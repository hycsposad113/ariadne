# W6-12｜E2 雙方法提案、依賴報告與 W7 交接

**狀態：** DRAFT／BLOCKED。這份文件與程式只準備前置契約；Founder 尚未撤銷天氣暫停，也未批准 E2 方法或 experiment。不得據此建立正式 run。

## 1. 本包產出與邊界

- `src/urban_design/environment/radiation.py` 只檢查輸入 refs 是否缺漏。refs 是不透明識別字，不會被開啟或解析；此模組不讀 weather file、不解析 EPW、不連接 runtime，也沒有派送函式。
- 暫停狀態在本包固定為 `E2_WEATHER_PAUSE_ACTIVE = True`。驗證結果永遠是 `BLOCKED`、`dispatch_allowed=false`；完整 fixture refs 也不會解除暫停或變成核准。
- `tests/test_radiation_preconditions.py` 只用明確標示的 `FIXTURE_ONLY` refs 和合成 sensor 點。
- 不新增依賴、不產生 HumanDecision、不改 workspace、Scenario、ConstraintSet 或 ledger。

## 2. 依賴報告

| 依賴 | 後續正式執行所需證據 | 此 worktree 可確認的狀態 | W6-12 處理 |
|---|---|---|---|
| Weather snapshot | 已批准的 snapshot ID/hash、來源與時間語義、授權狀態 | Founder 指示天氣暫停；本包不讀 weather file，沒有將 fixture 當成真實來源 | `weather_snapshot_ref` 缺漏時列為 blocker；即使填入 fixture ref 仍 BLOCKED |
| 方法與 experiment | Founder 批准的方法、ExperimentPlan、單一自變項與 comparison domain | HumanDecision＝0；未收到已批准 method／experiment refs | 缺 method 或 experiment ref 時拒絕；不建立 approval record |
| 情境與幾何 | 已接受 scenario revision、幾何與 context hashes | Scenario＝0；workspace rev6 為 DRAFT；zones＝0 | 保留為缺少／未就緒輸入，不補造情境 |
| Sensor 與比較 | Sensor grid hash、期間、sensor occupancy、有效 cell area、method 內 comparison refs | 既有 sensor grid 可記錄排除點；本包補上 sensor-cell 面積總量／有效覆蓋率與被占用面積欄位 | 缺少 area 時輸出 `null`，不以零代替未知 |
| Ladybug runtime | Ladybug/ladybug-radiance 套件版本、method runtime manifest、獨立 recipe/settings manifest 與 hashes | `config/runtimes/` 有 Radiance manifest；本包未查詢或執行本機 Ladybug runtime；該目錄沒有 Ladybug 套件 runtime manifest | 正式包須補齊並驗證方法 runtime manifest 與 recipe；不可由 Radiance manifest 代替 |
| Honeybee runtime | Honeybee-Radiance 套件版本、method runtime manifest、獨立 recipe/settings manifest 與 hashes | `config/runtimes/` 有 Radiance manifest；本包未查詢或執行本機 Honeybee runtime；該目錄沒有 Honeybee 套件 runtime manifest | 正式包須補齊並驗證方法 runtime manifest 與 recipe；不可沿用 Ladybug 的 manifest |
| Radiance runtime | 平台、架構、版本、執行檔 hashes 與現場 runtime 驗證 | `config/runtimes/radiance-6.0.2-arm64.json` 記載 Radiance 6.0.2 arm64；此包未執行 runtime 或重驗執行檔 hashes | 僅列為靜態 manifest 存在；不宣稱現場 runtime gate PASS |
| Material／reflectance | 每種方法使用的材料映射、反射參數、來源、單位、recipe 關係與 hash | 沒有此包可引用的 Founder 核准設定 | 不指定預設值；缺少核准設定即 NOT_READY |

本包不增加 Python、前端或外部 runtime 依賴。validator 只沿用既有 Pydantic domain model。現有 Radiance manifest 是靜態設定檔，不是此任務執行或驗證 runtime 的證據。

## 3. 共同控制清單

任何未來 E2 baseline 與 variants 都必須分別保存並鎖定：

1. Founder 核准的 weather snapshot、來源、時間語義與內容 hash；weather ref 不代表已讀取或已驗證。
2. 已批准 scenario revision、幾何、場址／context、sensor grid、comparison domain 與 ExperimentPlan refs/hashes。
3. 期間、時區、true north、time convention、sensor 定義、座標／單位及計算設定。
4. 方法與工具版本、方法專屬 runtime manifest、Radiance runtime manifest、recipe/settings hash。
5. 材料模型與反射設定的來源、數值／單位、適用表面、版本和方法對應。未核准項目不得以預設材料補足。
6. Sensor `VALID` 與 `EXCLUDED_INSIDE_FOOTPRINT` 點均保留。報告 sensor 點數 coverage 與 sensor cell-area coverage；列出被新量體占用的點 ID 和其面積。sensor cell coverage 不宣稱等於整個 polygon 的幾何覆蓋率。
7. 數值只在相同方法、相同 weather／period、grid 與鎖定 recipe 內比較。跨方法只可報方向一致或不一致，不可相減、合併絕對值或做總排名。

## 4. 兩方法控制清單

| 控制面 | Ladybug／ladybug-radiance screening | Honeybee-Radiance verification |
|---|---|---|
| 角色 | 第一層 incident-radiation screening | 獨立的 verification tier |
| Runtime | Ladybug/ladybug-radiance 專屬版本及 manifest，另記 Radiance runtime | Honeybee-Radiance 專屬版本及 manifest，另記 Radiance runtime |
| Recipe | 使用本方法單獨批准並 hash 的 recipe/settings；本包不指定 recipe 參數 | 使用本方法單獨批准並 hash 的 recipe/settings；不得直接繼承 screening recipe |
| Material | 明列本方法使用的材料模型與對應；缺來源／值即 NOT_READY | 明列本方法使用的材料模型與對應；缺來源／值即 NOT_READY |
| Reflectance | 記錄方法所用反射參數、單位、表面、來源和 hash；不補預設值 | 獨立記錄此方法實際使用的反射參數；不假設與 screening 數值等價 |
| 輸出與比較 | 保存 method-specific 結果、面積加權 summer cumulative incident radiation、空間分布與 within-method delta | 以本方法輸出保存相同範圍的證據，但使用獨立 parser／recipe provenance 和 within-method delta |
| 限制 | screening 結果不可冒充 Honeybee 絕對值或正式 verification | verification 結果不可與 Ladybug 絕對值互換；輻射降低不證明熱舒適改善 |

兩方法實際可用的材料欄位、反射參數、recipe schema、輸出單位與 parser 限制尚待各自 runtime／recipe manifest 與 Founder 決定；本提案不填入任何假定值。

## 5. W7 交接與入口條件

1. 先從權威狀態重新確認 HumanDecision＝0、ConstraintSet＝0、Scenario＝0、workspace rev6 DRAFT、zones＝0 是否仍成立；本包未讀正式 SQLite，也不宣稱完成 state reconciliation。
2. Founder 另行明確撤銷天氣暫停，批准 weather 方法與 source，並批准 E2 ExperimentPlan、比較域和所需材料／reflectance／recipe 控制。未完成前維持 `BLOCKED`。
3. W7 取得 Ladybug 與 Honeybee 方法 runtime manifests、dependency/licence 資訊、recipe/settings manifests、Radiance manifest，逐一比對版本／hash 並記錄可重現的環境驗證。靜態 manifest 不等於 runtime PASS。
4. 正式 API 必須從後端權威狀態解析 approval refs，再呼叫 validator；不得接受前端 `approved=true`、僅有 ID 的假批准或 fixture 作為 authority。job 建立前重驗輸入版本和 refs。
5. 只有新的、明確授權的執行包才能更改暫停契約並加入 dispatch。屆時兩方法各自保存 baseline 與兩個可行 variants、recipe/runtime/input/output hashes、occupancy/coverage、within-method delta；最後才比較方向。
6. 派送後如連線中斷，依 `OUTCOME_UNKNOWN` reconcile receipt、artifact 與權威狀態，不盲目重送。此 W6-12 包無派送、無結果，CP6-D 仍 BLOCKED，不能宣稱 E2 gate PASS。

## 6. 整合步驟

- Backend domain 使用 `urban_design.environment.radiation.validate_radiation_preconditions()`，且只能在載入 authority-backed refs 後呼叫。此 worktree 沒有新增 API router，因此 `src/urban_design/api.py` 沒有 router 可 include；未來執行 router 必須另立工作包並在 job 建立前 fail closed。
- 本包沒有新增 UI 元件，因此 `web/src/App.tsx` 不需 stage 掛載或 props。若 W7 另做狀態 UI，應由獨立元件顯示 persisted `BLOCKED`／`NOT_READY` 和原因，再由唯一整合者接入 Conditions／Refine 流程；UI 不可控制暫停解除或派送權限。

## 7. 執行記錄

- 執行模型：本 session 顯示為 **Codex／GPT-6**；reasoning effort 沒有由執行環境提供，因此不宣稱已使用計畫指定的 Luna Max effort。選擇理由：本包是範圍明確的 validator、回歸測試與交接文件工作。
- 未派遣 subagent，未呼叫外部服務，也未完成 Claude 跨供應商 review；跨供應商 review 與 Founder 接受仍待後續 gate。
