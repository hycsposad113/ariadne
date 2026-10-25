"""Morphological context reading pure functions for urban design.

Provides deterministic calculations for:
- Street network cutting and block polygonization
- Orientation histograms, azimuths, and primary peak detection
- Building coverage (GSI) with water-excluded land denominator
- Floor Space Index (FSI) and floor height estimation
- Building wing depth and dominant typology classification
- Typical parallel street spacing
- Adjacencies and continuation street candidate identification
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    box,
    shape,
)
from shapely.ops import nearest_points, polygonize, unary_union


def normalize_azimuth_deg(deg: float) -> float:
    """Normalize an angle to standard bidirectional line azimuth [0, 180) degrees.

    Azimuth is measured clockwise from True North (0 = North, 90 = East).
    Lines are undirected, so 180 degrees symmetry applies.
    """
    res = deg % 180.0
    return res if res >= 0.0 else res + 180.0


def segment_azimuth_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Compute geographic azimuth (clockwise from North) for a segment in [0, 180).

    In projected Cartesian CRS (e.g. EPSG:28992):
    x is Easting, y is Northing.
    dx = x2 - x1, dy = y2 - y1.
    azimuth = atan2(dx, dy) in degrees.
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    if math.isclose(dx, 0.0, abs_tol=1e-9) and math.isclose(dy, 0.0, abs_tol=1e-9):
        return 0.0
    angle = math.degrees(math.atan2(dx, dy))
    return normalize_azimuth_deg(angle)


def segment_bearing_ccw_east_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Compute mathematical angle CCW from East in [0, 180)."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    if math.isclose(dx, 0.0, abs_tol=1e-9) and math.isclose(dy, 0.0, abs_tol=1e-9):
        return 0.0
    angle = math.degrees(math.atan2(dy, dx))
    res = angle % 180.0
    return res if res >= 0.0 else res + 180.0


def line_azimuth_deg(line: LineString) -> float:
    """Compute length-weighted dominant azimuth for a LineString."""
    coords = list(line.coords)
    if len(coords) < 2:
        return 0.0
    if len(coords) == 2:
        return segment_azimuth_deg(coords[0], coords[1])

    sin_sum = 0.0
    cos_sum = 0.0
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if length <= 1e-6:
            continue
        az = segment_azimuth_deg(p1, p2)
        rad = math.radians(2.0 * az)
        sin_sum += length * math.sin(rad)
        cos_sum += length * math.cos(rad)

    if math.hypot(sin_sum, cos_sum) <= 1e-9:
        return segment_azimuth_deg(coords[0], coords[-1])

    mean_angle_2 = math.degrees(math.atan2(sin_sum, cos_sum))
    return normalize_azimuth_deg(mean_angle_2 / 2.0)


def angle_difference_deg(az1: float, az2: float) -> float:
    """Compute the acute angle difference between two line orientations [0, 90] degrees."""
    diff = abs(az1 - az2) % 180.0
    if diff > 90.0:
        diff = 180.0 - diff
    return diff


def compute_orientation_peaks(
    lines: Sequence[LineString],
    bin_size_deg: float = 5.0,
    min_separation_deg: float = 25.0,
) -> tuple[float | None, float | None, list[dict[str, Any]]]:
    """Calculate orientation histogram and extract the two primary peaks.

    Segments are weighted by length. Returns (peak1_azimuth, peak2_azimuth, bins).
    """
    n_bins = int(round(180.0 / bin_size_deg))
    bin_edges = np.linspace(0.0, 180.0, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    weights = np.zeros(n_bins, dtype=float)

    for line in lines:
        if line.is_empty:
            continue
        coords = list(line.coords)
        for i in range(len(coords) - 1):
            p1, p2 = coords[i], coords[i + 1]
            seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if seg_len <= 1e-6:
                continue
            az = segment_azimuth_deg(p1, p2)
            idx = int(math.floor(az / bin_size_deg)) % n_bins
            weights[idx] += seg_len

    if np.sum(weights) <= 1e-9:
        return None, None, []

    # Circular smoothing with kernel [0.25, 0.5, 0.25]
    smoothed = np.zeros_like(weights)
    for i in range(n_bins):
        im1 = (i - 1) % n_bins
        ip1 = (i + 1) % n_bins
        smoothed[i] = 0.25 * weights[im1] + 0.5 * weights[i] + 0.25 * weights[ip1]

    # Find primary peak (highest mode)
    idx1 = int(np.argmax(smoothed))
    peak1 = float(bin_centers[idx1])

    # Find secondary peak with separation >= min_separation_deg
    best_val = 0.0
    idx2: int | None = None
    for i in range(n_bins):
        diff = angle_difference_deg(bin_centers[i], peak1)
        if diff >= min_separation_deg and smoothed[i] > best_val:
            best_val = smoothed[i]
            idx2 = i

    peak2 = float(bin_centers[idx2]) if idx2 is not None else None

    histogram_records = [
        {
            "bin_start_deg": round(float(bin_edges[i]), 1),
            "bin_end_deg": round(float(bin_edges[i + 1]), 1),
            "bin_center_deg": round(float(bin_centers[i]), 1),
            "raw_length_m": round(float(weights[i]), 2),
            "smoothed_length_m": round(float(smoothed[i]), 2),
        }
        for i in range(n_bins)
    ]

    return round(peak1, 1), (round(peak2, 1) if peak2 is not None else None), histogram_records


def calculate_polygon_mrr_dimensions(poly: Polygon) -> tuple[float, float]:
    """Calculate the short edge and long edge of a polygon's minimum rotated rectangle."""
    if poly.is_empty or not poly.is_valid or poly.area < 1e-4:
        minx, miny, maxx, maxy = poly.bounds
        dx = maxx - minx
        dy = maxy - miny
        return min(dx, dy), max(dx, dy)
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mrr = poly.minimum_rotated_rectangle
        if mrr.geom_type == "Polygon" and len(mrr.exterior.coords) >= 4:
            coords = list(mrr.exterior.coords)
            edge1 = math.hypot(coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])
            edge2 = math.hypot(coords[2][0] - coords[1][0], coords[2][1] - coords[1][1])
            if edge1 > 0 or edge2 > 0:
                return min(edge1, edge2), max(edge1, edge2)
    except Exception:
        pass

    minx, miny, maxx, maxy = poly.bounds
    dx = maxx - minx
    dy = maxy - miny
    return min(dx, dy), max(dx, dy)


def compute_site_principal_axis(site_poly: Polygon) -> dict[str, Any]:
    """Compute the principal long axis and short axis azimuth of the site."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mrr = site_poly.minimum_rotated_rectangle
    if not isinstance(mrr, Polygon) or mrr.is_empty or len(mrr.exterior.coords) < 5:
        minx, miny, maxx, maxy = site_poly.bounds
        mrr = box(minx, miny, maxx, maxy)
    coords = list(mrr.exterior.coords)
    edges: list[tuple[float, float, tuple[tuple[float, float], tuple[float, float]]]] = []
    for i in range(4):
        p1, p2 = coords[i], coords[i + 1]
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        az = segment_azimuth_deg(p1, p2)
        edges.append((length, az, (p1, p2)))

    edges.sort(key=lambda x: x[0], reverse=True)
    long_len, long_az, long_seg = edges[0]
    short_len, short_az, short_seg = edges[2]

    return {
        "long_axis_length_m": round(long_len, 2),
        "long_axis_azimuth_deg": round(long_az, 1),
        "short_axis_length_m": round(short_len, 2),
        "short_axis_azimuth_deg": round(short_az, 1),
        "long_axis_segment": [[round(long_seg[0][0], 2), round(long_seg[0][1], 2)], [round(long_seg[1][0], 2), round(long_seg[1][1], 2)]],
    }


def cut_blocks_from_network(
    window_poly: Polygon,
    road_lines: Sequence[LineString],
    water_polygons: Sequence[Polygon] | None = None,
    min_block_area_m2: float = 100.0,
) -> list[Polygon]:
    """Cut study window by road centerlines and water bodies to extract closed urban blocks."""
    land = window_poly
    if water_polygons:
        valid_waters = [w for w in water_polygons if not w.is_empty and w.is_valid]
        if valid_waters:
            water_union = unary_union(valid_waters)
            if not water_union.is_empty:
                land = land.difference(water_union)

    land_parts: list[Polygon] = []
    if isinstance(land, Polygon):
        land_parts = [land]
    elif isinstance(land, MultiPolygon):
        land_parts = [p for p in land.geoms if not p.is_empty and p.area > min_block_area_m2]

    if not land_parts:
        return []

    valid_roads = [r for r in road_lines if not r.is_empty and r.length > 0]

    all_blocks: list[Polygon] = []
    for part in land_parts:
        clipped_roads: list[LineString] = []
        for r in valid_roads:
            if not r.intersects(part):
                continue
            inter = r.intersection(part)
            if isinstance(inter, LineString):
                clipped_roads.append(inter)
            elif isinstance(inter, MultiLineString):
                clipped_roads.extend([ls for ls in inter.geoms if ls.length > 0])
            elif isinstance(inter, GeometryCollection):
                for g in inter.geoms:
                    if isinstance(g, LineString) and g.length > 0:
                        clipped_roads.append(g)

        boundary_lines: list[LineString] = []
        if part.exterior:
            boundary_lines.append(LineString(part.exterior.coords))
        for interior in part.interiors:
            boundary_lines.append(LineString(interior.coords))

        merged_network = unary_union(boundary_lines + clipped_roads)
        polys = list(polygonize(merged_network))

        for p in polys:
            if not p.is_valid or p.is_empty:
                continue
            rep_point = p.representative_point()
            if part.contains(rep_point) and p.area >= min_block_area_m2:
                all_blocks.append(p)

    return all_blocks


def analyze_block_distribution(
    blocks: Sequence[Polygon],
    window_poly: Polygon,
    boundary_buffer_m: float = 1.0,
) -> dict[str, Any]:
    """Compute distribution statistics for urban blocks: area, short/long edge, complete count."""
    if not blocks:
        return {
            "total_blocks": 0,
            "complete_blocks": 0,
            "area_m2": {"median": 0.0, "p25": 0.0, "p75": 0.0},
            "short_edge_m": {"median": 0.0, "p25": 0.0, "p75": 0.0},
            "long_edge_m": {"median": 0.0, "p25": 0.0, "p75": 0.0},
        }

    areas: list[float] = []
    short_edges: list[float] = []
    long_edges: list[float] = []
    complete_count = 0

    window_boundary = window_poly.boundary

    for b in blocks:
        area = b.area
        areas.append(area)
        s_edge, l_edge = calculate_polygon_mrr_dimensions(b)
        short_edges.append(s_edge)
        long_edges.append(l_edge)

        # Check if complete block (does not touch outer boundary of study window)
        if not b.boundary.intersects(window_boundary):
            complete_count += 1

    areas_arr = np.array(areas)
    short_arr = np.array(short_edges)
    long_arr = np.array(long_edges)

    return {
        "total_blocks": len(blocks),
        "complete_blocks": complete_count,
        "area_m2": {
            "median": round(float(np.median(areas_arr)), 1),
            "p25": round(float(np.percentile(areas_arr, 25)), 1),
            "p75": round(float(np.percentile(areas_arr, 75)), 1),
        },
        "short_edge_m": {
            "median": round(float(np.median(short_arr)), 1),
            "p25": round(float(np.percentile(short_arr, 25)), 1),
            "p75": round(float(np.percentile(short_arr, 75)), 1),
        },
        "long_edge_m": {
            "median": round(float(np.median(long_arr)), 1),
            "p25": round(float(np.percentile(long_arr, 25)), 1),
            "p75": round(float(np.percentile(long_arr, 75)), 1),
        },
    }


def compute_intersection_density(
    road_lines: Sequence[LineString],
    land_area_m2: float,
) -> tuple[int, float]:
    """Find road intersections / junctions and compute density per km².

    Nodes the road network with unary_union to detect all actual crossings and T-junctions.
    A junction is defined as a point where 3 or more segments connect (degree >= 3).
    """
    if land_area_m2 <= 0.0 or not road_lines:
        return 0, 0.0

    valid_roads = [r for r in road_lines if not r.is_empty and r.length > 0]
    if not valid_roads:
        return 0, 0.0

    noded = unary_union(valid_roads)
    segments: list[LineString] = []
    if isinstance(noded, LineString):
        segments = [noded]
    elif isinstance(noded, MultiLineString):
        segments = list(noded.geoms)
    elif isinstance(noded, GeometryCollection):
        for g in noded.geoms:
            if isinstance(g, LineString):
                segments.append(g)

    endpoints: dict[tuple[float, float], int] = {}
    for r in segments:
        coords = list(r.coords)
        if len(coords) < 2:
            continue
        p_start = (round(coords[0][0], 1), round(coords[0][1], 1))
        p_end = (round(coords[-1][0], 1), round(coords[-1][1], 1))
        endpoints[p_start] = endpoints.get(p_start, 0) + 1
        endpoints[p_end] = endpoints.get(p_end, 0) + 1

    junctions = [pt for pt, degree in endpoints.items() if degree >= 3]
    count = len(junctions)
    land_area_km2 = land_area_m2 / 1_000_000.0
    density = count / land_area_km2 if land_area_km2 > 0 else 0.0
    return count, round(density, 1)


def compute_typical_street_spacing(
    road_lines: Sequence[LineString],
    peak_azimuth_deg: float,
    tolerance_deg: float = 15.0,
    min_dist_m: float = 20.0,
    max_dist_m: float = 350.0,
) -> dict[str, Any]:
    """Compute typical spacing between parallel streets aligned with peak azimuth."""
    aligned_segments: list[tuple[Point, float, LineString]] = []
    for r in road_lines:
        if r.is_empty or r.length < 25.0:
            continue
        az = line_azimuth_deg(r)
        if angle_difference_deg(az, peak_azimuth_deg) <= tolerance_deg:
            aligned_segments.append((r.centroid, az, r))

    if len(aligned_segments) < 2:
        return {"median_m": None, "p25_m": None, "p75_m": None, "samples_count": 0}

    # For each segment, find perpendicular distance to nearest parallel neighbor
    spacings: list[float] = []
    rad = math.radians(peak_azimuth_deg)
    # Unit normal vector perpendicular to street direction (clockwise 90 deg)
    nx = math.cos(rad)
    ny = -math.sin(rad)

    for i in range(len(aligned_segments)):
        c1, _, line1 = aligned_segments[i]
        min_p_dist = 1e9
        found = False
        for j in range(len(aligned_segments)):
            if i == j:
                continue
            c2, _, line2 = aligned_segments[j]
            dx = c2.x - c1.x
            dy = c2.y - c1.y
            perp_dist = abs(dx * nx + dy * ny)
            if min_dist_m <= perp_dist <= max_dist_m:
                if perp_dist < min_p_dist:
                    min_p_dist = perp_dist
                    found = True
        if found:
            spacings.append(min_p_dist)

    if not spacings:
        return {"median_m": None, "p25_m": None, "p75_m": None, "samples_count": 0}

    arr = np.array(spacings)
    return {
        "median_m": round(float(np.median(arr)), 1),
        "p25_m": round(float(np.percentile(arr, 25)), 1),
        "p75_m": round(float(np.percentile(arr, 75)), 1),
        "samples_count": len(spacings),
    }


def compute_gsi(
    window_poly: Polygon,
    building_polygons: Sequence[Polygon],
    water_polygons: Sequence[Polygon] | None = None,
) -> dict[str, float | None]:
    """Compute Ground Space Index (GSI / 建蔽率) strictly with land area as denominator."""
    window_area = window_poly.area
    water_union = Polygon()
    if water_polygons:
        valid_waters = [w for w in water_polygons if not w.is_empty and w.is_valid]
        if valid_waters:
            water_union = unary_union(valid_waters)

    if not water_union.is_empty:
        water_in_window = window_poly.intersection(water_union)
        water_area = water_in_window.area
        land = window_poly.difference(water_union)
    else:
        water_area = 0.0
        land = window_poly

    land_area = land.area if not land.is_empty else 0.0
    if land_area <= 0.0:
        return {
            "window_area_m2": round(window_area, 1),
            "water_area_m2": round(water_area, 1),
            "land_area_m2": 0.0,
            "building_footprint_m2": 0.0,
            "gsi": None,
        }

    b_clipped: list[Polygon] = []
    for b in building_polygons:
        if not b.is_empty and b.is_valid and b.intersects(land):
            inter = b.intersection(land)
            if isinstance(inter, Polygon) and inter.area > 0:
                b_clipped.append(inter)
            elif isinstance(inter, MultiPolygon):
                b_clipped.extend([p for p in inter.geoms if p.area > 0])

    if b_clipped:
        b_union = unary_union(b_clipped)
        b_area = b_union.area
    else:
        b_area = 0.0

    gsi = b_area / land_area if land_area > 0 else 0.0
    return {
        "window_area_m2": round(window_area, 1),
        "water_area_m2": round(water_area, 1),
        "land_area_m2": round(land_area, 1),
        "building_footprint_m2": round(b_area, 1),
        "gsi": round(gsi, 3),
    }


def compute_wing_depths(
    building_polygons: Sequence[Polygon],
    min_area_m2: float = 50.0,
) -> dict[str, Any]:
    """Compute wing depth (翼深) distribution for buildings >= min_area_m2."""
    depths: list[float] = []
    for b in building_polygons:
        if b.is_empty or not b.is_valid or b.area < min_area_m2:
            continue
        short_edge, _ = calculate_polygon_mrr_dimensions(b)
        if short_edge > 0.0:
            depths.append(short_edge)

    if not depths:
        return {
            "count": 0,
            "median_m": 0.0,
            "p25_m": 0.0,
            "p75_m": 0.0,
        }

    arr = np.array(depths)
    return {
        "count": len(depths),
        "median_m": round(float(np.median(arr)), 1),
        "p25_m": round(float(np.percentile(arr, 25)), 1),
        "p75_m": round(float(np.percentile(arr, 75)), 1),
    }


def compute_fsi_and_floors(
    buildings_meta: Sequence[dict[str, Any]],
    land_area_m2: float,
    is_industrial: bool | None = None,
) -> dict[str, Any]:
    """Compute FSI only from footprints with explicitly identified 3DBAG heights.

    Floors are estimated as ``height_m / floor_height_m`` (3.0 m residential,
    5.0 m industrial). OSM ``building:levels`` and generic defaults are not
    substituted for missing height observations. Partial height coverage is
    returned separately and never presented as a complete-zone FSI.
    """
    total_footprint = 0.0
    height_footprint = 0.0
    measured_footprint = 0.0
    total_gfa = 0.0
    measured_count = 0
    height_count = 0
    valid_count = 0
    floor_heights: set[float] = set()

    for item in buildings_meta:
        footprint = float(item.get("area_m2", 0.0))
        if footprint <= 0.0:
            continue
        valid_count += 1
        total_footprint += footprint
        if not str(item.get("height_source", "")).upper().startswith("3DBAG"):
            continue
        h = item.get("height_m")
        if h is None or float(h) <= 0.0:
            continue
        height_footprint += footprint
        height_count += 1
        industrial_value = item.get("is_industrial", is_industrial)
        if industrial_value is None:
            continue
        industrial = bool(industrial_value)
        floor_h = 5.0 if industrial else 3.0
        floor_heights.add(floor_h)
        floors = float(h) / floor_h

        gfa = footprint * floors
        measured_footprint += footprint
        total_gfa += gfa
        measured_count += 1

    height_coverage = height_footprint / total_footprint if total_footprint > 0.0 else 0.0
    floor_height_coverage = measured_footprint / total_footprint if total_footprint > 0.0 else 0.0
    observed_fsi = total_gfa / land_area_m2 if land_area_m2 > 0.0 and measured_count else None
    observed_floors = total_gfa / measured_footprint if measured_footprint > 0.0 else None
    complete = valid_count > 0 and floor_height_coverage >= 1.0 - 1e-9 and land_area_m2 > 0.0
    status = "COMPUTED" if complete else ("PARTIAL" if measured_count and land_area_m2 > 0.0 else "UNKNOWN")

    return {
        "status": status,
        "building_count": valid_count,
        "height_building_count": height_count,
        "floor_height_classified_building_count": measured_count,
        "floor_height_assumption_m": next(iter(floor_heights)) if len(floor_heights) == 1 else None,
        "floor_height_assumptions_m": sorted(floor_heights),
        "total_footprint_m2": round(total_footprint, 1),
        "measured_footprint_m2": round(measured_footprint, 1),
        "total_gfa_m2": round(total_gfa, 1) if measured_count else None,
        "height_coverage_ratio": round(height_coverage, 4),
        "floor_height_coverage_ratio": round(floor_height_coverage, 4),
        "fsi": round(observed_fsi, 3) if complete and observed_fsi is not None else None,
        "fsi_observed_subset": round(observed_fsi, 3) if observed_fsi is not None else None,
        "average_floors": round(observed_floors, 2) if complete and observed_floors is not None else None,
        "average_floors_observed_subset": round(observed_floors, 2) if observed_floors is not None else None,
    }


def classify_dominant_typology(
    gsi: float,
    avg_floors: float | None,
    wing_depth_median: float,
    median_block_area_m2: float,
    large_footprint_ratio: float,
    is_port_industrial: bool = False,
) -> tuple[str, str]:
    """Deterministically classify dominant building typology.

    Typologies:
    - 周邊式 (Perimeter block / Courtyard): high enclosure, moderate wing depth 10-22m, 2.5-6 floors, GSI >= 0.35.
    - 板樓 (Linear / Slab block): elongated rows, wing depth 10-18m, GSI < 0.35, floors >= 3.5.
    - 廠房 / 倉庫 (Industrial hall / warehouse): large footprint ratio > 0.4, low floor count, wing depth > 25m.
    - 點式 (Point block / Detached / Villa): compact detached footprint, low GSI or point tower.
    """
    if gsi <= 0.0 and wing_depth_median <= 0.0 and large_footprint_ratio <= 0.0:
        return "UNKNOWN", "缺少可量測建物足跡，無法判定主導類型"
    if is_port_industrial or large_footprint_ratio >= 0.40 or wing_depth_median >= 28.0:
        return "廠房 / 倉庫", "大跨度單層或雙層物流廠房，翼深廣，占地規模大且建蔽率集中於巨型量體"
    if (
        gsi >= 0.35
        and 8.0 <= wing_depth_median <= 22.0
        and (avg_floors is None or 2.2 <= avg_floors <= 6.5)
    ):
        return "周邊式", "街廓外緣連續圍合建築群，具內部中庭或院落，標準進深 10–18 m"
    if (
        gsi < 0.35
        and 9.0 <= wing_depth_median <= 18.0
        and (avg_floors is None or avg_floors >= 3.5)
    ):
        return "板樓", "平行排列或開放式條形板樓，具良好採光面與綠地間距"
    if wing_depth_median < 14.0 and gsi < 0.30:
        return "點式", "獨立低層或塔式量體，密度較鬆散，周邊開敞空間占比高"
    return "混合／未判定", "現有足跡、建蔽率與街廓指標未形成單一類型的穩定判定"


def find_continuation_street_candidates(
    site_poly: Polygon,
    streets: Sequence[dict[str, Any]],
    max_search_dist_m: float = 300.0,
    min_length_m: float = 30.0,
) -> list[dict[str, Any]]:
    """Identify nearby streets whose local direction can geometrically extend into the site."""
    candidates: list[dict[str, Any]] = []
    site_centroid = site_poly.centroid
    max_direction_deviation_deg = 25.0

    for st in streets:
        geom = st.get("geometry")
        if not isinstance(geom, LineString) or geom.length < min_length_m:
            continue
        line_point, boundary_point = nearest_points(geom, site_poly.boundary)
        dist = line_point.distance(boundary_point)
        if dist > max_search_dist_m or dist < 0.5:
            continue

        along = geom.project(line_point)
        delta = min(5.0, geom.length / 4.0)
        before = geom.interpolate(max(0.0, along - delta))
        after = geom.interpolate(min(geom.length, along + delta))
        tangent_dx = after.x - before.x
        tangent_dy = after.y - before.y
        tangent_len = math.hypot(tangent_dx, tangent_dy)
        if tangent_len <= 1e-9:
            continue
        approach_dx = boundary_point.x - line_point.x
        approach_dy = boundary_point.y - line_point.y
        approach_len = math.hypot(approach_dx, approach_dy)
        dot = (tangent_dx * approach_dx + tangent_dy * approach_dy) / (tangent_len * approach_len)
        alignment = abs(max(-1.0, min(1.0, dot)))
        if alignment < math.cos(math.radians(max_direction_deviation_deg)):
            continue

        az = segment_azimuth_deg((before.x, before.y), (after.x, after.y))
        nearest_site_pt = boundary_point
        extension = LineString([(line_point.x, line_point.y), (boundary_point.x, boundary_point.y)])
        if not extension.intersects(site_poly):
            continue
        dx = nearest_site_pt.x - site_centroid.x
        dy = nearest_site_pt.y - site_centroid.y

        if abs(dy) > abs(dx):
            side = "北側" if dy > 0 else "南側"
        else:
            side = "東側" if dx > 0 else "西側"

        candidates.append({
            "name": st.get("name") or "未命名街道",
            "highway": st.get("highway", "residential"),
            "azimuth_deg": round(az, 1),
            "distance_to_site_m": round(dist, 1),
            "approach_side": side,
            "direction_alignment_deg": round(math.degrees(math.acos(alignment)), 1),
            "connection_point": [round(nearest_site_pt.x, 2), round(nearest_site_pt.y, 2)],
            "street_end_point": [round(line_point.x, 2), round(line_point.y, 2)],
            "extension_line": [
                [round(line_point.x, 2), round(line_point.y, 2)],
                [round(nearest_site_pt.x, 2), round(nearest_site_pt.y, 2)],
            ],
        })

    candidates.sort(key=lambda c: c["distance_to_site_m"])
    return candidates
