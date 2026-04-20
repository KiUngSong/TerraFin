import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { chartRequest } from '../api';
import { CHART_API_BASE, FONT_FAMILY } from '../constants';
import { flipSideTooltip } from '../../shared/positioningUtils';
import type { ChartHistoryBySeries, ChartUpdate } from '../types';

interface SearchInputProps {
  sessionId: string;
  seriesCount: number;
  maxSeries: number;
  onAdded: (update: ChartUpdate | null, historyBySeries?: ChartHistoryBySeries | null) => void;
  fullWidth?: boolean;
  compact?: boolean;
}

const INFO_TOOLTIP_WIDTH = 280;
const INFO_TOOLTIP_GAP = 12;
const INFO_TOOLTIP_EDGE_PADDING = 12;

const SERIES_META: Record<string, { helpTitle: string; helpText: string }> = {
  'Vol Regime': {
    helpTitle: 'Vol Regime',
    helpText:
      'Vol Regime measures the market volatility regime using the VIX 6-month percentile rank on a 0-100 scale. Low readings mean a calmer, more stable volatility regime. High readings mean a more stressed, unstable volatility regime. TerraFin uses sub-20 as calm and above-80 as elevated.',
  },
  MOVE: {
    helpTitle: 'MOVE',
    helpText:
      'MOVE is the bond-market implied volatility index. It tracks expected Treasury-rate volatility, similar to how VIX tracks expected equity volatility. In TerraFin it is available as a standalone bond-volatility read.',
  },
  'Net Breadth': {
    helpTitle: 'Net Breadth',
    helpText:
      'Net Breadth measures how broad the daily move is across the S&P 500 universe. It is advancers minus decliners as a share of the basket, so positive values mean participation is broadening, negative values mean weakness is widespread, and zero is roughly balanced.',
  },
};

const SearchInput: React.FC<SearchInputProps> = ({
  sessionId,
  seriesCount,
  maxSeries,
  onAdded,
  fullWidth = false,
  compact = false,
}) => {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const infoButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const infoTooltipRef = useRef<HTMLDivElement>(null);
  const [infoTarget, setInfoTarget] = useState<string | null>(null);
  const [infoTooltipPos, setInfoTooltipPos] = useState<{ top: number; left: number; placement: 'left' | 'right' } | null>(null);
  const disabled = seriesCount >= maxSeries;

  // Close dropdown on click outside
  useEffect(() => {
    if (!showDropdown) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
        setInfoTarget(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showDropdown]);

  useEffect(() => {
    if (!showDropdown) {
      setInfoTarget(null);
      setInfoTooltipPos(null);
      return;
    }
    const handleViewportChange = () => {
      setShowDropdown(false);
      setInfoTarget(null);
    };
    window.addEventListener('scroll', handleViewportChange, true);
    window.addEventListener('resize', handleViewportChange);
    return () => {
      window.removeEventListener('scroll', handleViewportChange, true);
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [showDropdown]);

  // Search suggestions
  const search = useCallback((q: string) => {
    if (!q.trim()) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }
    fetch(`${CHART_API_BASE}/chart-series/search?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then((data) => {
        setSuggestions(data.suggestions || []);
        setShowDropdown((data.suggestions || []).length > 0);
      })
      .catch(() => {});
  }, []);

  const handleInputChange = (val: string) => {
    setQuery(val);
    setError(false);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(val), 300);
  };

  const addSeries = useCallback(
    (name: string) => {
      if (!name.trim() || loading) return;
      setLoading(true);
      setShowDropdown(false);
      chartRequest(`${CHART_API_BASE}/chart-series/add`, sessionId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.ok) {
            setQuery('');
            setSuggestions([]);
            onAdded(data.mutation ?? null, data.historyBySeries ?? null);
          } else {
            setError(true);
            setTimeout(() => setError(false), 1500);
          }
          setLoading(false);
        })
        .catch(() => {
          setError(true);
          setLoading(false);
          setTimeout(() => setError(false), 1500);
        });
    },
    [loading, onAdded, sessionId]
  );

  const computeInfoTooltipPosition = (name: string) => {
    const infoButton = infoButtonRefs.current[name];
    if (!infoButton) return null;

    const rect = infoButton.getBoundingClientRect();
    return flipSideTooltip(
      rect,
      INFO_TOOLTIP_WIDTH,
      INFO_TOOLTIP_GAP,
      INFO_TOOLTIP_EDGE_PADDING,
    );
  };

  useLayoutEffect(() => {
    if (!showDropdown || !infoTarget) {
      setInfoTooltipPos(null);
      return;
    }
    const nextPos = computeInfoTooltipPosition(infoTarget);
    if (!nextPos) {
      setInfoTooltipPos(null);
      return;
    }
    setInfoTooltipPos((current) => {
      if (
        current &&
        current.top === nextPos.top &&
        current.left === nextPos.left &&
        current.placement === nextPos.placement
      ) {
        return current;
      }
      return nextPos;
    });
  }, [infoTarget, showDropdown, suggestions]);

  useLayoutEffect(() => {
    if (!infoTarget || !infoTooltipPos || !infoTooltipRef.current) return;
    const tooltipRect = infoTooltipRef.current.getBoundingClientRect();
    const minTop = tooltipRect.height / 2 + INFO_TOOLTIP_EDGE_PADDING;
    const maxTop = window.innerHeight - tooltipRect.height / 2 - INFO_TOOLTIP_EDGE_PADDING;
    const clampedTop = Math.min(Math.max(infoTooltipPos.top, minTop), maxTop);
    if (clampedTop !== infoTooltipPos.top) {
      setInfoTooltipPos({ ...infoTooltipPos, top: clampedTop });
    }
  }, [infoTarget, infoTooltipPos]);

  return (
    <div
      ref={containerRef}
      className={`tf-chart-search${fullWidth ? ' tf-chart-search--full' : ''}`}
      style={{ position: 'relative', ...(compact ? { width: 'clamp(118px, 34vw, 152px)', flexShrink: 0 } : null) }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          border: `1px solid ${error ? '#ef5350' : '#e0e0e0'}`,
          borderRadius: 6,
          background: disabled ? '#f5f5f5' : '#fff',
          padding: '0 8px',
          height: 28,
          transition: 'border-color 0.2s',
        }}
      >
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#999"
          strokeWidth="2"
          style={{ flexShrink: 0, marginRight: 6 }}
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addSeries(query);
          }}
          onFocus={() => {
            if (suggestions.length > 0) setShowDropdown(true);
          }}
          placeholder={disabled ? `Max ${maxSeries} charts` : 'Add chart...'}
          disabled={disabled || loading}
          style={{
            border: 'none',
            outline: 'none',
            background: 'transparent',
            fontFamily: FONT_FAMILY,
            fontSize: 12,
            color: '#333',
            width: '100%',
          }}
        />
        {loading && (
          <span style={{ fontSize: 10, color: '#999', flexShrink: 0 }}>...</span>
        )}
      </div>

      {showDropdown && suggestions.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: 4,
            background: '#fff',
            border: '1px solid #e0e0e0',
            borderRadius: 6,
            boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
            zIndex: 1000,
            maxHeight: 200,
            overflowY: 'auto',
            fontFamily: FONT_FAMILY,
          }}
        >
          {suggestions.map((name) => (
            <div key={name} style={{ position: 'relative' }}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => addSeries(name)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    addSeries(name);
                  }
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                  width: '100%',
                  padding: '7px 12px',
                  border: 'none',
                  boxSizing: 'border-box',
                  background: 'transparent',
                  cursor: 'pointer',
                  fontFamily: FONT_FAMILY,
                  fontSize: 12,
                  color: '#333',
                  textAlign: 'left',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = '#f5f5f5';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                }}
              >
                <span style={{ minWidth: 0, flex: 1 }}>{name}</span>
                {SERIES_META[name] && (
                  <button
                    ref={(node) => {
                      infoButtonRefs.current[name] = node;
                    }}
                    type="button"
                    aria-label={`${name} explanation`}
                    aria-expanded={infoTarget === name}
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      setInfoTarget((current) => (current === name ? null : name));
                    }}
                    onKeyDown={(e) => e.stopPropagation()}
                    onMouseEnter={() => setInfoTarget(name)}
                    onMouseLeave={() => setInfoTarget((current) => (current === name ? null : current))}
                    onFocus={() => setInfoTarget(name)}
                    onBlur={() => setInfoTarget((current) => (current === name ? null : current))}
                    style={{
                      width: 18,
                      height: 18,
                      borderRadius: 999,
                      border: '1px solid #cbd5e1',
                      background: infoTarget === name ? '#1976d2' : '#fff',
                      color: infoTarget === name ? '#fff' : '#5f6b7a',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontFamily: FONT_FAMILY,
                      fontSize: 11,
                      fontWeight: 700,
                      lineHeight: 1,
                      cursor: 'help',
                      padding: 0,
                      flexShrink: 0,
                    }}
                  >
                    i
                  </button>
                )}
              </div>
              {SERIES_META[name] && infoTarget === name && infoTooltipPos && createPortal(
                <div
                  ref={infoTooltipRef}
                  role="tooltip"
                  style={{
                    position: 'fixed',
                    top: infoTooltipPos.top,
                    left: infoTooltipPos.left,
                    transform: 'translateY(-50%)',
                    width: INFO_TOOLTIP_WIDTH,
                    padding: '10px 12px',
                    background: '#2d2d2d',
                    color: '#fff',
                    fontSize: 12,
                    fontFamily: FONT_FAMILY,
                    lineHeight: 1.5,
                    borderRadius: 8,
                    whiteSpace: 'normal',
                    zIndex: 10002,
                    boxShadow: '0 6px 18px rgba(0,0,0,0.2)',
                    pointerEvents: 'none',
                  }}
                >
                  <span
                    style={{
                      position: 'absolute',
                      top: '50%',
                      [infoTooltipPos.placement === 'right' ? 'right' : 'left']: '100%',
                      transform: 'translateY(-50%)',
                      width: 0,
                      height: 0,
                      border: '6px solid transparent',
                      [infoTooltipPos.placement === 'right' ? 'borderRightColor' : 'borderLeftColor']: '#2d2d2d',
                    }}
                  />
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{SERIES_META[name].helpTitle}</div>
                  <div>{SERIES_META[name].helpText}</div>
                </div>,
                document.body,
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SearchInput;
