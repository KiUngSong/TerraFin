import { useEffect, useState } from 'react';

// Canonical viewport-width breakpoints. Anything that makes a *viewport*-scale
// decision (page grid reflow, full-screen modal, fixed widget) should read
// these. Container-width decisions (e.g. ChartComponent's ResizeObserver) are
// intentionally separate and should NOT be routed through these constants.
export const BREAKPOINTS = {
  MOBILE_MAX: 767,
  TABLET_MAX: 1023,
  CHART_COMPACT_MAX: 1000,
} as const;

export const MOBILE_MAX_WIDTH = BREAKPOINTS.MOBILE_MAX;
export const TABLET_MAX_WIDTH = BREAKPOINTS.TABLET_MAX;

export type ResponsiveTier = 'mobile' | 'tablet' | 'desktop';

export function getResponsiveTier(width: number): ResponsiveTier {
  if (width <= MOBILE_MAX_WIDTH) {
    return 'mobile';
  }
  if (width <= TABLET_MAX_WIDTH) {
    return 'tablet';
  }
  return 'desktop';
}

export function useViewportTier() {
  const [width, setWidth] = useState<number>(() =>
    typeof window === 'undefined' ? TABLET_MAX_WIDTH + 1 : window.innerWidth
  );

  useEffect(() => {
    const handleResize = () => setWidth(window.innerWidth);
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const tier = getResponsiveTier(width);

  return {
    width,
    tier,
    isMobile: tier === 'mobile',
    isTablet: tier === 'tablet',
    isDesktop: tier === 'desktop',
    isTabletOrBelow: tier !== 'desktop',
  };
}
