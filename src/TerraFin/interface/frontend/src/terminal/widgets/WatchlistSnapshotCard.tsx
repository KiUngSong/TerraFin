import React from 'react';
import SignedDelta from '../../shared/SignedDelta';
import { useWatchlist } from '../../watchlist/useWatchlist';
import { useTerminalStore } from '../../terminal/store';

function parseMovePct(move: string): number {
  const cleaned = move.replace(/[%+\s]/g, '').replace('−', '-');
  const v = parseFloat(cleaned);
  return Number.isFinite(v) ? v / 100 : 0;
}

function displaySymbol(symbol: string): string {
  // `005930.KS` → `5930.KS`; `000660.KS` → `660.KS`. Leave US tickers untouched.
  const m = symbol.match(/^0*(\d+)(\.\w+)$/);
  return m ? `${m[1]}${m[2]}` : symbol;
}

const WatchlistSnapshotCard: React.FC = () => {
  const { items, loading, error } = useWatchlist();
  const setActiveTicker = useTerminalStore((s) => s.setActiveTicker);
  const prevLastRef = React.useRef<Map<string, number>>(new Map());

  return (
    <div className="tf-table tf-table--watch">
      <div className="tf-table__head">
        <span className="tf-table__col tf-table__col--sym">Sym</span>
        <span className="tf-table__col tf-table__col--name">Name</span>
        <span className="tf-table__col tf-table__col--num">Last</span>
        <span className="tf-table__col tf-table__col--num">Chg %</span>
      </div>
      <div className="tf-table__body">
        {error ? <div className="tf-table__status tf-table__status--err">{error}</div> : null}
        {loading ? <div className="tf-table__status">loading…</div> : null}
        {!loading && items.length === 0 ? (
          <div className="tf-table__status">empty · add tickers in Watchlist</div>
        ) : null}
        <a href="/watchlist" className="tf-table__row tf-table__cta" title="Open full watchlist">
          <span className="tf-table__col tf-table__col--sym">→</span>
          <span className="tf-table__col tf-table__col--name">Open Watchlist</span>
          <span className="tf-table__col tf-table__col--num"></span>
          <span className="tf-table__col tf-table__col--num"></span>
        </a>
        {items.map((item) => {
          const pct = parseMovePct(item.move);
          const isKr = /\.(KS|KQ)$/i.test(item.symbol);
          const last = typeof item.last === 'number'
            ? isKr
              ? `₩${item.last.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
              : item.last.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
            : '—';
          const mag = Math.min(Math.abs(pct) / 0.05, 1);
          const magStyle = {
            '--tf-mag': mag,
            '--tf-mag-c': pct >= 0 ? 'var(--tf-up)' : 'var(--tf-down)',
          } as React.CSSProperties;
          return (
            <a
              key={item.symbol}
              href={`/stock/${item.symbol}`}
              className="tf-table__row"
              onClick={() => setActiveTicker(item.symbol)}
            >
              <span className="tf-table__col tf-table__col--sym" title={item.symbol}>{displaySymbol(item.symbol)}</span>
              <span className="tf-table__col tf-table__col--name" title={item.name}>{item.name}</span>
              <span className="tf-table__col tf-table__col--num">{last}</span>
              <span className="tf-table__col tf-table__col--num tf-table__col--mag" style={magStyle}>
                <SignedDelta value={pct} />
              </span>
            </a>
          );
        })}
      </div>
    </div>
  );
};

export default WatchlistSnapshotCard;
