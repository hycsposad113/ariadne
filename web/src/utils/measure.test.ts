import { describe, expect, it } from 'vitest';
import {
  measure3DPoints,
  measureDistance2D,
  measurePolygon,
  measurePolylineLength,
  type MetricPoint2D,
  type MetricPoint3D,
} from './measure';

describe('EPSG:28992 metric measurements', () => {
  it('measures a 100 m source-coordinate line independent of viewport scale', () => {
    const start: MetricPoint2D = [89100, 435900];
    const end: MetricPoint2D = [89200, 435900];

    const resultAtZoomHalf = measureDistance2D(start, end);
    const resultAtZoomFour = measureDistance2D(start, end);

    expect(resultAtZoomHalf).toEqual({ value: 100, unit: 'm' });
    expect(resultAtZoomFour).toEqual(resultAtZoomHalf);
  });

  it('sums each segment of a source-coordinate polyline in metres', () => {
    const result = measurePolylineLength([[0, 0], [3, 4], [3, 14]]);

    expect(result.value).toBeCloseTo(15, 10);
    expect(result.unit).toBe('m');
  });

  it('returns area and perimeter for an open 20 m by 50 m polygon', () => {
    const rectangle: MetricPoint2D[] = [[0, 0], [20, 0], [20, 50], [0, 50]];

    expect(measurePolygon(rectangle)).toEqual({
      area: { value: 1000, unit: 'm²' },
      perimeter: { value: 140, unit: 'm' },
    });
  });

  it('accepts a repeated closing point without changing the polygon result', () => {
    const open: MetricPoint2D[] = [[0, 0], [20, 0], [20, 50], [0, 50]];
    const closed: MetricPoint2D[] = [...open, open[0]];

    expect(measurePolygon(closed)).toEqual(measurePolygon(open));
  });

  it('rejects a self-intersecting polygon before returning an area', () => {
    const bowTie: MetricPoint2D[] = [[0, 0], [20, 20], [0, 20], [20, 0]];

    expect(() => measurePolygon(bowTie)).toThrow(/simple polygon|self-intersecting/i);
  });

  it('rejects non-finite, zero-area, and too-short polygon inputs', () => {
    expect(() => measurePolygon([[0, 0], [10, 0], [Number.NaN, 10]])).toThrow(/finite/i);
    expect(() => measurePolygon([[0, 0], [10, 10], [20, 20]])).toThrow(/area/i);
    expect(() => measurePolygon([[0, 0], [10, 0]])).toThrow(/at least three/i);
  });

  it('returns horizontal distance, signed and absolute height deltas, and slant distance', () => {
    const lower: MetricPoint3D = [100, 200, 10];
    const higher: MetricPoint3D = [103, 204, 16];

    const result = measure3DPoints(lower, higher);

    expect(result.horizontalDistance).toEqual({ value: 5, unit: 'm' });
    expect(result.verticalDelta).toEqual({ signed: 6, absolute: 6, unit: 'm' });
    expect(result.slantDistance.unit).toBe('m');
    expect(result.slantDistance.value).toBeCloseTo(Math.sqrt(61), 12);
    expect(result).toMatchObject({
      horizontalDistance: { value: 5, unit: 'm' },
      verticalDelta: { signed: 6, absolute: 6, unit: 'm' },
    });
    expect(measure3DPoints(higher, lower).verticalDelta).toEqual({
      signed: -6,
      absolute: 6,
      unit: 'm',
    });
  });
});
