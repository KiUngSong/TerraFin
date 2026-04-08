from ..registry import EconomicIndicator


INDICATORS = {
    "Federal Funds Effective Rate": EconomicIndicator(
        description="Federal Funds Effective Rate: The effective rate at which banks lend to each other overnight.",
        key="FEDFUNDS",
    ),
    "Unemployment Rate": EconomicIndicator(
        description="Unemployment Rate: The percentage of the labor force that is unemployed.",
        key="UNRATE",
    ),
}
