from datetime import datetime, timezone

import pytest
from shapely.geometry import LineString, box

from urban_design.site_analysis import calculate_site_metrics
from urban_design.site_intelligence.adapters import ExistingAnalysisResults, build_analysis_bundle
from urban_design.site_intelligence.contracts import AnalysisExtent, FrozenRef


def ref(identifier, digest="a"):
    return FrozenRef(id=identifier, revision=1, sha256="sha256:" + digest * 64)


WORKSPACE = ref("fixture-workspace", "f")
STUDY_AREA = ref("fixture-study-area", "a")
BAG_INPUT = ref("fixture-bag-snapshot", "b")
WATER_INPUT = ref("fixture-water-snapshot", "c")
ROAD_INPUT = ref("fixture-road-snapshot", "d")


def build(results, *, method_config=None, source_refs=(BAG_INPUT, WATER_INPUT, ROAD_INPUT)):
    return build_analysis_bundle(
        workspace_ref=WORKSPACE,
        study_area_ref=STUDY_AREA,
        source_refs=source_refs,
        method_config=method_config or {},
        results=results,
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )


def observation(bundle, key):
    return next(item for item in bundle.observations if item.metric_key == key)


def test_missing_land_use_is_blocked_not_a_residential_zero():
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id=STUDY_AREA.id,
        building_features=[],
        water_features=[],
        road_features=[],
    )
    bundle = build(ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED"))

    residential = observation(bundle, "building.registered_residential_count")
    assert residential.status == "BLOCKED"
    assert residential.value is None
    assert observation(bundle, "building.registered_use_distribution").status == "BLOCKED"


def test_analysis_that_was_never_run_is_not_reported_as_blocked_or_zero():
    bundle = build(ExistingAnalysisResults())
    for key in (
        "building.count",
        "building.registered_residential_count",
        "building.height_median_m",
        "building.floor_area_ratio",
    ):
        item = observation(bundle, key)
        assert item.status == "NOT_RUN"
        assert item.value is None


def test_complete_empty_source_can_report_zero_with_explicit_coverage():
    complete = {
        source: {"status": "DECLARED_COMPLETE_WITHIN_SCOPE", "evidence_refs": [f"fixture:{source}"]}
        for source in ("buildings", "water", "roads")
    }
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id=STUDY_AREA.id,
        building_features=[],
        water_features=[],
        road_features=[],
        source_coverage=complete,
    )
    bundle = build(ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED"))

    residential = observation(bundle, "building.registered_residential_count")
    assert residential.status == "PARTIAL"
    assert residential.value == 0.0
    assert "PROVENANCE_NOT_VERIFIED" in residential.limitation_codes


def test_existing_calculation_values_and_limits_are_projected_without_recalculation():
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 50, 20),
        study_area_id=STUDY_AREA.id,
        building_features=[
            {"id": "b1", "geometry": box(5, 5, 15, 15), "properties": {"gebruiksdoel": "woonfunctie"}},
            {"id": "b2", "geometry": box(25, 5, 35, 15), "properties": {"gebruiksdoel": "industriefunctie"}},
        ],
        water_features=[],
        road_features=[],
        source_coverage={
            "buildings": {"status": "DECLARED_COMPLETE_WITHIN_SCOPE", "evidence_refs": ["fixture:bag"]},
            "water": {"status": "DECLARED_COMPLETE_WITHIN_SCOPE", "evidence_refs": ["fixture:water"]},
            "roads": {"status": "DECLARED_COMPLETE_WITHIN_SCOPE", "evidence_refs": ["fixture:roads"]},
        },
    )
    results = ExistingAnalysisResults(
        site_metrics=metrics,
        site_status="COMPUTED",
        site_method_version="site-analysis-m4h-v1",
        tool_versions={"site_analysis": "site-analysis-m4h-v1"},
    )
    bundle = build(results, method_config={"clip_tolerance_m": 0.001})

    assert observation(bundle, "building.footprint_union_area_m2").value == 200.0
    assert observation(bundle, "building.ground_coverage_ratio").value == 0.2
    assert observation(bundle, "building.ground_coverage_ratio").status == "PARTIAL"
    assert observation(bundle, "building.height_median_m").value is None
    assert observation(bundle, "building.height_median_m").status == "BLOCKED"
    assert bundle.method_parameters == {"clip_tolerance_m": 0.001}
    assert bundle.tool_versions["site_analysis"] == "site-analysis-m4h-v1"


def test_height_and_far_remain_unknown_even_when_a_three_metre_parameter_exists():
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id=STUDY_AREA.id,
        building_features=[],
        water_features=[],
        road_features=[],
    )
    bundle = build(
        ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED"),
        method_config={"illustrative_floor_height_m": 3.0},
    )
    assert observation(bundle, "building.height_median_m").value is None
    assert observation(bundle, "building.floor_area_ratio").value is None
    assert observation(bundle, "building.height_median_m").status == "BLOCKED"


def test_stale_loader_status_suppresses_old_numeric_values():
    metrics = {
        "study_area_area_m2": 100.0,
        "source_data_status": {"buildings": "DECLARED_COMPLETE_WITHIN_SCOPE"},
        "building_count": 0,
        "building_footprint_area_m2": 0.0,
        "ground_coverage_ratio": 0.0,
        "height_status": "UNAVAILABLE",
        "far_status": "UNAVAILABLE",
        "calculated_far": None,
        "data_gaps": [],
    }
    bundle = build(ExistingAnalysisResults(site_metrics=metrics, site_status="STALE"))
    building = observation(bundle, "building.ground_coverage_ratio")
    assert building.status == "BLOCKED"
    assert building.value is None
    assert "STALE" in building.limitation_codes


def test_unrecognized_site_loader_status_suppresses_values():
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id=STUDY_AREA.id,
        building_features=[{"id": "b1", "geometry": box(10, 10, 20, 20), "properties": {}}],
        water_features=[],
        road_features=[],
    )
    bundle = build(ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED_WITH_WARNING"))
    item = observation(bundle, "building.ground_coverage_ratio")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "COMPUTED_WITH_WARNING" in item.limitation_codes


def test_unrecognized_syntax_loader_status_suppresses_values():
    extent = AnalysisExtent(
        id="pedestrian-800m", study_area_ref=STUDY_AREA, display_radius_m=800.0,
        calculation_radius_m=800.0, network_mode="pedestrian",
    )
    bundle = build(
        ExistingAnalysisResults(
            syntax_status="READY",
            syntax_bundle={"engine": "fixture-engine", "layers": [{
                "id": "syntax_local_800m_integration", "radius_m": 800.0,
                "network_mode": "pedestrian", "calculation_status": "COMPUTED",
                "statistics": {"mean": 0.4}, "unit": "NAIN",
            }]},
            analysis_extents=(extent,),
            metric_input_refs={"syntax_local_800m_integration": (ROAD_INPUT,)},
        ),
        source_refs=(ROAD_INPUT,),
    )
    item = observation(bundle, "syntax_local_800m_integration")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "READY" in item.limitation_codes


def test_problem_definition_projection_preserves_metric_limits_and_requires_scope():
    problem_summary = {
        "metadata": {"methodology": "deterministic-spatial-fixture-v1"},
        "problems": [
            {
                "problem_id": "prob-02-spatial-fragmentation",
                "status": "CONFIRMED_BASELINE",
                "limitations": ["Coordinate-vertex degree does not verify access."],
                "metrics": [
                    {
                        "key": "road_degree_one_vertex_count",
                        "value": 1,
                        "unit": "vertices",
                        "evidence_level": "COMPUTED_RESULT",
                        "limitations": [
                            "Degree-one vertices are not confirmed dead ends.",
                            "Source-specific caveat: grade separation is unknown.",
                        ],
                    }
                ],
            }
        ],
    }
    results = ExistingAnalysisResults(
        problem_definition=problem_summary,
        problem_status="COMPUTED",
        metric_scope_refs={"road_degree_one_vertex_count": STUDY_AREA},
        metric_input_refs={"road_degree_one_vertex_count": (ROAD_INPUT,)},
    )
    bundle = build(results, source_refs=(ROAD_INPUT,))
    degree = observation(bundle, "road_degree_one_vertex_count")
    assert degree.value == 1.0
    assert degree.status == "PARTIAL"
    assert "DEGREE_ONE_IS_NOT_DEAD_END" in degree.limitation_codes
    assert degree.limitation_details == (
        "Coordinate-vertex degree does not verify access.",
        "Degree-one vertices are not confirmed dead ends.",
        "Source-specific caveat: grade separation is unknown.",
    )
    assert observation(bundle, "road_degree_one_vertex_count").input_refs == (ROAD_INPUT, STUDY_AREA)

    no_scope = ExistingAnalysisResults(
        problem_definition=problem_summary,
        problem_status="COMPUTED",
        metric_input_refs={"road_degree_one_vertex_count": (ROAD_INPUT,)},
    )
    no_scope_bundle = build(no_scope, source_refs=(ROAD_INPUT,))
    assert observation(no_scope_bundle, "road_degree_one_vertex_count").status == "BLOCKED"
    assert observation(no_scope_bundle, "road_degree_one_vertex_count").value is None


def test_syntax_adaptation_keeps_mode_radius_and_extraction_buffer_distinct():
    extents = (
        AnalysisExtent(
            id="pedestrian-800m",
            study_area_ref=STUDY_AREA,
            display_radius_m=800.0,
            calculation_radius_m=800.0,
            source_extraction_buffer_m=1500.0,
            network_mode="pedestrian",
        ),
        AnalysisExtent(
            id="bicycle-2000m",
            study_area_ref=STUDY_AREA,
            display_radius_m=2000.0,
            calculation_radius_m=2000.0,
            source_extraction_buffer_m=6000.0,
            network_mode="bicycle",
        ),
        AnalysisExtent(
            id="motor-vehicle-10000m",
            study_area_ref=STUDY_AREA,
            display_radius_m=10000.0,
            calculation_radius_m=10000.0,
            source_extraction_buffer_m=20000.0,
            network_mode="motor_vehicle",
        ),
    )
    syntax = {
        "engine": "PST_3.3.1_EXPLORATORY",
        "layers": [
            {
                "id": "syntax_local_800m_integration",
                "metric_key": "syntax_local_800m_integration",
                "network_mode": "pedestrian",
                "radius_m": 800.0,
                "calculation_status": "COMPUTED",
                "statistics": {"mean": 0.4},
                "unit": "NAIN (normalized)",
            }
        ],
    }
    results = ExistingAnalysisResults(
        syntax_bundle=syntax,
        syntax_status="COMPUTED",
        metric_input_refs={"syntax_local_800m_integration": (ROAD_INPUT,)},
        analysis_extents=extents,
        tool_versions={"pst": "PST_3.3.1_EXPLORATORY"},
    )
    bundle = build(results, source_refs=(ROAD_INPUT,))
    assert bundle.analysis_extents == extents
    assert bundle.analysis_extents[0].display_radius_m == 800.0
    assert bundle.analysis_extents[0].source_extraction_buffer_m == 1500.0
    syntax_observation = observation(bundle, "syntax_local_800m_integration")
    assert syntax_observation.value == 0.4
    assert syntax_observation.status == "PARTIAL"
    assert "SYNTAX_IS_NOT_MEASURED_PEDESTRIAN_OR_TRAFFIC_FLOW" in syntax_observation.limitation_codes
    assert "overall_syntax_score" not in {item.metric_key for item in bundle.observations}


def test_stale_syntax_loader_returns_null_values():
    syntax = {
        "layers": [
            {
                "id": "syntax_local_800m_integration",
                "calculation_status": "COMPUTED",
                "statistics": {"mean": 0.4},
                "unit": "NAIN (normalized)",
            }
        ]
    }
    bundle = build(
        ExistingAnalysisResults(
            syntax_bundle=syntax,
            syntax_status="STALE",
            metric_input_refs={"syntax_local_800m_integration": (ROAD_INPUT,)},
        ),
        source_refs=(ROAD_INPUT,),
    )
    syntax_observation = observation(bundle, "syntax_local_800m_integration")
    assert syntax_observation.status == "BLOCKED"
    assert syntax_observation.value is None


def test_persisted_syntax_layer_plan_preserves_blocked_readiness_and_empty_coverage():
    extent = AnalysisExtent(
        id="pedestrian-800m",
        study_area_ref=STUDY_AREA,
        display_radius_m=800.0,
        calculation_radius_m=800.0,
        source_extraction_buffer_m=1500.0,
        network_mode="pedestrian",
        input_refs=(ROAD_INPUT,),
    )
    syntax = {
        "engine": "PST 3.3.1",
        "layer_plan": [
            {
                "layer_id": "syntax_local_800m_integration",
                "metric_key": "nain",
                "radius_m": 800.0,
                "calculation_status": "COMPUTED",
                "data_readiness": "BLOCKED_BOUNDARY_STABILITY_UNASSESSED",
                "statistics": {"mean": 0.0, "count": 0},
                "segment_values": {},
                "formula_version": "pstalgo-3.3.1-walking-radius-v1",
                "unit": "NAIN (normalized)",
            }
        ],
    }
    bundle = build(
        ExistingAnalysisResults(
            syntax_bundle=syntax,
            syntax_status="VERIFIED_SOURCE_RESULT_ALIGNMENT",
            analysis_extents=(extent,),
            tool_versions={"pst": "3.3.1"},
        ),
        source_refs=(ROAD_INPUT,),
    )
    item = observation(bundle, "syntax_local_800m_integration")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "BLOCKED_BOUNDARY_STABILITY_UNASSESSED" in item.limitation_codes


@pytest.mark.parametrize(
    ("radius", "mode"),
    [(1200.0, "pedestrian"), (800.0, "bicycle")],
)
def test_syntax_extent_id_must_match_radius_and_network_mode(radius, mode):
    extent = AnalysisExtent(
        id="pedestrian-800m", study_area_ref=STUDY_AREA, display_radius_m=800.0,
        calculation_radius_m=800.0, network_mode="pedestrian",
    )
    bundle = build(
        ExistingAnalysisResults(
            syntax_status="COMPUTED",
            syntax_bundle={"engine": "fixture-engine", "layers": [{
                "id": "syntax_local_800m_integration", "extent_id": extent.id,
                "radius_m": radius, "network_mode": mode, "calculation_status": "COMPUTED",
                "statistics": {"mean": 0.4}, "unit": "NAIN",
            }]},
            analysis_extents=(extent,),
            metric_input_refs={"syntax_local_800m_integration": (ROAD_INPUT,)},
        ),
        source_refs=(ROAD_INPUT,),
    )
    item = observation(bundle, "syntax_local_800m_integration")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "ANALYSIS_EXTENT_MISMATCH" in item.limitation_codes


def test_syntax_extent_id_must_belong_to_bundle_study_area():
    other_study_area = ref("other-study-area", "e")
    extent = AnalysisExtent(
        id="other-pedestrian-800m", study_area_ref=other_study_area, display_radius_m=800.0,
        calculation_radius_m=800.0, network_mode="pedestrian",
    )
    bundle = build(
        ExistingAnalysisResults(
            syntax_status="COMPUTED",
            syntax_bundle={"engine": "fixture-engine", "layers": [{
                "id": "syntax_local_800m_integration", "extent_id": extent.id,
                "radius_m": 800.0, "network_mode": "pedestrian", "calculation_status": "COMPUTED",
                "statistics": {"mean": 0.4}, "unit": "NAIN",
            }]},
            analysis_extents=(extent,),
            metric_input_refs={"syntax_local_800m_integration": (ROAD_INPUT,)},
        ),
        source_refs=(ROAD_INPUT,),
    )
    item = observation(bundle, "syntax_local_800m_integration")
    assert item.status == "BLOCKED"
    assert item.scope_ref == STUDY_AREA
    assert "ANALYSIS_EXTENT_MISMATCH" in item.limitation_codes


def test_syntax_zero_mean_is_a_valid_value_when_observation_count_is_positive():
    extent = AnalysisExtent(
        id="pedestrian-800m", study_area_ref=STUDY_AREA, display_radius_m=800.0,
        calculation_radius_m=800.0, network_mode="pedestrian",
    )
    bundle = build(
        ExistingAnalysisResults(
            syntax_status="COMPUTED",
            syntax_bundle={"engine": "fixture-engine", "layers": [{
                "id": "syntax_local_800m_integration", "extent_id": extent.id,
                "radius_m": 800.0, "network_mode": "pedestrian", "calculation_status": "COMPUTED",
                "statistics": {"mean": 0.0, "count": 12}, "unit": "NAIN",
            }]},
            analysis_extents=(extent,),
            metric_input_refs={"syntax_local_800m_integration": (ROAD_INPUT,)},
        ),
        source_refs=(ROAD_INPUT,),
    )
    item = observation(bundle, "syntax_local_800m_integration")
    assert item.status == "PARTIAL"
    assert item.value == 0.0


@pytest.mark.parametrize("segment_values", [None, [], {}, 0.0])
def test_syntax_zero_count_is_missing_coverage_for_all_segment_value_shapes(segment_values):
    extent = AnalysisExtent(
        id="pedestrian-800m", study_area_ref=STUDY_AREA, display_radius_m=800.0,
        calculation_radius_m=800.0, network_mode="pedestrian",
    )
    layer = {
        "id": "syntax_local_800m_integration", "extent_id": extent.id,
        "radius_m": 800.0, "network_mode": "pedestrian", "calculation_status": "COMPUTED",
        "statistics": {"mean": 0.0, "count": 0}, "unit": "NAIN",
    }
    if segment_values is not None:
        layer["segment_values"] = segment_values
    bundle = build(
        ExistingAnalysisResults(
            syntax_status="COMPUTED",
            syntax_bundle={"engine": "fixture-engine", "layers": [layer]},
            analysis_extents=(extent,),
            metric_input_refs={"syntax_local_800m_integration": (ROAD_INPUT,)},
        ),
        source_refs=(ROAD_INPUT,),
    )
    item = observation(bundle, "syntax_local_800m_integration")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "SYNTAX_LAYER_HAS_NO_SEGMENT_VALUES" in item.limitation_codes


def test_site_metrics_preserve_road_and_building_coverage_limitations():
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id=STUDY_AREA.id,
        building_features=[{"id": "b1", "geometry": box(10, 10, 20, 20), "properties": {}}],
        water_features=[],
        road_features=[{"id": "r1", "geometry": LineString([(0, 50), (100, 50)]), "properties": {}}],
    )
    bundle = build(ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED"))
    road = observation(bundle, "road.total_length_m")
    coverage = observation(bundle, "building.ground_coverage_ratio")
    assert road.limitation_details
    assert any("sum" in item.lower() and "overlap" in item.lower() for item in road.limitation_details)
    assert any("connectivity" in item.lower() for item in road.limitation_details)
    assert coverage.limitation_details
    assert any("planning" in item.lower() for item in coverage.limitation_details)


def test_problem_status_and_residual_metric_codes_follow_problem_definition_keys():
    summary = {
        "metadata": {"methodology": "deterministic-fixture-v1"},
        "problems": [{
            "status": "PENDING_DESIGNER_CONFIRMATION",
            "limitations": ["Residual geometry does not identify land use."],
            "metrics": [
                {"key": "nonbuilding_nonwater_residual_area_m2", "value": 12.0, "unit": "m2", "evidence_level": "COMPUTED_RESULT"},
                {"key": "nonbuilding_nonwater_residual_ratio_pct", "value": 12.0, "unit": "%", "evidence_level": "COMPUTED_RESULT"},
            ],
        }],
    }
    results = ExistingAnalysisResults(
        problem_definition=summary,
        problem_status="COMPUTED",
        metric_scope_refs={
            "nonbuilding_nonwater_residual_area_m2": STUDY_AREA,
            "nonbuilding_nonwater_residual_ratio_pct": STUDY_AREA,
        },
        metric_input_refs={
            "nonbuilding_nonwater_residual_area_m2": (BAG_INPUT, WATER_INPUT),
            "nonbuilding_nonwater_residual_ratio_pct": (BAG_INPUT, WATER_INPUT),
        },
    )
    bundle = build(results)
    for key in ("nonbuilding_nonwater_residual_area_m2", "nonbuilding_nonwater_residual_ratio_pct"):
        item = observation(bundle, key)
        assert "RESIDUAL_IS_NOT_BUILDABLE_OR_PUBLIC_SPACE" in item.limitation_codes
        assert "PROBLEM_STATUS_PENDING_DESIGNER_CONFIRMATION" in item.limitation_codes
        assert "Residual geometry does not identify land use." in item.limitation_details


@pytest.mark.parametrize("field", ["site_metrics", "syntax_bundle", "problem_definition"])
def test_non_mapping_loader_payload_becomes_blocked_observation(field):
    results = ExistingAnalysisResults(**{
        field: ["malformed-loader-payload"],
        "site_status": "COMPUTED",
        "syntax_status": "COMPUTED",
    })
    bundle = build(results)
    if field == "site_metrics":
        item = observation(bundle, "building.count")
    elif field == "syntax_bundle":
        item = observation(bundle, "syntax.loader_result")
    else:
        item = observation(bundle, "problem_definition.loader_result")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "LOADER_RESULT_NOT_OBJECT" in item.limitation_codes


def test_non_mapping_problem_metrics_become_blocked_observation():
    bundle = build(ExistingAnalysisResults(problem_definition={"problems": [{"metrics": None}]}))
    item = observation(bundle, "problem_definition.loader_result")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "LOADER_RESULT_NOT_OBJECT" in item.limitation_codes


def test_non_mapping_syntax_layer_becomes_blocked_observation():
    bundle = build(ExistingAnalysisResults(syntax_bundle={"layers": [None]}))
    item = observation(bundle, "syntax.loader_result")
    assert item.status == "BLOCKED"
    assert item.value is None
    assert "LOADER_RESULT_NOT_OBJECT" in item.limitation_codes


@pytest.mark.parametrize("usage", [{}, {" ": 1}])
def test_invalid_or_missing_registered_use_does_not_publish_empty_success(usage):
    metrics = {"building_count": 1, "usage_distribution": usage,
               "source_data_status": {"buildings": "DECLARED_COMPLETE_WITHIN_SCOPE"}}
    bundle = build(ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED"))
    item = observation(bundle, "building.registered_use_distribution")
    assert item.status == "BLOCKED"
    assert not item.category_counts


def test_coverage_caveat_preserves_union_method():
    metrics = {"ground_coverage_ratio": 0.2,
               "source_data_status": {"buildings": "DECLARED_COMPLETE_WITHIN_SCOPE"}}
    item = observation(build(ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED")), "building.ground_coverage_ratio")
    assert "union" in " ".join(item.limitation_details).lower()


def test_explicit_empty_syntax_segments_without_count_are_missing():
    extent = AnalysisExtent(id="empty-syntax", study_area_ref=STUDY_AREA, display_radius_m=800.0,
                            calculation_radius_m=800.0, network_mode="pedestrian")
    results = ExistingAnalysisResults(syntax_status="COMPUTED", analysis_extents=(extent,),
        syntax_bundle={"engine": "fixture-v1", "layers": [{"id": "syn-empty", "unit": "NAIN",
            "radius_m": 800.0, "network_mode": "pedestrian", "calculation_status": "COMPUTED",
            "statistics": {"mean": 0.0}, "segment_values": []}]})
    item = observation(build(results), "syn-empty")
    assert item.status == "BLOCKED"
    assert item.value is None


@pytest.mark.parametrize("count", [1, True, "1"])
def test_usage_category_total_must_match_strict_building_count(count):
    metrics = {"building_count": count, "usage_distribution": {"woonfunctie": 99},
               "source_data_status": {"buildings": "DECLARED_COMPLETE_WITHIN_SCOPE"}}
    item = observation(build(ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED")), "building.registered_use_distribution")
    assert item.status == "BLOCKED"
    assert not item.category_counts
