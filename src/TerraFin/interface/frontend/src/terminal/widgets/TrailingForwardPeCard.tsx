import React, { useEffect, useMemo, useState } from 'react';

interface TrailingForwardPeHistoryPoint {
  date: string;
  value: number;
}

interface TrailingForwardPeSpreadPayload {
  date: string;
  description: string;
  latestValue?: number | null;
  usableCount?: number | null;
  requestedCount?: number | null;
  history: TrailingForwardPeHistoryPoint[];
}

const TrailingForwardPeCard: React.FC = () => {
  const [payload, setPayload] = useState<TrailingForwardPeSpreadPayload | null>(null);

  useEffect(() => {
    fetch('/terminal/api/trailing-forward-pe-spread')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((p: TrailingForwardPeSpreadPayload) => setPayload(p))
      .catch(() => setPayload(null));
  }, []);

  // Where does the latest spread sit within its own trailing window? A bare
  // number ("7.74") is meaningless without that range — this is the insight.
  const read = useMemo(() => {
    const latest = typeof payload?.latestValue === 'number' ? payload.latestValue : null;
    const vals = (payload?.history || []).map((p) => p.value).filter((v) => Number.isFinite(v));
    if (latest == null || vals.length < 2) return null;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const pct = Math.round((vals.filter((v) => v <= latest).length / vals.length) * 100);
    // Dot encodes the PERCENTILE RANK (matches the "Nth pct" label + COMPRESSED/
    // STRETCHED status), not the raw linear value position — otherwise a skewed
    // distribution puts the dot mid-track while the label says 16th pct.
    const pos = pct / 100;
    const status = pct < 33 ? 'COMPRESSED' : pct > 66 ? 'STRETCHED' : 'MID-RANGE';
    const color = pct > 66 ? 'var(--tf-down)' : pct < 33 ? 'var(--tf-up)' : 'var(--tf-muted-strong)';
    // Honest window label from the actual history span — not a hardcoded "1y".
    const hist = payload?.history || [];
    let spanLabel = 'range';
    const t0 = Date.parse(hist[0]?.date ?? '');
    const t1 = Date.parse(hist[hist.length - 1]?.date ?? '');
    if (Number.isFinite(t0) && Number.isFinite(t1) && t1 > t0) {
      const months = Math.round((t1 - t0) / (30 * 86400000));
      spanLabel = months >= 12 ? `${Math.round(months / 12)}y range` : `${Math.max(months, 1)}mo range`;
    }
    return { latest, min, max, pos, pct, status, color, spanLabel };
  }, [payload]);

  return (
    <a
      href="/market-insights?ticker=Trailing-Forward%20P%2FE%20Spread"
      className="tf-kv tf-kv--link"
      title="Open P/E Spread chart in Market Insights"
    >
      {!read ? (
        <div className="tf-table__status">{payload ? 'no spread history' : 'loading…'}</div>
      ) : (
        <>
          <div
            className="tf-kv__row tf-kv__row--span"
            style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}
            title="Where the latest spread sits in its own history — COMPRESSED <33rd pct · MID-RANGE 33–66th · STRETCHED >66th percentile"
          >
            <span style={{ fontSize: 'var(--tf-fs-md)', fontWeight: 700, color: 'var(--tf-text-strong)', fontVariantNumeric: 'tabular-nums' }}>
              {read.latest.toFixed(2)}
            </span>
            <span style={{ fontSize: 'var(--tf-fs-xs)', fontWeight: 700, letterSpacing: '0.06em', color: read.color }}>
              {read.status === 'STRETCHED' ? '▲ ' : read.status === 'COMPRESSED' ? '▼ ' : '— '}{read.status}
            </span>
            <span style={{ marginLeft: 'auto', fontSize: 'var(--tf-fs-xs)', color: 'var(--tf-muted)', fontVariantNumeric: 'tabular-nums' }}>
              {read.pct}th pct
            </span>
          </div>
          <div className="tf-kv__row tf-kv__row--span" style={{ position: 'relative', height: 6, margin: '2px 0' }} aria-hidden>
            <div style={{ position: 'absolute', top: 2, left: 0, right: 0, height: 2, background: 'var(--tf-border-strong)' }} />
            <div style={{ position: 'absolute', top: 0, left: `${read.pos * 100}%`, width: 6, height: 6, marginLeft: -3, borderRadius: '50%', background: read.color }} />
          </div>
          <div className="tf-kv__row tf-kv__row--span" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--tf-fs-micro)', color: 'var(--tf-muted)', fontVariantNumeric: 'tabular-nums' }}>
            <span>{read.min.toFixed(1)}</span>
            <span>{read.spanLabel}</span>
            <span>{read.max.toFixed(1)}</span>
          </div>
          <div
            className="tf-kv__row"
            style={{ marginTop: 2 }}
            title={`${payload?.usableCount ?? '--'} of ${payload?.requestedCount ?? '--'} index members had usable trailing+forward P/E data; as of ${payload?.date || '--'}`}
          >
            <span className="tf-kv__label">Coverage</span>
            <span className="tf-kv__value tf-kv__value--muted">
              {payload?.usableCount ?? '--'}/{payload?.requestedCount ?? '--'} · {payload?.date || '--'}
            </span>
          </div>
        </>
      )}
      <div className="tf-kv__row tf-kv__row--span tf-kv__cta">Open P/E chart →</div>
    </a>
  );
};

export default TrailingForwardPeCard;
