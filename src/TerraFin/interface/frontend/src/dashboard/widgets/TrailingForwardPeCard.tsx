import React, { useEffect, useState } from 'react';
import InsightCard from '../components/InsightCard';

interface TrailingForwardPeHistoryPoint {
  date: string;
  value: number;
}

interface TrailingForwardPeSpreadPayload {
  date: string;
  description: string;
  latestValue?: number | null;
  usableCount?: number | null;
  requestedCount?: number | null;
  history: TrailingForwardPeHistoryPoint[];
}

const Sparkline: React.FC<{ points: TrailingForwardPeHistoryPoint[] }> = ({ points }) => {
  if (points.length === 0) {
    return <div className="tf-dashboard-status">No spread history available yet.</div>;
  }

  const values = points.map((point) => point.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const width = 280;
  const height = 88;
  const span = maxValue - minValue || 1;
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((point.value - minValue) / span) * (height - 8) - 4;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label="Trailing-forward P/E spread history"
    >
      <path
        d={path}
        fill="none"
        stroke="#2563eb"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

const TrailingForwardPeCard: React.FC = () => {
  const [payload, setPayload] = useState<TrailingForwardPeSpreadPayload | null>(null);

  useEffect(() => {
    fetch('/dashboard/api/trailing-forward-pe-spread')
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`${response.status}`))))
      .then((nextPayload: TrailingForwardPeSpreadPayload) => {
        setPayload(nextPayload);
      })
      .catch(() => {
        setPayload(null);
      });
  }, []);

  return (
    <InsightCard
      title="Trailing-Forward P/E Spread"
      subtitle={
        payload?.description ||
        'Trailing P/E minus forward P/E, used as a rough proxy for how much future earnings expectations diverge from trailing earnings.'
      }
      href="/market-insights?ticker=Trailing-Forward%20P%2FE%20Spread"
    >
      <div className="tf-dashboard-pe">
        <div className="tf-dashboard-pe__summary">
          <div className="tf-dashboard-pe__stat">
            <div className="tf-dashboard-pe__label">Latest spread</div>
            <div className="tf-dashboard-pe__value">
              {typeof payload?.latestValue === 'number' ? payload.latestValue.toFixed(2) : '--'}
            </div>
          </div>
          <div className="tf-dashboard-pe__coverage">
            <div>{payload?.date || ''}</div>
            <div>
              Coverage {payload?.usableCount ?? '--'}/{payload?.requestedCount ?? '--'}
            </div>
          </div>
        </div>
        <div className="tf-dashboard-pe__sparkline">
          <Sparkline points={payload?.history || []} />
        </div>
      </div>
    </InsightCard>
  );
};

export default TrailingForwardPeCard;
