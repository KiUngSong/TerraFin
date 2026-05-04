import React, { useEffect, useMemo, useState } from 'react';
import InsightCard from '../components/InsightCard';

interface SpxGexHistoryCardProps {
  /** Delay the fetch until true — lets the host page prioritize chart data first. */
  enabled?: boolean;
}

interface SpxGexPoint {
  date: string;
  gex_b: number;
  dix: number | null;
  price: number | null;
}

interface SpxGexHistoryPayload {
  points: SpxGexPoint[];
  source: string;
}

type Range = '1Y' | '2Y' | '5Y' | 'ALL';
const RANGE_DAYS: Record<Range, number> = { '1Y': 252, '2Y': 504, '5Y': 1260, ALL: 99999 };
const RANGES: Range[] = ['1Y', '2Y', '5Y', 'ALL'];

const W = 320;
const H = 100;
const PAD_L = 38;
const PAD_R = 8;
const PAD_T = 14;
const PAD_B = 22;
const CHART_W = W - PAD_L - PAD_R;
const CHART_H = H - PAD_T - PAD_B;

const GexBarChart: React.FC<{ points: SpxGexPoint[] }> = ({ points }) => {
  if (points.length === 0) {
    return <div className="tf-dashboard-status">No data available.</div>;
  }

  const values = points.map((p) => p.gex_b);
  const absMax = Math.max(...values.map(Math.abs), 0.1);
  const yScale = (v: number) => PAD_T + CHART_H * (1 - (v + absMax) / (2 * absMax));
  const zeroY = yScale(0);

  const barW = Math.max(1, CHART_W / points.length - 0.4);

  // Y-axis ticks: +absMax, 0, -absMax
  const yTicks = [absMax, 0, -absMax];

  // X-axis labels: first, middle, last
  const xLabels: { idx: number; label: string }[] = [
    { idx: 0, label: points[0].date.slice(0, 7) },
    { idx: Math.floor(points.length / 2), label: points[Math.floor(points.length / 2)].date.slice(0, 7) },
    { idx: points.length - 1, label: points[points.length - 1].date.slice(0, 7) },
  ];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      role="img"
      aria-label="SPX Gamma Exposure history"
    >
      {/* Y-axis ticks */}
      {yTicks.map((v) => {
        const y = yScale(v);
        const label = v === 0 ? '0' : `${v > 0 ? '+' : ''}${v.toFixed(1)}B`;
        return (
          <g key={v}>
            <line x1={PAD_L - 3} y1={y} x2={W - PAD_R} y2={y} stroke={v === 0 ? '#94a3b8' : '#e2e8f0'} strokeWidth={v === 0 ? 1 : 0.5} />
            <text x={PAD_L - 5} y={y + 3.5} textAnchor="end" fontSize={8} fill="#94a3b8">
              {label}
            </text>
          </g>
        );
      })}

      {/* Bars */}
      {points.map((p, i) => {
        const x = PAD_L + (i / points.length) * CHART_W;
        const barY = p.gex_b >= 0 ? yScale(p.gex_b) : zeroY;
        const barH = Math.abs(yScale(p.gex_b) - zeroY);
        return (
          <rect
            key={p.date}
            x={x}
            y={barY}
            width={barW}
            height={Math.max(barH, 0.5)}
            fill={p.gex_b >= 0 ? '#22c55e' : '#ef4444'}
            opacity={0.85}
          />
        );
      })}

      {/* X-axis labels */}
      {xLabels.map(({ idx, label }) => {
        const x = PAD_L + ((idx + 0.5) / points.length) * CHART_W;
        const anchor = idx === 0 ? 'start' : idx === points.length - 1 ? 'end' : 'middle';
        return (
          <text key={idx} x={x} y={H - 6} textAnchor={anchor} fontSize={8} fill="#94a3b8">
            {label}
          </text>
        );
      })}
    </svg>
  );
};

const SpxGexHistoryCard: React.FC<SpxGexHistoryCardProps> = ({ enabled = true }) => {
  const [payload, setPayload] = useState<SpxGexHistoryPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [range, setRange] = useState<Range>('1Y');

  useEffect(() => {
    if (!enabled) return;
    fetch('/dashboard/api/spx-gex-history')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: SpxGexHistoryPayload) => setPayload(d))
      .catch(() => setFailed(true));
  }, [enabled]);

  const visible = useMemo(() => {
    if (!payload) return [];
    const days = RANGE_DAYS[range];
    return payload.points.slice(-days);
  }, [payload, range]);

  const latest = visible.length > 0 ? visible[visible.length - 1] : null;
  const isLong = (latest?.gex_b ?? 0) >= 0;

  return (
    <InsightCard
      title="SPX Gamma Exposure"
      subtitle="Dealer net gamma positioning — long gamma suppresses moves, short gamma amplifies them."
    >
      {failed ? (
        <div className="tf-dashboard-status tf-dashboard-status--error">Failed to load GEX history.</div>
      ) : (
        <div className="tf-dashboard-gex">
          <div className="tf-dashboard-gex__summary">
            <div className="tf-dashboard-gex__stat">
              <div className="tf-dashboard-gex__label">Latest GEX</div>
              <div className="tf-dashboard-gex__value">
                {latest ? `${latest.gex_b >= 0 ? '+' : ''}${latest.gex_b.toFixed(2)}B` : '--'}
              </div>
            </div>
            <div className="tf-dashboard-gex__meta">
              <span className="tf-dashboard-gex__regime" data-regime={isLong ? 'long' : 'short'}>
                {isLong ? 'Long Gamma' : 'Short Gamma'}
              </span>
              <div className="tf-dashboard-gex__date">{latest?.date ?? ''}</div>
            </div>
          </div>

          <div className="tf-dashboard-gex__range-tabs">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                className={`tf-dashboard-gex__range-btn${range === r ? ' tf-dashboard-gex__range-btn--active' : ''}`}
                onClick={() => setRange(r)}
              >
                {r}
              </button>
            ))}
          </div>

          <div className="tf-dashboard-gex__chart">
            {!payload ? (
              <div className="tf-dashboard-status">Loading…</div>
            ) : (
              <GexBarChart points={visible} />
            )}
          </div>
        </div>
      )}
    </InsightCard>
  );
};

export default SpxGexHistoryCard;
