import React from 'react';
import type { DcfProjectionPoint } from '../../dcf/types';

const POSITIVE_COLOR = '#059669';
const NEGATIVE_COLOR = '#dc2626';
const AXIS_COLOR = '#94a3b8';
const GRID_COLOR = '#e2e8f0';
const LABEL_COLOR = '#475569';

const MIN_VIEWBOX_HEIGHT = 140;
const PADDING_TOP = 18;
const PADDING_BOTTOM = 36;
const PADDING_LEFT = 56;
const PADDING_RIGHT = 16;

const fmtPerShare = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
  const abs = Math.abs(value);
  if (abs === 0) return '$0';
  const digits = abs >= 100 ? 0 : abs >= 1 ? 2 : 3;
  return `${value < 0 ? '-' : ''}$${abs.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
};

const fmtAxisTick = (value: number): string => {
  if (!Number.isFinite(value)) return '';
  const abs = Math.abs(value);
  if (abs === 0) return '$0';
  if (abs >= 1000) {
    const scaled = abs / 1000;
    const digits = scaled >= 10 ? 0 : 1;
    return `${value < 0 ? '-' : ''}$${scaled.toFixed(digits).replace(/\.0$/, '')}K`;
  }
  const digits = abs >= 100 ? 0 : abs >= 1 ? 1 : 2;
  return `${value < 0 ? '-' : ''}$${abs.toFixed(digits)}`;
};

function niceTicks(min: number, max: number, targetCount: number): number[] {
  if (min === max) return [min];
  const range = max - min;
  const rough = range / targetCount;
  const pow = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / pow;
  let step: number;
  if (norm < 1.5) step = 1 * pow;
  else if (norm < 3) step = 2 * pow;
  else if (norm < 7) step = 5 * pow;
  else step = 10 * pow;
  const niceMin = Math.floor(min / step) * step;
  const niceMax = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = niceMin; v <= niceMax + step * 0.001; v += step) {
    ticks.push(Math.round(v / step) * step);
  }
  return ticks;
}

interface ProjectedFcfChartProps {
  /** Single-scenario projection (used when scenarios prop is absent). */
  projections?: DcfProjectionPoint[];
  /** Multi-scenario projection set. When provided, renders bear/bull as a
   *  shaded band and base as the primary series (line or bars). */
  scenarios?: {
    bear?: DcfProjectionPoint[];
    base?: DcfProjectionPoint[];
    bull?: DcfProjectionPoint[];
  };
  title?: string;
}

const BAND_FILL = 'rgba(29, 78, 216, 0.12)';
const BASE_LINE_COLOR = '#1d4ed8';
const BEAR_LINE_COLOR = '#dc2626';
const BULL_LINE_COLOR = '#059669';
const LINE_HORIZON_THRESHOLD = 15;

const ProjectedFcfChart: React.FC<ProjectedFcfChartProps> = ({
  projections,
  scenarios,
  title = 'Projected FCF / Share',
}) => {
  const basePointsRaw =
    (scenarios?.base && scenarios.base.length > 0 ? scenarios.base : projections) || [];
  const bearPointsRaw = scenarios?.bear || [];
  const bullPointsRaw = scenarios?.bull || [];
  const [viewWidth, setViewWidth] = React.useState(600);
  const [viewHeight, setViewHeight] = React.useState(MIN_VIEWBOX_HEIGHT);
  const [hover, setHover] = React.useState<{ x: number; y: number; label: string; value: string; accent: string } | null>(null);
  const wrapperRef = React.useRef<HTMLDivElement | null>(null);

  // Tooltip right next to the cursor; flip when near edges.
  const handleHover = React.useCallback(
    (event: React.MouseEvent, label: string, value: string, accent: string) => {
      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      const TIP_W = 200;
      const TIP_H = 26;
      const OFFSET = 10;
      const cursorX = event.clientX - rect.left;
      const cursorY = event.clientY - rect.top;
      const wouldClipRight = cursorX + OFFSET + TIP_W > rect.width - 4;
      const wouldClipBottom = cursorY + OFFSET + TIP_H > rect.height - 4;
      const x = wouldClipRight ? Math.max(cursorX - OFFSET - TIP_W, 4) : cursorX + OFFSET;
      const y = wouldClipBottom ? Math.max(cursorY - OFFSET - TIP_H, 4) : cursorY + OFFSET;
      setHover({ x, y, label, value, accent });
    },
    [],
  );
  const clearHover = React.useCallback(() => setHover(null), []);

  React.useLayoutEffect(() => {
    const el = wrapperRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const obs = new ResizeObserver((entries) => {
      const e = entries[0];
      if (!e) return;
      if (e.contentRect.width > 0) setViewWidth(e.contentRect.width);
      if (e.contentRect.height > 0) setViewHeight(Math.max(e.contentRect.height, MIN_VIEWBOX_HEIGHT));
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const finite = (p: DcfProjectionPoint) =>
    typeof p.cashFlowPerShare === 'number' && Number.isFinite(p.cashFlowPerShare);
  const valid = basePointsRaw.filter(finite);
  const bearValid = bearPointsRaw.filter(finite);
  const bullValid = bullPointsRaw.filter(finite);
  const hasScenarios = bearValid.length > 0 && bullValid.length > 0;
  // Switch to line mode only at long horizons. With scenarios + short horizon
  // we still use bars (cleaner read), and overlay bear/bull as line markers.
  const useLineMode = valid.length > LINE_HORIZON_THRESHOLD;
  if (valid.length === 0) return null;

  const values = [
    ...valid.map((p) => p.cashFlowPerShare),
    ...bearValid.map((p) => p.cashFlowPerShare),
    ...bullValid.map((p) => p.cashFlowPerShare),
  ];
  // Tighten y-range so bear/base/bull divergence is visible. Only force-include
  // 0 when the data crosses sign — otherwise we squash actual variation.
  const dataMax = Math.max(...values);
  const dataMin = Math.min(...values);
  const includeZero = dataMin < 0 && dataMax > 0;
  const rawMax = includeZero ? Math.max(dataMax, 0) : dataMax;
  const rawMin = includeZero ? Math.min(dataMin, 0) : dataMin;
  const span = Math.max(rawMax - rawMin, Math.abs(rawMax) || Math.abs(rawMin) || 1);
  const headroom = span * 0.05;
  const yMax = rawMax + headroom;
  const yMin = includeZero ? rawMin - headroom : Math.max(rawMin - headroom, 0);

  const chartTop = PADDING_TOP;
  const chartBottom = viewHeight - PADDING_BOTTOM;
  const chartHeight = chartBottom - chartTop;
  const chartLeft = PADDING_LEFT;
  const chartRight = Math.max(viewWidth - PADDING_RIGHT, chartLeft + 80);
  const chartWidth = chartRight - chartLeft;

  // Tight y-range; clip ticks rather than extending the range to fit them.
  const yTicks = niceTicks(yMin, yMax, 4).filter((t) => t >= yMin - 1e-6 && t <= yMax + 1e-6);

  const yToPx = (value: number): number => {
    if (yMax === yMin) return chartBottom;
    return chartBottom - ((value - yMin) / (yMax - yMin)) * chartHeight;
  };
  const zeroY = yToPx(0);
  // Cap bar baseline at chartBottom so positive-only data (where yMin > 0
  // pushes zeroY below the chart) doesn't cause bars to spill past the
  // x-axis label area.
  const barBaseline = Math.min(Math.max(zeroY, chartTop), chartBottom);

  const bandCount = valid.length;
  const bandWidth = chartWidth / bandCount;
  const barWidth = Math.max(bandWidth * 0.62, 6);

  return (
    <div style={containerStyle}>
      <div style={titleStyle}>{title}</div>
      <div ref={wrapperRef} style={wrapperStyle}>
        <svg
          viewBox={`0 0 ${Math.max(viewWidth, chartLeft + 120)} ${viewHeight}`}
          width="100%"
          height="100%"
          role="img"
          aria-label="Projected free cash flow per share"
          style={svgStyle}
        >
          {yTicks.map((tick) => (
            <g key={`tick-${tick}`}>
              <line
                x1={chartLeft}
                x2={chartRight}
                y1={yToPx(tick)}
                y2={yToPx(tick)}
                stroke={tick === 0 ? AXIS_COLOR : GRID_COLOR}
                strokeWidth={tick === 0 ? 1.5 : 1}
                strokeDasharray={tick === 0 ? undefined : '2 3'}
              />
              <text
                x={chartLeft - 6}
                y={yToPx(tick) + 4}
                fontSize="10"
                fill={LABEL_COLOR}
                textAnchor="end"
              >
                {fmtAxisTick(tick)}
              </text>
            </g>
          ))}

          {!useLineMode
            ? valid.map((p, idx) => {
                const value = p.cashFlowPerShare;
                const cx = chartLeft + bandWidth * (idx + 0.5);
                const barLeft = cx - barWidth / 2;
                const barTop = value >= 0 ? yToPx(value) : barBaseline;
                const barH = Math.abs(yToPx(value) - barBaseline);
                const color = value >= 0 ? POSITIVE_COLOR : NEGATIVE_COLOR;
                const yearLabel = p.forecastDate ? p.forecastDate.slice(0, 4) : `Y${idx + 1}`;
                const bearVal = bearValid[idx]?.cashFlowPerShare;
                const bullVal = bullValid[idx]?.cashFlowPerShare;
                const showWhisker =
                  hasScenarios && typeof bearVal === 'number' && typeof bullVal === 'number';
                const tipLabel = showWhisker
                  ? `${yearLabel} · bear ${fmtPerShare(bearVal)} ↔ bull ${fmtPerShare(bullVal)}`
                  : yearLabel;
                return (
                  <g
                    key={`proj-${p.yearOffset}`}
                    onMouseEnter={(e) => handleHover(e, tipLabel, fmtPerShare(value), color)}
                    onMouseLeave={clearHover}
                    style={{ cursor: 'pointer' }}
                  >
                    <rect
                      x={barLeft}
                      y={barTop}
                      width={barWidth}
                      height={Math.max(barH, 1)}
                      fill={color}
                      opacity={0.85}
                      rx={2}
                    />
                    {showWhisker ? (
                      <g pointerEvents="none">
                        <line
                          x1={cx}
                          x2={cx}
                          y1={yToPx(bullVal)}
                          y2={yToPx(bearVal)}
                          stroke="#0f172a"
                          strokeWidth={1.2}
                          opacity={0.85}
                        />
                        <line
                          x1={cx - 4}
                          x2={cx + 4}
                          y1={yToPx(bullVal)}
                          y2={yToPx(bullVal)}
                          stroke={BULL_LINE_COLOR}
                          strokeWidth={2}
                        />
                        <line
                          x1={cx - 4}
                          x2={cx + 4}
                          y1={yToPx(bearVal)}
                          y2={yToPx(bearVal)}
                          stroke={BEAR_LINE_COLOR}
                          strokeWidth={2}
                        />
                      </g>
                    ) : null}
                    <text
                      x={cx}
                      y={viewHeight - 10}
                      fontSize="10"
                      fill={LABEL_COLOR}
                      textAnchor="middle"
                    >
                      {yearLabel}
                    </text>
                  </g>
                );
              })
            : (() => {
                // Line + (optional) shaded band mode. Used when there are
                // multi-scenario projections or horizon > 10.
                const xFor = (idx: number) => chartLeft + bandWidth * (idx + 0.5);
                const basePath = valid
                  .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${xFor(idx)} ${yToPx(p.cashFlowPerShare)}`)
                  .join(' ');
                const bandPath = hasScenarios
                  ? `${bullValid
                      .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${xFor(idx)} ${yToPx(p.cashFlowPerShare)}`)
                      .join(' ')} ${bearValid
                      .slice()
                      .reverse()
                      .map(
                        (p, i) =>
                          `L ${xFor(bearValid.length - 1 - i)} ${yToPx(p.cashFlowPerShare)}`,
                      )
                      .join(' ')} Z`
                  : null;
                const bearPath = hasScenarios
                  ? bearValid
                      .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${xFor(idx)} ${yToPx(p.cashFlowPerShare)}`)
                      .join(' ')
                  : null;
                const bullPath = hasScenarios
                  ? bullValid
                      .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${xFor(idx)} ${yToPx(p.cashFlowPerShare)}`)
                      .join(' ')
                  : null;
                return (
                  <g>
                    {bandPath ? <path d={bandPath} fill={BAND_FILL} stroke="none" /> : null}
                    {bearPath ? (
                      <path d={bearPath} stroke={BEAR_LINE_COLOR} strokeWidth={1.2} strokeDasharray="4 3" fill="none" opacity={0.75} />
                    ) : null}
                    {bullPath ? (
                      <path d={bullPath} stroke={BULL_LINE_COLOR} strokeWidth={1.2} strokeDasharray="4 3" fill="none" opacity={0.75} />
                    ) : null}
                    <path d={basePath} stroke={BASE_LINE_COLOR} strokeWidth={2} fill="none" />
                    {valid.map((p, idx) => {
                      const x = xFor(idx);
                      const y = yToPx(p.cashFlowPerShare);
                      const isLast = idx === valid.length - 1;
                      const yearLabel = p.forecastDate ? p.forecastDate.slice(0, 4) : `Y${idx + 1}`;
                      return (
                        <g
                          key={`proj-${p.yearOffset}`}
                          onMouseEnter={(e) =>
                            handleHover(e, yearLabel, fmtPerShare(p.cashFlowPerShare), BASE_LINE_COLOR)
                          }
                          onMouseLeave={clearHover}
                          style={{ cursor: 'pointer' }}
                        >
                          <circle
                            cx={x}
                            cy={y}
                            r={isLast ? 4 : 2.5}
                            fill="#ffffff"
                            stroke={BASE_LINE_COLOR}
                            strokeWidth={1.5}
                          />
                          {idx === 0 || idx === valid.length - 1 || idx === Math.floor(valid.length / 2) ? (
                            <text
                              x={x}
                              y={viewHeight - 10}
                              fontSize="10"
                              fill={LABEL_COLOR}
                              textAnchor="middle"
                            >
                              {yearLabel}
                            </text>
                          ) : null}
                        </g>
                      );
                    })}
                  </g>
                );
              })()}
        </svg>
        {hover ? (
          <div style={tooltipStyle(hover.x, hover.y, hover.accent)}>
            <span style={tooltipDotStyle(hover.accent)} />
            <span style={tooltipLabelStyle}>{hover.label}</span>
            <span>{hover.value}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
};

const tooltipStyle = (x: number, y: number, _accent: string): React.CSSProperties => ({
  position: 'absolute',
  left: x,
  top: y,
  padding: '4px 9px',
  background: '#ffffff',
  color: '#0f172a',
  fontSize: 11,
  fontWeight: 700,
  borderRadius: 6,
  border: '1px solid #cbd5e1',
  pointerEvents: 'none',
  whiteSpace: 'nowrap',
  zIndex: 10,
  boxShadow: '0 2px 6px rgba(15, 23, 42, 0.12)',
  lineHeight: 1.3,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
});

const tooltipDotStyle = (accent: string): React.CSSProperties => ({
  display: 'inline-block',
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: accent,
});

const tooltipLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  color: '#64748b',
};

const containerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  marginTop: 12,
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: '10px 12px',
  background: '#f8fafc',
  minHeight: 0,
};

const titleStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#334155',
  letterSpacing: '0.02em',
};

const wrapperStyle: React.CSSProperties = {
  width: '100%',
  height: 160,
  minHeight: 0,
  position: 'relative',
};

const svgStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
  display: 'block',
};

export default ProjectedFcfChart;
