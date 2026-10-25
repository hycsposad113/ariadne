# C1 QGIS 實機重驗操作手冊（W6-1）

**依據：** [修正計畫 C1](../superpowers/plans/2026-09-25-control-tower-correction-plan-zh.md)、[Week 4 收尾執行計畫 WC-5](../superpowers/plans/2026-09-25-week4-closeout-plan-zh.md)、[決定紀錄 PD-14](../decisions/2026-09-25-plan-decisions-zh.md)。
**目前狀態：** Runtime 檢查 `PARTIAL`；C1 `BLOCKED（待 Founder 親自 Sync 並提交收據）`。
**人類權限：** 依 PD-14，代理不得透過 Computer Use 模擬或代替設計者點擊 QGIS。下列 Sync 必須由 Founder 本人操作。此流程不批准設計方案，也不建立 `HumanDecision`。

## 1. 已確認的 Runtime

- 主機為 macOS `arm64`；`/Applications/QGIS-LTR.app` 是 Intel `x86_64`，版本為 `3.40.5-Bratislava`，build `8d6d1b54486`。Rosetta 2 已由 Founder 重新安裝；QGIS process 與其 Python 透過 `arch -x86_64` 可執行，QGIS Python 為 3.9.5，`qgis.core` 可匯入。
- 釘選資料見 [`config/runtimes/qgis-3.40.5-ltr-x86_64-rosetta.json`](../../config/runtimes/qgis-3.40.5-ltr-x86_64-rosetta.json)。runtime 已在本機，不需下載；本次未安裝或下載任何項目。
- QGIS MCP server 與 plugin 版本都必須是 `0.14.0`。PROJ 資料目錄為 `/Applications/QGIS-LTR.app/Contents/Resources/proj`；獨立檢查 QGIS 時要設定 `PROJ_LIB` 指向該目錄。
- 正式 Bridge `8788` 與 QGIS MCP `9876` 由 `Open Urban Design QGIS.command` 啟動。這兩個服務目前由 Founder 的既有 QGIS session 管理；**不要再執行 launcher，也不要啟停或重啟 `8788`、`9876` 或其他既有服務**。本次未連線或改動正式 listener。

## 2. Rosetta 前後檢查

目前 worktree 沒有保留前次五項檢查的逐項終端輸出。依 Commander 於 2026-10-03 核實的環境變更，前次共同阻塞原因是 Rosetta 未安裝；下表把逐項歷史結果標為該次共同阻塞，不宣稱保存了不存在的舊 log。

| 檢查 | Before（前次） | Now（本次結果與命令） |
|---|---|---|
| arm64 主機與 x86_64 QGIS 的相容組合 | Rosetta 缺失，Intel runtime 無法執行 | **PASS（架構識別）**：`uname -m` → `arm64`；`/usr/bin/lipo -archs /Applications/QGIS-LTR.app/Contents/MacOS/QGIS` → `x86_64`。 |
| Rosetta 執行路徑 | Rosetta 未安裝，x86_64 執行被阻塞 | **PARTIAL**：`/usr/bin/arch -x86_64 /usr/sbin/sysctl -n sysctl.proc_translated` 被 sandbox 擋下，回 `Operation not permitted`；但下兩列 QGIS 與 Python 命令在 `arch -x86_64` 下成功，並回報 Python machine `x86_64`。 |
| QGIS process 與版本 | Intel QGIS 無 Rosetta 執行層 | **PASS**：`PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj /usr/bin/arch -x86_64 /Applications/QGIS-LTR.app/Contents/MacOS/bin/qgis_process --version` → `3.40.5-Bratislava`，exit 0。 |
| QGIS bundled Python | Intel interpreter 無 Rosetta 執行層 | **PASS**：`PYTHONDONTWRITEBYTECODE=1 /usr/bin/arch -x86_64 /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 -c 'import platform,sys; print("python="+sys.version.split()[0]); print("machine="+platform.machine())'` → Python `3.9.5`、`x86_64`。 |
| `qgis.core` import | QGIS Python runtime 無法在缺少 Rosetta 時執行 | **PASS**：`PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj PYTHONDONTWRITEBYTECODE=1 /usr/bin/arch -x86_64 /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 -c 'from qgis.core import Qgis; print(Qgis.QGIS_VERSION)'` → `3.40.5-Bratislava`，exit 0。 |

首次未設定 `PROJ_LIB` 的版本／import 命令有 `Cannot find proj.db` 警告；設定上述既有 PROJ 路徑後重跑，警告消失。這些是 runtime readiness 檢查，不是五個 pytest node。現有 launcher tests 未硬編碼「Rosetta 缺失」，因此本次沒有改 launcher 或 tests。

## 3. W6-1 隔離 Geometry Smoke 收據（BLOCKED）

- `src/urban_design/bridge.py` 的命令 allowlist 是 `ping`、`get_plugin_info`、`get_active_layer`、`get_layer_info`、`get_selection`、`export_layer`；不允許任意 Processing。產品層 `QgisMCPFacade` 另有固定操作 `urban.buffer_fixture`，其輸入／參數受限，實作才使用 `native:buffer`。
- 本次以 temp QGIS profile、PROJ 路徑、暫存副本 `qgis_point.geojson`，以及 `distance_m=10`、`segments=4` 執行 `urban.buffer_fixture` 對應的 in-process QGIS Python 操作。這只檢查 facade 政策與 QGIS Processing 執行；沒有啟動 Bridge／MCP，沒有經過 `bridge.py` 命令 allowlist，因此不算 allowlisted bridge transport 驗收。
- 啟動器將 MCP port 固定為 `9876`；為遵守既有 port 邊界，本次沒有啟動第二個 MCP。未開啟正式 runtime DB，也沒有可用的既存 sqlite backup；結果記在新建的 test SQLite，該 DB 不是正式 runtime DB 的副本。沒有呼叫付費服務或寫入正式 DB。
- QGIS 回報 1 個 feature，bbox `[-10, -10, 10, 10]`。GeoPackage `quick_check=ok`，SHA-256 `769bbb922c325299dcc0aee11123187bfc57d4df7481f26b7869002c48b73bd2`。但 QGIS Python 在輸出成功結果後以 `-11`（SIGSEGV）結束，外層 facade 記為 `FAILED`，因此本 smoke **BLOCKED，不可當成 PASS 或 live MCP 驗收**。
- 保留的暫存收據：`/private/var/folders/_t/cqm4x_v56g327tfhswnzhzwr0000gn/T/w6-1-qgis-smoke.Oq4hNFwlnr/blocked-smoke-receipt.json`，SHA-256 `5ac8eef50e19dfa35f1652a024e3f3e3a7ce59dc87bc7a36ddfdb516ea67d784`。其中 test-created DB 的 `ToolExecution` revision 為 `1`、ledger event count 為 `2`、DB SHA-256 `e29b56488c5be18425a1812daf122507a7423bc814c5d2605df8faf308249155`；該狀態為 `FAILED`。未建立任何正式 WorkspaceRevision。
- 本次 in-process smoke 三次嘗試均保留在收據：第一次未接受（原 child exit 未留存，後續診斷確認 runner API 錯誤）；第二次因 runner 呼叫不存在的 `QgsApplication.qgisVersion()` 而 exit 1；第三次輸出正確 geometry 後 exit `-11`。無服務重啟，無正式 DB 寫入，無檔案刪除。由於 SIGSEGV、無正式 DB backup、且未走 bridge command allowlist，W6-1 smoke 維持 `BLOCKED`。

## 4. Founder 親自完成一次 Sync

使用 Founder 已開啟、由正式 launcher 管理的 QGIS session。**不要重跑 launcher**。若視窗不存在、外掛狀態不是 READY，或畫面顯示的 project／StudyArea 不符，停止並保留錯誤畫面；不要改用另一個 QGIS process 或手動呼叫 API。

1. 在 QGIS 外掛面板確認 project 為 `rotterdam-m4h-pilot-project`，並確認 `Backend`、`QGIS MCP`、`Anchor`、`Context` 均顯示 `READY`。確認 QGIS `3.40.5-Bratislava`、MCP server/plugin `0.14.0`。
2. 在已核對的來源圖層（例如 `pdok-bag-pand-m4h` 或已連結的道路來源）選取 1–100 個 feature；確認每個 feature 有穩定來源 ID，且可連到現有 source snapshot。不要把選取或 Sync 解讀成邊界核准或設計接受。
3. 記下目前 UI 顯示的 workspace revision，截取包含 QGIS 選取、外掛狀態與可見本機時間的同步前畫面。
4. Founder 本人只按一次 **Sync Selection to Platform**，等待外掛確認。首次新 revision 預期 HTTP `201`；只有精確冪等重放時才預期 `200`。不要用 curl、SQL 或其他腳本替代外掛請求。
5. 在既有平台頁面 `http://localhost:5173` 重新整理一次，確認同一 project 的新 revision 顯示 `DRAFT`，feature disposition 數量及來源 ID 與選取相符。保存同步後截圖及外掛成功訊息；不按 approve／accept，也不建立 `HumanDecision`。
6. 將證據存到 Founder 指定的 `artifacts/week6-c1-qgis-sync/` 目錄並提交 Commander 審查；Founder 保留最終接受／拒絕權。

### 收據必備欄位

- 執行時間與時區、QGIS 版本／架構、QGIS MCP server/plugin 版本、project ID、StudyArea ID。
- Sync request 的 `expected_workspace_revision`、`source_snapshot_ids`、穩定 feature references、`actor_kind`、`actor_session_id`、`idempotency_key`。不要記錄 token、credential 或任何密語。
- HTTP 狀態碼及完整 `workspace_revision` 摘要：`workspace_id`、`project_id`、`revision`、`study_area_id`、`source_snapshot_ids`、`feature_dispositions`、`status=DRAFT`、`idempotency_key`、`payload_digest`；另記頂層 `idempotent_replay`。
- 新 revision 的 `payload_digest`／SHA-256、來源 Artifact／Snapshot hash、選取 feature ID 對照，以及同步前後截圖的檔案 hash。
- 若平台未回覆，記錄外掛顯示的 `OUTCOME_UNKNOWN` 與 pending request 狀態；不要自行補造 revision 或 receipt。

## 5. 失敗處理與回復

- 按下前發現選取錯誤：清除錯誤選取、重新核對來源；本手冊只授權一次初始 Sync。
- 派送後 timeout／連線中斷：按 `OUTCOME_UNKNOWN` 處理。保留外掛已保存的原 request、同一 `idempotency_key` 與畫面；不要改選 feature、建立新 key、盲目重送或另開服務。先以既有平台 revision/history 對照同一 project、StudyArea、payload digest。無法唯一對應時停止，交 Commander／Founder 判斷。
- 如果錯誤 revision 已經持久化，**不可刪除、覆寫或直接改 DB／ledger**。保留該 DRAFT 與收據；任何修正都是 Founder 另行決定的新 revision，並保留舊 revision lineage。此流程不會自動回滾或建立決策。
- 若確認沒有 request 派送且沒有新 revision，無需回復資料；保留失敗截圖與錯誤訊息後結束。

### Commander 補充驗證（2026-10-03，沙箱外）

- 以 `arch -x86_64 /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3`（`PROJ_LIB` 指向 QGIS 內建 proj）在臨時目錄執行無頭腳本：`initQgis()` → 建立 EPSG:28992 記憶體圖層 → 寫出 GeoPackage（1 feature，bbox `[-10,-10,10,10]`）→ `exitQgis()`，**結束碼 0、無 SIGSEGV**。
- 推論：executor 回報的 `-11` 發生在沙箱內且腳本未呼叫 `exitQgis()`，屬環境／收尾問題，非 runtime 本身故障。之後的 smoke runner 必須在結束前呼叫 `exitQgis()`。
- 本補充僅為 runtime 可執行性證據；**未**經 bridge allowlist、**未**寫入任何 DB，C1 仍待 Founder 本人一次 Sync。
