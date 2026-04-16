from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException

from TerraFin.data import DataFactory
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.data.providers.economic import indicator_registry
from TerraFin.data.providers.market import INDEX_DESCRIPTIONS, INDEX_MAP, MARKET_INDICATOR_REGISTRY
from TerraFin.interface.chart.state import get_named_series


_MACRO_NAME_ALIASES = {
    "nasdaq composite": "Nasdaq",
    "nasdaq composite index": "Nasdaq",
    "nasdaq comp": "Nasdaq",
    "dow jones": "Dow",
    "dow jones industrial average": "Dow",
    "s&p500": "S&P 500",
    "s&p 500 index": "S&P 500",
    "nikkei": "Nikkei 225",
}


def _display_name(name: str) -> str:
    return name.upper() if name == name.lower() else name


def _case_insensitive_match(name: str, candidates: Iterable[str]) -> str | None:
    normalized = name.strip().casefold()
    if not normalized:
        return None
    for candidate in candidates:
        if candidate.casefold() == normalized:
            return candidate
    return None


def canonical_macro_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        return stripped
    alias = _MACRO_NAME_ALIASES.get(stripped.casefold())
    if alias:
        return alias
    match = _case_insensitive_match(stripped, INDEX_MAP.keys())
    if match:
        return match
    match = _case_insensitive_match(stripped, MARKET_INDICATOR_REGISTRY.keys())
    if match:
        return match
    try:
        match = _case_insensitive_match(stripped, indicator_registry._indicators.keys())
        if match:
            return match
    except Exception:
        pass
    return _display_name(stripped)


def resolve_macro_type(name: str) -> str | None:
    resolved_name = canonical_macro_name(name)
    if resolved_name in INDEX_MAP:
        return "index"
    if resolved_name in MARKET_INDICATOR_REGISTRY:
        if "Treasury" in resolved_name:
            return "treasury"
        if resolved_name in ("VIX", "VVIX", "SKEW"):
            return "volatility"
        return "indicator"
    try:
        if resolved_name in indicator_registry._indicators:
            return "economic"
    except Exception:
        pass
    return None


def get_macro_description(name: str) -> str:
    resolved_name = canonical_macro_name(name)
    if resolved_name in INDEX_DESCRIPTIONS:
        return INDEX_DESCRIPTIONS[resolved_name]
    if resolved_name in MARKET_INDICATOR_REGISTRY:
        return MARKET_INDICATOR_REGISTRY[resolved_name].description
    if resolved_name in indicator_registry._indicators:
        return indicator_registry._indicators[resolved_name].description
    return ""


def load_macro_dataframe(
    name: str,
    *,
    session_id: str | None = None,
) -> tuple[str, str, TimeSeriesDataFrame]:
    resolved_name = canonical_macro_name(name)
    indicator_type = resolve_macro_type(resolved_name)
    if indicator_type is None:
        raise HTTPException(status_code=404, detail=f"Unknown macro instrument: '{resolved_name}'")

    description = get_macro_description(resolved_name)

    if session_id:
        session_df = get_named_series(session_id).get(resolved_name)
        if session_df is not None:
            session_df.name = resolved_name
            return indicator_type, description, session_df

    try:
        factory = DataFactory()
        if hasattr(factory, "get_recent_history"):
            history_chunk = factory.get_recent_history(resolved_name, period="3y")
            df = history_chunk.frame
        else:
            df = factory.get(resolved_name)
    except Exception:
        try:
            df = DataFactory().get(resolved_name)
        except Exception as fallback_exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch data: {fallback_exc}") from fallback_exc

    df.name = resolved_name
    return indicator_type, description, df


def build_macro_info_payload(
    name: str,
    description: str,
    df: TimeSeriesDataFrame,
    *,
    indicator_type: str,
) -> dict[str, Any]:
    closes = df["close"].dropna()
    current = float(closes.iloc[-1]) if len(closes) > 0 else None
    previous = float(closes.iloc[-2]) if len(closes) > 1 else None
    change = round(current - previous, 4) if current is not None and previous is not None else None
    change_pct = round((change / previous) * 100, 2) if change is not None and previous else None

    return {
        "name": canonical_macro_name(name),
        "type": indicator_type,
        "description": description,
        "currentValue": current,
        "change": change,
        "changePercent": change_pct,
    }
