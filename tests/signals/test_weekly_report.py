"""Tests for the weekly report pipeline.

Network calls (yfinance, Google News RSS, agent runtime) are mocked so the
suite runs offline. Focus is on the deterministic skeleton: WoW math, event
detection, headline attribution, action wording, render shape, and the M7
fallback path.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from TerraFin.signals.reports.weekly import (
    TickerReport,
    _M7_FALLBACK,
    _action_signal,
    _attribute,
    _compute_wow,
    _detect_events,
    _matches_relevance,
    _relevance_terms,
    _render,
    _resolve_universe,
)


# ---------------------------------------------------------------------------
# Universe resolution
# ---------------------------------------------------------------------------


def test_resolve_universe_uses_watchlist_when_present():
    fake = [{"symbol": "AAPL", "name": "Apple Inc.", "tags": ["Tech"]}]

    class _Service:
        def get_watchlist_snapshot(self):
            return fake

    with patch(
        "TerraFin.interface.watchlist_service.get_watchlist_service",
        return_value=_Service(),
    ):
        items, is_sample = _resolve_universe()

    assert items == fake
    assert is_sample is False


def test_resolve_universe_falls_back_to_m7():
    class _Service:
        def get_watchlist_snapshot(self):
            return []

    with patch(
        "TerraFin.interface.watchlist_service.get_watchlist_service",
        return_value=_Service(),
    ):
        items, is_sample = _resolve_universe()

    assert is_sample is True
    assert items == _M7_FALLBACK
    assert {t["symbol"] for t in items} == {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"}


# ---------------------------------------------------------------------------
# Numerical primitives
# ---------------------------------------------------------------------------


def test_compute_wow_requires_six_closes():
    short = [{"time": f"2026-04-{d:02d}", "close": 100 + d} for d in (20, 21, 22)]
    assert _compute_wow(short) is None


def test_compute_wow_uses_5_trading_day_window():
    closes = [
        {"time": "2026-04-21", "close": 100.0},
        {"time": "2026-04-22", "close": 102.0},
        {"time": "2026-04-23", "close": 101.0},
        {"time": "2026-04-24", "close": 103.0},
        {"time": "2026-04-25", "close": 105.0},
        {"time": "2026-04-28", "close": 110.0},
    ]
    wow = _compute_wow(closes)
    assert wow is not None
    assert wow["last_close"] == 110.0
    assert wow["week_ago_close"] == 100.0
    assert wow["wow_pct"] == 10.0


def test_detect_events_skips_below_threshold_and_attaches_volume():
    rows = [
        # 21-day baseline so the 20-day rolling avg has data
        *[
            {"time": f"2026-03-{d:02d}", "close": 100.0, "volume": 1_000_000}
            for d in range(1, 22)
        ],
        {"time": "2026-04-22", "close": 100.0, "volume": 1_000_000},
        {"time": "2026-04-23", "close": 100.5, "volume": 1_000_000},  # <4% noise
        {"time": "2026-04-24", "close": 105.0, "volume": 3_000_000},  # +4.5% on 3x vol
        {"time": "2026-04-25", "close": 104.0, "volume": 1_000_000},
        {"time": "2026-04-28", "close": 95.0, "volume": 2_000_000},   # -8.7%
    ]
    events = _detect_events(rows, threshold_pct=4.0)
    dates = {e["date"] for e in events}
    assert "2026-04-23" not in dates  # under threshold
    assert "2026-04-24" in dates
    assert "2026-04-28" in dates
    e_24 = next(e for e in events if e["date"] == "2026-04-24")
    assert e_24["vol_ratio"] is not None
    assert e_24["vol_ratio"] > 2.0  # ~3x avg


# ---------------------------------------------------------------------------
# Headline attribution
# ---------------------------------------------------------------------------


def test_relevance_terms_drops_generic_first_word():
    # "Advanced" is too generic — only the ticker + second word should anchor.
    terms = _relevance_terms("AMD", "Advanced Micro Devices, Inc.")
    assert "amd" in terms
    assert "micro" in terms
    assert "advanced" not in terms


def test_relevance_terms_drops_english_word_ticker():
    # "ALL" (Allstate) is a common English word — drop the ticker token,
    # rely on company name instead.
    terms = _relevance_terms("ALL", "The Allstate Corporation")
    assert "all" not in terms
    assert "allstate" in terms


def test_relevance_terms_uses_brand_alias_for_googl():
    terms = _relevance_terms("GOOGL", "Alphabet Inc.")
    assert "google" in terms
    assert "alphabet" in terms


def test_matches_relevance_uses_word_boundary_for_short_tokens():
    terms = {"amd"}
    # "iSCIB1+" looks dangerous but doesn't actually contain "amd"; an
    # earlier bug let "advanced" substring-match.
    assert _matches_relevance("iscib1+ receives fda fast track", terms) is False
    assert _matches_relevance("amd stock jumps", terms) is True
    assert _matches_relevance("scrambled eggs", terms) is False  # not amd in 'scrambled'


def test_attribute_filters_irrelevant_news_within_window():
    events = [{"date": "2026-04-24", "move_pct": 13.91, "vol_ratio": 2.21}]
    news = [
        # In window + relevant
        {"date": "2026-04-24", "title": "AMD jumps after Intel results"},
        # In window + irrelevant
        {"date": "2026-04-24", "title": "Apple closes record high"},
        # Out of window
        {"date": "2026-04-15", "title": "AMD prior-week update"},
    ]
    attributed = _attribute(events, news, "AMD", "Advanced Micro Devices")
    assert len(attributed) == 1
    headlines = attributed[0]["headlines"]
    assert any("AMD jumps" in h for h in headlines)
    assert all("Apple" not in h for h in headlines)


# ---------------------------------------------------------------------------
# Action wording — the (anomaly, headline, vol) decision tree
# ---------------------------------------------------------------------------


def _ticker(
    *,
    wow_pct: float,
    anomaly: bool = False,
    catalysts: list[dict] | None = None,
) -> TickerReport:
    return TickerReport(
        symbol="X",
        name="X Co.",
        tags=["G"],
        wow={
            "last_close": 100,
            "week_ago_close": 100 - wow_pct,
            "wow_pct": wow_pct,
            "last_date": "2026-04-29",
            "week_ago_date": "2026-04-22",
        },
        catalysts=catalysts or [],
        recent_earnings=None,
        days_to_earnings=None,
        anomaly_flag=anomaly,
    )


def test_action_anomaly_with_headline():
    t = _ticker(
        wow_pct=28.4,
        anomaly=True,
        catalysts=[{"date": "2026-04-23", "move_pct": 14.0, "vol_ratio": 3.0, "headlines": ["beat est"]}],
    )
    notes = _action_signal(t)
    assert any("catalyst named" in n for n in notes)


def test_action_anomaly_without_headline():
    t = _ticker(
        wow_pct=28.4,
        anomaly=True,
        catalysts=[{"date": "2026-04-23", "move_pct": 14.0, "vol_ratio": 3.0, "headlines": []}],
    )
    notes = _action_signal(t)
    assert any("dig before adding" in n for n in notes)


def test_action_breakdown_thin_volume_no_headline_is_drift():
    t = _ticker(
        wow_pct=-9.0,
        catalysts=[{"date": "2026-04-23", "move_pct": -7.0, "vol_ratio": 0.9, "headlines": []}],
    )
    notes = _action_signal(t)
    assert any("drift" in n for n in notes)


def test_action_below_threshold_no_note():
    t = _ticker(wow_pct=2.5)
    assert _action_signal(t) == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_marks_sample_in_header_and_footer():
    tickers = [_ticker(wow_pct=1.0)]
    md = _render(tickers, date(2026, 4, 30), is_sample=True)
    assert "Sample (M7)" in md
    assert "## Make this yours" in md
    assert "/watchlist" in md  # CTA link to dashboard


def test_render_personal_report_omits_sample_cta():
    tickers = [_ticker(wow_pct=1.0)]
    md = _render(tickers, date(2026, 4, 30), is_sample=False)
    assert "Sample" not in md
    assert "Make this yours" not in md


def test_render_anomaly_flag_in_biggest_mover_line():
    big = _ticker(wow_pct=28.4, anomaly=True)
    md = _render([big], date(2026, 4, 30), is_sample=False)
    assert "Biggest mover" in md
    # Anomaly flag must show in the footer summary (rendering uses ⚠)
    assert "⚠" in md
