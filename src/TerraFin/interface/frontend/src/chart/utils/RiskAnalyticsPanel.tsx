import React, { useEffect, useMemo, useRef } from 'react';
import { FONT_FAMILY } from '../constants';
import { computeRiskMetrics } from './riskMetrics';

interface RiskAnalyticsPanelProps {
  visible: boolean;
  onClose: () => void;
  closes: number[];
  mobile?: boolean;
}

const METRIC_UNITS: Record<string, string> = {
  'Ann. Return': '%',
  Volatility: '%',
  'Max DD': '%',
  'Win Rate': '%',
  'VaR 95%': '%',
  'VaR 99%': '%',
  'CVaR 95%': '%',
  'CVaR 99%': '%',
};

const METRIC_ORDER = [
  'Ann. Return',
  'Volatility',
  'Sharpe',
  'Sortino',
  'Max DD',
  'Calmar',
  'Win Rate',
  'VaR 95%',
  'VaR 99%',
  'CVaR 95%',
  'CVaR 99%',
];

const RiskAnalyticsPanel: React.FC<RiskAnalyticsPanelProps> = ({ visible, onClose, closes, mobile = false }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const metrics = useMemo(() => (visible ? computeRiskMetrics(closes) : null), [visible, closes]);

  // Close on click outside
  useEffect(() => {
    if (!visible) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const timer = setTimeout(() => document.addEventListener('mousedown', handler), 100);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handler);
    };
  }, [visible, onClose]);

  useEffect(() => {
    if (!visible) return;
    const handleViewportChange = () => {
      onClose();
    };
    window.addEventListener('scroll', handleViewportChange, true);
    window.addEventListener('resize', handleViewportChange);
    return () => {
      window.removeEventListener('scroll', handleViewportChange, true);
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [visible, onClose]);

  if (!visible) return null;

  const sorted = METRIC_ORDER.filter((k) => metrics && k in metrics);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'absolute',
        top: mobile ? 'auto' : 8,
        right: mobile ? 8 : 8,
        left: mobile ? 8 : 'auto',
        bottom: mobile ? 8 : 'auto',
        background: 'rgba(255,255,255,0.95)',
        border: '1px solid #e0e0e0',
        borderRadius: mobile ? 12 : 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
        zIndex: 100,
        fontFamily: FONT_FAMILY,
        fontSize: 12,
        minWidth: mobile ? 'auto' : 200,
        maxHeight: mobile ? 'min(60%, 320px)' : 'none',
        padding: 0,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid #eee',
          fontWeight: 600,
          fontSize: 12,
          color: '#333',
        }}
      >
        Risk Analytics
        <button
          type="button"
          onClick={onClose}
          style={{
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            padding: '2px 4px',
            fontSize: 14,
            color: '#999',
            lineHeight: 1,
          }}
        >
          ×
        </button>
      </div>

      {metrics && sorted.length > 0 ? (
        <div style={{ padding: '6px 0', overflowY: 'auto' }}>
          {sorted.map((key) => {
            const val = metrics[key];
            const unit = METRIC_UNITS[key] ?? '';
            const isNeg = val < 0;
            return (
              <div
                key={key}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '4px 12px',
                  gap: 16,
                }}
              >
                <span style={{ color: '#666' }}>{key}</span>
                <span style={{ fontWeight: 500, color: isNeg ? '#ef5350' : '#333', fontVariantNumeric: 'tabular-nums' }}>
                  {val}
                  {unit}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ padding: '12px', color: '#999', textAlign: 'center' }}>No data</div>
      )}
    </div>
  );
};

export default RiskAnalyticsPanel;
