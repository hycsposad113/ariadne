import * as THREE from 'three';

export type RoadPoint = [number, number];
export type RoadLinePart = RoadPoint[];

/**
 * Return the renderable LineString parts for a source-backed road geometry.
 * Invalid coordinates and unsupported geometry types are rejected as a whole
 * so rendering and picking use the same source geometry contract.
 */
export function normalizeRoadLineParts(geometry: unknown): RoadLinePart[] {
  if (!geometry || typeof geometry !== 'object') return [];
  const candidate = geometry as { type?: unknown; coordinates?: unknown };
  const { type, coordinates } = candidate;

  const normalizeLine = (value: unknown): RoadLinePart | null => {
    if (!Array.isArray(value) || value.length < 2) return null;
    const points: RoadPoint[] = [];
    for (const point of value) {
      if (!Array.isArray(point) || point.length < 2) return null;
      const x = point[0];
      const y = point[1];
      if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) return null;
      points.push([x, y]);
    }
    return points;
  };

  if (type === 'LineString') {
    const line = normalizeLine(coordinates);
    return line ? [line] : [];
  }
  if (type !== 'MultiLineString' || !Array.isArray(coordinates)) return [];
  const lines = coordinates.map((line) => {
    const normalized = normalizeLine(line);
    return normalized;
  });
  return lines.every((line): line is RoadLinePart => line !== null) ? lines : [];
}

/**
 * Convert a desired screen-space pick radius into Three.js world units at the
 * current camera distance. This keeps picking stable when the viewport zooms.
 */
export function calculateRoadPickThreshold(
  camera: THREE.PerspectiveCamera,
  viewportHeight: number,
  pixelRadius = 4,
): number {
  const safeHeight = Math.max(1, viewportHeight);
  const distance = Math.max(camera.position.length(), camera.near);
  const verticalWorldSpan = 2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  return (verticalWorldSpan / safeHeight) * Math.max(0, pixelRadius);
}
