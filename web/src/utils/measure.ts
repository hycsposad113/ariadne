/**
 * Pure measurements in the authoritative EPSG:28992 coordinate space.
 *
 * The coordinates are RD New easting/northing values in metres. No viewport,
 * canvas, zoom, pan, or screen-pixel value is accepted by these functions.
 */

export type MetricPoint2D = readonly [easting: number, northing: number];
export type MetricPoint3D = readonly [easting: number, northing: number, elevation: number];

export interface DistanceMeasurement {
  value: number;
  unit: 'm';
}

export interface AreaMeasurement {
  value: number;
  unit: 'm²';
}

export interface PolygonMeasurement {
  area: AreaMeasurement;
  perimeter: DistanceMeasurement;
}

/**
 * The signed vertical delta is end elevation minus start elevation. The
 * absolute value is supplied alongside it for callers that need height only.
 */
export interface VerticalDeltaMeasurement {
  signed: number;
  absolute: number;
  unit: 'm';
}

export interface ThreeDimensionalMeasurement {
  horizontalDistance: DistanceMeasurement;
  verticalDelta: VerticalDeltaMeasurement;
  slantDistance: DistanceMeasurement;
}

const POINT_TOLERANCE_METRES = 1e-9;

export function measureDistance2D(start: MetricPoint2D, end: MetricPoint2D): DistanceMeasurement {
  assertFinitePoint(start, 2, 'start');
  assertFinitePoint(end, 2, 'end');

  return distanceMeasurement(Math.hypot(end[0] - start[0], end[1] - start[1]));
}

export function measurePolylineLength(points: readonly MetricPoint2D[]): DistanceMeasurement {
  if (points.length < 2) {
    throw new RangeError('A polyline requires at least two points.');
  }
  points.forEach((point, index) => assertFinitePoint(point, 2, `point ${index}`));

  let length = 0;
  for (let index = 1; index < points.length; index += 1) {
    length += Math.hypot(
      points[index][0] - points[index - 1][0],
      points[index][1] - points[index - 1][1],
    );
  }

  return distanceMeasurement(length);
}

export function measurePolygon(points: readonly MetricPoint2D[]): PolygonMeasurement {
  const ring = normalizePolygon(points);
  const area = polygonArea(ring);
  let perimeter = 0;

  for (let index = 0; index < ring.length; index += 1) {
    const current = ring[index];
    const next = ring[(index + 1) % ring.length];
    perimeter += Math.hypot(next[0] - current[0], next[1] - current[1]);
  }

  return {
    area: { value: area, unit: 'm²' },
    perimeter: distanceMeasurement(perimeter),
  };
}

export function measurePolygonArea(points: readonly MetricPoint2D[]): AreaMeasurement {
  return measurePolygon(points).area;
}

export function measurePolygonPerimeter(points: readonly MetricPoint2D[]): DistanceMeasurement {
  return measurePolygon(points).perimeter;
}

export function measure3DPoints(start: MetricPoint3D, end: MetricPoint3D): ThreeDimensionalMeasurement {
  assertFinitePoint(start, 3, 'start');
  assertFinitePoint(end, 3, 'end');

  const horizontalDistance = Math.hypot(end[0] - start[0], end[1] - start[1]);
  const signedVerticalDelta = end[2] - start[2];

  return {
    horizontalDistance: distanceMeasurement(horizontalDistance),
    verticalDelta: {
      signed: signedVerticalDelta,
      absolute: Math.abs(signedVerticalDelta),
      unit: 'm',
    },
    slantDistance: distanceMeasurement(Math.hypot(horizontalDistance, signedVerticalDelta)),
  };
}

function distanceMeasurement(value: number): DistanceMeasurement {
  return { value, unit: 'm' };
}

function assertFinitePoint(
  point: readonly number[],
  dimension: 2 | 3,
  label: string,
): void {
  if (!Array.isArray(point)
      || point.length !== dimension
      || point.some((coordinate) => !Number.isFinite(coordinate))) {
    throw new TypeError(`${label} coordinates must contain ${dimension} finite numbers.`);
  }
}

function normalizePolygon(points: readonly MetricPoint2D[]): MetricPoint2D[] {
  if (points.length < 3) {
    throw new RangeError('A polygon requires at least three points.');
  }
  points.forEach((point, index) => assertFinitePoint(point, 2, `polygon point ${index}`));

  const ring = [...points];
  if (samePoint(ring[0], ring[ring.length - 1])) {
    ring.pop();
  }
  if (ring.length < 3) {
    throw new RangeError('A polygon requires at least three distinct points.');
  }

  for (let index = 0; index < ring.length; index += 1) {
    if (samePoint(ring[index], ring[(index + 1) % ring.length])) {
      throw new RangeError('A polygon cannot contain duplicate consecutive points.');
    }
  }

  if (hasNonAdjacentIntersection(ring)) {
    throw new RangeError('A polygon must be a simple, non-self-intersecting ring.');
  }

  const area = polygonArea(ring);
  if (area <= polygonAreaTolerance(ring)) {
    throw new RangeError('A polygon must enclose a positive area.');
  }
  if (hasImmediateBacktrack(ring)) {
    throw new RangeError('A polygon must be a simple, non-self-intersecting ring.');
  }

  return ring;
}

function polygonArea(ring: readonly MetricPoint2D[]): number {
  const origin = ring[0];
  let twiceArea = 0;

  for (let index = 0; index < ring.length; index += 1) {
    const current = ring[index];
    const next = ring[(index + 1) % ring.length];
    twiceArea += (current[0] - origin[0]) * (next[1] - origin[1])
      - (next[0] - origin[0]) * (current[1] - origin[1]);
  }

  return Math.abs(twiceArea) / 2;
}

function polygonAreaTolerance(ring: readonly MetricPoint2D[]): number {
  const eastings = ring.map(([easting]) => easting);
  const northings = ring.map(([, northing]) => northing);
  const extent = Math.max(
    1,
    Math.max(...eastings) - Math.min(...eastings),
    Math.max(...northings) - Math.min(...northings),
  );
  return Number.EPSILON * extent * extent * ring.length * 16;
}

function hasImmediateBacktrack(ring: readonly MetricPoint2D[]): boolean {
  for (let index = 0; index < ring.length; index += 1) {
    const previous = ring[(index + ring.length - 1) % ring.length];
    const current = ring[index];
    const next = ring[(index + 1) % ring.length];
    if (orientation(previous, current, next) === 0) {
      const incomingX = previous[0] - current[0];
      const incomingY = previous[1] - current[1];
      const outgoingX = next[0] - current[0];
      const outgoingY = next[1] - current[1];
      if (incomingX * outgoingX + incomingY * outgoingY > 0) return true;
    }
  }
  return false;
}

function hasNonAdjacentIntersection(ring: readonly MetricPoint2D[]): boolean {
  const segmentCount = ring.length;
  for (let first = 0; first < segmentCount; first += 1) {
    const firstStart = ring[first];
    const firstEnd = ring[(first + 1) % segmentCount];
    for (let second = first + 1; second < segmentCount; second += 1) {
      const adjacent = second === first + 1 || (first === 0 && second === segmentCount - 1);
      if (adjacent) continue;

      const secondStart = ring[second];
      const secondEnd = ring[(second + 1) % segmentCount];
      if (segmentsIntersect(firstStart, firstEnd, secondStart, secondEnd)) return true;
    }
  }
  return false;
}

function orientation(a: MetricPoint2D, b: MetricPoint2D, c: MetricPoint2D): -1 | 0 | 1 {
  const abX = b[0] - a[0];
  const abY = b[1] - a[1];
  const acX = c[0] - a[0];
  const acY = c[1] - a[1];
  const cross = abX * acY - abY * acX;
  const tolerance = Number.EPSILON * Math.max(1, Math.abs(abX * acY), Math.abs(abY * acX)) * 32;
  if (Math.abs(cross) <= tolerance) return 0;
  return cross > 0 ? 1 : -1;
}

function segmentsIntersect(
  firstStart: MetricPoint2D,
  firstEnd: MetricPoint2D,
  secondStart: MetricPoint2D,
  secondEnd: MetricPoint2D,
): boolean {
  const firstOrientationStart = orientation(firstStart, firstEnd, secondStart);
  const firstOrientationEnd = orientation(firstStart, firstEnd, secondEnd);
  const secondOrientationStart = orientation(secondStart, secondEnd, firstStart);
  const secondOrientationEnd = orientation(secondStart, secondEnd, firstEnd);

  if (firstOrientationStart * firstOrientationEnd < 0
      && secondOrientationStart * secondOrientationEnd < 0) {
    return true;
  }

  return (firstOrientationStart === 0 && pointOnSegment(secondStart, firstStart, firstEnd))
    || (firstOrientationEnd === 0 && pointOnSegment(secondEnd, firstStart, firstEnd))
    || (secondOrientationStart === 0 && pointOnSegment(firstStart, secondStart, secondEnd))
    || (secondOrientationEnd === 0 && pointOnSegment(firstEnd, secondStart, secondEnd));
}

function pointOnSegment(
  point: MetricPoint2D,
  start: MetricPoint2D,
  end: MetricPoint2D,
): boolean {
  return point[0] >= Math.min(start[0], end[0]) - POINT_TOLERANCE_METRES
    && point[0] <= Math.max(start[0], end[0]) + POINT_TOLERANCE_METRES
    && point[1] >= Math.min(start[1], end[1]) - POINT_TOLERANCE_METRES
    && point[1] <= Math.max(start[1], end[1]) + POINT_TOLERANCE_METRES;
}

function samePoint(first: MetricPoint2D, second: MetricPoint2D): boolean {
  return first[0] === second[0] && first[1] === second[1];
}
