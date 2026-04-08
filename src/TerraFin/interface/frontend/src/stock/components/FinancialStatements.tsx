import React, { useState } from 'react';
import { useFinancials } from '../useStockData';

const TABS = [
  { key: 'income', label: 'Income Statement' },
  { key: 'balance', label: 'Balance Sheet' },
  { key: 'cashflow', label: 'Cash Flow' },
] as const;

const PERIODS = [
  { key: 'annual', label: 'Annual' },
  { key: 'quarter', label: 'Quarterly' },
] as const;

const FinancialStatements: React.FC<{ ticker: string; enabled?: boolean }> = ({ ticker, enabled = true }) => {
  const [tab, setTab] = useState<string>('income');
  const [period, setPeriod] = useState<string>('annual');
  const { data, loading, error } = useFinancials(ticker, tab, period, enabled);

  if (!enabled) {
    return <div style={{ fontSize: 13, color: '#475569' }}>Waiting for chart to finish loading...</div>;
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              style={tabStyle(tab === t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ width: 1, height: 20, background: '#e2e8f0', margin: '0 6px' }} />
        <div style={{ display: 'flex', gap: 4 }}>
          {PERIODS.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => setPeriod(p.key)}
              style={tabStyle(period === p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <div style={{ fontSize: 13, color: '#475569' }}>Loading financials...</div>}
      {error && <div style={{ fontSize: 13, color: '#b91c1c' }}>Failed to load: {error}</div>}

      {data && data.rows.length > 0 && (
        <div style={{ overflowX: 'auto', maxHeight: 480, border: '1px solid #e2e8f0', borderRadius: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, background: '#fff' }}>
            <thead>
              <tr>
                <th style={thStyle}>Item</th>
                {data.columns.map((col) => (
                  <th key={col} style={{ ...thStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {col.slice(0, 10)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, i) => (
                <tr key={i}>
                  <td style={{ ...cellStyle, fontWeight: 500, color: '#0f172a', whiteSpace: 'nowrap' }}>
                    {formatLabel(row.label)}
                  </td>
                  {data.columns.map((col) => (
                    <td key={col} style={{ ...cellStyle, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                      {formatValue(row.values[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.rows.length === 0 && !loading && (
        <div style={{ fontSize: 13, color: '#64748b' }}>No financial data available.</div>
      )}
    </div>
  );
};

const thStyle: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: 11,
  fontWeight: 600,
  color: '#64748b',
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
  borderBottom: '2px solid #e2e8f0',
  background: '#f8fafc',
  position: 'sticky',
  top: 0,
  textAlign: 'left',
};

const cellStyle: React.CSSProperties = {
  padding: '5px 8px',
  borderBottom: '1px solid #f1f5f9',
  fontSize: 12,
};

function tabStyle(active: boolean): React.CSSProperties {
  return {
    border: '1px solid ' + (active ? '#93c5fd' : '#cbd5e1'),
    borderRadius: 999,
    padding: '4px 12px',
    fontSize: 11,
    fontWeight: 600,
    background: active ? '#dbeafe' : '#f8fafc',
    color: active ? '#1e3a8a' : '#334155',
    cursor: 'pointer',
  };
}

function formatLabel(label: string): string {
  // Convert camelCase to Title Case
  return label
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, (s) => s.toUpperCase())
    .trim();
}

function formatValue(val: string | number | null | undefined): string {
  if (val == null || val === '' || val === 'None') return '-';
  const num = typeof val === 'number' ? val : parseFloat(String(val));
  if (isNaN(num)) return String(val);
  if (Math.abs(num) >= 1e9) return (num / 1e9).toFixed(2) + 'B';
  if (Math.abs(num) >= 1e6) return (num / 1e6).toFixed(1) + 'M';
  if (Math.abs(num) >= 1e3) return num.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return num.toFixed(2);
}

export default FinancialStatements;
