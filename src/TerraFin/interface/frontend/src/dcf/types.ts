export interface DcfProjectionPoint {
  yearOffset: number;
  forecastDate: string;
  growthPct: number;
  cashFlowPerShare: number;
  discountRatePct: number;
  discountFactor: number;
  presentValue: number;
}

export interface DcfScenario {
  key: string;
  label: string;
  status: string;
  growthShiftPct: number;
  discountRateShiftBps: number;
  terminalGrowthShiftBps: number;
  intrinsicValue: number | null;
  upsidePct: number | null;
  terminalValue: number | null;
  terminalGrowthPct: number;
  terminalDiscountRatePct: number;
  projectedCashFlows: DcfProjectionPoint[];
}

export interface DcfSensitivityCell {
  terminalGrowthShiftBps: number;
  discountRateShiftBps: number;
  intrinsicValue: number | null;
  upsidePct: number | null;
}

export interface DcfValuationPayload {
  status: string;
  entityType: string;
  symbol: string;
  asOf: string;
  currentPrice: number | null;
  currentIntrinsicValue: number | null;
  upsidePct: number | null;
  scenarios: Record<string, DcfScenario>;
  assumptions: Record<string, unknown>;
  sensitivity: {
    discountRateShiftBps: number[];
    terminalGrowthShiftBps: number[];
    cells: DcfSensitivityCell[];
  };
  rateCurve: {
    source: string;
    asOf: string;
    fitRmse?: number | null;
    fallbackUsed?: boolean;
    points: Array<{ maturityYears: number; yieldPct: number; label: string }>;
    fittedPoints: Array<{ maturityYears: number; yieldPct: number; label: string }>;
  };
  dataQuality: {
    mode?: string;
    sources?: string[];
    valuationMode?: string;
  };
  warnings: string[];
  methods?: Array<{
    key: string;
    label: string;
    description: string;
    weight: number;
    currentIntrinsicValue: number | null;
    upsidePct: number | null;
  }>;
}

export interface RateCurvePayload {
  source: string;
  asOf: string;
  fitRmse?: number | null;
  fallbackUsed?: boolean;
  points: Array<{ maturityYears: number; yieldPct: number; label: string }>;
  fittedPoints: Array<{ maturityYears: number; yieldPct: number; label: string }>;
}

export interface ReverseDcfPayload {
  status: string;
  entityType: string;
  symbol: string;
  asOf: string;
  currentPrice: number | null;
  baseCashFlowPerShare: number | null;
  impliedGrowthPct: number | null;
  modelPrice: number | null;
  projectionYears: number;
  growthProfile: {
    key: string;
    label: string;
    description: string;
  };
  priceToCashFlowMultiple: number | null;
  terminalGrowthPct: number | null;
  terminalDiscountRatePct: number | null;
  terminalValue: number | null;
  terminalPresentValueWeightPct: number | null;
  discountSpreadPct: number | null;
  assumptions: Record<string, unknown>;
  projectedCashFlows: DcfProjectionPoint[];
  rateCurve: RateCurvePayload;
  dataQuality: {
    mode?: string;
    sources?: string[];
    valuationMode?: string;
  };
  warnings: string[];
}

export interface BetaEstimatePayload {
  status: string;
  symbol: string;
  benchmarkSymbol: string | null;
  benchmarkLabel: string | null;
  methodId: string;
  adjustedMethodId: string;
  lookbackYears: number;
  frequency: string;
  beta: number | null;
  adjustedBeta: number | null;
  observations: number;
  rSquared: number | null;
  warnings: string[];
}
