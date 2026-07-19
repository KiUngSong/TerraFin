---
title: Agent Architecture
summary: Design guide for TerraFin's shared capability layer and the boundary between hosted and external agent modes.
read_when:
  - Designing the next layer of TerraFin's agent harness
  - Deciding where a new agent feature belongs
  - Reviewing how hosted and external agent modes should stay aligned
---

# Agent Architecture

This document is for maintainers.

!!! note "Attribution Boundary"
    TerraFin's provider/model registry and model-management CLI were inspired by
    OpenClaw's model-provider UX. TerraFin's transcript-first session history
    now also follows the same broad reference shape used by OpenClaw and Claude
    Code: append-only per-session transcripts plus a separate session index. The
    hidden guru-role split described below also borrows the high-level idea of
    explicit analyst role separation from `ai-hedge-fund`, while deliberately
    keeping TerraFin's shared capability layer instead of per-guru Python
    analysis modules.
    The shared financial capability layer, hosted-runtime policy layer,
    permission flow, widget integration, and view-context design described here
    are TerraFin-specific architecture.

The main rule is simple:

> Do not create an agent-only shortcut path that bypasses TerraFin's real data,
> chart, and analysis pipeline.

Hosted agents and external agents should both sit on top of the same shared capability layer.

## Core idea

TerraFin should converge on one shared **capability layer** that owns:

- capability registration
- typed inputs and outputs
- session-scoped context
- artifact creation
- task lifecycle
- policy and permission decisions

Then two controllers can sit on top:

- **Hosted runtime mode**
  TerraFin owns the model loop and tool execution.
- **External agent mode**
  Another system owns the model loop and calls TerraFin through Python, CLI, HTTP, or future MCP-like adapters.

The unification point is not the LLM loop. It is the capability layer.
The capability layer plays the role an MCP server plays for MCP clients — it
exposes one typed capability set identically to the hosted runtime and to
external agents.

## Capability-layer components

### Capability registry

Examples:

- market snapshots
- macro focus
- indicators
- company info
- earnings and financial statements
- guru portfolios
- calendar scans
- LPPL analysis
- chart opening

Rules:

- keep inputs typed
- keep outputs typed
- preserve top-level `processing`
- preserve chart/session semantics

### Session and context layer

The runtime should own session-scoped state through objects like:

- `TerraFinAgentSession`
- `TerraFinAgentContext`

Suggested responsibilities:

- current symbols or macro instruments
- chart session references
- user defaults like depth/view
- task references
- artifact references
- stable session ids across transports

Conversation history should not be treated as another mutable session blob.
Transcript history is append-only and separate from the runtime session record.

### Task layer

Use a capability when the work is immediate and returns a small result.

Use a task when:

- the work is long-running
- progress or cancellation matters
- output should become an artifact
- the result may arrive after the current turn

Likely task categories:

- multi-asset screens
- portfolio sweeps
- report synthesis
- valuation packs
- chart build workflows

### Agent definition layer

Hosted agents should come from a registry, not ad-hoc prompt blobs.

Definitions should describe:

- role name
- purpose
- allowed capabilities
- default depth and view
- chart permission
- background-task permission

Current default product path:

- `terrafin-assistant`

The registry also contains **internal guru definitions** such as Buffett,
Marks, and Druckenmiller. These are hidden research roles, not public product
surfaces.

Current product rule:

- users talk to `terrafin-assistant`
- `terrafin-assistant` is the **orchestrator**. It calls hidden guru
  subagents as tool-calls (`consult_warren_buffett`, `consult_howard_marks`,
  `consult_stanley_druckenmiller`) when its own LLM decides, per-turn,
  that an investor lens would help. See the diagrams in
  [Orchestrator + persona subagents](#orchestrator-persona-subagents).
- guru roles are not shown in the default catalog or session history
- guru roles are not creatable through the public runtime session API
- hidden guru session ids are not valid public session/task/approval handles

### Hosted loop layer

This exists only for hosted runtime mode.

Its job is to:

- run the model loop
- expose capabilities as tools
- append transcript-first messages and structured tool results to the session
- decide when to invoke a capability directly versus launch a task
- normalize transcript state before the next provider call
- compact context proactively before the provider rejects the prompt

External agents do not need TerraFin to own this layer.

### Orchestrator + persona subagents

The user-facing `terrafin-assistant` is the **orchestrator**. It has
autonomy — its own LLM decides, in-context, when to call a hidden
investor persona. The three personas (Warren Buffett, Howard Marks,
Stanley Druckenmiller) are exposed to the orchestrator as **tools**,
not as a pre-route. This is a standard agent-with-subagent pattern.

Two levels. The orchestrator runs the usual tool-call loop; the
`consult_<persona>` tool, when called, spins up a hidden persona
subagent that runs its own tool-call loop and finalises via a
structured memo.

#### Level 1 — orchestrator loop

The user prompt arrives at the orchestrator. It owns conversation
history, view-context, and tool results. The orchestrator agent
decides, per-turn, whether a persona lens would improve the answer.

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

Tools available to the orchestrator agent:

- **Research / data tools** — `sec_filings`, `sec_filing_document`,
  `sec_filing_section`, `market_snapshot`, `valuation`,
  `financials`, `earnings`, `company_info`, `macro_focus`,
  `portfolio`, `economic`, `calendar_events`, `lppl_analysis`,
  `market_breadth`, `watchlist`, `fear_greed`, `sp500_dcf`,
  `beta_estimate`, `top_companies`, `market_regime`,
  `trailing_forward_pe`, `fundamental_screen`, `risk_profile`,
  `open_chart`, `current_view_context`, `resolve`
- **Persona-consult tools** — `consult_warren_buffett`,
  `consult_howard_marks`, `consult_stanley_druckenmiller`

The orchestrator agent may ignore all three persona tools (for pure
lookup questions like "what's AAPL trading at"), call one, or call
several in parallel ("how would Buffett and Marks disagree on
this"). The decision is an agent tool-call, not a regex gate.

#### Level 2 — persona subagent loop (zoom-in on `consult_<persona>`)

When the orchestrator calls `consult_warren_buffett("is this a good
business")`, a hidden session spins up with:

- `metadata.hiddenInternal = true` (excluded from session history)
- `metadata.disableGuruRouting = true` (defensive; can't recurse)
- linked view-context inherited from the parent
- the persona's YAML persona prompt as system prompt
- a persona-specific tool set (research tools only; no nested
  `consult_*`)

```
   Orchestrator Agent calls consult_<persona>(question)
                           │
                           ▼
  ┌─────────────────────────────────────────────────┐
  │  Hidden Persona Subagent session                │
  │                                                 │
  │  new session, metadata.hiddenInternal = true,   │
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

Tools available to the persona agent inside the hidden subagent:

- **Research / data tools** — a persona-scoped subset chosen by
  `_select_guru_worker_tools` in `guru.py`. Same capability layer
  as the orchestrator, but curated per persona (Buffett skews to
  `valuation`, `financials`, `fundamental_screen`; Marks to
  `economic`, `risk_profile`, `macro_focus`; Druckenmiller to
  `macro_focus`, `market_snapshot`, `economic`). No
  `consult_<persona>` tools (recursion is blocked by construction).
- **Finalizer** — `submit_guru_research_memo`, a single-shot tool
  the persona MUST call to end its turn. The memo payload is
  validated against `GuruResearchMemo` (Pydantic). Non-memo
  free-form prose is not accepted as a finalisation.

#### `GuruResearchMemo` fields (what the orchestrator gets back)

| Field | Shape | Source |
|-------|-------|--------|
| `guru` | string | Server-stamped (persona name) |
| `stance` | `bullish` \| `bearish` \| `neutral` \| `abstain` | Persona self-reported |
| `confidence` | integer 0–100 | Persona self-reported (see note below) |
| `thesis` | short paragraph | Persona self-reported |
| `key_evidence` | list of bullets | Persona self-reported |
| `risks` | list of bullets | Persona self-reported |
| `open_questions` | list of bullets | Persona self-reported |
| `citations` | list of strings | Persona self-reported |

**Note on `confidence`**: it's a number the persona agent writes
into the memo payload. It is NOT a calculated metric. The persona's
system prompt instructs: if evidence is missing or the case is
outside the persona's style, either use `stance="abstain"` or
submit a lower-confidence partial memo. Pydantic validates the
value is an integer in `[0, 100]`; `_persona_fit_feedback` separately
validates that the memo sounds like the persona (and triggers one
in-turn retry if it doesn't) but never edits the confidence number.
Treat `confidence` as the persona's self-assessed evidence
strength, not a statistical score.

#### Invariants

- **One visible assistant.** The user only ever sees the
  orchestrator's reply. Persona sessions are never surfaced.
- **Persona can't recurse.** Consult tools are not registered for
  `hiddenInternal` sessions, so Buffett can't call
  `consult_howard_marks` which calls `consult_warren_buffett`.
- **Structured handoff only.** Personas finalise through
  `submit_guru_research_memo(...)` — never via free-form prose. The
  memo schema (`GuruResearchMemo`) is a Pydantic model so the
  orchestrator always gets typed fields, not text to re-parse.
- **View-context inheritance.** Persona sessions see the same
  linked view-context the orchestrator is reasoning over, so their
  research uses the same ticker / filing / page the user is looking
  at.
- **Loop-guard.** Calling the same persona with the same question
  three times in a turn is short-circuited (see `loop.py`
  `_tool_call_fingerprint`).

### Transport adapters

Northbound transports should stay thin:

- Python client
- CLI
- HTTP routes
- browser widget
- skill artifact
- future MCP or notebook adapters

Different transport, same semantics. That's the rule.

## Operating modes

### Hosted runtime mode

TerraFin owns:

- the model loop
- the session
- task dispatch
- artifacts
- chart/session side effects

Shape:

`User -> hosted runtime -> shared context/session -> capability layer`

### External agent mode

Another system owns:

- the model
- prompt strategy
- conversation planning

TerraFin owns:

- the same capability layer
- optional session/task semantics
- transport adapters

Shape:

`External agent -> Python/CLI/HTTP adapter -> shared context/session -> capability layer`

## Current code map

The agent package was split into sub-packages — compatibility shims at the
old top-level paths re-export the new locations so external imports keep
working, but new code should target the canonical paths below.

| Module (canonical)                                                  | Role                                                                                          | Shim at                                  |
|----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------|------------------------------------------|
| `agent/runtime/capability.py`                                        | capability registry + `build_default_capability_registry`                                     | (re-exported via `agent/runtime/__init__.py`) |
| `agent/runtime/hosted.py`                                            | hosted runtime controller and policy layer                                                    | `agent/hosted_runtime.py`                |
| `agent/runtime/loop.py`                                              | provider-agnostic hosted loop and transcript append flow                                      | `agent/loop.py`                          |
| `agent/runtime/context.py`, `session.py`, `tasks.py`, `artifacts.py` | session context, task registry, artifact tracking                                             | —                                        |
| `agent/runtime/transcript_normalizer.py`, `context_budget.py`, `recovery.py` | normalization, prompt-budget estimation, per-turn recovery                            | —                                        |
| `agent/contracts/tool_contracts.py`                                  | LLM-facing tool input schemas                                                                 | `agent/tool_contracts.py`                |
| `agent/contracts/definitions.py`                                     | hosted agent definition registry                                                              | `agent/definitions.py`                   |
| `agent/contracts/conversation.py`, `conversation_state.py`           | message/block protocol + conversation dataclasses                                             | `agent/conversation.py`, `conversation_state.py` |
| `agent/service/service.py`                                           | capability implementation layer (`TerraFinAgentService`)                                      | —                                        |
| `agent/service/hosted.py`                                            | hosted-service wiring                                                                         | `agent/hosted_service.py`                |
| `agent/service/client.py`                                            | Python transport adapter (`TerraFinAgentClient`)                                              | `agent/client.py`                        |
| `agent/service/client_helpers.py`                                    | helpers used by client + CLI                                                                  | `agent/runtime_helpers.py`               |
| `agent/storage/transcript_store.py`                                  | append-only transcript store + `sessions.json` index                                          | `agent/transcript_store.py`              |
| `agent/storage/session_store.py`                                     | non-transcript hosted state: tasks, approvals, audit, view context                            | `agent/session_store.py`                 |
| `agent/models/management.py`                                         | saved model/auth state + CLI-facing provider catalog (`list_provider_catalog`)                | `agent/model_management.py`              |
| `agent/models/runtime.py`                                            | provider registry, runtime-model binding, canonical `provider/model` refs                     | `agent/model_runtime.py`                 |
| `agent/models/providers/*.py`                                        | provider adapters for OpenAI, Gemini, GitHub Copilot                                          | `agent/providers/*.py`                   |
| `agent/tools/adapter.py`, `execution.py`, `normalize.py`             | hosted tool adapter + structured tool execution outcomes                                      | `agent/tools.py`, `tool_execution.py`    |
| `agent/guru/worker.py`                                               | hidden persona subagent runner, persona prompts, `_select_guru_worker_tools`                  | (re-exported via `agent/guru/__init__.py`) |
| `agent/guru/memo.py`, `consult.py`, `feedback.py`                    | `GuruResearchMemo` schema, `consult_<persona>` glue, persona-fit feedback                     | —                                        |
| `agent/guru/personas/*.yaml`                                         | persona YAMLs (Buffett / Marks / Druckenmiller) — single source of truth for allowlists       | `agent/personas/` (re-export shim)       |
| `agent/cli/main.py`                                                  | CLI adapter (`terrafin-agent`)                                                                | (none — `agent/cli/` package replaces the old `agent/cli.py` module) |
| `interface/agent/data_routes.py`                                     | HTTP adapter                                                                                  | —                                        |
| `interface/frontend/src/agent/GlobalAgentWidget.tsx`                 | browser widget over the hosted runtime                                                        | —                                        |

## Guardrails

- Do not fork financial logic away from the product path.
- Do not make hosted-only capabilities that external agents cannot also reach.
- Do not let HTTP, CLI, and Python semantics drift away from the same capability layer.
- Do not treat chart-opening as a toy path if agents can create chart artifacts.
- Do not overbuild remote or multi-agent orchestration before local capability-layer semantics are solid.
- Do not expose hidden guru roles as a product picker unless the product
  direction explicitly changes.
- Do not let internal guru orchestration depend on regex recovery from prose;
  the internal handoff must stay structured.
- Do not reintroduce a pre-intercept regex router in front of the main
  assistant — the orchestrator's own LLM decides when to consult a
  persona via `consult_<persona>` tool-calls.

## Read next

- [hosted-runtime.md](./hosted-runtime.md)
- [usage.md](./usage.md)
- [../feature-integration.md](../feature-integration.md)
- [../chart-architecture.md](../chart-architecture.md)
