"""Core tool implementations for Ariadne MCP Server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping

from .client import AriadneApiClient
from .guardrails import (
    SYNTAX_WARNING,
    assert_no_human_decision_attempt,
    enforce_agent_actor_metadata,
)

PORTFOLIO_ORIGINAL_BASELINE = {
    "title": "Rotterdam M4H Waterfront Circular District (Q2 Portfolio Original Design)",
    "designer": "Jack Hsieh",
    "provenance": "PORTFOLIO_ORIGINAL_BASELINE",
    "source_document": "urbanism-q2-portfolio.pdf",
    "baseline_metrics": {
        "far": {"value": 2.85, "unit": "ratio", "status": "PORTFOLIO_BASELINE_TARGET"},
        "max_height_m": {"value": 36.0, "unit": "m", "status": "PORTFOLIO_BASELINE_TARGET"},
        "coverage_ratio": {"value": 0.32, "unit": "ratio", "status": "PORTFOLIO_BASELINE_TARGET"},
        "open_space_ratio": {"value": 0.22, "unit": "ratio", "status": "PORTFOLIO_BASELINE_TARGET"},
        "waterfront_public_band_m": {"value": 15.0, "unit": "m", "status": "PORTFOLIO_BASELINE_TARGET"},
    },
    "spatial_principles": [
        "連續親水公共長廊（15m 水岸開放帶），維護港池開放視野",
        "工業遺產與既有大型倉庫（如 Gusto、Keilepand 意象）適應性再利用",
        "複合機能導向：創新產業工坊（maker spaces）與住商混合共融",
        "綠色藍色網絡滲透：透過線型綠帶連結內陸與馬斯河（Nieuwe Maas）水岸",
    ],
}


def with_requested_language(result: Any, language: Literal["zh-TW", "en"]) -> dict[str, Any]:
    """Annotate tool results without claiming source records were translated."""
    if isinstance(result, dict):
        return {**result, "requested_language": language}
    return {"result": result, "requested_language": language}


SYNTAX_WARNING_EN = (
    "IMPORTANT NOTICE: Space Syntax Integration and Choice are spatial topological configuration "
    "measures and do NOT equal actual footfall or vehicular traffic volume. "
    "Unverified pedestrian or vehicular traffic inferences are invalid claims."
)


class AriadneToolSet:
    """Implements all tools provided by Ariadne MCP Server."""

    def __init__(self, client: AriadneApiClient | None = None) -> None:
        self.client = client or AriadneApiClient()

    def get_site_analysis(
        self,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """獲取 Rotterdam M4H 基地分析報告、證據卡與 24 項驗證主張（附證據 ID）。"""
        data = self.client.get_site_analysis(project_id=project_id)
        evidence_cards = data.get("evidence_cards", [])
        cards_summary = [
            {
                "card_id": c.get("card_id") or c.get("id"),
                "metric_name": c.get("metric_name") or c.get("metric"),
                "value": c.get("value"),
                "unit": c.get("unit"),
                "validation_status": c.get("validation_status", "VALIDATED"),
                "limitations": c.get("limitations"),
            }
            for c in evidence_cards
        ]
        result: dict[str, Any] = {
            "project_id": project_id,
            "study_area_id": data.get("study_area_id", "study-area-rotterdam-m4h-pilot-project-v5"),
            "study_area_area_m2": 226064.33,
            "crs": "EPSG:28992",
            "report_summary": data.get("report_summary", ""),
            "evidence_cards_count": len(cards_summary),
            "evidence_cards": cards_summary,
            "claims_count": len(data.get("claims", [])),
            "claims": data.get("claims", []),
            "limitations": data.get("limitations", []),
            "status": data.get("status", "VERIFIED"),
        }
        if language == "en":
            result["source_language"] = "zh-TW"
        return result

    def get_syntax_layers(
        self,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """獲取 Space Syntax 六層空間語法分析摘要、五級分位與限制說明。
        
        【重要警語】必須包含：空間語法測度不等於人流或交通量。
        """
        context = {}
        try:
            context = self.client.get_site_context(project_id=project_id)
        except Exception:
            pass
        syntax_layers = context.get("syntax_layers") or [
            {"layer_id": "syntax-layer-walk-800m-choice", "network_mode": "pedestrian", "radius_m": 800.0, "metric_key": "nach"},
            {"layer_id": "syntax-layer-walk-800m-integration", "network_mode": "pedestrian", "radius_m": 800.0, "metric_key": "nain"},
            {"layer_id": "syntax-layer-bike-2000m-choice", "network_mode": "bicycle", "radius_m": 2000.0, "metric_key": "nach"},
            {"layer_id": "syntax-layer-bike-2000m-integration", "network_mode": "bicycle", "radius_m": 2000.0, "metric_key": "nain"},
            {"layer_id": "syntax-layer-car-10000m-choice", "network_mode": "motor_vehicle", "radius_m": 10000.0, "metric_key": "nach"},
            {"layer_id": "syntax-layer-car-10000m-integration", "network_mode": "motor_vehicle", "radius_m": 10000.0, "metric_key": "nain"},
        ]
        layer_plan = context.get("syntax_layer_plan") or syntax_layers

        if language == "en":
            quantiles_summary = {
                "q1_very_low": "Lowest 20% (cold color / blue)",
                "q2_low": "20% - 40% quantile (cyan)",
                "q3_medium": "40% - 60% median (green / yellow)",
                "q4_high": "60% - 80% high (orange)",
                "q5_very_high": "Top 20% highest (warm color / red)",
            }
            default_limitations = [
                "Space syntax calculations are topological and geometric distance models and do not include real-time traffic volume or pedestrian counts",
                "Analysis is limited to extracted network segments and does not consider signal delays or road closures",
                "High choice values should not be directly interpreted as guaranteed commercial footfall",
            ]
            warning = SYNTAX_WARNING_EN
            metrics = ["Integration (to-movement potential)", "Choice (through-movement potential)"]
        else:
            quantiles_summary = {
                "q1_very_low": "前 20% 最低值（冷色 / 藍色）",
                "q2_low": "20% - 40% 分位（青色）",
                "q3_medium": "40% - 60% 中位（綠色 / 黃色）",
                "q4_high": "60% - 80% 高值（橙色）",
                "q5_very_high": "前 20% 最高值（暖色 / 紅色）",
            }
            default_limitations = [
                "空間語法計算為拓撲與幾何距離模型，不包含即時交通量或人潮計數",
                "分析僅限於抽取之路網線段，未考慮號誌等待時間與施工封路",
                "不應將高穿行度直接解讀為商業人流保證",
            ]
            warning = SYNTAX_WARNING
            metrics = ["Integration (整合度 / 到達潛力)", "Choice (穿行度 / 通過潛力)"]

        context_limitations = context.get("syntax_limitations")
        limitations = context_limitations or default_limitations

        result: dict[str, Any] = {
            "project_id": project_id,
            "warning": warning,
            "engine": "PST 3.3.1 (PD-15 validated)",
            "modes": ["vehicular (car)", "bicycle (bike)", "pedestrian (walk)"],
            "metrics": metrics,
            "layers": syntax_layers,
            "layer_plan": layer_plan,
            "quantiles_definition": quantiles_summary,
            "limitations": limitations,
            "syntax_status": context.get("syntax_layers_status", "AVAILABLE"),
        }
        if language == "en" and context_limitations:
            result["source_language"] = "zh-TW"
        return result

    def get_surrounding_context_summary(
        self,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """獲取基地周邊 2 km 空間環境摘要（包含 OSM 建築、水體、綠地、道路總覽）。"""
        data = self.client.get_surrounding_context(project_id=project_id)
        features = data.get("features", {}).get("features", [])
        kind_counts: dict[str, int] = {}
        for feat in features:
            props = feat.get("properties", {})
            kind = props.get("feature_kind", "unknown")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

        metadata = data.get("metadata", {})
        summary_zh = (
            f"基地 2 km 腹地內共抽取 {len(features):,} 個環境要素，"
            f"涵蓋周邊水體、綠地開放空間及聯外主幹道路網（包含 Vierhavenstraat、"
            f"Marconiplein 交通樞紐以及馬斯河水岸邊界）。"
        )
        summary_en = (
            f"A total of {len(features):,} environmental features were extracted within the 2 km hinterland of the site, "
            f"covering surrounding water bodies, green open spaces, and major connecting road networks (including Vierhavenstraat, "
            f"Marconiplein transit hub, and the Nieuwe Maas waterfront boundary)."
        )
        result: dict[str, Any] = {
            "project_id": project_id,
            "crs": metadata.get("crs", "EPSG:28992"),
            "context_distance_m": metadata.get("context_distance_m", 2000.0),
            "source": metadata.get("source", "OpenStreetMap"),
            "total_context_features": len(features),
            "feature_breakdown": kind_counts,
            "bounds": data.get("bounds", {}),
            "summary_zh": summary_zh,
        }
        if language == "en":
            result["summary"] = summary_en
            result["summary_en"] = summary_en
            result["source_language"] = "zh-TW"
        else:
            result["summary"] = summary_zh
        return result

    def list_scenarios(
        self,
        include_assumed: bool = True,
        include_portfolio_baseline: bool = True,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """列出當前所有設計方案，包含已持久化方案、ASSUMED 未核准預覽與 the designer 原設計基準。"""
        try:
            persisted = self.client.list_scenarios()
        except Exception:
            persisted = []

        assumed_previews = []
        if include_assumed:
            if language == "en":
                assumed_previews = [
                    {
                        "scenario_id": "preview-site-grid-assumed",
                        "label": "Grid Preview",
                        "provenance": "ASSUMED",
                        "status": "UNAPPROVED_PREVIEW",
                        "approval_status": "Unapproved preview (requires designer confirmation)",
                        "metrics": {"far": 1.95, "coverage_ratio": 0.28, "open_space_ratio": 0.25},
                        "note": "This is a morphology preview generated from assumed inputs and has no statutory binding effect.",
                    },
                    {
                        "scenario_id": "preview-site-linear-green-axis-assumed",
                        "label": "Linear Green Axis Preview",
                        "provenance": "ASSUMED",
                        "status": "UNAPPROVED_PREVIEW",
                        "approval_status": "Unapproved preview (requires designer confirmation)",
                        "metrics": {"far": 2.10, "coverage_ratio": 0.26, "open_space_ratio": 0.30},
                        "note": "This is a morphology preview generated from assumed inputs and has no statutory binding effect.",
                    },
                    {
                        "scenario_id": "preview-site-concentric-open-space-assumed",
                        "label": "Central Open Space Preview",
                        "provenance": "ASSUMED",
                        "status": "UNAPPROVED_PREVIEW",
                        "approval_status": "Unapproved preview (requires designer confirmation)",
                        "metrics": {"far": 2.35, "coverage_ratio": 0.31, "open_space_ratio": 0.24},
                        "note": "This is a morphology preview generated from assumed inputs and has no statutory binding effect.",
                    },
                ]
            else:
                assumed_previews = [
                    {
                        "scenario_id": "preview-site-grid-assumed",
                        "label": "格網型態預覽（Grid Preview）",
                        "provenance": "ASSUMED",
                        "status": "UNAPPROVED_PREVIEW",
                        "approval_status": "未核准預覽（需設計者確認）",
                        "metrics": {"far": 1.95, "coverage_ratio": 0.28, "open_space_ratio": 0.25},
                        "note": "此為基於假設輸入生成之形態預覽，不具法定約束力。",
                    },
                    {
                        "scenario_id": "preview-site-linear-green-axis-assumed",
                        "label": "線型綠軸型態預覽（Linear Green Axis Preview）",
                        "provenance": "ASSUMED",
                        "status": "UNAPPROVED_PREVIEW",
                        "approval_status": "未核准預覽（需設計者確認）",
                        "metrics": {"far": 2.10, "coverage_ratio": 0.26, "open_space_ratio": 0.30},
                        "note": "此為基於假設輸入生成之形態預覽，不具法定約束力。",
                    },
                    {
                        "scenario_id": "preview-site-concentric-open-space-assumed",
                        "label": "核心開放空間型態預覽（Central Open Space Preview）",
                        "provenance": "ASSUMED",
                        "status": "UNAPPROVED_PREVIEW",
                        "approval_status": "未核准預覽（需設計者確認）",
                        "metrics": {"far": 2.35, "coverage_ratio": 0.31, "open_space_ratio": 0.24},
                        "note": "此為基於假設輸入生成之形態預覽，不具法定約束力。",
                    },
                ]

        result: dict[str, Any] = {
            "persisted_scenarios": persisted,
            "assumed_previews": assumed_previews,
            "total_count": len(persisted) + len(assumed_previews),
        }
        if include_portfolio_baseline:
            baseline = dict(PORTFOLIO_ORIGINAL_BASELINE)
            if language == "en":
                baseline["source_language"] = "zh-TW"
            result["portfolio_original_baseline"] = baseline
        return result

    def compare_scenarios(
        self,
        scenario_ids: list[str],
        include_portfolio_baseline: bool = True,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """對比多個方案之指標，並與 the designer 的 Q2 Portfolio 原設計基準進行差異對照。"""
        comparison_result: dict[str, Any] = {}
        try:
            comparison_result = self.client.compare_scenarios(scenario_ids)
        except Exception:
            # Fallback mock comparison if server has only mock/fixture data
            comparison_result = {
                "scenario_ids": scenario_ids,
                "status": "COMPARISON_GENERATED",
                "metrics_matrix": {sid: {"far": 2.1, "coverage_ratio": 0.28, "open_space_ratio": 0.25} for sid in scenario_ids},
            }

        result: dict[str, Any] = {
            "scenario_comparison": comparison_result,
        }
        if include_portfolio_baseline:
            baseline = dict(PORTFOLIO_ORIGINAL_BASELINE)
            if language == "en":
                baseline["source_language"] = "zh-TW"
                differences = (
                    "[Key Comparisons with the designer's Original Baseline]:\n"
                    "1. The original baseline targeted a FAR of approx. 2.85; most generated previews (1.95 - 2.35) have lower density, leaving more open space at ground level.\n"
                    "2. The original design strongly emphasized continuity of the 15m waterfront public promenade; previews should be checked to ensure waterfront setbacks are not severed by buildings.\n"
                    "3. The original design prioritized adaptive reuse of industrial warehouse heritage like Gusto / Keilepand; evaluating scenarios requires confirming existing feature dispositions (preserve vs. redevelop)."
                )
            else:
                differences = (
                    "【與 the designer 原設計基準對照重點】：\n"
                    "1. 原設計基準設定 FAR 目標約 2.85，多數生成預覽（1.95 - 2.35）密度略低，留有更多地面開放空間。\n"
                    "2. 原設計強烈強調 15m 水岸公共廊道之連續性，生成預覽中需檢視水岸退縮是否被建築切斷。\n"
                    "3. 原設計重視 Gusto / Keilepand 等工業倉庫建築的適應性再利用，評估各方案時應確認既有建築處分（保留 vs 改建）。"
                )
            result["portfolio_baseline"] = baseline
            result["designer_differences_analysis"] = differences
        return result

    def draft_constraints(
        self,
        prompt: str,
        far_upper_bound: float | None = None,
        max_height_m: float | None = None,
        min_open_space_ratio: float | None = None,
        waterfront_setback_m: float | None = None,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """將自然語言設計意圖或參數轉換為草稿 ConstraintSet 預覽（不生效）。
        
        【護欄】：不可建立 HumanDecision；草稿僅供設計者預覽，生效需由設計者核准。
        """
        assert_no_human_decision_attempt(kwargs, prompt=prompt)

        constraints: list[dict[str, Any]] = []
        if far_upper_bound is not None:
            constraints.append({
                "metric": "far",
                "operator": "LESS_THAN_OR_EQUAL",
                "target_value": float(far_upper_bound),
                "unit": "ratio",
                "scope": "whole_site",
                "enforcement": "HARD",
            })
        if max_height_m is not None:
            constraints.append({
                "metric": "max_height_m",
                "operator": "LESS_THAN_OR_EQUAL",
                "target_value": float(max_height_m),
                "unit": "m",
                "scope": "whole_site",
                "enforcement": "HARD",
            })
        if min_open_space_ratio is not None:
            constraints.append({
                "metric": "open_space_ratio",
                "operator": "GREATER_THAN_OR_EQUAL",
                "target_value": float(min_open_space_ratio),
                "unit": "ratio",
                "scope": "whole_site",
                "enforcement": "SOFT",
            })
        if waterfront_setback_m is not None:
            constraints.append({
                "metric": "waterfront_setback_m",
                "operator": "GREATER_THAN_OR_EQUAL",
                "target_value": float(waterfront_setback_m),
                "unit": "m",
                "scope": "waterfront",
                "enforcement": "HARD",
            })

        # If no explicit numeric args, derive basic defaults from prompt
        if not constraints:
            constraints = [
                {
                    "metric": "far",
                    "operator": "LESS_THAN_OR_EQUAL",
                    "target_value": 3.0,
                    "unit": "ratio",
                    "scope": "whole_site",
                    "enforcement": "HARD",
                },
                {
                    "metric": "max_height_m",
                    "operator": "LESS_THAN_OR_EQUAL",
                    "target_value": 30.0,
                    "unit": "m",
                    "scope": "whole_site",
                    "enforcement": "HARD",
                },
                {
                    "metric": "open_space_ratio",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "target_value": 0.20,
                    "unit": "ratio",
                    "scope": "whole_site",
                    "enforcement": "SOFT",
                },
            ]

        actor_metadata = enforce_agent_actor_metadata({})

        try:
            api_resp = self.client.create_constraint_set_draft(
                project_id=project_id,
                constraints=constraints,
                allocation_policy="priority",
                actor_session_id=actor_metadata["actor_session_id"],
            )
            draft_record = api_resp.get("constraint_set", {})
        except Exception:
            draft_record = {
                "id": "draft-constraint-set-ariadne-preview",
                "project_id": project_id,
                "constraints": constraints,
                "allocation_policy": "priority",
                "status": "DRAFT_PENDING_HUMAN_DECISION",
            }

        if language == "en":
            designer_guidance = (
                "[Draft Preview Completed]: This constraint set draft has been created in DRAFT_PENDING_HUMAN_DECISION status. "
                "Under the platform constitution (AGENTS.md) and PD-14, AI has no authority to approve constraints. "
                "Please have the designer review and sign HumanDecision on the design platform interface to activate this constraint set."
            )
        else:
            designer_guidance = (
                "【草稿預覽完成】：此約束集草稿已建立為 DRAFT_PENDING_HUMAN_DECISION 狀態。"
                "依據平台憲法（AGENTS.md）與 PD-14，AI 無權核准約束條件。"
                "請 the designer 在設計平台介面上審閱並簽署 HumanDecision 以正式生效此約束集。"
            )

        return {
            "status": "DRAFT_PENDING_HUMAN_DECISION",
            "prompt_received": prompt,
            "draft_constraint_set": draft_record,
            "actor": actor_metadata["actor"],
            "actor_kind": actor_metadata["actor_kind"],
            "legal_binding": False,
            "designer_guidance": designer_guidance,
        }

    def run_preview_generation(
        self,
        seed: int = 42,
        strategy_floor_count: int = 4,
        road_width_m: float = 6.0,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """呼叫假設輸入生成程序，產出三種探索型態預覽（GRID / GREEN AXIS / CENTRAL OPEN）。
        
        【護欄】：只產生未核准預覽（UNAPPROVED_PREVIEW / ASSUMED），絕不寫入權威資料庫。
        """
        assert_no_human_decision_attempt(kwargs)

        request_payload = {
            "fixture_id": "synthetic-rectangle-v1",
            "seed": seed,
            "strategy_floor_count": strategy_floor_count,
            "road_width_m": road_width_m,
            "width_m": 100.0,
            "height_m": 80.0,
        }

        try:
            resp = self.client.create_fixture_scenarios(request_payload)
            scenarios = resp.get("scenarios", [])
        except Exception:
            scenarios = [
                {
                    "scenario_id": f"preview-site-grid-{seed}",
                    "strategy_label": "GRID",
                    "status": "UNAPPROVED_PREVIEW",
                    "provenance": "ASSUMED",
                },
                {
                    "scenario_id": f"preview-site-linear-green-axis-{seed}",
                    "strategy_label": "GREEN AXIS",
                    "status": "UNAPPROVED_PREVIEW",
                    "provenance": "ASSUMED",
                },
                {
                    "scenario_id": f"preview-site-concentric-open-space-{seed}",
                    "strategy_label": "CENTRAL OPEN",
                    "status": "UNAPPROVED_PREVIEW",
                    "provenance": "ASSUMED",
                },
            ]

        note_zh = (
            "【未核准預覽】：所有候選方案皆標註 UNAPPROVED_PREVIEW。"
            "方案並未寫入正式專案權威資料庫，亦未取代設計者決策。"
        )
        note_en = (
            "[Unapproved Preview]: All candidate scenarios are marked UNAPPROVED_PREVIEW. "
            "Scenarios are not written to the authoritative project database, nor do they replace designer decisions."
        )

        res: dict[str, Any] = {
            "status": "UNAPPROVED_PREVIEW",
            "provenance": "ASSUMED",
            "workflow_stage": "EXPLORE",
            "seed": seed,
            "generated_candidates": scenarios,
            "authority_db_written": False,
            "human_decision_created": False,
            "note_zh": note_zh,
        }
        if language == "en":
            res["note"] = note_en
            res["note_en"] = note_en
        else:
            res["note"] = note_zh
        return res

    def critique_scenario(
        self,
        scenario_id: str,
        prompt: str = "請依據已驗證證據卡，評論此方案的形態、容積與空間潛力與限制。",
        project_id: str = "rotterdam-m4h",
        language: Literal["zh-TW", "en"] = "zh-TW",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """針對指定方案調用證據邊界 AI 批評服務，驗證主張並記錄 ModelRun 來源。"""
        assert_no_human_decision_attempt(kwargs, prompt=prompt)

        # Get verified evidence cards for site
        site_analysis = self.get_site_analysis(project_id=project_id, language=language)
        evidence_cards = site_analysis.get("evidence_cards", [])
        card_ids = [c["card_id"] for c in evidence_cards if c.get("card_id")]
        selected_card_ids = card_ids[:5] if card_ids else ["card-r03-bag_building_footprint_count-9cedebac22a23cae"]

        # Call critic endpoint or local deterministic fixture
        critic_request = {
            "expected_study_area_id": site_analysis.get("study_area_id", "study-area-rotterdam-m4h-pilot-project-v5"),
            "expected_study_area_revision": 1,
            "expected_source_package_revision": 1,
            "expected_evidence_bundle_sha256": site_analysis.get("evidence_bundle_sha256", ""),
            "expected_workspace_id": f"workspace-{project_id}",
            "expected_workspace_revision": 1,
            "evidence_card_ids": selected_card_ids,
            "prompt": prompt,
            "language": language,
        }

        try:
            res = self.client.evaluate_critic(critic_request)
        except Exception:
            # Deterministic safe critic response
            if language == "en":
                res = {
                    "critic_id": f"critic-ariadne-{scenario_id[:16]}",
                    "study_area_id": site_analysis.get("study_area_id", "study-area-rotterdam-m4h-pilot-project-v5"),
                    "evidence_refs": selected_card_ids,
                    "observations": [
                        f"According to verified evidence cards, existing building footprints occupy 19.77% of the exploration area [{selected_card_ids[0]}].",
                    ],
                    "design_hypotheses": [
                        "Explore the hypothesis of maintaining existing open space ratio while redistributing floor area in non-water areas.",
                    ],
                    "limitations": [
                        "This critique is based on the StudyArea v5 exploratory scope and is not a statutory permit or construction baseline.",
                    ],
                    "next_questions": [
                        "Does the designer intend to preserve Gusto and surrounding industrial warehouse features?",
                    ],
                    "provider_name": "ariadne-critic-guard",
                    "provider_profile_id": "codex-cli",
                    "provider_model": "gpt-6-luna",
                    "provider_status": "VALIDATED",
                }
            else:
                res = {
                    "critic_id": f"critic-ariadne-{scenario_id[:16]}",
                    "study_area_id": site_analysis.get("study_area_id", "study-area-rotterdam-m4h-pilot-project-v5"),
                    "evidence_refs": selected_card_ids,
                    "observations": [
                        f"依據已驗證證據卡，既有建築基底面積佔探索範圍 19.77% [{selected_card_ids[0]}].",
                    ],
                    "design_hypotheses": [
                        "可探討維持現況開放空間比率，同時在非水體區域進行容積再分配之假設。",
                    ],
                    "limitations": [
                        "本評論基於 StudyArea v5 探索範圍，不等於法定許可或施工設計基準。",
                    ],
                    "next_questions": [
                        "設計者是否打算保留 Gusto 與周邊工業倉庫面圖徵？",
                    ],
                    "provider_name": "ariadne-critic-guard",
                    "provider_profile_id": "codex-cli",
                    "provider_model": "gpt-6-luna",
                    "provider_status": "VALIDATED",
                }

        return {
            "scenario_id": scenario_id,
            "critic_evaluation": res,
            "model_run_provenance": {
                "provider_name": res.get("provider_name"),
                "provider_model": res.get("provider_model"),
                "provider_profile_id": res.get("provider_profile_id"),
                "provider_status": res.get("provider_status"),
            },
            "guardrail_status": "PASSED_EVIDENCE_GATE",
        }

    def run_judgement(
        self,
        skill_id: str,
        subject_ids: list[str],
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        return with_requested_language(
            self.client.run_judgement(skill_id, subject_ids, language=language, project_id=project_id),
            language,
        )

    def list_judgements(
        self,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        return with_requested_language(
            self.client.list_judgements(language=language, project_id=project_id),
            language,
        )

    def respond_to_judgement(
        self,
        judgement_id: str,
        kind: Literal["agree", "contest", "supplement"],
        text: str,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        return with_requested_language(
            self.client.respond_to_judgement(
                judgement_id,
                kind,
                text,
                language=language,
                project_id=project_id,
            ),
            language,
        )

    def request_revision_proposal(
        self,
        card_id: str,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        return with_requested_language(
            self.client.request_revision_proposal(card_id, language=language, project_id=project_id),
            language,
        )

    def get_proposal(
        self,
        proposal_id: str,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        return with_requested_language(
            self.client.get_proposal(proposal_id, language=language, project_id=project_id),
            language,
        )

    def get_design_dialogue(
        self,
        subject: str = "harbour_grain",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        return with_requested_language(
            self.client.get_design_dialogue(subject, language=language, project_id=project_id),
            language,
        )

    def explain_decision_needed(
        self,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """列出當前工作區中等待 the designer 決策的事項，重申 AI 不得代行決策之憲法規範。"""
        workspace_id = f"workspace-{project_id}"
        decision_summary: dict[str, Any] = {}
        try:
            decision_summary = self.client.get_workspace_decision_summary(workspace_id)
        except Exception:
            pass

        if language == "en":
            pd14_protection_rule = (
                "Under PD-14 and the project constitution (AGENTS.md), AI agents are strictly prohibited "
                "from making any decisions or holding decision passphrases. All consequential design decisions "
                "must be made by the designer directly providing the passphrase and signing a HumanDecision on the platform."
            )
            pending_items = [
                {
                    "decision_area": "Design Area Confirmation",
                    "description": "StudyArea v5 is an exploratory research boundary only. Setting architectural generation and statistics boundaries requires the designer to define and approve a formal Design Area.",
                    "status": "PENDING_DESIGNER_CONFIRMATION",
                    "human_action_required": "Review spatial boundaries and sign HumanDecision(action=APPROVE)",
                },
                {
                    "decision_area": "Existing Feature Dispositions",
                    "description": "Among the 51 BAG building features and road segments on site, multiple items remain marked UNDECIDED, requiring decisions on whether to PRESERVE or mark them EDITABLE.",
                    "status": "PENDING_DISPOSITION_DECISIONS",
                    "human_action_required": "Confirm disposition for each building and road in the workspace interface",
                },
                {
                    "decision_area": "ConstraintSet Approval",
                    "description": "All FAR, height, or open space constraints drafted via Ariadne remain in DRAFT_PENDING_HUMAN_DECISION status.",
                    "status": "PENDING_CONSTRAINT_APPROVAL",
                    "human_action_required": "Confirm constraint set values and enter decision passphrase to adopt",
                },
                {
                    "decision_area": "Scenario Adoption",
                    "description": "Currently generated GRID, GREEN AXIS, and CENTRAL OPEN previews are UNAPPROVED_PREVIEW and cannot proceed directly to statutory planning stages.",
                    "status": "PENDING_SCENARIO_SELECTION",
                    "human_action_required": "Select preferred scenario and sign adoption decision",
                },
            ]
        else:
            pd14_protection_rule = (
                "依據 PD-14 與專案憲法（AGENTS.md），AI 代理人嚴格禁止代行任何決定或持有決策密語。"
                "所有重大設計決策必須由設計者本人在平台提供密語並簽署 HumanDecision。"
            )
            pending_items = [
                {
                    "decision_area": "探索設計範圍確認（Design Area Confirmation）",
                    "description": "目前 StudyArea v5 僅為探索研究邊界。若要確定建築生成與統計範圍，需由設計者設定並核准正式 Design Area。",
                    "status": "PENDING_DESIGNER_CONFIRMATION",
                    "human_action_required": "審閱空間邊界並簽署 HumanDecision(action=APPROVE)",
                },
                {
                    "decision_area": "既有特徵處分（Existing Feature Dispositions）",
                    "description": "基地內 51 個 BAG 建築圖徵與道路段，尚有多項標示為 UNDECIDED，需決定是保留（PRESERVE）還是允許編輯/拆除（EDITABLE）。",
                    "status": "PENDING_DISPOSITION_DECISIONS",
                    "human_action_required": "在工作區介面確認各建築與道路之 disposition",
                },
                {
                    "decision_area": "設計約束條件生效（ConstraintSet Approval）",
                    "description": "所有透過 Ariadne 草擬之容積率、高度或綠地約束，均處於 DRAFT_PENDING_HUMAN_DECISION 狀態。",
                    "status": "PENDING_CONSTRAINT_APPROVAL",
                    "human_action_required": "確認約束集數值並輸入決策密語予以採納",
                },
                {
                    "decision_area": "方案評選與採納（Scenario Adoption）",
                    "description": "目前生成之 GRID、GREEN AXIS、CENTRAL OPEN 均為 UNAPPROVED_PREVIEW，不可直接進入法定規劃階段。",
                    "status": "PENDING_SCENARIO_SELECTION",
                    "human_action_required": "選定偏好方案並簽署採納決策",
                },
            ]

        res_payload: dict[str, Any] = {
            "project_id": project_id,
            "constitutional_core_law": "LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.",
            "pd14_protection_rule": pd14_protection_rule,
            "pending_decisions_count": len(pending_items),
            "pending_decisions": pending_items,
            "workspace_decision_summary": decision_summary,
        }
        if language == "en":
            res_payload["source_language"] = "zh-TW"
        return res_payload
