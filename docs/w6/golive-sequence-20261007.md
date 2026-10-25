# W6／W7 上線序列封包（2026-10-07，Claude 指揮官）

> 狀態：**READY_FOR_FOUNDER**。下列每一步都要 Founder 在聊天中**當次明確核准**，核准一步做一步，做完立即驗證並記錄。
> 未核准前：不合併 main、不重啟正式服務、不寫正式 DB。

## 0. 要上線的內容
- 分支 `wp/w67-integration`（`Q5/w6-07-compare`），HEAD `4a01495`；main `516bbaa` 是它的祖先（可快轉或 no-ff merge）。main 之上共 74 個提交。
- 包含：
  - W6 收尾：Grok G0–G14；正式編輯 409 修正；E1 plan hash 綁定；ribbon；R04；custody 匯入；renderer v2 r2 修正。
  - E2 輻射實作，含雜訊門檻 NOT_SIGNIFICANT。
  - W7 改接真實資料，並整合進 UI。
  - J2 共用有效決策解析器、方案「重新考慮」。
  - J4 修正：STALE 傳播、草稿 Rerun、晚到結果與斷線處理。
- 程式變更：src／web/src／tests 共 189 檔，+26,435／−650。
- **另外有 1,243 個證據檔**（artifacts，約 166 萬行 JSON／log／圖）已經在分支歷史裡（見第 2 步的選項）。

## 1. 上線前狀態（Claude 已驗證）
| 項目 | 結果 |
|---|---|
| 全套 pytest（J4 狀態） | 2119 passed、2 已知失敗（沙箱 tty、歷史 PNG）、5 skipped |
| 走查 2a–2k（DB 副本，連跑 2 次） | 全部 PASS；兩次 E2 方向判定一致 |
| 故障矩陣 | 24／24 PASS |
| 前端 | vitest 319 passed；lint、tsc 通過 |
| 瀏覽器（Claude 在沙箱外） | 1440 寬無水平捲軸；Compare／Refine 版面正常；新分頁 console 0 錯誤 |
| 跨供應商審查 | 執行者全是 OpenAI；Claude（Anthropic）逐項審查 diff、抽跑測試 |
| 正式 DB | SHA `2f70e846…` 自始至終未變（ledger 303、HD 3、DS 5） |

## 2. 上線步驟（每步需 Founder 核准）
1. **備份正式 DB**：用 sqlite backup API 備份到 `.urban_design_runtime/backups/state-pre-w67-<UTC>.sqlite3`，並驗證 quick_check。
2. **合併到 main**，二選一（需 Founder 決定）：
   - (a) 直接 `git merge --no-ff wp/w67-integration`：證據檔一起進 main；
   - (b) 先開一條發布分支，最後一個提交用 `git rm --cached` 把 artifacts 移出 index（實體檔保留在磁碟），再合併。main 的目錄比較乾淨，但歷史裡仍有那些物件，repo 大小差不多。

   合併後，在 main checkout 跑全套 pytest、vitest、build、lint，失敗清單必須跟第 1 節一致。
3. **重啟正式服務**：8795（API）、5195（Web），用 nohup，舊 log 先改名保留。指令見 `Q5/OPERATIONS-LOG.md` 交接快照 C 節。重啟後，瀏覽器確認 Site／Compare／Refine 正常。
4. **重新生成 5 個方案**（r4 南側集散道路版）：在正式網站的 Generate 分頁按 Full scheme。新方案以 PROPOSED 寫入正式 DB，舊的 5 個保留。
5. **Founder：決策三**：Compare → 「選定基準方案」→ 選一案並寫理由 → 其餘四案逐一寫駁回理由 → 輸入密語。之後如果要改，可以用新的「重新考慮」，同樣需要密語。
6. **Founder：批准 E1 plan artifact**（3／6／12 月 21 日、08–18 時、15 分鐘、5 m、全部公共開放空間），輸入密語。
7. **Founder：批准天氣方法**（candidate-01 DatasetSnapshot），輸入密語。之後由指揮官在正式環境跑 E1、E2。
8. **Founder：C1 QGIS 本人同步**（runbook：`docs/w4-closeout/c1-qgis-runbook.md`）。
9. Live AI：依 Founder 10-06 的決定**維持 BLOCKED**。

## 3. 還原方式
- 程式：`git revert -m 1 <merge commit>`，再重啟服務。
- 資料：停止服務 → 用第 1 步的備份還原 → 重啟。正式 DB 是 append-only，第 4–7 步新增的紀錄會一起消失，需要重做。

## 4. 已知限制（不擋上線，照實記錄）
- 歷史 PNG 測試維持 BLOCKED（Founder 2A）；renderer 是另建的 v2 baseline。
- `-u-` 的 Radiance 雜訊門檻、40 m 可達、4.5 m 巷道、E2 反射率 0.2 都是 ASSUMED_COMMANDER，Founder 可以改。
- Space Syntax 800 m 邊界穩定性仍是 EXPLORATORY。
- E3／E4 只有入口，標 NOT_ACCEPTED。
