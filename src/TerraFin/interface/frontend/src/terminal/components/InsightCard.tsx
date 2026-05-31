import React from 'react';
import TerminalPane from './TerminalPane';

/**
 * Temporary shim — keeps the old `InsightCard` import path working while
 * widgets are migrated to `TerminalPane` directly. Deleted in Phase 6.
 *
 * Prop surface mirrors the original `InsightCard`. Subtitle text flows
 * into TerminalPane's subtitle slot.
 */

interface InsightCardProps {
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
  minHeight?: number;
  fillContent?: boolean;
  href?: string;
  allowOverflow?: boolean;
  className?: string;
  contentClassName?: string;
}

const InsightCard: React.FC<InsightCardProps> = (props) => {
  return <TerminalPane {...props} />;
};

export default InsightCard;
