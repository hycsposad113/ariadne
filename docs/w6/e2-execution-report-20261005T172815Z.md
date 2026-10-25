# W6／W7 E2 第二輪執行報告 — 20261005T172815Z

已完成指定 import 整理與新副本完整演練，提交 Founder 審查。**全套 regression 以實際結果為準；READY_FOR_FOUNDER 是交付狀態，不是 release PASS、正式天氣批准或 CP-W7 接受。**

任務 `sol-e2-execution-r2`，Claude 派工，Founder 2026-10-05 核准；OpenAI `gpt-6.1-sol medium` 直接執行，無委派／模型替換。worktree `/Users/jackhsieh/Downloads/TUD/Q5/w6-11-e1`，分支 `wp/w6-e2-execution`，HEAD `8eaca2a4a06444bde2cbe88c703b96d3c138ee9b`。先讀第一輪報告，保留原檔：`docs/w6/e2-execution-report-20261005T165356Z.md`；SHA-256 `74c87b82ad046ac2460c5a5c262d05fdebd91cf37867143dbc7bee57dcf7cd37`。

## 修改與 Git

產品原始碼只改 `src/urban_design/api.py:411` 一處：一般 `from urban_design.environment.e2_router import router as e2_router` 與 `app.include_router(e2_router)`。其餘新增檔均為本輪演練、API 回應、SQLite／計算證據、測試 log 與本報告；Q5 的 OPERATIONS-LOG.md 僅追加。Patch：`artifacts/e2-execution-r2-20261005T165907Z/implementation.patch`；SHA-256 `4073380318ade9c0437dd4b9372717f5509f8013e69ff4004cf1bd89e71a25fb`。受保護檔案與兩個埠測試未改：`artifacts/e2-execution-r2-20261005T165907Z/final-guard.json`；SHA-256 `66514c7b0f85e5660d9a075253e26dc10f900a5a4090c4d601abeb6104c814d3`。沒有修改其他指定 worktree。

`git add -- src/urban_design/api.py` exit 128，`index.lock: Operation not permitted`。未重試或繞過；**新 commit：無，保留未提交狀態**，HEAD 仍為 8eaca2a。`artifacts/e2-execution-r2-20261005T165907Z/git-stage.log`；SHA-256 `d01f7885d47658715a9fe8096c20a80f585aeac569233e0b7b4abca3cf398ce8`。`git diff --check` exit 0：`artifacts/e2-execution-r2-20261005T165907Z/diff-check.log`；SHA-256 `f891dbdfc0402cd4ba60fab1be3245dfec559c5d7afc7e21b87e795a73d05e5f`。

## 新副本演練

正式 DB 只以 SQLite `mode=ro` 開啟，使用 backup API 建立全新 `/private/tmp/e2-copy-8zqnaptw/copy.sqlite3`。正式 DB 前後 SHA-256 都是 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`；`artifacts/e2-execution-r2-20261005T165907Z/guard-baseline.json`；SHA-256 `f6dd2b1d367a98dbe6392b6cd5e1d93d7cefe10c8a781c07f28fb5cbb0928cec`；`artifacts/e2-execution-r2-20261005T165907Z/final-guard.json`；SHA-256 `66514c7b0f85e5660d9a075253e26dc10f900a5a4090c4d601abeb6104c814d3`。新測試 key 只在此 `/private/tmp` 副本建立、供測試 API 決策，未列印或匯出；沒有正式 HumanDecision、正式 key／密語讀取或生成。

本輪透過 FastAPI TestClient 執行實際 ASGI endpoints，不綁埠。重建 API／store 後 GET 恢復相同結果，另以新 Python process 再驗證。這證明 API 初始化、持久化與結果恢復；未驗證 TCP／Uvicorn 部署啟停。

每個 API 步驟存有 UTC（由 `date -u` 取得）、無測試 key 的 request、HTTP status 與完整 response。以下檔案位於 `artifacts/e2-execution-r2-20261005T165907Z/`：

| 證據 | API | HTTP | SHA-256 |
|---|---|---:|---|
| api-01 | `POST /api/v1/environment/e2/weather/snapshots` | 201 | `7a80ff38627ea45fdbed1279f6ca5afd86b1170f0298d5c79609c0700b24f341` |
| api-02 | `POST /api/v1/projects/rotterdam-m4h-pilot-project/decisions` | 201 | `e83daa7515e92e33daab37122e80f8140f966dd45dfe7ac8409a1e4a7b51ca0f` |
| api-03 | `POST /api/v1/scenarios/comparison/decision` | 201 | `aea4a46b032290e8895ae78c91a6866976d863c9b5de463841ab2af1c6f8efe7` |
| api-04 | `POST /api/v1/environment/e2/plan` | 201 | `1b5ba08194166bf3d2bd19cb5c833bac1c27eacd4af3f9aa07f177ed7eb14530` |
| api-05 | `POST /api/v1/environment/e2/simulate` | 409 | `5066e1511365f0b924c17274b4cf1ce82a59867448023f0c8f2e9b0394e9f6d0` |
| api-06 | `POST /api/v1/projects/rotterdam-m4h-pilot-project/decisions` | 201 | `324b2aed9512d77ee4aa3c20dab33776d2c03dadd501d5ba70df3ec4dd644893` |
| api-07 | `GET /api/v1/environment/e2/readiness` | 200 | `4940a6cfdb8db75c0aec7828972ced756d6bc19fe5cc89c5bd90b1cddd1fe119` |
| api-08 | `POST /api/v1/environment/e2/simulate` | 200 | `ebbe42b071e17d16f2af0e70b22bdc6fa669e96c6423aeac0d36213740672540` |
| api-09 | `POST /api/v1/environment/e2/simulate` | 200 | `6bd896e225a7a48ed0be61f751fdb587c53bf9a12c29a377dd59f0026e2c9519` |
| api-10 | `POST /api/v1/environment/e2/compare` | 200 | `7847569d50e349471562dceee7fd2b5d182dea2172ddcda20cad787504e7a24f` |
| api-11 | `GET /api/v1/environment/e2/results/78488032c31345ae87bf3ffc61f5d85f` | 200 | `61e3f7040362644229695cf661105ae16adb69af505a28925b66ecdf934873ed` |

`api-01/02` 是 snapshot 草稿及副本批准；`api-03` 是比較 API 對兩個原正式 DesignScenario 建立副本測試決策，common-compact accepted、common-mixed rejected；`api-04/05/06/07` 是 plan 草稿、未批准 dispatch 409、副本批准、readiness；`api-08` 計算／發布；`api-09` 重複相同 request；`api-10` 比較；`api-11` API 重建後 GET。完整方法資格驗證、scenario pins 與 plan：`artifacts/e2-execution-r2-20261005T165907Z/completed-drill-context.json`；SHA-256 `e193a07d2fa881d6add44965e1763f4b974abe6ce5febf2b6323eac02ae2b841`。

job `78488032c31345ae87bf3ffc61f5d85f` 成功發布，job store `READY`，十二組結果均 `SUCCEEDED`、十二筆 EvidenceCard 均 `validated`；Artifact bytes hash 與 ToolExecution 關係逐筆核對，紀錄和 hash 在 `artifacts/e2-execution-r2-20261005T165907Z/measurement-summary.json`；SHA-256 `123b75bfa8740402d93c88363de3408a062ebdb10bb4fefd76f1da44c7f6a204`。重複 request 前後 job rows／manifest hash 相同且僅一筆：`artifacts/e2-execution-r2-20261005T165907Z/idempotency-jobs.json`；SHA-256 `2e5999a003480389ebc9d82dcd4731e27d2cdddb8dbb85d2bb80e9666f6233e9`。新 process exact JSON recovery HTTP 200：`artifacts/e2-execution-r2-20261005T165907Z/fresh-process-recovery.json`；SHA-256 `b871857200290b9825a6e17e7381c7b3274c9ef4d9c88a9a53060eb42d9719a4`。

完整 job 約 370 秒（API UTC 起訖差，1 秒解析度）；方法執行秒數使用 monotonic timer，見下表。無 job 超過 30 分鐘，沒有取消、kill 或停止既有服務。演練 harness 已設 1800 秒記錄與 job store `request_cancel`；未觸發。完成證據：`artifacts/e2-execution-r2-20261005T165907Z/completion-receipt.json`；SHA-256 `2390c20dcb12ec46358b119ee8cdcff0f65da17091ec9c18446ed2aaca33340f`。

## 真實測量

六月至八月，5 m E1 common ground grid、0.05 m sensor offset、EPSG:28992，平移至 local metres；hour-end −1／0／+1h 保留 weather values，改時間對位。Recipe／原始 commands、WEA、sky、geometry、distribution 與工具 hash 保存於 `artifacts/e2-execution-r2-20261005T165907Z/calculation-evidence.tar.gz`；SHA-256 `ebe7284a0dcc0d66f7ba3ae6065b4eca9dbb90fddbf72490cb628ae386abc913`。測站天空、平地高度、反射率 0.2、Ladybug patch visibility、Honeybee `-I -ab 2 -ad 2048 -lw 0.0001` 為明示方法設定；不聲稱 NAP 地形或現場微氣候。

| 方法 | offset h | accepted kWh/m² | rejected kWh/m² | 有效測點 accepted／rejected | 執行秒 accepted／rejected |
|---|---:|---:|---:|---:|---:|
| ladybug_radiance | -1 | 390.640519 | 398.890727 | 6041／6212 | 0.904／0.840 |
| ladybug_radiance | +0 | 393.062910 | 401.089859 | 6041／6212 | 0.887／0.879 |
| ladybug_radiance | +1 | 389.025102 | 396.660980 | 6041／6212 | 0.883／0.853 |
| honeybee_radiance | -1 | 399.115869 | 406.672340 | 6041／6212 | 39.037／39.171 |
| honeybee_radiance | +0 | 401.477133 | 408.755933 | 6041／6212 | 38.991／39.019 |
| honeybee_radiance | +1 | 397.473851 | 404.439381 | 6041／6212 | 39.185／38.941 |

各案 total points 9041；方法的面積加權值按各自有效 ground cells 計算。成對比較使用 5901 共同有效點，與兩案各自有效集合的加權值分開保存。兩方法在 −1／0／+1h 都為 `INCREASED`，方向一致，敏感度未反轉；完整比較與 direction_summary：`artifacts/e2-execution-r2-20261005T165907Z/comparison.json`；SHA-256 `d6b0d2e37c6f78e84c42cdc60da049e21429adac81aa615eb71a36d66fe0fa39`。沒有整體 winner；不比較兩方法絕對值，不將較低入射輻射當熱舒適或耗能改善。這是兩個真實正式方案的副本比較，**不是單一形態變數的 controlled refinement experiment**；正式 controlled experiment／Founder 接受仍待辦。

原 EPW、derived EPW、mapping hash 均重新核對且未變：`artifacts/e2-execution-r2-20261005T165907Z/weather-source-reverification.json`；SHA-256 `6a3e225a5fd41b23eda298cbc7243307c89af6aa36c5708bd78c844922a584ef`。公開 exports 僅 allowlist 計算資料夾及兩份 DB 副本，不遍歷或包含 sibling test-key：`artifacts/e2-execution-r2-20261005T165907Z/export-receipt.json`；SHA-256 `46e16f90c5dfd16a1d27c1d18c3337fce7af0ef99e93e9bc7af64b7230150689`。副本 ledger 及 job store：`artifacts/e2-execution-r2-20261005T165907Z/copy-state-evidence.sqlite3`；SHA-256 `9ba97bdbc1b2252d1aa8055c6e449da9b44515c55967c26cdfd99288d531f69e`；`artifacts/e2-execution-r2-20261005T165907Z/job-state-evidence.sqlite3`；SHA-256 `dab5560a524a21cb60dc8936e6c0022db731525650a1096ac10d105f286a497e`。

## 新鮮測試結果

全套命令（前景、plain pipes、無 tty；沒有 background worker）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider --deselect tests/test_m2a02_plugin_launcher.py::test_launcher_fails_safely_when_8788_is_already_listening --deselect tests/test_m2a02_plugin_launcher.py::test_bridge_cli_fails_safely_when_default_port_is_occupied
```

實際：**3 failed, 1816 passed, 6 skipped, 2 deselected, 14 warnings in 1714.63s (0:28:34)**；exit 1。`artifacts/e2-execution-r2-20261005T165907Z/full-pytest.log`；SHA-256 `6ce2df3afa969ade8af95330cc7e40636c437590b30b828c029b34e19576c2bc`。只排除題示兩節點，原因逐字記錄：**binds protected port 8788 (known test defect, Commander guidance event)**。指揮官事件：`/Users/jackhsieh/.local/share/agent-coordination/q5-urban-design/events/20261005T165751Z-3365f968b1e64f0bb7efbea2e346f3b5.json`；SHA-256 `62e6496e3b81973373c680ed5643f4a6431e3aaad26aaf3b4ff7d37733ad4d80`。沒有更改 assertions、門檻或新增 skip；既有 skip 是原 suite 行為。

失敗節點（原樣）：

```text
FAILED tests/test_m2a03_spatial_policy.py::test_piped_decision_key_stays_on_stdin_when_dev_tty_exists
FAILED tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema
FAILED tests/test_week4_r04_amendments_r02.py::test_self_test_returns_status_and_runs_fault_cases_when_upstream_is_valid
```

v4 PNG 是已知 canonical bytes 差異；R04 是 worktree 缺正式 DB 的 upstream failure。本輪不建立正式 DB 替身，也不修它們。第三個實際失敗 `test_piped_decision_key_stays_on_stdin_when_dev_tty_exists` 的 child `/dev/tty` 回 EPERM，是沙箱環境問題，仍計為 FAIL，沒有排除。完整 traceback 保留於上列 full-pytest.log。**有 FAIL 就不能宣稱全套 PASS 或 release eligible；待 Claude／Founder 處理。**

- `npm --prefix web run test`：45 files／279 tests passed，exit 0；`artifacts/e2-execution-r2-20261005T165907Z/web-tests.log`；SHA-256 `0551f1dbd665bd6e91a3b229b0ccba000b2eeb964b8d6daf063989006a9f7323`。
- `npm --prefix web run build`：exit 0，保留 chunk-size warning；`artifacts/e2-execution-r2-20261005T165907Z/web-build.log`；SHA-256 `2e1c7188b912cfa514733ac3c7e59798e62df248bba17585a41360eec33e6588`。沒有 fallback、安裝、下載或設定檔修改。
- 演練／恢復／exports 的實際命令與記錄：`artifacts/e2-execution-r2-20261005T165907Z/commands.json`；SHA-256 `3966bff0be9adcbf95845449f733d801362cf8a3502361e5018b62894132e914`、`artifacts/e2-execution-r2-20261005T165907Z/export.log`；SHA-256 `4f7b4539eda4ac30cc48bc4e12428fb1cfb1e2c8fc9d476cc2df1b469deaa087`。

## 重試與清理

計算派送只有一次，沒有重跑 simulation、另建 job 或 OUTCOME_UNKNOWN 重送。新增 fresh-process harness 首次錯誤使用 `.venv/bin/python.resolve()`，解析 symlink 到系統 interpreter，缺 `osmium`；因此原 drill harness exit 1，不能把該 log 改寫成成功：`artifacts/e2-execution-r2-20261005T165907Z/drill.log`；SHA-256 `66a5f47f7e5c0b1684bc0b04e8e7f688e8112f82eef268704d5b01497eea6628`；`artifacts/e2-execution-r2-20261005T165907Z/restore-process.log`；SHA-256 `3fb720fa32bc06c764a1aecf0d9ab5a4732abb8320ca4c480074d849696d53ac`。核對已成功發布、job READY、既有 API 重建 GET 相等後，只用原 `.venv/bin/python` 路徑重新執行 fresh-process GET，一次成功：`artifacts/e2-execution-r2-20261005T165907Z/recovery-reconciliation.json`；SHA-256 `6069b841167ee115b65461875ba911e3f077aa8210cf8ec80fb708cce1ef5252`；`artifacts/e2-execution-r2-20261005T165907Z/restore-process-retry.log`；SHA-256 `c5b8361f78ba09370ccde8c6d3384fc4f006a7e36a61e5a75281f1dd3b344022`。完整演練的最終結果由 completion-receipt 與新恢復證據支持，沒有隱藏原 harness 失敗。

Git add 一次 EPERM，不重試。沒有刪除、改名、清理檔案／目錄，所有前一輪與本輪失敗 log 保留；沒有 push、reset、clean、rebase、正式 DB 寫入、正式決策、Live AI、付費呼叫、下載、受保護埠操作或其他服務停止。沒有跨 provider 新審查或 Founder 最終接受；這些仍由 Claude／Founder 負責。

全部本輪 artifacts／來源 SHA-256 manifest：`artifacts/e2-execution-r2-20261005T165907Z/evidence-manifest.json`；SHA-256 `c58b0de8bbb2c60bdf77b777abe9fe8fa6ecb4af1f7bf0d179ac70f7f9fb6fff`。READY_FOR_FOUNDER 僅表示可審查交付；上述 regression FAIL、Git 未提交與正式批准仍明確保留。

```text
E2_IMPLEMENTATION / E2_DRILL_ON_COPY / E2_FORMAL: READY_FOR_FOUNDER
```
