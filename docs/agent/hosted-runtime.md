---
title: Hosted Runtime
summary: Maintainer guide to TerraFin's current hosted runtime, transcript-first session storage, adapters, and regression surfaces.
read_when:
  - Maintaining the hosted agent loop
  - Changing runtime endpoints, transcript storage, tool adapters, or the browser widget
  - Verifying which files define the current hosted runtime behavior
---

# Hosted Runtime

This document is the implementation-focused companion to
[architecture.md](./architecture.md).

It answers a narrower question:

> What is actually implemented today for TerraFin's hosted runtime, and where do
> the important seams live?

!!! note "Reference Boundary"
    TerraFin's transcript-first session persistence follows the same core shape
    used by OpenClaw and Claude Code: append-only per-session transcripts with a
    separate session index and explicit rewrite paths. TerraFin's runtime
    controller, financial capability layer, task/approval flow, widget, and API
    integration remain TerraFin-specific. The orchestrator-agent-with-persona-
    subagents pattern also takes inspiration from the role-separation style in
    `ai-hedge-fund`, but TerraFin keeps shared capabilities and prompt-level
    persona policy instead of hardcoded per-guru analysis modules — see the
    diagrams in [architecture.md](./architecture.md#orchestrator-persona-subagents)
    for the authoritative shape.

## Current runtime shape

Today the hosted runtime has:

- a shared financial capability layer
- a hosted agent definition registry
- a policy-enforcing runtime controller
- a hosted tool adapter
- a provider-agnostic hosted loop
- a provider registry with OpenAI and Gemini adapters
- Python, CLI, HTTP, notebook, and browser widget adapters
- transcript-first local session history
- hidden persona subagents (Buffett / Marks / Druckenmiller) reached by
  the main orchestrator agent via `consult_<persona>` tool-calls (see
  the architecture diagrams in
  [architecture.md](./architecture.md#orchestrator-persona-subagents))
- a structured internal tool-result/error protocol
- transcript normalization and repair before model calls
- a proactive context-budget manager with reactive fallback retries

## Transcript-first persistence

Conversation history is no longer stored inside the hosted session record.

Instead TerraFin now splits local hosted state into two layers:

- transcript JSONL files: durable source of truth for message history
- session index JSON: summary metadata for history/list/delete behavior

Default layout under the unified TerraFin state dir:

```text
.terrafin/agent/sessions/sessions.json
.terrafin/agent/sessions/<session-id>.jsonl
```

Transcript events are append-only and currently include:

- `session_header`
- `message`
- `runtime_model`
- `custom_title`
- `compact_boundary`

`session_header` carries `agentName`, plus `origin` and `parentSessionId` when
the creator supplied them in session metadata:

| `origin` | Who created the session |
|---|---|
| `dashboard` | a person typing in the browser widget |
| `pipeline` | a batch stage calling the agent as an LLM |
| `guru` | a hidden worker spawned by a turn; also carries `parentSessionId` |

The names live in `agent/storage/transcript_store.py` (`SESSION_ORIGIN_*`).
An absent `origin` means unknown, which covers the CLI and every transcript
written before the field existed; an unrecognised one is recorded and logged at
warning level. A corpus reader gets both fields from the file's first line, and
`parentSessionId` is what makes a turn and its hidden workers one tree — the
session record also holds them, but the idle sweep deletes it.

`message` events now carry structured internal content blocks as well as the
public `role/content` shape. In practice that means TerraFin can persist:

- assistant text
- hidden internal tool-use turns
- tool results
- retryable tool-error results

without exposing the hidden internal turns in the browser widget or public
session APIs.

Important consequences:

- session list/history is transcript-derived
- reopening a session reconstructs the conversation from transcript events
- deleting a session archives the transcript file with a `.deleted.<timestamp>`
  suffix and removes it from active history
- legacy embedded conversation blobs are ignored and not migrated
- hidden internal guru sessions can still be recorded for runtime/debug purposes,
  but they are filtered out of normal public session history
- hidden guru sessions are also blocked from normal public read/delete/task/approval
  routes even when a caller knows a session id
- deleting a public parent session cascades hidden guru child cleanup

Tasks, approvals, audit, and published view context still live in the hosted
runtime/session store. Only conversation history moved to transcript files.

## Important files

Module paths use the post-refactor canonical locations. Old top-level paths
(e.g. `agent/loop.py`, `agent/transcript_store.py`) remain as compatibility
shims — see [architecture.md § Current code map](./architecture.md#current-code-map)
for the full old → new mapping.

| File | What it owns |
|------|---------------|
| `src/TerraFin/agent/runtime/capability.py` | capability registry, session context, task registry, artifact tracking |
| `src/TerraFin/agent/contracts/definitions.py` | hosted agent definitions and allowlists |
| `src/TerraFin/agent/runtime/hosted.py` | session lifecycle, policy enforcement, task dispatch, transcript-aware session access |
| `src/TerraFin/agent/runtime/loop.py` | hosted loop, immediate message append flow, provider state persistence |
| `src/TerraFin/agent/contracts/conversation.py` | internal message/block protocol and conversation dataclasses |
| `src/TerraFin/agent/guru/worker.py` | route planning, hidden guru execution, and structured memo synthesis |
| `src/TerraFin/agent/tools/execution.py` | structured tool execution outcomes and tool-result message creation |
| `src/TerraFin/agent/runtime/transcript_normalizer.py` | transcript repair, tool-use/tool-result pairing, internal/public view split |
| `src/TerraFin/agent/runtime/context_budget.py` | proactive prompt-budget estimation and compaction levels |
| `src/TerraFin/agent/runtime/recovery.py` | per-turn recovery budget / repeated-error policy |
| `src/TerraFin/agent/storage/transcript_store.py` | append-only transcript store, `sessions.json` index, transcript readers, archive/rewrite helpers |
| `src/TerraFin/agent/storage/session_store.py` | non-transcript hosted state: tasks, approvals, audit, view context, transient conversation attachment |
| `src/TerraFin/agent/models/runtime.py` | provider registry, runtime-model binding, canonical `provider/model` refs |
| `src/TerraFin/agent/models/providers/*.py` | provider adapters for OpenAI and Gemini |
| `src/TerraFin/agent/tools/adapter.py` | function-callable tool definitions and tool execution bridge |
| `src/TerraFin/agent/service/client.py` | Python transport adapter (`TerraFinAgentClient`) |
| `src/TerraFin/agent/cli/main.py` | CLI adapter (`terrafin-agent`) |
| `src/TerraFin/interface/agent/data_routes.py` | HTTP runtime endpoints |
| `src/TerraFin/interface/frontend/src/agent/GlobalAgentWidget.tsx` | floating assistant widget |
| `src/TerraFin/interface/frontend/src/AppRouter.tsx` | mounts the widget across the main pages |

## Runtime endpoint family

Hosted runtime endpoints live under `/agent/api/runtime/*`.

Current routes:

- `GET /agent/api/runtime/agents`
- `POST /agent/api/runtime/sessions`
- `GET /agent/api/runtime/sessions`
- `GET /agent/api/runtime/sessions/{session_id}`
- `DELETE /agent/api/runtime/sessions/{session_id}`
- `POST /agent/api/runtime/sessions/{session_id}/messages`
- `GET /agent/api/runtime/sessions/{session_id}/approvals`
- `GET /agent/api/runtime/tasks/{task_id}`
- `POST /agent/api/runtime/tasks/{task_id}/cancel`
- `GET /agent/api/runtime/approvals/{approval_id}`
- `POST /agent/api/runtime/approvals/{approval_id}/approve`

## Recovery architecture

The hosted loop now follows a stricter internal recovery path inspired by the
kind of guardrails Claude Code uses internally, while keeping TerraFin's own
surface and naming:

- retryable tool/input failures stay inside the loop as structured tool-error results
- fatal upstream auth/quota/provider failures are the main class still surfaced to users
- transcripts are normalized before provider calls so orphaned tool results do not leak into the next turn
- context is proactively compacted before provider calls, with reactive retry levels still kept as a last resort
- `POST /agent/api/runtime/approvals/{approval_id}/deny`
- `PUT /agent/api/runtime/view-contexts/{context_id}`
- `GET /agent/api/runtime/view-contexts/{context_id}`

The browser widget, notebook helpers, CLI runtime commands, and Python client
all sit on top of this same contract.

The runtime catalog intentionally exposes only public agents in the normal
adapter surfaces. Hidden guru roles are internal runtime definitions, not
default user-facing choices, and the public session-create route rejects them
directly.

## Browser behavior

The hosted runtime is not exposed through a dedicated `/agent` page anymore.

Instead:

- the browser UI is a floating assistant widget
- it appears across main interface pages
- it calls the same hosted runtime endpoints as every other adapter

If the deployment does not expose `/agent/api/runtime/*`, the widget should fail
with a clear runtime error rather than silently hanging.

## Current implementation status

What is already there:

- capability metadata and backgroundability markers
- hosted agent definition registry
- policy-enforced capability allowlists
- hosted tool adapter
- provider-backed model loop
- transcript-first local session history
- archived session delete behavior
- hidden persona subagents reached by the main orchestrator agent via
  `consult_<persona>` tool-calls (authoritative shape: [architecture.md
  § Orchestrator + persona subagents](./architecture.md#orchestrator-persona-subagents))
- structured internal guru memos returned to the orchestrator through a
  dedicated memo tool-call contract, not JSON scraped from prose
- notebook helper surface
- browser widget over the runtime endpoints

What is still intentionally lighter:

- automatic transcript compaction
- richer task progress UX
- artifact history UI
- MCP-like external adapter layer

## Regression surfaces

When touching hosted runtime code, the highest-signal regression surfaces are:

- transcript append order for `user -> assistant/tool -> assistant`
- session reopen/history summaries derived from transcript + index
- session delete/archive behavior
- response parsing from each provider
- semantic agreement between the surfaces a capability does expose: HTTP
  reaches nearly all of them, while the Python client and CLI expose a smaller
  subset under the same names and arguments
- widget integration over `/agent/api/runtime/*`

Current tests:

- `tests/agent/test_runtime.py`
- `tests/agent/test_hosted_runtime.py`
- `tests/agent/test_tools.py`
- `tests/agent/test_loop.py`
- `tests/agent/test_transcript_store.py`
- `tests/agent/test_openai_model.py`
- `tests/agent/test_google_provider.py`
- `tests/agent/test_runtime_helpers.py`
- `tests/agent/test_client.py`
- `tests/agent/test_cli.py`
- `tests/interface/test_agent_api.py`

Useful commands:

```bash
pytest tests/agent/test_runtime.py \
  tests/agent/test_hosted_runtime.py \
  tests/agent/test_tools.py \
  tests/agent/test_loop.py \
  tests/agent/test_transcript_store.py \
  tests/agent/test_openai_model.py \
  tests/agent/test_google_provider.py \
  tests/agent/test_runtime_helpers.py \
  tests/agent/test_client.py \
  tests/agent/test_cli.py \
  tests/interface/test_agent_api.py

npm run build
```

## Read next

- [usage.md](./usage.md)
- [architecture.md](./architecture.md)
- [../interface.md](../interface.md)

## Background-task completion delivery

A capability registered with `background_only=True` is never exposed to the
model as a synchronous tool -- only `start_<cap>_task` is. Which capabilities
set it is a property of the registry, not of this document. The model kicks the
task off and keeps talking; the result arrives later. "Later" needs machinery,
because no model turn is running when the task finishes.

The path, end to end:

1. `runtime.start_task(..., origin_tool_call_id=...)` records which tool call
   started the task, so a completion can be traced back to its request.
2. The worker passes a `progress` reporter into the capability handler (injected
   only for handlers that declare the parameter). Each call records
   `task.progress.stage` **and renews the lease**, so a run taking minutes is not
   re-claimed mid-flight by another worker.
3. On completion the worker writes a marker to `hosted_pending_completions` -- a
   dedicated table, not part of the session payload. That isolation matters: an
   unrelated whole-record `persist()` would otherwise clobber a marker a sibling
   task had just written. `(session_id, task_id)` is the primary key, so a
   double-run collapses to one marker via `INSERT OR IGNORE`.
4. On the user's next `submit_user_message`, the loop drains pending completions
   BEFORE the model sees the turn, appending each as a `user`-role message
   flagged `internalOnly`.

Two details are load-bearing:

- **Why a user-role message, not a synthesized tool_use/tool_result pair.** A
  user message is forwarded verbatim by every provider adapter. OpenAI Responses
  drops assistant/tool_use turns and sends only user messages plus
  `function_call_output`; a fabricated `function_call_output` with no matching
  server-side `function_call` is rejected with HTTP 400.
- **Peek-then-clear.** A marker is deleted only AFTER its delivery message is
  appended. A mid-drain failure leaves the marker intact for the next turn, so a
  completion is never silently lost. Delivery is deduped twice: by the store's
  primary key, and by scanning the transcript for an already-delivered `taskId`.

Delivery is **at-most-once on a best-effort basis, not guaranteed**. It rides on
the task layer's at-least-once semantics, so a lease-expiry re-claim can still,
rarely, double-run and double-deliver.

## Verification as a tool

`verify_claims` is the one capability that checks rather than fetches. It exists
because a gate that runs after generation can only delete a wrong number, never
correct it -- so on its own it can only lower answer quality. Exposed as a tool,
the same rules become an acceptance control the model iterates against: draft,
verify, read the repair hint, resubmit.

It is self-contained -- `source_text` in, verdicts out -- so it needs no session
state and works identically in-process, over `/agent/api/verify-claims`, and from
an external agent consuming `skills/terrafin/SKILL.md`.

Grounding is per `(line item, period)`, never per table. A whole-table citation
launders every figure inside it: the prose scan admits any number appearing in a
verified quote, so net income passes as capital expenditure. `facts.py` exists to
make the line item itself the thing that must match, and
`tests/agent/test_deepresearch_facts.py` pins that difference.

Multi-step arithmetic is expressed by NESTING a derivation inside an operand,
with `avg` for a mean -- return on assets is
`margin_pct(net_income, avg(assets_t, assets_t-1))`. Dividing by a literal `2` is
rejected on purpose: the literal has no citation, and admitting uncited literals
would open a hole big enough to drive any number through.
