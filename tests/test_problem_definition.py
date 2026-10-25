"""Tests for spatial problem definition (Understand -> Define) in Rotterdam M4H."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.morphology_dictionary import load_dictionary
from urban_design.problem_definition import (
    ProblemDefinitionBundle,
    classify_review_severity,
    run_problem_definition_analysis,
)
from scripts.build_problem_definition import (
    load_context_data,
    load_normalized_inputs,
    load_study_area,
    load_syntax_layer0,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts/w6-problem-definition"
FIGURES_DIR = ARTIFACTS_DIR / "figures"


@pytest.fixture(scope="module")
def analysis_bundle() -> ProblemDefinitionBundle:
    sa_geom, sa_id = load_study_area()
    bag_features, water_features, osm_features = load_normalized_inputs()
    green_features, _ = load_context_data()
    syntax_layer0 = load_syntax_layer0()

    return run_problem_definition_analysis(
        study_area_geom=sa_geom,
        bag_features=bag_features,
        water_features=water_features,
        road_features=osm_features,
        context_green_features=green_features,
        context_bag_features=bag_features,
        syntax_candidate_layer0=syntax_layer0,
        study_area_id=sa_id,
    )


def test_problem_definition_analysis_recomputable(analysis_bundle: ProblemDefinitionBundle) -> None:
    """Test that all 6 problem definitions are deterministically computed and populated."""
    assert len(analysis_bundle.problems) == 6
    assert round(analysis_bundle.study_area_area_m2, 1) == 226064.3
    assert round(analysis_bundle.water_area_m2, 1) == 42473.0
    assert round(analysis_bundle.land_area_m2, 1) == 183591.3

    problem_ids = [p.problem_id for p in analysis_bundle.problems]
    expected_ids = [
        "prob-01-functional-monoculture",
        "prob-02-spatial-fragmentation",
        "prob-03-sociospatial-isolation",
        "prob-04-ecological-disconnection",
        "prob-05-waterfront-inaccessibility",
        "prob-06-unclassified-residual-ground",
    ]
    assert problem_ids == expected_ids

    # Prob 1: Functional monoculture
    p1 = analysis_bundle.problems[0]
    assert p1.metrics["residential_share_site"] == 0.0
    assert p1.metrics["industrial_share_site"] > 40.0
    assert p1.statement.status == "CONFIRMED_BASELINE"

    # Prob 2: Spatial fragmentation
    p2 = analysis_bundle.problems[1]
    assert p2.metrics["road_degree_one_vertex_count"] > 30
    assert p2.metrics["road_degree_ge3_vertex_density"] > 0
    assert p2.metrics["walking_detour_ratio"] > 1.3
    assert p2.metrics["max_building_footprint_long_axis_m"] > 200.0

    # Prob 3: Socio-spatial isolation
    p3 = analysis_bundle.problems[2]
    assert p3.metrics["syntax_pedestrian_800m_nain_mean"] > 0.0
    assert p3.metrics["north_boundary_osm_intersections_count"] > 0

    # Prob 4: Ecological disconnection
    p4 = analysis_bundle.problems[3]
    assert p4.metrics["green_coverage_percentage"] < 15.0
    assert p4.metrics["green_polygon_nearest_gap_over_40m_count"] >= 0

    # Prob 5: Waterfront inaccessibility
    p5 = analysis_bundle.problems[4]
    assert p5.metrics["osmped_way_quay_proximity_pct"] < 25.0
    assert p5.metrics["water_land_interface_length_m"] > 1300.0

    # Prob 6: Unclassified residual ground (AI-discovered)
    p6 = analysis_bundle.problems[5]
    assert p6.statement.is_designer_baseline is False
    assert p6.statement.status == "PENDING_DESIGNER_CONFIRMATION"
    assert p6.metrics["nonbuilding_nonwater_residual_ratio_pct"] > 60.0


def test_s2_review_recalculated_metrics_and_rule_generated_severity(
    analysis_bundle: ProblemDefinitionBundle,
) -> None:
    """Bind reviewed numbers to the frozen inputs and expose only supported comparisons."""
    assert analysis_bundle.metadata["severity_rules_version"] == "s2-review-bands-v1"

    p1, p2, p3, p4, p5, p6 = analysis_bundle.problems
    assert p1.metrics["residential_share_site"] == 0.0
    p1_metric = {metric.key: metric for metric in p1.statement.metrics}
    assert p1_metric["residential_share_site"].comparison_value == 71.37
    assert p1_metric["industrial_share_site"].comparison_value == 8.13
    assert p1.metrics["unknown_usage_building_count"] == 20
    assert p1.metrics["demolished_building_count"] == 19
    assert p1.metrics["unknown_or_demolished_building_count"] == 29
    assert p1.metrics["site_building_feature_count"] == 51
    assert p1.metrics["site_known_usage_tag_count"] == 43
    assert p1.metrics["site_residential_usage_tag_count"] == 0
    assert p1.metrics["site_industrial_usage_tag_count"] == 19
    assert p1.metrics["context_ring_building_feature_count"] == 3762
    assert p1.metrics["context_ring_known_usage_tag_count"] == 3395
    assert p1.metrics["context_ring_residential_usage_tag_count"] == 2423
    assert p1.metrics["context_ring_industrial_usage_tag_count"] == 276

    assert p2.metrics["road_degree_one_vertex_count"] == 44
    assert p2.metrics["road_degree_ge3_vertex_density"] == 10.73
    assert p2.metrics["walking_detour_ratio"] == 1.49
    assert p2.metrics["max_walking_detour_ratio"] == 2.46
    assert p2.metrics["walking_detour_sample_pair_count"] == 57
    assert p2.metrics["max_building_footprint_long_axis_m"] == 213.02
    assert p2.metrics["total_osm_road_line_length_m"] == 8424.18
    assert p2.metrics["highway_service_line_length_m"] == 3424.99
    assert p2.metrics["selected_path_network_line_length_m"] == 3472.79
    assert p2.metrics["service_road_ratio"] == 40.66
    assert p2.metrics["long_building_footprint_over_80m_count"] == 6
    assert p2.metrics["polygonized_blocks_over_1ha_count"] == 3

    assert p3.metrics["north_boundary_osm_intersections_count"] == 12
    assert p3.metrics["all_boundary_osm_intersections_count"] == 22
    assert p3.metrics["syntax_pedestrian_800m_nain_mean"] == 0.7828
    assert p3.metrics["syntax_zero_nain_segment_count"] == 1
    assert p3.metrics["syntax_source_segment_count"] == 481
    assert "syntax_pedestrian_800m_nain_delta" not in p3.metrics
    assert "longest_uncrossed_boundary_segment" not in p3.metrics

    assert p4.metrics["site_green_area_m2"] == 21876.82
    assert p4.metrics["green_coverage_percentage"] == 9.68
    assert p4.metrics["site_green_polygon_count"] == 18
    assert p4.metrics["green_polygon_nearest_gap_over_40m_count"] == 1
    assert "north_south_corridor_gap" not in p4.metrics

    assert p5.metrics["water_land_interface_length_m"] == 1330.2
    assert p5.metrics["quay_near_osm_pedestrian_way_m"] == 202.94
    assert p5.metrics["osmped_way_quay_proximity_pct"] == 15.26
    assert p5.metrics["quay_without_nearby_osm_pedestrian_way_m"] == 1127.26

    assert p6.metrics["nonbuilding_nonwater_residual_area_m2"] == 138891.77
    assert p6.metrics["nonbuilding_nonwater_residual_ratio_pct"] == 61.44
    assert p6.metrics["residual_polygons_over_5000m2_count"] == 1

    assert [problem.statement.severity_code for problem in analysis_bundle.problems] == [
        "CRITICAL",
        "HIGH",
        "UNRATED",
        "CRITICAL",
        "HIGH",
        "UNRATED",
    ]
    for problem in analysis_bundle.problems:
        statement = problem.statement
        assert statement.severity_rule_id
        assert statement.severity_basis_zh
        assert statement.severity_code in {"CRITICAL", "HIGH", "MODERATE", "LOW", "UNRATED"}

    assert "road_degree_one_vertex_count" in p2.metrics
    assert "cul_de_sac_count" not in p2.metrics
    assert "road_degree_ge3_vertex_density" in p2.metrics
    assert "intersection_density" not in p2.metrics
    assert "syntax_pedestrian_800m_nain_delta" not in p3.metrics
    assert "north_south_corridor_gap" not in p4.metrics


def test_s2_severity_bands_have_explicit_reproducible_boundaries() -> None:
    assert classify_review_severity("relative_coverage_v1", 25, 100).code == "CRITICAL"
    assert classify_review_severity("relative_coverage_v1", 50, 100).code == "HIGH"
    assert classify_review_severity("relative_coverage_v1", 75, 100).code == "MODERATE"
    assert classify_review_severity("relative_coverage_v1", 76, 100).code == "LOW"

    assert classify_review_severity("detour_vs_direct_v1", 1.0, 1.0).code == "LOW"
    assert classify_review_severity("detour_vs_direct_v1", 1.25, 1.0).code == "MODERATE"
    assert classify_review_severity("detour_vs_direct_v1", 1.50, 1.0).code == "HIGH"
    assert classify_review_severity("detour_vs_direct_v1", 1.51, 1.0).code == "CRITICAL"

    assert classify_review_severity("measured_share_v1", 10).code == "CRITICAL"
    assert classify_review_severity("measured_share_v1", 25).code == "HIGH"
    assert classify_review_severity("measured_share_v1", 50).code == "MODERATE"
    assert classify_review_severity("measured_share_v1", 50.01).code == "LOW"
    assert classify_review_severity("unrated_nonsemantic_geometry_v1").code == "UNRATED"


def test_problem_evidence_and_limitations(analysis_bundle: ProblemDefinitionBundle) -> None:
    """Verify that every problem has evidence references, limitations, and portfolio alignment."""
    valid_evidence_levels = {"COMPUTED_RESULT", "DATASET_OBSERVATION", "DATA_GAP", "PROJECT_DECISION"}

    for problem in analysis_bundle.problems:
        stmt = problem.statement
        assert len(stmt.evidence_ids) > 0, f"{stmt.problem_id} missing evidence_ids"
        assert len(stmt.limitations) > 0, f"{stmt.problem_id} missing limitations"
        assert len(stmt.uncertainties_zh) > 0, f"{stmt.problem_id} missing uncertainties_zh"
        assert len(stmt.location_zh) > 0, f"{stmt.problem_id} missing location_zh"
        assert len(stmt.severity_zh) > 0, f"{stmt.problem_id} missing severity_zh"
        assert len(stmt.jack_portfolio_response_zh) > 0, f"{stmt.problem_id} missing jack_portfolio_response_zh"

        # Check evidence claims format
        for eid in stmt.evidence_ids:
            assert eid.startswith("claim-w5-site-"), f"Unexpected evidence ID format: {eid}"

        # Check metrics items
        for m in stmt.metrics:
            assert m.evidence_level in valid_evidence_levels, f"Invalid evidence level {m.evidence_level} in {m.key}"
            assert len(m.limitations) > 0, f"Metric {m.key} missing limitations"


def test_morphology_recommendation_ids_exist(analysis_bundle: ProblemDefinitionBundle) -> None:
    """Verify that all recommended morphology dictionary entries exist in config/morphology-dictionary."""
    dictionary = load_dictionary()
    catalogue = dictionary["entry_by_id"]

    for problem in analysis_bundle.problems:
        recs = problem.statement.recommended_morphology
        assert len(recs) >= 3, f"{problem.problem_id} has fewer than 3 morphology recommendations"
        for rec in recs:
            assert rec.entry_id in catalogue, f"Unknown morphology entry ID {rec.entry_id} in {problem.problem_id}"
            assert len(rec.name_zh) > 0
            assert len(rec.rationale_zh) > 0
            assert rec.level in {"building_plan", "block_assembly", "street_open_space"}


def test_problem_geojson_layers_validity(analysis_bundle: ProblemDefinitionBundle) -> None:
    """Verify that all generated problem GeoJSON layers are valid EPSG:28992 FeatureCollections."""
    for problem in analysis_bundle.problems:
        layer = problem.geojson_layer
        assert layer.get("type") == "FeatureCollection"
        assert "features" in layer
        assert len(layer["features"]) > 0, f"{problem.problem_id} GeoJSON layer is empty"
        assert layer.get("crs", {}).get("properties", {}).get("name") == "urn:ogc:def:crs:EPSG::28992"

        for feat in layer["features"]:
            assert feat.get("type") == "Feature"
            assert "geometry" in feat
            assert feat["geometry"] is not None
            assert "properties" in feat


def test_reviewed_geojson_uses_observation_scoped_feature_types() -> None:
    p2 = json.loads((ARTIFACTS_DIR / "problem_02_spatial_fragmentation.geojson").read_text(encoding="utf-8"))
    p3 = json.loads((ARTIFACTS_DIR / "problem_03_sociospatial_isolation.geojson").read_text(encoding="utf-8"))
    p4 = json.loads((ARTIFACTS_DIR / "problem_04_ecological_disconnection.geojson").read_text(encoding="utf-8"))
    p5 = json.loads((ARTIFACTS_DIR / "problem_05_waterfront_inaccessibility.geojson").read_text(encoding="utf-8"))
    p6 = json.loads((ARTIFACTS_DIR / "problem_06_unclassified_residual_ground.geojson").read_text(encoding="utf-8"))

    p2_types = {feature["properties"].get("feature_type") for feature in p2["features"]}
    assert "osm_line_degree_one_vertex" in p2_types
    assert "polygonized_road_area_over_1ha" in p2_types
    assert "cul_de_sac_dead_end" not in p2_types
    assert "continuous_barrier_building" not in p2_types

    assert all("boundary_intersection_type" in feature["properties"] for feature in p3["features"])
    assert all("is_northern_residential_gateway" not in feature["properties"] for feature in p3["features"])

    assert all(feature["properties"].get("feature_type") == "osm_green_tag_polygon_piece" for feature in p4["features"])
    assert all("is_isolated" not in feature["properties"] for feature in p4["features"])

    p5_statuses = {feature["properties"].get("quay_status") for feature in p5["features"]}
    assert p5_statuses <= {"NEAR_SELECTED_OSM_WAY", "NO_SELECTED_OSM_WAY_WITHIN_22M"}
    assert "ACCESSIBLE_PUBLIC" not in p5_statuses

    assert all("severity" not in feature["properties"] for feature in p6["features"])


def test_exported_artifacts_integrity() -> None:
    """Verify that exported files in artifacts/w6-problem-definition exist and match schemas."""
    expected_files = [
        "problem_01_functional_monoculture.geojson",
        "problem_02_spatial_fragmentation.geojson",
        "problem_03_sociospatial_isolation.geojson",
        "problem_04_ecological_disconnection.geojson",
        "problem_05_waterfront_inaccessibility.geojson",
        "problem_06_unclassified_residual_ground.geojson",
        "problem-statements.json",
        "problem-summary.json",
    ]
    for filename in expected_files:
        p = ARTIFACTS_DIR / filename
        assert p.exists(), f"Missing exported artifact: {p}"
        assert p.stat().st_size > 0, f"Empty exported artifact: {p}"

    # Verify statements json
    statements_data = json.loads((ARTIFACTS_DIR / "problem-statements.json").read_text(encoding="utf-8"))
    assert "statements" in statements_data
    assert len(statements_data["statements"]) == 6

    # Verify summary json
    summary_data = json.loads((ARTIFACTS_DIR / "problem-summary.json").read_text(encoding="utf-8"))
    assert summary_data["problem_count"] == 6
    assert all(row["severity_code"] in {"CRITICAL", "HIGH", "MODERATE", "LOW", "UNRATED"} for row in summary_data["problems"])
    inventory = summary_data["metadata"]["source_inventory"]
    assert inventory["crs"] == "EPSG:28992"
    assert inventory["source_metadata"]["pst_candidate"]["data_readiness"] == "BLOCKED_BOUNDARY_STABILITY_UNASSESSED"
    assert len(inventory["inputs"]) >= 20
    assert all(len(row["sha256"]) == 64 and row["bytes"] > 0 for row in inventory["inputs"])


def test_rendered_figures_exist() -> None:
    """Verify that all 6 map figures exist as non-empty PNG files."""
    expected_figures = [
        "fig01_problem_functional_monoculture.png",
        "fig02_problem_spatial_fragmentation.png",
        "fig03_problem_sociospatial_isolation.png",
        "fig04_problem_ecological_disconnection.png",
        "fig05_problem_waterfront_inaccessibility.png",
        "fig06_problem_unclassified_residual_ground.png",
    ]
    for f_name in expected_figures:
        p = FIGURES_DIR / f_name
        assert p.exists(), f"Missing figure file: {p}"
        # PNG signature check and size
        data = p.read_bytes()
        assert len(data) > 50000, f"Figure {f_name} too small ({len(data)} bytes)"
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"Figure {f_name} lacks valid PNG header"


def test_problem_definition_api_endpoints(tmp_path: Path) -> None:
    """Test read-only API endpoints for spatial problem definitions."""
    from urban_design.store import ProjectStateStore

    store_path = tmp_path / "test.sqlite3"
    store = ProjectStateStore(store_path)
    db_before = hashlib.sha256(store_path.read_bytes()).hexdigest()
    artifacts_before = {
        str(path.relative_to(ARTIFACTS_DIR)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(ARTIFACTS_DIR.rglob("*"))
        if path.is_file()
    }
    app = create_workspace_app(store=store)
    client = TestClient(app)

    problem_routes = [
        route for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/projects/{project_id}/problems")
    ]
    assert problem_routes
    assert all(route.methods == {"GET"} for route in problem_routes)

    # 1. GET problems list
    resp = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/problems")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == "rotterdam-m4h-pilot-project"
    assert data["status"] == "ANALYSIS_DEFINED"
    assert len(data["statements"]) == 6

    # 2. GET specific problem detail
    resp_detail = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/problems/prob-01-functional-monoculture")
    assert resp_detail.status_code == 200
    detail_data = resp_detail.json()
    assert detail_data["problem_id"] == "prob-01-functional-monoculture"
    assert detail_data["statement"]["status"] == "CONFIRMED_BASELINE"
    assert len(detail_data["statement"]["recommended_morphology"]) >= 3

    # 3. GET problem GeoJSON layer
    resp_geo = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/problems/prob-01-functional-monoculture/geojson")
    assert resp_geo.status_code == 200
    geo_data = resp_geo.json()
    assert geo_data["type"] == "FeatureCollection"
    assert len(geo_data["features"]) > 0

    # 4. Unknown problem ID
    resp_404 = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/problems/prob-99-non-existent")
    assert resp_404.status_code == 404

    assert hashlib.sha256(store_path.read_bytes()).hexdigest() == db_before
    artifacts_after = {
        str(path.relative_to(ARTIFACTS_DIR)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(ARTIFACTS_DIR.rglob("*"))
        if path.is_file()
    }
    assert artifacts_after == artifacts_before
