import React, { useEffect, useMemo, useRef, useState } from 'react';
import TradingViewEmbed, { type TradingViewTheme } from './TradingViewEmbed';
import { useViewportTier } from '../../shared/responsive';
import { useTerminalStore } from '../../terminal/store';

type HeatmapGrouping = 'sector' | 'name' | 'no_group';

interface StockHeatmapProps {
  theme?: TradingViewTheme;
  grouping?: HeatmapGrouping;
  dataSource?: string;
}

const SCRIPT_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js';

const StockHeatmap: React.FC<StockHeatmapProps> = ({
  theme: themeProp,
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
  // On desktop the map fills its panel. TradingView sizes the map once at load,
  // so a new height reloads it, after the resize settles.
  const boxRef = useRef<HTMLDivElement>(null);
  const [fillHeight, setFillHeight] = useState<number | null>(null);
  useEffect(() => {
    const box = boxRef.current;
    if (box == null || isMobile || isTablet) return;
    let timer: number | undefined;
    const observer = new ResizeObserver(([entry]) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const h = Math.floor(entry.contentRect.height / 10) * 10;
        if (h > 0) setFillHeight(h);
      }, 200);
    });
    observer.observe(box);
    return () => {
      window.clearTimeout(timer);
      observer.disconnect();
    };
  }, [isMobile, isTablet]);
  const responsiveHeight = isMobile ? mobileHeight : isTablet ? 400 : fillHeight ?? 0;
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
    <div ref={boxRef} style={{ height: isMobile || isTablet ? undefined : '100%', minHeight: 0 }}>
    {/* On desktop the map waits for the panel's height, so it loads once. */}
    {!isMobile && !isTablet && fillHeight == null ? null : <TradingViewEmbed
      key={theme}
      scriptSrc={SCRIPT_SRC}
      config={config}
      minHeight={responsiveHeight}
      theme={theme}
      contentMinWidth={responsiveMinWidth}
      allowOverflowX={responsiveMinWidth != null}
    />}
    </div>
  );
};

export default StockHeatmap;
