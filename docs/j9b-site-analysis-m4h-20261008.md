# J9b M4H 基本基地分析實測（2026-10-08）

報告生成 UTC：`2026-10-08T03:59:29Z`。資料抓取／運算時間均由 `date -u` 取得。

**狀態：探索性實算完成，整體驗收 INCOMPLETE（瀏覽器核准拒絕、D1 全套測試阻擋、Claude 跨供應商審查未完成）。**

正式 DB 僅 mode=ro；使用 sqlite backup API 產生 `/private/tmp/` 副本。沒有建立 HumanDecision、讀取正式金鑰、變更 active StudyArea、重啟或連接禁止的服務。

- StudyArea：`study-area-rotterdam-m4h-pilot-project-v5`／`v5`；粗範圍：`extent-22e0fcda05157bda63cf17d0d15d8bed`。
- 實算：`2026-10-08T03:54:53Z` → `2026-10-08T03:56:35Z`，102.339 秒；FastAPI TestClient HTTP 200。
- 正式 ledger：304／304 → 304／304；分析副本 ledger：552 → 552。
- 步行圖 323,105 節點／362,123 邊；入口候選 15；基地外來源 48,753，其中 773 未能在 30 m 內接上路網。

## 各側最近站點與步行距離

方位是基地 centroid 的 N/E/S/W 分區；每側取該側所有路網邊界交點到站點的最小步行路徑，不是四條直線。距離含明列的假設接線，單位 m。

| 方位 | 公車 | 地鐵 | 電車 | 鐵路 | 渡輪／水上計程車 |
|---|---|---|---|---|---|
| N | Rotterdam, Van Helmontstraat：64.66 | Marconiplein：328.37 | Marconiplein：360.26 | Schiedam Centrum：2491.92 | Watertaxi - Marconistraat / M4H：802.29 |
| E | Rotterdam, Van Helmontstraat：105.64 | Marconiplein：369.36 | Marconiplein：401.25 | Schiedam Centrum：2532.91 | Watertaxi - Marconistraat / M4H：1039.16 |
| S | 缺值（不連通／無入口） | 缺值（不連通／無入口） | 缺值（不連通／無入口） | 缺值（不連通／無入口） | 缺值（不連通／無入口） |
| W | Rotterdam, Van Helmontstraat：743.69 | Marconiplein：1007.41 | Marconiplein：1039.29 | Schiedam Centrum：3016.72 | Watertaxi - Marconistraat / M4H：959.42 |

最接近大眾運輸的方位：**N**。南側沒有此路網能驗證連通的邊界入口，不能宣稱南側沒有交通設施或行人。

最近 metro 的 OSM route metadata 保留 Metro A/B/C 名稱及方向；這是路線標籤，沒有 GTFS 班次、營運中確認或人數。

## 基地外 0–500 m 方位土地使用

BAG 分母是有效記錄的樓地板面積；OSM 是 polygon 面積佔該扇區環帶的比例。兩者不是相同量，不能混成單一土地使用百分比。

| 方位 | BAG 樓地板面積 m² | BAG 主要用途 | OSM landuse 主要面積比例 | 缺面積物件數 |
|---|---:|---|---|---:|
| N | 345,907.00 | 住宅 37.49%, 工業 20.63%, 其他用途 15.82%, 教育 12.68% | industrial 55.37%, residential 26.88%, grass 10.41% | 0 |
| E | 283,586.00 | 住宅 54.01%, 工業 16.98%, 商業 14.23%, 其他用途 7.34% | industrial 41.17%, residential 39.02%, grass 11.40% | 0 |
| S | 27,308.00 | 工業 100.00% | industrial 28.69%, grass 0.12% | 0 |
| W | 34,996.00 | 工業 56.34%, 教育 29.88%, 辦公 13.79% | industrial 87.80%, grass 2.74%, brownfield 0.04% | 0 |

東側 BAG 用途以住宅為主；西側以工業為主。北側 BAG 住宅樓地板較多，OSM 卻仍有較大的工業用地面積；這反映樓地板與地面 polygon 的分母不同，不能視為資料互相否定。南側的 BAG 工業 100% 只涵蓋有記錄用途面積的物件，不表示整個扇區都是工業。

## 推估到達潛力與主要路線

規則為 `sum(weight × exp(-walking_distance_m / 800))`，權重全為 ASSUMED_COMMANDER，詳見 [方法契約](j9b-site-analysis-contract.md)。不是觀測人流、旅次、人／時、人口或最佳方案的判斷。

| 排序 | 入口 | 方位 | 相對距離到達潛力 | 可達來源數 | 最大單一路徑貢獻來源 |
|---:|---|---|---:|---:|---|
| 1 | entrance-15 | N | 2284.966470 | 46821 | Marconiplein |
| 2 | entrance-14 | N | 2274.831097 | 46821 | Marconiplein |
| 3 | entrance-13 | E | 2200.803165 | 46821 | Marconiplein |
| 4 | entrance-11 | E | 1897.297694 | 46821 | Marconiplein |
| 5 | entrance-10 | E | 1866.296302 | 46821 | Marconiplein |

主要到達潛力集中在北側，其後為東側。第一名 `entrance-15` 最大單一路線貢獻來自 `Marconiplein`，步行 328.37 m（假設接線 8.49 m）。完整最短路徑與每入口前三條主要路線保留在 `m4h-result.json`／`m4h-overlay.geojson`。

該主要路線疊到既有 800 m Syntax：覆蓋率 97.42%，matched NAIN=0.815336、NACH=1.223895。原資料 readiness 仍是 `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`，沒有改成 PASS。

此版入口總排序只使用全部來源的距離潛力，Syntax 疊加主要路徑而不推造全來源校正分數；`syntax_adjusted_potential=null`。欲以 Syntax 改變入口總排序仍需後續明確方法與 coverage 驗證。

## 逐來源抓取與快照

2026-10-08 一次新的公開資料查詢已成功收到原始 bytes；首次 OSM 解析失敗，原因是非 landuse／建物的觀光船閉合折線誤觸 polygon validator。修正後兩次使用同一批 hash 驗證的 bytes 離線重播，最終 replay HTTP 次數為 0，未重送來源請求。

| 來源 | 最終狀態 | 筆數／圖層合計 | bytes | 原始 live 耗時 s | 最終 replay 耗時 s |
|---|---|---:|---:|---:|---:|
| OSM | DONE | 131211 | 96,951,703 | 22.64 | 29.783 |
| PDOK BAG | DONE | 2307 | 1,896,307 | 1.447 | 0.222 |
| PDOK BAG verblijfsobject | DONE | 45819 | 35,065,804 | 28.756 | 6.994 |
| 3D BAG | DONE | 2178 | 10,556,608 | 2.467 | 1.343 |
| Public planning | DONE | null | 476,859 | 0.508 | 0.106 |
| ruimtelijkeplannen.nl / DSO keyed APIs | BLOCKED_NEEDS_KEY | null | 0 | 0 | 0 |

OSM normalized 分層合計包含交通站點 365、POI 2670；多種角色可能共用 OSM identity，合計不是唯一物件數。最終 extent 登記 61 個 raw DatasetSnapshot，manifest／raw response／derived files 均有 hash。

## 與舊 surrounding context 比對

共同比較範圍：粗範圍 +500 m。新 BAG footprints 2307 vs 舊 OSM footprints 2284，差 23；舊資料不是 BAG pand 快照，所以不能宣稱 BAG 變動 23 棟。
道路裁切總長：新 72188.73 m vs 舊 71247.33 m，差 941.39 m（1.3213%）；road count 850 vs 809。來源日期不同，未修改既有 surrounding context。

## 可重跑指令與產物

```sh
PYTHONPATH=src .venv/bin/python scripts/reconcile_extent_fetch.py \
  --receipt /private/tmp/j9-extent-live-20261008T034138Z/receipt.json
PYTHONPATH=src .venv/bin/python scripts/rehearse_basic_site_analysis.py \
  --receipt /private/tmp/j9-extent-reconciled-20261008T035245Z/receipt.json \
  --syntax-root /Users/jackhsieh/.local/share/urban-design-data/syntax-context/run-20261001T105231Z \
  --output /private/tmp/j9b-analysis-new-unique-directory
```

超過 10 分鐘時加 nohup 並輪詢。output 目錄必須是新的，不能覆蓋舊結果。

- DB 副本：`/private/tmp/j9-extent-reconciled-20261008T035245Z/copy.sqlite3`。
- source manifest：`/Users/jackhsieh/.local/share/urban-design-data/extent-fetch/extent-22e0fcda05157bda63cf17d0d15d8bed/20261008T035245Z-8378301f93f5461a999ac618e92f9b9d/manifest.json`。
- Repo 保留 raw manifest／fetch receipt／API result／audit／map overlay／comparison：`artifacts/j9b-site-analysis/`。
- API result SHA：`sha256:340116c2dc7b771db3a2eadc03008018a44a7b2a4982ec7f419ac03d12f664ca`。

### 來源 hash

- `analysis_code`：`sha256:8370e9668702b2333a72c8e7ce775a8e39f38b83d194e0e9e2bdc7271d9d0e35`。
- `bag`：`sha256:257c3ee79db26cafbf6233ef7e1891e56b773a5d56dba50a115a6aa8a1e6f111`。
- `extent_manifest`：`sha256:5291c1e59833162718a106189df39c461ae66db2909d26fa439d3fbd78408280`。
- `landuse`：`sha256:d61e7abf54e7afe1658aa1f72b8b11cdddd5e5c9fa86d218912a2573efe51951`。
- `mode_policy_code`：`sha256:8e56220257cbc930a711b55b23886723f3e76ba2ae0db6376f6105345ed2d99d`。
- `network`：`sha256:87d62860c57c38f814061e2872fec1345634cd36d850546ecb81d0eec142ed4c`。
- `parameters`：`sha256:c818baae328482896fbd6aee4a2d9c20428439fa96e19f454eb327410e21989b`。
- `pois`：`sha256:597d7a095187c96502177b159df1feacf084f884ba94864d235d4b9fc9aa73fa`。
- `study_area`：`sha256:9a59159505505dbe658ec6667ecfeb9024b868faf6377e7cd91889c763170d32`。
- `syntax_manifest`：`sha256:a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1`。
- `syntax_pedestrian`：`sha256:5e0cd13dfdd33ebfc4f22a47c4426be06a47d875926c383257399bbd6adaa3e6`。
- `transit`：`sha256:cdb42f3016a5abeebc02d193158e7f190456bdf9ecc9159a4c7d4a94db73ea32`。

## 限制與未完成驗收

- 來源時間不同、OSM polygon multipolygon 仍未建立；POI／站點 representative 不是實際門口。
- 尚無班次、stop-area 去重、人口／旅次／觀測人流；同一站的 platform 和 stop_position 可能重複計入。
- BAG 多用途面積平均分配；用途物件數作吸引點，不是假設面積等於人數。
- 入口是 source walking network 與邊界交點，尚未核對門、圍牆、開放時間、vertical access；snap connector 可能跨實際障礙。
- 10 km 道路 acquisition 不證明 10 km Syntax 完整性／邊界穩定性。公開 WMS raster 不是法定 zoning。
- 前端實際瀏覽器／WebGL 畫面走查被自動核准拒絕；沒有繞過。TestClient／vitest 不能替代此驗收。
- 全套 pytest 最終結果、Claude 跨供應商審查與 Founder 接受仍須在 handoff 核對，不能把本文當整體 PASS。

## 驗證補記（2026-10-08T04:39:47Z）

- `.venv/bin/python -m pytest tests/test_site_analysis_basic.py tests/test_site_extents.py tests/test_regional_network.py tests/test_regional_network_extract.py -q`：51 passed，6.47 秒，exit 0。
- `npm --prefix web run test`：326 passed／56 files，11.88 秒，exit 0（vitest-r3.log）。
- `npm --prefix web run lint`：exit 0，既有 warnings 及新面板 3 個 React warnings 保留，無 suppression。
- `npm --prefix web run build`：exit 0，chunk warnings 保留。
- `Q5_READONLY_FIXTURE_ROOT=/Users/jackhsieh/Downloads/TUD/Q5/project .venv/bin/python -m pytest -q`：2145 passed／6 failed／5 skipped／15 warnings，2019.55 秒，exit 1。
- 上述 6 個失敗：2 個已知環境／歷史 PNG、3 個 subprocess 無 PYTHONPATH、1 個 D1 v8 acceptance 與當前 v9 DRAFT 不相符。
- `PYTHONPATH=src Q5_READONLY_FIXTURE_ROOT=/Users/jackhsieh/Downloads/TUD/Q5/project .venv/bin/python -m pytest tests/test_store_thread_safety.py tests/test_week6_d1_workspace_binding.py -q`：10 passed／1 failed，3.53 秒；store subprocess 全部通過，D1 保持失敗。
- D1 guard 原始碼與起點 `9299c9d` SHA 相同；沒有放寬斷言／核准規則。詳見 `artifacts/j9b-site-analysis/d1-failure-diagnosis.json`。
- 補上 PYTHONPATH 的完整重跑已結束：2148 passed / 3 failed / 5 skipped / 15 warnings; 1874.78s; exit 1；仍未通過完整套件門檻。原有 5 skipped 並非本次新增。

## 最終結束紀錄（2026-10-08T05:09:20Z）

`PYTHONPATH=src Q5_READONLY_FIXTURE_ROOT=/Users/jackhsieh/Downloads/TUD/Q5/project .venv/bin/python -m pytest -q`：**2148 passed / 3 failed / 5 skipped / 15 warnings; 1874.78s; exit 1**。

失敗節點：

- `tests/test_m2a03_spatial_policy.py::test_piped_decision_key_stays_on_stdin_when_dev_tty_exists`
- `tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema`
- `tests/test_week6_d1_workspace_binding.py::test_d1_v8_workspace_geometry_binds_active_study_area`

正式 ledger count/max sequence：304/304 → 304/304。`PYTHONPATH=src .venv/bin/python artifacts/j9b-site-analysis/verify-final-evidence.py artifacts/j9b-site-analysis/final-audit.json`：exit 0，81 個 manifest 檔、14 個程式 hash、GeoPackage hash／層筆數全部相符，diff check exit 0。

狀態仍 INCOMPLETE；未 stage／commit。最終進度：`artifacts/j9b-site-analysis/progress-evidence-20261008T050920Z.json`。瀏覽器／Claude 審查／Founder 接受均未完成。
