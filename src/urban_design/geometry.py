"""Deterministic geometry validation and known-answer helpers for Milestone 1.

The project deliberately keeps this small validation kernel dependency-free. It
accepts GeoJSON-like mappings, validates planar two-dimensional coordinates,
rejects malformed topology, and exposes stable area/perimeter/hash functions.
It is a verifier primitive; it does not repair or infer geometry.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


class GeometryValidationError(ValueError):
    """Raised when geometry or its measurement contract is invalid."""


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeometryValidationError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise GeometryValidationError(f"{path} must be finite")
    return number


def _point(value: Any, path: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise GeometryValidationError(f"{path} must be a two-dimensional coordinate")
    return (_number(value[0], f"{path}[0]"), _number(value[1], f"{path}[1]"))


def _ring(value: Any, path: str) -> list[tuple[float, float]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GeometryValidationError(f"{path} must be a coordinate ring")
    points = [_point(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if len(points) < 4 or points[0] != points[-1]:
        raise GeometryValidationError(f"{path} must contain at least four closed coordinates")
    if len(set(points[:-1])) < 3:
        raise GeometryValidationError(f"{path} must contain at least three distinct vertices")
    _assert_simple_ring(points, path)
    return points


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> bool:
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
        and math.isclose(_orientation(a, b, p), 0.0, abs_tol=1e-12)
    )


def _segments_intersect(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]
) -> bool:
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    eps = 1e-12
    if ((ab_c > eps and ab_d < -eps) or (ab_c < -eps and ab_d > eps)) and (
        (cd_a > eps and cd_b < -eps) or (cd_a < -eps and cd_b > eps)
    ):
        return True
    return (
        (abs(ab_c) <= eps and _on_segment(a, b, c))
        or (abs(ab_d) <= eps and _on_segment(a, b, d))
        or (abs(cd_a) <= eps and _on_segment(c, d, a))
        or (abs(cd_b) <= eps and _on_segment(c, d, b))
    )


def _assert_simple_ring(points: list[tuple[float, float]], path: str) -> None:
    edges = list(zip(points, points[1:]))
    for first, (a, b) in enumerate(edges):
        for second in range(first + 1, len(edges)):
            c, d = edges[second]
            if second in {first - 1, first + 1}:
                continue
            if first == 0 and second == len(edges) - 1:
                continue
            if _segments_intersect(a, b, c, d):
                raise GeometryValidationError(f"{path} contains self-intersecting edges")


def _validated_geometry(geometry: Mapping[str, Any]) -> tuple[str, Any]:
    if not isinstance(geometry, Mapping):
        raise GeometryValidationError("geometry must be an object")
    geometry_type = geometry.get("type")
    if not isinstance(geometry_type, str) or not geometry_type.strip():
        raise GeometryValidationError("geometry type is required")
    geometry_type = geometry_type.strip()
    if geometry_type == "Point":
        return geometry_type, _point(geometry.get("coordinates"), "coordinates")
    if geometry_type == "LineString":
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, Sequence) or len(coordinates) < 2:
            raise GeometryValidationError("LineString requires at least two coordinates")
        points = [_point(item, f"coordinates[{index}]") for index, item in enumerate(coordinates)]
        if len(set(points)) < 2:
            raise GeometryValidationError("LineString requires two distinct coordinates")
        return geometry_type, points
    if geometry_type == "Polygon":
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, Sequence) or not coordinates:
            raise GeometryValidationError("Polygon coordinates must not be empty")
        return geometry_type, [_ring(item, f"coordinates[{index}]") for index, item in enumerate(coordinates)]
    if geometry_type == "MultiPolygon":
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, Sequence) or not coordinates:
            raise GeometryValidationError("MultiPolygon coordinates must not be empty")
        polygons = []
        for index, polygon in enumerate(coordinates):
            if not isinstance(polygon, Sequence) or not polygon:
                raise GeometryValidationError(f"coordinates[{index}] must contain rings")
            polygons.append([_ring(ring, f"coordinates[{index}][{ring_index}]") for ring_index, ring in enumerate(polygon)])
        return geometry_type, polygons
    raise GeometryValidationError(f"unsupported or mixed-dimensional geometry type: {geometry_type}")


def validate_geometry(geometry: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a canonical, JSON-safe geometry summary."""
    geometry_type, coordinates = _validated_geometry(geometry)
    canonical = {"type": geometry_type, "coordinates": coordinates}
    return {
        "type": geometry_type,
        "coordinates": coordinates,
        "canonical": canonical,
        "sha256": canonical_geometry_hash(canonical),
    }


def _signed_ring_area(ring: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum((a[0] * b[1]) - (b[0] * a[1]) for a, b in zip(ring, ring[1:]))


def polygon_area(geometry: Mapping[str, Any]) -> float:
    geometry_type, coordinates = _validated_geometry(geometry)
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise GeometryValidationError("area requires Polygon or MultiPolygon geometry")
    if geometry_type == "Polygon":
        rings = coordinates
        return abs(_signed_ring_area(rings[0])) - sum(abs(_signed_ring_area(ring)) for ring in rings[1:])
    return sum(abs(_signed_ring_area(polygon[0])) - sum(abs(_signed_ring_area(ring)) for ring in polygon[1:]) for polygon in coordinates)


def polygon_perimeter(geometry: Mapping[str, Any]) -> float:
    geometry_type, coordinates = _validated_geometry(geometry)
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise GeometryValidationError("perimeter requires Polygon or MultiPolygon geometry")
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates
    return sum(
        sum(math.dist(a, b) for a, b in zip(ring, ring[1:]))
        for polygon in polygons
        for ring in [polygon[0]]
    )


def canonical_geometry_hash(geometry: Mapping[str, Any]) -> str:
    geometry_type, coordinates = _validated_geometry(geometry)
    payload = {"type": geometry_type, "coordinates": coordinates}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def validate_metric_input(*, geometry: Mapping[str, Any] | None, units: str | None, boundary: Mapping[str, Any] | None) -> dict[str, Any]:
    """Fail closed when a metric lacks units/boundary or has invalid values."""
    if not isinstance(units, str) or not units.strip():
        raise GeometryValidationError("metric units are required")
    if boundary is None:
        raise GeometryValidationError("metric boundary is required")
    boundary_summary = validate_geometry(boundary)
    if geometry is None:
        raise GeometryValidationError("metric geometry is required")
    geometry_summary = validate_geometry(geometry)
    return {"units": units.strip(), "boundary": boundary_summary, "geometry": geometry_summary}


__all__ = [
    "GeometryValidationError",
    "canonical_geometry_hash",
    "polygon_area",
    "polygon_perimeter",
    "validate_geometry",
    "validate_metric_input",
]
