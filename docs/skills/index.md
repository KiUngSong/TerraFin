---
title: Skills
summary: What TerraFin's skill layer is, how to install it, and how to find what it can do.
---

# Skills

TerraFin's skills are financial research tools your own agent calls. Your
agent keeps its model and its loop. TerraFin supplies the data, the models,
and the sources.

## Install

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin
pip install -e .           # the Python client, the CLI and the server
./setup                    # every host found on PATH
./setup --host claude      # or codex, opencode
```

`./setup` symlinks `skills/terrafin` into each host's skill directory. Because
it is a symlink, `git pull` upgrades every host at once. Inside a checkout,
do not copy the directory: a copy stops tracking the code it documents. On a
machine with no checkout, copy the whole `skills/terrafin/` directory.

## Surfaces

Every capability is registered once, in the capability registry
(`src/TerraFin/agent/runtime/capability.py`). The surfaces below are
views of that registry. Each surface names a capability its own way: the CLI
uses subcommands and HTTP uses kebab-case paths (`market_snapshot` is
`terrafin-agent snapshot` and `/agent/api/market-snapshot`).
`terrafin-agent capabilities` shows each capability's CLI and HTTP name.

| Surface | What it is | Use it when |
|---|---|---|
| [`skills/terrafin/SKILL.md`](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md) | The skill file your host loads. Task recipes live beside it in `references/`. | Your agent is Claude Code, Codex, or opencode. |
| HTTP `/agent/api/*` | Routes on a running TerraFin server. The widest surface. | Your agent speaks HTTP, or runs outside the TerraFin venv. |
| `terrafin-agent` CLI | A shell command installed with the package. | Your agent works through a shell. |
| Python `TerraFinAgentClient` | `from TerraFin.agent import TerraFinAgentClient`. | Your agent runs Python in the TerraFin venv. |

The CLI and the Python client expose a smaller subset than HTTP. Check before
you assume a method exists.

`scripts/generate-agent-artefacts.py` regenerates the capability list in
SKILL.md and the route summary in [Usage](../agent/usage.md) from the
registry, so those lists follow the code.

## Find what exists

```bash
terrafin-agent capabilities                    # the live set as JSON
terrafin-agent capabilities --name valuation   # one capability
curl -s $TF/openapi.json                       # every HTTP route and its schema
```

`terrafin-agent capabilities` reads the registry without starting a server.
`/openapi.json` is the authority on which HTTP routes exist. See
[For External Agents](../agent/external-agents.md) for how to set `$TF`.

The [route summary](../agent/usage.md#route-summary) lists every capability with a route, grouped by kind.

## Next

- [For External Agents](../agent/external-agents.md): base URL, discovery,
  finding a series by name.
- [Usage](../agent/usage.md): request policy and the route summary.
- [API Reference](../api-reference.md): per-route docs.
- [Agent Harness](../harness/index.md): TerraFin's own agent, built on these
  same skills.
