import React, { useMemo, useState } from 'react';
import DashboardHeader from './components/DashboardHeader';
import DashboardLayout, { DashboardWidgetPlacement } from './components/DashboardLayout';
import InsightCard from './components/InsightCard';
import FearGreedGauge from './widgets/FearGreedGauge';
import LiveTickerTape from './widgets/LiveTickerTape';
import MarketBreadthCard from './widgets/MarketBreadthCard';
import StockHeatmap from './widgets/StockHeatmap';
import TrailingForwardPeCard from './widgets/TrailingForwardPeCard';
import UpcomingCatalysts from './widgets/UpcomingCatalysts';
import WatchlistSnapshotCard from './widgets/WatchlistSnapshotCard';

const DashboardPage: React.FC = () => {
  const [searchValue, setSearchValue] = useState('');

  const headline = 'Market dashboard overview';

  const widgets = useMemo<DashboardWidgetPlacement[]>(
    () => [
      {
        id: 'ticker',
        slot: 'hero',
        order: 1,
        mobileOrder: 1,
        minHeight: 96,
        element: (
          <InsightCard
            title="Live Market Tape"
            subtitle="Streaming major U.S. market benchmarks via TradingView."
            minHeight={96}
          >
            <LiveTickerTape />
          </InsightCard>
        ),
      },
      {
        id: 'heatmap',
        slot: 'primary',
        order: 1,
        mobileOrder: 2,
        minHeight: 0,
        element: (
          <InsightCard title="S&P 500 Sector Heatmap" subtitle={headline} minHeight={0}>
            <StockHeatmap height={500} />
          </InsightCard>
        ),
      },
      {
        id: 'calendar',
        slot: 'primary',
        order: 2,
        mobileOrder: 5,
        minHeight: 0,
        element: (
          <InsightCard title="Event Calendar" subtitle="Upcoming earnings and key market events." minHeight={0}>
            <UpcomingCatalysts />
          </InsightCard>
        ),
      },
      {
        id: 'fear',
        slot: 'rail',
        order: 1,
        mobileOrder: 3,
        minHeight: 0,
        element: (
          <InsightCard
            title="Fear & Greed Index"
            subtitle="CNN market sentiment gauge (0-100)."
            minHeight={0}
            href="/market-insights?ticker=Fear%20%26%20Greed"
          >
            <FearGreedGauge />
          </InsightCard>
        ),
      },
      {
        id: 'watchlist',
        slot: 'rail',
        order: 2,
        mobileOrder: 4,
        element: <WatchlistSnapshotCard />,
      },
      {
        id: 'breadth',
        slot: 'rail',
        order: 3,
        mobileOrder: 6,
        minHeight: 0,
        element: <MarketBreadthCard />,
      },
      {
        id: 'pe',
        slot: 'rail',
        order: 4,
        mobileOrder: 7,
        minHeight: 0,
        element: <TrailingForwardPeCard />,
      },
    ],
    [headline]
  );

  return (
    <div className="tf-dashboard-page">
      <DashboardHeader searchValue={searchValue} onSearchChange={setSearchValue} />

      <main className="tf-dashboard-main">
        <DashboardLayout widgets={widgets} />
      </main>
    </div>
  );
};

export default DashboardPage;
