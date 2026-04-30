"""KRX KOSPI + KOSDAQ company name → Yahoo-compatible ticker map.

Source: KRX public corpList page (no auth, EUC-KR HTML).
Cached to ~/.terrafin/cache/kr_listings.json with 24h TTL so we hit
the network at most once per day.
"""

import io
import json
import logging
import time
from pathlib import Path


log = logging.getLogger(__name__)

_CACHE_PATH = Path.home() / ".terrafin" / "cache" / "kr_listings.json"
_TTL_SECONDS = 24 * 3600

_KRX_URLS: dict[str, str] = {
    # market suffix → KRX listing URL (HTML table)
    ".KS": "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13&marketType=stockMkt",
    ".KQ": "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13&marketType=kosdaqMkt",
}


def _fetch_market(url: str, suffix: str) -> dict[str, str]:
    import pandas as pd
    import requests

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    resp.encoding = "euc-kr"
    tables = pd.read_html(io.StringIO(resp.text))
    if not tables:
        return {}
    df = tables[0]

    name_col = next((c for c in df.columns if "회사" in str(c)), None)
    code_col = next((c for c in df.columns if "종목코드" in str(c)), None)
    if not name_col or not code_col:
        return {}

    out: dict[str, str] = {}
    for _, row in df.iterrows():
        name = str(row[name_col]).strip()
        raw_code = str(row[code_col]).strip()
        if not name or not raw_code or raw_code.lower() == "nan":
            continue
        # KRX codes are 6 chars, sometimes left-stripped of leading zeros
        code = raw_code.zfill(6)
        out[name] = f"{code}{suffix}"
    return out


def _load_cache() -> dict[str, str] | None:
    try:
        if not _CACHE_PATH.exists():
            return None
        if time.time() - _CACHE_PATH.stat().st_mtime > _TTL_SECONDS:
            return None
        with _CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    except Exception:
        return None
    return None


def _save_cache(data: dict[str, str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as exc:
        log.debug("KRX cache write failed: %s", exc)


def load_kr_listings() -> dict[str, str]:
    """Return {company_name: ticker.KS|.KQ}. Cached for 24h."""
    cached = _load_cache()
    if cached is not None:
        return cached

    merged: dict[str, str] = {}
    for suffix, url in _KRX_URLS.items():
        try:
            merged.update(_fetch_market(url, suffix))
        except Exception as exc:
            log.warning("KRX fetch failed for %s: %s", suffix, exc)

    if merged:
        _save_cache(merged)
    return merged
