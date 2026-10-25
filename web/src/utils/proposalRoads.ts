import type { Segment } from '../types';
import type { SyntaxContextMode } from './syntaxContext';

export const ROAD_STYLES = {
  shared: { color: '#2dd4bf', dash: [], label: 'Pedestrian + bicycle' },
  pedestrian: { color: '#a3e635', dash: [3, 3], label: 'Pedestrian only' },
  motor: { color: '#f59e0b', dash: [], label: 'Motor / service access' },
  bicycle: { color: '#38bdf8', dash: [6, 3], label: 'Bicycle only' },
  existing: { color: '#475569', dash: [], label: 'Existing road' },
};

export function proposalRoadStyle(road: Pick<Segment, 'modes' | 'origin'>) {
  if (!road.modes) return ROAD_STYLES.existing;
  if (road.modes.includes('motor_vehicle')) return ROAD_STYLES.motor;
  if (road.modes.includes('pedestrian') && road.modes.includes('bicycle')) return ROAD_STYLES.shared;
  return road.modes.includes('pedestrian') ? ROAD_STYLES.pedestrian : ROAD_STYLES.bicycle;
}

export function proposalRoadMetadata(properties: Record<string, unknown> = {}, id = '') {
  const collector = /^road:south_strip_(collector|connector):/.test(String(properties.road_id ?? id));
  return {
    modes: Array.isArray(properties.modes) ? properties.modes as SyntaxContextMode[] : collector ? ['pedestrian', 'bicycle', 'motor_vehicle'] as SyntaxContextMode[] : ['pedestrian', 'bicycle'] as SyntaxContextMode[],
    origin: (properties.origin ?? 'new') as 'retained' | 'transformed' | 'new',
    width_m: typeof properties.width_m === 'number' ? properties.width_m : undefined,
    semantics_provenance: String(properties.semantics_provenance ?? 'ASSUMED_COMMANDER'),
  };
}

type XY = number[];
function insideRing(p: XY, ring: XY[]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i], b = ring[j];
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

/** Clip old context centreline strokes out of a proposal site, including holes.
 * Existing retained roads are drawn from the proposal layer. Outside stubs remain.
 */
export function outsideRoadParts(coords: XY[], site: { type: string; coordinates: unknown } | null | undefined): XY[][] {
  if (!site || !['Polygon', 'MultiPolygon'].includes(site.type)) return [coords];
  const polygons = (site.type === 'Polygon' ? [site.coordinates] : site.coordinates) as XY[][][];
  const inside = (p: XY) => polygons.some(poly => insideRing(p, poly[0]) && !poly.slice(1).some(hole => insideRing(p, hole)));
  const result: XY[][] = [];
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i-1], b = coords[i], dx = b[0]-a[0], dy = b[1]-a[1];
    const cuts = [0, 1];
    for (const ring of polygons.flat()) for (let j = 1; j < ring.length; j++) {
      const c = ring[j-1], d = ring[j], ex = d[0]-c[0], ey = d[1]-c[1];
      const denominator = dx*ey-dy*ex;
      if (Math.abs(denominator) < 1e-12) continue;
      const t = ((c[0]-a[0])*ey-(c[1]-a[1])*ex)/denominator;
      const u = ((c[0]-a[0])*dy-(c[1]-a[1])*dx)/denominator;
      if (t > 0 && t < 1 && u >= 0 && u <= 1) cuts.push(t);
    }
    const ordered = [...new Set(cuts)].sort((x,y) => x-y);
    const at = (t: number) => [a[0]+t*dx,a[1]+t*dy];
    for (let j = 1; j < ordered.length; j++) if (!inside(at((ordered[j-1]+ordered[j])/2))) result.push([at(ordered[j-1]), at(ordered[j])]);
  }
  return result;
}

/** Triangles for a road surface in projected metres (schematic butt joins). */
export function roadRibbonVertices(coords: number[][], widthM: number, z = 0.4): number[] {
  const vertices: number[] = [];
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i-1], b = coords[i], dx = b[0]-a[0], dy = b[1]-a[1], length = Math.hypot(dx,dy);
    if (!length || !Number.isFinite(widthM) || widthM <= 0) continue;
    const nx = -dy/length*widthM/2, ny = dx/length*widthM/2;
    const p = [a[0]+nx,a[1]+ny,z], q = [a[0]-nx,a[1]-ny,z], r = [b[0]+nx,b[1]+ny,z], s = [b[0]-nx,b[1]-ny,z];
    vertices.push(...p,...q,...r,...r,...q,...s);
  }
  return vertices;
}
