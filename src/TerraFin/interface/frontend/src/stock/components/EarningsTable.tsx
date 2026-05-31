import React from 'react';
import type { EarningsRecord } from '../useStockData';

const cellBase: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: "var(--tf-fs-base)",
  borderBottom: '1px solid var(--tf-border)',
};

const SurpriseCell: React.FC<{ value: string }> = ({ value }) => {
  if (!value || value === '-') {
    return <td style={{ ...cellBase, textAlign: 'right', color: 'var(--tf-muted)' }}>-</td>;
  }
  const num = parseFloat(value.replace(/[+%]/g, ''));
  const color = isNaN(num) ? 'var(--tf-text)' : num >= 0 ? 'var(--tf-up)' : 'var(--tf-down)';
  return <td style={{ ...cellBase, color, fontWeight: 600, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{value}</td>;
};

const EarningsTable: React.FC<{ earnings: EarningsRecord[] }> = ({ earnings }) => {
  if (earnings.length === 0) {
    return <div style={{ fontSize: "var(--tf-fs-base)", color: 'var(--tf-muted)' }}>No earnings data available.</div>;
  }

  const thStyle: React.CSSProperties = {
    ...cellBase,
    color: 'var(--tf-muted)',
    fontWeight: 600,
    textAlign: 'left',
    fontSize: "var(--tf-fs-xs)",
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    background: 'var(--tf-bg-pane)',
    position: 'sticky',
    top: 0,
    zIndex: 1,
    whiteSpace: 'nowrap',
  };
  const tdRight: React.CSSProperties = { ...cellBase, textAlign: 'right', fontVariantNumeric: 'tabular-nums' };

  return (
    <div
      style={{
        overflowY: 'auto',
        flex: 1,
        minHeight: 0,
        maxHeight: 320,
        maxWidth: '100%',
        border: '1px solid var(--tf-border)',
        borderRadius: 'var(--tf-radius)',
        background: 'var(--tf-bg-elevated)',
      }}
    >
        <table style={{ width: '100%', borderCollapse: 'collapse', background: 'var(--tf-bg-elevated)' }}>
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
                <td style={{ ...cellBase, color: 'var(--tf-text)' }}>{e.date}</td>
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
