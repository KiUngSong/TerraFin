"""Background jobs for TerraFin server.

Each module exposes a single coroutine ``run() -> None`` that runs for the
lifetime of the server process. Server lifespan wraps each in
``asyncio.create_task`` and cancels them on shutdown.

Contract:
- ``run()`` is an infinite loop.
- Transient errors are caught with ``except Exception`` (never ``BaseException``),
  logged, and the loop retries after a backoff.
- ``asyncio.CancelledError`` is never caught — it propagates naturally so
  ``asyncio.gather(*tasks, return_exceptions=True)`` on shutdown completes cleanly.
- Blocking I/O uses ``asyncio.get_running_loop().run_in_executor(None, fn)``.

External packages can register jobs via the ``terrafin.jobs`` entry point group
or by calling ``register_job()`` before the server starts.
"""

import importlib.metadata
import logging
from collections.abc import Callable, Coroutine
from typing import Any


_log = logging.getLogger(__name__)

_registry: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = []


def register_job(name: str, coro_fn: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Register a background job coroutine function."""
    _registry.append((name, coro_fn))


def get_registered_jobs() -> list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]]:
    """Return all registered jobs as (name, coro_fn) pairs."""
    return list(_registry)


def load_entry_point_jobs() -> None:
    """Discover and register jobs from installed packages' ``terrafin.jobs`` entry points."""
    for ep in importlib.metadata.entry_points(group="terrafin.jobs"):
        try:
            coro_fn = ep.load()
            register_job(ep.name, coro_fn)
            _log.info("jobs: loaded '%s' from %s", ep.name, ep.value)
        except Exception:
            _log.exception("jobs: failed to load entry point '%s'", ep.name)
