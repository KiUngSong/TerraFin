import React from 'react';
import { ResearchReport } from './researchReport';

const STATUS_TONE: Record<string, string> = { partial: 'running', failed: 'failed' };

type ResearchReportCardProps = {
  report: ResearchReport;
  // The report body, rendered by the widget's markdown renderer.
  children: React.ReactNode;
};

export const ResearchReportCard: React.FC<ResearchReportCardProps> = ({ report, children }) => (
  <div className="tf-agent-report">
    {report.status !== 'ok' ? (
      <div className="tf-agent-task-card__meta">
        <span className={`tf-agent-task-badge tf-agent-task-badge--${STATUS_TONE[report.status] || 'failed'}`}>
          {report.status.toUpperCase()}
        </span>
        <div className="tf-agent-turn__detail">
          {report.statusHint}
          {report.stopReason ? ` Stop reason: ${report.stopReason}` : ''}
        </div>
      </div>
    ) : null}
    {report.report.trim() ? children : <div className="tf-agent-turn__detail">The run returned no report text.</div>}
  </div>
);
