import React from 'react';
import InsightCard from '../components/InsightCard';
import GexPanel from '../../stock/components/GexPanel';
import { GexPayload } from '../../stock/useStockData';

interface Props {
  data: GexPayload | null;
  loading: boolean;
  error: string | null;
}

const SpxGexSnapshotCard: React.FC<Props> = ({ data, loading, error }) => {
  if (loading || (!data && !error) || (data != null && !data.available && !error)) return null;

  return (
    <InsightCard
      title="SPX Gamma Exposure"
      subtitle="CBOE delayed options (15–20 min). SqueezeMetrics estimates GEX from dark pool volume; CBOE calculates from open interest — expect divergence vs macro chart history."
    >
      <GexPanel payload={data} loading={false} error={error} />
    </InsightCard>
  );
};

export default SpxGexSnapshotCard;
