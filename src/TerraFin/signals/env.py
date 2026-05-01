"""Env-var lookup with backward compatibility for legacy ``TERRAFIN_ALERT_*``.

The signals module renamed `alerting/` → `signals/` umbrella; matching env
vars now use the ``TERRAFIN_SIGNALS_*`` prefix. Keep reading the legacy
``TERRAFIN_ALERT_*`` names so existing `.env` files don't break, but log a
one-time deprecation warning per variable so operators can migrate.
"""

import logging
import os

log = logging.getLogger(__name__)

_warned: set[str] = set()


def signals_env(new_name: str, old_name: str, default: str = "") -> str:
    """Return env value preferring ``new_name``; fall back to ``old_name``.

    Empty string from the new name does NOT mask a populated old name —
    we treat empty as unset. Logs at most one deprecation warning per
    legacy name encountered.
    """
    new_val = os.environ.get(new_name, "")
    if new_val:
        return new_val
    old_val = os.environ.get(old_name, "")
    if old_val:
        if old_name not in _warned:
            log.warning(
                "Env var %s is deprecated; rename to %s", old_name, new_name
            )
            _warned.add(old_name)
        return old_val
    return default
