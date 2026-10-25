# W8 凍結清單與環境重建驗證指南

本文件說明如何運用 `scripts/verify_w8_freeze.py` 驗證與重建 Rotterdam M4H 都市設計環境，確保 W8 報告所引用的資料集、核心演算法、空間語法與微氣候模擬、模型設定及方案成果完全一致，無任何未預期的漂移（Drift）。

---

## 1. 核心原則與驗證架構

依據專案憲章核心原則：
> **LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.**

所有分析指標與方案結果皆由決定性專業工具（Deterministic Tools）產出，任何環境或程式碼漂移均會破壞可重算性與證據鏈（Evidence Framework）。因此，本系統透過數位簽章（SHA-256）建立完整的凍結清單（`docs/w8/freeze-manifest.json`），並提供自動化驗證工具。

### 驗證工具運作模式
`scripts/verify_w8_freeze.py` 提供兩種操作模式：
1. **清單收集寫入模式 (`--write`)**：
   自動掃描並以串流（Streaming Chunk）計算大檔案（如 211MB 之 OSM PBF、數十萬點之空間語法 GeoJSON）之 SHA-256 與大小，彙整至清單檔案。
2. **防漂移檢查模式 (`--check`)**：
   即時重算本機所有對應項目，逐項比對 SHA-256、檔案大小與執行期狀態，輸出清晰之 `PASS / DRIFT / MISSING` 檢核表。**若有任一項目發生 DRIFT 或 MISSING，立即以狀態碼 1 (exit 1) 終止**。

---

## 2. 凍結清單涵蓋項目 (`freeze-manifest.json`)

清單中每個項目皆記錄 `category`、`path`、`size_bytes`、`sha256` 與繁體中文 `description`：

| 類別 (Category) | 涵蓋範疇與檔案說明 | 雜湊計算方式 |
|---|---|---|
| **資料集 (`dataset`)** | • `~/.local/share/urban-design-data/context/`：周邊建物、綠地、水系、道路及 study-area-v5 範圍。<br>• `~/.local/share/urban-design-data/syntax-context/run-20261001T105231Z/`：自行車、行人、機動車空間語法背景圖層。<br>• `~/.local/share/urban-design-data/osm/zuid-holland-260922.osm.pbf`：荷蘭南荷蘭省區域路網原始二進位檔 (211MB)。<br>• `~/.local/share/urban-design-data/3dbag/`：3D BAG 荷蘭建物高度、瓦片索引與 WFS 定義檔。<br>• `artifacts/net2/water/`：Net2 局部水系與覆蓋率成果 GeoJSON (EPSG:28992)。 | 1MB 串流 SHA-256，支援超大檔案。 |
| **方法與知識 (`knowledge`, `code_src`, `code_script`)** | • `knowledge/v2/`：都市設計知識庫所有 JSON 規則（共 2,026 檔）。<br>• `src/urban_design/`：所有核心 Python 模組（共 137 檔）。<br>• `scripts/`：維運、分析、生成與報告腳本（共 118 個 `.py` 與 1 個 `.cjs`）。 | 知識庫採相對路徑排序後串流合併雜湊並記錄檔案總數；程式碼逐檔計算 SHA-256。 |
| **方案與結果 (`proposal`)** | • `artifacts/net2/round-3/plans/*-plan.json`：Net2 第三輪四大方案 (`closed_block_extension`, `courtyard_islands`, `harbour_grain`, `landscape_figure`)。<br>• `artifacts/fab1/run-6/*-plan.json`：Fab1 第六輪基準方案。 | 逐檔計算 SHA-256 與位元組大小。 |
| **依賴與鎖定 (`dependency`)** | • `dependency:pip_freeze`：`.venv` Python 虛擬環境套件清單。<br>• `web/package-lock.json`：前端 npm 依賴鎖定檔。 | 排序後之 pip freeze 文本雜湊；package-lock.json 串流雜湊。 |
| **執行期 (`runtime`)** | • Python `3.12.13`<br>• Node.js `v22.22.3`<br>• PST (Place Syntax Tool) `3.3.1`<br>• Radiance `6.0.2` (2026-02-02 LBNL)<br>• QGIS LTR `/Applications/QGIS-LTR.app` | 記錄版本字串雜湊與存在狀態。 |
| **模型與 Prompt (`model_prompt`)** | • `config/model-providers.json`：模型配置與路由。<br>• `docs/prompts/*.md`：Live AI Prompt 範本文件。<br>• `docs/w6/live-ai-acceptance-packet-20261005T0000Z.md`：驗收認證。 | 檔案 SHA-256；**嚴格排除並禁止讀取任何 API 密鑰或 `.env` 檔案**。 |
| **版本控制 (`git`)** | • Git HEAD Commit Hash (`git rev-parse HEAD`)<br>• 當前分支名稱<br>• `git status --porcelain` 變更與未追蹤摘要 | SHA-256 記錄 HEAD commit 與分支。 |

---

## 3. 環境重建步驟指南 (Reconstruction Guide)

若需在全新的機器或環境中重建完全相同的都市設計運算環境，請遵循以下步驟：

### 3.1 取得原始碼與切換分支
```bash
git clone <repository_url> w6-07-compare
cd w6-07-compare
git checkout wp/dl-quickfix
```

### 3.2 建立 Python 3.12.13 虛擬環境並安裝鎖定依賴
專案依賴高度精確之 Ladybug Tools、Honeybee 及幾何處理套件，必須採用 Python 3.12.13：
```bash
# 1. 建立虛擬環境
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 依鎖定檔安裝精確版本
pip install -r requirements.lock

# 3. 安裝本專案為可編輯模式
pip install -e .
```

### 3.3 建置 Web 前端環境
前端視覺化介面採用 Node.js 22：
```bash
# 前往 web 目錄並依照 package-lock.json 安裝
npm --prefix web ci

# 驗證前端建置與測試
npm --prefix web run test
npm --prefix web run build
```

### 3.4 資料集目錄佈署 (`~/.local/share/urban-design-data/`)
都市設計大型地理資料集不置於 Git 倉庫內，統一存放在使用者家目錄下之標準路徑：
```
~/.local/share/urban-design-data/
├── 3dbag/
│   ├── height-table-v2025.09.03-study-area-v5-buffer500m.json
│   ├── tile_index-v2025.09.03.fgb
│   ├── tile-8-296-512-v2025.09.03.gpkg.gz
│   ├── tile-9-304-512-v2025.09.03.gpkg.gz
│   ├── tile-9-304-516-v2025.09.03.gpkg.gz
│   └── wfs-capabilities.xml, *.xsd, *.geojson ...
├── context/
│   ├── manifest.json
│   └── context-20260927T153054Z/
│       ├── buildings.geojson
│       ├── green.geojson
│       ├── roads.geojson
│       ├── water.geojson
│       ├── study-area-v5.geojson
│       └── manifest.json
├── osm/
│   └── zuid-holland-260922.osm.pbf
└── syntax-context/
    └── run-20261001T105231Z/
        ├── manifest.json
        ├── syntax_context_bicycle.json
        ├── syntax_context_motor_vehicle.json
        └── syntax_context_pedestrian.json
```
> [!NOTE]
> 局部水系與覆蓋率成果資料集則納入專案目錄中，路徑為 `artifacts/net2/water/`。

---

## 4. 外部 Runtime 說明（僅記錄版本，未封裝於 Repository）

下列三項專業外部運算引擎因平台二進位檔案巨大、授權或硬體架構限制，**僅在清單中記錄其版本與路徑，未直接封裝於 Git Repository 中**：

### 4.1 QGIS LTR (3.40.5-Bratislava)
- **路徑**：`/Applications/QGIS-LTR.app`
- **架構**：macOS `x86_64`（透過 Rosetta 2 執行）或 `arm64` 原生。
- **用途**：提供專業 GIS 桌面操作與圖層算圖。後端透過 QGIS MCP Server (埠 9876) 或 `qgis_process` CLI 提供確定性空間分析。
- **未封裝原因**：完整 QGIS 應用程式體積超過 2GB，且包含專屬動態函式庫與 Qt 框架，應由系統層級安裝。

### 4.2 Radiance 6.0.2 (`2026-02-02 LBNL 6.0.c1700d56cc`)
- **路徑**：`~/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/`
- **架構**：macOS `arm64`。
- **用途**：Honeybee 日照、天空視域（SVF）及累積日射量模擬。
- **環境變數要求**：
  ```bash
  export RAYPATH="$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib"
  export PATH="$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin:$PATH"
  ```
- **版本驗證**：`rtrace -version` 應輸出 `RADIANCE 6.0.2 2026-02-02 LBNL (6.0.c1700d56cc)`。
- **未封裝原因**：為編譯完成之 C 語言原生二進位執行檔套件，不適宜存入原始碼版本控制。

### 4.3 PST (Place Syntax Tool) 3.3.1
- **路徑**：`~/.local/share/urban-design-runtimes/pstalgo-3.3.1/`
- **核心組件**：`bin/libpstalgo.dylib` 與 `python/pstalgo`。
- **用途**：執行軸線分析（Axial Map）、線段整合度（Integration）與穿越度（Choice）計算。
- **公式版本**：`pstalgo-3.3.1-walking-radius-v1`。
- **未封裝原因**：PST 演算法引擎由 KTH / Chalmers 開發，為特定平台編譯之 C++ 動態連結庫與 Python 介接包，依專案慣例置於 `~/.local/share/urban-design-runtimes/`。

---

## 5. 驗證指令與使用方法 (CLI Operations)

### 執行環境設定
在執行任何驗證指令前，請設定環境變數並指定專案虛擬環境：
```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
VENV_PY="/Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python"
```

### 5.1 重新收集並寫入凍結清單 (`--write`)
```bash
$VENV_PY scripts/verify_w8_freeze.py --write docs/w8/freeze-manifest.json
```
**預期輸出**：
```text
[*] 正在收集並計算 W8 凍結清單 SHA-256 (儲存至: .../docs/w8/freeze-manifest.json)...
[+] 凍結清單產生成功！共記錄 360 個項目。
```

### 5.2 執行防漂移重算比對 (`--check`)
```bash
$VENV_PY scripts/verify_w8_freeze.py --check docs/w8/freeze-manifest.json
```
**預期輸出**：
```text
[*] 正在重算並驗證 W8 凍結清單 (來源: .../docs/w8/freeze-manifest.json)...
=========================================================================================================
狀態 (Status) | 類別 (Category) | 大小 (Size)    | 路徑 / 項目名稱 (Path / Item)            | 說明
---------------------------------------------------------------------------------------------------------
PASS      | dataset        | 5,747 B        | ...urban-design-data/context/manifest.json | Context 空間背景圖層: manifest.json
PASS      | dataset        | 211,355,323 B  | .../osm/zuid-holland-260922.osm.pbf        | Zuid-Holland 區域 OSM PBF 原始路網資..
PASS      | knowledge      | 7,315,335 B    | knowledge/v2                               | 知識庫 v2 全體 JSON 規則合併雜湊 (共 2..
PASS      | code_src       | 14,477 B       | ...rban_design/generation/fabric_net2.py   | 都市設計核心模組: generation/fabric_..
PASS      | proposal       | 600,994 B      | ...lans/closed_block_extension-plan.json   | Net2 Round-3 設計方案成果: closed_..
PASS      | dependency     | 64 B           | dependency:pip_freeze                      | Python 虛擬環境套件清單 (pip freeze,..
PASS      | runtime        | 47 B           | runtime:radiance                           | Radiance 日照模擬版本: RADIANCE 6...
PASS      | model_prompt   | 3,123 B        | config/model-providers.json                | Live AI 模型與 Provider 路由設定 (不..
PASS      | git            | 40 B           | git:head                                   | Git HEAD Commit: 8c2e2009081..
=========================================================================================================
【W8 凍結驗證結果摘要】
  總檢核項目數 : 360
  通過 (PASS)   : 360
  漂移 (DRIFT)  : 0
  缺失 (MISSING): 0
  整體判定結果 : [PASS] 全數吻合，未偵測到任何資料、程式、模型設定或依賴漂移！
=========================================================================================================
```
- 若所有項目一致，結束狀態碼為 `0`。
- 若任何檔案被篡改或遺失，狀態欄將顯示 `DRIFT` 或 `MISSING`，標示詳細預期／實際差異，並以狀態碼 `1` 退出。

---

## 6. 自動化測試驗證 (Automated Pytest)

專案包含針對凍結與比對邏輯的最小自動化回歸測試：
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
$VENV_PY -m pytest tests/test_verify_w8_freeze.py -v
```

### 測試案例說明：
1. **`test_verify_w8_freeze_workflow`**：
   - 建立獨立暫存目錄（`tmp_path`）與模擬資料。
   - 執行 `--write` 生成暫存清單，確認結構與項目數。
   - 執行 `--check` 驗證首次檢查為 `PASS` (exit 0)。
   - 故意修改單一檔案內容，執行 `--check` 確認精準偵測到 `DRIFT` 並以 exit 1 終止。
   - 刪除該檔案，執行 `--check` 確認精準偵測到 `MISSING` 並以 exit 1 終止。
2. **`test_verify_manifest_programmatic`**：
   - 驗證核心函式 `verify_manifest` 在純 Python 呼叫下的判定與計數準確性。

---

## 7. 隱私與安全防護聲明

依據專案資安與授權準則：
- **嚴格禁止存取密鑰**：清單生成與檢查流程絕不讀取、剖析或輸出任何 `.env` 檔案、Keychain 密碼或系統憑證。
- **公開模型定義**：`model_prompt` 類別僅記錄官方核准之模型名稱（如 `gpt-4o`、`gpt-6-luna`）與 Prompt 模板結構，確保架構公開透明且無機密外洩風險。
