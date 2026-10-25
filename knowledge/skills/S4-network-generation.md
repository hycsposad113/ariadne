# S4 路網生成

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

先配置保留／新建多模式路網，再切街廓，為生活入口與服务保留空間。

## 觸發時機

S3 策略方向與條件已由正式 harness 授權，開始離線候選。

## AI（LLM）責任

選擇路網語法與生活用途、提出不同方案與理由；不輸出未驗證座標或路面量測。

## 確定性程式責任

geometry/graph 生成與驗證由後續引擎；使用已批准路面幾何，不猜寬度；核查斷連、碰撞、模式接點與40 m平面可達。

## 失敗處理

不連通、壓保留物或改城市道路標 INVALID；外部工具未知結果先調和，不盲重試。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/generation/skeleton.py
- src/urban_design/generation/road_access.py
- src/urban_design/morphology/streets.py
- src/urban_design/morphology/parcels.py
- TODO_SOURCE: S3 targets 與新多模式 corridor 契約／生成 facade，尚未實作

## 要讀的規則卡

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
- PUB-001
- PUB-002
- PUB-003
- PUB-004
- PUB-005
- PUB-006
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

- 凍結保留城市道路、保留建築與合法入口。
- 按候選策略生成連續步行／騎行走廊與服務網，先看從外部進來到中心的路。
- 逐路標 retain/transform/remove/new 與 mode、role、access、grade、corridor_id、來源；任何保留改動交 Founder。
- 檢查共廊與停車入口，先切街廓再安排可建區，不事後任意補接駁道。
- 送 S5 多變體重算並列目標差距；不宣稱最優即採納。

## 品質檢查

- 不改生成器；本檔是未來執行規格。
- 路寬細節 deferred；缺路面幾何不能做碰撞 PASS。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S4",
  "title_zh": "路網生成",
  "purpose_zh": "先配置保留／新建多模式路網，再切街廓，為生活入口與服务保留空間。",
  "trigger_zh": "S3 策略方向與條件已由正式 harness 授權，開始離線候選。",
  "inputs": [
    "src/urban_design/generation/skeleton.py",
    "src/urban_design/generation/road_access.py",
    "src/urban_design/morphology/streets.py",
    "src/urban_design/morphology/parcels.py",
    "TODO_SOURCE: S3 targets 與新多模式 corridor 契約／生成 facade，尚未實作"
  ],
  "card_ids": [
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
    "PUB-001",
    "PUB-002",
    "PUB-003",
    "PUB-004",
    "PUB-005",
    "PUB-006",
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
    "MOB-015"
  ],
  "steps_zh": [
    "凍結保留城市道路、保留建築與合法入口。",
    "按候選策略生成連續步行／騎行走廊與服務網，先看從外部進來到中心的路。",
    "逐路標 retain/transform/remove/new 與 mode、role、access、grade、corridor_id、來源；任何保留改動交 Founder。",
    "檢查共廊與停車入口，先切街廓再安排可建區，不事後任意補接駁道。",
    "送 S5 多變體重算並列目標差距；不宣稱最優即採納。"
  ],
  "llm_responsibility_zh": "選擇路網語法與生活用途、提出不同方案與理由；不輸出未驗證座標或路面量測。",
  "deterministic_responsibility_zh": "geometry/graph 生成與驗證由後續引擎；使用已批准路面幾何，不猜寬度；核查斷連、碰撞、模式接點與40 m平面可達。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "實際使用的卡 id 與版本；不是僅整個 domain 名稱",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "roads": "geometry_ref/modes/access/grade/role/corridor_id/disposition/source_ref",
    "blocks": "先路後地塊 geometry_ref 與面積",
    "variant_refs": "路網 hash、參數、目標與結果引用"
  },
  "quality_checks_zh": [
    "不改生成器；本檔是未來執行規格。",
    "路寬細節 deferred；缺路面幾何不能做碰撞 PASS。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "不連通、壓保留物或改城市道路標 INVALID；外部工具未知結果先調和，不盲重試。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
  "requires_design_rationale": false
}
```

## J8 本機知識增補

- MOB-015

執行只讀本機 library／cards；候選 0.2.0 待 Founder 審核及鎖定。
