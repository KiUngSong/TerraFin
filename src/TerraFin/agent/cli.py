import argparse
import getpass
import json
import sys
from typing import Any

from TerraFin.env import load_entrypoint_dotenv

from .client import TerraFinAgentClient
from .hosted_service import build_hosted_model_provider_registry
from .model_management import (
    build_provider_auth_status,
    get_provider_catalog,
    get_saved_provider_credentials,
    list_provider_catalog,
    resolve_current_model_preference,
    resolve_model_state_path,
    set_saved_default_model_ref,
    set_saved_provider_credentials,
)
from .providers.github_copilot import (
    poll_github_copilot_device_access_token,
    request_github_copilot_device_code,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="terrafin-agent")
    parser.add_argument("--transport", default="auto", choices=["auto", "python", "http"])
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timeout", type=float, default=10.0)

    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("query")

    market_data_parser = subparsers.add_parser("market-data")
    market_data_parser.add_argument("name")
    market_data_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    market_data_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    indicators_parser = subparsers.add_parser("indicators")
    indicators_parser.add_argument("name")
    indicators_parser.add_argument("--indicators", required=True)
    indicators_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    indicators_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("name")
    snapshot_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    snapshot_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    economic_parser = subparsers.add_parser("economic")
    economic_parser.add_argument("--indicators", required=True)

    portfolio_parser = subparsers.add_parser("portfolio")
    portfolio_parser.add_argument("guru")

    company_parser = subparsers.add_parser("company")
    company_parser.add_argument("ticker")

    earnings_parser = subparsers.add_parser("earnings")
    earnings_parser.add_argument("ticker")

    financials_parser = subparsers.add_parser("financials")
    financials_parser.add_argument("ticker")
    financials_parser.add_argument("--statement", default="income", choices=["income", "balance", "cashflow"])
    financials_parser.add_argument("--period", default="annual", choices=["annual", "quarter"])

    macro_parser = subparsers.add_parser("macro-focus")
    macro_parser.add_argument("name")
    macro_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    macro_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    lppl_parser = subparsers.add_parser("lppl")
    lppl_parser.add_argument("name")
    lppl_parser.add_argument("--depth", default="auto", choices=["auto", "recent", "full"])
    lppl_parser.add_argument("--view", default="daily", choices=["daily", "weekly", "monthly", "yearly"])

    calendar_parser = subparsers.add_parser("calendar")
    calendar_parser.add_argument("--year", type=int, required=True)
    calendar_parser.add_argument("--month", type=int, required=True)
    calendar_parser.add_argument("--categories", default=None)
    calendar_parser.add_argument("--limit", type=int, default=None)

    runtime_agents_parser = subparsers.add_parser("runtime-agents")
    _ = runtime_agents_parser

    runtime_create_parser = subparsers.add_parser("runtime-create-session")
    runtime_create_parser.add_argument("agent_name")
    runtime_create_parser.add_argument("--session-id", default=None)
    runtime_create_parser.add_argument("--system-prompt", default=None)

    runtime_session_parser = subparsers.add_parser("runtime-session")
    runtime_session_parser.add_argument("session_id")

    runtime_message_parser = subparsers.add_parser("runtime-message")
    runtime_message_parser.add_argument("session_id")
    runtime_message_parser.add_argument("content")

    runtime_tasks_parser = subparsers.add_parser("runtime-tasks")
    runtime_tasks_parser.add_argument("session_id")

    runtime_approvals_parser = subparsers.add_parser("runtime-approvals")
    runtime_approvals_parser.add_argument("session_id")

    runtime_task_parser = subparsers.add_parser("runtime-task")
    runtime_task_parser.add_argument("task_id")

    runtime_approval_parser = subparsers.add_parser("runtime-approval")
    runtime_approval_parser.add_argument("approval_id")

    runtime_cancel_task_parser = subparsers.add_parser("runtime-cancel-task")
    runtime_cancel_task_parser.add_argument("task_id")

    runtime_approve_approval_parser = subparsers.add_parser("runtime-approve-approval")
    runtime_approve_approval_parser.add_argument("approval_id")
    runtime_approve_approval_parser.add_argument("--note", default=None)

    runtime_deny_approval_parser = subparsers.add_parser("runtime-deny-approval")
    runtime_deny_approval_parser.add_argument("approval_id")
    runtime_deny_approval_parser.add_argument("--note", default=None)

    open_chart_parser = subparsers.add_parser("open-chart")
    open_chart_parser.add_argument("names", nargs="+")
    open_chart_parser.add_argument("--session-id", default=None)

    models_parser = subparsers.add_parser("models")
    models_subparsers = models_parser.add_subparsers(dest="models_command", required=True)

    models_list_parser = models_subparsers.add_parser("list")
    models_list_parser.add_argument("provider", nargs="?", default=None)
    models_list_parser.add_argument("--all", action="store_true", help="Show featured model refs for each provider.")

    models_current_parser = models_subparsers.add_parser("current")
    _ = models_current_parser

    models_use_parser = models_subparsers.add_parser("use")
    models_use_parser.add_argument("model_ref")

    models_auth_parser = models_subparsers.add_parser("auth")
    models_auth_subparsers = models_auth_parser.add_subparsers(dest="models_auth_command", required=True)

    models_auth_status_parser = models_auth_subparsers.add_parser("status")
    models_auth_status_parser.add_argument("--provider", default=None)

    models_auth_login_parser = models_auth_subparsers.add_parser("login")
    models_auth_login_parser.add_argument("--provider", required=True)
    models_auth_login_parser.add_argument(
        "--method",
        default="auto",
        choices=["auto", "token", "device"],
        help="Auth method. GitHub Copilot supports device login; other providers use token/API-key auth.",
    )
    models_auth_login_parser.add_argument("--token", default=None)
    models_auth_login_parser.add_argument("--set-default", action="store_true")
    models_auth_login_parser.add_argument("--model-ref", default=None)
    models_auth_login_parser.add_argument("--yes", action="store_true")

    models_auth_copilot_parser = models_auth_subparsers.add_parser("login-github-copilot")
    models_auth_copilot_parser.add_argument("--token", default=None)
    models_auth_copilot_parser.add_argument("--set-default", action="store_true")
    models_auth_copilot_parser.add_argument("--model-ref", default=None)
    models_auth_copilot_parser.add_argument("--yes", action="store_true")

    return parser


def _make_client(args: argparse.Namespace) -> TerraFinAgentClient:
    return TerraFinAgentClient(
        transport=args.transport,
        base_url=args.base_url,
        timeout=args.timeout,
    )


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def _format_row(row: list[str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    lines = [_format_row(headers)]
    lines.extend(_format_row(row) for row in rows)
    return "\n".join(lines)


def _models_table_rows(payload: dict[str, Any]) -> list[list[str]]:
    current_model_ref = str(payload.get("current", {}).get("modelRef", "") or "").strip()
    rows: list[list[str]] = []
    for provider in payload.get("providers", []):
        auth = provider.get("auth", {})
        auth_label = str(auth.get("source") or "").strip() if auth.get("configured") else "no"
        local_label = _yes_no(auth.get("localConfigured"))
        models = provider.get("models") or [
            {
                "modelRef": provider["defaultModelRef"],
                "isDefault": True,
                "isCurrent": provider["defaultModelRef"] == current_model_ref,
            }
        ]
        for model in models:
            rows.append(
                [
                    str(model.get("modelRef") or ""),
                    auth_label,
                    local_label,
                    _yes_no(model.get("isCurrent")),
                    _yes_no(model.get("isDefault")),
                ]
            )
    return rows


def _format_models_list_output(payload: dict[str, Any]) -> str:
    current = payload.get("current", {})
    current_ref = str(current.get("modelRef") or "").strip()
    current_source = str(current.get("source") or "").strip() or "unknown"
    rows = _models_table_rows(payload)
    table = _render_table(["Model", "Auth", "Local", "Current", "Default"], rows)
    lines = [f"Current: {current_ref} ({current_source})"]
    if table:
        lines.extend(["", table])
    return "\n".join(lines)


def _format_models_current_output(payload: dict[str, Any]) -> str:
    auth = payload.get("auth", {})
    active_auth = str(auth.get("source") or "").strip() if auth.get("configured") else "no"
    lines = [
        f"Current: {payload['modelRef']}",
        f"Provider: {payload['providerLabel']}",
        f"Source: {payload.get('source', 'unknown')}",
        f"Auth: {active_auth}",
        f"Local auth: {_yes_no(auth.get('localConfigured'))}",
    ]
    return "\n".join(lines)


def _format_models_use_output(payload: dict[str, Any]) -> str:
    runtime_model = payload.get("runtimeModel", {})
    return "\n".join(
        [
            f"Saved default model: {runtime_model.get('modelRef', '')}",
            f"Provider: {runtime_model.get('providerLabel', '')}",
        ]
    )


def _format_models_auth_status_output(payload: dict[str, Any]) -> str:
    rows = []
    for provider in payload.get("providers", []):
        active_auth = str(provider.get("source") or "").strip() if provider.get("configured") else "no"
        rows.append(
            [
                str(provider.get("providerId") or ""),
                str(provider.get("authKind") or ""),
                active_auth,
                _yes_no(provider.get("localConfigured")),
                _yes_no(provider.get("configured")),
            ]
        )
    return _render_table(["Provider", "Kind", "Auth", "Local", "Configured"], rows)


def _format_models_auth_login_output(payload: dict[str, Any]) -> str:
    lines = [
        f"Saved {payload.get('providerLabel', payload.get('providerId', 'provider'))} credentials ({payload.get('authMode', 'token')})."
    ]
    default_model = payload.get("defaultModel")
    if isinstance(default_model, dict) and default_model.get("modelRef"):
        lines.append(f"Default model: {default_model['modelRef']}")
    return "\n".join(lines)


def _format_models_output(args: argparse.Namespace, payload: dict[str, Any]) -> str:
    if args.models_command == "list":
        return _format_models_list_output(payload)
    if args.models_command == "current":
        return _format_models_current_output(payload)
    if args.models_command == "use":
        return _format_models_use_output(payload)
    if args.models_command == "auth":
        if args.models_auth_command == "status":
            return _format_models_auth_status_output(payload)
        if args.models_auth_command in {"login", "login-github-copilot"}:
            return _format_models_auth_login_output(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _prompt_secret(label: str) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError(f"{label} requires --token or an interactive TTY.")
    return getpass.getpass(f"{label}: ").strip()


def _confirm_overwrite(provider_label: str) -> None:
    if not sys.stdin.isatty():
        raise RuntimeError(
            f"Saved {provider_label} credentials already exist. Re-run with --yes to overwrite them."
        )
    answer = input(f"Overwrite saved {provider_label} credentials? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise RuntimeError("Cancelled.")


def _require_tty(context: str) -> None:
    if not sys.stdin.isatty():
        raise RuntimeError(f"{context} requires an interactive TTY.")


def _model_payload_from_ref(model_ref: str) -> dict[str, Any]:
    registry = build_hosted_model_provider_registry()
    resolved = registry.resolve_model_ref(model_ref)
    return resolved.to_payload()


def _models_list_payload(*, provider_filter: str | None = None, include_models: bool = False) -> dict[str, Any]:
    current = resolve_current_model_preference()
    current_payload = _model_payload_from_ref(current["modelRef"])
    providers: list[dict[str, Any]] = []
    for catalog in list_provider_catalog():
        if provider_filter and catalog.provider_id != provider_filter:
            continue
        provider_payload: dict[str, Any] = {
            "providerId": catalog.provider_id,
            "providerLabel": catalog.provider_label,
            "description": catalog.description,
            "defaultModelRef": catalog.default_model_ref,
            "supportsCustomModelIds": catalog.supports_custom_model_ids,
            "notes": catalog.notes,
            "auth": build_provider_auth_status(catalog.provider_id),
        }
        if include_models:
            provider_payload["models"] = [
                {
                    "modelRef": model_ref,
                    "modelId": model_ref.split("/", 1)[1],
                    "isDefault": model_ref == catalog.default_model_ref,
                    "isCurrent": model_ref == current_payload["modelRef"],
                }
                for model_ref in catalog.featured_model_refs
            ]
        providers.append(provider_payload)
    return {
        "current": {
            **current_payload,
            "source": current["source"],
        },
        "providers": providers,
        "savedStatePath": str(resolve_model_state_path()),
    }


def _models_current_payload() -> dict[str, Any]:
    current = resolve_current_model_preference()
    payload = _model_payload_from_ref(current["modelRef"])
    payload["source"] = current["source"]
    payload["savedStatePath"] = str(resolve_model_state_path())
    payload["auth"] = build_provider_auth_status(payload["providerId"])
    return payload


def _models_use_payload(model_ref: str) -> dict[str, Any]:
    payload = _model_payload_from_ref(model_ref)
    state_path = set_saved_default_model_ref(payload["modelRef"])
    return {
        "ok": True,
        "runtimeModel": payload,
        "savedStatePath": str(state_path),
        "source": "saved",
    }


def _models_auth_status_payload(provider_id: str | None = None) -> dict[str, Any]:
    providers = [get_provider_catalog(provider_id)] if provider_id else list_provider_catalog()
    return {
        "providers": [build_provider_auth_status(provider.provider_id) for provider in providers],
        "savedStatePath": str(resolve_model_state_path()),
    }


def _models_auth_login_payload(
    *,
    provider_id: str,
    method: str,
    token: str | None,
    set_default: bool,
    model_ref: str | None,
    yes: bool,
) -> dict[str, Any]:
    catalog = get_provider_catalog(provider_id)
    existing = get_saved_provider_credentials(provider_id)
    if existing and not yes:
        _confirm_overwrite(catalog.provider_label)
    normalized_method = str(method or "auto").strip().lower() or "auto"
    if normalized_method not in {"auto", "token", "device"}:
        raise RuntimeError(f"Unknown auth method: {normalized_method}")
    if catalog.provider_id != "github-copilot" and normalized_method == "device":
        raise RuntimeError(f"Provider '{catalog.provider_id}' does not support device login.")
    if normalized_method == "device" and str(token or "").strip():
        raise RuntimeError("--token cannot be combined with --method device.")

    auth_mode = "token"
    if catalog.provider_id == "github-copilot" and normalized_method in {"auto", "device"} and not str(token or "").strip():
        _require_tty("GitHub Copilot device login")
        device = request_github_copilot_device_code()
        print(
            f"Authorize GitHub Copilot by visiting {device.authorization_url} and entering code {device.user_code}.",
            file=sys.stderr,
        )
        print("Waiting for GitHub authorization...", file=sys.stderr)
        secret = poll_github_copilot_device_access_token(
            device_code=device.device_code,
            interval_seconds=device.interval_seconds,
            expires_in_seconds=device.expires_in_seconds,
        )
        auth_mode = "device"
    else:
        secret = str(token or "").strip() or _prompt_secret(catalog.auth_prompt)
    if not secret:
        raise RuntimeError(f"{catalog.auth_prompt} cannot be empty.")
    state_path = set_saved_provider_credentials(
        provider_id,
        {
            catalog.auth_field: secret,
            "updatedAt": "cli",
            "authMode": auth_mode,
        },
    )
    default_payload = None
    if set_default:
        selected_model_ref = str(model_ref or "").strip() or catalog.default_model_ref
        resolved = _model_payload_from_ref(selected_model_ref)
        if resolved["providerId"] != provider_id:
            raise RuntimeError(
                f"Model ref '{selected_model_ref}' does not belong to provider '{provider_id}'."
            )
        set_saved_default_model_ref(resolved["modelRef"])
        default_payload = {
            **resolved,
            "source": "saved",
        }
    return {
        "ok": True,
        "providerId": catalog.provider_id,
        "providerLabel": catalog.provider_label,
        "savedStatePath": str(state_path),
        "auth": build_provider_auth_status(provider_id),
        "defaultModel": default_payload,
        "authMode": auth_mode,
    }


def main(argv: list[str] | None = None) -> int:
    load_entrypoint_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "models":
            if args.models_command == "list":
                provider_filter = None if args.provider is None else get_provider_catalog(args.provider).provider_id
                payload = _models_list_payload(provider_filter=provider_filter, include_models=args.all)
            elif args.models_command == "current":
                payload = _models_current_payload()
            elif args.models_command == "use":
                payload = _models_use_payload(args.model_ref)
            elif args.models_command == "auth":
                if args.models_auth_command == "status":
                    provider_filter = None if args.provider is None else get_provider_catalog(args.provider).provider_id
                    payload = _models_auth_status_payload(provider_filter)
                elif args.models_auth_command == "login":
                    payload = _models_auth_login_payload(
                        provider_id=get_provider_catalog(args.provider).provider_id,
                        method=args.method,
                        token=args.token,
                        set_default=args.set_default,
                        model_ref=args.model_ref,
                        yes=args.yes,
                    )
                elif args.models_auth_command == "login-github-copilot":
                    payload = _models_auth_login_payload(
                        provider_id="github-copilot",
                        method="device" if not str(args.token or "").strip() else "token",
                        token=args.token,
                        set_default=args.set_default,
                        model_ref=args.model_ref,
                        yes=args.yes,
                    )
                else:  # pragma: no cover - argparse keeps this unreachable
                    raise RuntimeError(f"Unknown models auth command: {args.models_auth_command}")
            else:  # pragma: no cover - argparse keeps this unreachable
                raise RuntimeError(f"Unknown models command: {args.models_command}")
        else:
            client = _make_client(args)
            if args.command == "resolve":
                payload = client.resolve(args.query)
            elif args.command == "market-data":
                payload = client.market_data(args.name, depth=args.depth, view=args.view)
            elif args.command == "indicators":
                payload = client.indicators(args.name, args.indicators, depth=args.depth, view=args.view)
            elif args.command == "snapshot":
                payload = client.market_snapshot(args.name, depth=args.depth, view=args.view)
            elif args.command == "economic":
                payload = client.economic(args.indicators)
            elif args.command == "portfolio":
                payload = client.portfolio(args.guru)
            elif args.command == "company":
                payload = client.company_info(args.ticker)
            elif args.command == "earnings":
                payload = client.earnings(args.ticker)
            elif args.command == "financials":
                payload = client.financials(args.ticker, statement=args.statement, period=args.period)
            elif args.command == "lppl":
                payload = client.lppl_analysis(args.name, depth=args.depth, view=args.view)
            elif args.command == "macro-focus":
                payload = client.macro_focus(args.name, depth=args.depth, view=args.view)
            elif args.command == "calendar":
                payload = client.calendar_events(
                    year=args.year,
                    month=args.month,
                    categories=args.categories,
                    limit=args.limit,
                )
            elif args.command == "runtime-agents":
                payload = client.runtime_agents()
            elif args.command == "runtime-create-session":
                payload = client.runtime_create_session(
                    args.agent_name,
                    session_id=args.session_id,
                    system_prompt=args.system_prompt,
                )
            elif args.command == "runtime-session":
                payload = client.runtime_session(args.session_id)
            elif args.command == "runtime-message":
                payload = client.runtime_message(args.session_id, args.content)
            elif args.command == "runtime-tasks":
                payload = client.runtime_session_tasks(args.session_id)
            elif args.command == "runtime-approvals":
                payload = client.runtime_session_approvals(args.session_id)
            elif args.command == "runtime-task":
                payload = client.runtime_task(args.task_id)
            elif args.command == "runtime-approval":
                payload = client.runtime_approval(args.approval_id)
            elif args.command == "runtime-cancel-task":
                payload = client.runtime_cancel_task(args.task_id)
            elif args.command == "runtime-approve-approval":
                payload = client.runtime_approve_approval(args.approval_id, note=args.note)
            elif args.command == "runtime-deny-approval":
                payload = client.runtime_deny_approval(args.approval_id, note=args.note)
            elif args.command == "open-chart":
                payload = client.open_chart(args.names, session_id=args.session_id)
            else:  # pragma: no cover - argparse keeps this unreachable
                raise RuntimeError(f"Unknown command: {args.command}")
        if args.command == "models":
            print(_format_models_output(args, payload))
        else:
            _emit(payload)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
