import type { ChartMutation, ChartPayload, ChartSeries, ChartSnapshot } from './types';

export function isChartMutation(update: ChartMutation | ChartSnapshot | null | undefined): update is ChartMutation {
  return Boolean(update && 'upsertSeries' in update && 'seriesOrder' in update);
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

function seriesSignature(series: ChartSeries): string {
  const data = series.data ?? [];
  const first = data[0] as Record<string, unknown> | undefined;
  const middle = data[Math.floor(data.length / 2)] as Record<string, unknown> | undefined;
  const last = data[data.length - 1] as Record<string, unknown> | undefined;
  const priceLevels = (series.priceLevels ?? [])
    .map((level) => `${level.price}:${level.color}:${level.title}`)
    .join(',');
  const zones = (series.zones ?? [])
    .map((zone) => `${zone.from}:${zone.to}:${zone.color}`)
    .join(',');

  return [
    series.id,
    series.seriesType,
    series.color ?? '',
    series.priceScaleId ?? '',
    series.returnSeries ? '1' : '0',
    series.indicator ? '1' : '0',
    series.indicatorGroup ?? '',
    series.lineStyle ?? '',
    priceLevels,
    zones,
    String(data.length),
    pointSignature(first),
    pointSignature(middle),
    pointSignature(last),
  ].join('|');
}

export function payloadSignature(payload: ChartPayload): string {
  return [
    payload.mode,
    payload.forcePercentage === true ? '1' : '0',
    ...(payload.series ?? []).map(seriesSignature),
  ].join('||');
}

export function entriesSignature(entries: ChartSnapshot['entries']): string {
  return entries.map((entry) => `${entry.name}:${entry.pinned ? '1' : '0'}`).join('|');
}

export function applyMutationToPayload(
  current: ChartPayload | null,
  mutation: ChartMutation
): ChartPayload {
  const existingSeries = current?.series ?? [];
  const nextSeriesById = new Map<string, ChartSeries>();

  for (const series of existingSeries) {
    nextSeriesById.set(series.id, series);
  }
  for (const id of mutation.removedSeriesIds ?? []) {
    nextSeriesById.delete(id);
  }
  for (const series of mutation.upsertSeries ?? []) {
    nextSeriesById.set(series.id, series);
  }

  const nextSeries: ChartSeries[] = [];
  const seen = new Set<string>();
  for (const id of mutation.seriesOrder ?? []) {
    const series = nextSeriesById.get(id);
    if (!series) continue;
    nextSeries.push(series);
    seen.add(id);
  }
  for (const series of Array.from(nextSeriesById.values())) {
    if (seen.has(series.id)) continue;
    nextSeries.push(series);
  }

  return {
    mode: mutation.mode,
    series: nextSeries,
    dataLength: mutation.dataLength,
    forcePercentage: mutation.forcePercentage === true,
  };
}
