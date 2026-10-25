import { describe, expect, it } from 'vitest';
import { selectFeaturesIntersectingExtent } from './featureSelection';

describe('selectFeaturesIntersectingExtent', () => {
  it('returns intersecting source feature IDs, including lines that cross the box', () => {
    const result = selectFeaturesIntersectingExtent(
      [
        {
          id: 'bag:partial',
          disposition: 'UNDECIDED',
          geometry: { type: 'Polygon', coordinates: [[[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]] },
        },
        {
          id: 'bag:outside',
          disposition: 'UNDECIDED',
          geometry: { type: 'Polygon', coordinates: [[[11, 11], [12, 11], [12, 12], [11, 12], [11, 11]]] },
        },
      ],
      [
        { id: 'osm:crossing', geometry: { type: 'LineString', coordinates: [[-3, 2], [8, 2]] }, length_m: 11, layer: 0 },
        { id: 'osm:touching', geometry: { type: 'LineString', coordinates: [[5, 5], [7, 5]] }, length_m: 2, layer: 0 },
        { id: 'osm:outside', geometry: { type: 'LineString', coordinates: [[6, 6], [8, 8]] }, length_m: 2.8, layer: 0 },
      ],
      { minX: 0, minY: 0, maxX: 5, maxY: 5 },
    );

    expect(result).toEqual({ buildingIds: ['bag:partial'], roadIds: ['osm:crossing', 'osm:touching'] });
  });

  it('does not select a polygon when the box is entirely inside one of its holes', () => {
    const result = selectFeaturesIntersectingExtent(
      [{
        id: 'bag:courtyard',
        disposition: 'UNDECIDED',
        geometry: {
          type: 'Polygon',
          coordinates: [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
          ],
        },
      }],
      [],
      { minX: 4.5, minY: 4.5, maxX: 5.5, maxY: 5.5 },
    );

    expect(result).toEqual({ buildingIds: [], roadIds: [] });
  });

  it('rejects invalid extents rather than silently selecting features', () => {
    expect(() => selectFeaturesIntersectingExtent([], [], { minX: 5, minY: 0, maxX: 0, maxY: 1 }))
      .toThrow(/finite ordered extent/i);
  });
});
