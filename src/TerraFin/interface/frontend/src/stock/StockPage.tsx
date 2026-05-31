import React from 'react';
import InsightCard from '../terminal/components/InsightCard';
import DcfValuationPanel from '../dcf/DcfValuationPanel';
import DcfWorkbench from '../dcf/DcfWorkbench';
import ReverseDcfPanel from '../dcf/ReverseDcfPanel';
import ReverseDcfWorkbench from '../dcf/ReverseDcfWorkbench';
import { DcfValuationPayload, ReverseDcfPayload } from '../dcf/types';
import { useViewportTier } from '../shared/responsive';
import TickerSearchInput from '../shared/TickerSearchInput';
import { resolveAndGo } from '../shared/resolveTicker';
import { clearAgentViewContextSource, publishAgentViewContext } from '../agent/viewContext';
import StockHeader from './components/StockHeader';
import StockChart from './components/StockChart';
import CompanyProfile from './components/CompanyProfile';
import EarningsTable from './components/EarningsTable';
import FcfHistoryChart from './components/FcfHistoryChart';
import GexPanel from './components/GexPanel';
// IncomeSankeyCard pulls in ~150KB gzipped of @nivo/sankey + @nivo/core.
// The card is hidden behind a toggle (collapsed by default), so the bundle
// is split into a chunk that only loads when the user opens the toggle.
const IncomeSankeyCard = React.lazy(() => import('./components/IncomeSankeyCard'));
import AdditionalFeatureToggle from './components/AdditionalFeatureToggle';
import SecFilings from './components/SecFilings';
import { useCompanyInfo, useEarnings, useFcfHistory, useGex, useIncomeSankey, type IncomeSankeyPeriod } from './useStockData';

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
  const [readyTicker, setReadyTicker] = React.useState<string | null>(null);
  const [isReverseDcfOpen, setIsReverseDcfOpen] = React.useState(false);
  const [isGexOpen, setIsGexOpen] = React.useState(false);
  const [isIncomeSankeyOpen, setIsIncomeSankeyOpen] = React.useState(false);
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
  const [sankeyPeriod, setSankeyPeriod] = React.useState<IncomeSankeyPeriod>('quarter');
  const { data: incomeSankey, loading: incomeSankeyLoading, error: incomeSankeyError } = useIncomeSankey(
    ticker,
    sankeyPeriod,
    isEquity && isIncomeSankeyOpen,
  );
  const { data: gex, loading: gexLoading, error: gexError } = useGex(ticker);
  // Cboe delayed-quotes only lists US-listed options. Hide the GEX
  // section entirely when the ticker has no chain (KOSPI/TSE, micro-caps).
  const showGex = !gexLoading && !gexError && gex?.available === true;

  React.useEffect(() => {
    setIsReverseDcfOpen(false);
    setIsGexOpen(false);
    setIsIncomeSankeyOpen(false);
    setSankeyPeriod('quarter');
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

  const [localTicker, setLocalTicker] = React.useState('');
  if (!ticker) {
    return (
      <div style={pageStyle}>
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
            <div style={{ fontSize: "var(--tf-fs-lg)", fontWeight: 700, color: 'var(--tf-text)', marginBottom: 8 }}>Stock Analysis</div>
            <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)', marginBottom: 24 }}>
              Enter a ticker symbol to view company profile, price chart, earnings, and valuation context.
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const t = localTicker.trim().toUpperCase();
                if (t) window.location.href = `/stock/${encodeURIComponent(t)}`;
              }}
              style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}
            >
              <div style={{ width: 'min(100%, 320px)', maxWidth: 320, flex: '1 1 240px' }}>
                <TickerSearchInput
                  value={localTicker}
                  onChange={setLocalTicker}
                  onSelect={(hit) => resolveAndGo(hit.symbol)}
                  onSubmit={async () => {
                    const t = localTicker.trim();
                    if (!t) return;
                    // Try Korean-aware ticker-search first; fall back to uppercase US tickers.
                    try {
                      const res = await fetch(`/api/ticker-search?q=${encodeURIComponent(t)}`);
                      if (res.ok) {
                        const data: { translated?: string; stocks?: { symbol: string }[] } = await res.json();
                        const sym = data.translated || data.stocks?.[0]?.symbol;
                        if (sym) { window.location.href = `/stock/${encodeURIComponent(sym)}`; return; }
                      }
                    } catch { /* fall through */ }
                    window.location.href = `/stock/${encodeURIComponent(t.toUpperCase())}`;
                  }}
                  placeholder="Search ticker or company"
                  ariaLabel="Search ticker or company"
                  inputStyle={{
                    width: '100%',
                    boxSizing: 'border-box',
                    height: 48,
                    border: '2px solid var(--tf-border)',
                    borderRadius: 'var(--tf-radius)',
                    padding: '0 16px',
                    fontSize: "var(--tf-fs-base)",
                    color: 'var(--tf-text)',
                    background: 'var(--tf-bg-elevated)',
                    outline: 'none',
                  }}
                />
              </div>
              <button
                type="submit"
                style={{
                  height: 48,
                  padding: '0 24px',
                  borderRadius: 'var(--tf-radius)',
                  border: 'none',
                  background: 'var(--tf-amber)',
                  color: 'var(--tf-bg)',
                  fontSize: "var(--tf-fs-base)",
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
                <div style={{ fontSize: "var(--tf-fs-xs)", fontWeight: 700, color: 'var(--tf-muted)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8 }}>
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
                        border: '1px solid var(--tf-border)',
                        borderRadius: 'var(--tf-radius)',
                        background: 'var(--tf-bg-elevated)',
                        textDecoration: 'none',
                        cursor: 'pointer',
                        transition: 'border-color 0.15s',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--tf-amber)')}
                      onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--tf-border)')}
                    >
                      <span style={{ fontSize: "var(--tf-fs-base)", fontWeight: 700, color: 'var(--tf-amber)' }}>{t.symbol}</span>
                      <span style={{ fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)' }}>{t.name}</span>
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

  if (!infoLoading && infoError) {
    return (
      <div style={pageStyle}>
        <main style={{ ...mainStyle, alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
          <div style={{ textAlign: 'center', maxWidth: 480, padding: 24 }}>
            <div style={{ fontFamily: 'var(--tf-mono)', fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)', letterSpacing: '0.12em' }}>UNKNOWN TICKER</div>
            <h1 style={{ margin: '8px 0 4px', fontFamily: 'var(--tf-mono)', fontSize: "var(--tf-fs-xl)", color: 'var(--tf-amber)' }}>{ticker}</h1>
            <p style={{ fontFamily: 'var(--tf-sans)', fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)', margin: 0 }}>
              Backend could not resolve this symbol.
            </p>
            <p style={{ fontFamily: 'var(--tf-sans)', fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)', marginTop: 16 }}>
              Try the ticker search above, or check spelling.
            </p>
            <a href="/terminal" style={{ display: 'inline-block', marginTop: 20, padding: '8px 16px', border: '1px solid var(--tf-amber)', color: 'var(--tf-amber)', fontFamily: 'var(--tf-mono)', fontSize: "var(--tf-fs-base)", textDecoration: 'none', letterSpacing: '0.08em' }}>
              ← Back to Terminal
            </a>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div style={pageStyle}>
      <main style={mainStyle}>
        <section style={rowGridStyle(isNarrowLayout, 'minmax(0, 1.6fr) minmax(360px, 1fr)', 'start')}>
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
            minHeight={0}
          >
              {companyInfo ? (
                <div style={overviewPanelStyle}>
                  <StockHeader info={companyInfo} />
                  <div style={overviewDividerStyle} />
                  <CompanyProfile info={companyInfo} />
                </div>
              ) : infoLoading ? (
                <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Loading company profile...</div>
              ) : infoError ? (
                <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-down)' }}>Failed to load: {infoError}</div>
              ) : (
                <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Company profile unavailable.</div>
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
              <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Loading earnings...</div>
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
          <AdditionalFeatureToggle
            title="Income Statement Flow"
            subtitle="Sankey diagram of revenue → margin → earnings, Y/Y vs same period prior year. Click to load."
            open={isIncomeSankeyOpen}
            onToggle={() => setIsIncomeSankeyOpen((current) => !current)}
          />
        ) : null}

        {isEquity && isIncomeSankeyOpen ? (
          <section>
            <React.Suspense fallback={<div style={{ padding: 16, color: 'var(--tf-muted)', fontSize: "var(--tf-fs-base)" }}>Loading diagram...</div>}>
              <IncomeSankeyCard
                payload={incomeSankey}
                loading={incomeSankeyLoading}
                error={incomeSankeyError}
                period={sankeyPeriod}
                onPeriodChange={setSankeyPeriod}
              />
            </React.Suspense>
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
              defaultBaseGrowthPct={(() => {
                const te = companyInfo?.trailingEps;
                const fe = companyInfo?.forwardEps;
                if (!te || !fe || te <= 0 || fe <= 0) return null;
                const g = ((fe / te) - 1.0) * 100.0;
                return Number.isFinite(g) ? g : null;
              })()}
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
          <AdditionalFeatureToggle
            title="Reverse DCF"
            subtitle={`Market-implied growth assumptions for ${ticker}. Open this only when you want the extra valuation tool.`}
            open={isReverseDcfOpen}
            onToggle={() => setIsReverseDcfOpen((current) => !current)}
          />
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

        {showGex ? (
          <AdditionalFeatureToggle
            title="Gamma Exposure (delayed)"
            subtitle={`Dealer GEX snapshot for ${ticker} from Cboe delayed quotes. Long/short gamma regime, zero-gamma strike, call/put walls.`}
            open={isGexOpen}
            onToggle={() => setIsGexOpen((current) => !current)}
          />
        ) : null}

        {showGex && isGexOpen ? (
          <section>
            <InsightCard
              title="Gamma Exposure (delayed)"
              subtitle={`Cboe delayed-quote chain. Updated on each page load.`}
              fillContent
              allowOverflow
            >
              <GexPanel payload={gex} loading={gexLoading} error={gexError} />
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
  background: 'var(--tf-bg)',
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  color: 'var(--tf-text)',
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
  background: 'var(--tf-border)',
};

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
