"""Replay unchanged motor geometry with verified source-label changes only.

Numeric PST rows are never recalculated or edited. Require identical ordered
prepared coordinates, layers, site, radius, runtime, implementation and unlinks.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from shapely.geometry import shape
from urban_design import scenario_syntax as ss
from urban_design.fabric_syntax import proposal_roads
from urban_design.generation.formal_multimodal import unlink_points
from urban_design.pst_syntax import prepare_pst_lines
from compute_fabric_syntax import cache_key, receipt, write


def label_map(old, new):
    if len(old) != len(new):
        raise ValueError('Motor feature count differs')
    if any({k:v for k,v in a.items() if k != 'id'} != {k:v for k,v in b.items() if k != 'id'} for a,b in zip(old,new)):
        raise ValueError('Motor geometry/properties/order differs')
    old_lines = prepare_pst_lines(old); new_lines = prepare_pst_lines(new)
    if len(old_lines) != len(new_lines) or any(a.coordinates != b.coordinates for a,b in zip(old_lines,new_lines)):
        raise ValueError('Prepared PST input order/geometry differs')
    return {a.id:b.id for a,b in zip(old_lines,new_lines)}


def run(source_root, target_root, cache, proof_dir):
    proof_dir.mkdir(parents=True, exist_ok=True)
    external = {m:ss.verified_extract(m)[0] for m in ss.MODES}
    features = {m:d['network']['features'] for m,d in external.items()}
    unlinks = unlink_points(external['motor_vehicle']['unlinks'])
    radius = ss.MODES['motor_vehicle'][1]; runtime = receipt(ss.DEFAULT_PST_MANIFEST)
    for path in sorted(source_root.glob('*-plan.json')):
        target_path = target_root/path.name; source=json.loads(path.read_text()); target=json.loads(target_path.read_text())
        if source['site'] != target['site']: raise ValueError('Site differs')
        site=shape(source['site']); merged=[]
        for plan in (source,target):
            roads=proposal_roads(plan,features,mode='motor_vehicle')
            merged.append(ss.merge_network(features['motor_vehicle'],roads,site,'motor_vehicle',ss.MergeParameters(snap_tolerance_m=0),unlinks))
        old,new=merged
        if old['status']!='READY' or new['status']!='READY' or old['derived_unlinks']!=new['derived_unlinks']:
            raise ValueError('Motor merge status/unlinks differ')
        links=tuple(sorted(set(tuple(p) for p in unlinks)|set(old['derived_unlinks'])))
        mapping=label_map(old['features'],new['features'])
        old_key=cache_key(old['features'],radius,links,site,runtime,ss.IMPLEMENTATION_SHA256)
        new_key=cache_key(new['features'],radius,links,site,runtime,ss.IMPLEMENTATION_SHA256)
        if old_key==new_key: continue
        old_raw=cache/(old_key.removeprefix('sha256:')+'-segments.json');old_meta=cache/(old_key.removeprefix('sha256:')+'-receipt.json')
        record=json.loads(old_meta.read_text())
        if record != {**record,'request_key':old_key,'runtime':runtime,'implementation_sha256':ss.IMPLEMENTATION_SHA256,'raw_result':receipt(old_raw)}:
            raise ValueError('Source checkpoint drift')
        proof={'schema_version':'net1-motor-label-replay-v1','source_plan':receipt(path),'target_plan':receipt(target_path),
               'source_checkpoint':receipt(old_meta),'source_raw':receipt(old_raw),'source_request':old_key,'target_request':new_key,
               'runtime':runtime,'implementation':ss.IMPLEMENTATION_SHA256,'radius_m':radius,
               'changed_labels':{k:v for k,v in mapping.items() if k!=v},
               'numeric_metrics_action':'UNCHANGED_VERIFIED_REPLAY','geometry_order_layers_site_unlinks':'EXACT_EQUAL'}
        proof_path=proof_dir/(path.stem+'-motor-replay.json')
        if proof_path.exists():raise ValueError('Proof exists; no overwrite')
        rows=json.loads(old_raw.read_text())
        for row in rows:
            source_id=row['source_line_id'];new_id=mapping[source_id]
            if not row['id'].startswith(source_id+'::pst-segment-'):raise ValueError('Unexpected PST segment identity')
            row['id']=new_id+row['id'][len(source_id):];row['source_line_id']=new_id
        raw=cache/(new_key.removeprefix('sha256:')+'-segments.json');meta=cache/(new_key.removeprefix('sha256:')+'-receipt.json')
        if raw.exists() or meta.exists():raise ValueError('Target checkpoint exists; reconcile')
        write(proof_path,proof);write(raw,rows)
        write(meta,{'request_key':new_key,'runtime':runtime,'implementation_sha256':ss.IMPLEMENTATION_SHA256,'raw_result':receipt(raw),'label_replay_proof':receipt(proof_path)})
        print(path.stem,'VERIFIED_LABEL_ONLY_REPLAY',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source-root',type=Path,required=True);parser.add_argument('--target-root',type=Path,required=True)
    parser.add_argument('--cache-dir',type=Path,required=True);parser.add_argument('--proof-dir',type=Path,required=True)
    args=parser.parse_args();run(args.source_root,args.target_root,args.cache_dir,args.proof_dir)
