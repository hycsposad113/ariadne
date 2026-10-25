# 3D BAG 下載請求提案（未送出）

**狀態：** `NOT_SUBMITTED`。沒有網路請求、下載、DatasetSnapshot 或資料供應商聯絡。僅提出取得設計範圍內及緊鄰建築資料的方案，依 PD-11 等待設計者明確核准。

| 欄位 | 提案內容 | 現況／限制 |
|---|---|---|
| 資料集 | TU Delft 3D BAG，以 BAG identificatie 對應建築高度 | PD-11 指明授權 CC BY 4.0；實際資料版本尚未確認 |
| 端點 | 候選 OGC API Features endpoint：`https://api.3dbag.nl/collections/pand/items` | 只從專案來源名稱形成的未驗證候選；沒有連線確認。送出前須確認服務、collection、欄位與 API 版本 |
| 查詢範圍 | 只查設計者已批准 ExplorationDesignArea 內及其緊鄰的保留／可改建築，按 BAG ID 對應 | 當前 Commander 提供的唯讀 DB 副本中 workspace revision 6 沒有 ExplorationDesignArea／分區，也沒有批准 HumanDecision；因此 bbox／polygon 不能填寫。不得改用整個 StudyArea 代替 |
| 預計筆數／大小 | 未估算 | 尚無批准的查詢幾何與 BAG ID 集合；填入數量或大小會是虛構。批准範圍確定後，先提出只回傳要素計數／回應大小的 query plan，再請設計者核准 |
| 版本 | `UNRESOLVED_PENDING_ENDPOINT_REVIEW` | 不預先假定最新版本；請求批准前須記錄 API 宣告版本、資料時間／版本欄位與擷取時間 |
| 預期欄位 | BAG ID、屋頂高度第 70 百分位、地面高及用途對照需要的識別欄位 | 欄位名稱、垂直基準、單位與欄位是否能直接提供 P70 尚未驗證；收到 bytes 後才可核驗 |
| 授權 | CC BY 4.0（PD-11） | 擷取時仍須保存端點授權／來源聲明與 attribution |
| 用途 | 對匹配建築執行 `floor-estimate-v1`；每項標示 `ESTIMATE`，大空間用途顯示 `[1, 估算值]`，未匹配值保留 `UnavailableValue` | 不把估算稱作觀測樓層或實際 GFA |

## 請求前需補齊

1. 設計者批准 ExplorationDesignArea 與納入建築清單／BAG ID 範圍。
2. 在任何請求前，以本機以外的正式來源確認端點、collection、資料版本、欄位、單位、垂直基準、license 與 attribution；記錄查詢幾何及預估回應大小。
3. 將精確 URL、查詢參數、一次請求上限、逾時與 bytes 上限交設計者審批；未批准前不呼叫端點。

**設計者核准：** `________________`　**核准 HumanDecision ID：** `________________`  
**狀態仍為未送出；本文件不構成下載授權。**
