# G12　C1 代理模擬（2026-10-05T00:25Z）

狀態：`DONE_ON_BRANCH`。這是 runbook 的代理走查，`acceptance` 為 `NOT_ACCEPTANCE`。Founder 本人尚未在 QGIS 按 Sync。沒有 HumanDecision，沒有 C1 驗收。

## 模擬

工作樹 `Q5/w6-02-brief`，分支 `wp/w6-01-qgis`。權威資料庫只以 `mode=ro` 備份到一次性副本，伺服器只聽 `127.0.0.1:54321`。這個埠不在 5195、8644、8787、8788、8789、8795、9876。沒有傳 `--ariadne-live`，也沒有設定 `PROJECT_AI_AUTHORIZED`。8788 與 9876 在模擬前後都沒有監聽。

走的是外掛既有函式：`build_platform_sync_payload`、`create_pending_platform_sync`、`validate_pending_sync_revision`、`matching_pending_sync_revision`，以及真實路由 `GET /api/v1/projects/rotterdam-m4h-pilot-project/site-context`、`POST /api/v1/workspaces/sync`、`GET /api/v1/workspaces/workspace-rotterdam-m4h-pilot-project/history`。

| 欄位 | 值 |
| --- | --- |
| proxy_status | SIMULATED，程序結束碼 0 |
| project_id | rotterdam-m4h-pilot-project |
| study_area_id | study-area-rotterdam-m4h-pilot-project-v5 |
| 選取 feature | bag:0599100000035095 |
| expected_workspace_revision | 9 |
| 首次 HTTP | 201，`idempotent_replay` false |
| 重放 HTTP | 200，`idempotent_replay` true |
| workspace_id | workspace-rotterdam-m4h-pilot-project |
| revision / status | 10 / DRAFT |
| source_snapshot_ids | 52 |
| feature_dispositions | 11 |
| actor_kind / actor_session_id | QGIS_PLUGIN / c1-proxy-simulation |
| idempotency_key | c1-proxy-20261005T002511Z |
| payload_digest | 6fa2ccf8a32dca052cfa4a6828ae4e8be3a93ccadfa697353d188e0610c39f76 |
| Approve 事件 | 副本前後都是 3 |
| 截圖 | `NOT_CAPTURED_PROXY_SIMULATION`，前後 hash 都是空值 |
| QGIS | 3.40.5-Bratislava，x86_64，`exitQgis()` 已呼叫，結束碼 0 |
| GeoPackage | 1 feature，bbox `[-10, -10, 10, 10]` |
| MCP server / plugin | 0.14.0，來源是 manifest pin `config/runtimes/qgis-3.40.5-ltr-x86_64-rosetta.json` |
| live MCP / bridge | 都是 false |

收據檔 `docs/w6/c1-proxy-receipt-20261005T0025Z.json`，sha256 `0285517fe91fc43cb5d2e8cb0fdb5360c789a710d6034228adf83c4e910b51e1`，8994 bytes。

權威資料庫 sha256 前後都是 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`，3211264 bytes。副本在兩次同步之後的 sha256 是 `609f4b06c55029da134d0d805053ceeda1deb27a14d30a8ce8b3f5c43b988844`。同步只寫進副本。

## 契約

`build_platform_sync_payload` 與 `SyncRequest` 都要 `actor_kind`、`actor_session_id`。`create_pending_platform_sync` 先前的必填集合沒有這兩欄，外掛的凍結步驟會直接失敗。現在必填集合與 `SyncRequest` 對齊，`actor_kind` 必須是 `QGIS_PLUGIN`，`actor_session_id` 為 1–128 個非空白字元。

## QGIS 收尾

同一副本上先有一次完整 HTTP 走查：201、DRAFT revision 9，smoke JSON 已是 `ok` 且 `exit_qgis_called` true，但 Python 正常返回後 Qt 靜態解構以 SIGSEGV（結束碼 -11）離開。該次不記為 SIMULATED，revision 9 留在副本。腳本改為在 `exitQgis()` 並印出 JSON 之後以 `os._exit` 帶出 smoke 狀態。上表這次重跑是 revision 10，結束碼 0。

## 測試

`tests/test_c1_proxy_smoke.py` 與 `tests/test_m2a02_plugin_launcher.py`：32 passed，1 failed。失敗是既有的 `test_project_has_an_unambiguous_visible_identity`，這個 worktree 沒有 `.urban_design_runtime/rotterdam-m4h-pilot-project.qgs`。斷言沒有放寬，留給 G13。

## 停點

Founder 本人在 QGIS 做一次 Sync。這份收據不能代替該步驟。
