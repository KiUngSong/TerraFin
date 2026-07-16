export type LinePoint = { time: string; value: number };
export type CandlestickPoint = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};
// A band point carries n ordered layer shares that stack to 1.0 (e.g. news
// sentiment pos/neu/neg). Key order = layer order, top layer first; rendered
// as n cumulative area series, not a single line.
export type BandPoint = { [layer: string]: number | string; time: string };
export type ChartZone = { from: number; to: number; color: string };

export interface ChartSeries {
  id: string;
  seriesType: 'line' | 'candlestick' | 'histogram' | 'band';
  color?: string;
  data: Array<LinePoint | CandlestickPoint | BandPoint>;
  priceScaleId?: string;
  returnSeries?: boolean;
  indicator?: boolean;
  indicatorGroup?: string;
  description?: string;
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
