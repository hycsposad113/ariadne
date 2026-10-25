// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {I18nProvider} from '../i18n';
import type {FabricLayers} from './FabricCompareMap';
import {FabricSyntaxComparison,comparisonContext,type FabricSyntaxPayload} from './FabricSyntaxComparison';
import {classifyContextValue} from '../utils/syntaxContext';
vi.mock('./FabricViewport',()=>({FabricViewport:(p:Record<string,unknown>)=><div data-testid={`pane-${p.id}`} data-props={JSON.stringify(p)}><button onClick={()=> (p.onTransformChange as (x:unknown)=>void)?.({originX:1,originY:2,panX:10,panY:20,zoom:3})}>pan {String(p.id)}</button><button onClick={()=> (p.onCameraChange as (x:unknown)=>void)?.({target:[1,2,3],radius:40,phi:1,theta:2,up:[0,0,1]})}>orbit {String(p.id)}</button></div>}));
const empty={type:'FeatureCollection' as const,features:[]};
const layers:FabricLayers={site:empty,roads:empty,buildings:empty,blocks:empty,land_use:empty,parks:empty};
const payload:FabricSyntaxPayload={type:'FeatureCollection',crs:{type:'name',properties:{name:'EPSG:28992'}},metadata:{fabric_id:'a',mode:'pedestrian',radius_m:800,buffer_m:1000,reliable_within_m:9200},legend_breaks:{nain:[0,1,2,3,4,5],nach:[0,2,4,6,8,10]},features:[{geometry:{type:'LineString',coordinates:[[89100,435900],[89200,435900]]},properties:{render_phase:'after',segment_id:'old',before_nain:1,after_nain:2,delta_nain:1,before_nach:2,after_nach:1,delta_nach:-1,inside_site:true,name:'Street'}},{geometry:{type:'LineString',coordinates:[[89100,435900],[89100,436000]]},properties:{render_phase:'after',segment_id:'new',before_nain:null,after_nain:3,delta_nain:null,is_new_street:true}}],intent_assessment:{intents:[{intent_en:'Primary street',intent_zh:'主街',status:'partial',percentile:65}],all_new_roads:[{road_id:'new',nain:3,nach:2,after_context_percentile:65}]}};
payload.features.push({geometry:{type:'LineString',coordinates:[[89100,435900],[89150,435900]]},properties:{render_phase:'before',segment_id:'before:old',before_nain:1,before_nach:2}});
function props(id='a'){return JSON.parse(screen.getByTestId(`pane-${id}`).dataset.props!);}
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('preserves null comparison gaps, baseline breaks and metric colors',()=>{const before=comparisonContext(payload,'pedestrian','before','nain');const after=comparisonContext(payload,'pedestrian','after','nain');const diff=comparisonContext(payload,'pedestrian','diff','nain');expect(before.legend_breaks).toBe(after.legend_breaks);expect(before.segments).toHaveLength(1);expect(before.segments[0].id).toBe('before:old:0');expect(after.segments).toHaveLength(2);expect(diff.segments[1].nain).toBeNull();expect(classifyContextValue(diff,'nain',null)).toMatchObject({isUncomputed:true,lineDash:[3,3]});expect(classifyContextValue(diff,'nain',0).strokeColor).not.toBe(classifyContextValue(diff,'nain',null).strokeColor);});
it('keeps context separate, switches three views metrics modes and bilingual legend',async()=>{const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>({ok:true,json:async()=>({...payload,metadata:{...payload.metadata,mode:String(url).split('/').at(-1)}})} as Response));const {rerender}=render(<I18nProvider language="en"><FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D" syntaxContextData={null}/></I18nProvider>);expect(fetcher).not.toHaveBeenCalled();fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));await waitFor(()=>expect(screen.getByTestId('fabric-syntax-comparison').dataset.state).toBe('ready'));expect(props().syntaxContextData.comparison_view).toBe('after');fireEvent.change(screen.getByTestId('fabric-syntax-view'),{target:{value:'before'}});expect(props().syntaxContextData.segments).toHaveLength(1);expect(props().syntaxContextData.segments[0].nain).toBe(1);fireEvent.change(screen.getByTestId('fabric-syntax-view'),{target:{value:'diff'}});expect(screen.getByTestId('fabric-syntax-legend').textContent).toContain('Decrease');fireEvent.change(screen.getByTestId('fabric-syntax-metric'),{target:{value:'nach'}});expect(props().syntaxContextData.segments[0].nach).toBe(-1);fireEvent.change(screen.getByTestId('fabric-syntax-mode'),{target:{value:'bicycle'}});await waitFor(()=>expect(props().syntaxContextData?.mode).toBe('bicycle'));expect(fetcher.mock.calls.at(-1)?.[0]).toContain('/syntax/bicycle');rerender(<I18nProvider language="zh-TW"><FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/></I18nProvider>);expect(screen.getByTestId('fabric-syntax-legend').textContent).toContain('無可比較路段');});
it('rejects stale selected fabric responses and fails closed on lineage endpoint errors',async()=>{let resolve!:(r:Response)=>void;vi.spyOn(globalThis,'fetch').mockImplementationOnce(()=>new Promise(r=>{resolve=r;})).mockResolvedValueOnce({ok:true,json:async()=>({...payload,metadata:{...payload.metadata,fabric_id:'b'}})} as Response).mockResolvedValueOnce({ok:false,status:503} as Response);const {rerender}=render(<FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/>);fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));rerender(<FabricSyntaxComparison apiBase="" id="b" layers={layers} mode="2D"/>);await waitFor(()=>expect(screen.getByTestId('fabric-syntax-comparison').dataset.state).toBe('ready'));resolve({ok:true,json:async()=>({...payload,metadata:{...payload.metadata,fabric_id:'a'}})} as Response);await waitFor(()=>expect(screen.getByTestId('fabric-syntax-comparison').dataset.fabricId).toBe('b'));expect(props('b').syntaxContextData.segments[0].id).toBe('old:0');fireEvent.change(screen.getByTestId('fabric-syntax-mode'),{target:{value:'motor_vehicle'}});await waitFor(()=>expect(screen.getByTestId('fabric-syntax-comparison').dataset.state).toBe('error'));expect(props('b').syntaxContextData).toBeNull();});
it('synchronizes actual controlled transforms and camera state across coherent split pairs',async()=>{vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>payload} as Response);const {rerender}=render(<FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/>);fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));await waitFor(()=>expect(screen.getByTestId('fabric-syntax-comparison').dataset.state).toBe('ready'));fireEvent.click(screen.getByTestId('fabric-syntax-split'));expect(props('a-before').mode).toBe('2D');expect(props('a-after').mode).toBe('2D');fireEvent.click(screen.getByText('pan a-before'));expect(props('a-before').viewTransform).toEqual(props('a-after').viewTransform);expect(props('a-after').viewTransform.zoom).toBe(3);rerender(<FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="3D"/>);expect(props('a-before').mode).toBe('3D');expect(props('a-after').mode).toBe('3D');fireEvent.click(screen.getByText('orbit a-after'));expect(props('a-before').cameraState).toEqual(props('a-after').cameraState);rerender(<FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="SPLIT"/>);expect(props('a-before').mode).toBe('2D');expect(props('a-after').mode).toBe('2D');});

it('renders intent checks in the Compare sidebar and independently enables proposal overlay', async()=>{
 const target=document.createElement('div');target.id='fabric-intent-sidebar-a';document.body.append(target);
 vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>payload} as Response);
 render(<FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="3D" syntaxOverlayVisible={false}/>);
 fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));
 await waitFor(()=>expect(props().syntaxOverlayVisible).toBe(true));
 expect(target.querySelector('[data-testid="fabric-intent-checks"]')).toBeTruthy();target.remove();
});

it('clears previously loaded evidence when re-enabling the same mode returns BLOCKED',async()=>{
 vi.spyOn(globalThis,'fetch').mockResolvedValueOnce({ok:true,json:async()=>payload} as Response).mockResolvedValueOnce({ok:false,status:503} as Response);
 render(<FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/>);
 fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));
 await waitFor(()=>expect(screen.getByTestId('fabric-syntax-comparison').dataset.state).toBe('ready'));
 fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));
 await waitFor(()=>expect(screen.getByTestId('fabric-syntax-comparison').dataset.state).toBe('error'));
 expect(props().syntaxContextData).toBeNull();expect(screen.queryByTestId('fabric-intent-checks')).toBeNull();
});

it('renders bilingual NET1 hard-target checks separately from unchanged INT3 intent results',async()=>{
 const data:FabricSyntaxPayload={...payload,net1_assessment:{schema_version:'net1-assessment-v1',fabric_id:'a',mode:'pedestrian',status:'FAIL',hard_targets_pass:false,formal_result_eligible:false,checks:[
  {target:'primary_street',metric:'length_weighted_nain_percentile',value:65,minimum:80,status:'FAIL'},
  {target:'connection Dakpark',metric:'direct_join_road_count',value:null,minimum:1,status:'UNAVAILABLE'},
  {target:'waterfront multiple joins',metric:'unique_geometric_same_mode_junction_count',value:2,minimum:2,status:'PASS'}]}};
 vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>data} as Response);
 const {rerender}=render(<I18nProvider language="en"><FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/></I18nProvider>);
 fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));
 await waitFor(()=>expect(screen.getByTestId('fabric-net1-checks')).toBeTruthy());
 const section=screen.getByTestId('fabric-net1-checks');
 expect(section.textContent).toContain('65 / Minimum 80%');
 expect(section.textContent).toContain('— / Minimum 1');
 expect(section.querySelector('[data-status="UNAVAILABLE"]')?.textContent).toContain('Unavailable');
 expect(screen.getByTestId('fabric-intent-checks').textContent).toContain('partial');
 expect(screen.getByTestId('fabric-intent-checks').textContent).toContain('Descriptive heuristic');
 expect(section.textContent).toContain('no scenario acceptance is recorded');
 rerender(<I18nProvider language="zh-TW"><FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/></I18nProvider>);
 expect(section.textContent).toContain('NET1 硬目標計算');
 expect(section.textContent).toContain('無法評估');
 expect(screen.getByTestId('fabric-intent-checks').textContent).toContain('部分符合');
});


it('uses measured NET2 baselines dynamically and marks missing evidence unproven',async()=>{
 const data:FabricSyntaxPayload={...payload,net2_assessment:{schema_version:'net2-assessment-v1',fabric_id:'a',mode:'pedestrian',status:'PASS',formal_result_eligible:false,hard_targets_pass:true,baselines:{primary_meets:{name:'Vierhavensstraat',percentile:53},primary_excellent:{name:'Keileweg',percentile:75},waterfront_meets:{reference:'OSM pedestrian before segments near frozen water',percentile:null}},checks:[{target:'primary_street',metric:'length_weighted_nain_percentile',value:61,minimum:53,status:'PASS'},{target:'waterfront_path',metric:'length_weighted_nain_percentile',value:null,minimum:null,status:'UNAVAILABLE'}]}};
 vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:true,json:async()=>data} as Response);
 const {rerender}=render(<I18nProvider language="zh-TW"><FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/></I18nProvider>);
 fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));
 await waitFor(()=>expect(screen.getByTestId('fabric-net2-checks')).toBeTruthy());
 expect(screen.getByTestId('fabric-net2-checks').textContent).toContain('主街 61%（≥ Vierhavensstraat 53%）符合');
 expect(screen.getByTestId('fabric-net2-checks').textContent).toContain('Keileweg 75%');
 expect(screen.getByTestId('fabric-net2-checks').textContent).toContain('未證實');
 expect(screen.getByTestId('fabric-net2-checks').textContent).toContain('既有步行路段中位數');
 expect(screen.queryByText(/Descriptive heuristic/)).toBeNull();
 rerender(<I18nProvider language="en"><FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/></I18nProvider>);
 expect(screen.getByTestId('fabric-net2-checks').textContent).toContain('Primary street 61% (≥ Vierhavensstraat 53%) Meets');
});

it('keeps motor NET2 descriptive without showing pedestrian waterfront thresholds',async()=>{
 vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>({ok:true,json:async()=>({...payload,metadata:{...payload.metadata,mode:String(url).split('/').at(-1)},net2_assessment:{schema_version:'net2-assessment-v1',fabric_id:'a',mode:String(url).split('/').at(-1),status:'DESCRIPTIVE_ONLY',formal_result_eligible:false,hard_targets_pass:null,baselines:{},checks:[]}})} as Response));
 render(<I18nProvider language="zh-TW"><FabricSyntaxComparison apiBase="" id="a" layers={layers} mode="2D"/></I18nProvider>);
 fireEvent.click(screen.getByTestId('fabric-syntax-toggle'));
 fireEvent.change(screen.getByTestId('fabric-syntax-mode'),{target:{value:'motor_vehicle'}});
 await waitFor(()=>expect(screen.getByTestId('fabric-net2-checks').textContent).toContain('僅描述性結果'));
 expect(screen.getByTestId('fabric-net2-checks').textContent).not.toContain('水岸實測基準');
 expect(screen.getByTestId('fabric-net2-checks').textContent).not.toContain('主街優判準');
});
