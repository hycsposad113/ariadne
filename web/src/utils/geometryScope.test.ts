import { describe, expect, it } from 'vitest';
import { measurePolygonalAreaM2, preparePolygonWithinStudyArea } from './geometryScope';

const square = {
  type: 'Polygon',
  coordinates: [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
} as const;

describe('preparePolygonWithinStudyArea', () => {
  it('closes and accepts a valid polygon covered by a Polygon StudyArea', () => {
    const result = preparePolygonWithinStudyArea([[10, 10], [40, 10], [40, 40], [10, 40]], square);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.closedRing).toEqual([[10, 10], [40, 10], [40, 40], [10, 40], [10, 10]]);
      expect(result.areaM2).toBe(900);
    }
  });

  it('rejects a polygon edge that crosses outside a concave StudyArea even when its vertices are inside', () => {
    const uShape = {
      type: 'Polygon',
      coordinates: [[[0, 0], [100, 0], [100, 100], [70, 100], [70, 30], [30, 30], [30, 100], [0, 100], [0, 0]]],
    } as const;
    const candidate = [[10, 50], [90, 50], [90, 70], [10, 70]] as [number, number][];

    const result = preparePolygonWithinStudyArea(candidate, uShape);

    expect(result).toMatchObject({ ok: false, reason: 'OUTSIDE_STUDY_AREA' });
  });

  it('rejects a polygon wholly inside the bounding box but in a StudyArea hole', () => {
    const withHole = {
      type: 'Polygon',
      coordinates: [
        [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
        [[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]],
      ],
    } as const;

    const result = preparePolygonWithinStudyArea([[45, 45], [55, 45], [55, 55], [45, 55]], withHole);

    expect(result).toMatchObject({ ok: false, reason: 'OUTSIDE_STUDY_AREA' });
  });

  it('rejects a candidate that surrounds a hole without crossing its boundary', () => {
    const withHole = {
      type: 'Polygon',
      coordinates: [
        [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
        [[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]],
      ],
    } as const;

    expect(preparePolygonWithinStudyArea([[20, 20], [80, 20], [80, 80], [20, 80]], withHole))
      .toMatchObject({ ok: false, reason: 'OUTSIDE_STUDY_AREA' });
  });

  it('accepts a polygon within one MultiPolygon component and rejects one spanning components', () => {
    const multi = {
      type: 'MultiPolygon',
      coordinates: [
        [[[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]]],
        [[[60, 0], [100, 0], [100, 40], [60, 40], [60, 0]]],
      ],
    } as const;

    expect(preparePolygonWithinStudyArea([[5, 5], [30, 5], [30, 30], [5, 30]], multi).ok).toBe(true);
    expect(preparePolygonWithinStudyArea([[10, 10], [90, 10], [90, 30], [10, 30]], multi))
      .toMatchObject({ ok: false, reason: 'OUTSIDE_STUDY_AREA' });
  });

  it('rejects a candidate with an outside vertex and a nonzero-area self-intersection', () => {
    expect(preparePolygonWithinStudyArea([[10, 10], [110, 10], [110, 30], [10, 30]], square))
      .toMatchObject({ ok: false, reason: 'OUTSIDE_STUDY_AREA' });
    expect(preparePolygonWithinStudyArea([[10, 10], [40, 40], [10, 40], [30, 10]], square))
      .toMatchObject({ ok: false, reason: 'INVALID_POLYGON' });
  });

  it('fails closed when geometry is absent, non-finite, self-intersecting, or zero-area', () => {
    expect(preparePolygonWithinStudyArea([[1, 1], [2, 1], [2, 2]], null))
      .toMatchObject({ ok: false, reason: 'STUDY_AREA_UNAVAILABLE' });
    expect(preparePolygonWithinStudyArea([[1, 1], [2, 1], [Number.NaN, 2]], square).ok).toBe(false);
    expect(preparePolygonWithinStudyArea([[10, 10], [30, 30], [10, 30], [30, 10]], square).ok).toBe(false);
    expect(preparePolygonWithinStudyArea([[10, 10], [20, 20], [30, 30]], square).ok).toBe(false);
  });
});

describe('StudyArea area measurement', () => {
  it('subtracts polygon holes and sums multiple StudyArea components', () => {
    expect(measurePolygonalAreaM2({
      type: 'MultiPolygon',
      coordinates: [
        [
          [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
          [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]],
        ],
        [[[20, 0], [25, 0], [25, 5], [20, 5], [20, 0]]],
      ],
    })).toBe(121);
  });
});


it('hides context lines crossing the site even when both endpoints are outside', async () => {
  const {lineTouchesStudyArea} = await import('./geometryScope');
  const site = {type:'Polygon',coordinates:[[[0,0],[10,0],[10,10],[0,10],[0,0]]]};
  expect(lineTouchesStudyArea([[-5,5],[15,5]],site)).toBe(true);
  expect(lineTouchesStudyArea([[-5,15],[15,15]],site)).toBe(false);
  expect(lineTouchesStudyArea([[2,2],[3,3]],site)).toBe(true);
});
