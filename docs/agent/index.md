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
    wiring are TerraFin-specific unless a page says otherwise.

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

Hosted runtime history is now local and transcript-first:

- append-only JSONL transcript per session
- separate `sessions.json` index for history lookup
- delete archives old sessions instead of rewriting them in place

## Related Docs

- [Interface Overview](../interface.md)
- [Chart Architecture](../chart-architecture.md)
- [Feature Integration](../feature-integration.md)
- [TerraFin skill on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
