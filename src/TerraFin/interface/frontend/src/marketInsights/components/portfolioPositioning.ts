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

// Magnitude tones for treemap tiles. Greens → tf-up family, reds → tf-down,
// neutral → tf-muted. Magnitude within each direction is conveyed by alpha
// (kept solid here; intensity stepping via the tone scale is the DNA we want
// to preserve in a terminal-flat way — saturation varies, hue locks to the
// semantic token).
const PORTFOLIO_TONES = {
  strongGreen: {
    fill: 'var(--tf-up)',
    edge: 'var(--tf-up)',
    label: 'New / +10%+',
  },
  mediumGreen: {
    fill: 'var(--tf-up)',
    edge: 'var(--tf-up)',
    label: '+5% to +10%',
  },
  lightGreen: {
    fill: 'var(--tf-up)',
    edge: 'var(--tf-up)',
    label: '+2.5% to +5%',
  },
  neutral: {
    fill: 'var(--tf-muted)',
    edge: 'var(--tf-muted)',
    label: 'Within +/-2.5%',
  },
  lightRed: {
    fill: 'var(--tf-down)',
    edge: 'var(--tf-down)',
    label: '-2.5% to -5%',
  },
  mediumRed: {
    fill: 'var(--tf-down)',
    edge: 'var(--tf-down)',
    label: '-5% to -10%',
  },
  strongRed: {
    fill: 'var(--tf-down)',
    edge: 'var(--tf-down)',
    label: '-10%+',
  },
} satisfies Record<string, PortfolioTone>;

// Tiles render only 3 distinct colors (up / neutral / down) — the magnitude
// sub-buckets all resolve to the same token, so a 7-row legend showed 3
// identical green dots + 3 identical red. Legend matches what the eye sees;
// exact magnitude is on each tile's label/tooltip.
export const PORTFOLIO_LEGEND = [
  { fill: 'var(--tf-up)', edge: 'var(--tf-up)', label: 'Added / up' },
  { fill: 'var(--tf-muted)', edge: 'var(--tf-muted)', label: 'Within +/-2.5%' },
  { fill: 'var(--tf-down)', edge: 'var(--tf-down)', label: 'Trimmed / down' },
] satisfies PortfolioTone[];

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
