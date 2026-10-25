import { describe, it, expect } from 'vitest';
import {
  epsg28992ToLocalMetric,
  localMetricToEpsg28992,
  epsg28992ToScreen,
  screenToEpsg28992,
  panByWheelDelta,
  zoomAtPoint,
  getSyntaxColor,
} from './geoTransform';

describe('geoTransform math and invertible mappings', () => {
  it('correctly maps forward and inverse metric coordinates', () => {
    const origX = 89100.0;
    const origY = 435900.0;

    const [lx, ly] = epsg28992ToLocalMetric(89500.0, 436200.0, origX, origY);
    expect(lx).toBe(400.0);
    expect(ly).toBe(300.0);

    const [rx, ry] = localMetricToEpsg28992(lx, ly, origX, origY);
    expect(rx).toBe(89500.0);
    expect(ry).toBe(436200.0);
  });

  it('guarantees round-trip precision between screen pixels and EPSG:28992', () => {
    const t = {
      originX: 89100.0,
      originY: 435900.0,
      zoom: 1.25,
      panX: 500,
      panY: 400,
    };

    const worldPoints: [number, number][] = [
      [88600.0, 435500.0],
      [89100.0, 435900.0],
      [89600.0, 436300.0],
    ];

    for (const [wx, wy] of worldPoints) {
      const [px, py] = epsg28992ToScreen(wx, wy, t);
      const [invX, invY] = screenToEpsg28992(px, py, t);

      expect(Math.abs(invX - wx)).toBeLessThan(1e-5);
      expect(Math.abs(invY - wy)).toBeLessThan(1e-5);
    }
  });

  it('computes color ramp deterministically', () => {
    const cMin = getSyntaxColor(0.0, 0.0, 10.0);
    const cMax = getSyntaxColor(10.0, 0.0, 10.0);
    const cMid = getSyntaxColor(5.0, 0.0, 10.0);

    expect(cMin).toBe('rgb(44, 123, 182)');
    expect(cMax).toBe('rgb(215, 25, 28)');
    expect(cMid).toBe('rgb(255, 255, 191)');
  });

  it('zooms around the pointer while keeping its EPSG:28992 coordinate fixed', () => {
    const transform = {
      originX: 89100,
      originY: 435900,
      zoom: 0.9,
      panX: 420,
      panY: 380,
    };
    const cursor: [number, number] = [173, 249];
    const worldBefore = screenToEpsg28992(cursor[0], cursor[1], transform);
    const zoomed = zoomAtPoint(transform, 1.7, cursor[0], cursor[1]);
    const worldAfter = screenToEpsg28992(cursor[0], cursor[1], zoomed);

    expect(zoomed.zoom).toBeCloseTo(transform.zoom * 1.7);
    expect(worldAfter[0]).toBeCloseTo(worldBefore[0]);
    expect(worldAfter[1]).toBeCloseTo(worldBefore[1]);
  });

  it('pans opposite to positive trackpad deltas', () => {
    const transform = {
      originX: 89100,
      originY: 435900,
      zoom: 0.9,
      panX: 420,
      panY: 380,
    };
    const panned = panByWheelDelta(transform, 12, 25);

    expect(panned.panX).toBe(transform.panX - 12);
    expect(panned.panY).toBe(transform.panY - 25);
  });
});
