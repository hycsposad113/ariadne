# W6-A 第五輪：品質修正與副本彩排

狀態：IMPLEMENTED_PENDING_CLAUDE_REVIEW。這是 executor 的新鮮驗證，不是跨 provider review、Founder acceptance、main merge 或部署。

執行範圍：本 session executor；依任務指定的困難工作路由 gpt-6.1-sol / low，沒有啟動額外模型程序、背景工作或子代理。沒有 Live AI、下載或新依賴。

## 修改

- `formal_pipeline.py`：五個正式 recipe，要求三種拓撲、有效案任兩案道路／街廓差異 ≥0.1 且至少兩項實質差異；總 FAR 0.70–0.80、五區有 GFA、每案 ≥2 型態、合計 ≥4 型態。
- `formal_placement.py`：完整 envelope 搜尋與 packing，保留道路、水岸帶、既有 footprint 排除；逐層用途按五區偏好配置，五區外最近分區延伸明列 ASSUMED_FROM_PORTFOLIO。
- `legacy_profile_adapter.py`：直接呼叫 W5 `_template_geometry`，不重寫 courtyard、L、bar、point_array；檢查完整 envelope 及型態語意。
- `massing_adapter.py`：支援逐 envelope typed recipe；保留 fixture 路徑，formal massing 版本 v2。
- `skeleton.py`：grid 依真正連通群組接通，不因相鄰 atomic line 零距離提早結束；common approach 端點進入公地 0.1 mm，避免 micrometre noding 後失去介面。連通 gate、證據 validator 均未修改。
- `run_formal_dictionary_generation.py`：補齊每棟型態、GFA 與用途報告；整體 INCOMPLETE 不寫 Scenario，仍保留候選 Artifact。
- `test_formal_dictionary_pipeline.py`、`test_formal_legacy_profiles.py`：品質、重現、FAR、未知 GFA、保留與水岸排除、失敗保存、W5 幾何對照與語意、grid 連通回歸。

既有 height_binding、formal_adapter、resolver 未重寫。D1 v8／D2 A 與 3D BAG hash 綁定沿用；無新增 WorkspaceRevision 或 HumanDecision。

## 彩排與重現

DB：`out/formal-dictionary/fifth-rehearsal-db/state.sqlite3`，由使用者指定 rehearsal DB 以 SQLite backup 建立新副本。舊歷史完整保留。

報告：`out/formal-dictionary/fifth-rehearsal-final/report.json`、`report.md`；核對：`verification.json`、`fifth-rehearsal-db/before.json`、`after-audit.json`、`copy-provenance.json`。out 保留本地，不 stage。

第一次非 dry-run 新增 5 PROPOSED（儲存 enum 值 `proposed`）與 5 Artifacts，actor AGENT_AUTOMATION。第二次非 dry-run 相同 seed 42／輸入：五個 result hash 與 Scenario id 相同，沒有新增版本或事件。全部舊版本、ledger 前綴、舊 heads 保持；原指定副本 bytes SHA-256 保持。

陸地 FAR 分母 183591.328035937 m²（以報告全精度為準）；保留 GFA ESTIMATE 下界 13562.531 m²、上界 68907.884 m²，硬 FAR 取上界。
#5 已拆除 GFA 0／保留空 footprint，以及 20 m 只適用新建與加蓋總高仍標 ASSUMED_COMMANDER。無加蓋候選。

| 策略 | Scenario id | FAR | 新建 GFA m² | 建蔽率 | 最高新建 m | 開放空間 |
|---|---|---|---|---|---|---|
| grid-mixed | formal-dict-3da03eb0172d-grid-mixed-f764c233baa3 | 0.7550 | 69703.4 | 15.61% | 17.5 | 69.32% |
| common-mixed | formal-dict-3da03eb0172d-common-mixed-98854aff5f7b | 0.7431 | 67516.4 | 15.38% | 17.5 | 75.12% |
| spine-mixed | formal-dict-3da03eb0172d-spine-mixed-475cd5c6320c | 0.7374 | 66471.5 | 15.26% | 17.5 | 79.67% |
| grid-fine | formal-dict-3da03eb0172d-grid-fine-18c292b0c44c | 0.7739 | 73171.2 | 15.99% | 17.5 | 68.03% |
| common-compact | formal-dict-3da03eb0172d-common-compact-a1ff97864a21 | 0.7644 | 71436.0 | 17.75% | 14.0 | 74.37% |

五區均非零，住宅偏好區住宅 75–80%，Maker／Recycle 製造回收 75–80%，Energy 區能源設施 75–80%，Art 區藝術休閒 75–80%；其餘層配置設施／辦公。UNALLOCATED 0%。各區詳細 GFA、每棟型態在 JSON／Markdown。

任兩案道路差異 0.427–1.423，街廓差異 0.068–0.279；均道路或街廓 ≥0.1，且至少兩項實質差異。差異是 symmetric-difference area / max(area)，可大於 1，不是百分比概率。

## 限制與待審

- 全址 portfolio p9 比例是參考而非硬 gate，未宣稱達到該全址比例；p18 無凍結可機讀數值，沒有補造面積。用途配置與最近分區延伸均為待審假設，不改五區權威幾何。
- Point array 採 W5 footprint 能力；字典 tower 案例樓層 6–28 與 D2 的最多 5 層不相容，因此本案明列為 4–5 層點陣量體，不宣稱符合高層 tower 案例。
- 新道路採 primary 14 m／residential 6 m；未生成 secondary class，沒有用其他寬度冒充 D2 的 secondary 10 m。
- Open space 為陸地扣除道路及 footprint 的幾何餘量；不宣稱公共可達或園景已設計。
- 保留 GFA 是寬範圍 ESTIMATE；FAR 值依上界保守核驗，不宣稱既有樓層已實測。
- 無方案核准、接受、整體優勝判定，無舊 10 UNAPPROVED_PREVIEW 升級。待 Claude 跨 provider 獨立 review 與 Founder 最終決定。

## 實際測試

最終 Python 指令（236 passed，1 個既有 Starlette deprecation warning，75.43 s）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_formal_dictionary_pipeline.py tests/test_formal_legacy_profiles.py tests/test_generation_skeleton.py tests/test_fixture_dictionary_pipeline.py tests/test_generation_type_registry.py tests/test_formal_dictionary_preflight.py tests/test_formal_height_binding.py tests/test_formal_source_resolution.py tests/test_generation_context.py tests/test_far_denominator.py tests/test_dictionary_generator.py tests/test_approved_generation.py tests/test_assumed_generation.py tests/test_generation_review_g.py tests/test_morphology_shape_semantics.py tests/test_generation_contracts.py
```

前端：

```sh
npm --prefix web run test
npm --prefix web run test -- --configLoader runner --cache=false
npm --prefix web run build
node web/node_modules/typescript/bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-fifth-app.tsbuildinfo
node web/node_modules/typescript/bin/tsc -p web/tsconfig.node.json --tsBuildInfoFile /private/tmp/w6-fifth-node.tsbuildinfo
# cwd = web
node node_modules/vite/bin/vite.js build --configLoader runner --outDir /private/tmp/w6-fifth-web-build --emptyOutDir false
```

原 npm test／build 因共享 node_modules 寫入 EPERM 未執行成功；runner test 36 files／218 tests passed（5.15 s），兩個 tsc 指令 exit 0，runner Vite build 1930 modules／301 ms 成功；保留既有 >500 kB chunk warning。沒有改 web／tsconfig 設定檔。

彩排指令（兩次 READY）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/run_formal_dictionary_generation.py --database out/formal-dictionary/fifth-rehearsal-db/state.sqlite3 --output out/formal-dictionary/fifth-rehearsal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/run_formal_dictionary_generation.py --database out/formal-dictionary/fifth-rehearsal-db/state.sqlite3 --output out/formal-dictionary/fifth-rehearsal-final
```

## 所有重試／清理

- 保留 `fifth-dry-1`（品質 FAIL／BLOCKED）、`fifth-dry-2`（READY 但 common 兩案骨架重複）、`fifth-dry-3`（common diameter 80 m 後全部 pair 合格），無覆寫或刪除。前三次均指定原 rehearsal copy 且 --dry-run。
- 初輪 formal tests：3 failed／2 passed，原因為 packing 強度不足、極低 FAR 無 envelope 候選狀態、RD transform 邊界 round-off；修正後 5 passed。首批既有 tests 100 passed，第二批 139 passed；最後合併 236 passed。
- 新副本 backup 的 WAL header 缺 sidecars，3 次只讀探查 unable to open database；以 PRAGMA journal_mode=DELETE 正規化新副本一次，未改資料／ledger。之後 store 自行啟用 WAL；稽核用 closed-DB immutable read，不更動 store。
- 首次稽核 assertions 誤用 PROPOSED 大寫及 Scenario entity type；實際 enum 為 proposed、entity type 為 DesignScenario。修正稽核並通過，未改資料。
- 原 npm test／build EPERM 後依授權用 runner／暫存 build-info；一次 npm exec Vite 在 repo root 找不到 index.html，改在 web cwd 後通過。
- 第二次非 dry-run 是相同 seed 的冪等重現檢查，沒有新增 Scenario 或 ledger。
- 沒有人工刪除或清理檔案／目錄，未執行 reset／clean／rebase／push；SQLite 自行管理 journaling 檔。/private/tmp build 與 build-info 仍保留。

## Git 提交限制

git add 九個具名檔案被 sandbox 拒絕：無法在 `/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-06-generator/index.lock` 建立鎖（EPERM）。未重試、未提升權限，沒有 stage 或新 commit；HEAD 保持 f991463。全部修改保留於指定 worktree，完整 review.patch 與 SHA-256 manifest 放在 `out/formal-dictionary/fifth-rehearsal-final/`。
