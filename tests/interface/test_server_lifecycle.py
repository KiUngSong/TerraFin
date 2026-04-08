import signal
from types import SimpleNamespace

import pytest

import TerraFin.interface.server as server_module


def test_stop_server_waits_for_process_exit_and_port_release(monkeypatch) -> None:
    kill_calls: list[tuple[int, int]] = []
    wait_process_calls: list[tuple[int, float, float]] = []
    wait_port_calls: list[tuple[str, int, float, float]] = []
    removed: list[str] = []

    monkeypatch.setattr(server_module, "_read_pid", lambda: 1234)
    monkeypatch.setattr(server_module, "_is_process_alive", lambda pid: pid == 1234)
    monkeypatch.setattr(
        server_module,
        "get_runtime_config",
        lambda: SimpleNamespace(host="127.0.0.1", port=8001),
    )
    monkeypatch.setattr(server_module, "_find_listener_pid", lambda port: 1234)
    monkeypatch.setattr(server_module.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr(
        server_module,
        "_wait_for_process_exit",
        lambda pid, timeout_s=5.0, poll_interval_s=0.1: (
            wait_process_calls.append((pid, timeout_s, poll_interval_s)) or True
        ),
    )
    monkeypatch.setattr(
        server_module,
        "_wait_for_port_release",
        lambda host, port, timeout_s=5.0, poll_interval_s=0.1: (
            wait_port_calls.append((host, port, timeout_s, poll_interval_s)) or True
        ),
    )
    monkeypatch.setattr(server_module, "_remove_pid_file", lambda: removed.append("removed"))

    assert server_module.stop_server() is True
    assert kill_calls == [(1234, signal.SIGTERM)]
    assert wait_process_calls == [(1234, 5.0, 0.1)]
    assert wait_port_calls == [("127.0.0.1", 8001, 5.0, 0.1)]
    assert removed == ["removed"]


def test_stop_server_escalates_to_sigkill_when_process_does_not_exit(monkeypatch) -> None:
    kill_calls: list[tuple[int, int]] = []
    wait_process_calls: list[tuple[int, float, float]] = []

    wait_results = iter([False, True])

    monkeypatch.setattr(server_module, "_read_pid", lambda: 5678)
    monkeypatch.setattr(server_module, "_is_process_alive", lambda pid: pid == 5678)
    monkeypatch.setattr(
        server_module,
        "get_runtime_config",
        lambda: SimpleNamespace(host="127.0.0.1", port=8001),
    )
    monkeypatch.setattr(server_module, "_find_listener_pid", lambda port: 5678)
    monkeypatch.setattr(server_module.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr(
        server_module,
        "_wait_for_process_exit",
        lambda pid, timeout_s=5.0, poll_interval_s=0.1: (
            wait_process_calls.append((pid, timeout_s, poll_interval_s)) or next(wait_results)
        ),
    )
    monkeypatch.setattr(
        server_module, "_wait_for_port_release", lambda host, port, timeout_s=5.0, poll_interval_s=0.1: True
    )
    monkeypatch.setattr(server_module, "_remove_pid_file", lambda: None)

    assert server_module.stop_server() is True
    assert kill_calls == [(5678, signal.SIGTERM), (5678, signal.SIGKILL)]
    assert wait_process_calls == [(5678, 5.0, 0.1), (5678, 2.0, 0.1)]


def test_server_status_recovers_listener_when_pid_file_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(server_module, "_read_pid", lambda: None)
    monkeypatch.setattr(
        server_module,
        "get_runtime_config",
        lambda: SimpleNamespace(host="127.0.0.1", port=8001),
    )
    monkeypatch.setattr(server_module, "_find_listener_pid", lambda port: 2468)

    assert server_module.server_status() == (True, 2468)


def test_stop_server_uses_listener_pid_when_pid_file_is_missing(monkeypatch) -> None:
    kill_calls: list[tuple[int, int]] = []
    removed: list[str] = []

    monkeypatch.setattr(server_module, "_read_pid", lambda: None)
    monkeypatch.setattr(
        server_module,
        "get_runtime_config",
        lambda: SimpleNamespace(host="127.0.0.1", port=8001),
    )
    monkeypatch.setattr(server_module, "_find_listener_pid", lambda port: 2468)
    monkeypatch.setattr(server_module, "_is_process_alive", lambda pid: pid == 2468)
    monkeypatch.setattr(server_module.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr(
        server_module,
        "_wait_for_process_exit",
        lambda pid, timeout_s=5.0, poll_interval_s=0.1: True,
    )
    monkeypatch.setattr(
        server_module,
        "_wait_for_port_release",
        lambda host, port, timeout_s=5.0, poll_interval_s=0.1: True,
    )
    monkeypatch.setattr(server_module, "_remove_pid_file", lambda: removed.append("removed"))

    assert server_module.stop_server() is True
    assert kill_calls == [(2468, signal.SIGTERM)]
    assert removed == ["removed"]


def test_start_server_raises_when_process_never_binds_port(monkeypatch, tmp_path) -> None:
    class _FakeProc:
        pid = 4321

        @staticmethod
        def poll():
            return None

    writes: list[int] = []
    removed: list[str] = []

    monkeypatch.setattr(
        server_module,
        "get_runtime_config",
        lambda: SimpleNamespace(host="127.0.0.1", port=8001),
    )
    monkeypatch.setattr(server_module, "_resolve_server_pid", lambda runtime_config=None: None)
    monkeypatch.setattr(server_module, "_port_has_listener", lambda host, port: False)
    monkeypatch.setattr(server_module.subprocess, "Popen", lambda *args, **kwargs: _FakeProc())
    monkeypatch.setattr(
        server_module,
        "_wait_for_server_startup",
        lambda proc, host, port, timeout_s=5.0, poll_interval_s=0.1: False,
    )
    monkeypatch.setattr(server_module, "_write_pid", lambda pid: writes.append(pid))
    monkeypatch.setattr(server_module, "_remove_pid_file", lambda: removed.append("removed"))
    monkeypatch.setattr(server_module, "SERVER_LOG_FILE", tmp_path / "interface_server.log")

    with pytest.raises(RuntimeError, match="Check interface_server.log"):
        server_module.start_server()

    assert writes == [4321]
    assert removed == ["removed"]
