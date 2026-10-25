from __future__ import annotations

import pytest

from urban_design.environment.comparison import (
    IncompatibleComparisonError,
    compare_environmental_runs,
)
from urban_design.environment.contracts import ComparisonResult, SensorGridResult, SensorPoint
from urban_design.environment.radiation import (
    RadiationInputReferences,
    validate_radiation_preconditions,
)
from urban_design.environment.sensors import create_sensor_grid_result


@pytest.mark.parametrize(
    "missing_reference",
    ["weather_snapshot_ref", "method", "experiment_plan_ref"],
)
def test_missing_weather_method_or_experiment_reference_blocks_e2(
    missing_reference: str,
) -> None:
    report = validate_radiation_preconditions(
        RadiationInputReferences(input_status="FIXTURE_ONLY")
    )

    assert report.status == "BLOCKED"
    assert report.dispatch_allowed is False
    assert report.weather_file_read is False
    assert report.e2_dispatch_attempted is False
    assert missing_reference in report.missing_references


def test_fixture_references_do_not_release_weather_pause() -> None:
    refs = RadiationInputReferences(
        input_status="FIXTURE_ONLY",
        weather_snapshot_ref="fixture://weather-snapshot",
        method="ladybug_radiance",
        experiment_plan_ref="fixture://experiment-plan",
        scenario_revision_ref="fixture://scenario-revision",
        geometry_hash="fixture:geometry-hash",
        sensor_grid_hash="fixture:sensor-grid-hash",
        method_runtime_manifest_ref="fixture://method-runtime-manifest",
        radiance_runtime_manifest_ref="fixture://radiance-runtime-manifest",
        recipe_ref="fixture://recipe",
        period_ref="fixture://period",
        context_ref="fixture://context",
        material_assumptions_ref="fixture://material-assumptions",
        true_north_ref="fixture://true-north",
        time_convention_ref="fixture://time-convention",
        settings_ref="fixture://settings",
        comparison_domain_ref="fixture://comparison-domain",
        method_approval_ref="fixture://method-approval",
        experiment_approval_ref="fixture://experiment-approval",
        weather_pause_release_ref="fixture://pause-release",
    )

    report = validate_radiation_preconditions(refs)

    assert report.status == "BLOCKED"
    assert report.dispatch_allowed is False
    assert report.blockers == ("E2_WEATHER_PAUSE_ACTIVE", "INPUTS_NOT_APPROVED")


def test_sensor_grid_retains_occupied_cell_area_and_area_coverage() -> None:
    assert "total_area_m2" in SensorGridResult.model_fields
    assert "excluded_area_m2" in SensorGridResult.model_fields
    assert "area_coverage_ratio" in SensorGridResult.model_fields

    points = [
        SensorPoint.create(x=0, y=0, cell_area_m2=25.0, status="VALID"),
        SensorPoint.create(
            x=5,
            y=0,
            cell_area_m2=75.0,
            status="EXCLUDED_INSIDE_FOOTPRINT",
        ),
    ]

    result = create_sensor_grid_result(
        points=points,
        values={points[0].point_id: 12.0, points[1].point_id: 999.0},
        spacing_m=5.0,
    )

    assert result.total_points == 2
    assert result.valid_points == 1
    assert result.excluded_points == 1
    assert result.coverage_ratio == 0.5
    assert result.total_area_m2 == 100.0
    assert result.valid_area_m2 == 25.0
    assert result.excluded_area_m2 == 75.0
    assert result.area_coverage_ratio == 0.25


def test_comparison_retains_occupied_sensor_area_and_each_run_area_coverage() -> None:
    assert "occupied_sensor_area_m2" in ComparisonResult.model_fields
    assert "baseline_area_coverage_ratio" in ComparisonResult.model_fields
    assert "modified_area_coverage_ratio" in ComparisonResult.model_fields

    baseline = {
        "method": "ladybug_radiance",
        "weather_hash": "FIXTURE_ONLY:weather",
        "period_hash": "FIXTURE_ONLY:period",
        "area_weighted_average": 10.0,
        "points": [
            {"point_id": "a", "status": "VALID", "cell_area_m2": 25.0},
            {"point_id": "b", "status": "VALID", "cell_area_m2": 75.0},
        ],
    }
    modified = {
        **baseline,
        "area_weighted_average": 12.0,
        "points": [
            {"point_id": "a", "status": "VALID", "cell_area_m2": 25.0},
            {
                "point_id": "b",
                "status": "EXCLUDED_INSIDE_FOOTPRINT",
                "cell_area_m2": 75.0,
            },
        ],
    }

    comparison = compare_environmental_runs(baseline, modified)

    assert comparison.occupied_points == ["b"]
    assert comparison.occupied_sensor_area_m2 == 75.0
    assert comparison.baseline_area_coverage_ratio == 1.0
    assert comparison.modified_area_coverage_ratio == 0.25


@pytest.mark.parametrize("missing_field", ["method", "weather_hash", "period_hash"])
def test_comparison_rejects_missing_method_weather_or_period_reference(
    missing_field: str,
) -> None:
    run = {
        "method": "ladybug_radiance",
        "weather_hash": "FIXTURE_ONLY:weather",
        "period_hash": "FIXTURE_ONLY:period",
        "area_weighted_average": 10.0,
        "points": [],
    }
    baseline = {**run, missing_field: ""}
    modified = {**run, missing_field: ""}

    with pytest.raises(IncompatibleComparisonError, match="Missing"):
        compare_environmental_runs(baseline, modified)
