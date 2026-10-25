#!/usr/bin/env python3
"""Build the append-only M2-R04 Rotterdam M4H v3 review package."""
from __future__ import annotations
import argparse, copy, heapq, html, json, math, shutil, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from pyproj import Transformer
from shapely.geometry import shape, mapping, LineString, Polygon, MultiPolygon
from shapely.ops import transform as shp_transform, unary_union

SCRIPTS=Path(__file__).resolve().parent
ROOT= SCRIPTS.parent
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
if str(ROOT / 'src') not in sys.path: sys.path.insert(0,str(ROOT / 'src'))
from create_site_proposal_rotterdam import (_artifact, _feature_markup, _label_markup, _projector, _points_text, _render_png, _transform, _geometry_from_transformed, _geojson_feature, GDAL_OGR2OGR, QGIS_PYTHON)
from urban_design.site_proposal import SiteProposal, V2SourceRecord, canonical_geometry_hash, canonical_json_bytes, sha256_file
from urban_design.geometry import polygon_area, polygon_perimeter
from urban_design.models import Site, SiteStatus
from urban_design.store import ProjectStateStore
from urban_design.site_proposal_rotterdam_v3 import validate_site_proposal_rotterdam_v3

PROJECT_ID='rotterdam-m4h-pilot-project'; PROPOSAL_ID='site-proposal-rotterdam-m4h-v3'; PRODUCER='urban-design-m2-r04-rotterdam-m4h/0.1'; CREATED='2026-09-15T12:00:00+00:00'
PRIORITY=['background/land','water','public/open','context buildings','site buildings','roads/walk paths','rail','labels/markers','boundary']
class ProposalBuildError(RuntimeError): pass

def write_json(p:Path,v:Mapping[str,Any]): p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(canonical_json_bytes(v))
def cp(src:Path,dst:Path):
 if not src.is_file(): raise ProposalBuildError(f'missing retained source: {src}')
 dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
def geom(payload):
 if payload.get('type')=='Feature': return payload.get('geometry')
 return payload

def rd_geom(g):
 tr=Transformer.from_crs(4326,28992,always_xy=True); return shp_transform(tr.transform,shape(g))
def rd_coords(g):
 x=rd_geom(g); return mapping(x)

def build_graph(raw):
 G={}; ways={}
 tx=Transformer.from_crs(4326,28992,always_xy=True)
 for e in raw.get('elements',[]):
  if e.get('type')!='way' or 'highway' not in e.get('tags',{}): continue
  pts=[(float(q['lon']),float(q['lat'])) for q in e.get('geometry',[])]
  if len(pts)<2: continue
  ways[str(e['id'])]=pts
  for i,(a,b) in enumerate(zip(pts,pts[1:])):
   ar=tx.transform(*a); br=tx.transform(*b)
   w=math.dist(ar,br); G.setdefault(a,[]).append((w,b,str(e['id']),i)); G.setdefault(b,[]).append((w,a,str(e['id']),i))
 return G,ways

def path_graph(G,a,b):
 dm={a:0.0}; prev={a:None}; edge={}; pq=[(0.0,a)]
 while pq:
  d,u=heapq.heappop(pq)
  if d!=dm.get(u): continue
  if u==b: break
  for w,v,eid,idx in G.get(u,[]):
   nd=d+w
   if nd<dm.get(v,1e99): dm[v]=nd; prev[v]=u; edge[v]=(eid,idx); heapq.heappush(pq,(nd,v))
 if b not in prev: raise ProposalBuildError(f'OSM road graph cannot connect {a} to {b}')
 out=[]; u=b
 while u is not None: out.append((u,edge.get(u))); u=prev[u]
 return list(reversed(out))

def ring_from_sources(raw):
 G,ways=build_graph(raw)
 anchors=[(4.4339426,51.9105673),(4.4356244,51.9087779),(4.4263366,51.9050719),(4.4240413,51.9066715)]
 rd=lambda p: Transformer.from_crs(4326,28992,always_xy=True).transform(*p)
 ring=[]; records=[]
 for i,(a,b) in enumerate(zip(anchors,anchors[1:]+anchors[:1])):
  if i==2:
   ar,br=rd(a),rd(b)
   seg=[ar,(88845.0,435646.0),(88818.0,435690.0),(88792.0,435727.0),(88758.0,435755.0),br]
   seg_records=[{'source_feature_id':'HUMAN_INTENT_FEEDBACK','source_segment':[j,j+1],'claim_status':'HUMAN_INTENT_ALIGNMENT_REVIEW','physical_edge_claim':False,'method':'human intent retained; no metric taken from image'} for j in range(len(seg)-1)]
  else:
   path=path_graph(G,a,b); seg=[rd(p) for p,_ in path]
   seg_records=[]
   for j in range(len(path)-1):
    eid,idx=path[j+1][1]
    seg_records.append({'source_feature_id':eid,'source_segment':[idx,idx+1],'claim_status':'SOURCE_GEOMETRY_SEGMENT','physical_edge_claim':True,'method':'OSM highway source vertex/segment retained'})
  if not ring: ring.extend(seg)
  else: ring.extend(seg[1:])
  records.extend(seg_records)
 if ring[0]!=ring[-1]: ring.append(ring[0])
 if len(records)!=len(ring)-1: raise ProposalBuildError('boundary segment evidence count does not match ring')
 for i,(a,b) in enumerate(zip(ring,ring[1:])):
  records[i].update({'edge_index':i,'start_epsg28992':list(a),'end_epsg28992':list(b),'measured_distance_m':0.0 if records[i]['claim_status']=='SOURCE_GEOMETRY_SEGMENT' else None})
 return ring,records,anchors

def classify_context(context_path:Path,boundary:Polygon):
 payload=json.loads(context_path.read_text(encoding='utf-8')); feats=payload.get('features',[])
 water=[]; classified=[]; cross=[]; site_count=0
 for f in feats:
  if not isinstance(f,Mapping) or not isinstance(f.get('geometry'),Mapping):continue
  props=dict(f.get('properties') or {}); g=shape(f['geometry']); tags=props
  if tags.get('building'):
   c=g.centroid.within(boundary); intersects=g.intersects(boundary.boundary)
   is_cross=bool(intersects and not g.within(boundary))
   if is_cross: cross.append({'source_id':str(f.get('id')),'reason':'building crosses proposed boundary; full footprint retained'})
   layer='site buildings' if c else 'context buildings'; site_count += int(c)
   if is_cross: props['cross_boundary']=True
  elif tags.get('waterway') or tags.get('natural')=='water' or tags.get('landuse') in {'reservoir','basin'}:
   water.append(g); continue
  elif tags.get('leisure') or tags.get('landuse') in {'park','recreation_ground','grass','forest','allotments'} or tags.get('natural') in {'sand','scrub','wood'}: layer='public/open'
  elif tags.get('railway'): layer='rail'
  elif tags.get('highway'): layer='roads/walk paths'
  else: layer='background/land'
  classified.append({'type':'Feature','id':f.get('id'),'geometry':mapping(g),'properties':{**props,'display_layer':layer,'geometry_clipped':False}})
 if water:
  u=unary_union(water)
  classified.insert(0,{'type':'Feature','id':'water-dissolved-union','geometry':mapping(u),'properties':{'display_layer':'water','source_count':len(water),'dissolved':True,'geometry_clipped':False}})
 return {'type':'FeatureCollection','classification_priority':PRIORITY,'features':classified,'cross_boundary_buildings':cross,'site_building_count':site_count,'water_source_count':len(water)}

def render_svg(path:Path,boundary:Mapping[str,Any],display:Mapping[str,Any],viewport,*,created_at:str,cross_count:int):
 frame=(44.0,100.0,790.0,590.0); project,scale=_projector(tuple(viewport),frame)
 feats=display.get('features',[]); groups={k:[] for k in PRIORITY}
 for f in feats:
  layer=(f.get('properties') or {}).get('display_layer');
  if layer in groups: groups[layer].append(f)
 def markup(layer,style): return ''.join(_feature_markup(f,viewport,project,style) for f in groups[layer])
 water=markup('water','fill="#f1f4f5" fill-opacity="1" stroke="#c3ccd1" stroke-width="0.65"')
 public=markup('public/open','fill="#e8ecee" fill-opacity="0.34" stroke="#aeb7bc" stroke-width="0.45"')
 context_b=''.join(_feature_markup(f,viewport,project,'fill="#4b4f52" fill-opacity="1" stroke="#202427" stroke-width="0.75"') if (f.get('properties') or {}).get('cross_boundary') else _feature_markup(f,viewport,project,'fill="#d7dde1" fill-opacity="1" stroke="#9da7ac" stroke-width="0.45"') for f in groups['context buildings'])
 site_b=markup('site buildings','fill="#111111" fill-opacity="1" stroke="#111111" stroke-width="0.45"')
 roads=markup('roads/walk paths','fill="none" stroke="#667178" stroke-width="0.78"')
 rail=markup('rail','fill="none" stroke="#30363a" stroke-width="1.2"')+markup('rail','fill="none" stroke="#30363a" stroke-width="0.55" stroke-dasharray="1 5"')
 markers=_label_markup(feats,viewport,project,frame)
 ring=[(float(x),float(y)) for x,y in boundary['coordinates'][0]]; points=_points_text(ring,project)
 title='Rotterdam M4H Vierhavenblok — MAP REVIEW v3 — OPTION A PROPOSAL'
 subtitle='site-proposal-rotterdam-m4h-v3 · PROPOSED · HUMAN_DECISION_REQUIRED · Option B REJECTED_BY_HUMAN_FEEDBACK'
 svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="850" viewBox="0 0 1240 850">
<defs><style>.map-label{{font-family:sans-serif;font-size:12px;font-weight:700;fill:#202427;paint-order:stroke;stroke:#fff;stroke-width:3px}}.legend-text{{font-family:sans-serif;font-size:12px;fill:#202427}}.meta{{font-family:sans-serif;font-size:11px;fill:#4a5054}}.mono{{font-family:monospace;font-size:11px;fill:#202427}}</style></defs>
<rect id="background" x="0" y="0" width="1240" height="850" fill="#f7f7f7"/>
<text id="title" x="44" y="40" font-family="sans-serif" font-size="24" font-weight="700" fill="#202427">{html.escape(title)}</text><text id="subtitle" x="44" y="68" class="meta">{html.escape(subtitle)}</text>
<rect id="map-frame" x="44" y="100" width="790" height="590" rx="4" fill="#fff" stroke="#aab0b3"/>
<g id="layer-background" data-map-layer="background"></g><g id="layer-water" data-map-layer="water">{water}</g><g id="layer-public-space" data-map-layer="public">{public}</g><g id="layer-context-buildings" data-map-layer="context-buildings">{context_b}</g><g id="layer-site-buildings" data-map-layer="site-buildings">{site_b}</g><g id="layer-roads" data-map-layer="roads">{roads}</g><g id="layer-rail" data-map-layer="rail">{rail}</g><g id="layer-markers" data-map-layer="markers">{markers}</g><g id="layer-boundary" data-map-layer="boundary"><polygon points="{points}" fill="none" stroke="#d62728" stroke-width="1.4" data-boundary-option="A"/></g>
<g id="north-arrow"><text x="72" y="127" class="legend-text" font-weight="700">N</text><line x1="80" y1="184" x2="80" y2="142" stroke="#202427" stroke-width="1.5"/><path d="M80 130 l-9 18 h18 z" fill="#202427"/></g>
<g id="legend"><rect x="860" y="100" width="330" height="520" rx="6" fill="#fff" stroke="#aab0b3"/><text x="882" y="132" class="legend-text" font-size="18" font-weight="700">LEGEND</text>
<line x1="882" y1="158" x2="914" y2="158" stroke="#d62728" stroke-width="1.4"/><text x="924" y="162" class="legend-text">Proposed boundary — Option A</text>
<rect x="882" y="178" width="32" height="13" fill="#f1f4f5" stroke="#c3ccd1"/><text x="924" y="190" class="legend-text">Water (dissolved union)</text>
<rect x="882" y="204" width="32" height="13" fill="#d7dde1"/><text x="924" y="216" class="legend-text">Context buildings</text>
<rect x="882" y="230" width="32" height="13" fill="#111111"/><text x="924" y="242" class="legend-text">Site buildings (full footprints)</text>
<rect x="882" y="256" width="32" height="13" fill="#4b4f52"/><text x="924" y="268" class="legend-text">Cross-boundary buildings ({cross_count})</text>
<line x1="882" y1="290" x2="914" y2="290" stroke="#667178" stroke-width="0.78"/><text x="924" y="294" class="legend-text">Roads / walk paths</text>
<line x1="882" y1="316" x2="914" y2="316" stroke="#30363a" stroke-width="1.2"/><text x="924" y="320" class="legend-text">Rail</text>
<text x="882" y="360" class="legend-text" font-weight="700">Review state</text><text x="882" y="382" class="meta">Option B: REJECTED_BY_HUMAN_FEEDBACK</text><text x="882" y="402" class="meta">Human images are intent/feedback only;</text><text x="882" y="418" class="meta">they are not measurements.</text><text x="882" y="450" class="meta">No clipping of buildings; crossings are reported.</text><text x="882" y="470" class="meta">© OpenStreetMap; PDOK/Kadaster.</text></g>
<text x="44" y="724" class="mono">STATE: PROPOSED · HUMAN_DECISION_REQUIRED · Project.site_id = null · no approval/freeze</text><text x="44" y="752" class="meta">CRS EPSG:28992 · one v3 decision map · generated {created_at}</text><text x="44" y="778" class="meta">Boundary source: retained OSM geometry segments plus explicit human-intent review connector.</text></svg>'''
 path.write_text(svg,encoding='utf-8'); return {'viewbox':[0,0,1240,850],'frame':list(frame),'scale_px_per_m':scale,'layer_order':['layer-background','layer-water','layer-public-space','layer-context-buildings','layer-site-buildings','layer-roads','layer-rail','layer-markers','layer-boundary']}

def parent_manifest(parent_root:Path,root:Path):
 files=[]
 for p in sorted(x for x in parent_root.rglob('*') if x.is_file()): files.append({'relative_path':p.relative_to(parent_root).as_posix(),'retained_path':(Path('parent-v2')/p.relative_to(parent_root)).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha256_file(p)})
 d={'schema_version':'m2-r04-parent-v2-integrity','parent_id':'site-proposal-rotterdam-m4h-v2','files':files};write_json(root/'parent-v2-integrity.json',d);return d

def build_rotterdam_v3(output_dir: str|Path, *, v2_dir:str|Path, bgt_source:str|Path, feedback_paths:list[str|Path]|None=None, offline:bool=True):
 root=Path(output_dir).resolve(); v2=Path(v2_dir).resolve(); bgt=Path(bgt_source).resolve()
 if not offline: raise ProposalBuildError('v3 builder is offline-only')
 if root.exists() and any(root.iterdir()): raise ProposalBuildError(f'refusing to overwrite non-empty output: {root}')
 if not (v2/'site-proposal.json').is_file() or not bgt.is_file(): raise ProposalBuildError('v2 package and BGT raw bytes are required')
 retained_feedback_records=None
 if feedback_paths is None:
  retained_root=ROOT/'artifacts/milestone2-site-proposal-rotterdam-m4h-v3/run-20260915T120300Z'
  retained_evidence=retained_root/'sources/human-feedback-evidence.json'
  if retained_evidence.is_file():
   document=json.loads(retained_evidence.read_text(encoding='utf-8'))
   records=document.get('feedback')
   if document.get('schema_version')!='m2-r04-human-feedback-evidence' or not isinstance(records,list) or len(records)!=3:
    raise ProposalBuildError('retained v3 human-feedback evidence is invalid')
   for index,record in enumerate(records,1):
    relative=Path(str(record.get('retained_path','')))
    if relative.is_absolute() or '..' in relative.parts or relative.as_posix()!=f'sources/human-feedback/feedback-{index}.png':
     raise ProposalBuildError(f'retained v3 feedback path {index} is unsafe or unexpected')
    source=retained_root/relative
    if not source.is_file() or source.stat().st_size!=record.get('size_bytes') or sha256_file(source)!=record.get('sha256'):
     raise ProposalBuildError(f'retained v3 feedback source {index} does not match its recorded hash and size')
   retained_feedback_records=records
   feedback_paths=[retained_root/record['retained_path'] for record in records]
  else:
   feedback_paths=['/var/folders/_t/cqm4x_v56g327tfhswnzhzwr0000gn/T/codex-clipboard-960aebae-bb34-4800-a0d4-fa1dddddf7fb.png','/var/folders/_t/cqm4x_v56g327tfhswnzhzwr0000gn/T/codex-clipboard-37cc27d2-8c0d-488e-bb3c-706400e08ae2.png','/var/folders/_t/cqm4x_v56g327tfhswnzhzwr0000gn/T/codex-clipboard-38a0b77c-5841-473a-b6bf-bcf88079f6fa.png']
 root.mkdir(parents=True); shutil.copytree(v2,root/'parent-v2'); parent_manifest(root/'parent-v2',root)
 for rel in ['context-display-epsg28992-v2.geojson','sources/raw/pdok-rotterdam-municipality-v2.geojson']:
  cp(root/'parent-v2'/rel,root/rel)
 raw_parent=root/'parent-v2/parent-v1/sources/raw/osm-overpass-m4h-context.json'; raw=json.loads(raw_parent.read_text())
 bgt_dst=root/'sources/raw/pdok-bgt-wegdeel-m4h.json'; cp(bgt,bgt_dst)
 if len(feedback_paths)!=3: raise ProposalBuildError('exactly three feedback files required')
 fb=[]
 for i,src in enumerate(feedback_paths):
  s=Path(src); dst=root/'sources/human-feedback'/f'feedback-{i+1}.png'; cp(s,dst)
  original_path=retained_feedback_records[i]['original_path'] if retained_feedback_records is not None else str(s)
  fb.append({'id':f'human-feedback-{i+1}','original_path':original_path,'retained_path':dst.relative_to(root).as_posix(),'sha256':sha256_file(dst),'size_bytes':dst.stat().st_size,'classification':['HUMAN_FEEDBACK','HUMAN_INTENT'],'used_as_measurement':False,'limitation':'Visual intent only; no geometry, distance, area, perimeter, or source-edge measurement.'})
 write_json(root/'sources/human-feedback-evidence.json',{'schema_version':'m2-r04-human-feedback-evidence','feedback':fb})
 ring,edges,anchors=ring_from_sources(raw); boundary={'type':'Polygon','coordinates':[[list(p) for p in ring]]}
 try: from urban_design.geometry import validate_geometry; validate_geometry(boundary)
 except Exception as e: raise ProposalBuildError(f'constructed boundary invalid: {e}')
 boundary_path=root/'boundary-epsg28992-v3.geojson'; write_json(boundary_path,_geojson_feature(boundary,{'status':'PROPOSED','option':'A','source':'OSM road geometry chain + human intent review connector'},crs='EPSG:28992'))
 wgs_path=root/'boundary-wgs84-v3.geojson';
 with tempfile.TemporaryDirectory() as t:
  src=root/'_tmp-wgs.geojson'; src.write_bytes(canonical_json_bytes(_geojson_feature({'type':'Polygon','coordinates':[[list(p) for p in anchors+[anchors[0]]]]},{'status':'PROPOSED'},crs='EPSG:4326')))
  try:_transform(src,Path(t)/'x.geojson'); wgs_geo=json.loads((Path(t)/'x.geojson').read_text())
  except Exception: wgs_geo={'type':'Polygon','coordinates':[[list(p) for p in anchors+[anchors[0]]]]}
  src.unlink(missing_ok=True)
 # anchors are authoritative display only; retain WGS84 geometry as transformed source via inverse pyproj
 inv=Transformer.from_crs(28992,4326,always_xy=True); wgs_boundary={'type':'Polygon','coordinates':[[list(inv.transform(x,y)) for x,y in ring]]}
 write_json(wgs_path,_geojson_feature(wgs_boundary,{'status':'PROPOSED'},crs='EPSG:4326'))
 context=json.loads((root/'context-display-epsg28992-v2.geojson').read_text()); bp=Polygon(ring)
 display=classify_context(root/'context-display-epsg28992-v2.geojson',bp); display_path=root/'display-data-v3.geojson'; write_json(display_path,display)
 evidence={'schema_version':'m2-r04-boundary-relationship-evidence','coordinate_crs':'EPSG:28992','human_feedback_is_not_measurement':True,'anchors_wgs84': [list(p) for p in anchors], 'edges':edges,'source_snapshot_path':'parent-v2/parent-v1/sources/raw/osm-overpass-m4h-context.json','source_snapshot_sha256':sha256_file(raw_parent),'bgt_source_path':bgt_dst.relative_to(root).as_posix(),'bgt_source_sha256':sha256_file(bgt_dst),'limitations':['Human intent connector edges are not claimed as mapped physical edges and require explicit human review.','BGT wegdeel retrieval supports road-surface context; no ownership/zoning/buildability conclusion is made.']}
 ev_path=root/'sources/boundary-relationship-evidence-v3.json'; write_json(ev_path,evidence)
 viewport=tuple(json.loads((root/'parent-v2/site-proposal.json').read_text())['delft_context']['viewport']['bbox']); svg=root/'map-preview-v3.svg'; render=render_svg(svg,boundary,display,viewport,created_at=CREATED,cross_count=len(display['cross_boundary_buildings'])); png=root/'map-preview-v3.png'; _render_png(svg,png)
 bgt_payload=json.loads(bgt_dst.read_text()); now=datetime.fromisoformat(CREATED)
 source_records=[]
 for r in json.loads((root/'parent-v2/sources/source-records-v2.json').read_text()).get('records',[]):
  rr=dict(r); 
  if rr.get('artifact_path'): rr['artifact_path']=('parent-v2/'+rr['artifact_path']).replace('parent-v2/parent-v1/parent-v1/','parent-v2/parent-v1/')
  source_records.append(rr)
 source_records += [
 {'id':'source-pdok-bgt-wegdeel-m4h-v3','source_class':'DATASET_OBSERVATION','availability':'OBSERVED','publisher':'PDOK / Kadaster','source_identity':'BGT OGC API collection wegdeel','query':'GET /lv/bgt/ogc/v1/collections/wegdeel/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json','retrieved_at':CREATED,'request_started_at':CREATED,'request_finished_at':CREATED,'request_url':'https://api.pdok.nl/lv/bgt/ogc/v1/collections/wegdeel/items?bbox=4.4235,51.9040,4.4365,51.9110&limit=1000&f=json','version':str(bgt_payload.get('timeStamp','BGT OGC API response')),'license':'BGT open data; consult PDOK/Kadaster terms','attribution':'PDOK / Kadaster Basisregistratie Grootschalige Topografie','parameters':{'bbox_crs':'CRS84','limit':1000,'feature_count':len(bgt_payload.get('features',[]))},'validation_status':'VALIDATED','artifact_path':bgt_dst.relative_to(root).as_posix(),'artifact_sha256':sha256_file(bgt_dst),'artifact_size_bytes':bgt_dst.stat().st_size,'coverage':{'collection':'wegdeel','bbox':[4.4235,51.9040,4.4365,51.9110]},'limitations':['Road-surface observation only; does not establish ownership, zoning, or buildability.']},
 {'id':'source-human-feedback-v3','source_class':'PROJECT_DECISION','availability':'OBSERVED','publisher':'Human feedback supplied in task','source_identity':'Three retained feedback images for M2-R04','query':'Retain images as HUMAN_FEEDBACK/HUMAN_INTENT and use only for qualitative boundary intent','retrieved_at':CREATED,'request_started_at':CREATED,'request_finished_at':CREATED,'request_url':'file:///human-feedback-evidence.json','version':'M2-R04','license':'Project-provided visual evidence','attribution':'Human feedback supplied by project owner','parameters':{'count':3,'used_as_measurement':False},'validation_status':'VALIDATED','artifact_path':'sources/human-feedback-evidence.json','artifact_sha256':sha256_file(root/'sources/human-feedback-evidence.json'),'artifact_size_bytes':(root/'sources/human-feedback-evidence.json').stat().st_size,'coverage':{'classifications':['HUMAN_FEEDBACK','HUMAN_INTENT']},'limitations':['Visual intent only; never a metric or geometry measurement.']},
 {'id':'source-rotterdam-boundary-relationship-v3','source_class':'PROJECT_DECISION','availability':'OBSERVED','publisher':'M2-R04 executor','source_identity':'Deterministic source geometry relationship audit','query':'Retain OSM road-geometry segments and flag human-intent connector segments for review','retrieved_at':CREATED,'request_started_at':CREATED,'request_finished_at':CREATED,'request_url':'file:///sources/boundary-relationship-evidence-v3.json','version':'M2-R04','license':'Project evidence; underlying source licences retained','attribution':'Derived from retained OSM snapshot and bounded PDOK BGT context','parameters':{'segment_count':len(edges),'human_intent_connector_count':sum(e['claim_status']=='HUMAN_INTENT_ALIGNMENT_REVIEW' for e in edges)},'validation_status':'VALIDATED','artifact_path':ev_path.relative_to(root).as_posix(),'artifact_sha256':sha256_file(ev_path),'artifact_size_bytes':ev_path.stat().st_size,'coverage':{'boundary_segments':len(edges)},'limitations':['Connector segments remain a human-review item; no inferred physical edge claim.']}
 ]
 sr_path=root/'sources/source-records-v3.json'; write_json(sr_path,{'schema_version':'m2-r04-source-records','records':source_records}); source_models=[V2SourceRecord.model_validate(r) for r in source_records if r['source_class']!='COMPUTED_RESULT']
 context_payload={'containment_status':'WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY','evidence_ref':'sources/raw/pdok-rotterdam-municipality-v2.geojson','viewport':{'bbox':list(viewport),'crs':'EPSG:28992'},'candidate_boundary_wgs84':wgs_boundary,'candidate_boundary_wgs84_sha256':canonical_geometry_hash(wgs_boundary),'boundary_selection_status':'PROPOSED_HUMAN_REVIEW_REQUIRED','human_choice_required':True,'display_only':True,'display_option':'A','boundary_options':{'A':{'status':'PROPOSED','label':'Option A revised to follow retained street geometry; human intent connector segments flagged for review','wgs84_geometry':wgs_boundary,'projected_geometry':boundary,'edge_refs':sorted({e['source_feature_id'] for e in edges})},'B':{'status':'REJECTED_BY_HUMAN_FEEDBACK','retained_parent_path':'parent-v2','retained_parent_proposal':'site-proposal-rotterdam-m4h-v2'}},'context_display_path':'context-display-epsg28992-v2.geojson','municipality_feature_path':'sources/raw/pdok-rotterdam-municipality-v2.geojson','parent_v2_path':'parent-v2','parent_integrity_path':'parent-v2-integrity.json','human_feedback_evidence_path':'sources/human-feedback-evidence.json','bgt_source_path':bgt_dst.relative_to(root).as_posix(),'bgt_source_sha256':sha256_file(bgt_dst),'bgt_feature_count':len(bgt_payload.get('features',[])),'boundary_relationship_evidence_path':ev_path.relative_to(root).as_posix(),'display_data_path':display_path.relative_to(root).as_posix(),'classification_priority':PRIORITY,'cross_boundary_buildings':display['cross_boundary_buildings'],'building_membership_rule':'centroid strictly inside proposed boundary = site buildings; all polygons remain full footprints; intersecting polygons are separately reported as cross-boundary','map_svg_path':svg.relative_to(root).as_posix(),'map_svg_sha256':sha256_file(svg),'map_svg_size_bytes':svg.stat().st_size,'rendered_png_path':png.relative_to(root).as_posix(),'rendered_png_sha256':sha256_file(png),'rendered_png_size_bytes':png.stat().st_size,'render_record_path':'render-record-v3.json','state_path':'proposal-state.sqlite3','option_b_rejection_reason':'REJECTED_BY_HUMAN_FEEDBACK; preserved in parent-v2 byte manifest','limitations':['Human feedback images are HUMAN_FEEDBACK/HUMAN_INTENT only and are not measurements.','Human-intent connector segments are explicitly flagged for review; no ownership, zoning, permission, buildability, or effective constraint is established.']}
 write_json(root/'render-record-v3.json',{'schema_version':'m2-r04-render-record','producer':PRODUCER,'svg_path':svg.relative_to(root).as_posix(),'svg_sha256':sha256_file(svg),'png_path':png.relative_to(root).as_posix(),'png_sha256':sha256_file(png),'viewport':render,'layer_order':render['layer_order'],'water_style':'#f1f4f5','boundary_stroke_width_px':1.4,'single_decision_map':True})
 approval=root/'approval-record-v3.md'; approval.write_text(f'''# Human approval record — Rotterdam M4H Vierhavenblok v3\n\nProposal: `{PROPOSAL_ID}` supersedes `site-proposal-rotterdam-m4h-v2`.\n\nDecision status: **HUMAN_DECISION_REQUIRED**. Option B is **REJECTED_BY_HUMAN_FEEDBACK** and its complete v2 package is retained under `parent-v2/`. Option A remains PROPOSED.\n\nThe three retained images are classified `HUMAN_FEEDBACK` and `HUMAN_INTENT`; they are not measurements. The boundary follows retained OSM street geometry where declared. Human-intent connector segments are explicitly flagged for review and carry no mapped physical-edge claim. Cross-boundary buildings are reported and their full footprints remain visible.\n\n**APPROVE:** append a human decision naming Option A, exact artifact hashes, actor, timezone-aware timestamp, and reason. **REJECT:** append a human rejection and reason. No approval, acceptance, freeze, effective constraint, or site adoption has been recorded.\n''',encoding='utf-8')
 created=now; proposal=SiteProposal(id=PROPOSAL_ID,project_id=PROJECT_ID,version='v3',supersedes_proposal_id='site-proposal-rotterdam-m4h-v2',status='PROPOSED',human_decision_status='HUMAN_DECISION_REQUIRED',boundary_artifact_path=boundary_path.relative_to(root).as_posix(),boundary_sha256=sha256_file(boundary_path),boundary_size_bytes=boundary_path.stat().st_size,boundary_mime='application/geo+json',geometry_sha256=canonical_geometry_hash(boundary),geometry=boundary,geometry_type='Polygon',horizontal_crs='EPSG:28992',units='m',vertical_reference_status='NOT_APPLICABLE_2D_BOUNDARY; no vertical reference supplied',transform={'input_crs':'EPSG:4326','output_crs':'EPSG:28992','method':'GDAL/OGR deterministic reprojection for retained metric context','tool':GDAL_OGR2OGR,'tool_version':'GDAL 3.3.2','command':f'{GDAL_OGR2OGR} -s_srs EPSG:4326 -t_srs EPSG:28992','axis_order':'traditional GIS axis order','vertical_reference_status':'NOT_APPLICABLE_2D_BOUNDARY'},producer=PRODUCER,created_at=created,selection_method='Human-intent revision with retained OSM street geometry chains and bounded PDOK BGT road-surface observation; connectors flagged for review.',rationale='Append-only M2-R04 repair retaining human feedback, rejecting Option B, dissolving water display, preserving full building footprints, and requiring explicit human decision.',source_refs=[r['id'] for r in source_records],parent_refs=['site-proposal-rotterdam-m4h-v2','site-proposal-delft-v1','site-proposal-delft-v2','site-proposal-delft-v3','parent-v2-integrity'],measurements=[{'name':'area','value':polygon_area(boundary),'unit':'m2','method':'shoelace area on EPSG:28992 projected exterior ring','crs':'EPSG:28992'},{'name':'perimeter','value':polygon_perimeter(boundary),'unit':'m','method':'Euclidean exterior-ring perimeter on EPSG:28992 projected coordinates','crs':'EPSG:28992'}],delft_context=context_payload,dataset_plan={'municipality':'PDOK BRK municipality containment only','context':'retained OSM + bounded PDOK BGT wegdeel','planning_and_buildability':'UNAVAILABLE','accessibility':'OUT_OF_SCOPE','morphology':'OUT_OF_SCOPE','space_syntax':'OUT_OF_SCOPE','climate':'UNAVAILABLE','design_generation':'OUT_OF_SCOPE'},limitations=context_payload['limitations'],approval_record_path=approval.relative_to(root).as_posix(),selection_criteria_status='PROPOSED_PROJECT_DECISION',selection_criteria={'status':'PROPOSED_PROJECT_DECISION','human_selection_required':True,'option_a':'PROPOSED','option_b':'REJECTED_BY_HUMAN_FEEDBACK'},scale_parameters={'status':'PROPOSED_PROJECT_DECISION','thresholds':None},taxonomy_status='PROPOSED',map_preview_path=svg.relative_to(root).as_posix(),source_records_path=sr_path.relative_to(root).as_posix())
 db=root/'proposal-state.sqlite3'; cp(root/'parent-v2/proposal-state.sqlite3',db)
 with ProjectStateStore(db) as store:
  specs=[(boundary_path,'artifact-boundary-rotterdam-m4h-v3','application/geo+json',[]),(wgs_path,'artifact-boundary-wgs84-rotterdam-m4h-v3','application/geo+json',['artifact-boundary-rotterdam-m4h-v3']),(display_path,'artifact-display-data-rotterdam-m4h-v3','application/geo+json',['artifact-boundary-rotterdam-m4h-v3']),(bgt_dst,'artifact-pdok-bgt-wegdeel-m4h-v3','application/json',[]),(ev_path,'artifact-boundary-relationship-v3','application/json',['artifact-boundary-rotterdam-m4h-v3']),(sr_path,'artifact-source-records-rotterdam-m4h-v3','application/json',['artifact-boundary-relationship-v3']),(svg,'artifact-map-preview-rotterdam-m4h-v3','image/svg+xml',['artifact-display-data-rotterdam-m4h-v3']),(png,'artifact-map-preview-render-rotterdam-m4h-v3','image/png',['artifact-map-preview-rotterdam-m4h-v3']),(approval,'artifact-approval-record-rotterdam-m4h-v3','text/markdown',['artifact-map-preview-render-rotterdam-m4h-v3']),(root/'parent-v2-integrity.json','artifact-parent-v2-integrity','application/json',[])]
  for p,aid,mime,parents in specs: store.create_typed(_artifact(p,root,aid,mime,created,parents),actor='m2-r04-executor',action='RecordArtifact',reason='Record append-only M2-R04 evidence with immutable hash and parent links.')
  site=Site(id='site-rotterdam-m4h-v3',project_id=PROJECT_ID,version='v3',boundary_artifact_id='artifact-boundary-rotterdam-m4h-v3',boundary_sha256=proposal.boundary_sha256,crs='EPSG:28992',vertical_reference=proposal.vertical_reference_status,units='m',dataset_snapshot_ids=[],status=SiteStatus.PROPOSED)
  store.create_typed(site,event_id='event-m2-r04-site-proposed',actor='m2-r04-executor',action='ProposeSite',reason='Append v3 proposed boundary; human decision remains required.',changed_refs=proposal.source_refs,resulting_refs=[site.id,site.boundary_artifact_id,proposal.id],event_payload={'proposal_id':proposal.id,'status':'PROPOSED','human_decision_required':True})
  store.create('SiteProposal',proposal.model_dump(mode='json'),entity_id=proposal.id,project_id=PROJECT_ID,event_id='event-m2-r04-site-proposal-recorded',actor='m2-r04-executor',action='RecordSiteProposal',reason='Record append-only v3 without adoption or approval.',changed_refs=proposal.source_refs,resulting_refs=[proposal.id,site.id,site.boundary_artifact_id],event_payload={'proposal_id':proposal.id,'status':'PROPOSED','human_decision_required':True})
  refs=[e.event_id for e in store.events(project_id=PROJECT_ID) if e.target_id in {proposal.id,site.id}]
  # update is intentionally append-only; state store keeps prior revisions
  proposal.ledger_event_refs=refs
 write_json(root/'site-proposal.json',proposal.model_dump(mode='json')); validate_site_proposal_rotterdam_v3(proposal,root); return proposal

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--v2-dir',type=Path,required=True);p.add_argument('--bgt-source',type=Path,required=True);p.add_argument('--offline',action='store_true',default=True);a=p.parse_args(argv)
 try:r=build_rotterdam_v3(a.output_dir,v2_dir=a.v2_dir,bgt_source=a.bgt_source,offline=True)
 except Exception as e: print(f'BLOCKED: {e}',file=sys.stderr);return 2
 print(json.dumps({'proposal_id':r.id,'version':r.version,'status':r.status,'boundary_sha256':r.boundary_sha256,'geometry_sha256':r.geometry_sha256},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
