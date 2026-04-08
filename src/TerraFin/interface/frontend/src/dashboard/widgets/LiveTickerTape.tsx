import React, { useMemo } from 'react';
import TradingViewEmbed, { type TradingViewTheme } from './TradingViewEmbed';

interface LiveTickerTapeProps {
  theme?: TradingViewTheme;
}

const SCRIPT_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js';

const LiveTickerTape: React.FC<LiveTickerTapeProps> = ({ theme = 'light' }) => {
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
      displayMode: 'adaptive',
      locale: 'en',
    }),
    []
  );

  return (
    <TradingViewEmbed
      scriptSrc={SCRIPT_SRC}
      config={config}
      minHeight={56}
      theme={theme}
      contentMinWidth={480}
      allowOverflowX
    />
  );
};

export default LiveTickerTape;
