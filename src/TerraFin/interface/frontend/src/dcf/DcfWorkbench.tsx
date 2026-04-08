import React from 'react';
import DcfValuationPanel from './DcfValuationPanel';
import InfoHint from './InfoHint';
import { SP500_DCF_FORM_PRESET, Sp500DcfFormPreset, Sp500YearAssumptionFormValue } from './presets';
import { BetaEstimatePayload, DcfValuationPayload } from './types';
import { useBetaEstimate } from './useBetaEstimate';
import { DcfFetchRequest, useDcfValuation } from './useDcfValuation';

interface StockFormState {
  baseCashFlowPerShare: string;
  baseGrowthPct: string;
  terminalGrowthPct: string;
  beta: string;
  equityRiskPremiumPct: string;
}

const COMPUTE_BETA_INFO =
  'Computes TerraFin beta_5y_monthly from 5 years of monthly returns against the mapped benchmark and fills the Beta field. The adjusted beta is shown only as reference. This does not rerun DCF automatically.';

const DEFAULT_STOCK_FORM = {
  baseCashFlowPerShare: '',
  terminalGrowthPct: '3.00',
  equityRiskPremiumPct: '5.00',
};

const DcfWorkbench: React.FC<{
  mode: 'index' | 'stock';
  endpoint: string | null;
  enabled?: boolean;
  blockedMessage?: string;
  symbolLabel?: string;
  betaEndpoint?: string | null;
  indexPreset?: Sp500DcfFormPreset;
  defaultBaseGrowthPct?: number | null;
  defaultBeta?: number | null;
  showInlineResults?: boolean;
  onValuationStateChange?: (state: {
    payload: DcfValuationPayload | null;
    loading: boolean;
    error: string | null;
    hasValuationState: boolean;
  }) => void;
}> = ({
  mode,
  endpoint,
  enabled = true,
  blockedMessage = 'This feature is not ready yet.',
  symbolLabel,
  betaEndpoint = null,
  indexPreset = SP500_DCF_FORM_PRESET,
  defaultBaseGrowthPct = null,
  defaultBeta = null,
  showInlineResults = true,
  onValuationStateChange,
}) => {
  const [indexForm, setIndexForm] = React.useState(() => buildIndexFormState(indexPreset));
  const [stockForm, setStockForm] = React.useState(() => buildStockFormState(defaultBaseGrowthPct, defaultBeta));
  const [request, setRequest] = React.useState<DcfFetchRequest | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);
  const { data, loading, error } = useDcfValuation(endpoint, request, enabled);
  const {
    data: betaEstimate,
    loading: betaLoading,
    error: betaError,
    compute: computeBeta,
    reset: resetBetaEstimate,
  } = useBetaEstimate(mode === 'stock' ? betaEndpoint : null, enabled && mode === 'stock');
  const hasValuationState = Boolean(request || loading || error || data);

  React.useEffect(() => {
    setRequest(null);
    setFormError(null);
    resetBetaEstimate();
    if (mode === 'index') {
      setIndexForm(buildIndexFormState(indexPreset));
      return;
    }
    setStockForm(buildStockFormState(defaultBaseGrowthPct, defaultBeta));
  }, [defaultBaseGrowthPct, defaultBeta, endpoint, indexPreset, mode, resetBetaEstimate, symbolLabel]);

  React.useEffect(() => {
    onValuationStateChange?.({
      payload: data,
      loading,
      error,
      hasValuationState,
    });
  }, [data, error, hasValuationState, loading, onValuationStateChange]);

  if (!enabled) {
    return <div style={{ fontSize: 13, color: '#475569' }}>{blockedMessage}</div>;
  }

  const handleIndexSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const baseYearEps = parseOptionalNumber(indexForm.baseYearEps);
    const terminalGrowthPct = parseOptionalNumber(indexForm.terminalGrowthPct);
    const terminalEquityRiskPremiumPct = parseOptionalNumber(indexForm.terminalEquityRiskPremiumPct);
    const terminalRoePct = parseOptionalNumber(indexForm.terminalRoePct);
    const yearlyAssumptions = indexForm.yearlyAssumptions.map((row) => ({
      yearOffset: row.yearOffset,
      growthPct: parseOptionalNumber(row.growthPct),
      payoutRatioPct: parseOptionalNumber(row.payoutRatioPct),
      buybackRatioPct: parseOptionalNumber(row.buybackRatioPct),
      equityRiskPremiumPct: parseOptionalNumber(row.equityRiskPremiumPct),
    }));

    const hasMissingInput =
      baseYearEps == null ||
      terminalGrowthPct == null ||
      terminalEquityRiskPremiumPct == null ||
      terminalRoePct == null ||
      yearlyAssumptions.some(
        (row) =>
          row.growthPct == null ||
          row.payoutRatioPct == null ||
          row.buybackRatioPct == null ||
          row.equityRiskPremiumPct == null
      );

    if (hasMissingInput) {
      setFormError('Fill in every index DCF input before running the model.');
      return;
    }

    setFormError(null);
    setRequest({
      method: 'POST',
      requestId: Date.now(),
      body: {
        baseYearEps,
        terminalGrowthPct,
        terminalEquityRiskPremiumPct,
        terminalRoePct,
        yearlyAssumptions,
      },
    });
  };

  const handleStockSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    setRequest({
      method: 'POST',
      requestId: Date.now(),
      body: compactRecord({
        baseCashFlowPerShare: parseOptionalNumber(stockForm.baseCashFlowPerShare),
        baseGrowthPct: parseOptionalNumber(stockForm.baseGrowthPct),
        terminalGrowthPct: parseOptionalNumber(stockForm.terminalGrowthPct),
        beta: parseOptionalNumber(stockForm.beta),
        equityRiskPremiumPct: parseOptionalNumber(stockForm.equityRiskPremiumPct),
      }),
    });
  };

  const resetIndexForm = () => {
    setFormError(null);
    setRequest(null);
    setIndexForm(buildIndexFormState(indexPreset));
  };

  const resetStockForm = () => {
    setFormError(null);
    setRequest(null);
    resetBetaEstimate();
    setStockForm(buildStockFormState(defaultBaseGrowthPct, defaultBeta));
  };

  const handleComputeBeta = async () => {
    const payload = await computeBeta();
    if (payload?.status === 'ready' && payload.beta != null) {
      setStockForm((current) => ({ ...current, beta: payload.beta!.toFixed(2) }));
    }
  };

  const betaHelper = buildBetaHelper(betaEstimate, betaError, betaLoading);

  return (
    <div style={workbenchRootStyle}>
      {mode === 'index' ? (
        <form onSubmit={handleIndexSubmit} style={workbenchStyle}>
          <div style={headerRowStyle}>
            <div>
              <div style={eyebrowStyle}>Last Completed Year</div>
              <div style={indexHeadlineStyle}>{`FY${indexPreset.baseYear} actuals`}</div>
            </div>
            <div style={badgeStyle}>S&amp;P 500</div>
          </div>

          <div style={sectionStyle}>
            <SectionTitle title="Core Inputs" />
            <div style={fieldsGridStyle}>
              <NumericField
                label={`EPS (FY${indexPreset.baseYear})`}
                info="Starting S&P 500 earnings per index unit from the last completed year. TerraFin's baseline uses nominal strategist-style EPS, not an inflation-adjusted real earnings series, because the model is trying to frame a year-end index target."
                step="0.01"
                value={indexForm.baseYearEps}
                onChange={(value) => setIndexForm((current) => ({ ...current, baseYearEps: value }))}
              />
              <NumericField
                label="Terminal Growth %"
                info="Long-run perpetual growth used after the five-year forecast. TerraFin's baseline uses 4.00%. A 3.90% setting is a slightly more conservative alternative, while 4.00% fits the current street year-end target cluster better. Keep it meaningfully below the terminal discount rate."
                step="0.01"
                value={indexForm.terminalGrowthPct}
                onChange={(value) => setIndexForm((current) => ({ ...current, terminalGrowthPct: value }))}
              />
              <NumericField
                label="Terminal ERP %"
                info="Long-run equity risk premium added to the terminal Treasury rate to form the terminal discount rate. TerraFin's baseline uses 4.00% so the terminal discount rate stays closer to the current implied-ERP regime instead of the older, harsher legacy schedule."
                step="0.01"
                value={indexForm.terminalEquityRiskPremiumPct}
                onChange={(value) =>
                  setIndexForm((current) => ({ ...current, terminalEquityRiskPremiumPct: value }))
                }
              />
              <NumericField
                label="Terminal ROE %"
                info="Long-run return on equity used in the shareholder-yield case to estimate how much earnings can be distributed while still supporting terminal growth."
                step="0.01"
                value={indexForm.terminalRoePct}
                onChange={(value) => setIndexForm((current) => ({ ...current, terminalRoePct: value }))}
              />
            </div>
          </div>

          <div style={sectionStyle}>
            <SectionTitle
              title="Five-Year Schedule"
              info="Each row is an explicit forecast year before the model moves into the terminal value. Growth drives EPS, payout and buyback convert earnings into shareholder cash flow, and ERP shapes the discount rate. TerraFin's default schedule is calibrated to current strategist expectations for a year-end S&P 500 target, not to reverse-engineered spot multiples."
            />
            <div style={{ overflowX: 'auto' }}>
              <table style={scheduleTableStyle}>
                <thead>
                  <tr>
                    <th style={scheduleHeaderStyle}>
                      <HeaderWithInfo
                        label="Year"
                        info="Explicit forecast year in the five-year schedule."
                      />
                    </th>
                    <th style={scheduleHeaderStyle}>
                      <HeaderWithInfo
                        label="Growth %"
                        info="Expected EPS growth for that year. TerraFin's baseline starts near the current strategist and bottom-up earnings-growth regime, then fades toward a more mature path."
                      />
                    </th>
                    <th style={scheduleHeaderStyle}>
                      <HeaderWithInfo
                        label="Payout %"
                        info="Dividend payout ratio as a percent of earnings."
                      />
                    </th>
                    <th style={scheduleHeaderStyle}>
                      <HeaderWithInfo
                        label="Buyback %"
                        info="Net buybacks as a percent of earnings."
                      />
                    </th>
                    <th style={scheduleHeaderStyle}>
                      <HeaderWithInfo
                        label="ERP %"
                        info="Equity risk premium added to the Treasury curve to form the annual discount rate. TerraFin's baseline fades from 4.5% to 4.1%, which is closer to the current implied-ERP regime than the older legacy path."
                      />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {indexForm.yearlyAssumptions.map((row, index) => (
                    <tr key={row.yearOffset}>
                      <td style={scheduleCellLabelStyle}>{indexPreset.baseYear + row.yearOffset}</td>
                      <td style={scheduleCellStyle}>
                        <CompactNumericInput
                          value={row.growthPct}
                          onChange={(value) => updateIndexYearValue(setIndexForm, index, 'growthPct', value)}
                        />
                      </td>
                      <td style={scheduleCellStyle}>
                        <CompactNumericInput
                          value={row.payoutRatioPct}
                          onChange={(value) => updateIndexYearValue(setIndexForm, index, 'payoutRatioPct', value)}
                        />
                      </td>
                      <td style={scheduleCellStyle}>
                        <CompactNumericInput
                          value={row.buybackRatioPct}
                          onChange={(value) => updateIndexYearValue(setIndexForm, index, 'buybackRatioPct', value)}
                        />
                      </td>
                      <td style={scheduleCellStyle}>
                        <CompactNumericInput
                          value={row.equityRiskPremiumPct}
                          onChange={(value) => updateIndexYearValue(setIndexForm, index, 'equityRiskPremiumPct', value)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <ActionRow
            runLabel="Run S&P 500 DCF"
            loading={loading}
            onReset={resetIndexForm}
          />
        </form>
      ) : (
        <form onSubmit={handleStockSubmit} style={stockWorkbenchStyle}>
          <div style={headerRowStyle}>
            <div>
              <div style={eyebrowStyle}>Ticker</div>
              <div style={stockHeadlineStyle}>{symbolLabel || 'Stock'}</div>
            </div>
            <div style={stockBadgeStyle}>{hasValuationState ? 'DCF Ready' : 'Equity DCF'}</div>
          </div>

          <div style={sectionStyle}>
            <SectionTitle
              title="Model Inputs"
              info="These are the key stock-specific assumptions. Blank fields fall back to TerraFin's derived defaults from current company data."
            />
            <div style={fieldsGridStyle}>
              <NumericField
                label="Base FCF / Share"
                info="Starting free cash flow per share used in year one. Leave blank to use TerraFin's derived TTM or latest annual value."
                step="0.0001"
                value={stockForm.baseCashFlowPerShare}
                placeholder="Auto"
                onChange={(value) => setStockForm((current) => ({ ...current, baseCashFlowPerShare: value }))}
              />
              <NumericField
                label="Base Growth %"
                info="Initial growth rate for free cash flow per share. Blank uses TerraFin's fallback order: user override, EPS growth from forward vs trailing EPS, annual revenue CAGR, annual FCF CAGR, then the 6% default. The model fades this toward terminal growth over the explicit forecast."
                step="0.01"
                value={stockForm.baseGrowthPct}
                placeholder={formatPlaceholder(defaultBaseGrowthPct)}
                onChange={(value) => setStockForm((current) => ({ ...current, baseGrowthPct: value }))}
              />
              <NumericField
                label="Terminal Growth %"
                info="Perpetual growth rate used after the explicit forecast period."
                step="0.01"
                value={stockForm.terminalGrowthPct}
                onChange={(value) => setStockForm((current) => ({ ...current, terminalGrowthPct: value }))}
              />
              <NumericField
                label="Beta"
                info="Stock beta used to scale the equity risk premium in the discount rate."
                step="0.01"
                value={stockForm.beta}
                placeholder={formatPlaceholder(defaultBeta)}
                onChange={(value) => setStockForm((current) => ({ ...current, beta: value }))}
                utility={
                  <span style={fieldUtilityRowStyle}>
                    <button
                      type="button"
                      onClick={handleComputeBeta}
                      disabled={betaLoading || !betaEndpoint}
                      style={fieldActionButtonStyle(betaLoading || !betaEndpoint)}
                    >
                      {betaLoading ? 'Computing...' : 'Compute Beta'}
                    </button>
                    <InfoHint text={COMPUTE_BETA_INFO} />
                  </span>
                }
                footer={betaHelper}
              />
              <NumericField
                label="Equity Risk Premium %"
                info="Excess return over the risk-free rate used in the stock discount rate."
                step="0.01"
                value={stockForm.equityRiskPremiumPct}
                onChange={(value) => setStockForm((current) => ({ ...current, equityRiskPremiumPct: value }))}
              />
            </div>
          </div>

          <ActionRow
            runLabel={hasValuationState ? 'Update DCF' : `Run ${symbolLabel || 'Stock'} DCF`}
            loading={loading}
            onReset={resetStockForm}
          />
        </form>
      )}

      {formError ? (
        <div style={formErrorStyle}>{formError}</div>
      ) : null}

      {showInlineResults && hasValuationState ? (
        <div style={valuationShellStyle(mode)}>
          <DcfValuationPanel payload={data} loading={loading} error={error} />
        </div>
      ) : null}
    </div>
  );
};

const NumericField: React.FC<{
  label: string;
  info?: string;
  value: string;
  step: string;
  placeholder?: string;
  onChange: (value: string) => void;
  action?: React.ReactNode;
  utility?: React.ReactNode;
  footer?: React.ReactNode;
  cardStyle?: React.CSSProperties;
}> = ({ label, info, value, step, placeholder, onChange, action, utility, footer, cardStyle }) => (
  <label style={{ ...fieldCardStyle, ...cardStyle }}>
    <span style={fieldLabelRowStyle}>
      <span style={fieldLabelClusterStyle}>
        <span style={fieldLabelStyle}>{label}</span>
        {info ? <InfoHint text={info} /> : null}
      </span>
      {action}
    </span>
    <input
      type="number"
      inputMode="decimal"
      step={step}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      style={inputStyle}
    />
    {utility}
    {footer ? <span style={fieldFooterStyle}>{footer}</span> : null}
  </label>
);

const SectionTitle: React.FC<{ title: string; info?: string }> = ({ title, info }) => (
  <div style={sectionTitleRowStyle}>
    <div style={sectionTitleStyle}>{title}</div>
    {info ? <InfoHint text={info} /> : null}
  </div>
);

const HeaderWithInfo: React.FC<{ label: string; info: string }> = ({ label, info }) => (
  <span style={headerLabelRowStyle}>
    <span>{label}</span>
    <InfoHint text={info} compact />
  </span>
);

const CompactNumericInput: React.FC<{
  value: string;
  onChange: (value: string) => void;
}> = ({ value, onChange }) => (
  <input
    type="number"
    inputMode="decimal"
    step="0.01"
    value={value}
    onChange={(event) => onChange(event.target.value)}
    style={compactInputStyle}
  />
);

const ActionRow: React.FC<{
  runLabel: string;
  loading: boolean;
  onReset: () => void;
}> = ({ runLabel, loading, onReset }) => (
  <div style={actionRowStyle}>
    <button type="button" onClick={onReset} style={secondaryButtonStyle}>
      Reset
    </button>
    <button type="submit" disabled={loading} style={primaryButtonStyle(loading)}>
      {loading ? 'Running...' : runLabel}
    </button>
  </div>
);

interface IndexFormState {
  baseYearEps: string;
  terminalGrowthPct: string;
  terminalEquityRiskPremiumPct: string;
  terminalRoePct: string;
  yearlyAssumptions: Sp500YearAssumptionFormValue[];
}

function buildIndexFormState(preset: Sp500DcfFormPreset): IndexFormState {
  return {
    baseYearEps: preset.baseYearEps,
    terminalGrowthPct: preset.terminalGrowthPct,
    terminalEquityRiskPremiumPct: preset.terminalEquityRiskPremiumPct,
    terminalRoePct: preset.terminalRoePct,
    yearlyAssumptions: preset.yearlyAssumptions.map((row) => ({ ...row })),
  };
}

function buildStockFormState(defaultBaseGrowthPct: number | null, defaultBeta: number | null): StockFormState {
  return {
    ...DEFAULT_STOCK_FORM,
    baseGrowthPct: defaultBaseGrowthPct != null ? defaultBaseGrowthPct.toFixed(2) : '',
    beta: defaultBeta != null ? defaultBeta.toFixed(2) : '',
  };
}

function updateIndexYearValue(
  setIndexForm: React.Dispatch<React.SetStateAction<IndexFormState>>,
  rowIndex: number,
  field: keyof Omit<Sp500YearAssumptionFormValue, 'yearOffset'>,
  value: string,
) {
  setIndexForm((current) => ({
    ...current,
    yearlyAssumptions: current.yearlyAssumptions.map((row, index) =>
      index === rowIndex ? { ...row, [field]: value } : row
    ),
  }));
}

function parseOptionalNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatPlaceholder(value: number | null | undefined): string | undefined {
  return typeof value === 'number' ? value.toFixed(2) : undefined;
}

function compactRecord<T extends Record<string, number | null>>(record: T): Partial<T> {
  const next: Partial<T> = {};
  for (const key of Object.keys(record) as Array<keyof T>) {
    if (record[key] != null) {
      next[key] = record[key];
    }
  }
  return next;
}

function buildBetaHelper(
  payload: BetaEstimatePayload | null,
  error: string | null,
  loading: boolean,
): React.ReactNode {
  if (error) {
    return `Unable to compute beta (${error}).`;
  }
  if (!payload) {
    return null;
  }
  if (payload.status !== 'ready' || payload.beta == null) {
    return payload.warnings[0] || 'Beta estimate is unavailable for this ticker.';
  }
  return null;
}

const workbenchStyle: React.CSSProperties = {
  display: 'grid',
  gap: 14,
  border: '1px solid #dbe4ef',
  borderRadius: 16,
  padding: 14,
  background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
};

const workbenchRootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  height: '100%',
  minHeight: 0,
};

const stockWorkbenchStyle: React.CSSProperties = {
  ...workbenchStyle,
};

const headerRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  gap: 12,
  flexWrap: 'wrap',
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
};

const headlineStyle: React.CSSProperties = {
  marginTop: 4,
  fontSize: 24,
  fontWeight: 800,
  color: '#0f172a',
};

const indexHeadlineStyle: React.CSSProperties = {
  ...headlineStyle,
  marginTop: 2,
  fontSize: 18,
  fontWeight: 700,
  lineHeight: 1.2,
};

const stockHeadlineStyle: React.CSSProperties = {
  ...headlineStyle,
  marginTop: 2,
  fontSize: 20,
  fontWeight: 800,
  lineHeight: 1.2,
};

const badgeStyle: React.CSSProperties = {
  borderRadius: 999,
  padding: '8px 12px',
  background: '#e0f2fe',
  color: '#075985',
  fontSize: 11,
  fontWeight: 800,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
};

const stockBadgeStyle: React.CSSProperties = {
  ...badgeStyle,
};

const sectionStyle: React.CSSProperties = {
  display: 'grid',
  gap: 10,
};

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 800,
  color: '#334155',
  letterSpacing: '0.02em',
};

const sectionTitleRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
};

const fieldsGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
  gap: 10,
};

const fieldCardStyle: React.CSSProperties = {
  display: 'grid',
  gap: 6,
  minWidth: 0,
  border: '1px solid #dbe4ef',
  borderRadius: 12,
  padding: '10px 12px',
  background: '#ffffff',
};

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  minWidth: 0,
  lineHeight: 1.25,
};

const fieldLabelRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: 8,
  flexWrap: 'wrap',
};

const fieldLabelClusterStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1fr) auto',
  alignItems: 'start',
  gap: 6,
  minWidth: 0,
  width: '100%',
};

const fieldActionClusterStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  flexWrap: 'wrap',
  minWidth: 0,
};

const fieldUtilityRowStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'flex-start',
  gap: 6,
  flexWrap: 'wrap',
  minWidth: 0,
  paddingTop: 2,
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  minWidth: 0,
  height: 36,
  border: '1px solid #cbd5e1',
  borderRadius: 10,
  padding: '0 10px',
  fontSize: 14,
  color: '#0f172a',
  background: '#f8fafc',
  boxSizing: 'border-box',
};

const fieldFooterStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#475569',
  lineHeight: 1.45,
};

const compactInputStyle: React.CSSProperties = {
  width: '100%',
  height: 34,
  border: '1px solid #cbd5e1',
  borderRadius: 10,
  padding: '0 8px',
  fontSize: 13,
  color: '#0f172a',
  background: '#f8fafc',
  boxSizing: 'border-box',
};

const scheduleTableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  minWidth: 620,
};

const scheduleHeaderStyle: React.CSSProperties = {
  padding: '8px 10px',
  textAlign: 'left',
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  borderBottom: '1px solid #e2e8f0',
  verticalAlign: 'top',
};

const headerLabelRowStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  position: 'relative',
};

const scheduleCellLabelStyle: React.CSSProperties = {
  padding: '10px',
  fontSize: 12,
  fontWeight: 700,
  color: '#0f172a',
  borderBottom: '1px solid #f1f5f9',
  whiteSpace: 'nowrap',
};

const scheduleCellStyle: React.CSSProperties = {
  padding: '8px 10px',
  borderBottom: '1px solid #f1f5f9',
};

const actionRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 10,
  flexWrap: 'wrap',
};

const secondaryButtonStyle: React.CSSProperties = {
  height: 40,
  padding: '0 14px',
  borderRadius: 12,
  border: '1px solid #cbd5e1',
  background: '#ffffff',
  color: '#334155',
  fontSize: 13,
  fontWeight: 700,
  cursor: 'pointer',
  flex: '1 1 140px',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  maxWidth: '100%',
  whiteSpace: 'nowrap',
};

const fieldActionButtonStyle = (disabled: boolean): React.CSSProperties => ({
  height: 24,
  padding: '0 8px',
  borderRadius: 999,
  border: '1px solid #bfdbfe',
  background: disabled ? '#eff6ff' : '#dbeafe',
  color: '#1d4ed8',
  fontSize: 11,
  fontWeight: 800,
  cursor: disabled ? 'default' : 'pointer',
  whiteSpace: 'nowrap',
  maxWidth: '100%',
});

const primaryButtonStyle = (disabled: boolean): React.CSSProperties => ({
  height: 40,
  padding: '0 16px',
  borderRadius: 12,
  border: '1px solid #1d4ed8',
  background: disabled ? '#bfdbfe' : '#1d4ed8',
  color: '#ffffff',
  fontSize: 13,
  fontWeight: 800,
  cursor: disabled ? 'default' : 'pointer',
  flex: '1 1 180px',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  maxWidth: '100%',
  whiteSpace: 'nowrap',
});

const formErrorStyle: React.CSSProperties = {
  border: '1px solid #fecaca',
  background: '#fef2f2',
  color: '#b91c1c',
  borderRadius: 12,
  padding: '10px 12px',
  fontSize: 12,
  fontWeight: 600,
};

function valuationShellStyle(mode: 'index' | 'stock'): React.CSSProperties {
  return {
    display: 'grid',
    gap: 12,
    minHeight: mode === 'stock' ? 0 : undefined,
    flex: mode === 'stock' ? 1 : undefined,
    overflowY: mode === 'stock' ? 'auto' : undefined,
    padding: mode === 'stock' ? 12 : undefined,
    paddingRight: mode === 'stock' ? 10 : undefined,
    border: mode === 'stock' ? '1px solid #dbe4ef' : undefined,
    borderRadius: mode === 'stock' ? 16 : undefined,
    background: mode === 'stock' ? '#ffffff' : undefined,
  };
}

export default DcfWorkbench;
