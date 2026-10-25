"""Tests for environmental run comparison and compatibility gates (W6 precursor lane F3)."""

from __future__ import annotations

import pytest

from urban_design.environment.comparison import (
    IncompatibleComparisonError,
    compare_direction_consistency,
    compare_environmental_runs,
)


@pytest.fixture
def base_run() -> dict:
    return {
        "method": "ladybug_radiance",
        "grid_definition": {"origin_x": 0.0, "origin_y": 0.0, "spacing_m": 5.0, "crs": "LOCAL_METRE"},
        "weather_hash": "sha256:weather123",
        "period_hash": "sha256:period456",
        "area_weighted_average": 6.5,
        "points": [
            {"point_id": "pt_0.0_0.0_0.0", "status": "VALID"},
            {"point_id": "pt_5.0_0.0_0.0", "status": "VALID"},
            {"point_id": "pt_10.0_0.0_0.0", "status": "VALID"},
        ],
    }


def test_within_method_comparison_success(base_run: dict) -> None:
    # Modified run: sunlight increased, but pt_10.0_0.0_0.0 is occupied by a new building
    mod_run = {
        "method": "ladybug_radiance",
        "grid_definition": {"origin_x": 0.0, "origin_y": 0.0, "spacing_m": 5.0, "crs": "LOCAL_METRE"},
        "weather_hash": "sha256:weather123",
        "period_hash": "sha256:period456",
        "area_weighted_average": 7.2,
        "points": [
            {"point_id": "pt_0.0_0.0_0.0", "status": "VALID"},
            {"point_id": "pt_5.0_0.0_0.0", "status": "VALID"},
            {"point_id": "pt_10.0_0.0_0.0", "status": "EXCLUDED_INSIDE_FOOTPRINT"},  # Occupied!
        ],
    }

    comp = compare_environmental_runs(base_run, mod_run)
    assert comp.comparable is True
    assert comp.direction_of_change == "INCREASED"
    assert comp.delta_mean == 0.7
    # Displaced point is captured, not lost
    assert comp.occupied_points == ["pt_10.0_0.0_0.0"]


def test_cross_method_absolute_comparison_rejected(base_run: dict) -> None:
    mod_run_different_method = {
        **base_run,
        "method": "pure_python_box_ray",
    }
    with pytest.raises(IncompatibleComparisonError, match="Cross-method comparison rejected"):
        compare_environmental_runs(base_run, mod_run_different_method)

    # When raise_on_incompatible is False, returns typed rejection
    res = compare_environmental_runs(base_run, mod_run_different_method, raise_on_incompatible=False)
    assert res.comparable is False
    assert res.direction_of_change == "INCOMPARABLE"
    assert "Cross-method comparison rejected" in (res.rejection_reason or "")


def test_grid_mismatch_rejected(base_run: dict) -> None:
    mod_run_different_grid = {
        **base_run,
        "grid_definition": {"origin_x": 0.0, "origin_y": 0.0, "spacing_m": 10.0, "crs": "LOCAL_METRE"},
    }
    with pytest.raises(IncompatibleComparisonError, match="Grid mismatch rejected"):
        compare_environmental_runs(base_run, mod_run_different_grid)


def test_weather_hash_mismatch_rejected(base_run: dict) -> None:
    mod_run_diff_weather = {
        **base_run,
        "weather_hash": "sha256:different_weather_789",
    }
    with pytest.raises(IncompatibleComparisonError, match="Weather/solar hash mismatch rejected"):
        compare_environmental_runs(base_run, mod_run_diff_weather)


def test_period_mismatch_rejected(base_run: dict) -> None:
    mod_run_diff_period = {
        **base_run,
        "period_hash": "sha256:different_period_999",
    }
    with pytest.raises(IncompatibleComparisonError, match="Period mismatch rejected"):
        compare_environmental_runs(base_run, mod_run_diff_period)


def test_cross_method_direction_consistency(base_run: dict) -> None:
    """Two different methods may only be compared for direction consistency, never absolute values."""
    # Method 1 (Radiance) shows an increase
    comp_rad = compare_environmental_runs(
        base_run,
        {**base_run, "area_weighted_average": 7.5},
    )

    # Method 2 (Python reference) also shows an increase
    comp_py = compare_environmental_runs(
        {**base_run, "method": "pure_python_box_ray", "area_weighted_average": 5.0},
        {**base_run, "method": "pure_python_box_ray", "area_weighted_average": 5.8},
    )

    summary = compare_direction_consistency(comp_rad, comp_py)
    assert summary["direction_consistent"] is True
    assert summary["cross_method_absolute_subtraction_allowed"] is False
