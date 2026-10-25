# W7 稽核缺口補齊報告

日期：2026-10-15  
工作目錄／分支：`/Users/jackhsieh/Downloads/TUD/Q5/w7-fixes`／`wp/w7-fixes`

## 結果摘要

已補上有效 D1／StudyArea 綁定下的 Modify 正向路徑、E1／E2 修改後重跑、幾何與計算故障注入、離線模型傳輸失敗、W7 Override 正式人類決策入口，以及隔離狀態庫和 job store 重開還原測試。OUTCOME_UNKNOWN 不自動重送。

整段 walkthrough 使用隔離 `ProjectStateStore`、凍結測試來源、六項 Syntax 狀態和四個正式形狀的測試方案紀錄。方案幾何與指標是測試程式以明確幾何輸入計算的 fixture，不是正式場址生成結果。瀏覽器腳本已寫好但依要求未執行。E1 reconciliation 會比對 handler-entry receipt、job events、已持久化執行及 artifact bundle hash；E1 沒有暴露可核對的子程序識別，因此仍標記 `UNRESOLVED`／`NOT_RECORDED`，並禁止自動重送。

## 稽核清單 1–9

| 項目 | 結果 | 新增或擴充測試與驗證 |
|---|---|---|
| 1. W7-A 整段 walkthrough | **PARTIAL，測試通過** | `test_week7_real_walkthrough_sync_four_proposals_modify_e1_e2_and_restart`：隔離資料下同步來源、保存／可編輯處置、分區 brief、六項 Syntax（2 項計算、4 項因覆蓋受阻而未計算）、四案比較、人類選案、Modify、E1／E2、再比較、重開資料庫與雜湊核對。四案為測試 fixture，尚未從正式生成工作流程產生；再比較誠實回報 `NOT_COMPARABLE`，沒有產生優勝者。 |
| 2. Modify 成功草稿及有效 D1 綁定 | **PASS** | `test_modify_opens_w6_formal_draft_after_accepted_baseline_and_workspace`：有效 StudyArea／已接受 workspace 建立 W6 `FORMAL_DRAFT`；核對 parent revision、原幾何 hash、原方案及 HumanDecision 集合不變。先以錯誤 StudyArea 綁定驗證 HTTP 409。`test_modify_closed_without_acceptance_and_live_transport_denied` 保留未接受基準的 409。未修改或放寬 `formal_authority.py` 的既有權限驗證。 |
| 3. 修改後 E1／E2 Rerun 與 lineage | **PASS** | `test_e1_approved_w7_rerun_publishes_current_draft_lineage_once`、`test_w7_e2_success_invalid_geometry_failure_unknown_and_restart`、整段 walkthrough：已核准且綁定方案版本的計畫可執行；核對 ToolExecution、EvidenceCard、idempotency 及 draft lineage。E1 未核准計畫、錯誤 lineage、錯誤 hash 的拒絕測試仍保留。草稿證據維持 `unverified`。 |
| 4. E1 `OUTCOME_UNKNOWN` | **PASS，程序觀測受限** | `test_e1_calculation_failure_is_failed_and_outcome_unknown_survives_restart`、`test_e1_approved_w7_rerun_publishes_current_draft_lineage_once`：失聯保留 `OUTCOME_UNKNOWN`；重開後同一 idempotency key 回到同一 job，dispatch 次數為一次。reconciliation 比對 handler-entry receipt、job events、candidate ToolExecution、Artifact bundle hash、staging／published 檔案；`redispatch_allowed=false`。E1 沒有可觀測的子程序 PID，故不宣稱完成程序識別或結果歸因，狀態保持 unresolved。 |
| 5. 無效 geometry 注入 | **PASS** | E1 幾何注入在 `test_e1_approved_w7_rerun_publishes_current_draft_lineage_once`；E2 自交 polygon 注入在 `test_w7_e2_success_invalid_geometry_failure_unknown_and_restart`。兩者均於派送前拒絕，沒有新 job DB／ToolExecution／發布結果，原 scenario head 與歷史不變。W7 E2 router 在開 job store 前驗證 pinned geometry。 |
| 6. E1／E2 計算失敗注入 | **PASS** | `test_e1_calculation_failure_is_failed_and_outcome_unknown_survives_restart`、`test_w7_e2_success_invalid_geometry_failure_unknown_and_restart`：已知計算失敗為 `FAILED`，與 post-dispatch unknown 分開。E1 沒有發布輸出或 EvidenceCard；E2 失敗記錄沒有 distribution 數值，執行狀態為 `FAILED`，EvidenceCard 維持 `unverified`。 |
| 7. 模型／provider 傳輸失敗 | **PASS（僅離線 fake transport）** | `test_fake_model_transport_failure_is_redacted_and_never_creates_evidence`：離線注入 ConnectionError／TimeoutError，檢查失敗或 unknown 狀態、敏感測試標記不回顯、不建立 EvidenceCard；unknown 明確 `retry_allowed=false`。未呼叫 live provider。 |
| 8. Override 接正式 HumanDecision | **PASS** | `test_override_pending_event_uses_existing_human_decision_endpoint` 及 `keeps Override pending until the human submits through the formal decision API`：W7 只記待決事件，再由既有人類決策 endpoint 提交；後端測試以既有 test-only fixture 模擬人類提交。錯誤 hash 回 409，scenario 與 EvidenceCard 不變。新增瀏覽器檢查腳本 `web/e2e/week7_real_override_dialog.py`，未執行。 |
| 9. 關閉／重開後還原 | **PASS** | E1 unknown／成功重跑、E2 unknown／成功重跑與整段 walkthrough 均關閉並重開隔離 ProjectStateStore 和相應 job DB；重建 view，核對 lineage、scenario head、job id／狀態、artifact hash 和 idempotent replay。 |

## 修改檔案

- `src/urban_design/environment/plan_service.py`：E1 job stage 狀態分類、handler-entry receipt。
- `src/urban_design/generation/job_runner.py`：區分已知計算失敗與派送後失聯。
- `src/urban_design/week7/jobs.py`：E1 派送前 frozen-input／geometry 驗證、unknown reconciliation 與不重送狀態。
- `src/urban_design/week7/router.py`：E2 pinned geometry 派送前拒絕。
- `src/urban_design/week7/real_service.py`：Override 僅接受提案方案並指向正式 HumanDecision endpoint；離線 fake transport 失敗處理。
- `tests/test_week7_real_integration.py`、`tests/test_week7_e2_fault_paths.py`、`tests/test_week7_walkthrough.py`：正向、負向、故障注入與持久化測試。
- `web/src/week7/Week7Actions.tsx`、`web/src/week7/Week7RealActions.test.tsx`：待決 Override 對話框及正式人類決策送出測試。
- `web/e2e/week7_real_override_dialog.py`：手動瀏覽器檢查腳本；未執行。
- `docs/w7-fixes-report-zh.md`：清單結果、驗證、限制與重試紀錄。

## 最終驗證

所有 Python 測試均以指定 Python、`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src`、`-p no:cacheprovider` 執行；新測試使用 pytest 暫存目錄中的隔離 store／job DB。

| 指令 | 結果 |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python -m pytest -p no:cacheprovider tests/test_week7_*.py tests/test_generation_jobs.py tests/test_decision_resolution_pipeline.py` | **107 passed, 2 warnings, 58.82s** |
| `npm --prefix web run test` | **69 files passed；387 tests passed** |
| `npm --prefix web run build` | **成功**；Vite 提示 bundle chunk 超過 500 kB |
| `npm --prefix web run lint` | **exit 0**；輸出有 lint warnings，沒有 lint errors |
| `git diff --check` | **通過** |

補充 focused runs：Modify 正向／錯誤綁定 1 passed；E1 失敗／unknown 與成功 rerun 2 passed；E2 故障／重開 1 passed；完整 walkthrough 1 passed。

## 重試與清理紀錄

- Modify 初次測試的 StudyArea hash fixture 不符合 canonical geometry binding；修正 fixture 後通過。後續加入錯誤 StudyArea 綁定 409 負測，focused run 通過。
- Walkthrough 測試先後修正重複初始化 test key、DatasetSnapshot 使用 `id`、W7 scenarios response 欄位、E2 helper 匯入名稱；隔離 walkthrough 最終通過。均使用 `_world` 建立的 test-only key，沒有讀取真實密語。
- E1 focused run 曾使用缺少 `model_dump` 的簡化 mock，造成 `HANDLER_FAILED`；改用 typed `E1PipelineRunResult` 後，E1 known failure／unknown 測試 2 passed。
- E1 成功 rerun 測試初次檢查了錯誤的 metadata 欄位，另一次把實際祖先當成錯誤 lineage；改核對 ToolExecution parameters 並改用無關方案作負測後通過。
- E2 fault run 曾有 fixture family、執行數、draft 證據狀態、比較狀態假設不符；改為符合實際 contract 的檢查。無效 polygon 初次暴露派送前未轉為 HTTP 409，補上幾何 gate；重開測試曾沿用故障注入用 job DB，改回原隔離 DB；新增 failure assertions 時曾有縮排錯誤，修正後 E2 focused run 通過。
- Web Override 測試初次以跨元素文字匹配失敗，改用對話框 label selector 後通過；全套 Web 測試最終 387 passed。
- 清理／刪除：未執行任何檔案刪除、git clean/reset/checkout、服務重啟或部署；沒有觸碰受限埠，沒有讀寫正式 `state.sqlite3`。未安裝套件、未下載檔案、未呼叫真實模型或付費服務。`npm run build` 產生的 ignored `web/dist` 留在原處，未清理。

## 尚未完成／限制

1. Walkthrough 的 4 個方案由測試 fixture 建立，沒有驅動正式 proposal-generation workflow；本測試不構成正式場址方案生成證據。最終比較是 `NOT_COMPARABLE`，不產生 winner。
2. E1 reconciliation 能比對 handler-entry receipt、job events 與 artifact hash，但底層 handler 沒有提供可驗證的子程序 PID／engine receipt；因此仍是 `UNRESOLVED`，不會自動重送。
3. 瀏覽器腳本依要求只寫未執行；W7 Override 的提交路徑由 React 測試與隔離 API 測試驗證。
4. 模型測試只有離線 fake transport；未測試 live provider。
