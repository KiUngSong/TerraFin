import React, { useEffect, useState } from 'react';
import { useTerminalStore } from '../../terminal/store';

interface SectorTile {
  symbol: string;
  name: string;
  movePct: number | null;
}

interface SectorsPayload {
  tiles: SectorTile[];
}

// 11 GICS sector ETFs in fixed order, full names hardcoded.
const SECTORS: Array<{ symbol: string; name: string }> = [
  { symbol: 'XLK', name: 'Technology' },
  { symbol: 'XLC', name: 'Comm. Svcs' },
  { symbol: 'XLY', name: 'Cons. Discr.' },
  { symbol: 'XLP', name: 'Cons. Staples' },
  { symbol: 'XLE', name: 'Energy' },
  { symbol: 'XLF', name: 'Financials' },
  { symbol: 'XLV', name: 'Health Care' },
  { symbol: 'XLI', name: 'Industrials' },
  { symbol: 'XLB', name: 'Materials' },
  { symbol: 'XLRE', name: 'Real Estate' },
  { symbol: 'XLU', name: 'Utilities' },
];

// Continuous diverging scale — interpolate between a faint endpoint and a
// saturated endpoint by |pct| capped at 2.5%. Monotonic: bigger move = darker
// tile, so severity ranks correctly at a glance (the 3-bucket version collapsed
// −0.84/−0.93/−0.97 to one color).
const lerp = (a: number, b: number, t: number) => Math.round(a + (b - a) * t);
const mix = (c0: number[], c1: number[], t: number) =>
  `rgb(${lerp(c0[0], c1[0], t)}, ${lerp(c0[1], c1[1], t)}, ${lerp(c0[2], c1[2], t)})`;

// [faint, saturated] RGB endpoints per direction + theme.
const RAMP = {
  dark: {
    gain: [[19, 38, 30], [60, 224, 130]],
    loss: [[48, 26, 30], [255, 110, 122]],
  },
  light: {
    gain: [[214, 240, 224], [21, 128, 61]],
    loss: [[246, 220, 223], [185, 28, 28]],
  },
} as const;

const toneFor = (
  pct: number | null,
  theme: 'dark' | 'light',
): { bg: string; fg: string } => {
  if (pct == null) {
    return { bg: 'var(--tf-bg-elevated)', fg: 'var(--tf-text)' };
  }
  const t = Math.min(Math.abs(pct) / 2.5, 1);
  const ramp = RAMP[theme];
  const [c0, c1] = pct >= 0 ? ramp.gain : ramp.loss;
  const bg = mix(c0 as unknown as number[], c1 as unknown as number[], t);
  // Flip to contrasting text once the fill is dark/saturated enough.
  const dark = theme === 'dark';
  const fg = dark
    ? t > 0.55 ? '#0b0e12' : '#e6e9ee'
    : t > 0.55 ? '#ffffff' : '#111110';
  return { bg, fg };
};

const fmtPct = (pct: number | null): string => {
  if (pct == null) return '--';
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : ' ';
  return `${sign}${Math.abs(pct).toFixed(2)}%`;
};

const SectorGrid: React.FC = () => {
  const [tiles, setTiles] = useState<SectorTile[]>([]);
  const [loading, setLoading] = useState(true);
  const theme = useTerminalStore((s) => s.theme);
  const markDataFresh = useTerminalStore((s) => s.markDataFresh);

  useEffect(() => {
    fetch('/terminal/api/sectors')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((p: SectorsPayload) => {
        setTiles(p.tiles || []);
        markDataFresh();
      })
      .catch(() => setTiles([]))
      .finally(() => setLoading(false));
  }, [markDataFresh]);

  if (loading) return <div className="tf-table__status">loading sectors…</div>;
  if (tiles.length === 0) return <div className="tf-table__status">no sector data</div>;

  const tileMap: Record<string, SectorTile> = {};
  for (const t of tiles) tileMap[t.symbol] = t;
  // SPY benchmark folds in as the 12th tile (top-left anchor) so the grid is
  // exactly 12 cells — divisible by every column count (6/4/3/2), no void cell,
  // and no separate header/legend bands eating vertical space.
  const cells: Array<{ symbol: string; name: string; bench?: boolean }> = [
    { symbol: 'SPY', name: 'S&P 500', bench: true },
    ...SECTORS,
  ];

  return (
    <div className="tf-sector">
      <div className="tf-sector__grid">
        {cells.map((s) => {
          const tile = tileMap[s.symbol];
          const pct = tile ? tile.movePct : null;
          const tone = toneFor(pct, theme);
          return (
            <a
              key={s.symbol}
              href={`/stock/${s.symbol}`}
              className={`tf-sector__cell${s.bench ? ' tf-sector__cell--bench' : ''}`}
              style={{ background: tone.bg, color: tone.fg }}
              title={`${s.symbol} · ${s.name} · ${fmtPct(pct)}`}
            >
              <span className="tf-sector__name">
                {s.name} <span className="tf-sector__sym">{s.symbol}</span>
              </span>
              <span className="tf-sector__pct">{fmtPct(pct)}</span>
            </a>
          );
        })}
      </div>
    </div>
  );
};

export default SectorGrid;
