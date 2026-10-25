// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { FabricCompareMap } from './FabricCompareMap';
import type { FabricLayers } from './FabricCompareMap';
const empty = () => ({ type: 'FeatureCollection' as const, features: [] });
const layers: FabricLayers = { roads: empty(), blocks: empty(), buildings: empty(), land_use: empty(), parks: empty(), site: empty() };
afterEach(() => { cleanup(); delete (window as unknown as {maplibregl?: unknown}).maplibregl; });
function install() {
 const events: Record<string, () => void> = {}; const added: Record<string, unknown>[]=[];
 const map={setLayoutProperty:vi.fn(),setPitch:vi.fn(),getPitch:vi.fn(),getStyle:vi.fn(),on:vi.fn((event:string,handler:()=>void)=>{events[event]=handler;}),addSource:vi.fn(),addLayer:vi.fn((layer:Record<string,unknown>)=>added.push(layer)),fitBounds:vi.fn(),remove:vi.fn(),resize:vi.fn()};
 (window as unknown as {maplibregl: unknown}).maplibregl={getVersion:()=> '4.7.1',Map:class { constructor(){return map;} }};
 return {events,map,added};
}
it('uses verified local 4.7.1, renders source category and numeric hierarchy, waits for idle, removes map',async()=>{
 const {events,map,added}=install(); const {unmount}=render(<FabricCompareMap id="harbour_grain" layers={layers}/>);
 await waitFor(()=>expect(events.load).toBeTruthy()); act(()=>events.load());
 expect(map.addSource).toHaveBeenCalledTimes(6); expect(map.addSource).toHaveBeenCalledWith('land_use',expect.objectContaining({type:'geojson'}));
 const land=added.find(layer=>layer.id==='land-use')!; expect(JSON.stringify(land)).toContain('fabric_color');
 const roads=added.find(layer=>layer.id==='roads')!; expect((roads.paint as Record<string,unknown>)['line-width']).toEqual(['get','fabric_width']);
 expect(screen.getByTestId('fabric-map-harbour_grain').getAttribute('data-map-state')).toBe('loading');
 act(()=>events.idle()); expect(screen.getByTestId('fabric-map-harbour_grain').getAttribute('data-map-state')).toBe('ready');
 unmount(); expect(map.remove).toHaveBeenCalledOnce();
});
it('does not clear rendering errors on idle',async()=>{const {events}=install();render(<FabricCompareMap id="broken" layers={layers}/>);await waitFor(()=>expect(events.load).toBeTruthy());act(()=>events.load());act(()=>events.error());act(()=>events.idle());expect(screen.getByTestId('fabric-map-broken').getAttribute('data-map-state')).toBe('error');});
it('rejects another version and uses only a local vendor URL',async()=>{
 (window as unknown as {maplibregl: unknown}).maplibregl={getVersion:()=> '5.0.0',Map:vi.fn()};
 render(<FabricCompareMap id="wrong-version" layers={layers}/>);
 const script=document.querySelector<HTMLScriptElement>('script[src="/vendor/maplibre-gl-4.7.1/maplibre-gl.js"]');expect(script).toBeTruthy();
 act(()=>script!.dispatchEvent(new Event('load')));await waitFor(()=>expect(screen.getByTestId('fabric-map-wrong-version').getAttribute('data-map-state')).toBe('error'));
 expect(document.querySelector('script[src^="https://"]')).toBeNull();
});

it('fits the site bounding box again after resize with a measured 85% area target', async () => {
 const { events, map } = install(); let resize: (() => void) | undefined;
 vi.stubGlobal('ResizeObserver', class { constructor(callback: () => void) { resize = callback; } observe() {} disconnect() {} });
 const site: FabricLayers = { ...layers, site: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[4, 51], [4.01, 51], [4.01, 51.01], [4, 51.01], [4, 51]]] } }] } };
 const { container } = render(<FabricCompareMap id="fit" layers={site} />);
 const canvas = container.querySelector('.fabric-map') as HTMLElement;
 const aspect = Number(screen.getByTestId('fabric-map-fit').getAttribute('data-site-aspect'));
 Object.defineProperties(canvas, { clientWidth: { value: 400 }, clientHeight: { value: 400 / aspect } });
 await waitFor(() => expect(events.load).toBeTruthy()); act(() => events.load());
 expect(map.fitBounds).toHaveBeenCalledWith([[4, 51], [4.01, 51.01]], expect.objectContaining({ duration: 0 }));
 expect(Number(screen.getByTestId('fabric-map-fit').getAttribute('data-site-bounds-area-coverage'))).toBeGreaterThan(0.85);
 Object.assign(map, { project: vi.fn((coordinate: number[]) => coordinate[0] === 4 ? {x:12,y:12} : {x:388,y:400 / aspect - 12}) });
 act(() => events.idle()); expect(screen.getByTestId('fabric-map-fit').getAttribute('data-coverage-measurement')).toBe('map-project');
 expect(Number(screen.getByTestId('fabric-map-fit').getAttribute('data-site-width-coverage'))).toBeCloseTo(0.94);
 act(() => resize?.()); expect(map.resize).toHaveBeenCalledOnce(); expect(map.fitBounds).toHaveBeenCalledTimes(2);
 vi.unstubAllGlobals();
});

it('renders explicit measured heights, retained grey, and toggles mode on the same map with hook cleanup', async () => {
 const { events, map, added } = install();
 const { rerender, unmount } = render(<FabricCompareMap id="three" layers={layers} mode="3D" />);
 await waitFor(() => expect(events.load).toBeTruthy()); act(() => events.load());
 const extrusion = added.find(layer => layer.id === 'buildings-3d')!;
 expect(extrusion.type).toBe('fill-extrusion');
 expect((extrusion.paint as Record<string, unknown>)['fill-extrusion-height']).toEqual(['max', 0, ['to-number', ['get', 'height_m'], 0]]);
 expect((extrusion.paint as Record<string, unknown>)['fill-extrusion-color']).toEqual(['get', 'fabric_color']);
 for (const id of ['roads', 'parks', 'land-use']) expect(added.find(layer => layer.id === id)?.type).not.toBe('fill-extrusion');
 expect(window.__fabricCompareMaps?.three).toBe(map);
 rerender(<FabricCompareMap id="three" layers={layers} mode="2D" />);
 expect(map.setPitch).toHaveBeenLastCalledWith(0);
 expect(map.setLayoutProperty).toHaveBeenCalledWith('buildings-3d', 'visibility', 'none');
 rerender(<FabricCompareMap id="three" layers={layers} mode="3D" />);
 expect(map.setPitch).toHaveBeenLastCalledWith(55);
 expect(map.setLayoutProperty).toHaveBeenCalledWith('buildings', 'visibility', 'none');
 expect(map.fitBounds).not.toHaveBeenCalled(); expect(map.remove).not.toHaveBeenCalled();
 unmount(); expect(window.__fabricCompareMaps?.three).toBeUndefined(); expect(map.remove).toHaveBeenCalledOnce();
});
