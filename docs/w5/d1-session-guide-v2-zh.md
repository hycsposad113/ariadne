# Week 5 第 1 天設計決策操作指南（v2）

**文件版本：** v2.0（2026-09-27）  
**適用對象：** 設計者（Jack Hsieh / Founder）  
**執行角色：** 設計者本人操作確認，AI 代理與測試僅於副本環境驗證。  
**核心目標：** 在 Rotterdam M4H 設計工作區完成探索設計範圍（ExplorationDesignArea）、既有要素處置（建築與道路之 Preserve／Editable／Undecided）以及空間分區（Spatial Zones）草稿，並透過密語簽署綁定不可篡改之 `WorkspaceRevision` 權威人類決策（HumanDecision）。

---

## 1. 啟動與環境核對

### 1.1 服務啟動
在兩個獨立終端機視窗中分別啟動 API 與 Web 前端：

**視窗 A：後端 API 伺服器**
```bash
cd /Users/jackhsieh/Downloads/TUD/Q5/w5-d1-flow
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/uvicorn urban_design.api:app --host 127.0.0.1 --port 8789
```

**視窗 B：前端 Web 平台**
```bash
cd /Users/jackhsieh/Downloads/TUD/Q5/w5-d1-flow/web
npm run dev -- --host 127.0.0.1 --port 5173
```

開啟瀏覽器前往 `http://127.0.0.1:5173`。

### 1.2 介面核對檢查清單（進場前必看）
請先核對頁首（Header）的狀態標籤，必須符合以下狀態才可開始進行正式決策：
- **Project ID**：`rotterdam-m4h-pilot-project`
- **StudyArea ID**：`study-area-rotterdam-m4h-pilot-project-v5`
- **CRS**：`EPSG:28992`（荷蘭阿默斯福特 RD 投影坐標系）
- **StudyArea status**：`CONFIRMED_FOR_EXPLORATION`（綠色徽章）
- **權威伺服器狀態**：顯示 `In Sync (Server Authority)` 或有草稿變更時顯示 `Unsaved Draft Changes`
- **決策狀態**：若尚未確認決策，顯示灰色 `D1 決策：未確認 (DRAFT)`

---

## 2. 平台操作三部曲

### 步驟一：繪製探索設計範圍（Exploration Design Area, EDA）
1. 切換至左側欄 **Spatial Brief** 分頁。
2. 捲動至 **Exploration Design Area** 區塊，點選 `Draw exploration design area`。
3. 在 2D 地圖上點擊頂點繪製多邊形（至少 3 個頂點），點擊 `Finish Polygon` 閉合。
4. 核對計算出的面積（m²）。請注意：EDA 必須完全落於 active StudyArea 幾何範圍內。
5. 點擊 `Save draft area` 保存設計範圍草稿。
   > **注意**：Exploration Design Area 是探索與統計分母，並非法定地籍線或分區封套。

### 步驟二：標記要素處置（Feature Dispositions）
1. 切換至左側欄 **Dispositions** 分頁。
2. 切換上方分頁標籤可分別檢視 **BAG Buildings**（建築）與 **OSM Roads**（道路）。
3. 處置標記方式：
   - **單項選取**：在地圖點選或於列表中點選建築／道路，在右側（或詳細欄）標記其為 **Preserve（保留）**、**Editable（可改）** 或 **Undecided（未決）**，並可填寫備註理由。
   - **批次選取**：按住 Shift 多選要素後批次設定。
   - 若欲將已鎖定項目改為 Editable，系統會跳出確認對話框以防止誤觸。
4. 未決項（Undecided）會維持來源現狀，不會被後續生成器誤刪。

### 步驟三：設定空間分區草稿（Spatial Zones）
1. 回到 **Spatial Brief** 分頁，於「Add Spatial Zone」區塊設定：
   - **Zone Name**（分區名稱，例如：`North Mixed-Use Innovation District`）
   - **Target Use**（主要土地使用用途）
   - **Target FAR**（容積率，例如：`2.5`）與 **Max Height**（限高公尺，例如：`35`）
   - **Hard Constraints**（硬性條件，以逗號分隔）
   - **Design Preferences**（偏好條件，以逗號分隔）
2. 點擊 `Draw Zone Polygon`，於 2D 地圖繪製分區範圍，完成後按 `Finish Polygon`。
3. 點擊 `Add Draft Zone` 將分區加入草稿清單。

---

## 3. 同步工作區（Sync Workspace）

完成上述繪製與標記後，工作區處於本地草稿狀態（頁首顯示黃色 `Unsaved Draft Changes`）：
1. 點擊頁首的 **Sync Workspace** 按鈕。
2. 彈出版本比對對話框（SyncModal），檢視本次變更的要素統計與分區摘要。
3. 點擊確認同步（Confirm Sync）。
4. 同步成功後：
   - 伺服器將資料持久化並產生新的 `WorkspaceRevision`（例如 rev 1）。
   - 計算正式的 `payload_digest` 與 EDA 幾何雜湊 `geometry_hash`。
   - 頁首恢復綠色 `In Sync (Server Authority)`。

---

## 4. 確認第 1 天決策（Confirm Day 1 Decision）

當工作區已儲存且**無未保存草稿**時，頁首的 **「確認第 1 天決策」** 按鈕將會啟用（綠色可點擊）。

### 4.1 開啟確認對話框與摘要核對
點擊 **「確認第 1 天決策」**，系統將直接載入伺服器端該版本之唯讀摘要（`Day1DecisionSummary`）：

1. **設計範圍 (Exploration Design Area)**：
   - 核對面積（m²）。
   - 核對幾何 Hash（格式如 `sha256:4a7b...`）。
2. **要素處置 (Feature Dispositions)**：
   - 建築物：確認保留、可改、未決棟數總和；點擊 `<檢視清單>` 可展開查看各分類之具體 ID 清單。
   - 道路：確認保留、可改、未決條數總和；可展開查看 ID 清單。
3. **分區清單與條件 (Spatial Zones & Constraints)**：
   - 檢視各分區之名稱、目標用途、FAR 與限高。
   - 檢視硬性條件與偏好條件。

### 4.2 未保存變更防呆機制
> **防呆規則**：若工作區存在未儲存變更，對話框上方會出現黃色警告橫幅：  
> `未保存的變更警告：目前工作區存在未保存的草稿變更。必須先點擊「Sync Workspace」儲存為正式版本後，才能對該版本確認第 1 天決策。`  
> 且下方的 **「Confirm decision」按鈕將被強制禁用**，杜絕送出未經持久化之不一致狀態。

### 4.3 輸入密語並送出
1. 核對理由（Reason）：系統預設填入 `第 1 天決策：確認設計範圍、建築與道路保留／可改處置，以及空間分區草稿。`，設計者亦可補充說明。
2. 輸入設計者個人的 **Decision key**（決策密語）。
3. 點擊 **Confirm decision**。
4. 密語安全保證：
   - 密語僅透過加密傳輸至本機端點比對雜湊。
   - 密語送出後立即自記憶體清除。
   - **絕不**儲存於 `localStorage`、`sessionStorage`、Cookie 或任何日誌中。

---

## 5. 完成確認與舊版本狀態標記

### 5.1 決策成功之狀態呈現
決策送出成功後：
- 頁首將彈出提示：`Day 1 decision recorded: decision-xxx (approved)`。
- 頁首決策徽章顯示為綠色：`D1 決策：decision-xxx (approved)`。
- 側欄 **Spatial Brief** 的狀態橫幅由草稿黃色警示轉為綠色：  
  `決策已確認: 第 1 天決策 decision-xxx（approved）已綁定至此工作區版本。`
- 側欄 **Dispositions** 亦顯示決策已確認與決策 ID。
- 重新整理網頁（Reload）後，決策狀態依然完整載入與顯示。

### 5.2 「對應舊版本」自動標記規則
在第 1 天決策完成後，若設計者後續進一步修改工作區：
1. **本地修改期間**：一旦有未保存修改，決策徽章即提示該決策對應舊版本。
2. **重新同步新版本後**（例如推進至 rev 2）：
   - 舊的決策（綁定 rev 1）不會被覆寫或刪除（保留不可篡改審計歷史）。
   - 頁首徽章轉為黃色：`D1 決策：decision-xxx (對應舊版本 rev 1)`。
   - 側欄狀態提示：`對應舊版本: 決策 decision-xxx 綁定於 revision 1。目前工作區存在新變更，請於調整完成並同步後重新確認決策。`
   - 設計者若確認新版本符合要求，可再次點擊「確認第 1 天決策」對新版本簽署新的決策記錄。
