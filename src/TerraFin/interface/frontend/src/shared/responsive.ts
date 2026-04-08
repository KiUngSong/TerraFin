import { useEffect, useState } from 'react';

export const MOBILE_MAX_WIDTH = 767;
export const TABLET_MAX_WIDTH = 1023;

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
