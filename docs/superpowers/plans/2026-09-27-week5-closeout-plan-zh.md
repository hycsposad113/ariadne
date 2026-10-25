# Week 5 收尾執行計畫（2026-09-27）

**撰寫與審查：** Claude（Commander）。**執行：** AGY（Gemini 3.8 Flash）與 Codex（gpt-6-luna max）。
**起點：** `main` = `c1c6e58`（W5 整合、W4 Syntax 修正、W6 前導線已合併）。

## 0. 本輪設計者決定（2026-09-27，於聊天室以選項題回答）

### PD-20 三尺度改用三種交通模式的路網（取代 PD-02／08 契約的「共同路網」基線）

設計者表示：800 m 算行人、2 km 算腳踏車、10 km 算汽車，依正常荷蘭道路規則訂定過濾原則；自行車網依荷蘭 RVV。

| 尺度 | 路網 | 納入 | 排除 |
|---|---|---|---|
| 800 m | 行人 | 人可走的全部：footway（含 sidewalk、crossing）、pedestrian、living_street、residential、unclassified、service、path、steps、track、tertiary／secondary／primary（一般道路可通行與過街）；cycleway 只在 `foot` 為 yes／designated／permissive 時納入 | motorway、motorway_link、trunk、trunk_link（荷蘭 autoweg 禁止行人）、`motorroad=yes`、`foot=no`、`access=no/private` 且無 foot 例外、施工／廢棄 |
| 2 km | 自行車（依 RVV） | cycleway；`bicycle=yes/designated/permissive` 的 path／footway；fietsstraat（`cyclestreet=yes` 或 `bicycle_road=yes`）；允許騎車且沒有強制側邊自行車道的一般道路：residential、living_street、unclassified、tertiary、service，以及未標 `bicycle=use_sidepath`、`cycleway=separate` 的 secondary／primary | motorway、motorway_link、trunk、trunk_link、`motorroad=yes`、`bicycle=no`、`bicycle=use_sidepath`、無 bicycle 許可的 footway／pedestrian／steps、施工／廢棄 |
| 10 km | 汽車 | motorway、motorway_link、trunk、trunk_link、primary(_link)、secondary(_link)、tertiary(_link)、unclassified、residential、living_street | pedestrian、footway、cycleway、path、steps、track、bridleway、service 中的 driveway／parking_aisle／drive-through、`motor_vehicle=no`、`access=no/private`、bus-only（bus_guideway、`access=no`＋`bus=yes`）、施工／廢棄 |

- 立體交叉照 PD-15 以 layer／bridge／tunnel 與 unlink 表達。
- PST 的 angular 分析視路網為無向；單行道方向性不被模型反映，寫入限制。
- 標籤不足時（例如缺 `foot`、`bicycle`）依荷蘭預設規則推定，並把推定比例寫進 metadata；不得把未知當成禁止或允許而不記錄。
- UI 可以標示「行人路網 800 m／自行車路網 2 km／汽車路網 10 km」；但結果是空間結構指標，不是人流、車流或交通量預測。三尺度的網不同，數值不可跨尺度直接比較。
- 新政策為 `syntax-network-policy-v2`（mode-specific），仍需設計者檢視結果後批准，批准前結果標 EXPLORATORY。

### PD-21 Syntax 熱力圖顯示

- 每張圖層各自以**五分位**分成五級：very high／high／medium／low／very low（各約 20% 路段），圖例標出各級數值範圍。
- 配色採 **藍→紅（depthmapX 風格）**：very low 藍、very high 紅；未計算或被排除的路段以灰色虛線顯示並在圖例說明，不得塗成最冷色。
- 平台可切換六張圖層（三尺度 × integration／choice），也能匯出含圖例、尺度、路網模式、方法、狀態的 PNG。

### PD-22 Live AI 路線（擴充 PD-12）

- 優先序：① API key（OpenAI gpt-4o 等，設計者存入 Keychain）；② Hermes 專用 profile（沒有工具、不寫記憶）；③ 新增本機 CLI 子程序路線：`codex exec`（ChatGPT 登入）與 `claude -p`（Claude 登入）。
- CLI 路線的隔離要求：在新建的空暫存目錄執行；Codex 用 `-s read-only --ephemeral --skip-git-repo-check`，Claude 用 `-p` 並關閉工具；不得讀取 repo、權威 DB、key 或使用者檔案；只把 evidence bundle 放在 prompt 內；輸出以本地 validator 驗證；逾時與失敗照 PD-12 處理。以訂閱帳號供本機程式呼叫是否符合服務條款，由設計者自行判斷。

### 核准事項

設計者核准：合併 w4-closeout 修正與 W6 前導線（已完成，`6224d13`、`c1c6e58`）；依 PD-20 重算後，把六張圖層以分析紀錄寫入權威 DB（寫前備份快照；仍標 EXPLORATORY）。第 1 天決策今天進行。

## 1. 工作線

| 線 | 執行者 | 分支／worktree | 內容 | 可動的檔案 |
|---|---|---|---|---|
| A | AGY | `wp/w5-d1-flow`／`Q5/w5-d1-flow` | 第 1 天決策流程 | App.tsx、SidebarBrief.tsx、SidebarDispositions.tsx、HumanDecisionDialog.tsx、新元件、api.py 的決策摘要端點、D1 操作說明 |
| B | AGY | `wp/w5-syntax-modes`／`Q5/w5-syntax-modes` | PD-20 路網與重算、PD-21 熱力圖 | regional_network.py、pst_syntax.py、extract／compute 腳本、config/runtimes/syntax-network-policy-v2.json、SidebarSyntax.tsx、新的 syntaxHeatmap 工具與元件、mapFigure.ts 的 Syntax 圖層部分 |
| C | Codex | `wp/w5-ai-routes`／`Q5/w5-ai-routes` | PD-22 AI 三路線 | model_provider.py、site_critic.py、新檔、config/model-providers.json |

- A 與 B 都可能動到 `Viewport2D.tsx`：A 只能動與決策、設計範圍相關的部分；B 只能動 Syntax 圖層繪製部分；衝突由 Commander 合併時處理。
- 三條線都不得修改 `models.py`、`store.py`；若必要，停下回報。

## 2. 共同規則

- 只在自己的 `wp/*` 分支 commit；不碰 main、push、reset、clean、刪除。
- 不寫入權威 DB；不建立 HumanDecision（測試用臨時密語與 DB 副本除外）；不接觸 Hermes 8787、8644；不修改 `web/index.html`、`web/src/index.css` 與舊證據包；不讀出或記錄任何 key 或密語；不再委派。
- 長時間計算必須在前景同步執行並等待完成，不得丟到背景（print 模式結束時背景任務會被終止）。
- 大型資料（PBF、GeoJSON、SQLite）不得 commit，放在 `~/.local/share/urban-design-data/`，Git 只留 manifest 與 hash。
- 停損：同一項 2 次嘗試無進展就停下並寫明卡點與選項。所有重試、清理、改名都要揭露。
- 測試：Python 用 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src RAYPATH=$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib PATH=$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin:$PATH /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/pytest -q -p no:cacheprovider`；前端 `npm --prefix web run test`、`build`、`lint`。

## 3. 線 A：第 1 天決策流程（最優先，今天要用）

1. 設計者在平台上完成：畫設計範圍（ExplorationDesignArea）、標記保留／可改／未決、畫分區，按同步保存成 WorkspaceRevision。
2. 新增「確認第 1 天決策」按鈕：開啟 HumanDecisionDialog，目標為目前的 WorkspaceRevision（id、revision、payload_digest），並附設計範圍的 geometry hash（WC-2b 已支援）。對話框先列出摘要：設計範圍面積與 hash、保留／可改／未決各幾棟與幾條道路（附 ID 清單可展開）、分區清單與硬性／偏好條件。設計者輸入密語後送出。
3. 未保存的變更存在時不得送出；送出後顯示 HumanDecision ID 與狀態；重新載入後可看到決策紀錄。workspace 之後若再修改，舊決策標示「對應舊版本」。
4. 若後端缺少讀取決策摘要的端點，在 api.py 新增唯讀端點；不修改 store.py 的決策驗證。
5. 修訂 `docs/technical/2026-09-22/week5-d1-session-guide-zh.md`（若此檔被證據包記錄為 parent，改寫成新檔 `docs/w5/d1-session-guide-v2-zh.md`）：一步一步寫給設計者，含啟動方式、操作、決策摘要代表什麼、密語輸入、完成後怎麼確認。
6. 測試：前端單元測試（摘要內容、未保存禁止送出、送出成功顯示）、API 測試（綁定 payload_digest 與 geometry hash、過期拒絕）；瀏覽器 E2E 用 DB 副本與測試用臨時密語檔跑完整流程並附截圖。

## 4. 線 B：三模式路網、重算、熱力圖

1. 從 `~/.local/share/urban-design-data/osm/zuid-holland-260922.osm.pbf` 重新裁切（保留 highway、foot、bicycle、motor_vehicle、access、motorroad、cycleway*、sidewalk*、footway、service、cyclestreet、bicycle_road、layer、bridge、tunnel、oneway 等標籤），依 PD-20 產生三種網：行人（外擴 1.5 km）、自行車（外擴 4 km 與 6 km）、汽車（外擴 15 km 與 20 km）。記錄各網路段數、推定比例。
2. 以 PST（walking 半徑、PD-15）計算：行人網 800 m、自行車網 2 km、汽車網 10 km 的 integration 與 choice；做穩定性比較（自行車 4 vs 6 km、汽車 15 vs 20 km）。前景同步執行，每次 PST 呼叫上限 7,200 秒，記錄實際秒數。
3. 產出可供 WC-2 持久化腳本寫入權威 DB 的結果檔與寫入步驟（寫入由 Commander 執行）。
4. 熱力圖（PD-21）：新增 syntaxHeatmap 工具（五分位分級、depthmapX 藍→紅色階、未計算／排除路段灰色虛線），接到平台的 Syntax 側欄與 2D 圖層，可切換六張圖；匯出 PNG 含圖例（五級名稱與數值範圍）、路網模式、半徑、方法、狀態。
5. 測試：路網過濾規則的 fixture 測試（每條 RVV 規則至少一例：autoweg 禁行人與腳踏車、use_sidepath、fietsstraat、driveway 排除等）、五分位分級與色階的單元測試、穩定性報告、全套測試。

## 5. 線 C：AI 三路線

1. 檢查 main 上 W5-AI 的 profile 驅動模型層，補上缺漏：OpenAI API key 路線、Hermes 專用 profile 路線（每次先 GET /v1/toolsets，有工具就拒絕）。
2. 新增 `cli_subprocess` adapter，兩個 profile：`codex-cli`（`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex exec -m gpt-6-luna -s read-only --ephemeral --skip-git-repo-check -C <新建空暫存目錄> --output-schema <schema>`）與 `claude-cli`（`claude -p`，關閉工具，於空暫存目錄）。evidence bundle 只放在 prompt；輸出依 JSON schema 與本地引用 validator 驗證；逾時 120 秒；每次呼叫寫 ModelRun（provider=codex-cli／claude-cli、實際模型字串若可得）。
3. 平台設定頁顯示各 profile 狀態（可用、缺 key、停用、超出預算），可選擇使用中的 profile；不顯示也不輸入 key。
4. 測試全部用假 transport／假子程序；不得在測試中真的呼叫 CLI、API 或 Hermes。另提供一支 live 煙霧測試腳本（預設不執行），由 Commander 在設計者同意後執行。

## 6. 完成後（Commander）

逐線審查、在沙箱外重跑全套測試；依核准把 PD-20 結果寫入權威 DB；經設計者核准後合併進 main；在平台上替設計者啟動第 1 天決策時段。

## 7. 追加決定（2026-09-27 下午）

### PD-23 周邊環境與設計範圍改進
- 平台 2D／3D 顯示 StudyArea 外擴 **2 km** 的周邊環境：建築、水體（水陸介面）、道路、綠地／土地使用。資料來源用已下載的 Geofabrik PBF（OSM，ODbL），不新增 PDOK 請求；基地（StudyArea／設計範圍）內建築明顯、外面淡色。Syntax 熱力圖可疊在周邊環境上。
- 3D 高度：StudyArea 外擴 **500 m** 內下載 **3D BAG**（TU Delft，CC BY 4.0）的真實高度，設計者已核准；下載前確認端點、資料版本與大小，超過 200 MB 停下請設計者確認。500 m 外的周邊建築：OSM 有 height／building:levels 就用，沒有就只畫平面輪廓並在圖例說明，不捏造高度。
- 設計範圍：新增一鍵「使用整個 StudyArea」；手畫超出 StudyArea 時自動裁切到 StudyArea 內，預覽裁切後形狀與面積，設計者確認才保存。

| 線 | 執行者 | 分支 | 內容 | 可動檔案 |
|---|---|---|---|---|
| I1 | AGY | wp/w5-context | 2 km 周邊環境圖層（PBF 萃取→API→2D／3D 呈現）、設計範圍兩項改進 | 新的 context 萃取模組與腳本、api.py 的 context 唯讀端點、Viewport2D.tsx／Viewport3D.tsx 的周邊圖層部分、SidebarBrief.tsx 的設計範圍部分、新元件 |
| I2 | Codex | wp/w5-3dbag | 3D BAG 下載（StudyArea＋500 m）與高度整合（周邊 3D、W5-15 樓層估算） | 新的 3dbag 模組與腳本、floor_estimate.py、config 下的 manifest |
