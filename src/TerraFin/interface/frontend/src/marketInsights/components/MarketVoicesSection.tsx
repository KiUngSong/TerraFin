import React, { useEffect, useMemo, useState } from 'react';

import InsightCard from '../../terminal/components/InsightCard';

interface MarketVoiceEntry {
  slug: string;
  name: string;
  as_of: string;
  age_days: number;
  stance: 'bullish' | 'bearish' | 'neutral' | string;
  thesis: string;
  source_url?: string;
}

interface MarketVoicesSummary {
  bull: number;
  bear: number;
  neutral: number;
  stale: number;
  reporting: number;
}

const stanceColor = (stance: string): string =>
  stance === 'bullish' ? 'var(--tf-up)' : stance === 'bearish' ? 'var(--tf-down)' : 'var(--tf-amber)';

const agoLabel = (age: number): string => (age <= 0 ? 'today' : `${age}d ago`);

// "2026-07-15" -> "Jul 15". Force LOCAL parse: `new Date("2026-07-15")` is UTC
// midnight, which renders as the previous day for sub-UTC (US) viewers — a
// fresh card would read "Jul 14 · today". Appending a time makes it local.
const shortDate = (iso: string): string => {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const MarketVoicesSection: React.FC = () => {
  const [views, setViews] = useState<MarketVoiceEntry[]>([]);
  const [summary, setSummary] = useState<MarketVoicesSummary | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    fetch('/market-insights/api/market-voices')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: { views: MarketVoiceEntry[]; summary: MarketVoicesSummary }) => {
        setViews(d.views || []);
        setSummary(d.summary || null);
      })
      .catch(() => setViews([]));
  }, []);

  const counted = useMemo(() => (summary ? summary.bull + summary.neutral + summary.bear : 0), [summary]);

  // Read-if-present: no data (or endpoint down) -> the section simply doesn't exist.
  if (views.length === 0) return null;

  return (
    <InsightCard
      title="Market Voices"
      subtitle="Each strategist's latest market read, in their own words — dated, no forecasts implied."
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {summary && (
          <div style={consensusStyle}>
            {counted > 0 && (
              <span style={distBarStyle} role="img" aria-label={`${summary.bull} bullish, ${summary.neutral} neutral, ${summary.bear} bearish`}>
                <span style={{ width: `${(summary.bull / counted) * 100}%`, background: 'var(--tf-up)' }} />
                <span style={{ width: `${(summary.neutral / counted) * 100}%`, background: 'var(--tf-amber)' }} />
                <span style={{ width: `${(summary.bear / counted) * 100}%`, background: 'var(--tf-down)' }} />
              </span>
            )}
            <span style={{ color: 'var(--tf-up)' }}>{summary.bull} bull</span>
            <span style={{ color: 'var(--tf-amber)' }}>{summary.neutral} neutral</span>
            <span style={{ color: 'var(--tf-down)' }}>{summary.bear} bear</span>
            <span style={{ color: 'var(--tf-muted)' }}>
              · {summary.reporting} reporting{summary.stale > 0 ? ` · ${summary.stale} dated` : ''}
            </span>
          </div>
        )}

        {/* Bounded, scrollable list — the section never balloons the page. */}
        <div style={listStyle}>
          {views.map((v) => {
            const open = expanded === v.slug;
            return (
              <div key={v.slug} style={rowStyle} onClick={() => setExpanded(open ? null : v.slug)}>
                <div style={rowHeadStyle}>
                  <span style={{ ...stanceDotStyle, background: stanceColor(v.stance) }} />
                  <span style={nameStyle}>{v.name}</span>
                  <span style={{ ...stanceTextStyle, color: stanceColor(v.stance) }}>{v.stance}</span>
                  <span style={{ flex: 1 }} />
                  <span style={dateStyle}>
                    {shortDate(v.as_of)} · {agoLabel(v.age_days)}
                  </span>
                </div>
                <div style={open ? thesisOpenStyle : thesisStyle}>{v.thesis}</div>
                {open && v.source_url && (
                  <a
                    href={v.source_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    style={sourceStyle}
                  >
                    source ↗
                  </a>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </InsightCard>
  );
};

const consensusStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  flexWrap: 'wrap',
  fontFamily: 'var(--tf-mono)',
  fontSize: 'var(--tf-fs-xs)',
  fontWeight: 700,
  fontVariantNumeric: 'tabular-nums',
};

const distBarStyle: React.CSSProperties = {
  display: 'inline-flex',
  width: 120,
  height: 8,
  borderRadius: 4,
  overflow: 'hidden',
  border: '1px solid var(--tf-border)',
  background: 'var(--tf-bg-hover)',
};

const listStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  maxHeight: 320,
  overflowY: 'auto',
  border: '1px solid var(--tf-border)',
  borderRadius: 'var(--tf-radius-panel)',
};

const rowStyle: React.CSSProperties = {
  padding: '9px 12px',
  borderBottom: '1px solid var(--tf-border)',
  cursor: 'pointer',
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
};

const rowHeadStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 };
const stanceDotStyle: React.CSSProperties = { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 };
const nameStyle: React.CSSProperties = {
  fontWeight: 600,
  color: 'var(--tf-text-strong)',
  fontSize: 'var(--tf-fs-base)',
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
};
const stanceTextStyle: React.CSSProperties = {
  fontFamily: 'var(--tf-mono)',
  fontSize: 'var(--tf-fs-micro)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  flexShrink: 0,
};
const dateStyle: React.CSSProperties = {
  fontFamily: 'var(--tf-mono)',
  fontSize: 'var(--tf-fs-micro)',
  color: 'var(--tf-muted)',
  whiteSpace: 'nowrap',
  fontVariantNumeric: 'tabular-nums',
};

const thesisStyle: React.CSSProperties = {
  fontSize: 'var(--tf-fs-xs)',
  color: 'var(--tf-text)',
  lineHeight: 1.45,
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
};
const thesisOpenStyle: React.CSSProperties = { fontSize: 'var(--tf-fs-xs)', color: 'var(--tf-text)', lineHeight: 1.5 };
const sourceStyle: React.CSSProperties = {
  fontFamily: 'var(--tf-mono)',
  fontSize: 'var(--tf-fs-micro)',
  color: 'var(--tf-muted)',
  textDecoration: 'none',
  alignSelf: 'flex-start',
};

export default MarketVoicesSection;
