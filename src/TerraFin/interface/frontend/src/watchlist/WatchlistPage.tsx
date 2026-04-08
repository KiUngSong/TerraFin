import React, { useEffect, useMemo, useState } from 'react';
import DashboardHeader from '../dashboard/components/DashboardHeader';
import InsightCard from '../dashboard/components/InsightCard';
import { useWatchlist } from './useWatchlist';

const WatchlistPage: React.FC = () => {
  const [searchValue, setSearchValue] = useState('');
  const [watchlistInput, setWatchlistInput] = useState('');
  const [isNarrowLayout, setIsNarrowLayout] = useState(false);
  const { items, loading, busy, error, addSymbol, removeSymbol, backendConfigured } = useWatchlist();

  const subtitle = useMemo(() => {
    if (items.length === 0) {
      return 'Build a TerraFin watchlist and keep your core tickers in one place.';
    }
    if (items.length === 1) {
      return '1 saved ticker in your TerraFin watchlist.';
    }
    return `${items.length} saved tickers in your TerraFin watchlist.`;
  }, [items.length]);

  const handleAddWatchlistItem = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const symbol = watchlistInput.trim().toUpperCase();
    if (!symbol) {
      return;
    }

    try {
      await addSymbol(symbol);
      setWatchlistInput('');
    } catch {
      // Error state is handled inside the watchlist hook.
    }
  };

  const hasItems = items.length > 0;
  const managementEnabled = backendConfigured;

  useEffect(() => {
    const updateLayoutMode = () => setIsNarrowLayout(window.innerWidth < 1180);
    updateLayoutMode();
    window.addEventListener('resize', updateLayoutMode);
    return () => window.removeEventListener('resize', updateLayoutMode);
  }, []);

  return (
    <div style={pageStyle}>
      <DashboardHeader
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        sectionLabel="Watchlist"
        title="TerraFin"
        placeholder="Search ticker (AAPL, MSFT, TSLA)"
      />

      <main
        style={{
          display: 'grid',
          gap: 16,
          padding: 16,
          gridTemplateColumns: isNarrowLayout ? '1fr' : 'minmax(320px, 420px) minmax(0, 1fr)',
          alignItems: 'start',
        }}
      >
        <InsightCard title="Watchlist" subtitle={subtitle} minHeight={0}>
          <div style={{ display: 'grid', gap: 14 }}>
            {!managementEnabled ? (
              <div
                style={{
                  border: '1px solid #cbd5e1',
                  borderRadius: 14,
                  padding: 14,
                  background: '#fff7ed',
                  color: '#9a3412',
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Optional Local Backend
                </div>
                <div style={{ marginTop: 6, fontSize: 13, lineHeight: 1.6 }}>
                  Connect MongoDB with <code>TERRAFIN_MONGODB_URI</code> or <code>MONGODB_URI</code> to manage a
                  writable local watchlist. Until then, TerraFin shows a sample watchlist in read-only mode.
                </div>
              </div>
            ) : null}
            <form
              onSubmit={handleAddWatchlistItem}
              style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) auto',
                gap: 10,
                alignItems: 'center',
              }}
            >
              <input
                value={watchlistInput}
                onChange={(event) => setWatchlistInput(event.target.value)}
                placeholder="Add ticker, e.g. META"
                aria-label="Add ticker to watchlist"
                style={inputStyle}
                disabled={!managementEnabled || busy}
              />
              <button type="submit" disabled={!managementEnabled || busy} style={primaryButtonStyle(!managementEnabled || busy)}>
                {busy ? 'Saving...' : 'Add to Watchlist'}
              </button>
            </form>

            <div style={{ fontSize: 12, color: '#64748b' }}>
              {managementEnabled
                ? 'Watchlist changes are saved to your configured MongoDB document.'
                : 'Configure MongoDB to enable local watchlist management.'}
            </div>

            {error ? <div style={{ fontSize: 12, color: '#b91c1c' }}>{error}</div> : null}
          </div>
        </InsightCard>

        <InsightCard
          title="Saved Tickers"
          subtitle="Review your saved tickers, jump to stock pages, and remove symbols you no longer track."
          minHeight={0}
        >
          <div style={{ display: 'grid', gap: 10 }}>
            {loading ? <div style={{ fontSize: 13, color: '#475569' }}>Loading watchlist...</div> : null}
            {!loading && !hasItems ? (
              <div style={{ fontSize: 13, color: '#64748b' }}>
                No watchlist items saved yet. Add a ticker above to start your list.
              </div>
            ) : null}
            {!loading &&
              items.map((item) => (
                <div key={item.symbol} style={watchlistRowStyle}>
                  <div>
                    <a href={`/stock/${item.symbol}`} style={symbolLinkStyle}>
                      {item.symbol}
                    </a>
                    <div style={{ marginTop: 2, fontSize: 12, color: '#64748b' }}>{item.name}</div>
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
                  <button
                    type="button"
                    onClick={() => {
                      void removeSymbol(item.symbol);
                    }}
                    disabled={!managementEnabled || busy}
                    style={secondaryButtonStyle(!managementEnabled || busy)}
                  >
                    Remove
                  </button>
                </div>
              ))}
          </div>
        </InsightCard>
      </main>
    </div>
  );
};

const pageStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  width: '100%',
  height: '100%',
  overflow: 'auto',
  background: 'linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)',
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  color: '#0f172a',
};

const inputStyle: React.CSSProperties = {
  border: '1px solid #cbd5e1',
  borderRadius: 12,
  padding: '11px 14px',
  fontSize: 14,
  color: '#0f172a',
  background: '#ffffff',
};

const watchlistRowStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1fr) auto auto',
  alignItems: 'center',
  gap: 12,
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: '10px 12px',
  background: '#f8fafc',
};

const symbolLinkStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 700,
  color: '#1d4ed8',
  textDecoration: 'none',
};

const primaryButtonStyle = (disabled: boolean): React.CSSProperties => ({
  border: 'none',
  borderRadius: 12,
  padding: '11px 14px',
  fontSize: 12,
  fontWeight: 700,
  color: '#ffffff',
  background: disabled ? '#94a3b8' : '#0f172a',
  cursor: disabled ? 'not-allowed' : 'pointer',
});

const secondaryButtonStyle = (disabled: boolean): React.CSSProperties => ({
  border: '1px solid #cbd5e1',
  borderRadius: 999,
  padding: '5px 10px',
  fontSize: 11,
  fontWeight: 700,
  color: '#475569',
  background: '#ffffff',
  cursor: disabled ? 'not-allowed' : 'pointer',
});

export default WatchlistPage;
