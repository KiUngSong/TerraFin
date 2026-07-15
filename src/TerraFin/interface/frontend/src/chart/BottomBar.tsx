import React, { useState } from 'react';
import { BOTTOM_BAR_HEIGHT, FONT_FAMILY } from './constants';
import IndicatorSelector, { type IndicatorOption } from './utils/IndicatorSelector';
import { ResetButton } from './TopBar';
import InfoHint from '../dcf/InfoHint';

const PriceScaleMode = { Normal: 0, Logarithmic: 1, Percentage: 2 } as const;

export interface SeriesTag {
  name: string;
  color: string;
  pinned: boolean;
  description?: string;
}

interface BottomBarProps {
  isEmpty: boolean;
  priceScaleMode: number;
  onPriceScaleModeChange: (mode: number) => void;
  forcePercentage?: boolean;
  seriesTags: SeriesTag[];
  onRemoveTag: (name: string) => void;
  compact?: boolean;
  indicatorOptions?: IndicatorOption[];
  selectedIndicators?: Set<string>;
  onSelectedIndicatorsChange?: (next: Set<string>) => void;
  onReset?: () => void;
  volumeAvailable?: boolean;
  showVolume?: boolean;
  onShowVolumeChange?: (next: boolean) => void;
}

const SeriesTags: React.FC<{ tags: SeriesTag[]; onRemove: (name: string) => void; compact?: boolean }> = ({
  tags,
  onRemove,
  compact = false,
}) => (
  <div className="tf-chart-series-tags">
    {tags.map((tag) => (
      <div
        key={tag.name}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          background: 'var(--tf-bg-elevated)',
          borderRadius: 'var(--tf-radius)',
          padding: compact ? '2px 5px 2px 7px' : '3px 6px 3px 8px',
          fontSize: compact ? 'var(--tf-fs-micro)' : 'var(--tf-fs-xs)',
          fontWeight: 600,
          color: 'var(--tf-text)',
          whiteSpace: 'nowrap',
          flexShrink: 0,
        }}
      >
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: tag.color, flexShrink: 0 }} />
        {tag.name}
        {tag.description && <InfoHint text={tag.description} compact />}
        {!tag.pinned && (
          <button
            type="button"
            onClick={() => onRemove(tag.name)}
            aria-label={`Remove ${tag.name}`}
            style={{
              border: 'none',
              background: 'transparent',
              cursor: 'pointer',
              padding: 0,
              marginLeft: 1,
              width: 18,
              height: 18,
              borderRadius: 999,
              fontSize: "var(--tf-fs-xs)",
              color: 'var(--tf-muted)',
              lineHeight: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--tf-text)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--tf-muted)'; }}
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>
    ))}
  </div>
);

const Divider: React.FC<{ compact?: boolean }> = ({ compact = false }) => (
  <div
    style={{
      width: 1,
      height: compact ? 16 : 20,
      background: 'var(--tf-border)',
      marginRight: compact ? 3 : 4,
      marginLeft: compact ? 3 : 4,
      flexShrink: 0,
    }}
  />
);

const PriceScaleControls: React.FC<{
  mode: number;
  onChange: (m: number) => void;
  forcePercentage?: boolean;
  compact?: boolean;
}> = ({ mode, onChange, forcePercentage, compact = false }) => {
  const [hovered, setHovered] = useState<'%' | 'log' | null>(null);
  const buttonPadding = compact ? '4px 8px' : '6px 10px';
  const buttonFontSize = compact ? 'var(--tf-fs-xs)' : 'var(--tf-fs-base)';

  return (
    <>
      <Divider compact={compact} />
      <button
        type="button"
        onMouseEnter={() => setHovered('%')}
        onMouseLeave={() => setHovered(null)}
        onClick={() => {
          if (!forcePercentage) {
            onChange(mode === PriceScaleMode.Percentage ? PriceScaleMode.Normal : PriceScaleMode.Percentage);
          }
        }}
        style={{
          fontFamily: FONT_FAMILY,
          padding: buttonPadding,
          minHeight: compact ? 28 : undefined,
          fontSize: buttonFontSize,
          fontWeight: 500,
          border: 'none',
          borderRadius: 'var(--tf-radius)',
          background:
            forcePercentage || mode === PriceScaleMode.Percentage
              ? 'var(--tf-bg-pane)'
              : hovered === '%'
                ? 'var(--tf-bg-pane)'
                : 'transparent',
          color: forcePercentage || mode === PriceScaleMode.Percentage ? 'var(--tf-amber)' : 'var(--tf-text)',
          cursor: forcePercentage ? 'default' : 'pointer',
          lineHeight: 1,
          whiteSpace: 'nowrap',
        }}
      >
        %
      </button>
      <Divider compact={compact} />
      <button
        type="button"
        onMouseEnter={() => setHovered('log')}
        onMouseLeave={() => setHovered(null)}
        onClick={() => {
          if (!forcePercentage) {
            onChange(mode === PriceScaleMode.Logarithmic ? PriceScaleMode.Normal : PriceScaleMode.Logarithmic);
          }
        }}
        style={{
          fontFamily: FONT_FAMILY,
          padding: buttonPadding,
          minHeight: compact ? 28 : undefined,
          fontSize: buttonFontSize,
          fontWeight: 500,
          border: 'none',
          borderRadius: 'var(--tf-radius)',
          background: mode === PriceScaleMode.Logarithmic ? 'var(--tf-bg-pane)' : hovered === 'log' ? 'var(--tf-bg-pane)' : 'transparent',
          color: forcePercentage ? 'var(--tf-muted)' : mode === PriceScaleMode.Logarithmic ? 'var(--tf-amber)' : 'var(--tf-text)',
          cursor: forcePercentage ? 'default' : 'pointer',
          lineHeight: 1,
          whiteSpace: 'nowrap',
        }}
      >
        Log
      </button>
      <Divider compact={compact} />
    </>
  );
};

const VolumeToggle: React.FC<{
  available: boolean;
  active: boolean;
  onToggle: () => void;
  compact?: boolean;
}> = ({ available, active, onToggle, compact = false }) => {
  const [hovered, setHovered] = useState(false);
  const buttonPadding = compact ? '4px 8px' : '6px 10px';
  const buttonFontSize = compact ? 'var(--tf-fs-xs)' : 'var(--tf-fs-base)';
  const disabled = !available;
  return (
    <>
      <Divider compact={compact} />
      <button
        type="button"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => {
          if (!disabled) onToggle();
        }}
        title={
          disabled
            ? 'Volume available only for a single candlestick chart'
            : active ? 'Hide volume' : 'Show volume'
        }
        disabled={disabled}
        style={{
          fontFamily: FONT_FAMILY,
          padding: buttonPadding,
          minHeight: compact ? 28 : undefined,
          fontSize: buttonFontSize,
          fontWeight: 500,
          border: 'none',
          borderRadius: 'var(--tf-radius)',
          background: disabled
            ? 'transparent'
            : active
              ? 'var(--tf-bg-pane)'
              : hovered
                ? 'var(--tf-bg-pane)'
                : 'transparent',
          color: disabled ? 'var(--tf-muted)' : active ? 'var(--tf-amber)' : 'var(--tf-text)',
          cursor: disabled ? 'default' : 'pointer',
          lineHeight: 1,
          whiteSpace: 'nowrap',
        }}
      >
        Vol
      </button>
    </>
  );
};

const BottomBar: React.FC<BottomBarProps> = ({
  isEmpty,
  priceScaleMode,
  onPriceScaleModeChange,
  forcePercentage,
  seriesTags,
  onRemoveTag,
  compact = false,
  indicatorOptions = [],
  selectedIndicators,
  onSelectedIndicatorsChange,
  onReset,
  volumeAvailable = false,
  showVolume = false,
  onShowVolumeChange,
}) => {
  if (compact) {
    const compactRowStyle: React.CSSProperties = {
      flexShrink: 0,
      height: 28,
      background: 'var(--tf-bg-pane)',
      borderTop: '1px solid var(--tf-border)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingLeft: 12,
      paddingRight: 24,
      overflow: 'hidden',
      fontFamily: FONT_FAMILY,
    };
    return (
      <div style={{ flexShrink: 0 }}>
        <div style={compactRowStyle}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              minWidth: 0,
              flex: 1,
              overflowX: 'auto',
              overflowY: 'hidden',
              scrollbarWidth: 'thin',
              flexWrap: 'nowrap',
            }}
          >
            {indicatorOptions.length > 0 && onSelectedIndicatorsChange ? (
              <>
                {selectedIndicators && selectedIndicators.size > 0 && onReset ? (
                  <ResetButton onClick={onReset} />
                ) : null}
                <IndicatorSelector
                  options={indicatorOptions}
                  selected={selectedIndicators || new Set()}
                  onChange={onSelectedIndicatorsChange}
                  dropUp
                />
              </>
            ) : null}
          </div>

          {!isEmpty ? (
            <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0, marginLeft: 'auto' }}>
              {onShowVolumeChange ? (
                <VolumeToggle
                  available={volumeAvailable}
                  active={showVolume}
                  onToggle={() => onShowVolumeChange(!showVolume)}
                  compact
                />
              ) : null}
              <PriceScaleControls
                mode={priceScaleMode}
                onChange={onPriceScaleModeChange}
                forcePercentage={forcePercentage}
                compact
              />
            </div>
          ) : null}
        </div>

        {seriesTags.length > 0 ? (
          <div style={{ ...compactRowStyle, justifyContent: 'flex-start' }}>
            <SeriesTags tags={seriesTags} onRemove={onRemoveTag} compact />
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="tf-chart-bottom-bar">
      <div className="tf-chart-bottom-bar__row" style={{ minHeight: BOTTOM_BAR_HEIGHT, fontFamily: FONT_FAMILY }}>
        <SeriesTags tags={seriesTags} onRemove={onRemoveTag} />
        {!isEmpty ? (
          <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
            {onShowVolumeChange ? (
              <VolumeToggle
                available={volumeAvailable}
                active={showVolume}
                onToggle={() => onShowVolumeChange(!showVolume)}
              />
            ) : null}
            <PriceScaleControls
              mode={priceScaleMode}
              onChange={onPriceScaleModeChange}
              forcePercentage={forcePercentage}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default BottomBar;
