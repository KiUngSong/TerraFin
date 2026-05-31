import React, { useEffect, useMemo, useState } from 'react';

interface BreadthMetric {
  label: string;
  value: string;
  tone: string;
}

const num = (s: string | undefined): number | null => {
  if (!s) return null;
  const n = parseFloat(s.replace(/[^0-9.\-]/g, ''));
  return Number.isFinite(n) ? n : null;
};

const MarketBreadthCard: React.FC = () => {
  const [metrics, setMetrics] = useState<BreadthMetric[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/terminal/api/market-breadth')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((p: { metrics?: BreadthMetric[] }) => setMetrics(p.metrics || []))
      .catch(() => setMetrics([]))
      .finally(() => setLoading(false));
  }, []);

  const read = useMemo(() => {
    const find = (frag: string) => metrics.find((m) => m.label.toLowerCase().includes(frag));
    const adv = num(find('advanc')?.value);
    const dec = num(find('declin')?.value);
    let pct = num(find('advance %')?.value);
    if (pct == null && adv != null && dec != null && adv + dec > 0) pct = (adv / (adv + dec)) * 100;
    if (pct == null) return null;
    // Regime band from advance breadth — the at-a-glance market-internals read.
    const regime = pct >= 55 ? 'EXPANDING' : pct >= 45 ? 'NEUTRAL' : 'WEAK';
    const lead = pct > 52 ? 'advancers lead' : pct < 48 ? 'decliners lead' : 'balanced';
    const color = pct >= 55 ? 'var(--tf-up)' : pct < 45 ? 'var(--tf-down)' : 'var(--tf-muted-strong)';
    return { adv, dec, pct, regime, lead, color };
  }, [metrics]);

  return (
    <a
      href="/market-insights?ticker=Net%20Breadth"
      className="tf-kv tf-kv--link"
      title="Open breadth chart in Market Insights"
    >
      {loading ? <div className="tf-table__status">loading…</div> : null}
      {!loading && !read ? <div className="tf-table__status">no breadth data</div> : null}
      {read ? (
        <>
          <div
            className="tf-kv__row tf-kv__row--span"
            style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}
            title="Advance breadth regime — EXPANDING ≥55% · NEUTRAL 45–55% · WEAK <45% of issues advancing"
          >
            <span style={{ fontSize: 'var(--tf-fs-xs)', fontWeight: 700, letterSpacing: '0.06em', color: read.color }}>
              {read.regime === 'EXPANDING' ? '▲ ' : read.regime === 'WEAK' ? '▼ ' : '— '}{read.regime}
            </span>
            <span style={{ fontSize: 'var(--tf-fs-xs)', color: 'var(--tf-muted)' }}>· {read.lead}</span>
            <span style={{ marginLeft: 'auto', fontSize: 'var(--tf-fs-md)', fontWeight: 700, color: read.color, fontVariantNumeric: 'tabular-nums' }}>
              {read.pct.toFixed(1)}%
            </span>
          </div>
          <div className="tf-kv__row--span" aria-hidden>
            <div style={{ display: 'flex', height: 6, borderRadius: 2, overflow: 'hidden', background: 'var(--tf-down)' }}>
              <div style={{ width: `${read.pct}%`, background: 'var(--tf-up)' }} />
            </div>
          </div>
          <div className="tf-kv__row tf-kv__row--span" style={{ display: 'flex', gap: 12, fontSize: 'var(--tf-fs-xs)', fontVariantNumeric: 'tabular-nums' }}>
            <span style={{ color: 'var(--tf-up)' }}>{read.adv ?? '--'} ▲</span>
            <span style={{ color: 'var(--tf-down)' }}>{read.dec ?? '--'} ▼</span>
          </div>
        </>
      ) : null}
      <div className="tf-kv__row tf-kv__row--span tf-kv__cta">Open Breadth chart →</div>
    </a>
  );
};

export default MarketBreadthCard;
