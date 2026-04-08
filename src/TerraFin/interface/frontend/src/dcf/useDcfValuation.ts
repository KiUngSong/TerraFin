import { useEffect, useState } from 'react';
import { DcfValuationPayload } from './types';

export interface DcfFetchRequest {
  method?: 'GET' | 'POST';
  body?: unknown;
  requestId: number;
}

export function useDcfValuation<TPayload = DcfValuationPayload>(
  endpoint: string | null,
  request: DcfFetchRequest | null,
  enabled = true,
) {
  const [data, setData] = useState<TPayload | null>(null);
  const [loading, setLoading] = useState(Boolean(endpoint) && Boolean(request) && enabled);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!endpoint || !enabled || !request) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    let canceled = false;
    setLoading(true);
    setError(null);

    fetch(endpoint, {
      method: request.method || 'GET',
      headers: request.body ? { 'Content-Type': 'application/json' } : undefined,
      body: request.body ? JSON.stringify(request.body) : undefined,
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: TPayload) => {
        if (!canceled) setData(payload);
      })
      .catch((err) => {
        if (!canceled) {
          setData(null);
          setError(err instanceof Error ? err.message : 'Unable to load valuation.');
        }
      })
      .finally(() => {
        if (!canceled) setLoading(false);
      });

    return () => {
      canceled = true;
    };
  }, [enabled, endpoint, request]);

  return { data, loading, error };
}
