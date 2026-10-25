# Week 5 線 B：三模式路網、PST 重算與熱力圖成果案卷（PD-20 / PD-21）

**執行者：** AGY（Gemini 3.8 Flash）  
**審查者：** Claude（Commander）  
**決策者：** Jack（設計者）  
**工作分支：** `wp/w5-syntax-modes`（worktree: `Q5/w5-syntax-modes`）  
**依據文件：** `docs/superpowers/plans/2026-09-27-week5-closeout-plan-zh.md` 第 0、2、4 節  

---

## 1. 執行摘要

本案卷依據 2026-09-27 設計者於聊天室之最新指示，全面執行計畫第 4 節（線 B）：
1. **PD-20 三交通模式路網過濾與重切**：
   - 行人路網（800 m，外擴緩衝 1.5 km）：納入所有行人可通行路段；排除 autoweg、motorroad、封閉私人道路等。
   - 自行車路網（2 km，外擴緩衝 4 km 與 6 km）：嚴格落實荷蘭道路交通法規（RVV 1990），排除 autoweg（標誌 G3）、強制側邊自行車道（標誌 G11/G12a，`bicycle=use_sidepath` 或 `cycleway=separate/track`）、禁止腳踏車路段；納入專用自行車道、fietsstraat（`cyclestreet=yes`、`bicycle_road=yes`）與允許騎行之一般街道。
   - 汽車路網（10 km，外擴緩衝 15 km 與 20 km）：納入 motorway、trunk、primary、secondary、tertiary、residential、unclassified；排除所有步行/自行車專用道、service 中的私人車道（driveway）、停車通道（parking_aisle）、得來速（drive-through）與公車專用道（bus-only / bus_guideway）。
   - 缺標籤時依荷蘭預設交通法規（`dutch_default_traffic_rules_v1`）推定，並完整記錄各網路段數、推定比例與 highway 分類明細。
2. **PST 3.3.1 同步計算與穩定性檢驗**：
   - 行人網 800 m（1.5 km extract）：計算 NAIN 與 NACH。
   - 自行車網 2 km（4 km vs 6 km extract）：計算 NAIN 與 NACH，並執行半徑穩定性檢驗（Spearman 相關係數與 >5% 邊界敏感路段篩檢）。
   - 汽車網 10 km（15 km vs 20 km extract）：以分步計算（split mode）完成 NAIN 與 NACH，並執行 15 km vs 20 km 穩定性檢驗。
3. **PD-21 Syntax 熱力圖前端實現**：
   - 建立 `web/src/utils/syntaxHeatmap.ts` 工具，以五分位（quintiles: q20, q40, q60, q80）切分五個等級（Very Low, Low, Medium, High, Very High）。
   - 採用 depthmapX 經典冷至熱色階（深藍 `#1d4ed8` → 青綠 `#06b6d4` → 綠 `#10b981` → 琥珀橙 `#f59e0b` → 紅 `#dc2626`）。
   - 未計算或被排除路段以灰色虛線（`#64748b`, `[4, 4]`）明確標示，嚴禁塗成最冷深藍色。
   - 平台 2D 畫布（`Viewport2D.tsx`）與 Syntax 側欄（`SidebarSyntax.tsx`）全面接通五分位色階與圖例，並標示路網模式（行人 800m／自行車 2km／汽車 10km）。
   - 匯出 PNG（`mapFigure.ts`）支援圖例五級區間、路網模式、PST 分析方法與狀態說明。

---

## 2. 裁切與推計統計數據（PD-20 證據）

來源資料：`~/.local/share/urban-design-data/osm/zuid-holland-260922.osm.pbf`（SHA256: `71379de6fcb38b114ae2ee564cac99cfb2763b6cc3f6d87667c1079ea578401c`，大小: 211,355,323 bytes）。  
政策版本：`config/runtimes/syntax-network-policy-v2.json`。  
輸出路徑：`~/.local/share/urban-design-data/week5-syntax-modes/extracted/`。

| 模式 | 緩衝半徑 | 裁切線段數 | 偵測立體交叉點 (Unlinks) | 顯式標籤路段 | 荷蘭規則推定路段 | 推定比例 | 耗時 (秒) | Manifest 檔案 |
|---|---|---|---|---|---|---|---|---|
| **行人 (pedestrian)** | 1,500 m | 2,499 | 195 | 122 | 2,375 | 95.11% | 27.05s | `extraction-manifest_pedestrian_1500m.json` |
| **自行車 (bicycle)** | 4,000 m | 8,629 | 807 | 2,509 | 6,087 | 70.81% | 29.43s | `extraction-manifest_bicycle_4000m.json` |
| **自行車 (bicycle)** | 6,000 m | 19,491 | 1,589 | 5,431 | 13,965 | 72.00% | 28.21s | `extraction-manifest_bicycle_6000m.json` |
| **汽車 (motor_vehicle)** | 15,000 m | 62,201 | 5,928 | 386 | 61,475 | 99.38% | 32.65s | `extraction-manifest_motor_vehicle_15000m.json` |
| **汽車 (motor_vehicle)** | 20,000 m | 97,812 | 9,215 | 525 | 96,769 | 99.46% | 37.15s | `extraction-manifest_motor_vehicle_20000m.json` |

### 主要道路型態構成分析
- **行人 (1.5 km)**：footway 733、residential 705、service 260、tertiary 211、unclassified 161、steps 117、secondary 107、pedestrian 78、path 69、living_street 42、cycleway（允許步行）9。完全排除高速公路與封閉道路。
- **自行車 (4.0 km)**：residential 2955、cycleway 2152、service 2101、unclassified 663、tertiary 276、living_street 146、pedestrian 105、footway（允許騎車）98、secondary（無強制側邊車道）24。
- **汽車 (15.0 km)**：residential 23136、service（排除 driveway 等）10176、unclassified 7796、tertiary 6643、secondary 5509、living_street 2927、primary 2318、motorway_link 1502、motorway 1208、trunk 246 等。完全不含徒步區、自行車專用道與踏步。

---

## 3. PST 3.3.1 空間語法計算與穩定性報告

輸出目錄：`~/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/`  
候選資料集：`syntax_six_layer_candidate.json` (SHA256: `fde6d49b4f41135316d6b432b690697233c77f0b91c3df6f22363b5eef4b5900`)  
Manifest：`run-manifest.json` (SHA256: `a6ebf6c8c0ff08e4a4980f229e042b4b3a114c181a985f236e62eaa577d4ecdc`)  
區域狀態：`COMPUTED_STABLE`  
計算引擎：PST 3.3.1

### 六圖層清單與規格

| 圖層 ID | 交通模式 | 搜尋半徑 | 語法指標 | 計算路段數 | 準備狀態 (Data Readiness) | 耗時 (秒) |
|---|---|---|---|---|---|---|
| `syntax_local_800m_integration` | pedestrian | 800 m | NAIN (Angular Integration) | 481 | `BLOCKED_BOUNDARY_STABILITY_UNASSESSED` | 1.22s (總計) |
| `syntax_local_800m_choice` | pedestrian | 800 m | NACH (Angular Choice) | 481 | `BLOCKED_BOUNDARY_STABILITY_UNASSESSED` | (包含於上方) |
| `syntax_mid_2000m_integration` | bicycle (RVV) | 2,000 m | NAIN (Angular Integration) | 140 | `EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY` | 10.53s (6km) |
| `syntax_mid_2000m_choice` | bicycle (RVV) | 2,000 m | NACH (Angular Choice) | 140 | `EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY` | (包含於上方) |
| `syntax_regional_10000m_integration` | motor_vehicle | 10,000 m | NAIN (Angular Integration) | 76 | `EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY` | 181.83s (15k) / 421.72s (20k) |
| `syntax_regional_10000m_choice` | motor_vehicle | 10,000 m | NACH (Angular Choice) | 76 | `EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY` | 284.74s (15k) / 474.99s (20k) |

### 實際計算耗時明細 (Timings)
- **行人網 (800m on 1,500m extract)**：`1.2198s`
- **自行車網 (2,000m on 4,000m extract)**：`3.5348s`
- **自行車網 (2,000m on 6,000m extract)**：`10.5293s`
- **尺度擴展基準 (800m on 6,000m auxiliary)**：`6.0288s`
- **汽車網 (10,000m on 15,000m extract, 62,201 線段)**：
  - Angular Integration：`181.8303s` (~3.03 分鐘)
  - Angular Choice：`284.7358s` (~4.75 分鐘)
  - 合計：`466.5661s` (~7.78 分鐘)
- **汽車網 (10,000m on 20,000m extract, 97,812 線段)**：
  - Angular Integration：`421.7221s` (~7.03 分鐘)
  - Angular Choice：`474.9880s` (~7.92 分鐘)
  - 合計：`896.7101s` (~14.95 分鐘)

### 穩定性檢驗結果 (Stability Reports)

1. **自行車路網 (2,000m: 4,000m vs 6,000m 緩衝區)**
   - 檢驗基準：Spearman 相關係數 $\rho \ge 0.98$；路段值變化 $>5\%$ 標記為 `EDGE_AFFECTED`。
   - 共有路段數 (M4H StudyArea): 140
   - NAIN Spearman 相關係數：**1.0**（Pass）
   - NACH Spearman 相關係數：**1.0**（Pass）
   - 邊界受影響路段 (Edge Affected)：0 段 (0.0%)
   - 穩定性結論：**`PASS`**（通過）
   - 結果檔：`stability_2000m_4000m_vs_6000m.json` (SHA256: `600506eed48111e91c0a19cfb2b6aa46a68c16e82c7cafeaa04a6acd57176f7e`)

2. **汽車路網 (10,000m: 15,000m vs 20,000m 緩衝區)**
   - 檢驗基準：Spearman 相關係數 $\rho \ge 0.98$；路段值變化 $>5\%$ 標記為 `EDGE_AFFECTED`。
   - 共有路段數 (M4H StudyArea): 76
   - NAIN Spearman 相關係數：**1.0**（Pass）
   - NACH Spearman 相關係數：**1.0**（Pass）
   - 邊界受影響路段 (Edge Affected)：0 段 (0.0%)
   - 穩定性結論：**`PASS`**（通過）
   - 結果檔：`stability_10000m_15000m_vs_20000m.json` (SHA256: `425fad4aeef1ab07ceffaa4d9f4bf1a5912c4fc65da01e48a0f3cc398761ef01`)

### 產出檔案清單與 SHA-256 驗證表

| 檔案名稱 | 大小 (bytes) | SHA-256 雜湊值 |
|---|---|---|
| `run-manifest.json` | 5,924 | `a6ebf6c8c0ff08e4a4980f229e042b4b3a114c181a985f236e62eaa577d4ecdc` |
| `syntax_six_layer_candidate.json` | 165,791 | `fde6d49b4f41135316d6b432b690697233c77f0b91c3df6f22363b5eef4b5900` |
| `syntax_800m_1500m.json` | 57,785 | `1309b6d9bc0a36265f5342549ddf20c5de58c2f21db6a750ffa75941768caa00` |
| `syntax_2000m_4000m.json` | 20,600 | `92d5f1b4c6477f4570f087201dbab5d94d8fbd982ddb7766af3f1fd896ec227b` |
| `syntax_2000m_6000m.json` | 20,659 | `9561fcb77bed98aabd475d64e9d10a9e34640f7bf8862f4ebafc7d0c6d1738d3` |
| `syntax_10000m_15000m.json` | 13,601 | `71efeac4d1f9502568b372f3a618da2f5769c0cf69ca29b35ce28a27a4898056` |
| `syntax_10000m_20000m.json` | 13,914 | `ffdcd86fd1ed35f88c5bbce110591eb650b822387896ee8406b5ae868f304c46` |
| `stability_2000m_4000m_vs_6000m.json` | 643 | `600506eed48111e91c0a19cfb2b6aa46a68c16e82c7cafeaa04a6acd57176f7e` |
| `stability_10000m_15000m_vs_20000m.json` | 643 | `425fad4aeef1ab07ceffaa4d9f4bf1a5912c4fc65da01e48a0f3cc398761ef01` |
| `runtime_estimate_10km.json` | 1,361 | `054da5945f4808027cee38b75bf25144b73e076d87d5961fedff96959844ea20` |
| `runtime_benchmark_800m_6000m.json` | 257 | `01ed451d5ce64963c1803cce3d1372d3929b4c30cadd16c80d7d9444a7e5f365` |

---

## 4. Commander（Claude）權威資料庫持久化操作步驟

依據第 2 節共同規則，本執行者（AGY）不直接修改權威資料庫（`state.sqlite3`）。請 Commander 依下列步驟執行寫入：

### 步驟 1：備份權威資料庫
```bash
cp /Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3 \
   /Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3.backup-$(date +%Y%m%d%H%M%S)
```

### 步驟 2：驗證計算成果一致性
檢查 `run-manifest.json` 與 `syntax_six_layer_candidate.json`：
```bash
sha256sum /Users/jackhsieh/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01/syntax_six_layer_candidate.json
```

### 步驟 3：執行持久化寫入腳本
以 `--write-authority` 將六圖層寫入 `state.sqlite3`（狀態標為 EXPLORATORY）：
```bash
PYTHONPATH=src:/Users/jackhsieh/Downloads/TUD/Q5/project/.venv/lib/python3.12/site-packages \
/opt/homebrew/bin/python3.12 scripts/persist_analysis_results.py \
  --syntax-run-dir /Users/jackhsieh/.local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01 \
  --write-authority
```

### 步驟 4：確認狀態
確認權威 DB 包含新的 6 張 Syntax 分析圖層與對應 LedgerEvent。
