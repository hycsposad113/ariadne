"""Receipt-verified, explanatory PST segment projection in Dutch RD metres."""
from __future__ import annotations
import hashlib, os
import json
from bisect import bisect_right
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, JsonValue, FiniteFloat, model_validator
from shapely.geometry import LineString, Point, mapping, shape
from .scenario_syntax import WELD_TOLERANCE_M
from .syntax_context_api import calculate_quantile_breaks

class Receipt(BaseModel):
    model_config = ConfigDict(extra='ignore')
    path: str
    sha256: str

class SegmentProperties(BaseModel):
    model_config = ConfigDict(extra='allow')
    segment_id: str
    before_nain: FiniteFloat | None
    after_nain: FiniteFloat | None
    delta_nain: FiniteFloat | None
    before_nach: FiniteFloat | None
    after_nach: FiniteFloat | None
    delta_nach: FiniteFloat | None
    is_new_street: bool
    inside_site: bool
    comparison_status: Literal['MATCHED_GEOMETRY','NEW_OR_CHANGED_GEOMETRY','REMOVED','ORIGINAL_SEGMENT']
    render_phase: Literal['before','after']

    @model_validator(mode='after')
    def comparable_values(self):
        for metric in ('nain','nach'):
            before=getattr(self,'before_'+metric); after=getattr(self,'after_'+metric); delta=getattr(self,'delta_'+metric)
            if self.comparison_status=='MATCHED_GEOMETRY':
                if before is None or after is None or delta is None or abs(delta-(after-before))>1e-9:
                    raise ValueError('BLOCKED: incomparable delta')
            elif delta is not None:
                raise ValueError('BLOCKED: non-matched geometry has delta')
        if self.render_phase=='before' and self.comparison_status!='ORIGINAL_SEGMENT':
            raise ValueError('BLOCKED: original rendering lineage mismatch')
        return self

class SegmentFeature(BaseModel):
    type: Literal['Feature']
    id: str | None = None
    geometry: dict[str, JsonValue]
    properties: SegmentProperties

    @model_validator(mode='after')
    def valid_geometry(self):
        geometry=shape(self.geometry)
        if geometry.geom_type not in ('LineString','MultiLineString') or geometry.is_empty or not geometry.is_valid or geometry.length<=0:
            raise ValueError('BLOCKED: invalid segment geometry')
        return self

class SegmentCollection(BaseModel):
    type: Literal['FeatureCollection']
    crs: dict[str, JsonValue]
    legend_breaks: dict[str,list[FiniteFloat]]
    features: list[SegmentFeature]
    metadata: dict[str, JsonValue]
    intent_assessment: dict[str, JsonValue]
    net1_assessment: dict[str, JsonValue] | None = None
    net2_assessment: dict[str, JsonValue] | None = None

    @model_validator(mode='after')
    def validate_collection(self):
        for metric in ('nain','nach'):
            breaks=self.legend_breaks.get(metric,[])
            if len(breaks)!=6 or breaks!=sorted(breaks):
                raise ValueError('BLOCKED: invalid legend breaks')
        ids=[f.properties.segment_id for f in self.features]
        if len(ids)!=len(set(ids)): raise ValueError('BLOCKED: duplicate segment IDs')
        return self

def receipt(path: Path) -> dict[str,str]:
    return {'path':str(path.resolve()),'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()}

REPO_ROOT=Path(__file__).resolve().parents[2]
_RELOCATABLE=('artifacts','src','scripts')

def _candidates(path: Path) -> list[Path]:
    # Receipts record absolute paths from the machine/checkout that produced them. Prefer the
    # same repository-relative file in this checkout, then the local urban-design data root,
    # then the recorded path; the sha256 check in verify() decides which one is accepted.
    out=[]
    parts=path.parts
    for i,part in enumerate(parts):
        if part in _RELOCATABLE and not out:
            out.append(REPO_ROOT.joinpath(*parts[i:]))
        if part=='urban-design-data':
            data_root=Path(os.environ.get('URBAN_DESIGN_DATA_ROOT','~/.local/share/urban-design-data')).expanduser()
            out.append(data_root.joinpath(*parts[i+1:]))
    out.append(path)
    return out

def verify(record: dict[str,Any]) -> Path:
    r=Receipt.model_validate(record); expected=r.sha256.removeprefix('sha256:')
    for p in _candidates(Path(r.path)):
        if p.is_file() and receipt(p)['sha256'].removeprefix('sha256:')==expected:
            return p
    raise ValueError('BLOCKED: missing or mismatched receipt '+r.path)

def lineage(compact: dict[str,Any]) -> tuple[dict,dict,dict]:
    if compact['status']!='COMPUTED': raise ValueError('BLOCKED: syntax unavailable')
    full=json.loads(verify(compact['complete_intermediate']).read_text())
    plan=json.loads(verify(compact['source_receipts']['plan']).read_text())
    network=json.loads(verify(compact['source_receipts']['extract']['manifest']['outputs']['network']).read_text())
    verify(compact['retained_road_receipts'])
    if plan['crs']!='EPSG:28992' or full['legend_breaks']!=compact['legend_breaks']:
        raise ValueError('BLOCKED: CRS or legend lineage mismatch')
    if full.get('status')!='COMPUTED' or full.get('mode')!=compact.get('mode') or full.get('radius_m')!=compact.get('radius_m') or plan.get('fabric_id') not in (compact.get('fabric_id'),'fabric.'+compact['fabric_id']):
        raise ValueError('BLOCKED: full/compact/plan identity mismatch')
    return full,plan,network

def authored(source: str, roads: dict) -> str | None:
    if not source.startswith('proposal:'): return None
    value=source.removeprefix('proposal:')
    hits=[k for k in roads if value in (k,k+'_a',k+'_b') or value.startswith(k+':part:') or value.startswith(k+':uncovered:')]
    return max(hits,key=len) if hits else None

def display_breaks(full: dict) -> dict:
    # Site uses quintiles over the visible context distance. Fix this original
    # population for both views so proposal changes never recolor the baseline.
    baseline=[r for r in full['before']['segments'] if r['distance_to_site_m']<=1000]
    return {metric:calculate_quantile_breaks([r[metric] for r in baseline]) for metric in ('nain','nach')}

def build(compact_path: Path) -> tuple[dict,dict]:
    compact=json.loads(compact_path.read_text());full,plan,network=lineage(compact)
    site=shape(plan['site']);scope=site.buffer(1000)
    roads={str(f['id']):f for f in plan['roads']}
    sources={str(f['id']):f for f in network['features']}
    values={metric:sorted(r[metric] for r in full['after']['segments']) for metric in ('nain','nach')}
    groups={};features=[]
    for row in full['diff']:
        original=LineString(row['coordinates']); clipped=original.intersection(scope)
        if clipped.is_empty or clipped.length==0: continue
        source=row['source_line_id'];road=authored(source,roads)
        source_id=source.removeprefix('proposal:existing:').split(':part:')[0].split(':uncovered:')[0]
        existing_source=roads[road]['properties'].get('source_id') if road else None
        is_new=road is not None and not existing_source and not roads[road]['properties'].get('role','').startswith('retained_')
        if existing_source: source_id=str(existing_source)
        src=sources.get(source_id)
        if not road and src is not None and any(shape(src['geometry']).distance(Point(c))>WELD_TOLERANCE_M+.002 for c in original.coords):
            raise ValueError('BLOCKED: source geometry support mismatch '+source)
        props={'render_phase':'after','segment_id':row['id'],'source_line_id':source,'source_id':(source_id if src else road),'road_id':road,'name':(src or {}).get('properties',{}).get('name') or None,'road_role':roads[road]['properties'].get('role') if road else None,'is_new_street':is_new,'inside_site':row['inside_site'],'comparison_status':row['comparison_status'],'boundary_effect_risk':row['boundary_effect_risk']}
        for metric in ('nain','nach'):
            for phase in ('before','after','delta'):
                props[f'{phase}_{metric}']=(row.get(phase) or {}).get(metric)
        features.append({'type':'Feature','geometry':mapping(clipped.simplify(1,preserve_topology=True)),'properties':props})
        length=original.intersection(site).length
        if road and row.get('after') and length>0:
            g=groups.setdefault(road,{'road_id':road,'is_new_street':is_new,'role':props['road_role'],'length_m':0.,'weighted_nain':0.,'weighted_nach':0.})
            g['length_m']+=length;g['weighted_nain']+=length*row['after']['nain'];g['weighted_nach']+=length*row['after']['nach']
    # The diff's before values can be weighted across multiple original pieces.
    # Keep exact PST baseline segments separately for a faithful original map.
    for row in full['before']['segments']:
        clipped = LineString(row['coordinates']).intersection(scope)
        if clipped.is_empty or clipped.length == 0: continue
        source_id = row['source_line_id'].split(':part:')[0].split(':uncovered:')[0]
        src = sources.get(source_id)
        props = {'render_phase':'before','segment_id':'before:'+row['id'],
                 'source_line_id':row['source_line_id'],
                 'source_id':source_id,'name':(src or {}).get('properties',{}).get('name') or None,
                 'is_new_street':False,'inside_site':row['inside_site'],
                 'boundary_effect_risk':row['boundary_effect_risk'],
                 'comparison_status':'ORIGINAL_SEGMENT'}
        for metric in ('nain','nach'):
            props['before_'+metric]=row[metric];props['after_'+metric]=None;props['delta_'+metric]=None
        features.append({'type':'Feature',
                         'geometry':mapping(clipped.simplify(1,preserve_topology=True)),'properties':props})
    ranked=[]
    for g in groups.values():
        g['nain']=g.pop('weighted_nain')/g['length_m'];g['nach']=g.pop('weighted_nach')/g['length_m'];
        for metric in ('nain','nach'): g[metric+'_percentile']=100*bisect_right(values[metric],g[metric])/len(values[metric])
        g['after_context_percentile']=g['nain_percentile']
        g['status']='meets' if g['after_context_percentile']>=80 else 'partial' if g['after_context_percentile']>=60 else 'not met'
        g['status_zh']={'meets':'符合','partial':'部分符合','not met':'不符合'}[g['status']];ranked.append(g)
    ranked.sort(key=lambda g:(-g['nain'],g['road_id']))
    new_ranked=[r for r in ranked if r['is_new_street']]
    changed=[f['properties'] for f in features if not f['properties']['is_new_street'] and f['properties']['delta_nain'] is not None]
    changed.sort(key=lambda p:(p['delta_nain'],p['segment_id']))
    assessments=[]
    for role,zh in [('primary_street','主要街道／港灣大道'),('waterfront_path','水岸路徑'),('waterfront_detour','水岸繞行')]:
        rows=[r for r in ranked if r['role']==role]
        score=sum(r['after_context_percentile']*r['length_m'] for r in rows)/sum(r['length_m'] for r in rows) if rows else None
        assessments.append({'intent_en':role,'intent_zh':zh,'percentile':score,'status':('meets' if score>=80 else 'partial' if score>=60 else 'not met') if score is not None else 'unavailable','roads':rows})
    # A merge receipt junction plus surviving same-mode after support proves
    # direct graph contact. Mere proximity to an authored line is insufficient.
    junctions=[Point(c) for c in full['merge']['connection_points']]
    unlinks=[Point(c) for c in full['merge'].get('derived_unlinks',[])]
    for target in ('Keileweg','Dakpark'):
        named={str(s['id']) for s in sources.values() if target.casefold() in str(s['properties'].get('name','')).casefold()}
        target_lines=[LineString(r['coordinates']) for r in full['after']['segments']
                      if r['source_line_id'].removeprefix('proposal:existing:').split(':part:')[0].split(':uncovered:')[0] in named]
        joins=set()
        for row in full['after']['segments']:
            road=authored(row['source_line_id'],roads)
            if not road or road not in groups or not groups[road]['is_new_street']: continue
            line=LineString(row['coordinates'])
            if any(line.distance(point)<=.001 and not any(point.distance(u)<=.001 for u in unlinks)
                   and any(other.distance(point)<=.001 for other in target_lines) for point in junctions): joins.add(road)
        rows=[r for r in ranked if r['road_id'] in joins]
        score=sum(r['nain_percentile']*r['length_m'] for r in rows)/sum(r['length_m'] for r in rows) if rows else None
        status=('meets' if score>=80 else 'partial' if score>=60 else 'not met') if score is not None else ('not met' if target_lines else 'unavailable')
        reason=('Direct same-mode junction verified in merge receipt and surviving after segments.' if rows else
                'No direct proposal junction to this named target in the evaluated mode.' if target_lines else
                'Named target has no surviving segment in the evaluated mode; intent cannot be assessed.')
        assessments.append({'intent_en':'connection '+target,'intent_zh':'銜接 '+target,
                            'percentile':score,'status':status,'direct_join_road_ids':sorted(joins),
                            'roads':rows,'named_source_count':len(named),'reason':reason})
    result={'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:28992'}},'legend_breaks':display_breaks(full),'features':features,'metadata':{'schema_version':'fabric-syntax-segments-v2','legend_basis':'Original segments within 1000 m; Site quintile algorithm; fixed across original and proposal','analysis_legend_breaks':full['legend_breaks'],'fabric_id':compact['fabric_id'],'mode':compact['mode'],'scope':'Site plus 1000 m buffer; clipped then simplified','buffer_m':1000,'radius_m':full['radius_m'],'extract_buffer_m':full['extract_buffer_m'],'reliable_within_m':max(0,full['extract_buffer_m']-full['radius_m']),'simplify_tolerance_m':1,'full_diff_count':len(full['diff']),'original_segment_count':sum(f['properties']['render_phase']=='before' for f in features),'exported_feature_count':len(features),'formal_result_eligible':False,'source_receipts':{'compact':receipt(compact_path),'full':compact['complete_intermediate'],'plan':compact['source_receipts']['plan'],'network':compact['source_receipts']['extract']['manifest']['outputs']['network'],'retained_roads':compact['retained_road_receipts']}}}
    report={'fabric_id':compact['fabric_id'],'mode':compact['mode'],'method':'Site-clipped length-weighted NAIN/NACH per authored feature.id; percentile empirical CDF in full after context. Illustrative project descriptive heuristic: >=80 meets, >=60 partial, <60 not met; not an approved design constraint or movement prediction. Null deltas retained for non-matched geometry. Authored retained_* roles or roads with OSM source_id are existing/modified streets, excluded from new-street rankings and direct connector intent checks.','intents':assessments,'all_authored_roads':ranked,'all_new_roads':new_ranked,'top5_new':new_ranked[:5],'bottom5_new':list(reversed(new_ranked[-5:])),'existing_delta_positive5':list(reversed([r for r in changed if r['delta_nain']>1e-12][-5:])),'existing_delta_negative5':[r for r in changed if r['delta_nain'] < -1e-12][:5]}
    result["intent_assessment"]=report
    return result,report

def load_verified(path: Path) -> dict:
    record=json.loads(path.with_suffix('.receipt.json').read_text())
    # Commander 2026-10-13: receipts carry the authoring worktree's absolute path; verify the local
    # file by name and SHA-256 so the same committed export validates in any checkout.
    if Path(record['export']['path']).name!=path.name: raise ValueError('BLOCKED: export path mismatch')
    verify({**record['export'],'path':str(path)})
    result=json.loads(path.read_text())
    for r in result['metadata']['source_receipts'].values(): verify(r)
    compact=json.loads(Path(result['metadata']['source_receipts']['compact']['path']).read_text());full,_,_=lineage(compact)
    if display_breaks(full)!=result['legend_breaks'] or compact['legend_breaks']!=result['metadata']['analysis_legend_breaks']: raise ValueError('BLOCKED: fixed legend drift')
    if result['metadata']['fabric_id']!=compact['fabric_id'] or result['metadata']['mode']!=compact['mode']:
        raise ValueError('BLOCKED: export identity drift')
    if path.stat().st_size>=5_000_000: raise ValueError('BLOCKED: export size exceeds 5 MB')
    for r in (result.get("net2_assessment") or {}).get("baselines", {}).get("waterfront_meets", {}).get("source_receipts", {}).values(): verify(r)
    SegmentCollection.model_validate(result)
    return result
