---
title: Agent Architecture
summary: Design guide for TerraFin's shared agent kernel and the boundary between hosted and external agent modes.
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
    keeping TerraFin's shared capability kernel instead of per-guru Python
    analysis modules.
    The shared financial capability kernel, hosted-runtime policy layer,
    permission flow, widget integration, and view-context design described here
    are TerraFin-specific architecture.

The main rule is simple:

> Do not create an agent-only shortcut path that bypasses TerraFin's real data,
> chart, and analysis pipeline.

Hosted agents and external agents should both sit on top of the same shared kernel.

## Core idea

TerraFin should converge on one shared **agent kernel** that owns:

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

The unification point is not the LLM loop. It is the kernel.

## Shared kernel layers

### Capability layer

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
- `terrafin-assistant` may route to hidden guru roles when policy says the
  request benefits from those lenses
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

### Main-orchestrator router layer

The main hosted assistant now owns a **policy-first router** for investor
personas.

Rules:

- inspect the user request
- inspect current TerraFin view context
- decide whether to stay in general TerraFin mode or invoke hidden guru roles
- synthesize the resulting research back into one user-facing answer
- require each hidden guru role to finish via a structured memo handoff, not
  free-form prose parsing

This is intentionally not an LLM-first “let the model decide everything”
approach. Routing is deterministic and cost-bounded.

Current default role mapping:

- portfolio / holdings / business-quality interpretation -> Buffett first,
  optionally Marks
- macro / regime / liquidity / top-down setup -> Druckenmiller first,
  optionally Marks
- valuation / downside / DCF review / cycle framing -> Marks first,
  optionally Buffett

The user still sees one assistant.

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

`User -> hosted runtime -> shared context/session -> capability/task kernel`

### External agent mode

Another system owns:

- the model
- prompt strategy
- conversation planning

TerraFin owns:

- the same capability kernel
- optional session/task semantics
- transport adapters

Shape:

`External agent -> Python/CLI/HTTP adapter -> shared context/session -> capability/task kernel`

## Current code map

| File | Role |
|------|------|
| `src/TerraFin/agent/runtime.py` | shared kernel primitives |
| `src/TerraFin/agent/service.py` | capability implementation layer |
| `src/TerraFin/agent/definitions.py` | hosted agent definition registry |
| `src/TerraFin/agent/guru.py` | policy-first guru router, structured research memos, and hidden-role synthesis |
| `src/TerraFin/agent/hosted_runtime.py` | hosted runtime controller and policy layer |
| `src/TerraFin/agent/transcript_store.py` | append-only transcript store and session index |
| `src/TerraFin/agent/session_store.py` | non-transcript hosted state, approvals, tasks, audit, and view context |
| `src/TerraFin/agent/model_runtime.py` | provider registry, canonical model refs, and runtime model binding |
| `src/TerraFin/agent/model_management.py` | saved model/auth state and CLI-facing provider catalog |
| `src/TerraFin/agent/providers/*.py` | provider adapters for OpenAI, Gemini, and GitHub Copilot |
| `src/TerraFin/agent/tools.py` | hosted tool adapter |
| `src/TerraFin/agent/loop.py` | provider-agnostic hosted loop and transcript append flow |
| `src/TerraFin/agent/openai_model.py` | compatibility re-export for the OpenAI provider module |
| `src/TerraFin/interface/agent/data_routes.py` | HTTP adapter |
| `src/TerraFin/interface/frontend/src/agent/GlobalAgentWidget.tsx` | browser widget over the hosted runtime |

## Guardrails

- Do not fork financial logic away from the product path.
- Do not make hosted-only capabilities that external agents cannot also reach.
- Do not let HTTP, CLI, and Python semantics drift away from the same kernel.
- Do not treat chart-opening as a toy path if agents can create chart artifacts.
- Do not overbuild remote or multi-agent orchestration before local kernel semantics are solid.
- Do not expose hidden guru roles as a product picker unless the product
  direction explicitly changes.
- Do not let internal guru orchestration depend on regex recovery from prose;
  the internal handoff must stay structured.

## Read next

- [hosted-runtime.md](./hosted-runtime.md)
- [usage.md](./usage.md)
- [../feature-integration.md](../feature-integration.md)
- [../chart-architecture.md](../chart-architecture.md)
