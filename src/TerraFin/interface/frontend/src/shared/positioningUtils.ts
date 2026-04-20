// Viewport-relative positioning helpers for floating UI (dropdowns, tooltips,
// panels). All functions read `window.innerWidth` / `window.innerHeight` —
// they are the right choice for `position: fixed` overlays that should stay
// within the viewport, not within their parent container.
//
// These helpers replace copies of the same clamp/flip math that were
// duplicated across RiskAnalyticsPanel, IndicatorSelector, TimeframeSelector,
// SearchInput, and InfoHint. Keep positioning logic here so a future viewport
// quirk can be fixed in one place.

export interface RectLike {
  top: number;
  bottom: number;
  left: number;
  right: number;
  width: number;
  height: number;
}

/**
 * Place a dropdown directly below an anchor with its right edge aligned to the
 * anchor's right edge. Right-anchored by design so the menu can't push past
 * the viewport right edge — the minimum margin (`edgeMargin`) prevents a
 * wide-right anchor from forcing right:0.
 */
export function dropdownBelowAnchorRight(
  anchorRect: RectLike,
  gap = 4,
  edgeMargin = 8,
): { top: number; right: number } {
  return {
    top: Math.round(anchorRect.bottom) + gap,
    right: Math.max(edgeMargin, Math.round(window.innerWidth - anchorRect.right)),
  };
}

/**
 * Place a dropdown directly below an anchor with its left edge aligned to the
 * anchor's left edge, clamped to the viewport. Used when the menu should hang
 * from the left (wider than the anchor, compact-mode icon triggers, etc.).
 */
export function dropdownBelowAnchorLeft(
  anchorRect: RectLike,
  menuWidth: number,
  gap = 6,
  edgeMargin = 12,
): { top: number; left: number } {
  const clampedLeft = Math.min(
    Math.max(edgeMargin, anchorRect.left),
    Math.max(edgeMargin, window.innerWidth - menuWidth - edgeMargin),
  );
  return {
    top: anchorRect.bottom + gap,
    left: clampedLeft,
  };
}

/**
 * Place a side-tooltip to the right of an anchor if it fits; otherwise flip to
 * the left. Vertically centered on the anchor. Horizontal coordinate is
 * clamped to the viewport's edge margin.
 */
export function flipSideTooltip(
  anchorRect: RectLike,
  tooltipWidth: number,
  gap: number,
  edgeMargin: number,
): { top: number; left: number; placement: 'left' | 'right' } {
  const canOpenRight =
    anchorRect.right + gap + tooltipWidth + edgeMargin <= window.innerWidth;
  const placement: 'left' | 'right' = canOpenRight ? 'right' : 'left';
  const left =
    placement === 'right'
      ? Math.min(anchorRect.right + gap, window.innerWidth - tooltipWidth - edgeMargin)
      : Math.max(edgeMargin, anchorRect.left - tooltipWidth - gap);
  return {
    top: anchorRect.top + anchorRect.height / 2,
    left,
    placement,
  };
}

/**
 * Place a panel below an anchor, flipping above if it would overflow the
 * viewport bottom. Horizontal alignment is configurable (`align`) and the
 * resulting `left` is clamped to the viewport. Used by hover-info panels.
 */
export function placeBelowOrAbove(
  anchorRect: RectLike,
  panelWidth: number,
  panelHeight: number,
  options: { gap?: number; edgeMargin?: number; align?: 'left' | 'right' } = {},
): { top: number; left: number } {
  const { gap = 8, edgeMargin = 12, align = 'right' } = options;
  let left = align === 'left' ? anchorRect.left : anchorRect.right - panelWidth;
  left = Math.min(left, window.innerWidth - panelWidth - edgeMargin);
  left = Math.max(edgeMargin, left);

  let top = anchorRect.bottom + gap;
  if (panelHeight > 0 && top + panelHeight > window.innerHeight - edgeMargin) {
    top = Math.max(edgeMargin, anchorRect.top - panelHeight - gap);
  }
  return { top, left };
}
