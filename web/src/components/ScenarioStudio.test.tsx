// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScenarioStudio } from './ScenarioStudio';
import { CompareWorkspace } from './CompareWorkspace';
import { I18nProvider } from '../i18n';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const summary = (scenarioId: string, label: string) => ({
  scenario_id: scenarioId,
  status: 'PROPOSED',
  provenance: 'FIXTURE_ONLY',
  valid: true,
  failure_reasons: [],
  strategy_label: label,
  strategy_explanation_status: '非 AI 生成',
  strategy_explanation: `${label}：確定性模板說明。`,
  metrics: {
    far: { value: 0.55, unit: 'ratio', method: 'fixture GFA / area', validation_status: 'VALIDATED', data_gaps: ['合成輸入'] },
    coverage_ratio: { value: 0.28, unit: 'ratio', method: 'footprint / area', validation_status: 'VALIDATED', data_gaps: [] },
    height_m: { value: 12, unit: 'm', method: 'floor height', validation_status: 'VALIDATED', data_gaps: [] },
    road_ratio: { value: 0.1, unit: 'ratio', method: 'road / area', validation_status: 'VALIDATED', data_gaps: [] },
    open_space_ratio: { value: 0.3, unit: 'ratio', method: 'open / area', validation_status: 'VALIDATED', data_gaps: [] },
  },
});

const floor = (floorId: string, level: number) => ({
  floor_id: floorId,
  level,
  geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 8], [0, 8], [0, 0]]] },
});

const roadGraph = {
  graph_hash: 'graph-before',
  nodes: [
    { node_id: 'west', x_m: 0, y_m: 0, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'east', x_m: 10, y_m: 0, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'moving', x_m: 4, y_m: 10, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'tail', x_m: 4, y_m: 20, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'endpoint', x_m: 5, y_m: 1, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'endpoint-tail', x_m: 5, y_m: 5, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'locked', x_m: 20, y_m: 0, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'locked-tail', x_m: 20, y_m: 10, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
  ],
  edges: [
    { edge_id: 'horizontal', start_node_id: 'west', end_node_id: 'east', layer: 0, bridge: false, tunnel: false, locked: false, lineage_ids: [] },
    { edge_id: 'moving-spur', start_node_id: 'moving', end_node_id: 'tail', layer: 0, bridge: false, tunnel: false, locked: false, lineage_ids: [] },
    { edge_id: 'endpoint-link', start_node_id: 'endpoint', end_node_id: 'endpoint-tail', layer: 0, bridge: false, tunnel: false, locked: false, lineage_ids: [] },
    { edge_id: 'locked-road', start_node_id: 'locked', end_node_id: 'locked-tail', layer: 0, bridge: false, tunnel: false, locked: true, lineage_ids: [] },
  ],
};

const roadFeatures = roadGraph.edges.map((edge) => {
  const start = roadGraph.nodes.find((node) => node.node_id === edge.start_node_id)!;
  const end = roadGraph.nodes.find((node) => node.node_id === edge.end_node_id)!;
  return {
    id: edge.edge_id,
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [[start.x_m, start.y_m], [end.x_m, end.y_m]] },
    properties: { feature_kind: 'road_centerline', locked: edge.locked },
  };
});

const detail = (activeRevisionId = 0, far = 0.55, graphHash = 'graph-before', syntaxStatus = 'CURRENT', dependencyStatus?: 'CURRENT' | 'STALE') => ({
  ...summary('scenario-one', 'Courtyard'),
  revision: activeRevisionId + 1,
  metrics: { ...summary('scenario-one', 'Courtyard').metrics, far: { value: far, unit: 'ratio', method: 'fixture GFA / area', validation_status: 'VALIDATED', data_gaps: ['合成輸入'] } },
  geometry: {
    type: 'FeatureCollection',
    features: [...roadFeatures, {
      id: 'building-a',
      type: 'Feature',
      geometry: floor('floor-a', 0).geometry,
      properties: { feature_kind: 'building', floor_count: 2, use_label: 'mixed' },
    }],
  },
  editor: {
    provenance: 'FIXTURE_ONLY',
    design_area_m2: 8000,
    limits: { far_upper_bound: 0.8, max_coverage_ratio: 0.35, max_height_m: 18 },
    editable_buildings: [{
      building_id: 'building-a',
      floors: [floor('building-a-floor-1', 0), floor('building-a-floor-2', 1)],
      first_floor_height_m: 3,
      standard_floor_height_m: 3,
      geometry_hash: 'geometry-hash-a',
      use_label: 'mixed',
    }],
    active_buildings: {},
    active_edit_revision_id: activeRevisionId,
    road_graph: { ...roadGraph, graph_hash: graphHash },
    road_edit_revision_id: 0,
    road_snap_tolerance_m: 2,
    road_edit_policy_version: 'fixture-road-snap-v1',
    syntax_result_ids: ['syntax-800m-fixture'],
    syntax_statuses: { 'syntax-800m-fixture': syntaxStatus },
    ...(dependencyStatus ? {
      accessibility_result_ids: ['access-fixture'],
      accessibility_statuses: { 'access-fixture': dependencyStatus },
      e1_result_ids: ['e1-fixture'],
      e1_statuses: { 'e1-fixture': dependencyStatus },
    } : {}),
  },
});


describe('ScenarioStudio', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('loads persisted candidates and displays evidence fields without ranking', async () => {
    const candidates = [summary('scenario-one', 'Courtyard'), summary('scenario-two', 'Perimeter')];
    let comparisonRequest: unknown;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/v1/scenarios') && !init?.method) return new Response(JSON.stringify({ scenarios: candidates }), { status: 200 });
      if (url.endsWith('/api/v1/scenarios/scenario-one')) return new Response(JSON.stringify(detail()), { status: 200 });
      if (url.endsWith('/api/v1/scenarios/comparison')) {
        comparisonRequest = JSON.parse(String(init?.body));
        return new Response(JSON.stringify({
          status: 'COMPARABLE',
          scenario_ids: ['scenario-one', 'scenario-two'],
          ranking: null,
          overall_score: null,
          metrics: [{ metric_id: 'far', label: 'FAR', unit: 'ratio', method: 'GFA / area', data_gaps: ['合成輸入'], validation_status: { 'scenario-one': 'VALIDATED', 'scenario-two': 'VALIDATED' }, status: 'COMPARABLE', values: { 'scenario-one': 0.55, 'scenario-two': 0.62 } }],
        }), { status: 200 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    await screen.findByRole('button', { name: 'Inspect Courtyard' });
    const checks = screen.getAllByRole('checkbox');
    fireEvent.click(checks[0]!);
    fireEvent.click(checks[1]!);
    fireEvent.click(screen.getByRole('button', { name: /Compare selected scenarios/ }));

    await screen.findByRole('region', { name: 'Scenario comparison table' });
    expect(comparisonRequest).toEqual({ scenario_ids: ['scenario-one', 'scenario-two'] });
    expect(screen.getByText('GFA / area')).toBeTruthy();
    expect(screen.getByText('合成輸入')).toBeTruthy();
    expect(screen.queryByText(/排名|總分|overall score|ranking/i)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Courtyard' }));
    expect(await screen.findByRole('group', { name: 'Scenario EPSG:28992 plan and road-node editor' })).toBeTruthy();
    expect(screen.getByText(/Not AI-generated/)).toBeTruthy();
  });

  it('sends a DRAFT massing edit with the active revision and renders confirmed dashboard values', async () => {
    let persisted = detail();
    let editBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/v1/scenarios') && !init?.method) return new Response(JSON.stringify({ scenarios: [summary('scenario-one', 'Courtyard')] }), { status: 200 });
      if (url.endsWith('/api/v1/scenarios/scenario-one') && !init?.method) return new Response(JSON.stringify(persisted), { status: 200 });
      if (url.endsWith('/api/v1/scenarios/scenario-one/edits')) {
        editBody = JSON.parse(String(init?.body));
        persisted = detail(1, 0.58);
        return new Response(JSON.stringify({ status: 'DRAFT', revision_id: 1, dashboard: { metric_state: 'BACKEND_CONFIRMED' } }), { status: 201 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    await screen.findByRole('button', { name: 'Inspect Courtyard' });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Courtyard' }));
    await screen.findByRole('group', { name: 'Scenario EPSG:28992 plan and road-node editor' });
    fireEvent.click(screen.getByRole('button', { name: 'Add one floor' }));

    await screen.findByText(/Server confirmed DRAFT revision saved/);
    expect(editBody).toEqual(expect.objectContaining({
      building_id: 'building-a',
      command: { type: 'add_floor', new_floor_id: 'building-a-floor-3' },
      expected_revision: 0,
      idempotency_key: expect.any(String),
    }));
    expect(screen.getByText('0.58')).toBeTruthy();
    expect(screen.getByText(/DRAFT revision 1/)).toBeTruthy();
  });

  it('previews snap kinds, blocks locked roads, posts the move, and displays validation, graph hashes, and STALE Syntax', async () => {
    let roadEdited = false;
    let roadEditBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/v1/scenarios') && !init?.method) return new Response(JSON.stringify({ scenarios: [summary('scenario-one', 'Courtyard')] }), { status: 200 });
      if (url.endsWith('/api/v1/scenarios/scenario-one') && !init?.method) {
        return new Response(JSON.stringify(roadEdited ? detail(0, 0.55, 'graph-after', 'STALE', 'STALE') : detail()), { status: 200 });
      }
      if (url.endsWith('/api/v1/scenarios/scenario-one/road-nodes/moving/move')) {
        roadEditBody = JSON.parse(String(init?.body));
        roadEdited = true;
        return new Response(JSON.stringify({
          status: 'DRAFT',
          revision_id: 1,
          snap_kind: 'NEAREST_POINT',
          snapped_to_edge_id: 'horizontal',
          graph_hash_before: 'graph-before',
          graph_hash_after: 'graph-after',
          stale_syntax_result_ids: ['syntax-800m-fixture'],
          validation: { status: 'PASS', valid: true },
        }), { status: 201 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    await screen.findByRole('button', { name: 'Inspect Courtyard' });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Courtyard' }));
    const svg = await screen.findByRole('group', { name: 'Scenario EPSG:28992 plan and road-node editor' });
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 600, bottom: 400, width: 600, height: 400,
      toJSON: () => ({}),
    } as DOMRect);
    // Fixture spans 0–20 m on both axes; uniform scale min(528/20, 328/20) = 16.4 px/m, centred horizontally.
    const clientPoint = (x_m: number, y_m: number) => ({
      clientX: 36 + (528 - 20 * 16.4) / 2 + x_m * 16.4,
      clientY: 36 + (20 - y_m) * 16.4,
      pointerId: 1,
    });

    const lockedNode = screen.getByRole('button', { name: 'Road node locked · locked' });
    expect(lockedNode.getAttribute('aria-disabled')).toBe('true');
    fireEvent.pointerDown(lockedNode, clientPoint(20, 0));
    fireEvent.pointerMove(svg, clientPoint(4.4, 0.2));
    expect(screen.queryByText(/吸附候選：/)).toBeNull();
    expect(roadEditBody).toBeNull();

    fireEvent.pointerDown(screen.getByRole('button', { name: 'Road node moving · draggable' }), clientPoint(4, 10));
    fireEvent.pointerMove(svg, clientPoint(4.4, 0.2));
    expect(await screen.findByText(/Endpoint endpoint（1.00 m）；Nearest point horizontal（0.20 m）/)).toBeTruthy();
    fireEvent.pointerUp(svg, clientPoint(4.4, 0.2));

    expect(await screen.findByText(/Validation PASS/)).toBeTruthy();
    expect(screen.getByText(/Nearest point horizontal/)).toBeTruthy();
    expect(screen.getByText(/Graph hash graph-before → graph-after/)).toBeTruthy();
    expect((await screen.findByText('syntax-800m-fixture · STALE')).className).toContain('is-stale');
    expect(screen.getByText('access-fixture · STALE').className).toContain('is-stale');
    expect(screen.getByText('e1-fixture · STALE').className).toContain('is-stale');
    expect(roadEditBody).toEqual({
      x_m: expect.any(Number),
      y_m: expect.any(Number),
      expected_revision: 0,
      idempotency_key: expect.any(String),
    });
    expect(roadEditBody).not.toHaveProperty('syntax_result_ids');
    expect(roadEditBody).not.toHaveProperty('snap_tolerance_m');
    const postedCoordinates = roadEditBody as { x_m: number; y_m: number } | null;
    expect(postedCoordinates?.x_m).toBeCloseTo(4.4, 5);
    expect(postedCoordinates?.y_m).toBeCloseTo(0.2, 5);
  });
});

const previewCard = (intensity: 'A' | 'B', index: number) => ({
  identity: {
    intensity,
    strategy_id: 'strategy_' + index,
    status: 'UNAPPROVED_PREVIEW',
    human_decision_created: false,
    generator_version: 'dictionary-generator-v4',
    run_created_at: null,
    generator_commit: null,
  },
  strategy_label: 'Strategy ' + index,
  limits: {
    intensity,
    far_upper_bound_land: intensity === 'A' ? 1.592296 : 2,
    coverage_upper_bound: intensity === 'A' ? null : 0.5,
    height_upper_bound_new_buildings_m: intensity === 'A' ? 20 : 40,
  },
  metrics: {
    building_count: 12,
    known_part_land_far: 1.25,
    coverage_ratio: 0.25,
    maximum_height_m: 20,
    open_space_ratio: 0.5,
    generator_valid: true,
    warnings: ['1 unknown retained floor estimate(s); known-part FAR is reported separately'],
  },
  retained_buildings: [{
    feature_id: 'retained-1', confidence: 'LOW', floor_estimate_status: 'UNKNOWN',
    floor_count: null, height_m: null,
  }],
  input_refs: [],
  limitations: ['Run creation time is UNKNOWN.'],
  verified_at_utc: '2026-09-30T10:15:00Z',
  source_reverified: false,
  assets: {
    plan: '/api/v1/morphology/previews/' + intensity + '/strategy_' + index + '/assets/plan',
    axonometric: '/api/v1/morphology/previews/' + intensity + '/strategy_' + index + '/assets/axonometric',
    geometry: '/api/v1/morphology/previews/' + intensity + '/strategy_' + index + '/assets/geometry',
  },
});

const previewCatalog5Plus5 = {
  status: 'AVAILABLE',
  count: 10,
  verified_at_utc: '2026-09-30T10:15:00Z',
  source_reverified: false,
  previews: [
    ...Array.from({ length: 5 }, (_, i) => previewCard('A', i + 1)),
    ...Array.from({ length: 5 }, (_, i) => previewCard('B', i + 1)),
  ],
  limits: [
    { intensity: 'A', far_upper_bound_land: 1.59, coverage_upper_bound: null, height_upper_bound_new_buildings_m: 20 },
    { intensity: 'B', far_upper_bound_land: 2.0, coverage_upper_bound: 0.5, height_upper_bound_new_buildings_m: 40 },
  ],
  manifest_sha256: 'a'.repeat(64),
  comparison_sha256: 'b'.repeat(64),
  input_refs: [],
  limitations: ['Run creation time is UNKNOWN.'],
  seed: 42,
};

describe('ScenarioStudio preview tab', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('exposes linked tab panels and supports arrow-key navigation', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/api/v1/scenarios')) return new Response(JSON.stringify({ scenarios: [] }), { status: 200 });
      if (url.endsWith('/api/v1/morphology/previews')) return new Response(JSON.stringify(previewCatalog5Plus5), { status: 200 });
      throw new Error('unexpected fetch: ' + url);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    const editableTab = screen.getByRole('tab', { name: 'Editable scenarios' });
    const previewTab = screen.getByRole('tab', { name: 'Existing exploratory previews' });
    expect(editableTab.getAttribute('aria-controls')).toBe('scenario-studio-panel-editable');
    expect(previewTab.getAttribute('aria-controls')).toBe('scenario-studio-panel-previews');

    fireEvent.keyDown(editableTab, { key: 'ArrowRight' });
    expect(previewTab.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(previewTab);
    expect(await screen.findByRole('tabpanel', { name: 'Existing exploratory previews' })).toBeTruthy();
  });

  it('renders disabled state without POST calls or generation buttons', async () => {
    const fetchCalls: Array<{ url: string; method: string }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      fetchCalls.push({ url, method });
      if (url.endsWith('/api/v1/scenarios')) return new Response(JSON.stringify({ scenarios: [] }), { status: 200 });
      if (url.endsWith('/api/v1/morphology/previews')) {
        return new Response(JSON.stringify({
          status: 'DISABLED',
          count: 0,
          previews: [],
          limits: [],
          manifest_sha256: null,
          comparison_sha256: null,
          input_refs: [],
          limitations: [],
          seed: null,
        }), { status: 200 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    const previewTabButton = screen.getByRole('tab', { name: 'Existing exploratory previews' });
    fireEvent.click(previewTabButton);

    expect(await screen.findByText('Preview catalog disabled.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create synthetic candidates' })).toBeNull();
    expect(screen.queryByRole('button', { name: /accept|approve|edit/i })).toBeNull();
    expect(fetchCalls.every((c) => c.method === 'GET')).toBe(true);
    expect(fetchCalls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('renders loading state without POST calls', async () => {
    const fetchCalls: Array<{ url: string; method: string }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      fetchCalls.push({ url, method });
      if (url.endsWith('/api/v1/scenarios')) return Promise.resolve(new Response(JSON.stringify({ scenarios: [] }), { status: 200 }));
      if (url.endsWith('/api/v1/morphology/previews')) {
        return new Promise(() => {});
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    fireEvent.click(screen.getByRole('tab', { name: 'Existing exploratory previews' }));

    expect(await screen.findByText('Loading existing previews…')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create synthetic candidates' })).toBeNull();
    expect(fetchCalls.every((c) => c.method === 'GET')).toBe(true);
  });

  it('renders error state properly and never renders as "0 個方案"', async () => {
    const fetchCalls: Array<{ url: string; method: string }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      fetchCalls.push({ url, method });
      if (url.endsWith('/api/v1/scenarios')) return new Response(JSON.stringify({ scenarios: [] }), { status: 200 });
      if (url.endsWith('/api/v1/morphology/previews')) {
        return new Response(JSON.stringify({ detail: 'Configured morphology preview bundle is unavailable (category=hash_mismatch).' }), { status: 503 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    fireEvent.click(screen.getByRole('tab', { name: 'Existing exploratory previews' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Preview catalog unavailable');
    expect(screen.queryByText(/0 個方案/)).toBeNull();
    expect(screen.queryByText(/目前沒有方案/)).toBeNull();
    expect(fetchCalls.every((c) => c.method === 'GET')).toBe(true);
  });

  it('renders 5+5 success state with A/B assumption sets, no ranking, no winner, and no POST calls', async () => {
    const fetchCalls: Array<{ url: string; method: string }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      fetchCalls.push({ url, method });
      if (url.endsWith('/api/v1/scenarios')) return new Response(JSON.stringify({ scenarios: [] }), { status: 200 });
      if (url.endsWith('/api/v1/morphology/previews')) {
        return new Response(JSON.stringify(previewCatalog5Plus5), { status: 200 });
      }
      if (url.includes('/assets/geometry')) {
        return new Response(JSON.stringify({
          type: 'FeatureCollection',
          features: [{
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] },
            properties: {},
          }],
        }), { status: 200, headers: { 'Content-Type': 'application/geo+json' } });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<ScenarioStudio apiBase="http://fixture.test" />);
    fireEvent.click(screen.getByRole('tab', { name: 'Existing exploratory previews' }));

    expect(await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Assumption set B (5 previews)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open A: Strategy 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open B: Strategy 5' })).toBeTruthy();

    expect(screen.queryByText(/排名|winner|overall winner|rank/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /accept|approve|edit|產生合成候選/i })).toBeNull();
    expect(screen.getAllByText('UNAPPROVED_PREVIEW').length).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getByRole('button', { name: 'Open B: Strategy 2' }));
    fireEvent.click(screen.getByRole('button', { name: 'Geometry' }));
    expect(await screen.findByLabelText('Preview geometry in EPSG:28992')).toBeTruthy();

    expect(fetchCalls.every((c) => c.method === 'GET')).toBe(true);
    expect(fetchCalls.some((c) => c.method === 'POST')).toBe(false);
  });
});

it('submits signed whole-metre dx/dy through the authoritative massing edit endpoint', async () => {
  let command: unknown;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/api/v1/scenarios')) return new Response(JSON.stringify({ scenarios: [summary('scenario-one', 'Courtyard')] }));
    if (url.endsWith('/scenario-one/edits')) { command = JSON.parse(String(init?.body)).command; return new Response('{}'); }
    if (url.endsWith('/scenario-one')) return new Response(JSON.stringify(detail()));
    throw new Error(url);
  });
  render(<ScenarioStudio apiBase="" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Courtyard' }));
  fireEvent.change(await screen.findByLabelText('Move dx (metres)'), { target: { value: '-2' } });
  fireEvent.change(screen.getByLabelText('Move dy (metres)'), { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply move' }));
  await screen.findByText(/Server confirmed DRAFT revision saved/);
  expect(command).toEqual({ type: 'move', dx_m: -2, dy_m: 3 });
  cleanup(); vi.restoreAllMocks();
});

it('subtracts courtyard holes from selected-building preview GFA', async () => {
  const courtyard = detail();
  courtyard.editor.editable_buildings[0].floors = [{ ...floor('courtyard-floor', 0), geometry: { type: 'Polygon', coordinates: [[[0,0],[10,0],[10,8],[0,8],[0,0]], [[2,2],[4,2],[4,4],[2,4],[2,2]]] } }];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).endsWith('/api/v1/scenarios') ? { scenarios: [summary('scenario-one', 'Courtyard')] } : courtyard)));
  render(<ScenarioStudio apiBase="" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Courtyard' }));
  expect(await screen.findByText('76m²')).toBeTruthy();
  cleanup(); vi.restoreAllMocks();
});

it('reloads formal geometry and both dashboards after a successful face edit', async () => {
  let edited = false;
  let detailLoads = 0;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/api/v1/scenarios')) return new Response(JSON.stringify({ scenarios: [summary('scenario-one', 'Courtyard')] }));
    if (url.includes('/editing/faces')) {
      if (init?.method === 'POST') edited = true;
      return new Response(JSON.stringify({ scenario_revision: edited ? 2 : 1, face_revision: edited ? 1 : 0, geometry_hash: edited ? 'after' : 'before', faces: [{ id: 'top', floor_id: 'floor', kind: 'TOP', parent_revision: edited ? 1 : 0, triangles: [] }] }));
    }
    if (url.endsWith('/scenario-one')) {
      detailLoads++;
      const next = detail(edited ? 1 : 0);
      next.provenance = 'FORMAL_DRAFT';
      if (edited) next.editor.editable_buildings[0].floors.push(floor('floor-new', 2));
      return new Response(JSON.stringify(next));
    }
    return new Response(JSON.stringify({ status: 'NOT_READY' }));
  });
  render(<ScenarioStudio apiBase="" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Courtyard' }));
  await screen.findByRole('region', { name: 'Formal draft road snapping' });
  await screen.findByText('top / r0');
  fireEvent.change(screen.getByLabelText('Operation'), { target: { value: 'TOP_EXTRUDE' } });
  fireEvent.click(screen.getByText('Apply formal face edit'));
  expect(await screen.findByText('240m²')).toBeTruthy();
  expect(detailLoads).toBe(2);
  cleanup(); vi.restoreAllMocks();
});

it('does not request scenario Space Syntax for a formal draft (ineligible until proposed)', async () => {
  const urls: string[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input); urls.push(url);
    if (url.endsWith('/api/v1/scenarios')) return new Response(JSON.stringify({ scenarios: [summary('scenario-one', 'Courtyard')] }));
    if (url.endsWith('/scenario-one')) { const next = detail(); next.provenance = 'FORMAL_DRAFT'; return new Response(JSON.stringify(next)); }
    return new Response(JSON.stringify({ status: 'NOT_READY', faces: [], scenario_revision: 1, face_revision: 0, geometry_hash: 'h' }));
  });
  render(<ScenarioStudio apiBase="" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Courtyard' }));
  expect(await screen.findByText('Space Syntax is computed after the draft is proposed.')).toBeTruthy();
  expect(urls.some(url => /\/scenarios\/scenario-one\/syntax/.test(url))).toBe(false);
  cleanup(); vi.restoreAllMocks();
});

it('opens an accepted harbour passed from refinement into its formal draft', async () => {
  const accepted = {...detail(), scenario_id: 'harbour', status: 'accepted', provenance: 'FABRIC_PLAN_E2_ONLY', editor: {...detail().editor, editable_buildings: []}};
  const draft = {...detail(), scenario_id: 'harbour-draft', status: 'draft', provenance: 'FORMAL_DRAFT'};
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/formal-draft') && init?.method === 'POST') return new Response(JSON.stringify(draft), {status: 201});
    if (url.endsWith('/scenarios/harbour')) return new Response(JSON.stringify(accepted));
    if (url.endsWith('/scenarios/harbour-draft')) return new Response(JSON.stringify(draft));
    if (url.endsWith('/scenarios')) return new Response(JSON.stringify({scenarios: [accepted]}));
    return new Response(JSON.stringify({detail: 'No face fixture'}), {status: 404});
  });
  render(<ScenarioStudio apiBase="http://fixture.test" scenarioId="harbour" />);
  await screen.findByRole('option', {name: 'building-a'});
  expect(fetchSpy).toHaveBeenCalledWith('http://fixture.test/api/v1/scenarios/harbour/formal-draft', {method: 'POST'});
});


it.each([{status:200, mode:'COMPARE'}, {status:201, mode:'SPLIT'}] as const)('opens the pinned harbour through the idempotent endpoint ($status, $mode)', async ({status, mode}) => {
  const harbour = 'formal-fabric-harbour-grain-88445febe1b6';
  const draft = {...detail(), scenario_id: 'formal-draft-harbour', status: 'draft', provenance: 'FORMAL_DRAFT'};
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith(`/${harbour}/formal-draft`) && init?.method === 'POST') return new Response(JSON.stringify(draft), {status});
    if (url.endsWith('/formal-proposals')) return new Response('[]');
    if (url.endsWith('/scenarios')) return new Response(JSON.stringify({scenarios: []}));
    if (url.endsWith('/previews')) return new Response(JSON.stringify({status: 'DISABLED'}));
    return new Response(JSON.stringify({detail: 'Accepted geometry unavailable; use formal draft endpoint'}), {status: 503});
  });
  render(<CompareWorkspace apiBase="http://fixture.test" startEditing viewMode={mode} syncedViews={false} />);
  fireEvent.click(await screen.findByTestId('harbour-mainline-btn'));
  fireEvent.click(screen.getByTestId('open-scenario-editing-btn'));
  expect(await screen.findByRole('option', {name: 'building-a'})).toBeTruthy();
  expect(fetchSpy).toHaveBeenCalledWith(`http://fixture.test/api/v1/scenarios/${harbour}/formal-draft`, {method: 'POST'});
  expect(screen.queryByText('No scenario selected')).toBeNull();
  if (mode === 'SPLIT') expect(screen.getByRole('group', {name: 'Scenario EPSG:28992 plan and road-node editor'})).toBeTruthy();
  expect(screen.getByRole('region', {name: 'Massing editing tools'})).toBeTruthy();
  expect(screen.getByRole('region', {name: 'Formal face editing'})).toBeTruthy();
});


it('preserves accepted common-mixed editing without opening another formal draft', async () => {
  const accepted = {...detail(), scenario_id: 'common-mixed', status: 'accepted', provenance: 'APPROVED_INPUTS'};
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.endsWith('/scenarios')) return new Response(JSON.stringify({scenarios: [accepted]}));
    if (url.endsWith('/scenarios/common-mixed')) return new Response(JSON.stringify(accepted));
    return new Response('{}', {status: 404});
  });
  render(<ScenarioStudio apiBase="http://fixture.test" scenarioId="common-mixed" />);
  expect(await screen.findByRole('option', {name:'building-a'})).toBeTruthy();
  expect(fetchSpy.mock.calls.some(([,init]) => init?.method === 'POST')).toBe(false);
});

it('shows an authoritative harbour draft failure without selecting or retrying another draft', async () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (String(input).endsWith('/formal-draft') && init?.method === 'POST') return new Response(JSON.stringify({detail:'Draft authority blocked'}), {status:409});
    return new Response(JSON.stringify({scenarios:[]}));
  });
  render(<ScenarioStudio apiBase="http://fixture.test" scenarioId="formal-fabric-harbour-grain-88445febe1b6" />);
  expect(await screen.findByText('Draft authority blocked')).toBeTruthy();
  expect(screen.queryByRole('option', {name:'building-a'})).toBeNull();
  expect(fetchSpy.mock.calls.filter(([,init]) => init?.method === 'POST')).toHaveLength(1);
});


it('renders the collapsed W6 history heading in Traditional Chinese', async () => {
 vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({scenarios:[summary('common-mixed','歷史混合方案')]})));
 render(<I18nProvider language="zh-TW"><ScenarioStudio apiBase="http://fixture.test" /></I18nProvider>);
 const history = await screen.findByTestId('scenario-catalog-historical');
 expect(history.querySelector('summary')?.textContent).toContain('歷史方案');
 expect(history.textContent).not.toContain('Historical scenarios');
 expect(history.hasAttribute('open')).toBe(false);
});

it('fits real EPSG:28992 coordinates into the plan instead of collapsing them to a dot', async () => {
  const shifted = detail();
  const shift = (c: unknown): unknown => Array.isArray(c) && typeof c[0] === 'number' ? [(c as number[])[0] + 88600, (c as number[])[1] + 435500] : Array.isArray(c) ? c.map(shift) : c;
  shifted.geometry.features = shifted.geometry.features.map(f => ({ ...f, geometry: { ...f.geometry, coordinates: shift(f.geometry.coordinates) } })) as typeof shifted.geometry.features;
  shifted.editor.road_graph = { ...shifted.editor.road_graph, nodes: shifted.editor.road_graph.nodes.map(n => ({ ...n, x_m: n.x_m + 88600, y_m: n.y_m + 435500 })) };
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).endsWith('/api/v1/scenarios') ? { scenarios: [summary('scenario-one', 'Courtyard')] } : shifted)));
  render(<ScenarioStudio apiBase="" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Courtyard' }));
  const svg = await screen.findByRole('group', { name: 'Scenario EPSG:28992 plan and road-node editor' });
  const xs = [...svg.querySelectorAll('path')].flatMap(path => [...(path.getAttribute('d') ?? '').matchAll(/[ML] ([-\d.]+) ([-\d.]+)/g)].map(m => Number(m[1])));
  expect(xs.length).toBeGreaterThan(0);
  expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(100);
  expect(Math.min(...xs)).toBeGreaterThanOrEqual(36);
  expect(Math.max(...xs)).toBeLessThanOrEqual(564);
  cleanup(); vi.restoreAllMocks();
});
