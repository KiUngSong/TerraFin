import { useEffect, useState } from 'react';

export interface IndicatorEntry {
  symbol: string;
  name: string;
  group: string;
}

export interface TickerRegistry {
  krAliases: Record<string, string>;
  indicators: IndicatorEntry[];
  // Pre-normalized once on load — never serialized to sessionStorage.
  normAliases: Array<{ norm: string; ticker: string; display: string }>;
  normIndicators: Array<{ hay: string; symbol: string; name: string; group: string }>;
}

const CACHE_KEY = 'tf-ticker-registry';
let verifiedMemo: TickerRegistry | null = null;
let inflight: Promise<TickerRegistry> | null = null;
let fetchFailCount = 0;
const MAX_FETCH_ATTEMPTS = 3;

function normalize(s: string): string {
  return s.trim().toLowerCase().replace(/\s+/g, '');
}

function buildRegistry(data: { kr_aliases?: Record<string, string>; indicators?: IndicatorEntry[] }): TickerRegistry {
  const krAliases = data.kr_aliases || {};
  const indicators = data.indicators || [];
  return {
    krAliases,
    indicators,
    normAliases: Object.entries(krAliases).map(([display, ticker]) => ({
      norm: normalize(display),
      ticker,
      display,
    })),
    normIndicators: indicators.map((ind) => ({
      hay: `${ind.symbol} ${ind.name}`.toLowerCase(),
      symbol: ind.symbol,
      name: ind.name,
      group: ind.group,
    })),
  };
}

function _isValidRegistryPayload(parsed: unknown): parsed is { kr_aliases: Record<string, string>; indicators: IndicatorEntry[] } {
  if (!parsed || typeof parsed !== 'object') return false;
  const p = parsed as Record<string, unknown>;
  return typeof p.kr_aliases === 'object' && p.kr_aliases !== null &&
    Object.keys(p.kr_aliases as object).length > 0 &&
    Array.isArray(p.indicators);
}

function readCache(): TickerRegistry | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (_isValidRegistryPayload(parsed)) {
      return buildRegistry(parsed);
    }
  } catch {
    // ignore
  }
  return null;
}

async function fetchRegistry(): Promise<TickerRegistry> {
  if (verifiedMemo) return verifiedMemo;
  if (inflight) return inflight;
  if (fetchFailCount >= MAX_FETCH_ATTEMPTS) throw new Error('registry fetch failed after max attempts');
  inflight = (async () => {
    const resp = await fetch('/api/ticker-search/registry');
    if (!resp.ok) throw new Error(`registry ${resp.status}`);
    const data = await resp.json();
    if (!_isValidRegistryPayload(data)) throw new Error('registry payload empty or invalid');
    const reg = buildRegistry(data);
    verifiedMemo = reg;
    fetchFailCount = 0;
    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(data)); } catch { /* ignore */ }
    return reg;
  })().catch((err) => {
    fetchFailCount++;
    throw err;
  }).finally(() => { inflight = null; });
  return inflight;
}

export function useTickerRegistry(): TickerRegistry | null {
  const [reg, setReg] = useState<TickerRegistry | null>(() => readCache());

  useEffect(() => {
    let cancelled = false;
    fetchRegistry()
      .then((r) => { if (!cancelled) setReg(r); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return reg;
}

const HANGUL_RE = /[가-힣]/;

export function isKoreanQuery(q: string): boolean {
  return HANGUL_RE.test(q);
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
  for (const ind of reg.normIndicators) {
    if (ind.hay.includes(qLower)) {
      indicators.push({ symbol: ind.symbol, name: ind.name, group: ind.group, category: 'indicator' });
    }
  }

  const stocks: LocalHit[] = [];
  let translated: string | null = null;
  if (isKoreanQuery(trimmed)) {
    const n = normalize(trimmed);
    const exact: LocalHit[] = [];
    const prefix: LocalHit[] = [];
    const substring: LocalHit[] = [];
    const allowSubstring = n.length >= 2;
    for (const { norm: aliasNorm, ticker, display: alias } of reg.normAliases) {
      if (aliasNorm === n) {
        translated = ticker;
        exact.push({ symbol: ticker, name: alias, category: 'stock' });
      } else if (aliasNorm.startsWith(n)) {
        prefix.push({ symbol: ticker, name: alias, category: 'stock' });
      } else if (allowSubstring && aliasNorm.includes(n)) {
        substring.push({ symbol: ticker, name: alias, category: 'stock' });
      }
    }
    prefix.sort((a, b) => a.name.localeCompare(b.name));
    substring.sort((a, b) => a.name.localeCompare(b.name));
    const seenSymbols = new Set<string>();
    for (const hit of [...exact, ...prefix, ...substring]) {
      if (!seenSymbols.has(hit.symbol)) {
        seenSymbols.add(hit.symbol);
        stocks.push(hit);
      }
    }
  }

  return {
    hits: [...indicators, ...stocks].slice(0, limit),
    translated,
  };
}
