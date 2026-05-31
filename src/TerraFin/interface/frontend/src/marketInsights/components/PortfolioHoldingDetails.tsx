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
  sourceUrl?: string;
  rows: PortfolioHoldingRow[];
  topHoldings: PortfolioHoldingRow[];
  activeRow: PortfolioHoldingRow | null;
  height?: React.CSSProperties['height'];
}

const sectionLabelStyle: React.CSSProperties = {
  fontSize: "var(--tf-fs-xs)",
  fontWeight: 700,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  color: 'var(--tf-muted)',
};

const metaValueStyle: React.CSSProperties = {
  fontSize: "var(--tf-fs-base)",
  fontWeight: 700,
  color: 'var(--tf-text)',
};

const listItemValueStyle: React.CSSProperties = {
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap',
};

const DESKTOP_SUMMARY_MIN_HEIGHT = 112;

const PortfolioHoldingDetails: React.FC<PortfolioHoldingDetailsProps> = ({
  guru,
  period,
  sourceUrl,
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
            borderRadius: 'var(--tf-radius)',
            border: `1px solid ${activeTone.edge}`,
            background: activeTone.fill,
            color: '#ffffff',
            padding: 8,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: 6,
            overflow: 'hidden',
            minHeight: 0,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: "var(--tf-fs-micro)", fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', opacity: 0.78 }}>
                Focused Holding
              </div>
              <div
                style={{
                  fontSize: "var(--tf-fs-base)",
                  fontWeight: 700,
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
                    fontSize: "var(--tf-fs-micro)",
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
                fontSize: "var(--tf-fs-micro)",
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
            borderRadius: 'var(--tf-radius)',
            border: '1px solid var(--tf-border)',
            background: 'var(--tf-bg-elevated)',
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
                fontSize: "var(--tf-fs-md)",
                fontWeight: 700,
                color: 'var(--tf-text-strong)',
                ...(isMobile
                  ? { whiteSpace: 'normal', overflowWrap: 'anywhere' as const }
                  : { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }),
              }}
            >
              {guru || 'Investor Positioning'}
            </div>
          </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
              <div
                style={{
                  fontSize: "var(--tf-fs-micro)",
                  fontWeight: 700,
                  color: 'var(--tf-muted)',
                  whiteSpace: isMobile ? 'normal' : 'nowrap',
                  textAlign: 'right',
                }}
              >
                {period || 'Latest filing'}
              </div>
              {sourceUrl && (
                <a
                  href={sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    fontSize: "var(--tf-fs-micro)",
                    fontWeight: 700,
                    color: 'var(--tf-amber)',
                    textDecoration: 'none',
                    whiteSpace: 'nowrap',
                  }}
                >
                  View on EDGAR ↗
                </a>
              )}
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
          borderRadius: 'var(--tf-radius)',
          border: '1px solid var(--tf-border)',
          background: 'var(--tf-bg-elevated)',
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            padding: '8px 10px',
            borderBottom: '1px solid var(--tf-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
          }}
        >
          <div style={sectionLabelStyle}>Top Holdings</div>
          <div style={{ fontSize: "var(--tf-fs-micro)", color: 'var(--tf-muted)' }}>{rankedHoldings.length > 0 ? `${rankedHoldings.length} tracked` : 'No holdings'}</div>
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
                      borderRadius: 'var(--tf-radius)',
                      border: isActive ? `1px solid ${tone.edge}` : '1px solid var(--tf-border)',
                      background: isActive ? 'var(--tf-bg-elevated)' : 'var(--tf-bg)',
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
                            background: isActive ? tone.fill : 'var(--tf-bg-elevated)',
                            color: isActive ? '#ffffff' : 'var(--tf-text)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: "var(--tf-fs-micro)",
                            fontWeight: 700,
                            flexShrink: 0,
                          }}
                        >
                          {index + 1}
                        </div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: "var(--tf-fs-xs)", fontWeight: 700, color: 'var(--tf-text-strong)' }}>{ticker.ticker}</div>
                          {ticker.company ? (
                            <div style={{ fontSize: "var(--tf-fs-micro)", lineHeight: 1.15, color: 'var(--tf-muted)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {ticker.company}
                            </div>
                          ) : null}
                        </div>
                      </div>
                      <div style={{ ...listItemValueStyle, fontSize: "var(--tf-fs-micro)", fontWeight: 700, color: 'var(--tf-text-strong)' }}>{weight.toFixed(2)}%</div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                      <div style={{ fontSize: "var(--tf-fs-micro)", color: 'var(--tf-muted)' }}>{formatPortfolioActivity(holding)}</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        {Array.isArray(holding.History) ? (
                          <HistorySparkline data={holding.History as (number | null)[]} />
                        ) : null}
                        <div
                          style={{
                            ...listItemValueStyle,
                            fontSize: "var(--tf-fs-micro)",
                            fontWeight: 700,
                            color: update < 0 ? 'var(--tf-down)' : update > 0 ? 'var(--tf-up)' : 'var(--tf-muted)',
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
                fontSize: "var(--tf-fs-base)",
                color: 'var(--tf-muted)',
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
  const color = trending === true ? 'var(--tf-up)' : trending === false ? 'var(--tf-down)' : 'var(--tf-muted)';
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
      borderRadius: 'var(--tf-radius)',
      border: inverse ? '1px solid rgba(255, 255, 255, 0.16)' : '1px solid var(--tf-border)',
      background: inverse ? 'rgba(255, 255, 255, 0.12)' : subtle ? 'var(--tf-bg)' : 'var(--tf-bg-elevated)',
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
        fontSize: "var(--tf-fs-micro)",
        fontWeight: 700,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        color: inverse ? 'rgba(255, 255, 255, 0.72)' : 'var(--tf-muted)',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
    <span
      style={{
        fontSize: "var(--tf-fs-xs)",
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
