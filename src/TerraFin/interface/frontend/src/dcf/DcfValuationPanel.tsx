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
  if (typeof upsidePct !== 'number') return '#f8fafc';
  if (upsidePct >= 20) return '#dcfce7';
  if (upsidePct >= 5) return '#ecfccb';
  if (upsidePct > -5) return '#f8fafc';
  if (upsidePct > -20) return '#fee2e2';
  return '#fecaca';
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
    return <div style={{ fontSize: 13, color: '#475569' }}>Loading valuation...</div>;
  }

  if (error) {
    return <div style={{ fontSize: 13, color: '#b91c1c' }}>Failed to load valuation: {error}</div>;
  }

  if (!payload) {
    return <div style={{ fontSize: 13, color: '#64748b' }}>No valuation available right now.</div>;
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
            border: '1px solid #fcd34d',
            background: '#fffbeb',
            color: '#92400e',
            borderRadius: 10,
            padding: '10px 12px',
            fontSize: 12,
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
        <SummaryMetric label="Current Price" value={fmtCurrency(payload.currentPrice)} tone="#0f172a" />
        <SummaryMetric label={headlineLabel} value={fmtCurrency(payload.currentIntrinsicValue)} tone="#0f172a" />
        {showPresentValueToday ? (
          <SummaryMetric label="Present Value Today" value={fmtCurrency(presentValueToday)} tone="#334155" />
        ) : null}
        <SummaryMetric
          label="Upside / Downside"
          value={fmtPct(payload.upsidePct)}
          tone={typeof payload.upsidePct === 'number' && payload.upsidePct < 0 ? '#b91c1c' : '#047857'}
        />
      </div>

      {methodCases.length > 0 ? (
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Index Cases</div>
          <div style={responsiveGridStyle(180)}>
            {methodCases.map((methodCase) => (
              <div
                key={methodCase.key}
                style={{
                  border: '1px solid #e2e8f0',
                  borderRadius: 10,
                  padding: '10px 12px',
                  background: '#ffffff',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#0f172a' }}>{methodCase.label}</div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#475569' }}>{Math.round(methodCase.weight * 100)}%</div>
                </div>
                <div style={{ marginTop: 6, fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
                  {fmtCurrency(methodCase.currentIntrinsicValue)}
                </div>
                <div
                  style={{
                    marginTop: 2,
                    fontSize: 11,
                    fontWeight: 600,
                    color: typeof methodCase.upsidePct === 'number' && methodCase.upsidePct < 0 ? '#b91c1c' : '#047857',
                  }}
                >
                  {fmtPct(methodCase.upsidePct)}
                </div>
                <div style={{ marginTop: 8, fontSize: 11, color: '#64748b', lineHeight: 1.5 }}>{methodCase.description}</div>
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
              tone={typeof scenario.upsidePct === 'number' && scenario.upsidePct < 0 ? '#b91c1c' : '#0f172a'}
            />
          ))}
        </div>
      ) : null}

      {selectedScenario ? (
        <div style={{ display: 'grid', gap: 10 }}>
          <div style={responsiveGridStyle(160)}>
            <SummaryMetric label="Scenario Value" value={fmtCurrency(selectedScenario.intrinsicValue)} tone="#0f172a" />
            <SummaryMetric
              label="Scenario Upside"
              value={fmtPct(selectedScenario.upsidePct)}
              tone={typeof selectedScenario.upsidePct === 'number' && selectedScenario.upsidePct < 0 ? '#b91c1c' : '#047857'}
            />
            <SummaryMetric label="Terminal Growth" value={`${selectedScenario.terminalGrowthPct.toFixed(2)}%`} tone="#0f172a" />
            <SummaryMetric label="Terminal Discount" value={`${selectedScenario.terminalDiscountRatePct.toFixed(2)}%`} tone="#0f172a" />
          </div>

          <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.5 }}>
            {typeof payload.assumptions.valuationMethodDescription === 'string' ? `${payload.assumptions.valuationMethodDescription} ` : ''}
            {isBlendedIndexView ? 'Blended two-case S&P 500 estimate. ' : ''}
            Base growth {formatAssumptionNumber(payload.assumptions.baseGrowthPct)}. Rate source {payload.rateCurve.source}. Curve fallback{' '}
            {payload.rateCurve.fallbackUsed ? 'on' : 'off'}.
          </div>

          <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 10 }}>
            <table style={{ width: '100%', minWidth: 520, borderCollapse: 'collapse', fontSize: 12, background: '#ffffff' }}>
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
        <div style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Sensitivity</div>
        {payload.sensitivity.cells.length === 0 ? (
          <div style={{ fontSize: 12, color: '#64748b' }}>Sensitivity is unavailable until the valuation is ready.</div>
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
                          borderRadius: 10,
                          border: '1px solid #e2e8f0',
                          padding: '8px 6px',
                          background: cellColor(cell?.upsidePct),
                          textAlign: 'center',
                        }}
                        title={typeof cell?.upsidePct === 'number' ? `${cell.upsidePct.toFixed(2)}%` : 'N/A'}
                      >
                        <div style={{ fontSize: 11, fontWeight: 700, color: '#0f172a' }}>
                          {fmtCurrency(cell?.intrinsicValue)}
                        </div>
                        <div style={{ marginTop: 2, fontSize: 10, color: '#475569' }}>{fmtPct(cell?.upsidePct)}</div>
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
      border: '1px solid #e2e8f0',
      borderRadius: 10,
      padding: '10px 12px',
      background: '#ffffff',
    }}
  >
    <div style={{ fontSize: 11, color: '#64748b' }}>{label}</div>
    <div style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: tone, lineHeight: 1.25, overflowWrap: 'anywhere' }}>
      {value}
    </div>
  </div>
);

const thStyle: React.CSSProperties = {
  padding: '7px 8px',
  borderBottom: '1px solid #e2e8f0',
  textAlign: 'left',
  fontSize: 11,
  color: '#64748b',
  background: '#f8fafc',
};

const tdStyle: React.CSSProperties = {
  padding: '7px 8px',
  borderBottom: '1px solid #f1f5f9',
  color: '#0f172a',
};

const axisHeaderStyle: React.CSSProperties = {
  borderRadius: 10,
  border: '1px solid #e2e8f0',
  padding: '8px 6px',
  fontSize: 11,
  fontWeight: 700,
  textAlign: 'center',
  color: '#334155',
  background: '#f8fafc',
};

function formatAssumptionNumber(value: unknown): string {
  return typeof value === 'number' ? `${value.toFixed(2)}%` : '--';
}

export default DcfValuationPanel;
