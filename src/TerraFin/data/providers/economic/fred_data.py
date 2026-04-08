import pandas as pd
from fredapi import Fred

from TerraFin.configuration import load_terrafin_config


FRED_CACHE: dict[str, pd.DataFrame] = {}

_NAMESPACE = "fred"
_FILE_TTL = 7 * 86_400  # 7 days


def _file_cache():
    """Lazy import to avoid circular dependency."""
    from TerraFin.data.cache.manager import CacheManager

    return CacheManager


def get_fred_data(name: str) -> pd.DataFrame:
    api_key = load_terrafin_config().fred.api_key
    if not api_key:
        raise ValueError(
            "API key FRED_API_KEY not found in environment variables. Pass FRED_API_KEY to the DataFactory constructor."
        )
    fred = Fred(api_key=api_key)

    # Check memory cache
    if name in FRED_CACHE:
        return FRED_CACHE[name].copy()

    # Check file cache
    cached = _file_cache().file_cache_read(_NAMESPACE, name, _FILE_TTL)
    if cached is not None:
        try:
            df = pd.DataFrame(cached["records"])
            if "index" in cached:
                df.index = pd.to_datetime(cached["index"])
                df.index.name = cached.get("index_name")
            FRED_CACHE[name] = df
            return df.copy()
        except Exception:
            pass  # fall through to download

    # Download fresh from FRED
    fred_data = pd.DataFrame(fred.get_series(name), columns=["Close"])
    FRED_CACHE[name] = fred_data

    # Persist to file cache
    try:
        payload = {
            "records": fred_data.reset_index().to_dict(orient="records"),
            "index": fred_data.index.astype(str).tolist(),
            "index_name": fred_data.index.name,
        }
        _file_cache().file_cache_write(_NAMESPACE, name, payload)
    except Exception:
        pass  # non-fatal

    return fred_data.copy()


def clear_fred_cache() -> None:
    FRED_CACHE.clear()
    _file_cache().file_cache_clear(_NAMESPACE)
