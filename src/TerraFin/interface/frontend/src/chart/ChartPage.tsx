import React, { useRef } from 'react';
import { getChartSessionId } from './api';
import ChartComponent from './ChartComponent';

function getInitialSessionId(): string {
  try {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get('sessionId');
    if (requested) {
      return requested;
    }
  } catch {
    // fall back to a page-scoped session id below
  }
  return getChartSessionId('chart-page');
}

const ChartPage: React.FC = () => {
  const sessionIdRef = useRef(getInitialSessionId());
  return <ChartComponent sessionId={sessionIdRef.current} />;
};

export default ChartPage;
