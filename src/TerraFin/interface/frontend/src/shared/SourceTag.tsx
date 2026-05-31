import React from 'react';

/**
 * Source + timestamp inline tag. Renders as `[yf · 14:23 KST]`.
 *
 * This is the Bloomberg-DNA substance bar that says: every datum carries
 * its own provenance + freshness, inline with the cell, not in a tooltip.
 *
 * `at` accepts a `Date` or an ISO string or epoch-ms number. Falls back
 * to `Date.now()` so consumers can drop it in before plumbing meta is
 * threaded through every widget — leave a TODO comment when you use the
 * fallback so Phase 4 can sweep them out widget-by-widget.
 */

export type SourceSlug =
  | 'yf'
  | 'poly'
  | 'fred'
  | 'cboe'
  | 'cnn'
  | 'sec'
  | 'calc'
  | 'ai';

interface SourceTagProps {
  source: SourceSlug;
  at?: Date | string | number;
  /**
   * Override the timezone abbreviation suffix. Defaults to `KST` because
   * the engineer reads markets from Seoul; widgets dealing in US-market
   * close timestamps may want `ET`.
   */
  tz?: string;
  className?: string;
}

function toDate(at?: Date | string | number): Date {
  if (at == null) return new Date();
  if (at instanceof Date) return at;
  if (typeof at === 'number') return new Date(at);
  // ISO or RFC string
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? new Date() : d;
}

function formatTime(at: Date, tz?: string): string {
  // Render the time IN the labeled zone (default Asia/Seoul / KST). Previously
  // used local getHours() but printed "KST" — wrong by the UTC offset on any
  // non-Seoul machine. en-US + explicit timeZone keeps label and value honest.
  const suffix = tz ?? 'KST';
  const ianaTz = tz ? undefined : 'Asia/Seoul';
  const hhmm = at.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    ...(ianaTz ? { timeZone: ianaTz } : {}),
  });
  return `${hhmm} ${suffix}`;
}

const SourceTag: React.FC<SourceTagProps> = ({
  source,
  at,
  tz,
  className = '',
}) => {
  const ts = formatTime(toDate(at), tz);
  return (
    <span className={['tf-src', className].filter(Boolean).join(' ')}>
      <span className="tf-src__src">{source}</span>
      <span className="tf-src__dot">·</span>
      <span className="tf-src__ts">{ts}</span>
    </span>
  );
};

export default SourceTag;
