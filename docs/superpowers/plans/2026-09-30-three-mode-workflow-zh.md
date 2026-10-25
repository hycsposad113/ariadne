# U4：三模式操作、版本重算與整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. contracts完成後才派前後端平行施工。

**Goal:** 以同一管線支援骨架優先、完整方案、逐步共同設計，能切換、修改與重播。
**Architecture:** mode是interaction policy而不是geometry algorithm。server-owned job/state控制執行、idempotency、stale與recovery；既有workspace/scenario/decision services保留權威。
**Tech Stack:** FastAPI/Pydantic、SQLite、immutable Artifacts、React、既有editing commands、pytest/Vitest/disposable browser。

## Task U0：mode policy與明確停點

Create `src/urban_design/generation/workflow.py`、`tests/test_generation_modes.py`。
```python
from enum import StrEnum

class GenerationMode(StrEnum):
    SKELETON_FIRST = "SKELETON_FIRST"
    FULL_SCHEME = "FULL_SCHEME"
    STEPWISE = "STEPWISE"

STOP_AFTER = {
    GenerationMode.SKELETON_FIRST: frozenset({"SKELETON", "MASSING"}),
    GenerationMode.FULL_SCHEME: frozenset({"MASSING"}),
    GenerationMode.STEPWISE: frozenset({"SKELETON", "BLOCK_PROGRAM", "MASSING"}),
}

def needs_user_selection(mode: GenerationMode, stage: str) -> bool:
    return stage in STOP_AFTER[mode]
```
完整模式仍生成／保存全部中間層；骨架模式選定一個或fork多個骨架後才量體；逐步模式可微調各層。選中stage稱CONTINUE_WITH_SELECTION，不自動建立HumanDecision。
- [ ] RED：mode改變不能更改geometry hash；switch到STEPWISE可檢视已完成中間結果，不必重跑。
- [ ] FULL_SCHEME不跳過已存在的人類hard constraints；不讀到新模型建議就改鎖定geometry。
- [ ] 使用者改上游才invalidate依赖層，不能把純UI tab切換當成新run。
CP-U0：相同stage selections与seed，三模式artifact hashes一致。

## Task U1：durable jobs、一次派送與恢復

Create `generation/job_store.py`、`job_runner.py`、`tests/test_generation_jobs.py`。
Integration owner modify `store.py` 的schema migration，仅新增execution bookkeeping，不改既有歷史records。
技術提案：主SQLite新增 `generation_jobs`、`generation_job_events`，前者mutable current status，後者append-only執行史；domain ledger仍只有正式發布Artifact/ToolExecution/Scenario與人類決策，不把每個progress刷成domain事件。migration先在副本測，合併時由Claude review。

欄位：job_id PK、project_id、idempotency_key UNIQUE(project_id,key)、request_hash、input_refs_json、stage、status、owner_token、last_heartbeat、output_manifest_ref、error_code。events：event_id PK、job_id、seq UNIQUE(job_id,seq)、time、from_status、to_status、reason。

- [ ] POST先BEGIN IMMEDIATE；同key同request_hash返回舊job，同key不同request→409，不再dispatch。
- [ ] job claim以CAS `UPDATE ... WHERE status='PENDING' AND owner_token IS NULL`；只有rowcount1的worker可執行。
- [ ] local geometry worker寫獨立staging dir，所有產物size/hash驗證再做同filesystem rename。SQLite與filesystem不能宣稱單一原子交易：manifest先PREPARED，publish成功才transaction登記domain refs；最後markCOMMITTED。
- [ ] crash在rename前／後／DB commit後各有reconcile：驗證immutable輸出並恢復index，不刪除peer目錄、不自動重算外部工具。存在同ID不同hash→BLOCKED_COLLISION。
- [ ] heartbeat過期先查pid＋owner token＋artifact狀態；純本地deterministic job可由明示recovery接管已發布產物；外部post-dispatch失聯→OUTCOME_UNKNOWN，不直接retry。
- [ ] cancel只取消該job，已完成artifact保存，未完成staging標interrupted；不 kill共享QGIS/Hermes。
- [ ] job輸出不得由舊workspace rev覆蓋當前head；READY artifact保留但STALE_FOR_CURRENT_CONTEXT。

HTTP：POST /api/v1/projects/{project_id}/generation-jobs（202）；GET /generation-jobs/{id}；POST /generation-jobs/{id}/cancel；POST /generation-jobs/{id}/continue（带selected stage ref/expected_revision）。GET不能觸發重跑。
CP-U1：double-click、兩worker、restart、lost-response、disk-full/DB failure的測試均不重複邏輯輸出；request可重播。

## Task U2：失效依賴與局部編輯

Create `generation/invalidation.py`、`tests/test_generation_invalidation.py`；reuse `scenario_editing_api.py`、`editing/` 幾何commands。

| 變更 | 需過期的結果 | 可保留 |
|---|---|---|
| StudyArea／保留幾何／主要道路／hard spatial zones | skeleton→blocks→massing→all affected analysis | 舊版本只讀 |
| program allocation | blocks/program→massing＋use-sensitive metrics | 原skeleton |
| footprint位置／形狀 | massing metrics、affected obstruction/entrance analysis | 不受影響骨架 |
| 高度／樓層 | GFA/FAR/height、sun/shadow/radiation cache | 純水平road graph/syntax（若entrance不變） |
| 色彩、標籤、鏡頭 | 僅出圖cache | 所有量測 |
| weather source | weather-dependent analysis | spatial analysis/geometry |

- [ ] 比較server input hashes，不只靠UI猜變更類型；artifact依賴明確記錄。
- [ ] edit command必帶base_revision、target geometry hash；server驗證並計算，client即時dashboard标PREVIEW。
- [ ] 保存無效草稿、undo/redo追加版本；不能改保留locked feature，除非使用者明示更新保留決策。
- [ ] top每次一層；lateral相對1m；road snapping用真實節點/line投影位置，不為整数斷開道路。
- [ ] disjoint edit仍需序列化workspace revision，冲突顯示409，不能last-write-wins抹掉另一panel更新。
CP-U2：改高度不改道路hash；改入口不沿用舊accessibility；舊結果仍可看但明示stale。

## Task U3：React介入節奏與stage inspector

Create `web/src/components/GenerationWorkflow.tsx`、`GenerationModeSelector.tsx`、`GenerationStageInspector.tsx`、`generationWorkflow.ts`（types/client），及對應`.test.tsx`。
Modify App.tsx（sidebar patch合併後）与ScenarioStudio.tsx（preview panel改動合併後），不能平行覆寫。

- [ ] 將mode selector放生成入口：先骨架／完整方案／逐步設計；顯示這次會停在哪一層。預設可建議骨架優先，但不強迫使用者。
- [ ] stage inspector顯示來源brief、locked elements、proposal geometry、why/limits、continue/fork/reject；生成中取消可用。
- [ ] 分開「繼續生成」「保存草稿」「接受方案」按鈕語义；接受必須現行HumanDecision流程，不由mode自動提交。
- [ ] 用AbortController/response context IDs拒絕過期回應；不要晚到的job把新草稿重設。
- [ ] 前端poll仅针对明确job lifecycle（有取消与完成停止），與指揮官禁止busy-poll worker不是同一件事；刷新可用GET恢復job，不再POST。
- [ ] Rerun仅重新計算同版選擇；Modify/Fork建立新brief/run ref；模型對話建議不是隱藏設定變更。
- [ ] 空dataset、provider不可用、生成只得2個、stage BLOCKED、有未存草稿五種狀態各有可操作解釋。
CP-U3：自設＋AI建議都可進三模式；沒有為停點改過資料／批准界線。

## Task U4：比較、出圖與研究呈現

Create/extend `generation/comparison.py` adapter、`web/src/components/StrategyComparison.tsx`、對應tests；沿用 `src/urban_design/figure_export.py` 與 `tests/test_figure_export.py`；新 renderer 只在既有 module 無法提供所需視圖時增加，不改寫歷史輸出。
- [ ] 同一context/方法下比較；不同強度/assumption set分組，不能把它們當同條件實驗。
- [ ] 道路／開放空間骨架、量體平面、等角、用途、高度、參數表六種視圖可追同scenario rev。
- [ ] renderer輸出固定視角/尺度policy；平面有比例尺與北箭頭，透視不放誤導的單一比例尺；移除操作handles。
- [ ] labels包含UNAPPROVED_PREVIEW/PROPOSED、method/version、known-part/missing值；比較圖不把空白metric變零。
- [ ] 未跑日照風場就不提供假的「最佳舒適」徽章；UI只列可用engine與尚需輸入。
CP-U4：以圖面與差異解釋方案，而不是只用十張縮圖＋VALID。

## Task U5：獨立review、live session與回滾

Create `web/e2e/generation_workflow.py`、`tests/test_generation_end_to_end.py`。
- [ ] 端到端最小case六條路徑：manual/AI-edited brief × 三mode。fixtures驗證流程，額外已授權真provider smoke驗證AI環節，分開報。
- [ ] disposable SQLite backup API（含WAL一致性）與新ports；前後authority DB不變；不得透過正式app初始化去做「唯讀」查核。
- [ ] bounds/browser：至少1280/1440/1920 desktop，3D無WebGL時fallback清楚；不以browser crash當pass。
- [ ] 採用相同測試brief和seed比較三mode的stage hashes；human會改中間結果時差異是預期，不要求盲目相同。
- [ ] schema/server/client version compatibility、wrong inputhash、restart recovery、source mutation、unavailable provider都測。
- [ ] cross-provider review完成指定diff hash；Claude＋Founder決定是否merge與runtime activation。
- [ ] 正式切換前確認draft已保存/匯出，不能靠刷新丟掉；port owners與DB path實測記log。
- [ ] 回滾切回previous code/config；append-only artifacts/ledger不倒退不刪，新增generation結果保留只讀。
CP-U5：LIVE_ACCEPTANCE_READY僅表示可給設計者試用；人類接受方案與整個學期完成是別的gate。

## 共同執行契約

本文件與 `2026-09-30-site-analysis-generation-master-zh.md` 同版使用。一次只領一個task，先RED再GREEN；原始輸入只讀、每個CP更新shared event。所有新符號／route為planned，既有fixtures成功不代替live驗證。尚未取得main merge／runtime activation批准時，交付reviewable diff，不自行部署。

## U1 CAS 核心與失敗界線

下列SQL在同一connection交易執行；owner_token為每次claim的隨機身份，不能用UI提供的approved flag替代：
```sql
BEGIN IMMEDIATE;
UPDATE generation_jobs
SET status = 'RUNNING', owner_token = :owner_token,
    last_heartbeat = :now_utc
WHERE job_id = :job_id AND status = 'PENDING' AND owner_token IS NULL;
-- Check cursor.rowcount in Python before appending an event.
COMMIT;
```
rowcount=0時不能跑handler，也不能追加RUNNING成功事件。事件append與UPDATE須同交易；上面SQL的COMMIT要在Python確認rowcount及event INSERT後才送出。不要用SELECT後無條件UPDATE。

job handler contract：`run_stage(stage_input_ref, staging_root, cancellation_token) -> PreparedManifest`。PreparedManifest具manifest_path、sha256、input_refs、output_refs、handler_version；未通過hash驗證不能發布。handler registry server-owned，request不得傳python import path。analysis handler與generation handler共用durable job core，但各有schema/validation，沒有任意code dispatch。

一次用兩個SQLite connections做 barrier 同時claim同job，assert one winner、one execution receipt。另測已rename未登記DB的故障點：restart只驗證並接回同輸出，不新增第二個Artifact identity。這些測試跑disposable DB，不測正式project.sqlite。
