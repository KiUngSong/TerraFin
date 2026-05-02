from .series import PrivateSeriesSpec


PRIVATE_SERIES: dict[str, PrivateSeriesSpec] = {
    "cape": PrivateSeriesSpec(
        key="cape",
        display_name="CAPE",
        history_cache_namespace="private_cape_history",
        current_cache_namespace="private_cape_series_current",
    ),
    "fear_greed": PrivateSeriesSpec(
        key="fear-greed",
        display_name="Fear & Greed",
        history_cache_namespace="private_fear_greed_history",
        current_cache_namespace="private_fear_greed_current",
    ),
    "net_breadth": PrivateSeriesSpec(
        key="net-breadth",
        display_name="Net Breadth",
        history_cache_namespace="private_net_breadth_history",
    ),
    "trailing_forward_pe": PrivateSeriesSpec(
        key="trailing-forward-pe-spread",
        display_name="Trailing-Forward P/E Spread",
        history_cache_namespace="private_trailing_forward_pe_history",
    ),
}
