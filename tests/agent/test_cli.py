import json

import TerraFin.agent.cli as agent_cli


class _FakeClient:
    def __init__(self, *, transport: str = "auto", base_url: str | None = None, timeout: float = 10.0) -> None:
        self.transport = transport
        self.base_url = base_url
        self.timeout = timeout

    def resolve(self, query: str):
        return {"query": query, "transport": self.transport}

    def market_snapshot(self, name: str, *, depth: str = "auto", view: str = "daily"):
        raise RuntimeError(f"boom:{name}:{depth}:{view}")


def test_cli_emits_json_for_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(agent_cli, "TerraFinAgentClient", _FakeClient)

    exit_code = agent_cli.main(["--json", "--transport", "python", "resolve", "AAPL"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"query": "AAPL", "transport": "python"}


def test_cli_returns_nonzero_for_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(agent_cli, "TerraFinAgentClient", _FakeClient)

    exit_code = agent_cli.main(["--json", "snapshot", "AAPL", "--depth", "full", "--view", "weekly"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert json.loads(captured.err) == {"error": "boom:AAPL:full:weekly"}
