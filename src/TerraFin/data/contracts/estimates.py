"""Forward consensus-estimate contract.

Everything here is *forward-looking* market expectation, as distinct from the
realized history in `statements.py` and the reported/surprise history behind
`earnings`. It answers "what does the street expect, and which way is that
expectation moving", which is the observable half of a priced-in check.

Revision counts are the load-bearing field: an estimate level tells you where
consensus sits, but the 7- and 30-day up/down counts tell you which direction it
is being revised, which is a signal rather than a snapshot.
"""

from dataclasses import dataclass, field


# yfinance labels estimate periods relative to the current one: current quarter,
# next quarter, current year, next year. Kept verbatim so callers can map back.
PeriodKey = str
PERIOD_KEYS: tuple[PeriodKey, ...] = ("0q", "+1q", "0y", "+1y")


@dataclass(frozen=True)
class PeriodEstimate:
    """Consensus for one forward period."""

    period: PeriodKey
    avg: float | None = None
    low: float | None = None
    high: float | None = None
    analyst_count: int | None = None
    growth: float | None = None
    year_ago: float | None = None

    @property
    def dispersion(self) -> float | None:
        """(high - low) / |avg| — how much the street disagrees.

        Wide dispersion means the "consensus" is an average over genuinely
        different views, so a variant-perception claim needs to beat the range,
        not the midpoint.
        """
        if self.avg in (None, 0) or self.low is None or self.high is None:
            return None
        return (self.high - self.low) / abs(self.avg)


@dataclass(frozen=True)
class RevisionCounts:
    """Analyst revision activity for one forward period."""

    period: PeriodKey
    up_7d: int | None = None
    down_7d: int | None = None
    up_30d: int | None = None
    down_30d: int | None = None

    @property
    def net_30d(self) -> int | None:
        if self.up_30d is None and self.down_30d is None:
            return None
        return (self.up_30d or 0) - (self.down_30d or 0)

    @property
    def direction_30d(self) -> str | None:
        """"up" / "down" / "flat" over the last 30 days, or None when unknown."""
        net = self.net_30d
        if net is None:
            return None
        if net > 0:
            return "up"
        if net < 0:
            return "down"
        return "flat"


@dataclass(frozen=True)
class PriceTargets:
    current: float | None = None
    mean: float | None = None
    median: float | None = None
    low: float | None = None
    high: float | None = None

    @property
    def upside_to_mean_pct(self) -> float | None:
        if not self.current or self.mean is None:
            return None
        return (self.mean / self.current - 1.0) * 100.0


@dataclass(frozen=True)
class ConsensusEstimates:
    """Forward consensus for one ticker.

    Every field is optional: coverage thins out fast below large caps, and
    indices/ETFs have none at all. `has_coverage` is the single check a caller
    should make before treating any of it as a signal.
    """

    ticker: str
    as_of: str
    currency: str | None = None
    eps: tuple[PeriodEstimate, ...] = ()
    revenue: tuple[PeriodEstimate, ...] = ()
    revisions: tuple[RevisionCounts, ...] = ()
    price_targets: PriceTargets = field(default_factory=PriceTargets)
    # strongBuy / buy / hold / sell / strongSell by month offset ("0m", "-1m", …)
    recommendations: tuple[dict, ...] = ()
    # True only when the fetch itself failed and no cached copy existed. Kept as
    # a field rather than inferred from `warnings`, so a benign note (a stale
    # cache tier, one missing surface) cannot be mistaken for a failure.
    upstream_failed: bool = False
    # Other surfaces responded but every estimate surface was empty. A genuinely
    # uncovered name and a partial upstream failure are identical here, so
    # callers must not assert either.
    estimates_missing: bool = False
    # Best-effort instrument type ("EQUITY", "INDEX", "ETF", …) attached when the
    # fetch returned nothing. CONTEXT ONLY: it is recovered from endpoints that
    # stay up when the estimate endpoint is down, so it cannot confirm that the
    # estimates really are absent.
    quote_type_hint: str | None = None
    # "fresh" | "stale" | "fallback"
    cache_tier: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def has_coverage(self) -> bool:
        return bool(self.eps or self.revenue or self.revisions or self.price_targets.mean)

    @classmethod
    def make_empty(cls, ticker: str = "", as_of: str = "") -> "ConsensusEstimates":
        return cls(ticker=ticker, as_of=as_of)
