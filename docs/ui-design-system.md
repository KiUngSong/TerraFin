---
title: UI / UX Design System (TerraFin Terminal)
summary: The frontend design language — aesthetic, type spine, color tokens, casing, layout primitives, data-presentation and accessibility conventions. Read this before changing any frontend UI so the Terminal stays consistent.
read_when:
  - Adding or restyling any frontend component
  - Touching fonts, colors, spacing, or casing
  - Adding a dashboard widget, panel, or page
  - Reviewing UI for consistency / doing design QA
---

# UI / UX Design System — TerraFin Terminal

Frontend lives at `src/TerraFin/interface/frontend/src`. Build with
`src/TerraFin/interface/build_component.sh` (runs `npm run build`; the backend
serves the bundle on `:8001`). This doc is the source of truth for *how the UI
should look and behave*. When in doubt, match what's here, not whatever is
nearby.

## Philosophy

A dense, Bloomberg-DNA market **terminal** — information-rich, sharp, fast to
scan — but personal: the user shapes their own terrain (watchlist, layout) and
an AI co-pilot reads the same screen. Every pixel earns its place; every label
is honest about what it claims. Prefer **interpretation over raw dumps**, and
**one shared primitive over per-page silos**.

## Type spine (single scale — never invent sizes)

One font family (`--tf-sans`, Inter + Pretendard for Hangul; `--tf-mono` is
aliased to it). Numerics use `font-variant-numeric: tabular-nums`. All text uses
exactly these tokens — **no raw `px`, no off-spine values** (a stray 9px/12px is
a bug):

| Token | px | Role |
|---|---|---|
| `--tf-fs-micro` | 10 | footnotes, source tags, timestamps |
| `--tf-fs-xs` | 11 | labels, eyebrows, column headers, chips, tags |
| `--tf-fs-base` | 13 | body, table values, paragraphs |
| `--tf-fs-md` | 15 | card / panel / page titles |
| `--tf-fs-lg` | 20 | the one focal metric per card |
| `--tf-fs-xl` | 28 | page wordmark / rare hero |

**Weight max is 700.** `fontWeight: 800` is always a bug. (`--tf-fs-sm`/12px was
removed — do not reintroduce.) SVG charts must set font via
`style={{ fontSize: 'var(--tf-fs-…)' }}` (CSS vars don't resolve in SVG
presentation attributes).

## Spacing & dimensions (tokens, not raw px)

Layout numbers come from tokens in `theme.css`, not inline px, so density stays
uniform and tunable from one place:

- `--tf-space-1..6` (4 / 8 / 12 / 16 / 24 / 32) — padding, gap, margin.
- `--tf-tap-min` (40px) — minimum interactive target on touch viewports.
- `--tf-radius` / `--tf-radius-panel` / `--tf-radius-modal`, `--tf-row-h`,
  `--tf-pane-header-h` — existing chrome dimensions.
- `--tf-panel-h-mobile` — shared height for the stacked Stocks/Sectors panel on
  mobile. Consumed by BOTH CSS (panel body) and JS (`StockHeatmap` reads it via
  `getComputedStyle` for the TradingView embed height) so the two tabs fill the
  same box and tab-switching doesn't reflow the column. When a dimension must be
  shared across the CSS/JS boundary, make the token the single source and read
  it in JS — don't duplicate the literal.

## Color (tokens only — never hardcode hex for chrome)

All chrome colors come from `--tf-*` tokens in `styles/theme.css`; theme switches
via `[data-theme="dark"|"light"]` on `<html>` (persisted in the zustand store,
applied pre-paint in `index.html`). 10-step gray ramp; light is a warm-paper
reader mode, not an RGB inversion.

- Surfaces: `--tf-bg`, `--tf-bg-pane`, `--tf-bg-elevated`, `--tf-bg-hover`
- Text: `--tf-text`, `--tf-text-strong`, `--tf-muted`, `--tf-muted-strong`
- Borders: `--tf-border`, `--tf-border-strong`
- Semantic: `--tf-up` (green), `--tf-down` (red), `--tf-amber`/`--tf-accent`

Hardcoded hex is allowed ONLY for genuine data-viz palettes (chart series, gauge
arcs, sector ramps, treemap tiles, white-on-colored-tile text) — never for UI
chrome (a dropdown that hardcodes light grays breaks dark mode).

## Casing system ("System A")

- **UPPERCASE** (+ `letter-spacing`): panel tabs, in-pane section eyebrows,
  table column headers, data-state chips (EXPANDING/COMPRESSED/LONG GAMMA),
  abbreviations (SPY, EPS).
- **Title-Case**: card / panel / page titles, inline field labels (Coverage,
  Spread).
- **sentence case**: body, descriptions, subtitles.

## Layout & component primitives

- `TerminalWorkspace` — CSS-grid of numbered panels (preset in `layout.ts`).
- `PanelFrame` — a panel with tabbed widgets (`tabs[]`); tabs are nav chrome
  (base/13, UPPERCASE), distinct from page-hero titles.
- `TerminalPane` (`.tf-pane__*`) — the titled card chrome (title + subtitle +
  meta). **`InsightCard` is a thin shim that delegates to `TerminalPane`** — so a
  single `.tf-pane__*` rule covers every card on every page. Don't fork headers.
- `FunctionBar` — top nav + unified search + theme toggle + GitHub/Docs links +
  Weekly-Reports bell. Chrome icon buttons use `.tf-funcbar__kbutton` (uniform
  28×28 square; ≥40px tap target on mobile).
- `StatusBar` — bottom: clock, active ticker, freshness, agent LED (driven by
  `useTerminalStore.agentActivity`, set by the agent widget on send/idle).
- Floating agent drawer (`GlobalAgentWidget`) — z-index above the funcbar;
  full-screen on mobile.
- Composite "stack" panes (`MacroStack`, `SentimentCalendarStack`) compose two
  child widgets under one tab, each labelled by a shared `EYEBROW_STYLE`
  (`terminal/widgets/stackStyles.ts`).

## Data-presentation conventions

- **Interpret, don't dump.** A bare `label: value` list is the floor. Add the
  signal: a regime word + A/D bar (breadth), a percentile + range track (P/E),
  not just numbers.
- Any computed regime/status word carries a **hover `title`** explaining its
  thresholds, and a **glyph prefix** (`▲ / ▼ / —`) so it's readable without
  color (colorblind-safe). Don't sell arbitrary buckets as deep insight — keep
  thresholds honest and labelled.
- Source tags `[src · HH:MM TZ]`, magnitude-scaled `SignedDelta` for changes.
- Clickable rows/cards navigate; prefer a semantic `<a>` for the primary target
  (keyboard + right-click) over a bare `onClick`.

## Search (one resolver, no silos)

Every search surface (FunctionBar, stock-page search) routes **both click-select
and submit** through `shared/resolveTicker.ts` → `/resolve-ticker`. Indices/macro
resolve to `/market-insights?ticker=…`, stocks to `/stock/<ticker>`. Never
hardcode `/stock/${symbol}` on select (that's what sent "S&P 500" to an unknown
ticker). Always `encodeURIComponent` ticker path segments (`^GSPC`, `BRK-B`).

## Responsive & accessibility

- Mobile (≤767px): tap targets ≥ 40px; agent drawer is full-screen (`box-sizing:
  border-box` on `width:100vw`+padding); pane headers stack title-above-subtitle;
  calendar event tap scrolls the detail into view; ticker tape edge-fades
  (tape-only) instead of hard-clipping.
- Treemap (skewed portfolios): fold holdings below `MIN_VISIBLE_WEIGHT` into one
  `OTHER (n)` tile so every visible tile is legible — no slivers.
- `:focus-visible` amber ring on all interactive elements (keyboard nav).
- Muted text must clear AA; small muted text uses `--tf-muted-strong`.

## Maintenance rules

1. Fonts → spine tokens only. Colors → `--tf-*` tokens only (chrome).
2. One shared primitive, not per-page copies. Find the existing component first.
3. After any change: `npx tsc --noEmit` + `build_component.sh`, then verify on
   `:8001` at **desktop 1440 AND mobile 390, dark AND light**.
4. When removing/redesigning, diff against the prior version — don't silently
   drop existing features (links, widgets, controls).
