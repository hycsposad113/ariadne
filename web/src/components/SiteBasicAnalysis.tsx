import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { JudgementPanel } from './JudgementCard';
import { useI18n } from '../i18n';
import { extentBasemap } from '../utils/extentDrawing';

export const basicCopy = {
  en: { title: 'Basic site analysis', close: 'Close', extent: 'Acquisition extent', load: 'Analyse site', analysing: 'Analysing…', cancel: 'Cancel analysis', cancelling: 'Cancelling…', elapsed: 'Elapsed', lastAnalysis: 'Last analysis', cached: 'Cached result', empty: 'Draw an extent and fetch its data first.',
    estimate: 'Estimated arrival potential — not observed pedestrian flow.', transit: 'Nearest transit by side (walking network)', closest: 'Closest side',
    landuse: 'Land use by direction (outside site, 0–500 m)', entrances: 'Estimated entrance arrival ranking',
    bag: 'BAG floor area by use', osm: 'OSM landuse', noData: 'Unavailable / unreachable', distance: 'Walking distance', station: 'Station',
    status: 'Status', mapError: 'Map unavailable. Analysis remains available below.', hashes: 'Source hashes and assumptions', limitations: 'Limitations',
    stations: 'Stations', nearest: 'Nearest walking routes', sectors: 'Land use sectors', routes: 'Main arrival routes',
    parameters: 'Assumed parameters', syntax: 'Syntax path overlay', rank: 'Rank', potential: 'Distance potential',
    loading: 'Loading…', unavailable: 'Analysis unavailable', uses: 'use', area: 'm² floor area', unknown: 'Unnamed station', missingArea: 'Objects missing floor area' },
  'zh-TW': { title: '基本基地分析', close: '關閉', extent: '資料抓取範圍', load: '分析基地', analysing: '分析中…', cancel: '取消分析', cancelling: '取消中…', elapsed: '經過時間', lastAnalysis: '上次分析時間', cached: '快取命中', empty: '請先畫範圍並抓取資料。',
    estimate: '推估的到達潛力，並非觀測行人人流。', transit: '各側最近大眾運輸（沿步行路網）', closest: '最接近的一側',
    landuse: '各方位土地使用（基地外 0–500 m）', entrances: '各入口推估到達潛力排序',
    bag: 'BAG 樓地板用途面積', osm: 'OSM 土地使用', noData: '缺資料／無法到達', distance: '步行距離', station: '站點',
    status: '狀態', mapError: '地圖無法使用；下方仍可檢視分析。', hashes: '來源 hash 與假設', limitations: '限制',
    stations: '交通站點', nearest: '最近步行路徑', sectors: '土地使用扇區', routes: '主要到達路線',
    parameters: '假設參數', syntax: 'Syntax 路徑疊圖', rank: '排序', potential: '距離到達潛力',
    loading: '載入中…', unavailable: '分析無法使用', uses: '用途', area: 'm² 樓地板面積', unknown: '未命名站點', missingArea: '缺用途面積的物件' },
};
type Route = { origin_id: string; name: string | null; kind: string; distance_m: number; connector_m: number; routes?: Array<{ name?: string | null; ref?: string | null; mode?: string }>; syntax: { coverage_ratio?: number; nain_mean?: number | null; nach_mean?: number | null } };
export type BasicAnalysis = {
  status: string; created_at: string; closest_transit_sides: string[]; source_hashes: Record<string, string>; parameters: Record<string, unknown>; limitations: string[];
  transit: Array<{ side: string; status: string; nearest_by_mode: Record<string, Route | null> }>;
  landuse: Array<{ side: string; bag_floor_area_m2: number; bag_usage_percent: Record<string, number>; osm_ring_area_percent: Record<string, number>; missing_area_count: number }>;
  entrances: Array<{ id: string; side: string; rank: number; distance_potential: number; reachable_origins: number; major_routes: Route[] }>;
  syntax: { status: string }; overlay_wgs84: GeoJSON.FeatureCollection;
};
type BasicAnalysisJob = {
  job_id: string; status: 'PENDING' | 'RUNNING' | 'CANCELLING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
  cache_hit?: boolean; elapsed_seconds?: number; last_analysis_at?: string | null; result?: BasicAnalysis | null; error?: string | null;
};
type Overlay = 'stations' | 'nearest' | 'sectors' | 'routes';
const kinds: Record<Overlay, string[]> = { stations: ['station'], nearest: ['nearest_route'], sectors: ['sector'], routes: ['arrival_route', 'entrance'] };
export function selectedBasicOverlay(data: GeoJSON.FeatureCollection, enabled: Record<Overlay, boolean>): GeoJSON.FeatureCollection {
  const selected = Object.entries(enabled).flatMap(([key, value]) => value ? kinds[key as Overlay] : []);
  return { type: 'FeatureCollection', features: data.features.filter(feature => selected.includes(feature.properties?.kind)) };
}

function BasicMap({ data, enabled, errorText }: { data: GeoJSON.FeatureCollection; enabled: Record<Overlay, boolean>; errorText: string }) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<maplibregl.Map | null>(null);
  const [error, setError] = useState(false);
  const shown = selectedBasicOverlay(data, enabled);
  const latest = useRef(shown);
  useEffect(() => {
    try {
      const map = new maplibregl.Map({ container: container.current!, style: extentBasemap('OSM'), center: [4.43, 51.91], zoom: 13, attributionControl: false });
      instance.current = map;
      map.addControl(new maplibregl.AttributionControl({ compact: false }));
      map.addControl(new maplibregl.NavigationControl());
      map.on('error', () => setError(true));
      map.on('load', () => {
        map.addSource('basic', { type: 'geojson', data: latest.current });
        map.addLayer({ id: 'basic-sector', type: 'fill', source: 'basic', filter: ['==', ['get', 'kind'], 'sector'], paint: {
          'fill-color': ['match', ['get', 'side'], 'N', '#65bfa0', 'E', '#e3b56b', 'S', '#829adb', '#b492ce'], 'fill-opacity': .2 } });
        map.addLayer({ id: 'basic-arrivals', type: 'line', source: 'basic', filter: ['==', ['get', 'kind'], 'arrival_route'], paint: { 'line-color': '#d18be0', 'line-width': 3, 'line-opacity': .7 } });
        map.addLayer({ id: 'basic-nearest', type: 'line', source: 'basic', filter: ['==', ['get', 'kind'], 'nearest_route'], paint: { 'line-color': '#ffb347', 'line-width': 4 } });
        map.addLayer({ id: 'basic-stations', type: 'circle', source: 'basic', filter: ['==', ['get', 'kind'], 'station'], paint: { 'circle-color': '#50c8db', 'circle-radius': 5, 'circle-stroke-width': 1, 'circle-stroke-color': '#17222d' } });
        map.addLayer({ id: 'basic-entrances', type: 'circle', source: 'basic', filter: ['==', ['get', 'kind'], 'entrance'], paint: { 'circle-color': '#f08080', 'circle-radius': 6 } });
        map.on('click', 'basic-stations', event => {
          const feature = event.features?.[0];
          if (feature?.geometry.type === 'Point') new maplibregl.Popup().setLngLat(feature.geometry.coordinates as [number, number]).setText(String(feature.properties?.name || feature.properties?.ref || feature.id || '')).addTo(map);
        });
      });
    } catch { setError(true); }
    return () => { instance.current?.remove(); instance.current = null; };
  }, []);
  useEffect(() => {
    latest.current = shown;
    const source = instance.current?.getSource('basic') as maplibregl.GeoJSONSource | undefined;
    source?.setData(shown);
  }, [shown]);
  return <><div ref={container} style={{ minHeight: 350, height: '42vh' }} data-testid="basic-map" />{error && <p role="alert">{errorText}</p>}</>;
}

export function SiteBasicAnalysis({ apiBase, projectId, onClose }: { apiBase: string; projectId: string; onClose: () => void }) {
  const { language } = useI18n();
  const c = basicCopy[language];
  const [extents, setExtents] = useState<Array<{ id: string }>>([]);
  const [extent, setExtent] = useState('');
  const [data, setData] = useState<BasicAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [jobStatus, setJobStatus] = useState<BasicAnalysisJob['status'] | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [cancelRequested, setCancelRequested] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [lastAnalysisAt, setLastAnalysisAt] = useState<string | null>(null);
  const [cacheHit, setCacheHit] = useState(false);
  const activeJobId = useRef<string | null>(null);
  const [enabled, setEnabled] = useState<Record<Overlay, boolean>>({ stations: true, nearest: true, sectors: true, routes: true });
  const projectUrl = `${apiBase}/api/v1/projects/${encodeURIComponent(projectId)}`;
  useEffect(() => {
    let active = true;
    fetch(`${projectUrl}/site-extents`).then(async response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const json = await response.json();
      if (active) { setExtents(json.extents); setExtent(json.extents.at(-1)?.id ?? ''); }
    }).catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [projectUrl]);
  useEffect(() => {
    if (!busy || startedAt === null) return;
    const timer = window.setInterval(() => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000)), 250);
    return () => window.clearInterval(timer);
  }, [busy, startedAt]);
  function acceptJob(job: BasicAnalysisJob) {
    setJobStatus(job.status);
    setCacheHit(Boolean(job.cache_hit));
    if (job.status === 'SUCCEEDED' && job.result) {
      setData(job.result);
      setLastAnalysisAt(job.last_analysis_at ?? job.result.created_at);
    }
    if (job.status === 'FAILED') setError(job.error || c.unavailable);
  }
  async function waitForJob(id: string) {
    while (true) {
      await new Promise(resolve => window.setTimeout(resolve, 250));
      const response = await fetch(`${projectUrl}/site-analysis/basic/jobs/${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      const job = await response.json() as BasicAnalysisJob;
      acceptJob(job);
      if (job.status === 'SUCCEEDED' || job.status === 'CANCELLED') return;
      if (job.status === 'FAILED') throw new Error(job.error || c.unavailable);
    }
  }
  async function load() {
    if (!extent || busy) return;
    setBusy(true); setError(''); setJobStatus('PENDING'); setJobId(null); setCancelRequested(false); setStartedAt(Date.now()); setElapsedSeconds(0); setCacheHit(false);
    try {
      const response = await fetch(`${projectUrl}/site-analysis/basic/jobs`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ extent_id: extent }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      const job = await response.json() as BasicAnalysisJob;
      activeJobId.current = job.job_id;
      setJobId(job.job_id);
      acceptJob(job);
      if (job.status === 'SUCCEEDED') return;
      if (job.status === 'FAILED') throw new Error(job.error || c.unavailable);
      await waitForJob(job.job_id);
    } catch (e) { setError(String(e)); }
    finally { activeJobId.current = null; setBusy(false); setJobId(null); }
  }
  async function cancel() {
    const id = activeJobId.current;
    if (!id || cancelRequested) return;
    setCancelRequested(true); setJobStatus('CANCELLING');
    try {
      const response = await fetch(`${projectUrl}/site-analysis/basic/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      acceptJob(await response.json() as BasicAnalysisJob);
    } catch (e) { setError(String(e)); }
  }
  return <section aria-label={c.title} style={{ width: '100%', height: '100%', overflow: 'auto', padding: 16 }}>
    <div className="ribbon-group ribbon-actions"><div className="ribbon-tools"><h2>{c.title}</h2><button onClick={onClose}>{c.close}</button>
      <label>{c.extent}<select value={extent} aria-label={c.extent} disabled={busy} onChange={e => { setExtent(e.target.value); setData(null); setLastAnalysisAt(null); setCacheHit(false); }}>
        {extents.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
      </select></label><button className="ribbon-btn-primary" disabled={!extent || busy} onClick={load}>{busy ? c.analysing : c.load}</button>
      {busy && jobId && <button disabled={cancelRequested || jobStatus === 'CANCELLING'} onClick={cancel}>{cancelRequested || jobStatus === 'CANCELLING' ? c.cancelling : c.cancel}</button>}
    </div></div>
    {busy && <output role="status" aria-live="polite">{c.elapsed}: {`${Math.floor(elapsedSeconds / 60).toString().padStart(2, '0')}:${(elapsedSeconds % 60).toString().padStart(2, '0')}`} · {jobStatus || 'RUNNING'}</output>}
    <p><strong>{c.estimate}</strong></p>{!extents.length && <p>{c.empty}</p>}{error && <p role="alert">{c.unavailable}: {error}</p>}
    {data && <><p>{c.status}: {data.status} · {c.closest}: {data.closest_transit_sides.join(' / ') || c.noData}</p>
      {lastAnalysisAt && <p>{c.lastAnalysis}: <time dateTime={lastAnalysisAt}>{lastAnalysisAt}</time>{cacheHit && <> · <span>{c.cached}</span></>}</p>}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>{(Object.keys(enabled) as Overlay[]).map(key => <label key={key}><input type="checkbox" checked={enabled[key]} onChange={e => setEnabled({ ...enabled, [key]: e.target.checked })} />{c[key]}</label>)}</div>
      <BasicMap data={data.overlay_wgs84} enabled={enabled} errorText={c.mapError} />
      <h3>{c.transit}</h3><table><thead><tr><th>{c.closest}</th><th>{c.uses}</th><th>{c.station}</th><th>{c.distance} (m)</th></tr></thead><tbody>
        {data.transit.flatMap(side => Object.entries(side.nearest_by_mode).map(([mode, route]) => <tr key={`${side.side}-${mode}`}><td>{side.side}</td><td>{mode}</td><td>{route ? route.name || c.unknown : c.noData}{route?.routes?.length ? <small> · {route.routes.map(line => line.name || line.ref || '').join(', ')}</small> : null}</td><td>{route?.distance_m.toFixed(1) ?? '—'}</td></tr>))}
      </tbody></table>
      <h3>{c.landuse}</h3>{data.landuse.map(side => <p key={side.side}><strong>{side.side}</strong> · {c.bag}: {Object.entries(side.bag_usage_percent).map(([use, percent]) => `${use} ${percent}%`).join(', ') || c.noData} ({side.bag_floor_area_m2.toFixed(0)} {c.area}; {c.missingArea}: {side.missing_area_count}) · {c.osm}: {Object.entries(side.osm_ring_area_percent).map(([use, percent]) => `${use} ${percent}%`).join(', ') || c.noData}</p>)}
      <h3>{c.entrances}</h3><p>{c.syntax}: {data.syntax.status}</p><ol>{data.entrances.map(entry => <li key={entry.id}>{entry.id} ({entry.side}) · {c.potential}: {entry.distance_potential.toFixed(3)}
        {entry.major_routes.map(route => <p key={route.origin_id}>{route.name || route.origin_id} · {route.distance_m.toFixed(1)} m · Syntax {route.syntax.coverage_ratio === undefined ? '—' : `${(route.syntax.coverage_ratio * 100).toFixed(0)}%`} · NAIN {route.syntax.nain_mean?.toFixed(3) ?? '—'} / NACH {route.syntax.nach_mean?.toFixed(3) ?? '—'}</p>)}
      </li>)}</ol>
      <details><summary>{c.hashes}</summary>{Object.entries(data.source_hashes).map(([key, hash]) => <p key={key}>{key}: <code>{hash}</code></p>)}<h4>{c.parameters}</h4><pre>{JSON.stringify(data.parameters, null, 2)}</pre></details>
      <h3>{c.limitations}</h3><ul>{data.limitations.map(item => <li key={item}>{item}</li>)}</ul>
    </>}
    <JudgementPanel apiBase={apiBase} projectId={projectId} skillId="J-SITE" />
  </section>;
}
