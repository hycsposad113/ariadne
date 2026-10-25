import { expect, it } from 'vitest';
import * as THREE from 'three';
import { fabricCameraFit } from './fabricCamera';
it('projects the RD site into a finite visible camera frame in wide and split panes', () => {
 const site = {coordinates:[[[88610,435507],[89558,435507],[89558,436222],[88610,436222],[88610,435507]]]};
 for (const aspect of [1156/680, 578/680]) {
  const fit=fabricCameraFit(site,aspect)!;
  const camera=new THREE.PerspectiveCamera(45,aspect,1,10000);
  const phi=Math.PI/3.5; camera.up.set(0,0,1);
  camera.position.copy(fit.target).add(new THREE.Vector3(0,-fit.radius*Math.sin(phi),fit.radius*Math.cos(phi)));
  camera.lookAt(fit.target); camera.updateMatrixWorld();
  expect(camera.position.toArray().every(Number.isFinite)).toBe(true);
  const projected: THREE.Vector3[] = [];
  for(const ring of site.coordinates) for(const [x,y] of ring) {
   const p=new THREE.Vector3(x-89100,y-435900,0).project(camera);
   projected.push(p);
   expect(Math.abs(p.x)).toBeLessThan(1);expect(Math.abs(p.y)).toBeLessThan(1);expect(p.z).toBeLessThan(1);
  }
  const width = (Math.max(...projected.map(p=>p.x))-Math.min(...projected.map(p=>p.x)))/2;
  const height = (Math.max(...projected.map(p=>p.y))-Math.min(...projected.map(p=>p.y)))/2;
  expect(Math.max(width,height)).toBeGreaterThan(.6);
 }
 expect(fabricCameraFit(site,NaN)).toBeNull();expect(fabricCameraFit(site,0)).toBeNull();
});
