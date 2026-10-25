# AntiGravity / Gemini 3.8 — Week 4 執行 Prompt

**日期／版本：** 2026-09-22／v1  
**用途：** 直接貼給 AntiGravity，指定 Gemini 3.8 執行本學期 Week 4。  
**範圍：** 實作平台接入與基地分析；完成後停止，不跨入 Week 5 的正式 morphology 生成。

---

```text
你是本專案的外部執行工程師，使用 Gemini 3.8。請直接實作，不要只回覆計畫、
建議或程式碼片段。你必須在專案 workspace 內完成可檢查的程式、測試、實際
操作證據與交接報告。你的結果會回到 Sol/Astra 作獨立審查；你不能接受自己的
輸出為最終 PASS。

PROJECT ROOT
/Users/jackhsieh/Downloads/TUD/Q5/project

PRIMARY OBJECTIVE
完成學期 Week 4 的「平台接入＋基地分析」：

1. QGIS 以明確同步按鈕把版本化 StudyArea／來源要素同步到自有平台；
2. 平台能以真實 feature ID 選擇建築與道路的 preserve/editable/undecided；
3. 使用者能畫局部分區、輸入機能／開放空間訴求，看到 hard/soft constraint 預覽；
4. 平台顯示可追溯的基地分析與資料缺口；
5. 在共同清理路網上真正計算 800 m、2 km、10 km 的 angular integration 和
   angular choice，共六個可視圖層；
6. 一個真實配置的 AI provider 只能根據有效 Evidence Cards 解釋基地條件、
   潛能、限制與設計假說；
7. 輸出至少一張可開啟、帶版本／圖例／狀態的基地分析圖；
8. 形成 Week 5 可使用的 validated handoff，但不要開始正式生成 3–5 個方案。

REQUIRED READING — 按順序完整讀取

1. AGENTS.md
2. README.md
3. docs/08_WORKFLOW_REALIGNMENT_2026-09-22.md
4. docs/interviews/2026-09-22-grillme-workflow-interview-v1.md
5. docs/superpowers/plans/2026-09-22-week4-platform-site-analysis-zh.md
6. docs/superpowers/plans/2026-09-22-semester-project-blueprint-zh.md
7. docs/00_PRODUCT_VISION.md
8. docs/01_PRODUCT_REQUIREMENTS.md
9. docs/02_SYSTEM_ARCHITECTURE.md
10. docs/03_AGENT_ARCHITECTURE.md
11. docs/05_EVIDENCE_FRAMEWORK.md
12. docs/06_EVALUATION_FRAMEWORK.md
13. docs/07_IMPLEMENTATION_PLAN.md
14. 與 R08–R09-R01、spatial-r01、spatial decision addenda 直接相關的文件與 manifests。

若 prompt 與 AGENTS.md 衝突，以 AGENTS.md 為準。研究報告提供背景，不自動批准
產品設定或資料政策。

CURRENT STATE — 必須重新驗證，不可照抄

- 專案不是 Git repository；不要建立虛假的 branch、commit 或 worktree 紀錄。
- 已有 Python/Pydantic/FastAPI/SQLite、StudyArea、QGIS facade、來源封存與 ledger 基礎。
- 不可假設已有 React 前端、可用的 Space Syntax runtime 或量體 editor。
- active StudyArea 預期為 Rotterdam M4H v5；v4 預期 superseded，但必須查 SQLite
  和 ledger 證明目前狀態。
- spatial-r01、原/r02/r03 addenda 與 weather R05–R09-R01 都是歷史／審查證據；
  不得覆寫。任何 verifier/source hash drift 要明確報告。
- weather 預期仍為 BLOCKED / SEMANTICS_UNRESOLVED；這不是本週要解決的工作。
- Hermes 預期擁有 8787；bridge 預期使用 8788。必須核對實際 listener owner，
  不得殺掉、重啟或搶占無關服務。

EXECUTION ORDER

按以下順序執行。每個 checkpoint 先留下證據，再進入下一階段。失敗只阻擋真正
相依的工作；其他離線／UI 工作繼續。不要因某一項 BLOCKED 就提前結束整個 Week 4。

PHASE 0 — CURRENT BASELINE / CP4-0

- 檢查實際 source tree、依賴、runtime、SQLite、ledger、artifact manifests、ports。
- 記錄 active StudyArea、v4 狀態、各主要 entity 實際 counts、目前前端／API／AI／
  Syntax 能力，以及測試 collection；數字必須從目前狀態讀取。
- 分開 archival_integrity、current_authority_state、functional_acceptance。
- 將結果寫入一個新的、不可覆寫的 Week 4 baseline revision。
- 不修改任何歷史 artifact 來讓 verifier 變綠。

CP4-0 PASS：基線、protected state、drift 與可執行範圍都可追溯。若來源／authority
drift，標記受影響真實工作，但使用明示 synthetic fixtures 繼續建立不相依功能。

PHASE 1 — HIGH-RISK SPIKES / CP4-1a + CP4-1b

A. Space Syntax：
- 查第一方文件，選擇可在目標環境真正執行 segment angular integration／choice
  並支援 metric radius 的引擎；記錄版本、授權、安裝方式與 runtime boundary。
- 建立直線、T 字、對稱十字、不同轉角、孤立元件、同平面交叉與 bridge/tunnel
  不相接 fixtures。
- 先寫 reference/known-answer tests，再接引擎。reference 不能由同一被測函式生成。
- 一般 closeness/betweenness 不得改名冒充 angular integration/choice。

B. Week 5/W6 風險預研：
- 建立最小幾何試算：逐層體塊、平面分割、局部推拉、每層 footprint、無效幾何拒絕。
- 只核對 Ladybug/Honeybee/Radiance 真實 runtime 與既有 smoke；不要執行基地氣候分析。
- 列出 E3/E4/E5 尚需的輸入與 runtime，不把 import success 當功能完成。

CP4-1a PASS：真實 Syntax 引擎通過小型 reference。若失敗，保留 BLOCKED 與具體原因，
繼續平台／同步／基地指標，不降級成假 Syntax。
CP4-1b PASS：W5 幾何 feasibility 有實際試算，環境工具能力有真實或明確未驗證狀態。

PHASE 2 — TYPED WORKSPACE SYNC / CP4-2

- 先閱讀現有 models.py、store.py、bridge.py、qgis_facade.py，重用 domain IDs、transaction
  與 append-only ledger，禁止另建聊天內權威狀態。
- 實作 typed SyncRequest、FeatureDisposition、WorkspaceRevision 或與現有模型相容的等價
  契約；extra fields fail closed，客戶端不可傳 approved=true 取得批准。
- 實作 POST /api/v1/workspaces/sync 與 GET /api/v1/workspaces/{id} 或符合現有 API
  風格的等價 endpoint。
- 使用 expected revision 與 idempotency key；相同 key/相同 payload 重播同一 revision；
  相同 key/不同 payload 409；stale revision 409；無效來源／policy 具體 422。
- 後端從 persisted records 解引用來源與 hash，不相信客戶端 geometry/status/approval。
- QGIS 只使用 allowlisted export／既有快照；不可加入 execute_code、任意 Python、任意
  SQL 或 batch bypass。
- 測 transaction rollback、duplicate dispatch、missing parent、stale StudyArea、source
  mutation、連線中斷 OUTCOME_UNKNOWN。

CP4-2 PASS：同步可持久、可重播、不覆蓋既有草稿；不是只把 QGIS 畫面截圖送到平台。

PHASE 3 — OPERABLE PLATFORM VERTICAL SLICE / CP4-3

- 若 web/ 不存在，建立最小 React/TypeScript app、lockfile、unit test、browser E2E、build
  scripts；選擇 map/3D libraries 前記錄版本與 licence。
- 主畫面至少有：2D map、3D massing/context、feature/brief sidebar、AI/evidence panel、
  revision/job status、Sync 按鈕。
- 使用 stable feature IDs；地圖、3D、sidebar 對到同一物件。記錄 EPSG:28992→local
  render transform 與逆轉換。
- sync 遇到未保存／既有 draft 顯示版本 diff，不 silent overwrite。
- refresh/restart 後從 server 恢復正式狀態；background tiles 失敗不隱藏 frozen vectors。
- 新服務先找未占用 port，記錄 owner；禁止使用 8787。

CP4-3 PASS：真實 UI 可以同步、選物件、切 2D/3D、重開恢復，並有 browser test 及
截圖/短錄影。只有 mock 畫面或 HTTP 200 不算 PASS。

PHASE 4 — PRESERVE / EDITABLE / UNDECIDED + LOCAL BRIEF / CP4-4

- 建築與道路提供 preserve/editable/undecided，保留物預設鎖定。
- 原始觀測資料不可因方案標記而刪除；變更是 scenario overlay。
- 能畫局部 polygon 並輸入機能／開放空間註記；保存 geometry、原始文字、作用範圍、
  hard/soft 建議、作者與 revision。
- 明確分開 StudyArea、ContextExtent、ExplorationDesignArea；後者也不是法律
  DesignBoundary。
- 提供整體 FAR 上限與可選分區上限的輸入介面，但本週沒有任何人類已批准的數值。
  不能填常見值、3.5m 等示例為 project default。
- AI 結構化結果先給人類確認；沒有 HumanDecision 就保持 DRAFT。
- 測 invalid/empty/self-intersecting polygon、範圍外、錯 feature ID、重疊區無分配規則。

CP4-4 PASS：保存與重開一致；人類未批准的設定沒有進入有效 constraint state。

PHASE 5 — SITE ANALYSIS / CP4-5

- 先離線審查 frozen PDOK/OSM 可提供哪些欄位與 scope，分類 observed/unavailable/not
  applicable；missing 不可變成 zero。
- 計算可由現有資料支持的 source coverage、building footprint/coverage、已知用途/POIs、
  water/open space、road topology/connectivity；缺高度/樓層時不可生成假 FAR。
- 每個結果綁 source、scope、unit、formula version、geometry hash、parameters、limitations
  和 validation status，並在 UI 可開 Evidence Card。
- grocery accessibility 只有在三項 spatial policies 真實批准後才運行；未批准只阻擋
  該指標，不阻擋其他基地分析。
- UI 與 AI 使用同一 result ID，不得各自重新算數字。

若現有 spatial-r01 envelope 無法支持區域 Syntax，只先用它完成範圍內基地分析與
offline fixtures。需要新 PDOK/OSM/Overpass live acquisition 時，先產出單獨 request
proposal：endpoint、licence、bbox/extent、分析目的、最大 requests/pages/bytes/time、
timeout、retry=0、去重及失聯處理。這份 prompt 不授權新 live geodata dispatch；把
proposal 交給人類，同時繼續所有不依賴該請求的工作。

CP4-5 PASS：實算的基地證據與缺口都可見；未知不被說成沒有。

PHASE 6 — SIX SPACE SYNTAX LAYERS / CP4-6

- 使用 CP4-1a 已驗證的共同 cleaned segment network。
- 計算 800、2,000、10,000 metres 三個 radius 的 angular integration 與 angular choice。
- 記錄 segmentation、angle cost、metric radius、normalization、formula/tool version、孤立
  元件、bridge/tunnel/layer 規則與 unknown tags。
- 分開 analysis radius 與 data acquisition extent；5 km buffer 不足以自動支持 10 km。
  20 km 也只是候選，必須用擴大範圍的 stability/boundary sensitivity 證明。
- UI 顯示六個可切換圖層、原值、legend、radius、normalization、缺失與 edge-affected
  segments。預設名稱是 local/mid/regional scale，不稱為已驗證 walk/bike/car mode。
- 在新區域資料未被授權／取得時，將真實 10 km 結果標為 BLOCKED；可用 reference/
  synthetic network 完成軟體功能，不可把它輸出成 Rotterdam 實算 PASS。

CP4-6 PASS：只有在六層都是真實方法、來源範圍足夠、reference 和 boundary checks 通過
時才成立。軟體功能 PASS 與 Rotterdam data readiness 必須分開報告。

PHASE 7 — EVIDENCE-BOUND AI + FIRST FIGURE / CP4-7

- 重用 provider-neutral adapter，接一個真實、已配置且允許的 model provider。若環境
  沒有 credential，保留 live AI BLOCKED，fixture adapter 只能測試 schema。
- AI 輸入是經驗證的 evidence bundle；輸出至少有 evidence refs、observations、design
  hypotheses、limitations、可選 next questions。
- 驗證 fake ID、錯 scenario、錯 radius、錯 unit、stale result、unsupported number、
  prompt injection 和隱藏 overall ranking。
- AI 不能直接改 ledger、批准 constraint、選方案或提升工具權限。
- 參考圖片/網頁若使用，保存 URL、作者/來源與 licence limitation；不得把 inspiration
  轉為 quantitative evidence。
- 輸出至少一張可打開的基地/Syntax PNG，隱藏 gizmos/selection/chat，包含 revision、
  metric/unit、legend、radius/time（如適用）、validation/stale status。

CP4-7 PASS：真實 AI 回答與 UI 顯示的 evidence 一致；圖片 artifact 能追到同一版本。

PHASE 8 — REGRESSION, RED TEAM, REVIEW, W5 HANDOFF / CP4-8

- 先跑所有新增 focused tests，再跑完整 backend suite、frontend unit/build/E2E；保存實際
  collected nodes 和結果，不預設 test counts。
- Red-team：source mutation、missing parent、stale job、missing policy、unknown access、
  duplicate dispatch、rollback、empty-vs-unavailable、AI 錯引用、QGIS/model connection loss。
- 重新驗證受保護歷史 package；合法新增 ledger/state 另列 current authority change，
  不要求 mutable state 永遠等於舊數字。
- 找獨立 reviewer 重跑：Sync → 選建築/道路 → 畫分區 → 查看基地證據/六層 → 問 AI →
  保存 → 出圖 → 重開。執行者不能批准自己的結果。
- 形成 immutable Week 5 handoff：source/context refs、feature dispositions、draft/approved
  brief refs、valid evidence、Syntax method manifest、尚缺人類決策、geometry feasibility、
  tests、limitations、parent hashes。
- 停止。不要建立或接受正式 3–5 morphology proposals；那是 Week 5。

CP4-8 PASS：Week 4 有可操作的垂直流程與獨立證據。若部分 BLOCKED，分別報告已完成的
軟體能力、資料阻塞與仍可進行的 Week 5 fixture work，不能只給一個模糊總狀態。

PROTECTED STATE / FORBIDDEN ACTIONS

- 不修改或重新封裝 R05–R09-R01、blocked weather r03、spatial-r01、原/r02/r03
  decision addenda、歷史 StudyArea geometry、superseded v4 bytes、舊 ledger events。
- 不執行 spatial policy approval；不虛構 actor、reason、origin/destination/network choice。
- 零 weather ZIP/API request；不修改 Minute，不放寬 EPW validator，不選 weather source，
  不發布 weather DatasetSnapshot，不啟動正式 climate experiment。
- 不推導 cadastral ownership、zoning compliance、legal buildability 或正式 DesignBoundary。
- 不占用/重啟/kill Hermes 8787；不對 QGIS 開放任意 execute_code/SQL/Python/batch。
- 不刪 rejected/failed/stale scenarios、evidence、challenges 或 human decisions。
- 不把缺資料變 0，不把 model estimate 當 GIS/geometry/simulation measurement。
- 不建立 Git commit/worktree claim；此專案目前不是 Git repository。
- 不自行跨入 Week 5 正式生成，不擴大到外部模型 import、energy、thermal mass 或 CFD。

EXTERNAL / NETWORK RULES

- 允許唯讀查閱第一方官方技術文件與 package metadata。
- 安裝新 dependency 前先記錄 necessity、版本、licence、runtime boundary；避免不需要的
  大型依賴。不得用 dependency 自帶 sample output 代替本專案驗收。
- 任何新 geodata/source live request 先停在可審查 request proposal，等待人類明確授權。
- model API 只有在本機已配置且專案允許時使用；記錄 provider/model 和 bounded call
  purpose，不在 artifacts/logs 中寫 secret。
- post-dispatch connection loss = OUTCOME_UNKNOWN；先 reconcile，禁止盲目 retry。

HUMAN DECISION BOUNDARIES

你可以完成 UI、offline fixtures、typed contracts、validators、analysis code、evidence views、
request proposal 和具體 decision packet。以下必須由人類決定，不能代填：

- 解除/改變保留建築或道路；
- 啟用具體設計分母、FAR/coverage/height/floor-height 或局部分區 hard constraints；
- 批准 origin denominator、destination taxonomy、pedestrian network policy；
- 接受 morphology proposal；
- 批准 weather method 或 climate experiment；
- 採用新 formal DesignBoundary。

只有在真正到達某個決策入口且已有具體選項、觀測數量、影響與限制時，才向人類提出
一個清楚問題。不要在開始前要求籠統確認。等待時繼續所有不相依工作。

IMPLEMENTATION DISCIPLINE

- Inspect before edit；保留使用者與其他執行者已有的修改。
- 每項功能 TDD：具體 failing test → 確認失敗原因 → 最小實作 → targeted tests → integration。
- 使用 typed boundaries；backend 是權威，frontend preview 必須標示。
- immutable artifacts + SHA-256 + parent refs + append-only ledger；修正建立新 revision。
- 只在實際產物存在且 runtime/semantic checks 通過時報 PASS。
- 每完成 CP4-N，更新 checkpoint record，包含 observed state、files、tests、artifacts、hash、
  human decisions、limitations、next dependency；不要把 commentary 當證據。
- 在 60 秒以上工作期間持續給簡短進度更新；說明學到什麼、正在解什麼阻塞。

FINAL RETURN FORMAT

TASK STATUS
WEEK_4_OVERALL: PASS | PARTIAL | BLOCKED | OUTCOME_UNKNOWN

SUMMARY
VISIBLE USER FLOW
CP4-0 THROUGH CP4-8 RESULTS
FILES CREATED / MODIFIED
PUBLIC INTERFACES
FRONTEND / API / RUNTIME EVIDENCE
SPACE SYNTAX METHOD AND DATA-READINESS
AI PROVIDER AND EVIDENCE-BOUNDARY RESULTS
LIVE REQUEST ACCOUNTING
STATE / SQLITE / LEDGER CHANGES
TESTS COLLECTED AND RUN
INTEGRITY / PRESERVATION RESULTS
HUMAN DECISIONS REQUESTED OR RECORDED
WEATHER_METHOD_GATE
CORE GAPS / BLOCKERS / OUTCOME_UNKNOWN
WEEK_5 HANDOFF
INDEPENDENT REVIEW REQUEST

不要只說「完成」。附上精確檔案路徑、commands、observed outputs、artifact hashes 與
可重現操作。最終報告回交 Sol/Astra 審查；審查前不要宣布整體 project complete。
```

## 使用方式

把上方完整 code block 貼進 AntiGravity，並明確選擇 Gemini 3.8。讓它直接開啟指定 project root。若 AntiGravity 只能接一段 prompt，勿刪除 protected state、live request、human decision 或 final return sections。

本 prompt 已授權程式、前端、測試、離線 fixture、新 Week 4 revision 與必要文件修改；沒有授權新 geodata dispatch、政策批准、天氣處理、正式 climate experiment 或 Week 5 生成。
