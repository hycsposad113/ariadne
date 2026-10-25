# I2：3D BAG 高度資料與 DatasetSnapshot 登錄

**狀態：** `DRAFT_FOR_COMMANDER_REVIEW`。資料與程式已在此 worktree 產生，權威資料庫尚未寫入，待 Claude（Commander）獨立審查。

## 範圍與來源

PD-23 核准使用 3D BAG 取得 active StudyArea v5 外擴 500 m 的真實建築高度。較早的 [3D BAG 下載請求提案](3dbag-request-proposal.md)記錄的是另一個尚待設計者批准的 ExplorationDesignArea 範圍；此線遵循較新的 PD-23 StudyArea 範圍，不修改該歷史提案。

本次選用官方版本化 tile 下載與官方 WFS tile index。官方文件指出 3D API 目前不符合 OGC API 標準；服務 collection 宣告版本為 `v2023.10.08`，因此本次使用較新的版本化 tile `v2025.09.03`，可核對每個 tile 的 SHA-256。欄位、圖層及授權資訊以官方文件為準：[Webservices](https://docs.3dbag.nl/en/delivery/webservices/)、[Layers](https://docs.3dbag.nl/en/schema/layers/)、[Attributes](https://docs.3dbag.nl/en/schema/attributes/)、[Copyright and License](https://docs.3dbag.nl/en/copyright/)。

採用欄位：`pand.identificatie` 為 BAG identificatie，`pand.b3_h_maaiveld` 為地面高，`lod22_2d.b3_h_70p` 為屋頂高度 P70。Tile 使用複合 CRS EPSG:7415，水平座標為 EPSG:28992，垂直基準為 NAP height EPSG:5709；高度單位為公尺。BAG ID 僅接受 `NL.IMBAG.Pand.<16 digits>` 或 16 位數字，後者正規化為官方完整格式。

`b3_h_70p` 位於屋頂分部圖層。當同一 BAG 建築有多個屋頂分部時，資料表採各分部有效 P70 的最大值，並記錄 `maximum-roofpart-b3_h_70p` 與方法版本 `3dbag-roof-p70-aggregation-v1`。這是資料整理規則，不是法規高度或設計判斷。

授權為 CC BY 4.0，署名文字為 **© 3DBAG by tudelft3d and 3DGI**。衍生資料的聲明記錄已選取 tiles、以 500 m 範圍篩選 footprint，並依 BAG identificatie 聚合屋頂分部值。

## 預檢、下載與衍生表

StudyArea v5 幾何及 GeoJSON artifact 的 hash、WFS 查詢參數、每項請求 URL／時間／狀態／大小／hash、官方 tile hash、授權與工具版本都記錄於 [3D BAG 來源 manifest](../../config/3dbag-height-source-manifest-v1.json)。WFS BBOX 預檢選出 3 個 tiles；三次 HEAD 回應的 `Content-Length` 合計 **10,550,762 bytes**（約 10.1 MiB），低於 200,000,000-byte 上限，才下載 tile。全程共 12 次直接 3D BAG HTTP 請求、0 次重試、0 次 HTTP 失敗；含 metadata 與 tile 的 response body 合計 16,353,881 bytes。Tile SHA-256 與官方 tile index 記錄相符。

Tile 是整個瓦片的原始回應，包含緩衝區以外的同瓦片建築；下載服務未提供精確 polygon 裁切。衍生高度表則以 StudyArea 真實幾何的 500 m buffer 和 pand footprint 做本機相交篩選，不把 bbox 當作最終範圍。三個完整 tile 共列 5,787 棟建築，這只是預檢上限資訊；精確 buffer 相交後資料表有 **964 筆**，964 筆均有有效高度配對。StudyArea buffer 面積為 2,211,479.009 m²，buffer 幾何 SHA-256 為 `sha256:6c45f8869089597ad7f78e97f52cb22150eda56fd7bebfb11119e711fcc41ace`。

原始 tile 和衍生表都留在 `~/.local/share/urban-design-data/3dbag/`，不納入 Git：

| 檔案 | 大小 | SHA-256 |
|---|---:|---|
| `tile-9-304-512-v2025.09.03.gpkg.gz` | 1,433,837 B | `ad74d7c249c617b985df70a7b7e5785b67dae15c4a713ca19bcd6853e47e0da4` |
| `tile-9-304-516-v2025.09.03.gpkg.gz` | 5,123,678 B | `c784d9e774c7f57a88d64499c540cd594e9002dd336f7601fe313242cf119967` |
| `tile-8-296-512-v2025.09.03.gpkg.gz` | 3,993,247 B | `0ef9379495a26fd3b1b64af6a1fa41fd4d90a55430baeb669a70d66fed32ad12` |
| `height-table-v2025.09.03-study-area-v5-buffer500m.json` | 445,470 B | `5897f273cf1180fa744692f71cb18b875adfa28737ddab10ade720a94f4a5f97` |

本次處理環境：Python 3.12.13、Shapely 2.1.2、GEOS 3.13.1、SQLite 3.51.0。buffer 使用 Shapely `buffer(distance_m, quad_segs=16)`；範圍 hash 使用正規化後的二維 little-endian WKB。高度表 schema 為 `3dbag-height-table-v1`。

第一次本機擷取 CLI 呼叫因 manifest 欄位映射不合而在預檢階段停止，未建立輸出、未改 manifest、未發出網路請求。修正欄位映射後執行一次成功擷取。無檔案清理或改名；網路請求沒有重試。

## W5-15 樓層估算介面

`urban_design.morphology.floor_estimate.estimate_floor_count_from_3dbag` 依 BAG identificatie 查表後呼叫既有 PD-11 `estimate_floor_count`。規則版本仍為 `floor-estimate-v1`，目前樓層高度仍是 fixture-only 3.0 m：

```python
table = load_3dbag_height_table(
    "~/.local/share/urban-design-data/3dbag/height-table-v2025.09.03-study-area-v5-buffer500m.json"
)
estimate = estimate_floor_count_from_3dbag(
    building_id="building-id",
    bag_id="NL.IMBAG.Pand.0599100010050132",
    building_use="woonfunctie",
    height_table=table,
)
```

輸出狀態為 `ESTIMATE`，不代表觀測層數或法定樓層。`industriefunctie` 仍輸出 `(1, estimated)` 範圍；找不到 BAG 對應、缺高度，或屋頂 P70 低於地面高，都輸出 `UnavailableValue`。不得以估算高度宣稱實際 GFA。

## Commander 的 DatasetSnapshot 登錄步驟

登錄程式預設只驗證來源檔案 hash 並在 stdout 輸出 typed `Artifact`／`DatasetSnapshot` bundle；預設不開啟資料庫。程式只在明確傳入 `--write`、資料庫路徑，以及 hash 已核實且與資料庫分離的寫前備份時，才呼叫 `ProjectStateStore.commit_batch`。程式會核對備份檔案 hash 和目標專案存在；Commander 必須在執行前自行確認備份是現行權威 DB 的一致快照，不能使用舊備份。程式會建立 3 個原始 tile `Artifact`、1 個衍生高度表 `Artifact`、3 個 `DatasetSnapshot` 及對應建立事件，不建立 HumanDecision。

Claude（Commander）審查後如決定登錄，步驟如下：

1. 確認此分支提交、manifest hash、原始 tile／高度表的檔案 hash，並以唯讀方式確認權威資料庫仍指向 manifest 中的 StudyArea v5 及相同 artifact／幾何 hash。建立備份前後核對資料庫 state-head IDs／revision 和 ledger 序號／事件 ID，確保備份沒有落後或涵蓋錯誤資料庫。
2. 依專案既有安全流程建立一致的 SQLite 寫前備份（須涵蓋 WAL 狀態），另存檔並計算該備份的 `sha256:<64 lowercase hex>`。本腳本不建立或清理備份。
3. 先執行預設唯讀輸出並檢視 bundle：

   ```sh
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python scripts/register_3dbag_snapshots.py --manifest config/3dbag-height-source-manifest-v1.json
   ```

4. 只有 Commander 完成審查並選定權威 DB 及備份後，才在其監督下明確加入 `--write --database <DB_PATH> --backup-path <BACKUP_PATH> --backup-sha256 <BACKUP_SHA256>`。此文件不代表已執行該寫入。
5. 寫入後核對列出的 Artifact／DatasetSnapshot ID 與 ledger event，並確認 HumanDecision 數量未增加；最後由 Commander 判定是否接受。不得把本地測試結果當成權威 DB 寫入證據或驗收。

## 狀態與尚待處理

- 本地 tile 校驗、離線精確相交、高度表 schema 與 snapshot bundle 均可供審查。
- 權威 DB 未寫入；DatasetSnapshot 尚未登錄。
- 3D 顯示目前可讀取這份高度表；要把表暴露為平台 API／圖層需其他批准工作線處理，本 I2 變更不擴大到 API、models.py、store.py 或前端。
- 整體完成狀態仍待指定測試結果和 Commander 的獨立審查。
