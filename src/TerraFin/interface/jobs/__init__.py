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
"""
