# S1 範圍與資料

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

建立資料抓取範圍與已確認 StudyArea 的分別，保留可追溯輸入。

## 觸發時機

首次範圍或來源／版本變更；草繪不等於採納基地。

## AI（LLM）責任

提出資料需求、缺口與引用；不確認範圍，不創造資料。

## 確定性程式責任

解析已接受狀態、檢查 Polygon/MultiPolygon 有效性、正面積、投影 CRS／canonical units、sha256；下載只能由日後已批准 facade 執行。

## 失敗處理

範圍／CRS／資料不足標 INCOMPLETE 並列缺項；post-dispatch 失聯為 OUTCOME_UNKNOWN，先調和再重試。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/study_area_workflow.py
- src/urban_design/models.py
- src/urban_design/workspace_sources.py
- src/urban_design/m2a03_sources.py
- TODO_SOURCE: 線上粗範圍地圖與 >=10 km 凍結資料 package；尚未由 J7 整合
- TODO_SOURCE: 現行政府土地使用規劃原文、精確版本與授權

## 要讀的規則卡

- LAN-002
- POL-001

## 步驟

- 解析草範圍與已接受 StudyArea artifact，核對 CRS／單位／hash。
- 列出所需建物、道路模式、地形、現況用途、政府規劃；既有資料只讀，不自行下載。
- 檢查來源、query、retrieval UTC、license、版本、覆蓋；列 >=10 km 邊界穩定性需要的資料缺口。
- 粗範圍精修與接受均交 Founder；保存草案，不更換正式指標。

## 品質檢查

- StudyArea 與正式 DesignBoundary 分開，法律主張需要其獨立批准。
- 沒有來源日期與 hash 的資料不能作計算證據。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S1",
  "title_zh": "範圍與資料",
  "purpose_zh": "建立資料抓取範圍與已確認 StudyArea 的分別，保留可追溯輸入。",
  "trigger_zh": "首次範圍或來源／版本變更；草繪不等於採納基地。",
  "inputs": [
    "src/urban_design/study_area_workflow.py",
    "src/urban_design/models.py",
    "src/urban_design/workspace_sources.py",
    "src/urban_design/m2a03_sources.py",
    "TODO_SOURCE: 線上粗範圍地圖與 >=10 km 凍結資料 package；尚未由 J7 整合",
    "TODO_SOURCE: 現行政府土地使用規劃原文、精確版本與授權"
  ],
  "card_ids": [
    "LAN-002",
    "POL-001",
    "LAN-010",
    "POL-002",
    "POL-003",
    "POL-004"
  ],
  "steps_zh": [
    "解析草範圍與已接受 StudyArea artifact，核對 CRS／單位／hash。",
    "列出所需建物、道路模式、地形、現況用途、政府規劃；既有資料只讀，不自行下載。",
    "檢查來源、query、retrieval UTC、license、版本、覆蓋；列 >=10 km 邊界穩定性需要的資料缺口。",
    "粗範圍精修與接受均交 Founder；保存草案，不更換正式指標。"
  ],
  "llm_responsibility_zh": "提出資料需求、缺口與引用；不確認範圍，不創造資料。",
  "deterministic_responsibility_zh": "解析已接受狀態、檢查 Polygon/MultiPolygon 有效性、正面積、投影 CRS／canonical units、sha256；下載只能由日後已批准 facade 執行。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "實際使用的卡 id 與版本；不是僅整個 domain 名稱",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "scope": "draft_fetch_envelope 與 confirmed_study_area_ref 分欄",
    "source_inventory": "各 snapshot 的 identity/query/time/license/hash/coverage/status",
    "planned_land_use": "TODO_SOURCE 或可核實文件 id，不填政策條文"
  },
  "quality_checks_zh": [
    "StudyArea 與正式 DesignBoundary 分開，法律主張需要其獨立批准。",
    "沒有來源日期與 hash 的資料不能作計算證據。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "範圍／CRS／資料不足標 INCOMPLETE 並列缺項；post-dispatch 失聯為 OUTCOME_UNKNOWN，先調和再重試。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
  "requires_design_rationale": false
}
```

## J8 本機知識增補

- LAN-010
- POL-002
- POL-003
- POL-004

執行只讀本機 library／cards；候選 0.2.0 待 Founder 審核及鎖定。
