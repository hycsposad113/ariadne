import { FABRIC_COLORS, normalizeFabricLayers } from './fabricPalette';
import { FabricLegend } from './FabricViewport';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useT } from '../i18n';
export type FabricCollection = { type: 'FeatureCollection'; features: { type: 'Feature'; geometry: { type: string; coordinates: unknown } | null; properties: Record<string, unknown> | null }[] };
export type FabricLayers = Record<'roads' | 'blocks' | 'buildings' | 'land_use' | 'parks' | 'site', FabricCollection> & { water?: FabricCollection };
export type FabricMapInstance = { setLayoutProperty: (id: string, name: string, value: unknown) => void; setPitch: (pitch: number) => void; getPitch: () => number; getStyle: () => unknown; on: (event: string, handler: () => void) => void; addSource: (id: string, source: unknown) => void; addLayer: (layer: unknown) => void; fitBounds: (bounds: number[][], options: unknown) => void; remove: () => void; resize: () => void; project?: (coordinate: number[]) => { x: number; y: number } };
type FabricMapLibrary = { Map: new (options: unknown) => FabricMapInstance; getVersion: () => string };
declare global { interface Window { __fabricCompareMaps?: Record<string, FabricMapInstance> } }
const buildingColor = ['get', 'fabric_color'];
let libraryPromise: Promise<FabricMapLibrary> | null = null;
export function loadFabricMapLibrary(): Promise<FabricMapLibrary> {
  const existing = (window as unknown as { maplibregl?: FabricMapLibrary }).maplibregl;
  if (existing?.getVersion() === '4.7.1') return Promise.resolve(existing);
  if (!libraryPromise) libraryPromise = new Promise((resolve, reject) => {
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = '/vendor/maplibre-gl-4.7.1/maplibre-gl.css'; document.head.append(css);
    const script = document.createElement('script'); script.src = '/vendor/maplibre-gl-4.7.1/maplibre-gl.js';
    script.onload = () => { const loaded = (window as unknown as { maplibregl?: FabricMapLibrary }).maplibregl; if (loaded?.getVersion() === '4.7.1') resolve(loaded); else reject(new Error('version')); };
    script.onerror = () => reject(new Error('unavailable')); document.head.append(script);
  });
  return libraryPromise;
}
function coordinates(value: unknown, output: number[][]): void {
  if (!Array.isArray(value)) return;
  if (typeof value[0] === 'number' && typeof value[1] === 'number') { output.push([value[0], value[1]]); return; }
  value.forEach(item => coordinates(item, output));
}
// Mercator bounds determine the canvas shape so the intact site can fill both axes.
export function fabricViewport(layers: FabricLayers) {
  const points: number[][] = [];
  (layers.site.features.length ? layers.site : layers.buildings).features.forEach(feature => coordinates(feature.geometry?.coordinates, points));
  const finite = points.filter(p => p.every(Number.isFinite));
  if (!finite.length) return null;
  const bounds = [[Math.min(...finite.map(p => p[0])), Math.min(...finite.map(p => p[1]))], [Math.max(...finite.map(p => p[0])), Math.max(...finite.map(p => p[1]))]];
  const mercatorY = (latitude: number) => Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360));
  const width = (bounds[1][0] - bounds[0][0]) * Math.PI / 180;
  const height = mercatorY(bounds[1][1]) - mercatorY(bounds[0][1]);
  return { bounds, aspect: width > 0 && height > 0 ? width / height : 1 };
}
export function FabricCompareMap({ id, layers: inputLayers, mode = '2D' }: { id: string; layers: FabricLayers; mode?: '2D' | '3D' }) {
  const layers = useMemo(() => normalizeFabricLayers(inputLayers), [inputLayers]);
  const viewport = useMemo(() => fabricViewport(layers), [layers]);
  const t = useT(); const host = useRef<HTMLDivElement>(null); const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const mapRef = useRef<FabricMapInstance | undefined>(undefined);
  const modeRef = useRef(mode); modeRef.current = mode;
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setLayoutProperty('buildings', 'visibility', mode === '3D' ? 'none' : 'visible');
    map.setLayoutProperty('buildings-3d', 'visibility', mode === '3D' ? 'visible' : 'none');
    map.setPitch(mode === '3D' ? 55 : 0);
  }, [mode]);
  useEffect(() => {
    let active = true; let failed = false; let map: FabricMapInstance | undefined; let observer: ResizeObserver | undefined;
    setState('loading');
    let loaded = false;
    const measure = () => {
      if (!map?.project || !viewport || !host.current) return;
      const start = map.project(viewport.bounds[0]); const end = map.project(viewport.bounds[1]);
      const width = host.current.clientWidth; const height = host.current.clientHeight;
      const wrap = host.current.parentElement;
      if (width > 0 && height > 0 && wrap) {
        wrap.dataset.siteWidthCoverage = String(Math.abs(end.x - start.x) / width);
        wrap.dataset.siteHeightCoverage = String(Math.abs(end.y - start.y) / height);
        wrap.dataset.siteBoundsAreaCoverage = String(Math.abs((end.x - start.x) * (end.y - start.y)) / (width * height));
        wrap.dataset.coverageMeasurement = 'map-project';
      }
    };
    const fit = () => {
      if (!loaded || !map || !viewport || !host.current) return;
      const width = host.current.clientWidth; const height = host.current.clientHeight;
      const padding = Math.min(width, height) * 0.03;
      map.fitBounds(viewport.bounds, { padding, duration: 0 });
      const scale = Math.min((width - 2 * padding) / viewport.aspect, height - 2 * padding);
      const wrap = host.current.parentElement;
      if (width > 0 && height > 0 && wrap) {
        wrap.dataset.coverageMeasurement = 'fit-estimate';
        wrap.dataset.siteWidthCoverage = String(scale * viewport.aspect / width);
        wrap.dataset.siteHeightCoverage = String(scale / height);
        wrap.dataset.siteBoundsAreaCoverage = String(scale * scale * viewport.aspect / (width * height));
      }
    };
    loadFabricMapLibrary().then(library => {
      if (!active || !host.current) return;
      map = new library.Map({ container: host.current, style: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': FABRIC_COLORS.background } }] }, attributionControl: false, center: [4.43, 51.91], zoom: 13, pitch: modeRef.current === '3D' ? 55 : 0, dragRotate: true });
      (window.__fabricCompareMaps ??= {})[id] = map;
      map.on('load', () => {
        if (!active || !map) return;
        Object.entries(layers).forEach(([name, data]) => map!.addSource(name, { type: 'geojson', data }));
        if (layers.water) map.addLayer({ id: 'water', type: 'fill', source: 'water', paint: { 'fill-color': FABRIC_COLORS.water, 'fill-opacity': 0.9 } });
        map.addLayer({ id: 'land-use', type: 'fill', source: 'land_use', paint: { 'fill-color': ['get', 'fabric_color'], 'fill-opacity': 0.7 } });
        map.addLayer({ id: 'parks', type: 'fill', source: 'parks', paint: { 'fill-color': FABRIC_COLORS.park, 'fill-opacity': 0.8 } });
        map.addLayer({ id: 'blocks', type: 'line', source: 'blocks', paint: { 'line-color': FABRIC_COLORS.blocks, 'line-width': 1 } });
        map.addLayer({ id: 'roads', type: 'line', source: 'roads', paint: { 'line-color': ['get', 'fabric_color'], 'line-width': ['get', 'fabric_width'] } });
        map.addLayer({ id: 'buildings', type: 'fill', source: 'buildings', layout: { visibility: modeRef.current === '3D' ? 'none' : 'visible' }, paint: { 'fill-color': buildingColor, 'fill-outline-color': '#594d43' } });
        // Missing height remains flat; floor counts are never converted into an estimated height.
        map.addLayer({ id: 'buildings-3d', type: 'fill-extrusion', source: 'buildings', layout: { visibility: modeRef.current === '3D' ? 'visible' : 'none' }, paint: { 'fill-extrusion-color': buildingColor, 'fill-extrusion-height': ['max', 0, ['to-number', ['get', 'height_m'], 0]], 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 1 } });
        map.addLayer({ id: 'site', type: 'line', source: 'site', paint: { 'line-color': FABRIC_COLORS.boundary, 'line-width': 2 } });
        loaded = true; mapRef.current = map; fit(); map.setPitch(modeRef.current === '3D' ? 55 : 0);
        map.on('idle', () => { if (active && !failed) { measure(); setState('ready'); } });
      });
      map.on('error', () => { failed = true; if (active) setState('error'); });
      if (typeof ResizeObserver !== 'undefined') { observer = new ResizeObserver(() => { map?.resize(); fit(); }); observer.observe(host.current); }
    }).catch(() => { if (active) setState('error'); });
    return () => { active = false; observer?.disconnect(); const registeredMaps = window.__fabricCompareMaps;
      if (registeredMaps && registeredMaps[id] === map) delete registeredMaps[id];
      if (mapRef.current === map) mapRef.current = undefined;
      map?.remove(); };
  }, [id, layers, viewport]);
  return <div className="fabric-map-wrap" data-map-mode={mode} data-fit-basis="site-mercator-bounding-box" data-fit-padding-fraction="0.03" data-site-aspect={viewport?.aspect} data-testid={`fabric-map-${id}`} data-map-state={state}><div ref={host} style={{ aspectRatio: viewport?.aspect ?? 1 }} className="fabric-map" aria-label={t('Fabric map {id}', { id })} />{state !== 'ready' && <p role={state === 'error' ? 'alert' : 'status'}>{t(state === 'error' ? 'Map renderer unavailable.' : 'Loading fabric plans…')}</p>}<FabricLegend layers={layers}/></div>;
}
