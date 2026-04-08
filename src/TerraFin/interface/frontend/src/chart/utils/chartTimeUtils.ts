/**
 * Pure utility functions for time conversions and visible range calculations.
 */
import { RANGE_BUTTONS } from '../constants';
import type { RangeId } from '../constants';

export function getVisibleRange(
  data: Array<{ time: string }>,
  rangeId: RangeId
): { from: string; to: string } | null {
  if (data.length === 0) return null;
  const first = data[0];
  const last = data[data.length - 1];
  const toStr = typeof last.time === 'string' ? last.time : String(last.time);
  const option = RANGE_BUTTONS.find((r) => r.id === rangeId);
  if (!option) return null;
  if (option.monthsBack === null) {
    const fromStr = typeof first.time === 'string' ? first.time.slice(0, 10) : String(first.time).slice(0, 10);
    return { from: fromStr, to: toStr };
  }
  const toDate = new Date(toStr);
  const fromDate = new Date(toDate);
  fromDate.setMonth(fromDate.getMonth() - option.monthsBack);
  const fromStr = fromDate.toISOString().slice(0, 10);
  return { from: fromStr, to: toStr };
}

export function timeToDateString(t: unknown): string {
  if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 10);
  if (typeof t === 'string') return t.slice(0, 10);
  const b = t as { year: number; month: number; day: number };
  return `${b.year}-${String(b.month).padStart(2, '0')}-${String(b.day).padStart(2, '0')}`;
}

export function visibleRangeToDateStrings(range: { from: unknown; to: unknown }): { from: string; to: string } {
  return { from: timeToDateString(range.from), to: timeToDateString(range.to) };
}

export function rangesMatch(
  a: { from: string; to: string },
  b: { from: string; to: string },
  toleranceDays = 1
): boolean {
  const toMs = (s: string) => new Date(s).getTime();
  return (
    Math.abs(toMs(a.from) - toMs(b.from)) <= toleranceDays * 86400000 &&
    Math.abs(toMs(a.to) - toMs(b.to)) <= toleranceDays * 86400000
  );
}

export function rangeToSeconds(range: { from: unknown; to: unknown }): { from: number; to: number } {
  const toSec = (t: unknown): number => {
    if (typeof t === 'number') return t;
    if (typeof t === 'string') return Math.floor(new Date(t).getTime() / 1000);
    const b = t as { year: number; month: number; day: number };
    return Math.floor(new Date(b.year, b.month - 1, b.day).getTime() / 1000);
  };
  return { from: toSec(range.from), to: toSec(range.to) };
}
