import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { useI18n } from '../i18n';
import type { FaceSelection } from './FaceEditControls';
import { faceLabel } from './FaceEditControls';
export type SelectableFace = FaceSelection & { triangles: [number, number, number][] };
/** Triangles must come from the geometry adapter, never derive authority from a mesh index. */
export function FaceSelection3D({ faces, selectedId, onSelect }: { faces: SelectableFace[]; selectedId: string | null; onSelect: (face: FaceSelection) => void }) {
  const ref = useRef<HTMLDivElement>(null); const { language } = useI18n(); const [unavailable, setUnavailable] = useState(false);
  const label = language === 'zh-TW' ? '3D 選面' : '3D semantic face selection';
  useEffect(() => {
    const container = ref.current; if (!container) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); } catch { setUnavailable(true); return; }
    setUnavailable(false); const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(45, 1.5, 0.01, 100000);
    renderer.setSize(600, 400); renderer.domElement.setAttribute('aria-label', label); container.appendChild(renderer.domElement);
    const meshes: THREE.Mesh[] = [];
    for (const face of faces) {
      if (!face.triangles.length || face.triangles.length % 3 || !face.triangles.every(p => p.length === 3 && p.every(Number.isFinite))) continue;
      const geometry = new THREE.BufferGeometry(); geometry.setAttribute('position', new THREE.Float32BufferAttribute(face.triangles.flat(), 3)); geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: face.id === selectedId ? '#49c9b0' : '#55758d', side: THREE.DoubleSide }));
      mesh.userData.face = face; scene.add(mesh); meshes.push(mesh);
    }
    const box = new THREE.Box3().setFromObject(scene); const center = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
    const span = box.isEmpty() ? 10 : Math.max(...box.getSize(new THREE.Vector3()).toArray(), 1);
    camera.up.set(0, 0, 1); camera.position.copy(center).add(new THREE.Vector3(span, -span, span)); camera.lookAt(center); renderer.render(scene, camera);
    const ray = new THREE.Raycaster();
    function pick(event: PointerEvent) { const rect = renderer.domElement.getBoundingClientRect(); if (!rect.width || !rect.height) return;
      ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1, -(event.clientY-rect.top)/rect.height*2+1), camera);
      const hit = ray.intersectObjects(meshes)[0]; if (hit) { const face = hit.object.userData.face as SelectableFace; onSelect({ id: face.id, floorId: face.floorId, kind: face.kind, parentRevision: face.parentRevision }); }
    }
    renderer.domElement.addEventListener('pointerdown', pick);
    return () => { renderer.domElement.removeEventListener('pointerdown', pick); for (const mesh of meshes) { mesh.geometry.dispose(); (mesh.material as THREE.Material).dispose(); } renderer.dispose(); renderer.domElement.remove(); };
  }, [faces, selectedId, onSelect, label]);
  return <section aria-label={label}><div ref={ref} />{unavailable && <p role="status">{language === 'zh-TW' ? 'WebGL 無法使用；請用下方面清單選取。' : 'WebGL unavailable; select from the face list below.'}</p>}
    <div className="face-selection-list" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 160, overflowY: 'auto' }}>{faces.map(face => <button key={face.id} type="button" data-face-id={face.id} title={face.id} aria-pressed={face.id === selectedId} onClick={() => onSelect({ id: face.id, floorId: face.floorId, parentRevision: face.parentRevision, kind: face.kind })}>{faceLabel(face.id, language)}</button>)}</div>
  </section>;
}
