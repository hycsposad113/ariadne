"""Fixture massing placement within generated parcels."""

from __future__ import annotations

from dataclasses import dataclass
import math

from shapely.affinity import rotate
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry

from urban_design.morphology.contracts import GeneratedBuilding, GeneratedFloorBlock

_MIN_FLOOR_PLATE_AREA_M2 = 1e-9


@dataclass(frozen=True)
class SiteMassingResult:
    buildings: tuple[GeneratedBuilding, ...]
    discarded_massing_count: int
    discarded_gfa_m2: float


def place_fixture_buildings(
    parcels: tuple[BaseGeometry, ...],
    *,
    floor_count: int,
    maximum_footprint_width_m: float = 24.0,
    maximum_footprint_depth_m: float = 20.0,
    use_label: str = "mixed-use fixture",
) -> tuple[GeneratedBuilding, ...]:
    """Place at most one centred rectangular footprint per parcel, never outside it."""
    buildings: list[GeneratedBuilding] = []
    for index, parcel in enumerate(parcels):
        point = parcel.representative_point()
        bounds = parcel.bounds
        width = min(maximum_footprint_width_m, (bounds[2] - bounds[0]) * 0.6)
        depth = min(maximum_footprint_depth_m, (bounds[3] - bounds[1]) * 0.6)
        for _ in range(14):
            footprint = box(point.x - width / 2, point.y - depth / 2, point.x + width / 2, point.y + depth / 2)
            if width > 0 and depth > 0 and parcel.covers(footprint):
                buildings.append(GeneratedBuilding(
                    building_id=f"fixture-building-{index + 1}",
                    footprint=footprint,
                    floor_count=floor_count,
                    use_label=use_label,
                    strategy_parameter=(
                        f"floor-count={floor_count};preferred-max-footprint="
                        f"{maximum_footprint_width_m:g}x{maximum_footprint_depth_m:g}m;"
                        "placement=parcel-representative-point;fixture-only"
                    ),
                ))
                break
            width *= 0.75
            depth *= 0.75
    return tuple(buildings)


def _polygon_parts(geometry: BaseGeometry) -> tuple[BaseGeometry, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "Polygon":
        return (geometry,)
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return tuple(part for child in geometry.geoms for part in _polygon_parts(child))
    return ()


def subdivide_building_sites(
    zoned_parcels: tuple[tuple[BaseGeometry, str, str], ...],
    *,
    building_plot_size_m: float,
) -> tuple[tuple[BaseGeometry, str, str], ...]:
    """Split large street blocks into a deterministic grid of individual building sites."""
    if isinstance(building_plot_size_m, bool) or not math.isfinite(float(building_plot_size_m)) or building_plot_size_m <= 0:
        raise ValueError("building plot size must be a positive finite number")
    sites: list[tuple[BaseGeometry, str, str]] = []
    for parcel, zone_id, use_label in zoned_parcels:
        min_x, min_y, max_x, max_y = parcel.bounds
        columns = max(1, math.ceil((max_x - min_x) / building_plot_size_m))
        rows = max(1, math.ceil((max_y - min_y) / building_plot_size_m))
        for row in range(rows):
            y0 = min_y + row * building_plot_size_m
            y1 = min(max_y, y0 + building_plot_size_m)
            for column in range(columns):
                x0 = min_x + column * building_plot_size_m
                x1 = min(max_x, x0 + building_plot_size_m)
                cell = box(x0, y0, x1, y1).intersection(parcel)
                for site in _polygon_parts(cell):
                    if site.area > 1e-6:
                        sites.append((site, zone_id, use_label))
    return tuple(sorted(sites, key=lambda item: (
        item[1], tuple(round(value, 6) for value in item[0].bounds), -round(float(item[0].area), 6)
    )))


def _fit_site_footprint(parcel: BaseGeometry, target_area_m2: float) -> BaseGeometry | None:
    """Fit a deterministic axis-aligned footprint inside an irregular parcel."""
    if not math.isfinite(target_area_m2) or target_area_m2 <= _MIN_FLOOR_PLATE_AREA_M2 or parcel.is_empty:
        return None
    point = parcel.representative_point()
    side = min(
        (parcel.bounds[2] - parcel.bounds[0]) * 0.84,
        (parcel.bounds[3] - parcel.bounds[1]) * 0.84,
        target_area_m2 ** 0.5,
    )
    for _ in range(24):
        if side > 0:
            candidate = box(point.x - side / 2, point.y - side / 2, point.x + side / 2, point.y + side / 2)
            if candidate.is_valid and candidate.area > _MIN_FLOOR_PLATE_AREA_M2 and parcel.covers(candidate):
                return candidate
        side *= 0.8
    return None


def _fit_site_footprint_shape_aware(
    parcel: BaseGeometry,
    target_area_m2: float,
    *,
    minimum_footprint_area_m2: float,
    minimum_short_edge_m: float,
) -> BaseGeometry | None:
    """Fit a deterministic bar footprint to a parcel's shape and orientation."""
    if not math.isfinite(target_area_m2) or target_area_m2 < minimum_footprint_area_m2 or parcel.is_empty:
        return None
    coordinates = list(parcel.convex_hull.exterior.coords)[:-1]
    oriented_bounds = []
    for index, first in enumerate(coordinates):
        second = coordinates[(index + 1) % len(coordinates)]
        angle = math.atan2(second[1] - first[1], second[0] - first[0])
        rotated_hull = rotate(parcel.convex_hull, -angle, origin=(0.0, 0.0), use_radians=True)
        min_x, min_y, max_x, max_y = rotated_hull.bounds
        width, height = max_x - min_x, max_y - min_y
        oriented_bounds.append((width * height, angle, width, height))
    _area, principal_angle, envelope_width, envelope_height = min(oriented_bounds, default=(1.0, 0.0, 1.0, 1.0))
    orientations = {0.0, round(principal_angle % (math.pi / 2.0), 10)}
    maximum_ratio = max(
        1.0,
        max(envelope_width, envelope_height) / max(min(envelope_width, envelope_height), 1e-9),
    )
    ratios = sorted({1.0, 1.5, 2.0, 3.0, min(6.0, maximum_ratio)})

    min_x, min_y, max_x, max_y = parcel.bounds
    centers = {(
        float(parcel.representative_point().x), float(parcel.representative_point().y)
    )}
    centroid = parcel.centroid
    if parcel.covers(centroid):
        centers.add((float(centroid.x), float(centroid.y)))
    for x_fraction in (0.25, 0.5, 0.75):
        for y_fraction in (0.25, 0.5, 0.75):
            point = Point(
                min_x + (max_x - min_x) * x_fraction,
                min_y + (max_y - min_y) * y_fraction,
            )
            if parcel.covers(point):
                centers.add((float(point.x), float(point.y)))

    candidates: list[tuple[float, float, float, float, BaseGeometry]] = []
    for angle in sorted(orientations):
        for ratio in ratios:
            width = math.sqrt(target_area_m2 * ratio)
            height = target_area_m2 / width
            for center_x, center_y in sorted(centers):
                local_center = rotate(Point(center_x, center_y), -angle, origin=(0.0, 0.0), use_radians=True)

                def rectangle(scale: float) -> BaseGeometry:
                    raw = box(
                        local_center.x - width * scale / 2.0,
                        local_center.y - height * scale / 2.0,
                        local_center.x + width * scale / 2.0,
                        local_center.y + height * scale / 2.0,
                    )
                    return rotate(raw, angle, origin=(0.0, 0.0), use_radians=True)

                candidate = rectangle(1.0)
                if not parcel.covers(candidate):
                    lower, upper = 0.0, 1.0
                    for _ in range(18):
                        middle = (lower + upper) / 2.0
                        if parcel.covers(rectangle(middle)):
                            lower = middle
                        else:
                            upper = middle
                    candidate = rectangle(lower)
                if candidate.area + 1e-9 < minimum_footprint_area_m2:
                    continue
                short_edge = _minimum_rotated_edge_m(candidate)
                if short_edge + 1e-9 < minimum_short_edge_m:
                    continue
                candidates.append((float(candidate.area), min(width, height), -angle, -center_x, candidate))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[:4])[-1]


def place_site_buildings(
    zoned_parcels: tuple[tuple[BaseGeometry, str, str], ...],
    *,
    strategy_id: str,
    seed: int,
    floor_count: int,
    first_floor_height_m: float,
    standard_floor_height_m: float,
    maximum_new_gfa_m2: float,
    maximum_new_coverage_m2: float,
    zone_gfa_limits_m2: dict[str, float],
    footprint_fraction: float,
    building_plot_size_m: float | None = None,
    minimum_footprint_area_m2: float = 0.0,
    minimum_short_edge_m: float = 0.0,
    footprint_mode: str = "square",
    preserve_capacity_after_discard: bool = False,
) -> SiteMassingResult:
    """Place explicit floor blocks in street-block plots under supplied area caps."""
    if floor_count < 1 or first_floor_height_m <= 0 or standard_floor_height_m <= 0:
        raise ValueError("site massing requires positive floor count and approved floor heights")
    if any(
        isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0
        for value in (minimum_footprint_area_m2, minimum_short_edge_m)
    ):
        raise ValueError("minimum massing dimensions must be finite and nonnegative")
    if footprint_mode not in {"square", "shape-aware"}:
        raise ValueError("footprint mode must be square or shape-aware")
    remaining_gfa = float(maximum_new_gfa_m2)
    remaining_coverage = float(maximum_new_coverage_m2)
    zone_remaining = {key: float(value) for key, value in zone_gfa_limits_m2.items()}
    plots = (
        subdivide_building_sites(zoned_parcels, building_plot_size_m=building_plot_size_m)
        if building_plot_size_m is not None
        else tuple(zoned_parcels)
    )
    ordered = sorted(plots, key=lambda item: (item[1], -round(float(item[0].area), 6), tuple(round(v, 6) for v in item[0].bounds)))
    buildings: list[GeneratedBuilding] = []
    discarded_massing_count = 0
    discarded_gfa_m2 = 0.0
    for plot_index, (parcel, zone_id, use_label) in enumerate(ordered, start=1):
        local_gfa = min(remaining_gfa, zone_remaining.get(zone_id, remaining_gfa))
        footprint_limit = min(remaining_coverage, local_gfa / floor_count)
        target_area = min(float(parcel.area) * footprint_fraction, footprint_limit)
        footprint = (
            _fit_site_footprint_shape_aware(
                parcel,
                target_area,
                minimum_footprint_area_m2=float(minimum_footprint_area_m2),
                minimum_short_edge_m=float(minimum_short_edge_m),
            )
            if footprint_mode == "shape-aware"
            else _fit_site_footprint(parcel, target_area)
        )
        if footprint is None:
            if footprint_mode == "shape-aware" and target_area + 1e-9 >= minimum_footprint_area_m2:
                discarded_massing_count += 1
                discarded_gfa_m2 += target_area * floor_count
            continue
        generated_gfa = float(footprint.area) * floor_count
        if generated_gfa <= 0 or generated_gfa > local_gfa + 1e-8 or footprint.area > remaining_coverage + 1e-8:
            continue
        minimum_short_edge = _minimum_rotated_edge_m(footprint)
        if (
            float(footprint.area) + 1e-9 < float(minimum_footprint_area_m2)
            or minimum_short_edge + 1e-9 < float(minimum_short_edge_m)
        ):
            discarded_massing_count += 1
            discarded_gfa_m2 += generated_gfa
            if not preserve_capacity_after_discard:
                remaining_gfa -= generated_gfa
                remaining_coverage -= float(footprint.area)
                if zone_id in zone_remaining:
                    zone_remaining[zone_id] -= generated_gfa
            continue
        building_id = f"{strategy_id}-{seed}-building-{plot_index}"
        floor_blocks: list[GeneratedFloorBlock] = []
        base_height = 0.0
        for floor_number in range(1, floor_count + 1):
            top_height = first_floor_height_m if floor_number == 1 else base_height + standard_floor_height_m
            floor_blocks.append(GeneratedFloorBlock(
                floor_number=floor_number,
                footprint=footprint,
                base_height_m=base_height,
                top_height_m=top_height,
                use_label=use_label,
            ))
            base_height = top_height
        buildings.append(GeneratedBuilding(
            building_id=building_id,
            footprint=footprint,
            floor_count=floor_count,
            use_label=use_label,
            strategy_parameter=(
                f"strategy={strategy_id};seed={seed};floors={floor_count};"
                f"footprint_fraction={footprint_fraction:.3f};building_plot_size_m={building_plot_size_m};"
                f"building_site_index={plot_index};zone_id={zone_id};"
                "floor_blocks=explicit"
            ),
            zone_id=zone_id,
            floor_blocks=tuple(floor_blocks),
        ))
        remaining_gfa -= generated_gfa
        remaining_coverage -= float(footprint.area)
        if zone_id in zone_remaining:
            zone_remaining[zone_id] -= generated_gfa
    return SiteMassingResult(
        buildings=tuple(buildings),
        discarded_massing_count=discarded_massing_count,
        discarded_gfa_m2=discarded_gfa_m2,
    )


def _minimum_rotated_edge_m(geometry: BaseGeometry) -> float:
    """Return the shortest edge of the footprint's minimum rotated rectangle."""
    polygons = (geometry,) if geometry.geom_type == "Polygon" else tuple(
        item for item in getattr(geometry, "geoms", ()) if item.geom_type == "Polygon"
    )
    candidates = []
    for polygon in polygons:
        coordinates = [(float(x), float(y)) for x, y, *_ in polygon.exterior.coords[:-1]]
        for index, first in enumerate(coordinates):
            second = coordinates[(index + 1) % len(coordinates)]
            dx, dy = second[0] - first[0], second[1] - first[1]
            length = math.hypot(dx, dy)
            if length <= _MIN_FLOOR_PLATE_AREA_M2:
                continue
            ux, uy = dx / length, dy / length
            along = [x * ux + y * uy for x, y in coordinates]
            across = [-x * uy + y * ux for x, y in coordinates]
            width = max(along) - min(along)
            height = max(across) - min(across)
            candidates.append((width * height, min(width, height)))
    return min(candidates)[1] if candidates else 0.0


__all__ = ["SiteMassingResult", "place_fixture_buildings", "place_site_buildings", "subdivide_building_sites"]
