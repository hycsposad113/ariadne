// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { FabricProperties } from './FabricProperties';
import { FABRIC_IDS, type FabricPlan } from './FabricCompare';
import { I18nProvider } from '../i18n';
afterEach(cleanup);
const empty = {type:'FeatureCollection' as const,features:[]};
const plans = Object.fromEntries(FABRIC_IDS.map(fabric_id => [fabric_id, {fabric_id,label_zh:'中文',status:'EXPLORATORY_DRAFT',output_crs:'EPSG:4326',projected_crs:'EPSG:28992',layers_projected:Object.fromEntries(['roads','blocks','buildings','land_use','parks','site'].map(key => [key,{type:'FeatureCollection',features:[]}])) as unknown as FabricPlan['layers'],layers:{roads:empty,blocks:empty,buildings:empty,land_use:empty,parks:empty,site:empty},metrics:{new_far:0.8,new_gfa_m2:1000,new_building_count:2},land_use_table:[],checks:{failure_ids:[]},syntax_summary:null,design_statement_markdown:null,limitations:[]} satisfies FabricPlan]));
it('updates Properties to the current fabric, its run-5 assets and recorded assumptions', () => {
 const {container,rerender} = render(<I18nProvider language="en"><FabricProperties apiBase="http://fixture" selection={{selected:'harbour_grain',plans,parallel:false,error:false}} /></I18nProvider>);
 for (const selected of FABRIC_IDS) {
  rerender(<I18nProvider language="en"><FabricProperties apiBase="http://fixture" selection={{selected,plans,parallel:false,error:false}} /></I18nProvider>);
  expect(screen.getByTestId('fabric-properties').dataset.fabricId).toBe(selected);
  expect(container.querySelectorAll('a[download]')).toHaveLength(1);
  expect(screen.getByRole('link').textContent).toBe('Download plan (Chinese annotations)');
  expect(container.querySelector('img')).toBeNull();
  expect([...container.querySelectorAll('a[download]')].every(link=>link.getAttribute('href')!.includes(`/fabric-plans/${selected}/figures/`))).toBe(true);
  expect(container.textContent).not.toMatch(/[\u3400-\u9fff\uf900-\ufaff]|linear_green_mixed|UNAPPROVED_PREVIEW/);
 }
 expect(container.textContent).toContain('Exploratory draft');
 expect(container.textContent).not.toContain('EXPLORATORY_DRAFT');
 expect(container.querySelector('[data-status="EXPLORATORY_DRAFT"]')).toBeTruthy();
 expect(container.querySelector('[title="Exploratory draft"]')).toBeTruthy();
 expect(container.textContent).toContain('146,873 m²'); expect(container.textContent).toContain('20 m');
 expect(container.textContent).toContain('ASSUMED');
});
it('shows all four summaries and no stale images when parallel', () => {
 const {container}=render(<I18nProvider language="en"><FabricProperties apiBase="" selection={{selected:'harbour_grain',plans,parallel:true,error:false}} /></I18nProvider>);
 expect(container.querySelectorAll('tbody tr')).toHaveLength(4); expect(container.querySelector('img')).toBeNull();
 expect(screen.getByTestId('fabric-properties').dataset.fabricId).toBe('all');
 expect(container.textContent).not.toMatch(/[\u3400-\u9fff\uf900-\ufaff]/);
});
it('shows loading and failure states without stale preview content', () => {
 const {container,rerender}=render(<I18nProvider language="en"><FabricProperties apiBase="" selection={{selected:'harbour_grain',plans:{},parallel:false,error:false}} /></I18nProvider>);
 expect(screen.getByRole('status').textContent).toBe('Loading fabric plans…');
 rerender(<I18nProvider language="en"><FabricProperties apiBase="" selection={{selected:'harbour_grain',plans:{},parallel:false,error:true}} /></I18nProvider>);
 expect(screen.getByRole('alert').textContent).toBe('Fabric plans unavailable.'); expect(container.querySelector('img')).toBeNull();
});
