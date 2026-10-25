# Week 5 執行計畫：多方案生成＋基礎編輯（含 W4 延續項）

**版本：** 2026-09-25／v3（PD-12：通用模型層＋Hermes 路線）。**撰寫與審查：** Claude（Control Tower）。**執行：** Codex CLI `gpt-6-luna`（reasoning max）；內部 sub-agent 只能用同一模型（AGENTS.md）。
**預定日期：** W5 第 1–5 天＝2026-09-28（一）至 10-02（五）。這是假設學期週從週一開始；若不同，按相對日序執行。
**依據：** [計畫層級決定紀錄 PD-01–PD-12](../../decisions/2026-09-25-plan-decisions-zh.md)、[Control Tower 修正計畫 v2](2026-09-25-control-tower-correction-plan-zh.md)、[08 修訂契約](../../08_WORKFLOW_REALIGNMENT_2026-09-22.md)、[學期藍圖（含 2026-09-25 修訂）](2026-09-22-semester-project-blueprint-zh.md)、[Week 5 技術細節](../../technical/2026-09-22/week5-generation-editing.md)。衝突時以決定紀錄為準。

---

## 0. 本週結束時，設計者能做到的事

1. 在平台上畫設計範圍、選保留建築與道路、畫分區，並以自己的決策密語確認（HumanDecision）。
2. 看到 800 m、2 km（10 km 視進度）的 angular integration／choice 圖層，附方法說明與限制。
3. 在聊天室選定 FAR、高度、層高、道路寬度後，看到至少三個策略不同、有效、可重現的方案。每個方案都說得出道路、街廓、開放空間、機能、量體的差異；AI 依證據說明各方案的優缺點，介面標出實際使用的 provider 與模型（PD-10、PD-12）。
3a. 在平台上詢問 AI 基地的潛能與限制，回答引用可點開的 Evidence Card。
4. 用同一套分母與規則比較方案，親自選定 B（HumanDecision），A、C 的拒絕理由也保存下來。
5. 在 B 上移動、旋轉、一次拉高一層、側面每次推 1 m、拖曳道路節點並吸附到端點或最近點；儀表板即時顯示樓層、高度、GFA、FAR、建蔽率與剩餘額度，並清楚標示「預覽」或「已確認」。
6. 在 2D 畫面看到比例尺與北向，可量距離、長度、面積。
7. 關掉瀏覽器與 API 再重開，以上全部從權威狀態恢復。

**本週不做：** 分面與局部推拉的完整版、完整吸附（中點、交點、垂直點、四分點），這些是 W6 核心；E1／E2 分析；E3–E5（PD-07）；模型匯出；正式氣候實驗。

## 1. 起點（執行前必須自行重新核對）

以下是 2026-09-25 的狀態，**不保證**開始執行時仍相同。

- Git：`main` 上有 `811cb65`（基線）、`5b73a3b`（AGENTS.md）、`b9e27bf`（修正計畫），之後還有決定紀錄與本計畫的 commit。R39 的程式修改已含在基線 commit 內，但**尚未經 Control Tower 審查**；R39 證據包在基線之後才完成，可能仍是 untracked。
- 權威 SQLite：`.urban_design_runtime/state.sqlite3`，2026-09-24 的 SHA-256 為 `4db9a1a8…6ee6d3`，ledger 185 筆；Artifact heads 109、DatasetSnapshot heads 52；HumanDecision、ParameterDefinition heads 皆為 0；workspace revision 4 DRAFT；StudyArea v5 CONFIRMED_FOR_EXPLORATION。
- 已有 model（`src/urban_design/models.py`）：Constraint、ConstraintSet、UnavailableValue、ParameterDefinition、Scenario、ToolExecution、ModelRun、EvidenceResult、EvidenceCard、HumanDecision、ContestEvent。**沿用並擴充，不另建平行型別。**
- 已有前端：React＋three.js 自製 2D／3D 視窗（`web/src/components/Viewport2D.tsx`、`Viewport3D.tsx`），沒有地圖函式庫。
- Syntax：顯示的 800 m 值來自凍結的 R02 套件（`src/urban_design/r03_syntax.py`），2 km、10 km 未計算。
- PST 3.3.1 位於 `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/pst/pstalgo/`（universal `libpstalgo.dylib`，LGPL-3）。
- Hermes：8787 是網頁介面，不可接觸；Hermes Agent 0.21.4 的 OpenAI 相容 API 目前由 `life-agent` profile 開在 8644，**不得使用**（啟用了工具與記憶）。只有 PD-12 的專用 profile 可以用。

## 2. 共同規則

### 2.1 Git 與平行工作

- 每個工作包一條分支 `wp/w5-<nn>-<name>`，平行線用 `git worktree`。
- **共享核心檔的擁有權：** `models.py`、`store.py`、`api.py` 只由 A 線修改。其他線若需要新欄位或路由，先交給 A 線；新模組放在各自的新檔案。
- 合併到 `main` 前：在分支上跑全套 Python 與前端測試，並交給 Control Tower 審查。執行者不得自行合併自己的分支。
- 不得 force-push、不得改寫 `main` 歷史、不得 commit `.urban_design_runtime/`。

### 2.2 證據分級（PD-06）

| 等級 | 適用 | 內容 |
|---|---|---|
| 0 | 一般程式修改 | commit＋測試命令與輸出（寫在 commit message 或 `evidence/` 下的小檔） |
| 1 | UI 功能 | 等級 0＋瀏覽器截圖與簡短紀錄，隨 commit 保存 |
| 2 | gate 判定、寫入權威 DB、外部 runtime、下載、天氣 | 完整 R 包：`artifacts/week5-<id>-<UTC>/`，含 integrity manifest、verifier、故障注入、`git_commit`、`git_dirty` |

### 2.3 停損（PD-05）

同一個 gate 連續 2 個 revision 或 1 個工作天沒有**功能進展**（只有加固、補證據、改文件都不算），立刻停下，回報：卡在哪裡、已試過什麼、2–3 個具體選項與建議。只停受影響的工作線，其他線繼續。

### 2.4 權威 DB 寫入（PD-04）

- **可以追加：** ToolExecution、Artifact、EvidenceResult／EvidenceCard、生成器產出的 PROPOSED Scenario 與其幾何 Artifact、編輯產生的 DRAFT Scenario revision。
- **每次寫入前：** 用 `sqlite3` 的 `.backup` 做快照（存到 `~/.local/share/urban-design-backups/`，不入 Git），記錄快照與寫入前後的 SHA-256。
- **actor：** 一律 `AGENT_AUTOMATION`（C2 完成後由程式強制）。
- **禁止：** 建立 HumanDecision、啟用 Constraint、批准設計範圍或 StudyArea、接受方案、發布天氣 DatasetSnapshot（天氣要等設計者批准後才可發布，見 W5-12）。
- 開發與測試一律使用 DB 副本；只有「產生正式結果」的步驟才寫權威 DB。

### 2.5 需要事先核准的外部動作

以下每項都要先在回報中列出來源、檔名、大小、授權、用途，等設計者明確同意：

1. Geofabrik 南荷蘭省 OSM 抽取檔（W5-4）；若 20 km 外擴超出省界，另列相鄰抽取檔。
2. 新 Python 依賴（例如 `osmium`／pyosmium）：列出版本與授權，加入 `pyproject.toml`。
3. Radiance（W5-14，選做）。
4. 3D BAG 高度資料（W5-15，PD-11）：列出端點、範圍、筆數或大小、版本。
5. Live AI（PD-12）：只有在設計者設定好至少一個 profile 的 key（或 Hermes 專用 profile）並設定 `PROJECT_AI_AUTHORIZED=1` 之後才可呼叫；全部路線合計全週上限 200 次。
6. Hermes 專用 profile：若由執行者建立，需設計者明確授權；不得動 8787 或既有 Hermes 行程。

複製本機已安裝的 PST 檔案不算下載，但要記錄來源路徑與 hash。

### 2.6 絕對禁止

- 捏造 GIS、幾何、規劃、Syntax 或模擬數值；把未知當 0；把探索結果標成正式結果。
- 代替設計者按確認、輸入或讀取決策密語、在決策時段擷取畫面、以 designer 身分寫入任何紀錄。
- 未經批准就把 FAR、高度、層高、道路寬度當成有效設定。fixture 值必須標成 `FIXTURE_ONLY`。
- QGIS MCP 任意執行、SQL、batch 繞道；接觸 Hermes 8787 或 `life-agent` 的 8644；關閉或重啟非本任務啟動的服務。
- 修改舊證據包；修改被證據包記錄為 parent 的文件（修改現行文件前先 grep `artifacts/*/parent-references.json` 與 `integrity-manifest.json`）。
- 修改 `web/index.html`、`web/src/index.css`（Grok Build 的 icon 工作）。
- 儲存或要求私有 chain-of-thought。

## 3. W4 延續項（本週必須收掉或明確阻塞）

| ID | 內容 | 本週工作包 |
|---|---|---|
| K1 | R39 審查與收尾 | W5-0 |
| K2 | C2 actor 與人類決策機制 | W5-1 |
| K3 | C1 QGIS GUI 重驗（設計者操作） | W5-2 |
| K4 | C3 分析結果持久化 | W5-3 |
| K5 | 六張 Syntax 圖層（PST） | W5-4 |
| K6 | C5 文件修正、C6 殘留 SQLite 調查 | W5-13 |
| K7 | R26-15 測量與比例尺（C7） | W5-11 |
| K8 | Live AI（通用模型層，PD-12） | W5-AI |

## 4. 工作線與逐日排程

| 線 | 負責工作包 | 可以動的共享檔 |
|---|---|---|
| A 權威與決策 | W5-0、W5-1、W5-3、W5-6、W5-8 | `models.py`、`store.py`、`api.py` |
| B Syntax | W5-4 | 無（新模組＋經 A 線加路由） |
| C 幾何 | W5-5、W5-15、W5-7、W5-9 後端、W5-10 後端 | 無（新模組） |
| D 前端 | W5-2 UI、W5-11、方案面板、W5-9 與 W5-10 前端、儀表板 | `web/src/**`（除 icon 檔） |
| E 天氣與 AI | W5-12、W5-AI | `model_provider.py`、`site_critic.py`（其餘經 A 線） |

| 日 | 上午 | 下午 | 人類時段與 checkpoint |
|---|---|---|---|
| D1 | W5-0；W5-1 完成並合併；W5-5 開始；W5-4 PST runtime 與 adapter | W5-2 設計範圍 UI；W5-3 開始；W5-12 開始 | **決策時段 1**（設計者在平台上）＋ **C1 QGIS 重驗**；CP5-0、CP5-1 |
| D2 | W5-4 比對完成（**PD-01 期限**）；W5-3 完成；W5-AI adapter | 下載核准後 W5-4 做 2 km、W5-15 取 3D BAG；W5-7 用 fixture 跑通；W5-11 | CP5-2（Syntax 方法）、CP5-3（持久化）、CP5-AI |
| D3 | W5-6 決策文件定稿，送給設計者 | **決策時段 2** 後：W5-7 用真實約束生成；W5-9 後端 | CP5-4（約束） |
| D4 | W5-7 三方案完成；W5-8 比較表；W5-4 10 km（若 2 km 效能允許） | **決策時段 3**：設計者選 B；W5-9 前端與儀表板；W5-10 | CP5-5（生成）、CP5-6（選擇） |
| D5 | W5-9、W5-10 收尾；W5-12 送設計者批准 | 全套測試、瀏覽器 walkthrough、獨立審查、W6 交接 | CP5-7（編輯）、CP-W5 |

排程是目標，不是保證。任何工作線觸發停損就停下上報，不為趕進度跳過 gate。

## 5. 工作包

### W5-0 起點核對與 R39 收尾（A 線，D1 上午，等級 0）

```yaml
objective: 確認起點狀態，把 R39 的剩餘檔案納入版本控制並送審。
scope: git 狀態、權威 DB 唯讀核對、埠核對、R39 verifier。
relevant_files: artifacts/week4-execution-r39-*/, git log, .urban_design_runtime/state.sqlite3（唯讀）
allowed_changes: 在分支 wp/w5-00-r39-import commit R39 的 untracked 證據檔（不改其內容）
forbidden_changes: 不修改 R39 檔案內容；不寫權威 DB
acceptance_criteria:
  - 記錄權威 DB 的 SHA-256、quick_check、各類 heads 數、ledger 數，與本計畫第 1 節比較並列出差異
  - R39 verifier 結果照實記錄（包括因 AGENTS.md 修改造成的 parent drift）
  - 8787 僅以 lsof 觀察；8788、8789、9876 與本週要用的埠確認空閒
tests: 全套 pytest 一次作為基線
expected_return: 起點報告（寫在 commit message 或 evidence/w5-00.md）
```

### W5-1 行為者標記與人類決策機制（A 線，D1 上午完成，等級 2）

實作修正計畫 C2（v2），重點如下：

```yaml
objective: 讓 ledger 能分辨真人、plugin、代理與測試；讓 HumanDecision 只能由持有決策密語的設計者建立。
scope: actor_kind／actor_session_id 欄位；決策密語的初始化、驗證與節流；HumanDecision API；前端確認對話框。
relevant_files: src/urban_design/workspace_service.py, api.py, models.py, store.py, web/src/**, qgis_plugin/urban_design_study_area/plugin.py
allowed_changes:
  - 新增 src/urban_design/decision_key.py：`python -m urban_design.decision_key init` 以 getpass 讀入密語，存 scrypt 雜湊到 ~/.config/urban-design/decision-key（0600）
  - 新增 POST /api/v1/projects/{id}/decisions：需要密語、目標 ID／版本／hash、決策動作、理由；成功後寫 HumanDecision＋ledger（actor_kind=HUMAN_UI）
  - 移除 actor 預設值 "designer"；缺 actor_kind 回 422；e2e 與代理驅動一律 AGENT_AUTOMATION 或 TEST_HARNESS
forbidden_changes:
  - 不得在程式、測試、log、artifact、前端 bundle 中出現真實密語或其雜湊；測試用臨時目錄與假密語
  - 不得替設計者執行 init；只提供指令與說明
  - 不修改既有 ledger 事件
acceptance_criteria:
  - 雜湊檔不存在時，決策端點回 BLOCKED（不放行）
  - 錯誤密語被拒，連續失敗會節流；正確密語才建立 HumanDecision
  - HumanDecision 綁定目標版本與 hash；目標版本過期（stale）時被拒
  - e2e 產生的所有事件 actor_kind 都不是 HUMAN_UI
tests: 新增 tests/test_actor_provenance.py、tests/test_decision_key.py；更新 test_workspace_api.py；全套 pytest＋前端 test／build／lint
expected_return: 分支、commit、測試輸出、給設計者的 init 指令（一行）、第 2 級證據包
```

**D1 開始前要設計者做的事：** 在自己的終端機執行 init 指令並設定密語。執行者只提供指令。

### W5-2 設計範圍 UI 與決策時段 1（D＋A 線，D1，等級 2）

```yaml
objective: 讓設計者在平台上畫設計範圍（ExplorationDesignArea）、確認保留要素與分區，並以 HumanDecision 記錄；同時完成 C1 QGIS 重驗。
scope:
  - 新增設計範圍的繪製、編輯、刪除（沿用 R39 的分區繪製互動）；必須位於 StudyArea 內、有效、不自交；顯示面積（m²）
  - 保留／可改／未決三態選取（已有），補上「送出決策」流程
  - 分區：硬性條件與偏好分開顯示
  - 送出時彈出確認對話框：列出將被記錄的內容（範圍面積與 hash、保留建築與道路數量及 ID 清單、分區清單），由設計者輸入密語
relevant_files: web/src/components/Viewport2D.tsx, SidebarDispositions.tsx, SidebarBrief.tsx, src/urban_design/design_brief.py, workspace_contracts.py
allowed_changes: 上述檔案與新元件；typed ExplorationDesignArea（若 models.py 無對應，由 A 線新增）
forbidden_changes: 代理不得代替設計者按確認或輸入密語；代理不得擷取決策時段畫面
acceptance_criteria:
  - 設計者完成後，權威 DB 有三類 HumanDecision：設計範圍、要素處置、分區 brief；各自綁定目標 hash
  - 重開瀏覽器與 API 後，範圍、處置、分區與決策狀態一致
  - C1：設計者在可見的 QGIS 視窗按一次「Sync to Platform」，平台副本或權威 DB（依設計者當時決定）出現新 revision；有截圖序列、git commit、site-context 200／sync 201 紀錄
tests: 前端單元測試（範圍在 StudyArea 外、自交、面積計算）；瀏覽器 E2E（用 TEST_HARNESS 身分在副本 DB 跑完整流程，不建立 HumanDecision）
expected_return: UI 完成截圖、決策時段操作說明（給設計者）、時段後的權威 DB 讀取結果、C1 證據包
```

**決策時段 1（約 30–45 分鐘）：** 設計者畫範圍、選保留、畫分區、送出。執行者事先準備一頁操作說明，並提醒：未決要素不會被生成器刪除。

### W5-3 分析結果持久化（A 線，D1–D2，等級 2）

實作修正計畫 C3，並依 PD-04 寫入權威 DB。

```yaml
objective: 基地分析卡片與 Syntax 結果改由權威狀態提供。
scope: 以 ToolExecution＋Artifact＋EvidenceResult／EvidenceCard 保存；R02 的 800 m 以 IMPORTED_HISTORICAL_EXPLORATORY 狀態登錄；API 讀取持久化結果並重驗 hash；輸入 hash 改變時標 STALE。
relevant_files: src/urban_design/site_analysis.py, r03_evidence.py, r04_evidence.py, r03_syntax.py, models.py, store.py, api.py
forbidden_changes: 不改 R02；不在 API 請求中即時補算；缺結果回 NOT_COMPUTED
acceptance_criteria:
  - 寫入前有備份快照與 hash；寫入後重啟 API，卡片與圖層內容一致並可追溯到 ToolExecution 與輸入快照
  - 副本上的故障注入：改一個輸入快照 hash 後相依結果變 STALE；重複派送同一 idempotency key 不產生第二筆
  - 缺值顯示 unavailable，不是 0
tests: 新增 tests/test_analysis_persistence.py；既有 test_site_analysis、test_week4_r04_evidence、test_red_team_week4 全過；瀏覽器流程一次
expected_return: 分支、commit、權威 DB 寫入清單（前後 hash）、第 2 級證據包
```

### W5-4 六張 Syntax 圖層（B 線，D1–D4，等級 2）

**步驟 1：PST runtime（D1）**
- 把 `pst/pstalgo/`（`python/` 與 `bin/`）複製到 `~/.local/share/urban-design-runtimes/pstalgo-3.3.1/`。
- 在 repo 新增 `config/runtimes/pstalgo-3.3.1.json`：來源路徑、PST plugin metadata、每個檔案的 SHA-256、授權 LGPL-3.0-or-later、架構。
- 新增 `src/urban_design/syntax_engines/pst_adapter.py`：載入前核對 hash；以**子行程**執行（避免 ctypes 崩潰拖垮 API），JSON 輸入輸出，逾時上限 2 小時。
- 查明 PST 的 `CreateSegmentMap`／`CreateGraph` 如何處理平面交叉與 unlink。若無法表達橋與隧道的立體交叉，就自行切分路段並傳入 unlink 點，不得讓立體交叉被當成相連。

**步驟 2：方法比對（D1–D2，PD-01 期限 D2）**
- 小網路 fixture：直線、T 字、十字、不同轉角、孤立元件、立體交叉。
- 兩個引擎都輸出**原始量**：節點數（NC）、角度總深度（TD）、choice 次數；再用同一套公式正規化：NAIN = NC^1.2／(TD+2)，NACH = log(choice+1)／log(TD+3)。
- **比對標準（Control Tower 核定，method-comparison-v1）：** fixture 上 NC 完全相同，TD 與 choice 在定義一致時相對誤差 ≤ 1e-6；M4H 800 m 子網上，TD 與 choice 的 Spearman ≥ 0.99，且相對誤差的第 95 百分位 ≤ 1%。
- 半徑量測方式、角度成本等定義差異要用可區分的 fixture 查明並寫入 method manifest。未達標準就依 PD-05 停下上報，不得調整門檻湊通過。

**步驟 3：區域資料（D2 起，需下載核准）**
- 先回報 Geofabrik 南荷蘭省抽取檔的 URL、大小、檔案日期、ODbL，等設計者同意。
- 下載後記錄 SHA-256、檔頭的 replication timestamp，存成新的 DatasetSnapshot（屬分析輸入，依 PD-04 可寫入）。
- 路網政策 `syntax-network-policy-v1`：列出納入與排除的 `highway` 類別、access 處理方式、立體交叉規則（layer／bridge／tunnel）。在設計者於決策時段 2 確認前，所有結果標為 EXPLORATORY。
- 範圍：2 km 用 StudyArea 外擴 4 km；10 km 用外擴 20 km。若 20 km 超出省界，記錄邊緣受影響路段，並另列相鄰抽取檔待核准。

**步驟 4：計算與穩定性（D2–D4）**
- 2 km：用外擴 4 km 與 6 km 各算一次，比較 StudyArea 內路段的結果。
- 10 km：先用 2 km 的執行時間推估；推估超過 2 小時就停下上報，並附選項（簡化路網、限制起點、分區計算等）。可行時用外擴 15 km 與 20 km 各算一次。
- **穩定性標準（提案 stability-v1，可由設計者調整）：** StudyArea 內 Spearman ≥ 0.98；變化超過 5% 的路段標為 EDGE_AFFECTED。
- 結果依 W5-3 寫入權威 DB，平台顯示六張圖層，每張附方法、半徑、正規化方式、狀態、限制。UI 用「局部／中距／區域尺度」，不標成步行、自行車、汽車。

```yaml
forbidden_changes: 不以一般 closeness／betweenness 冒充 angular 指標；不修改 R02；不以 QGIS MCP 執行 PST
acceptance_criteria:
  - method manifest 完整（引擎、版本、hash、分段方式、角度成本、半徑、正規化、公式版本、孤立元件、邊界效應）
  - 比對結果達標或已依 PD-05 上報
  - 800 m 與 2 km 圖層由權威狀態提供；10 km 完成或有具體阻塞與選項
tests: 新增 tests/test_pst_adapter.py、tests/test_syntax_method_comparison.py、tests/test_regional_network.py；既有 test_space_syntax、test_context_network 全過
expected_return: runtime manifest、比對報告、下載核准請求、計算時間紀錄、穩定性報告、第 2 級證據包
```

### W5-5 計量核心（C 線，D1–D2，等級 0）

```yaml
objective: 以確定性方式計算 GFA、FAR、建蔽率與分區分配，作為生成、編輯、儀表板的共同基礎。
scope: 新增 src/urban_design/morphology/metrics.py
rules:
  - GFA = 所有計入樓板多邊形面積總和（逐層 footprint，不用外框 × 層數）
  - FAR = GFA ／ 有效設計面積（來自已批准的 ExplorationDesignArea）
  - 建蔽率 = 建築 footprint 聯集面積 ／ 有效設計面積
  - 分區 FAR：以樓板與分區的幾何交集分配；分區重疊沒有分配規則時拒絕計算
  - 高度 = 首層高 ＋ (N−1) × 標準層高
  - 保留建築：樓層未知時回傳 UnavailableValue，FAR 標示「部分未知」，不填 0
acceptance_criteria:
  - blueprint fixture：設計面積 1,000 m²，10 × 20 m、3 層 → GFA 600、FAR 0.6；首層 4 m、標準層 3 m → 高度 10 m；加一層 → GFA 800、FAR 0.8、高度 13 m；上限 0.7 時該草稿「可保存、不可接受」
  - 只改用途 GFA 不變；退台只改相關樓層
tests: 新增 tests/test_morphology_metrics.py（全部是 FIXTURE_ONLY 值）
expected_return: 分支、commit、測試輸出
```

### W5-6 約束集與決策時段 2 準備（A 線，D2–D3，等級 2）

```yaml
objective: 把強度與道路參數做成可預覽、待確認的 ConstraintSet，並準備決策時段 2 的選項文件。
scope:
  - ConstraintSet 欄位：整體 FAR 上限、各分區 FAR 上限（可選）、建蔽率上限、高度上限、首層高、標準層高、道路寬度（依階層）、旋轉步進；每項有單位、作用範圍、來源（HumanDecision ID）、硬性或偏好
  - 決策文件 docs/decisions/2026-09-30-session2-docket-zh.md（日期依實際 D3 調整）：每項列 2–4 個選項與影響說明
relevant_files: models.py（Constraint、ConstraintSet、ParameterDefinition）、design_brief.py、api.py
rules:
  - 選項的數值影響，用 W5-5 與 W5-7 在已批准的設計範圍上算出，標為 ILLUSTRATIVE，不是方案
  - 不得寫「法規值」「常見值」；3.5 m 只是訪談舉例
  - 保留建築樓層依 PD-11 由 W5-15 估算；決策文件列出估算結果摘要（含大空間建築的範圍值），並請設計者確認估算層高
  - 必須包含「syntax-network-policy-v1 是否採用」與 stability-v1 門檻
acceptance_criteria:
  - 未經 HumanDecision 的約束無法啟用；重疊分區沒有分配規則時拒絕
  - 決策時段 2 後，權威 DB 有對應的 HumanDecision 與啟用的 ConstraintSet；重開後一致
tests: 擴充 tests/test_design_brief.py，新增 tests/test_constraint_set.py
expected_return: 決策文件（先交 Control Tower 審閱再給設計者）、時段後的權威狀態讀取結果
```

**決策時段 2（D3，聊天室）：** Control Tower 把決策文件整理成選項題，設計者選擇後，由設計者在平台以密語確認寫入。

### W5-7 策略生成（C 線，D2 fixture、D3–D4 真實，等級 2）

```yaml
objective: 在已批准的範圍、保留要素、分區與約束下，產生至少三個有效、策略不同、可重現的方案。
scope: 新增 src/urban_design/morphology/{contracts,strategies,streets,parcels,massing,validation}.py
steps:
  1. 鎖定保留建築與道路、設計範圍、可連接的外部道路節點（從來源路網與設計範圍邊界交點取得，保留 layer）
  2. 策略骨架：主次道路與開放空間。策略範本放在 strategy-catalog-v1（例如向心開放空間、格網、線性綠軸），標示為「系統提出的範本，非已批准類型」，且不得違反設計者的分區訴求
  3. 依批准的道路寬度產生道路面；街廓 = 設計範圍 − 道路 − 保留 footprint − 開放空間；過小或過窄的碎片標記並排除（門檻為版本化設定，FIXTURE 值需標示）
  4. 量體：逐層體塊；FAR 是上限不是目標，每個策略的使用率是明示的策略參數
  5. 用途依分區偏好配置，至少追溯到 building／floor
  6. 驗證：幾何有效、在範圍內、不壓保留物、道路與外部節點連通（graph 檢查）、FAR／建蔽率／高度／分區上限；失敗候選保存原因
  7. 差異報告：道路圖差異、開放空間位置與比例、街廓尺寸分布、量體配置；只報告數值，不自訂合格門檻
rules:
  - 固定 seed；幾何 canonicalization（座標四捨五入到 1e-6 m、環方向一致）後計算 hash；同輸入重跑 hash 相同
  - 每個方案存成 Scenario（PROPOSED）＋幾何 Artifact（EPSG:28992 GeoJSON）＋ToolExecution
  - 只有兩個有效方案時，照實報告 2／3 未達標，不得複製量體或換色湊數
  - 策略文字說明：有可用 profile 時由 W5-AI 依方案 evidence bundle 產生，標示「AI 解釋」與 provider／模型，並通過引用驗證；沒有可用 profile 時用確定性模板並標示「非 AI 生成」。AI 只能說明，不得產生或修改幾何與數值
acceptance_criteria:
  - D2：合成矩形基地上跑出三策略，全部測試通過
  - D4：真實設計範圍上至少三個有效方案；重跑 hash 一致；平台可切換檢視 2D／3D
tests: 新增 tests/test_morphology.py（fixture 策略、保留物不動、道路連通、跨橋不誤連、上限不超、重現性、失敗候選保存）
expected_return: 方案清單與 hash、差異報告、失敗候選、第 2 級證據包
```

### W5-8 方案比較與決策時段 3（A＋D 線，D4，等級 2）

```yaml
objective: 以同一分母與規則比較方案，由設計者選定 B。
scope: 比較表（FAR、建蔽率、高度、用途比例、道路與開放空間比例、可用的 Syntax 結果），並列單位、方法、資料缺口、驗證狀態；不做總分或排名。AI 依比較表產生優缺點說明，每句連到證據；不得宣稱哪個方案最好
rules:
  - 同一比較中分母、計入規則、Syntax 圖層版本必須一致，不一致就標示不可比較
  - 選定 B、拒絕 A／C 都由設計者以密語建立 HumanDecision，綁定具體 revision 與 hash；拒絕理由保存
acceptance_criteria: 權威 DB 有選定與拒絕的 HumanDecision；重開後一致；未選方案仍可查閱
tests: 新增 tests/test_scenario_comparison.py；瀏覽器 E2E（副本 DB、TEST_HARNESS 身分）
expected_return: 比較表截圖、決策時段後的權威狀態讀取結果
```

### W5-9 基礎量體編輯與儀表板（C＋D 線，D3–D5，等級 1／2）

```yaml
objective: 在選定方案上提供可重播的基本編輯，前端預覽與後端確認值分開。
scope:
  - 後端 src/urban_design/editing/{commands,floors,validation}.py：add_floor／remove_floor、push_side（整數公尺步數，沿面法向，相對原位置）、move（dx, dy）、rotate（精確角度，繞 footprint 質心）
  - 每次編輯：POST /api/v1/scenarios/{id}/edits，帶 expected_revision 與 idempotency key；產生 DRAFT 子 revision；記錄命令、參數、前後幾何 hash、驗證結果
  - 違規草稿可保存，標紅具體原因，不可接受、不可送分析；undo／redo 以 revision 指標實作
  - 前端：three.js 頂面拖曳一次一層（沒有 Shift 自由拉伸）、側面拖曳每次 1 m、移動、旋轉；儀表板顯示選取棟的樓層、高度、GFA，以及整體與分區的 FAR、建蔽率、上限、剩餘額度
  - 拖曳中只顯示「預覽」（前端估算）；放開後送後端，顯示「已確認」值
forbidden_changes: 不修改保留建築；不整數化地理座標；不提供三軸自由縮放
acceptance_criteria:
  - 依 W5-5 fixture 驗證每個操作的數值；拖曳後前端預覽與後端確認值一致，或差異被清楚標示
  - 重開後編輯歷史與 undo／redo 狀態恢復
tests: 新增 tests/test_editing.py、web/src/utils/editing.test.ts；瀏覽器 E2E 做一次拉高、一次側推、一次 undo
expected_return: 截圖、測試、權威 DB 寫入清單
```

### W5-10 道路節點基礎編輯（C＋D 線，D4–D5，等級 1）

```yaml
objective: 拖曳道路節點並精確吸附到端點或最近點；保留道路鎖定；拓撲重新驗證。
scope: 新增 src/urban_design/editing/roads.py 與前端互動
rules:
  - 吸附容差以地面公尺記錄；接到路段中間時切分該路段並更新 node／edge ID 與 lineage
  - 同層平交才相連；bridge／tunnel／layer 不同不誤連
  - 修改後重算 graph hash，相依的 Syntax 結果標 STALE（不自動重算）
acceptance_criteria: 平交 fixture 接通、跨橋 fixture 不接通；保留道路無法拖曳；零長邊被拒
tests: 新增 tests/test_road_editing.py；瀏覽器 E2E 一次節點拖曳
expected_return: 截圖、測試
```

### W5-11 測量與比例尺（D 線，D2–D3，等級 1）

依修正計畫 C7。先寫 `web/src/utils/measure.ts` 與測試，再接到 `Viewport2D.tsx`（R39 已含在基線，W5-0 審查後即可修改）。驗收標準照 C7：100 m 線段在不同縮放下量出 100.00 ± 0.01 m、20 × 50 m 多邊形量出 1,000.00 m²、自交多邊形拒絕、比例尺與 `metersPerPixel` 一致；3D 只做兩點距離與高差，透視圖不放單一比例尺。測量值不寫入 ledger、不供 AI 引用。

### W5-12 天氣推導方法提案（E 線，D1–D5，等級 2）

```yaml
objective: 依 PD-08 準備天氣推導方法提案，讓設計者在 W5 結束前可以批准或退回。
scope:
  - 三個既有 Rotterdam TMYx 候選檔（R08 保留的 bytes）逐一分析，唯讀
  - 太陽幾何診斷：分別假設時間戳記為「該小時終點」「起點」「中點」，用 ladybug 的 sunpath 計算太陽高度，統計「DNI > 0 但太陽在地平線下」的小時數；結果作為 DATASET_OBSERVATION＋INFERENCE，不是供應商語義證據
  - 推導檔：原始 bytes 不變，以逐列對照表把 Minute=0 映射為該小時終點；推導檔通過現行 validator（不得放寬 validator）
  - 敏感度：正負 1 小時位移下，南、東、西向垂直面與水平面的夏季累積直射量（用 ladybug 純 Python 計算，不需 Radiance）的變化；判斷是否可能改變 E2 比較方向
  - 提案文件：選哪一個候選檔（附比較與建議）、方法、時間規則、轉換、限制、範圍，並留給設計者填寫的批准欄
forbidden_changes:
  - 批准前不得發布 DatasetSnapshot、不得開始任何氣候實驗
  - 不下載新的天氣檔、不聯絡供應商、不修改 R03–R09 任何包
acceptance_criteria:
  - 診斷與敏感度結果可重現（固定程式版本與輸入 hash）
  - 設計者批准後（以密語建立 HumanDecision），才可在新的第 2 級證據包中發布 DatasetSnapshot
tests: 新增 tests/test_weather_derived_method.py（fixture EPW 列、三種時間假設、對照表往返）
expected_return: 提案包路徑、給設計者的一頁摘要
```

### W5-13 小項（任一線有空檔時，等級 0）

- **C5：** 修正 `docs/00_PRODUCT_VISION.md` 的 v4 敘述（該檔未被證據包記錄為 parent）；README 補列 08 前，先確認根目錄 README 是否被記錄為 parent，若是則改寫在藍圖修訂段。
- **C6：** 唯讀調查 `.../urban_design_runtime/state.sqlite3`，出一份短報告，不刪不改。

### W5-14 Radiance 重新佈建（選做，需下載核准，等級 2）

依修正計畫 C4，為 W6 的 E1 做準備。只有在核心工作包沒有觸發停損、且設計者核准下載時才做。

### W5-15 保留建築高度與樓層估算（C 線，D2–D3，等級 2）

```yaml
objective: 依 PD-11，用 3D BAG 高度估算保留與可改建築的樓層，供 FAR 計入。
scope: 設計範圍內（及其緊鄰）的建築；以 BAG identificatie 對應 3D BAG
steps:
  1. 下載前回報 3D BAG 的端點、查詢範圍、預計筆數或大小、資料版本、授權（CC BY 4.0），等設計者核准
  2. 下載後存成 DatasetSnapshot（原始回應、查詢、時間、版本、hash）
  3. floor-estimate-v1：max(1, round((70 百分位屋頂高 − 地面高) ÷ 估算層高))；估算層高在決策時段 2 前用 3.0 m 並標 FIXTURE_ONLY，之後改用批准的標準層高並重算
  4. industriefunctie 等大空間用途顯示範圍 [1, 估算值]；W5-5 的 FAR 對這些建築輸出範圍
  5. 對不到的建築維持 UnavailableValue
forbidden_changes: 不把估算值標成觀測值；不擴大下載範圍到整個 StudyArea 以外
acceptance_criteria:
  - 每棟建築的估算值附高度欄位名稱、3D BAG 版本、規則版本、限制
  - 更換估算層高後，樓層與 FAR 全部重算，舊結果標 STALE
  - 平台儀表板把估算值標為「估算」，大空間建築顯示範圍
tests: 新增 tests/test_floor_estimate.py（fixture 高度、大空間用途、缺對應、層高變更）
expected_return: 下載核准請求、DatasetSnapshot ID、估算摘要表、第 2 級證據包
```

### W5-AI 通用模型層：API 路線＋Hermes 路線（E 線，D2 起，等級 2）

依 PD-10、PD-12。

```yaml
objective: 建立可切換 provider 的模型層，讓 AI 依有效證據解釋基地與方案，並驗證每一句引用。
scope:
  - src/urban_design/model_provider.py 重構為 profile 驅動：
      openai_compatible（OpenAI、xAI、OpenRouter、ModelScope、Ollama、Hermes 共用）
      anthropic（Claude 原生 Messages API）
      gemini（既有）
    全部沿用現有 provider-neutral 介面與 transport 注入
  - config/model-providers.json：profile id、adapter、base_url、model、keychain 服務名稱、是否支援 JSON schema、資料外送類型（cloud／local／hermes）、enabled、備援順序；不含 secret
  - 預設 profile：openai-gpt-4o（第一順位）、hermes-urban-critic（最後順位）；其餘 provider 提供範本、預設 disabled，由設計者啟用
  - key 讀取：伺服器啟動時以 `security find-generic-password -s urban-design-<profile-id> -w` 讀取；另需 PROJECT_AI_AUTHORIZED=1；缺少時該 profile 為 BLOCKED_CREDENTIAL_ABSENT
  - 第一次使用某 profile：先呼叫該 provider 的模型清單，確認設定的模型存在；不存在就停用該 profile 並上報，不得自行替換模型
  - 結構化輸出：支援 JSON schema 的 provider 用 schema 模式；不支援的要求 JSON 回覆，一律由本地 validator 解析與驗證
  - 備援：只在確定請求沒有送出（缺 key、連線不上、401／403）時換到下一個 profile；驗證失敗、逾時、OUTCOME_UNKNOWN 不換
  - Hermes 路線額外檢查：只連設計者指定的專用 profile 埠；每次工作階段先 GET /v1/toolsets，任何工具啟用就拒絕；請求不帶 X-Hermes-Session-Key；ModelRun 記錄 Hermes 版本、profile、Hermes 回報的模型，以及從 profile 設定唯讀取得的上游 provider／model（只解析模型欄位，不讀取或記錄任何 secret）
  - 呼叫計數：全部 profile 合計全週 200 次，單次輸出 2,048 tokens，逾時 30 秒；達上限回報 BLOCKED_BUDGET
  - 用途：基地解釋（site critic）、方案策略說明（W5-7）、方案比較說明（W5-8）
  - 每次呼叫寫 ModelRun：profile、provider、實際回傳的模型版本字串、模板版本與 hash、請求與回應 hash、驗證結果、狀態
  - 前端：每個 AI 回答標出 provider 與模型；設定頁顯示各 profile 狀態（可用、缺 key、停用、超出預算），但不顯示或輸入 key
rules:
  - 送出內容只限 evidence bundle（公開資料衍生值、分析結果、方案指標、限制）；不含 key、本機路徑、個人資料
  - 驗證層：JSON 格式正確不夠；每句引用的 evidence ID 必須屬於同一方案、同一半徑、同一單位與版本；出現證據中沒有的數字就拒絕；「integration 高＝人多」之類的無據推論要拒絕或降級為假說
  - 模型失敗或格式錯誤：記 MODEL_FAILED，同一 profile 最多重試一次；派送後失聯記 OUTCOME_UNKNOWN
forbidden_changes:
  - 代理不得建立、輸入、讀出、顯示或記錄任何 key（包括 Hermes 的 API_SERVER_KEY）；log 與 artifact 遮蔽 Authorization 標頭
  - 不得使用 Hermes life-agent（8644）或任何啟用工具或記憶的 Hermes profile；不得碰 8787；不得停止或重啟既有 Hermes 行程；未經設計者授權不得修改 ~/.hermes 設定
  - 不得讓模型直接寫 ledger、改幾何、改約束或調工具權限
  - 沒有可用 profile 時，不得用模板冒充 AI 回覆
acceptance_criteria:
  - 假 transport 測試覆蓋每種 adapter：正確回應、捏造數字、錯方案、錯半徑、錯單位、過期來源、格式錯誤、逾時、401、連線失敗後的備援、驗證失敗時不備援、達上限、Hermes toolsets 非空時拒絕
  - live 煙霧測試：設計者設定好的每個 profile 各做一次基地解釋；CP5-AI 至少需一個 profile 成功；結果附 ModelRun 與引用驗證報告
  - 每日回報列出各 profile 的呼叫次數與總數
tests: 擴充 tests/test_site_critic.py；新增 tests/test_model_profiles.py、tests/test_openai_compatible_provider.py、tests/test_anthropic_provider.py、tests/test_hermes_route.py（全部用假 transport；live 測試另以標記區分，預設不跑）
expected_return: 分支、commit、測試、config/model-providers.json、各 profile 的 live 煙霧測試 ModelRun ID 與驗證報告、第 2 級證據包
```

**設計者要先做的事（任選，至少一項）：**

1. OpenAI：建專案專用 key 並設用量上限，存入 Keychain：

   ```bash
   security add-generic-password -s urban-design-openai-gpt-4o -a "$USER" -w
   ```

2. 其他 API（Claude、xAI、OpenRouter、ModelScope）：同上，把服務名稱換成 `urban-design-<profile-id>`，並告訴執行者要啟用哪個 profile 與模型。Ollama 只需本機已安裝並下載模型。
3. Hermes：建立沒有工具、不寫記憶的專用 profile（建議 `urban-critic`），開在新埠號，把它的 API_SERVER_KEY 存入 Keychain（`urban-design-hermes`）；或授權執行者依 Hermes 本機文件建立。

## 6. Checkpoints

| CP | 通過條件 | 不算通過 |
|---|---|---|
| CP5-0 | 起點報告；R39 已送審 | 沿用本計畫第 1 節數字而未重查 |
| CP5-1 | 決策機制上線；決策時段 1 的三類 HumanDecision 存在；C1 截圖與紀錄完整 | 代理代按確認、actor 仍為 designer |
| CP5-2 | PST 與自製引擎比對達標或已上報；method manifest 完整 | 調整門檻湊通過；只改欄位名稱 |
| CP5-3 | 分析卡片與 Syntax 由權威狀態提供；STALE 與 idempotency 有測試 | API 仍即時計算 |
| CP5-4 | 已批准 ConstraintSet 存在；未批准者不可啟用 | 使用 fixture 值當正式約束 |
| CP5-5 | ≥ 3 個有效、不同、可重現方案；失敗候選保存 | 換色或只改高度湊數 |
| CP5-6 | 設計者以 HumanDecision 選 B、拒 A／C | AI 或執行者代選 |
| CP5-7 | 編輯與儀表板數值一致；違規草稿不可接受；重開可恢復 | 只改畫面不改資料 |
| CP5-S | 800 m、2 km 圖層就緒；10 km 就緒或有具體阻塞 | 無方法紀錄的彩色線圖 |
| CP5-AI | 至少一個 profile 完成經驗證的基地與方案說明各一次；錯誤引用全部被拒；每個回答標出 provider 與模型；呼叫數在上限內 | 用模板冒充 AI；只驗 JSON 格式；使用有工具的 Hermes profile |
| CP5-F | 保留建築樓層估算附來源與規則；大空間建築為範圍；缺對應為 unavailable | 把估算當觀測；缺值填 0 |
| CP-W5 | 第 0 節的 7 項可以由獨立審查者實際操作；全套測試通過；延續項逐項有狀態 | 只有測試總數或證據包 |

狀態只能是 PASS、FAIL、BLOCKED、OUTCOME_UNKNOWN。外部 dispatch 後失聯一律先標 OUTCOME_UNKNOWN，核對產出與狀態後才決定是否重試。

## 7. 測試命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider
```

```bash
npm --prefix web run test
```

```bash
npm --prefix web run build
```

```bash
npm --prefix web run lint
```

瀏覽器流程沿用 R37／R39 的命令（見 `artifacts/week4-execution-r37-20260924T2108z-context-network-fail-closed/test-results.json`），一律使用 DB 副本與臨時埠。

## 8. 回報格式（每天一次，以及每個停損時）

```text
DAY / TIME (UTC):
GIT: branch, commits, dirty?
CP RESULTS: CP-ID -> PASS | FAIL | BLOCKED | OUTCOME_UNKNOWN（附證據路徑）
VISIBLE DEMO: 實際操作步驟與截圖路徑
TESTS: 命令、collected／passed／failed
AUTHORITY WRITES: 寫了什麼、備份快照與前後 SHA-256
HUMAN DECISIONS: 已建立的 HumanDecision ID（由設計者建立）；待決事項
REQUESTS: 下載、外部請求、各 profile 的模型呼叫次數與合計（上限 200）
STOP-LOSS: 是否觸發；卡點與選項
WEATHER: 提案進度；是否已獲批准
CARRY-OVER: 延續項狀態
NEXT: 下一步與需要設計者做的事
```
