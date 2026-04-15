import os
import subprocess
import sys
from pathlib import Path

import TerraFin.agent.cli as cli_module
import TerraFin.interface.server as server_module


def _run_repo_python(tmp_path, code: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    repo_src = Path(__file__).resolve().parents[1] / "src"
    command = [
        sys.executable,
        "-c",
        (
            "import sys; "
            f"sys.path.insert(0, {str(repo_src).__repr__()}); "
            f"{code}"
        ),
    ]
    return subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


def test_importing_terrafin_does_not_load_dotenv(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TERRAFIN_TEST_AUTOLOAD=loaded\n", encoding="utf-8")
    result = _run_repo_python(
        tmp_path,
        "import os; import TerraFin; print(os.getenv('TERRAFIN_TEST_AUTOLOAD', ''))",
    )
    assert result.stdout.strip() == ""


def test_agent_cli_main_loads_dotenv_from_explicit_entrypoint(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("TERRAFIN_TEST_AGENT_DOTENV=cli-loaded\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERRAFIN_TEST_AGENT_DOTENV", raising=False)

    class _FakeClient:
        def resolve(self, query: str) -> dict:
            return {"query": query}

    monkeypatch.setattr(cli_module, "_make_client", lambda args: _FakeClient())

    assert cli_module.main(["resolve", "AAPL"]) == 0
    assert os.getenv("TERRAFIN_TEST_AGENT_DOTENV") == "cli-loaded"


def test_server_main_loads_dotenv_from_explicit_entrypoint(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("TERRAFIN_TEST_SERVER_DOTENV=server-loaded\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERRAFIN_TEST_SERVER_DOTENV", raising=False)
    monkeypatch.setattr(server_module, "server_status", lambda: (False, None))

    assert server_module.main(["status"]) == 0
    assert os.getenv("TERRAFIN_TEST_SERVER_DOTENV") == "server-loaded"


def test_env_backed_feature_lazy_loads_dotenv(tmp_path) -> None:
    (tmp_path / ".env").write_text("TERRAFIN_TEST_LAZY=lazy-loaded\n", encoding="utf-8")

    result = _run_repo_python(
        tmp_path,
        (
            "import json, os; "
            "import TerraFin; "
            "from TerraFin.data.utils.api_check import check_api_key; "
            "print(json.dumps({"
            "'before': os.getenv('TERRAFIN_TEST_LAZY', ''), "
            "'after': check_api_key('TERRAFIN_TEST_LAZY')"
            "}))"
        ),
    )

    assert result.stdout.strip() == '{"before": "", "after": "lazy-loaded"}'


def test_configure_loads_explicit_dotenv_path_even_when_lazy_autoload_is_disabled(tmp_path) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text("TERRAFIN_TEST_CONFIGURE=configured\n", encoding="utf-8")
    env = os.environ.copy()
    env["TERRAFIN_DISABLE_DOTENV"] = "1"

    result = _run_repo_python(
        tmp_path,
        (
            "import os; "
            "from TerraFin import configure; "
            f"configure(dotenv_path={str(env_file).__repr__()}); "
            "print(os.getenv('TERRAFIN_TEST_CONFIGURE', ''))"
        ),
        env=env,
    )

    assert result.stdout.strip() == "configured"


def test_disable_dotenv_prevents_lazy_autoload(tmp_path) -> None:
    (tmp_path / ".env").write_text("TERRAFIN_TEST_DISABLED=should-not-load\n", encoding="utf-8")
    env = os.environ.copy()
    env["TERRAFIN_DISABLE_DOTENV"] = "1"

    result = _run_repo_python(
        tmp_path,
        (
            "from TerraFin.data.utils.api_check import check_api_key\n"
            "try:\n"
            "    check_api_key('TERRAFIN_TEST_DISABLED')\n"
            "except Exception as exc:\n"
            "    print(type(exc).__name__)\n"
            "    print(str(exc))\n"
        ),
        env=env,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "ValueError"
    assert "TERRAFIN_TEST_DISABLED" in lines[1]
