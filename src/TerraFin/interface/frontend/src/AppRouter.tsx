import React, { Suspense } from 'react';

const ChartPage = React.lazy(() => import('./chart/ChartPage'));
const DashboardPage = React.lazy(() => import('./dashboard/DashboardPage'));
const CalendarPage = React.lazy(() => import('./calendar/CalendarPage'));
const MarketInsightsPage = React.lazy(() => import('./marketInsights/MarketInsightsPage'));
const StockPage = React.lazy(() => import('./stock/StockPage'));
const WatchlistPage = React.lazy(() => import('./watchlist/WatchlistPage'));

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

  if (path === '/stock' || path.startsWith('/stock/')) {
    Page = StockPage;
  } else if (path.startsWith('/calendar')) {
    Page = CalendarPage;
  } else if (path.startsWith('/market-insights')) {
    Page = MarketInsightsPage;
  } else if (path.startsWith('/watchlist')) {
    Page = WatchlistPage;
  } else if (path.startsWith('/dashboard')) {
    Page = DashboardPage;
  }

  return (
    <Suspense fallback={<div style={ROUTER_FALLBACK_STYLE}>Loading TerraFin...</div>}>
      <Page />
    </Suspense>
  );
};

export default AppRouter;
