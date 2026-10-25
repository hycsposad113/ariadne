# 基地分析 → 設計訴求 → 三模式形態生成：總執行計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax. 一次只領一個工作包；不得把整本計畫當成一次無邊界派工。

**Goal:** 讓設計者從可追溯的基地分析提出／修改設計機會，選擇骨架優先、完整方案或逐步設計，以同一生成管線得到三至五個真正不同且可修改的空間策略。

**Architecture:** 沿用 React/TypeScript、FastAPI/Pydantic、SQLite project store/ledger 與 immutable artifacts。新增 analysis→brief→skeleton→blocks/program→massing 的 typed stages；模式只控制停點。AI 提議策略與解釋，確定性程式產生／驗證幾何，設計者決定。指揮官協作日誌與設計決策 ledger 完全分離。

**Tech Stack:** 現有 Python 環境、Shapely、pyproj、Pydantic、FastAPI、SQLite、pytest、React、TypeScript、Vitest、Vite 與既有瀏覽器測試。沿用現有 PST adapter；本輪不新引進最佳化框架或更換幾何引擎。

**版本：** 2026-09-30 v1。**狀態：** PLAN_READY_FOR_ARCHITECTURE_REVIEW；需求方向已由使用者確認，工程方案／數值門檻是待審規格，不是部署或 HumanDecision。

## 0. 正式入口、權威與本輪界線

正式專案根目錄 `PROJECT=/Users/jackhsieh/Downloads/TUD/Q5/project`。
本計畫由獨立 `wp/analysis-generation-plan` worktree 保存；它不是 main 已採用的文件。
文件中的 `src/`、`web/`、`tests/`、`docs/` 均相對執行者自己的 `WP` 根目錄。
命令必須在已驗證的 WP 執行；Python 可使用 `$PROJECT/.venv/bin/python`，但 `PYTHONPATH=$WP/src`，不能誤測 main 模組。

使用者確認的四個產品決定：
- U1：現況分析＋設計機會；解釋證據、限制、潛力，不替使用者決定方向。
- U2：改善整體道路／公共空間組織、基地回應、量體高度／形狀／排列，三項都需要，不推定先後排名。
- U3：三種模式全部可選：SKELETON_FIRST、FULL_SCHEME、STEPWISE；共用資料與演算法。
- U4：自行設定訴求或從 AI 建議開始都可以；允許框選區域、文字註記、修改或拒絕。

繼承的操作要求：三至五種空間策略；保留建築／道路鎖定；整體＋可選分區上限；頂面逐層、側面相對 1m 步進；道路精確吸附優先；保存無效草稿與舊版本；比較、出圖；原始資料不被編輯覆蓋。

本次不批准任何 FAR、建蔽率、層高、道路寬度、退距、公共路權、設計邊界或氣候實驗。不把使用者同意軟體功能寫成 HumanDecision。學期 Week 8 核心、Week 9 收尾仍是目標；不因日期切換推定目前學期週次或聲稱已有 90% 完成。

## 1. 已查基線與不能遺漏的既有成果

| 項目 | 本計畫基線 | 執行者如何刷新 |
|---|---|---|
| main | 2026-09-30 檢視 HEAD e1a054f | `git rev-parse HEAD`、`git status --short`，保留 dirty 檔 |
| 選單修復 | wp/ui-sidebar-overflow；僅 App.tsx，未合併；子代理報 119 tests/build 與三種視窗 | 重新讀 diff 與可定位的 browser evidence；不能把報告當獨立接受 |
| v4 生成器／問題報告 | 已合併 main；不是全功能驗收 | 讀 dictionary_generator.py、problem_definition.py、docs/w6/problem-definition-zh.md |
| 舊預覽 | 外部 worktree run-01，10 個 A/B，UNAPPROVED_PREVIEW | 固定 manifest hash 與 52 listed files；不重生成來補 provenance |
| morphology r02 | 31 卡、10 SVG；15 synthetic tested、14 missing、2 code untested | research 目錄與 capability CSV；非已採用 runtime dictionary |
| 工作區 | 先前 rev6 DRAFT，非本計畫新鮮 DB 證據 | runtime DB `mode=ro` 列真正 heads/decisions/counts；不從舊報告複製 |
| UI/API | 上次 5195/8795，前端主 checkout；使用者有 unsaved draft | lsof owner/cwd＋GET health；不自動刷新使用者分頁 |
| Grok 研究 | 使用者手動執行，r02 已交付 | 共同 event 讀 timestamp 與 supersedes；不得重派 |

只讀成果路徑：
- `/Users/jackhsieh/Downloads/TUD/Q5/w6-dictionary-generator/out/dictionary-generator/run-01`
- `/Users/jackhsieh/.local/share/agent-coordination/q5-urban-design/research/morphology-revision-r02-20260929T202637Z`
- `/private/tmp/q5-preview-integration-packet.md`（參考，不可當永久唯一交接）

## 2. 必讀與衝突處理

AGENTS.md、README、CLAUDE-commander.md、docs/00、01、02、03、05、06、07，及 docs/08_WORKFLOW_REALIGNMENT_2026-09-22.md、docs/decisions/2026-09-25-plan-decisions-zh.md。
閱讀相關段落而非只憑 grep 命中。版本修訂優先於明確被取代的歷史規格；舊 gate 仍保留證據意義。

ARCH-01：文件保留 COMPAS two-family 敘述，現有生成路徑是 Shapely；本計畫建議把現有 Shapely 封裝成版本化 adapter 做增量修正，不重新建一條 COMPAS 管線。此為 implementation constraint／架構對齊項；Claude 審查後才能更改 authoritative architecture，不得稱歷史 COMPAS gate 已通過。
ARCH-02：近期使用者指定 Claude 與 Codex 都能協調工作；現有 AGENTS 仍要求 Claude review＋Founder approval 才可 merge main。雙指揮官共享派工／查核，並不自動取消合併規則。
ARCH-03：新的三模式是 R26-07 的操作展開，不是三套 generator；不新增未經授權的自動最佳方案決策。
ARCH-04：所有參數分為 human hard constraint、human preference、method parameter、illustrative fixture；來源不能相互冒充。

## 3. 工作包與依賴（五份子計畫）

| WP | 子計畫 | 交付／checkpoint | 依賴 |
|---|---|---|---|
| C0 | 2026-09-30-commander-coordination-zh.md | 共同事件、工作所有權與正確狀態，CP-C0..C3 | 首先做最小協定；不能先等完整 dashboard |
| P1 | 2026-09-30-preview-and-ui-zh.md | 選單修復審查、10 預覽唯讀可見，CP-P0..P3 | C0；不等新 generator |
| A2 | 2026-09-30-analysis-and-brief-zh.md | analysis bundle、opportunity、地圖訴求，CP-A0..A4 | C0；可與 P1 核心 adapter 並行 |
| G3 | 2026-09-30-generation-core-zh.md | skeleton／block／massing／可比較差異，CP-G0..G6 | A2 frozen contracts；純幾何 fixture 可提前 |
| U4 | 2026-09-30-three-mode-workflow-zh.md | 三模式、版本／重算、端到端與出圖，CP-U0..U5 | G3 stages＋A2；前端 fixture 可提前 |

串接順序：C0 → P1（先讓使用者看現有成果）；A2 contracts → G3 stages → U4 UI。U1 的通用 durable-job 基礎在 A1/G0 contracts 凍結後提前實作；A3 的 analysis-jobs 與 U3 UI 都依賴它。job core 不依賴完整 generator，透過 registered stage handler 接入，避免 A2↔U4 循環依賴。
單一檔案所有權：api.py / models.py / store.py 由 designated integration worker 修改；其他 workers 提供 adapter 或 patch proposal，不同時編輯這些檔。App.tsx 先處理已完成 sidebar 修復，再由 U4 接入，禁止相互整檔覆寫。

## 4. 共同資料流與狀態

```text
Frozen datasets + persisted WorkspaceRevision
   → SiteAnalysisBundle → OpportunitySet
   → DesignBriefRevision (self-authored or edited AI proposal)
   → SkeletonArtifact → BlockProgramArtifact → MassingArtifact
   → ValidationReport + ComparisonBundle
   → PROPOSED scenario → explicit human acceptance (separate action)
```

- analysis 的有效／缺失、工程 gate、研究採用、方案接受，是四種不同狀態欄，禁止單一 PASS 代替全部。
- stages：PENDING / RUNNING / READY / FAILED / BLOCKED / STALE / OUTCOME_UNKNOWN。
- viewing previews 不建立 Scenario；生成 run 的草稿不得因自動模式自動 ACCEPTED。
- 影像檔存在不能代表幾何已驗證；JSON合法不能代表 evidence refs 對應正確。
- 生成可在 UNAPPROVED_PREVIEW 模式使用明示假設；若要建立依批准條件的正式 proposal，必須由伺服器核對 effective ConstraintSet。
- stage lock 是「沿用本次選取的設計版本」，不是法律保留、人類正式批准或不可修改的永久狀態。

## 5. 全局執行規則與標準命令

每個 task 採可追蹤 TDD：
- [ ] 建立該任務列出的具體反例／known-answer fixture。
- [ ] 先跑指定 test node，確認因待實作行為 FAIL。新增 module/symbol 尚不存在的 ImportError 可記為初次 RED；先建立最小 interface 後須看到 assertion RED。依賴缺失／錯 Python／測 main 等環境錯誤不能當行為 RED。
- [ ] 實作當前最小 scope；不順手重構整個 api.py 或 generator。
- [ ] 跑 focused tests、affected regressions、git diff --check。
- [ ] own wp/* branch 可提交具名檔案；不 `git add .`，不 push、不 merge main。
- [ ] 更新 task evidence 與共同 log；跨 provider review。只有 main 整合候選才跑完整 Python suite／前端 suite，純文件不跑。

```bash
# 執行者在已核對的 WP 根目錄，PROJECT 是正式 checkout 的絕對路徑
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PROJECT/.venv/bin/python" -m pytest -q -p no:cacheprovider tests/test_preview_catalog.py
# web 任務由 WP/web 執行：
npm test -- --run
npm run build
# 整合候選由 WP 執行：
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PROJECT/.venv/bin/python" -m pytest -q -p no:cacheprovider
```
所有新測試檔與函式名稱都是計畫介面，執行者須先建立再執行；測試數量以 collected output 為準，不承諾沿用 914 或 119。
不新增 live source/model requests 作一般測試。模型輸出 schema 有 fixture route，但 fixture 成功不能替代真實 provider 對話驗收；該真實驗收沿用現行授權與 PD12 預算，未核實則 UNKNOWN，不重新索取已有效授權。

## 6. 完成定義與品質驗收

工程品質：保留鎖、CRS/units、拓撲、參數與資料來源、版本／重播、fail-closed 全部通過。
空間品質：道路／公共空間骨架與量體形態的多樣性可解釋；用相同基地/constraints 比較，不用渲染顏色或不同密度掩飾沒有策略差異。
設計品質：使用者能說明哪個方案回應哪些問題、改動什麼；「喜歡」由設計者決定，不由 validator 宣布。

Release gate 必須包括：
- 至少三種不同策略，或明確報不足三種與失敗原因；不能重複圖湊數。
- 三模式在同輸入、seed、相同中間選擇時，stage artifacts 完全相同（timestamps另存 metadata）。
- 每個機會／方案理由能打開來源圖層或 EvidenceCard；缺比較值不能自動宣稱問題／改善。
- 保留建築與道路內容不被生成／編輯改掉；未決要素也不可默認移除。
- FAR 包括保留建築；缺樓層時 known-part 與完整可驗證性分開，不能把「known-part沒超」當作 full cap PASS。
- 使用者自設／AI建議兩種 brief，與三種模式，六組路徑均可實際走通。
- 取消、重啟、同時提交、過期回覆、變更StudyArea、缺檔／hash drift 均有明確結果。
- comparison/export 有同視角／圖例／版本／假設；沒有合法性、通行權、氣候改善的越界主張。

## 7. Commander 一次派一包的 prompt

```text
你是 bounded executor。使用指定模型；不要自行切換或遞迴派工。
閱讀總計畫及被指派的子計畫。這次只做 task_ids 指定的 task。
先核對 canonical project、當前分支、共同 log 與工作所有權。
objective: 完成 task_ids 的可驗證交付。
scope: 指定 wp/* worktree；所有 main、來源 artifacts、正式 DB 只讀。
relevant_files: 逐項使用該 task Files 清單。
allowed_changes: 清單所列新檔／狹義修改與測試。
forbidden_changes: merge/push/reset/clean、正式決策、來源下載、模型外呼、服務重啟、未指派檔案。
acceptance_criteria: 該 task 的 CP；不以測試總數替代。
tests: 執行計畫指定的節點，保存實際 log；環境錯誤不得算功能 FAIL/PASS。
expected_return: 檔案差異、code SHA、輸入hash、指令／實測、限制、review必要項、下一個安全步驟。
完成請追加 shared handoff event，不宣稱 deployed。若中斷，寫阻礙及 output 位置，不重送 OUTCOME_UNKNOWN 操作。
```
Commander 發送時必須把 task_ids、worktree、模型、允許檔案與測試展開成具體值，不能只把整本計畫丟給 worker。

## 8. 計畫自身檢核與採用界線

- [ ] U1–U4 需求全部映射到 A2/G3/U4，不丟掉任一模式。
- [ ] 歷史修復與十個預覽分開報，不重新批准／重做。
- [ ] 全部 code symbols 在子計畫定義為既有或 planned；不假稱已存在。
- [ ] 每個 task 有輸入、輸出、失敗條件、反例、CP與 owner。
- [ ] 兩位指揮官都能從共享入口找到同 hash 計畫及最新事件。
- [ ] Architecture review、implementation completion、main merge、runtime activation、human acceptance 各自記錄。
- [ ] 本輪只寫文件；上述 execution checkboxes 留空，不能宣稱已执行。

## 9. Checkpoint → 測試與需求對照

| Task / checkpoint | 主要具體測試節點（待建立，列名就是交付契約） | 使用者需求 |
|---|---|---|
| C0–C3 | test_claim_rejects_overlapping_scope、test_event_order_uses_recorded_time、test_merge_is_not_activation | 兩位指揮官共同知情 |
| P0 | disposable browser tabs-within-sidebar at 1280/1440/1920 | 修正選單溢出 |
| P1 | test_catalog_rejects_manifest_drift、test_asset_rejects_symlink_escape | 既有成果可見且可信 |
| P2 | test_preview_gets_do_not_write_store、test_disabled_catalog_is_explicit | 不冒充正式方案 |
| P3 | groups A and B、shows unknown retained floors、never posts preview approval | 真實10個預覽 |
| A0–A1 | test_missing_observation_is_not_zero、test_evidence_scope_hash_mismatch | 基地分析與限制 |
| A2 | test_claim_rejects_wrong_metric_reference、test_model_failure_keeps_manual_brief_available | AI機會有依據 |
| A3 | test_stale_workspace_rejects_brief_without_write、test_ai_intent_does_not_approve_constraint | 自設／AI修改訴求 |
| A4 | test_waterfront_intent_preserves_scope_refs | 分析影響設計 |
| G0 | test_stage_hash_excludes_mode_and_timestamps | 同一生成管線 |
| G1 | test_h_profile_is_not_one_sided_comb、test_unknown_profile_is_explicit_error | 型態正確性 |
| G2 | test_skeleton_preserves_locked_features、test_different_levels_do_not_connect | 基地與道路回應 |
| G3 | test_land_partition_conserves_area、test_zone_overlap_requires_policy | 空間組織／不漏南側 |
| G4 | test_retained_unknown_blocks_full_far_verification、test_floor_step_updates_actual_gfa | 高度與強度 |
| G5 | test_renamed_geometry_is_not_diverse、test_no_hidden_winner | 真正不同的方案 |
| G6 | test_frozen_site_preview_preserves_inputs | M4H實檔整合 |
| U0 | test_three_modes_match_given_identical_selections | 三模式全部提供 |
| U1 | test_duplicate_dispatch_claims_once、test_reconcile_after_publish_before_db_commit | 不重複生成 |
| U2 | test_height_change_preserves_road_hash、test_stale_result_cannot_replace_head | 編輯與重算 |
| U3–U4 | mode switch retains selection、late response ignored、export retains preview label | 可介入／可比較／出圖 |
| U5 | 六條manual/AI × mode的browser flow | 完整使用流程 |

表內測試列為計畫中的精確行為，不是已collected或已通過的證據。使用 `pytest --collect-only -q <檔案>` 核對後再回報。

## 10. 階段性交付與縮範圍規則

- Release R1：P1讓現有成果可看；獨立於新generator。遇來源漂移就顯示失效，不轉成空清單。
- Release R2：A2分析／訴求＋G3 skeleton；可讓設計者試骨架，不宣稱完整量體生成已完成。
- Release R3：G3全管線＋U4三模式／重算／比較；正式驗收用相同輸入的完整流程。
- 不夠時間時先限制「已驗證型態數」、局部優化次數與附加環境模擬；不能剪掉三種mode、來源缺值揭露、保留鎖、可取消／重播、真實策略差異。
- 先做一個綜合fixture＋一個M4H案例；不為了通用性同時擴十個城市。
- 尚未觀察真實耗時，不寫死幾天必完成。每task完成記wall time與資源，再由commander更新remaining estimate；不使用模型自報百分比當進度。

## 11. 已核對的工具命令（須按實際任務展開）

Luna executor CLI：`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex exec -m gpt-6-luna -c model_reasoning_effort=max -s workspace-write -C <owned-wp> <bounded-prompt>`。
這裡的尖括號是命令參數說明，不可原樣執行；實際任務使用structured subprocess argv與prompt-file reader，不用危險shell字串插值。
原生subagent：明確requested model=`gpt-6-luna`、reasoning_effort=`max`；記returned agent ID，不以新app thread冒充subagent。
AGY：精確model `gemini-3.8-flash-high`，`--sandbox --mode accept-edits`；若headless拒權限，回報而非自動使用dangerously-skip-permissions。審查可把已授權diff／檔案全文附在prompt，聲明材料範圍。
Grok研究由使用者已手動派出的任務負責；這份計畫不再發起相同文獻任務。

## 12. 文件入口

- [A2：基地分析、設計機會與設計訴求 Implementation Plan](2026-09-30-analysis-and-brief-zh.md)
- [C0：Claude／Codex 共同派工與交接 Implementation Plan](2026-09-30-commander-coordination-zh.md)
- [G3：基地回應、道路骨架與量體生成 Implementation Plan](2026-09-30-generation-core-zh.md)
- [P1：既有方案唯讀預覽與選單修復 Implementation Plan](2026-09-30-preview-and-ui-zh.md)
- [U4：三模式操作、版本重算與整合 Implementation Plan](2026-09-30-three-mode-workflow-zh.md)
