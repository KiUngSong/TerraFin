from TerraFin.agent.definitions import DEFAULT_HOSTED_AGENT_NAME
from TerraFin.agent.runtime_helpers import ask_agent, create_runtime_session


class _FakeClient:
    def runtime_create_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        metadata: dict | None = None,
    ):
        return {
            "sessionId": session_id or "runtime:test",
            "agentName": agent_name,
            "metadata": dict(metadata or {}),
            "tools": [{"name": "market_snapshot"}],
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt or "You are a hosted TerraFin agent.",
                    "createdAt": "2026-01-01T00:00:00+00:00",
                    "metadata": {},
                }
            ],
        }

    def runtime_session(self, session_id: str):
        return {
            "sessionId": session_id,
            "agentName": DEFAULT_HOSTED_AGENT_NAME,
            "metadata": {},
            "tools": [{"name": "market_snapshot"}],
            "messages": [
                {
                    "role": "system",
                    "content": "You are a hosted TerraFin agent.",
                    "createdAt": "2026-01-01T00:00:00+00:00",
                    "metadata": {},
                },
                {
                    "role": "assistant",
                    "content": "AAPL looks constructive.",
                    "createdAt": "2026-01-01T00:00:01+00:00",
                    "metadata": {},
                },
            ],
        }

    def runtime_message(self, session_id: str, content: str):
        return {
            "sessionId": session_id,
            "agentName": DEFAULT_HOSTED_AGENT_NAME,
            "steps": 2,
            "finalMessage": {
                "role": "assistant",
                "content": f"Echo: {content}",
                "createdAt": "2026-01-01T00:00:02+00:00",
                "metadata": {},
            },
            "messagesAdded": [
                {
                    "role": "user",
                    "content": content,
                    "createdAt": "2026-01-01T00:00:01+00:00",
                    "metadata": {},
                },
                {
                    "role": "assistant",
                    "content": f"Echo: {content}",
                    "createdAt": "2026-01-01T00:00:02+00:00",
                    "metadata": {},
                },
            ],
            "toolResults": [],
            "session": {
                "sessionId": session_id,
                "agentName": DEFAULT_HOSTED_AGENT_NAME,
                "metadata": {},
                "tools": [{"name": "market_snapshot"}],
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a hosted TerraFin agent.",
                        "createdAt": "2026-01-01T00:00:00+00:00",
                        "metadata": {},
                    },
                    {
                        "role": "user",
                        "content": content,
                        "createdAt": "2026-01-01T00:00:01+00:00",
                        "metadata": {},
                    },
                    {
                        "role": "assistant",
                        "content": f"Echo: {content}",
                        "createdAt": "2026-01-01T00:00:02+00:00",
                        "metadata": {},
                    },
                ],
            },
        }


def test_create_runtime_session_returns_stateful_wrapper() -> None:
    session = create_runtime_session(DEFAULT_HOSTED_AGENT_NAME, client=_FakeClient(), session_id="runtime:helper")

    assert session.session_id == "runtime:helper"
    assert session.agent_name == DEFAULT_HOSTED_AGENT_NAME
    assert session.tools[0]["name"] == "market_snapshot"


def test_runtime_session_wrapper_can_send_and_render_transcript() -> None:
    session = create_runtime_session(DEFAULT_HOSTED_AGENT_NAME, client=_FakeClient(), session_id="runtime:helper")

    result = session.send("Give me AAPL.")

    assert result["finalMessage"]["content"] == "Echo: Give me AAPL."
    assert "USER: Give me AAPL." in session.transcript_text()
    assert "ASSISTANT: Echo: Give me AAPL." in session.transcript_text()
    assert "TerraFin Agent Session" in session.notebook_html()


def test_ask_agent_runs_one_shot_message() -> None:
    result = ask_agent(DEFAULT_HOSTED_AGENT_NAME, "Summarize AAPL.", client=_FakeClient(), session_id="runtime:oneshot")

    assert result["sessionId"] == "runtime:oneshot"
    assert result["finalMessage"]["content"] == "Echo: Summarize AAPL."
