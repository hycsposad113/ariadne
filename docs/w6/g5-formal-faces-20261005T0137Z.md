# G5 正式分面

TASK: G5 formal faces
STATUS: DONE_ON_BRANCH
BRANCH/COMMIT: wp/w6-formal-faces。SHA 記在同一次 OPERATIONS-LOG 追加，本文件與程式同一個 commit。父提交 5d224fbdbc29656e500999bd6b40b253adcc1359。未合併、未驗收。

CHANGED FILES:
- src/urban_design/formal_face_editing_api.py
- src/urban_design/scenario_api.py
- tests/test_formal_face_editing_api.py
- tests/test_formal_editor_authority.py
- web/src/components/FaceEditControls.tsx
- web/src/components/FaceEditControls.test.tsx
- web/src/components/FormalFaceEditor.tsx
- web/src/components/ScenarioStudio.tsx
- docs/w6/g5-formal-faces-20261005T0137Z.md

做了什麼：正式草稿走 `GET/POST /api/v1/scenarios/{scenario_id}/editing/faces`。伺服器載入該建物的樓板，借既有 `FaceEditHistory` 做分割、側推、頂部加層與上層兩層退台，再把多邊形寫回 `FORMAL_DRAFT`。語意面 ID 與舊面到新面的 lineage 存在草稿參數，重開 `ProjectStateStore` 後仍在。分割不改樓板面積。退台只動最高兩層。新高度超過 20 m 時在寫出 staging 之前拒絕。同一冪等鍵與同一內容只算一次編輯；不同內容回 409，不發布第二份產物。過期的情境修訂在鍵尚未存在時回 409，且不建立 staging。發布在寫入 Artifact 失敗時保留 staging 檔，不刪同目錄的其他最終檔。`acceptance_eligible` 與 `analysis_eligible` 維持 false。fixture 路由 `/api/v1/editing/faces/fixture-preview` 沒有改，readiness 仍是 BLOCKED。前端只在 `provenance === FORMAL_DRAFT` 且已選建物時掛上 `FormalFaceEditor`。

TESTS (fresh):
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_formal_face_editing_api.py tests/test_face_editing_api.py tests/test_face_editing.py tests/test_formal_editor_authority.py tests/test_scenario_editor_bridge.py tests/test_scenario_comparison_router.py`
- cwd：`/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor`。stdin 脫離 tty。結果：48 passed，1 warning，6.03s。
- 其中正式分面四則：分割後 API 回傳樓板面積和為 4000.0；上層退台後逐層面積為 864、864、1000、1000，和為 3728.0，差 272.0。加兩層到 21 m 被拒且沒有 staging。加一層高度 17.5 m。重開後 lineage 與 3728.0 仍在。
- `web/node_modules/.bin/vitest run src/components/FaceEditControls.test.tsx src/components/ScenarioStudio.test.tsx src/components/ScenarioStudioDashboard.test.tsx`：3 files，16 passed。沒有下載套件。
- 本包沒有重跑全套。G13 記錄的 PNG 位元組斷言沒有放寬，也沒有新增 skip。

SELF-CHECK:
- [x] 只做分割時，正式 API 回傳的樓板面積和是 4000.0。
- [x] 上層兩層變成邊界 (1, 1, 19, 49) 後，面積和是 3728.0，差 272 m²。
- [x] lineage 在新的 `ProjectStateStore` 上仍然存在。
- [x] 新建高度拒絕 21 m，允許 17.5 m，兩者都不超過 20 m。
- [x] fixture 分面測試仍要求 `production_status == BLOCKED`。這輪 `tests/test_face_editing_api.py` 與 `tests/test_face_editing.py` 是綠的。
- [x] 權威庫 mode=ro：SHA-256 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`，3211264 bytes，quick_check ok，Approve 3，ledger 303。本包沒有寫入。
- [ ] 視覺自我檢核 INCOMPLETE。`npx --no-install playwright --version` 因本機沒有 playwright 套件而停止，沒有下載，沒有截圖。

ARTIFACTS:
- src/urban_design/formal_face_editing_api.py `4309114f8a59e2d70c200a1e3b5a7023e937c2104beb695e68e8ddc98e553f9a`
- src/urban_design/scenario_api.py `0c07d94fd7ebbbecd279a10ed0e88ce03e043f1abe60b7810a983c86e19abf48`
- tests/test_formal_face_editing_api.py `03a528c759a918b0c95afaeccd3c8f2159482bcc41336ed9686233887e46e47a`
- tests/test_formal_editor_authority.py `023c0d97b9902b4201981a1b9a778eec25d94d1a1ec4dcee0cfa1b5f4615cba1`
- web/src/components/FaceEditControls.tsx `865dd4471b497e2469786ff37c30c2a1a8ad1bb0dba0e91f89529f030229bce2`
- web/src/components/FaceEditControls.test.tsx `b200c98e6a60e1c7e66d78de83ec60c5ff31a248b000d6febc6f3f87fb62b75f`
- web/src/components/FormalFaceEditor.tsx `1a883f8238b893c661ed777147b29fda20891e0e8c1ec2a74702e3d681c6274d`
- web/src/components/ScenarioStudio.tsx `23ccca033af7e802bd4a011f937a132237e9da25cf30829121215148c6d4c781`

DEVIATIONS: 幾何核 `editing/faces.py` 仍只接受 `FIXTURE_ONLY`。正式 API 借一份同多邊形的複本給核，再把結果寫回正式草稿，沒有放寬核的來源限制，也沒有把 fixture 路由改成正式路徑。`FaceSelection3D.tsx` 已能用伺服器三角形做 ray pick，這包沒有改它的選取演算法。`_world` 多了一個可選 `stages`，既有 G4 測試仍用原來的樓層。冪等鍵在情境修訂檢查之前比對：同一內容的重送仍是一次編輯；不同內容不發布。

RETRIES/CLEANUPS: 第一輪 pytest 在退台前失敗，因為分割後有兩片 TOP，輔助函式仍要求唯一頂面。已改成呼叫端已給 `face_id` 與 `points` 時不再查頂面。數值斷言沒有改。沒有改名或刪檔。

STOP POINT / NEEDS: 合併等決策三與 Founder 批准。指揮官審查這個分支。視覺畫面仍是 INCOMPLETE。Live AI 與天氣維持 READY_FOR_FOUNDER。

NEXT: G6 `wp/w6-formal-snapping`，同一工作樹，從這個分支切出。
