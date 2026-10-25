// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('./JudgementCard', () => ({JudgementPanel: ({skillId, subjectIds}: {skillId:string;subjectIds?:string[]}) => <section data-testid="judgement-placement" data-skill={skillId} data-subjects={subjectIds?.join(',')} />}));
import { SiteBasicAnalysis, selectedBasicOverlay, type BasicAnalysis } from './SiteBasicAnalysis';
import { I18nProvider } from '../i18n';
vi.mock('maplibre-gl', () => ({ default: { Map: class { addControl() {} on() {} remove() {} getSource() {} }, AttributionControl: class {}, NavigationControl: class {} } }));
const data: BasicAnalysis = {
  status: 'EXPLORATORY', created_at: '2026-10-08T05:00:00Z', closest_transit_sides: ['W'], parameters: { status: 'ASSUMED_COMMANDER' }, source_hashes: { bag: 'sha256:abc' }, limitations: ['No observed flow'],
  transit: [{ side: 'W', status: 'ROUTED', nearest_by_mode: { bus: { origin_id: 'stop', name: 'West stop', kind: 'transit', distance_m: 210, connector_m: 0, syntax: {} } } }],
  landuse: [{ side: 'N', bag_floor_area_m2: 1000, bag_usage_percent: { woonfunctie: 62 }, osm_ring_area_percent: { residential: 30 }, missing_area_count: 0 }],
  entrances: [{ id: 'e1', side: 'W', rank: 1, distance_potential: 1.25, reachable_origins: 1, major_routes: [] }], syntax: { status: 'UNAVAILABLE' },
  overlay_wgs84: { type: 'FeatureCollection', features: ['station', 'nearest_route', 'sector', 'arrival_route', 'entrance'].map(kind => ({ type: 'Feature', properties: { kind }, geometry: { type: 'Point', coordinates: [4.43, 51.91] } })) },
};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
  if (url.endsWith('/site-extents')) return { ok: true, json: async () => ({ extents: [{ id: 'extent1' }] }) };
  if (url.endsWith('/site-analysis/basic/jobs') && init?.method === 'POST') {
    return { ok: true, json: async () => ({ job_id: 'job1', status: 'SUCCEEDED', cache_hit: false, last_analysis_at: data.created_at, result: data }) };
  }
  throw new Error(`Unexpected request: ${url}`);
})));
it('fetches project-bound analysis and shows network distances, area shares, assumptions and estimate label', async () => {
  render(<SiteBasicAnalysis apiBase="" projectId="p" onClose={() => {}} />);
  expect(screen.getByTestId('judgement-placement').dataset.skill).toBe('J-SITE');
  const button = screen.getByRole('button', { name: 'Analyse site' });
  expect(button).toBeDisabled();
  await screen.findByRole('option', { name: 'extent1' });
  fireEvent.click(button);
  await screen.findByText('West stop');
  expect(fetch).toHaveBeenCalledWith('/api/v1/projects/p/site-analysis/basic/jobs', expect.objectContaining({ method: 'POST', body: JSON.stringify({ extent_id: 'extent1' }) }));
  expect(screen.getByText('210.0')).toBeVisible();
  expect(screen.getByText('Estimated arrival potential — not observed pedestrian flow.')).toBeVisible();
  expect(screen.getByText(/woonfunctie 62%/)).toBeVisible();
  expect(screen.getByText('sha256:abc')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Stations' }));
  expect(screen.getByRole('checkbox', { name: 'Stations' })).not.toBeChecked();
});
it('filters each map overlay independently', () => {
  const result = selectedBasicOverlay(data.overlay_wgs84, { stations: false, nearest: true, sectors: false, routes: true });
  expect(result.features.map(f => f.properties?.kind)).toEqual(['nearest_route', 'arrival_route', 'entrance']);
});
it('supports Traditional Chinese and preserves API errors as unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/site-extents') ? { ok: true, json: async () => ({ extents: [{ id: 'e' }] }) } : { ok: false, status: 409, text: async () => 'MISSING_BASIC_SOURCE' }));
  render(<I18nProvider language="zh-TW"><SiteBasicAnalysis apiBase="" projectId="p" onClose={() => {}} /></I18nProvider>);
  await screen.findByRole('option', { name: 'e' });
  fireEvent.click(screen.getByRole('button', { name: '分析基地' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('MISSING_BASIC_SOURCE');
  expect(screen.getByText('推估的到達潛力，並非觀測行人人流。')).toBeVisible();
});

it('uses app ribbon styles and keeps Analyse site visible while a cancellable job runs', async () => {
  let cancelRequested = false;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/site-extents')) return { ok: true, json: async () => ({ extents: [{ id: 'extent1' }] }) };
    if (url.endsWith('/site-analysis/basic/jobs') && init?.method === 'POST') {
      return { ok: true, status: 202, json: async () => ({ job_id: 'job1', status: 'RUNNING', cache_hit: false }) };
    }
    if (url.endsWith('/site-analysis/basic/jobs/job1') && init?.method === 'DELETE') {
      cancelRequested = true;
      return { ok: true, json: async () => ({ job_id: 'job1', status: 'CANCELLING' }) };
    }
    if (url.endsWith('/site-analysis/basic/jobs/job1')) {
      return { ok: true, json: async () => ({ job_id: 'job1', status: cancelRequested ? 'CANCELLED' : 'RUNNING', elapsed_seconds: 1 }) };
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<SiteBasicAnalysis apiBase="" projectId="p" onClose={() => {}} />);
  await screen.findByRole('option', { name: 'extent1' });
  const analyse = screen.getByRole('button', { name: 'Analyse site' });
  expect(analyse.closest('.ribbon-group')).not.toBeNull();
  expect(analyse).toHaveClass('ribbon-btn-primary');
  fireEvent.click(analyse);
  expect(await screen.findByRole('button', { name: 'Analysing…' })).toBeDisabled();
  expect(screen.getByRole('status')).toHaveTextContent(/Elapsed: /);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel analysis' }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/projects/p/site-analysis/basic/jobs/job1', expect.objectContaining({ method: 'DELETE' })));
  await screen.findByRole('button', { name: 'Analyse site' });
});

it('shows the last analysis time when the API returns a cached result', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/site-extents')) return { ok: true, json: async () => ({ extents: [{ id: 'extent1' }] }) };
    if (url.endsWith('/site-analysis/basic/jobs') && init?.method === 'POST') {
      return { ok: true, status: 200, json: async () => ({ job_id: 'cached1', status: 'SUCCEEDED', cache_hit: true, last_analysis_at: data.created_at, result: data }) };
    }
    throw new Error(`Unexpected request: ${url}`);
  }));
  render(<SiteBasicAnalysis apiBase="" projectId="p" onClose={() => {}} />);
  await screen.findByRole('option', { name: 'extent1' });
  fireEvent.click(screen.getByRole('button', { name: 'Analyse site' }));
  expect(await screen.findByText(/Last analysis:/)).toHaveTextContent(data.created_at);
  expect(screen.getByText('Cached result')).toBeVisible();
});
