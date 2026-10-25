# S2 現況診斷

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

把現況、政府規劃、港區生活、入口與不同尺度診斷合為版本化基準。

## 觸發時機

S1 輸入充分或 context snapshot 更新。

## AI（LLM）責任

整理關係、可能問題與替代解釋；不能把 High 等同人流實測。

## 確定性程式責任

度量面積、圖拓樸／入口、匹配合法 access/grade，保持 manifest readiness：目前 Syntax 不升格正式。

## 失敗處理

必要政府規劃或拓樸缺失即 INCOMPLETE；保留可描述的已知部分與缺口，不捏造診斷。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/site_analysis.py
- src/urban_design/syntax_context_api.py
- src/urban_design/api.py
- src/urban_design/workspace_contracts.py
- TODO_SOURCE: Dakpark 同垂直基準高程、門禁與實際人流觀測
- TODO_SOURCE: 已核實 M4H／omgevingsplan 與現況用途同分類資料

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
- CTX-001
- CTX-002
- CTX-003
- CTX-004
- CTX-005
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

- 讀 site-context、site-analysis、syntax/context 的結構定義，只使用離線凍結輸出，不連正式服務。
- 現況、政府規劃、portfolio 各自列 taxonomy 與時間；確認用途比例分母。
- 確定性計算面積、地塊與模式入口；按 radius 800/2000/10000 診斷 integration/choice。
- 列外部 High 入口、到中心路徑、保留建物、城市車道、Dakpark、水岸與產業物流。
- 將 10 m 高差與10/40% 尺度門檻作待核假說；輸出多方法解釋和限制。

## 品質檢查

- API 定義可讀：GET /api/v1/projects/{project_id}/site-context、/site-analysis、/syntax/context。
- 不同模式與半徑不共用排名分母。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S2",
  "title_zh": "現況診斷",
  "purpose_zh": "把現況、政府規劃、港區生活、入口與不同尺度診斷合為版本化基準。",
  "trigger_zh": "S1 輸入充分或 context snapshot 更新。",
  "inputs": [
    "src/urban_design/site_analysis.py",
    "src/urban_design/syntax_context_api.py",
    "src/urban_design/api.py",
    "src/urban_design/workspace_contracts.py",
    "TODO_SOURCE: Dakpark 同垂直基準高程、門禁與實際人流觀測",
    "TODO_SOURCE: 已核實 M4H／omgevingsplan 與現況用途同分類資料"
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
    "CTX-001",
    "CTX-002",
    "CTX-003",
    "CTX-004",
    "CTX-005",
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
    "CTX-006",
    "CTX-007"
  ],
  "steps_zh": [
    "讀 site-context、site-analysis、syntax/context 的結構定義，只使用離線凍結輸出，不連正式服務。",
    "現況、政府規劃、portfolio 各自列 taxonomy 與時間；確認用途比例分母。",
    "確定性計算面積、地塊與模式入口；按 radius 800/2000/10000 診斷 integration/choice。",
    "列外部 High 入口、到中心路徑、保留建物、城市車道、Dakpark、水岸與產業物流。",
    "將 10 m 高差與10/40% 尺度門檻作待核假說；輸出多方法解釋和限制。",
    "沿合法步行路網比較各側到站距離，確認斷點與不可達。",
    "把吸引點、路網組態與時段作人流假說，不以設施點數產生人數。",
    "對各方位用途與住宅／工業介面列反應策略、緩衝假設及資料缺口。"
  ],
  "llm_responsibility_zh": "整理關係、可能問題與替代解釋；不能把 High 等同人流實測。",
  "deterministic_responsibility_zh": "度量面積、圖拓樸／入口、匹配合法 access/grade，保持 manifest readiness：目前 Syntax 不升格正式。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "實際使用的卡 id 與版本；不是僅整個 domain 名稱",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "diagnosis": "土地使用三欄、scale、context_observation_refs",
    "entry_roads": "segment id、mode、radius、percentile、外部接點與權利",
    "baseline_syntax": "方法、樣本、分布、status、邊界限制",
    "transit_accessibility": "各側入口／最近站點／沿步行路網距離 m／不可達／直線對照／路網版本",
    "surrounding_functions": "BAG 用途與 OSM 吸引點分開、分類分母、日期及 UNKNOWN",
    "flow_hypotheses": "站點與吸引點路徑、Syntax／時段／門禁；未校準不得報人數",
    "directional_interfaces": "方位分段與北向定義、外側 buffer m、住宅／工業介面及衝突"
  },
  "quality_checks_zh": [
    "API 定義可讀：GET /api/v1/projects/{project_id}/site-context、/site-analysis、/syntax/context。",
    "不同模式與半徑不共用排名分母。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "必要政府規劃或拓樸缺失即 INCOMPLETE；保留可描述的已知部分與缺口，不捏造診斷。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
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
- CTX-006
- CTX-007

執行只讀本機 library／cards；候選 0.2.0 待 Founder 審核及鎖定。
