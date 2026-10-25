# J2 有效決策解析器與重新考慮執行報告

結論：**INCOMPLETE**。實作、負面 pipeline 測試、前端測試及副本 API 演練已完成；全套 pytest 仍有 2 個使用者列明的既有失敗與 5 個既有 skip，未達全綠 release gate。未由執行者接受里程碑；待 Claude 跨 provider 獨立審核與 Founder 最終決定。

記錄 UTC：2026-10-07T15:11:00Z。task_id：`j2-decision-resolver`。執行者 OpenAI；Founder 指定模型路由 `gpt-6.1-sol`、reasoning effort `medium`，理由為極難 bounded integration。未委派、未 fallback；記錄的是指定路由，宿主未提供可獨立核驗的模型 runtime receipt。

## 分支、授權及保護

worktree `/Users/jackhsieh/Downloads/TUD/Q5/w6-07-compare`，分支 `wp/w67-integration`，source commit `567a1fa52db5de1dfb119d21eaf321adc7ac61ce`；從頭到尾未切分支。已讀 J1 報告、治理文件與 Founder takeover event，按 2026-10-07 規則執行，沒有重問或使用舊的 pending policy。J1 的測試與改動保留。未 stage/commit/merge/push/deploy；變更留在 worktree 供 Claude 審核提交。

正式 DB 只以 `mode=ro` + SQLite backup API 產生副本；測試金鑰僅存臨時目錄。未讀正式密語、key、.env、Keychain；未安裝/下載、呼叫付費或 Live AI、刪除檔案、重啟或操作禁止的服務與隔離 runtime。API 驗證使用 FastAPI TestClient，未聲稱瀏覽器或正式 runtime 驗收。

正式 DB `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3`：開工 2026-10-07T14:00:47Z、結束 2026-10-07T15:06:38Z SHA-256 均為 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`。核驗檔 `artifacts/j2-decision-resolver/final-verification.json`，SHA-256 `de70b1388f0b9ff73274afcade852af4fa719c82e1b07c1e8e50b521731a7597`。483 個來源/測試/Web 檔凍結後漂移 0；J1 guard 測試 SHA-256 `b58ed81df5096dc0977873c0bbc59c62d754736f3a32430ae9d21403f5e7e880`。

## 最終行為

1. 新增共用 typed `DecisionTarget` / `DecisionResolution`。以 persisted ledger sequence 選最新相容決策，驗證 immutable decision state、event、project、target type/ID/version、指定 hash、action、actor/session、parent 與 transition。事件缺漏或衝突回 BLOCKED；沒有 ID/timestamp 排序、前綴推測、hash OR、catch-all 回退批准。
2. E1 plan、E2 plan/weather snapshot、W7 jobs/view、comparison 及 formal authority 都經共用解析器。W7 同 SHA 也比對版本與 decision identity；重新批准產生新 job，不重用舊決策的 job。
3. DesignScenario accepted/rejected revision 繼承只允許事件明確命名 `human_decision_id`、相鄰 parent revision、同 geometry artifact 與 SHA，並驗證 action/status/actor/refs。任意 parent revision 不能授權。
4. 新增 `DecisionAction.Reconsider`，對 accepted/rejected scenario 追加 HumanDecision 與 ReconsiderDesignScenario 事件，新 revision 回 proposed 並撤除 baseline；歷史不改寫。只有新密語授權決策可重新接受。`POST /api/v1/scenarios/reconsider` 綁定 version/geometry SHA、理由及 SecretStr key；錯誤 key 403，無新 ledger event。
5. Compare 加重新考慮按鈕與理由/密語對話框，en/zh-TW；顯示實際 revision 與 Pending。重新選定後 formal draft 採新 ID，保留舊 draft。
6. E1/E2 的 promotion 在 store 同一 `BEGIN IMMEDIATE` 交易内重新讀有效決策與 inputs；decision 改變則 rollback promotion。計算 artifact/tool execution 與 unverified evidence 歷史保留，沒有將失效批准結果標為 validated。

## 實際驗證與 SHA-256

以下為最後固定來源的 fresh 執行。每列 PASS 只代表該限定檢查。

| 檢查 | 結果 | 實際證據檔 | SHA-256 |
|---|---|---|---|
| 實際 pipeline focused | PASS: 35 passed, 1 warning, exit 0 | `artifacts/j2-decision-resolver/verified-focused.log` | `8622c0ea4f0d71cb77347fa691741e87fcbdb2061386292750ece3cd8c3aa6bd` |
| Vitest | PASS: 312 passed / 51 files, exit 0 | `artifacts/j2-decision-resolver/vitest-frozen.log` | `5d86c51d8c872fafcfbaed499716f676e21d60e4726ae9de389b194b696b6fca` |
| lint | PASS: exit 0；保留 warning | `artifacts/j2-decision-resolver/lint-complete.log` | `535fe6a145ea20a2b434f3642199b4ff176c24eef9a66fd8fd146a1759a2d97d` |
| TypeScript | PASS: tsc -b --noEmit exit 0 | `artifacts/j2-decision-resolver/tsc-complete.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| DB 副本演練 | PASS: exit 0；13 API receipts | `artifacts/j2-decision-resolver/rehearsal-complete.log` | `674ca64b03fc7497a116b76991b86b18326365ec9602bb835515c59e1c3943e8` |
| git diff --check | PASS: exit 0 | `artifacts/j2-decision-resolver/final-diff-check.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| 全套 pytest | INCOMPLETE: 2090 passed / 2 failed / 5 skipped / 15 warnings, exit 1 | `artifacts/j2-decision-resolver/pytest-full.log` | `cec2aba92c396f984f6eab776691d05b23bc26b79f80cd6765fb6b3c389834df` |

完整命令：`artifacts/j2-decision-resolver/commands.txt`，SHA-256 `6e962802e86cf1c48d3a23aad5b45e64b84240ab5a39462e80fa1e528ddd919e`。完整 pytest 以 nohup 非 TTY 執行，無 node 排除、skip 新增或 deselect，使用 `Q5_READONLY_FIXTURE_ROOT` 與 `PYTHONPATH=src`；開始 2026-10-07T14:33:35Z、結束 2026-10-07T15:03:54Z，耗時 1815.78 秒。JUnit `artifacts/j2-decision-resolver/pytest-full.xml`，SHA-256 `ad28180ad0ff085d383c66891a16cef045e3fd54a2a18598323d11aa672c87e6`。收集 2097 項，新增 J2 26 項全部 passed；下列 node 的 passed 證據共同由完整 JUnit、focused log 及 outcome inventory 支持，並非 helper-only 結論。

- `tests/test_decision_resolution_e2.py::test_actual_e2_dispatch_reject_blocks_without_job[plan]` — passed
- `tests/test_decision_resolution_e2.py::test_actual_e2_dispatch_reject_blocks_without_job[weather]` — passed
- `tests/test_decision_resolution_e2.py::test_actual_e2_promotion_reject_between_check_and_transaction` — passed
- `tests/test_decision_resolution_pipeline.py::test_ledger_order_actual_e1_and_w7_dispatch` — passed
- `tests/test_decision_resolution_pipeline.py::test_actual_e1_handler_reject_after_approval_before_dispatch` — passed
- `tests/test_decision_resolution_pipeline.py::test_reconsider_actual_comparison_api_and_old_accept_never_revives` — passed
- `tests/test_decision_resolution_pipeline.py::test_parent_revision_without_named_transition_cannot_inherit` — passed
- `tests/test_decision_resolution_pipeline.py::test_e1_promotion_transaction_rechecks_after_reject_and_retains_history` — passed
- `tests/test_decision_resolution_pipeline.py::test_formal_draft_pipeline_blocks_after_reconsider_and_generic_parent` — passed
- `tests/test_decision_resolution_pipeline.py::test_w7_view_requires_exact_named_transition` — passed
- `tests/test_decision_resolution_pipeline.py::test_missing_latest_reject_event_blocks_actual_dispatch_not_old_approval` — passed
- `tests/test_decision_resolution_pipeline.py::test_actual_w7_rerun_changed_decision_aborts_promotion_even_same_plan_sha[Reject]` — passed
- `tests/test_decision_resolution_pipeline.py::test_actual_w7_rerun_changed_decision_aborts_promotion_even_same_plan_sha[Approve]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[state_revision-None]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[target_type-DesignScenario]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[project_id-other-project]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[parent_event_id-unrelated-event]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[action-Approve]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[actor_session_id-wrong-session]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[payload_json-{]` — passed
- `tests/test_decision_resolution_pipeline.py::test_corrupt_latest_decision_event_blocks_actual_e1_pipeline[actor_kind-FORGED_ACTOR]` — passed
- `tests/test_decision_resolution_pipeline.py::test_current_scope_state_event_conflict_blocks_actual_e1_pipeline[target_type-DesignScenario]` — passed
- `tests/test_decision_resolution_pipeline.py::test_current_scope_state_event_conflict_blocks_actual_e1_pipeline[target_id-unrelated-target]` — passed
- `tests/test_decision_resolution_pipeline.py::test_current_scope_state_event_conflict_blocks_actual_e1_pipeline[target_version-999]` — passed
- `tests/test_decision_resolution_pipeline.py::test_current_scope_state_event_conflict_blocks_actual_e1_pipeline[target_artifact_sha256-sha256:0000000000000000000000000000000000000000000000000000000000000000]` — passed
- `tests/test_decision_resolution_pipeline.py::test_current_scope_state_event_conflict_blocks_actual_e1_pipeline[project_id-other-project]` — passed

負面覆蓋包含 actual `execute_e1_rerun`、E1 API dispatch、E1/E2 promotion、E2 plan/weather dispatch、formal draft、W7 view、comparison API。race test 在先前解析之後、promotion 交易之前注入 Reject，並於 callback 斷言 `connection.in_transaction`；交易內重解析阻止 promotion，保留計算歷史。W7 也驗證在同 plan SHA 下 Reject 或新的 Approve 都使正在執行的舊決策 job 中止。

corrupt actor case 受既有 SQLite CHECK 約束阻擋：測試確認 IntegrityError，並繼續驗證 API409；不是聲稱成功插入不存在的 actor。其餘 event/state corruption 實際進入 E1 API pipeline，驗證 fail-closed。

完整結果清單 `artifacts/j2-decision-resolver/outcome-inventory.json`，SHA-256 `8c34a00d37163e86ed5d230e849dee8a888761b20875115253f08fc5dfd3574f`。

兩個失敗原樣保留，未放寬斷言：

- `tests/test_m2a03_spatial_policy.py::test_piped_decision_key_stays_on_stdin_when_dev_tty_exists`：`/dev/tty` PermissionError（沙箱）。
- `tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema`：歷史 PNG bytes 第 66 位不一致。

五個 inherited skip，未新增 skip：

- `tests/test_m2a02_plugin_launcher.py::test_project_has_an_unambiguous_visible_identity`：missing untracked runtime file .urban_design_runtime/rotterdam-m4h-pilot-project.qgs; this worktree does not carry the local QGIS project, so the visible identity cannot be checked
- `tests/test_m2a02_r02_georeference.py::test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path`：missing untracked runtime file .urban_design_runtime/rotterdam-m4h-pilot-project.qgs; this worktree does not carry the local QGIS project, so the anchor extent cannot be checked
- `tests/test_pst_syntax.py::test_compute_pst_six_syntax_layers_m4h_context`：retained M4H context or StudyArea fixture is unavailable
- `tests/test_site_analysis_report.py::test_syntax_map_rerender_when_matplotlib_is_available`：matplotlib is unavailable in this test interpreter; PNG redraw skipped
- `tests/test_week4_r03_integrity.py::test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit`：missing untracked runtime file .urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson; this worktree does not carry the local StudyArea artifact, so R03 parent drift cannot be checked

lint 保留既有 warnings，exit 0 不表示零警告。pytest 15 warnings 包含 Compare router 既有重複 registration 帶來的 operation ID warning；新增 reconsider route 也有 duplicate operation ID warning，未隱藏，待指揮官獨立檢視。未以變更來源消除警告後重用舊測試結果。

## 正式 DB 副本 API 演練

分類 **FIXTURE_ONLY**。SQLite backup 來源是正式 DB；複本 `/private/tmp/q5-j2-rehearsal-3k7ntbet/copy.sqlite3`，演練後 SHA-256 `b40cc64c1b42a2e45216cd1a8e66af7d09e290abedaebdcaf26f0d60777bacd0`，343 ledger events，`quick_check=ok`。在複本加入合成 project-e1/proj-formal fixtures，以臨時測試金鑰執行；沒有批准原 Rotterdam entities。E1 使用本地 deterministic Radiance 執行。Approve→Reject 後 dispatch 409；新 Approve 後新 run SUCCESS。Scenario 選定→三個 accepted/rejected scenario 各重新考慮→comparison 全部待定→新選定；歷史 revisions 1/2/3/4 保留；錯誤金鑰拒絕且 ledger 不變。

唯一最終 API receipt 目錄 `artifacts/j2-decision-resolver/rehearsal-20261007T142904Z-1e46856b3c4f4c6085e080ef26fbb2e1`；request 已去除 decision_key，含 response/status/UTC。每一步實際證據如下：

| receipt（以上目錄內） | SHA-256 |
|---|---|
| `01-e1-approve.json` | `1abe82242fe1291b7d026c06aa9b7185b6aa9494d604af8ca92a78ace57d1ca6` |
| `02-e1-approved-execute.json` | `102ffa8b97229b65ee6104c1b758c7411ecfafcd6316ef479abc792b20d0930e` |
| `03-e1-reject.json` | `716f854c9144e04f8ff8ef6494f031fa1da8cc9ed8b3a83a607c0d333f5903f4` |
| `04-e1-rejected-dispatch.json` | `d882cde7acb05410d3823379de719583e6f5a2f284a1b42952ddd575ad55941c` |
| `05-e1-new-approve.json` | `380a0882f587d9dc7941a61b807de24d37867893d54b33f202c8e941abd3392f` |
| `06-e1-reapproved-execute.json` | `5a5dadaea07f6bd2d8d8a829b9ecb2a0772cac4b9da30fb613d1b64b81b8cb86` |
| `07-scenario-select.json` | `56b9379c498a673b14b6e6da43e68c13f3edefb3fcd527313bb47b0bd2d2099d` |
| `08-wrong-test-key.json` | `e11601002857bfd2667bf1c9c59bb1dbafeed6c4be267bfacb99698e2e2ba23e` |
| `09-reconsider-0.json` | `9bd911ee530a6cdeecc241604c4cc03e136b18e3fee469c79b01c56604a90916` |
| `09-reconsider-1.json` | `29786b070ab5051477436db96a7c6be0b2b3d07f71d6477f8337d0cf79b2217b` |
| `09-reconsider-2.json` | `6271f0ac9451f60b2a6ed70a8d8b17a343f93cba7cc80cd04b7921aa2ad5377b` |
| `10-pending-comparison.json` | `36ba0d76eda990a2b22fc4261e767f7e153b792b9c561da73c5de6c8bfd18948` |
| `11-scenario-reselect.json` | `51e9d5cbf9b894a619f9762b4dfeb855af1ce386326325488e85aadba00dbae1` |

演練 audit `artifacts/j2-decision-resolver/rehearsal-audit.json`，SHA-256 `f05638a717f97359f5870c73704dc730e5e7075f263d77222da2b0632f99ea25`。前兩次診斷演練共用 rehearsal/ receipt 名稱，第二次覆寫第一份診斷 receipts；log 與臨時 DB 留存。最終改採 UTC+UUID 目錄獨立保存，以上只有最終演練作為證據，沒有聲稱早期 receipts immutable。

## 修正過程與證據界限

缺少最新 Reject event 的初始 RED 測試實際得到 HTTP200，之後加入 heads/event completeness audit；最後 actual dispatch 為 BLOCKED，不回退舊 Approve。保留 `missing-event-red.log`，SHA-256 `b7cce9f44dd260fa9960c42811710c16a008090869cfde0c3de918a651adb2c5`。過程中亦修正 E2 缺 ActorKind import 與前端 unused parameter；沒有降低門檻。四次因來源修正中止的完整嘗試在 interrupted-full* 目錄保留，不列為完整測試通過。正式 acceptance 只採上述完整 final run。

來源 import provenance `artifacts/j2-decision-resolver/import-provenance.json`，SHA-256 `83f04926695bb356d7e711e0411f340ca956db5a896eebb6bb4d86f0466a662d`，證明匯入 worktree src，沒有採用 /private/tmp 暫存 helper 的測試取代實作。

## 變更清單及交接

J2 source/test 檔 SHA-256：

| 檔案 | SHA-256 |
|---|---|
| `src/urban_design/api.py` | `b84c205bd20a343aba5206977b993fbfce8aa08858464e2e503ac0375337667c` |
| `src/urban_design/editing/formal_authority.py` | `8e7ad0358ece314b003bd24f61f3f44660367843d7f3cca484564d14e8c526bc` |
| `src/urban_design/environment/e2_service.py` | `90d5f93579dbc9bc32fbe0d257736b3b0dad3bcd6cad57804bd091dc4cb2595f` |
| `src/urban_design/environment/pipeline.py` | `fe66091aa4ef3d760c01f4107764fdd33d4153ba4eb2cd4b25f72136e547cdc6` |
| `src/urban_design/environment/plan_service.py` | `45452036a1912d1f3cd4da77e0ff81729d7b2cb31e6af8e44fb25a9b666df436` |
| `src/urban_design/environment/router.py` | `d8fe87f0a278aac09951fba103623326a8949929daeb19a996410205d51119d7` |
| `src/urban_design/environment/weather_snapshot.py` | `7b9898804712d6f245b90ac2856e550b88b2ecfdde94c1ca71fb7ecca93218a1` |
| `src/urban_design/generation/formal_service.py` | `25c8ae2afb0ca8bc0a1a429ff5143ee22e050ae33b64937fcfe7c7f42baecc6c` |
| `src/urban_design/models.py` | `5cc697dda31b168f416d65f9b98d65e3a3bc6ded2e191ddcf7883c29f39a9792` |
| `src/urban_design/scenario_api.py` | `2d3436e67f1e0f00cb285c9f1044f9ec5a0e2898242c888b5af8190427752b4b` |
| `src/urban_design/scenario_comparison_router.py` | `5aaa5bf8ad3460545193a9a9bad19269e5a5813be15a5dfe24498273da342e5c` |
| `src/urban_design/store.py` | `4fb9922eef039b5bc566206a299a33a8af5427d45cd10e47bdc10ac449542cfd` |
| `src/urban_design/week7/jobs.py` | `f2a3db519ae844a6088938a4790cd3e5ca8b65faba5b4bc868757c92110a69a6` |
| `src/urban_design/week7/real_service.py` | `8a777a6e83ff3414b214e523e0d81f381da81f13d136ed0220f7622cfe7c4a63` |
| `web/src/components/CompareWorkspace.test.tsx` | `29b38cd676bda0d7df0b38294d740334b1eaa5fb0f8dab0c38f8d2457015a127` |
| `web/src/components/CompareWorkspace.tsx` | `9877a9b531ea39a3a6567fc7ef7e1261d897dd3f9a66b275f8a949de17b5a216` |
| `web/src/components/HumanDecisionDialog.tsx` | `c3c69219fc808dd33520b07af7349cef07f1e6456705a26340e791ecde43829e` |
| `web/src/i18n/scenarios.ts` | `914292b83bd61b10a73d86b678713ac88886ba6ac00d44a14169acb805c73417` |
| `src/urban_design/decision_resolution.py` | `03d36d792d578ae8d6a3e78aac72bc4093007ea9ec559e58667816cddd0b0c3f` |
| `tests/test_decision_resolution_pipeline.py` | `a48350abe5202ce3bbcb1caf547f4427137562ce0bb58791ad13c07ec5a00fda` |
| `tests/test_decision_resolution_e2.py` | `09fe9870992c44780a203e9c6aca1a335b2a80a669647fcb1ce33c1baf94b87a` |

`final-tracked-diff.patch` 只含 tracked diff（包含先前 J1 week7_support.py），不含 untracked resolver/new tests；不可用它單獨判斷完整 J2 diff。`write-set.json` 明列 J2 與保留 J1 範圍，SHA-256 `9e468174ef93c5662e3175e6ee1056734f392d4b3dce3f620a4bc04fc9ad0341`。

完整 evidence manifest `artifacts/j2-decision-resolver/evidence-manifest.json`，SHA-256 `e7820e01b0232cc04568a4986ce4bc23c3b14dfa88ff48edc04e2abe4fa739c7`；包含實際現存檔案大小/雜湊與 J2 source SHA，排除 manifest 自身及之後產生的報告/handoff，避免循環雜湊。

交給 Claude：審核共用 resolver 全部 binding、transaction callback/race、append-only reconsider、26 個新增 pipeline nodes、13 receipts 與 full suite blockers；確認 OpenAPI route warning。沒有跨 provider review 或 Founder acceptance receipt，不能宣告里程碑完成。後續若修正來源須重新執行相關 checks，不能沿用本次凍結來源證據。
