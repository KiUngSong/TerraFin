import { chartRequest } from './api';
import { useEffect, useRef, useState } from 'react';
import { CHART_API_BASE, POLL_MS } from './constants';
import type { ChartHistoryBySeries, ChartMutation, ChartPayload, ChartSeriesEntry, ChartSnapshot } from './types';
import {
  applyMutationToPayload,
  entriesSignature,
  payloadSignature,
} from './updateUtils';

function normalizeHistoryBySeries(value: unknown): ChartHistoryBySeries {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return value as ChartHistoryBySeries;
}

function normalizeSnapshot(
  next: ChartPayload & {
    mode?: string;
    series?: unknown;
    forcePercentage?: boolean;
    entries?: unknown;
    historyBySeries?: unknown;
  }
): ChartSnapshot {
  if (next.mode !== 'multi' || !Array.isArray(next.series)) {
    throw new Error('Unsupported chart payload contract. Expected multi-series payload.');
  }

  const payload: ChartPayload = {
    mode: 'multi',
    series: next.series as ChartPayload['series'],
    dataLength: typeof next.dataLength === 'number' ? next.dataLength : 0,
    forcePercentage: next.forcePercentage === true,
  };

  const entries = Array.isArray(next.entries)
    ? next.entries
        .filter(
          (entry): entry is ChartSeriesEntry =>
            entry != null &&
            typeof entry === 'object' &&
            typeof (entry as ChartSeriesEntry).name === 'string' &&
            typeof (entry as ChartSeriesEntry).pinned === 'boolean'
        )
    : [];

  return { payload, entries, historyBySeries: normalizeHistoryBySeries(next.historyBySeries) };
}

interface UseChartDataOptions {
  initialPayload?: ChartPayload | null;
  initialEntries?: ChartSeriesEntry[];
  pollingEnabled?: boolean;
  sessionId: string;
}

export function useChartData(options: UseChartDataOptions): {
  payload: ChartPayload | null;
  entries: ChartSeriesEntry[];
  historyBySeries: ChartHistoryBySeries;
  error: string | null;
  fetchData: () => void;
  applySnapshot: (snapshot: ChartSnapshot | null) => void;
  applyMutation: (mutation: ChartMutation | null) => void;
} {
  const { initialPayload = null, initialEntries = [], pollingEnabled = true, sessionId } = options;
  const [payload, setPayload] = useState<ChartPayload | null>(initialPayload);
  const [entries, setEntries] = useState<ChartSeriesEntry[]>(initialEntries);
  const [historyBySeries, setHistoryBySeries] = useState<ChartHistoryBySeries>({});
  const [error, setError] = useState<string | null>(null);
  const payloadRef = useRef<ChartPayload | null>(initialPayload);
  const entriesRef = useRef<ChartSeriesEntry[]>(initialEntries);
  const lastSigRef = useRef<string | null>(
    initialPayload ? `${payloadSignature(initialPayload)}|entries:${entriesSignature(initialEntries)}` : null
  );
  const initialSigRef = useRef<string | null>(
    initialPayload ? `${payloadSignature(initialPayload)}|entries:${entriesSignature(initialEntries)}` : null
  );

  const applySnapshot = (snapshot: ChartSnapshot | null) => {
    if (snapshot == null) {
      lastSigRef.current = null;
      payloadRef.current = null;
      entriesRef.current = [];
      setPayload(null);
      setEntries([]);
      return;
    }

    const sig = `${payloadSignature(snapshot.payload)}|entries:${entriesSignature(snapshot.entries)}`;
    if (lastSigRef.current === sig) return;
    lastSigRef.current = sig;
    payloadRef.current = snapshot.payload;
    entriesRef.current = snapshot.entries;
    setPayload(snapshot.payload);
    setEntries(snapshot.entries);
    if (snapshot.historyBySeries !== undefined) {
      setHistoryBySeries(snapshot.historyBySeries);
    }
    setError(null);
  };

  const applyMutation = (mutation: ChartMutation | null) => {
    if (mutation == null) {
      return;
    }
    const nextPayload = applyMutationToPayload(payloadRef.current, mutation);
    const nextEntries = mutation.entries ?? [];
    const sig = `${payloadSignature(nextPayload)}|entries:${entriesSignature(nextEntries)}`;
    if (lastSigRef.current === sig) return;
    lastSigRef.current = sig;
    payloadRef.current = nextPayload;
    entriesRef.current = nextEntries;
    setPayload(nextPayload);
    setEntries(nextEntries);
    setError(null);
  };

  useEffect(() => {
    const nextPayload = initialPayload;
    const nextSig = nextPayload
      ? `${payloadSignature(initialPayload)}|entries:${entriesSignature(initialEntries)}`
      : null;
    if (nextSig == null || nextPayload == null || nextSig === initialSigRef.current) return;
    initialSigRef.current = nextSig;
    applySnapshot({ payload: nextPayload, entries: initialEntries });
  }, [initialPayload, initialEntries]);

  const fetchData = () => {
    chartRequest(`${CHART_API_BASE}/chart-data`, sessionId)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((next: ChartPayload & {
        mode?: string;
        series?: unknown;
        forcePercentage?: boolean;
        entries?: unknown;
        historyBySeries?: unknown;
      }) => {
        applySnapshot(normalizeSnapshot(next));
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load chart data'));
  };

  useEffect(() => {
    if (initialPayload == null) {
      fetchData();
    }
    if (!pollingEnabled) return;
    const id = setInterval(fetchData, POLL_MS);
    return () => clearInterval(id);
  }, [initialPayload, pollingEnabled, sessionId]);

  return { payload, entries, historyBySeries, error, fetchData, applySnapshot, applyMutation };
}
