"""Core tool implementations for Ariadne MCP Server."""

from __future__ import annotations

import math
from typing import Any, Literal, Mapping

import httpx

from .baseline import PORTFOLIO_ORIGINAL_BASELINE
from .client import AriadneApiClient
from .guardrails import (
    SYNTAX_WARNING,
    assert_no_human_decision_attempt,
    enforce_agent_actor_metadata,
)

ANALYSIS_RADII_M = {
    "pedestrian": 800.0,
    "bicycle": 2000.0,
    "motor_vehicle": 10000.0,
}


def _unavailable_for_exception(exc: Exception) -> dict[str, str]:
    """Return a short, non-sensitive diagnostic for a failed platform call."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            reason = "The requested platform record was not found (HTTP 404)."
        else:
            reason = f"The platform API returned HTTP {code}."
    elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        reason = "The platform API request timed out."
    elif isinstance(exc, (httpx.ConnectError, ConnectionError)):
        reason = "The platform API connection failed."
    else:
        reason = "The platform API request failed."
    return {"status": "UNAVAILABLE", "error_class": type(exc).__name__, "reason": reason}


def _missing_record(reason: str) -> dict[str, str]:
    return {"status": "UNAVAILABLE", "error_class": "MissingRecordError", "reason": reason}


def _unavailable_response(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or value.get("status") != "UNAVAILABLE":
        return None
    result = dict(value)
    result["error_class"] = str(result.get("error_class") or "PlatformApiError")
    result["reason"] = str(result.get("reason") or "The platform API record is unavailable.")
    return result


def _comparable_far_differences(
    comparison: Mapping[str, Any],
    scenario_ids: list[str],
    baseline_metrics: Mapping[str, Any],
) -> dict[str, tuple[float, float]]:
    """Return FAR observations and deltas only for comparable land-area rows."""
    if comparison.get("status") != "COMPARABLE":
        return {}
    baseline_far = baseline_metrics.get("far")
    if not isinstance(baseline_far, Mapping) or baseline_far.get("denominator") != "land_area":
        return {}
    baseline_value = baseline_far.get("value")
    if isinstance(baseline_value, bool) or not isinstance(baseline_value, (int, float)):
        return {}
    if not math.isfinite(float(baseline_value)):
        return {}

    metric_rows = comparison.get("metrics")
    if not isinstance(metric_rows, list):
        return {}
    far_row = next(
        (
            row for row in metric_rows
            if isinstance(row, Mapping)
            and row.get("metric_id") == "far"
            and row.get("status") == "COMPARABLE"
        ),
        None,
    )
    if far_row is None:
        return {}
    values = far_row.get("values")
    denominators = far_row.get("denominators")
    validation_status = far_row.get("validation_status")
    if (
        not isinstance(values, Mapping)
        or not isinstance(denominators, Mapping)
        or not isinstance(validation_status, Mapping)
    ):
        return {}

    result: dict[str, tuple[float, float]] = {}
    for scenario_id in scenario_ids:
        value = values.get(scenario_id)
        denominator = denominators.get(scenario_id)
        if validation_status.get(scenario_id) != "VALIDATED":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            continue
        if not isinstance(denominator, Mapping):
            continue
        label = denominator.get("label")
        if not isinstance(label, str) or label.strip().casefold().replace(" ", "_") != "land_area":
            continue
        value = float(value)
        result[scenario_id] = (value, value - float(baseline_value))
    return result


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

    def _call_client(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            value = getattr(self.client, method_name)(*args, **kwargs)
        except Exception as exc:
            return _unavailable_for_exception(exc)
        unavailable = _unavailable_response(value)
        return unavailable if unavailable is not None else value

    def get_site_analysis(
        self,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """獲取平台目前已驗證的基地分析記錄與證據卡。"""
        data = self._call_client("get_site_analysis", project_id=project_id)
        unavailable = _unavailable_response(data)
        if unavailable is not None:
            return with_requested_language({**unavailable, "project_id": project_id}, language)
        if not isinstance(data, Mapping):
            return with_requested_language(
                {**_missing_record("The site-analysis response is not a record."), "project_id": project_id},
                language,
            )

        evidence_cards = data.get("evidence_cards")
        claims = data.get("claims")
        area_m2 = data.get("study_area_area_m2")
        study_area_id = data.get("study_area_id")
        report_summary = data.get("report_summary")
        if (
            data.get("evidence_cards_status") != "VERIFIED_SOURCE_RESULT_ALIGNMENT"
            or not isinstance(evidence_cards, list)
            or not evidence_cards
            or not isinstance(claims, list)
            or not claims
            or not isinstance(study_area_id, str)
            or not study_area_id.strip()
            or isinstance(area_m2, bool)
            or not isinstance(area_m2, (int, float))
            or not math.isfinite(float(area_m2))
            or float(area_m2) <= 0
            or not isinstance(report_summary, str)
            or not report_summary.strip()
            or not isinstance(data.get("status"), str)
        ):
            return with_requested_language(
                {
                    **_missing_record("Current verified site-analysis records are incomplete or unavailable."),
                    "project_id": project_id,
                },
                language,
            )

        cards_summary = []
        for card in evidence_cards:
            if not isinstance(card, Mapping):
                return with_requested_language(
                    {
                        **_missing_record("A site-analysis Evidence Card record is invalid."),
                        "project_id": project_id,
                    },
                    language,
                )
            card_id = card.get("card_id") or card.get("id")
            metric_name = card.get("metric_name") or card.get("metric")
            if not card_id or not metric_name:
                return with_requested_language(
                    {
                        **_missing_record("A site-analysis Evidence Card is missing its ID or metric."),
                        "project_id": project_id,
                    },
                    language,
                )
            cards_summary.append({
                "card_id": card_id,
                "metric_name": metric_name,
                "value": card.get("value"),
                "unit": card.get("unit"),
                "validation_status": card.get("validation_status"),
                "limitations": card.get("limitations"),
            })

        result: dict[str, Any] = {
            "project_id": project_id,
            "study_area_id": study_area_id,
            "study_area_area_m2": area_m2,
            "crs": data.get("crs"),
            "study_area_revision": data.get("study_area_revision"),
            "source_package_revision": data.get("source_package_revision"),
            "evidence_bundle_sha256": data.get("evidence_bundle_sha256"),
            "report_summary": report_summary,
            "evidence_cards_count": len(cards_summary),
            "evidence_cards": cards_summary,
            "claims_count": len(claims),
            "claims": claims,
            "limitations": data.get("limitations", []),
            "status": data.get("status"),
        }
        if language == "en":
            result["source_language"] = data.get("source_language") or "zh-TW"
        return result

    def get_syntax_layers(
        self,
        project_id: str = "rotterdam-m4h",
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
    ) -> dict[str, Any]:
        """獲取平台目前的 Space Syntax 結果、五級分位與限制說明。
        
        【重要警語】必須包含：空間語法測度不等於人流或交通量。
        """
        context = self._call_client("get_site_context", project_id=project_id)
        failure = _unavailable_response(context)
        if failure is None and not isinstance(context, Mapping):
            failure = _missing_record("The syntax response is not a site-context record.")
        syntax_layers = context.get("syntax_layers") if isinstance(context, Mapping) else None
        syntax_status = context.get("syntax_layers_status") if isinstance(context, Mapping) else None
        if failure is None and (
            not isinstance(syntax_layers, list)
            or not syntax_layers
            or syntax_status in (None, "NOT_COMPUTED", "UNAVAILABLE")
        ):
            failure = _missing_record("No current Space Syntax result record is available.")

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

        context_limitations = context.get("syntax_limitations") if isinstance(context, Mapping) else None
        limitations = context_limitations or default_limitations

        if failure is not None:
            result: dict[str, Any] = {
                **failure,
                "project_id": project_id,
                "warning": warning,
                "analysis_radii_m": dict(ANALYSIS_RADII_M),
                "quantiles_definition": quantiles_summary,
                "metrics": metrics,
                "limitations": limitations,
            }
            if language == "en" and context_limitations:
                result["source_language"] = "zh-TW"
            return result

        result: dict[str, Any] = {
            "project_id": project_id,
            "warning": warning,
            "analysis_radii_m": dict(ANALYSIS_RADII_M),
            "engine": context.get("syntax_engine"),
            "modes": ["vehicular (car)", "bicycle (bike)", "pedestrian (walk)"],
            "metrics": metrics,
            "layers": syntax_layers,
            "layer_plan": context.get("syntax_layer_plan", []),
            "quantiles_definition": quantiles_summary,
            "limitations": limitations,
            "syntax_status": syntax_status,
            "status": syntax_status,
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
        data = self._call_client("get_surrounding_context", project_id=project_id)
        unavailable = _unavailable_response(data)
        if unavailable is not None:
            return with_requested_language({**unavailable, "project_id": project_id}, language)
        if not isinstance(data, Mapping):
            return with_requested_language(
                {**_missing_record("The surrounding-context response is not a record."), "project_id": project_id},
                language,
            )
        metadata = data.get("metadata")
        layers = data.get("layers")
        expected_layers = ("buildings", "water", "green", "roads")
        if not isinstance(metadata, Mapping) or not isinstance(layers, Mapping):
            return with_requested_language(
                {**_missing_record("Surrounding-context metadata or layer records are missing."), "project_id": project_id},
                language,
            )
        kind_counts: dict[str, int] = {}
        for layer_name in expected_layers:
            layer = layers.get(layer_name)
            features = layer.get("features") if isinstance(layer, Mapping) else None
            if not isinstance(features, list):
                return with_requested_language(
                    {**_missing_record(f"The surrounding-context {layer_name} layer record is missing."), "project_id": project_id},
                    language,
                )
            kind_counts[layer_name] = len(features)
        total_features = sum(kind_counts.values())
        summary_zh = (
            f"周邊環境記錄包含 {total_features:,} 個圖徵：建築 {kind_counts['buildings']:,}、"
            f"水體 {kind_counts['water']:,}、綠地 {kind_counts['green']:,}、道路 {kind_counts['roads']:,}。"
        )
        summary_en = (
            f"The surrounding-context record contains {total_features:,} features: "
            f"{kind_counts['buildings']:,} buildings, {kind_counts['water']:,} water features, "
            f"{kind_counts['green']:,} green features, and {kind_counts['roads']:,} roads."
        )
        result: dict[str, Any] = {
            "project_id": project_id,
            "crs": metadata.get("crs"),
            "context_distance_m": metadata.get("context_distance_m"),
            "source": metadata.get("source"),
            "total_context_features": total_features,
            "feature_breakdown": kind_counts,
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
        """列出已持久化方案、平台形態方案與 the designer 原設計基準。"""
        persisted = self._call_client("list_scenarios")
        failure = _unavailable_response(persisted)
        if failure is not None:
            result: dict[str, Any] = {**failure, "persisted_scenarios": [], "assumed_previews": [], "total_count": 0}
            if include_portfolio_baseline:
                baseline = dict(PORTFOLIO_ORIGINAL_BASELINE)
                if language == "en":
                    baseline["source_language"] = "zh-TW"
                result["portfolio_original_baseline"] = baseline
            return result
        if not isinstance(persisted, list):
            return _missing_record("The scenario list response is not a record list.")

        assumed_previews = []
        failure = None
        if include_assumed:
            catalog = self._call_client("list_fabric_plans")
            failure = _unavailable_response(catalog)
            if failure is None and (
                not isinstance(catalog, Mapping)
                or catalog.get("status") != "EXPLORATORY_DRAFT"
                or not isinstance(catalog.get("plans"), list)
            ):
                failure = _missing_record("The fabric-plan catalog record is missing or invalid.")
            if failure is None:
                for plan in catalog["plans"]:
                    if (
                        not isinstance(plan, Mapping)
                        or not isinstance(plan.get("fabric_id"), str)
                        or not isinstance(plan.get("label_zh"), str)
                        or not isinstance(plan.get("metrics"), Mapping)
                    ):
                        failure = _missing_record("A fabric-plan record is missing required fields.")
                        assumed_previews = []
                        break
                    preview = {
                        "scenario_id": plan["fabric_id"],
                        "fabric_id": plan["fabric_id"],
                        "label": plan["label_zh"],
                        "label_zh": plan["label_zh"],
                        "provenance": "PLATFORM_FABRIC_PLAN_API",
                        "status": catalog["status"],
                        "metrics": plan["metrics"],
                    }
                    if language == "en":
                        preview["source_language"] = "zh-TW"
                    assumed_previews.append(preview)

        result: dict[str, Any] = {
            "persisted_scenarios": persisted,
            "assumed_previews": assumed_previews,
            "total_count": len(persisted) + len(assumed_previews),
            "status": "AVAILABLE" if failure is None else failure["status"],
        }
        if failure is not None:
            result.update({key: value for key, value in failure.items() if key != "status"})
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
        comparison_result = self._call_client("compare_scenarios", scenario_ids)
        failure = _unavailable_response(comparison_result)
        if failure is None and not isinstance(comparison_result, Mapping):
            failure = _missing_record("The scenario comparison response is not a record.")
            comparison_result = failure
        elif failure is not None:
            comparison_result = {**failure, "scenario_ids": scenario_ids}

        result: dict[str, Any] = {
            "scenario_comparison": comparison_result,
            "status": "UNAVAILABLE" if failure is not None else "AVAILABLE",
        }
        if failure is not None:
            result["error_class"] = failure["error_class"]
            result["reason"] = failure["reason"]
        if include_portfolio_baseline:
            baseline = dict(PORTFOLIO_ORIGINAL_BASELINE)
            baseline_far_value = baseline["baseline_metrics"]["far"]["value"]
            far_differences = _comparable_far_differences(
                comparison_result,
                scenario_ids,
                baseline["baseline_metrics"],
            )
            if language == "en":
                baseline["source_language"] = "zh-TW"
                if far_differences:
                    far_summary = "; ".join(
                        f"{scenario_id}: {value:.3f} ({difference:+.3f} vs. {baseline_far_value:.3f})"
                        for scenario_id, (value, difference) in far_differences.items()
                    )
                    far_comparison = f"1. Comparable FAR values using the land-area denominator versus the portfolio baseline ({baseline_far_value:.3f}): {far_summary}."
                else:
                    far_comparison = "1. No comparable FAR values using the land-area denominator are available, so no numeric difference is reported."
                differences = "\n".join((
                    "[Key Comparisons with the designer's Original Baseline]:",
                    far_comparison,
                    "2. Check whether each plan maintains a continuous 15 m waterfront public band and an unobstructed public route.",
                    "3. The original design prioritized adaptive reuse of industrial warehouse heritage like Gusto / Keilepand; confirm whether existing features are preserved or redeveloped in each plan.",
                ))
            else:
                if far_differences:
                    far_summary = "；".join(
                        f"{scenario_id}：{value:.3f}（相較 {baseline_far_value:.3f} 為 {difference:+.3f}）"
                        for scenario_id, (value, difference) in far_differences.items()
                    )
                    far_comparison = f"1. FAR（基地陸地面積分母）相較作品集基準（{baseline_far_value:.3f}）：{far_summary}。"
                else:
                    far_comparison = "1. 目前沒有使用基地陸地面積分母且可比較的 FAR 數值，因此不提供數值差異。"
                differences = "\n".join((
                    "【與 the designer 原設計基準對照重點】：",
                    far_comparison,
                    "2. 請檢視各方案是否維持連續的 15m 水岸公共帶與不受阻的公共通行路徑。",
                    "3. 原設計重視 Gusto / Keilepand 等工業倉庫建築的適應性再利用；請確認各方案對既有建物採保留或改建。",
                ))
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

        supplied_parameters = {
            "far_upper_bound": far_upper_bound,
            "max_height_m": max_height_m,
            "min_open_space_ratio": min_open_space_ratio,
            "waterfront_setback_m": waterfront_setback_m,
        }
        parameters = {
            name: {
                "value": float(value) if value is not None else None,
                "status": "SPECIFIED" if value is not None else "NOT_SPECIFIED",
            }
            for name, value in supplied_parameters.items()
        }

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

        if not constraints:
            if language == "en":
                designer_guidance = (
                    "No constraint values were supplied. Provide the required parameter values before creating a draft; "
                    "unspecified parameters remain NOT_SPECIFIED and do not activate any constraint."
                )
            else:
                designer_guidance = (
                    "尚未提供約束數值。建立草稿前請補上所需參數；未提供的參數維持 NOT_SPECIFIED，且不會生效。"
                )
            return {
                "status": "NOT_SPECIFIED",
                "prompt_received": prompt,
                "parameters": parameters,
                "draft_constraint_set": {
                    "project_id": project_id,
                    "constraints": [],
                    "parameters": parameters,
                    "status": "NOT_SPECIFIED",
                },
                "actor": "agent-ariadne",
                "actor_kind": "AGENT_AUTOMATION",
                "legal_binding": False,
                "designer_guidance": designer_guidance,
            }

        actor_metadata = enforce_agent_actor_metadata({})
        api_resp = self._call_client(
            "create_constraint_set_draft",
            project_id=project_id,
            constraints=constraints,
            allocation_policy="priority",
            actor_session_id=actor_metadata["actor_session_id"],
        )
        failure = _unavailable_response(api_resp)
        if failure is not None:
            return {
                **failure,
                "project_id": project_id,
                "prompt_received": prompt,
                "parameters": parameters,
                "actor": actor_metadata["actor"],
                "actor_kind": actor_metadata["actor_kind"],
                "legal_binding": False,
            }
        draft_record = api_resp.get("constraint_set") if isinstance(api_resp, Mapping) else None
        if (
            not isinstance(draft_record, Mapping)
            or not isinstance(draft_record.get("id"), str)
            or not isinstance(draft_record.get("status"), str)
        ):
            return {
                **_missing_record("The platform did not return a ConstraintSet draft record."),
                "project_id": project_id,
                "prompt_received": prompt,
                "parameters": parameters,
                "actor": actor_metadata["actor"],
                "actor_kind": actor_metadata["actor_kind"],
                "legal_binding": False,
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
            "status": draft_record["status"],
            "prompt_received": prompt,
            "parameters": parameters,
            "draft_constraint_set": {**dict(draft_record), "parameters": parameters},
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
        """以標記為合成測試輸入的幾何參數請求探索型態預覽。
        
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

        preview_inputs = {**request_payload, "status": "SYNTHETIC_TEST_INPUT"}
        response = self._call_client("create_fixture_scenarios", request_payload)
        failure = _unavailable_response(response)
        if failure is not None:
            return {**failure, "project_id": project_id, "preview_inputs": preview_inputs}
        scenarios = response.get("scenarios") if isinstance(response, Mapping) else None
        if not isinstance(scenarios, list):
            return {
                **_missing_record("The platform did not return a preview scenario list."),
                "project_id": project_id,
                "preview_inputs": preview_inputs,
            }

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
            "provenance": "SYNTHETIC_TEST_INPUT",
            "workflow_stage": "EXPLORE",
            "preview_inputs": preview_inputs,
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

        site_analysis = self.get_site_analysis(project_id=project_id, language=language)
        site_failure = _unavailable_response(site_analysis)
        if site_failure is not None:
            return {**site_failure, "scenario_id": scenario_id}
        evidence_cards = site_analysis.get("evidence_cards", [])
        card_ids = [c["card_id"] for c in evidence_cards if c.get("card_id")]
        if not card_ids:
            return {
                **_missing_record("No current verified Evidence Card IDs are available for critique."),
                "scenario_id": scenario_id,
            }
        selected_card_ids = card_ids[:5]

        decision_summary = self._call_client("get_workspace_decision_summary", f"workspace-{project_id}")
        summary_failure = _unavailable_response(decision_summary)
        if summary_failure is not None:
            return {**summary_failure, "scenario_id": scenario_id}
        if not isinstance(decision_summary, Mapping):
            return {
                **_missing_record("The current workspace summary is missing."),
                "scenario_id": scenario_id,
            }
        workspace_id = decision_summary.get("workspace_id")
        workspace_revision = decision_summary.get("revision")
        study_area_revision = site_analysis.get("study_area_revision")
        source_package_revision = site_analysis.get("source_package_revision")
        evidence_bundle_sha256 = site_analysis.get("evidence_bundle_sha256")
        if (
            not isinstance(workspace_id, str)
            or not workspace_id
            or isinstance(workspace_revision, bool)
            or not isinstance(workspace_revision, int)
            or isinstance(study_area_revision, bool)
            or not isinstance(study_area_revision, int)
            or not isinstance(source_package_revision, str)
            or not source_package_revision
            or not isinstance(evidence_bundle_sha256, str)
            or not evidence_bundle_sha256
        ):
            return {
                **_missing_record("The critic's current workspace or evidence revision metadata is incomplete."),
                "scenario_id": scenario_id,
            }

        critic_request = {
            "expected_study_area_id": site_analysis["study_area_id"],
            "expected_study_area_revision": study_area_revision,
            "expected_source_package_revision": source_package_revision,
            "expected_evidence_bundle_sha256": evidence_bundle_sha256,
            "expected_workspace_id": workspace_id,
            "expected_workspace_revision": workspace_revision,
            "evidence_card_ids": selected_card_ids,
            "prompt": prompt,
            "language": language,
        }
        res = self._call_client("evaluate_critic", critic_request)
        failure = _unavailable_response(res)
        if failure is not None:
            return {**failure, "scenario_id": scenario_id}
        if not isinstance(res, Mapping):
            return {
                **_missing_record("The platform did not return a critic evaluation record."),
                "scenario_id": scenario_id,
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
            self._call_client("run_judgement", skill_id, subject_ids, language=language, project_id=project_id),
            language,
        )

    def list_judgements(
        self,
        *,
        language: Literal["zh-TW", "en"] = "zh-TW",
        project_id: str = "rotterdam-m4h",
    ) -> dict[str, Any]:
        return with_requested_language(
            self._call_client("list_judgements", language=language, project_id=project_id),
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
            self._call_client(
                "respond_to_judgement",
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
            self._call_client("request_revision_proposal", card_id, language=language, project_id=project_id),
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
            self._call_client("get_proposal", proposal_id, language=language, project_id=project_id),
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
            self._call_client("get_design_dialogue", subject, language=language, project_id=project_id),
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
        decision_summary = self._call_client("get_workspace_decision_summary", workspace_id)
        failure = _unavailable_response(decision_summary)
        if failure is not None:
            return {**failure, "project_id": project_id}
        if not isinstance(decision_summary, Mapping) or not decision_summary:
            return {**_missing_record("The current workspace decision summary is missing."), "project_id": project_id}

        dispositions = decision_summary.get("dispositions")
        buildings = dispositions.get("buildings") if isinstance(dispositions, Mapping) else None
        roads = dispositions.get("roads") if isinstance(dispositions, Mapping) else None
        building_counts = buildings.get("counts") if isinstance(buildings, Mapping) else None
        road_counts = roads.get("counts") if isinstance(roads, Mapping) else None

        def valid_count(counts: Any, name: str) -> int | None:
            value = counts.get(name) if isinstance(counts, Mapping) else None
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

        building_total = valid_count(building_counts, "total")
        building_undecided = valid_count(building_counts, "undecided")
        road_total = valid_count(road_counts, "total")
        road_undecided = valid_count(road_counts, "undecided")
        pending_items: list[dict[str, Any]] = []
        if (building_undecided or 0) + (road_undecided or 0) > 0:
            if language == "en":
                if building_total is not None and road_total is not None and building_undecided is not None and road_undecided is not None:
                    description = (
                        f"Among {building_total} BAG building features and {road_total} road segments, "
                        f"{building_undecided} buildings and {road_undecided} roads remain UNDECIDED."
                    )
                else:
                    description = "Some existing building or road dispositions remain UNDECIDED."
                area_name = "Existing Feature Dispositions"
                action = "Review the available building and road items and mark each PRESERVE or EDITABLE"
            else:
                if building_total is not None and road_total is not None and building_undecided is not None and road_undecided is not None:
                    description = (
                        f"基地內 {building_total} 個 BAG 建築圖徵與 {road_total} 個道路段中，"
                        f"有 {building_undecided} 個建築與 {road_undecided} 個道路段仍為 UNDECIDED。"
                    )
                else:
                    description = "部分既有建築或道路的處分仍為 UNDECIDED。"
                area_name = "既有特徵處分（Existing Feature Dispositions）"
                action = "在工作區介面確認可用的建築與道路項目，並逐項標示 PRESERVE 或 EDITABLE"
            pending_items.append({
                "decision_area": area_name,
                "description": description,
                "status": "PENDING_DISPOSITION_DECISIONS",
                "human_action_required": action,
            })

        if language == "en":
            pd14_protection_rule = (
                "Under PD-14 and the project constitution (AGENTS.md), AI agents are strictly prohibited "
                "from making any decisions or holding decision passphrases. All consequential design decisions "
                "must be made by the designer directly providing the passphrase and signing a HumanDecision on the platform."
            )
        else:
            pd14_protection_rule = (
                "依據 PD-14 與專案憲法（AGENTS.md），AI 代理人嚴格禁止代行任何決定或持有決策密語。"
                "所有重大設計決策必須由設計者本人在平台提供密語並簽署 HumanDecision。"
            )

        res_payload: dict[str, Any] = {
            "project_id": project_id,
            "status": "AVAILABLE",
            "constitutional_core_law": "LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.",
            "pd14_protection_rule": pd14_protection_rule,
            "pending_decisions_count": len(pending_items),
            "pending_decisions": pending_items,
            "workspace_decision_summary": dict(decision_summary),
        }
        if language == "en":
            res_payload["source_language"] = "zh-TW"
        return res_payload
