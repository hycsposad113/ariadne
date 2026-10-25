import { describe, expect, it } from 'vitest';
import { get2DNavigationAction, getNavigationAction } from './navigation';

describe('Rhino viewport navigation action mapping', () => {
  it.each([
    ['two-finger pixel scroll without modifiers orbits', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: false }, 'orbit'],
    ['trackpad fractional scroll with x drift orbits', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: false, deltaX: 1.5, deltaY: 3.25, wheelDeltaY: -9 }, 'orbit'],
    ['macOS pixel-mode mouse wheel notch zooms', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: false, deltaX: 0, deltaY: 100, wheelDeltaY: -120 }, 'zoom'],
    ['mouse wheel without legacy field but large integer notch zooms', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: false, deltaX: 0, deltaY: 100 }, 'zoom'],
    ['Shift plus mouse wheel still pans', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: true, deltaX: 0, deltaY: 100, wheelDeltaY: -120 }, 'pan'],
    ['Shift plus two-finger scroll pans', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: true }, 'pan'],
    ['trackpad pinch with Ctrl zooms', { type: 'wheel', deltaMode: 0, ctrlKey: true, shiftKey: false }, 'zoom'],
    ['line-mode mouse wheel zooms without Ctrl', { type: 'wheel', deltaMode: 1, ctrlKey: false, shiftKey: false }, 'zoom'],
    ['right-button drag orbits', { type: 'pointer', button: 2, ctrlKey: false, shiftKey: false }, 'orbit'],
    ['Shift plus left-button drag pans', { type: 'pointer', button: 0, ctrlKey: false, shiftKey: true }, 'pan'],
    ['Shift plus right-button drag pans', { type: 'pointer', button: 2, ctrlKey: false, shiftKey: true }, 'pan'],
    ['Ctrl plus right-button drag zooms', { type: 'pointer', button: 2, ctrlKey: true, shiftKey: false }, 'zoom'],
    ['plain left-button drag remains available for selection', { type: 'pointer', button: 0, ctrlKey: false, shiftKey: false }, 'none'],
    ['middle-button drag has no navigation action', { type: 'pointer', button: 1, ctrlKey: false, shiftKey: false }, 'none'],
  ] as const)('%s', (_description, event, expected) => {
    expect(getNavigationAction(event)).toBe(expected);
  });
});

describe('2D Rhino Top viewport navigation action mapping', () => {
  it.each([
    ['Ctrl trackpad pinch zooms', { type: 'wheel', deltaMode: 0, ctrlKey: true, shiftKey: false }, 'zoom'],
    ['Shift trackpad scroll pans', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: true }, 'pan'],
    ['trackpad two-finger scroll pans', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: false, deltaX: 3, deltaY: 8 }, 'pan'],
    ['pixel-mode mouse wheel zooms', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: false, deltaX: 0, deltaY: 100 }, 'zoom'],
    ['line-mode wheel zooms', { type: 'wheel', deltaMode: 1, ctrlKey: false, shiftKey: false, deltaY: 3 }, 'zoom'],
    ['Shift takes precedence over mouse-wheel zoom', { type: 'wheel', deltaMode: 0, ctrlKey: false, shiftKey: true, deltaY: 100 }, 'pan'],
    ['right-button drag pans', { type: 'pointer', button: 2, ctrlKey: false, shiftKey: false }, 'pan'],
    ['Shift plus left-button drag pans', { type: 'pointer', button: 0, ctrlKey: false, shiftKey: true }, 'pan'],
    ['Ctrl plus right-button drag zooms', { type: 'pointer', button: 2, ctrlKey: true, shiftKey: false }, 'zoom'],
    ['plain left-button drag remains available to map tools', { type: 'pointer', button: 0, ctrlKey: false, shiftKey: false }, 'none'],
    ['middle-button drag has no navigation action', { type: 'pointer', button: 1, ctrlKey: false, shiftKey: false }, 'none'],
  ] as const)('%s', (_description, event, expected) => {
    expect(get2DNavigationAction(event)).toBe(expected);
  });
});
