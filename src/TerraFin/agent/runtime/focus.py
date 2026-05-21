"""Focus extractors and artifact builders bound to specific capabilities.

These small functions are wired into `TerraFinCapability` registrations in
`runtime.capability.build_default_capability_registry`. Keeping them here
keeps the registry file focused on registration data.
"""
from collections.abc import Iterable, Mapping
from typing import Any

from .artifacts import FocusExtractor, TerraFinArtifact, _dedupe, _utc_now


def _focus_from_input_keys(*keys: str) -> FocusExtractor:
    def _extract(inputs: Mapping[str, Any], _: Mapping[str, Any]) -> tuple[str, ...]:
        values: list[str] = []
        for key in keys:
            value = inputs.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                values.append(value)
                continue
            if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
                values.extend(str(item) for item in value)
                continue
            values.append(str(value))
        return tuple(_dedupe(values))

    return _extract


def _resolve_focus(_: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[str, ...]:
    name = payload.get("name")
    if name is None:
        return ()
    return tuple(_dedupe([str(name)]))


def _economic_focus(inputs: Mapping[str, Any], _: Mapping[str, Any]) -> tuple[str, ...]:
    indicators = inputs.get("indicators")
    if indicators is None:
        return ()
    if isinstance(indicators, str):
        return tuple(_dedupe(part for part in indicators.split(",")))
    if isinstance(indicators, Iterable) and not isinstance(indicators, (bytes, bytearray, dict)):
        return tuple(_dedupe(str(item) for item in indicators))
    return tuple(_dedupe([str(indicators)]))


def _chart_focus(inputs: Mapping[str, Any], _: Mapping[str, Any]) -> tuple[str, ...]:
    value = inputs.get("data_or_names")
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        names = [str(item) for item in value if isinstance(item, str)]
        return tuple(_dedupe(names))
    return ()


def _chart_artifact(
    session_id: str,
    capability_name: str,
    inputs: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> TerraFinArtifact | None:
    if not payload.get("ok"):
        return None
    chart_url = payload.get("chartUrl")
    chart_session_id = payload.get("sessionId")
    if chart_url is None or chart_session_id is None:
        return None

    focused = _chart_focus(inputs, payload)
    if focused:
        title = f"Chart: {', '.join(focused)}"
    else:
        title = "Chart Session"

    return TerraFinArtifact(
        artifact_id=str(chart_session_id),
        kind="chart",
        title=title,
        session_id=session_id,
        capability_name=capability_name,
        created_at=_utc_now(),
        payload={
            "chartUrl": str(chart_url),
            "sessionId": str(chart_session_id),
        },
    )
