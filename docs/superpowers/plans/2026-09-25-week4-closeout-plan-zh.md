# Week 4 收尾執行計畫

**版本：** 2026-09-25／v1。**撰寫與審查：** Claude（Commander）。**執行：** AntiGravity（Gemini 3.8 Flash），依 PD-18。
**目標：** 把 Week 4 所有**可以由執行者完成**的工作做完。只能由設計者或其他工作線完成的 gate，以「具名負責人＋具體阻塞」結案。最後交出一份 Week 4 驗收請求，由 Commander 審查、設計者決定是否接受。
**依據：** `AGENTS.md`、`CLAUDE-commander.md`、[決定紀錄 PD-01–PD-18](../../decisions/2026-09-25-plan-decisions-zh.md)、[Week 4 原計畫](2026-09-22-week4-platform-site-analysis-zh.md)、[修正計畫 C1–C8](2026-09-25-control-tower-correction-plan-zh.md)、[Week 5 計畫](2026-09-25-week5-execution-plan-zh.md)（了解分工與相依）。

## 0. 分工（PD-18）

| 工作 | 負責 |
|---|---|
| R40–R55 保存成果的審閱與選擇性合併（`wp/w4-r40-r53`） | **AntiGravity** |
| C3 分析結果持久化 | **AntiGravity** |
| 六張 Syntax 圖層：PST 驗證、OSM 下載（PD-17）、800 m 重算、2 km、10 km、穩定性 | **AntiGravity**（以 Luna 的 `wp/w5-04-pst-runtime` 為起點） |
| PD-14 ledger 來源註記（事件 182–187） | **AntiGravity**（需 `wp/w5-01` 已合併） |
| C1 QGIS 重驗：操作說明與結果核對 | **AntiGravity** 準備；**設計者**本人按鈕 |
| C5 文件修正、C6 殘留 SQLite 調查 | **AntiGravity** |
| Week 4 驗收請求 | **AntiGravity** 整理；**Commander** 審查；**設計者**決定 |
| W5-1 決策機制（actor、決策密語） | Luna（已完成，待 Commander 審查與合併） |
| Live AI（W5-AI，Week 4 的 CP4-7 依賴它） | Luna |
| 測量工具、生成、編輯、W5 決策時段 | Luna |

**共用核心檔擁有權：** `src/urban_design/models.py`、`store.py`、`api.py` 在 `wp/w5-01` 合併進 `main` 之後，由 AntiGravity 擁有，直到本計畫的 WC-2、WC-3 合併完成，再交還 Luna。在 `wp/w5-01` 合併之前，AntiGravity 不得修改這三個檔案。

## 1. 完成定義

Week 4 的每個 gate 都必須落在下列之一，並附證據路徑：

- **PASS**：功能在真實流程可操作，有測試、runtime 證據與權威狀態讀取結果。
- **BLOCKED（具名）**：寫明負責人（設計者、Luna 或 Commander）、缺什麼、解除條件。例如：C1 等設計者本人按鈕；CP4-7 等 Luna 的 W5-AI 與設計者的 key。
- **FAIL**：照實記錄，不得改寫成通過。

AntiGravity 不得自行宣告 Week 4 通過；只能交出驗收請求。

## 2. 共同規則

### 2.1 Git 與工作目錄

- 在專案外建立自己的 worktree（例如 `git worktree add ../w4-closeout -b wp/w4-closeout main`），所有工作都在那裡做。**不得在主工作目錄 `/Users/jackhsieh/Downloads/TUD/Q5/project` 工作。**
- 只能在自己的 `wp/w4-closeout*` 分支 stage 與 commit。不得碰 `main`、push、reset、clean、刪除分支。合併到 `main` 由 Commander 審查、設計者核准。
- 一個 commit 做一件事，commit message 寫測試命令與結果。

### 2.2 證據分級（PD-06）與停損（PD-05）

- **第 0 級：** 一般程式修改，commit 加測試輸出。
- **第 1 級：** UI 功能，再加截圖。
- **第 2 級（完整證據包）：** 只用於寫入權威 DB、外部下載、外部 runtime、gate 判定。
- 不得再為審查某個證據包而另做一個證據包。
- **停損：** 同一項目連續 2 個 revision 或 1 個工作天沒有功能進展，就停下回報卡點、已試過什麼、2–3 個選項。只停受影響的項目。

### 2.3 權威 DB（PD-04）

- 可追加 ToolExecution、Artifact、EvidenceResult／EvidenceCard、分析輸入的 DatasetSnapshot，以及 PD-14 的來源註記。
- 每次寫入前用 `sqlite3` 的 `.backup` 做快照，存到 `~/.local/share/urban-design-backups/`，記錄快照與寫入前後的 SHA-256；actor 標 `AGENT_AUTOMATION`。
- 開發與測試一律用 DB 副本。
- 禁止建立 HumanDecision、啟用 Constraint、批准設計範圍或 StudyArea、接受方案、發布天氣 DatasetSnapshot。

### 2.4 絕對禁止

- 透過電腦操作介面或任何自動化，代替設計者執行會寫入權威 DB 的 QGIS 或瀏覽器動作（PD-14）。代理驅動的測試只能連 DB 副本。
- 捏造數值、把未知當 0、把探索結果標成正式結果、把 fixture 值當成已批准設定（fixture 值一律標 `FIXTURE_ONLY`）。
- 以一般 closeness／betweenness 冒充 angular 指標；把 method-comparison-v1 的 FAIL 改寫成通過。
- QGIS MCP 任意執行、SQL、batch 繞道；接觸 Hermes（8787、8644）；呼叫任何模型服務；關閉或重啟不是你啟動的服務。
- 修改舊證據包；修改被證據包記錄為 parent 的文件（修改現行文件前先 grep `artifacts/*/parent-references.json` 與 `integrity-manifest.json`）；修改 `web/index.html`、`web/src/index.css`。
- 讀出、印出、記錄任何憑證或 key。
- 刪除檔案或目錄；需要保留就改名。所有重試、清理、改名都要在回報中揭露。
- 把工作再委派給其他模型或 agent。

## 3. 工作項目（依序）

### WC-0 起點核對（等級 0）

- 重查：git 分支與 worktree、權威 DB 的 SHA-256、`quick_check`、ledger 數、各類 heads、埠監聽（8787、8644 只用 `lsof` 觀察）。與上次紀錄比較，列出差異：2026-09-25 時 ledger 187、DB `3e30c3d4…`、workspace revision 6 DRAFT。
- 確認 `wp/w5-01-decision-actor` 是否已合併進 `main`，並把結果寫在回報開頭。未合併時，先做 WC-1 與 WC-3 中不動共用核心檔的部分。

### WC-1 審閱並合併 R40–R55 保存成果（等級 0，涉及證據包時 1）

- 來源：`wp/w4-r40-r53`，commit `19ed8d6` 與 `10f0903`，兩次都未經審查。
- 逐項分類為「採用」「改寫後採用」「捨棄」，寫成 `docs/w4-closeout/r40-r55-triage.md`，並附理由。
- **優先順序：**
  1. R41 設計範圍、R46 決策保護、R50 分區範圍檢查、R55 的同步中狀態修補。Luna 第 1 天決策時段的畫面需要這些。
  2. R40 數值驗證、R43／R45 同步與瀏覽器相關修改。
  3. R44／R47 幾何與邊界相關、R48／R53 的 PST 工作。
- **PST 只保留一份實作：** 以 `wp/w5-04-pst-runtime` 的 `src/urban_design/syntax_engines/` 為主，runtime 放在 repo 外的 `~/.local/share/urban-design-runtimes/pstalgo-3.3.1/`。R48 放進 repo 的 `runtimes/` 與 `src/urban_design/pst_engine.py`，只把有用的部分併進 adapter，不再保留第二份。
- 與 `wp/w5-01` 衝突時，以 `wp/w5-01` 的 actor 與決策結構為準。
- 每合併一段就跑全套測試。
- R54、R55 把 CP1 標為 PASS_SCOPED，依 PD-14 無效，不得沿用。

### WC-2 分析結果持久化（修正計畫 C3，等級 2；需 `wp/w5-01` 已合併）

- 基地分析卡片與 Syntax 結果存成 ToolExecution＋Artifact＋EvidenceResult／EvidenceCard。R02 的 800 m 先以 `IMPORTED_HISTORICAL_EXPLORATORY` 登錄，WC-3 以 PST 重算後成為新結果，舊值保留並標為舊方法。
- API 改讀持久化結果並重驗 hash；沒有結果時回報 `NOT_COMPUTED`，不在請求中即時補算。
- 輸入 hash 改變時，相依結果標 `STALE`；同一 idempotency key 重複派送不得產生第二筆。
- **測試：** 新增 `tests/test_analysis_persistence.py`；既有的 `test_site_analysis`、`test_week4_r04_evidence`、`test_red_team_week4` 全過；瀏覽器流程重跑一次（DB 副本）。
- 寫入權威 DB 前後都要記錄 hash。

### WC-3 六張 Syntax 圖層（PD-15、PD-17，等級 2）

1. **PST 驗證：** 用可手算的小網路驗證 PST 本身，包括直線、T 字、十字、不同轉角、孤立元件、立體交叉。期望值寫在測試裡，並附手算過程；不得由 PST 輸出反推期望值。method-comparison-v1 保留 FAIL。
2. **method manifest：** 寫明 PST 3.3.1、runtime hash、半徑模式 `walking`、角度成本、正規化公式、分段方式、孤立元件與邊界效應處理。
3. **下載（PD-17 已核准，只限這兩個檔）：**
   - `https://download.geofabrik.de/europe/netherlands/zuid-holland-260922.osm.pbf`：211,355,323 bytes，ODbL 1.0，需標註 © OpenStreetMap contributors。
   - 同一抽取檔的 `zuid-holland.poly`：上限 1 MB。
   - 每個檔只送 1 次 GET，不自動重試、不續傳、不改用其他網址。PBF 回應上限 262,144,000 bytes，逾時 300 秒。
   - HTTP 非 200、大小不符、跨主機重導、逾時或結果不明，一律停下核對，不重送。
   - 檔案日期或大小若已改變，停下並重新列出網址、日期、大小請設計者核准。
   - 原始 bytes 與回應標頭存進第 2 級證據包，並登錄為 DatasetSnapshot。
   - 若需要讀取 PBF 的新 Python 依賴（例如 `osmium`），先回報版本與授權，等核准後才可加入。
4. **路網政策 `syntax-network-policy-v1`：** 列出納入與排除的 `highway` 類別、access 處理方式、立體交叉規則（layer／bridge／tunnel）。PST 若無法表達立體交叉，就先切分路段並傳入 unlink 點。設計者確認政策前，結果標為 EXPLORATORY。
5. **範圍：** 2 km 用 StudyArea 外擴 4 km；10 km 用外擴 20 km。用 `.poly` 檢查是否超出省界；超出的邊緣路段標 `EDGE_AFFECTED`，並寫明限制。
6. **計算：**
   - 800 m 以 PST 重算。
   - 2 km 用外擴 4 km 與 6 km 各算一次，比較 StudyArea 內的結果。
   - 10 km 先用 2 km 的執行時間推估；**單次預估超過 2 小時就停下上報**，並附選項。可行時用外擴 15 km 與 20 km 各算一次。
   - 穩定性標準 stability-v1（提案）：StudyArea 內 Spearman ≥ 0.98；變化超過 5% 的路段標 `EDGE_AFFECTED`。
7. **持久化與顯示：** 結果依 WC-2 寫入權威 DB；平台顯示六張圖層，每張附方法、半徑、正規化方式、狀態、限制。UI 用「局部／中距／區域尺度」，不標成步行、自行車、汽車。
8. **測試：** `tests/test_pst_adapter.py`、`tests/test_pst_fixtures.py`、`tests/test_regional_network.py`、`tests/test_syntax_persistence.py`；既有的 Syntax 與 context network 測試全過。

### WC-4 PD-14 來源註記（等級 2；需 `wp/w5-01` 已合併）

- 用 `wp/w5-01` 提供的機制，為 ledger 事件 182–187 追加註記：
  - 182–185 的 `designer` 是程式預設值，未經驗證。
  - 186–187 是代理經電腦操作介面操作 QGIS 所寫入，actor 記錄有誤。
- 只追加，不修改舊事件。寫入前做備份快照，記錄前後 hash；讀回確認舊事件 bytes 不變。

### WC-5 C1 QGIS 重驗支援（等級 2）

- 寫一頁操作說明 `docs/w4-closeout/c1-qgis-runbook.md`：
  - 啟動方式：`Open Urban Design QGIS.command`。
  - 要選哪一類要素、按哪個鈕、要截哪些畫面。
  - 平台端要看到什麼結果。
  - 預設寫入 DB 副本；要寫入權威 DB，需設計者事先明說。
- **代理不得操作 QGIS。** 設計者完成後，AntiGravity 核對 site-context 200、sync 201、revision、要素 ID、來源快照 ID、重新整理後是否一致，並做成證據包。
- 設計者尚未操作時，C1 標為 `BLOCKED（負責人：設計者）`。

### WC-6 小項（等級 0）

- **C5：** 修正 `docs/00_PRODUCT_VISION.md` 中 active StudyArea 為 v4 的敘述，改為 v5。README 補列 08 修訂契約前，先確認 README 未被證據包記錄為 parent；若已被記錄，改在藍圖修訂段補充。
- **C6：** 唯讀調查根目錄 `.../urban_design_runtime/state.sqlite3`：`quick_check`、heads、ledger、最後事件時間，與權威 DB 比較，並 grep 可能產生該路徑的程式。寫成短報告，不刪不改。

### WC-7 Week 4 驗收請求（最後做）

- 在 `docs/w4-closeout/week4-acceptance-request.md` 逐一列出 Week 4 gate，每項附狀態、證據路徑、測試節點、權威狀態讀取結果：
  - CP4-0 至 CP4-8
  - QGIS GUI、平台同步與保存、保留與分區操作、基地分析、六張 Syntax、Live AI、出圖、人類決策、獨立 walkthrough
- BLOCKED 項目寫明負責人與解除條件。
- 附一份給獨立審查者的完整 walkthrough 腳本：同步 → 保留建築與道路 → 分區 → 讀基地分析與六圖 → 詢問 AI → 保存 → 出圖 → 重開。代理用 DB 副本預跑一次並附截圖。
- 全套測試：
  - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider`，Radiance 測試需設定 runtime 的 `RAYPATH`。
  - `npm --prefix web run test`、`build`、`lint`。
- 回報 collected、passed、failed、skipped 數；未執行的測試不得記為 PASS。

## 4. 回報格式

每天一次、每次停損、以及完成時各回報一次：

```text
TIME (UTC):
GIT: worktree、branch、commits、dirty?
MAIN 狀態: wp/w5-01 是否已合併
ITEMS: WC-0–WC-7 -> PASS | FAIL | BLOCKED(負責人) | OUTCOME_UNKNOWN（附證據路徑）
TESTS: 命令、collected／passed／failed／skipped
AUTHORITY WRITES: 內容、備份快照、前後 SHA-256
DOWNLOADS: 網址、大小、SHA-256、HTTP 狀態
RETRIES/RENAMES/CLEANUP: 全部揭露
STOP-LOSS: 是否觸發；卡點與選項
NEEDS: 需要設計者、Luna 或 Commander 做的事
```
