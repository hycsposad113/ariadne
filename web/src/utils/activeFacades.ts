export type FacadeSegment = { active: boolean; geometry: { type: string; coordinates: number[][] }; length_m: number };

// Only explicit exterior segments can carry active-use colour.
export function activeFacadeVertices(value: unknown, height: number, local: (x: number, y: number) => number[]): number[][][] {
  if (!Array.isArray(value) || !Number.isFinite(height) || height <= 0) return [];
  return value.flatMap((edge: FacadeSegment) => {
    if (edge.active !== true || edge.geometry?.type !== 'LineString' || !Array.isArray(edge.geometry.coordinates)) return [];
    const cs = edge.geometry.coordinates;
    if (cs.length !== 2 || cs.some(p => p.length < 2 || !p.slice(0, 2).every(Number.isFinite))) return [];
    const a = local(cs[0][0], cs[0][1]); const b = local(cs[1][0], cs[1][1]);
    return [[[a[0], a[1], 0], [b[0], b[1], 0], [b[0], b[1], height],
      [a[0], a[1], 0], [b[0], b[1], height], [a[0], a[1], height]]];
  });
}
