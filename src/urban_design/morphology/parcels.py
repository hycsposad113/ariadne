"""Deterministic fixture parcel extraction and fragment exclusion."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Iterable

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


@dataclass(frozen=True)
class ExcludedParcelFragment:
    area_m2: float
    minimum_width_m: float
    reason: str
    fragment_id: str = ""
    geometry: BaseGeometry | None = None


@dataclass(frozen=True)
class ParcelizationResult:
    parcels: tuple[Polygon, ...]
    excluded_fragments: tuple[ExcludedParcelFragment, ...]


def _polygon_parts(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "Polygon":
        return (geometry,)
    if geometry.geom_type == "MultiPolygon":
        return tuple(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return tuple(part for child in geometry.geoms for part in _polygon_parts(child))
    return ()


def _minimum_width(geometry: BaseGeometry) -> float:
    """Return convex-hull minimum width without GEOS oriented-envelope warnings."""
    hull = geometry.convex_hull
    if hull.geom_type != "Polygon":
        return 0.0
    coordinates = list(hull.exterior.coords)[:-1]
    widths = []
    for index, first in enumerate(coordinates):
        second = coordinates[(index + 1) % len(coordinates)]
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            continue
        normal_x, normal_y = -dy / length, dx / length
        projections = [x * normal_x + y * normal_y for x, y in coordinates]
        widths.append(max(projections) - min(projections))
    return min(widths, default=0.0)


def parcelize(
    design_area: BaseGeometry,
    exclusions: Iterable[BaseGeometry],
    *,
    minimum_area_m2: float,
    minimum_width_m: float,
) -> ParcelizationResult:
    """Subtract roads, retained footprints, and open space; report tiny fragments."""
    for value, name in ((minimum_area_m2, "minimum parcel area"), (minimum_width_m, "minimum parcel width")):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    cutouts = tuple(item for item in exclusions if not item.is_empty)
    remainder = design_area.difference(unary_union(cutouts)) if cutouts else design_area
    parts = sorted(
        _polygon_parts(remainder),
        key=lambda item: (tuple(round(value, 6) for value in item.bounds), -round(item.area, 6)),
    )
    retained: list[Polygon] = []
    excluded: list[ExcludedParcelFragment] = []
    for part in parts:
        width = _minimum_width(part) if part.area > 1e-9 else 0.0
        reasons: list[str] = []
        if part.area < minimum_area_m2:
            reasons.append("below_versioned_minimum_area")
        if width < minimum_width_m:
            reasons.append("below_versioned_minimum_width")
        if reasons:
            fragment_hash = hashlib.sha256(part.normalize().wkb).hexdigest()
            excluded.append(ExcludedParcelFragment(
                float(part.area),
                float(width),
                "+".join(reasons),
                "fragment-" + fragment_hash[:16],
                part,
            ))
        else:
            retained.append(part)
    return ParcelizationResult(tuple(retained), tuple(excluded))


__all__ = ["ExcludedParcelFragment", "ParcelizationResult", "parcelize"]
