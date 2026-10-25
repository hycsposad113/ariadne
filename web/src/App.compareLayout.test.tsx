// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import App from './App';
vi.mock('./components/Viewport2D', () => ({ Viewport2D: () => <div /> }));
vi.mock('./components/Viewport3D', () => ({ Viewport3D: () => <div /> }));
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });
it.each(['Compare', 'Refine'])('clean App mount of %s keeps W7 and citations inside the sidebar without console errors', async stage => {
 const errors = vi.spyOn(console, 'error');
 const workspaceId = 'workspace-rotterdam-m4h-pilot-project';
 const revision = `${workspaceId}@8/formal-dict@1`;
 const panel = {revision, scenario_id:'formal-dict', far:0.7644361027674244, far_unit:'ratio', evidence_ids:[]};
 vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
  const url = String(input);
  let data: unknown = {};
  let status = 200;
  if (url.endsWith('/site-context')) data = { buildings:[],roads:[],evidence_cards:[],evidence_gaps:[],syntax_layers:[],current_workspace:{workspace_id:workspaceId,revision:8,feature_dispositions:[]} };
  else if (url.endsWith('/formal-proposals') || url.includes('/week7/') && url.endsWith('/scenarios')) data = [];
  else if (url.endsWith('/previews')) data = {status:'DISABLED'};
  else if (url.includes('/week7/') && url.endsWith('/view')) data = {workspace_id:workspaceId,project_id:'rotterdam-m4h-pilot-project',scenario_id:'formal-dict',workspace_ref:{entity_id:workspaceId,revision:8},scenario_ref:{entity_id:'formal-dict',revision:1},revision,revision_label:revision,cards:[],runs:[],panels:Object.fromEntries(['map','model3d','dashboard','ai','chart','export'].map(name => [name,panel]))};
  else status = 404;
  return new Response(JSON.stringify(data), {status});
 });
 render(<App />);
 fireEvent.click(screen.getByRole('button', {name:stage}));
 await screen.findByTestId('week7-revision');
 await waitFor(() => expect(screen.getByTestId('compare-bound-revision').textContent).toContain('FAR 0.76 ratio'));
 const bound = screen.getByTestId('compare-bound-revision');
 expect(bound.closest('.compare-browser')).toBeTruthy();
 expect(bound.closest('details')?.open).toBe(false);
 expect(document.querySelector('.compare-week7')?.contains(screen.getByTestId('week7-status'))).toBe(true);
 expect((document.querySelector('.compare-week7') as HTMLDetailsElement).open).toBe(false);
 expect(document.querySelector('.compare-canvas')?.textContent).not.toContain(revision);
 expect(screen.queryByTestId('week7-bound-surfaces')).toBeNull();
 expect(document.body.textContent).not.toContain('dashboard '+revision);
 expect(document.body.textContent).not.toContain('0.7644361027674244');
 expect(errors).toHaveBeenCalledTimes(0);
});

vi.mock('./components/FabricViewport', () => ({FabricViewport: ({id,mode}: {id:string;mode:string}) => <div data-testid={`fabric-map-${id}`} data-map-mode={mode}/> }));
vi.mock('./components/FabricCompareMap', () => ({FabricCompareMap: ({id,mode}: {id:string;mode:string}) => <div data-testid={`fabric-map-${id}`} data-map-mode={mode}/> }));
it.each(['Compare','Generate'])('routes %s current fabric and top-level 3D selection into the shell Properties', async stage => {
 const ids=['harbour_grain','closed_block_extension','courtyard_islands','landscape_figure'];
 vi.spyOn(globalThis,'fetch').mockImplementation(async input => {
  const url=String(input); let data:unknown;
  if(url.endsWith('/site-context')) data={buildings:[],roads:[],evidence_cards:[],evidence_gaps:[],syntax_layers:[]};
  else if(url.endsWith('/fabric-plans')) data={plans:ids.map(fabric_id=>({fabric_id,label_zh:'中文'}))};
  else if(url.includes('/fabric-plans/')) data={fabric_id:url.split('?')[0].split('/').at(-1),label_zh:'中文',status:'EXPLORATORY_DRAFT',output_crs:'EPSG:4326',projected_crs:'EPSG:28992',layers_projected:Object.fromEntries(['roads','blocks','buildings','land_use','parks','site'].map(key=>[key,{type:'FeatureCollection',features:[]}])),layers:Object.fromEntries(['roads','blocks','buildings','land_use','parks','site'].map(key=>[key,{type:'FeatureCollection',features:[]}])),metrics:{new_far:0.8},land_use_table:[],checks:{failure_ids:[]},syntax_summary:{computed_count:12,results:[]},design_statement_markdown:'English design statement pending',limitations:[]};
  else if(url.endsWith('/formal-proposals')) data=[];
  else if(url.endsWith('/previews')) data={status:'DISABLED',previews:[]};
  else if(url.endsWith('/scenarios')) data={scenarios:[]};
  return new Response(JSON.stringify(data ?? {}),{status:data === undefined ? 404 : 200});
 });
 render(<App/>); fireEvent.click(screen.getByRole('button',{name:stage}));
 await screen.findByTestId('fabric-select-harbour_grain');
 expect(screen.getByTestId('fabric-properties').closest('.shell-properties')).toBeTruthy();
 for(const id of ids){
  fireEvent.click(screen.getByTestId(`fabric-select-${id}`));
  expect(screen.getByTestId('fabric-properties').dataset.fabricId).toBe(id);
 }
 fireEvent.click(screen.getByRole('button',{name:stage}));
 expect(screen.getByTestId('fabric-properties').dataset.fabricId).toBe('landscape_figure');
 fireEvent.click(screen.getByRole('button',{name:'3D'}));
 expect(screen.getByTestId('fabric-map-landscape_figure').dataset.mapMode).toBe('3D');
 expect(screen.getByTestId('fabric-properties').dataset.fabricId).toBe('landscape_figure');
 fireEvent.click(screen.getByTestId('fabric-parallel-toggle'));
 expect(screen.getByTestId('fabric-properties').dataset.fabricId).toBe('all');
 expect(screen.getByTestId('fabric-properties').querySelectorAll('tbody tr')).toHaveLength(4);
 ids.forEach(id=>expect(screen.getByTestId(`fabric-map-${id}`).dataset.mapMode).toBe('3D'));
 expect(screen.getByTestId('fabric-properties').textContent).not.toMatch(/[\u3400-\u9fff\uf900-\ufaff]|linear_green_mixed|UNAPPROVED_PREVIEW/);
});
