---
title: Agent Docs
summary: Entry point for TerraFin's agent usage, architecture, and hosted runtime documentation.
read_when:
  - You are not sure which agent document to read first
  - You want a quick map of TerraFin's agent surfaces
  - You need to distinguish external-agent usage from hosted runtime maintenance
---

# Agent Docs

TerraFin's agent surface now spans three separate concerns:

- how to use the agent-facing APIs and helpers
- how the shared kernel is supposed to be structured
- what the current hosted runtime actually looks like in code

Keeping those in one file made the docs noisy. This folder splits them by job.

## Start here

| Doc | Read this when... |
|-----|-------------------|
| [usage.md](./usage.md) | You want to use TerraFin from Python, CLI, HTTP, OpenAPI, or the hosted assistant widget |
| [models.md](./models.md) | You want to inspect providers, save credentials, or switch the hosted runtime model from the CLI |
| [architecture.md](./architecture.md) | You are designing the shared kernel and deciding how hosted and external agent modes should fit together |
| [hosted-runtime.md](./hosted-runtime.md) | You are maintaining the current hosted runtime, tool loop, adapters, widget, or regression coverage |

## Quick mental model

TerraFin supports two agent modes:

- **External agent mode**
  Another system owns the model loop and calls TerraFin through Python, CLI, or HTTP.
- **Hosted runtime mode**
  TerraFin owns the conversation loop, tool execution, and browser/notebook chat surface.

Both should stay aligned with the same shared financial capability kernel.

Hosted runtime history is local and transcript-first:

- append-only JSONL transcript per session
- separate `sessions.json` index for history lookup
- delete archives old sessions instead of rewriting them in place

## Related docs

- [../interface.md](../interface.md)
- [../chart-architecture.md](../chart-architecture.md)
- [../feature-integration.md](../feature-integration.md)
- [TerraFin skill on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
