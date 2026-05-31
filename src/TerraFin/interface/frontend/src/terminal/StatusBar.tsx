import React from 'react';
import { useTerminalStore } from './store';

/**
 * Ultra-thin status bar. Renders ONLY while the agent is active (streaming /
 * thinking). The old freshness dot showed a lone unlabeled circle when data
 * was stale — useless on every viewport — so it's gone; idle renders nothing.
 */

const StatusBar: React.FC = () => {
  const activity = useTerminalStore((s) => s.agentActivity);
  if (activity === 'idle') return null;

  return (
    <div className="tf-statusbar" role="status" aria-live="off">
      <span className={`tf-statusbar__led tf-statusbar__led--${activity}`} title={`agent: ${activity}`}>
        agent {activity}
      </span>
      <span className="tf-statusbar__spacer" />
    </div>
  );
};

export default StatusBar;
