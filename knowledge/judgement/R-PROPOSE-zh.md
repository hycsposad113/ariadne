# R-PROPOSE 修正提案 v1.2.0

撰寫：Claude Opus 5.5（Commander），2026-10-17；v1.1.0（2026-10-18）加入冬至日照幾何（第一個真模型提案降南側兩棟各一層，重算後中庭冬至平均 0.108 → 0.109 h，幾何上注定無效）。依據 Founder 10-17：AI 修正提案全部可提，但每案需 Founder 在平台按「核准重算」才套用到草稿；正式接受修正後方案仍走決策密語。

## 目的
把一張已通過驗證的判讀卡（J-CLIMATE／J-COMPARE）與設計者的回應，轉成**可由確定性編輯核心執行**的修正提案。模型只決定「改哪裡、改什麼、為什麼」；幾何與數值由程式套用與計算。

## 觸發
判讀卡上設計者按「請 Ariadne 提出修正方案」。前提：該卡為 VALIDATED，且主體方案已有正式草稿（港埠：`formal-draft-formal-fabric-harbour-grain-88445febe1b6`）。

## 輸入組裝（確定性）
| 群組 | 內容 |
|---|---|
| 判讀卡 | 卡片 JSON（judgement、revision_directions、questions_for_designer）＋ card_id、round |
| 設計者回應 | 該卡與先前輪次的同意／質疑／補充原文（含 Founder 已表達立場 seed） |
| 草稿狀態 | 草稿 revision；每棟可編輯建築：`building_id、block_id、floors、height_m、gfa_m2、footprint_area_m2、centroid`；保留建築不可編輯 |
| 中庭關係 | 每個中庭：`courtyard_id、block_id、clear_width_m、area_m2`、**南側相鄰建築** `south_building_ids`（確定性推導：同街廓、質心在中庭南側、與中庭外框距離 ≤ 12 m）、北側／東西側同理 |
| 中庭日照幾何（確定性） | 每個中庭：冬至正午太陽高度 `winter_noon_sun_altitude_deg`（基地緯度 51.9°N ≈ 14.7°）、南側邊緣現況高度（最高／中位數）、`depth_along_sun_m`（沿正午太陽方位的中庭淨深；無資料時以 clear_width_m 近似並標示）、**正午陽光可達中庭北緣的南側高度上限** `h_north_edge_m = depth × tan(高度角)`、可達中庭一半深度的上限 `h_half_m`、達到上限需移除的樓層數、在目錄限制（每棟最多移除 2 層）內是否可行 `feasible_within_catalogue`；若有重算結果，附各中庭冬至平均日照 |
| 約束 | 新建高度上限 20 m；新建 GFA 下限 85%（ASSUMED，124,842 m²）與目前 GFA；保留建築與保留道路不可改 |
| 操作目錄 | 見下 |

## 操作目錄（v1；只能用這些）
| op | 參數 | 執行方式 |
|---|---|---|
| `REMOVE_TOP_FLOOR` | `building_ids[]`、`floors`（每棟移除層數 1–2） | 編輯核心 REMOVE_FLOOR，逐棟逐層 |
| `ADD_FLOOR` | `building_ids[]`、`floors`（1–2，套用後高度 ≤ 20 m） | 編輯核心 ADD_FLOOR |
| `SETBACK_UPPER` | `building_ids[]`、`metres`（1–3，整數） | 分面核心「上兩層退台」 |
| `MOVE` | `building_id`、`dx_m`、`dy_m`（各 ≤ 6 m，整數） | 編輯核心 MOVE（套用後需通過拓撲／重疊驗證） |
| `PLANTING_NOTE` | `target`（open-space 類別或 courtyard_id）、`kind`（deciduous_trees／pergola／both） | **不改幾何**；記錄為設計註記，標示「未納入模擬」 |
| `RERUN` | `analyses[]` ⊆ {E1, UTCI} | 套用後重算（E1 約 10 分鐘、UTCI 數秒） |

一個提案最多 3 個幾何操作群組、最多 24 棟建築；必須至少包含一個 `RERUN`。（v1.2 策略操作另見下節）

## 量體策略操作（v1.2.0，2026-10-18，Claude 撰寫；Founder 10-18 選定「量體策略操作」）

街廓尺度的策略，由確定性程式展開成逐棟的 REMOVE_FLOOR／ADD_FLOOR／分面退縮，再走同一套乾跑、核准重算與再判讀。路網、街廓邊界與保留建築不變。

| op | 參數 | 確定性展開 |
|---|---|---|
| `SOLAR_ENVELOPE` | `courtyard_ids[]`（1–4 個）、`target`（`north_edge`＝正午陽光到中庭北緣／`half_depth`＝到中庭一半深度）、`redistribute`（true／false） | ① 每個指定中庭：門檻高度 H＝`h_north_edge_m` 或 `h_half_m`；`south_building_ids` 每棟逐層移除到高度 ≤ H（至少保留 1 層；首層 4 m 仍高於 H 時標 `ENVELOPE_UNREACHABLE`，該棟只保留 1 層）。② 若 `redistribute`：被移除的樓地板依序加到（a）同街廓 `north_building_ids`、（b）同街廓其他非南側棟、（c）同街廓臨主街棟；每棟加到高度 ≤ 20 m（首層 4＋標準層 3.5，最多 5 層 18 m），加總不超過移除量；不足部分回報 `gfa_shortfall_m2`。③ 不在其他中庭南側名單上的棟才可加層（避免把陰影移到另一個中庭）。 |
| `COURTYARD_WING_DEPTH` | `courtyard_id`、`side`（`south`／`north`／`east`／`west`）、`depth_m`（10–12，整數） | 該側中庭邊緣上的建築，把面向中庭的立面向外推，使進深變成 `depth_m`（原 13 m）；中庭淨深相應增加；所有樓層一起縮（不是退台）；乾跑重算 `h_north_edge_m` 與 GFA。住宅翼深下限 10 m（J12 尺度規格）。 |

一個提案最多 2 個策略操作，可再加至多 1 個逐棟操作群組；總受影響棟數上限提高到 80 棟（策略操作展開後計算）。

### 策略判斷規則
- **先算代價再提**：乾跑會回報 `SOLAR_ENVELOPE` 的移除量、移入量、`gfa_shortfall_m2`、移入的棟（與其北側是否為街道）。提案的 `trade_offs` 必須引用這些欄位：移入北側會增加北側街道或鄰近開放空間的冬季陰影；`gfa_shortfall_m2 > 0` 時說明 GFA 下降與 85% 下限的關係。
- **選中庭**：只對 `feasible_within_catalogue = true` 或 `target = half_depth` 時可達的中庭用 `SOLAR_ENVELOPE`；不可達的中庭要說明（例：courtyard-2 淨深約 26 m，北緣門檻約 6.8 m，只能 1 層，不建議）。
- **與局部日照帶的取捨**：若設計者重視街牆連續，先比較「整段南側包絡」與「局部日照帶（P3 的 REMOVE_TOP_FLOOR 少數棟）」的代價，讓設計者選，不要直接選最激烈的。
- **重算必須含 E1**；有移入北側時建議同時跑 UTCI。
- 不承諾效果：expected_effects 只寫方向，提醒「北側街道冬季日照可能下降，需看重算」。

### 驗證追加
- `SOLAR_ENVELOPE.courtyard_ids` 必須存在且有 `solar_geometry`；`target` 值域檢查。
- `COURTYARD_WING_DEPTH.depth_m` 10–12 整數；該側必須有建築。
- 展開後的每棟操作仍受 20 m、樓層 ≥ 1、無重疊、拓撲檢查。
- 乾跑 `strategy_report`：每個策略的移除／移入棟清單、樓地板量、`gfa_shortfall_m2`、`ENVELOPE_UNREACHABLE` 棟、受影響中庭的新 `h_north_edge_m`（WING_DEPTH）與 `solar_access_check`（應全部 `reaches_north_edge = true` 才算包絡成功）。


## 輸出（JSON）
`proposal_id`（由程式產生）、`responds_to`（card_id＋回應 id）、`summary`（一句話，第一人稱）、`operations[]`、`rationale[]`（每條連到判讀卡的哪個觀察／修正方向或設計者的哪段話）、`expected_effects[]`（定性方向，不寫新數值）、`trade_offs[]`、`risks[]`、`not_simulated[]`（例如植栽）、`questions_for_designer[]`（1–2 題）。

## 判斷規則
- **回應設計者**：若設計者已說「不希望整段打斷長向街牆」，不得提出移除整棟或連續多棟一起降到很低的方案；改用局部（中庭南側少數幾棟）降層或退台。
- **最小有效修改**：先提影響最小、最可能改善判讀弱點的修改；不要一次改滿上限。
- **GFA 自覺**：程式會先試算 GFA；若低於 85% 下限，提案必須同時提出補回方式（例如同街廓北側加一層，仍 ≤ 20 m），或明白標示「需設計者決定是否接受低於下限」。
- **不承諾效果**：expected_effects 只寫方向；效果由重算結果驗證。

### 冬至日照幾何規則（v1.1.0）
- **先算再提**：以「中庭日照幾何」判斷修改是否可能讓冬至正午陽光進入中庭。降層後南側高度仍高於 `h_north_edge_m` 的修改，**不能**當作改善中庭冬陽的方案（只能當作街牆高度或量體調整，並說明對中庭冬陽無效）。
- **選最有機會的中庭**：優先選 `depth_along_sun_m` 最大、`h_north_edge_m` 最高、且有重算數值時冬至平均最低的中庭；不要因為它在清單第一個就選它。
- **在目錄內不可行時要說出來**：若所有中庭 `feasible_within_catalogue = false`，或可行方案需大量降層（GFA 逼近下限、街牆大幅降低），提案必須誠實寫明「以目前密度與 20 m 量體，中庭冬至正午日照在操作目錄內無法達成」，並把選擇交給設計者：（a）接受中庭以夏季遮蔭為主、冬陽目標轉到南向公共空間（街坊公園／水岸），（b）選一個最寬的中庭做南側低層段（2 層以內），以 GFA 與街牆換冬陽，（c）其他由設計者指定。這種情況仍可提出（b）的具體操作供重算驗證，但 risks 必須寫明代價。
- **春分／秋分是另一個尺度**：春秋分正午太陽高度約 38°，降層對春秋分日照較有感；若提案主要改善春秋分而非冬至，expected_effects 要明說是哪一季。
- **局部日照帶 vs 中庭整體**（v1.1.1）：只降南側少數幾棟到 `h_north_edge_m` 以下，會在那幾棟後方形成**局部日照帶**（寬度約等於被降建築的面寬），中庭整體冬至平均不會明顯改變。這是合法的設計策略（例如在日照帶配置冬季座椅與停留邊），但提案必須**明說是局部日照帶**，expected_effects 不得暗示中庭整體改善；若要中庭整體改善，需降低整段南側（並承擔 GFA 與街牆代價），由設計者取捨。
- 這些門檻由程式計算，模型只引用欄位名稱與既有數值，不自行換算新數字。

### 寫作規則（v1.1.1）
- `summary` 只寫設計動作與目的（第一人稱、一句）；**不要寫核准流程、簽署、密語或任何人名**——平台介面已標示「核准重算不是正式接受」。
- 不要在任何欄位寫設計者的名字；稱呼一律用「你」。

## 驗證（確定性；不通過不顯示）
- op 與參數在目錄與範圍內；building_id 存在、可編輯、非保留；套用後高度 ≤ 20 m、樓層 ≥ 1。
- 乾跑（dry-run）套用到草稿副本：幾何有效、無重疊、拓撲通過；回報 GFA 前後與 85% 比較。
- rationale 必須引用判讀卡或設計者回應的實際內容（id 或原句片段）。
- 乾跑另附 `solar_access_check`：每個受影響中庭降層後的南側高度與 `h_north_edge_m` 比較（`reaches_north_edge` 真／假＝中庭整體）；另列 `local_sun_pockets`（降到門檻以下的個別建築與其面寬）；若提案宣稱改善中庭冬陽但全部為假，平台在核准前顯示警告（不阻擋核准，由設計者決定是否仍要重算）。
- 禁止詞：「已核准」「批准」「正式接受」「最佳」「保證改善」。

## 核准與重算流程
1. 提案通過驗證 → 平台顯示：操作清單（人話）、受影響建築高亮、GFA 試算、未模擬項目。
2. Founder 按「核准重算」→ 記錄核准（設計對話紀錄；非 HumanDecision）→ 套用到正式草稿新 revision。
3. 背景重算 `RERUN` 指定分析（僅草稿；輸出到 `.urban_design_runtime/revisions/<proposal_id>/`）→ 完成後自動以草稿為主體重跑 J-CLIMATE（新一輪判讀卡），並顯示前後對照（中庭冬至日照、全體冬至、UTCI 非常強烈比例、GFA、受影響棟數）。
4. 任一步失敗：保留草稿前一 revision，不自動重試；OUTCOME_UNKNOWN 需對帳。
