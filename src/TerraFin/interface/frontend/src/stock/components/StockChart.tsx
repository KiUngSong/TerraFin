import React, { useEffect, useRef, useState } from 'react';
import { chartRequest, getChartSessionId } from '../../chart/api';
import ChartComponent from '../../chart/ChartComponent';
import { CHART_API_BASE, type ChartScaleMargins } from '../../chart/constants';
import type { ChartHistoryBySeries, ChartSnapshot } from '../../chart/types';

interface StockChartProps {
  ticker: string;
  onReadyChange?: (ready: boolean) => void;
}

const STOCK_CHART_COMPACT_BREAKPOINT = 920;
const STOCK_CHART_SCALE_MARGINS: ChartScaleMargins = { top: 0.05, bottom: 0.05 };

const StockChart: React.FC<StockChartProps> = ({ ticker, onReadyChange }) => {
  const [snapshot, setSnapshot] = useState<ChartSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [historyBySeries, setHistoryBySeries] = useState<ChartHistoryBySeries>({});
  const sessionIdRef = useRef(getChartSessionId('stock-analysis'));
  const onReadyChangeRef = useRef(onReadyChange);

  useEffect(() => {
    onReadyChangeRef.current = onReadyChange;
  }, [onReadyChange]);

  useEffect(() => {
    if (!ticker) return;
    const controller = new AbortController();
    setIsLoading(true);
    setLoadError(null);
    setHistoryBySeries({});
    onReadyChangeRef.current?.(false);
    chartRequest(`${CHART_API_BASE}/chart-series/progressive/set`, sessionIdRef.current, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: ticker, pinned: true, seedPeriod: '3y' }),
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`${response.status}`))))
      .then((payload) => {
        if (!payload.ok) throw new Error(payload.error || 'Failed to initialize chart');
        const nextSnapshot = {
          payload: {
            mode: payload.mode,
            series: payload.series,
            dataLength: payload.dataLength,
            forcePercentage: payload.forcePercentage === true,
          },
          entries: payload.entries || [],
        };
        setSnapshot(nextSnapshot);
        setHistoryBySeries(payload.historyBySeries ?? {});
        onReadyChangeRef.current?.(true);
      })
      .catch((error) => {
        if (error instanceof Error && error.name === 'AbortError') return;
        setLoadError(error instanceof Error ? error.message : 'Failed to load chart');
        onReadyChangeRef.current?.(false);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      });

    return () => controller.abort();
  }, [ticker]);

  if (!snapshot && loadError) {
    return <div style={{ padding: '18px 0', fontSize: 13, color: '#b91c1c' }}>Failed to load chart: {loadError}</div>;
  }

  if (!snapshot) {
    return <div style={{ padding: '18px 0', fontSize: 13, color: '#475569' }}>Loading chart...</div>;
  }

  return (
    <div style={{ height: 500, position: 'relative', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          minWidth: 0,
          border: '1px solid #e2e8f0',
          borderRadius: 12,
          overflow: 'hidden',
          background: '#ffffff',
        }}
      >
        <ChartComponent
          sessionId={sessionIdRef.current}
          initialPayload={snapshot.payload}
          initialEntries={snapshot.entries}
          pollingEnabled={false}
          initialHistoryBySeries={historyBySeries}
          compactBreakpoint={STOCK_CHART_COMPACT_BREAKPOINT}
          priceScaleMargins={STOCK_CHART_SCALE_MARGINS}
        />
      </div>
      {isLoading ? (
        <div
          style={{
            position: 'absolute',
            top: 10,
            right: 10,
            padding: '4px 8px',
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 700,
            color: '#334155',
            background: 'rgba(255,255,255,0.92)',
            border: '1px solid #e2e8f0',
          }}
          >
          Refreshing...
        </div>
      ) : null}
    </div>
  );
};

export default StockChart;
