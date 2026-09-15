# TerraFin for External Agents

For agents that own their own model loop — Claude Code, Codex, opencode, or
anything that speaks HTTP — and want TerraFin as a data and analysis backend.

This is **Mode B**. If instead you want TerraFin to own the conversation and
tool loop, that is Mode A, the hosted runtime: see
[hosted-runtime.md](./hosted-runtime.md) and [models.md](./models.md). The two
share a capability registry and nothing else; nothing on this page needs a
model provider, an API key, or a runtime session.

## Install the skill

```bash
git clone https://github.com/KiUngSong/TerraFin
cd TerraFin && ./setup          # symlinks skills/terrafin into every AI host found
```

`./setup --host claude|codex|opencode` targets one host. The install is a
symlink, so `git pull` upgrades every host at once.
[`skills/terrafin/SKILL.md`](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
is the entry point; task recipes live beside it under `references/`.

## Resolve the base URL

Never hardcode `127.0.0.1:8001`. The address is configuration
(`.env.example`), so derive it:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"
```

## Discover what exists

`/agent/api/*` is the widest surface: nearly every capability has a route, and
the `openapi.json` call below enumerates exactly which. The Python client and
CLI expose a smaller subset under the same names — do not assume a method
exists because a route does. A few capabilities have no route at all: some are
session-bound by design, others are simply in-process only. **An HTTP-only
agent cannot reach those at all**; it needs `pip install -e .` and an
in-process `build_default_capability_registry().invoke("<name>", …)`. The
generated "Hosted-runtime-only tools" list in
[SKILL.md](https://github.com/KiUngSong/TerraFin/blob/main/skills/terrafin/SKILL.md)
names which ones, and is regenerated from the registry.

```bash
curl -s $TF/openapi.json \
  | jq '.paths | with_entries(select(.key | startswith("/agent/api/")
        and (contains("/runtime") | not)))'
```

Each entry carries the parameter schema, response model and description. That
is the source of truth for argument validation.

## Find what a series is called

Every data call takes a name from TerraFin's catalog, which spans four
registries (Index, Market, Economic, and chart-only custom specs). If you do
not know the exact name, search — do not guess a ticker, and do not fetch the
number from an outside source:

```bash
curl "$TF/agent/api/indicator-search?q=trea"
# Treasury-13W / 2Y / 5Y / 10Y / 30Y, TGA, Term Spread, High Yield Spread, ...
```

`/agent/api/resolve` is not a substitute. It matches exact names only, and
answers an unrecognised string with a fabricated stock row — `trea` comes back
as `type: stock, name: TREA` rather than as a miss.

In-process, the same search and the series behind it:

```python
from TerraFin.data.factory import DataFactory

df = DataFactory()
df.search_indicators("trea")                                 # find the name
chunk = df.get_recent_history("Treasury-30Y", period="30y")   # 7531 rows, 1996→
chunk.frame[["time", "close"]]         # columns are lowercase: time, close
```

`period` takes `30d` / `3m` / `5y` offsets plus `ytd` and `max`. `max` on
`Treasury-30Y` reaches 1977. `get_indicator_snapshot` is **not** the scalar
reader for these — it serves private series only and raises on a market or
economic name.

## Read the processing metadata

Every response carries `requestedDepth`, `resolvedDepth`, `loadedStart`,
`loadedEnd`, `isComplete`, `hasOlder`, `sourceVersion`, `view`. Start at
`depth="auto"`, inspect, and only rerun with `depth="full"` when the task
genuinely needs long-range context.

## Read next

- [usage.md](./usage.md) — the full capability list and the route summary
- [../data-layer.md](../data-layer.md) — contracts, the `DataFactory` facade, caching
- [architecture.md](./architecture.md#operating-modes) — how Mode A and Mode B differ
