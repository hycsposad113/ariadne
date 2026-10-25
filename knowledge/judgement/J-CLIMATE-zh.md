# J-CLIMATE 氣候效能判讀 v1.2.0

## 目的
把 E1–E5 的確定性結果翻成**設計判斷**：這個方案在鹿特丹海洋性溫帶氣候下，戶外空間一年四季好不好用、建築是否耗能、哪些地方該改，以及哪些結論其實還不能下。

## 觸發
- 比較頁「氣候與環境」區塊打開某方案或四案對照時（設計者按「請 Ariadne 判讀」）。
- 任何 E1／UTCI／E3／E4／E5 結果更新後（結果 sha 變了才重跑，避免重複呼叫）。

## 輸入組裝（確定性程式負責；模型只看到這些）
每個值都帶 `metric_id`、值、單位、來源檔 sha256。缺檔的項目以 `DATA_GAP:<metric_id>` 列出。

| 群組 | metric_id 格式 | 來源 |
|---|---|---|
| E1 日照 | `e1.<scheme>.<category>.<season>.mean_h`、`.ge2h_pct`、`.area_m2` | `artifacts/w8/e1-fabric/comparison_table.csv`（category＝全體、公園綠軸、水岸、街道、街廓中庭、街廓內其他空地、設備院；season＝spring／summer／winter） |
| UTCI | `utci.<scheme>.<category>.mean_c`、`.very_strong_pct`、`.strong_plus_pct`、`.mean_mrt_c`、`.mean_svf` | `artifacts/w8/utci/utci_stress_hours_comparison.json`（最熱日 2017-08-19，10–17 時） |
| E2 輻射 | `e2.harbour_vs_mixed.hb_0h_kwh_m2.{base,variant}`、`.pct`；`.lb_0h…` | `artifacts/w8/e2-formal/harbour-vs-mixed-result.json` |
| E3 耗能 | `e3.<scheme>.eui_kwh_m2`、`.heating_kwh`、`.cooling_kwh`、`.peak_heating_kw`、`.peak_cooling_kw` | `artifacts/w8/e3e4-final/e3e4_results_zh.csv` |
| E4 蓄熱 | `e4.harbour.<mass|light>.overheat_h`、`.winter_heating_kwh`、`.peak_cooling_kw` | 同上 |
| E5 風 | `e5.harbour.<SW|W|S|NW>.freq_pct`、`.mean_ratio`、`.max_ratio`、`.gt12_area_m2` | `artifacts/w8/e5-cfd/` summary |
| 方法限制 | `limit.<e1|utci|e2|e3|e5>` 原文 | 各 README／報告限制段 |
| 方案脈絡 | `scheme.<id>.label`、`.selected`、`.fsi`、`.gsi`、`.height_max_m` | fabric plans API |
| 設計者立場 | `designer.stance.<key>`（例：`courtyard_role`、`season_priority`）原文 | 設計對話紀錄（Founder 已表達的立場；判讀必須回應，不得推翻成相反前提） |

## 必讀知識單元（組裝時附摘要；推理只准引用這些）
- 日照與遮陰：KU-CLI-007、KU-CLI-026、KU-CLI-027、KU-CLI-054、KU-CLI-055、KU-CLI-056、KU-CLI-065
- 街谷幾何：KU-CLI-001、KU-CLI-012、KU-CLI-015、KU-CLI-046
- 熱舒適：KU-CLI-008、KU-CLI-040、KU-CLI-041、KU-CLI-050、KU-CLI-057、KU-CLI-059；SVF 不是舒適度：KU-CLI-018
- 風：KU-CLI-006、KU-CLI-019、KU-CLI-023、KU-CLI-025、KU-CLI-052、KU-CLI-053
- 高密度氣候設計：KU-CLI-042、KU-CLI-043、KU-CLI-044、KU-CLI-047、KU-CLI-066
- 遮蔭植栽：KU-CLI-029、KU-CLI-061
- 形態與能耗：KU-MOR-036、KU-MOR-037、KU-MOR-038
可選：KU-CLI-068、KU-CLI-072（熱風險熱點與避暑路徑）。

## 判斷框架（逐鏡頭作答，再收斂成一個立場）

**L1 季節取捨（夏遮陰 vs 冬日照）**
- 問：夏季降低輻射與熱壓力的收益，是否以冬季可停留空間的日照為代價？代價落在哪一類空間？
- 規則：先讀 `designer.stance.*`。若設計者表示冬季陽光與夏季熱舒適同等重要（目前 Founder 立場），則**不得用一季的優勢抵銷另一季的失效**：停留型空間（公園、廣場、水岸、中庭）必須同時有「冬季部分區域有日照的停留帶」與「夏季遮蔭」。無設計者立場時，鹿特丹冬季日照稀缺、夏季極端熱日少 → 停留空間冬季 ≥2h 比例下降給較高權重。通過型街道的冬季日照不足權重較低，但要指出主要步行路線是否全落在陰影中（KU-CLI-055、KU-CLI-065）。

**L2 空間分類**
- 問：哪一類空間在哪個季節失效？例如中庭冬季接近 0 h。
- 規則：失效的空間要給設計建議，不能只報數字。若設計者已把該空間定位為停留空間（例如 Founder：中庭＝住戶停留空間兼夏季遮蔭庭），不得建議「改定位成不停留」來迴避問題；改提能同時滿足兩季的做法（例如降低中庭南側量體讓北側邊緣形成冬季日照停留帶，夏季以落葉樹與棚架遮蔭）。

**L3 夏季熱壓力（UTCI）**
- 問：方案之間的差異是否大到有設計意義？
- 規則：平均 UTCI 差距小於約 0.5 °C 時，不得據以排序，改看「非常強烈熱壓力時數比」與分類分布；說明 MRT 與 SVF 是差異的主因（KU-CLI-050）；指出風速採均勻對數律，建築風場未耦合，因此通風收益未被計入。

**L4 建築耗能（E3／E4）**
- 問：耗能差異主要來自形態（緊湊度、體形係數）還是量體數量？重質構造的價值多大？
- 規則：EUI 只用於相對比較（理想負荷、風機電力缺值、非認證）；E4 的差異要換算成相對比例的定性描述（例如「約 5% 的尖峰冷負荷降幅」只能在輸入有此比例時引用），否則只寫方向。

**L5 風（E5）**
- 問：靜風區與熱壓力區是否重疊？有無強風加速角落？
- 規則：E5 為粗網格篩選、背風區換算不準 → 只能說「趨勢」；不得給風舒適或風安全結論；若有靜風＋高 UTCI 重疊區，列為 `analysis_needed`（需細網格）。

**L6 結論可信度**
- 問：哪些判斷站得住、哪些是暫時的？
- 規則：把每條主要判斷標成「穩健」（多個模擬一致）或「暫定」（單一粗略模擬、方法限制大）；信心等級依此決定。

## 收斂規則
- `stance`：若 L1 對停留空間的冬季代價明顯、且其他鏡頭沒有足以抵銷的收益 → `CONCERN` 或 `SUPPORT_WITH_CONDITIONS`；只有在 L1–L4 沒有實質弱點時才可 `SUPPORT`。
- `revision_directions` 至少一項對應 L1 或 L2 的最大弱點；可用參數族：`height`、`setback`、`courtyard_width`、`orientation`、`open_space_allocation`、`planting_shade`、`analysis_needed`。
- `questions_for_designer`：設計者尚未表達季節優先順序時，至少一題問「冬季停留 vs 夏季遮蔭，你更重視哪一個？」；已表達時不得重問，改問下一層的取捨（例如可接受的 GFA 減少幅度、中庭最小寬度）。

## 修正後再判讀（v1.2.0，2026-10-18，Claude 撰寫）
主體為草稿（`harbour_grain@draft-rN`）且輸入含 `revision_context`（由程式寫入：提案摘要、操作清單人話、設計者回應原文、重算前後的指標值、乾跑 `solar_access_check`）時：
- **第一個觀察必須回答「上一案有沒有達到目的」**：引用 `revision_context` 裡的重算前後數值（只引用，不推算新數字），說明改善、無明顯變化或變差。
- **說明原因方向**：若 `solar_access_check` 顯示降層後南側高度仍高於 `h_north_edge_m`，要明說「冬至正午太陽高度下，這個幅度的降層不足以讓陽光進入中庭」，不要把無變化歸因於模擬誤差。
- **下一步要換策略而不是重複**：前一案無效時，`revision_directions` 不得只重複同一操作的小幅版本；應提出幾何上可能有效的方向（例如較寬中庭的南側低層段），或把冬陽目標移到其他公共空間並請設計者取捨。
- 承接設計者的回應：設計者對上一案的質疑或補充必須在本輪被回應（同意採納、或說明為何不採納）。

## 驗證（確定性）
- 數字白名單：輸入中出現過的值（含其顯示精度的四捨五入）。
- `refs.kind=metric` 的 id 必須存在於輸入。
- `knowledge_refs` ⊆ 必讀＋可選清單。
- 禁止詞：「認證」「合格」「符合法規」「實測」「風安全」「Lawson 判定」「最佳方案」「冠軍」「已核准」「批准」「正式接受」。
- E5 相關文字不得出現「舒適」「安全」作結論（只可出現在限制段）。

## 評測案例（eval/J-CLIMATE-*.json，施工時建立）
1. 港埠單案（現有資料＋Founder 立場：中庭為停留空間、兩季同等重要）：預期 stance ∈ {CONCERN, SUPPORT_WITH_CONDITIONS}，不得建議把中庭改為不停留；修正方向含 `courtyard_width` 或 `height`／`setback`（中庭冬季 0.11 h、街道 1.79 h）；指出 UTCI 平均差距小、改看非常強烈時數比。
2. 四案對照：預期以條件式表達（重視冬季公共空間 → 地景或圍合；重視夏季熱壓力與輻射 → 港埠），不宣告總冠軍；EUI 只作相對比較。
3. 缺 E5 檔：預期 `DATA_GAP:e5.*` 進 limitations，判斷不引用風。
