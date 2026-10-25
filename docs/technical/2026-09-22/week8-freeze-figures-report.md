# Week 8｜核心凍結、出圖與報告：技術細節大綱

**日期／版本：** 2026-09-22／v1。**對應：** W8-A–C、CP-W8；R26-13、14 與全部核心驗收。**本週目標：** 可穩定展示、出圖、重現的核心版本。

[返回索引](README.md) · [上一週](week7-integration-recovery.md) · [下一週](week9-closeout-extensions.md)

## 1. 「至少 90%」要如何落地

使用者的期限是 Week 8 大致完成、Week 9 收尾。驗收時先問核心流程是否完整，而不是計算寫了多少檔案或測試。

現行核心清單 R26-01–14 包含三尺度 Syntax、三方案、直接編輯與分面、E1/E2、出圖；不得臨時把沒做完的核心改成 optional。耗能／蓄熱／風場、精細交通模式、模型檔匯出依原排序另外報告。

若呈現百分比，列出凍結的分母／权重及通過證據；否則用「核心通過 12/14、兩项阻塞」比沒有依據的 90% 更有用。項目大小不同，簡單計數不是工時或品質百分比。

## 2. 凍結哪些東西，不能只備份程式

| 凍結対象 | 內容 |
|---|---|
| 程式／依賴 | 原始碼版本清單、lockfiles、外部 runtime 路徑與版本、OS/架構、授權 |
| 資料與方法 | StudyArea、來源 bytes、query／licence、policy、CRS、解析／轉換版本 |
| 設計狀態 | brief、保留物、分區、限制、scenario lineage、seed、接受／拒絕／override |
| 分析 | graph、Syntax 設定、sensor、天氣、時間、材料、recipes、原始輸出與 log |
| AI | provider/model、template 版本、實際結構化回答、引用與驗證結果 |
| 圖像 | camera、visible layers、圖例範圍、單位、版型、解析度、引用的結果版本 |
| 驗收 | actual collected tests、runtime evidence、獨立 reviewer、限制與 release decision |

專案若仍不是 Git repository，以有版本的 manifest、hash 與不可覆寫資料夾形成 release record；不能寫不存在的 commit SHA。不要把 secret、token 或私人環境檔帶入研究包。

## 3. 重現不等於所有東西都重新 live 呼叫

分三層驗證：

1. **檔案完整性：** frozen bytes 的 size/hash 一致。
2. **確定性重播：** 相同輸入與受控 runtime 可重建 geometry／metrics／state。浮點與 simulation 的容差、比較規則事前寫清楚。
3. **解釋與展示重播：** 保存的 AI 回覆與 figure settings 能對應當時證據；新的 model 呼叫即使 prompt 相同也不保證字句完全相同，不能用它覆寫歷史解釋。

比較 geometry bytes 前先採用已定義 canonicalization；數值重算看已指定 tolerance，不能遇到差異才放寬。保存「原值」「新值」「差異」「判準」，不只一個 PASS。

受控環境應與日常開發狀態分開，但不要求破壞使用者現有服務。QGIS 與 Radiance 等外部工具的執行證據不能用 Python package import 取代。

## 4. 出圖功能：先定義圖種與資料

| 圖種 | 主要內容 | 必要標示 |
|---|---|---|
| 基地分析平面 | 建築／道路／機能／開放空間與限制 | 來源、scope、比例尺／北向、缺資料 |
| Space Syntax | 各尺度 integration／choice | metric、radius、正規化、色階、boundary limitation |
| Morphology 平面 | 道路階層、保留／新建、開放空間、用途 | scenario revision、圖例、設計邊界 |
| 透視 | 選定視角的空間關係 | 方案、是否 draft、必要分析圖例 |
| 等角圖 | 可比較的量體／道路構成 | 正交投影設定、方案版本、比例解讀限制 |
| 環境結果 | E1／E2 空間分布 | 單位、期間、method、sensor domain、缺失與過期 |
| 方案對照 | 同框幅比較 A/B/C 或修改前後 | 相同 camera／尺度規則、方法一致性 |

先保證可靠 PNG 與簡單版面；不把 PDF、任意排版或三種 CAD 格式都變成新核心工作。等角通常應用正交投影的固定角度；不要把任意 perspective 截圖叫作等角。

## 5. 相機與 scene preset

保存 camera target、position／orientation、projection、視野或 orthographic scale、clipping planes、畫面比例、顯示圖層、背景与 geometry revision。不同方案比較時預設同一預設視角與範圍，必要差異明示。

**技術問題：** 各方案 auto-fit 後看似同大小，實際量體尺度不同；或 near/far clipping 裁掉地面；或選取高亮被匯出當作分析色彩。

導出前確認 scene 已載入、最新 render 完成、非同步分析圖層與字體載入完成。隱藏 gizmo、選取框、hover tooltip、聊天與 debug panel。渲染背景與透明輸出要實際檢查，不能只看 canvas 在瀏覽器裡正常。

## 6. 圖例、顏色與資料誠實

數據色階是 method/result 的顯示設定，要保存；出圖不能重新以另一個極值範圍着色卻仍使用舊圖例。跨圖用共同 color range 或明示不相同。

缺值、未分析、無效 sensor、範圍外、真實零值要有可辨識符號，不全部塗最冷色。stale／draft／illustrative 的標示不能因「想要乾淨」就移除。

分析圖的單位與研究範圍要足以獨立理解；一張圖離開平台後，讀者仍應知道那是某日 hours、某期間 kWh/m²，還是無單位／方法特定的 Syntax 指標。不能把彩色渲染當成沒有定義的「環境舒適度」。

## 7. 解析度與版面品質

輸出以明確 pixel dimensions 管理；DPI metadata 不會自動增加細節。投影片與印刷的尺寸需求先分開決定。本文件不替使用者預定 A1/A3 或某個解析度為硬限制。

技術上要檢查高解析度 render target 的 GPU／memory 限制、長標題與中文字型、圖例位置、線寬／文字比例、透明背景、抗鋸齒與檔案大小。超過能力時回報可選尺寸，不生成無聲截斷圖。

若背景 map tiles 或圖片造成跨來源 canvas export 問題，採合法可匯出的底圖／已允許資源或不含該底圖的明示模式；不能繞過來源條款或偷偷讓整張圖只剩空白。

## 8. 圖像與研究資料的關係

建議 FigureArtifact 連結到 scenario、result、camera／legend settings、輸出 bytes/hash、建立時間與軟體版本。這是責任分工建議，不宣稱該型別目前已實作。

PNG 可以是交付物，但不能是唯一留存的分析資料。保存原始數值、幾何與圖層，才能追溯或重畫。幾何／結果未變、只改字體的重出圖，是新 figure revision，不是重新進行 climate experiment。

## 9. 出圖驗收要真的打開檔案

| 案例 | 需要檢查 |
|---|---|
| 地圖 PNG | 尺寸與 extent、北向／比例尺、來源與圖例不被裁切 |
| 透視／等角 | camera 正確、保留／新建可辨、無 gizmo、無漏面 |
| 三方案拼圖 | 相同鏡頭／色階、標籤對應正確、沒有混用 revision |
| 環境熱圖 | 單位／期間／方法、sensor 缺口、色階與數值相符 |
| 高解析度與長文字 | 字體不缺字、圖例不溢位、記憶體失敗有回報 |
| 過期／違規草稿 | 可以作明示研究記錄，但不能輸出為無標記正式成果 |

應同時做自動檔案／metadata 檢查與人工視覺檢查；像素對比受平台影響時，不要僅靠 exact screenshot hash 判斷資料正確性。

## 10. 報告版本與七分鐘展示

七分鐘是先前提案簡報的已知長度；若最終報告另有要求，再依實際規格調整，不假定學期最終也一定七分鐘。可以先保留七分鐘精簡版本：

| 時間 | 訊息與畫面 |
|---|---|
| 0:00–1:00 | 問題、使用者角色、四階段流程 |
| 1:00–2:30 | 同步、基地理解、三尺度 Syntax 與人類設定 |
| 2:30–4:00 | 三個策略、比較與選 B、直接編輯 |
| 4:00–6:00 | 證據與環境前後比較、一次 challenge/rerun |
| 6:00–7:00 | 已證明結果、限制、哪些附加尚未完成 |

優先展示一個真實、可追溯的完整例子；不要串接不同版本的片段偽装成單次操作。備用錄影可避免現場依賴，但要註明錄製版本，不能代替產品驗收。

## 11. 缺口分類與 release decision

**核心阻塞：** 例如 Syntax 算法不正確、少於三個有效策略、編輯面積錯誤、E2 無批准來源、無法出完整圖、重開後失去決策。要列為 incomplete。

**可收尾缺陷：** 不改數值／決策的版面瑕疵、非關鍵操作便利性，可列修復清單；由實際影響判斷，不一律說輕微。

**附加未做：** E3/E4/E5、模式精細化、模型檔匯出，依原規劃報告，不降低已完成核心。

人類決定可展示／release 的版本與限制。這項决定不使錯誤數值變正確，也不把未通過的核心標成 PASS。

## 12. Phase 檢核與 W9 交接

- **W8-A：** 凍結清單完整，能在受控環境重播；runtime 與數值差異符合事前定義。
- **W8-B：** 每種核心圖都實際產出與打開檢查；資料、版本、圖例与畫面一致。
- **W8-C：** 展示腳本、離線備用、已知限制與人類 release decision 可查。
- **CP-W8：** 核心清單與證據逐項核對；不以口頭「90%」取代驗收。

交付給 W9 的是明確 frozen baseline、修復優先序、報告資源與獨立附加入口。不能把未完成的核心藏在「最後一週加功能」裡。
