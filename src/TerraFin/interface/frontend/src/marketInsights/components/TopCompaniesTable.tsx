import React from 'react';

interface Company {
  rank: number;
  ticker: string;
  name: string;
  marketCap: string;
  country: string;
}

interface TopCompaniesTableProps {
  companies: Company[];
  height?: number;
}

const TH = { borderBottom: '1px solid var(--tf-border)', padding: '10px 8px', color: 'var(--tf-muted)', fontWeight: 700 as const, fontSize: "var(--tf-fs-xs)", textTransform: 'uppercase' as const, letterSpacing: '0.06em' };
const TD = { borderBottom: '1px solid var(--tf-border)', padding: '10px 8px', fontSize: "var(--tf-fs-base)" };

const SHORT_COUNTRY: Record<string, string> = {
  'United States': 'US',
  'United Kingdom': 'UK',
  'South Korea': 'KR',
  'Netherlands': 'NL',
  'Switzerland': 'CH',
  'Germany': 'DE',
  'France': 'FR',
  'Japan': 'JP',
  'Canada': 'CA',
  'China': 'CN',
  'Taiwan': 'TW',
  'Ireland': 'IE',
  'Israel': 'IL',
  'Denmark': 'DK',
  'Australia': 'AU',
  'Brazil': 'BR',
  'India': 'IN',
  'Argentina': 'AR',
};

const TopCompaniesTable: React.FC<TopCompaniesTableProps> = ({ companies, height }) => (
  <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', ...(height != null ? { height, maxHeight: height } : {}) }}>
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <th style={{ ...TH, textAlign: 'left', width: 30 }}>#</th>
          <th style={{ ...TH, textAlign: 'left', width: 70 }}>Ticker</th>
          <th style={{ ...TH, textAlign: 'left' }}>Company</th>
          <th style={{ ...TH, textAlign: 'right', whiteSpace: 'nowrap', width: 100 }}>Market Cap</th>
          <th style={{ ...TH, textAlign: 'right', width: 55 }}>Country</th>
        </tr>
      </thead>
      <tbody>
        {companies.map((c) => (
          <tr
            key={c.ticker}
            onClick={() => { window.location.href = `/stock/${encodeURIComponent(c.ticker)}`; }}
            style={{ cursor: 'pointer' }}
            title={`Open ${c.ticker}`}
          >
            <td style={{ ...TD, color: 'var(--tf-muted)' }}>{c.rank}</td>
            <td style={TD}>
              <a
                href={`/stock/${encodeURIComponent(c.ticker)}`}
                onClick={(e) => e.stopPropagation()}
                style={{ color: 'var(--tf-amber)', fontWeight: 600, textDecoration: 'none' }}
              >
                {c.ticker}
              </a>
            </td>
            <td style={{ ...TD, color: 'var(--tf-text)' }}>{c.name}</td>
            <td style={{ ...TD, textAlign: 'right', color: 'var(--tf-text-strong)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{c.marketCap}</td>
            <td style={{ ...TD, textAlign: 'right', color: 'var(--tf-muted)' }}>{SHORT_COUNTRY[c.country] || c.country}</td>
          </tr>
        ))}
      </tbody>
    </table>
    {companies.length === 0 && (
      <div style={{ padding: 24, textAlign: 'center', color: 'var(--tf-muted)', fontSize: "var(--tf-fs-base)" }}>No data available</div>
    )}
  </div>
);

export default TopCompaniesTable;
