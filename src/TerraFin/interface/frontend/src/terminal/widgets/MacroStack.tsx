import React from 'react';
import MarketBreadthCard from './MarketBreadthCard';
import TrailingForwardPeCard from './TrailingForwardPeCard';

// Composite macro rail: market breadth on top, trailing/forward P/E spread
// below, split by an in-pane divider. Each card renders its own eyebrow, with
// the indicator's description behind an info hint.
const MacroStack: React.FC = () => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ flex: '0 0 auto' }}>
        <MarketBreadthCard />
      </div>
      <div
        style={{
          flex: '1 1 auto',
          minHeight: 0,
          borderTop: '1px solid var(--tf-border)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <TrailingForwardPeCard />
      </div>
    </div>
  );
};

export default MacroStack;
