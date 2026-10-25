# C6 殘留 SQLite 資料庫唯讀調查報告

**檔案路徑：** `docs/w4-closeout/c6-stray-sqlite-report.md`  
**依據：** [修正計畫 C6](superpowers/plans/2026-09-25-control-tower-correction-plan-zh.md)、[Week 4 收尾執行計畫 WC-6](superpowers/plans/2026-09-25-week4-closeout-plan-zh.md)  
**調查者：** AntiGravity (Gemini 3.8 Flash)  
**審查者：** Commander (Claude Opus 5.5)  
**調查時間：** 2026-09-25 15:42 UTC  
**調查原則：** 唯讀檢視，不刪除、不修改。

---

## 1. 調查對象與檔案屬性

在專案主目錄根目錄發現帶有三點路徑之殘留資料庫：
- 路徑：`/Users/jackhsieh/Downloads/TUD/Q5/project/.../urban_design_runtime/state.sqlite3`
- 建立／最後修改時間：2026-09-19 13:54 CEST
- 檔案大小：57,344 bytes
- SHA-256：`6453fc31047c09325168b2f9a114872aeb88909c181029815c975c68da254a49`
- 伴隨檔案：
  - `state.sqlite3-wal`: 0 bytes (2026-09-19 13:54)
  - `state.sqlite3-shm`: 32,768 bytes (2026-09-25 17:42 唯讀連接時生成)

---

## 2. 結構與內容檢驗

以 `mode=ro` 進行 SQLite 唯讀查詢：

1. **完整性檢驗 (`PRAGMA quick_check`)：**
   ```text
   ok
   ```
2. **資料庫結構與筆數統計：**
   - `store_metadata`: 1 筆 (`('schema_version', '1')`)
   - `state_heads`: 0 筆
   - `state_versions`: 0 筆
   - `ledger_events`: 0 筆
   - `sqlite_sequence`: 0 筆
3. **最後事件時間：**
   - 無任何 ledger 事件（事件數 = 0，序號 MAX = None）。

---

## 3. 與權威資料庫（Authoritative DB）之對比

| 屬性 | 殘留資料庫 (`.../urban_design_runtime/`) | 權威資料庫 (`.urban_design_runtime/`) |
|---|---|---|
| **檔案大小** | 57,344 bytes | 786,432 bytes |
| **SHA-256** | `6453fc31047c09325168b2f9a114872aeb88909c181029815c975c68da254a49` | `3e30c3d4d73f58a9455584ca39423f9f1f1a9c5018652670c863f76f5b3b56a9` |
| **Ledger 事件數** | 0 筆 | 187 筆 |
| **State Heads** | 0 筆 | 7 筆 (Artifact 4, DatasetSnapshot 2, WorkspaceRevision 1) |
| **最後事件** | 無 | Sequence 187 (`2026-09-25T11:02:40+00:00`) |
| **Workspace 狀態** | 無 | revision 6 DRAFT |

---

## 4. 來源代碼搜尋與路徑成因分析

1. **代碼搜尋結果：**
   - 經搜尋 `src/`、`scripts/`、`tests/` 全部檔案，所有程式皆指向 `.urban_design_runtime/state.sqlite3`（前綴為句點）。
   - 沒有任何現行源碼中存在 `.../urban_design_runtime`。
2. **成因分析：**
   - 該目錄於 2026-09-19 13:54 建立。在 Unix 系統中，`.` 為當前目錄，`..` 為上一層目錄，而 `...` 為字面名稱之普通目錄。
   - 當時某個手動指令或臨時腳本在初始化 `ProjectStateStore` 時，路徑誤輸入為 `.../urban_design_runtime/state.sqlite3`（例如將 `../..` 誤打為 `...`）。
   - `ProjectStateStore` 初始化時呼叫 `_init_db()`，建立資料表並寫入 `schema_version = 1`，但隨後並未寫入任何業務資料或 ledger 事件。
   - 該目錄隨後被棄置，並於 `.gitignore` 第 16–17 行明確加入忽略規則：
     ```gitignore
     # Stray runtime copy of unknown provenance (kept on disk, not tracked; see correction plan)
     /.../
     ```

---

## 5. 結論與建議處置

- 該資料庫為初生即棄置之空結構，無任何遺失之歷史資料、決策或憑證。
- 依據 `AGENTS.md`「不進行破壞性修改」原則及 C6 規格，**保持硬碟原狀，不刪除、不修改**。
