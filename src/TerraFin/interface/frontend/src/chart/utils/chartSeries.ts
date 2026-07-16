/**
 * Series creation and incremental update helpers for the chart.
 */
import { AreaSeries, CandlestickSeries, HistogramSeries, LineSeries, LineStyle } from 'lightweight-charts';
import type { BandPoint, CandlestickPoint, ChartSeries, ChartZone, LinePoint } from '../types';
import { attachPriceLevelsPrimitive, clearNativePriceLines, detachPriceLevelsPrimitive, syncNativePriceLines } from './chartPriceLevels';
import { attachZonePrimitive, detachZonePrimitive } from './chartZones';

export type ChartApi = any; // eslint-disable-line
export type SeriesRef = any; // eslint-disable-line

const COLOR_PALETTE = ['#2196f3', '#ef5350', '#26a69a', '#ab47bc', '#ffa726', '#5c6bc0', '#66bb6a'];
const CANDLE_GREEN = '#26a69a';
const CANDLE_RED = '#ef5350';
// Band (stacked sentiment) colors — opaque so back-to-front fills hide each other.
// Match the app's semantic up/down tokens (--tf-up / --tf-down) with a slate neutral.
// Band layer palette by layer position (top layer first); the first three keep
// the original pos/neu/neg colors so existing bands render unchanged. Cycles
// for bands with more layers.
const BAND_LAYER_COLORS = ['#00d97e', '#64748b', '#ff5d5d', '#7c6df2', '#e8a13c'];
const BAND_PANE_INDEX = 1; // bands live in their own panes below price
const CANDLE_COLOR_PAIRS: Array<{ up: string; down: string }> = [
  { up: CANDLE_GREEN, down: CANDLE_RED },
  { up: '#1976d2', down: '#f57c00' },
];
const LINE_PALETTE_WHEN_CANDLESTICK = COLOR_PALETTE.filter((c) => c !== CANDLE_GREEN && c !== CANDLE_RED);

const RETURN_PRICE_FORMAT = {
  priceFormat: {
    type: 'custom' as const,
    formatter: (price: { valueOf(): number }) => Number(price.valueOf()).toFixed(2) + '%',
    minMove: 0.01,
  },
};

export interface SeriesSpec {
  key: string;
  id: string;
  kind: 'line' | 'candlestick' | 'histogram' | 'area';
  color: string;
  priceScaleId: string;
  paneIndex?: number;
  data: Array<LinePoint | CandlestickPoint>;
  originalData?: LinePoint[];
  indicator: boolean;
  lineStyle?: string;
  priceLevels?: Array<{ price: number; color: string; title: string }>;
  zones?: ChartZone[];
  renderZones?: boolean;
  upColor?: string;
  downColor?: string;
  recreateSignature: string;
  appearanceSignature: string;
  dataSignature: string;
}

export interface AddSeriesResult {
  seriesToId: Map<SeriesRef, string>;
  seriesToColor: Map<SeriesRef, string>;
  originalDataMap: Map<SeriesRef, LinePoint[]>;
}

function lineOptions(spec: SeriesSpec): Record<string, unknown> {
  const isReturnSeries = spec.originalData != null;
  return {
    priceScaleId: isReturnSeries ? 'right' : spec.priceScaleId,
    color: spec.color,
    lineWidth: 1,
    ...(isReturnSeries ? RETURN_PRICE_FORMAT : {}),
    ...(spec.indicator ? { lastValueVisible: false, priceLineVisible: false } : {}),
    ...(spec.lineStyle === 'dashed' ? { lineStyle: LineStyle.Dashed } : {}),
  };
}

function candlestickOptions(spec: SeriesSpec): Record<string, unknown> {
  return {
    priceScaleId: spec.priceScaleId,
    upColor: spec.upColor,
    downColor: spec.downColor,
    borderVisible: false,
    wickUpColor: spec.upColor,
    wickDownColor: spec.downColor,
  };
}

function histogramOptions(spec: SeriesSpec): Record<string, unknown> {
  return {
    priceScaleId: spec.priceScaleId,
    lastValueVisible: false,
    priceLineVisible: false,
    color: spec.color,
  };
}

function areaOptions(spec: SeriesSpec): Record<string, unknown> {
  // Solid fill (top=bottom, opaque) so cumulative areas stack into discrete bands.
  // Lock the band's own scale to a fixed, independent [0,1] (shares always span
  // 0..1) so it never autoscales/drifts with the data.
  return {
    priceScaleId: spec.priceScaleId,
    topColor: spec.color,
    bottomColor: spec.color,
    lineColor: spec.color,
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
    autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }),
  };
}

// A band's scale id is derived from its own id — layout is renderer policy,
// the backend item carries data only.
const bandScaleId = (item: ChartSeries): string => `band:${item.id}`;

// Layer keys in point order (JSON preserves the producer's field order),
// top layer first.
const bandLayerKeys = (pts: BandPoint[]): string[] =>
  Object.keys(pts[0] ?? {}).filter((k) => k !== 'time');

function bandAreaSpecs(item: ChartSeries, paneIndex: number): SeriesSpec[] {
  // Expand one band item into n cumulative area series (each single-value),
  // drawn back-to-front: layer i's value is the sum of layers i..n-1, so the
  // first key fills the full stack and the last key is the bottom band.
  const pts = item.data as BandPoint[];
  const scale = bandScaleId(item);
  const keys = bandLayerKeys(pts);
  return keys.map((suffix, i) => {
    const color = BAND_LAYER_COLORS[i % BAND_LAYER_COLORS.length];
    const tail = keys.slice(i);
    const data = pts.map((p) => ({
      time: p.time,
      value: tail.reduce((sum, k) => sum + (typeof p[k] === 'number' ? (p[k] as number) : 0), 0),
    }));
    return {
      key: `${item.id}::${suffix}`,
      id: `${item.id}::${suffix}`,
      kind: 'area' as const,
      color,
      priceScaleId: scale,
      paneIndex,
      data,
      indicator: false,
      appearanceSignature: JSON.stringify({ kind: 'area', priceScaleId: scale, color, pane: paneIndex }),
      dataSignature: dataSignature(data),
      recreateSignature: JSON.stringify({ kind: 'area', priceScaleId: scale, pane: paneIndex, suffix }),
    };
  });
}

function bandPaneAssignments(series: ChartSeries[]): Map<string, number> {
  // Each band gets its own pane below the price pane (allocated in series order).
  const panes = new Map<string, number>();
  series.forEach((item) => {
    if (item.seriesType !== 'band') return;
    const scale = bandScaleId(item);
    if (!panes.has(scale)) {
      panes.set(scale, BAND_PANE_INDEX + panes.size);
    }
  });
  return panes;
}

function pointSignature(point: Record<string, unknown> | undefined): string {
  if (!point) return '';
  return [
    String(point.time ?? ''),
    String(point.open ?? point.value ?? ''),
    String(point.high ?? ''),
    String(point.low ?? ''),
    String(point.close ?? point.value ?? ''),
  ].join(':');
}

function dataSignature(data: Array<LinePoint | CandlestickPoint>): string {
  const first = data[0] as Record<string, unknown> | undefined;
  const middle = data[Math.floor(data.length / 2)] as Record<string, unknown> | undefined;
  const last = data[data.length - 1] as Record<string, unknown> | undefined;
  return [String(data.length), pointSignature(first), pointSignature(middle), pointSignature(last)].join('|');
}

export function buildSeriesSpecs(
  series: ChartSeries[],
  opts: { hasCandlestick: boolean; returnMode: boolean }
): SeriesSpec[] {
  let lineColorIndex = 0;
  let candleIndex = 0;
  const seenZoneKeys = new Set<string>();
  const bandPanes = bandPaneAssignments(series);

  return series.flatMap((item): SeriesSpec | SeriesSpec[] => {
    if (item.seriesType === 'band') {
      return bandAreaSpecs(item, bandPanes.get(bandScaleId(item)) ?? BAND_PANE_INDEX);
    }

    const priceScaleId = item.priceScaleId ?? 'right';

    if (opts.returnMode && item.returnSeries && item.seriesType === 'candlestick') {
      const colors = CANDLE_COLOR_PAIRS[candleIndex % CANDLE_COLOR_PAIRS.length];
      candleIndex += 1;
      const lineData = (item.data as CandlestickPoint[]).map((point) => ({ time: point.time, value: point.close }));
      return {
        key: item.id,
        id: item.id,
        kind: 'line',
        color: colors.up,
        priceScaleId: 'right',
        data: lineData,
        originalData: lineData,
        indicator: false,
        appearanceSignature: JSON.stringify({
          kind: 'line',
          priceScaleId: 'right',
          color: colors.up,
        }),
        dataSignature: dataSignature(lineData),
        recreateSignature: JSON.stringify({
          kind: 'line',
          returnSeries: true,
          priceScaleId: 'right',
        }),
      };
    }

    if (item.seriesType === 'candlestick') {
      const colors = CANDLE_COLOR_PAIRS[candleIndex % CANDLE_COLOR_PAIRS.length];
      candleIndex += 1;
      return {
        key: item.id,
        id: item.id,
        kind: 'candlestick',
        color: colors.up,
        priceScaleId,
        data: item.data as CandlestickPoint[],
        indicator: false,
        upColor: colors.up,
        downColor: colors.down,
        appearanceSignature: JSON.stringify({
          kind: 'candlestick',
          priceScaleId,
          upColor: colors.up,
          downColor: colors.down,
        }),
        dataSignature: dataSignature(item.data as CandlestickPoint[]),
        recreateSignature: JSON.stringify({
          kind: 'candlestick',
          priceScaleId,
        }),
      };
    }

    if (item.seriesType === 'histogram') {
      return {
        key: item.id,
        id: item.id,
        kind: 'histogram',
        color: item.color ?? '#888',
        priceScaleId,
        data: item.data as LinePoint[],
        indicator: false,
        appearanceSignature: JSON.stringify({
          kind: 'histogram',
          priceScaleId,
          color: item.color ?? '#888',
        }),
        dataSignature: dataSignature(item.data as LinePoint[]),
        recreateSignature: JSON.stringify({
          kind: 'histogram',
          priceScaleId,
        }),
      };
    }

    const palette = opts.hasCandlestick && !opts.returnMode ? LINE_PALETTE_WHEN_CANDLESTICK : COLOR_PALETTE;
    const color = item.color ?? palette[lineColorIndex % palette.length];
    lineColorIndex += 1;
    const isReturnSeries = opts.returnMode && item.returnSeries === true;
    const linePriceScaleId = isReturnSeries ? 'right' : priceScaleId;
    const zones = item.zones;
    const zoneKey =
      zones && zones.length > 0 ? `${isReturnSeries ? 'right' : priceScaleId}|${JSON.stringify(zones)}` : null;
    const renderZones = zoneKey != null && !seenZoneKeys.has(zoneKey);
    if (renderZones && zoneKey) {
      seenZoneKeys.add(zoneKey);
    }

    return {
      key: item.id,
      id: item.id,
      kind: 'line',
      color,
      priceScaleId: linePriceScaleId,
      data: item.data as LinePoint[],
      originalData: isReturnSeries ? (item.data as LinePoint[]) : undefined,
      indicator: item.indicator === true,
      lineStyle: item.lineStyle,
      priceLevels: item.priceLevels,
      zones,
      renderZones,
      appearanceSignature: JSON.stringify({
        kind: 'line',
        priceScaleId: linePriceScaleId,
        color,
        indicator: item.indicator === true,
        lineStyle: item.lineStyle ?? '',
        priceLevels: item.priceLevels ?? [],
        renderZones,
        zones: renderZones ? zones ?? [] : [],
      }),
      dataSignature: dataSignature((item.data as LinePoint[]) ?? []),
      recreateSignature: JSON.stringify({
        kind: 'line',
        priceScaleId: linePriceScaleId,
        returnSeries: isReturnSeries,
        indicator: item.indicator === true,
        lineStyle: item.lineStyle ?? '',
        priceLevels: item.priceLevels ?? [],
      }),
    };
  });
}

export function createSeriesFromSpec(chart: ChartApi, spec: SeriesSpec): SeriesRef {
  if (spec.kind === 'candlestick') {
    const series = chart.addSeries(CandlestickSeries, candlestickOptions(spec));
    series.setData(spec.data as CandlestickPoint[]);
    return series;
  }

  if (spec.kind === 'histogram') {
    const series = chart.addSeries(HistogramSeries, histogramOptions(spec));
    series.setData(spec.data);
    return series;
  }

  if (spec.kind === 'area') {
    const series =
      spec.paneIndex != null
        ? chart.addSeries(AreaSeries, areaOptions(spec), spec.paneIndex)
        : chart.addSeries(AreaSeries, areaOptions(spec));
    series.setData(spec.data as LinePoint[]);
    return series;
  }

  const series =
    spec.paneIndex != null
      ? chart.addSeries(LineSeries, lineOptions(spec), spec.paneIndex)
      : chart.addSeries(LineSeries, lineOptions(spec));
  series.setData((spec.originalData ?? spec.data) as LinePoint[]);
  attachZonePrimitive(series, spec.renderZones ? spec.zones : undefined);
  attachPriceLevelsPrimitive(series, spec.priceLevels);
  syncNativePriceLines(series, spec.priceLevels);
  return series;
}

export function applySeriesAppearance(series: SeriesRef, spec: SeriesSpec): void {
  if (spec.kind === 'candlestick') {
    series.applyOptions(candlestickOptions(spec));
    return;
  }
  if (spec.kind === 'histogram') {
    series.applyOptions(histogramOptions(spec));
    return;
  }
  if (spec.kind === 'area') {
    series.applyOptions(areaOptions(spec));
    return;
  }
  series.applyOptions(lineOptions(spec));
  attachZonePrimitive(series, spec.renderZones ? spec.zones : undefined);
  attachPriceLevelsPrimitive(series, spec.priceLevels);
  syncNativePriceLines(series, spec.priceLevels);
}

export function applySeriesData(series: SeriesRef, spec: SeriesSpec): void {
  series.setData((spec.originalData ?? spec.data) as Array<LinePoint | CandlestickPoint>);
}

export function destroySeries(series: SeriesRef): void {
  clearNativePriceLines(series);
  detachPriceLevelsPrimitive(series);
  detachZonePrimitive(series);
}

export function addAllSeries(
  chart: ChartApi,
  series: ChartSeries[],
  opts: { hasCandlestick: boolean; returnMode: boolean }
): AddSeriesResult {
  const seriesToId = new Map<SeriesRef, string>();
  const seriesToColor = new Map<SeriesRef, string>();
  const originalDataMap = new Map<SeriesRef, LinePoint[]>();

  buildSeriesSpecs(series, opts).forEach((spec) => {
    const seriesRef = createSeriesFromSpec(chart, spec);
    seriesToId.set(seriesRef, spec.id);
    seriesToColor.set(seriesRef, spec.color);
    if (spec.originalData) {
      originalDataMap.set(seriesRef, spec.originalData);
    }
  });

  return { seriesToId, seriesToColor, originalDataMap };
}
