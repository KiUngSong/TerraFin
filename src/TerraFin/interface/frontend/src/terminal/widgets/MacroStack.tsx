import React from 'react';
import MarketBreadthCard from './MarketBreadthCard';
import TrailingForwardPeCard from './TrailingForwardPeCard';
import { EYEBROW_STYLE as eyebrowStyle } from './stackStyles';

// Composite macro rail: market breadth on top, trailing/forward P/E spread
// below, split by an in-pane divider. Each section carries its own eyebrow so
// the pane reads as two labelled blocks rather than one ambiguous card.
const MacroStack: React.FC = () => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ flex: '0 0 auto' }}>
        <div style={eyebrowStyle}>Market Breadth</div>
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
        <div style={eyebrowStyle}>Trailing / Forward P/E</div>
        <TrailingForwardPeCard />
      </div>
    </div>
  );
};

export default MacroStack;
