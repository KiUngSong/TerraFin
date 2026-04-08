import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { FONT_FAMILY } from '../constants';

const MAX_SELECTED = 5;
const INFO_TOOLTIP_WIDTH = 280;
const INFO_TOOLTIP_GAP = 12;
const INFO_TOOLTIP_EDGE_PADDING = 12;

const INDICATOR_META: Record<string, { label: string; order: number; helpText?: string }> = {
  'ma-20': { label: 'MA 20', order: 0 },
  'ma-60': { label: 'MA 60', order: 1 },
  'ma-120': { label: 'MA 120', order: 2 },
  'ma-200': { label: 'MA 200', order: 3 },
  bb: { label: 'Bollinger', order: 4 },
  rsi: { label: 'RSI', order: 5 },
  macd: { label: 'MACD', order: 6 },
  'realized-vol': { label: 'Realized Vol', order: 7 },
  'range-vol': { label: 'Range Vol', order: 8 },
  'trend-signal': { label: 'Trend Signal', order: 9 },
  mfd: {
    label: 'MFD',
    order: 10,
    helpText:
      'Mandelbrot Fractal Dimension measures how fragile or anti-fragile the recent price path is. Lower values mean a smoother, one-sided move and more fragility. Higher values mean a choppier, two-way path and more anti-fragility. The chart uses 1.0, 1.5, and 2.0 as reference levels, and shows the 130-day view by default.',
  },
};

export function getIndicatorLabel(group: string): string {
  return INDICATOR_META[group]?.label ?? group;
}

export interface IndicatorOption {
  group: string;
  color: string;
}

interface IndicatorSelectorProps {
  options: IndicatorOption[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  dropUp?: boolean;
}

const IndicatorSelector: React.FC<IndicatorSelectorProps> = ({ options, selected, onChange, dropUp = false }) => {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const infoButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const infoTooltipRef = useRef<HTMLDivElement>(null);
  const [menuPos, setMenuPos] = useState<{ top?: number; bottom?: number; right: number }>({ right: 0 });
  const [localSelected, setLocalSelected] = useState<Set<string>>(new Set(selected));
  const [infoTarget, setInfoTarget] = useState<string | null>(null);
  const [infoTooltipPos, setInfoTooltipPos] = useState<{ top: number; left: number; placement: 'left' | 'right' } | null>(null);
  const selectedSignature = Array.from(selected).sort().join(',');

  useEffect(() => {
    setLocalSelected(new Set(selected));
  }, [selectedSignature]);

  useEffect(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    if (dropUp) {
      setMenuPos({ bottom: window.innerHeight - rect.top + 4, right: window.innerWidth - rect.right });
    } else {
      setMenuPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
    }
  }, [open, dropUp]);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      const insideWrapper = wrapperRef.current?.contains(target) ?? false;
      const insideMenu = menuRef.current?.contains(target) ?? false;
      if (!insideWrapper && !insideMenu) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleViewportChange = () => {
      setOpen(false);
      setInfoTarget(null);
    };
    window.addEventListener('scroll', handleViewportChange, true);
    window.addEventListener('resize', handleViewportChange);
    return () => {
      window.removeEventListener('scroll', handleViewportChange, true);
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setInfoTarget(null);
      setInfoTooltipPos(null);
    }
  }, [open]);

  const sorted = [...options].sort(
    (a, b) => (INDICATOR_META[a.group]?.order ?? 99) - (INDICATOR_META[b.group]?.order ?? 99)
  );
  const buttonLabel = 'Technical Indicator';

  const toggle = (group: string) => {
    const next = new Set(Array.from(localSelected));
    if (next.has(group)) {
      next.delete(group);
    } else if (next.size < MAX_SELECTED) {
      next.add(group);
    }
    setLocalSelected(next);
    onChange(next);
  };

  const computeInfoTooltipPosition = (group: string) => {
    const infoButton = infoButtonRefs.current[group];
    if (!infoButton) return null;

    const rect = infoButton.getBoundingClientRect();
    const canOpenRight =
      rect.right + INFO_TOOLTIP_GAP + INFO_TOOLTIP_WIDTH + INFO_TOOLTIP_EDGE_PADDING <= window.innerWidth;
    const placement: 'left' | 'right' = canOpenRight ? 'right' : 'left';
    const left =
      placement === 'right'
        ? Math.min(rect.right + INFO_TOOLTIP_GAP, window.innerWidth - INFO_TOOLTIP_WIDTH - INFO_TOOLTIP_EDGE_PADDING)
        : Math.max(INFO_TOOLTIP_EDGE_PADDING, rect.left - INFO_TOOLTIP_WIDTH - INFO_TOOLTIP_GAP);

    return {
      top: rect.top + rect.height / 2,
      left,
      placement,
    };
  };

  useLayoutEffect(() => {
    if (!open || !infoTarget) {
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
  }, [infoTarget, menuPos.bottom, menuPos.right, menuPos.top, open]);

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
    <div ref={wrapperRef} style={{ position: 'relative' }}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          fontFamily: FONT_FAMILY,
          padding: '5px 10px',
          minHeight: 28,
          maxWidth: '100%',
          minWidth: 0,
          fontSize: 12,
          fontWeight: 500,
          border: '1px solid #e0e0e0',
          borderRadius: 6,
          background: open ? '#e8e8e8' : '#fff',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          color: '#333',
          lineHeight: 1,
          whiteSpace: 'nowrap',
          flexShrink: 1,
        }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
        <span
          style={{
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {buttonLabel}
        </span>
        {localSelected.size > 0 && (
          <span
            style={{
              background: '#1976d2',
              color: '#fff',
              borderRadius: 8,
              padding: '1px 6px',
              fontSize: 10,
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            {localSelected.size}
          </span>
        )}
      </button>

      {open && createPortal(
        <div
          ref={menuRef}
          style={{
            position: 'fixed',
            top: menuPos.top,
            bottom: menuPos.bottom,
            right: menuPos.right,
            background: '#fff',
            border: '1px solid #e0e0e0',
            borderRadius: 8,
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            zIndex: 10000,
            minWidth: 180,
            padding: '6px 0',
            fontFamily: FONT_FAMILY,
          }}
        >
          {sorted.map((opt) => {
            const checked = localSelected.has(opt.group);
            const disabled = !checked && localSelected.size >= MAX_SELECTED;
            const label = getIndicatorLabel(opt.group);
            const helpText = INDICATOR_META[opt.group]?.helpText;
            const infoVisible = infoTarget === opt.group;
            return (
              <div
                key={opt.group}
                style={{
                  position: 'relative',
                  width: '100%',
                }}
              >
                <div
                  role="button"
                  tabIndex={disabled ? -1 : 0}
                  aria-pressed={checked}
                  aria-disabled={disabled}
                  onClick={() => !disabled && toggle(opt.group)}
                  onKeyDown={(e) => {
                    if (disabled) return;
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      toggle(opt.group);
                    }
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    width: '100%',
                    padding: '7px 14px',
                    border: 'none',
                    boxSizing: 'border-box',
                    background: 'transparent',
                    cursor: disabled ? 'default' : 'pointer',
                    opacity: disabled ? 0.4 : 1,
                    fontFamily: FONT_FAMILY,
                    fontSize: 13,
                    color: '#333',
                    textAlign: 'left',
                  }}
                  onMouseEnter={(e) => {
                    if (!disabled) e.currentTarget.style.background = '#f5f5f5';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <span
                    style={{
                      width: 16,
                      height: 16,
                      borderRadius: 3,
                      border: checked ? 'none' : '2px solid #ccc',
                      background: checked ? opt.color : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    {checked && (
                      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#fff" strokeWidth="2">
                        <polyline points="2 6 5 9 10 3" />
                      </svg>
                    )}
                  </span>
                  <span
                    style={{
                      width: 10,
                      height: 3,
                      borderRadius: 1,
                      background: opt.color,
                      flexShrink: 0,
                    }}
                  />
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
                    <span>{label}</span>
                    {helpText && (
                      <button
                        ref={(node) => {
                          infoButtonRefs.current[opt.group] = node;
                        }}
                        type="button"
                        aria-label={`${label} explanation`}
                        aria-expanded={infoVisible}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          setInfoTarget((current) => (current === opt.group ? null : opt.group));
                        }}
                        onMouseEnter={() => setInfoTarget(opt.group)}
                        onMouseLeave={() => setInfoTarget((current) => (current === opt.group ? null : current))}
                        onFocus={() => setInfoTarget(opt.group)}
                        onBlur={() => setInfoTarget((current) => (current === opt.group ? null : current))}
                        style={{
                          width: 18,
                          height: 18,
                          borderRadius: 999,
                          border: '1px solid #cbd5e1',
                          background: infoVisible ? '#1976d2' : '#fff',
                          color: infoVisible ? '#fff' : '#5f6b7a',
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
                  {helpText && infoVisible && infoTooltipPos && createPortal(
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
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>Mandelbrot Fractal Dimension</div>
                      <div>{helpText}</div>
                    </div>,
                    document.body,
                  )}
                </div>
              </div>
            );
          })}
          {localSelected.size >= MAX_SELECTED && (
            <div style={{ padding: '4px 14px', fontSize: 11, color: '#999' }}>Max {MAX_SELECTED} selected</div>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
};

export default IndicatorSelector;
