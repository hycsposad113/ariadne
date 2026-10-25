# Rotterdam M4H 空間問題定義報告

## 審查紀錄

- **原作者：** AntiGravity（Gemini 3.8 Flash）
- **審查者：** Codex（OpenAI；本次執行環境未提供可驗證的精確模型 ID）
- **審查日期：** 2026-09-28
- **審查標的：** 分支 `wp/w6-problem-definition` 的原作者版本 commit `2a2afca`
- **審查方式：** 讀取本地凍結輸入、重新執行確定性空間計算、比對每個輸出指標、GeoJSON 與圖面；未呼叫網路或 Live AI。
- **重算命令：** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts MPLCONFIGDIR=/private/tmp/w6-problem-definition-mplconfig PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj .venv/bin/python scripts/build_problem_definition.py --output-dir artifacts/w6-problem-definition`
- **修正摘要：** 重算 BAG 外環比較、OSM 座標頂點與路徑代理值、PST NAIN、OSM 綠地幾何、水陸界面及幾何差額；移除沒有來源支持的地表材質、工廠名稱、封閉程度、廊道缺口及人流結論；所有嚴重度改由版本化規則計算。

本報告與 `artifacts/w6-problem-definition/review-codex.md` 是交叉審查紀錄，不是設計者接受、設計約束啟用或總體方案決定。問題 6 仍是待設計者確認的候選項目；本次沒有建立 HumanDecision。

## 判讀與嚴重度規則

所有面積、長度與距離均在 EPSG:28992（RD New，公尺）計算。比例只使用下述資料分母；未觀測狀態維持未知。嚴重度規則版號為 `s2-review-bands-v1`，是本次審查的排序帶，不是法規、規劃標準或設計品質評分。

| 規則 | 計算方式 | 分級帶 |
|---|---|---|
| `relative_coverage_v1` | 基地比例 ÷ StudyArea 外側 0–800m 環比例 | ≤0.25 CRITICAL；≤0.50 HIGH；≤0.75 MODERATE；>0.75 LOW；缺參考值則 UNRATED |
| `detour_vs_direct_v1` | 取樣網絡繞行比均值 ÷ 直線距離下界 1.0 | ≤1.0 LOW；≤1.25 MODERATE；≤1.50 HIGH；>1.50 CRITICAL；缺值則 UNRATED |
| `measured_share_v1` | 量得的面積或界面比例 | ≤10% CRITICAL；≤25% HIGH；≤50% MODERATE；>50% LOW |
| 無語意／比較基準 | 不對幾何差額或無外部參考的拓撲值強行分級 | UNRATED |

因此本次分級為：問題 1 CRITICAL（住宅登記比例相對外環為 0）；問題 2 HIGH（取樣繞行均值 1.49）；問題 3 UNRATED（沒有周邊 NAIN 比較值）；問題 4 CRITICAL（OSM 綠地標籤比例 9.68%）；問題 5 HIGH（鄰近所選 OSM 路線的界面比例 15.26%）；問題 6 UNRATED（幾何差額不能單獨表示不利程度）。這些代碼只反映上述審查帶。

## 輸入、來源與重現性

- **StudyArea v5：** 226,064.33 m²；BGT 水體聯集 42,473.00 m²；幾何陸域 183,591.33 m²。輸入為 `artifacts/week4-repair-r02/syntax/study-area.geojson`，SHA-256 `b96aa5625a9d2e8c4163cf2e88fb31c74b9a0f5b94aef5434ecd3295607a82ea`。
- **PDOK/Kadaster BAG、BGT 及 OSM 道路：** 使用本地正規化 GeoJSON；其 `source-and-integrity-manifest.json` 為 `m2-a03-spatial-source-integrity-v1`，記錄 52 個來源快照與 52 個正規化產物，狀態 `READY_FOR_HUMAN_REVIEW`。版本範圍為 2026-09-21 19:46:21–19:51:51 UTC，擷取時間範圍為 19:46:20.768385–19:51:53.716182 UTC。來源授權欄記載 PDOK/Kadaster 開放資料條款（發布前應再核對）與 ODbL 1.0。該 manifest SHA-256 為 `c1456e51d34402fd280dfee10ef28fd34f53195955d990a07be79a7185f85c09`。
- **來源查詢範圍：** BAG 建築用途用於基地及基地外側 0–800m 幾何環；BGT `waterdeel` 幾何與 StudyArea 相交；OSM 道路線先以陸域幾何裁切再計算。詳細快照與正規化檔案雜湊均記錄在 `problem-summary.json` 的 `metadata.source_inventory.inputs`。本次沒有重新送出來源查詢。
- **OSM 綠地：** 本地 context run `context-20260927T153054Z`；資料版本 `2026-09-22T20:22:59Z`；ODbL 1.0，署名 © OpenStreetMap contributors，EPSG:28992。manifest 的 `retrieved_at` 欄為 null，故不推定精確擷取時間。`green.geojson` SHA-256 為 `b810415d546761498eea4db84933bfca6cb6b47a62eac610296e0c9f0e753581`。
- **PST 候選層：** 本地 `syntax_six_layer_candidate.json` SHA-256 `fde6d49b4f41135316d6b432b690697233c77f0b91c3df6f22363b5eef4b5900`；只使用 layer 0 的 StudyArea `segment_values`。來源狀態為 `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`，沒有周邊 NAIN 比較值。
- **工具與方法：** Python 3.12.13、Shapely 2.1.2、PST 標記 `PST_3.3.1_EXPLORATORY`；六張圖由 QGIS Python 3.9.5 與 Matplotlib 3.3.0 渲染。建置方法版號 `deterministic_spatial_indicators_s2_review_v2`。所有輸入檔案路徑、大小與 SHA-256 已寫入輸出 summary。

方法參數包括外環 800m、北側選取 `y > 436000m`、邊界點 5m 聚類、道路座標精度 0.1m、90m 路網取樣、150m 最近點吸附、點對直線距離 120–450m、繞行比上限 6、OSM 綠地片段面積門檻 5m²、綠地最近距離門檻 40m、水岸 OSM 路線距離 22m、幾何差額 GeoJSON 匯出門檻 5,000m²。參數也記錄在 `problem-summary.json` 的 `metadata.method_parameters`。

## 六項問題與校正結果

各表的 `PASS` 表示重算支持該數值；`FIX` 表示更正舊值、分母或語意；`REMOVE` 表示沒有可重現依據，不再作為結論。完整逐項核對見 [Codex 交叉審查紀錄](../../artifacts/w6-problem-definition/review-codex.md)。

### 1. BAG 建築用途標籤與登記狀態

基地內 51 個相交 BAG 建築圖徵包含 43 個已知用途標籤；StudyArea 外側 0–800m 環有 3,762 個 BAG 圖徵與 3,395 個已知用途標籤。該環是平面幾何環，不是步行服務區。

| 指標 | 重算值 | 審查 |
|---|---:|---|
| 用途標籤 Shannon 指數：基地／外環 | 1.5171／1.0930 | PASS |
| woonfunctie 標籤：基地／外環 | 0/43 = 0.00%／2,423/3,395 = 71.37% | FIX：外環舊值更正為 71.37% |
| industriefunctie 標籤：基地／外環 | 19/43 = 44.19%／276/3,395 = 8.13% | FIX：更正舊外環比例 8.64% |
| 用途欄缺漏／BAG 狀態 `Pand gesloopt` | 20／19 個圖徵 | FIX：是兩種不同狀態，不表示現場空置或拆除 |
| 缺漏或 `Pand gesloopt` 條件聯集 | 29/51 個圖徵；兩條件重疊 10 個 | FIX：不能把 20 與 19 相加稱為閒置率 |

「Keileweg 兩側原食品加工廠房」沒有來源支持，REMOVE。BAG 登記用途不能證明實際營運或居住。

### 2. OSM 座標頂點、道路線多邊形化與取樣繞行比

| 指標 | 重算值 | 審查 |
|---|---:|---|
| OSM 座標頂點 degree ≥3 數／密度 | 197 個／10.73 vertices/ha（陸域 18.3591ha） | FIX：不是完成切分、驗證通行性的交叉口密度 |
| OSM 座標頂點 degree =1 | 44 個 | FIX：不是 141 個死巷；degree-one 頂點不等同死巷 |
| 取樣網絡繞行比均值／最大值／樣本點對 | 1.49／2.46／57 | FIX：取代 1.56／3.39；直線下界 1.0，不代表現場步行時間 |
| BAG footprint 最小旋轉矩形最大長軸 | 213.02m | FIX：不是 251.5m 連續阻隔；不指名 Keilepand |
| OSM 道路總長／`highway=service` 長 | 8,424.18m／3,424.99m = 40.66% | FIX：OSM 標籤不代表專供貨運或車行 |
| 所選步行／騎行類標籤線長 | 3,472.79m = 總長的 41.22% | PASS：與 service share 同分母 |
| 長軸 ≥80m footprint／多邊形化面積 >1ha | 6 個／3 個 | PASS：是明示幾何篩選結果，不表示阻隔或地籍街廓 |

道路頂點圖沒有對每條線的內部交點重新切分，也未建模立體交叉、門禁、坡度或通行權。嚴重度 HIGH 由均值 1.49 對 1.0 直線下界套用 `detour_vs_direct_v1` 產生。

### 3. 邊界幾何交點與拓撲整合度

| 指標 | 重算值 | 審查 |
|---|---:|---|
| StudyArea 全邊界 OSM 線幾何交點 | 22 個點（5m 聚類） | PASS：幾何交點，不宣稱可通行穿越 |
| `y > 436000m` 選取區交點 | 12 個點 | FIX：不是基地交叉口數，也不證明北側通道數 |
| PST 行人 800m NAIN 候選層平均 | 0.7828，481 個 segment values | FIX：使用來源值重算；來源邊界穩定性未評估 |
| NAIN = 0 的 segment | 1/481 | FIX：舊值 10 不成立 |
| 基地與周邊 NAIN 差值 | 無周邊值，不能計算 | REMOVE：`−0.2606`、基地 0.7806 與周邊 1.0412 沒有來源支持 |

本項只能描述路網的**拓撲整合度**。不推論人流、出行量、犯罪或社會隔離；嚴重度為 UNRATED。

### 4. OSM 綠地標籤面積與多邊形間距

| 指標 | 重算值 | 審查 |
|---|---:|---|
| OSM 綠地標籤多邊形聯集 | 21,876.82m²／StudyArea 226,064.33m² = 9.68% | PASS：描述 OSM 標籤幾何 |
| 面積 >5m² 的多邊形片段 | 18 個 | PASS：片段數，不等於 18 個孤立綠地 |
| 最近其他片段距離 >40m 的片段 | 1 個 | FIX：以幾何距離門檻計數 |
| 南北廊道缺口 | 沒有可重現量測 | REMOVE：450m 為硬編碼，亦沒有 25% 綠地目標來源 |

OSM 標籤不測量樹冠、植被覆蓋、地表材質、公共進入權或生態連通。嚴重度 CRITICAL 是 9.68% 對 `measured_share_v1` 的結果，不是生態規範判定。

### 5. 水陸幾何界面與 OSM 選定標籤路線鄰近度

| 指標 | 重算值 | 審查 |
|---|---:|---|
| BGT 水體與 StudyArea 內部幾何界面 | 1,330.20m | FIX：界面線取自 BGT 水體邊界與 StudyArea 相交，扣除外邊界 0.8m 緩衝 |
| 距所選 OSM 路線 ≤22m 的界面 | 202.94m／1,330.20m = 15.26% | FIX：是幾何鄰近比例，不是公眾可達比例 |
| 不在上述 22m 鄰近範圍的界面 | 1,127.26m（84.74%） | FIX：不是封閉、私有或物流專用岸線 |

納入 highway 標籤 `footway`、`pedestrian`、`path`、`cycleway` 且未明確標示 `access=no/private` 的 OSM way；缺少 access 標籤仍可進入候選。舊界面 1,332.04m、可達 198.94m、14.9% 及「阻隔岸線」數值不再使用。嚴重度 HIGH 只按 15.26% 審查帶產生；不代表公共通行權。

### 6. 非建築／非水體幾何差額（待確認候選）

| 指標 | 重算值 | 審查 |
|---|---:|---|
| StudyArea 減去 BGT 水體與 BAG footprint 聯集後的幾何差額 | 138,891.77m²／226,064.33m² = 61.44% | FIX：只稱幾何差額 |
| BAG footprint 聯集／StudyArea 水體 | 44,699.56m²／42,473.00m² | PASS |
| 幾何差額 Polygon 片段／面積 >5,000m² 匯出片段 | 2／1 | FIX：5,000m² 是圖層匯出門檻，不代表價值或嚴重度 |

沒有地表材質、樹冠、空置、所有權、土地用途或可開發性資料。因此「瀝青與混凝土覆蓋」「無樹冠瀝青與碎石」「空置貨櫃場」「荒廢地表」均 REMOVE；問題 6 仍為 `PENDING_DESIGNER_CONFIRMATION`，嚴重度 UNRATED。

## 語意修正與輸出

以下句子沒有可重現來源，已從文件、圖例、GeoJSON 屬性或摘要移除：碼頭前沿「完全由瀝青與混凝土覆蓋」、地面由「無樹冠瀝青與碎石佔據」、「優質水岸資源完全被浪費」、「全區深陷邊緣化封閉孤島狀態」、Keileweg 兩側原食品加工廠房。`CRITICAL`／`HIGH` 等代碼僅由文件列明的 S2 門檻生成。PST 整合度只標為拓撲指標。

六個 GeoJSON、`problem-statements.json`、`problem-summary.json` 與六張 PNG 已由同一次分析重建；summary 內含方法參數、嚴重度規則、工具版本與所有輸入雜湊。圖例僅標出實際輸出的幾何類型與其篩選定義。

`api.py` 的問題列表、單項與 GeoJSON 路由僅使用 GET 並讀取上述靜態產物；測試會確認三個 GET 回應前後 SQLite 檔案及產物 SHA-256 不變。

## 本次測試

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_problem_definition.py`：10 passed，1 warning，2.73 秒。
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider`：901 passed，2 skipped，4 failed，9 warnings，562.46 秒。四個失敗皆因目前 worktree 缺少既有 `.urban_design_runtime/rotterdam-m4h-pilot-project.qgs` 或兩個歷史 StudyArea GeoJSON 快照；失敗項為 `test_project_has_an_unambiguous_visible_identity`、`test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path`、`test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit`、`test_r02_archive_remains_intact_and_reports_exact_current_source_drift`。這些是環境前置檔案缺失，未補建或複製 runtime 狀態；完整套件因此未全綠。
