// Single source of truth for "user picked or typed a search term → navigate".
// The /resolve-ticker endpoint decides routing: indices/macro go to Market
// Insights (e.g. "S&P 500" → /market-insights?ticker=S&P 500), stocks go to
// /stock/<ticker>. Every search surface (funcbar, stock-page search, …) calls
// this for BOTH click-select and submit so the two never diverge.
export function resolveAndGo(query: string): void {
  const trimmed = query.trim();
  if (!trimmed) return;
  fetch(`/resolve-ticker?q=${encodeURIComponent(trimmed)}`)
    .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
    .then((d: { path: string }) => {
      window.location.href = d.path;
    })
    .catch(() => {
      // Resolver unreachable — best-effort stock route.
      window.location.href = `/stock/${encodeURIComponent(trimmed.toUpperCase())}`;
    });
}
