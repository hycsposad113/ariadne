"""Ground sensor grid generation, building exclusion masks, and area-weighted aggregation (W6 precursor lane F3)."""

from __future__ import annotations

import math
from typing import Any, Sequence

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.prepared import prep

from .contracts import GroundGridDefinition, SensorGridResult, SensorPoint


def _to_polygon(geom: Any) -> Polygon | MultiPolygon:
    """Normalize input coordinates or Shapely geometry to a polygonal area."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, (list, tuple)):
        return Polygon(geom)
    raise TypeError(f"Expected Polygon, MultiPolygon, or list of coordinates, got {type(geom)}")


def generate_ground_sensor_grid(
    boundary: Any,
    spacing_m: float = 5.0,
    origin: tuple[float, float] = (0.0, 0.0),
    elevation: float = 0.0,
    surface_offset: float = 0.05,
    building_footprints: Sequence[Any] = (),
    crs: str = "LOCAL_METRE",
) -> list[SensorPoint]:
    """Generate a regular ground sensor grid over a boundary polygon aligned to a fixed world origin.

    Sensors falling inside building footprints are marked as EXCLUDED_INSIDE_FOOTPRINT, not deleted.
    Sensor IDs are deterministically derived from world coordinates so unchanged points keep identical IDs.
    """
    if spacing_m <= 0.0:
        raise ValueError(f"Grid spacing_m must be > 0.0, got {spacing_m}")

    poly = _to_polygon(boundary)
    if not poly.is_valid or poly.is_empty:
        raise ValueError("Invalid or empty boundary polygon for sensor grid generation.")

    prepared_poly = prep(poly)
    prepared_footprints = [prep(_to_polygon(fp)) for fp in building_footprints]

    min_x, min_y, max_x, max_y = poly.bounds
    orig_x, orig_y = origin

    # Snap grid iteration to fixed world origin
    i_min = math.floor((min_x - orig_x) / spacing_m)
    i_max = math.ceil((max_x - orig_x) / spacing_m)
    j_min = math.floor((min_y - orig_y) / spacing_m)
    j_max = math.ceil((max_y - orig_y) / spacing_m)

    cell_area = spacing_m * spacing_m
    points: list[SensorPoint] = []

    for i in range(i_min, i_max + 1):
        x = orig_x + i * spacing_m
        for j in range(j_min, j_max + 1):
            y = orig_y + j * spacing_m
            pt_geom = Point(x, y)

            # Check if point is inside boundary polygon
            if not prepared_poly.covers(pt_geom):
                continue

            # Check if point falls inside any building footprint
            is_excluded = any(fp.covers(pt_geom) for fp in prepared_footprints)
            status = "EXCLUDED_INSIDE_FOOTPRINT" if is_excluded else "VALID"

            sensor = SensorPoint.create(
                x=x,
                y=y,
                z=elevation,
                normal=(0.0, 0.0, 1.0),
                surface_offset=surface_offset,
                status=status,
                cell_area_m2=cell_area,
            )
            points.append(sensor)

    return points


def compute_area_weighted_metric(
    points: Sequence[SensorPoint],
    values: dict[str, float],
) -> tuple[float, float, float]:
    """Compute area-weighted average and total integral for valid sensor points.

    Formula:
        area_weighted_average = Σ(A_i * V_i) / Σ(A_i)
        total_integral = Σ(A_i * V_i)
        total_valid_area = Σ(A_i)

    Excluded points (EXCLUDED_INSIDE_FOOTPRINT) are strictly ignored in the weighted average.

    Returns:
        (area_weighted_average, total_integral, total_valid_area)
    """
    total_area = 0.0
    total_integral = 0.0

    for pt in points:
        if pt.status != "VALID":
            continue
        val = values.get(pt.point_id, 0.0)
        area = pt.cell_area_m2
        total_integral += area * val
        total_area += area

    if total_area <= 0.0:
        return 0.0, 0.0, 0.0

    mean_metric = total_integral / total_area
    return round(mean_metric, 6), round(total_integral, 6), round(total_area, 6)


def create_sensor_grid_result(
    points: list[SensorPoint],
    values: dict[str, float],
    spacing_m: float,
    origin: tuple[float, float] = (0.0, 0.0),
    crs: str = "LOCAL_METRE",
) -> SensorGridResult:
    """Build a typed SensorGridResult capturing sensor coverage, valid counts, and area metrics."""
    total_pts = len(points)
    valid_pts = sum(1 for p in points if p.status == "VALID")
    excluded_pts = total_pts - valid_pts
    coverage = (valid_pts / total_pts) if total_pts > 0 else 0.0

    mean_metric, total_integral, valid_area = compute_area_weighted_metric(points, values)
    total_area = round(sum(point.cell_area_m2 for point in points), 6)
    excluded_area = round(max(0.0, total_area - valid_area), 6)
    area_coverage = valid_area / total_area if total_area > 0.0 else 0.0

    grid_def = GroundGridDefinition(
        origin_x=origin[0],
        origin_y=origin[1],
        spacing_m=spacing_m,
        crs=crs,
        tag="FIXTURE_ONLY",
    )

    return SensorGridResult(
        grid_definition=grid_def,
        points=points,
        total_points=total_pts,
        valid_points=valid_pts,
        excluded_points=excluded_pts,
        coverage_ratio=round(coverage, 6),
        total_area_m2=total_area,
        area_weighted_average=mean_metric,
        total_area_integral=total_integral,
        valid_area_m2=valid_area,
        excluded_area_m2=excluded_area,
        area_coverage_ratio=round(area_coverage, 6),
        fixture_tag="FIXTURE_ONLY",
    )
