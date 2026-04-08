import type { ChartZone } from '../types';

type SeriesLike = {
  attachPrimitive?: (primitive: unknown) => void;
  detachPrimitive?: (primitive: unknown) => void;
  priceToCoordinate?: (price: number) => number | null;
  [key: symbol]: unknown;
};

type ZoneBand = {
  top: number;
  bottom: number;
  color: string;
};

const ZONE_PRIMITIVE_KEY = Symbol('terrafin-zone-primitive');
const ZONE_SIGNATURE_KEY = Symbol('terrafin-zone-signature');

class ZoneRenderer {
  private readonly getBands: () => ZoneBand[];

  constructor(getBands: () => ZoneBand[]) {
    this.getBands = getBands;
  }

  draw(): void {}

  drawBackground(target: any): void {
    const bands = this.getBands();
    if (bands.length === 0) {
      return;
    }

    target.useBitmapCoordinateSpace(({ context, bitmapSize, verticalPixelRatio }: any) => {
      context.save();
      for (const band of bands) {
        const top = Math.max(0, Math.min(bitmapSize.height, Math.round(band.top * verticalPixelRatio)));
        const bottom = Math.max(0, Math.min(bitmapSize.height, Math.round(band.bottom * verticalPixelRatio)));
        const height = bottom - top;
        if (height <= 0) {
          continue;
        }
        context.fillStyle = band.color;
        context.fillRect(0, top, bitmapSize.width, height);
      }
      context.restore();
    });
  }
}

class ZonePaneView {
  private readonly rendererRef: ZoneRenderer;

  constructor(getBands: () => ZoneBand[]) {
    this.rendererRef = new ZoneRenderer(getBands);
  }

  zOrder(): 'bottom' {
    return 'bottom';
  }

  renderer(): ZoneRenderer {
    return this.rendererRef;
  }
}

class SeriesZonePrimitive {
  private readonly paneViewsRef: readonly ZonePaneView[];
  private attachedParams: { series: SeriesLike } | null = null;

  constructor(private readonly zones: ChartZone[]) {
    this.paneViewsRef = [new ZonePaneView(() => this.zoneBands())];
  }

  attached(param: { series: SeriesLike }): void {
    this.attachedParams = param;
  }

  detached(): void {
    this.attachedParams = null;
  }

  updateAllViews(): void {}

  paneViews(): readonly ZonePaneView[] {
    return this.paneViewsRef;
  }

  autoscaleInfo(): { priceRange: { minValue: number; maxValue: number } } | null {
    if (this.zones.length === 0) {
      return null;
    }
    const bounds = this.zones.reduce(
      (acc, zone) => ({
        minValue: Math.min(acc.minValue, zone.from, zone.to),
        maxValue: Math.max(acc.maxValue, zone.from, zone.to),
      }),
      { minValue: Number.POSITIVE_INFINITY, maxValue: Number.NEGATIVE_INFINITY }
    );
    return Number.isFinite(bounds.minValue) && Number.isFinite(bounds.maxValue)
      ? { priceRange: bounds }
      : null;
  }

  private zoneBands(): ZoneBand[] {
    const series = this.attachedParams?.series;
    if (!series?.priceToCoordinate) {
      return [];
    }

    return this.zones.flatMap((zone) => {
      const first = series.priceToCoordinate!(zone.from);
      const second = series.priceToCoordinate!(zone.to);
      if (!Number.isFinite(first) || !Number.isFinite(second)) {
        return [];
      }
      return [
        {
          top: Math.min(first as number, second as number),
          bottom: Math.max(first as number, second as number),
          color: zone.color,
        },
      ];
    });
  }
}

export function attachZonePrimitive(series: SeriesLike, zones?: ChartZone[]): void {
  const nextSignature = JSON.stringify(zones ?? []);
  const currentSignature = series[ZONE_SIGNATURE_KEY];
  if (currentSignature === nextSignature) {
    return;
  }
  detachZonePrimitive(series);
  if (!zones || zones.length === 0 || typeof series.attachPrimitive !== 'function') {
    series[ZONE_SIGNATURE_KEY] = nextSignature;
    return;
  }
  const primitive = new SeriesZonePrimitive(zones);
  series.attachPrimitive(primitive);
  series[ZONE_PRIMITIVE_KEY] = primitive;
  series[ZONE_SIGNATURE_KEY] = nextSignature;
}

export function detachZonePrimitive(series: SeriesLike | null | undefined): void {
  const primitive = series?.[ZONE_PRIMITIVE_KEY];
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
  delete series[ZONE_PRIMITIVE_KEY];
  delete series[ZONE_SIGNATURE_KEY];
}
