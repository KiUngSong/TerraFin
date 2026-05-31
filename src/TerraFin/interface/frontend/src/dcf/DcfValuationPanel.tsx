import React from 'react';
import { DcfScenario, DcfValuationPayload } from './types';

const SCENARIO_ORDER = ['bear', 'base', 'bull'];

const fmtCurrency = (value: number | null | undefined) =>
  typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '--';

const fmtPct = (value: number | null | undefined) =>
  typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : '--';

const responsiveGridStyle = (minWidth: number): React.CSSProperties => ({
  display: 'grid',
  gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${minWidth}px), 1fr))`,
  gap: 10,
});

function cellColor(upsidePct: number | null | undefined): string {
  if (typeof upsidePct !== 'number') return 'var(--tf-bg-elevated)';
  if (upsidePct >= 20) return 'rgba(46, 204, 113, 0.28)';
  if (upsidePct >= 5) return 'rgba(46, 204, 113, 0.14)';
  if (upsidePct > -5) return 'var(--tf-bg-elevated)';
  if (upsidePct > -20) return 'rgba(255, 82, 103, 0.14)';
  return 'rgba(255, 82, 103, 0.28)';
}

const DcfValuationPanel: React.FC<{
  payload: DcfValuationPayload | null;
  loading?: boolean;
  error?: string | null;
}> = ({ payload, loading = false, error = null }) => {
  const selectedScenario: DcfScenario | null =
    payload?.scenarios.base ||
    (payload ? payload.scenarios[SCENARIO_ORDER.find((key) => payload.scenarios[key]) || ''] || null : null);

  const scenarioList: DcfScenario[] = payload
    ? SCENARIO_ORDER.map((key) => payload.scenarios[key]).filter((scenario): scenario is DcfScenario => Boolean(scenario))
    : [];

  const sensitivityLookup = React.useMemo(() => {
    const map = new Map<string, { intrinsicValue: number | null; upsidePct: number | null }>();
    for (const cell of payload?.sensitivity.cells || []) {
      map.set(`${cell.terminalGrowthShiftBps}:${cell.discountRateShiftBps}`, {
        intrinsicValue: cell.intrinsicValue,
        upsidePct: cell.upsidePct,
      });
    }
    return map;
  }, [payload]);

  if (loading) {
    return <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Loading valuation...</div>;
  }

  if (error) {
    return <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-down)' }}>Failed to load valuation: {error}</div>;
  }

  if (!payload) {
    return <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>No valuation available right now.</div>;
  }

  const qualityMode = payload.dataQuality?.mode || 'live';
  const showBanner = payload.status !== 'ready' || qualityMode !== 'live' || payload.warnings.length > 0;
  const methodCases = payload.methods || [];
  const isBlendedIndexView = methodCases.length > 0;
  const headlineLabel =
    typeof payload.assumptions.valuationHeadlineLabel === 'string'
      ? payload.assumptions.valuationHeadlineLabel
      : isBlendedIndexView
        ? 'Blended Intrinsic Value'
        : 'Intrinsic Value';
  const presentValueToday =
    typeof payload.assumptions.presentValueToday === 'number' ? payload.assumptions.presentValueToday : null;
  const showPresentValueToday = presentValueToday !== null && headlineLabel !== 'Intrinsic Value';

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
            {payload.status === 'ready' ? `Data quality: ${qualityMode}` : 'Insufficient data for a full valuation'}
          </div>
          {(payload.warnings.length ? payload.warnings : ['This model is using fallback assumptions.']).map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}

      <div style={responsiveGridStyle(showPresentValueToday ? 160 : 180)}>
        <SummaryMetric label="Current Price" value={fmtCurrency(payload.currentPrice)} tone="var(--tf-text)" />
        <SummaryMetric label={headlineLabel} value={fmtCurrency(payload.currentIntrinsicValue)} tone="var(--tf-text)" />
        {showPresentValueToday ? (
          <SummaryMetric label="Present Value Today" value={fmtCurrency(presentValueToday)} tone="var(--tf-muted)" />
        ) : null}
        <SummaryMetric
          label="Upside / Downside"
          value={fmtPct(payload.upsidePct)}
          tone={typeof payload.upsidePct === 'number' && payload.upsidePct < 0 ? 'var(--tf-down)' : 'var(--tf-up)'}
        />
      </div>

      {methodCases.length > 0 ? (
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ fontSize: "var(--tf-fs-xs)", fontWeight: 700, color: 'var(--tf-muted-strong)' }}>Index Cases</div>
          <div style={responsiveGridStyle(180)}>
            {methodCases.map((methodCase) => (
              <div
                key={methodCase.key}
                style={{
                  border: '1px solid var(--tf-border)',
                  borderRadius: 'var(--tf-radius)',
                  padding: '10px 12px',
                  background: 'var(--tf-bg-elevated)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ fontSize: "var(--tf-fs-xs)", fontWeight: 700, color: 'var(--tf-text)' }}>{methodCase.label}</div>
                  <div style={{ fontSize: "var(--tf-fs-micro)", fontWeight: 700, color: 'var(--tf-muted)' }}>{Math.round(methodCase.weight * 100)}%</div>
                </div>
                <div style={{ marginTop: 6, fontSize: "var(--tf-fs-base)", fontWeight: 700, color: 'var(--tf-text)' }}>
                  {fmtCurrency(methodCase.currentIntrinsicValue)}
                </div>
                <div
                  style={{
                    marginTop: 2,
                    fontSize: "var(--tf-fs-xs)",
                    fontWeight: 600,
                    color: typeof methodCase.upsidePct === 'number' && methodCase.upsidePct < 0 ? 'var(--tf-down)' : 'var(--tf-up)',
                  }}
                >
                  {fmtPct(methodCase.upsidePct)}
                </div>
                <div style={{ marginTop: 8, fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)', lineHeight: 1.5 }}>{methodCase.description}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {scenarioList.length > 0 ? (
        <div style={responsiveGridStyle(180)}>
          {scenarioList.map((scenario) => (
            <SummaryMetric
              key={scenario.key}
              label={`${scenario.label} Scenario`}
              value={`${fmtCurrency(scenario.intrinsicValue)} / ${fmtPct(scenario.upsidePct)}`}
              tone={typeof scenario.upsidePct === 'number' && scenario.upsidePct < 0 ? 'var(--tf-down)' : 'var(--tf-text)'}
            />
          ))}
        </div>
      ) : null}

      {selectedScenario ? (
        <div style={{ display: 'grid', gap: 10 }}>
          <div style={responsiveGridStyle(160)}>
            <SummaryMetric label="Scenario Value" value={fmtCurrency(selectedScenario.intrinsicValue)} tone="var(--tf-text)" />
            <SummaryMetric
              label="Scenario Upside"
              value={fmtPct(selectedScenario.upsidePct)}
              tone={typeof selectedScenario.upsidePct === 'number' && selectedScenario.upsidePct < 0 ? 'var(--tf-down)' : 'var(--tf-up)'}
            />
            <SummaryMetric label="Terminal Growth" value={`${selectedScenario.terminalGrowthPct.toFixed(2)}%`} tone="var(--tf-text)" />
            <SummaryMetric label="Terminal Discount" value={`${selectedScenario.terminalDiscountRatePct.toFixed(2)}%`} tone="var(--tf-text)" />
          </div>

          <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)', lineHeight: 1.5 }}>
            {typeof payload.assumptions.valuationMethodDescription === 'string' ? `${payload.assumptions.valuationMethodDescription} ` : ''}
            {isBlendedIndexView ? 'Blended two-case S&P 500 estimate. ' : ''}
            Base growth {formatAssumptionNumber(payload.assumptions.baseGrowthPct)}. Rate source {payload.rateCurve.source}. Curve fallback{' '}
            {payload.rateCurve.fallbackUsed ? 'on' : 'off'}.
          </div>

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
                {selectedScenario.projectedCashFlows.map((point) => (
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
        </div>
      ) : null}

      <div style={{ display: 'grid', gap: 8 }}>
        <div style={{ fontSize: "var(--tf-fs-xs)", fontWeight: 700, color: 'var(--tf-muted-strong)' }}>Sensitivity</div>
        {payload.sensitivity.cells.length === 0 ? (
          <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Sensitivity is unavailable until the valuation is ready.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: `88px repeat(${payload.sensitivity.discountRateShiftBps.length}, minmax(60px, 1fr))`,
                gap: 6,
                alignItems: 'stretch',
                minWidth: 420,
              }}
            >
              <div style={axisHeaderStyle}>TG / DR</div>
              {payload.sensitivity.discountRateShiftBps.map((shift) => (
                <div key={`dr-${shift}`} style={axisHeaderStyle}>
                  {shift > 0 ? '+' : ''}
                  {shift}bp
                </div>
              ))}
              {payload.sensitivity.terminalGrowthShiftBps.map((tgShift) => (
                <React.Fragment key={`row-${tgShift}`}>
                  <div style={axisHeaderStyle}>
                    {tgShift > 0 ? '+' : ''}
                    {tgShift}bp
                  </div>
                  {payload.sensitivity.discountRateShiftBps.map((drShift) => {
                    const cell = sensitivityLookup.get(`${tgShift}:${drShift}`);
                    return (
                      <div
                        key={`${tgShift}:${drShift}`}
                        style={{
                          borderRadius: 'var(--tf-radius)',
                          border: '1px solid var(--tf-border)',
                          padding: '8px 6px',
                          background: cellColor(cell?.upsidePct),
                          textAlign: 'center',
                        }}
                        aria-label={typeof cell?.upsidePct === 'number' ? `${cell.upsidePct.toFixed(2)}% upside` : 'No data'}
                      >
                        <div style={{ fontSize: "var(--tf-fs-xs)", fontWeight: 700, color: 'var(--tf-text)', fontFamily: 'var(--tf-mono)' }}>
                          {fmtCurrency(cell?.intrinsicValue)}
                        </div>
                        <div style={{ marginTop: 2, fontSize: "var(--tf-fs-micro)", color: 'var(--tf-muted)', fontFamily: 'var(--tf-mono)' }}>{fmtPct(cell?.upsidePct)}</div>
                      </div>
                    );
                  })}
                </React.Fragment>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const SummaryMetric: React.FC<{ label: string; value: string; tone: string }> = ({ label, value, tone }) => (
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

const axisHeaderStyle: React.CSSProperties = {
  borderRadius: 'var(--tf-radius)',
  border: '1px solid var(--tf-border)',
  padding: '8px 6px',
  fontSize: "var(--tf-fs-xs)",
  fontWeight: 700,
  textAlign: 'center',
  color: 'var(--tf-muted-strong)',
  background: 'var(--tf-bg-pane)',
};

function formatAssumptionNumber(value: unknown): string {
  return typeof value === 'number' ? `${value.toFixed(2)}%` : '--';
}

export default DcfValuationPanel;
