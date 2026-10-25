# W7 真實資料重接執行報告 — 20261005T185847Z

狀態 **INCOMPLETE，不可據此合併／上線**。OpenAI / gpt-6.1-sol(medium) / sol-w7-real-integration；直接 executor，未委派。分支 wp/w7-real-integration，HEAD e54f778f5012c2bcbee0094e2a87dbdc8bbee241；所有更動未提交。

## 實作與持久化

新增 week7/real_service.py、contracts.py、jobs.py、real_figures.py 與真實 router；舊 router 改存 fixture_router.py、舊 UI 改存 FixtureWeek7Actions.tsx。歷史 fixture 只在 sibling `.week7-fixture.sqlite3` 演練庫建表，正式路由不初始化它。原 week7/service.py 歷史保留。正式 DB 查無 week7_* 表。新 contest／selection／待決判斷走 append_ledger_event，Fork／ModelRun／Figure Artifact 走 ProjectStateStore；ledger無UPDATE／DELETE。job資料仍在現有generation/E1/E2獨立sqlite，僅排程簿記，不能替代權威computed實體。READY job欄位不等同發布完整性通過。

本輪正式 DB 僅mode=ro讀取及sqlite backup；所有寫入在副本。W7 require_write 保留對指定正式DB的拒寫保護；此次沒有批准解除它，正式寫入部署仍需指揮官review。前後hash皆 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`。E2演練副本內accepted／rejected與HumanDecision均為指揮官先前以測試批准建立的既存資料，並非Founder正式決策。沒有建立正式或測試 HumanDecision，也未讀取／產生Founder密語、下載、安裝、付費或Live AI呼叫、綁埠、上線。原 W6 generation/editing/environment/formal檔沒有更動。最新已找到w6_checkpoint7910771為HEAD祖先；依第二次啟動指示沒有merge／切分支。E2只唯讀參考d6a03e7及其真實結果。

改動群組：src/urban_design/week7/{router,fixture_router,service,real_service,contracts,jobs,real_figures}.py；figure_export.py只增加真實renderer入口；scripts/w7_real_drill.py；Python W7測試；web/src/week7/{Week7Actions,FixtureWeek7Actions,Week7StatusBar,surfacesFromWeek7View}及測試；App.tsx、CompareWorkspace.tsx及測試；.gitignore與manifest。本次共用熱點App.tsx新行29、137、154、328、518、530–533、537、911–912、916、927、1276，已寫progress事件；api.py／i18n未改。

`?week7Workspace=`僅import.meta.env.MODE=test可進fixture。正式UI直接以workspace/scenario呼叫真實API。未知結果含network exception、HTTP200 OUTCOME_UNKNOWN及HTTP409 publication refusal都鎖住送出，沒有自動重送。正式Reject／Override只記錄待決事件與Founder入口，不能代Founder決定。Modify與編輯後STALE仍受上述W6前置條件阻擋。

## R26逐條判定

| 條目 | 判定 | 結果與限制 | 證據代號 |
|---|---|---|---|
| R26-01 | INCOMPLETE | 既有 workspace／QGIS 同步未更動。W7 真實實體讀取已接入；沒有正式 QGIS 或瀏覽器同步新驗收。 | scope |
| R26-02 | PARTIAL | 七個 API panel 共用真實 workspace@8／DesignScenario@revision；支援 accepted E2 副本與草稿 lineage。正式 UI 自動進入真實 workspace；map／3D 仍沿用原平台資料。瀏覽器七面板一致性未驗收。 | view |
| R26-03 | INCOMPLETE | 既有 disposition 路徑保持；真實基地圖使用 hash-verified BAG／BGT。保留鎖定的互動驗收未做。 | scope |
| R26-04 | INCOMPLETE | 既有硬限制、偏好與批准入口保持，未批准新約束或改 site。沒有新增正式 HumanDecision。 | scope |
| R26-05 | PARTIAL_OFFLINE | 假 transport 綁真實 EvidenceCard／ToolExecution，核對 revision、單位、方法、freshness、validation_status 與 stated_numbers；拒收私有推理欄位。自由 statement 語義仍需獨立審查，非 Live AI 驗收。 | api |
| R26-06 | PARTIAL_EXPLORATORY | 真實 Syntax bundle／segment values 出圖並標800m、NAIN、EXPLORATORY／BLOCKED_BOUNDARY_STABILITY_UNASSESSED。未宣稱六層正式 Syntax 通過。 | fig |
| R26-07 | PARTIAL | 讀取真實五個正式方案與已存在的決策方案；沒有重跑 generation 或建立決策三。 | view |
| R26-08 | PARTIAL | 五維狀態採實體 validation／HumanDecision／ToolExecution／hash／EvidenceCard 狀態；資料缺少為UNKNOWN。未修改原 validator，也未把 hash 正確等同幾何有效。 | api |
| R26-09 | BLOCKED_ON_W6_DEFECT_A | Modify 直接呼叫 W6 open_formal_draft；accepted 副本回409：D1 study-area acceptance missing or does not match active StudyArea。正式編輯後 STALE 未驗證；未修 W6。 | ops |
| R26-10 | INCOMPLETE | 道路 formal editor 與吸附／拓撲驗證未更動，瀏覽器操控未驗收。 | scope |
| R26-11 | PARTIAL | Inspect／Challenge／Compare／Fork 成功；Reject／Override 留待Founder的append-only理由紀錄，不改計算值。Modify409；Rerun需已批准plan，E2未整合進checkout。 | ops |
| R26-12 | PARTIAL_E2_RESULT_VERIFIED | 真實 E2 honeybee_radiance／ladybug_radiance 同鏡頭、範圍、色階比較圖已產生；169發布檔唯讀完整性通過。E2 dispatch未在本分支驗證。E1 nohup執行無receipt、空log，OUTCOME_UNKNOWN，未重試；E1無新真實圖。 | e2pub |
| R26-14 | INCOMPLETE | 8列故障探針作用於真實refs／現有runner，注入處明列；沒有全generation／E1／E2端到端驗收。Live AI OFFLINE，跨供應商審查與Founder接受待辦。 | fault |

R26-13附記：真實平面、透視、等角、量體、基地、Syntax、E2雙方法比較已輸出SVG／PNG。比較共享相機、extent、ramp，隱藏操控器，標版本、單位、時段。高度缺少顯示footprint並註明；E1資料缺少即拒絕，不以schematic替代。這是確定性幾何投影，沒有新增photorealistic或氣候計算。圖像與來源hash在各manifest；fig、recovery證據如下。

## 八列故障矩陣

| 故障 | 探針結果 | 實際結果 | 覆蓋界線 |
|---|---|---|---|
| source_or_geometry_hash_mismatch | PASS | "artifact_hash_mismatch" | 真實實體副本／既有store實測 |
| observation_source_unavailable | PASS | "artifact_file_unavailable" | 真實實體副本／既有store實測 |
| repeated_run | PASS | {"job_id": "78488032c31345ae87bf3ffc61f5d85f", "created": false, "status": "READY"} | 真實實體副本／既有store實測 |
| tool_disconnect | PASS | {"status": "OUTCOME_UNKNOWN", "repeat_status": "OUTCOME_UNKNOWN"} | Real input refs and existing runner; injected transport, not live E1/E2 dispatch |
| late_b1_after_b2 | PASS | {"selected": "formal-dict-3da03eb0172d-common-mixed-98854aff5f7b", "late_result_excluded": true} | Retained real A results delivered/read after B selection; no engine redispatch |
| refresh_or_restart | PASS | "workspace-rotterdam-m4h-pilot-project@8/formal-dict-3da03eb0172d-common-mixed-98854aff5f7b@2" | 真實實體副本／既有store實測 |
| partial_publish_db_failure | PASS | {"status": "PREPARED", "file_preserved": true, "ready_claimed": false} | Real scene bytes; existing publication contract with bookkeeping fault injection |
| ai_wrong_citation | PASS | ["model_computed_number", "unknown_or_out_of_scope_evidence"] | 真實實體副本／既有store實測 |

8/8探針通過不能宣稱三種engine端到端全部通過。Generation實際既有READY job原request/ref重送為same id、createdFalse；E2實際READY job同樣去重，發布169檔hash／大小、DB refs與manifest一致。工具失聯與partial publication使用真實geometry bytes及既有runner，transport／DB故障是明示注入。late A after B為既有真實A結果在B選取後讀取，非新dispatch。E1沒有執行證明。

## 測試指令與結果

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_week7_real_integration.py tests/test_week7_contestability.py tests/test_week7_version_chain.py tests/test_generation_jobs.py
npm --prefix web run test
npm --prefix web run build
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider --deselect=tests/test_m2a02_plugin_launcher.py::test_launcher_fails_safely_when_8788_is_already_listening --deselect=tests/test_m2a02_plugin_launcher.py::test_bridge_cli_fails_safely_when_default_port_is_occupied
```

最終focused45 passed；web297 passed／51 files；build通過。最終全套：**3 failed, 1867 passed, 6 skipped, 2 deselected, 15 warnings in 1746.82s (0:29:06)**，exit `1`。

僅排除指定兩項，原因原文：**binds protected port 8788 (known test defect, Commander guidance event)**。6個skip為既有測試行為，未新增skip或放寬門檻。

最終失敗：

- FAILED tests/test_m2a03_spatial_policy.py::test_piped_decision_key_stays_on_stdin_when_dev_tty_exists
- FAILED tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema
- FAILED tests/test_week4_r04_amendments_r02.py::test_self_test_returns_status_and_runs_fault_cases_when_upstream_is_valid

第一輪全套4 failed,1863 passed,6 skipped,2 deselected：含/dev/tty、v4 PNG、R04，以及初期新測試誤讀comparison_status（真實契約欄位為status）；該測試已修正，未改比較實作或放寬assertion。第二輪測最終Python版本。BLOCKED_SANDBOX_BROWSER依Commander明示Chrome SIGABRT／不能綁埠；未啟Chrome或產生瀏覽器截圖，留待沙箱外獨立驗收。

補充只讀診斷：同一全套指令另加 `--collect-only` 保存測試順序（verification/w7-final-test-collection.log）；故障演練指令為 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/w7_real_drill.py --root /private/tmp/w7-real-fault-drill-5 --source /Users/jackhsieh/Downloads/TUD/Q5/w6-11-e1/artifacts/e2-execution-r2-20261005T165907Z/copy-state-evidence.sqlite3`。兩次全套均在無tty的前景exec執行，沒有nohup pytest。

## 保留、重試與未完成

456個既有證據檔（165PNG）已從原路徑rename到/private/tmp保存，hash重查0 mismatch。`git rm --cached`明確失敗exit128/index.lock EPERM，因此**index移除未完成**，git目前看到456 unstaged deletions；沒有檔案被刪除。Commander須依w7-preserved-evidence-manifest.json完成git rm --cached及提交。原untracked .venv與w7-browser-20261005T151819Z保留。沒有commit嘗試、push/reset/clean/rebase/merge/branch切換。

所有修正／重試：fixture已完成snapshot的ro backup失敗改用mode=ro&immutable=1；E2 snapshot同理。初期資料探查role=massing誤用，改依真實new_building；EvidenceCard parameters list處理修正。Fork清除繼承baseline_reason等受限制欄位後重測200。English shell／fixture Compare測試初期2fail後修正語言與fixtureOnly區別。comparison測試改讀真實status欄位。出圖方法名稱ladybug_radiation誤用改成真實ladybug_radiance；3D framing重出新檔。故障drill1–3保留，drill4錯用不存在state-evidence.sqlite3而失敗；drill5正確copy-state-evidence.sqlite3完成。最後一次出圖呼叫誤傳.svg導致PNG寫在.svg、覆寫本輪暫存SVG；三份原SVG已從相同hash的新輸出恢復，錯檔保留，renderer新增副檔名拒絕與測試，正式有效檔為final-r2-*.png/.svg。full suite重跑以涵蓋最終Python修正。E1 nohup nice(5) EPERM、零log、無copy DB／exit receipt，ps又被sandbox拒絕；**OUTCOME_UNKNOWN，未重試或宣稱完成**。沒有手動清理／刪除工作區檔案或停止其他程序。既有figure_export.py第91行的PNG renderer會在finally unlink自建暫存.py；未新增或改動該清理，也沒有逐次unlink receipt。此內建清理在本報告明列，不能解讀為完全沒有暫存檔刪除。原始資料、456證據及重出結果皆保留。

剩餘必須由Commander／Founder處理：提供相符D1與正式草稿前置紀錄後驗證Modify／編輯後STALE；E2正式integration與real rerun；E1 reconciliation與核准rerun／真實圖；generation/E1/E2全鏈失聯、late、publication端到端；解除執行護欄與正式寫入policy審查；沙箱外瀏覽器；真實模型語義與Live AI；跨供應商review、Founder acceptance；index removal／commit。沒有宣告overall winner。

## 證據與SHA-256

manifest：`/Users/jackhsieh/Downloads/TUD/Q5/w6-07-compare/docs/w7/w7-real-evidence-manifest.json`，SHA-256 `f50d19185f5250370c086329933f07c414629fb47c997ea50f74d11983ed4491`。僅manifest／hash與報告進git，新圖片、DB、log全在/private/tmp。下列證據檔全部實際存在：

- api: `/private/tmp/sol-w7-real-20261005T174732Z/verification/w7-final-focused-r2.log` (SHA-256 `19bea420b98d086c089baacb31df7bfe867a6ad33df078c292f6c7fedeb3e3e0`)
- web: `/private/tmp/sol-w7-real-20261005T174732Z/verification/w7-web-final-tests.log` (SHA-256 `07f92e741be36f8a4489b33bf5e54d806bc1a85198bf5ea24c39855223c66cca`)
- build: `/private/tmp/sol-w7-real-20261005T174732Z/verification/w7-web-final-build.log` (SHA-256 `4f9c08cbb835afe8f15f1e0226876050a65542a9c8ebbae0c9cbe5369f8449bf`)
- full: `/private/tmp/sol-w7-real-20261005T174732Z/verification/w7-final-full-pytest.log` (SHA-256 `540bbaaecf1ceee5226273a41a7dc28a115dbad9a1a8bdfda0f2e4059f63c2ae`)
- ops: `/private/tmp/sol-w7-real-20261005T174732Z/verification/eight-operations.json` (SHA-256 `37debd20e3e737a1550be073c841514a6dc3fad400c8a902dd8cb04e47a3e2cb`)
- fault: `/private/tmp/sol-w7-real-20261005T174732Z/verification/fault-matrix.json` (SHA-256 `2a8e8636e49fce4aa5392f0122b9294a2cdf73d8f55ec673db033f52c346b9b6`)
- view: `/private/tmp/sol-w7-real-20261005T174732Z/verification/view-before.json` (SHA-256 `76d6cd66b85e0afef3561dd5662784d20d11893cae16a2db3b7820485a3eb431`)
- scope: `/private/tmp/sol-w7-real-20261005T174732Z/scope-audit.json` (SHA-256 `c77427c52be514096a4df0acbd3d33c5f49ec65eccd75261018d07508e47d081`)
- preserve: `/private/tmp/sol-w7-real-20261005T174732Z/preservation-reverification.json` (SHA-256 `9aad0f4ff1f426b243100269b2759f2ab889cdbe23b6dd42dcfa9cfcdc31226f`)
- fig: `/private/tmp/sol-w7-real-20261005T174732Z/final-r2-analysis-exports.json` (SHA-256 `510a1c7dcf1ddc1fdfcf5247a1748f25b03e0c22c366ddddc61bae3cedbc33fd`)
- e2pub: `/private/tmp/sol-w7-real-20261005T174732Z/e2-publication-integrity.json` (SHA-256 `42d1bf3e4162626de0c42a6ac609c02a4a3727bdd8bc9a2d2e89df10b0869832`)
- gen: `/private/tmp/sol-w7-real-20261005T174732Z/generation-real-job-dedup.json` (SHA-256 `eeb7ba90347398ce2746a05d92c723b0f7a73569923a6d4628611bc94ac743ec`)
- recovery: `/private/tmp/sol-w7-real-20261005T174732Z/export-extension-recovery.json` (SHA-256 `36370c5a9a2f92cee6fe648c8f429a2e78f64a512618477a6c80e7a6d0ea4efe`)

## 最終狀態

```text
WEEK_7_IMPLEMENTATION: INCOMPLETE
CP_W7: INCOMPLETE
E2_CORE: REAL_RESULT_EXPORT_AND_PUBLICATION_HASH_VERIFIED / NOT_MERGED / DISPATCH_NOT_VERIFIED
LIVE_AI: OFFLINE_FAKE_ONLY
CROSS_PROVIDER_REVIEW: PENDING
FOUNDER_ACCEPTANCE: PENDING
```
