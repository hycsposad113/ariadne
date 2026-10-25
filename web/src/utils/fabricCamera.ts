import * as THREE from 'three';
import { epsg28992ToLocalMetric } from './geoTransform';

/** Fit only the projected site, independently of fetched context geometry. */
export function fabricCameraFit(geometry: { coordinates: unknown }, aspect: number, fov = 45) {
  const points: THREE.Vector3[] = [];
  const collect = (value: unknown): void => {
    if (!Array.isArray(value)) return;
    if (typeof value[0] === 'number' && typeof value[1] === 'number') {
      if (Number.isFinite(value[0]) && Number.isFinite(value[1])) {
        const [x, y] = epsg28992ToLocalMetric(value[0], value[1]);
        points.push(new THREE.Vector3(x, y, 0));
      }
    } else value.forEach(collect);
  };
  collect(geometry.coordinates);
  if (!points.length || !Number.isFinite(aspect) || aspect <= 0) return null;
  const bounds = new THREE.Box3().setFromPoints(points);
  const target = bounds.getCenter(new THREE.Vector3());
  const camera = new THREE.PerspectiveCamera(fov, aspect, 1, 10000);
  camera.up.set(0, 0, 1);
  const phi = Math.PI / 3.5;
  // Fit actual projected vertices rather than a conservative bounding sphere.
  // 18% margin leaves headroom for the proposal's <=20 m extrusions.
  const fits = (radius: number) => {
    camera.position.copy(target).add(new THREE.Vector3(0, -radius * Math.sin(phi), radius * Math.cos(phi)));
    camera.lookAt(target); camera.updateMatrixWorld();
    return points.every(point => {
      const p = point.clone().project(camera);
      return Math.abs(p.x) <= .82 && Math.abs(p.y) <= .82 && p.z > -1 && p.z < 1;
    });
  };
  let low = 1, high = 9000;
  if (!fits(high)) return null;
  for (let i = 0; i < 48; i++) {
    const mid = (low + high) / 2;
    if (fits(mid)) high = mid; else low = mid;
  }
  return { target, radius: high, bounds };

}
