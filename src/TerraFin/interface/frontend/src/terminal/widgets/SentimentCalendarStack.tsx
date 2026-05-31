import React from 'react';
import FearGreedGauge from './FearGreedGauge';
import UpcomingCatalysts from './UpcomingCatalysts';
import { EYEBROW_STYLE as eyebrowStyle } from './stackStyles';

// Right-rail composite: Fear & Greed gauge on top, upcoming catalysts list
// below, split by an in-pane divider so the rail fills top-to-bottom. Each
// section carries its own eyebrow so the single "Sentiment" tab still reads as
// two labelled blocks.
const SentimentCalendarStack: React.FC = () => {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
      }}
    >
      <div style={{ flex: '0 0 auto' }}>
        <div style={eyebrowStyle}>Fear &amp; Greed</div>
        <div style={{ padding: '0 12px 12px' }}>
          <FearGreedGauge />
        </div>
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
        <div style={eyebrowStyle}>Upcoming Catalysts</div>
        <UpcomingCatalysts />
      </div>
    </div>
  );
};

export default SentimentCalendarStack;
