"""Fail-closed validation for the append-only M2-R06/R07 Rotterdam M4H v5 package."""
from __future__ import annotations
import json, math, re, struct, sqlite3
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform as shp_transform, unary_union
from .geometry import canonical_geometry_hash, validate_geometry, GeometryValidationError
from .site_proposal import SiteProposal, sha256_file
from .boundary_decision_rotterdam_m4h import BoundarySemanticGateError, require_semantically_bounded

class RotterdamSiteProposalV5ValidationError(ValueError): pass

def _safe(root:Path,value:str)->Path:
 p=(root/PurePosixPath(value.replace('\\','/'))).resolve()
 if root.resolve() not in p.parents and p!=root.resolve(): raise RotterdamSiteProposalV5ValidationError('path escapes package')
 return p

def _load(path:Path)->Any:
 try:return json.loads(path.read_text(encoding='utf-8'))
 except Exception as exc: raise RotterdamSiteProposalV5ValidationError(f'invalid JSON: {path}') from exc

def _require(root:Path,rel:str,expected:str|None=None)->Path:
 p=_safe(root,rel)
 if not p.is_file(): raise RotterdamSiteProposalV5ValidationError(f'missing artifact: {rel}')
 if expected and sha256_file(p)!=expected: raise RotterdamSiteProposalV5ValidationError(f'hash mismatch: {rel}')
 return p

def _geom(payload:Mapping[str,Any]): return payload.get('geometry') if payload.get('type')=='Feature' else payload

def _validate_parent(root:Path,ctx:Mapping[str,Any])->Mapping[str,Any]:
 manifest=_load(_require(root,ctx['parent_integrity_path']))
 if manifest.get('parent_id')!='site-proposal-rotterdam-m4h-v4' or manifest.get('schema_version')!='m2-r06-parent-v4-integrity': raise RotterdamSiteProposalV5ValidationError('v4 parent manifest identity missing')
 for item in manifest.get('files',[]):
  p=_safe(root,item['retained_path'])
  if not p.is_file() or p.stat().st_size!=item['size_bytes'] or sha256_file(p)!=item['sha256']: raise RotterdamSiteProposalV5ValidationError(f'parent v4 byte integrity failed: {item.get("relative_path")}')
 return manifest

def _ring(g:Mapping[str,Any])->list[tuple[float,float]]:
 if g.get('type')!='Polygon' or len(g.get('coordinates',[]))!=1: raise RotterdamSiteProposalV5ValidationError('v5 boundary must be one Polygon exterior ring')
 ring=[(float(x),float(y)) for x,y in g['coordinates'][0]]
 if len(ring)<4 or ring[0]!=ring[-1]: raise RotterdamSiteProposalV5ValidationError('v5 boundary ring must be closed')
 try:validate_geometry(g)
 except GeometryValidationError as exc: raise RotterdamSiteProposalV5ValidationError(str(exc)) from exc
 return ring

def _validate_sources(root:Path,ctx:Mapping[str,Any],proposal_geom:Mapping[str,Any])->None:
 ev=_load(_require(root,ctx['boundary_relationship_evidence_path']))
 if ev.get('schema_version')!='m2-r06-boundary-relationship-evidence' or ev.get('coordinate_crs')!='EPSG:28992' or ev.get('source_dataset')!='BGT': raise RotterdamSiteProposalV5ValidationError('v5 BGT evidence schema/CRS invalid')
 paths={c:_require(root,item['path'],item['sha256']) for c,item in ev.get('source_snapshots',{}).items()}
 if set(paths) != {'wegdeel','ondersteunendwegdeel','onbegroeidterreindeel','waterdeel','begroeidterreindeel'}: raise RotterdamSiteProposalV5ValidationError('required BGT source snapshots missing')
 raws={c:_load(p) for c,p in paths.items()}; byid={(c,str(f.get('id'))):f for c,r in raws.items() for f in r.get('features',[]) if f.get('id') is not None}
 ring=_ring(proposal_geom); edges=ev.get('edges',[])
 if len(edges)!=len(ring)-1: raise RotterdamSiteProposalV5ValidationError('one source relationship is required per exterior segment')
 tx=Transformer.from_crs(4326,28992,always_xy=True)
 for i,item in enumerate(edges):
  if item.get('edge_index')!=i or item.get('claim_status')!='SOURCE_GEOMETRY_SEGMENT' or item.get('physical_edge_claim') is not True or item.get('source_dataset')!='BGT' or item.get('derived_from_union') is not True: raise RotterdamSiteProposalV5ValidationError(f'unsupported v5 boundary edge claim {i}')
  if item.get('relationship') not in {'SITE-FACING_ROAD_EDGE','SITE-FACING_SUPPLEMENTARY_EDGE'}: raise RotterdamSiteProposalV5ValidationError('boundary edge relationship taxonomy invalid')
  coll=str(item.get('source_collection')); f=byid.get((coll,str(item.get('source_feature_id')))); seg=item.get('source_segment')
  if f is None or not isinstance(seg,list) or len(seg)!=2 or any(type(v) is not int or v<0 for v in seg): raise RotterdamSiteProposalV5ValidationError(f'source feature/segment missing at edge {i}')
  geometry=f.get('geometry') or {}; coords=geometry.get('coordinates',[]); geometry_type=geometry.get('type')
  if geometry_type=='Polygon': rings=coords
  elif geometry_type=='MultiPolygon': rings=[polygon[0] for polygon in coords if polygon and polygon[0]]
  else: rings=[]
  ring_index=item.get('source_ring_index',0)
  if not rings or not isinstance(ring_index,int) or ring_index<0 or ring_index>=len(rings) or seg[1]!=seg[0]+1 or seg[1]>=len(rings[ring_index]): raise RotterdamSiteProposalV5ValidationError(f'source ring/segment index invalid at edge {i}')
  source=shp_transform(tx.transform,shape({'type':'LineString','coordinates':[rings[ring_index][seg[0]],rings[ring_index][seg[1]]]})); target=LineString([tuple(item['start_epsg28992']),tuple(item['end_epsg28992'])])
  if target.length<=0 or source.distance(target)>1e-4 or not source.buffer(1e-7).covers(target): raise RotterdamSiteProposalV5ValidationError(f'boundary segment is not the cited BGT source segment at edge {i}')
  interval=item.get('source_interval_m');
  if not isinstance(interval,list) or len(interval)!=2 or any(not math.isfinite(float(v)) or float(v)<-1e-6 or float(v)>source.length+1e-5 for v in interval): raise RotterdamSiteProposalV5ValidationError(f'source interval invalid at edge {i}')
  direction=item.get('direction');
  if direction not in {'FORWARD','REVERSE'}: raise RotterdamSiteProposalV5ValidationError(f'source direction invalid at edge {i}')
  if item.get('relationship')=='SITE-FACING_ROAD_EDGE' and coll!='wegdeel': raise RotterdamSiteProposalV5ValidationError('road relationship cites a non-road collection')
  if item.get('relationship')=='SITE-FACING_SUPPLEMENTARY_EDGE' and coll=='wegdeel': raise RotterdamSiteProposalV5ValidationError('supplementary relationship cites road collection')
 # Recompute the complete candidate overlay from retained snapshots and compare hashes.
 try:
  from scripts.create_site_proposal_rotterdam_v5 import _source_face_union
 except ModuleNotFoundError:
  from create_site_proposal_rotterdam_v5 import _source_face_union
 seed=shape(_load(_require(root,'parent-v4/parent-v3/site-proposal.json'))['geometry'])
 candidate,rebuilt,rebuild_details=_source_face_union(seed,[(c,paths[c]) for c in ['wegdeel','ondersteunendwegdeel','onbegroeidterreindeel','waterdeel','begroeidterreindeel']])
 try:
  require_semantically_bounded(
   rebuild_details.get('supplementary_runs', []),
   perimeter_m=candidate.length,
   candidate=candidate,
   seed=seed,
  )
 except BoundarySemanticGateError as exc:
  raise RotterdamSiteProposalV5ValidationError(str(exc)) from exc
 if canonical_geometry_hash(mapping_geom(candidate))!=canonical_geometry_hash(proposal_geom): raise RotterdamSiteProposalV5ValidationError('boundary does not equal deterministic offline BGT overlay rebuild')
 if len(rebuilt)!=len(edges): raise RotterdamSiteProposalV5ValidationError('recomputed relationship count mismatch')


def _validate_persisted_semantic_gate(root:Path, proposal_geom:Mapping[str,Any])->None:
 """Reject a persisted r07 candidate before any source rebuild can imply acceptance."""
 audit_path = root / 'topology-gate-audit-v5-r06.json'
 if not audit_path.is_file():
  return
 audit = _load(audit_path)
 gate = audit.get('topology_gate') or {}
 runs = gate.get('aggregated_supplementary_runs') or []
 if not isinstance(runs, list):
  raise RotterdamSiteProposalV5ValidationError('persisted supplementary semantic audit is malformed')
 try:
  seed = shape(_load(_require(root, 'parent-v4/parent-v3/site-proposal.json'))['geometry'])
  candidate = shape(proposal_geom)
  require_semantically_bounded(runs, perimeter_m=candidate.length, candidate=candidate, seed=seed)
 except BoundarySemanticGateError as exc:
  raise RotterdamSiteProposalV5ValidationError(str(exc)) from exc

def mapping_geom(g):
 from shapely.geometry import mapping
 return mapping(g)

def _validate_display(root:Path,ctx:Mapping[str,Any],proposal_geom:Mapping[str,Any])->dict[str,Any]:
 display=_load(_require(root,ctx['display_data_path']))
 expected=['background/land','water','public/open','context buildings','site buildings','roads/walk paths','rail','labels/markers','boundary']
 if display.get('classification_priority')!=expected: raise RotterdamSiteProposalV5ValidationError('display priority mismatch')
 layers=[(f.get('properties') or {}).get('display_layer') for f in display.get('features',[])]
 if any(x not in expected for x in layers) or sum(x=='water' for x in layers)>1: raise RotterdamSiteProposalV5ValidationError('display layer contract failed')
 if any((f.get('properties') or {}).get('geometry_clipped') for f in display.get('features',[]) if (f.get('properties') or {}).get('building')): raise RotterdamSiteProposalV5ValidationError('building geometry was clipped')
 if display.get('cross_boundary_buildings')!=[] or display.get('building_crossing_count')!=0: raise RotterdamSiteProposalV5ValidationError('context building crossing result is not zero')
 site_count=sum(x=='site buildings' for x in layers)
 if site_count<30: raise RotterdamSiteProposalV5ValidationError('v5 must include the retained site-building centroids')
 return display

def _validate_osm_building_audit(root:Path,ctx:Mapping[str,Any],display:Mapping[str,Any],boundary:Mapping[str,Any],bag:Mapping[str,Any])->None:
 """Recompute OSM/BAG duplicate reconciliation and compare persisted audit facts."""
 try:
  from scripts.create_site_proposal_rotterdam_v5 import _bag_by_id, _canonical_osm_building_audit, _display_audit_geometry
 except ModuleNotFoundError:
  from create_site_proposal_rotterdam_v5 import _bag_by_id, _canonical_osm_building_audit, _display_audit_geometry
 candidate=shape(boundary)
 crossings,reconciliations=_canonical_osm_building_audit(display,bag,candidate)
 if crossings: raise RotterdamSiteProposalV5ValidationError(f'OSM/BAG building crossing result is not zero/reconcilable: {crossings}')
 if display.get('osm_building_crossing_count')!=0 or display.get('building_crossing_count')!=0: raise RotterdamSiteProposalV5ValidationError('OSM building crossing count is not zero')
 if display.get('osm_raw_geometry_reconciliation_count')!=len(reconciliations) or display.get('osm_raw_geometry_reconciliations')!=reconciliations: raise RotterdamSiteProposalV5ValidationError('OSM raw geometry reconciliation audit is not recomputable')
 if ctx.get('osm_building_crossing_count')!=0 or ctx.get('osm_raw_geometry_reconciliation_count')!=len(reconciliations) or ctx.get('osm_raw_geometry_reconciliations')!=reconciliations: raise RotterdamSiteProposalV5ValidationError('context OSM/BAG audit fields do not match recomputation')
 evidence=_load(_require(root,ctx['boundary_relationship_evidence_path']))
 if evidence.get('osm_building_crossing_count')!=0 or evidence.get('osm_raw_geometry_reconciliation_count')!=len(reconciliations) or evidence.get('osm_raw_geometry_reconciliations')!=reconciliations: raise RotterdamSiteProposalV5ValidationError('evidence OSM/BAG audit fields do not match recomputation')
 if evidence.get('building_crossing_method')!=ctx.get('building_crossing_method'): raise RotterdamSiteProposalV5ValidationError('building crossing method is not consistent')
 tolerance=ctx.get('osm_bag_reconciliation_tolerance') or {}
 if tolerance.get('symmetric_difference_area_m2_max')!=1.0 or tolerance.get('hausdorff_distance_m_max')!=0.01: raise RotterdamSiteProposalV5ValidationError('OSM/BAG reconciliation tolerance changed')
 bag_by_id=_bag_by_id(bag)
 for feature in display.get('features',[]):
  props=feature.get('properties') or {}
  if not props.get('building'): continue
  _,audit=_display_audit_geometry(feature,bag_by_id)
  if audit:
   for key in ('canonical_bag_id','canonical_geometry_source','osm_geometry_sha256','bag_geometry_sha256','osm_bag_reconciliation_status'):
    if props.get(key)!=audit.get(key): raise RotterdamSiteProposalV5ValidationError(f'display OSM/BAG audit field mismatch: {key}')
   for key in ('osm_bag_discrepancy_area_m2','osm_bag_hausdorff_distance_m'):
    if abs(float(props.get(key))-float(audit.get(key)))>1e-9: raise RotterdamSiteProposalV5ValidationError(f'display OSM/BAG metric mismatch: {key}')
  if props.get('cross_boundary'): raise RotterdamSiteProposalV5ValidationError('display retains a cross-boundary building flag')

def _validate_metrics(root:Path,ctx:Mapping[str,Any],proposal_geom:Mapping[str,Any],display:Mapping[str,Any])->None:
 m=ctx.get('intent_drift_metrics') or {}; boundary=shape(proposal_geom); seed=shape(_load(_require(root,'parent-v4/parent-v3/site-proposal.json'))['geometry'])
 for key in ['intersection_area_m2','symmetric_difference_area_m2','area_ratio_candidate_to_seed','relative_area_delta','road_surface_overlap_ratio']:
  if key not in m or not math.isfinite(float(m[key])): raise RotterdamSiteProposalV5ValidationError(f'missing metric: {key}')
 if abs(float(m['intersection_area_m2'])-seed.intersection(boundary).area)>1e-3 or abs(float(m['symmetric_difference_area_m2'])-seed.symmetric_difference(boundary).area)>1e-3 or abs(float(m['area_ratio_candidate_to_seed'])-boundary.area/seed.area)>1e-8: raise RotterdamSiteProposalV5ValidationError('intent-drift metrics are not recomputable')
 if boundary.area<10000 or float(m['area_ratio_candidate_to_seed'])<0.5 or float(m['area_ratio_candidate_to_seed'])>1.5 or float(m['symmetric_difference_area_m2'])/seed.area>0.75: raise RotterdamSiteProposalV5ValidationError('candidate exhibits v4-like collapse or excessive seed drift')
 if float(m['road_surface_overlap_ratio'])>=0.75: raise RotterdamSiteProposalV5ValidationError('candidate interior is road-surface dominant')
 if m.get('candidate_building_centroid_count',0)<30 or m.get('seed_building_centroid_count',0)<30: raise RotterdamSiteProposalV5ValidationError('site building centroid counts are missing')

def _validate_png(root:Path,ctx:Mapping[str,Any],diag:bool=False)->None:
 rel=ctx['diagnostic_png_path'] if diag else ctx['rendered_png_path']; expected=ctx['diagnostic_png_sha256'] if diag else ctx['rendered_png_sha256']; p=_require(root,rel,expected); raw=p.read_bytes()
 if raw[:8]!=b'\x89PNG\r\n\x1a\n' or len(raw)<24 or struct.unpack('>II',raw[16:24])!=(1240,850) or b'IDAT' not in raw: raise RotterdamSiteProposalV5ValidationError(f'{rel} is not a nonblank 1240x850 PNG')

def _validate_maps(root:Path,ctx:Mapping[str,Any])->None:
 svg=_require(root,ctx['map_svg_path'],ctx['map_svg_sha256']).read_text(encoding='utf-8'); required=['layer-background','layer-water','layer-public-space','layer-context-buildings','layer-site-buildings','layer-roads','layer-rail','layer-markers','layer-boundary']; ids=re.findall(r'<g id="([^"]+)"',svg)
 if [x for x in ids if x in required]!=required: raise RotterdamSiteProposalV5ValidationError('main SVG layer order mismatch')
 for token in ['#d62728','stroke-width="1.4"','fill="none"','site-proposal-rotterdam-m4h-v5','BGT site-facing polygon edges','REJECTED_BY_HUMAN_FEEDBACK']: 
  if token not in svg: raise RotterdamSiteProposalV5ValidationError(f'main SVG token missing: {token}')
 diag=_require(root,ctx['diagnostic_svg_path'],ctx['diagnostic_svg_sha256']).read_text(encoding='utf-8')
 for token in ['v3 seed','v5 proposal','official BGT perimeter edges','stroke="#9aa3a8"','stroke="#d62728"','stroke="#1976d2"']: 
  if token not in diag: raise RotterdamSiteProposalV5ValidationError(f'diagnostic SVG token missing: {token}')
 _validate_png(root,ctx); _validate_png(root,ctx,diag=True)

def _validate_state(root:Path,proposal:SiteProposal)->None:
 with sqlite3.connect(_safe(root,proposal.delft_context['state_path'])) as con:
  rows=con.execute("select entity_type,payload_json from state_versions where entity_type in ('Project','Site','SiteModel','SiteProposal','ContestEvent')").fetchall();
  if not rows: raise RotterdamSiteProposalV5ValidationError('state has no records')
  found=False
  for typ,payload in rows:
   d=json.loads(payload)
   if typ=='Project' and d.get('id')==proposal.project_id and d.get('site_id') is not None: raise RotterdamSiteProposalV5ValidationError('Project.site_id must remain null')
   if typ in {'Site','SiteModel'} and d.get('version')=='v5':
    found=True
    if str(d.get('status','')).upper()!='PROPOSED': raise RotterdamSiteProposalV5ValidationError('v5 Site is not PROPOSED')
   if typ=='SiteProposal' and d.get('id')==proposal.id and d.get('status')!='PROPOSED': raise RotterdamSiteProposalV5ValidationError('v5 SiteProposal is not PROPOSED')
  if not found: raise RotterdamSiteProposalV5ValidationError('v5 Site record missing')
  events=con.execute('select action,reason,payload_json from ledger_events').fetchall();
  if any(any(t in str(a).lower() for t in ('approve','accept','freeze')) for a,_,_ in events): raise RotterdamSiteProposalV5ValidationError('approval/accept/freeze event present')
  if not any('REJECTED_BY_CONTROL_TOWER_INVALID_SITE_SEMANTICS' in f'{reason} {payload}' for _,reason,payload in events): raise RotterdamSiteProposalV5ValidationError('v4 automated rejection marker missing')

def validate_site_proposal_rotterdam_v5(proposal:SiteProposal|Mapping[str,Any],package_root:str|Path,*,v4_dir:str|Path|None=None)->SiteProposal:
 candidate=proposal if isinstance(proposal,SiteProposal) else SiteProposal.model_validate(proposal)
 if candidate.id!='site-proposal-rotterdam-m4h-v5' or candidate.version!='v5' or candidate.supersedes_proposal_id!='site-proposal-rotterdam-m4h-v4': raise RotterdamSiteProposalV5ValidationError('wrong v5 identity/lineage')
 root=Path(package_root).resolve(); ctx=candidate.delft_context
 _validate_persisted_semantic_gate(root, candidate.geometry)
 _validate_parent(root,ctx)
 bp=_require(root,candidate.boundary_artifact_path,candidate.boundary_sha256)
 if bp.stat().st_size!=candidate.boundary_size_bytes: raise RotterdamSiteProposalV5ValidationError('boundary artifact size mismatch')
 geom=_geom(_load(bp)); _ring(geom)
 if geom!=candidate.geometry or canonical_geometry_hash(geom)!=candidate.geometry_sha256: raise RotterdamSiteProposalV5ValidationError('boundary geometry/hash mismatch')
 _validate_sources(root,ctx,geom); display=_validate_display(root,ctx,geom); _validate_metrics(root,ctx,geom,display)
 bag=_load(_require(root,ctx['bag_source_path'],ctx['bag_source_sha256']))
 boundary=shape(geom); tx=Transformer.from_crs(4326,28992,always_xy=True); crossings=[]
 for f in bag.get('features',[]):
  g=shp_transform(tx.transform,shape(f.get('geometry') or {})); area=g.intersection(boundary).area
  if area>1e-7 and area<g.area-1e-5: crossings.append(str((f.get('properties') or {}).get('identificatie') or f.get('id') or 'unknown'))
 if sorted(set(crossings))!=ctx.get('bag_cross_boundary_buildings',[]) or crossings: raise RotterdamSiteProposalV5ValidationError('BAG building crossing result is not zero/recomputable')
 _validate_osm_building_audit(root,ctx,display,geom,bag)
 _validate_maps(root,ctx); _validate_state(root,candidate)
 return candidate

__all__=['RotterdamSiteProposalV5ValidationError','validate_site_proposal_rotterdam_v5']
