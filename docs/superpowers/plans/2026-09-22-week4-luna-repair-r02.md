# Week 4 權威同步與證據修復 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task by task. Steps use checkbox (`- [ ]`) syntax. 每個 checkpoint 先自驗，再交 Sol／Astra 獨立驗收。

**Goal:** 修復 Week 4 已有的介面和分析成果，使 QGIS→平台同步、來源與草稿驗證、基地證據、Space Syntax、AI 狀態和交接包能被獨立重播及審查。

**Architecture:** 以既有 spatial-r01 和 SQLite／ledger 為權威，平台只接收版本化的觀測要素與草稿選擇。QGIS bridge 保留 8788；平台 API 使用獨立可配置的本機埠。六個 Syntax 圖層分開報告計算能力與 Rotterdam 資料可用性，未具足夠來源範圍者維持 `BLOCKED`。

**Tech Stack:** Python／Pydantic／FastAPI／SQLite／Shapely／pytest、既有 QGIS bridge、React／TypeScript／Vite，以及一個可重播的瀏覽器測試工具。

---

## 現況與執行邊界

2026-09-22 的唯讀複查：聚焦後端 `40 passed`、前端 Vitest `3 passed`、production build 成功。真實 SQLite 已有 `workspace-rotterdam-m4h-pilot-project` 的 rev 1、rev 2，兩版均為 `DRAFT`；ledger 183。`artifacts/week4-repair-r01/` 已有瀏覽器截圖與新版彩色圖，但沒有 package manifest／verifier。這些是觀察到的進度，**不是 Week 4 最終 PASS**。開工時重新讀取現況；若另一執行者仍在改同一批檔案，先協調檔案所有權。

已修復的部分：rev 2 寫入、前端道路標記、地圖畫 polygon、選擇 Evidence Card，以及圖像依數值上色已有程式與局部測試。保留這些實作，針對下列剩餘問題修正。

本輪不做新 geodata 請求、天氣方法、空間政策批准、正式 morphology 方案或氣候分析。`week4-baseline`、`week4-repair-r01`、spatial-r01、R05–R09-R01、blocked r03 與既有 ledger 版本只讀。所有測試寫入一次性 SQLite；新的驗收證據寫進未使用的 `artifacts/week4-repair-r02/`。

### 目前可直接重現的失敗

1. `WorkspaceService.sync()` 只檢查 ID 存在；Artifact 可以冒充 DatasetSnapshot；來源 hash、parent、project、StudyArea active pointer 均未核對。不存在的 feature 和 artifact 仍可存入。`spatial_brief` 是 `dict[str, Any]`，空 polygon、`CONFIRMED`、`hard_constraints_active=true` 被接受。一次性 SQLite 的 POST 回傳 `201`。
2. `src/urban_design/api.py` 從舊 v5 proposal／`artifacts/week4-baseline` 讀地圖和證據，卻給 UI spatial-r01 的 snapshot IDs。151 個舊 BAG features 只有 19 個 ID 出現在固定指派的 spatial-r01 BAG page 1；道路在 UI 的 segment IDs 與來源 OSM way IDs 也不同。每個 feature 必須有可驗證 parent mapping。
3. `scripts/run_workspace_server.py` 用 8788；既有 QGIS bridge 及 `Open Urban Design QGIS.command` 也用 8788。QGIS plugin 目前只有 Draw、Use as Study Area、Refresh，沒有平台同步動作。
4. `GeminiLiveCriticProvider.generate_criticism()` 仍直接組裝固定文字，沒有模型請求。不得回報 `LIVE_AI: ACTIVE`。
5. `tests/test_e2e_workspace_flow.py` 是 FastAPI TestClient，沒有執行瀏覽器。截圖不構成自動化 E2E。
6. Syntax 的 4.2 km extent 由預設參數提供；2 km 是 `EDGE_AFFECTED_AT_PERIMETER`，10 km 是 `INSUFFICIENT_EXTENT_FOR_TRUE_REGIONAL_SCALE`。`clean_osm_segments()` 只在既有 vertices 切段，同層幾何交叉但無共同 vertex 時仍不相接。現有「known-answer」數值不足以驗證有 radius 限制的多路徑情況。
7. 修復後彩色圖已存在，但尚須證明圖中每條線的 ID／數值來自同一版 source 和 Syntax 結果；`week4-repair-r01` 尚無完整性封存。

## Task 0 — 凍結觀察基線（CP-R0）

**Files:** 新增 `artifacts/week4-repair-r02/baseline.json`；讀取 `AGENTS.md`、`README.md`、`docs/08_WORKFLOW_REALIGNMENT_2026-09-22.md`、Week 4 原計畫、`docs/02_SYSTEM_ARCHITECTURE.md`、`docs/05_EVIDENCE_FRAMEWORK.md`、`docs/06_EVALUATION_FRAMEWORK.md`、`docs/07_IMPLEMENTATION_PLAN.md` 與 spatial-r01 manifest。

- [ ] 讀取 SQLite 的 active StudyArea、project pointer、workspace revisions、ledger、snapshot counts；將 rev 1／rev 2 標作「先前執行產生的未審核 DRAFT」，不推定為人類批准。
- [ ] 記錄 `week4-baseline`、`week4-repair-r01` 與受保護封存的 size／SHA-256。既有 SQLite 是可變 state；只記錄 baseline hash，不把後續合法 append 視為 archival corruption。
- [ ] 讀取 8787、8788、預定平台埠的 listener owner。不得停止、重啟或搶占 Hermes／QGIS bridge。
- [ ] 在 `/private/tmp` 建一次性測試資料庫；禁止測試直接寫 `.urban_design_runtime/state.sqlite3`。

**CP-R0：** 基線可重播、既有草稿未被當成批准決定、受保護檔案 hash 已記錄；任何 drift 以 `BLOCKED_BASELINE_DRIFT` 回報。

## Task 1 — 建立單一、可追溯的 spatial-r01 讀取路徑（CP-R1）

**Files:** 修改 `src/urban_design/api.py`、`src/urban_design/workspace_service.py`；可新增 `src/urban_design/workspace_sources.py`；修改 `tests/test_workspace_api.py`、`tests/test_workspace_sync.py`。

- [ ] **先寫失敗測試：** 取得 site-context 後，對每一個可選建築／道路，能在 spatial-r01 的完整來源集合中找到其 feature ID 或明確的 `way-id → segment-id` 映射及正確 parent Artifact。測試 UI 看到的 feature 不得綁到一個不含它的 BAG page。使用實際 spatial-r01 fixture，不從舊 v5 proposal 取代。
- [ ] **先寫失敗測試：** `source_snapshot_ids` 指向 Artifact、別的 project、未屬於 spatial-r01、缺檔、錯 hash、錯 parent，或被 supersede，API 均回 `422`，且 state／ledger 數量不變。
- [ ] 重用 `load_m2a03_spatial_package()` 與 `inspect_active_study_area()` 或其相同檢核語義。從 SQLite 解析 active StudyArea、確認／啟用 events、CRS、來源 manifest、Artifact URI／hash 和 snapshot parent；不信任 UI 傳的 status、geometry、hash 或 approval。
- [ ] 從完整 spatial-r01 normalized artifacts 建立選取索引，明確保存 `feature_id`、`feature_kind`、`source_artifact_id`、`source_snapshot_id`、`source_feature_id`、`crs`。若來源無法將舊 UI ID 對回權威資料，該 feature 應顯示 `UNVERIFIED_LINEAGE` 且不可提交。
- [ ] site-context 的 Evidence Cards、Syntax layers 與地圖來源應標示同一個 package revision；禁止混合 `week4-baseline` 和 r02 後仍宣稱來源一致。取得不足時以清楚的 blocked reason 回傳。

測試命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_workspace_api.py tests/test_workspace_sync.py
```

**CP-R1：** 所有 UI 可提交 feature 有真正 parent；缺失、錯類型、錯 hash、錯 project、錯 StudyArea 的請求 fail closed，且沒有新增 state／ledger。

## Task 2 — 收緊 WorkspaceRevision 與 SpatialBrief 契約（CP-R2）

**Files:** 修改 `src/urban_design/workspace_contracts.py`、`src/urban_design/workspace_service.py`、`src/urban_design/design_brief.py`、`src/urban_design/api.py`；新增／修改 `tests/test_workspace_sync.py`、`tests/test_design_brief.py`、`tests/test_red_team_week4.py`。

- [ ] **先寫失敗測試：** 下例必須回 `422`、沒有 ledger append：

```python
bad = {
    "feature_dispositions": [{
        "feature_id": "nonexistent-building",
        "feature_kind": "building",
        "disposition": "preserve",
        "source_artifact_id": "nonexistent-artifact",
    }],
    "spatial_brief": {
        "zones": [{"geometry": {"type": "Polygon", "coordinates": []}}],
        "status": "CONFIRMED",
        "hard_constraints_active": True,
    },
}
```

- [ ] 以具名 Pydantic 型別取代自由 `dict[str, Any]`。`SpatialZone` 必須有 EPSG:28992 polygon、正面積、範圍內幾何、原始註記、作者、revision、program／open-space 訴求。FAR／coverage／height 數值只能以 `DRAFT_PENDING_HUMAN_DECISION` 保存；client 無權送 `CONFIRMED`、`approved` 或有效 hard constraint。
- [ ] 空 `source_artifact_id` 不再由固定第一頁補上；以已驗證的 feature 索引解析，錯 kind、未知 ID、重複衝突或跨來源指派都 `422`。
- [ ] idempotency digest 覆蓋 canonical full payload，包括 zone geometry、文字、單位、來源和 dispositions。相同 key／相同 payload 回原 revision；同 key／不同 payload `409`；stale revision `409`；寫入失敗 rollback。
- [ ] 不改舊 rev 1／rev 2。若需遷移，另立 versioned record，先列出每個無法證實 lineage 的舊選項，交設計者確認；不得自動升為 Week 5 有效 constraint。

測試命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_workspace_sync.py tests/test_design_brief.py tests/test_red_team_week4.py
```

**CP-R2：** 任意 client JSON 不能取得批准狀態；正式 schema、持久 state、ledger、回讀結果一致；失敗請求沒有部分寫入。

## Task 3 — QGIS／平台埠與真實瀏覽器流程（CP-R3）

**Files:** 修改 `scripts/run_workspace_server.py`、`web/src/App.tsx`、`web/src/components/Header.tsx`、`web/src/components/Viewport2D.tsx`、`qgis_plugin/urban_design_study_area/plugin.py` 與必要 helper；新增 `web/e2e/workspace-flow.spec.ts`、`web/package.json` 的 test script、QGIS plugin helper 測試。

- [ ] 先寫 fail case：既有 QGIS bridge 啟在 8788 時，平台 API 不得搶 8788；前端從單一可配置 API base 連線。建議平台 API 用 8789；若被占用，選可用埠並記錄。現有佔 8788 的平台進程，先核對 PID、啟動命令與 in-flight 狀態，再以正常關閉方式遷移；不得停止 Hermes 或無關服務。8787 永遠保留 Hermes。
- [ ] QGIS plugin 提供一個明確的「Sync to Platform」操作，發送只含 stable layer／selection／StudyArea 引用的有界請求。bridge 或平台後端自行解析權威幾何、來源與 hash。不得開放任意 `execute_code`、SQL、Python 或 batch route。若 QGIS runtime 此輪無法啟動，插件／API 合約與 fake facade 測試可先完成，實際 QGIS 操作 checkpoint 維持 `BLOCKED_RUNTIME_NOT_VERIFIED`。
- [ ] UI 不硬編 snapshot／artifact ID；從權威 site-context 接收。當 server 無 workspace、載入失敗或 revision unknown 時，不顯示 `In Sync`。`409` 顯示可讀的 stale diff；post-dispatch 失聯顯示 `OUTCOME_UNKNOWN`，先 GET 對帳，不自動重送。
- [ ] 建立**真正的瀏覽器測試**：使用一次性 API／SQLite 啟動 UI，選建築與道路、畫非預設 polygon、提交 rev 1、改值提交 rev 2、reload 比對 geometry／ID／disposition、切六層、選 Evidence Card。HTTP TestClient 可留作 API integration，不能命名為 browser E2E 的替身。
- [ ] 只在斷言通過後保存截圖／短錄影；測試報告需記錄 browser、API、DB 及埠版本。

測試命令（由實作者新增 `e2e` script）：

```bash
npm --prefix web test -- --run
npm --prefix web run build
npm --prefix web run e2e
```

**CP-R3：** QGIS bridge 與平台可同時服務；真正瀏覽器操作及重載成功；server authority 只在持久化後顯示。

## Task 4 — AI provider 誠實狀態與 Evidence Card 驗證（CP-R4）

**Files:** 修改 `src/urban_design/model_provider.py`、`src/urban_design/site_critic.py`、`src/urban_design/api.py`、`web/src/components/PanelEvidenceAndCritic.tsx`；修改 `tests/test_site_critic.py`、`tests/test_workspace_api.py`。

- [ ] **先寫失敗測試：** 假 key 加 `PROJECT_GEMINI_AUTHORIZED=true` 不可產生固定文字卻宣稱 `gemini-live／ACTIVE`；transport 未配置或真實請求失敗必須分別顯示 `BLOCKED`／`OUTCOME_UNKNOWN` 等正確狀態。測試使用注入的 fake transport，**不可真打 model API**。
- [ ] 實作真正的 bounded provider adapter：明確 model ID、request ID、timeout、max output、structured response、provider metadata，不輸出 secret 或 private chain-of-thought。若本機沒有 credential／授權，保持 fixture-only 並於 UI 清楚標記，CP-R4 的 live 子門檻維持 `BLOCKED_CREDENTIAL_ABSENT`。
- [ ] Evidence Card ID 必須從同版 bundle 解引用；空選擇、假 ID、stale scenario／radius、錯單位與未支持數字被拒。輸出 `observations`／`hypotheses`／`limitations` 分開；model 不得批准 constraint 或產生總冠軍排名。

測試命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_site_critic.py tests/test_workspace_api.py
```

**CP-R4：** fixture、live、blocked 的狀態與實際路徑一致；無 credential 時不宣稱真實 AI 已通過。

## Task 5 — Syntax 方法、來源範圍與圖紙（CP-R5）

**Files:** 修改 `src/urban_design/space_syntax.py`、`src/urban_design/context_network.py`、`src/urban_design/figure_export.py`、`scripts/render_syntax_figure.py`、`tests/test_space_syntax.py`、`tests/test_context_network.py`、`tests/test_figure_export.py`。

- [ ] **先寫失敗測試：** 同層線段於 interior 交叉但原始資料沒有 vertex 時，必須形成 junction；不同 layer crossing 不相接。已知 linear corridor 的 `NAIN=1.148698`、中段 `NACH=0.630930` 可保留，但另需獨立手算／可信外部參考的分岔、cycle、metric-radius 邊界與雙路徑數值，不以同一函式生成 oracle。
- [ ] 修正 metric-radius 內角度與距離的路徑搜尋：若兩條到達同一 directed state 的路徑分別較短距離／較低角成本，不可只留一個 label，直到有獨立對照證明結果正確。保留 isolated、bridge／tunnel、unknown tags 的明確狀態。
- [ ] 從實際 acquisition envelope 與 study-area 到 network boundary 的距離推導每個 segment／radius 的 coverage；刪除硬編的 `network_extent_m=4200` 作為驗收根據。沒有範圍穩定性證據時，2 km／10 km 保持 `EDGE_AFFECTED`／`BLOCKED`，UI 圖層可存在但不得標為 Rotterdam `VALIDATED`。
- [ ] 從同一個 verified syntax result、source manifest 和 segment mapping 重建彩色 PNG／SVG。斷言有數值對應的多色線、matched segment IDs、缺值灰色、圖例 min／max、CRS、radius、資料 readiness、artifact hash。圖面文字不能把 edge-clipped 指標稱作 validated。

測試命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_space_syntax.py tests/test_context_network.py tests/test_figure_export.py
```

**CP-R5：** 程式計算正確性與 Rotterdam 資料範圍分開判定；缺 10 km 來源時 10 km 不會因六個 JSON layer 都存在而變成 PASS。

## Task 6 — r02 封存、回歸與交接（CP-R6）

**Files:** 新增 `artifacts/week4-repair-r02/`（source/context/analysis/UI evidence 與 handoff）、`scripts/verify_week4_repair_r02.py`、`tests/test_week4_repair_integrity.py`；更新一份狹義交接文件，保留舊檔。

- [ ] 先建立 package schema：每個檔案的 package-relative path、size、SHA-256、parent IDs／hash、producer、tool versions、輸入 revision、licence／limitations。manifest 自身排除或使用明確 self-hash 規則。
- [ ] verifier 驗證檔案、父檔、SQLite 參照與相互一致性；每種故障至少測一例：單 byte mutation、缺 parent、錯 hash、錯 revision、未知 Evidence Card ID、缺來源 feature。故障必須輸出 `BLOCKED`；不得重寫 r01 讓它變綠。
- [ ] handoff 中的 `valid_evidence_cards` 從實際卡片產生；Syntax 圖、六層、source 與 SQLite 參照的 hashes 均重新計算。保留原始錯誤 handoff 為歷史，不使用舊的虛構 IDs 或錯誤 hashes。
- [ ] 跑完整 backend pytest、frontend unit/build/browser E2E、r02 verifier、fault injection；另核對受保護 package hashes、Hermes 8787、真實 SQLite／ledger delta。沒有新 live geodata／weather 請求。
- [ ] Sol／Astra 獨立審查前僅回報 `EXECUTOR_SELF_CHECKED`。任何 live AI、QGIS runtime、區域 10 km 缺口留作明確 `BLOCKED`，不能彙總成 Week 4 `PASS`。

測試命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider
npm --prefix web test -- --run
npm --prefix web run build
npm --prefix web run e2e
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/verify_week4_repair_r02.py artifacts/week4-repair-r02
```

**CP-R6：** 新 package 和所有 parent hashes 可重播；原始 evidence 未改；報告將 CP4-0–CP4-8 分別列 `PASS／PARTIAL／FAIL／BLOCKED／OUTCOME_UNKNOWN`，並標示哪些 Week 5 fixture 工作可開始、哪些真實流程仍缺門檻。

## 自我檢核與停止規則

每個 CP-R0–R6 都需記錄：觀察到的 state／ledger 前後數量、測試 node、最小可重現輸入與回應、artifact path／hash、保護檔 hash、失敗控制、下一相依階段。某一 gate 失敗時，繼續與其無關的離線工作；不得改寫該 gate 為 PASS。斷線後的外部 dispatch 是 `OUTCOME_UNKNOWN`，先查 server／ledger／檔案再考慮後續操作。

獨立驗收前的目標狀態是「可核對的修復成果」，不是強迫 Week 4 PASS。天氣維持 `BLOCKED / SEMANTICS_UNRESOLVED`，spatial policies 維持未批准，既有 rev 1／rev 2 只是歷史 DRAFT。
