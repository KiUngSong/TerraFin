"""Holes inside a downloaded frame, which no consumer could previously see.

yfinance returns no bar for QCOM on 2026-08-28 — a session NVDA traded 195M
shares in. The frame it hands back is contiguous to anyone without the exchange
calendar, so an N-session return taken by position silently spans the gap.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from TerraFin.data.providers.market.sessions import missing_sessions, prev_session


_CLEAN = ["2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31"]
_HOLE = ["2026-08-25", "2026-08-26", "2026-08-27", "2026-08-31"]


def test_a_dropped_session_is_reported():
    assert missing_sessions(_HOLE, "QCOM") == ("2026-08-28",)


def test_a_complete_frame_reports_nothing():
    assert missing_sessions(_CLEAN, "NVDA") == ()


def test_a_holiday_is_not_a_hole():
    """Holiday-naive detection would fire ~9 times a year and drown the signal.
    2026-07-03 is the observed Independence Day holiday, not a missing bar."""
    assert missing_sessions(["2026-07-02", "2026-07-06"], "AAPL") == ()


def test_only_holes_inside_the_frame_count():
    """A short window is not a hole: the range is bounded by the frame's own
    first and last date, so callers asking for less history are not warned."""
    assert missing_sessions(["2026-08-27", "2026-08-28"], "NVDA") == ()
