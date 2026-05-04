import React from 'react';
import { GexPayload } from '../useStockData';

interface Props {
  payload: GexPayload | null;
  loading: boolean;
  error: string | null;
}

const COLOR_CALL = '#16a34a';
const COLOR_PUT = '#dc2626';
const COLOR_SPOT = '#0f172a';
const COLOR_ZERO_GAMMA = '#f59e0b';
const COLOR_GRID = '#e2e8f0';

const GexPanel: React.FC<Props> = ({ payload, loading, error }) => {
  if (loading) return <div style={{ fontSize: 13, color: '#475569' }}>Loading GEX…</div>;
  if (error) return <div style={{ fontSize: 13, color: '#b91c1c' }}>Failed to load GEX: {error}</div>;
  if (!payload) return null;
  if (!payload.available) return null;

  const totalB = payload.total_gex_b ?? 0;
  const regime = payload.regime ?? 'long_gamma';
  const isLong = regime === 'long_gamma';
  const spot = payload.spot_price ?? 0;
  const zeroGamma = payload.zero_gamma_strike;

  return (
    <div style={containerStyle}>
      <SummaryRow
        regime={regime}
        isLong={isLong}
        totalB={totalB}
        spot={spot}
        zeroGamma={zeroGamma}
        callWall={payload.largest_call_wall}
        putWall={payload.largest_put_wall}
      />

      <div style={chartGroupStyle}>
        <ChartCard title={`GEX by Strike (±${Math.round((payload.strike_window_pct ?? 0.15) * 100)}% spot, in $B)`}>
          <ByStrikeChart
            buckets={payload.by_strike}
            spot={spot}
            zeroGamma={zeroGamma}
            callWall={payload.largest_call_wall?.strike ?? null}
            putWall={payload.largest_put_wall?.strike ?? null}
          />
        </ChartCard>
        <ChartCard title={`GEX by Expiration (next ${payload.lookahead_days ?? 90}d, in $B)`}>
          <ByExpirationChart buckets={payload.by_expiration} />
        </ChartCard>
      </div>
    </div>
  );
};

const SummaryRow: React.FC<{
  regime: string;
  isLong: boolean;
  totalB: number;
  spot: number;
  zeroGamma: number | null;
  callWall: { strike: number; gex_b: number } | null;
  putWall: { strike: number; gex_b: number } | null;
}> = ({ regime, isLong, totalB, spot, zeroGamma, callWall, putWall }) => {
  const regimeColor = isLong ? '#16a34a' : '#dc2626';
  const regimeLabel = isLong ? 'LONG GAMMA' : 'SHORT GAMMA';
  const regimeBlurb = isLong
    ? 'Dealers buy dips / sell rallies — mean-reverting flow.'
    : 'Dealers chase moves — amplifies trend.';

  const distance = zeroGamma != null && spot ? ((spot - zeroGamma) / spot) * 100 : null;

  return (
    <div style={summaryRowStyle}>
      <div style={summaryBlockStyle}>
        <div style={{ ...regimeBadgeStyle, background: isLong ? '#dcfce7' : '#fee2e2', color: regimeColor }}>
          {regimeLabel}
        </div>
        <div style={metricLabelStyle}>Total GEX</div>
        <div style={{ ...metricValueStyle, color: regimeColor }}>{formatB(totalB)}</div>
        <div style={metricFootnoteStyle}>{regimeBlurb}</div>
      </div>

      <div style={summaryBlockStyle}>
        <div style={metricLabelStyle}>Spot</div>
        <div style={metricValueStyle}>{spot ? spot.toFixed(2) : '—'}</div>
        {zeroGamma != null && (
          <>
            <div style={{ ...metricLabelStyle, marginTop: 8 }}>Zero-gamma strike</div>
            <div style={metricValueSecondaryStyle}>{zeroGamma.toFixed(2)}</div>
            {distance != null && (
              <div style={{ ...metricFootnoteStyle, color: Math.abs(distance) < 0.5 ? '#dc2626' : '#64748b' }}>
                spot is {distance >= 0 ? '+' : ''}
                {distance.toFixed(2)}% vs zero-gamma
              </div>
            )}
          </>
        )}
      </div>

      <div style={summaryBlockStyle}>
        <div style={metricLabelStyle}>Largest call wall</div>
        <div style={{ ...metricValueSecondaryStyle, color: COLOR_CALL }}>
          {callWall ? `${callWall.strike.toFixed(2)} (${formatB(callWall.gex_b)})` : '—'}
        </div>
        <div style={{ ...metricLabelStyle, marginTop: 8 }}>Largest put wall</div>
        <div style={{ ...metricValueSecondaryStyle, color: COLOR_PUT }}>
          {putWall ? `${putWall.strike.toFixed(2)} (${formatB(putWall.gex_b)})` : '—'}
        </div>
      </div>
    </div>
  );
};

const ChartCard: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div style={chartCardStyle}>
    <div style={chartTitleStyle}>{title}</div>
    <div style={{ width: '100%', height: 220 }}>{children}</div>
  </div>
);

const ByStrikeChart: React.FC<{
  buckets: { strike?: number | null; gex_b: number }[];
  spot: number;
  zeroGamma: number | null;
  callWall: number | null;
  putWall: number | null;
}> = ({ buckets, spot, zeroGamma, callWall, putWall }) => {
  if (!buckets.length) return <EmptyChart message="No strikes within window." />;
  const strikes = buckets.map((b) => b.strike ?? 0);
  const minStrike = Math.min(...strikes);
  const maxStrike = Math.max(...strikes);
  const maxAbs = Math.max(...buckets.map((b) => Math.abs(b.gex_b))) || 1;

  const W = 600;
  const H = 220;
  const PAD_L = 48;
  const PAD_R = 12;
  const PAD_T = 36;
  const PAD_B = 40;
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;

  const x = (s: number) => PAD_L + ((s - minStrike) / Math.max(maxStrike - minStrike, 1e-9)) * innerW;
  const y = (g: number) => PAD_T + innerH / 2 - (g / maxAbs) * (innerH / 2);
  const bw = Math.max(innerW / Math.max(buckets.length, 1) - 1, 1);

  // Marker triangle drawn AT the wall bar's top, pointing at the bar.
  // Wall identity is conveyed by colored stroke + summary row metadata,
  // not by inline text — text labels collided with the spot/γ=0 lines.
  const wallMarker = (strike: number, color: string, key: string) => {
    if (!Number.isFinite(strike)) return null;
    if (strike < minStrike || strike > maxStrike) return null;
    const bucket = buckets.find((b) => b.strike === strike);
    if (!bucket) return null;
    const xc = x(strike);
    const yTip = bucket.gex_b >= 0 ? y(bucket.gex_b) - 4 : y(bucket.gex_b) + 4;
    const dir = bucket.gex_b >= 0 ? -1 : 1;
    const points = `${xc},${yTip} ${xc - 4},${yTip + dir * 6} ${xc + 4},${yTip + dir * 6}`;
    return <polygon key={key} points={points} fill={color} />;
  };

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
      <line x1={PAD_L} x2={W - PAD_R} y1={y(0)} y2={y(0)} stroke={COLOR_GRID} strokeWidth={1} />
      {buckets.map((b, i) => {
        const xc = x(b.strike ?? 0);
        const yTop = b.gex_b >= 0 ? y(b.gex_b) : y(0);
        const h = Math.abs(y(b.gex_b) - y(0));
        return (
          <rect
            key={i}
            x={xc - bw / 2}
            y={yTop}
            width={bw}
            height={Math.max(h, 0.5)}
            fill={b.gex_b >= 0 ? COLOR_CALL : COLOR_PUT}
            opacity={0.85}
          />
        );
      })}
      {/* spot: top band. γ=0: bottom band (below x-axis ticks) — never collide. */}
      {spot >= minStrike && spot <= maxStrike && (
        <>
          <line x1={x(spot)} x2={x(spot)} y1={PAD_T} y2={H - PAD_B} stroke={COLOR_SPOT} strokeWidth={1.5} strokeDasharray="3 3" />
          <text x={x(spot)} y={PAD_T - 10} fontSize={10} fill={COLOR_SPOT} textAnchor="middle">spot {spot.toFixed(2)}</text>
        </>
      )}
      {zeroGamma != null && zeroGamma >= minStrike && zeroGamma <= maxStrike && (
        <>
          <line x1={x(zeroGamma)} x2={x(zeroGamma)} y1={PAD_T} y2={H - PAD_B} stroke={COLOR_ZERO_GAMMA} strokeWidth={1.5} />
          <text x={x(zeroGamma)} y={H - PAD_B + 14} fontSize={10} fill={COLOR_ZERO_GAMMA} textAnchor="middle">γ=0 {zeroGamma.toFixed(2)}</text>
        </>
      )}
      {/* Wall markers — colored triangles at the bar top, no text overlay. */}
      {callWall != null && wallMarker(callWall, COLOR_CALL, 'cw')}
      {putWall != null && wallMarker(putWall, COLOR_PUT, 'pw')}
      {/* x-axis ticks: min, mid, max */}
      {[minStrike, (minStrike + maxStrike) / 2, maxStrike].map((s, i) => (
        <text key={i} x={x(s)} y={H - 14} fontSize={10} fill="#64748b" textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}>
          {s.toFixed(0)}
        </text>
      ))}
      {/* Single x-axis caption so the reader sees what the bottom number means. */}
      <text x={(PAD_L + W - PAD_R) / 2} y={H - 2} fontSize={9} fill="#94a3b8" textAnchor="middle">strike</text>
      {/* y-axis labels */}
      <text x={4} y={y(maxAbs) + 3} fontSize={10} fill="#64748b">+{maxAbs.toFixed(2)}B</text>
      <text x={4} y={y(0) + 3} fontSize={10} fill="#64748b">0</text>
      <text x={4} y={y(-maxAbs) + 3} fontSize={10} fill="#64748b">-{maxAbs.toFixed(2)}B</text>
    </svg>
  );
};

const ByExpirationChart: React.FC<{ buckets: { expiration?: string | null; gex_b: number }[] }> = ({ buckets }) => {
  if (!buckets.length) return <EmptyChart message="No expirations in window." />;
  const maxAbs = Math.max(...buckets.map((b) => Math.abs(b.gex_b))) || 1;
  const W = 600;
  const H = 220;
  const PAD_L = 44;
  const PAD_R = 12;
  const PAD_T = 14;
  const PAD_B = 36;
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;
  const bw = Math.max(innerW / buckets.length - 2, 2);
  const xCenter = (i: number) => PAD_L + ((i + 0.5) / buckets.length) * innerW;
  const y = (g: number) => PAD_T + innerH / 2 - (g / maxAbs) * (innerH / 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
      <line x1={PAD_L} x2={W - PAD_R} y1={y(0)} y2={y(0)} stroke={COLOR_GRID} strokeWidth={1} />
      {buckets.map((b, i) => {
        const xc = xCenter(i);
        const yTop = b.gex_b >= 0 ? y(b.gex_b) : y(0);
        const h = Math.abs(y(b.gex_b) - y(0));
        return (
          <g key={i}>
            <rect
              x={xc - bw / 2}
              y={yTop}
              width={bw}
              height={Math.max(h, 0.5)}
              fill={b.gex_b >= 0 ? COLOR_CALL : COLOR_PUT}
              opacity={0.85}
            />
            {(i === 0 || i === buckets.length - 1 || i % Math.max(Math.floor(buckets.length / 4), 1) === 0) && (
              <text x={xc} y={H - 18} fontSize={9} fill="#64748b" textAnchor="middle" transform={`rotate(-30 ${xc} ${H - 18})`}>
                {b.expiration?.slice(5)}
              </text>
            )}
          </g>
        );
      })}
      <text x={4} y={y(maxAbs) + 3} fontSize={10} fill="#64748b">+{maxAbs.toFixed(2)}B</text>
      <text x={4} y={y(0) + 3} fontSize={10} fill="#64748b">0</text>
      <text x={4} y={y(-maxAbs) + 3} fontSize={10} fill="#64748b">-{maxAbs.toFixed(2)}B</text>
    </svg>
  );
};

const EmptyChart: React.FC<{ message: string }> = ({ message }) => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', fontSize: 12, color: '#94a3b8' }}>
    {message}
  </div>
);

function formatB(v: number): string {
  const sign = v >= 0 ? '+' : '−';
  return `${sign}${Math.abs(v).toFixed(2)}B`;
}

const containerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  width: '100%',
};

const summaryRowStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
  gap: 12,
};

const summaryBlockStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  padding: '12px 14px',
  background: '#f8fafc',
  border: '1px solid #e2e8f0',
  borderRadius: 10,
  minWidth: 0,
};

const regimeBadgeStyle: React.CSSProperties = {
  alignSelf: 'flex-start',
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: '0.06em',
  padding: '3px 8px',
  borderRadius: 999,
  marginBottom: 4,
};

const metricLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
};

const metricValueStyle: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  color: '#0f172a',
};

const metricValueSecondaryStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
  color: '#0f172a',
};

const metricFootnoteStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#64748b',
  marginTop: 2,
};

const chartGroupStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(360px, 100%), 1fr))',
  gap: 12,
};

const chartCardStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  padding: 12,
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 10,
};

const chartTitleStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  color: '#475569',
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
};

export default GexPanel;
