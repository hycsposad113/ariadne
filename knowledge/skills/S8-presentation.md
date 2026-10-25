# S8 方案說明

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

讓設計者以可理解理由比較方案並保留最终决定權。

## 觸發時機

S7審查結果固定後、提交Founder審查前。

## AI（LLM）責任

用白話整理來源、有效結果與選擇代价；不掩盖失败或把假說寫成量測。

## 確定性程式責任

校驗每个數字鏈接有效結果、同版本同分母，出圖標注CRS/尺度/方法/status/hash；驗證輸出結構字段。

## 失敗處理

無理由／引用或結果鏈接 INCOMPLETE；缺值顯示未知不补零，正式接受交Founder。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/scenario_comparison.py
- src/urban_design/scenario_comparison_router.py
- src/urban_design/figure_export.py
- src/urban_design/models.py
- TODO_SOURCE: S6/S7 版本化設計叙事與對比數據 bundle；本任務不改UI

## 要讀的規則卡

- SYN-012
- CTX-001
- CTX-002
- CTX-003
- CTX-004
- CTX-005
- PUB-001
- PUB-002
- PUB-003
- PUB-004
- PUB-005
- PUB-006
- POL-001
- POR-001
- POR-002
- POR-003
- POR-004
- POR-005
- POR-006
- POR-007
- POR-008
- POR-009
- POR-010
- POR-011
- POR-012
- POR-013
- POR-014
- POR-015
- POR-016
- POR-017
- POR-018

## 步驟

- 保留每案輸入、狀態與版本；無效/不全方案也如實呈現，不能隱藏。
- 按外部入口→生活走廊→中心→住宅/工坊/服务說明真實可達與未知。
- 解釋為何這裡高、那裡低、哪裡留廣場、Dakpark與水岸如何回應；附相反選擇及代价。
- 將目標vs實際、量體/開放空間/一樓用途差異與來源並列，不自行加權選赢家。
- 必須輸出設計意圖＋理由＋引用卡id；引用未核、參數假設、資料缺口清楚顯示。
- 輸出審查包，等待Founder决定；不創建HumanDecision、不部署或發布。

## 品質檢查

- 任何引用或結果過期顯示STALE；不以圖像漂亮宣称品質。
- 每个比較值使用一致定義或顯式不可比。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S8",
  "title_zh": "方案說明",
  "purpose_zh": "讓設計者以可理解理由比較方案並保留最终决定權。",
  "trigger_zh": "S7審查結果固定後、提交Founder審查前。",
  "inputs": [
    "src/urban_design/scenario_comparison.py",
    "src/urban_design/scenario_comparison_router.py",
    "src/urban_design/figure_export.py",
    "src/urban_design/models.py",
    "TODO_SOURCE: S6/S7 版本化設計叙事與對比數據 bundle；本任務不改UI"
  ],
  "card_ids": [
    "SYN-012",
    "CTX-001",
    "CTX-002",
    "CTX-003",
    "CTX-004",
    "CTX-005",
    "PUB-001",
    "PUB-002",
    "PUB-003",
    "PUB-004",
    "PUB-005",
    "PUB-006",
    "POL-001",
    "POR-001",
    "POR-002",
    "POR-003",
    "POR-004",
    "POR-005",
    "POR-006",
    "POR-007",
    "POR-008",
    "POR-009",
    "POR-010",
    "POR-011",
    "POR-012",
    "POR-013",
    "POR-014",
    "POR-015",
    "POR-016",
    "POR-017",
    "POR-018",
    "MOB-012",
    "MOB-013",
    "MOB-014",
    "MOB-015",
    "LAN-003",
    "LAN-004",
    "LAN-005",
    "LAN-006",
    "LAN-007",
    "LAN-008",
    "LAN-009",
    "LAN-010",
    "POL-002",
    "POL-003",
    "POL-004",
    "POL-005",
    "SYN-013",
    "SYN-014",
    "MOR-014",
    "MOR-015",
    "MOR-016",
    "PUB-007",
    "PUB-008",
    "CTX-006",
    "CTX-007"
  ],
  "steps_zh": [
    "保留每案輸入、狀態與版本；無效/不全方案也如實呈現，不能隱藏。",
    "按外部入口→生活走廊→中心→住宅/工坊/服务說明真實可達與未知。",
    "解釋為何這裡高、那裡低、哪裡留廣場、Dakpark與水岸如何回應；附相反選擇及代价。",
    "將目標vs實際、量體/開放空間/一樓用途差異與來源並列，不自行加權選赢家。",
    "必須輸出設計意圖＋理由＋引用卡id；引用未核、參數假設、資料缺口清楚顯示。",
    "輸出審查包，等待Founder决定；不創建HumanDecision、不部署或發布。"
  ],
  "llm_responsibility_zh": "用白話整理來源、有效結果與選擇代价；不掩盖失败或把假說寫成量測。",
  "deterministic_responsibility_zh": "校驗每个數字鏈接有效結果、同版本同分母，出圖標注CRS/尺度/方法/status/hash；驗證輸出結構字段。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "每項理由的卡id/version與result_refs",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "scenario_summaries": "每案來源/參數/輸入/結果/狀態/生活路徑與限制",
    "comparison": "差異表和反例，無總赢家",
    "design_intent_zh": "每方案的空間與生活目標，非空",
    "rationale_zh": "高度/空地/入口/context/策略理由與代价，非空",
    "founder_questions": "未確認假設、政策與衝突，不含密語"
  },
  "quality_checks_zh": [
    "任何引用或結果過期顯示STALE；不以圖像漂亮宣称品質。",
    "每个比較值使用一致定義或顯式不可比。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "無理由／引用或結果鏈接 INCOMPLETE；缺值顯示未知不补零，正式接受交Founder。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
  "requires_design_rationale": true
}
```

## J8 本機知識增補

- MOB-012
- MOB-013
- MOB-014
- MOB-015
- LAN-003
- LAN-004
- LAN-005
- LAN-006
- LAN-007
- LAN-008
- LAN-009
- LAN-010
- POL-002
- POL-003
- POL-004
- POL-005
- SYN-013
- SYN-014
- MOR-014
- MOR-015
- MOR-016
- PUB-007
- PUB-008
- CTX-006
- CTX-007

執行只讀本機 library／cards；候選 0.2.0 待 Founder 審核及鎖定。
