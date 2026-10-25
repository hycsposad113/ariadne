"""Fail-closed validators for the M2-R04 Rotterdam M4H v3 proposal."""
from __future__ import annotations
import hashlib, json, math, struct
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from .site_proposal import SiteProposal, sha256_file
from .geometry import validate_geometry, polygon_area, polygon_perimeter, GeometryValidationError

class RotterdamSiteProposalV3ValidationError(ValueError): pass

def _safe(root: Path, value: str) -> Path:
    p=(root / PurePosixPath(value.replace('\\','/'))).resolve()
    if root.resolve() not in p.parents and p != root.resolve(): raise RotterdamSiteProposalV3ValidationError('path escapes package')
    return p

def _hash(path: Path) -> str: return sha256_file(path)
def _load(path: Path) -> Any:
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e: raise RotterdamSiteProposalV3ValidationError(f'invalid JSON: {path.name}') from e

def _geom(payload: Mapping[str,Any]) -> Mapping[str,Any]:
    if payload.get('type')=='Feature': return payload.get('geometry') or {}
    if payload.get('type') in {'Polygon','MultiPolygon'}: return payload
    if payload.get('type')=='FeatureCollection' and len(payload.get('features',[]))==1: return payload['features'][0].get('geometry') or {}
    raise RotterdamSiteProposalV3ValidationError('boundary artifact has no polygon geometry')

def _feature_geoms(path: Path):
    p=_load(path); feats=p.get('features',[]) if isinstance(p,Mapping) else []
    return [f for f in feats if isinstance(f,Mapping) and isinstance(f.get('geometry'),Mapping)]

def _require_hash(root: Path, rel: str, expected: str|None=None):
    p=_safe(root,rel)
    if not p.is_file(): raise RotterdamSiteProposalV3ValidationError(f'missing artifact: {rel}')
    actual=_hash(p)
    if expected and actual != expected: raise RotterdamSiteProposalV3ValidationError(f'hash mismatch: {rel}')
    return p,actual

def _validate_human_feedback(root: Path, context: Mapping[str,Any]):
    rel=context.get('human_feedback_evidence_path');
    if not isinstance(rel,str): raise RotterdamSiteProposalV3ValidationError('human feedback evidence path required')
    payload=_load(_safe(root,rel)); entries=payload.get('feedback',[])
    if len(entries)!=3: raise RotterdamSiteProposalV3ValidationError('exactly three retained feedback images required')
    for item in entries:
        if item.get('classification') != ['HUMAN_FEEDBACK','HUMAN_INTENT']:
            raise RotterdamSiteProposalV3ValidationError('feedback image classification is not HUMAN_FEEDBACK/HUMAN_INTENT')
        if item.get('used_as_measurement') is not False: raise RotterdamSiteProposalV3ValidationError('human feedback cannot be a measurement')
        p,h=_require_hash(root,item['retained_path'],item.get('sha256'))
        if p.stat().st_size != item.get('size_bytes'): raise RotterdamSiteProposalV3ValidationError('feedback size mismatch')
    return payload

def _validate_parent(root: Path, context: Mapping[str,Any]):
    rel=context.get('parent_integrity_path','parent-v2-integrity.json'); manifest=_load(_safe(root,rel))
    if manifest.get('parent_id')!='site-proposal-rotterdam-m4h-v2': raise RotterdamSiteProposalV3ValidationError('v2 parent manifest id missing')
    for item in manifest.get('files',[]):
        p=_safe(root,item['retained_path'])
        if not p.is_file() or p.stat().st_size!=item['size_bytes'] or _hash(p)!=item['sha256']:
            raise RotterdamSiteProposalV3ValidationError(f'parent byte integrity failed: {item.get("relative_path")}')
    return manifest

def _ring(geometry):
    if geometry.get('type')!='Polygon' or len(geometry.get('coordinates',[]))!=1: raise RotterdamSiteProposalV3ValidationError('v3 boundary must be one Polygon ring')
    ring=[(float(x),float(y)) for x,y in geometry['coordinates'][0]]
    if len(ring)<4 or ring[0]!=ring[-1]: raise RotterdamSiteProposalV3ValidationError('boundary ring must be closed')
    try: validate_geometry(geometry)
    except GeometryValidationError as e: raise RotterdamSiteProposalV3ValidationError(str(e)) from e
    return ring

def _segment_distance(point, a, b):
    dx=b[0]-a[0];dy=b[1]-a[1]; den=dx*dx+dy*dy
    if den==0:return math.dist(point,a)
    t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/den))
    return math.dist(point,(a[0]+t*dx,a[1]+t*dy))

def _validate_boundary_evidence(root: Path, context: Mapping[str,Any], ring):
    rel=context.get('boundary_relationship_evidence_path');
    if not isinstance(rel,str): raise RotterdamSiteProposalV3ValidationError('boundary relationship evidence required')
    p=_safe(root,rel); payload=_load(p)
    if payload.get('schema_version')!='m2-r04-boundary-relationship-evidence': raise RotterdamSiteProposalV3ValidationError('boundary evidence schema invalid')
    edges=payload.get('edges',[])
    if len(edges)!=len(ring)-1: raise RotterdamSiteProposalV3ValidationError('one evidence record required for every boundary segment')
    context_rel='context-display-epsg28992-v2.geojson'
    context_payload=_load(_safe(root,context_rel))
    source_features={str(f.get('id')): f for f in context_payload.get('features',[]) if isinstance(f,Mapping) and f.get('id') is not None}
    for i,e in enumerate(edges):
        if e.get('edge_index')!=i or e.get('claim_status') not in {'SOURCE_GEOMETRY_SEGMENT','HUMAN_INTENT_ALIGNMENT_REVIEW'}:
            raise RotterdamSiteProposalV3ValidationError('unsupported boundary edge claim')
        if e.get('source_feature_id') is None or e.get('source_segment') is None: raise RotterdamSiteProposalV3ValidationError('source feature/segment missing')
        if e.get('claim_status')=='HUMAN_INTENT_ALIGNMENT_REVIEW':
            if e.get('physical_edge_claim') is not False: raise RotterdamSiteProposalV3ValidationError('human intent edge cannot claim physical edge')
            continue
        feature=source_features.get(str(e['source_feature_id']))
        seg=e.get('source_segment')
        if feature is None or not isinstance(seg,list) or len(seg)!=2 or any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in seg):
            raise RotterdamSiteProposalV3ValidationError('source geometry segment is missing or malformed')
        coords=(feature.get('geometry') or {}).get('coordinates',[])
        if (feature.get('geometry') or {}).get('type')!='LineString' or seg[1]!=seg[0]+1 or seg[1]>=len(coords):
            raise RotterdamSiteProposalV3ValidationError('source geometry segment index is outside retained line')
        src_a=(float(coords[seg[0]][0]),float(coords[seg[0]][1])); src_b=(float(coords[seg[1]][0]),float(coords[seg[1]][1]))
        a=tuple(float(v) for v in e.get('start_epsg28992',[])); b=tuple(float(v) for v in e.get('end_epsg28992',[]))
        direct=math.dist(a,src_a)+math.dist(b,src_b); reverse=math.dist(a,src_b)+math.dist(b,src_a)
        if min(direct,reverse)>0.05: raise RotterdamSiteProposalV3ValidationError('boundary segment is not the retained source segment')
        if e.get('measured_distance_m') is None or float(e['measured_distance_m'])>0.05: raise RotterdamSiteProposalV3ValidationError('source segment distance exceeds tolerance')
    return payload

def _validate_display(root: Path, context: Mapping[str,Any]):
    rel=context.get('display_data_path'); p=_safe(root,rel); payload=_load(p)
    order=['background/land','water','public/open','context buildings','site buildings','roads/walk paths','rail','labels/markers','boundary']
    if payload.get('classification_priority')!=order: raise RotterdamSiteProposalV3ValidationError('display priority mismatch')
    layers=[(f.get('properties') or {}).get('display_layer') for f in payload.get('features',[]) if isinstance(f,Mapping)]
    allowed=set(order); 
    if any(v not in allowed for v in layers): raise RotterdamSiteProposalV3ValidationError('unknown display layer')
    # exactly one major class per feature
    if len(layers)!=len(payload.get('features',[])): raise RotterdamSiteProposalV3ValidationError('exclusive display classification failed')
    water=[f for f in payload.get('features',[]) if (f.get('properties') or {}).get('display_layer')=='water']
    if len(water)>1: raise RotterdamSiteProposalV3ValidationError('water polygons were not dissolved')
    return payload

def _validate_svg(root: Path, context: Mapping[str,Any]):
    p=_safe(root,context['map_svg_path']); text=p.read_text(encoding='utf-8')
    ids=[]
    import re
    ids=re.findall(r'<g id="([^"]+)"',text)
    required=['layer-background','layer-water','layer-public-space','layer-context-buildings','layer-site-buildings','layer-roads','layer-rail','layer-markers','layer-boundary']
    if [x for x in ids if x in required] != required: raise RotterdamSiteProposalV3ValidationError('SVG layer order mismatch')
    if '#f1f4f5' not in text or '#d62728' not in text or 'stroke-width="1.4"' not in text: raise RotterdamSiteProposalV3ValidationError('required map styling missing')
    bstart=text.find('<g id="layer-boundary"'); bend=text.find('</g>',bstart)
    if bstart < 0 or bend < 0 or 'fill="none"' not in text[bstart:bend]: raise RotterdamSiteProposalV3ValidationError('boundary fill is too strong')
    if 'REJECTED_BY_HUMAN_FEEDBACK' not in text or 'Cross-boundary buildings' not in text: raise RotterdamSiteProposalV3ValidationError('decision/cross-boundary legend missing')
    return p

def _validate_png(root: Path, context: Mapping[str,Any]):
    p=_safe(root,context['rendered_png_path']); raw=p.read_bytes()
    if _hash(p)!=context['rendered_png_sha256'] or raw[:8]!=b'\x89PNG\r\n\x1a\n': raise RotterdamSiteProposalV3ValidationError('PNG hash/signature invalid')
    if len(raw)<24 or struct.unpack('>II',raw[16:24]) != (1240,850): raise RotterdamSiteProposalV3ValidationError('PNG must be 1240x850')
    if not any(raw[i:i+4]==b'IDAT' for i in range(len(raw)-4)): raise RotterdamSiteProposalV3ValidationError('PNG has no image data')
    return p

def _validate_state(root: Path, proposal: SiteProposal):
    import sqlite3
    p=_safe(root,proposal.delft_context['state_path']); con=sqlite3.connect(p)
    try:
        rows=con.execute("select entity_type, payload_json from state_versions where entity_type in ('Project','Site','SiteProposal')").fetchall()
        if not rows: raise RotterdamSiteProposalV3ValidationError('state has no records')
        for typ,payload in rows:
            try:d=json.loads(payload)
            except:continue
            if typ=='Project' and d.get('id')==proposal.project_id and d.get('site_id') is not None: raise RotterdamSiteProposalV3ValidationError('Project.site_id must remain null')
            if typ=='Site' and d.get('version')=='v3' and str(d.get('status','')).upper() not in {'PROPOSED'}: raise RotterdamSiteProposalV3ValidationError('v3 site is not proposed')
        bad=con.execute("select action from ledger_events where lower(action) like '%approve%' or lower(action) like '%accept%' or lower(action) like '%freeze%'").fetchall()
        if bad: raise RotterdamSiteProposalV3ValidationError('approval/freeze event present')
    finally:con.close()

def validate_site_proposal_rotterdam_v3(proposal: SiteProposal|Mapping[str,Any], package_root: str|Path, *, v2_dir: str|Path|None=None) -> SiteProposal:
    candidate=proposal if isinstance(proposal,SiteProposal) else SiteProposal.model_validate(proposal)
    if candidate.id!='site-proposal-rotterdam-m4h-v3' or candidate.version!='v3' or candidate.supersedes_proposal_id!='site-proposal-rotterdam-m4h-v2': raise RotterdamSiteProposalV3ValidationError('wrong v3 identity/lineage')
    root=Path(package_root).resolve(); context=candidate.delft_context
    _validate_parent(root,context); _validate_human_feedback(root,context)
    raw_rel=context.get('bgt_source_path'); rawp,h=_require_hash(root,raw_rel,context.get('bgt_source_sha256'))
    raw=_load(rawp)
    if len(raw.get('features',[]))!=context.get('bgt_feature_count'): raise RotterdamSiteProposalV3ValidationError('BGT feature count mismatch')
    boundaryp=_safe(root,candidate.boundary_artifact_path)
    if _hash(boundaryp)!=candidate.boundary_sha256 or boundaryp.stat().st_size!=candidate.boundary_size_bytes: raise RotterdamSiteProposalV3ValidationError('boundary byte mismatch')
    geom=_geom(_load(boundaryp)); ring=_ring(geom)
    if geom!=candidate.geometry or candidate.geometry_sha256 != __import__('urban_design.geometry',fromlist=['canonical_geometry_hash']).canonical_geometry_hash(geom): raise RotterdamSiteProposalV3ValidationError('boundary geometry mismatch')
    _validate_boundary_evidence(root,context,ring); _validate_display(root,context); _validate_svg(root,context); _validate_png(root,context)
    # no clipping: every context building remains a full footprint; statuses are explicit
    cross=context.get('cross_boundary_buildings',[])
    if not isinstance(cross,list): raise RotterdamSiteProposalV3ValidationError('cross-boundary report missing')
    disp=_load(_safe(root,context['display_data_path']))
    for f in disp.get('features',[]):
        if (f.get('properties') or {}).get('display_layer') in {'site buildings','context buildings'} and (f.get('properties') or {}).get('geometry_clipped'): raise RotterdamSiteProposalV3ValidationError('building geometry was clipped')
    _validate_state(root,candidate)
    return candidate

__all__=['RotterdamSiteProposalV3ValidationError','validate_site_proposal_rotterdam_v3']
