"""Session-aware staleness helper for cached market history.

The 24h wall-clock TTL on ``yfinance.full`` is too coarse: an artifact
fetched at May 19 18:00 UTC stays "fresh" until May 20 18:00 UTC, even
though the May 20 session has already closed at 20:00 UTC and a newer
bar exists upstream. ``latest_expected_close`` answers the question
"what is the most recent session close, in UTC, that the upstream
provider should already have a bar for?" given the asset's exchange.

We deliberately ship a tiny hardcoded calendar (regular weekly schedule,
no holiday awareness) rather than pulling in ``pandas_market_calendars``
or ``exchange_calendars``. The trade-off: on a holiday the staleness
check may say "stale" when in fact no new bar will arrive — the worst
case is a single redundant re-fetch that returns the same data. We
never *under*-refresh, only occasionally *over*-refresh. Adding a real
calendar dep can be done later if that over-refresh becomes painful.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


# Plain 6-digit numerics (no suffix) are KRX. With-suffix forms are
# routed by the suffix map below — that handles ``.KS``/``.KQ`` for KRX,
# but also keeps ``600519.SS`` from collapsing into KRX (it belongs on
# SSE).
_KRX_NUMERIC = re.compile(r"^\d{6}$")

# Known yfinance crypto quote suffixes. Anything with a "-" that does NOT end
# in one of these falls through to the default equity path. This avoids
# routing equities like ``BRK-B``, ``BRK-A``, ``BF-B`` (class-share dashes
# on NYSE) to the CRYPTO schedule, which would skip the staleness check and
# revert to the original 24h-stale bug.
_CRYPTO_QUOTE_SUFFIXES = (
    "-USD",
    "-USDT",
    "-USDC",
    "-BTC",
    "-ETH",
    "-EUR",
    "-GBP",
    "-JPY",
)


@dataclass(frozen=True)
class ExchangeSchedule:
    """Weekly trading calendar for one exchange (regular sessions only)."""

    name: str
    tz: ZoneInfo
    close_time: time
    # Monday=0..Sunday=6. None means "always open" (crypto), empty means
    # "never has a session close to wait for" (skip the check entirely).
    trading_weekdays: tuple[int, ...] | None


# Hardcoded schedules. Holiday-naive on purpose — see module docstring.
NYSE = ExchangeSchedule(
    name="NYSE",
    tz=ZoneInfo("America/New_York"),
    close_time=time(16, 0),
    trading_weekdays=(0, 1, 2, 3, 4),
)
KRX = ExchangeSchedule(
    name="KRX",
    tz=ZoneInfo("Asia/Seoul"),
    close_time=time(15, 30),
    trading_weekdays=(0, 1, 2, 3, 4),
)
TSE = ExchangeSchedule(
    name="TSE",
    tz=ZoneInfo("Asia/Tokyo"),
    close_time=time(15, 0),
    trading_weekdays=(0, 1, 2, 3, 4),
)
HKEX = ExchangeSchedule(
    name="HKEX",
    tz=ZoneInfo("Asia/Hong_Kong"),
    close_time=time(16, 0),
    trading_weekdays=(0, 1, 2, 3, 4),
)
SSE = ExchangeSchedule(
    name="SSE",
    tz=ZoneInfo("Asia/Shanghai"),
    close_time=time(15, 0),
    trading_weekdays=(0, 1, 2, 3, 4),
)
SZSE = ExchangeSchedule(
    name="SZSE",
    tz=ZoneInfo("Asia/Shanghai"),
    close_time=time(15, 0),
    trading_weekdays=(0, 1, 2, 3, 4),
)
LSE = ExchangeSchedule(
    name="LSE",
    tz=ZoneInfo("Europe/London"),
    close_time=time(16, 30),
    trading_weekdays=(0, 1, 2, 3, 4),
)
ASX = ExchangeSchedule(
    name="ASX",
    tz=ZoneInfo("Australia/Sydney"),
    close_time=time(16, 0),
    trading_weekdays=(0, 1, 2, 3, 4),
)
EURONEXT_PARIS = ExchangeSchedule(
    name="EURONEXT_PARIS",
    tz=ZoneInfo("Europe/Paris"),
    close_time=time(17, 30),
    trading_weekdays=(0, 1, 2, 3, 4),
)
XETRA = ExchangeSchedule(
    name="XETRA",
    tz=ZoneInfo("Europe/Berlin"),
    close_time=time(17, 30),
    trading_weekdays=(0, 1, 2, 3, 4),
)
SIX_SWISS = ExchangeSchedule(
    name="SIX_SWISS",
    tz=ZoneInfo("Europe/Zurich"),
    close_time=time(17, 30),
    trading_weekdays=(0, 1, 2, 3, 4),
)
_CRYPTO = ExchangeSchedule(
    name="CRYPTO",
    tz=ZoneInfo("UTC"),
    close_time=time(0, 0),
    trading_weekdays=None,
)
_FOREX = ExchangeSchedule(
    name="FOREX",
    tz=ZoneInfo("UTC"),
    close_time=time(0, 0),
    # Forex runs 24/5 — no concept of a single daily close to wait on.
    trading_weekdays=(),
)


# Suffix -> exchange mapping for foreign yfinance tickers.
_SUFFIX_EXCHANGE: tuple[tuple[str, ExchangeSchedule], ...] = (
    (".KS", KRX),
    (".KQ", KRX),
    (".T", TSE),
    (".HK", HKEX),
    (".SS", SSE),
    (".SZ", SZSE),
    (".L", LSE),
    (".AX", ASX),
    (".PA", EURONEXT_PARIS),
    (".DE", XETRA),
    (".SW", SIX_SWISS),
)


def resolve_exchange(ticker: str) -> ExchangeSchedule:
    """Map a yfinance ticker to its primary exchange schedule.

    Heuristics:
    * Forex pairs (``USDKRW=X``) -> FOREX (skip the check).
    * Crypto pairs with a known quote suffix (``BTC-USD``, ``ETH-USDT``)
      -> CRYPTO. Class-share dashes like ``BRK-B`` fall through.
    * 6-digit numeric, optionally ``.KS``/``.KQ`` suffixed -> KRX.
    * Other known foreign suffixes (``.T``, ``.L``, ``.HK``, ...) -> the
      matching exchange.
    * Everything else (plain US tickers, ``^VIX``-style indices, unknown
      ``FOO-BAR`` shapes) -> NYSE.
    """
    if not ticker:
        return NYSE
    upper = ticker.upper()
    if upper.endswith("=X"):
        return _FOREX
    # Crypto pairs must end in a known quote suffix. ``BRK-B``, ``BF-B``,
    # ``RANDOM-FOO`` all fall through to the equity path.
    if not upper.startswith("^"):
        for suffix in _CRYPTO_QUOTE_SUFFIXES:
            if upper.endswith(suffix):
                return _CRYPTO
    if _KRX_NUMERIC.match(upper):
        return KRX
    for suffix, schedule in _SUFFIX_EXCHANGE:
        if upper.endswith(suffix):
            return schedule
    return NYSE


def latest_expected_close(schedule: ExchangeSchedule, *, now_utc: datetime) -> datetime | None:
    """Most recent expected session close at or before ``now_utc`` (UTC).

    Returns ``None`` for schedules where the concept doesn't apply
    (crypto = always open, forex = 24/5 with no single daily close).
    """
    if schedule.trading_weekdays is None:
        return None
    if not schedule.trading_weekdays:
        return None
    local_now = now_utc.astimezone(schedule.tz)
    # Walk back at most 7 days looking for the most recent (weekday,
    # local-close-time) point that has already happened.
    for delta_days in range(0, 8):
        candidate_date = (local_now - timedelta(days=delta_days)).date()
        if candidate_date.weekday() not in schedule.trading_weekdays:
            continue
        candidate_local = datetime.combine(candidate_date, schedule.close_time, tzinfo=schedule.tz)
        if candidate_local <= local_now:
            return candidate_local.astimezone(ZoneInfo("UTC"))
    return None  # pragma: no cover - 8-day window always finds a weekday


def is_cache_stale_by_session(
    last_bar_utc: datetime | None,
    ticker: str,
    *,
    now_utc: datetime,
) -> bool:
    """Return True iff the cached artifact predates the latest expected
    close for ``ticker``'s exchange.

    A True result means "a newer bar should exist upstream — re-fetch".
    Returns False for crypto/forex (no session concept) and when the
    artifact is unreadable (defer to caller's wall-clock TTL).

    Compared at TRADING-DATE granularity. yfinance daily bars are
    labelled by the trading-day calendar date (e.g. "2025-01-07"), not
    by an absolute close instant — we read the bar's UTC date directly
    as the trading date and ask "is it before the most-recent expected
    close's trading date?".
    """
    if last_bar_utc is None:
        return False
    schedule = resolve_exchange(ticker)
    expected = latest_expected_close(schedule, now_utc=now_utc)
    if expected is None:
        return False
    return last_bar_utc.date() < expected.date()
