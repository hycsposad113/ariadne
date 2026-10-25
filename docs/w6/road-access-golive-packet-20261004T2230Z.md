# 道路 r4 上線封包（給指揮官；Grok 未執行合併、重啟或正式生成）

UTC：2026-10-04T22:30Z。分支：`wp/w6-road-access`。Worktree：`/Users/jackhsieh/Downloads/TUD/Q5/w6-06-generator`。

狀態：**DONE_ON_BRANCH 準備完成，尚未上線。** 合併、重啟 8795／5195、寫入正式 DB、重新生成正式方案，都要 Founder 當次核准後由指揮官做。

## 要合併的 commit

從 `main`（本包開工時 `516bbaafa42522e809031f47df4cd35d4dc7e306`）到 `wp/w6-road-access` 的 tip。已固定的前置 commit：

- `4b1938eb6f9b6b6500898f07eec1f43aa1824691`：r4 之前的分支 HEAD。
- `24c5a6543fa45c6ecead4b50c41e823bbefebb9a`：r4 worker output snapshot（gpt-6.1-sol low，exit=0），由 Grok 原樣提交。
- 本封包所在的下一個 commit：Grok 加上 `ACCEPTED_TRADEOFF_FOUNDER_2026-10-04`，沒有改骨架幾何。合併前請用 `git log --oneline main..wp/w6-road-access` 核對 tip。

不要合併 `out/formal-dictionary/fifth-rehearsal-db/` 裡的彩排 DB 進正式 runtime。它只是離線重播的唯讀輸入。

## 合併後在 main 要跑的測試

```text
cd /Users/jackhsieh/Downloads/TUD/Q5/project
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_south_strip_collector.py tests/test_formal_dictionary_pipeline.py::test_formal_diversity_replay_and_land_far tests/test_formal_dictionary_pipeline.py::test_large_rd_coordinate_rotation_preserves_dictionary_semantics tests/test_formal_dictionary_pipeline.py::test_all_candidates_have_road_access tests/test_formal_workflow_service.py::test_job_runs_real_pipeline_and_reuses_proposed_ids
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider
```

第二條不要在 pty 下跑：`tests/test_m2a03_spatial_policy.py` 會卡在 `getpass`。已知失敗只應是 main 上既有的兩項（`test_site_proposal_rotterdam_v4` offline rebuild、`test_week4_repair_integrity`）。多出來的失敗就停，不要放寬斷言。

## DB 備份

正式庫開工時 SHA-256：`2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`。備份前再算一次；不一致就停。用 sqlite backup API，來源 `mode=ro`，不要覆蓋既有檔：

```text
cd /Users/jackhsieh/Downloads/TUD/Q5/project
.venv/bin/python - << 'PY'
import sqlite3
from pathlib import Path
src = Path(".urban_design_runtime/state.sqlite3")
dst = Path(".urban_design_runtime/backups/state-pre-road-r4-golive-<UTC>.sqlite3")
if dst.exists():
    raise SystemExit("refusing to overwrite")
dst.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True) as source:
    with sqlite3.connect(dst) as dest:
        source.backup(dest)
print(dst)
PY
```

## 重啟（照 OPERATIONS-LOG 交接快照 C 節；需 Founder 核准）

先把舊 log 改名保留。不要碰 8787、8644、8788、8789、9876。

```text
cd /Users/jackhsieh/Downloads/TUD/Q5/project
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 nohup .venv/bin/python scripts/run_workspace_server.py --host 127.0.0.1 --port 8795 --database .urban_design_runtime/state.sqlite3 --morphology-preview-root /Users/jackhsieh/Downloads/TUD/Q5/w6-dictionary-generator/out/dictionary-generator/run-01 --morphology-preview-manifest-sha256 14b2378ca16f79b84ce8fd60fbe6aa81ff11e7cccdec875034be5740e6b37452 --syntax-context-root /Users/jackhsieh/.local/share/urban-design-data/syntax-context/run-20261001T105231Z --syntax-context-manifest-sha256 a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1 > .urban_design_runtime/logs/api8795.log 2>&1 < /dev/null &
cd web && VITE_API_BASE=http://127.0.0.1:8795 nohup npx vite --host 127.0.0.1 --port 5195 --strictPort > ../.urban_design_runtime/logs/web5195.log 2>&1 < /dev/null &
```

## Generate 分頁重新生成

1. 確認服務已吃到合併後的 main。
2. 在 Generate 用既有正式流程重跑字典生成，seed 42，recipe `formal-dictionary-v6-south-strip-collector`。這會**追加**新的 PROPOSED 方案，不會改寫既有五筆。
3. 不要在這一步建立 HumanDecision。決策三仍等新方案上線後，由 Founder 在 Compare 分頁按「選定基準方案」。

離線 dry-run（彩排 DB，未寫正式庫）已跑兩次，候選 `result_hash` 相同。整份 `report.json` 的檔案 hash 不同，因為 stage 裡有 `created_at`；比對時用候選 `result_hash`。

| recipe | 預期 scenario id | result_hash | FAR | 開放空間 | 最高新建 m |
|---|---|---|---:|---:|---:|
| grid-mixed | `formal-dict-3da03eb0172d-grid-mixed-83f4f88fe9f2` | `sha256:83f4f88fe9f2017c076b20cd163aa7995112fb3ecee17796ff4624033156828a` | 0.757951 | 0.692642 | 17.5 |
| common-mixed | `formal-dict-3da03eb0172d-common-mixed-2b508e918481` | `sha256:2b508e918481c3121d7b685f56b5e5e8b898fbbd48c45c19a9b89c07323e221c` | 0.743333 | 0.686492 | 17.5 |
| spine-mixed | `formal-dict-3da03eb0172d-spine-mixed-bc0b62dce94d` | `sha256:bc0b62dce94d4732b5c5f706f2acb5722de88712f34e0428e264ff317c452c22` | 0.735016 | 0.731290 | 17.5 |
| grid-fine | `formal-dict-3da03eb0172d-grid-fine-fba35d228a25` | `sha256:fba35d228a25e8d98f728e4b54c677f162697fcf57b828d8888dbc3108f3c4e4` | 0.771730 | 0.680707 | 17.5 |
| common-compact | `formal-dict-3da03eb0172d-common-compact-b9825908f73b` | `sha256:b9825908f73bda976d81e3305355fdabbb0b4e31f44bf42a5c4addde03e8f811` | 0.765776 | 0.680197 | 14.0 |

分母是陸地面積 `183591.328035937` m²，標籤 `land_area`。五案 VALID、quality gate READY、三種拓樸、每案四種字典型、五區新建 GFA > 0、開放空間 ≥ 40%、新建高度 ≤ 20 m。common／spine 的南側集散道路接在路網上、對齊格網，並避開主開放空間、保留建物 3 m 退縮與水岸帶。grid 不加這條路。

`ACCEPTED_TRADEOFF_FOUNDER_2026-10-04`：fallback 巷道 201–242 m（common-compact 201.16、common-mixed 226.49、spine-mixed 242.49），道路長度相對 before 增加約 64–80%（64.38%、70.06%、79.58%），開放空間下降約 6.4 個百分點（6.35、6.47、6.54）。巷道精簡是之後的工作。

證據：

- `out/road-access-r4-final-20261004T222744Z-a/`
- `out/road-access-r4-final-20261004T222744Z-b/`
- `out/road-access-r4-final-comparison-20261004T222744Z/comparison.png` SHA-256 `0ef428e54bdeb5f1426eb7e1c3fae34bc8c25429d25435e4bc2a39cc3e380d93`
- 同目錄 `comparison.md` SHA-256 `6e2fd4d3db47179ddca7078504ebb304a276fc368d8c1211d241fb4214d90821`
- 同目錄 `audit.json`：status PASS；彩排 DB 前後 SHA-256 都是 `992ad023d26bbfeffce78ef0e7dd0054f123c3bc5819520ead58be648ff9bd18`

## 失敗時怎麼還原

1. 不要對正式庫做新的 import。若生成已寫入，用上面的備份檔換回，或保留新列、不要刪 ledger。
2. 服務若已重啟，停掉本輪啟動的 8795／5195 後，用合併前的 checkout 與備份庫，照同一組 nohup 指令拉起。不要動 8787 與 8644。
3. 分支還原只在 worktree 上開新 commit；不要 `git reset`、`git clean` 或改歷史。
