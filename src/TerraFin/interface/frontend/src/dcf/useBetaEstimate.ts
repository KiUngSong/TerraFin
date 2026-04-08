import { useCallback, useEffect, useState } from 'react';
import { BetaEstimatePayload } from './types';

export function useBetaEstimate(endpoint: string | null, enabled = true) {
  const [data, setData] = useState<BetaEstimatePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setLoading(false);
    setError(null);
  }, [endpoint]);

  const compute = useCallback(async () => {
    if (!endpoint || !enabled) {
      setData(null);
      setLoading(false);
      setError(null);
      return null;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch(endpoint);
      if (!response.ok) {
        throw new Error(`${response.status}`);
      }
      const payload = (await response.json()) as BetaEstimatePayload;
      setData(payload);
      return payload;
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : 'Unable to compute beta.');
      return null;
    } finally {
      setLoading(false);
    }
  }, [enabled, endpoint]);

  const reset = useCallback(() => {
    setData(null);
    setLoading(false);
    setError(null);
  }, []);

  return { data, loading, error, compute, reset };
}
