import React, { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { chartRequest } from './api';
import BottomBar from './BottomBar';
import ChartCanvas from './ChartCanvas';
import {
  CHART_API_BASE,
  DEFAULT_CHART_COMPACT_BREAKPOINT,
  DEFAULT_PRICE_SCALE_MARGINS,
  FONT_FAMILY,
  RANGE_BUTTONS,
  type RangeAvailability,
  type ChartScaleMargins,
} from './constants';
import type { RangeId } from './constants';
import TopBar from './TopBar';
import { useChartData } from './useChartData';
import DateSelector, { type DateSelectionRequest } from './utils/DateSelector';
import type { IndicatorOption } from './utils/IndicatorSelector';
import type { SeriesTag } from './BottomBar';
import RiskAnalyticsPanel from './utils/RiskAnalyticsPanel';
import type {
  ChartHistoryBySeries,
  ChartMutation,
  ChartPayload,
  ChartSeriesEntry,
  ChartSnapshot,
  ChartUpdate,
  SeriesHistoryStatus,
} from './types';
import { isChartMutation } from './updateUtils';
import { getResponsiveTier } from '../shared/responsive';

const DEFAULT_INDICATORS = new Set(['ma-20', 'ma-60', 'ma-120']);
const MAX_CHART_SERIES = 5;
const EMPTY_HISTORY_BY_SERIES: ChartHistoryBySeries = {};
const MAX_CONCURRENT_BACKFILLS = 1;
const BACKFILL_DEFER_MS = 600;

interface ChartComponentProps {
  sessionId: string;
  initialPayload?: ChartPayload | null;
  initialEntries?: ChartSeriesEntry[];
  pollingEnabled?: boolean;
  initialHistoryBySeries?: ChartHistoryBySeries;
  onEntriesChange?: (entries: ChartSeriesEntry[]) => void;
  canRemoveSeries?: (name: string, entries: ChartSeriesEntry[]) => boolean;
  onRemoveSeries?: (
    name: string,
    entries: ChartSeriesEntry[]
  ) => ChartUpdate | null | void | Promise<ChartUpdate | null | void>;
  compactBreakpoint?: number;
  priceScaleMargins?: ChartScaleMargins;
}

export interface ChartComponentHandle {
  applyExternalMutation: (mutation: ChartMutation | null, historyBySeries?: ChartHistoryBySeries | null) => void;
  applyExternalSnapshot: (snapshot: ChartSnapshot | null) => void;
  refresh: () => void;
  removeSeries: (name: string) => Promise<RemoveSeriesResult>;
}

export interface RemoveSeriesResult {
  ok: boolean;
  entries: ChartSeriesEntry[];
  historyBySeries: ChartHistoryBySeries;
  error?: string | null;
}

function subtractMonths(dateString: string, months: number): Date {
  const date = new Date(dateString);
  date.setMonth(date.getMonth() - months);
  return date;
}

function hasLoadedMonths(status: SeriesHistoryStatus, months: number): boolean {
  if (!status.loadedStart || !status.loadedEnd) return false;
  const loadedStart = new Date(status.loadedStart);
  const requiredStart = subtractMonths(status.loadedEnd, months);
  return loadedStart.getTime() <= requiredStart.getTime();
}

function pruneSeriesHistory(history: ChartHistoryBySeries, name: string): ChartHistoryBySeries {
  if (!(name in history)) {
    return history;
  }
  const next = { ...history };
  delete next[name];
  return next;
}

const ChartComponentInner = React.forwardRef<ChartComponentHandle, ChartComponentProps>(({
  sessionId,
  initialPayload = null,
  initialEntries = [],
  pollingEnabled = true,
  initialHistoryBySeries,
  onEntriesChange,
  canRemoveSeries,
  onRemoveSeries,
  compactBreakpoint = DEFAULT_CHART_COMPACT_BREAKPOINT,
  priceScaleMargins = DEFAULT_PRICE_SCALE_MARGINS,
}, ref) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const backfillControllersRef = useRef<Map<string, { controller: AbortController; token: string }>>(new Map());
  const backfillWakeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const deferBackfillsUntilRef = useRef(0);
  const entriesRef = useRef<ChartSeriesEntry[]>(initialEntries);
  const historyBySeriesRef = useRef<ChartHistoryBySeries>(initialHistoryBySeries ?? EMPTY_HISTORY_BY_SERIES);
  const [containerWidth, setContainerWidth] = useState(0);
  const [isNarrow, setIsNarrow] = useState(false);
  const [historyBySeries, setHistoryBySeries] = useState<ChartHistoryBySeries>(
    initialHistoryBySeries ?? EMPTY_HISTORY_BY_SERIES
  );
  const [backfillCycle, setBackfillCycle] = useState(0);

  const { payload, entries, historyBySeries: fetchedHistoryBySeries, error, fetchData, applySnapshot, applyMutation } = useChartData({
    sessionId,
    initialPayload,
    initialEntries,
    pollingEnabled,
  });
  const payloadReady = payload != null;

  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const check = () => {
      setContainerWidth(el.clientWidth);
      setIsNarrow(el.clientWidth < compactBreakpoint);
    };
    check();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(check);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, [compactBreakpoint, payloadReady]);
  const [activeView, setActiveView] = useState<string>('daily');
  const [selectedRange, setSelectedRange] = useState<RangeId | null>('1Y');
  const [priceScaleMode, setPriceScaleMode] = useState<number>(0);
  const [dateSelectorOpen, setDateSelectorOpen] = useState(false);
  const [dateSelectionRequest, setDateSelectionRequest] = useState<DateSelectionRequest>(null);
  const [selectedIndicators, setSelectedIndicators] = useState<Set<string>>(DEFAULT_INDICATORS);
  const [riskCloses, setRiskCloses] = useState<number[]>([]);
  const [riskAnalyticsOpen, setRiskAnalyticsOpen] = useState(false);
  const [visibleRange, setVisibleRange] = useState<{ from: string; to: string } | null>(null);

  const forcePercentage = payload?.forcePercentage === true;

  useEffect(() => {
    if (initialHistoryBySeries === undefined) {
      return;
    }
    setHistoryBySeries(initialHistoryBySeries);
  }, [initialHistoryBySeries]);

  useEffect(() => {
    entriesRef.current = entries;
  }, [entries]);

  useEffect(() => {
    historyBySeriesRef.current = historyBySeries;
  }, [historyBySeries]);

  useEffect(() => {
    if (initialHistoryBySeries !== undefined) {
      return;
    }
    setHistoryBySeries(fetchedHistoryBySeries);
  }, [fetchedHistoryBySeries, initialHistoryBySeries]);

  useEffect(() => {
    setHistoryBySeries((current) => {
      const activeNames = new Set(entries.map((entry) => entry.name));
      const nextEntries = Object.entries(current).filter(([name]) => activeNames.has(name));
      if (nextEntries.length === Object.keys(current).length) {
        return current;
      }
      return Object.fromEntries(nextEntries);
    });
  }, [entries]);

  const trackedHistoryStatuses = useMemo(
    () =>
      entries.flatMap((entry) => {
        const status = historyBySeries[entry.name];
        return status ? [{ name: entry.name, status }] : [];
      }),
    [entries, historyBySeries]
  );

  const rangeAvailability = useMemo<Partial<Record<RangeId, RangeAvailability>>>(() => {
    if (trackedHistoryStatuses.length === 0) return {};
    const unavailableTooltip = trackedHistoryStatuses.some(({ status }) => status.backfillInFlight)
      ? 'Loading older history...'
      : 'Older history is still loading';
    const availability: Partial<Record<RangeId, RangeAvailability>> = {};

    if (trackedHistoryStatuses.some(({ status }) => !(status.isComplete || hasLoadedMonths(status, 60)))) {
      availability['5Y'] = { disabled: true, tooltip: unavailableTooltip };
    }
    if (trackedHistoryStatuses.some(({ status }) => !status.isComplete)) {
      availability['ALL'] = { disabled: true, tooltip: unavailableTooltip };
    }
    return availability;
  }, [trackedHistoryStatuses]);

  const statusBadgeLabel = trackedHistoryStatuses.some(({ status }) => status.backfillInFlight)
    ? 'Loading older history...'
    : null;

  const buildOptimisticRemoveMutation = useCallback((name: string): ChartMutation | null => {
    if (!payload) {
      return null;
    }

    const removedSeriesIds = new Set<string>([name]);
    const remainingPrimarySeries = (payload.series ?? []).filter(
      (series) => !series.indicator && series.id !== name
    );
    const remainingCandlestickCount = remainingPrimarySeries.filter(
      (series) => series.seriesType === 'candlestick' || series.returnSeries === true
    ).length;

    if (remainingCandlestickCount !== 1) {
      for (const series of payload.series ?? []) {
        if (series.indicator) {
          removedSeriesIds.add(series.id);
        }
      }
    }

    const keptSeries = (payload.series ?? []).filter((series) => !removedSeriesIds.has(series.id));

    return {
      mode: payload.mode,
      upsertSeries: [],
      removedSeriesIds: Array.from(removedSeriesIds),
      seriesOrder: keptSeries.map((series) => series.id),
      dataLength: keptSeries.reduce((sum, series) => sum + (series.data?.length ?? 0), 0),
      forcePercentage: remainingCandlestickCount >= 3,
      entries: entries.filter((entry) => entry.name !== name),
    };
  }, [entries, payload]);

  const scheduleBackfillWake = useCallback((delayMs: number) => {
    if (backfillWakeTimerRef.current) {
      clearTimeout(backfillWakeTimerRef.current);
      backfillWakeTimerRef.current = null;
    }
    backfillWakeTimerRef.current = setTimeout(() => {
      backfillWakeTimerRef.current = null;
      setBackfillCycle((current) => current + 1);
    }, Math.max(0, delayMs));
  }, []);

  const pauseBackgroundBackfills = useCallback((delayMs = BACKFILL_DEFER_MS) => {
    deferBackfillsUntilRef.current = Date.now() + delayMs;
    for (const { controller } of Array.from(backfillControllersRef.current.values())) {
      controller.abort();
    }
    backfillControllersRef.current.clear();
    scheduleBackfillWake(delayMs);
  }, [scheduleBackfillWake]);

  useEffect(() => {
    onEntriesChange?.(entries);
  }, [entries, onEntriesChange]);

  const handleRemoveSeries = useCallback(async (name: string): Promise<RemoveSeriesResult> => {
    if (canRemoveSeries && !canRemoveSeries(name, entries)) {
      return {
        ok: false,
        entries,
        historyBySeries,
        error: 'Series cannot be removed.',
      };
    }
    pauseBackgroundBackfills();

    const activeBackfill = backfillControllersRef.current.get(name);
    if (activeBackfill) {
      activeBackfill.controller.abort();
      backfillControllersRef.current.delete(name);
    }

    const previousPayload = payload;
    const previousEntries = entries;
    const previousHistory = historyBySeries;
    const optimisticHistory = pruneSeriesHistory(previousHistory, name);
    const applyPrunedHistory = () => {
      setHistoryBySeries((current) => pruneSeriesHistory(current, name));
    };

    if (onRemoveSeries) {
      try {
        const update = await Promise.resolve(onRemoveSeries(name, entries));
        if (!update) {
          return {
            ok: true,
            entries,
            historyBySeries: optimisticHistory,
          };
        }
        if (isChartMutation(update)) {
          applyMutation(update);
          applyPrunedHistory();
          return {
            ok: true,
            entries: update.entries ?? entries.filter((entry) => entry.name !== name),
            historyBySeries: optimisticHistory,
          };
        }
        applySnapshot(update);
        applyPrunedHistory();
        return {
          ok: true,
          entries: update.entries,
          historyBySeries: pruneSeriesHistory(update.historyBySeries ?? previousHistory, name),
        };
      } catch (_error) {
        return {
          ok: false,
          entries: previousEntries,
          historyBySeries: previousHistory,
          error: 'Failed to update chart.',
        };
      }
    }
    const optimisticMutation = buildOptimisticRemoveMutation(name);
    if (optimisticMutation) {
      applyMutation(optimisticMutation);
      applyPrunedHistory();
    }
    try {
      const response = await chartRequest(`${CHART_API_BASE}/chart-series/remove`, sessionId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const d = await response.json();
      if (!d.ok) {
        throw new Error(typeof d.error === 'string' && d.error.trim() ? d.error : 'Failed to update chart.');
      }

      const nextHistory =
        d.historyBySeries && typeof d.historyBySeries === 'object'
          ? (d.historyBySeries as ChartHistoryBySeries)
          : optimisticHistory;
      setHistoryBySeries(nextHistory);

      if (d.mutation) {
        const mutation = d.mutation as ChartMutation;
        applyMutation(mutation);
        return {
          ok: true,
          entries: mutation.entries ?? previousEntries.filter((entry) => entry.name !== name),
          historyBySeries: nextHistory,
        };
      }

      const snapshot: ChartSnapshot = {
        payload: {
          mode: d.mode,
          series: d.series,
          dataLength: d.dataLength,
          forcePercentage: d.forcePercentage === true,
        },
        entries: d.entries || [],
        historyBySeries: nextHistory,
      };
      applySnapshot(snapshot);
      return {
        ok: true,
        entries: snapshot.entries,
        historyBySeries: nextHistory,
      };
    } catch (error) {
      if (optimisticMutation && previousPayload) {
        applySnapshot({
          payload: previousPayload,
          entries: previousEntries,
          historyBySeries: previousHistory,
        });
      }
      fetchData();
      return {
        ok: false,
        entries: previousEntries,
        historyBySeries: previousHistory,
        error: error instanceof Error ? error.message : 'Failed to update chart.',
      };
    }
  }, [applyMutation, applySnapshot, buildOptimisticRemoveMutation, canRemoveSeries, entries, fetchData, historyBySeries, onRemoveSeries, pauseBackgroundBackfills, payload, sessionId]);

  const handleSeriesAdded = useCallback((update: ChartUpdate | null, nextHistoryBySeries?: ChartHistoryBySeries | null) => {
    pauseBackgroundBackfills();
    if (nextHistoryBySeries) {
      setHistoryBySeries(nextHistoryBySeries);
    }
    if (update) {
      if (isChartMutation(update)) {
        applyMutation(update);
      } else {
        applySnapshot(update);
      }
      return;
    }
    fetchData();
  }, [applyMutation, applySnapshot, fetchData, pauseBackgroundBackfills]);

  useImperativeHandle(ref, () => ({
    applyExternalMutation: (mutation, nextHistoryBySeries) => {
      if (nextHistoryBySeries) {
        setHistoryBySeries(nextHistoryBySeries);
      }
      if (mutation) {
        applyMutation(mutation);
      }
    },
    applyExternalSnapshot: (snapshot) => {
      if (snapshot?.historyBySeries !== undefined) {
        setHistoryBySeries(snapshot.historyBySeries);
      }
      applySnapshot(snapshot);
    },
    refresh: () => {
      fetchData();
    },
    removeSeries: (name) => handleRemoveSeries(name),
  }), [applyMutation, applySnapshot, fetchData, handleRemoveSeries]);

  useEffect(() => {
    const activeNames = new Set(entries.map((entry) => entry.name));
    for (const [name, active] of Array.from(backfillControllersRef.current.entries())) {
      const status = historyBySeries[name];
      if (
        !activeNames.has(name) ||
        !status ||
        status.requestToken !== active.token ||
        status.isComplete ||
        !status.hasOlder ||
        !status.backfillInFlight
      ) {
        active.controller.abort();
        backfillControllersRef.current.delete(name);
      }
    }

    const deferMs = deferBackfillsUntilRef.current - Date.now();
    if (deferMs > 0) {
      scheduleBackfillWake(deferMs);
      return;
    }

    if (backfillControllersRef.current.size >= MAX_CONCURRENT_BACKFILLS) {
      return;
    }

    const pendingStatuses = [...trackedHistoryStatuses]
      .reverse()
      .filter(({ name, status }) =>
        !status.isComplete &&
        status.hasOlder &&
        status.backfillInFlight &&
        !backfillControllersRef.current.has(name)
      );

    for (const { name, status } of pendingStatuses) {
      if (backfillControllersRef.current.size >= MAX_CONCURRENT_BACKFILLS) {
        break;
      }

      const controller = new AbortController();
      backfillControllersRef.current.set(name, { controller, token: status.requestToken });

      chartRequest(`${CHART_API_BASE}/chart-series/progressive/backfill`, sessionId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, requestToken: status.requestToken }),
        signal: controller.signal,
      })
        .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`${response.status}`))))
        .then((next) => {
          if (next.ok !== true || next.stale) {
            return;
          }
          if (controller.signal.aborted) {
            return;
          }
          const currentStatus = historyBySeriesRef.current[name];
          const isStillActive = entriesRef.current.some((entry) => entry.name === name);
          if (!isStillActive || !currentStatus || currentStatus.requestToken !== status.requestToken) {
            return;
          }
          if (next.mutation) {
            applyMutation(next.mutation as ChartMutation);
          }
          if (next.historyBySeries && typeof next.historyBySeries === 'object') {
            setHistoryBySeries(next.historyBySeries as ChartHistoryBySeries);
          }
        })
        .catch((backfillError) => {
          if (backfillError instanceof Error && backfillError.name === 'AbortError') {
            return;
          }
          setHistoryBySeries((current) => {
            const existing = current[name];
            if (!existing) {
              return current;
            }
            return {
              ...current,
              [name]: {
                ...existing,
                backfillInFlight: false,
              },
            };
          });
        })
        .finally(() => {
          const active = backfillControllersRef.current.get(name);
          if (active?.token === status.requestToken) {
            backfillControllersRef.current.delete(name);
            setBackfillCycle((current) => current + 1);
          }
        });
    }
  }, [applyMutation, backfillCycle, entries, historyBySeries, scheduleBackfillWake, sessionId, trackedHistoryStatuses]);

  useEffect(() => () => {
    if (backfillWakeTimerRef.current) {
      clearTimeout(backfillWakeTimerRef.current);
      backfillWakeTimerRef.current = null;
    }
    for (const { controller } of Array.from(backfillControllersRef.current.values())) {
      controller.abort();
    }
    backfillControllersRef.current.clear();
  }, []);

  // Extract unique indicator groups from payload
  const indicatorOptions: IndicatorOption[] = useMemo(() => {
    if (!payload) return [];
    const seen = new Map<string, string>();
    for (const s of payload.series ?? []) {
      if (s.indicator && s.indicatorGroup && !seen.has(s.indicatorGroup)) {
        seen.set(s.indicatorGroup, s.color ?? '#888');
      }
    }
    const result: IndicatorOption[] = [];
    seen.forEach((color, group) => result.push({ group, color }));
    return result;
  }, [payload]);

  // Stable string for dependency tracking in ChartCanvas
  const selectedIndicatorsSig = useMemo(
    () => Array.from(selectedIndicators).sort().join(','),
    [selectedIndicators]
  );

  const handleDateSelect = useCallback((request: NonNullable<DateSelectionRequest>) => {
    setDateSelectionRequest(request);
    setDateSelectorOpen(false);
    setSelectedRange(null);
  }, []);

  const handleAppliedDateSelection = useCallback(() => {
    setDateSelectionRequest(null);
  }, []);

  const handleTimeframeChange = useCallback(
    (view: string, snapshot: ChartSnapshot | null, nextHistoryBySeries?: ChartHistoryBySeries | null) => {
      pauseBackgroundBackfills();
      setActiveView(view);
      if (nextHistoryBySeries) {
        setHistoryBySeries(nextHistoryBySeries);
      }
      if (snapshot) {
        applySnapshot(snapshot);
        return;
      }
      fetchData();
    },
    [applySnapshot, fetchData, pauseBackgroundBackfills]
  );

  const handleRangeSelect = useCallback(
    (rangeId: RangeId) => {
      pauseBackgroundBackfills();
      const option = RANGE_BUTTONS.find((r) => r.id === rangeId);
      if (!option) return;
      setSelectedRange(rangeId);
      chartRequest('/chart/api/chart-view', sessionId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ view: option.view }),
      })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
        .then((d) => {
          setActiveView(option.view);
          if (d.historyBySeries && typeof d.historyBySeries === 'object') {
            setHistoryBySeries(d.historyBySeries as ChartHistoryBySeries);
          }
          applySnapshot({
            payload: {
              mode: d.mode,
              series: d.series,
              dataLength: d.dataLength,
              forcePercentage: d.forcePercentage === true,
            },
            entries: d.entries || [],
            historyBySeries: d.historyBySeries ?? {},
          });
        })
        .catch(() => {
          fetchData();
        })
    },
    [applySnapshot, fetchData, pauseBackgroundBackfills, sessionId]
  );

  const handleToggleRiskAnalytics = useCallback(() => {
    if (riskAnalyticsOpen) {
      setRiskAnalyticsOpen(false);
      return;
    }
    if (!payload) return;
    const toDateStr = (v: unknown): string => {
      if (typeof v === 'number') return new Date(v * 1000).toISOString().slice(0, 10);
      const s = String(v);
      if (/^\d+(\.\d+)?$/.test(s) && Number(s) > 1e8) return new Date(Number(s) * 1000).toISOString().slice(0, 10);
      return s.slice(0, 10);
    };
    const candle = (payload.series ?? []).find(
      (s) => s.seriesType === 'candlestick' || (!s.indicator && s.seriesType === 'line')
    );
    if (!candle) return;
    const fromDate = visibleRange?.from ? toDateStr(visibleRange.from) : null;
    const toDate = visibleRange?.to ? toDateStr(visibleRange.to) : null;
    const closes: number[] = [];
    for (const p of candle.data) {
      const t = (p as { time: string }).time.slice(0, 10);
      if (fromDate && t < fromDate) continue;
      if (toDate && t > toDate) continue;
      const val = 'close' in p ? (p as { close: number }).close : 'value' in p ? (p as { value: number }).value : null;
      if (val != null) closes.push(val as number);
    }
    setRiskCloses(closes);
    setRiskAnalyticsOpen(true);
  }, [payload, riskAnalyticsOpen, visibleRange]);

  // Build tags from series entries + payload colors
  const seriesTags: SeriesTag[] = useMemo(() => {
    if (!payload) return [];
    const colorMap = new Map<string, string>();
    for (const s of payload.series ?? []) {
      if (!s.indicator && s.id && !colorMap.has(s.id)) {
        colorMap.set(s.id, s.color ?? '#2196f3');
      }
    }
    return entries.map((e) => ({
      name: e.name,
      color: colorMap.get(e.name) ?? '#2196f3',
      pinned: e.pinned,
    }));
  }, [entries, payload]);

  const handleResetIndicators = useCallback(() => {
    setSelectedIndicators(new Set());
  }, []);

  const isMobileChart = getResponsiveTier(containerWidth || compactBreakpoint) === 'mobile';

  if (error) {
    return (
      <div style={{ padding: 20, color: '#c62828', fontFamily: FONT_FAMILY }}>
        Chart: failed to load data ({error}). Is the server running?
      </div>
    );
  }

  if (payload == null) return <div style={{ padding: 20, fontFamily: FONT_FAMILY }}>Loading chart…</div>;

  const isEmpty = (payload.series ?? []).every((s) => (s.data ?? []).length === 0);

  const chartBodyTopInset = !isEmpty && statusBadgeLabel && !isNarrow ? 16 : 0;

  return (
    <div
      ref={rootRef}
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        height: '100%',
        minWidth: 0,
        overflow: 'hidden',
        background: '#fff',
        fontFamily: FONT_FAMILY,
      }}
    >
      <TopBar
        sessionId={sessionId}
        isEmpty={isEmpty}
        activeView={activeView}
        onViewChange={handleTimeframeChange}
        selectedRange={selectedRange}
        onRangeSelect={handleRangeSelect}
        rangeAvailability={rangeAvailability}
        onOpenDateSelector={() => setDateSelectorOpen(true)}
        indicatorOptions={indicatorOptions}
        selectedIndicators={selectedIndicators}
        onSelectedIndicatorsChange={setSelectedIndicators}
        onReset={handleResetIndicators}
        riskAnalyticsOpen={riskAnalyticsOpen}
        onToggleRiskAnalytics={handleToggleRiskAnalytics}
        seriesCount={entries.length}
        maxSeries={MAX_CHART_SERIES}
        onSeriesAdded={handleSeriesAdded}
        statusBadgeLabel={statusBadgeLabel}
        compact={isNarrow}
      />
      <div
        style={{
          position: 'relative',
          flex: 1,
          minHeight: 0,
          overflow: 'hidden',
          paddingTop: chartBodyTopInset,
          boxSizing: 'border-box',
        }}
      >
        {isEmpty ? (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: '#fafafa',
              color: '#bbb',
              fontSize: 13,
              zIndex: 1,
            }}
          >
            Search to add a chart
          </div>
        ) : (
          <>
            <ChartCanvas
              sessionId={sessionId}
              payload={payload}
              selectedRange={selectedRange}
              priceScaleMode={priceScaleMode}
              priceScaleMargins={priceScaleMargins}
              dateSelectionRequest={dateSelectionRequest}
              onAppliedDateSelection={handleAppliedDateSelection}
              onUserScroll={() => {
                setSelectedRange(null);
                setRiskAnalyticsOpen(false);
              }}
              selectedIndicatorsSig={selectedIndicatorsSig}
              onVisibleRangeChange={setVisibleRange}
            />
            <RiskAnalyticsPanel
              visible={riskAnalyticsOpen}
              onClose={() => setRiskAnalyticsOpen(false)}
              closes={riskCloses}
              mobile={isMobileChart}
            />
          </>
        )}
      </div>
      <BottomBar
        isEmpty={isEmpty}
        priceScaleMode={priceScaleMode}
        onPriceScaleModeChange={setPriceScaleMode}
        forcePercentage={forcePercentage}
        seriesTags={seriesTags}
        onRemoveTag={handleRemoveSeries}
        compact={isNarrow}
        indicatorOptions={indicatorOptions}
        selectedIndicators={selectedIndicators}
        onSelectedIndicatorsChange={setSelectedIndicators}
        onReset={handleResetIndicators}
      />
      <DateSelector isOpen={dateSelectorOpen} onClose={() => setDateSelectorOpen(false)} onSelect={handleDateSelect} />
    </div>
  );
});

ChartComponentInner.displayName = 'ChartComponent';

const ChartComponent = React.memo(ChartComponentInner);

export default ChartComponent;
