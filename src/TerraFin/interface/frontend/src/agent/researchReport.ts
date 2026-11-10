// Reads a deep_research task.result into what the report card shows. Pure: no
// React, no fetch.

export interface ResearchReport {
  title: string;
  // The run's own status: ok, partial or failed.
  status: string;
  statusHint: string;
  stopReason: string;
  // Markdown written from web pages, so it renders only through the widget's guarded renderer.
  report: string;
}

const STATUS_HINT: Record<string, string> = {
  partial: 'The run stopped at a budget cap, so the report may be incomplete.',
  failed: 'The run failed before it finished the report.',
};

const asText = (value: unknown) => (typeof value === 'string' ? value : '');

// Null when the result is not a research report.
export const readResearchReport = (result: unknown): ResearchReport | null => {
  const raw = result && typeof result === 'object' && !Array.isArray(result) ? (result as Record<string, unknown>) : null;
  if (!raw || typeof raw.report !== 'string' || typeof raw.status !== 'string') {
    return null;
  }
  return {
    title: asText(raw.title) || asText(raw.question) || 'Research report',
    status: raw.status,
    statusHint: STATUS_HINT[raw.status] || '',
    stopReason: asText(raw.stopReason),
    report: raw.report,
  };
};
