type PriceLevel = {
  price: number;
  color: string;
  title: string;
};

type SeriesLike = {
  attachPrimitive?: (primitive: unknown) => void;
  detachPrimitive?: (primitive: unknown) => void;
  [key: symbol]: unknown;
};

const PRICE_LEVEL_PRIMITIVE_KEY = Symbol('terrafin-price-level-primitive');
const PRICE_LEVEL_SIGNATURE_KEY = Symbol('terrafin-price-level-signature');

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
