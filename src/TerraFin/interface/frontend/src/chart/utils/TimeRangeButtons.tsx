import React, { useState } from 'react';
import { FONT_FAMILY, RANGE_BUTTONS, type RangeAvailability } from '../constants';
import type { RangeId } from '../constants';

interface TimeRangeButtonsProps {
  selectedRange: RangeId | null;
  onRangeSelect: (rangeId: RangeId) => void;
  availability?: Partial<Record<RangeId, RangeAvailability>>;
}

const TimeRangeButtons: React.FC<TimeRangeButtonsProps> = ({ selectedRange, onRangeSelect, availability }) => {
  const [hoveredId, setHoveredId] = useState<RangeId | null>(null);
  const [tooltipTarget, setTooltipTarget] = useState<RangeId | null>(null);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, minWidth: 'max-content' }}>
      {RANGE_BUTTONS.map(({ id, label, tooltip }) => {
        const isSelected = selectedRange === id;
        const isHovered = hoveredId === id;
        const config = availability?.[id];
        const isDisabled = config?.disabled === true;
        const tooltipText = config?.tooltip ?? tooltip;
        return (
          <div key={id} style={{ position: 'relative' }}>
            <button
              type="button"
              onClick={() => {
                if (isDisabled) return;
                onRangeSelect(id);
              }}
              onMouseEnter={() => {
                setHoveredId(id);
                setTooltipTarget(id);
              }}
              onMouseLeave={() => {
                setHoveredId(null);
                setTooltipTarget(null);
              }}
              style={{
                fontFamily: FONT_FAMILY,
                padding: '6px 10px',
                fontSize: 13,
                fontWeight: 500,
                border: 'none',
                borderRadius: 6,
                background: isHovered ? '#f0f0f0' : 'transparent',
                color: isDisabled ? '#94a3b8' : isSelected ? '#1976d2' : '#1a1a1a',
                cursor: isDisabled ? 'not-allowed' : 'pointer',
                opacity: isDisabled ? 0.75 : 1,
                textDecoration: isSelected ? 'underline' : 'none',
                textUnderlineOffset: 3,
              }}
            >
              {label}
            </button>
            {tooltipTarget === id && tooltipText && (
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  marginTop: 6,
                  padding: '6px 10px',
                  background: '#2d2d2d',
                  color: '#fff',
                  fontSize: 12,
                  fontFamily: FONT_FAMILY,
                  fontWeight: 500,
                  borderRadius: 6,
                  whiteSpace: 'nowrap',
                  zIndex: 11,
                  boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
                }}
                >
                <span
                  style={{
                    position: 'absolute',
                    bottom: '100%',
                    left: '50%',
                    marginLeft: -6,
                    width: 0,
                    height: 0,
                    border: '6px solid transparent',
                    borderBottomColor: '#2d2d2d',
                  }}
                />
                {tooltipText}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default TimeRangeButtons;
