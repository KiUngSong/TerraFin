"""Private data access entrypoint and typed contracts."""

from .cape import (
    clear_cape_cache,
    get_cape_current,
    get_cape_history,
    refresh_cape_cache,
)
from .client import PrivateAccessClient
from .config import PrivateAccessConfig, load_private_access_config
from .fear_greed import (
    clear_fear_greed_cache,
    get_fear_greed_current,
    get_fear_greed_history,
    refresh_fear_greed_cache,
)
from .net_breadth import (
    clear_net_breadth_cache,
    get_net_breadth_history,
    refresh_net_breadth_cache,
)
from .series import PrivateSeriesSpec
from .trailing_forward_pe import (
    clear_trailing_forward_pe_cache,
    get_trailing_forward_pe_history,
    refresh_trailing_forward_pe_cache,
)


__all__ = [
    "PrivateAccessClient",
    "PrivateAccessConfig",
    "load_private_access_config",
    "PrivateSeriesSpec",
    "get_cape_history",
    "get_cape_current",
    "refresh_cape_cache",
    "clear_cape_cache",
    "get_fear_greed_history",
    "get_fear_greed_current",
    "refresh_fear_greed_cache",
    "clear_fear_greed_cache",
    "get_net_breadth_history",
    "refresh_net_breadth_cache",
    "clear_net_breadth_cache",
    "get_trailing_forward_pe_history",
    "refresh_trailing_forward_pe_cache",
    "clear_trailing_forward_pe_cache",
]
