/**
 * Figure camera and layout presets for reproducible urban design figures (W6 precursor lane F4).
 *
 * Provides:
 * 1. Isometric preset (Three.js OrthographicCamera, azimuth 45°, true elevation 35.264°)
 * 2. Plan preset (Top-down Orthographic, with scale bar and north arrow via mapFigure.ts)
 * 3. Perspective preset (Three.js PerspectiveCamera, fixed FOV/viewpoint, explicitly NO 2D scale bar)
 * 4. Framing calculation from 3D bounding box ensuring identical scale across shared proposals
 * 5. Figure stamp metadata with proposal revision, git commit, date, and visible status markers (DRAFT, STALE, ILLUSTRATIVE)
 */

import { selectMapScaleBar } from './mapFigure';

export type FigureStampStatus = 'DRAFT' | 'STALE' | 'ILLUSTRATIVE' | 'REVIEWED' | 'APPROVED';
export type FigurePresetKind = 'ISOMETRIC' | 'PERSPECTIVE' | 'PLAN';

export interface BoundingBox3D {
  minX: number;
  minY: number;
  minZ: number;
  maxX: number;
  maxY: number;
  maxZ: number;
}

export interface FigureResolution {
  width: number;
  height: number;
  dpi?: number;
}

export const STANDARD_RESOLUTIONS: Record<string, FigureResolution> = {
  FHD_1080P: { width: 1920, height: 1080, dpi: 96 },
  QHD_1440P: { width: 2560, height: 1440, dpi: 96 },
  UHD_4K: { width: 3840, height: 2160, dpi: 150 },
  A4_LANDSCAPE_300DPI: { width: 3508, height: 2480, dpi: 300 },
};

export interface OrthographicCameraPreset {
  cameraType: 'orthographic';
  position: [number, number, number];
  target: [number, number, number];
  up: [number, number, number];
  frustum: {
    left: number;
    right: number;
    top: number;
    bottom: number;
    near: number;
    far: number;
  };
  zoom: number;
  azimuthDeg: number;
  elevationDeg: number;
  pixelsPerMeter: number;
}

export interface PerspectiveCameraPreset {
  cameraType: 'perspective';
  position: [number, number, number];
  target: [number, number, number];
  up: [number, number, number];
  fov: number; // Vertical field of view in degrees
  aspect: number;
  near: number;
  far: number;
}

export interface ScaleBarSpec {
  distanceMeters: number;
  lengthPixels: number;
  metersPerPixel: number;
  unit: 'm';
}

export interface NorthArrowSpec {
  enabled: boolean;
  angleDegrees: number;
  label: 'N';
}

export interface FigureLegendItem {
  label: string;
  color: string;
}

export interface FigureMetadataStamp {
  figureVersion: 'w6-figure-preset-v1';
  presetKind: FigurePresetKind;
  proposalRevision: string | number;
  gitCommit: string;
  dateUtc: string;
  status: FigureStampStatus;
  resolution: FigureResolution;
  scaleBar: ScaleBarSpec | null;
  northArrow: NorthArrowSpec | null;
  legend: FigureLegendItem[];
  framingBBox: BoundingBox3D;
  camera: OrthographicCameraPreset | PerspectiveCameraPreset;
}

/** True isometric elevation angle: arcsin(1 / sqrt(3)) ≈ 35.26438968° */
export const TRUE_ISOMETRIC_ELEVATION_DEG = Math.asin(1 / Math.sqrt(3)) * (180 / Math.PI);
export const TRUE_ISOMETRIC_AZIMUTH_DEG = 45.0;

/**
 * Calculate camera framing bounds for an orthographic view of a 3D bounding box.
 */
export function calculateOrthographicFraming(
  bbox: BoundingBox3D,
  resolution: FigureResolution,
  marginFactor = 1.15,
): {
  center: [number, number, number];
  frustumWidth: number;
  frustumHeight: number;
  pixelsPerMeter: number;
} {
  const dx = Math.max(1, bbox.maxX - bbox.minX);
  const dy = Math.max(1, bbox.maxY - bbox.minY);
  const dz = Math.max(1, bbox.maxZ - bbox.minZ);

  const cx = (bbox.minX + bbox.maxX) / 2;
  const cy = (bbox.minY + bbox.maxY) / 2;
  const cz = (bbox.minZ + bbox.maxZ) / 2;

  // Maximum spatial dimension on ground plane or diagonal
  const maxSpan = Math.max(dx, dy, Math.hypot(dx, dy)) * marginFactor;
  const aspect = resolution.width / resolution.height;

  let frustumWidth: number;
  let frustumHeight: number;

  if (aspect >= 1.0) {
    frustumHeight = Math.max(maxSpan, dz * 2);
    frustumWidth = frustumHeight * aspect;
  } else {
    frustumWidth = Math.max(maxSpan, dz * 2);
    frustumHeight = frustumWidth / aspect;
  }

  const pixelsPerMeter = resolution.width / frustumWidth;

  return {
    center: [cx, cy, cz],
    frustumWidth,
    frustumHeight,
    pixelsPerMeter,
  };
}

/**
 * Build an isometric orthographic camera preset.
 * Azimuth: 45°, Elevation: 35.264° (true isometric).
 */
export function buildIsometricCameraPreset(
  bbox: BoundingBox3D,
  resolution: FigureResolution,
  marginFactor = 1.15,
): OrthographicCameraPreset {
  const framing = calculateOrthographicFraming(bbox, resolution, marginFactor);
  const [cx, cy, cz] = framing.center;

  // Distance along isometric direction (equal projection along X, -Y, Z)
  const diagonal = Math.hypot(
    bbox.maxX - bbox.minX,
    bbox.maxY - bbox.minY,
    bbox.maxZ - bbox.minZ,
  );
  const distance = Math.max(500, diagonal * 2);

  // Direction vector: azimuth 45° (from SE/SW quadrant), elevation 35.264°
  // In our local metric system: +X is East, +Y is North, +Z is Up
  // Camera viewing towards center from (+X, -Y, +Z):
  const cosElev = Math.cos(TRUE_ISOMETRIC_ELEVATION_DEG * (Math.PI / 180));
  const sinElev = Math.sin(TRUE_ISOMETRIC_ELEVATION_DEG * (Math.PI / 180));
  const radAzimuth = TRUE_ISOMETRIC_AZIMUTH_DEG * (Math.PI / 180);

  const dirX = Math.sin(radAzimuth) * cosElev; // 1 / sqrt(3)
  const dirY = -Math.cos(radAzimuth) * cosElev; // -1 / sqrt(3)
  const dirZ = sinElev; // 1 / sqrt(3)

  const posX = cx + dirX * distance;
  const posY = cy + dirY * distance;
  const posZ = cz + dirZ * distance;

  const halfW = framing.frustumWidth / 2;
  const halfH = framing.frustumHeight / 2;

  return {
    cameraType: 'orthographic',
    position: [posX, posY, posZ],
    target: [cx, cy, cz],
    up: [0, 0, 1], // Z-up
    frustum: {
      left: -halfW,
      right: halfW,
      top: halfH,
      bottom: -halfH,
      near: 1,
      far: distance * 4,
    },
    zoom: 1.0,
    azimuthDeg: TRUE_ISOMETRIC_AZIMUTH_DEG,
    elevationDeg: Number(TRUE_ISOMETRIC_ELEVATION_DEG.toFixed(3)),
    pixelsPerMeter: framing.pixelsPerMeter,
  };
}

/**
 * Build a top-down Plan orthographic camera preset.
 * Elevation: 90° (looking straight down along -Z).
 * Up: [0, 1, 0] (North is up).
 */
export function buildPlanCameraPreset(
  bbox: BoundingBox3D,
  resolution: FigureResolution,
  marginFactor = 1.15,
): OrthographicCameraPreset {
  const framing = calculateOrthographicFraming(bbox, resolution, marginFactor);
  const [cx, cy, cz] = framing.center;

  const diagonal = Math.hypot(bbox.maxX - bbox.minX, bbox.maxY - bbox.minY);
  const distance = Math.max(500, diagonal * 2);

  const halfW = framing.frustumWidth / 2;
  const halfH = framing.frustumHeight / 2;

  return {
    cameraType: 'orthographic',
    position: [cx, cy, cz + distance],
    target: [cx, cy, cz],
    up: [0, 1, 0], // North is +Y
    frustum: {
      left: -halfW,
      right: halfW,
      top: halfH,
      bottom: -halfH,
      near: 1,
      far: distance * 4,
    },
    zoom: 1.0,
    azimuthDeg: 0.0,
    elevationDeg: 90.0,
    pixelsPerMeter: framing.pixelsPerMeter,
  };
}

/**
 * Build a fixed Perspective camera preset.
 * FOV: 45° vertical field of view.
 * Looking from south towards the center.
 */
export function buildPerspectiveCameraPreset(
  bbox: BoundingBox3D,
  resolution: FigureResolution,
  fov = 45.0,
  marginFactor = 1.2,
): PerspectiveCameraPreset {
  const dx = Math.max(1, bbox.maxX - bbox.minX);
  const dy = Math.max(1, bbox.maxY - bbox.minY);
  const dz = Math.max(1, bbox.maxZ - bbox.minZ);

  const cx = (bbox.minX + bbox.maxX) / 2;
  const cy = (bbox.minY + bbox.maxY) / 2;
  const cz = (bbox.minZ + bbox.maxZ) / 2;

  const aspect = resolution.width / resolution.height;
  const fovRad = fov * (Math.PI / 180);

  // Distance required to enclose horizontal and vertical extent
  const requiredDist = (Math.max(dx, dy, dz) * marginFactor) / (2 * Math.tan(fovRad / 2));
  const distance = Math.max(400, requiredDist * 1.5);

  // Positioned south of center (+Z up)
  const posX = cx;
  const posY = cy - distance * 0.85;
  const posZ = cz + distance * 0.55;

  return {
    cameraType: 'perspective',
    position: [posX, posY, posZ],
    target: [cx, cy, cz],
    up: [0, 0, 1],
    fov,
    aspect,
    near: 1.0,
    far: distance * 5,
  };
}

export interface FigureStampInput {
  presetKind: FigurePresetKind;
  bbox: BoundingBox3D;
  resolution?: FigureResolution;
  proposalRevision: string | number;
  gitCommit: string;
  dateUtc?: string;
  status: FigureStampStatus;
  legend?: FigureLegendItem[];
}

/**
 * Create figure stamp metadata linking camera, framing, scale bar, and provenance.
 *
 * Rules:
 * - PLAN: includes scale bar (via mapFigure.selectMapScaleBar) and North arrow
 * - ISOMETRIC: fixed metric scale, optional scale bar
 * - PERSPECTIVE: explicitly NO 2D scale bar (scaleBar is null)
 */
export function createFigureMetadataStamp(input: FigureStampInput): FigureMetadataStamp {
  const resolution = input.resolution ?? STANDARD_RESOLUTIONS.FHD_1080P;
  const dateUtc = input.dateUtc ?? new Date().toISOString();
  const legend = input.legend ?? [
    { label: 'Site boundary', color: '#38bdf8' },
    { label: 'Building context', color: '#64748b' },
  ];

  let camera: OrthographicCameraPreset | PerspectiveCameraPreset;
  let scaleBar: ScaleBarSpec | null = null;
  let northArrow: NorthArrowSpec | null = null;

  if (input.presetKind === 'ISOMETRIC') {
    camera = buildIsometricCameraPreset(input.bbox, resolution);
    // Isometric preserves fixed metric scale across the projection plane
    const sceneWidth = camera.frustum.right - camera.frustum.left;
    scaleBar = selectMapScaleBar({
      zoom: camera.zoom,
      canvasWidth: resolution.width,
      sceneWidth,
    });
    northArrow = { enabled: true, angleDegrees: 45.0, label: 'N' };
  } else if (input.presetKind === 'PLAN') {
    camera = buildPlanCameraPreset(input.bbox, resolution);
    const sceneWidth = camera.frustum.right - camera.frustum.left;
    scaleBar = selectMapScaleBar({
      zoom: camera.zoom,
      canvasWidth: resolution.width,
      sceneWidth,
    });
    northArrow = { enabled: true, angleDegrees: 0.0, label: 'N' };
  } else {
    // PERSPECTIVE: Perspective projections distort distance; a single flat scale bar is strictly disallowed
    camera = buildPerspectiveCameraPreset(input.bbox, resolution);
    scaleBar = null;
    northArrow = null;
  }

  return {
    figureVersion: 'w6-figure-preset-v1',
    presetKind: input.presetKind,
    proposalRevision: input.proposalRevision,
    gitCommit: input.gitCommit,
    dateUtc,
    status: input.status,
    resolution,
    scaleBar,
    northArrow,
    legend,
    framingBBox: input.bbox,
    camera,
  };
}
