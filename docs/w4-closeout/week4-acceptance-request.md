# Rotterdam M4H 都市設計平台 Week 4 驗收請求

**版本：** 2026-09-25／v1  
**執行者：** AntiGravity（Gemini 3.8 Flash），依 PD-18 授權與執行  
**審查者：** Claude（Commander，Control Tower）  
**裁決者：** 設計者（Jack）  
**工作目錄：** `/Users/jackhsieh/Downloads/TUD/Q5/w4-closeout`（獨立 worktree）  
**工作分支：** `wp/w4-closeout`（基底：`main` @ `78be302`）  

---

## 1. 執行總結與 Checkpoint 狀態矩陣

依據 [Week 4 收尾執行計畫](../superpowers/plans/2026-09-25-week4-closeout-plan-zh.md) 與 [決定紀錄 PD-01–PD-18](../../decisions/2026-09-25-plan-decisions-zh.md)，AntiGravity 不得自行宣告通過或合併至 `main`。以下照實陳報各項 Gate 狀態：

| Checkpoint / 項目 | 狀態 | 負責人 / 阻塞解除條件 | 證據路徑 / 產出 |
|---|---|---|---|
| **CP4-0 起點核對** | **PASS** | 已完成 | DB SHA-256 `3e30c3d4...`、ledger 187、rev 6 DRAFT、port 8787/8644 未接觸 |
| **CP4-1 (C1) QGIS 介面同步** | **BLOCKED** | **負責人：設計者（Jack）**<br>需設計者本人在 QGIS 操作「Sync to Platform」按鈕（PD-14） | `docs/w4-closeout/c1-qgis-runbook.md`<br>`Open Urban Design QGIS.command` |
| **CP4-2 保留與分區操作** | **PASS** | 已完成 | R41 探索設計範圍（EDA）、R46 決策保護、R50 分區範圍重疊檢查已合併並通過 71 項單元測試 |
| **CP4-3 基地分析卡片** | **PARTIAL** | **負責人：AntiGravity (WC-2)**<br>分析結果尚未完成資料庫持久化，目前涵蓋有限 | 側邊欄 EDA/Brief 數值卡片已合併展示，持久化待解鎖核心檔後寫入 |
| **CP4-4 六張 Syntax 圖層** | **PARTIAL / BLOCKED** | **負責人：AntiGravity / 設計者**<br>先前「800m 579路段」為臨時探針測試輸出非正式持久化成果，依審查指示撤回；800m 改以區域 PBF 裁出外擴範圍計算並持久化；2km/10km 待 PBF 裁剪計算 | 1. 手算驗證：`tests/test_pst_fixtures.py`<br>2. 方法清單：`config/runtimes/pst-method-manifest-v1.json`<br>3. 下載證據包：`artifacts/week4-regional-osm/`<br>4. 路網政策：`config/runtimes/syntax-network-policy-v1.json`、`docs/methods/syntax-network-policy-v1.md`<br>5. 邊界解析：`src/urban_design/regional_network.py`（距省界 21.8 km）<br>6. 區域路網裁切與計算進行中 |
| **CP4-5 圖面輸出** | **PASS_SCOPED** | 已完成範圍內功能 | 2D / 3D 圖面渲染、SVG / PNG 輸出管線正常（目前為探索性圖面） |
| **CP4-6 人類決策保護** | **PASS** | 已完成 | R46 決策保護守衛：未批准之草案嚴格標示為 DRAFT / EXPLORATORY，禁止自動竄改 |
| **CP4-7 Live AI 整合** | **BLOCKED** | **負責人：Luna / 設計者**<br>等待 Luna 完成 W5-AI 模型層，以及設計者在 Keychain 配置 API key（PD-10/PD-12） | 依 PD-10/PD-12 由 Week 5 Luna 負責提供 API 整合 |
| **CP4-8 審查與 Walkthrough** | **BLOCKED** | **負責人：AntiGravity**<br>需使用 DB 副本完整預跑流程、產出截圖並供獨立審查 | 待持久化與所有功能齊備後以 DB 副本跑完整 walkthrough 並截圖 |
| **WC-1 R40–R55 分流合併** | **PASS** | 已完成 | `docs/w4-closeout/r40-r55-triage.md`（commit `633661e`） |
| **WC-2 分析結果持久化** | **BLOCKED** | **負責人：Commander / Luna**<br>需等待 `wp/w5-01-decision-actor` 合併入 `main` 後解鎖共用核心檔 | `src/urban_design/models.py`, `store.py`, `api.py` 嚴格受保護中 |
| **WC-4 PD-14 來源註記** | **BLOCKED** | **負責人：Commander / Luna**<br>需等待 `wp/w5-01-decision-actor` 合併入 `main` 後追加 ledger 註記 | 182–185 預設值、186–187 代理操作註記待合併 |
| **WC-5 C1 驗證支援** | **PASS** | 已完成 | `docs/w4-closeout/c1-qgis-runbook.md`（commit `b6a6aa7`） |
| **WC-6 文件修正與殘留 DB** | **PASS** | 已完成 | C5：`docs/00_PRODUCT_VISION.md`<br>C6：`docs/w4-closeout/c6-stray-sqlite-report.md`（commit `b6a6aa7`） |

---

## 2. 測試執行總結果（All Release-Blocking Tests Pass）

### 2.1 Python 後端測試
- **執行命令：** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q`
- **結果：** **582 passed, 7 warnings in 387.32s (0:06:27)**
- **失敗數：** 0
- **略過數：** 0

### 2.2 前端測試與建置
- **單元測試：** `npm --prefix web run test`
  - **結果：** 14 test files passed, 71 tests passed in 1.93s
- **正式建置：** `npm --prefix web run build`
  - **結果：** `tsc -b && vite build` 成功建置，耗時 306ms
- **程式碼檢查：** `npm --prefix web run lint`
  - **結果：** 0 errors, 3 warnings (62ms)

### 2.3 第 2 級證據包驗證（PD-06 / PD-17）
- **封包路徑：** `artifacts/week4-regional-osm/`
- **驗證命令：** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/week4-regional-osm/verify_package.py`
  - **結果：** `PASS`（10 files checked, 4 parents checked, 0 failures）
- **故障注入測試：** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/week4-regional-osm/run_integrity_fault_tests.py`
  - **結果：** `PASS`（全部人為竄改與遺失皆被即時偵測攔截）

---

## 3. 獨立審查者端到端 Walkthrough 腳本

審查者可在本地按照以下步驟進行驗證（全程使用資料庫副本，絕不汙染權威資料庫）：

```bash
# 1. 確保位於 worktree
cd /Users/jackhsieh/Downloads/TUD/Q5/w4-closeout

# 2. 啟動後端伺服器（使用本地副本 DB）
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/uvicorn urban_design.api:app --port 8000

# 3. 啟動前端開發伺服器
npm --prefix web run dev -- --port 5173
```

### 操作步驟：
1. **載入與同步：** 開啟瀏覽器至 `http://localhost:5173`。點擊右上角「Sync to Platform」，確認 StudyArea v5 範圍與既有 140 筆道路要素正確顯示。
2. **要素選擇與保留：** 在 2D 地圖點選建築要素，點擊「PRESERVE」設定為保留；點選道路要素設定為可改動。確認要素顏色即時更新（綠色保留、藍色可改）。
3. **分區繪製：** 點擊「Draw Zone」按鈕，在基地內點擊多個節點繪製多邊形並閉合。確認 R50 邊界檢查生效，無重疊報錯，分區屬性卡片正確更新。
4. **基地分析卡片：** 查看側邊欄「Spatial Brief」與「Exploration Design Area」，確認數值驗證（R40）嚴格生效，負數與非法字元皆被防護攔截。
5. **Syntax 圖層檢視：** 切換至「Syntax」分頁，點選「Local Scale (800m) Angular Integration」與「Choice」，確認 PST 3.3.1 步行動線數值呈現正常。
6. **匯出與重開：** 測試「Export GeoJSON / SVG」，確認下載檔案內容與目前視圖要素完全一致；重新整理網頁，確認草案狀態完整保留。

---

## 4. 待決事項與解除阻塞需求（Needs）

1. **依賴核准（`osmium`）：**
   - **套件名稱：** `osmium`（pyosmium）
   - **版本：** `>=3.7.0, <=4.0.2`
   - **授權：** BSD-2-Clause
   - **用途：** 高效串流讀取 211MB 之 `zuid-holland-260922.osm.pbf`，進行 StudyArea 4km、6km、20km 緩衝區之路網裁剪與 2km / 10km 計算。
   - **請求：** 請設計者（Jack）或 Commander 核准安裝此依賴。
2. **C1 QGIS 驗證：**
   - 依據 PD-14，代理不得代按。請設計者參照 `docs/w4-closeout/c1-qgis-runbook.md`，自行啟動 QGIS 並點擊「Sync to Platform」完成 C1 驗收。
3. **共用核心檔解鎖（WC-2 / WC-4）：**
   - 等待 Commander 審查並合併 `wp/w5-01-decision-actor` 至 `main`。合併後 AntiGravity 將立即進行分析結果持久化（WC-2）與 ledger 事件 182–187 追加來源註記（WC-4）。

---

## 5. 2026-09-26 現況補充 R02

本節是新的現況紀錄；第 1–4 節的 R01 數值與當時狀態保留作歷史記錄，若與本節不同，以本節的重新核對結果為準。此次實際執行環境為 Codex executor，與原計畫指定的 AntiGravity/Gemini 不同；工作仍限制在 `wp/w4-closeout` worktree。

### 起點與權威狀態

- Worktree：`/Users/jackhsieh/Downloads/TUD/Q5/w4-closeout`，branch `wp/w4-closeout`；本次作業起點 HEAD 為 `93d3a49`。`main` 為 `d9c9afa`；`wp/w5-01-decision-actor` 是 `main` 的祖先，已合併。作業產生的 commit 記錄見此 branch history。
- 權威 DB `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3`：2,248,704 bytes；SHA-256 `6dd5d6e137032a8f08e3a119de2cd7399f9215f9567671c10bf7ffbda22d9fb4`；`quick_check=ok`；ledger 215；workspace revision 6；active StudyArea v5，狀態 `CONFIRMED_FOR_EXPLORATION`。本次執行未寫入此 DB。
- 依計畫只用 `lsof` 觀察服務：8787 為 loopback `python` PID 80540，8644 為 loopback `python` PID 65898；兩者均未呼叫或停止。使用者 Vite PID 75418 持續監聽 5173。任務自啟動的 8789 API 已停止，停止後無 listener。

### CP4 gate 現況

| Gate | R02 狀態 | 最新證據與解除條件 |
|---|---|---|
| CP4-0 起點核對 | **PASS** | 權威 hash、ledger、workspace、active v5 與 ports 已重新讀取；證據見本節及 `docs/w4-closeout/c6-stray-sqlite-report-r02.md`。 |
| CP4-1 QGIS GUI 同步 | **BLOCKED（負責人：設計者）** | 本任務未操作 QGIS。依 `docs/w4-closeout/c1-qgis-runbook.md` 由設計者本人完成並提供同步畫面及狀態證據後解除。 |
| CP4-2 保留與分區 | **BLOCKED（尚未完成權威端獨立驗收）** | 拋棄式 DB browser walkthrough 驗證建築／道路 Preserve、草稿分區、sync、重載恢復；不能代替對正式運行及權威狀態的獨立驗收。詳見 `artifacts/week4-walkthrough-r01/run-20260926T024949Z-r02/`。 |
| CP4-3 基地分析卡片 | **BLOCKED（尚未完成正式運行驗收）** | API 在 DB 副本上回傳 7 張 `VERIFIED_OBSERVATION` 卡片；完整 pytest 通過。來源涵蓋與未知項仍須保持卡片明示；正式運行端的獨立驗收尚未完成。 |
| CP4-4 六張 Syntax 圖層 | **FAIL（UI 對應不一致）；計算仍 BLOCKED** | API 有 6 個尺度／指標候選，4 層已計算、2 個 10 km 層為 `NOT_COMPUTED_RUNTIME_BUDGET`。UI 將四個已計算圖層顯示成 `Result unavailable · plan/result mismatch`，並仍顯示只有 800 m 有值；見 `syntax-panel-r02.png`。請 Commander 指派前端 owner 修正並獨立驗證；不得將探索值稱為正式結論。 |
| CP4-5 圖面輸出 | **BLOCKED（UI 匯出未實測）** | 本次未執行 PNG／SVG 匯出。建置成功及既有單元測試不代替瀏覽器匯出驗收。 |
| CP4-6 人類決策保護 | **PASS（保護機制範圍）** | 完整 Python 測試通過；copy walkthrough 的分區狀態為 `DRAFT_PENDING_HUMAN_DECISION`。本次沒有建立或批准 HumanDecision。 |
| CP4-7 Live AI | **BLOCKED（負責人：Luna 與設計者）** | Critic 只讀狀態為 unavailable；沒有向 Live AI provider 送出請求。自動化測試只使用本地 fake provider。依 PD-10/PD-12，待模型層及設計者憑證配置完成後解除。 |
| CP4-8 獨立 walkthrough | **BLOCKED（完整流程尚未完成）** | DB 副本已完成載入、閱讀、保留、畫草稿、同步及重新載入；Live AI 與圖面匯出沒有測試，且 Syntax UI mismatch 仍存在。需先解除 CP4-4，之後由獨立審查者執行完整流程。 |

### WC-0 至 WC-7

- **WC-0 — PASS：** 本節已更新 branch、main 合併關係、權威 DB 與 ports 狀態。
- **WC-1 — PASS：** `docs/w4-closeout/r40-r55-triage.md` 保留逐項分類與理由；本次未改寫原審查結論。
- **WC-2 — PASS（程式／測試範圍）：** 持久化讀取與 stale/hash 驗證測試通過；目前 authority DB 含已持久化 EvidenceCard、Artifact 與 ToolExecution。此次無權威寫入。
- **WC-3 — BLOCKED：** 800 m 與 2 km 有探索結果；10 km 未計算，完整六層輸出與穩定性 gate 未達成。`CP4-4` 另有 UI mapping failure。
- **WC-4 — BLOCKED（automatic review）：** 對 ledger events 182–187 的六筆 PD-14 註記未寫入。先前 automatic approval review 拒絕了直接追加權威 ledger 的動作；本次未用其他路徑重試，也沒有權威 DB 寫入。
- **WC-5 — PASS（runbook 交付）：** `docs/w4-closeout/c1-qgis-runbook.md` 已存在；QGIS 實際操作仍由設計者完成。
- **WC-6 — PASS：** `docs/00_PRODUCT_VISION.md` 已指向 v5；README 目前也指向 v5，沒有修改 README。舊 C6 報告保留，新增 `docs/w4-closeout/c6-stray-sqlite-report-r02.md`。
- **WC-7 — PASS（驗收請求已更新）；Week 4 整體仍未完成：** 此補充明列目前 gate、測試、證據與阻塞，不代表接受或合併。

### R02 測試與 browser evidence

- 完整 Python：`RAYPATH=.:/Users/jackhsieh/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider` — **648 passed, 0 failed, 7 warnings，383.67 s**。首次完整 run 的 1 個失敗已定位為該 API 測試複製了舊 worktree SQLite（ledger 200、輸入 hashes 不一致）；`tests/test_week4_r03_observational_evidence.py` 改成唯讀複製權威 DB 到 pytest tmp 後，該檔 7/7 通過，之後完整 suite 全過。權威 DB 沒有被測試寫入。
- Web：`npm --prefix web run test` — 15 files／71 tests passed；`npm --prefix web run lint` — 0 errors、3 warnings。直接 build 在清理 worktree `web/dist/ariadne-brand.png` 時回 `EPERM`；沒有刪檔或請求更高權限。相同 production build 改輸出至 `/private/tmp/w4-closeout-web-build-r02` 後成功；包含既有 chunk-size warning。
- `git diff --check` 通過。
- Browser reload evidence：`disposable_browser_reload_verify-r02.py` 只送出本機 GET，標題為 `Ariadne — Rotterdam M4H Pilot`、StudyArea v5 與 workspace rev 7 正確顯示；建築 `bag:0599100000035095` 與道路 `way/1014567258` 的 Preserve 控制重載後仍為啟用，草稿區域 `brief-zone-muhsyqfa` 狀態為 `DRAFT_PENDING_HUMAN_DECISION`。截圖為 `walkthrough-04-reloaded-r02.png`。
- 寫入副本的 walkthrough 第一次且唯一一次 `POST /api/v1/workspaces/sync` 為 HTTP 201，將副本 workspace revision 6→7、ledger 215→216。腳本隨後因它預期的草圖座標與 canvas 整數 pixel rounding 後的保存座標相差 2 m 而停止；沒有重送 sync。獨立幾何核對確認實際 3,200 m² 三角形仍在 v5 StudyArea 內，狀態保持草稿。`post-shutdown-reconciliation-r02.json` 記錄了 API 關閉 checkpoint WAL 後副本完整檔案 hash `65d8b37679689fdf373f9f7c509ebb018f4ded38fc4a6bb0726d67eed8540c68`、size 2,306,048 bytes、`quick_check=ok`。副本不等同權威 DB。
- 未送出 PDOK／OSM／天氣或其他外部請求；未呼叫 Live AI provider；未操作 QGIS；未測試圖面匯出。Vite 5173 是使用者服務，本次未停止；8789 為本任務建立後已停止的副本 API。

### 目前需要的決策或工作

1. 設計者依 C1 runbook 親自完成 QGIS GUI／同步驗收。
2. Commander 指派 UI owner 修正 CP4-4 的已計算層與計畫資料映射，再重做獨立 walkthrough。
3. Luna 與設計者完成 Live AI 所需整合與憑證配置；本任務不取得或使用任何 key。
4. 若要完成 WC-4，需針對 automatic review 拒絕的六筆 authority ledger append 提供明確授權；目前六筆均未寫入。

## 6. 2026-09-26 現況補充 R03

**檢查時間：** 2026-09-26 04:03 UTC。以下是本次複核；R01、R02 內容保留作歷史記錄。

### Git、authority 與服務狀態

- Worktree `/Users/jackhsieh/Downloads/TUD/Q5/w4-closeout`，branch `wp/w4-closeout`，HEAD `532442e`；`main` 為 `d9c9afa`。`wp/w5-01-decision-actor` 是 `main` 的祖先。Worktree 仍 dirty，未 stage 或 commit 本次修改。
- 正式 DB `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3` 仍為 2,248,704 bytes、SHA-256 `6dd5d6e137032a8f08e3a119de2cd7399f9215f9567671c10bf7ffbda22d9fb4`、`quick_check=ok`；ledger 215，Artifact 117、DatasetSnapshot 54、EvidenceCard 15、Project 1、StudyArea 5、ToolExecution 3、WorkspaceRevision 1；Project rev 6 仍指向 `study-area-rotterdam-m4h-pilot-project-v5`，狀態 `CONFIRMED_FOR_EXPLORATION`。PD-14 註記數為 0；本次沒有 authority write。
- `lsof` 觀察到 `127.0.0.1:8787` 仍由 PID 80540 使用、`:8644` 由 PID 65898 使用；未呼叫或停止這兩個服務。供本次預覽使用的 API `:18789`（PID 98947）與 Vite `:15173`（PID 99007）仍在監聽，前端連線到 `/private/tmp/w4-closeout-interface-test-r03.sqlite3` 的暫存 DB 副本，不是正式 DB。使用者原有 `:5173` 服務未觸碰。
- 只讀複核 literal `.../urban_design_runtime/state.sqlite3`：57,344 bytes、SHA-256 `6453fc31047c09325168b2f9a114872aeb88909c181029815c975c68da254a49`、`quick_check=ok`，heads 與 ledger 均為 0；現行 `src/`、`scripts/`、`tests/` 沒有能生成該 literal 路徑的命中。C6 報告仍符合本次觀察，該 DB 與 sidecar 未更動。

### Gate 狀態更新

| Gate | R03 狀態 | 證據與解除條件 |
|---|---|---|
| CP4-0 起點核對 | **PASS** | 本節記錄的 Git、正式 DB、StudyArea v5 與服務埠讀取結果。 |
| CP4-1 QGIS GUI 同步 | **BLOCKED（負責人：設計者）** | 本次只開啟 Web 預覽，沒有操作 QGIS；依 `docs/w4-closeout/c1-qgis-runbook.md` 由設計者本人完成。 |
| CP4-2 保留與分區 | **BLOCKED（只完成 DB 副本操作）** | R02 的 disposable DB walkthrough 有保留、分區、一次 sync 與重新載入證據；尚不能替代獨立審查者對完整流程的驗收。 |
| CP4-3 基地分析卡片 | **BLOCKED（完整 walkthrough 未完成）** | 本次預覽載入 7 張 evidence cards；這是 DB 副本的顯示檢查，不代表正式端到端驗收。 |
| CP4-4 六張 Syntax 圖層 | **BLOCKED（計算範圍）** | WC-3 R02 manifest verifier `PASS`，6 layers；四層有計算結果，兩個 10 km 層為 `NOT_COMPUTED_RUNTIME_BUDGET`。前端現在正確呈現這兩個 unavailable 狀態，不再把已計算結果顯示成 plan/result mismatch。10 km 結果與完整穩定性檢查仍未完成。 |
| CP4-5 圖面輸出 | **BLOCKED** | 本次沒有執行匯出；需要瀏覽器 PNG/SVG 輸出核驗。 |
| CP4-6 人類決策保護 | **PASS（保護範圍）** | 既有測試與 R02 disposable walkthrough 保持 DRAFT 狀態；本次沒有新增 HumanDecision 或啟用 Constraint。 |
| CP4-7 Live AI | **BLOCKED（負責人：Luna 與設計者）** | 本次沒有模型呼叫；需完成 W5-AI 並由設計者配置憑證。 |
| CP4-8 獨立 walkthrough | **BLOCKED** | 本次在 `http://127.0.0.1:15173/` 檢視 Ariadne 標誌、StudyArea v5、rev 6、同步提示與 7 張 cards，並查看新版 Syntax 狀態；完整 Playwright runner 因環境缺少 `playwright` 套件而無法啟動，匯出與 Live AI 也未測。 |
| WC-0 | **PASS** | branch/merge-base 與正式 DB 狀態已複核。 |
| WC-1 | **PASS** | `docs/w4-closeout/r40-r55-triage.md`。 |
| WC-2 | **PASS（持久化讀取範圍）** | 正式 DB 已有 persisted Artifact、EvidenceCard 與 ToolExecution；本次無新增寫入。完整 backend 測試通過。 |
| WC-3 | **BLOCKED（10 km stop-loss）** | `artifacts/week4-wc3-regional-syntax-r02/` verifier 為 8 個本地檔、31 個 external parents、6 layers 全數通過；15/20 km 執行時間預估超過 7,200 秒，因此沒有啟動兩個 10 km 計算。 |
| WC-4 | **BLOCKED（automatic review）** | 嘗試執行受 hash guard 與 SQLite `.backup` 保護的六筆追加註記命令時，auto-review 拒絕了該命令；資料庫未改變，沒有以其他方式重試。解除條件：取得明確授權後，重新核對 hash 並再執行 guarded writer。 |
| WC-5 | **PASS（runbook 交付）** | `docs/w4-closeout/c1-qgis-runbook.md`；QGIS 實際操作仍待設計者。 |
| WC-6 | **PASS（文件與唯讀調查）** | Product Vision 明確指出 v5 supersedes v4；README 因被歷史證據包記錄為 parent 而保持 byte-for-byte unchanged，替代說明記在未被引用的 semester blueprint revision section。C6：`docs/w4-closeout/c6-stray-sqlite-report-r02.md`。 |
| WC-7 | **PASS（驗收請求已更新；不代表驗收）** | 本 R03 補充列明目前證據、測試與具名阻塞，交由 Commander 獨立審查。 |

### 測試、預覽與操作紀錄

- Backend 全套：`RAYPATH=.:/Users/jackhsieh/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider` — **650 passed、0 failed、7 warnings**。
- Frontend：`npm --prefix web run test -- --run` — **15 files、72 tests passed**；`npm --prefix web run build -- --outDir /private/tmp/w4-closeout-web-build-r03` — **PASS**（既有 large-chunk warning）；`npm --prefix web run lint` — **0 errors、3 warnings**。
- WC-4 focused tests：`tests/test_provenance_annotations_wc4.py tests/test_pd14_authority_writer.py` — **6 passed**。C5 文件一致性：`tests/test_m2a02_r01_documentation.py` — **2 passed**。`git diff --check` — **PASS**。
- 本次沒有新增 PDOK、OSM、天氣或其他外部下載／請求；沒有 QGIS 操作、Hermes 請求、模型呼叫或權威 DB 寫入。WC-3 使用先前核准並保存的輸入；R02 package 的 fault-injection 結果為 byte mutation 與 missing parent 均 fail-closed。
- 本次預覽只讀顯示暫存 DB 副本，沒有按 Sync 或更改 state。既有 R02 walkthrough 的一次性副本 sync／reload 證據與 10 km stop-loss 均保留，不以此宣稱完整 walkthrough 通過。
- 曾有唯讀 SQLite URI 拼字錯誤在正式路徑旁建立一個 0-byte `state.sqlite3?mode=ro` 空檔；已將該空檔移至 `/private/tmp/w4-closeout-accidental-empty-uri-db-20260926T0348Z` 並確認原 DB SHA-256 不變。沒有刪除資料或清理任何既有證據。

### 尚需處理

1. 若要完成 WC-4，需明確授權六筆 PD-14 append；auto-review 本次拒絕的動作是對正式 SQLite 追加 ledger 註記。任何重試前都要重新核對 authority SHA-256。
2. 設計者依 C1 runbook 親自操作 QGIS；Commander 指派並獨立驗收完整 browser flow；Luna 與設計者完成 Live AI gate。
3. 若需完成 WC-3，需由 Commander／設計者評估是否調整可接受 runtime 預算或採取其他有證據的方法；本執行者沒有啟動被 stop-loss 阻擋的計算。

## 7. 2026-09-26 現況補充 R04

**檢查時間：** 2026-09-26 04:48 UTC。這是新的現況紀錄；R01–R03 保留為歷史紀錄。R04 工作開始時 branch `wp/w4-closeout` 的 HEAD 為 `532442e`；`wp/w5-01-decision-actor` 已是 `main` 的祖先。執行器為 Codex，與計畫指定的 AntiGravity/Gemini 不同。此補充交由 Commander 獨立審查，不構成 Week 4 接受或合併。

### 權威資料與受保護服務

- 正式資料庫 `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3`：2,498,560 bytes，SHA-256 `43c2f156fdd82547c7903fe039277e60a451fdb3fe9ee9ce53db43ee522ddc96`；唯讀 `quick_check=ok`，檢查前後 SHA-256 相同。Ledger events 為 232（sequence 1–232）；active StudyArea 為 v5、`CONFIRMED_FOR_EXPLORATION`，workspace revision 6；heads 為 Artifact 121、DatasetSnapshot 54、EvidenceCard 21、Project 1、ProvenanceAnnotation 6、StudyArea 5、ToolExecution 4、WorkspaceRevision 1。HumanDecision 與 Constraint 均為 0。
- WC-4 guarded append：DB 從 `6dd5d6e137032a8f08e3a119de2cd7399f9215f9567671c10bf7ffbda22d9fb4` 到 `4a824e6036594298252455672cc66a4c8b1b05fe1fb67f45d0843319a7bc1f30`；備份 `/Users/jackhsieh/.local/share/urban-design-backups/state_pre_pd14_annotations_20260926T042439Z_6dd5d6e13703.sqlite3`，SHA-256 `c499ad2a147886b96c9ded7f8522c741ba10131448ae13ce8b02280cecab9448`，quick check 通過。僅追加六筆 PD-14 `ProvenanceAnnotation`（ledger 216–221），舊 ledger prefix、Project 與 StudyArea heads/versions hash 保持不變。收據：`artifacts/week4-wc4-pd14-annotations/authority-write-r01/authority-write-receipt.json`。
- WC-2 guarded append：DB 從 `4a824e6036594298252455672cc66a4c8b1b05fe1fb67f45d0843319a7bc1f30` 到目前 `43c2f156fdd82547c7903fe039277e60a451fdb3fe9ee9ce53db43ee522ddc96`；備份 `/Users/jackhsieh/.local/share/urban-design-backups/state_pre_wc2_wc3_persistence_20260926T042554Z_7e149e55.sqlite3`，SHA-256 `b91de9ba1a74b2178f1e98bf83cddf5f33043b2a23550ec032126afc06d22923`。追加 11 個 ledger events（222–232）、4 Artifacts、6 EvidenceCards、1 ToolExecution；未發布 DatasetSnapshot，也未更改 StudyArea 或 workspace revision。收據：`artifacts/week4-wc2-persistence/authority-write-r02/authority-write-receipt.json`。
- 證據包 verifier：WC-2 `PASS`（8 local files、26 external parents、ledger 232）；WC-3 `PASS`（8 files、31 parents、6 layers）；WC-4 `PASS`（8 files、16 parents、6 annotations）。三包已保存的故障注入結果均為 `PASS`：原包通過、單 byte 修改及移除 parent reference 均被 `BLOCKED`。WC-2／WC-4 故障副本在 `/private/tmp` 保留；WC-3 的故障案例使用 disposable copies。
- 唯讀 `lsof` 顯示 8787 仍由 PID 80540 監聽、8644 由 PID 65898 監聽；本次未呼叫或停止這兩個服務。使用者原有 5173 未觸碰。本次 Web 預覽由任務啟動的 Vite `127.0.0.1:15174`（PID 4380）提供，API `127.0.0.1:18889`（PID 4327）；UI 使用 `/private/tmp/w4-closeout-walkthrough-r03.sqlite3` 隔離副本。兩個預覽服務暫留，使已開啟的頁面可繼續使用。
- 保留處理：六個較早的 extraction outputs 從 `artifacts/week4-regional-osm/extracted/` 移至 `/Users/jackhsieh/.local/share/urban-design-data/week4-regional-osm/retained-earlier-extraction-r01/`；沒有丟棄 bytes，六個 size／SHA-256 均符合 `artifacts/week4-regional-osm-earlier-extraction-relocation-r01/retention-manifest.json`。舊 `syntax_results/` 保留原位，沒有覆寫。WC-3 已保存的 fault runner 使用 Python `TemporaryDirectory`，因此測試副本由該 runner 自動清理；故障結果仍保存在 `integrity-fault-results.json`。本次未再清理或刪除檔案。

### 最新 Gate 判定

| Gate | R04 狀態 | 證據與解除條件 |
|---|---|---|
| CP4-0 權威狀態 | **PASS** | 上述 hash、quick check、ledger/head counts、revision 與 active StudyArea v5。 |
| CP4-1 QGIS GUI 同步 | **BLOCKED（負責人：設計者）** | 仍須設計者依 `docs/w4-closeout/c1-qgis-runbook.md` 親自操作並提供畫面及同步狀態。 |
| CP4-2 保留與分區 | **BLOCKED（待獨立驗收）** | R02 的 disposable DB walkthrough 保留了互動與 reload 證據；尚不構成完整的獨立 walkthrough 或正式端驗收。 |
| CP4-3 基地分析 | **BLOCKED（待完整 UI 驗收）** | persisted Artifact／EvidenceCard／ToolExecution 已存在；預覽顯示 7 張 evidence cards，但來源與未知事項仍需獨立檢查。 |
| CP4-4 六張 Syntax | **BLOCKED（10 km stop-loss）** | WC-3 R02 有四個探索性已計算層、兩個未計算 10 km 層；UI plan/result mapping 已修正並新增 regression test。此次只目視檢查預覽載入狀態，Syntax 分頁未能安全驗收，詳見下節。 |
| CP4-5 圖面輸出 | **BLOCKED** | 本次未測試 PNG／SVG 匯出。 |
| CP4-6 人類決策保護 | **PASS（保護範圍）** | DB 無 HumanDecision／Constraint；10 km unavailable 層沒有合成零值；本次未批准任何決策。 |
| CP4-7 Live AI | **BLOCKED（負責人：Luna 與設計者）** | 未呼叫 provider；待 W5-AI 及設計者憑證配置。 |
| CP4-8 獨立 walkthrough | **BLOCKED** | 隔離預覽載入 Ariadne、v5、rev 6、同步狀態與 evidence cards；未完成完整操作、匯出與 Live AI。Playwright runner 未能在此環境完成獨立流程。 |
| WC-0 | **PASS** | Branch、main 合併關係及權威資料狀態已核對。 |
| WC-1 | **PASS** | R40–R55 triage 保留。 |
| WC-2 | **PASS（持久化與權威 append 範圍）** | Guarded writer 收據、authority readback、R02 verifier/fault evidence 及完整 pytest。 |
| WC-3 | **BLOCKED（具名 stop-loss）** | 800 m 與 2 km 保留為探索結果；2 km 兩指標 stability Spearman 為 0.9997／0.9980。10 km screening 預估為 15 km envelope 16,527.9 秒、20 km envelope 30,054.3 秒，均超過單次 7,200 秒上限，故未啟動計算。800 m 邊界穩定性未驗證；OSM 完整性未建立、network policy 尚待設計者批准。 |
| WC-4 | **PASS（六筆 append）** | 六筆 PD-14 註記及 immutable ledger-prefix readback 見 WC-4 receipt。 |
| WC-5 | **PASS（runbook）** | `docs/w4-closeout/c1-qgis-runbook.md`；QGIS GUI 仍待設計者。 |
| WC-6 | **PASS（文件／唯讀調查）** | Product Vision 指向 active v5；README 未改，既有 C6 調查報告保留。 |
| WC-7 | **PASS（驗收請求已更新；不等於接受）** | 本 R04 明列目前 gate、權威狀態、測試與具名阻塞，交 Commander 審查。 |

### R04 測試與介面檢查

- 完整 Python suite：`RAYPATH=.:/Users/jackhsieh/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider` — **652 passed、0 failed、7 warnings，382.62 秒**。
- Frontend：`npm --prefix web run test -- --run` — **15 files、72 tests passed**；`npm --prefix web run build -- --outDir /private/tmp/w4-closeout-web-build-r04` — **PASS**，有既有 large-chunk warning；`npm --prefix web run lint` — **0 errors、3 warnings**。
- 介面已在 Codex 瀏覽器開啟 `http://127.0.0.1:15174/`。實際畫面顯示 Ariadne 品牌、Rotterdam M4H、StudyArea v5、revision、`CONFIRMED_FOR_EXPLORATION`、In Sync 與七張卡片；頁面使用隔離 SQLite 副本，未按 Sync。嘗試切換 Syntax 時意外出現「Confirm human decision」檢查對話框；未輸入理由或密語、未確認，按 Escape 關閉。該分頁的 Syntax GUI 呈現因此標為未驗證；單元測試與 API contract 測試不取代此人工驗收。
- R04 沒有新發送 PDOK／OSM／天氣或模型服務請求，沒有操作 QGIS／Hermes，也沒有新增 DatasetSnapshot、HumanDecision 或 Constraint。WC-3 R02 使用已保留資料；其結果不是已批准的 network policy 或正式規劃結論。Week 4 整體仍為 **INCOMPLETE**。

### 交由獨立審查／設計者的事項

1. Commander 獨立檢查 R04 的 guarded authority append、證據包與 diff；設計者依 C1 runbook 完成 QGIS GUI gate。
2. 10 km Syntax 要待 Commander／設計者評估 stop-loss 預算；在新決策前保持未計算，不得以替代來源或估值補值。設計者仍須批准 network policy，並確認來源完整性限制。
3. 由獨立審查者完成含保存、分區、六層 Syntax、Live AI、匯出與重新載入的 walkthrough；本執行器不宣告 Week 4 通過。

### 提交後 parent-hash 對帳（04:55 UTC）

- 提交後重驗發現 WC-2 R02 將 WC-4 R01 的原始 `integrity-manifest.json` SHA-256 `35ac6f20204f6841682f12a8b7f08b6730e669c5df27aa3c91330cc3181c2f30` 固定為 parent。先前為清除 package Markdown 的 intentional hard-break 空白而刷新 WC-4 manifest，導致 WC-2 verifier fail-closed。
- 已從原先暫存的 Git blobs 還原 WC-4 R01 的 manifest、builder 與 docket 原始 bytes；未改寫 WC-2 R02。WC-2／WC-3／WC-4 verifier 隨後均通過，權威 DB hash 不變。修復以新 commit 追加保留，未 reset 或改寫 branch 歷史。
- WC-4 R01 的原始 Markdown hard-break 尾端空白為維持與 WC-2 的 parent hash 所必需；其專屬 staged check 排除此 intentional whitespace。還原提交後一般工作樹 `git diff --check` 通過。

### R05 程式語義與最終驗證補充（2026-09-26 05:27 UTC）

- WC-3 衍生的 Syntax readiness 現將「extract 是否涵蓋要求的分析包絡」記為 `extract_covers_envelope`（`true`／`false`／`null`），不再接受含義過寬的 `source_complete` 布林值。即使包絡包含範圍且半徑穩定性已有證據，單靠這些條件仍維持 `BLOCKED_SOURCE_COMPLETENESS_UNVERIFIED`；這不證明 OSM feature、語義或 network 完整性。Figure renderer 拒絕舊欄位，並阻止未涵蓋 extract 被標為 `VALIDATED_COVERAGE`。
- 最終完整 Python suite：`RAYPATH=.:/Users/jackhsieh/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider` — **657 passed、0 failed、7 warnings，379.64 秒**。既有 frontend 程式未變更；沿用 R04 所記錄的 frontend 15 files／72 tests、build PASS、lint 0 errors／3 warnings。
- 本次重跑的 WC-2 R02 verifier：**PASS**（8 local files、26 external parents、232 ledger events）；WC-3 R02：**PASS**（8 local files、31 parents、6 layers）；WC-4 R01：**PASS**（8 local files、16 parents、6 annotations）。舊 `artifacts/week4-regional-osm/verify_package.py` 仍 **FAIL**：plan-decisions 文件 parent hash mismatch，且 `syntax_results/` 下有四個未列入 manifest 的歷史輸出；保留原包未改寫，WC-3 R02 仍是通過驗證的追加包。
- 正式 authority DB 唯讀複核：SHA-256 `43c2f156fdd82547c7903fe039277e60a451fdb3fe9ee9ce53db43ee522ddc96`、`quick_check=ok`、ledger 232；Project revision 6 仍指向 StudyArea v5 `CONFIRMED_FOR_EXPLORATION`。heads：Artifact 121、DatasetSnapshot 54、EvidenceCard 21、Project 1、ProvenanceAnnotation 6、StudyArea 5、ToolExecution 4、WorkspaceRevision 1。本次沒有 authority write、DatasetSnapshot、HumanDecision 或 Constraint。
- Ariadne 介面已在 Codex 內建瀏覽器前景開啟 `http://127.0.0.1:15174/`，畫面顯示 Ariadne、Rotterdam M4H、StudyArea v5、workspace rev 6、`CONFIRMED_FOR_EXPLORATION`、In Sync 與 7 張 evidence cards。這是以 disposable SQLite 副本提供的預覽；只讀目視，沒有按 Sync 或修改工作區。8787 由 PID 80540 監聽、8644 由 PID 65898 監聽，僅以 `lsof` 觀察，未呼叫或停止。
- 獨立完整 walkthrough 仍 **BLOCKED**：`web/e2e/workspace_flow.py` 在啟動前因環境缺少 `playwright` 套件而以 `ModuleNotFoundError` 結束；未安裝依賴或改用網路。Syntax 分頁的 GUI 驗收仍待設計者／獨立審查者；先前開啟的人類決策確認對話框已在未輸入資料、未確認的情況下關閉。CP4-1 QGIS、CP4-4 10 km／網路完整性、CP4-5 匯出、CP4-7 Live AI 與 CP4-8 walkthrough 仍未解除，Week 4 維持 **INCOMPLETE**。

### R06 disposable-browser recheck (2026-09-26 05:52 UTC)

- 預覽 Vite listener 為 PID 4380、工作目錄在本 worktree 的 `web/`；API listener 為 PID 4327、port 18889。`lsof` 顯示 API 開啟的是 `/private/tmp/w4-closeout-walkthrough-r03.sqlite3`。此副本 SHA-256 `90c4fedfdaf693f72cd969242a0ff787707176d2cb3310e943f9a9c44b65f289`、`quick_check=ok`、ledger 232。權威 DB 本回合前後 SHA-256 均為 `43c2f156fdd82547c7903fe039277e60a451fdb3fe9ee9ce53db43ee522ddc96`，`quick_check=ok`、ledger 232；本回合沒有權威寫入。
- 在暫時 1440×900 瀏覽器視窗檢查 Syntax 分頁，實際呈現六層且沒有 plan/result mismatch：800 m 兩層為 `COMPUTED` 但 boundary stability 未驗證；2 km 兩層為探索性結果並明示 extract completeness／語義未證；10 km 兩層為 `NOT_COMPUTED_RUNTIME_BUDGET`，沒有 metric values，並列出 15 km／20 km screening estimate。這解除先前的 UI mapping 呈現問題，不解除 10 km 或來源完整性 gate。視窗尺寸驗收後已 reset。
- 初次以數字 AX 索引操作誤開 `Confirm human decision`（StudyArea v5、Action `Inspect`）；沒有輸入 reason 或 decision key，沒有送出，按 Escape 關閉。其後以 Syntax 按鈕鍵盤操作成功切換面板。沒有建立 HumanDecision 或呼叫 decisions API。
- 2D 圖面匯出第一次在狹窄預覽尺寸回報 `The 2D map viewport is not ready for export.`。桌面尺寸下 canvas 為 760×759，頁面狀態回報 `PNG downloaded · workspace-rotterdam-m4h-pilot-project r6 · COMPUTED_EXPLORATORY`；瀏覽器 download event 等待逾時，且預期檔名在 Downloads／`/private/tmp` 未找到。未能獨立讀取 PNG bytes，因此 CP4-5 仍 **BLOCKED（輸出檔案未驗證）**；瀏覽器 console 沒有 error／warning。
- Ariadne 分頁仍留在前景。完整 walkthrough 仍受缺少 Python `playwright` 套件阻塞；本回合未安裝依賴、未操作 QGIS、未接觸 Hermes，未變更任何舊證據包。畫面截圖在執行回合中呈現，但本回合未新增截圖檔至證據目錄。

## 11. 2026-09-26 現況補充 R07

**檢查時間：** 2026-09-26 10:47 UTC。此節記錄 Codex 在 `wp/w4-closeout` 的續作，交 Commander 獨立審查；不是設計者接受、不是 milestone closeout，也不授權合併。

### Git、權威資料與執行界線

- 工作樹 `/Users/jackhsieh/Downloads/TUD/Q5/w4-closeout`，branch `wp/w4-closeout`，續作起點 HEAD `96d60e4`；`main` 為 `d9c9afa`。`wp/w5-01-decision-actor` 是 `main` 的祖先。本節提交只會在 `wp/w4-closeout`。
- `5badc6c` 已由既有 commit `81d7cb0` 以 `git revert` 撤回；`scripts/approve_m2a03_spatial_inputs.py` 使用 `getpass.getpass`。本回合沒有讀取或記錄密語。
- 開工說明中的 authority ledger 187 已過時：本回合前後唯讀觀察到正式 DB `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3` SHA-256 均為 `43c2f156fdd82547c7903fe039277e60a451fdb3fe9ee9ce53db43ee522ddc96`、`quick_check=ok`、ledger 232、ProvenanceAnnotation 6（事件 216–221）。Artifact 121、DatasetSnapshot 54、EvidenceCard 21、ToolExecution 4、Project revision 6 指向 StudyArea v5；HumanDecision／Constraint 均為 0。此回合對正式 DB 寫入為 **0**。
- worktree 內 `.urban_design_runtime/state.sqlite3` 是另一份 seed，SHA-256 `965c5db387ecc86592fb5d82f2e3903181b321bab1c2c72670f0377d5629db20`、ledger 200；不得把它稱為正式 DB。
- 正式 DB 的 ledger schema 已有 `actor_kind`、`actor_session_id`。若未來對尚未遷移的 DB 首次以可寫模式開啟 `ProjectStateStore`，該次開啟會套用 W5-01 ledger schema migration；所有寫入前必須先完成 `.backup` 並記錄原始 SHA-256。R08／R09 副本演練沒有改寫正式 DB。

### WC-3：新一輪實測、stop-loss 與資料保留

- 沒有重新下載 PBF。既有 15 km／20 km envelope extract manifests 的 `extract_covers_envelope=true`，line count 分別為 152,287、238,994；這只表示 extract 包住分析包絡，不表示 OSM 要素、語義或路網完整。
- 使用同一 PST 方法，測得：800 m／1,500 m extract **2.166 秒**；2 km／4 km **22.830 秒**；2 km／6 km **63.767 秒**；另以 800 m／6 km 做 runtime benchmark **23.742 秒**。
- 2 km 比較通過既定 Spearman ≥0.98 判準：NAIN **0.999703**、NACH **0.998031**。兩項各有 1 個 common segment 變化超過 5%（513 個中 0.195%），標記 `EDGE_AFFECTED`。此結果不建立 800 m 邊界穩定性。
- 篩選預估 10 km／15 km envelope **14,672.618 秒（約 4.08 小時）**，20 km envelope **25,820.290 秒（約 7.17 小時）**，都超過每次 7,200 秒上限。依 stop-loss 沒有啟動 10 km PST 計算；兩個 10 km 圖層維持 `NOT_COMPUTED_RUNTIME_BUDGET`，不填零值。
- 完整小型 JSON 輸出與 hash manifest：`artifacts/week4-wc3-runtime-rerun-r07/`；manifest SHA-256 `6aa63c26e08217bdae2b880cabd3a3b69eae5d5b115115912129d1471256ac2f`。其中記錄 PBF、poly、extract manifests、每個輸出 JSON 的 SHA-256、實測時間、估算與 stability。沒有複製或提交抽取 GeoJSON。
- 計算最初指向預設共享資料目錄時被 sandbox 拒絕寫入；改用 `/private/tmp/week4-syntax-r07-20260926T101310Z` 成功完成，原始暫存輸出保留。manifest 首版曾從錯誤層級讀取 extraction 欄位，已在 R07 manifest revision 2 依原始 extraction manifests 修正 `extract_covers_envelope`／line count；來源和計算輸出 bytes 未改。

### WC-2：型別化持久化與 DB 副本演練

- 修正 `analysis_persistence.py` 的 SHA-256 表示法，讓 Artifact、ToolExecution 輸入／輸出 hashes 符合 domain schema `sha256:<64 lowercase hex>`；ToolExecution schema 現明列 snapshot hash map、Artifact IDs 與 Artifact hash map。基地分析另存型別化 EvidenceCard，其巢狀 `EvidenceResult` 與輸出 Artifact／ToolExecution hash 相符；歷史 R04 原始卡片封包仍作 API 讀取與 source-result alignment 的依據。
- `tests/test_analysis_persistence.py`：**8 passed、0 failed**；新增 Artifact／ToolExecution／EvidenceCard 模型驗證與輸出 hash 一致性斷言。
- R08 使用 worktree seed 的唯讀 SQLite backup 副本：ledger **200→228**，舊事件 1–200 prefix 相同，來源 seed hash 前後不變；Site Analysis 為 `VERIFIED_SOURCE_RESULT_ALIGNMENT`、回傳 7 張卡，六張 Syntax 圖層為 4 computed＋2 `NOT_COMPUTED_RUNTIME_BUDGET`。3 個 ToolExecution、3 個輸出 Artifact、15 張型別化 EvidenceCard 通過模型驗證。收據：`artifacts/week4-wc2-copy-r08/copy-persistence-receipt.json`。
- R09 直接從正式 DB 唯讀 backup 到 worktree 後演練：副本 ledger **232→245**、舊事件 1–232 prefix SHA 前後一致、`quick_check`／`integrity_check` 均為 `ok`；3 個 ToolExecution、3 個輸出 Artifact、21 張型別化 EvidenceCard 通過驗證。Site Analysis 7 張卡及六層狀態讀回成功。正式來源 DB SHA 前後不變。收據：`artifacts/week4-wc2-copy-r09-current-authority/copy-persistence-receipt.json`。
- 正式 DB 尚未套用這次 schema 正規化；唯讀模型驗證顯示現有 WC-2 ToolExecution／Artifact 仍有裸 hash。R09 將修正演練在**正式 DB 的副本**完成。Commander 審查後若決定套用，須用下方 guarded writer，重新核對當時 authority hash；不可直接重用本節舊 hash。

### WC-4：PD-14 註記副本演練

- 從 worktree seed 複製 SQLite 後執行 `scripts/annotate_pd14_ledger.py`，只在副本追加 events 182–187 的 6 個 ProvenanceAnnotation：ledger **200→206**。收據中 1–187 及既有 1–200 的 typed SQLite row hashes 前後一致；HumanDecision／Constraint 未建立或變更。SQLite `.backup` 快照及收據保留於 `artifacts/week4-wc4-copy-r07/`。
- 正式 DB 已有 6 筆註記（216–221）；本回合沒有再寫入或重送 authority append。

### 瀏覽器預跑

- 以 `artifacts/week4-wc2-copy-r08/state-copy.sqlite3` 為 seed 呼叫 `web/e2e/workspace_flow.py`。第一次 worktree Python 因缺 `playwright` 在啟動前結束；未建瀏覽器或埠。第二次使用已安裝 Playwright 的本機 Python，runner 在 `e2e_ports.py` 綁定 `127.0.0.1:0` 時收到 sandbox `PermissionError: [Errno 1] Operation not permitted`，尚未啟動 API、Vite 或瀏覽器。遵守停損，沒有改用其他瀏覽器／埠路徑。
- 沒有截圖；`artifacts/week4-walkthrough-r07/` 未建立。CP4-8 維持 **BLOCKED**。

### CP4 與 WC-0–WC-7

| 項目 | R07 狀態 | 證據／解除條件 |
|---|---|---|
| CP4-0／WC-0 起點 | **PASS（唯讀查核）** | 本節記錄 branch、revert、authority hash／ledger；權威寫入 0。 |
| CP4-1／WC-5 QGIS GUI | **BLOCKED（設計者）** | `docs/w4-closeout/c1-qgis-runbook.md`；Jack 須本人操作並提交同步畫面／狀態。 |
| CP4-2 保留、分區 | **BLOCKED（未做完整 UI walkthrough）** | R07 browser runner 被 sandbox 埠權限阻止；既有 R02/R06 evidence 不替代本次完整驗收。 |
| CP4-3 基地分析 | **PASS（副本後端持久化）；BLOCKED（完整 UI 驗收）** | R08/R09 收據；正式 DB schema normalization 待 Commander 審查及 Jack 決定。 |
| CP4-4／WC-3 六層 Syntax | **BLOCKED（10 km stop-loss）** | R07 runtime manifest；4 層 computed、2 層 `NOT_COMPUTED_RUNTIME_BUDGET`。預估均高於 7,200 秒；來源完整性及 800 m 穩定性仍未證明。 |
| CP4-5 圖面輸出 | **BLOCKED** | 本回合無瀏覽器，未讀取匯出 bytes。 |
| CP4-6 人類決策保護 | **PASS（副本／schema 範圍）** | R08/R09/WC4 收據沒有建立 HumanDecision 或改 Constraint。 |
| CP4-7 Live AI | **BLOCKED** | 沒有模型呼叫；仍需 W5-AI 與 Jack 配置。 |
| CP4-8 獨立 walkthrough | **BLOCKED** | Python Playwright 缺件及 sandbox loopback bind 拒絕；無截圖。 |
| WC-1 triage | **PASS（既有）** | `docs/w4-closeout/r40-r55-triage.md`。 |
| WC-2 persistence | **PASS（typed code／tests／兩份副本）；authority normalization pending** | R08、R09 receipt；`tests/test_analysis_persistence.py` 8 passed。 |
| WC-4 provenance | **PASS（副本演練；authority 既有六筆）** | `artifacts/week4-wc4-copy-r07/annotation-receipt.json`。 |
| WC-6 文件與 C6 | **PASS（既有；本回合未改舊證據包）** | R04/R05 說明及 `docs/w4-closeout/c6-stray-sqlite-report-r02.md`。 |
| WC-7 acceptance request | **PASS（本節已更新；不等於接受）** | R07 交 Commander 審查。 |

Week 4 維持 **INCOMPLETE**。

### R07 tests

- Python（指定完整命令）：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src RAYPATH=$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib PATH=$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin:$PATH /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/pytest -q -p no:cacheprovider` — **collected 657；657 passed、0 failed、0 skipped；7 warnings；398.12 s**。
- `npm --prefix web run test` — **BLOCKED before collection**：Vite 嘗試寫 `web/node_modules/.vite-temp/...` 時 `EPERM`。支援的 `configLoader=runner` 不需建立該檔；`npm --prefix web run test -- --configLoader=runner` — **15 files／72 tests passed、0 failed、0 skipped；1.96 s**。
- `npm --prefix web run build -- --outDir /private/tmp/w4-closeout-web-build-r07 --configLoader=runner` — TypeScript 因共用唯讀 `web/node_modules/.tmp/*.tsbuildinfo` 回 `EPERM`。在兩個 TypeScript project 分別將 build info 導向 `/private/tmp` 後型別檢查通過，再於 `web/` 執行 Vite build，**1,899 modules transformed，build PASS**；輸出在 `/private/tmp/w4-closeout-web-build-r07/`，有既有 >500 kB chunk warning。`web/dist` 未清理或覆寫。
- `npm --prefix web run lint` — **0 errors、3 warnings**（既有 App／Viewport2D state-in-effect 及 hook dependency warnings）。
- 沒有修改 `web/index.html` 或 `web/src/index.css`。本回合未呼叫網路、OSM/Pdok、模型、QGIS 或 Hermes；也未刪除／清理既有 worktree evidence。

### Commander／設計者後續步驟

1. **先由 Commander 審查 R07 diff 和 R08/R09 副本收據；Jack 保留最終決定權。** 以下 authority 命令僅為後續受審查操作說明，本回合未執行。執行前要重新唯讀查 SHA-256、`quick_check`、ledger／heads，且確認本分支的腳本已被審查。
2. WC-2 若決定寫入正式 DB，先建立手動 `.backup`，再用 fresh SHA guard 執行 writer。writer 還會在第一次可寫 `ProjectStateStore` 開啟前自行建立第二份 `.backup`；若 DB 尚未具備 W5-01 的 `actor_kind`／`actor_session_id` 欄位，該首次可寫開啟會觸發 ledger schema migration。

```bash
cd /Users/jackhsieh/Downloads/TUD/Q5/w4-closeout
DB=/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3
BACKUP_DIR="$HOME/.local/share/urban-design-backups"
STAMP=REPLACE_WITH_UNIQUE_UTC_STAMP
BACKUP="$BACKUP_DIR/state_pre_wc2_manual_${STAMP}.sqlite3"
BEFORE_SHA=REPLACE_WITH_FRESH_64_HEX_FROM_SHASUM
mkdir -p "$BACKUP_DIR"
shasum -a 256 "$DB"                     # 確認並抄下當下 BEFORE_SHA
sqlite3 "$DB" ".backup $BACKUP"          # 手動寫前快照
sqlite3 "$BACKUP" "PRAGMA quick_check;"
shasum -a 256 "$BACKUP"                 # 把快照 hash 記錄於審查紀錄
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python scripts/persist_analysis_results.py \
  --database "$DB" \
  --syntax-package-dir artifacts/week4-wc3-regional-syntax-r02 \
  --write-authority --expected-sha256 "$BEFORE_SHA" \
  --backup-dir "$BACKUP_DIR" \
  --receipt-out artifacts/week4-wc2-persistence/authority-write-r03/authority-write-receipt.json
shasum -a 256 "$DB"                     # 記錄 AFTER_SHA，與 receipt 對帳
sqlite3 "$DB" "PRAGMA quick_check; SELECT COUNT(*), MAX(sequence) FROM ledger_events;"
```

3. WC-2 若已套用，重新唯讀記錄 authority SHA、`quick_check`、ledger heads，再檢查 PD-14 註記。**目前 authority 已有六筆註記**，所以應讀取既有收據／驗證結果，不需要再追加。只有 fresh readback 顯示缺漏、且 Jack 決定補寫時，才以重新讀到的 SHA 填入 `AFTER_WC2_SHA`，再執行下方 guarded writer；它會在實際補寫前 `.backup`，並核對舊事件 1–187 bytes。

```bash
AFTER_WC2_SHA=REPLACE_WITH_FRESH_64_HEX_FROM_SHASUM
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python scripts/annotate_pd14_ledger.py \
  --database "$DB" --expected-sha256 "$AFTER_WC2_SHA" --write-authority \
  --backup-dir "$BACKUP_DIR" \
  --receipt-out artifacts/week4-wc4-pd14-annotations/authority-write-r02/authority-write-receipt.json
shasum -a 256 "$DB"                     # 記錄註記完成後的 SHA-256
sqlite3 "$DB" "PRAGMA quick_check; SELECT COUNT(*), MAX(sequence) FROM ledger_events;"
```
4. WC-3 選項：保持兩個 10 km 層 `NOT_COMPUTED_RUNTIME_BUDGET`；或由 Commander 與 Jack 明確核定更高單次時間預算與資源後，逐一執行並重做穩定性分析；或先對 deterministic PST 作效能剖析、重測 800 m／2 km、重新估算。當前預估不是完成計算的保證，也不能以替代估值補值。
5. CP4-1 由 Jack 親自完成 QGIS；完整 browser walkthrough 要在允許 loopback bind 且具備 Playwright 的受控環境重跑，並保存實際截圖／匯出 bytes。Commander 再獨立審查後，由 Jack 決定接受或拒絕；此執行者不驗收、不合併 `main`。


## 12. 2026-09-27 現況補充 R08

**檢查時間：** 2026-09-27 01:18 UTC。此節是 Codex 在 `wp/w4-closeout` 的續作紀錄，交 Commander 獨立審查；不是設計者接受、不是 milestone closeout，也不授權合併。

### 起點、權威資料與隔離預覽

- 起點 HEAD `2e8b347`，branch `wp/w4-closeout`；本節只追加驗收文件與新的 walkthrough/export evidence。原有未追蹤 `.venv`、R01/R02 walkthrough 副本、WC-2 R07–R09 副本及 WC-4 R07 副本均保留，未覆寫或清理。
- 正式 DB `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3` 唯讀核對：2,498,560 bytes，SHA-256 `43c2f156fdd82547c7903fe039277e60a451fdb3fe9ee9ce53db43ee522ddc96`，`quick_check=ok`、schema version 2、ledger 232。Heads：Artifact 121、DatasetSnapshot 54、EvidenceCard 21、Project 1、ProvenanceAnnotation 6、StudyArea 5、ToolExecution 4、WorkspaceRevision 1；HumanDecision 與 Constraint 均為 0。Project revision 6 的 active StudyArea 是 v5，狀態 `CONFIRMED_FOR_EXPLORATION`。本次權威 DB 寫入為 0。
- Vite `127.0.0.1:15174` PID 4380、API `127.0.0.1:18889` PID 4327。API 開啟的隔離副本 `/private/tmp/w4-closeout-walkthrough-r03.sqlite3`：2,498,560 bytes，SHA-256 `90c4fedfdaf693f72cd969242a0ff787707176d2cb3310e943f9a9c44b65f289`，`quick_check=ok`、ledger 232、workspace revision 6。匯出只在此副本畫面操作，沒有 Sync、Critic dispatch 或其他 DB 寫入。
- Browser title `Ariadne — Rotterdam M4H Pilot`；StudyArea v5、7 張 Evidence Cards、51 buildings、140 roads。Syntax 顯示六層：800 m 兩層 computed 但 boundary stability 未證；2,000 m 兩層 exploratory；10,000 m 兩層 `NOT_COMPUTED_RUNTIME_BUDGET` 且沒有 metric value。所選 800 m NAIN 的畫面摘要為 514 segments，readiness `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`，source manifest/result unavailable。

### R08 匯出 bytes

新增 append-only 證據目錄：`artifacts/week4-walkthrough-r08/run-20260927T011814Z/`，包含兩個輸出、`export-receipt.json` 與 `integrity-manifest.json`。Manifest 逐檔列 size、SHA-256 與 parent path/hash；self excluded。獨立驗證 **3/3 files、全部 parent references 通過，0 errors**。

- **2D PNG：** 在隔離預覽以 CUA 點擊 `Export analysis map figure (PNG)`。頁面回報 `PNG downloaded · workspace-rotterdam-m4h-pilot-project r6 · COMPUTED_EXPLORATORY`；輸出存在於 `~/Downloads/rotterdam-m4h-week4-analysis-map-v1-workspace-r6-study-area-rotterdam-m4h-pilot-project-v5.png`，並逐 byte 複製至上述證據目錄。尺寸 1,112,306 bytes、SHA-256 `04a4406a2430c044b28ce02cbe405d09a0b9e40761555c0a116833b900c8eea2`，PNG 1440×2973。已目視檢查：畫面保留 StudyArea 輪廓及目前 2D 底圖，列出 workspace r6、StudyArea v5、51 buildings、140 roads、0 draft zones、選取的 800 m NAIN；明示 `COMPUTED_EXPLORATORY`、source/result unavailable 及資料限制。PNG 內記錄匯出 UTC `2026-09-27T01:18:14.526Z`。這證明隔離副本上的 2D PNG bytes 可產生及讀取，不等於完整 walkthrough 或設計結論。
- **SVG：** 以瀏覽器下載 Syntax 面板的 “Download explicitly exploratory 800 m figure (SVG)” 連結，URL 為 `http://127.0.0.1:18889/api/v1/projects/rotterdam-m4h-pilot-project/syntax/exploratory-figure.svg`。下載完成；browser download API 沒有回報 HTTP status，故不宣稱本次已觀測到狀態碼。輸出 160,687 bytes、SHA-256 `b4f175270a1a12f08af4589ab0ad4fe8471617d78e3f9d26df221ca220e258f0`，SVG XML well-formed、1240×850。檔案標示 `BLOCKED_COVERAGE_EVIDENCE_ABSENT`、`NOT A FORMAL ROTTERDAM RESULT`、`spatial-r01`，並記載 1,328 linework／1,272 帶值／56 無值／source-mapped network 1,355。這是已保留的 R03 source-linked historical figure；其 figure record SHA-256 `6241fe22444c939c17ff5c75cec9b0ac7434155bb06f21550d833fa1b9b68be3`，凍結 SVG parent SHA-256 `e3a70e5775c65d0a35cc5bbee8e4208291f773fbadaa27530236ae50a2853d0e`。它與當前 UI 所選 persisted layer 的 514-segment 摘要不同；不可當成符合目前 layer 的匯出。
- R08 確認前端有目前 viewport 2D PNG button、3D PNG button與獨立 800 m historical SVG 連結；在 `web/src`／API export route 搜尋不到 GeoJSON 匯出入口。3D PNG、GeoJSON，以及 SVG 與目前 persisted view 的一致性均未驗證。故 **CP4-5 僅 2D PNG 子範圍有 bytes 證據，整體仍 BLOCKED**。
- 首次 Playwright `download` event wait 逾時，之後以 CUA 直接按 UI 匯出按鈕並取得實際 PNG。這是對觀測方式的修正，不是再次執行 runner。另一次唯讀 SQLite 探查誤用了不存在的 `schema_migrations` 表；已依實際 `store_metadata.schema_version` 修正查詢，兩次均無 DB 寫入。

### R08 gates、測試與剩餘工作

- **CP4-5：BLOCKED（整體）**；2D PNG bytes 驗證通過。SVG bytes 驗證通過但屬 historical R03 輸出且與目前 layer 不同；GeoJSON 與 3D 匯出未驗證。
- **CP4-8：BLOCKED。** 完整 `web/e2e/workspace_flow.py` 仍未跑完：R07 的 worktree Python 缺 Playwright；替代 Python 在 sandbox 埠 bind 被拒絕。R08 不重啟或再繞行 runner，也未保存完整瀏覽器 walkthrough 截圖。此節保存的是匯出的地圖圖面，不是完整 UI walkthrough 截圖。
- CP4-1 QGIS GUI 仍由 Jack 本人操作；CP4-4 10 km 兩層維持 stop-loss 未計算，且 OSM 完整性／網路政策與 800 m boundary stability 未解；CP4-7 無 Live AI 呼叫，仍待 W5-AI 與設計者配置。WC-2 正式 DB hash normalization 仍待 Commander 審查及 Jack 決定是否執行；WC-4 正式 DB 已有六筆來源註記，不重送。Week 4 維持 **INCOMPLETE**。
- R08 focused regression tests：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_figure_export.py tests/test_week4_r03_syntax.py tests/test_analysis_persistence.py` — **15 passed、0 failed、1 warning，40.41 s**。完整 Python 657 passed／0 failed／0 skipped、Web 15 files／72 tests、build 與 lint 結果仍沿用 R07 記錄；R08 只新增文件與匯出證據，沒有更動程式碼，所以未重跑完整套件。
- 本次沒有 PDOK／OSM／weather 外部請求、模型呼叫、QGIS 操作、Hermes 存取、authority write、DatasetSnapshot、HumanDecision 或 Constraint。

### R08 交接

1. Commander 審查 R07–R08 程式與新增 export receipt/hash lineage；本執行者不驗收、不合併。
2. Jack 完成 C1 QGIS GUI gate；由 Commander／Jack 決定 10 km stop-loss 預算與 WC-2 authority normalization。
3. Commander 指派或獨立執行完整 walkthrough；需具備可用 Playwright／loopback 環境及實際 UI 截圖。要測 GeoJSON／3D 或目前 persisted layer 對應的 SVG，先由 Control Tower 裁定需求／實作範圍；不得把 historical SVG 當目前 view 證據。

## 13. 2026-09-27 現況補充 R09

**檢查時間：** 2026-09-27 01:29–01:38 UTC。R09 是對 R08「完整 walkthrough 尚未執行」狀態的後續驗證紀錄；不代表設計者接受或 Week 4 通過。

### 完整 runner 驗證

- 使用 Python 3.12.13（已安裝 Playwright）與既有 Google Chrome，執行原始 `web/e2e/workspace_flow.py`，以正式 DB 唯讀製作暫存副本，輸出寫入 `artifacts/week4-walkthrough-r09/run-20260927T012900Z/`。腳本選擇隔離埠 API `127.0.0.1:54625`、Vite `127.0.0.1:54645`；兩個 child service 均在失敗後正常關閉，埠上沒有遺留 listener。未操作既有預覽埠、Hermes `8787` 或 QGIS bridge `8788`。
- 兩個本機 HTTP 檢查均為 200：`GET /health` 與 `GET /api/v1/projects/rotterdam-m4h-pilot-project/site-context`。runner 在 API contract gate 以 exit code 1 停止，尚未執行 Chromium launch；因此沒有 UI walkthrough、screenshots、workspace sync 或副本寫入。保留的 server logs 可核對服務生命週期。
- 阻塞條件不是 Playwright／loopback：API 回應含六個 Syntax layer、六個計劃項目、四個 computed layer 及兩個 10 km `NOT_COMPUTED_RUNTIME_BUDGET` layer。10 km layer 沒有值且 `statistics` 為 null。但所有六筆 PST layer 都缺少 `formal_result_eligible` 欄位；runner 要求此欄位明確為布林 `false`，所以 fail closed。沒有把缺欄位推定為 false，也沒有修改 runner 或既有 Artifact。
- 以同一正式 DB 的唯讀 SQLite backup 另用 FastAPI TestClient 重現；暫存副本 `quick_check=ok`、ledger 232。GET 回應 HTTP 200，條件結果仍為 false。完整 API body 未複製保存（含基地幾何）；`api-site-context-diagnostic.json` 保留 body SHA-256、層級狀態和每層欄位存在性。
- 正式 DB 前後 SHA-256 都是 `43c2f156fdd82547c7903fe039277e60a451fdb3fe9ee9ce53db43ee522ddc96`，2,498,560 bytes；沒有 authority write。未發出模型、PDOK、OSM 或天氣請求，未建立新 DatasetSnapshot／HumanDecision／Constraint。

### R09 證據、測試與交接

- R09 證據目錄包含 API／Vite server logs、API contract 診斷、runner failure report 與 `integrity-manifest.json`。Manifest 列出每個檔案的 size、SHA-256、kind、parent paths/hash，並排除 manifest 自身。新列出的 4/4 檔案及所有 parent hash 已獨立驗證。
- 驗證結果：原始完整 E2E runner **BLOCKED**（在 Chromium 前失敗）；獨立 TestClient API GET **PASS（HTTP 200）**，但 formal-eligibility runner invariant **FAIL**；本節只新增文件／診斷證據，未重跑完整 pytest。R08 最近一次相關 focused tests 為 15 passed；R07 完整測試結果保留在歷史紀錄，並非 R09 新跑結果。
- 下一步由 Control Tower 決定明確的 API／持久化契約：對非正式 candidate 是在新 candidate artifact 中保存 `formal_result_eligible=false`，或由 API 僅在已驗證 `EXPLORATORY_CANDIDATE` 狀態下投影 false。應新增契約測試，但不得把缺欄位接受為 false 或改弱 runner。決定並實作後，才在全新暫存副本重跑完整 browser walkthrough。CP4-8 與 Week 4 仍 **BLOCKED／INCOMPLETE**。
