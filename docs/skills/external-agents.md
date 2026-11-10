# TerraFin for External Agents

This page is for agents that run their own model loop and want TerraFin as a
data and analysis backend:

- Such agents include Claude Code, Codex, opencode, or anything that speaks HTTP.
- Your agent keeps its model.
- TerraFin answers its calls.
- Nothing here needs a model provider, an API key, or a chat session.

If you want TerraFin to run the conversation itself, with its own model and
chat panel, read [Hosted Runtime](../harness/hosted-runtime.md) and
[Model Management](../getting-started/models.md) instead. The two share the capability
registry and nothing else.

## Install the skill

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin
pip install -e .   # the Python client, the CLI and the server
./setup            # symlinks skills/terrafin into every AI host found
```

- `./setup --host claude|codex|opencode` targets one host.
- The install is a symlink, so `git pull` upgrades every host at once.
- [`skills/terrafin/SKILL.md`](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
  is the entry point.
- Task recipes live beside it under `references/`.

## Resolve the base URL

Do not hardcode the address. It is configuration (`.env.example`), so derive
it:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"
```

## Discover what exists

- `/agent/api/*` is the widest surface: nearly every capability has a route.
- **The Python client and CLI expose a smaller subset**, so do not assume a
  method exists because a route does.
- A few capabilities have no route because they need a live session.
- SKILL.md lists the capabilities with no route.

```bash
curl -s $TF/openapi.json \
  | jq '.paths | with_entries(select(.key | startswith("/agent/api/")
        and (contains("/runtime") | not)))'
```

Each entry carries the parameter schema, response model and description. That
is the source of truth for argument validation.

## Find what a series is called

Every data call takes a name from TerraFin's catalog.

- Do not guess a ticker.
- Do not fetch the number from an outside source.
- If you do not know the exact name, search:

```bash
curl "$TF/agent/api/indicator-search?q=trea"
```

`/agent/api/resolve` is not a substitute. It matches exact names only, and
treats an unknown string as a stock ticker instead of reporting a miss.

In-process, the same search and the series behind it:

```python
from TerraFin.data.factory import DataFactory

df = DataFactory()
df.search_indicators("trea")                                 # find the name
chunk = df.get_recent_history("Treasury-30Y", period="30y")
chunk.frame[["time", "close"]]
```

`get_indicator_snapshot` is not a general scalar reader. It serves private
series only and raises on a market or economic name.

## Read the processing metadata

Data responses carry processing metadata:

- how deep the request asked for
- how deep it loaded
- the loaded range
- whether older data exists

Start at `depth="auto"`, inspect, and rerun with `depth="full"` only when the
task needs long-range context.

## Read next

- [Usage](usage.md): the capability index and the route summary
- [Data Layer](../reference/data-layer.md): contracts, the `DataFactory` facade, caching
- [Architecture](../harness/architecture.md): how the skill layer and TerraFin's own
  agent share one capability layer
