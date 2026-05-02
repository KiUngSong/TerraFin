"""Env-var lookup for the signals subsystem.

All env vars use the ``TERRAFIN_SIGNALS_*`` prefix.
"""

import os


def signals_env(name: str, default: str = "") -> str:
    """Return env value, treating empty string as unset."""
    val = os.environ.get(name, "")
    return val if val else default
