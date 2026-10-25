import { describe, it, expect } from 'vitest';
import { activeFacadeVertices } from './activeFacades';
describe('specific active facades', () => {
  it('renders measured active edges with local coordinates, without a whole-building band', () => {
    const edge = { active: true, length_m: 10, geometry: { type: 'LineString', coordinates: [[100, 200], [110, 200]] } };
    const result = activeFacadeVertices([edge, { ...edge, active: false }], 4.5, (x, y) => [x - 100, y - 200]);
    expect(result).toHaveLength(1); expect(result[0][2]).toEqual([10, 0, 4.5]);
  });
  it('omits absent, malformed and nonfinite segments', () => {
    expect(activeFacadeVertices(true, 3.5, (x,y) => [x,y])).toEqual([]);
    expect(activeFacadeVertices([{ active: true, geometry: {type:'Polygon', coordinates:[]} }], 3.5, (x,y) => [x,y])).toEqual([]);
    expect(activeFacadeVertices([], NaN, (x,y) => [x,y])).toEqual([]);
  });
});
