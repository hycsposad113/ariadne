import { useMemo } from 'react';
import { Viewport2D } from './Viewport2D';
import { Viewport3D, type Viewport3DCameraState } from './Viewport3D';
import type { RenderTransform } from '../utils/geoTransform';
import type { FabricLayers } from './FabricCompareMap';
import type { Building, Segment, SyntaxLayer } from '../types';
import type { SyntaxContextResponse, SyntaxContextMode, SyntaxContextMetric } from '../utils/syntaxContext';
import { fabricLegend, landCategory, normalizeFabricLayers } from './fabricPalette';
import { useT } from '../i18n';
export interface FabricViewportProps { viewTransform?:RenderTransform; onTransformChange?:(state:RenderTransform)=>void; cameraState?:Viewport3DCameraState; onCameraChange?:(state:Viewport3DCameraState)=>void; id:string; layers:FabricLayers; mode:'2D'|'3D'|'SPLIT'; syntaxContextData?:SyntaxContextResponse|null; syntaxContextStatus?:'idle'|'loading'|'success'|'error'; syntaxContextError?:string|null; syntaxMode?:SyntaxContextMode; syntaxMetric?:SyntaxContextMetric; syntaxDistanceKm?:number; activeSyntaxLayer?:SyntaxLayer|null; syntaxSegments?:Segment[]; syntaxOverlayVisible?:boolean; onSyntaxOverlayVisibilityChange?:(visible:boolean)=>void; syntaxLegend?:Array<{label:string;color:string}>; }
export function fabricSiteData(input:FabricLayers) {
 const layers=normalizeFabricLayers(input);
 const buildings:Building[]=layers.buildings.features.filter(f=>f.geometry).map((f,i)=>({id:String(f.properties?.building_id??`fabric-building-${i}`), geometry:f.geometry, properties:{...f.properties,fabric_display:true},disposition:f.properties?.retained===true?'PRESERVE':'EDITABLE'}));
 const segments:Segment[]=layers.roads.features.filter(f=>f.geometry).map((f,i)=>({id:String(f.properties?.road_id??`fabric-road-${i}`),geometry:f.geometry as Segment['geometry'],length_m:typeof f.properties?.length_m==='number'?f.properties.length_m:0,layer:0,width_m:typeof f.properties?.width_m==='number'?f.properties.width_m:undefined,...{fabric_color:f.properties?.fabric_color,fabric_width:f.properties?.fabric_width}}));
 const scenarioAreas=['land_use','parks','water'].flatMap(key=>(layers[key as keyof FabricLayers]?.features??[]).filter(f=>f.geometry).map((f,i)=>({id:`${key}-${i}`,geometry:f.geometry!,kind:`fabric:${key==='land_use'?landCategory(f.properties??{}):key==='parks'?'park':key}`})));
 return {buildings,segments,scenarioAreas,studyAreaGeometry:layers.site.features[0]?.geometry??null};
}
export function FabricLegend({layers}:{layers:FabricLayers}) {const t=useT();const entries=fabricLegend(layers);return <div className="fabric-map-legend" data-testid="fabric-legend" data-legend-count={entries.length} style={{display:'flex',flexWrap:'wrap',gap:12,padding:10,fontSize:12}}>{entries.map(e=><span key={e.label} data-legend-key={e.label} data-legend-color={e.color}><i style={{display:'inline-block',width:12,height:12,background:e.color,marginRight:5}}/>{t(e.label)}</span>)}</div>;}
export function FabricViewport({id,layers,mode,viewTransform,onTransformChange,cameraState,onCameraChange,...syntax}:FabricViewportProps) {
 const data=useMemo(()=>fabricSiteData(layers),[layers]);
 const figureContext={projectId:id,workspace:null,studyArea:null,hasUnsavedChanges:false,sourcePackageRevision:null,sourceSnapshotIds:[],buildingCount:data.buildings.length,roadCount:data.segments.length,selectedFeatureIds:[]};
 const shared={...data,...syntax,selectedFeatureId:null,onSelectFeature:()=>{},figureExportReady:false};
 return <div className="fabric-viewport" data-testid={`fabric-viewport-${id}`} data-map-mode={mode} data-crs="EPSG:28992" ><div className="fabric-viewport-panes">{mode!=='3D'&&<div className="fabric-viewport-pane"><Viewport2D {...shared} viewTransform={viewTransform} onTransformChange={onTransformChange} activeSyntaxLayer={syntax.activeSyntaxLayer??null} spatialZones={[]} figureContext={{...figureContext,sourceAttributions:[],spatialZoneCount:0,activeSyntaxLayer:syntax.activeSyntaxLayer??null}}/></div>}{mode!=='2D'&&<div className="fabric-viewport-pane"><Viewport3D {...shared} cameraState={cameraState} onCameraChange={onCameraChange} syntaxSegmentValues={syntax.activeSyntaxLayer?.segment_values} figureContext={figureContext}/></div>}</div><FabricLegend layers={{...layers,blocks:{type:'FeatureCollection',features:[]}}}/></div>;
}
