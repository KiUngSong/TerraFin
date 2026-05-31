import React from 'react';
import { useViewportTier } from '../../shared/responsive';
import type { CompanyInfo } from '../useStockData';

const CompanyProfile: React.FC<{ info: CompanyInfo }> = ({ info }) => {
  const { isMobile } = useViewportTier();
  const metrics: { label: string; value: string; span?: number }[] = [
    { label: 'Market Cap', value: formatMarketCap(info.marketCap) },
    { label: 'P/E (Trailing)', value: fmt(info.trailingPE) },
    { label: 'P/E (Forward)', value: fmt(info.forwardPE) },
    { label: 'EPS (Trailing)', value: fmt(info.trailingEps, '$') },
    { label: 'EPS (Forward)', value: fmt(info.forwardEps, '$') },
    {
      label: 'Dividend Yield',
      value: info.dividendYield != null ? (info.dividendYield * 100).toFixed(2) + '%' : '-',
    },
    {
      label: '52-Week Range',
      value:
        info.fiftyTwoWeekLow != null && info.fiftyTwoWeekHigh != null
          ? `$${info.fiftyTwoWeekLow.toFixed(2)} – $${info.fiftyTwoWeekHigh.toFixed(2)}`
          : '-',
      span: 2,
    },
    { label: 'Country', value: info.country || '-' },
  ];

  const gridTemplateColumns = isMobile
    ? '1fr'
    : 'repeat(3, minmax(0, 1fr))';

  const metricCardPadding = isMobile ? '12px 13px' : '12px';
  const valueFontSize = 'var(--tf-fs-base)';

  return (
    <div style={{ display: 'grid', gridTemplateColumns, gap: 10, minWidth: 0 }}>
      {metrics.map((m) => (
        <div
          key={m.label}
          style={{
            ...metricCardStyle,
            padding: metricCardPadding,
            gridColumn: !isMobile && m.span ? `span ${m.span}` : undefined,
          }}
        >
          <div style={{ fontSize: 'var(--tf-fs-xs)', color: 'var(--tf-muted)', fontWeight: 600, marginBottom: 6, letterSpacing: '0.04em' }}>{m.label}</div>
          <div
            style={{
              fontSize: valueFontSize,
              fontWeight: 700,
              color: 'var(--tf-text-strong)',
              lineHeight: 1.25,
              overflowWrap: 'anywhere',
              wordBreak: 'break-word',
            }}
          >
            {m.value}
          </div>
        </div>
      ))}
      {info.website && (
        <div
          style={{
            ...metricCardStyle,
            padding: metricCardPadding,
            gridColumn: isMobile ? 'auto' : '1 / -1',
          }}
        >
          <div style={{ fontSize: 'var(--tf-fs-xs)', color: 'var(--tf-muted)', fontWeight: 600, marginBottom: 6, letterSpacing: '0.04em' }}>Website</div>
          <a
            href={info.website}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontSize: 'var(--tf-fs-base)',
              color: 'var(--tf-amber)',
              textDecoration: 'none',
              fontWeight: 700,
              overflowWrap: 'anywhere',
              wordBreak: 'break-word',
            }}
          >
            {info.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
          </a>
        </div>
      )}
    </div>
  );
};

const metricCardStyle: React.CSSProperties = {
  border: '1px solid var(--tf-border)',
  borderRadius: 'var(--tf-radius)',
  padding: '12px',
  background: 'var(--tf-bg-elevated)',
  minWidth: 0,
};

function formatMarketCap(val: number | null): string {
  if (val == null) return '-';
  if (val >= 1e12) return `$${(val / 1e12).toFixed(2)}T`;
  if (val >= 1e9) return `$${(val / 1e9).toFixed(2)}B`;
  if (val >= 1e6) return `$${(val / 1e6).toFixed(1)}M`;
  return `$${val.toLocaleString()}`;
}

function fmt(val: number | null, prefix = ''): string {
  if (val == null) return '-';
  return `${prefix}${val.toFixed(2)}`;
}

export default CompanyProfile;
