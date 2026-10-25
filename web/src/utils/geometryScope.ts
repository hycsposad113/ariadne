export type Position2D = [number, number];

export type PolygonalGeometry = {
  type: 'Polygon' | 'MultiPolygon';
  coordinates: unknown;
};

export type PolygonPreparation =
  | { ok: true; closedRing: Position2D[]; areaM2: number }
  | {
      ok: false;
      reason: 'STUDY_AREA_UNAVAILABLE' | 'INVALID_STUDY_AREA_GEOMETRY' | 'INVALID_POLYGON' | 'OUTSIDE_STUDY_AREA';
    };

type RingLocation = 'inside' | 'boundary' | 'outside';
type PolygonComponent = Position2D[][];

const MACHINE_EPSILON = Number.EPSILON * 32;

/**
 * Prepare a drawn ring and require it to be covered by one connected polygon
 * component of the server-provided StudyArea. This is an early UI guard only;
 * the API repeats the authoritative Shapely `covers` check before persistence.
 */
export function preparePolygonWithinStudyArea(
  candidateCoordinates: unknown,
  studyAreaGeometry: unknown,
): PolygonPreparation {
  if (!studyAreaGeometry || typeof studyAreaGeometry !== 'object') {
    return { ok: false, reason: 'STUDY_AREA_UNAVAILABLE' };
  }

  const geometry = studyAreaGeometry as Partial<PolygonalGeometry>;
  const components = parsePolygonalGeometry(geometry);
  if (!components) return { ok: false, reason: 'INVALID_STUDY_AREA_GEOMETRY' };

  const candidate = normalizeRing(candidateCoordinates, false);
  if (!candidate) return { ok: false, reason: 'INVALID_POLYGON' };

  for (const component of components) {
    if (coversCandidate(component, candidate.ring)) {
      return { ok: true, closedRing: candidate.ring, areaM2: candidate.area };
    }
  }

  return { ok: false, reason: 'OUTSIDE_STUDY_AREA' };
}

export function measurePolygonalAreaM2(studyAreaGeometry: unknown): number | null {
  if (!studyAreaGeometry || typeof studyAreaGeometry !== 'object') return null;
  const components = parsePolygonalGeometry(studyAreaGeometry as Partial<PolygonalGeometry>);
  if (!components) return null;
  const area = components.reduce((total, component) => {
    const exterior = ringArea(component[0]);
    const holes = component.slice(1).reduce((holeTotal, hole) => holeTotal + ringArea(hole), 0);
    return total + Math.max(0, exterior - holes);
  }, 0);
  return Number.isFinite(area) && area > 0 ? area : null;
}

function parsePolygonalGeometry(geometry: Partial<PolygonalGeometry>): PolygonComponent[] | null {
  if (geometry.type === 'Polygon') {
    const component = parsePolygonCoordinates(geometry.coordinates);
    return component ? [component] : null;
  }
  if (geometry.type !== 'MultiPolygon' || !Array.isArray(geometry.coordinates) || geometry.coordinates.length === 0) {
    return null;
  }

  const components = geometry.coordinates.map(parsePolygonCoordinates);
  return components.every((component): component is PolygonComponent => component !== null) ? components : null;
}

function parsePolygonCoordinates(value: unknown): PolygonComponent | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const rings = value.map((ring) => normalizeRing(ring, true));
  if (rings.some((ring) => ring === null)) return null;
  const component = rings.map((ring) => (ring as NonNullable<typeof ring>).ring);

  // Every hole must start within the exterior ring and must not overlap it.
  for (const hole of component.slice(1)) {
    if (locateInRing(hole[0], component[0]) === 'outside') return null;
    if (ringsIntersect(component[0], hole)) return null;
  }
  return component;
}

function normalizeRing(value: unknown, requireClosed: boolean): { ring: Position2D[]; area: number } | null {
  if (!Array.isArray(value) || value.length < 3) return null;
  const positions: Position2D[] = [];
  for (const entry of value) {
    if (!Array.isArray(entry) || entry.length < 2) return null;
    const x: unknown = entry[0];
    const y: unknown = entry[1];
    if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) return null;
    positions.push([x, y]);
  }

  if (requireClosed && !samePoint(positions[0], positions[positions.length - 1])) return null;
  if (!requireClosed && !samePoint(positions[0], positions[positions.length - 1])) {
    positions.push([...positions[0]]);
  }
  if (positions.length < 4 || positions.some((point, index) =>
    index < positions.length - 1 && samePoint(point, positions[index + 1]),
  )) return null;

  const area = ringArea(positions);
  if (!Number.isFinite(area) || area <= areaTolerance(positions)) return null;
  if (ringSelfIntersects(positions)) return null;
  return { ring: positions, area };
}

function ringArea(ring: Position2D[]): number {
  const origin = ring[0];
  let twiceArea = 0;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const current = ring[index];
    const next = ring[index + 1];
    twiceArea += (current[0] - origin[0]) * (next[1] - origin[1])
      - (next[0] - origin[0]) * (current[1] - origin[1]);
  }
  return Math.abs(twiceArea) / 2;
}

function areaTolerance(ring: Position2D[]): number {
  const xs = ring.map(([x]) => x);
  const ys = ring.map(([, y]) => y);
  const extent = Math.max(1, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  return Number.EPSILON * extent * extent * ring.length * 8;
}

function ringSelfIntersects(ring: Position2D[]): boolean {
  const segmentCount = ring.length - 1;
  for (let first = 0; first < segmentCount; first += 1) {
    const a = ring[first];
    const b = ring[first + 1];
    for (let second = first + 1; second < segmentCount; second += 1) {
      const adjacent = second === first + 1 || (first === 0 && second === segmentCount - 1);
      if (!adjacent && segmentsIntersect(a, b, ring[second], ring[second + 1])) return true;
    }
    if (sameLine(a, b, ring[(first + 2) % segmentCount])) {
      const incoming: Position2D = [b[0] - a[0], b[1] - a[1]];
      const next = ring[(first + 2) % segmentCount];
      const outgoing: Position2D = [next[0] - b[0], next[1] - b[1]];
      if (incoming[0] * outgoing[0] + incoming[1] * outgoing[1] < 0) return true;
    }
  }
  return false;
}

function sameLine(a: Position2D, b: Position2D, c: Position2D): boolean {
  return orientationSign(a, b, c) === 0;
}

function ringsIntersect(first: Position2D[], second: Position2D[]): boolean {
  for (let i = 0; i < first.length - 1; i += 1) {
    for (let j = 0; j < second.length - 1; j += 1) {
      if (segmentsIntersect(first[i], first[i + 1], second[j], second[j + 1])) return true;
    }
  }
  return false;
}

function orientationSign(a: Position2D, b: Position2D, c: Position2D): number {
  const abx = b[0] - a[0];
  const aby = b[1] - a[1];
  const acx = c[0] - a[0];
  const acy = c[1] - a[1];
  const cross = abx * acy - aby * acx;
  const tolerance = MACHINE_EPSILON * Math.max(1, Math.abs(abx * acy), Math.abs(aby * acx));
  return Math.abs(cross) <= tolerance ? 0 : cross > 0 ? 1 : -1;
}

function pointOnSegment(point: Position2D, start: Position2D, end: Position2D): boolean {
  if (orientationSign(start, end, point) !== 0) return false;
  const tolerance = MACHINE_EPSILON * Math.max(1, ...point.map(Math.abs), ...start.map(Math.abs), ...end.map(Math.abs));
  return point[0] >= Math.min(start[0], end[0]) - tolerance
    && point[0] <= Math.max(start[0], end[0]) + tolerance
    && point[1] >= Math.min(start[1], end[1]) - tolerance
    && point[1] <= Math.max(start[1], end[1]) + tolerance;
}

function segmentsIntersect(a: Position2D, b: Position2D, c: Position2D, d: Position2D): boolean {
  const o1 = orientationSign(a, b, c);
  const o2 = orientationSign(a, b, d);
  const o3 = orientationSign(c, d, a);
  const o4 = orientationSign(c, d, b);
  if (o1 * o2 < 0 && o3 * o4 < 0) return true;
  return (o1 === 0 && pointOnSegment(c, a, b))
    || (o2 === 0 && pointOnSegment(d, a, b))
    || (o3 === 0 && pointOnSegment(a, c, d))
    || (o4 === 0 && pointOnSegment(b, c, d));
}

function locateInRing(point: Position2D, ring: Position2D[]): RingLocation {
  let inside = false;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const start = ring[index];
    const end = ring[index + 1];
    if (pointOnSegment(point, start, end)) return 'boundary';
    const crosses = (start[1] > point[1]) !== (end[1] > point[1]);
    if (crosses) {
      const crossingX = ((end[0] - start[0]) * (point[1] - start[1])) / (end[1] - start[1]) + start[0];
      if (point[0] < crossingX) inside = !inside;
    }
  }
  return inside ? 'inside' : 'outside';
}

function locateInPolygon(point: Position2D, component: PolygonComponent): RingLocation {
  const outerLocation = locateInRing(point, component[0]);
  if (outerLocation === 'outside') return 'outside';
  for (const hole of component.slice(1)) {
    if (locateInRing(point, hole) === 'inside') return 'outside';
  }
  return outerLocation;
}

function coversCandidate(component: PolygonComponent, candidate: Position2D[]): boolean {
  if (candidate.slice(0, -1).some((point) => locateInPolygon(point, component) === 'outside')) return false;

  const boundaryRings = component;
  for (let index = 0; index < candidate.length - 1; index += 1) {
    const start = candidate[index];
    const end = candidate[index + 1];
    const parameters = [0, 1];
    for (const boundary of boundaryRings) {
      for (let edge = 0; edge < boundary.length - 1; edge += 1) {
        parameters.push(...segmentIntersectionParameters(start, end, boundary[edge], boundary[edge + 1]));
      }
    }
    const ordered = uniqueSorted(parameters);
    for (let part = 0; part < ordered.length - 1; part += 1) {
      if (ordered[part + 1] - ordered[part] <= MACHINE_EPSILON) continue;
      const t = (ordered[part] + ordered[part + 1]) / 2;
      const sample: Position2D = [start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t];
      if (locateInPolygon(sample, component) === 'outside') return false;
    }
  }

  // A candidate can surround a StudyArea hole without crossing its boundary.
  for (const hole of component.slice(1)) {
    if (hole.slice(0, -1).some((point) => locateInRing(point, candidate) === 'inside')) return false;
  }
  return true;
}

function segmentIntersectionParameters(
  a: Position2D,
  b: Position2D,
  c: Position2D,
  d: Position2D,
): number[] {
  const rx = b[0] - a[0];
  const ry = b[1] - a[1];
  const sx = d[0] - c[0];
  const sy = d[1] - c[1];
  const denominator = rx * sy - ry * sx;
  const qx = c[0] - a[0];
  const qy = c[1] - a[1];
  const scale = Math.max(1, Math.abs(rx * sy), Math.abs(ry * sx));
  const tolerance = MACHINE_EPSILON * scale;

  if (Math.abs(denominator) > tolerance) {
    const t = (qx * sy - qy * sx) / denominator;
    const u = (qx * ry - qy * rx) / denominator;
    const parameterTolerance = MACHINE_EPSILON * 8;
    return t >= -parameterTolerance && t <= 1 + parameterTolerance
      && u >= -parameterTolerance && u <= 1 + parameterTolerance
      ? [clamp01(t)]
      : [];
  }

  if (Math.abs(qx * ry - qy * rx) > tolerance) return [];
  const lengthSquared = rx * rx + ry * ry;
  if (lengthSquared <= tolerance) return [];
  const t0 = (qx * rx + qy * ry) / lengthSquared;
  const t1 = t0 + (sx * rx + sy * ry) / lengthSquared;
  const lower = Math.max(0, Math.min(t0, t1));
  const upper = Math.min(1, Math.max(t0, t1));
  return upper < lower - MACHINE_EPSILON ? [] : [clamp01(lower), clamp01(upper)];
}

function uniqueSorted(values: number[]): number[] {
  return values.sort((a, b) => a - b).filter((value, index, ordered) =>
    index === 0 || Math.abs(value - ordered[index - 1]) > MACHINE_EPSILON * 8,
  );
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function samePoint(a: Position2D, b: Position2D): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

/** Hide whole context lines touching the site; proposal syntax is handled separately. */
export function lineTouchesStudyArea(coordinates: number[][], geometry: unknown): boolean {
  if (!geometry || typeof geometry !== 'object') return false;
  const components = parsePolygonalGeometry(geometry as Partial<PolygonalGeometry>);
  if (!components) return false;
  const points = coordinates.filter(p => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])) as Position2D[];
  return components.some(component => points.some(p => locateInPolygon(p, component) !== 'outside')
    || points.slice(1).some((end, i) => component.some(ring => ring.slice(1).some((b, j) => segmentsIntersect(points[i], end, ring[j], b)))));
}
