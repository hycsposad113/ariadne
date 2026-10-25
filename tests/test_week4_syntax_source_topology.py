import pytest
from pyproj import Transformer
from shapely.geometry import LineString, mapping


def test_osm_node_reference_alignment_uses_verified_way_vertex_order():
    from urban_design.context_network import _aligned_osm_node_ids

    transformer = Transformer.from_crs("OGC:CRS84", "EPSG:28992", always_xy=True)
    source_points = [(4.4, 51.9), (4.401, 51.901), (4.402, 51.902)]
    projected = [transformer.transform(lon, lat) for lon, lat in source_points]
    way = {
        "id": 7001,
        "type": "way",
        "nodes": [901, 902, 903],
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in source_points],
    }

    node_ids = _aligned_osm_node_ids(mapping(LineString(projected)), way, transform=transformer.transform)

    assert node_ids == ["901", "902", "903"]


def test_osm_node_reference_alignment_rejects_geometry_drift():
    from urban_design.context_network import _aligned_osm_node_ids

    transformer = Transformer.from_crs("OGC:CRS84", "EPSG:28992", always_xy=True)
    source_points = [(4.4, 51.9), (4.401, 51.901)]
    projected = [transformer.transform(lon, lat) for lon, lat in source_points]
    way = {
        "id": 7002,
        "type": "way",
        "nodes": [911, 912],
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in source_points],
    }
    drifted = LineString([projected[0], (projected[1][0] + 1.0, projected[1][1])])

    with pytest.raises(ValueError, match="geometry does not align"):
        _aligned_osm_node_ids(mapping(drifted), way, transform=transformer.transform)
