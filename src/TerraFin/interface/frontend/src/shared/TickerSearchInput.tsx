import React, { useEffect, useMemo, useRef, useState } from 'react';
import { isKoreanQuery, localPrefixMatch, useTickerRegistry, type LocalHit } from './useTickerRegistry';

interface SearchHit extends LocalHit {
  type?: string;
}

interface YahooStock {
  symbol: string;
  name: string;
  exchange: string;
  type: string;
}

export interface TickerSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onSelect: (hit: SearchHit) => void;
  onSubmit?: () => void;
  placeholder?: string;
  disabled?: boolean;
  ariaLabel?: string;
  inputStyle?: React.CSSProperties;
}

const DEBOUNCE_MS = 200;

interface BackendIndicator {
  symbol: string;
  name: string;
  group: string;
}

const TickerSearchInput: React.FC<TickerSearchInputProps> = ({
  value, onChange, onSelect, onSubmit, placeholder, disabled, ariaLabel, inputStyle,
}) => {
  const registry = useTickerRegistry();
  const [yahooStocks, setYahooStocks] = useState<YahooStock[]>([]);
  const [backendIndicators, setBackendIndicators] = useState<BackendIndicator[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const reqIdRef = useRef(0);

  // Local-first matches (no network)
  const local = useMemo(() => {
    if (!registry) return { hits: [] as LocalHit[], translated: null as string | null };
    return localPrefixMatch(value, registry, 8);
  }, [value, registry]);

  // Backend search for stocks (Yahoo proxy) and indicators not yet in local registry
  useEffect(() => {
    const q = value.trim();
    if (!q || isKoreanQuery(q)) {
      setYahooStocks([]);
      setBackendIndicators([]);
      return;
    }
    const myId = ++reqIdRef.current;
    const timer = setTimeout(async () => {
      try {
        const resp = await fetch(`/api/ticker-search?q=${encodeURIComponent(q)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (myId !== reqIdRef.current) return;
        setYahooStocks(data.stocks || []);
        setBackendIndicators(data.indicators || []);
      } catch {
        // ignore
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [value]);

  // Reset highlight on hits change
  useEffect(() => {
    setActiveIdx(-1);
  }, [value]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const hits: SearchHit[] = useMemo(() => {
    const known = new Set(local.hits.map((h) => h.symbol));
    // Merge backend indicators not already present in local registry hits
    const remoteInds: SearchHit[] = backendIndicators
      .filter((i) => !known.has(i.symbol))
      .map((i) => ({ symbol: i.symbol, name: i.name, group: i.group, category: 'indicator' as const }));
    remoteInds.forEach((i) => known.add(i.symbol));
    const yahooHits: SearchHit[] = yahooStocks
      .filter((s) => !known.has(s.symbol))
      .map((s) => ({ symbol: s.symbol, name: s.name, exchange: s.exchange, type: s.type, category: 'stock' as const }));
    return [...local.hits, ...remoteInds, ...yahooHits];
  }, [local.hits, backendIndicators, yahooStocks]);

  const handleSelect = (hit: SearchHit) => {
    onSelect(hit);
    setOpen(false);
  };

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (hits.length === 0) return;
      setOpen(true);
      setActiveIdx((idx) => (idx + 1) % hits.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (hits.length === 0) return;
      setOpen(true);
      setActiveIdx((idx) => (idx <= 0 ? hits.length - 1 : idx - 1));
    } else if (e.key === 'Enter') {
      if (open && activeIdx >= 0 && hits[activeIdx]) {
        e.preventDefault();
        handleSelect(hits[activeIdx]);
      } else if (hits.length > 0) {
        const top = hits[0];
        if (local.translated || top.symbol.toLowerCase() !== value.trim().toLowerCase()) {
          e.preventDefault();
          handleSelect(top);
          return;
        }
        if (onSubmit) onSubmit();
      } else if (onSubmit) {
        onSubmit();
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div ref={wrapperRef} style={{ position: 'relative', width: '100%' }}>
      <input
        type="text"
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => { if (hits.length > 0) setOpen(true); }}
        onKeyDown={handleKey}
        placeholder={placeholder}
        aria-label={ariaLabel}
        disabled={disabled}
        autoComplete="off"
        style={inputStyle}
      />
      {open && hits.length > 0 && (
        <ul style={dropdownStyle}>
          {local.translated && (
            <li style={translatedRowStyle}>
              한국어 → <strong>{local.translated}</strong>
            </li>
          )}
          {renderGrouped(hits, activeIdx, handleSelect)}
        </ul>
      )}
    </div>
  );
};

function renderGrouped(
  hits: SearchHit[],
  activeIdx: number,
  onSelect: (h: SearchHit) => void,
) {
  const indicators = hits.filter((h) => h.category === 'indicator');
  const stocks = hits.filter((h) => h.category === 'stock');
  const out: React.ReactNode[] = [];
  let idx = 0;
  if (indicators.length > 0) {
    out.push(<li key="hdr-i" style={headerStyle}>지표 / Indicators</li>);
    indicators.forEach((h) => {
      const i = idx++;
      out.push(
        <li key={`i-${h.symbol}`}>
          <button type="button" onMouseDown={(e) => { e.preventDefault(); onSelect(h); }} style={itemStyle(i === activeIdx)}>
            <span style={{ fontWeight: 600 }}>{h.symbol}</span>
            {h.name && h.name !== h.symbol && <span style={nameStyle}>{h.name}</span>}
            {h.group && <span style={badgeStyle}>{h.group}</span>}
          </button>
        </li>,
      );
    });
  }
  if (stocks.length > 0) {
    out.push(<li key="hdr-s" style={headerStyle}>종목 / Stocks</li>);
    stocks.forEach((h) => {
      const i = idx++;
      out.push(
        <li key={`s-${h.symbol}`}>
          <button type="button" onMouseDown={(e) => { e.preventDefault(); onSelect(h); }} style={itemStyle(i === activeIdx)}>
            <span style={{ fontWeight: 600 }}>{h.symbol}</span>
            <span style={nameStyle}>{h.name}</span>
            {h.exchange && <span style={badgeStyle}>{h.exchange}</span>}
          </button>
        </li>,
      );
    });
  }
  return out;
}

const dropdownStyle: React.CSSProperties = {
  position: 'absolute',
  top: 'calc(100% + 4px)',
  left: 0,
  right: 0,
  background: '#ffffff',
  border: '1px solid #cbd5e1',
  borderRadius: 10,
  margin: 0,
  padding: 4,
  listStyle: 'none',
  boxShadow: '0 8px 20px rgba(15, 23, 42, 0.10)',
  maxHeight: 320,
  overflowY: 'auto',
  zIndex: 50,
};

const headerStyle: React.CSSProperties = {
  padding: '6px 10px 4px',
  fontSize: 10,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: '#94a3b8',
};

const itemStyle = (active: boolean): React.CSSProperties => ({
  width: '100%',
  textAlign: 'left',
  padding: '8px 10px',
  fontSize: 13,
  border: 'none',
  borderRadius: 6,
  background: active ? '#eff6ff' : 'transparent',
  color: '#0f172a',
  cursor: 'pointer',
  outline: 'none',
  display: 'flex',
  alignItems: 'center',
  gap: 8,
});

const nameStyle: React.CSSProperties = {
  color: '#475569',
  fontSize: 12,
  flex: 1,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
};

const badgeStyle: React.CSSProperties = {
  fontSize: 10,
  color: '#64748b',
  background: '#f1f5f9',
  padding: '2px 6px',
  borderRadius: 4,
};

const translatedRowStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 11,
  color: '#475569',
  background: '#f8fafc',
  borderRadius: 6,
  marginBottom: 4,
};

export default TickerSearchInput;
