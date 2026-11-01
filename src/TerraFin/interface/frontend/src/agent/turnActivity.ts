// Groups a transcript's tool messages by turn so the panel can show what each
// answer rests on. Pure: no React, no fetch.

export interface ActivityMessage {
  role: string;
  content: string;
  createdAt: string;
  name?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ActivityCapabilityCall {
  capabilityName: string;
  calledAt: string;
  inputs?: Record<string, unknown>;
  outputKeys?: string[];
  artifactIds?: string[];
}

export interface ToolCallActivity {
  callId: string;
  label: string;
  isError: boolean;
  errorLine: string;
  inputs: Record<string, unknown> | null;
  outputKeys: string[];
  artifactIds: string[];
  raw: string;
}

export interface TokenCount {
  input: number;
  output: number;
}

export interface TurnActivity {
  // The user message's server createdAt, which names the turn.
  key: string;
  answeredAt: string | null;
  // Every model call of the turn, tool-only steps included, from the server's turnTokenUsage.
  tokens: TokenCount | null;
  calls: ToolCallActivity[];
}

// The client's copy of a sent user message, with the count of user messages the
// transcript held when it was sent.
export interface PendingUserMessage extends ActivityMessage {
  userTurnsBefore: number;
}

const time = (value: string) => new Date(value).getTime();

// A pending message gives way once its server copy lands: a user message with
// the same text past the count it was sent after. The client and server stamps
// differ, so the stamp cannot pair them.
export const unlandedPending = <T extends PendingUserMessage>(messages: ActivityMessage[], pending: T[]): T[] => {
  const userMessages = messages.filter((message) => message.role === 'user');
  return pending.filter(
    (item) => !userMessages.slice(item.userTurnsBefore).some((message) => message.content === item.content)
  );
};

const turnTokens = (message: ActivityMessage | null): TokenCount | null => {
  const usage = message?.metadata?.turnTokenUsage as Record<string, unknown> | undefined;
  return typeof usage?.input === 'number' && typeof usage?.output === 'number'
    ? { input: usage.input, output: usage.output }
    : null;
};

const TURN_ENDING_ROW: Record<string, string> = {
  step_limit: 'Stopped at the step limit. What is established and what is missing is above.',
  length: 'Reply cut at the length limit. Send "continue".',
  interrupted: 'Stopped by you.',
};

// Must match _STOPPED_TEXT in agent/runtime/loop.py. That reply already says it was stopped.
const STOPPED_REPLY_TEXT = 'Stopped at your request before an answer was written.';

// The row under a reply whose turn did not end on its own, or '' for one that did.
export const turnEndingRow = (message: ActivityMessage) => {
  const ending = message.role === 'assistant' ? message.metadata?.turnEnding : undefined;
  if (ending === 'interrupted' && message.content === STOPPED_REPLY_TEXT) {
    return '';
  }
  return typeof ending === 'string' ? TURN_ENDING_ROW[ending] ?? '' : '';
};

// The session's tokens, summed over replies that carry a turn total. Null until
// two turns do, since one turn's total is already in its own footer.
export const sessionTokens = (messages: ActivityMessage[]): TokenCount | null => {
  const counted = messages.map((message) => (message.role === 'assistant' ? turnTokens(message) : null));
  const turns = counted.filter((count): count is TokenCount => count !== null);
  return turns.length < 2
    ? null
    : turns.reduce((sum, count) => ({ input: sum.input + count.input, output: sum.output + count.output }));
};

const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });

const formatTokens = ({ input, output }: TokenCount) => `↑${compact.format(input)} ↓${compact.format(output)}`;

const firstErrorLine = (content: string) => {
  try {
    const message = JSON.parse(content)?.errorMessage;
    return typeof message === 'string' ? message.split('\n')[0].trim() : '';
  } catch {
    return '';
  }
};

export const callLabel = (capabilityName: string, inputs: Record<string, unknown> | null) => {
  const focus = inputs?.ticker || inputs?.name;
  return typeof focus === 'string' && focus.trim() ? `${capabilityName} · ${focus}` : capabilityName;
};

export const formatInputs = (inputs: Record<string, unknown> | null) =>
  Object.entries(inputs || {}).map(
    ([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`
  );

// A capabilityCall carries no callId and is recorded only once its handler
// returns. Tools run one at a time and a tool message is stamped right after its
// call is recorded, so a tool message pairs with the unclaimed call of the same
// capability that lands latest at or before it, inside its own turn. A background
// task records its call whenever it finishes, inside whatever turn is open then,
// so taking the latest call rather than the first keeps it from being claimed.
// Failed and task-mode calls claim nothing.
export const buildTurnActivities = (
  messages: ActivityMessage[],
  capabilityCalls: ActivityCapabilityCall[] = []
): TurnActivity[] => {
  const turns: Array<{
    key: string;
    answer: ActivityMessage | null;
    startedAt: number;
    toolMessages: ActivityMessage[];
  }> = [];
  messages.forEach((message) => {
    const current = turns[turns.length - 1];
    if (message.role === 'user') {
      turns.push({
        key: message.createdAt,
        answer: null,
        startedAt: time(message.createdAt),
        toolMessages: [],
      });
    } else if (current && message.role === 'tool') {
      current.toolMessages.push(message);
      // Only an assistant message after the last tool message is the answer: one
      // before it was a preamble. A turn that died between its preamble and the
      // tool-use message still reads as answered, since that message is
      // internalOnly and never reaches this transcript.
      current.answer = null;
    } else if (current && message.role === 'assistant') {
      current.answer = message;
    }
  });
  return turns.map((turn, index) => {
    const endsAt = index + 1 < turns.length ? turns[index + 1].startedAt : Infinity;
    const unclaimed = capabilityCalls.filter((call) => {
      const calledAt = time(call.calledAt);
      return calledAt >= turn.startedAt && calledAt < endsAt;
    });
    const calls = turn.toolMessages.map((message, position): ToolCallActivity => {
      const metadata = message.metadata || {};
      const capabilityName =
        typeof metadata.capabilityName === 'string' ? metadata.capabilityName : message.name || 'tool';
      const isError = metadata.isError === true;
      let call: ActivityCapabilityCall | undefined;
      if (!isError && metadata.executionMode !== 'task') {
        const stampedAt = time(message.createdAt);
        let found = -1;
        unclaimed.forEach((candidate, candidateIndex) => {
          const calledAt = time(candidate.calledAt);
          if (
            candidate.capabilityName === capabilityName &&
            calledAt <= stampedAt &&
            (found < 0 || calledAt >= time(unclaimed[found].calledAt))
          ) {
            found = candidateIndex;
          }
        });
        if (found >= 0) {
          call = unclaimed.splice(found, 1)[0];
        }
      }
      const inputs = call?.inputs || null;
      return {
        // The provider's call id is not promised unique across turns.
        callId: `${turn.key}#${position}`,
        label: callLabel(capabilityName, inputs),
        isError,
        errorLine: isError ? firstErrorLine(message.content) : '',
        inputs,
        outputKeys: call?.outputKeys || [],
        artifactIds: call?.artifactIds || [],
        raw: message.content,
      };
    });
    return { key: turn.key, answeredAt: turn.answer?.createdAt ?? null, tokens: turnTokens(turn.answer), calls };
  });
};

export const summarizeTurn = (turn: TurnActivity) =>
  `Used ${turn.calls.length} tool${turn.calls.length === 1 ? '' : 's'}: ${turn.calls
    .map((call) => call.label)
    .join(', ')}`;

export const formatTurnFooter = (turn: TurnActivity, modelLabel: string, session: TokenCount | null = null) => {
  if (!turn.answeredAt) {
    return '';
  }
  const seconds = Math.max(0, Math.round((time(turn.answeredAt) - time(turn.key)) / 1000));
  return [
    `Completed in ${seconds}s`,
    turn.calls.length > 0 ? `${turn.calls.length} tool${turn.calls.length === 1 ? '' : 's'}` : '',
    turn.tokens ? `${formatTokens(turn.tokens)} tokens` : '',
    session ? `session ${formatTokens(session)}` : '',
    modelLabel,
  ]
    .filter(Boolean)
    .join(' · ');
};
