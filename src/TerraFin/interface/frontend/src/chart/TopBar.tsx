import React from 'react';
import TimeframeSelector from './utils/TimeframeSelector';
import TimeRangeButtons from './utils/TimeRangeButtons';
import SearchInput from './utils/SearchInput';
import { FONT_FAMILY, TOP_BAR_HEIGHT, type RangeAvailability } from './constants';
import type { RangeId } from './constants';
import type { ChartHistoryBySeries, ChartSnapshot, ChartUpdate } from './types';
import type { IndicatorOption } from './utils/IndicatorSelector';
import IndicatorSelector from './utils/IndicatorSelector';

interface TopBarProps {
  sessionId: string;
  isEmpty: boolean;
  activeView: string;
  onViewChange: (view: string, snapshot: ChartSnapshot | null, historyBySeries?: ChartHistoryBySeries | null) => void;
  selectedRange: RangeId | null;
  onRangeSelect: (rangeId: RangeId) => void;
  rangeAvailability?: Partial<Record<RangeId, RangeAvailability>>;
  onOpenDateSelector: () => void;
  indicatorOptions: IndicatorOption[];
  selectedIndicators: Set<string>;
  onSelectedIndicatorsChange: (next: Set<string>) => void;
  onReset: () => void;
  riskAnalyticsOpen: boolean;
  onToggleRiskAnalytics: () => void;
  riskButtonRef?: React.Ref<HTMLButtonElement>;
  seriesCount: number;
  maxSeries: number;
  onSeriesAdded: (update: ChartUpdate | null, historyBySeries?: ChartHistoryBySeries | null) => void;
  statusBadgeLabel?: string | null;
  compact?: boolean;
}

const Divider: React.FC<{ compact?: boolean }> = ({ compact = false }) => (
  <div
    style={{
      width: 1,
      height: compact ? 18 : 20,
      background: 'var(--tf-border)',
      marginLeft: compact ? 4 : 4,
      marginRight: compact ? 4 : 4,
      flexShrink: 0,
      alignSelf: 'center',
    }}
  />
);

const RiskAnalyticsButton = React.forwardRef<HTMLButtonElement, { active: boolean; onClick: () => void }>(
  ({ active, onClick }, ref) => (
  <button
    ref={ref}
    type="button"
    onClick={onClick}
    style={{
      fontFamily: FONT_FAMILY,
      padding: '5px 10px',
      fontSize: "var(--tf-fs-xs)",
      fontWeight: 500,
      border: '1px solid var(--tf-border)',
      borderRadius: 'var(--tf-radius)',
      background: active ? 'var(--tf-bg-pane)' : 'var(--tf-bg-elevated)',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: 5,
      color: active ? 'var(--tf-amber)' : 'var(--tf-text)',
      flexShrink: 0,
      whiteSpace: 'nowrap',
    }}
    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = 'var(--tf-bg-pane)'; }}
    onMouseLeave={(e) => { e.currentTarget.style.background = active ? 'var(--tf-bg-pane)' : 'var(--tf-bg-elevated)'; }}
  >
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 15h18M9 3v18M15 9l-6 6" />
    </svg>
    Risk Analytics
  </button>
  )
);
RiskAnalyticsButton.displayName = 'RiskAnalyticsButton';

const ResetButton: React.FC<{ onClick: () => void }> = ({ onClick }) => (
  <button
    type="button"
    onClick={onClick}
    aria-label="Clear selected indicators"
    style={{
      fontFamily: FONT_FAMILY,
      padding: '5px 12px',
      minHeight: 28,
      fontSize: "var(--tf-fs-xs)",
      fontWeight: 500,
      border: '1px solid var(--tf-border)',
      borderRadius: 'var(--tf-radius)',
      background: 'var(--tf-bg-elevated)',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: 5,
      color: 'var(--tf-text)',
      flexShrink: 0,
    }}
    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--tf-bg-pane)'; }}
    onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--tf-bg-elevated)'; }}
  >
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
    Reset
  </button>
);

const DatePickerButton: React.FC<{ onClick: () => void }> = ({ onClick }) => (
  <button
    type="button"
    onClick={onClick}
    aria-label="Pick date"
    style={{
      fontFamily: FONT_FAMILY,
      padding: '6px 8px',
      fontSize: "var(--tf-fs-base)",
      border: 'none',
      borderRadius: 'var(--tf-radius)',
      background: 'transparent',
      cursor: 'pointer',
      flexShrink: 0,
    }}
    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--tf-bg-pane)'; }}
    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
  >
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ display: 'block' }}
    >
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  </button>
);

const StatusBadgeOverlay: React.FC<{ label: string }> = ({ label }) => (
  // Fully BELOW the top bar (never straddling it — a half-overlap covers the
  // bar's own controls), on the left: recent price action lives on the chart's
  // right edge and older history loads on the left, so the top-left corner is
  // the spot that covers neither the freshest candles nor the bar.
  <div
    style={{
      position: 'absolute',
      left: 12,
      top: 'calc(100% + 6px)',
      zIndex: 4,
      pointerEvents: 'none',
      display: 'inline-flex',
      alignItems: 'center',
      padding: '5px 10px',
      borderRadius: 999,
      border: '1px solid var(--tf-border-strong)',
      background: 'var(--tf-bg-pane)',
      color: 'var(--tf-amber)',
      fontSize: "var(--tf-fs-xs)",
      fontWeight: 700,
      whiteSpace: 'nowrap',
    }}
  >
    {label}
  </div>
);

const TopBar: React.FC<TopBarProps> = ({
  sessionId,
  isEmpty,
  activeView,
  onViewChange,
  selectedRange,
  onRangeSelect,
  rangeAvailability,
  onOpenDateSelector,
  indicatorOptions,
  selectedIndicators,
  onSelectedIndicatorsChange,
  onReset,
  riskAnalyticsOpen,
  onToggleRiskAnalytics,
  riskButtonRef,
  seriesCount,
  maxSeries,
  onSeriesAdded,
  statusBadgeLabel,
  compact = false,
}) => {
  if (compact) {
    return (
      <div
        className="tf-chart-topbar"
        style={{
          position: 'relative',
          flexShrink: 0,
          height: 34,
          fontFamily: FONT_FAMILY,
          paddingLeft: 6,
          paddingRight: 6,
          gap: 0,
        }}
      >
        <SearchInput
          sessionId={sessionId}
          seriesCount={seriesCount}
          maxSeries={maxSeries}
          onAdded={onSeriesAdded}
          compact
        />
        {!isEmpty ? <Divider compact /> : null}
        {!isEmpty ? (
          <>
            <div
              className="tf-chart-scroll-row"
              style={{
                flex: 1,
                minWidth: 0,
              }}
            >
              <TimeframeSelector
                sessionId={sessionId}
                activeView={activeView}
                onViewChange={onViewChange}
                compact
              />
              <Divider compact />
              <TimeRangeButtons
                selectedRange={selectedRange}
                onRangeSelect={onRangeSelect}
                availability={rangeAvailability}
              />
              <Divider compact />
              <DatePickerButton onClick={onOpenDateSelector} />
              {indicatorOptions.length > 0 ? (
                <>
                  <Divider compact />
                  <RiskAnalyticsButton ref={riskButtonRef} active={riskAnalyticsOpen} onClick={onToggleRiskAnalytics} />
                </>
              ) : null}
            </div>
            {statusBadgeLabel ? <StatusBadgeOverlay label={statusBadgeLabel} /> : null}
          </>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="tf-chart-topbar"
      style={{
        position: 'relative',
        flexShrink: 0,
        height: TOP_BAR_HEIGHT,
        fontFamily: FONT_FAMILY,
      }}
    >
      <SearchInput sessionId={sessionId} seriesCount={seriesCount} maxSeries={maxSeries} onAdded={onSeriesAdded} />
      {!isEmpty && (
        <>
          <Divider />
          <TimeframeSelector sessionId={sessionId} activeView={activeView} onViewChange={onViewChange} />
          <Divider />
          <TimeRangeButtons
            selectedRange={selectedRange}
            onRangeSelect={onRangeSelect}
            availability={rangeAvailability}
          />
          <Divider />
          <DatePickerButton onClick={onOpenDateSelector} />
        </>
      )}

      <div style={{ flex: 1 }} />

      {!isEmpty && (
        <>
          {indicatorOptions.length > 0 && (
            <RiskAnalyticsButton ref={riskButtonRef} active={riskAnalyticsOpen} onClick={onToggleRiskAnalytics} />
          )}
          <div style={{ width: 6 }} />
          {indicatorOptions.length > 0 && selectedIndicators.size > 0 && (
            <>
              <ResetButton onClick={onReset} />
              <div style={{ width: 6 }} />
            </>
          )}
          {indicatorOptions.length > 0 && (
            <IndicatorSelector
              options={indicatorOptions}
              selected={selectedIndicators}
              onChange={onSelectedIndicatorsChange}
            />
          )}
        </>
      )}

      {!isEmpty && statusBadgeLabel ? <StatusBadgeOverlay label={statusBadgeLabel} /> : null}
    </div>
  );
};

export { ResetButton };
export default TopBar;
