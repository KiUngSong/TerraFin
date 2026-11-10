---
title: Agent Architecture
summary: Design guide for TerraFin's shared capability layer and the boundary between TerraFin's own agent and external agents.
read_when:
  - Designing the next layer of TerraFin's agent harness
  - Deciding where a new agent feature belongs
  - Reviewing how TerraFin's own agent and external agents stay aligned
---

# Agent Architecture

This document is for maintainers.

TerraFin can be used by an agent in two ways:

- **TerraFin's own agent (hosted runtime).** TerraFin runs the model loop
  itself and serves it in the browser panel and over `/agent/api/*`.
- **TerraFin's skills from your own agent (external agent).** Another agent,
  such as Claude Code or Codex, owns the model loop and calls TerraFin through
  Python, the CLI, or HTTP.

The main rule is simple:

> Do not create an agent-only shortcut path that bypasses TerraFin's real data,
> chart, and analysis pipeline.

Both ways sit on top of the same shared capability layer.

!!! note "Attribution"
    - The provider/model registry and model-management CLI were inspired by
      OpenClaw's model-provider UX.
    - Session history follows the shape used by OpenClaw and Claude Code:
      append-only per-session transcripts plus a separate session index.
    - The capability layer, persona sub-agents, policy layer, permission flow,
      widget integration, and view-context design are TerraFin's own.

## Core idea

One shared **capability layer** owns:

- capability registration
- typed inputs and outputs
- session-scoped context
- artifact creation
- task lifecycle
- policy and permission decisions

Two controllers sit on top:

- **Hosted runtime.** TerraFin owns the model loop and tool execution.
- **External agent.** Another system owns the model loop and calls TerraFin
  through Python, CLI, or HTTP adapters.

The unification point is the capability layer, not the LLM loop. The
capability layer plays the role an MCP server plays for MCP clients: one typed
capability set, exposed the same way to both controllers.

## Capability-layer components

### Capability registry

Each capability (market snapshots, company info, filings, valuation, chart
opening, and so on) is registered once in `agent/runtime/capability.py`. The
live list comes from `terrafin-agent capabilities`, not from this page.

Rules:

- keep inputs typed
- keep outputs typed
- preserve top-level `processing`
- preserve chart/session semantics

### Session and context layer

The runtime owns session-scoped state through `TerraFinAgentSession` and
`TerraFinAgentContext`:

- current symbols
- chart session references
- user defaults like depth and view
- task and artifact references
- session ids that stay stable across transports

Conversation history is not another mutable session blob. Transcripts are
append-only and stored apart from the runtime session record.

### Task layer

Use a capability when the work is immediate and returns a small result.

Use a task when:

- the work is long-running
- progress or cancellation matters
- output should become an artifact
- the result may arrive after the current turn

### Agent definition layer

Hosted agents come from a registry (`agent/contracts/definitions.py`), not
ad-hoc prompt blobs. A definition names:

- the role and its purpose
- the capabilities it may use
- default depth and view
- whether it may open charts or run background tasks

Users talk to one agent, `terrafin-assistant`. The registry also holds hidden
guru roles (Buffett, Marks, Druckenmiller). These are internal research roles:

- they are not shown in the default catalog or session history
- they cannot be created through the public session API
- their session ids are not valid public session, task, or approval handles

### Hosted loop layer

This layer exists only for the hosted runtime. It:

- runs the model loop
- exposes capabilities as tools
- appends messages and structured tool results to the transcript
- chooses between a direct call and a task
- normalizes the transcript before each provider call
- compacts context before the provider rejects the prompt

External agents do not need TerraFin to own this layer.

### Orchestrator + persona subagents

`terrafin-assistant` is the **orchestrator**.

- Its own LLM decides, each turn, whether an investor lens would help.
- The three personas are exposed to it as tools (`consult_warren_buffett`,
  `consult_howard_marks`, `consult_stanley_druckenmiller`), not as a
  pre-route.

#### Level 1: orchestrator loop

The orchestrator holds the conversation, the view context, and tool results.
Each turn it either replies or calls a tool.

```
            ┌─────────────────┐
            │   User Prompt   │
            └────────┬────────┘
                     │
                     ▼
    ┌──────────────────────────────────────────┐
    │     TerraFin Orchestrator Agent          │
    │                                          │
    │  holds: conversation history,            │
    │         view-context,                    │
    │         tool observations so far         │
    │                                          │
    │  thinks & decides each turn:             │
    │    - reply directly, or                  │
    │    - call a tool                         │
    └──────────┬──────────────────┬────────────┘
               │                  │
       Response│                  │ Tool Use
               │                  │
               ▼                  ▼
       ┌────────────────┐   ┌────────────────┐
       │   Final User   │   │  Execute Tool  │
       │    Response    │   │                │
       └────────────────┘   └────────┬───────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │  Tool Result /  │
                            │   Observation   │
                            └────────┬────────┘
                                     │
                                     └──▶ back into Orchestrator
                                          (next turn)
```

Its tools are the research and data capabilities plus the three
`consult_<persona>` tools. It may call:

- no persona, for a lookup like "what's AAPL trading at"
- one persona
- several in parallel, as in "how would Buffett and Marks disagree on this"

#### Level 2: persona subagent loop

A `consult_<persona>` call starts a hidden session. The session:

- inherits the parent's view context
- loads the persona's YAML prompt as its system prompt
- is excluded from session history

```
   Orchestrator Agent calls consult_<persona>(question)
                           │
                           ▼
  ┌─────────────────────────────────────────────────┐
  │  Hidden Persona Subagent session                │
  │                                                 │
  │  new hidden session,                            │
  │  persona YAML loaded as system prompt,          │
  │  linked view-context inherited from parent      │
  └────────────────────────┬────────────────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │     Persona Agent       │◀──────────┐
              │  (Buffett / Marks /     │           │
              │   Druckenmiller)        │           │
              │  thinks in its voice    │           │
              └──────┬───────────┬──────┘           │
                     │           │                  │
             Research│           │Finalize          │
             Tool Use│           │Tool Use          │
                     ▼           ▼                  │
         ┌─────────────────┐   ┌────────────────┐   │
         │  Execute        │   │ submit_guru_   │   │
         │  research tool  │   │ research_memo  │   │
         │                 │   │  (finalizer)   │   │
         └────────┬────────┘   └───────┬────────┘   │
                  │                    │            │
                  ▼                    │            │
         ┌─────────────────┐           │            │
         │  Tool Result /  │───────────┼────────────┘
         │   Observation   │           │  (next turn)
         └─────────────────┘           │
                                       ▼
                          ┌────────────────────────┐
                          │   GuruResearchMemo     │
                          │   (structured JSON)    │
                          └───────────┬────────────┘
                                      │
                                      ▼
                    returned as tool_result to the
                    Orchestrator Agent (Level 1)
```

The persona's tools:

- **Research tools.** The allowlist is `allowed_capabilities` in the persona's
  YAML under `agent/guru/personas/`. To change a persona's tools, edit its
  YAML.
- **Finalizer.** The persona must end by calling `submit_guru_research_memo`.
  The payload is validated against `GuruResearchMemo` (`agent/guru/memo.py`):
  stance, confidence, thesis, evidence, risks, open questions, and citations.

`confidence` is a number the persona writes, not a calculated metric.

- Treat `confidence` as the persona's own view of its evidence strength.
- The memo schema lowers `confidence` when a high-confidence memo cites
  nothing, and appends a note to the thesis saying why.
- A separate persona-fit check can ask the persona to revise a memo that does
  not sound like it.

#### Invariants

- **One visible assistant.** The user only sees the orchestrator's reply.
  Persona sessions are never surfaced.
- **Personas cannot recurse.** Hidden persona sessions do not get
  `consult_*` tools.
- **Structured handoff only.** Personas finish through the memo tool, never
  through free-form prose, so the orchestrator gets typed fields.
- **Shared view context.** Personas see the same ticker, filing, or page the
  user is looking at.
- **Loop guard.** The hosted loop short-circuits a tool call repeated with
  the same arguments within a turn.

### Transport adapters

Transports stay thin: Python client, CLI, HTTP routes, browser widget, and the
skill file. Different transport, same semantics.

## Operating modes

TerraFin's own agent:

`User -> hosted runtime -> shared context/session -> capability layer`

TerraFin owns the model loop, the session, task dispatch, artifacts, and chart
side effects.

TerraFin's skills from your own agent:

`External agent -> Python/CLI/HTTP adapter -> shared context/session -> capability layer`

The other system owns the model, prompt strategy, and planning. TerraFin
owns the same capability layer, optional session and task semantics, and the
adapters.

## Current code map

Paths are under `src/TerraFin/`. New code should import from these packages.

| Module | Role |
|--------|------|
| `agent/runtime/` | capability registry, hosted runtime and policy, hosted loop, session, context, tasks, artifacts |
| `agent/contracts/` | tool input schemas, agent definitions, conversation protocol |
| `agent/service/` | capability implementations (`TerraFinAgentService`) and the Python client (`TerraFinAgentClient`) |
| `agent/storage/` | append-only transcript store and session index, plus tasks, approvals, audit, and view context |
| `agent/models/` | saved model and auth state, provider registry, provider adapters |
| `agent/tools/` | hosted tool adapter and tool execution |
| `agent/guru/` | persona subagent runner, memo schema, consult tools, persona YAMLs |
| `agent/deepresearch/` | the [deep research](deep-research.md) agent loop and its document reader, on by default (`TERRAFIN_AGENT_DEEPRESEARCH_ENABLED=0` turns it off) |
| `agent/cli/` | `terrafin-agent` CLI |
| `interface/agent/data_routes.py` | HTTP adapter |
| `interface/frontend/src/agent/GlobalAgentWidget.tsx` | browser widget |

## Guardrails

- Do not fork financial logic away from the product path.
- Keep every financial capability reachable by external agents. Only tools
  that need a live hosted session are hosted-only: the `consult_<persona>`
  tools, `current_view_context`, `open_chart`, `read_tool_result`, `ask_user`,
  and `deep_research`, which runs only as a background task.
- Do not let HTTP, CLI, and Python semantics drift away from the same capability layer.
- Do not treat chart-opening as a toy path if agents can create chart artifacts.
- Do not overbuild remote or multi-agent orchestration before local capability-layer semantics are solid.
- Do not expose hidden guru roles as a product picker unless the product
  direction explicitly changes.
- Keep the guru handoff structured. Do not recover it from prose with regex.
- Do not put a regex router in front of the main assistant. The
  orchestrator's own LLM decides when to consult a persona.

## Read next

- [hosted-runtime.md](hosted-runtime.md)
- [usage.md](../skills/usage.md)
- [../feature-integration.md](../reference/feature-integration.md)
- [../chart-architecture.md](../reference/chart-architecture.md)
