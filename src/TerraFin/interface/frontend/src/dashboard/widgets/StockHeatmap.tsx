import React, { useMemo } from 'react';
import TradingViewEmbed, { type TradingViewTheme } from './TradingViewEmbed';
import { useViewportTier } from '../../shared/responsive';

type HeatmapGrouping = 'sector' | 'name' | 'no_group';

interface StockHeatmapProps {
  theme?: TradingViewTheme;
  height?: number;
  grouping?: HeatmapGrouping;
  dataSource?: string;
}

const SCRIPT_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js';

const StockHeatmap: React.FC<StockHeatmapProps> = ({
  theme = 'light',
  height = 500,
  grouping = 'sector',
  dataSource = 'SPX500',
}) => {
  const { isMobile, isTablet } = useViewportTier();
  const responsiveHeight = isMobile ? 320 : isTablet ? 400 : height;
  const responsiveMinWidth = isMobile ? 540 : isTablet ? 640 : undefined;

  const config = useMemo(
    () => ({
      exchanges: [],
      dataSource,
      grouping,
      blockSize: 'market_cap_basic',
      blockColor: 'change',
      locale: 'en',
      symbolUrl: '',
      hasTopBar: !isMobile,
      isDataSetEnabled: false,
      isZoomEnabled: false,
      hasSymbolTooltip: false,
      isMonoSize: false,
      width: '100%',
      height: responsiveHeight,
    }),
    [dataSource, grouping, isMobile, responsiveHeight]
  );

  return (
    <TradingViewEmbed
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
