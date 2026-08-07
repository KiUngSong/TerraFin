"""Forward consensus estimates from yfinance.

Sits beside `ticker_info` (which owns `.info` and `.earnings_dates`) rather than
inside it, because this pulls four separate yfinance surfaces and shapes them
into one contract. Cached like its neighbours: a day is plenty, since consensus
moves on analyst notes, not intraday.
"""

import logging
import threading
import time
from datetime import date
from typing import Any

from TerraFin.data.cache.policy import ttl_for
from TerraFin.data.contracts.estimates import (
    PERIOD_KEYS,
    ConsensusEstimates,
    PeriodEstimate,
    PriceTargets,
    RevisionCounts,
)


log = logging.getLogger(__name__)


class EstimatesUnavailableError(RuntimeError):
    """Raised when no estimate surface returned data.

    Deliberately does NOT claim to know why. "Upstream gave us nothing" and
    "this symbol has no estimates" are identical in yfinance's output, so the
    point of raising is to keep an unknowable verdict out of the cache.
    """


_SOURCE_PREFIX = "market.estimates"
_NS = "market.estimates"

# An all-empty response is never written to the file cache — it is unknowable
# whether the symbol has no estimates or the endpoint is down, and a stored
# verdict would be wrong for a full TTL. But the OBSERVATION ("at T, every
# surface came back empty") is a fact, and remembering it briefly is what stops
# a repeatedly-queried index from re-hitting five endpoints on every call.
#
# In memory only, so a restart clears it, and short enough that a transient
# rate-limit self-heals: the outage case and the genuine-no-estimates case are
# indistinguishable, so the worse one sets the horizon.
_EMPTY_MEMO_SECONDS = 300
_MAX_EMPTY_MEMOS = 256
_empty_observations: dict[str, tuple[float, str]] = {}
_memo_mutex = threading.Lock()


def _recent_empty(ticker: str) -> str | None:
    """A remembered all-empty observation, phrased so it cannot read as fresh."""
    with _memo_mutex:
        entry = _empty_observations.get(ticker)
        if entry is None:
            return None
        deadline, observed_at = entry
        now = time.monotonic()
        if now >= deadline:
            del _empty_observations[ticker]
            return None
        age = int(_EMPTY_MEMO_SECONDS - (deadline - now))
    return (
        f"not retried: every estimate surface was empty {age}s ago (at {observed_at}) and that "
        f"observation is remembered for {_EMPTY_MEMO_SECONDS}s; pass force_refresh to retry now"
    )


def _remember_empty(ticker: str) -> None:
    with _memo_mutex:
        if len(_empty_observations) >= _MAX_EMPTY_MEMOS:
            now = time.monotonic()
            for stale in [t for t, (deadline, _) in _empty_observations.items() if now >= deadline]:
                del _empty_observations[stale]
            if len(_empty_observations) >= _MAX_EMPTY_MEMOS:
                _empty_observations.clear()
        _empty_observations[ticker] = (
            time.monotonic() + _EMPTY_MEMO_SECONDS,
            date.today().isoformat(),
        )


def clear_empty_memo() -> None:
    """Forget remembered all-empty observations (process-local)."""
    with _memo_mutex:
        _empty_observations.clear()


def _manager():
    from TerraFin.data.cache import get_cache_manager

    return get_cache_manager()


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result  # drop NaN


def _safe_int(value) -> int | None:
    result = _safe_float(value)
    return None if result is None else int(result)


def _jsonable(value):
    """Coerce a numpy/pandas scalar to a JSON-safe primitive."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return None if isinstance(value, float) and value != value else value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonable(item())
        except (ValueError, TypeError):
            return None
    return str(value)


def _frame_to_period_map(frame) -> dict[str, dict]:
    """{period: {column: primitive}} — JSON-safe, indexed by period label."""
    if frame is None or getattr(frame, "empty", True):
        return {}
    out: dict[str, dict] = {}
    for period in frame.index:
        out[str(period)] = {str(col): _jsonable(frame.loc[period, col]) for col in frame.columns}
    return out


def _frame_to_records(frame) -> list[dict]:
    """[{column: primitive}] — JSON-safe row records."""
    if frame is None or getattr(frame, "empty", True):
        return []
    return [{str(col): _jsonable(row[col]) for col in frame.columns} for _, row in frame.iterrows()]


def _first_present(row: dict, *keys: str):
    """First key actually present in `row`, tolerating a falsy value.

    `row.get(a) or row.get(b)` cannot be used here: 0 is a legitimate revision
    count (zero analysts revised up) and would fall through to the alternate
    spelling, yielding None.
    """
    for key in keys:
        if key in row:
            return row[key]
    return None


def _row(period_map, period: str) -> dict:
    """One period's row from an already-normalised map, or {} when absent."""
    if not isinstance(period_map, dict):
        return {}
    row = period_map.get(period)
    return dict(row) if isinstance(row, dict) else {}


def _fetch_raw(ticker: str) -> dict[str, Any]:
    """Pull the four yfinance surfaces, tolerating any one of them failing.

    Each surface is fetched independently so a ticker with price targets but no
    revision data still yields the half that exists.
    """
    import yfinance as yf

    obj = yf.Ticker(ticker)
    raw: dict[str, Any] = {"warnings": [], "fetchedAt": date.today().isoformat()}
    for key, attr in (
        ("eps", "earnings_estimate"),
        ("revenue", "revenue_estimate"),
        ("revisions", "eps_revisions"),
        ("targets", "analyst_price_targets"),
        ("recommendations", "recommendations"),
    ):
        try:
            value = getattr(obj, attr)
            if key == "targets":
                raw[key] = {str(k): _jsonable(v) for k, v in (value or {}).items()}
            elif key == "recommendations":
                raw[key] = _frame_to_records(value)
            else:
                raw[key] = _frame_to_period_map(value)
        except Exception as exc:  # noqa: BLE001 - upstream raises many shapes
            log.debug("estimates: %s.%s failed: %s", ticker, attr, exc)
            raw["warnings"].append(f"{attr} unavailable")
            raw[key] = None
            continue

    # yfinance runs with hide_exceptions=True, and its quoteSummary fetch turns
    # an HTTP 401/429/404 into `None` (analysis.py:190) which becomes an EMPTY
    # frame, not an exception (analysis.py:200-204). So the per-surface handler
    # above never fires for the dominant failure, and an all-empty result is
    # indistinguishable from a symbol that genuinely has no estimates.
    #
    # Earlier attempts tried to tell the two apart with a probe. Both were wrong:
    # `valid_ticker` asks the v8 chart endpoint, and `get_ticker_info` falls back
    # to the chart endpoint AND the query2 search endpoint precisely so it keeps
    # working when quoteSummary is down (see its docstring). Neither shares a
    # failure domain with the estimate surfaces, so neither can detect the
    # outage — and a wrong verdict would then be cached for the full TTL.
    #
    # So: never cache an all-empty result. Raise, and let the caller describe the
    # ambiguity honestly. `quoteType` is attached by the fallback path purely as
    # a labelled hint, never as a verdict.
    estimate_surfaces = {
        "eps": raw.get("eps"),
        "revenue": raw.get("revenue"),
        "revisions": raw.get("revisions"),
    }
    if not any((*estimate_surfaces.values(), raw.get("targets"), raw.get("recommendations"))):
        raise EstimatesUnavailableError(
            f"no estimate surface returned data for {ticker} — this is either a symbol without "
            "analyst estimates or an upstream failure, and the two are indistinguishable here"
        )

    if not any(estimate_surfaces.values()):
        raw["estimatesMissing"] = True
        raw["warnings"].append(
            "every estimate surface (eps, revenue, revisions) returned no data while other "
            "surfaces responded — either an uncovered symbol or a partial upstream failure"
        )
    else:
        empty = [name for name, value in estimate_surfaces.items() if not value]
        if empty:
            raw["warnings"].append(
                f"these estimate surfaces returned no data: {', '.join(empty)} "
                "(upstream reports an empty result rather than an error, so a partial "
                "failure is indistinguishable from genuinely absent data)"
            )
    return raw


def _shape(
    ticker: str,
    raw: dict[str, Any],
    as_of: str,
    *,
    cache_tier: str | None = None,
    upstream_failed: bool = False,
    quote_type_hint: str | None = None,
) -> ConsensusEstimates:
    eps_map = raw.get("eps")
    rev_map = raw.get("revenue")
    revisions_map = raw.get("revisions")
    targets = raw.get("targets") or {}

    currency = None
    for period_map in (eps_map, rev_map):
        row = _row(period_map, PERIOD_KEYS[0])
        if row.get("currency"):
            currency = str(row["currency"])
            break

    eps: list[PeriodEstimate] = []
    revenue: list[PeriodEstimate] = []
    revisions: list[RevisionCounts] = []
    for period in PERIOD_KEYS:
        eps_row = _row(eps_map, period)
        if eps_row:
            eps.append(
                PeriodEstimate(
                    period=period,
                    avg=_safe_float(eps_row.get("avg")),
                    low=_safe_float(eps_row.get("low")),
                    high=_safe_float(eps_row.get("high")),
                    analyst_count=_safe_int(eps_row.get("numberOfAnalysts")),
                    growth=_safe_float(eps_row.get("growth")),
                    year_ago=_safe_float(eps_row.get("yearAgoEps")),
                )
            )
        rev_row = _row(rev_map, period)
        if rev_row:
            revenue.append(
                PeriodEstimate(
                    period=period,
                    avg=_safe_float(rev_row.get("avg")),
                    low=_safe_float(rev_row.get("low")),
                    high=_safe_float(rev_row.get("high")),
                    analyst_count=_safe_int(rev_row.get("numberOfAnalysts")),
                    growth=_safe_float(rev_row.get("growth")),
                    year_ago=_safe_float(rev_row.get("yearAgoRevenue")),
                )
            )
        rv_row = _row(revisions_map, period)
        if rv_row:
            revisions.append(
                RevisionCounts(
                    period=period,
                    # Upstream casing is inconsistent — the live column is
                    # "downLast7Days" (capital D) while yfinance's own docstring
                    # says "downLast7days". Accept either so a flip does not
                    # silently zero the field.
                    up_7d=_safe_int(_first_present(rv_row, "upLast7days", "upLast7Days")),
                    down_7d=_safe_int(_first_present(rv_row, "downLast7Days", "downLast7days")),
                    up_30d=_safe_int(_first_present(rv_row, "upLast30days", "upLast30Days")),
                    down_30d=_safe_int(_first_present(rv_row, "downLast30days", "downLast30Days")),
                )
            )

    recommendations: list[dict] = []
    for row in raw.get("recommendations") or []:
        recommendations.append(
            {
                "period": str(row.get("period", "")),
                "strongBuy": _safe_int(row.get("strongBuy")),
                "buy": _safe_int(row.get("buy")),
                "hold": _safe_int(row.get("hold")),
                "sell": _safe_int(row.get("sell")),
                "strongSell": _safe_int(row.get("strongSell")),
            }
        )

    return ConsensusEstimates(
        ticker=ticker,
        as_of=as_of,
        currency=currency,
        eps=tuple(eps),
        revenue=tuple(revenue),
        revisions=tuple(revisions),
        price_targets=PriceTargets(
            current=_safe_float(targets.get("current")),
            mean=_safe_float(targets.get("mean")),
            median=_safe_float(targets.get("median")),
            low=_safe_float(targets.get("low")),
            high=_safe_float(targets.get("high")),
        ),
        recommendations=tuple(recommendations),
        upstream_failed=upstream_failed,
        estimates_missing=bool(raw.get("estimatesMissing")),
        quote_type_hint=quote_type_hint,
        cache_tier=cache_tier,
        warnings=tuple(raw.get("warnings") or ()),
    )


def _quote_type_hint(ticker: str) -> str | None:
    """Best-effort instrument type, for context only.

    Deliberately a hint: it comes from `get_ticker_info`, which recovers via the
    chart and search endpoints when quoteSummary is down, so its presence says
    nothing about whether the estimate surfaces really are empty.
    """
    try:
        from TerraFin.data.providers.market.ticker_info import get_ticker_info

        info = get_ticker_info(ticker)
    except Exception:  # noqa: BLE001 - a hint is never worth failing over
        return None
    quote_type = str((info or {}).get("quoteType") or "").upper()
    return quote_type or None


def _ensure_source(ticker: str) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec

    source = f"{_SOURCE_PREFIX}.{ticker}"
    manager = _manager()
    if source not in manager._payload_specs:
        manager.register_payload(
            CachePayloadSpec(
                source=source,
                namespace=_NS,
                key=ticker,
                ttl_seconds=ttl_for("market.estimates"),
                fetch_fn=lambda t=ticker: _fetch_raw(t),
                # Serve an empty shape on a transient upstream block so callers
                # render; the fallback path is not cached, so the next request
                # retries the real fetch.
                # Reached only after the fetch raised and no stale copy exists.
                # `upstreamFailed` lets the caller avoid reporting this as
                # "no analyst coverage"; the quote-type hint is best-effort
                # context, deliberately not a verdict.
                # Deliberately cheap and I/O-free: CacheManager calls this inside
                # its per-source fetch lock. The quote-type hint is computed by
                # the caller after the fact instead.
                fallback_fn=lambda: {
                    "warnings": ["estimates upstream returned nothing"],
                    "upstreamFailed": True,
                },
            )
        )
    return source


def get_consensus_estimates(ticker: str, *, force_refresh: bool = False) -> ConsensusEstimates:
    """Forward consensus for one ticker.

    Returns a contract rather than raising when nothing came back: `has_coverage`
    is False and `upstream_failed` says the reason is unknowable. An all-empty
    response is never cached, but it IS remembered in memory for
    `_EMPTY_MEMO_SECONDS` so a repeatedly-queried index does not re-hit upstream
    every call. `force_refresh=True` bypasses that memo.
    """
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("Ticker is required")

    if not force_refresh:
        remembered = _recent_empty(normalized)
        if remembered is not None:
            return _shape(
                normalized,
                {"warnings": [remembered]},
                "",
                cache_tier="fallback",
                upstream_failed=True,
                quote_type_hint=_quote_type_hint(normalized),
            )

    source = _ensure_source(normalized)
    result = _manager().get_payload(source, force_refresh=force_refresh)
    payload = dict(result.payload or {})
    # CachePayloadResult carries no timestamp, so the fetch date is stamped into
    # the payload by `_fetch_raw` and travels with it through the cache.
    as_of = str(payload.get("fetchedAt") or "")
    upstream_failed = bool(payload.get("upstreamFailed"))

    hint = None
    if upstream_failed:
        # Remember the observation so the next call is cheap, and attach the
        # instrument-type hint here rather than in `fallback_fn`.
        _remember_empty(normalized)
        hint = _quote_type_hint(normalized)

    return _shape(
        normalized,
        payload,
        as_of,
        cache_tier=result.freshness,
        upstream_failed=upstream_failed,
        quote_type_hint=hint,
    )


def clear_estimates_cache() -> None:
    """Drop cached estimates. Registered in `data/cache/registry.py`."""
    from TerraFin.data.cache.manager import CacheManager

    manager = _manager()
    # Registered specs hold in-memory copies for tickers touched this process.
    # `.copy()` snapshots atomically: iterating the live dict can raise
    # "dictionary changed size during iteration" when a worker thread registers
    # a new ticker mid-sweep, which would skip the rest of the clear.
    for source in [s for s in manager._payload_specs.copy() if s.startswith(f"{_SOURCE_PREFIX}.")]:
        manager.clear_payload(source)
    # ...and the namespace tree holds every ticker ever fetched, including by
    # earlier processes.
    CacheManager.file_cache_remove_tree(_NS)
