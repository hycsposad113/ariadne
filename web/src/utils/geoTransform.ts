/**
 * Deterministic Coordinate Transformation: EPSG:28992 (Amersfoort / RD New) <-> Local Render Canvas / 3D.
 * 
 * Formal Anchor:
 * Rotterdam M4H Pilot Center: (89100.0, 435900.0)
 * Forward: Local_X = X_rd - Origin_X; Local_Y = Y_rd - Origin_Y
 * Inverse: X_rd = Local_X + Origin_X; Y_rd = Local_Y + Origin_Y
 */

export interface RenderTransform {
  originX: number; // EPSG:28992 Easting anchor (meters)
  originY: number; // EPSG:28992 Northing anchor (meters)
  zoom: number;    // Canvas pixels per meter
  panX: number;    // Canvas pan offset X (pixels)
  panY: number;    // Canvas pan offset Y (pixels)
}

export const DEFAULT_TRANSFORM: RenderTransform = {
  originX: 89100.0,
  originY: 435900.0,
  zoom: 0.8,
  panX: 400.0,
  panY: 350.0,
};

/**
 * Convert EPSG:28992 coordinate to local centered metric space (meters).
 */
export function epsg28992ToLocalMetric(x: number, y: number, originX: number = DEFAULT_TRANSFORM.originX, originY: number = DEFAULT_TRANSFORM.originY): [number, number] {
  return [x - originX, y - originY];
}

/**
 * Convert local centered metric space (meters) back to EPSG:28992.
 */
export function localMetricToEpsg28992(lx: number, ly: number, originX: number = DEFAULT_TRANSFORM.originX, originY: number = DEFAULT_TRANSFORM.originY): [number, number] {
  return [lx + originX, ly + originY];
}

/**
 * Convert EPSG:28992 coordinate directly to 2D Canvas screen pixels.
 * Note: Screen Y increases downward, so Northing is inverted.
 */
export function epsg28992ToScreen(x: number, y: number, transform: RenderTransform): [number, number] {
  const lx = x - transform.originX;
  const ly = y - transform.originY;
  const px = transform.panX + lx * transform.zoom;
  const py = transform.panY - ly * transform.zoom; // Invert Y for canvas
  return [px, py];
}

/**
 * Convert 2D Canvas screen pixels back to authoritative EPSG:28992 coordinates.
 */
export function screenToEpsg28992(px: number, py: number, transform: RenderTransform): [number, number] {
  const lx = (px - transform.panX) / transform.zoom;
  const ly = (transform.panY - py) / transform.zoom; // Re-invert Y
  const x = lx + transform.originX;
  const y = ly + transform.originY;
  return [x, y];
}

/** Pan the 2D map in the inverse direction of native trackpad wheel deltas. */
export function panByWheelDelta(transform: RenderTransform, deltaX: number, deltaY: number): RenderTransform {
  return {
    ...transform,
    panX: transform.panX - deltaX,
    panY: transform.panY - deltaY,
  };
}

/** Zoom around a screen point while keeping its EPSG:28992 coordinate fixed. */
export function zoomAtPoint(
  transform: RenderTransform,
  factor: number,
  px: number,
  py: number,
): RenderTransform {
  const zoom = Math.max(0.2, Math.min(6.0, transform.zoom * factor));
  const ratio = zoom / transform.zoom;
  return {
    ...transform,
    zoom,
    panX: px - (px - transform.panX) * ratio,
    panY: py + (transform.panY - py) * ratio,
  };
}

/**
 * Color ramp for Space Syntax values: Blue (low) -> Cyan -> Yellow -> Orange -> Red (high).
 */
export function getSyntaxColor(val: number, min: number, max: number): string {
  if (val === undefined || isNaN(val) || max <= min) {
    return '#64748b';
  }
  const norm = Math.max(0, Math.min(1, (val - min) / (max - min)));
  const stops = [
    { t: 0.0, r: 44, g: 123, b: 182 },
    { t: 0.25, r: 171, g: 217, b: 233 },
    { t: 0.5, r: 255, g: 255, b: 191 },
    { t: 0.75, r: 253, g: 174, b: 97 },
    { t: 1.0, r: 215, g: 25, b: 28 },
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const s0 = stops[i];
    const s1 = stops[i + 1];
    if (norm >= s0.t && norm <= s1.t) {
      const f = (norm - s0.t) / (s1.t - s0.t);
      const r = Math.round(s0.r + f * (s1.r - s0.r));
      const g = Math.round(s0.g + f * (s1.g - s0.g));
      const b = Math.round(s0.b + f * (s1.b - s0.b));
      return `rgb(${r}, ${g}, ${b})`;
    }
  }
  return 'rgb(215, 25, 28)';
}
