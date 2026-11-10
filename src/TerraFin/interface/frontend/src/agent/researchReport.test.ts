import { describe, expect, it } from '@jest/globals';
import { readResearchReport } from './researchReport';

// The shape run_deep_research returns: ResearchResult.to_payload plus question, title, status, documents, usage.
const payload = {
  report: '# AAPL revenue growth\n\nRevenue grew **2.02%** in FY2024.',
  status: 'ok',
  stopReason: 'model finished',
  turns: 4,
  toolCalls: 9,
  tokens: 12000,
  seconds: 41.2,
  reviews: [],
  question: 'How fast did AAPL revenue grow?',
  title: 'AAPL revenue growth',
  documents: [],
  usage: { input: 10000, output: 2000 },
};

describe('readResearchReport', () => {
  it('reads the title and the markdown report', () => {
    expect(readResearchReport(payload)).toEqual({
      title: 'AAPL revenue growth',
      status: 'ok',
      statusHint: '',
      stopReason: 'model finished',
      report: payload.report,
    });
  });

  it('falls back to the question when the title is empty', () => {
    expect(readResearchReport({ ...payload, title: '' })?.title).toBe('How fast did AAPL revenue grow?');
  });

  it('explains a partial or failed run', () => {
    const partial = readResearchReport({ ...payload, status: 'partial', stopReason: 'budget: tokens' });
    expect(partial?.statusHint).toMatch(/budget cap/);
    expect(partial?.stopReason).toBe('budget: tokens');
    const failed = readResearchReport({ ...payload, status: 'failed', report: '' });
    expect(failed?.statusHint).toMatch(/failed/);
    expect(failed?.report).toBe('');
  });

  it('returns null for a result that is not a report', () => {
    expect(readResearchReport({ ticker: 'AAPL' })).toBeNull();
    expect(readResearchReport({ status: 'ok', claims: [] })).toBeNull();
    expect(readResearchReport(null)).toBeNull();
  });
});
