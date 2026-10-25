# A2：基地分析、設計機會與設計訴求 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 先凍結 contracts，再做 adapters/UI。

**Goal:** 把已有基地資料與計算整理成設計者可用的觀測、問題、機會與局部訴求。
**Architecture:** 保留 site_analysis.py／problem_definition.py 的計算，新增 typed projection，不讓LLM重新估算數值。Brief draft與批准ConstraintSet分離，所有關係綁定snapshot／geometry hash。
**Tech Stack:** Pydantic、Shapely/pyproj、既有EvidenceCard/Artifact/WorkspaceService、React。

## Task A0：分析範圍與既有計算對齊

Read：`src/urban_design/site_analysis.py`、`problem_definition.py`、`docs/w5/site-analysis-report-zh.md`、`docs/w6/problem-definition-zh.md`、現行PD20/PD21。
Create：`docs/technical/site-intelligence-metric-map.md`（實作WP）；不可改歷史報告。
- [ ] 列 metrics 的已實作函式、資料範圍、算法、單位、limitations、是否有reference。
- [ ] 六領域：建築/高度/用途、道路連通、Syntax、綠地水體、機能周邊、環境方法可用性；不承諾未知資料已取得。
- [ ] AnalysisExtent 和 displayed StudyArea分開；800/2000/10000半徑不等於資料擷取buffer。
- [ ] 接受現行有依據的mode-specific網路，另保留coarse common-network模式標籤；不同網路結果不直接作數值排名。
- [ ] 每個analysis status使用 AVAILABLE / PARTIAL / BLOCKED / NOT_RUN；UNKNOWN value用null，不把缺資料當0。
CP-A0：每個展示欄位可追到計算或source；不把proxy改成實際人流、公共通行或可建土地。

## Task A1：契約、關係驗證與數值防污染

Create `src/urban_design/site_intelligence/contracts.py`、`relationships.py`、`tests/test_site_intelligence_contracts.py`。
所有下列型別為planned，放同一contracts，禁止在frontend另發明不同status。
```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

class FrozenRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    metric_key: str
    status: Literal["AVAILABLE", "PARTIAL", "BLOCKED", "NOT_RUN"]
    value: FiniteFloat | None
    unit: str
    method_version: str
    scope_ref: FrozenRef
    input_refs: tuple[FrozenRef, ...]
    limitation_codes: tuple[str, ...]

    @model_validator(mode="after")
    def guard_value(self):
        if self.status in {"BLOCKED", "NOT_RUN"} and self.value is not None:
            raise ValueError("unavailable observation cannot carry a number")
        if self.status == "AVAILABLE" and self.value is None:
            raise ValueError("available scalar needs a value")
        if self.status == "PARTIAL" and not self.limitation_codes:
            raise ValueError("partial result needs limits")
        return self
```
其他required types：
- `SiteAnalysisBundle`: schema_version=`site-analysis-bundle-v1`、bundle_ref、study_area_ref、workspace_ref、observations、layer_refs、coverage_refs、created_at、tool_versions。
- `Opportunity`: id、origin=`AI_SUGGESTED|DESIGNER_AUTHORED|RULE_SUGGESTED`、statement、kind=`OBSERVED_PROBLEM|CONDITIONAL_HYPOTHESIS|DESIGN_PREFERENCE`、evidence_refs、scope_ref、suggested_actions、counterexamples、verification_metric_keys、uncertainties。
- `DesignIntent`: id、text、scope_ref、kind=`PREFERENCE|REQUIRED_FEATURE|AVOID_FEATURE`、source_opportunity_ids、origin、priority（使用者可不排序）、version。
- `DesignBriefRevision`: id、revision、parent_ref、workspace_ref、analysis_ref、intents、selected_opportunity_ids、constraint_set_ref（可null）、assumption_refs、required_decision_refs。

所有geo scope採Artifact ref，避免geometry copy與hash脫節。ID是否存在／同project／scope覆蓋／scenario版本／unit與method相符由relationships查backend index，非Schema自己判定。
- [ ] RED tests：null/0區分、另一scenario證據、相同id錯hash、無baseline卻標OBSERVED_PROBLEM。
- [ ] evidence缺比較時可提出CONDITIONAL_HYPOTHESIS，不阻止創作，但不得宣稱測量改善。
- [ ] meaningful relation test：NAIN evidence不能替代distance_m證據；來源scope在基地外不等於基地內數值。
CP-A1：合法JSON但錯語义的反例必須失敗。

## Task A2：既有分析 adapters＋可檢查的 AI 建議

Create `site_intelligence/adapters.py`、`opportunities.py`、`tests/test_site_intelligence_adapters.py`、`tests/test_opportunity_relationships.py`。
Implement `build_analysis_bundle(workspace_ref, source_refs, method_config) -> SiteAnalysisBundle`；只調既有計算／結果loader，parameter/version全保存。
Implement `validate_opportunity(proposal, bundle, resolver) -> Opportunity`；提議生成接既有model adapter，不新增provider SDK。

- [ ] RED：無土地用途資料，不得填「住宅0」；高度未知，不得補3m；syntactic degree1不自動叫死巷。
- [ ] AI input只有typed evidence摘要＋可引用id＋允許action enum，沒有任意SQL/QGIS/python能力。
- [ ] output schema不足／錯refs：一次有界修正機會（預設max_repair=1屬工程配置），仍失敗→INVALID_MODEL_OUTPUT；保留raw structured output與拒絕理由，不保存私有推理。
- [ ] 無provider／budget未授權時保留deterministic圖層與設計者自填入口；UI顯示建議不可用，不能冒充live AI。
- [ ] numeric claims用metric_key引用後由server填值；LLM不得把自己寫的數字當computed result。
- [ ] UI顯示「觀測→解讀→可能措施→需驗證」；適用條件與反例可展开。
CP-A2：使用者看見可追溯設計機會，而非一張只有SWOT形容詞的報告。

## Task A3：可編輯 brief 與局部分區

Create `site_intelligence/brief_service.py`、`api.py`、`tests/test_design_brief.py`；integration owner註冊root api。
Create `web/src/components/SiteOpportunities.tsx`、`DesignBriefPanel.tsx`與同名tests。
Reuse WorkspaceService與既有zones/dispositions UI，不再造一個不會保存的地圖草稿。

Proposed API：
- GET /api/v1/projects/{project_id}/site-intelligence → latest bundle ref/status；不在GET觸發live重算。
- POST /api/v1/projects/{project_id}/analysis-jobs → explicitly requested frozen-input analysis；回job，套用U4 job契約。
- POST /api/v1/projects/{project_id}/design-briefs → draft Artifact＋ledger（不是HumanDecision）。
- GET /api/v1/projects/{project_id}/design-briefs/{brief_id}/revisions/{revision} → immutable payload。

`POST`必帶expected_workspace_revision、input hashes與idempotency key；伺服器從store比對，409 stale，422 invalid ref，不吃client approved flag。
- [ ] RED test：預期rev6但actualrev7→409且無新artifact/ledger；AI送approved_constraint_ids不可自行批准。
- [ ] 自填與AI建議使用同一DesignIntent；用户可修改、刪除、拒絕，保留parent與reason。
- [ ] 畫scope時校驗EPSG:28992、valid polygon、在EDA內；重疊zones需要明示分配policy，不能重複算GFA。
- [ ] 新的REQUIRED_FEATURE可先存草稿；在正式generator前核對它是否需HumanDecision，不以點擊「採用建議」冒充hard constraint批准。
- [ ] 鎖定要素必須引用同source hash；研究preserved清單可作候選overlay，不自動寫入批准處置。
CP-A3：自己寫、AI建議修改、拒絕再選三條都可保存／重載；沒有隱藏權威提升。

## Task A4：分析能否影響後續設計的驗證

Create `tests/test_analysis_to_brief.py`。
Synthetic fixture：200×120m研究矩形，兩個外部路口、中央保留20×20m建築、南側水體；所謂公共通行權用明示fixture tag，不當真實M4H事實。
- [ ] 有waterfront connection intent→brief帶該scope＋entry target refs；無此intent時不強加水岸策略。
- [ ] 證據版本更新→brief analysis refs仍指原版並標stale，不偷偷換新數值。
- [ ] 若使用者堅持與資料相反的偏好，可保留設計偏好，但不能改寫原觀測。
- [ ] 輸出 requirement-to-input matrix，交G3用；G3不得讀markdown問題報告後自由猜幾何。
CP-A4：數據、機會、選擇、generator inputs的鏈可重播。研究範圍內缺資料不是整份brief全停，僅受影響的claim／analysis標缺失。

## 共同執行契約

本文件與 `2026-09-30-site-analysis-generation-master-zh.md` 同版使用。一次只領一個task，先RED再GREEN；原始輸入只讀、每個CP更新shared event。所有新符號／route為planned，既有fixtures成功不代替live驗證。尚未取得main merge／runtime activation批准時，交付reviewable diff，不自行部署。

## A1 最小反例與 exact test command

`tests/test_site_intelligence_contracts.py`：
```python
import pytest
from pydantic import ValidationError
from urban_design.site_intelligence.contracts import Observation

@pytest.mark.parametrize("value", [0.0, 1.0])
def test_blocked_observation_rejects_numeric_value(value):
    ref = {"id": "synthetic-scope", "revision": 1, "sha256": "sha256:" + "a" * 64}
    with pytest.raises(ValidationError):
        Observation(metric_key="synthetic.distance", status="BLOCKED", value=value,
                    unit="m", method_version="fixture-v1", scope_ref=ref,
                    input_refs=(ref,), limitation_codes=("MISSING_INPUT",))
```
Run in WP：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PROJECT/.venv/bin/python" -m pytest -q -p no:cacheprovider tests/test_site_intelligence_contracts.py::test_blocked_observation_rejects_numeric_value`。
預期RED為數值被錯誤接受（初次也可missing symbol），GREEN為兩組case拒絕。另加AVAILABLE=0合法測試，證明沒有把真正零值當缺失。

A1還需建立 `ClaimBinding(metric_key, scope_ref, input_refs, method_version, unit)`；其逐項匹配由relationships完成。Opportunity的自然語言不直接提供數值欄；UI數值僅由有效binding解引用Observation。未知metric_key、換unit未轉換、不同scope、同id錯hash全部拒絕。機會引用分析baseline不等於有改善結果，改善claim須另綁before/after同方法計算。
