# W6 road access — executor report (2026-10-03)

分支 `wp/w6-road-access`；基準 `516bbaa`。僅離線生成，沒有 live AI、runtime DB、ledger、HumanDecision、服務或 UI 修改。待 Claude 跨供應商獨立 review 與 Founder 接受。

## 方法與可見假設

`ROAD_ACCESS_RULE_M=40.0`、`ASSUMED_COMMANDER`。依 Commander 提供的 Bouwbesluit 2012 消防入口距離概念，採 footprint 到含半道路寬中心線 buffer 的最短幾何距離；這是入口代理值，未驗證實際入口、通行權或消防路線，不宣稱法規符合。MultiPolygon 取各分離 footprint 最短距離的最大值，因此四棟 point-array 均須通過。計數沿用 BuildingMassing record；一個 point-array 計一個 record。

先對 G2 街廓中超過 40 m 的區域加 connected local spur；從既有道路端點接入，使用 `road_local_width_m`、G2 避障路由、微米 noding、typed graph 和既有拓樸 validator，再重建街廓。主要開放空間、保留 footprint 均作避障範圍。authored settings 同時公開最大 64 個 spur 與最小 1600 m² 遠離道路區域的工程設定；小區域由精確 footprint 過濾處理。

放置只收可達的完整 dictionary footprint，再按原 round-robin/refill 填補容量。最後從 massing 重算 `road_access`；任一棟失敗則候選 `INVALID`，附 failure reason 與 `road_access` FAIL check。參數進入 context hash、recipe version 與 pipeline 回傳 authored settings。Scenario persistence 原已保存完整 metrics，因此無需改動 persistence 或 ledger。

原三拓樸 quality gate、FAR land-area 分母、20 m 新建／加蓋界線、#5 footprint reserved/GFA zero、15 m waterfront 與固定 seed replay 均保留。

## 新鮮離線比較

所有方案後測 `VALID`，overall `READY`；最大距離均 ≤40 m。GFA 下表為新建 GFA；總 GFA 上界另列。

| 方案 | 不可達 records 前→後 | FAR 前→後 | 新建 GFA m² 前→後 | coverage 前→後 | open-space 前→後 |
|---|---:|---:|---:|---:|---:|
| grid-mixed | 0 → 0 | 0.754999 → 0.754999 | 69703.36 → 69703.36 | 15.613% → 15.613% | 69.323% → 69.323% |
| common-mixed | 12 → 0 | 0.743087 → 0.745474 | 67516.42 → 67954.69 | 15.375% → 15.423% | 75.117% → 67.715% |
| spine-mixed | 13 → 0 | 0.737395 → 0.732919 | 66471.49 → 65649.76 | 15.261% → 15.172% | 79.673% → 71.773% |
| grid-fine | 0 → 0 | 0.773888 → 0.773888 | 73171.20 → 73171.20 | 15.991% → 15.991% | 68.028% → 68.028% |
| common-compact | 18 → 0 | 0.764436 → 0.764387 | 71435.96 → 71426.92 | 17.748% → 17.746% | 74.372% → 66.889% |

| 方案 | 總 GFA 上界 m² 前→後 | 後測可達/總 records | 最大距離 m | 道路 edges 前→後 |
|---|---:|---:|---:|---:|
| grid-mixed | 138611.24 → 138611.24 | 21/21 | 37.707278 | 117 → 117 |
| common-mixed | 136424.30 → 136862.57 | 21/21 | 37.674367 | 13 → 57 |
| spine-mixed | 135379.37 → 134557.64 | 20/20 | 38.159734 | 10 → 35 |
| grid-fine | 142079.08 → 142079.08 | 19/19 | 17.707278 | 130 → 130 |
| common-compact | 140343.84 → 140334.80 | 32/32 | 34.206065 | 14 → 79 |

來源（保留於本 worktree）：

- `out/road-access-before-20261003/report.json` SHA-256 `542e95427b2aa3a5b9a0d978f113fff93da027b429b7c2ad4dd639638fd7a899`
- `out/road-access-final-20261003/report.json` SHA-256 `1cb8b198a6238a675bf7d6e88375b33d9f05a3cdd88fdcf27b5969548d0e47b6`
- `out/road-access-comparison-20261003.json`：由前後 geometry 獨立重算可達性，核對後測 metrics。

## 實際指令

基準、最終皆執行下列指令，分別指定 `out/road-access-before-20261003` 與 `out/road-access-final-20261003`：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python scripts/run_formal_dictionary_generation.py --database out/formal-dictionary/fifth-rehearsal-db/state.sqlite3 --dry-run --output <新目錄>
```

只讀既有 rehearsal DB；`--dry-run` 沒有持久化 Scenario 或 Artifact。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/pytest -q -p no:cacheprovider tests/test_formal_dictionary_pipeline.py tests/test_formal_dictionary_preflight.py tests/test_formal_legacy_profiles.py tests/test_formal_height_binding.py tests/test_formal_workflow_service.py tests/test_formal_source_resolution.py
```

28 passed，1 個既有 Starlette/AnyIO deprecation warning，58.34 s。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/pytest -q -p no:cacheprovider
```

完整前景結果：**1632 passed、5 failed、3 skipped、12 warnings，601.71 s，exit 1**。log：`out/road-access-full-pytest-20261003.log`。五個失敗完全對應使用者預先列出的既有 worktree-only failures；沒有新增失敗。實際失敗如下：

- `tests/test_m2a02_plugin_launcher.py::test_project_has_an_unambiguous_visible_identity`：缺少本 worktree 的 QGIS project。
- `tests/test_m2a02_r02_georeference.py::test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path`：同一 QGIS project 缺檔。
- `tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema`：PNG bytes 與 canonical artifact 不同。
- `tests/test_week4_r03_integrity.py::test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit`：缺少 runtime StudyArea source-parent GeoJSON，產生預期之外的 upstream error。
- `tests/test_week4_r04_amendments_r02.py::test_self_test_returns_status_and_runs_fault_cases_when_upstream_is_valid`：upstream 已 BLOCKED，error 並非全都只有 mismatch。

沒有補入 runtime 檔案、修改封存來源或更動上述測試來消除失敗。完整 suite 不宣稱 PASS。

## 重試與保留

1. Red tests：初次新增測試失敗；修正測試 LineString 誤用 AreaGeometryValue，再確認缺少 road_edges API 的預期失敗。
2. 只做 placement filtering：7 項 pipeline 測試 3 failed/4 passed；離線 `out/road-access-after-20261003` 為 INCOMPLETE（common/spine FAR 不足）。沒有降低 FAR gate。
3. 初版 spur：7 項測試 1 failed/6 passed；`out/road-access-after-spurs-20261003` 為 INCOMPLETE，原因為 attachment 路由／sub-mm edge hash collapse。另一次只讀 preflight traceback 診斷，未產生 DB 或 output。
4. 改用既有 width-clear 節點接入：7 passed；`out/road-access-after-node-spurs-20261003` READY。最後公開工程設定並重跑至 `out/road-access-final-20261003` READY。
5. 程序狀態診斷 `ps` 被 sandbox 拒絕（operation not permitted），沒有升權或重試。

沒有刪除、rename、reset、clean、服務重啟或 runtime DB 清理。所有中間 output 均保留；`/private/tmp/road_access_compare.py` 與 `/private/tmp/road-access-governance.txt` 是保留的暫存診斷檔。

## 未完成

Claude 跨供應商獨立 review、Founder 接受、merge／runtime adoption 未執行；本 session 不呼叫外部 AI、不做整合接受。完整 suite 的上述五個既有失敗仍未修復，因超出本 lane 與使用者禁止的 runtime／封存資料範圍。

## Git 提交阻擋

`git add` 與 `git commit -m "fix(generation): enforce formal road access with connected local spurs"` 均失敗：sandbox 拒絕建立 `/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-06-generator/index.lock`（Operation not permitted）。沒有 stage／commit 成功，沒有 commit SHA；分支仍為 `wp/w6-road-access`，HEAD 仍為基準 `516bbaa`。未升權、未重試、未繞過 metadata 寫入邊界。

完整 source/doc/test patch 保留在 `out/road-access-changes-20261003.patch`。修改共五檔：`formal_pipeline.py`、`formal_placement.py`、新增 `road_access.py`、`test_formal_dictionary_pipeline.py`、本報告。
