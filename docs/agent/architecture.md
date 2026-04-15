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
    Code: append-only per-session transcripts plus a separate session index.
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

The registry still exists so TerraFin can define narrower hosted agents for
tests, future deployments, or specialized operator workflows without changing
the runtime architecture.

### Hosted loop layer

This exists only for hosted runtime mode.

Its job is to:

- run the model loop
- expose capabilities as tools
- append messages and tool results to the session
- decide when to invoke a capability directly versus launch a task

External agents do not need TerraFin to own this layer.

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

## Read next

- [hosted-runtime.md](./hosted-runtime.md)
- [usage.md](./usage.md)
- [../feature-integration.md](../feature-integration.md)
- [../chart-architecture.md](../chart-architecture.md)
