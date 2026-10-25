// @vitest-environment jsdom
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import App from './App';
vi.mock('./components/Viewport2D', () => ({Viewport2D:({selectedFeatureId}: {selectedFeatureId?: string | null})=> <div data-testid="plan" data-selected-feature={selectedFeatureId ?? ''} />}));
vi.mock('./components/Viewport3D', () => ({Viewport3D:()=> <div data-testid="volume" />}));
vi.mock('./components/FabricCompare', () => ({FabricCompare:()=> <div data-testid="fabric-workspace" />}));
vi.mock('./components/CompareWorkspace', () => ({CompareWorkspace:()=> <div data-testid="compare" />}));
afterEach(()=> {cleanup();localStorage.clear();vi.restoreAllMocks();});
test('shell renders the Ariadne brand logo with an i18n alt label and no action', () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:true,json:async()=>({buildings:[],roads:[],evidence_cards:[],evidence_gaps:[],syntax_layers:[]})}));
  render(<App/>);
  const logo=screen.getByRole('img',{name:'Ariadne'});
  expect(logo.getAttribute('src')).toBe('/ariadne-brand.png');
  expect(logo.closest('button, a')).toBeNull();
});
test('five stages keep a central view and language switch updates visible shell text', async()=> {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({buildings:[],roads:[],evidence_cards:[],evidence_gaps:[],syntax_layers:[]})}));
  const {container}=render(<App/>);
  expect(screen.getByRole('navigation').textContent).toBe('SiteConditionsGenerateCompareRefine');
  expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/);
  expect(container.querySelector('.app-header__view-switcher')).toBeNull();
  const languageToggle = container.querySelector<HTMLButtonElement>('#language-toggle');
  expect(languageToggle?.style.color).toBe('rgb(248, 250, 252)');
  expect(languageToggle?.style.backgroundColor).toBe('rgb(30, 41, 59)');
  expect(languageToggle?.textContent).toBe('English ▾');
  expect(languageToggle?.getAttribute('aria-label')).toBe('Current language: English; click to switch language');
  expect(screen.queryByRole('button', {name:'Sync Workspace'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Conditions'}));
  expect(screen.getByRole('button', {name:'Sync Workspace'}).closest('.ribbon-group')).not.toBeNull();
  expect(screen.getByRole('button', {name:'Confirm Day 1 decision'}).closest('.ribbon-group')).not.toBeNull();
  fireEvent.click(languageToggle!);
  expect(languageToggle?.textContent).toBe('中文 ▾');
  expect(languageToggle?.getAttribute('aria-label')).toBe('目前語言：繁體中文；點擊切換語言');
  expect(screen.getByRole('navigation').textContent).toBe('基地條件生成比較細修');
  expect(container.textContent).not.toMatch(/Urban design workspace|Project Browser|Properties|Select a feature|Loading server authority|Site Facts/);
  fireEvent.click(screen.getByRole('button',{name:'生成'}));
  expect(screen.getAllByText('先建立骨架')).toHaveLength(1);
  expect(screen.getByRole('heading', {name:'生成流程'})).toBeTruthy();
  expect(screen.getByTestId('fabric-workspace')).toBeTruthy();
  expect(screen.queryByTestId('plan')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'比較'}));
  expect(screen.getByTestId('compare')).toBeTruthy();
  expect(screen.getByRole('button',{name:'方案並排'}).hasAttribute('disabled')).toBe(false);
  fireEvent.click(languageToggle!);
  expect(languageToggle?.textContent).toBe('English ▾');
  expect(languageToggle?.getAttribute('aria-label')).toBe('Current language: English; click to switch language');
  expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/);
});

test('Ariadne offline evidence card names use the Site Facts translation in Chinese', async () => {
  const cardId = 'card-studyarea-footprint';
  const footprintCard = {
    card_id: cardId,
    metric_key: 'footprint-area',
    metric_name: 'BAG footprint area inside StudyArea',
    value: 44700,
    unit: 'm2',
    confidence: 'HIGH',
    source: 'BAG',
    limitations: [],
    timestamp: '2026-09-30T00:00:00Z',
    status: 'SOURCE_ALIGNED_COVERAGE_LIMITED',
    crs: 'EPSG:28992',
    query_bounds: [],
    algorithm_version: 'test',
    input_sha256: 'input-hash',
    output_sha256: 'output-hash',
    source_package_id: 'source-package',
    source_package_revision: 'r01',
    study_area_id: 'study-area-v5',
    study_area_revision: 1,
    study_area_geometry_sha256: 'geometry-hash',
    source_feature_ids: [],
    source_artifact_ids: [],
    dataset_snapshot_ids: [],
    parents: [],
  };
  const assistantContent = 'BAG footprint area inside StudyArea：44,700 m² [card-studyarea-footprint]。';
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/site-context')) {
      return { ok: true, json: async () => ({
        buildings: [], roads: [], evidence_cards: [footprintCard],
        evidence_cards_status: 'VERIFIED_SOURCE_RESULT_ALIGNMENT', evidence_gaps: [], syntax_layers: [],
      }) };
    }
    if (url.endsWith('/ariadne/status')) {
      return { ok: true, json: async () => ({ mode: 'OFFLINE', block_reason_code: 'BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED' }) };
    }
    if (url.endsWith('/ariadne/messages') && init?.method === 'POST') {
      return { ok: true, json: async () => ({
        user_message: { id: 'user-1', role: 'user', content: '建築輪廓面積是多少？', evidence_refs: [] },
        assistant_message: {
          id: 'assistant-1', role: 'assistant', content: assistantContent,
          evidence_refs: [cardId],
          evidence_sources: [{ evidence_id: cardId, source_type: 'evidence_card' }],
          provider_status: 'NON_AI: DETERMINISTIC_TEMPLATE',
        },
        status: { mode: 'OFFLINE', block_reason_code: 'BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED' },
      }) };
    }
    if (url.endsWith('/ariadne/messages')) return { ok: true, json: async () => ({ messages: [] }) };
    if (url.endsWith('/ariadne/decisions-needed')) return { ok: true, json: async () => ({ items: [] }) };
    return { ok: true, json: async () => ({}) };
  }));

  render(<App />);
  fireEvent.click(document.getElementById('language-toggle')!);
  fireEvent.click(screen.getByRole('button', { name: 'Ariadne' }));
  const input = await screen.findByRole('textbox', { name: '詢問 Ariadne' });
  fireEvent.change(input, { target: { value: '建築輪廓面積是多少？' } });
  fireEvent.click(screen.getByRole('button', { name: '傳送訊息' }));

  const answer = await screen.findByText(content => content.includes(`[${cardId}]`));
  expect(answer.textContent).toBe('研究範圍內 BAG 建築輪廓面積：44,700 m² [card-studyarea-footprint]。');
});

test('Ariadne tab shows its decision badge and citations highlight mapped features', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/site-context')) {
      return { ok: true, json: async () => ({
        buildings: [{ id: 'building-42', geometry: null, disposition: 'PRESERVE', properties: {} }],
        roads: [],
        evidence_cards: [{ card_id: 'card-building-count', metric_key: 'building-count', metric_name: 'Building count', value: 1, unit: 'features', confidence: 'HIGH', source: 'BAG', limitations: [], timestamp: '2026-09-30T00:00:00Z', status: 'SOURCE_ALIGNED_COVERAGE_LIMITED', crs: 'EPSG:28992', query_bounds: [], algorithm_version: 'test', input_sha256: 'input-hash', output_sha256: 'output-hash', source_package_id: 'source-package', source_package_revision: 'r01', study_area_id: 'study-area-v5', study_area_revision: 1, study_area_geometry_sha256: 'geometry-hash', source_feature_ids: ['building-42'], source_artifact_ids: [], dataset_snapshot_ids: [], parents: [] }],
        evidence_gaps: [], syntax_layers: [],
      }) };
    }
    if (url.endsWith('/ariadne/status')) return new Response(JSON.stringify({ mode: 'OFFLINE', block_reason: 'Live AI is disabled.', block_reason_code: 'BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED' }));
    if (url.endsWith('/ariadne/decisions-needed')) return new Response(JSON.stringify({ items: [{ id: 'decision-1', title: 'Confirm the workspace', source_id: 'workspace-1', source_type: 'workspace' }] }));
    if (url.endsWith('/ariadne/messages')) return new Response(JSON.stringify({ messages: [{ id: 'assistant-1', role: 'assistant', content: 'See the source [card-building-count].', evidence_refs: ['card-building-count'], evidence_sources: [{ evidence_id: 'card-building-count', source_type: 'evidence_card' }] }] }));
    return { ok: true, json: async () => ({ status: 'OFFLINE' }) };
  }));

  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Ariadne' }));

  expect((await screen.findByTestId('ariadne-decisions-badge')).textContent).toBe('1');
  fireEvent.click(await screen.findByRole('button', { name: 'Evidence card card-building-count' }));
  expect(screen.getByTestId('plan').getAttribute('data-selected-feature')).toBe('building-42');
});

test('Site Opportunities entrypoint and Conditions Design Brief panel are wired and localized', async () => {
  const oppStatement = 'Explore another pedestrian connection along the quay.';
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/site-context')) {
      return { ok: true, json: async () => ({
        buildings: [],
        roads: [],
        evidence_cards: [],
        evidence_gaps: [],
        syntax_layers: [],
        study_area: { id: 'study-area-v1', status: 'ACTIVE', revision: 1, version: 'v1' },
        current_workspace: {
          revision: 1,
          workspace_id: 'workspace-rotterdam-m4h-pilot-project',
          study_area_id: 'study-area-v1',
          payload_digest: 'sha256:' + 'b'.repeat(64),
          feature_dispositions: [],
        },
      }) };
    }
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/site-intelligence')) {
      return { ok: true, json: async () => ({
        project_id: 'rotterdam-m4h-pilot-project',
        status: 'AVAILABLE',
        analysis_status: 'AVAILABLE',
        latest_bundle_ref: { id: 'bundle-test', revision: 1, sha256: 'sha256:' + 'a'.repeat(64) },
        bundle_persisted: true,
        workspace_ref: { id: 'workspace-rotterdam-m4h-pilot-project', revision: 1, sha256: 'sha256:' + 'b'.repeat(64) },
        default_scope_ref: { id: 'scope-study-area', revision: 1, sha256: 'sha256:' + 'c'.repeat(64) },
        scope_refs: [],
        opportunity_ref: { id: 'opportunity-set-test', revision: 1, sha256: 'sha256:' + 'd'.repeat(64) },
        opportunities: [{
          id: 'opp-route-quay',
          origin: 'AI_SUGGESTED',
          statement: oppStatement,
          kind: 'CONDITIONAL_HYPOTHESIS',
          evidence_refs: [],
          scope_ref: { id: 'scope-study-area', revision: 1, sha256: 'sha256:' + 'c'.repeat(64) },
          suggested_actions: ['CONNECT_WATERFRONT_PROMENADE'],
          counterexamples: [],
          uncertainties: [],
        }],
        input_hashes: {
          'workspace-rotterdam-m4h-pilot-project': 'sha256:' + 'b'.repeat(64),
          'bundle-test': 'sha256:' + 'a'.repeat(64),
          'opportunity-set-test': 'sha256:' + 'd'.repeat(64),
          'scope-study-area': 'sha256:' + 'c'.repeat(64),
        },
        limitations: [],
      }) };
    }
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/problems')) {
      return { ok: true, json: async () => ({
        project_id: 'rotterdam-m4h-pilot-project',
        status: 'ANALYSIS_DEFINED',
        summary: { study_area_id: 'study-area-v1' },
        statements: [
          { problem_id: 'prob-01-functional-monoculture', title_zh: 'BAG 建築用途標籤與登記狀態', severity_code: 'CRITICAL', status: 'CONFIRMED_BASELINE' },
          { problem_id: 'prob-06-unclassified-residual-ground', title_zh: '非建築／非水體幾何差額', severity_code: 'UNRATED', status: 'PENDING_DESIGNER_CONFIRMATION', uncertainties_zh: ['不代表可開發土地'] },
        ],
      }) };
    }
    return { ok: true, json: async () => ({}) };
  }));

  const { container } = render(<App />);

  // In Site stage, click "Site Opportunities"
  fireEvent.click(screen.getByRole('button', { name: 'Site Opportunities' }));
  expect(await screen.findByRole('heading', { name: 'Site Problems & Opportunities' })).toBeTruthy();
  expect(await screen.findByText(/prob-06-unclassified-residual-ground/i)).toBeTruthy();
  expect(screen.getByText(oppStatement)).toBeTruthy();

  // Click "Go to Design Brief" in Site Opportunities -> navigates to Conditions stage BRIEF
  fireEvent.click(screen.getByRole('button', { name: /Go to Design Brief/i }));
  expect(await screen.findByRole('heading', { name: 'Design brief · Draft' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Save draft brief' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Spatial Zones →' })).toBeTruthy();

  // Test language toggle
  const languageToggle = container.querySelector<HTMLButtonElement>('#language-toggle');
  fireEvent.click(languageToggle!);
  expect(await screen.findByRole('heading', { name: '設計需求 · 草稿' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '儲存需求草稿' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '空間分區 →' })).toBeTruthy();

  // Switch to Spatial Zones
  fireEvent.click(screen.getByRole('button', { name: '空間分區 →' }));
  expect(screen.getByText(/空間需求與分區/)).toBeTruthy();
});

test('Conditions keeps brief persistence NOT_READY without a persisted matching analysis reference', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/site-context')) {
      return { ok: true, json: async () => ({
        buildings: [], roads: [], evidence_cards: [], evidence_gaps: [], syntax_layers: [],
        study_area: { id: 'study-area-v1', status: 'ACTIVE', revision: 1, version: 'v1' },
        current_workspace: {
          revision: 6,
          workspace_id: 'workspace-rotterdam-m4h-pilot-project',
          study_area_id: 'study-area-v1',
          payload_digest: 'sha256:' + 'b'.repeat(64),
          feature_dispositions: [],
        },
      }) };
    }
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/site-intelligence')) {
      return { ok: true, json: async () => ({
        project_id: 'rotterdam-m4h-pilot-project',
        status: 'NOT_RUN',
        analysis_status: 'NOT_RUN',
        latest_bundle_ref: null,
        bundle_persisted: false,
        workspace_ref: { id: 'workspace-rotterdam-m4h-pilot-project', revision: 6, sha256: 'sha256:' + 'b'.repeat(64) },
        default_scope_ref: null,
        scope_refs: [],
        opportunity_ref: null,
        opportunities: [],
        input_hashes: { 'workspace-rotterdam-m4h-pilot-project': 'sha256:' + 'b'.repeat(64) },
        latest_brief: null,
        limitations: [],
      }) };
    }
    if (url.endsWith('/api/v1/projects/rotterdam-m4h-pilot-project/problems')) {
      return { ok: false, status: 404, json: async () => ({ detail: 'Problem report not found' }) };
    }
    if (url.endsWith('/design-briefs/latest')) {
      return { ok: false, status: 404, json: async () => ({ detail: 'No design brief found' }) };
    }
    return { ok: true, json: async () => ({}) };
  }));

  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Conditions' }));
  fireEvent.click(screen.getByRole('button', { name: 'Design Brief' }));

  const saveButton = await screen.findByRole('button', { name: 'Save draft brief' });
  expect(saveButton.hasAttribute('disabled')).toBe(true);
  expect(screen.getByText('NOT_READY: A persisted SiteAnalysisBundle matching this workspace is required.')).toBeTruthy();
  expect(screen.queryByText(/provisional-bundle/)).toBeNull();
});

test.each(['en', 'zh-TW'])('site readiness is compact and retains full tooltip evidence in %s', (language) => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({buildings:[],roads:[],evidence_cards:[],evidence_gaps:[],syntax_layers:[]})}));
  const { container } = render(<App/>);
  if (language === 'zh-TW') fireEvent.click(container.querySelector('.shell-titlebar button')!);
  for (const mode of ['walk', 'bike', 'car']) {
    const badge = container.querySelector(`#syntax-readiness-${mode}`)!;
    expect(badge.textContent!.length).toBeLessThanOrEqual(14);
    expect(badge.textContent).toBe(mode === 'walk' ? (language === 'en' ? 'Blocked' : '已阻擋') : (language === 'en' ? 'Exploratory' : '探索'));
    expect(badge.getAttribute('data-formal-result')).toBe('false');
    const readinessLabel = language === 'zh-TW'
      ? (mode === 'walk' ? '邊界穩定性尚未評估（空間語法僅供參考）' : '探索性')
      : (mode === 'walk' ? 'Boundary stability unassessed (space syntax for reference only)' : 'Exploratory');
    expect(badge.getAttribute('title')).toContain(readinessLabel);
    expect(badge.getAttribute('title')).toContain(badge.getAttribute('data-manifest-sha256'));
  }
  expect(container.querySelector('#syntax-context-readiness-reason')).toBeNull();
  expect(container.querySelector('#syntax-context-manifest')!.textContent).not.toContain('manifest');
});

test('ribbon and measurement styles bound their content and permit horizontal labels', async () => {
  const fs = await vi.importActual<{ readFileSync(path: string, encoding: 'utf8'): string }>('node:fs');
  const appCss = fs.readFileSync('src/App.css', 'utf8');
  const measurementCss = fs.readFileSync('src/components/Viewport2D.measure.css', 'utf8');
  const style = document.createElement('style');
  style.textContent = appCss + measurementCss;
  document.head.append(style);
  const host = document.createElement('div');
  host.innerHTML = '<div class="shell-ribbon"><div class="ribbon-group"><div class="ribbon-tools"><button>長按鈕 label</button></div></div></div><div class="viewport2d-layout"><div class="viewport2d-measure-banner">Measurement active</div></div>';
  document.body.append(host);
  try {
    expect(getComputedStyle(host.querySelector('.shell-ribbon')!).flexWrap).toBe('wrap');
    expect(getComputedStyle(host.querySelector('.ribbon-tools')!).flexWrap).toBe('wrap');
    expect(getComputedStyle(host.querySelector('button')!).whiteSpace).toBe('nowrap');
    expect(getComputedStyle(host.querySelector('.viewport2d-layout')!).minWidth).toBe('0px');
    expect(getComputedStyle(host.querySelector('.viewport2d-measure-banner')!).position).toBe('absolute');
    expect(getComputedStyle(host.querySelector('.viewport2d-measure-banner')!).boxSizing).toBe('border-box');
  } finally {
    host.remove(); style.remove();
  }
});
