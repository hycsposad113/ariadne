from __future__ import annotations

import pytest

from scripts.compute_regional_syntax_and_stability import (
    _set_regional_not_computed,
    compare_radius_stability,
    estimate_10km_runtime_seconds,
)


def test_runtime_estimate_uses_measured_network_and_radius_scaling():
    estimate = estimate_10km_runtime_seconds(
        seconds_2km_4k=2.0,
        segments_2km_4k=100,
        seconds_2km_6k=8.0,
        segments_2km_6k=200,
        estimated_segments_15k=300,
        estimated_segments_20k=400,
        seconds_800m_6k=1.0,
    )

    assert estimate["network_size_exponent"] == pytest.approx(2.0)
    assert estimate["radius_scaling_factor"] == pytest.approx(25.0)
    assert estimate["predicted_15k_seconds"] == pytest.approx(450.0)
    assert estimate["predicted_20k_seconds"] == pytest.approx(800.0)
    assert estimate["runtime_model"] == "empirical_network_power_law_with_quadratic_radius_screen"


def test_runtime_estimate_rejects_zero_or_nonfinite_measurements():
    with pytest.raises(ValueError, match="positive finite"):
        estimate_10km_runtime_seconds(
            seconds_2km_4k=0.0,
            segments_2km_4k=100,
            seconds_2km_6k=8.0,
            segments_2km_6k=200,
            estimated_segments_15k=300,
            estimated_segments_20k=400,
            seconds_800m_6k=1.0,
        )


def test_runtime_withheld_layer_has_no_zero_valued_metric_results():
    estimate = {
        "predicted_15k_seconds": 16451.7,
        "predicted_20k_seconds": 29411.8,
    }
    result = {
        "layers": [
            {
                "radius_m": 10000.0,
                "metric_key": "nain",
                "calculation_status": "COMPUTED",
                "data_readiness": "READY",
                "segment_values": {},
                "statistics": {"count": 0, "min": 0.0, "mean": 0.0, "max": 0.0},
            }
        ]
    }

    withheld = _set_regional_not_computed(result, estimate)
    layer = withheld["layers"][0]

    assert layer["calculation_status"] == "NOT_COMPUTED_RUNTIME_BUDGET"
    assert layer["segment_values"] == {}
    assert layer["statistics"] is None
    assert "exceeds" in layer["limitations"]


def _syntax_result(nain: dict[str, float], nach: dict[str, float]) -> dict:
    return {
        "layers": [
            {"radius_m": 2000.0, "metric_key": "nain", "segment_values": nain},
            {"radius_m": 2000.0, "metric_key": "nach", "segment_values": nach},
        ]
    }


def test_radius_stability_compares_common_study_area_segment_ids_and_flags_changes():
    smaller = _syntax_result(
        {"a": 1.0, "b": 2.0, "c": 3.0, "only-small": 4.0},
        {"a": 4.0, "b": 3.0, "c": 2.0, "only-small": 1.0},
    )
    larger = _syntax_result(
        {"a": 1.2, "b": 2.4, "c": 3.6, "only-large": 5.0},
        {"a": 4.8, "b": 3.6, "c": 2.4, "only-large": 2.0},
    )

    report = compare_radius_stability(smaller, larger, radius_m=2000.0)

    assert report["common_segment_count"] == 3
    assert report["smaller_only_count"] == 1
    assert report["larger_only_count"] == 1
    assert report["metrics"]["nain"]["spearman_correlation"] == pytest.approx(1.0)
    assert report["metrics"]["nain"]["edge_affected_segment_ids"] == ["a", "b", "c"]
    assert report["stability_pass"] is True
