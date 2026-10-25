"""Regression tests for regional OSM road topology extraction."""

from __future__ import annotations

from shapely.geometry import LineString

from scripts.extract_regional_network import detect_grade_separated_unlinks


def _meta(node_coordinates, *, layer=0, bridge=None, tunnel=None, level=None):
    return {
        "source_node_coordinates": node_coordinates,
        "vertical_signature": (layer, bridge, tunnel, level),
    }


def test_crossing_without_a_shared_node_at_the_crossing_is_unlinked_even_if_ways_share_another_node():
    horizontal = LineString([(0.0, 50.0), (20.0, 50.0), (50.0, 50.0), (100.0, 50.0)])
    vertical = LineString([(20.0, 50.0), (50.0, 0.0), (50.0, 50.0), (50.0, 100.0)])
    metadata = [
        _meta({10: (0.0, 50.0), 20: (20.0, 50.0), 30: (50.0, 50.0), 40: (100.0, 50.0)}),
        _meta({20: (20.0, 50.0), 50: (50.0, 0.0), 60: (50.0, 50.0), 70: (50.0, 100.0)}),
    ]

    assert detect_grade_separated_unlinks([horizontal, vertical], metadata) == [(50.0, 50.0)]


def test_matching_source_node_at_crossing_with_matching_grade_is_at_grade():
    horizontal = LineString([(0.0, 50.0), (50.0, 50.0), (100.0, 50.0)])
    vertical = LineString([(50.0, 0.0), (50.0, 50.0), (50.0, 100.0)])
    metadata = [
        _meta({10: (0.0, 50.0), 99: (50.0, 50.0), 11: (100.0, 50.0)}),
        _meta({12: (50.0, 0.0), 99: (50.0, 50.0), 13: (50.0, 100.0)}),
    ]

    assert detect_grade_separated_unlinks([horizontal, vertical], metadata) == []


def test_different_vertical_grade_signature_is_unlinked_even_at_shared_source_node():
    horizontal = LineString([(0.0, 50.0), (50.0, 50.0), (100.0, 50.0)])
    vertical = LineString([(50.0, 0.0), (50.0, 50.0), (50.0, 100.0)])
    metadata = [
        _meta({10: (0.0, 50.0), 99: (50.0, 50.0), 11: (100.0, 50.0)}, layer=0),
        _meta({12: (50.0, 0.0), 99: (50.0, 50.0), 13: (50.0, 100.0)}, layer=1),
    ]

    assert detect_grade_separated_unlinks([horizontal, vertical], metadata) == [(50.0, 50.0)]


def test_level_zero_is_preserved_in_vertical_signature():
    from scripts.extract_regional_network import _vertical_signature

    assert _vertical_signature({"level": "0"}) == (0, None, None, "0")


def test_unrecognized_level_tag_is_marked_ambiguous():
    from scripts.extract_regional_network import _vertical_signature, _vertical_signature_is_usable

    signature = _vertical_signature({"level": "ground"})

    assert signature[3] == "invalid:ground"
    assert not _vertical_signature_is_usable(signature)


def test_invalid_vertical_metadata_does_not_prove_same_grade():
    horizontal = LineString([(0.0, 50.0), (50.0, 50.0), (100.0, 50.0)])
    vertical = LineString([(50.0, 0.0), (50.0, 50.0), (50.0, 100.0)])
    invalid_signature = ("invalid:ground-level?", None, None, None)
    metadata = [
        {
            "source_node_coordinates": {99: (50.0, 50.0)},
            "vertical_signature": invalid_signature,
        },
        {
            "source_node_coordinates": {99: (50.0, 50.0)},
            "vertical_signature": invalid_signature,
        },
    ]

    assert detect_grade_separated_unlinks([horizontal, vertical], metadata) == [(50.0, 50.0)]


def test_full_way_geometry_finds_envelope_crossing_without_an_interior_osm_node():
    from pyproj import Transformer
    from shapely.geometry import box

    from scripts.extract_regional_network import RegionalOsmHandler

    to_wgs84 = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
    line_points = [(79000.0, 435000.0), (91000.0, 435000.0)]
    nodes = []
    for node_id, (x, y) in enumerate(line_points, start=1):
        lon, lat = to_wgs84.transform(x, y)
        nodes.append(type("Node", (), {"ref": node_id, "lon": lon, "lat": lat})())
    way = type(
        "Way",
        (),
        {"id": 42, "tags": {"highway": "residential"}, "nodes": nodes},
    )()
    handler = RegionalOsmHandler(
        buffer_polygon=box(80000.0, 430000.0, 90000.0, 440000.0),
        transformer=Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True),
    )

    handler.way(way)

    assert [item["osm_id"] for item in handler.ways] == [42]


def test_motorway_and_trunk_classes_are_only_kept_for_regional_scale():
    from pyproj import Transformer
    from shapely.geometry import box

    from scripts.extract_regional_network import RegionalOsmHandler

    to_wgs84 = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
    lon, lat = to_wgs84.transform(85000.0, 435000.0)
    node1 = type("Node", (), {"ref": 1, "lon": lon, "lat": lat})()
    lon2, lat2 = to_wgs84.transform(86000.0, 435000.0)
    node2 = type("Node", (), {"ref": 2, "lon": lon2, "lat": lat2})()
    way = type("Way", (), {"id": 7, "tags": {"highway": "motorway"}, "nodes": [node1, node2]})()
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    envelope = box(84000.0, 434000.0, 87000.0, 436000.0)

    local_handler = RegionalOsmHandler(envelope, transformer, include_regional_highways=False)
    regional_handler = RegionalOsmHandler(envelope, transformer, include_regional_highways=True)
    local_handler.way(way)
    regional_handler.way(way)

    assert local_handler.ways == []
    assert len(regional_handler.ways) == 1


def test_geofabrik_poly_is_projected_as_a_valid_coverage_polygon(tmp_path):
    from pyproj import Transformer

    from scripts.extract_regional_network import load_geofabrik_poly

    poly_path = tmp_path / "test.poly"
    poly_path.write_text(
        "test-region\n1\n4.0 52.0\n4.1 52.0\n4.1 52.1\n4.0 52.1\n4.0 52.0\nEND\nEND\n",
        encoding="utf-8",
    )
    coverage = load_geofabrik_poly(
        poly_path,
        Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True),
    )

    assert coverage.is_valid
    assert not coverage.is_empty
    assert coverage.area > 0


def test_retained_source_identity_verification_fails_closed_on_hash_drift(tmp_path):
    import hashlib

    import pytest

    from scripts.extract_regional_network import verify_recorded_file

    path = tmp_path / "source.bin"
    path.write_bytes(b"retained source")
    record = {
        "status_code": 200,
        "success": True,
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }

    assert verify_recorded_file(path, record, label="fixture")["size_bytes"] == len(b"retained source")
    path.write_bytes(b"changed source")
    with pytest.raises(ValueError, match="does not match"):
        verify_recorded_file(path, record, label="fixture")
