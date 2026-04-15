import React, { Suspense, useEffect } from 'react';
import { publishAgentViewContext } from './agent/viewContext';

const ChartPage = React.lazy(() => import('./chart/ChartPage'));
const DashboardPage = React.lazy(() => import('./dashboard/DashboardPage'));
const CalendarPage = React.lazy(() => import('./calendar/CalendarPage'));
const MarketInsightsPage = React.lazy(() => import('./marketInsights/MarketInsightsPage'));
const StockPage = React.lazy(() => import('./stock/StockPage'));
const WatchlistPage = React.lazy(() => import('./watchlist/WatchlistPage'));
const GlobalAgentWidget = React.lazy(() => import('./agent/GlobalAgentWidget'));

const ROUTER_FALLBACK_STYLE: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: '100%',
  height: '100%',
  background: 'linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%)',
  color: '#475569',
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  fontSize: 14,
};

const AppRouter: React.FC = () => {
  const path = window.location.pathname;
  let Page = ChartPage;
  let pageType = 'chart';

  if (path === '/stock' || path.startsWith('/stock/')) {
    Page = StockPage;
    pageType = path === '/stock' ? 'stock-search' : 'stock';
  } else if (path.startsWith('/calendar')) {
    Page = CalendarPage;
    pageType = 'calendar';
  } else if (path.startsWith('/market-insights')) {
    Page = MarketInsightsPage;
    pageType = 'market-insights';
  } else if (path.startsWith('/watchlist')) {
    Page = WatchlistPage;
    pageType = 'watchlist';
  } else if (path.startsWith('/dashboard')) {
    Page = DashboardPage;
    pageType = 'dashboard';
  }

  useEffect(() => {
    void publishAgentViewContext({
      source: 'app-router',
      scope: 'page',
      route: path,
      pageType,
      title: `TerraFin · ${pageType}`,
      summary: `Viewing the ${pageType} page in TerraFin.`,
      metadata: { source: 'app-router' },
    });
  }, [pageType, path]);

  return (
    <Suspense fallback={<div style={ROUTER_FALLBACK_STYLE}>Loading TerraFin...</div>}>
      <>
        <Page />
        <GlobalAgentWidget />
      </>
    </Suspense>
  );
};

export default AppRouter;
