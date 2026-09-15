# Portfolio, watchlist & session recipes

Reference for the `terrafin` skill. Shell examples use `$TF` — define it first, in this shell:

```bash
TF="http://${TERRAFIN_HOST:-127.0.0.1}:${TERRAFIN_PORT:-8001}${TERRAFIN_BASE_PATH:-}"
```

### Portfolio context

Use:

- `portfolio_context(guru)`

### Watchlist

Use:

- `watchlist()` — read the user's current watchlist (read-only from agent).

### Top companies

Use:

- `top_companies()` — market-cap-ranked equity list driving Market Insights.

### Read what the user is currently viewing

Use:

- `current_view_context()` — returns the page/panel the user is looking at,
  including form-state selection (e.g., the DCF input form's current
  `projectionYears`, `fcfBaseSource`, `turnaroundMode`, `breakevenYear`),
  FCF history candidates already loaded, the auto-selected DCF base source,
  and any active scenario state.

This is the agent's primary tool for matching what the user *sees* without
re-fetching. Always call it before answering "what am I looking at?" or
"explain this card" types of questions.

### Open chart

Use only when a chart is explicitly helpful.

- `open_chart("AAPL")`
- `open_chart(["S&P 500", "Nasdaq"])`

Chart requests by lookup name use TerraFin's progressive chart pipeline. Raw
dataframe chart requests are supported through the Python client and are treated
as complete from the start.
