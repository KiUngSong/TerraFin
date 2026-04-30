import React, { useEffect, useState } from 'react';
import InsightCard from '../components/InsightCard';

interface BreadthMetric {
  label: string;
  value: string;
  tone: string;
}

const MarketBreadthCard: React.FC = () => {
  const [metrics, setMetrics] = useState<BreadthMetric[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/dashboard/api/market-breadth')
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`${response.status}`))))
      .then((payload: { metrics?: BreadthMetric[] }) => {
        setMetrics(payload.metrics || []);
      })
      .catch(() => {
        setMetrics([]);
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  return (
    <InsightCard
      title="Market Breadth"
      subtitle="Daily S&P 500 breadth from advancers and decliners."
      href="/market-insights?ticker=Net%20Breadth"
      minHeight={0}
    >
      <div className="tf-dashboard-breadth-grid">
        {metrics.map((item) => (
          <div key={item.label} className="tf-dashboard-metric-card">
            <div className="tf-dashboard-metric-card__label">{item.label}</div>
            <div className="tf-dashboard-metric-card__value" style={{ color: item.tone }}>
              {item.value}
            </div>
          </div>
        ))}
        {!loading && metrics.length === 0 ? (
          <div className="tf-dashboard-status tf-dashboard-status--span">
            No market breadth data available right now.
          </div>
        ) : null}
      </div>
    </InsightCard>
  );
};

export default MarketBreadthCard;
