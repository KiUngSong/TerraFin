import React from 'react';
import { useViewportTier } from '../../shared/responsive';

import {
  PortfolioHoldingRow,
  formatPortfolioActivity,
  formatSignedPercent,
  getPortfolioRowKey,
  getPortfolioTone,
  hasPortfolioFieldValue,
  parsePortfolioUpdate,
  parsePortfolioWeight,
  splitPortfolioStockLabel,
} from './portfolioPositioning';

interface PortfolioHoldingDetailsProps {
  guru: string;
  period?: string;
  rows: PortfolioHoldingRow[];
  topHoldings: PortfolioHoldingRow[];
  activeRow: PortfolioHoldingRow | null;
  height?: React.CSSProperties['height'];
}

const sectionLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  color: '#64748b',
};

const metaValueStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 700,
  color: '#0f172a',
};

const listItemValueStyle: React.CSSProperties = {
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap',
};

const DESKTOP_SUMMARY_MIN_HEIGHT = 112;

const PortfolioHoldingDetails: React.FC<PortfolioHoldingDetailsProps> = ({
  guru,
  period,
  rows,
  topHoldings,
  activeRow,
  height = '100%',
}) => {
  const { isMobile } = useViewportTier();
  const activeTicker = activeRow ? splitPortfolioStockLabel(activeRow.Stock) : null;
  const activeWeight = activeRow ? parsePortfolioWeight(activeRow['% of Portfolio']) : null;
  const activeUpdate = activeRow ? parsePortfolioUpdate(activeRow.Updated) : null;
  const activeTone = activeRow ? getPortfolioTone(activeRow.Updated, activeRow['Recent Activity']) : null;
  const rankedHoldings = (rows.length > 0 ? rows : topHoldings)
    .slice()
    .sort((left, right) => parsePortfolioWeight(right['% of Portfolio']) - parsePortfolioWeight(left['% of Portfolio']));
  const largestTicker = topHoldings[0] ? splitPortfolioStockLabel(topHoldings[0].Stock) : rows[0] ? splitPortfolioStockLabel(rows[0].Stock) : null;
  const largestWeight = topHoldings[0]
    ? parsePortfolioWeight(topHoldings[0]['% of Portfolio'])
    : rows[0]
      ? parsePortfolioWeight(rows[0]['% of Portfolio'])
      : null;
  const activeKey = activeRow ? getPortfolioRowKey(activeRow) : null;
  const snapshotDescription = activeRow
    ? null
    : 'Hover a treemap block to inspect the holding behind the weight map.';

  return (
    <div
      style={{
        height,
        display: 'grid',
        gridTemplateRows: isMobile
          ? 'auto minmax(0, 1fr)'
          : `minmax(${DESKTOP_SUMMARY_MIN_HEIGHT}px, auto) minmax(0, 1fr)`,
        gap: 12,
      }}
    >
      {activeRow && activeTicker && activeTone ? (
        <div
          style={{
            borderRadius: 14,
            border: `1px solid ${activeTone.edge}`,
            background: `linear-gradient(180deg, ${activeTone.fill} 0%, ${activeTone.edge} 100%)`,
            color: '#ffffff',
            padding: 8,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: 6,
            boxShadow: `0 12px 28px ${activeTone.edge}33`,
            overflow: 'hidden',
            minHeight: 0,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', opacity: 0.78 }}>
                Focused Holding
              </div>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 800,
                  lineHeight: 1.05,
                  ...(isMobile
                    ? { whiteSpace: 'normal', overflowWrap: 'anywhere' as const }
                    : { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }),
                }}
              >
                {activeTicker.ticker}
              </div>
              {activeTicker.company ? (
                <div
                  style={{
                    marginTop: 1,
                    fontSize: 9.5,
                    lineHeight: 1.15,
                    opacity: 0.9,
                    ...(isMobile
                      ? { whiteSpace: 'normal', overflowWrap: 'anywhere' as const }
                      : { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }),
                  }}
                >
                  {activeTicker.company}
                </div>
              ) : null}
            </div>
            <div
              style={{
                borderRadius: 999,
                padding: '4px 8px',
                background: 'rgba(255, 255, 255, 0.14)',
                border: '1px solid rgba(255, 255, 255, 0.22)',
                fontSize: 10,
                fontWeight: 700,
                whiteSpace: 'nowrap',
              }}
            >
              {activeWeight?.toFixed(2)}%
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 4,
            }}
          >
            <InlineMetric label="Change" value={activeUpdate != null ? formatSignedPercent(activeUpdate) : '-'} inverse />
            <InlineMetric label="Activity" value={formatPortfolioActivity(activeRow)} inverse />
            <InlineMetric label="Shares" value={hasPortfolioFieldValue(activeRow.Shares) ? activeRow.Shares || '-' : '-'} inverse />
            <InlineMetric label="Price" value={hasPortfolioFieldValue(activeRow['Reported Price']) ? activeRow['Reported Price'] || '-' : '-'} inverse />
          </div>
        </div>
      ) : (
        <div
          style={{
            borderRadius: 14,
            border: '1px solid #dbe5f0',
            background: 'linear-gradient(180deg, #f8fbff 0%, #eef4ff 100%)',
            padding: 8,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: 6,
            overflow: 'hidden',
            minHeight: 0,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <div style={sectionLabelStyle}>Portfolio Snapshot</div>
              <div
              style={{
                fontSize: 13,
                fontWeight: 800,
                color: '#0f172a',
                ...(isMobile
                  ? { whiteSpace: 'normal', overflowWrap: 'anywhere' as const }
                  : { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }),
              }}
            >
              {guru || 'Investor Positioning'}
            </div>
          </div>
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: '#475569',
                whiteSpace: isMobile ? 'normal' : 'nowrap',
                textAlign: 'right',
              }}
            >
              {period || 'Latest filing'}
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 4,
            }}
          >
            <InlineMetric label="Holdings" value={String(rows.length || 0)} />
            <InlineMetric label="Largest" value={largestTicker?.ticker || '-'} />
            <InlineMetric label="Weight" value={largestWeight != null ? `${largestWeight.toFixed(2)}%` : '-'} />
            {snapshotDescription ? <InlineMetric label="Hint" value="Hover a treemap block" subtle /> : null}
          </div>
        </div>
      )}

      <div
        style={{
          borderRadius: 12,
          border: '1px solid #e2e8f0',
          background: '#ffffff',
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            padding: '8px 10px',
            borderBottom: '1px solid #eef2f7',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
          }}
        >
          <div style={sectionLabelStyle}>Top Holdings</div>
          <div style={{ fontSize: 9.5, color: '#64748b' }}>{rankedHoldings.length > 0 ? `${rankedHoldings.length} tracked` : 'No holdings'}</div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 5 }}>
          {rankedHoldings.length > 0 ? (
            <div style={{ display: 'grid', gap: 4 }}>
              {rankedHoldings.map((holding, index) => {
                const rowKey = getPortfolioRowKey(holding);
                const ticker = splitPortfolioStockLabel(holding.Stock);
                const weight = parsePortfolioWeight(holding['% of Portfolio']);
                const update = parsePortfolioUpdate(holding.Updated);
                const isActive = activeKey === rowKey;
                const tone = getPortfolioTone(holding.Updated, holding['Recent Activity']);

                return (
                  <div
                    key={rowKey}
                    style={{
                      borderRadius: 12,
                      border: isActive ? `1px solid ${tone.edge}` : '1px solid #edf2f7',
                      background: isActive ? `${tone.fill}12` : '#f8fafc',
                      padding: '6px 8px',
                      display: 'grid',
                      gap: 3,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                        <div
                          style={{
                            width: 24,
                            height: 24,
                            borderRadius: 999,
                            background: isActive ? tone.fill : '#e2e8f0',
                            color: isActive ? '#ffffff' : '#334155',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: 10.5,
                            fontWeight: 800,
                            flexShrink: 0,
                          }}
                        >
                          {index + 1}
                        </div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 11, fontWeight: 800, color: '#0f172a' }}>{ticker.ticker}</div>
                          {ticker.company ? (
                            <div style={{ fontSize: 9.5, lineHeight: 1.15, color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {ticker.company}
                            </div>
                          ) : null}
                        </div>
                      </div>
                      <div style={{ ...listItemValueStyle, fontSize: 10.5, fontWeight: 800, color: '#0f172a' }}>{weight.toFixed(2)}%</div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                      <div style={{ fontSize: 9.5, color: '#475569' }}>{formatPortfolioActivity(holding)}</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        {Array.isArray(holding.History) ? (
                          <HistorySparkline data={holding.History as (number | null)[]} />
                        ) : null}
                        <div
                          style={{
                            ...listItemValueStyle,
                            fontSize: 9.5,
                            fontWeight: 700,
                            color: update < 0 ? '#b42318' : update > 0 ? '#166534' : '#475569',
                          }}
                        >
                          {formatSignedPercent(update)}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div
              style={{
                padding: 20,
                textAlign: 'center',
                fontSize: 13,
                color: '#94a3b8',
              }}
            >
              No holdings available yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

interface SparklineProps {
  data: (number | null)[];
  width?: number;
  height?: number;
}

const HistorySparkline: React.FC<SparklineProps> = ({ data, width = 48, height = 18 }) => {
  const values = data.filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = data
    .map((v, i) => {
      if (v == null) return null;
      const x = (i / (data.length - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter(Boolean)
    .join(' ');
  const lastVal = data[data.length - 1];
  const prevVal = data.slice(0, -1).reverse().find((v) => v != null);
  const trending = lastVal != null && prevVal != null ? lastVal >= prevVal : null;
  const color = trending === true ? '#166534' : trending === false ? '#b42318' : '#64748b';
  return (
    <svg width={width} height={height} style={{ display: 'block', flexShrink: 0 }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
};

interface MetricProps {
  label: string;
  value: string;
  inverse?: boolean;
  subtle?: boolean;
}

const InlineMetric: React.FC<MetricProps> = ({ label, value, inverse = false, subtle = false }) => (
  <div
    style={{
      borderRadius: 999,
      border: inverse ? '1px solid rgba(255, 255, 255, 0.16)' : '1px solid #e2e8f0',
      background: inverse ? 'rgba(255, 255, 255, 0.12)' : subtle ? '#f8fafc' : '#ffffff',
      padding: '4px 7px',
      display: 'inline-flex',
      alignItems: 'baseline',
      flexWrap: 'wrap',
      gap: 5,
      minWidth: 0,
      maxWidth: '100%',
    }}
  >
    <span
      style={{
        fontSize: 8.5,
        fontWeight: 700,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        color: inverse ? 'rgba(255, 255, 255, 0.72)' : '#64748b',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        lineHeight: 1.2,
        color: inverse ? '#ffffff' : metaValueStyle.color,
        whiteSpace: 'normal',
        overflowWrap: 'anywhere',
      }}
    >
      {value}
    </span>
  </div>
);

export default PortfolioHoldingDetails;
