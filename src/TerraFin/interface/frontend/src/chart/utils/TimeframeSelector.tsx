import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { chartRequest } from '../api';
import { DAYS_OPTIONS, FONT_FAMILY, VIEW_LETTER } from '../constants';
import { dropdownBelowAnchorLeft } from '../../shared/positioningUtils';
import type { ChartHistoryBySeries, ChartSnapshot } from '../types';

interface TimeframeSelectorProps {
  sessionId: string;
  activeView: string;
  onViewChange: (view: string, snapshot: ChartSnapshot | null, historyBySeries?: ChartHistoryBySeries | null) => void;
  compact?: boolean;
}

const TimeframeSelector: React.FC<TimeframeSelectorProps> = ({
  sessionId,
  activeView,
  onViewChange,
  compact = false,
}) => {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [pendingView, setPendingView] = useState<string | null>(null);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [buttonHover, setButtonHover] = useState(false);
  const [hoveredOption, setHoveredOption] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const compactButtonRef = useRef<HTMLButtonElement>(null);
  const compactMenuRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const [compactMenuPos, setCompactMenuPos] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (!dropdownOpen) return;
    const handleClickOutside = (e: Event) => {
      const target = e.target as Node;
      const insideDropdown = dropdownRef.current?.contains(target) ?? false;
      const insideCompactMenu = compactMenuRef.current?.contains(target) ?? false;
      if (!insideDropdown && !insideCompactMenu) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('touchstart', handleClickOutside, { passive: true });
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('touchstart', handleClickOutside);
    };
  }, [dropdownOpen]);

  useEffect(() => {
    if (!dropdownOpen && !tooltipVisible) return;
    const handleViewportChange = () => {
      setDropdownOpen(false);
      setTooltipVisible(false);
      setButtonHover(false);
      setHoveredOption(null);
    };
    window.addEventListener('scroll', handleViewportChange, true);
    window.addEventListener('resize', handleViewportChange);
    return () => {
      window.removeEventListener('scroll', handleViewportChange, true);
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [dropdownOpen, tooltipVisible]);

  useLayoutEffect(() => {
    if (!compact || !dropdownOpen || !compactButtonRef.current) {
      setCompactMenuPos(null);
      return;
    }
    const rect = compactButtonRef.current.getBoundingClientRect();
    setCompactMenuPos(dropdownBelowAnchorLeft(rect, 148));
  }, [compact, dropdownOpen]);

  useEffect(() => {
    if (pendingView && activeView === pendingView) {
      setPendingView(null);
    }
  }, [activeView, pendingView]);

  const displayedView = pendingView ?? activeView;

  const setView = (view: string) => {
    if (view === displayedView) {
      setDropdownOpen(false);
      return;
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setPendingView(view);
    setDropdownOpen(false);

    chartRequest('/chart/api/chart-view', sessionId, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ view }),
    })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`${response.status}`))))
      .then((data) => {
        if (requestId !== requestIdRef.current) return;
        onViewChange(
          view,
          {
            payload: {
              mode: data.mode,
              series: data.series,
              dataLength: data.dataLength,
              forcePercentage: data.forcePercentage === true,
            },
            entries: data.entries || [],
            historyBySeries: data.historyBySeries ?? {},
          },
          data.historyBySeries ?? null
        );
        setPendingView(null);
      })
      .catch(() => {
        if (requestId === requestIdRef.current) {
          setPendingView(null);
        }
      });
  };

  const tooltipLabel = DAYS_OPTIONS.find((o) => o.id === displayedView)?.label ?? '1 day';

  if (compact) {
    return (
      <>
        <div
          style={{
            position: 'relative',
            display: 'inline-flex',
            alignItems: 'center',
            minWidth: 'max-content',
            flexShrink: 0,
          }}
        >
          <button
            ref={compactButtonRef}
            type="button"
            aria-label="Change chart interval"
            aria-expanded={dropdownOpen}
            onClick={(event) => {
              event.stopPropagation();
              setDropdownOpen((open) => !open);
            }}
            style={{
              minWidth: 0,
              minHeight: 0,
              padding: '5px 8px',
              borderRadius: 6,
              border: 'none',
              background: dropdownOpen ? '#f0f0f0' : 'transparent',
              color: '#1a1a1a',
              fontFamily: FONT_FAMILY,
              fontSize: 12,
              fontWeight: 600,
              lineHeight: 1,
              cursor: 'pointer',
              boxShadow: 'none',
            }}
          >
            {VIEW_LETTER[displayedView] ?? 'D'}
          </button>
        </div>

        {dropdownOpen && compactMenuPos
          ? createPortal(
              <div
                ref={compactMenuRef}
                style={{
                  position: 'fixed',
                  top: compactMenuPos.top,
                  left: compactMenuPos.left,
                  width: 148,
                  padding: 4,
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
                  gap: 4,
                  background: 'rgba(255, 255, 255, 0.98)',
                  border: '1px solid rgba(215, 220, 227, 0.92)',
                  borderRadius: 10,
                  boxShadow: '0 10px 24px rgba(15, 23, 42, 0.12)',
                  zIndex: 10000,
                  backdropFilter: 'blur(8px)',
                }}
              >
                {DAYS_OPTIONS.map(({ id }) => {
                  const active = displayedView === id;
                  const letter = VIEW_LETTER[id] ?? id.slice(0, 1).toUpperCase();
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setView(id)}
                      style={{
                        minHeight: 32,
                        border: active ? '1px solid #0f172a' : '1px solid transparent',
                        borderRadius: 6,
                        background: active ? '#0f172a' : 'transparent',
                        color: active ? '#ffffff' : '#475569',
                        fontFamily: FONT_FAMILY,
                        fontSize: 12,
                        fontWeight: active ? 700 : 600,
                        cursor: 'pointer',
                        boxShadow: active ? '0 1px 2px rgba(15, 23, 42, 0.08)' : 'none',
                      }}
                    >
                      {letter}
                    </button>
                  );
                })}
              </div>,
              document.body
            )
          : null}
      </>
    );
  }

  return (
    <>
      <div ref={dropdownRef} style={{ position: 'relative' }}>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setDropdownOpen((open) => !open);
          }}
          onMouseEnter={() => {
            setTooltipVisible(true);
            setButtonHover(true);
          }}
          onMouseLeave={() => {
            setTooltipVisible(false);
            setButtonHover(false);
          }}
          style={{
            fontFamily: FONT_FAMILY,
            padding: '6px 10px',
            fontSize: 13,
            fontWeight: 500,
            border: 'none',
            borderRadius: 6,
            background: buttonHover || dropdownOpen ? '#f0f0f0' : 'transparent',
            color: '#1a1a1a',
            cursor: 'pointer',
          }}
        >
          {VIEW_LETTER[displayedView] ?? 'D'}
        </button>
        {tooltipVisible && !dropdownOpen && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              marginTop: 6,
              padding: '6px 10px',
              background: '#2d2d2d',
              color: '#fff',
              fontSize: 12,
              fontFamily: FONT_FAMILY,
              fontWeight: 500,
              borderRadius: 6,
              whiteSpace: 'nowrap',
              zIndex: 11,
              boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
            }}
          >
            <span
              style={{
                position: 'absolute',
                bottom: '100%',
                left: '50%',
                marginLeft: -6,
                width: 0,
                height: 0,
                border: '6px solid transparent',
                borderBottomColor: '#2d2d2d',
              }}
            />
            {tooltipLabel}
          </div>
        )}
        {dropdownOpen && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: 4,
              minWidth: 160,
              background: '#fff',
              border: '1px solid #e0e0e0',
              borderRadius: 6,
              boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
              zIndex: 10,
              overflow: 'hidden',
            }}
          >
            {DAYS_OPTIONS.map(({ id, label }) => (
              <div
                key={id}
                role="button"
                tabIndex={0}
                onClick={() => setView(id)}
                onKeyDown={(e) => e.key === 'Enter' && setView(id)}
                onMouseEnter={() => setHoveredOption(id)}
                onMouseLeave={() => setHoveredOption((current) => (current === id ? null : current))}
                style={{
                  padding: '8px 12px',
                  fontSize: 13,
                  fontFamily: FONT_FAMILY,
                  background: displayedView === id ? '#e8e8e8' : hoveredOption === id ? '#f0f0f0' : 'transparent',
                  color: '#333',
                  cursor: 'pointer',
                }}
              >
                {label}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
};

export default TimeframeSelector;
