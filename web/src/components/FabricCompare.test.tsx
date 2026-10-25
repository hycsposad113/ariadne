// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
vi.mock('./JudgementCard', () => ({JudgementPanel: ({skillId, subjectIds}: {skillId:string;subjectIds?:string[]}) => <section data-testid={`judgement-placement-${skillId}`} data-skill={skillId} data-subjects={subjectIds?.join(',')} />}));
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FABRIC_IDS, FabricCompare, FabricStatement, FabricSyntax } from './FabricCompare';
import { I18nProvider } from '../i18n';
vi.mock('./FabricViewport', () => ({FabricViewport: ({id,mode}: {id:string;mode:string}) => <div data-testid={`fabric-map-${id}`} data-map-mode={mode}/> }));
vi.mock('./FabricCompareMap', () => ({ FabricCompareMap: ({ id }: { id: string }) => <div data-testid={`fabric-map-${id}`} /> }));
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const layers = Object.fromEntries(['roads','blocks','buildings','land_use','parks','site'].map(key => [key, { type:'FeatureCollection', features:[] }]));
function mockData(missing = false) { vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('fabric-plans') ? { plans: FABRIC_IDS.map(id => ({ fabric_id:id, label_zh:id })) } : { fabric_id: url.split('?')[0].split('/').at(-1),label_zh: url.split('?')[0].split('/').at(-1),output_crs:'EPSG:4326',projected_crs:'EPSG:28992',layers_projected:layers,layers,metrics:{new_far:0.8},land_use_table:[],checks:{failure_ids:[]},syntax_summary:null,design_statement_markdown:missing ? null : '# 說明\n<script>alert(1)</script>',limitations:[] } }))); }
it('switches four plans, keeps selected metrics and renders four maps', async () => { mockData(); render(<I18nProvider><FabricCompare apiBase="http://fixture" /></I18nProvider>); await screen.findByTestId('fabric-select-harbour_grain'); for (const id of FABRIC_IDS) { fireEvent.click(screen.getByTestId(`fabric-select-${id}`)); expect(screen.getByTestId('fabric-details').getAttribute('data-fabric-id')).toBe(id); expect(screen.getByTestId(`fabric-map-${id}`)).toBeTruthy(); } fireEvent.click(screen.getByTestId('fabric-parallel-toggle')); FABRIC_IDS.forEach(id => expect(screen.getByTestId(`fabric-map-${id}`)).toBeTruthy()); expect(screen.getByText('計算中（0/12）')).toBeTruthy(); });
it('shows missing design statement honestly', async () => { mockData(true); render(<I18nProvider><FabricCompare apiBase="" /></I18nProvider>); expect(await screen.findByText('尚無設計說明。')).toBeTruthy(); });
it('reports failure without retaining stale geometry', async () => { vi.stubGlobal('fetch', vi.fn(async () => ({ ok:false }))); render(<I18nProvider><FabricCompare apiBase="" /></I18nProvider>); await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('無法載入紋理方案。')); expect(screen.queryByTestId('fabric-details')).toBeNull(); });
it('does not execute statement HTML', () => { const {container}=render(<FabricStatement markdown={'# 說明\n<img src=x onerror=alert(1)>\n- 清楚的依據'} />); expect(container.querySelector('img')).toBeNull(); expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy(); expect(screen.getByRole('heading').textContent).toBe('說明'); });

it('shows computed syntax changes, measured lengths and all road ranks with precise blocked reason', () => {
 const {container}=render(<I18nProvider><FabricSyntax summary={{status:'COMPUTED',results:[{mode:'pedestrian',status:'COMPUTED',radius_m:800,before:{metrics:{mean_integration_nain:1.25,high_integration_length_m:120}},after:{metrics:{mean_integration_nain:1.5,high_integration_length_m:180}},delta_mean_integration_nain:0.25,new_street_ranking:[{road_id:'new-a',nain:2,nach:3,inside_length_m:40},{road_id:'new-b',nain:1,nach:2,inside_length_m:50}]},{mode:'bicycle',status:'BLOCKED',before:null,after:null,reason_zh:'缺少自行車來源網路',new_street_ranking:[]}]}} /></I18nProvider>);
 expect(screen.getAllByText('平均整合度變化（NAIN）')).toHaveLength(2); expect(screen.getByText('0.25')).toBeTruthy(); expect(screen.getByText('120')).toBeTruthy(); expect(screen.getByText('180')).toBeTruthy(); expect(container.querySelectorAll('li')).toHaveLength(2); expect(container.textContent).toContain('new-a');expect(container.textContent).toContain('new-b');expect(screen.getByText('缺少自行車來源網路')).toBeTruthy();expect(screen.getAllByText('尚無資料').length).toBeGreaterThan(0);
});

it('keeps the first two design paragraphs open and the rest collapsed', () => {
 const { container } = render(<I18nProvider><FabricStatement markdown={'# 設計\n第一段\n\n第二段\n\n### 第三標題\n第三段'} /></I18nProvider>);
 const details = container.querySelectorAll('details');
 expect(details).toHaveLength(2); expect(details[0].open).toBe(true); expect(details[1].open).toBe(false);
 expect(details[0].textContent).toContain('第一段'); expect(details[0].textContent).toContain('第二段'); expect(details[1].textContent).toContain('第三段'); expect(details[0].textContent).not.toContain('第三標題'); expect(details[1].textContent).toContain('第三標題');
 fireEvent.click(screen.getByText('展開其餘設計說明')); expect(details[1].open).toBe(true);
});
it('renders API land aggregation and plain check reasons beneath the statement', async () => {
 vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('fabric-plans') ? { plans: FABRIC_IDS.map(id => ({ fabric_id:id, label_zh:id })) } : { fabric_id:url.split('?')[0].split('/').at(-1),label_zh:'方案',output_crs:'EPSG:4326',projected_crs:'EPSG:28992',layers_projected:layers,layers,metrics:{},land_use_table:[{category:'retained_buildings',category_zh:'保留建築',feature_id:'retained',area_m2:20,site_land_percent:20},{category:'waterfront_public',category_zh:'水岸公共帶',feature_id:'waterfront',area_m2:80,site_land_percent:80}],checks:{failure_ids:['WIDTH']},check_explanations_zh:{WIDTH:'道路寬度尚未符合本輪要求'},syntax_summary:null,design_statement_markdown:'第一段\n\n第二段\n\n第三段',limitations:[] } })));
 const {container} = render(<I18nProvider><FabricCompare apiBase="" /></I18nProvider>);
 await screen.findByText('道路寬度尚未符合本輪要求');
 expect(container.querySelector('tfoot')?.textContent).toContain('100%'); expect(screen.getAllByText('保留建築')).toHaveLength(1);
 expect(container.textContent!.indexOf('設計說明（前兩段）')).toBeLessThan(container.textContent!.indexOf('道路寬度尚未符合本輪要求'));
});


it('shows global calculation progress rather than the filtered plan count', () => {
 render(<I18nProvider><FabricSyntax summary={{computed_count:2,status:'INCOMPLETE',results:[]}} /></I18nProvider>);
 expect(screen.getByRole('status').textContent).toBe('計算中（2/12）');
});
it('refreshes pending summaries and stops when all twelve results are available', async () => {
 vi.useFakeTimers();
 let count = 2;
 const fetch = vi.fn(async (url: string) => ({ok:true,json:async () => url.endsWith('fabric-plans') ? {plans:FABRIC_IDS.map(id => ({fabric_id:id,label_zh:id}))} : {fabric_id:url.split('?')[0].split('/').at(-1),label_zh:'方案',output_crs:'EPSG:4326',projected_crs:'EPSG:28992',layers_projected:layers,layers,metrics:{},land_use_table:[],checks:{failure_ids:[]},syntax_summary:{computed_count:count,status:count===12?'COMPUTED':'INCOMPLETE',results:[]},design_statement_markdown:'說明',limitations:[]}}));
 vi.stubGlobal('fetch',fetch);
 await act(async () => {render(<I18nProvider><FabricCompare apiBase="http://fixture" /></I18nProvider>);});
 expect(screen.getByText('計算中（2/12）')).toBeTruthy();
 count = 12;
 await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
 expect(screen.queryByText('計算中（2/12）')).toBeNull();
 expect(fetch).toHaveBeenCalledTimes(9);
 await act(async () => {await vi.advanceTimersByTimeAsync(20000);});
 expect(fetch).toHaveBeenCalledTimes(9);
});
it('reports a failed progress refresh and retries without losing maps', async () => {
 vi.useFakeTimers();
 let fail = false;
 const fetch = vi.fn(async (url: string) => ({ok:!fail,json:async () => url.endsWith('fabric-plans') ? {plans:FABRIC_IDS.map(id => ({fabric_id:id,label_zh:id}))} : {fabric_id:url.split('?')[0].split('/').at(-1),label_zh:'方案',output_crs:'EPSG:4326',projected_crs:'EPSG:28992',layers_projected:layers,layers,metrics:{},land_use_table:[],checks:{failure_ids:[]},syntax_summary:{computed_count:2,status:'INCOMPLETE',results:[]},design_statement_markdown:'說明',limitations:[]}}));
 vi.stubGlobal('fetch',fetch);
 await act(async () => {render(<I18nProvider><FabricCompare apiBase="" /></I18nProvider>);});
 fail = true;
 await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
 expect(screen.getByText('無法更新計算進度，稍後重試；以下為上次讀取的結果。')).toBeTruthy();
 expect(screen.getByTestId('fabric-map-harbour_grain')).toBeTruthy();
 fail = false;
 await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
 expect(screen.queryByText('無法更新計算進度，稍後重試；以下為上次讀取的結果。')).toBeNull();
});

it('uses only English in all fabric surfaces, including pending statements and blocked explanations', async () => {
 vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ok:true,json:async () => url.endsWith('fabric-plans') ? {plans:FABRIC_IDS.map(id=>({fabric_id:id,label_zh:'中文名稱'}))} : {fabric_id:url.split('?')[0].split('/').at(-1),label_zh:'中文',output_crs:'EPSG:4326',projected_crs:'EPSG:28992',layers_projected:layers,layers,metrics:{new_far:0.8},land_use_table:['retained_buildings','waterfront_public','road','park','block','service','plaza','utility_yard','maintenance_green','shared_planting'].map(category=>({category,category_zh:'原始中文',feature_id:category,area_m2:10,site_land_percent:10})),checks:{failure_ids:['WIDTH']},check_explanations_zh:{WIDTH:'中文失敗'},check_explanations_en:{WIDTH:'Road width is below the requirement.'},syntax_summary:{status:'BLOCKED',results:[{mode:'pedestrian',status:'BLOCKED',reason_zh:'中文錯誤'}]},design_statement_markdown:'English design statement pending',limitations:['探索草稿，尚未經人類接受；公共通行權未核實。']}})));
 const {container} = render(<I18nProvider language="en"><FabricCompare apiBase="" /></I18nProvider>);
 await screen.findByText('English design statement pending');
 expect(container.textContent).not.toMatch(/[\u3400-\u9fff\uf900-\ufaff]/);
 expect(screen.getAllByText('Harbour grain').length).toBeGreaterThan(0);
 expect(screen.getByText('Road width is below the requirement.')).toBeTruthy();
 expect(vi.mocked(fetch).mock.calls.slice(1).every(([url]) => String(url).endsWith('?lang=en'))).toBe(true);
});
it('retains selected fabric and parallel layout when switching rendering mode', async () => {
 mockData(); const onSelection = vi.fn();
 const {rerender} = render(<I18nProvider><FabricCompare apiBase="" onSelection={onSelection} /></I18nProvider>);
 await screen.findByTestId('fabric-select-courtyard_islands');
 fireEvent.click(screen.getByTestId('fabric-select-courtyard_islands'));
 expect(screen.getByTestId('judgement-placement-J-COMPARE').dataset.subjects).toBe('courtyard_islands');
 expect(screen.getByTestId('judgement-placement-J-MORPH').dataset.subjects).toBe('courtyard_islands');
 fireEvent.click(screen.getByTestId('fabric-parallel-toggle'));
 expect(screen.getByTestId('judgement-placement-J-COMPARE').dataset.skill).toBe('J-COMPARE');
 expect(screen.getByTestId('judgement-placement-J-COMPARE').dataset.subjects).toBe(FABRIC_IDS.join(','));
 expect(screen.queryByTestId('judgement-placement-J-MORPH')).toBeNull();
 rerender(<I18nProvider><FabricCompare apiBase="" mode="3D" onSelection={onSelection} /></I18nProvider>);
 expect(screen.getByTestId('fabric-details').dataset.fabricId).toBe('courtyard_islands');
 FABRIC_IDS.forEach(id=>expect(screen.getByTestId(`fabric-map-${id}`)).toBeTruthy());
 expect(onSelection.mock.calls.at(-1)?.[0]).toMatchObject({selected:'courtyard_islands',parallel:true});
});

it('hides the previous Chinese statement while English content is loading', async () => {
 mockData(); const onSelection=vi.fn();
 const {container,rerender}=render(<I18nProvider language="zh-TW"><FabricCompare apiBase="" onSelection={onSelection}/></I18nProvider>);
 await screen.findByText('說明');
 vi.stubGlobal('fetch',vi.fn(() => new Promise(() => {})));
 rerender(<I18nProvider language="en"><FabricCompare apiBase="" onSelection={onSelection}/></I18nProvider>);
 await screen.findByText('Loading fabric plans…');
 expect(container.textContent).not.toMatch(/[\u3400-\u9fff\uf900-\ufaff]/);
 expect(onSelection.mock.calls.at(-1)?.[0].plans).toEqual({});
});
