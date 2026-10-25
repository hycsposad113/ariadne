# 計畫層級決定紀錄（2026-09-25）

**性質：** 設計者在聊天室以選項題回答 Control Tower 的提問，本文件逐項記錄選擇與其工程後果。這些是**排程、方法與權限**的決定，不是基地、約束、方案或天氣來源的批准；那些仍需各自的 HumanDecision。
**提問者：** Claude（Control Tower）。**決定者：** 設計者（專案使用者）。**記錄方式：** 選項標題照錄；設計者的自由文字回覆以引號標示。

## PD-01 Space Syntax 引擎（解決「Syntax gate 沒有決策點」）

- 設計者表示：「我的 QGIS 裡面本來就有 depthmapX 的引擎外掛」。
- Control Tower 核查：預設 QGIS profile 裝有 Space Syntax Toolkit 0.3.10（esstoolkit）。它把計算送到 depthmapXnet 伺服器，本機沒有該伺服器，也沒有任何 depthmapX 執行檔。同一 profile 另有 **PST 3.3.1**（KTH／Chalmers，LGPL-3），附原生 arm64 `libpstalgo.dylib` 與 Python ctypes 介面 `AngularIntegration`、`AngularChoice`，支援公尺網路半徑。
- **決定：** PST 當參考＋效能引擎。
  - 將 pstalgo 3.3.1 複製到專案管理的 runtime 目錄並固定 SHA-256，經 typed adapter 呼叫；不透過 QGIS 或 QGIS MCP 執行。
  - 先在測試小網路與 M4H 子網上與自製引擎比對，一致就定案。800 m 兩者皆可；2 km、10 km 用 PST。
  - PST 與自製引擎的定義差異（角度成本、半徑量測方式、正規化）寫進 method manifest。
  - **期限：W5 第 2 天。** 逾期未一致即依 PD-05 停損上報。

## PD-02 區域路網資料與計算（解決「10 km 沒有規劃」）

- 設計者重申：800 m、2 km、10 km **三個尺度都要**。
- **決定：** 分階段＋單一 OSM 檔。
  - 一次下載 Geofabrik 的南荷蘭省（Zuid-Holland）OSM 抽取檔（ODbL）。下載前列出檔名、大小、日期、授權，經設計者核准。
  - 先算 2 km（StudyArea 外擴約 4 km），完成效能測試後再算 10 km（外擴約 20 km）。
  - 若 20 km 外擴超出省界（例如南側的 Noord-Brabant），記錄邊緣限制，或另外申請相鄰抽取檔。
  - **計算預算：** 單次執行不超過 2 小時（本機），超過就簡化路網或調整做法，並上報。
  - 「分階段」只是先後順序，六張圖層全部是必做範圍。

## PD-03 人類決策的時間與方式（解決「決策沒排日期」）

- **決定：** 分兩次。
  - **第一次（W5 第 1 天）：** 設計者在平台上親手畫設計範圍（ExplorationDesignArea）、選保留建築與道路、畫分區。
  - **第二次（W5 第 3 天）：** 設計者看過基地分析與測試方案後，在聊天室選 FAR、高度、層高、道路寬度等數值。Control Tower 事先準備選項與影響說明。
  - 兩次都透過 C2 的人類確認機制寫成 HumanDecision。**因此 C2 必須在 W5 第 1 天的決策時段前完成。**

## PD-04 分析結果寫入權威 DB（解決「分析結果未持久化」）

- **決定：** 授權執行者追加分析紀錄。
  - 可追加寫入：ToolExecution、Artifact、EvidenceResult／EvidenceCard，以及生成器產出的 PROPOSED 狀態 Scenario 與其幾何 Artifact。
  - 寫入前做權威 DB 的備份快照並記錄 hash；actor 標為 AGENT_AUTOMATION。
  - **仍然禁止：** HumanDecision、Constraint 的啟用、StudyArea 或設計範圍的批准、方案接受。
  - 設計者於 2026-09-25 確認：生成的 PROPOSED Scenario 與編輯產生的 DRAFT Scenario revision 可以寫入權威 DB。

## PD-05 停損規則（解決「沒有停損或重排規則」前半）

- **決定：** 2 個 revision 或 1 個工作天。
  - 同一個 gate 連續 2 個 revision 或 1 個工作天沒有功能進展（只有加固、補證據、改文件），執行者停下，交出具體卡點與選項，由 Control Tower 與設計者決定。
  - 週末未完成的項目列為下一週的明確延續項，不阻擋獨立工作線。

## PD-06 證據包分級（解決「沒有停損或重排規則」後半）

- **決定：** 三級制。
  - **第 0 級：** commit＋測試輸出。適用一般程式修改。
  - **第 1 級：** 第 0 級再加瀏覽器截圖與簡短紀錄，放進 commit。適用 UI 功能。
  - **第 2 級：** 完整 R 包（integrity manifest、verifier、故障注入）。只用於 gate 判定、寫入權威 DB、外部 runtime、下載。

## PD-07 E3／E4／E5 可行性檢核時點（解決「E3–E5 檢核沒做」）

- **決定：** W7 核心整合後才做。
  - W4 計畫 P1.2 對 E3／E4／E5 的可行性要求，以及 Week 9 文件「W4 應已做可行性檢核」的敘述，改以本決定為準。
  - **接受的風險：** 工具鏈若裝不起來，要到 W7 後才會發現；屬附加項，不影響核心驗收。
  - C8（OpenFOAM）與 EnergyPlus／OpenStudio 檢核都排在 W7 核心通過之後。

## PD-08 天氣方法（解決「天氣沒有決定期限」）

- **決定：** 推導方法＋敏感度測試。
  - 依 EnergyPlus 通則，把既有 Rotterdam TMYx 檔的 `Minute=0` 視為該小時的**終點**。這是**專案假設**，不是供應商證據；原始 bytes 不變，以逐列對照表產生推導檔。
  - 同時做正負 1 小時位移的敏感度測試。若位移會改變 E2 比較的方向，就在結果中標明。
  - **期限：W5 結束前，由設計者以 HumanDecision 正式批准。** 批准前不得發布 DatasetSnapshot，也不得開始正式氣候實驗。

## PD-09 新增需求 R26-15（設計者要求）

平台 2D 即時比例尺、北向箭頭、座標讀數，以及距離／折線／面積測量；3D 兩點距離與高差。測量值只供參考，不是 EvidenceResult。W5 基礎、W8 完整。規格見修正計畫 C7。此需求記錄在此而非 `08` 契約本文，理由同藍圖修訂第 11 項。

## PD-10 Live AI provider（2026-09-25 追加；已由 PD-12 擴充）

- 設計者表示：「看有沒有辦法用 OpenAI 的 OAuth 登入，然後用 GPT-4o」。
- Control Tower 說明：OpenAI API 沒有提供給第三方應用程式的 OAuth 登入；以 ChatGPT 帳號登入只適用於 OpenAI 自家工具。本專案要呼叫 OpenAI API，需使用 **API key**。
- **決定：** provider 為 OpenAI，模型 GPT-4o，驗證方式為 API key。
  - 設計者自行在 OpenAI 後台建立**專案專用 key** 並設定用量上限，存入 macOS Keychain（服務名稱 `urban-design-openai`）。代理不得建立、輸入、讀出、顯示或記錄 key。
  - 伺服器啟動時從 Keychain 讀取；另需 `PROJECT_OPENAI_AUTHORIZED=1` 才啟用 live 呼叫。
  - 第一次使用時，以模型清單 API 確認帳號可用 GPT-4o；若不可用，停止並請設計者改選模型，不得自行替換。
  - 送出資料限於 evidence bundle：公開 PDOK／OSM 衍生值、分析結果、方案指標與限制。不含 key、檔案路徑、個人資料。
  - 預設上限：W5 全週 200 次呼叫，單次輸出 2,048 tokens，逾時 30 秒；設計者可調整。
  - 每次呼叫記錄 ModelRun：provider、實際回傳的模型版本字串、prompt 模板版本與 hash、請求與回應 hash、驗證結果、狀態。

## PD-11 保留建築樓層估算（2026-09-25 追加）

- 設計者表示：自動偵測 BAG 建築的高度，大概推算幾樓即可，不需要很精確。
- Control Tower 說明：BAG `pand` 只有用途、建造年、狀態等欄位，沒有高度。高度需另外取自 **3D BAG**（TU Delft，以 BAG ID 對應，CC BY 4.0）。
- **決定：** 以 3D BAG 高度估算保留建築樓層。
  - 只取設計範圍內（及其緊鄰）保留與可改建築的資料。下載前列出端點、範圍、筆數或大小、版本，經設計者核准後再下載。
  - 估算規則 `floor-estimate-v1`：樓層數 = max(1, round((屋頂 70 百分位高度 − 地面高度) ÷ 估算層高))。估算層高沿用第二次決策時段批准的標準層高；批准前用 3.0 m 並標 `FIXTURE_ONLY`。
  - `gebruiksdoel` 為 industriefunctie 等大空間用途（倉庫、廠房）時，高度換算會高估樓層，改顯示範圍 [1, 估算值]，FAR 以範圍呈現。
  - 所有估算值標為 `ESTIMATE`，附高度來源、規則版本與限制；不當作觀測值，不宣稱是實際樓地板面積。
  - 找不到 3D BAG 對應的建築，維持 UnavailableValue，不填 0。

## PD-12 通用模型層：API 路線＋Hermes 路線（2026-09-25 追加，擴充 PD-10）

- 設計者表示：OAuth 不行的話，改用開源或 Claude、xAI Grok 等可接 API 的方式，保持通用；保留兩種路線，一種是 Hermes，一種是接 API（提供 provider 與 API key）；開源 API 如 OpenRouter、Ollama、ModelScope 都可以；都不行就直接接 Hermes，因為 Hermes 可以用 OpenAI 的 OAuth 登入。
- **決定：** 建立 provider-neutral 的模型層，同時支援兩條路線。

**路線 A：API（provider＋key）**

| adapter | 涵蓋的 provider | 驗證方式 |
|---|---|---|
| `openai_compatible` | OpenAI、xAI Grok、OpenRouter、ModelScope、Ollama（本機） | Keychain 中各自的 key（Ollama 不需要） |
| `anthropic` | Claude（原生 Messages API） | Keychain |
| `gemini` | Gemini（既有 adapter） | Keychain 或既有環境變數 |

- base URL、模型名稱、是否支援 JSON schema 等，寫在 `config/model-providers.json`（不含任何 secret）。每個 base URL 在第一次使用前，都要對照官方文件確認。
- 每個 profile 的 key 由設計者存入 Keychain，服務名稱為 `urban-design-<profile-id>`。
- PD-10 的 OpenAI GPT-4o 保留為第一順位的 profile；有 key 且帳號可用 gpt-4o 時就用它。

**路線 B：Hermes**

- 使用 Hermes Agent（本機 0.21.4）內建的 OpenAI 相容 API，走 `openai_compatible` adapter。Hermes 背後可用 OAuth 登入的 OpenAI Codex 或 xAI 模型。
- **必須使用專用 Hermes profile**（建議名稱 `urban-critic`）：api_server 的 toolsets 為空、不寫長期記憶、獨立埠號。現有的 `life-agent`（8644）啟用了工具與記憶，**不得使用**。
- 專用 profile 由設計者建立，或設計者明確授權後由執行者依 Hermes 本機文件建立；新 profile 開在新的 gateway 行程，不得停止或重啟既有的 Hermes 行程。
- 每次使用前以 `GET /v1/toolsets` 確認沒有啟用任何工具；有工具就拒絕使用。請求不帶 `X-Hermes-Session-Key`。
- `API_SERVER_KEY` 由設計者存入 Keychain（`urban-design-hermes`）。
- 8787 的 Hermes 網頁介面仍然不可接觸。
- ModelRun 要記錄 Hermes 版本、profile、Hermes 回報的模型，以及從該 profile 設定唯讀取得的上游 provider 與模型。

**選擇與切換規則**

- 使用中的 profile 與備援順序由設計者在設定中明確指定。預設順序：OpenAI GPT-4o → 設計者另外設定的 API profile → Hermes `urban-critic`。
- 只有在**確定請求沒有送出**（缺 key、連線不上、401／403）時，才自動換到下一個 profile。回應驗證失敗、逾時、送出後失聯（OUTCOME_UNKNOWN）都不換，直接回報。
- 每個 AI 回答都在介面上標出實際的 provider 與模型。
- 全部路線合計，全週上限 200 次呼叫。
- 資料外送：雲端 provider 與 Hermes（上游為雲端）都會收到 evidence bundle；Ollama 留在本機。送出內容限制同 PD-10。
- 以 ChatGPT 或 xAI 訂閱的 OAuth 經由 Hermes 呼叫，是否符合該服務條款，由設計者自行判斷；本專案只記錄實際使用的路線。

## PD-13 W6 前導線與外部執行路線（2026-09-25 追加）

- 設計者同意開一條與 Week 5 平行的「W6 前導線」，並表示：「給我 prompt，我會交給 Gemini 3.8 Flash 執行」。
- **決定：** 依 AGENTS.md 的外部升級條款，設計者授權以 Gemini 3.8 Flash 執行 [W6 前導線計畫](../superpowers/plans/2026-09-25-w6-precursor-lane-plan-zh.md) 的 F1–F5。成果交 Claude（Control Tower）審查，執行者不得自行驗收或合併。
- 範圍限於合成 fixture 的前置工作；檔案範圍與 Week 5 主線分開；不寫權威 DB；不讀天氣檔；不呼叫模型服務。
- **下載核准：** 交付該 Prompt 即代表核准唯一一項下載：LBNL-ETA Radiance 6.0.2 macOS arm64 官方壓縮檔（8,202,089 bytes，SHA-256 `329ca788…118cf0`，與 Milestone 1 相同檔案）。

## PD-14 R42／R51 的 QGIS 同步由代理操作（2026-09-25 追加）

- R42（ledger 186，workspace revision 5）與 R51（ledger 187，revision 6）的 QGIS 同步寫入權威 DB，actor 記為 `designer`。設計者確認：「是代理操作的」。
- **處理：**
  - 原紀錄不刪不改。W5-1 合併後，由 Week 5 執行者為事件 182–187 追加來源註記：182–185 的 `designer` 是程式預設值、未經驗證；186–187 是代理經電腦操作介面操作 QGIS，actor 記錄有誤。設計者的回答即授權把這些註記追加寫入權威 ledger。
  - 這兩次同步都不算 C1 交接驗收。C1 仍需設計者本人按 Sync to Platform，並留下截圖或錄影。
  - 今後代理不得透過電腦操作介面代替設計者執行會寫入權威 DB 的 GUI 動作；代理驅動的 QGIS 或瀏覽器測試只能連到 DB 副本，actor 標為 AGENT_AUTOMATION 或 TEST_HARNESS。

## PD-15 PST 定為正式 Syntax 方法（2026-09-25 追加，取代 PD-01 的比對驗收方式）

- R48、R53 比對未達 method-comparison-v1：改用 PST 的 walking 半徑後，總深度 Spearman 0.988、choice 0.991，第 95 百分位相對誤差 4.0% 與 42.1%（門檻 1%）。設計者依停損規則選擇：PST 定為正式方法。
- **決定：**
  - 本專案的 angular integration／choice 以 PST 3.3.1 的定義為準，method manifest 寫明角度成本、半徑、正規化、分段方式與版本。
  - 半徑模式採 PST 的 `walking`（沿路網距離）。依據是 08 契約的「公尺半徑」指沿網路量測的距離，不是直線距離。
  - 驗證改為用可手算的小網路（直線、T 字、十字、不同轉角、孤立元件、立體交叉）檢查 PST 本身，不再要求與自製引擎一致。
  - method-comparison-v1 的結果照實保存為 **FAIL**，不得改寫成通過；自製引擎退為歷史參考，不再用於新結果。
  - R02 的 800 m 以 PST 重算成為新結果；舊值保留並標示為舊方法。
  - 立體交叉（bridge／tunnel／layer）必須正確表達；PST 若無法表達，就先切分路段並傳入 unlink 點。
  - W5 可立即進行 2 km／10 km（仍需 Geofabrik 下載核准）。

## PD-16 停止舊的 Week 4 R 系列執行者（2026-09-25 追加）

- 設計者選擇：停下，工作併入 Luna。
- R 系列停在 R53。它尚未 commit 的程式修改與 R40–R53 證據包，已由 Control Tower 原樣保存到分支 `wp/w4-r40-r53`（commit `19ed8d6`），**尚未審查**。
- Week 5 執行者把該分支當作延續項，逐項選擇性合併；與 W5 分支衝突時以 W5 計畫的結構為準。
- PST 只能留一份實作：以 `wp/w5-04-pst-runtime` 的 adapter 為主，runtime 放在 repo 外（PD-01）；R48 放進 repo 的 `runtimes/` 與 `pst_engine.py` 中有用的部分併入後，不另保留第二份。
- 主工作目錄只供 Control Tower 使用；所有執行者必須在自己的 git worktree 中工作。

## PD-17 區域 OSM 下載核准（2026-09-25 追加）

- 設計者核准 R48 提案中的單次下載，並一併核准裁切邊界檔，由 Week 5 執行者在 W5-4 執行：
  - `https://download.geofabrik.de/europe/netherlands/zuid-holland-260922.osm.pbf`：211,355,323 bytes，OSM 資料截至 2026-09-22T20:22:59Z，ODbL 1.0，需標註 © OpenStreetMap contributors。
  - 同一抽取檔的 `zuid-holland.poly`（裁切邊界，上限 1 MB），用於檢查 20 km 範圍是否超出省界。
- 上限：每個檔案 1 次 GET、不自動重試或續傳、不改用其他網址；PBF 回應上限 262,144,000 bytes、逾時 300 秒。HTTP 非 200、大小不符、跨主機重導、逾時或結果不明，一律停下並核對，不重送。
- 若核准時的檔案日期或大小已變，執行者必須停下，重新列出網址、日期、大小請設計者核准。
- 原始 bytes 與回應標頭存入新的第 2 級證據包，登錄為 DatasetSnapshot（屬分析輸入，PD-04 可寫入）。
- R 系列在 PD-16 之後仍產出 R54、R55 與前端修改；已由 Control Tower 經設計者核准原樣追加保存到 `wp/w4-r40-r53`（commit `10f0903`）。R54／R55 以 R51 為依據把 CP1 標為 PASS_SCOPED，依 PD-14 該狀態無效。

## PD-18 Week 4 收尾改由 AntiGravity 執行（2026-09-25 追加，調整 PD-16）

- 設計者表示：要一份把 Week 4 可收尾的都結束掉的完整 Prompt，先交給 AntiGravity 做。
- **分工：**
  - AntiGravity（Gemini 3.8 Flash）依 [Week 4 收尾計畫](../superpowers/plans/2026-09-25-week4-closeout-plan-zh.md) 負責：R40–R55 保存成果的審閱與合併、C3 分析持久化、六張 Syntax 圖層（含 PD-17 下載，以 `wp/w5-04-pst-runtime` 為起點）、PD-14 來源註記、C1 操作說明與核對、C5、C6、Week 4 驗收請求。
  - Luna 保留：W5-1 決策機制、Live AI（W5-AI）、測量工具、生成與編輯、W5 決策時段。Week 5 計畫中的 K1、K4、K5、K6 與 W5-3、W5-4 轉給 AntiGravity。
- **共用核心檔：** `models.py`、`store.py`、`api.py` 在 `wp/w5-01` 合併進 `main` 之後由 AntiGravity 擁有，直到 WC-2、WC-3 合併完成再交還 Luna。在此之前 Luna 不得修改這三個檔案。
- PD-17 的下載改由 AntiGravity 執行，條件不變。

## PD-19 核准新依賴 osmium（2026-09-25 追加）

- 設計者核准把 `osmium`（pyosmium，版本 >=3.7.0,<=4.0.2，BSD-2-Clause）安裝到專案 `.venv`，只用於離線讀取與裁切 PD-17 的區域 OSM 檔。
- 由 Week 4 收尾執行者加入 `pyproject.toml`，並記錄實際安裝版本、授權與來源（PyPI）。安裝只從 PyPI 下載該套件及其必要依賴；若會連帶安裝其他新依賴，先列出再裝。

## 仍未決定

- **權威 DB 快照是否入 Git（D10）**、**C1 是否寫入權威 DB**、**C2 來源註記是否寫入權威 ledger**。
