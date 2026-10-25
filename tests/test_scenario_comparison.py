from __future__ import annotations

from urban_design.scenario_comparison import build_scenario_comparison


def _syntax_scenario(scenario_id: str, *, layer_version: str, method_version: str, syntax_status: str = "CURRENT") -> dict:
    return {
        "scenario_id": scenario_id,
        "denominator_hash": "d" * 64,
        "rules_version": "fixture-metrics-v1",
        "syntax_layer_version": layer_version,
        "syntax_method_version": method_version,
        "syntax_statuses": {f"syntax-{scenario_id}": syntax_status},
        "metrics": {
            "far": {"value": 1.2, "unit": "ratio", "method": "gfa/site-area"},
            "coverage_ratio": {"value": 0.3, "unit": "ratio", "method": "footprint/site-area"},
            "height_m": {"value": 12, "unit": "m", "method": "floor height"},
            "road_ratio": {"value": 0.1, "unit": "ratio", "method": "road/site-area"},
            "open_space_ratio": {"value": 0.2, "unit": "ratio", "method": "open-space/site-area"},
            "syntax_integration_800m": {
                "value": 2.5,
                "unit": "normalized value",
                "method": "PST walking radius 800m",
                "validation_status": "VALIDATED",
                "data_gaps": [],
            },
        },
    }


def test_scenarios_with_different_denominators_are_not_comparable() -> None:
    result = build_scenario_comparison(
        [
            {
                "scenario_id": "scenario-a",
                "denominator_hash": "a" * 64,
                "rules_version": "fixture-metrics-v1",
                "metrics": {"far": {"value": 1.2, "unit": "ratio", "method": "gfa/site-area"}},
            },
            {
                "scenario_id": "scenario-b",
                "denominator_hash": "b" * 64,
                "rules_version": "fixture-metrics-v1",
                "metrics": {"far": {"value": 1.4, "unit": "ratio", "method": "gfa/site-area"}},
            },
        ]
    )

    far = next(row for row in result["metrics"] if row["metric_id"] == "far")
    assert result["status"] == "NOT_COMPARABLE"
    assert far["status"] == "NOT_COMPARABLE"
    assert far["values"] == {"scenario-a": 1.2, "scenario-b": 1.4}


def test_different_syntax_versions_make_the_comparison_not_comparable() -> None:
    result = build_scenario_comparison(
        [
            _syntax_scenario("scenario-a", layer_version="syntax-layer-1", method_version="pstalgo-3.3.1"),
            _syntax_scenario("scenario-b", layer_version="syntax-layer-2", method_version="pstalgo-3.3.1"),
        ]
    )

    syntax = next(row for row in result["metrics"] if row["metric_id"] == "syntax_integration_800m")
    assert result["status"] == "NOT_COMPARABLE"
    assert syntax["status"] == "NOT_COMPARABLE"


def test_stale_syntax_dependency_is_not_presented_as_comparable() -> None:
    result = build_scenario_comparison(
        [
            _syntax_scenario("scenario-a", layer_version="syntax-layer-1", method_version="pstalgo-3.3.1", syntax_status="STALE"),
            _syntax_scenario("scenario-b", layer_version="syntax-layer-1", method_version="pstalgo-3.3.1"),
        ]
    )

    syntax = next(row for row in result["metrics"] if row["metric_id"] == "syntax_integration_800m")
    assert result["status"] == "NOT_COMPARABLE"
    assert syntax["status"] == "NOT_COMPARABLE"
    assert syntax["validation_status"]["scenario-a"] == "STALE"
    assert "dependent Syntax result is STALE" in syntax["data_gaps"]


def test_matching_current_syntax_versions_can_be_compared_without_ranking() -> None:
    result = build_scenario_comparison(
        [
            _syntax_scenario("scenario-a", layer_version="syntax-layer-1", method_version="pstalgo-3.3.1"),
            _syntax_scenario("scenario-b", layer_version="syntax-layer-1", method_version="pstalgo-3.3.1"),
        ]
    )

    syntax = next(row for row in result["metrics"] if row["metric_id"] == "syntax_integration_800m")
    assert result["status"] == "COMPARABLE"
    assert syntax["status"] == "COMPARABLE"
    assert result["ranking"] is None
    assert result["overall_score"] is None
    assert result["winner"] is None


def test_different_constraint_sets_are_not_comparable() -> None:
    result = build_scenario_comparison(
        [
            {
                "scenario_id": "scenario-a",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "constraint_set_id": "constraint-set-a",
                "metrics": {"far": {"value": 1.2, "unit": "ratio", "method": "gfa/site-area"}},
            },
            {
                "scenario_id": "scenario-b",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "constraint_set_id": "constraint-set-b",
                "metrics": {"far": {"value": 1.4, "unit": "ratio", "method": "gfa/site-area"}},
            },
        ]
    )
    assert result["status"] == "NOT_COMPARABLE"
    assert any("constraint set" in reason.lower() for reason in result["incompatibility_reasons"])


def test_divergent_methods_make_metric_and_comparison_not_comparable() -> None:
    result = build_scenario_comparison(
        [
            {
                "scenario_id": "scenario-a",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "metrics": {
                    "far": {"value": 1.2, "unit": "ratio", "method": "gross-gfa/site-area"},
                    "coverage_ratio": {"value": 0.3, "unit": "ratio", "method": "footprint/site-area"},
                    "height_m": {"value": 12, "unit": "m", "method": "floor height"},
                    "road_ratio": {"value": 0.1, "unit": "ratio", "method": "road/site-area"},
                    "open_space_ratio": {"value": 0.2, "unit": "ratio", "method": "open-space/site-area"},
                },
            },
            {
                "scenario_id": "scenario-b",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "metrics": {
                    "far": {"value": 1.4, "unit": "ratio", "method": "net-gfa/site-area"},
                    "coverage_ratio": {"value": 0.3, "unit": "ratio", "method": "footprint/site-area"},
                    "height_m": {"value": 12, "unit": "m", "method": "floor height"},
                    "road_ratio": {"value": 0.1, "unit": "ratio", "method": "road/site-area"},
                    "open_space_ratio": {"value": 0.2, "unit": "ratio", "method": "open-space/site-area"},
                },
            },
        ]
    )
    far = next(row for row in result["metrics"] if row["metric_id"] == "far")
    assert result["status"] == "NOT_COMPARABLE"
    assert far["status"] == "NOT_COMPARABLE"
    assert any("measurement methods" in reason.lower() for reason in far["incompatibility_reasons"])


def test_previews_and_fixtures_cannot_be_accepted_as_baseline() -> None:
    result = build_scenario_comparison(
        [
            {
                "scenario_id": "scenario-a",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "provenance": "FIXTURE_ONLY",
                "metrics": {
                    "far": {"value": 1.2, "unit": "ratio", "method": "gfa/site-area"},
                    "coverage_ratio": {"value": 0.3, "unit": "ratio", "method": "footprint/site-area"},
                    "height_m": {"value": 12, "unit": "m", "method": "floor height"},
                    "road_ratio": {"value": 0.1, "unit": "ratio", "method": "road/site-area"},
                    "open_space_ratio": {"value": 0.2, "unit": "ratio", "method": "open-space/site-area"},
                },
            },
            {
                "scenario_id": "scenario-b",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "provenance": "UNAPPROVED_PREVIEW",
                "metrics": {
                    "far": {"value": 1.4, "unit": "ratio", "method": "gfa/site-area"},
                    "coverage_ratio": {"value": 0.3, "unit": "ratio", "method": "footprint/site-area"},
                    "height_m": {"value": 12, "unit": "m", "method": "floor height"},
                    "road_ratio": {"value": 0.1, "unit": "ratio", "method": "road/site-area"},
                    "open_space_ratio": {"value": 0.2, "unit": "ratio", "method": "open-space/site-area"},
                },
            },
        ]
    )
    assert result["status"] == "COMPARABLE"
    eligibility = result["eligibility_for_decision"]
    assert eligibility["can_accept"] is False
    assert eligibility["status"] == "BLOCKED_PREVIEWS_ONLY"
    assert "Formal proposals required" in eligibility["reason"]


def test_formal_proposals_allow_baseline_decision_without_ranking() -> None:
    result = build_scenario_comparison(
        [
            {
                "scenario_id": "prop-1",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "constraint_set_id": "cs-rotterdam-1",
                "provenance": "FORMAL_PROPOSAL",
                "valid": True,
                "metrics": {
                    "far": {"value": 1.2, "unit": "ratio", "method": "gfa/site-area"},
                    "coverage_ratio": {"value": 0.3, "unit": "ratio", "method": "footprint/site-area"},
                    "height_m": {"value": 12, "unit": "m", "method": "floor height"},
                    "road_ratio": {"value": 0.1, "unit": "ratio", "method": "road/site-area"},
                    "open_space_ratio": {"value": 0.2, "unit": "ratio", "method": "open-space/site-area"},
                },
            },
            {
                "scenario_id": "prop-2",
                "denominator_hash": "d" * 64,
                "rules_version": "rules-v1",
                "constraint_set_id": "cs-rotterdam-1",
                "provenance": "FORMAL_PROPOSAL",
                "valid": True,
                "metrics": {
                    "far": {"value": 1.5, "unit": "ratio", "method": "gfa/site-area"},
                    "coverage_ratio": {"value": 0.35, "unit": "ratio", "method": "footprint/site-area"},
                    "height_m": {"value": 15, "unit": "m", "method": "floor height"},
                    "road_ratio": {"value": 0.12, "unit": "ratio", "method": "road/site-area"},
                    "open_space_ratio": {"value": 0.25, "unit": "ratio", "method": "open-space/site-area"},
                },
            },
        ]
    )
    assert result["status"] == "COMPARABLE"
    assert result["ranking"] is None
    assert result["overall_score"] is None
    assert result["winner"] is None
    eligibility = result["eligibility_for_decision"]
    assert eligibility["can_accept"] is True
    assert eligibility["status"] == "READY_FOR_DECISION"

