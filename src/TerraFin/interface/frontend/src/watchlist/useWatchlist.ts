import { useCallback, useEffect, useState } from 'react';

export interface WatchlistItem {
  symbol: string;
  name: string;
  move: string;
  tags: string[];
}

export interface WatchlistGroup {
  tag: string;
  count: number;
}

interface WatchlistResponse {
  items?: WatchlistItem[];
  detail?: string;
  backendConfigured?: boolean;
  mode?: string;
  monitorEnabled?: boolean;
}

const WATCHLIST_ENDPOINT = '/dashboard/api/watchlist';

interface ParsedWatchlistResponse {
  items: WatchlistItem[];
  backendConfigured: boolean;
  mode: string;
  monitorEnabled: boolean;
}

async function parseWatchlistResponse(response: Response): Promise<ParsedWatchlistResponse> {
  const payload = (await response.json().catch(() => ({}))) as WatchlistResponse;
  if (!response.ok) {
    throw new Error(payload.detail || 'Unable to update the TerraFin watchlist right now.');
  }
  return {
    items: (payload.items || []).map((item) => ({ ...item, tags: item.tags || [] })),
    backendConfigured: Boolean(payload.backendConfigured),
    mode: payload.mode || 'fallback',
    monitorEnabled: Boolean(payload.monitorEnabled),
  };
}

export function useWatchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendConfigured, setBackendConfigured] = useState(false);
  const [mode, setMode] = useState('fallback');
  const [monitorEnabled, setMonitorEnabled] = useState(false);

  const fetchGroups = useCallback(async () => {
    try {
      const resp = await fetch(`${WATCHLIST_ENDPOINT}/groups`);
      if (resp.ok) {
        const data = (await resp.json()) as { groups?: WatchlistGroup[] };
        setGroups(data.groups || []);
      }
    } catch {
      // groups are non-critical
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = selectedGroup
        ? `${WATCHLIST_ENDPOINT}?group=${encodeURIComponent(selectedGroup)}`
        : WATCHLIST_ENDPOINT;
      const response = await fetch(url);
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
      setMonitorEnabled(payload.monitorEnabled);
    } catch (fetchError) {
      setItems([]);
      setBackendConfigured(false);
      setMode('fallback');
      setMonitorEnabled(false);
      setError(fetchError instanceof Error ? fetchError.message : 'Unable to load the TerraFin watchlist right now.');
    } finally {
      setLoading(false);
    }
  }, [selectedGroup]);

  useEffect(() => {
    void refresh();
    void fetchGroups();
  }, [refresh, fetchGroups]);

  const addSymbol = useCallback(async (symbol: string, tags?: string[]) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(WATCHLIST_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, tags: tags || [] }),
      });
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
      setMonitorEnabled(payload.monitorEnabled);
      await fetchGroups();
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to add that ticker right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, [fetchGroups]);

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
      setMonitorEnabled(payload.monitorEnabled);
      await fetchGroups();
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to remove that ticker right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, [fetchGroups]);

  const setTags = useCallback(async (symbol: string, tags: string[], mode_: 'set' | 'add' | 'remove' = 'set') => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${WATCHLIST_ENDPOINT}/${encodeURIComponent(symbol)}/tags`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags, mode: mode_ }),
      });
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
      setMonitorEnabled(payload.monitorEnabled);
      await fetchGroups();
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to update tags right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, [fetchGroups]);

  const renameGroup = useCallback(async (oldTag: string, newTag: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${WATCHLIST_ENDPOINT}/groups/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old: oldTag, new: newTag }),
      });
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
      setMonitorEnabled(payload.monitorEnabled);
      await fetchGroups();
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to rename group right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, [fetchGroups]);

  const promoteGroup = useCallback(async (syntheticItems: WatchlistItem[], newTag: string, allItems: WatchlistItem[]) => {
    setBusy(true);
    setError(null);
    try {
      const syntheticSymbols = new Set(syntheticItems.map((i) => i.symbol));
      const updatedSymbols = allItems.map((item) => ({
        symbol: item.symbol,
        tags: syntheticSymbols.has(item.symbol) ? [...item.tags, newTag] : item.tags,
      }));
      const response = await fetch(WATCHLIST_ENDPOINT, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: updatedSymbols }),
      });
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
      setMonitorEnabled(payload.monitorEnabled);
      await fetchGroups();
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to rename group right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, [fetchGroups]);

  const deleteGroup = useCallback(async (tag: string, currentItems: WatchlistItem[]) => {
    setBusy(true);
    setError(null);
    try {
      const updatedSymbols = currentItems.map((item) => ({
        symbol: item.symbol,
        tags: item.tags.filter((t) => t !== tag),
      }));
      const response = await fetch(WATCHLIST_ENDPOINT, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: updatedSymbols }),
      });
      const payload = await parseWatchlistResponse(response);
      setItems(payload.items);
      setBackendConfigured(payload.backendConfigured);
      setMode(payload.mode);
      setMonitorEnabled(payload.monitorEnabled);
      await fetchGroups();
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to delete group right now.');
      throw mutationError;
    } finally {
      setBusy(false);
    }
  }, [fetchGroups]);

  return {
    items,
    groups,
    selectedGroup,
    setSelectedGroup,
    loading,
    busy,
    error,
    backendConfigured,
    mode,
    monitorEnabled,
    refresh,
    addSymbol,
    removeSymbol,
    setTags,
    renameGroup,
    deleteGroup,
    promoteGroup,
  };
}
