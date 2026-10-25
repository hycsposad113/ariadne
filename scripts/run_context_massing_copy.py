"""J12 offline S6 rehearsal; SQLite backup source must be opened mode=ro."""
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


def run(database,network_root,output,*,variant=0):
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
        result=generate_massing(family=family,blocks=blocks,roads=roads,syntax_document=pedestrian,network_rules=rules,
            site=inputs.design_area,water=inputs.water_geometry,retained=retained,zones=manifest.zones,entrances=entrances,
            denominator=denominator,retained_gfa=bounds['upper_m2'],parameters=parameters,context_edges=context)
        hard=net.hard_checks(site=inputs.design_area,roads=roads,buildings=[shape(f['geometry']) for f in result['features']],
            retained_before=retained,retained_after=retained,water=inputs.water_geometry,entrances=entrances,external=external,rules=rules,public_spaces=public)
        result['network_hard_checks']=hard
        result['source_receipts']=dict(network=row_receipt,inputs=inputs_receipt,pedestrian=ped_receipt,bicycle=bike_receipt,motor=motor_receipt,J9b=diagnosis_receipt,Dakpark=dakpark_receipt)
        result['family']=family;result['id']=id;result['far_denominator']=label
        result['failure_reasons']=[k for k,v in result['checks'].items() if not v]+[k for k,v in hard['checks'].items() if not v]
        result['failure_reasons']+=old.get('parameters',{}).get('construction_failures',[])
        if old['quality']['connected_component_count']!=1:result['failure_reasons'].append('network_disconnected')
        result['status']='VALID' if not result['failure_reasons'] else 'INVALID'
        result['design_intent']=dict(reason_zh='依方案自己的步行800m Syntax、已接受用途偏好與街廓尺度配置量體；高整合節點距離參與逐棟高度與首層候選用途。道路與公共核心沿用 J11；S6將無建築地面分類為具名公園／廣場，Dakpark採作品集假設高差及兩日期正午退台初篩；入口與完整日照模擬尚待驗證。未將 Syntax 當成觀測人流。',rule_card_ids=sorted({c for r in result['buildings'] for c in r['design_intent']['rule_card_ids']}),status='DRAFT')
        result['geometry']={**old['geometry'],'features':[f for f in features if f['properties']['role']!='new_building']+result['features']}
        result['utc']=utc();result['database']=str(database)
        (output/(id+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        results.append(result)
        print(id,result['status'],result['metrics'],result['failure_reasons'],flush=True)
        # Single invalid building or hard gate => no new drawing, preserve JSON.
        if result['status']=='VALID':
            subprocess.run(['/Users/jackhsieh/.pyenv/versions/3.12.13/bin/python3','scripts/render_context_massing.py','--input',str(output/(id+'.json')),'--output',str(output)],check=True)
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
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--network-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--variant',type=int,default=0)
    a=p.parse_args();r=run(a.database,a.network_root,a.output,variant=a.variant)
    print(r['status'],r['valid_count'],flush=True)
    raise SystemExit(0 if r['status']=='DRAFT' else 2)
