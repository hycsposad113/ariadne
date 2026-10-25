# G8　周邊 Space Syntax readiness

TASK: G8 Space Syntax 周邊、模式與 readiness 收尾
STATUS: DONE_ON_BRANCH
BRANCH/COMMIT: wp/w6-syntax-readiness（由 5c620de 切出；commit 見本檔入庫後的 git 記錄）
WORKTREE: /Users/jackhsieh/Downloads/TUD/Q5/w6-07-compare

這是執行者自檢，不是指揮官驗收，也不是 Founder 批准。

## 做了什麼

周邊句法回應現在帶每一層的 readiness、原因，以及已驗證的 manifest SHA-256。標籤綁定出貨 manifest `a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1`（`run-20261001T105231Z`，PST 3.3.1）：

| 模式 | 半徑 | readiness | formal_result |
| --- | --- | --- | --- |
| pedestrian | 800 m | `BLOCKED_BOUNDARY_STABILITY_UNASSESSED` | false |
| bicycle | 2 km | `EXPLORATORY` | false |
| motor_vehicle | 10 km | `EXPLORATORY` | false |

Site 階段色帶在 Walk / Bicycle / Car 旁邊顯示上述標籤，並顯示 manifest 前綴與「不是正式結果」。`App.tsx` 不再把 SidebarSyntax 的 fallback 寫成 `EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT`。地圖圖例在回應含 readiness 時顯示該狀態，不把 800 m 畫成單一的 EXPLORATORY 正式結果。

沒有下載。沒有改 8795／5195。沒有寫正式資料庫。沒有把 800 m 改成 PASS。路網政策與方法門檻仍是 Founder 的決定，所以 2 km 與 10 km 維持探索層。

## 800 m 邊界穩定性（只回報）

比較既有檔，沒有重跑 PST，也沒有新的 extract。

1. 步行 metric extract 只有 1500 m 一份。`runtime_benchmark_800m_6000m.json`（sha256 `01ed451d5ce64963c1803cce3d1372d3929b4c30cadd16c80d7d9444a7e5f365`）寫明 purpose 是 runtime scaling measurement only，沒有指標值，路網段數 49738。因此 1500 m 與 6000 m 的 800 m 指標差無法計算。
2. 同一 1500 m extract 的兩次周邊產出（`run-20261001T105212Z` 與 `run-20261001T105231Z`）各 6641 段，識別碼完全對上，NAIN 與 NACH 最大絕對差都是 0。這是同半徑重跑，不是第二個 extract 半徑。
3. Week 5 `syntax_800m_1500m.json`（sha256 `1309b6d9bc0a36265f5342549ddf20c5de58c2f21db6a750ffa75941768caa00`）基地內 481 段，readiness 已是 `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`。以 `pedestrian:` 加段識別碼對上 105231Z 周邊檔，481 段全部對上，指標差 0。仍是同一個 1500 m extract。
4. 105231Z 步行 6641 段裡，4674 段距基地超過可靠距離 700 m，`boundary_effect_risk` 為真。這是單一 extract 內的邊緣旗標，不是跨半徑穩定性通過。

結論：800 m 維持 `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`。這次回報不構成 PASS。

既有 2 km 比較（4000 m 對 6000 m，共同段 140，NAIN／NACH Spearman 皆 1.0，檔案 sha256 `600506eed48111e91c0a19cfb2b6aa46a68c16e82c7cafeaa04a6acd57176f7e`）與 10 km 比較（15000 m 對 20000 m，共同段 76，Spearman 皆 1.0，sha256 `425fad4aeef1ab07ceffaa4d9f4bf1a5912c4fc65da01e48a0f3cc398761ef01`）只當既有數字引用。G8 不把它們升成正式結果。

## 自我檢核

- [x] 每一層都有 readiness 和原因，並綁定 manifest hash。證據：`tests/test_syntax_context_api.py` 的 `test_shipped_manifest_readiness_stays_blocked_or_exploratory` 對三個模式打已出貨 router；UI 為 `#syntax-readiness-walk`、`#syntax-readiness-bike`、`#syntax-readiness-car` 與 `#syntax-context-manifest`。
- [x] 沒有新增下載；探索層和正式層在 UI 上分得出來。`formal_result` 固定 false，色帶寫「不是正式結果」。

## TESTS (fresh)

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_syntax_context_api.py` → 9 passed, 1 warning, 0.37s。警告是既有 Starlette deprecation。沒有放寬斷言。
- `web/node_modules/.bin/vitest run src/SyntaxContext.test.tsx` → 6 passed。

## ARTIFACTS

- manifest `run-20261001T105231Z/manifest.json` sha256 `a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1`，754 bytes。
- 步行／自行車／汽車模式檔 sha256：`5e0cd13dfdd33ebfc4f22a47c4426be06a47d875926c383257399bbd6adaa3e6`、`194e6d22a400c4563d08bef55ef59e2dc0494d00f3e2805167dd87f1c0f43a72`、`4a8b633ef37a54c858f3688b7be723a18d9d01b7470857801b0b22e8aa954dac`。
- 敏感度計算留在執行者 scratch `g8-sensitivity.json`，沒有入庫，也沒有寫進正式資料庫。

## DEVIATIONS

無流程偏離。800 m 沒有第二份 metric extract，所以敏感度只能報告「無法比較」，不能改標籤。

## STOP POINT / NEEDS

路網政策與方法門檻是否核准，由 Founder 決定。合併 `wp/w6-syntax-readiness` 要指揮官審查與 Founder 核准。這不是驗收。

NEXT: G10 `wp/w6-live-ai`（先在 `Q5/w6-12-e2` commit，再切天氣分支）。G4–G6 仍因 `Q5/w6-08-editor` 髒樹停住。
