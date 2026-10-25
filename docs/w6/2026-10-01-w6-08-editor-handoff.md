# W6-08 editor bridge 執行交接

模型路由：gpt-6.1-sol，low。正式 adapter 的 authority／hash 邊界為困難但界限清楚的工作，依 Founder 2026-09-30 路由與 W6-08 指定；沒有改模型、沒有外送 review。

範圍：正式 adapter 介面、invalid DRAFT 保存與 gate、Rhino Top 導航的 click→world 回歸。正式 baseline 尚未存在，本包不宣稱 CP6-E、CP6-M、CP6-R 或 CP-W6 PASS。

## 交付

- `FormalEditorAdapter.resolve(store, record)` 是注入的 server 介面；本包沒有 live semantic resolver。W6-6／7 必須從持久化 authority 解析真正 accepted baseline、ConstraintSet、source snapshots，核對每個關係的 scope、狀態、版本與 hash。只傳字串 ID／合法 JSON 不構成批准證據。
- `FormalEditorBinding` 綁 scenario ID、revision、geometry SHA、完整 editor parameters SHA，以及有 revision／SHA 的 decision、constraint、source refs。每次 edit、undo、redo、dashboard 都重新 resolve；沒有 adapter／refs／hash 不一致＝409 BLOCKED／NOT_READY。formal road adapter 尚未實作，明確 BLOCKED。
- fixture guard 留在 `validate_building` 預設路徑。正式輸入保持 FORMAL_DRAFT，不再硬改 FIXTURE_ONLY。正式 adapter 必須先通過 server binding 才使用正式 validator；eligibility 始終為 false。
- invalid draft 仍 append immutable artifact／revision；UI detail validation 同步為 invalid。dashboard 不把 invalid 指標標 VALIDATED，metrics value=null／UNAVAILABLE，whole-site 值不提供。
- 正式 whole-site aggregation 未接入 W6-6 保留建築／zone 語意，所以 site 值留空，`NOT_READY_RETAINED_AGGREGATION`。逐層 GFA 使用 polygon area，沒有 bounding-box 替代。正式接受與分析仍阻塞。
- undo／redo 保留 revision／artifact lineage；重新建立 store 與 app 的 fixture 測試確認 invalid 狀態恢復。
- 獨立 `ScenarioStudioDashboard` 讀 server dashboard，要求回傳 scenario_revision 與 UI 一致；stale response 不显示。原 dashboard 明示本機預覽。新字串為 en／zh-TW，集中在所屬元件。

## 新鮮驗證

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_scenario_editor_bridge.py tests/test_scenario_editing_api.py tests/test_editing.py tests/test_road_editing.py
```

46 passed，1 個既有 Starlette／AnyIO DeprecationWarning。測試自建 DB，沒有建立 HumanDecision。

```sh
npm --prefix web run test -- --configLoader runner
```

32 test files／194 tests passed。Rhino Top 測量透過 jsdom 元件的 mouse／wheel handlers：右鍵平移、Ctrl＋右鍵 zoom、trackpad pan／pinch、offset canvas、100.00 m、1000.00 m²、比例尺與自交反例。這不是實際瀏覽器操作，CP6-M 仍待 isolated browser fixture walkthrough。

```sh
npm --prefix web run build
```

TS5033 EPERM：node_modules 為共享位置，tsbuildinfo 不可寫。沒有修改設定檔，改用以下等價 typecheck／bundle：

```sh
web/node_modules/.bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-08-tsconfig.app.tsbuildinfo
web/node_modules/.bin/tsc -p web/tsconfig.node.json --tsBuildInfoFile /private/tmp/w6-08-tsconfig.node.tsbuildinfo
(cd web && ./node_modules/.bin/vite build --configLoader runner)
```

兩個 typecheck 與 Vite build 通過；Vite 保留既有 >500 kB chunk warning。

## 重試與清理

測試先紅再綠：初次 bridge 5 failed（來源硬改 fixture、缺 adapter、invalid metrics），恢復 detail 1 failed（舊 validation 未刷新），dashboard 元件初次缺檔，再實作。adapter artifact SHA 嚴格檢查曾揭露 fixture 原 geometry SHA 與 raw Artifact SHA 不同；正面 formal fixture 明確用 Artifact SHA，不更動 production fixture 舊資料。

build 的原指令因 EPERM 失敗；首次 `npm --prefix web exec -- vite build --configLoader runner` 執行 cwd 是 repository，無 index.html 而失敗；改在 web cwd bundle 成功。保留 /private/tmp 的輔助編輯腳本與 typecheck cache；沒有刪除任何檔案／目錄，沒有起停伺服器，沒有埠操作。預存 `.venv` 未追蹤項保留且不 stage。没有讀寫正式 runtime DB、憑證、EPW，沒有付費／Live AI，沒有外送 review。

## 尚未完成

正式 baseline／批准 inputs＝NOT_READY；live semantic resolver、保留建築與 zone aggregation、formal road adapter、正式接受／分析、實際瀏覽器 CP6-M、正式重啟 CP6-R、Claude 跨供應商 review／Founder 接受均待後續，不以 fixture 通過替代。

## 整合步驟

1. `api.py:378` 已經透過 `register_scenario_routes(app, store, root)` 註冊 editing routes；`scenario_api.py:438` 已呼叫 `register_scenario_edit_routes(router, store, root)`。不要再次 include 相同 router 造成重複 routes。W6-2 integration owner 在現有註冊鏈傳入真正 W6-6／7 resolver：`register_scenario_edit_routes(router, store, root, formal_adapter=resolver)`；必要時為 `register_scenario_routes` 增加 keyword 並由 api.py 傳入。本包未改 api.py／scenario_api.py。
2. `App.tsx` 在 Refine stage 放現有 `ScenarioStudio`，props `apiBase`、選定 `scenarioId`、`shellViewMode`；不可將 stage selection 視為批准。ScenarioStudio 已內含 server dashboard；它傳 `apiBase`、`scenarioId`、`buildingId`、`scenarioRevision`。若只需獨立 projection，可在同 stage 直接放 `ScenarioStudioDashboard` 並傳同四 props。本包未改 App.tsx。
3. Resolver 逐次驗證目前 persisted refs 與完整 parameters hash，重新啟動後由同一 authoritative baseline 和 draft history 恢復；不從 client approved flag、stage selection 或 preview 推出批准。正式 source/constraint 不能解析時維持 BLOCKED。

## 最終提交與 root 覆核補充

root 新鮮覆核重跑 Python：46 passed；Vite build 通過。標準 `npm --prefix web run test` 在共享 node_modules 的 `.vite-temp` 遇 EPERM；使用 `--configLoader runner` 作 sandbox fallback，沒有改設定檔。

本次精確列出本包檔案的 `git add` 與 `git commit` 均因無法在 `/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-08-editor/index.lock` 寫入而失敗。該 git metadata 在 writable roots 外；沒有 bypass、沒有再次嘗試提交。沒有 stage，沒有新 commit SHA。工作仍留在 `wp/w6-08-editor` 的未提交 diff；原 HEAD 為 `6bb2d9f3a0598a1433873fe628fc01923edc05d5`。預定 commit 訊息為 `Add guarded formal editor bridge and Rhino measurement regressions`，末段 `Co-Authored-By: gpt-6.1-sol`。
