"""Unified interface server for chart and dashboard."""

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


_log = logging.getLogger(__name__)


if __package__ in (None, ""):
    # When launched as `python server.py` from this directory, local package names
    # can shadow stdlib modules (e.g. `calendar`). Prefer project src root imports.
    current_dir = Path(__file__).resolve().parent
    src_root = current_dir.parent.parent
    cleaned_path = []
    for entry in sys.path:
        try:
            resolved = Path(entry or ".").resolve()
        except OSError:
            cleaned_path.append(entry)
            continue
        if resolved == current_dir:
            continue
        cleaned_path.append(entry)
    if str(src_root) not in cleaned_path:
        cleaned_path.insert(0, str(src_root))
    sys.path[:] = cleaned_path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from TerraFin.data import get_data_factory
from TerraFin.data.cache.registry import get_cache_manager
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.env import load_entrypoint_dotenv
from TerraFin.interface.agent.data_routes import create_agent_data_router
from TerraFin.interface.signals.heartbeat import registration_heartbeat
from TerraFin.interface.signals.http_provider import get_alert_provider_from_env
from TerraFin.interface.signals.routes import create_alerting_router
from TerraFin.interface.calendar.routes import create_calendar_router
from TerraFin.interface.calendar.state import reset_calendar_state
from TerraFin.interface.chart.formatters import format_dataframe
from TerraFin.interface.chart.routes import CHART_PATH, create_chart_router
from TerraFin.interface.chart.state import reset_chart_state
from TerraFin.interface.config import RuntimeConfigError, load_runtime_config
from TerraFin.interface.dashboard.data_routes import create_dashboard_data_router
from TerraFin.interface.dashboard.routes import DASHBOARD_PATH, create_dashboard_router
from TerraFin.interface.errors import AppRuntimeError, build_error_response
from TerraFin.interface.frontend_assets import FrontendBuildError, validate_frontend_build
from TerraFin.interface.market_insights.data_routes import create_market_insights_data_router
from TerraFin.interface.market_insights.routes import create_market_insights_router
from TerraFin.interface.stock.data_routes import create_stock_data_router
from TerraFin.interface.stock.routes import create_stock_router
from TerraFin.interface.ticker_search import create_ticker_search_router
from TerraFin.interface.watchlist.routes import create_watchlist_router
from TerraFin.interface.watchlist_service import get_watchlist_service


ROOT_DIR = Path(__file__).parent
BUILD_DIR = ROOT_DIR / "frontend" / "build"
PID_FILE = ROOT_DIR / ".interface_server.pid"
SERVER_LOG_FILE = ROOT_DIR / "interface_server.log"


def _service_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("TerraFin")
    except PackageNotFoundError:
        return "unknown"


def get_runtime_config():
    return load_runtime_config()


def _maybe_start_alert_scanner() -> "asyncio.Task | None":
    """Start background alert scanner if TERRAFIN_ALERT_CHANNEL is set to a non-stdout channel."""
    channel_type = os.environ.get("TERRAFIN_ALERT_CHANNEL", "stdout")
    if channel_type in ("stdout", ""):
        return None
    interval = int(os.environ.get("TERRAFIN_ALERT_INTERVAL", "300"))
    group = os.environ.get("TERRAFIN_ALERT_GROUP") or None
    _log.info("Alert scanner enabled (channel=%s, interval=%ds, group=%s)", channel_type, interval, group or "all")
    return asyncio.create_task(_alert_scanner_loop(interval, group))


def _start_weekly_report() -> "asyncio.Task | None":
    """Always run the weekly report scheduler — generation is universal,
    Telegram dispatch is optional. Disable with TERRAFIN_WEEKLY_REPORT_ENABLED=0."""
    if os.environ.get("TERRAFIN_WEEKLY_REPORT_ENABLED", "1") in ("0", "false", "False"):
        return None
    _log.info("Weekly report scheduler enabled (Fri 16:30 ET)")
    return asyncio.create_task(_weekly_report_loop())


async def _weekly_report_loop() -> None:
    """Generate on startup if no recent report; then on every Friday 16:30 ET."""
    from zoneinfo import ZoneInfo
    tz_name = os.environ.get("TERRAFIN_CACHE_TIMEZONE", "America/New_York")
    tz = ZoneInfo(tz_name)
    loop = asyncio.get_running_loop()

    # Onboarding: ensure a report exists for the latest Friday on startup so
    # the dashboard always has something to show, even before the next tick.
    try:
        await loop.run_in_executor(None, _ensure_recent_report)
    except Exception:
        _log.exception("Initial weekly report generation failed")

    while True:
        now = datetime.now(tz)
        days_ahead = (4 - now.weekday()) % 7
        target = now.replace(hour=16, minute=30, second=0, microsecond=0)
        if days_ahead == 0 and now >= target:
            days_ahead = 7
        target = target + timedelta(days=days_ahead)
        sleep_seconds = (target - now).total_seconds()
        _log.info("Weekly report: next run at %s (%.0fs)", target.isoformat(), sleep_seconds)
        try:
            await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            return
        try:
            from TerraFin.signals.reports.weekly import build_weekly_report
            md = await loop.run_in_executor(None, build_weekly_report)
            _log.info("Weekly report generated")
            # Optional push to channel if configured
            channel_type = os.environ.get("TERRAFIN_ALERT_CHANNEL", "stdout")
            if channel_type not in ("stdout", ""):
                try:
                    from TerraFin.signals.alerting.notify import get_channel_from_env
                    channel = get_channel_from_env()
                    title = f"TerraFin Weekly — {datetime.now(tz).date().isoformat()}"
                    await loop.run_in_executor(None, channel.send, title, md, {"markdown": md})
                    _log.info("Weekly report pushed to channel %s", channel_type)
                except Exception:
                    _log.exception("Weekly report channel push failed")
        except Exception:
            _log.exception("Weekly report generation failed")


def _ensure_recent_report() -> None:
    """Generate a report for the most recently completed Friday close.

    Skips if a report already exists for that exact anchor date — avoids
    re-running the (sometimes slow) enrichment path on every restart.
    Mid-week startups do not produce a stale report dated today.
    """
    from TerraFin.signals.reports import list_reports
    from TerraFin.signals.reports.weekly import _last_completed_friday, build_weekly_report

    target = _last_completed_friday()
    existing = list_reports(limit=8)
    if any(r.as_of == target.isoformat() for r in existing):
        return
    build_weekly_report(as_of=target)


async def _alert_scanner_loop(interval: int, group: str | None) -> None:
    loop = asyncio.get_running_loop()
    while True:
        try:
            from TerraFin.signals.alerting.dedup import deduplicate
            from TerraFin.signals.alerting.notify import get_channel_from_env
            from TerraFin.signals.alerting.scanner import scan

            signals = await loop.run_in_executor(None, scan, group)
            fired = deduplicate(signals)
            if fired:
                channel = get_channel_from_env()
                payload = {
                    "signals": [
                        {
                            "name": s.name,
                            "ticker": s.ticker,
                            "severity": s.severity,
                            "message": s.message,
                            "snapshot": s.snapshot,
                        }
                        for s in fired
                    ],
                    "total": len(fired),
                }
                title = f"TerraFin Alerts — {len(fired)} signal(s)"
                body = "\n".join(f"[{s.severity.upper()}] {s.ticker} {s.name}: {s.message}" for s in fired)
                await loop.run_in_executor(None, channel.send, title, body, payload)
                _log.info("Alert: sent %d signal(s)", len(fired))
            else:
                _log.debug("Alert scan complete — no new signals")
        except asyncio.CancelledError:
            return
        except Exception:
            _log.exception("Alert scanner error (will retry in %ds)", interval)
        await asyncio.sleep(interval)


def create_app(initial_data: TimeSeriesDataFrame | None = None, base_path: str = "") -> FastAPI:
    reset_chart_state(initial_data, format_dataframe)
    reset_calendar_state()

    prefix = base_path.rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = f"/{prefix}"

    try:
        frontend_build = validate_frontend_build(BUILD_DIR)
    except FrontendBuildError as exc:
        raise AppRuntimeError(
            "Frontend build assets are missing or incomplete. Rebuild the frontend before running TerraFin.",
            code="frontend_assets_missing",
            status_code=500,
            details={"buildDir": str(BUILD_DIR), "reason": str(exc)},
        ) from exc

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        _ = app
        _ = get_watchlist_service()
        cache_manager = get_cache_manager()
        cache_manager.start()
        background_tasks: list[asyncio.Task] = []
        if t := _maybe_start_alert_scanner():
            background_tasks.append(t)
        if t := _start_weekly_report():
            background_tasks.append(t)
        alert_provider = get_alert_provider_from_env()
        if alert_provider is not None:
            background_tasks.append(asyncio.create_task(registration_heartbeat(alert_provider)))
            _log.info("Alert provider configured — heartbeat started")
        try:
            yield
        finally:
            for t in background_tasks:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            cache_manager.stop()

    app = FastAPI(lifespan=_lifespan)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        return build_error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=exc.errors(),
        )

    @app.exception_handler(RuntimeError)
    async def _handle_runtime_error(request: Request, exc: RuntimeError):
        if isinstance(exc, AppRuntimeError):
            return build_error_response(
                request,
                status_code=exc.status_code,
                code=exc.code,
                message=str(exc),
                details=exc.details,
            )
        return build_error_response(
            request,
            status_code=500,
            code="runtime_error",
            message=str(exc) or "Runtime error.",
        )

    @app.exception_handler(ValueError)
    async def _handle_value_error(request: Request, exc: ValueError):
        return build_error_response(
            request,
            status_code=500,
            code="value_error",
            message=str(exc) or "Value error.",
        )

    @app.exception_handler(Exception)
    async def _handle_uncaught_error(request: Request, exc: Exception):
        _ = exc
        return build_error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Internal server error.",
        )

    app.include_router(create_chart_router(frontend_build.build_dir), prefix=prefix)
    app.include_router(create_dashboard_router(frontend_build.build_dir), prefix=prefix)
    app.include_router(create_dashboard_data_router(), prefix=prefix)
    app.include_router(create_calendar_router(frontend_build.build_dir), prefix=prefix)
    app.include_router(create_market_insights_router(frontend_build.build_dir), prefix=prefix)
    app.include_router(create_market_insights_data_router(), prefix=prefix)
    app.include_router(create_watchlist_router(frontend_build.build_dir), prefix=prefix)
    app.include_router(create_agent_data_router(), prefix=prefix)
    app.include_router(create_stock_data_router(), prefix=prefix)
    app.include_router(create_stock_router(frontend_build.build_dir), prefix=prefix)
    app.include_router(create_alerting_router(), prefix=prefix)
    app.include_router(create_ticker_search_router(), prefix=prefix)

    @app.get("/")
    def index():
        return RedirectResponse(url=f"{prefix}{DASHBOARD_PATH}")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "alive": True,
            "service": "terrafin-interface",
            "version": _service_version(),
        }

    @app.get("/ready")
    def ready():
        checks: dict[str, Any] = {}
        is_ready = True

        try:
            sources = get_cache_manager().get_status()
            checks["cache_manager"] = {"ok": True, "sources_count": len(sources)}
        except Exception as exc:  # pragma: no cover - defensive readiness guard
            is_ready = False
            checks["cache_manager"] = {"ok": False, "message": str(exc)}

        try:
            _ = get_data_factory()
            checks["data_factory"] = {"ok": True}
        except Exception as exc:  # pragma: no cover - defensive readiness guard
            is_ready = False
            checks["data_factory"] = {"ok": False, "message": str(exc)}

        if not is_ready:
            raise AppRuntimeError(
                "Service is not ready.",
                code="service_not_ready",
                status_code=503,
                details={"checks": checks},
            )

        return {"status": "ready", "ready": True, "checks": checks}

    static_path = f"{prefix}/static" if prefix else "/static"
    app.mount(static_path, StaticFiles(directory=frontend_build.static_dir), name="static")
    return app


def run_server(initial_data: TimeSeriesDataFrame | None = None) -> None:
    runtime_config = get_runtime_config()
    app = create_app(initial_data=initial_data, base_path=runtime_config.base_path)
    uvicorn.run(app, host=runtime_config.host, port=runtime_config.port)


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        raw = PID_FILE.read_text().strip()
        return int(raw) if raw else None
    except (ValueError, OSError):
        return None


def _write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid))


def _remove_pid_file() -> None:
    if PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)


def _port_probe_host(host: str) -> str:
    if host in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return host


def _port_has_listener(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.3)
        return sock.connect_ex((_port_probe_host(host), port)) == 0
    finally:
        sock.close()


def _find_listener_pid(port: int) -> int | None:
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    if result.returncode not in (0, 1):
        return None
    for line in result.stdout.splitlines():
        if not line.startswith("p"):
            continue
        try:
            return int(line[1:])
        except ValueError:
            continue
    return None


def _wait_for_process_exit(pid: int, timeout_s: float = 5.0, poll_interval_s: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            return True
        time.sleep(poll_interval_s)
    return not _is_process_alive(pid)


def _wait_for_port_release(host: str, port: int, timeout_s: float = 5.0, poll_interval_s: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _port_has_listener(host, port):
            return True
        time.sleep(poll_interval_s)
    return not _port_has_listener(host, port)


def _wait_for_server_startup(
    proc: subprocess.Popen,
    host: str,
    port: int,
    timeout_s: float = 5.0,
    poll_interval_s: float = 0.1,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        listener_pid = _find_listener_pid(port)
        if listener_pid == proc.pid:
            return True
        if listener_pid is None and _port_has_listener(host, port):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(poll_interval_s)
    listener_pid = _find_listener_pid(port)
    if listener_pid == proc.pid:
        return True
    if listener_pid is None and _port_has_listener(host, port):
        return True
    return False


def _resolve_server_pid(runtime_config: Any | None = None) -> int | None:
    if runtime_config is None:
        try:
            runtime_config = get_runtime_config()
        except RuntimeConfigError:
            runtime_config = None
    listener_pid = _find_listener_pid(runtime_config.port) if runtime_config is not None else None
    pid = _read_pid()
    if pid is not None:
        if not _is_process_alive(pid):
            _remove_pid_file()
            pid = None
        elif listener_pid is None or listener_pid == pid:
            return pid
        else:
            _remove_pid_file()
    return listener_pid


def start_server() -> int:
    runtime_config = get_runtime_config()
    existing_pid = _resolve_server_pid(runtime_config)
    if existing_pid is not None:
        raise RuntimeError(
            f"Cannot start server: {runtime_config.host}:{runtime_config.port} is already in use (PID={existing_pid})."
        )
    if _port_has_listener(runtime_config.host, runtime_config.port):
        raise RuntimeError(f"Cannot start server: {runtime_config.host}:{runtime_config.port} is already in use.")

    log_handle = open(SERVER_LOG_FILE, "a")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "run"],
            cwd=ROOT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _write_pid(proc.pid)
        if not _wait_for_server_startup(proc, runtime_config.host, runtime_config.port):
            _remove_pid_file()
            raise RuntimeError("Server process failed during startup. Check interface_server.log for details.")
        return proc.pid
    finally:
        log_handle.close()


def stop_server() -> bool:
    runtime_config = None
    try:
        runtime_config = get_runtime_config()
    except RuntimeConfigError:
        runtime_config = None
    pid = _resolve_server_pid(runtime_config)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    if not _wait_for_process_exit(pid, timeout_s=5.0, poll_interval_s=0.1):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        _wait_for_process_exit(pid, timeout_s=2.0, poll_interval_s=0.1)
    if runtime_config is not None:
        _wait_for_port_release(runtime_config.host, runtime_config.port, timeout_s=5.0, poll_interval_s=0.1)
    _remove_pid_file()
    return True


def server_status() -> tuple[bool, int | None]:
    pid = _resolve_server_pid()
    return (pid is not None), pid


def restart_server() -> int:
    stop_server()
    return start_server()


def main(argv: list[str] | None = None) -> int:
    load_entrypoint_dotenv()
    args = argv if argv is not None else sys.argv[1:]
    cmd = (args[0] if args else "start").lower()
    if cmd == "run":
        try:
            runtime_config = get_runtime_config()
            print(f"Interface server running at {runtime_config.base_url}. Press Ctrl+C to stop.")
            run_server()
        except RuntimeConfigError as e:
            print(str(e))
            return 1
        return 0
    if cmd == "start":
        running, pid = server_status()
        if running:
            print(f"Server already running (PID={pid}).")
            return 0
        try:
            runtime_config = get_runtime_config()
            child_pid = start_server()
        except (RuntimeError, RuntimeConfigError) as e:
            print(str(e))
            return 1
        print(f"Server started at {runtime_config.base_url} (PID={child_pid}).")
        return 0
    if cmd == "stop":
        print("Server stopped." if stop_server() else "Server was not running.")
        return 0
    if cmd == "status":
        running, pid = server_status()
        print(f"Server running (PID={pid})." if running else "Server not running.")
        return 0
    if cmd == "restart":
        try:
            runtime_config = get_runtime_config()
            child_pid = restart_server()
        except (RuntimeError, RuntimeConfigError) as e:
            print(str(e))
            return 1
        print(f"Server restarted at {runtime_config.base_url} (PID={child_pid}).")
        return 0
    print(f"Unknown command: {cmd}. Use start, stop, status, restart, or run.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
