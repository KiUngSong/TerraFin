"""FRED-based macro event values overlay.

Enriches calendar events with Latest and Previous values from FRED series
observations. Each FRED release_id maps to a headline series_id.
"""

import json
import logging

import requests

from TerraFin.configuration import load_terrafin_config


_logger = logging.getLogger(__name__)

_FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED release_id (from macro_calendar.py) → headline series_id + display config
# The release_id appears in the event id as "macro-{release_id}-..."
_RELEASE_SERIES: dict[int, dict] = {
    10: {"series_id": "CPIAUCSL", "label": "CPI Index", "fmt": ".1f"},
    46: {"series_id": "PPIACO", "label": "PPI Index", "fmt": ".1f"},
    50: {"series_id": "PAYEMS", "label": "Nonfarm Payrolls (K)", "fmt": ",.0f"},
    53: {"series_id": "GDP", "label": "GDP (B$)", "fmt": ",.1f"},
    21: {"series_id": "FEDFUNDS", "label": "Fed Funds Rate (%)", "fmt": ".2f"},
    54: {"series_id": "PCE", "label": "PCE (B$)", "fmt": ",.1f"},
    9: {"series_id": "RSAFS", "label": "Retail Sales (M$)", "fmt": ",.0f"},
    180: {"series_id": "ICSA", "label": "Initial Claims", "fmt": ",.0f"},
    352: {"series_id": "ADPMNUSNERSA", "label": "ADP Employment (K)", "fmt": ",.0f"},
    82: {"series_id": "MANEMP", "label": "Mfg Employment (K)", "fmt": ",.0f"},
    323: {"series_id": "UMCSENT", "label": "Sentiment Index", "fmt": ".1f"},
    86: {"series_id": "DGORDER", "label": "Durable Goods (M$)", "fmt": ",.0f"},
    475: {"series_id": "JTSJOL", "label": "Job Openings (K)", "fmt": ",.0f"},
    22: {"series_id": "EXHOSLUSM495S", "label": "Existing Home Sales (K)", "fmt": ",.0f"},
    304: {"series_id": "HSN1F", "label": "New Home Sales (K)", "fmt": ",.0f"},
    57: {"series_id": "BOPGSTB", "label": "Trade Balance (M$)", "fmt": ",.0f"},
    13: {"series_id": "INDPRO", "label": "Industrial Prod Index", "fmt": ".1f"},
}

# Cache fetched observations within a single enrichment run
_obs_cache: dict[str, list[dict]] = {}


def enrich_macro_events_all(events: list[dict]) -> list[dict]:
    """Add Latest/Previous values to all macro events from FRED observations."""
    return _enrich(events)


def enrich_macro_events(events: list[dict], year: int, month: int) -> list[dict]:
    """Add Latest/Previous values to macro events from FRED observations."""
    return _enrich(events)


def _enrich(events: list[dict]) -> list[dict]:
    """Core enrichment logic using FRED series observations."""
    api_key = load_terrafin_config().fred.api_key or ""
    if not api_key:
        return events

    # Group events by release_id (extracted from event id: "macro-{release_id}-...")
    for event in events:
        event_id = event.get("id", "")
        parts = event_id.split("-")
        if len(parts) < 2 or parts[0] != "macro":
            continue

        try:
            release_id = int(parts[1])
        except (ValueError, IndexError):
            continue

        series_info = _RELEASE_SERIES.get(release_id)
        if not series_info:
            continue

        series_id = series_info["series_id"]
        obs = _fetch_observations(series_id, api_key)
        if len(obs) < 1:
            continue

        latest = obs[0]
        previous = obs[1] if len(obs) >= 2 else None

        desc_data: dict = {}
        fmt = series_info["fmt"]
        try:
            latest_val = float(latest["value"])
            desc_data["actual"] = f"{latest_val:{fmt}}"
            desc_data["actual_date"] = latest["date"]
        except (ValueError, KeyError):
            desc_data["actual"] = latest.get("value", "-")

        if previous:
            try:
                prev_val = float(previous["value"])
                desc_data["last"] = f"{prev_val:{fmt}}"
            except (ValueError, KeyError):
                desc_data["last"] = previous.get("value", "-")
        else:
            desc_data["last"] = "-"

        desc_data["expected"] = "-"
        desc_data["label"] = series_info["label"]
        event["description"] = json.dumps(desc_data)

    return events


def _fetch_observations(series_id: str, api_key: str) -> list[dict]:
    """Fetch the 2 most recent observations for a FRED series."""
    if series_id in _obs_cache:
        return _obs_cache[series_id]

    try:
        resp = requests.get(
            _FRED_OBS_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 2,
            },
            timeout=10,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        # Filter out observations with "." as value (FRED placeholder for missing)
        obs = [o for o in obs if o.get("value", ".") != "."]
        _obs_cache[series_id] = obs
        return obs
    except Exception as exc:
        _logger.debug("FRED observations fetch failed for %s: %s", series_id, exc)
        _obs_cache[series_id] = []
        return []
