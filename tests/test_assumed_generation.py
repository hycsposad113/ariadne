from __future__ import annotations

import json
from pathlib import Path
import sys

from shapely.geometry import LineString, box, shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_assumed_generation import (  # noqa: E402
    APPROVAL_REFERENCE,
    DEFAULT_SOURCE_ROOT,
    DEFAULT_STUDY_AREA,
    _build_input,
    run_assumed_generation,
)
from urban_design.morphology.contracts import (  # noqa: E402
    ApprovedSiteConstraint,
    SiteGenerationInput,
    SiteRoadInput,
    SiteZoneInput,
)
from urban_design.morphology.massing import _minimum_rotated_edge_m  # noqa: E402
from urban_design.models import UnavailableValue  # noqa: E402
from urban_design.morphology.strategies import generate_site_strategies  # noqa: E402


def _assumed_constraint(name: str, value: float, unit: str, scope: str = "whole_site") -> ApprovedSiteConstraint:
    return ApprovedSiteConstraint(
        id=f"test-assumed-{name}-{scope.replace(':', '-')}",
        name=name,
        value=value,
        unit=unit,
        scope=scope,
        enforcement="HARD",
        approval_decision_id=APPROVAL_REFERENCE,
    )


def test_real_study_area_preview_serializes_assumptions_metrics_and_artifacts(tmp_path: Path) -> None:
    context = _build_input(DEFAULT_STUDY_AREA, DEFAULT_SOURCE_ROOT)
    result = run_assumed_generation(
        study_area_path=DEFAULT_STUDY_AREA,
        source_root=DEFAULT_SOURCE_ROOT,
        output_dir=tmp_path / "run",
    )
    output_dir = result["output_dir"]
    assumptions = json.loads((output_dir / "assumptions.json").read_text(encoding="utf-8"))

    assert assumptions["evidence_status"] == "UNAPPROVED_PREVIEW"
    assert assumptions["assumption_status"] == "ASSUMED"
    assert assumptions["approval_decision_id"] == APPROVAL_REFERENCE
    assert assumptions["human_decision_created"] is False
    assert assumptions["authority_database_accessed"] is False
    assert assumptions["authority_database_written"] is False
    assert all(item["status"] == "ASSUMED" for item in assumptions["all_assumptions"])
    assert all(item["approval_decision_id"] == APPROVAL_REFERENCE for item in assumptions["all_assumptions"])
    assert assumptions["approval_decision_id"] == "ASSUMED_BY_COMMANDER_2026-09-27"
    assert context["generation_input"].provenance == "ASSUMED"
    assert context["generation_input"].crs == "EPSG:28992"
    assert context["generation_input"].seed == 42
    assert context["generation_input"].preserved_buildings == ()
    assert context["design_area"].symmetric_difference(context["study_area"].buffer(-5.0)).area < 1e-3
    assert context["generation_input"].non_buildable_areas[0].kind == "water"
    assert context["generation_input"].non_buildable_areas[0].source_artifact_id == context["source_metadata"]["water"]["artifact_id"]
    assert context["generation_input"].land_area.symmetric_difference(context["land_area"]).area < 1e-6

    assumptions_by_name = {item["name"]: item for item in assumptions["all_assumptions"]}
    assert assumptions_by_name["design_area"]["value"] == "entire StudyArea v5 inward-buffered by 5 m"
    assert assumptions_by_name["horizontal_crs"]["value"] == "EPSG:28992"
    assert assumptions_by_name["waterfront_public_band_width"]["value"] == 15.0
    assert assumptions_by_name["waterfront_public_band_width"]["status"] == "ASSUMED"
    assert assumptions_by_name["minimum_massing_footprint_area"]["value"] == 150.0
    assert assumptions_by_name["minimum_massing_short_edge"]["value"] == 8.0
    assert assumptions_by_name["preserved_roads"]["value"] == "OSM highway=primary, secondary, tertiary intersecting original StudyArea v5"
    assert assumptions_by_name["existing_buildings"]["value"] == {"disposition": "editable", "preserved": False}
    assert assumptions_by_name["zones"]["value"] == [
        {
            "zone_id": "waterfront-public-15m",
            "geometry": "land area within 15 m of the boundary of frozen BGT waterdeel polygons",
            "target_use": "mixed",
            "use_enforcement": "PREFERENCE",
            "open_space_preference": True,
        },
        {
            "zone_id": "remainder",
            "geometry": "land area outside the 15 m waterfront public band",
            "target_use": "mixed",
            "use_enforcement": "PREFERENCE",
        },
    ]
    assert assumptions_by_name["minimum_open_space_ratio"]["value"] == 0.15
    assert assumptions_by_name["minimum_open_space_ratio"]["unit"] == "ratio"
    assert assumptions_by_name["contact_connectivity_rules_version"]["value"] == "contact-connectivity-v3.1"
    assert assumptions_by_name["minimum_land_block_area"]["value"] == 2_000.0
    assert assumptions_by_name["land_far_density_target"]["value"] == [1.6, 1.9]
    assert assumptions["workflow_stage"] == "EXPLORE"
    assert assumptions["evidence_status_zh"] == "未核准預覽"

    assert assumptions["source_feature_counts"]["design_area_after_5m_inset_m2"] < assumptions["source_feature_counts"]["study_area_area_m2"]
    assert assumptions["source_feature_counts"]["land_area_after_water_exclusion_m2"] < assumptions["source_feature_counts"]["design_area_after_5m_inset_m2"]
    assert assumptions["source_feature_counts"]["bgt_water_mask_area_m2"] == round(context["water_mask"].area, 3)
    assert assumptions["source_feature_counts"]["preserved_highways_intersecting_study_area"] == len(context["selected_preserved_roads"])
    assert assumptions["source_provenance"] == context["source_metadata"]
    assert all(source["artifact_sha256"] for source in (context["source_metadata"]["osm"], context["source_metadata"]["water"]))
    assert all(context["source_metadata"][name]["sha256"] for name in ("study_area",))

    constraints = {(item["name"], item["scope"]): item for item in assumptions["hard_intensity_constraints"]}
    assert constraints[("far_upper_limit", "whole_site")]["value"] == 2.0
    assert constraints[("coverage_upper_limit", "whole_site")]["value"] == 0.5
    assert constraints[("height_upper_limit", "whole_site")]["value"] == 40.0
    assert constraints[("first_floor_height", "whole_site")]["value"] == 4.5
    assert constraints[("standard_floor_height", "whole_site")]["value"] == 3.5
    assert "not an approved floor height" in constraints[("standard_floor_height", "whole_site")]["note"]
    assert constraints[("road_width", "road:primary")]["value"] == 14.0
    assert constraints[("road_width", "road:secondary")]["value"] == 10.0
    assert all(item["enforcement"] == "HARD" for item in assumptions["hard_intensity_constraints"])
    assert all(item["status"] == "ASSUMED" for item in assumptions["hard_intensity_constraints"])
    assert all(item["approval_decision_id"] == APPROVAL_REFERENCE for item in assumptions["hard_intensity_constraints"])
    assert next(item for item in assumptions["all_assumptions"] if item["name"] == "seed")["value"] == 42
    assert next(item for item in assumptions["all_assumptions"] if item["name"] == "minimum_block_area")["value"] == 400.0
    assert next(item for item in assumptions["all_assumptions"] if item["name"] == "minimum_block_width")["value"] == 12.0
    assert next(item for item in assumptions["all_assumptions"] if item["name"] == "minimum_open_space_ratio")["value"] == 0.15

    assert len(result["strategies"]) >= 3
    assert sum(
        row["document"]["metrics"]["far_land_area"]["value"] >= 1.6
        for row in result["strategies"]
    ) >= 2
    assert result["manifest"]["contact_connectivity_rules_version"] == "contact-connectivity-v3.1"
    assert result["manifest"]["input_hash"] == result["input_hash"]
    assert result["manifest"]["elapsed_seconds"] >= 0
    assert result["manifest"]["program_git_revision"]
    for row in result["strategies"]:
        strategy_dir = output_dir / row["strategy_id"]
        metrics = json.loads((strategy_dir / "metrics.json").read_text(encoding="utf-8"))
        scenario = json.loads((strategy_dir / "scenario.geojson").read_text(encoding="utf-8"))
        far = metrics["metrics"]["far_land_area"]["value"]
        full_far = metrics["metrics"]["far_full_design_area"]["value"]
        height = metrics["metrics"]["maximum_height_m"]["value"]
        assert isinstance(far, (float, int)) and far <= 2.0 + 1e-9
        assert isinstance(full_far, (float, int)) and full_far <= far + 1e-9
        assert metrics["metrics"]["far_land_area"]["denominator_area_m2"] == round(context["land_area"].area, 3)
        assert metrics["metrics"]["far_full_design_area"]["denominator_area_m2"] == round(context["design_area"].area, 3)
        assert isinstance(height, (float, int)) and height <= 40.0 + 1e-9
        assert metrics["metrics"]["coverage_ratio"]["value"] <= 0.5 + 1e-9
        assert metrics["approval_decision_id"] == APPROVAL_REFERENCE
        assert metrics["scenario_status"] == "UNAPPROVED_PREVIEW"
        assert metrics["human_decision_created"] is False
        assert metrics["hard_constraint_validation"]["far_upper_limit"]["status"] == "PASS"
        assert metrics["hard_constraint_validation"]["far_upper_limit"]["denominator"] == "land area (design area minus non-buildable masks)"
        assert metrics["hard_constraint_validation"]["height_upper_limit"]["status"] == "PASS"
        assert metrics["validation"]["valid"] is row["document"]["validation"]["valid"]
        assert metrics["validation"]["valid"]
        assert metrics["validation"]["failure_reasons"] == []
        assert scenario["properties"]["evidence_status"] == "UNAPPROVED_PREVIEW"
        assert all(feature["properties"]["approval_decision_id"] == APPROVAL_REFERENCE for feature in scenario["features"])

        scenario_features = scenario["features"]
        contact_features = [feature for feature in scenario_features if feature["properties"].get("feature_kind") == "external_road_contact"]
        assert contact_features
        assert metrics["metrics"]["external_connection_count"]["total_contacts"] == len(contact_features)
        assert metrics["metrics"]["external_connection_count"]["value"] >= 2
        assert sum(feature["properties"]["connected"] for feature in contact_features) == metrics["metrics"]["external_connection_count"]["value"]
        assert all(feature["properties"]["source_mode"] in {"motor_vehicle", "pedestrian"} for feature in contact_features)
        assert all(shape(feature["geometry"]).distance(context["design_area"].exterior) <= 1e-6 for feature in contact_features)
        assert all(feature["properties"]["source_road_id"] != "way/1364569297" for feature in contact_features)
        water_features = [feature for feature in scenario_features if feature["properties"].get("feature_kind") == "non_buildable_area"]
        band_features = [feature for feature in scenario_features if feature["properties"].get("feature_kind") == "waterfront_public_band"]
        assert len(water_features) == 1 and water_features[0]["properties"]["mask_kind"] == "water"
        assert len(band_features) == 1 and band_features[0]["properties"]["width_m"] == 15.0
        water = shape(water_features[0]["geometry"])
        band = shape(band_features[0]["geometry"])
        water_interior = water.buffer(-1e-6)
        for feature in scenario_features:
            feature_kind = feature["properties"].get("feature_kind")
            geometry = shape(feature["geometry"])
            if feature_kind in {"block", "building_mass", "open_space", "road_surface"}:
                assert geometry.intersection(water).area <= 1e-8
            if feature_kind == "road_centerline" and feature["properties"].get("road_status") == "generated":
                assert geometry.intersection(water_interior).length <= 1e-8
                assert geometry.intersection(band).length <= 1e-8
            if feature_kind == "road_surface" and feature["properties"].get("road_status") == "generated":
                assert geometry.intersection(band).area <= 1e-8
            if feature_kind == "building_mass":
                assert geometry.area >= 150.0 - 1e-8
                assert _minimum_rotated_edge_m(geometry) >= 8.0 - 1e-8
                assert geometry.intersection(band).area <= 1e-8
        assert isinstance(metrics["metrics"]["discarded_massing_count"], int)
        assert metrics["generator"]["contact_connectivity_rules_version"] == "contact-connectivity-v3.1"
        land_blocks = metrics["metrics"]["land_block_connectivity"]["blocks"]
        assert land_blocks
        assert all(block["road_component_count"] == 1 for block in land_blocks if block["required"])
        assert all(
            block["connected_external_contact_count"] >= block["required_external_connection_count"]
            for block in land_blocks
            if block["required"] and block["available_external_contact_count"] > 0
        )
        assert all(
            block["connected_primary_contact_count"] >= 1
            for block in land_blocks
            if block["required"] and block["available_primary_contact_count"] > 0
        )
        assert all(
            block["warnings"]
            for block in land_blocks
            if block["required"] and block["available_external_contact_count"] == 0
        )
        assert all(
            block["observed_primary_contact_count"] == 0
            and block["unusable_primary_contact_count"] == 0
            and block["connected_primary_contact_count"] == 0
            for block in land_blocks
            if block["required"]
        )

        preserved = {
            feature["properties"]["road_id"]: feature
            for feature in scenario["features"]
            if feature["properties"].get("road_status") == "preserved_by_assumption"
        }
        expected = {
            road.road_id: road for road in context["selected_preserved_roads"]
            if not road.geometry.intersection(context["study_area"]).is_empty
            and (road.bridge or not road.geometry.intersection(context["study_area"]).difference(context["water_context"]).is_empty)
        }
        assert set(preserved) == set(expected)
        for road_id, road in expected.items():
            expected_geometry = road.geometry.intersection(context["study_area"])
            if not road.bridge:
                expected_geometry = expected_geometry.difference(context["water_context"])
            assert shape(preserved[road_id]["geometry"]).equals_exact(expected_geometry, 1e-9)

        assert {feature["properties"]["feature_kind"] for feature in scenario["features"]} >= {
            "building_mass",
            "road_centerline",
            "block",
            "open_space",
            "zone",
            "non_buildable_area",
            "waterfront_public_band",
            "land_block_boundary",
            "external_road_contact",
        }
        building_features = [
            feature for feature in scenario["features"]
            if feature["properties"]["feature_kind"] == "building_mass"
        ]
        assert building_features
        assert all(isinstance(feature["properties"]["floors"], int) for feature in building_features)
        assert all(feature["properties"]["height_m"] <= 40.0 for feature in building_features)

        for image_name in ("plan.png", "axonometric.png"):
            image = (strategy_dir / image_name).read_bytes()
            assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert (output_dir / "comparison.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (output_dir / "run-manifest.json").is_file()


def test_assumed_generation_keeps_preserved_roads_and_enforces_hard_limits() -> None:
    area = box(0, 0, 1000, 800)
    primary = SiteRoadInput("primary-1", LineString([(-20, 200), (1020, 200)]), 0, False, False, "osm", "osm-v1", "road:primary", highway="primary")
    secondary = SiteRoadInput("secondary-1", LineString([(-20, 600), (1020, 600)]), 0, False, False, "osm", "osm-v1", "road:secondary", highway="secondary")
    tertiary = SiteRoadInput("tertiary-1", LineString([(250, 400), (750, 400)]), 0, False, False, "osm", "osm-v1", None, highway="tertiary")
    roads = (primary, secondary, tertiary)
    constraints = (
        _assumed_constraint("far_upper_limit", 2.0, "ratio"),
        _assumed_constraint("coverage_upper_limit", 0.5, "ratio"),
        _assumed_constraint("height_upper_limit", 40.0, "m"),
        _assumed_constraint("first_floor_height", 4.5, "m"),
        _assumed_constraint("standard_floor_height", 3.5, "m"),
        _assumed_constraint("road_width", 14.0, "m", "road:primary"),
        _assumed_constraint("road_width", 10.0, "m", "road:secondary"),
    )
    generation_input = SiteGenerationInput(
        design_area=area,
        crs="EPSG:28992",
        seed=42,
        source_network_roads=roads,
        preserved_roads=roads,
        preserved_buildings=(),
        zones=(SiteZoneInput("whole", area, "EPSG:28992", "mixed", "PREFERENCE"),),
        approved_constraints=constraints,
        minimum_fragment_area_m2=400.0,
        minimum_fragment_width_m=12.0,
        fragment_rule_version="assumed-test-v1",
        allocation_policy=None,
        provenance="ASSUMED",
    )

    generated = generate_site_strategies(generation_input)
    assert generated.metadata["evidence_class"] == "UNAPPROVED_PREVIEW"
    assert len(generated.candidates) >= 3
    for candidate in generated.candidates:
        assert candidate.scenario_status == "UNAPPROVED_PREVIEW"
        assert {road.road_id for road in candidate.preserved_roads} == {"primary-1", "secondary-1", "tertiary-1"}
        assert candidate.preserved_roads == roads
        height_metric = candidate.metrics.height_m
        if isinstance(height_metric, UnavailableValue):
            raise AssertionError(f"synthetic candidate height unexpectedly unavailable: {height_metric.reason}")
        maximum_height = max(height_metric) if isinstance(height_metric, tuple) else height_metric
        assert isinstance(maximum_height, (float, int)) and maximum_height <= 40.0 + 1e-9
        assert isinstance(candidate.metrics.far, (float, int)) and candidate.metrics.far <= 2.0 + 1e-9
        assert all(item.approval_decision_id == APPROVAL_REFERENCE for item in constraints)
