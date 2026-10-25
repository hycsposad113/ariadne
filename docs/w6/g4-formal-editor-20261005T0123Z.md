# G4 正式編輯器

TASK: G4 formal editor
STATUS: DONE_ON_BRANCH
BRANCH/COMMIT: wp/w6-formal-editor。SHA 記在同一次 OPERATIONS-LOG 追加，本文件與程式同一個 commit。父提交 7ea3b8995795d0222143bbb743edb27b5192aa59。未合併、未驗收。

CHANGED FILES:
- src/urban_design/editing/formal_authority.py
- src/urban_design/scenario_api.py
- src/urban_design/scenario_editing_api.py
- web/src/components/ScenarioStudio.tsx
- web/src/components/ScenarioStudioDashboard.tsx
- tests/test_formal_editor_authority.py
- docs/w6/g4-formal-editor-20261005T0123Z.md

做了什麼：已接受的 formal-dictionary 方案才能開出 `FORMAL_DRAFT`。草稿帶樓層多邊形、道路 LineString、來源參照、基線 HumanDecision 與 D2 定義摘要。PROPOSED、REJECTED、fixture、預覽、過期約束、幾何位元組不符、未知來源、缺父方案、缺核准事件、決策修訂過期，都回 409 或 `FormalAuthorityError`。樓地板面積用含洞多邊形，陸域分母固定 183591.328 m²。正式草稿的整體 `site.far` 維持空值。卡片名稱改讀 recipe 或形態族。選到已接受且沒有可編輯建物的方案時，前端才呼叫 formal-draft。

TESTS (fresh):
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_formal_editor_authority.py tests/test_scenario_editor_bridge.py tests/test_scenario_comparison_router.py`
- 結果：24 passed，1 warning，4.66s。stdin 脫離 tty。
- `web/node_modules/.bin/vitest run src/components/ScenarioStudioDashboard.test.tsx`：2 passed。既有整體容積率「無法提供」仍在。
- 本包沒有重跑全套。G13 記錄的 PNG 位元組斷言沒有放寬，也沒有新增 skip。

SELF-CHECK:
- [x] 只有已接受方案開出具名 FORMAL_DRAFT；第二次請求回傳同一筆。
- [x] REJECTED 與 PROPOSED 被拒，原因寫在回應裡。
- [x] fixture 路徑仍走原守衛。`tests/test_scenario_editor_bridge.py` 這輪是綠的。
- [x] 移出設計範圍的草稿可存，acceptance 與 analysis 都是 false。
- [x] 樓地板 480 m²，外框 512 m²，兩者不相等。陸域 FAR 是 480/183591.328。`site.far` 是 null。
- [x] 重開 store 後草稿、來源與樓地板面積還在。undo 與 redo 回 200。
- [x] 冪等鍵配上不同位移回 409，ledger 事件數不變。
- [x] 權威庫 mode=ro：SHA-256 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`，3211264 bytes，quick_check ok，Approve 3，ledger 303。本包沒有寫入。
- [ ] 視覺自我檢核 INCOMPLETE。`npx --no-install playwright --version` 因本機沒有 playwright 套件而停止，沒有下載。

ARTIFACTS:
- src/urban_design/editing/formal_authority.py `f2973ab077e7f8eae1315f9e8383ac6be24637ee2eedbbad083559cdec2d2ccc`
- src/urban_design/scenario_api.py `495d267f6c68f92fe856b8ba4c86904e1b95399e737b0950dbca99288fc15264`
- src/urban_design/scenario_editing_api.py `8cc4eb09d950498eeaf2d91af30ddda80596dce5f43629810c7cf7b057a67f22`
- web/src/components/ScenarioStudio.tsx `5c8a37be5c7aa3b7d6bd7c759aba4170ee787dc12e960e239c2f70990a0c4777`
- web/src/components/ScenarioStudioDashboard.tsx `680651e7c2845c6bda730cb267f37d1503169946d78a71bd213dae64dfa78ed0`
- tests/test_formal_editor_authority.py `c8d7b5e6c183f71167f70f93fdde9a24334f53c842dad01d8c577c25d4ab1156`

DEVIATIONS: 正式編輯做在 `wp/w6-formal-editor`，不是做在先前六個語法與測試髒檔上面。那些檔在 `wp/w6-editor-custody` `06d6a895e5e6435738f50796840c725d4be6583c`。沒有 stash、reset、clean，也沒有新 worktree。未追蹤的 `.venv`、baseline、`out/`、week4 fixture、`docs/w6/week6-test-baseline-r01.md` 沒有進這個 commit。

RETRIES/CLEANUPS: 故障測試初稿在 `resolve` 成功時會放行。改成 `pytest.raises(FormalAuthorityError)`。未知 snapshot 若在接受之後才寫入，會先撞上決策修訂過期，所以改成接受前寫入，再打 formal-draft。沒有改名或刪檔。

STOP POINT / NEEDS: 合併等決策三與 Founder 批准。指揮官審查這個分支。視覺畫面仍是 INCOMPLETE。Live AI 與天氣維持 READY_FOR_FOUNDER。

NEXT: G5 `wp/w6-formal-faces`，同一工作樹，從這個分支切出。
