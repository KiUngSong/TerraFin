---
title: Agent Docs
summary: Entry point for TerraFin's external-agent surfaces, model management, and hosted runtime docs.
---

# Agent Docs

TerraFin's agent surface has three separate jobs:

- external-agent usage through Python, CLI, and HTTP
- model/provider management for the hosted assistant
- hosted runtime architecture and maintenance

!!! note "Attribution Boundary"
    TerraFin's model-management layer borrows some UX and naming ideas from
    OpenClaw, especially canonical `provider/model` refs, the `models ...`
    command family, and the GitHub Copilot login flow. TerraFin's hosted
    runtime, financial capability kernel, session/task model, widget, and API
    wiring are TerraFin-specific unless a page says otherwise. The hosted
    runtime's orchestrator-agent-with-persona-subagents architecture also
    borrows the high-level idea of explicit analyst-role separation from
    `ai-hedge-fund`, while keeping TerraFin's shared capability kernel
    instead of per-guru Python modules. See the architecture diagrams in
    [architecture.md § Orchestrator + persona subagents](./architecture.md#orchestrator-persona-subagents)
    for the authoritative shape.

## Start Here

| Doc | Read this when... |
|-----|-------------------|
| [Usage](usage.md) | You want Python, CLI, HTTP, OpenAPI, or widget usage |
| [Model Management](models.md) | You want to inspect providers, save credentials, or switch hosted models |
| [Architecture](architecture.md) | You are designing the shared agent kernel or provider routing |
| [Hosted Runtime](hosted-runtime.md) | You are maintaining the current tool loop, sessions, tasks, and approvals |

## Quick Mental Model

TerraFin supports two agent modes:

- **External agent mode**: another system owns the model loop and calls TerraFin
- **Hosted runtime mode**: TerraFin owns the conversation loop, tools, and widget

Both modes should stay aligned with the same shared financial capability
kernel.

## Glossary

These terms appear across the docs and refer to distinct things — keep them
straight:

| Term | Meaning |
|---|---|
| **TerraFin Agent** | The hosted runtime + browser chat panel that ships with TerraFin (Mode A). Singular product surface. |
| **TerraFin Agent runtime** | The Python-side machinery that powers the Agent: capability registry, tool loop, session/task state, model routing. Lives in `src/TerraFin/agent/`. |
| **Capability** | A single agent-callable function (e.g., `valuation`, `fcf_history`, `sec_filings`). Each capability is exposed identically through Python (`TerraFinAgentClient`), CLI (`terrafin-agent`), and HTTP (`/agent/api/*`). 27 in total. |
| **Tool** | The model-facing wrapper around a Capability, with input schema validation and an LLM-readable description. Defined in `src/TerraFin/agent/tool_contracts.py` + `runtime.py`. |
| **Skill** | An Anthropic-Skills-shaped artifact (`skills/terrafin/SKILL.md`) that lets external agents like Claude Code or Codex consume TerraFin (Mode B). The agent reads SKILL.md and self-registers TerraFin's capabilities by introspecting the documented Python / CLI / HTTP surfaces — no provider-specific manifest required. Drop-in install. |
| **`TerraFinAgentClient`** | The Python client for stateless capability calls. The skill examples use it. Direct import — no server required. |
| **`terrafin-agent`** | The CLI counterpart — same capabilities, shell-friendly. Registered as a `[project.scripts]` entry. |
| **`/agent/api/*`** | The HTTP parity surface. Every Capability has a route. External HTTP-only agents and SDK consumers use this. |
| **Hosted runtime tools** | Capabilities that only make sense inside a live session (e.g., `current_view_context()` reads the user's frontend panel state; `open_chart(...)` creates a chart artifact bound to the session). Not exposed as stateless HTTP routes. |
| **Persona** | A named investing-archetype subagent (Buffett, Marks, Druckenmiller). Allowlists are defined in `src/TerraFin/agent/personas/*.yaml` and are the **single source of truth** — no hidden override layer. |
| **Orchestrator-as-tool** | The default assistant LLM consults persona subagents via `consult_<persona>` tools rather than via a regex pre-route. The persona's research memo is then synthesized back into the user-facing answer. |
| **View context** | A read-only snapshot of which panel and form-state the user is currently viewing in the dashboard. The agent reads via `current_view_context()`; **the agent cannot write back to the user's form today** (no `apply_dcf_inputs` / `set_form_state` tool exists yet). |

Hosted runtime history is now local and transcript-first:

- append-only JSONL transcript per session
- separate `sessions.json` index for history lookup
- delete archives old sessions instead of rewriting them in place
- hidden internal tool-use turns stay out of the public chat surface
- retryable tool/input failures are handled inside the loop instead of dumped straight to the user

Hosted runtime also keeps one public assistant surface:

- `TerraFin Agent` is the only default user-facing chat surface. It
  acts as the orchestrator; its own LLM decides when to call
  `consult_warren_buffett`, `consult_howard_marks`, or
  `consult_stanley_druckenmiller` tool-calls.
- hidden persona subagents run behind the scenes for research requests
  and are research-only in v1 (no position sizing, no trade execution)

## Related Docs

- [Interface Overview](../interface.md)
- [Chart Architecture](../chart-architecture.md)
- [Feature Integration](../feature-integration.md)
- [TerraFin skill on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
