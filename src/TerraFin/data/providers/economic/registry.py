from dataclasses import dataclass
from typing import Callable, cast

import pandas as pd

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame

from .fred_data import get_fred_data


@dataclass
class EconomicIndicator:
    """Economic indicator"""

    description: str = ""  # description of the indicator
    key: str = ""  # required key value to get data. e.g. id for fred
    get_data: Callable[[str], pd.DataFrame] = get_fred_data  # function to get data
    output_type: type = TimeSeriesDataFrame  # type of the output


class IndicatorRegistry:
    """Registry for economic indicators"""

    def __init__(self):
        self._indicators: dict[str, EconomicIndicator] = {}
        self._load_indicators()

    def _load_indicators(self):
        """Load all indicator definitions"""
        from .indicators import credit_risk, macro, monetary_fiscal

        # Load indicators from each module
        for module in [macro, monetary_fiscal, credit_risk]:
            if hasattr(module, "INDICATORS"):
                self._indicators.update(cast(dict[str, EconomicIndicator], getattr(module, "INDICATORS")))

    def get_indicator(self, name: str) -> TimeSeriesDataFrame:
        """Get indicator by name"""
        if name not in self._indicators:
            raise ValueError(f"Unknown indicator: {name}")
        indicator = self._indicators[name]

        data = indicator.get_data(indicator.key)
        data = cast(TimeSeriesDataFrame, indicator.output_type(data))

        return data
