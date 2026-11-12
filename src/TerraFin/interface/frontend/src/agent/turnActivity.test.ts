import { describe, expect, it } from '@jest/globals';
import {
  ActivityMessage,
  buildTurnActivities,
  formatTurnFooter,
  sessionTokens,
  summarizeTurn,
  turnEndingRow,
  unlandedPending,
} from './turnActivity';

const at = (second: number) => `2026-11-01T10:00:${String(second).padStart(2, '0')}.000000+00:00`;

const user = (second: number): ActivityMessage => ({
  role: 'user',
  content: 'question',
  createdAt: at(second),
});

const assistant = (second: number): ActivityMessage => ({
  role: 'assistant',
  content: 'answer',
  createdAt: at(second),
});

const tool = (
  second: number,
  capabilityName: string,
  extra: { isError?: boolean; errorMessage?: string; executionMode?: string } = {}
): ActivityMessage => ({
  role: 'tool',
  name: capabilityName,
  createdAt: at(second),
  content: JSON.stringify({ capabilityName, errorMessage: extra.errorMessage }),
  metadata: {
    capabilityName,
    isError: extra.isError === true,
    executionMode: extra.executionMode || 'invoke',
  },
});

const call = (second: number, capabilityName: string, ticker: string) => ({
  capabilityName,
  calledAt: at(second),
  inputs: { ticker },
  outputKeys: ['price'],
  artifactIds: [],
});

describe('buildTurnActivities', () => {
  it('groups tool messages under the turn that made them', () => {
    const turns = buildTurnActivities(
      [
        user(0),
        tool(2, 'market_snapshot'),
        assistant(3),
        user(10),
        tool(12, 'valuation'),
        tool(13, 'market_snapshot'),
        assistant(15),
      ],
      [call(1, 'market_snapshot', 'AAPL'), call(11, 'valuation', 'MSFT'), call(12, 'market_snapshot', 'MSFT')]
    );
    expect(turns.map((turn) => turn.calls.map((item) => item.label))).toEqual([
      ['market_snapshot · AAPL'],
      ['valuation · MSFT', 'market_snapshot · MSFT'],
    ]);
    expect(summarizeTurn(turns[1])).toBe('Used 2 tools: valuation · MSFT, market_snapshot · MSFT');
    expect(formatTurnFooter(turns[1], 'OpenAI / gpt-6-luna')).toBe('Completed in 5s · 2 tools · OpenAI / gpt-6-luna');
  });

  it('shows a failed call by name and error, without claiming a capabilityCall', () => {
    const [turn] = buildTurnActivities(
      [
        user(0),
        tool(2, 'valuation', { isError: true, errorMessage: 'Ticker not found.\nTrace' }),
        tool(4, 'market_snapshot'),
        assistant(5),
      ],
      // A same-name call before the failure, which only the error guard keeps unclaimed.
      [call(1, 'valuation', 'AAPL'), call(3, 'market_snapshot', 'AAPL')]
    );
    expect(turn.calls[0]).toMatchObject({
      label: 'valuation',
      isError: true,
      errorLine: 'Ticker not found.',
      inputs: null,
    });
    expect(turn.calls[1].label).toBe('market_snapshot · AAPL');
    expect(summarizeTurn(turn)).toBe('Used 2 tools: valuation, market_snapshot · AAPL');
  });

  it('matches repeated calls of one capability in order', () => {
    const [turn] = buildTurnActivities(
      [user(0), tool(2, 'valuation'), tool(4, 'valuation'), assistant(5)],
      [call(1, 'valuation', 'AAPL'), call(3, 'valuation', 'NVDA')]
    );
    expect(turn.calls.map((item) => item.label)).toEqual(['valuation · AAPL', 'valuation · NVDA']);
  });

  it('leaves a background task call that lands mid-turn to no inline call', () => {
    const turns = buildTurnActivities(
      [
        user(0),
        tool(2, 'valuation', { executionMode: 'task' }),
        assistant(3),
        user(10),
        tool(13, 'valuation'),
        assistant(15),
      ],
      // call(1) sits in turn 1, where only the task-mode guard keeps it unclaimed.
      [call(1, 'valuation', 'NVDA'), call(11, 'valuation', 'AAPL'), call(12, 'valuation', 'MSFT')]
    );
    expect(turns.map((turn) => turn.calls.map((item) => item.label))).toEqual([['valuation'], ['valuation · MSFT']]);
  });

  it('shows one user turn when a pending message and its server copy coexist', () => {
    const server = [user(0), assistant(3), user(10), tool(12, 'valuation')];
    // The client clock runs behind the server's, so the two stamps differ.
    const pending = [{ ...user(9), userTurnsBefore: 1 }];
    const shown = [...server, ...unlandedPending(server, pending)];
    const turns = buildTurnActivities(shown, [call(11, 'valuation', 'MSFT')]);
    expect(turns.map((turn) => turn.key)).toEqual([at(0), at(10)]);
    expect(turns[1].calls.map((item) => item.label)).toEqual(['valuation · MSFT']);
    // Before it lands, the same text in an earlier turn does not hide it.
    expect(unlandedPending(server.slice(0, 2), pending)).toEqual(pending);
  });
});

const reply = (second: number, metadata: Record<string, unknown>): ActivityMessage => ({
  ...assistant(second),
  metadata,
});

describe('turn endings and tokens', () => {
  it('maps each turnEnding to its row, and a reply that ended on its own to none', () => {
    expect(turnEndingRow(reply(1, { turnEnding: 'step_limit' }))).toBe(
      'Stopped at the step limit. What is established and what is missing is above.'
    );
    expect(turnEndingRow(reply(1, { turnEnding: 'length' }))).toBe('Reply cut at the length limit. Send "continue".');
    expect(turnEndingRow(reply(1, { turnEnding: 'interrupted' }))).toBe('Stopped by you.');
    const stoppedReply = { ...reply(1, { turnEnding: 'interrupted' }), content: 'Stopped at your request before an answer was written.' };
    expect(turnEndingRow(stoppedReply)).toBe('');
    expect(turnEndingRow(reply(1, { turnEnding: 'unknown_kind' }))).toBe('');
    expect(turnEndingRow(assistant(1))).toBe('');
  });

  it('puts the turn total in the footer and sums the session from replies', () => {
    const messages = [
      user(0),
      tool(2, 'market_snapshot'),
      reply(3, { turnTokenUsage: { input: 12400, output: 380, cacheRead: 0, cacheWrite: 0 } }),
      user(10),
      reply(12, { turnTokenUsage: { input: 900, output: 40, cacheRead: 0, cacheWrite: 0 } }),
    ];
    const turns = buildTurnActivities(messages, [call(1, 'market_snapshot', 'AAPL')]);
    expect(turns[0].tokens).toEqual({ input: 12400, output: 380 });
    expect(formatTurnFooter(turns[0], 'OpenAI / gpt-6-luna')).toBe(
      'Completed in 3s · 1 tool · ↑12.4K ↓380 tokens · OpenAI / gpt-6-luna'
    );
    expect(formatTurnFooter(turns[1], '', sessionTokens(messages))).toBe(
      'Completed in 2s · ↑900 ↓40 tokens · session ↑13.3K ↓420'
    );
    // One counted turn has no session total beyond its own footer.
    expect(sessionTokens(messages.slice(0, 3))).toBeNull();
  });
});
