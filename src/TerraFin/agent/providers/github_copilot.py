from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from openai import OpenAI

from TerraFin.env import ensure_runtime_env_loaded, resolve_state_dir

from ..conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinModelTurn,
    TerraFinToolCall,
    iter_tool_result_blocks,
    iter_tool_use_blocks,
)
from ..definitions import TerraFinAgentDefinition
from ..model_management import resolve_provider_secret
from ..model_runtime import (
    TerraFinModelConfigError,
    TerraFinModelProvider,
    TerraFinModelResponseError,
    TerraFinRuntimeModel,
)
from ..runtime import TerraFinAgentSession
from ..tools import TerraFinToolDefinition


DEFAULT_COPILOT_MODEL = "gpt-4o"
DEFAULT_COPILOT_TIMEOUT_SECONDS = 60.0
DEFAULT_COPILOT_MAX_RETRIES = 2
DEFAULT_COPILOT_API_BASE_URL = "https://api.individual.githubcopilot.com"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
GITHUB_DEVICE_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_DEVICE_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEFAULT_GITHUB_DEVICE_SCOPE = "read:user"
_COPILOT_MODEL_RE = re.compile(r"^(gpt-[a-z0-9][a-z0-9.-]*|o[a-z0-9][a-z0-9.-]*)$", re.IGNORECASE)
COPILOT_IDE_HEADERS = {
    "Editor-Version": "vscode/1.96.2",
    "User-Agent": "GitHubCopilotChat/0.26.7",
    "X-Github-Api-Version": "2025-04-01",
}


class TerraFinGithubCopilotConfigError(TerraFinModelConfigError):
    """Raised when hosted GitHub Copilot runtime configuration is missing or invalid."""


class TerraFinGithubCopilotResponseError(TerraFinModelResponseError):
    """Raised when the GitHub Copilot API returns an invalid or failed payload."""


class TerraFinGithubCopilotAuthError(Exception):
    """Raised when GitHub Copilot auth/login flows fail."""


@dataclass(frozen=True, slots=True)
class TerraFinGithubCopilotConfig:
    github_token: str
    timeout_seconds: float = DEFAULT_COPILOT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_COPILOT_MAX_RETRIES
    token_url: str = COPILOT_TOKEN_URL
    token_cache_path: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TerraFinGithubCopilotConfig":
        if env is None:
            ensure_runtime_env_loaded()
        source = env if env is not None else os.environ
        github_token, _ = resolve_provider_secret("github-copilot", env)
        github_token = str(github_token or "").strip()
        if not github_token:
            raise TerraFinGithubCopilotConfigError(
                "COPILOT_GITHUB_TOKEN, GH_TOKEN, or GITHUB_TOKEN is required for the hosted GitHub Copilot runtime."
            )
        timeout_raw = source.get("TERRAFIN_COPILOT_TIMEOUT_SECONDS", "").strip() or str(
            DEFAULT_COPILOT_TIMEOUT_SECONDS
        )
        retry_raw = source.get("TERRAFIN_COPILOT_MAX_RETRIES", "").strip() or str(DEFAULT_COPILOT_MAX_RETRIES)
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise TerraFinGithubCopilotConfigError("TERRAFIN_COPILOT_TIMEOUT_SECONDS must be numeric.") from exc
        try:
            max_retries = int(retry_raw)
        except ValueError as exc:
            raise TerraFinGithubCopilotConfigError("TERRAFIN_COPILOT_MAX_RETRIES must be an integer.") from exc
        if max_retries < 0:
            raise TerraFinGithubCopilotConfigError("TERRAFIN_COPILOT_MAX_RETRIES cannot be negative.")
        token_cache_path = source.get("TERRAFIN_COPILOT_TOKEN_CACHE_PATH", "").strip() or None
        return cls(
            github_token=github_token,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            token_cache_path=token_cache_path,
        )


@dataclass(frozen=True, slots=True)
class TerraFinGithubDeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in_seconds: int
    interval_seconds: int

    @property
    def authorization_url(self) -> str:
        return self.verification_uri_complete or self.verification_uri


def request_github_copilot_device_code(
    *,
    session: requests.Session | None = None,
    timeout_seconds: float = DEFAULT_COPILOT_TIMEOUT_SECONDS,
    scope: str = DEFAULT_GITHUB_DEVICE_SCOPE,
) -> TerraFinGithubDeviceCode:
    client = session or requests.Session()
    response = client.post(
        GITHUB_DEVICE_CODE_URL,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "client_id": GITHUB_DEVICE_CLIENT_ID,
            "scope": str(scope or DEFAULT_GITHUB_DEVICE_SCOPE).strip() or DEFAULT_GITHUB_DEVICE_SCOPE,
        },
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise TerraFinGithubCopilotAuthError(f"GitHub device code failed: HTTP {response.status_code}")
    payload = _parse_json_mapping(
        response=response,
        error_cls=TerraFinGithubCopilotAuthError,
        fallback_message="GitHub device code returned a non-JSON payload.",
    )
    device_code = str(payload.get("device_code") or "").strip()
    user_code = str(payload.get("user_code") or "").strip()
    verification_uri = str(payload.get("verification_uri") or "").strip()
    verification_uri_complete = str(payload.get("verification_uri_complete") or "").strip() or None
    try:
        expires_in_seconds = int(payload.get("expires_in") or 0)
        interval_seconds = int(payload.get("interval") or 0)
    except (TypeError, ValueError) as exc:
        raise TerraFinGithubCopilotAuthError("GitHub device code response has invalid timing fields.") from exc
    if not device_code or not user_code or not verification_uri:
        raise TerraFinGithubCopilotAuthError("GitHub device code response missing fields.")
    if expires_in_seconds <= 0:
        raise TerraFinGithubCopilotAuthError("GitHub device code response missing expires_in.")
    if interval_seconds <= 0:
        interval_seconds = 5
    return TerraFinGithubDeviceCode(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=verification_uri_complete,
        expires_in_seconds=expires_in_seconds,
        interval_seconds=interval_seconds,
    )


def poll_github_copilot_device_access_token(
    *,
    device_code: str,
    interval_seconds: int,
    expires_in_seconds: int,
    session: requests.Session | None = None,
    timeout_seconds: float = DEFAULT_COPILOT_TIMEOUT_SECONDS,
    sleep_fn: Any = time.sleep,
    now_fn: Any = time.monotonic,
) -> str:
    normalized_device_code = str(device_code or "").strip()
    if not normalized_device_code:
        raise TerraFinGithubCopilotAuthError("GitHub device code is required.")
    if expires_in_seconds <= 0:
        raise TerraFinGithubCopilotAuthError("GitHub device code expiry must be positive.")
    client = session or requests.Session()
    poll_interval_seconds = max(1, int(interval_seconds or 0))
    deadline = float(now_fn()) + float(expires_in_seconds)
    while float(now_fn()) < deadline:
        response = client.post(
            GITHUB_DEVICE_ACCESS_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "client_id": GITHUB_DEVICE_CLIENT_ID,
                "device_code": normalized_device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=timeout_seconds,
        )
        if response.status_code >= 400:
            raise TerraFinGithubCopilotAuthError(f"GitHub device token failed: HTTP {response.status_code}")
        payload = _parse_json_mapping(
            response=response,
            error_cls=TerraFinGithubCopilotAuthError,
            fallback_message="GitHub device token returned a non-JSON payload.",
        )
        access_token = str(payload.get("access_token") or "").strip()
        if access_token:
            return access_token
        error_code = str(payload.get("error") or "unknown").strip() or "unknown"
        if error_code == "authorization_pending":
            sleep_fn(poll_interval_seconds)
            continue
        if error_code == "slow_down":
            poll_interval_seconds += 2
            sleep_fn(poll_interval_seconds)
            continue
        if error_code == "expired_token":
            raise TerraFinGithubCopilotAuthError("GitHub device code expired; run login again.")
        if error_code == "access_denied":
            raise TerraFinGithubCopilotAuthError("GitHub login cancelled.")
        raise TerraFinGithubCopilotAuthError(f"GitHub device flow error: {error_code}")
    raise TerraFinGithubCopilotAuthError("GitHub device code expired; run login again.")


def _parse_json_mapping(
    *,
    response: Any,
    error_cls: type[Exception],
    fallback_message: str,
) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise error_cls(fallback_message) from exc
    if not isinstance(payload, Mapping):
        raise error_cls(fallback_message)
    return payload


class TerraFinGithubCopilotResponsesProvider(TerraFinModelProvider):
    provider_id = "github-copilot"
    label = "GitHub Copilot"

    def __init__(
        self,
        *,
        config: TerraFinGithubCopilotConfig | None = None,
        env: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._env = env
        self._session = session or requests.Session()

    @property
    def config(self) -> TerraFinGithubCopilotConfig:
        if self._config is None:
            self._config = TerraFinGithubCopilotConfig.from_env(self._env)
        return self._config

    def resolve_model(self, model_id: str) -> TerraFinRuntimeModel:
        normalized = str(model_id or "").strip()
        if not normalized:
            raise TerraFinGithubCopilotConfigError("GitHub Copilot model ids must not be empty.")
        if not _COPILOT_MODEL_RE.match(normalized):
            raise TerraFinGithubCopilotConfigError(
                f"Unsupported GitHub Copilot model id '{normalized}'. TerraFin v1 supports the OpenAI-compatible Copilot family only."
            )
        return TerraFinRuntimeModel(
            model_ref=f"{self.provider_id}/{normalized}",
            provider_id=self.provider_id,
            provider_label=self.label,
            model_id=normalized,
        )

    def complete(
        self,
        *,
        model: TerraFinRuntimeModel,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
    ) -> TerraFinModelTurn:
        token_info = self._resolve_api_token()
        client = OpenAI(
            api_key=token_info["token"],
            base_url=token_info["baseUrl"],
            timeout=self.config.timeout_seconds,
            default_headers=COPILOT_IDE_HEADERS,
        )
        payload = {
            "model": model.model_id,
            "messages": self._messages_to_chat(messages=messages, conversation=conversation),
            "tools": [self._tool_to_chat_completion(tool) for tool in tools],
        }
        response = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = client.chat.completions.create(**payload)
                break
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                retryable = status_code is None or status_code == 429 or int(status_code) >= 500
                if attempt >= self.config.max_retries or not retryable:
                    raise TerraFinGithubCopilotResponseError(str(exc)) from exc
        if response is None:
            raise TerraFinGithubCopilotResponseError("GitHub Copilot did not return a completion payload.")
        return self._completion_to_turn(response)

    def _resolve_api_token(self) -> dict[str, Any]:
        cache_path = self._resolve_token_cache_path()
        cached = self._load_cached_token(cache_path)
        now_ms = int(time.time() * 1000)
        if cached is not None and int(cached.get("expiresAt", 0)) - now_ms > 5 * 60 * 1000:
            return {
                "token": str(cached["token"]),
                "expiresAt": int(cached["expiresAt"]),
                "baseUrl": str(cached.get("baseUrl") or DEFAULT_COPILOT_API_BASE_URL),
            }

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.github_token}",
            **COPILOT_IDE_HEADERS,
        }
        response = self._session.get(
            self.config.token_url,
            headers=headers,
            timeout=self.config.timeout_seconds,
        )
        if response.status_code >= 400:
            raise TerraFinGithubCopilotResponseError(f"Copilot token exchange failed: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TerraFinGithubCopilotResponseError("Copilot token exchange returned a non-JSON payload.") from exc
        token, expires_at = self._parse_token_payload(payload)
        base_url = self._derive_api_base_url(token) or DEFAULT_COPILOT_API_BASE_URL
        cached_payload = {
            "token": token,
            "expiresAt": expires_at,
            "updatedAt": now_ms,
            "baseUrl": base_url,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cached_payload, ensure_ascii=True), encoding="utf-8")
        return {
            "token": token,
            "expiresAt": expires_at,
            "baseUrl": base_url,
        }

    def _resolve_token_cache_path(self) -> Path:
        if self.config.token_cache_path:
            return Path(self.config.token_cache_path).expanduser()
        return resolve_state_dir() / "credentials" / "github-copilot.token.json"

    def _tool_to_chat_completion(self, tool: TerraFinToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    def _messages_to_chat(
        self,
        *,
        messages: tuple[TerraFinConversationMessage, ...],
        conversation: TerraFinHostedConversation,
    ) -> list[dict[str, Any]]:
        chat_messages: list[dict[str, Any]] = []
        pending_tool_calls: list[dict[str, Any]] = []

        def flush_pending_tool_calls() -> None:
            nonlocal pending_tool_calls
            if not pending_tool_calls:
                return
            chat_messages.append({"role": "assistant", "content": "", "tool_calls": pending_tool_calls})
            pending_tool_calls = []

        for message in messages:
            tool_use_blocks = iter_tool_use_blocks(message)
            if tool_use_blocks:
                for block in tool_use_blocks:
                    pending_tool_calls.append(
                        {
                            "id": str(block.payload.get("callId") or "").strip(),
                            "type": "function",
                            "function": {
                                "name": str(block.payload.get("toolName") or "").strip(),
                                "arguments": json.dumps(block.payload.get("arguments", {}), ensure_ascii=True),
                            },
                        }
                    )
                if not message.content.strip():
                    continue
            if message.role == "tool":
                flush_pending_tool_calls()
                tool_result_blocks = iter_tool_result_blocks(message)
                tool_result_block = tool_result_blocks[0] if tool_result_blocks else None
                if not message.tool_call_id:
                    continue
                content = (
                    json.dumps(tool_result_block.payload.get("payload", {}), ensure_ascii=False)
                    if tool_result_block is not None
                    else message.content
                )
                chat_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": content,
                    }
                )
                continue
            flush_pending_tool_calls()
            if message.role not in {"system", "user", "assistant"}:
                continue
            chat_messages.append(
                {
                    "role": message.role,
                    "content": message.content,
                }
            )

        flush_pending_tool_calls()
        return chat_messages

    def _completion_to_turn(self, response: Any) -> TerraFinModelTurn:
        payload = response.model_dump(mode="python") if hasattr(response, "model_dump") else response
        if not isinstance(payload, Mapping):
            raise TerraFinGithubCopilotResponseError("GitHub Copilot returned an unexpected completion payload.")
        choices = payload.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise TerraFinGithubCopilotResponseError("GitHub Copilot completion payload did not include choices.")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise TerraFinGithubCopilotResponseError("GitHub Copilot completion choice was invalid.")
        message = choice.get("message", {})
        if not isinstance(message, Mapping):
            raise TerraFinGithubCopilotResponseError("GitHub Copilot completion message was invalid.")

        assistant_text = str(message.get("content") or "").strip()
        assistant_message = (
            TerraFinConversationMessage(role="assistant", content=assistant_text) if assistant_text else None
        )

        tool_calls: list[TerraFinToolCall] = []
        raw_tool_calls = message.get("tool_calls", [])
        if isinstance(raw_tool_calls, list):
            for index, item in enumerate(raw_tool_calls):
                if not isinstance(item, Mapping):
                    continue
                function = item.get("function", {})
                if not isinstance(function, Mapping):
                    continue
                tool_name = str(function.get("name") or "").strip()
                arguments_raw = function.get("arguments")
                if isinstance(arguments_raw, str) and arguments_raw.strip():
                    try:
                        arguments = json.loads(arguments_raw)
                    except json.JSONDecodeError as exc:
                        raise TerraFinGithubCopilotResponseError(
                            f"GitHub Copilot tool arguments for '{tool_name or 'unknown'}' were not valid JSON."
                        ) from exc
                else:
                    arguments = {}
                if not isinstance(arguments, Mapping):
                    raise TerraFinGithubCopilotResponseError(
                        f"GitHub Copilot tool arguments for '{tool_name or 'unknown'}' must decode to an object."
                    )
                call_id = str(item.get("id") or f"copilot-call:{index}").strip()
                if not call_id or not tool_name:
                    raise TerraFinGithubCopilotResponseError(
                        "GitHub Copilot tool call payload was missing id or function name."
                    )
                tool_calls.append(
                    TerraFinToolCall(
                        call_id=call_id,
                        tool_name=tool_name,
                        arguments=dict(arguments),
                    )
                )

        return TerraFinModelTurn(
            assistant_message=assistant_message,
            tool_calls=tuple(tool_calls),
            stop_reason="tool_calls" if tool_calls else "completed",
        )

    def _load_cached_token(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _parse_token_payload(self, payload: Any) -> tuple[str, int]:
        if not isinstance(payload, Mapping):
            raise TerraFinGithubCopilotResponseError("Unexpected response from GitHub Copilot token endpoint.")
        token = str(payload.get("token") or "").strip()
        expires_at_raw = payload.get("expires_at")
        if not token:
            raise TerraFinGithubCopilotResponseError("Copilot token response missing token.")
        if isinstance(expires_at_raw, (int, float)):
            expires_at = int(expires_at_raw)
        elif isinstance(expires_at_raw, str) and expires_at_raw.strip():
            try:
                expires_at = int(expires_at_raw.strip())
            except ValueError as exc:
                raise TerraFinGithubCopilotResponseError("Copilot token response has invalid expires_at.") from exc
        else:
            raise TerraFinGithubCopilotResponseError("Copilot token response missing expires_at.")
        if expires_at < 100_000_000_000:
            expires_at *= 1000
        return token, expires_at

    def _derive_api_base_url(self, token: str) -> str | None:
        match = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", token)
        proxy_endpoint = match.group(1).strip() if match else ""
        if not proxy_endpoint:
            return None
        url_text = (
            proxy_endpoint if proxy_endpoint.startswith(("http://", "https://")) else f"https://{proxy_endpoint}"
        )
        try:
            parsed = requests.utils.urlparse(url_text)
        except Exception:
            return None
        host = (parsed.hostname or "").strip().lower()
        if not host:
            return None
        api_host = re.sub(r"^proxy\.", "api.", host)
        return f"https://{api_host}"
