import React, { useEffect, useState } from 'react';
import DashboardHeader from '../dashboard/components/DashboardHeader';
import InsightCard from '../dashboard/components/InsightCard';
import DcfWorkbench from '../dcf/DcfWorkbench';
import { clearAgentViewContextSource, publishAgentViewContext } from '../agent/viewContext';
import MacroFocusPanel from './components/MacroFocusPanel';
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

const INVESTOR_POSITIONING_PANEL_HEIGHT = 520;

const MarketInsightsPage: React.FC = () => {
  const [searchValue, setSearchValue] = useState('');
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
  const [sp500DcfOpen, setSp500DcfOpen] = useState(false);

  useEffect(() => {
    if (!macroChartReady) return;
    fetch('/market-insights/api/top-companies')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((data) => setTopCompanies(data.companies || []))
      .catch(() => setTopCompanies([]));
  }, [macroChartReady]);

  useEffect(() => {
    const updateLayoutMode = () => setIsNarrowLayout(window.innerWidth < 1120);
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
    if (!macroChartReady || !selectedGuru || !investorPositioningEnabled) {
      setIsLoading(false);
      setPositioning(null);
      return;
    }
    setActiveHoldingKey(null);
    setIsLoading(true);
    fetch(`/market-insights/api/investor-positioning/holdings?guru=${encodeURIComponent(selectedGuru)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: InvestorPositioningPayload) => setPositioning(payload))
      .catch(() => setPositioning(null))
      .finally(() => setIsLoading(false));
  }, [investorPositioningEnabled, macroChartReady, selectedGuru]);

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
        overflow: 'auto',
        background: 'linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%)',
        fontFamily:
          'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
      }}
    >
      <DashboardHeader searchValue={searchValue} onSearchChange={setSearchValue} />

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

        <InsightCard
          title="S&P 500 DCF"
          subtitle="Year-end target valuation range for the S&P 500."
          allowOverflow
          minHeight={sp500DcfOpen ? 156 : 96}
        >
          <div style={{ display: 'grid', gap: 12 }}>
            <button
              type="button"
              onClick={() => setSp500DcfOpen((current) => !current)}
              style={dcfToggleButtonStyle(sp500DcfOpen)}
              aria-expanded={sp500DcfOpen}
            >
              <span>{sp500DcfOpen ? 'Hide S&P 500 DCF' : 'Show S&P 500 DCF'}</span>
              <span style={{ fontSize: 15, lineHeight: 1 }}>{sp500DcfOpen ? '−' : '+'}</span>
            </button>
            {sp500DcfOpen ? (
              <DcfWorkbench
                mode="index"
                endpoint="/market-insights/api/dcf/sp500"
              />
            ) : null}
          </div>
        </InsightCard>

        <InsightCard title="Investor Positioning" subtitle="Guru portfolio concentration and top holdings.">
          <div style={{ display: 'grid', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <label htmlFor="guru-selector" style={{ fontSize: 13, color: '#334155', fontWeight: 600 }}>
                Guru
              </label>
              <select
                id="guru-selector"
                value={selectedGuru}
                onChange={(event) => setSelectedGuru(event.target.value)}
                disabled={!investorPositioningEnabled || gurus.length === 0 || isLoading}
                style={{
                  border: '1px solid #cbd5e1',
                  borderRadius: 8,
                  padding: '8px 10px',
                  minWidth: 260,
                  background: !investorPositioningEnabled ? '#f8fafc' : '#fff',
                  color: !investorPositioningEnabled ? '#94a3b8' : '#0f172a',
                  cursor: !investorPositioningEnabled ? 'not-allowed' : 'pointer',
                }}
              >
                {gurus.map((guru) => (
                  <option key={guru} value={guru}>
                    {guru}
                  </option>
                ))}
              </select>
              <div style={{ fontSize: 12, color: '#64748b' }}>
                {positioning?.info?.Period ? `Period: ${positioning.info.Period}` : ''}
              </div>
            </div>

            {!investorPositioningEnabled && investorPositioningMessage ? (
              <div
                style={{
                  border: '1px solid #cbd5e1',
                  borderRadius: 12,
                  padding: '12px 14px',
                  background: '#f8fafc',
                  color: '#475569',
                  fontSize: 13,
                  lineHeight: 1.6,
                }}
              >
                {investorPositioningMessage}
              </div>
            ) : null}

            {isLoading ? (
              <div style={{ fontSize: 13, color: '#475569' }}>Loading investor positioning...</div>
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
                  border: '1px solid #e2e8f0',
                  borderRadius: 14,
                  padding: 12,
                  background: '#ffffff',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  minHeight: 0,
                  height: INVESTOR_POSITIONING_PANEL_HEIGHT,
                  boxSizing: 'border-box',
                }}
              >
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>Portfolio Treemap</div>
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
                  border: '1px solid #e2e8f0',
                  borderRadius: 14,
                  padding: 12,
                  background: '#ffffff',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  minHeight: 0,
                  height: INVESTOR_POSITIONING_PANEL_HEIGHT,
                  boxSizing: 'border-box',
                }}
              >
                <div style={{ fontSize: 12, color: '#64748b' }}>
                  {activeHolding ? 'Holding Details' : 'Portfolio Snapshot'}
                </div>
                <div style={{ flex: 1, minHeight: 0 }}>
                  <PortfolioHoldingDetails
                    guru={positioning?.guru || selectedGuru}
                    period={positioning?.info?.Period}
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
      </main>
    </div>
  );
};

function dcfToggleButtonStyle(open: boolean): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    width: '100%',
    borderRadius: 12,
    border: '1px solid #cbd5e1',
    background: open ? '#eff6ff' : '#ffffff',
    color: '#0f172a',
    padding: '12px 14px',
    fontSize: 13,
    fontWeight: 700,
    cursor: 'pointer',
  };
}

export default MarketInsightsPage;
