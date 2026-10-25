"""J12c offline network/massing coupling; SQLite backup source must be opened mode=ro."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from itertools import combinations
from shapely.geometry import shape, LineString, MultiPoint, mapping
from shapely.ops import unary_union
from urban_design.store import ProjectStateStore
from urban_design.approved_generation import _load_approved_inputs
from urban_design.generation.formal_multimodal import checked_copy, utc, load_sources, load_j9b, retained_roads, unlink_points
from urban_design.generation.formal_pipeline import approved_parameters
from urban_design.generation.formal_adapter import retained_gfa_bounds
from urban_design.generation import multimodal_network as net
from urban_design.generation.context_massing import generate_massing, difference_metrics, FAMILIES
from urban_design.generation.network_massing_coupling import (CouplingRules, ClusterSelector, ranked_development_roads, downgrade_roads, coupling_checks)
from urban_design.far import FarSiteContext, resolve_far_denominator


def receipt(path,archive=None):
    raw=Path(path).read_bytes()
    sha=hashlib.sha256(raw).hexdigest()
    result=dict(path=str(Path(path).resolve()),sha256='sha256:'+sha)
    if archive is not None:
        archive.mkdir(exist_ok=True)
        snapshot=archive/(Path(path).stem+'-'+sha[:12]+'.json')
        if not snapshot.exists():
            with snapshot.open('xb') as f:f.write(raw)
        elif snapshot.read_bytes()!=raw:raise ValueError('immutable input snapshot collision')
        result['snapshot_path']=str(snapshot)
    return json.loads(raw),result


def validate_motor_baseline(motor, expected):
    """The J11 shared baseline excludes scenario-specific service roads."""
    if motor.get('status') != 'COMPUTED' or any(motor.get(k) != v for k,v in expected.items()):
        raise ValueError('motor baseline input/implementation mismatch')



def compare_motor_using_verified_before(features,roads,site,unlinks,baseline,source_ref):
    """Run the new layer, reusing ONLY the verified run13 external baseline.

    The caller has already checked the fixed-road baseline and raw input receipt.
    Massing never enters this metric; this is not a quality-gate substitution.
    """
    from urban_design import scenario_syntax as ss
    parameters=ss.MergeParameters(snap_tolerance_m=0)
    expected=dict(mode='motor_vehicle',radius_m=ss.MODES['motor_vehicle'][1],
        site_sha256=ss.digest(mapping(site)),network_input_sha256=ss.digest(features),
        unlinks_sha256=ss.digest(unlinks),implementation_sha256=ss.IMPLEMENTATION_SHA256,
        parameters=parameters.model_dump(),engine='PST 3.3.1')
    validate_motor_baseline(baseline,expected)
    if not source_ref.get('sha256') or not baseline.get('before',{}).get('segments'):
        raise ValueError('verified motor baseline before artifact required')
    started=time.perf_counter();merge=ss.merge_network(features,roads,site,'motor_vehicle',parameters,unlinks)
    common={k:v for k,v in baseline.items() if k not in ('before','after','diff','merge','runtime_seconds','before_seconds','after_seconds','reuse_status')}
    common.update(road_input_sha256=ss.digest([r.model_dump() for r in roads]),merge={k:v for k,v in merge.items() if k!='features'},
        before_cache_provenance=source_ref,orchestration_method='j12c-verified-motor-before-cache-v1')
    if merge['status']=='BLOCKED':
        return {**common,'status':'BLOCKED','error':merge['reason'],'before':None,'after':None,'diff':[],'runtime_seconds':time.perf_counter()-started}
    before=baseline['before']['segments'];buffer,radius=ss.MODES['motor_vehicle']
    after_unlinks=tuple(sorted(set(tuple(p) for p in unlinks)|set(merge['derived_unlinks'])))
    clock=time.perf_counter()
    after=before if merge['unchanged'] else ss._compute(merge['features'],ss.PSTAdapter(manifest_path=ss.DEFAULT_PST_MANIFEST),radius,after_unlinks,site)
    after_seconds=time.perf_counter()-clock
    breaks={key:ss._breaks(before,key) for key in ('nain','nach')};threshold=breaks['nain'][3]
    for row in after:row['boundary_effect_risk']=row['distance_to_site_m']>buffer-radius
    return {**common,'status':'COMPUTED','reuse_status':'VERIFIED_BEFORE_AND_UNCHANGED_AFTER' if merge['unchanged'] else 'VERIFIED_BEFORE_FRESH_AFTER',
        'before':{'segments':before,'metrics':ss._metrics(before,threshold)},'after':{'segments':after,'metrics':ss._metrics(after,threshold)},
        'diff':ss.segment_diff(before,after),'legend_breaks':breaks,'before_seconds':0,'after_seconds':after_seconds,'runtime_seconds':time.perf_counter()-started}


def matching_motor_cache(roots,id,expected,archive):
    """Only complete, identical road/extract/site/engine inputs can be reused."""
    for root in roots:
        root=Path(root);path=root/(id+'-motor_vehicle-syntax.json')
        if not path.is_file() or not (root/(id+'.json')).is_file():continue
        document,ref=receipt(path,archive)
        try:validate_motor_baseline(document,expected)
        except ValueError:continue
        if not document.get('before') or not document.get('after'):continue
        return {**document,'reuse_status':'HASH_VERIFIED_COMPLETE_SCENARIO_MOTOR_CACHE','cache_provenance':ref}
    return None

def run(database,network_root,output,*,variant=0,motor_result_roots=()):
    database=checked_copy(database);root=Path(network_root);output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    started=utc();clock=time.perf_counter()
    archive=output/'input-snapshot'
    source,inputs_receipt=receipt(root/'inputs.json',archive)
    with ProjectStateStore(database,read_only=True) as store:
        ledger_before=list(store.connection.execute('select count(*),max(sequence) from ledger_events').fetchone())
        project=store.list_current('Project')[0].entity_id
        inputs=_load_approved_inputs(store,project,site_generation=True)
        # Do not create decisions or mutate any approval state.
        constraint=next(c for c in inputs.constraint_set.constraints if c.name=='far_upper_limit' and c.scope=='whole_site')
        denominator,label=resolve_far_denominator(constraint,FarSiteContext(inputs.design_area,inputs.water_geometry))
        parameters=approved_parameters(inputs)
        manifest=type('Manifest',(),source['frozen_context']['context'])()
        bounds=retained_gfa_bounds(manifest)
        if bounds['status']=='UNAVAILABLE':raise ValueError('retained GFA UNKNOWN')
        from urban_design.generation_context import resolve_readiness
        ready=resolve_readiness(store,project)
        if ready.status!='READY' or ready.context_hash!=source['frozen_context']['context_hash']:
            raise ValueError('copy/source frozen approval context mismatch')
    rules=net.NetworkRules.model_validate(source['rules'])
    entrances=[net.Entrance.model_validate(e) for e in source['entrances']]
    external,_,_,source_features,mode_lookup=load_sources(inputs.design_area)
    motor,motor_receipt=receipt(root/'motor-vehicle-syntax.json',archive)
    from urban_design.scenario_syntax import digest, verified_extract, MergeParameters, IMPLEMENTATION_SHA256
    fixed=retained_roads(source_features,[net.Disposition.model_validate(d) for d in source['dispositions']],mode_lookup,rules)
    motor_inputs=net.syntax_roads(fixed,'motor_vehicle',rules)
    motor_docs,_=verified_extract('motor_vehicle')
    validate_motor_baseline(motor,dict(mode='motor_vehicle',road_input_sha256=digest([r.model_dump() for r in motor_inputs]),
        network_input_sha256=digest(external['motor_vehicle']),site_sha256=digest(mapping(inputs.design_area)),
        unlinks_sha256=digest(unlink_points(motor_docs['unlinks'])),implementation_sha256=IMPLEMENTATION_SHA256,
        parameters=MergeParameters(snap_tolerance_m=0).model_dump(),engine='PST 3.3.1'))
    retained={d.feature_id:g for d,g,_ in inputs.retained_buildings}
    context=[];diagnosis_receipt=source.get('J9b',{})
    if diagnosis_receipt.get('path'):
        raw,doc=load_j9b(diagnosis_receipt['path'],project,next(r['id'] for r in source['frozen_context']['context']['refs'] if r.get('entity_type')=='StudyArea'))
        if 'sha256:'+hashlib.sha256(raw).hexdigest()!=diagnosis_receipt['sha256']:raise ValueError('J9b hash drift')
        transit_side=doc['closest_transit_side']
        coords=[e['coordinates'] for e in doc['entrances'] if e['side']==transit_side]
        if coords:context.append(dict(kind='transit',geometry=mapping(MultiPoint(coords)),source_ref=diagnosis_receipt['sha256']+'; J9b closest-side entrance proxy, not stop geometry'))
    dakpark_doc,dakpark_receipt=receipt(Path('data/context/dakpark-osm-epsg28992.geojson'),archive)
    if dakpark_doc.get('crs',{}).get('properties',{}).get('name')!='EPSG:28992':raise ValueError('Dakpark CRS required')
    if len(dakpark_doc['features'])!=1:raise ValueError('exactly one source-backed Dakpark park polygon required')
    park_feature=dakpark_doc['features'][0];p=park_feature['properties']
    if p.get('leisure')!='park' or p.get('name')!='Dakpark' or not p.get('source_ref') or p.get('elevation_difference_m')!=10 or not p.get('elevation_provenance','').startswith('ASSUMED_PORTFOLIO_P21'):
        raise ValueError('Dakpark source/elevation provenance mismatch')
    context.append(dict(kind='dakpark',geometry=park_feature['geometry'],source_ref=p['source_ref']+'; '+dakpark_receipt['sha256']+'; ODbL 1.0; ASSUMED_PORTFOLIO_P21',elevation_difference_m=10))
    results=[];failures=[]
    for family in FAMILIES:
        id=family+f'-{variant}'
        if variant==-1:
            available=[]
            for path in sorted(root.glob(family+'-[0-9].json')):
                candidate=json.loads(path.read_bytes())
                # J12 replaces J11's massing: old four_types/all_zones failures
                # do not disqualify an otherwise intact network. All are rerun
                # on the NEW massing below; no inherited failed gate is waived.
                checks=candidate.get('hard_checks',{}).get('checks',{})
                intact=all(checks.get(k) is True for k in ('bicycle_adjacency','retained_intact','retained_fire_service','entrance_connectivity'))
                modes=candidate.get('syntax',{})
                computed=all(modes.get(m,{}).get('status')=='COMPUTED' for m in ('pedestrian','bicycle'))
                connected=candidate.get('quality',{}).get('connected_component_count')==1
                if candidate.get('status')=='VALID' and intact and computed and connected and not candidate['parameters'].get('construction_failures'):available.append(candidate)
            if not available:
                failures.append(dict(id=family,reason='no intact, connected, computed J11 network/Syntax variant available'));continue
            id=max(available,key=lambda c:(c['target_score'],c['geometry_score'],c['id']))['id']
        if not (root/(id+'.json')).is_file():
            failures.append(dict(id=id,reason='J11 result not yet available'));continue
        old,row_receipt=receipt(root/(id+'.json'),archive)
        from urban_design.scenario_syntax import digest
        if old.get('result_hash')!=digest({k:v for k,v in old.items() if k not in ('runtime_seconds','syntax','result_hash')}):
            failures.append(dict(id=id,reason='J11 result hash mismatch',source=row_receipt));continue
        features=old['geometry']['features']
        roads=[net.NetworkRoad.model_validate(dict(id=f['properties']['road_id'],coordinates=f['geometry']['coordinates'],**{k:v for k,v in f['properties'].items() if k in net.NetworkRoad.model_fields and k!='id'})) for f in features if f['properties']['role']=='road']
        public=[shape(f['geometry']) for f in features if f['properties']['role'] in ('central_core','green_band')]
        blocks=[shape(f['geometry']) for f in features if f['properties']['role']=='street_block']
        pedestrian,ped_receipt=receipt(root/(id+'-pedestrian-syntax.json'),archive)
        bicycle,bike_receipt=receipt(root/(id+'-bicycle-syntax.json'),archive)
        if pedestrian.get('status')!='COMPUTED':
            failures.append(dict(id=id,reason=pedestrian.get('error','pedestrian Syntax not computed'),source=row_receipt));continue
        if bicycle.get('status')!='COMPUTED' or bicycle['road_input_sha256']!=digest([r.model_dump() for r in net.syntax_roads(roads,'bicycle',rules)]):
            failures.append(dict(id=id,reason='bicycle source lineage mismatch',source=bike_receipt));continue
        coupling_rules=CouplingRules()
        ranked=ranked_development_roads(family,roads,pedestrian,bicycle,inputs.design_area,entrances,coupling_rules,rules)
        print(id,'發展街道候選',len(ranked),flush=True)
        selector=ClusterSelector(ranked,roads,inputs.water_geometry,coupling_rules)
        result=generate_massing(family=family,blocks=blocks,roads=roads,syntax_document=pedestrian,network_rules=rules,
            site=inputs.design_area,water=inputs.water_geometry,retained=retained,zones=manifest.zones,entrances=entrances,
            denominator=denominator,retained_gfa=bounds['upper_m2'],parameters=parameters,context_edges=context,candidate_selector=selector)
        print(id,'集中量體',len(result['buildings']),'發展街道',len(selector.development),flush=True)
        coupling_external={**external,"_site":inputs.design_area,"_water":inputs.water_geometry}
        roads,trace=downgrade_roads(roads,[shape(f["geometry"]) for f in result["features"]],retained,entrances,coupling_external,rules,public)
        print(id,'逐段道路處理完成',len(trace),flush=True)
        from urban_design.scenario_syntax import compare_syntax
        after_syntax={}
        for mode,before_doc in [("pedestrian",pedestrian),("bicycle",bicycle),("motor_vehicle",motor)]:
            syntax_roads=net.syntax_roads(roads,mode,rules)
            docs,_=verified_extract(mode)
            if mode=="motor_vehicle" and digest([r.model_dump() for r in syntax_roads])==motor["road_input_sha256"]:
                after_doc={**motor,"reuse_status":"HASH_VERIFIED_RUN13_PUBLIC_MOTOR_UNCHANGED"}
            elif mode=='motor_vehicle':
                expected=dict(mode=mode,radius_m=10000,road_input_sha256=digest([r.model_dump() for r in syntax_roads]),network_input_sha256=digest(external[mode]),site_sha256=digest(mapping(inputs.design_area)),unlinks_sha256=digest(unlink_points(docs['unlinks'])),implementation_sha256=IMPLEMENTATION_SHA256,parameters=MergeParameters(snap_tolerance_m=0).model_dump(),engine='PST 3.3.1')
                after_doc=matching_motor_cache(motor_result_roots,id,expected,archive)
                if after_doc is None:after_doc=compare_motor_using_verified_before(external[mode],syntax_roads,inputs.design_area,unlink_points(docs['unlinks']),motor,motor_receipt)
            else:
                after_doc=compare_syntax(external[mode],syntax_roads,inputs.design_area,mode,parameters=MergeParameters(snap_tolerance_m=0),unlinks=unlink_points(docs["unlinks"]))
            after_syntax[mode]=after_doc
            (output/(id+"-"+mode+"-syntax.json")).write_text(json.dumps(after_doc,ensure_ascii=False,indent=2,allow_nan=False))
        # Recompute facades from the final network before all geometry gates.
        from urban_design.generation.massing_revision import facade_segments,revision_checks
        development_lines=[shape(d["geometry"]) for d in selector.development]
        for f,b in zip(result["features"],result["buildings"]):
            b["facade_segments"]=facade_segments(shape(f["geometry"]),roads,development_lines)
        edges=[e for b in result["buildings"] for e in b["facade_segments"]];allowance=.5*sum(e["length_m"] for e in edges);used=0
        for e in edges:
            if e["active"]:
                if used+e["length_m"]<=allowance:used+=e["length_m"]
                else:e["active"]=False
        for f,b in zip(result["features"],result["buildings"]):f["properties"]["facade_segments"]=b["facade_segments"]
        cc,cm,ground,spaces,remnants=coupling_checks(result,selector.development,roads,inputs.design_area,inputs.water_geometry,retained,entrances,coupling_external,coupling_rules)
        result["checks"].update(cc);result["metrics"].update(cm)
        result["checks"]["syntax_after_computed"]=all(d["status"]=="COMPUTED" for d in after_syntax.values())
        result["open_space"]=mapping(ground);result["named_open_spaces"]=spaces;result["narrow_remnants"]=remnants
        result["metrics"]["named_open_space_area_m2"]=sum(s["area_m2"] for s in spaces)
        result["metrics"]["open_space_ratio"]=ground.area/denominator
        result["metrics"]["downgraded_road_length_m"]=sum(t["length_m"] for t in trace if t["action"]=="downgraded")
        result["coupling"]=dict(version="j12c-coupling-v1",rules=coupling_rules.model_dump(),development_streets=selector.development,development_rejections=selector.rejections,road_actions=trace,syntax_comparison={})
        for mode,before_doc in [("pedestrian",pedestrian),("bicycle",bicycle),("motor_vehicle",motor)]:
            after_doc=after_syntax[mode]
            bm=before_doc["after"]["metrics"];am=after_doc["after"]["metrics"] if after_doc.get("after") else {}
            result["coupling"]["syntax_comparison"][mode]=dict(before=bm,after=am,delta={k:am[k]-v for k,v in bm.items() if isinstance(v,(int,float)) and not isinstance(v,bool) and isinstance(am.get(k),(int,float))},before_document_sha256=digest(before_doc),after_document_sha256=digest(after_doc),before_road_input_sha256=before_doc["road_input_sha256"],after_road_input_sha256=after_doc["road_input_sha256"],status=after_doc["status"],motor_service_policy="Service-only excluded under unchanged J11 DRAFT rule" if mode=="motor_vehicle" else None)
        hard=net.hard_checks(site=inputs.design_area,roads=roads,buildings=[shape(f['geometry']) for f in result['features']],
            retained_before=retained,retained_after=retained,water=inputs.water_geometry,entrances=entrances,external=external,rules=rules,public_spaces=public)
        result['network_hard_checks']=hard
        result['source_receipts']=dict(network=row_receipt,inputs=inputs_receipt,pedestrian=ped_receipt,bicycle=bike_receipt,motor=motor_receipt,J9b=diagnosis_receipt,Dakpark=dakpark_receipt)
        result['family']=family;result['id']=id;result['far_denominator']=label
        result['failure_reasons']=[k for k,v in result['checks'].items() if not v]+[k for k,v in hard['checks'].items() if not v]
        result['failure_reasons']+=old.get('parameters',{}).get('construction_failures',[])
        if old['quality']['connected_component_count']!=1:result['failure_reasons'].append('network_disconnected')
        result['status']='VALID' if not result['failure_reasons'] else 'INVALID'
        result['design_intent']=dict(reason_zh=selector.development[0]['intent_zh'] if selector.development else '無可行的雙側高整合發展街道；不得出圖',method_zh='以配置前的步行800公尺及自行車2公里整合度、外部高整合入口連通與GFA預算挑發展街道，先配置完整雙側組團，再保留必要服務路。新車道逐段試降級、失敗回退；配置後重算Syntax，公園包含共用慢行道。高度與首層用途仍依J12b的策略及context規則。Syntax為配置潛勢，非觀測人流。',rule_card_ids=sorted({c for r in result['buildings'] for c in r['design_intent']['rule_card_ids']}),status='DRAFT')
        result['geometry']={**old['geometry'],'features':[f for f in features if f['properties']['role'] not in ('new_building','road','street_block','central_core','green_band')]+[dict(type='Feature',geometry=mapping(LineString(r.coordinates)),properties=dict(role='road',road_id=r.id,**{k:v for k,v in r.model_dump().items() if k not in ('id','coordinates')},coupling_action=next((t['action'] for t in trace if t['road_id']==r.id),'unchanged'))) for r in roads]+result['features']}
        result['version']='j12c-coupling-v1'
        result['utc']=utc();result['database']=str(database)
        (output/(id+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        results.append(result)
        print(id,result['status'],{k:result['metrics'][k] for k in ('far','streetwall_continuity_ratio','largest_park_m2','park_count','narrow_remnant_area_m2','downgraded_road_length_m')},result['failure_reasons'],flush=True)
        import csv
        with (output/(id+'-scale.csv')).open('w') as csvfile:
            writer=csv.writer(csvfile);writer.writerow(['建築','類型','高度公尺','層數','底面積平方公尺','樓地板平方公尺','翼深公尺','中庭淨寬公尺','合院外框短邊公尺'])
            for b in result['buildings']:writer.writerow([b['building_id'],b['type_id'],b['height_m'],b['floor_count'],b['footprint_area_m2'],b['new_gfa_m2'],b['scale']['wing_depth_m'],b['scale'].get('courtyard_width_m'),b['scale'].get('outer_short_m')])
        # Single invalid building or hard gate => no new drawing, preserve JSON.
        if result['status']=='VALID':
            subprocess.run(['/Users/jackhsieh/.pyenv/versions/3.12.13/bin/python3','scripts/render_network_massing_coupling.py','--input',str(output/(id+'.json')),'--output',str(output)],check=True)
    differences=[dict(a=a['id'],b=b['id'],**difference_metrics(a,b)) for a,b in combinations(results,2) if a['buildings'] and b['buildings']]
    with ProjectStateStore(database,read_only=True) as store:
        ledger_after=list(store.connection.execute('select count(*),max(sequence) from ledger_events').fetchone())
    report=dict(status='DRAFT' if len(results)==4 and all(r['status']=='VALID' for r in results) and all(d['distinct'] for d in differences) and ledger_before==ledger_after else 'INCOMPLETE',
        start_utc=started,end_utc=utc(),runtime_seconds=time.perf_counter()-clock,database=str(database),database_access='READ_ONLY_COPY',
        copy_ledger_before=ledger_before,copy_ledger_after=ledger_after,variant_count=len(results),valid_count=sum(r['status']=='VALID' for r in results),
        missing=failures,pairwise_differences=differences,source_receipts=dict(inputs=inputs_receipt,motor=motor_receipt),
        rules=results[0]['rules'] if results else None,parameters=parameters,overall_winner=None,
        unfinished=['DRAFT cards require Founder review.','Dakpark noon screen is not full E1 sunlight verification.','Retained box-in-box internal survey.','Independent Claude review and browser acceptance.'])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--network-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--variant',type=int,default=0);p.add_argument('--motor-result-root',type=Path,action='append',default=[])
    a=p.parse_args();r=run(a.database,a.network_root,a.output,variant=a.variant,motor_result_roots=a.motor_result_root)
    print(r['status'],r['valid_count'],flush=True)
    raise SystemExit(0 if r['status']=='DRAFT' else 2)
