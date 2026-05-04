import { LineStyle } from 'lightweight-charts';

type PriceLevel = {
  price: number;
  color: string;
  title: string;
};

type NativePriceLine = {
  applyOptions: (options: object) => void;
};

type SeriesWithNativeLines = {
  createPriceLine: (options: object) => NativePriceLine;
  removePriceLine: (line: NativePriceLine) => void;
};

type SeriesLike = {
  attachPrimitive?: (primitive: unknown) => void;
  detachPrimitive?: (primitive: unknown) => void;
  [key: symbol]: unknown;
};

const PRICE_LEVEL_PRIMITIVE_KEY = Symbol('terrafin-price-level-primitive');
const PRICE_LEVEL_SIGNATURE_KEY = Symbol('terrafin-price-level-signature');
const NATIVE_PRICE_LINES_KEY = Symbol('terrafin-native-price-lines');
const NATIVE_PRICE_LINES_SIG_KEY = Symbol('terrafin-native-price-lines-sig');

class SeriesPriceLevelPrimitive {
  constructor(private readonly levels: PriceLevel[]) {}

  attached(): void {}

  detached(): void {}

  updateAllViews(): void {}

  paneViews(): readonly [] {
    return [];
  }

  autoscaleInfo(): { priceRange: { minValue: number; maxValue: number } } | null {
    const prices = this.levels
      .map((level) => level.price)
      .filter((price) => Number.isFinite(price));

    if (prices.length === 0) {
      return null;
    }

    return {
      priceRange: {
        minValue: Math.min(...prices),
        maxValue: Math.max(...prices),
      },
    };
  }
}

export function attachPriceLevelsPrimitive(series: SeriesLike, levels?: PriceLevel[]): void {
  const nextSignature = JSON.stringify(levels ?? []);
  const currentSignature = series[PRICE_LEVEL_SIGNATURE_KEY];
  if (currentSignature === nextSignature) {
    return;
  }

  detachPriceLevelsPrimitive(series);
  if (!levels || levels.length === 0 || typeof series.attachPrimitive !== 'function') {
    series[PRICE_LEVEL_SIGNATURE_KEY] = nextSignature;
    return;
  }

  const primitive = new SeriesPriceLevelPrimitive(levels);
  series.attachPrimitive(primitive);
  series[PRICE_LEVEL_PRIMITIVE_KEY] = primitive;
  series[PRICE_LEVEL_SIGNATURE_KEY] = nextSignature;
}

export function detachPriceLevelsPrimitive(series: SeriesLike | null | undefined): void {
  const primitive = series?.[PRICE_LEVEL_PRIMITIVE_KEY];
  if (!primitive) {
    return;
  }
  if (typeof series?.detachPrimitive === 'function') {
    try {
      series.detachPrimitive(primitive);
    } catch {
      // Ignore detach failures during chart teardown.
    }
  }
  delete series[PRICE_LEVEL_PRIMITIVE_KEY];
  delete series[PRICE_LEVEL_SIGNATURE_KEY];
}

export function syncNativePriceLines(series: SeriesLike, levels?: PriceLevel[]): void {
  const nextSig = JSON.stringify(levels ?? []);
  if (series[NATIVE_PRICE_LINES_SIG_KEY] === nextSig) return;

  // Remove previously created native lines.
  const existing = series[NATIVE_PRICE_LINES_KEY] as NativePriceLine[] | undefined;
  if (existing?.length) {
    const s = series as unknown as SeriesWithNativeLines;
    for (const line of existing) {
      try { s.removePriceLine(line); } catch { /* teardown */ }
    }
  }
  series[NATIVE_PRICE_LINES_KEY] = [];
  series[NATIVE_PRICE_LINES_SIG_KEY] = nextSig;

  if (!levels?.length) return;

  const s = series as unknown as SeriesWithNativeLines;
  if (typeof s.createPriceLine !== 'function') return;

  const created: NativePriceLine[] = [];
  for (const level of levels) {
    created.push(s.createPriceLine({
      price: level.price,
      color: level.color,
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      axisLabelColor: level.color,
      title: level.title,
    }));
  }
  series[NATIVE_PRICE_LINES_KEY] = created;
}

export function clearNativePriceLines(series: SeriesLike | null | undefined): void {
  if (!series) return;
  const existing = series[NATIVE_PRICE_LINES_KEY] as NativePriceLine[] | undefined;
  if (existing?.length) {
    const s = series as unknown as SeriesWithNativeLines;
    for (const line of existing) {
      try { s.removePriceLine(line); } catch { /* teardown */ }
    }
  }
  delete series[NATIVE_PRICE_LINES_KEY];
  delete series[NATIVE_PRICE_LINES_SIG_KEY];
}
