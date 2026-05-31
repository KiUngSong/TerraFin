import React, { useEffect, useState } from 'react';
import InsightCard from '../terminal/components/InsightCard';
import DcfWorkbench from '../dcf/DcfWorkbench';
import { clearAgentViewContextSource, publishAgentViewContext } from '../agent/viewContext';
import { BREAKPOINTS } from '../shared/responsive';
import SpxGexSnapshotCard from '../terminal/widgets/SpxGexSnapshotCard';
import { useGex } from '../stock/useStockData';
import MacroFocusPanel from './components/MacroFocusPanel';

// Page reflows earlier than the shared tablet breakpoint (1023) because the
// sidebar + macro chart + top-companies grid become cramped well above that.
const NARROW_LAYOUT_BREAKPOINT = BREAKPOINTS.TABLET_MAX + 97; // 1120
import PortfolioHoldingDetails from './components/PortfolioHoldingDetails';
import PortfolioTreemap from './components/PortfolioTreemap';
import TopCompaniesTable from './components/TopCompaniesTable';
import {
  PortfolioHoldingRow,
  getPortfolioRowKey,
  parsePortfolioWeight,
  splitPortfolioStockLabel,
} from './components/portfolioPositioning';

interface InvestorPositioningPayload {
  guru: string;
  info: Record<string, string>;
  rows: PortfolioHoldingRow[];
  topHoldings: PortfolioHoldingRow[];
}

interface GuruListPayload {
  gurus?: string[];
  enabled?: boolean;
  message?: string | null;
}

interface FilingSummary {
  filing_date: string;
  period: string;
  accession: string;
}

const INVESTOR_POSITIONING_PANEL_HEIGHT = 520;

const MarketInsightsPage: React.FC = () => {
  const [macroChartReady, setMacroChartReady] = useState(false);
  const [gurus, setGurus] = useState<string[]>([]);
  const [selectedGuru, setSelectedGuru] = useState('');
  const [positioning, setPositioning] = useState<InvestorPositioningPayload | null>(null);
  const [investorPositioningEnabled, setInvestorPositioningEnabled] = useState(false);
  const [investorPositioningMessage, setInvestorPositioningMessage] = useState<string | null>(null);
  const [activeHoldingKey, setActiveHoldingKey] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [topCompanies, setTopCompanies] = useState<Array<{ rank: number; ticker: string; name: string; marketCap: string; country: string }>>([]);
  const [isNarrowLayout, setIsNarrowLayout] = useState(false);
  const { data: gexData, loading: gexLoading, error: gexError } = useGex('SPX');
  const [filingHistory, setFilingHistory] = useState<FilingSummary[]>([]);
  const [selectedAccession, setSelectedAccession] = useState<string | null>(null);

  useEffect(() => {
    if (!macroChartReady) return;
    fetch('/market-insights/api/top-companies')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((data) => setTopCompanies(data.companies || []))
      .catch(() => setTopCompanies([]));
  }, [macroChartReady]);

  useEffect(() => {
    const updateLayoutMode = () => setIsNarrowLayout(window.innerWidth < NARROW_LAYOUT_BREAKPOINT);
    updateLayoutMode();
    window.addEventListener('resize', updateLayoutMode);
    return () => window.removeEventListener('resize', updateLayoutMode);
  }, []);

  useEffect(() => {
    if (!macroChartReady) return;
    fetch('/market-insights/api/investor-positioning/gurus')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: GuruListPayload) => {
        const next = payload.gurus || [];
        const enabled = payload.enabled !== false;
        setGurus(next);
        setInvestorPositioningEnabled(enabled);
        setInvestorPositioningMessage(payload.message ?? null);
        if (next.length > 0) {
          setSelectedGuru(next[0]);
        } else {
          setSelectedGuru('');
        }
      })
      .catch(() => {
        setGurus([]);
        setSelectedGuru('');
        setInvestorPositioningEnabled(false);
        setInvestorPositioningMessage(
          'Investor positioning is unavailable. Set TERRAFIN_SEC_USER_AGENT to enable SEC EDGAR access.'
        );
      });
  }, [macroChartReady]);

  useEffect(() => {
    if (!selectedGuru || !investorPositioningEnabled) {
      setFilingHistory([]);
      setSelectedAccession(null);
      return;
    }
    fetch(`/market-insights/api/investor-positioning/history?guru=${encodeURIComponent(selectedGuru)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((data: { filings?: FilingSummary[] }) => setFilingHistory(data.filings || []))
      .catch(() => setFilingHistory([]));
    setSelectedAccession(null);
  }, [investorPositioningEnabled, selectedGuru]);

  useEffect(() => {
    if (!macroChartReady || !selectedGuru || !investorPositioningEnabled) {
      setIsLoading(false);
      setPositioning(null);
      return;
    }
    setActiveHoldingKey(null);
    setIsLoading(true);
    const url = selectedAccession
      ? `/market-insights/api/investor-positioning/holdings?guru=${encodeURIComponent(selectedGuru)}&accession=${encodeURIComponent(selectedAccession)}`
      : `/market-insights/api/investor-positioning/holdings?guru=${encodeURIComponent(selectedGuru)}`;
    fetch(url)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: InvestorPositioningPayload) => setPositioning(payload))
      .catch(() => setPositioning(null))
      .finally(() => setIsLoading(false));
  }, [investorPositioningEnabled, macroChartReady, selectedGuru, selectedAccession]);

  useEffect(() => {
    if (!activeHoldingKey) {
      return;
    }

    const hasActiveHolding = (positioning?.rows || []).some((row) => getPortfolioRowKey(row) === activeHoldingKey);
    if (!hasActiveHolding) {
      setActiveHoldingKey(null);
    }
  }, [activeHoldingKey, positioning]);

  const activeHolding = (positioning?.rows || []).find((row) => getPortfolioRowKey(row) === activeHoldingKey) || null;

  useEffect(() => {
    const route = `${window.location.pathname}${window.location.search}`;
    const rankedHoldings = [...(positioning?.rows || [])]
      .sort((left, right) => parsePortfolioWeight(right['% of Portfolio']) - parsePortfolioWeight(left['% of Portfolio']))
      .slice(0, 10)
      .map((holding, index) => {
        const label = splitPortfolioStockLabel(holding.Stock);
        return {
          rank: index + 1,
          ticker: label.ticker,
          company: label.company,
          weight: parsePortfolioWeight(holding['% of Portfolio']),
          recentActivity: holding['Recent Activity'],
          updated: holding.Updated,
        };
      });
    const activeLabel = activeHolding ? splitPortfolioStockLabel(activeHolding.Stock) : null;
    void publishAgentViewContext({
      source: 'market-insights-page',
      scope: 'page',
      route,
      pageType: 'market-insights',
      title: selectedGuru ? `${selectedGuru} Portfolio View` : 'Market Insights',
      summary: selectedGuru
        ? `Viewing market insights with ${selectedGuru}'s portfolio positioning.`
        : 'Viewing market insights in TerraFin.',
      selection: {
        selectedGuru: selectedGuru || null,
        activeHoldingTicker: activeLabel?.ticker || null,
        activeHoldingCompany: activeLabel?.company || null,
        investorPositioningEnabled,
        macroChartReady,
        topHoldingTickers: rankedHoldings.map((holding) => holding.ticker),
      },
      entities: [
        ...(selectedGuru
          ? [
              {
                kind: 'portfolio',
                id: selectedGuru,
                label: selectedGuru,
                attributes: {
                  period: positioning?.info?.Period || null,
                  holdingCount: positioning?.rows?.length || 0,
                  topHoldings: rankedHoldings,
                },
              },
            ]
          : []),
        ...(activeLabel
          ? [
              {
                kind: 'holding',
                id: activeLabel.ticker,
                label: activeLabel.company || activeLabel.ticker,
                attributes: {
                  ticker: activeLabel.ticker,
                  stock: activeHolding?.Stock || null,
                  weight: activeHolding ? parsePortfolioWeight(activeHolding['% of Portfolio']) : null,
                  recentActivity: activeHolding?.['Recent Activity'] || null,
                  updated: activeHolding?.Updated || null,
                },
              },
            ]
          : []),
      ],
      metadata: {
        source: 'market-insights-page',
        topCompaniesCount: topCompanies.length,
        holdingCount: positioning?.rows?.length || 0,
      },
    });
    return () => {
      void clearAgentViewContextSource('market-insights-page');
    };
  }, [
    activeHolding,
    investorPositioningEnabled,
    macroChartReady,
    positioning,
    selectedGuru,
    topCompanies.length,
  ]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        height: '100%',
        overflowY: 'auto',
        overflowX: 'hidden',
        background: 'var(--tf-bg)',
        fontFamily: 'var(--tf-sans)',
        color: 'var(--tf-text)',
      }}
    >
      <main style={{ display: 'grid', gap: 16, padding: 16 }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: isNarrowLayout ? '1fr' : '1.2fr 1fr',
            gap: 16,
            alignItems: 'stretch',
          }}
        >
          <InsightCard title="Macro Analysis" subtitle="Index and indicator deep-dive with interactive chart.">
            <MacroFocusPanel onReadyChange={setMacroChartReady} />
          </InsightCard>
          <div style={{ position: 'relative', minHeight: 300 }}>
            <div style={{ position: 'absolute', inset: 0 }}>
              <InsightCard title="Top Companies by Market Cap" subtitle="Top 50 companies ranked by market capitalization." fillContent>
                <TopCompaniesTable companies={topCompanies} />
              </InsightCard>
            </div>
          </div>
        </div>

        <InsightCard title="Investor Positioning" subtitle="Guru portfolio concentration and top holdings.">
          <div style={{ display: 'grid', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <label htmlFor="guru-selector" style={{ fontSize: 'var(--tf-fs-base)', color: 'var(--tf-text)', fontWeight: 600 }}>
                Guru
              </label>
              <select
                id="guru-selector"
                value={selectedGuru}
                onChange={(event) => setSelectedGuru(event.target.value)}
                disabled={!investorPositioningEnabled || gurus.length === 0 || isLoading}
                style={{
                  border: '1px solid var(--tf-border)',
                  borderRadius: 'var(--tf-radius)',
                  padding: '8px 10px',
                  minWidth: 260,
                  background: 'var(--tf-bg-elevated)',
                  color: !investorPositioningEnabled ? 'var(--tf-muted)' : 'var(--tf-text)',
                  cursor: !investorPositioningEnabled ? 'not-allowed' : 'pointer',
                  fontFamily: 'var(--tf-sans)',
                  fontSize: 'var(--tf-fs-base)',
                }}
              >
                {gurus.map((guru) => (
                  <option key={guru} value={guru}>
                    {guru}
                  </option>
                ))}
              </select>
              {investorPositioningEnabled && (
                <>
                  <label htmlFor="period-selector" style={{ fontSize: 'var(--tf-fs-base)', color: 'var(--tf-text)', fontWeight: 600 }}>
                    Period
                  </label>
                  <select
                    id="period-selector"
                    value={selectedAccession ?? ''}
                    onChange={(e) => setSelectedAccession(e.target.value || null)}
                    disabled={isLoading || filingHistory.length === 0}
                    style={{
                      border: '1px solid var(--tf-border)',
                      borderRadius: 'var(--tf-radius)',
                      padding: '8px 10px',
                      background: 'var(--tf-bg-elevated)',
                      color: filingHistory.length === 0 ? 'var(--tf-muted)' : 'var(--tf-text)',
                      cursor: filingHistory.length === 0 || isLoading ? 'not-allowed' : 'pointer',
                      fontSize: 'var(--tf-fs-base)',
                      minWidth: 110,
                      fontFamily: 'var(--tf-sans)',
                    }}
                  >
                    {filingHistory.length === 0 ? (
                      <option value="">—</option>
                    ) : (
                      <>
                        <option value="">{filingHistory[0].period}</option>
                        {filingHistory.slice(1).map((f) => (
                          <option key={f.accession} value={f.accession}>
                            {f.period}
                          </option>
                        ))}
                      </>
                    )}
                  </select>
                </>
              )}
            </div>

            {!investorPositioningEnabled && investorPositioningMessage ? (
              <div
                style={{
                  border: '1px solid var(--tf-border)',
                  borderRadius: 'var(--tf-radius)',
                  padding: '12px 14px',
                  background: 'var(--tf-bg-elevated)',
                  color: 'var(--tf-text)',
                  fontSize: "var(--tf-fs-base)",
                  lineHeight: 1.6,
                }}
              >
                {investorPositioningMessage}
              </div>
            ) : null}

            {isLoading ? (
              <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>Loading investor positioning...</div>
            ) : null}

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: isNarrowLayout ? '1fr' : '1.3fr 1fr',
                gap: 12,
                alignItems: 'start',
              }}
            >
              <div
                style={{
                  border: '1px solid var(--tf-border)',
                  borderRadius: 'var(--tf-radius)',
                  padding: 12,
                  background: 'var(--tf-bg-elevated)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  minHeight: 0,
                  height: INVESTOR_POSITIONING_PANEL_HEIGHT,
                  boxSizing: 'border-box',
                }}
              >
                <div style={{ fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)', marginBottom: 8 }}>Portfolio Treemap</div>
                <div style={{ flex: 1, minHeight: 0 }}>
                  <PortfolioTreemap
                    rows={positioning?.rows || []}
                    height="100%"
                    activeRowKey={activeHoldingKey}
                    onActiveRowChange={(row) => setActiveHoldingKey(row ? getPortfolioRowKey(row) : null)}
                  />
                </div>
              </div>
              <div
                style={{
                  border: '1px solid var(--tf-border)',
                  borderRadius: 'var(--tf-radius)',
                  padding: 12,
                  background: 'var(--tf-bg-elevated)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  minHeight: 0,
                  height: INVESTOR_POSITIONING_PANEL_HEIGHT,
                  boxSizing: 'border-box',
                }}
              >
                <div style={{ fontSize: "var(--tf-fs-xs)", color: 'var(--tf-muted)' }}>
                  {activeHolding ? 'Holding Details' : 'Portfolio Snapshot'}
                </div>
                <div style={{ flex: 1, minHeight: 0 }}>
                  <PortfolioHoldingDetails
                    guru={positioning?.guru || selectedGuru}
                    period={positioning?.info?.Period}
                    sourceUrl={positioning?.info?.Source}
                    rows={positioning?.rows || []}
                    topHoldings={positioning?.topHoldings || []}
                    activeRow={activeHolding}
                    height="100%"
                  />
                </div>
              </div>
            </div>
          </div>
        </InsightCard>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: isNarrowLayout ? '1fr' : '1fr 1fr',
            gap: 16,
            alignItems: 'stretch',
          }}
        >
          {!gexLoading && !gexError && gexData?.available === true ? (
            <SpxGexSnapshotCard data={gexData} loading={gexLoading} error={gexError} />
          ) : null}

          <InsightCard
            title="S&P 500 DCF"
            subtitle="Year-end target valuation range for the S&P 500."
            fillContent
            allowOverflow
          >
            <DcfWorkbench mode="index" endpoint="/market-insights/api/dcf/sp500" />
          </InsightCard>
        </div>
      </main>
    </div>
  );
};


export default MarketInsightsPage;
