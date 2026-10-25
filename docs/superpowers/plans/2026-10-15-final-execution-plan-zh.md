# 最終執行計畫：第 7 輪定案 → 上線 → E2 → W8 交付（2026-10-15 傍晚起，Commander 自主執行）

授權來源：Founder 10-15「都要」（合併上線、E2、release）與出門前四項回答（見 memory `approvals-2026-10-15`）。
工作分支：`wp/dl-quickfix`（worktree `w6-07-compare`，HEAD 1eb79cd 已含 W7 修補）。正式 DB 只讀；不碰 8787／8644。
派工順序：AGY（gemini-3.8-flash-high，10-15 16:5x 已恢復）→ Codex（gpt-6-luna max；難題 gpt-6.1-sol medium）。交叉審查：作者與審查者不同供應商，Claude 審全部。

## 階段 1：資料定案（平行）

| 步驟 | 內容 | 執行者 | 完成定義 |
|---|---|---|---|
| 1.1 | round-7 汽車語法 4 組（`--modes motor_vehicle --resume`） | 本機（進行中） | `round-7/syntax` 12/12 COMPUTED |
| 1.2 | round-7 語法路段匯出到 `round-7/syntax/segments/`（含 receipt，<5 MB 單檔）與 NET2 評估表（含水域 manifest） | 本機 | export 成功、12 份 segments |
| 1.3 | 平台整合包 `artifacts/fab1/run-8/`：plan、checks、api-checks、landuse.csv、massing／axon／landuse 中文圖；API 預設來源 `net2` 改指 run-8＋round-7/syntax（保留 net1、run5 可切回）；修 int1b 等測試預期 | AGY | fabric/int1b/plans API 測試通過；Claude 審查 |
| 1.4 | Ariadne 設計說明重寫：中英各 4 篇，最多 8 次 Live AI＋4 次失敗重試；OUTCOME_UNKNOWN 不重送；數值經確定性驗證器 | Codex Luna max（沿用 S6/S8 通道與腳本） | 8 篇通過驗證器、呼叫計數記入 budget 檔 |
| 1.5 | W8 最終圖組 `artifacts/w8/figures/round-7-final/` | 已完成 16:5x | Claude 抽查 6 張 |

## 階段 2：驗證與上線

| 步驟 | 內容 | 完成定義 |
|---|---|---|
| 2.1 | 全套 pytest（clean archive）＋ web test/build/lint | 失敗項全部在已知清單內（classification-zh.md）；任何新失敗 → 修或停 |
| 2.2 | 中英雙語全視圖演練：臨時埠＋DB 副本；Site／Compare／Generate × zh/en × 2D／3D／分割／四格 × 語法原始／方案／差值；側欄、圖例、console 0 error、英文模式無中文 | `web/e2e/fabric_compare.py` PASS＋人工截圖抽查 |
| 2.3 | W7 瀏覽器腳本 `web/e2e/week7_real_override_dialog.py`（臨時埠＋DB 副本） | PASS 或如實記錄 |
| 2.4 | 合併 `wp/dl-quickfix` → main；重啟 8795／5195（同既有啟動參數，只換 morphology／syntax 來源）| live 健康檢查＋上線後自查全部視圖＋console |
| 2.5 | 失敗回退：上線後若主要視圖壞掉，立刻以前一版 main（9c4538c）重啟並記錄 | — |

停止條件：2.1／2.2 出現無法在一個小修內解決的新失敗 → 停在 wp 分支，寫交接，等 Founder。

## 階段 3：E2

| 步驟 | 內容 |
|---|---|
| 3.1 | 用上線版程式在 DB 副本演練 E2 全流程（快照 → 批准 → 計畫 → 批准 → 計算 → 發布 → 比較），驗證可行 |
| 3.2 | 寫給 Founder 的逐步說明（中文、附截圖）：哪兩步需要密語、按哪個按鈕、預期結果 |
| 3.3 | 正式執行等 Founder 回來操作密語步驟；Commander 只準備，不代為批准 |

## 階段 4：W8 交付

| 步驟 | 內容 | 執行者 |
|---|---|---|
| 4.1 | 重產凍結清單 `docs/w8/freeze-manifest.json` 並 `--check` PASS | 本機 |
| 4.2 | 報告更新：七分鐘講稿、結果表換 round-7、拓撲微縫發現、限制與未達項、R26-01–14 逐項狀態 | AGY 初稿 → Claude 事實核對 |
| 4.3 | 離線備用 demo：瀏覽器自動化走四階段逐步截圖＋W8 圖組 → 中文 PDF，標明版本 commit | 本機 |
| 4.4 | Release 呈報：R26-01–14 狀態表、限制、未達假說、產出路徑 → Founder 決定 | Founder |

## 營運規則

- 背景任務一律 `run_in_background`；長任務排 1200 s 以上備援喚醒。
- 額度用完（Codex／AGY／Claude）：記錄重置時間，ScheduleWakeup 到重置後繼續；同一件產出不換通道，除非送出請求前就被擋。
- 401／付款錯誤立即停止該通道；OUTCOME_UNKNOWN 不重送。
- 每階段完成寫協調事件與 `Q5/OPERATIONS-LOG.md`；只在需要 Founder 時通知（E2 密語、release、停止條件）。
