import json
from pathlib import Path


def load_fallback_section(section: str) -> dict:
    path = Path(__file__).resolve().parent / "fallbacks.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Fallback file must contain a JSON object.")
    selected = payload.get(section)
    if not isinstance(selected, dict):
        raise ValueError(f"Fallback section '{section}' must be a JSON object.")
    return selected
