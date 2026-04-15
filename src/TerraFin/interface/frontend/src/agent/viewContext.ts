export interface AgentViewContextPayload {
  source?: string;
  scope?: 'page' | 'panel';
  route: string;
  pageType: string;
  title?: string | null;
  summary?: string | null;
  selection?: Record<string, unknown>;
  entities?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
}

const VIEW_CONTEXT_ID_STORAGE_KEY = 'terrafin.agent.view-context-id';

let fallbackViewContextId: string | null = null;
let lastPublishedSignature: string | null = null;
const viewContextSources = new Map<string, AgentViewContextPayload & { source: string; scope: 'page' | 'panel'; updatedAt: number }>();

function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `view-${Math.random().toString(36).slice(2, 10)}`;
}

export function getAgentViewContextId(): string {
  try {
    const existing = window.sessionStorage.getItem(VIEW_CONTEXT_ID_STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const next = randomId();
    window.sessionStorage.setItem(VIEW_CONTEXT_ID_STORAGE_KEY, next);
    return next;
  } catch {
    if (fallbackViewContextId == null) {
      fallbackViewContextId = randomId();
    }
    return fallbackViewContextId;
  }
}

function mergeViewContextPayloads() {
  const entries = Array.from(viewContextSources.values()).sort((left, right) => left.updatedAt - right.updatedAt);
  if (entries.length === 0) {
    return null;
  }
  const pageEntries = entries.filter((entry) => entry.scope === 'page');
  const primary = pageEntries[pageEntries.length - 1] || entries[entries.length - 1];
  const selection = Object.assign({}, ...entries.map((entry) => entry.selection || {}));
  const metadata = Object.assign({}, ...entries.map((entry) => entry.metadata || {})) as Record<string, unknown>;
  const entitySignatures = new Set<string>();
  const entities: Array<Record<string, unknown>> = [];
  for (const entry of entries) {
    for (const entity of entry.entities || []) {
      const signature = JSON.stringify(entity);
      if (entitySignatures.has(signature)) {
        continue;
      }
      entitySignatures.add(signature);
      entities.push(entity);
    }
  }
  metadata.sources = entries.map((entry) => entry.source);
  metadata.sections = Object.fromEntries(
    entries.map((entry) => [
      entry.source,
      {
        scope: entry.scope,
        title: entry.title ?? null,
        summary: entry.summary ?? null,
        selection: entry.selection || {},
        entities: entry.entities || [],
        metadata: entry.metadata || {},
        updatedAt: new Date(entry.updatedAt).toISOString(),
      },
    ])
  );
  return {
    route: primary.route,
    pageType: primary.pageType,
    title: primary.title ?? null,
    summary: primary.summary ?? null,
    selection,
    entities,
    metadata,
  };
}

async function flushAgentViewContext(): Promise<void> {
  const contextId = getAgentViewContextId();
  const body = mergeViewContextPayloads();
  if (body == null) {
    lastPublishedSignature = null;
    return;
  }
  const signature = JSON.stringify({ contextId, body });
  if (signature === lastPublishedSignature) {
    return;
  }
  const previousSignature = lastPublishedSignature;
  lastPublishedSignature = signature;
  try {
    const response = await fetch(`/agent/api/runtime/view-contexts/${encodeURIComponent(contextId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      lastPublishedSignature = previousSignature;
    }
  } catch {
    lastPublishedSignature = previousSignature;
    // Current view context is best-effort UI state, so avoid surfacing transient sync failures.
  }
}

export async function publishAgentViewContext(payload: AgentViewContextPayload): Promise<void> {
  const source = payload.source?.trim() || 'default';
  viewContextSources.set(source, {
    ...payload,
    source,
    scope: payload.scope || 'page',
    updatedAt: Date.now(),
  });
  await flushAgentViewContext();
}

export async function clearAgentViewContextSource(source: string): Promise<void> {
  if (!source.trim()) {
    return;
  }
  viewContextSources.delete(source);
  await flushAgentViewContext();
}
