# Week 5 D1 設計者操作指南

**狀態：未就緒；完成下方就緒閘門前，請勿開始正式決策時段。** 本指南是 D1 使用說明，不代表 UI、決策流程或 C1 已驗收。

## 開始前的就緒閘門

Control Tower 須先審查並整合 W5-1 決策機制與 W5-2 設計範圍流程；同一個可執行版本必須能分別預覽並送出三類目標：Exploration Design Area、要素處置、Spatial Brief。每個確認摘要都要列出目標版本與 geometry/artifact hash、要素 ID 清單或分區內容。若任一條件缺少，改做非正式 walkthrough，不輸入密語、不建立決策。

就緒閘門通過後，設計者在自己的終端機執行 `python -m urban_design.decision_key init` 並自行設定密語；不要將密語告訴協作者或寫入文件。若初始化失敗，停止正式決策時段。

目前 W5-1 分支的 `Record Review` 只對 active StudyArea 記錄 `Inspect`；它不代表上述三類決策。`Sync Workspace` 只保存 Workspace DRAFT revision，也不是 HumanDecision。不要用其中任一操作代替正式確認。

## 正式時段（約 30–45 分鐘）

1. 開啟已審查／整合的 Ariadne build。核對頁首專案是 `Rotterdam M4H Pilot`，active StudyArea 為 `study-area-rotterdam-m4h-pilot-project-v5`，狀態為 `CONFIRMED_FOR_EXPLORATION`；版本或狀態不符即停止。
2. 在 **Spatial Brief** 畫 Exploration Design Area：點選 `Draw exploration design area`，沿預定邊界放置頂點，按 `Finish Polygon`，檢查面積（m²），再按 `Save draft area`。它是 StudyArea 內的探索分母，不是法定基地界線。若驗證報錯，不要用同步繞過。
3. 在 **Dispositions** 分別檢視 Buildings 與 Roads，逐項或對明確選取項標記 **Preserve／Editable／Undecided**。核對選取數量與 ID；未決項仍保留在來源，不會被生成器刪除。不要在未檢視清單時使用全選批次操作。
4. 回到 **Spatial Brief**，逐區填寫用途／需求；把硬性條件與偏好分開，畫區域後選 `Finish Polygon`、`Add Draft Zone`。檢查每區名稱、需求與幾何；彼此重疊或超出設計範圍時先修正。
5. 如需持久化草稿，使用 **Sync Workspace**，確認摘要中的專案、StudyArea、revision、要素處置與區域內容。同步成功只代表 DRAFT 已保存。
6. 只有在就緒閘門通過後，才逐一開啟三類目標的決策確認摘要。設計者本人核對 target ID、revision/hash、要素／分區清單、動作與理由，再親自在對話框輸入決策密語並確認一次。密語不得傳給協作者、貼入聊天或截圖。若摘要沒有綁定本次內容，取消並停止。
7. 設計者重新載入平台，確認三筆決策各自對應正確版本與 hash。保存操作前後截圖及可見時間；不要讓代理代按或在決策時段替設計者擷取畫面。

## C1 QGIS 重驗（另行記錄）

執行前由設計者決定同步至平台副本或權威 DB；寫入權威 DB 須有明確授權。使用者本人確認可見 QGIS 視窗標題、專案與所選 StudyArea 後，只按一次 **Sync to Platform**。記錄 site-context 200、sync 201、revision 前後值、來源快照／要素 ID 與截圖序列。若請求結果不明，先核對平台副本或權威狀態再決定是否重試；不要關閉或重啟不屬於本次任務的程序，也不要碰 Hermes 8787。
