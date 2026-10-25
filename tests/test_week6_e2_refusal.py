from __future__ import annotations

import pytest

from urban_design.environment.comparison import (
    IncompatibleComparisonError,
    compare_direction_consistency,
    compare_environmental_runs,
)
from urban_design.environment.radiation import (
    E2_WEATHER_PAUSE_ACTIVE,
    MethodControlLimits,
    RadiationInputReferences,
    label_hour_shift_comparison_direction,
    refuse_formal_e2,
)


def _run(method: str, mean: float) -> dict[str, object]:
    return {
        "method": method,
        "weather_hash": "FIXTURE_ONLY:weather",
        "period_hash": "FIXTURE_ONLY:period",
        "area_weighted_average": mean,
        "points": [
            {"point_id": "a", "status": "VALID", "cell_area_m2": 25.0},
            {"point_id": "b", "status": "VALID", "cell_area_m2": 75.0},
        ],
    }


def test_missing_weather_method_or_experiment_refuses_formal_e2() -> None:
    report = refuse_formal_e2(RadiationInputReferences(input_status="FIXTURE_ONLY"))

    assert report.status == "BLOCKED"
    assert report.gate == "READY_FOR_FOUNDER"
    assert report.dispatch_allowed is False
    assert report.weather_file_read is False
    assert report.e2_dispatch_attempted is False
    assert report.dataset_snapshot_published is False
    assert report.human_decision_created is False
    assert "weather_snapshot_ref" in report.missing_references
    assert "method" in report.missing_references
    assert "experiment_plan_ref" in report.missing_references
    assert "DATASET_SNAPSHOT_NOT_APPROVED" in report.blockers
    assert "E2_WEATHER_PAUSE_ACTIVE" in report.blockers


def test_caller_supplied_approval_does_not_publish_or_dispatch() -> None:
    refs = RadiationInputReferences(
        input_status="UNAPPROVED_PREVIEW",
        weather_snapshot_ref="snapshot-draft",
        method="honeybee_radiance",
        experiment_plan_ref="experiment-draft",
        scenario_revision_ref="scenario-draft",
        geometry_hash="ab" * 32,
        sensor_grid_hash="cd" * 32,
        method_runtime_manifest_ref="method-manifest",
        radiance_runtime_manifest_ref="radiance-manifest",
        recipe_ref="recipe-draft",
        period_ref="period-draft",
        context_ref="context-draft",
        material_assumptions_ref="material-draft",
        true_north_ref="north-draft",
        time_convention_ref="time-draft",
        settings_ref="settings-draft",
        comparison_domain_ref="domain-draft",
        method_approval_ref="method-unapproved",
        experiment_approval_ref="experiment-unapproved",
        weather_pause_release_ref="pause-unreleased",
    )

    report = refuse_formal_e2(
        refs,
        dataset_snapshot_status="APPROVED",
        human_decision_id="decision-not-authority",
    )

    assert E2_WEATHER_PAUSE_ACTIVE is True
    assert report.weather_pause_active is True
    assert report.dispatch_allowed is False
    assert report.dataset_snapshot_published is False
    assert report.human_decision_created is False
    assert report.job_created is False
    assert report.scheduler_created is False
    assert "DATASET_SNAPSHOT_NOT_APPROVED" in report.blockers
    assert "CALLER_SUPPLIED_APPROVAL_IS_NOT_AUTHORITY" in report.blockers
    assert "INPUTS_NOT_APPROVED" in report.blockers
    assert report.job_mechanism == "urban_design.generation.job_store.GenerationJobStore"
    assert report.job_runner == "urban_design.generation.job_runner.GenerationJobRunner"
    assert report.comparison_extent == "geometric_analysis_extent"
    assert report.pairwise_domain == "COMMON_OVERLAP"
    assert report.legal_right_of_way is False


def test_method_limits_stay_separate_and_unapproved() -> None:
    report = refuse_formal_e2(RadiationInputReferences())
    screening, verification = report.method_limits

    assert screening.method == "ladybug_radiance"
    assert screening.role == "screening"
    assert verification.method == "honeybee_radiance"
    assert verification.role == "verification"
    assert screening.reported_quantity == verification.reported_quantity
    fields = MethodControlLimits.model_fields
    assert set(fields) >= {"material", "reflectance", "recipe"}
    assert fields["material"] is not fields["reflectance"]
    assert fields["reflectance"] is not fields["recipe"]
    for limits in report.method_limits:
        assert limits.material == "NOT_APPROVED"
        assert limits.reflectance == "NOT_APPROVED"
        assert limits.recipe == "NOT_APPROVED"


def test_cross_method_absolute_comparison_is_refused() -> None:
    with pytest.raises(IncompatibleComparisonError, match="Cross-method"):
        compare_environmental_runs(
            _run("ladybug_radiance", 10.0),
            _run("honeybee_radiance", 12.0),
        )

    ladybug = compare_environmental_runs(
        _run("ladybug_radiance", 10.0),
        {
            **_run("ladybug_radiance", 12.0),
            "points": [
                {"point_id": "a", "status": "VALID", "cell_area_m2": 25.0},
                {
                    "point_id": "b",
                    "status": "EXCLUDED_INSIDE_FOOTPRINT",
                    "cell_area_m2": 75.0,
                },
            ],
        },
    )
    honeybee = compare_environmental_runs(
        _run("honeybee_radiance", 40.0),
        _run("honeybee_radiance", 30.0),
    )
    direction = compare_direction_consistency(ladybug, honeybee)

    assert ladybug.occupied_sensor_area_m2 == 75.0
    assert ladybug.baseline_area_coverage_ratio == 1.0
    assert ladybug.modified_area_coverage_ratio == 0.25
    assert direction["cross_method_absolute_subtraction_allowed"] is False
    assert "delta_mean" not in direction
    assert direction["direction_consistent"] is False


@pytest.mark.parametrize(
    ("baseline", "shifted", "expected"),
    [
        (None, None, "NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS"),
        ("INCREASED", "DECREASED", "REVERSED"),
        ("DECREASED", "INCREASED", "REVERSED"),
        ("DECREASED", "DECREASED", "NOT_REVERSED"),
        ("INCREASED", "UNCHANGED", "NOT_REVERSED"),
    ],
)
def test_hour_shift_labels_comparison_direction(
    baseline: str | None,
    shifted: str | None,
    expected: str,
) -> None:
    assert label_hour_shift_comparison_direction(baseline, shifted) == expected
    report = refuse_formal_e2(
        RadiationInputReferences(),
        baseline_direction=baseline,
        shifted_direction=shifted,
    )
    assert report.sensitivity_direction == expected
    assert report.dispatch_allowed is False
