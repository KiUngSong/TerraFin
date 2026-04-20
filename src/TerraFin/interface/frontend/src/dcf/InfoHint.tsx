import React from 'react';
import { createPortal } from 'react-dom';

const VIEWPORT_MARGIN = 12;
const PANEL_GAP = 8;
const UI_FONT_STACK = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

// Visibility gate. When a parent provides `false`, the icon is hidden entirely.
// Default `true` keeps existing usage outside the gated subtree unchanged.
export const InfoHintVisibilityContext = React.createContext<boolean>(true);

const InfoHint: React.FC<{ text: string; compact?: boolean }> = ({ text, compact = false }) => {
  const visible = React.useContext(InfoHintVisibilityContext);
  const buttonRef = React.useRef<HTMLButtonElement | null>(null);
  const panelRef = React.useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = React.useState(false);
  const [position, setPosition] = React.useState<{ top: number; left: number; width: number } | null>(null);
  const tooltipId = React.useId();

  const updatePosition = React.useCallback(() => {
    if (typeof window === 'undefined' || !buttonRef.current) {
      return;
    }

    const buttonRect = buttonRef.current.getBoundingClientRect();
    const width = compact ? 228 : 260;
    const panelHeight = panelRef.current?.offsetHeight ?? 0;

    let left = compact ? buttonRect.left : buttonRect.right - width;
    left = Math.min(left, window.innerWidth - width - VIEWPORT_MARGIN);
    left = Math.max(VIEWPORT_MARGIN, left);

    let top = buttonRect.bottom + PANEL_GAP;
    if (panelHeight > 0 && top + panelHeight > window.innerHeight - VIEWPORT_MARGIN) {
      top = Math.max(VIEWPORT_MARGIN, buttonRect.top - panelHeight - PANEL_GAP);
    }

    setPosition({ top, left, width });
  }, [compact]);

  React.useLayoutEffect(() => {
    if (!open) {
      return;
    }

    updatePosition();
    const handleViewportChange = () => updatePosition();
    window.addEventListener('resize', handleViewportChange);
    window.addEventListener('scroll', handleViewportChange, true);
    return () => {
      window.removeEventListener('resize', handleViewportChange);
      window.removeEventListener('scroll', handleViewportChange, true);
    };
  }, [open, updatePosition]);

  // Early return AFTER all hooks so the hook-call order is stable across
  // visibility toggles (Rules of Hooks). Hiding the icon entirely when the
  // form-level "Explain inputs" toggle is off.
  if (!visible) return null;

  return (
    <>
      <span style={wrapStyle}>
        <button
          ref={buttonRef}
          type="button"
          aria-label="Variable information"
          aria-describedby={open ? tooltipId : undefined}
          aria-expanded={open}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          style={compact ? compactButtonStyle : buttonStyle}
        >
          i
        </button>
      </span>
      {open && typeof document !== 'undefined'
        ? createPortal(
            <div
              id={tooltipId}
              ref={panelRef}
              role="tooltip"
              style={{
                ...panelStyle,
                width: position?.width ?? (compact ? 228 : 260),
                top: position?.top ?? 0,
                left: position?.left ?? VIEWPORT_MARGIN,
              }}
            >
              {text}
            </div>,
            document.body
          )
        : null}
    </>
  );
};

const wrapStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  flexShrink: 0,
};

const buttonStyle: React.CSSProperties = {
  width: 16,
  height: 16,
  borderRadius: '50%',
  border: '1px solid #93c5fd',
  background: '#eff6ff',
  color: '#1d4ed8',
  fontSize: 9,
  fontWeight: 800,
  lineHeight: 1,
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 0,
};

const compactButtonStyle: React.CSSProperties = {
  ...buttonStyle,
  width: 14,
  height: 14,
  fontSize: 8,
};

const panelStyle: React.CSSProperties = {
  position: 'fixed',
  zIndex: 1200,
  border: '1px solid #bfdbfe',
  borderRadius: 12,
  padding: '10px 12px',
  background: '#f8fbff',
  color: '#334155',
  fontSize: 12,
  fontFamily: UI_FONT_STACK,
  lineHeight: 1.55,
  boxShadow: '0 16px 28px rgba(15, 23, 42, 0.12)',
  pointerEvents: 'none',
};

export default InfoHint;
