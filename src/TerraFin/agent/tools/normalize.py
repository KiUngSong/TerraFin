"""Argument repair, alias maps, and heuristic helpers for hosted tools."""
from typing import Any

from TerraFin.interface.market_insights.payloads import canonical_macro_name, resolve_macro_type
from TerraFin.interface.stock.payloads import resolve_ticker_query


# Map of persona-consult tool name -> guru name. Lives here because the
# adapter consults it during dispatch; keeping it in normalize avoids
# pulling the adapter into the leaves.
_PERSONA_CONSULT_TOOLS = {
    "consult_warren_buffett": "warren-buffett",
    "consult_howard_marks": "howard-marks",
    "consult_stanley_druckenmiller": "stanley-druckenmiller",
}


_EQUITY_INDEX_ALIASES = {
    "spx": "SPY",
    "spx index": "SPY",
    "sp500": "SPY",
    "s&p 500": "SPY",
    "ndx": "QQQ",
    "ndx index": "QQQ",
    "nasdaq-100": "QQQ",
    "nasdaq 100": "QQQ",
    "djia": "DIA",
    "dji": "DIA",
    "dow jones industrial average": "DIA",
    "rty": "IWM",
}


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_common_alias_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments)
    for key in ("name", "ticker"):
        value = normalized.get(key)
        if value is None:
            continue
        alias = _EQUITY_INDEX_ALIASES.get(str(value).strip().casefold())
        if alias:
            normalized[key] = alias
    return normalized


def _repair_symbol_or_name(value: str | None, *, allow_macro: bool) -> str | None:
    if not value:
        return None
    alias = _EQUITY_INDEX_ALIASES.get(str(value).strip().casefold())
    if alias:
        return alias
    canonical = canonical_macro_name(value)
    if allow_macro and resolve_macro_type(canonical) is not None:
        return canonical
    resolved = resolve_ticker_query(value)
    resolved_type = str(resolved.get("type") or "").strip().lower()
    resolved_name = _optional_string(resolved.get("name"))
    if allow_macro and resolved_type == "macro" and resolved_name:
        return resolved_name
    if resolved_type == "stock" and resolved_name:
        return resolved_name
    return None


def _repair_macro_focus_name(value: str | None) -> str | None:
    if not value:
        return None
    canonical = canonical_macro_name(value)
    return canonical if resolve_macro_type(canonical) is not None else None


def _looks_like_equity_index_or_etf(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    normalized = text.casefold()
    if normalized in _EQUITY_INDEX_ALIASES:
        return True
    if normalized in {
        "spy",
        "qqq",
        "dia",
        "vt",
        "iwm",
        "s&p 500",
        "nasdaq",
        "nasdaq 100",
        "dow",
        "dow jones",
        "dow jones industrial average",
        "russell 2000",
    }:
        return True
    try:
        resolved = resolve_ticker_query(text)
    except Exception:
        return False
    resolved_name = _optional_string(resolved.get("name"))
    return (resolved_name or "").upper() in {"SPY", "QQQ", "DIA", "VT", "IWM"}


def _looks_like_descriptive_phrase(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    return " " in text
