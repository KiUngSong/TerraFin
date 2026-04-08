import React from 'react';
import InfoHint from './InfoHint';
import { BetaEstimatePayload, ReverseDcfPayload } from './types';
import { useBetaEstimate } from './useBetaEstimate';
import { DcfFetchRequest, useDcfValuation } from './useDcfValuation';

type GrowthProfileKey = 'high_growth' | 'early_maturity' | 'fully_mature';

interface ReverseDcfFormState {
  currentPrice: string;
  baseCashFlowPerShare: string;
  terminalGrowthPct: string;
  beta: string;
  equityRiskPremiumPct: string;
  projectionYears: 5 | 10 | 15;
  growthProfile: GrowthProfileKey;
}

const HORIZON_OPTIONS: Array<{ value: 5 | 10 | 15; label: string }> = [
  { value: 5, label: '5Y' },
  { value: 10, label: '10Y' },
  { value: 15, label: '15Y' },
];

const PROFILE_OPTIONS: Array<{ value: GrowthProfileKey; label: string; description: string }> = [
  {
    value: 'high_growth',
    label: 'High Growth',
    description: 'Growth stays elevated for longer.',
  },
  {
    value: 'early_maturity',
    label: 'Early Maturity',
    description: 'Growth fades linearly toward steady state.',
  },
  {
    value: 'fully_mature',
    label: 'Fully Mature',
    description: 'Growth converges toward terminal quickly.',
  },
];

const DEFAULT_TERMINAL_GROWTH = '3.00';
const DEFAULT_ERP = '5.00';
const COMPUTE_BETA_INFO =
  'Computes TerraFin beta_5y_monthly from 5 years of monthly returns against the mapped benchmark and fills the Beta field. The adjusted beta is shown only as reference. This does not rerun Reverse DCF automatically.';

const ReverseDcfWorkbench: React.FC<{
  endpoint: string | null;
  enabled?: boolean;
  blockedMessage?: string;
  symbolLabel?: string;
  betaEndpoint?: string | null;
  defaultCurrentPrice?: number | null;
  defaultBeta?: number | null;
  onValuationStateChange?: (state: {
    payload: ReverseDcfPayload | null;
    loading: boolean;
    error: string | null;
    hasValuationState: boolean;
  }) => void;
}> = ({
  endpoint,
  enabled = true,
  blockedMessage = 'This feature is not ready yet.',
  symbolLabel,
  betaEndpoint = null,
  defaultCurrentPrice = null,
  defaultBeta = null,
  onValuationStateChange,
}) => {
  const [form, setForm] = React.useState(() => buildFormState(defaultCurrentPrice, defaultBeta));
  const [request, setRequest] = React.useState<DcfFetchRequest | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);
  const { data, loading, error } = useDcfValuation<ReverseDcfPayload>(endpoint, request, enabled);
  const {
    data: betaEstimate,
    loading: betaLoading,
    error: betaError,
    compute: computeBeta,
    reset: resetBetaEstimate,
  } = useBetaEstimate(betaEndpoint, enabled);
  const hasValuationState = Boolean(request || loading || error || data);

  React.useEffect(() => {
    setForm(buildFormState(defaultCurrentPrice, defaultBeta));
    setRequest(null);
    setFormError(null);
    resetBetaEstimate();
  }, [defaultBeta, defaultCurrentPrice, endpoint, resetBetaEstimate, symbolLabel]);

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

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const currentPrice = parseOptionalNumber(form.currentPrice);
    if (currentPrice != null && currentPrice <= 0) {
      setFormError('Current price must be positive when you override it.');
      return;
    }
    const baseCashFlowPerShare = parseOptionalNumber(form.baseCashFlowPerShare);
    if (baseCashFlowPerShare != null && baseCashFlowPerShare <= 0) {
      setFormError('FCF per share must be positive when you override it.');
      return;
    }
    setFormError(null);
    setRequest({
      method: 'POST',
      requestId: Date.now(),
      body: compactRecord({
        currentPrice,
        baseCashFlowPerShare,
        terminalGrowthPct: parseOptionalNumber(form.terminalGrowthPct),
        beta: parseOptionalNumber(form.beta),
        equityRiskPremiumPct: parseOptionalNumber(form.equityRiskPremiumPct),
        projectionYears: form.projectionYears,
        growthProfile: form.growthProfile,
      }),
    });
  };

  const handleReset = () => {
    setForm(buildFormState(defaultCurrentPrice, defaultBeta));
    setRequest(null);
    setFormError(null);
    resetBetaEstimate();
  };

  const handleComputeBeta = async () => {
    const payload = await computeBeta();
    if (payload?.status === 'ready' && payload.beta != null) {
      setForm((current) => ({ ...current, beta: payload.beta!.toFixed(2) }));
    }
  };

  const betaHelper = buildBetaHelper(betaEstimate, betaError, betaLoading);

  return (
    <div style={rootStyle}>
      <form onSubmit={handleSubmit} style={workbenchStyle}>
        <div style={headerStyle}>
          <div>
            <div style={eyebrowStyle}>Reverse DCF</div>
            <div style={headlineStyle}>{symbolLabel || 'Stock'}</div>
          </div>
          <div style={badgeStyle}>P/FCF</div>
        </div>

        <div style={stepRailStyle}>
          <StepPill step="1" label="Inputs" active />
          <StepPill step="2" label="Assumptions" active />
          <StepPill step="3" label="Result" active={hasValuationState} />
        </div>

        <div style={sectionStyle}>
          <div style={sectionTitleStyle}>Inputs</div>
          <div style={fieldGridStyle}>
            <NumericField
              label="Current Price"
              value={form.currentPrice}
              step="0.01"
              placeholder={formatPlaceholder(defaultCurrentPrice)}
              onChange={(value) => setForm((current) => ({ ...current, currentPrice: value }))}
            />
            <NumericField
              label="FCF / Share (TTM)"
              value={form.baseCashFlowPerShare}
              step="0.0001"
              placeholder="Auto"
              onChange={(value) => setForm((current) => ({ ...current, baseCashFlowPerShare: value }))}
            />
          </div>
          <div style={helperTextStyle}>GAAP free cash flow is used today. Leave fields blank to use TerraFin defaults.</div>
        </div>

        <div style={sectionStyle}>
          <div style={sectionTitleStyle}>Assumptions</div>
          <div style={fieldGridStyle}>
            <NumericField
              label="Terminal Growth %"
              value={form.terminalGrowthPct}
              step="0.01"
              onChange={(value) => setForm((current) => ({ ...current, terminalGrowthPct: value }))}
            />
            <NumericField
              label="Beta"
              value={form.beta}
              step="0.01"
              placeholder={formatPlaceholder(defaultBeta)}
              onChange={(value) => setForm((current) => ({ ...current, beta: value }))}
              action={
                <span style={fieldActionClusterStyle}>
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
              helperText={betaHelper}
            />
            <NumericField
              label="Equity Risk Premium %"
              value={form.equityRiskPremiumPct}
              step="0.01"
              onChange={(value) => setForm((current) => ({ ...current, equityRiskPremiumPct: value }))}
            />
          </div>

          <div style={controlGroupStyle}>
            <div style={controlLabelStyle}>Projection Horizon</div>
            <SegmentedControl
              options={HORIZON_OPTIONS}
              value={form.projectionYears}
              onChange={(value) => setForm((current) => ({ ...current, projectionYears: value }))}
            />
          </div>

          <div style={controlGroupStyle}>
            <div style={controlLabelStyle}>Growth Profile</div>
            <div style={profileGridStyle}>
              {PROFILE_OPTIONS.map((option) => {
                const active = option.value === form.growthProfile;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setForm((current) => ({ ...current, growthProfile: option.value }))}
                    style={profileButtonStyle(active)}
                  >
                    <div style={profileLabelStyle}>{option.label}</div>
                    <div style={profileDescriptionStyle}>{option.description}</div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {formError ? <div style={errorStyle}>{formError}</div> : null}

        <div style={actionRowStyle}>
          <button type="button" onClick={handleReset} style={secondaryButtonStyle}>
            Reset
          </button>
          <button type="submit" disabled={loading} style={primaryButtonStyle(loading)}>
            {loading ? 'Estimating...' : 'Estimate Implied Growth'}
          </button>
        </div>
      </form>
    </div>
  );
};

const StepPill: React.FC<{ step: string; label: string; active?: boolean }> = ({ step, label, active = false }) => (
  <div style={stepPillStyle(active)}>
    <span style={stepNumberStyle(active)}>{step}</span>
    <span>{label}</span>
  </div>
);

const NumericField: React.FC<{
  label: string;
  value: string;
  step: string;
  placeholder?: string;
  onChange: (value: string) => void;
  action?: React.ReactNode;
  helperText?: React.ReactNode;
}> = ({ label, value, step, placeholder, onChange, action, helperText }) => (
  <label style={fieldStyle}>
    <span style={fieldLabelRowStyle}>
      <span style={fieldLabelStyle}>{label}</span>
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
    {helperText ? <span style={fieldHelperTextStyle}>{helperText}</span> : null}
  </label>
);

const SegmentedControl = <T extends string | number>({
  options,
  value,
  onChange,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
}) => (
  <div style={segmentWrapStyle}>
    {options.map((option) => {
      const active = option.value === value;
      return (
        <button key={`${option.value}`} type="button" onClick={() => onChange(option.value)} style={segmentButtonStyle(active)}>
          {option.label}
        </button>
      );
    })}
  </div>
);

function buildFormState(defaultCurrentPrice: number | null | undefined, defaultBeta: number | null | undefined): ReverseDcfFormState {
  return {
    currentPrice: typeof defaultCurrentPrice === 'number' ? defaultCurrentPrice.toFixed(2) : '',
    baseCashFlowPerShare: '',
    terminalGrowthPct: DEFAULT_TERMINAL_GROWTH,
    beta: typeof defaultBeta === 'number' ? defaultBeta.toFixed(2) : '',
    equityRiskPremiumPct: DEFAULT_ERP,
    projectionYears: 5,
    growthProfile: 'early_maturity',
  };
}

function parseOptionalNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatPlaceholder(value: number | null | undefined): string | undefined {
  return typeof value === 'number' ? value.toFixed(2) : undefined;
}

function compactRecord<T extends Record<string, unknown>>(record: T): Partial<T> {
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

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  height: '100%',
};

const workbenchStyle: React.CSSProperties = {
  display: 'grid',
  gap: 14,
  border: '1px solid #dbe4ef',
  borderRadius: 16,
  padding: 14,
  background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
};

const headerStyle: React.CSSProperties = {
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
  marginTop: 2,
  fontSize: 20,
  fontWeight: 800,
  color: '#0f172a',
  lineHeight: 1.2,
};

const badgeStyle: React.CSSProperties = {
  borderRadius: 999,
  padding: '8px 12px',
  background: '#dcfce7',
  color: '#166534',
  fontSize: 11,
  fontWeight: 800,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
};

const stepRailStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  flexWrap: 'wrap',
};

const stepPillStyle = (active: boolean): React.CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  borderRadius: 999,
  padding: '6px 10px',
  background: active ? '#ecfdf5' : '#f8fafc',
  color: active ? '#166534' : '#64748b',
  border: `1px solid ${active ? '#86efac' : '#e2e8f0'}`,
  fontSize: 12,
  fontWeight: 700,
});

const stepNumberStyle = (active: boolean): React.CSSProperties => ({
  width: 20,
  height: 20,
  borderRadius: '50%',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: active ? '#22c55e' : '#ffffff',
  color: active ? '#ffffff' : '#64748b',
  fontSize: 11,
  fontWeight: 800,
});

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

const fieldGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
  gap: 10,
};

const fieldStyle: React.CSSProperties = {
  display: 'grid',
  gap: 6,
  border: '1px solid #dbe4ef',
  borderRadius: 12,
  padding: '10px 12px',
  background: '#ffffff',
};

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
};

const fieldLabelRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: 8,
  flexWrap: 'wrap',
};

const fieldActionClusterStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  flexWrap: 'wrap',
  minWidth: 0,
};

const inputStyle: React.CSSProperties = {
  height: 36,
  border: '1px solid #cbd5e1',
  borderRadius: 10,
  padding: '0 10px',
  fontSize: 14,
  color: '#0f172a',
  background: '#f8fafc',
};

const helperTextStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#475569',
  lineHeight: 1.5,
};

const fieldHelperTextStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#475569',
  lineHeight: 1.45,
};

const controlGroupStyle: React.CSSProperties = {
  display: 'grid',
  gap: 8,
};

const controlLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  letterSpacing: '0.03em',
  textTransform: 'uppercase',
};

const segmentWrapStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
  gap: 0,
  border: '1px solid #cbd5e1',
  borderRadius: 12,
  overflow: 'hidden',
  background: '#ffffff',
};

const segmentButtonStyle = (active: boolean): React.CSSProperties => ({
  height: 42,
  border: 'none',
  borderRight: active ? 'none' : '1px solid #e2e8f0',
  background: active ? '#334155' : '#ffffff',
  color: active ? '#ffffff' : '#334155',
  fontSize: 13,
  fontWeight: 700,
  cursor: 'pointer',
});

const profileGridStyle: React.CSSProperties = {
  display: 'grid',
  gap: 8,
};

const profileButtonStyle = (active: boolean): React.CSSProperties => ({
  border: `1px solid ${active ? '#93c5fd' : '#dbe4ef'}`,
  borderRadius: 12,
  padding: '10px 12px',
  background: active ? '#eff6ff' : '#ffffff',
  color: '#0f172a',
  textAlign: 'left',
  cursor: 'pointer',
  display: 'grid',
  gap: 4,
});

const profileLabelStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 700,
};

const profileDescriptionStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#475569',
  lineHeight: 1.45,
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

const errorStyle: React.CSSProperties = {
  border: '1px solid #fecaca',
  background: '#fef2f2',
  color: '#b91c1c',
  borderRadius: 12,
  padding: '10px 12px',
  fontSize: 12,
  fontWeight: 600,
};

export default ReverseDcfWorkbench;
