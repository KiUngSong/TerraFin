export const POLL_MS = 2000;
export const CHART_API_BASE = '/chart/api';

import { BREAKPOINTS } from '../shared/responsive';

export const TOP_BAR_HEIGHT = 40;
export const BOTTOM_BAR_HEIGHT = 40;
// Container-width threshold — NOT a viewport breakpoint. Drives toolbar
// density only; sourced from the shared BREAKPOINTS object for visibility
// even though it's applied to `el.clientWidth`, not `window.innerWidth`.
export const DEFAULT_CHART_COMPACT_BREAKPOINT = BREAKPOINTS.CHART_COMPACT_MAX;
export const DEFAULT_PRICE_SCALE_MARGINS = { top: 0.05, bottom: 0.02 } as const;

export const FONT_FAMILY =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

export interface ChartScaleMargins {
  top: number;
  bottom: number;
}

export interface RangeAvailability {
  disabled?: boolean;
  tooltip?: string;
}

export const DAYS_OPTIONS = [
  { id: 'daily', label: '1 day' },
  { id: 'weekly', label: '1 week' },
  { id: 'monthly', label: '1 month' },
  { id: 'yearly', label: '1 year' },
] as const;

export const VIEW_LETTER: Record<string, string> = {
  daily: 'D',
  weekly: 'W',
  monthly: 'M',
  yearly: 'Y',
};

export type RangeId = '3M' | '6M' | '1Y' | '5Y' | 'ALL';

export const RANGE_BUTTONS: Array<{
  id: RangeId;
  label: string;
  view: string;
  tooltip: string;
  monthsBack: number | null;
}> = [
  { id: '3M', label: '3M', view: 'daily', tooltip: '3 months in 1 day intervals', monthsBack: 3 },
  { id: '6M', label: '6M', view: 'daily', tooltip: '6 months in 1 day intervals', monthsBack: 6 },
  { id: '1Y', label: '1Y', view: 'daily', tooltip: '1 year in 1 day intervals', monthsBack: 12 },
  { id: '5Y', label: '5Y', view: 'weekly', tooltip: '5 years in 1 week intervals', monthsBack: 60 },
  { id: 'ALL', label: 'ALL', view: 'monthly', tooltip: 'All data in 1 month intervals', monthsBack: null },
];
