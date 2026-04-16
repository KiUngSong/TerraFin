from __future__ import annotations

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
            properties={"ticker": {"type": "string", "minLength": 1}},
            required=["ticker"],
        ),
        "response_model": "ValuationResponse",
    },
}


def get_hosted_tool_contract(capability_name: str) -> dict[str, Any]:
    try:
        return deepcopy(HOSTED_TOOL_CONTRACTS[capability_name])
    except KeyError as exc:
        raise KeyError(f"No explicit hosted tool contract registered for capability '{capability_name}'.") from exc
