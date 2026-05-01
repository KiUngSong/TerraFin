"""Signal deduplication — fires each (ticker, signal_name) at most once per calendar day.

State file: ~/.terrafin/alert_state.json
Format: {"AAPL:RSI_OVERBOUGHT": "2026-04-30", ...}
"""
import json
import logging
from datetime import date
from pathlib import Path

from TerraFin.signals.alerting.conditions import Signal

log = logging.getLogger(__name__)

_STATE_PATH = Path.home() / ".terrafin" / "alert_state.json"


def deduplicate(signals: list[Signal], state_path: Path = _STATE_PATH) -> list[Signal]:
    """Return only signals not already fired today; persist updated state."""
    state: dict[str, str] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            log.warning("Could not read alert state from %s; starting fresh", state_path)

    today = date.today().isoformat()
    fired: list[Signal] = []
    for s in signals:
        key = f"{s.ticker}:{s.name}"
        if state.get(key) != today:
            fired.append(s)
            state[key] = today

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))
    except Exception:
        log.warning("Could not persist alert state to %s", state_path)

    return fired
