# Ariadne 判讀與對話式修正：四期執行計畫（2026-10-17）

依據：Founder 10-17 決定（memory `ai-judgement-program-2026-10-17`）與稽核 `docs/w8/ai-participation-ux-audit-2026-10-17-zh.md`。

## 不變的原則
- AI 只提判斷與方案；不代行 HumanDecision；所有數值只來自確定性計算，判讀文字中的數值必須逐一對上來源（metric_id＋單位），驗證器不通過就不顯示。
- 判讀品質不隨模型浮動：每個階段有**專屬 skill**（固定判斷框架、必讀知識單元、輸入組裝、JSON schema、驗證規則），模型只負責在框架內寫判斷。
- 複雜 skill 與知識庫由前沿模型撰寫（Claude Opus 為主，必要時 gpt-6.1-sol medium）；平台接線由執行者（AGY／Codex）施工，Claude 跨供應商審查。
- Live AI：每週 200 次；OUTCOME_UNKNOWN 不重送；401／付款錯誤即停。
- 正式 DB 只經既有寫入規則；演練一律 DB 副本＋臨時埠。

## 既有基礎（不重做）
- 知識庫 v2：`knowledge/v2/`（18 領域、2,026 單元，含 CLI 氣候主題 T01–T06）。
- 分階段 skill 規格 `knowledge/skills/S1–S8`、skill 執行器 `src/urban_design/skills/`（引用白名單、numeric_claims、驗證器、ModelRun 記帳），已有 `POST /api/v1/.../skills/runs`，但**前端未使用**。
- Ariadne 對話（只含基地證據）、MCP 工具雛形（critique／compare／draft_constraints）。

## 第 1 期：主線整合＋UI 修正
| 項目 | 完成定義 |
|---|---|
| 1.1 港埠可編輯 | 由已釘選的港埠 plan（sha256 88445feb…）確定性推導逐層量體（3.5 m 層高、含中庭洞），細修頁可開港埠正式草稿；不改已接受的 scenario payload |
| 1.2 方案收納 | 目前主線（四紋理方案＋選定港埠）置頂；W5 預覽與 W6 common-* 收進「歷史方案」可展開 |
| 1.3 E1 去重 | 平台內 E1 與附加氣候 E1 清楚分工或合併成一處，標明資料來源 |
| 1.4 代碼改人話 | 所有對使用者顯示的狀態代碼（BLOCKED_*、UNAPPROVED_PREVIEW、EXPLORATORY_DRAFT、FIXTURE_ONLY、FORMAL_DRAFT、FABRIC_PLAN_E2_ONLY…）改中英說明，代碼移到 tooltip |
| 1.5 Ariadne 面板 | 可展開成寬面板／抽屜；關閉時的說明改成使用者語言；待處理決策與實際狀態同步 |
| 1.6 版面 | 「第 7 週」等週次名稱改功能名；工具列狀態標籤與按鈕分開；條件頁左欄標題裁切；比較頁加分段索引 |
驗收：web／pytest 不新增失敗；中英全視圖演練；Commander 自查。

## 第 2 期：Ariadne 判讀卡（基地、比較、氣候）
- **判讀卡 schema（共用）**：`observations[]`（每條附 evidence_ref 或 metric_id＋值＋單位）、`judgement`（立場句）、`reasoning[]`（引用知識單元 KU／規則卡）、`confidence`（high／medium／low＋理由）、`revision_directions[]`（可執行的設計動作）、`counterpoints[]`（反例或替代觀點）、`limitations[]`。
- **三個 skill（前沿模型撰寫）**：
  - `J-SITE`：基地判讀（證據卡、語法、脈絡；讀 MOR／SYN／PUB／WAT／HAR 知識單元）。
  - `J-COMPARE`：多方案綜合判斷（指標、語法、形態檢核、E2；明確取捨與條件式排序，不宣告總冠軍）。
  - `J-CLIMATE`：氣候效能判讀（E1–E5 結果與限制；讀 CLI T01–T06；把結果翻成設計啟示與修改方向）。
- 每個 skill：判斷框架、必讀 KU 清單、輸入組裝器（只取已持久化的確定性結果）、驗證器（數值逐一比對、引用白名單、禁止詞）、離線評測集（同一輸入跑兩種模型，比對格式與關鍵判斷一致性）。
- 前端：各階段「Ariadne 判讀」卡，三個按鈕：同意／質疑（必填理由）／補充我的看法；紀錄進設計對話紀錄。
- **Founder 審查點**：判讀卡格式與三個 skill 的判斷框架（第一版出來時）。

## 第 3 期：對話式修正迴圈
- 設計者的質疑或意見 → Ariadne 讀判讀卡＋意見 → 回覆理解並產生**修正提案**（結構化：改哪些參數／條件／強度、預期影響、風險）。
- **每案需 Founder 核准才重算**（核准走既有人類決策入口）。
- 核准後：確定性生成器／編輯核心套用 → 重跑相關分析 → 新舊並排 → Ariadne 再判讀 → 寫入設計對話紀錄（可匯出成報告的 contestable 證據）。

## 第 4 期：生成階段 AI 參與＋E2 介面
- 形態設計意圖書在平台上顯示、可討論，依意見產生新意圖書並重生成（同樣每案核准）。
- E2 平台介面（建立快照、選基準、建立計畫、送出計算；密語仍由 Founder 輸入）。

## 派工與順序
- 第 1 期：1.1（後端幾何，Codex gpt-6.1-sol low）與 1.2–1.6（前端整理，AGY flash-high）平行，兩個 worktree；Commander 審查、瀏覽器驗證、整合。
- 第 2 期 skill 與知識框架：Claude Opus 撰寫；接線：Codex。
- 每期結束：整合分支全套測試與 main 基線比對、中英全視圖演練、Commander 自查 → 依授權上線。
