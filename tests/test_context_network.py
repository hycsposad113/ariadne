"""Tests for OSM network cleaning, segment extraction, and 6 Space Syntax layers (CP4-6)."""

import json
from pathlib import Path
import pytest
from shapely.geometry import LineString, box


def test_osm_segment_extraction_respects_bridge_layers():
    from urban_design.context_network import clean_osm_segments

    features = [
        {
            "id": 101,
            "geometry": LineString([(0, 0), (100, 0)]),
            "properties": {"tags": {"highway": "residential", "layer": "0"}},
        },
        {
            "id": 102,
            "geometry": LineString([(50, -50), (50, 50)]),
            "properties": {"tags": {"highway": "primary", "bridge": "yes", "layer": "1"}},
        },
    ]

    segments = clean_osm_segments(features)
    assert len(segments) == 2
    assert segments[0].layer == 0
    assert segments[1].layer == 1


def test_space_syntax_six_layers_calculation():
    from urban_design.context_network import compute_six_syntax_layers
    from urban_design.space_syntax import SegmentFeature

    # Create a 5-segment synthetic test grid
    features = [
        SegmentFeature(id="s1", geometry=LineString([(0, 0), (500, 0)]), length_m=500.0),
        SegmentFeature(id="s2", geometry=LineString([(500, 0), (1000, 0)]), length_m=500.0),
        SegmentFeature(id="s3", geometry=LineString([(500, 0), (500, 500)]), length_m=500.0),
        SegmentFeature(id="s4", geometry=LineString([(500, 500), (500, 1000)]), length_m=500.0),
        SegmentFeature(id="s5", geometry=LineString([(500, 500), (1000, 500)]), length_m=500.0),
    ]

    res = compute_six_syntax_layers(features)

    # 6 layers must be returned: 3 scales (800m, 2000m, 10000m) x 2 measures (integration, choice)
    layers = res["layers"]
    assert len(layers) == 6
    layer_ids = [l["layer_id"] for l in layers]

    assert "syntax_local_800m_integration" in layer_ids
    assert "syntax_local_800m_choice" in layer_ids
    assert "syntax_mid_2000m_integration" in layer_ids
    assert "syntax_mid_2000m_choice" in layer_ids
    assert "syntax_regional_10000m_integration" in layer_ids
    assert "syntax_regional_10000m_choice" in layer_ids

    # Synthetic geometry without an acquisition envelope/completeness/stability
    # assessment cannot be presented as validated Rotterdam coverage.
    assert {layer["data_readiness"] for layer in layers} == {"BLOCKED_COVERAGE_EVIDENCE_ABSENT"}


def test_osm_segment_extraction_nodes_same_layer_interior_crossing():
    from urban_design.context_network import clean_osm_segments
    from urban_design.space_syntax import SegmentNetwork

    features = [
        {
            "id": 201,
            "geometry": LineString([(0, 50), (100, 50)]),
            "properties": {"tags": {"highway": "residential", "layer": "0"}},
        },
        {
            "id": 202,
            "geometry": LineString([(50, 0), (50, 100)]),
            "properties": {"tags": {"highway": "primary", "layer": "0"}},
        },
    ]

    segments = clean_osm_segments(features)
    network = SegmentNetwork.from_features(segments)

    assert len(segments) == 4
    junction = network.junctions[((50.0, 50.0), 0)]
    assert len(junction) == 4
    assert sum(segment.id.startswith("osm_201_seg_0_node_") for segment in segments) == 2
    assert sum(segment.id.startswith("osm_202_seg_0_node_") for segment in segments) == 2


def test_osm_crossing_requires_shared_source_node_identity():
    from urban_design.context_network import clean_osm_segments
    from urban_design.space_syntax import SegmentNetwork

    features = [
        {
            "id": "way/301",
            "geometry": LineString([(0, 50), (100, 50)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 301,
                "osm_node_ids": ["n1", "n2"],
                "tags": {"highway": "residential"},
            },
        },
        {
            "id": "way/302",
            "geometry": LineString([(50, 0), (50, 100)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 302,
                "osm_node_ids": ["n3", "n4"],
                "tags": {"highway": "primary"},
            },
        },
    ]

    segments = clean_osm_segments(features)
    network = SegmentNetwork.from_features(segments)

    assert len(segments) == 2
    assert all(segment.layer is None for segment in segments)
    # The two lines cross in XY but have no shared OSM node, so no junction is
    # invented from coordinate coincidence or missing grade tags.
    assert all(len(junction) == 1 for junction in network.junctions.values())


def test_osm_shared_source_node_connects_way_endpoints():
    from urban_design.context_network import clean_osm_segments
    from urban_design.space_syntax import SegmentNetwork

    features = [
        {
            "id": "way/401",
            "geometry": LineString([(0, 0), (100, 0)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 401,
                "osm_node_ids": ["n1", "shared"],
                "tags": {"highway": "residential"},
            },
        },
        {
            "id": "way/402",
            "geometry": LineString([(100, 0), (100, 100)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 402,
                "osm_node_ids": ["shared", "n3"],
                "tags": {"highway": "primary"},
            },
        },
    ]

    network = SegmentNetwork.from_features(clean_osm_segments(features))

    assert len(network.junctions[("osm-node", "shared")]) == 2


def test_osm_source_way_without_aligned_node_ids_fails_closed():
    from urban_design.context_network import clean_osm_segments

    feature = {
        "id": "way/501",
        "geometry": LineString([(0, 0), (100, 0)]),
        "properties": {
            "osm_type": "way",
            "osm_id": 501,
            "tags": {"highway": "residential"},
        },
    }

    with pytest.raises(ValueError, match="OSM way.*node IDs"):
        clean_osm_segments([feature])


def test_legacy_r02_topology_replay_requires_explicit_unsafe_mode():
    from urban_design.context_network import clean_osm_segments

    features = [
        {
            "id": "way/511",
            "geometry": LineString([(0, 50), (100, 50)]),
            "properties": {"osm_type": "way", "tags": {"highway": "residential"}},
        },
        {
            "id": "way/512",
            "geometry": LineString([(50, 0), (50, 100)]),
            "properties": {"osm_type": "way", "tags": {"highway": "primary"}},
        },
    ]

    segments = clean_osm_segments(features, topology_policy="legacy_r02_replay")

    assert len(segments) == 4
    assert {segment.layer for segment in segments} == {0}


def test_source_topology_audit_exposes_unresolved_grade_crossing():
    from urban_design.context_network import audit_source_topology, clean_osm_segments

    features = [
        {
            "id": "way/701",
            "geometry": LineString([(0, 50), (100, 50)]),
            "properties": {"osm_type": "way", "osm_node_ids": ["a", "b"], "tags": {"highway": "residential"}},
        },
        {
            "id": "way/702",
            "geometry": LineString([(50, 0), (50, 100)]),
            "properties": {"osm_type": "way", "osm_node_ids": ["c", "d"], "tags": {"highway": "primary"}},
        },
    ]

    audit = audit_source_topology(clean_osm_segments(features))

    assert audit["unresolved_intersection_count"] == 1
    assert audit["known_grade_separated_intersection_count"] == 0
    assert audit["readiness"] == "BLOCKED_UNRESOLVED_GRADE_OR_TOPOLOGY_CROSSINGS"


def test_source_topology_audit_accepts_explicitly_separated_layers():
    from urban_design.context_network import audit_source_topology, clean_osm_segments

    features = [
        {
            "id": "way/711",
            "geometry": LineString([(0, 50), (100, 50)]),
            "properties": {"osm_type": "way", "osm_node_ids": ["a", "b"], "tags": {"highway": "residential", "layer": "0"}},
        },
        {
            "id": "way/712",
            "geometry": LineString([(50, 0), (50, 100)]),
            "properties": {"osm_type": "way", "osm_node_ids": ["c", "d"], "tags": {"highway": "primary", "bridge": "yes", "layer": "1"}},
        },
    ]

    audit = audit_source_topology(clean_osm_segments(features))

    assert audit["unresolved_intersection_count"] == 0
    assert audit["known_grade_separated_intersection_count"] == 1
    assert audit["readiness"] == "SOURCE_NODE_TOPOLOGY_CHECKED"


def test_source_topology_audit_records_overlapping_way_pair_for_review():
    from urban_design.context_network import audit_source_topology, clean_osm_segments

    features = [
        {
            "id": "way/721",
            "geometry": LineString([(0, 0), (100, 0)]),
            "properties": {"osm_type": "way", "osm_node_ids": ["a", "b"], "tags": {"highway": "residential"}},
        },
        {
            "id": "way/722",
            "geometry": LineString([(50, 0), (150, 0)]),
            "properties": {"osm_type": "way", "osm_node_ids": ["c", "d"], "tags": {"highway": "primary"}},
        },
    ]

    audit = audit_source_topology(clean_osm_segments(features))

    assert audit["overlap_count"] == 1
    assert audit["readiness"] == "BLOCKED_OVERLAPPING_SEGMENT_REVIEW"
    assert audit["overlapping_pairs"] == [
        {"left_segment_id": "osm_way/721_seg_0", "right_segment_id": "osm_way/722_seg_0", "overlap_length_m": 50.0}
    ]


def test_unknown_grade_synthetic_intersection_does_not_get_noded():
    from urban_design.context_network import clean_osm_segments
    from urban_design.space_syntax import SegmentNetwork

    features = [
        {"id": 601, "geometry": LineString([(0, 50), (100, 50)]), "properties": {"tags": {"highway": "residential"}}},
        {"id": 602, "geometry": LineString([(50, 0), (50, 100)]), "properties": {"tags": {"highway": "primary"}}},
    ]

    segments = clean_osm_segments(features)
    network = SegmentNetwork.from_features(segments)

    assert len(segments) == 2
    assert all(segment.layer is None for segment in segments)
    assert all(len(junction) == 1 for junction in network.junctions.values())


def test_syntax_readiness_uses_study_area_buffer_and_stability_evidence():
    from urban_design.context_network import compute_six_syntax_layers
    from urban_design.space_syntax import SegmentFeature

    study_area = box(0, 0, 100, 100)
    envelope = box(-2500, -2500, 2600, 2600)
    features = [
        SegmentFeature("inside", LineString([(10, 50), (90, 50)]), 80.0),
        SegmentFeature("outside", LineString([(200, 200), (300, 200)]), 100.0),
    ]
    result = compute_six_syntax_layers(
        features,
        study_area_geometry=study_area,
        acquisition_envelope_geometry=envelope,
        extract_covers_envelope=True,
        stability_validated_radii_m=[800.0],
    )
    by_id = {layer["layer_id"]: layer for layer in result["layers"]}

    assert result["coverage_buffer_m"] == pytest.approx(2500.0)
    assert result["analysis_segment_count"] == 1
    assert by_id["syntax_local_800m_integration"]["data_readiness"] == "BLOCKED_SOURCE_COMPLETENESS_UNVERIFIED"
    assert by_id["syntax_mid_2000m_integration"]["data_readiness"] == "BLOCKED_BOUNDARY_STABILITY_UNASSESSED"
    assert by_id["syntax_regional_10000m_integration"]["data_readiness"] == "EDGE_AFFECTED_INSUFFICIENT_ACQUISITION_BUFFER"
    assert set(by_id["syntax_local_800m_integration"]["segment_values"]) == {"inside"}
    assert result["extract_covers_envelope"] is True
    assert "source_complete" not in result
    assert "does not establish OSM feature, semantic, or network completeness" in by_id["syntax_local_800m_integration"]["limitations"]


def test_extract_envelope_failure_blocks_syntax_readiness():
    from urban_design.context_network import compute_six_syntax_layers
    from urban_design.space_syntax import SegmentFeature

    result = compute_six_syntax_layers(
        [SegmentFeature("inside", LineString([(10, 50), (90, 50)]), 80.0)],
        study_area_geometry=box(0, 0, 100, 100),
        acquisition_envelope_geometry=box(-1000, -1000, 1100, 1100),
        extract_covers_envelope=False,
        stability_validated_radii_m=[800.0],
    )
    local = next(layer for layer in result["layers"] if layer["layer_id"] == "syntax_local_800m_integration")

    assert local["data_readiness"] == "BLOCKED_EXTRACT_ENVELOPE_NOT_COVERED"
    assert result["extract_covers_envelope"] is False
    assert "source_complete" not in result


def test_unknown_extract_envelope_status_remains_unknown():
    from urban_design.context_network import compute_six_syntax_layers
    from urban_design.space_syntax import SegmentFeature

    result = compute_six_syntax_layers(
        [SegmentFeature("inside", LineString([(10, 50), (90, 50)]), 80.0)],
        study_area_geometry=box(0, 0, 100, 100),
        acquisition_envelope_geometry=box(-1000, -1000, 1100, 1100),
        stability_validated_radii_m=[800.0],
    )
    local = next(layer for layer in result["layers"] if layer["layer_id"] == "syntax_local_800m_integration")

    assert result["extract_covers_envelope"] is None
    assert local["data_readiness"] == "BLOCKED_EXTRACT_ENVELOPE_STATUS_UNKNOWN"


def test_extract_envelope_status_requires_boolean_or_none():
    from urban_design.context_network import compute_six_syntax_layers
    from urban_design.space_syntax import SegmentFeature

    with pytest.raises(ValueError, match="extract_covers_envelope must be true, false, or None"):
        compute_six_syntax_layers(
            [SegmentFeature("inside", LineString([(10, 50), (90, 50)]), 80.0)],
            extract_covers_envelope="complete",  # type: ignore[arg-type]
        )


def test_blocked_radius_can_remain_uncomputed_without_fake_values():
    from urban_design.context_network import compute_six_syntax_layers
    from urban_design.space_syntax import SegmentFeature

    result = compute_six_syntax_layers(
        [SegmentFeature("single", LineString([(0, 0), (10, 0)]), 10.0)],
        calculate_radii_m=[800.0],
    )
    by_id = {layer["layer_id"]: layer for layer in result["layers"]}

    assert result["extract_covers_envelope"] is None
    assert "source_complete" not in result
    assert by_id["syntax_local_800m_integration"]["calculation_status"] == "COMPUTED"
    assert by_id["syntax_mid_2000m_integration"]["calculation_status"] == "NOT_COMPUTED_COVERAGE_BLOCKED"
    assert by_id["syntax_mid_2000m_integration"]["segment_values"] == {}
    assert by_id["syntax_regional_10000m_choice"]["segment_values"] == {}


def test_shared_node_candidate_keeps_shape_vertices_inside_intersection_segments():
    from urban_design.context_network import clean_osm_segments
    from urban_design.space_syntax import SegmentNetwork

    features = [
        {
            "id": "way-a",
            "geometry": LineString([(0, 0), (40, 0), (100, 0), (100, 40), (100, 100)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 801,
                "osm_node_ids": ["a", "shape-a", "junction", "shape-b", "b"],
                "tags": {"highway": "residential", "layer": "0"},
            },
        },
        {
            "id": "way-c",
            "geometry": LineString([(100, 0), (140, 0), (200, 0)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 802,
                "osm_node_ids": ["junction", "shape-c", "c"],
                "tags": {"highway": "residential", "layer": "0"},
            },
        },
    ]

    segments = clean_osm_segments(
        features,
        segmentation_policy="osm_shared_nodes_candidate_v1",
    )

    assert len(segments) == 3
    assert [list(segment.geometry.coords) for segment in segments] == [
        [(0.0, 0.0), (40.0, 0.0), (100.0, 0.0)],
        [(100.0, 0.0), (100.0, 40.0), (100.0, 100.0)],
        [(100.0, 0.0), (140.0, 0.0), (200.0, 0.0)],
    ]
    network = SegmentNetwork.from_features(segments)
    assert len(network.junctions[("osm-node", "junction")]) == 3
    assert all(
        endpoint_node in {"a", "junction", "b", "c"}
        for segment in segments
        for endpoint_node in (segment.start_node_id, segment.end_node_id)
    )


def test_shared_node_candidate_requires_explicit_osm_way_identity():
    from urban_design.context_network import clean_osm_segments

    feature = {
        "id": "synthetic-line",
        "geometry": LineString([(0, 0), (1, 0)]),
        "properties": {"tags": {"highway": "residential", "layer": "0"}},
    }
    with pytest.raises(ValueError, match="requires OSM ways with aligned source node IDs"):
        clean_osm_segments([feature], segmentation_policy="osm_shared_nodes_candidate_v1")


@pytest.mark.parametrize("blank_node_id", ["", "   "])
def test_shared_node_candidate_rejects_blank_source_node_ids(blank_node_id):
    from urban_design.context_network import clean_osm_segments

    feature = {
        "id": "way/803",
        "geometry": LineString([(0, 0), (1, 0)]),
        "properties": {
            "osm_type": "way",
            "osm_node_ids": [blank_node_id, "end"],
            "tags": {"highway": "residential"},
        },
    }
    with pytest.raises(ValueError, match="source node IDs must be non-empty"):
        clean_osm_segments([feature], segmentation_policy="osm_shared_nodes_candidate_v1")


@pytest.mark.parametrize("geometry_state", ["missing", "null", "point", "empty_line"])
def test_shared_node_candidate_fails_closed_for_missing_or_unsupported_geometry(geometry_state):
    from shapely.geometry import Point
    from urban_design.context_network import clean_osm_segments

    feature = {
        "id": "way/804",
        "properties": {
            "osm_type": "way",
            "osm_node_ids": ["start", "end"],
            "tags": {"highway": "residential"},
        },
    }
    if geometry_state != "missing":
        feature["geometry"] = {
            "null": None,
            "point": Point(0, 0),
            "empty_line": LineString(),
        }.get(geometry_state)
    with pytest.raises(ValueError, match="must include a non-empty LineString geometry"):
        clean_osm_segments([feature], segmentation_policy="osm_shared_nodes_candidate_v1")


def test_shared_node_candidate_uses_the_unique_validated_way_id_for_segment_ids():
    from urban_design.context_network import clean_osm_segments

    features = [
        {
            "id": "duplicate-export-id",
            "geometry": LineString([(0, 0), (1, 0), (2, 0)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 805,
                "osm_node_ids": ["a", "shared", "b"],
                "tags": {"highway": "residential"},
            },
        },
        {
            "id": "duplicate-export-id",
            "geometry": LineString([(2, 0), (3, 0)]),
            "properties": {
                "osm_type": "way",
                "osm_id": 806,
                "osm_node_ids": ["shared", "c"],
                "tags": {"highway": "residential"},
            },
        },
    ]

    segments = clean_osm_segments(features, segmentation_policy="osm_shared_nodes_candidate_v1")

    assert len({segment.id for segment in segments}) == len(segments)
    assert {segment.id for segment in segments} == {
        "osm_805_seg_0_1",
        "osm_805_seg_1_2",
        "osm_806_seg_0_1",
    }


@pytest.mark.parametrize("bad_coordinate", [float("nan"), float("inf")])
def test_shared_node_candidate_rejects_non_finite_xy_coordinates(bad_coordinate):
    from urban_design.context_network import clean_osm_segments

    feature = {
        "id": "way/807",
        "geometry": LineString([(bad_coordinate, 0), (1, 0)]),
        "properties": {
            "osm_type": "way",
            "osm_node_ids": ["start", "end"],
            "tags": {"highway": "residential"},
        },
    }
    with pytest.raises(ValueError, match="finite XY coordinates"):
        clean_osm_segments([feature], segmentation_policy="osm_shared_nodes_candidate_v1")


def test_shared_node_candidate_rejects_coordinates_with_non_finite_derived_length():
    from urban_design.context_network import clean_osm_segments

    feature = {
        "id": "way/808",
        "geometry": LineString([(-1e308, 0), (1e308, 0)]),
        "properties": {
            "osm_type": "way",
            "osm_node_ids": ["start", "end"],
            "tags": {"highway": "residential"},
        },
    }
    with pytest.raises(ValueError, match="finite segment lengths"):
        clean_osm_segments([feature], segmentation_policy="osm_shared_nodes_candidate_v1")


def test_shared_node_candidate_fails_closed_for_single_junction_closed_way():
    from urban_design.context_network import clean_osm_segments

    features = [
        {
            "id": "roundabout",
            "geometry": LineString([(0, 0), (10, 0), (0, 0)]),
            "properties": {
                "osm_type": "way",
                "osm_node_ids": ["junction", "shape", "junction"],
                "tags": {"highway": "residential", "junction": "roundabout", "layer": "0"},
            },
        },
        {
            "id": "connector",
            "geometry": LineString([(0, 0), (-10, 0)]),
            "properties": {
                "osm_type": "way",
                "osm_node_ids": ["junction", "dead-end"],
                "tags": {"highway": "residential", "layer": "0"},
            },
        },
    ]

    with pytest.raises(ValueError, match="requires at least two distinct shared source junctions"):
        clean_osm_segments(features, segmentation_policy="osm_shared_nodes_candidate_v1")


def test_candidate_segmentation_cannot_be_used_for_legacy_r02_replay():
    from urban_design.context_network import clean_osm_segments

    feature = {
        "id": "way/900",
        "geometry": LineString([(0, 0), (1, 0)]),
        "properties": {
            "osm_type": "way",
            "osm_node_ids": ["a", "b"],
            "tags": {"highway": "residential"},
        },
    }
    with pytest.raises(ValueError, match="cannot be combined with legacy_r02_replay"):
        clean_osm_segments(
            [feature],
            topology_policy="legacy_r02_replay",
            segmentation_policy="osm_shared_nodes_candidate_v1",
        )
