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
    "Composite Leading Indicator": EconomicIndicator(
        description=(
            "Composite Leading Indicator: OECD CLI for the United States, built to signal business-cycle turning "
            "points about 6-9 months ahead, so it is read for recession risk. Amplitude adjusted, long-term average "
            "= 100: above 100 and falling is the early warning of a downturn, below 100 and falling a slowdown, "
            "below 100 and rising a recovery, above 100 and rising an expansion."
        ),
        key="USALOLITOAASTSAM",
    ),
}
