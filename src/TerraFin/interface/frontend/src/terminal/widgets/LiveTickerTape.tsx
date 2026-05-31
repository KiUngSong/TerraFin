import React, { useMemo } from 'react';
import TradingViewEmbed, { type TradingViewTheme } from './TradingViewEmbed';
import InsightCard from '../components/InsightCard';
import { useTerminalStore } from '../../terminal/store';

interface LiveTickerTapeProps {
  theme?: TradingViewTheme;
}

const SCRIPT_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js';

const LiveTickerTape: React.FC<LiveTickerTapeProps> = ({ theme: themeProp }) => {
  const storeTheme = useTerminalStore((s) => s.theme);
  const theme: TradingViewTheme = themeProp ?? storeTheme;
  const config = useMemo(
    () => ({
      symbols: [
        { proName: 'FOREXCOM:DJI', title: 'Dow Jones' },
        { proName: 'FOREXCOM:SPXUSD', title: 'S&P 500 Index' },
        { proName: 'FOREXCOM:NSXUSD', title: 'Nasdaq 100' },
        { proName: 'PEPPERSTONE:VIX', title: 'VIX' },
      ],
      showSymbolLogo: false,
      isTransparent: false,
      displayMode: 'regular',
      locale: 'en',
    }),
    [],
  );

  return (
    <InsightCard
      title=""
      className="tf-pane--tape"
      allowOverflow
      fillContent
    >
      <TradingViewEmbed
        scriptSrc={SCRIPT_SRC}
        config={config}
        minHeight={46}
        theme={theme}
        contentMinWidth={720}
        allowOverflowX
        fadeEdges
      />
    </InsightCard>
  );
};

export default LiveTickerTape;
