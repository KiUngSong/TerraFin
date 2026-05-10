"""yfinance-based fallback for top-companies when the private API is unavailable."""

import logging
from typing import Any

log = logging.getLogger(__name__)

_TOP_K = 50
# Rough sample size — enough to cover the real top-50 without fetching all 700.
_SAMPLE_SIZE = 150


def get_top_companies_fallback() -> list[dict[str, Any]]:
    """Return top-companies list ranked by market cap via yfinance.

    Samples the first _SAMPLE_SIZE symbols from the S&P 500 + KOSPI 200
    universe (S&P 500 is listed alphabetically so the sample is biased toward
    large well-known names that cluster near the top of most watchlists).
    Returns at most _TOP_K results shaped as TopCompanyRow dicts.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning("top_companies fallback: yfinance not installed")
        return []

    try:
        from TerraFin.data.reference import UNIVERSES_DIR
        import csv

        symbols: list[tuple[str, str, str]] = []  # (symbol, name, country)
        for universe_file, country in [("sp500.csv", "US"), ("kospi200.csv", "KR")]:
            path = UNIVERSES_DIR / universe_file
            if not path.exists():
                continue
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    symbols.append((row["symbol"], row.get("name", ""), country))
    except Exception as exc:
        log.warning("top_companies fallback: failed to load universe: %s", exc)
        return []

    sample = symbols[:_SAMPLE_SIZE]
    tickers_str = " ".join(s[0] for s in sample)
    sym_meta = {s[0]: (s[1], s[2]) for s in sample}

    try:
        tickers_obj = yf.Tickers(tickers_str)
    except Exception as exc:
        log.warning("top_companies fallback: yf.Tickers failed: %s", exc)
        return []

    rows: list[dict[str, Any]] = []
    for sym, (name, country) in sym_meta.items():
        try:
            fi = tickers_obj.tickers[sym].fast_info
            mcap = fi.market_cap
            if not mcap:
                continue
            rows.append({"symbol": sym, "name": name, "country": country, "marketCapValue": float(mcap)})
        except Exception:
            continue

    rows.sort(key=lambda r: r["marketCapValue"], reverse=True)
    result = []
    for rank, row in enumerate(rows[:_TOP_K], start=1):
        mcap_val = row["marketCapValue"]
        if mcap_val >= 1e12:
            mcap_str = f"${mcap_val / 1e12:.2f}T"
        elif mcap_val >= 1e9:
            mcap_str = f"${mcap_val / 1e9:.2f}B"
        else:
            mcap_str = f"${mcap_val / 1e6:.0f}M"
        result.append({
            "rank": rank,
            "ticker": row["symbol"],
            "name": row["name"],
            "marketCap": mcap_str,
            "country": row["country"],
            "marketCapValue": mcap_val,
        })
    return result
