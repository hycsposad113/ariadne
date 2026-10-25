"""Read-only NET2 geometry/receipt audit; writes only its new report path."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from shapely.geometry import shape
from shapely.ops import unary_union


def has_clear_contact(row,target,links,land,mass):
    source=shape(row['geometry'])
    if source.distance(target)<=.001:return True
    for link in links:
        line=shape(link['geometry']);width=link['properties']['width_m']
        if line.distance(source)>.001 or line.distance(target)>.001:continue
        surface=line.buffer(width/2,cap_style=2,join_style=2)
        if surface.difference(land).area<=.05 and surface.intersection(mass).area<=.05:return True
    return False


def same_serialized_result(fresh,stored):
    """Compare the JSON artifact representation, retaining every measured value."""
    return json.loads(json.dumps(fresh,allow_nan=False))==stored


def receipt(path):
    return {'path':str(path.resolve()),'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),'size_bytes':path.stat().st_size}


def audit_plan(path,parent,recompute=False):
    plan=json.loads(path.read_text());old=json.loads(parent.read_text())
    land=shape(plan['site']).difference(shape(plan['water']))
    mass=unary_union([shape(b['geometry']) for b in plan['buildings']])
    rows=plan['roads'];by_id={str(r['id']):r for r in rows}
    baseline=old.get('net1',{}).get('added_roads',[])
    preserved=[r['id'] for r in baseline if by_id.get(str(r['id']))==r]
    changed=[r['id'] for r in baseline if by_id.get(str(r['id']))!=r]
    new=[b for b in plan['buildings'] if not b['properties'].get('retained')]
    primary=unary_union([shape(r['geometry']) for r in rows if r['properties']['role']=='primary_street'])
    waterfront=unary_union([shape(r['geometry']) for r in rows if r['properties']['role']=='waterfront_path'])
    cross=[r for r in rows if r['properties']['role'] in ('primary_street','block_edge_street','harbour_cross_lane')]
    links=[r for r in rows if r['properties'].get('net2_strategy') in ('each_transverse_to_waterfront','primary_to_waterfront')]
    contacts=[{'road_id':r['id'],'role':r['properties']['role'],'clear_direct_waterfront_contact':has_clear_contact(r,waterfront,[q for q in links if q['properties'].get('source_road_id')==r['id']],land,mass)} for r in cross]
    check=plan['validation'];metrics=plan['metrics'];gfa=metrics['new_gfa_m2']
    fresh=None
    if recompute:
        from urban_design.generation.fabric_plan import validate_plan
        measured=validate_plan(plan)
        fresh={'status':measured['status'],'failure_ids':measured['failure_ids'],'stored_result_equal':same_serialized_result(measured,check)}
    required=('LAND_COVERAGE','LAND_NO_OVERLAP','LAND_MANAGEMENT','LAND_SUM_100_PERCENT','LAND_USE_CATEGORIES','FIRE_ALL_EXTERIORS','WING_DEPTH','COURTYARD_CLEAR_WIDTH','SLAB_LENGTH_DEPTH','HEIGHT_CAP','CONNECTIVITY_PEDESTRIAN','CONNECTIVITY_BICYCLE','CONNECTIVITY_CAR','CONNECTIVITY_SERVICE','CONNECTIVITY_FIRE')
    source_checks=check.get('checks',{})
    if isinstance(source_checks,list):source_checks={r.get('id',r.get('check_id')):r for r in source_checks}
    def status(key):
        value=source_checks.get(key)
        return value.get('status','UNKNOWN') if isinstance(value,dict) else 'UNKNOWN'
    floor_bad=[b['id'] for b in new if b['properties']['floors']>5 or b['properties']['height_m']>20]
    return {'fabric_id':plan['fabric_id'],'plan':receipt(path),'parent':receipt(parent),'stored_validation_status':check['status'],'fresh_validation':fresh,'failure_ids':check['failure_ids'],'new_failure_ids':sorted(set(check['failure_ids'])-set(old['validation']['failure_ids'])),
            'required_core_checks':{k:status(k) for k in required},'new_gfa_m2':gfa,'new_gfa_percent':100*gfa/146873,'exact_90_percent_minimum_m2':146873*.9,'gfa_target_pass':146873*.9<=gfa<=146873,
            'allocation_percent':metrics.get('allocation_percent'),'unallocated_m2':land.difference(unary_union([shape(r['geometry']) for r in plan['land_use']])).area,
            'max_floors':max(b['properties']['floors'] for b in new),'max_height_m':max(b['properties']['height_m'] for b in new),'five_floor_height_pass':not floor_bad,'floor_or_height_violation_ids':floor_bad,
            'net1_preservation':{'preserved_count':len(preserved),'original_count':len(baseline),'changed_or_missing_ids':changed,'all_exact':not changed,'bridge_ids':[r['id'] for r in baseline if r['properties'].get('assumption')=='ASSUMED_BRIDGE']},
            'capacity_search':plan.get('net2',{}).get('five_storey_capacity'),'network_connection_diagnostics':plan.get('net2',{}).get('network_preservation',{}),'primary_length_m':primary.length,'waterfront_per_street_contacts':contacts,'waterfront_all_transverse_and_primary_pass':all(r['clear_direct_waterfront_contact'] for r in contacts) if contacts else False,
            'blocks_changed':plan['blocks']!=old['blocks'],'buildings_changed':plan['buildings']!=old['buildings'],'formal_result_eligible':False}


def run(output,recompute=False):
    base=Path('artifacts/net2');snapshot=json.loads((base/'baseline-sha256.json').read_text())
    drift=[]
    for row in snapshot['retained_inputs']:
        p=Path(row['path'])
        if not p.is_file() or receipt(p)!=row:drift.append(str(p))
    rounds=[]
    for n in (1,2,3):
        folder=base/f'round-{n}'/'plans'
        if not folder.exists():continue
        plans=[audit_plan(p,Path('artifacts/fab1/run-6')/p.name,recompute and n==3) for p in sorted(folder.glob('*-plan.json'))]
        comparison=json.loads((folder/'comparison.json').read_text()) if (folder/'comparison.json').exists() else None
        rounds.append({'round':n,'plans':plans,'comparison':{'status':comparison['status'],'distinct_pair_count':comparison['distinct_pair_count'],'pairwise':comparison['pairwise']} if comparison else None})
    files=[p for d in (base,Path('artifacts/fab1/run-7')) if d.exists() for p in d.rglob('*') if p.is_file() and p!=output]
    oversize=[{'path':str(p),'bytes':p.stat().st_size} for p in files if p.stat().st_size>=5_000_000]
    result={'schema_version':'net2-delivery-audit-v1','source_commit':'0a939db','fresh_validation_scope':'final_round_3' if recompute else 'stored_only','old_input_hash_drift':drift,'oversize_files':oversize,'rounds':rounds,'formal_result_eligible':False,'authority_database':'NOT_ACCESSED','runtime_ports':[]}
    data=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
    if len(data.encode())>=5_000_000:raise ValueError('Audit exceeds size cap')
    with output.open('x') as stream:stream.write(data)
    print(json.dumps({'rounds':len(rounds),'old_input_hash_drift':len(drift),'oversize_files':len(oversize)}))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--recompute',action='store_true');a=p.parse_args();run(a.output,a.recompute)
