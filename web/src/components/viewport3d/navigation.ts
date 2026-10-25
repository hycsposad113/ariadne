export type NavigationAction = 'orbit' | 'pan' | 'zoom' | 'none';

export type ViewportNavigationEvent =
  | {
      type: 'wheel';
      deltaMode: number;
      ctrlKey: boolean;
      shiftKey: boolean;
      deltaX?: number;
      deltaY?: number;
      /** Legacy WebKit/Blink field; mouse wheels report multiples of 120. */
      wheelDeltaY?: number;
    }
  | { type: 'pointer'; button: number; ctrlKey: boolean; shiftKey: boolean };

export function getNavigationAction(event: ViewportNavigationEvent): NavigationAction {
  if (event.type === 'wheel') {
    if (event.ctrlKey) return 'zoom';
    if (event.shiftKey) return 'pan';
    if (event.deltaMode !== 0) return 'zoom';
    if (isLikelyMouseWheel(event)) return 'zoom';
    return 'orbit';
  }

  if (event.shiftKey && (event.button === 0 || event.button === 2)) return 'pan';
  if (event.button === 2 && event.ctrlKey) return 'zoom';
  if (event.button === 2) return 'orbit';
  return 'none';
}

export type Navigation2DAction = 'pan' | 'zoom' | 'none';

/** Rhino Top viewport mapping, kept separate from the 3D navigation contract. */
export function get2DNavigationAction(event: ViewportNavigationEvent): Navigation2DAction {
  if (event.type === 'wheel') {
    if (event.ctrlKey) return 'zoom';
    if (event.shiftKey) return 'pan';
    if (event.deltaMode !== 0 || isLikelyMouseWheel(event)) return 'zoom';
    return 'pan';
  }

  if (event.button === 2 && event.ctrlKey) return 'zoom';
  if (event.shiftKey && (event.button === 0 || event.button === 2)) return 'pan';
  if (event.button === 2) return 'pan';
  return 'none';
}

/**
 * macOS browsers report both trackpads and mouse wheels in pixel mode, so deltaMode
 * alone cannot separate them. Mouse wheels move in discrete notches: wheelDeltaY is a
 * multiple of 120, there is no horizontal component and deltaY is a large integer.
 * Trackpad two-finger scrolls stream small, often fractional deltas with deltaX drift.
 */
export function isLikelyMouseWheel(event: { deltaX?: number; deltaY?: number; wheelDeltaY?: number }): boolean {
  const deltaX = event.deltaX ?? 0;
  const deltaY = event.deltaY ?? 0;
  if (deltaX !== 0 || deltaY === 0) return false;
  const legacy = event.wheelDeltaY;
  if (typeof legacy === 'number' && legacy !== 0) {
    return Math.abs(legacy) % 120 === 0;
  }
  return Number.isInteger(deltaY) && Math.abs(deltaY) >= 50;
}
