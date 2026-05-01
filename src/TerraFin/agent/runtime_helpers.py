from dataclasses import dataclass, field
from html import escape
from typing import Any

from .client import TerraFinAgentClient


def _client(client: TerraFinAgentClient | None, **client_kwargs: Any) -> TerraFinAgentClient:
    return client if client is not None else TerraFinAgentClient(**client_kwargs)


@dataclass
class TerraFinRuntimeSessionClient:
    client: TerraFinAgentClient
    session_id: str
    agent_name: str
    session: dict[str, Any]
    last_run: dict[str, Any] | None = None

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.session.get("metadata", {}))

    @property
    def tools(self) -> tuple[dict[str, Any], ...]:
        tools = self.session.get("tools", [])
        return tuple(tool for tool in tools if isinstance(tool, dict))

    @property
    def messages(self) -> tuple[dict[str, Any], ...]:
        messages = self.session.get("messages", [])
        return tuple(message for message in messages if isinstance(message, dict))

    @property
    def tasks(self) -> tuple[dict[str, Any], ...]:
        tasks = self.session.get("tasks", [])
        return tuple(task for task in tasks if isinstance(task, dict))

    @property
    def approvals(self) -> tuple[dict[str, Any], ...]:
        approvals = self.session.get("approvals", [])
        return tuple(approval for approval in approvals if isinstance(approval, dict))

    def refresh(self) -> dict[str, Any]:
        self.session = self.client.runtime_session(self.session_id)
        return self.session

    def send(self, content: str) -> dict[str, Any]:
        result = self.client.runtime_message(self.session_id, content)
        session = result.get("session")
        if isinstance(session, dict):
            self.session = session
        self.last_run = result
        return result

    def task(self, task_id: str) -> dict[str, Any]:
        return self.client.runtime_task(task_id)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        result = self.client.runtime_cancel_task(task_id)
        self.refresh()
        return result

    def approval(self, approval_id: str) -> dict[str, Any]:
        return self.client.runtime_approval(approval_id)

    def approve(self, approval_id: str, *, note: str | None = None) -> dict[str, Any]:
        result = self.client.runtime_approve_approval(approval_id, note=note)
        self.refresh()
        return result

    def deny(self, approval_id: str, *, note: str | None = None) -> dict[str, Any]:
        result = self.client.runtime_deny_approval(approval_id, note=note)
        self.refresh()
        return result

    def transcript_text(self) -> str:
        lines: list[str] = []
        for message in self.messages:
            role = str(message.get("role", "unknown")).upper()
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def notebook_html(self) -> str:
        message_blocks: list[str] = []
        for message in self.messages:
            role = escape(str(message.get("role", "unknown")).upper())
            name = message.get("name")
            title = role if not name else f"{role} · {escape(str(name))}"
            content = escape(str(message.get("content", ""))).replace("\n", "<br/>")
            message_blocks.append(
                f"""
                <div style="border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;background:#fff;">
                  <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;margin-bottom:8px;">{title}</div>
                  <div style="font-size:14px;line-height:1.55;color:#0f172a;white-space:normal;">{content or '&mdash;'}</div>
                </div>
                """
            )
        tools = "".join(
            f'<span style="display:inline-flex;padding:4px 8px;border-radius:999px;background:#eff6ff;color:#1d4ed8;font-size:11px;font-weight:700;border:1px solid #bfdbfe;">{escape(str(tool.get("name", "")))}</span>'
            for tool in self.tools
        )
        return f"""
        <div style="font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;border:1px solid #e2e8f0;border-radius:18px;padding:18px;display:grid;gap:16px;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;">
            <div>
              <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;">TerraFin Agent Session</div>
              <div style="font-size:22px;font-weight:800;color:#0f172a;margin-top:4px;">{escape(self.agent_name)}</div>
              <div style="font-size:12px;color:#64748b;margin-top:6px;">Session ID: {escape(self.session_id)}</div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">{tools}</div>
          </div>
          <div style="display:grid;gap:10px;">
            {''.join(message_blocks) or '<div style="font-size:13px;color:#64748b;">No messages yet.</div>'}
          </div>
        </div>
        """

    def display_notebook(self):
        try:
            from IPython.display import HTML, display
        except ImportError as exc:  # pragma: no cover - optional notebook dependency
            raise RuntimeError("IPython is required to display TerraFin agent sessions in a notebook.") from exc
        html = HTML(self.notebook_html())
        display(html)
        return html


def create_runtime_session(
    agent_name: str,
    *,
    client: TerraFinAgentClient | None = None,
    session_id: str | None = None,
    system_prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
    **client_kwargs: Any,
) -> TerraFinRuntimeSessionClient:
    agent_client = _client(client, **client_kwargs)
    session = agent_client.runtime_create_session(
        agent_name,
        session_id=session_id,
        system_prompt=system_prompt,
        metadata=metadata,
    )
    return TerraFinRuntimeSessionClient(
        client=agent_client,
        session_id=str(session["sessionId"]),
        agent_name=str(session["agentName"]),
        session=session,
    )


def ask_agent(
    agent_name: str,
    content: str,
    *,
    client: TerraFinAgentClient | None = None,
    session_id: str | None = None,
    system_prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
    **client_kwargs: Any,
) -> dict[str, Any]:
    session = create_runtime_session(
        agent_name,
        client=client,
        session_id=session_id,
        system_prompt=system_prompt,
        metadata=metadata,
        **client_kwargs,
    )
    return session.send(content)
