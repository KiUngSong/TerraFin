import React, { useEffect, useState } from 'react';

interface FearGreedData {
  score: number | null;
  rating: string;
  timestamp: string;
  previous_close?: number;
  previous_1_week?: number;
  previous_1_month?: number;
}

const RATING_COLORS: Record<string, string> = {
  'Extreme Fear': '#991b1b',
  Fear: '#dc2626',
  Neutral: '#64748b',
  Greed: '#16a34a',
  'Extreme Greed': '#065f46',
};

const GAUGE_START_DEG = -178.4;
const GAUGE_END_DEG = -1.6;

const SCORE_BANDS = [
  { label: 'Extreme Fear', min: 1, max: 25, arcColor: '#ef4444' },
  { label: 'Fear', min: 25, max: 45, arcColor: '#fca5a5' },
  { label: 'Neutral', min: 45, max: 55, arcColor: '#d4d4d8' },
  { label: 'Greed', min: 55, max: 75, arcColor: '#86efac' },
  { label: 'Extreme Greed', min: 75, max: 100, arcColor: '#22c55e' },
] as const;

const FearGreedGauge: React.FC = () => {
  const [data, setData] = useState<FearGreedData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch('/dashboard/api/fear-greed')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && d.score != null) setData(d);
        else setFailed(true);
      })
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return <div style={{ fontSize: 12, color: '#94a3b8' }}>Data source not connected</div>;
  }

  if (!data || data.score == null) {
    return <div style={{ fontSize: 12, color: '#94a3b8' }}>Loading...</div>;
  }

  const score = data.score;
  const rating = data.rating;
  const activeBand = bandForScore(score);
  const color = RATING_COLORS[rating] || activeBand.arcColor || '#64748b';

  // Match the visual gauge bands to the same score thresholds used by the rating label.
  const needleDeg = scoreToNeedleRotation(score);

  return (
    <div className="tf-fear-greed">
      {/* Gauge */}
      <div style={{ width: 130, flexShrink: 0 }}>
        <svg viewBox="0 0 200 140" width="130" height="91">
          {SCORE_BANDS.map((band) => (
            <path
              key={band.label}
              d={thickArc(100, 110, 38, 92, scoreToAngle(band.min), scoreToAngle(band.max))}
              stroke={band.arcColor}
              fill={band.arcColor}
              opacity={band.label === activeBand.label ? 1 : 0.2}
            />
          ))}

          {/* Needle */}
          <g transform={`rotate(${needleDeg}, 100, 110)`}>
            <line x1="100" y1="110" x2="100" y2="45" stroke="#1e293b" strokeWidth="3" strokeLinecap="round" />
          </g>
          <circle cx="100" cy="110" r="5" fill="#1e293b" />

          {/* Score below gauge */}
          <text x="100" y="135" textAnchor="middle" fontSize="18" fontWeight="800" fill="#1e293b">
            {score}
          </text>
        </svg>
      </div>

      {/* Label */}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 15, lineHeight: 1.5 }}>
          <span style={{ fontWeight: 700, color }}>{rating}</span>
          <span style={{ color: '#334155' }}> is driving the</span>
          <br />
          <span style={{ color: '#334155' }}>US market</span>
        </div>
        <div className="tf-fear-greed__history">
          {data.previous_close != null && (
            <span>Prev <span style={{ color: '#475569', fontWeight: 600 }}>{data.previous_close}</span></span>
          )}
          {data.previous_1_week != null && (
            <span>1W <span style={{ color: '#475569', fontWeight: 600 }}>{data.previous_1_week}</span></span>
          )}
          {data.previous_1_month != null && (
            <span>1M <span style={{ color: '#475569', fontWeight: 600 }}>{data.previous_1_month}</span></span>
          )}
        </div>
      </div>
    </div>
  );
};

/**
 * Build a thick arc path (filled band between inner and outer radius).
 */
function thickArc(
  cx: number, cy: number,
  rInner: number, rOuter: number,
  startDeg: number, endDeg: number
): string {
  const s1 = polar(cx, cy, rOuter, startDeg);
  const e1 = polar(cx, cy, rOuter, endDeg);
  const s2 = polar(cx, cy, rInner, endDeg);
  const e2 = polar(cx, cy, rInner, startDeg);
  const large = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;
  return [
    `M${s1.x},${s1.y}`,
    `A${rOuter},${rOuter} 0 ${large} 1 ${e1.x},${e1.y}`,
    `L${s2.x},${s2.y}`,
    `A${rInner},${rInner} 0 ${large} 0 ${e2.x},${e2.y}`,
    'Z',
  ].join(' ');
}

function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function scoreToAngle(score: number) {
  const clamped = Math.min(Math.max(score, 1), 100);
  return GAUGE_START_DEG + ((GAUGE_END_DEG - GAUGE_START_DEG) * (clamped - 1)) / 99;
}

function scoreToNeedleRotation(score: number) {
  const band = bandForScore(score);
  const bandStart = scoreToAngle(band.min);
  const bandEnd = scoreToAngle(band.max);
  const bandCount = band.max - band.min + 1;
  const paddedBinCount = bandCount + 2;
  const clamped = Math.min(Math.max(score, band.min), band.max);
  const paddedIndex = (clamped - band.min) + 2;
  const bandRatio = (paddedIndex - 1) / (paddedBinCount - 1);
  const absoluteAngle = bandStart + (bandEnd - bandStart) * bandRatio;

  // The needle line starts at straight-up (-90deg), so convert the absolute arc
  // angle into a relative SVG rotation around the gauge center.
  return absoluteAngle + 90;
}

function bandForScore(score: number) {
  return SCORE_BANDS.find((band) => score <= band.max) || SCORE_BANDS[SCORE_BANDS.length - 1];
}

export default FearGreedGauge;
