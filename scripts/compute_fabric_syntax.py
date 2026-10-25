"""Run read-only FAB PST comparisons with compact workspace evidence."""
import argparse, hashlib, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shapely.geometry import shape
from urban_design import scenario_syntax as ss
from urban_design.fabric_syntax import proposal_roads, compact_result, positive_support_diff
from urban_design.generation.formal_multimodal import unlink_points
from urban_design.syntax_engines.pst_adapter import verify_runtime

FABRICS=('harbour_grain','courtyard_islands','landscape_figure','closed_block_extension')
def receipt(p): return {'path':str(p.resolve()),'sha256':'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()}
def write(p,value):
    # 原子發布避免 API 或其他計算讀到半份 JSON；既有證據仍由上層控制覆寫。
    pending=p.with_name(p.name+'.writing')
    pending.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
    pending.replace(p)
def cache_key(features, radius, unlinks, site, runtime, implementation):
    return ss.digest({'features':features,'radius':radius,'unlinks':unlinks,'site':ss.digest(site.__geo_interface__),'runtime':runtime,'implementation':implementation})

class ComputeCache:
    def __init__(self, compute, runtime, implementation, cache_dir=None):
        self.compute=compute; self.runtime=runtime; self.implementation=implementation; self.rows={}
        self.used_receipts=[]
        self.cache_dir=cache_dir
        if cache_dir is not None: cache_dir.mkdir(parents=True,exist_ok=True)
    def __call__(self, features, adapter, radius, unlinks, site):
        key=cache_key(features,radius,unlinks,site,self.runtime,self.implementation)
        if key not in self.rows:
            raw=meta=None
            if self.cache_dir is not None:
                raw=self.cache_dir/(key.removeprefix('sha256:')+'-segments.json')
                meta=self.cache_dir/(key.removeprefix('sha256:')+'-receipt.json')
            if meta is not None and meta.exists():
                record=json.loads(meta.read_text())
                if (record.get('request_key')!=key or record.get('runtime')!=self.runtime
                    or record.get('implementation_sha256')!=self.implementation
                    or record.get('raw_result')!=receipt(raw)):
                    raise ValueError('Persisted PST checkpoint receipt drift; reconcile before retry')
                if 'label_replay_proof' in record:
                    proof_ref=record['label_replay_proof'];proof_path=Path(proof_ref['path'])
                    if receipt(proof_path)!=proof_ref:raise ValueError('Label replay proof drift')
                    proof=json.loads(proof_path.read_text())
                    for ref in ('source_plan','target_plan','source_checkpoint','source_raw'):
                        if receipt(Path(proof[ref]['path']))!=proof[ref]:raise ValueError('Label replay source drift')
                    if proof['target_request']!=key:raise ValueError('Label replay request mismatch')
                self.rows[key]=json.loads(raw.read_text())
                self.used_receipts.append(receipt(meta))
                print(f'PST VERIFIED_CHECKPOINT {key}',flush=True)
            else:
                if raw is not None and raw.exists():
                    raise ValueError('PST checkpoint lacks receipt; reconcile before retry')
                self.rows[key]=self.compute(features,adapter,radius,unlinks,site)
                if raw is not None:
                    write(raw.with_suffix('.pending'),self.rows[key]);raw.with_suffix('.pending').rename(raw)
                    record={'request_key':key,'runtime':self.runtime,'implementation_sha256':self.implementation,'raw_result':receipt(raw)}
                    write(meta.with_suffix('.pending'),record);meta.with_suffix('.pending').rename(meta)
                    self.used_receipts.append(receipt(meta))
                    print(f'PST CHECKPOINT_SAVED {key}',flush=True)
        return [dict(row) for row in self.rows[key]]

def run(root, output, temp, resume=False, cache_dir=None, modes=None, positive_support=False):
    if (output/'syntax-summary.json').exists() and not resume:
        raise ValueError('Evidence output already exists; choose a new --output directory')
    if temp.exists() and any(temp.iterdir()) and not resume:
        raise ValueError('Intermediate evidence already exists; choose a new --temp directory')
    output.mkdir(parents=True,exist_ok=True);temp.mkdir(parents=True,exist_ok=True)
    verify_runtime(ss.DEFAULT_PST_MANIFEST)
    runtime_receipt=receipt(ss.DEFAULT_PST_MANIFEST)
    original_compute=ss._compute
    original_diff=ss.segment_diff
    if positive_support:
        # The helper calls the unchanged INT3 diff for substantial rows.
        # Bind its module-level reference to the original to avoid recursion.
        def bounded_diff(before, after, epsilon=1e-6):
            ss.segment_diff=original_diff
            try: return positive_support_diff(before,after,epsilon)
            finally: ss.segment_diff=bounded_diff
        ss.segment_diff=bounded_diff
    cached_compute=ComputeCache(original_compute,runtime_receipt,ss.IMPLEMENTATION_SHA256,cache_dir or temp/'verified-compute-cache')
    cache=cached_compute.rows
    ss._compute=cached_compute
    try:
        docs={};refs={};external={};rows=[]
        for mode in ss.MODES:
            try:
                docs[mode],refs[mode]=ss.verified_extract(mode);external[mode]=docs[mode]['network']['features']
            except Exception as exc: refs[mode]={'error':str(exc)}
        summary={'schema_version':'fabric-syntax-summary-v1','status':'INCOMPLETE','expected_count':12,'computed_count':0,'results':rows,'formal_result_eligible':False,'created_utc':datetime.now(timezone.utc).isoformat()}
        for fabric in FABRICS:
            path=root/(fabric+'-plan.json');plan=json.loads(path.read_text());site=shape(plan['site'])
            try:
                if len(external)!=3: raise ValueError('BLOCKED: one or more verified mode extracts unavailable')
                roads=[]
                error=None
            except Exception as exc: roads=[];error=str(exc)
            for mode in ss.MODES:
                prior=output/(fabric+'-'+mode+'.json')
                if modes is not None and mode not in modes:
                    if prior.exists():
                        row=json.loads(prior.read_text())
                        if row.get('status')=='COMPUTED':
                            for record in (row['source_receipts']['plan'],row['complete_intermediate'],row['retained_road_receipts']):
                                if receipt(Path(record['path'])) != record: raise ValueError('Excluded-mode result receipt drift')
                            if row['source_receipts']['extract'] != refs[mode]: raise ValueError('Excluded-mode extraction drift')
                        rows.append(row)
                    continue
                if resume and prior.exists():
                    row=json.loads(prior.read_text())
                    if row.get('status')=='COMPUTED':
                        for record in (row['source_receipts']['plan'],row['complete_intermediate'],row['retained_road_receipts']):
                            if receipt(Path(record['path'])) != record: raise ValueError('Existing result receipt drift')
                        if row['source_receipts']['extract'] != refs[mode]: raise ValueError('Existing extraction receipt drift')
                        full_result=json.loads(Path(row['complete_intermediate']['path']).read_text())
                        current_roads=proposal_roads(plan,external,mode=mode)
                        expected={'road_input_sha256':ss.digest([r.model_dump() for r in current_roads]),'parameters':ss.MergeParameters(snap_tolerance_m=0).model_dump(),'network_input_sha256':ss.digest(external[mode]),'unlinks_sha256':ss.digest(unlink_points(docs[mode]['unlinks'])),'site_sha256':ss.digest(site.__geo_interface__),'radius_m':ss.MODES[mode][1],'implementation_sha256':ss.IMPLEMENTATION_SHA256,'formula_version':'pstalgo-3.3.1-walking-radius-v1'}
                        if any(full_result.get(k)!=v for k,v in expected.items()): raise ValueError('Existing baseline request drift')
                        key=cache_key(external[mode],ss.MODES[mode][1],unlink_points(docs[mode]['unlinks']),site,runtime_receipt,ss.IMPLEMENTATION_SHA256)
                        cache[key]=full_result['before']['segments']
                        rows.append(row)
                        print(f'{fabric} {mode} VERIFIED_EXISTING',flush=True)
                        continue
                print(f'{fabric} {mode} START',flush=True)
                try:
                    if error: raise ValueError(error)
                    road_receipts=[]
                    roads=proposal_roads(plan,external,mode=mode,receipts=road_receipts)
                    write(output/(fabric+'-'+mode+'-road-receipts.json'),road_receipts)
                    result=ss.compare_syntax(external[mode],roads,site,mode,parameters=ss.MergeParameters(snap_tolerance_m=0),unlinks=unlink_points(docs[mode]['unlinks']))
                    if positive_support:
                        result['diff_postprocessor']={'version':'net1-positive-support-v1','source':receipt(Path(__file__).resolve().parents[1]/'src/urban_design/fabric_syntax.py'),'scope':'No PST metric/topology changes; <=1e-6m support keeps null baseline/delta'}
                    result['pst_checkpoint_receipts']=list(cached_compute.used_receipts)
                    full=temp/(fabric+'-'+mode+'-full.json');write(full,result)
                    row=compact_result(result,site,roads);row['complete_intermediate']=receipt(full)
                    row['retained_road_receipts']=receipt(output/(fabric+'-'+mode+'-road-receipts.json'))
                except Exception as exc:
                    row={'status':'BLOCKED','error':str(exc),'mode':mode,'before':None,'after':None,'new_street_ranking':[],'delta_mean_integration_nain':None,'parameters':ss.MergeParameters(snap_tolerance_m=0).model_dump(),'radius_m':ss.MODES[mode][1],'extract_buffer_m':ss.MODES[mode][0]}
                row.update(fabric_id=fabric,source_receipts={'plan':receipt(path),'extract':refs.get(mode)},formal_result_eligible=False)
                if row['status']=='BLOCKED':
                    row['error_zh']='保留道路超出已核准的 1 mm 來源比對容差，請核對道路對應與裁切範圍。' if 'retained geometry mismatch' in row.get('error','') else '軸線分析未完成，請查閱來源與錯誤診斷。'
                write(output/(fabric+'-'+mode+'.json'),row);rows.append(row)
                summary['computed_count']=sum(r['status']=='COMPUTED' for r in rows)
                summary['status']='COMPUTED' if summary['computed_count']==12 else 'INCOMPLETE'
                write(output/'syntax-summary.json',summary)
                print(f'{fabric} {mode} {row["status"]} {row.get("error","")}',flush=True)
        summary['computed_count']=sum(r['status']=='COMPUTED' for r in rows)
        summary['status']='COMPUTED' if summary['computed_count']==12 else 'INCOMPLETE'
        write(output/'syntax-summary.json',summary)
        return summary
    finally:
        ss._compute=original_compute
        ss.segment_diff=original_diff
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('artifacts/fab1/run-5'));p.add_argument('--output',type=Path,default=Path('artifacts/int1b/syntax'));p.add_argument('--temp',type=Path,default=Path('/private/tmp/int1b-fabric-syntax'))
    p.add_argument('--resume',action='store_true')
    p.add_argument('--cache-dir',type=Path,help='Reuse only request/runtime/implementation/hash verified PST checkpoints; full outputs still use --temp')
    p.add_argument('--modes',nargs='+',choices=tuple(ss.MODES),help='Bounded staged calculation; summary stays INCOMPLETE until all 12 exist')
    p.add_argument('--positive-support-diff',action='store_true',help='NET1 only: preserve null delta for sub-epsilon support instead of zero division')
    a=p.parse_args();r=run(a.root,a.output,a.temp,a.resume,a.cache_dir,a.modes,a.positive_support_diff);sys.exit(0 if r['status']=='COMPUTED' else 2)
