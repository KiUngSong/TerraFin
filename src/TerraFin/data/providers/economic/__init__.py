from .fred_data import get_fred_data as get_fred_data_raw
from .registry import IndicatorRegistry


indicator_registry = IndicatorRegistry()


def get_economic_indicator(indicator_name: str):
    return indicator_registry.get_indicator(indicator_name)


def get_fred_data(indicator_name: str):
    return get_fred_data_raw(indicator_name)


__all__ = ["get_economic_indicator", "get_fred_data", "indicator_registry"]
