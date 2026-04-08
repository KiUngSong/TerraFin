export interface Sp500YearAssumptionFormValue {
  yearOffset: number;
  growthPct: string;
  payoutRatioPct: string;
  buybackRatioPct: string;
  equityRiskPremiumPct: string;
}

export interface Sp500DcfFormPreset {
  baseYear: number;
  baseYearEps: string;
  terminalGrowthPct: string;
  terminalEquityRiskPremiumPct: string;
  terminalRoePct: string;
  yearlyAssumptions: Sp500YearAssumptionFormValue[];
}

export const SP500_DCF_FORM_PRESET: Sp500DcfFormPreset = {
  baseYear: 2025,
  baseYearEps: '274.14',
  terminalGrowthPct: '4.00',
  terminalEquityRiskPremiumPct: '4.00',
  terminalRoePct: '20.00',
  yearlyAssumptions: [
    { yearOffset: 1, growthPct: '14.40', payoutRatioPct: '32.50', buybackRatioPct: '45.70', equityRiskPremiumPct: '4.50' },
    { yearOffset: 2, growthPct: '11.50', payoutRatioPct: '32.20', buybackRatioPct: '46.00', equityRiskPremiumPct: '4.40' },
    { yearOffset: 3, growthPct: '9.50', payoutRatioPct: '31.80', buybackRatioPct: '46.20', equityRiskPremiumPct: '4.30' },
    { yearOffset: 4, growthPct: '7.50', payoutRatioPct: '31.20', buybackRatioPct: '46.50', equityRiskPremiumPct: '4.20' },
    { yearOffset: 5, growthPct: '5.80', payoutRatioPct: '30.80', buybackRatioPct: '46.80', equityRiskPremiumPct: '4.10' },
  ],
};
