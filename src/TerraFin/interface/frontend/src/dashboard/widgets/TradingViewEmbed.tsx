import React, { useEffect, useRef } from 'react';

type TradingViewTheme = 'light' | 'dark';

interface TradingViewEmbedProps {
  scriptSrc: string;
  config: Record<string, unknown>;
  minHeight?: number;
  theme?: TradingViewTheme;
  contentMinWidth?: number;
  allowOverflowX?: boolean;
}

const TradingViewEmbed: React.FC<TradingViewEmbedProps> = ({
  scriptSrc,
  config,
  minHeight = 56,
  theme = 'light',
  contentMinWidth,
  allowOverflowX = false,
}) => {
  const hostRef = useRef<HTMLDivElement | null>(null);

  // Serialize the effective payload so parent re-renders that produce an
  // identical config (common during resize / theme-toggle ping-pong) don't
  // tear down + refetch the TradingView script. Reference-only deps would
  // refire on every fresh useMemo result even when the values are equal.
  const serialized = JSON.stringify({ scriptSrc, theme, config });

  useEffect(() => {
    const host = hostRef.current;
    if (host == null) return;

    host.innerHTML = '';

    const container = document.createElement('div');
    container.className = 'tradingview-widget-container';
    container.style.width = '100%';
    container.style.height = '100%';

    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    widget.style.width = '100%';
    widget.style.height = '100%';

    const script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = scriptSrc;
    script.async = true;
    script.text = JSON.stringify({ ...config, colorTheme: theme });

    container.appendChild(widget);
    container.appendChild(script);
    host.appendChild(container);

    return () => {
      host.innerHTML = '';
    };
  }, [serialized]);

  return (
    <div
      className={`tf-tradingview-embed${allowOverflowX ? ' tf-tradingview-embed--scrollable' : ''}`}
      style={{ minHeight }}
    >
      <div className="tf-tradingview-embed__inner" style={{ minHeight, minWidth: contentMinWidth }}>
        <div ref={hostRef} style={{ width: '100%', minHeight }} />
      </div>
    </div>
  );
};

export type { TradingViewTheme };
export default TradingViewEmbed;
