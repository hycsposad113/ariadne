"""Offline recomputation of the canonical FAB1e delivery; never accepts designs."""
from pathlib import Path
import hashlib
import json
from PIL import Image
from shapely.geometry import shape
from urban_design.generation.fabric_plan import validate_plan, compare_plans

ROOT=Path('artifacts/fab1/run-5')
IDS=('harbour_grain','closed_block_extension','courtyard_islands','landscape_figure')
LABELS=('港埠線性紋理','圍合街廓延伸','大型院落島','地景為圖')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_new(name,value):
    path=ROOT/name
    content=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text()!=content:
        raise FileExistsError(f'拒絕覆寫既有驗證收據：{path}')
    if not path.exists():path.write_text(content)

def main():
    plans=[];rows=[];locations=[]
    sources={str(p):digest(p) for p in [Path('src/urban_design/generation/fabric_plan.py'),Path('src/urban_design/generation/fabric_finish_ne.py'),Path('src/urban_design/generation/fabric_finish_green.py'),Path('scripts/run_fabric_plan.py')]}
    for fid,label in zip(IDS,LABELS):
        p=json.loads((ROOT/f'{fid}-plan.json').read_text());saved=json.loads((ROOT/f'{fid}-checks.json').read_text());plans.append(p)
        recomputed=json.loads(json.dumps(validate_plan(p)))
        assert recomputed==saved['core_validator'], f'{fid} 重算與交付checks不相符'
        assert p['fab1_provenance']['core_source_sha256']==sources['src/urban_design/generation/fabric_plan.py']
        assert p['fab1_provenance']['runner_source_sha256']==sources['scripts/run_fabric_plan.py']
        checks=recomputed['checks'];before=json.loads(Path(f'artifacts/fab1/run-4/{fid}-checks.json').read_text())['core_validator']['checks']
        m=recomputed['metrics']
        rows.append({'方案':label,'方案代碼':fid,'整體狀態':recomputed['status'],'新建GFA_m2':m['new_gfa_m2'],'新FAR':m.get('new_far'),'GSI':m.get('gsi'),'FSI':m.get('fsi'),'新建量體數':m.get('new_building_count'),'街廓數':len(p['blocks']),'東北街廓數':checks['NORTHEAST_REGULAR_BLOCKS'].get('count'),'核心PASS':sum(c['passed'] for c in checks.values()),'核心總數':len(checks),'核心FAIL':recomputed['failure_ids'],'新增FAIL':[k for k,c in checks.items() if not c['passed'] and before.get(k,{}).get('passed')],'修復PASS':[k for k,c in checks.items() if c['passed'] and before.get(k,{}).get('passed') is False],'圖面檢查':saved['runner_checks'],'東北收尾':p.get('ne_finish_evidence',{}),'綠軸收尾':p.get('green_finish_evidence',[]),'臨街搬移':[r['building_id'] for r in p.get('public_frontage_alignment_attempts',[]) if r['status']=='MOVED']})
        lookup={r['id']:r['geometry'] for key in ('buildings','blocks','boundary_parcels','roads','land_use','courtyards') for r in p.get(key,[])}
        if p.get('south_quay_band'):lookup[p['south_quay_band']['id']]=p['south_quay_band']['geometry']
        for ident in recomputed['failure_ids']:
            c=checks[ident];found=False
            for loc in c.get('failure_locations',[]):
                g=loc.get('geometry') if isinstance(loc,dict) else lookup.get(loc) if isinstance(loc,str) else None
                if not g and isinstance(loc,dict):
                    g=next((lookup.get(loc[k]) for k in ('building_id','block_id','parcel_id','allocation_id','road_id') if loc.get(k) in lookup),None)
                if g:
                    locations.append({'type':'Feature','geometry':g,'properties':{'方案':label,'檢查':ident,'定位':'實際失敗圖徵','證據':loc}});found=True
            if not found:
                locations.append({'type':'Feature','geometry':c.get('zone_geometry') or c.get('frontage_geometry') or p['site'],'properties':{'方案':label,'檢查':ident,'定位':'檢查範圍；未提供個別圖徵','證據':c}})
    comparison=json.loads(json.dumps(compare_plans(plans)))
    assert comparison==json.loads((ROOT/'comparison.json').read_text())['comparison']
    old=json.loads((ROOT/'old-runs-sha256.json').read_text())
    drift=[name for name,h in old.items() if not Path(name).is_file() or digest(Path(name))!=h]
    images=[]
    for path in ROOT.glob('*.png'):
        with Image.open(path) as im:
            im.load();images.append({'檔案':path.name,'尺寸':list(im.size),'SHA256':digest(path)})
    facts=json.loads((ROOT/'inputs/site-facts.json').read_text())
    front=shape(plans[0]['south_quay_band']['properties']['frontage_geometry']);allowed=shape(facts['geometry']['buildable'])
    conflicts={'南岸立面線至凍結可建區最短距離_m':front.distance(allowed),'南岸立面線3m範圍與凍結可建區交集_m2':front.buffer(3.00001,cap_style=2).intersection(allowed).area,'判定':'run-4立面線與凍結可建區無3m可行交集，未改門檻或輸入。','院落東北數量':'本輪需求3–6；沿用run-4檢查1–2；兩者衝突，沒有放寬檢查。'}
    write_new('failure-locations-zh.geojson',{'type':'FeatureCollection','name':'第五輪全部失敗定位','crs':{'type':'name','properties':{'name':'EPSG:28992'}},'features':locations})
    large=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and p.stat().st_size>=5_000_000]
    report={'四案':rows,'比較重算相符':True,'六組比較':comparison,'輸入與幾何衝突':conflicts,'核心與runner雜湊相符':True,'執行程式SHA256':sources,'舊輪次檔案數':len(old),'舊輪次變更':drift,'PNG完整解碼':images,'單檔超限':large,'跨供應商審查':'未執行；本紀錄為Codex確定性重算，未代表Claude或Founder接受。'}
    write_new('independent-recompute-zh.json',report)
    print(json.dumps({k:report[k] for k in ('四案','輸入與幾何衝突','舊輪次變更','單檔超限')},ensure_ascii=False))
    if drift or large:return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
