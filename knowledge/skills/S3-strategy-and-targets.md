# S3 策略與目標

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

讓尺度、用途與生活情境引出多個可爭辯的策略及路段目標。

## 觸發時機

S2 基準具備必要來源與 Founder 確認策略前。

## AI（LLM）責任

提出策略、交通組合與目標及理由，週配額由未來 harness 管制；本任務不呼叫模型。

## 確定性程式責任

驗證 ids、模式、半徑、百分位邊界、基準 hash、D1/D2 和權限；不根據文字判定數值已達成。

## 失敗處理

目標／來源／批准不全即草案；禁止模型選總冠軍或重新定義 D2。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/generation/type_registry.py
- src/urban_design/constraint_sets.py
- src/urban_design/api.py
- TODO_SOURCE: S2 版本化 diagnosis artifact（本任務不實作串接）
- TODO_SOURCE: 已接受 D1/D2 與策略決策對應的離線 evidence bundle

## 要讀的規則卡

- SYN-001
- SYN-002
- SYN-003
- SYN-004
- SYN-005
- SYN-006
- SYN-007
- SYN-008
- SYN-009
- SYN-010
- SYN-011
- MOB-001
- MOB-002
- MOB-003
- MOB-004
- MOB-005
- MOB-006
- MOB-007
- MOB-008
- MOB-009
- MOB-010
- MOB-011
- MOR-001
- MOR-002
- MOR-003
- MOR-004
- MOR-005
- MOR-006
- MOR-007
- MOR-008
- MOR-009
- MOR-010
- MOR-011
- MOR-012
- MOR-013
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
- LAN-001
- LAN-002
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

- 讀適用卡，缺條件則回查 S2，不把 browsing 結果當全部適用。
- 比較向心、軸線、網格、綠廊；每個提出入口到中心、安靜區、服務物流的意圖。
- 依尺度與土地使用提出模式組合；既有城市車道與保留建築維持。
- 每路段填 role×mode×radius×High/Medium/Low，引用固定基準樣本與 SYN-011 假設。
- 列試算參數與代價供 Founder 判斷，保持 PROPOSED；不由模型啟動約束。

## 品質檢查

- ASSUMED 百分位、面積與辦公比例不可自動啟用。
- 服務專用道路不得成為一般車行捷徑。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S3",
  "title_zh": "策略與目標",
  "purpose_zh": "讓尺度、用途與生活情境引出多個可爭辯的策略及路段目標。",
  "trigger_zh": "S2 基準具備必要來源與 Founder 確認策略前。",
  "inputs": [
    "src/urban_design/generation/type_registry.py",
    "src/urban_design/constraint_sets.py",
    "src/urban_design/api.py",
    "TODO_SOURCE: S2 版本化 diagnosis artifact（本任務不實作串接）",
    "TODO_SOURCE: 已接受 D1/D2 與策略決策對應的離線 evidence bundle"
  ],
  "card_ids": [
    "SYN-001",
    "SYN-002",
    "SYN-003",
    "SYN-004",
    "SYN-005",
    "SYN-006",
    "SYN-007",
    "SYN-008",
    "SYN-009",
    "SYN-010",
    "SYN-011",
    "MOB-001",
    "MOB-002",
    "MOB-003",
    "MOB-004",
    "MOB-005",
    "MOB-006",
    "MOB-007",
    "MOB-008",
    "MOB-009",
    "MOB-010",
    "MOB-011",
    "MOR-001",
    "MOR-002",
    "MOR-003",
    "MOR-004",
    "MOR-005",
    "MOR-006",
    "MOR-007",
    "MOR-008",
    "MOR-009",
    "MOR-010",
    "MOR-011",
    "MOR-012",
    "MOR-013",
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
    "LAN-001",
    "LAN-002",
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
    "讀適用卡，缺條件則回查 S2，不把 browsing 結果當全部適用。",
    "比較向心、軸線、網格、綠廊；每個提出入口到中心、安靜區、服務物流的意圖。",
    "依尺度與土地使用提出模式組合；既有城市車道與保留建築維持。",
    "每路段填 role×mode×radius×High/Medium/Low，引用固定基準樣本與 SYN-011 假設。",
    "列試算參數與代價供 Founder 判斷，保持 PROPOSED；不由模型啟動約束。"
  ],
  "llm_responsibility_zh": "提出策略、交通組合與目標及理由，週配額由未來 harness 管制；本任務不呼叫模型。",
  "deterministic_responsibility_zh": "驗證 ids、模式、半徑、百分位邊界、基準 hash、D1/D2 和權限；不根據文字判定數值已達成。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "實際使用的卡 id 與版本；不是僅整個 domain 名稱",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "strategies": "至少兩種策略、入口／中心／物流安排與來源",
    "targets": "segment_id/role/mode/radius_m/level/reference_hash",
    "design_intent_zh": "策略要讓誰怎麼生活",
    "rationale_zh": "依 context 與卡片解釋選擇與代價"
  },
  "quality_checks_zh": [
    "ASSUMED 百分位、面積與辦公比例不可自動啟用。",
    "服務專用道路不得成為一般車行捷徑。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "目標／來源／批准不全即草案；禁止模型選總冠軍或重新定義 D2。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
  "requires_design_rationale": false
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
