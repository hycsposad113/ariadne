import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { calculateRoadPickThreshold, normalizeRoadLineParts } from './roadPicking';

describe('road picking geometry', () => {
  it('normalizes LineString and MultiLineString into renderable parts', () => {
    expect(normalizeRoadLineParts({
      type: 'LineString',
      coordinates: [[1, 2], [3, 4]],
    })).toEqual([[[1, 2], [3, 4]]]);
    expect(normalizeRoadLineParts({
      type: 'MultiLineString',
      coordinates: [
        [[1, 2], [3, 4]],
        [[5, 6], [7, 8], [9, 10]],
      ],
    })).toEqual([
      [[1, 2], [3, 4]],
      [[5, 6], [7, 8], [9, 10]],
    ]);
  });

  it('rejects malformed or unsupported road geometry', () => {
    expect(normalizeRoadLineParts({ type: 'Polygon', coordinates: [] })).toEqual([]);
    expect(normalizeRoadLineParts({
      type: 'MultiLineString',
      coordinates: [[[1, 2]], [[3, Number.NaN], [4, 5]]],
    })).toEqual([]);
  });

  it('scales the world tolerance with camera distance and viewport height', () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 1, 10_000);
    camera.position.set(0, -600, 450);
    const baseline = calculateRoadPickThreshold(camera, 800);
    camera.position.multiplyScalar(0.5);
    const zoomed = calculateRoadPickThreshold(camera, 800);
    const tallerViewport = calculateRoadPickThreshold(camera, 1600);

    expect(zoomed).toBeCloseTo(baseline * 0.5, 8);
    expect(tallerViewport).toBeCloseTo(zoomed * 0.5, 8);
  });
});
