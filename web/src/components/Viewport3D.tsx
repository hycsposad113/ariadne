import { lineTouchesStudyArea } from '../utils/geometryScope';
import { fabricCameraFit } from '../utils/fabricCamera';
import { landColor } from './fabricPalette';
import { activeFacadeVertices } from '../utils/activeFacades';
import { proposalRoadStyle, outsideRoadParts, roadRibbonVertices } from '../utils/proposalRoads';
import { MassingIntent, type MassingIntentRecord } from './MassingIntent';
import React, { useRef, useEffect, useState, useCallback } from 'react';
import * as THREE from 'three';
import { ArrowRight, ArrowUp, Compass, Download, Expand, Info, Layers, Ruler } from 'lucide-react';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { useI18n, useT } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import type { Building, ExplorationDesignArea, Segment } from '../types';
import { epsg28992ToLocalMetric, localMetricToEpsg28992 } from '../utils/geoTransform';
import { measure3DPoints, type MetricPoint3D, type ThreeDimensionalMeasurement } from '../utils/measure';
import { calculateRoadPickThreshold, normalizeRoadLineParts } from '../utils/roadPicking';
import { buildSyntaxHeatmapClassification } from '../utils/syntaxHeatmap';
import {
  type SyntaxContextResponse,
  type SyntaxContextMode,
  type SyntaxContextMetric,
  buildClassificationFromBreaks,
  classifyContextValue,
  syntaxContextBadgeStatus,
} from '../utils/syntaxContext';
import { getNavigationAction, type NavigationAction } from './viewport3d/navigation';
import {
  buildSchematic3DFigureMetadata,
  canExportSchematic3DFigure,
  composeSchematic3DFigure,
  MAX_RENDERED_ROAD_SEGMENTS,
  type SchematicFigureContext,
} from '../utils/schematicFigure';
import './Viewport3D.measure.css';
import { getContextBuildingExtrusion, useSurroundingContext } from '../utils/surroundingContext';

export interface Viewport3DLabels {
  viewToolbar: string;
  top: string;
  front: string;
  right: string;
  perspective: string;
  zoomExtents: string;
  syntax: string;
  visible: string;
  hidden: string;
  syntaxLegend: string;
}

export interface Viewport3DCameraState {
  target: [number, number, number];
  radius: number;
  phi: number;
  theta: number;
  up: [number, number, number];
}

export interface BuildingDisplayHeight {
  heightM: number;
  status: 'KNOWN' | 'UNKNOWN';
  method: 'FEATURE_HEIGHT' | 'SCENARIO_ASSUMPTIONS' | 'DISPLAY_DEFAULT';
}

export const DEFAULT_PREVIEW_STOREY_HEIGHT_M = 3;

export function resolveBuildingDisplayHeight(properties: Record<string, unknown> = {}): BuildingDisplayHeight {
  const positive = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
  const floorCount = typeof properties.floor_count === 'number' && Number.isInteger(properties.floor_count) && properties.floor_count > 0
    ? properties.floor_count
    : null;
  const firstFloorHeight = positive(properties.first_floor_height_m);
  const standardFloorHeight = positive(properties.standard_floor_height_m);
  if (properties.fabric_display === true) { const h=positive(properties.height_m); return h !== null ? { heightM: h, status: 'KNOWN', method: 'FEATURE_HEIGHT' } : { heightM: 0, status: 'UNKNOWN', method: 'DISPLAY_DEFAULT' }; }
  if (floorCount !== null && firstFloorHeight !== null && standardFloorHeight !== null) {
    return {
      heightM: firstFloorHeight + (floorCount - 1) * standardFloorHeight,
      status: 'KNOWN',
      method: 'SCENARIO_ASSUMPTIONS',
    };
  }
  const featureHeight = positive(properties.height_m);
  if (featureHeight !== null) return { heightM: featureHeight, status: 'KNOWN', method: 'FEATURE_HEIGHT' };
  if (floorCount !== null) {
    return {
      heightM: DEFAULT_PREVIEW_STOREY_HEIGHT_M + (floorCount - 1) * DEFAULT_PREVIEW_STOREY_HEIGHT_M,
      status: 'UNKNOWN',
      method: 'DISPLAY_DEFAULT',
    };
  }
  return { heightM: DEFAULT_PREVIEW_STOREY_HEIGHT_M, status: 'UNKNOWN', method: 'DISPLAY_DEFAULT' };
}

export interface Viewport3DSyntaxLegendEntry {
  label: string;
  color: string;
}

export interface Viewport3DProps {
  studyAreaGeometry: any;
  explorationDesignArea?: ExplorationDesignArea | null;
  buildings: Building[];
  segments: Segment[];
  scenarioAreas?: Array<{ id: string; geometry: { type: string; coordinates: unknown }; kind: string }>;
  syntaxSegments?: Segment[];
  syntaxSegmentValues?: Record<string, number>;
  syntaxLegend?: Viewport3DSyntaxLegendEntry[];
  syntaxOverlayVisible?: boolean;
  onSyntaxOverlayVisibilityChange?: (visible: boolean) => void;
  labels?: Partial<Viewport3DLabels>;
  cameraState?: Viewport3DCameraState;
  onCameraChange?: (state: Viewport3DCameraState) => void;
  selectedFeatureId: string | null;
  selectedFeatureIds?: string[];
  onSelectFeature: (id: string | null, type: 'building' | 'road') => void;
  figureContext: SchematicFigureContext;
  figureExportReady: boolean;
  syntaxContextData?: SyntaxContextResponse | null;
  syntaxContextStatus?: 'idle' | 'loading' | 'success' | 'error';
  syntaxContextError?: string | null;
  syntaxMode?: SyntaxContextMode;
  syntaxMetric?: SyntaxContextMetric;
  syntaxDistanceKm?: number;
}

const DEFAULT_VIEWPORT3D_LABELS: Viewport3DLabels = {
  viewToolbar: '3D views',
  top: 'Top',
  front: 'Front',
  right: 'Right',
  perspective: 'Perspective',
  zoomExtents: 'Zoom Extents',
  syntax: 'Space Syntax',
  visible: 'On',
  hidden: 'Off',
  syntaxLegend: 'Space Syntax legend',
};

type ViewPreset = 'top' | 'front' | 'right' | 'perspective';
const EMPTY_SEGMENTS: Segment[] = [];
const EMPTY_SCENARIO_AREAS: NonNullable<Viewport3DProps['scenarioAreas']> = [];
const EMPTY_SYNTAX_VALUES: Record<string, number> = {};
const EMPTY_SYNTAX_LEGEND: Viewport3DSyntaxLegendEntry[] = [];

function threePathFromRing(ring: number[][], project: (point: number[]) => [number, number]): THREE.Shape | null {
  if (!Array.isArray(ring) || ring.length < 4) return null;
  const path = new THREE.Shape();
  const [firstX, firstY] = project(ring[0]);
  path.moveTo(firstX, firstY);
  for (let index = 1; index < ring.length; index += 1) {
    const [x, y] = project(ring[index]);
    path.lineTo(x, y);
  }
  path.closePath();
  return path;
}

function shapesFromPolygonGeometry(
  geometry: { type: string; coordinates: any },
  project: (point: number[]) => [number, number],
): THREE.Shape[] {
  if (!geometry || !geometry.coordinates || !['Polygon', 'MultiPolygon'].includes(geometry.type)) return [];
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  const shapes: THREE.Shape[] = [];
  for (const rings of polygons) {
    if (!Array.isArray(rings) || rings.length === 0) continue;
    const shape = threePathFromRing(rings[0], project);
    if (!shape) continue;
    for (const holeRing of rings.slice(1)) {
      if (!Array.isArray(holeRing) || holeRing.length < 4) continue;
      const hole = new THREE.Path();
      const [firstX, firstY] = project(holeRing[0]);
      hole.moveTo(firstX, firstY);
      for (let index = 1; index < holeRing.length; index += 1) {
        const [x, y] = project(holeRing[index]);
        hole.lineTo(x, y);
      }
      hole.closePath();
      shape.holes.push(hole);
    }
    shapes.push(shape);
  }
  return shapes;
}

export const Viewport3D: React.FC<Viewport3DProps> = ({
  studyAreaGeometry,
  explorationDesignArea = null,
  buildings,
  segments,
  scenarioAreas = EMPTY_SCENARIO_AREAS,
  syntaxSegments = EMPTY_SEGMENTS,
  syntaxSegmentValues = EMPTY_SYNTAX_VALUES,
  syntaxLegend = EMPTY_SYNTAX_LEGEND,
  syntaxOverlayVisible: controlledSyntaxOverlayVisible,
  onSyntaxOverlayVisibilityChange,
  labels: suppliedLabels,
  cameraState,
  onCameraChange,
  selectedFeatureId,
  selectedFeatureIds = [],
  onSelectFeature,
  figureContext,
  figureExportReady,
  syntaxContextData = null,
  syntaxContextStatus = 'idle',
  syntaxContextError = null,
  syntaxMode = 'pedestrian',
  syntaxMetric = 'nain',
  syntaxDistanceKm = 1.0,
}) => {
  const t = useT();
  const { language } = useI18n();
  const labels = {
    viewToolbar: t(suppliedLabels?.viewToolbar ?? DEFAULT_VIEWPORT3D_LABELS.viewToolbar),
    top: t(suppliedLabels?.top ?? DEFAULT_VIEWPORT3D_LABELS.top),
    front: t(suppliedLabels?.front ?? DEFAULT_VIEWPORT3D_LABELS.front),
    right: t(suppliedLabels?.right ?? DEFAULT_VIEWPORT3D_LABELS.right),
    perspective: t(suppliedLabels?.perspective ?? DEFAULT_VIEWPORT3D_LABELS.perspective),
    zoomExtents: t(suppliedLabels?.zoomExtents ?? DEFAULT_VIEWPORT3D_LABELS.zoomExtents),
    syntax: t(suppliedLabels?.syntax ?? DEFAULT_VIEWPORT3D_LABELS.syntax),
    visible: t(suppliedLabels?.visible ?? DEFAULT_VIEWPORT3D_LABELS.visible),
    hidden: t(suppliedLabels?.hidden ?? DEFAULT_VIEWPORT3D_LABELS.hidden),
    syntaxLegend: t(suppliedLabels?.syntaxLegend ?? DEFAULT_VIEWPORT3D_LABELS.syntaxLegend),
  };
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const navigationApiRef = useRef<{
    setPreset: (preset: ViewPreset) => void;
    zoomExtents: () => void;
    setCameraState: (state: Viewport3DCameraState) => void;
  } | null>(null);
  const meshMapRef = useRef<Map<string, THREE.Mesh>>(new Map());
  const buildingMaterialMapRef = useRef<Map<string, THREE.MeshStandardMaterial>>(new Map());
  const buildingBaseColorMapRef = useRef<Map<string, THREE.ColorRepresentation>>(new Map());
  const roadMaterialMapRef = useRef<Map<string, THREE.LineBasicMaterial>>(new Map());
  const roadLineMapRef = useRef<Map<string, THREE.Line[]>>(new Map());
  const renderedRoadSegmentCountRef = useRef(0);
  const onSelectFeatureRef = useRef(onSelectFeature);
  const selectedFeatureIdRef = useRef(selectedFeatureId);
  const cameraStateRef = useRef(cameraState);
  const onCameraChangeRef = useRef(onCameraChange);
  const sphericalRef = useRef({ radius: 750, phi: Math.PI / 3.5, theta: 0 });
  const isMeasuring3DRef = useRef(false);
  const measurementPoints3DRef = useRef<MetricPoint3D[]>([]);
  const [isExportingFigure, setIsExportingFigure] = useState(false);
  const [figureExportMessage, setFigureExportMessage] = useState('');
  const [isMeasuring3D, setIsMeasuring3D] = useState(false);
  const [measurementPoints3D, setMeasurementPoints3D] = useState<MetricPoint3D[]>([]);
  const [measurement3DResult, setMeasurement3DResult] = useState<ThreeDimensionalMeasurement | null>(null);
  const [measurement3DError, setMeasurement3DError] = useState('');
  const [localSyntaxOverlayVisible, setLocalSyntaxOverlayVisible] = useState(true);
  const [sceneRevision, setSceneRevision] = useState(0);
  const isSyntaxOverlayVisible = controlledSyntaxOverlayVisible ?? localSyntaxOverlayVisible;
  const surroundingContext = useSurroundingContext(4.0);
  const unknownBuildingHeightCount = buildings.filter(building => resolveBuildingDisplayHeight(building.properties ?? {}).status === 'UNKNOWN').length;

  const recordMeasurementPoint3D = useCallback((point: MetricPoint3D) => {
    const current = measurementPoints3DRef.current;
    if (current.length === 0) {
      const next = [point];
      measurementPoints3DRef.current = next;
      setMeasurementPoints3D(next);
      setMeasurement3DResult(null);
      setMeasurement3DError('');
      return;
    }
    if (current.length === 1) {
      const next = [current[0], point];
      measurementPoints3DRef.current = next;
      setMeasurementPoints3D(next);
      setMeasurement3DResult(measure3DPoints(next[0], next[1]));
      setMeasurement3DError('');
      isMeasuring3DRef.current = false;
      setIsMeasuring3D(false);
    }
  }, []);

  useEffect(() => {
    onSelectFeatureRef.current = onSelectFeature;
  }, [onSelectFeature]);

  useEffect(() => {
    selectedFeatureIdRef.current = selectedFeatureId;
  }, [selectedFeatureId]);

  useEffect(() => {
    cameraStateRef.current = cameraState;
  }, [cameraState]);

  useEffect(() => {
    onCameraChangeRef.current = onCameraChange;
  }, [onCameraChange]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = Math.max(1, container.clientWidth);
    const height = Math.max(1, container.clientHeight);
    const isFabric = buildings.some(b => b.properties?.fabric_display === true);

    // 1. Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0f17);
    scene.fog = isFabric ? null : new THREE.FogExp2(0x0b0f17, 0.0008);
    sceneRef.current = scene;
    setSceneRevision((revision) => revision + 1);

    // 2. Camera
    const camera = new THREE.PerspectiveCamera(45, width / height, 1, 10000);
    camera.up.set(0, 0, 1);
    camera.position.set(0, -600, 450);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;
    const initialCameraState = cameraStateRef.current;
    const cameraTarget = new THREE.Vector3(...(initialCameraState?.target ?? [0, 0, 0]));

    // 3. Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: isFabric });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // 4. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
    dirLight.position.set(300, -400, 600);
    dirLight.castShadow = true;
    scene.add(dirLight);

    // Surrounding context is merged by visual class so thousands of OSM
    // footprints and ground surfaces remain a small number of GPU draw calls.
    const contextGround: Record<'water' | 'green', THREE.BufferGeometry[]> = { water: [], green: [] };
    const contextBuildings: Record<'measured' | 'osmHeight' | 'levels' | 'flat', THREE.BufferGeometry[]> = {
      measured: [], osmHeight: [], levels: [], flat: [],
    };
    const contextRoadPositions: number[] = [];
    const contextLayers = surroundingContext.data?.layers;
    const toLocal = ([x, y]: number[]): [number, number] => epsg28992ToLocalMetric(x, y);

    for (const feature of contextLayers?.water?.features ?? []) {
      if (!feature.geometry) continue;
      const shapes = shapesFromPolygonGeometry(feature.geometry, toLocal);
      if (shapes.length > 0) {
        const geometry = new THREE.ShapeGeometry(shapes);
        geometry.translate(0, 0, 0.25);
        contextGround.water.push(geometry);
      }
    }
    for (const feature of contextLayers?.green?.features ?? []) {
      if (!feature.geometry) continue;
      const shapes = shapesFromPolygonGeometry(feature.geometry, toLocal);
      if (shapes.length > 0) {
        const geometry = new THREE.ShapeGeometry(shapes);
        geometry.translate(0, 0, 0.2);
        contextGround.green.push(geometry);
      }
    }
    for (const feature of contextLayers?.roads?.features ?? []) {
      const geometry = feature.geometry;
      if (!geometry || !['LineString', 'MultiLineString'].includes(geometry.type)) continue;
      const rawLines = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates;
      const lines = segments.some(s => s.origin) ? rawLines.flatMap((line: number[][]) => outsideRoadParts(line, studyAreaGeometry)) : rawLines;
      for (const line of lines) {
        if (!Array.isArray(line) || line.length < 2) continue;
        for (let index = 1; index < line.length; index += 1) {
          const [startX, startY] = toLocal(line[index - 1]);
          const [endX, endY] = toLocal(line[index]);
          contextRoadPositions.push(startX, startY, 0.55, endX, endY, 0.55);
        }
      }
    }
    for (const feature of contextLayers?.buildings?.features ?? []) {
      if (!feature.geometry || feature.properties?.inside_study_area) continue;
      const shapes = shapesFromPolygonGeometry(feature.geometry, toLocal);
      if (shapes.length === 0) continue;
      const height = getContextBuildingExtrusion(feature.properties ?? {});
      const geometry = height
        ? new THREE.ExtrudeGeometry(shapes, { depth: height.heightM, bevelEnabled: false, curveSegments: 1, steps: 1 })
        : new THREE.ShapeGeometry(shapes);
      if (!height) geometry.translate(0, 0, 0.3);
      if (feature.properties?.height_source === '3DBAG') contextBuildings.measured.push(geometry);
      else if (feature.properties?.height_source === 'OSM_HEIGHT') contextBuildings.osmHeight.push(geometry);
      else if (feature.properties?.height_source === 'OSM_BUILDING_LEVELS_DISPLAY_ASSUMPTION') contextBuildings.levels.push(geometry);
      else contextBuildings.flat.push(geometry);
    }

    const addMergedMesh = (
      geometries: THREE.BufferGeometry[],
      color: number,
      opacity: number,
      name: string,
    ) => {
      if (geometries.length === 0) return;
      const merged = mergeGeometries(geometries, false);
      geometries.forEach((geometry) => geometry.dispose());
      if (!merged) return;
      const material = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.8,
        metalness: 0,
        transparent: opacity < 1,
        opacity,
        depthWrite: opacity >= 0.9,
      });
      const mesh = new THREE.Mesh(merged, material);
      mesh.name = name;
      mesh.receiveShadow = false;
      mesh.castShadow = false;
      scene.add(mesh);
    };
    addMergedMesh(contextGround.water, 0x287ca2, 0.52, 'osm-context-water');
    addMergedMesh(contextGround.green, 0x668b5b, 0.28, 'osm-context-green');
    addMergedMesh(contextBuildings.measured, 0xaab7bf, 0.58, 'context-buildings-3dbag');
    addMergedMesh(contextBuildings.osmHeight, 0x94a4ad, 0.42, 'context-buildings-osm-height');
    addMergedMesh(contextBuildings.levels, 0x83949e, 0.34, 'context-buildings-osm-levels');
    addMergedMesh(contextBuildings.flat, 0x7c8991, 0.2, 'context-building-footprints');
    if (contextRoadPositions.length > 0) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(contextRoadPositions, 3));
      const material = new THREE.LineBasicMaterial({ color: 0x9aa6ad, transparent: true, opacity: 0.32 });
      const lines = new THREE.LineSegments(geometry, material);
      lines.name = 'osm-context-road-centerlines';
      scene.add(lines);
    }

    // 5. Ground Grid
    const grid = new THREE.GridHelper(2000, 40, 0x334155, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    // 6. Add Study Area Boundary Line
    if (studyAreaGeometry && studyAreaGeometry.coordinates) {
      const rings = studyAreaGeometry.coordinates;
      for (const ring of rings) {
        if (ring.length < 3) continue;
        const pts: THREE.Vector3[] = [];
        for (const [x, y] of ring) {
          const [lx, ly] = epsg28992ToLocalMetric(x, y);
          pts.push(new THREE.Vector3(lx, ly, 1));
        }
        const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
        const lineMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, linewidth: 2 });
        const boundaryLine = new THREE.Line(lineGeo, lineMat);
        scene.add(boundaryLine);
      }
    }

    // Keep the conceptual Exploration Design Area distinct from StudyArea.
    if (explorationDesignArea?.geometry?.coordinates) {
      const polygons = explorationDesignArea.geometry.type === 'MultiPolygon'
        ? explorationDesignArea.geometry.coordinates
        : [explorationDesignArea.geometry.coordinates];
      for (const rings of polygons) {
        for (const ring of rings) {
          if (ring.length < 3) continue;
          const points: THREE.Vector3[] = [];
          for (const [x, y] of ring) {
            const [lx, ly] = epsg28992ToLocalMetric(x, y);
            points.push(new THREE.Vector3(lx, ly, 2));
          }
          const boundary = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(points),
            new THREE.LineDashedMaterial({ color: 0xfacc15, dashSize: 14, gapSize: 8 }),
          );
          boundary.computeLineDistances();
          boundary.name = 'exploration-design-area-boundary';
          scene.add(boundary);
        }
      }
    }

    // The verified preview geometry includes water, blocks, and open spaces.
    // Draw these at ground level over the existing 2 km context.
    for (const area of scenarioAreas) {
      const shapes = shapesFromPolygonGeometry(area.geometry, toLocal);
      if (shapes.length === 0) continue;
      const color = area.kind.startsWith('fabric:') ? landColor(area.kind.slice(7)) : area.kind === 'water'
        ? 0x287ca2
        : area.kind === 'waterfront_building_no_build_band'
          ? 0xf472b6
          : area.kind === 'street_block'
            ? 0x94a3b8
            : 0x668b5b;
      const mesh = new THREE.Mesh(
        new THREE.ShapeGeometry(shapes),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: area.kind === 'street_block' ? 0.13 : 0.28, side: THREE.DoubleSide, depthWrite: false }),
      );
      mesh.position.z = 0.18;
      mesh.name = `scenario-area:${area.kind}:${area.id}`;
      mesh.renderOrder = 1;
      scene.add(mesh);
    }

    // 7. Add Road Segments
    roadMaterialMapRef.current.clear();
    roadLineMapRef.current.clear();
    let renderedRoadCount = 0;
    for (const seg of segments.slice(0, MAX_RENDERED_ROAD_SEGMENTS)) {
      const roadParts = normalizeRoadLineParts(seg.geometry);
      if (roadParts.length === 0) continue;
      const style = { ...proposalRoadStyle(seg) };
      const fabric = seg as Segment & { fabric_color?: string };
      if (fabric.fabric_color) style.color = fabric.fabric_color;
      const roadMat = style.dash.length ? new THREE.LineDashedMaterial({ color: style.color, dashSize: 3, gapSize: 3 }) : new THREE.LineBasicMaterial({ color: style.color });
      const roadLines = roadParts.map((part) => {
        const pts = part.map(([x, y]) => {
          const [lx, ly] = epsg28992ToLocalMetric(x, y);
          return new THREE.Vector3(lx, ly, 0.5);
        });
        const roadGeo = new THREE.BufferGeometry().setFromPoints(pts);
        const roadLine = new THREE.Line(roadGeo, roadMat);
        roadLine.name = seg.id;
        roadLine.userData.featureId = seg.id;
        roadLine.userData.featureKind = 'road';
        if (style.dash.length) roadLine.computeLineDistances();
        scene.add(roadLine);
        if (seg.width_m && (seg.modes || fabric.fabric_color)) {
          const surfaceGeometry = new THREE.BufferGeometry();
          const vertices = roadRibbonVertices(pts.map(p => [p.x,p.y]), seg.width_m);
          surfaceGeometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
          const surface = new THREE.Mesh(surfaceGeometry, new THREE.MeshBasicMaterial({ color: style.color, side: THREE.DoubleSide, transparent: true, opacity: 0.55 }));
          surface.name = `proposal-road-surface:${seg.id}`;
          scene.add(surface);
        }
        return roadLine;
      });
      roadMaterialMapRef.current.set(seg.id, roadMat);
      roadLineMapRef.current.set(seg.id, roadLines);
      renderedRoadCount += 1;
    }
    renderedRoadSegmentCountRef.current = renderedRoadCount;

    // 8. Add Extruded Buildings
    meshMapRef.current.clear();
    buildingMaterialMapRef.current.clear();
    buildingBaseColorMapRef.current.clear();
    for (const b of buildings) {
      const geom = b.geometry;
      if (!geom || !geom.coordinates) continue;

      const shapes = shapesFromPolygonGeometry(geom, toLocal);
      if (!shapes.length) continue;

      const height = resolveBuildingDisplayHeight(b.properties ?? {});
      const extrudeSettings = {
        depth: height.heightM,
        bevelEnabled: false,
      };

      // S6 podium/cutback plates have different footprints. Preserve each plate
      // instead of extruding the ground footprint through the whole building.
      const plates = b.properties?.floors;
      const floorGeometries: THREE.BufferGeometry[] = [];
      let elevation = 0;
      if (Array.isArray(plates)) for (const plate of plates) {
        const depth = Number(plate.floor_height_m);
        if (!Number.isFinite(depth) || depth <= 0 || !plate.geometry) continue;
        const floorShapes = shapesFromPolygonGeometry(plate.geometry, toLocal);
        if (!floorShapes.length) continue;
        const geometry = new THREE.ExtrudeGeometry(floorShapes, { depth, bevelEnabled: false });
        geometry.translate(0, 0, elevation); elevation += depth;
        floorGeometries.push(geometry);
      }
      const mergedFloors = floorGeometries.length ? mergeGeometries(floorGeometries, false) : null;
      const buildingGeo = mergedFloors ?? new THREE.ExtrudeGeometry(shapes, extrudeSettings);
      floorGeometries.forEach(g => g.dispose());

      let matColor: THREE.ColorRepresentation = 0x64748b;
      if (b.disposition === 'PRESERVE') matColor = 0x10b981;
      else if (b.disposition === 'EDITABLE') matColor = 0x38bdf8;

      if (b.properties?.fabric_display === true) matColor = b.properties.fabric_color;
      const buildingMat = new THREE.MeshStandardMaterial({
        color: matColor,
        roughness: 0.4,
        metalness: 0.1,
      });
      buildingBaseColorMapRef.current.set(b.id, matColor);
      buildingMaterialMapRef.current.set(b.id, buildingMat);

      const mesh = new THREE.Mesh(buildingGeo, buildingMat);
      mesh.name = b.id;
      mesh.userData.heightStatus = height.status;
      mesh.userData.heightMethod = height.method;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      scene.add(mesh);
      for (const vertices of activeFacadeVertices(b.properties?.facade_segments,
        Math.min(height.heightM, Number(b.properties?.first_floor_height_m) || 3.5), epsg28992ToLocalMetric)) {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices.flat(), 3));
        const facade = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0xd86c37, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 }));
        facade.name = `active-facade:${b.id}`; scene.add(facade);
      }
      meshMapRef.current.set(b.id, mesh);
    }

    // Rhino-style navigation keeps the Z-up ground plane under the cursor.
    let isMouseDown = false;
    let didDrag = false;
    let activeAction: NavigationAction = 'none';
    let activeButton = 0;
    let mouseDownPos = { x: 0, y: 0 };
    let prevMousePos = { x: 0, y: 0 };
    let spherical = initialCameraState
      ? { radius: initialCameraState.radius, phi: initialCameraState.phi, theta: initialCameraState.theta }
      : { ...sphericalRef.current };
    const cameraUp = new THREE.Vector3(...(initialCameraState?.up ?? [0, 0, 1]));
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

    const publishCameraState = () => {
      onCameraChangeRef.current?.({
        target: [cameraTarget.x, cameraTarget.y, cameraTarget.z],
        radius: spherical.radius,
        phi: spherical.phi,
        theta: spherical.theta,
        up: [cameraUp.x, cameraUp.y, cameraUp.z],
      });
    };

    const updateCameraPosition = (publish = false) => {
      const horizontalRadius = spherical.radius * Math.sin(spherical.phi);
      camera.position.set(
        cameraTarget.x + horizontalRadius * Math.sin(spherical.theta),
        cameraTarget.y - horizontalRadius * Math.cos(spherical.theta),
        cameraTarget.z + spherical.radius * Math.cos(spherical.phi),
      );
      camera.up.copy(cameraUp);
      camera.lookAt(cameraTarget);
      camera.updateMatrixWorld();
      sphericalRef.current = { ...spherical };
      renderer.domElement.dataset.cameraState = JSON.stringify({target:[cameraTarget.x,cameraTarget.y,cameraTarget.z],radius:spherical.radius,phi:spherical.phi,theta:spherical.theta,up:[cameraUp.x,cameraUp.y,cameraUp.z]});
      if (publish) publishCameraState();
    };

    const syncSphericalFromCamera = () => {
      const offset = camera.position.clone().sub(cameraTarget);
      spherical.radius = Math.max(1, offset.length());
      spherical.phi = Math.acos(THREE.MathUtils.clamp(offset.z / spherical.radius, -1, 1));
      spherical.theta = Math.atan2(offset.x, -offset.y);
      sphericalRef.current = { ...spherical };
      renderer.domElement.dataset.cameraState = JSON.stringify({target:[cameraTarget.x,cameraTarget.y,cameraTarget.z],radius:spherical.radius,phi:spherical.phi,theta:spherical.theta,up:[cameraUp.x,cameraUp.y,cameraUp.z]});
    };

    const getSelectedOrbitTarget = () => {
      const selectedId = selectedFeatureIdRef.current;
      const selectedObjects: THREE.Object3D[] = [];
      const selectedBuilding = selectedId ? meshMapRef.current.get(selectedId) : undefined;
      if (selectedBuilding) selectedObjects.push(selectedBuilding);
      const selectedRoadParts = selectedId ? roadLineMapRef.current.get(selectedId) : undefined;
      if (selectedRoadParts) selectedObjects.push(...selectedRoadParts);
      if (selectedObjects.length === 0) return cameraTarget.clone();

      const bounds = new THREE.Box3();
      for (const object of selectedObjects) bounds.expandByObject(object);
      return bounds.isEmpty() ? cameraTarget.clone() : bounds.getCenter(new THREE.Vector3());
    };

    const getCursorGroundPoint = (clientX: number, clientY: number) => {
      const rect = dom.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return null;
      const x = ((clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((clientY - rect.top) / rect.height) * 2 + 1;
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(new THREE.Vector2(x, y), camera);
      return raycaster.ray.intersectPlane(groundPlane, new THREE.Vector3());
    };

    const zoomAtCursor = (delta: number, clientX: number, clientY: number, sensitivity = 0.001) => {
      const previousRadius = spherical.radius;
      const nextRadius = THREE.MathUtils.clamp(previousRadius * Math.exp(delta * sensitivity), 100, 25000);
      const zoomRatio = nextRadius / previousRadius;
      const anchor = getCursorGroundPoint(clientX, clientY);
      if (anchor) cameraTarget.add(anchor.sub(cameraTarget).multiplyScalar(1 - zoomRatio));
      spherical.radius = nextRadius;
      updateCameraPosition(true);
    };

    const panCamera = (dx: number, dy: number) => {
      camera.updateMatrixWorld();
      const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
      const screenUp = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
      const unitsPerPixel = (2 * spherical.radius * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)))
        / Math.max(container.clientHeight, 1);
      const translation = right.multiplyScalar(-dx * unitsPerPixel)
        .add(screenUp.multiplyScalar(dy * unitsPerPixel));
      cameraTarget.add(translation);
      camera.position.add(translation);
      camera.lookAt(cameraTarget);
      camera.updateMatrixWorld();
      publishCameraState();
    };

    const setPreset = (preset: ViewPreset) => {
      cameraTarget.copy(getSelectedOrbitTarget());
      if (preset === 'top') {
        cameraUp.set(0, 1, 0);
        spherical.phi = 0;
        spherical.theta = 0;
      } else if (preset === 'front') {
        cameraUp.set(0, 0, 1);
        spherical.phi = Math.PI / 2;
        spherical.theta = 0;
      } else if (preset === 'right') {
        cameraUp.set(0, 0, 1);
        spherical.phi = Math.PI / 2;
        spherical.theta = Math.PI / 2;
      } else {
        cameraUp.set(0, 0, 1);
        spherical.phi = Math.PI / 3.5;
        spherical.theta = 0;
      }
      updateCameraPosition(true);
    };

    const zoomExtents = () => {
      const bounds = new THREE.Box3().setFromObject(scene);
      const fabricFit = isFabric && studyAreaGeometry ? fabricCameraFit(studyAreaGeometry, camera.aspect, camera.fov) : null;
      if (fabricFit) container.dataset.fabricSiteBounds = JSON.stringify([fabricFit.bounds.min.toArray(), fabricFit.bounds.max.toArray()]);
      if (fabricFit) bounds.copy(fabricFit.bounds);
      if (bounds.isEmpty()) {
        cameraTarget.set(0, 0, 0);
        spherical.radius = 750;
      } else {
        const sphere = bounds.getBoundingSphere(new THREE.Sphere());
        const verticalHalfFov = THREE.MathUtils.degToRad(camera.fov / 2);
        const horizontalHalfFov = Math.atan(Math.tan(verticalHalfFov) * camera.aspect);
        const limitingHalfFov = Math.min(verticalHalfFov, horizontalHalfFov);
        cameraTarget.copy(fabricFit?.target ?? sphere.center);
        spherical.radius = fabricFit?.radius ?? THREE.MathUtils.clamp(
          (sphere.radius / Math.sin(limitingHalfFov)) * 1.12,
          100,
          25000,
        );
      }
      cameraUp.set(0, 0, 1);
      spherical.phi = Math.PI / 3.5;
      spherical.theta = 0;
      updateCameraPosition(true);
    };

    const setCameraState = (state: Viewport3DCameraState) => {
      cameraTarget.set(...state.target);
      spherical = { radius: state.radius, phi: state.phi, theta: state.theta };
      cameraUp.set(...state.up);
      updateCameraPosition(false);
    };

    const applyOrbitDelta = (dx: number, dy: number) => {
      cameraTarget.copy(getSelectedOrbitTarget());
      syncSphericalFromCamera();
      spherical.theta += dx * 0.005;
      spherical.phi = THREE.MathUtils.clamp(spherical.phi + dy * 0.005, 0.05, Math.PI - 0.05);
      updateCameraPosition(true);
    };

    updateCameraPosition();
    navigationApiRef.current = { setPreset, zoomExtents, setCameraState };
    if (buildings.some(b => b.properties?.fabric_display === true)) zoomExtents();

    // Diagnostic values come from the actual extrusion geometry, not UI mode flags.
    const fabricMeshes = buildings.filter(b => b.properties?.fabric_display === true).flatMap(b => {
      const mesh = meshMapRef.current.get(b.id);
      if (!mesh) return [];
      mesh.geometry.computeBoundingBox();
      const bounds = mesh.geometry.boundingBox;
      return bounds ? [{ id: b.id, height_m: bounds.max.z - bounds.min.z }] : [];
    });
    if (fabricMeshes.length) {
      container.dataset.fabricRenderState = 'loading';
      container.dataset.fabricMeshCount = String(fabricMeshes.length);
      container.dataset.fabricRenderedHeights = JSON.stringify(fabricMeshes);
    }
    // Render loop
    let reqId: number;
    const animate = () => {
      reqId = requestAnimationFrame(animate);
      renderer.render(scene, camera);
      if (fabricMeshes.length) {
        if (studyAreaGeometry) {
          const projected: THREE.Vector3[] = [];
          const collect = (value: unknown): void => {
            if (!Array.isArray(value)) return;
            if (typeof value[0] === 'number' && typeof value[1] === 'number') {
              const [x, y] = epsg28992ToLocalMetric(value[0], value[1]);
              projected.push(new THREE.Vector3(x, y, 0).project(camera));
            } else value.forEach(collect);
          };
          collect(studyAreaGeometry.coordinates);
          container.dataset.fabricSiteCoverage = JSON.stringify({
            width: (Math.max(...projected.map(p=>p.x))-Math.min(...projected.map(p=>p.x)))/2,
            height: (Math.max(...projected.map(p=>p.y))-Math.min(...projected.map(p=>p.y)))/2,
            unclipped: projected.every(p=>Math.abs(p.x)<=1 && Math.abs(p.y)<=1 && p.z>-1 && p.z<1),
          });
        }
        // Commander 2026-10-13: camera signature excludes aspect (panel layout), so paired views compare camera state only.
        container.dataset.fabricCamera = JSON.stringify({target: cameraTarget.toArray().map(v => Math.round(v * 100) / 100), radius: Math.round(spherical.radius * 100) / 100, position: camera.position.toArray().map(v => Math.round(v * 100) / 100)});
        container.dataset.fabricRenderState = 'ready';
      }
    };
    animate();

    const onMouseDown = (event: MouseEvent) => {
      activeAction = getNavigationAction({
        type: 'pointer',
        button: event.button,
        ctrlKey: event.ctrlKey,
        shiftKey: event.shiftKey,
      });
      activeButton = event.button;
      isMouseDown = true;
      didDrag = false;
      mouseDownPos = { x: event.clientX, y: event.clientY };
      prevMousePos = { x: event.clientX, y: event.clientY };

      if (activeButton === 2 || activeAction !== 'none') event.preventDefault();
      if (activeAction === 'orbit') {
        cameraTarget.copy(getSelectedOrbitTarget());
        syncSphericalFromCamera();
        updateCameraPosition();
      }
    };

    const onMouseMove = (event: MouseEvent) => {
      if (!isMouseDown) return;
      const dx = event.clientX - prevMousePos.x;
      const dy = event.clientY - prevMousePos.y;
      if (Math.hypot(event.clientX - mouseDownPos.x, event.clientY - mouseDownPos.y) >= 3) didDrag = true;
      prevMousePos = { x: event.clientX, y: event.clientY };

      if (activeAction === 'orbit') applyOrbitDelta(dx, dy);
      else if (activeAction === 'pan') panCamera(dx, dy);
      else if (activeAction === 'zoom' && dy !== 0) zoomAtCursor(dy, event.clientX, event.clientY);
    };

    const onMouseUp = (event: MouseEvent) => {
      if (!isMouseDown) return;
      isMouseDown = false;
      if (activeButton !== 0 || activeAction !== 'none' || didDrag) return;

      // Plain left click remains the feature-picking gesture.
      const rect = renderer.domElement.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const mouseX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const mouseY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(new THREE.Vector2(mouseX, mouseY), camera);
      raycaster.params.Line.threshold = calculateRoadPickThreshold(camera, rect.height);
      const selectableObjects: THREE.Object3D[] = [
        ...meshMapRef.current.values(),
        ...Array.from(roadLineMapRef.current.values()).flat(),
      ];
      const intersects = raycaster.intersectObjects(selectableObjects);

      if (isMeasuring3DRef.current) {
        const hit = intersects[0];
        if (!hit) {
          setMeasurement3DError('Click a visible building or road surface in the schematic 3D model.');
          return;
        }
        const [easting, northing] = localMetricToEpsg28992(hit.point.x, hit.point.y);
        recordMeasurementPoint3D([easting, northing, hit.point.z]);
        return;
      }

      if (intersects.length > 0) {
        const hitObject = intersects[0].object;
        if (hitObject.userData.featureKind === 'road') {
          const clickedId = hitObject.userData.featureId || hitObject.name;
          onSelectFeatureRef.current(clickedId, 'road');
        } else {
          onSelectFeatureRef.current(hitObject.name, 'building');
        }
      }
    };

    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const action = getNavigationAction({
        type: 'wheel',
        deltaMode: event.deltaMode,
        ctrlKey: event.ctrlKey,
        shiftKey: event.shiftKey,
        deltaX: event.deltaX,
        deltaY: event.deltaY,
        wheelDeltaY: (event as WheelEvent & { wheelDeltaY?: number }).wheelDeltaY,
      });
      const deltaScale = event.deltaMode === 1
        ? 30
        : event.deltaMode === 2
          ? Math.max(dom.clientHeight, 1)
          : 1;
      const deltaX = event.deltaX * deltaScale;
      const deltaY = event.deltaY * deltaScale;
      if (action === 'orbit') applyOrbitDelta(deltaX, deltaY);
      // Trackpad scroll deltas are opposite to pointer-drag deltas; negate so the scene follows the fingers (Rhino-style grab).
      else if (action === 'pan') panCamera(-deltaX, -deltaY);
      else if (action === 'zoom') zoomAtCursor(deltaY, event.clientX, event.clientY);
    };

    const onDoubleClick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const mouseX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const mouseY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(new THREE.Vector2(mouseX, mouseY), camera);
      raycaster.params.Line.threshold = calculateRoadPickThreshold(camera, rect.height);
      const selectableObjects: THREE.Object3D[] = [
        ...meshMapRef.current.values(),
        ...Array.from(roadLineMapRef.current.values()).flat(),
      ];
      if (raycaster.intersectObjects(selectableObjects).length === 0) zoomExtents();
    };

    const onContextMenu = (event: MouseEvent) => event.preventDefault();
    const dom = renderer.domElement;
    dom.style.touchAction = 'none';
    dom.style.overscrollBehavior = 'contain';
    dom.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    dom.addEventListener('wheel', onWheel, { passive: false });
    dom.addEventListener('dblclick', onDoubleClick);
    dom.addEventListener('contextmenu', onContextMenu);

    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w <= 0 || h <= 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      if (buildings.some(b => b.properties?.fabric_display === true)) zoomExtents();
    };
    window.addEventListener('resize', handleResize);
    const resizeObserver=typeof ResizeObserver !== 'undefined'?new ResizeObserver(handleResize):null;
    resizeObserver?.observe(container);

    return () => {
      cancelAnimationFrame(reqId);
      delete container.dataset.fabricRenderState;
      delete container.dataset.fabricMeshCount;
      delete container.dataset.fabricRenderedHeights;
      dom.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      dom.removeEventListener('wheel', onWheel);
      dom.removeEventListener('dblclick', onDoubleClick);
      dom.removeEventListener('contextmenu', onContextMenu);
      window.removeEventListener('resize', handleResize);
      resizeObserver?.disconnect();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      if (sceneRef.current === scene) sceneRef.current = null;
      if (cameraRef.current === camera) cameraRef.current = null;
      if (rendererRef.current === renderer) rendererRef.current = null;
      if (navigationApiRef.current?.setPreset === setPreset) navigationApiRef.current = null;
      renderer.dispose();
    };
  }, [studyAreaGeometry, explorationDesignArea, buildings, segments, scenarioAreas, surroundingContext.data, recordMeasurementPoint3D]);

  useEffect(() => {
    if (!cameraState) return;
    navigationApiRef.current?.setCameraState(cameraState);
  }, [cameraState]);

  useEffect(() => {
    const scene = sceneRef.current;
    const hasContextSegments = Boolean(
      syntaxContextData &&
      Array.isArray(syntaxContextData.segments) &&
      syntaxContextData.segments.length > 0 &&
      syntaxContextData.legend_breaks &&
      syntaxContextData.legend_breaks[syntaxMetric ?? 'nain']
    );
    if (!scene || !isSyntaxOverlayVisible || (!hasContextSegments && syntaxSegments.length === 0)) return;

    const group = new THREE.Group();
    group.name = 'space-syntax-overlay';
    const ribbonPositionsByColor = new Map<string, number[]>();
    const boundaryPositionsByColor = new Map<string, number[]>();
    const bandHalfWidth = 1.5;
    const bandHeight = 1.25;

    if (hasContextSegments && syntaxContextData) {
      for (const segment of syntaxContextData.segments) {
        const coordinates = segment.coordinates;
        if (buildings.some(b => b.properties?.fabric_display === true) && !syntaxContextData?.comparison_view && (segment.inside_site || lineTouchesStudyArea(segment.coordinates, studyAreaGeometry))) continue;
        if (!Array.isArray(coordinates) || coordinates.length < 2) continue;
        if (coordinates.some((point) => !Array.isArray(point)
          || point.length < 2
          || !Number.isFinite(point[0])
          || !Number.isFinite(point[1]))) continue;

        const val = syntaxMetric === 'nach' ? segment.nach : segment.nain;
        const style = classifyContextValue(syntaxContextData, syntaxMetric ?? 'nain', val);
        const points = coordinates.map(([easting, northing]) => {
          const [x, y] = epsg28992ToLocalMetric(easting, northing);
          return new THREE.Vector3(x, y, bandHeight);
        });

        if (style.isUncomputed) {
          const geometry = new THREE.BufferGeometry().setFromPoints(points);
          const material = new THREE.LineDashedMaterial({color:style.strokeColor,dashSize:3,gapSize:3,depthWrite:false});
          const line = new THREE.Line(geometry, material);
          line.computeLineDistances(); line.name = `space-syntax-uncomputed:${segment.id}`;
          group.add(line); continue;
        }
        const targetMap = segment.boundary_effect_risk ? boundaryPositionsByColor : ribbonPositionsByColor;
        const vertices = targetMap.get(style.strokeColor) ?? [];
        for (let index = 1; index < points.length; index += 1) {
          const start = points[index - 1];
          const end = points[index];
          const dx = end.x - start.x;
          const dy = end.y - start.y;
          const length = Math.hypot(dx, dy);
          if (length <= 0) continue;
          const offsetX = -(dy / length) * bandHalfWidth;
          const offsetY = (dx / length) * bandHalfWidth;
          const leftStart = [start.x + offsetX, start.y + offsetY, bandHeight];
          const rightStart = [start.x - offsetX, start.y - offsetY, bandHeight];
          const leftEnd = [end.x + offsetX, end.y + offsetY, bandHeight];
          const rightEnd = [end.x - offsetX, end.y - offsetY, bandHeight];
          vertices.push(...leftStart, ...rightStart, ...leftEnd, ...rightStart, ...rightEnd, ...leftEnd);
        }
        targetMap.set(style.strokeColor, vertices);
      }
    } else {
      const classification = buildSyntaxHeatmapClassification(syntaxSegmentValues);
      for (const segment of syntaxSegments) {
        const coordinates = segment.geometry?.coordinates;
        if (buildings.some(b => b.properties?.fabric_display === true) && lineTouchesStudyArea(segment.geometry?.coordinates ?? [], studyAreaGeometry)) continue;
        if (!Array.isArray(coordinates) || coordinates.length < 2) continue;
        if (coordinates.some((point) => !Array.isArray(point)
          || point.length < 2
          || !Number.isFinite(point[0])
          || !Number.isFinite(point[1]))) continue;

        const style = classification.classify(syntaxSegmentValues[segment.id]);
        const points = coordinates.map(([easting, northing]) => {
          const [x, y] = epsg28992ToLocalMetric(easting, northing);
          return new THREE.Vector3(x, y, bandHeight);
        });

        if (style.isUncomputed) {
          const geometry = new THREE.BufferGeometry().setFromPoints(points);
          const material = new THREE.LineDashedMaterial({
            color: style.strokeColor,
            dashSize: style.lineDash[0] ?? 4,
            gapSize: style.lineDash[1] ?? 4,
            depthWrite: false,
          });
          const line = new THREE.Line(geometry, material);
          line.computeLineDistances();
          line.name = `space-syntax-uncomputed:${segment.id}`;
          group.add(line);
          continue;
        }

        const vertices = ribbonPositionsByColor.get(style.strokeColor) ?? [];
        for (let index = 1; index < points.length; index += 1) {
          const start = points[index - 1];
          const end = points[index];
          const dx = end.x - start.x;
          const dy = end.y - start.y;
          const length = Math.hypot(dx, dy);
          if (length <= 0) continue;
          const offsetX = -(dy / length) * bandHalfWidth;
          const offsetY = (dx / length) * bandHalfWidth;
          const leftStart = [start.x + offsetX, start.y + offsetY, bandHeight];
          const rightStart = [start.x - offsetX, start.y - offsetY, bandHeight];
          const leftEnd = [end.x + offsetX, end.y + offsetY, bandHeight];
          const rightEnd = [end.x - offsetX, end.y - offsetY, bandHeight];
          vertices.push(...leftStart, ...rightStart, ...leftEnd, ...rightStart, ...rightEnd, ...leftEnd);
        }
        ribbonPositionsByColor.set(style.strokeColor, vertices);
      }
    }

    for (const [color, positions] of ribbonPositionsByColor) {
      if (positions.length === 0) continue;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      const material = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, depthWrite: false });
      const ribbon = new THREE.Mesh(geometry, material);
      ribbon.name = `space-syntax-quintile:${color}`;
      group.add(ribbon);
    }

    for (const [color, positions] of boundaryPositionsByColor) {
      if (positions.length === 0) continue;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      const material = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, depthWrite: false, transparent: true, opacity: 0.45 });
      const ribbon = new THREE.Mesh(geometry, material);
      ribbon.name = `space-syntax-boundary:${color}`;
      group.add(ribbon);
    }

    scene.add(group);
    if (containerRef.current) {
      containerRef.current.dataset.syntaxView = syntaxContextData?.comparison_view ?? 'context';
      containerRef.current.dataset.syntaxMetric = syntaxMetric ?? 'nain';
      containerRef.current.dataset.syntaxObjectCount = String(group.children.length);
    }
    return () => {
      scene.remove(group);
      group.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) object.geometry.dispose();
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
    };
  }, [syntaxSegments, syntaxSegmentValues, syntaxContextData, syntaxMetric, isSyntaxOverlayVisible, sceneRevision, buildings, studyAreaGeometry]);

  useEffect(() => {
    const selectedIds = new Set(selectedFeatureIds);
    if (selectedFeatureId) selectedIds.add(selectedFeatureId);

    for (const [featureId, material] of buildingMaterialMapRef.current) {
      const baseColor = buildingBaseColorMapRef.current.get(featureId);
      if (baseColor !== undefined) material.color.set(selectedIds.has(featureId) ? 0xfacc15 : baseColor);
    }
    for (const [featureId, material] of roadMaterialMapRef.current) {
      material.color.set(selectedIds.has(featureId) ? '#facc15' : (segments.find(s => s.id === featureId) as Segment & { fabric_color?: string })?.fabric_color ?? proposalRoadStyle(segments.find(s => s.id === featureId) ?? {}).color);
    }
  }, [selectedFeatureId, selectedFeatureIds, buildings, segments]);

  const exportCurrentFigure = async () => {
    const renderer = rendererRef.current;
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    if (!renderer || !scene || !camera) {
      setFigureExportMessage(t('The 3D viewport is not ready for export.'));
      return;
    }
    if (!figureExportReady || !canExportSchematic3DFigure(figureContext)) {
      setFigureExportMessage(t(figureContext.hasUnsavedChanges
        ? 'Save or discard local design changes before exporting.'
        : 'Save and reload a workspace for the active StudyArea before exporting.'));
      return;
    }

    setIsExportingFigure(true);
    setFigureExportMessage(t('Preparing PNG…'));
    try {
      const selectedIds = [...new Set([...selectedFeatureIds, ...(selectedFeatureId ? [selectedFeatureId] : [])])];
      const metadata = buildSchematic3DFigureMetadata({
        ...figureContext,
        selectedFeatureIds: selectedIds,
        renderedRoadCount: renderedRoadSegmentCountRef.current,
        exportedAtUtc: new Date().toISOString(),
      });
      renderer.render(scene, camera);
      const renderedView = renderer.domElement.toDataURL('image/png');
      const sceneImage = await new Promise<HTMLImageElement>((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error('The current 3D viewport could not be captured.'));
        image.src = renderedView;
      });
      const figure = composeSchematic3DFigure(sceneImage, metadata);
      const blob = await new Promise<Blob>((resolve, reject) => {
        figure.toBlob((value) => value ? resolve(value) : reject(new Error('PNG encoding failed.')), 'image/png');
      });
      const downloadUrl = URL.createObjectURL(blob);
      const download = document.createElement('a');
      download.href = downloadUrl;
      const safeStudyAreaId = metadata.studyArea.id.replace(/[^a-zA-Z0-9-]/g, '-');
      download.download = `rotterdam-m4h-${metadata.figureVersion}-workspace-r${metadata.workspace.revision}-${safeStudyAreaId}.png`;
      document.body.appendChild(download);
      download.click();
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1_000);
      setFigureExportMessage(t('PNG downloaded · {workspace} r{revision} · {studyArea} (record rev {studyAreaRevision}).', {
        workspace: metadata.workspace.id,
        revision: metadata.workspace.revision,
        studyArea: metadata.studyArea.id,
        studyAreaRevision: metadata.studyArea.revision,
      }));
    } catch (error) {
      setFigureExportMessage(error instanceof Error ? t('PNG export failed: {error}', { error: error.message }) : t('PNG export failed.'));
    } finally {
      setIsExportingFigure(false);
    }
  };

  const schematicExportDisabledReason = figureContext.hasUnsavedChanges
    ? 'Save or discard local design changes before exporting.'
    : figureContext.workspace?.status === 'STALE'
      ? 'Reload the current server workspace before exporting.'
      : isExportingFigure
        ? 'The 3D figure is being prepared.'
      : 'Save and reload a workspace for the active StudyArea before exporting.';
  const schematicExportDisabled = !figureExportReady
    || !canExportSchematic3DFigure(figureContext)
    || isExportingFigure;

  const start3DMeasurement = () => {
    measurementPoints3DRef.current = [];
    isMeasuring3DRef.current = true;
    setMeasurementPoints3D([]);
    setMeasurement3DResult(null);
    setMeasurement3DError('');
    setIsMeasuring3D(true);
  };

  const clear3DMeasurement = () => {
    isMeasuring3DRef.current = false;
    measurementPoints3DRef.current = [];
    setIsMeasuring3D(false);
    setMeasurementPoints3D([]);
    setMeasurement3DResult(null);
    setMeasurement3DError('');
  };

  const measurementLabel = isMeasuring3D
    ? 'Cancel 3D measurement'
    : measurement3DResult
      ? 'Clear 3D measurement'
      : 'Measure 3D distance and height';

  const contextAttribution = [
    t('Surrounding context · OSM · ODbL · © OpenStreetMap contributors'),
    surroundingContext.data?.metadata['3dbag']?.used
      ? t('3D BAG {version} · © 3DBAG by tudelft3d and 3DGI · CC BY 4.0', { version: String(surroundingContext.data.metadata['3dbag']?.data_version ?? 'height table') })
      : t('3D BAG height data unavailable · only OSM heights or flat footprints shown.'),
  ].join(' · ');

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      <div ref={containerRef} id="viewport-3d-container" style={{ width: '100%', height: '100%' }} />

      <div
        role="toolbar"
        aria-label={labels.viewToolbar}
        data-testid="viewport3d-navigation-toolbar"
        className="viewport3d-toolbar"
      >
        {(['top', 'front', 'right', 'perspective'] as const).map((preset) => (
          <button
            key={preset}
            type="button"
            aria-label={labels[preset]}
            title={t(labels[preset])}
            onClick={() => navigationApiRef.current?.setPreset(preset)}
            className="viewport3d-toolbar__button"
          >
            {preset === 'top' ? <ArrowUp size={15} aria-hidden="true" />
              : preset === 'front' || preset === 'right' ? <ArrowRight size={15} aria-hidden="true" />
                : <Compass size={15} aria-hidden="true" />}
          </button>
        ))}
        <button
          type="button"
          aria-label={labels.zoomExtents}
          title={t(labels.zoomExtents)}
          onClick={() => navigationApiRef.current?.zoomExtents()}
          className="viewport3d-toolbar__button"
        >
          <Expand size={15} aria-hidden="true" />
        </button>
        {syntaxSegments.length > 0 && (
          <button
            type="button"
            aria-label={`${labels.syntax}: ${isSyntaxOverlayVisible ? labels.visible : labels.hidden}`}
            title={`${t(labels.syntax)}: ${t(isSyntaxOverlayVisible ? labels.visible : labels.hidden)}`}
            aria-pressed={isSyntaxOverlayVisible}
            onClick={() => {
              const nextVisibility = !isSyntaxOverlayVisible;
              if (controlledSyntaxOverlayVisible === undefined) setLocalSyntaxOverlayVisible(nextVisibility);
              onSyntaxOverlayVisibilityChange?.(nextVisibility);
            }}
            className="viewport3d-toolbar__button"
          >
            <Layers size={15} aria-hidden="true" />
          </button>
        )}
        <span className="viewport3d-toolbar__divider" aria-hidden="true" />
        <button
          type="button"
          aria-label={t(measurementLabel)}
          title={t(measurementLabel)}
          aria-pressed={isMeasuring3D}
          onClick={isMeasuring3D || measurement3DResult ? clear3DMeasurement : start3DMeasurement}
          className="viewport3d-toolbar__button"
          data-testid="viewport3d-measure-button"
        >
          <Ruler size={15} aria-hidden="true" />
        </button>
        <button
          type="button"
          id="btn-export-3d-figure"
          aria-label={t('Export 3D figure (PNG)')}
          title={t(schematicExportDisabled ? schematicExportDisabledReason : 'Export 3D figure (PNG)')}
          aria-describedby="status-3d-figure-export"
          disabled={schematicExportDisabled}
          onClick={exportCurrentFigure}
          className="viewport3d-toolbar__button"
          data-testid="viewport3d-export-button"
        >
          {isExportingFigure ? <span className="viewport3d-toolbar__spinner" aria-hidden="true">…</span> : <Download size={15} aria-hidden="true" />}
        </button>
      </div>

      {isSyntaxOverlayVisible && (
        <details
          aria-label={labels.syntaxLegend}
          data-testid="viewport3d-syntax-legend"
          className="viewport3d-corner-details viewport3d-syntax-legend"
        >
          <summary title={t(labels.syntaxLegend)}>
            <Layers size={13} aria-hidden="true" />
            <span>{t('Space Syntax')}</span>
            {syntaxContextData && syntaxContextStatus === 'success' && (
              <span className="badge-exploratory" data-formal-result={syntaxContextData.readiness ? 'false' : undefined} style={{ marginLeft: '6px', fontSize: '9px', background: '#3b82f6', color: '#fff', padding: '1px 4px', borderRadius: '2px', fontWeight: 'bold' }}>
                <StatusBadge status={syntaxContextBadgeStatus(syntaxContextData)} language={language} />
              </span>
            )}
            {syntaxContextData?.readiness && syntaxContextData.readiness.formal_result !== true && syntaxContextStatus === 'success' && (
              <span data-testid="syntax-context-not-formal">{t('Not a formal result')}</span>
            )}
          </summary>
          <div className="viewport3d-corner-details__body">
            {syntaxContextData && syntaxContextStatus === 'success' && syntaxContextData.comparison_view !== 'diff' && syntaxContextData.legend_breaks && syntaxContextData.legend_breaks[syntaxMetric ?? 'nain'] ? (
              <>
                <div style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '4px', display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  <span>{t('Scale: {scale}', { scale: syntaxMode === 'pedestrian' ? t('Walk 800 m') : syntaxMode === 'bicycle' ? t('Bicycle 2 km') : t('Car 10 km') })}</span>
                  <span>{t('Radius: {radius} m', { radius: syntaxContextData.radius_m })}</span>
                  <span>{t('Range: {range} km', { range: ((syntaxContextData?.distance_m ? syntaxContextData.distance_m / 1000 : syntaxDistanceKm)).toFixed(1) })}</span>
                  <span>{t('Metric: {metric}', { metric: syntaxMetric === 'nain' ? t('Integration (NAIN)') : t('Choice (NACH)') })}</span>
                </div>
                {buildClassificationFromBreaks(syntaxContextData.legend_breaks[syntaxMetric ?? 'nain']).ranges.map((entry, index) => (
                  <span key={`${entry.label}-${index}`} className="viewport3d-syntax-legend__entry">
                    <span aria-hidden="true" style={{ background: entry.color }} />
                    <span>{t(entry.label)}: {entry.min.toFixed(2)} - {entry.max.toFixed(2)}</span>
                  </span>
                ))}
                <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '4px', borderTop: '1px solid rgba(148, 163, 184, 0.2)', paddingTop: '4px' }}>
                  {t('Faint dashed line = less than one radius to network boundary; boundary effect possible')}
                </div>
              </>
            ) : (
              <>
                {syntaxContextStatus === 'error' && (
                  <div style={{ color: '#f87171', fontSize: '10px', marginBottom: '4px' }}>
                    {t('Surrounding Space Syntax unavailable; falling back to site-only layer.')}
                    {syntaxContextError ? ` (${t(syntaxContextError)})` : ''}
                  </div>
                )}
                {syntaxLegend.map((entry, index) => (
                  <span key={`${entry.label}-${index}`} className="viewport3d-syntax-legend__entry">
                    <span aria-hidden="true" style={{ background: entry.color }} />
                    <span>{t(entry.label)}</span>
                  </span>
                ))}
              </>
            )}
          </div>
        </details>
      )}

      <details
        data-testid="viewport3d-information"
        className="viewport3d-info"
      >
        <summary aria-label={t('3D preview information')} title={t('3D preview information')}><Info size={14} aria-hidden="true" /><span aria-hidden="true">i</span></summary>
        <div className="viewport3d-info__body">
          <strong>{t('Schematic 3D volume preview')}</strong>
          <p>{t('Building extrusions use recorded feature height or scenario assumptions. UNKNOWN assumptions use the explicit 3 m/storey display default; heights are not evidence.')}</p>
          <p>{t('Building heights: 3D BAG within 500 m when available; otherwise OSM height, OSM levels × 3 m/storey (display assumption), or flat footprint.')}</p>
          <p>{contextAttribution}</p>
          {unknownBuildingHeightCount > 0 && <p>{t('{count} building heights UNKNOWN · display fallback 3 m/storey.', { count: unknownBuildingHeightCount })}</p>}
          {selectedFeatureId && (
            <div id="selected-feature-3d" role="status" aria-live="polite">
              {t('Selected source feature:')} <code>{selectedFeatureId}</code>
              {selectedFeatureIds.length > 1 ? ` · ${selectedFeatureIds.length} ${t('selected')}` : ''}
              <MassingIntent
                intent={buildings.find(b => b.id === selectedFeatureId)?.properties?.design_intent as MassingIntentRecord | undefined}
                height={buildings.find(b => b.id === selectedFeatureId)?.properties?.height_m as number | undefined}
                active={buildings.find(b => b.id === selectedFeatureId)?.properties?.active_frontage as boolean | undefined}
              />
            </div>
          )}
        </div>
      </details>

      {(isMeasuring3D || measurement3DResult || measurement3DError) && (
        <div className="viewport3d-measure-status" role="status" aria-label={t('3D measurement status')}>
          {isMeasuring3D && t('Schematic 3D only · click two visible surfaces ({points}/2 points). Heights are display estimates, not evidence.', { points: measurementPoints3D.length })}
          {measurement3DResult && (
            <>
              <span>{t('Horizontal: {value} m', { value: format3DValue(measurement3DResult.horizontalDistance.value) })}</span>
              <span>{t('Elevation difference: {value} m', { value: format3DValue(measurement3DResult.verticalDelta.signed) })}</span>
              <span>{t('Slant: {value} m', { value: format3DValue(measurement3DResult.slantDistance.value) })}</span>
              <span>{t('Reference: schematic 3D surfaces · not EvidenceResult')}</span>
            </>
          )}
          {measurement3DError && <span role="alert">{t(measurement3DError)}</span>}
        </div>
      )}

      <div
        data-testid="surrounding-context-3d-attribution"
        aria-label={t('Surrounding context attribution')}
        className="viewport3d-attribution"
        title={contextAttribution}
      >
        <span>{contextAttribution}</span>
      </div>
      <span id="status-3d-figure-export" role="status" aria-live="polite" className={figureExportMessage ? 'viewport3d-export-status' : 'viewport3d-visually-hidden'}>
        {t(figureExportMessage)}
      </span>
    </div>
  );
};

function format3DValue(value: number): string {
  return value.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
