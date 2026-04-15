import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AgentShellDrawer } from './layout';
import { getAgentViewContextId } from './viewContext';

interface HostedToolDefinition {
  name: string;
  capabilityName: string;
  description: string;
  executionMode: 'invoke' | 'task';
}

interface HostedRuntimeModel {
  modelRef: string;
  providerId: string;
  providerLabel: string;
  modelId: string;
  metadata?: Record<string, unknown>;
}

interface HostedAgentDefinition {
  name: string;
  description: string;
  defaultDepth: string;
  defaultView: string;
  chartAccess: boolean;
  allowBackgroundTasks: boolean;
  runtimeModel?: HostedRuntimeModel | null;
  tools: HostedToolDefinition[];
}

interface HostedConversationMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  createdAt: string;
  name?: string | null;
  toolCallId?: string | null;
  metadata?: Record<string, unknown>;
}

interface HostedTask {
  taskId: string;
  capabilityName: string;
  status: string;
  description: string;
  sessionId?: string | null;
  createdAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
  inputPayload: Record<string, unknown>;
  progress: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

interface HostedApproval {
  approvalId: string;
  createdAt: string;
  updatedAt: string;
  resolvedAt?: string | null;
  sessionId: string;
  agentName: string;
  action: 'invoke' | 'task';
  capabilityName: string;
  toolName?: string | null;
  sideEffecting: boolean;
  status: 'pending' | 'approved' | 'denied' | 'consumed';
  reason: string;
  inputPayload: Record<string, unknown>;
  decisionNote?: string | null;
  metadata: Record<string, unknown>;
}

interface HostedToolResult {
  toolName: string;
  capabilityName: string;
  executionMode: 'invoke' | 'task';
  payload: Record<string, unknown>;
  task?: {
    taskId: string;
    status: string;
    description: string;
  } | null;
}

interface HostedAgentSession {
  sessionId: string;
  agentName: string;
  metadata: Record<string, unknown>;
  runtimeModel?: HostedRuntimeModel | null;
  tools: HostedToolDefinition[];
  messages: HostedConversationMessage[];
  tasks: HostedTask[];
  approvals: HostedApproval[];
}

interface HostedRunResponse {
  sessionId: string;
  agentName: string;
  steps: number;
  finalMessage?: HostedConversationMessage | null;
  messagesAdded: HostedConversationMessage[];
  session: HostedAgentSession;
  toolResults: HostedToolResult[];
}

interface HostedSessionSummary {
  sessionId: string;
  agentName: string;
  createdAt: string;
  updatedAt: string;
  lastAccessedAt: string;
  runtimeModel?: HostedRuntimeModel | null;
  title?: string | null;
  lastMessagePreview?: string | null;
  lastMessageAt?: string | null;
  messageCount: number;
  pendingTaskCount: number;
}

interface HostedSessionListResponse {
  sessions: HostedSessionSummary[];
}

interface HostedDeleteSessionResponse {
  sessionId: string;
  deletedAt: string;
}

interface HostedTaskListResponse {
  sessionId: string;
  tasks: HostedTask[];
}

const REQUEST_TIMEOUT_MS = 12000;
const TASK_POLL_INTERVAL_MS = 1500;
const MODEL_REFRESH_INTERVAL_MS = 60000;
const CATALOG_STALE_MS = 60000;
const HISTORY_STALE_MS = 15000;
const AGENT_UI_NAME = 'TerraFin Agent';
const ACTIVE_SESSION_STORAGE_KEY = 'terrafin.agent.active-session-id';
const LOCAL_SETUP_MESSAGE = `${AGENT_UI_NAME} needs a local hosted model setup before it can run here.

To use it locally:
- choose a hosted model with TERRAFIN_AGENT_MODEL_REF
- add provider credentials such as OPENAI_API_KEY, GEMINI_API_KEY, or COPILOT_GITHUB_TOKEN
- restart TerraFin after saving the model or credentials`
;

const DEFAULT_PROMPTS = [
  'Give me a compact AAPL market snapshot.',
  'Summarize the key signals on this page and tell me what stands out.',
  'Review the current setup and tell me what deserves a second look.',
];

type AgentMessageItemProps = {
  message: HostedConversationMessage;
  messageKey: string;
};

const AgentMessageItem = memo(
  (props: AgentMessageItemProps) => {
    const { message } = props;
    const showRoleMeta = message.role === 'tool' || message.role === 'system';
    return (
      <div className={`tf-agent-message tf-agent-message--${message.role}`}>
        {showRoleMeta ? (
          <div className="tf-agent-message__meta">
            <span>{roleLabel(message)}</span>
          </div>
        ) : null}
        <div className="tf-agent-message__body">{message.content}</div>
      </div>
    );
  },
  (previous, next) => previous.messageKey === next.messageKey
);

const messageFingerprint = (message: HostedConversationMessage) =>
  [
    message.createdAt,
    message.role,
    message.name || '',
    message.toolCallId || '',
    message.content,
  ].join('::');

const mergeMessages = (...messageGroups: Array<HostedConversationMessage[] | undefined>) => {
  const seen = new Set<string>();
  const merged: HostedConversationMessage[] = [];
  messageGroups.forEach((messages) => {
    (messages || []).forEach((message) => {
      const fingerprint = messageFingerprint(message);
      if (seen.has(fingerprint)) {
        return;
      }
      seen.add(fingerprint);
      merged.push(message);
    });
  });
  return merged.sort((left, right) => {
    const leftTime = new Date(left.createdAt).getTime();
    const rightTime = new Date(right.createdAt).getTime();
    if (leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return messageFingerprint(left).localeCompare(messageFingerprint(right));
  });
};

const mergeSessionFromRun = (
  previousSession: HostedAgentSession | null,
  run: HostedRunResponse
): HostedAgentSession => ({
  ...run.session,
  messages: mergeMessages(previousSession?.messages, run.session.messages, run.messagesAdded),
});

const roleLabel = (message: HostedConversationMessage) => {
  if (message.role === 'assistant') {
    return AGENT_UI_NAME;
  }
  if (message.role === 'user') {
    return 'You';
  }
  if (message.role === 'tool') {
    return message.name || 'Tool';
  }
  return 'System';
};

const truncateText = (text: string | null | undefined, limit = 88) => {
  const compact = (text || '').replace(/\s+/g, ' ').trim();
  if (!compact) {
    return '';
  }
  if (compact.length <= limit) {
    return compact;
  }
  return `${compact.slice(0, limit - 1).trimEnd()}…`;
};

const formatSessionTimestamp = (value: string | null | undefined) => {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(date);
  } catch {
    return date.toLocaleString();
  }
};

const runtimeModelRef = (runtimeModel: HostedRuntimeModel | null | undefined) =>
  typeof runtimeModel?.modelRef === 'string' ? runtimeModel.modelRef : '';

const readStoredActiveSessionId = () => {
  try {
    return window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
};

const writeStoredActiveSessionId = (sessionId: string | null) => {
  try {
    if (sessionId) {
      window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
    } else {
      window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    }
  } catch {
    // Best effort only.
  }
};

const TERMINAL_TASK_STATUSES = new Set(['completed', 'failed', 'cancelled']);

const isTerminalTaskStatus = (status: string) => TERMINAL_TASK_STATUSES.has(status);

const formatTaskLabel = (task: HostedTask) => {
  const target = task.result?.ticker || task.inputPayload?.name || task.inputPayload?.ticker;
  if (typeof target === 'string' && target.trim()) {
    return `${task.description} · ${target}`;
  }
  return task.description;
};

const formatTaskDetail = (task: HostedTask) => {
  if (task.error) {
    return task.error;
  }
  const stage = task.progress?.stage;
  if (typeof stage === 'string' && stage.trim()) {
    return stage;
  }
  if (task.status === 'completed') {
    return 'Finished in the background.';
  }
  if (task.status === 'cancelled') {
    return 'Stopped before completion.';
  }
  if (task.status === 'failed') {
    return 'The task ended with an error.';
  }
  return 'Running in the background.';
};

const formatApprovalLabel = (approval: HostedApproval) => {
  const target = approval.inputPayload?.name || approval.inputPayload?.ticker || approval.inputPayload?.data_or_names;
  if (Array.isArray(target) && target.length > 0) {
    return `${approval.toolName || approval.capabilityName} · ${target.join(', ')}`;
  }
  if (typeof target === 'string' && target.trim()) {
    return `${approval.toolName || approval.capabilityName} · ${target}`;
  }
  return approval.toolName || approval.capabilityName;
};

const parseRuntimeError = (payload: unknown, fallback: string): string => {
  if (payload instanceof Error) {
    return payload.message || fallback;
  }
  const detail = (payload as any)?.error?.message || (payload as any)?.detail;
  if (detail === 'Not Found') {
    return `${AGENT_UI_NAME} is not available on this deployment yet.`;
  }
  if ((payload as any)?.error?.code === 'hosted_agent_not_configured') {
    return LOCAL_SETUP_MESSAGE;
  }
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  return fallback;
};

const fetchRuntimeJson = async <T,>(url: string, options: RequestInit = {}, timeoutLabel: string): Promise<T> => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    const raw = await response.text();
    let payload: unknown = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        payload = { detail: raw };
      }
    }
    if (!response.ok) {
      throw payload;
    }
    return payload as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`${timeoutLabel} timed out. Please try again.`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const GlobalAgentWidget: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [agents, setAgents] = useState<HostedAgentDefinition[]>([]);
  const [session, setSession] = useState<HostedAgentSession | null>(null);
  const [sessionHistory, setSessionHistory] = useState<HostedSessionSummary[]>([]);
  const [toolResults, setToolResults] = useState<HostedToolResult[]>([]);
  const [draft, setDraft] = useState('');
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [catalogRequested, setCatalogRequested] = useState(false);
  const [historyRequested, setHistoryRequested] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [showWarmupHint, setShowWarmupHint] = useState(false);
  const [activeDrawer, setActiveDrawer] = useState<AgentShellDrawer>(null);
  const [showPromptSuggestions, setShowPromptSuggestions] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const promptMenuRef = useRef<HTMLDivElement | null>(null);
  const wasOpenRef = useRef(false);
  const restoreAttemptedRef = useRef(false);
  const lastCatalogLoadedAtRef = useRef(0);
  const lastHistoryLoadedAtRef = useRef(0);
  const [historyPinnedSession, setHistoryPinnedSession] = useState(false);

  const currentAgent = useMemo(() => agents[0] || null, [agents]);
  const activeSession = session;
  const activeSessionId = activeSession?.sessionId || null;
  const defaultRuntimeModel = currentAgent?.runtimeModel || null;
  const activeRuntimeModel = activeSession?.runtimeModel || defaultRuntimeModel || null;
  const newChatRuntimeModel =
    activeSession?.runtimeModel &&
    defaultRuntimeModel &&
    activeSession.runtimeModel.modelRef !== defaultRuntimeModel.modelRef
      ? defaultRuntimeModel
      : null;
  const visibleMessages = useMemo(
    () => (activeSession?.messages || []).filter((message) => message.role !== 'system' && message.role !== 'tool'),
    [activeSession]
  );
  const visibleMessageEntries = useMemo(
    () =>
      visibleMessages.map((message, index) => ({
        key: `${messageFingerprint(message)}::${index}`,
        message,
      })),
    [visibleMessages]
  );
  const orderedTasks = useMemo(() => {
    const tasks = activeSession?.tasks || [];
    return [...tasks].sort((left, right) => {
      const leftTime = new Date(left.createdAt).getTime();
      const rightTime = new Date(right.createdAt).getTime();
      return rightTime - leftTime;
    });
  }, [activeSession]);
  const activeTasks = useMemo(
    () => orderedTasks.filter((task) => !isTerminalTaskStatus(task.status)),
    [orderedTasks]
  );
  const recentTaskResults = useMemo(
    () => toolResults.filter((result) => result.executionMode === 'task'),
    [toolResults]
  );
  const orderedApprovals = useMemo(() => {
    const approvals = activeSession?.approvals || [];
    return [...approvals].sort((left, right) => {
      const leftTime = new Date(left.createdAt).getTime();
      const rightTime = new Date(right.createdAt).getTime();
      return rightTime - leftTime;
    });
  }, [activeSession]);
  const pendingApprovals = useMemo(
    () => orderedApprovals.filter((approval) => approval.status === 'pending'),
    [orderedApprovals]
  );
  const needsLocalSetup = useMemo(
    () => error === LOCAL_SETUP_MESSAGE,
    [error]
  );
  const hasPendingTaskRequest = useMemo(
    () => recentTaskResults.some((result) => result.task && !isTerminalTaskStatus(result.task.status)),
    [recentTaskResults]
  );
  const visibleTaskCount = activeTasks.length > 0 ? activeTasks.length : hasPendingTaskRequest ? 1 : 0;
  const activityCount = pendingApprovals.length + visibleTaskCount;
  const hasActivity = orderedApprovals.length > 0 || orderedTasks.length > 0 || recentTaskResults.length > 0;
  const currentSessionSummary = useMemo(
    () => sessionHistory.find((item) => item.sessionId === activeSessionId) || null,
    [activeSessionId, sessionHistory]
  );
  const currentSessionLabel = useMemo(() => {
    if (currentSessionSummary) {
      return truncateText(currentSessionSummary.title || currentSessionSummary.lastMessagePreview || 'Current chat', 52);
    }
    if (visibleMessages.length > 0) {
      return truncateText(visibleMessages[0]?.content || 'Current chat', 52);
    }
    return '';
  }, [currentSessionSummary, visibleMessages]);
  const promptSuggestions = DEFAULT_PROMPTS;
  const isSessionsDrawerOpen = activeDrawer === 'sessions';
  const isActivityDrawerOpen = activeDrawer === 'activity';
  const showSessionLabel = Boolean(currentSessionLabel);
  const primaryRuntimeModelLabel = activeRuntimeModel
    ? `${newChatRuntimeModel ? 'Chat: ' : ''}${activeRuntimeModel.providerLabel} / ${activeRuntimeModel.modelId}`
    : '';
  const newChatRuntimeModelLabel = newChatRuntimeModel
    ? `Default: ${newChatRuntimeModel.providerLabel} / ${newChatRuntimeModel.modelId}`
    : '';

  const toggleDrawer = useCallback((drawer: Exclude<AgentShellDrawer, null>) => {
    setActiveDrawer((current) => (current === drawer ? null : drawer));
    setShowPromptSuggestions(false);
  }, []);

  const loadSessionRecord = useCallback(
    async (sessionId: string, options: { pinnedByHistory?: boolean } = {}) => {
      setLoadingSessionId(sessionId);
      try {
        const payload = await fetchRuntimeJson<HostedAgentSession>(
          `/agent/api/runtime/sessions/${encodeURIComponent(sessionId)}`,
          {},
          'Loading saved session'
        );
        setSession(payload);
        setHistoryPinnedSession(Boolean(options.pinnedByHistory));
        setToolResults([]);
        setError(null);
        writeStoredActiveSessionId(payload.sessionId);
        return payload;
      } catch (payload) {
        const message = parseRuntimeError(payload, `Failed to load session '${sessionId}'.`);
        setError(message);
        if (message.includes('404') || message.includes('Unknown') || message.includes('Not Found')) {
          writeStoredActiveSessionId(null);
        }
        return null;
      } finally {
        setLoadingSessionId((current) => (current === sessionId ? null : current));
      }
    },
    []
  );

  const loadSessionHistory = useCallback(
    async ({
      restoreSelection = false,
      focusSessionId = null,
      force = false,
    }: {
      restoreSelection?: boolean;
      focusSessionId?: string | null;
      force?: boolean;
    } = {}) => {
      if (!currentAgent) {
        return;
      }
      if (
        !force &&
        historyRequested &&
        Date.now() - lastHistoryLoadedAtRef.current < HISTORY_STALE_MS
      ) {
        return;
      }
      setHistoryRequested(true);
      setLoadingHistory(true);
      try {
        const payload = await fetchRuntimeJson<HostedSessionListResponse>(
          '/agent/api/runtime/sessions',
          {},
          'Loading saved sessions'
        );
        const sessions = payload.sessions || [];
        lastHistoryLoadedAtRef.current = Date.now();
        setSessionHistory(sessions);
        const activeId = activeSessionId;
        if (activeId && !sessions.some((item) => item.sessionId === activeId)) {
          setSession(null);
          setToolResults([]);
          writeStoredActiveSessionId(null);
        }
        if (!restoreSelection || activeId) {
          return;
        }
        const preferredId = focusSessionId || readStoredActiveSessionId();
        if (!preferredId) {
          return;
        }
        const preferredSession = sessions.find((item) => item.sessionId === preferredId);
        if (!preferredSession) {
          writeStoredActiveSessionId(null);
          return;
        }
        const preferredModelRef = runtimeModelRef(preferredSession.runtimeModel);
        const currentDefaultModelRef = runtimeModelRef(currentAgent?.runtimeModel);
        if (
          focusSessionId == null &&
          preferredModelRef &&
          currentDefaultModelRef &&
          preferredModelRef !== currentDefaultModelRef
        ) {
          writeStoredActiveSessionId(null);
          return;
        }
        await loadSessionRecord(preferredId, { pinnedByHistory: false });
      } catch (payload) {
        setError(parseRuntimeError(payload, 'Failed to load saved TerraFin Agent sessions.'));
      } finally {
        setLoadingHistory(false);
      }
    },
    [activeSessionId, currentAgent, historyRequested, loadSessionRecord]
  );

  const loadCatalog = useCallback(
    async ({ background = false, force = false }: { background?: boolean; force?: boolean } = {}) => {
      if (
        !force &&
        agents.length > 0 &&
        Date.now() - lastCatalogLoadedAtRef.current < CATALOG_STALE_MS
      ) {
        return;
      }
      setCatalogRequested(true);
      if (!background) {
        setLoadingCatalog(true);
        setShowWarmupHint(false);
      }
      try {
        const payload = await fetchRuntimeJson<{ agents?: HostedAgentDefinition[] }>(
          '/agent/api/runtime/agents',
          {},
          'Loading assistant catalog'
        );
        const nextAgents = payload.agents || [];
        lastCatalogLoadedAtRef.current = Date.now();
        setAgents(nextAgents);
        setError(
          nextAgents.length > 0
            ? null
            : LOCAL_SETUP_MESSAGE
        );
      } catch (payload) {
        if (!background) {
          setError(parseRuntimeError(payload, 'Failed to load TerraFin hosted agents.'));
        }
      } finally {
        if (!background) {
          setLoadingCatalog(false);
        }
      }
    },
    [agents.length]
  );

  useEffect(() => {
    if (!isOpen) {
      wasOpenRef.current = false;
      restoreAttemptedRef.current = false;
      return;
    }
    if (!wasOpenRef.current) {
      void loadCatalog({ force: agents.length === 0 });
      wasOpenRef.current = true;
    }
  }, [agents.length, isOpen, loadCatalog]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const refreshCatalog = () => {
      if (document.visibilityState === 'hidden') {
        return;
      }
      void loadCatalog({ background: true });
    };
    window.addEventListener('focus', refreshCatalog);
    document.addEventListener('visibilitychange', refreshCatalog);
    const timer = window.setInterval(refreshCatalog, MODEL_REFRESH_INTERVAL_MS);
    return () => {
      window.removeEventListener('focus', refreshCatalog);
      document.removeEventListener('visibilitychange', refreshCatalog);
      window.clearInterval(timer);
    };
  }, [isOpen, loadCatalog]);

  useEffect(() => {
    if (
      !isOpen ||
      !currentAgent ||
      activeSessionId ||
      restoreAttemptedRef.current ||
      creatingSession ||
      loadingSessionId
    ) {
      return;
    }
    restoreAttemptedRef.current = true;
    const preferredId = readStoredActiveSessionId();
    if (!preferredId) {
      return;
    }
    void (async () => {
      const payload = await loadSessionRecord(preferredId, { pinnedByHistory: false });
      const preferredModelRef = runtimeModelRef(payload?.runtimeModel);
      const currentDefaultModelRef = runtimeModelRef(currentAgent.runtimeModel);
      if (
        payload &&
        preferredModelRef &&
        currentDefaultModelRef &&
        preferredModelRef !== currentDefaultModelRef
      ) {
        setSession(null);
        setHistoryPinnedSession(false);
        setToolResults([]);
        writeStoredActiveSessionId(null);
      }
    })();
  }, [activeSessionId, creatingSession, currentAgent, isOpen, loadSessionRecord, loadingSessionId]);

  useEffect(() => {
    if (!isOpen || !isSessionsDrawerOpen || !currentAgent || loadingHistory) {
      return;
    }
    void loadSessionHistory({ force: !historyRequested });
  }, [currentAgent, historyRequested, isOpen, isSessionsDrawerOpen, loadSessionHistory, loadingHistory]);

  useEffect(() => {
    if (!loadingCatalog) {
      setShowWarmupHint(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setShowWarmupHint(true);
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [loadingCatalog]);

  useEffect(() => {
    if (!transcriptRef.current || !isOpen) {
      return;
    }
    transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [isOpen, visibleMessages]);

  useEffect(() => {
    if (!showPromptSuggestions) {
      return;
    }
    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (promptMenuRef.current?.contains(target)) {
        return;
      }
      setShowPromptSuggestions(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('touchstart', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('touchstart', handlePointerDown);
    };
  }, [showPromptSuggestions]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !activeSessionId || (activeTasks.length === 0 && !hasPendingTaskRequest)) {
      return;
    }
    let cancelled = false;

    const pollTasks = async () => {
      try {
        const payload = await fetchRuntimeJson<HostedTaskListResponse>(
          `/agent/api/runtime/sessions/${encodeURIComponent(activeSessionId)}/tasks`,
          {},
          'Refreshing background tasks'
        );
        if (cancelled) {
          return;
        }
        setSession((current) => {
          if (!current || current.sessionId !== activeSessionId) {
            return current;
          }
          return { ...current, tasks: payload.tasks || [] };
        });
      } catch {
        // Keep the current UI state if background polling fails transiently.
      }
    };

    void pollTasks();
    const timer = window.setInterval(() => {
      void pollTasks();
    }, TASK_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSessionId, activeTasks.length, hasPendingTaskRequest, isOpen]);

  useEffect(() => {
    if (activeDrawer === 'activity' && !hasActivity) {
      setActiveDrawer(null);
    }
  }, [activeDrawer, hasActivity]);

  useEffect(() => {
    const activeModelRef = runtimeModelRef(activeSession?.runtimeModel);
    const defaultModelRef = runtimeModelRef(defaultRuntimeModel);
    if (
      !isOpen ||
      !activeSession ||
      !activeModelRef ||
      !defaultModelRef ||
      activeModelRef === defaultModelRef ||
      historyPinnedSession
    ) {
      return;
    }
    setSession(null);
    setToolResults([]);
    setActiveDrawer(null);
    setShowPromptSuggestions(false);
    setHistoryPinnedSession(false);
    writeStoredActiveSessionId(null);
  }, [activeSession, defaultRuntimeModel, historyPinnedSession, isOpen]);

  const ensureSession = async () => {
    const existing = session;
    if (existing) {
      return existing;
    }
    const agentName = currentAgent?.name;
    if (!agentName) {
      return null;
    }
    setCreatingSession(true);
    try {
      const payload = (await fetchRuntimeJson<HostedAgentSession>(
        '/agent/api/runtime/sessions',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agentName,
            metadata: {
              viewContextId: getAgentViewContextId(),
            },
          }),
        },
        'Creating assistant session'
      )) as HostedAgentSession;
      setSession(payload);
      setHistoryPinnedSession(false);
      setToolResults([]);
      setError(null);
      writeStoredActiveSessionId(payload.sessionId);
      return payload;
    } catch (payload) {
      setError(parseRuntimeError(payload, `Failed to create a hosted session for ${agentName}.`));
      return null;
    } finally {
      setCreatingSession(false);
    }
  };

  const handleSend = async (content: string) => {
    if (!currentAgent || !content.trim()) {
      return;
    }
    setSending(true);
    setError(null);
    try {
      const session = activeSession ?? (await ensureSession());
      if (!session) {
        return;
      }
      const run = (await fetchRuntimeJson<HostedRunResponse>(
        `/agent/api/runtime/sessions/${encodeURIComponent(session.sessionId)}/messages`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        },
        'Running assistant request'
      )) as HostedRunResponse;
      const nextSession = mergeSessionFromRun(session, run);
      const previousMessageCount = session.messages.length;
      const nextVisibleMessages = nextSession.messages
        .slice(previousMessageCount)
        .filter((message) => message.role !== 'system' && message.role !== 'tool');
      setSession(nextSession);
      writeStoredActiveSessionId(nextSession.sessionId);
      setToolResults(run.toolResults || []);
      setDraft('');
      setShowPromptSuggestions(false);
      if (
        !run.finalMessage &&
        (run.toolResults || []).length === 0 &&
        !nextVisibleMessages.some((message) => message.role === 'assistant')
      ) {
        setError(`${AGENT_UI_NAME} did not return a visible reply. Please try again.`);
      }
    } catch (payload) {
      setError(parseRuntimeError(payload, 'Failed to run the hosted TerraFin agent.'));
    } finally {
      setSending(false);
    }
  };

  const handleClear = () => {
    setDraft('');
    setError(null);
    setSession(null);
    setHistoryPinnedSession(false);
    setToolResults([]);
    setActiveDrawer(null);
    setShowPromptSuggestions(false);
    writeStoredActiveSessionId(null);
  };

  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      const payload = await loadSessionRecord(sessionId, { pinnedByHistory: true });
      if (payload) {
        setActiveDrawer(null);
      }
    },
    [loadSessionRecord]
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      setDeletingSessionId(sessionId);
      try {
        await fetchRuntimeJson<HostedDeleteSessionResponse>(
          `/agent/api/runtime/sessions/${encodeURIComponent(sessionId)}`,
          {
            method: 'DELETE',
          },
          'Deleting saved session'
        );
        setSessionHistory((current) => current.filter((item) => item.sessionId !== sessionId));
        if (activeSessionId === sessionId) {
          setSession(null);
          setHistoryPinnedSession(false);
          setToolResults([]);
          setDraft('');
          writeStoredActiveSessionId(null);
        }
        setError(null);
      } catch (payload) {
        setError(parseRuntimeError(payload, 'Failed to delete the saved session.'));
      } finally {
        setDeletingSessionId((current) => (current === sessionId ? null : current));
      }
    },
    [activeSessionId, loadSessionHistory]
  );

  const handleCancelTask = useCallback(
    async (taskId: string) => {
      if (!activeSessionId) {
        return;
      }
      try {
        const task = await fetchRuntimeJson<HostedTask>(
          `/agent/api/runtime/tasks/${encodeURIComponent(taskId)}/cancel`,
          {
            method: 'POST',
          },
          'Cancelling background task'
        );
        setSession((current) => {
          if (!current || current.sessionId !== activeSessionId) {
            return current;
          }
          return {
            ...current,
            tasks: current.tasks.map((existing) => (existing.taskId === task.taskId ? task : existing)),
          };
        });
      } catch (payload) {
        setError(parseRuntimeError(payload, 'Failed to cancel the background task.'));
      }
    },
    [activeSessionId]
  );

  const handleApprovalDecision = useCallback(
    async (approvalId: string, decision: 'approve' | 'deny') => {
      if (!activeSessionId) {
        return;
      }
      try {
        const approval = await fetchRuntimeJson<HostedApproval>(
          `/agent/api/runtime/approvals/${encodeURIComponent(approvalId)}/${decision}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: null }),
          },
          `${decision === 'approve' ? 'Approving' : 'Denying'} assistant action`
        );
        setSession((current) => {
          if (!current || current.sessionId !== activeSessionId) {
            return current;
          }
          return {
            ...current,
            approvals: current.approvals.map((existing) =>
              existing.approvalId === approval.approvalId ? approval : existing
            ),
          };
        });
        setError(null);
      } catch (payload) {
        setError(parseRuntimeError(payload, 'Failed to record the approval decision.'));
      }
    },
    [activeSessionId]
  );

  const canClear = Boolean(draft.trim() || activeSession || error);
  const runtimeState = currentAgent
    ? sending
      ? 'Working'
      : 'Ready'
    : needsLocalSetup
      ? 'Local setup required'
      : loadingCatalog
        ? 'Loading'
        : 'Unavailable';

  if (!isOpen) {
    return (
      <div className="tf-agent-widget">
        <button
          type="button"
          className="tf-agent-widget__fab"
          onClick={() => setIsOpen(true)}
          aria-label={`Open ${AGENT_UI_NAME}`}
        >
          {AGENT_UI_NAME}
        </button>
      </div>
    );
  }

  return (
    <div className="tf-agent-widget tf-agent-widget--open">
      <button
        type="button"
        className="tf-agent-widget__backdrop"
        onClick={() => {
          setShowPromptSuggestions(false);
          setActiveDrawer(null);
          setIsOpen(false);
        }}
        aria-label={`Close ${AGENT_UI_NAME}`}
      />
      <section
        className="tf-agent-widget__panel"
        aria-label={AGENT_UI_NAME}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="tf-agent-widget__header">
          <div className="tf-agent-widget__header-copy">
            <div className="tf-agent-widget__title-row">
              <div className="tf-agent-widget__title">{AGENT_UI_NAME}</div>
              <span className={`tf-agent-widget__runtime-chip tf-agent-widget__runtime-chip--${runtimeState.toLowerCase().replace(/\s+/g, '-')}`}>
                {runtimeState}
              </span>
              {primaryRuntimeModelLabel ? (
                <span className="tf-agent-widget__meta-pill tf-agent-widget__meta-pill--inline">
                  {primaryRuntimeModelLabel}
                </span>
              ) : null}
            </div>
            {showSessionLabel || newChatRuntimeModelLabel ? (
              <div className="tf-agent-widget__meta-row">
                {showSessionLabel ? (
                  <span className="tf-agent-widget__session-pill">{currentSessionLabel}</span>
                ) : null}
                {newChatRuntimeModelLabel ? (
                <span className="tf-agent-widget__meta-pill tf-agent-widget__meta-pill--accent">
                    {newChatRuntimeModelLabel}
                </span>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="tf-agent-widget__header-actions">
            <button
              type="button"
              className={`tf-agent-widget__header-button ${
                isSessionsDrawerOpen ? 'tf-agent-widget__header-button--active' : ''
              }`}
              onClick={() => toggleDrawer('sessions')}
              disabled={loadingHistory}
            >
              Sessions
            </button>
            {hasActivity ? (
              <button
                type="button"
                className={`tf-agent-widget__header-button ${
                  isActivityDrawerOpen ? 'tf-agent-widget__header-button--active' : ''
                } ${pendingApprovals.length > 0 ? 'tf-agent-widget__header-button--attention' : ''}`}
                onClick={() => toggleDrawer('activity')}
              >
                Activity{activityCount > 0 ? ` ${activityCount}` : ''}
              </button>
            ) : null}
            <button
              type="button"
              className="tf-agent-widget__header-button"
              onClick={handleClear}
              disabled={sending || creatingSession}
            >
              New
            </button>
            <button
              type="button"
              className="tf-agent-widget__close"
              onClick={() => setIsOpen(false)}
              aria-label={`Close ${AGENT_UI_NAME}`}
            >
              Close
            </button>
          </div>
        </div>

        <div className="tf-agent-widget__body">
          {isSessionsDrawerOpen ? (
            <div className="tf-agent-widget__drawer" aria-label="Saved sessions">
              <div className="tf-agent-widget__drawer-header">
                <div className="tf-agent-widget__drawer-title">Recent sessions</div>
                {activeSession ? (
                  <div className="tf-agent-widget__drawer-copy">Pick a past chat or start fresh.</div>
                ) : null}
              </div>
              {loadingHistory ? (
                <div className="tf-agent-history__loading">Loading saved sessions...</div>
              ) : sessionHistory.length > 0 ? (
                <div className="tf-agent-history__list tf-agent-history__list--drawer">
                  {sessionHistory.map((item) => {
                    const isActive = activeSessionId === item.sessionId;
                    const label = truncateText(item.title || item.lastMessagePreview || 'Untitled session', 60);
                    const metaParts = [
                      formatSessionTimestamp(item.lastMessageAt || item.updatedAt),
                      item.messageCount > 0 ? `${item.messageCount} msg${item.messageCount === 1 ? '' : 's'}` : '',
                      item.pendingTaskCount > 0 ? `${item.pendingTaskCount} active` : '',
                    ].filter(Boolean);
                    return (
                      <div
                        key={item.sessionId}
                        className={`tf-agent-history__item ${isActive ? 'tf-agent-history__item--active' : ''}`}
                      >
                        <button
                          type="button"
                          className="tf-agent-history__select"
                          onClick={() => void handleSelectSession(item.sessionId)}
                          disabled={loadingSessionId === item.sessionId || deletingSessionId === item.sessionId}
                        >
                          <div className="tf-agent-history__label">{label}</div>
                          {metaParts.length > 0 ? (
                            <div className="tf-agent-history__meta">{metaParts.join(' · ')}</div>
                          ) : null}
                        </button>
                        <button
                          type="button"
                          className="tf-agent-history__delete"
                          onClick={() => void handleDeleteSession(item.sessionId)}
                          disabled={deletingSessionId === item.sessionId || loadingSessionId === item.sessionId}
                          aria-label={`Delete session ${label}`}
                        >
                          {deletingSessionId === item.sessionId ? 'Deleting...' : 'Delete'}
                        </button>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="tf-agent-widget__drawer-empty">
                  No saved sessions yet. Once you start chatting, recent conversations will appear here.
                </div>
              )}
            </div>
          ) : null}

          {isActivityDrawerOpen ? (
            <div className="tf-agent-widget__drawer" aria-label="Activity">
              {orderedApprovals.length > 0 ? (
                <div className="tf-agent-widget__drawer-section">
                  <div className="tf-agent-widget__drawer-header">
                    <div className="tf-agent-widget__drawer-title">Approval requests</div>
                    <div className="tf-agent-widget__drawer-copy">
                      {pendingApprovals.length > 0 ? `${pendingApprovals.length} pending` : 'Resolved'}
                    </div>
                  </div>
                  <div className="tf-agent-approval-list">
                    {orderedApprovals.map((approval) => (
                      <div
                        key={approval.approvalId}
                        className={`tf-agent-approval-card tf-agent-approval-card--${approval.status}`}
                      >
                        <div className="tf-agent-approval-card__meta">
                          <div className="tf-agent-approval-card__label">{formatApprovalLabel(approval)}</div>
                          <span className={`tf-agent-approval-badge tf-agent-approval-badge--${approval.status}`}>
                            {approval.status}
                          </span>
                        </div>
                        <div className="tf-agent-approval-card__detail">{approval.reason}</div>
                        <div className="tf-agent-approval-card__actions">
                          <span className="tf-agent-approval-card__capability">{approval.action}</span>
                          {approval.status === 'pending' ? (
                            <div className="tf-agent-approval-card__buttons">
                              <button
                                type="button"
                                className="tf-agent-approval-card__button tf-agent-approval-card__button--approve"
                                onClick={() => void handleApprovalDecision(approval.approvalId, 'approve')}
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                className="tf-agent-approval-card__button tf-agent-approval-card__button--deny"
                                onClick={() => void handleApprovalDecision(approval.approvalId, 'deny')}
                              >
                                Deny
                              </button>
                            </div>
                          ) : (
                            <span className="tf-agent-approval-card__hint">
                              {approval.status === 'approved'
                                ? 'Resend the request to continue.'
                                : approval.status === 'consumed'
                                  ? 'Already used.'
                                  : 'Request was declined.'}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {orderedTasks.length > 0 || recentTaskResults.length > 0 ? (
                <div className="tf-agent-widget__drawer-section">
                  <div className="tf-agent-widget__drawer-header">
                    <div className="tf-agent-widget__drawer-title">Background tasks</div>
                    <div className="tf-agent-widget__drawer-copy">
                      {activeTasks.length > 0 ? `${activeTasks.length} active` : 'All settled'}
                    </div>
                  </div>
                  <div className="tf-agent-task-list">
                    {orderedTasks.map((task) => (
                      <div key={task.taskId} className={`tf-agent-task-card tf-agent-task-card--${task.status}`}>
                        <div className="tf-agent-task-card__meta">
                          <div className="tf-agent-task-card__label">{formatTaskLabel(task)}</div>
                          <span className={`tf-agent-task-badge tf-agent-task-badge--${task.status}`}>
                            {task.status}
                          </span>
                        </div>
                        <div className="tf-agent-task-card__detail">{formatTaskDetail(task)}</div>
                        <div className="tf-agent-task-card__actions">
                          <span className="tf-agent-task-card__capability">{task.capabilityName}</span>
                          {!isTerminalTaskStatus(task.status) ? (
                            <button
                              type="button"
                              className="tf-agent-task-card__cancel"
                              onClick={() => void handleCancelTask(task.taskId)}
                            >
                              Cancel
                            </button>
                          ) : null}
                        </div>
                      </div>
                    ))}
                    {orderedTasks.length === 0 ? (
                      <div className="tf-agent-task-card tf-agent-task-card--accepted">
                        <div className="tf-agent-task-card__label">
                          {recentTaskResults[0]?.task?.description || 'Background task accepted'}
                        </div>
                        <div className="tf-agent-task-card__detail">
                          Waiting for the runtime to publish task state.
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {error ? <div className="tf-agent-error-banner">{error}</div> : null}

          <div className="tf-agent-chat-shell">
            {hasActivity && !isActivityDrawerOpen ? (
              <div className="tf-agent-widget__notice-row">
                {pendingApprovals.length > 0 ? (
                  <button
                    type="button"
                    className="tf-agent-widget__notice tf-agent-widget__notice--attention"
                    onClick={() => toggleDrawer('activity')}
                  >
                    {pendingApprovals.length} approval{pendingApprovals.length === 1 ? '' : 's'} waiting
                  </button>
                ) : null}
                {visibleTaskCount > 0 ? (
                  <button
                    type="button"
                    className="tf-agent-widget__notice"
                    onClick={() => toggleDrawer('activity')}
                  >
                    {visibleTaskCount} background task{visibleTaskCount === 1 ? '' : 's'} running
                  </button>
                ) : null}
              </div>
            ) : null}

            <div
              ref={transcriptRef}
              className={`tf-agent-transcript tf-agent-transcript--widget ${
                visibleMessages.length > 0 ? 'tf-agent-transcript--live' : 'tf-agent-transcript--idle'
              }`}
            >
              {sending ? (
                <div className="tf-agent-widget__activity">
                  <div className="tf-agent-widget__activity-spinner" aria-hidden="true" />
                  <div className="tf-agent-widget__activity-copy">Working on your request...</div>
                </div>
              ) : null}
              {visibleMessageEntries.map(({ key, message }) => (
                <AgentMessageItem key={key} message={message} messageKey={key} />
              ))}
              {visibleMessages.length === 0 && loadingCatalog ? (
                <div className="tf-agent-widget__placeholder">
                  <div className="tf-agent-widget__placeholder-spinner" aria-hidden="true" />
                  <div className="tf-agent-widget__placeholder-title">Warming up {AGENT_UI_NAME}</div>
                  <div className="tf-agent-widget__placeholder-copy">
                    {showWarmupHint
                      ? 'This can take a moment on a cold start. Once the runtime responds, the agent will be ready.'
                      : 'Fetching the available hosted tools for this deployment.'}
                  </div>
                </div>
              ) : null}
              {visibleMessages.length === 0 && creatingSession ? (
                <div className="tf-agent-widget__placeholder">
                  <div className="tf-agent-widget__placeholder-spinner" aria-hidden="true" />
                  <div className="tf-agent-widget__placeholder-title">Starting a conversation</div>
                  <div className="tf-agent-widget__placeholder-copy">
                    Creating a fresh session for the assistant.
                  </div>
                </div>
              ) : null}
              {visibleMessages.length === 0 && !loadingCatalog && !creatingSession && !sending ? (
                <div className="tf-agent-widget__placeholder">
                  <div className="tf-agent-widget__placeholder-title">
                    {agents.length > 0
                      ? 'Start with a question'
                      : needsLocalSetup
                        ? `Set up ${AGENT_UI_NAME} locally`
                        : `${AGENT_UI_NAME} not ready`}
                  </div>
                  <div className="tf-agent-widget__placeholder-copy">
                    {agents.length > 0
                      ? 'Ask directly below, or open the ? button if you want a few examples.'
                      : error ||
                        'The hosted agent runtime is not responding on this deployment yet.'}
                  </div>
                  {agents.length === 0 ? (
                    <div className="tf-agent-widget__placeholder-actions">
                      <button
                        type="button"
                        className="tf-agent-secondary"
                        onClick={() => {
                          setError(null);
                          void loadCatalog({ force: true });
                        }}
                        disabled={loadingCatalog}
                      >
                        Retry
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="tf-agent-composer">
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask about a stock, portfolio, DCF, chart, or macro setup."
                rows={3}
                disabled={!currentAgent || sending || creatingSession || loadingCatalog}
                className="tf-agent-composer__input"
              />
              <div className="tf-agent-composer__actions">
                <div className="tf-agent-composer__actions-left">
                  {promptSuggestions.length > 0 ? (
                    <div ref={promptMenuRef} className="tf-agent-composer__examples-menu">
                      {showPromptSuggestions ? (
                        <div className="tf-agent-composer__examples" aria-label="Example prompts">
                          {promptSuggestions.map((prompt) => (
                            <button
                              key={prompt}
                              type="button"
                              className="tf-agent-suggestion"
                              disabled={!currentAgent || sending || creatingSession || loadingCatalog}
                              onClick={() => void handleSend(prompt)}
                            >
                              {prompt}
                            </button>
                          ))}
                        </div>
                      ) : null}
                      <button
                        type="button"
                        className={`tf-agent-composer__examples-toggle ${
                          showPromptSuggestions ? 'tf-agent-composer__examples-toggle--active' : ''
                        }`}
                        onClick={() => setShowPromptSuggestions((current) => !current)}
                        aria-label={showPromptSuggestions ? 'Hide example prompts' : 'Show example prompts'}
                        aria-expanded={showPromptSuggestions}
                        disabled={sending || creatingSession || loadingCatalog}
                      >
                        ?
                      </button>
                    </div>
                  ) : null}
                </div>
                <div className="tf-agent-composer__actions-right">
                  <button
                    type="button"
                    className="tf-agent-secondary"
                    onClick={handleClear}
                    disabled={!canClear || sending}
                  >
                    Clear
                  </button>
                  <button
                    type="button"
                    className="tf-agent-primary"
                    onClick={() => void handleSend(draft)}
                    disabled={!currentAgent || !draft.trim() || sending || creatingSession || loadingCatalog}
                  >
                    {sending ? 'Running...' : 'Send'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

export default GlobalAgentWidget;
