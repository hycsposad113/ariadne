# 港埠方案與 mixed：E2 執行指南

此指南對應 `artifacts/w8/e2-harbour-drill/` 的副本演練。副本執行不代表正式帳本已登錄或 Founder 已接受方案、批准實驗。正式操作必須由 Founder 在核對內容後完成決策。

## 證據與邊界

固定來源為 `artifacts/fab1/run-8/harbour_grain-plan.json`。來源規劃檢核 `passed=False` 必須保留；新增幾何 adapter 僅做 E2 環境幾何檢核，`validation.valid=True` 的範圍是 `ENVIRONMENT_GEOMETRY_ONLY`，不能宣稱原規劃方案通過。Founder 的接受決策不會使 invalid evidence 有效，也不會自動拒絕 mixed。來源五項失敗為 `ROAD_WATERFRONT_COMBINED_BUDGET`、`SOUTH_QUAY_SHARED_ALLEY`、`SOUTH_QUAY_FACADE_CONTINUITY`、`BUILDING_STREET_EDGE_3M`、`SOUTH_QUAY_MAX_GAP`。259 棟來源建物中，BAG `0599100000765601` 有 demolished status 與 0 floors 證據，adapter 將其排除於環境障礙物，留下 258 棟；不是替未知高度任意估值。來源 SHA-256 固定為 `88445febe1b657019b9e52d024de978bd628672e244423d1b07480ebfede06dd`。

演練以 SQLite `mode=ro` 連線備份正式 DB 至 `/private/tmp/e2-harbour-copy-*`，只在副本建立測試決策金鑰。正式金鑰不讀取。API 逐筆證據會移除測試密語。正式 DB 前後 SHA-256 與 finally 結果在 `drill-context.json`。演練只派送一次 simulate；失聯或未知結果必須先對帳，禁止再送一次。

使用既有天氣 `snapshot-e2-weather-109b15ff7c739ceb92a161a5` 與方法驗證 `artifact-e2-method-validation-c2ddc895d1ccd8b86f164c07`。mixed 為 baseline，港埠為 modified；沿用夏季 6–8 月、5 m 地面網格、±1 小時敏感度與固定雙層 recipe。兩方法絕對值不能混用；降低入射輻射不等於熱舒適改善。

## Founder 正式步驟

1. 先由 Commander 核對副本結果、原規劃失敗項與程式差異，完成獨立 review。確認正確 checkout 與正式服務身份。
2. 透過正式 API 登錄固定港埠來源；確認產生 proposed（等待你決策的提案）、來源 SHA、幾何 SHA 與環境 SHA，且 HumanDecision 未增加。登錄本身不需要接受決策。
3. Founder 檢視來源失敗及適用範圍後，決定是否使用 generic decisions API 接受港埠；只接受港埠，不送會拒絕 mixed 的雙案比較決策。密語只在終端 getpass 輸入。
4. 從 pin API 重新讀取 mixed 與港埠的最新 revision/hash，確認 mixed baseline、港埠 modified，提出 E2 plan。
5. Founder 檢視所有鎖定設定後批准該 plan 的精確 revision/hash；確認 readiness `dispatch_allowed=true`。
6. 使用唯一 idempotency key 派送一次 simulate。若結果未知即停止並交 Commander 對帳。正式腳本成功後執行 compare，再交 Commander 只讀對帳 immutable artifacts、durable job 與 ledger。重開 store／獨立程序 exact JSON recovery 是本輪副本已完成的驗證；正式腳本不執行該副本驗證，也不重啟服務。

本指南不是正式執行授權、規劃有效性證明或整體 W8 驗收。副本與正式環境的差異，以及正式 Founder 決策與跨 provider review，仍須分別記錄。

## 副本結果

本次副本演練 **PASS**，2026-10-16 07:45:13–08:00:07 UTC；程序 exit 0，simulate 單次派送 823.563 秒。job：`e75be4be477149239eeca1743624b178`，副本：`/private/tmp/e2-harbour-copy-22f8skd0/copy.sqlite3`。登錄前後 HumanDecision 數量相同、初始為 draft（演練時版本；Commander 審查後改為 proposed，見下）；generic 接受港埠後 mixed payload 完全不變。plan 批准後 readiness 通過，compare、重開 store 及獨立程序 exact JSON 讀回皆成功。

共同範圍 4,932 點、122,007.768353 m²。夏季累積入射輻射單位 kWh/m²，以下為 offset 0：

| 方法 | mixed 基準 | 港埠修改 | 差值（港埠−mixed） |
|---|---:|---:|---:|
| Ladybug screening | 403.964148 | 359.970347 | -43.993800 |
| Honeybee-Radiance verification | 411.455453 | 374.118467 | -37.336985 |

兩方法在 -1、0、+1 小時皆為 `DECREASED`，方向一致且敏感度未翻轉。這是各方法內的輻射比較，不能推出整體設計勝出、規劃合規或熱舒適改善。`gendaymtx` 的 unusually bright warnings 原樣保留於 execution log。

正式 DB 前後 SHA-256 均為 `2bff9375952f318a146ca33c57662abf76dd20aa70c37ec1886f4d486ea30955`，finally 核對 unchanged=true。沒有重試、取消或清理。腳本現有既存證據 guard，再執行會於派送前 exit 1（`rerun-guard.log`），不覆寫本次 evidence。

小型可檢閱結果見 `result-summary.json`、`comparison.json`、`drill-context.json`、`fresh-process-recovery.json`、`execution-receipt.json` 與 `evidence-manifest.json`。完整 `full-result.json`（62,922,773 bytes）及 `api-08.json`（62,923,148 bytes）保留本機，由目錄 `.gitignore` 排除，不加入 Git；精確 SHA 與大小見 manifest。Radiance 原始輸出保留於副本目錄，不刪除。root 獨立核對另證實：1 筆 durable job 為 READY、547 個 manifest output files 逐一 SHA 通過、full-result 與 durable result byte hash 一致、compare 內容一致，見 `test-final-artifact-verification.json`。

## 正式終端命令與未完成 gate

Commander 核對正式 API 身份及 checkout 後，由 Founder 自行在本 worktree 終端執行（將 `<已核對的API網址>` 換成 Commander 核對的網址）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python scripts/e2_harbour_formal_run.py --api '<已核對的API網址>'
```

此次工作沒有連接正式 ports、部署或重啟服務。Founder 執行前須由 Commander 確認正式服務已載入新 routes 且可用；本輪未證實這一項。指定既有 E2 suite 結果為 **47 passed、1 failed、1 warning，129.48 秒**；失敗為 `tests/test_e2_formal_wiring.py::test_e2_validation_endpoint_workflow:110`。正式 backup 已有 approved weather，但測試假設 unapproved、預期 HTTP 409，實得 HTTP 200。這個前提差異尚未修正，故不能聲稱全部既有 gate 通過。此最後測試包含 20 項新增測試；另 store＋decision binding 18 項通過（2.08 秒）。測試原始證據見同目錄 `test-*.log` 與 `test-results.json`。跨 provider 的 Claude 獨立 review、Founder 正式決策與整體驗收仍待完成。

## 技術交接

既有 `generation/formal_persistence.persist_results` 依賴字典生成的 report/context；固定港埠來源不是該型態，因此新增 `harbour_registration` adapter。`formal-dictionary-fabric-geometry-adapter-v1` generator prefix 是既有 E2 幾何格式相容契約，provenance 為 `FABRIC_PLAN_E2_ONLY`，不代表重新執行字典生成或規劃 PASS。Commander 審查（Claude）後撤回 `store.py` 的例外：港埠改登錄為 proposed（與既有生成器相同狀態），直接走原本只接受 proposed 的決策規則，核心帳本規則不放寬；登錄測試 20 passed、E2／store／decision 套件 46 passed。E2 數值與登錄狀態無關，副本演練結果仍有效。`e2_service.py` 未修改，以保留既有方法驗證的 runtime fingerprint。文件更新沒有重跑模擬。
