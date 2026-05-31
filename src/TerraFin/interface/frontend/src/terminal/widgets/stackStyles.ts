import type React from 'react';

// Shared eyebrow label for stacked composite panes (MacroStack,
// SentimentCalendarStack) so each in-pane section reads as a labelled block.
export const EYEBROW_STYLE: React.CSSProperties = {
  fontSize: 'var(--tf-fs-xs)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  color: 'var(--tf-muted-strong)',
  padding: '8px 12px 2px',
};
