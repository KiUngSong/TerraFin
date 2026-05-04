"""SqueezeMetrics SPX GEX historical data (2011-present).

Source: https://squeezemetrics.com/monitor/dix  (DIX.csv endpoint)
Default CSV endpoint configurable via TERRAFIN_SQUEEZEMETRICS_URL.
Refreshed daily by the cache manager (24h TTL).

Data columns returned per point:
  date    — ISO date string (YYYY-MM-DD)
  gex_b   — Gamma Exposure in billions USD (signed; negative = short gamma)
  dix     — Dark Pool Index ratio (e.g. 0.42 = 42%)
  price   — SPX close price (optional)
"""

import csv
import io
import logging
import os
import time
from typing import TypedDict


log = logging.getLogger(__name__)

_SOURCE = "spx.gex.history"
_NAMESPACE = "spx_gex"
_KEY = "history"
# Cache-busted URL matches what squeezemetrics.com/monitor/dix uses in-browser
_DEFAULT_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
_TTL_SECONDS = 86_400  # 24 h

_registered = False


class SpxGexPoint(TypedDict):
    date: str
    gex_b: float
    dix: float | None
    price: float | None


def _url() -> str:
    base = os.environ.get("TERRAFIN_SQUEEZEMETRICS_URL", _DEFAULT_URL)
    # Append cache-buster so CDN/nginx doesn't serve a stale copy
    return f"{base}?_t={int(time.time() * 1000)}"


def _fetch() -> list[SpxGexPoint]:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx required: pip install httpx") from exc

    url = _url()
    log.info("Fetching SPX GEX history from %s", url)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 TerraFin/1.0"})
        resp.raise_for_status()
    return _parse_csv(resp.text)


def _parse_csv(content: str) -> list[SpxGexPoint]:
    """Parse SqueezeMetrics DIX.csv.

    Expected header: date,price,dix,gex
    GEX is raw USD (e.g. 1_897_312_571); divide by 1e9 to get billions.
    DIX is a ratio (0.38 = 38%).
    """
    if content.lstrip().startswith("<"):
        raise ValueError("Expected CSV, got HTML — URL may be returning an error page")
    reader = csv.DictReader(io.StringIO(content))
    out: list[SpxGexPoint] = []
    for row in reader:
        try:
            raw_date = (row.get("date") or row.get("Date") or row.get("DATE") or "").strip()
            if not raw_date:
                continue

            # Accept YYYY-MM-DD or MM/DD/YYYY
            if "/" in raw_date:
                m, d, y = raw_date.split("/")
                raw_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"

            gex_raw = (row.get("gex") or row.get("GEX") or "").strip()
            if not gex_raw:
                continue
            gex_b = float(gex_raw) / 1e9  # raw USD → billions

            dix_raw = (row.get("dix") or row.get("DIX") or "").strip()
            dix = float(dix_raw) if dix_raw else None

            price_raw = (row.get("price") or row.get("Price") or "").strip()
            price = float(price_raw) if price_raw else None

            out.append(SpxGexPoint(date=raw_date, gex_b=gex_b, dix=dix, price=price))
        except (ValueError, KeyError):
            continue

    out.sort(key=lambda p: p["date"])

    if len(out) < 100:
        raise ValueError(
            f"SPX GEX CSV parsed only {len(out)} rows — likely a format change or wrong URL"
        )
    max_abs_gex = max(abs(p["gex_b"]) for p in out)
    if max_abs_gex < 0.01:
        raise ValueError(
            f"SPX GEX values suspiciously small (max |gex_b|={max_abs_gex:.2e}) — "
            "GEX column may already be in billions; check source format"
        )

    return out


def _ensure_registered() -> None:
    global _registered
    if _registered:
        return
    from TerraFin.data.cache.manager import CachePayloadSpec
    from TerraFin.data.cache.registry import get_cache_manager

    get_cache_manager().register_payload(
        CachePayloadSpec(
            source=_SOURCE,
            namespace=_NAMESPACE,
            key=_KEY,
            ttl_seconds=_TTL_SECONDS,
            fetch_fn=_fetch,
        )
    )
    _registered = True


def get_spx_gex_history(*, force_refresh: bool = False) -> list[SpxGexPoint]:
    """Return cached SPX GEX history (SqueezeMetrics, 2011-present).

    Returns an empty list if the source is unreachable and no cached data
    exists.
    """
    _ensure_registered()
    from TerraFin.data.cache.registry import get_cache_manager

    try:
        result = get_cache_manager().get_payload(
            _SOURCE,
            force_refresh=force_refresh,
            allow_stale=False,
            allow_fallback=False,
        )
        return result.payload or []
    except Exception:
        log.exception("Failed to load SPX GEX history")
        return []
