# W6 前導線執行計畫（與 Week 5 平行）

**版本：** 2026-09-25／v1。**撰寫與審查：** Claude（Control Tower）。**執行：** Gemini 3.8 Flash（外部執行路線，設計者 2026-09-25 授權，見決定紀錄 PD-13）。
**期間：** 與 Week 5 同週（預定 2026-09-28 至 10-02）。
**性質：** 只做 W6／W8 的前置工作，全部使用合成 fixture，**不產生任何 M4H 正式環境結果**。與 Week 5 主線的檔案範圍完全分開。

## 0. 本線目標與不做的事

| ID | 內容 | 對應 | 證據等級 |
|---|---|---|---|
| F1 | Radiance 6.0.2（arm64）裝到持久位置，重跑原本兩層氣候 smoke | 修正計畫 C4 | 2 |
| F2 | E1 日照時數／陰影方法原型（合成幾何） | W6-C | 0 |
| F3 | E2 中與天氣無關的部分：感測網格、排除遮罩、面積加權、比較規則 | W6-D | 0 |
| F4 | 出圖相機預設：等角正投影、透視、固定解析度與取景、版本標示 | W8-B 提前 | 0（附截圖時為 1） |
| F5 | 重現性基礎：依賴鎖定檔、runtime 清單彙整、乾淨環境重建說明（最後做） | W8-A 提前 | 0 |

**不做：** 任何使用天氣檔的計算；對 M4H 方案或真實幾何的正式 E1／E2；E3–E5；W5 主線負責的任何功能。

## 1. 共同規則

### 1.1 檔案範圍（最重要）

**可以新增或修改：**
- `src/urban_design/environment/`（新 package）
- `tests/test_environment_*.py`、`tests/test_radiance_runtime.py`
- `scripts/radiance_smoke.py`、`scripts/rebuild_env.md` 或同性質的新檔
- `config/runtimes/radiance-6.0.2-arm64.json`
- `web/src/utils/figurePresets.ts`、`web/src/utils/figurePresets.test.ts`
- 依賴鎖定檔（F5，僅新增鎖定檔，不改依賴版本範圍）

**不得修改（Week 5 主線擁有）：** `models.py`、`store.py`、`api.py`、`model_provider.py`、`site_critic.py`、`workspace_*.py`、`design_brief.py`、`space_syntax.py`、`context_network.py`、`src/urban_design/editing/`、`src/urban_design/morphology/`、`src/urban_design/syntax_engines/`、`web/src/components/**`、`web/src/App.tsx`、`web/src/types.ts`、`pyproject.toml` 的依賴清單。另外永遠不得修改 `web/index.html`、`web/src/index.css`、舊證據包、被證據包記錄為 parent 的文件。

若需要動上述檔案，停下並回報，由 Control Tower 協調。

### 1.2 Git

- 分支 `wp/w6p-<nn>-<name>`，從最新的 `main` 開出；每個 F 項一條分支。
- 一個 commit 只做一件事，commit message 寫測試命令與結果。
- 不得合併到 `main`、不得 force-push、不得改寫歷史、不得 commit `.urban_design_runtime/`。合併由 Control Tower 審查後進行。

### 1.3 其他規則

- **停損（PD-05）：** 同一項目連續 2 個 revision 或 1 個工作天沒有功能進展，就停下回報卡點與選項。
- **權威 DB：** 本線**完全不寫**權威 SQLite，也不需要讀它。
- **下載：** 唯一核准的下載是 F1 的 Radiance 壓縮檔（網址與 SHA-256 見 F1）。其他任何下載、新 Python 或 npm 依賴都要先回報、等核准。
- **外部服務：** 不呼叫任何模型服務；不接觸 Hermes（8787、8644 或其他埠）、QGIS、QGIS MCP；不關閉或重啟不是本線啟動的服務。
- **數值：** 不得捏造；fixture 值一律標 `FIXTURE_ONLY`；未知不得當 0。
- **委派：** 不得再把工作委派給其他模型或 agent。

## 2. 工作項目

### F1 Radiance runtime 重新佈建（D1，等級 2）

```yaml
objective: 把 Radiance 裝到持久位置，恢復 E1／E2 的執行環境。
download_approved:
  url: https://github.com/LBNL-ETA/Radiance/releases/download/rad6R0P2/Radiance_c1700d56_OSX_arm64.zip
  expected_sha256: 329ca788c6cedc641ad47577ce985ae16ee291acb1d5d02d7995192d58118cf0
  expected_size_bytes: 8202089
  note: 與 Milestone 1 使用的是同一個官方檔（docs/milestone1-feasibility.md）
steps:
  1. 下載到暫存位置；SHA-256 或大小不符就刪除暫存檔、停止並回報，不得改用其他來源
  2. 解壓到 ~/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/（不是 /tmp，不放進 .venv 或 repo）
  3. 新增 config/runtimes/radiance-6.0.2-arm64.json：來源網址、壓縮檔 SHA-256 與大小、解壓後各執行檔的 SHA-256、`rtrace -version` 輸出、授權（以壓縮檔內授權檔為準，照實記錄檔名與首段）、架構、安裝時間
  4. 確認 rad、gendaymtx、rtrace、rfluxmtx、oconv、rmtxop 都能執行
  5. 新增 scripts/radiance_smoke.py：只用 tests/fixtures/climate_smoke.json 重跑 Ladybug 與 Honeybee-Radiance 兩層 smoke；不跑 QGIS 部分（既有 scripts/tool_feasibility_probe.py 含 QGIS 段，不要用它）
  6. 新增 tests/test_radiance_runtime.py：runtime 不存在時 skip 並說明；存在時驗證 manifest hash 與版本
acceptance_criteria:
  - 六個執行檔可執行，版本為 RADIANCE 6.0.2
  - 兩層 smoke 通過，輸出與 Milestone 1 的 fixture 設定一致
  - 第 2 級證據包 artifacts/w6p-f1-radiance-runtime-<UTC>/：下載紀錄、hash、manifest、smoke 輸出、git_commit、git_dirty
forbidden: 不下載天氣檔；不執行任何 M4H 氣候分析
```

### F2 E1 日照時數／陰影方法原型（D1–D3，等級 0）

```yaml
objective: 建立不需天氣檔的日照時數計算，並用合成幾何證明正確。
files: src/urban_design/environment/{__init__,contracts,sunlight}.py、tests/test_environment_sunlight.py
contract（typed，Pydantic）:
  - 位置：緯度、經度、海拔、時區（IANA，例如 Europe/Amsterdam）
  - 期間：日期範圍、每日時段、timestep（每小時樣本數）
  - 感測點：座標（公尺，本地座標）、法向量、表面偏移量
  - 遮蔽物：Mesh3D 或 Face3D 清單，附來源與 hash
  - 輸出：每個感測點的日照時數（hours）、太陽向量數、方法與版本
method:
  - 主方法：ladybug Sunpath 產生地平線以上的太陽向量 → ladybug_radiance 的 DirectSunStudy／intersection_matrix（會呼叫 Radiance，使用 F1 的 runtime）→ 日照時數 = 可見樣本數 × (1 ÷ timestep)
  - 獨立對照：對軸向長方體遮蔽物寫一個純 Python 射線與方盒相交檢查，用來比對主方法
  - 若要示範真實位置，只能以 pyproj 把 StudyArea v5 質心從 EPSG:28992 轉成經緯度，並標示「位置示範，非分析結果」
fixtures（全部 FIXTURE_ONLY）:
  - 無遮擋水平面：日照時數等於該時段內太陽在地平線以上的時數（以 Sunpath 的日出日落核對）
  - 已知遮擋：冬至正午，點位正南方有足夠高的牆 → 該時刻不可見
  - 夜間時段 → 0
  - 夏令時間切換日（2026-03-29、2026-10-25，Europe/Amsterdam）：當地時間與 UTC 換算正確，不多算或少算一小時
  - timestep 1、4、12 的結果隨樣本增加而收斂，且不超過時段長度
  - 感測點位於幾何內部或偏移為 0 造成自遮擋 → 拒絕或明確警告
  - 主方法與獨立對照在方盒 fixture 上一致
acceptance_criteria: 以上 fixture 全部通過；Radiance 不存在時主方法測試 skip，獨立對照測試照跑
forbidden: 不讀取任何 EPW；不宣稱室內照度、熱舒適或全年表現
```

### F3 E2 中與天氣無關的部分（D2–D4，等級 0）

```yaml
objective: 先做好感測網格與比較規則，等天氣方法批准後 W6 可直接接上。
files: src/urban_design/environment/{sensors,comparison}.py、tests/test_environment_sensors.py、tests/test_environment_comparison.py
scope:
  - 地面感測網格：在給定多邊形上，以固定世界座標原點與間距產生網格（間距為參數，fixture 值標 FIXTURE_ONLY）；感測點 ID 由世界座標決定，修改方案後相同位置得到相同 ID
  - 排除遮罩：落在任何建築 footprint 內的點標為 EXCLUDED_INSIDE_FOOTPRINT，不刪除；回報涵蓋率
  - 面積加權平均：Σ(Aᵢ × Hᵢ) ÷ ΣAᵢ；只計入有效點；總量與每平方公尺指標分開
  - 比較物件：只允許「同一方法內」baseline 與 modified 比較；方法不同、網格定義不同、天氣 hash 不同、時段不同時一律拒絕並說明原因；兩方法只能比較「變化方向」是否一致
  - 被新建築占用的點：baseline 有效、modified 被排除時，比較結果要列出這些點，不得靜默丟棄
acceptance_criteria:
  - fixture：已知面積與數值的網格，面積加權結果與手算一致
  - 移動一棟建築後，未受影響的點 ID 不變；被占用的點正確標示
  - 跨方法絕對值比較、網格不符、天氣 hash 不符都被拒絕
forbidden: 不執行任何輻射模擬；不讀天氣檔
```

### F4 出圖相機預設（D3–D5，等級 0／1）

```yaml
objective: 為 W8 的平面、等角、透視圖建立可重現的相機與版面設定；本週只做工具函式，不接到畫面。
files: web/src/utils/figurePresets.ts、web/src/utils/figurePresets.test.ts
scope:
  - 等角預設：正投影（three.js OrthographicCamera），方位角 45°、仰角 35.264°（真等角），同一組方案用相同取景範圍與比例
  - 透視預設：固定視角、視野角與鏡頭位置；透視圖不附單一平面比例尺
  - 平面預設：正上方正投影；需要比例尺與北向（沿用 web/src/utils/mapFigure.ts 的比例尺函式，不修改該檔）
  - 取景：依給定邊界框計算相機位置與正投影縮放；多個方案共用同一邊界框時畫面尺度一致
  - 固定輸出解析度（寬高像素為參數）
  - 標示資料：方案 revision、git commit、日期、狀態（DRAFT、STALE、ILLUSTRATIVE 必須可見）、圖例規格
acceptance_criteria:
  - 單元測試驗證相機參數、取景計算、兩個方案共用取景時比例相同、透視預設不產生比例尺
  - npm --prefix web run test、build、lint 全部通過
forbidden: 不修改 Viewport2D.tsx、Viewport3D.tsx、App.tsx、mapFigure.ts；接到畫面的工作留待 W5 前端完成後另行安排
```

### F5 重現性基礎（有餘力才做，等級 0）

```yaml
objective: 為 W8 凍結做準備。
scope:
  - Python 依賴鎖定檔（例如 uv lock 產生的 uv.lock）：不改 pyproject.toml 的依賴範圍；若工具要求修改 pyproject，停下回報
  - 彙整 config/runtimes/ 下的 runtime 清單，寫一份說明：Python、Node、Radiance、PST、QGIS 的版本與取得方式
  - scripts/rebuild_env.md：從乾淨環境重建的步驟；只寫文件，不在本機實際重裝
acceptance_criteria: 鎖定檔可由既有 .venv 重現；說明文件的每個版本都能對到實際檔案或指令輸出
```

## 3. 建議順序

D1：F1 → F2 開始。D2–D3：F2 完成、F3。D3–D5：F4。有餘力：F5。F1 失敗時，F2 的獨立對照與 F3、F4 照常進行。

## 4. 測試命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_environment_sunlight.py tests/test_environment_sensors.py tests/test_environment_comparison.py tests/test_radiance_runtime.py
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider
```

```bash
npm --prefix web run test
```

每個分支送審前都要跑全套 Python 測試，確認沒有影響 Week 5 主線。

## 5. 回報格式（每天一次，以及每次停損時）

```text
DAY / TIME (UTC):
GIT: branch, commits, dirty?
ITEMS: F1–F5 -> PASS | FAIL | BLOCKED | OUTCOME_UNKNOWN（附證據路徑）
TESTS: 命令、collected／passed／failed／skipped
DOWNLOADS: 網址、大小、SHA-256、是否符合
FILES TOUCHED: 確認全部在第 1.1 節允許範圍內
STOP-LOSS: 是否觸發；卡點與選項
NEXT: 下一步與需要 Control Tower 或設計者做的事
```
