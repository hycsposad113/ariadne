import type { Building, Segment } from '../types';

export interface SelectionExtent {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface FeatureSelection {
  buildingIds: string[];
  roadIds: string[];
}

export function selectFeaturesIntersectingExtent(
  buildings: Building[],
  roads: Segment[],
  extent: SelectionExtent,
): FeatureSelection {
  if (
    ![extent.minX, extent.minY, extent.maxX, extent.maxY].every(Number.isFinite)
    || extent.minX > extent.maxX
    || extent.minY > extent.maxY
  ) {
    throw new RangeError('Box selection requires a finite ordered extent.');
  }

  return {
    buildingIds: buildings
      .filter(building => geometryIntersectsExtent(building.geometry, extent))
      .map(building => building.id),
    roadIds: roads
      .filter(road => geometryIntersectsExtent(road.geometry, extent))
      .map(road => road.id),
  };
}

function geometryIntersectsExtent(geometry: any, extent: SelectionExtent): boolean {
  if (!geometry || !Array.isArray(geometry.coordinates)) return false;
  if (geometry.type === 'Polygon') return polygonIntersectsExtent(geometry.coordinates, extent);
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((polygon: number[][][]) => polygonIntersectsExtent(polygon, extent));
  }
  if (geometry.type === 'LineString') return lineIntersectsExtent(geometry.coordinates, extent);
  if (geometry.type === 'MultiLineString') {
    return geometry.coordinates.some((line: number[][]) => lineIntersectsExtent(line, extent));
  }
  return false;
}

function polygonIntersectsExtent(rings: number[][][], extent: SelectionExtent): boolean {
  const [outerRing, ...holes] = rings;
  if (!outerRing || outerRing.length < 3) return false;

  for (const ring of rings) {
    if (ring.some(point => point.length >= 2 && pointInExtent(point, extent))) return true;
    for (let index = 0; index < ring.length; index += 1) {
      const start = ring[index];
      const end = ring[(index + 1) % ring.length];
      if (start.length >= 2 && end.length >= 2 && segmentIntersectsExtent(start, end, extent)) return true;
    }
  }

  const corners = [
    [extent.minX, extent.minY],
    [extent.minX, extent.maxY],
    [extent.maxX, extent.minY],
    [extent.maxX, extent.maxY],
  ];
  return corners.some(([x, y]) => pointInPolygonWithHoles([x, y], outerRing, holes));
}

function lineIntersectsExtent(points: number[][], extent: SelectionExtent): boolean {
  if (points.length < 2) return points.some(point => point.length >= 2 && pointInExtent(point, extent));
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (start.length >= 2 && end.length >= 2 && segmentIntersectsExtent(start, end, extent)) return true;
  }
  return false;
}

function pointInPolygonWithHoles(point: number[], outerRing: number[][], holes: number[][][]): boolean {
  if (!pointInRing(point, outerRing)) return false;
  for (const hole of holes) {
    if (pointOnRing(point, hole)) return true;
    if (pointInRing(point, hole)) return false;
  }
  return true;
}

function pointInRing(point: number[], ring: number[][]): boolean {
  if (pointOnRing(point, ring)) return true;
  let inside = false;
  for (let current = 0, previous = ring.length - 1; current < ring.length; previous = current++) {
    const [x1, y1] = ring[current];
    const [x2, y2] = ring[previous];
    if ((y1 > point[1]) !== (y2 > point[1]) && point[0] < ((x2 - x1) * (point[1] - y1)) / (y2 - y1) + x1) {
      inside = !inside;
    }
  }
  return inside;
}

function pointOnRing(point: number[], ring: number[][]): boolean {
  for (let index = 0; index < ring.length; index += 1) {
    if (pointOnSegment(point, ring[index], ring[(index + 1) % ring.length])) return true;
  }
  return false;
}

function pointInExtent(point: number[], extent: SelectionExtent): boolean {
  return point[0] >= extent.minX && point[0] <= extent.maxX && point[1] >= extent.minY && point[1] <= extent.maxY;
}

function segmentIntersectsExtent(start: number[], end: number[], extent: SelectionExtent): boolean {
  let lower = 0;
  let upper = 1;
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const p = [-dx, dx, -dy, dy];
  const q = [start[0] - extent.minX, extent.maxX - start[0], start[1] - extent.minY, extent.maxY - start[1]];

  for (let index = 0; index < p.length; index += 1) {
    if (p[index] === 0) {
      if (q[index] < 0) return false;
      continue;
    }
    const ratio = q[index] / p[index];
    if (p[index] < 0) lower = Math.max(lower, ratio);
    else upper = Math.min(upper, ratio);
    if (lower > upper) return false;
  }
  return true;
}

function pointOnSegment(point: number[], start: number[], end: number[]): boolean {
  const cross = (point[1] - start[1]) * (end[0] - start[0]) - (point[0] - start[0]) * (end[1] - start[1]);
  if (Math.abs(cross) > 1e-9) return false;
  return point[0] >= Math.min(start[0], end[0]) - 1e-9
    && point[0] <= Math.max(start[0], end[0]) + 1e-9
    && point[1] >= Math.min(start[1], end[1]) - 1e-9
    && point[1] <= Math.max(start[1], end[1]) + 1e-9;
}
