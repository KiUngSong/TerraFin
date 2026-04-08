/**
 * Cumulative return computation for return-mode series.
 */
import type { LinePoint } from '../types';

export function createReturnsComputer(originalDataMap: Map<any, LinePoint[]>) { // eslint-disable-line
  let lastBaselineTime = '';

  return function computeReturns(fromTime: string) {
    if (fromTime === lastBaselineTime) return;
    lastBaselineTime = fromTime;
    originalDataMap.forEach((data, series) => {
      let baseline = data.find((p) => p.time >= fromTime);
      if (!baseline || baseline.value === 0) {
        baseline = data.find((p) => p.value !== 0);
      }
      if (!baseline) return;
      const baseVal = baseline.value;
      series.setData(
        data.map((p) => ({
          time: p.time,
          value: ((p.value / baseVal) - 1) * 100,
        }))
      );
    });
  };
}
