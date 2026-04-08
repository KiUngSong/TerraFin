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

const TH = { borderBottom: '1px solid #e2e8f0', padding: '10px 8px', color: '#64748b', fontWeight: 600 as const, fontSize: 13 };
const TD = { borderBottom: '1px solid #f1f5f9', padding: '10px 8px', fontSize: 14 };

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
          <tr key={c.ticker}>
            <td style={{ ...TD, color: '#94a3b8' }}>{c.rank}</td>
            <td style={{ ...TD, color: '#0f172a', fontWeight: 600 }}>{c.ticker}</td>
            <td style={{ ...TD, color: '#334155' }}>{c.name}</td>
            <td style={{ ...TD, textAlign: 'right', color: '#0f172a', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{c.marketCap}</td>
            <td style={{ ...TD, textAlign: 'right', color: '#64748b' }}>{SHORT_COUNTRY[c.country] || c.country}</td>
          </tr>
        ))}
      </tbody>
    </table>
    {companies.length === 0 && (
      <div style={{ padding: 24, textAlign: 'center', color: '#94a3b8', fontSize: 14 }}>No data available</div>
    )}
  </div>
);

export default TopCompaniesTable;
