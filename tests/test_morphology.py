from __future__ import annotations

from dataclasses import replace

import pytest
from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box

from urban_design.morphology.contracts import (
    ApprovedSiteConstraint,
    FixtureGenerationInput,
    MorphologyGenerationError,
    NonBuildableArea,
    PreservedBuildingInput,
    SiteGenerationInput,
    SiteRoadInput,
    SiteZoneInput,
)
from urban_design.morphology.massing import _minimum_rotated_edge_m, place_site_buildings
from urban_design.morphology.streets import (
    RoadSegment,
    count_road_components,
    count_site_road_components,
    derive_external_road_contacts,
)
from urban_design.morphology.strategies import (
    _route_inside_area,
    generate_fixture_strategies,
    generate_site_strategies,
)
from urban_design.morphology.validation import is_within_site_geometry_tolerance, validate_site_candidate


def _fixture(**overrides) -> FixtureGenerationInput:
    values = {
        "design_area": box(0, 0, 200, 120),
        "crs": "EPSG:28992",
        "seed": 57,
        "road_width_m": 6.0,
        "first_floor_height_m": 4.0,
        "standard_floor_height_m": 3.0,
        "strategy_floor_count": 3,
        "far_upper_bound": 2.0,
        "retained_footprints": (box(15, 15, 30, 35),),
        "retained_floor_counts": (2,),
        "provenance": "FIXTURE_ONLY",
    }
    values.update(overrides)
    return FixtureGenerationInput(**values)


def test_three_fixture_strategies_are_valid_distinct_and_reproducible():
    first = generate_fixture_strategies(_fixture())
    second = generate_fixture_strategies(_fixture())

    assert len(first.candidates) == len(second.candidates) == 3
    assert {item.strategy_id for item in first.candidates} == {
        "grid", "linear-green-axis", "offset-courtyard"
    }
    assert all(item.valid for item in first.candidates), [
        (item.strategy_id, item.failure_reasons) for item in first.candidates
    ]
    assert all(item.provenance == "FIXTURE_ONLY" for item in first.candidates)
    assert [item.geometry_hash for item in first.candidates] == [item.geometry_hash for item in second.candidates]
    assert len({item.geometry_hash for item in first.candidates}) == 3
    assert all(item.scenario_status == "PROPOSED_FIXTURE_ONLY" for item in first.candidates)
    assert all(item.strategy_label.startswith("System-proposed") for item in first.candidates)
    assert all(
        building.use_label == "UNASSIGNED_FIXTURE_USE"
        and "fixture-only" in building.strategy_parameter
        for item in first.candidates
        for building in item.buildings
    )


def test_retained_footprints_are_preserved_and_generated_geometry_stays_in_area():
    generation = generate_fixture_strategies(_fixture())
    retained = _fixture().retained_footprints

    for candidate in generation.candidates:
        assert candidate.retained_footprints == retained
        assert all(_fixture().design_area.covers(polygon) for polygon in candidate.road_surfaces)
        assert _fixture().design_area.covers(candidate.open_space)
        assert all(_fixture().design_area.covers(parcel) for parcel in candidate.parcels)
        assert all(_fixture().design_area.covers(building.footprint) for building in candidate.buildings)
        assert all(not building.footprint.intersects(retained[0]) for building in candidate.buildings)
        assert candidate.road_component_count == 1
        assert candidate.external_connection_count >= 1


def test_crossing_roads_on_different_layers_do_not_connect():
    roads = (
        RoadSegment("at-grade", LineString([(-10, 0), (10, 0)])),
        RoadSegment(
            "bridge",
            LineString([(0, -10), (0, 10)]),
            layer=1,
            bridge=True,
        ),
    )

    assert count_road_components(roads) == 2


def test_disjoint_parts_inside_one_multiline_are_not_one_road_graph_component():
    road = RoadSegment(
        "disconnected-multiline",
        MultiLineString([[(0, 0), (10, 0)], [(20, 0), (30, 0)]]),
    )

    assert count_road_components((road,)) == 2


def test_site_graph_does_not_join_a_crossing_bridge_to_an_at_grade_road():
    area = box(-20, -20, 20, 20)
    roads = (RoadSegment("ground", LineString([(-10, 0), (10, 0)])),)
    preserved_bridge = SiteRoadInput(
        "bridge-road",
        LineString([(0, -10), (0, 10)]),
        0,
        True,
        False,
        "artifact-roads",
        "snapshot-roads",
        "road:local",
    )

    assert count_site_road_components(roads, (preserved_bridge,), design_area=area) == 2


def test_site_graph_ignores_point_only_boundary_clip_fragments():
    area = box(0, 0, 10, 10)
    roads = (
        RoadSegment(
            "line-with-outside-touch",
            MultiLineString([[(0, 0), (5, 0)], [(10, 10), (11, 11)]]),
        ),
    )

    assert count_site_road_components(roads, (), design_area=area) == 1


def test_site_routes_preserve_boundary_precision_and_remain_inside_area():
    area = Polygon([
        (0, 0), (4, 0), (4, 4), (3, 4),
        (3, 0.9999996), (1, 0.9999996), (1, 4), (0, 4),
    ])

    route = _route_inside_area(area, (), Point(0.5, 3.9), Point(3.5, 3.9))

    assert route is not None
    assert area.covers(route)
    assert route.intersection(area).length == pytest.approx(route.length)


def test_exceeded_fixture_far_is_saved_as_failed_candidate_with_reason():
    generation = generate_fixture_strategies(_fixture(far_upper_bound=0.0))

    assert len(generation.candidates) == 3
    assert all(not item.valid for item in generation.candidates)
    assert all(item.geometry_hash for item in generation.candidates)
    assert all(any("FAR" in reason for reason in item.failure_reasons) for item in generation.candidates)


def test_unknown_retained_floors_keep_far_unavailable_and_candidates_failed():
    from urban_design.models import UnavailableValue

    generation = generate_fixture_strategies(_fixture(retained_floor_counts=()))

    assert all(isinstance(item.metrics.far, UnavailableValue) for item in generation.candidates)
    assert all(not item.valid for item in generation.candidates)
    assert all(any("FAR is unavailable" in reason for reason in item.failure_reasons) for item in generation.candidates)


def test_real_project_inputs_are_rejected_by_d2_fixture_generator():
    with pytest.raises(MorphologyGenerationError, match="FIXTURE_ONLY"):
        _fixture(provenance="PROJECT_DATA")


def _site_fixture(**overrides) -> SiteGenerationInput:
    area = Polygon(
        [(0, 0), (160, 0), (160, 100), (100, 100), (100, 120), (96, 120), (96, 100), (0, 100)]
    )
    network = (
        SiteRoadInput("source-east-west", LineString([(-20, 25), (180, 25)]), 0, False, False, "source-roads", "snapshot-roads", None, highway="primary"),
        SiteRoadInput("source-west-crossing", LineString([(30, -20), (30, 110)]), 0, False, False, "source-roads", "snapshot-roads", None, highway="residential"),
        SiteRoadInput("source-east-crossing", LineString([(130, -20), (130, 110)]), 0, False, False, "source-roads", "snapshot-roads", None, highway="secondary"),
    )
    preserved_roads = (
        SiteRoadInput("preserved-narrow-road", LineString([(96.5, 102), (99.5, 102)]), 0, False, False, "source-roads", "snapshot-roads", "road:hierarchy-a"),
    )
    zones = (SiteZoneInput("zone-whole-site", area, "EPSG:28992", "mixed-use", "PREFERENCE"),)
    constraints = (
        ApprovedSiteConstraint("c-far", "far_upper_limit", 2.4, "ratio", "whole_site", "HARD", "decision-fixture"),
        ApprovedSiteConstraint("c-zone-far", "zone_far_upper_limit", 1.8, "ratio", "zone:zone-whole-site", "HARD", "decision-fixture"),
        ApprovedSiteConstraint("c-coverage", "coverage_upper_limit", 0.55, "ratio", "whole_site", "HARD", "decision-fixture"),
        ApprovedSiteConstraint("c-height", "height_upper_limit", 18.0, "m", "whole_site", "HARD", "decision-fixture"),
        ApprovedSiteConstraint("c-first-floor", "first_floor_height", 4.0, "m", "whole_site", "HARD", "decision-fixture"),
        ApprovedSiteConstraint("c-standard-floor", "standard_floor_height", 3.0, "m", "whole_site", "HARD", "decision-fixture"),
        ApprovedSiteConstraint("c-road-width", "road_width", 6.0, "m", "road:hierarchy-a", "HARD", "decision-fixture"),
    )
    values = {
        "design_area": area,
        "crs": "EPSG:28992",
        "seed": 57,
        "source_network_roads": network,
        "preserved_roads": preserved_roads,
        "preserved_buildings": (
            PreservedBuildingInput("building-locked", box(12, 58, 24, 70), 2, "source-buildings", "snapshot-buildings"),
        ),
        "zones": zones,
        "approved_constraints": constraints,
        "minimum_fragment_area_m2": 100.0,
        "minimum_fragment_width_m": 20.0,
        "fragment_rule_version": "site-fragment-test-v1",
        "allocation_policy": None,
        "provenance": "FIXTURE_ONLY",
    }
    values.update(overrides)
    return SiteGenerationInput(**values)


def _assumed_external_contact_fixture() -> SiteGenerationInput:
    area = box(0, 0, 300, 200)
    source_roads = (
        SiteRoadInput("north-primary", LineString([(50, 190), (50, 210)]), 0, False, False, "osm", "snapshot-osm", None, highway="primary"),
        SiteRoadInput("south-residential", LineString([(250, -10), (250, 10)]), 0, False, False, "osm", "snapshot-osm", None, highway="residential"),
        SiteRoadInput("east-residential", LineString([(290, 100), (310, 100)]), 0, False, False, "osm", "snapshot-osm", None, highway="residential"),
    )
    return _site_fixture(
        design_area=area,
        source_network_roads=source_roads,
        preserved_roads=(),
        preserved_buildings=(),
        zones=(SiteZoneInput("zone-whole-site", area, "EPSG:28992", "mixed-use", "PREFERENCE"),),
        provenance="ASSUMED",
    )


def test_assumed_land_block_requires_two_external_connections_and_preserves_primary_rule():
    inputs = _assumed_external_contact_fixture()
    connected = generate_site_strategies(inputs)

    assert connected.metadata["contact_connectivity_rules_version"] == "contact-connectivity-v3.1"
    for candidate in connected.candidates:
        assert candidate.valid, (candidate.strategy_id, candidate.failure_reasons)
        assert candidate.external_connection_count >= 2
        block = candidate.diff_report["land_block_connectivity"][0]
        assert block["available_external_contact_count"] == 3
        assert block["required_external_connection_count"] == 2
        assert block["connected_external_contact_count"] >= 2
        assert block["available_primary_contact_count"] == 1
        assert block["connected_primary_contact_count"] >= 1
        connected_contacts = [contact for contact in block["external_contacts"] if contact["connected"]]
        assert len({contact["boundary_side"] for contact in connected_contacts}) >= 2

    one_contact = generate_site_strategies(
        replace(inputs, source_network_roads=(inputs.source_network_roads[0],))
    )
    for candidate in one_contact.candidates:
        assert candidate.valid, (candidate.strategy_id, candidate.failure_reasons)
        block = candidate.diff_report["land_block_connectivity"][0]
        assert block["available_external_contact_count"] == 1
        assert block["required_external_connection_count"] == 1
        assert block["connected_external_contact_count"] == 1

    candidate = connected.candidates[0]
    interior_land = inputs.land_area.buffer(-1.0)
    disconnected_roads = tuple(
        replace(road, geometry=road.geometry.intersection(interior_land))
        for road in candidate.roads
        if not road.geometry.intersection(interior_land).is_empty
    )
    failure_reasons, _metrics, _components, external_count, _report, _unconnected = validate_site_candidate(
        inputs,
        roads=disconnected_roads,
        road_surfaces=candidate.road_surfaces,
        preserved_road_surfaces=candidate.preserved_road_surfaces,
        open_space=candidate.open_space,
        parcels=candidate.parcels,
        buildings=candidate.buildings,
        retained_footprints=candidate.retained_footprints,
        preserved_roads=candidate.preserved_roads,
        external_contacts=candidate.external_contacts,
        excluded_fragments=candidate.excluded_fragments,
        contact_connectivity_rules_version="contact-connectivity-v3.1",
    )
    assert external_count == 0
    assert any("requires 2 connected external OSM contacts" in reason for reason in failure_reasons)


def test_irregular_site_strategies_preserve_inputs_connect_and_replay():
    inputs = _site_fixture()
    first = generate_site_strategies(inputs)
    second = generate_site_strategies(inputs)

    assert len(first.candidates) == len(second.candidates) == 3
    assert {item.strategy_id for item in first.candidates} == {
        "site-grid", "site-linear-green-axis", "site-concentric-open-space"
    }
    assert all(item.valid for item in first.candidates), [
        (item.strategy_id, item.failure_reasons) for item in first.candidates if not item.valid
    ]
    assert len({item.geometry_hash for item in first.candidates}) == 3
    assert [item.geometry_hash for item in first.candidates] == [item.geometry_hash for item in second.candidates]
    road_geometries = {
        tuple(sorted(road.geometry.normalize().wkb_hex for road in item.roads))
        for item in first.candidates
    }
    assert len(road_geometries) == 3

    for candidate in first.candidates:
        assert inputs.design_area.covers(candidate.open_space)
        assert all(inputs.design_area.covers(surface) for surface in candidate.road_surfaces)
        assert all(inputs.design_area.covers(parcel) for parcel in candidate.parcels)
        assert all(inputs.design_area.covers(building.footprint) for building in candidate.buildings)
        assert candidate.retained_footprints[0].equals(inputs.preserved_buildings[0].footprint)
        assert candidate.preserved_roads[0].geometry.equals(inputs.preserved_roads[0].geometry)
        assert candidate.road_component_count == 1
        assert candidate.external_connection_count == len(candidate.external_contacts)
        assert candidate.external_connection_count >= 2
        assert candidate.diff_report["excluded_fragment_count"] >= 1
        assert all(building.use_label == "mixed-use" for building in candidate.buildings)
        assert all(len(building.floor_blocks) == building.floor_count for building in candidate.buildings)
        assert candidate.metrics.far <= 2.4
        assert candidate.metrics.coverage_ratio <= 0.55
        assert candidate.metrics.height_m <= 18.0
        assert candidate.diff_report["zone_far_ratio"]["zone-whole-site"] <= 1.8


def test_site_input_rejects_missing_approved_road_width_instead_of_defaulting():
    values = _site_fixture().__dict__
    values["approved_constraints"] = tuple(
        item for item in values["approved_constraints"] if item.name != "road_width"
    )
    with pytest.raises(MorphologyGenerationError, match="road_width"):
        SiteGenerationInput(**values)


def test_site_generation_keeps_design_area_holes_out_of_every_candidate():
    outer = [(0, 0), (160, 0), (160, 120), (0, 120)]
    hole = [(70, 40), (90, 40), (90, 60), (70, 60)]
    area = Polygon(outer, [hole])
    inputs = _site_fixture(
        design_area=area,
        preserved_roads=(),
        preserved_buildings=(),
        zones=(SiteZoneInput("zone-whole-site", area, "EPSG:28992", "mixed-use", "PREFERENCE"),),
    )
    result = generate_site_strategies(inputs)

    for candidate in result.candidates:
        assert candidate.valid, (candidate.strategy_id, candidate.failure_reasons)
        assert all(geometry.intersection(Polygon(hole)).area <= 1e-9 for geometry in candidate.road_surfaces)
        assert all(parcel.intersection(Polygon(hole)).area <= 1e-9 for parcel in candidate.parcels)


def test_site_generation_excludes_water_and_reserved_waterfront_from_new_geometry():
    from dataclasses import fields
    import urban_design.morphology.contracts as contracts

    non_buildable_type = getattr(contracts, "NonBuildableArea", None)
    assert non_buildable_type is not None, "typed non-buildable mask input is missing"
    input_fields = {item.name for item in fields(SiteGenerationInput)}
    assert "non_buildable_areas" in input_fields, "site generation input has no non-buildable mask field"
    assert "waterfront_public_areas" in input_fields, "site generation input has no reserved waterfront geometry field"

    area = box(0, 0, 200, 120)
    water = box(80, 30, 120, 90)
    public_band = box(65, 15, 135, 105).difference(water)
    mask = non_buildable_type(
        id="water-fixture",
        geometry=water,
        kind="water",
        source_artifact_id="bgt-water-fixture",
    )
    inputs = _site_fixture(
        design_area=area,
        preserved_roads=(),
        preserved_buildings=(),
        zones=(SiteZoneInput("zone-whole-site", area, "EPSG:28992", "mixed-use", "PREFERENCE"),),
        non_buildable_areas=(mask,),
        waterfront_public_areas=(public_band,),
    )

    result = generate_site_strategies(inputs)
    land_area = area.difference(water)
    for candidate in result.candidates:
        water_interior = water.buffer(-1e-6)
        assert all(road.geometry.intersection(water_interior).length <= 1e-8 for road in candidate.roads)
        assert all(surface.intersection(water).area <= 1e-8 for surface in candidate.road_surfaces)
        assert all(parcel.intersection(water).area <= 1e-8 for parcel in candidate.parcels)
        assert all(building.footprint.intersection(water).area <= 1e-8 for building in candidate.buildings)
        assert all(building.footprint.intersection(public_band).area <= 1e-8 for building in candidate.buildings)
        assert candidate.open_space.intersection(water).area <= 1e-8
        assert candidate.metrics.far == pytest.approx(candidate.metrics.gfa_m2 / land_area.area)
        assert candidate.metrics.far <= 2.0 + 1e-9


def test_assumed_water_split_site_connects_each_land_block_to_its_own_primary_contact():
    area = box(0, 0, 300, 140)
    water = box(135, -10, 165, 150).intersection(area)
    land = area.difference(water)
    waterfront_band = land.intersection(water.boundary.buffer(15.0))
    source_roads = (
        SiteRoadInput("west-primary", LineString([(-20, 70), (25, 70)]), 0, False, False, "osm", "snapshot-osm", "road:primary", highway="primary"),
        SiteRoadInput("west-north-residential", LineString([(60, 125), (60, 155)]), 0, False, False, "osm", "snapshot-osm", None, highway="residential"),
        SiteRoadInput("east-primary", LineString([(275, 70), (320, 70)]), 0, False, False, "osm", "snapshot-osm", "road:primary", highway="primary"),
        SiteRoadInput("east-south-residential", LineString([(240, -15), (240, 15)]), 0, False, False, "osm", "snapshot-osm", None, highway="residential"),
        SiteRoadInput("water-edge-primary", LineString([(125, 70), (145, 70)]), 0, False, False, "osm", "snapshot-osm", "road:primary", highway="primary"),
    )
    constraints = (
        ApprovedSiteConstraint("c-far", "far_upper_limit", 2.0, "ratio", "whole_site", "HARD", "assumed-test"),
        ApprovedSiteConstraint("c-coverage", "coverage_upper_limit", 0.5, "ratio", "whole_site", "HARD", "assumed-test"),
        ApprovedSiteConstraint("c-height", "height_upper_limit", 40.0, "m", "whole_site", "HARD", "assumed-test"),
        ApprovedSiteConstraint("c-first-floor", "first_floor_height", 4.5, "m", "whole_site", "HARD", "assumed-test"),
        ApprovedSiteConstraint("c-standard-floor", "standard_floor_height", 3.5, "m", "whole_site", "HARD", "assumed-test"),
        ApprovedSiteConstraint("c-road-width", "road_width", 14.0, "m", "road:primary", "HARD", "assumed-test"),
    )
    inputs = SiteGenerationInput(
        design_area=area,
        crs="EPSG:28992",
        seed=42,
        source_network_roads=source_roads,
        preserved_roads=(),
        preserved_buildings=(),
        zones=(SiteZoneInput("whole", area, "EPSG:28992", "mixed", "PREFERENCE"),),
        approved_constraints=constraints,
        minimum_fragment_area_m2=400.0,
        minimum_fragment_width_m=12.0,
        fragment_rule_version="assumed-test-v1",
        allocation_policy=None,
        provenance="ASSUMED",
        non_buildable_areas=(NonBuildableArea("water", water, "water", "bgt-water"),),
        waterfront_public_areas=(waterfront_band,),
        minimum_footprint_area_m2=150.0,
        minimum_short_edge_m=8.0,
    )

    result = generate_site_strategies(inputs)

    assert result.metadata["contact_connectivity_rules_version"] == "contact-connectivity-v3.1"
    for candidate in result.candidates:
        assert candidate.valid, (candidate.strategy_id, candidate.failure_reasons)
        assert candidate.metrics.far <= 2.0 + 1e-9
        assert candidate.metrics.coverage_ratio <= 0.5 + 1e-9
        assert all(contact.source_road_id != "water-edge-primary" for contact in candidate.external_contacts)
        blocks = candidate.diff_report["contact_connectivity"]["land_blocks"]
        assert len(blocks) == 2
        assert all(block["road_component_count"] == 1 for block in blocks)
        assert all(block["available_external_contact_count"] >= 2 for block in blocks)
        assert all(block["required_external_connection_count"] == 2 for block in blocks)
        assert all(block["connected_external_contact_count"] >= 2 for block in blocks)
        assert all(block["available_primary_contact_count"] >= 1 for block in blocks)
        assert all(block["connected_primary_contact_count"] >= 1 for block in blocks)
        assert all(block["area_m2"] >= 2_000 for block in blocks)
        assert all(road.geometry.intersection(water.buffer(-1e-6)).length <= 1e-8 for road in candidate.roads)
        assert all(surface.intersection(water).area <= 1e-8 for surface in candidate.road_surfaces)
        assert all(surface.intersection(waterfront_band).area <= 1e-8 for surface in candidate.road_surfaces)
        assert all(road.geometry.intersection(waterfront_band).length <= 1e-8 for road in candidate.roads)

    non_contact_road = SiteRoadInput(
        "west-footway-only",
        LineString([(-20, 70), (25, 70)]),
        0,
        False,
        False,
        "osm",
        "snapshot-osm",
        None,
        highway="footway",
    )
    no_contact_result = generate_site_strategies(replace(inputs, source_network_roads=(non_contact_road,)))
    for candidate in no_contact_result.candidates:
        assert candidate.valid, (candidate.strategy_id, candidate.failure_reasons)
        assert all(
            block["warnings"]
            and any("no usable external primary OSM contact" in warning for warning in block["warnings"])
            and block["available_external_contact_count"] == 0
            and block["required_external_connection_count"] == 0
            for block in candidate.diff_report["land_block_connectivity"]
            if block["required"]
        )

    blocked_band = waterfront_band.union(box(0, 60, 10, 80))
    blocked_contact_result = generate_site_strategies(
        replace(inputs, waterfront_public_areas=(blocked_band,))
    )
    for candidate in blocked_contact_result.candidates:
        assert candidate.valid, (candidate.strategy_id, candidate.failure_reasons)
        assert all(
            block["unusable_primary_contact_count"] > 0
            for block in candidate.diff_report["land_block_connectivity"]
            if block["land_block_id"] == "land-block-001"
        )


def test_approved_project_data_retains_contact_connectivity_v2():
    base = _site_fixture(provenance="APPROVED_PROJECT_DATA")
    major_bridge = SiteRoadInput(
        "approved-major-bridge",
        LineString([(80, -20), (80, 0)]),
        1,
        True,
        False,
        "source-roads",
        "snapshot-roads",
        None,
        highway="primary",
    )

    result = generate_site_strategies(replace(base, source_network_roads=(*base.source_network_roads, major_bridge)))

    assert result.metadata["contact_connectivity_rules_version"] == "contact-connectivity-v2"
    assert all(not candidate.valid for candidate in result.candidates)
    assert all(
        candidate.diff_report["contact_connectivity"]["rules_version"] == "contact-connectivity-v2"
        for candidate in result.candidates
    )


def test_assumed_massing_uses_long_footprints_when_a_square_would_be_too_small():
    result = place_site_buildings(
        ((box(0, 0, 100, 14), "long-block", "mixed-use"),),
        strategy_id="assumed-long-footprint",
        seed=42,
        floor_count=8,
        first_floor_height_m=4.5,
        standard_floor_height_m=3.5,
        maximum_new_gfa_m2=10_000.0,
        maximum_new_coverage_m2=500.0,
        zone_gfa_limits_m2={},
        footprint_fraction=0.45,
        building_plot_size_m=100.0,
        minimum_footprint_area_m2=150.0,
        minimum_short_edge_m=8.0,
        footprint_mode="shape-aware",
        preserve_capacity_after_discard=True,
    )

    assert result.buildings
    footprint = result.buildings[0].footprint
    assert footprint.area >= 150.0
    assert _minimum_rotated_edge_m(footprint) >= 8.0
    assert max(footprint.bounds[2] - footprint.bounds[0], footprint.bounds[3] - footprint.bounds[1]) / min(
        footprint.bounds[2] - footprint.bounds[0], footprint.bounds[3] - footprint.bounds[1]
    ) >= 2.0


def test_assumed_massing_discards_too_small_footprints_without_refilling_their_gfa():
    import inspect

    parameters = inspect.signature(place_site_buildings).parameters
    assert "minimum_footprint_area_m2" in parameters, "massing has no minimum footprint area filter"
    assert "minimum_short_edge_m" in parameters, "massing has no minimum footprint edge filter"

    result = place_site_buildings(
        (
            (box(0, 0, 12, 12), "a-small", "mixed-use"),
            (box(30, 0, 70, 40), "z-large", "mixed-use"),
        ),
        strategy_id="minimum-footprint-fixture",
        seed=42,
        floor_count=4,
        first_floor_height_m=4.5,
        standard_floor_height_m=3.5,
        maximum_new_gfa_m2=600.0,
        maximum_new_coverage_m2=200.0,
        zone_gfa_limits_m2={},
        footprint_fraction=0.5,
        minimum_footprint_area_m2=150.0,
        minimum_short_edge_m=8.0,
    )

    assert result.buildings == ()
    assert result.discarded_massing_count == 2
    assert result.discarded_gfa_m2 == pytest.approx(600.0)
    assert _minimum_rotated_edge_m(rotate(box(0, 0, 20, 7), 31)) == pytest.approx(7.0)


def _tagged_source_road(road_id: str, highway: str, **tags) -> SiteRoadInput:
    return SiteRoadInput(
        road_id,
        LineString([(-20, 25), (0, 25)]),
        int(tags.pop("layer", 0)),
        bool(tags.pop("bridge", False)),
        bool(tags.pop("tunnel", False)),
        "source-roads",
        "snapshot-roads",
        None,
        highway=highway,
        **tags,
    )


def test_external_contacts_use_the_pd20_car_and_pedestrian_street_classes():
    area = box(0, 0, 100, 100)
    roads = (
        _tagged_source_road("primary", "primary"),
        _tagged_source_road("secondary-link", "secondary_link"),
        _tagged_source_road("tertiary", "tertiary"),
        _tagged_source_road("pedestrian", "pedestrian"),
        _tagged_source_road("residential", "residential"),
        _tagged_source_road("living-street", "living_street"),
        _tagged_source_road("unclassified", "unclassified"),
        _tagged_source_road("service-alley", "service", service="alley"),
        _tagged_source_road("footway", "footway"),
        _tagged_source_road("cycleway", "cycleway"),
        _tagged_source_road("driveway", "service", service="driveway"),
        _tagged_source_road("parking-aisle", "service", service="parking_aisle"),
        _tagged_source_road("motorway", "motorway"),
        _tagged_source_road("private-residential", "residential", access="private"),
        _tagged_source_road("motor-vehicle-prohibited", "tertiary", motor_vehicle="no"),
        _tagged_source_road("closed-pedestrian", "pedestrian", foot="no"),
    )

    contacts = derive_external_road_contacts(roads, design_area=area)

    by_source = {contact.source_road_id: contact for contact in contacts}
    assert set(by_source) == {
        "primary", "secondary-link", "tertiary", "pedestrian", "residential",
        "living-street", "unclassified", "service-alley",
    }
    assert {name for name, contact in by_source.items() if contact.priority == "major"} == {
        "primary", "secondary-link", "tertiary", "pedestrian",
    }
    assert {name for name, contact in by_source.items() if contact.priority == "minor"} == {
        "residential", "living-street", "unclassified", "service-alley",
    }


def test_major_contacts_are_required_but_unconnected_minor_contacts_are_report_only():
    base = _site_fixture()
    minor_bridge = _tagged_source_road(
        "minor-layered-alley", "service", service="alley", layer=1, bridge=True
    )
    inputs = replace(base, source_network_roads=(*base.source_network_roads, minor_bridge))

    result = generate_site_strategies(inputs)

    assert result.metadata["contact_connectivity_rules_version"] == "contact-connectivity-v2"
    for candidate in result.candidates:
        assert candidate.valid, (candidate.strategy_id, candidate.failure_reasons)
        assert any(item.source_road_id == "minor-layered-alley" and item.priority == "minor" for item in candidate.unconnected_contacts)
        assert not any("minor-layered-alley" in reason for reason in candidate.failure_reasons)
        assert candidate.diff_report["contact_connectivity"]["rules_version"] == "contact-connectivity-v2"


def test_unconnected_major_bridge_contact_invalidates_without_false_at_grade_join():
    base = _site_fixture()
    major_bridge = _tagged_source_road(
        "major-bridge", "primary", layer=1, bridge=True
    )
    inputs = replace(base, source_network_roads=(*base.source_network_roads, major_bridge))

    result = generate_site_strategies(inputs)

    for candidate in result.candidates:
        assert not candidate.valid
        unconnected = next(item for item in candidate.unconnected_contacts if item.source_road_id == "major-bridge")
        assert unconnected.priority == "major"
        assert "bridge" in unconnected.reason
        assert all((road.layer, road.bridge, road.tunnel) != (1, True, False) for road in candidate.roads)
        assert any(unconnected.contact_id in reason for reason in candidate.failure_reasons)


def test_large_street_block_is_subdivided_into_multiple_building_sites_under_area_caps():
    common = {
        "strategy_id": "density-fixture",
        "seed": 42,
        "floor_count": 5,
        "first_floor_height_m": 4.0,
        "standard_floor_height_m": 3.0,
        "maximum_new_gfa_m2": 20_000.0,
        "maximum_new_coverage_m2": 7_200.0,
        "zone_gfa_limits_m2": {},
        "footprint_fraction": 0.45,
        "building_plot_size_m": 40.0,
    }
    large_block = place_site_buildings(((box(0, 0, 120, 120), "zone-a", "mixed-use"),), **common)
    small_block = place_site_buildings(((box(0, 0, 40, 40), "zone-a", "mixed-use"),), **common)

    assert len(large_block.buildings) > len(small_block.buildings) > 0
    assert sum(building.footprint.area for building in large_block.buildings) <= common["maximum_new_coverage_m2"] + 1e-9
    assert sum(building.footprint.area * building.floor_count for building in large_block.buildings) <= common["maximum_new_gfa_m2"] + 1e-9
    assert max(block.top_height_m for building in large_block.buildings for block in building.floor_blocks) <= 16.0


def test_site_geometry_tolerance_accepts_only_submicron_overlay_roundoff():
    area = box(0, 0, 10, 10)

    assert is_within_site_geometry_tolerance(area, LineString([(-0.0000005, 5), (5, 5)]))
    assert not is_within_site_geometry_tolerance(area, LineString([(-0.000002, 5), (5, 5)]))
