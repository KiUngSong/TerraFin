/**
 * Custom tooltip overlay for the chart crosshair.
 */
import { FONT_FAMILY } from '../constants';
import type { LinePoint } from '../types';

type SeriesRef = unknown;

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
    'font-size: 12px',
    'font-family: ' + FONT_FAMILY,
    'background: white',
    'color: #333',
    'border: 1px solid #e0e0e0',
    'border-radius: 4px',
    'box-shadow: 0 1px 4px rgba(0,0,0,0.1)',
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
    param.seriesData.forEach((data, series) => {
      const s = series as SeriesRef;
      const id = seriesToId.get(s);
      if (id == null) return;
      const d = data as { value?: number; close?: number };
      const value = d.value !== undefined ? d.value : d.close;
      if (value !== undefined) {
        const isReturn = originalDataMap.has(s);
        const formatted =
          typeof value === 'number' && Number.isFinite(value)
            ? isReturn
              ? value.toFixed(2) + '%'
              : value.toLocaleString(undefined, { maximumFractionDigits: 4 })
            : String(value);
        const color = seriesToColor.get(s) ?? '#888';
        rows.push({ id, formatted, color });
      }
    });

    if (rows.length === 0) {
      toolTip.style.display = 'none';
      return;
    }

    const timeStr = typeof param.time === 'string' ? param.time.slice(0, 10) : String(param.time).slice(0, 10);
    const swatchStyle =
      'display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px;vertical-align:middle';
    toolTip.innerHTML = `<div style="font-weight:600;margin-bottom:4px;color:#111">${timeStr}</div>${rows
      .map(
        (r) =>
          `<div style="margin:3px 0;display:flex;align-items:center"><span style="${swatchStyle};background:${r.color}"></span><span>${r.id}: ${r.formatted}</span></div>`
      )
      .join('')}`;
    toolTip.style.display = 'block';

    const tw = 180;
    const th = 80;
    let left = param.point.x + margin;
    if (left + tw > el.clientWidth) left = param.point.x - margin - tw;
    let top = param.point.y + margin;
    if (top + th > el.clientHeight) top = param.point.y - margin - th;
    toolTip.style.left = Math.max(0, left) + 'px';
    toolTip.style.top = Math.max(0, top) + 'px';
  };

  return { element: toolTip, handler };
}
