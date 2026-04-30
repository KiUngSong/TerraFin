"""Weekly watchlist report — deterministic skeleton + bounded agent enrichment.

Pipeline:
1. Pull watchlist from `watchlist_service` (no HTTP).
2. For each ticker: yfinance (close + volume), compute WoW + intra-week >=4% events.
3. Google News RSS (after:/before: operators) for catalyst headlines.
4. Earnings calendar via yfinance.
5. Action wording driven by (anomaly_flag, has_headline, vol_ratio) decision tree.
6. Optional agent enrichment hook for cross-group / macro context (cheap LLM call,
   bounded prompt). Disabled by default to keep the report deterministic.

Anchors to a configurable as_of date so backtests reproduce exactly.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

log = logging.getLogger(__name__)

# Magnificent 7 fallback when the user hasn't connected a watchlist.
# Reports built from this list are explicitly labeled as a sample
# so the dashboard never silently presents M7 as the user's own list.
_M7_FALLBACK = [
    {"symbol": "AAPL", "name": "Apple Inc.", "tags": ["M7"]},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "tags": ["M7"]},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "tags": ["M7"]},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "tags": ["M7"]},
    {"symbol": "AMZN", "name": "Amazon.com, Inc.", "tags": ["M7"]},
    {"symbol": "META", "name": "Meta Platforms, Inc.", "tags": ["M7"]},
    {"symbol": "TSLA", "name": "Tesla, Inc.", "tags": ["M7"]},
]

_GENERIC_FIRST_WORDS = {
    "advanced", "american", "international", "global", "general", "national",
    "united", "first", "new", "the", "industries", "industrial", "applied",
    "electronic", "electric", "technologies", "consumer", "energy", "capital",
    "premier", "core", "alpha", "beta", "delta",
}

_GENERIC_SECOND_WORDS = {
    "inc", "corp", "ltd", "plc", "co", "company", "group", "holdings",
    "industries", "industrial", "international", "global", "technologies",
    "systems", "solutions", "partners",
}

# Tickers that are common English words. The ticker symbol itself is a noisy
# search term in news headlines, so we drop it from the relevance term set and
# require a company-name match instead. Add entries when a real watchlist
# member triggers obvious false positives.
_ENGLISH_WORD_TICKERS = {
    "ALL", "KEY", "ON", "IT", "WELL", "ARE", "FOR", "NOW", "BIG", "BEST",
    "GOOD", "OPEN", "LOW", "HIGH", "FAST", "EVER", "TRUE", "REAL", "NEW",
    "ONE", "TWO", "USA", "CAR", "PLAY", "LIFE", "WORK", "HOME", "SAFE",
}

# Brand names that differ from legal first word. Used as the primary news
# search term so headlines that mention the public-facing brand still match.
_BRAND_ALIASES = {
    "GOOGL": "Google",
    "GOOG": "Google",
    "META": "Meta",
    "BRK.B": "Berkshire",
    "BRK.A": "Berkshire",
}


@dataclass
class TickerReport:
    symbol: str
    name: str
    tags: list[str]
    wow: dict | None
    catalysts: list[dict]
    recent_earnings: dict | None
    days_to_earnings: int | None
    anomaly_flag: bool
    actions: list[str] = field(default_factory=list)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _last_completed_friday(now: datetime | None = None) -> date:
    """Return the most recently *completed* Friday close (US/Eastern).

    A weekly report anchored on a date `D` summarizes the trading week ending
    at `D`'s close. We want the most recent Friday whose 16:30 ET close has
    already happened. On any day Sat-Thu we take the prior Friday. On Friday
    itself we take today only if it's past the 16:30 close, else last Friday.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    except Exception:
        tz = timezone.utc
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    today = now.date()
    # weekday(): Mon=0 ... Fri=4 ... Sun=6
    days_since_fri = (today.weekday() - 4) % 7
    candidate = today - timedelta(days=days_since_fri)
    if candidate == today:
        close_dt = now.replace(hour=16, minute=30, second=0, microsecond=0)
        if now < close_dt:
            candidate = candidate - timedelta(days=7)
    return candidate


def _relevance_terms(ticker: str, name: str) -> set[str]:
    out: set[str] = set()
    if ticker.upper() not in _ENGLISH_WORD_TICKERS:
        out.add(ticker.lower())
    brand = _BRAND_ALIASES.get(ticker.upper())
    if brand:
        out.add(brand.lower())
    if name:
        words = [w.lower().strip(",.") for w in name.split()]
        if words and len(words[0]) >= 3 and words[0] not in _GENERIC_FIRST_WORDS:
            out.add(words[0])
        if len(words) >= 2:
            second = words[1]
            if len(second) >= 4 and second not in _GENERIC_SECOND_WORDS:
                out.add(second)
    return out


def _matches_relevance(title_lower: str, terms: set[str]) -> bool:
    """Whole-word match for short tokens to avoid substring collisions."""
    for term in terms:
        if len(term) <= 5:
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", title_lower):
                return True
        else:
            if term in title_lower:
                return True
    return False


def _fetch_market(ticker: str, as_of: date) -> list[dict]:
    """Fetch ~6 weeks ending as_of from yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    end = as_of + timedelta(days=1)  # yfinance end is exclusive
    start = as_of - timedelta(days=45)
    try:
        df = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
        )
    except Exception as exc:
        log.debug("yfinance history fail for %s: %s", ticker, exc)
        return []
    records = []
    for ts, row in df.iterrows():
        records.append({
            "time": ts.strftime("%Y-%m-%d"),
            "close": float(row["Close"]) if row["Close"] == row["Close"] else None,
            "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else None,
        })
    return [r for r in records if r["time"] <= as_of.isoformat()]


def _fetch_earnings(ticker: str) -> list[dict]:
    try:
        from TerraFin.interface.stock.payloads import build_earnings_payload
        payload = build_earnings_payload(ticker)
        return payload.get("earnings") or []
    except Exception as exc:
        log.debug("earnings fail for %s: %s", ticker, exc)
        return []


def _fetch_news_google(query: str, as_of: date, days: int = 8) -> list[dict]:
    after = (as_of - timedelta(days=days)).isoformat()
    before = (as_of + timedelta(days=1)).isoformat()
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {
            "q": f'"{query}" stock after:{after} before:{before}',
            "hl": "en-US", "gl": "US", "ceid": "US:en",
        }
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=10).read()
        root = ET.fromstring(data)
    except Exception as exc:
        log.debug("google news fail for %r: %s", query, exc)
        return []
    out = []
    for it in root.findall(".//item"):
        title = it.findtext("title")
        pub = it.findtext("pubDate")
        if not title or not pub:
            continue
        try:
            d = parsedate_to_datetime(pub).date()
        except Exception:
            continue
        out.append({"date": d.isoformat(), "title": title})
    return out


def _compute_wow(records: list[dict]) -> dict | None:
    closes = [(r["time"], r.get("close")) for r in records if r.get("close") is not None]
    if len(closes) < 6:
        return None
    last_date, last = closes[-1]
    week_date, week = closes[-6]
    pct = (last / week - 1.0) * 100.0
    return {
        "last_close": round(last, 2),
        "week_ago_close": round(week, 2),
        "wow_pct": round(pct, 2),
        "last_date": last_date,
        "week_ago_date": week_date,
    }


def _detect_events(records: list[dict], threshold_pct: float = 4.0) -> list[dict]:
    rows = [
        (r["time"], r.get("close"), r.get("volume"))
        for r in records
        if r.get("close") is not None
    ]
    events = []
    for i in range(max(1, len(rows) - 5), len(rows)):
        _, prev_close, _ = rows[i - 1]
        date_str, cur_close, vol = rows[i]
        if not prev_close or not cur_close:
            continue
        move = (cur_close / prev_close - 1.0) * 100.0
        if abs(move) < threshold_pct:
            continue
        vol_ratio = None
        if vol:
            window = [r[2] for r in rows[max(0, i - 20):i] if r[2]]
            if window:
                avg = sum(window) / len(window)
                if avg:
                    vol_ratio = round(vol / avg, 2)
        events.append({"date": date_str, "move_pct": round(move, 2), "vol_ratio": vol_ratio})
    return events


def _attribute(events: list[dict], news: list[dict], ticker: str, name: str, days_window: int = 1) -> list[dict]:
    terms = _relevance_terms(ticker, name)
    out = []
    for ev in events:
        ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        matches: list[str] = []
        seen: set[str] = set()
        for n in news:
            n_date = datetime.strptime(n["date"], "%Y-%m-%d").date()
            if abs((n_date - ev_date).days) > days_window:
                continue
            title = n["title"]
            tlow = title.lower()
            if not _matches_relevance(tlow, terms):
                continue
            key = tlow[:60]
            if key in seen:
                continue
            seen.add(key)
            matches.append(title)
        out.append({
            "date": ev["date"],
            "move_pct": ev["move_pct"],
            "vol_ratio": ev.get("vol_ratio"),
            "headlines": matches[:3],
        })
    return out


def _action_signal(t: TickerReport) -> list[str]:
    notes: list[str] = []
    pct = (t.wow or {}).get("wow_pct", 0)
    dominant = max(t.catalysts, key=lambda c: abs(c.get("move_pct", 0)), default=None)
    dom_vol = dominant.get("vol_ratio") if dominant else None
    has_headline = bool(dominant and dominant.get("headlines"))

    if t.anomaly_flag:
        if has_headline:
            notes.append("⚠ outsized weekly move — catalyst named, size into earnings if thesis intact")
        else:
            notes.append("⚠ outsized weekly move — no headline match, dig before adding")
    elif pct >= 8:
        if has_headline:
            notes.append("up week with named catalyst — consider trim or trail stop")
        elif dom_vol and dom_vol >= 1.5:
            notes.append("strong tape on heavy volume but no headline — verify cause")
        else:
            notes.append("up week on tepid volume + no headline — momentum unconfirmed")
    elif pct <= -8:
        if has_headline:
            notes.append("down week with named catalyst — re-test thesis before adding")
        elif dom_vol and dom_vol >= 1.5:
            notes.append("breakdown on heavy volume but no headline — verify cause")
        else:
            notes.append("down week on thin volume + no headline — drift, not breakdown")
    return notes


def _days_until(date_str: str, as_of: date) -> int | None:
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    return (target - as_of).days


def _build_ticker(item: dict, as_of: date) -> TickerReport:
    sym = item["symbol"]
    name = item.get("name") or sym
    records = _fetch_market(sym, as_of)
    wow = _compute_wow(records)
    events = _detect_events(records)
    brand = _BRAND_ALIASES.get(sym.upper())
    primary = brand or (name.split()[0] if name else sym)
    news = _fetch_news_google(primary, as_of)
    if brand and len(news) < 10:
        legal_first = name.split()[0] if name else ""
        if legal_first and legal_first.lower() != brand.lower():
            news.extend(_fetch_news_google(legal_first, as_of))
    if sym.upper() not in _ENGLISH_WORD_TICKERS and len(news) < 10:
        news.extend(_fetch_news_google(sym, as_of))
    catalysts = _attribute(events, news, sym, name)
    earnings_list = _fetch_earnings(sym)
    earn_recent = None
    days_to = None
    if earnings_list:
        future = [r for r in earnings_list if r.get("date") and r["date"] >= as_of.isoformat()]
        future.sort(key=lambda r: r["date"])
        if future:
            earn_recent = future[0]
            days_to = _days_until(earn_recent.get("date", ""), as_of)
    t = TickerReport(
        symbol=sym,
        name=name,
        tags=item.get("tags") or [],
        wow=wow,
        catalysts=catalysts,
        recent_earnings=earn_recent,
        days_to_earnings=days_to,
        anomaly_flag=bool(wow and abs(wow["wow_pct"]) >= 15.0),
    )
    t.actions = _action_signal(t)
    return t


def _render(tickers: list[TickerReport], as_of: date, is_sample: bool = False) -> str:
    by_group: dict[str, list[TickerReport]] = {}
    for t in tickers:
        for tag in t.tags or ["Untagged"]:
            by_group.setdefault(tag, []).append(t)

    title_suffix = " — Sample (M7)" if is_sample else ""
    lines = [f"# Weekly Watchlist Report — {as_of.isoformat()}{title_suffix}"]
    if is_sample:
        lines.append(
            "> ⚡ **This is a sample report.** Connect your watchlist via MongoDB "
            "(`TERRAFIN_MONGODB_URI`) to see your tickers and groups here instead."
        )
    lines.append(
        "*WoW = 5-trading-day close-to-close. ⚠ = |WoW| ≥ 15%. "
        "Headlines matched within ±1 day of intra-week ≥4% moves, "
        "filtered to ticker/company relevance.*"
    )
    lines.append("")
    for group, members in by_group.items():
        lines.append(f"## {group}")
        for t in members:
            lines.append(_render_ticker(t))
        lines.append("")

    movers = sorted(
        [t for t in tickers if t.wow],
        key=lambda t: abs(t.wow["wow_pct"]),
        reverse=True,
    )
    biggest = movers[0] if movers else None
    earn_7d = sorted(
        [t for t in tickers if t.days_to_earnings is not None and 0 <= t.days_to_earnings <= 7],
        key=lambda t: t.days_to_earnings,
    )
    upcoming = sorted(
        [t for t in tickers if t.days_to_earnings is not None and t.days_to_earnings >= 0],
        key=lambda t: t.days_to_earnings,
    )

    lines.append("## This Week")
    if biggest:
        tail = " ⚠" if biggest.anomaly_flag else ""
        lines.append(f"- Biggest mover: **{biggest.symbol}** {biggest.wow['wow_pct']:+.2f}%{tail}")
    if earn_7d:
        names = ", ".join(f"{t.symbol} ({t.days_to_earnings}d)" for t in earn_7d)
        lines.append(f"- Earnings ≤7d (decide hold vs trim into print): {names}")
    elif upcoming:
        nxt = upcoming[0]
        lines.append(
            f"- Next catalyst: **{nxt.symbol}** earnings in {nxt.days_to_earnings}d "
            f"({nxt.recent_earnings.get('date','?')}, est {nxt.recent_earnings.get('epsEstimate','?')})"
        )
    avgs: dict[str, float] = {}
    for group, members in by_group.items():
        pcts = [t.wow["wow_pct"] for t in members if t.wow]
        if pcts:
            avgs[group] = sum(pcts) / len(pcts)
    if avgs:
        ranked = sorted(avgs.items(), key=lambda x: x[1], reverse=True)
        lines.append("- Group avg WoW: " + ", ".join(f"{g} {p:+.2f}%" for g, p in ranked))

    if is_sample:
        # Concrete diff CTA — instead of generic "connect your watchlist," call out
        # which sample-only sections would become personal once connected. DA review
        # flagged "see M7 → connect" as weak; the punchier version is showing what
        # changes with your own list.
        lines.append("")
        lines.append("## Make this yours")
        lines.append(
            f"- The week's biggest mover ({biggest.symbol if biggest else '—'} "
            f"{biggest.wow['wow_pct']:+.2f}%) might not be on your radar. With your "
            "watchlist connected, this section spotlights moves on **your tickers** instead."
        )
        if earn_7d:
            ec_names = ", ".join(f"{t.symbol} ({t.days_to_earnings}d)" for t in earn_7d)
            lines.append(
                f"- This week's earnings calendar ({ec_names}) is M7-only. Yours would "
                "surface the print dates that actually move your P&L."
            )
        lines.append(
            "- **Connect**: open the [Watchlist tab](/watchlist) and add tickers. "
            "Next Friday's report uses your list automatically."
        )
    return "\n".join(lines)


def _render_ticker(t: TickerReport) -> str:
    if not t.wow:
        return f"- **{t.symbol}** — insufficient data\n"
    pct = t.wow["wow_pct"]
    flag = " ⚠" if t.anomaly_flag else ""
    out = [
        f"- **{t.symbol}**{flag} — WoW: {pct:+.2f}% — {t.wow['last_close']} vs {t.wow['week_ago_close']} "
        f"({t.wow['week_ago_date']} → {t.wow['last_date']})"
    ]
    for c in t.catalysts:
        sign = "+" if c["move_pct"] > 0 else ""
        vol = c.get("vol_ratio")
        vol_part = f" [vol {vol}x avg]" if vol else ""
        if c["headlines"]:
            tail = " | " + "; ".join(f'"{h}"' for h in c["headlines"][:2])
        else:
            tail = " | no headline match — verify cause"
        out.append(f"  - {c['date']} ({sign}{c['move_pct']:.2f}%){vol_part}{tail}")
    if t.recent_earnings and t.days_to_earnings is not None:
        when = f"in {t.days_to_earnings}d" if t.days_to_earnings >= 0 else "past"
        est = t.recent_earnings.get("epsEstimate", "?")
        rep = t.recent_earnings.get("epsReported", "-")
        rep_part = f", reported {rep}" if rep and rep != "-" else ""
        out.append(f"  - Earnings {when} ({t.recent_earnings.get('date','?')}) — est {est}{rep_part}")
    if t.actions:
        out.append(f"  - **Action**: {'; '.join(t.actions)}")
    return "\n".join(out) + "\n"


def build_weekly_report(
    as_of: date | None = None,
    persist: bool = True,
    enrich: bool = True,
) -> str:
    """Return the markdown weekly report.

    Falls back to Magnificent 7 when the watchlist is empty / unavailable so
    a fresh-install user gets a non-trivial report on day one. Sample reports
    are explicitly labeled in the header. By default persists to
    ~/.terrafin/reports/weekly so the dashboard can render history. When the
    TerraFin agent runtime is configured, an additional enrichment section is
    appended (macro/index context with tool-call provenance).
    """
    anchor = as_of or _last_completed_friday()
    items, is_sample = _resolve_universe()
    tickers = [_build_ticker(it, anchor) for it in items]
    md = _render(tickers, anchor, is_sample=is_sample)
    if enrich:
        try:
            from .enrichment import render_enrichment_section
            summary = [
                {
                    "symbol": t.symbol,
                    "name": t.name,
                    "tags": t.tags,
                    "wow_pct": (t.wow or {}).get("wow_pct"),
                    "intra_week_events": [
                        {
                            "date": c["date"],
                            "move_pct": c["move_pct"],
                            "vol_ratio": c.get("vol_ratio"),
                            "unattributed": not c.get("headlines"),
                        }
                        for c in t.catalysts
                    ],
                }
                for t in tickers
            ]
            extra = render_enrichment_section(summary, anchor)
            if extra:
                md = md + extra
        except Exception:
            log.exception("agent enrichment failed; serving deterministic report only")
    if persist:
        try:
            from .storage import save_report
            save_report(anchor, md, is_sample=is_sample, universe=[t["symbol"] for t in items])
        except Exception:
            log.exception("failed to persist weekly report for %s", anchor)
    return md


def _resolve_universe() -> tuple[list[dict], bool]:
    try:
        from TerraFin.interface.watchlist_service import get_watchlist_service
        snapshot = get_watchlist_service().get_watchlist_snapshot() or []
    except Exception as exc:
        log.debug("watchlist unavailable: %s", exc)
        snapshot = []
    if snapshot:
        return list(snapshot), False
    return list(_M7_FALLBACK), True
