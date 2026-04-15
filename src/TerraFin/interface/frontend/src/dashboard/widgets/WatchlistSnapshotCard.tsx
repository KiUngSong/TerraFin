import React from 'react';
import InsightCard from '../components/InsightCard';
import { useWatchlist } from '../../watchlist/useWatchlist';

const WatchlistSnapshotCard: React.FC = () => {
  const { items, loading, error } = useWatchlist();
  const preview = items.slice(0, 4);
  const hiddenCount = Math.max(items.length - preview.length, 0);

  return (
    <InsightCard
      title="Watchlist Snapshot"
      subtitle="Your personal TerraFin watchlist, managed on the dedicated watchlist page."
    >
      <div className="tf-dashboard-watchlist">
        <div className="tf-dashboard-watchlist__summary">
          <div className="tf-dashboard-status">
            {items.length === 1 ? '1 ticker saved' : `${items.length} tickers saved`}
          </div>
          <a href="/watchlist" className="tf-dashboard-card-link">
            Manage Watchlist
          </a>
        </div>

        {error ? <div className="tf-dashboard-status tf-dashboard-status--error">{error}</div> : null}
        {loading ? <div className="tf-dashboard-status">Loading watchlist...</div> : null}

        {preview.length > 0 ? (
          <div className="tf-dashboard-watchlist__list">
            {preview.map((item) => {
              const isNegative = item.move.startsWith('-');
              return (
                <div key={item.symbol} className="tf-dashboard-watchlist__item">
                  <div className="tf-dashboard-watchlist__copy">
                    <a href={`/stock/${item.symbol}`} className="tf-dashboard-watchlist__symbol">
                      {item.symbol}
                    </a>
                    <div className="tf-dashboard-watchlist__name">{item.name}</div>
                  </div>
                  <div
                    className={`tf-dashboard-watchlist__move ${
                      isNegative
                        ? 'tf-dashboard-watchlist__move--negative'
                        : 'tf-dashboard-watchlist__move--positive'
                    }`}
                  >
                    {item.move}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}

        {hiddenCount > 0 ? (
          <div className="tf-dashboard-status">
            +{hiddenCount} more ticker{hiddenCount === 1 ? '' : 's'} on your watchlist.
          </div>
        ) : null}

        {!loading && items.length === 0 ? (
          <div className="tf-dashboard-status">No watchlist items saved yet.</div>
        ) : null}
      </div>
    </InsightCard>
  );
};

export default WatchlistSnapshotCard;
