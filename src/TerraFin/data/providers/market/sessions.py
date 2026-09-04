"""Exchange sessions: which ones a frame is missing, and which one came before.

Detection only: a dropped row cannot be recovered here, so the contract is to
say what is missing and let the caller decide.

Separate from `session_calendar`, which is holiday-naive because it only answers
"should a newer bar exist by now". These answers accept or reject data.
"""

import logging
from datetime import date, timedelta

from .session_calendar import (
    _CRYPTO_QUOTE_SUFFIXES,
    _KRX_NUMERIC,
    _SUFFIX_EXCHANGE,
    KRX,
    NYSE,
    resolve_exchange,
)


log = logging.getLogger(__name__)

# ExchangeSchedule.name -> exchange_calendars code. Anything absent lands on
# `None` (unknown), never on a false "clean".
_CAL_CODES = {NYSE.name: "XNYS", KRX.name: "XKRX"}

# Successful calendars only: caching a failure would disarm every caller for the
# life of the process.
_CAL_CACHE: dict[str, object] = {}
_WARNED: set[str] = set()


def unavailable_calendars() -> tuple[str, ...]:
    """Calendar codes that are NOT currently loadable.

    Derived from `_CAL_CACHE`, not stored. A stored set is a latch: one
    transient failure followed by a clean recovery kept reporting the outage,
    which is a false `calendar_unavailable` alert and a "draft needs you" on a
    morning where every figure verified. That is the same defect removed from
    `facts_degraded` — a flag with a writer and no clearing path.

    One cause, not twenty symptoms. When `exchange_calendars` is missing every
    code fails at once, so `_calendar` returns None for all of them and every
    downstream guard refuses simultaneously: all three tenors, all three ETFs,
    twelve heatmap tiles, every pinned frame, all 56 movers. Each reports its
    own loss and none names the reason, so the operator reads twenty unrelated
    entries. Callers surface this instead.
    """
    return tuple(sorted(set(_WARNED) - set(_CAL_CACHE)
                        | set(_ENUM_FAILED) | set(_QUERY_FAILED)))




def _calendar(code: str):
    if code in _CAL_CACHE:
        return _CAL_CACHE[code]
    try:
        # Imported here, not at module scope: an env without the package must
        # degrade (weekday naming, gates refuse) rather than kill every import.
        import exchange_calendars as xc

        cal = xc.get_calendar(code)
    except Exception as exc:
        # Once per code: `prev_session` loops over `is_session`.
        if code not in _WARNED:
            _WARNED.add(code)
            log.warning("sessions: calendar %s unavailable (%s) — callers gating "
                        "on data quality will treat this as unknown, not clean",
                        code, exc)
        return None
    _CAL_CACHE[code] = cal
    return cal


# Indices carry no suffix, so `resolve_exchange` falls through to NYSE. Without
# these, ^KS11/^KQ11 report 101 Korean-holiday bars as missing NYSE sessions.
_INDEX_CODES = {
    "^GSPC": "XNYS", "^SPX": "XNYS", "^DJI": "XNYS", "^IXIC": "XNYS",
    "^RUT": "XNYS", "^SOX": "XNYS", "^VIX": "XNYS", "^TNX": "XNYS",
    "^IRX": "XNYS", "^TYX": "XNYS", "^FVX": "XNYS",
    "^KS11": "XKRX", "^KQ11": "XKRX",
}


def _calendar_code(ticker: str) -> str | None:
    """The exchange calendar for `ticker`, or None when we would be guessing.

    `resolve_exchange` ends in a bare `return NYSE`, so an unrecognised symbol
    is indistinguishable from a US one; judging `EWY.MX` against XNYS would
    invent missing sessions. Name the indices, trust the shapes
    `resolve_exchange` matched, decline the rest. See `_gate_calendar_code` for
    the opposite default.
    """
    upper = (ticker or "").upper()
    if not upper:
        return _CAL_CODES.get(NYSE.name)  # matches `resolve_exchange("")`
    if upper in _INDEX_CODES:
        return _INDEX_CODES[upper]
    if upper.startswith("^"):
        return None
    placed = (
        upper.endswith("=X")
        or _KRX_NUMERIC.match(upper)
        or any(upper.endswith(sfx) for sfx in _CRYPTO_QUOTE_SUFFIXES)
        or any(upper.endswith(sfx) for sfx, _ in _SUFFIX_EXCHANGE)
    )
    if not placed:
        # Plain US ticker shape, or unplaceable. `BRK-B`/`BF-B` pass.
        if not (upper.replace("-", "").isalnum() and len(upper) <= 6):
            return None
    return _CAL_CODES.get(resolve_exchange(ticker).name)


_ALL_SESSIONS: dict[str, frozenset[int]] = {}
# Codes whose calendar loads but cannot be enumerated. Separate from `_WARNED`
# (load failures) because the recovery signal differs: a load failure clears
# when `_CAL_CACHE` fills, this one clears only when enumeration succeeds.
_ENUM_FAILED: set[str] = set()
# Codes whose calendar loads and enumerates but cannot cover a CURRENT date.
# `exchange_calendars` builds a rolling window (XNYS 2006-09-05..2027-09-03),
# so this is the calendar expiring under a running pipeline — a third mode:
# `_WARNED` clears when the calendar loads, `_ENUM_FAILED` when it enumerates,
# and without its own set this one reports clean while every gate refuses.
# Out-of-window BACKFILL probes are deliberately not recorded here; see
# `_cal_is_session`.
_QUERY_FAILED: set[str] = set()
_CAL_BOUNDS: dict[str, tuple[date, date]] = {}
_UNREPORTED: set[str] = set()   # gated tickers whose own calendar is unnamed


def _all_sessions(cal, code: str):
    """Every session the calendar knows, as ordinals. None if it refuses.

    One entry per exchange, not per window. Keying on `(code, lo, hi)` looked
    cheaper for a batch sweep, but on the server both bounds advance daily
    (`get_recent_history(period="3y")` per ticker per request), so the key space
    is tickers x days at ~54 KB each in a module-level dict with no eviction.
    A whole calendar is ~5.3k ordinals, and callers filter their own dates.
    """
    if code in _ALL_SESSIONS:
        return _ALL_SESSIONS[code]
    try:
        out = frozenset(date.fromisoformat(str(x)[:10]).toordinal()
                        for x in cal.sessions_in_range(cal.first_session,
                                                       cal.last_session))
    except Exception:
        # Record the cause where the failure actually lives. Routing it through
        # `_CAL_CACHE` was wrong: the calendar LOADS fine, so the next
        # `_calendar(code)` — which `is_session` does, i.e. every guard here —
        # put it straight back and cleared the report, while `missing_sessions`
        # kept returning None forever because nothing caches an enumeration
        # failure. A flag that clears itself while the failure persists is the
        # latch defect inverted, not fixed.
        _ENUM_FAILED.add(code)
        return None
    _ALL_SESSIONS[code] = out
    _ENUM_FAILED.discard(code)      # enumeration worked: the outage is over
    return out


def _gate_calendar_code(ticker: str) -> str | None:
    """The calendar to gate `ticker` against, or None only when truly unknown.

    More permissive than `_calendar_code`, for coverage rather than safety —
    every caller refuses on None, so a decline costs the figure, not the guard.
    Taking `resolve_exchange`'s NYSE default is what keeps `CL=F` and
    `DX-Y.NYB` gated; declining them would blank `oil` daily, and `oil` is one
    of the five assets `_check_polarity_lock` needs.

    Unnamed `^` symbols still decline: XNYS would confidently accept a `^N225`
    or `^FTSE` frame whose own exchange held a session Yahoo dropped.
    """
    upper = (ticker or "").upper()
    if upper in _INDEX_CODES:
        return _INDEX_CODES[upper]
    if upper.startswith("^"):
        return None
    return _CAL_CODES.get(resolve_exchange(ticker).name)


def _cal_bounds(cal, code: str) -> tuple[date, date] | None:
    """The calendar's own coverage window, or None if it will not say."""
    if code in _CAL_BOUNDS:
        return _CAL_BOUNDS[code]
    try:
        out = (date.fromisoformat(str(cal.first_session)[:10]),
               date.fromisoformat(str(cal.last_session)[:10]))
    except Exception:
        _ENUM_FAILED.add(code)
        return None
    _CAL_BOUNDS[code] = out
    return out


def _cal_is_session(cal, code: str, d: date) -> bool | None:
    """Ask the calendar about one date. None when it cannot answer.

    One answer path for all four query paths: `is_session`,
    `last_session_on_or_before`, `spans_a_gap` and `prev_session_or_none` all
    route here, so a refusal is recorded once instead of being swallowed four
    ways.

    Bound-checked and answered from the cached ordinal set rather than by
    letting `cal.is_session` raise. Measured over 15,339 in-window days across
    XNYS and XKRX the two agree exactly, and the set lookup is ~57x cheaper on
    loops that walk up to 400 days.

    Only a refusal about a CURRENT date is recorded. Marking every refusal made
    one pre-2006 backfill probe report XNYS unavailable for the life of the
    process — a writer with no clearing path, the latch this module removed from
    `facts_degraded`. A caller asking about 2005 has learned something about
    2005, not about the calendar.
    """
    every = _all_sessions(cal, code)
    if every is None:
        return None
    bounds = _cal_bounds(cal, code)
    if bounds is None:
        return None
    lo, hi = bounds
    if not lo <= d <= hi:
        if abs((d - date.today()).days) <= 30:
            _QUERY_FAILED.add(code)
        return None
    # No discard, unlike `_ENUM_FAILED`. It looks like the write-with-no-clear
    # latch this module removed elsewhere, and it is not: within one run
    # `current_session_state` queries TODAY for XNYS — which records when that
    # window has run out — and ordinary traffic then queries in-window historical dates
    # constantly. Discarding on those wipes the record before
    # `mark_calendar_outage`, its only reader, ever runs. Bounds are cached per
    # process, so there is no in-process recovery to represent.
    return d.toordinal() in every


def missing_sessions(dates, ticker: str) -> tuple[str, ...] | None:
    """Sessions the exchange held that `dates` lacks, or None if not checkable.

    Bounded by the frame's own dates and by the calendar's coverage: a frame
    starting before the calendar begins is checked over the overlap, not skipped.
    """
    # One `str(d)[:10]` per element, not two. The comprehension form evaluated
    # it in the filter and again in the value, which was 56% of this call — and
    # this runs on every chunk build, cache hits included.
    iso = sorted({t for t in (str(d)[:10] for d in dates) if t})
    if len(iso) < 2:
        return ()
    schedule = resolve_exchange(ticker)
    if schedule.trading_weekdays is None or not schedule.trading_weekdays:
        return ()  # crypto / forex: no sessions to miss
    code = _calendar_code(ticker)
    if not code:
        # Declining here while `_gate_calendar_code` still gates the ticker is
        # deliberate (see both docstrings), but it means CL=F, DX-Y.NYB and GC=F
        # get blanked downstream with no line naming why. Say it once per
        # ticker.
        if _gate_calendar_code(ticker) and ticker not in _UNREPORTED:
            _UNREPORTED.add(ticker)
            log.info("sessions: %s is gated against %s but its own calendar is "
                     "unnamed — holes in its frame go unreported",
                     ticker, _gate_calendar_code(ticker))
        return None
    cal = _calendar(code)
    if cal is None:
        return None
    lo = max(iso[0], str(cal.first_session)[:10])
    hi = min(iso[-1], str(cal.last_session)[:10])
    if lo > hi:
        return None
    every = _all_sessions(cal, code)
    if every is None:
        log.warning("sessions: %s calendar %s unavailable", ticker, code)
        return None
    lo_o, hi_o = date.fromisoformat(lo).toordinal(), date.fromisoformat(hi).toordinal()
    have = {date.fromisoformat(d).toordinal() for d in iso}
    # Walk the window (~1.1k days for 3y), not the calendar (~25k), and skip
    # the sort — ordinals ascend by construction.
    return tuple(date.fromordinal(o).isoformat()
                 for o in range(lo_o, hi_o + 1)
                 if o in every and o not in have)


def is_session(d: date, ticker: str = "") -> bool:
    """True if the exchange held a regular session on `d`.

    Falls back to a weekday check when no calendar is available: holidays
    misclassify, but the answer stays usable. Use `prev_session_or_none` where a
    guess is worse than a refusal.
    """
    code = _gate_calendar_code(ticker)
    cal = _calendar(code) if code else None
    if cal is not None:
        out = _cal_is_session(cal, code, d)
        if out is not None:
            return out
        # The calendar EXISTS and refused this date — outside its rolling
        # window. The weekday fallback is for "no calendar at all"; used here it
        # asserts a closed day was open (2005-07-04 → True). The cause is
        # recorded; callers that must not guess use `prev_session_or_none`.
    return d.weekday() < 5


def prev_session(d: date, ticker: str = "") -> date:
    """The exchange session before `d`. Skips weekends and holidays."""
    out = d - timedelta(days=1)
    while not is_session(out, ticker):
        out -= timedelta(days=1)
    return out


def last_session_on_or_before(d: date, ticker: str = "") -> date | None:
    """The ticker's own last session at or before `d`, or None if unanswerable.

    Unlike `prev_session_or_none` this includes `d` itself, so a caller can ask
    whether a frame ending on `d` is current — needed when comparing a KRX frame
    against an NYSE session date.
    """
    # No holiday calendar is not the same as unanswerable.
    schedule = resolve_exchange(ticker)
    if schedule.trading_weekdays is None:
        return d                       # always open
    if not schedule.trading_weekdays:
        out = d                        # forex, 24/5: back to the last weekday
        while out.weekday() >= 5:
            out -= timedelta(days=1)
        return out
    code = _gate_calendar_code(ticker)
    cal = _calendar(code) if code else None
    if cal is None:
        return None
    out = d
    for _ in range(30):
        got = _cal_is_session(cal, code, out)
        if got is None:
            return None
        if got:
            return out
        out -= timedelta(days=1)
    return None


def spans_a_gap(prior: date, last: date, ticker: str = "") -> bool | None:
    """True when `(prior, last)` is not a consecutive-session pair, None if
    the calendar cannot say.

    Callers divide by the `prior` close, so two separate things disqualify a
    pair and both must be checked:

    - a session sits between them — the hole this guard exists for; and
    - `prior` is not itself a session. Yahoo emits a filler bar on some closed
      days (^VIX 2026-05-25 Memorial Day, CL=F 2025-07-04), zero volume and a
      carried-over price. Counting only the sessions between accepts those and
      makes the filler the denominator: ^VIX prints +2.53% against a true
      +1.86%, CL=F +2.15% against +1.39%.

    Known limit: the pair is judged against `_gate_calendar_code`'s calendar,
    which is XNYS for CL=F and DX-Y.NYB. When their own exchange trades on a
    day NYSE is shut (2025-01-09, the Carter mourning close — CL=F traded
    213,421 lots) this refuses a good figure. Refusing beats printing a wrong
    one; the real repair is a NYMEX/CBOE calendar, not a looser test here.
    """
    if last <= prior:
        return True          # duplicate or reversed bars: no move to measure
    span = (last - prior).days
    if span > 400:
        return True          # far past any real gap; do not walk a year of days
    schedule = resolve_exchange(ticker)
    if schedule.trading_weekdays is None:
        return span > 1                                  # crypto: always open
    if not schedule.trading_weekdays:                    # forex, 24/5
        if prior.weekday() >= 5:
            return True
        return any((prior + timedelta(days=k)).weekday() < 5
                   for k in range(1, span))
    code = _gate_calendar_code(ticker)
    cal = _calendar(code) if code else None
    if cal is None:
        return None
    base = _cal_is_session(cal, code, prior)
    if base is None:
        return None
    if not base:
        return True
    for k in range(1, span):
        got = _cal_is_session(cal, code, prior + timedelta(days=k))
        if got is None:
            return None
        if got:
            return True
    return False


def prev_session_or_none(d: date, ticker: str = "") -> date | None:
    """`prev_session`, but None when the exchange calendar cannot answer.

    A caller deciding whether a bar is the true prior session must be able to
    refuse rather than guess, which `prev_session`'s weekday fallback cannot do.
    """
    schedule = resolve_exchange(ticker)
    if schedule.trading_weekdays is None:
        return d - timedelta(days=1)  # always open: yesterday is the prior bar
    if not schedule.trading_weekdays:
        out = d - timedelta(days=1)   # forex, 24/5: the prior weekday
        while out.weekday() >= 5:
            out -= timedelta(days=1)
        return out
    code = _gate_calendar_code(ticker)
    cal = _calendar(code) if code else None
    if cal is None:
        return None
    out = d - timedelta(days=1)
    for _ in range(30):
        got = _cal_is_session(cal, code, out)
        if got is None:
            return None
        if got:
            return out
        out -= timedelta(days=1)
    return None
