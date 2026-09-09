import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AgentShellDrawer } from './layout';
import { getAgentViewContextId } from './viewContext';
import { useTerminalStore } from '../terminal/store';

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
  runtimeConfigured?: boolean;
  runtimeSetupMessage?: string | null;
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

const isSameOriginUrl = (value: string) => {
  try {
    return new URL(value, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
};

const isInternalOnly = (message: HostedConversationMessage) =>
  Boolean((message.metadata as Record<string, unknown> | undefined)?.internalOnly);

const transcriptSignature = (messages: HostedConversationMessage[] | undefined) => {
  const real = (messages || []).filter((message) => !isInternalOnly(message));
  const visible = real.filter(
    (message) => message.role !== 'system' && message.role !== 'tool'
  );
  return `${real.length}:${visible[visible.length - 1]?.createdAt ?? ''}`;
};

type SendStatusState =
  | {
      kind: 'working';
      content: string;
      createdAt: string;
    }
  | {
      kind: 'error';
      content: string;
      createdAt: string;
      // What retires this error. 'nothing' — the message never reached the
      // transcript, so only the user can act. 'turn-end' — the notice describes a
      // turn rather than the message, so that turn ending retires it, whether it
      // ends by answering or by dying. Two booleans let the exits disagree about
      // the same state; one question cannot.
      retiredBy: 'nothing' | 'turn-end';
    }
  | null;

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
const RESYNC_POLL_INTERVAL_MS = 5000;
const SCROLL_PIN_SLACK_PX = 48;
const SEND_REQUEST_TIMEOUT_MS = 240000;
const SEND_TOOL_POLL_INTERVAL_MS = 1500;
const SEND_RECONCILE_POLL_MS = 1500;
const SEND_RECONCILE_WINDOW_MS = 8000;
// A foreground turn dies with its own request, so anything older than the
// send timeout plus its reconcile window is history, not a stall.
const RESYNC_LIVE_WINDOW_SECONDS =
  (SEND_REQUEST_TIMEOUT_MS + SEND_RECONCILE_WINDOW_MS) / 1000;
const TASK_POLL_INTERVAL_MS = 1500;
const MODEL_REFRESH_INTERVAL_MS = 60000;
const CATALOG_STALE_MS = 60000;
const HISTORY_STALE_MS = 15000;
const AGENT_UI_NAME = 'TerraFin Agent';
const ACTIVE_SESSION_STORAGE_KEY = 'terrafin.agent.active-session-id';
const LOCAL_SETUP_MESSAGE = `${AGENT_UI_NAME} needs a local hosted model setup before it can run here.

To use it locally:
- choose a hosted model with TERRAFIN_AGENT_MODEL_REF
- add provider credentials such as OPENAI_API_KEY or GEMINI_API_KEY
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
        {message.role === 'assistant' ? (
          // The agent answers in markdown. Rendering it as a raw string put every
          // ##, ** and list dash on screen as literal characters. Only assistant
          // turns: user text is shown as typed, and tool/system bodies are JSON.
          <div className="tf-agent-message__body tf-agent-message__body--md">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ node, ...props }) => (
                  // Without this the first citation click replaces the document,
                  // closing the panel and killing any in-flight turn.
                  <a {...props} target="_blank" rel="noopener noreferrer" />
                ),
                img: ({ node, src, alt, ...props }) => {
                  // A remote src is an outbound GET, with its query string, that
                  // the model or injected filing text chose — and there is no CSP.
                  // Same-origin only; anything else degrades to its alt text.
                  if (typeof src !== 'string' || !src || !isSameOriginUrl(src)) {
                    return (
                      <span className="tf-agent-message__img-blocked">
                        {alt || '[image omitted]'}
                      </span>
                    );
                  }
                  return (
                    <img
                      {...props}
                      src={src}
                      alt={alt || ''}
                      className="tf-agent-message__img"
                      onLoad={(event) => {
                        // An unloaded image is a zero-height box, so the pin ran
                        // against a scrollHeight that excluded it. Only re-pin if
                        // the user is still at the bottom — re-pinning always
                        // yanked anyone who had scrolled up to read.
                        const scroller = event.currentTarget.closest('.tf-agent-transcript');
                        if (!scroller) {
                          return;
                        }
                        const distance =
                          scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
                        if (distance < SCROLL_PIN_SLACK_PX) {
                          scroller.scrollTop = scroller.scrollHeight;
                        }
                      }}
                    />
                  );
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="tf-agent-message__body">{message.content}</div>
        )}
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

const buildEphemeralMessage = (
  role: HostedConversationMessage['role'],
  content: string,
  createdAt: string = new Date().toISOString()
): HostedConversationMessage => ({
  role,
  content,
  createdAt,
});

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
    // en-US, not device locale — undefined rendered timestamps in Korean on
    // Korean-locale devices. The UI is English.
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(date);
  } catch {
    return date.toLocaleString('en-US');
  }
};

const runtimeModelRef = (runtimeModel: HostedRuntimeModel | null | undefined) =>
  typeof runtimeModel?.modelRef === 'string' ? runtimeModel.modelRef : '';

const agentFingerprint = (agent: HostedAgentDefinition) =>
  [
    agent.name,
    agent.description,
    runtimeModelRef(agent.runtimeModel),
    agent.runtimeConfigured === false ? 'not-configured' : 'configured',
    agent.runtimeSetupMessage || '',
    agent.tools
      .map((tool) => `${tool.name}:${tool.executionMode}:${tool.capabilityName}`)
      .join('|'),
  ].join('::');

const sameAgents = (left: HostedAgentDefinition[] = [], right: HostedAgentDefinition[] = []) => {
  if (left.length !== right.length) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    if (agentFingerprint(left[index]) !== agentFingerprint(right[index])) {
      return false;
    }
  }
  return true;
};

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

const taskFingerprint = (task: HostedTask) =>
  [
    task.taskId,
    task.status,
    task.error || '',
    JSON.stringify(task.progress || {}),
    JSON.stringify(task.result || {}),
  ].join('::');

const sameTaskLists = (left: HostedTask[] = [], right: HostedTask[] = []) => {
  if (left.length !== right.length) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    if (taskFingerprint(left[index]) !== taskFingerprint(right[index])) {
      return false;
    }
  }
  return true;
};

const syncToolResultsWithTasks = (
  currentResults: HostedToolResult[],
  nextTasks: HostedTask[]
) => {
  if (currentResults.length === 0) {
    return currentResults;
  }
  const tasksById = new Map(nextTasks.map((task) => [task.taskId, task]));
  let changed = false;
  const nextResults = currentResults.map((result) => {
    const taskId = result.task?.taskId;
    if (!taskId) {
      return result;
    }
    const updatedTask = tasksById.get(taskId);
    if (!updatedTask) {
      return result;
    }
    if (
      result.task?.status === updatedTask.status &&
      result.task?.description === updatedTask.description
    ) {
      return result;
    }
    changed = true;
    return {
      ...result,
      task: {
        taskId: updatedTask.taskId,
        status: updatedTask.status,
        description: updatedTask.description,
      },
    };
  });
  return changed ? nextResults : currentResults;
};

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

const TURN_DEATH_MESSAGE: Record<string, string> = {
  'mid-tool':
    'A tool call in this chat was interrupted before it finished. Send your message again — it starts a clean exchange using the data already gathered.',
  'mid-turn':
    'This chat gathered its data but stopped before answering. Send your message again.',
  'no-answer': 'This chat stopped before it could answer. Send your message again.',
};

// The server's 409 says "wait for it to finish" — right at the instant of
// refusal, wrong for the rest of a notice only the user can retire.
// Must match TURN_IN_FLIGHT_ERROR_CODE in interface/agent/data_routes.py.
const TURN_IN_FLIGHT_ERROR_CODE = 'hosted_agent_turn_in_flight';

const SEND_REFUSED_MESSAGE =
  'Another window or session was already working on this chat, so your message was not sent. It is back in the composer — send it again.';

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

const fetchRuntimeJson = async <T,>(
  url: string,
  options: RequestInit = {},
  timeoutLabel: string,
  timeoutMs: number = REQUEST_TIMEOUT_MS
): Promise<T> => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
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

const delay = (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });

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
  const [pendingMessages, setPendingMessages] = useState<HostedConversationMessage[]>([]);
  const [sendStatus, setSendStatus] = useState<SendStatusState>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  // Whether the transcript is scrolled to the bottom. Every auto-scroll is gated
  // on it so a user reading earlier output is never dragged down.
  const pinnedRef = useRef(true);
  const promptMenuRef = useRef<HTMLDivElement | null>(null);
  const wasOpenRef = useRef(false);
  const restoreAttemptedRef = useRef(false);
  const lastCatalogLoadedAtRef = useRef(0);
  const lastHistoryLoadedAtRef = useRef(0);
  const [historyPinnedSession, setHistoryPinnedSession] = useState(false);

  const currentAgent = useMemo(() => agents[0] || null, [agents]);
  const activeSession = session;
  const activeSessionId = activeSession?.sessionId || null;
  const isRuntimeConfigured = currentAgent?.runtimeConfigured !== false;
  const runtimeSetupMessage =
    (typeof currentAgent?.runtimeSetupMessage === 'string' && currentAgent.runtimeSetupMessage.trim()) ||
    LOCAL_SETUP_MESSAGE;
  const defaultRuntimeModel = currentAgent?.runtimeModel || null;
  const activeRuntimeModel = isRuntimeConfigured ? activeSession?.runtimeModel || defaultRuntimeModel || null : null;
  const newChatRuntimeModel =
    isRuntimeConfigured &&
    activeSession?.runtimeModel &&
    defaultRuntimeModel &&
    activeSession.runtimeModel.modelRef !== defaultRuntimeModel.modelRef
      ? defaultRuntimeModel
      : null;
  const visibleMessages = useMemo(
    () => (activeSession?.messages || []).filter((message) => message.role !== 'system' && message.role !== 'tool'),
    [activeSession]
  );
  const displayedMessages = useMemo(
    () => mergeMessages(visibleMessages, pendingMessages),
    [pendingMessages, visibleMessages]
  );
  const visibleMessageEntries = useMemo(
    () =>
      displayedMessages.map((message, index) => ({
        key: `${messageFingerprint(message)}::${index}`,
        message,
      })),
    [displayedMessages]
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
    () => !isRuntimeConfigured || error === LOCAL_SETUP_MESSAGE || error === runtimeSetupMessage,
    [error, isRuntimeConfigured, runtimeSetupMessage]
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
  const chatAvailable = Boolean(currentAgent && isRuntimeConfigured);

  const toggleDrawer = useCallback((drawer: Exclude<AgentShellDrawer, null>) => {
    setActiveDrawer((current) => (current === drawer ? null : drawer));
    setShowPromptSuggestions(false);
  }, []);

  const fetchSessionPayload = useCallback(async (sessionId: string) => {
    return fetchRuntimeJson<HostedAgentSession>(
      `/agent/api/runtime/sessions/${encodeURIComponent(sessionId)}`,
      {},
      'Loading saved session'
    );
  }, []);

  const loadSessionRecord = useCallback(
    async (sessionId: string, options: { pinnedByHistory?: boolean } = {}) => {
      setLoadingSessionId(sessionId);
      try {
        const payload = await fetchSessionPayload(sessionId);
        pinnedRef.current = true; // opening a session shows its latest turn
        setSession(payload);
        setHistoryPinnedSession(Boolean(options.pinnedByHistory));
        setToolResults([]);
        setPendingMessages([]);
        setSendStatus(null);
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
    [fetchSessionPayload]
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
        setAgents((current) => (sameAgents(current, nextAgents) ? current : nextAgents));
        setError(
          nextAgents.length === 0
            ? LOCAL_SETUP_MESSAGE
            : nextAgents[0]?.runtimeConfigured === false
              ? nextAgents[0]?.runtimeSetupMessage || LOCAL_SETUP_MESSAGE
              : null
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
    if (isRuntimeConfigured) {
      return;
    }
    setSession(null);
    setHistoryPinnedSession(false);
    setToolResults([]);
    setPendingMessages([]);
    setSendStatus(null);
    setActiveDrawer(null);
    setShowPromptSuggestions(false);
    writeStoredActiveSessionId(null);
    setError(runtimeSetupMessage);
  }, [isRuntimeConfigured, runtimeSetupMessage]);

  // Reopening must resync, and keep resyncing until the reply lands. The restore
  // effect below early-returns while a session is active, so a panel closed
  // mid-run keeps its pre-send snapshot even though the server already has the
  // answer. Uses fetchSessionPayload, not loadSessionRecord: the latter resets
  // historyPinnedSession and pendingMessages, which would drop a pinned session
  // and wipe a message still in flight.
  const sendingRef = useRef(false);
  useEffect(() => {
    sendingRef.current = sending;
  }, [sending]);
  const sendStatusRef = useRef<SendStatusState>(null);
  useEffect(() => {
    sendStatusRef.current = sendStatus;
  }, [sendStatus]);
  // The send flow reports "ran but returned nothing" through `error` with
  // sendStatus cleared, so guarding on sendStatus alone left a spinner counting
  // up over a finished run.
  const errorRef = useRef<string | null>(null);
  useEffect(() => {
    errorRef.current = error;
  }, [error]);
  // Whether an arriving answer actually contradicts the standing banner.
  // `setError` is shared by concerns a turn has nothing to do with, so clearing
  // it on any completed turn made unrelated failures vanish. Only the two setup
  // messages are disproved by an answer arriving at all.
  const answerContradictsErrorRef = useRef(false);
  useEffect(() => {
    answerContradictsErrorRef.current =
      error != null && (error === LOCAL_SETUP_MESSAGE || error === runtimeSetupMessage);
  }, [error, runtimeSetupMessage]);
  useEffect(() => {
    // Read through a ref so the resync effect does not list activeSession as a
    // dependency: its own setSession would otherwise remount it mid-turn.
    activeSessionRef.current = activeSession;
  }, [activeSession]);
  // Growth, not the clock, tells us whether a turn is alive. `elapsed` subtracts a
  // server timestamp from a client clock, so skew alone must never silence the
  // indicator, and an unchanged payload must not re-set state — `setSession`
  // returns a new object each poll, which re-fires the scroll-to-bottom effect.
  const seenSignatureRef = useRef<string | null>(null);
  const seededForSessionRef = useRef<string | null>(null);
  const activeSessionRef = useRef<HostedAgentSession | null>(null);
  useEffect(() => {
    if (!isOpen || !activeSessionId || sending || loadingSessionId) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    let ticks = 0;
    const stop = () => {
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
    };
    const check = async () => {
      if (cancelled || sendingRef.current) {
        stop();
        return;
      }
      ticks += 1;
      let payload:
        | (HostedAgentSession & {
            capabilityCalls?: Array<{
              capabilityName: string;
              calledAt: string;
              inputs?: Record<string, unknown>;
            }>;
          })
        | null = null;
      try {
        payload = await fetchSessionPayload(activeSessionId);
      } catch {
        return;
      }
      if (cancelled || sendingRef.current || !payload) {
        return;
      }
      const visible = (payload.messages || []).filter(
        (message) => message.role !== 'system' && message.role !== 'tool'
      );
      const last = visible[visible.length - 1];
      const signature = transcriptSignature(payload.messages);
      const grew = seenSignatureRef.current !== signature;
      seenSignatureRef.current = signature;
      if (grew) {
        setSession(payload);
      }
      // The server reports whether it is running a turn. Every transcript-derived
      // signal is blind during a model call, which is where a multi-step turn
      // spends most of its time: `calledAt` is stamped only after a capability
      // returns, unanswered tool_use blocks cover tool time only, and growth
      // covers neither.
      const meta = payload.metadata as Record<string, unknown> | undefined;
      // Liveness comes from the server's in-flight flag alone. `pendingToolCalls`
      // is a property of the transcript, not a signal: an abandoned tool_use is
      // durable and can never be answered, so OR-ing it in pinned both exits shut
      // for the life of the session. Tool time is already inside turnInFlight.
      const turnInFlight = meta?.turnInFlight === true;
      const death = typeof meta?.turnUnfinished === 'string' ? meta.turnUnfinished : null;
      if (!turnInFlight && death) {
        const standing = sendStatusRef.current;
        const supersedes = standing?.kind === 'error' && standing.retiredBy === 'nothing';
        if (supersedes) {
          // Only the user can retire this one, so the death must not overwrite
          // it. A 'turn-end' error falls through: that turn has now ended.
          //
          // `errorRef` is deliberately not consulted — it is a different UI slot
          // that already coexists with this one, and consulting it let any stale
          // banner suppress the death and stop the poller for good, since
          // `error` is not in this effect's dependencies.
          stop();
          return;
        }
        // Nothing is running and the newest tool call has no result: the turn died
        // between appending the call and appending its result. Without this, a
        // restart mid-tool showed the model's preamble as the finished answer.
        setSendStatus({
          kind: 'error',
          content: TURN_DEATH_MESSAGE[death] ?? TURN_DEATH_MESSAGE['no-answer'],
          createdAt: new Date().toISOString(),
          retiredBy: 'turn-end',
        });
        stop();
        return;
      }
      if (
        last &&
        last.role === 'assistant' &&
        !turnInFlight &&
        !death
      ) {
        // The turn is done. An assistant message can also be a preamble before
        // more tool calls (loop.py:295-302 appends it before checking
        // tool_calls), and the tool-use message itself is internalOnly and
        // filtered from this payload — so a running tool is detected through
        // capabilityCalls, not through transcript growth, which cannot tell a
        // finished answer from a slow tool.
        // turnUnfinished is excluded above: a turn that died leaves the model's
        // preamble as the last visible message, so this branch would read it as a
        // finished answer and erase the send error along with it.
        const failed = sendStatusRef.current?.kind === 'error' ? sendStatusRef.current : null;
        if (answerContradictsErrorRef.current && grew) {
          // `grew` is load-bearing: this branch fires for any session with
          // prior history, so without it a setup banner raised mid-conversation
          // was cleared by the *previous* turn's answer within one tick.
          setError(null);
        }
        // Clear a failure only if the turn it described has ended. One that only
        // the user can retire is the sole record that anything went wrong, and
        // another turn's answer must not erase it.
        if (!failed || failed.retiredBy === 'turn-end') {
          // The turn this notice described has ended, so the notice is spent.
          setSendStatus(null);
        }
        stop();
        return;
      }
      if (sendStatusRef.current?.kind === 'error' || errorRef.current) {
        // A send already reported a failure; that is the truth, not a spinner.
        // But a 409 means another turn is genuinely running, so keep polling for
        // its answer instead of going dark until the panel is reopened.
        if (!turnInFlight) {
          stop();
        }
        return;
      }
      if (last) {
        // Reopening must look exactly like never having closed: same strings the
        // send flow's poller produces, rebuilt from the session payload.
        const turnStartedAt = last.createdAt ? new Date(last.createdAt).getTime() : Date.now();
        const elapsed = Math.max(0, Math.floor((Date.now() - turnStartedAt) / 1000));
        const turnCalls = (payload.capabilityCalls || []).filter(
          (call) => new Date(call.calledAt).getTime() >= turnStartedAt
        );
        let content: string;
        if (turnCalls.length === 0) {
          content = `Thinking… (${elapsed}s)`;
        } else {
          const latest = turnCalls[turnCalls.length - 1];
          const focus = latest.inputs && (latest.inputs.ticker || latest.inputs.name);
          const label = focus ? `${latest.capabilityName} · ${focus}` : latest.capabilityName;
          const suffix = turnCalls.length > 1 ? ` · ${turnCalls.length} tools` : '';
          content = `Running ${label}…${suffix} (${elapsed}s)`;
        }
        // Tick count as well as elapsed: a server clock running ahead of the
        // browser clamps elapsed to 0 forever, so the time test alone could never
        // retire a dead turn.
        const outOfPatience =
          elapsed > RESYNC_LIVE_WINDOW_SECONDS ||
          ticks * (RESYNC_POLL_INTERVAL_MS / 1000) > RESYNC_LIVE_WINDOW_SECONDS;
        if (outOfPatience && !grew && !turnInFlight) {
          // Stale, not moving, and no tool outstanding: history being read, not a
          // stall. `!grew` alone did not cover a slow call — the payload only
          // grows when a result lands, so a single long tool looked idle. Clear any
          // spinner rather than freezing one on screen, and say nothing. The
          // `!grew` term means a skewed clock cannot silence a live turn.
          setSendStatus(null);
          stop();
          return;
        }
        if (sendStatusRef.current?.content !== content) {
          setSendStatus({ kind: 'working', content, createdAt: new Date().toISOString() });
        }
        return;
      }
      stop();
    };
    if (seededForSessionRef.current !== activeSessionId) {
      // Seed once per session. Seeding on every remount let the effect's own
      // setSession reset the signature, so `grew` became an edge that guarded
      // for milliseconds instead of a tick.
      seededForSessionRef.current = activeSessionId;
      seenSignatureRef.current = transcriptSignature(activeSessionRef.current?.messages);
    }
    void check();
    timer = window.setInterval(() => void check(), RESYNC_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      stop();
    };
  }, [activeSessionId, fetchSessionPayload, isOpen, loadingSessionId, sending]);

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
        setPendingMessages([]);
        setSendStatus(null);
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
    const scroller = transcriptRef.current;
    if (!scroller || !isOpen) {
      return;
    }
    // Opening the panel is an unambiguous "show me the latest".
    pinnedRef.current = true;
    const track = () => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      pinnedRef.current = distance < SCROLL_PIN_SLACK_PX;
    };
    // Deliberately not called here: at attach the node has existed for zero
    // frames with scrollTop 0, which carries no information about intent.
    scroller.addEventListener('scroll', track, { passive: true });
    return () => scroller.removeEventListener('scroll', track);
  }, [isOpen]);

  useEffect(() => {
    if (!transcriptRef.current || !isOpen) {
      return;
    }
    if (pinnedRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [isOpen, sendStatus, visibleMessageEntries]);

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
          const nextTasks = payload.tasks || [];
          if (sameTaskLists(current.tasks || [], nextTasks)) {
            return current;
          }
          return { ...current, tasks: nextTasks };
        });
        setToolResults((current) => syncToolResultsWithTasks(current, payload.tasks || []));
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
    setPendingMessages([]);
    setSendStatus(null);
    setActiveDrawer(null);
    setShowPromptSuggestions(false);
    setHistoryPinnedSession(false);
    writeStoredActiveSessionId(null);
  }, [activeSession, defaultRuntimeModel, historyPinnedSession, isOpen]);

  const ensureSession = async (options: { preserveTransientState?: boolean } = {}) => {
    const { preserveTransientState = false } = options;
    const existing = session;
    if (existing) {
      return existing;
    }
    const agentName = currentAgent?.name;
    if (!agentName || !chatAvailable) {
      setError(runtimeSetupMessage);
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
      if (!preserveTransientState) {
        setPendingMessages([]);
        setSendStatus(null);
      }
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

  const reconcileTimedOutSend = useCallback(
    async (sessionId: string, baselineVisibleCount: number) => {
      const deadline = Date.now() + SEND_RECONCILE_WINDOW_MS;
      let latestPayload: HostedAgentSession | null = null;
      while (Date.now() < deadline) {
        try {
          const payload = await fetchSessionPayload(sessionId);
          latestPayload = payload;
          const nextVisibleMessages = payload.messages.filter(
            (message) => message.role !== 'system' && message.role !== 'tool'
          );
          const newVisibleMessages = nextVisibleMessages.slice(baselineVisibleCount);
          setSession(payload);
          writeStoredActiveSessionId(payload.sessionId);
          setPendingMessages([]);
          if (newVisibleMessages.some((message) => message.role === 'assistant')) {
            setSendStatus(null);
            return true;
          }
        } catch {
          // Best effort reconciliation only.
        }
        await delay(SEND_RECONCILE_POLL_MS);
      }
      if (latestPayload) {
        setSession(latestPayload);
        writeStoredActiveSessionId(latestPayload.sessionId);
      }
      setPendingMessages([]);
      return false;
    },
    [fetchSessionPayload]
  );

  const handleSend = async (content: string) => {
    const trimmedContent = content.trim();
    // Sending is intent: never leave the user's own turn below the fold.
    pinnedRef.current = true;
    // Declared here, not inside the try: the catch needs them to decide whether
    // the message landed. null means "no baseline" — a 0 fallback would read as
    // growth and wrongly claim it landed.
    let baselineUserTurns: number | null = null;
    let sentToSessionId: string | null = null;
    const countUserTurns = (messages: HostedConversationMessage[] | undefined) =>
      (messages || []).filter(
        (message) => message.role === 'user' && !isInternalOnly(message)
      ).length;
    if (!currentAgent || !trimmedContent) {
      return;
    }
    if (!chatAvailable) {
      setError(runtimeSetupMessage);
      return;
    }
    const optimisticCreatedAt = new Date().toISOString();
    setSending(true);
    useTerminalStore.getState().setAgentActivity('streaming');
    setError(null);
    setDraft('');
    setPendingMessages([buildEphemeralMessage('user', trimmedContent, optimisticCreatedAt)]);
    setSendStatus({
      kind: 'working',
      content: 'Thinking…',
      createdAt: new Date(Date.now() + 1).toISOString(),
    });
    const baselineVisibleCount = visibleMessages.length;
    let toolPollTimer: number | null = null;
    let pollingSessionId: string | null = null;
    let baselineCallCount = 0;
    const startedAt = Date.now();
    const startToolPolling = (sessionId: string, baseline: number) => {
      pollingSessionId = sessionId;
      baselineCallCount = baseline;
      const tick = async () => {
        if (pollingSessionId !== sessionId) {
          return;
        }
        let detail: (HostedAgentSession & {
          capabilityCalls?: Array<{ capabilityName: string; calledAt: string; inputs?: Record<string, unknown> }>;
        }) | null = null;
        try {
          detail = await fetchRuntimeJson<HostedAgentSession & {
            capabilityCalls?: Array<{ capabilityName: string; calledAt: string; inputs?: Record<string, unknown> }>;
          }>(
            `/agent/api/runtime/sessions/${encodeURIComponent(sessionId)}`,
            {},
            'Polling assistant progress'
          );
        } catch {
          return;
        }
        if (pollingSessionId !== sessionId) {
          return;
        }
        const calls = detail?.capabilityCalls || [];
        const newCalls = calls.slice(baselineCallCount);
        const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
        let content: string;
        if (newCalls.length === 0) {
          content = `Thinking… (${elapsed}s)`;
        } else {
          const latest = newCalls[newCalls.length - 1];
          const focus = latest.inputs && (latest.inputs.ticker || latest.inputs.name);
          const label = focus ? `${latest.capabilityName} · ${focus}` : latest.capabilityName;
          const suffix = newCalls.length > 1 ? ` · ${newCalls.length} tools` : '';
          content = `Running ${label}…${suffix} (${elapsed}s)`;
        }
        setSendStatus({
          kind: 'working',
          content,
          createdAt: new Date().toISOString(),
        });
      };
      void tick();
      toolPollTimer = window.setInterval(() => {
        void tick();
      }, SEND_TOOL_POLL_INTERVAL_MS);
    };
    const stopToolPolling = () => {
      pollingSessionId = null;
      if (toolPollTimer !== null) {
        window.clearInterval(toolPollTimer);
        toolPollTimer = null;
      }
    };
    try {
      const session = activeSession ?? (await ensureSession({ preserveTransientState: true }));
      if (!session) {
        // Nothing was sent — ensureSession swallows its error and returns null.
        // setDraft('') already ran, so give the text back rather than eat it.
        setPendingMessages([]);
        setSendStatus(null);
        setDraft((current) => (current.trim() ? current : trimmedContent));
        return;
      }
      let baseline = 0;
      sentToSessionId = session.sessionId;
      try {
        const initial = await fetchRuntimeJson<HostedAgentSession & {
          capabilityCalls?: unknown[];
        }>(
          `/agent/api/runtime/sessions/${encodeURIComponent(session.sessionId)}`,
          {},
          'Reading session baseline'
        );
        baseline = (initial.capabilityCalls || []).length;
        baselineUserTurns = countUserTurns(initial.messages);
      } catch {
        baseline = 0;
      }
      startToolPolling(session.sessionId, baseline);
      const run = (await fetchRuntimeJson<HostedRunResponse>(
        `/agent/api/runtime/sessions/${encodeURIComponent(session.sessionId)}/messages`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Include the browser's live viewContextId so the server can refresh
          // the session's link and `current_view_context` reads the user's
          // actual current view (not the snapshot at session-creation time).
          body: JSON.stringify({ content: trimmedContent, viewContextId: getAgentViewContextId() }),
        },
        'Running assistant request',
        SEND_REQUEST_TIMEOUT_MS
      )) as HostedRunResponse;
      stopToolPolling();
      const nextSession = mergeSessionFromRun(session, run);
      const previousMessageCount = session.messages.length;
      const nextVisibleMessages = nextSession.messages
        .slice(previousMessageCount)
        .filter((message) => message.role !== 'system' && message.role !== 'tool');
      setSession(nextSession);
      writeStoredActiveSessionId(nextSession.sessionId);
      setToolResults(run.toolResults || []);
      setPendingMessages([]);
      setSendStatus(null);
      setShowPromptSuggestions(false);
      if (
        !run.finalMessage &&
        (run.toolResults || []).length === 0 &&
        !nextVisibleMessages.some((message) => message.role === 'assistant')
      ) {
        setError(`${AGENT_UI_NAME} did not return a visible reply. Please try again.`);
      }
    } catch (payload) {
      const parsedMessage = parseRuntimeError(payload, 'Failed to run the hosted TerraFin agent.');
      const timedOut = /timed out/i.test(parsedMessage);
      if (timedOut) {
        const sessionId = activeSession?.sessionId || readStoredActiveSessionId();
        if (sessionId) {
          setSendStatus({
            kind: 'working',
            content: 'Still waiting for the assistant…',
            createdAt: new Date(Date.now() + 2).toISOString(),
          });
          const reconciled = await reconcileTimedOutSend(sessionId, baselineVisibleCount);
          if (reconciled) {
            return;
          }
        } else {
          setPendingMessages([]);
        }
      }
      const displayMessage = timedOut
        ? 'The assistant is taking longer than expected. Check this chat again in a moment.'
        : parsedMessage;
      if (displayMessage === LOCAL_SETUP_MESSAGE || displayMessage === runtimeSetupMessage) {
        setPendingMessages([]);
        setSendStatus(null);
        setError(displayMessage);
        // The runtime never accepted the message, so the text is gone unless it
        // goes back. Guarded on the session it was typed in, since the awaits
        // above can outlast a switch.
        if (activeSessionRef.current?.sessionId === sentToSessionId) {
          setDraft((current) => (current.trim() ? current : trimmedContent));
        }
      } else {
        // Ask the transcript, not the status code. Inferring "did it land" from a
        // status triple was wrong in both directions: a bare KeyError/LookupError
        // maps to 404 *after* loop.py:274 persists the message, and a pre-persist
        // RuntimeError from _ensure_message_budget (loop.py:268) surfaces as 502.
        // The server is the only thing that knows.
        const sessionId = activeSession?.sessionId || readStoredActiveSessionId();
        // Refused before the message could be appended, whatever the turn count
        // says — a concurrent sender's message inside the baseline-to-POST
        // window would otherwise read as growth. Keyed on the server's code, not
        // on the 409: `_raise_http_error` mints that status for a session
        // conflict and for an approval requirement too, and this branch skips
        // the transcript probe and writes a permanent 'nothing' notice, so
        // reading it off the wrong 409 tells the user a landed message was never
        // sent and hands their text back to duplicate.
        const rejectedOutright =
          (payload as { error?: { code?: string } } | undefined)?.error?.code ===
          TURN_IN_FLIGHT_ERROR_CODE;
        let landed = false;
        if (!rejectedOutright && sessionId && baselineUserTurns !== null) {
          try {
            const latest = await fetchSessionPayload(sessionId);
            landed = countUserTurns(latest.messages) > baselineUserTurns;
          } catch {
            landed = false; // could not confirm: assume it never left the browser
          }
        }
        setPendingMessages([]);
        // The awaits above can outlast a session switch. sendStatus renders as the
        // last bubble inside the transcript list, so neither the draft nor the
        // error may be applied to a session that is no longer on screen.
        if (activeSessionRef.current?.sessionId === sentToSessionId) {
          if (!landed) {
            setDraft((current) => (current.trim() ? current : trimmedContent));
          }
          setSendStatus({
            kind: 'error',
            content: rejectedOutright ? SEND_REFUSED_MESSAGE : displayMessage,
            createdAt: new Date(Date.now() + 2).toISOString(),
            // `landed` alone. A 409 is the one case where we *know* the message
            // never reached the transcript, so it is the strongest 'nothing'
            // there is — filing it as turn-scoped let the other writer's turn
            // retire it: exit 2 cleared the notice and appended that writer's
            // answer in its place, leaving the user a foreign reply, their text
            // in the composer, and no record that their own send had failed.
            retiredBy: landed ? 'turn-end' : 'nothing',
          });
        }
      }
    } finally {
      stopToolPolling();
      setSending(false);
      useTerminalStore.getState().setAgentActivity('idle');
    }
  };

  const handleComposerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
        return;
      }
      if (!chatAvailable || sending || creatingSession || loadingCatalog || !draft.trim()) {
        return;
      }
      event.preventDefault();
      void handleSend(draft);
    },
    [chatAvailable, creatingSession, draft, loadingCatalog, sending]
  );

  const handleClear = () => {
    setDraft('');
    setError(null);
    setSession(null);
    setHistoryPinnedSession(false);
    setToolResults([]);
    setPendingMessages([]);
    setSendStatus(null);
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
          setPendingMessages([]);
          setSendStatus(null);
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
      : isRuntimeConfigured
        ? 'Ready'
        : 'Local setup required'
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
          AGENT
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
          <div className="tf-agent-widget__title-group">
            <div className="tf-agent-widget__title">{AGENT_UI_NAME}</div>
            <span className={`tf-agent-widget__runtime-chip tf-agent-widget__runtime-chip--${runtimeState.toLowerCase().replace(/\s+/g, '-')}`}>
              {runtimeState}
            </span>
          </div>
          <div className="tf-agent-widget__header-actions">
            <button
              type="button"
              className={`tf-agent-widget__header-button ${
                isSessionsDrawerOpen ? 'tf-agent-widget__header-button--active' : ''
              }`}
              onClick={() => toggleDrawer('sessions')}
              disabled={loadingHistory || !chatAvailable}
            >
              Sessions
            </button>
            <button
              type="button"
              className="tf-agent-widget__header-button"
              onClick={handleClear}
              disabled={sending || creatingSession || !chatAvailable}
            >
              New
            </button>
            <button
              type="button"
              className="tf-agent-widget__header-button tf-agent-widget__close"
              onClick={() => setIsOpen(false)}
              aria-label={`Close ${AGENT_UI_NAME}`}
            >
              Close
            </button>
          </div>
        </div>

        {primaryRuntimeModelLabel || showSessionLabel || newChatRuntimeModelLabel || hasActivity ? (
          <div className="tf-agent-widget__header-sub">
            {primaryRuntimeModelLabel ? (
              <span className="tf-agent-widget__meta-pill tf-agent-widget__meta-pill--inline">
                {primaryRuntimeModelLabel}
              </span>
            ) : null}
            {hasActivity ? (
              <button
                type="button"
                className={`tf-agent-widget__meta-pill tf-agent-widget__meta-pill--button ${
                  isActivityDrawerOpen ? 'tf-agent-widget__meta-pill--active' : ''
                } ${pendingApprovals.length > 0 ? 'tf-agent-widget__meta-pill--attention' : ''}`}
                onClick={() => toggleDrawer('activity')}
              >
                Activity{activityCount > 0 ? ` ${activityCount}` : ''}
              </button>
            ) : null}
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
                visibleMessageEntries.length > 0 || sendStatus
                  ? 'tf-agent-transcript--live'
                  : 'tf-agent-transcript--idle'
              }`}
            >
              {visibleMessageEntries.map(({ key, message }) => (
                <AgentMessageItem key={key} message={message} messageKey={key} />
              ))}
              {sendStatus ? (
                <div
                  className={`tf-agent-message tf-agent-message--assistant tf-agent-message--status tf-agent-message--status-${sendStatus.kind}`}
                >
                  <div className="tf-agent-message__status">
                    {sendStatus.kind === 'working' ? (
                      <span className="tf-agent-message__status-spinner" aria-hidden="true" />
                    ) : null}
                    <span className="tf-agent-message__status-copy">{sendStatus.content}</span>
                  </div>
                </div>
              ) : null}
              {visibleMessageEntries.length === 0 && !sendStatus && loadingCatalog ? (
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
              {visibleMessageEntries.length === 0 && !sendStatus && creatingSession ? (
                <div className="tf-agent-widget__placeholder">
                  <div className="tf-agent-widget__placeholder-spinner" aria-hidden="true" />
                  <div className="tf-agent-widget__placeholder-title">Starting a conversation</div>
                  <div className="tf-agent-widget__placeholder-copy">
                    Creating a fresh session for the assistant.
                  </div>
                </div>
              ) : null}
              {visibleMessageEntries.length === 0 && !sendStatus && !loadingCatalog && !creatingSession && !sending ? (
                <div className="tf-agent-widget__placeholder">
                  <div className="tf-agent-widget__placeholder-title">
                    {chatAvailable
                      ? 'Start with a question'
                      : needsLocalSetup
                        ? `Set up ${AGENT_UI_NAME} locally`
                        : `${AGENT_UI_NAME} not ready`}
                  </div>
                  <div className="tf-agent-widget__placeholder-copy">
                    {chatAvailable
                      ? 'Ask directly below, or open the ? button if you want a few examples.'
                      : error ||
                        'The hosted agent runtime is not responding on this deployment yet.'}
                  </div>
                  {!chatAvailable ? (
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
                onKeyDown={handleComposerKeyDown}
                placeholder={
                  chatAvailable
                    ? 'Ask about a stock, portfolio, DCF, chart, or macro setup.'
                    : `${AGENT_UI_NAME} requires a local hosted model setup on this deployment.`
                }
                rows={3}
                disabled={!chatAvailable || sending || creatingSession || loadingCatalog}
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
                              disabled={!chatAvailable || sending || creatingSession || loadingCatalog}
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
                        disabled={!chatAvailable || sending || creatingSession || loadingCatalog}
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
                    disabled={!chatAvailable || !draft.trim() || sending || creatingSession || loadingCatalog}
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
