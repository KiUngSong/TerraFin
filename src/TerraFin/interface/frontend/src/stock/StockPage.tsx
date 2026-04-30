import React from 'react';
import DashboardHeader from '../dashboard/components/DashboardHeader';
import InsightCard from '../dashboard/components/InsightCard';
import DcfValuationPanel from '../dcf/DcfValuationPanel';
import DcfWorkbench from '../dcf/DcfWorkbench';
import ReverseDcfPanel from '../dcf/ReverseDcfPanel';
import ReverseDcfWorkbench from '../dcf/ReverseDcfWorkbench';
import { DcfValuationPayload, ReverseDcfPayload } from '../dcf/types';
import { useViewportTier } from '../shared/responsive';
import TickerSearchInput from '../shared/TickerSearchInput';
import { clearAgentViewContextSource, publishAgentViewContext } from '../agent/viewContext';
import StockHeader from './components/StockHeader';
import StockChart from './components/StockChart';
import CompanyProfile from './components/CompanyProfile';
import EarningsTable from './components/EarningsTable';
import FcfHistoryChart from './components/FcfHistoryChart';
import SecFilings from './components/SecFilings';
import { useCompanyInfo, useEarnings, useFcfHistory } from './useStockData';

const TICKER_GROUPS = [
  {
    label: 'Magnificent 7',
    tickers: [
      { symbol: 'AAPL', name: 'Apple' },
      { symbol: 'MSFT', name: 'Microsoft' },
      { symbol: 'GOOGL', name: 'Alphabet' },
      { symbol: 'AMZN', name: 'Amazon' },
      { symbol: 'NVDA', name: 'NVIDIA' },
      { symbol: 'META', name: 'Meta Platforms' },
      { symbol: 'TSLA', name: 'Tesla' },
    ],
  },
  {
    label: 'South Korea',
    tickers: [
      { symbol: '005930.KS', name: 'Samsung Electronics' },
      { symbol: '000660.KS', name: 'SK Hynix' },
      { symbol: '373220.KS', name: 'LG Energy Solution' },
      { symbol: '005380.KS', name: 'Hyundai Motor' },
      { symbol: '035420.KS', name: 'Naver' },
      { symbol: '035720.KS', name: 'Kakao' },
    ],
  },
  {
    label: 'Japan',
    tickers: [
      { symbol: '7203.T', name: 'Toyota' },
      { symbol: '6758.T', name: 'Sony' },
      { symbol: '6861.T', name: 'Keyence' },
      { symbol: '8306.T', name: 'MUFG' },
      { symbol: '9984.T', name: 'SoftBank Group' },
      { symbol: '6501.T', name: 'Hitachi' },
    ],
  },
  {
    label: 'Financials',
    tickers: [
      { symbol: 'JPM', name: 'JP Morgan' },
      { symbol: 'GS', name: 'Goldman Sachs' },
      { symbol: 'BRK-B', name: 'Berkshire Hathaway' },
      { symbol: 'V', name: 'Visa' },
      { symbol: 'MA', name: 'Mastercard' },
    ],
  },
  {
    label: 'Semiconductors',
    tickers: [
      { symbol: 'TSM', name: 'TSMC' },
      { symbol: 'AVGO', name: 'Broadcom' },
      { symbol: 'AMD', name: 'AMD' },
      { symbol: 'INTC', name: 'Intel' },
      { symbol: 'QCOM', name: 'Qualcomm' },
      { symbol: 'ASML', name: 'ASML' },
    ],
  },
];

function extractTicker(): string {
  const path = window.location.pathname;
  const match = path.match(/^\/stock\/(.+)/);
  return match ? decodeURIComponent(match[1]).toUpperCase() : '';
}

const StockPage: React.FC = () => {
  const ticker = extractTicker();
  const [searchValue, setSearchValue] = React.useState('');
  const [readyTicker, setReadyTicker] = React.useState<string | null>(null);
  const [isReverseDcfOpen, setIsReverseDcfOpen] = React.useState(false);
  const { isMobile, isTabletOrBelow } = useViewportTier();
  const [stockDcfState, setStockDcfState] = React.useState<{
    payload: DcfValuationPayload | null;
    loading: boolean;
    error: string | null;
    hasValuationState: boolean;
  }>({
    payload: null,
    loading: false,
    error: null,
    hasValuationState: false,
  });
  const [reverseDcfState, setReverseDcfState] = React.useState<{
    payload: ReverseDcfPayload | null;
    loading: boolean;
    error: string | null;
    hasValuationState: boolean;
  }>({
    payload: null,
    loading: false,
    error: null,
    hasValuationState: false,
  });
  const panelsEnabled = readyTicker === ticker;
  const handleChartReadyChange = React.useCallback(
    (ready: boolean) => setReadyTicker(ready ? ticker : null),
    [ticker]
  );
  const isNarrowLayout = isTabletOrBelow;
  const { data: companyInfo, loading: infoLoading, error: infoError } = useCompanyInfo(ticker);
  // ETFs and indices don't have FCF/DCF/earnings/SEC filings — only equities do.
  // Default to equity treatment until quoteType resolves so initial load isn't gated.
  const isEquity = !companyInfo?.quoteType || companyInfo.quoteType === 'EQUITY';
  const { data: earnings, loading: earningsLoading } = useEarnings(ticker);
  const { data: fcfHistory, loading: fcfHistoryLoading, error: fcfHistoryError } = useFcfHistory(ticker, 10);

  React.useEffect(() => {
    setIsReverseDcfOpen(false);
  }, [ticker]);

  // SEC filings section hides itself for non-US tickers (KOSPI, TSE, etc.)
  // where the ticker has no SEC CIK. Reset on ticker change so switching
  // from 005930.KS to AAPL re-shows the section.
  const [hideSecFilings, setHideSecFilings] = React.useState(false);
  React.useEffect(() => {
    setHideSecFilings(false);
  }, [ticker]);

  React.useEffect(() => {
    const route = window.location.pathname;
    if (!ticker) {
      void publishAgentViewContext({
        source: 'stock-page',
        scope: 'page',
        route,
        pageType: 'stock-search',
        title: 'Stock Analysis',
        summary: 'Viewing the stock search page in TerraFin.',
        metadata: { source: 'stock-page' },
      });
      return () => {
        void clearAgentViewContextSource('stock-page');
      };
    }
    const fcfCandidates = fcfHistory?.candidates ?? null;
    const fcfHistoryRowCount = fcfHistory?.history.length ?? 0;
    const ttmFcfPerShare = fcfHistory?.ttmFcfPerShare ?? null;
    const autoSelectedFcfSource = fcfHistory?.autoSelectedSource ?? null;
    void publishAgentViewContext({
      source: 'stock-page',
      scope: 'page',
      route,
      pageType: 'stock',
      title: `${ticker} Stock Analysis`,
      summary:
        `Viewing stock analysis for ${ticker}. ` +
        `FCF history: ${fcfHistoryRowCount} annual rows; ` +
        `TTM FCF/share: ${ttmFcfPerShare ?? 'n/a'}; ` +
        `Auto-selected DCF base: ${autoSelectedFcfSource ?? 'n/a'}.`,
      selection: {
        ticker,
        panelsEnabled,
        reverseDcfOpen: isReverseDcfOpen,
        fcfCandidates,
        autoSelectedFcfSource,
        ttmFcfPerShare,
      },
      entities: [
        {
          kind: 'ticker',
          id: ticker,
          label: companyInfo?.shortName || ticker,
          attributes: {
            exchange: companyInfo?.exchange || null,
            sector: companyInfo?.sector || null,
            industry: companyInfo?.industry || null,
            currentPrice: companyInfo?.currentPrice || null,
            changePercent: companyInfo?.changePercent || null,
          },
        },
      ],
      metadata: {
        source: 'stock-page',
        infoLoaded: !infoLoading,
        earningsLoaded: !earningsLoading,
        hasInfoError: Boolean(infoError),
        earningsCount: earnings.length,
        fcfHistoryLoaded: !fcfHistoryLoading,
        fcfHistoryError: fcfHistoryError ?? null,
      },
    });
    return () => {
      void clearAgentViewContextSource('stock-page');
    };
  }, [companyInfo, earnings.length, earningsLoading, fcfHistory, fcfHistoryError, fcfHistoryLoading, infoError, infoLoading, isReverseDcfOpen, panelsEnabled, ticker]);

  const handleSearchSubmit = (query: string) => {
    const trimmed = query.trim();
    if (!trimmed) return;
    fetch(`/resolve-ticker?q=${encodeURIComponent(trimmed)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d) => { window.location.href = d.path; })
      .catch(() => { window.location.href = `/stock/${trimmed.toUpperCase()}`; });
  };

  if (!ticker) {
    const [localTicker, setLocalTicker] = React.useState('');
    return (
      <div style={pageStyle}>
        <DashboardHeader searchValue={searchValue} onSearchChange={setSearchValue} onSearchSubmit={handleSearchSubmit} />
        <main
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            flex: 1,
            padding: isMobile ? '36px 12px 12px' : '48px 16px 16px',
          }}
        >
          <div style={{ textAlign: 'center', maxWidth: 520, marginBottom: 40 }}>
            <div style={{ fontSize: 28, fontWeight: 800, color: '#0f172a', marginBottom: 8 }}>Stock Analysis</div>
            <div style={{ fontSize: 14, color: '#64748b', marginBottom: 24 }}>
              Enter a ticker symbol to view company profile, price chart, earnings, and valuation context.
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const t = localTicker.trim().toUpperCase();
                if (t) window.location.href = `/stock/${t}`;
              }}
              style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}
            >
              <div style={{ width: 'min(100%, 320px)', maxWidth: 320, flex: '1 1 240px' }}>
                <TickerSearchInput
                  value={localTicker}
                  onChange={setLocalTicker}
                  onSelect={(hit) => { window.location.href = `/stock/${hit.symbol}`; }}
                  onSubmit={() => {
                    const t = localTicker.trim().toUpperCase();
                    if (t) window.location.href = `/stock/${t}`;
                  }}
                  placeholder="Search ticker or company"
                  ariaLabel="Search ticker or company"
                  inputStyle={{
                    width: '100%',
                    boxSizing: 'border-box',
                    height: 48,
                    border: '2px solid #cbd5e1',
                    borderRadius: 12,
                    padding: '0 16px',
                    fontSize: 16,
                    color: '#0f172a',
                    outline: 'none',
                  }}
                />
              </div>
              <button
                type="submit"
                style={{
                  height: 48,
                  padding: '0 24px',
                  borderRadius: 12,
                  border: 'none',
                  background: '#1d4ed8',
                  color: '#fff',
                  fontSize: 14,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Analyze
              </button>
            </form>
          </div>

          <div style={{ width: '100%', maxWidth: 800 }}>
            {TICKER_GROUPS.map((group) => (
              <div key={group.label} style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8 }}>
                  {group.label}
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {group.tickers.map((t) => (
                    <a
                      key={t.symbol}
                      href={`/stock/${t.symbol}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '8px 14px',
                        border: '1px solid #e2e8f0',
                        borderRadius: 10,
                        background: '#fff',
                        textDecoration: 'none',
                        cursor: 'pointer',
                        transition: 'border-color 0.15s',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.borderColor = '#93c5fd')}
                      onMouseLeave={(e) => (e.currentTarget.style.borderColor = '#e2e8f0')}
                    >
                      <span style={{ fontSize: 13, fontWeight: 700, color: '#1d4ed8' }}>{t.symbol}</span>
                      <span style={{ fontSize: 12, color: '#475569' }}>{t.name}</span>
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </main>
      </div>
    );
  }

  return (
    <div style={pageStyle}>
      <DashboardHeader
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        onSearchSubmit={handleSearchSubmit}
        placeholder={`Search ticker or company (currently viewing ${ticker})`}
      />

      <main style={mainStyle}>
        <section style={rowGridStyle(isNarrowLayout, 'minmax(0, 1.7fr) minmax(360px, 1fr)')}>
          <InsightCard
            title="Market Chart"
            subtitle={`${ticker} price history and technical overlays`}
            fillContent
            minHeight={560}
          >
              <StockChart ticker={ticker} onReadyChange={handleChartReadyChange} />
          </InsightCard>

          <InsightCard
            title="Overview & Valuation"
            subtitle="Company identity, price context, and core metrics"
            minHeight={isNarrowLayout ? 0 : 560}
          >
              {companyInfo ? (
                <div style={overviewPanelStyle}>
                  <StockHeader info={companyInfo} />
                  <div style={overviewDividerStyle} />
                  <CompanyProfile info={companyInfo} />
                </div>
              ) : infoLoading ? (
                <div style={{ fontSize: 13, color: '#475569' }}>Loading company profile...</div>
              ) : infoError ? (
                <div style={{ fontSize: 13, color: '#b91c1c' }}>Failed to load: {infoError}</div>
              ) : (
                <div style={{ fontSize: 13, color: '#475569' }}>Company profile unavailable.</div>
              )}
          </InsightCard>
        </section>

        {isEquity ? (
        <section style={{ ...rowGridStyle(isNarrowLayout, 'minmax(0, 1.2fr) minmax(0, 1fr)'), height: isNarrowLayout ? undefined : 280 }}>
          <InsightCard
            title="Earnings History"
            subtitle="Recent EPS estimates, actuals, and surprises"
            fillContent
            minHeight={240}
          >
            {earningsLoading ? (
              <div style={{ fontSize: 13, color: '#475569' }}>Loading earnings...</div>
            ) : (
              <EarningsTable earnings={earnings} />
            )}
          </InsightCard>

          <InsightCard
            title="FCF / Share History"
            subtitle={`Annual free cash flow per share for ${ticker}, with TTM.`}
            fillContent
            minHeight={240}
          >
            <FcfHistoryChart payload={fcfHistory} loading={fcfHistoryLoading} error={fcfHistoryError} />
          </InsightCard>
        </section>
        ) : null}

        {isEquity ? (
        <section style={rowGridStyle(isNarrowLayout, 'minmax(420px, 1.08fr) minmax(0, 1fr)')}>
          <InsightCard
            title="DCF Valuation"
            subtitle={`Model inputs for ${ticker}.`}
            fillContent
            minHeight={420}
            allowOverflow
          >
            <DcfWorkbench
              mode="stock"
              endpoint={`/stock/api/dcf?ticker=${encodeURIComponent(ticker)}`}
              betaEndpoint={`/stock/api/beta-estimate?ticker=${encodeURIComponent(ticker)}`}
              symbolLabel={ticker}
              showInlineResults={false}
              onValuationStateChange={setStockDcfState}
              defaultBaseGrowthPct={
                companyInfo?.trailingEps && companyInfo?.forwardEps && companyInfo.trailingEps > 0 && companyInfo.forwardEps > 0
                  ? ((companyInfo.forwardEps / companyInfo.trailingEps) - 1.0) * 100.0
                  : null
              }
              defaultBeta={companyInfo?.beta ?? null}
              fcfCandidates={fcfHistory?.candidates ?? null}
            />
          </InsightCard>

          <InsightCard
            title="DCF Valuation Result"
            subtitle={`Equity valuation range for ${ticker}.`}
            fillContent
            minHeight={420}
            allowOverflow
          >
            <DcfValuationPanel
              payload={stockDcfState.payload}
              loading={stockDcfState.loading}
              error={stockDcfState.error}
            />
          </InsightCard>
        </section>
        ) : null}

        {isEquity ? (
        <section style={reverseDcfToggleCardStyle}>
          <button
            type="button"
            aria-expanded={isReverseDcfOpen}
            onClick={() => setIsReverseDcfOpen((current) => !current)}
            style={reverseDcfToggleButtonStyle}
          >
            <div style={reverseDcfToggleTextBlockStyle}>
              <div style={reverseDcfEyebrowStyle}>Additional Feature</div>
              <div style={reverseDcfTitleRowStyle}>
                <h3 style={reverseDcfTitleStyle}>Reverse DCF</h3>
                <span style={reverseDcfStateBadgeStyle(isReverseDcfOpen)}>
                  {isReverseDcfOpen ? 'Expanded' : 'Collapsed'}
                </span>
              </div>
              <p style={reverseDcfSubtitleStyle}>
                Market-implied growth assumptions for {ticker}. Open this only when you want the extra valuation tool.
              </p>
            </div>
            <span style={reverseDcfToggleChipStyle(isReverseDcfOpen)}>{isReverseDcfOpen ? 'Hide' : 'Show'}</span>
          </button>
        </section>
        ) : null}

        {isEquity && isReverseDcfOpen ? (
          <section style={rowGridStyle(isNarrowLayout, 'minmax(420px, 1.08fr) minmax(0, 1fr)')}>
            <InsightCard
              title="Reverse DCF"
              subtitle={`Market-implied growth assumptions for ${ticker}.`}
              fillContent
              minHeight={420}
              allowOverflow
            >
              <ReverseDcfWorkbench
                endpoint={`/stock/api/reverse-dcf?ticker=${encodeURIComponent(ticker)}`}
                betaEndpoint={`/stock/api/beta-estimate?ticker=${encodeURIComponent(ticker)}`}
                symbolLabel={ticker}
                defaultCurrentPrice={companyInfo?.currentPrice ?? null}
                defaultBeta={companyInfo?.beta ?? null}
                onValuationStateChange={setReverseDcfState}
              />
            </InsightCard>

            <InsightCard
              title="Reverse DCF Result"
              subtitle="Growth rate required to justify the current market price."
              fillContent
              minHeight={420}
              allowOverflow
            >
              <ReverseDcfPanel
                payload={reverseDcfState.payload}
                loading={reverseDcfState.loading}
                error={reverseDcfState.error}
              />
            </InsightCard>
          </section>
        ) : null}

        {isEquity && !hideSecFilings ? (
          <section>
            <InsightCard
              title="SEC Filings"
              subtitle={`10-K / 10-Q filings for ${ticker}. Open a filing to browse section-by-section.`}
              fillContent
              allowOverflow
            >
              <SecFilings ticker={ticker} onUnavailable={() => setHideSecFilings(true)} />
            </InsightCard>
          </section>
        ) : null}
      </main>
    </div>
  );
};

const pageStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  width: '100%',
  height: '100%',
  overflowX: 'hidden',
  overflowY: 'auto',
  background: 'linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)',
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  color: '#0f172a',
};

const mainStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 16,
  width: '100%',
  maxWidth: 1480,
  margin: '0 auto',
  padding: 'var(--tf-page-padding)',
  boxSizing: 'border-box',
};

const overviewPanelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  minWidth: 0,
};

const overviewDividerStyle: React.CSSProperties = {
  width: '100%',
  height: 1,
  background: '#e2e8f0',
};

const reverseDcfToggleCardStyle: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: 14,
  border: '1px solid #e2e8f0',
  boxShadow: '0 8px 20px rgba(15, 23, 42, 0.04)',
  overflow: 'hidden',
};

const reverseDcfToggleButtonStyle: React.CSSProperties = {
  width: '100%',
  border: 'none',
  background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
  padding: 16,
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: 16,
  flexWrap: 'wrap',
  textAlign: 'left',
  cursor: 'pointer',
};

const reverseDcfToggleTextBlockStyle: React.CSSProperties = {
  display: 'grid',
  gap: 6,
  minWidth: 0,
};

const reverseDcfEyebrowStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#64748b',
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
};

const reverseDcfTitleRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  flexWrap: 'wrap',
};

const reverseDcfTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 15,
  fontWeight: 700,
  color: '#0f172a',
};

const reverseDcfStateBadgeStyle = (open: boolean): React.CSSProperties => ({
  borderRadius: 999,
  padding: '5px 9px',
  background: open ? '#dcfce7' : '#f1f5f9',
  color: open ? '#166534' : '#475569',
  fontSize: 11,
  fontWeight: 700,
});

const reverseDcfSubtitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: '#64748b',
  lineHeight: 1.5,
};

const reverseDcfToggleChipStyle = (open: boolean): React.CSSProperties => ({
  flexShrink: 0,
  minWidth: 72,
  height: 36,
  borderRadius: 999,
  border: `1px solid ${open ? '#86efac' : '#cbd5e1'}`,
  background: open ? '#ecfdf5' : '#ffffff',
  color: open ? '#166534' : '#334155',
  fontSize: 12,
  fontWeight: 800,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
});

function rowGridStyle(
  isNarrowLayout: boolean,
  desktopColumns: string,
  alignItems: React.CSSProperties['alignItems'] = 'stretch',
): React.CSSProperties {
  return {
    display: 'grid',
    gridTemplateColumns: isNarrowLayout ? '1fr' : desktopColumns,
    gap: 16,
    alignItems,
  };
}

export default StockPage;
