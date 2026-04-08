import { useCallback, useEffect, useState } from 'react';

export interface WatchlistItem {
  symbol: string;
  name: string;
  move: string;
}

interface WatchlistResponse {
  items?: WatchlistItem[];
  detail?: string;
  backendConfigured?: boolean;
  mode?: string;
}

const WATCHLIST_ENDPOINT = '/dashboard/api/watchlist';

interface ParsedWatchlistResponse {
  items: WatchlistItem[];
  backendConfigured: boolean;
  mode: string;
}

async function parseWatchlistResponse(response: Response): Promise<ParsedWatchlistResponse> {
  const payload = (await response.json().catch(() => ({}))) as WatchlistResponse;
  if (!response.ok) {
    throw new Error(payload.detail || 'Unable to update the TerraFin watchlist right now.');
  }
  return {
    items: payload.items || [],
    backendConfigured: Boolean(payload.backendConfigured),
    mode: payload.mode || 'fallback',
  };
}

export function useWatchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendConfigured, setBackendConfigured] = useState(false);
  const [mode, setMode] = useState('fallback');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(WATCHLIST_ENDPOINT);
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
    } catch (fetchError) {
      setItems([]);
      setBackendConfigured(false);
      setMode('fallback');
      setError(fetchError instanceof Error ? fetchError.message : 'Unable to load the TerraFin watchlist right now.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addSymbol = useCallback(async (symbol: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(WATCHLIST_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      });
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to add that ticker right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, []);

  const removeSymbol = useCallback(async (symbol: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${WATCHLIST_ENDPOINT}/${encodeURIComponent(symbol)}`, {
        method: 'DELETE',
      });
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to remove that ticker right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    items,
    loading,
    busy,
    error,
    backendConfigured,
    mode,
    refresh,
    addSymbol,
    removeSymbol,
  };
}
