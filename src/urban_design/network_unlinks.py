"""OSM grade-separation helpers preserved from extract_regional_network.py.

Shared by installed extent acquisition and the historical extraction script.
"""
from typing import Any, Mapping, Sequence
import math
from shapely.geometry import LineString, Point, MultiPoint
from shapely.strtree import STRtree

def _normalized_vertical_tag(value: Any, *, preserve_zero: bool = False) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if normalized in {"", "no", "false"} or (normalized == "0" and not preserve_zero):
        return None
    return normalized


def _vertical_signature(tags: Any) -> tuple[int | str, str | None, str | None, str | None]:
    raw_layer = tags.get("layer")
    if raw_layer is None or not str(raw_layer).strip():
        layer: int | str = 0
    else:
        try:
            layer = int(str(raw_layer).strip())
        except ValueError:
            layer = f"invalid:{str(raw_layer).strip().casefold()}"
    raw_level = _normalized_vertical_tag(tags.get("level"), preserve_zero=True)
    if raw_level is not None:
        try:
            if not math.isfinite(float(raw_level)):
                raw_level = f"invalid:{raw_level}"
        except ValueError:
            raw_level = f"invalid:{raw_level}"
    return (
        layer,
        _normalized_vertical_tag(tags.get("bridge")),
        _normalized_vertical_tag(tags.get("tunnel")),
        raw_level,
    )


def _vertical_signature_is_usable(signature: Any) -> bool:
    if not isinstance(signature, (tuple, list)) or len(signature) != 4:
        return False
    return not any(
        isinstance(value, str) and value.startswith("invalid:")
        for value in signature
    )


def _point_intersections(geometry: Any) -> list[Point]:
    if isinstance(geometry, Point):
        return [geometry]
    if isinstance(geometry, MultiPoint):
        return list(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return [point for child in geometry.geoms for point in _point_intersections(child)]
    return []


def detect_grade_separated_unlinks(
    line_geometries: Sequence[LineString],
    line_metadata: Sequence[Mapping[str, Any]],
    *,
    node_tolerance_m: float = 0.05,
) -> list[tuple[float, float]]:
    """Return point intersections not proven to be same-grade shared OSM nodes."""
    if len(line_geometries) != len(line_metadata):
        raise ValueError("line metadata must align one-to-one with geometries")
    if node_tolerance_m < 0 or not math.isfinite(node_tolerance_m):
        raise ValueError("node_tolerance_m must be finite and non-negative")

    unlinks: set[tuple[float, float]] = set()
    if not line_geometries:
        return []

    tree = STRtree(line_geometries)
    for index, geometry in enumerate(line_geometries):
        metadata = line_metadata[index]
        for candidate in tree.query(geometry):
            other_index = int(candidate)
            if other_index <= index:
                continue
            other_geometry = line_geometries[other_index]
            other_metadata = line_metadata[other_index]
            signature_a = metadata.get("vertical_signature")
            signature_b = other_metadata.get("vertical_signature")
            same_grade = (
                _vertical_signature_is_usable(signature_a)
                and _vertical_signature_is_usable(signature_b)
                and signature_a == signature_b
            )
            intersection = geometry.intersection(other_geometry)
            for point in _point_intersections(intersection):
                node_coords_a = metadata.get("source_node_coordinates", {})
                node_coords_b = other_metadata.get("source_node_coordinates", {})
                shared_ids = set(node_coords_a).intersection(node_coords_b)
                shared_at_point = False
                for node_id in shared_ids:
                    coord_a = node_coords_a[node_id]
                    coord_b = node_coords_b[node_id]
                    if (
                        Point(coord_a).distance(point) <= node_tolerance_m
                        and Point(coord_b).distance(point) <= node_tolerance_m
                    ):
                        shared_at_point = True
                        break
                if not same_grade or not shared_at_point:
                    unlinks.add((round(point.x, 2), round(point.y, 2)))
    return sorted(unlinks)

