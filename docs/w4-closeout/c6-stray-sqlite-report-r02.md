# C6 殘留 SQLite 資料庫唯讀複核 R02

**檢查時間：** 2026-09-26 03:06 UTC
**檢查者：** Codex executor（本次執行環境為 Codex；與計畫指定的 AntiGravity/Gemini 執行者不同）
**方法：** SQLite `mode=ro`、`PRAGMA query_only=ON`、`PRAGMA quick_check`、檔案 SHA-256 與程式碼唯讀搜尋。未刪除、修改或重新命名任何資料庫、sidecar 或目錄。

## 殘留資料庫

目標是字面名稱為 `...` 的目錄下之 `/Users/jackhsieh/Downloads/TUD/Q5/project/.../urban_design_runtime/state.sqlite3`。

| 檢查項目 | 觀察值 |
|---|---|
| 大小 | 57,344 bytes |
| SHA-256 | `6453fc31047c09325168b2f9a114872aeb88909c181029815c975c68da254a49` |
| `PRAGMA quick_check` | `ok` |
| schema metadata | `schema_version=1` |
| `state_heads` | 0 rows |
| `state_versions` | 0 rows |
| `ledger_events` | 0 rows；無最後事件 |
| `-wal` / `-shm` | 0 / 32,768 bytes |

唯讀查詢確認這仍是空白初始化資料庫，沒有 workspace、Artifact、DatasetSnapshot 或 ledger 歷史。

## 權威資料庫對照

權威檔案 `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3` 的本次觀察值：大小 2,248,704 bytes、SHA-256 `6dd5d6e137032a8f08e3a119de2cd7399f9215f9567671c10bf7ffbda22d9fb4`、`quick_check=ok`、schema v2、ledger 215 筆，最後事件為 sequence 215 `CreateEvidenceCard`（`2026-09-26T01:45:13.425848+00:00`）。各類 current heads 為 Artifact 117、DatasetSnapshot 54、EvidenceCard 15、Project 1、StudyArea 5、ToolExecution 3、WorkspaceRevision 1；workspace revision 為 6。Project active pointer 指向 StudyArea v5，其狀態為 `CONFIRMED_FOR_EXPLORATION`，並記錄 supersedes v4。該資料庫 SHA-256 與本次檢查前的核對值一致。

兩份資料庫的用途及內容明確不同。殘留資料庫的空表不構成權威資料遺失證據；本任務未將它升格或接入執行流程。

## 路徑成因搜尋與處置

在 worktree 的 `src/`、`scripts/`、`tests/` 與 `.gitignore` 搜尋字面路徑 `.../urban_design_runtime`，沒有產生器命中。現行 API/server 預設使用 `.urban_design_runtime/state.sqlite3`；其他命中指向測試暫存 DB、提案封包 DB 或明確的隱藏 runtime 路徑。這支持「殘留資料庫是先前手動或暫時初始化的空副本」這一解釋，但無法由目前程式碼確定建立者或原始命令。

依 C6 的唯讀界線，保留殘留資料庫與現有 sidecar 原狀；不刪除、不改名、不執行清理。
