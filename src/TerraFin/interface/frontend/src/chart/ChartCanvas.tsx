import React, { useEffect, useMemo, useRef } from 'react';
import { createChart, ColorType, PriceScaleMode, type UTCTimestamp } from 'lightweight-charts';
import { DEFAULT_PRICE_SCALE_MARGINS, FONT_FAMILY, type ChartScaleMargins } from './constants';
import type { RangeId } from './constants';
import type { CandlestickPoint, ChartPayload, ChartSeries, LinePoint } from './types';
import type { DateSelectionRequest } from './utils/DateSelector';
import {
  getVisibleRange,
  timeToDateString,
  visibleRangeToDateStrings,
  rangesMatch,
  rangeToSeconds,
} from './utils/chartTimeUtils';
import {
  applySeriesAppearance,
  applySeriesData,
  buildSeriesSpecs,
  createSeriesFromSpec,
  destroySeries,
  type SeriesRef,
} from './utils/chartSeries';
import { createTooltip } from './utils/chartTooltip';
import { createReturnsComputer } from './utils/chartReturns';

interface ChartCanvasProps {
  sessionId: string;
  payload: ChartPayload;
  selectedRange: RangeId | null;
  priceScaleMode: number;
  priceScaleMargins?: ChartScaleMargins;
  dateSelectionRequest: DateSelectionRequest;
  onAppliedDateSelection: () => void;
  onUserScroll?: () => void;
  selectedIndicatorsSig: string;
  onVisibleRangeChange?: (range: { from: string; to: string } | null) => void;
  showVolume?: boolean;
  onVolumeAvailableChange?: (available: boolean) => void;
}

const VOLUME_SERIES_KEY = '__volume_overlay__';
const VOLUME_PRICE_SCALE_ID = 'volume';
const VOLUME_UP_COLOR = 'rgba(38, 166, 154, 0.5)';
const VOLUME_DOWN_COLOR = 'rgba(239, 83, 80, 0.5)';

function toUtcSeconds(date: string): UTCTimestamp {
  return Math.floor(new Date(date).getTime() / 1000) as UTCTimestamp;
}

function getContainerDimension(size: number, fallback: number): number {
  return size > 0 ? size : fallback;
}

const ChartCanvas: React.FC<ChartCanvasProps> = ({
  sessionId,
  payload,
  selectedRange,
  priceScaleMode,
  priceScaleMargins = DEFAULT_PRICE_SCALE_MARGINS,
  dateSelectionRequest,
  onAppliedDateSelection,
  onUserScroll,
  selectedIndicatorsSig,
  onVisibleRangeChange,
  showVolume = false,
  onVolumeAvailableChange,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRefsByKeyRef = useRef<Map<string, SeriesRef>>(new Map());
  const seriesSignatureByKeyRef = useRef<Map<string, string>>(new Map());
  const seriesAppearanceSignatureByKeyRef = useRef<Map<string, string>>(new Map());
  const seriesDataSignatureByKeyRef = useRef<Map<string, string>>(new Map());
  const seriesToIdRef = useRef<Map<SeriesRef, string>>(new Map());
  const seriesToColorRef = useRef<Map<SeriesRef, string>>(new Map());
  const originalDataMapRef = useRef<Map<SeriesRef, LinePoint[]>>(new Map());
  const computeReturnsRef = useRef<(fromTime: string) => void>(() => {});
  const lastVisibleRangeRef = useRef<{ from: number; to: number } | null>(null);
  const ignoreNextRangeChangeRef = useRef(false);
  const onUserScrollRef = useRef(onUserScroll);
  const onVisibleRangeChangeRef = useRef(onVisibleRangeChange);
  const selectedRangeRef = useRef<RangeId | null>(selectedRange);
  const allPointsRef = useRef<Array<{ time: string }>>([]);
  const returnModeRef = useRef(false);
  const publishedRangeSigRef = useRef<string | null>(null);

  onUserScrollRef.current = onUserScroll;
  onVisibleRangeChangeRef.current = onVisibleRangeChange;
  selectedRangeRef.current = selectedRange;

  const activeSeries = useMemo(() => {
    const selected = new Set(selectedIndicatorsSig ? selectedIndicatorsSig.split(',') : []);
    return (payload.series ?? []).filter((series) => {
      if (!series.indicator) return true;
      return series.indicatorGroup != null && selected.has(series.indicatorGroup);
    });
  }, [payload, selectedIndicatorsSig]);

  const rangeAxisSeries = useMemo(() => {
    const baseSeries = activeSeries.filter((series) => !series.indicator);
    const candidates = baseSeries.length > 0 ? baseSeries : activeSeries;
    if (candidates.length === 0) {
      return null;
    }
    const candlestick = candidates.find((series) => series.seriesType === 'candlestick');
    if (candlestick) {
      return candlestick;
    }
    return candidates.reduce((best, current) => {
      const bestLength = best.data?.length ?? 0;
      const currentLength = current.data?.length ?? 0;
      if (currentLength !== bestLength) {
        return currentLength > bestLength ? current : best;
      }
      const bestLast = best.data?.[best.data.length - 1];
      const currentLast = current.data?.[current.data.length - 1];
      const bestTime = bestLast?.time != null ? String(bestLast.time) : '';
      const currentTime = currentLast?.time != null ? String(currentLast.time) : '';
      if (currentTime !== bestTime) {
        return currentTime > bestTime ? current : best;
      }
      return best;
    });
  }, [activeSeries]);

  const hasCandlestick = useMemo(
    () => activeSeries.some((series) => series.seriesType === 'candlestick'),
    [activeSeries]
  );
  const forcePercentage = payload.forcePercentage === true;
  const hasReturnSeries = useMemo(
    () => activeSeries.some((series) => series.returnSeries),
    [activeSeries]
  );
  const returnMode = forcePercentage || (hasReturnSeries && priceScaleMode === 2);

  const allPoints = useMemo(() => {
    const data = rangeAxisSeries?.data ?? [];
    return data
      .map((point) => (point != null && point.time != null ? { time: String(point.time) } : null))
      .filter((point): point is { time: string } => point != null && point.time.length > 0);
  }, [rangeAxisSeries]);

  allPointsRef.current = allPoints;
  returnModeRef.current = returnMode;

  const baseCandlesticks = useMemo(
    () => activeSeries.filter((series) => series.seriesType === 'candlestick' && !series.indicator),
    [activeSeries]
  );
  const volumeCandle = baseCandlesticks.length === 1 ? baseCandlesticks[0] : null;
  const volumeAvailable = useMemo(() => {
    if (!volumeCandle) return false;
    return (volumeCandle.data as CandlestickPoint[]).some(
      (point) => typeof point.volume === 'number' && point.volume > 0
    );
  }, [volumeCandle]);
  useEffect(() => {
    onVolumeAvailableChange?.(volumeAvailable);
  }, [volumeAvailable, onVolumeAvailableChange]);

  const augmentedSeries = useMemo<ChartSeries[]>(() => {
    if (!showVolume || !volumeCandle || !volumeAvailable || returnMode) {
      return activeSeries;
    }
    const candleData = volumeCandle.data as CandlestickPoint[];
    const volumeData = candleData
      .filter((p) => typeof p.volume === 'number' && p.volume! >= 0)
      .map((p) => ({
        time: p.time,
        value: p.volume as number,
        color: p.close >= p.open ? VOLUME_UP_COLOR : VOLUME_DOWN_COLOR,
      })) as unknown as LinePoint[];
    if (volumeData.length === 0) return activeSeries;
    const volumeSeries: ChartSeries = {
      id: VOLUME_SERIES_KEY,
      seriesType: 'histogram',
      data: volumeData,
      priceScaleId: VOLUME_PRICE_SCALE_ID,
    };
    return [...activeSeries, volumeSeries];
  }, [activeSeries, showVolume, volumeAvailable, volumeCandle, returnMode]);

  const seriesSpecs = useMemo(
    () => buildSeriesSpecs(augmentedSeries, { hasCandlestick, returnMode }),
    [augmentedSeries, hasCandlestick, returnMode]
  );
  const hasRenderableSeries = seriesSpecs.length > 0;
  const returnComputationSignature = useMemo(
    () =>
      returnMode
        ? seriesSpecs.map((spec) => `${spec.key}:${spec.dataSignature}`).join('|')
        : '',
    [returnMode, seriesSpecs]
  );

  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el || chartRef.current) return;

    const chart = createChart(el, {
      layout: {
        textColor: 'black',
        background: { type: ColorType.Solid, color: 'white' },
        fontFamily: FONT_FAMILY,
      },
      localization: {
        locale: 'en-US',
      },
      width: getContainerDimension(el.clientWidth, 400),
      height: getContainerDimension(el.clientHeight, 200),
      crosshair: { mode: 1 },
      leftPriceScale: {
        visible: false,
        borderVisible: true,
        mode: priceScaleMode as PriceScaleMode,
        scaleMargins: priceScaleMargins,
      },
      rightPriceScale: {
        borderVisible: true,
        mode: (returnMode ? 0 : priceScaleMode) as PriceScaleMode,
        scaleMargins: priceScaleMargins,
      },
      timeScale: { borderVisible: true, timeVisible: true, secondsVisible: false, barSpacing: 10 },
    });
    chartRef.current = chart;

    const handleResize = () => {
      if (!chartContainerRef.current || !chartRef.current) return;
      chartRef.current.resize(
        getContainerDimension(chartContainerRef.current.clientWidth, 400),
        getContainerDimension(chartContainerRef.current.clientHeight, 200)
      );
    };
    handleResize();

    let returnDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    const { element: toolTipEl, handler: crosshairHandler } = createTooltip({
      el,
      seriesToId: seriesToIdRef.current,
      seriesToColor: seriesToColorRef.current,
      originalDataMap: originalDataMapRef.current,
    });

    const handleVisibleTimeRangeChange = (chartRange: { from: unknown; to: unknown } | null) => {
      if (chartRange) {
        const actual = visibleRangeToDateStrings(chartRange);
        const rangeSig = `${actual.from}|${actual.to}`;
        if (publishedRangeSigRef.current !== rangeSig) {
          publishedRangeSigRef.current = rangeSig;
          onVisibleRangeChangeRef.current?.(actual);
        }
      } else if (publishedRangeSigRef.current !== null) {
        publishedRangeSigRef.current = null;
        onVisibleRangeChangeRef.current?.(null);
      }
      if (returnModeRef.current && chartRange) {
        const nextFrom = timeToDateString(chartRange.from);
        if (returnDebounceTimer) clearTimeout(returnDebounceTimer);
        returnDebounceTimer = setTimeout(() => computeReturnsRef.current(nextFrom), 200);
      }
      if (ignoreNextRangeChangeRef.current) {
        ignoreNextRangeChangeRef.current = false;
        return;
      }
      if (chartRange) {
        lastVisibleRangeRef.current = rangeToSeconds(chartRange);
      }
      if (
        selectedRangeRef.current &&
        chartRange &&
        typeof onUserScrollRef.current === 'function'
      ) {
        const expected = getVisibleRange(allPointsRef.current, selectedRangeRef.current);
        if (expected) {
          const actual = visibleRangeToDateStrings(chartRange);
          if (!rangesMatch(actual, expected)) {
            onUserScrollRef.current();
          }
        }
      }
    };

    chart.subscribeCrosshairMove(crosshairHandler as (param: unknown) => void);
    chart.timeScale().subscribeVisibleTimeRangeChange(handleVisibleTimeRangeChange);
    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => handleResize());
      resizeObserver.observe(el);
    } else {
      window.addEventListener('resize', handleResize);
    }

    return () => {
      if (returnDebounceTimer) clearTimeout(returnDebounceTimer);
      if (resizeObserver) {
        resizeObserver.disconnect();
      } else {
        window.removeEventListener('resize', handleResize);
      }
      chart.timeScale().unsubscribeVisibleTimeRangeChange(handleVisibleTimeRangeChange);
      for (const seriesRef of Array.from(seriesRefsByKeyRef.current.values())) {
        destroySeries(seriesRef);
      }
      chart.remove();
      toolTipEl.remove();
      chartRef.current = null;
      seriesRefsByKeyRef.current.clear();
      seriesSignatureByKeyRef.current.clear();
      seriesAppearanceSignatureByKeyRef.current.clear();
      seriesDataSignatureByKeyRef.current.clear();
      seriesToIdRef.current.clear();
      seriesToColorRef.current.clear();
      originalDataMapRef.current.clear();
    };
  }, [sessionId]);

  useEffect(() => {
    if (!chartRef.current) return;

    chartRef.current.applyOptions({
      leftPriceScale: {
        visible: !returnMode && activeSeries.some((series) => series.priceScaleId === 'left'),
        borderVisible: true,
        mode: priceScaleMode as PriceScaleMode,
        scaleMargins: priceScaleMargins,
      },
      rightPriceScale: {
        borderVisible: true,
        mode: (returnMode ? 0 : priceScaleMode) as PriceScaleMode,
        scaleMargins: priceScaleMargins,
      },
    });
  }, [activeSeries, priceScaleMargins, priceScaleMode, returnMode]);

  useEffect(() => {
    if (!chartRef.current) return;

    const chart = chartRef.current;
    const nextKeys = new Set(seriesSpecs.map((spec) => spec.key));

    for (const [key, seriesRef] of Array.from(seriesRefsByKeyRef.current.entries())) {
      if (nextKeys.has(key)) continue;
      destroySeries(seriesRef);
      chart.removeSeries(seriesRef);
      seriesRefsByKeyRef.current.delete(key);
      seriesSignatureByKeyRef.current.delete(key);
      seriesAppearanceSignatureByKeyRef.current.delete(key);
      seriesDataSignatureByKeyRef.current.delete(key);
      seriesToIdRef.current.delete(seriesRef);
      seriesToColorRef.current.delete(seriesRef);
      originalDataMapRef.current.delete(seriesRef);
    }

    for (const spec of seriesSpecs) {
      const existing = seriesRefsByKeyRef.current.get(spec.key);
      const existingSignature = seriesSignatureByKeyRef.current.get(spec.key);
      let seriesRef = existing;

      if (seriesRef && existingSignature !== spec.recreateSignature) {
        destroySeries(seriesRef);
        chart.removeSeries(seriesRef);
        seriesRefsByKeyRef.current.delete(spec.key);
        seriesSignatureByKeyRef.current.delete(spec.key);
        seriesAppearanceSignatureByKeyRef.current.delete(spec.key);
        seriesDataSignatureByKeyRef.current.delete(spec.key);
        seriesToIdRef.current.delete(seriesRef);
        seriesToColorRef.current.delete(seriesRef);
        originalDataMapRef.current.delete(seriesRef);
        seriesRef = undefined;
      }

      if (!seriesRef) {
        seriesRef = createSeriesFromSpec(chart, spec);
        seriesRefsByKeyRef.current.set(spec.key, seriesRef);
        // Configure volume price scale immediately after series creation so the
        // scale exists when applyOptions runs (avoiding the first-toggle float bug).
        if (spec.key === VOLUME_SERIES_KEY) {
          try {
            chart.priceScale(VOLUME_PRICE_SCALE_ID).applyOptions({
              scaleMargins: { top: 0.8, bottom: 0 },
              visible: false,
            });
          } catch { /* ignore */ }
        }
      } else {
        if (seriesAppearanceSignatureByKeyRef.current.get(spec.key) !== spec.appearanceSignature) {
          applySeriesAppearance(seriesRef, spec);
        }
        if (seriesDataSignatureByKeyRef.current.get(spec.key) !== spec.dataSignature) {
          applySeriesData(seriesRef, spec);
        }
      }

      seriesSignatureByKeyRef.current.set(spec.key, spec.recreateSignature);
      seriesAppearanceSignatureByKeyRef.current.set(spec.key, spec.appearanceSignature);
      seriesDataSignatureByKeyRef.current.set(spec.key, spec.dataSignature);
      seriesToIdRef.current.set(seriesRef, spec.id);
      seriesToColorRef.current.set(seriesRef, spec.color);
      if (spec.originalData) {
        originalDataMapRef.current.set(seriesRef, spec.originalData);
      } else {
        originalDataMapRef.current.delete(seriesRef);
      }
    }

    const computeReturns = createReturnsComputer(originalDataMapRef.current);
    computeReturnsRef.current = computeReturns;
  }, [seriesSpecs]);

  useEffect(() => {
    if (!chartRef.current) return;

    const timeScale = chartRef.current.timeScale();
    if (!hasRenderableSeries || allPoints.length === 0) {
      return;
    }

    if (returnMode && originalDataMapRef.current.size > 0) {
      let initialFrom = allPoints[0]?.time ?? '';
      if (selectedRange) {
        const range = getVisibleRange(allPoints, selectedRange);
        if (range) initialFrom = range.from;
      } else if (lastVisibleRangeRef.current) {
        initialFrom = timeToDateString(lastVisibleRangeRef.current.from);
      }
      computeReturnsRef.current(initialFrom);
    }

    if (selectedRange) {
      const range = getVisibleRange(allPoints, selectedRange);
      if (range) {
        ignoreNextRangeChangeRef.current = true;
        timeScale.setVisibleRange({ from: toUtcSeconds(range.from), to: toUtcSeconds(range.to) });
        lastVisibleRangeRef.current = {
          from: toUtcSeconds(range.from),
          to: toUtcSeconds(range.to),
        };
      }
      return;
    }

    if (lastVisibleRangeRef.current) {
      const firstTime = allPoints[0]?.time;
      const lastTime = allPoints[allPoints.length - 1]?.time;
      if (firstTime && lastTime) {
        const firstSec = toUtcSeconds(firstTime);
        const lastSec = toUtcSeconds(lastTime);
        const saved = lastVisibleRangeRef.current;
        const from = Math.max(saved.from, firstSec) as UTCTimestamp;
        const to = Math.min(saved.to, lastSec) as UTCTimestamp;
        ignoreNextRangeChangeRef.current = true;
        timeScale.setVisibleRange({ from, to });
        lastVisibleRangeRef.current = { from, to };
        return;
      }
    }

    timeScale.fitContent();
  }, [allPoints, hasRenderableSeries, returnComputationSignature, returnMode, selectedRange]);

  useEffect(() => {
    if (!chartRef.current || !dateSelectionRequest) return;
    const timeScale = chartRef.current.timeScale();
    if (dateSelectionRequest.type === 'date') {
      const current = new Date(dateSelectionRequest.date);
      const from = new Date(current);
      from.setMonth(from.getMonth() - 1);
      const to = new Date(current);
      to.setMonth(to.getMonth() + 1);
      timeScale.setVisibleRange({
        from: Math.floor(from.getTime() / 1000) as UTCTimestamp,
        to: Math.floor(to.getTime() / 1000) as UTCTimestamp,
      });
      lastVisibleRangeRef.current = {
        from: Math.floor(from.getTime() / 1000),
        to: Math.floor(to.getTime() / 1000),
      };
    } else {
      const from = Math.floor(new Date(dateSelectionRequest.from).getTime() / 1000) as UTCTimestamp;
      const to = Math.floor(new Date(dateSelectionRequest.to).getTime() / 1000) as UTCTimestamp;
      timeScale.setVisibleRange({ from, to });
      lastVisibleRangeRef.current = { from, to };
    }
    onAppliedDateSelection();
  }, [dateSelectionRequest, onAppliedDateSelection]);

  return (
    <div
      ref={chartContainerRef}
      style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}
    />
  );
};

export default React.memo(ChartCanvas);
