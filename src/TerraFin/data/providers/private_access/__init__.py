"""Private data access entrypoint and typed contracts."""

from .client import PrivateAccessClient
from .config import PrivateAccessConfig, load_private_access_config
from .series import (
    PrivateSeriesSpec,
    clear_private_series_cache,
    get_private_series_current,
    get_private_series_history,
    refresh_private_series_cache,
)
from .series_registry import PRIVATE_SERIES


__all__ = [
    "PrivateAccessClient",
    "PrivateAccessConfig",
    "load_private_access_config",
    "PrivateSeriesSpec",
    "PRIVATE_SERIES",
    "get_private_series_history",
    "get_private_series_current",
    "refresh_private_series_cache",
    "clear_private_series_cache",
]
