import type { FabricLayers } from './FabricCompareMap';
export const FABRIC_COLORS = { background: '#0b0f17', boundary: '#38bdf8', retained: '#a4a4a4', '1–2F': '#b7a698', '3F': '#a08c7c', '4F': '#897365', '5F': '#715a4c', '6F+': '#3e332c', unknown: '#64748b', park: '#89ae86', residential: '#e3c598', commercial: '#d5a39b', service: '#c49791', plazas: '#e9dac1', waterfront: '#94b7c6', water: '#287ca2', blocks: '#b3a894', roads: '#b6b0a4', other: '#d5ccba', utility_yard: '#8b7d9c', maintenance_green: '#557a56', shared_planting: '#b5ca89' };
export function landCategory(p: Record<string, unknown> = {}) { const raw = String(p.category ?? p.land_use ?? p.role ?? p.category_zh ?? 'other').toLowerCase(); return ({ '公園':'park', parks:'park', '住宅':'residential', '商業':'commercial', '水域':'water', retained_buildings:'retained',block:'blocks',road:'roads',plaza:'plazas',waterfront_public:'waterfront' } as Record<string,string>)[raw] ?? (raw in FABRIC_COLORS ? raw : 'other'); }
export function landColor(kind: string) { return FABRIC_COLORS[kind as keyof typeof FABRIC_COLORS] ?? FABRIC_COLORS.other; }
export function floorBand(p: Record<string, unknown>) { const n = p.floors ?? p.floor_count; return typeof n !== 'number' || !Number.isFinite(n) || n <= 0 ? 'unknown' : n <= 2 ? '1–2F' : n === 3 ? '3F' : n === 4 ? '4F' : n === 5 ? '5F' : '6F+'; }
export function buildingColor(p: Record<string, unknown>) { return FABRIC_COLORS[p.retained === true ? 'retained' : floorBand(p)]; }
export function roadTier(p: Record<string, unknown>) { const n = p.hierarchy ?? p.road_hierarchy; return typeof n === 'number' && Number.isInteger(n) && n >= 0 && n <= 3 ? n : 4; }
export const ROAD_COLORS = ['#f59e0b', '#c4a370', '#94a3b8', '#889c89', '#475569'];
export const ROAD_WIDTHS = [5, 3.5, 2.5, 1.5, 1];
export function fabricLegend(layers: FabricLayers) {
 const entries = new Map<string, {label:string;color:string}>();
 const add = (key:string,label:string,color:string) => entries.set(key,{label,color});
 if(layers.site.features.length) add('boundary','Site boundary',FABRIC_COLORS.boundary);
 layers.land_use.features.forEach(f=> { const k=landCategory(f.properties ?? {}); add(k,`Land use: ${k}`,landColor(k)); });
 if(layers.blocks.features.length) add('blocks','Land use: blocks',FABRIC_COLORS.blocks);
 if(layers.parks.features.length) add('park','Land use: park',FABRIC_COLORS.park);
 if(layers.water?.features.length) add('water','Land use: water',FABRIC_COLORS.water);
 layers.buildings.features.forEach(f=> { const p=f.properties??{}; const k=p.retained===true?'retained':floorBand(p); add(k==='retained'?'retained':`building-${k}`,k==='retained'?'Land use: retained':`Buildings: ${k}`,buildingColor(p)); });
 layers.roads.features.forEach(f=> {const tier=roadTier(f.properties??{});add(`road-${tier}`,`Road hierarchy ${tier === 4 ? 'unknown' : tier}`,ROAD_COLORS[tier]);});
 return [...entries.values()];
}
export function normalizeFabricLayers(layers: FabricLayers): FabricLayers {
 return {...layers, land_use:{...layers.land_use,features:layers.land_use.features.map(f=>({...f,properties:{...f.properties,fabric_color:landColor(landCategory(f.properties??{}))}}))}, buildings:{...layers.buildings,features:layers.buildings.features.map(f=>({...f,properties:{...f.properties,fabric_color:buildingColor(f.properties??{})}}))},roads:{...layers.roads,features:layers.roads.features.map(f=>{const tier=roadTier(f.properties??{});return {...f,properties:{...f.properties,fabric_color:ROAD_COLORS[tier],fabric_width:ROAD_WIDTHS[tier]}};})}};
}
