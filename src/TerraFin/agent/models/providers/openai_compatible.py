import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from openai import APIError

from ...conversation import (
    TerraFinConversationMessage,
    TerraFinHostedConversation,
    TerraFinModelTurn,
    TerraFinToolCall,
)
from ...contracts.conversation_state import iter_tool_call_history
from ...conversation_state import get_provider_state, set_provider_state
from ...definitions import TerraFinAgentDefinition
from ...runtime.session import TerraFinAgentSession
from ...tools import TerraFinToolDefinition

_logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

_MAX_CHAIN_RECOVERIES = 2
# Strikes expire by wall clock, not by turns: a recovery clears the chain, so the
# next turn cannot resume, so a turn-based decay could never reach the limit
# while holding forever made a single benign 400 disable resuming for good.
_CHAIN_STRIKE_TTL_SECONDS = 3600


class OpenAICompatibleResponsesRunner:
    def __init__(
        self,
        *,
        provider_id: str,
        max_retries: int,
        response_error_cls: type[RuntimeError],
    ) -> None:
        self.provider_id = provider_id
        self.max_retries = max(max_retries, 0)
        self.response_error_cls = response_error_cls

    def complete(
        self,
        *,
        client: Any,
        model_id: str,
        agent: TerraFinAgentDefinition,
        session: TerraFinAgentSession,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
        legacy_response_id: str | None = None,
        legacy_message_cursor: int = 0,
        legacy_response_id_key: str | None = None,
    ) -> TerraFinModelTurn:
        _ = session
        payload = self._build_request_payload(
            model_id=model_id,
            agent=agent,
            conversation=conversation,
            messages=messages,
            tools=tools,
            legacy_response_id=legacy_response_id,
            legacy_message_cursor=legacy_message_cursor,
            legacy_response_id_key=legacy_response_id_key,
        )
        response = None
        attempt = 0
        recovered_chain = False
        attempted_resume = "previous_response_id" in payload
        while True:
            try:
                response = client.responses.create(**payload)
                break
            except APIError as exc:
                status_code = getattr(exc, "status_code", None)
                sent_chain = "previous_response_id" in payload
                if not recovered_chain and self._is_dead_chain_error(exc, sent_chain=sent_chain):
                    recovered_chain = True
                    _logger.warning(
                        "%s: abandoning unusable response chain and retrying fresh: %s",
                        self.provider_id,
                        exc,
                    )
                    self._abandon_chain(
                        conversation,
                        get_provider_state(conversation, self.provider_id),
                        legacy_response_id_key,
                    )
                    payload = self._build_request_payload(
                        model_id=model_id,
                        agent=agent,
                        conversation=conversation,
                        messages=messages,
                        tools=tools,
                        legacy_response_id=None,
                        legacy_message_cursor=0,
                        legacy_response_id_key=legacy_response_id_key,
                        force_fresh=True,
                    )
                    continue
                retryable = status_code is None or status_code == 429 or int(status_code) >= 500
                if attempt >= self.max_retries or not retryable:
                    raise self.response_error_cls(str(exc)) from exc
                attempt += 1
            except Exception as exc:
                raise self.response_error_cls(str(exc)) from exc
        if response is None:
            raise self.response_error_cls("Provider SDK did not return a response payload.")
        data = self._to_payload(response)
        response_id = data.get("id")
        if not response_id:
            raise self.response_error_cls("Provider response did not include an id.")

        tool_calls = self._extract_tool_calls(data)
        state_before = get_provider_state(conversation, self.provider_id)
        set_provider_state(
            conversation,
            self.provider_id,
            {
                **get_provider_state(conversation, self.provider_id),
                "responseId": response_id,
                "messageCursor": len(conversation.messages),
                "sentThrough": self._latest_created_at(conversation),
                "openCallIds": [call.call_id for call in tool_calls],
                # Only a resume that actually ran and worked clears the strike
                # count. Resetting on any success cleared it on the very next
                # (non-resumed) turn, turning the counter into a one-turn cooldown
                # that oscillates 2-1-2-1 requests forever.
                "chainRecoveries": self._next_recoveries(
                    state_before,
                    attempted_resume=attempted_resume,
                    recovered_chain=recovered_chain,
                ),
                "chainRecoveriesAt": (
                    _utc_now_iso() if recovered_chain else state_before.get("chainRecoveriesAt")
                ),
            },
        )

        assistant_text = self._extract_assistant_text(data)
        assistant_message = (
            TerraFinConversationMessage(role="assistant", content=assistant_text) if assistant_text else None
        )
        return TerraFinModelTurn(
            assistant_message=assistant_message,
            tool_calls=tuple(tool_calls),
            stop_reason="tool_calls" if tool_calls else "completed",
        )

    def _build_request_payload(
        self,
        *,
        model_id: str,
        agent: TerraFinAgentDefinition,
        conversation: TerraFinHostedConversation,
        messages: tuple[TerraFinConversationMessage, ...],
        tools: tuple[TerraFinToolDefinition, ...],
        legacy_response_id: str | None,
        legacy_message_cursor: int,
        legacy_response_id_key: str | None = None,
        force_fresh: bool = False,
    ) -> dict[str, Any]:
        state = get_provider_state(conversation, self.provider_id)
        previous_response_id = str(state.get("responseId") or legacy_response_id or "").strip() or None
        resume = self._resume_messages(conversation, state, legacy_message_cursor)
        if resume is not None:
            resume = self._budgeted_tail(resume, messages)
        if force_fresh or not resume or not previous_response_id:
            if previous_response_id:
                self._abandon_chain(conversation, state, legacy_response_id_key)
            previous_response_id = None
            input_items = self._messages_to_input(messages, as_plain_text=True)
        else:
            input_items = self._messages_to_input(resume)

        payload: dict[str, Any] = {
            "model": model_id,
            "tools": [self._tool_to_openai(tool) for tool in tools],
            "input": input_items,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if not previous_response_id:
            payload["instructions"] = (
                f"You are '{agent.name}'. "
                "Follow the user's format instructions exactly — do not add preamble, commentary, or conclusions outside the requested format. "
                "Use tools only when the user's data is insufficient; if the user provides all necessary data inline, respond directly without tool calls. "
                "Never fabricate specific numbers (prices, percentages, EPS values) not present in the provided data."
            )
        return payload

    def _decline_resume(self, reason: str) -> None:
        """Log why a resume was declined. Every exit was silent, so a resume that
        stops engaging looked identical to one that never applied: correctness
        intact, cost and latency up, nothing in the tests or logs."""
        _logger.debug("%s: resuming declined (%s)", self.provider_id, reason)
        return None

    def _strikes_active(self, state: Mapping[str, Any]) -> bool:
        """True while recent recoveries say this session's resume cannot be trusted."""
        try:
            strikes = int(state.get("chainRecoveries", 0) or 0)
        except (TypeError, ValueError):
            return False
        if strikes < _MAX_CHAIN_RECOVERIES:
            return False
        earned = self._as_datetime(state.get("chainRecoveriesAt"))
        if earned is None:
            return True
        try:
            age = (datetime.now(earned.tzinfo) - earned).total_seconds()
        except (TypeError, ValueError):
            return True
        return age < _CHAIN_STRIKE_TTL_SECONDS

    @staticmethod
    def _next_recoveries(
        state: Mapping[str, Any],
        *,
        attempted_resume: bool,
        recovered_chain: bool,
    ) -> int:
        try:
            current = max(int(state.get("chainRecoveries", 0) or 0), 0)
        except (TypeError, ValueError):
            current = 0
        if recovered_chain:
            return current + 1
        if attempted_resume:
            return 0  # a resume ran and worked: the chain is healthy again
        return current  # no resume was attempted; the count says nothing new

    @staticmethod
    def _is_dead_chain_error(exc: Exception, *, sent_chain: bool) -> bool:
        """A 400 on a request that carried `previous_response_id` is unusable-chain.

        Matched structurally, not on provider prose: the three English phrases this
        used to grep for are not a contract, and a reworded body would have left
        every test green while production reverted to a bricked session. Retrying
        once on a fresh chain is safe because that request is self-contained.
        """
        return sent_chain and int(getattr(exc, "status_code", 0) or 0) == 400

    @staticmethod
    def _as_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _latest_created_at(self, conversation: TerraFinHostedConversation) -> str | None:
        stamps = [
            stamp
            for stamp in (self._as_datetime(getattr(m, "created_at", None)) for m in conversation.messages)
            if stamp is not None
        ]
        return max(stamps).isoformat() if stamps else None

    def _resume_messages(
        self,
        conversation: TerraFinHostedConversation,
        state: Mapping[str, Any],
        legacy_message_cursor: int,
    ) -> tuple[TerraFinConversationMessage, ...] | None:
        """Messages appended since the chain's last response, or None to start fresh.

        Keyed on `created_at`, not on a count: `loop.py:511-516` deletes the prior
        working-memory note from `conversation.messages` in place on every user
        turn, so an absolute index silently omits one message — a deferred research
        report, or in the early-return case the user's own question.
        """
        if self._strikes_active(state):
            return self._decline_resume("recent chain recoveries")
        if self._unanswered_call_ids(conversation, state):
            return self._decline_resume("a recorded tool call has no result")
        watermark = self._as_datetime(state.get("sentThrough"))
        if watermark is not None:
            try:
                # Contiguous tail, not a timestamp filter. The synthetic carrier
                # now inherits its paired result's created_at, so stamps are
                # non-strictly monotonic — but a filter would still admit any
                # future-dated message while skipping real turns before it, and
                # `prepared[-len(resume):]` needs a contiguous slice to align
                # against. Ties are why the boundary is `<=`, not `<`.
                boundary = -1
                for index, message in enumerate(conversation.messages):
                    stamp = self._as_datetime(getattr(message, "created_at", None))
                    if stamp is not None and stamp <= watermark:
                        boundary = index
                resume = tuple(conversation.messages[boundary + 1 :])
            except TypeError:
                return self._decline_resume("naive/aware timestamp mix")
        else:
            # No watermark: a pre-existing session. The old index counted a list that
            # loop.py:511-516 edits in place, so it dropped a message. Take one fresh
            # chain instead; this turn's success writes the watermark.
            _ = legacy_message_cursor
            return self._decline_resume("no sentThrough watermark (pre-existing session)")
        if not resume:
            return self._decline_resume("no new messages since the last response")
        return resume

    def _budgeted_tail(
        self,
        resume: tuple[TerraFinConversationMessage, ...],
        prepared: tuple[TerraFinConversationMessage, ...],
    ) -> tuple[TerraFinConversationMessage, ...] | None:
        """The resume slice taken from `prepared`, or None to start fresh.

        The last N of `prepared` are taken as the same turns as the last N of the
        slice. That alignment is approximate: `normalize_for_model` drops unpaired
        assistant tool_use messages and inserts synthetic ones, so an assistant slot
        can be substituted. Harmless only because `_messages_to_input` never sends
        assistant messages on a resume; tool slots are checked by call id. Taking them from
        `prepared` means the wire content is whatever the budget manager approved,
        and it shrinks with the level, which keeps loop.py's ladder monotone.

        Comparing raw content instead cannot work: `execution.py:64-77` emits the
        optional tool-result keys only when set while `context_budget.py:180-194`
        always emits all nine, so the two strings never match on a tool turn.
        """
        if not resume:
            return None
        if len(resume) > len(prepared):
            return self._decline_resume("resume slice longer than the budgeted window")
        tail = tuple(prepared[-len(resume) :])
        if [message.role for message in tail] != [message.role for message in resume]:
            return self._decline_resume("role sequence misaligned with the budgeted window")
        for original, approved in zip(resume, tail, strict=True):
            if original.role == "tool" and str(original.tool_call_id or "") != str(
                approved.tool_call_id or ""
            ):
                return self._decline_resume("tool_call_id misaligned with the budgeted window")
        return tail

    @staticmethod
    def _satisfied_call_ids(conversation: TerraFinHostedConversation) -> set[str]:
        return {
            str(message.tool_call_id).strip()
            for message in conversation.messages
            if message.role == "tool" and str(message.tool_call_id or "").strip()
        }

    def _unanswered_call_ids(
        self,
        conversation: TerraFinHostedConversation,
        state: Mapping[str, Any],
    ) -> set[str]:
        """Calls the current chain is still waiting on.

        Prefers `openCallIds`, recorded from the response that made them, because
        that is the exact set the API validates. Falls back to the whole-conversation
        ledger for chains started before that field existed.
        """
        satisfied = self._satisfied_call_ids(conversation)
        open_ids = state.get("openCallIds")
        if isinstance(open_ids, (list, tuple)):
            candidates = (str(item).strip() for item in open_ids)
        else:
            candidates = (str(record.get("callId") or "").strip() for record in iter_tool_call_history(conversation))
        return {item for item in candidates if item and item not in satisfied}

    def _abandon_chain(
        self,
        conversation: TerraFinHostedConversation,
        state: Mapping[str, Any],
        legacy_response_id_key: str | None,
    ) -> None:
        """Write off a chain whose pending calls can never be answered.

        Recorded in provider state, not in toolCallHistory: that ledger is
        re-derived from the transcript on every persist, so edits to it vanish.
        """
        set_provider_state(
            conversation,
            self.provider_id,
            {**dict(state), "responseId": None, "openCallIds": []},
        )
        if legacy_response_id_key:
            conversation.metadata[legacy_response_id_key] = None

    def _messages_to_input(
        self,
        messages: tuple[TerraFinConversationMessage, ...],
        *,
        as_plain_text: bool = False,
    ) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "assistant":
                # A fresh chain has no server-side copy of the assistant's turns, so
                # replay them as text rather than losing every prior answer.
                if as_plain_text and str(message.content or "").strip():
                    input_items.append({"role": "assistant", "content": message.content})
                continue
            if message.role == "tool":
                if not message.tool_call_id:
                    continue
                if as_plain_text:
                    # A fresh chain has no function_call for this output to answer,
                    # so send the data as text rather than losing it.
                    input_items.append(
                        self._text_item(f"[tool result: {message.name}]\n{message.content}")
                    )
                    continue
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
                continue
            input_items.append(
                {
                    "type": "message",
                    "role": message.role,
                    "content": [{"type": "input_text", "text": message.content}],
                }
            )
        return input_items

    @staticmethod
    def _text_item(text: str) -> dict[str, Any]:
        return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}

    def _tool_to_openai(self, tool: TerraFinToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }

    def _extract_tool_calls(self, payload: Mapping[str, Any]) -> tuple[TerraFinToolCall, ...]:
        calls: list[TerraFinToolCall] = []
        for item in payload.get("output", []):
            if not isinstance(item, Mapping) or item.get("type") != "function_call":
                continue
            arguments_raw = item.get("arguments")
            if isinstance(arguments_raw, str) and arguments_raw.strip():
                try:
                    arguments = json.loads(arguments_raw)
                except json.JSONDecodeError as exc:
                    raise self.response_error_cls(
                        f"Provider function_call arguments for '{item.get('name')}' were not valid JSON."
                    ) from exc
            else:
                arguments = {}
            if not isinstance(arguments, Mapping):
                raise self.response_error_cls(
                    f"Provider function_call arguments for '{item.get('name')}' must decode to an object."
                )
            call_id = str(item.get("call_id") or item.get("id") or "").strip()
            tool_name = str(item.get("name") or "").strip()
            if not call_id or not tool_name:
                raise self.response_error_cls("Provider function_call response was missing call_id or name.")
            calls.append(
                TerraFinToolCall(
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=dict(arguments),
                )
            )
        return tuple(calls)

    def _extract_assistant_text(self, payload: Mapping[str, Any]) -> str:
        texts: list[str] = []
        for item in payload.get("output", []):
            if not isinstance(item, Mapping):
                continue
            if item.get("type") != "message" or item.get("role") != "assistant":
                continue
            for content in item.get("content", []):
                if not isinstance(content, Mapping):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
        if texts:
            return "\n".join(texts).strip()
        output_text = payload.get("output_text")
        return output_text.strip() if isinstance(output_text, str) else ""

    def _to_payload(self, response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            payload = response.model_dump(mode="python")
            if isinstance(payload, dict):
                return payload
        if isinstance(response, Mapping):
            return dict(response)
        raise self.response_error_cls("Provider SDK returned an unexpected response payload.")
