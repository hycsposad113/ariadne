# Metabolic Engine 原設計基準（草稿）

## 狀態與用途

本組輸出把 Jack 的 Vierhavenblok（M4H）portfolio 圖面轉為可供平台載入與比較的**草稿基準**。它保存人類原設計的空間意圖，供後續與 AI 參與的設計流程比較；不代表已核准的基地界線、法定分區、保存清冊、建築許可、工程圖或設計決策。

依工程原則，幾何轉錄與指標均標為估算或 `FIXTURE_ONLY`。設計者仍保有採納或更改範圍、機能、密度與方案的決定權。兩套強度檔案是任務指定的假設輸入，沒有建立 HumanDecision。

## 範圍與來源

- 使用主 repo 的 `artifacts/week4-repair-r02/syntax/study-area.geojson`，EPSG:28992（RD New，公尺）。StudyArea v5 幾何面積為 **226,064.33 m²**；依正規化 BGT 水體面裁切後，水體為 **42,473.00 m²**、陸地為 **183,591.33 m²**。這是探索範圍，不是正式 DesignBoundary。
- 平面底圖為本目錄 `artifacts/portfolio-baseline/pages/p15-hires-15.png`；分區／Tree Map 取自 `p18-18.png`，景觀參考 `p19-19.png`、公共空間參考 `p20-20.png`。p09、p16、p17 與 p04 用作原用途、策略與目標的文字／圖像參考。
- 使用既有正規化 BAG pand、BGT waterdeel、OSM 線資料。既有來源清冊記錄 PDOK/Kadaster 與 OSM 的來源、擷取時間及授權；此處只讀取本機快照，沒有新下載。PDOK/Kadaster 授權依快照清冊標為其開放資料條款，公開再用前應核實當期條款；OSM 授權為 ODbL 1.0。3D BAG 高度表若存在則只列入參考，版本 v2025.09.03、CC BY 4.0，不用來推定設計樓層。
- `georef.json` 記錄輸入路徑與 SHA-256。腳本重算時會讀取來源，不改寫來源或權威 DB。

## 圖面對位

以 p15 與 p18 兩張 raster 的影像特徵配準建立頁面間對位，再將 p15 像素座標以最小平方法仿射配準到 EPSG:28992。控制點共 10 個：4 個 p18 虛線圖框與 StudyArea v5 頂點、p15 #5/#7/#9/#17 紅色建築中心與候選 BAG pand 輪廓、1 個 Keileweg 與 OSM 中心線、1 個港池岸線與 BGT waterdeel 邊界。逐點殘差保存在 `georef.json`。

- p15 多源控制點 **RMSE = 17.96 m**；p18 圖框四點單獨配準 **RMSE = 4.16 m**。
- 配準後檢核點至 Keileweg 最近中心線距離 **6.45 m**，至最近 BGT 港池邊界 **3.19 m**。
- 四個 BAG 建築控制點殘差約 14.88–40.72 m。設計圖未提供地理座標；虛線框與 StudyArea「範圍相近」是視覺對照，不是界址測量。此精度只適合區域級比較；不適合地籍、建築邊界或施工定位。
- BAG #5 的候選 pand 狀態標記為 `Pand gesloopt`，和圖面紅色保留表達衝突。該項保留 LOW 信心，不以 BAG 狀態取代設計者圖面，也不宣稱現況保存狀態已查證。

## 保留建築與用途

`preserved-buildings.json` 以 p15 圖例建立 8 筆紅色既有建築對照。ID 是正規化 BAG 中的候選 pand；信心表示空間對應程度，不代表法律身分、結構安全或保存資格。

| 圖號 | 圖面名稱 | BAG pand ID | 新用途／改造意圖 | 加蓋 | 信心 |
|---:|---|---|---|---|---|
| 5 | Art Studio (Current) | `0599100000765601` | Art Studio | 否 | LOW |
| 7 | Museum (Current) / Residence (Artist) | `0599100010058726` | 藝術家住宅，低層保留博物館 | 是 | MEDIUM |
| 9 | Restaurant | `0599100010039532` | Restaurant | 否 | MEDIUM |
| 11 | Art Studio + Office (Current) | `0599100010058726` | Art Studio + Office | 否 | LOW |
| 12 | Design Firm (Current) | `0599100000641255` | Design Firm | 否 | LOW |
| 13 | Leisure + Shopping / Residence（Katoenveem） | `0599100000188925` | 低層休閒／購物，上層住宅 | 是 | LOW |
| 15 | Community Kitchen + Food Bank (Current) | `0599100000641246` | Community Kitchen + Food Bank | 否 | LOW |
| 17 | Maker Space (Current) / Residence (Maker)（Keilepand） | `0599100000752293` | 低層自造空間，上層 maker 住宅 | 是 | HIGH* |

`*` #17 的 HIGH 僅表示圖面中心與候選 BAG 輪廓、Keilepand 名稱的空間對應較強；不表示法律保存或現況狀態已驗證。所有用途文字直接按圖例轉錄；混合用途拆分是圖面意圖，不是樓層登記資料。

## 分區與公共空間

- `zones.geojson` 有 5 個 `PREFERENCE` 多邊形：Energy Hub、Residential + Tidal Park、Art Space + Recreation、Residential、Maker Space + Recycle Hub。
- `open-spaces.geojson` 有 Tidal Park、Central Food Garden、Art Park、Ecology Forest、Ecology Bridge corridor 5 個偏好面。走廊由圖面線位估繪並以 14 m 寬度表達，不是實測橋體寬度。
- 分區依 p18 彩色標籤區域人工描繪；公共空間依 p15 編號與 p19/p20 圖面人工描繪。所有幾何均在 EPSG:28992，裁切至 StudyArea 陸地；它們是低信心偏好範圍，不表示法定地界、公共通行權、洪水安全或種植狀況。公共空間多邊形可能重疊，因此開放空間比以聯集計算。

## Tree Map 機能量與不確定性

`program.json` 將 p18 Tree Map 的**可讀數值**逐項轉錄，單位 m²。可讀值合計為 **109,177 m²**，13 個小字項目標記 `UNREADABLE` 並保留 null；因此這是可讀下限，不是完整總樓地板面積。

| 類別 | 可讀小計（m²） | 佔可讀小計 | 狀態 |
|---|---:|---:|---|
| 住宅 | 52,566 | 48.1475% | 部分下限 |
| 自造與產業 | 42,566 | 38.9881% | 部分下限 |
| 辦公 | 600 | 0.5496% | 部分下限 |
| 設施 | 13,445 | 12.3149% | 部分下限 |

百分比的分母只有 109,177 m² 可讀值。**完整 Tree Map 總量、完整類別比例與其 FAR 都是 UNKNOWN**；沒有按方塊面積比例補猜 unreadable 數字。每筆數值含 p18 來源頁與人工轉錄方法。

## 原設計量體與密度指標

`portfolio-scenario.geojson` 以 p15 人工像素框描出圖號 1–18 的建築，包含既有、加蓋與新建意圖，並記錄 BAG 候選 ID、樓層數估值及高度方法。底層／上層採同一估繪足跡重複計算，沒有推估退縮、局部加層或結構可行性；因此不是精細 3D 量體。

| 指標 | 草稿估值 | 來源與計算 |
|---|---:|---|
| 情境估算 GFA | 265,756.19 m² | p15 人工足跡 × 估計樓層，使用 `urban_design.morphology.metrics.calculate_morphology_metrics` |
| 陸地 FAR | 1.4475 | 情境估算 GFA / StudyArea 減 BGT 水體 |
| 完整 StudyArea FAR | 1.1756 | 情境估算 GFA / 含港池的完整 StudyArea |
| 建蔽率估計 | 34.9208% | 情境足跡聯集 / StudyArea 陸地 |
| 開放空間比估計 | 23.3812% | 5 個公共空間偏好面之聯集 / StudyArea 陸地 |
| 圖面代表住宅高度 | 約 17 m | 任務附註稱住宅約 5 層／17 m；屬設計參考，不是測量值 |
| 指標核心最大估計高度 | 18.5 m | 最高估計 5 層，以首層 4.5 m、上層每層 3.5 m 計算 |

**重要一致性檢查：** p15 足跡／樓層估算 GFA 是 Tree Map 可讀下限的 **2.43 倍**。Tree Map 有 13 項 unreadable，且 p15 量體採粗略框線與整層重複，資料不足以判斷差距來自圖面尺度、足跡框選、樓層推估或 Tree Map。故 scenario GFA、FAR、建蔽率及開放空間比均標為 `DRAFT` / `FIXTURE_ONLY`，需要設計者核對後才能作為實質基準。不得把 265,756 m² 說成已驗證的原設計 GFA。

任務提供的附註稱坡道建築接至生態橋並跨越 Dakpark 約 10 m 高差。本次附件中的 `p22-22.png` 實際標題是「Public Space Master Plan」，沒有可核實的量體剖面；因此 5 層／17 m 與 10 m 高差明確作為使用者提供的設計註記，而非宣稱從 p22 圖片量得。坡道建築 18 號的 3 層／11.5 m 是另一項草稿估算，不能與地形高差混為一談。

## 兩套比較強度

兩個 JSON 的 `approval_decision_id` 都按任務要求寫入 `ASSUMED_FROM_PORTFOLIO_2026-09-27`，但同時明確標示 `human_approval_recorded: false` 與 `ASSUMPTION_ONLY_NOT_APPROVED`；這個識別字不是權威決策紀錄。

- A `ASSUMED_FROM_PORTFOLIO`：FAR 上限 **1.592296**（本次低信心量體估算陸地 FAR 1.4475422 × 1.1）；高度上限 20 m、首層 4.5 m、標準層 3.5 m、開放空間偏好至少 23.3812%。由於原設計完整 FAR 未能從 Tree Map 讀取，A 的 FAR 上限只是一項按任務公式推得的暫定參數，不代表已確認原設計強度。
- B `ASSUMED_HIGH_DENSITY`：陸地 FAR 2.0、高度上限 40 m、建蔽率上限 0.5；首層、標準層與開放空間偏好沿用 A。

這些設定是比較用輸入值，不是法規、已啟用限制或採納的設計條件。

## 重現與驗證

在 worktree 根目錄執行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/build_portfolio_baseline.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider
```

腳本只新增／覆寫其九個基準輸出檔，不刪除既有頁面或其他檔案。測試驗證輸出存在、保留 BAG ID 可在正規化 BAG 找到、分區與公共空間落在 StudyArea 陸地、Tree Map 數字具來源，以及量體指標標示 `FIXTURE_ONLY`。本測試是本地程式與資料契約檢查，不代表設計者接受、正式審查通過或可投入生產。
