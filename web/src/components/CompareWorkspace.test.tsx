// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import { I18nProvider, useI18n } from '../i18n';
import { CompareWorkspace } from './CompareWorkspace';
vi.mock('./ScenarioStudio', () => ({ScenarioStudio:()=> <div data-testid="editing-tools"/>}));
vi.mock('./Viewport2D', () => ({ Viewport2D: ({ selectedFeatureId, onSelectFeature, buildings, scenarioAreas = [], syntaxSegments = [], activeSyntaxLayer, syntaxContextData }: { selectedFeatureId: string | null; onSelectFeature: (id: string) => void; buildings: { id: string }[]; scenarioAreas?: { kind: string }[]; syntaxSegments?: { id: string }[]; activeSyntaxLayer?: { layer_id: string } | null; syntaxContextData?: unknown }) => <div><div data-context={JSON.stringify(syntaxContextData ?? null)} data-testid="scenario-plan" data-areas={scenarioAreas.map(area => area.kind).join(',')} data-syntax={syntaxSegments.map(segment => segment.id).join(',')} data-layer={activeSyntaxLayer?.layer_id ?? ''} /> <button aria-label="2D select" onClick={() => onSelectFeature(buildings[0]!.id)}>2D {selectedFeatureId} buildings {buildings.length}</button></div> }));
vi.mock('./Viewport3D', () => ({ Viewport3D: ({ selectedFeatureId, onCameraChange, cameraState, buildings, scenarioAreas = [], syntaxSegments = [], syntaxOverlayVisible, syntaxContextData }: { selectedFeatureId: string | null; onCameraChange?: (state: { radius: number }) => void; cameraState?: { radius: number }; buildings: { id: string; properties?: { height_m?: number } }[]; scenarioAreas?: { kind: string }[]; syntaxSegments?: { id: string }[]; syntaxOverlayVisible?: boolean; syntaxContextData?: unknown }) => <div><div data-context={JSON.stringify(syntaxContextData ?? null)} data-testid="scenario-3d" data-areas={scenarioAreas.map(area => area.kind).join(',')} data-syntax={syntaxSegments.map(segment => segment.id).join(',')} data-syntax-visible={String(syntaxOverlayVisible ?? false)} data-heights={buildings.map(building => building.properties?.height_m ?? '').join(',')} data-camera-radius={cameraState?.radius ?? ''} /><button aria-label="change camera" onClick={() => onCameraChange?.({ radius: 321 })}>3D selection {selectedFeatureId}</button></div> }));
const makePreview = (intensity: string, index: number) => ({ identity: { intensity, strategy_id: 's' + index, status: 'UNAPPROVED_PREVIEW', human_decision_created: false, generator_version: 'test', run_created_at: null, generator_commit: null }, strategy_label: 'Strategy ' + index, limits: { intensity, far_upper_bound_land: 1, coverage_upper_bound: null, height_upper_bound_new_buildings_m: 20 }, metrics: { building_count: 1, known_part_land_far: 1, coverage_ratio: 0.2, maximum_height_m: 10, open_space_ratio: 0.8, generator_valid: true, warnings: [] }, retained_buildings: [], input_refs: [], limitations: [], assets: { plan: '/plan.png', axonometric: '/axo.png', geometry: '/geometry.json' } });
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });
function setup() {
 const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
 const url = String(input);
 const response = url.endsWith('/scenarios') ? { scenarios: [{ scenario_id: 'editable-one', strategy_label: 'Saved candidate', status: 'DRAFT' }] } : url.endsWith('/geometry.json') ? { type: 'FeatureCollection', properties: { scenario_hash: 'sha256:fixture' }, features: [
   ...['study_area', 'water', 'generated_building', 'preserved_building', 'street_block', 'strategy_open_space'].map(kind => ({ type: 'Feature', properties: { feature_kind: kind, building_id: kind + '-one', floor_count: kind === 'generated_building' ? 4 : null, height_m: kind === 'generated_building' ? 13.5 : null }, geometry: { type: 'Polygon', coordinates: [[[90000, 435000], [90010, 435000], [90010, 435010], [90000, 435000]]] } })),
   { type: 'Feature', properties: { feature_kind: 'road_segment', segment_id: 'preview-road' }, geometry: { type: 'LineString', coordinates: [[90000,435000],[90010,435010]] } },
 ] } : { status: 'AVAILABLE', count: 10, source_reverified: false, verified_at_utc: null, previews: ['A', 'B'].flatMap(intensity => Array.from({ length: 5 }, (_, i) => makePreview(intensity, i + 1))), limits: [] };
 return new Response(JSON.stringify(response), { status: 200 });
 });
 return fetchSpy;
}
it('shows the bound revision and does not fetch another scheme list', () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch');
  render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="2D" syncedViews={false} boundRevision={{ fixtureOnly: true, scenarioId: 'B2', revision: 'rev-b2', far: 2.2, unit: 'ratio', label: 'compare revision rev-b2 scenario B2 far 2.2 ratio' }} />);
  expect(screen.getByTestId('compare-bound-revision').textContent).toBe('compare revision rev-b2 scenario B2 far 2.2 ratio');
  expect(fetchSpy).not.toHaveBeenCalled();
});
it('lists ten read-only previews beside editable scenarios and synchronizes split selection without writes', async () => {
 const fetchSpy = setup();
 render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="SPLIT" syncedViews={false} syntaxSegments={[{id:'syntax-road'}] as never} syntaxSegmentValues={{'syntax-road': 0.5}} activeSyntaxLayer={{layer_id:'syntax-800'} as never} />);
 expect(await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' })).toBeTruthy();
 expect(screen.getAllByRole('button', { name: /^Open [AB]: Strategy/ })).toHaveLength(10);
 expect(screen.getByRole('button', { name: /Saved candidate/ })).toBeTruthy();
 const plan = await screen.findByRole('button', { name: '2D select' });
 expect(plan.textContent).toContain('buildings 2');
 expect(screen.getByTestId('scenario-plan').getAttribute('data-areas')).toContain('street_block');
 expect(screen.getByTestId('scenario-plan').getAttribute('data-areas')).toContain('strategy_open_space');
 expect(screen.getByTestId('scenario-plan').getAttribute('data-layer')).toBe('syntax-800');
 expect(screen.getByTestId('scenario-3d').getAttribute('data-heights')).toBe('13.5,');
 expect(screen.getByTestId('scenario-3d').getAttribute('data-syntax')).toBe('syntax-road');
 expect(screen.getByTestId('scenario-3d').getAttribute('data-syntax-visible')).toBe('true');
 fireEvent.click(plan);
 expect(screen.getByRole('button', { name: 'change camera' }).textContent).toContain('generated_building-one');
 expect(fetchSpy.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
});
it('shows two selectable 3D scenario views and synchronizes their camera state when enabled', async () => {
 setup(); render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="COMPARE" syncedViews />);
 expect(await screen.findAllByTestId('scenario-3d')).toHaveLength(2);
 expect(screen.getByRole('combobox', { name: 'Right scenario' })).toBeTruthy();
 fireEvent.click(screen.getAllByRole('button', { name: 'change camera' })[0]!);
 await waitFor(() => expect(screen.getAllByTestId('scenario-3d').map(view => view.getAttribute('data-camera-radius'))).toEqual(['321','321']));
});

function LanguageToggle() { const { setLanguage } = useI18n(); return <button onClick={() => setLanguage('zh-TW')}>Switch language</button>; }
it('switches catalog and editable-list interface text to Traditional Chinese immediately', async () => {
 setup();
 render(<I18nProvider><LanguageToggle /><CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="2D" syncedViews={false} /></I18nProvider>);
 await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' });
 fireEvent.click(screen.getByRole('button', { name: 'Switch language' }));
 expect(screen.getByRole('heading', { name: '假設組 A（5 個預覽）' })).toBeTruthy();
 expect(screen.getByRole('heading', { name: '可編輯方案' })).toBeTruthy();
 expect(screen.queryByRole('heading', { name: 'Editable scenarios' })).toBeNull();
 expect(screen.queryByText('Read-only catalog')).toBeNull();
 expect(screen.getByRole('button', { name: '開啟方案編輯工具' })).toBeTruthy();
});

it('keeps refinement editing tools visible after the default preview loads', async () => { setup(); render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="2D" syncedViews={false} startEditing />); await screen.findByRole('heading', {name:'Assumption set A (5 previews)'}); expect(screen.getByTestId('editing-tools')).toBeTruthy(); fireEvent.click(screen.getByRole('button',{name:'Open A: Strategy 2'})); expect(await screen.findByRole('button',{name:'2D select'})).toBeTruthy(); expect(screen.queryByTestId('editing-tools')).toBeNull(); });

it('retains editable scenarios when the preview catalog is disabled', async () => {
 vi.spyOn(globalThis,'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).endsWith('/scenarios') ? {scenarios:[{scenario_id:'editable-one',strategy_label:'Saved candidate',status:'DRAFT'}]} : {status:'DISABLED'})));
 render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="2D" syncedViews={false} />);
 await screen.findByText('Preview catalog disabled.');
 fireEvent.click(await screen.findByRole('button',{name:/Saved candidate/}));
 expect(screen.getByTestId('editing-tools')).toBeTruthy();
});
it('renders two formal proposals with heights and layers using only GET and reports formal properties selection', async () => {
 const selected = vi.fn();
 const proposals = ['formal-a','formal-b'].map((id, i) => ({generator_version:'formal-dictionary-v7-multimodal',id,strategy:`Formal ${i+1}`,status:'PROPOSED',metrics:{far:0.75,far_denominator:'land_area',far_denominator_m2:10000},geometry:{type:'FeatureCollection',features:[
  ...['new_building','retained','street_block','primary_open_space'].map(role => ({type:'Feature',properties:{role,building_id:`${id}-${role}`,height_m:role==='new_building'?17.5:12},geometry:{type:'Polygon',coordinates:[[[90000,435000],[90010,435000],[90010,435010],[90000,435000]]]}})),
  {type:'Feature',properties:{role:'road',width_m:6},geometry:{type:'LineString',coordinates:[[90000,435000],[90010,435010]]}}
 ]}}));
 const fetchSpy=vi.spyOn(globalThis,'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).endsWith('/formal-proposals') ? proposals : String(input).endsWith('/scenarios') ? {scenarios:[]} : {status:'DISABLED',count:0,previews:[]})));
 const {rerender}=render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" projectId="p" viewMode="SPLIT" syncedViews onSchemeSelection={selected}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Formal 1 · PROPOSED'}));
 await waitFor(() => expect(screen.getByTestId('scenario-3d').getAttribute('data-heights')).toBe('17.5,12'));
 expect(screen.getByTestId('scenario-plan').getAttribute('data-areas')).toContain('street_block');
 expect(screen.getByTestId('scenario-plan').getAttribute('data-areas')).toContain('primary_open_space');
 expect(selected).toHaveBeenCalledWith(expect.objectContaining({id:'formal-a',status:'PROPOSED',formal:proposals[0]}));
 rerender(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" projectId="p" viewMode="COMPARE" syncedViews onSchemeSelection={selected}/>);
 await waitFor(() => expect(screen.getAllByTestId('scenario-3d')).toHaveLength(2));
 expect(screen.getByRole('combobox',{name:'Right scenario'})).toBeTruthy();
 expect(fetchSpy.mock.calls.every(([, init]) => !init?.method || init.method==='GET')).toBe(true);
});

it('opens baseline selection dialog when clicking Select baseline button', async () => {
  const proposals = ['formal-a', 'formal-b'].map((id, i) => ({
    id,
    generator_version: 'formal-dictionary-v7-multimodal',
    strategy: `Formal ${i + 1}`,
    status: 'PROPOSED',
    geometry_sha256: `sha256:geom-${id}`,
    metrics: { far: 0.75, far_denominator: 'land_area', far_denominator_m2: 10000 },
    geometry: { type: 'FeatureCollection', features: [] },
  }));
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input =>
    new Response(
      JSON.stringify(
        String(input).endsWith('/formal-proposals')
          ? proposals
          : String(input).endsWith('/scenarios')
          ? { scenarios: [] }
          : { status: 'DISABLED', count: 0, previews: [] }
      )
    )
  );

  render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" projectId="p" viewMode="2D" syncedViews={false} />);
  const baselineBtn = await screen.findByTestId('select-baseline-btn');
  expect(baselineBtn).toBeTruthy();
  expect((baselineBtn as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(baselineBtn);
  expect(await screen.findByRole('dialog')).toBeTruthy();
  expect(screen.getByText('Confirm baseline proposal & decisions')).toBeTruthy();
});

it('renders ACCEPTED and REJECTED badges with reasons and disables baseline button when baseline exists', async () => {
  const proposals = [
    {
      id: 'formal-a',
      generator_version: 'formal-dictionary-v7-multimodal',
      strategy: 'Formal 1',
      status: 'ACCEPTED',
      baseline_reason: 'Meets solar access and open space targets.',
      geometry_sha256: 'sha256:geom-a',
      metrics: { far: 0.8 },
      geometry: { type: 'FeatureCollection', features: [] },
    },
    {
      id: 'formal-b',
      generator_version: 'formal-dictionary-v7-multimodal',
      strategy: 'Formal 2',
      status: 'REJECTED',
      rejection_reason: 'Street canyon effect too severe.',
      geometry_sha256: 'sha256:geom-b',
      metrics: { far: 1.2 },
      geometry: { type: 'FeatureCollection', features: [] },
    },
  ];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input =>
    new Response(
      JSON.stringify(
        String(input).endsWith('/formal-proposals')
          ? proposals
          : String(input).endsWith('/scenarios')
          ? { scenarios: [] }
          : { status: 'DISABLED', count: 0, previews: [] }
      )
    )
  );

  render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" projectId="p" viewMode="2D" syncedViews={false} />);
  expect(await screen.findByText('ACCEPTED')).toBeTruthy();
  expect(screen.getByText('REJECTED')).toBeTruthy();
  expect(screen.getByText(/Meets solar access and open space targets\./)).toBeTruthy();
  expect(screen.getByText(/Street canyon effect too severe\./)).toBeTruthy();

  const baselineBtn = screen.getByTestId('select-baseline-btn');
  expect((baselineBtn as HTMLButtonElement).disabled).toBe(true);
});


it.each(['en', 'zh-TW'] as const)('opens a passphrase and reason reconsider dialog in %s and submits the exact revision', async language => {
 let proposals = [{generator_version:'formal-dictionary-v7-multimodal',id:'accepted-fixture',strategy:'Accepted fixture',status:'ACCEPTED',revision:7,
   geometry_sha256:'sha256:'+'a'.repeat(64),metrics:{},geometry:{type:'FeatureCollection',features:[]}}];
 const fetchSpy=vi.spyOn(globalThis,'fetch').mockImplementation(async input => {
   const url=String(input);
   if (url.endsWith('/reconsider')) {
     proposals=proposals.map(p=>({...p,status:'PROPOSED',revision:8}));
     return new Response(JSON.stringify({status:'proposed'}),{status:201});
   }
   return new Response(JSON.stringify(url.endsWith('/formal-proposals') ? proposals : url.endsWith('/scenarios') ? {scenarios:[]} : {status:'DISABLED',count:0,previews:[]}));
 });
 render(<I18nProvider><LanguageToggle /><CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" projectId="fixture-project" viewMode="2D" syncedViews={false}/></I18nProvider>);
 if(language==='zh-TW') fireEvent.click(screen.getByRole('button',{name:'Switch language'}));
 fireEvent.click(await screen.findByRole('button',{name:language==='en' ? 'Reconsider · Accepted fixture' : '重新考慮 · Accepted fixture'}));
 const dialog=screen.getByRole('dialog');
 expect(dialog.textContent).toContain(language==='en' ? 'Return this scenario to proposed.' : '將此方案回到待定');
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'Fixture reconsideration reason'}});
 fireEvent.change(dialog.querySelector('input[type="password"]')!,{target:{value:'test-only-key'}});
 fireEvent.click(screen.getByRole('button',{name:language==='en' ? 'Confirm decision' : '確認決策'}));
 await waitFor(()=>expect(fetchSpy.mock.calls.some(([input])=>String(input).endsWith('/reconsider'))).toBe(true));
 const call=fetchSpy.mock.calls.find(([input])=>String(input).endsWith('/reconsider'))!;
 expect(JSON.parse(String(call[1]?.body))).toEqual(expect.objectContaining({project_id:'fixture-project',scenario_id:'accepted-fixture',target_version:'7',
   target_geometry_sha256:'sha256:'+'a'.repeat(64),reason:'Fixture reconsideration reason',decision_key:'test-only-key'}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
 await waitFor(()=>expect(screen.queryByRole('button',{name:/Reconsider ·|重新考慮 ·/})).toBeNull());
});

it('passes surrounding syntax to both compare viewports and clears it when disabled', async () => {
 setup();
 const context = { segments: [{ id: 'surrounding-road' }] };
 const {rerender} = render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="SPLIT" syncedViews syntaxContextData={context as never} />);
 await screen.findByRole('button', {name:'2D select'});
 for (const id of ['scenario-plan','scenario-3d']) expect(screen.getByTestId(id).getAttribute('data-context')).toBe(JSON.stringify(context));
 rerender(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="SPLIT" syncedViews syntaxContextData={context as never} syntaxOverlayVisible={false} />);
 for (const id of ['scenario-plan','scenario-3d']) expect(screen.getByTestId(id).getAttribute('data-context')).toBe('null');
});

it('does not fetch or mount legacy geometry until its workspace is selected', async () => {
 const fetchSpy=setup();
 render(<CompareWorkspace apiBase="http://fixture.test" viewMode="3D" syncedViews={false}/>);
 await screen.findByTestId('legacy-preview-toggle');
 expect(screen.queryByTestId('scenario-3d')).toBeNull();
 expect(fetchSpy.mock.calls.some(([url])=>String(url).endsWith('/geometry.json'))).toBe(false);
 fireEvent.click(screen.getByTestId('legacy-preview-toggle'));
 await screen.findByTestId('scenario-3d');
 expect(fetchSpy.mock.calls.some(([url])=>String(url).endsWith('/geometry.json'))).toBe(true);
});

it.each(['en', 'zh-TW'] as const)('exposes one Week 7 disclosure across default fabric, legacy and fixture workspaces in %s', async language => {
 setup();
 const props = { apiBase: 'http://fixture.test', viewMode: 'SPLIT' as const, syncedViews: false, week7Chrome: <div>Week 7 controls</div> };
 const { rerender } = render(<I18nProvider language={language}><CompareWorkspace {...props} /></I18nProvider>);
 const assertVisibleDisclosure = () => {
   const disclosures = document.querySelectorAll('.compare-week7');
   expect(disclosures).toHaveLength(1);
   const disclosure = disclosures[0] as HTMLDetailsElement;
   expect(disclosure.closest('[hidden]')).toBeNull();
   expect(disclosure.parentElement?.classList.contains('compare-workspace')).toBe(true);
   expect(disclosure.querySelector('summary')?.textContent).toBe(language === 'en' ? 'Scenario operations (View / Challenge / Modify / Fork / Reject / Override)' : '方案操作（檢視／質疑／修改／分支／駁回／覆寫）');
   return disclosure;
 };
 const disclosure = assertVisibleDisclosure();
 expect(disclosure.open).toBe(false);
 fireEvent.click(disclosure.querySelector('summary')!);
 expect(disclosure.open).toBe(true);
 fireEvent.click(screen.getByTestId('legacy-preview-toggle'));
 await screen.findAllByRole('button', { name: /Strategy 1/ });
 expect(assertVisibleDisclosure()).toBe(disclosure);
 rerender(<I18nProvider language={language}><CompareWorkspace {...props} boundRevision={{fixtureOnly:true,scenarioId:'B2',revision:'r2',far:2.2,unit:'ratio',label:'fixture revision'}} /></I18nProvider>);
 expect(assertVisibleDisclosure()).toBe(disclosure);
});

it('shows formal draft geometry without requesting ineligible scenario Syntax', async () => {
 const draft = {generator_version:'formal-dictionary-v7-multimodal',id:'formal-draft-source',strategy:'Editable formal draft',status:'DRAFT',metrics:{},geometry:{type:'FeatureCollection',features:[]}};
 const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async input => new Response(JSON.stringify(String(input).endsWith('/formal-proposals') ? [draft] : String(input).endsWith('/scenarios') ? {scenarios:[]} : {status:'DISABLED',previews:[]})));
 render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="2D" syncedViews={false}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Editable formal draft · DRAFT'}));
 await screen.findByTestId('scenario-plan');
 expect(fetcher.mock.calls.filter(([url])=>String(url).includes('/syntax'))).toHaveLength(0);
 expect(screen.queryByRole('button',{name:'Recompute scenario Syntax'})).toBeNull();
});

it('leaves the selected formal preview when opening refinement editing tools', async () => {
  const harbour = {id: 'harbour', generator_version: 'formal-dictionary-v7-multimodal', strategy: 'Harbour', status: 'ACCEPTED', geometry: {type: 'FeatureCollection', features: []}, metrics: {}};
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(
    String(input).endsWith('/formal-proposals') ? [harbour] : String(input).endsWith('/scenarios') ? {scenarios: []} : {status: 'DISABLED', previews: []}
  )));
  render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" projectId="p" viewMode="2D" syncedViews={false} startEditing />);
  fireEvent.click(await screen.findByTestId('harbour-mainline-btn'));
  expect(screen.queryByTestId('editing-tools')).toBeNull();
  fireEvent.click(screen.getByRole('button', {name: 'Open scenario editing tools'}));
  expect(await screen.findByTestId('editing-tools')).toBeTruthy();
});


it('keeps W6 editable scenarios in collapsed history and only five mainline choices', async () => {
 const historical = ['common-compact','common-mixed','grid-fine','grid-mixed','spine-mixed'];
 vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(
   String(input).endsWith('/scenarios') ? {scenarios: historical.map(id => ({scenario_id:id,strategy_label:id,status:'accepted'}))}
   : String(input).endsWith('/formal-proposals') ? [] : {status:'DISABLED'}
 )));
 render(<CompareWorkspace initialWorkspace="legacy" apiBase="http://fixture.test" viewMode="2D" syncedViews={false} />);
 await waitFor(() => expect(screen.getByTestId('compare-historical-scenarios').textContent).toContain('common-mixed'));
 const history = screen.getByTestId('compare-historical-scenarios');
 expect(history.hasAttribute('open')).toBe(false);
 expect(within(screen.getByTestId('compare-mainline-proposals')).getAllByRole('button')).toHaveLength(5);
 for (const id of historical) {
   expect(history.textContent).toContain(id);
   expect(screen.getByTestId('compare-editable-list').textContent).not.toContain(id);
 }
 fireEvent.click(within(history).getByRole('button', {name:/common-mixed/}));
 expect(screen.getByTestId('editing-tools')).toBeTruthy();
});
