import pandas as pd
from fredapi import Fred

from TerraFin.configuration import load_terrafin_config
from TerraFin.data.cache.policy import ttl_for


_NAMESPACE = "fred"
_SOURCE_PREFIX = "fred"


def _manager():
    """Lazy import to avoid circular dependency."""
    from TerraFin.data.cache.registry import get_cache_manager

    return get_cache_manager()


def _serialize_frame(df: pd.DataFrame) -> dict:
    return {
        "records": df.reset_index().to_dict(orient="records"),
        "index": df.index.astype(str).tolist(),
        "index_name": df.index.name,
    }


def _deserialize_frame(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame(payload["records"])
    if "index" in payload:
        df.index = pd.to_datetime(payload["index"])
        df.index.name = payload.get("index_name")
    if "Close" in df.columns and len(df.columns) > 1:
        df = df[["Close"]]
    return df


def _ensure_source(name: str) -> str:
    from TerraFin.data.cache.manager import CachePayloadSpec

    source = f"{_SOURCE_PREFIX}.{name}"
    manager = _manager()
    if source not in manager._payload_specs:
        manager.register_payload(
            CachePayloadSpec(
                source=source,
                namespace=_NAMESPACE,
                key=name,
                ttl_seconds=ttl_for("fred"),
                fetch_fn=lambda series_id=name: _fetch_fred(series_id),
            )
        )
    return source


def _fetch_fred(name: str) -> dict:
    api_key = load_terrafin_config().fred.api_key
    if not api_key:
        raise ValueError(
            "API key FRED_API_KEY not found in environment variables. Pass FRED_API_KEY to the data factory constructor."
        )
    fred = Fred(api_key=api_key)
    fred_data = pd.DataFrame(fred.get_series(name), columns=["Close"])
    return _serialize_frame(fred_data)


def get_fred_data(name: str) -> pd.DataFrame:
    source = _ensure_source(name)
    result = _manager().get_payload(source)
    payload = result.payload if isinstance(result.payload, dict) else {}
    if not payload:
        return pd.DataFrame(columns=["Close"])
    return _deserialize_frame(payload)


def clear_fred_cache() -> None:
    from TerraFin.data.cache.manager import CacheManager

    manager = _manager()
    for source in list(manager._payload_specs.keys()):
        if source.startswith(_SOURCE_PREFIX + "."):
            manager.clear_payload(source)
    CacheManager.file_cache_clear(_NAMESPACE)
