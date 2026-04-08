export type LinePoint = { time: string; value: number };
export type CandlestickPoint = { time: string; open: number; high: number; low: number; close: number };
export type ChartZone = { from: number; to: number; color: string };

export interface ChartSeries {
  id: string;
  seriesType: 'line' | 'candlestick' | 'histogram';
  color?: string;
  data: Array<LinePoint | CandlestickPoint>;
  priceScaleId?: string;
  returnSeries?: boolean;
  indicator?: boolean;
  indicatorGroup?: string;
  lineStyle?: string;
  priceLevels?: Array<{ price: number; color: string; title: string }>;
  zones?: ChartZone[];
}

export interface ChartPayload {
  mode: 'multi';
  series: ChartSeries[];
  dataLength: number;
  forcePercentage?: boolean;
}

export interface ChartSeriesEntry {
  name: string;
  pinned: boolean;
}

export interface SeriesHistoryStatus {
  loadedStart: string | null;
  loadedEnd: string | null;
  isComplete: boolean;
  hasOlder: boolean;
  seedPeriod: string | null;
  backfillInFlight: boolean;
  requestToken: string;
}

export type ChartHistoryBySeries = Record<string, SeriesHistoryStatus>;

export interface ChartSnapshot {
  payload: ChartPayload;
  entries: ChartSeriesEntry[];
  historyBySeries?: ChartHistoryBySeries;
}

export interface ChartMutation {
  mode: 'multi';
  upsertSeries: ChartSeries[];
  removedSeriesIds: string[];
  seriesOrder: string[];
  dataLength: number;
  forcePercentage?: boolean;
  entries: ChartSeriesEntry[];
}

export type ChartUpdate = ChartSnapshot | ChartMutation;
