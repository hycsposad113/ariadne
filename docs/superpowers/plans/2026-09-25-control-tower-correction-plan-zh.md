# Control Tower 修正執行計畫（2026-09-25／v1）

**性質：** 修正工作包計畫，不是執行結果，也不批准任何來源、方法、約束或設計決定。
**來源：** Control Tower 於 2026-09-24T21:30Z 唯讀核查 R37 與權威 SQLite 後提出的五項差異，加上使用者 2026-09-25 新增的兩項要求：Git，以及測量與比例尺工具。
**撰寫：** Claude（Control Tower）。執行者不得自行驗收；每個工作包的結果交給 Control Tower 審查。
**v2 修訂（同日）：** 依 [計畫層級決定紀錄](../../decisions/2026-09-25-plan-decisions-zh.md) PD-01–PD-09 更新 C2、C5、C7、C8 與第 3–5 節。W5 的排程與任務契約以 [Week 5 執行計畫](2026-09-25-week5-execution-plan-zh.md) 為準。

## 0. 共同規則（Git 導入後生效）

專案自 2026-09-25 起是 Git repository。基線 commit 為 `811cb65`；AGENTS.md 治理更新為 `5b73a3b`。

- **分支：** 每個工作包開一條分支，命名 `wp/<id>-<short-name>`，例如 `wp/c3-analysis-persistence`。平行工作用 `git worktree`，不得兩個執行者同時改同一條分支。
- **Commit：** 一個 commit 只做一件事，commit message 寫明測試命令與結果。不得 force-push、rebase 已共享的分支，也不得改寫 `main` 的歷史。
- **合併：** 由 Control Tower 審查通過後才能合併到 `main`。合併前在分支上重跑全套 Python 與前端測試。
- **證據包：** 仍然 append-only。每個新證據包的 `package-record.json` 必須記錄 `git_commit`、`git_branch`、`git_dirty`（true/false）。`git_dirty=true` 時不得宣稱來源可重現。
- **不入 Git：** `.urban_design_runtime/`（權威 SQLite、WAL/SHM、QGIS profile、log）、`.venv`、快取、`node_modules`、`web/dist`，以及殘留的 `.../` 目錄。
- **歷史 verifier：** 16 個證據包把 AGENTS.md 記為 parent，現在會回報 parent drift。這是預期中的 lineage 差異，不是封存損壞；不得為此改舊包。
- **被記錄為 parent 的文件：** `docs/08_WORKFLOW_REALIGNMENT_2026-09-22.md`、`docs/superpowers/plans/2026-09-22-week4-platform-site-analysis-zh.md` 等被多個證據包記錄為 parent。修改任何現行文件前，先 grep `artifacts/*/parent-references.json` 與 `integrity-manifest.json`；若被記錄，改在未被記錄的藍圖修訂段或決定紀錄中寫入，不直接改原檔。
- **證據包粒度：** 只有涉及 gate 判定、權威狀態寫入或外部 runtime 的變更才需要完整證據包。純程式修正以「commit＋測試輸出」即可，避免每次修改都產生 R 包。

## 1. 工作包總表

| ID | 問題 | 類型 | 依賴 | 可否與 R39 平行 |
|---|---|---|---|---|
| C1 | QGIS GUI 交接需針對現行後端重驗 | A＋D（需要人類在畫面上操作） | 無 | 可以（用獨立的 DB 副本與埠） |
| C2 | ledger actor 一律為預設的 `designer`，無法分辨人類、代理與測試 | A（程式）＋D（寫入權威 ledger 需授權） | 無 | 可以；會碰到 `workspace_service.py`，需與 R39 協調 |
| C3 | 基地分析與 Syntax 結果沒有進入權威狀態 | A | 需 C2 的 actor 欄位 | 可以；不碰前端 |
| C4 | E2 所需的 Radiance runtime 已遺失 | C（下載需授權） | 無 | 可以；與程式碼無衝突 |
| C5 | 文件落差：Vision 寫 v4、README 權威清單漏列 08 | A | 無 | 可以 |
| C6 | 根目錄殘留 `.../urban_design_runtime/state.sqlite3`，來源不明 | A（唯讀調查） | 無 | 可以 |
| C7 | 介面缺少測量工具與即時比例尺 | A | R39 合併後再動 `Viewport2D.tsx` | 分支可先做工具函式，UI 接線等 R39 |
| C8 | E5 風場工具鏈可行性（OpenFOAM） | C（下載需授權） | C4 的 runtime 管理方式 | 可以；屬附加項，不佔核心資源 |

A 表示現有資料即可完成，B 表示可先用 fixture 開發，C 表示需要新的來源、runtime 或模型授權，D 表示需要設計者本人操作或決定。

## 2. 工作包

### C1 — QGIS→平台同步重驗

```yaml
objective: 以現行後端重跑一次 QGIS plugin「Sync to Platform」，取得可獨立審查的 GUI 交接證據，並重新分類 R13 的地位。
scope: 專用 QGIS profile 啟動、plugin 讀取 site-context、選取 1–100 個來源要素、按一次同步、平台顯示新 DRAFT revision、重新整理後仍在。
relevant_files:
  - Open Urban Design QGIS.command
  - qgis_plugin/urban_design_study_area/plugin.py, helpers.py
  - src/urban_design/api.py, workspace_service.py, workspace_contracts.py, workspace_sources.py
  - artifacts/week4-execution-r13-20260924T004209Z/（只讀，作為前次證據）
allowed_changes:
  - 新證據包 artifacts/week4-c1-qgis-reverify-<UTC>/
  - 若發現缺陷，另開 wp/c1-fix-* 分支修正並附測試
forbidden_changes:
  - 預設不得寫入權威 SQLite；平台 API 以權威 DB 的一次性副本啟動
  - 不得改 R13 或任何舊包
  - 不得使用 QGIS MCP 任意執行、SQL 或 batch 繞道
  - 不得停用、重啟或搶佔 Hermes 8787；啟動前確認 8788、8789、9876 無人占用
acceptance_criteria:
  - 同步按鈕由設計者本人在可見的 QGIS 視窗中按下，並有螢幕錄影或截圖序列（標示時間與視窗標題）
  - plugin 端收到 site-context 200 與 sync 201；平台副本 DB 新增一筆 revision；重新整理後 revision、要素 ID 與來源快照 ID 一致
  - 記錄現行 git commit，證明後端版本就是 R13 之後修改過的版本
  - 連線中斷時標記 OUTCOME_UNKNOWN，先核對副本 DB 再決定是否重試
  - gate 記錄把 R13 改標為「HISTORICAL_EXECUTOR_SELF_CHECK_PRE_BACKEND_CHANGE」，並以新包取代其驗收地位
tests: 全套 pytest（含 test_qgis_bridge、test_workspace_api、test_m2a02_plugin_launcher）；新包的 verify_package.py 與一次性故障注入
expected_return: 證據包路徑、git commit、同步前後副本 DB 的 revision 與 hash、錄影或截圖清單、未解決問題
```

**人類部分：** 設計者本人按同步鈕。代理可以準備環境、讀 log、核對結果，但不能代替這一下點擊，否則這一步不算人類交接驗收。
**授權點：** 若設計者希望這次同步寫入權威 DB（產生 revision 5），需在執行前明確說「寫入權威狀態」。

### C2 — 行為者（actor）來源標記

```yaml
objective: 讓每筆 ledger 事件能分辨真人介面操作、QGIS plugin、代理自動化與測試 harness；讓 HumanDecision 無法由自動化流程產生。
scope: workspace sync/update 事件、未來的 HumanDecision、API 請求的 actor 欄位來源。
relevant_files:
  - src/urban_design/workspace_service.py（actor 預設 "designer"，第 85、270 行）
  - src/urban_design/api.py, models.py, store.py
  - web/src/（送出請求的地方）, e2e/workspace_flow.py, qgis_plugin/.../plugin.py
allowed_changes:
  - 新增 typed 欄位 actor_kind（HUMAN_UI、QGIS_PLUGIN、AGENT_AUTOMATION、TEST_HARNESS）與 actor_session_id
  - 移除 "designer" 預設值；請求缺 actor_kind 時回 422
  - e2e 與代理驅動的瀏覽器一律送 AGENT_AUTOMATION 或 TEST_HARNESS
  - HumanDecision 端點要求設計者持有的決策密語：設計者在自己的終端機執行 `python -m urban_design.decision_key init`，以 getpass 輸入，只儲存 scrypt 雜湊（`~/.config/urban-design/decision-key`，權限 0600）；決策時由設計者在平台介面輸入。代理不得詢問、讀取、產生或保存密語，也不得在決策時段擷取畫面
  - 在副本 DB 上驗證「追加式來源註記」：為事件 182–185 各追加一筆 ProvenanceAnnotation，說明其 actor 是預設標籤、未經驗證；revision 1–2 的分區作者欄位是測試殘留
forbidden_changes:
  - 不得修改或刪除既有 ledger 事件或 state_versions
  - 未經設計者授權，不得把 ProvenanceAnnotation 寫入權威 DB
  - 不得讓密語或其雜湊出現在 artifact、log、截圖、測試 fixture 或前端 bundle；測試使用臨時目錄中由測試產生的假密語
acceptance_criteria:
  - 缺 actor_kind 的請求被拒；e2e 產生的事件都標為 AGENT_AUTOMATION 或 TEST_HARNESS
  - 沒有正確密語無法建立 HumanDecision；錯誤密語被拒，連續失敗有節流；雜湊檔不存在時決策端點回報 BLOCKED 而非放行
  - HumanDecision 紀錄 actor_kind=HUMAN_UI、決策內容、目標 ID／版本／hash、理由；密語本身與雜湊都不進 ledger、artifact、log
  - 副本 DB 上的註記只追加不改寫；舊事件 bytes 不變
tests: 新增 tests/test_actor_provenance.py；更新 test_workspace_api.py、e2e 流程；全套 pytest＋前端 test/build
expected_return: 分支、commit、測試輸出、副本 DB 註記前後比對、待授權的權威 DB 寫入內容（逐筆列出）
```

### C3 — 分析結果持久化

```yaml
objective: 把基地分析 Evidence Cards 與 Syntax 結果存成 ToolRun + Artifact + EvidenceRecord，由 SQLite 解引用後提供給 API，取代目前每次請求即時計算或讀取舊包。
scope: site_analysis.py 的五類觀測卡、R02 的 800 m 探索結果（以 IMPORTED_HISTORICAL_EXPLORATORY 狀態登錄）、日後的 Syntax job。
relevant_files:
  - src/urban_design/site_analysis.py, r03_evidence.py, r04_evidence.py, r03_syntax.py, space_syntax.py
  - src/urban_design/models.py, store.py, api.py
  - artifacts/week4-repair-r02/（只讀）
allowed_changes:
  - 新增 typed ToolRun／EvidenceRecord（若 models.py 已有，沿用並補欄位），記錄工具版本、git commit、輸入快照 hash、參數、輸出 hash、驗證狀態、限制
  - 新增「執行分析」命令：以 idempotency key 派送，結果原子寫入；輸入 hash 改變時舊結果標 STALE，不刪除
  - API 改為讀取持久化結果並重驗 hash；無結果時回報 NOT_COMPUTED，不即時補算
forbidden_changes:
  - 不得改寫 R02 或任何舊包
  - 不得把 800 m 探索結果升級為正式結果，也不得產生 2 km、10 km 數值
  - 未經授權不得寫入權威 DB；開發與驗收在副本上進行
acceptance_criteria:
  - 重啟 API 後卡片與 Syntax 圖層內容與寫入時一致，且都能追到 ToolRun 與輸入快照
  - 改一個輸入快照 hash（副本上的故障注入）後，相依結果顯示 STALE
  - 重複派送同一 idempotency key 不產生第二筆結果
  - 缺值顯示 unavailable，不變成 0
tests: 新增 tests/test_analysis_persistence.py；既有 test_site_analysis、test_week4_r04_evidence、test_red_team_week4 全過；瀏覽器流程重跑一次
expected_return: 分支、commit、測試、副本 DB 寫入清單、待授權的權威寫入內容
```

### C4 — Radiance runtime 重新佈建（E1／E2 前置）

```yaml
objective: 把 Radiance 放到持久、版本固定的位置，重跑 Milestone 1 的 Ladybug 與 Honeybee-Radiance smoke，並確認 E1 無 Rhino 的 headless 路徑。
scope: runtime 佈建、smoke 重跑、E1 路徑可行性；不做任何 Rotterdam 氣候實驗。
relevant_files:
  - docs/milestone1-feasibility.md（原本使用 /private/tmp/radiance-arm64）
  - scripts/ 內的 feasibility probe、tests/test_tool_feasibility.py
allowed_changes:
  - 在 ~/.local/share/urban-design-runtimes/radiance-<version>/ 或設計者指定的位置安裝，不放 /tmp
  - 新增 runtime manifest（版本、來源 URL、SHA-256、授權、架構）
forbidden_changes:
  - 未經授權不得下載；下載前列出檔名、來源、大小、授權
  - 不得選用天氣來源、轉換 Minute 或放寬 EPW validator
  - 不得把 Radiance 放進專案 .venv
acceptance_criteria:
  - rtrace、oconv、rfluxmtx、gendaymtx 可執行，版本與 manifest 一致
  - Milestone 1 的兩層 smoke 在新位置重跑通過
  - 提出 E1 headless 方法（例如 ladybug-radiance 的日照或太陽可見性計算），用無遮擋平面與已知遮擋物 fixture 證明結果正確；若該方法依賴 Radiance，寫明
tests: test_tool_feasibility.py；新增 E1 fixture 測試
expected_return: runtime manifest、smoke 輸出、E1 方法比較與建議
```

**授權點：** 下載 Radiance（來源、大小、授權先列給設計者）。

### C5 — 文件落差修正

```yaml
objective: 修正兩處與現況不符的現行文件敘述。
scope: docs/00_PRODUCT_VISION.md 的 Target User 段落（v4 → v5，並加註 v4 已被取代）；README「Authoritative Documents」補列 08 修訂契約。
allowed_changes: 只改上述兩處；以附註說明修正日期與依據。修改前先確認該檔未被證據包記錄為 parent；若已被記錄，改寫進藍圖修訂段
forbidden_changes: 不改歷史 artifact、研究報告或其他段落
acceptance_criteria: tests/test_m2a02_r01_documentation.py 通過；文件本地連結有效
tests: 文件一致性測試
expected_return: 一個 commit
```

### C6 — 殘留 SQLite 調查

```yaml
objective: 查明專案根目錄 .../urban_design_runtime/ 內 SQLite 的來源與內容，確認它沒有被任何程式當成權威狀態。
scope: 唯讀開啟、quick_check、heads 與 ledger 數量、最後事件時間，與權威 DB 比較；grep 程式與腳本中可能產生此路徑的程式碼。
forbidden_changes: 不刪除、不移動、不寫入該檔
acceptance_criteria: 一份短報告，說明產生原因（或無法判定）、是否含權威 DB 沒有的事件；若有，列出差異等設計者決定
expected_return: 報告與建議
```

### C7 — 測量工具與即時比例尺（新增需求）

使用者 2026-09-25 要求新增。目前只有匯出的地圖 PNG 有比例尺（`web/src/utils/mapFigure.ts`），互動的 2D 與 3D 視窗沒有比例尺、北向標示或測量工具。已記錄為需求 **R26-15**（決定紀錄 PD-09），W5 基礎、W8 完整。

```yaml
objective: 在平台 2D 視窗提供即時比例尺、北向箭頭，以及距離、折線長度、面積測量；在 3D 視窗提供高度與兩點距離測量。
scope:
  - 2D：縮放時更新的比例尺（公尺，取 1/2/5 的整數級距）、北向箭頭（EPSG:28992 格網北，另註明與真北的差異）、滑鼠座標讀數（EPSG:28992，公尺）
  - 測量：兩點距離、折線長度、多邊形面積（m²）與周長；可吸附到建築角點、道路頂點與道路中心線
  - 3D：兩點斜距、水平距離、高差；透視視角不顯示單一平面比例尺（08 契約第 3 節）
  - 匯出：測量線可選擇是否出現在匯出圖，出現時標示為「使用者測量」
relevant_files:
  - web/src/components/Viewport2D.tsx, Viewport3D.tsx
  - web/src/utils/geoTransform.ts, mapFigure.ts, roadPicking.ts
allowed_changes:
  - 新增 web/src/utils/measure.ts（純函式）與測試；新增量測工具列元件
  - 測量以來源 EPSG:28992 公尺座標計算，不用螢幕像素
forbidden_changes:
  - 測量值不是 EvidenceResult，不寫入 ledger，不供 AI 當作計算證據引用
  - 不得改 web/index.html、web/src/index.css（Grok Build 的 icon 工作）
  - R39 合併前不得修改 Viewport2D.tsx；可先在分支完成 measure.ts 與測試
acceptance_criteria:
  - 已知長度的 fixture（例如 100 m 線段）在不同縮放下都量出 100.00 m ± 0.01 m
  - 已知面積多邊形（例如 20 m × 50 m）量出 1,000.00 m²；自交多邊形拒絕計算
  - 比例尺長度與 geoTransform 的 metersPerPixel 一致；縮放後更新
  - 北向箭頭方向在旋轉視角後仍正確（若視角可旋轉）
  - 瀏覽器 E2E：量一段已知道路長度，與後端 Shapely 計算的長度比對
tests: web/src/utils/measure.test.ts；瀏覽器 E2E 新增測量步驟；前端 build 與 lint
expected_return: 分支、commit、測試、E2E 截圖
```

### C8 — E5 風場工具鏈可行性（附加項）

```yaml
objective: 在不影響核心的前提下，確認 OpenFOAM 能否在本機受控執行，並用公開 benchmark 驗證一個最小案例。
timing: 依 PD-07，W7 核心整合通過之後才開始；EnergyPlus／OpenStudio（E3、E4）同一時點。
scope: 工具鏈選擇、安裝、benchmark；不做 Rotterdam 正式風場研究。
relevant_files: 新增 docs/technical/e5-wind-feasibility.md、scripts/probe_openfoam.py
allowed_changes: 在 Docker 容器或指定路徑中執行固定版本的 OpenFOAM
forbidden_changes:
  - 未經授權不得下載映像或安裝包；下載前列出來源、版本、大小、授權（OpenFOAM 為 GPL）
  - 不得以風玫瑰或單一風向結果宣稱行人風舒適
  - 不得佔用核心 W5–W8 的執行者時間
acceptance_criteria:
  - blockMesh、snappyHexMesh、simpleFoam 在容器中可執行，版本固定
  - 一個有公開量測資料的 benchmark（例如 AIJ 單棟建築案例或 CEDVAL）跑完，收斂與誤差記錄在案
  - 列出正式研究所需的其他輸入：入流風剖面、地表粗糙度、風向頻率（需天氣來源，受天氣 gate 約束）、評估標準（荷蘭 NEN 8100）
expected_return: 可行性報告、runtime manifest、benchmark 結果或具體阻塞
```

## 3. 可以與 Week 4 平行的 Week 5 工作

原則：只用明確標示的合成 fixture；不使用未批准的 FAR、用途、層高或設計範圍；結果不得作為正式方案或送正式分析。每條線各開分支，只新增檔案或只動列出的檔案，避免碰到 R39 正在修改的前端與 brief 相關檔案。

| 平行線 | 內容 | 新增或修改的檔案 | 現在能做到哪裡 | 不能正式採用的部分 |
|---|---|---|---|---|
| P5-1 計量核心 | 逐層 footprint 的 GFA、FAR、coverage（union）、分區分配、保留建築計入；缺樓層回報 unknown | 新增 `src/urban_design/morphology/metrics.py`、`tests/test_morphology_metrics.py` | 用 blueprint 的 1,000 m² fixture 完成並測試 | 真實基地的分母與上限尚未批准 |
| P5-2 量體編輯核心 | 逐層體塊、一次一層拉高、側面 1 m 相對步進、移動、旋轉、自交／非流形拒絕、undo 紀錄 | 新增 `src/urban_design/editing/{commands,floors,validation}.py`、`tests/test_editing.py`；可沿用 R34 probe | 合成量體上完成後端命令與驗證 | 首層、標準層高尚未批准，只能用 fixture 參數 |
| P5-3 道路圖編輯核心 | 節點拖曳、端點與最近點吸附、接到路段中間時切分、保留道路鎖定、橋隧不誤連、改道後 graph hash 更新 | 新增 `src/urban_design/editing/roads.py`、`tests/test_road_editing.py` | 合成平交與跨橋 fixture | 道路寬度與階層數值未定 |
| P5-4 策略生成骨架 | 固定 seed 的三種策略：先道路與開放空間骨架，再街廓，再量體；保存失敗候選；三策略的差異可說明 | 新增 `src/urban_design/morphology/{contracts,strategies,streets,parcels,massing,validation}.py`、`tests/test_morphology.py` | 合成矩形基地與虛構 brief | 真實生成要等 brief、分母、上限、保留決定 |
| P5-5 前端編輯器原型 | three.js 的面選取、拉高把手、儀表板（標示為預覽） | 新增 `web/src/features/editor/`；R39 合併前不改 App.tsx、Viewport2D.tsx | 獨立頁面或 storybook 式測試頁 | 接到主工作區要等 R39 合併 |
| P5-6 決策文件 | 把 D 類決策整理成選項表（見第 4 節），附圖與影響說明 | 新增 `docs/decisions/2026-09-25-w5-decision-docket-zh.md` | 立即可做 | 由設計者決定，代理不得代填 |

W4 關鍵路徑上也可以平行推進的項目：C3（分析持久化）、C4（Radiance）、Syntax 引擎的獨立數值比較。最後一項可以在新檔案中呼叫外部參考引擎，不修改 `space_syntax.py`；但外部引擎的下載需要授權。

## 4. 決策狀態（v2）

已由設計者決定（見決定紀錄）：Live AI（PD-10、PD-12）、樓層估算（PD-11）、Syntax 引擎（PD-01）、區域路網與計算預算（PD-02）、決策時段（PD-03）、分析寫入權限（PD-04）、停損（PD-05）、證據分級（PD-06）、E3–E5 時點（PD-07）、天氣方法路線（PD-08）、R26-15（PD-09）。

仍待決定：
1. 設計範圍、保留要素、分區：W5 第 1 天在平台上決定。
2. FAR、高度、首層與標準層高、道路寬度與階層：W5 第 3 天在聊天室決定。保留建築樓層改以 3D BAG 估算（PD-11）。
3. Live AI 採通用模型層（PD-10、PD-12）：API 路線（OpenAI GPT-4o 優先，另可接 Claude、xAI、OpenRouter、ModelScope、Ollama）＋Hermes 專用 profile 路線；待設計者設定至少一個 profile 的 key。
4. 權威 DB 快照是否入 Git；C1 是否寫入權威 DB；C2 來源註記是否寫入權威 ledger。
5. 天氣推導方法的正式批准：W5 結束前。
6. 下載核准：Geofabrik 南荷蘭省 OSM 檔、3D BAG（PD-11）、Radiance（C4）。

## 5. 順序

W5 的逐日順序見 [Week 5 執行計畫](2026-09-25-week5-execution-plan-zh.md)。要點：C2 必須在 W5 第 1 天的決策時段前合併；C1 與第一次決策時段同一天進行（設計者都在電腦前）；C3 在第 2 天完成，供生成器與比較使用；C8 依 PD-07 排在 W7 之後。
