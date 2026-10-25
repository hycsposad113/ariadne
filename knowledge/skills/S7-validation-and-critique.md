# S7 驗證與評論

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

把硬性結果、目標差距與設計判斷分開，提供可質疑的評論。

## 觸發時機

每個新候選或修改版本送審前。

## AI（LLM）責任

按有效結果解釋與批評，提出衝突及反例，不認證法規、不計算、不接受自身輸出。

## 確定性程式責任

運行正式已註冊 validator，結果關聯project/scenario/input/tool；強制缺檢查不能由文字PASS替代。

## 失敗處理

缺 mandatory 證據 INCOMPLETE；硬性結果失败 INVALID；單一來源/未核假設不得升級硬性門槛。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/editing/validation.py
- src/urban_design/morphology/validation.py
- src/urban_design/generation/formal_pipeline.py
- src/urban_design/site_critic.py
- src/urban_design/models.py
- TODO_SOURCE: 新共廊／停車入口距离 validator 與 S6 evidence bundle，未實作

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
- SYN-012
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

- 核對方案、輸入、D1/D2 與 results 的版本/hash關係，不只查 id 存在。
- 列道路碰撞、保留、水岸退縮、FAR/GSI/高度、40 m平面可達、共廊與停車路徑；未批准ASSUMED只是候選檢查。
- 每目標逐項寫達成/部分/未達/未知及值、單位、基準。
- 檢查偏誤：是否只引用單派、是否忽略货運、弱勢或非西歐反例，提出相反方案。
- 必須輸出設計意圖＋理由＋引用卡 id，解釋人從哪裡進來、走到哪、哪裡停留和量體為何如此。
- 彙總 DRAFT（附驗證結果）/INCOMPLETE/INVALID；有效候選仍待Founder决定。

## 品質檢查

- 消防／服務正式合規仍需作業資料，40 m 平面檢查不能替代。
- 引用卡或 JSON 合法不等於證據有效；所有 mandatory check 必須有新鮮結果。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S7",
  "title_zh": "驗證與評論",
  "purpose_zh": "把硬性結果、目標差距與設計判斷分開，提供可質疑的評論。",
  "trigger_zh": "每個新候選或修改版本送審前。",
  "inputs": [
    "src/urban_design/editing/validation.py",
    "src/urban_design/morphology/validation.py",
    "src/urban_design/generation/formal_pipeline.py",
    "src/urban_design/site_critic.py",
    "src/urban_design/models.py",
    "TODO_SOURCE: 新共廊／停車入口距离 validator 與 S6 evidence bundle，未實作"
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
    "SYN-012",
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
    "核對方案、輸入、D1/D2 與 results 的版本/hash關係，不只查 id 存在。",
    "列道路碰撞、保留、水岸退縮、FAR/GSI/高度、40 m平面可達、共廊與停車路徑；未批准ASSUMED只是候選檢查。",
    "每目標逐項寫達成/部分/未達/未知及值、單位、基準。",
    "檢查偏誤：是否只引用單派、是否忽略货運、弱勢或非西歐反例，提出相反方案。",
    "必須輸出設計意圖＋理由＋引用卡 id，解釋人從哪裡進來、走到哪、哪裡停留和量體為何如此。",
    "彙總 DRAFT（附驗證結果）/INCOMPLETE/INVALID；有效候選仍待Founder决定。"
  ],
  "llm_responsibility_zh": "按有效結果解釋與批評，提出衝突及反例，不認證法規、不計算、不接受自身輸出。",
  "deterministic_responsibility_zh": "運行正式已註冊 validator，結果關聯project/scenario/input/tool；強制缺檢查不能由文字PASS替代。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "評論逐項卡id/version與evidence鏈接",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "checks": "id/status/value/unit/authority_ref/result_ref/limitations",
    "goal_results": "target_id/result_ref/value/unit/achievement",
    "design_intent_zh": "保留S6意圖並說明是否仍成立",
    "rationale_zh": "根據有效結果評論、代价、反例與無法證明內容"
  },
  "quality_checks_zh": [
    "消防／服務正式合規仍需作業資料，40 m 平面檢查不能替代。",
    "引用卡或 JSON 合法不等於證據有效；所有 mandatory check 必須有新鮮結果。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "缺 mandatory 證據 INCOMPLETE；硬性結果失败 INVALID；單一來源/未核假設不得升級硬性門槛。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
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
