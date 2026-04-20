import React from 'react';
import type { EarningsRecord } from '../useStockData';

const cellBase: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: 12,
  borderBottom: '1px solid #e2e8f0',
};

const SurpriseCell: React.FC<{ value: string }> = ({ value }) => {
  if (!value || value === '-') {
    return <td style={{ ...cellBase, textAlign: 'right', color: '#94a3b8' }}>-</td>;
  }
  const num = parseFloat(value.replace(/[+%]/g, ''));
  const color = isNaN(num) ? '#334155' : num >= 0 ? '#047857' : '#b91c1c';
  return <td style={{ ...cellBase, color, fontWeight: 600, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{value}</td>;
};

const EarningsTable: React.FC<{ earnings: EarningsRecord[] }> = ({ earnings }) => {
  if (earnings.length === 0) {
    return <div style={{ fontSize: 13, color: '#64748b' }}>No earnings data available.</div>;
  }

  const thStyle: React.CSSProperties = {
    ...cellBase,
    color: '#64748b',
    fontWeight: 600,
    textAlign: 'left',
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    background: '#f8fafc',
    position: 'sticky',
    top: 0,
    zIndex: 1,
  };
  const tdRight: React.CSSProperties = { ...cellBase, textAlign: 'right', fontVariantNumeric: 'tabular-nums' };

  return (
    <div
      style={{
        overflowY: 'auto',
        flex: 1,
        minHeight: 0,
        maxWidth: '100%',
        border: '1px solid #e2e8f0',
        borderRadius: 12,
        background: '#fff',
      }}
    >
        <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff' }}>
          <thead>
            <tr>
              <th style={thStyle}>Date</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Estimate</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Reported</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Surprise</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>Surprise %</th>
            </tr>
          </thead>
          <tbody>
            {earnings.map((e, i) => (
              <tr key={i}>
                <td style={{ ...cellBase, color: '#334155' }}>{e.date}</td>
                <td style={tdRight}>{e.epsEstimate}</td>
                <td style={tdRight}>{e.epsReported}</td>
                <SurpriseCell value={e.surprise} />
                <SurpriseCell value={e.surprisePercent} />
              </tr>
            ))}
          </tbody>
        </table>
    </div>
  );
};

export default EarningsTable;
