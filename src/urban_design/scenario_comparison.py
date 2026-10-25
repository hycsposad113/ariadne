"""Evidence-bound, non-ranking comparison of persisted scenarios."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


_REQUIRED_METRICS = (
    ("far", "FAR", "ratio"),
    ("coverage_ratio", "Coverage ratio", "ratio"),
    ("height_m", "Height", "m"),
    ("road_ratio", "Road ratio", "ratio"),
    ("open_space_ratio", "Open space ratio", "ratio"),
)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _finite_value(metric: Mapping[str, Any]) -> float | None:
    value = metric.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _check_basis_compatibility(scenarios: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    denominators = {_text(item.get("denominator_hash")) for item in scenarios}
    rules = {_text(item.get("rules_version")) for item in scenarios}
    if None in denominators:
        reasons.append("Missing spatial denominator hash (comparison requires identical denominator)")
    elif len(denominators) > 1:
        reasons.append("Mismatched spatial denominator hashes (different site or design area boundaries)")
    if None in rules:
        reasons.append("Missing metric calculation rules version")
    elif len(rules) > 1:
        reasons.append("Mismatched metric calculation rules versions")

    constraint_sets = {_text(item.get("constraint_set_id")) for item in scenarios if item.get("constraint_set_id") is not None}
    if len(constraint_sets) > 1:
        reasons.append("Mismatched constraint set identifiers (comparison requires identical constraint set)")

    sites = {_text(item.get("site_id")) for item in scenarios if item.get("site_id") is not None}
    if len(sites) > 1:
        reasons.append("Mismatched site identifiers (comparison requires identical site)")

    has_syntax_metrics = any(
        isinstance(item.get("metrics"), Mapping)
        and any(str(metric_id).startswith("syntax_") for metric_id in item["metrics"])
        for item in scenarios
    )
    if has_syntax_metrics:
        syntax_versions = {
            (_text(item.get("syntax_layer_version")), _text(item.get("syntax_method_version")))
            for item in scenarios
        }
        if len(syntax_versions) != 1 or None in next(iter(syntax_versions)):
            reasons.append("Mismatched or missing Syntax layer or method versions")
        if any(_has_stale_syntax(item) for item in scenarios):
            reasons.append("Dependent Syntax result is STALE")

    return (len(reasons) == 0, reasons)


def _basis_compatible(scenarios: Sequence[Mapping[str, Any]]) -> bool:
    compatible, _ = _check_basis_compatibility(scenarios)
    return compatible


def _has_stale_syntax(scenario: Mapping[str, Any]) -> bool:
    statuses = scenario.get("syntax_statuses")
    return isinstance(statuses, Mapping) and any(_text(status) == "STALE" for status in statuses.values())


def _metric_rows(scenarios: Sequence[Mapping[str, Any]], basis_ok: bool) -> list[dict[str, Any]]:
    ids = [str(item["scenario_id"]) for item in scenarios]
    metric_ids = [item[0] for item in _REQUIRED_METRICS]
    metric_ids.extend(
        sorted(
            {
                str(metric_id)
                for scenario in scenarios
                for metric_id in (scenario.get("metrics") or {})
                if str(metric_id).startswith("use_ratio:") or str(metric_id).startswith("syntax_")
            }
        )
    )
    definitions = {metric_id: (label, unit) for metric_id, label, unit in _REQUIRED_METRICS}
    rows: list[dict[str, Any]] = []
    for metric_id in metric_ids:
        observations: dict[str, Mapping[str, Any]] = {}
        for scenario in scenarios:
            metrics = scenario.get("metrics")
            if isinstance(metrics, Mapping) and isinstance(metrics.get(metric_id), Mapping):
                observations[str(scenario["scenario_id"])] = metrics[metric_id]

        units = {_text(item.get("unit")) for item in observations.values()}
        methods = {_text(item.get("method")) for item in observations.values()}
        syntax_metric = metric_id.startswith("syntax_")
        syntax_versions = {
            (_text(item.get("syntax_layer_version")), _text(item.get("syntax_method_version")))
            for item in scenarios
        }
        stale_syntax = {
            str(scenario["scenario_id"]): _has_stale_syntax(scenario)
            for scenario in scenarios
        }

        row_reasons: list[str] = []
        far_bases = {(item.get("denominator_label", "legacy/unspecified"), item.get("denominator_area_m2")) for item in observations.values()}
        if metric_id == "far" and len(far_bases) != 1:
            row_reasons.append("Inconsistent FAR denominator")
        if not basis_ok:
            row_reasons.append("Incompatible comparison basis")
        if len(observations) != len(scenarios):
            missing_ids = [s_id for s_id in ids if s_id not in observations]
            row_reasons.append(f"Metric missing in scenarios: {', '.join(missing_ids)}")
        if len(units) != 1 or None in units:
            row_reasons.append("Inconsistent metric units")
        if len(methods) != 1 or None in methods:
            row_reasons.append("Inconsistent measurement methods")
        if syntax_metric:
            if len(syntax_versions) != 1 or None in next(iter(syntax_versions)):
                row_reasons.append("Inconsistent Syntax version")
            if any(stale_syntax.values()):
                row_reasons.append("Dependent Syntax result is STALE")

        compatible = len(row_reasons) == 0

        values = {
            scenario_id: _finite_value(observations[scenario_id])
            for scenario_id in ids
            if scenario_id in observations
        }
        gaps = sorted(
            {
                str(gap)
                for observation in observations.values()
                for gap in (observation.get("data_gaps") or [])
                if isinstance(gap, str) and gap.strip()
            }
        )
        validation = {
            scenario_id: _text(observations[scenario_id].get("validation_status")) or "UNKNOWN"
            for scenario_id in ids
            if scenario_id in observations
        }
        if syntax_metric and any(stale_syntax.values()):
            validation = {
                scenario_id: "STALE" if stale_syntax.get(scenario_id, False) else status
                for scenario_id, status in validation.items()
            }
            gaps = sorted({*gaps, "dependent Syntax result is STALE"})
        default_label, default_unit = definitions.get(metric_id, (metric_id.replace("_", " "), "unknown"))
        rows.append(
            {
                "metric_id": metric_id,
                "label": default_label,
                "unit": next(iter(units)) if len(units) == 1 and None not in units else default_unit,
                "method": next(iter(methods)) if len(methods) == 1 and None not in methods else None,
                "data_gaps": gaps,
                "validation_status": validation,
                "status": "COMPARABLE" if compatible else "NOT_COMPARABLE",
                "incompatibility_reasons": row_reasons,
                "values": values,
                **({"denominators": {sid: {"label": obs.get("denominator_label", "legacy/unspecified"), "area_m2": obs.get("denominator_area_m2")} for sid, obs in observations.items()}} if metric_id == "far" else {}),
            }
        )
    return rows


def check_decision_eligibility(
    scenarios: Sequence[Mapping[str, Any]],
    comparison_status: str,
) -> dict[str, Any]:
    """Determine whether human acceptance as baseline is permitted."""
    if comparison_status != "COMPARABLE":
        return {
            "can_accept": False,
            "status": "BLOCKED",
            "reason": "Comparison basis or metrics are not comparable; decision entrance is closed.",
            "baseline_scenario_id": None,
        }

    baseline_id = None
    for s in scenarios:
        if s.get("status") == "accepted" or s.get("is_baseline") is True:
            baseline_id = str(s.get("scenario_id"))
            break
    if baseline_id is not None:
        return {
            "can_accept": False,
            "status": "BASELINE_SELECTED",
            "reason": f"Baseline scenario has already been selected: {baseline_id}",
            "baseline_scenario_id": baseline_id,
        }

    non_formal_provenances = {"FIXTURE_ONLY", "UNAPPROVED_PREVIEW", "UNKNOWN", "ASSUMED"}
    has_non_formal = any(
        str(s.get("provenance", "UNKNOWN")).upper() in non_formal_provenances
        for s in scenarios
    )
    if has_non_formal:
        return {
            "can_accept": False,
            "status": "BLOCKED_PREVIEWS_ONLY",
            "reason": "Formal proposals required; unapproved preview or fixture cannot be accepted as baseline.",
            "baseline_scenario_id": None,
        }

    invalid_ids = [
        str(s.get("scenario_id"))
        for s in scenarios
        if s.get("valid") is False or (s.get("failure_reasons") and len(s.get("failure_reasons")) > 0)
    ]
    if invalid_ids:
        return {
            "can_accept": False,
            "status": "BLOCKED_VALIDATION_FAILED",
            "reason": f"Proposals failed geometric or planning validation: {', '.join(invalid_ids)}",
            "baseline_scenario_id": None,
        }

    return {
        "can_accept": True,
        "status": "READY_FOR_DECISION",
        "reason": None,
        "baseline_scenario_id": None,
    }


def build_scenario_comparison(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build metric rows only when persisted denominator and rule bases align.

    The function intentionally has no score, winner, or ranking output. Callers must pass
    records loaded from the project store rather than browser-provided metrics.
    """
    if len(scenarios) < 2:
        raise ValueError("at least two scenarios are required for comparison")
    ids = [_text(item.get("scenario_id")) for item in scenarios]
    if any(item is None for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("scenario identifiers must be non-empty and unique")
    if any(not isinstance(item.get("metrics", {}), Mapping) for item in scenarios):
        raise ValueError("scenario metrics must be persisted mappings")
    basis_ok, basis_reasons = _check_basis_compatibility(scenarios)
    metrics = _metric_rows(scenarios, basis_ok)
    all_metrics_comparable = all(row["status"] == "COMPARABLE" for row in metrics)
    is_comparable = basis_ok and all_metrics_comparable

    incompatibility_reasons = list(basis_reasons)
    for row in metrics:
        if row["status"] != "COMPARABLE":
            for reason in row.get("incompatibility_reasons", []):
                formatted = f"{row['label']}: {reason}"
                if formatted not in incompatibility_reasons:
                    incompatibility_reasons.append(formatted)

    comparison_status = "COMPARABLE" if is_comparable else "NOT_COMPARABLE"
    eligibility = check_decision_eligibility(scenarios, comparison_status)

    scenarios_summary = []
    for item in scenarios:
        scenarios_summary.append({
            "scenario_id": str(item.get("scenario_id")),
            "revision": item.get("revision", 1),
            "status": item.get("status", "proposed"),
            "strategy_id": item.get("strategy_id"),
            "strategy_label": item.get("strategy_label") or str(item.get("scenario_id")),
            "geometry_sha256": item.get("geometry_sha256"),
            "provenance": item.get("provenance", "UNKNOWN"),
            "valid": item.get("valid", True),
            "failure_reasons": list(item.get("failure_reasons") or []),
            "constraint_set_id": item.get("constraint_set_id"),
            "is_baseline": item.get("status") == "accepted" or item.get("is_baseline") is True,
        })

    return {
        "status": comparison_status,
        "scenario_ids": ids,
        "scenarios": scenarios_summary,
        "metrics": metrics,
        "incompatibility_reasons": incompatibility_reasons,
        "eligibility_for_decision": eligibility,
        "ranking": None,
        "overall_score": None,
        "winner": None,
    }


__all__ = ["build_scenario_comparison", "check_decision_eligibility"]

