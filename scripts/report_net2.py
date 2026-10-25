"""Generate Chinese NET2 handoff from retained measurements and command evidence."""
import argparse
import json
from pathlib import Path

NAMES={'closed_block_extension':'圍合周邊式','courtyard_islands':'院落大島','harbour_grain':'港埠長條','landscape_figure':'地景綠軸'}
MODES={'pedestrian':'步行','bicycle':'自行車','motor_vehicle':'汽車'}
def number(v):return '—' if v is None else f'{v:.2f}'
def load(p):return json.loads(p.read_text())
def run(output,final_round):
 root=Path('artifacts/net2'); audit=load(root/'delivery-verification-v2.json'); commands=load(root/'command-results.json')
 final=root/f'round-{final_round}'
 reports={n:load(root/f'round-{n}'/'net2-assessment.json')['reports'] for n in (1,2,3) if (root/f'round-{n}'/'net2-assessment.json').exists()}
 baseline=next((r['net2_assessment']['baselines'] for r in reports.get(final_round,[]) if r['net2_assessment']['mode']=='pedestrian' and r['net2_assessment'].get('baselines')),None)
 lines=['# NET2：主街骨幹重排與失敗報告','', '**狀態：未完成；三輪上限內保留全部結果，不降低新判準，不宣告優勝或正式接受。**','',
 '分支 `wp/dl-quickfix`，起點 `0a939db`。產物為 `artifacts/fab1/run-7/`，API 預設 `net2` profile 對應本次最終語法目錄；舊 `net1`、`run5-int1b` 可用 `URBAN_DESIGN_FABRIC_SOURCE` 切回。沒有變動正式 DB、既有服務、8787／8644／8795／5195，沒有部署、下載、安裝、push、reset、clean、checkout 或刪檔。瀏覽器演練及跨 provider 獨立審查仍由指揮官執行。','',
 '執行標記依使用者要求為 Codex gpt-6.1-sol medium；有界子任務依 Founder 2026-09-30 路由為 gpt-6.1-sol low（幾何重排、證據語義、跨層整合）。未將標記冒充已驗證的根代理 runtime metadata。','',
 '## 實測基準與方法','',
 '主街符合門檻為各運具 before 中具名 Vierhavensstraat 的 NAIN 百分位，優門檻為 Keileweg。具名道路先按每個 before segment 的實際線長加權 NAIN，再在完整同運具 before segment 母體求右含 empirical CDF；沒有把 Founder 約略數值寫死。基準包含凍結網絡內同名路段全長，與指揮官先前約 53／85 的取樣範圍或聚合方式可能不同；本報告揭露結果，不為吻合約值調數字。','',
 '方案值維持每條道路基地內長度加權 NAIN→完整 after 網絡百分位→角色組街長加權的聚合順序，但 NET2 另驗完整實體道路支持，包含與既有 Keileweg 重合的區段。原 INT3 僅新路剩餘部分的歸屬值另列診斷，不冒充整條主街；完整支持缺口超過0.001m或同位置NAIN衝突時，正式值為未證實。平行支持採既有0.001m來源容差，垂交點不計、同值重複去重、異值拒絕。比較的是各自完整網絡的相對名次，不把 after 值改對 before CDF 排名、不只挑最好一段。NAIN 是模型整合度，不能推論實際人流。','',
 '|運具|符合：Vierhavensstraat|優：Keileweg|具名道路樣本數（符合／優）|before 母體段數|','|---|---:|---:|---:|---:|']
 for mode in ('pedestrian','bicycle','motor_vehicle'):
  b=next((r['net2_assessment'].get('baselines') for r in reports.get(final_round,[]) if r['net2_assessment']['mode']==mode and r['net2_assessment'].get('baselines')),None)
  if not b:continue
  a,e=b['primary_meets'],b['primary_excellent']
  lines.append(f"|{MODES[mode]}|{number(a['percentile'])}%|{number(e['percentile'])}%|{a['sample_count']}／{e['sample_count']}|{a['population_count']}|")
 lines+=['', '汽車基準只供描述，沒有新增汽車整合度通過門檻。逐 segment 百分位長加權的替代聚合另保存在每輪 JSON 與 [基準診斷](baseline-diagnostic.json)，沒有取代主法。','',
 '水岸正式門檻應取距基地 ≤1,500 m、距水域 ≤20 m 的 OSM 步行 before segments 百分位中位數（不按長度加權）。現有水域取得範圍僅能證明 1,200 m，無完整 1,500 m（及 20 m 距水搜尋外緣）覆蓋證據；禁止下載下沒有補來源，因此正式門檻為 **UNAVAILABLE／未證實**。保留的 1,200 m 診斷有 797 段、中位數 42.16%，明示不是 NET2 門檻，沒有用它代替正式標準。','',
 '## 每輪四案 × 三運具','', 'K／D 是嚴格 INT3 合併 receipt、存續同運具 after 路段與 unlink 排除後的接點道路數。NET2 要求保留接點，故可計入仍存在的 NET1 道路，不把資料缺失填零。水岸接點數是未簡化線段實際點交；每條橫街／主街的額外幾何檢查另列於 delivery-verification-v2.json。']
 for n,records in reports.items():
  lines+=['',f'### 第 {n} 輪','',f'[完整結果與 receipts](round-{n}/net2-assessment.json) · [逐目標表](round-{n}/net2-table-zh.md)','', '|方案|運具|全主街百分位|局部 INT3 診斷|符合門檻|主街判定|水岸百分位|K／D 接點|水岸接點|整體檢核|','|---|---|---:|---:|---:|---|---:|---|---:|---|']
  for record in records:
   a=record['net2_assessment'];checks={c['target']:c for c in a['checks']};intents={c['intent_en']:c for c in a.get('descriptive_intents',[])}
   p=checks.get('primary_street',{});w=checks.get('waterfront_path',{});pv=p.get('value',intents.get('primary_street',{}).get('percentile'));wv=w.get('value',intents.get('waterfront_path',{}).get('percentile'))
   k=checks.get('connection Keileweg',{}).get('value');d=checks.get('connection Dakpark',{}).get('value');joins=checks.get('waterfront multiple joins',{}).get('value')
   name=NAMES.get(a['fabric_id'].removeprefix('fabric.'),a['fabric_id'])
   lines.append('|'+ '|'.join([name,MODES[a['mode']],number(pv),number(p.get('diagnostic_int3_percentile',intents.get('primary_street',{}).get('percentile'))),number(p.get('minimum')),p.get('grade') or p.get('status','僅描述'),number(wv),number(k)+'／'+number(d),number(joins),a['status']])+'|')
 lines+=['','## 幾何、容量與維持條件','', '土地配置、尺度、消防、連通及差異仍使用原始共用 validators；新增顯式五層檢核，因原始地景案六層／20 m 不符合本次「最多五層」。精確 GFA 下限為 146,873 × 90% = 132,185.7 m²；原 validator 使用 132,186 m²，沒有放寬。','', '|輪次|方案|新建 GFA m²|目標比|最高樓層|最高高度 m|未配置 m²|原檢核|','|---|---|---:|---:|---:|---:|---:|---|']
 for roundrow in audit['rounds']:
  for p in roundrow['plans']:
   lines.append('|'+ '|'.join(map(str,[roundrow['round'],NAMES[p['fabric_id'].removeprefix('fabric.')],number(p['new_gfa_m2']),number(p['new_gfa_percent'])+'%',p['max_floors'],number(p['max_height_m']),number(p['unallocated_m2']),p['stored_validation_status']]))+'|')
 lines+=['', '第二輪院落島實例：完整主街920.97m、PST實體支持793.55m、缺127.42m並有NAIN衝突；水岸1850.82m、支持750.67m。這些是完整支持不足，不能直接用局部INT3數字6.68%或4.76%判整條路失敗或通過，正式評分為UNAVAILABLE。詳見 [支持診斷](physical-support-diagnostic.json)。各輪所有失敗（包含既有失敗及本次新增失敗）與逐項維持條件見 [幾何／來源稽核](delivery-verification-v2.json)。以下列最終輪明確失敗；通過軟體測試不代表方案通過。']
 final_audit=next(r for r in audit['rounds'] if r['round']==final_round)
 for p in final_audit['plans']:
  lines+=['',f"### {NAMES[p['fabric_id'].removeprefix('fabric.')]}：未達標項目",'', '`'+'`、`'.join(p['failure_ids'])+'`。',
           f"GFA：{number(p['new_gfa_m2'])} m²／{number(p['new_gfa_percent'])}%，五層與高度：{'通過' if p['five_floor_height_pass'] else '失敗'}；NET1 原幾何完整保留：{'是' if p['net1_preservation']['all_exact'] else '否'}；每條橫街與主街到水岸皆有陸地內淨寬連線：{'是' if p['waterfront_all_transverse_and_primary_pass'] else '未全數通過'}。"]
  links=p.get('network_connection_diagnostics',{}).get('failed_links',[])
  if links:
   lines+=['','直接連線未完成：']
   for link in links:lines.append(f"- `{link.get('id','?')}`／`{link.get('kind','?')}`：{link.get('reason','未證實')}")
  capacity=p.get('capacity_search') or {}
  if capacity:
   lines+=['',f"本輪有界容量搜尋新增 {len(capacity.get('added_buildings',[]))} 棟／翼，距原 validator 下限仍差 {number(capacity.get('remaining_target_deficit_m2'))} m²。拒絕候選計數：`{json.dumps(capacity.get('rejected_candidate_counts',{}),ensure_ascii=False)}`。這只證明本輪指定模板與網格步距的搜尋結果，不代表其他重新佈局不可能達標。"]
 comp=final_audit['comparison'];lines+=['',f"最終四案兩兩差異：{comp['distinct_pair_count']}/6，狀態 {comp['status']}。未制定總排名規則，沒有選出優勝案。",'',
 '失敗原因須對照 checks 內的實際幾何與數量：保留建築、18 m 主街預留、原 NET1 接點與全幅水岸共同限制可建空間；完整保留接點也可能造成新配置的路網斷裂或路幅預算超限。未達容量、尺度、道路／水岸預算或連通的方案均未通過；不把街道名次改善當成幾何合格。凍結自行車網缺少具名 Dakpark 目標，保留假設路徑仍不能宣稱同運具接點已證實。橋梁維持 ASSUMED_BRIDGE，標高、結構與通行權仍未驗證。','',
 '## 中文前後對照圖','',f'全部使用 EPSG:28992、相同視域與比例；左為 NET1 run-6，右為最終 NET2 第 {final_round} 輪。圖只顯示實際產出幾何，不補造基地模型。']
 for f,name in NAMES.items():lines+=['',f'### {name}','',f'![{name}街廓調整前後](round-{final_round}/figures/{f}-before-after-zh.png)']
 lines+=['','## 測試與交接','', '|命令／檢查|實測結果|證據|','|---|---|---|']
 for c in commands['commands']:lines.append(f"|{c['command']}|{c['result']}|[{c['log']}]({c['log']})|")
 lines+=['',f"原 [v1核驗](delivery-verification.json) 的完整相等欄位曾以Python tuple與JSON list直接比較而為false；單案重驗證實JSON語義相同，已加數值差異仍會失敗的回歸測試並用新v2核驗。四案v2完整序列化驗證均與凍結結果一致。舊 run-5／run-6／NET1 雜湊漂移：{len(audit['old_input_hash_drift'])}；新產物 ≥5,000,000 bytes 檔案：{len(audit['oversize_files'])}。大小使用 stat 的精確 bytes 比較，沒有使用 find -size -5M。",'',
 '大型完整 PST 中間檔與 verified cache 留在 `/private/tmp/net2-*`；共用已核驗 checkpoint 位於 `/private/tmp/net1-round-1/verified-compute-cache`。receipt 指向它們，需保留以供指揮官驗證；只複製 worktree 不能重現完整證據鏈。第一輪原始實驗 adapter 未留原始碼快照，已在 geometry-source receipt 揭露，不能宣稱以目前 --round 1 重現完全相同 bytes。第二／三輪來源快照另存。','',
 '指揮官下一步：核對 run-7 與最終 round 來源／receipts，獨立跨 provider 審查，依已更新 e2e 在另行授權的 runtime 執行雙語瀏覽器演練。需完整 1,500 m 水域來源與新的 Founder 授權，才可能補算水岸正式基準；本次不超過三輪、不新增下載，也不記錄方案接受決策。']
 data='\n'.join(lines)+'\n'
 with output.open('x') as stream:stream.write(data)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--final-round',type=int,required=True);a=p.parse_args();run(a.output,a.final_round)
