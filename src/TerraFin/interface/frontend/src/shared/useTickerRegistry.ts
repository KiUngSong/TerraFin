import { useEffect, useState } from 'react';

export interface IndicatorEntry {
  symbol: string;
  name: string;
  group: string;
}

export interface TickerRegistry {
  krAliases: Record<string, string>;
  indicators: IndicatorEntry[];
}

// Bump version when the server-side indicator catalog shape changes so old
// sessionStorage caches don't keep showing removed/duplicated entries.
const CACHE_KEY = 'tf-ticker-registry-v2';
let inflight: Promise<TickerRegistry> | null = null;
let memo: TickerRegistry | null = null;

function readCache(): TickerRegistry | null {
  if (memo) return memo;
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && parsed.kr_aliases && Array.isArray(parsed.indicators)) {
      const reg: TickerRegistry = {
        krAliases: parsed.kr_aliases,
        indicators: parsed.indicators,
      };
      memo = reg;
      return reg;
    }
  } catch {
    // ignore
  }
  return null;
}

async function fetchRegistry(): Promise<TickerRegistry> {
  if (memo) return memo;
  if (inflight) return inflight;
  inflight = (async () => {
    const resp = await fetch('/api/ticker-search/registry');
    if (!resp.ok) throw new Error(`registry ${resp.status}`);
    const data = await resp.json();
    const reg: TickerRegistry = {
      krAliases: data.kr_aliases || {},
      indicators: data.indicators || [],
    };
    memo = reg;
    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(data)); } catch { /* ignore */ }
    return reg;
  })().finally(() => { inflight = null; });
  return inflight;
}

export function useTickerRegistry(): TickerRegistry | null {
  const [reg, setReg] = useState<TickerRegistry | null>(() => readCache());

  useEffect(() => {
    if (reg) return;
    let cancelled = false;
    fetchRegistry()
      .then((r) => { if (!cancelled) setReg(r); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [reg]);

  return reg;
}

const HANGUL_RE = /[가-힣]/;

export function isKoreanQuery(q: string): boolean {
  return HANGUL_RE.test(q);
}

function normalize(s: string): string {
  return s.trim().toLowerCase().replace(/\s+/g, '');
}

export interface LocalHit {
  symbol: string;
  name: string;
  group?: string;
  exchange?: string;
  category: 'indicator' | 'stock';
}

export function localPrefixMatch(
  query: string,
  reg: TickerRegistry,
  limit = 8,
): { hits: LocalHit[]; translated: string | null } {
  const trimmed = query.trim();
  if (!trimmed) return { hits: [], translated: null };

  const indicators: LocalHit[] = [];
  const qLower = trimmed.toLowerCase();
  for (const ind of reg.indicators) {
    const hay = `${ind.symbol} ${ind.name}`.toLowerCase();
    if (hay.includes(qLower)) {
      indicators.push({ symbol: ind.symbol, name: ind.name, group: ind.group, category: 'indicator' });
    }
  }

  const stocks: LocalHit[] = [];
  let translated: string | null = null;
  if (isKoreanQuery(trimmed)) {
    const n = normalize(trimmed);
    const exact: LocalHit[] = [];
    const prefix: LocalHit[] = [];
    for (const [alias, ticker] of Object.entries(reg.krAliases)) {
      const aliasNorm = normalize(alias);
      if (aliasNorm === n) {
        translated = ticker;
        exact.push({ symbol: ticker, name: alias, category: 'stock' });
      } else if (aliasNorm.startsWith(n)) {
        prefix.push({ symbol: ticker, name: alias, category: 'stock' });
      }
    }
    prefix.sort((a, b) => a.name.localeCompare(b.name));
    stocks.push(...exact, ...prefix);
  }

  return {
    hits: [...indicators, ...stocks].slice(0, limit),
    translated,
  };
}
