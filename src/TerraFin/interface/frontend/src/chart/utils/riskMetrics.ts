/**
 * Client-side risk metrics computation.
 *
 * Optimised for interactive use:
 * - Two passes over the data (returns + stats), no redundant iteration
 * - Max drawdown computed inline during returns construction
 * - Quickselect (O(n) avg) for VaR/CVaR instead of full sort
 */

export function computeRiskMetrics(closes: number[]): Record<string, number> | null {
  const n = closes.length;
  if (n < 3) return null;

  // ── Pass 1: build returns, max drawdown, total return ──────────────
  const rn = n - 1;
  const returns = new Float64Array(rn);
  let peak = closes[0];
  let maxDD = 0;
  for (let i = 1; i < n; i++) {
    returns[i - 1] = closes[i] / closes[i - 1] - 1;
    if (closes[i] > peak) peak = closes[i];
    const dd = (peak - closes[i]) / peak;
    if (dd > maxDD) maxDD = dd;
  }

  // ── Pass 2: mean, variance, downside, wins in one loop ─────────────
  let sum = 0;
  let sumSq = 0;
  let dsSum = 0;
  let dsCount = 0;
  let wins = 0;
  for (let i = 0; i < rn; i++) {
    const r = returns[i];
    sum += r;
    if (r > 0) wins++;
    if (r < 0) {
      dsSum += r * r;
      dsCount++;
    }
  }
  const mean = sum / rn;
  for (let i = 0; i < rn; i++) {
    const d = returns[i] - mean;
    sumSq += d * d;
  }
  const std = Math.sqrt(sumSq / (rn - 1));

  // Sharpe & Sortino (annualised, rf=0)
  const sqrt252 = 15.874507866; // Math.sqrt(252)
  const sharpe = std > 0 ? (mean / std) * sqrt252 : 0;
  const dsStd = dsCount > 0 ? Math.sqrt(dsSum / dsCount) : 0;
  const sortino = dsStd > 0 ? (mean / dsStd) * sqrt252 : 0;

  // ── VaR & CVaR via quickselect (O(n) avg) ──────────────────────────
  const buf = new Float64Array(returns); // copy for in-place partition
  const k95 = Math.max(0, Math.floor(0.05 * rn) - 1);
  const k99 = Math.max(0, Math.floor(0.01 * rn) - 1);
  const var99 = quickselect(buf, k99);
  const var95 = quickselect(buf, k95); // k95 >= k99, buf already partitioned up to k99
  // CVaR: mean of everything <= VaR
  let tail95Sum = 0;
  let tail95N = 0;
  let tail99Sum = 0;
  let tail99N = 0;
  for (let i = 0; i < rn; i++) {
    if (returns[i] <= var95) { tail95Sum += returns[i]; tail95N++; }
    if (returns[i] <= var99) { tail99Sum += returns[i]; tail99N++; }
  }
  const cvar95 = tail95N > 0 ? tail95Sum / tail95N : var95;
  const cvar99 = tail99N > 0 ? tail99Sum / tail99N : var99;

  // ── Annualised return & Calmar ─────────────────────────────────────
  const totalReturn = closes[n - 1] / closes[0];
  const years = rn / 252;
  const annReturn = years > 0 ? totalReturn ** (1 / years) - 1 : 0;
  const calmar = maxDD > 0 ? annReturn / maxDD : 0;

  return {
    'Ann. Return': round(annReturn * 100, 2),
    Volatility: round(std * sqrt252 * 100, 2),
    Sharpe: round(sharpe, 3),
    Sortino: round(sortino, 3),
    'Max DD': round(maxDD * 100, 2),
    Calmar: round(calmar, 3),
    'Win Rate': round((wins / rn) * 100, 1),
    'VaR 95%': round(var95 * 100, 2),
    'VaR 99%': round(var99 * 100, 2),
    'CVaR 95%': round(cvar95 * 100, 2),
    'CVaR 99%': round(cvar99 * 100, 2),
  };
}

// ── Helpers ──────────────────────────────────────────────────────────────

function round(v: number, d: number): number {
  const f = 10 ** d;
  return Math.round(v * f) / f;
}

/** In-place quickselect: rearranges so arr[k] is the k-th smallest. O(n) avg. */
function quickselect(arr: Float64Array, k: number): number {
  let lo = 0;
  let hi = arr.length - 1;
  while (lo < hi) {
    const pivot = arr[(lo + hi) >> 1];
    let i = lo;
    let j = hi;
    while (i <= j) {
      while (arr[i] < pivot) i++;
      while (arr[j] > pivot) j--;
      if (i <= j) {
        const tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
        i++; j--;
      }
    }
    if (j < k) lo = i;
    if (i > k) hi = j;
  }
  return arr[k];
}
