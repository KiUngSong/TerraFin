/**
 * Custom tooltip overlay for the chart crosshair.
 */
import { FONT_FAMILY } from '../constants';
import type { LinePoint } from '../types';

type SeriesRef = unknown;


function formatMagnitude(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return (value / 1_000_000_000).toFixed(2) + 'B';
  if (abs >= 1_000_000) return (value / 1_000_000).toFixed(2) + 'M';
  if (abs >= 1_000) return (value / 1_000).toFixed(2) + 'K';
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

interface TooltipContext {
  el: HTMLElement;
  seriesToId: Map<SeriesRef, string>;
  seriesToColor: Map<SeriesRef, string>;
  originalDataMap: Map<SeriesRef, LinePoint[]>;
}

export function createTooltip(ctx: TooltipContext): {
  element: HTMLDivElement;
  handler: (param: { point?: { x: number; y: number }; time?: unknown; seriesData: Map<unknown, unknown> }) => void;
} {
  const { el, seriesToId, seriesToColor, originalDataMap } = ctx;
  const margin = 12;

  const toolTip = document.createElement('div');
  toolTip.style.cssText = [
    'position: absolute',
    'display: none',
    'padding: 6px 10px',
    'font-size: var(--tf-fs-xs)',
    'font-family: ' + FONT_FAMILY,
    'background: var(--tf-bg-elevated)',
    'color: var(--tf-text)',
    'border: 1px solid var(--tf-border)',
    'border-radius: var(--tf-radius)',
    'pointer-events: none',
    'z-index: 1000',
    'white-space: nowrap',
  ].join('; ');
  el.appendChild(toolTip);

  const handler = (param: { point?: { x: number; y: number }; time?: unknown; seriesData: Map<unknown, unknown> }) => {
    if (
      param.point === undefined ||
      !param.time ||
      param.point.x < 0 ||
      param.point.y < 0 ||
      param.point.x > el.clientWidth ||
      param.point.y > el.clientHeight
    ) {
      toolTip.style.display = 'none';
      return;
    }

    const rows: Array<{ id: string; formatted: string; color: string }> = [];
    // Band series render as 3 cumulative area layers keyed `<base>::pos|neu|neg`.
    // The crosshair sees cumulative values; difference them back to real shares.
    const bands = new Map<string, Record<string, { v: number; color: string }>>();
    param.seriesData.forEach((data, series) => {
      const s = series as SeriesRef;
      const id = seriesToId.get(s);
      if (id == null) return;
      const d = data as { value?: number; close?: number };
      const value = d.value !== undefined ? d.value : d.close;
      if (value === undefined) return;
      const color = seriesToColor.get(s) ?? '#888';
      if (id.includes('::') && typeof value === 'number') {
        const [base, layer] = id.split('::');
        const entry = bands.get(base) ?? {};
        entry[layer] = { v: value, color };
        bands.set(base, entry);
        return;
      }
      // Auxiliary overlay series use ids prefixed with `__` (e.g. the volume
      // histogram). Show with a friendly label + magnitude suffix instead
      // of leaking the synthetic id as a symbol name.
      if (id.startsWith('__')) {
        if (id === '__volume_overlay__' && typeof value === 'number') {
          rows.push({ id: 'Volume', formatted: formatMagnitude(value), color });
        }
        return;
      }
      const isReturn = originalDataMap.has(s);
      const formatted =
        typeof value === 'number' && Number.isFinite(value)
          ? isReturn
            ? value.toFixed(2) + '%'
            : value.toLocaleString('en-US', { maximumFractionDigits: 4 })
          : String(value);
      rows.push({ id, formatted, color });
    });

    // Cumulative layers: pos = pos+neu+neg (1.0), neu = neu+neg, neg = neg.
    // Real share = this layer's cumulative minus the next-lower layer's.
    bands.forEach((layers, base) => {
      const { pos, neu, neg } = layers;
      if (!pos || !neu || !neg) return;
      const pct = (x: number) => (Math.max(0, x) * 100).toFixed(1) + '%';
      rows.push({ id: `${base} · pos`, formatted: pct(pos.v - neu.v), color: pos.color });
      rows.push({ id: `${base} · neu`, formatted: pct(neu.v - neg.v), color: neu.color });
      rows.push({ id: `${base} · neg`, formatted: pct(neg.v), color: neg.color });
    });

    if (rows.length === 0) {
      toolTip.style.display = 'none';
      return;
    }

    const timeStr = typeof param.time === 'string' ? param.time.slice(0, 10) : String(param.time).slice(0, 10);
    const swatchStyle =
      'display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px;vertical-align:middle';
    toolTip.innerHTML = `<div style="font-weight:600;margin-bottom:4px;color:var(--tf-text-strong)">${timeStr}</div>${rows
      .map(
        (r) =>
          `<div style="margin:3px 0;display:flex;align-items:center"><span style="${swatchStyle};background:${r.color}"></span><span>${r.id}: ${r.formatted}</span></div>`
      )
      .join('')}`;
    toolTip.style.display = 'block';

    const tw = 180;
    const th = toolTip.offsetHeight || 80;
    let left = param.point.x + margin;
    if (left + tw > el.clientWidth) left = param.point.x - margin - tw;
    let top = param.point.y + margin;
    if (top + th > el.clientHeight) top = param.point.y - margin - th;
    toolTip.style.left = Math.max(0, left) + 'px';
    toolTip.style.top = Math.max(0, top) + 'px';
  };

  return { element: toolTip, handler };
}
