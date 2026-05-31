import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FONT_FAMILY } from '../constants';
import { dropdownBelowAnchorRight } from '../../shared/positioningUtils';
import { computeRiskMetrics } from './riskMetrics';

interface RiskAnalyticsPanelProps {
  visible: boolean;
  onClose: () => void;
  closes: number[];
  anchorRef?: React.RefObject<HTMLElement | null>;
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

const RiskAnalyticsPanel: React.FC<RiskAnalyticsPanelProps> = ({ visible, onClose, closes, anchorRef }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

  const metrics = useMemo(() => (visible ? computeRiskMetrics(closes) : null), [visible, closes]);

  useEffect(() => {
    if (!visible || !anchorRef?.current) {
      setAnchorRect(null);
      return;
    }
    setAnchorRect(anchorRef.current.getBoundingClientRect());
  }, [visible, anchorRef]);

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

  const positionStyle: React.CSSProperties = anchorRect
    ? { position: 'fixed', ...dropdownBelowAnchorRight(anchorRect) }
    : { position: 'fixed', top: 48, right: 8 };

  return (
    <div
      ref={containerRef}
      style={{
        ...positionStyle,
        background: 'var(--tf-bg-pane)',
        border: '1px solid var(--tf-border)',
        borderRadius: 'var(--tf-radius)',
        zIndex: 100,
        fontFamily: FONT_FAMILY,
        fontSize: "var(--tf-fs-xs)",
        minWidth: 220,
        maxWidth: 'calc(100vw - 16px)',
        maxHeight: 'min(60vh, 440px)',
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
          borderBottom: '1px solid var(--tf-border)',
          fontWeight: 600,
          fontSize: "var(--tf-fs-xs)",
          color: 'var(--tf-text)',
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
            fontSize: "var(--tf-fs-base)",
            color: 'var(--tf-muted)',
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
                <span style={{ color: 'var(--tf-muted)' }}>{key}</span>
                <span style={{ fontWeight: 500, color: isNeg ? 'var(--tf-down)' : 'var(--tf-text)', fontVariantNumeric: 'tabular-nums' }}>
                  {val}
                  {unit}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ padding: '12px', color: 'var(--tf-muted)', textAlign: 'center' }}>No data</div>
      )}
    </div>
  );
};

export default RiskAnalyticsPanel;
