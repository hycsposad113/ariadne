# Week 7 reviewer 操作手冊

這份手冊給 Founder 或指揮官手動走一次。演練用 sqlite backup 的 DB 副本，以及臨時連接埠 API `8901`、Web `5301`。不要啟動或重啟 `8795`、`5195`、`8788`、`8789`、`9876`，也不要碰 Hermes `8787` 或 life-agent `8644`。正式 DB 只用 `mode=ro` 讀。不要建立 HumanDecision，不要讀 key 或 `.env`。

工作樹是 `Q5/w6-07-compare`。核心分支是 `wp/w7-integration`。Codex 的 `w6_checkpoint` `7910771` 已合併。不要改 `Q5/w6-08-editor`。

## 1. 準備副本

在 worktree 裡，用專案的 `.venv` Python 呼叫 `urban_design.week7.service.copy_authority_database`，來源是 `project/.urban_design_runtime/state.sqlite3`，目標是一個新檔。然後用 `tests.week7_support.seed_pair` 寫入工作區 `ws-w7`。這筆資料的標籤是 `FIXTURE_ONLY`：B2 的 FAR 是 2.2，證據卡是 `card-b2-sun`，驗證狀態是 `invalid`。

## 2. 啟動臨時服務

```bash
cd /Users/jackhsieh/Downloads/TUD/Q5/w6-07-compare
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python \
  scripts/run_workspace_server.py --host 127.0.0.1 --port 8901 --database /路徑/state-copy.sqlite3
```

另一個終端機：

```bash
cd /Users/jackhsieh/Downloads/TUD/Q5/w6-07-compare/web
VITE_API_BASE=http://127.0.0.1:8901 npx --no-install vite --host 127.0.0.1 --port 5301 --strictPort
```

瀏覽器打開：

`http://127.0.0.1:5301/?week7Workspace=ws-w7&week7Fork=branch-b2`

查詢參數只決定要問哪一個 workspace。revision 文字必須來自 `GET /api/v1/week7/workspaces/ws-w7/view`。服務沒有這筆資料時，畫面要顯示 `revision unavailable`，不可以自己編一個版本。

## 3. 你應該看到的版本鏈

頂端有一條深色列，六個面板共用同一個 `revision` 標籤。五個狀態分開寫成文字：geometry、human、run、freshness、evidence。過時時要看到 `STALE 結果已過時`，不能只靠顏色。旁邊要看到 `OFFLINE mock — not a live model reply`。這不是 live 模型回覆。

按 `Switch B1`，標籤變成 `revision rev-b1`，FAR 面板是 1.1。重新整理後仍是 `rev-b1`。再按 `Switch B2`，六個面板都回到 `rev-b2` 與 FAR 2.2，證據卡是 `card-b2-sun`。地圖、側欄、AI 與匯出不可以各看各的版本。頁尾要是 `Authority: READY`，StudyArea ID 來自已存在的研究區，`Workspace rev` 與目前 revision 相同。地圖上要看到這個 revision 的 footprint，文字是 `map revision <revision> feature <id>`。B1 與 B2 的 footprint 不同。

按證據卡按鈕，展開後要有 source、formula、unit、version、limits。這次種子的 limits 是 `FIXTURE_ONLY`。

直接呼叫 API 也不能繞過後端。幾何無效時，`POST /controls/run_analysis` 即使 body 帶 `allowed: true` 也要回 409。設計、約束、實驗的接受會回 `NEEDS_FOUNDER`。不要在這個畫面按 Record Review，那會走向 HumanDecision。

## 4. 八種操作

每一顆按鈕都會打到後端並把回應寫在 `week7-op-result`。做完後用 `mode=ro` 查副本，確認有列：

| 按鈕 | 畫面上要看到 | 副本裡要查到 |
|---|---|---|
| inspect | `forged_calculation: false` | `week7_operations.kind = inspect`，結果列數不變 |
| challenge | `target_revision` 是 `rev-b2` | contest 列綁在 `rev-b2` |
| modify | `grants_acceptance: false`，`human_status: not_reviewed` | `week7_drafts` 有草稿，HumanDecision 筆數不變 |
| rerun | `overwrote_baseline: false`，baseline 仍是 2.2 | `week7_runs` 新增一筆，原 `week7_results` 仍是 2.2 |
| compare | `comparable: false`，`not_comparable` 含 `radius_family` | 這次比較故意把 accessibility 和 syntax 放在一起，所以不可比 |
| fork | lineage 含 `B2@rev-b2` 與 `branch-b2` | `week7_forks.branch_id = branch-b2` |
| reject | `still_queryable: true` | 被拒的 `candidate-b0` 仍查得到 |
| override | 計算值前後都是 2.2，invalid 證據仍是 invalid | 只多了判斷與理由，沒有把無效證據改成有效 |

同一個已批准的 rerun 再送一次，要回到原來的 run，不再詢問。這條在 `tests/test_week7_contestability.py`。

## 5. 停在這裡

下面這些不是這次演練能關掉的，畫面或文件若把它們寫成 PASS，就是錯的：

- 合併 `main`、重啟正式服務、重跑五個正式方案、決策三。
- E1 plan 仍是草稿。不要批准。
- 天氣方法與正式 E2。Week 6 的正式 E2 沒有通過，這次也沒有新的真實 E2 通過。
- Live AI。沒有 Founder 的 key 之前，只許假 transport，畫面維持 OFFLINE。
- accessibility 400／800／1200 m 與 Syntax 800／2,000／10,000 m 是兩套半徑。compare 若混用，必須標成不可比。
- Syntax 800 m 的 readiness 仍是 `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`，2,000 與 10,000 m 是 `EXPLORATORY`，`formal_result` 是 false。出圖目錄裡的圖是 `FIXTURE_ONLY schematic`，不是那六張計算圖。

自動化腳本是 `web/e2e/week7_walkthrough.py`。它用已經安裝的 Google Chrome headless CDP，臨時 profile 在 `/private/tmp`。它不安裝 Playwright。連跑兩次時，revision、fork id 與出圖 SHA-256 要相同。Chrome 若根本開不起來，日誌會留下 `CHROME_START_FAILED`。開起來但 revision 列空白、頁尾停在 `Authority: LOADING`，或地圖沒有這個 revision 的 footprint，算產品失敗，不能當成環境問題放行。

## 6. 結束後核對

正式 DB 的 SHA-256 仍是 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`。把臨時 API 與 Vite 停掉。不要刪除 `artifacts/w7-*`。跨 provider 審查與 Founder 驗收都還是 PENDING。
