# Rotterdam M4H（Merwe-Vierhavens）基地分析報告

> **工作流階段：** 第一階段 Understand（理解基地現況，需求 R26-05／R26-06）  
> **撰寫者：** 執行者 AntiGravity（Gemini 3.8 Flash）  
> **審閱狀態：** **待設計者審閱（Pending Designer Review）**（本報告由執行者依確定性數據與代碼計算撰寫，非 Live AI 即時生成結果）  
> **基準座標系統：** EPSG:28992（Amersfoort / RD New，單位：公尺）  
> **日期：** 2026-09-27  
> **審查紀錄：** 作者 AntiGravity（Gemini 3.8 Flash）；交叉審查 Codex（OpenAI GPT-6，執行環境未提供更具體型號）；日期 2026-09-27。修正摘要：移除無水深／港池名稱依據的主張，修正資料分類與幾何描述，改以基地內路段重算語法圖分位並補周邊圖層與重現指令。詳見 `artifacts/w5-site-analysis/review-codex.md`。

---

## 執行摘要（Executive Summary）

本報告描述經人工確認、供探索使用的 StudyArea v5（226,064.33 m²）；此範圍不是正式 Site 或 DesignBoundary。數值依本機保留的 PDOK BAG／BGT、TU Delft 3D BAG、OSM 與 PST 3.3.1 輸入計算，並逐項列出來源及限制。25 項原始主張經交叉審查後保留 24 項；claim-w5-site-011 因港池名稱、深度及路網拓撲缺乏來源而移除。Space Syntax 結果仍屬探索性，整合度與穿行度不代表實際人流或交通量。

---

## (a) 範圍與資料來源（Scope & Provenance）

### 1. 基地界線與空間範疇
- **研究範圍版本：** StudyArea v5（`study-area-rotterdam-m4h-pilot-project-v5`）。
- **探索範圍幾何面積：** **226,064.33 m²**（約 **22.61 公頃**，引用證據 [claim-w5-site-001](#claims-register)）；StudyArea 確認不等於法定地籍或 DesignBoundary 核准。
- **RD New 投影邊界 [minX, minY, maxX, maxY]：** `[88610.65, 435507.08, 89558.21, 436221.65]`。
- **垂直高程基準：** 荷蘭常備水準面 NAP（EPSG:5709）；3D BAG 幾何複合格網為 EPSG:7415。
- **研究邊界 GeoJSON SHA-256：** `b96aa5625a9d2e8c4163cf2e88fb31c74b9a0f5b94aef5434ecd3295607a82ea`。

### 2. 權威資料來源清冊與雜湊校驗表

| 資料集名稱 | 版本 / 時間戳記 | 供應者 / 機構 | 授權條款 | 原始檔案 / 抽取識別碼 | SHA-256 完整雜湊值 | 用途說明 |
|---|---|---|---|---|---|---|
| **StudyArea v5** | v5 (2026-09-22) | 專案確認之探索範圍 | 專案專有 | `study-area.geojson` | `b96aa5625a9d2e8c4163cf2e88fb31c74b9a0f5b94aef5434ecd3295607a82ea` | 經確認的探索範圍，非正式 DesignBoundary |
| **PDOK BAG (pand)** | 2024-03 抽取 | Kadaster / PDOK | CC0 1.0 | `pdok-bag-pand-p001~p015` | `spatial-r01` manifest 鎖定 | 既有建築基底與登記屬性 |
| **PDOK BGT (waterdeel)** | 2024-03 抽取 | Kadaster / PDOK | CC0 1.0 | `pdok-bgt-waterdeel-p001` | `spatial-r01` manifest 鎖定 | 水體與港池邊界多邊形 |
| **PDOK BGT (wegdeel)** | 2024-03 抽取 | Kadaster / PDOK | CC0 1.0 | `pdok-bgt-wegdeel-p001~p035` | `spatial-r01` manifest 鎖定 | 地表道路鋪面要素 |
| **3D BAG** | v2025.09.03 | TU Delft 3DGI | CC BY 4.0 | `height-table-v2025.09.03...json` | `3dbag-height-table-v1` | 屋頂 P70 高程與樓層推估 |
| **OSM 區域路網** | 2026-09-22T20:22Z | OpenStreetMap 社群 | ODbL 1.0 | `zuid-holland-260922.osm.pbf` | `71379de6fcb38b114ae2ee564cac99cfb2763b6cc3f6d87667c1079ea578401c` | 三模式路網抽取基底 |
| **2 km 周邊環境 (Context)** | context-20260927T153054Z | OSM / 專案抽取器 | ODbL 1.0 | `buildings/water/green/roads` | `context/manifest.json` 鎖定 | 2 km 腹地多邊形與現況 |
| **Space Syntax 六圖層** | run-week5-modes-01 | PST 3.3.1 (PD-15) | LGPL-3 | `syntax_six_layer_candidate.json` | `fde6d49b4f41135316d6b432b690697233c77f0b91c3df6f22363b5eef4b5900` | 三模式空間語法熱圖 |

![圖 1：Rotterdam M4H 基地範圍與 2 km 周邊環境概覽](../../artifacts/w5-site-analysis/figures/fig01_scope_and_context.png)
*圖 1：Rotterdam M4H 基地範圍與 2 km 周邊環境概覽（EPSG:28992；周邊建築為視覺稀疏繪製，完整 context snapshot 記錄 21,045 個建築面圖徵）。*

---

## (b) 既有建築現況與高度分布（Existing Buildings & Morphology）

### 1. 建築數量與基底面積（Footprint Analysis）
- **BAG 建築面圖徵：** 基地內共計 **51** 個（`bag:pand`，引用證據 [claim-w5-site-002](#claims-register)）；不等同於現地建築棟數或使用狀態。
- **基底無重疊聯集面積（Unary Union Footprint Area）：** **44,699.56 m²**（約 **4.47 公頃**，引用證據 [claim-w5-site-003](#claims-register)）。
- **建築基底面積比：** 佔 StudyArea 總面積 **19.77%**（引用證據 [claim-w5-site-004](#claims-register)）；此為幾何比率，不是法規建蔽率。

### 2. 3D BAG 建築高度統計（Height Distribution）
依據 TU Delft 3D BAG（v2025.09.03）於 StudyArea v5 加外擴 500 m 緩衝區之高度表比對：
- **有效配對高度圖徵：** **31 個**（佔 60.8%）。
- **建築地面高度中位數（Median Height）：** **9.85 m**（引用證據 [claim-w5-site-005](#claims-register)）。
- **高度極值：** 配對值最高 **27.41 m**、最低 **2.68 m**、平均 **10.44 m**；資料未提供可確認的建築名稱或結構用途。
- **高度分位數：** 第 25 百分位 **4.85 m**，第 75 百分位 **12.53 m**。
- 其餘 **20** 個 BAG 特徵沒有可用高度配對；其中 BAG 屬性有 **19** 筆標示 `Pand gesloopt`、**1** 筆 `bouwjaar: 2025`，這些登記不單獨證明現地狀態。

### 3. 總樓地板面積估算（GFA / BVO Estimation & Limitations）
- **估算規則：** 嚴格落實計畫決策 PD-11 之 `floor-estimate-v1` 規則：
  $$\text{估算樓層數} = \max(1, \text{round}((\text{屋頂 P70 高度} - \text{地面高度}) / 3.0\,\text{m}))$$
- **工業用途修正：** BAG 登記含 `industriefunctie` 的特徵採用 $[1, \text{估算樓層}]$ 區間；這是 PD-11 的估算規則，不代表已確認實際用途或樓層。
- **估算成果（引用證據 [claim-w5-site-006](#claims-register)）：**
  * 31 個具高度圖徵的標準點估算總樓地板面積（Point GFA）：**175,984.03 m²**。
  * PD-11 工業用途區間估算：**[55,425.20 m², 175,984.03 m²]**。
  * 缺漏高度之 20 個 BAG 圖徵維持 **`UnavailableValue`（UNKNOWN）**，不補 0；此估算不支持全區實際樓地板面積或精確容積率（FAR）。

### 4. 登記用途分布（Registered Usages）
- 基地內有 **31 棟**具有有效登記用途（`gebruiksdoel`），**20 棟**為空白或未登記（引用證據 [claim-w5-site-007](#claims-register)）。
- BAG 有用途欄位的圖徵中，登記用途包含工業功能（`industriefunctie`）19 個、辦公（`kantoorfunctie`）9 個、集會（`bijeenkomstfunctie`）5 個、零售（`winkelfunctie`）3 個及運動功能 2 個；登記欄位不是實際租戶或現況用途清冊。

![圖 2：既有建築高度分布與保存狀況圖](../../artifacts/w5-site-analysis/figures/fig02_existing_buildings_height.png)
*圖 2：既有建築高度分布與保存狀況圖（基於 3D BAG v2025.09.03，分級顯示低層、中層、高層、超高塔樓與歷史已拆除特徵）。*

---

## (c) 道路與交通路網（Transportation & Connectivity）

### 1. 路網層級與幾何長度（Road Hierarchy）
- **基地內去重複道路中心線總長度（Unique Centerline Union）：** **8,496.54 m**（約 **8.50 km**，引用證據 [claim-w5-site-008](#claims-register)）。
- **各層級道路標籤長度（引用證據 [claim-w5-site-009](#claims-register)）：** 以下百分比以各類標籤長度總和 **8,501.23 m** 為分母；重疊線段可被多個標籤計入，故不等於去重複總長度。
  * **`service`：** **3,424.99 m**（40.3%）。
  * **`footway`：** **1,897.64 m**（22.3%）。
  * **`unclassified`：** **1,293.09 m**（15.2%）。
  * **`cycleway`：** **955.98 m**（11.2%）。
  * **`pedestrian`：** **696.23 m**（8.2%）。
  * 其他已計入標籤長度包括 `proposed`、`residential` 等；OSM highway 標籤不代表法定路權、通行狀態或交通量。

### 2. 道路與範圍邊界交點
- OSM highway 線幾何與 StudyArea 邊界有 **22 個互異幾何交點**（引用證據 [claim-w5-site-010](#claims-register)）；此結果不證明現地出入口、道路通行權、管制狀態或交通容量。

### 3. 水體幾何
- 水體範圍及其幾何介面見 (e)；原主張 claim-w5-site-011 的港池名稱、深度、尺度及路網拓撲未由本次輸入資料支持，因此移除。

![圖 3：道路路網層級、外部連接點與水岸阻隔圖](../../artifacts/w5-site-analysis/figures/fig03_transport_road_network.png)
*圖 3：OSM 道路標籤與 StudyArea 範圍邊界幾何交點；交點不代表可通行出入口。*

---

## (d) 機能與土地使用現況（Land Use & Functions）

### 1. 基地內機能資料範圍
- 本次 OSM 抽取沒有獨立的 `amenity` 或 `landuse` 多邊形圖層，且點狀標籤與 BAG 用途欄位不足以形成完整現況機能清冊；本次資料不能判定實際租戶或當前用途（引用證據 [claim-w5-site-013](#claims-register)）。

### 2. 2 km 周邊腹地環境構成（Context Analysis）
2 km 緩衝區（StudyArea 外擴 2 km）之 OSM context snapshot 面積約 17.58 km²。圖徵數僅描述該快照內容，不代表人口、住宅戶數、交通量或土地使用比例（引用證據 [claim-w5-site-012](#claims-register)）：
- 建築面 **21,045** 個、綠地面 **1,135** 個、水體面 **103** 個、道路線 **4,862** 條。
- 周邊圖層依 OSM 資料版本 `2026-09-22T20:22:59Z`；個別建物用途與使用人口未由這些圖徵數推定。

![圖 4：基地登記使用機能與綠地分布圖](../../artifacts/w5-site-analysis/figures/fig04_land_use_and_functions.png)
*圖 4：基地登記使用機能與綠地分布圖（標註 31 棟 BAG 登記用途建物及 2.19 公頃都市綠地）。*

---

## (e) 開放空間與水體環境（Open Space & Water Systems）

### 1. 港池水體與水陸介面（Water Body & Quay Walls）
- **水體面積：** 基地內 BGT 水體面特徵面積為 **42,473.00 m²**（約 **4.25 公頃**），佔基地總面積之 **18.79%**（引用證據 [claim-w5-site-014](#claims-register)）。
- **水陸幾何介面：** BGT 水體聯集邊界扣除 StudyArea 裁切邊界後長 **1,332.04 m**（引用證據 [claim-w5-site-015](#claims-register)）；幾何資料不包含護岸型式、高度、材質、防汛功能或可親水性。

### 2. 都市綠地空間（Green Spaces）
- **綠地圖徵與裁切面積：** OSM 綠地圖徵相交數 **21** 個，總裁切面積 **21,886.06 m²**（約 **2.19 公頃**，佔 StudyArea 9.68%，引用證據 [claim-w5-site-017](#claims-register)）。
- **按 OSM 標籤分類的裁切面積：** `grass` 11,454.32 m²、`forest` 1,526.74 m²、`allotments` 8,905.00 m²。標籤不證明植被狀態、公共開放或特定團體管理。

### 3. 未建地面殘差分析（Unclassified Surface Residual）
- **殘差面積計算：** 基地總面積扣除建築基底（44,699.56 m²）與水體（42,472.998 m²）後，剩餘之未建殘差地表面積高達 **138,891.77 m²**（約 **13.89 公頃**，佔基地總面積之 **61.44%**，引用證據 [claim-w5-site-016](#claims-register)）。
- 此殘差是圖層幾何差額，不代表硬鋪面、空置、可開發、公共開放或可使用狀態；OSM 綠地圖徵可與該殘差相交。

![圖 5：水體、水陸介面、綠地與未分類地面殘差分布圖](../../artifacts/w5-site-analysis/figures/fig05_open_space_and_water.png)
*圖 5：BGT 水體、幾何水陸介面、OSM 綠地與未分類幾何殘差；紅線只標示水體邊界幾何，不表示岸線構造。*

---

## (f) 空間語法分析（Space Syntax — Six Layer Heatmaps）

### 1. 計算方法、引擎決策與邊界效應聲明
- **計算引擎：** PST 3.3.1（Place Syntax Tool，KTH／Chalmers），依據計畫決策 **PD-15** 確定為本專案正式語法計算引擎。
- **方法比對說明（Method Comparison FAIL）：** 前期自製引擎與 PST 之比對（`method-comparison-v1`）因角度成本與步行半徑實作差異判定為 **FAIL**（Choice 第 95 百分位相對誤差達 42.1%）。依 PD-15 停損規則，自製引擎已退為歷史參考，當前六圖層結果分類為 **EXPLORATORY（探索性分析）**（引用證據 [{c_map['claim-w5-site-024']['id']}](#claims-register)）。
- **絕對禁止偽科學解讀：** **嚴禁將整合度（Integration / NAIN）解讀為實際人流量，嚴禁將穿行度（Choice / NACH）解讀為車輛交通量**。空間語法指標僅度量路網在特定度量半徑下的拓撲幾何可達性與潛在穿行選擇率。
- **邊界穩定性檢驗結果：**
  * **行人 800 m（1.5 km 緩衝抽取）：** 狀態標記為 `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`（邊界穩定性尚未進行雙倍半徑之交叉驗證，引用證據 [{c_map['claim-w5-site-018']['id']}](#claims-register)）。
  * **自行車 2,000 m（4 km vs 6 km 緩衝抽取）：** 狀態為 `EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY`，Spearman 相關係數達 **1.0**，邊界受影響路段為 0 段（0.0%，通過檢驗，引用證據 [{c_map['claim-w5-site-020']['id']}](#claims-register)）。
  * **汽車 10,000 m（15 km vs 20 km 緩衝抽取）：** 狀態為 `EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY`，Spearman 相關係數達 **1.0**，邊界受影響路段為 0 段（0.0%，通過檢驗，引用證據 [{c_map['claim-w5-site-022']['id']}](#claims-register)）。

### 2. 六圖層候選路網統計

以下統計涵蓋候選路網的全部計算段；分位數供各候選路網描述使用，並非實際人流或交通量。圖 6–11 僅將 StudyArea 內的路段著色，其五級切點另依各圖顯示的基地內路段重算。

| 圖層 | 模式 | 半徑 | 指標 | 候選段數 | 最小 | 平均 | 最大 | 全候選網分位切點 Q0/Q20/Q40/Q60/Q80/Q100 | 基地內著色段數 |
|---|---|---|---|---:|---:|---:|---:|---|---:|
| **0** | pedestrian | 800.0 m | NAIN | 481 | 0.0000 | 0.7828 | 1.2729 | `[0.0, 0.6425, 0.7219, 0.8098, 0.9176, 1.2729]` | 477 |
| **1** | pedestrian | 800.0 m | NACH | 481 | 0.0000 | 0.8542 | 1.4713 | `[0.0, 0.6782, 0.8168, 0.9433, 1.1187, 1.4713]` | 477 |
| **2** | bicycle | 2,000.0 m | NAIN | 140 | 0.0000 | 0.6738 | 0.8807 | `[0.0, 0.584, 0.658, 0.6934, 0.7949, 0.8807]` | 132 |
| **3** | bicycle | 2,000.0 m | NACH | 140 | 0.0000 | 0.7650 | 1.2715 | `[0.0, 0.0, 0.8396, 1.011, 1.1625, 1.2715]` | 132 |
| **4** | motor_vehicle | 10,000.0 m | NAIN | 76 | 0.0000 | 0.6446 | 0.7406 | `[0.0, 0.5983, 0.6291, 0.6639, 0.7312, 0.7406]` | 70 |
| **5** | motor_vehicle | 10,000.0 m | NACH | 76 | 0.0000 | 0.7572 | 1.1620 | `[0.0, 0.2067, 0.8499, 0.9473, 1.064, 1.162]` | 70 |

### 3. 六張語法熱圖（基地內路段五級分位：深藍→青綠→綠→橙→紅）

每圖圖例都標出五級的基地內線段數及該圖使用的局部分位值。底圖顯示淡化的 OSM 2 km 周邊水體、建築與路網；基地內有候選值的線段以五級色階強調，無候選值的基地內線段以灰色虛線表示。這些分級只描述各圖所示線段的相對分布，不能跨模式或圖層直接比較數值。

![圖 6：行人 800m 整合度熱圖](../../artifacts/w5-site-analysis/figures/fig06_syntax_local_800m_integration.png)
*圖 6：行人 800 m NAIN。各級線段數 `[96, 95, 95, 95, 96]`，共 477 段基地內有值路段。*

![圖 7：行人 800m 穿行度熱圖](../../artifacts/w5-site-analysis/figures/fig07_syntax_local_800m_choice.png)
*圖 7：行人 800 m NACH。各級線段數 `[96, 95, 95, 95, 96]`，共 477 段基地內有值路段。*

![圖 8：自行車 2km 整合度熱圖](../../artifacts/w5-site-analysis/figures/fig08_syntax_mid_2000m_integration.png)
*圖 8：自行車 2,000 m NAIN。各級線段數 `[27, 26, 26, 26, 27]`，共 132 段基地內有值路段。*

![圖 9：自行車 2km 穿行度熱圖](../../artifacts/w5-site-analysis/figures/fig09_syntax_mid_2000m_choice.png)
*圖 9：自行車 2,000 m NACH。各級線段數 `[29, 24, 26, 26, 27]`，共 132 段基地內有值路段。*

![圖 10：汽車 10km 整合度熱圖](../../artifacts/w5-site-analysis/figures/fig10_syntax_regional_10000m_integration.png)
*圖 10：機動車 10,000 m NAIN。各級線段數 `[14, 14, 14, 14, 14]`，共 70 段基地內有值路段。*

![圖 11：汽車 10km 穿行度熱圖](../../artifacts/w5-site-analysis/figures/fig11_syntax_regional_10000m_choice.png)
*圖 11：機動車 10,000 m NACH。各級線段數 `[14, 14, 14, 14, 14]`，共 70 段基地內有值路段。*

---

## (g) 周邊都市關係與區位結構（Regional Urban Context）

### 1. OSM 2 km context 的資料範圍
- 周邊 OSM 快照含 21,045 個建築面、1,135 個綠地面、103 個水體面及 4,862 條道路線圖徵。這些數量未按用途、人口或通行狀態分類。
- 圖 12 以同一快照作區域位置參考；未由該圖徵清單驗證社區人口、設施服務、交通屏障高度、步行心理感受或公共空間品質。

### 2. 水系與道路圖層
- 周邊水體與道路可在 OSM context 圖層中查看；本次分析沒有水上客運服務、道路容量、出行時間或交通量資料，因此不對服務可用性或運輸效能作判斷。

![圖 12：M4H 基地與鹿特丹區域城區、水系及幹道關係圖](../../artifacts/w5-site-analysis/figures/fig12_regional_urban_relationships.png)
*圖 12：StudyArea v5 與 2 km OSM 水體、綠地及道路圖層；不表示人口、用途或交通服務判讀。*

---

## (h) SWOT 綜合分析（潛力、限制、優點、缺點）

以下把可量測的條件與尚未驗證的解讀並列；它們是後續設計評估的輸入，不構成空間品質、可建性或方案優劣的判斷。

| 編號 | 可查核的現況條件 | 數值與規模 | 引用證據 ID / 檔案來源 | 未支持的推論 |
|---|---|---|---|---|---|
| S1 | 幾何殘差尚未分類 | 138,891.77 m²（61.44%） | `claim-w5-site-016` | 地表材質、用途與可開發性未知。 |
| S2 | BGT 水體及其幾何介面可量測 | 42,473.00 m²；介面 1,332.04 m | `claim-w5-site-014/015` | 不證明護岸型式、航行、親水性或風險。 |
| S3 | 部分 BAG 圖徵有 3D BAG 高度配對 | 31 個；中位數 9.85 m | `claim-w5-site-005` | 不證明現地保存、結構安全或再利用適宜性。 |
| S4 | OSM 綠地圖徵有可計算的裁切面積 | 21,886.06 m²；21 個相交圖徵 | `claim-w5-site-017` | 不證明公眾進入權或植被狀態。 |
| W1 | 道路標籤長度與去重幾何長度有不同口徑 | 去重長度 8,496.54 m | `claim-w5-site-008/009` | 不證明公共通行、連通品質或交通量。 |
| W2 | StudyArea 邊界與道路線相交 | 22 個幾何交點 | `claim-w5-site-010` | 不等於已核實出入口。 |
| O1 | 2 km OSM context 快照保留多類圖徵 | 建築 21,045；道路 4,862 | `claim-w5-site-012` | 不得推定人口、住宅或設施需求。 |
| O2 | 六層 PST 候選值可供探索性比較 | 行人 800 m NAIN 最大值 1.2729 | `claim-w5-site-018/024` | 最大值路段為 imputed 且無名稱；不支持 Marconistraat 出入口解讀。 |
| T1 | BAG 特徵與 3D BAG 高度並非完全配對 | 無高度配對圖徵需保留 UNKNOWN | `claim-w5-site-005` | 登記狀態不單獨證明現地狀態。 |
| T2 | 路網、土地使用、可達性與地籍等資料有缺項 | 詳見資料缺口表 | `claim-w5-site-013/025` | 本報告不評估方案或提供設計決策。 |

---

## (i) 資料缺口登錄與補充建議（Data Gaps & Actionable Recommendations）

下列項目未由本次保留的資料與程式驗證。此處只標示證據缺口，不把缺少資料改寫成全域不存在，也不推定未來的設計結論。

### 1. 資料缺口登錄清冊（Data Gap Register）

| 缺口領域 | 欄位名稱 | 當前系統狀態 | 對都市設計之實質衝擊 | 建議補充資料來源與採購/獲取路徑 |
|---|---|---|---|---|
| **地籍／產權** | `cadastral_ownership` | 專案程式標示 `NOT_APPLICABLE_IN_STUDY_AREA_SCOPE`；本次報告未驗證登記 | 未取得地塊所有權或租賃界線證據 | `src/urban_design/site_analysis.py` | 未形成地籍結論。 |
| **公共通行權** | 道路通行狀態 | 本次資料未驗證 | OSM 幾何和 `highway` 標籤不記錄本次審查所需的通行權與管制狀態 | 本次輸入資料範圍 | 不由道路長度或交點推定公眾可通行。 |
| **無障礙環境** | 無障礙設施與路面品質 | 本次資料未驗證 | 沒有可支持坡度、路緣或連續無障礙通路的觀測欄位 | 本次輸入資料範圍 | 不推定無障礙條件良好或不足。 |
| **實際租戶與用途** | 現況租戶清冊 | 本次資料未驗證 | BAG 登記用途及 OSM 圖徵數不能識別實際營運者或使用率 | 本次輸入資料範圍 | 不由登記用途推定實際使用。 |
| **微氣候與風環境** | `local_microclimate_wind` | `UNVERIFIED_E5` | 本次資料沒有基地尺度風環境模擬結果 | `data-gap-register.json`; `src/urban_design/site_analysis.py` | 不對風舒適或風險作判斷。 |
| **零售可達性** | Grocery / retail accessibility | `BLOCKED` | 必要空間政策未批准，本次未計算 | `src/urban_design/site_analysis.py` | 未批准前不推算結果。 |

### 2. 後續查證項目
1. 在將 StudyArea 用於正式設計或法定分析前，依專案流程另行確認設計邊界及必要核准。
2. 如後續工作需要，就地確認建築現況、通行權、無障礙條件、租戶用途及岸線構造，並記錄資料來源、日期與限制。
3. 若需評估零售可達性或風環境，先滿足各自的專案政策與方法前置條件；本報告不產生這些分析結果。

---

## 結論引用索引表（Claims Register）

原始 25 項主張逐條交叉審查，保留 24 項；claim-w5-site-011 標為 REMOVE 並自 claims.json 移除。完整保留主張存於 `artifacts/w5-site-analysis/claims.json`，逐條審查理由見 `artifacts/w5-site-analysis/review-codex.md`。

| Claim ID | 所屬章節 | 核心陳述摘要 | 檢驗數值 | 來源檔案或證據卡 ID | 證據層級 |
|---|---|---|---|---|---|
| `claim-w5-site-001` | 範圍與資料來源 | Rotterdam M4H StudyArea v5 是供探索使用、經人工確認的研究範圍，... | `226064.325714` m² | `artifacts/week4-repair-r02/syntax/study-area.geojson; matching context snapshot: ~/.local/share/urban-design-data/context/context-20260927T153054Z/study-area-v5.geojson` | COMPUTED_RESULT |
| `claim-w5-site-002` | 既有建築 | StudyArea v5 範圍內共有 51 個 BAG 建築面圖徵；圖徵數不等於現地建築棟... | `51` features | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; artifacts/week4-repair-r03/evidence-bundle.json#card-r03-bag_building_footprint_count-9cedebac22a23cae` | COMPUTED_RESULT |
| `claim-w5-site-003` | 既有建築 | 51 個 BAG 建築面圖徵裁切至 StudyArea 後的幾何聯集面積為 44,699.... | `44699.556694` m² | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; artifacts/week4-repair-r03/evidence-bundle.json#card-r03-bag_building_footprint_area-71df3071d6ce665e` | COMPUTED_RESULT |
| `claim-w5-site-004` | 既有建築 | BAG 建築面聯集佔 StudyArea 面積 19.77%；這是幾何比率，不是法規建蔽率... | `19.772937` % | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson + StudyArea; computed as footprint union / StudyArea area` | COMPUTED_RESULT |
| `claim-w5-site-005` | 既有建築 | 3D BAG v2025.09.03 高度表可與基地內 51 個 BAG 特徵配對出 31... | `9.85` m | `~/.local/share/urban-design-data/3dbag/height-table-v2025.09.03-study-area-v5-buffer500m.json + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson` | COMPUTED_RESULT |
| `claim-w5-site-006` | 既有建築 | 依 PD-11 floor-estimate-v1 與 3.0 m FIXTURE_ONL... | `175984.03` m² | `~/.local/share/urban-design-data/3dbag/height-table-v2025.09.03-study-area-v5-buffer500m.json + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; docs/decisions/2026-09-25-plan-decisions-zh.md (PD-11)` | COMPUTED_RESULT |
| `claim-w5-site-007` | 既有建築 | 51 個 BAG 建築面圖徵中，31 個有登記用途欄位、20 個為空白；19 個特徵的用途... | `31` features | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson; artifacts/week4-execution-r25-20260924T113401Z/browser-run/report.json#card-r04-bag_registered_gebruiksdoel_features-f518e91a8d407773` | COMPUTED_RESULT |
| `claim-w5-site-008` | 道路與交通 | 基地內去重複之 OSM 道路中心線聯集總長度為 8,496.54 m。... | `8496.540522` m | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson; artifacts/week4-execution-r25-20260924T113401Z/browser-run/report.json#card-r04-osm_highway_unique_centerline_length-7532d933e2f11866` | COMPUTED_RESULT |
| `claim-w5-site-009` | 道路與交通 | 依 OSM highway 標籤裁切後各類中心線長度合計 8,501.23 m（含重疊線段... | `3424.987919` m | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson` | COMPUTED_RESULT |
| `claim-w5-site-010` | 道路與交通 | OSM highway 線幾何與 StudyArea 邊界產生 22 個互異交點；交點僅為... | `22` distinct_boundary_intersections | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson + artifacts/week4-repair-r02/syntax/study-area.geojson` | COMPUTED_RESULT |
| `claim-w5-site-012` | 機能與土地使用 | 2 km OSM context snapshot 含 21,045 個建築面、1,135... | `21045` buildings | `~/.local/share/urban-design-data/context/manifest.json + ~/.local/share/urban-design-data/context/context-20260927T153054Z/{buildings,green,water,roads}.geojson` | DATASET_OBSERVATION |
| `claim-w5-site-013` | 機能與土地使用 | 本次 OSM 路網抽取沒有獨立 amenity 或 landuse 多邊形；點狀標籤與 B... | `UNKNOWN` status | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/osm-overpass-v5-epsg28992.geojson` | DATA_GAP |
| `claim-w5-site-014` | 開放空間與水體 | 基地內 BGT 登記水體面積為 42,472.998 m²，佔基地總面積 18.79%。... | `42472.997678` m² | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bgt-waterdeel-p001-epsg28992.geojson; artifacts/week4-repair-r03/evidence-bundle.json#card-r03-bgt_waterdeel_area-67f47470e954c0bb` | COMPUTED_RESULT |
| `claim-w5-site-015` | 開放空間與水體 | 基地內 BGT 水體聯集邊界中，扣除貼近 StudyArea 邊界的裁切線後，幾何水陸介面... | `1332.04` m | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bgt-waterdeel-p001-epsg28992.geojson + StudyArea geometry` | COMPUTED_RESULT |
| `claim-w5-site-016` | 開放空間與水體 | 基地面積扣除 BAG 建築基底與 BGT 水體聯集後的未分類幾何殘差為 138,891.7... | `138891.771343` m² | `artifacts/week4-repair-r02/syntax/study-area.geojson + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bag-pand-*.geojson + artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/sources/normalized/pdok-bgt-waterdeel-*.geojson; artifacts/week4-execution-r25-20260924T113401Z/browser-run/report.json#card-r04-unclassified_surface_residual_area-e0f816172e96540c` | COMPUTED_RESULT |
| `claim-w5-site-017` | 開放空間與水體 | StudyArea 內與 OSM 綠地相交的 21 個圖徵總裁切面積為 21,886.06... | `21886.06` m² | `~/.local/share/urban-design-data/context/context-20260927T153054Z/green.geojson` | COMPUTED_RESULT |
| `claim-w5-site-018` | Space Syntax | PST 3.3.1 行人 800 m NAIN 候選值的中間五分位（Q40–Q60）為 [... | `1.2729` NAIN (normalized) | `~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 0) + ~/.local/share/urban-design-data/week5-syntax-modes/extracted/network_pedestrian_1500m.geojson` | COMPUTED_RESULT |
| `claim-w5-site-019` | Space Syntax | PST 3.3.1 行人 800 m 角穿行度（NACH）最高值 1.4713，平均值 0... | `1.4713` NACH (normalized) | `~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 1)` | COMPUTED_RESULT |
| `claim-w5-site-020` | Space Syntax | 自行車 2,000 m（RVV 法規路網）角整合度 NAIN 最高 0.8807，平均 0... | `0.8807` NAIN (normalized) | `~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 2) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_2000m_4000m_vs_6000m.json` | COMPUTED_RESULT |
| `claim-w5-site-021` | Space Syntax | 自行車 2,000 m（RVV 法規路網）角穿行度 NACH 最高 1.2715，平均 0... | `1.2715` NACH (normalized) | `~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 3) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_2000m_4000m_vs_6000m.json` | COMPUTED_RESULT |
| `claim-w5-site-022` | Space Syntax | 汽車 10,000 m 角整合度 NAIN 最高 0.7406，平均 0.6446，經 1... | `0.7406` NAIN (normalized) | `~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 4) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_10000m_15000m_vs_20000m.json` | COMPUTED_RESULT |
| `claim-w5-site-023` | Space Syntax | 汽車 10,000 m 角穿行度 NACH 最高 1.1620，平均 0.7572，Spe... | `1.162` NACH (normalized) | `~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json (Layer 5) + ~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/stability_10000m_15000m_vs_20000m.json` | COMPUTED_RESULT |
| `claim-w5-site-024` | Space Syntax | 空間語法自製引擎比對 method-comparison-v1 判定為 FAIL（95 百... | `FAIL` status | `docs/decisions/2026-09-25-plan-decisions-zh.md (PD-15)` | PROJECT_DECISION |
| `claim-w5-site-025` | 資料缺口與建議補充 | 本次保留的資料與程式未驗證正式地籍／產權、公共通行權、無障礙環境、實際租戶使用及微氣候風環... | `UNKNOWN_BLOCKED` status | `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/data-gap-register.json; src/urban_design/site_analysis.py` | DATA_GAP |

---

## 附錄：重現指令與執行環境

需要 macOS 上的 QGIS LTR Python：`/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3`。專案 `.venv` 沒有 matplotlib；不可用 `.venv` 重繪 PNG。下列命令從專案根目錄執行，不下載或安裝套件：

```sh
MPLCONFIGDIR=/private/tmp/w5-site-analysis-mplconfig \
PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj \
PYTHONPATH=src:scripts PYTHONDONTWRITEBYTECODE=1 \
/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 \
scripts/build_site_analysis_report.py --skip-figures
```

重繪 12 張 PNG 使用：

```sh
MPLCONFIGDIR=/private/tmp/w5-site-analysis-mplconfig \
PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj \
PYTHONPATH=src:scripts PYTHONDONTWRITEBYTECODE=1 \
/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 \
scripts/render_site_analysis_maps.py --output-dir artifacts/w5-site-analysis/figures
```

`tests/test_site_analysis_report.py` 會在目前測試直譯器找不到 matplotlib 時略過圖形重繪測試；PNG 格式與檔案大小檢查仍會執行。Matplotlib 設定快取使用 `/private/tmp/w5-site-analysis-mplconfig`。

*報告結束 · Generated deterministically by build_site_analysis_report.py · 2026-09-27*
