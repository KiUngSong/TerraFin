import React from 'react';
import { ResponsiveSankey } from '@nivo/sankey';
import { useViewportTier } from '../../shared/responsive';
import type {
  IncomeSankeyMetric,
  IncomeSankeyPeriod,
  IncomeSankeyResponse,
} from '../useStockData';

// Color palette by node `kind`. Matches the surrounding card system (green
// for retained value, red for cost / leakage, slate-grey for raw revenue).
const COLOR_BY_KIND: Record<string, string> = {
  good: '#10b981',
  bad: '#ef4444',
  neutral: '#94a3b8',
};

// Lighter shade used for link strands. Mixing pure-saturated colors at link
// opacity makes the diagram look muddy — these tones keep contrast against
// the white background while staying readable when strands overlap.
const LINK_TINT_BY_KIND: Record<string, string> = {
  good: '#bbf7d0',
  bad: '#fecaca',
  neutral: '#cbd5e1',
};

// KPI summary row across the top of the card. Each entry is one canonical
// metric from the payload's `metrics` map; order matters because the user
// reads left-to-right.
const KPI_ORDER: Array<{ key: string; label: string }> = [
  { key: 'revenue', label: 'Revenue' },
  { key: 'grossProfit', label: 'Gross profit' },
  { key: 'costOfRevenue', label: 'Cost of sales' },
  { key: 'netIncome', label: 'Net income' },
];

const fmtUSD = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
};

const fmtPct = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
};

// Y/Y deltas: green when improvement is positive for the line item, red when
// negative. For cost-side items (lower is better), the polarity flips — a
// rising "cost of sales" Y/Y is a negative signal even though the number is
// up. The boolean signals which side of the ledger this metric sits on.
const yoyColor = (yoy: number | null | undefined, costSide = false): string => {
  if (typeof yoy !== 'number' || !Number.isFinite(yoy)) return 'var(--tf-muted)';
  const positive = yoy >= 0;
  const good = costSide ? !positive : positive;
  return good ? 'var(--tf-up)' : 'var(--tf-down)';
};

const COST_SIDE_METRICS = new Set([
  'costOfRevenue',
  'operatingExpense',
  'researchAndDevelopment',
  'sellingGeneralAdmin',
  'taxProvision',
]);

interface IncomeSankeyCardProps {
  payload: IncomeSankeyResponse | null;
  loading: boolean;
  error: string | null;
  period: IncomeSankeyPeriod;
  onPeriodChange: (period: IncomeSankeyPeriod) => void;
}

const PERIOD_OPTIONS: Array<{ value: IncomeSankeyPeriod; label: string }> = [
  { value: 'quarter', label: 'Quarterly' },
  { value: 'annual', label: 'Annual' },
];

const KpiCell: React.FC<{ label: string; metric: IncomeSankeyMetric | undefined; metricKey: string }> = ({
  label,
  metric,
  metricKey,
}) => {
  const value = metric?.value ?? null;
  const yoy = metric?.yoyPct ?? null;
  const costSide = COST_SIDE_METRICS.has(metricKey);
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
        <span style={{ fontSize: "var(--tf-fs-lg)", fontWeight: 700, color: 'var(--tf-text-strong)' }}>{fmtUSD(value)}</span>
        <span style={{ fontSize: "var(--tf-fs-base)", fontWeight: 600, color: yoyColor(yoy, costSide) }}>
          {fmtPct(yoy)} Y/Y
        </span>
      </div>
    </div>
  );
};

const PeriodToggle: React.FC<{
  period: IncomeSankeyPeriod;
  onChange: (period: IncomeSankeyPeriod) => void;
}> = ({ period, onChange }) => (
  <div
    style={{
      display: 'inline-flex',
      border: '1px solid var(--tf-border)',
      borderRadius: 'var(--tf-radius)',
      overflow: 'hidden',
      background: 'var(--tf-bg-elevated)',
    }}
  >
    {PERIOD_OPTIONS.map((opt) => {
      const active = opt.value === period;
      return (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          style={{
            padding: '6px 14px',
            background: active ? 'var(--tf-amber)' : 'transparent',
            color: active ? 'var(--tf-bg)' : 'var(--tf-muted)',
            border: 'none',
            fontSize: "var(--tf-fs-xs)",
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'background 120ms ease',
          }}
        >
          {opt.label}
        </button>
      );
    })}
  </div>
);

// Distinguishing kind suffix appended to node labels. Removes the WCAG 1.4.1
// color-only-signaling failure (deuteranopia maps green/red to ~same hue) and
// is also useful on the desktop tooltip — "Cost" beats inferring meaning from
// a red strand.
const KIND_TAG: Record<string, string> = {
  good: '↑ Margin',
  bad: '↓ Cost',
  neutral: '',
};

const IncomeSankeyCard: React.FC<IncomeSankeyCardProps> = ({
  payload,
  loading,
  error,
  period,
  onPeriodChange,
}) => {
  const { isMobile } = useViewportTier();
  // On mobile the card container is ~320-400px wide. A Sankey with 9+ nodes
  // and outside labels can't physically fit — clamping it produces overlapping
  // labels and a 30px-tall diagram strand. We render the diagram at a fixed
  // 880px width and let the user pan horizontally. `touch-action: pan-x`
  // tells iOS/Android to commit the gesture to horizontal scroll, avoiding
  // the page-scroll fight. Inside labels reclaim the gutter that outside
  // labels would consume on the narrower mobile canvas.
  const MOBILE_DIAGRAM_WIDTH = 880;
  const sankeyMargin = isMobile
    ? { top: 12, right: 16, bottom: 12, left: 16 }
    : { top: 12, right: 220, bottom: 12, left: 200 };
  const labelPosition: 'inside' | 'outside' = isMobile ? 'inside' : 'outside';
  // Nivo wants strictly positive link values; backend already guards but
  // belt-and-suspenders here in case a future field gets surfaced negative.
  const sankeyData = React.useMemo(() => {
    if (!payload) return null;
    const nodes = payload.nodes.map((n) => ({
      id: n.id,
      nodeColor: COLOR_BY_KIND[n.kind] ?? COLOR_BY_KIND.neutral,
      label: n.label,
      value: n.value,
      yoyPct: n.yoyPct,
      kind: n.kind,
    }));
    const links = payload.links
      .filter((l) => typeof l.value === 'number' && l.value > 0)
      .map((l) => ({
        source: l.source,
        target: l.target,
        value: l.value,
      }));
    return { nodes, links };
  }, [payload]);

  // Clean name lookup for tooltips. Nivo's `label` callback (below) injects
  // the formatted value into the on-diagram label, but the same string then
  // bleeds into `link.source.label` / `link.target.label`. The lookup map
  // lets the tooltip render the bare node name without the value string.
  const cleanLabelById = React.useMemo(() => {
    const map: Record<string, string> = {};
    if (payload) {
      for (const n of payload.nodes) map[n.id] = n.label;
    }
    return map;
  }, [payload]);

  const headerRight = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      {payload?.asOf ? (
        <span style={{ fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)', fontWeight: 500 }}>
          {payload.period === 'quarter' ? 'Period' : 'FY'} ending {payload.asOf}
          {payload.priorAsOf ? ` · vs ${payload.priorAsOf}` : ''}
        </span>
      ) : null}
      <div style={{ flexShrink: 0 }}>
        <PeriodToggle period={period} onChange={onPeriodChange} />
      </div>
    </div>
  );

  if (error) {
    return (
      <div style={cardStyle}>
        <div style={cardHeaderStyle}>
          <div>
            <div style={cardTitleStyle}>Income Statement Flow</div>
            <div style={cardSubtitleStyle}>Revenue → margin → earnings, Y/Y vs same period prior year</div>
          </div>
          {headerRight}
        </div>
        <div style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--tf-down)', fontSize: "var(--tf-fs-base)" }}>
          {error.includes('404') || error.includes('422')
            ? 'Income statement data is not available for this ticker.'
            : `Failed to load income statement: ${error}`}
        </div>
      </div>
    );
  }

  if (loading && !payload) {
    return (
      <div style={cardStyle}>
        <div style={cardHeaderStyle}>
          <div>
            <div style={cardTitleStyle}>Income Statement Flow</div>
            <div style={cardSubtitleStyle}>Revenue → margin → earnings, Y/Y vs same period prior year</div>
          </div>
          {headerRight}
        </div>
        <div style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--tf-muted)', fontSize: "var(--tf-fs-base)" }}>
          Loading income statement...
        </div>
      </div>
    );
  }

  if (!payload || !sankeyData) return null;

  return (
    <div style={cardStyle}>
      <div style={cardHeaderStyle}>
        <div>
          <div style={cardTitleStyle}>Income Statement Flow</div>
          <div style={cardSubtitleStyle}>Revenue → margin → earnings, Y/Y vs same period prior year</div>
        </div>
        {headerRight}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 16,
          padding: '0 4px 16px',
          borderBottom: '1px solid var(--tf-border)',
          marginBottom: 12,
        }}
      >
        {KPI_ORDER.map((kpi) => (
          <KpiCell
            key={kpi.key}
            label={kpi.label}
            metric={payload.metrics[kpi.key]}
            metricKey={kpi.key}
          />
        ))}
      </div>

      <div
        role="img"
        aria-label={(() => {
          const rev = payload.metrics.revenue?.value;
          const ni = payload.metrics.netIncome?.value;
          const revStr = fmtUSD(rev ?? null);
          const niStr = fmtUSD(ni ?? null);
          const periodLabel = payload.period === 'quarter' ? 'quarter' : 'fiscal year';
          return `Income statement flow for ${payload.ticker}, ${periodLabel} ending ${payload.asOf}. Revenue ${revStr}, net income ${niStr}.`;
        })()}
        style={{
          height: 420,
          opacity: loading ? 0.6 : 1,
          transition: 'opacity 150ms ease',
          overflowX: isMobile ? 'auto' : 'visible',
          overflowY: 'hidden',
          // Commit horizontal swipes inside the diagram to pan-only so they
          // don't fight the page's vertical scroll on mobile.
          touchAction: isMobile ? 'pan-x' : undefined,
          WebkitOverflowScrolling: 'touch',
        }}
      >
        <div style={{ width: isMobile ? MOBILE_DIAGRAM_WIDTH : '100%', height: '100%' }}>
        <ResponsiveSankey
          data={sankeyData}
          // Desktop: wide horizontal margins reserve room for outside labels.
          // Mobile: tight margins because labels render INSIDE the nodes.
          margin={sankeyMargin}
          align="justify"
          colors={(n: { nodeColor?: string }) => n.nodeColor ?? '#94a3b8'}
          nodeOpacity={1}
          nodeHoverOthersOpacity={0.45}
          nodeThickness={14}
          nodeSpacing={20}
          nodeBorderWidth={0}
          // Link color follows the TARGET node's kind so cost streams render
          // red and value-retention streams render green regardless of source.
          linkOpacity={0.55}
          linkHoverOthersOpacity={0.12}
          linkContract={3}
          enableLinkGradient={false}
          linkBlendMode="normal"
          // @ts-expect-error nivo's `colors` for links accepts a function but the
          // type generic is permissive; cast is safer than rewriting the union.
          linkColor={(link: { target: { kind?: string } }) =>
            LINK_TINT_BY_KIND[link.target?.kind ?? 'neutral'] ?? LINK_TINT_BY_KIND.neutral
          }
          labelPosition={labelPosition}
          labelOrientation="horizontal"
          labelPadding={10}
          // Label format = "<name> · <value>". Y/Y delta lives in the tooltip
          // to keep the on-diagram label short enough to render without
          // clipping against the card edge.
          label={(n: { label?: string; value?: number }) => {
            const v = fmtUSD(n.value ?? null);
            return `${n.label} · ${v}`;
          }}
          labelTextColor={{ from: 'color', modifiers: [['darker', 1.6]] }}
          // Tooltip carries only the info NOT already on the on-diagram label
          // (the Y/Y delta + kind tag). Repeating the value would just clutter
          // the popup since the user can read it off the label two pixels away.
          nodeTooltip={({ node }: { node: { label?: string; yoyPct?: number | null; kind?: string } }) => {
            const yoy = node.yoyPct;
            const showYoY = typeof yoy === 'number' && Number.isFinite(yoy);
            const tag = KIND_TAG[node.kind ?? 'neutral'];
            return (
              <div style={tooltipStyle}>
                <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>{node.label}</span>
                  {tag ? <span style={{ fontSize: "var(--tf-fs-micro)", fontWeight: 600, opacity: 0.75 }}>{tag}</span> : null}
                </div>
                {showYoY ? (
                  <div style={{ color: yoy! >= 0 ? 'var(--tf-up)' : 'var(--tf-down)', marginTop: 2 }}>
                    {fmtPct(yoy)} Y/Y
                  </div>
                ) : null}
              </div>
            );
          }}
          linkTooltip={({ link }: { link: { source: { id?: string }; target: { id?: string }; value: number } }) => {
            const sourceName = cleanLabelById[link.source.id ?? ''] ?? link.source.id ?? '';
            const targetName = cleanLabelById[link.target.id ?? ''] ?? link.target.id ?? '';
            return (
              <div style={tooltipStyle}>
                <div style={{ fontWeight: 600 }}>
                  {sourceName} → {targetName}
                </div>
                <div style={{ marginTop: 2 }}>{fmtUSD(link.value)}</div>
              </div>
            );
          }}
          animate={false}
          theme={{
            text: { fontSize: "var(--tf-fs-xs)", fontFamily: 'inherit', fontWeight: 500 },
            tooltip: { container: { fontSize: "var(--tf-fs-base)" } },
          }}
        />
        </div>
      </div>
    </div>
  );
};

const cardStyle: React.CSSProperties = {
  background: 'var(--tf-bg-pane)',
  border: '1px solid var(--tf-border)',
  borderRadius: 'var(--tf-radius)',
  padding: 16,
};

const cardHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: 12,
  marginBottom: 14,
  flexWrap: 'wrap',
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: "var(--tf-fs-md)",
  fontWeight: 700,
  color: 'var(--tf-text-strong)',
};

const cardSubtitleStyle: React.CSSProperties = {
  fontSize: "var(--tf-fs-xs)",
  color: 'var(--tf-muted)',
  marginTop: 2,
};

const tooltipStyle: React.CSSProperties = {
  background: 'var(--tf-bg-elevated)',
  color: 'var(--tf-text)',
  border: '1px solid var(--tf-border)',
  padding: '6px 10px',
  borderRadius: 'var(--tf-radius)',
  fontSize: "var(--tf-fs-base)",
  lineHeight: 1.45,
  whiteSpace: 'nowrap',
};

export default IncomeSankeyCard;
