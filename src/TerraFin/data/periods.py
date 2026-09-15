"""Period strings, parsed in one place.

`"3m"`, `"5y"`, `"30d"` are offsets back from an anchor. `"max"` and `"ytd"`
are not — one has no lower bound and the other anchors to January 1 — so the
parser returns a cutoff rather than an offset, and `None` means "no lower
bound, keep everything".

This lived as five byte-identical private copies (market_indicator, yfinance,
private_access.series, the columnar cache serializer, DataFactory), each
raising `int('ma')` on `"max"` and `int('yt')` on `"ytd"` — period strings the
chart and any agent would reasonably try.
"""

import pandas as pd


def period_cutoff(period: str, anchor: pd.Timestamp) -> pd.Timestamp | None:
    """Earliest timestamp `period` keeps, measured back from `anchor`.

    `None` means keep everything. Callers filter with `>= cutoff` and skip the
    filter entirely when this is `None`.
    """
    text = period.strip().lower()
    if not text:
        raise ValueError("Period is required")
    if text == "max":
        return None
    if text == "ytd":
        # Built off the anchor rather than constructed fresh, so the cutoff
        # keeps the anchor's timezone — a naive one cannot be compared against
        # a tz-aware index.
        return anchor.replace(month=1, day=1).normalize()

    unit = text[-1]
    head = text[:-1]
    if not head.isdigit():
        raise ValueError(f"Unsupported period: {period}")
    amount = int(head)
    if amount <= 0:
        raise ValueError(f"Invalid period: {period}")
    if unit == "y":
        return (anchor - pd.DateOffset(years=amount)).normalize()
    if unit == "m":
        return (anchor - pd.DateOffset(months=amount)).normalize()
    if unit == "d":
        return (anchor - pd.DateOffset(days=amount)).normalize()
    raise ValueError(f"Unsupported period: {period}")
