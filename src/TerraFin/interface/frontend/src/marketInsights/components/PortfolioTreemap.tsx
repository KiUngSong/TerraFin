import React, { useCallback, useMemo, useRef } from 'react';

import {
  PORTFOLIO_LEGEND,
  PortfolioHoldingRow,
  formatSignedPercent,
  getPortfolioRowKey,
  getPortfolioTone,
  parsePortfolioUpdate,
  parsePortfolioWeight,
  splitPortfolioStockLabel,
} from './portfolioPositioning';

interface LayoutTile {
  x: number;
  y: number;
  w: number;
  h: number;
  row: PortfolioHoldingRow | null; // null = the aggregated "Other" tile
  weight: number;
  area: number;
  otherCount?: number; // when set, this tile aggregates N small holdings
}

interface PortfolioTreemapProps {
  rows: PortfolioHoldingRow[];
  height?: React.CSSProperties['height'];
  activeRowKey?: string | null;
  onActiveRowChange?: (row: PortfolioHoldingRow | null) => void;
}

const CANVAS_WIDTH = 100;
const CANVAS_HEIGHT = 100;
const CANVAS_AREA = CANVAS_WIDTH * CANVAS_HEIGHT;
const MAX_VISIBLE_COUNT = 10;
const MIN_VISIBLE_WEIGHT = 5.0; // % of portfolio — below this folds into "Other"

const worstAspectRatio = (row: LayoutTile[], shortSide: number): number => {
  if (row.length === 0) {
    return Number.POSITIVE_INFINITY;
  }

  const totalArea = row.reduce((acc, tile) => acc + tile.area, 0);
  const largest = Math.max(...row.map((tile) => tile.area));
  const smallest = Math.min(...row.map((tile) => tile.area));
  const shortSideSquared = shortSide * shortSide;

  return Math.max(
    (shortSideSquared * largest) / (totalArea * totalArea),
    (totalArea * totalArea) / (shortSideSquared * smallest),
  );
};

const layoutStrip = (
  row: LayoutTile[],
  rect: Pick<LayoutTile, 'x' | 'y' | 'w' | 'h'>,
): {
  placed: LayoutTile[];
  nextRect: Pick<LayoutTile, 'x' | 'y' | 'w' | 'h'>;
} => {
  const totalArea = row.reduce((acc, tile) => acc + tile.area, 0);

  if (rect.w >= rect.h) {
    const stripHeight = totalArea / rect.w;
    let cursorX = rect.x;
    const placed = row.map((tile) => {
      const tileWidth = tile.area / stripHeight;
      const nextTile = { ...tile, x: cursorX, y: rect.y, w: tileWidth, h: stripHeight };
      cursorX += tileWidth;
      return nextTile;
    });

    return {
      placed,
      nextRect: {
        x: rect.x,
        y: rect.y + stripHeight,
        w: rect.w,
        h: rect.h - stripHeight,
      },
    };
  }

  const stripWidth = totalArea / rect.h;
  let cursorY = rect.y;
  const placed = row.map((tile) => {
    const tileHeight = tile.area / stripWidth;
    const nextTile = { ...tile, x: rect.x, y: cursorY, w: stripWidth, h: tileHeight };
    cursorY += tileHeight;
    return nextTile;
  });

  return {
    placed,
    nextRect: {
      x: rect.x + stripWidth,
      y: rect.y,
      w: rect.w - stripWidth,
      h: rect.h,
    },
  };
};

const squarify = (items: LayoutTile[]): LayoutTile[] => {
  const source = [...items];
  let row: LayoutTile[] = [];
  let rect = { x: 0, y: 0, w: CANVAS_WIDTH, h: CANVAS_HEIGHT };
  const output: LayoutTile[] = [];

  while (source.length > 0) {
    const next = source[0];
    const shortSide = Math.min(rect.w, rect.h);
    const currentWorst = worstAspectRatio(row, shortSide);
    const nextWorst = worstAspectRatio([...row, next], shortSide);

    if (row.length === 0 || nextWorst <= currentWorst) {
      row.push(next);
      source.shift();
      continue;
    }

    const result = layoutStrip(row, rect);
    output.push(...result.placed);
    rect = result.nextRect;
    row = [];
  }

  if (row.length > 0) {
    const result = layoutStrip(row, rect);
    output.push(...result.placed);
  }

  return output;
};

const buildTiles = (rows: PortfolioHoldingRow[]): LayoutTile[] => {
  const weightedRows = rows
    .map((row) => ({
      row: row as PortfolioHoldingRow | null,
      weight: Math.max(parsePortfolioWeight(row['% of Portfolio']), 0.0001),
      otherCount: undefined as number | undefined,
    }))
    .sort((left, right) => right.weight - left.weight);

  if (weightedRows.length === 0) return [];

  // Show only holdings big enough to render readably; fold the rest into ONE
  // "Other" tile. Fold EARLY — any holding below MIN_VISIBLE_WEIGHT becomes a
  // sliver, so it goes to Other (always show at least the top 3, at most
  // MAX_VISIBLE_COUNT). Keeps every visible tile legible; no unreadable boxes.
  let cut = weightedRows.findIndex((r) => r.weight < MIN_VISIBLE_WEIGHT);
  if (cut < 0) cut = weightedRows.length;
  cut = Math.min(Math.max(cut, Math.min(2, weightedRows.length)), MAX_VISIBLE_COUNT);
  const head = weightedRows.slice(0, cut);
  const tail = weightedRows.slice(cut);
  const entries = [...head];
  if (tail.length > 0) {
    entries.push({
      row: null,
      weight: tail.reduce((acc, t) => acc + t.weight, 0),
      otherCount: tail.length,
    });
  }

  const totalWeight = entries.reduce((acc, e) => acc + e.weight, 0) || 1;
  const normalized: LayoutTile[] = entries.map((e) => ({
    x: 0,
    y: 0,
    w: 0,
    h: 0,
    area: (e.weight / totalWeight) * CANVAS_AREA,
    row: e.row,
    weight: e.weight,
    otherCount: e.otherCount,
  }));

  return squarify(normalized);
};

const PortfolioTreemap: React.FC<PortfolioTreemapProps> = ({
  rows,
  height = '100%',
  activeRowKey = null,
  onActiveRowChange,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);

  const tiles = useMemo(() => {
    if (rows.length === 0) {
      return [];
    }

    return buildTiles(rows);
  }, [rows]);

  const clearActive = useCallback(() => {
    onActiveRowChange?.(null);
  }, [onActiveRowChange]);

  const handleBlurCapture = useCallback(
    (event: React.FocusEvent<HTMLDivElement>) => {
      const nextTarget = event.relatedTarget;
      if (nextTarget instanceof Node && containerRef.current?.contains(nextTarget)) {
        return;
      }
      clearActive();
    },
    [clearActive],
  );

  return (
    <div
      style={{
        height,
        minHeight: 0,
        display: 'grid',
        gridTemplateRows: 'auto minmax(0, 1fr)',
        gap: 10,
      }}
    >
      <div style={{ display: 'grid', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
          <div style={{ fontSize: "var(--tf-fs-micro)", fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--tf-muted)' }}>
            Treemap Legend
          </div>
          <div style={{ fontSize: "var(--tf-fs-micro)", color: 'var(--tf-muted)' }}>
            Size = portfolio weight
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {PORTFOLIO_LEGEND.map((item) => (
            <div
              key={item.label}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 8px',
                borderRadius: 'var(--tf-radius)',
                background: 'var(--tf-bg-elevated)',
                border: '1px solid var(--tf-border)',
                fontSize: "var(--tf-fs-micro)",
                color: 'var(--tf-text)',
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 999,
                  background: item.fill,
                  flexShrink: 0,
                }}
              />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div
        ref={containerRef}
        onMouseLeave={clearActive}
        onBlurCapture={handleBlurCapture}
        style={{
          width: '100%',
          height: '100%',
          minHeight: 0,
          position: 'relative',
          borderRadius: 'var(--tf-radius)',
          overflow: 'hidden',
          background: 'var(--tf-bg-elevated)',
          border: '1px solid var(--tf-border)',
        }}
      >
        {tiles.length > 0 ? (
          tiles.map((tile) => {
            if (tile.otherCount != null || !tile.row) {
              return (
                <button
                  key="__other__"
                  type="button"
                  onMouseEnter={clearActive}
                  onFocus={clearActive}
                  style={{
                    position: 'absolute',
                    left: `${tile.x}%`,
                    top: `${tile.y}%`,
                    width: `${tile.w}%`,
                    height: `${tile.h}%`,
                    padding: 3,
                    border: 'none',
                    background: 'transparent',
                    cursor: 'default',
                    textAlign: 'left',
                  }}
                  aria-label={`Other holdings: ${tile.weight.toFixed(2)} percent of portfolio across ${tile.otherCount ?? 0} positions`}
                >
                  <div
                    style={{
                      width: '100%',
                      height: '100%',
                      borderRadius: 'var(--tf-radius)',
                      background: 'var(--tf-bg-hover)',
                      border: '1px solid var(--tf-border)',
                      color: 'var(--tf-muted-strong)',
                      padding: 7,
                      boxSizing: 'border-box',
                      overflow: 'hidden',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      fontFamily: 'var(--tf-mono)',
                    }}
                  >
                    <div style={{ fontSize: 'var(--tf-fs-xs)', fontWeight: 700, letterSpacing: '0.04em' }}>OTHER</div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 8, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                      <span style={{ fontSize: 'var(--tf-fs-micro)' }}>{tile.otherCount} holdings</span>
                      <span style={{ fontSize: 'var(--tf-fs-base)', fontWeight: 700 }}>{tile.weight.toFixed(2)}%</span>
                    </div>
                  </div>
                </button>
              );
            }
            const row = tile.row;
            const rowKey = getPortfolioRowKey(row);
            const tone = getPortfolioTone(row.Updated, row['Recent Activity']);
            const stock = splitPortfolioStockLabel(row.Stock || '');
            const weight = parsePortfolioWeight(row['% of Portfolio']);
            const update = parsePortfolioUpdate(row.Updated);
            const isActive = activeRowKey === rowKey;
            const minDimension = Math.min(tile.w, tile.h);
            const isLarge = tile.w >= 24 && tile.h >= 20;
            const isMedium = !isLarge && tile.w >= 18 && tile.h >= 14;
            const canShowMetrics = tile.h >= 18 && tile.w >= 24;
            const canWrapPrimary = !stock.company && tile.h >= 18;
            const primaryLineClamp = canWrapPrimary ? (isLarge ? 2 : 1) : 1;

            return (
              <button
                key={rowKey}
                type="button"
                onMouseEnter={() => onActiveRowChange?.(tile.row)}
                onFocus={() => onActiveRowChange?.(tile.row)}
                onPointerDown={() => onActiveRowChange?.(tile.row)}
                style={{
                  position: 'absolute',
                  left: `${tile.x}%`,
                  top: `${tile.y}%`,
                  width: `${tile.w}%`,
                  height: `${tile.h}%`,
                  padding: 3,
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
                aria-label={`${stock.ticker}, ${weight.toFixed(2)} percent of portfolio, position change ${formatSignedPercent(update)}`}
              >
                <div
                  style={{
                    width: '100%',
                    height: '100%',
                    borderRadius: 'var(--tf-radius)',
                    background: tone.fill,
                    border: isActive ? '1px solid var(--tf-amber)' : '1px solid var(--tf-border)',
                    color: '#ffffff',
                    padding: isLarge ? 12 : isMedium ? 9 : 7,
                    boxSizing: 'border-box',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'flex-start',
                    gap: 4,
                    outline: 'none',
                    fontFamily: 'var(--tf-mono)',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: isLarge ? 'var(--tf-fs-base)' : 'var(--tf-fs-xs)',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        lineHeight: canWrapPrimary ? 1.1 : 1.05,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: canWrapPrimary ? 'normal' : 'nowrap',
                        display: canWrapPrimary ? '-webkit-box' : 'block',
                        WebkitLineClamp: canWrapPrimary ? primaryLineClamp : undefined,
                        WebkitBoxOrient: canWrapPrimary ? 'vertical' : undefined,
                      }}
                    >
                      {stock.ticker}
                    </div>
                    {isLarge && stock.company ? (
                      <div
                        style={{
                          marginTop: 4,
                          fontSize: 'var(--tf-fs-xs)',
                          fontWeight: 600,
                          lineHeight: 1.35,
                          opacity: 0.92,
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {stock.company}
                      </div>
                    ) : null}
                  </div>

                  {canShowMetrics ? (
                    <div
                      style={{
                        marginTop: 'auto',
                        display: 'flex',
                        alignItems: 'flex-end',
                        justifyContent: 'space-between',
                        gap: 8,
                        fontVariantNumeric: 'tabular-nums',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      <div style={{ fontSize: 'var(--tf-fs-base)', fontWeight: 700 }}>{weight.toFixed(2)}%</div>
                      <div style={{ fontSize: 'var(--tf-fs-base)', fontWeight: 700, opacity: 0.95 }}>
                        {formatSignedPercent(update)}
                      </div>
                    </div>
                  ) : null}
                </div>
              </button>
            );
          })
        ) : (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: "var(--tf-fs-base)",
              color: 'var(--tf-muted)',
            }}
          >
            No portfolio holdings available.
          </div>
        )}
      </div>
    </div>
  );
};

export default PortfolioTreemap;
