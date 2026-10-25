# Week 5–9 技術細節大綱｜2026-09-22｜v1

> **2026-09-25 修訂：** Week 9 文件中「W4 應已做 E3／E4／E5 可行性檢核」改為「W7 核心整合後才做」；Week 8、Week 9 文件中「沒有 Git」的敘述已不成立。詳見 [計畫層級決定紀錄](../../decisions/2026-09-25-plan-decisions-zh.md)。

這組文件補充「每週做什麼」背後的技術問題、資料依賴、互動細節與驗收觀察。它不是逐行 coding prompt，也不是已執行結果。日期是整理日期，Week 5–9 是學期週次，不推算未提供的日曆截止日。

## 閱讀入口

| 文件 | 內容 |
|---|---|
| [GrillMe 訪談紀錄](../../interviews/2026-09-22-grillme-workflow-interview-v1.md) | 關鍵原話、問答脈絡、撤回選項與最後決定 |
| [整體學期藍圖](../../superpowers/plans/2026-09-22-semester-project-blueprint-zh.md) | 全局範圍、時程與 weekly gates |
| [Week 4 詳細計畫](../../superpowers/plans/2026-09-22-week4-platform-site-analysis-zh.md) | 平台與基地分析的執行入口 |
| [AntiGravity / Gemini 3.8 Week 4 Prompt](../../prompts/2026-09-22-antigravity-gemini-3.8-week4-execution.md) | 可直接貼給外部執行器的 Week 4 實作指令與邊界 |
| [Week 5 技術細節](week5-generation-editing.md) | Brief、三至五策略、道路／街廓、FAR、基本編輯與儀表板 |
| [Week 6 技術細節](week6-geometry-environment.md) | 分面、樓板、吸附、座標轉換、日照與雙層輻射 |
| [Week 7 技術細節](week7-integration-recovery.md) | 狀態、重算、AI、八種 contest actions、錯誤復原與完整流程 |
| [Week 8 技術細節](week8-freeze-figures-report.md) | 凍結、重現、正式出圖、報告與核心驗收 |
| [Week 9 技術細節](week9-closeout-extensions.md) | 收尾、耗能、蓄熱、風場、精細網路與模型匯出 |

## 如何分辨「已決定」與「技術建議」

- **已確認需求：** 引自本次訪談與 [現行產品契約](../../08_WORKFLOW_REALIGNMENT_2026-09-22.md)，不在這組細節筆記中改掉。
- **建議的工程處理：** 用來落實需求的設計建議，尚不是已採用的程式 API、資料表或依賴版本；執行前以實際架構驗證。
- **待決技術事項：** 必須經 prototype、方法比較或具體人類選擇解決；不得偷偷套用數值預設。
- **檢核點：** 描述應看到什麼證據；此處寫出 checkpoint 不等於它已 PASS。

這些文件不另建第二套 gate。各週細節檢核對應原藍圖的 CP-W5–CP-W9；若細節暴露範圍衝突，先列差異，不默默改核心定義。既有歷史 artifact、批准邊界、模型／工具安全規則都繼續有效。

## 跨週技術依賴

```text
W4：資料快照、保留圖層、分區 brief、基地／Syntax 證據
 ↓
W5：可追溯策略＋有效方案＋基本編輯＋指標
 ↓
W6：可分析幾何＋正確 sensor／方法＋環境結果
 ↓
W7：可信版本關係＋完整互動＋復原／重播
 ↓
W8：凍結核心＋穩定出圖＋可驗證報告
 ↓
W9：修復與獨立附加，保留 W8 版本
```

天氣方法是 E2 及相關耗能分析的獨立依賴，不能用它阻擋所有空間工作。反過來，空間 gate 通過也不能替代天氣批准。

## 每週細節文件的共同結構

每週包含使用者可見成果、輸入與交付、技術主題、典型失敗、待決項目、phase/checkpoint 及交接資料。數學例子與效能目標若出現，會標示為 fixture／建議，不是基地測量或人類已批准值。

本組是截至 2026-09-22 的最新技術細節版 v1；後續修訂新增 v2 或新日期目錄，保留歷史。這次只有文件工作，沒有更新 SQLite、來源包、政策或實作程式。
