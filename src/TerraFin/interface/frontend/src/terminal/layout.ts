import type { LayoutPreset } from '../terminal/store';

export type WidgetId =
  | 'ticker'
  | 'sector'
  | 'heatmap'
  | 'watchlist'
  | 'macro'
  | 'fear';

export type SourceCode = 'yf' | 'cnn' | 'sec' | 'cboe' | 'calc' | 'ai';

export interface PanelTab {
  id: WidgetId;
  label: string;
  source?: SourceCode;
  href?: string;
}

export interface PanelDef {
  number: number;
  area: string;
  tabs: PanelTab[];
}

export interface PresetDef {
  label: string;
  gridTemplate: { columns: string; rows: string; areas: string };
  panels: PanelDef[];
}

const TRADER: PresetDef = {
  label: 'Default',
  gridTemplate: {
    columns: '340px 1fr 360px',
    rows: '46px 1fr',
    areas: `
      "tape tape tape"
      "watch heat fng"
    `,
  },
  panels: [
    {
      number: 1,
      area: 'tape',
      tabs: [{ id: 'ticker', label: 'Tape', source: 'yf' }],
    },
    {
      number: 2,
      area: 'watch',
      tabs: [
        { id: 'watchlist', label: 'Watch', source: 'yf', href: '/watchlist' },
        { id: 'macro', label: 'Gauges', source: 'calc' },
      ],
    },
    {
      number: 3,
      area: 'heat',
      tabs: [
        { id: 'heatmap', label: 'Stocks', source: 'yf' },
        { id: 'sector', label: 'Sectors', source: 'yf' },
      ],
    },
    {
      number: 4,
      area: 'fng',
      tabs: [{ id: 'fear', label: 'Sentiment', source: 'cnn' }],
    },
  ],
};

// All preset slots map to the same single layout — kills the broken
// trader/macro/research switcher while preserving the store type.
export const LAYOUT_PRESETS: Record<LayoutPreset, PresetDef> = {
  trader: TRADER,
  macro: TRADER,
  research: TRADER,
};
