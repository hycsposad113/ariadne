# D2-C 約束集：Founder 正式批准操作指南

> ⚠️ **暫不執行（Commander 審查，2026-10-16）**：`approved_generation` 規定只能有一個生效（effective）約束集。批准 D2-C 後 D2-A 仍維持生效，正式生成會因「multiple effective ConstraintSets」被擋；系統也不允許對已生效的 D2-A 下決策讓它退場。要正式化必須先做「新約束集取代舊約束集」的規則（核心帳本變更），或維持報告中的 ASSUMED 標記。由 Founder 決定。


此指南對應 `artifacts/w8/d2c-drill/` 的完整資料庫副本演練。副本演練僅在 `/private/tmp` 隔離環境中驗證流程可行性與安全性，**不代表正式帳本已生效**。D2-C 約束集的正式生效必須由 Founder 親自在終端機核對內容並輸入決策密語完成。

---

## 一、背景與核心原則

在 W8 評估與深化過程中，Founder 已拍板並於先前回報中標註為 **ASSUMED** 的三項關鍵假設值，現透過 D2-C 約束集（`constraint-set-d2-c-20261016`）正式化為具備完整數位決策追溯力的正式提案：

1. **FAR 0.8 只計「新建＋加蓋」樓地板**，保留建築不計入；新建 GFA 上限為 **146,873 m²**。
2. **新建 GFA 下限為上限的 85%**（即 **124,842.05 m²**）。
3. **保留廠房（retained halls）以 1–2 層計**，不以 3.5 m 層高推算。
4. **高度上限 20 m**（最多 5 層：首層 4 m＋4×3.5 m = 18 m ≤ 20 m）。

### 系統架構守則（Core Law）
> LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.

依據平台核心架構契約，約束集必須通過 `validate_constraint_set_definition(..., require_complete=True)` 嚴格檢核。現有系統約束型別庫（`CONSTRAINT_UNIT_BY_NAME`）僅支援 8 類參數族（`far_upper_limit`, `zone_far_upper_limit`, `coverage_upper_limit`, `height_upper_limit`, `first_floor_height`, `standard_floor_height`, `road_width`, `rotation_step`），且數值強制要求正數與特定單位。

針對型別庫無法直接以欄位表達的項目，**絕不破壞 schema 硬塞自訂型別**，而是採用嚴格透明的工程做法：以最接近的既有型別精確表達上限，將下限與保留層數規則完整記載於約束集的權威說明（`notes`）中，並由下游形態評估與驗證器把關。

---

## 二、D2-C 約束集數值逐項對照

草稿 ID：`constraint-set-d2-c-20261016`  
提案角色：`AGENT_AUTOMATION`（`agent-d2c-formal-session`）  
內容摘要 (Digest)：`sha256:c41ba5cb8657bdef05f3a9d16da84aba413470c611736125b62ff81383dc9930`

| 項次 | 項目與 Founder 拍板內容 | D2-C 欄位表達方式 | 數值與單位 | 約束強制力 | 分母 / 範圍 | 備註與來源註記 |
|:---:|:---|:---|:---:|:---:|:---:|:---|
| 1 | **FAR 上限 0.8（新建 GFA 上限 146,873 m²）**<br>只計新建＋加蓋，保留建築不計入 | `far_upper_limit` | `0.8`<br>(ratio) | HARD | `land_area`<br>whole_site | 陸地面積 183,591.328 m² × 0.8 ＝ 146,873 m²。<br>`source_note`: FOUNDER_STATED: Founder 2026-10-11／10-15 決定 |
| 2 | **新建 GFA 下限 85%（124,842.05 m²）** | 【無法直接型別欄位表達】<br>記載於 `notes` | 124,842.05 m² | HARD（政策） | whole_site | 現行系統無 lower limit 型別。由 notes 明載，驗證器與報告把關四案落點（85.4%–94.7% 通過）。 |
| 3 | **保留廠房以 1–2 層計**<br>不以 3.5 m 層高推算 | 【無法直接型別欄位表達】<br>記載於 `notes` | 1–2 層 | HARD（政策） | 保留建物 | 現行系統無保留建築專屬層數欄位。明載於 notes，供容量與形態分析引用。 |
| 4 | **高度上限 20 m（最多 5 層）** | `height_upper_limit` | `20.0`<br>(m) | HARD | whole_site | 法定限高 20 m。<br>`source_note`: FOUNDER_STATED: Founder 既有決定 |
| 5 | **首層高度 4.0 m** | `first_floor_height` | `4.0`<br>(m) | HARD | whole_site | 首層挑高 4 m。<br>`source_note`: FOUNDER_STATED: Founder 2026-10-11／10-15 決定 |
| 6 | **標準層高度 3.5 m** | `standard_floor_height` | `3.5`<br>(m) | HARD | whole_site | 4 m + 4×3.5 m = 18 m ≤ 20 m。<br>`source_note`: FOUNDER_STATED: Founder 2026-10-11／10-15 決定 |
| 7 | **建蔽率上限 0.35** | `coverage_upper_limit` | `0.35`<br>(ratio) | HARD | whole_site | 沿用 D2-A 基準建蔽率。<br>`source_note`: ASSUMED |
| 8 | **主要道路路寬 14 m** | `road_width` | `14.0`<br>(m) | HARD | `road:primary` | 沿用 D2-A 道路設定。<br>`source_note`: ASSUMED |
| 9 | **次要道路路寬 10 m** | `road_width` | `10.0`<br>(m) | HARD | `road:secondary` | 沿用 D2-A 道路設定。<br>`source_note`: ASSUMED |
| 10 | **住宅街巷路寬 6 m** | `road_width` | `6.0`<br>(m) | HARD | `road:residential` | 沿用 D2-A 道路設定。<br>`source_note`: ASSUMED |
| 11 | **量體旋轉步階 15°** | `rotation_step` | `15.0`<br>(degree) | HARD | whole_site | 沿用 D2-A 旋轉步階。<br>`source_note`: ASSUMED |

---

## 三、無法直接以現有 Constraint 型別表達的項目說明

依照專案工程憲法，我們拒絕捏造或破壞資料綱要。以下兩項在現有系統中列為「無法以單一 Constraint item 表達項」：

1. **新建 GFA 85% 下限（124,842.05 m²）**：
   - **原因**：系統僅提供 `far_upper_limit` 與 `coverage_upper_limit` 等上限約束，未設計下限約束型別。
   - **處置**：明載於 D2-C `notes` 中。在下游規劃評估（Evaluation Framework）中，四個生成紋理方案（港埠 139,128 m²、院落 129,350 m²、圍合 126,875 m²、地景 125,492 m²）實測均落於 85%–100% 區間，全數合格。
2. **保留廠房（retained halls）以 1–2 層計**：
   - **原因**：系統的 `first_floor_height` 與 `standard_floor_height` 僅約束新建建築量體的幾何生成，無保留現存工業廠房的實體層數欄位。
   - **處置**：明載於 D2-C `notes` 中，不強制將保留廠房按 3.5 m 層高折算樓層。

---

## 四、系統規則與批准後的狀態變化

1. **D2-C 狀態變化**：
   - 建立草稿後初始為 `proposed`（revision 1），無任何生效約束與 `source_refs`。
   - Founder 輸入密語批准後，系統以不可變原子操作（Atomic Ledger Append）記錄一筆 `HumanDecision`，並觸發 `ActivateConstraintSet` 事件，將 D2-C 推進至 `effective`（revision 2），內部 9 項約束全部轉為 `effective` 且綁定該決策 ID。
2. **既有 D2-A 與 D2-B 的狀態**：
   - **D2-A（`constraint-set-d2-a-20261001`）**：維持 `effective`（revision 2）。
   - **D2-B（`constraint-set-d2-b-20261001`）**：維持 `proposed`（revision 1）。
   - **系統規則依據**：在 `ProjectStateStore.record_human_decision` 中，約束集的批准僅對被批准的目標實體進行版本推進與狀態切換，不會跨實體副作用標記舊集合為 `superseded`（約束集允許多組共存供不同方案比對引用）。

---

## 五、副本演練驗證結果（Evidence Summary）

本次演練完整證據收錄於 `artifacts/w8/d2c-drill/`：

- **正式資料庫唯讀安全**：
  - 正式 DB 路徑：`/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3`
  - 演練前 SHA-256：`2bff9375952f318a146ca33c57662abf76dd20aa70c37ec1886f4d486ea30955`
  - 演練後 SHA-256：`2bff9375952f318a146ca33c57662abf76dd20aa70c37ec1886f4d486ea30955`（**完全一致，正式庫零寫入**）
  - 副本透過 SQLite `mode=ro` backup API 備份至 `/private/tmp/d2c-drill-*/copy-state.sqlite3`，`PRAGMA quick_check` 為 `ok`。
- **流程驗證結果**：
  - 草稿建立：HTTP 201 Created，Digest: `sha256:c41ba5cb8657bdef05f3a9d16da84aba413470c611736125b62ff81383dc9930`（`api-01-create-draft.json`）
  - 冪等調用：HTTP 201 Created，完全一致無重複修訂（`api-02-idempotent-draft.json`）
  - 錯誤密語測試：HTTP 403 Forbidden，拒絕決策，草稿維持 `proposed`（`api-03-wrong-key.json`）
  - 正確密語批准：HTTP 201 Created，決策成功登錄（`api-04-approve-decision.json`）
  - 狀態驗證：D2-C 成功轉為 `effective`（rev 2），D2-A 維持 `effective`（rev 2），D2-B 維持 `proposed`（rev 1）（`api-05` 至 `api-07`）
  - 帳本完整性：帳本事件精確新增 3 筆，無破壞性變更（`ledger-evidence.json`）
- **單元與整合測試**：
  - `tests/test_d2c_constraint_set.py`：5 項測試全部 PASS。
  - 既有約束集測試（`test_constraint_set.py`, `test_constraint_set_drafts.py`）：25 項測試全部 PASS。
  - 總計 30 passed（4.07 秒）。

---

## 六、Founder 正式執行操作步驟

正式執行需由 Founder 在本機終端機親自執行，流程不存、不印、不記錄決策密語。

### 步驟 1：確認 API 伺服器狀態
確認 API 服務（預設埠 8795）已在背景正常運行：
```sh
curl -s http://127.0.0.1:8795/api/v1/projects/rotterdam-m4h-pilot-project/constraint-sets | jq .
```

### 步驟 2：執行正式腳本
在專案目錄下執行：
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python scripts/d2c_formal_run.py --api 'http://127.0.0.1:8795'
```

### 步驟 3：終端機互動與確認
1. **建立草稿**：腳本自動檢查並建立 D2-C 草稿，印出包含 9 項約束與 Digest 之摘要清單。
2. **人工確認**：
   ```text
   2/2 【需要你的決策】批准 D2-C 約束集（constraint-set-d2-c-20261016）生效 輸入 y 繼續，其他鍵中止：y
   ```
3. **輸入密語**：
   ```text
   請輸入決策密語（不會顯示）：
   ```
   透過 `getpass` 隱蔽輸入，終端機不顯示任何字符，送出後記憶體立即抹除。
4. **確認生效**：
   終端機回傳：
   ```text
   ✓ 決策已記錄：decision-...
   ✓ D2-C 約束集已成功生效（status: effective, revision: 2）。
   結果已寫入正式帳本。請告訴 Commander「D2-C 跑完了」。
   ```
