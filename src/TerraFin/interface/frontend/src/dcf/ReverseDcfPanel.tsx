import React from 'react';
import ProjectedFcfChart from '../stock/components/ProjectedFcfChart';
import { ReverseDcfPayload } from './types';

const fmtCurrency = (value: number | null | undefined, digits = 2) =>
  typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : '--';

const fmtPct = (value: number | null | undefined) =>
  typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : '--';

const responsiveMetricGridStyle = (minWidth: number): React.CSSProperties => ({
  display: 'grid',
  gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${minWidth}px), 1fr))`,
  gap: 10,
});

const ReverseDcfPanel: React.FC<{
  payload: ReverseDcfPayload | null;
  loading?: boolean;
  error?: string | null;
}> = ({ payload, loading = false, error = null }) => {
  if (loading) {
    return <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Estimating implied growth...</div>;
  }

  if (error) {
    return <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-down)' }}>Failed to load reverse DCF: {error}</div>;
  }

  if (!payload) {
    return <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Run reverse DCF to estimate the market-implied growth rate.</div>;
  }

  const showBanner = payload.status !== 'ready' || payload.warnings.length > 0 || payload.dataQuality?.mode !== 'live';

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      {showBanner ? (
        <div
          style={{
            border: '1px solid var(--tf-amber)',
            background: 'var(--tf-bg-elevated)',
            color: 'var(--tf-amber)',
            borderRadius: 'var(--tf-radius)',
            padding: '10px 12px',
            fontSize: "var(--tf-fs-base)",
            lineHeight: 1.5,
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            {payload.status === 'ready' ? `Data quality: ${payload.dataQuality?.mode || 'mixed'}` : 'Reverse DCF needs better inputs'}
          </div>
          {(payload.warnings.length ? payload.warnings : ['This model is using fallback assumptions.']).map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}

      <div style={responsiveMetricGridStyle(150)}>
        <MetricCard label="Implied Growth" value={fmtPct(payload.impliedGrowthPct)} tone="var(--tf-text)" />
        <MetricCard label="Current Price" value={fmtCurrency(payload.currentPrice)} tone="var(--tf-text)" />
        <MetricCard label="FCF / Share" value={fmtCurrency(payload.baseCashFlowPerShare, 4)} tone="var(--tf-text)" />
        <MetricCard label="P / FCF" value={fmtCurrency(payload.priceToCashFlowMultiple)} tone="var(--tf-muted)" />
      </div>

      <div style={responsiveMetricGridStyle(150)}>
        <MetricCard label="Projection Years" value={`${payload.projectionYears}`} tone="var(--tf-text)" />
        <MetricCard label="Growth Profile" value={payload.growthProfile.label} tone="var(--tf-text)" />
        <MetricCard label="Terminal Growth" value={fmtPct(payload.terminalGrowthPct)} tone="var(--tf-text)" />
        <MetricCard label="Terminal Discount" value={fmtPct(payload.terminalDiscountRatePct)} tone="var(--tf-text)" />
      </div>

      <div style={responsiveMetricGridStyle(170)}>
        <MetricCard label="Model Price" value={fmtCurrency(payload.modelPrice)} tone="var(--tf-text)" />
        <MetricCard label="Terminal Value" value={fmtCurrency(payload.terminalValue)} tone="var(--tf-text)" />
        <MetricCard
          label="Terminal PV / Price"
          value={fmtPct(payload.terminalPresentValueWeightPct)}
          tone="var(--tf-muted)"
        />
      </div>

      <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)', lineHeight: 1.55 }}>
        TerraFin solves for the starting FCF growth rate that makes discounted cash flow equal the current price, then
        fades that growth toward a {fmtPct(payload.terminalGrowthPct)} terminal rate over {payload.projectionYears} years
        using the {payload.growthProfile.label.toLowerCase()} path.
      </div>

      {payload.projectedCashFlows.length > 0 ? (
        <div style={{ overflowX: 'auto', border: '1px solid var(--tf-border)', borderRadius: 'var(--tf-radius)' }}>
          <table style={{ width: '100%', minWidth: 520, borderCollapse: 'collapse', fontSize: "var(--tf-fs-base)", background: 'var(--tf-bg-elevated)', fontFamily: 'var(--tf-mono)' }}>
            <thead>
              <tr>
                <th style={thStyle}>Year</th>
                <th style={thStyle}>Growth</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Cash Flow</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Discount Rate</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Present Value</th>
              </tr>
            </thead>
            <tbody>
              {payload.projectedCashFlows.map((point) => (
                <tr key={point.forecastDate}>
                  <td style={tdStyle}>{point.forecastDate.slice(0, 10)}</td>
                  <td style={tdStyle}>{point.growthPct.toFixed(2)}%</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{point.cashFlowPerShare.toFixed(4)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{point.discountRatePct.toFixed(2)}%</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{point.presentValue.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {payload.projectedCashFlows.length > 0 ? (
        <ProjectedFcfChart
          projections={payload.projectedCashFlows}
          title={`Projected FCF / Share — ${payload.symbol} (implied schedule)`}
        />
      ) : null}
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string; tone: string }> = ({ label, value, tone }) => (
  <div
    style={{
      border: '1px solid var(--tf-border)',
      borderRadius: 'var(--tf-radius)',
      padding: '10px 12px',
      background: 'var(--tf-bg-elevated)',
    }}
  >
    <div style={{ fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)' }}>{label}</div>
    <div style={{ marginTop: 4, fontSize: "var(--tf-fs-lg)", fontWeight: 700, color: tone, lineHeight: 1.25, overflowWrap: 'anywhere', fontFamily: 'var(--tf-mono)' }}>
      {value}
    </div>
  </div>
);

const thStyle: React.CSSProperties = {
  padding: '7px 8px',
  borderBottom: '1px solid var(--tf-border)',
  textAlign: 'left',
  fontSize: "var(--tf-fs-xs)",
  color: 'var(--tf-muted)',
  background: 'var(--tf-bg-pane)',
};

const tdStyle: React.CSSProperties = {
  padding: '7px 8px',
  borderBottom: '1px solid var(--tf-border)',
  color: 'var(--tf-text)',
  fontFamily: 'var(--tf-mono)',
};

export default ReverseDcfPanel;
