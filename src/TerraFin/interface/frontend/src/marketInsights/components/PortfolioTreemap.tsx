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
  row: PortfolioHoldingRow;
  weight: number;
  area: number;
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
const MIN_VISIBLE_COUNT = 4;
const MAX_VISIBLE_COUNT = 10;
const MIN_TILE_HEIGHT = 14;
const MIN_TILE_WIDTH = 18;

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
      row,
      weight: Math.max(parsePortfolioWeight(row['% of Portfolio']), 0.0001),
    }))
    .sort((left, right) => right.weight - left.weight);

  const maxCount = Math.min(MAX_VISIBLE_COUNT, weightedRows.length);
  const minCount = Math.min(MIN_VISIBLE_COUNT, maxCount);

  let fallback: LayoutTile[] = [];
  for (let count = maxCount; count >= minCount; count -= 1) {
    const subset = weightedRows.slice(0, count);
    const totalWeight = subset.reduce((acc, tile) => acc + tile.weight, 0) || 1;
    const normalized = subset.map((tile) => ({
      x: 0,
      y: 0,
      w: 0,
      h: 0,
      area: (tile.weight / totalWeight) * CANVAS_AREA,
      ...tile,
    }));

    const nextTiles = squarify(normalized);
    fallback = nextTiles;

    if (nextTiles.every((tile) => tile.h >= MIN_TILE_HEIGHT && tile.w >= MIN_TILE_WIDTH)) {
      return nextTiles;
    }
  }

  return fallback;
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

  const hiddenCount = Math.max(rows.length - tiles.length, 0);

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
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', color: '#64748b' }}>
            Treemap Legend
          </div>
          <div style={{ fontSize: 11, color: '#64748b' }}>
            {hiddenCount > 0 ? `${hiddenCount} smaller positions are listed at right` : 'Size = portfolio weight'}
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
                borderRadius: 999,
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                fontSize: 11,
                color: '#475569',
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 999,
                  background: `linear-gradient(160deg, ${item.fill} 0%, ${item.edge} 100%)`,
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
          borderRadius: 18,
          overflow: 'hidden',
          background: 'linear-gradient(180deg, #f8fafc 0%, #eef4ff 100%)',
          border: '1px solid #dbe5f0',
          boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.8)',
        }}
      >
        {tiles.length > 0 ? (
          tiles.map((tile) => {
            const rowKey = getPortfolioRowKey(tile.row);
            const tone = getPortfolioTone(tile.row.Updated, tile.row['Recent Activity']);
            const stock = splitPortfolioStockLabel(tile.row.Stock || '');
            const weight = parsePortfolioWeight(tile.row['% of Portfolio']);
            const update = parsePortfolioUpdate(tile.row.Updated);
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
                    borderRadius: isLarge ? 16 : 12,
                    background: `linear-gradient(160deg, ${tone.fill} 0%, ${tone.edge} 100%)`,
                    border: isActive ? '1px solid rgba(255, 255, 255, 0.85)' : '1px solid rgba(255, 255, 255, 0.18)',
                    boxShadow: isActive
                      ? `0 16px 32px ${tone.edge}55, inset 0 1px 0 rgba(255, 255, 255, 0.16)`
                      : '0 10px 20px rgba(15, 23, 42, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.1)',
                    color: '#ffffff',
                    padding: isLarge ? 12 : isMedium ? 9 : 7,
                    boxSizing: 'border-box',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'flex-start',
                    gap: 4,
                    outline: 'none',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: isLarge ? 17 : isMedium ? 13 : 11,
                        fontWeight: 800,
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
                          fontSize: 11,
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
                      <div style={{ fontSize: isLarge ? 12 : 10.5, fontWeight: 800 }}>{weight.toFixed(2)}%</div>
                      <div style={{ fontSize: isLarge ? 12 : 10.5, fontWeight: 700, opacity: 0.95 }}>
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
              fontSize: 13,
              color: '#64748b',
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
