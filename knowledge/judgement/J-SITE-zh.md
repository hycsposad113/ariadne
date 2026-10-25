# J-SITE 基地判讀 v1.0.0

## 目的
讀完基地資料後，提出 Ariadne 自己的**基地判讀**：這塊地的結構性潛力與限制是什麼、設計應該從哪裡切入、哪些既有元素值得保留、哪些問題資料還答不了。結果會成為條件與生成階段的起點，設計者可以同意、質疑或補充。

## 觸發
- 基地頁設計者按「請 Ariadne 判讀基地」。
- 基地分析 bundle、空間語法或脈絡快照的 sha 變了才重跑。

## 輸入組裝（確定性）
| 群組 | id 格式 | 來源 |
|---|---|---|
| 證據卡 | `evidence_card:<card_id>`（含狀態、值、單位、限制） | `get_persisted_site_analysis`（只收 VERIFIED_SOURCE_RESULT_ALIGNMENT 或 SOURCE_ALIGNED_COVERAGE_LIMITED） |
| 空間語法 | `syntax.context.<ped|bike|car>.<nain|nach>.<radius>.site_mean_pctl`、`.top20_segments_in_site` | syntax context bundle（800 m／2 km／10 km） |
| 基地幾何 | `site.design_area_m2`、`site.land_area_m2`、`site.waterfront_length_m`、`site.retained_buildings`、`site.retained_roads` | 工作區／D1 |
| 脈絡 | `context.<osm|3dbag>.<summary_key>` | surrounding context summary |
| 問題定義 | `problem.<id>.statement` | problem definitions |
| 設計者已表達 | `designer.note.<n>`（過去在基地階段的補充與質疑） | 設計對話紀錄 |

## 必讀知識單元
- 城鎮平面與既有結構：KU-MOR-009、KU-MOR-011、KU-MOR-013、KU-MOR-015
- 空間語法讀法：KU-SYN-009、KU-SYN-010、KU-SYN-012、KU-SYN-014、KU-SYN-057、KU-SYN-061、KU-SYN-068、KU-SYN-069
- 港口再生先例：KU-MOR-083、KU-MOR-084、KU-MOR-088、KU-MOR-090、KU-MOR-091
- 水岸與公共空間：KU-PUB-009、KU-PUB-012、KU-PUB-013
- 氣候前提：KU-CLI-026、KU-CLI-043

## 判斷框架
**L1 結構與尺度**：基地在城市結構中的位置（半島、末端、與 Spangen／Keileweg 的關係）；既有街廓尺度與路網骨架哪些可以延續。
**L2 移動潛力**：三種半徑的語法結果代表什麼；基地內哪些既有道路具有接到城市網絡的潛力，哪裡是盡端；語法是潛力不是人流。
**L3 既有元素**：保留建築、保留道路、港埠遺構的價值（空間錨點、記憶、限制）；哪些保留是設計資產，哪些是代價。
**L4 水與邊緣**：水岸可及、邊緣的公共性、半島末端的結構性限制。
**L5 資料缺口**：哪些關鍵判斷因資料不足無法下（權屬、實際人流、高程、法定分區），以及它們會怎樣改變判斷。

## 收斂規則
- headline 是一句設計切入點判斷（例如「我認為這塊地的關鍵不是密度，而是能否把 Keileweg 的城市連結延伸到半島末端；做不到，水岸就會是盡端」）。
- `revision_directions` 在基地階段代表「給條件與生成的建議」：可用 `retention`、`street_add_remove`、`open_space_allocation`、`intensity`、`land_use`、`analysis_needed`。
- `questions_for_designer` 至少一題問在地知識或設計立場（例如「你怎麼看港埠遺構的保留價值？」）。

## 驗證
- 數字白名單、`evidence_card` id 必須在輸入中、KU 白名單。
- 禁止詞：「人流量」「實測人流」「已核准」「批准」「正式接受」「合法」「權屬確認」。
- 證據卡狀態為 COVERAGE_LIMITED 的觀察，句中必須帶限定語（「在資料涵蓋範圍內」或同義）。

## 評測案例
1. 現有基地資料：預期 headline 指向連結／盡端或水岸結構，而非單純密度；L5 至少列 2 項資料缺口；不出現人流斷言。
2. 移除語法輸入：預期 L2 改為 `analysis_needed`，stance 不得高於 `SUPPORT_WITH_CONDITIONS`。
