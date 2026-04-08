import React from 'react';
import type { CompanyInfo } from '../useStockData';

const StockHeader: React.FC<{ info: CompanyInfo }> = ({ info }) => {
  const changeColor = (info.changePercent ?? 0) >= 0 ? '#047857' : '#b91c1c';
  const changeSign = (info.changePercent ?? 0) >= 0 ? '+' : '';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 20, lineHeight: 1, fontWeight: 800, color: '#0f172a' }}>{info.ticker}</span>
        {info.shortName && (
          <span style={{ fontSize: 14, color: '#334155', fontWeight: 600 }}>{info.shortName}</span>
        )}
        {info.currentPrice != null && (
          <span style={{ fontSize: 17, fontWeight: 800, color: '#0f172a' }}>
            ${info.currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        )}
        {info.changePercent != null && (
          <span style={{ fontSize: 13, fontWeight: 700, color: changeColor }}>
            {changeSign}{info.changePercent.toFixed(2)}%
          </span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {info.sector && <span style={pillStyle}>{info.sector}</span>}
        {info.industry && <span style={pillStyle}>{info.industry}</span>}
      </div>
    </div>
  );
};

const pillStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#475569',
  background: '#f1f5f9',
  borderRadius: 999,
  padding: '5px 12px',
  border: '1px solid #e2e8f0',
};

export default StockHeader;
