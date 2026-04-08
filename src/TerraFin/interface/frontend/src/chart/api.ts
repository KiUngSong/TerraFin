const TAB_ID_STORAGE_KEY = 'terrafin.chart.tab-id';

let fallbackTabId: string | null = null;

function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `chart-${Math.random().toString(36).slice(2, 10)}`;
}

function getTabId(): string {
  try {
    const existing = window.sessionStorage.getItem(TAB_ID_STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const next = randomId();
    window.sessionStorage.setItem(TAB_ID_STORAGE_KEY, next);
    return next;
  } catch {
    if (fallbackTabId == null) {
      fallbackTabId = randomId();
    }
    return fallbackTabId;
  }
}

export function getChartSessionId(scope: string): string {
  return `${scope}:${getTabId()}`;
}

export function chartRequest(input: RequestInfo | URL, sessionId: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-Session-ID', sessionId);
  return fetch(input, { ...init, headers });
}
