"""Tests for deterministic site calculations and provisional display cards."""

import pytest
from shapely.geometry import Polygon, box


def _declared_complete_coverage(*source_names):
    return {
        name: {"status": "DECLARED_COMPLETE_WITHIN_SCOPE", "evidence_refs": [f"fixture:{name}"]}
        for name in source_names
    }


def test_site_analysis_coverage_calculation_exact():
    from urban_design.site_analysis import calculate_site_metrics

    # StudyArea of 1,000 m2: 0..50 x 0..20
    study_area = box(0, 0, 50, 20)
    # Two 100 m2 buildings (10x10 each)
    bldg1 = box(5, 5, 15, 15)
    bldg2 = box(25, 5, 35, 15)

    metrics = calculate_site_metrics(
        study_area_geom=study_area,
        study_area_id="test-area-1",
        building_features=[
            {"id": "b1", "geometry": bldg1, "properties": {"gebruiksdoel": "woonfunctie", "bouwjaar": 1995}},
            {"id": "b2", "geometry": bldg2, "properties": {"gebruiksdoel": "industriefunctie", "bouwjaar": 2005}},
        ],
        water_features=[],
        road_features=[],
        source_coverage=_declared_complete_coverage("buildings"),
    )

    # Footprint total = 200 m2 on 1000 m2 study area -> coverage = 0.20
    assert metrics["study_area_area_m2"] == 1000.0
    assert metrics["building_count"] == 2
    assert metrics["building_footprint_area_m2"] == 200.0
    assert metrics["ground_coverage_ratio"] == 0.20

    # Building height and FAR must be UNAVAILABLE, not fabricated!
    assert metrics["height_status"] == "UNAVAILABLE"
    assert metrics["far_status"] == "UNAVAILABLE"
    assert metrics.get("calculated_far") is None


def test_site_analysis_unknown_empty_source_is_unavailable_not_zero():
    from urban_design.site_analysis import calculate_site_metrics

    study_area = box(0, 0, 100, 100)
    metrics = calculate_site_metrics(
        study_area_geom=study_area,
        study_area_id="test-area-2",
        building_features=[],
        water_features=[],
        road_features=[],
    )
    # Missing source coverage is distinct from verified zero source features.
    gaps = metrics["data_gaps"]
    assert any("building_height" in g["field"] for g in gaps)
    assert any("far" in g["field"] for g in gaps)
    assert metrics["source_data_status"]["buildings"] == "UNKNOWN"
    assert metrics["building_count"] is None
    assert metrics["building_footprint_area_m2"] is None
    assert metrics["ground_coverage_ratio"] is None


def test_overlapping_buildings_and_water_are_not_double_counted():
    from urban_design.site_analysis import calculate_site_metrics

    study_area = box(0, 0, 50, 20)  # 1,000 m²
    metrics = calculate_site_metrics(
        study_area_geom=study_area,
        study_area_id="overlap-area",
        building_features=[
            {"id": "b1", "geometry": box(0, 0, 20, 10), "properties": {}},
            {"id": "b2", "geometry": box(10, 0, 30, 10), "properties": {}},
        ],
        water_features=[
            {"id": "w1", "geometry": box(30, 0, 45, 10), "properties": {}},
            {"id": "w2", "geometry": box(35, 0, 50, 10), "properties": {}},
        ],
        road_features=[],
        source_coverage=_declared_complete_coverage("buildings", "water"),
    )

    assert metrics["building_footprint_area_m2"] == 300.0
    assert metrics["ground_coverage_ratio"] == 0.3
    assert metrics["water_area_m2"] == 200.0
    assert metrics["water_coverage_ratio"] == 0.2
    assert metrics["unclassified_surface_residual_area_m2"] == 500.0


def test_site_analysis_grocery_accessibility_blocked_without_human_policy():
    from urban_design.site_analysis import evaluate_grocery_accessibility

    # Without approved human spatial policies, grocery accessibility must be BLOCKED
    res = evaluate_grocery_accessibility(
        policies_approved=False,
    )
    assert res["status"] == "BLOCKED"
    assert "spatial polic" in res["reason"].lower()


def test_site_analysis_grocery_accessibility_never_fabricates_zero_without_route_inputs():
    from urban_design.site_analysis import evaluate_grocery_accessibility

    result = evaluate_grocery_accessibility(
        policies_approved=True,
        origin_denominator="all_residential_addresses",
        destination_taxonomy="osm_shop_supermarket_and_convenience",
        network_policy="walkable_public_roads_v1",
    )

    assert result["status"] == "BLOCKED"
    assert result["metric_value"] is None
    assert "route inputs" in result["reason"].lower()


def test_site_analysis_evidence_cards_structure():
    from urban_design.site_analysis import generate_site_evidence_cards

    study_area = box(0, 0, 100, 100)
    cards = generate_site_evidence_cards(
        study_area_geom=study_area,
        study_area_id="test-area-3",
        building_features=[{"id": "b1", "geometry": box(10, 10, 30, 30), "properties": {}}],
        water_features=[],
        road_features=[],
    )

    assert len(cards) >= 3
    card_ids = [c["card_id"] for c in cards]
    assert any("coverage" in cid for cid in card_ids)
    assert any("gaps" in cid for cid in card_ids)

    for card in cards:
        assert "source_ref" in card
        assert "formula_version" in card
        assert "limitations" in card
        assert "validation_status" in card
        assert card["validation_status"] != "VALIDATED"

    road = next(card for card in cards if card["metric"] == "total_road_length_m")
    assert "length sum" in road["title"].lower()
    assert "connectivity" not in road["title"].lower()
    assert "not a graph" in road["limitations"].lower()


def test_site_analysis_keeps_unverified_empty_sources_unavailable():
    from urban_design.site_analysis import calculate_site_metrics, generate_site_evidence_cards

    study_area = box(0, 0, 100, 100)
    metrics = calculate_site_metrics(
        study_area_geom=study_area,
        study_area_id="unverified-empty-source",
        building_features=[],
        water_features=[],
        road_features=[],
    )

    assert metrics["source_data_status"]["buildings"] == "UNKNOWN"
    assert metrics["building_count"] is None
    assert metrics["building_footprint_area_m2"] is None
    assert metrics["ground_coverage_ratio"] is None
    assert metrics["water_area_m2"] is None
    assert metrics["unclassified_surface_residual_area_m2"] is None
    assert metrics["total_road_length_m"] is None

    cards = generate_site_evidence_cards(
        study_area_geom=study_area,
        study_area_id="unverified-empty-source",
        building_features=[],
        water_features=[],
        road_features=[],
    )
    coverage = next(card for card in cards if card["metric"] == "ground_coverage_ratio")
    assert coverage["value"] is None
    assert coverage["validation_status"] == "UNAVAILABLE"
    residual = next(card for card in cards if card["metric"] == "unclassified_surface_residual_ratio")
    assert residual["value"] is None
    assert residual["validation_status"] == "UNAVAILABLE"


def test_incomplete_nonempty_source_is_still_unavailable():
    from urban_design.site_analysis import calculate_site_metrics

    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id="partial-bag-source",
        building_features=[{"id": "b1", "geometry": box(0, 0, 10, 10), "properties": {}}],
        water_features=[],
        road_features=[],
        source_coverage={"buildings": {"status": "INCOMPLETE", "evidence_refs": ["partial:bag"]}},
    )

    assert metrics["source_data_status"]["buildings"] == "INCOMPLETE"
    assert metrics["building_count"] is None
    assert metrics["building_footprint_area_m2"] is None


def test_declared_complete_coverage_requires_a_nonblank_reference():
    from pydantic import ValidationError

    from urban_design.site_analysis import SourceCoverageEvidence

    with pytest.raises(ValidationError, match="reference"):
        SourceCoverageEvidence(status="DECLARED_COMPLETE_WITHIN_SCOPE", evidence_refs=["  "])


def test_site_analysis_accepts_zero_only_with_declared_complete_source_evidence():
    from urban_design.site_analysis import SourceCoverageEvidence, calculate_site_metrics, generate_site_evidence_cards

    complete = {
        name: SourceCoverageEvidence(
            status="DECLARED_COMPLETE_WITHIN_SCOPE",
            evidence_refs=[f"snapshot-{name}-sha256:fixture"],
        )
        for name in ("buildings", "water", "roads")
    }
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id="verified-empty-source",
        building_features=[],
        water_features=[],
        road_features=[],
        source_coverage=complete,
    )

    assert metrics["source_data_status"]["buildings"] == "DECLARED_COMPLETE_WITHIN_SCOPE"
    assert metrics["building_count"] == 0
    assert metrics["building_footprint_area_m2"] == 0.0
    assert metrics["ground_coverage_ratio"] == 0.0

    cards = generate_site_evidence_cards(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id="verified-empty-source",
        building_features=[],
        water_features=[],
        road_features=[],
        source_coverage=complete,
    )
    coverage = next(card for card in cards if card["metric"] == "ground_coverage_ratio")
    assert coverage["value"] == 0.0
    assert coverage["validation_status"] == "CALCULATED_INPUT_PROVENANCE_UNVERIFIED"
