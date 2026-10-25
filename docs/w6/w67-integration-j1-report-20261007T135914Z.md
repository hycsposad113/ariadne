# J1：W6/W7 整合 guard 隔離與全套回歸

- task_id：`j1-w67-guard-regression`
- 執行者：OpenAI / `gpt-6.1-sol` / low。由使用者明確指定此 bounded integration regression 任務；未委派、未切換或降級模型。
- 指揮官：Claude（2026-10-07）；獨立審查及接受仍由指揮官／Founder 執行。
- worktree：`/Users/jackhsieh/Downloads/TUD/Q5/w6-07-compare`
- 分支：`wp/w67-integration`；開始及結束 HEAD：`567a1fa52db5de1dfb119d21eaf321adc7ac61ce`。
- 報告 UTC：`20261007T135914Z`（`date -u`）。

## 結論與界線

**guard 隔離修正有紅→綠證據；完整回歸已跑完，但整體狀態 INCOMPLETE。** 完整 pytest 有兩項未通過，沒有把已知失敗豁免成 PASS；5 個既有 skip 仍代表未執行的測試。未新增 skip、deselect、mock PASS、門檻或斷言放寬。W6/W7、renderer、批准解析、release 均不因本報告獲得接受。

本次唯一 production 問題修正是測試 guard 的作用範圍，沒有 production code 修改。剩餘整合 guard 回歸：0；完整 pytest 未解失敗：2。前端首次測試另有 1 項既有競態，完整重跑成功但競態未修。

## 讀取及前置核對

已讀 AGENTS.md、README.md、全域 AGENTS-commander.md、System Architecture、Evaluation Framework、COORDINATION.md，以及指定的 commander handoff。已讀事件 `20261007T130051Z-b3441a23828e46c9bba719be44e61a80.json`（task_id `claude-takeover-20261007`），確認批准規則已回答；**本 J1 未修改批准解析邏輯**，保留給 J2。現次明確的模型指派優先於較早交接中的模型路由文字。

開始時只有既有未追蹤 `.venv`；未操作它。正式 DB 在 `2026-10-07T13:21:10Z` 開工 SHA-256：

`2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`

結束核對同值，見 `authority-after.sha256` 與 `final-verification-utc.txt`。新增測試僅以 SQLite `mode=ro` 打開正式 DB，再以 backup API 複製至 pytest 臨時 DB，後續 quick_check 在副本執行。未讀取／產生正式密語、key、.env 或 Keychain；未建立正式 HumanDecision。

## 根因與最小修正

`tests.week7_support` 由 W7 測試的 `pytest_plugins` 註冊為 session-wide plugin；原 guard 是 autouse fixture，導致 W6 測試也重新啟用 guard。這是 fixture 可見性／啟用範圍問題，不是 monkeypatch teardown 沒有還原。

`tests/week7_support.py` 新增 autouse `week7_database_guard_scope(request)`，只對檔名 `test_week7_*.py` 呼叫 `request.getfixturevalue("no_canonical_main_database")`；原 guard 改為普通 function-scoped fixture。原 canonical DB、`-wal`、`-shm` 檢查，URI 解碼、SQLite、Path.open、builtins.open、io.open 攔截，以及 monkeypatch teardown 全部保留。W7 自動保護不變，也可明確要求 guard fixture。

新增 `tests/test_database_guard_isolation.py`：刻意載入相同 plugin，但作為非 W7 測試，以唯讀正式 DB backup 至臨時副本，驗證 quick_check。它在修正前 `1 failed`，修正後通過；另完整 W7 測試後接這個測試 `64 passed`，驗證 W7 執行後不污染非 W7。既有 W7 URI／file-read 拒絕測試也通過。

來源 SHA-256：

- `tests/week7_support.py`：`b58ed81df5096dc0977873c0bbc59c62d754736f3a32430ae9d21403f5e7e880`
- `tests/test_database_guard_isolation.py`：`2a53e091bdfd04232876ca980fa72e6620b001323fde9aa10c585eb6de168e21`

## 紅→綠與全部失敗分類

### 整合造成的 guard 回歸：已最小修正

修正前下列 7 個 errors 全為 `canonical main DB access forbidden`；修正後相同三模組加新增隔離測試共 `20 passed`。逐項皆由 `reproduction-red.log` → `focused-green.log` 佐證：

1. `tests/test_week6_site_analysis_replay.py::test_legacy_normalization_preserves_results_and_stabilizes`
2. `tests/test_week6_d1_workspace_binding.py::test_d1_v8_workspace_geometry_binds_active_study_area`
3. `tests/test_week6_d1_workspace_binding.py::test_d1_workspace_drift_fails_closed[patch0]`
4. `tests/test_week6_d1_workspace_binding.py::test_d1_workspace_drift_fails_closed[patch1]`
5. `tests/test_week6_d1_workspace_binding.py::test_d1_workspace_drift_fails_closed[patch2]`
6. `tests/test_week6_d1_workspace_binding.py::test_d1_workspace_drift_fails_closed[patch3]`
7. `tests/test_week6_d1_workspace_binding.py::test_no_d1_decision_never_passes`

新增非 W7 測試的預期紅燈亦屬同根因，並非新增 production 失敗。進度事件把此項寫成「1 error」是分類筆誤；實際 `isolation-red.log` 為 **1 failed**，本報告及 handoff 更正。

### 完整 pytest 未通過項：逐項分類

| Node | 分類 | fresh 證據與處理 |
|---|---|---|
| `tests/test_m2a03_spatial_policy.py::test_piped_decision_key_stays_on_stdin_when_dev_tty_exists` | 已知環境性 | 子程序開啟 `/dev/tty` 得 `PermissionError: [Errno 1] Operation not permitted`，`test_m2a03_spatial_policy.py:150`；未繞過沙箱、未修改測試。 |
| `tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema` | 已知舊失敗 | PNG bytes 比對於 index 66 不同，`test_site_proposal_rotterdam_v4.py:224`；保留歷史 PNG 及 strict assertion，未放寬。 |

完整原始 traceback 存於 `pytest-full.log`。沒有其他 FAIL／ERROR；`outcome-inventory.json` 記錄 2071 個已收集 node 的 outcome 計數與全部 skip。

### 前端首次失敗：既有非同步測試競態

`src/components/AriadnePanel.test.tsx > AriadnePanel > renders OFFLINE, LIVE, BLOCKED, and OUTCOME_UNKNOWN as distinct labels` 首次全組為 `expected 'Offline' to contain 'Outcome unknown'`，行 293。測試 `findByTestId` 只等待初始已存在 badge；component 初始狀態是 OFFLINE，fetch/json 完成後才更新。這是未等待最終狀態的既有測試競態：該測試及 component 與整合前 W7 commit `2f57f13` 完全相同，`ariadne-parent-diff.txt` 為空；單檔 `11 passed`，無改碼完整重跑 `310 passed`。分類為既有失敗／flaky，非此次整合新增程式回歸；遵守 J1 修改範圍，未修舊測試或 production 邏輯。首次失敗不被後續成功抹除。

曾在 commentary 誤把記錄退出碼的 wrapper 成功當成前端测试成功；隨即核對實際 `web-test-exit.txt=1` 並更正。本報告依子命令退出碼與原始結果。

## Fresh 執行與證據 SHA-256

完整 pytest UTC：`2026-10-07T13:24:15Z` → `2026-10-07T13:54:53Z`；pytest 計時 `1834.25s`，退出 `1`。未指定 node、未排除任何測試：

```sh
Q5_READONLY_FIXTURE_ROOT=/Users/jackhsieh/Downloads/TUD/Q5/project PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/pytest -q -p no:cacheprovider
npm --prefix web run test
npm --prefix web run lint
# cwd: web
./node_modules/.bin/tsc -b --noEmit
```

完整 pytest 以 `nohup sh artifacts/j1-w67-guard-regression/run-pytest.sh` 在可追蹤、非 tty exec session `87161` 執行；session 完成並讀取實際退出碼收據。第一次使用 shell `&` 的背景啟動只有開始時間，沒有输出／退出碼；`ps`、`pgrep` 被沙箱禁止，zsh 另回報 `nice(5)` 拒絕。該次記為 OUTCOME_UNKNOWN 啟動，不算完成，空日誌及開始時間保留。第二次記錄是實際完成並可驗證的 fresh suite。

| 驗證 | 實際結果 | 存在的證據檔 | SHA-256 |
|---|---|---|---|
| 原重現（紅） | 12 passed、7 errors | `artifacts/j1-w67-guard-regression/reproduction-red.log` | `1f5741330b4d11c1d12496037e13381bf8ba5914782b3ed87eda7a65b9639b87` |
| 新增隔離測試（紅） | 1 failed | `artifacts/j1-w67-guard-regression/isolation-red.log` | `a7042630cb9b7d1f387f2821698e263c4182210eac84c85e82556d8233692122` |
| 原重現＋新增隔離測試（綠） | 20 passed、1 warning | `artifacts/j1-w67-guard-regression/focused-green.log` | `36bd85c6b2f36427ee9adc9bd412914361e620c691534936c080a6f9ad24ac0e` |
| 所有 W7 後接非 W7（綠） | 64 passed、2 warnings | `artifacts/j1-w67-guard-regression/week7-then-isolation-green.log` | `7445669e2f413e0ceab62095194b41bea5992b66d4a43b2f90824514ee20368c` |
| 完整 pytest | 2064 passed、2 failed、5 skipped、14 warnings；exit 1 | `artifacts/j1-w67-guard-regression/pytest-full.log` | `9ea484d7d2a8d945a0df5bea6a1f39e4787475cd2b3f0c5c17431fbe12976802` |
| 前端首次完整測試 | 309 passed、1 failed；exit 1 | `artifacts/j1-w67-guard-regression/web-test.log` | `e34ac88b281c243120bd5fe25d101ec6c89c36f4a34116ae0d614e0848375eee` |
| Ariadne 單檔重跑 | 11 passed；exit 0 | `artifacts/j1-w67-guard-regression/ariadne-focused.log` | `167b3408fd42b41a745dbdadf5b9ea2973bcfab76cd41f18eb3d0e9bd7c8973a` |
| 前端完整重跑 | 310 passed、51 files；exit 0 | `artifacts/j1-w67-guard-regression/web-test-rerun.log` | `197f2119abc7fe87bb140cbda0c9c27ebd2a20671f46f70950d9eee345fbb8de` |
| lint | exit 0；保留既有 warnings | `artifacts/j1-w67-guard-regression/web-lint.log` | `4fca7e26c408641980c0ba2a458c9c267b067859eafb17bc29198bf1fe59e30d` |
| TypeScript | tsc -b --noEmit；exit 0（無診斷輸出） | `artifacts/j1-w67-guard-regression/tsc.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| 最終 diff check | exit 0 | `artifacts/j1-w67-guard-regression/final-diff-check.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| 正式 DB 最終雜湊 | 符合指定 SHA-256 | `artifacts/j1-w67-guard-regression/authority-after.sha256` | `f9447ca29aaa6ffd740f9875f77a1d875aa468b81a7229f5310aa307a89c831b` |

以上都是本次親自執行，沒有以 worker／歷史回報替代。全部證據、來源與 exit receipt 的逐檔 SHA-256／大小見 `artifacts/j1-w67-guard-regression/evidence-manifest.json`；完整命令與輔助重跑見 `commands.txt`。空輸出的 TypeScript／diff check 由 exit receipt 佐證，不能單憑空檔判定通過。

5 個既有 skip（未新增）：

- `tests/test_m2a02_plugin_launcher.py::test_project_has_an_unambiguous_visible_identity`
- `tests/test_m2a02_r02_georeference.py::test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path`
- `tests/test_pst_syntax.py::test_compute_pst_six_syntax_layers_m4h_context`
- `tests/test_site_analysis_report.py::test_syntax_map_rerender_when_matplotlib_is_available`
- `tests/test_week4_r03_integrity.py::test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit`

## Handoff 與治理

未切分支、未 commit／stage／push／merge、未部署或安裝／下載、未呼叫付費 API／Live AI、未刪檔、未重啟／操作受保護正式服務或 8940／8941。無正式密語存取與正式 domain decision 寫入。

變更保留未提交：`tests/week7_support.py`、新增 `tests/test_database_guard_isolation.py`、本報告及 `artifacts/j1-w67-guard-regression/`。`.venv` 是開工前就存在的未追蹤項，不屬本次變更。最終 `git diff --check` 退出 0；tracked diff 僅上述 helper。沒有自我接受或跨 provider review 宣稱。

ownership_claim、progress 與 handoff 以 UTC/UUID exclusive 建立於共享 events；OPERATIONS-LOG.md 僅追加。交指揮官核對 diff、所有證據 hash，以及已知未通過項；J2 批准解析仍未由本任務處理。整體完整回歸 **INCOMPLETE**，guard 修正的有限範圍驗證已完成。
