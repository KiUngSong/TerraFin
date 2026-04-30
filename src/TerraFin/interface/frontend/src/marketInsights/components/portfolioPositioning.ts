export interface PortfolioHoldingRow {
  History?: (number | null)[] | string;
  Stock: string;
  ['% of Portfolio']: number | string;
  ['Recent Activity']: string;
  Updated: number | string;
  Shares?: string;
  ['Reported Price']?: string;
}

interface PortfolioTone {
  fill: string;
  edge: string;
  label: string;
}

const PORTFOLIO_TONES = {
  strongGreen: {
    fill: '#166534',
    edge: '#14532d',
    label: 'New / +10%+',
  },
  mediumGreen: {
    fill: '#237a57',
    edge: '#195e43',
    label: '+5% to +10%',
  },
  lightGreen: {
    fill: '#49a078',
    edge: '#2f855a',
    label: '+2.5% to +5%',
  },
  neutral: {
    fill: '#51627a',
    edge: '#334155',
    label: 'Within +/-2.5%',
  },
  lightRed: {
    fill: '#d96c78',
    edge: '#c24e5c',
    label: '-2.5% to -5%',
  },
  mediumRed: {
    fill: '#c44a55',
    edge: '#a1303f',
    label: '-5% to -10%',
  },
  strongRed: {
    fill: '#8b1e2d',
    edge: '#6e1523',
    label: '-10%+',
  },
} satisfies Record<string, PortfolioTone>;

export const PORTFOLIO_LEGEND = [
  PORTFOLIO_TONES.strongGreen,
  PORTFOLIO_TONES.mediumGreen,
  PORTFOLIO_TONES.lightGreen,
  PORTFOLIO_TONES.neutral,
  PORTFOLIO_TONES.lightRed,
  PORTFOLIO_TONES.mediumRed,
  PORTFOLIO_TONES.strongRed,
];

export const parsePortfolioWeight = (value: number | string): number => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }

  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const parsePortfolioUpdate = (value: number | string): number => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }

  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const splitPortfolioStockLabel = (stock: string): { ticker: string; company: string } => {
  const [ticker, ...rest] = (stock || '').split(' - ');
  return {
    ticker: ticker || stock,
    company: rest.join(' - ') || '',
  };
};

export const getPortfolioRowKey = (row: PortfolioHoldingRow): string =>
  [row.Stock, row['% of Portfolio'], row.Updated, row['Recent Activity']].join('|');

export const getPortfolioTone = (
  updatedRaw: number | string,
  recentActivityRaw: string,
): PortfolioTone => {
  const updated = parsePortfolioUpdate(updatedRaw);
  const recentActivity = (recentActivityRaw || '').trim();

  if (recentActivity === 'Buy' || updated >= 10) {
    return PORTFOLIO_TONES.strongGreen;
  }

  if (updated >= 5) {
    return PORTFOLIO_TONES.mediumGreen;
  }

  if (updated >= 2.5) {
    return PORTFOLIO_TONES.lightGreen;
  }

  if (updated > -2.5) {
    return PORTFOLIO_TONES.neutral;
  }

  if (updated > -5) {
    return PORTFOLIO_TONES.lightRed;
  }

  if (updated > -10) {
    return PORTFOLIO_TONES.mediumRed;
  }

  return PORTFOLIO_TONES.strongRed;
};

export const formatPortfolioActivity = (row: PortfolioHoldingRow): string => {
  const recentActivity = (row['Recent Activity'] || '').trim();
  if (recentActivity) {
    return recentActivity;
  }
  return 'Unchanged';
};

export const formatSignedPercent = (value: number): string => {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

export const hasPortfolioFieldValue = (value: string | undefined): boolean => {
  if (!value) {
    return false;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed !== '-';
};
