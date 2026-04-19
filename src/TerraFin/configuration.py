"""Typed runtime configuration for TerraFin."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from TerraFin.env import ensure_runtime_env_loaded


DEFAULT_CACHE_INTERVALS = {
    "market_breadth": 43200,
    "trailing_forward_pe": 43200,
    "cape": 86400,
    "calendar": 86400,
    "macro": 86400,
    "fear_greed": 43200,
    "top_companies": 86400,
    "fred": 259200,
    "yfinance": 43200,
    "portfolio": 259200,
    "ticker_info": 43200,
    "sec_filings": 2592000,
}

DEFAULT_WATCHLIST_DATABASE = "terrafin_status_db"
DEFAULT_WATCHLIST_COLLECTION = "terrafin_watchlist"
DEFAULT_WATCHLIST_DOCUMENT_ID = "terrafin_watchlist"


class TerraFinConfigError(ValueError):
    """Raised when TerraFin runtime configuration is invalid."""


class RuntimeConfigError(TerraFinConfigError):
    """Raised when TerraFin interface runtime configuration is invalid."""


@dataclass(frozen=True)
class RuntimeConfig:
    host: str
    port: int
    base_path: str
    cache_timezone: str

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class PrivateAccessConfig:
    endpoint: str | None
    access_key: str | None
    access_value: str | None
    timeout_seconds: float


@dataclass(frozen=True)
class WatchlistConfig:
    uri: str | None
    database: str
    collection: str
    document_id: str


@dataclass(frozen=True)
class SecEdgarConfig:
    user_agent: str | None


@dataclass(frozen=True)
class FredConfig:
    api_key: str | None


@dataclass(frozen=True)
class CacheConfig:
    intervals: dict[str, int]

    def interval_seconds_for(self, key: str) -> int:
        return self.intervals[key]


@dataclass(frozen=True)
class TerraFinConfig:
    runtime: RuntimeConfig
    private_access: PrivateAccessConfig
    watchlist: WatchlistConfig
    sec_edgar: SecEdgarConfig
    fred: FredConfig
    cache: CacheConfig


def get_environment(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    if env is None:
        ensure_runtime_env_loaded()
    return env if env is not None else os.environ


def _normalized_optional(source: Mapping[str, str], key: str) -> str | None:
    value = source.get(key, "").strip()
    return value or None


def _normalize_base_path(raw_value: str) -> str:
    text = raw_value.strip()
    if not text:
        return ""
    trimmed = text.rstrip("/")
    if not trimmed:
        return ""
    return trimmed if trimmed.startswith("/") else f"/{trimmed}"


def _parse_port(value: str) -> int:
    text = value.strip()
    try:
        parsed = int(text)
    except ValueError as exc:
        raise RuntimeConfigError("Invalid TERRAFIN_PORT: must be an integer between 1 and 65535.") from exc
    if parsed < 1 or parsed > 65535:
        raise RuntimeConfigError("Invalid TERRAFIN_PORT: must be an integer between 1 and 65535.")
    return parsed


def _parse_timezone(value: str) -> str:
    text = value.strip() or "UTC"
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeConfigError("Invalid TERRAFIN_CACHE_TIMEZONE: must be a valid IANA timezone.") from exc
    return text


def _load_runtime_config(source: Mapping[str, str]) -> RuntimeConfig:
    return RuntimeConfig(
        host=source.get("TERRAFIN_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_parse_port(source.get("TERRAFIN_PORT", "8001")),
        base_path=_normalize_base_path(source.get("TERRAFIN_BASE_PATH", "")),
        cache_timezone=_parse_timezone(source.get("TERRAFIN_CACHE_TIMEZONE", "UTC")),
    )


def _load_private_access_config(source: Mapping[str, str]) -> PrivateAccessConfig:
    return PrivateAccessConfig(
        endpoint=_normalized_optional(source, "TERRAFIN_PRIVATE_SOURCE_ENDPOINT"),
        access_key=_normalized_optional(source, "TERRAFIN_PRIVATE_SOURCE_ACCESS_KEY"),
        access_value=_normalized_optional(source, "TERRAFIN_PRIVATE_SOURCE_ACCESS_VALUE"),
        timeout_seconds=float(source.get("TERRAFIN_PRIVATE_SOURCE_TIMEOUT_SECONDS", "10")),
    )


def _load_watchlist_config(source: Mapping[str, str]) -> WatchlistConfig:
    uri = _normalized_optional(source, "TERRAFIN_MONGODB_URI") or _normalized_optional(source, "MONGODB_URI")
    return WatchlistConfig(
        uri=uri,
        database=source.get("TERRAFIN_WATCHLIST_MONGODB_DATABASE", "").strip() or DEFAULT_WATCHLIST_DATABASE,
        collection=source.get("TERRAFIN_WATCHLIST_MONGODB_COLLECTION", "").strip() or DEFAULT_WATCHLIST_COLLECTION,
        document_id=source.get("TERRAFIN_WATCHLIST_DOCUMENT_ID", "").strip() or DEFAULT_WATCHLIST_DOCUMENT_ID,
    )


def _load_sec_edgar_config(source: Mapping[str, str]) -> SecEdgarConfig:
    return SecEdgarConfig(user_agent=_normalized_optional(source, "TERRAFIN_SEC_USER_AGENT"))


def _load_fred_config(source: Mapping[str, str]) -> FredConfig:
    return FredConfig(api_key=_normalized_optional(source, "FRED_API_KEY"))


def _load_cache_config(source: Mapping[str, str]) -> CacheConfig:
    intervals: dict[str, int] = {}
    for key, default in DEFAULT_CACHE_INTERVALS.items():
        env_val = source.get(f"TERRAFIN_CACHE_{key.upper()}")
        if env_val is None:
            intervals[key] = default
            continue
        try:
            intervals[key] = max(1, int(str(env_val)))
        except ValueError:
            intervals[key] = default
    return CacheConfig(intervals=intervals)


def load_terrafin_config(env: Mapping[str, str] | None = None) -> TerraFinConfig:
    source = get_environment(env)
    return TerraFinConfig(
        runtime=_load_runtime_config(source),
        private_access=_load_private_access_config(source),
        watchlist=_load_watchlist_config(source),
        sec_edgar=_load_sec_edgar_config(source),
        fred=_load_fred_config(source),
        cache=_load_cache_config(source),
    )


__all__ = [
    "CacheConfig",
    "DEFAULT_CACHE_INTERVALS",
    "DEFAULT_WATCHLIST_COLLECTION",
    "DEFAULT_WATCHLIST_DATABASE",
    "DEFAULT_WATCHLIST_DOCUMENT_ID",
    "FredConfig",
    "PrivateAccessConfig",
    "RuntimeConfig",
    "RuntimeConfigError",
    "SecEdgarConfig",
    "TerraFinConfig",
    "TerraFinConfigError",
    "WatchlistConfig",
    "get_environment",
    "load_terrafin_config",
]
