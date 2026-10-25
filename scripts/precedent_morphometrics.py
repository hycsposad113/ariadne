#!/usr/bin/env python3
"""Reproducible, source-bounded morphology measurements for KB4 precedents.

The analysis uses Python's standard library and Shapely. OSM lon/lat geometry
is placed in a local equirectangular metric plane for each small study window;
that projection is used for within-window distances and areas only. Dutch
3DBAG heights are joined only by observed BAG identifiers. Unknown heights are
kept unknown and excluded from the measured floor-area subtotal.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont
from shapely import from_wkb
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, shape
from shapely.ops import linemerge, nearest_points, polygonize, transform, unary_union
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/kb4-precedents"
R_EARTH_M = 6_371_008.8
FLOOR_TO_FLOOR_M = 3.0
METRIC_METHOD = "local equirectangular tangent plane centered on the OSM study-area anchor; R=6371008.8 m"
TYPE_NAMES = ("周邊式", "板樓", "連棟", "點式", "合院", "混合／未分類")
BLOCK_EDGE_HIGHWAYS = {"primary", "secondary", "tertiary", "residential", "unclassified", "living_street", "pedestrian"}
ACCESSORY_BUILDING_TYPES = {"carport", "garage", "garages", "hut", "kiosk", "outbuilding", "roof", "service", "shed", "storage_tank", "transformer_tower"}
BUILDING_MERGE_TOLERANCE_M = 0.5
MIN_BLOCK_AREA_M2 = 1_000.0
FIGURE_SCALE_DENOMINATOR = 5_000
FIGURE_DPI = 120
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
CITY_NAMES_ZH = {
    "Amsterdam": "阿姆斯特丹", "Rotterdam": "鹿特丹", "Copenhagen": "哥本哈根",
    "Malmö": "馬爾默", "Stockholm": "斯德哥爾摩", "Hamburg": "漢堡",
    "Freiburg": "弗萊堡", "Barcelona": "巴塞隆納",
}


def utc_now() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def project_function(lon0: float, lat0: float):
    lat0_rad = math.radians(lat0)
    x_scale = R_EARTH_M * math.cos(lat0_rad) * math.pi / 180.0
    y_scale = R_EARTH_M * math.pi / 180.0

    def project(x: Any, y: Any, z: Any = None):
        if hasattr(x, "__iter__"):
            xs = [x_scale * (float(value) - lon0) for value in x]
            ys = [y_scale * (float(value) - lat0) for value in y]
            if z is None:
                return xs, ys
            return xs, ys, z
        if z is None:
            return x_scale * (float(x) - lon0), y_scale * (float(y) - lat0)
        return x_scale * (float(x) - lon0), y_scale * (float(y) - lat0), z

    return project


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def distribution(values: Iterable[float], digits: int = 2) -> dict[str, Any]:
    raw = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return {
        "sample_count": len(raw),
        "min": rounded(min(raw), digits) if raw else None,
        "p25": rounded(percentile(raw, 0.25), digits),
        "median": rounded(percentile(raw, 0.5), digits),
        "p75": rounded(percentile(raw, 0.75), digits),
        "max": rounded(max(raw), digits) if raw else None,
    }


def rounded(value: float | None, digits: int = 3) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _coordinates(element: dict[str, Any]) -> list[tuple[float, float]]:
    points = element.get("geometry") or []
    return [(float(row["lon"]), float(row["lat"])) for row in points if row.get("lon") is not None and row.get("lat") is not None]


def _relation_geometry(element: dict[str, Any]):
    outer_rings: list[list[tuple[float, float]]] = []
    inner_rings: list[list[tuple[float, float]]] = []
    lines: list[LineString] = []
    for member in element.get("members", []):
        points = _coordinates(member)
        if len(points) < 2:
            continue
        if member.get("type") == "way" and points[0] == points[-1] and len(points) >= 4:
            (inner_rings if member.get("role") == "inner" else outer_rings).append(points)
        else:
            lines.append(LineString(points))
    polygons: list[Polygon] = []
    if outer_rings:
        for shell in polygonize([LineString(ring) for ring in outer_rings]):
            holes = [ring for ring in inner_rings if shell.covers(Polygon(ring).representative_point())]
            candidate = Polygon(shell.exterior.coords, [ring for ring in holes])
            polygons.append(candidate if candidate.is_valid else candidate.buffer(0))
    if polygons:
        return unary_union(polygons)
    return unary_union(lines) if lines else None


def element_geometry(element: dict[str, Any], *, polygon: bool):
    if element.get("type") == "way":
        points = _coordinates(element)
        if len(points) < 2:
            return None
        if polygon and len(points) >= 4 and points[0] == points[-1]:
            candidate = Polygon(points)
            return candidate if candidate.is_valid else candidate.buffer(0)
        return LineString(points)
    if element.get("type") == "relation":
        return _relation_geometry(element)
    return None


def _as_polygons(geometry) -> Iterator[Polygon]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms
    elif isinstance(geometry, GeometryCollection):
        for part in geometry.geoms:
            yield from _as_polygons(part)


def _as_lines(geometry) -> Iterator[LineString]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, LineString):
        yield geometry
    elif isinstance(geometry, MultiLineString):
        yield from geometry.geoms
    elif isinstance(geometry, GeometryCollection):
        for part in geometry.geoms:
            yield from _as_lines(part)


def _numeric_tag(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _height_m_from_osm(tags: dict[str, Any]) -> float | None:
    raw = tags.get("height")
    value = _numeric_tag(raw)
    if value is None:
        return None
    lowered = str(raw).casefold()
    if any(unit in lowered for unit in ("ft", "feet", "foot", "′", "'")):
        value *= 0.3048
    # Bare OSM height values use metres by convention; this is recorded in the
    # method note and is never inferred from footprint geometry.
    return value if value > 0 else None


def bag_ids(tags: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for key, value in tags.items():
        if "bag" not in str(key).casefold() and "bag" not in str(value).casefold():
            continue
        for ident in re.findall(r"\d{16}", str(value)):
            found.add(ident)
    return found


def _gpkg_wkb(blob: bytes) -> bytes:
    if len(blob) < 8 or blob[:2] != b"GP":
        return blob
    flags = blob[3]
    envelope_code = (flags >> 1) & 0b111
    envelope_lengths = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    return blob[8 + envelope_lengths.get(envelope_code, 0):]


def load_3dbag_height_index(manifest_path: Path) -> tuple[dict[str, float], dict[str, Any]]:
    if not manifest_path.is_file():
        return {}, {"status": "NOT_ACQUIRED", "manifest_path": str(manifest_path.relative_to(ROOT)), "tile_count": 0, "matched_building_ids": 0}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    heights: dict[str, float] = {}
    tile_count = 0
    schemas: Counter[str] = Counter()
    tile_errors: list[dict[str, str]] = []
    tmp_parent = Path(os.environ.get("TMPDIR", "/private/tmp"))
    tmp_parent.mkdir(parents=True, exist_ok=True)
    for item in manifest.get("tiles", []):
        source = ROOT / item["response_path"]
        if not source.is_file() or sha256(source) != item.get("response_sha256"):
            continue
        tile_count += 1
        try:
            with tempfile.TemporaryDirectory(prefix="kb4-3dbag-", dir=tmp_parent) as temp_dir:
                gpkg_path = Path(temp_dir) / "tile.gpkg"
                if source.suffix.casefold() == ".gz":
                    with gzip.open(source, "rb") as compressed, gpkg_path.open("wb") as expanded:
                        while block := compressed.read(1024 * 1024):
                            expanded.write(block)
                else:
                    gpkg_path.write_bytes(source.read_bytes())
                uri = f"file:{gpkg_path.resolve()}?mode=ro"
                connection = sqlite3.connect(uri, uri=True)
                try:
                    tables = [row[0] for row in connection.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
                    table_columns = {}
                    for table in tables:
                        escaped = table.replace('"', '""')
                        table_columns[table] = [row[1] for row in connection.execute(f'PRAGMA table_info("{escaped}")')]
                    roof_table = next((name for name in ("lod22_2d", "lod13_2d", "lod12_2d")
                                       if name in table_columns and "b3_h_70p" in table_columns[name]
                                       and "identificatie" in table_columns[name]), None)
                    ground_table = next((name for name in tables if "b3_h_maaiveld" in table_columns[name]
                                         and "identificatie" in table_columns[name]), None)
                    if not roof_table or not ground_table:
                        tile_errors.append({"tile_id": str(item.get("tile_id")), "error": "required roof/ground fields or BAG identifier column absent"})
                        continue
                    schemas[f"{roof_table}+{ground_table}"] += 1
                    roof_sql = '"' + roof_table.replace('"', '""') + '"'
                    ground_sql = '"' + ground_table.replace('"', '""') + '"'
                    query = (
                        f"SELECT r.identificatie, MAX(r.b3_h_70p), MIN(g.b3_h_maaiveld) "
                        f"FROM {roof_sql} AS r JOIN {ground_sql} AS g "
                        "ON r.identificatie = g.identificatie "
                        "WHERE r.b3_h_70p IS NOT NULL AND g.b3_h_maaiveld IS NOT NULL "
                        "GROUP BY r.identificatie"
                    )
                    for raw_id, roof_value, ground_value in connection.execute(query):
                        roof = _numeric_tag(roof_value)
                        ground = _numeric_tag(ground_value)
                        if roof is None or ground is None or roof <= ground:
                            continue
                        height = roof - ground
                        for ident in re.findall(r"\d{16}", str(raw_id or "")):
                            heights[ident] = max(height, heights.get(ident, 0.0))
                finally:
                    connection.close()
        except (OSError, EOFError, sqlite3.Error) as exc:
            tile_errors.append({"tile_id": str(item.get("tile_id")), "error": f"{type(exc).__name__}: {exc}"})
    return heights, {
        "status": "OBSERVED" if heights else "NO_MATCHING_HEIGHT_ROWS",
        "manifest_path": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256(manifest_path),
        "tile_count": tile_count,
        "matched_building_ids": len(heights),
        "feature_tables": sorted(schemas),
        "tile_errors": tile_errors,
        "height_fields": ["b3_h_70p", "b3_h_maaiveld"],
        "height_definition": "per BAG identification, max(b3_h_70p from preferred LOD22/LOD13/LOD12 2D roof geometry) minus b3_h_maaiveld from pand table; NAP-referenced metres",
        "tiles": [
            {key: row.get(key) for key in ("tile_id", "response_path", "response_sha256", "response_size_bytes", "retrieved_at_utc", "url")}
            for row in manifest.get("tiles", [])
        ],
    }


def _building_record(element: dict[str, Any], area_metric, project, height_index: dict[str, float], dutch: bool):
    tags = element.get("tags", {})
    geometry = element_geometry(element, polygon=True)
    if geometry is None:
        return None
    metric = transform(project, geometry)
    clipped = metric.intersection(area_metric)
    if not clipped.is_valid:
        clipped = clipped.buffer(0)
    polygons = [part for part in _as_polygons(clipped) if part.area > 2.0]
    if not polygons:
        return None
    footprint = unary_union(polygons)
    if footprint.area <= 2.0:
        return None
    levels = _numeric_tag(tags.get("building:levels") or tags.get("levels"))
    height_source = "OSM building:levels" if levels is not None else None
    height_m: float | None = None
    if dutch:
        ids = bag_ids(tags)
        height_m = next((height_index[ident] for ident in ids if ident in height_index), None)
        if height_m is not None:
            levels = height_m / FLOOR_TO_FLOOR_M
            height_source = "3DBAG b3_h_70p - b3_h_maaiveld; floor count derived using 3.0 m/floor assumption"
        else:
            levels = None
            height_source = None
    elif levels is None:
        height_m = _height_m_from_osm(tags)
        if height_m is not None:
            levels = height_m / FLOOR_TO_FLOOR_M
            height_source = "OSM height; floor count derived using 3.0 m/floor assumption"
    return {
        "id": f"{element.get('type')}/{element.get('id')}",
        "tags": tags,
        "geometry": footprint,
        "area_m2": footprint.area,
        "levels": levels if levels is not None and levels > 0 else None,
        "height_m": height_m,
        "height_source": height_source,
        "bag_ids": sorted(bag_ids(tags)),
    }


def _unique_buildings(elements: list[dict[str, Any]], area_metric, project, height_index: dict[str, float], dutch: bool) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    geometries_seen: list[Polygon | MultiPolygon] = []
    for element in elements:
        tags = element.get("tags", {})
        if "building" not in tags and "building:part" not in tags:
            continue
        item = _building_record(element, area_metric, project, height_index, dutch)
        if item is None:
            continue
        geometry = item["geometry"]
        if any(geometry.equals(existing) or (geometry.intersection(existing).area / max(1.0, min(geometry.area, existing.area))) > 0.995 for existing in geometries_seen):
            continue
        selected.append(item)
        geometries_seen.append(geometry)
    return selected


def _edge_lengths(geometry) -> list[float]:
    """Return lengths from dissolved major-street segments between junctions."""
    geometries = geometry if isinstance(geometry, (list, tuple)) else [geometry]
    return [line.length for item in geometries for line in _as_lines(item) if line.length > 0.1]


def _is_accessory_building(building: dict[str, Any]) -> bool:
    kind = str(building.get("tags", {}).get("building", "")).casefold()
    return kind in ACCESSORY_BUILDING_TYPES


def _building_depth(mass: dict[str, Any]) -> float | None:
    """Use the merged mass minimum-rectangle short side as depth proxy."""
    dimensions = _minimum_rotated_dimensions(mass["geometry"])
    return dimensions[0] if dimensions else None


def _area_perimeter_depth(mass: dict[str, Any]) -> float | None:
    geometry = mass["geometry"]
    return 2.0 * geometry.area / geometry.length if geometry.length > 0 else None


def _minimum_rotated_dimensions(geometry) -> tuple[float, float] | None:
    """Minimum-area rectangle side lengths, evaluated over convex-hull edges."""
    hull = geometry.convex_hull
    if not isinstance(hull, Polygon):
        return None
    points = list(hull.exterior.coords)[:-1]
    if len(points) < 3:
        return None
    best_area = math.inf
    best_dimensions: tuple[float, float] | None = None
    for first, second in zip(points, points[1:] + points[:1]):
        dx, dy = second[0] - first[0], second[1] - first[1]
        if math.hypot(dx, dy) <= 1e-9:
            continue
        angle = math.atan2(dy, dx)
        cosine, sine = math.cos(angle), math.sin(angle)
        along = [x * cosine + y * sine for x, y in points]
        across = [-x * sine + y * cosine for x, y in points]
        width, depth = max(along) - min(along), max(across) - min(across)
        area = width * depth
        if area < best_area:
            best_area = area
            best_dimensions = tuple(sorted((width, depth)))
    return best_dimensions


def _shape_ratio(building: dict[str, Any]) -> float | None:
    sides = _minimum_rotated_dimensions(building["geometry"])
    if not sides or sides[0] <= 0:
        return None
    return sides[-1] / sides[0]


def merge_touching_buildings(buildings: list[dict[str, Any]], tolerance_m: float = BUILDING_MERGE_TOLERANCE_M) -> list[dict[str, Any]]:
    """Merge connected building footprints within tolerance for mass-level measures.

    The closing operation only creates mass geometry; footprint and floor-area
    totals continue to use the original, deduplicated building records.
    """
    if not buildings:
        return []
    geometries = [row["geometry"] for row in buildings]
    tree = STRtree(geometries)
    parents = list(range(len(buildings)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[root_right] = root_left

    for index, geometry in enumerate(geometries):
        expanded = geometry.buffer(tolerance_m)
        for candidate in tree.query(expanded, predicate="intersects"):
            other = int(candidate)
            if other > index and geometry.distance(geometries[other]) <= tolerance_m + 1e-8:
                union(index, other)

    groups: dict[int, list[int]] = {}
    for index in range(len(buildings)):
        groups.setdefault(find(index), []).append(index)

    masses: list[dict[str, Any]] = []
    radius = tolerance_m / 2.0
    for members in sorted(groups.values(), key=lambda indices: indices[0]):
        source_geometries = [geometries[index] for index in members]
        closed = unary_union([geometry.buffer(radius, join_style="mitre") for geometry in source_geometries]).buffer(-radius, join_style="mitre")
        if closed.is_empty or not closed.is_valid:
            closed = unary_union(source_geometries)
        source_rows = [buildings[index] for index in members]
        known_levels = [float(row["levels"]) for row in source_rows if row.get("levels") is not None]
        dimensions = [_minimum_rotated_dimensions(geometry) for geometry in source_geometries]
        small_units = all(
            row["area_m2"] <= 260.0 and dimension is not None and dimension[0] <= 16.0
            for row, dimension in zip(source_rows, dimensions)
        )
        max_levels = max(known_levels) if known_levels else None
        masses.append({
            "id": f"mass/{len(masses) + 1}",
            "geometry": closed,
            "area_m2": closed.area,
            "constituent_count": len(members),
            "member_ids": [row.get("id") for row in source_rows],
            "member_area_m2": [float(row["area_m2"]) for row in source_rows],
            "max_known_levels": max_levels,
            "all_member_levels_known": len(known_levels) == len(source_rows),
            "rowhouse_candidate": len(members) >= 3 and small_units and len(known_levels) == len(source_rows) and max_levels <= 4.0,
        })
    return masses


def _mass_has_courtyard(mass) -> bool:
    return any(sum(Polygon(ring).area for ring in polygon.interiors) >= 50.0 for polygon in _as_polygons(mass["geometry"]))


def _block_type(block, masses: list[dict[str, Any]]) -> str:
    local = []
    for mass in masses:
        footprint = mass["geometry"].intersection(block)
        if footprint.area > 10:
            local.append({**mass, "geometry": footprint, "area_m2": footprint.area})
    if not local:
        return "混合／未分類"
    built_union = unary_union([row["geometry"] for row in local])
    holes = sum(sum(Polygon(ring).area for ring in polygon.interiors) for polygon in _as_polygons(built_union))
    perimeter = block.boundary.length
    frontage_ratio = block.boundary.intersection(built_union.buffer(4.0)).length / perimeter if perimeter > 0 else 0.0
    if holes >= max(50.0, block.area * 0.04):
        if frontage_ratio >= 0.65:
            return "周邊式"
        if sum(1 for row in local if _mass_has_courtyard(row)) == 1:
            return "合院"
    total_mass_area = sum(row["area_m2"] for row in local)
    if total_mass_area <= 0:
        return "混合／未分類"
    rowhouse_share = sum(row["area_m2"] for row in local if row.get("rowhouse_candidate")) / total_mass_area
    if rowhouse_share >= 0.50:
        return "連棟"
    slab_share = sum(row["area_m2"] for row in local if (_shape_ratio(row) or 0.0) > 3.0) / total_mass_area
    if slab_share >= 0.50:
        return "板樓"
    point_share = sum(
        row["area_m2"] for row in local
        if (_shape_ratio(row) or math.inf) < 1.6 and row["area_m2"] < 1_200.0
    ) / total_mass_area
    if point_share >= 0.50:
        return "點式"
    return "混合／未分類"


def _street_width_samples(buildings: list[dict[str, Any]], road_lines: list[LineString]) -> list[float]:
    if len(buildings) < 2 or not road_lines:
        return []
    road_network = unary_union(road_lines).buffer(1.5)
    samples: list[float] = []
    for left_index, left in enumerate(buildings):
        for right in buildings[left_index + 1:]:
            distance = left["geometry"].distance(right["geometry"])
            if not 4.0 <= distance <= 70.0:
                continue
            point_a, point_b = nearest_points(left["geometry"], right["geometry"])
            connector = LineString([point_a, point_b])
            if connector.intersects(road_network):
                samples.append(distance)
    return samples


def _is_block_edge_road(tags: dict[str, Any]) -> bool:
    highway = tags.get("highway")
    if highway == "pedestrian":
        return tags.get("area") != "yes" and bool(tags.get("name") or tags.get("ref"))
    return highway in BLOCK_EDGE_HIGHWAYS - {"pedestrian"}


def _block_stats(land_area, study_area, road_lines: list[LineString], masses: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [line.simplify(0.5, preserve_topology=True) for road in road_lines
             for line in _as_lines(road.intersection(land_area)) if line.length > 2]
    if not lines:
        return {
            "count": 0,
            "complete_count": 0,
            "area_m2": distribution([]),
            "area_m2_all_observed": distribution([]),
            "edge_length_m": distribution([]),
            "types": {},
            "boundary_clipped_count": 0,
            "small_fragment_count": 0,
            "small_fragment_area_m2": 0.0,
            "unclassified_share": None,
            "typology_sample_count": 0,
            "geometries": [],
            "boundary_note": "未取得可形成封閉街廓的道路幾何，因此未計街廓。",
        }
    components = list(_as_polygons(land_area))
    candidates = []
    for component in components:
        local_lines = [line.intersection(component) for line in lines if line.intersects(component)]
        local_lines = [line for geometry in local_lines for line in _as_lines(geometry) if line.length > 2]
        network = unary_union([*local_lines, component.boundary])
        candidates.extend(poly.intersection(component) for poly in polygonize(network))
    candidates = [poly for poly in candidates if not poly.is_empty and poly.area > 10]
    fragments = [poly for poly in candidates if poly.area < MIN_BLOCK_AREA_M2]
    blocks = [poly for poly in candidates if poly.area >= MIN_BLOCK_AREA_M2]
    clipped = [block.boundary.intersection(study_area.boundary).length > 0.1 for block in blocks]
    complete_blocks = [block for block, is_clipped in zip(blocks, clipped) if not is_clipped]
    areas_all = [poly.area for poly in blocks]
    areas_complete = [poly.area for poly in complete_blocks]
    noded_roads = unary_union(lines)
    merged_road_segments = linemerge(noded_roads) if noded_roads.geom_type in ("MultiLineString", "GeometryCollection") else noded_roads
    interior_street_edges = [
        line for line in _as_lines(merged_road_segments)
        if line.length > 0.1
        and Point(line.coords[0]).distance(study_area.boundary) > 0.1
        and Point(line.coords[-1]).distance(study_area.boundary) > 0.1
    ]
    edges = _edge_lengths(interior_street_edges)
    counts: Counter[str] = Counter(_block_type(poly, masses) for poly in complete_blocks)
    type_mix = {
        label: {"block_count": counts[label], "share": rounded(counts[label] / len(complete_blocks), 4) if complete_blocks else None}
        for label in TYPE_NAMES
    }
    clipped_count = sum(clipped)
    return {
        "count": len(blocks),
        "complete_count": len(complete_blocks),
        "area_m2": distribution(areas_complete),
        "area_m2_all_observed": distribution(areas_all),
        "edge_length_m": distribution(edges),
        "types": type_mix,
        "boundary_clipped_count": clipped_count,
        "small_fragment_count": len(fragments),
        "small_fragment_area_m2": rounded(sum(poly.area for poly in fragments), 2),
        "unclassified_share": rounded(counts["混合／未分類"] / len(complete_blocks), 4) if complete_blocks else None,
        "typology_sample_count": len(complete_blocks),
        "geometries": blocks,
        "boundary_note": f"街廓由主要街道中心線切分；低於 {MIN_BLOCK_AREA_M2:.0f} m² 的 {len(fragments)} 個碎片排除。總街廓 {len(blocks)} 個，完整窗內街廓 {len(complete_blocks)} 個、截邊 {clipped_count} 個；邊長取主要街道交叉口間已合併街段，研究窗邊界端點街段不納入。",
    }


def _water_access_class(elements: list[dict[str, Any]], project, area_metric, water_geoms: list[Any]) -> dict[str, Any]:
    public_routes = 0
    restricted_routes = 0
    unknown_routes = 0
    nearby_route_count = 0
    for element in elements:
        tags = element.get("tags", {})
        if tags.get("highway") not in ("footway", "pedestrian", "path", "steps", "living_street"):
            continue
        geometry = element_geometry(element, polygon=False)
        if geometry is None:
            continue
        metric = transform(project, geometry)
        if metric.distance(unary_union(water_geoms)) > 15:
            continue
        nearby_route_count += 1
        access = str(tags.get("access", "")).casefold()
        foot = str(tags.get("foot", "")).casefold()
        if access in ("private", "no") or foot in ("private", "no"):
            restricted_routes += 1
        elif access in ("yes", "permissive") or foot in ("yes", "permissive"):
            public_routes += 1
        else:
            unknown_routes += 1
    if public_routes:
        status = "OSM_EXPLICIT_OPEN_ACCESS_TAG_NEAR_WATER"
    elif restricted_routes:
        status = "OSM_EXPLICIT_RESTRICTION_TAG_NEAR_WATER"
    else:
        status = "ACCESS_UNRESOLVED_FROM_OSM"
    return {
        "status": status,
        "nearby_mapped_route_count": nearby_route_count,
        "routes_with_explicit_open_access_tags": public_routes,
        "routes_with_explicit_restriction_tags": restricted_routes,
        "routes_with_ambiguous_access": unknown_routes,
        "interpretation_limit": "OSM access/path tags are mapped observations, not a legal easement, ownership, or verified public-access determination.",
    }


def calculate_metrics(area_metric, buildings: list[dict[str, Any]], road_lines: list[LineString], water_geoms: list[Any], elements: list[dict[str, Any]], project, *, height_source: str, snapshot_date: str, land_area=None, water_area_geoms: list[Any] | None = None) -> dict[str, Any]:
    gross_area_m2 = area_metric.area
    land_area = land_area if land_area is not None else area_metric
    land_area_m2 = land_area.area
    mapped_water_area_m2 = max(0.0, gross_area_m2 - land_area_m2)
    footprint_area = sum(row["area_m2"] for row in buildings)
    known = [row for row in buildings if row.get("levels") is not None]
    known_floor_area = sum(row["area_m2"] * float(row["levels"]) for row in known)
    known_footprint = sum(row["area_m2"] for row in known)
    gsi = footprint_area / land_area_m2 if land_area_m2 else None
    fsi = known_floor_area / land_area_m2 if land_area_m2 and known else None
    osr = (1.0 - gsi) / fsi if fsi and fsi > 0 else None
    gross_gsi = footprint_area / gross_area_m2 if gross_area_m2 else None
    gross_fsi = known_floor_area / gross_area_m2 if gross_area_m2 and known else None
    masses = merge_touching_buildings(buildings)
    principal_buildings = [row for row in buildings if not _is_accessory_building(row)]
    principal_masses = merge_touching_buildings(principal_buildings)
    wings = [_area_perimeter_depth(mass) for mass in principal_masses]
    wing_crosschecks = [_building_depth(mass) for mass in principal_masses]
    valid_wings = [value for value in wings if value is not None]
    small_masses = [mass for mass in principal_masses if mass["geometry"].area < 100.0]
    water_union = unary_union(water_geoms) if water_geoms else None
    water_distance = [row["geometry"].distance(water_union) for row in buildings] if water_union and buildings else []
    blocks = _block_stats(land_area, area_metric, road_lines, principal_masses)
    street_widths = _street_width_samples(principal_buildings, road_lines)
    height_coverage = len(known) / len(buildings) if buildings else None
    if not known:
        fsi_status = "NOT_AVAILABLE"
    elif height_coverage is not None and height_coverage >= 0.80:
        fsi_status = "COMPARABLE"
    else:
        fsi_status = "LOWER_BOUND_NONCOMPARABLE"
    if len(buildings) < 5:
        spatial_coverage_status = "SPARSE_NOT_REPRESENTATIVE"
    else:
        spatial_coverage_status = "OSM_OBSERVED_COVERAGE"
    unclassified_share = blocks["unclassified_share"]
    if blocks["typology_sample_count"] == 0:
        typology_quality_note = "未取得完整窗內街廓，分類樣本為 0；不以截邊街廓估算未分類比例。"
    elif unclassified_share is not None and unclassified_share > 0.25:
        typology_quality_note = (
            "未分類比例高於 25%；本輪不強迫歸類。原因可能包括混合街廓、研究窗切邊、"
            "足跡未形成可辨識連通群，或已知樓層不足以支持連棟判型。輔助建物不列入翼深和類型樣本。"
        )
    else:
        typology_quality_note = "未分類比例未超過 25%；判型仍是基於完整街廓內主要建築足跡連通、閉合孔洞、長寬比與樓層覆蓋的自動代理。"
    return {
        "method_version": "kb4-morphometrics-v3-corrected",
        "calculated_at_utc": utc_now(),
        "snapshot_date": snapshot_date,
        "metric_projection": METRIC_METHOD,
        "study_area_gross_m2": rounded(gross_area_m2, 2),
        "study_area_gross_ha": rounded(gross_area_m2 / 10_000, 4),
        "mapped_water_area_m2": rounded(mapped_water_area_m2, 2),
        "land_area_m2": rounded(land_area_m2, 2),
        "study_area_ha": rounded(land_area_m2 / 10_000, 4),
        "land_denominator_definition": "研究窗扣除 OSM 中可解析的水域多邊形；線狀岸線／水道不推估寬度，未映射水域仍是資料限制。",
        "building_count": len(buildings),
        "building_mass_count_after_merge_0_5m": len(masses),
        "principal_building_count_for_form": len(principal_buildings),
        "principal_mass_count_after_merge_0_5m": len(principal_masses),
        "accessory_building_count_excluded_from_form_metrics": len(buildings) - len(principal_buildings),
        "building_footprint_area_m2": rounded(footprint_area, 2),
        "GSI": rounded(gsi, 4),
        "GSI_gross_water_inclusive": rounded(gross_gsi, 4),
        "FSI_known_floor_area_lower_bound": rounded(fsi, 4),
        "FSI_gross_water_inclusive_lower_bound": rounded(gross_fsi, 4),
        "FSI_comparability_status": fsi_status,
        "comparison_eligible": fsi_status == "COMPARABLE" and spatial_coverage_status != "SPARSE_NOT_REPRESENTATIVE",
        "L_area_weighted_known_building_floors": rounded(known_floor_area / known_footprint if known_footprint > 0 else None),
        "OSR_from_measured_GSI_and_known_FSI": rounded(osr, 4),
        "gross_floor_area_known_m2": rounded(known_floor_area, 2),
        "height_source": height_source,
        "height_observed_building_count": len(known),
        "height_missing_building_count": len(buildings) - len(known),
        "height_coverage_ratio": rounded(height_coverage, 4),
        "height_missing_ratio": rounded(1.0 - height_coverage, 4) if height_coverage is not None else None,
        "floor_conversion_assumption_m": FLOOR_TO_FLOOR_M,
        "floor_conversion_note": "OSM building:levels 直接用於 L；3DBAG roof-ground height 或 OSM height 僅在沒有樓層標記時以 3.0 m/層換算，為明示假設。缺值不補猜。",
        "block_count": blocks["count"],
        "complete_block_count": blocks["complete_count"],
        "block_area_m2": blocks["area_m2"],
        "block_area_m2_all_observed": blocks["area_m2_all_observed"],
        "block_edge_length_m": blocks["edge_length_m"],
        "block_type_mix": blocks["types"],
        "boundary_clipped_block_count": blocks["boundary_clipped_count"],
        "small_block_fragment_count_excluded_under_1000m2": blocks["small_fragment_count"],
        "small_block_fragment_total_area_excluded_m2": blocks["small_fragment_area_m2"],
        "unclassified_block_share": blocks["unclassified_share"],
        "typology_sample_count": blocks["typology_sample_count"],
        "typology_quality_note": typology_quality_note,
        "block_boundary_note": blocks["boundary_note"],
        "street_width_building_gap_m": distribution(street_widths),
        "street_width_definition": "主要建築外牆最近點間距；棚屋、車庫等明示輔助建物不列入；只保留最近點連線穿越主要車行／主街道中心線緩衝者，包含退縮，不等同法定車道淨寬。",
        "building_wing_depth_proxy_m": distribution(value for value in wings if value is not None),
        "building_wing_depth_crosscheck_minimum_rotated_rectangle_short_side_m": distribution(value for value in wing_crosschecks if value is not None),
        "building_wing_depth_proxy_under_4m_sample_count": sum(value < 4.0 for value in valid_wings),
        "building_wing_depth_proxy_under_4m_sample_share": rounded(sum(value < 4.0 for value in valid_wings) / len(valid_wings) if valid_wings else None, 4),
        "principal_mass_under_100m2_sample_count": len(small_masses),
        "principal_mass_under_100m2_sample_share": rounded(len(small_masses) / len(principal_masses) if principal_masses else None, 4),
        "building_wing_depth_definition": "先排除明示的輔助建物標籤，再將主要建築足跡依相距不超過 0.5 m 合併；翼深主代理為 2×合併面積÷周長，最小旋轉外接矩形短邊作交叉檢查。兩者皆非室內淨深。",
        "building_to_mapped_water_distance_m": distribution(water_distance),
        "mapped_water_polygon_count": len(list(_as_polygons(unary_union(water_area_geoms)))) if water_area_geoms else 0,
        "spatial_coverage_status": spatial_coverage_status,
        "block_edge_road_classes": sorted(BLOCK_EDGE_HIGHWAYS - {"pedestrian"}) + ["pedestrian（只納入非面狀且有名稱或編號的主街）"],
        "water_access": _water_access_class(elements, project, area_metric, water_geoms) if water_geoms else {
            "status": "NO_MAPPED_WATER_GEOMETRY",
            "nearby_mapped_route_count": 0,
            "routes_with_explicit_open_access_tags": 0,
            "routes_with_explicit_restriction_tags": 0,
            "routes_with_ambiguous_access": 0,
            "interpretation_limit": "此研究窗未取得 OSM 水體／岸線幾何；水岸公共性未取得。",
        },
        "building_typology_rules": {
            "周邊式": "合併量體形成封閉中庭，且量體距街廓外緣 4 m 內的界面涵蓋街廓周長至少 65%。",
            "合院": "單一合併量體含面積至少 50 m² 的閉合中庭，但未達周邊式的街廓環繞條件。",
            "連棟": "相距 ≤0.5 m 合併後的量體含至少 3 個原始足跡；各單元面積 ≤260 m²、短邊 ≤16 m，且可用高度資料均顯示不超過 4 層。",
            "板樓": "合併量體最小旋轉外接矩形長短邊比 >3.0；街廓中此類量體足跡占比至少 50%。",
            "點式": "合併量體最小旋轉外接矩形長短邊比 <1.6 且足跡面積 <1,200 m²；街廓中此類量體足跡占比至少 50%。",
            "分類次序": "周邊式 → 合院 → 連棟 → 板樓 → 點式 → 混合／未分類；只用完整窗內街廓和排除輔助建物後的主要建築量體；僅為幾何規則，不是人工校正真值。",
        },
    }


def source_record_path_for(slug: str) -> Path:
    overrides_path = ARTIFACTS / "source-overrides.json"
    if overrides_path.is_file():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8")).get("cases", {})
        if slug in overrides:
            return ROOT / overrides[slug]["source_record_path"]
    return ARTIFACTS / f"osm-source-record-{slug}.json"


def load_case(slug: str, areas_path: Path = ARTIFACTS / "study-areas.json") -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], Path, Path]:
    areas_payload = json.loads(areas_path.read_text(encoding="utf-8"))
    area = next((row for row in areas_payload["cases"] if row["slug"] == slug), None)
    if area is None:
        raise ValueError(f"no study area for {slug}")
    source_path = source_record_path_for(slug)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    raw_path = ROOT / source.get("response_path", source.get("source_response_path", ""))
    if not raw_path.is_file():
        raise FileNotFoundError(f"OSM snapshot missing for {slug}: {raw_path}")
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    if payload.get("remark"):
        raise ValueError(f"OSM source response is incomplete for {slug}")
    if source.get("status", "").startswith("INCOMPLETE"):
        raise ValueError(f"OSM source record is incomplete for {slug}")
    return area, source, payload.get("elements", []), raw_path, source_path


def prepare_case(slug: str, areas_path: Path = ARTIFACTS / "study-areas.json", bag_index: dict[str, float] | None = None, bag_source: dict[str, Any] | None = None) -> dict[str, Any]:
    area, source, elements, raw_path, source_path = load_case(slug, areas_path)
    anchor = area["anchor"]
    project = project_function(float(anchor["lon"]), float(anchor["lat"]))
    area_wgs = shape(area["geometry_wgs84"])
    area_metric = transform(project, area_wgs)
    if not area_metric.is_valid or area_metric.area <= 0:
        raise ValueError(f"invalid metric study polygon for {slug}")
    bag_index = bag_index or {}
    dutch = area["country"] == "Netherlands"
    all_roads: list[LineString] = []
    block_roads: list[LineString] = []
    water: list[Any] = []
    water_area_geoms: list[Any] = []
    for element in elements:
        tags = element.get("tags", {})
        if "highway" in tags and "building" not in tags:
            raw_geom = element_geometry(element, polygon=False)
            if raw_geom is not None:
                clipped_roads = [line for line in _as_lines(transform(project, raw_geom).intersection(area_metric)) if line.length > 1]
                all_roads.extend(clipped_roads)
                if _is_block_edge_road(tags):
                    block_roads.extend(clipped_roads)
        is_mapped_water = (
            tags.get("natural") in ("water", "coastline")
            or bool(tags.get("waterway"))
            or bool(tags.get("water"))
            or tags.get("landuse") == "reservoir"
        )
        if is_mapped_water:
            raw_geom = element_geometry(element, polygon=True)
            if raw_geom is not None:
                metric = transform(project, raw_geom).intersection(area_metric.buffer(100))
                if not metric.is_empty:
                    water.append(metric)
                    water_area_geoms.extend(part.intersection(area_metric) for part in _as_polygons(metric) if part.area > 1.0)
            line_geom = element_geometry(element, polygon=False)
            if line_geom is not None:
                metric_line = transform(project, line_geom).intersection(area_metric.buffer(100))
                if not metric_line.is_empty:
                    water.extend(_as_lines(metric_line))
    water_area_union = unary_union(water_area_geoms) if water_area_geoms else GeometryCollection()
    # Relations and member ways can describe the same water surface. Keep the
    # denominator union exact and report disjoint polygon parts, not duplicate
    # OSM feature counts.
    water_area_geoms = list(_as_polygons(water_area_union))
    land_area = area_metric.difference(water_area_union)
    if not land_area.is_valid:
        land_area = land_area.buffer(0)
    buildings = _unique_buildings(elements, land_area, project, bag_index, dutch)
    snapshot_date = source.get("osm_base_timestamp") or source.get("source_request_at_utc") or source.get("retrieved_at_utc") or "UNKNOWN"
    height_source = "3DBAG observed BAG-id join; no OSM fallback" if dutch else "OSM building:levels, then tagged height / 3.0 m-floor conversion"
    metrics = calculate_metrics(
        area_metric, buildings, block_roads, water, elements, project,
        height_source=height_source, snapshot_date=snapshot_date,
        land_area=land_area, water_area_geoms=water_area_geoms,
    )
    principal_buildings = [row for row in buildings if not _is_accessory_building(row)]
    masses = merge_touching_buildings(principal_buildings)
    block_result = _block_stats(land_area, area_metric, block_roads, masses)
    return {
        "slug": slug,
        "title_zh": area["title_zh"],
        "title_en": area["title_en"],
        "city": area["city"],
        "country": area["country"],
        "research_boundary": {
            "selection_method": area.get("boundary_note_zh"),
            "area_ha": area.get("area_ha"),
            "crs": area.get("crs"),
            "anchor_osm_objects": area.get("anchor", {}).get("osm_objects", []),
            "geometry_sha256": hashlib.sha256(json.dumps(area["geometry_wgs84"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        },
        "source": {
            "osm_raw_path": str(raw_path.relative_to(ROOT)),
            "osm_sha256": sha256(raw_path),
            "source_record_path": str(source_path.relative_to(ROOT)),
            "source_record_sha256": sha256(source_path),
            "osm_license": source.get("license", "Open Database License 1.0; © OpenStreetMap contributors"),
            "osm_base_timestamp": source.get("osm_base_timestamp") or source.get("source_request_at_utc") or source.get("retrieved_at_utc"),
            "osm_retrieved_at_utc": source.get("retrieved_at_utc") or source.get("source_request_at_utc"),
            "osm_element_count": len(elements),
            "osm_status": source.get("status"),
            "3dbag": bag_source if dutch else None,
        },
        "metrics": metrics,
        "_geometry": {
            "area": area_metric, "land_area": land_area, "buildings": buildings,
            "masses": masses, "roads": all_roads, "block_roads": block_roads,
            "water": water, "water_area": water_area_geoms, "blocks": block_result["geometries"],
        },
    }


def _svg_polygon(poly: Polygon, bounds: tuple[float, float, float, float], *, scale: float, left: float, top: float, height_mm: float, fill: str, stroke: str = "none", stroke_width: float = 0.4) -> str:
    minx, _, maxx, maxy = bounds
    paths = []
    for item in _as_polygons(poly):
        coords = list(item.exterior.coords)
        points = [f"{left + (x-minx)*scale:.3f},{top + (maxy-y)*scale:.3f}" for x, y in coords]
        paths.append(f'<polygon points="{" ".join(points)}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>')
    return "".join(paths)


def _svg_line(line: LineString, bounds: tuple[float, float, float, float], *, scale: float, left: float, top: float, height_mm: float, stroke: str, stroke_width: float, dash: str = "") -> str:
    minx, _, _, maxy = bounds
    points = [f"{left + (x-minx)*scale:.3f},{top + (maxy-y)*scale:.3f}" for x, y in line.coords]
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<polyline points="{" ".join(points)}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}"{extra}/>'


def _case_svg(case: dict[str, Any], *, width_mm: float = 132.0, height_mm: float = 128.0, panel: bool = False) -> str:
    geom = case["_geometry"]
    area = geom["area"]
    minx, miny, maxx, maxy = area.bounds
    scale = 0.2  # 1 m on the ground = 0.2 mm on the page (1:5000)
    map_left, map_top = 8.0, 21.0
    map_height = height_mm - 28.0
    max_map_width = width_mm - 16.0
    drawn_width = (maxx - minx) * scale
    drawn_height = (maxy - miny) * scale
    if drawn_width > max_map_width or drawn_height > map_height:
        scale = min(max_map_width / (maxx - minx), map_height / (maxy - miny), 0.2)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="{height_mm}mm" viewBox="0 0 {width_mm} {height_mm}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width_mm/2}" y="8" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="3.5" fill="#10212b">{escape(case["title_zh"])}｜圖底關係</text>',
        f'<text x="{width_mm/2}" y="13" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.5" fill="#52646c">研究窗 {case["research_boundary"]["area_ha"]:.2f} 公頃 · OSM 建築標記 {case["metrics"]["building_count"]} 棟 · 比例尺 1:5000</text>']
    if case["metrics"].get("spatial_coverage_status") == "SPARSE_NOT_REPRESENTATIVE":
        parts.append(f'<text x="{width_mm/2}" y="17.5" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.2" fill="#9a342a">建築樣本過少；此圖不代表完整現況</text>')
    for water in geom["water"]:
        parts.append(_svg_polygon(water, area.bounds, scale=scale, left=map_left, top=map_top, height_mm=height_mm, fill="#cde8ef", stroke="#74aab8", stroke_width=0.35))
        for line in _as_lines(water):
            parts.append(_svg_line(line, area.bounds, scale=scale, left=map_left, top=map_top, height_mm=height_mm, stroke="#74aab8", stroke_width=0.45))
    for road in geom["roads"]:
        for line in _as_lines(road):
            parts.append(_svg_line(line, area.bounds, scale=scale, left=map_left, top=map_top, height_mm=height_mm, stroke="#c5cbd0", stroke_width=0.5))
    for building in geom["buildings"]:
        for polygon in _as_polygons(building["geometry"]):
            parts.append(_svg_polygon(polygon, area.bounds, scale=scale, left=map_left, top=map_top, height_mm=height_mm, fill="#222b31"))
    boundary = LineString(list(area.exterior.coords))
    parts.append(_svg_line(boundary, area.bounds, scale=scale, left=map_left, top=map_top, height_mm=height_mm, stroke="#c24136", stroke_width=0.45, dash="1.4,0.8"))
    # A 100 m scale bar uses the same physical length in every panel.
    bar_x = 8.0
    bar_y = height_mm - 8.0
    bar_length = 100.0 * scale
    parts.extend([
        f'<line x1="{bar_x}" y1="{bar_y}" x2="{bar_x+bar_length}" y2="{bar_y}" stroke="#101820" stroke-width="0.8"/>',
        f'<line x1="{bar_x}" y1="{bar_y-1}" x2="{bar_x}" y2="{bar_y+1}" stroke="#101820" stroke-width="0.6"/>',
        f'<line x1="{bar_x+bar_length}" y1="{bar_y-1}" x2="{bar_x+bar_length}" y2="{bar_y+1}" stroke="#101820" stroke-width="0.6"/>',
        f'<text x="{bar_x}" y="{bar_y-1.7}" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.3" fill="#101820">0</text>',
        f'<text x="{bar_x+bar_length}" y="{bar_y-1.7}" text-anchor="end" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.3" fill="#101820">100 公尺</text>',
        f'<rect x="{width_mm-49}" y="{height_mm-13}" width="3" height="2" fill="#222b31"/><text x="{width_mm-44}" y="{height_mm-11.4}" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.1">建築</text>',
        f'<line x1="{width_mm-38}" y1="{height_mm-12}" x2="{width_mm-34}" y2="{height_mm-12}" stroke="#c5cbd0" stroke-width="0.7"/><text x="{width_mm-32}" y="{height_mm-11.4}" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.1">道路</text>',
        f'<rect x="{width_mm-25}" y="{height_mm-13}" width="3" height="2" fill="#cde8ef" stroke="#74aab8" stroke-width="0.3"/><text x="{width_mm-20}" y="{height_mm-11.4}" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.1">水體</text>',
        f'<text x="{width_mm-2}" y="{height_mm-11.4}" text-anchor="end" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.1" fill="#c24136">虛線：研究範圍</text>',
        '</svg>'
    ])
    return "".join(parts)


def _missing_svg(area_row: dict[str, Any], *, width_mm: float = 132.0, height_mm: float = 128.0) -> str:
    anchor = area_row["anchor"]
    project = project_function(float(anchor["lon"]), float(anchor["lat"]))
    area = transform(project, shape(area_row["geometry_wgs84"]))
    scale = 0.2
    left, top = 8.0, 21.0
    boundary = _svg_line(LineString(list(area.exterior.coords)), area.bounds, scale=scale, left=left,
                         top=top, height_mm=height_mm, stroke="#c24136", stroke_width=0.45, dash="1.4,0.8")
    bar_x, bar_y, bar_length = 8.0, height_mm - 8.0, 20.0
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" height="{height_mm}mm" viewBox="0 0 {width_mm} {height_mm}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width_mm/2}" y="8" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="3.5" fill="#10212b">{escape(area_row["title_zh"])}｜幾何未取得</text>',
        f'<text x="{width_mm/2}" y="13" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.5" fill="#52646c">研究窗 {area_row["area_ha"]:.2f} 公頃 · 比例尺 1:5000</text>',
        boundary,
        f'<text x="{width_mm/2}" y="{height_mm/2}" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="3.2" fill="#9a342a">未取得完整 OSM 幾何；此空白不代表基地沒有建築</text>',
        f'<line x1="{bar_x}" y1="{bar_y}" x2="{bar_x+bar_length}" y2="{bar_y}" stroke="#101820" stroke-width="0.8"/>',
        f'<text x="{bar_x}" y="{bar_y-1.7}" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.3" fill="#101820">0</text>',
        f'<text x="{bar_x+bar_length}" y="{bar_y-1.7}" text-anchor="end" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.3" fill="#101820">100 公尺</text>',
        f'<text x="{width_mm-2}" y="{height_mm-11.4}" text-anchor="end" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.1" fill="#c24136">虛線：研究範圍</text>',
        '</svg>',
    ]
    return "".join(out)


def _comparison_svg(cases: list[dict[str, Any]], areas: list[dict[str, Any]]) -> str:
    measured = {case["slug"]: case for case in cases}
    columns, rows = 4, math.ceil(len(areas) / 4)
    cell_w, cell_h = 132.0, 128.0
    width, height = columns * cell_w, rows * cell_h + 16
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#f5f7f7"/>',
           f'<text x="{width/2}" y="8" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="4" fill="#10212b">形態先例並列比較｜相同比例尺 1:5000</text>']
    for index, area in enumerate(areas):
        col, row = index % columns, index // columns
        case = measured.get(area["slug"])
        raw = _case_svg(case, width_mm=cell_w, height_mm=cell_h) if case else _missing_svg(area, width_mm=cell_w, height_mm=cell_h)
        inner = raw.split(">", 1)[1].rsplit("</svg>", 1)[0]
        out.append(f'<g transform="translate({col*cell_w},{16+row*cell_h})">{inner}</g>')
    out.append('</svg>')
    return "".join(out)


def _spacematrix_svg(cases: list[dict[str, Any]]) -> str:
    width, height = 190.0, 145.0
    left, right, top, bottom = 25.0, 10.0, 18.0, 24.0
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = [case["metrics"]["FSI_known_floor_area_lower_bound"] for case in cases if case["metrics"]["FSI_known_floor_area_lower_bound"] is not None]
    ys = [case["metrics"]["GSI"] for case in cases if case["metrics"]["GSI"] is not None]
    xmax = max(xs, default=1.0) * 1.12 or 1.0
    ymax = max(ys, default=1.0) * 1.12 or 1.0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#fff"/>',
           f'<text x="{width/2}" y="8" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="4" fill="#10212b">先例 Spacematrix 散布圖｜FSI × GSI</text>']
    for i in range(6):
        x = left + i * plot_w / 5
        y = top + plot_h - i * plot_h / 5
        out.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top+plot_h}" stroke="#e2e7e9" stroke-width="0.25"/>')
        out.append(f'<line x1="{left}" y1="{y}" x2="{left+plot_w}" y2="{y}" stroke="#e2e7e9" stroke-width="0.25"/>')
        out.append(f'<text x="{x}" y="{top+plot_h+4}" text-anchor="middle" font-family="sans-serif" font-size="2.5">{xmax*i/5:.2f}</text>')
        out.append(f'<text x="{left-2}" y="{y+0.8}" text-anchor="end" font-family="sans-serif" font-size="2.5">{ymax*i/5:.2f}</text>')
    out.extend([
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#24333b" stroke-width="0.5"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#24333b" stroke-width="0.5"/>',
        f'<text x="{left+plot_w/2}" y="{height-4}" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="3">FSI 樓地板面積比（已知樓層下限）</text>',
        f'<text x="6" y="{top+plot_h/2}" transform="rotate(-90 6 {top+plot_h/2})" text-anchor="middle" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="3">GSI 建築覆蓋率</text>'
    ])
    for index, case in enumerate(cases):
        fsi, gsi = case["metrics"]["FSI_known_floor_area_lower_bound"], case["metrics"]["GSI"]
        if fsi is None or gsi is None:
            continue
        x = left + fsi / xmax * plot_w
        y = top + plot_h - gsi / ymax * plot_h
        color = "#1a7185" if case["country"] == "Netherlands" else "#ad5735"
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.5" fill="{color}" stroke="#fff" stroke-width="0.35"/>')
        label = escape(case["title_zh"])
        dx = 2.0 if index % 2 == 0 else -2.0
        anchor = "start" if dx > 0 else "end"
        dy = -1.3 if index % 3 else 3.2
        out.append(f'<text x="{x+dx:.2f}" y="{y+dy:.2f}" text-anchor="{anchor}" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.3" fill="#24333b">{label}</text>')
    out.extend([
        f'<text x="{left}" y="{height-12}" font-family="PingFang TC,Noto Sans CJK TC,sans-serif" font-size="2.2" fill="#7a4b2e">荷蘭外先例使用 OSM 樓層標籤；荷蘭先例使用 3DBAG 可連結建築。缺漏樓層未補值。</text>',
        '</svg>'
    ])
    return "".join(out)


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items() if not key.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size)


def _pixel_xy(x: float, y: float, bounds: tuple[float, float, float, float], center: tuple[float, float], scale: float) -> tuple[float, float]:
    center_x, center_y = center
    minx, _, _, maxy = bounds
    return center_x + (x - (minx + maxx_from_bounds(bounds)) / 2.0) * scale, center_y - (y - (miny_from_bounds(bounds) + maxy) / 2.0) * scale


def minx_from_bounds(bounds: tuple[float, float, float, float]) -> float:
    return bounds[0]


def maxx_from_bounds(bounds: tuple[float, float, float, float]) -> float:
    return bounds[2]


def miny_from_bounds(bounds: tuple[float, float, float, float]) -> float:
    return bounds[1]


def _draw_polygon_geometry(draw: ImageDraw.ImageDraw, geometry, bounds, center, scale, *, fill, outline=None, width=1, hole_fill="#F3EBDD") -> None:
    for polygon in _as_polygons(geometry):
        exterior = [_pixel_xy(x, y, bounds, center, scale) for x, y in polygon.exterior.coords]
        if len(exterior) >= 3:
            draw.polygon(exterior, fill=fill, outline=outline)
            if outline and width > 1:
                draw.line(exterior, fill=outline, width=width, joint="curve")
        for ring in polygon.interiors:
            interior = [_pixel_xy(x, y, bounds, center, scale) for x, y in ring.coords]
            if len(interior) >= 3:
                draw.polygon(interior, fill=hole_fill)


def _draw_line_geometry(draw: ImageDraw.ImageDraw, geometry, bounds, center, scale, *, fill, width=1, dash: bool = False) -> None:
    for line in _as_lines(geometry):
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        pixels = [_pixel_xy(x, y, bounds, center, scale) for x, y in coords]
        if not dash:
            draw.line(pixels, fill=fill, width=width, joint="curve")
            continue
        for start, end in zip(pixels, pixels[1:]):
            length = math.dist(start, end)
            if length <= 0:
                continue
            ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
            cursor = 0.0
            while cursor < length:
                stop = min(cursor + 7.0, length)
                if int(cursor / 11.0) % 2 == 0:
                    draw.line([(start[0] + ux * cursor, start[1] + uy * cursor),
                               (start[0] + ux * stop, start[1] + uy * stop)], fill=fill, width=width)
                cursor += 11.0


def _map_scale_px_per_m() -> float:
    return FIGURE_DPI / 25.4 * 1000.0 / FIGURE_SCALE_DENOMINATOR


def _draw_map_layers(image: Image.Image, case: dict[str, Any] | None, area_metric, bounds, panel_box, *, label_missing: bool = False) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = panel_box
    scale = _map_scale_px_per_m()
    width_m, height_m = bounds[2] - bounds[0], bounds[3] - bounds[1]
    center = ((left + right) / 2.0, (top + bottom) / 2.0)
    map_width_px, map_height_px = width_m * scale, height_m * scale
    if map_width_px > (right - left) + 1 or map_height_px > (bottom - top) + 1:
        raise ValueError("fixed 1:5000 map window exceeds its drawing panel")
    draw.rectangle([left, top, right, bottom], fill="#F3EBDD", outline="#9B8F80", width=1)
    if case is not None:
        geom = case["_geometry"]
        for water in geom["water_area"]:
            clipped = water.intersection(area_metric)
            _draw_polygon_geometry(draw, clipped, bounds, center, scale, fill="#B8D6E5", outline="#6D9EB2", width=1, hole_fill="#F3EBDD")
        for water in geom["water"]:
            clipped = water.intersection(area_metric)
            _draw_line_geometry(draw, clipped, bounds, center, scale, fill="#6D9EB2", width=2)
        for road in geom["roads"]:
            clipped = road.intersection(area_metric)
            _draw_line_geometry(draw, clipped, bounds, center, scale, fill="#C6C6C1", width=1)
        for road in geom["block_roads"]:
            clipped = road.intersection(area_metric)
            _draw_line_geometry(draw, clipped, bounds, center, scale, fill="#C28B43", width=2)
        for block in geom["blocks"]:
            clipped = block.intersection(area_metric)
            _draw_polygon_geometry(draw, clipped, bounds, center, scale, fill=None, outline="#C5483A", width=2, hole_fill="#F3EBDD")
        for mass in geom["masses"]:
            clipped = mass["geometry"].intersection(area_metric)
            _draw_polygon_geometry(draw, clipped, bounds, center, scale, fill="#283139", outline="#15191D", width=1, hole_fill="#F3EBDD")
        _draw_line_geometry(draw, LineString(list(area_metric.exterior.coords)), bounds, center, scale, fill="#B43B32", width=2, dash=True)
    else:
        _draw_line_geometry(draw, LineString(list(area_metric.exterior.coords)), bounds, center, scale, fill="#B43B32", width=2, dash=True)
    if label_missing:
        text = "OSM 幾何未取得；空白不代表無建築"
        font = _font(16)
        bbox = draw.textbbox((0, 0), text, font=font)
        x = center[0] - (bbox[2] - bbox[0]) / 2
        y = center[1] - (bbox[3] - bbox[1]) / 2
        draw.rounded_rectangle([x - 8, y - 6, x + bbox[2] - bbox[0] + 8, y + bbox[3] - bbox[1] + 6], radius=6, fill="#FFF8F3", outline="#B43B32", width=2)
        draw.text((x, y), text, font=font, fill="#8E302A")


def _draw_chinese_legend(draw: ImageDraw.ImageDraw, y: int, *, compact: bool = False) -> None:
    font = _font(13 if compact else 15)
    x = 24
    entries = [
        ("mass", "合併建築量體"), ("road", "主要街道"), ("block", "街廓邊界"),
        ("water", "已映射水域"), ("boundary", "研究窗"),
    ]
    for kind, label in entries:
        if kind == "mass":
            draw.rectangle([x, y + 2, x + 18, y + 15], fill="#283139", outline="#15191D")
        elif kind == "road":
            draw.line([x, y + 9, x + 20, y + 9], fill="#C28B43", width=3)
        elif kind == "block":
            draw.rectangle([x, y + 2, x + 18, y + 15], outline="#C5483A", width=2)
        elif kind == "water":
            draw.rectangle([x, y + 2, x + 18, y + 15], fill="#B8D6E5", outline="#6D9EB2")
        else:
            draw.line([x, y + 9, x + 20, y + 9], fill="#B43B32", width=2)
        draw.text((x + 24, y), label, font=font, fill="#26343A")
        x += 132 if compact else 150


def _draw_scale_bar(draw: ImageDraw.ImageDraw, y: int, x: int = 26) -> None:
    font = _font(14)
    length = 100.0 * _map_scale_px_per_m()
    draw.line([x, y, x + length, y], fill="#18242A", width=4)
    draw.line([x, y - 7, x, y + 7], fill="#18242A", width=2)
    draw.line([x + length, y - 7, x + length, y + 7], fill="#18242A", width=2)
    draw.text((x, y - 24), "0", font=font, fill="#18242A")
    draw.text((x + length - 55, y - 24), "100 公尺", font=font, fill="#18242A")


def _case_window_metric(area_row: dict[str, Any]):
    anchor = area_row["anchor"]
    project = project_function(float(anchor["lon"]), float(anchor["lat"]))
    return transform(project, shape(area_row["geometry_wgs84"]))


def _write_case_png(path: Path, area_row: dict[str, Any], case: dict[str, Any] | None) -> None:
    image = Image.new("RGB", (680, 600), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title_font, subtitle_font = _font(23), _font(15)
    title = f"{area_row['title_zh']}｜圖底關係"
    draw.text((340, 12), title, font=title_font, fill="#16242B", anchor="mt")
    status = "OSM／3DBAG 實測" if case else "NOT_ACQUIRED｜未取得完整 OSM 回應"
    city_zh = CITY_NAMES_ZH.get(area_row["city"], "研究地點未確認")
    subtitle = f"{city_zh}；研究窗 {area_row['area_ha']:.2f} 公頃；比例尺 1:5,000；{status}"
    draw.text((340, 46), subtitle, font=subtitle_font, fill="#52636B", anchor="mt")
    area_metric = case["_geometry"]["area"] if case else _case_window_metric(area_row)
    _draw_map_layers(image, case, area_metric, area_metric.bounds, (18, 72, 662, 492), label_missing=case is None)
    _draw_chinese_legend(draw, 514, compact=True)
    _draw_scale_bar(draw, 574)
    draw.text((658, 560), "北 ↑", font=subtitle_font, fill="#26343A", anchor="ra")
    image.save(path, format="PNG", dpi=(FIGURE_DPI, FIGURE_DPI), optimize=True)


def _write_comparison_png(path: Path, cases: list[dict[str, Any]], areas: list[dict[str, Any]]) -> None:
    columns, card_w, card_h, header_h = 4, 540, 430, 64
    rows = math.ceil(len(areas) / columns)
    image = Image.new("RGB", (columns * card_w, header_h + rows * card_h + 92), "#F3F5F5")
    draw = ImageDraw.Draw(image)
    draw.text((columns * card_w / 2, 10), "形態先例並列比較圖", font=_font(28), fill="#16242B", anchor="mt")
    draw.text((columns * card_w / 2, 45), "同一研究比例尺 1:5,000；研究窗不是官方開發邊界", font=_font(17), fill="#52636B", anchor="mt")
    measured = {case["slug"]: case for case in cases}
    for index, area_row in enumerate(areas):
        col, row = index % columns, index // columns
        card_x, card_y = col * card_w, header_h + row * card_h
        draw.rounded_rectangle([card_x + 5, card_y + 4, card_x + card_w - 5, card_y + card_h - 5], radius=5, fill="#FFFFFF", outline="#C5CCCF", width=1)
        draw.text((card_x + card_w / 2, card_y + 8), area_row["title_zh"], font=_font(18), fill="#26343A", anchor="mt")
        case = measured.get(area_row["slug"])
        area_metric = case["_geometry"]["area"] if case else _case_window_metric(area_row)
        _draw_map_layers(image, case, area_metric, area_metric.bounds,
                         (card_x + 30, card_y + 40, card_x + card_w - 30, card_y + 356),
                         label_missing=case is None)
    footer_y = header_h + rows * card_h + 11
    _draw_chinese_legend(draw, footer_y, compact=True)
    _draw_scale_bar(draw, footer_y + 48)
    image.save(path, format="PNG", dpi=(FIGURE_DPI, FIGURE_DPI), optimize=True)


def _write_spacematrix_png(path: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [case for case in cases if case["metrics"].get("comparison_eligible")]
    width, height = 1120, 820
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    draw.text((width / 2, 18), "Spacematrix 散布圖｜FSI 與 GSI", font=_font(28), fill="#16242B", anchor="mt")
    left, right, top, bottom = 150, 60, 95, 690
    plot_w, plot_h = width - left - right, bottom - top
    gsi_values = [float(case["metrics"]["GSI"]) for case in eligible]
    fsi_values = [float(case["metrics"]["FSI_known_floor_area_lower_bound"]) for case in eligible]
    xmax = max(0.7, math.ceil(max(gsi_values, default=0.6) * 10) / 10)
    ymax = max(4.0, math.ceil(max(fsi_values, default=3.0)))
    draw.rectangle([left, top, width - right, bottom], outline="#26343A", width=2)
    for index in range(6):
        x_value = xmax * index / 5
        x = left + x_value / xmax * plot_w
        draw.line([x, top, x, bottom], fill="#E4E8E9", width=1)
        draw.text((x, bottom + 10), f"{x_value:.1f}", font=_font(14), fill="#44545B", anchor="mt")
        y_value = ymax * index / 5
        y = bottom - y_value / ymax * plot_h
        draw.line([left, y, width - right, y], fill="#E4E8E9", width=1)
        draw.text((left - 12, y), f"{y_value:.1f}", font=_font(14), fill="#44545B", anchor="rm")
    draw.text((left + plot_w / 2, height - 56), "建築覆蓋率 GSI（陸地分母）", font=_font(19), fill="#26343A", anchor="mt")
    axis_label = "樓地板面積比 FSI（陸地分母）"
    bbox = draw.textbbox((0, 0), axis_label, font=_font(18))
    pad = 4
    label = Image.new("RGBA", (bbox[2] - bbox[0] + pad * 2, bbox[3] - bbox[1] + pad * 2), (255, 255, 255, 0))
    ImageDraw.Draw(label).text((pad - bbox[0], pad - bbox[1]), axis_label, font=_font(18), fill="#26343A")
    label = label.rotate(90, expand=True)
    image.paste(label, (28, int(top + plot_h / 2 - label.height / 2)), label)
    positions = []
    plotted = []
    for case in eligible:
        gsi = float(case["metrics"]["GSI"])
        fsi = float(case["metrics"]["FSI_known_floor_area_lower_bound"])
        x = left + gsi / xmax * plot_w
        y = bottom - fsi / ymax * plot_h
        color = "#19778A" if case["country"] == "Netherlands" else "#B55D32"
        plotted.append((case, x, y, color))
        positions.append({"slug": case["slug"], "x_gsi": gsi, "y_fsi": fsi})
    label_boxes: list[tuple[float, float, float, float]] = []
    for case, x, y, color in plotted:
        draw.ellipse([x - 7, y - 7, x + 7, y + 7], fill=color, outline="#FFFFFF", width=2)
    for case, x, y, _ in plotted:
        text, font = case["title_zh"], _font(14)
        bbox = draw.textbbox((0, 0), text, font=font)
        label_w, label_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        candidates = [
            (x + 13, y - label_h - 7), (x + 13, y + 7),
            (x - label_w - 13, y - label_h - 7), (x - label_w - 13, y + 7),
            (x - label_w / 2, y - label_h - 12), (x - label_w / 2, y + 12),
        ]
        marker_boxes = [(px - 10, py - 10, px + 10, py + 10) for _, px, py, _ in plotted if abs(px - x) > 0.1 or abs(py - y) > 0.1]
        selected = None
        for candidate_x, candidate_y in candidates:
            rect = (candidate_x - 3, candidate_y - 3, candidate_x + label_w + 3, candidate_y + label_h + 3)
            inside = rect[0] >= 90 and rect[1] >= top - 22 and rect[2] <= width - 8 and rect[3] <= bottom + 28
            overlaps_labels = any(not (rect[2] < other[0] or rect[0] > other[2] or rect[3] < other[1] or rect[1] > other[3]) for other in label_boxes)
            overlaps_markers = any(not (rect[2] < marker[0] or rect[0] > marker[2] or rect[3] < marker[1] or rect[1] > marker[3]) for marker in marker_boxes)
            if inside and not overlaps_labels and not overlaps_markers:
                selected = (candidate_x, candidate_y, rect)
                break
        if selected is None:
            candidate_x, candidate_y = candidates[0]
            selected = (candidate_x, candidate_y, (candidate_x - 3, candidate_y - 3, candidate_x + label_w + 3, candidate_y + label_h + 3))
        label_x, label_y, rect = selected
        draw.text((label_x - bbox[0], label_y - bbox[1]), text, font=font, fill="#26343A")
        label_boxes.append(rect)
    draw.ellipse([left + 5, height - 25, left + 17, height - 13], fill="#19778A")
    draw.text((left + 24, height - 28), "荷蘭", font=_font(14), fill="#26343A")
    draw.ellipse([left + 90, height - 25, left + 102, height - 13], fill="#B55D32")
    draw.text((left + 109, height - 28), "歐洲其他案例", font=_font(14), fill="#26343A")
    excluded = [case["slug"] for case in cases if case not in eligible]
    draw.text((width - right, height - 28), "高度缺值 >20% 或快照稀疏者不列入 FSI 比較", font=_font(14), fill="#7A3D33", anchor="ra")
    image.save(path, format="PNG", dpi=(FIGURE_DPI, FIGURE_DPI), optimize=True)
    return {"included": positions, "excluded_slugs": excluded, "x_axis": "GSI", "y_axis": "FSI", "scale_basis": "land area excluding mapped water", "y_axis_label_rotated": True}


def new_output_dir(requested: Path | None = None) -> Path:
    if requested is not None:
        resolved = requested.resolve()
        if not resolved.is_relative_to(ARTIFACTS.resolve()):
            raise ValueError("morphometry outputs must remain under artifacts/kb4-precedents")
        resolved.mkdir(parents=True, exist_ok=False)
        return resolved
    parent = ARTIFACTS / "runs"
    parent.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace("-", "").replace(":", "")
    path = parent / f"{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=False, exist_ok=False)
    return path


def build_all(output_dir: Path | None = None) -> dict[str, Any]:
    areas = json.loads((ARTIFACTS / "study-areas.json").read_text(encoding="utf-8"))["cases"]
    height_index, height_meta = load_3dbag_height_index(ARTIFACTS / "3dbag-source-manifest.json")
    bag_manifest_path = ARTIFACTS / "3dbag-source-manifest.json"
    bag_manifest = json.loads(bag_manifest_path.read_text(encoding="utf-8")) if bag_manifest_path.is_file() else {}
    cases: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for area in areas:
        slug = area["slug"]
        record_path = source_record_path_for(slug)
        if not record_path.is_file():
            failures.append({"slug": slug, "status": "NOT_ACQUIRED", "reason": "OSM source record and complete response are absent; no measurement made."})
            continue
        try:
            catalog = next((row for row in bag_manifest.get("tile_catalog_requests", []) if row.get("case_slug") == slug), None)
            case_tile_ids = set(catalog.get("matching_tile_ids", [])) if catalog else set()
            case_tiles = [row for row in bag_manifest.get("tiles", []) if row.get("tile_id") in case_tile_ids]
            case_bag_source = {
                "status": "OBSERVED" if case_tiles else ("INCOMPLETE" if catalog or bag_manifest else "NOT_ACQUIRED"),
                "endpoint": "https://data.3dbag.nl/api/BAG3D/wfs",
                "catalog_sha256": catalog.get("response_sha256") if catalog else None,
                "catalog_retrieved_at_utc": catalog.get("retrieved_at_utc") if catalog else None,
                "tiles": case_tiles,
                "limitations": "只有可連結的 BAG 識別碼才加入高度；缺少 3DBAG 高度不以 OSM 或幾何形狀補值。",
            }
            cases.append(prepare_case(slug, bag_index=height_index, bag_source=case_bag_source))
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            status = "NOT_ACQUIRED" if "source record is incomplete" in reason or "source response is incomplete" in reason else "MEASUREMENT_INCOMPLETE"
            failures.append({"slug": slug, "status": status, "reason": reason})
    retry_manifests = sorted(ARTIFACTS.glob("osm-bbox-chunk-retry-*.json"))
    retry_manifest_path = retry_manifests[-1] if retry_manifests else None
    retry_by_slug: dict[str, dict[str, Any]] = {}
    if retry_manifest_path is not None:
        retry_manifest = json.loads(retry_manifest_path.read_text(encoding="utf-8"))
        retry_by_slug = {row.get("case_slug"): row for row in retry_manifest.get("failures", [])}
    legacy_retry_path = ARTIFACTS / "osm-retry-failures.json"
    if legacy_retry_path.is_file():
        legacy = json.loads(legacy_retry_path.read_text(encoding="utf-8")).get("failures", [])
        retry_by_slug.update({row.get("case_slug"): row for row in legacy})
    for failure in failures:
        prior = retry_by_slug.get(failure["slug"])
        if prior:
            failure["attempt_count"] = prior.get("attempt_count")
            failure["http_statuses"] = prior.get("http_statuses", [])
            failure["last_error"] = prior.get("last_error")
            failure["retry_manifest_path"] = str(retry_manifest_path.relative_to(ROOT)) if retry_manifest_path else None
    output_dir = new_output_dir(output_dir)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    case_by_slug = {case["slug"]: case for case in cases}
    for area in areas:
        target = figures_dir / f"{area['slug']}-figure-ground.png"
        _write_case_png(target, area, case_by_slug.get(area["slug"]))
    comparison_path = figures_dir / "precedents-comparison.png"
    _write_comparison_png(comparison_path, cases, areas)
    spacematrix_path = figures_dir / "spacematrix-fsi-gsi.png"
    spacematrix_comparison = _write_spacematrix_png(spacematrix_path, cases)
    metrics_path = output_dir / "morphometrics-by-case.json"
    result = {
        "schema_version": "kb4-precedent-morphometrics-v3-corrected",
        "generated_at_utc": utc_now(),
        "script_sha256": sha256(Path(__file__)),
        "study_areas_path": str((ARTIFACTS / "study-areas.json").relative_to(ROOT)),
        "figure_scale_denominator": FIGURE_SCALE_DENOMINATOR,
        "acquisition_retry_manifest_path": str(retry_manifest_path.relative_to(ROOT)) if retry_manifest_path else None,
        "height_source": height_meta,
        "cases": [_json_ready(case) for case in cases],
        "unmeasured_cases": failures,
        "measurement_count": len(cases),
        "spacematrix_comparison": spacematrix_comparison,
        "measurement_limitations": [
            "Study windows are researcher-drawn metric rectangles around named OSM anchors and are not official development boundaries.",
            "OSM coverage is observational and may omit buildings, roads, water edges, heights, shoreline access, or edits.",
            "GSI and FSI use the study polygon minus mapped water polygons; line-only shore features are not assigned guessed widths.",
            "FSI and mean levels use only buildings with observed floor/height information; when height coverage is below 80 percent, FSI is a non-comparable lower bound and excluded from the scatter plot.",
            "Adjacent building footprints within 0.5 m are grouped into measured masses for wing-depth and typology checks; original footprints remain the GSI/FSI basis.",
            "Explicit accessory-building tags (shed, garage, carport, hut, kiosk, roof and service classes) are excluded from wing-depth, street-gap and typology samples but stay in the original GSI/FSI footprint basis.",
            "Street blocks are polygonized from primary, secondary, tertiary, residential, unclassified, living_street and named non-area pedestrian main streets; paths, cycleways and service roads are excluded, fragments below 1,000 m2 are reported and dropped.",
            "Block-area and typology statistics use only un-clipped blocks; street-edge lengths use noded major-road segments between junctions and exclude segments ending on the research-window boundary.",
            "Street width is a major-road-crossing building-gap proxy; edge clipping and automatic typology uncertainty are disclosed per case.",
            "Water access is inferred only from nearby OSM tags and is not a legal or ownership determination.",
        ],
        "outputs": [
            str(metrics_path.relative_to(ROOT)),
            *[str((figures_dir / f"{area['slug']}-figure-ground.png").relative_to(ROOT)) for area in areas],
            str(comparison_path.relative_to(ROOT)),
            str(spacematrix_path.relative_to(ROOT)),
        ],
    }
    with metrics_path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return {"status": "PASS" if cases and not failures else "INCOMPLETE", "measured_cases": len(cases), "unmeasured_cases": failures, "metrics_path": str(metrics_path.relative_to(ROOT)), "figure_count": len(areas) + 2, "comparison_eligible_count": len(spacematrix_comparison["included"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="A new, non-existent directory under artifacts/kb4-precedents.")
    parser.add_argument("--slug", help="Measure one case, leaving all other cases untouched.")
    parser.add_argument("--dry-run", action="store_true", help="Validate source availability and report cases without creating outputs.")
    args = parser.parse_args()
    if args.dry_run:
        areas = json.loads((ARTIFACTS / "study-areas.json").read_text(encoding="utf-8"))["cases"]
        available = [row["slug"] for row in areas if source_record_path_for(row["slug"]).is_file()]
        missing = [row["slug"] for row in areas if row["slug"] not in available]
        print(json.dumps({"source_available_count": len(available), "source_available": available, "source_missing_count": len(missing), "source_missing": missing}, ensure_ascii=False))
        return 0
    if args.slug:
        heights, _ = load_3dbag_height_index(ARTIFACTS / "3dbag-source-manifest.json")
        case = prepare_case(args.slug, bag_index=heights)
        payload = _json_ready(case)
        output_dir = new_output_dir(args.output_dir)
        output = output_dir / f"morphometrics-{args.slug}.json"
        with output.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"status": "PASS", "slug": args.slug, "output": str(output)}, ensure_ascii=False))
        return 0
    print(json.dumps(build_all(args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
