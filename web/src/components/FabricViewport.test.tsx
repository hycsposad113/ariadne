// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
vi.mock('./Viewport2D',()=>({Viewport2D:(p:Record<string,unknown>)=><div data-testid="site-2d" data-properties={JSON.stringify(p)}/> }));
vi.mock('./Viewport3D',()=>({Viewport3D:(p:Record<string,unknown>)=><div data-testid="site-3d" data-properties={JSON.stringify(p)}/> }));
import { I18nProvider } from '../i18n';
import { FabricViewport, fabricSiteData } from './FabricViewport';
import type { FabricLayers } from './FabricCompareMap';
const empty={type:'FeatureCollection' as const,features:[]};
const polygon={type:'Polygon',coordinates:[[[100,200],[110,200],[110,210],[100,200]]]};
const layers:FabricLayers={site:{...empty,features:[{type:'Feature',geometry:polygon,properties:{}}]},blocks:{...empty,features:[{type:'Feature',geometry:polygon,properties:{}}]},buildings:{...empty,features:[{type:'Feature',geometry:polygon,properties:{floors:4,height_m:14}}]},roads:{...empty,features:[{type:'Feature',geometry:{type:'LineString',coordinates:[[100,200],[110,210]]},properties:{hierarchy:1,width_m:9}}]},parks:empty,land_use:empty};
afterEach(cleanup);
it('mounts exact Site viewports for each mode and forwards syntax and projected data',()=>{
 const {rerender}=render(<FabricViewport id="a" layers={layers} mode="2D" syntaxMetric="nach" syntaxDistanceKm={2}/>);
 expect(screen.getByTestId('site-2d')).toBeTruthy();expect(screen.queryByTestId('site-3d')).toBeNull();
 const props=JSON.parse(screen.getByTestId('site-2d').dataset.properties!);expect(props.studyAreaGeometry).toEqual(polygon);expect(props.syntaxMetric).toBe('nach');expect(props.syntaxDistanceKm).toBe(2);expect(props.buildings[0].properties).toMatchObject({height_m:14,fabric_display:true});
 rerender(<FabricViewport id="a" layers={layers} mode="3D"/>);expect(screen.queryByTestId('site-2d')).toBeNull();expect(screen.getByTestId('site-3d')).toBeTruthy();
 rerender(<FabricViewport id="a" layers={layers} mode="SPLIT"/>);expect(screen.getByTestId('site-2d')).toBeTruthy();expect(screen.getByTestId('site-3d')).toBeTruthy();expect(screen.getByTestId('fabric-viewport-a').dataset.mapMode).toBe('SPLIT');
});
it('never fills block envelopes over use overlays and preserves actual road widths',()=>{const data=fabricSiteData(layers);expect(data.scenarioAreas).toEqual([]);expect(data.segments[0].width_m).toBe(9);});

it('localizes the actual complete map legend without CJK in English', () => {
 const categories=['retained_buildings','waterfront_public','road','park','block','service','plaza','utility_yard','maintenance_green','shared_planting'];
 const complete:FabricLayers={...layers,land_use:{type:'FeatureCollection',features:categories.map(category=>({type:'Feature',geometry:polygon,properties:{category}}))},buildings:{type:'FeatureCollection',features:[1,3,4,5].map(floors=>({type:'Feature',geometry:polygon,properties:{floors,height_m:15}}))}};
 const {container,rerender}=render(<I18nProvider language="en"><FabricViewport id="all" layers={complete} mode="2D"/></I18nProvider>);
 expect(container.textContent).not.toMatch(/[\u3400-\u9fff\uf900-\ufaff]/);
 expect(screen.getByTestId('fabric-legend').textContent).toContain('Waterfront public band');
 expect(screen.getByTestId('fabric-legend').textContent).toContain('New building: 5F');
 expect(screen.getByTestId('fabric-legend').textContent).not.toContain('Land use:');
 rerender(<I18nProvider language="zh-TW"><FabricViewport id="all" layers={complete} mode="2D"/></I18nProvider>);
 expect(screen.getByTestId('fabric-legend').textContent).toContain('水岸公共帶');
});
