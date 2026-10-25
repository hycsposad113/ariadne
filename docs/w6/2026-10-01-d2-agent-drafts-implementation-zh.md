# D2 代理草稿入口實作與驗證（executor，2026-10-01）

範圍依 Founder D 節及本次任務；只在 `wp/w6-03-freeze` 實作。直接在本 session 執行，未委派、未呼叫 Live AI。此記錄不是 Claude 獨立審查或 Founder 驗收。

## API 與權限

`POST /api/v1/projects/{project_id}/constraint-sets` 新增：

- `actor_kind`：省略仍為 `HUMAN_UI`，另允許 `AGENT_AUTOMATION`；ledger actor 分別為 `human-ui`、`agent-automation`，保留 actor session。
- `id`、`idempotency_key`：可選。只有 key 時，以 project＋key 的 UUID5 產生穩定 ID；只有 ID 也可重送相同內容。key 在同一 project 不可另綁其他 ID。
- `notes`：可選文字。每條 Constraint 可填 `source_note`；FAR Constraint 必須明列 `denominator=land_area|exploration_design_area`。非 FAR 不接受 denominator。

相同 ID、key、actor_kind、完整原始草稿 payload 重送，回傳 immutable revision 1 的原始 receipt，不追加 ledger／版本；衝突回 409。即使後來由人工改變狀態，重送也不重設當前狀態。重送 actor session 可不同；ledger 保留第一次實際寫入的 session。API store lock 序列化建立及冪等檢查。

代理的非草稿建立、內含 active Constraint 或 HumanDecision source_refs 被拒絕；store update 拒絕代理核准／啟用／停用／更新 ConstraintSet；commit_batch 建立亦使用相同代理建立防護。HumanDecision API 維持 extra=forbid，不接受代理 actor_kind；代理請求在讀取決策密語前被拒絕。既有 HumanDecision store 防護保留。本次沒有在正式資料建立 HumanDecision。

## Digest 相容性

改前 canonical definition 包含 set 的 `id/project_id/version/allocation_policy`，以及 constraints 的 `id/name/value/unit/scope/enforcement`；排除 status/source_refs。

改後保留上述項目及 canonical JSON 排序、UTF-8、緊縮分隔、SHA-256 方法。額外加入非 null 的 `notes`，以及各 Constraint 的 `source_note/denominator`。空字串也會入 hash；null 與缺欄等價，不擅自補 land_area。因此舊 raw JSON 與經新模型補上 null 的舊資料仍算出完全相同的舊 digest；舊核准 hash 不被無故改寫。新欄位文字或分母的改動必定影響 hash。status/source_refs 仍不影響 hash，人工 activation 不改決策內容 hash。

模型保留缺分母資料的讀取能力，API GET 不補分母；前端標「未指定（舊資料）」。新草稿 service 強制 FAR 分母；舊資料的既有核准／啟用相容路徑未強加新欄位，也未覆寫歷史。

本次僅儲存並確認分母，沒有更改生成預算或核准報告面積計算；兩者統一為陸地分母仍依 D 節另派工。

## D2 腳本及 UI

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/prepare_d2_drafts.py
# 以下僅供 Commander 在已核對的 DB 副本 API 彩排，不在此 session 執行：
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/prepare_d2_drafts.py --api-base <COPY_API_BASE>
```

固定 IDs：`constraint-set-d2-a-20261001`、`constraint-set-d2-b-20261001`；固定 key 分別 `d2-a-20261001-v1`、`d2-b-20261001-v1`。

A：FAR 0.80、建蔽率 0.35、高度 20 m；B：2.00、0.50、40 m；兩套首層及標準層均 3.5 m、旋轉步進 15°。來源註記分別保留 FOUNDER_STATED、PORTFOLIO_P24_SECTION、ASSUMED 及理由。notes 記 ≥40% 陸地開放空間偏好、15 m 水岸帶沿用 D1、五區偏好不設分區 FAR。未填 allocation_policy，避免將未決的 priority 規則加入 D2；若副本分區重疊，既有 gate 會拒絕建立，需先交 Founder 決定分配規則。

道路 scope 精確對應既有 `_approved_road_width_scope` 的 highway：primary→`road:primary` 14 m、secondary→`road:secondary` 10 m、local→`road:residential` 6 m。local 轉 residential 是明列的 ASSUMED 對應；不自動匹配 tertiary/service/unclassified/其他 highway。存在三種 width 時，未匹配 highway 仍由既有流程拒絕，不默認 6 m。

不給 api-base 只印 JSON。HTTP 模式只 POST 草稿、不提交 decisions、不啟用；任一 HTTP／連線／receipt 錯誤即停止，無重試（A 可能已成功，需以固定 ID／ledger 收據核對後再人工決定）。測試 HTTP 錯誤皆由 MockTransport 產生，無實際 401、付款或額度事件。

ConstraintSetPanel 可輸入上述 ID 載入草稿，顯示 server 值、notes/source_note/分母；手動 FAR 預設 land_area 且可選 EDA。核准對話框顯示各限制、来源及分母，仍綁定原 server digest；en／zh-TW 測試皆涵蓋。

## 驗證、重跑與保留項

實際結果及 commit SHA 見 executor 最終回報。完整 pytest 範圍包括 constraint sets、D2 script、generation_context、design_brief、approved_generation、store、store_thread_safety、decision_binding。前端執行完整 vitest 及兩份 TypeScript config／Vite production build。

本次重跑：

1. 首次 Python 36 項中 1 項失敗：PayloadError 是 ValueError 子類，API 先捕捉 ValueError 導致衝突回 422；調整此 endpoint 捕捉順序後重跑。
2. `npm --prefix web run test` 因 node_modules/.vite-temp EPERM 失敗。
3. runner 加 `--cacheDir /private/tmp/w6-03-vitest-cache` 被 Vitest 判定未知 option；改用 `--configLoader runner` 即可，無修改設定檔。
4. 完整 vitest 首次 runner 193 pass／3 fail：新增中文標籤 ID 及來源 DOM 字串比對；修正為「條件集編號」及獨立來源 span，重跑 196 pass。
5. `npm --prefix web run build` 因 TypeScript node_modules/.tmp tsbuildinfo EPERM 失敗；CLI 指定 `/private/tmp` 的 tsBuildInfoFile，兩份 config 編譯通過。
6. `npm --prefix web exec -- vite build ...` 在 repo root 尋找 index.html 失敗；改在 web cwd 執行後 production build 通過。输出 `/private/tmp/w6-03-build-20261001-success`，未清空外部 outDir；保留 chunk size 警告。

未啟動伺服器，未接觸正式 DB、EPW、憑證、token 或 Keychain。既有測試使用自建 fixture DB；既有人工決策回歸測試使用自己的測試 fixture，不操作正式決策。

未刪除檔案／目錄，無 reset/clean/rebase/push。未進行清理；保留 `/private/tmp` 編譯快取與 build 產物。初始既有未追蹤 `.venv` 保留，不納入 commit。

待 Commander 在 DB 副本彩排、Claude cross-provider review、Founder 確認／啟用；這些均不在 executor 自行接受範圍。

### 最終新鮮結果

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_constraint_set.py tests/test_constraint_set_drafts.py tests/test_prepare_d2_drafts.py tests/test_generation_context.py tests/test_design_brief.py tests/test_approved_generation.py tests/test_store.py tests/test_store_thread_safety.py tests/test_decision_binding.py
# 82 passed, 6 warnings in 7.40s；exit 0（警告為既有 Starlette deprecation）
npm --prefix web run test -- --configLoader runner
# 32 files / 196 tests passed；exit 0
web/node_modules/.bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-03-app.tsbuildinfo
web/node_modules/.bin/tsc -p web/tsconfig.node.json --tsBuildInfoFile /private/tmp/w6-03-node.tsbuildinfo
# 兩份 TypeScript config exit 0
# cwd 為指定 worktree 的 web：
npm exec -- vite build --configLoader runner --outDir /private/tmp/w6-03-build-20261001-success
# 1925 modules transformed, built in 299ms；exit 0
```

追加測試及修正後重跑 Python 81／82 項，皆通過；未重送任何 live request。最終新增案例包含原始 receipt 在狀態變更後的重送、批次繞過拒絕、legacy API 讀取及 store 層 FAR 必填。

`git diff --check` 通過。僅嘗試一次 `git add`（13 個明列檔案，不包含 .venv），被 sandbox 拒絕建立 `/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-03-freeze/index.lock`（Operation not permitted）。沒有 stage 成功，沒有執行 commit，無新 commit SHA；未重試或繞過權限。工作樹修改完整保留，供 Commander stage／commit。
