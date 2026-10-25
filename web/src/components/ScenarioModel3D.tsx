import { activeFacadeVertices } from '../utils/activeFacades';
import { proposalRoadMetadata, proposalRoadStyle, roadRibbonVertices } from '../utils/proposalRoads';
import { classifyContextValue, type SyntaxContextResponse } from '../utils/syntaxContext';
import { useT } from '../i18n';
import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { commandFromDrag, type EditableFloor, type MassingCommand } from '../utils/scenarioEdits';
import './ScenarioStudio.css';

type FloorGeometry = EditableFloor & {
  geometry: { type: string; coordinates: number[][][] | number[][][][] };
};
type EditableBuilding = {
  building_id: string;
  floors: FloorGeometry[];
  first_floor_height_m: number;
  standard_floor_height_m: number;
  geometry_hash?: string;
  active_frontage?: boolean;
  facade_segments?: unknown;
};

type DragStart = {
  buildingId: string;
  face: 'top' | 'side';
  edgeIndex: number;
  startY: number;
  floors: EditableFloor[];
  geometryHash: string;
};

function polygonRing(geometry: FloorGeometry['geometry']): number[][] | null {
  if (geometry.type !== 'Polygon') return null;
  const coordinates = geometry.coordinates as number[][][];
  return coordinates[0] ?? null;
}

function nearestEdgeIndex(x: number, y: number, ring: number[][]): number {
  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const first = ring[index];
    const second = ring[index + 1];
    if (!first || !second) continue;
    const dx = second[0] - first[0];
    const dy = second[1] - first[1];
    const lengthSquared = dx * dx + dy * dy;
    const ratio = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((x - first[0]) * dx + (y - first[1]) * dy) / lengthSquared));
    const distance = Math.hypot(x - (first[0] + ratio * dx), y - (first[1] + ratio * dy));
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  }
  return nearestIndex;
}

type RoadFeature = { id?: string; geometry: { type: string; coordinates: unknown }; properties: Record<string, unknown> };
const EMPTY_ROADS: RoadFeature[] = [];
export const ScenarioModel3D: React.FC<{
  buildings: EditableBuilding[];
  roadFeatures?: RoadFeature[];
  syntaxContext?: SyntaxContextResponse | null;
  selectedBuildingId: string;
  onSelectBuilding: (buildingId: string) => void;
  onPreview: (label: string | null) => void;
  onEdit: (buildingId: string, command: MassingCommand) => Promise<void>;
}> = ({ roadFeatures = EMPTY_ROADS, syntaxContext, buildings, selectedBuildingId, onSelectBuilding, onPreview, onEdit }) => {
  const t = useT();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragStart | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    setRenderError(null);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setRenderError(t("WebGL preview unavailable in this browser; switch to 2D."));
      return;
    }
    const width = Math.max(container.clientWidth, 360);
    const height = Math.max(container.clientHeight, 400);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#101826');
    const camera = new THREE.PerspectiveCamera(42, width / height, 1, 10000);
    camera.position.set(190, -220, 170);
    camera.up.set(0, 0, 1);
    camera.lookAt(0, 0, 18);
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.domElement.className = 'scenario-three-canvas';
    renderer.domElement.setAttribute('aria-label', t("Massing 3D preview and drag editor"));
    renderer.domElement.tabIndex = 0;
    container.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 1.2));
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.4);
    keyLight.position.set(-90, -120, 250);
    scene.add(keyLight);
    const grid = new THREE.GridHelper(220, 22, 0x36516c, 0x263649);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    const allCoordinates = [
      ...buildings.flatMap((building) => building.floors.flatMap((floor) => polygonRing(floor.geometry) ?? [])),
      ...roadFeatures.filter(f => f.geometry.type === 'LineString').flatMap(f => f.geometry.coordinates as number[][]),
    ];
    const minX = allCoordinates.length ? Math.min(...allCoordinates.map((point) => point[0])) : 0;
    const maxX = allCoordinates.length ? Math.max(...allCoordinates.map((point) => point[0])) : 1;
    const minY = allCoordinates.length ? Math.min(...allCoordinates.map((point) => point[1])) : 0;
    const maxY = allCoordinates.length ? Math.max(...allCoordinates.map((point) => point[1])) : 1;
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const masses: THREE.Mesh[] = [];
    const roadObjects: Array<THREE.Line | THREE.Mesh> = [];
    for (const feature of roadFeatures) {
      if (!['road', 'road_centerline', 'road_segment'].includes(String(feature.properties.role ?? feature.properties.feature_kind))) continue;
      if (feature.geometry.type !== 'LineString') continue;
      const road = proposalRoadMetadata(feature.properties, feature.id);
      const style = proposalRoadStyle(road);
      const coords = (feature.geometry.coordinates as number[][]).map(p => [p[0]-centerX,p[1]-centerY]);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(roadRibbonVertices(coords, road.width_m ?? 2),3));
      const mesh = new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({ color:style.color,side:THREE.DoubleSide }));
      mesh.name = `proposal-road:${feature.id ?? ''}`;
      scene.add(mesh); roadObjects.push(mesh);
    }
    for (const segment of syntaxContext?.segments ?? []) {
      const coords = segment.coordinates.map(p => new THREE.Vector3(p[0]-centerX,p[1]-centerY,1.0));
      const geometry = new THREE.BufferGeometry().setFromPoints(coords);
      const style = classifyContextValue(syntaxContext!, syntaxContext!.comparison_metric ?? 'nain', segment[syntaxContext!.comparison_metric ?? 'nain']);
      const line = new THREE.Line(geometry,new THREE.LineBasicMaterial({ color:style.strokeColor }));
      scene.add(line); roadObjects.push(line);
    }

    for (const building of buildings) {
      for (const floor of building.floors) {
        const ring = polygonRing(floor.geometry);
        if (!ring || ring.length < 4) continue;
        const shape = new THREE.Shape();
        shape.moveTo(ring[0]![0] - centerX, ring[0]![1] - centerY);
        for (const coordinate of ring.slice(1)) shape.lineTo(coordinate[0] - centerX, coordinate[1] - centerY);
        shape.closePath();
        const polygon = floor.geometry.coordinates as number[][][];
        for (const holeRing of polygon.slice(1)) {
          if (!holeRing.length) continue;
          const hole = new THREE.Path();
          hole.moveTo(holeRing[0][0] - centerX, holeRing[0][1] - centerY);
          for (const coordinate of holeRing.slice(1)) hole.lineTo(coordinate[0] - centerX, coordinate[1] - centerY);
          hole.closePath(); shape.holes.push(hole);
        }
        const floorHeight = floor.level === 0 ? building.first_floor_height_m : building.standard_floor_height_m;
        const baseElevation = floor.level === 0 ? 0 : building.first_floor_height_m + (floor.level - 1) * building.standard_floor_height_m;
        const geometry = new THREE.ExtrudeGeometry(shape, { depth: floorHeight, bevelEnabled: false });
        geometry.translate(0, 0, baseElevation);
        const material = new THREE.MeshStandardMaterial({
          color: building.building_id === selectedBuildingId ? '#49c9b0' : '#55758d',
          roughness: 0.78,
          metalness: 0.05,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData = {
          buildingId: building.building_id,
          floorId: floor.floor_id,
          edgeRing: ring.map((point) => [point[0] - centerX, point[1] - centerY]),
        };
        mesh.position.z = 0;
        scene.add(mesh);
        masses.push(mesh);
        if (floor.level === 0) for (const vertices of activeFacadeVertices(building.facade_segments, floorHeight, (x,y) => [x-centerX,y-centerY])) {
          const faceGeometry = new THREE.BufferGeometry();
          faceGeometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices.flat(), 3));
          scene.add(new THREE.Mesh(faceGeometry, new THREE.MeshStandardMaterial({ color: 0xd86c37, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 })));
        }
      }
    }

    const maxSpan = Math.max(maxX - minX, maxY - minY, 40);
    camera.position.set(maxSpan * 0.8, -maxSpan * 1.1, maxSpan * 0.8);
    camera.lookAt(0, 0, 14);
    let animationFrame = 0;
    const renderFrame = () => {
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(renderFrame);
    };
    animationFrame = window.requestAnimationFrame(renderFrame);
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const onPointerDown = (event: PointerEvent) => {
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.set(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -((event.clientY - bounds.top) / bounds.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(masses, false)[0];
      if (!hit) return;
      const buildingId = String(hit.object.userData.buildingId);
      const ring = hit.object.userData.edgeRing as number[][];
      const localPoint = hit.point;
      const edgeIndex = nearestEdgeIndex(localPoint.x, localPoint.y, ring);
      const face = hit.face && hit.face.normal.z > 0.65 ? 'top' : 'side';
      const building = buildings.find((item) => item.building_id === buildingId);
      if (!building) return;
      dragRef.current = {
        buildingId,
        face,
        edgeIndex,
        startY: event.clientY,
        floors: building.floors.map(({ floor_id, level }) => ({ floor_id, level })),
        geometryHash: building.geometry_hash ?? '',
      };
      renderer.domElement.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      const start = dragRef.current;
      if (!start) return;
      const deltaY = event.clientY - start.startY;
      if (start.face === 'top' && Math.abs(deltaY) >= 8) {
        onPreview(deltaY < 0 ? t("Preview: add one floor") : t("Preview: remove top floor"));
      } else if (start.face === 'side' && Math.abs(deltaY) >= 40) {
        const metres = Math.max(1, Math.round(Math.abs(deltaY) / 40));
        onPreview(t('Preview: move side normal by {metres} m', { metres: Math.sign(-deltaY) * metres }));
      }
    };
    const onPointerUp = async (event: PointerEvent) => {
      const start = dragRef.current;
      dragRef.current = null;
      onPreview(null);
      if (!start) return;
      const command = commandFromDrag({
        face: start.face,
        deltaY: event.clientY - start.startY,
        buildingId: start.buildingId,
        floors: start.floors,
        edgeIndex: start.edgeIndex,
        originGeometryHash: start.geometryHash,
      });
      onSelectBuilding(start.buildingId);
      if (command) await onEdit(start.buildingId, command);
    };
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('pointerup', onPointerUp);
    renderer.domElement.addEventListener('pointercancel', onPointerUp);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('pointerup', onPointerUp);
      renderer.domElement.removeEventListener('pointercancel', onPointerUp);
      for (const mesh of masses) {
        mesh.geometry.dispose();
        const material = mesh.material;
        if (Array.isArray(material)) material.forEach((item) => item.dispose());
        else material.dispose();
      }
      for (const road of roadObjects) { road.geometry.dispose(); (road.material as THREE.Material).dispose(); }
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [roadFeatures, syntaxContext, buildings, onEdit, onPreview, onSelectBuilding, selectedBuildingId]);

  return (
    <div className="scenario-model-3d" ref={containerRef}>
      {renderError && <div className="scenario-model-fallback" role="status">{renderError}</div>}
      {!renderError && <span className="scenario-model-instruction">{t("Drag top: add/remove one floor. Drag side: preview 1 m per 40 px. Shift does not change sizing mode.")}</span>}
    </div>
  );
};
