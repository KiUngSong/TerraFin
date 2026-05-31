import React, { useMemo } from 'react';
import TradingViewEmbed, { type TradingViewTheme } from './TradingViewEmbed';
import { useViewportTier } from '../../shared/responsive';
import { useTerminalStore } from '../../terminal/store';

type HeatmapGrouping = 'sector' | 'name' | 'no_group';

interface StockHeatmapProps {
  theme?: TradingViewTheme;
  height?: number;
  grouping?: HeatmapGrouping;
  dataSource?: string;
}

const SCRIPT_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js';

const StockHeatmap: React.FC<StockHeatmapProps> = ({
  theme: themeProp,
  height = 500,
  grouping = 'sector',
  dataSource = 'SPX500',
}) => {
  const storeTheme = useTerminalStore((s) => s.theme);
  const theme: TradingViewTheme = themeProp ?? storeTheme;
  const { isMobile, isTablet } = useViewportTier();
  // Mobile height comes from the --tf-panel-h-mobile token so this embed and
  // the sibling Sectors grid fill the same panel box (no tab-switch reflow).
  const mobileHeight = useMemo(() => {
    if (typeof window === 'undefined') return 460;
    const raw = getComputedStyle(document.documentElement).getPropertyValue('--tf-panel-h-mobile');
    const n = parseInt(raw, 10);
    return Number.isFinite(n) && n > 0 ? n : 460;
  }, []);
  const responsiveHeight = isMobile ? mobileHeight : isTablet ? 400 : height;
  const responsiveMinWidth = isMobile ? 540 : isTablet ? 640 : undefined;

  const config = useMemo(
    () => ({
      exchanges: [],
      dataSource,
      grouping,
      blockSize: 'market_cap_basic',
      blockColor: 'change',
      locale: 'en',
      hasTopBar: !isMobile,
      isDataSetEnabled: false,
      isZoomEnabled: false,
      hasSymbolTooltip: true,
      symbolUrl: '/stock/',
      isMonoSize: false,
      width: '100%',
      height: responsiveHeight,
    }),
    [dataSource, grouping, isMobile, responsiveHeight]
  );

  return (
    <TradingViewEmbed
      key={theme}
      scriptSrc={SCRIPT_SRC}
      config={config}
      minHeight={responsiveHeight}
      theme={theme}
      contentMinWidth={responsiveMinWidth}
      allowOverflowX={responsiveMinWidth != null}
    />
  );
};

export default StockHeatmap;
