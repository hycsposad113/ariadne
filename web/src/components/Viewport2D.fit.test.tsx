// @vitest-environment jsdom
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Viewport2D } from './Viewport2D';
import { epsg28992ToScreen, type RenderTransform } from '../utils/geoTransform';
import type { Building } from '../types';

// Diagonal site like M4H: 1200 m wide, 600 m tall in EPSG:28992.
const site = { type: 'Polygon', coordinates: [[[89000, 435600], [90200, 436200], [90100, 436200], [89000, 435700], [89000, 435600]]] };
const buildings = [{ id: 'b1', geometry: site, properties: { fabric_display: true }, disposition: 'EDITABLE' }] as unknown as Building[];

let size = { width: 0, height: 0 };
const observers: Array<{ callback: ResizeObserverCallback; targets: Element[] }> = [];

class FakeResizeObserver {
  entry: { callback: ResizeObserverCallback; targets: Element[] };
  constructor(callback: ResizeObserverCallback) { this.entry = { callback, targets: [] }; observers.push(this.entry); }
  observe(target: Element) { this.entry.targets.push(target); }
  unobserve() {}
  disconnect() { this.entry.targets = []; }
}

function resizeTo(width: number, height: number) {
  size = { width, height };
  act(() => { observers.forEach(o => o.targets.length && o.callback([], o as unknown as ResizeObserver)); });
}

function siteScreenBounds(transform: RenderTransform) {
  const points = site.coordinates[0].map(([x, y]) => epsg28992ToScreen(x, y, transform));
  return {
    minX: Math.min(...points.map(p => p[0])), maxX: Math.max(...points.map(p => p[0])),
    minY: Math.min(...points.map(p => p[1])), maxY: Math.max(...points.map(p => p[1])),
  };
}

function expectSiteFits(transform: RenderTransform, width: number, height: number) {
  const b = siteScreenBounds(transform);
  const margin = Math.min(width, height) * 0.02;
  expect(b.minX).toBeGreaterThanOrEqual(margin);
  expect(b.minY).toBeGreaterThanOrEqual(margin);
  expect(b.maxX).toBeLessThanOrEqual(width - margin);
  expect(b.maxY).toBeLessThanOrEqual(height - margin);
  // Fitted, not merely shrunk: the limiting axis fills most of the canvas.
  expect(Math.max((b.maxX - b.minX) / width, (b.maxY - b.minY) / height)).toBeGreaterThan(0.85);
}

describe('Viewport2D fit-to-site for fabric plans', () => {
  beforeEach(() => {
    observers.length = 0;
    size = { width: 0, height: 0 };
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    vi.spyOn(HTMLCanvasElement.prototype, 'clientWidth', 'get').mockImplementation(() => size.width);
    vi.spyOn(HTMLCanvasElement.prototype, 'clientHeight', 'get').mockImplementation(() => size.height);
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('re-applies fit-to-site after the canvas container gets its final height and on later resizes', () => {
    const onTransformChange = vi.fn<(t: RenderTransform) => void>();
    size = { width: 1110, height: 160 };
    const { container } = render(
      <Viewport2D studyAreaGeometry={site as never} buildings={buildings} segments={[]} activeSyntaxLayer={null}
        spatialZones={[]} selectedFeatureId={null} onSelectFeature={vi.fn()} figureContext={{} as never}
        figureExportReady={false} onTransformChange={onTransformChange} />,
    );
    const canvas = container.querySelector('canvas#canvas-viewport-2d') as HTMLCanvasElement;
    expect(onTransformChange).toHaveBeenCalled();
    expectSiteFits(onTransformChange.mock.lastCall![0], 1110, 160);

    // The panel settles taller after first render (legend/layout): the fit must follow it.
    resizeTo(1110, 380);
    expectSiteFits(onTransformChange.mock.lastCall![0], 1110, 380);
    expect([canvas.width, canvas.height]).toEqual([1110, 380]);

    // Window shrink: fit again and keep the bitmap in step with the canvas box.
    resizeTo(910, 252);
    expectSiteFits(onTransformChange.mock.lastCall![0], 910, 252);
    expect([canvas.width, canvas.height]).toEqual([910, 252]);
  });
});
