import React, { Suspense, useEffect } from 'react';
import { publishAgentViewContext } from './agent/viewContext';
import { useTerminalStore } from './terminal/store';
// Eager (not lazy): the nav chrome must paint immediately, before the lazy page
// chunk resolves. Previously each page imported + rendered its own FunctionBar.
import FunctionBar from './terminal/FunctionBar';

const ChartPage = React.lazy(() => import('./chart/ChartPage'));
const DashboardPage = React.lazy(() => import('./terminal/DashboardPage'));
const CalendarPage = React.lazy(() => import('./calendar/CalendarPage'));
const MarketInsightsPage = React.lazy(() => import('./marketInsights/MarketInsightsPage'));
const StockPage = React.lazy(() => import('./stock/StockPage'));
const WatchlistPage = React.lazy(() => import('./watchlist/WatchlistPage'));
const GlobalAgentWidget = React.lazy(() => import('./agent/GlobalAgentWidget'));
const StatusBar = React.lazy(() => import('./terminal/StatusBar'));

const ROUTER_FALLBACK_STYLE: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: '100%',
  height: '100%',
  background: 'var(--tf-bg)',
  color: 'var(--tf-muted)',
  fontFamily: 'var(--tf-mono)',
  fontSize: 'var(--tf-fs-base)',
};

const AppRouter: React.FC = () => {
  const theme = useTerminalStore((s) => s.theme);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);
  const path = window.location.pathname;
  let Page = DashboardPage;
  let pageType = 'terminal';

  if (path === '/' || path === '') {
    Page = DashboardPage;
    pageType = 'terminal';
  } else if (path === '/chart' || path.startsWith('/chart/')) {
    Page = ChartPage;
    pageType = 'chart';
  } else if (path === '/stock' || path.startsWith('/stock/')) {
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
  } else if (path.startsWith('/terminal')) {
    Page = DashboardPage;
    pageType = 'terminal';
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
    <div className={`tf-app tf-app--${pageType}`}>
      {pageType !== 'chart' && <FunctionBar />}
      <div className="tf-app__main">
        <Suspense fallback={<div style={ROUTER_FALLBACK_STYLE}>Loading TerraFin...</div>}>
          <Page />
        </Suspense>
      </div>
      <Suspense fallback={null}>
        <GlobalAgentWidget />
        <StatusBar />
      </Suspense>
    </div>
  );
};

export default AppRouter;
