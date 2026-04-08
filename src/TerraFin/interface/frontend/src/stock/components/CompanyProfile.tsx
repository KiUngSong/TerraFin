import React from 'react';
import { useViewportTier } from '../../shared/responsive';
import type { CompanyInfo } from '../useStockData';

const CompanyProfile: React.FC<{ info: CompanyInfo }> = ({ info }) => {
  const { isMobile, isTablet } = useViewportTier();
  const metrics: { label: string; value: string }[] = [
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
    },
    { label: 'Country', value: info.country || '-' },
  ];

  const gridTemplateColumns = isMobile
    ? '1fr'
    : isTablet
      ? 'repeat(3, minmax(0, 1fr))'
      : 'repeat(auto-fit, minmax(136px, 1fr))';

  const metricCardPadding = isMobile ? '12px 13px' : '10px 12px';
  const valueFontSize = isMobile ? 16 : 15;

  return (
    <div style={{ display: 'grid', gridTemplateColumns, gap: 10, minWidth: 0 }}>
      {metrics.map((m) => (
        <div
          key={m.label}
          style={{ ...metricCardStyle, padding: metricCardPadding }}
        >
          <div style={{ fontSize: 11, color: '#64748b', fontWeight: 700, marginBottom: 6, letterSpacing: '0.02em' }}>{m.label}</div>
          <div
            style={{
              fontSize: valueFontSize,
              fontWeight: 800,
              color: '#0f172a',
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
          <div style={{ fontSize: 11, color: '#64748b', fontWeight: 700, marginBottom: 6, letterSpacing: '0.02em' }}>Website</div>
          <a
            href={info.website}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontSize: isMobile ? 13 : 12,
              color: '#1d4ed8',
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
  border: '1px solid #dbe4ef',
  borderRadius: 12,
  padding: '12px 13px',
  background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
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
