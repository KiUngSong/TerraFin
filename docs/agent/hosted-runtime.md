---
title: Hosted Runtime
summary: Maintainer guide to TerraFin's own agent runtime, its session storage, and where its parts live.
read_when:
  - Maintaining the hosted agent loop
  - Changing runtime endpoints, transcript storage, tool adapters, or the browser widget
---

# Hosted Runtime

The hosted runtime is TerraFin's own agent: the assistant in the browser
widget, also reachable from Python, the CLI, notebooks, and HTTP. The other way
to use TerraFin, calling its skills from your own agent, does not run this
code. See [usage.md](./usage.md) for that path.

This page is the maintainer companion to [architecture.md](./architecture.md).
It says what the runtime is made of and where each part lives.

!!! note "Reference Boundary"
    Session persistence follows the shape used by OpenClaw and Claude Code:
    append-only per-session transcripts with a separate session index. The
    runtime controller, persona sub-agents, capability layer, task and
    approval flow, widget, and API are TerraFin's own.

## Parts

- a shared financial capability layer
- a registry of hosted agent definitions
- a runtime controller that enforces each agent's capability allowlist
- a tool adapter that turns capabilities into model tools
- a provider-agnostic loop, with OpenAI and Gemini providers
- Python, CLI, HTTP, notebook, and browser widget adapters over one runtime
- hidden persona subagents (Buffett, Marks, Druckenmiller) that the main agent
  reaches through `consult_<persona>` tool calls; see
  [architecture.md](./architecture.md#orchestrator-persona-subagents)
- transcript repair before each model call, and prompt compaction when the
  context budget runs short

## Session storage

Local hosted state has two layers:

- transcript JSONL files: the source of truth for message history
- a session index JSON: summary metadata for list, history, and delete

```text
.terrafin/agent/sessions/sessions.json
.terrafin/agent/sessions/<session-id>.jsonl
```

Transcripts are append-only. The first line is a `session_header` event, and
each message is a `message` event. Messages carry internal blocks (hidden tool
calls, tool results, retryable tool errors) beside the public `role/content`
shape, so a session can be replayed in full without showing internal turns to
the widget or the public session APIs.

`session_header` carries `agentName`, plus `origin` and `parentSessionId` when
the creator set them in session metadata:

| `origin` | Who created the session |
|---|---|
| `dashboard` | a person typing in the browser widget |
| `pipeline` | a batch stage calling the agent as an LLM |
| `guru` | a hidden worker spawned by a turn; also carries `parentSessionId` |

An absent `origin` means unknown. `parentSessionId` is what ties a turn and its
hidden workers into one tree.

Behavior that callers rely on:

- session list and history are read from transcripts
- reopening a session rebuilds the conversation from its transcript
- deleting a session archives the transcript under a `.deleted.` name and drops
  it from history
- hidden guru sessions are left out of public history and refused by the public
  read, delete, task, and approval routes
- deleting a public session also deletes its hidden guru children

Tasks, approvals, audit, and view context live in the session store, not in
transcripts.

## Where things live

| Path under `src/TerraFin/` | What it owns |
|------|---------------|
| `agent/runtime/capability.py` | capability registry, session context, tasks, artifacts |
| `agent/contracts/definitions.py` | hosted agent definitions and allowlists |
| `agent/runtime/hosted.py` | session lifecycle, policy enforcement, task dispatch |
| `agent/runtime/loop.py` | the hosted loop |
| `agent/contracts/conversation.py` | internal message and block protocol |
| `agent/guru/` | persona routing, hidden guru runs, memo synthesis |
| `agent/tools/` | tool definitions, tool execution, tool results |
| `agent/runtime/transcript_normalizer.py` | transcript repair and the internal/public split |
| `agent/runtime/context_budget.py` | prompt budget and compaction |
| `agent/runtime/recovery.py` | per-turn recovery policy |
| `agent/storage/transcript_store.py` | transcripts and the session index |
| `agent/storage/session_store.py` | tasks, approvals, audit, view context |
| `agent/models/` | provider registry and provider adapters |
| `agent/service/client.py` | Python client (`TerraFinAgentClient`) |
| `agent/cli/` | CLI (`terrafin-agent`) |
| `interface/agent/data_routes.py` | HTTP endpoints |
| `interface/frontend/src/agent/GlobalAgentWidget.tsx` | the browser widget |

## Endpoints

Runtime endpoints live under `/agent/api/runtime/*`: agents, sessions and their
messages, tasks, approvals, and view contexts. The route list is in
[api-reference.md](../api-reference.md), and `/openapi.json` on a running server
is the authority.

The widget, notebook helpers, CLI, and Python client all use this one contract.
Only public agents appear in the agent catalog, and the session-create route
refuses hidden guru agents.

The browser UI is a floating widget mounted across the main pages. It calls the
same endpoints as every other adapter.

## Errors and recovery

- retryable tool and input failures stay inside the loop as structured tool-error results
- fatal provider failures (auth, quota, upstream) are what reaches the user
- transcripts are repaired before each provider call, so an orphaned tool result does not leak into the next turn
- the prompt is compacted before a provider call when it is over budget, with reactive retries as a last resort

The transcript itself is never compacted. Compaction applies to the prompt
built from it.

## Background tasks

A capability marked backgroundable can also be offered to the model as
`start_<capability>_task`. The model starts the task and keeps talking. The
task runs on a worker under a lease, and a long run renews its lease when it
reports progress. Callers read task state through the task routes.

## Regression surfaces

When you change runtime code, check these first:

- transcript append order for `user -> assistant/tool -> assistant`
- session reopen and history summaries built from transcript and index
- session delete and archive
- response parsing for each provider
- that a capability means the same thing on every surface that exposes it:
  HTTP reaches nearly all of them, the Python client and CLI a smaller subset
  under the same names and arguments
- the widget over `/agent/api/runtime/*`

Tests live in `tests/agent/` and `tests/interface/test_agent_api.py`. Run the
frontend build with `npm run build`.

## Read next

- [usage.md](./usage.md)
- [architecture.md](./architecture.md)
- [../interface.md](../interface.md)
