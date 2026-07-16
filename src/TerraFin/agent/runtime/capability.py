"""Capability dataclass, registry, and the default-registry builder.

`TerraFinCapability` wraps a handler function with focus / artifact
metadata; `TerraFinCapabilityRegistry` is the lookup surface used by
contexts and the hosted runtime. `build_default_capability_registry`
materialises every TerraFin capability the agent service exposes.
"""
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .artifacts import (
    ArtifactBuilder,
    CapabilityHandler,
    FocusExtractor,
    TerraFinArtifact,
    _dedupe,
)
from .focus import (
    _chart_artifact,
    _chart_focus,
    _economic_focus,
    _focus_from_input_keys,
    _resolve_focus,
)


if TYPE_CHECKING:
    from .context import TerraFinAgentContext
    from ..service import TerraFinAgentService


@dataclass(frozen=True, slots=True)
class TerraFinCapability:
    name: str
    description: str
    handler: CapabilityHandler
    focus_extractor: FocusExtractor | None = None
    artifact_builder: ArtifactBuilder | None = None
    side_effecting: bool = False
    backgroundable: bool = False
    # Optional metadata consumed by the agent-artefacts generator (Part E of
    # the single-source-of-truth refactor) and by `terrafin-agent
    # capabilities`. All default-None / empty so existing registrations stay
    # valid without changes; the generator validates that public capabilities
    # populate `summary` + `http_route_path` + `response_model_name`.
    summary: str | None = None
    cli_subcommand_name: str | None = None
    http_route_path: str | None = None
    response_model_name: str | None = None
    examples: tuple[str, ...] = ()

    def extract_focus(self, inputs: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[str, ...]:
        if self.focus_extractor is None:
            return ()
        return tuple(_dedupe(self.focus_extractor(inputs, payload)))

    def build_artifact(
        self,
        session_id: str,
        inputs: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> TerraFinArtifact | None:
        if self.artifact_builder is None:
            return None
        return self.artifact_builder(session_id, self.name, inputs, payload)


class TerraFinCapabilityRegistry:
    def __init__(self, capabilities: Iterable[TerraFinCapability] | None = None) -> None:
        self._capabilities: dict[str, TerraFinCapability] = {}
        if capabilities is not None:
            for capability in capabilities:
                self.register(capability)

    def register(self, capability: TerraFinCapability) -> TerraFinCapability:
        if capability.name in self._capabilities:
            raise ValueError(f"Capability already registered: {capability.name}")
        self._capabilities[capability.name] = capability
        return capability

    def get(self, name: str) -> TerraFinCapability:
        try:
            return self._capabilities[name]
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise KeyError(f"Unknown TerraFin capability: {name}") from exc

    def list(self) -> tuple[TerraFinCapability, ...]:
        return tuple(self._capabilities.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._capabilities)

    def invoke(
        self,
        capability_name: str,
        *,
        context: "TerraFinAgentContext | None" = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        capability = self.get(capability_name)
        payload = capability.handler(**kwargs)
        if not isinstance(payload, dict):
            raise TypeError(f"Capability '{capability_name}' must return a dict payload.")
        if context is not None:
            context._record_capability_result(capability, inputs=kwargs, payload=payload)
        return payload


def build_default_capability_registry(
    service: "TerraFinAgentService | None" = None,
    *,
    chart_opener: Callable[..., dict[str, Any]] | None = None,
) -> TerraFinCapabilityRegistry:
    from ..service import TerraFinAgentService

    if chart_opener is None:
        from ..cli.tasks import open_chart as default_open_chart

    resolved_service = service or TerraFinAgentService()
    resolved_chart_opener = chart_opener or default_open_chart

    registry = TerraFinCapabilityRegistry(
        [
            TerraFinCapability(
                name="resolve",
                description="Resolve a free-form market or macro query into TerraFin routing.",
                handler=resolved_service.resolve,
                focus_extractor=_resolve_focus,
                summary="Resolve a free-form query into a TerraFin route.",
                cli_subcommand_name="resolve",
                http_route_path="/agent/api/resolve",
                response_model_name="ResolveResponse",
            ),
            TerraFinCapability(
                name="market_data",
                description="Fetch chart-ready market data for a single asset.",
                handler=resolved_service.market_data,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
                summary="Chart-ready OHLC time series for one asset.",
                cli_subcommand_name="market-data",
                http_route_path="/agent/api/market-data",
                response_model_name="MarketDataResponse",
            ),
            TerraFinCapability(
                name="indicators",
                description="Compute chart-matching technical indicators for a single asset.",
                handler=resolved_service.indicators,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
                summary="Chart-matching technical indicators for one asset.",
                cli_subcommand_name="indicators",
                http_route_path="/agent/api/indicators",
                response_model_name="IndicatorsResponse",
            ),
            TerraFinCapability(
                name="patterns",
                description="Evaluate every named market pattern (MA20_GOLDEN_CROSS, MINERVINI_TEMPLATE, 52W_NEW_HIGH, etc.) against the latest bar of a single asset and return whichever patterns currently match.",
                handler=resolved_service.patterns,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
                summary="Named market patterns matching the latest bar for one asset.",
                cli_subcommand_name="patterns",
                http_route_path="/agent/api/patterns",
                response_model_name="PatternsResponse",
            ),
            TerraFinCapability(
                name="market_snapshot",
                description=(
                    "Fetch a compact market snapshot for a single asset. "
                    "Response carries `asof` (ISO date of the last bar served) "
                    "so callers can detect a stale-by-one-session payload. "
                    "Pass `force_refresh=true` only when serving time-sensitive "
                    "snapshots (e.g. mid-session quote, freshly-closed bar that "
                    "may still be cached from the prior session); default false "
                    "keeps the cache hot to avoid hammering upstream. Only "
                    "yfinance-backed names (indices, raw tickers, VIX/VVIX/SKEW/"
                    "MOVE/Treasury yields) honor the flag; composite/private "
                    "indicators (Vol Regime, VVIX/VIX Ratio, Fear & Greed, Net "
                    "Breadth, CAPE, Trailing-Forward P/E Spread, SPX GEX) "
                    "ignore it."
                ),
                handler=resolved_service.market_snapshot,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
                summary="Compact market snapshot for one asset.",
                cli_subcommand_name="snapshot",
                http_route_path="/agent/api/market-snapshot",
                response_model_name="MarketSnapshotResponse",
            ),
            TerraFinCapability(
                name="lppl_analysis",
                description="Run LPPL bubble analysis for a single asset.",
                handler=resolved_service.lppl_analysis,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
                summary="LPPL bubble analysis (super-exponential growth + log-periodic oscillation detection).",
                cli_subcommand_name="lppl",
                http_route_path="/agent/api/lppl",
                response_model_name="LPPLAnalysisResponse",
            ),
            TerraFinCapability(
                name="company_info",
                description="Fetch company profile and valuation fields for a ticker.",
                handler=resolved_service.company_info,
                focus_extractor=_focus_from_input_keys("ticker"),
                summary="Company profile and valuation fields for a ticker.",
                cli_subcommand_name="company",
                http_route_path="/agent/api/company",
                response_model_name="CompanyInfoResponse",
            ),
            TerraFinCapability(
                name="earnings",
                description="Fetch earnings history for a ticker.",
                handler=resolved_service.earnings,
                focus_extractor=_focus_from_input_keys("ticker"),
                summary="Earnings history (estimate / reported / surprise) for a ticker.",
                cli_subcommand_name="earnings",
                http_route_path="/agent/api/earnings",
                response_model_name="EarningsResponse",
            ),
            TerraFinCapability(
                name="financials",
                description="Fetch a financial statement table for a ticker.",
                handler=resolved_service.financials,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="Financial statement table (income / balance / cashflow) for a ticker.",
                cli_subcommand_name="financials",
                http_route_path="/agent/api/financials",
                response_model_name="FinancialStatementResponse",
            ),
            TerraFinCapability(
                name="portfolio",
                description="Fetch guru portfolio holdings and summary metadata.",
                handler=resolved_service.portfolio,
                focus_extractor=_focus_from_input_keys("guru"),
                backgroundable=True,
                summary="Guru portfolio holdings and summary metadata.",
                cli_subcommand_name="portfolio",
                http_route_path="/agent/api/portfolio",
                response_model_name="PortfolioResponse",
            ),
            TerraFinCapability(
                name="economic",
                description="Fetch economic indicator series.",
                handler=resolved_service.economic,
                focus_extractor=_economic_focus,
                backgroundable=True,
                summary="Economic indicator series (FRED-backed).",
                cli_subcommand_name="economic",
                http_route_path="/agent/api/economic",
                response_model_name="EconomicResponse",
            ),
            TerraFinCapability(
                name="macro_focus",
                description="Fetch macro summary plus chart-ready series for an instrument.",
                handler=resolved_service.macro_focus,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
                summary="Macro summary plus chart-ready series for one instrument.",
                cli_subcommand_name="macro-focus",
                http_route_path="/agent/api/macro-focus",
                response_model_name="MacroFocusResponse",
            ),
            TerraFinCapability(
                name="calendar_events",
                description="Fetch TerraFin calendar events for a month.",
                handler=resolved_service.calendar_events,
                backgroundable=True,
                summary="TerraFin calendar events for a month.",
                cli_subcommand_name="calendar",
                http_route_path="/agent/api/calendar",
                response_model_name="CalendarResponse",
            ),
            # ----- Dashboard widget-parity capabilities -----
            # Each of these mirrors a standalone widget the user sees on the
            # dashboard / market-insights / stock-analysis pages. Without them
            # the user would be surprised the agent can't comment on something
            # they're staring at. Payloads pass through verbatim from the
            # `build_*_payload` / `get_*` route helpers so the two views never
            # diverge (DA audit: High-3/4/5, Med-6).
            TerraFinCapability(
                name="fear_greed",
                description=(
                    "Fetch the CNN Fear & Greed index — same data as the "
                    "`/terminal/api/fear-greed` widget. Returns score, rating, "
                    "previous close, and 1W/1M history."
                ),
                handler=resolved_service.fear_greed,
                summary="CNN Fear & Greed index — score, rating, history.",
                http_route_path="/agent/api/fear-greed",
                response_model_name="FearGreedResponse",
            ),
            TerraFinCapability(
                name="sp500_dcf",
                description=(
                    "Fetch the full S&P 500 DCF valuation — same shape as "
                    "`/market-insights/api/dcf/sp500`. Includes scenarios, "
                    "sensitivity matrix, methods, rateCurve, dataQuality."
                ),
                handler=resolved_service.sp500_dcf,
                backgroundable=True,
                summary="Full S&P 500 DCF valuation (scenarios, sensitivity, methods).",
                http_route_path="/agent/api/sp500-dcf",
                response_model_name="DCFValuationResponse",
            ),
            TerraFinCapability(
                name="beta_estimate",
                description=(
                    "Fetch a 5-year monthly beta estimate with adjusted beta, "
                    "R², and benchmark — same shape as `/stock/api/beta-estimate`. "
                    "Use this when you need the statistical quality of the beta; "
                    "`company_info` only surfaces a bare beta string."
                ),
                handler=resolved_service.beta_estimate,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="5-year monthly beta with adjusted beta, R², benchmark.",
                http_route_path="/agent/api/beta-estimate",
                response_model_name="BetaEstimateResponse",
            ),
            TerraFinCapability(
                name="fcf_history",
                description=(
                    "Fetch FCF-per-share history and the three candidate base values "
                    "(3yr_avg, latest_annual, TTM) that the DCF tool's `auto` cascade "
                    "evaluates. Use this when the user asks which FCF figure is being "
                    "used in the valuation or wants to inspect historical FCF trends."
                ),
                handler=resolved_service.fcf_history,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="FCF history + 3yr-avg / latest-annual / TTM candidates.",
                http_route_path="/agent/api/fcf-history",
                response_model_name="FcfHistoryResponse",
            ),
            TerraFinCapability(
                name="similarity_search",
                description=(
                    "Find stocks whose 1-year price chart most closely resembles the "
                    "target ticker, ranked by normalized shape similarity. "
                    "Searches across `universe` (sp500, kospi200, sp500+kospi200, or "
                    "watchlist). Returns a ranked list of symbols with similarity scores "
                    "in [0, 1] and the number of overlapping trading days. "
                    "Computationally heavy — background when possible."
                ),
                handler=resolved_service.similarity_search,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="Chart-pattern similarity search across a stock universe.",
                http_route_path="/agent/api/similarity-search",
                response_model_name="SimilaritySearchResponse",
            ),
            TerraFinCapability(
                name="top_companies",
                description=(
                    "Fetch the market-insights top-companies list — same data as "
                    "`/market-insights/api/top-companies`. Falls back to a yfinance-"
                    "computed market-cap ranking when the private API is unavailable."
                ),
                handler=resolved_service.top_companies,
                summary="Top companies by market cap (private API or yfinance fallback).",
                http_route_path="/agent/api/top-companies",
                response_model_name="TopCompaniesResponse",
            ),
            TerraFinCapability(
                name="market_regime",
                description=(
                    "Fetch the market regime summary — same data as "
                    "`/market-insights/api/regime`. Returns a short summary, "
                    "confidence, and bulleted signals."
                ),
                handler=resolved_service.market_regime,
                summary="Market regime classification with confidence and signals.",
                http_route_path="/agent/api/market-regime",
                response_model_name="MarketRegimeResponse",
            ),
            TerraFinCapability(
                name="trailing_forward_pe",
                description=(
                    "Fetch the trailing vs. forward P/E spread — same data as "
                    "`/terminal/api/trailing-forward-pe-spread`."
                ),
                handler=resolved_service.trailing_forward_pe,
                backgroundable=True,
                summary="S&P 500 trailing vs forward P/E spread (history + summary).",
                http_route_path="/agent/api/trailing-forward-pe",
                response_model_name="TrailingForwardPeSpreadResponse",
            ),
            TerraFinCapability(
                name="market_breadth",
                description=(
                    "Fetch standalone market-breadth metrics — same data as the "
                    "MarketBreadthCard widget. Was previously bundled inside "
                    "`market_snapshot`; use this capability when the question is "
                    "about whole-market state rather than a single ticker."
                ),
                handler=resolved_service.market_breadth,
                summary="Standalone market-breadth metrics (% advancing, new highs, etc.).",
                http_route_path="/agent/api/market-breadth",
                response_model_name="MarketBreadthResponse",
            ),
            TerraFinCapability(
                name="watchlist",
                description=(
                    "Fetch the user's current watchlist — same data as the "
                    "WatchlistSection widget. Standalone now; was previously "
                    "bundled inside `market_snapshot`."
                ),
                handler=resolved_service.watchlist,
                summary="The user's current watchlist (read-only).",
                http_route_path="/agent/api/watchlist",
                response_model_name="WatchlistResponse",
            ),
            TerraFinCapability(
                name="open_chart",
                description="Create or update a TerraFin chart session and return a chart artifact.",
                handler=resolved_chart_opener,
                focus_extractor=_chart_focus,
                artifact_builder=_chart_artifact,
                side_effecting=True,
                summary="Create or update a chart session bound to the conversation.",
                cli_subcommand_name="open-chart",
                # Hosted-only: no parity HTTP route. Chart artifacts are bound
                # to the active session.
                http_route_path=None,
                response_model_name="ChartOpenResponse",
            ),
            TerraFinCapability(
                name="fundamental_screen",
                description="Run fundamental quality and moat screening for a ticker (ROE, margins, earnings quality, balance sheet, pricing power).",
                handler=resolved_service.fundamental_screen,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="Fundamental quality and moat screen for a ticker.",
                http_route_path="/agent/api/fundamental-screen",
                response_model_name="FundamentalScreenResponse",
            ),
            TerraFinCapability(
                name="risk_profile",
                description="Compute statistical risk profile for an asset (tail risk, convexity, volatility regime, drawdown).",
                handler=resolved_service.risk_profile,
                focus_extractor=_focus_from_input_keys("name"),
                backgroundable=True,
                summary="Statistical risk profile (tail risk, convexity, vol regime, drawdown).",
                http_route_path="/agent/api/risk-profile",
                response_model_name="RiskProfileResponse",
            ),
            TerraFinCapability(
                name="valuation",
                description=(
                    "Run DCF, reverse DCF, relative valuation, and Graham Number for a ticker. "
                    "Optional inputs let the agent mirror the frontend's DCF input form: "
                    "`projection_years` (5/10/15) sets the explicit forecast horizon; "
                    "`fcf_base_source` (`auto`/`3yr_avg`/`ttm`/`latest_annual`) picks the base "
                    "FCF/share — `auto` cascades 3yr_avg → annual → ttm and is the default. "
                    "Supplying ALL three of `breakeven_year`, `breakeven_cash_flow_per_share`, "
                    "and `post_breakeven_growth_pct` switches to turnaround mode: pre-breakeven "
                    "years interpolate linearly from the (possibly negative) current FCF to the "
                    "breakeven value; post-breakeven years compound at the given rate fading "
                    "toward terminal growth. Use turnaround mode when the user is valuing a "
                    "company with current negative FCF whose thesis is a future turn."
                ),
                handler=resolved_service.valuation,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="DCF (incl. turnaround mode), reverse DCF, relative valuation, Graham number.",
                http_route_path="/agent/api/valuation",
                response_model_name="ValuationResponse",
            ),
            TerraFinCapability(
                name="sec_filings",
                description=(
                    "List recent 10-K / 10-Q / 8-K filings for a ticker with SEC EDGAR links. "
                    "Call this ONCE when you need to pivot to a filing not currently in view. The "
                    "response's `latestByForm` dict is the direct lookup: "
                    "`latestByForm['10-K'].accession` / `.primaryDocument` give you everything "
                    "`sec_filing_section` needs. Do NOT scan the flat `filings` array — it's "
                    "chronological, so 8-Ks cluster at the top and the 10-K/10-Q you want may be in "
                    "position 5+.\n"
                    "If a filing is already shown in the user's view context, DON'T call this tool at "
                    "all — the accession and primaryDocument live in `current_view_context.selection`.\n"
                    "OUTPUT FORMAT — pick by question type:\n"
                    "• Quantitative filing analysis ('analyze the 10-Q', 'what do the numbers say'): "
                    "(1) lead with a '## TL;DR' of 3-5 bullets where each bullet is a punchline number "
                    "or concrete insight — no filler adjectives; "
                    "(2) follow with a compact '## Key numbers' table (≤6 rows) comparing current vs "
                    "prior-year period, showing only metrics that move the thesis; tables MUST include "
                    "the `| --- |` header-separator row after the header row; "
                    "(3) narrate with named subsections ('### The X story', '### The Y anomaly') of "
                    "≤3 sentences each, **bolding** one driver number per sentence maximum; "
                    "(4) close with '## Not disclosed in this filing' as a short bulleted list.\n"
                    "• Qualitative/descriptive question ('what is their business', 'how do they make "
                    "money', 'what are the risks'): 2-4 short paragraphs grounded in the full section "
                    "body (you MUST have called sec_filing_section first — don't answer off the 4 KB "
                    "excerpt). Lead with the single most important sentence, then add specifics: "
                    "products/segments, go-to-market, differentiation, any concrete numbers the "
                    "filing discloses. Skip the TL;DR bullets and Key-numbers table — they're for "
                    "quantitative questions, not descriptive ones.\n"
                    "EDITORIAL DISCIPLINE (strict — reviewers will reject otherwise): "
                    "(a) no adjectives not grounded in the filing text — avoid 'notable', 'heavy lifting', "
                    "'nearly wiped', 'pristine'; if you flip management's spin, cite the arithmetic that "
                    "supports the flip (and report the net number management disclosed); "
                    "(b) numbers in the TL;DR MUST match the Key-numbers table exactly — no '+12%' in one "
                    "and '+11.6%' in the other for the same metric; "
                    "(c) when the fixture provides both QoQ and YoY deltas (or both Q and YTD), report "
                    "both — a QoQ drop can hide YoY expansion and vice versa; "
                    "(d) scan every statement for line items moving >50% YoY and surface them — a "
                    "13x jump in a small bucket or a credits line halving is exactly what skimmers want; "
                    "(e) if MD&A rounding or direction contradicts what you compute from the statements, "
                    "report BOTH and prefer the statement-derived number, flagging the discrepancy."
                ),
                handler=resolved_service.sec_filings,
                focus_extractor=_focus_from_input_keys("ticker"),
                summary="List recent 10-K / 10-Q / 8-K filings for a ticker with EDGAR URLs.",
                http_route_path="/agent/api/sec-filings",
                response_model_name="SecFilingsListResponse",
            ),
            TerraFinCapability(
                name="sec_filing_document",
                description=(
                    "Fetch the table of contents (section titles, slugs, and sizes) for a specific "
                    "10-K, 10-Q, or other SEC filing. Returns structure only — use `sec_filing_section` "
                    "to pull the actual prose. Requires the accession and primaryDocument fields from "
                    "`sec_filings` or the current view context.\n"
                    "Analyst discovery protocol — do NOT assume fixed item numbers across different "
                    "forms. Instead, scan the TOC for titles containing these keywords:\n"
                    "• Financial Data: 'Financial Statements', 'Notes', 'Consolidated Statements'.\n"
                    "• Strategy & Operations: 'Business', 'Management's Discussion', 'MD&A'.\n"
                    "• Risk & Legal: 'Risk Factors', 'Legal Proceedings', 'Controls'.\n"
                    "Plan to fetch the specific sections that contain the evidence needed for your "
                    "answer rather than guessing from summaries."
                ),
                handler=resolved_service.sec_filing_document,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="Filing table-of-contents (sections + char counts) without full body.",
                http_route_path="/agent/api/sec-filing-document",
                response_model_name="SecFilingDocumentResponse",
            ),
            TerraFinCapability(
                name="sec_filing_section",
                description=(
                    "Fetch the verbatim markdown body of a single filing section by slug. "
                    "The slug MUST come verbatim from a prior `sec_filing_document` call's TOC — "
                    "NEVER guess slug names from SEC filing conventions (the parser does not always "
                    "match convention; trust the actual TOC, not your prior knowledge).\n"
                    "\n"
                    "REQUIRED WORKFLOW (follow in order):\n"
                    "1. Call `sec_filing_document(ticker, accession, primaryDocument, form)` first to "
                    "obtain the TOC. Every entry has `{slug, text, charCount}`.\n"
                    "2. Pick the slug whose `text` matches what the user is asking about. If no text "
                    "matches cleanly (e.g. user asked about 'earnings' but there is no Item labelled "
                    "'Financial Statements'), use `charCount` as a size signal — the LARGEST section "
                    "in the relevant Part usually contains the content. 10-K MD&A and Financial "
                    "Statements often appear as a single very large section when the parser misses the "
                    "Item 7 / Item 8 split; a 200 KB section body in Part II is almost certainly "
                    "financial reporting regardless of what its heading says.\n"
                    "3. Pass that exact slug string to this tool. Do not reformat it, translate it, or "
                    "guess a canonical form.\n"
                    "\n"
                    "IF THIS TOOL RETURNS 'section not found': do NOT tell the user the section "
                    "doesn't exist. The error response includes the full list of available slugs with "
                    "their sizes. Pick one from that list (prefer the largest one in the relevant Part "
                    "if no name matches), and retry this tool immediately. Only after a second real "
                    "failure should you report inability to find the content.\n"
                    "\n"
                    "OUTPUT PROPERTIES:\n"
                    "- Returns raw, un-truncated markdown including tables. Use the tables to "
                    "recompute margins, growth rates, and capital allocation signals directly from "
                    "source data — do not fall back to the `financials` summary tool.\n"
                    "- If the user is viewing a filing, the `sectionExcerpt` in their view-context is "
                    "only ~4 KB. Substantive questions (strategy, full financials, segment detail) "
                    "REQUIRE this tool to fetch the full section body (often 100 KB+).\n"
                    "\n"
                    "VERBATIM CITATION RULE:\n"
                    "When you quote risk factors, MD&A language, forward-looking statements, or "
                    "legal commitments from the returned body, copy the exact wording inside "
                    "quotation marks and name the section. Do NOT paraphrase — users need to be "
                    "able to verify what the filing actually says, not what you think it says. "
                    "Paraphrasing into friendlier English in safety-sensitive sections is a bug."
                ),
                handler=resolved_service.sec_filing_section,
                focus_extractor=_focus_from_input_keys("ticker"),
                backgroundable=True,
                summary="Verbatim markdown body of one filing section by slug.",
                http_route_path="/agent/api/sec-filing-section",
                response_model_name="SecFilingSectionResponse",
            ),
        ]
    )
    return registry
