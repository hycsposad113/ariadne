# R40–R55 成果審閱與分類（Triage）紀錄

**檔案路徑：** `docs/w4-closeout/r40-r55-triage.md`  
**依據：** `AGENTS.md`、`CLAUDE-commander.md`、[決定紀錄 PD-01–PD-18](../decisions/2026-09-25-plan-decisions-zh.md)、[Week 4 收尾執行計畫 WC-1](superpowers/plans/2026-09-25-week4-closeout-plan-zh.md)  
**來源分支與 commits：** `wp/w4-r40-r53`，commits `19ed8d6` 與 `10f0903`（未經審查）  
**審閱者：** AntiGravity (Gemini 3.8 Flash)  
**審查者：** Commander (Claude Opus 5.5)  
**最終決定者：** 設計者 (Jack)  

---

## 總覽與分級原則

依據 `2026-09-25-week4-closeout-plan-zh.md` WC-1 要求，對 `wp/w4-r40-r53` 中保留之 R40 至 R55 各項目進行逐一技術審閱，分類為「**採用**」（Adopt）、「**改寫後採用**」（Adapt）或「**捨棄**」（Discard）：

1. **第一優先：** R41（設計範圍）、R46（決策保護）、R50（分區範圍檢查）、R55（同步中狀態修補）。提供 Luna 第 1 天決策時段與前端畫面所需基礎。
2. **第二優先：** R40（數值驗證）、R43／R45（同步與瀏覽器錯誤恢復）。
3. **第三優先：** R44／R47（幾何與邊界）、R48／R53（PST 工作）。
4. **PST 單一實作原則：** 廢棄 R48 放置於 repo 內之 `runtimes/` 與 `src/urban_design/pst_engine.py`，改以 `wp/w5-04-pst-runtime`（`src/urban_design/syntax_engines/`）為準，runtime 放於外部目錄 `~/.local/share/urban-design-runtimes/pstalgo-3.3.1/`。
5. **PD-14 宣告無效原則：** R51、R54、R55 中由代理經電腦操作介面操作 QGIS 所產生之成果與 CP1「PASS_SCOPED」宣告均依 PD-14 認定無效，全部駁回並維持 C1 為 `BLOCKED（負責人：設計者）`。
6. **核心檔保護原則：** `src/urban_design/models.py`、`store.py`、`api.py` 在 `wp/w5-01` 合併進 `main` 之前不進行修改。

---

## 逐項審閱與分類清單

| 修訂 | Package ID | 原始目標 | 審閱判定 | 處置方式與技術理由 |
|---|---|---|:---:|---|
| **R40** | `week4-execution-r40-20260924T2340z-draft-number-validation` | 空間綱要 UI 數值輸入檢查（FAR、高度等可選欄位） | **採用** | **採納前端修改與測試** (`web/src/components/SidebarBrief.tsx`, `SidebarBrief.test.tsx`)。嚴格過濾無效浮點數與空白輸入，防止草稿參數被損壞。 |
| **R41** | `week4-execution-r41-20260925T0041Z-exploration-design-area` | 探索性設計範圍（Exploration Design Area）草稿與導出 | **採用** | **採納合約、前端與導出工具** (`workspace_contracts.py`, `workspace_service.py`, `Viewport2D.tsx`, `Viewport3D.tsx`, `types.ts`, `mapFigure.ts`, `schematicFigure.ts`)。權威 DB revision 6 DRAFT 包含此欄位，合約必須具備相容性以防回放反序列化失敗。 |
| **R42** | `week4-execution-r42-20260925T0249Z-live-qgis-sync` | QGIS 外掛程式與平臺同步連線記錄 | **改寫後採用** | **採納外掛啟動與連接防護** (`qgis_plugin/helpers.py`, `plugin.py`, `Open Urban Design QGIS.command`, `tests/test_m2a02_plugin_launcher.py`)。修正 process 檢查邏輯與 port 衝突處理。捨棄其「真實人類同步」之證據判定。 |
| **R43** | `week4-execution-r43-20260925T030835Z-live-sync-reconciliation` | 瀏覽器 response-loss 與重載對齊 | **改寫後採用** | **吸收其連線重試與狀態恢復邏輯** 至前端狀態管理。捨棄其一次性 E2E 證據包，因為該流程是在拋棄式資料庫上進行之代理探索。 |
| **R44** | `week4-execution-r44-20260925T0420Z-p1-syntax-boundary` | P1 Syntax 邊界與未提交 Overpass 提議 | **捨棄** | **全數捨棄**。未提交之 Overpass 查詢提案已被 PD-17 核准之 Geofabrik PBF 正式下載路線取代；WC-3 將實作正式語法層。 |
| **R45** | `week4-execution-r45-20260925T0521Z-browser-workspace-validation` | 拋棄式資料庫上之瀏覽器工作區驗證 | **捨棄** | **捨棄其證據包判定**。底層 UI 修正已在 R40/R41 吸收，本包僅為無狀態驗證紀錄，不影響正式運行。 |
| **R46** | `week4-execution-r46-20260925T0552Z-human-decision-brief-guard` | 人類決策保護：未經批准草稿不得視為正式設計約束 | **採用** | **採納核心防護與測試** (`src/urban_design/design_brief.py`, `tests/test_design_brief.py`)。嚴格落實 AGENTS.md 憲章「Humans decide」，草稿綱要於決策前不得轉化為確定之 brief 規範。 |
| **R47** | `week4-execution-r47-20260925T0602Z-geometry-feasibility` | 編輯幾何合成可行性驗證 | **改寫後採用** | **採納幾何偵測腳本與測試** (`scripts/probe_editing_geometry.py`, `tests/test_probe_editing_geometry.py`) 作為幾何運算之輔助驗證；不標定 CP4-1b 為正式通過。 |
| **R48** | `week4-execution-r48-20260925T0708Z-pst-engine-comparison` | PST 3.3.1 reference runtime 與 800 m 比較 | **捨棄** | **全數捨棄 repo 內 binary 與重複實作**。依 PD-01 及 WC-1，二進位不得放進 repo (`runtimes/pst-3.3.1-arm64/` 丟棄)。改採 `wp/w5-04-pst-runtime` 之標準路徑 `~/.local/share/urban-design-runtimes/pstalgo-3.3.1/`。 |
| **R49** | `week4-execution-r49-20260925T0811Z-runtime-test-reconciliation` | Radiance 搜尋路徑與測試對齊 | **改寫後採用** | **採納搜尋路徑修復邏輯**；Radiance 6.0.2 arm64 依 W6 前導線計畫安裝於外部目錄，不影響 repo 乾淨度。 |
| **R50** | `week4-execution-r50-20260925T085101Z-zone-scope-integrity` | 草稿分區範圍與重疊檢查（Fail-closed） | **採用** | **採納合約與服務驗證邏輯** (`workspace_contracts.py`, `workspace_service.py`, `SidebarBrief.tsx`)。嚴格阻止超出 Study Area 或互相重疊之草稿分區，保護幾何拓撲。 |
| **R51** | `week4-execution-r51-20260925T094757Z-qgis-live-sync-reload` | QGIS GUI 要素選取與即時同步 | **捨棄** | **全數駁回其狀態宣告（依 PD-14）**。該次操作確認為代理透過電腦介面模擬，違反「人類親自操作」憲章，不能作為 CP1 通過之依據。C1 維持 BLOCKED。 |
| **R52** | `week4-execution-r52-20260925T100325Z-independent-review` | 對 R51 之審查包 | **捨棄** | **捨棄**。因其基礎 R51 已被 PD-14 宣告無效，此審查包結論自然失效。 |
| **R53** | `week4-execution-r53-20260925T1018Z-pst-radius-alignment` | PST 半徑模式（metric vs step）比較診斷 | **捨棄** | **捨棄比較診斷**。WC-3 已明確定義半徑模式為 `walking`（metric 距離），由 `wp/w5-04` PST adapter 統一承接。 |
| **R54** | `week4-execution-r54-20260925T1244Z-cp0-status-matrix` | CP0 狀態矩陣（將 CP1 標為 PASS_SCOPED） | **捨棄** | **全數駁回（依 PD-14 與 WC-1 規範）**。嚴格禁止繼承其將 CP1 標示為 PASS_SCOPED 之主張。 |
| **R55** | `week4-execution-r55-20260925T1302Z-sync-outcome-unknown` | 同步超時與 OUTCOME_UNKNOWN 狀態修補 | **採用程式／捨棄宣告** | **採納前端連線防護程式** (`web/src/components/SidebarDispositions.tsx`, `SidebarDispositions.test.tsx`, `App.tsx`)。提供按鈕禁用與同步中動畫，避免重複派送與狀態不一致。駁回其包中關於 CP1 通過之主張。 |

---

## 整合成果之驗證紀錄

在 `wp/w4-closeout` 分支上完成上述「採用」與「改寫後採用」之程式整合後，執行之驗證結果：

1. **Python 核心測試：**
   - 命令：`.venv/bin/pytest tests/test_m2a02_plugin_launcher.py tests/test_workspace_sync.py tests/test_design_brief.py`
   - 結果：47 passed in 1.44s
2. **前端測試、建置與檢查：**
   - 命令：`npm --prefix web run test`
   - 結果：14 test files passed, 71 tests passed (0 failed)
   - 命令：`npm --prefix web run build`
   - 結果：Vite build 成功，無打包錯誤
   - 命令：`npm --prefix web run lint`
   - 結果：ESLint 通過，0 錯誤
3. **QGIS 外掛指令驗證：**
   - `Open Urban Design QGIS.command` 通過 process 檢查與啟動驗證。
