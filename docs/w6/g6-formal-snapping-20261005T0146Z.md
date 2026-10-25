# G6 正式道路吸附

TASK: G6 formal snapping
STATUS: DONE_ON_BRANCH
BRANCH/COMMIT: wp/w6-formal-snapping。SHA 記在同一次 OPERATIONS-LOG 追加，本文件與程式同一個 commit。父提交 b58859397f9f102c35f4eda2ce47cac3c53c73ba。未合併、未驗收。

CHANGED FILES:
- src/urban_design/editing/roads.py
- src/urban_design/editing/formal_authority.py
- src/urban_design/editing/road_dependencies.py
- src/urban_design/scenario_editing_api.py
- src/urban_design/scenario_api.py
- web/src/components/ScenarioStudio.tsx
- web/src/components/ScenarioStudio.test.tsx
- tests/test_road_snapping.py
- tests/test_formal_road_snapping.py
- docs/w6/g6-formal-snapping-20261005T0146Z.md

做了什麼：正式草稿可以預覽並套用七種地面公尺吸附：ENDPOINT、NEAREST_POINT、MIDPOINT、INTERSECTION、PERPENDICULAR、QUARTER、THREE_QUARTER。多點 LineString 會保留中間節點，兩段以上的連接路徑用沿線長度取四分點、中點與四分之三點，方向從幾何起點算。折線 [(0,0),(10,0),(10,30)] 的長度是 40 m，中點 (10,10)、四分點 (10,0)、四分之三點 (10,20)。外框中心 (5,15) 不是候選。共用節點把目標邊切開時，新邊的 lineage 保留被切的邊。不同 level 的橋不參與地面節點的吸附。道路圖一改，Syntax、可達性與 E1 都標成 STALE。只加一層樓時 E1 變 STALE，道路圖雜湊與 Syntax、可達性維持 CURRENT。acceptance 仍是 false。

TESTS (fresh):
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_formal_road_snapping.py tests/test_road_snapping.py tests/test_road_snapping_api.py tests/test_road_invalidation.py tests/test_road_editing.py tests/test_formal_editor_authority.py tests/test_scenario_editing_api.py`
- cwd：`/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor`。stdin 脫離 tty。結果：40 passed，1 warning，4.20s。
- 另外 `tests/test_formal_face_editing_api.py tests/test_face_editing_api.py`：8 passed，1 warning，1.46s。
- `web/node_modules/.bin/vitest run src/components/ScenarioStudio.test.tsx src/components/RoadSnapPanel.test.tsx`：2 files，13 passed。道路編輯後畫面上的 Syntax、access-fixture、e1-fixture 都帶 `is-stale`。沒有下載套件。
- 本包沒有重跑全套。G13 記錄的 PNG 位元組斷言沒有放寬，也沒有新增 skip。

SELF-CHECK:
- [x] 七種吸附各有正例與反例。正例座標來自 snap-candidates 回應；反例移動回 409，且回應含 NOT_READY。
- [x] 40 m 折線的中點、四分點、四分之三點是 (10,10)、(10,0)、(10,20)。(5,15) 不是候選。
- [x] 中點套用後，含 `poly:1` lineage 的新邊存在。level 1 的 bridge 兩端仍是 b0、b1。
- [x] 重讀草稿後，syntax-formal、access-formal、e1-formal 都是 STALE。UI 測試裡三個標籤的 class 含 `is-stale`。
- [x] 加一層樓後 e1-formal 是 STALE，syntax-formal 與 access-formal 仍是 CURRENT，道路圖雜湊不變。
- [x] 權威庫這包沒有寫入。視覺自我檢核 INCOMPLETE。`npx --no-install playwright --version` 仍因缺少套件停止，沒有下載，沒有截圖。

ARTIFACTS:
- src/urban_design/editing/roads.py `5a40d1bf1d7c44e6430e7eb36b744af059379ddf449f292fa4fb6fa7adc78205`
- src/urban_design/editing/formal_authority.py `57f560aa560ea84cee94dac2ac957410bb0dd11b9ed5fed85580a721c0523eb2`
- src/urban_design/editing/road_dependencies.py `887a50de53e645b4824443c0f122ef4c47213d8c3e6898135eaa1fbdad5ff357`
- src/urban_design/scenario_editing_api.py `97271b216418f4050408e0cfcbd6c1987e9b4371580acadfc49e9ee9d869a663`
- src/urban_design/scenario_api.py `6a1fb3cc4c17485d1a7162f785c5ba4e98e7028430dc149121d83929c459fc3c`
- web/src/components/ScenarioStudio.tsx `bbaf3baadd0ae7d7c0f02ca5dc419fcd7eae5831226bab44dea191b4ccb2015f`
- web/src/components/ScenarioStudio.test.tsx `5e6c0e01967f56a71e74b8fffc48f7042ce65d73a10499e110a1776e70de5027`
- tests/test_road_snapping.py `f9fb7516105a8f619eb03a959eb6be4bcc81a52e917dbb29ac3a115919db6119`
- tests/test_formal_road_snapping.py `d9ce504ad9a291a51651614a00e945b56d328793b7ca2e350f7e47a179cf88df`

DEVIATIONS: 單邊的中點、四分點與四分之三點仍從該邊的起點量，既有八公尺邊測試沒有改。連接路徑的分數點是另外加上的。正式道路移動不再因 adapter 存在就整段拒絕；不完整的正式綁定仍回 409。

RETRIES/CLEANUPS: 分析編號若在接受之後才寫進祖先方案，正式草稿會因決策修訂過期而開不出來。已改成接受前寫入。沒有改名或刪檔。

STOP POINT / NEEDS: 合併等決策三與 Founder 批准。指揮官審查這個分支。視覺畫面仍是 INCOMPLETE。Live AI 與天氣維持 READY_FOR_FOUNDER。G3 的持久與量測仍是 PARTIAL。

NEXT: G14 `wp/w6-closeout-integration`，同一工作樹，從這個分支切出。不合併到 main。
