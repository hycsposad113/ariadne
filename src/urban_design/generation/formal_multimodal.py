"""J11 copy-only DRAFT orchestration. V6 remains available for historical replay."""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from urban_design.approved_generation import _load_approved_inputs
from urban_design.generation_context import resolve_readiness, freeze_context, FreezeRequest
from urban_design.scenario_syntax import compare_syntax, verified_extract, digest, MergeParameters
from urban_design.store import ProjectStateStore
from urban_design.far import FarSiteContext, resolve_far_denominator
from . import multimodal_network as net
from .network_cleanup import cleanup_network
from .block_program import geometry_value
from .contracts import BlockProgramArtifact, FrozenRef, MethodProvenance, MethodSourceKind, ProgramBlock, FixtureRetainedBuilding
from .formal_adapter import adapt_frozen_context, retained_gfa_bounds
from .formal_pipeline import approved_parameters
from .formal_placement import place_program
from .hashing import generation_context_digest, semantic_digest
from .massing_adapter import build_massing
from .skeleton import _principal_angle

VERSION=net.VERSION
CONTEXT_ROOT=Path.home()/'.local/share/urban-design-data/syntax-context/run-20261001T105231Z'


def unlink_points(document):
    if not isinstance(document,list) or any(not isinstance(p,list) or len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in p) for p in document):
        raise ValueError('verified extraction unlinks must be a finite list of XY pairs')
    return tuple(tuple(p) for p in document)


def checked_copy(path):
    p=Path(path).resolve()
    if not p.is_relative_to(Path('/private/tmp')):
        raise ValueError('DRAFT generation requires a /private/tmp database copy')
    if not p.is_file():raise ValueError('database copy missing')
    return p


def utc():
    return subprocess.check_output(['date','-u','+%Y-%m-%dT%H:%M:%SZ'],text=True).strip()


def load_sources(site):
    external={};contexts={};receipts={};features={};mode_lookup={}
    for mode in ('pedestrian','bicycle','motor_vehicle'):
        docs,receipt=verified_extract(mode)
        external[mode]=docs['network']['features']
        receipts[mode]=receipt
        if mode!='motor_vehicle':
            p=CONTEXT_ROOT/f'syntax_context_{mode}.json';raw=p.read_bytes();doc=json.loads(raw)
            if doc['network_mode']!=mode or doc['radius_m']!=(800 if mode=='pedestrian' else 2000):raise ValueError('context mode/radius mismatch')
            if doc['inputs']['network']['sha256'].removeprefix('sha256:')!=receipt['manifest']['outputs']['network']['sha256'].removeprefix('sha256:'):raise ValueError('context network lineage mismatch')
            contexts[mode]=doc;receipts[mode]['syntax_context']={'path':str(p),'sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),'attribution':doc['attribution'],'limitations':doc['limitations']}
        for f in external[mode]:
            g=shape(f['geometry'])
            if g.intersection(site).length<=1e-6:continue
            if f['id'] in features and not shape(features[f['id']]['geometry']).equals_exact(g,1e-6):
                raise ValueError('source geometry differs between mode extracts: '+f['id'])
            features[f['id']]=f;mode_lookup.setdefault(f['id'],[]).append(mode)
    return external,contexts,receipts,list(features.values()),mode_lookup


def retained_roads(features,dispositions,mode_lookup,rules):
    by_id={d.source_id:d for d in dispositions};roads=[]
    for f in features:
        d=by_id[f['id']]
        if d.disposition=='removed':continue
        modes=mode_lookup[f['id']]
        if d.disposition=='transformed':modes=['pedestrian','bicycle']
        car='motor_vehicle' in modes
        roads.append(net.NetworkRoad(id='existing:'+f['id'],coordinates=f['geometry']['coordinates'],width_m=rules.retained_car_width_m if car else rules.retained_cycle_width_m,
            modes=modes,origin=d.disposition,source_road_ids=[f['id']],semantics_provenance='MODE_EXTRACT_SOURCE; width ASSUMED_COMMANDER DRAFT',
            layer=int(f['properties'].get('layer') or 0),hierarchy='retained',width_class='city' if car else 'cycle',rule_card_ids=[d.rule_card_id],
            pedestrian_only_reason='Existing source-mode access retained; bicycle excluded by source extraction' if modes==['pedestrian'] else None))
    return roads


def shared_existing_overlay(fixed,site,id,rules):
    overlays=[]
    for f in fixed:
        if 'bicycle' in f.modes and 'pedestrian' not in f.modes:
            for i,line in enumerate(net._parts(LineString(f.coordinates).intersection(site))):
                r=net._road(line,id+':shared-existing:'+f.id+f':{i}',rules,'internal')
                # The bicycle half of this physical shared corridor is already
                # retained. Insert only its proposed pedestrian permission;
                # duplicate cycling lines are rejected by PST source coverage.
                overlays.append(r.model_copy(update={'modes':['pedestrian'],
                    'pedestrian_only_reason':'DRAFT shared corridor on retained cycling alignment; bicycle geometry/mode already retained separately',
                    'source_road_ids':list(f.source_road_ids)}))
    return overlays


def segment_planned_roads(roads):
    """Straight source segments preserve planned paths and immutable retained roads."""
    result=[]
    for r in roads:
        if r.origin=='retained' or len(r.coordinates)==2:
            result.append(r);continue
        for i,(a,b) in enumerate(zip(r.coordinates,r.coordinates[1:])):
            result.append(r.model_copy(update={'id':r.id+f'-segment-{i}','coordinates':[a,b]}))
    return result


class DistanceIndex:
    """Exact max-of-component minimum distance, equivalent to union distance."""
    def __init__(self,geometries):
        self.tree=STRtree(geometries)
    def __call__(self,geometry):
        if not len(self.tree.geometries):return None
        distances=[]
        for part in (geometry.geoms if geometry.geom_type=='MultiPolygon' else (geometry,)):
            _,measured=self.tree.query_nearest(part,return_distance=True)
            distances.append(float(min(measured)))
        return max(distances)


def block_artifact(context,parts,id,roads,created_at):
    h=generation_context_digest(context)
    return BlockProgramArtifact(artifact_id=id+'-blocks',context_hash=h,input_refs=context.source_refs,seed=context.seed,
        algorithm_version=VERSION,method=MethodProvenance(method_id=VERSION,version='7',description='All retained and planned road surfaces subtracted before placement',source_kind=MethodSourceKind.REGISTERED_DETERMINISTIC_METHOD),
        assumptions=context.assumptions,created_at=created_at,
        parent_skeleton_ref=FrozenRef(id=id+'-network',sha256=digest([r.model_dump() for r in roads]),kind='MultimodalNetwork'),
        blocks=tuple(ProgramBlock(id=id+f'-block-{i}',geometry=geometry_value(g)) for i,g in enumerate(parts)),zones=(),frontages=(),program_allocations=(),unallocated_areas=())


def place_candidate(context,manifest,inputs,roads,parts,id,angle,rules,created_at):
    parameters=approved_parameters(inputs)
    ctx=context.model_copy(update={'method_parameters':{**context.method_parameters,**parameters}})
    retained={d.feature_id:g for d,g,_ in inputs.retained_buildings}
    rb=tuple(FixtureRetainedBuilding(source_ref=FrozenRef(id=k,sha256=semantic_digest(g),kind='RETAINED_FOOTPRINT'),geometry=geometry_value(g)) for k,g in retained.items())
    bounds=retained_gfa_bounds(manifest)
    if bounds['status']=='UNAVAILABLE':raise ValueError('retained GFA unavailable')
    far_constraint=next(c for c in inputs.constraint_set.constraints if c.name=='far_upper_limit' and c.scope=='whole_site')
    denominator,label=resolve_far_denominator(far_constraint,FarSiteContext(inputs.design_area,inputs.water_geometry))
    artifact=block_artifact(ctx,parts,id,roads,created_at)
    # Keep the existing complete-envelope placer; restrict candidates before
    # selection to both bike proximity and service/fire proximity. No new roads.
    edges=[SimpleNamespace(geometry=SimpleNamespace(model_dump=lambda r=r:mapping(LineString(r.coordinates))),width_m=r.width_m) for r in roads]
    bike=unary_union([LineString(r.coordinates) for r in roads if 'bicycle' in r.modes])
    service=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads if 'motor_vehicle' in r.modes])
    bike_index=DistanceIndex([LineString(r.coordinates) for r in roads if 'bicycle' in r.modes])
    service_index=DistanceIndex([LineString(r.coordinates).buffer(r.width_m/2) for r in roads if 'motor_vehicle' in r.modes])
    road_index=DistanceIndex([LineString(r.coordinates).buffer(r.width_m/2) for r in roads])
    def allowed(profile,cell,z,d):
        bd=bike_index(profile);fd=service_index(profile)
        return bd is not None and fd is not None and bd<=rules.bicycle_distance_m and fd<=40
    target=max(0,min(.76,parameters['far_upper_bound']['value'])*denominator-bounds['upper_m2'])
    packed,recipes,assignments=place_program(artifact,angle=angle,zones=manifest.zones,recipe_id=id,seed=ctx.seed,target_gfa_m2=target,floor_count=5,road_edges=edges,profile_filter=allowed,road_distance=road_index)
    massing=build_massing(ctx,packed,next(iter(recipes.values())),rb,block_recipes=recipes)
    gs=[shape(b.footprint.model_dump()) for b in massing.buildings];footprint=unary_union(gs)
    new_gfa=sum(shape(f.geometry.model_dump()).area for b in massing.buildings for f in b.floors)
    surface=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads])
    land=inputs.design_area.difference(inputs.water_geometry)
    open_space=land.difference(unary_union([footprint,unary_union(list(retained.values())),surface]))
    zone_gfa={z['zone_id']:0 for z in manifest.zones};program={}
    for b in massing.buildings:
        for f in b.floors:
            a=shape(f.geometry.model_dump()).area;program[f.use]=program.get(f.use,0)+a
            zone_gfa[assignments[b.id.removesuffix('-building')]['zone_id']]+=a
    metrics={'far':(new_gfa+bounds['upper_m2'])/denominator,'far_denominator':label,'far_denominator_m2':denominator,
        'coverage':footprint.union(unary_union(list(retained.values()))).intersection(land).area/denominator,
        'highest_new_height_m':max(b.height_m for b in massing.buildings),'heights_m':sorted({b.height_m for b in massing.buildings}),
        'open_space_ratio':open_space.area/denominator,'new_gfa_m2':new_gfa,'block_count':len(parts),'new_building_count':len(gs),
        'road_length_m':unary_union([LineString(r.coordinates) for r in roads]).intersection(inputs.design_area).length,
        'program_gfa_m2':program,'dictionary_types':sorted({b.type_id for b in massing.buildings}),'zone_uses':[{ 'zone_id':z['zone_id'],'assigned_new_gfa_m2':zone_gfa[z['zone_id']]} for z in manifest.zones]}
    checks={'far_upper':metrics['far']<=parameters['far_upper_bound']['value'],'coverage':metrics['coverage']<=parameters['coverage_upper_bound']['value'],
        'height':metrics['highest_new_height_m']<=parameters['height_upper_bound_m']['value'],
        'quality_far_minimum':metrics['far']>=.70,'open_space_minimum':metrics['open_space_ratio']>=.4,
        'four_types':len(metrics['dictionary_types'])>=4,'all_zones':all(v>0 for v in zone_gfa.values())}
    return massing,metrics,checks


def feature(g,role,**properties):return {'type':'Feature','geometry':mapping(g),'properties':{'role':role,**properties}}


class DiagnosisRoute(BaseModel):
    model_config=ConfigDict(extra='ignore',frozen=True)
    kind:str
    coordinates:list[tuple[FiniteFloat,FiniteFloat]]=Field(min_length=2)


class DiagnosisEntry(BaseModel):
    model_config=ConfigDict(extra='ignore',frozen=True)
    id:str
    coordinates:tuple[FiniteFloat,FiniteFloat]
    side:Literal['N','E','S','W']
    distance_potential:FiniteFloat=Field(ge=0)
    major_routes:list[DiagnosisRoute]=Field(default_factory=list)


class LocalDiagnosis(BaseModel):
    model_config=ConfigDict(extra='ignore',frozen=True)
    project_id:str
    study_area_id:str
    crs:Literal['EPSG:28992']
    distance_unit:Literal['m']
    entrances:list[DiagnosisEntry]
    closest_transit_side:Literal['N','E','S','W'] | None
    created_at:str
    limitations:list[str]


def load_j9b(path,project_id,study_area_id):
    raw=Path(path).read_bytes();doc=LocalDiagnosis.model_validate_json(raw).model_dump()
    if doc['project_id']!=project_id or doc['study_area_id']!=study_area_id:
        raise ValueError('J9b project/site/CRS/units mismatch')
    return raw,doc


def apply_j9b(entrances,path,project_id,study_area_id):
    """Local diagnosis weights only: no fetching, site adoption or observed flow."""
    raw,doc=load_j9b(path,project_id,study_area_id)
    candidates=doc['entrances']
    if any(not math.isfinite(e['distance_potential']) or e['distance_potential']<0 for e in candidates):
        raise ValueError('invalid J9b distance potential')
    maximum=max((e['distance_potential'] for e in candidates),default=0)
    matched=[];updated=[]
    for entry in entrances:
        nearest=min(candidates,key=lambda e:Point(e['coordinates']).distance(Point(entry.coordinates)),default=None)
        distance=Point(nearest['coordinates']).distance(Point(entry.coordinates)) if nearest else None
        if nearest and distance<=30:
            extra=nearest['distance_potential']/maximum if maximum else 0
            updated.append(entry.model_copy(update={'weight':entry.weight+extra,'diagnosis_provenance':'J9b_LOCAL_EXPLORATORY; normalized distance potential weight ASSUMED_COMMANDER'}))
            matched.append({'entry_id':entry.id,'J9b_entry_id':nearest['id'],'match_distance_m':distance,'side':nearest['side'],'weight_increment':extra})
        else:updated.append(entry)
    receipt={'path':str(path),'sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),'closest_transit_side':doc['closest_transit_side'],
        'created_at':doc['created_at'],'matches':matched,'limitations':doc['limitations'],'status':'EXPLORATORY; unverified physical doors; match tolerance 30m ASSUMED_COMMANDER'}
    return sorted(updated,key=lambda e:(-e.weight,e.id)),receipt


def run_copy(database,output,*,rules=None,diagnosis_path=None,motor_cache=None):
    database=checked_copy(database);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    rules=rules or net.NetworkRules();started=utc();clock=time.perf_counter()
    with ProjectStateStore(database,read_only=True) as store:
        ledger=store.connection.execute('select count(*),max(sequence) from ledger_events').fetchone()
        project=store.list_current('Project')[0].entity_id;ready=resolve_readiness(store,project)
        if ready.status!='READY':raise ValueError('approved context unavailable: '+str(ready.blockers))
        frozen=freeze_context(store,project,FreezeRequest(expected_workspace_revision=ready.context.workspace_revision,expected_context_hash=ready.context_hash))
        context=adapt_frozen_context(frozen,seed=42);manifest=frozen.context;inputs=_load_approved_inputs(store,project,site_generation=True)
        # V6 comparison is measured from actual preserved current geometries.
        v6=[]
        for row in store.list_current('Scenario'):
            if not row.payload.get('generator','').startswith('formal-dictionary-v6'):continue
            artifact=store.get_record(row.payload['geometry_artifact_id']).payload;p=Path(artifact['uri']);raw=p.read_bytes()
            if 'sha256:'+hashlib.sha256(raw).hexdigest()!=artifact['sha256']:raise ValueError('v6 geometry hash mismatch')
            v6.append({'scenario_id':row.entity_id,'geometry':json.loads(raw),'source':{'path':str(p),'sha256':artifact['sha256']}})
    site=inputs.design_area;land=site.difference(inputs.water_geometry)
    retained={d.feature_id:g for d,g,_ in inputs.retained_buildings}
    external,contexts,receipts,sources,mode_lookup=load_sources(site)
    destination_routes=[]
    if diagnosis_path is not None:
        _,diagnosis_doc=load_j9b(diagnosis_path,project,next(r['id'] for r in manifest.refs if r['entity_type']=='StudyArea'))
        destination_routes=[LineString(r['coordinates']) for e in diagnosis_doc['entrances'] for r in e['major_routes'] if r['kind']=='transit']
    dispositions=net.classify_existing(sources,site,rules,list(retained.values()),destination_routes);fixed=retained_roads(sources,dispositions,mode_lookup,rules)
    entrances,samples=net.diagnose_entrances(site,contexts,external)
    if not entrances:raise ValueError('no source-derived multimodal entrances')
    diagnosis_receipt={'status':'J9b_PENDING_INTEGRATION'}
    if diagnosis_path is not None:
        study=next(r['id'] for r in manifest.refs if r['entity_type']=='StudyArea')
        entrances,diagnosis_receipt=apply_j9b(entrances,diagnosis_path,project,study)
    angle=round(_principal_angle(land)/15)*15
    (output/'inputs.json').write_text(json.dumps({'rules':rules.model_dump(),'dispositions':[d.model_dump() for d in dispositions],
        'entrances':[e.model_dump() for e in entrances],'sources':receipts,'frozen_context':frozen.model_dump(mode='json'),
        'context_hash':generation_context_digest(context),'baseline_distribution':{m:{'count':len(s),'sha256':digest(s)} for m,s in samples.items()},
        'J9b':diagnosis_receipt},ensure_ascii=False,indent=2))
    from urban_design.scenario_syntax import merge_network,MergeParameters
    motor=merge_network(external['motor_vehicle'],net.syntax_roads(fixed,'motor_vehicle',rules),site,'motor_vehicle',MergeParameters())
    motor_doc=json.loads((CONTEXT_ROOT/'syntax_context_motor_vehicle.json').read_bytes())
    if motor['unchanged']:
        motor_reuse={'status':'REUSED_UNCHANGED_MOTOR_NETWORK','source_sha256':digest(motor_doc),'baseline_metrics':{'mean_inside_nain':sum(r['nain'] for r in motor_doc['segments'] if r['inside_site'])/sum(r['inside_site'] for r in motor_doc['segments'])}}
    else:
        print('motor_vehicle RECOMPUTE local removal',utc(),flush=True)
        docs,_=verified_extract('motor_vehicle')
        motor_inputs=net.syntax_roads(fixed,'motor_vehicle',rules)
        from urban_design.scenario_syntax import IMPLEMENTATION_SHA256
        expected={'mode':'motor_vehicle','road_input_sha256':digest([r.model_dump() for r in motor_inputs]),'network_input_sha256':digest(external['motor_vehicle']),
            'site_sha256':digest(mapping(site)),'unlinks_sha256':digest(unlink_points(docs['unlinks'])),'implementation_sha256':IMPLEMENTATION_SHA256,
            'parameters':MergeParameters(snap_tolerance_m=0).model_dump(),'engine':'PST 3.3.1'}
        if motor_cache is not None:
            raw=Path(motor_cache).read_bytes();motor_result=json.loads(raw)
            if motor_result.get('status')!='COMPUTED' or any(motor_result.get(k)!=v for k,v in expected.items()):
                raise ValueError('motor cache input/implementation mismatch')
            motor_result={**motor_result,'cache_receipt':{'path':str(motor_cache),'sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),'verified_inputs':expected}}
        else:
            motor_result=compare_syntax(external['motor_vehicle'],motor_inputs,site,'motor_vehicle',parameters=MergeParameters(snap_tolerance_m=0),unlinks=unlink_points(docs['unlinks']))
        (output/'motor-vehicle-syntax.json').write_text(json.dumps(motor_result,ensure_ascii=False,allow_nan=False))
        motor_reuse={'status':motor_result['status'],'before':(motor_result.get('before') or {}).get('metrics'),'after':(motor_result.get('after') or {}).get('metrics'),'path':str(output/'motor-vehicle-syntax.json'),'reason':'Local industrial motor roads removed; city through roads unchanged; service-only proposals excluded.'}
    all_rows=[];selected=[]
    created=datetime.fromisoformat(started.replace('Z','+00:00'))
    for family in net.FAMILIES:
        family_rows=[]
        for variant in net.generate_variants(land,list(retained.values()),entrances,family,rules,angle=angle,fixed_roads=fixed):
            t=time.perf_counter();roads=[*fixed,*variant.roads]
            print(variant.id,'START',utc(),flush=True)
            # Retained cycle-only roads receive a DRAFT shared corridor overlay;
            # existing source geometry/modes remain immutable, overlay is explicit.
            roads.extend(shared_existing_overlay(fixed,site,variant.id,rules))
            # Paths may run through the waterfront no-build band (that is where the
            # public waterfront walk belongs); only water and retained setbacks block them.
            cleanup_obstacles=unary_union([inputs.water_geometry,
                *[g.buffer(rules.retained_setback_m,join_style=2) for g in retained.values()]])
            roads,cleanup_report=cleanup_network(roads,entrances,obstacles=cleanup_obstacles,
                domain=land,network_rules=rules)
            quality_roads=roads
            roads=segment_planned_roads(roads)
            public_spaces=[shape(g) for g in [*variant.parameters['central_core'],*variant.parameters['green_band']]]
            parts=net.derive_blocks(land,roads,list(retained.values()),inputs.water_geometry,rules,public_spaces)
            quality=net.geometry_quality(land,quality_roads,parts,entrances,rules)
            # Surface subtraction creates buildable remnants as well as closed
            # centerline blocks. Keep all oversized remnants explicit in receipt.
            for dimension in quality['block_dimensions']:
                if dimension['max_m']>rules.block_max_m:
                    cleanup_report.unresolved_block.append({
                        'coordinates':dimension['centroid'],'bounds':dimension['bounds'],
                        'long_side_m':dimension['max_m'],'short_side_m':dimension['min_m'],
                        'reason':'Oversized buildable remnant after road surfaces/public spaces/obstacles subtraction',
                        'measurement_basis':'derive_blocks buildable surface'})
            variant.parameters['network_cleanup']=cleanup_report.model_dump(mode='json')
            row={'id':variant.id,'recipe_id':variant.id,'recipe_version':VERSION,'family':family,'parameters':variant.parameters,
                'network_cleanup':cleanup_report.model_dump(mode='json'),'quality':quality,'geometry_score':quality['geometry_score'],'status':'INVALID','design_intent':{
                    'strategy':{'radial':'入口匯向中心與環形公共路徑','axial':'承接高整合入口，以主軸與分支組織日常行走','grid':'對齊基地軸向的共享步行騎行網格，分散通達','green_service':'中央無車共享綠廊與外圍服務環路'}[family],
                    'entry_logic':'從逐模式 Syntax 診斷的外部入口接入預先規劃走廊；步行800m與騎行2km各自重算，不推估觀測人流。',
                    'daily_life':'自行車與步行共享走廊，建築配置先滿足自行車25m及服務40m的構件距離；入口與停車位置尚未驗證。',
                    'road_reason':'城市穿越及公共目的地路線保留；工業碎片與小圈依MOB-008清理，保留物服務依賴保守保障；逐路理由見inputs.json。',
                    'rule_card_ids':list(rules.rule_card_ids),'status':'DRAFT_TEMPLATE_PENDING_FOUNDER','generator':'deterministic_template'},'failure_reasons':[]}
            results={}
            for mode in ('pedestrian','bicycle'):
                docs,receipt=verified_extract(mode)
                from urban_design.syntax_engines.pst_adapter import PSTExecutionError
                try:
                    result=compare_syntax(external[mode],net.syntax_roads(roads,mode,rules),site,mode,
                        parameters=MergeParameters(snap_tolerance_m=0),unlinks=unlink_points(docs['unlinks']))
                except (ValueError,PSTExecutionError,ArithmeticError) as exc:
                    result={'status':'ERROR','error':str(exc),'error_type':type(exc).__name__,'before':None,'after':None,'runtime_seconds':time.perf_counter()-t,
                        'formal_result_eligible':False,'road_input_sha256':digest([r.model_dump() for r in roads])}

                result['source_receipt']=receipt;results[mode]=result
                path=output/f'{variant.id}-{mode}-syntax.json';path.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
                print(variant.id,mode,result['status'],round(result['runtime_seconds'],2),flush=True)
            print(variant.id,'SCORING',utc(),flush=True)
            try:
                row['target_vs_actual'],row['target_score']=net.score_targets(net.strategy_targets(family,rules),roads,results,samples,rules)
            except ValueError as exc:
                # Keep the strict relationship assertion. A source-covered PST
                # result with simplified chords is insufficient for per-road
                # target acceptance; retain raw provider numbers as unverified.
                row['failure_reasons'].append('target_geometry_lineage: '+str(exc))
                row['target_score']=0
                row['target_vs_actual']=[]
                for target in net.strategy_targets(family,rules):
                    ids={r.id for r in roads if r.hierarchy==target.hierarchy and target.mode in r.modes}
                    raw=[r['nain'] for r in (results[target.mode].get('after') or {}).get('segments',[])
                         if r['inside_site'] and any(r['source_line_id']==('proposal:'+id) or r['source_line_id'].startswith('proposal:'+id+':part:') or r['source_line_id'] in ('proposal:'+id+'_a','proposal:'+id+'_b') for id in ids)]
                    row['target_vs_actual'].append({**target.model_dump(),'actual_mean_nain':None,'actual_percentile':None,
                        'status':'未達成','verification_status':'INVALID_GEOMETRY_LINEAGE; actual UNKNOWN, not zero',
                        'raw_unverified_mean_nain':sum(raw)/len(raw) if raw else None,'raw_segment_count':len(raw),'score':0,
                        'reason':str(exc)})

            row['syntax']={m:{'status':r['status'],'before':(r.get('before') or {}).get('metrics'),'after':(r.get('after') or {}).get('metrics'),'path':str(output/f'{variant.id}-{m}-syntax.json')} for m,r in results.items()}
            features=[feature(site,'site_area'),feature(inputs.water_geometry,'water'),*[feature(g,'retained',building_id=k) for k,g in retained.items()],
                *[feature(LineString(r.coordinates),'road',**{**r.model_dump(exclude={'coordinates','id'}),'road_id':r.id}) for r in roads],*[feature(p,'street_block') for p in parts],
                *[feature(shape(f['geometry']),'removed_road',source_id=f['id'],origin='removed') for f in sources if next(d for d in dispositions if d.source_id==f['id']).disposition=='removed'],
                *[feature(Point(e.coordinates),'entrance',entry_id=e.id,modes=e.modes) for e in entrances],
                *[feature(shape(g),'central_core') for g in variant.parameters['central_core']],
                *[feature(shape(g),'green_band') for g in variant.parameters['green_band']]]
            try:
                print(variant.id,'PLACEMENT',utc(),flush=True)
                massing,metrics,d2=place_candidate(context,manifest,inputs,roads,parts,variant.id,angle,rules,created)
                features.extend(feature(shape(b.footprint.model_dump()),'new_building',height_m=b.height_m,type_id=b.type_id,building_id=b.id) for b in massing.buildings)
                row['metrics']=metrics;row['d2_checks']=d2;row['massing']=massing.model_dump(mode='json')
                print(variant.id,'HARD_CHECKS',utc(),flush=True)
                row['hard_checks']=net.hard_checks(site=site,roads=roads,buildings=[shape(b.footprint.model_dump()) for b in massing.buildings],retained_before=retained,retained_after=retained,water=inputs.water_geometry,entrances=entrances,external=external,rules=rules,public_spaces=public_spaces)
                row['failure_reasons'] += [k for k,v in row['hard_checks']['checks'].items() if not v]+[k for k,v in d2.items() if not v]
                # Founder 2026-10-08: two tiers. Safety/basic logic is hard (above, plus
                # network connectivity); geometry quality is scored with explicit warnings.
                if quality['connected_component_count']!=1:row['failure_reasons'].append('network_disconnected')
                warnings=[]
                warnings += [{'kind':'acute_angle','coordinates':v['coordinates'],'value':v['angle_deg'],'limit':rules.minimum_turn_deg} for v in quality['angle_violations']]
                warnings += [{'kind':'short_segment','coordinates':v['coordinates'],'value':v['length_m'],'limit':rules.minimum_segment_m} for v in quality['short_segments']]
                warnings += [{'kind':'block_size','coordinates':b['centroid'],'value':[b['min_m'],b['max_m']],'limit':[rules.block_min_m,rules.block_max_m]} for b in quality['block_dimensions'] if not b['in_range']]
                if quality['dead_end_count']>rules.max_dead_ends:
                    warnings.append({'kind':'dead_ends','coordinates':quality['dead_ends'],'value':quality['dead_end_count'],'limit':rules.max_dead_ends})
                row['quality_warnings']=warnings
                row['quality_status']='PASS' if quality['valid'] else 'WARN'
                row['failure_reasons'].extend(variant.parameters['construction_failures'])
                if motor_reuse['status'] not in ('COMPUTED','REUSED_UNCHANGED_MOTOR_NETWORK'):row['failure_reasons'].append('motor_syntax_unavailable')
                if any(r['status']!='COMPUTED' for r in results.values()):row['failure_reasons'].append('syntax_unavailable')
                row['status']='VALID' if not row['failure_reasons'] else 'INVALID'
            except ValueError as exc:row['failure_reasons'].append(str(exc))
            row['geometry']={'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:28992'}},'features':features}
            row['runtime_seconds']=time.perf_counter()-t;row['result_hash']=digest({k:v for k,v in row.items() if k not in ('runtime_seconds','syntax')})
            (output/f'{variant.id}.json').write_text(json.dumps(row,ensure_ascii=False,indent=2,allow_nan=False))
            print(variant.id,row['status'],row['failure_reasons'],flush=True)
            family_rows.append(row);all_rows.append(row)
        winner=net.select_variant([r for r in family_rows if r['status']=='VALID'])
        diagnostic=max(family_rows,key=lambda r:(.7*r['target_score']+.3*r['geometry_score'],r['id']))
        chosen=winner or diagnostic
        selected.append({'family':family,'selected_variant':winner['id'] if winner else None,'diagnostic_variant':chosen['id'],
            'status':'DRAFT' if winner else 'INVALID','selection_basis':'0.7 target attainment + 0.3 geometry quality; ASSUMED_COMMANDER; within-family only',
            'metrics':chosen.get('metrics'),'hard_checks':chosen.get('hard_checks'),'quality':chosen['quality'],'syntax':chosen['syntax'],
            'target_vs_actual':chosen['target_vs_actual'],'failure_reasons':chosen['failure_reasons']})
        plot_plan(chosen,output/f'{family}-plan.png',site)
    all_surfaces=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in fixed])
    baseline=[]
    for v in v6:
        fs=v['geometry']['features'];gs=[shape(f['geometry']) for f in fs if f['properties']['role']=='new_building']
        roadfs=[f for f in fs if f['properties']['role']=='road'];surfaces=unary_union([all_surfaces,*[shape(f['geometry']).buffer(f['properties']['width_m']/2) for f in roadfs]])
        baseline.append({'scenario_id':v['scenario_id'],'road_overlap_area_m2':unary_union(gs).intersection(surfaces).area,'heights_m':sorted({f['properties']['height_m'] for f in fs if f['properties']['role']=='new_building'}),
            'generated_road_length_m':unary_union([shape(f['geometry']) for f in roadfs]).length,'total_road_length_m':unary_union([*[LineString(r.coordinates) for r in fixed],*[shape(f['geometry']) for f in roadfs]]).intersection(site).length,'source':v['source'],'comparison_width_basis':rules.model_dump()})
    report={'status':'DRAFT' if all(r['selected_variant'] for r in selected) else 'INCOMPLETE','version':VERSION,'start_utc':started,'end_utc':utc(),
        'runtime_seconds':time.perf_counter()-clock,'database':str(database),'database_access':'READ_ONLY_COPY','copy_ledger_before':list(ledger),
        'project_id':project,'rules':rules.model_dump(),'classification_counts':{k:sum(d.disposition==k for d in dispositions) for k in ('retained','transformed','removed')},'variant_count':len(all_rows),'valid_variant_count':sum(r['status']=='VALID' for r in all_rows),
        'strategies':selected,'motor_syntax':motor_reuse,'v6_comparison':baseline,'overall_winner':None,
        'parking':{'trigger_area_m2':rules.parking_area_trigger_m2,'trigger_office_share':rules.parking_office_share_trigger,'area_triggered':site.area>=rules.parking_area_trigger_m2,
            'office_share':None,'status':'J9b_LAND_USE_PENDING; underground/building access required if trigger fires; no general through-car roads'},
        'limitations':['DRAFT cards only; Founder review pending.','Current service does not publish these copy-only candidates.','J9b weights are exploratory; geometry proxy does not verify real entrances or parking.',
            'Context 3 km display baseline has extract-edge risk; targets compare pedestrian 800m and bicycle 2km only.','No HumanDecision, acceptance or deployment.']}
    with ProjectStateStore(database,read_only=True) as s:report['copy_ledger_after']=list(s.connection.execute('select count(*),max(sequence) from ledger_events').fetchone())
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    return report


def plot_plan(row,path,site):
    # Single renderer, including when matplotlib is installed in the executor.
    subprocess.run([os.environ.get('URBAN_DESIGN_PLOT_PYTHON', sys.executable),
        str(Path(__file__).resolve().parents[3]/'scripts/render_multimodal_plan.py'),
        '--input',str(Path(path).parent/(row['id']+'.json')),'--output',str(path)],check=True,timeout=60)
