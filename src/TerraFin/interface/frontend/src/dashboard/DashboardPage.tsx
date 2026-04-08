import React, { useEffect, useMemo, useState } from 'react';
import DashboardHeader from './components/DashboardHeader';
import InsightCard from './components/InsightCard';
import FearGreedGauge from './widgets/FearGreedGauge';
import LiveTickerTape from './widgets/LiveTickerTape';
import StockHeatmap from './widgets/StockHeatmap';
import UpcomingCatalysts from './widgets/UpcomingCatalysts';
import { useWatchlist } from '../watchlist/useWatchlist';

interface BreadthMetric {
  label: string;
  value: string;
  tone: string;
}

interface TrailingForwardPeHistoryPoint {
  date: string;
  value: number;
}

interface TrailingForwardPeSpreadPayload {
  date: string;
  description: string;
  latestValue?: number | null;
  usableCount?: number | null;
  requestedCount?: number | null;
  history: TrailingForwardPeHistoryPoint[];
}

const Sparkline: React.FC<{ points: TrailingForwardPeHistoryPoint[] }> = ({ points }) => {
  if (points.length === 0) {
    return <div style={{ fontSize: 12, color: '#64748b' }}>No spread history available yet.</div>;
  }

  const values = points.map((point) => point.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const width = 280;
  const height = 88;
  const span = maxValue - minValue || 1;
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((point.value - minValue) / span) * (height - 8) - 4;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label="Trailing-forward P/E spread history"
    >
      <path d={path} fill="none" stroke="#2563eb" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

const DashboardPage: React.FC = () => {
  const [searchValue, setSearchValue] = useState('');
  const [breadthMetrics, setBreadthMetrics] = useState<BreadthMetric[]>([]);
  const [trailingForwardPe, setTrailingForwardPe] = useState<TrailingForwardPeSpreadPayload | null>(null);
  const { items: watchlistItems, loading: watchlistLoading, error: watchlistError } = useWatchlist();

  useEffect(() => {
    fetch('/dashboard/api/market-breadth')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: { metrics?: BreadthMetric[] }) => setBreadthMetrics(payload.metrics || []))
      .catch(() => setBreadthMetrics([]));

    fetch('/dashboard/api/trailing-forward-pe-spread')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: TrailingForwardPeSpreadPayload) => setTrailingForwardPe(payload))
      .catch(() => setTrailingForwardPe(null));
  }, []);

  const headline = useMemo(() => {
    if (searchValue.trim().length === 0) return 'Market dashboard overview';
    return `Tracking: ${searchValue.trim().toUpperCase()}`;
  }, [searchValue]);
  const watchlistPreview = watchlistItems.slice(0, 4);
  const hiddenWatchlistCount = Math.max(watchlistItems.length - watchlistPreview.length, 0);

  return (
    <div className="tf-dashboard-page">
      <DashboardHeader searchValue={searchValue} onSearchChange={setSearchValue} />

      <main className="tf-dashboard-main">
        <div className="tf-dashboard-grid">
          <div className="tf-dashboard-card tf-dashboard-card--ticker">
            <InsightCard
              title="Live Market Tape"
              subtitle="Streaming major U.S. market benchmarks via TradingView."
              minHeight={96}
            >
              <LiveTickerTape />
            </InsightCard>
          </div>

          <div className="tf-dashboard-card tf-dashboard-card--heatmap">
            <InsightCard title="S&P 500 Sector Heatmap" subtitle={headline} minHeight={0}>
              <StockHeatmap height={500} />
            </InsightCard>
          </div>

          <div className="tf-dashboard-card tf-dashboard-card--calendar">
            <InsightCard title="Event Calendar" subtitle="Upcoming earnings and key market events." minHeight={0}>
              <UpcomingCatalysts />
            </InsightCard>
          </div>

          <div className="tf-dashboard-card tf-dashboard-card--fear">
            <InsightCard
              title="Fear & Greed Index"
              subtitle="CNN market sentiment gauge (0-100)."
              minHeight={0}
              href="/market-insights?ticker=Fear%20%26%20Greed"
            >
              <FearGreedGauge />
            </InsightCard>
          </div>

          <div className="tf-dashboard-card tf-dashboard-card--watchlist">
            <InsightCard
              title="Watchlist Snapshot"
              subtitle="Your personal TerraFin watchlist, managed on the dedicated watchlist page."
            >
              <div style={{ display: 'grid', gap: 10 }}>
                <div className="tf-dashboard-watchlist-summary">
                  <div style={{ fontSize: 12, color: '#64748b' }}>
                    {watchlistItems.length === 1 ? '1 ticker saved' : `${watchlistItems.length} tickers saved`}
                  </div>
                  <a
                    href="/watchlist"
                    className="tf-dashboard-watchlist-link"
                    style={{
                      textDecoration: 'none',
                      border: '1px solid #cbd5e1',
                      borderRadius: 999,
                      padding: '6px 11px',
                      fontSize: 11,
                      fontWeight: 700,
                      color: '#0f172a',
                      background: '#ffffff',
                    }}
                  >
                    Manage Watchlist
                  </a>
                </div>
                {watchlistError ? (
                  <div style={{ fontSize: 12, color: '#b91c1c' }}>{watchlistError}</div>
                ) : null}
                {watchlistLoading ? (
                  <div style={{ fontSize: 12, color: '#64748b' }}>Loading watchlist...</div>
                ) : null}
                {watchlistPreview.map((item) => (
                  <div
                    key={item.symbol}
                    className="tf-dashboard-watchlist-item"
                    style={{
                      border: '1px solid #e2e8f0',
                      borderRadius: 10,
                      gap: 10,
                      padding: '8px 10px',
                      background: '#f8fafc',
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <a
                        href={`/stock/${item.symbol}`}
                        style={{ fontSize: 13, fontWeight: 700, color: '#1d4ed8', textDecoration: 'none' }}
                      >
                        {item.symbol}
                      </a>
                      <div style={{ fontSize: 12, color: '#64748b' }}>{item.name}</div>
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        fontWeight: 700,
                        color: item.move.startsWith('-') ? '#b91c1c' : '#047857',
                      }}
                    >
                      {item.move}
                    </div>
                  </div>
                ))}
                {hiddenWatchlistCount > 0 ? (
                  <div style={{ fontSize: 12, color: '#64748b' }}>
                    +{hiddenWatchlistCount} more ticker{hiddenWatchlistCount === 1 ? '' : 's'} on your watchlist.
                  </div>
                ) : null}
                {!watchlistLoading && watchlistItems.length === 0 ? (
                  <div style={{ fontSize: 12, color: '#64748b' }}>No watchlist items saved yet.</div>
                ) : null}
              </div>
            </InsightCard>
          </div>

          <div className="tf-dashboard-card tf-dashboard-card--breadth">
            <InsightCard
              title="Market Breadth"
              subtitle="Daily S&P 500 breadth from advancers and decliners."
              minHeight={0}
              href="/market-insights?ticker=Net%20Breadth"
            >
              <div className="tf-dashboard-breadth-grid">
                {breadthMetrics.map((item) => (
                  <div
                    key={item.label}
                    style={{
                      border: '1px solid #e2e8f0',
                      borderRadius: 10,
                      padding: 10,
                      background: '#ffffff',
                    }}
                  >
                    <div style={{ fontSize: 11, color: '#64748b' }}>{item.label}</div>
                    <div style={{ marginTop: 4, fontSize: 18, fontWeight: 700, color: item.tone }}>{item.value}</div>
                  </div>
                ))}
                {breadthMetrics.length === 0 ? (
                  <div className="tf-dashboard-empty-span" style={{ fontSize: 12, color: '#64748b' }}>
                    No market breadth data available right now.
                  </div>
                ) : null}
              </div>
            </InsightCard>
          </div>

          <div className="tf-dashboard-card tf-dashboard-card--pe">
            <InsightCard
              title="Trailing-Forward P/E Spread"
              subtitle={
                trailingForwardPe?.description ||
                'Trailing P/E minus forward P/E, used as a rough proxy for how much future earnings expectations diverge from trailing earnings.'
              }
              minHeight={0}
              href="/market-insights?ticker=Trailing-Forward%20P%2FE%20Spread"
            >
              <div style={{ display: 'grid', gap: 10 }}>
                <div className="tf-dashboard-pe-header">
                  <div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Latest spread</div>
                    <div style={{ marginTop: 4, fontSize: 22, fontWeight: 700, color: '#0f172a' }}>
                      {typeof trailingForwardPe?.latestValue === 'number'
                        ? trailingForwardPe.latestValue.toFixed(2)
                        : '--'}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', fontSize: 11, color: '#64748b' }}>
                    <div>{trailingForwardPe?.date || ''}</div>
                    <div>
                      Coverage {trailingForwardPe?.usableCount ?? '--'}/{trailingForwardPe?.requestedCount ?? '--'}
                    </div>
                  </div>
                </div>
                <div
                  style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: 10,
                    background: '#ffffff',
                    padding: '8px 10px',
                  }}
                >
                  <Sparkline points={trailingForwardPe?.history || []} />
                </div>
              </div>
            </InsightCard>
          </div>
        </div>
      </main>
    </div>
  );
};

export default DashboardPage;
