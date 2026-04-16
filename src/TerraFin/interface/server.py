"""Unified interface server for chart and dashboard."""

import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any


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

from TerraFin.data.cache.registry import get_cache_manager
from TerraFin.data.contracts.dataframes import TimeSeriesDataFrame
from TerraFin.env import load_entrypoint_dotenv
from TerraFin.interface.agent.data_routes import create_agent_data_router
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
from TerraFin.interface.private_data_service import get_private_data_service
from TerraFin.interface.stock.data_routes import create_stock_data_router
from TerraFin.interface.stock.routes import create_stock_router
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
        _ = get_private_data_service()
        _ = get_watchlist_service()
        cache_manager = get_cache_manager()
        cache_manager.start()
        try:
            yield
        finally:
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
            _ = get_private_data_service()
            checks["private_data_service"] = {"ok": True}
        except Exception as exc:  # pragma: no cover - defensive readiness guard
            is_ready = False
            checks["private_data_service"] = {"ok": False, "message": str(exc)}

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
