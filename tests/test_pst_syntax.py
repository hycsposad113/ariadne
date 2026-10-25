"""Tests for compute_pst_six_syntax_layers on M4H context network (WC-3, PD-15)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import pytest
from shapely.geometry import box, shape

from urban_design.pst_syntax import (
    prepare_pst_lines,
    compute_pst_six_syntax_layers,
)

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / "artifacts/week4-repair-r02/syntax/context.geojson"
STUDY_AREA_PATH = ROOT / ".urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson"


def test_prepare_pst_lines_handles_closed_loops():
    # Synthetic closed ring
    ring_feat = {
        "id": "ring_1",
        "geometry": {
            "type": "LineString",
            "coordinates": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)],
        },
    }
    lines = prepare_pst_lines([ring_feat])
    assert len(lines) == 2
    assert lines[0].id == "ring_1_a"
    assert lines[1].id == "ring_1_b"
    assert lines[0].coordinates[0] != lines[0].coordinates[-1]
    assert lines[1].coordinates[0] != lines[1].coordinates[-1]


def test_compute_pst_six_syntax_layers_m4h_context():
    if not CONTEXT_PATH.exists() or not STUDY_AREA_PATH.exists():
        pytest.skip("retained M4H context or StudyArea fixture is unavailable")

    context = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    sa_feat = json.loads(STUDY_AREA_PATH.read_text(encoding="utf-8"))
    sa_geom = shape(sa_feat["geometry"])

    result = compute_pst_six_syntax_layers(
        context["features"],
        calculate_radii_m=[800.0],
        study_area_geometry=sa_geom,
        acquisition_envelope_geometry=None,
        extract_covers_envelope=False,
    )

    assert result["engine"] == "PST 3.3.1"
    assert result["network_segment_count"] > 0
    assert result["analysis_segment_count"] > 0
    assert len(result["layers"]) == 6

    # 800m layers should be COMPUTED
    layer_800_int = next(l for l in result["layers"] if l["layer_id"] == "syntax_local_800m_integration")
    layer_800_cho = next(l for l in result["layers"] if l["layer_id"] == "syntax_local_800m_choice")

    assert layer_800_int["calculation_status"] == "COMPUTED"
    assert layer_800_cho["calculation_status"] == "COMPUTED"
    assert layer_800_int["formula_version"] == "pstalgo-3.3.1-walking-radius-v1"
    assert layer_800_int["statistics"]["count"] == result["analysis_segment_count"]
    assert layer_800_int["statistics"]["max"] > 0.0
    assert layer_800_cho["statistics"]["count"] == result["analysis_segment_count"]

    # 2000m and 10000m should be NOT_COMPUTED_COVERAGE_BLOCKED
    layer_2k_int = next(l for l in result["layers"] if l["layer_id"] == "syntax_mid_2000m_integration")
    assert layer_2k_int["calculation_status"] == "NOT_COMPUTED_COVERAGE_BLOCKED"


def test_pst_output_describes_spatial_envelope_without_claiming_osm_completeness():
    study_area = box(0.0, 0.0, 100.0, 100.0)
    envelope = study_area.buffer(1000.0)
    features = [{
        "id": "way/1",
        "geometry": {"type": "LineString", "coordinates": [(0.0, 50.0), (100.0, 50.0)]},
    }]

    result = compute_pst_six_syntax_layers(
        features,
        calculate_radii_m=[800.0],
        study_area_geometry=study_area,
        acquisition_envelope_geometry=envelope,
        extract_covers_envelope=False,
        stability_validated_radii_m=[800.0],
    )

    assert result["extract_covers_envelope"] is False
    assert "source_complete" not in result
    local_layer = next(layer for layer in result["layers"] if layer["layer_id"] == "syntax_local_800m_integration")
    assert local_layer["data_readiness"] == "BLOCKED_EXTRACT_ENVELOPE_COVERAGE_UNVERIFIED"
    assert "completeness" in local_layer["limitations"].lower()


def test_compute_pst_six_syntax_layers_grade_separated_unlinks():
    # Two crossing features at (50, 50)
    features = [
        {
            "id": "h_way",
            "geometry": {"type": "LineString", "coordinates": [(0.0, 50.0), (100.0, 50.0)]},
        },
        {
            "id": "v_way",
            "geometry": {"type": "LineString", "coordinates": [(50.0, 0.0), (50.0, 100.0)]},
        },
    ]

    # Without unlinks: lines are split into 4 segments meeting at (50, 50)
    res_split = compute_pst_six_syntax_layers(features, calculate_radii_m=[800.0], unlinks=[])
    assert res_split["network_segment_count"] == 4

    # With unlinks: lines cross without forming a junction, keeping 2 segments
    res_unlinked = compute_pst_six_syntax_layers(features, calculate_radii_m=[800.0], unlinks=[(50.0, 50.0)])
    assert res_unlinked["network_segment_count"] == 2


def test_compute_pst_six_syntax_layers_metric_mode():
    features = [
        {
            "id": "line_1",
            "geometry": {"type": "LineString", "coordinates": [(0.0, 0.0), (100.0, 0.0)]},
        }
    ]
    res_int = compute_pst_six_syntax_layers(
        features,
        calculate_radii_m=[800.0],
        metric_mode="integration",
    )
    assert res_int["network_segment_count"] == 1
    layer_int = next(l for l in res_int["layers"] if l["layer_id"] == "syntax_local_800m_integration")
    assert layer_int["calculation_status"] == "COMPUTED"

    res_cho = compute_pst_six_syntax_layers(
        features,
        calculate_radii_m=[800.0],
        metric_mode="choice",
    )
    assert res_cho["network_segment_count"] == 1
    layer_cho = next(l for l in res_cho["layers"] if l["layer_id"] == "syntax_local_800m_choice")
    assert layer_cho["calculation_status"] == "COMPUTED"


def test_prepare_pst_lines_excludes_degenerate_and_duplicate_loops_and_records_reasons():
    features = [
        {
            "id": "main_road",
            "geometry": {"type": "LineString", "coordinates": [(0.0, 0.0), (100.0, 0.0)]},
        },
        {
            "id": "zero_len_way",
            "geometry": {"type": "LineString", "coordinates": [(50.0, 50.0), (50.0, 50.0)]},
        },
        {
            "id": "collapsed_ring",
            "geometry": {
                "type": "LineString",
                "coordinates": [(20.0, 0.0), (40.0, 0.0), (60.0, 0.0), (40.0, 0.0), (20.0, 0.0)],
            },
        },
        {
            "id": "triangle_loop",
            "geometry": {
                "type": "LineString",
                "coordinates": [(200.0, 0.0), (250.0, 50.0), (200.0, 50.0), (200.0, 0.0)],
            },
        },
        {
            "id": "duplicate_segment_way",
            "geometry": {
                "type": "LineString",
                "coordinates": [(200.0, 0.0), (250.0, 50.0)],
            },
        },
    ]

    lines, excluded = prepare_pst_lines(features, return_excluded=True)
    kept_ids = {l.id for l in lines}
    excluded_map = {e["id"]: e["reason"] for e in excluded}

    assert "main_road" in kept_ids
    assert "triangle_loop_a" in kept_ids
    assert "triangle_loop_b" in kept_ids
    assert "zero_len_way" in excluded_map
    assert excluded_map["zero_len_way"] == "zero_length"
    assert "collapsed_ring_b" in excluded_map
    assert excluded_map["collapsed_ring_b"] == "degenerate_collapsed_loop"
    assert "duplicate_segment_way" in excluded_map
    assert excluded_map["duplicate_segment_way"] == "duplicate_segments"


def test_compute_pst_syntax_with_degenerate_loop_fixture_succeeds_unaffected():
    main_feature = {
        "id": "main_corridor",
        "geometry": {"type": "LineString", "coordinates": [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]},
    }
    degen_feature = {
        "id": "degen_ring",
        "geometry": {
            "type": "LineString",
            "coordinates": [(10.0, 0.0), (25.0, 0.0), (40.0, 0.0), (25.0, 0.0), (10.0, 0.0)],
        },
    }
    zero_feature = {
        "id": "point_line",
        "geometry": {"type": "LineString", "coordinates": [(0.0, 0.0), (0.0, 0.0)]},
    }

    # Run with degenerate fixture present
    result_with_degen = compute_pst_six_syntax_layers(
        [main_feature, degen_feature, zero_feature],
        calculate_radii_m=[800.0],
    )
    assert result_with_degen["network_segment_count"] > 0
    excluded = result_with_degen["excluded_lines"]
    excluded_ids = {e["id"] for e in excluded}
    assert "point_line" in excluded_ids
    assert "degen_ring_b" in excluded_ids

    # Run clean baseline
    result_clean = compute_pst_six_syntax_layers(
        [main_feature],
        calculate_radii_m=[800.0],
    )

    # Main corridor statistics and segment count must match
    clean_layer = next(l for l in result_clean["layers"] if l["layer_id"] == "syntax_local_800m_integration")
    degen_layer = next(l for l in result_with_degen["layers"] if l["layer_id"] == "syntax_local_800m_integration")
    # All main corridor segments present in clean must have identical values in degen run
    for seg_id, val in clean_layer["segment_values"].items():
        assert seg_id in degen_layer["segment_values"]
        assert math.isclose(degen_layer["segment_values"][seg_id], val, rel_tol=1e-5)
