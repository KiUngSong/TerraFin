import React from 'react';
import type { FcfHistoryResponse } from '../useStockData';

const POSITIVE_COLOR = '#059669';
const NEGATIVE_COLOR = '#dc2626';
const TTM_COLOR = '#1d4ed8';
const AXIS_COLOR = '#94a3b8';
const GRID_COLOR = '#e2e8f0';
const LABEL_COLOR = '#475569';

const THREE_YEAR_CHIP_COLOR = '#0f766e';

const MIN_VIEWBOX_HEIGHT = 180;
const PADDING_TOP = 18;
const PADDING_BOTTOM = 42;
const PADDING_LEFT = 56;
// Right gutter holds the TTM callout pill + 3yr Avg label.
const PADDING_RIGHT = 90;

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
    const trimmed = scaled.toFixed(digits).replace(/\.0$/, '');
    return `${value < 0 ? '-' : ''}$${trimmed}K`;
  }
  const digits = abs >= 100 ? 0 : abs >= 1 ? 1 : 2;
  return `${value < 0 ? '-' : ''}$${abs.toFixed(digits)}`;
};

const FcfHistoryChart: React.FC<{
  payload: FcfHistoryResponse | null;
  loading?: boolean;
  error?: string | null;
}> = ({ payload, loading = false, error = null }) => {
  const [viewWidth, setViewWidth] = React.useState(600);
  const [viewHeight, setViewHeight] = React.useState(MIN_VIEWBOX_HEIGHT);
  const [hover, setHover] = React.useState<{ x: number; y: number; label: string; value: string; accent: string } | null>(null);
  const svgWrapperRef = React.useRef<HTMLDivElement | null>(null);
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  // Tooltip sits right next to the cursor (diagonal offset). Flips left/up
  // only when it would clip the wrapper edge. Set on enter, not move, to
  // avoid per-pixel flicker as the cursor slides across a bar.
  const handleHover = React.useCallback(
    (event: React.MouseEvent, label: string, value: string, accent: string) => {
      const wrapper = svgWrapperRef.current;
      if (!wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      const TIP_W = 110;
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
    const wrapper = svgWrapperRef.current;
    if (!wrapper || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const width = entry.contentRect.width;
      const height = entry.contentRect.height;
      if (width > 0) setViewWidth(width);
      if (height > 0) setViewHeight(Math.max(height, MIN_VIEWBOX_HEIGHT));
    });
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  if (loading) {
    return <div style={placeholderStyle}>Loading FCF history...</div>;
  }
  if (error) {
    return <div style={{ ...placeholderStyle, color: '#b91c1c' }}>Failed to load FCF: {error}</div>;
  }
  if (!payload) {
    return <div style={placeholderStyle}>No FCF data available.</div>;
  }

  const history = payload.history.filter(
    (row): row is { year: string; fcf: number | null; fcfPerShare: number } =>
      typeof row.fcfPerShare === 'number',
  );
  const ttm = typeof payload.ttmFcfPerShare === 'number' ? payload.ttmFcfPerShare : null;

  if (history.length === 0 && ttm === null && (payload.rollingTtm || []).length === 0) {
    return <div style={placeholderStyle}>No FCF data available.</div>;
  }

  const candidates = payload.candidates;
  const threeYearAvg = typeof candidates.threeYearAvg === 'number' ? candidates.threeYearAvg : null;
  const autoSelectedKey = ((): 'threeYearAvg' | 'latestAnnual' | 'ttm' | null => {
    switch (payload.autoSelectedSource) {
      case '3yr_avg':
        return 'threeYearAvg';
      case 'annual':
        return 'latestAnnual';
      case 'quarterly_ttm':
        return 'ttm';
      default:
        return null;
    }
  })();

  const values: number[] = [
    ...history.map((row) => row.fcfPerShare),
    ...(ttm !== null ? [ttm] : []),
  ];
  // Only force-include 0 when the data actually crosses sign. For all-positive
  // series, anchoring to 0 wastes vertical space and compresses bar variation.
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
  const chartRight = Math.max(viewWidth - PADDING_RIGHT, chartLeft + 120);
  const chartWidth = chartRight - chartLeft;

  const yToPx = (value: number): number => {
    if (yMax === yMin) return chartBottom;
    return chartBottom - ((value - yMin) / (yMax - yMin)) * chartHeight;
  };
  // When all data is positive (yMin > 0) yToPx(0) lands below chartBottom.
  // Cap the bar baseline at chartBottom so bars never spill into the year-label
  // area at the bottom of the SVG.
  const zeroYRaw = yToPx(0);
  const barBaseline = Math.min(Math.max(zeroYRaw, chartTop), chartBottom);

  // One band per historical year. TTM lives in the right gutter (PADDING_RIGHT)
  // as a callout, not as its own band.
  const bandCount = Math.max(history.length, 1);
  const bandWidth = chartWidth / bandCount;
  const barWidth = Math.max(bandWidth * 0.62, 6);

  // Compute nice ticks but DO NOT extend the y-range to fit them — that would
  // add an empty tier above the data. Instead clip ticks that fall outside
  // [yMin, yMax]. This keeps the chart tight while still using round labels.
  const yTicks = niceTicks(yMin, yMax, 4).filter((t) => t >= yMin - 1e-6 && t <= yMax + 1e-6);

  return (
    <div ref={containerRef} style={wrapperStyle}>
      <div ref={svgWrapperRef} style={svgWrapperStyle}>
      <svg
        viewBox={`0 0 ${Math.max(viewWidth, chartLeft + 200)} ${viewHeight}`}
        width="100%"
        height="100%"
        role="img"
        aria-label="Historical free cash flow per share"
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
              x={chartLeft - 8}
              y={yToPx(tick) + 4}
              fontSize="11"
              fill={LABEL_COLOR}
              textAnchor="end"
            >
              {fmtAxisTick(tick)}
            </text>
          </g>
        ))}

        {history.map((row, index) => {
          const value = row.fcfPerShare as number;
          const cx = chartLeft + bandWidth * (index + 0.5);
          const barLeft = cx - barWidth / 2;
          const barTop = value >= 0 ? yToPx(value) : barBaseline;
          const barH = Math.abs(yToPx(value) - barBaseline);
          const color = value >= 0 ? POSITIVE_COLOR : NEGATIVE_COLOR;
          const isLatestAnnual = index === history.length - 1;
          const valueLabelY = value >= 0 ? barTop - 4 : barTop + barH + 12;
          return (
            <g
              key={`bar-${row.year || index}`}
              onMouseEnter={(e) => handleHover(e, row.year || `Y${index + 1}`, fmtPerShare(value), color)}
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
              {isLatestAnnual ? (
                <text
                  x={cx}
                  y={valueLabelY}
                  fontSize="11"
                  fill={color}
                  fontWeight={700}
                  textAnchor="middle"
                >
                  {fmtPerShare(value)}
                </text>
              ) : null}
              <text
                x={cx}
                y={viewHeight - 14}
                fontSize="11"
                fill={LABEL_COLOR}
                textAnchor="middle"
              >
                {row.year || ''}
              </text>
            </g>
          );
        })}

        {threeYearAvg !== null ? (
          (() => {
            const y = yToPx(threeYearAvg);
            const labelText = `3yr Avg ${fmtPerShare(threeYearAvg)}${autoSelectedKey === 'threeYearAvg' ? ' · Auto' : ''}`;
            return (
              <g
                onMouseEnter={(e) =>
                  handleHover(
                    e,
                    `3yr Avg${autoSelectedKey === 'threeYearAvg' ? ' (Auto)' : ''}`,
                    fmtPerShare(threeYearAvg),
                    THREE_YEAR_CHIP_COLOR,
                  )
                }
                onMouseLeave={clearHover}
                style={{ cursor: 'pointer' }}
              >
                <line
                  x1={chartLeft}
                  x2={chartRight}
                  y1={y}
                  y2={y}
                  stroke={THREE_YEAR_CHIP_COLOR}
                  strokeWidth={1.5}
                  strokeDasharray="6 3"
                />
                {/* Label sits inside plot just above the line, anchored to the
                  * left so it doesn't collide with the TTM callout in the right
                  * gutter. White stroke (paint-order=stroke) gives a halo so the
                  * text stays legible over any bars it crosses. */}
                <text
                  x={chartLeft + 8}
                  y={y - 4}
                  fontSize="10"
                  fill={THREE_YEAR_CHIP_COLOR}
                  fontWeight={700}
                  textAnchor="start"
                  stroke="#ffffff"
                  strokeWidth={3}
                  paintOrder="stroke"
                  style={{ pointerEvents: 'none' }}
                >
                  {labelText}
                </text>
              </g>
            );
          })()
        ) : null}

        {ttm !== null ? (
          (() => {
            // TTM right-gutter callout: dashed leader from the last annual bar
            // to a tightly-padded pill in the right gutter.
            const lastBarCx = chartLeft + bandWidth * (history.length - 0.5);
            const cy = yToPx(ttm);
            const pillText = `TTM ${fmtPerShare(ttm)}`;
            const charW = 5.4;
            const padX = 7;
            const pillW = Math.min(pillText.length * charW + padX * 2, PADDING_RIGHT - 14);
            const pillH = 18;
            const pillX = chartRight + 6;
            const pillCenterX = pillX + pillW / 2;
            return (
              <g
                onMouseEnter={(e) => handleHover(e, 'TTM', fmtPerShare(ttm), TTM_COLOR)}
                onMouseLeave={clearHover}
                style={{ cursor: 'pointer' }}
              >
                <line
                  x1={lastBarCx + barWidth / 2}
                  x2={pillX}
                  y1={cy}
                  y2={cy}
                  stroke={TTM_COLOR}
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  opacity={0.7}
                />
                <rect
                  x={pillX}
                  y={cy - pillH / 2}
                  width={pillW}
                  height={pillH}
                  rx={pillH / 2}
                  fill="#eff6ff"
                  stroke={TTM_COLOR}
                  strokeWidth={1.2}
                />
                <text
                  x={pillCenterX}
                  y={cy}
                  fontSize="10"
                  fill={TTM_COLOR}
                  fontWeight={700}
                  textAnchor="middle"
                  dominantBaseline="central"
                >
                  {pillText}
                </text>
              </g>
            );
          })()
        ) : null}
      </svg>
      {hover ? (
        <div style={tooltipStyle(hover.x, hover.y, hover.accent)}>
          <span style={tooltipDotStyle(hover.accent)} />
          <span style={tooltipLabelStyle}>{hover.label}</span>
          <span>{hover.value}</span>
        </div>
      ) : null}
      </div>

      <div style={legendRowStyle}>
        <LegendSwatch color={POSITIVE_COLOR} label="Positive" />
        <LegendSwatch color={NEGATIVE_COLOR} label="Negative" />
        <span style={ttmLegendPillStyle}>TTM</span>
        {threeYearAvg !== null ? (
          <LegendSwatch
            color={THREE_YEAR_CHIP_COLOR}
            label={`3yr Avg${autoSelectedKey === 'threeYearAvg' ? ' (Auto)' : ''}`}
            outlined
            dashed
          />
        ) : null}
      </div>
    </div>
  );
};

function formatCompact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1000) {
    const scaled = abs / 1000;
    const digits = scaled >= 10 ? 0 : 1;
    return `${sign}${scaled.toFixed(digits).replace(/\.0$/, '')}K`;
  }
  if (abs >= 1) return `${sign}${abs.toFixed(2)}`;
  return `${sign}${abs.toFixed(3)}`;
}

function shortQuarterLabel(asOf: string | null): string {
  if (!asOf) return 'TTM';
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(asOf);
  if (!match) return 'TTM';
  const year = match[1].slice(2);
  const month = parseInt(match[2], 10);
  const quarter = Math.min(4, Math.max(1, Math.ceil(month / 3)));
  return `${year}Q${quarter}`;
}

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

const LegendSwatch: React.FC<{
  color: string;
  label: string;
  outlined?: boolean;
  dashed?: boolean;
}> = ({ color, label, outlined = false, dashed = false }) => (
  <span style={legendItemStyle}>
    <span
      style={{
        display: 'inline-block',
        width: 14,
        height: dashed ? 0 : 12,
        borderRadius: 3,
        background: outlined ? 'transparent' : color,
        border: dashed
          ? undefined
          : outlined
          ? `2px dashed ${color}`
          : `1px solid ${color}`,
        borderTop: dashed ? `2px dashed ${color}` : undefined,
      }}
    />
    <span>{label}</span>
  </span>
);

const wrapperStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  flex: 1,
  minHeight: 0,
};

const svgWrapperStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  width: '100%',
  position: 'relative',
};

// Mirrors the right-gutter TTM callout pill (rounded blue-on-white) so the
// legend swatch reads as the same visual element, not a separate concept.
const ttmLegendPillStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 9px',
  borderRadius: 999,
  background: '#eff6ff',
  color: TTM_COLOR,
  border: `1px solid ${TTM_COLOR}`,
  fontSize: 10,
  fontWeight: 700,
  lineHeight: 1.4,
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

const svgStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
  display: 'block',
};

const placeholderStyle: React.CSSProperties = {
  fontSize: 13,
  color: '#64748b',
  padding: '20px 4px',
};

const legendRowStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 14,
  alignItems: 'center',
  fontSize: 11,
  color: '#475569',
};

const legendItemStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
};


export default FcfHistoryChart;
