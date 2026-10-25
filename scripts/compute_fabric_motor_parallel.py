"""Compute one disjoint motor after-network, then assemble verified PST evidence."""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shapely.geometry import shape
from urban_design import scenario_syntax as ss
from urban_design.fabric_syntax import proposal_roads, compact_result
from urban_design.generation.formal_multimodal import unlink_points
from urban_design.syntax_engines.pst_adapter import verify_runtime
from compute_fabric_syntax import cache_key, receipt, write

def run(fabric, root=Path('artifacts/fab1/run-5'), output=Path('artifacts/int1b/syntax'), temp=Path('/private/tmp/int1b-fabric-syntax'), cache_dir=None):
    mode='motor_vehicle'
    temp.mkdir(parents=True,exist_ok=True)
    raw_path=temp/(fabric+'-motor-after-raw.json'); metadata_path=temp/(fabric+'-motor-after-cache-receipt.json')
    if raw_path.exists() or metadata_path.exists(): raise ValueError('Never overwrite raw evidence; reconcile first')
    docs,source=ss.verified_extract(mode); features=docs['network']['features']; unlinks=unlink_points(docs['unlinks'])
    plan_path=root/(fabric+'-plan.json'); plan=json.loads(plan_path.read_text()); site=shape(plan['site']); receipts=[]
    roads=proposal_roads(plan,{m:ss.verified_extract(m)[0]['network']['features'] for m in ss.MODES},mode=mode,receipts=receipts)
    parameters=ss.MergeParameters(snap_tolerance_m=0); merged=ss.merge_network(features,roads,site,mode,parameters,unlinks)
    if merged['status']!='READY': raise ValueError(merged['reason'])
    radius=ss.MODES[mode][1]; after_unlinks=tuple(sorted(set(tuple(p) for p in unlinks)|set(merged['derived_unlinks'])))
    verify_runtime(ss.DEFAULT_PST_MANIFEST); runtime=receipt(ss.DEFAULT_PST_MANIFEST)
    key=cache_key(merged['features'],radius,after_unlinks,site,runtime,ss.IMPLEMENTATION_SHA256)
    print(f'{fabric} AFTER PST START key={key}',flush=True); started=time.perf_counter()
    rows=ss._compute(merged['features'],ss.PSTAdapter(manifest_path=ss.DEFAULT_PST_MANIFEST),radius,after_unlinks,site)
    elapsed=time.perf_counter()-started; write(raw_path,rows)
    meta={'schema_version':'fabric-syntax-request-cache-v1','request_key':key,'runtime':runtime,'implementation_sha256':ss.IMPLEMENTATION_SHA256,'raw_result':receipt(raw_path),'source_receipts':{'plan':receipt(plan_path),'extract':source},'network_input_sha256':ss.digest(merged['features']),'unlinks_sha256':ss.digest(after_unlinks),'site_sha256':ss.digest(site.__geo_interface__),'radius_m':radius,'radius_mode':'walking','parameters':parameters.model_dump(),'runtime_seconds':elapsed}
    write(metadata_path,meta); print(f'{fabric} AFTER PST COMPLETE {elapsed:.2f}s; awaiting verified common baseline',flush=True)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True,exist_ok=True)
        raw=cache_dir/(key.removeprefix('sha256:')+'-segments.json')
        record=cache_dir/(key.removeprefix('sha256:')+'-receipt.json')
        if raw.exists() or record.exists(): raise ValueError('Concurrent cache entry; reconcile instead of overwrite')
        write(raw,rows)
        write(record,{'request_key':key,'runtime':runtime,'implementation_sha256':ss.IMPLEMENTATION_SHA256,'raw_result':receipt(raw)})
        print(f'{fabric} VERIFIED_CACHE_READY {key}',flush=True)
        return
    baseline_row_path=output/'harbour_grain-motor_vehicle.json'
    while not baseline_row_path.exists(): time.sleep(2)
    baseline_row=json.loads(baseline_row_path.read_text())
    if baseline_row.get('status')!='COMPUTED': raise ValueError('Common baseline unavailable')
    baseline_receipt=baseline_row['complete_intermediate']
    if receipt(Path(baseline_receipt['path']))!=baseline_receipt: raise ValueError('Baseline full receipt drift')
    if baseline_row['source_receipts']['extract']!=source: raise ValueError('Baseline extraction/runtime receipt drift')
    baseline=json.loads(Path(baseline_receipt['path']).read_text()); expected={'network_input_sha256':ss.digest(features),'unlinks_sha256':ss.digest(unlinks),'site_sha256':ss.digest(site.__geo_interface__),'radius_m':radius,'formula_version':'pstalgo-3.3.1-walking-radius-v1','implementation_sha256':ss.IMPLEMENTATION_SHA256}
    if any(baseline.get(k)!=v for k,v in expected.items()): raise ValueError('Baseline request drift')
    before=baseline['before']['segments']; del baseline
    if receipt(raw_path)!=meta['raw_result'] or receipt(ss.DEFAULT_PST_MANIFEST)!=runtime: raise ValueError('After/runtime receipt drift')
    before_key=cache_key(features,radius,unlinks,site,runtime,ss.IMPLEMENTATION_SHA256)
    original=ss._compute
    def cached(features,adapter,radius,unlinks,site):
        requested=cache_key(features,radius,unlinks,site,runtime,ss.IMPLEMENTATION_SHA256)
        if requested==before_key: return [dict(row) for row in before]
        if requested==key: return [dict(row) for row in rows]
        raise ValueError('Unexpected request; no unverified cache fallback')
    ss._compute=cached
    result=ss.compare_syntax(features,roads,site,mode,parameters=parameters,unlinks=unlinks);ss._compute=original
    result['baseline_cache_receipt']=baseline_receipt; result['after_cache_receipt']=receipt(metadata_path)
    result['after_seconds_actual_pst']=elapsed; full=temp/(fabric+'-'+mode+'-full.json')
    if full.exists(): raise ValueError('Concurrent full output exists; do not overwrite')
    write(full,result);road_path=output/(fabric+'-'+mode+'-road-receipts.json');write(road_path,receipts)
    row=compact_result(result,site,roads);row.update(fabric_id=fabric,complete_intermediate=receipt(full),retained_road_receipts=receipt(road_path),source_receipts={'plan':receipt(plan_path),'extract':source},formal_result_eligible=False)
    target=output/(fabric+'-'+mode+'.json')
    if target.exists(): raise ValueError('Concurrent compact output exists; do not overwrite')
    staging=target.with_suffix('.pending');write(staging,row);staging.rename(target)
    print(f'{fabric} COMPUTED {len(rows)} after segments',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fabric',required=True,choices=('courtyard_islands','landscape_figure','closed_block_extension'))
    p.add_argument('--root',type=Path,default=Path('artifacts/fab1/run-5'));p.add_argument('--output',type=Path,default=Path('artifacts/int1b/syntax'))
    p.add_argument('--temp',type=Path,default=Path('/private/tmp/int1b-fabric-syntax'));p.add_argument('--cache-dir',type=Path)
    a=p.parse_args();run(a.fabric,a.root,a.output,a.temp,a.cache_dir)
