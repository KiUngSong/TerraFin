from copy import deepcopy
from typing import Any


HOSTED_TOOL_CONTRACT_VERSION = "v1"


def _string_array_or_scalar() -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ]
    }


def _object_schema(
    *,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        payload["required"] = required
    return payload


HOSTED_TOOL_CONTRACTS: dict[str, dict[str, Any]] = {
    "resolve": {
        "input_schema": _object_schema(
            properties={"query": {"type": "string", "minLength": 1}},
            required=["query"],
        ),
        "response_model": "ResolveResponse",
    },
    "market_data": {
        "input_schema": _object_schema(
            properties={
                "name": {"type": "string", "minLength": 1},
                "depth": {"type": "string", "enum": ["auto", "recent", "full"], "default": "auto"},
                "view": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "yearly"],
                    "default": "daily",
                },
            },
            required=["name"],
        ),
        "response_model": "MarketDataResponse",
    },
    "indicators": {
        "input_schema": _object_schema(
            properties={
                "name": {"type": "string", "minLength": 1},
                "indicators": _string_array_or_scalar(),
                "depth": {"type": "string", "enum": ["auto", "recent", "full"], "default": "auto"},
                "view": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "yearly"],
                    "default": "daily",
                },
            },
            required=["name", "indicators"],
        ),
        "response_model": "IndicatorsResponse",
    },
    "market_snapshot": {
        "input_schema": _object_schema(
            properties={
                "name": {"type": "string", "minLength": 1},
                "depth": {"type": "string", "enum": ["auto", "recent", "full"], "default": "auto"},
                "view": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "yearly"],
                    "default": "daily",
                },
            },
            required=["name"],
        ),
        "response_model": "MarketSnapshotResponse",
    },
    "lppl_analysis": {
        "input_schema": _object_schema(
            properties={
                "name": {"type": "string", "minLength": 1},
                "depth": {"type": "string", "enum": ["auto", "recent", "full"], "default": "auto"},
                "view": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "yearly"],
                    "default": "daily",
                },
            },
            required=["name"],
        ),
        "response_model": "LPPLAnalysisResponse",
    },
    "company_info": {
        "input_schema": _object_schema(
            properties={"ticker": {"type": "string", "minLength": 1}},
            required=["ticker"],
        ),
        "response_model": "CompanyInfoResponse",
    },
    "earnings": {
        "input_schema": _object_schema(
            properties={"ticker": {"type": "string", "minLength": 1}},
            required=["ticker"],
        ),
        "response_model": "EarningsResponse",
    },
    "financials": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "statement": {
                    "type": "string",
                    "enum": ["income", "balance", "cashflow"],
                    "default": "income",
                },
                "period": {"type": "string", "enum": ["annual", "quarter"], "default": "annual"},
            },
            required=["ticker"],
        ),
        "response_model": "FinancialStatementResponse",
    },
    "portfolio": {
        "input_schema": _object_schema(
            properties={"guru": {"type": "string", "minLength": 1}},
            required=["guru"],
        ),
        "response_model": "PortfolioResponse",
    },
    "economic": {
        "input_schema": _object_schema(
            properties={"indicators": _string_array_or_scalar()},
            required=["indicators"],
        ),
        "response_model": "EconomicResponse",
    },
    "macro_focus": {
        "input_schema": _object_schema(
            properties={
                "name": {"type": "string", "minLength": 1},
                "depth": {"type": "string", "enum": ["auto", "recent", "full"], "default": "auto"},
                "view": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "yearly"],
                    "default": "daily",
                },
            },
            required=["name"],
        ),
        "response_model": "MacroFocusResponse",
    },
    "calendar_events": {
        "input_schema": _object_schema(
            properties={
                "year": {"type": "integer", "minimum": 1970, "maximum": 2200},
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "categories": _string_array_or_scalar(),
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            required=["year", "month"],
        ),
        "response_model": "CalendarResponse",
    },
    "open_chart": {
        "input_schema": _object_schema(
            properties={
                "data_or_names": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ]
                }
            },
            required=["data_or_names"],
        ),
        "response_model": "ChartOpenResponse",
    },
    "current_view_context": {
        "input_schema": _object_schema(
            properties={"viewContextId": {"type": "string", "minLength": 1}},
            required=[],
        ),
        "response_model": "HostedViewContextResponse",
    },
    "fundamental_screen": {
        "input_schema": _object_schema(
            properties={"ticker": {"type": "string", "minLength": 1}},
            required=["ticker"],
        ),
        "response_model": "FundamentalScreenResponse",
    },
    "risk_profile": {
        "input_schema": _object_schema(
            properties={
                "name": {"type": "string", "minLength": 1},
                "depth": {"type": "string", "enum": ["auto", "recent", "full"], "default": "auto"},
            },
            required=["name"],
        ),
        "response_model": "RiskProfileResponse",
    },
    "valuation": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "projection_years": {"type": "integer", "enum": [5, 10, 15]},
                "fcf_base_source": {
                    "type": "string",
                    "enum": ["auto", "3yr_avg", "ttm", "latest_annual"],
                },
                "breakeven_year": {"type": "integer", "minimum": 1, "maximum": 15},
                "breakeven_cash_flow_per_share": {"type": "number"},
                "post_breakeven_growth_pct": {"type": "number"},
            },
            required=["ticker"],
        ),
        "response_model": "ValuationResponse",
    },
    "sec_filings": {
        "input_schema": _object_schema(
            properties={"ticker": {"type": "string", "minLength": 1}},
            required=["ticker"],
        ),
        "response_model": "SecFilingsListResponse",
    },
    "sec_filing_document": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "accession": {"type": "string", "minLength": 1},
                "primaryDocument": {"type": "string", "minLength": 1},
                "form": {"type": "string", "minLength": 1, "default": "10-Q"},
            },
            required=["ticker", "accession", "primaryDocument"],
        ),
        "response_model": "SecFilingDocumentResponse",
    },
    "sec_filing_section": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "accession": {"type": "string", "minLength": 1},
                "primaryDocument": {"type": "string", "minLength": 1},
                "sectionSlug": {"type": "string", "minLength": 1},
                "form": {"type": "string", "minLength": 1, "default": "10-Q"},
            },
            required=["ticker", "accession", "primaryDocument", "sectionSlug"],
        ),
        "response_model": "SecFilingSectionResponse",
    },
    "fear_greed": {
        "input_schema": _object_schema(properties={}, required=[]),
        "response_model": "FearGreedResponse",
    },
    "sp500_dcf": {
        "input_schema": _object_schema(properties={}, required=[]),
        "response_model": "DCFValuationResponse",
    },
    "beta_estimate": {
        "input_schema": _object_schema(
            properties={"ticker": {"type": "string", "minLength": 1}},
            required=["ticker"],
        ),
        "response_model": "BetaEstimateResponse",
    },
    "top_companies": {
        "input_schema": _object_schema(properties={}, required=[]),
        "response_model": "TopCompaniesResponse",
    },
    "market_regime": {
        "input_schema": _object_schema(properties={}, required=[]),
        "response_model": "MarketRegimeResponse",
    },
    "trailing_forward_pe": {
        "input_schema": _object_schema(properties={}, required=[]),
        "response_model": "TrailingForwardPeSpreadResponse",
    },
    "market_breadth": {
        "input_schema": _object_schema(properties={}, required=[]),
        "response_model": "MarketBreadthResponse",
    },
    "watchlist": {
        "input_schema": _object_schema(properties={}, required=[]),
        "response_model": "WatchlistResponse",
    },
    # Persona-consult tools. Each takes a single `question` arg (the
    # orchestrator-scoped prompt sent to the persona subagent) and returns
    # a `GuruResearchMemo`-shaped payload. See
    # `docs/agent/architecture.md#orchestrator--persona-subagents`.
    "consult_warren_buffett": {
        "input_schema": _object_schema(
            properties={"question": {"type": "string", "minLength": 1}},
            required=["question"],
        ),
        "response_model": "GuruResearchMemo",
    },
    "consult_howard_marks": {
        "input_schema": _object_schema(
            properties={"question": {"type": "string", "minLength": 1}},
            required=["question"],
        ),
        "response_model": "GuruResearchMemo",
    },
    "consult_stanley_druckenmiller": {
        "input_schema": _object_schema(
            properties={"question": {"type": "string", "minLength": 1}},
            required=["question"],
        ),
        "response_model": "GuruResearchMemo",
    },
}


def get_hosted_tool_contract(capability_name: str) -> dict[str, Any]:
    try:
        return deepcopy(HOSTED_TOOL_CONTRACTS[capability_name])
    except KeyError as exc:
        raise KeyError(f"No explicit hosted tool contract registered for capability '{capability_name}'.") from exc
