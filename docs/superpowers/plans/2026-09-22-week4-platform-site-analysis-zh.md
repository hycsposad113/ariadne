# Week 4 平台接入與基地分析密集執行計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 每個 checkpoint 先自行檢核再獨立覆核；失敗只停止相依工作，不擴大授權。

**Goal:** 本學期 Week 4 讓設計者在自有平台完成 QGIS 按鈕同步、保留要素選擇、局部需求標記、基地分析、三尺度 Space Syntax 與 AI 證據解釋，並準備 Week 5 的多方案生成。

**Architecture:** 沿用後端權威狀態、immutable snapshots、append-only ledger 與受限 QGIS facade。新增 typed 工作區同步、前端可編輯圖層、確定性分析 job 與 Evidence Cards；AI 只讀經驗證的結果並提出可確認的需求／操作。

**Tech Stack:** 現有 Python、Pydantic、FastAPI、SQLite、pyproj、Shapely、pytest；計畫新增 React／TypeScript 前端及受驗證的 map／3D／Syntax adapters。版本和授權在 CP4-1 凍結，不把尚未選定的引擎當成已安裝能力。

---

## 0. 範圍、文件與目前起點

本計畫與 [整体藍圖](2026-09-22-semester-project-blueprint-zh.md)、[新版產品契約](../../08_WORKFLOW_REALIGNMENT_2026-09-22.md) 配套。舊 Week 2 計畫的來源與政策工作仍可重用，但本週不再只以它作全部產品成果。

執行前讀 AGENTS、README、docs/00、01、02、03、05、06、07 與新版契約；再讀必要的 R08–R09-R01、spatial-r01 和各 addendum。研究報告提供背景，不批准 policy。目前看到後端與現有來源審查程式，尚未確認有前端或可用 Syntax runtime。

受保護：所有原始與歷史包、blocked weather r03、spatial-r01、原／r02／r03 addendum、既有 ledger events、StudyArea geometry、weather bytes、Hermes 8787。新前端埠必須先檢查未佔用；bridge 8788 也要先確認實際 owner。不得 kill／restart 別的服務。

本計畫只制定後續工作；不等同本回合已授權執行。模型內部 sub-agent 若使用，遵循 AGENTS 的模型／reasoning 限制；不符合則主代理順序執行。不要自行發送至 Grok／AGY 或建立新 task。

## 1. 本週檔案地圖

| 任務 | 已有檔案（必要時修改） | 新增（實作時建立） |
|---|---|---|
| P0 基線 | 無需修改 source | 新 revision 的 baseline／gate report |
| P1 工具驗證 | 既有 probe 只讀 | `scripts/probe_space_syntax.py`, `scripts/probe_editing_geometry.py`, `tests/test_space_syntax.py` |
| P2 typed 同步 | `src/urban_design/models.py`, `store.py`, `bridge.py`, `qgis_facade.py` | `workspace_contracts.py`, `workspace_service.py`, `api.py`（同 package），`tests/test_workspace_sync.py`, `tests/test_workspace_api.py` |
| P3 平台 | 無現有前端可假定 | `web/package.json`, lockfile, `web/src/App.tsx`, `web/src/features/workspace/`, `web/e2e/workspace.spec.ts` |
| P4 要素與 brief | 現有 models／store | `src/urban_design/design_brief.py`, `tests/test_design_brief.py`, `web/src/features/brief/` |
| P5 基地分析 | 現有 sources／analysis_inputs | `site_analysis.py`, `context_network.py`, `tests/test_site_analysis.py`, `tests/test_context_network.py` |
| P6 Syntax | P1 probe 結果 | `src/urban_design/space_syntax.py`, `web/src/features/evidence/` |
| P7 AI／首張圖 | `src/urban_design/reasoning.py` | `model_provider.py`, `site_critic.py`, `figure_export.py`, `tests/test_site_critic.py`, `tests/test_figure_export.py`, `web/src/features/figures/` |
| P8 驗收 | 現有 docs 的狀態記錄 | 新 revision 的 acceptance record、圖與 demo |

`src/urban_design/` 相對 package 路徑不可與 scripts 混淆。新 module 名稱是規劃契約；不要在它尚未存在時聲稱 import／測試已成功。不同執行者共用 models/store 時採序列整合。

## 2. Phase P0 — 基線與範圍核對

- [ ] 讀本節所列必讀文件，整理目前程式／資料／文件差異。
- [ ] 查詢 SQLite 的 active StudyArea、HumanDecision、ParameterDefinition、Artifact、DatasetSnapshot 與 ledger 實際數量，保存讀取時間與資料庫位置。
- [ ] 分別驗證歷史 hash 與目前 authority；對 verifier source hash drift 不偷換 pass。若需新 addendum，在後續獨立新 revision 修復，原 r03 保留。
- [ ] 核對 QGIS／bridge／Hermes 埠 owner；只做必要唯讀檢查，服務不可用就記錄而非重啟。
- [ ] 核對來源 license、查詢 envelope、完整性及原有 live run receipts。審查資料是否足以支持新的 analysis scale。
- [ ] 建立本週需求覆蓋表：R26-01–06、13–14；W5/W6 預研列成支援工作，不冒充完成。

**CP4-0：** 基線可追溯；保護範圍清楚；現有未批准政策仍未批准。來源 drift 阻擋受影響的 live package，前端可用明示的 synthetic fixture 繼續开发。

## 3. Phase P1 — 第一天提前消除技術風險

### P1.1 Syntax 最小真實計算

- [ ] 查第一方文件，選定能計算 segment angular integration／choice、支援 metric radius 且可在目標環境執行的引擎。
- [ ] 將直線、T 字、對稱十字、不同轉角、孤立元件與跨越不相接的小網路製成 fixtures；記錄精確幾何、CRS、分段與方法。
- [ ] `scripts/probe_space_syntax.py` 執行引擎，保存原始輸入／輸出、版本與 log；與獨立參考計算或經核實的 reference output 對照。
- [ ] `tests/test_space_syntax.py` 檢查對稱性、radius 納入範圍、角度改變效果、孤立結果、欄位與單位。reference 不可由同一次被測函式自行產生。

**CP4-1a：** 真實引擎算出符合定義的 integration／choice。不得以 NetworkX 一般 centrality 改欄位名替代。若不可用，列具體平台／方法阻塞；其餘獨立任務繼續，Syntax 核心不降級。

### P1.2 編輯與環境預研

- [ ] `scripts/probe_editing_geometry.py` 試做逐層體塊、平面分割、局部水平推拉與每層面積，核對自交／無效幾何被拒絕。
- [ ] 核對 Ladybug／Honeybee／Radiance 真實 runtime 路徑與以前 smoke 證據，不跑未批准的基地氣候實驗。
- [ ] 為 E3/E4/E5 寫輸入需求與最小可行性結果；無 runtime 或必要假設時明示未驗證。
- [ ] 天氣方法另列 decision packet：仍缺什麼、何種證據可解除 gate、人類可選的後續路徑。沒有本任務授權就不聯絡 provider、不下載候選、不轉換。

**CP4-1b：** W5 編輯基礎可驗證；高風險能力已有具體結果或阻塞，不能等到 W8 才發現缺 runtime。

## 4. Phase P2 — typed 工作區與按鈕同步

### P2.1 新契約

以下為待實作的最小 typed 邊界；不得把已存在的 domain records 複製成另一套來源。

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class SyncRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str = Field(min_length=1)
    study_area_id: str = Field(min_length=1)
    expected_workspace_revision: int = Field(ge=0)
    source_snapshot_ids: list[str] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)

class FeatureDisposition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_artifact_id: str = Field(min_length=1)
    feature_id: str = Field(min_length=1)
    feature_kind: Literal['building', 'road']
    disposition: Literal['preserve', 'editable', 'undecided']

class WorkspaceRevision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace_id: str
    revision: int = Field(ge=1)
    study_area_id: str
    source_snapshot_ids: list[str]
    feature_dispositions: list[FeatureDisposition]
    status: Literal['DRAFT', 'VALIDATED', 'STALE']
```

實際 server 必須從 persisted records 解引用並驗證 hash，不相信客戶端傳來的 source、geometry、status 或批准聲明。此最小 schema 尚不取代已有 Artifact／StudyArea 的完整 provenance。

### P2.2 先測失敗，再接服務

新測試起點（`tests/test_workspace_sync.py`）：

```python
import pytest
from pydantic import ValidationError
from urban_design.workspace_contracts import SyncRequest

def test_sync_rejects_empty_sources():
    with pytest.raises(ValidationError):
        SyncRequest(project_id='fixture-project', study_area_id='fixture-area',
                    expected_workspace_revision=0, source_snapshot_ids=[],
                    idempotency_key='fixture-1')

def test_sync_rejects_client_approval():
    with pytest.raises(ValidationError):
        SyncRequest(project_id='fixture-project', study_area_id='fixture-area',
                    expected_workspace_revision=0, source_snapshot_ids=['fixture-source'],
                    idempotency_key='fixture-1', approved=True)
```

- [ ] 寫上述測試並執行，確認首次失敗來自未存在的契約，不是環境錯誤。
- [ ] 實作 `workspace_contracts.py` 後測試通過，再增加持久化／來源關係測試。
- [ ] API 規劃：`POST /api/v1/workspaces/sync`、`GET /api/v1/workspaces/{workspace_id}`。首次建立回傳 201；相同 key＋相同 payload 回傳同 revision；key＋不同 payload 回傳 409；來源無效／政策缺失回傳具體 422；舊 revision 回傳 409。
- [ ] sync 只讀取 allowlisted QGIS export／既有快照。不得加入任意 execute_code 或「方便」SQL endpoint。
- [ ] 來源解引用、版本分配與 ledger 事件原子提交；中途失敗不留下完整狀態假象。舊草稿保留，需確認的 merge 顯示 diff。
- [ ] 寫 transaction rollback、重複 dispatch、stale StudyArea、來源被改、缺 parent、連線中斷 OUTCOME_UNKNOWN 測試。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_workspace_sync.py tests/test_workspace_api.py
```

**CP4-2：** 同步與重播一致，重複請求不新增邏輯快照；不是只把 QGIS 畫面截圖放進平台。

## 5. Phase P3 — 平台可操作骨架

- [ ] 建立 `web/`、lockfile、TypeScript build、單元及瀏覽器測試，選一組地圖／3D renderer，記錄版本與授權。
- [ ] 主畫面包含地圖／3D、要素側欄、AI 區、證據區、版本／job 狀態。不同階段可共用畫面，不必做四套獨立 app。
- [ ] 把資料以稳定 feature ID 呈現；地圖選到的建築，側欄與 3D 指向同一物件。保留 CRS→顯示座標轉換證據。
- [ ] QGIS 按鈕同步後平台更新，已有草稿顯示版本差異；重新整理瀏覽器後從 server 恢復。
- [ ] 地圖 background tile 失敗不使已封存向量資料消失；offline replay 不做隱藏 live acquisition。
- [ ] 瀏覽器測試點擊真實 UI：同步、選物件、切 2D/3D、重開工作區；fixture 與 live 的標籤清楚。

**CP4-3：** 能實際操作且有短錄影／截圖；只有 UI mock 或 API 200 不算通過。紀錄實際端口，不占用 Hermes 8787。

## 6. Phase P4 — 保留物、局部框選與約束預覽

- [ ] 寫 `test_design_brief.py`：錯來源 feature ID、空 polygon、自交、分區超出設計範圍、重疊無分配規則均拒絕。
- [ ] 建築／道路三態選擇与顏色可見；保留物锁定，取消保留須使用者明確改設定。
- [ ] 繪分區、輸入註記，保存 geometry、機能／開放空間訴求、硬／軟條件、作者與版本。
- [ ] 分開 StudyArea、ContextExtent、ExplorationDesignArea；儀表板說清楚分母。概念設計分母不是法律 DesignBoundary。
- [ ] 對 FAR 整體上限與可選區域上限提供輸入；沒有指定值則保持未設定，不填「常見值」。
- [ ] 顯示 AI 解析的可讀表格，等待使用者確認才能啟用新硬條件。已明確批准的相同設定不重複詢問。

**CP4-4：** 操作保存後重新載入一致；保留與移除是 scenario proposal，不刪原始圖層。人類批准不存在就維持 DRAFT，不能假裝為生成器有效輸入。

## 7. Phase P5 — 基地分析與來源補足

### P5.1 來源邊界

- [ ] 先離線驗證 PDOK／OSM 快照可提供哪些欄位，列清楚取得／缺失／不適用。
- [ ] 若要區域路網，提出新的完整 bounded request plan：目的、envelope、endpoint、授權、最大頁數／bytes／timeout、重試與去重規則。
- [ ] 已在本執行任務明確授權的範圍內才 dispatch；舊單次 spatial-r01 acquisition 不視為可無限延伸。未批准時 offline fixture 可繼續。
- [ ] 回應不完整、超預算或 dispatch 後失聯分別記 BLOCKED／OUTCOME_UNKNOWN；先 reconciliation，不盲目重跑。

### P5.2 確定性指標與 Evidence Cards

- [ ] `site_analysis.py` 先做來源覆蓋、建築 footprint、密度、已知用途／POIs、水體／開放空間、道路連通性；缺高度就不產生假的 FAR。
- [ ] 若使用 grocery accessibility，必須仍有三項實際人類政策批准；未批准則該指標 BLOCKED，不擋別的有效分析。
- [ ] 每個 result 綁來源／範圍／單位／公式版本／geometry hash／參數／缺口，建立可點開的卡片。
- [ ] 圖層與 AI 使用同一 result ID，不用兩套各算各的數字。

測試基線：兩個不重疊 100 m² footprints 位於 1,000 m² fixture，coverage 應為 0.2；少一個 feature 的來源失敗不能變成 coverage 0.1 的有效觀測。只有確認完整且真正空的資料才可得到零。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_site_analysis.py tests/test_context_network.py
```

**CP4-5：** 至少能說明建築、道路、機能、開放空間／水體與資料限制；未知欄位可 unavailable，不可把未知說成沒有。輸入足夠且必需的核心指標須有實算。

## 8. Phase P6 — 六張 Space Syntax 結果

- [ ] 從 P1 鎖定 method manifest，採同一 cleaned segment network 與 800／2,000／10,000 m 三半徑。
- [ ] 清理重複線、斷點與平面交叉；按 bridge／tunnel／layer 處理立體交叉；缺 tag 不能暗中推成同層。
- [ ] 檢驗擷取範圍是否支援半徑，做擴大 extent 的穩定性對照；保存受邊界影響道路與比較結果。
- [ ] 產生每段兩指標×三半徑，保留原值及顯示分級；圖例標明方法／半徑／正規化與缺失。
- [ ] 預設不按交通工具過濾；UI 說「局部／中距／區域尺度」，不標成已驗證 walk/bike/car 預測。
- [ ] 切圖不改資料；比較不同尺度若使用不同色阶需明示。AI 查值以 backend result 為準。
- [ ] 執行 P1 參考、拓撲、缺資料、邊界、重播及來源 drift 測試。

**CP4-6：** 六圖實際存在且方法校驗通過，AI 可引用；無法證明完整性的段保留標記。若只有六張假色線圖而無正確計算，FAIL。

## 9. Phase P7 — AI 解釋、需求轉譯與初步出圖

- [ ] `model_provider.py` 沿用 provider-neutral adapter，配置一個真實 model；secret 由既有安全設定讀，不寫入 artifact／prompt log。
- [ ] `site_critic.py` 輸出 evidence references、觀測解釋、設計假說、局限與可選後續；模型不能直接改 ledger 或調工具權限。
- [ ] 測試捏造數字、錯 scenario、錯 radius、過期來源、無憑據交通預測被拒絕；未知值明示未知。
- [ ] 區分 factual evidence 與「適合中央開放空間」的設計建議；設計建議交人類評估。
- [ ] 如使用參考圖檢索，保留來源與使用權限制；結果不能自動成為 geometry 或效果證明。
- [ ] 初步圖像輸出：分析 map 與 3D 截圖，隱藏控制器，含版本、圖例與資料狀態；完整出圖版型在 W8 驗收。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_site_critic.py tests/test_figure_export.py
```

**CP4-7：** 真實 AI 可讀有效證據回答基地優缺點並展示來源；實際圖片檔可開啟。model mock 只可作測試，不能替代 live integration evidence。

## 10. Phase P8 — 本週獨立驗收與 W5 交接

- [ ] 跑已建立的 focused tests，再跑 backend 全套與 frontend test/build/E2E；記錄 collected nodes，不用預設測試總數。
- [ ] 由未自我批准輸出的 reviewer 核對真實 UI：同步→保留建築／道路→畫分區→讀基地／六圖→詢問 AI→保存→出圖→重開。
- [ ] 測試 damaged source、stale job、missing policy、未知 access、重複 dispatch、失聯復原與空／缺資料。
- [ ] 重算受保護歷史 hashes；允許本次合法 append 的狀態另表列出，不能要求 ledger 永遠固定某個舊數字。
- [ ] 產出 W5 輸入包：context refs、已確認保留規則、brief／分區、分析 method manifests、有效 evidence refs、尚缺人類決策、幾何預研結果。
- [ ] 本週不自動接受方案、啟動正式 climate experiment 或跨到 W5 實作。後續執行 prompt 清楚指定要接哪個 phase。

**CP4-8：** 核心本週流程有獨立驗收，不把 audit report 當產品。若部分 BLOCKED，列出哪些 W5 fixture 工作仍可開始、哪些真實生成依賴尚未滿足。

## 11. 完整執行 prompt

以下文字供使用者另行交給執行環境。貼上之後才是該任務的執行指示；本次撰寫文件不代表已執行。

```text
請使用 superpowers:executing-plans，執行本專案的學期 Week 4 計畫。

專案：/Users/jackhsieh/Downloads/TUD/Q5/project
主要計畫：docs/superpowers/plans/2026-09-22-week4-platform-site-analysis-zh.md
產品契約：docs/08_WORKFLOW_REALIGNMENT_2026-09-22.md
整體排程：docs/superpowers/plans/2026-09-22-semester-project-blueprint-zh.md

先讀 AGENTS、README 和計畫必讀文件。不要把舊工程 Week 2 當作目前
學期週次：現在 W4 合併平台與基地分析，W5 要開始生成與編輯。

目標是可操作的 QGIS 按鈕同步、自有平台、建築/道路保留選擇、局部框選
備註、基地分析、共同路網三尺度 angular integration/choice、AI 證據
解釋與初步出圖。不是只交文件、manifest 或綠色測試數。

逐步完成 P0–P8 和 CP4-0–CP4-8。允許本計畫列出的程式/前端/測試建置、
離線驗證、新 revision 工作成果與必要文件更新。採 TDD，先確認失敗原因
再實作；真實 runtime 要有證據，不能用 mock 謊稱產品接入完成。

先核對現有狀態與已完成的程式再接續，不重做別人已通過的工作。若 source
hash 改變使舊 addendum 失效，保留歷史，新建有父鏈的修復；不放寬 verifier。

live 請求先列出 endpoint、範圍、來源條款、完整 request/頁數/bytes/time
上限。只有在本任務已有明確授權的範圍內才發送；缺授權時把完整方案交人類，
同時繼續無相依的 offline/UI 工作。不要沿用已消耗的歷史單次請求授權。
真實 AI 請求也要使用已配置與允許的 provider，限制資料內容與呼叫數。

人類決策：保留規則、設計分母、硬性約束及尚未批准的分析政策，以目前
資料做出具體選項後請人類決定。不虛構 actor/reason，不把聊天偏好冒充
資料庫裡已批准的數值。已明確批准且內容相同的決策不重複詢問。

保護歷史資料、StudyArea geometry、所有原始/衍生 weather bytes 和舊 ledger。
零候選 weather ZIP/API 請求；不轉 Minute、不放寬 EPW validator、不聯絡
provider、不選 weather source、不啟動未批准氣候實驗。天氣維持 unresolved。
不搶 Hermes 8787，不 kill/restart 別的服務；QGIS 僅用受限 facade。
dispatch 後失聯標記 OUTCOME_UNKNOWN，先核對 artifacts/狀態再決定能否重試。

Space Syntax 必須真算，不用普通 centrality 改名替代。800m/2km/10km 是
共同路網的尺度，不等同真實三種交通模式。新 buffer 的完整性必須驗證。
面積/單位/缺資料明確；只因高度改變不能改 graph/accessibility。

每個 checkpoint 回報實際操作成果、證據、測試、人類決策、限制及下一步。
相依 gate 失敗不能繼續正式工作，但不擋獨立子系統。
最後交付 TASK STATUS、CP RESULTS、VISIBLE DEMO、FILES CHANGED、
TESTS、REQUEST ACCOUNTING、STATE CHANGES、INTEGRITY、HUMAN DECISIONS、
WEATHER GATE、CORE GAPS、INDEPENDENT REVIEW、W5 HANDOFF。
只完成 W4；沒有後續指示不自行跨入 W5。
```

## 12. 計畫本身的自我檢核

- [x] W4 含平台與基地分析，沒有把 Syntax 延回 W5。
- [x] 本週可見成果覆蓋 R26-01–06、13–14 的指定部分。
- [x] 新模組／命令標明待建立；沒有把計畫測試算成已通過。
- [x] 來源缺口、人類政策與天氣方法不互相冒充批准。
- [x] 完整編輯、三方案、E1/E2、出圖在整體排程都有明確 checkpoint。
- [x] 舊計畫與 artifact 正文保留，當前規劃入口明確。

文件審查記錄（2026-09-22）：新文件本地連結、code fences、R26-01–14 覆蓋、CP4-0–8 與 W1–9 節次檢查通過；兩份 2026-09-21 計畫移除新增通知後的正文 hash 與修改前一致。既有文件一致性測試 `tests/test_m2a02_r01_documentation.py`：2 passed。這些只證明本次文件修訂通過檢查，不代表上方任何產品 checkpoint 已執行；未跑產品全套測試。
