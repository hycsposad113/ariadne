# S6 量體配置

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

用用途、路網、Syntax 與 context 提出有理由且可驗證的量體與公共空間。

## 觸發時機

S4 路網與 S5 結果版本固定，S3 策略授權充分。

## AI（LLM）責任

提出量體、空地、首層用途與相反選項；說清楚誰怎麼進來生活、為何這裡高那裡低，不計算正式結果。

## 確定性程式責任

幾何生成、路面 intersection、批准D2、逐層面積、垂直基準、陰影與拓樸均由引擎；本 J7 只有規格。

## 失敗處理

缺理由、卡引用或context即INCOMPLETE；幾何硬性檢查失敗 INVALID；不憑LLM文字通過。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/morphology/massing.py
- src/urban_design/morphology/contracts.py
- src/urban_design/morphology/metrics.py
- src/urban_design/generation/formal_pipeline.py
- src/urban_design/generation/road_access.py
- src/urban_design/constraint_sets.py
- TODO_SOURCE: S2/S3/S4/S5 連結 evidence bundle 與新的高度 context facade

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

- 先保留全部道路面及保留建築，再配置可建地塊。
- High 沿街比較工坊／公共設施／小店；High 節點至少比較廣場、相對地標、組合。
- 比較周邊式、合院、板樓、點式、連棟、基座與可逆改造，不預設學派勝者。
- 每棟高度、空地與入口理由連到 context、Syntax 實際/目標、rule id；Dakpark 高差未測則顯示假說。
- 確定性計算逐層 GFA/FSI/GSI/L、20 m 上限、路面碰撞、保留 hash、平面40 m與入口可達。
- 輸出設計意圖＋理由＋引用卡 id；缺其中一項或只是抽象口号即 INCOMPLETE。

## 品質檢查

- 保留物不動、城市道路不變、無建築壓任何路面；任何不過 INVALID。
- 20 m 以已接受 D2 的 height datum 驗證；portfolio 層高不能代替實測。
- 設計理由不是數值證據；沒有有效 deterministic result 不能正式接受。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S6",
  "title_zh": "量體配置",
  "purpose_zh": "用用途、路網、Syntax 與 context 提出有理由且可驗證的量體與公共空間。",
  "trigger_zh": "S4 路網與 S5 結果版本固定，S3 策略授權充分。",
  "inputs": [
    "src/urban_design/morphology/massing.py",
    "src/urban_design/morphology/contracts.py",
    "src/urban_design/morphology/metrics.py",
    "src/urban_design/generation/formal_pipeline.py",
    "src/urban_design/generation/road_access.py",
    "src/urban_design/constraint_sets.py",
    "TODO_SOURCE: S2/S3/S4/S5 連結 evidence bundle 與新的高度 context facade"
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
    "LAN-003",
    "LAN-004",
    "LAN-005",
    "LAN-006",
    "LAN-007",
    "LAN-008",
    "POL-005",
    "MOR-014",
    "MOR-015",
    "MOR-016",
    "PUB-007",
    "PUB-008",
    "CTX-006",
    "CTX-007",
    "MOB-001",
    "MOB-003",
    "MOB-011"
  ],
  "steps_zh": [
    "先保留全部道路面及保留建築，再配置可建地塊。",
    "High 沿街比較工坊／公共設施／小店；High 節點至少比較廣場、相對地標、組合。",
    "比較周邊式、合院、板樓、點式、連棟、基座與可逆改造，不預設學派勝者。",
    "每棟高度、空地與入口理由連到 context、Syntax 實際/目標、rule id；Dakpark 高差未測則顯示假說。",
    "確定性計算逐層 GFA/FSI/GSI/L、20 m 上限、路面碰撞、保留 hash、平面40 m與入口可達。",
    "輸出設計意圖＋理由＋引用卡 id；缺其中一項或只是抽象口号即 INCOMPLETE。"
  ],
  "llm_responsibility_zh": "提出量體、空地、首層用途與相反選項；說清楚誰怎麼進來生活、為何這裡高那裡低，不計算正式結果。",
  "deterministic_responsibility_zh": "幾何生成、路面 intersection、批准D2、逐層面積、垂直基準、陰影與拓樸均由引擎；本 J7 只有規格。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "每項决定具體引用卡 id/version，與 context/result refs 配對",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "buildings": "id/geometry_ref/height_ref/use/entry_refs/context_refs/road_refs",
    "open_spaces": "id/geometry_ref/access_status/program",
    "design_intent_zh": "每案與每關鍵配置要實現的生活與空間意圖，非空字串",
    "rationale_zh": "逐棟高度、留空與入口决策理由，包含代價和反例"
  },
  "quality_checks_zh": [
    "保留物不動、城市道路不變、無建築壓任何路面；任何不過 INVALID。",
    "20 m 以已接受 D2 的 height datum 驗證；portfolio 層高不能代替實測。",
    "設計理由不是數值證據；沒有有效 deterministic result 不能正式接受。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "缺理由、卡引用或context即INCOMPLETE；幾何硬性檢查失敗 INVALID；不憑LLM文字通過。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
  "requires_design_rationale": true
}
```

## J8 本機知識增補

- LAN-003
- LAN-004
- LAN-005
- LAN-006
- LAN-007
- LAN-008
- POL-005
- MOR-014
- MOR-015
- MOR-016
- PUB-007
- PUB-008
- CTX-006
- CTX-007

執行只讀本機 library／cards；候選 0.2.0 待 Founder 審核及鎖定。

- MOB-001（J8 覆蓋：分模式路網／量體入口及服務回應）

- MOB-003（J8 覆蓋：分模式路網／量體入口及服務回應）

- MOB-011（J8 覆蓋：分模式路網／量體入口及服務回應）
