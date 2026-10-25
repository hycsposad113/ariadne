# J9：粗範圍與資料抓取

執行範圍：`j9-dl-map`，`wp/dl-map`，起點 `9299c9d`。粗範圍只作資料抓取；不建立 StudyArea、HumanDecision，不改 C1/D1。正式接受仍由 Claude 跨供應商審查及 Founder 決定。

## API 合約

- `POST /api/v1/projects/{project_id}/site-extents`：`{"geometry":{"type":"Polygon","coordinates":[[[lon,lat],…,[lon,lat]]]},"idempotency_key":"unique-key"}`。202 回傳 id、job_id、PENDING、area_m2、geometry_wgs84、geometry_epsg28992、settings、purpose。相同 key/geometry/settings 回傳原 job；不同輸入 422。非閉合、自交、非有限座標、面積超限 422，未知專案 404。不接受 client approval 或結果。
- `GET .../site-extents`：`{"extents":[…]}`，append-only 粗範圍紀錄。
- `GET .../site-extents/jobs/{job_id}`：專案隔離的 job 狀態、逐來源結果、manifest 路徑/hash。主狀態 PENDING/RUNNING/DONE/PARTIAL/FAILED；出版完整性、掉線或未完成登記另保留 OUTCOME_UNKNOWN，不重送。

Operational store/runner 沿用 `GenerationJobStore`／`GenerationJobRunner`。`READY` 是 artifact 出版狀態；UI 的 DONE/PARTIAL/FAILED 依逐來源結果投影，不把 READY 當下載全部成功。RAW Artifact／DatasetSnapshot 一次 transaction 登記；完整事件存在才顯示已完成。粗範圍建立與 job enqueue 跨 DB，若 enqueue 中斷，必須用原 key reconcile，不會自動換 key 重試。

## 設定、座標、下載

`ExtentSettings` 的預設設定標成 `ASSUMED_COMMANDER`：面積上限 25,000,000 m²、道路外推 10,000 m、建物／土地使用外推 500 m、單一來源上限 200 MB、WFS 每頁 1,000／最多 100 頁、Overpass 最多兩次重試／間隔至少 30 秒。這些是 acquisition guard，不是規劃規則。前端 spherical 面積是概略預覽；後端驗證有效 polygon 並重算 RD／全球 local AEQD 面積。全球提供 OSM；荷蘭範圍才抓 PDOK／3DBAG。全球 RD 座標輸出標記 `rd_area_of_use=false`，不能送入 RD-only Syntax；跨日期變更線及纬度超過 ±85° 明確拒絕。

Overpass 是道路、建物、landuse 一個 combined query，帶穩定 User-Agent；僅 429/502/503/504 可重試，connection loss 不重送。保留 source node IDs、交通方式原始 tags，沿用既有 `evaluate_way_for_mode`；全球模式分類的預設仍來自現有荷蘭政策，不能推論當地法定交通權。幾何外接框可能超出 exact buffer；polygon layers 再作 exact local buffer 篩選。

3DBAG 使用官方 WFS tile index、versioned GPKG.gz URL、HEAD 大小預檢及既有 height extractor。總 tile 下載超過 200 MB 或大小未知標 DEFERRED_SIZE；不在未知大小時先下載。高度是 roof/ground NAP 高程差，未知高度保留 null。不是新 StudyArea：height extractor 的 legacy 欄位名稱引用 extent draft ID，整份輸出標成 acquisition-only。

每次結果在 `~/.local/share/urban-design-data/extent-fetch/<extent_id>/<UTC>-<job_id>/`，獨占建檔。manifest 包含 URL/query/time/bytes/sha256/licence/count、逐次請求、處理狀態、exact artifact inventory。RAW snapshot 登記沿用 typed DatasetSnapshot，新增 extent_id/source_status/feature_count 放在 payload；不改正式 DB schema。

規劃資料：官方 [PDOK 公開規劃服務](https://www.pdok.nl/ogc-webservices/-/article/ruimtelijke-plannen) 提供 WMS，半年度更新。GetCapabilities + bounded GetMap 保存 `planning.png` 與 bbox/layer，標成 **WMS_RASTER_ONLY**，feature count 為 null；無向量 zoning、無法定符合性主張。ruimtelijkeplannen.nl／DSO keyed APIs 固定 BLOCKED_NEEDS_KEY，不讀 key；OSM landuse 保留為 observational alternative。初次試用的猜測 WFS URL 404 已保留在原始實測，不覆寫。

底圖使用 [OSM 使用政策](https://operations.osmfoundation.org/policies/tiles/) 所列 URL、可見 attribution、瀏覽器預設 cache/referrer；僅目前使用者視窗圖磚，不做 bulk/offline tile download。PDOK BRT EPSG:3857 raster 可切換。MapLibre 4.7.1（BSD-3-Clause）為指揮官預先安裝；本次未裝套件。

## QGIS 與 Syntax

```sh
PYTHONPATH=src .venv/bin/python scripts/export_extent_geopackage.py --manifest /absolute/fetch/manifest.json --output /private/tmp/extent.gpkg
PYTHONPATH=src .venv/bin/python scripts/compute_syntax_context.py --extraction-dir /absolute/fetch --acquisition-buffer-m 10000 --max-context-m 10000
```

GeoPackage 先核對 manifest 每個檔案 hash/bytes，再寫建物（高度 join）、各交通方式 roads、OSM buildings、landuse、粗範圍。目的地已存在即拒絕。規劃 raster 留在旁邊的 `planning.png`；可自行於 QGIS 載入，bbox 在 manifest。程式不啟動 QGIS／啟動器。Syntax 格式包含 source node IDs、grade-separated unlinks、extraction manifest；PST 的現有驗證不放寬，舊 SHA 格式保持原樣。`--max-context-m` 預設仍 3000。10 km acquisition **不能**保證 source completeness／boundary stability，更不能宣稱 formal Syntax PASS。

## 限制／交接

前端尚未作實際瀏覽器 GPU/map walk-through；vitest 用 map event boundary 測畫圖、提交、底圖切換，並非真實 WebGL 證據。抓取來源結果與路徑會顯示，但尚無下載圖層直接疊到畫範圍地圖的功能。OSM polygon 目前只收 closed ways，multipolygon relations 尚未處理；不能宣稱完整 buildings/landuse。各國投影精修與當地交通政策仍需後续配置。沒有自動重啟恢復／無限重試。粗範圍與資料只供探索，精確 QGIS 基地仍走既有 C1/D1。

## 2026-10-08 J9 續作與 J9b

此 worktree 的 J9 續作接上 J9b 新資料管線，handler 升為 `site-extent-fetch-v2`。原始 500 m 的 BAG pand 和預設 Syntax context 3,000 m 不變；OSM 建物／landuse／POI 追加至 1,500 m、交通站點至 2,000 m，BAG verblijfsobject 至 1,500 m。詳見 [J9b API／方法契約](j9b-site-analysis-contract.md) 與 [M4H 實測](j9b-site-analysis-m4h-20261008.md)。舊 2026-10-07 evidence 原封保留，不用舊查詢回應冒充新的 coverage。

新一次公開資料擷取保留來源回應後，使用同查詢、hash 驗證 bytes 離線重播。新 raw source snapshots 登記 61 個。GeoPackage 追加交通／POI／BAG 用途層；沒有啟動 QGIS、沒有改正式 StudyArea／HumanDecision。道路共同 +500 m 範圍比較多 941.39 m（1.3213%）；新 BAG footprints 2,307 vs 舊 OSM footprints 2,284，不能當同來源 BAG 差異。

新增「基本基地分析」Site 面板，沿既有 Site Intelligence 套件實作，不另造 job／storage 架構。最終資料、API 結果、疊圖及比較保留於 `artifacts/j9b-site-analysis/`。完整驗證／未完成 gate 以該目錄 handoff 為準；未經 Claude 審查與 Founder 接受。
