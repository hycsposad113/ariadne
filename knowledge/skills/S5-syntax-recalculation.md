# S5 Syntax 重算

版本：0.2.0。狀態：規格草案，未整合生成器／服務。

## 目的

以版本一致的併網方法比較方案與現況，不讓顏色替代結果。

## 觸發時機

候選道路模式／拓樸或輸入 hash 變更。

## AI（LLM）責任

解釋目標差距及方法敏感性，不生成指標數值。

## 確定性程式責任

數值計算、拓樸與 CRS、時間/version/hash、排名與邊界敏感性均由確定性工具。

## 失敗處理

方法或邊界驗證缺失即 INCOMPLETE/EXPLORATORY；處理外部結果不確定時 OUTCOME_UNKNOWN。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。

## 輸入（實際repo檔案與缺口）

- src/urban_design/space_syntax.py
- src/urban_design/context_network.py
- src/urban_design/regional_network.py
- src/urban_design/syntax_context_api.py
- TODO_SOURCE: 方案併網、各模式各尺度重算 facade 與獨立參考引擎驗證，尚未整合

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

## 步驟

- 凍結同周邊圖與模式準入，核對高度／layer，不把平面交叉自動接通。
- 將道路依 mode 併網，保留原 id 與來源，記錄刪／新／改動。
- 按三模式、三尺度與兩指標計算；一般車網完全相同才可引用相同 hash 的既有結果。
- 與現況固定基準比較平均值、入口值、穿越 choice 和 High 比例，列缺值與分母。
- 比較擴大邊界與 MCA/最短路徑替代方法；不足維持 EXPLORATORY，不重貼 PASS。
- 輸入變更標 STALE，保留所有舊 run。

## 品質檢查

- 現有 space_syntax.py 明示未完成選定引擎比對；數學可重現不等於正式結果。
- 六層×三模式的缺項逐項回報，不能補成0。
- 書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。
- AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。
- 準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。

## 輸出結構與可載入契約

下列 JSON 為規格，output_fields 的值說明未來輸出欄位含義；不是執行結果。S6／S7／S8 缺非空設計意圖、理由或有效卡引用即不完成。

```json
{
  "stage": "S5",
  "title_zh": "Syntax 重算",
  "purpose_zh": "以版本一致的併網方法比較方案與現況，不讓顏色替代結果。",
  "trigger_zh": "候選道路模式／拓樸或輸入 hash 變更。",
  "inputs": [
    "src/urban_design/space_syntax.py",
    "src/urban_design/context_network.py",
    "src/urban_design/regional_network.py",
    "src/urban_design/syntax_context_api.py",
    "TODO_SOURCE: 方案併網、各模式各尺度重算 facade 與獨立參考引擎驗證，尚未整合"
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
    "SYN-013",
    "SYN-014",
    "MOB-015"
  ],
  "steps_zh": [
    "凍結同周邊圖與模式準入，核對高度／layer，不把平面交叉自動接通。",
    "將道路依 mode 併網，保留原 id 與來源，記錄刪／新／改動。",
    "按三模式、三尺度與兩指標計算；一般車網完全相同才可引用相同 hash 的既有結果。",
    "與現況固定基準比較平均值、入口值、穿越 choice 和 High 比例，列缺值與分母。",
    "比較擴大邊界與 MCA/最短路徑替代方法；不足維持 EXPLORATORY，不重貼 PASS。",
    "輸入變更標 STALE，保留所有舊 run。"
  ],
  "llm_responsibility_zh": "解釋目標差距及方法敏感性，不生成指標數值。",
  "deterministic_responsibility_zh": "數值計算、拓樸與 CRS、時間/version/hash、排名與邊界敏感性均由確定性工具。",
  "output_fields": {
    "status": "DRAFT | INCOMPLETE | INVALID；本技能不能 ACCEPT",
    "project_id": "專案 id",
    "input_refs": "輸入 artifact 路徑、sha256、版本、來源、日期、授權；不含密鑰",
    "assumptions": "參數卡 id/name/value/unit/provenance/status",
    "data_gaps": "缺來源、未知值或 TODO_SOURCE",
    "validation_refs": "deterministic 結果 id、工具版本、hash、單位、CRS、限制",
    "rule_card_ids": "實際使用的卡 id 與版本；不是僅整個 domain 名稱",
    "alternatives": "至少兩個選項、各自來源與代價；不自動宣告 winner",
    "runs": "mode/radius_m/metric/method_version/input_hash/result_ref/status",
    "target_comparison": "每目標 reached/partial/not_reached/unknown、值與單位",
    "delta": "同 id 對齐結果及樣本／邊界差異"
  },
  "quality_checks_zh": [
    "現有 space_syntax.py 明示未完成選定引擎比對；數學可重現不等於正式結果。",
    "六層×三模式的缺項逐項回報，不能補成0。",
    "書目查證狀態與主張查閱層級依本機 library；候選卡不能代替批准。",
    "AI 提議必經確定性程式驗證；驗證尚未實作不可回報 PASS。",
    "準入、來源、權利未知標 DATA_GAP，不能以零或猜值補齊。",
    "AI 執行時只讀本機規則卡與 library，禁止臨時網路引用；新知識須補充、查證、審核及新版本。",
    "候選版本 0.2.0 尚待 Founder 審核及鎖定；載入不啟用任何約束。"
  ],
  "failure_zh": "方法或邊界驗證缺失即 INCOMPLETE/EXPLORATORY；處理外部結果不確定時 OUTCOME_UNKNOWN。 不產生 HumanDecision。Founder 才能確認重大決策；不讀密語、正式 key 或 .env。派工禁止 Live AI／連網／服務操作時，僅輸出離線草案。",
  "requires_design_rationale": false
}
```

## J8 本機知識增補

- SYN-013
- SYN-014

執行只讀本機 library／cards；候選 0.2.0 待 Founder 審核及鎖定。

- MOB-015（J8 覆蓋：分模式路網／量體入口及服務回應）
