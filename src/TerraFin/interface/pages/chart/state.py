from collections import OrderedDict
from copy import deepcopy
import uuid

from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame


DEFAULT_SESSION_ID = "default"

_EMPTY_PAYLOAD = {"mode": "multi", "series": [], "dataLength": 0}
_chart_payloads_by_session: dict[str, dict] = {}
_chart_sources_by_session: dict[str, dict] = {}
_chart_selection_by_session: dict[str, dict | None] = {}
_chart_view_by_session: dict[str, str] = {}
_chart_named_series_by_session: dict[str, dict[str, TimeSeriesDataFrame]] = {}
_chart_named_series_items_by_session: dict[str, dict[str, dict]] = {}
_chart_pinned_names_by_session: dict[str, set[str]] = {}
_chart_history_by_session: dict[str, dict[str, dict]] = {}
_indicator_overlays_by_signature: OrderedDict[str, list[dict]] = OrderedDict()
_MAX_INDICATOR_CACHE_ITEMS = 128


def _ensure_session(session_id: str) -> None:
    if session_id not in _chart_payloads_by_session:
        _chart_payloads_by_session[session_id] = dict(_EMPTY_PAYLOAD)
    if session_id not in _chart_sources_by_session:
        _chart_sources_by_session[session_id] = dict(_EMPTY_PAYLOAD)
    if session_id not in _chart_selection_by_session:
        _chart_selection_by_session[session_id] = None
    if session_id not in _chart_view_by_session:
        _chart_view_by_session[session_id] = "daily"
    if session_id not in _chart_named_series_by_session:
        _chart_named_series_by_session[session_id] = {}
    if session_id not in _chart_named_series_items_by_session:
        _chart_named_series_items_by_session[session_id] = {}
    if session_id not in _chart_pinned_names_by_session:
        _chart_pinned_names_by_session[session_id] = set()
    if session_id not in _chart_history_by_session:
        _chart_history_by_session[session_id] = {}


def reset_chart_state(df: TimeSeriesDataFrame | None, format_dataframe) -> None:
    _chart_payloads_by_session.clear()
    _chart_sources_by_session.clear()
    _chart_selection_by_session.clear()
    _chart_view_by_session.clear()
    _chart_named_series_by_session.clear()
    _chart_named_series_items_by_session.clear()
    _chart_pinned_names_by_session.clear()
    _chart_history_by_session.clear()
    _indicator_overlays_by_signature.clear()

    if df is None:
        _chart_payloads_by_session[DEFAULT_SESSION_ID] = dict(_EMPTY_PAYLOAD)
        _chart_sources_by_session[DEFAULT_SESSION_ID] = dict(_EMPTY_PAYLOAD)
        _chart_selection_by_session[DEFAULT_SESSION_ID] = None
        _chart_view_by_session[DEFAULT_SESSION_ID] = "daily"
        return

    payload = format_dataframe(df)
    _chart_payloads_by_session[DEFAULT_SESSION_ID] = payload
    _chart_sources_by_session[DEFAULT_SESSION_ID] = payload
    _chart_selection_by_session[DEFAULT_SESSION_ID] = None
    _chart_view_by_session[DEFAULT_SESSION_ID] = "daily"
    _chart_named_series_by_session[DEFAULT_SESSION_ID] = {}
    _chart_named_series_items_by_session[DEFAULT_SESSION_ID] = {}
    _chart_pinned_names_by_session[DEFAULT_SESSION_ID] = set()
    _chart_history_by_session[DEFAULT_SESSION_ID] = {}

    series = payload.get("series", [])
    if not isinstance(series, list) or len(series) != 1:
        return

    item = series[0]
    if not isinstance(item, dict) or item.get("indicator") or not item.get("id"):
        return

    display_name = str(item["id"])
    df.name = display_name
    _chart_named_series_by_session[DEFAULT_SESSION_ID][display_name] = df
    _chart_named_series_items_by_session[DEFAULT_SESSION_ID][display_name] = dict(item)

    data = item.get("data", [])
    times = [
        point.get("time")
        for point in data
        if isinstance(point, dict) and isinstance(point.get("time"), str)
    ]
    _chart_history_by_session[DEFAULT_SESSION_ID][display_name] = {
        "loadedStart": times[0] if times else None,
        "loadedEnd": times[-1] if times else None,
        "isComplete": True,
        "hasOlder": False,
        "seedPeriod": None,
        "backfillInFlight": False,
        "requestToken": uuid.uuid4().hex,
    }


def get_chart_payload(session_id: str = DEFAULT_SESSION_ID) -> dict:
    _ensure_session(session_id)
    return _chart_payloads_by_session[session_id]


def set_chart_payload(payload: dict, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_payloads_by_session[session_id] = payload


def get_chart_source(session_id: str = DEFAULT_SESSION_ID) -> dict:
    _ensure_session(session_id)
    return _chart_sources_by_session[session_id]


def set_chart_source(source: dict, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_sources_by_session[session_id] = source


def get_chart_selection(session_id: str = DEFAULT_SESSION_ID) -> dict | None:
    _ensure_session(session_id)
    return _chart_selection_by_session[session_id]


def set_chart_selection(selection: dict | None, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_selection_by_session[session_id] = selection


def get_chart_view(session_id: str = DEFAULT_SESSION_ID) -> str:
    _ensure_session(session_id)
    return _chart_view_by_session[session_id]


def set_chart_view(view: str, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_view_by_session[session_id] = view


# ── Named series (interactive search-based chart management) ──────────

def get_named_series(session_id: str = DEFAULT_SESSION_ID) -> dict[str, TimeSeriesDataFrame]:
    _ensure_session(session_id)
    return _chart_named_series_by_session[session_id]


def get_named_series_items(session_id: str = DEFAULT_SESSION_ID) -> dict[str, dict]:
    _ensure_session(session_id)
    return _chart_named_series_items_by_session[session_id]


def add_named_series(
    name: str,
    df: TimeSeriesDataFrame,
    session_id: str = DEFAULT_SESSION_ID,
    *,
    formatted_item: dict | None = None,
) -> None:
    _ensure_session(session_id)
    _chart_named_series_by_session[session_id][name] = df
    if formatted_item is not None:
        _chart_named_series_items_by_session[session_id][name] = formatted_item


def remove_named_series(name: str, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_named_series_by_session[session_id].pop(name, None)
    _chart_named_series_items_by_session[session_id].pop(name, None)


def get_series_names(session_id: str = DEFAULT_SESSION_ID) -> list[str]:
    _ensure_session(session_id)
    return list(_chart_named_series_by_session[session_id].keys())


def clear_named_series(session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_named_series_by_session[session_id].clear()
    _chart_named_series_items_by_session[session_id].clear()


def get_series_history_by_name(session_id: str = DEFAULT_SESSION_ID) -> dict[str, dict]:
    _ensure_session(session_id)
    return _chart_history_by_session[session_id]


def set_series_history_status(name: str, status: dict, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_history_by_session[session_id][name] = dict(status)


def get_series_history_status(name: str, session_id: str = DEFAULT_SESSION_ID) -> dict | None:
    _ensure_session(session_id)
    status = _chart_history_by_session[session_id].get(name)
    if status is None:
        return None
    return dict(status)


def remove_series_history_status(name: str, session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_history_by_session[session_id].pop(name, None)


def clear_series_history(session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_history_by_session[session_id].clear()


# ── Pinned series ─────────────────────────────────────────────────────

def set_pinned_names(names: set[str], session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_pinned_names_by_session[session_id] = set(names)


def get_pinned_names(session_id: str = DEFAULT_SESSION_ID) -> set[str]:
    _ensure_session(session_id)
    return _chart_pinned_names_by_session[session_id]


def clear_pinned_names(session_id: str = DEFAULT_SESSION_ID) -> None:
    _ensure_session(session_id)
    _chart_pinned_names_by_session[session_id].clear()


def get_indicator_overlays(signature: str) -> list[dict] | None:
    overlays = _indicator_overlays_by_signature.get(signature)
    if overlays is None:
        return None
    _indicator_overlays_by_signature.move_to_end(signature)
    return deepcopy(overlays)


def set_indicator_overlays(signature: str, overlays: list[dict]) -> None:
    _indicator_overlays_by_signature[signature] = deepcopy(overlays)
    _indicator_overlays_by_signature.move_to_end(signature)
    while len(_indicator_overlays_by_signature) > _MAX_INDICATOR_CACHE_ITEMS:
        _indicator_overlays_by_signature.popitem(last=False)
