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
    controller, financial capability kernel, task/approval flow, widget, and API
    integration remain TerraFin-specific. The hidden guru-router pattern also
    takes inspiration from the role-separation style in `ai-hedge-fund`, but
    TerraFin keeps shared capabilities and prompt-level persona policy instead
    of hardcoded per-guru analysis modules.

## Current runtime shape

Today the hosted runtime has:

- a shared financial capability kernel
- a hosted agent definition registry
- a policy-enforcing runtime controller
- a hosted tool adapter
- a provider-agnostic hosted loop
- a provider registry with OpenAI, Gemini, and GitHub Copilot adapters
- Python, CLI, HTTP, notebook, and browser widget adapters
- transcript-first local session history
- a main-orchestrator router for hidden guru research roles
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

| File | What it owns |
|------|---------------|
| `src/TerraFin/agent/runtime.py` | capability registry, session context, task registry, artifact tracking |
| `src/TerraFin/agent/definitions.py` | hosted agent definitions and allowlists |
| `src/TerraFin/agent/hosted_runtime.py` | session lifecycle, policy enforcement, task dispatch, transcript-aware session access |
| `src/TerraFin/agent/loop.py` | hosted loop, immediate message append flow, provider state persistence |
| `src/TerraFin/agent/conversation.py` | internal message/block protocol and conversation dataclasses |
| `src/TerraFin/agent/guru.py` | route planning, hidden guru execution, and structured memo synthesis |
| `src/TerraFin/agent/tool_execution.py` | structured tool execution outcomes and tool-result message creation |
| `src/TerraFin/agent/transcript_normalizer.py` | transcript repair, tool-use/tool-result pairing, internal/public view split |
| `src/TerraFin/agent/context_budget.py` | proactive prompt-budget estimation and compaction levels |
| `src/TerraFin/agent/recovery.py` | per-turn recovery budget / repeated-error policy |
| `src/TerraFin/agent/transcript_store.py` | append-only transcript store, `sessions.json` index, transcript readers, archive/rewrite helpers |
| `src/TerraFin/agent/session_store.py` | non-transcript hosted state: tasks, approvals, audit, view context, transient conversation attachment |
| `src/TerraFin/agent/model_runtime.py` | provider registry, runtime-model binding, canonical `provider/model` refs |
| `src/TerraFin/agent/providers/*.py` | provider adapters for OpenAI, Gemini, and GitHub Copilot |
| `src/TerraFin/agent/tools.py` | function-callable tool definitions and tool execution bridge |
| `src/TerraFin/agent/client.py` | Python transport adapter |
| `src/TerraFin/agent/cli.py` | CLI adapter |
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
- policy-first hidden guru routing from the main assistant
- structured internal guru memos for orchestrator synthesis through an internal
  memo tool-call contract, not JSON scraped from prose
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
- semantic parity across Python, CLI, and HTTP
- widget integration over `/agent/api/runtime/*`

Current tests:

- `tests/agent/test_runtime.py`
- `tests/agent/test_hosted_runtime.py`
- `tests/agent/test_tools.py`
- `tests/agent/test_loop.py`
- `tests/agent/test_transcript_store.py`
- `tests/agent/test_openai_model.py`
- `tests/agent/test_google_provider.py`
- `tests/agent/test_github_copilot_provider.py`
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
  tests/agent/test_github_copilot_provider.py \
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
