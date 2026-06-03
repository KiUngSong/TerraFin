import React from 'react';
import type { CompanyInfo } from '../useStockData';

const StockHeader: React.FC<{ info: CompanyInfo }> = ({ info }) => {
  const changeColor = (info.changePercent ?? 0) >= 0 ? 'var(--tf-up)' : 'var(--tf-down)';
  const changeSign = (info.changePercent ?? 0) >= 0 ? '+' : '';
  // KR exchanges trade in won — drop the $ for .KS / .KQ tickers.
  const isKr = /\.(KS|KQ)$/i.test(info.ticker);
  const currencyPrefix = isKr ? '₩' : '$';
  const priceFmt = isKr ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
        <span style={{ fontFamily: 'var(--tf-sans)', fontSize: 'var(--tf-fs-md)', fontWeight: 700, color: 'var(--tf-text-strong)', letterSpacing: '0.04em', flexShrink: 0 }}>
          {info.ticker}
        </span>
        {info.shortName && (
          <span style={{ fontFamily: 'var(--tf-sans)', fontSize: 'var(--tf-fs-md)', color: 'var(--tf-muted)', fontWeight: 500, minWidth: 0, overflow: 'hidden', display: 'inline-block' }} title={info.shortName}>
            · {info.shortName}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', minWidth: 0 }}>
        {info.currentPrice != null && (
          <span
            style={{
              fontFamily: 'var(--tf-sans)',
              fontSize: 'var(--tf-fs-md)',
              lineHeight: 1.2,
              fontWeight: 700,
              color: 'var(--tf-text-strong)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {currencyPrefix}{info.currentPrice.toLocaleString(undefined, priceFmt)}
          </span>
        )}
        {info.changePercent != null && (
          <span
            style={{
              fontFamily: 'var(--tf-sans)',
              fontSize: 'var(--tf-fs-base)',
              fontWeight: 700,
              color: changeColor,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {changeSign}{info.changePercent.toFixed(2)}%
          </span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', minWidth: 0, marginTop: 4 }}>
        {info.sector && <span style={pillStyle}>{info.sector}</span>}
        {info.industry && <span style={pillStyle}>{info.industry}</span>}
      </div>
    </div>
  );
};

const pillStyle: React.CSSProperties = {
  fontFamily: 'var(--tf-sans)',
  fontSize: 'var(--tf-fs-xs)',
  fontWeight: 500,
  color: 'var(--tf-muted)',
  background: 'transparent',
  borderRadius: 'var(--tf-radius)',
  padding: '2px 8px',
  border: '1px solid var(--tf-border)',
  maxWidth: '100%',
  overflowWrap: 'anywhere',
  wordBreak: 'break-word',
};

export default StockHeader;
