// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ExtentMap } from './ExtentMap';
import { extentBasemap, finishedExtent } from '../utils/extentDrawing';
import { I18nProvider } from '../i18n';

const mocks = vi.hoisted(() => ({ handlers: {} as Record<string, (event: unknown) => void>, styles: vi.fn(), remove: vi.fn(), setData: vi.fn(), sourceAvailable: false, layers: [] as Array<Record<string, unknown>> }));
vi.mock('maplibre-gl', () => ({ default: {
  Map: class {
    doubleClickZoom = { disable: vi.fn() };
    addControl() {} on(name: string, handler: (event: unknown) => void) { mocks.handlers[name] = handler; }
    addSource() { mocks.sourceAvailable = true; } addLayer(layer: Record<string, unknown>) { mocks.layers.push(layer); }
    remove = mocks.remove; setStyle = mocks.styles;
    isStyleLoaded() { return true; } getSource() { return mocks.sourceAvailable ? { setData: mocks.setData } : undefined; }
  }, AttributionControl: class {}, NavigationControl: class {},
} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => {
  vi.clearAllMocks(); mocks.handlers = {}; mocks.layers = []; mocks.sourceAvailable = false;
  vi.stubGlobal('fetch', vi.fn(async (_url, init) => ({ ok: true, json: async () => init ? { job_id: 'j1', status: 'PENDING' } : { extents: [] } })));
});
function click(lng: number, lat: number) { act(() => mocks.handlers.click({ lngLat: { lng, lat }, originalEvent: { detail: 1 } })); }
function finish() { act(() => mocks.handlers.dblclick({ preventDefault() {} })); }
describe('extent acquisition drawing', () => {
  it('uses the app ribbon treatment for panel actions, with the fetch action primary', async () => {
    render(<ExtentMap apiBase="" projectId="p1" onClose={() => {}} />);
    await screen.findByRole('button', { name: 'Return to Site views' });
    const close = screen.getByRole('button', { name: 'Return to Site views' });
    const submit = screen.getByRole('button', { name: 'Save extent and fetch data' });
    expect(close.closest('.ribbon-group')).not.toBeNull();
    expect(submit).toHaveClass('ribbon-btn-primary');
  });

  it('closes a WGS84 polygon and computes spherical preview area', () => {
    const result = finishedExtent([[4, 52], [4.01, 52], [4.01, 52.01], [4, 52.01]]);
    expect(result?.geometry).toEqual({ type: 'Polygon', coordinates: [[[4, 52], [4.01, 52], [4.01, 52.01], [4, 52.01], [4, 52]]] });
    expect(result!.areaM2).toBeGreaterThan(750000); expect(result!.areaM2).toBeLessThan(780000);
    expect(finishedExtent([[4, 52], [4.01, 52]])).toBeNull();
  });
  it('renders a filled outlined polygon, dashed live stroke and visible vertices', () => {
    render(<ExtentMap apiBase="" projectId="p1" onClose={() => {}} />);
    click(4, 52); click(4.01, 52); click(4.01, 52.01);
    expect(mocks.layers).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'extent-fill', paint: expect.objectContaining({ 'fill-opacity': expect.any(Number) }) }),
      expect.objectContaining({ id: 'extent-drawing-line', paint: expect.objectContaining({ 'line-dasharray': [2, 1.5] }) }),
      expect.objectContaining({ id: 'extent-points', paint: expect.objectContaining({ 'circle-radius': 6, 'circle-stroke-width': 2 }) }),
    ]));
    const boundary = mocks.layers.find(layer => layer.id === 'extent-line');
    expect(boundary).toBeDefined();
    if (!boundary) throw new Error('extent boundary layer was not registered');
    expect((boundary.paint as Record<string, unknown>)['line-width']).toBeGreaterThanOrEqual(4);
    finish();
    const latest = mocks.setData.mock.calls.at(-1)?.[0] as GeoJSON.FeatureCollection;
    expect(latest.features.some(feature => feature.geometry.type === 'Polygon')).toBe(true);
  });
  it('cannot submit unfinished points; sends completed polygon and redraw resets', async () => {
    render(<ExtentMap apiBase="" projectId="p1" onClose={() => {}} />);
    const submit = screen.getByRole('button', { name: 'Save extent and fetch data' });
    expect(submit).toBeDisabled(); click(4, 52); click(4.01, 52); finish(); expect(submit).toBeDisabled();
    click(4.01, 52.01); click(4, 52.01); expect(submit).toBeDisabled(); finish(); expect(submit).toBeEnabled();
    expect(screen.getByText('This is a data acquisition extent, not the formal site.')).toBeVisible();
    fireEvent.click(submit);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/projects/p1/site-extents', expect.objectContaining({ method: 'POST' })));
    const post = vi.mocked(fetch).mock.calls.find(call => call[1]?.method === 'POST')!;
    const body = JSON.parse(post[1]!.body as string);
    expect(body.geometry.coordinates[0]).toHaveLength(5); expect(body.idempotency_key).toBeTruthy();
    await screen.findByText('Acquisition status: PENDING');
    fireEvent.click(screen.getByRole('button', { name: 'Clear and redraw' })); expect(submit).toBeDisabled();
  });
  it('switches raster basemap and keeps copyright attribution', () => {
    render(<ExtentMap apiBase="" projectId="p1" onClose={() => {}} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Basemap' }), { target: { value: 'PDOK' } });
    expect(mocks.styles).toHaveBeenLastCalledWith(extentBasemap('PDOK'));
    expect(JSON.stringify(extentBasemap('OSM'))).toContain('OpenStreetMap contributors');
    expect(JSON.stringify(extentBasemap('PDOK'))).toContain('Kadaster / PDOK');
  });
  it('supports Traditional Chinese', () => {
    render(<I18nProvider language="zh-TW"><ExtentMap apiBase="" projectId="p1" onClose={() => {}} /></I18nProvider>);
    expect(screen.getByText('這是資料抓取範圍，不是正式基地。')).toBeVisible();
    expect(screen.getByRole('button', { name: '儲存範圍並抓取資料' })).toBeDisabled();
  });
});
