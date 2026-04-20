import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'terrafin.dcf.explainInputs';

function readInitial(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === '1';
  } catch {
    return false;
  }
}

export function useExplainInputs(): [boolean, () => void] {
  const [explain, setExplain] = useState<boolean>(readInitial);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(STORAGE_KEY, explain ? '1' : '0');
    } catch {
      // ignore quota / privacy errors
    }
  }, [explain]);

  const toggle = useCallback(() => setExplain((v) => !v), []);
  return [explain, toggle];
}
