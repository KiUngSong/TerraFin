import React, { useEffect, useMemo } from 'react';
import TerminalWorkspace from './components/TerminalWorkspace';
import LiveTickerTape from './widgets/LiveTickerTape';
import MacroStack from './widgets/MacroStack';
import SectorGrid, { prefetchSectors } from './widgets/SectorGrid';
import StockHeatmap from './widgets/StockHeatmap';
import SentimentCalendarStack from './widgets/SentimentCalendarStack';
import WatchlistSnapshotCard from './widgets/WatchlistSnapshotCard';
import { LAYOUT_PRESETS, WidgetId } from './layout';
import { useTerminalStore } from '../terminal/store';

// Widgets render bare — the PanelFrame already provides title/source chrome.
// Wrapping in TerminalPane added a second hidden header layer (DA audit).
const WIDGET_CATALOG: Record<WidgetId, React.ReactNode> = {
  ticker: <LiveTickerTape />,
  sector: <SectorGrid />,
  heatmap: <StockHeatmap height={500} />,
  fear: <SentimentCalendarStack />,
  watchlist: <WatchlistSnapshotCard />,
  macro: <MacroStack />,
};

const DashboardPage: React.FC = () => {
  // Warm the Sectors fetch on dashboard mount so the tab opens instantly.
  useEffect(() => {
    prefetchSectors().catch(() => {});
  }, []);
  const layoutPreset = useTerminalStore((s) => s.layoutPreset);
  const preset = useMemo(
    () => LAYOUT_PRESETS[layoutPreset] ?? LAYOUT_PRESETS.trader,
    [layoutPreset],
  );

  return (
    <div className="tf-terminal-shell">
      <main className="tf-terminal-shell__workspace">
        <TerminalWorkspace preset={preset} catalog={WIDGET_CATALOG} />
      </main>
    </div>
  );
};

export default DashboardPage;
