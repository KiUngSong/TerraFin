from collections.abc import Mapping
from copy import deepcopy
from typing import Any


HOSTED_TOOL_CONTRACT_VERSION = "v1"


def _string_array_or_scalar(*, max_items: int | None = None) -> dict[str, Any]:
    array_schema: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
    if max_items is not None:
        array_schema["maxItems"] = max_items
    return {
        "anyOf": [
            {"type": "string"},
            array_schema,
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
    "news": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "query": {"type": "string", "minLength": 1},
                "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            required=[],
        ),
        "response_model": "NewsResponse",
    },
    "consensus": {
        "input_schema": _object_schema(
            properties={"ticker": {"type": "string", "minLength": 1}},
            required=["ticker"],
        ),
        "response_model": "ConsensusResponse",
    },
    "pattern_scan": {
        "input_schema": _object_schema(
            properties={
                "group": {"type": "string", "minLength": 1},
                "tickers": _string_array_or_scalar(max_items=500),
                "severity_min": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "low",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
            },
            required=[],
        ),
        "response_model": "PatternScanResponse",
    },
    "relative_strength": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "universe": {
                    "type": "string",
                    "enum": [
                        "sp500",
                        "nasdaq100",
                        "kospi200",
                        "sp500+kospi200",
                        "sp500+nasdaq100+kospi200",
                        "watchlist",
                    ],
                    "default": "sp500",
                },
                "top_n": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            required=[],
        ),
        "response_model": "RelativeStrengthResponse",
    },
    "patterns": {
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
        "response_model": "PatternsResponse",
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
                "force_refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Set true only when serving time-sensitive snapshots "
                        "(e.g. mid-session quote, freshly-closed bar that may "
                        "still be cached from the prior session). Default false "
                        "keeps the cache hot to avoid hammering upstream. "
                        "Only honored for yfinance-backed names (indices, "
                        "tickers, VIX/VVIX/SKEW/MOVE/Treasury yields); "
                        "composite/private indicators (Vol Regime, VVIX/VIX "
                        "Ratio, Fear & Greed, Net Breadth, CAPE, "
                        "Trailing-Forward P/E Spread, SPX GEX) ignore this "
                        "flag — their TTLs govern freshness."
                    ),
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
                "form": {
                    "type": "string",
                    "minLength": 1,
                    "default": "10-Q",
                    "description": (
                        "Filing form string from sec_filings (e.g. '10-K', '10-Q', "
                        "'8-K', '8-K/A'). MUST be passed for 8-K filings — otherwise "
                        "EX-99.x exhibit bodies (earnings PR, CFO commentary) are not "
                        "appended and the agent only sees the 4 KB cover sheet."
                    ),
                },
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
                "form": {
                    "type": "string",
                    "minLength": 1,
                    "default": "10-Q",
                    "description": (
                        "Filing form string from sec_filings (e.g. '10-K', '10-Q', "
                        "'8-K', '8-K/A'). MUST be passed for 8-K filings so EX-99.x "
                        "exhibit slugs (exhibit-991-press-release, "
                        "exhibit-992-supplemental-material) are reachable."
                    ),
                },
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
    "fcf_history": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "years": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            required=["ticker"],
        ),
        "response_model": "FcfHistoryResponse",
    },
    "similarity_search": {
        "input_schema": _object_schema(
            properties={
                "ticker": {"type": "string", "minLength": 1},
                "universe": {
                    "type": "string",
                    "enum": ["sp500", "nasdaq100", "kospi200", "sp500+nasdaq100+kospi200", "sp500+kospi200", "watchlist"],
                    "default": "sp500+nasdaq100+kospi200",
                },
                "period": {
                    "type": "string",
                    "enum": ["1y", "2y", "6m"],
                    "default": "1y",
                },
                "top_n": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            required=["ticker"],
        ),
        "response_model": "SimilaritySearchResponse",
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


# ---------------------------------------------------------------------------
# Argument validation
#
# The schemas above were advisory until this existed: the dispatch path went
# straight from the model's arguments to `capability.handler(**kwargs)`, so
# `additionalProperties: False` enforced nothing. That mattered because several
# handlers accept parameters the schema deliberately hides — `valuation` takes
# `base_growth_pct`, `terminal_growth_pct`, and `beta`, which let a caller tilt
# a valuation into agreeing with whatever it already believed.
#
# Validating here makes the tool surface the schema says it is. Internal Python
# callers (routes, the service, a controller) are unaffected by design: they
# hold the full signature, and locking the *agent* is the point.
#
# Hand-rolled rather than pulling in `jsonschema`, because the contracts use a
# small fixed subset: type, enum, minimum, maximum, minLength, maxItems, anyOf,
# items, required, additionalProperties.
# ---------------------------------------------------------------------------

_TYPE_NAMES = {
    "string": str,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _type_error(value: Any, expected: str) -> str | None:
    """None when `value` satisfies `expected`, else a human-readable reason."""
    if expected == "integer":
        # bool is an int subclass in Python; a JSON boolean is not an integer.
        if isinstance(value, bool):
            return "expected an integer, got a boolean"
        if isinstance(value, int):
            return None
        # Models routinely emit 7.0 for an integer field; accept it losslessly.
        if isinstance(value, float) and value.is_integer():
            return None
        return f"expected an integer, got {type(value).__name__}"
    if expected == "number":
        if isinstance(value, bool):
            return "expected a number, got a boolean"
        return None if isinstance(value, (int, float)) else f"expected a number, got {type(value).__name__}"
    expected_type = _TYPE_NAMES.get(expected)
    if expected_type is None:
        return None  # unknown type keyword: nothing to assert
    if expected == "string" and isinstance(value, bool):
        return "expected a string, got a boolean"
    return None if isinstance(value, expected_type) else f"expected {expected}, got {type(value).__name__}"


def _check_value(name: str, value: Any, schema: dict[str, Any]) -> list[str]:
    if "anyOf" in schema:
        branches: list[dict[str, Any]] = schema["anyOf"]
        reasons = [_check_value(name, value, branch) for branch in branches]
        if any(not branch_errors for branch_errors in reasons):
            return []
        # Exactly one branch matching on type means the value's *shape* is right
        # and something inside it is wrong — a bound, or an item's type. Report
        # that branch's errors. The generic "expected string or array, got list"
        # would restate the value's own type back at the model, which cannot act
        # on it and would resend the same argument until the retry budget ends.
        matched = [
            branch_errors
            for branch, branch_errors in zip(branches, reasons)
            if branch.get("type") and not _type_error(value, branch["type"])
        ]
        if len(matched) == 1:
            return matched[0]
        allowed = " or ".join(str(branch.get("type", "?")) for branch in branches)
        return [f"{name}: expected {allowed}, got {type(value).__name__}"]

    errors: list[str] = []
    declared_type = schema.get("type")
    if declared_type:
        reason = _type_error(value, declared_type)
        if reason:
            return [f"{name}: {reason}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{name}: {value!r} is not one of {schema['enum']}")
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        errors.append(f"{name}: {value} is below the minimum of {schema['minimum']}")
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        errors.append(f"{name}: {value} is above the maximum of {schema['maximum']}")
    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        errors.append(f"{name}: must be at least {schema['minLength']} character(s)")
    if "maxItems" in schema and isinstance(value, list) and len(value) > schema["maxItems"]:
        errors.append(f"{name}: at most {schema['maxItems']} item(s), got {len(value)}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_check_value(f"{name}[{index}]", item, schema["items"]))
    return errors


def validate_tool_arguments(
    tool_name: str, arguments: Mapping[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    """Validate model-supplied arguments against a tool's declared input schema.

    Returns `(problems, arguments_to_dispatch)`. `problems` is a list of
    human-readable strings, empty when the arguments are acceptable. The second
    element is the dict the caller should actually dispatch: integral floats are
    narrowed to `int` for integer-typed fields, because accepting `20.0` without
    narrowing it only moves the failure downstream — `relative_strength(top_n=20.0)`
    reaches `ordered[:top_n]` and raises `TypeError: slice indices must be
    integers`, which no error classifier recognises, so the whole run aborts.

    Unknown tools validate vacuously — an unregistered tool is a different error,
    reported elsewhere. Callers must pass the *capability* name: task variants are
    exposed as `start_<capability>_task` but are handed the capability's own
    schema, so they validate against the same contract.
    """
    contract = HOSTED_TOOL_CONTRACTS.get(tool_name)
    if contract is None:
        return [], dict(arguments)
    schema = contract.get("input_schema") or {}
    properties: dict[str, Any] = schema.get("properties") or {}

    errors: list[str] = []
    for required_name in schema.get("required") or []:
        if required_name not in arguments:
            errors.append(f"{required_name}: required")
        elif arguments[required_name] is None:
            # An explicit null satisfies "key present" but not the handler, which
            # goes on to call `.upper()` on it. Optional nulls stay allowed below.
            errors.append(f"{required_name}: required, but was null")

    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            errors.append(
                f"unknown argument(s) {unknown}; this tool accepts only {sorted(properties)}"
            )

    normalized = dict(arguments)
    for name, value in arguments.items():
        declared = properties.get(name)
        if declared is None or value is None:
            continue
        errors.extend(_check_value(name, value, declared))
        if declared.get("type") == "integer" and isinstance(value, float) and value.is_integer():
            normalized[name] = int(value)
    return errors, normalized
