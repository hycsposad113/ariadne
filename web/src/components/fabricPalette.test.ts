import { expect, it } from 'vitest';
import { buildingColor, fabricLegend, normalizeFabricLayers, ROAD_COLORS } from './fabricPalette';
import { fabricSiteData } from './FabricViewport';
import { resolveBuildingDisplayHeight } from './Viewport3D';
import type { FabricLayers } from './FabricCompareMap';
const empty={type:'FeatureCollection' as const,features:[]};
const feature=(properties:Record<string,unknown>)=>({type:'Feature' as const,geometry:{type:'Polygon',coordinates:[[[1,2],[3,4],[1,2]]]},properties});
it('preserves projected geometry and explicit heights without estimating missing height from floors',()=>{
 const layers:FabricLayers={site:empty,blocks:empty,roads:empty,parks:empty,land_use:empty,buildings:{...empty,features:[feature({floors:5,height_m:17}),feature({floors:8})]}};
 const data=fabricSiteData(layers);expect(data.buildings[0].geometry).toBe(layers.buildings.features[0].geometry);
 expect(resolveBuildingDisplayHeight(data.buildings[0].properties).heightM).toBe(17);
 expect(resolveBuildingDisplayHeight(data.buildings[1].properties)).toMatchObject({heightM:0,status:'UNKNOWN'});
});
it('legend matches normalized fill and road colors and only includes categories present',()=>{
 const layers:FabricLayers={site:empty,blocks:empty,parks:empty,land_use:{...empty,features:[feature({category:'parks'})]},roads:{...empty,features:[feature({hierarchy:2})]},buildings:{...empty,features:[feature({floors:5}),feature({retained:true})]}};
 const normalized=normalizeFabricLayers(layers),legend=fabricLegend(layers);
 expect(legend).toHaveLength(4);
 expect(legend.map(e=>e.color)).toContain(normalized.land_use.features[0].properties?.fabric_color);
 expect(legend.map(e=>e.color)).toContain(buildingColor({floors:5}));
 expect(normalized.roads.features[0].properties?.fabric_color).toBe(ROAD_COLORS[2]);
});
it('distinguishes every source land category and each specified floor band',()=>{
 const values=['block','road','park','plaza','waterfront_public','retained_buildings','service','utility_yard','maintenance_green','shared_planting','water'];
 const layers:FabricLayers={site:empty,blocks:empty,parks:empty,roads:empty,buildings:empty,land_use:{...empty,features:values.map(category=>feature({category}))}};
 const legend=fabricLegend(layers);expect(legend).toHaveLength(values.length);expect(new Set(legend.map(e=>e.color)).size).toBe(values.length);
 expect(new Set([1,3,4,5,6].map(floors=>buildingColor({floors}))).size).toBe(5);
 expect(buildingColor({floors:1})).toBe(buildingColor({floors:2}));
});
