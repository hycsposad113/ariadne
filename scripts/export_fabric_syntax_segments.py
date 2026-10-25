"""Publish deterministic INT3 visualization exports without recomputing PST."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from urban_design.fabric_syntax_segments import build,receipt
root=Path(__file__).resolve().parents[1];source=root/'artifacts/int1b/syntax';out=source/'segments';out.mkdir(exist_ok=True);reports=[]
for p in sorted(source.glob('*.json')):
    if p.name.endswith('road-receipts.json') or p.name=='syntax-summary.json':continue
    result,report=build(p);dest=(out/p.name).with_suffix(".geojson");data=json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    if len(data.encode())>=5_000_000:raise ValueError('BLOCKED: compact export exceeds 5 MB')
    dest.write_text(data);dest.with_suffix('.receipt.json').write_text(json.dumps({'export':receipt(dest),'size_bytes':dest.stat().st_size},indent=2));reports.append(report)
    print(p.stem,len(result['features']),dest.stat().st_size,flush=True)
reportdir=root/'artifacts/int3';reportdir.mkdir(exist_ok=True);(reportdir/'intent-assessment.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2,allow_nan=False))
lines=['# INT3 解釋性軸線分析','', '描述性專案示例判準：完整 after 網絡 NAIN 百分位 ≥80 符合、60–80 部分符合、<60 未符合。按場址內長度加權；不是已核准設計限制，也不預測人流。幾何變動的 before/delta 保留 null。Keileweg / Dakpark 必須同時有合併 receipt 接點與存續的同運具路段，才納入直接銜接街道評分；間接路徑及實際通行量未評估。','', '|方案 Fabric|模式 Mode|主要街道 Primary street|水岸路徑 Waterfront path|水岸繞行 Detour|Keileweg|Dakpark|','|---|---|---|---|---|---|---|']
for r in reports:lines.append('|'+ '|'.join([r['fabric_id'],r['mode']]+[{'meets':'符合','partial':'部分符合','not met':'不符合','unavailable':'無資料','unproven':'未證實'}[i['status']]+(' '+format(i['percentile'],'.1f')+'%' if i.get('percentile') is not None else '') for i in r['intents']])+'|')
lines+=['','全部道路、前後值、排名和既有道路變化的具名 segment 詳見 intent-assessment.json。匯出範圍為場址 +1000m、EPSG:28992、裁切後簡化 1m，圖例沿用 Site 五分位演算法，固定 1000m 原始路網分級；完整運算原級距另存 metadata。來源、完整運算、方案、OSM network 與道路 receipt 均核驗 SHA256；端點每次重新核驗，漂移回傳 503。']
(reportdir/'intent-table-zh.md').write_text('\n'.join(lines)+'\n')
