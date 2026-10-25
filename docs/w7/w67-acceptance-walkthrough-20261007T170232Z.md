# J3 凍結回歸與隔離完整驗收走查

**最終狀態：INCOMPLETE。** 凍結 HEAD gate 失敗（branch 與來源檔 bytes 未變），已停止後續演練；原 gate 保留。STALE／W7 Rerun 與實際故障矩陣未完成 gate；全套回歸非全綠。未接受里程碑、未提交本任務、未部署。

UTC：2026-10-07T17:01:00Z；task_id：`j3-w67-walkthrough`。執行者 OpenAI；使用者指定 `gpt-6.1-sol / low`，複雜但 bounded 的整合走查。宿主模型 runtime receipt unavailable，未宣稱獨立核驗模型。Claude 指揮官／Founder 保留審查與接受權。未委派。

## 凍結與保護

分支固定 `wp/w67-integration`；凍結時 HEAD `567a1fa52db5de1dfb119d21eaf321adc7ac61ce`。初始來源清單 483 檔；發現 35 個既存 bytecode 未列入後，改以完整 518 檔凍結，重新啟動完整 pytest。首輪保留為診斷；正式凍結回歸採第二輪。未排除測試、未新增 skip／deselect、未放寬斷言。

凍結後 HEAD 已移至 `f58a5a55de7d29603ba92fff41aa96df4c306c4d`，原始 HEAD `567a1fa52db5de1dfb119d21eaf321adc7ac61ce`。本執行者沒有 Git mutation；Git raw log 與原 gate 失敗：`artifacts/j3-w67-walkthrough/report-head-gate-failure.json` — SHA-256 `97c3267511833e2dee05966d3fe96f1c6a80f1b5a0be393532c50badae7dca9a`；未放寬原斷言 `artifacts/j3-w67-walkthrough/build_report-head-gate-original.py` — SHA-256 `0f9993d51f39d0f375635730014db6376cb2b250cb3d531f286ed0d93c62421c`。此處只產生失敗／INCOMPLETE 交接，不重新驗收、不再跑演練。

完整凍結 `artifacts/j3-w67-walkthrough/freeze-all-files.json` — SHA-256 `474bc5f007763c69775e6d6949254bd6ebc37a2f9345f36415bd567a608e7b6d`。最終漂移 0，新增凍結範圍檔案 0；`artifacts/j3-w67-walkthrough/final-verification.json` — SHA-256 `f5d67129b46fc14170514c1bb1fc93c1c015ce4d66fa4088db5cd4da23da3564`。初始未提交變更詳列於原 freeze.json 與完整 freeze-all-files.json，包含 J1／J2 保留變更及未追蹤 .venv。

正式 DB 前後 SHA-256 均為 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`；只用 `mode=ro` + sqlite backup API，副本位於 summary.json 所列臨時目錄。測試金鑰僅在臨時目錄，不輸出密語；未讀正式 key／.env／Keychain。未動指定正式埠或 8940／8941。未安裝／下載／付費 API／Live AI／Git mutation；未執行刪檔命令，演練證據保留。

## 完整回歸（fresh）

pytest 收集 2097 項：{'passed': 2090, 'failed': 2, 'error': 0, 'skipped': 5}；退出 1。`artifacts/j3-w67-walkthrough/pytest-all-files.log` — SHA-256 `7b50c9331992274994103a0b398ad7ef5d3d71491b2454eca5f8a790b5bbbcad`；JUnit `artifacts/j3-w67-walkthrough/pytest-all-files.xml` — SHA-256 `9e6de20e1550bf5e1823441110d855e8acf08e72e6b144c30d0812304e0311a9`。

| 檢查 | 結果 | 證據與 SHA-256 |
|---|---|---|
| Vitest | PASS，exit 0 | `artifacts/j3-w67-walkthrough/vitest.log` — SHA-256 `5dbf94a7169d3d1e8bdb6f3f16d74fc72e4ff0f20fc4820d593738899dfac6c6`；退出收據 `artifacts/j3-w67-walkthrough/vitest-exit.txt` — SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa` |
| lint | PASS，exit 0 | `artifacts/j3-w67-walkthrough/lint.log` — SHA-256 `a4d40f44d8702fce20d0e5fbae69987b6ddb7fe7898286a4ddae2103af4c9209`；退出收據 `artifacts/j3-w67-walkthrough/lint-exit.txt` — SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa` |
| tsc --noEmit | PASS，exit 0 | `artifacts/j3-w67-walkthrough/tsc.log` — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；退出收據 `artifacts/j3-w67-walkthrough/tsc-exit.txt` — SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa` |
| tsc -b --noEmit（references） | PASS，exit 0 | `artifacts/j3-w67-walkthrough/tsc-build.log` — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；退出收據 `artifacts/j3-w67-walkthrough/tsc-build-exit.txt` — SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa` |
| git diff --check | PASS，exit 0 | `artifacts/j3-w67-walkthrough/git-diff-check.log` — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；退出收據 `artifacts/j3-w67-walkthrough/git-diff-check-exit.txt` — SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa` |

`tsc --noEmit` 根設定只有 references；因此另外執行 `tsc -b --noEmit`。Vitest 實際 312 tests / 51 files；lint 實際 46 條 warnings 原樣保留。空 log 不單獨作為 PASS，以上退出收據與 final-verification.json 一併核對。

完整 pytest 非通過項：

- `tests.test_m2a02_plugin_launcher::test_project_has_an_unambiguous_visible_identity` — skipped：missing untracked runtime file .urban_design_runtime/rotterdam-m4h-pilot-project.qgs; this worktree does not carry the local QGIS project, so the visible identity cannot be checked
- `tests.test_m2a02_r02_georeference::test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path` — skipped：missing untracked runtime file .urban_design_runtime/rotterdam-m4h-pilot-project.qgs; this worktree does not carry the local QGIS project, so the anchor extent cannot be checked
- `tests.test_m2a03_spatial_policy::test_piped_decision_key_stays_on_stdin_when_dev_tty_exists` — failed：AssertionError: Traceback (most recent call last):
    File "<string>", line 4, in <module>
  PermissionError: [Errno 1] Operation not permitted: '/dev/tty'
  
assert 1 == 0
 +  where 1 = CompletedProcess(args=['/Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python', '-c', '\nimport os, sys\nsys.path...ll last):\n  File "<string>", line 4, in <module>\nPermissionError: [Errno 1] Operation not permitted: \'/dev/tty\'\n').returncode
- `tests.test_pst_syntax::test_compute_pst_six_syntax_layers_m4h_context` — skipped：retained M4H context or StudyArea fixture is unavailable
- `tests.test_site_analysis_report::test_syntax_map_rerender_when_matplotlib_is_available` — skipped：matplotlib is unavailable in this test interpreter; PNG redraw skipped
- `tests.test_site_proposal_rotterdam_v4::test_offline_rebuild_matches_canonical_artifacts_across_store_schema` — failed：AssertionError: assert b'\x89PNG\r\n...END\xaeB`\x82' == b'\x89PNG\r\n...END\xaeB`\x82'
  
  At index 66 diff: b'u' != b'w'
  Use -v to get more diff
- `tests.test_week4_r03_integrity::test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit` — skipped：missing untracked runtime file .urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson; this worktree does not carry the local StudyArea artifact, so R03 parent drift cannot be checked

全部 traceback／非通過清單 `artifacts/j3-w67-walkthrough/pytest-outcomes.json` — SHA-256 `7c78ebc7ff37215b0c5c694a3fbb7fb984e9eef9a87e0fa2faa8fe3cf0026343`。既存 skip 是未執行，未豁免成 PASS。兩份完整 run 各有時間與退出收據，完整命令在 commands.txt。

## 兩次走查（真實資料副本；TestClient）

兩次狀態摘要比較：**不相同**，差異 10。`artifacts/j3-w67-walkthrough/two-run-comparison.json` — SHA-256 `402069a26fd8731b795c2c15397c2f6b4782b8791b6e845d9fc660f157fb88c3`。比較使用固定 observable state schema；原始所有 API、隨機 run／decision ID、時間、輸出路徑均保留於 receipts。腳本 exit 0 只代表收據流程完成，不代表各步 PASS。

腳本 `web/e2e/w67_walkthrough.py` — SHA-256 `56bfb71f5b637a4a7e3700765048e825a6a202105bc3f2bc0453b45a47ecaaf6`；故障腳本 `web/e2e/w67_fault_jobs.py` — SHA-256 `48562c44441822fae5ed32ead34afa045f2d3695b3b669873e6120684c63a3c3`。final-1／final-2 使用修正後同版腳本連續執行；較早 diagnostic 與 run-1／run-2 留存為診斷，後者跨腳本版本，不作重現接受證據。各次隔離收據中的 runner SHA 核對實際執行版本。

run 1 `artifacts/j3-w67-walkthrough/final-1/summary.json` — SHA-256 `fae44e68ee3c1505d322f8aa42be34c4b79bb89c45811d6925f3d09860386ae4`；run 2 `artifacts/j3-w67-walkthrough/final-2/summary.json` — SHA-256 `1f6b0d9e8d27d70314a6d9578019b3366caa677529554f6de608225a03ffdbb6`。

| 步驟 | run 1 | run 2 | 範圍 |
|---|---|---|---|
| 2a | PASS | PASS | r4 南側集散道路；5 真實方案、幾何 SHA、確定性 validator |
| 2b | PASS | PASS | 臨時測試金鑰；1 accepted、4 rejected，各附理由 |
| 2c | PASS | PASS | 舊 grid-mixed baseline 對新的 accepted r4；Founder 指定三日／08–18／15min／5m E1 |
| 2d | PASS | PASS | 正式草稿 remove_floor＋SPLIT_LINE；未把草稿變 accepted |
| 2e | INCOMPLETE | INCOMPLETE | 原 E1 未進入草稿 e1_statuses，無 STALE 證明 |
| 2f | INCOMPLETE | INCOMPLETE | W7 execution_scenario_mismatch 409；獨立 W6 新 plan run 完成，原結果不覆寫 |
| 2f-e2 | PASS | PASS | 本地雙引擎、12 method/scenario/offset 結果；臨時批准，PD08 假設與 FIXTURE_ONLY 資格保留 |
| 2g | PASS | PASS | 七個 API panel：map/model3d/dashboard/ai/chart/export/compare，同 revision；非瀏覽器 |
| 2h | INCOMPLETE | INCOMPLETE | 8 faults × generation/E1/E2，實際 job 與 handler；逐格判定 |
| 2i | PASS | PASS | 5 個重新考慮→新選定；歷史 revisions 保留 |
| 2j | PASS | PASS | 修改後 formal draft 的平面／透視／等角／E1／E2 真實資料 PNG；逐檔 SHA，未把草稿提升為 accepted |
| 2k | PASS | PASS | 關閉再建立 store/app，選定與 revision 恢復；非重啟正式 server |

狀態差異總數 10；下表列實際差異，不加容差：

| path | run 1 | run 2 |
|---|---|---|
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/-1/baseline_kwh_m2 | 401.2539439532923 | 401.32371621772273 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/-1/delta_kwh_m2 | 0.045714562945136095 | 0.023421449983800358 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/-1/modified_kwh_m2 | 401.29965851623746 | 401.34713766770653 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/0/baseline_kwh_m2 | 403.47601163606816 | 403.44667993037 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/0/delta_kwh_m2 | 0.03003222739408784 | 0.05402333859461805 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/0/modified_kwh_m2 | 403.50604386346225 | 403.5007032689646 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/1/baseline_kwh_m2 | 399.0476895651336 | 399.05535860120295 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/1/delta_kwh_m2 | 0.06262807226426048 | -0.05208925079159599 |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/1/direction | INCREASED | DECREASED |
| /core/steps/2f-e2/summary/comparison_statistics/honeybee_radiance/1/modified_kwh_m2 | 399.1103176373979 | 399.00326935041136 |

r4 五方案的本輪 deterministic metrics（保留樓層／GFA 估算與 D2 land_area 假設，不是觀測容積率）：

| recipe | family | candidate gate | FAR | coverage ratio | open-space ratio | max new height m | land denominator m² |
|---|---|---|---|---|---|---|---|
| grid-mixed | CONNECTED_GRID | VALID | 0.757951160299418 | 0.15672299457890548 | 0.6926423407786065 | 17.5 | 183591.328035937 |
| common-mixed | CENTRAL_COMMON | VALID | 0.74333312779887 | 0.1537993880787959 | 0.6864923567860982 | 17.5 | 183591.328035937 |
| spine-mixed | LINEAR_SPINE | VALID | 0.7350160465056041 | 0.1521359718201427 | 0.7312903022642063 | 17.5 | 183591.328035937 |
| grid-fine | CONNECTED_GRID | VALID | 0.7717295888722476 | 0.15947868029347143 | 0.6807072844587273 | 17.5 | 183591.328035937 |
| common-compact | CENTRAL_COMMON | VALID | 0.7657761224876649 | 0.17781014309193688 | 0.6801968893855705 | 14.0 | 183591.328035937 |

每一個限定 PASS 的收據（run 1 與 run 2 均列 SHA；不以 worker 回報代替）：

- run 1 / 2a：`artifacts/j3-w67-walkthrough/final-1/2a-generation-report.json` — SHA-256 `87fd99f3d9fb2ff10ea4200aa20bb78a500c27070dd9f5f1ff120c206889c9d1`
- run 1 / 2b：`artifacts/j3-w67-walkthrough/final-1/2b-selection.json` — SHA-256 `1ec9ec7bd597f01ede7de39594300fa784a6de04b9650b1320dc83f1e57204ea`
- run 1 / 2c：`artifacts/j3-w67-walkthrough/final-1/2c-e1.json` — SHA-256 `ce0ef73870f502974062ea18e802952692b32f2d06c1e607e50ec9abf704bd8e`
- run 1 / 2d：`artifacts/j3-w67-walkthrough/final-1/2d-massing.json` — SHA-256 `56fa190d71ec8e87a1c84c6532de0404c1e1481d579d6554ddca2aa026586cf5`
- run 1 / 2d：`artifacts/j3-w67-walkthrough/final-1/2d-split.json` — SHA-256 `fc4ac40fa9a2a630a0e5de27e7e9fee73f7a73937bd5c3b4d879ca485e0bc6d1`
- run 1 / 2f-e2：`artifacts/j3-w67-walkthrough/final-1/2f-e2-run.json` — SHA-256 `e076b4e582974f06532ac30bb5ed0c3f561dffdd8ed24726e24d3bd4c3a4874a`
- run 1 / 2f-e2：`artifacts/j3-w67-walkthrough/final-1/2f-e2-qualification.json` — SHA-256 `cb1387d5165660424d9108c34be60ad62d6b85b6075c42c2782a12731bdd3f01`
- run 1 / 2g：`artifacts/j3-w67-walkthrough/final-1/2g-panels.json` — SHA-256 `91b1ba8fb6e07dbea0702303ed9ebaea31638722251d14b34ad0ddee1f7e218a`
- run 1 / 2i：`artifacts/j3-w67-walkthrough/final-1/2i-reconsider-0.json` — SHA-256 `3f1377acc694ea038195cfe67135306cafc91d06c7f39186ff708cb7ab1a2d90`
- run 1 / 2i：`artifacts/j3-w67-walkthrough/final-1/2i-reconsider-1.json` — SHA-256 `79b2ec4708ee843c3b683206442d65020ff1ccd093394b364a624ea5d6b1368e`
- run 1 / 2i：`artifacts/j3-w67-walkthrough/final-1/2i-reconsider-2.json` — SHA-256 `92d4a2acef3bb0d08c62a152da041ddf86795943568623e960a8acf5d1973887`
- run 1 / 2i：`artifacts/j3-w67-walkthrough/final-1/2i-reconsider-3.json` — SHA-256 `74f490cee8b0f179914bef68eac03bcfb06f90644f0ef37cf1614cb45fec6f11`
- run 1 / 2i：`artifacts/j3-w67-walkthrough/final-1/2i-reconsider-4.json` — SHA-256 `c74cd2dba88ff8023848dcf309fe952b5f7a6c9abf8ab77b855615ff1d18f84f`
- run 1 / 2i：`artifacts/j3-w67-walkthrough/final-1/2i-reselect.json` — SHA-256 `ea67c813a647f8e7f7a59d9336dc23f4cabfd30865243947aba1dfb60e54e309`
- run 1 / 2j：`artifacts/j3-w67-walkthrough/final-1/2j-figures.json` — SHA-256 `74e2606a6ab04f8778eda50ef38d791ecffe20ffbfb1c8ac70ba42bbb4c103d4`
- run 1 / 2k：`artifacts/j3-w67-walkthrough/final-1/2k-before-close.json` — SHA-256 `546389c6bcec0f3d57b42097184ef3005478fc51c8b93b618d1a5f04c2813339`
- run 1 / 2k：`artifacts/j3-w67-walkthrough/final-1/2k-after-reopen.json` — SHA-256 `0dbe83196d0059528174b9b99d963553d891c0804629c60f385ec973a12a168e`
- run 1 / plan PNG：`artifacts/j3-w67-walkthrough/final-1/plan.png` — SHA-256 `960c0c7d393ddf68fabcaa528c0fa5bd3388d8e3a3afa1018be691a1dba166a1`
- run 1 / perspective PNG：`artifacts/j3-w67-walkthrough/final-1/perspective.png` — SHA-256 `4f05238d9ff6238b4e7997bed518bb931af1d5022d74c622097a25c899a6bf93`
- run 1 / axonometric PNG：`artifacts/j3-w67-walkthrough/final-1/axonometric.png` — SHA-256 `cd10e51d2aef7aceab8a7874a1811a01f013c192d1b7fbc14ad7f21d73b19739`
- run 1 / e1 PNG：`artifacts/j3-w67-walkthrough/final-1/e1.png` — SHA-256 `14a438211ac76c9e532179dc78c931460dda174db0a6a7dc0b8e6370015b18b7`
- run 1 / e2 PNG：`artifacts/j3-w67-walkthrough/final-1/e2.png` — SHA-256 `26ce51d90c436f66813e75eea7605f77ebac51950d015199094e5bd3786bab39`
- run 1 故障矩陣：{'INCOMPLETE': 2, 'PASS': 22} / 24；`artifacts/j3-w67-walkthrough/final-1/2h-fault-matrix.json` — SHA-256 `a5081a67964271364a78e98c32a46eb66bff560fb3df1475fc9758a0ec86113b`。每格收據、輸入 refs、注入點、結果、復原檔案 SHA 均在此與 evidence manifest。
- run 2 / 2a：`artifacts/j3-w67-walkthrough/final-2/2a-generation-report.json` — SHA-256 `1d5ef77ac80bff424e0eb1765e283640b86abde9fd559170caf31ab2f38c8834`
- run 2 / 2b：`artifacts/j3-w67-walkthrough/final-2/2b-selection.json` — SHA-256 `7b207b8f2c968d26a6794aa976bdab286529d013bd695f02347828c7562325ab`
- run 2 / 2c：`artifacts/j3-w67-walkthrough/final-2/2c-e1.json` — SHA-256 `50b227a3980fd6183cbcb6d9f8bc6ff02b3b870041fd4e7b72512179d862927e`
- run 2 / 2d：`artifacts/j3-w67-walkthrough/final-2/2d-massing.json` — SHA-256 `c3ca4c42fd1a3cb7166b8752b6b9d226226f93947112fb894d7808d3543990f9`
- run 2 / 2d：`artifacts/j3-w67-walkthrough/final-2/2d-split.json` — SHA-256 `a068cb3447e0b07f25de970b27f6e2a194397ab4775b9166fcec1a57aa05d81e`
- run 2 / 2f-e2：`artifacts/j3-w67-walkthrough/final-2/2f-e2-run.json` — SHA-256 `e556e76799b76c015924d11c398073496d40ee1086986c8b6782dfbadae9592b`
- run 2 / 2f-e2：`artifacts/j3-w67-walkthrough/final-2/2f-e2-qualification.json` — SHA-256 `18042c5b5889036155f90a9be2b57df997c48bf21202b9e67a34d680d2264244`
- run 2 / 2g：`artifacts/j3-w67-walkthrough/final-2/2g-panels.json` — SHA-256 `a8877a42d0d11b60b8e237f2f99495fc681fca13799182ac2cf3885041534fe1`
- run 2 / 2i：`artifacts/j3-w67-walkthrough/final-2/2i-reconsider-0.json` — SHA-256 `a8bf2ea0780f439d606d522a77ce9db37dd5aedbcc2ca5b70d162fb2337bdd87`
- run 2 / 2i：`artifacts/j3-w67-walkthrough/final-2/2i-reconsider-1.json` — SHA-256 `e4a94b3e427ac5a807c07a48583f1c3a6900a7eaee9816d1ca4d61bc15c15a02`
- run 2 / 2i：`artifacts/j3-w67-walkthrough/final-2/2i-reconsider-2.json` — SHA-256 `bc7645666c6b34a70b36ad1f20d6ae637d28e34fa1418d47ebc6b9326266edbd`
- run 2 / 2i：`artifacts/j3-w67-walkthrough/final-2/2i-reconsider-3.json` — SHA-256 `b11a9a64d47f44f7c6ae36cbdcf326e3089da3809cef949e153254cf3ecb7c4f`
- run 2 / 2i：`artifacts/j3-w67-walkthrough/final-2/2i-reconsider-4.json` — SHA-256 `e25dd0cb665c00ab1753f351c60550660b7cfcf715d422b433ce00533920bf10`
- run 2 / 2i：`artifacts/j3-w67-walkthrough/final-2/2i-reselect.json` — SHA-256 `b8863bd639a84937f6a530bdc53ea5b73af90d2d47816beb07618c6872855a83`
- run 2 / 2j：`artifacts/j3-w67-walkthrough/final-2/2j-figures.json` — SHA-256 `41d6ed4e6aba6cc2e4c7569cf156f04a44d0414238986b3983b64ac2e4d1ab20`
- run 2 / 2k：`artifacts/j3-w67-walkthrough/final-2/2k-before-close.json` — SHA-256 `2b94baf93c86106ce5f087ab4796b57a6655cc00b829ab3fda1f9a7de5216b30`
- run 2 / 2k：`artifacts/j3-w67-walkthrough/final-2/2k-after-reopen.json` — SHA-256 `41ca7c02d7bf79dccb33b7c47f8bb32ff0762b418b0d5440511e949e7699ee0e`
- run 2 / plan PNG：`artifacts/j3-w67-walkthrough/final-2/plan.png` — SHA-256 `960c0c7d393ddf68fabcaa528c0fa5bd3388d8e3a3afa1018be691a1dba166a1`
- run 2 / perspective PNG：`artifacts/j3-w67-walkthrough/final-2/perspective.png` — SHA-256 `4f05238d9ff6238b4e7997bed518bb931af1d5022d74c622097a25c899a6bf93`
- run 2 / axonometric PNG：`artifacts/j3-w67-walkthrough/final-2/axonometric.png` — SHA-256 `cd10e51d2aef7aceab8a7874a1811a01f013c192d1b7fbc14ad7f21d73b19739`
- run 2 / e1 PNG：`artifacts/j3-w67-walkthrough/final-2/e1.png` — SHA-256 `14a438211ac76c9e532179dc78c931460dda174db0a6a7dc0b8e6370015b18b7`
- run 2 / e2 PNG：`artifacts/j3-w67-walkthrough/final-2/e2.png` — SHA-256 `a9abd02746d34ec2cc0a12cfbcfa1c43780a5f74d4782a2a1f14759add18886d`
- run 2 故障矩陣：{'PASS': 22, 'INCOMPLETE': 2} / 24；`artifacts/j3-w67-walkthrough/final-2/2h-fault-matrix.json` — SHA-256 `0272325f9f76b95f9efda3b02ba14725d1a007f9e7455de438da2050e591f41c`。每格收據、輸入 refs、注入點、結果、復原檔案 SHA 均在此與 evidence manifest。

run 1 實際故障格（PASS 僅限明列注入邊界）：

| stage | fault | status | actual job | reason | evidence |
|---|---|---|---|---|---|
| generation | source_or_geometry_hash_mismatch | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-source_or_geometry_hash_mismatch.json` — SHA-256 `38d5c19a33f6f4cd02c793b06dfa300066eadbd042d273901aeb7a008522ae7a` |
| generation | observation_source_unavailable | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-observation_source_unavailable.json` — SHA-256 `e2b25ede9df0836e26e5aa6874d12aa90a120a87d2e3795ecc0bf10286df3831` |
| generation | repeated_run | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-repeated_run.json` — SHA-256 `93f44161c05d42f889a45b0e513b7f5a42ed561e74c57cb559df766485ba8636` |
| generation | tool_disconnect | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-tool_disconnect.json` — SHA-256 `b5e025a6f4abd985726e0f074faab920420263b4ff831c7e34e7035f30ae1222` |
| generation | late_b1_after_b2 | PASS | STALE_FOR_CURRENT_CONTEXT |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-late_b1_after_b2.json` — SHA-256 `edc6ab1bfa6253b01be460bf436089802ed36f4d9922a6d30e9cf8fbde2aa07d` |
| generation | refresh_or_restart | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-refresh_or_restart.json` — SHA-256 `3a4736070f3a5c1e8923fec13ae394e15fb835451e6020b54f60bb23c737ad66` |
| generation | partial_publish_db_failure | PASS | READY |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-partial_publish_db_failure.json` — SHA-256 `829b188069679dddcc660d20918943625580305c4e0bcfe75a5e68ff56545db5` |
| generation | ai_wrong_citation | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-generation-ai_wrong_citation.json` — SHA-256 `65def48954ace0f0e8945c61d1df86076bb7b2f397b62ba86d43e506ecb852b5` |
| E1 | source_or_geometry_hash_mismatch | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-1/2h-E1-source_or_geometry_hash_mismatch.json` — SHA-256 `63de1184d929dfd56d42fa0d511340bfe54842fe66cb93c5a132f9b5a35af13a` |
| E1 | observation_source_unavailable | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-1/2h-E1-observation_source_unavailable.json` — SHA-256 `550c65f6977a30189ea8970916b6d77bce60157318545c3735ac21e88c024292` |
| E1 | repeated_run | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-E1-repeated_run.json` — SHA-256 `cc6774fcd42283a1003bbc75d3a18477963a7a75b76672e11459a5ce3f6aec89` |
| E1 | tool_disconnect | INCOMPLETE | FAILED | AssertionError:FAILED | `artifacts/j3-w67-walkthrough/final-1/2h-E1-tool_disconnect.json` — SHA-256 `851b3ab27ce79f48e4f95702598810c7ac9a9dfcbcf3d83eac0f48e77b2b6d35` |
| E1 | late_b1_after_b2 | PASS | STALE_FOR_CURRENT_CONTEXT |  | `artifacts/j3-w67-walkthrough/final-1/2h-E1-late_b1_after_b2.json` — SHA-256 `15e4b43fe4ae3a961ff8d1bf68ddd9a945791ffff653fb08f8769875b31750e6` |
| E1 | refresh_or_restart | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-E1-refresh_or_restart.json` — SHA-256 `d21a2190fc87ae1bd75f85636a5781ed1462bee3ed65c9052b28aedc89d0b394` |
| E1 | partial_publish_db_failure | PASS | READY |  | `artifacts/j3-w67-walkthrough/final-1/2h-E1-partial_publish_db_failure.json` — SHA-256 `d5697d06f27cb9e8c7a4e89a9ac34b476ca30784130cc3e3b2e47bdc5ccfe28a` |
| E1 | ai_wrong_citation | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-E1-ai_wrong_citation.json` — SHA-256 `e7a59cbebcd574be6e0919b8bd05fd4a2eb4cdddd8040317cd620efb59379919` |
| E2 | source_or_geometry_hash_mismatch | PASS | OUTCOME_UNKNOWN |  | `artifacts/j3-w67-walkthrough/final-1/2h-E2-source_or_geometry_hash_mismatch.json` — SHA-256 `6b285dad501159ef7303f438d5981a0f5cca47cd372a51f47b892fc3ff493f4f` |
| E2 | observation_source_unavailable | PASS | OUTCOME_UNKNOWN |  | `artifacts/j3-w67-walkthrough/final-1/2h-E2-observation_source_unavailable.json` — SHA-256 `f0e7159e3fb4f83df6eb4e08e1ed9e9b6ff07452b8f09846b08761835c3ab6d5` |
| E2 | repeated_run | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-E2-repeated_run.json` — SHA-256 `06d06216d7d37fbf44d08c789b9c0b567e552bbe32f865cd5429dc369c1e5c42` |
| E2 | tool_disconnect | PASS | OUTCOME_UNKNOWN |  | `artifacts/j3-w67-walkthrough/final-1/2h-E2-tool_disconnect.json` — SHA-256 `98d8e2f3026c6ce1349dc715647003b289c1c47bc66f278fbd1aa14920c2d569` |
| E2 | late_b1_after_b2 | INCOMPLETE | READY | AssertionError:E2 late changed scenario revision job still READY | `artifacts/j3-w67-walkthrough/final-1/2h-E2-late_b1_after_b2.json` — SHA-256 `baa5347f87c94840cc595c30dc8d5b1f5cdd77964438a50ea3ee09a2ebb48c0d` |
| E2 | refresh_or_restart | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-E2-refresh_or_restart.json` — SHA-256 `67547a4d2cc3d4c50f3f101b718bb182ce68358013a873dc3a414a8ded8303a9` |
| E2 | partial_publish_db_failure | PASS | READY |  | `artifacts/j3-w67-walkthrough/final-1/2h-E2-partial_publish_db_failure.json` — SHA-256 `6d818a4084217d7964149d4aebdee5246b530e2c5523db2de4557292a438a1eb` |
| E2 | ai_wrong_citation | PASS |  |  | `artifacts/j3-w67-walkthrough/final-1/2h-E2-ai_wrong_citation.json` — SHA-256 `aea2ad152bad375ca43aeca3bb88ebab474c8ac88f40f7ba343f63008ff866a5` |

run 2 實際故障格（PASS 僅限明列注入邊界）：

| stage | fault | status | actual job | reason | evidence |
|---|---|---|---|---|---|
| generation | source_or_geometry_hash_mismatch | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-source_or_geometry_hash_mismatch.json` — SHA-256 `8da83789fa1e1cccec45bafee41d244cbaed0902878d61b7c29e7bb0f9e26bd8` |
| generation | observation_source_unavailable | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-observation_source_unavailable.json` — SHA-256 `88eed4c86e36b367cc25cf4be5405d07c7ed36f56d90393d2c05cefca97bbdc5` |
| generation | repeated_run | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-repeated_run.json` — SHA-256 `094a4fae0e57a8a0e40cb466e3d3cf99f4239865a75d0e4d00bb90814a32936d` |
| generation | tool_disconnect | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-tool_disconnect.json` — SHA-256 `55b9e18a53e8c23c2dfd2f072ebddf168b799214ad480a94d1c9696e973b1e02` |
| generation | late_b1_after_b2 | PASS | STALE_FOR_CURRENT_CONTEXT |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-late_b1_after_b2.json` — SHA-256 `817d219c0b2e4b4c64876169b223f78778f0328b669928dde643e87fb511142e` |
| generation | refresh_or_restart | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-refresh_or_restart.json` — SHA-256 `e3a6a11ff39b7e47c77eedc35e8ea41665a5c9c9a0bbdef22cff778b0795ea80` |
| generation | partial_publish_db_failure | PASS | READY |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-partial_publish_db_failure.json` — SHA-256 `530eddc02d76dea864d22fdc37a0b86c8826054631f7c669ab8e138b3b074c2f` |
| generation | ai_wrong_citation | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-generation-ai_wrong_citation.json` — SHA-256 `10eefbb0110fc8658f79e1cc7fb3112fa6d895f26b1e765af508c88573e762c4` |
| E1 | source_or_geometry_hash_mismatch | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-2/2h-E1-source_or_geometry_hash_mismatch.json` — SHA-256 `7c29a076df1916438f101e37f6f43434e791e2bc3ba6dc54105b73015d180c69` |
| E1 | observation_source_unavailable | PASS | FAILED |  | `artifacts/j3-w67-walkthrough/final-2/2h-E1-observation_source_unavailable.json` — SHA-256 `119b687df1e1cb4965a923862e7fe3214d702ceefac2e2bed712faec4b970d37` |
| E1 | repeated_run | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-E1-repeated_run.json` — SHA-256 `74d8e42db85aab9b1cb85662594e9e6035dfd411c07fb37848b128bc879e4a9e` |
| E1 | tool_disconnect | INCOMPLETE | FAILED | AssertionError:FAILED | `artifacts/j3-w67-walkthrough/final-2/2h-E1-tool_disconnect.json` — SHA-256 `7f1c7069cf2a761e1da01aecb7a6fb577fcc01af9a356ec2ddff89d6123b3fdb` |
| E1 | late_b1_after_b2 | PASS | STALE_FOR_CURRENT_CONTEXT |  | `artifacts/j3-w67-walkthrough/final-2/2h-E1-late_b1_after_b2.json` — SHA-256 `c16eb6126a566aabd93b34f3222c5e4513d1373677071ee4253590890fc77617` |
| E1 | refresh_or_restart | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-E1-refresh_or_restart.json` — SHA-256 `526e1d2ae6cfdaee521c3cb6958ff6f8f91d88f6f01b66bf0e871e51dd120e6b` |
| E1 | partial_publish_db_failure | PASS | READY |  | `artifacts/j3-w67-walkthrough/final-2/2h-E1-partial_publish_db_failure.json` — SHA-256 `5d07227a27ef739ceb844a311c1913df51fe94dd32c4e2feb44fada86575bdf8` |
| E1 | ai_wrong_citation | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-E1-ai_wrong_citation.json` — SHA-256 `a1be5fd85c73d359253c87e69494a41cee6bc811b779f352a84c5737fdadf7b0` |
| E2 | source_or_geometry_hash_mismatch | PASS | OUTCOME_UNKNOWN |  | `artifacts/j3-w67-walkthrough/final-2/2h-E2-source_or_geometry_hash_mismatch.json` — SHA-256 `ecaace8b7c7292bb3b2084446447c8fc7b81bbc2dc8752e5d7cacdb6cfd56cef` |
| E2 | observation_source_unavailable | PASS | OUTCOME_UNKNOWN |  | `artifacts/j3-w67-walkthrough/final-2/2h-E2-observation_source_unavailable.json` — SHA-256 `e9210bc70a152fad91996d4fe705e16cda6b03617fb3a2323c792c0a2c17f5e7` |
| E2 | repeated_run | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-E2-repeated_run.json` — SHA-256 `43d3630ebbd7f39cf94f92bafef7287fc0074b05b4f24f3022f3a4231e344d17` |
| E2 | tool_disconnect | PASS | OUTCOME_UNKNOWN |  | `artifacts/j3-w67-walkthrough/final-2/2h-E2-tool_disconnect.json` — SHA-256 `9989296e7a68bcc0da23b157f3d32d4d37ea784ea9d3c4695ceb25df1080f5fc` |
| E2 | late_b1_after_b2 | INCOMPLETE | READY | AssertionError:E2 late changed scenario revision job still READY | `artifacts/j3-w67-walkthrough/final-2/2h-E2-late_b1_after_b2.json` — SHA-256 `37df4b3ba878e1eddb607194e0b11b271e99324f3c36af0baffb021a3a6f4885` |
| E2 | refresh_or_restart | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-E2-refresh_or_restart.json` — SHA-256 `64c3c7de277aa07dbf55acc4a116562331415b8cf1e6f155afba5ac6c2c6e0d9` |
| E2 | partial_publish_db_failure | PASS | READY |  | `artifacts/j3-w67-walkthrough/final-2/2h-E2-partial_publish_db_failure.json` — SHA-256 `14f12d3299b1a771e1bfba6de4d0de8ca16e1100ff1706ff84abc41ad58736b4` |
| E2 | ai_wrong_citation | PASS |  |  | `artifacts/j3-w67-walkthrough/final-2/2h-E2-ai_wrong_citation.json` — SHA-256 `1179100768063eb47fbb1d7ecacc579cd4e13ae728aba7ed58346c2ba342ddaf` |

## 缺陷交接與界線

1. **E1 STALE lineage 缺失**：原 accepted 方案的實際 E1 結果未納入 formal draft 的 e1_result_ids/e1_statuses；量體修改與分面後未證明原結果 STALE。未補造綁定。

2. **W7 Rerun lineage 阻擋**：以原 E1 ToolExecution 對修改後 formal draft Rerun，API409 execution_scenario_mismatch。獨立 W6 fresh plan 計算不替代 W7 走查成功。原 artifact payload SHA 保持。

3. **E1 計算後失聯分類**：真實計算完成、保存 proof 並注入 ConnectionError，job FAILED 而非 OUTCOME_UNKNOWN；沒有重派。**E2 過時 job 狀態**：實際計算後切 B2 並追加 A revision，readiness 不允許重派，job 仍 READY；A 產物保留且未污染 B2，但 STALE gate 不成立。兩項均另寫 defect_for_commander，未修產品碼。

4. 部分發布／DB 失敗的局部測試明列 simulated terminated worker（pid_is_alive 返回 false）與 stale_after_seconds=0，讓副本 recovery policy 立即執行；不是正式 process restart 或 release timeout gate 驗收。產品設定未修改。

5. unavailable 格在 generation 破壞 normalized_source URI；在 E1／E2 破壞實際 scenario geometry Artifact URI。後兩格只證明幾何輸入 unavailable 的 fail-closed，不宣稱已演練氣象觀測 supplier unavailable。AI 格只測 real scenario context 加不存在的引用被 INVALID 拒絕，不宣稱所有錯單位／radius 或 Live AI 都已驗。

6. 故障注入使用 rehearsal instrumentation；失聯在真實計算完成並存證後以 ConnectionError 注入，不冒充實際 QGIS／provider 網路中斷。Generation 是 local nonexternal handler，其 FAILED 判定只有此局部邊界範圍；外部 simulation 的 post-dispatch 要求仍嚴格 OUTCOME_UNKNOWN。

7. E2 的 method qualification 明確 FIXTURE_ONLY；supplier_timing_semantics_proven=false，PD08 hour_end 假設保留。臨時 key 的 plan/weather HumanDecision 只存在 disposable DB，不代表 Founder 的正式批准。

8. 瀏覽器 BLOCKED_SANDBOX_BROWSER：loopback probe 可綁 ephemeral port，但 Chrome 臨時 profile headless startup exit -6；未啟動正式服務、未使用沙箱外繞過。
   `artifacts/j3-w67-walkthrough/browser-chrome-probe.json` — SHA-256 `1d15e0b58a2db86ee7cf775d59ad8ff80d1f6587243042d65421ce4310a62654`。由 Claude 在沙箱外補做七面板、QGIS 同步、互動 3D／編輯／道路操作；TestClient API 不冒充瀏覽器。

E2 重播數值有 10 個差異，其中 +1 h Honeybee-Radiance 的 delta 由 +0.06262807226426048 變成 -0.05208925079159599 kWh/m²，direction INCREASED → DECREASED；原因未判定，不宣告方案優勝、不新增容差或抹去差異。`artifacts/j3-w67-walkthrough/e2-replay-numerical-comparison.json` — SHA-256 `a839ab27b01d938226fd18f9c6234e367b30b3bbf3849e57bdfd4700d56312e6`。

兩輪 weather／geometry／environment pins、grid、period、recipe 與 offsets 相同；獨立 method-validation artifact ID 不同，因此不宣稱 plan bytes 完全相同。`artifacts/j3-w67-walkthrough/e2-replay-input-comparison.json` — SHA-256 `68dd8f5ed46099d1ad8b867c15f01b8606b70f65debdb9a21dccd44811f2d64f`。

## R26 逐條判定

| 需求 | 判定 | fresh 範圍與未完成部分 |
|---|---|---|
| R26-01 | INCOMPLETE | 未新增 QGIS 圈定／同步／可選取 UI 走查；全套 protocol 回歸不替代真實 UI |
| R26-02 | PARTIAL_API | 2g 七面板同 revision，證據上列；browser BLOCKED_SANDBOX_BROWSER |
| R26-03 | PARTIAL_REGRESSION | 凍結資料與生成使用既有保留處置；未重新做互動保留鎖定 |
| R26-04 | PARTIAL_FROZEN_INPUTS | r4 使用既有 D1/D2／分區／約束，未新建／改動正式約束 |
| R26-05 | PARTIAL_OFFLINE | 真實 refs／Evidence 與錯引用負測；Live AI 仍由 Founder 阻擋 |
| R26-06 | INCOMPLETE | 未重算六層正式 Syntax；原 stability／source gates 未由 J3 升級 |
| R26-07 | PARTIAL_REAL_GENERATION | 5 方案 r4 重算、1 選定4駁回有真實副本證據；所有模式／瀏覽器完整驗收未做 |
| R26-08 | PARTIAL_REAL_VALIDATION | 五候選 deterministic quality gate 與土地 FAR；未接受為設計／法律規則 |
| R26-09 | INCOMPLETE | 真實 remove_floor＋分面成功；STALE lineage 缺陷，旋轉／移動／1m側推拉／局部推拉 UI 未驗 |
| R26-10 | INCOMPLETE | 道路 module full regression，未在此走查做真實 UI 節點拖曳、吸附與鎖定 |
| R26-11 | INCOMPLETE | 重新考慮與新選定 append-only 成功；W7 Rerun 缺陷，全部八 contest action 的 UI 未驗 |
| R26-12 | INCOMPLETE | E1/E2 真實計算與出圖成功範圍上列；STALE／Rerun／late job 故障與正式批准未完成 |
| R26-14 | INCOMPLETE | 真實 job 負測矩陣及重現證據上列；全部 fault gate、Live AI、跨 provider review、Founder acceptance 未齊 |

R26-13 非本次要求的逐條表；五種出圖列為限定 artifact 證據，不宣稱整個 R26-13 接受。

```text
WEEK_6: INCOMPLETE

CP_W6: INCOMPLETE

WEEK_7: INCOMPLETE

CP_W7: INCOMPLETE

E2_CORE: INCOMPLETE (real-data dual-engine rehearsal completed; release gate not accepted)

LIVE_AI: BLOCKED by Founder

CROSS_PROVIDER_REVIEW: PENDING

FOUNDER_ACCEPTANCE: PENDING
```

限定圖像檢視證據：`artifacts/j3-w67-walkthrough/final-1-visual-inspection.json` — SHA-256 `8a6810ce43deded87540e8598113622cb8557efbc53410f58c3076e88b743a0a`；`artifacts/j3-w67-walkthrough/final-2-visual-inspection.json` — SHA-256 `7138838f31fdf1f9bf375552798bcba70eeecc3a57a86c4cc787dc29f7aa4924`。每張最終 PNG 有直接檢視或與已檢視檔案相同 SHA 的像素證明；不是 font provenance、numerical 或 browser acceptance。

獨立最終檔案／manifest SHA 與 sqlite quick_check：`artifacts/j3-w67-walkthrough/final-publication-integrity.json` — SHA-256 `4d2be23369c474c147e714fdca05c38ad50c609c530f77d3f8e6aab73de23701`。

完整 evidence manifest：`artifacts/j3-w67-walkthrough/evidence-manifest.json` — SHA-256 `73d45c3bff757c744ee8f174071644803b4f3c79ade113b975b6bfe20d1facd8`。此 manifest 不含自身與之後報告，避免循環 hash。執行者不作獨立接受；請 Claude 檢視事件、原始 API／SQL state／job manifests／PNG，修復缺陷後再跑對應 gate，Founder 另行決定。
