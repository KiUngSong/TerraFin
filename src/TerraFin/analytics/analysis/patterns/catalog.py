"""Facts about the pattern catalogue itself.

Two things a caller cannot derive from a fired ``Signal`` alone: the timeframe a
pattern belongs to, and which detections are the same finding. Both are
properties of the detector, so they are stated here beside it.
"""

from ._base import Signal


# The timeframe each pattern fires on. Every name the catalogue can emit is
# listed, so a caller reads the timeframe here instead of keeping its own copy.
PATTERN_TIMEFRAMES: dict[str, str] = {
    # Trend — close-vs-MA(N) golden/death grid (daily + weekly) + Minervini
    "MA20_GOLDEN_CROSS": "daily",
    "MA20_DEATH_CROSS": "daily",
    "MA60_GOLDEN_CROSS": "daily",
    "MA60_DEATH_CROSS": "daily",
    "MA120_GOLDEN_CROSS": "daily",
    "MA120_DEATH_CROSS": "daily",
    "MA200_GOLDEN_CROSS": "daily",
    "MA200_DEATH_CROSS": "daily",
    "MA20W_GOLDEN_CROSS": "weekly",
    "MA20W_DEATH_CROSS": "weekly",
    "MA60W_GOLDEN_CROSS": "weekly",
    "MA60W_DEATH_CROSS": "weekly",
    "MA120W_GOLDEN_CROSS": "weekly",
    "MA120W_DEATH_CROSS": "weekly",
    "MINERVINI_TEMPLATE": "daily",
    # Breakout
    "52W_NEW_HIGH": "daily",
    "52W_NEW_LOW": "daily",
    "WEEKLY_VOLUME_DRYUP": "weekly",
    "WEEKLY_NEW_HIGH": "weekly",
    "WEEKLY_NEW_LOW": "weekly",
    "WEEKLY_RSI_BULL_DIVERGENCE": "weekly",
    "WEEKLY_RSI_BEAR_DIVERGENCE": "weekly",
    # Reversal
    "RSI_BULL_DIVERGENCE": "daily",
    "RSI_BEAR_DIVERGENCE": "daily",
}


def signal_key(signal: Signal) -> str | None:
    """What identifies one finding across every bar it re-fires on.

    The trigger bar wins: it names the exact bar the finding is about, so a
    divergence that re-confirms on three consecutive weekly bars off one pivot
    stays a single finding. `week_ending` is next, naming the data week the fire
    belongs to. Both are facts the detector put in the snapshot.

    The week only keys a pattern this map calls weekly. A daily pattern that
    reports its data week for display would otherwise be identified by that
    week and ship once instead of once per day, with nothing to notice.

    None when the snapshot carries neither, leaving the caller to key the
    signal by whatever it knows rather than this module inventing an identity.
    """
    snapshot = signal.snapshot or {}
    trigger_bar = snapshot.get("trigger_bar")
    if trigger_bar:
        return trigger_bar
    if PATTERN_TIMEFRAMES.get(signal.name) == "weekly":
        return snapshot.get("week_ending") or None
    return None
