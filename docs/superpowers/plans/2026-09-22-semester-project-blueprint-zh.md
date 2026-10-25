# 學期 Week 1–9 都市設計平台整體實作藍圖

> **2026-09-25 修訂（以此為準，下方原文保留）：** 依 [計畫層級決定紀錄](../../decisions/2026-09-25-plan-decisions-zh.md) 與 [Control Tower 修正計畫](2026-09-25-control-tower-correction-plan-zh.md)，以下條款被取代：
> 1. 第 2 節「本项目未建立 Git 工作流」：專案自 2026-09-25 起使用 Git，規則見修正計畫第 0 節。
> 2. Syntax 引擎：PST 3.3.1（pstalgo）作為參考與效能引擎，W5 第 2 天前完成比對（PD-01）。
> 3. 區域路網：單一 Geofabrik 南荷蘭省 OSM 檔，先 2 km 再 10 km，單次計算不超過 2 小時；三尺度六圖層仍全部必做（PD-02）。
> 4. 人類決策：W5 第 1 天（平台上：設計範圍、保留、分區）與 W5 第 3 天（聊天室：強度數值）兩次，經 C2 人類確認機制寫成 HumanDecision（PD-03）。
> 5. 分析結果必須以 ToolExecution／Artifact／EvidenceResult 存入權威 DB；執行者獲授權追加分析紀錄（PD-04）。
> 6. 停損：同一 gate 連續 2 個 revision 或 1 個工作天無功能進展即停止上報（PD-05）；證據包三級制（PD-06）。
> 7. E3／E4／E5 可行性檢核移到 W7 核心整合之後（PD-07）。
> 8. 天氣：推導方法＋正負 1 小時敏感度測試，W5 結束前由設計者批准（PD-08）。
> 9. 新增需求 R26-15 測量工具與即時比例尺（修正計畫 C7）。
> 10. Week 4 計畫的 P1.1／P1.2／P5 依上列 2、3、5、7 項調整；W4 未完成項依 PD-05 成為 W5 延續項。
> 11. `08` 修訂契約與 Week 4 計畫被多個歷史證據包記錄為 parent，為避免 lineage drift，修訂不寫進那兩份檔案，以本段與決定紀錄為準。
> 12. 根目錄 `README.md` 的 Authoritative Documents 清單也被歷史證據包記錄為 parent，故不直接改寫；`08_WORKFLOW_REALIGNMENT_2026-09-22.md` 的修訂效力仍依本藍圖與決定紀錄所載的採納條款。
> W5 執行入口改為 [Week 5 執行計畫](2026-09-25-week5-execution-plan-zh.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本文件目前只做規劃；取得執行指示後，逐週執行並獨立覆核，不自行跨越人類決策入口。

**Goal:** 在學期 Week 8 完成可操作、可出圖、可追溯的 Understand → Explore → Test → Refine 核心流程；Week 9 收尾與報告。

**Architecture:** 平台透過按鈕接收 QGIS 快照，以後端版本化狀態連接基地分析、AI 解釋、3–5 方案生成、幾何編輯及分級環境分析。工具負責計算，驗證器檢查，人類批准設計；前端預覽不替代後端正式結果。

**Tech Stack:** 現有 Python 3.11+、Pydantic、FastAPI、SQLite、pyproj、Shapely、pytest、受限 QGIS MCP；規劃新增 React／TypeScript 地圖與 3D 前端、受測的 angular Space Syntax 引擎、幾何生成／編輯適配器、Ladybug 與 Honeybee-Radiance。新依賴須記錄版本、授權與實際 runtime 證據。

---

## 0. 如何使用這份計畫

補充閱讀：[GrillMe 訪談紀錄](../../interviews/2026-09-22-grillme-workflow-interview-v1.md) 保存需求決策脈絡；[Week 5–9 技術細節大綱](../../technical/2026-09-22/README.md) 解釋各週的技術問題、依賴與檢核觀察，不是另一套排程。

本文件採納 [2026-09-22 工作流程契約](../../08_WORKFLOW_REALIGNMENT_2026-09-22.md)。這是學期排程，不是從現在再開八週。W1–W3 是基礎能力與已完成工作的對照框架；不虛構它們在某日實際完成，也不把過去工作重新列為全新待辦。

**已改動的排程：W4＝平台接入＋基地分析；W5＝多方案生成＋基礎編輯；W6＝完整編輯＋環境分析；W7＝串接驗收；W8＝核心凍結與報告；W9＝修復與附加。**

本計畫不觸發 live request、政策批准、幾何修改或程式實作。另個執行環境使用 [Week 4 詳細計畫](2026-09-22-week4-platform-site-analysis-zh.md) 起步。每週檢核要看實際成果，不能用文件完成替代產品完成。

## 1. 關鍵路徑與平行工作

```text
既有基礎／資料保存 ── W4 同步＋保留圖層＋分析 ── W5 策略生成＋基本編輯
                           │                         │
                      真實 AI 解釋              W6 分面／吸附＋E1
                           │                         │
W4 天氣方法處理 ── 方法批准＋資料驗證 ─────────────── W6 E2
                                                     │
                          W7 全流程與獨立驗收 ── W8 凍結／出圖／報告
                                                     │
                                           W9 修復／有條件附加
```

資料授權、Syntax 真實 runtime 與幾何編輯可行性是 W4 的早期風險檢核。W4 不能只花在檔案整理；每個工作日應有可點選或可計算的可見成果。不同工作線可以平行，但必須有人整合與驗收。若只有單人執行，這是高強度目標排程，不是已證明能達成的工期承諾。

## 2. 檔案與子系統責任

以下「新增」均是計畫中的位置，2026-09-22 尚不宣稱存在。若執行時已有人新增，先核對契約再沿用，不建立重複模組。

| 子系統 | 沿用／修改 | 預定新增 | 檢核入口 |
|---|---|---|---|
| typed 狀態與版本 | `src/urban_design/models.py`, `store.py`, `gates.py` | `workspace_contracts.py`, `workspace_service.py`（同一 package 下） | `tests/test_workspace_sync.py` |
| QGIS 同步 | `bridge.py`, `qgis_facade.py` | `src/urban_design/api.py` | `tests/test_workspace_api.py` |
| 平台 | 無已確認前端 | `web/package.json`, `web/src/App.tsx`, `web/src/features/workspace/`, `web/src/features/evidence/` | `web/e2e/workspace.spec.ts` |
| 基地證據 | `m2a03_sources.py`, `analysis_inputs.py`, `spatial_input_policy.py` | `src/urban_design/site_analysis.py`, `context_network.py`, `space_syntax.py` | `tests/test_site_analysis.py`, `test_context_network.py`, `test_space_syntax.py` |
| 設計訴求與 AI | `reasoning.py`, `models.py` | `src/urban_design/design_brief.py`, `site_critic.py`, `model_provider.py` | `tests/test_design_brief.py`, `test_site_critic.py` |
| 生成 | `models.py`, `store.py` | `src/urban_design/morphology/{contracts,strategies,streets,parcels,massing,validation}.py` | `tests/test_morphology.py` |
| 編輯 | `geometry.py`, `gates.py` | `src/urban_design/editing/{commands,floors,faces,roads,validation}.py`, `web/src/features/editor/` | `tests/test_editing.py`, `web/e2e/editor.spec.ts` |
| 環境 | 既有 smoke 證據與 ExperimentPlan | `src/urban_design/environment/{contracts,sunlight,radiation,comparison}.py` | `tests/test_environment.py` |
| 出圖 | 既有 Artifact 模型 | `web/src/features/figures/`, `src/urban_design/figure_export.py` | `tests/test_figure_export.py`, `web/e2e/figures.spec.ts` |

保留 `models.py`／`store.py` 作共同狀態核心，新子模組只能透過既有交易／ledger 模式更新。影響同一檔案的工作不要同時交給兩個執行者。所有路徑相對 project root；本项目未建立 Git 工作流，不要求虛構 commit，改用 revision、manifest 與修改清單。

## 3. 共通執行與驗收方式

每個功能拆成：先寫具體失敗測試 → 收集並確認預期失敗 → 最小實作 → 測試通过 → 接上 UI／runtime → 獨立檢核。單一步驟只做一件事，禁止把整週包成一次不可回復修改。

既有 backend 測試命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider
```

前端建立時必須定義 `test`、`test:e2e`、`build` scripts，並提交 lockfile；之後才能使用下列規劃命令，現在執行會因前端未建立而失敗：

```bash
npm --prefix web run test -- --run
npm --prefix web run test:e2e
npm --prefix web run build
```

採用分離狀態：`archival_integrity`、`current_authority_state`、`functional_acceptance`。合法的新 ledger 事件不破壞歷史封存；真正來源 mutation 必須阻擋。所有實際狀態／測試數現查，不能從這份計畫抄答案。

每週輸出一份不可覆寫的 acceptance record，包含 CP、需求 ID、輸入輸出 hash、實際 collected test nodes、runtime 結果、人類決策、限制、下一階段授權範圍。失敗只阻擋依賴項；不能讓獨立工作全停，也不能略過依賴繼續正式分析。

## 4. Week 1 — 基礎契約對照（歷史工作，不重新排程）

**目的：** 檢查現有基礎能支撐新版產品。

- [ ] W1-A：核對 typed model round-trip、CRS／單位／geometry validation，保存實際失敗狀態。
- [ ] W1-B：核對 SQLite append-only ledger、版本與重播；刪除與 override 不覆寫舊結果。
- [ ] W1-C：核對模型 adapter 與受限 QGIS facade；任意 Python、SQL、batch bypass 仍禁止。
- [ ] W1-D：檢查現有 QGIS、Ladybug、Honeybee smoke 報告；歷史 PASS 不是目前 runtime 自動 PASS。

**CP-W1：** 能指到實際程式、測試與證據。已通過部分沿用；有 drift 的部分在 W4-A 列為特定修復，不重做全部。

## 5. Week 2 — StudyArea 與來源基礎對照

- [ ] W2-A：辨認 active StudyArea、確認與啟用事件；拒絕只讀聊天宣稱。
- [ ] W2-B：辨認 frozen spatial-r01、來源 receipts、hash 與可用觀測。
- [ ] W2-C：區分已封存來源、未選政策、已批准政策；來源包 PASS 不等於 spatial acceptance。
- [ ] W2-D：核對 weather unresolved 與 r03 preservation；不重跑下載或改 Minute。

**CP-W2：** 得到當前狀態表。若 addendum 與目前驗證程式不相容，用後續 append-only 修復記錄，不改舊包。現有狹窄 envelope 未證明可用於三尺度 Syntax。

## 6. Week 3 — 整合準備對照與未完成項歸位

- [ ] W3-A：清點現有 UI、API、地圖、graph、AI provider 與 climate runtime；區分實作、mock、只有文件。
- [ ] W3-B：把缺口移入 W4 的具體任務，不因學期已到 W4 就把缺功能標成完成。
- [ ] W3-C：建立 R26-01–14 驗收表；核對新訴求與舊限制的衝突類別。

**CP-W3：** 形成真實起點與可執行 backlog。W1–3 不作新增三週工期，也不聲稱歷史所有檢核已通過。

## 7. Week 4 — 平台接入＋基地分析（合併原先兩週）

**使用者本週應能完成：** QGIS 按同步 → 平台選建築／道路與畫分區 → 看基地分析及六張 Syntax 圖 → AI 解釋 → 保存並出第一張圖。

| Phase | 實作成果 | 自我檢核與停止條件 |
|---|---|---|
| W4-A | 現況基線、需求凍結、Syntax／幾何／環境工具最小試算 | 試算失敗寫明具體缺口；不得用 mock 代替真實方法 |
| W4-B | 前端骨架、按鈕同步、可點選 map／3D、版本恢復 | 新同步不覆蓋草稿；舊 job 不覆蓋新版本 |
| W4-C | 保留／可改／未決圖層、局部分區備註、約束預覽 | 保留項目鎖定；新硬限制等人類確認 |
| W4-D | 建築／用途／道路／水體／開放空間指標與證據 | 缺資料顯示 unavailable，不能當零；探索範圍不冒充地籍 |
| W4-E | 三半徑 integration／choice、共同網路、六圖層 | 參考網路校驗＋邊界敏感性；引擎不支援則本 gate BLOCKED |
| W4-F | 真實 AI 讀有效 Evidence Cards、解釋基地與設計潛能 | 假 evidence ID、錯單位、無依據數值全部拒絕 |
| W4-G | 完整操作 demo、初步出圖、下一週生成輸入 | 能重開工作區重現；獨立 reviewer 逐項檢查 |

建議五個工作日順序：D1 A＋B；D2 B＋C；D3 D＋Syntax runtime；D4 E＋F；D5 G＋修復。這是工作分配，不是每項只需一天的保證。Syntax 範圍、天氣來源方法與 editor 幾何試驗在 D1 啟動，不能拖到 W6 才發現不可用。

**CP-W4：** R26-01/03/05/06 的本週成果有真實 UI 和計算；R26-02/04/13/14 有可操作基礎。若 Syntax 未通過，仍可開發生成 fixture，但不得對外聲稱完成基地分析或用虛構 Syntax 驅動正式方案。

本週詳情、TDD 目標與完整 prompt 見 [Week 4 計畫](2026-09-22-week4-platform-site-analysis-zh.md)。

## 8. Week 5 — 多方案生成＋基礎編輯

**使用者本週應能完成：** 輸入空間策略與上限 → 看三至五個方案 → 比較利弊 → 選 B → 拖曳量體與道路 → 看儀表板变化。

### W5-A：結構化 brief 與約束

**Files:** 新增 `src/urban_design/design_brief.py`、`tests/test_design_brief.py`；修改 `models.py`／`store.py` 的 typed references；前端 `web/src/features/brief/`。

- [ ] 寫測試：相互重疊分區不能不經分配就雙重計算；未批准的硬限制不能啟用；缺樓層不能填零。
- [ ] 實作整體／分區 FAR、建蔽率、高度與用途限制；保留建築計入總量。
- [ ] UI 呈現自然語言解析結果與來源，設計者確認作用範圍及上限。

**CP5-A：** brief 從 SQLite 重播一致。不得把「上限」變成自動填滿目標。

### W5-B：街道、街廓與策略生成

**Files:** 新增 `src/urban_design/morphology/` 表列模組、`tests/test_morphology.py`；前端 `web/src/features/scenarios/`。

- [ ] 寫 fixture：固定 boundary、保留建築／道路、相同 brief、seed，期待三個不同策略且各自重跑 hash 一致。
- [ ] 先產生主次道路連接與開放空間，再街廓／量體／用途，保存策略、參數、seed、來源與父方案。
- [ ] 驗證所有方案保留物不移動、道路真接通、geometry 有效、區域上限不超標；記錄無解與拒絕候選。
- [ ] 若只能產生兩個有效策略，報告 2/3 未達標，不複製量體換顏色湊數。
- [ ] 提供可選先例檢索，保存圖片來源與使用限制；先例不能改寫硬限制。

**CP5-B：** 至少三個有效且不同的空間策略，同一訴求下差異能以道路、開放空間、街廓與量體配置說清楚。

### W5-C：評估與人類選擇

- [ ] 用同一來源與規則比較 FAR、coverage、用途、道路／開放空間、可用 accessibility／Syntax 結果。
- [ ] AI 只描述經驗證的差異與限制，不給無規則的總排名。
- [ ] 使用者明確選 B 後記錄 HumanDecision；拒絕 A/C 也保存。

**CP5-C：** 相同對象、單位、尺度的比較成立；選擇不是模型代替人類做出。

### W5-D：基本編輯與儀表板

**Files:** 新增 `src/urban_design/editing/commands.py`、`floors.py`、`validation.py`、`tests/test_editing.py`、`web/src/features/editor/`。

- [ ] 先驗證 floor counting 與 1 m relative step，再做移動／旋轉／頂面逐層／側面推拉。
- [ ] 顯示全局層高規則；不提供自由垂直拉伸。
- [ ] 前端預覽和後端確認值分開；違規草稿標紅，可保存、undo／redo，正式接受被阻擋。
- [ ] 自然語言編輯先顯示命令作用對象與 diff，採用相同命令與驗證途徑。

**具體測試例（新 fixture，非真實基地值）：** 設計面積 1,000 m²，10×20 m、3 層，GFA=600 m²、FAR=0.6；首層 4 m、標準層 3 m，高度=10 m。增加一層後 GFA=800 m²、FAR=0.8、高度=13 m。若上限 0.7，草稿保留但不得接受。這些數值是測試資料，不是已批准的設計限制。

**CP5-D：** 量體每次操作的幾何與數值一致；沒有「只改視覺模型、資料不變」。

### W5-E：道路節點與幾何可行性

- [ ] `editing/roads.py` 實作節點拖曳、端點／最近點吸附、保留路鎖定。
- [ ] 以地面交叉與跨橋 fixture 驗證：前者接通，後者不誤連。
- [ ] `editing/faces.py` 在簡單量體完成分面與局部推拉試驗，提早暴露拓撲風險。

**CP-W5：** 三個可重現方案＋選擇＋基本編輯 demo 通過；進階分面與完整吸附是 W6 必做，不會因 W5 未完成而被默默移除。

## 9. Week 6 — 完整編輯＋環境分析

### W6-A：分面與局部推拉

**Files:** `editing/faces.py`、`floors.py`、`validation.py`、`tests/test_editing.py`、`web/e2e/editor.spec.ts`。

- [ ] 測試平面畫線與封閉輪廓切分、局部推拉、退台；切分而不推拉時 GFA 不變。
- [ ] 計算每層實際 footprint，不用總 bounding box × 層數估算。
- [ ] 拒絕自交／非流形結果，保存可復原草稿；不允許操作修改保留物。

**CP6-A：** 使用者實際畫輪廓、拉側面後，拓撲有效，儀表板與獨立面積計算吻合。

### W6-B：完整道路吸附與分析失效處理

- [ ] 實作中點、交點、垂直點、沿线四分點；近似點不替代精確接通。
- [ ] 道路修訂使舊 graph／Syntax／accessibility stale；只有高度改變，graph hash 與 accessibility 不變。
- [ ] 舊分析 job 回傳不得覆蓋新方案；依輸入 hash 判斷而非只看完成時間。

**CP6-B：** 高度負面控制、道路正面控制與延遲回應控制通過。

### W6-C：E1 日照與陰影

**Files:** `environment/contracts.py`、`sunlight.py`、`tests/test_environment.py`。

- [ ] 凍結方案 geometry、地理位置、時區、日期／時段、步長、遮蔽物、sensor grid。
- [ ] 平面無遮擋、已知遮擋、夜間、時區 fixture 先通過，再接真實量體。
- [ ] 顯示時段與單位；不能把某天日照時數當全年表現。

**CP6-C：** 可比較修改前後的日照／陰影，並保存圖層與 Evidence Cards。

### W6-D：E2 輻射雙層分析

**Files:** `environment/radiation.py`、`comparison.py`、`tests/test_environment.py`。

- [ ] 先檢查天氣方法與實驗批准；缺失時 BLOCKED，不因趕排程調鬆 EPW validator。
- [ ] 固定對照情境、時段、材料、感測網格與排除面；分別執行 Ladybug 與 Honeybee-Radiance。
- [ ] 記錄各方法的面積加權累積入射輻射與空間分布，解釋方向一致或不一致；不得混算絕對值。
- [ ] 未改善或失敗結果仍保存。輻射結果不冒充熱舒適、耗能或材料蓄熱。

**CP-W6：** 分面／吸附與 E1 通過；E2 至少完成真實端到端路徑或明確列出阻塞。W7 是 E2 核心驗收期限，不能把 unresolved 說成完成。

## 10. Week 7 — 四階段完整串接與獨立驗收

### W7-A：從同步到修改後分析的完整 walkthrough

- [ ] 全新工作區載入 frozen sources，選保留物、畫分區、讀基地與六張 Syntax 圖。
- [ ] brief → 三方案 → 比較 → 人類選 B → 編輯 → E1/E2 → 再比較。
- [ ] 每張結果卡可展開來源、公式、單位、版本與限制。AI 語句連結相應卡片。

### W7-B：可質疑與復原

- [ ] 逐一操作 Inspect、Challenge、Modify、Rerun、Compare、Fork、Reject、Override，確認不是只有按鈕。
- [ ] accessibility 400/800/1200 m 的舊敏感性案例仍分別保存；與 Syntax 的 800/2,000/10,000 m 不混用。
- [ ] 注入錯來源、無效 geometry、未批准政策、失敗模型、失敗 simulation、重複 dispatch、OUTCOME_UNKNOWN。
- [ ] 中斷後重新啟動，以 persisted state 重現，不依賴聊天或開著的 QGIS 畫面。

### W7-C：出圖與附加環境功能入口

- [ ] 接好一致視角的方案比較、平面／透視／等角及分析圖輸出。
- [ ] 核心通過後才排 E3 建築耗能，接著 E4 蓄熱；用独立假設與 benchmark，不綁架核心整合。
- [ ] 若 E3/E4 試算未可驗證，保持 NOT_ACCEPTED，保留 W8 核心修復時間。

**CP-W7：** 獨立 reviewer 能完整操作四階段；R26-01–12 全部核心路徑通過。E2 未通過就如實報核心 incomplete；其他已完成能力仍可演示。

## 11. Week 8 — 至少 90% 目標的實際驗收與報告版

### W8-A：核心凍結

- [ ] 凍結 datasets、軟體依賴、模型／prompt 設定、方法、場景、約束、天氣與 recipes。
- [ ] 受控新環境從清單重建；需要外部 runtime 的部分保留版本與安裝證據。
- [ ] 全套 release-blocking 測試與端到端操作通過；未執行不記 PASS。

### W8-B：出圖正式驗收（R26-13）

**Files:** `web/src/features/figures/`、`figure_export.py`、兩類 figure 測試。

- [ ] 輸出基地、Syntax、量體平面、透視、等角、環境結果、方案比較的 PNG。
- [ ] 至少一次檢查實际輸出檔尺寸、圖例與文字不裁切、操控器隱藏、版本／單位／時段完整。
- [ ] 同一比較使用一致鏡頭、範圍與色階；不同範圍明示，不操縱圖像製造改善印象。
- [ ] 過期結果不能無標記進正式報告；只有日照時也不能用圖名聲稱完成全環境分析。

### W8-C：報告與 release decision

- [ ] 準備七分鐘版本：問題與流程 1 分鐘；Understand 1.5；Explore 1.5；Test/Refine 2；結果與限制 1。
- [ ] 保存可離線播放的備用 demo 與圖紙，明示錄製時的版本；影片不能取代 runtime 驗收。
- [ ] 展示限制、未完成附加項、沒有改善的假說；取得人類 release decision。

**CP-W8：** R26-01–14 核心清單逐項 PASS 才稱核心完成；產品完成率若要數值化，必須使用 W4 凍結的項目／權重且揭露分母，不憑感覺填 90%。「核心全通過、附加未全做」符合收尾意圖；「核心少了 Syntax／生成／出圖」不符合。

## 12. Week 9 — 修復、報告與有條件加值

- [ ] W9-A：先修報告阻塞與可重現問題，不做大架構改動。
- [ ] W9-B：仍有容量時，依已驗證成熟度加入 E3／E4；E5 風場最後評估。
- [ ] W9-C：附加精細交通模式、模型匯出。先驗證一種格式的 units、座標與幾何 round-trip，不承諾同時 OBJ／FBX／DWG。
- [ ] W9-D：最終報告、封存版本、備份證據與人類決定；新功能失敗不污染已凍結的 Week 8 demo。

**CP-W9：** 報告穩定、資料可讀、版本可重現；附加項分別標明完成／部分／未做。不得為附加功能犧牲核心正確性。

## 13. 每週自行檢查與交接格式

```text
SEMESTER_WEEK:
REQUIREMENTS_COVERED:
PHASE_RESULTS: CP-ID -> PASS | FAIL | BLOCKED | OUTCOME_UNKNOWN
VISIBLE_DEMO: actual steps and recorded artifact
FILES_CHANGED:
INPUT_OUTPUT_HASHES:
TESTS_COLLECTED_AND_RUN:
LIVE_REQUESTS_AND_BUDGET:
HUMAN_DECISIONS:
ARCHIVAL_INTEGRITY:
CURRENT_AUTHORITY_STATE:
WEATHER_METHOD_GATE:
CORE_GAPS:
OPTIONAL_FEATURES:
INDEPENDENT_REVIEW:
NEXT_AUTHORIZED_WORK:
```

W4 到 W8 每週至少一段可以實際操作的 demo。只交 manifest、測試總數或計畫不能代替使用者流程。若預估做不完，執行者需列出具體差額與可選調整，設計者決定；不能擅自刪掉 Space Syntax、三方案、分面、E1/E2 或出圖。
