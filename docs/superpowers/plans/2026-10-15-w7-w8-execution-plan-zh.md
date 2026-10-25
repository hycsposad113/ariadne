# W7／W8 剩餘工作執行計畫（2026-10-15，Commander）

依據：`docs/superpowers/plans/2026-09-22-semester-project-blueprint-zh.md` §10–11、`docs/08_WORKFLOW_REALIGNMENT_2026-09-22.md` R26-01–14、Founder 10-08／10-14／10-15 指示。
分支：`wp/dl-quickfix`（worktree `w6-07-compare`）。正式 DB 只讀；合併 main 與重啟正式服務需 Founder 逐次核准。

## 0. 現況盤點

| 項目 | 狀態 | 證據 |
|---|---|---|
| R26-01–06 Understand（同步、保留、分區、基地分析、六張 Syntax） | 已上線 | main 9c4538c |
| R26-07/08 四種紋理方案＋FAR/高度校驗 | 上線（探索草案，整體驗證 FAIL） | artifacts/fab1/run-6 |
| R26-09/10 編輯、吸附 | W6 完成 | docs/w6 |
| R26-11 比較＋AI 說明 | Compare 上線；八個操作（Inspect…Override）未逐一驗收 | — |
| R26-12 E1 日照 | 完成 | docs/w6/e1-sunlight-* |
| R26-12 E2 輻射 | 實作＋副本演練 READY_FOR_FOUNDER；10-08 Founder 列為加分，未正式執行 | e2-execution-report-20261005T172815Z |
| NET2 路網接城市＋語法對基準 | 進行中；10-15 修正拓撲微縫後 harbour 步行主街 52.6（基準 57.3） | commit 8c2e200 |
| R26-13 出圖 | figure_export.py 存在；W8 正式出圖未做 | — |
| R26-14 凍結／重現／全套回歸 | 未做；上次全套 3 FAIL（已知環境／canonical） | e2 報告 |
| W8 報告 | 初稿 v1，已修 CROW 措辭 | docs/presentation/2026-10-15-w8-report-draft-zh.md |

## 1. 平行工作線

| 線 | 內容 | 執行者（模型） | 寫入範圍 | 完成定義 |
|---|---|---|---|---|
| A | NET2：12 組語法重算 → 評估表 → 若主街未達基準，改路網（先院落島、地景為圖）最多 2 輪 | 本機計算；改路網派 Codex gpt-6.1-sol medium（沿用 NET2 通道） | artifacts/net2/*、generation/fabric_net2.py | 四案評估表＋前後對照圖；誠實列出未達項 |
| B | W7-A/B 稽核：四階段 walkthrough、八個操作、錯誤注入、重啟重現；只讀出缺口清單與重現指令 | Codex gpt-6-luna max，read-only | 無（報告寫在 log） | 每項 PASS／FAIL／未實作＋證據路徑 |
| C | W8-B 出圖：基地、Syntax、量體平面、透視、等角、E1、方案比較 PNG（四案一致鏡頭與色階），中文圖名與圖例 | AGY gemini-3.8-flash-high（沙箱） | scripts/export_w8_figures.py、artifacts/w8/figures/ | PNG＋manifest（尺寸、雜湊、來源版本）；Commander 逐張檢查 |
| D | W8-A 凍結清單：資料集、依賴、模型／prompt、方法、場景、天氣與 recipes 雜湊；驗證腳本 | AGY gemini-3.8-flash-high（沙箱） | docs/w8/freeze-manifest.json、scripts/verify_w8_freeze.py | 腳本可重算並比對全部雜湊 |
| E | 全套回歸：pytest 全部、web test/build/lint | Commander 背景執行 | artifacts/w8/regression/ | 新鮮結果；失敗逐項分類，不改門檻 |
| F | 雙語全視圖演練（Compare/Generate × zh/en × 2D/3D/分割/四格 × 語法三視圖）＋console | Commander，臨時埠＋DB 副本 | artifacts/w8/rehearsal/ | 0 console error、無中英混雜 |
| G | 報告更新＋離線備用 demo（錄影＋圖紙）＋限制與未達假說 | AGY 初稿 → Commander 事實核對 | docs/presentation/ | 七分鐘稿與圖對齊最新數據 |

順序依賴：A 完成 → C 重出最終圖、F 演練 → 合併 main／更新正式平台（Founder 核准）→ G 錄 demo → Founder release decision。B、D、E 立即可跑。

## 2. 需要 Founder 的點（只在這些時候通知）

1. 合併 `wp/dl-quickfix` → main 並重啟 8795/5195（F 通過後）。
2. E2 是否在 W8 正式執行（否則報告列為「已實作、未正式執行」）。
3. 最終 release decision（W8-C）。

## 3. 護欄

不碰 8787／8644；正式 DB 只讀；不下載；Live AI 週上限 200 次；OUTCOME_UNKNOWN 不重送；執行者只在 wp 分支提交指定檔案；交叉審查由不同供應商（Codex 作品給 Claude／AGY 審，AGY 作品給 Claude 審）。
