# J-MORPH 形態生成判讀 v1.0.1

撰寫：Claude Opus 5.5（Commander），2026-10-18。依據 Founder 10-17「從基地分析到 morphology 的量體與道路生成，Ariadne 都要有自己的判讀」與 10-18「第 4 期 A 做量體策略操作＋J-MORPH」。

## 目的
針對一個紋理方案的**生成結果**（路網、街廓、中庭、量體高度分布），提出 Ariadne 自己的形態判斷：生成邏輯是否回應了基地與先例、街廓與中庭的尺度是否支撐預定的生活方式、哪些失敗項是結構性的、哪些可以靠量體策略修正。結果是設計者在「生成／比較」階段可以同意、質疑或補充的判讀，並可接著請 Ariadne 提出量體策略修正（R-PROPOSE v1.2 的 `SOLAR_ENVELOPE`／`COURTYARD_WING_DEPTH`）。

## 觸發
- 比較頁或生成頁選定一個紋理方案時，設計者按「請 Ariadne 判讀形態」。
- 方案 plan、檢核或字典版本的 sha 變了才重跑。

## 輸入組裝（確定性程式負責；模型只看到這些）
| 群組 | id 格式 | 內容 |
|---|---|---|
| 生成參數 | `morph.<fabric>.param.<name>` | `block_long_m`、`block_short_m`、`street_width_m`、`building_depth_m`、`target_gfa_m2`、`seam_width_m`、`orientation_deg`（plan.parameters） |
| 字典範圍與依據 | `morph.<fabric>.bound.<name>.minimum／.maximum`（數值）、`basis.<fabric>.<name>`（依據文字）、`ku:<KU-id>` | 形態字典的 minimum／maximum 與 `basis.status`、`note_zh`（例如港埠短邊 68.6 m 只有一個先例，`MEASURED_PRECEDENT_DERIVED`） |
| 形態指標 | `scheme.<fabric>.<fsi|gsi|osr|l|new_gfa_m2|building_count>` | plan.metrics |
| 街廓與中庭 | `morph.<fabric>.courtyard.<id>.<clear_width_m|area_m2|depth_along_sun_m|h_north_edge_m|south_edge_height_max_m|feasible_within_catalogue>` | 與 R-PROPOSE 相同的確定性日照幾何（冬至正午高度 14.66°） |
| 高度分布 | `morph.<fabric>.height.<p10|median|p90|share_at_cap>` | 新建建築高度分布、達 18–20 m 上限的比例 |
| 檢核失敗 | `morph.<fabric>.check.<failure_id>` | plan.validation.failure_ids 與中文說明（例：`SOUTH_QUAY_FACADE_CONTINUITY`） |
| 路網 | `syntax.<fabric>.<mode>.<metric>` | 新設計路段、主街、水岸的 NAIN／NACH 百分位（與 J-COMPARE 同來源） |
| 生成說明 | `morph.<fabric>.statement` | `artifacts/fab1/run-8/ai-explanations/<fabric>-design-statement-zh.md` 摘要（≤ 1,200 字） |
| 設計者立場 | `designer.stance.<key>` | seed（中庭定位、季節優先）與先前回應 |

## 必讀知識單元
- 街廓與類型：KU-MOR-001、KU-MOR-002、KU-MOR-003、KU-MOR-039、KU-MOR-040、KU-MOR-041、KU-MOR-079、KU-MOR-080
- 密度與形態：KU-MOR-028、KU-MOR-031、KU-MOR-033、KU-MOR-073、KU-MOR-097
- 本案紋理：KU-MOR-100（港埠線性紋理）、KU-MOR-101（圍合街廓延伸）、KU-MOR-081（Borneo-Sporenburg 街廓推估）
- 日照：KU-CLI-007、KU-CLI-026、KU-CLI-027

## 判斷框架（逐鏡頭作答，再收斂）
**L1 生成邏輯**：路網與街廓是否從基地結構（岸線、鐵道切線、既有路口）長出來；參數是否落在先例依據範圍內；單一先例推估的參數要明說其脆弱性。
**L2 街廓與中庭尺度**：中庭淨寬與南側高度的關係（引用 `h_north_edge_m` 與 `south_edge_height_max_m`）；中庭是否撐得起設計者定義的用途（住戶停留＋夏季遮蔭＋冬季日照）；尺度不足時是結構問題（街廓短邊）還是量體問題（高度分布）。
**L3 高度與密度分布**：密度是均勻攤平還是有層次；是否把高度放在對公共空間代價最小的位置（北側、臨主街）；GFA 與 85% 下限的餘裕。
**L4 檢核失敗與修補**：逐一判斷失敗項屬於路網／界面（需重新生成才能解）或量體（量體策略可修）；不得把結構性失敗說成小修可解。
**L5 資料缺口**：哪些形態判斷因缺資料不能下（例如地籍、實際用途、日照逐中庭細分）。

## 收斂規則
- `stance`：L2 或 L4 有結構性弱點且無量體解 → `CONCERN`；有量體解 → `SUPPORT_WITH_CONDITIONS`；只有在 L1–L4 皆無實質弱點時才可 `SUPPORT`。
- `revision_directions` 至少一項對應最大弱點；可用參數族：`height`、`courtyard_width`、`setback`、`intensity`、`block_subdivision`、`street_section`、`street_add_remove`、`open_space_allocation`、`analysis_needed`（v1.0.1：路網／界面失敗需要回到路網或開放空間配置時用後兩者，並明說這不是量體策略能修的）。若方向需要量體策略，`action` 要寫成可由 R-PROPOSE 執行的語言（例：「對 courtyard-0、courtyard-1 南側採日照包絡限高，樓地板移到北側與臨主街棟」）。
- 不得建議超出字典範圍的參數修改，除非明說「超出先例依據，屬探索」並列為設計者問題。
- `questions_for_designer`：1–2 題，問下一層取捨（例如可接受北側街道冬季日照下降多少、GFA 餘裕要用多少換中庭日照）；不重問設計者已表達的立場。

## 驗證（確定性）
- 共同原則同 README（數字白名單、refs 存在、knowledge_refs ⊆ 清單、禁止詞）。
- `stage = "morphology"`。
- L4 對每個檢核失敗 id 至少在 observations 或 limitations 提到一次（id 或中文名稱）。
- 禁止詞另加：「已通過檢核」「合規」「最佳形態」。

## 評測案例
1. 港埠 run-8：預期 headline 指向「街廓短邊固定＋均勻 18 m 高度使中庭冬季無日照」，L4 區分南碼頭界面失敗（路網／界面）與中庭日照（量體可修）；`revision_directions` 含日照包絡。
2. 移除日照幾何輸入：L2 改為 `analysis_needed`，不得斷言中庭冬陽可行或不可行。
