---
title: Agent Docs and Glossary
summary: Start-here map and glossary shared by TerraFin's skill layer and agent harness.
---

# Agent Docs and Glossary

Package paths on this page drop the leading `src/TerraFin/`: `data/` means `src/TerraFin/data/`.

There are two ways to put an agent on TerraFin. Both read one capability
registry (`agent/runtime/capability.py`):

- **[Skills](../skills/index.md)**: your own agent (Claude Code, Codex,
  opencode, or anything that speaks HTTP) keeps its model and loop, and calls
  TerraFin through SKILL.md, HTTP `/agent/api/*`, the `terrafin-agent` CLI, or
  the Python `TerraFinAgentClient`.
- **[Agent Harness](../harness/index.md)**: TerraFin's own agent. TerraFin
  owns the conversation loop, the tools, and the chat panel on every page. See
  [The Agent Loop](../harness/loop.md) for one turn step by step.

This page keeps the start-here map and the terms both share.

!!! note "Attribution"
    The model-management layer borrows UX and naming ideas from OpenClaw,
    such as `provider/model` refs and the `models ...` command family. The
    rest is TerraFin's own unless a page says otherwise.

## Start Here

| Doc | Read this when... |
|-----|-------------------|
| [For External Agents](external-agents.md) | Your own agent is calling TerraFin: install, base URL, discovery, finding a series by name |
| [Usage](usage.md) | You want Python, CLI, HTTP, OpenAPI, or widget usage |
| [Model Management](models.md) | You want to inspect providers, save credentials, or switch models for TerraFin's own agent |
| [Architecture](architecture.md) | You are designing the shared capability layer or provider routing |
| [Hosted Runtime](hosted-runtime.md) | You are maintaining the tool loop, sessions, tasks, and approvals |

## Glossary

| Term | Meaning |
|---|---|
| **TerraFin Agent** | TerraFin's own agent: the hosted runtime plus the chat panel in the dashboard. |
| **Hosted runtime** | The Python side of the TerraFin Agent: tool loop, sessions, tasks, model routing. Lives in `agent/`. |
| **Capability** | One agent-callable function, such as `valuation` or `sec_filings`. `terrafin-agent capabilities` prints the live set. |
| **Tool** | The model-facing wrapper around a capability: an input schema and a description the model reads. |
| **Skill** | `skills/terrafin/SKILL.md`, the file that lets Claude Code, Codex, or opencode use TerraFin. The host loads it and calls the documented Python, CLI, or HTTP surfaces. |
| **`TerraFinAgentClient`** | The Python client for stateless capability calls. No server needed. |
| **`terrafin-agent`** | The CLI counterpart, for agents that work through a shell. |
| **`/agent/api/*`** | The HTTP surface. Nearly every capability has a route. `curl $TF/openapi.json` lists them. |
| **Hosted runtime tools** | Tools that only make sense inside a live session, such as `current_view_context()` and `open_chart(...)`. They have no stateless HTTP route. |
| **Persona** | An investing-archetype subagent (Buffett, Marks, Druckenmiller). Each persona's allowed capabilities are set in its YAML under `agent/guru/personas/`. |
| **Orchestrator-as-tool** | The TerraFin Agent consults personas through `consult_<persona>` tools, then folds each persona's memo into its answer. |
| **View context** | A read-only snapshot of the panel and form state the user is viewing. The agent reads it with `current_view_context()`. It cannot write back to the form. |

The TerraFin Agent is the only chat surface users see. Persona subagents run
hidden behind it and are research-only: no position sizing, no trades.

## Related Docs

- [Interface Overview](../interface.md)
- [Chart Architecture](../chart-architecture.md)
- [Feature Integration](../feature-integration.md)
- [TerraFin skill on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
