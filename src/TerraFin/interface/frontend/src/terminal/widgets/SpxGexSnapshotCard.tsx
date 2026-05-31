import React from 'react';
import TerminalPane from '../components/TerminalPane';
import SourceTag from '../../shared/SourceTag';
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
    <TerminalPane
      title="SPX Gamma Exposure"
      subtitle="CBOE delayed options · 15–20 min"
      meta={<SourceTag source="cboe" />}
      paneId="pane-spx-gex-snapshot"
    >
      <GexPanel payload={data} loading={false} error={error} />
    </TerminalPane>
  );
};

export default SpxGexSnapshotCard;
