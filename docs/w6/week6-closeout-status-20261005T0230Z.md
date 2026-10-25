# Week 6 closeout status

記錄時間：2026-10-05T02:30:18Z。這是整合分支上的演練紀錄，不是合併，也不是 Founder 驗收。

```text
WEEK_6_IMPLEMENTATION: INCOMPLETE
WEEK_6_RUNTIME_ACCEPTANCE: BLOCKED
CP_W6: BLOCKED
WEATHER_METHOD_GATE: READY_FOR_FOUNDER
E2_EXECUTION_GATE: BLOCKED
LIVE_AI_GATE: READY_FOR_FOUNDER
CROSS_PROVIDER_REVIEW: PENDING
FOUNDER_ACCEPTANCE: PENDING
WEEK_7_ENTRY: NOT_ENTERED. Commander reviews wp/w6-closeout-integration. Founder still owns the chapter 5 merge onto main, the production restart, five-scheme regeneration, Decision 3, E1 plan approval, the weather HumanDecision, the Live AI key, PROJECT_AI_AUTHORIZED, and the restart, plus the personal C1 sync. No Week 7 feature work is open.
```

Live AI 與天氣的閘門值是 `READY_FOR_FOUNDER`。正式 live 呼叫與正式天氣 HumanDecision 仍待 Founder。這份紀錄沒有把這兩項寫成 PASS。

## 第 7 章

TASK: G14 整合、全鏈演練、故障注入與 W7 交接
STATUS: DONE_ON_BRANCH
BRANCH/COMMIT: `wp/w6-closeout-integration`。本文件與 `web/e2e/week6_closeout.py`、`tests/test_week6_closeout_safety.py` 同一個 commit。父提交是合併尖端 `f4cf03e`。SHA 記在同一次 OPERATIONS-LOG 追加。未合併到 main，未驗收。
WORKTREE: `/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor`

CHANGED FILES:
- `web/e2e/week6_closeout.py`
- `tests/test_week6_closeout_safety.py`
- `docs/w6/week6-closeout-status-20261005T0230Z.md`

做了什麼：從 `45c9c07` 切出 `wp/w6-closeout-integration`，依第 5 章順序把已完成分支合進這條演練分支。`web/e2e/week6_closeout.py` 對權威庫的 sqlite backup 複本跑了兩次。兩次都讀到同一個 workspace，八條故障的預期與實際一致，然後把臨時 API 停掉。視覺鏈與五案重生成沒有跑。

### 合入

合併提交（新到舊）：

| commit | 合入 |
|---|---|
| `f4cf03e` | `wp/w6-weather-e2` |
| `ebfb4b7` | `wp/w6-live-ai` |
| `a3db381` | `wp/w6-test-hygiene` |
| `11e8eec` | `wp/w6-01-qgis` |
| `3904a7e` | `wp/w6-11-e1` |
| `4ddf329` | `wp/w6-syntax-readiness` |
| `87f3615` | `wp/w6-route-contract` |
| `2b1b41d` | `wp/w6-polish` |
| `fd44a8e` | `wp/w6-road-access` |

已經是祖先、沒有另做合併提交：`wp/w6-integration` `7ea3b89`、`wp/w6-formal-editor` `5d224fb`、`wp/w6-formal-faces` `b588593`、`wp/w6-formal-snapping` `45c9c07`。

沒有合入：`wp/w5-02-d1-session-guide` `750d112`（G3 文件；持久與量測仍是 PARTIAL）、`wp/w6-editor-custody` `06d6a89`。`wp/w5-ai-routes` 沒有修改。main HEAD 仍是 `516bbaafa42522e809031f47df4cd35d4dc7e306`。

### 複本演練

兩次演練的狀態欄位一致。不同的只有 API port（8880、8881）、預留的 web port（5280、5281）與各自的輸出目錄。綁定 `127.0.0.1`。web server 是 `NOT_STARTED`。API 子行程的 `project_ai_authorized` 是 `0`，`ariadne_live` 是 false。兩次備份雜湊都是 `0138554b746017a5f47f5e94e3521426b6576ae24965e61485f1c00546bdca76`。這是 sqlite backup 的雜湊，與權威檔雜湊分開。權威檔在每次備份前後都是 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`，3211264 bytes，`authority_written` false。

兩次讀到的 workspace 相同：HTTP 200，project `rotterdam-m4h-pilot-project`，workspace `workspace-rotterdam-m4h-pilot-project`，revision 8，study area `study-area-rotterdam-m4h-pilot-project-v5`，status `DRAFT`，HumanDecision 3，DesignScenario 5。兩次回應本文位元組相同，sha256 `8fb43f431ed6443c49fb78b5f125974081e38be687d681aee44fb6cd62f86842`。`r4_tradeoff_label_present` 是 true，標籤來自已合入的 golive 封包 `ACCEPTED_TRADEOFF_FOUNDER_2026-10-04`。

演練閘門：`C1_FOUNDER_SYNC`、`DECISION_3`、`FIVE_SCHEME_REGENERATION` 是 `NEEDS_FOUNDER`。`G3_PERSIST_MEASURE` 是 `PARTIAL`。`VISUAL_SELF_CHECK` 是 `INCOMPLETE`。`E2_EXECUTION_GATE` 是 `BLOCKED`。`LIVE_AI_GATE` 與 `WEATHER_METHOD_GATE` 是 `READY_FOR_FOUNDER`。

### 故障注入

兩次的故障列相同。第二次紀錄與第一次位元組相同，sha256 `1b8e328bf84c383866f69ca2888e8a0e563ac1403fa5dc58551993841f938ad6`。

| 故障 | expected | actual | recovery |
|---|---|---|---|
| api-killed-mid-job | INTERRUPTED | INTERRUPTED | INTERRUPTED |
| tampered-db-copy-hash | HASH_MISMATCH | HASH_MISMATCH | BACKUP_HASH_RETAINED |
| tampered-artifact | OUTCOME_UNKNOWN | OUTCOME_UNKNOWN | ORIGINAL_BYTES_RETAINED |
| wrong-passphrase | REJECTED | REJECTED | TEST_KEY_STILL_ACCEPTED |
| live-ai-401 | HTTP_401 | HTTP_401 | NO_SOCKET |
| live-ai-429 | HTTP_429 | HTTP_429 | NO_SOCKET |
| radiance-unavailable | UNAVAILABLE | UNAVAILABLE | PINNED_MANIFEST_PRESENT |
| formal-e2-refusal | BLOCKED | BLOCKED | READY_FOR_FOUNDER |

API 被殺的那一條，error_code 是 `RECOVERY_REQUIRED`。錯密語與 Live AI 故障用的是測試字串與假 transport。報告裡沒有密語、key 或 token。沒有讀 Keychain，沒有付費呼叫。

被保護的 port 8795、5195、8787、8644 在紀錄當下接受連線，這次沒有啟動或停止它們。8788、8789、9876 沒有在聽，也沒有被啟動。演練用過的 8880 與 8881 在紀錄當下已經關閉。

### 測試

TESTS (fresh):

- 整合分支全套：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python -m pytest -q -p no:cacheprovider`，cwd `/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor`，stdin 脫離 tty。結果 `2 failed, 1806 passed, 6 skipped, 14 warnings in 1535.91s`。紀錄 sha256 `6a89875d42b88c2034644892282c7b54e8d7b87e4b92557da983039b956860d5`。
- 失敗一：`tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema`，index 66 仍是 `b'u' != b'w'`。斷言沒有放寬。說明在 `docs/w6/g13-test-hygiene-20261005T0044Z.md`，sha256 `a4ea479a8fd450e520be37b027c016f29be8e242adbd75f248a9317109e66457`。
- 失敗二：`tests/test_week4_r04_amendments_r02.py::test_self_test_returns_status_and_runs_fault_cases_when_upstream_is_valid`。upstream 是 BLOCKED，56 條錯誤裡有 4 條是 `declared R04 parent is missing or unsafe: .urban_design_runtime/state.sqlite3`，這 4 條沒有 `mismatch` 這個字，所以阻擋路徑的斷言沒有過。其餘是凍結 R04 包對後來提交的 parent SHA-256 mismatch。這支測試在計畫第 1.2 節的已知名單裡。權威庫留在專案檢出目錄，沒有複製或 symlink 進這個工作樹，斷言沒有放寬。
- 六個 skip 都是既有條件，G14 沒有新增 skip：
  - `test_m2a02_plugin_launcher.py::test_project_has_an_unambiguous_visible_identity`：G13 明示 skip，工作樹沒有 `.urban_design_runtime/rotterdam-m4h-pilot-project.qgs`。
  - `test_m2a02_r02_georeference.py::test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path`：同上。
  - `test_week4_r03_integrity.py::test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit`：G13 明示 skip，工作樹沒有該 StudyArea artifact。
  - `test_week4_repair_integrity.py::test_r02_archive_remains_intact_and_reports_exact_current_source_drift`：G13 的條件，工作樹內沒有本地 `state.sqlite3` 快照。
  - `test_pst_syntax.py::test_compute_pst_six_syntax_layers_m4h_context`：既有條件，M4H context 或 StudyArea fixture 不在這個工作樹。
  - `test_site_analysis_report.py::test_syntax_map_rerender_when_matplotlib_is_available`：既有條件，這個解譯器沒有 matplotlib。
- vitest：合併後的樹，45 files，279 passed，6.37s。紀錄 sha256 `b5e30af998d426ff643528b0d6e9edaec4e3bdbb8ee2e3f8ed877b47f2f79b63`。
- Playwright：`npx --prefix web --no-install playwright --version` 結束碼 1，缺少 `playwright@1.63.0`。沒有安裝。探針 sha256 `c50b713a5247eb490233b2ae5fb2282915b36d8e138d6286e07c3ddcfdae6673`。視覺自我檢核維持 INCOMPLETE。沒有截圖。

SELF-CHECK:

- [x] 兩次複本演練的狀態欄位一致，故障列的預期與實際一致。
- [x] 九個狀態代幣都寫在本文件，Live AI 與天氣是 `READY_FOR_FOUNDER`。
- [x] 凍結備份雜湊、收據與未完成項目都寫了負責人。
- [x] 全套只剩計畫第 1.2 節已點名的兩支失敗。PNG 斷言沒有放寬，沒有新增 skip。
- [ ] 視覺全鏈、五案重生成、決策三、正式 E1、正式 E2、Live AI 正式呼叫、C1 本人同步。這些停在 Founder 或指揮官，本包沒有把它們做成通過。

ARTIFACTS:

- `web/e2e/week6_closeout.py` sha256 `a8eb4fc0a906569cd3547f246619c16a5619826c35d38ec21601efa1f237e33d`
- `tests/test_week6_closeout_safety.py` sha256 `1b47198dc0f2cdc00371c11aba584eeb0c45bfcf05c15a5d157cbc27fa9f272d`
- 全套 pytest 紀錄 sha256 `6a89875d42b88c2034644892282c7b54e8d7b87e4b92557da983039b956860d5`
- 兩次故障列 sha256 `1b8e328bf84c383866f69ca2888e8a0e563ac1403fa5dc58551993841f938ad6`
- 兩次 API 本文 sha256 `8fb43f431ed6443c49fb78b5f125974081e38be687d681aee44fb6cd62f86842`

DEVIATIONS: goal plan 的 Deviations 仍是既有六條。這包沒有加第七條。

RETRIES/CLEANUPS: 演練腳本在進正式兩次之前修過三處，並留在這次 commit：回復前先 claim 再殺擁有者；Live AI 故障只在該行程內把 `PROJECT_AI_AUTHORIZED` 設為 1，模型清單回 200，401 與 429 來自假的 chat transport，結束時還原；備份比的是目錄盤點與權威檔雜湊，不是把 sqlite backup 位元組拿去對權威檔。沒有刪檔，沒有 amend `f4cf03e`、`06d6a89`、`5d224fb`、`b588593` 或 `45c9c07`。

STOP POINT / NEEDS: 見下一節。這不是驗收。

NEXT: 指揮官審查這條分支。Founder 決定第 5 章的 main 合併順序。執行者不合併 main。

## 凍結雜湊、收據與未完成項目

權威檔與備份是兩件事。

| 物件 | SHA-256 | 負責人 |
|---|---|---|
| 權威庫 `project/.urban_design_runtime/state.sqlite3`，3211264 bytes，mode=ro，quick_check ok，Approve 3，ledger 303 | `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366` | 執行者只讀。寫入與 checkpoint 留給之後的 Founder 授權流程 |
| 演練 sqlite backup（兩次相同） | `0138554b746017a5f47f5e94e3521426b6576ae24965e61485f1c00546bdca76` | 演練產物。它不是權威檔的位元組複本 |

收據與封包：

| 物件 | 位置 | SHA-256 | 負責人 |
|---|---|---|---|
| C1 代理收據，revision 10，payload_digest `6fa2ccf8a32dca052cfa4a6828ae4e8be3a93ccadfa697353d188e0610c39f76` | `docs/w6/c1-proxy-receipt-20261005T0025Z.json` | `0285517fe91fc43cb5d2e8cb0fdb5360c789a710d6034228adf83c4e910b51e1` | 正式同步是 Founder 本人。這次是代理模擬 |
| 道路 r4 golive 封包 | `docs/w6/road-access-golive-packet-20261004T2230Z.md` | `407f4cfad514172ac714235f323159e04fcf63c366290a3c4d09ae0cdb1806b0` | 合併、重啟、五案重生成是指揮官與 Founder |
| Live AI 封包 | `docs/w6/live-ai-acceptance-packet-20261005T0000Z.md` | `9d5febf656e48bece3d7fa2022487b6bf7fe7494a4c7422fe3612728306fa527` | Founder 設定 Keychain 服務 `urban-design-openai-gpt-4o`、`PROJECT_AI_AUTHORIZED=1` 與重啟 |
| 天氣方法封包，建議 candidate-01 | `docs/w6/weather-method-approval-packet-20261005T0012Z.md` | `01dabf5df5509c071ff1a3286e2d7c9e755eaf8e660b59b8f908365e9267e396` | Founder 的天氣 HumanDecision。正式 E2 維持 BLOCKED |
| G13 已知 PNG 說明 | `docs/w6/g13-test-hygiene-20261005T0044Z.md` | `a4ea479a8fd450e520be37b027c016f29be8e242adbd75f248a9317109e66457` | 指揮官決定是否把這項已知失敗留到合併 |

candidate-01 原始 EPW sha256 `3c9a109d7f0b2e54c2b204d592bf5ec59774d16f36054bb89c284db4b5f7802a`。derived-minute60.epw sha256 `d6cc646473f2805002e28c99d13eb0c6d5fa08d40734b8fb2c89dbaae1371369`。原始位元組沒有改。

未完成：

| 項目 | 狀態 | 負責人 |
|---|---|---|
| G3 持久與量測 | PARTIAL | 指揮官。分支 `wp/w5-02-d1-session-guide` `750d112` 只含文件，沒有合進這條演練分支 |
| 決策三 | NEEDS_FOUNDER | Founder 在 Compare 選定基準方案 |
| 五案重生成 | NEEDS_FOUNDER | Founder 與指揮官，在 r4 合併並重啟之後 |
| E1 plan 批准 | 標籤仍是 `E1_PLAN: DRAFT_DOMAIN_FOUNDER_2026-10-04`，EvidenceCard 維持 unverified | Founder |
| 天氣 HumanDecision 與正式 E2 | READY_FOR_FOUNDER／E2 BLOCKED | Founder |
| Live AI key、旗標、重啟 | READY_FOR_FOUNDER | Founder。每週上限 200 ModelRuns |
| C1 同步 | NEEDS_FOUNDER | Founder 本人。8788 與 9876 這次沒有啟動 |
| 視覺全鏈 | INCOMPLETE | Playwright 未安裝。執行者沒有下載。若要截圖，由指揮官決定安裝 |
| PNG 位元組 | 已知失敗 | 指揮官。斷言保持原樣 |
| R04 self-test | 已知失敗，工作樹沒有權威庫檔 | 指揮官若要在帶有本地 runtime 檔的檢出重跑 |
| 跨 provider 審查 | PENDING | 審查者的 provider 必須不同於 xAI。Claude 或 Codex |
| Founder 驗收與 main 合併 | PENDING | Founder，在指揮官審查之後 |
| Week 7 | NOT_ENTERED | 依賴上一列全部停點 |

## 第 8 章自我檢核

- Founder 既有決定有被沿用：D1 v7／v8、D2 set A 陸域 183591.328 m²、南向集流路取捨標籤、E1 草案時程、Live AI 與天氣維持 READY_FOR_FOUNDER。沒有重問，沒有新的生產 HumanDecision。
- 權威庫雜湊在這次收尾前後仍是 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`。main HEAD 仍是 `516bbaafa42522e809031f47df4cd35d4dc7e306`。
- 沒有付費 API、下載或安裝。沒有讀 Keychain，沒有設定 `PROJECT_OPENAI_AUTHORIZED`。
- 沒有放寬門檻，沒有新增 skip，沒有 mock PASS。PNG 與 R04 兩支已知失敗都還在。
- `UNAPPROVED_PREVIEW`、`ASSUMED_*`、`FIXTURE_ONLY`、`DRAFT_*` 沒有升級。
- 各包的 commit、測試與事件在先前的 OPERATIONS-LOG。G3 持久與量測仍是 PARTIAL，所以 G3–G6 的合併核取維持未勾。G14 這包有 commit、全套結果與事件。
- 停點都寫成 Founder 或指揮官的工作。執行者沒有合併 main、沒有重啟 8795／5195、沒有做決策三、沒有做 C1 本人同步。
- 上面九個代幣是分開寫的。Week 6 實作是 INCOMPLETE。
