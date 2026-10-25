import { useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type MapMouseEvent } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useI18n } from '../i18n';

import { extentCopy, extentBasemap, finishedExtent, type Point } from '../utils/extentDrawing';

type SourceResult = { name: string; status: string; count?: number; bytes?: number; error?: string };
type ExtentJob = { job_id: string; status: string; sources?: SourceResult[]; manifest_path?: string };
export function ExtentMap({ apiBase, projectId, onClose }: { apiBase: string; projectId: string; onClose: () => void }) {
  const { language } = useI18n();
  const copy = extentCopy[language];
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const vertices = useRef<Point[]>([]);
  const completed = useRef(false);
  const [points, setPoints] = useState<Point[]>([]);
  const [done, setDone] = useState(false);
  const [basemap, setBasemap] = useState<'OSM' | 'PDOK'>('OSM');
  const [mapError, setMapError] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState<ExtentJob | null>(null);
  const [saved, setSaved] = useState<Array<{ id: string; area_m2: number }>>([]);
  const [savedStatus, setSavedStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const key = useRef<string | null>(null);
  const extent = done ? finishedExtent(points) : null;
  const endpoint = `${apiBase}/api/v1/projects/${encodeURIComponent(projectId)}/site-extents`;
  function draw() {
    const instance = map.current;
    if (!instance?.isStyleLoaded()) return;
    if (!instance.getSource('extent')) {
      instance.addSource('extent', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      instance.addLayer({ id: 'extent-fill', type: 'fill', source: 'extent', filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': '#ffb347', 'fill-opacity': 0.34 } });
      instance.addLayer({ id: 'extent-line', type: 'line', source: 'extent', filter: ['==', '$type', 'Polygon'], paint: { 'line-color': '#ff8c00', 'line-width': 4 } });
      instance.addLayer({ id: 'extent-drawing-line', type: 'line', source: 'extent', filter: ['==', '$type', 'LineString'], paint: { 'line-color': '#ff8c00', 'line-width': 3, 'line-dasharray': [2, 1.5] } });
      instance.addLayer({ id: 'extent-points', type: 'circle', source: 'extent', filter: ['==', '$type', 'Point'], paint: { 'circle-color': '#ffd166', 'circle-radius': 6, 'circle-stroke-color': '#17222d', 'circle-stroke-width': 2 } });
    }
    const polygon = completed.current ? finishedExtent(vertices.current) : null;
    const features: GeoJSON.Feature[] = vertices.current.map(point => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: point } }));
    if (polygon) features.push({ type: 'Feature', properties: {}, geometry: polygon.geometry });
    else if (vertices.current.length >= 2) features.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: vertices.current } });
    (instance.getSource('extent') as GeoJSONSource).setData({ type: 'FeatureCollection', features });
  }
  useEffect(() => {
    try {
      const instance = new maplibregl.Map({ container: container.current!, style: extentBasemap('OSM'), center: [4.43, 51.91], zoom: 12, attributionControl: false });
      map.current = instance;
      instance.addControl(new maplibregl.AttributionControl({ compact: false }));
      instance.addControl(new maplibregl.NavigationControl());
      instance.doubleClickZoom.disable();
      instance.on('style.load', draw);
      instance.on('error', () => setMapError(true));
      instance.on('click', (event: MapMouseEvent) => {
        if (completed.current || event.originalEvent.detail > 1) return;
        const next: Point = [event.lngLat.lng, event.lngLat.lat];
        vertices.current = [...vertices.current, next];
        setPoints(vertices.current); draw();
      });
      instance.on('dblclick', (event: MapMouseEvent) => {
        event.preventDefault();
        if (!completed.current && finishedExtent(vertices.current)) { completed.current = true; setDone(true); draw(); }
      });
    } catch { setMapError(true); }
    return () => { map.current?.remove(); map.current = null; };
  }, []);
  useEffect(() => { map.current?.setStyle(extentBasemap(basemap)); }, [basemap]);
  useEffect(() => {
    let active = true;
    fetch(endpoint).then(async response => {
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      if (active) { setSaved(data.extents); setSavedStatus('ready'); }
    }).catch(() => { if (active) setSavedStatus('error'); });
    return () => { active = false; };
  }, [endpoint, job?.job_id]);
  useEffect(() => {
    if (!job || !['PENDING', 'RUNNING', 'PREPARED'].includes(job.status)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${endpoint}/jobs/${job.job_id}`);
        if (!response.ok) throw new Error(String(response.status));
        const next = await response.json();
        if (active) setJob(next);
      } catch { if (active) setError(copy.unavailable); }
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [job, endpoint, copy.unavailable]);
  async function submit() {
    if (!extent || submitting || job) return;
    setSubmitting(true); setError('');
    key.current ??= crypto.randomUUID();
    try {
      const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ geometry: extent.geometry, idempotency_key: key.current }) });
      if (!response.ok) { setError(`HTTP ${response.status}: ${await response.text()}`); return; }
      setJob(await response.json());
    } catch { setError(copy.unavailable); }
    finally { setSubmitting(false); }
  }
  return <section style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', padding: 12, gap: 8 }} aria-label={copy.title}>
    <div className="ribbon-group ribbon-actions"><div className="ribbon-tools">
      <h2>{copy.title}</h2><button onClick={onClose}>{copy.close}</button>
      <label>{copy.basemap} <select aria-label={copy.basemap} value={basemap} onChange={event => { setBasemap(event.target.value as 'OSM' | 'PDOK'); setMapError(false); }}><option>OSM</option><option>PDOK</option></select></label>
      <button disabled={submitting} onClick={() => { vertices.current = []; completed.current = false; setPoints([]); setDone(false); setJob(null); key.current = null; setError(''); draw(); }}>{copy.clear}</button>
      <button className="ribbon-btn-primary" disabled={!extent || submitting || !!job} onClick={submit}>{copy.submit}</button>
    </div></div>
    <p>{copy.instruction}</p><strong>{copy.warning}</strong>
    <output aria-live="polite">{copy.area}: {extent ? (extent.areaM2 / 1e6).toFixed(3) : '—'} km²</output>
    {mapError && <p role="alert">{copy.error}</p>}{error && <p role="alert">{error}</p>}
    <div ref={container} style={{ minHeight: 260, flex: 1 }} data-testid="extent-map" />
    <p>{copy.list}: {savedStatus === 'loading' ? copy.loading : savedStatus === 'error' ? copy.listError : saved.map(item => `${item.id} (${(item.area_m2 / 1e6).toFixed(3)} km²)`).join(', ')}</p>
    {job && <div aria-live="polite"><strong>{copy.status}: {job.status}</strong>{job.sources?.map(source => <p key={source.name}>{source.name}: {source.status} · {source.count ?? '—'} · {source.bytes ?? 0} bytes {source.error}</p>)}</div>}
  </section>;
}
