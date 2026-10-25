# W6／W7 E2 執行實作報告 — 20261005T165356Z

**INCOMPLETE；已依 Founder 的「護欄（違反即停）」停止。未上線，未提交。**

執行者 OpenAI `gpt-6.1-sol(medium)`，直接執行，無委派／模型替換。worktree `/Users/jackhsieh/Downloads/TUD/Q5/w6-11-e1`；分支 `wp/w6-e2-execution`；source commit `7910771d23fd5ceb15c364492d671efc9ce097d8`。本報告不是 Claude 的獨立審查，也不是 CP-W7 接受。

## 事故與停止

**FAIL：** 全套命令中的既有 `test_launcher_fails_safely_when_8788_is_already_listening` 實際建立 8788 listener。失敗分支 `listener is not None` 證明綁定成功；測試 `finally` 隨後關閉它。這違反本任務受保護埠規則。執行者應在跑全套前檢查此衝突；沒有再執行該測試，也沒有更改斷言、門檻或加 skip。證據：`artifacts/e2-execution/full-pytest-initial.log`；SHA-256 `5b2c3ef7d74ff214c8902e9b14fe0d8b2e5acb576c41fa52bdb178875c1e7cda`，28–66 行；`artifacts/e2-execution/guard-incident.json`；SHA-256 `8c801c6ee34171b1d6e5d7dcd7d3ffa0caebbf78f42b42049481ee6e39a3a1e0`。

**BLOCKED／已取消：** 只對本 E2 job owner PID 23389 發出 SIGTERM，沙箱回 EPERM；改用既有 GenerationJobStore 的 request_cancel。job `516cea5616434214a2f0415682a52f5d` 最終 `CANCELLED`，演練退出碼 1。runner 保留 staging 與 interrupted marker，未刪檔。這輪數值已產生，但沒有完成發布、重複請求、重啟驗收，所以最新版本完整演練不能記 PASS。證據：`artifacts/e2-execution/guard-reconciliation.json`；SHA-256 `8bb6685228b95a03ed612aa46e20231aa705748ba0ef4c246db7fc8f9649c0b0`；`artifacts/e2-execution/drill-final.log`；SHA-256 `737db2a2380ccd4db2dd40b2afbb0b942760d6870fadb1150fea0d1e464ca49b`。

## 實作與範圍

新增 `environment/weather_snapshot.py`、`e2_service.py`、`e2_router.py`，以及 `tests/test_e2_execution.py`、`test_e2_weather.py`、`test_e2_real_methods.py`。既有檔案只有 `src/urban_design/api.py:411` 增加一行 E2 router 掛載。沒有修改 contracts.py、plan_service.py、router.py、radiation.py、comparison.py、sensors.py，也沒有碰其他指定 worktree。

可審查 patch：`artifacts/e2-execution/implementation.patch`；SHA-256 `68375d8931419e0c13868403d3360950a8a197e1a2e7323dfc45063ccef8a070`。各原始碼與證據檔的完整雜湊：`artifacts/e2-execution/evidence-manifest.json`；SHA-256 `1b91b68bf3a7844c83fdd967c77abf78b1f49b4ea0fe487efe67f8acf2c8d26e`。Git add 回 index.lock EPERM；未再嘗試或繞過。**commit SHA：無；HEAD 仍是 source commit。** 證據：`artifacts/e2-execution/git-stage-blocked.json`；SHA-256 `e76870477b71f095d09e1e517a623e3e728cebc67c59631ad8dc151b2b50e025`。

| 項目 | 狀態 | 實際證據與 SHA-256 |
|---|---|---|
| candidate-01 原始／推導／mapping 三 hash、8760 列、可逆推導 | PASS（fixture／副本） | `artifacts/e2-execution/focused-final-validation.log`；SHA-256 `bee6ab7f3db23d6bbf7f51fff438e48b5393c0b4c605de9bd3f9a7c6acb18367` |
| DatasetSnapshot PROPOSED 草稿、Artifact、最新 HumanDecision bundle hash 綁定 | PASS（副本） | 同上；`artifacts/e2-execution/blocked-copy-state.sqlite3`；SHA-256 `b3a2fa6b9eb36bd4be8b83a3f2c34bb5d12067c23547dea0c83630de53b80156` |
| snapshot hash 改變／拒絕決策使批准無效 | PASS | `artifacts/e2-execution/focused-final-validation.log`；SHA-256 `bee6ab7f3db23d6bbf7f51fff438e48b5393c0b4c605de9bd3f9a7c6acb18367` |
| Ladybug 與 Honeybee 兩方法真實小 fixture、物理能量上限 | PASS | 同上；`artifacts/e2-execution/blocked-calculation-evidence.tar.gz`；SHA-256 `4c5344adfeeb7ecc25259ec569cb068ae39ffb45a8d416f0e35a0999978da3b4` |
| 無天氣批准、無 plan 批准、method drift 時拒派送，不建立 job | PASS | `artifacts/e2-execution/focused-final-validation.log`；SHA-256 `bee6ab7f3db23d6bbf7f51fff438e48b5393c0b4c605de9bd3f9a7c6acb18367` |
| 跨方法絕對值拒絕、共同有效點比較、佔用率／面積覆蓋率 | PASS | 同上；`artifacts/e2-execution/blocked-measurement-summary.json`；SHA-256 `85f73033ef06ead32813bfea1af5a87210a9b25b4db7ef4ee6b74816026bb8dd` |
| ±1h 保持 weather values、改 hour_end 對位；方向反轉標示測試 | PASS | `artifacts/e2-execution/focused-final-validation.log`；SHA-256 `bee6ab7f3db23d6bbf7f51fff438e48b5393c0b4c605de9bd3f9a7c6acb18367` |
| ToolExecution／Artifact／EvidenceCard 保存成功、失敗、OUTCOME_UNKNOWN | PASS（fixture） | 同上 |
| approved snapshot＋plan、bytes、加權計算、domain 關係驗證後才升級 validated | PASS（fixture）；完整方案數值已產生但 job 取消 | 同上；`artifacts/e2-execution/blocked-copy-state.sqlite3`；SHA-256 `b3a2fa6b9eb36bd4be8b83a3f2c34bb5d12067c23547dea0c83630de53b80156` |
| 計算中撤銷 plan → computed card 保留 unverified | PASS（fixture） | `artifacts/e2-execution/focused-final-validation.log`；SHA-256 `bee6ab7f3db23d6bbf7f51fff438e48b5393c0b4c605de9bd3f9a7c6acb18367` |
| 最新版本完整正式方案副本演練／發布後重啟驗收 | BLOCKED | `artifacts/e2-execution/guard-reconciliation.json`；SHA-256 `8bb6685228b95a03ed612aa46e20231aa705748ba0ef4c246db7fc8f9649c0b0` |
| 全套 release regression | FAIL | `artifacts/e2-execution/full-pytest-initial.log`；SHA-256 `5b2c3ef7d74ff214c8902e9b14fe0d8b2e5acb576c41fa52bdb178875c1e7cda` |

Snapshot frozen payload 保留 PROPOSED；API 由最新、當前 hash 綁定的 HumanDecision 解析有效 approved 狀態，沒有代理自行寫入 HumanDecision 的正式路徑。演練只在 `/private/tmp` sqlite backup 副本，以新測試 key 呼叫 HumanDecisionDialog 使用的 `/api/v1/projects/{project_id}/decisions`；兩個真實方案的 accepted／rejected 是先用 `/api/v1/scenarios/comparison/decision` 在副本建立。key 未打印、未匯出；正式 key 未讀取。

E2 API prefix `/api/v1/environment/e2`：weather snapshot 發布／狀態、plan 發布／讀取、readiness、simulate、compare、results。job 沿用 GenerationJobStore／GenerationJobRunner；沒有另建排程。OUTCOME_UNKNOWN 保留且不重送。

## 最新副本的已計算數值（不是完整演練 PASS）

副本 `/private/tmp/e2-copy-t_30u82p/copy.sqlite3`。兩案是原正式 DB 的 common-compact 與 common-mixed；批准、接受、拒絕全是副本測試決策。六月至八月原始 hourly rows，hour_end 與 −1／0／+1h；5 m 網格、0.05 m offset；EPSG:28992，剛體平移到 local metres。拆除 `bag:0599100000765601` 不進遮擋物；未知高度 fail closed。範圍沿用 E1 的 site − water − 建築 footprint，非 legal right of way。

Recipe `ASSUMED_COMMANDER`：ground／building reflectance 0.2；Ladybug Tregenza visibility screening（無建築多重反射）；Honeybee Radiance `-I -ab 2 -ad 2048 -lw 0.0001`；排除 building bottom faces。Radiance 6.0.2 arm64 manifest 與七個所用 executable hashes 在派送前核對，RAYPATH 指向既有 6.0.2 `lib`。本演練按 EPW 測站生成天空、按方案 height above flat local ground 建模，不聲稱 NAP 地形或實測現場微氣候。

Honeybee `--solar --cumulative` 的 `gendaymtx -A` 是平均天空；本 recipe 用 radiometric RGB `0.265074126 0.670114631 0.064811243`，乘回選定 hourly record 數再除 1000。已避開既有 smoke 的照度係數，以及已安裝 CLI 的 multiply-by 型別 bug。原矩陣、命令、場景、WEA、spatial values 全保存。這是新的明示 recipe，不修改舊 smoke 或門檻。

以下每列完整 spatial artifact 的 SHA 在來源 summary 的 records 欄；summary 證據：`artifacts/e2-execution/blocked-measurement-summary.json`；SHA-256 `85f73033ef06ead32813bfea1af5a87210a9b25b4db7ef4ee6b74816026bb8dd`。raw archive：`artifacts/e2-execution/blocked-calculation-evidence.tar.gz`；SHA-256 `4c5344adfeeb7ecc25259ec569cb068ae39ffb45a8d416f0e35a0999978da3b4`。

| 方法 | offset h | accepted kWh/m² | rejected kWh/m² | 有效測點 accepted／rejected | 秒 accepted／rejected |
|---|---:|---:|---:|---:|---:|
| ladybug_radiance | -1 | 390.640519 | 398.890727 | 6041／6212 | 0.901／0.831 |
| ladybug_radiance | +0 | 393.062910 | 401.089859 | 6041／6212 | 0.871／0.880 |
| ladybug_radiance | +1 | 389.025102 | 396.660980 | 6041／6212 | 0.862／0.822 |
| honeybee_radiance | -1 | 399.114416 | 406.667378 | 6041／6212 | 38.339／38.328 |
| honeybee_radiance | +0 | 401.403809 | 408.775578 | 6041／6212 | 38.261／38.303 |
| honeybee_radiance | +1 | 397.377183 | 404.337480 | 6041／6212 | 38.402／38.335 |

各案 total points 9,041；accepted／rejected point coverage 約 0.668178／0.687092，area coverage 約 0.666633／0.685666。權重是裁切到 site 的代表 cell area；公共空間按測點中心判定，coverage 不是精確公共空間面積或法律權利。成對比較共同有效點 5,901；新增佔用 140 點、3500 m² 代表 cell area；所有明細見同一 summary。

**數值觀察：** 兩方法在 −1／0／+1h 都是 INCREASED，方向一致、未反轉；沒有改善的結果照樣保存。各方法只做自己的 baseline／modified 差值，沒有相減兩方法絕對值，也沒有整體 winner。這些輻射數值不能冒充熱舒適、耗能、蓄熱或單一設計變數的因果效應。兩案是不同正式生成方案；本演練不是一個單軸 controlled morphology experiment。Radiance sampling 可能有小幅重跑差異；idempotency 與 restart 驗的是已保存 bytes／結果恢復，不宣稱跨 run bitwise 等同。

## 實際測試

- 最終版本 focused：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_e2_execution.py tests/test_e2_weather.py tests/test_e2_real_methods.py tests/test_environment_formal_e1.py tests/test_environment_plan_approval.py tests/test_radiation_preconditions.py tests/test_environment_comparison.py tests/test_environment_sensors.py`。**51 passed，23.51 s，exit 0**；`artifacts/e2-execution/focused-final-validation.log`；SHA-256 `bee6ab7f3db23d6bbf7f51fff438e48b5393c0b4c605de9bd3f9a7c6acb18367`。包含真實兩方法、批准撤銷、失敗注入（只注入 failure，不提供假 PASS）、OUTCOME_UNKNOWN 不重送、恢復。
- 全套：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider`，無 tty、shell 前景命令，**1815 passed／4 failed／6 skipped，1679.28 s，exit 1**；`artifacts/e2-execution/full-pytest-initial.log`；SHA-256 `5b2c3ef7d74ff214c8902e9b14fe0d8b2e5acb576c41fa52bdb178875c1e7cda`。它在中途版本啟動、收集 1825 項；最終 inventory 是 1827 項，新增／修改 E2 路徑另由 focused 最終重驗，不能宣稱單一凍結版本全套 PASS。6 個 skip 是原測試結果，本次未新增 skip。
- `npm --prefix web run test`：**45 files／279 tests passed，exit 0**；`artifacts/e2-execution/web-tests.log`；SHA-256 `45b25dd62cd09152d7129353645919c419f28ae1401d8de83f08208428d65520`。
- `npm --prefix web run build`：**exit 0**，保留 chunk-size warning；`artifacts/e2-execution/web-build.log`；SHA-256 `3c65a10ba757e25bee38d756b9acf919e98ec0a60ccf5b802689ff138e8b38ee`。沒有修改 web 設定或加依賴。
- `git diff --check`：exit 0。Git add 因沙箱 index.lock EPERM 失敗；沒有 commit／push／reset／clean／rebase。

全套四個 FAIL：

1. `test_m2a02_plugin_launcher.py::test_launcher_fails_safely_when_8788_is_already_listening`：launcher 的 process listing 被沙箱擋住；更重要的是測試本身觸及保護埠，觸發本次停止。
2. `test_m2a03_spatial_policy.py::test_piped_decision_key_stays_on_stdin_when_dev_tty_exists`：子程序 open `/dev/tty` 回 EPERM；即使 pytest 無 tty 仍不能在此沙箱通過。
3. `test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema`：已知 v4 PNG bytes 差異，index 66 不同。
4. `test_week4_r04_amendments_r02.py::test_self_test_returns_status_and_runs_fault_cases_when_upstream_is_valid`：已知 worktree 缺正式 DB 的 upstream 錯誤，使 mismatch-only 斷言失敗。

沒有放寬門檻、改斷言、加 skip、mock PASS 或安裝／下載。沒有再執行受保護埠測試。這四項未修復；跨 provider Claude review／red-team 與 Founder 接受也未完成。

## 正式 DB 與原始資料

正式 DB `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3` 只以 mode=ro 做 backup／讀取；before 與 after SHA-256 都是 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`。最後核對證據：`artifacts/e2-execution/guard-reconciliation.json`；SHA-256 `8bb6685228b95a03ed612aa46e20231aa705748ba0ef4c246db7fc8f9649c0b0`。原 EPW、derived EPW、mapping 的最後 hash 與 candidate packet 相同，列於 evidence-manifest 的外部輸入部分；沒有修改原始 bytes、正式 ledger、StudyArea／保留物或正式決策。

## 重試／清理的完整揭露

所有 attempt 的 log 都保留並列在 evidence-manifest：initial（EPW 副檔名）、second（SensorPoint coordinates）、third（Mesh faces）、fourth（CLI multiply-by bug）、fifth（Radiance matrix header）、sixth（小 fixture）；full（比較決策後 revision 重新讀取缺失）、full-second（錯誤 solar 換算，且執行中 source hash 改變使重複請求被拒）；corrected（完整數值與恢復通過）；pre-promotion final（完整副本 PASS）；latest promotion final（因護欄事故取消）。舊錯誤換算輸出標 superseded-solar-conversion；後續完整版本改名 pre-final-unknown-guard、pre-promotion 保留。沒有盲重送 OUTCOME_UNKNOWN。

較早版本的完整副本真實 PASS 保留於 `artifacts/e2-execution/pre-promotion-drill-context.json`／`pre-promotion-full-result.json`／`pre-promotion-calculation-evidence.tar.gz`，但不當作最新 promotion 程式的完整驗收。最新未發布資料在 blocked-copy-state／blocked-job-state／blocked-calculation-evidence；測試 keys 未匯出。只發出一次 SIGTERM（EPERM）及一次既有 job cancellation；runner 正常保留 staging。未刪檔，未停止或重啟任何既有服務。

`ps` 查詢 EPERM；nohup 啟動顯示 nice(5) EPERM，但後續 DB job state／log／退出檔證明實際執行。最後 latest job 已 CANCELLED／exit 1，沒有另建／重送 job；但 SIGTERM 被拒，既有 handler 在取消請求後仍執行剩餘子命令，直到返回既有 runner 的取消檢查才退出。這是取消響應缺口，不能聲稱即時停下；需在重新授權後修復。

## 依據衝突與待辦

PD-08／原 W6-12 禁止未批准的正式發布／實驗；本次 Founder 授權新增 PROPOSED 發布、讀既有天氣與副本測試，是新的產品執行範圍，沒有把它當正式天氣批准，也沒有修改舊文件或 pause 契約。使用者引用的 AGY report 全文不在此 worktree／project 的指定路徑；缺少執行路徑的事實已由當前 radiation.py 源碼確認，未冒稱讀過該全文。

後續由指揮官／Founder 決定安全的完整測試範圍、處理四個失敗、審查未提交 patch，再安排最新版本副本發布／重啟驗收。本執行者已停工；沒有自行續跑、上線或正式批准。

```text
E2_IMPLEMENTATION: INCOMPLETE
E2_DRILL_ON_COPY: BLOCKED
E2_FORMAL: READY_FOR_FOUNDER
```
