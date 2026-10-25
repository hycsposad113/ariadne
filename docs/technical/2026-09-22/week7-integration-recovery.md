# Week 7｜四階段整合、證據與復原：技術細節大綱

**日期／版本：** 2026-09-22／v1。**對應：** W7-A–C、CP-W7；R26-01–12、14。**本週定位：** 把已做出的功能接成可信工作流程，而不只是連起頁面。

[返回索引](README.md) · [上一週](week6-geometry-environment.md) · [下一週](week8-freeze-figures-report.md)

## 1. 整合的成功樣貌

從重新開啟的平台開始，載入一份可追溯的基地，看到保留物、brief 與分析；生成／載入三方案，解釋利弊，接受 B；修改 B，重新驗證並比較日照／輻射；質疑一個參數，再跑一個分支；最後保存、重開、出圖。

使用者應理解自己正在看哪個方案版本、數字是否過期、AI 的話根據哪份證據、下一步為何可以或不可以執行。這些要直接反映在介面，不需要人去讀 ledger 才知道狀態。

## 2. 頁面、階段與狀態不是同一件事

Understand／Explore／Test／Refine 是工作模式，不應實作成只能單向走一次的四頁 wizard。設計者選 B 以後仍可回去看基地或改 brief。

建議 UI 分開顯示以下維度；正式 enum 名稱沿用或擴充既有 typed models，不在此筆記另創不可相容的狀態表：

| 維度 | 例子 | 避免的混淆 |
|---|---|---|
| 幾何有效性 | 有效／違規草稿 | 「可保存」不等於「可分析」 |
| 人類接受 | 未決／已接受某 revision／已拒絕 | 新修改不繼承舊接受 |
| 分析執行 | 排隊／執行／成功／失敗／未知 | 程序結束不等於结果有效 |
| 結果時效 | current／stale | 舊成功結果仍可看但不能冒充最新 |
| 證據可用性 | 完整／缺資料／方法未批准 | 載入成功不等於語義合格 |

控制按鈕的入口要以 persisted state 判斷，不只靠前端 disabled。重新整理或直接呼叫 API 也不能繞過 gate。

## 3. 單一版本鏈：避免每個面板各有答案

地圖、3D、dashboard、AI、圖表與 export 都應引用相同 workspace/scenario revision。selection、camera 等介面狀態可以暫存；批准、幾何、分析與數值不能只存在 browser memory。

建議保存的依賴關係：來源快照 → 保留與brief → 生成／編輯版本 → 計量／graph → analysis run → Evidence Card → AI 解釋／出圖。任何 claim 應能反向追到計算與輸入。

**典型失敗：** 地圖切到 B2，側欄仍显示 B1 FAR，AI 引用 B0 日照圖，export 把三者混成「B2」。整合測試需要故意快速切方案與刷新，查它是否發生。

## 4. 哪些改動讓哪些結果失效

以下為依賴設計起點，實作需對照實際方法與參數；不是一律把所有分析清空。

| 改動 | 應重算／標 stale | 應可重用的部分 |
|---|---|---|
| 只增減樓層／高度 | GFA/FAR、高度限制、遮蔽與環境 | 無其他依賴變化時的路網／路徑 |
| 改 footprint | coverage/GFA、碰撞／保留、環境；入口改變時路徑 | 未受影響來源觀測 |
| 改道路／通道／入口 | graph、相依 accessibility／Syntax | geometry 與 sensor 未變的獨立結果，需實際依賴判斷 |
| 改用途 | 用途比例、耗能假設；若作目的地來源則其可達性 | 僅幾何決定的面積與陰影 |
| 改 weather／期間／recipe | 對應環境結果與比較 | morphology／原始路網 |
| 改圖例／camera | 圖像輸出 | 原始計算值 |
| 改硬限制 | 方案驗證／接受入口 | 舊證據仍保存，標明其舊限制版本 |

cache key 需包含實際影響計算的輸入、方法、版本、參數，不只 scenario 名稱。分析 idempotency key 與 cache key 不同：前者避免重複派送，後者決定既有結果可否重用。

## 5. 非同步工作、衝突與 OUTCOME_UNKNOWN

重點案例：B1 分析還在跑，使用者改成 B2。B1 回傳後可以保存為 B1 的有效結果，但 B2 仍需自己的計算。不得依「最後回來」更新 current result。

**建議 job 記錄：** 輸入版本/hash、方法與工具版本、批准參照、dispatch receipt、run location、開始／完成時間、輸出 hash、驗證與取消／失聯狀態。這是資料需求，不是規定必須另造一個 queue 技術。

dispatch 後連線丟失不能直接當作未執行。先尋找 receipt、程序／工具狀態、產出與 ledger；未能判定就保留 OUTCOME_UNKNOWN。取消請求成功送達，也不代表外部程序已確定停止。

多個分頁或重複點擊需使用 expected revision 與 idempotency。版本不符時呈現差異；不採 silent last-write-wins 覆蓋人類選擇。

## 6. Artifact 與 SQLite 的一致性

檔案系統與 SQLite 不會因一個函式就自然變成跨系統交易。建議以 staging、驗證、可辨識的發布狀態與復原規則處理；確切順序沿用經測的既有 publication contract。

需要測的故障點：產檔前、產檔後／DB 前、DB 提交前後、final directory 發布時、重開後 reconciliation。無論在哪裡失敗，都不能留下「DB 指向不存在檔案」卻被標完成的 package，也不能重試時刪到別人的已發布 package。

歷史完整性和當前 authority 分開查。合法增加 ledger 不是 archive corruption；原始檔少一 byte 才是完整性故障。已有 r03 verifier 的相容性問題要明示處理，不能通過默默改動舊 manifest 來消除。

## 7. 八種可質疑操作到底改變什麼

| 操作 | 使用者應看到 | 應保存的結果 |
|---|---|---|
| Inspect | 輸入、方法、單位、原始結果、限制 | 查看对象與必要稽核，不偽造新計算 |
| Challenge | 指出哪個假設／指標有問題 | contest event 與対象版本 |
| Modify | 修改參數／幾何的 preview 與影響 | 新設定／draft，必要人類確認 |
| Rerun | 新 job 與原基線並列 | 新 run，不覆寫原結果 |
| Compare | 相同單位／域／方法的比較 | 明示比較對與不可比較項 |
| Fork | 從某版本開分支 | parent lineage 與新分支 |
| Reject | 拒絕某個候選及理由 | rejection 仍可查閱 |
| Override | 人類選擇不同設計判斷 | 人類決定與理由；不更改計算值或讓無效證據變有效 |

不需要每次查看都要求額外批准；真正的設計／約束／實驗決定才依既有權限處理。相同已批准 rerun 不重複詢問。

## 8. AI 整合：解釋要與資料一致

模型每次收到的是作用範圍明確的 evidence bundle，而不是整個硬碟或所有歷史 JSON。至少帶 scenario revision、可引用 evidence、限制、允許行動與輸出 schema。

驗證分兩層：JSON 格式有效；引用關係與意思有效。存在的 evidence ID 也可能屬於別的方案、別的半徑、別的時段，不能只查 ID 是否存在。

比較敘述要避免隱藏總分／排名。不同機能或開放空間的偏好由人類判斷；模型可以提出假說但不得補算數值。「integration 高」不能直接推出「這條街一定最多人」。

網頁、案例文字與來源欄位屬資料，不是可重新授權工具的指令。檢索內容中若要求忽略規則、執行程式或外傳資料，不進入 tool permission path。

需要保存 provider/model、prompt template 版本、公開的結構化輸出、驗證與簡短理由；不保存私有 chain-of-thought。secret 不進 log、截圖或 export。

## 9. 效能與體驗問題

- 地圖／3D 要同步選取，但大範圍 context 可分層載入；不能為了快把缺失資料當成空。
- 重算按影響範圍執行；拖曳 preview 不與正式 job 共用「成功」標記。
- 長任務顯示階段、可取消狀態與最後已保存版本，不給假百分比。
- 單位、圖例與狀態不要只靠顏色；可比較項與不可比較項都有文字說明。
- 真實 model service 暫不可用時，仍能查看已有證據與編輯；若提供 deterministic mock，必須標為測試，不假裝 live AI 回覆。

效能驗收以 W5/W6 收集的案例與硬體條件設定，記錄操作 latency、simulation duration、儲存與記憶體；未量測前不承諾 FPS 或秒數。

## 10. 故障演練矩陣

| 注入情況 | 預期行為 |
|---|---|
| source／geometry hash 不符 | 拒絕受影響結果，不刪歷史 |
| 某個觀測来源 unavailable | 卡片顯示缺口，零值不冒充觀測 |
| 重複點擊 Run／雙分頁提交 | 不重複建立邏輯 run；衝突可見 |
| QGIS／model／simulation 失聯 | 分清派送前失败與派送後未知 |
| B1 延遲結果在 B2 後回傳 | 存到 B1，不污染 B2 |
| 前端刷新或後端重啟 | 恢復已提交狀態；未提交 preview 標明損失範圍 |
| 部分檔案已發布而 DB 失敗 | 可 reconciliation，沒有假完成或 peer deletion |
| AI 引用錯方案／單位／radius | 拒絕敘述並提供可用證據，不偷偷改原值 |

## 11. Phase 與獨立檢核

**W7-A／流程整合：** 由 reviewer 操作完整四階段，對比地圖、3D、dashboard、AI 与 export 的 revision。輸出操作紀錄與具體失敗點。

**W7-B／contestability 與復原：** 八種操作都有實質狀態效果；故障矩陣逐項有實測證據。重播可以不用再次下載 frozen sources。

**W7-C／出圖接線與附加入口：** Week 8 所需圖種都能取得正確資料和視角；耗能／蓄熱只在不擠壓核心修復時開始獨立支線。

**CP-W7：** 核心 R26-01–12 完整路徑可操作，E2 有真實通過證據。若 E2 或其他核心未過，清楚列 incomplete，不把成熟的其他功能也說成不可用。

## 12. 交給 Week 8

交付選定 demo revision、scenario／decision lineage、方法與依賴清單、實際 gate→test node/runtime 映射、可復原的 job 資料、已知限制、figure scene／legend presets。Week 8 應主要凍結與修復，不再猜各子系統怎麼連。
