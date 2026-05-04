import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { chartRequest, getChartSessionId } from '../../chart/api';
import ChartComponent, { type ChartComponentHandle } from '../../chart/ChartComponent';
import { CHART_API_BASE, type ChartScaleMargins } from '../../chart/constants';
import type {
  ChartHistoryBySeries,
  ChartMutation,
  ChartPayload,
  ChartSeries,
  ChartSeriesEntry,
  ChartSnapshot,
} from '../../chart/types';
import { applyMutationToPayload } from '../../chart/updateUtils';

const QUICK_PICKS = [
  { name: 'S&P 500', label: 'S&P 500' },
  { name: 'Dow', label: 'Dow' },
  { name: 'Nasdaq', label: 'Nasdaq' },
  { name: 'Shanghai Composite', label: 'Shanghai Composite' },
  { name: 'Nikkei 225', label: 'Nikkei' },
  { name: 'Kospi', label: 'Kospi' },
  { name: 'Kosdaq', label: 'Kosdaq' },
  { name: 'SPX GEX', label: 'SPX GEX' },
];
const QUICK_PICK_NAMES = QUICK_PICKS.map((pick) => pick.name);
const QUICK_PICK_META: Record<string, { type: string; description: string }> = {
  'S&P 500': { type: 'index', description: 'Benchmark U.S. large-cap equity index.' },
  Dow: { type: 'index', description: 'Price-weighted U.S. blue-chip equity index.' },
  Nasdaq: { type: 'index', description: 'Technology-heavy U.S. equity index.' },
  'Shanghai Composite': {
    type: 'index',
    description: 'Broad mainland China equity benchmark tracking the Shanghai market.',
  },
  'Nikkei 225': { type: 'index', description: 'Price-weighted Japanese large-cap equity index.' },
  Kospi: { type: 'index', description: 'Benchmark South Korean large-cap equity index.' },
  Kosdaq: { type: 'index', description: 'South Korean growth and technology-focused equity index.' },
  'SPX GEX': {
    type: 'options',
    description:
      'Dealer net gamma positioning (SqueezeMetrics, 2011–present). Negative = short gamma — dealers amplify moves. SqueezeMetrics estimates GEX from dark pool volume; CBOE snapshot calculates from open interest — expect divergence.',
  },
};
const MACRO_CHART_COMPACT_BREAKPOINT = 860;
const MACRO_CHART_SCALE_MARGINS: ChartScaleMargins = { top: 0.04, bottom: 0.04 };

interface MacroInstrumentInfo {
  name: string;
  type: string;
  description: string;
  currentValue: number | null;
  change: number | null;
  changePercent: number | null;
}

interface ProgressiveSetResponse {
  ok: boolean;
  error?: string;
  mode: 'multi';
  series: ChartSnapshot['payload']['series'];
  dataLength: number;
  forcePercentage?: boolean;
  entries: ChartSeriesEntry[];
  historyBySeries?: ChartHistoryBySeries;
}

function needsMacroInfoHydration(info: MacroInstrumentInfo | null | undefined): boolean {
  return !info || !info.description.trim();
}

function nextQuickPickFocus(
  currentTicker: string,
  removedName: string,
  entries: ChartSeriesEntry[]
): string | null {
  const selectedNames = QUICK_PICK_NAMES.filter((name) =>
    entries.some((entry) => entry.name === name)
  );
  const selectedSet = new Set(selectedNames);
  if (removedName !== currentTicker && selectedSet.has(currentTicker)) {
    return currentTicker;
  }
  return selectedNames.find((name) => name !== removedName) ?? null;
}

function numericSeriesValues(series: ChartSeries): number[] {
  return (series.data ?? [])
    .map((point) => {
      if ('close' in point && typeof point.close === 'number') {
        return point.close;
      }
      if ('value' in point && typeof point.value === 'number') {
        return point.value;
      }
      return null;
    })
    .filter((value): value is number => value != null);
}

function buildLocalMacroInfo(
  name: string,
  series: ChartSeries,
  fallback?: MacroInstrumentInfo | null
): MacroInstrumentInfo | null {
  const values = numericSeriesValues(series);
  if (values.length === 0) {
    return fallback ?? null;
  }
  const currentValue = values[values.length - 1] ?? null;
  const previousValue = values.length > 1 ? values[values.length - 2] : null;
  const change =
    currentValue != null && previousValue != null ? currentValue - previousValue : null;
  const changePercent =
    change != null && previousValue != null && previousValue !== 0
      ? (change / previousValue) * 100
      : null;
  const meta = QUICK_PICK_META[name];
  return {
    name,
    type: fallback?.type ?? meta?.type ?? 'index',
    description: fallback?.description ?? meta?.description ?? '',
    currentValue,
    change,
    changePercent,
  };
}

function toSnapshotFromSetResponse(payload: ProgressiveSetResponse): ChartSnapshot {
  return {
    payload: {
      mode: payload.mode,
      series: payload.series,
      dataLength: payload.dataLength,
      forcePercentage: payload.forcePercentage === true,
    },
    entries: payload.entries || [],
  };
}

function findPrimarySeries(payload: ChartPayload, name: string): ChartSeries | null {
  const primarySeries = (payload.series ?? []).filter((series) => !series.indicator);
  return (
    primarySeries.find((series) => series.id === name) ??
    primarySeries[0] ??
    null
  );
}

const CHART_PLACEHOLDER_STYLE: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 13,
  color: '#475569',
  background:
    'linear-gradient(180deg, rgba(248,250,252,0.96) 0%, rgba(255,255,255,0.98) 100%)',
};

interface MacroFocusPanelProps {
  onReadyChange?: (ready: boolean) => void;
}

const MacroFocusPanel: React.FC<MacroFocusPanelProps> = ({ onReadyChange }) => {
  const initialTickerRef = useRef<string>(
    (() => {
      const queryTicker = new URLSearchParams(window.location.search).get('ticker');
      if (queryTicker && queryTicker.trim()) {
        return queryTicker.trim();
      }
      return QUICK_PICKS[0].name;
    })()
  );
  const [ticker, setTicker] = useState(initialTickerRef.current);
  const sessionIdRef = useRef(getChartSessionId('market-insights'));
  const chartComponentRef = useRef<ChartComponentHandle | null>(null);
  const [info, setInfo] = useState<MacroInstrumentInfo | null>(null);
  const [chartSnapshot, setChartSnapshot] = useState<ChartSnapshot | null>(null);
  const [chartEntries, setChartEntries] = useState<ChartSeriesEntry[]>([]);
  const [initialHistoryBySeries, setInitialHistoryBySeries] = useState<ChartHistoryBySeries>({});
  const [pendingRequestCount, setPendingRequestCount] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const infoCacheRef = useRef<Map<string, MacroInstrumentInfo>>(new Map());
  const seedControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);
  const onReadyChangeRef = useRef(onReadyChange);
  const tickerRef = useRef(ticker);
  const selectedQuickPickNames = useMemo(
    () => QUICK_PICK_NAMES.filter((name) => chartEntries.some((entry) => entry.name === name)),
    [chartEntries]
  );
  const selectedQuickPickSet = useMemo(
    () => new Set(selectedQuickPickNames),
    [selectedQuickPickNames]
  );

  const parseError = useCallback(async (response: Response): Promise<string> => {
    try {
      const payload = await response.json();
      const detail = payload?.detail;
      if (typeof detail === 'string' && detail.trim()) {
        return detail;
      }
    } catch (_error) {
      // Fall back to a generic status-based message when the body is not JSON.
    }
    return `Request failed (${response.status})`;
  }, []);

  const requestMacroInfo = useCallback(async (
    name: string,
    signal?: AbortSignal
  ): Promise<MacroInstrumentInfo | null> => {
    try {
      const response = await chartRequest(
        `/market-insights/api/macro-info?name=${encodeURIComponent(name)}`,
        sessionIdRef.current,
        { signal }
      );
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      const payload = (await response.json()) as MacroInstrumentInfo;
      infoCacheRef.current.set(payload.name, payload);
      return payload;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        throw error;
      }
      return null;
    }
  }, [parseError]);

  const syncFocusedInfo = useCallback(async (name: string): Promise<void> => {
    try {
      const payload = await requestMacroInfo(name);
      if (payload && tickerRef.current === payload.name) {
        setInfo(payload);
      }
    } catch {
      // Best-effort background sync only.
    }
  }, [requestMacroInfo]);

  const handleChartEntriesChange = useCallback((nextEntries: ChartSeriesEntry[]) => {
    setChartEntries(nextEntries);
    if (nextEntries.some((entry) => entry.name === tickerRef.current)) {
      return;
    }

    const nextQuickPick = QUICK_PICK_NAMES.find((name) =>
      nextEntries.some((entry) => entry.name === name)
    );
    if (nextQuickPick) {
      setTicker(nextQuickPick);
      const cached = infoCacheRef.current.get(nextQuickPick) ?? null;
      setInfo(cached);
      if (needsMacroInfoHydration(cached)) {
        void syncFocusedInfo(nextQuickPick);
      }
      return;
    }

    const nextFocusedName = nextEntries[0]?.name ?? null;
    if (nextFocusedName) {
      setTicker(nextFocusedName);
      const cached = infoCacheRef.current.get(nextFocusedName) ?? null;
      setInfo(cached);
      if (needsMacroInfoHydration(cached)) {
        void syncFocusedInfo(nextFocusedName);
      }
      return;
    }

    setInfo(null);
  }, [syncFocusedInfo]);

  useEffect(() => {
    onReadyChangeRef.current = onReadyChange;
  }, [onReadyChange]);

  useEffect(() => {
    tickerRef.current = ticker;
  }, [ticker]);

  useEffect(() => () => {
    isMountedRef.current = false;
    seedControllerRef.current?.abort();
  }, []);

  const beginPendingRequest = useCallback(() => {
    setPendingRequestCount((current) => current + 1);
  }, []);

  const endPendingRequest = useCallback(() => {
    setPendingRequestCount((current) => Math.max(0, current - 1));
  }, []);

  const applyMacroMutation = useCallback((mutation: ChartMutation, nextHistoryBySeries?: ChartHistoryBySeries | null) => {
    if (mutation.entries && !chartComponentRef.current) {
      setChartEntries(mutation.entries);
    }
    if (chartComponentRef.current) {
      chartComponentRef.current.applyExternalMutation(mutation, nextHistoryBySeries ?? null);
      return;
    }
    if (nextHistoryBySeries) {
      setInitialHistoryBySeries(nextHistoryBySeries);
    }
    setChartSnapshot((current) => {
      if (!current) {
        return current;
      }
      return {
        payload: applyMutationToPayload(current.payload, mutation),
        entries: mutation.entries ?? current.entries,
      };
    });
  }, []);

  const seedMacro = useCallback(async (name: string) => {
    seedControllerRef.current?.abort();
    const controller = new AbortController();
    seedControllerRef.current = controller;
    beginPendingRequest();
    setLoadError(null);
    onReadyChangeRef.current?.(false);

    const cachedInfo = infoCacheRef.current.get(name);
    if (cachedInfo) {
      setInfo(cachedInfo);
    }

    try {
      const response = await chartRequest(`${CHART_API_BASE}/chart-series/progressive/set`, sessionIdRef.current, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, pinned: false, seedPeriod: '3y' }),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(await parseError(response));
      }
      const payload = (await response.json()) as ProgressiveSetResponse;
      if (!payload.ok) {
        throw new Error(payload.error || 'Failed to load macro data.');
      }
      if (!isMountedRef.current || controller.signal.aborted) {
        return;
      }

      const nextSnapshot = toSnapshotFromSetResponse(payload);
      const seededName = nextSnapshot.entries[0]?.name ?? name;
      const primarySeries = findPrimarySeries(nextSnapshot.payload, seededName);
      const localInfo = primarySeries
        ? buildLocalMacroInfo(seededName, primarySeries, infoCacheRef.current.get(seededName) ?? cachedInfo ?? null)
        : infoCacheRef.current.get(seededName) ?? cachedInfo ?? null;

      setTicker(seededName);
      setChartSnapshot(nextSnapshot);
      setChartEntries(nextSnapshot.entries);
      setInitialHistoryBySeries(payload.historyBySeries ?? {});
      if (localInfo) {
        infoCacheRef.current.set(seededName, localInfo);
        setInfo(localInfo);
      } else if (cachedInfo) {
        setInfo(cachedInfo);
      }
      onReadyChangeRef.current?.(true);

      if (needsMacroInfoHydration(localInfo)) {
        const fetchedInfo = await requestMacroInfo(seededName, controller.signal);
        if (!isMountedRef.current || controller.signal.aborted || !fetchedInfo) {
          return;
        }
        if (seededName === fetchedInfo.name && tickerRef.current === seededName) {
          setInfo(fetchedInfo);
        }
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
      if (!isMountedRef.current) return;
      setLoadError(error instanceof Error ? error.message : 'Failed to load macro data.');
      onReadyChangeRef.current?.(false);
    } finally {
      if (seedControllerRef.current === controller) {
        seedControllerRef.current = null;
      }
      if (isMountedRef.current) {
        endPendingRequest();
      }
    }
  }, [beginPendingRequest, endPendingRequest, parseError, requestMacroInfo]);

  const addMacro = useCallback(async (name: string) => {
    setLoadError(null);
    const cachedInfo = infoCacheRef.current.get(name);
    if (cachedInfo) {
      setInfo(cachedInfo);
    }
    beginPendingRequest();
    await chartRequest(`${CHART_API_BASE}/chart-series/add`, sessionIdRef.current, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, pinned: false }),
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await parseError(response));
        }

        const payload = (await response.json()) as {
          ok: boolean;
          error?: string;
          mutation?: ChartMutation;
          historyBySeries?: ChartHistoryBySeries;
        };
        if (!isMountedRef.current) {
          return;
        }
        if (!payload.ok || !payload.mutation) {
          throw new Error(payload.error || 'Failed to load macro data.');
        }
        applyMacroMutation(payload.mutation, payload.historyBySeries ?? {});
        const addedSeries = payload.mutation.upsertSeries.find((series) => series.id === name);
        const nextInfo =
          (addedSeries ? buildLocalMacroInfo(name, addedSeries, cachedInfo) : null) ?? cachedInfo ?? null;
        if (nextInfo) {
          infoCacheRef.current.set(name, nextInfo);
          if (tickerRef.current === name) {
            setInfo(nextInfo);
          }
        }
        if (needsMacroInfoHydration(nextInfo)) {
          void requestMacroInfo(name).then((fetchedInfo) => {
            if (!fetchedInfo || !isMountedRef.current) {
              return;
            }
            if (tickerRef.current === fetchedInfo.name) {
              setInfo(fetchedInfo);
            }
          });
        }
      })
      .catch((error) => {
        if (!isMountedRef.current) return;
        setLoadError(error instanceof Error ? error.message : 'Failed to load macro data.');
      })
      .finally(() => {
        if (isMountedRef.current) {
          endPendingRequest();
        }
      });
  }, [applyMacroMutation, beginPendingRequest, endPendingRequest, parseError, requestMacroInfo]);

  const removeMacro = useCallback(async (name: string) => {
    setLoadError(null);
    if (chartComponentRef.current) {
      beginPendingRequest();
      try {
        const previousTicker = tickerRef.current;
        const result = await chartComponentRef.current.removeSeries(name);
        const activeName = nextQuickPickFocus(previousTicker, name, result.entries);
        if (activeName) {
          setTicker(activeName);
          const cachedInfo = infoCacheRef.current.get(activeName);
          setInfo(cachedInfo ?? null);
          if (needsMacroInfoHydration(cachedInfo)) {
            void syncFocusedInfo(activeName);
          }
        } else {
          setInfo(null);
        }
        if (!result.ok) {
          setLoadError(result.error || 'Failed to update chart.');
        }
      } finally {
        if (isMountedRef.current) {
          endPendingRequest();
        }
      }
      return null;
    }
    beginPendingRequest();
    return chartRequest(`${CHART_API_BASE}/chart-series/remove`, sessionIdRef.current, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await parseError(response));
        }
        const payload = (await response.json()) as {
          ok: boolean;
          mutation?: ChartMutation;
          historyBySeries?: ChartHistoryBySeries;
        };
        if (!isMountedRef.current) {
          return null;
        }
        if (!payload.ok || !payload.mutation) {
          throw new Error('Failed to update chart.');
        }
        const nextEntries = payload.mutation.entries ?? [];
        setChartEntries(nextEntries);
        applyMacroMutation(payload.mutation, payload.historyBySeries ?? {});
        const activeName = nextQuickPickFocus(tickerRef.current, name, nextEntries);
        if (activeName) {
          setTicker(activeName);
          const cachedInfo = infoCacheRef.current.get(activeName);
          setInfo(cachedInfo ?? null);
          if (needsMacroInfoHydration(cachedInfo)) {
            void syncFocusedInfo(activeName);
          }
        } else {
          setInfo(null);
        }
        return null;
      })
      .catch((error) => {
        if (!isMountedRef.current) return null;
        setLoadError(error instanceof Error ? error.message : 'Failed to update chart.');
        return null;
      })
      .finally(() => {
        if (isMountedRef.current) {
          endPendingRequest();
        }
      });
  }, [applyMacroMutation, beginPendingRequest, endPendingRequest, parseError, syncFocusedInfo]);

  useEffect(() => {
    void seedMacro(initialTickerRef.current);
  }, [seedMacro]);

  useEffect(() => {
    if (selectedQuickPickNames.length === 0 || selectedQuickPickSet.has(ticker)) {
      return;
    }
    const fallback = selectedQuickPickNames[0];
    setTicker(fallback);
    const cachedInfo = infoCacheRef.current.get(fallback);
    setInfo(cachedInfo ?? null);
    if (needsMacroInfoHydration(cachedInfo)) {
      void syncFocusedInfo(fallback);
    }
  }, [selectedQuickPickNames, selectedQuickPickSet, syncFocusedInfo, ticker]);

  const handleQuickPick = useCallback((name: string) => {
    if (pendingRequestCount > 0 && chartSnapshot) {
      return;
    }
    if (selectedQuickPickSet.has(name)) {
      void removeMacro(name);
      return;
    }
    setTicker(name);
    if (chartSnapshot) {
      void addMacro(name);
      return;
    }
    void seedMacro(name);
  }, [
    addMacro,
    chartSnapshot,
    pendingRequestCount,
    removeMacro,
    seedMacro,
    selectedQuickPickSet,
  ]);

  const changeColor = (info?.changePercent ?? 0) >= 0 ? '#047857' : '#b91c1c';
  const changeSign = (info?.changePercent ?? 0) >= 0 ? '+' : '';
  const isLoading = pendingRequestCount > 0;

  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
        {QUICK_PICKS.map((p) => (
          <button
            key={p.name}
            type="button"
            disabled={isLoading && !!chartSnapshot}
            onClick={() => handleQuickPick(p.name)}
            style={{
              border: '1px solid ' + (selectedQuickPickSet.has(p.name) ? '#93c5fd' : '#e2e8f0'),
              borderRadius: 999,
              padding: '3px 10px',
              fontSize: 11,
              fontWeight: 600,
              background: selectedQuickPickSet.has(p.name) ? '#dbeafe' : '#fff',
              color: selectedQuickPickSet.has(p.name) ? '#1e3a8a' : '#475569',
              cursor: isLoading && chartSnapshot ? 'default' : 'pointer',
              opacity: isLoading && chartSnapshot ? 0.65 : 1,
            }}
          >
            {p.label}
          </button>
        ))}
      </div>

      {info && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 16, fontWeight: 800, color: '#0f172a' }}>{info.name}</span>
            {info.currentValue != null && (
              <span style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>
                {info.currentValue.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </span>
            )}
            {info.changePercent != null && (
              <span style={{ fontSize: 12, fontWeight: 600, color: changeColor }}>
                {changeSign}{info.changePercent.toFixed(2)}%
              </span>
            )}
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              color: '#475569',
              background: '#f1f5f9',
              borderRadius: 999,
              padding: '2px 8px',
              border: '1px solid #e2e8f0',
              textTransform: 'uppercase',
            }}>
              {info.type}
            </span>
          </div>
          {info.description && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{info.description}</div>
          )}
        </div>
      )}

      <div
        style={{
          height: 480,
          position: 'relative',
          border: '1px solid #e2e8f0',
          borderRadius: 12,
          overflow: 'hidden',
          background: '#ffffff',
        }}
      >
        {chartSnapshot ? (
          <ChartComponent
            ref={chartComponentRef}
            sessionId={sessionIdRef.current}
            initialPayload={chartSnapshot.payload}
            initialEntries={chartSnapshot.entries}
            pollingEnabled={false}
            initialHistoryBySeries={initialHistoryBySeries}
            onEntriesChange={handleChartEntriesChange}
            compactBreakpoint={MACRO_CHART_COMPACT_BREAKPOINT}
            priceScaleMargins={MACRO_CHART_SCALE_MARGINS}
          />
        ) : (
          <div style={{ ...CHART_PLACEHOLDER_STYLE, color: loadError ? '#b91c1c' : '#475569' }}>
            {loadError ?? 'Loading chart...'}
          </div>
        )}

        {isLoading && chartSnapshot ? (
          <div
            style={{
              position: 'absolute',
              top: 10,
              right: 10,
              padding: '4px 8px',
              borderRadius: 999,
              fontSize: 11,
              fontWeight: 700,
              color: '#334155',
              background: 'rgba(255,255,255,0.9)',
              border: '1px solid #e2e8f0',
            }}
          >
            Refreshing...
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default MacroFocusPanel;
