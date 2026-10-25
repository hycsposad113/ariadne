#!/usr/bin/env python3
"""E1 Fabric Sunlight Simulation (四個紋理方案開放空間日照時數分析).

Calculates direct sunlight duration for all unbuilt land (parks, waterfront, roads, courtyards, other block land, service yards)
across four urban fabric scenarios in Rotterdam M4H on Vernal Equinox, Summer Solstice,
and Winter Solstice using verified Radiance 6.0.2 via Ladybug Radiance.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from urban_design.environment.contracts import AnalysisPeriod, Obstacle, SensorPoint
from urban_design.environment.geometry_adapter import (
    _hash_faces,
    compute_grid_convergence_deg,
    footprint_to_obstacle,
)
from urban_design.environment.sensors import generate_ground_sensor_grid
from urban_design.environment.sunlight import (
    calculate_direct_sunlight_hours,
    get_rotterdam_m4h_demo_location,
    verify_radiance_runtime,
)

# --- Configuration & Constants ---
FABRICS = [
    "harbour_grain",
    "closed_block_extension",
    "courtyard_islands",
    "landscape_figure",
]

FABRIC_NAMES_ZH = {
    "harbour_grain": "港埠線性紋理",
    "closed_block_extension": "圍合街廓延伸",
    "courtyard_islands": "大型院落島",
    "landscape_figure": "地景為圖",
}

FABRIC_DESCRIPTIONS_ZH = {
    "harbour_grain": "Founder 選定方案；以長條街廓呼應碼頭作業軸線",
    "closed_block_extension": "延伸周邊既有圍合街廓網絡與內部街坊維護空間",
    "courtyard_islands": "大型院落島嶼街廓，內部形成大型共用開敞空間",
    "landscape_figure": "以連續綠地景為底圖，建物作為離散散點配置",
}

ANALYSIS_DATES = [
    date(2026, 3, 21),
    date(2026, 6, 21),
    date(2026, 12, 21),
]

DATE_LABELS_ZH = {
    "2026-03-21": "春分 (03/21)",
    "2026-06-21": "夏至 (06/21)",
    "2026-12-21": "冬至 (12/21)",
}

FABRIC_NAMES_EN = {
    "harbour_grain": "Harbour grain",
    "closed_block_extension": "Closed-block extension",
    "courtyard_islands": "Courtyard islands",
    "landscape_figure": "Landscape as figure",
}

DATE_LABELS_EN = {
    "2026-03-21": "Spring equinox 2026-03-21",
    "2026-06-21": "Summer solstice 2026-06-21",
    "2026-12-21": "Winter solstice 2026-12-21",
}

SPACE_CATEGORY_LABELS_EN = {
    "all": "All open space",
    "parks": "Parks and green corridors",
    "waterfront": "Waterfront public realm",
    "roads": "Streets and road right-of-way",
    "courtyards": "Block courtyards",
    "blocks": "Other block open land",
    "service": "Service yards and other open land",
}

DEFAULT_CONTEXT_BUILDINGS = Path.home() / ".local/share/urban-design-data/context/context-20260927T153054Z/buildings.geojson"
DEFAULT_CONTEXT_WATER = Path.home() / ".local/share/urban-design-data/context/context-20260927T153054Z/water.geojson"
DEFAULT_CONTEXT_ROADS = Path.home() / ".local/share/urban-design-data/context/context-20260927T153054Z/roads.geojson"

CONTEXT_BUFFER_M = 300.0
CONTEXT_ASSUMED_HEIGHT_M = 12.0  # Median of known context buildings is 11.5m; 12.0m is standard 4-storey Dutch block height

FONT_PATHS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def get_font_path() -> Optional[str]:
    for p in FONT_PATHS:
        if os.path.exists(p):
            return p
    return None


ACTIVE_FONT_PATH = get_font_path()


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if ACTIVE_FONT_PATH:
        try:
            return ImageFont.truetype(ACTIVE_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _read_draft_buildings(path: Path) -> Dict[str, Dict[str, Any]]:
    """Read editable floor geometry exported from a formal-draft response."""
    with path.open(encoding="utf-8") as stream:
        document = json.load(stream)
    if isinstance(document, list):
        buildings = document
    elif isinstance(document, dict):
        editor = document.get("editor")
        buildings = (
            editor.get("editable_buildings")
            if isinstance(editor, dict)
            else None
        )
        if buildings is None:
            buildings = document.get("editable_buildings", document.get("buildings"))
    else:
        buildings = None
    if not isinstance(buildings, list) or not buildings:
        raise ValueError("buildings override must contain a non-empty editable_buildings list")

    result: Dict[str, Dict[str, Any]] = {}
    for building in buildings:
        if not isinstance(building, dict):
            raise ValueError("each draft building must be a JSON object")
        building_id = building.get("building_id")
        if not isinstance(building_id, str) or not building_id.strip():
            raise ValueError("each draft building requires a non-empty building_id")
        if building_id in result:
            raise ValueError(f"duplicate draft building_id: {building_id}")

        first_height = building.get("first_floor_height_m")
        standard_height = building.get("standard_floor_height_m")
        if (
            isinstance(first_height, bool)
            or not isinstance(first_height, (int, float))
            or not math.isfinite(float(first_height))
            or float(first_height) <= 0
            or isinstance(standard_height, bool)
            or not isinstance(standard_height, (int, float))
            or not math.isfinite(float(standard_height))
            or float(standard_height) <= 0
        ):
            raise ValueError(f"draft building {building_id} must declare positive floor heights")

        floors = building.get("floors")
        if not isinstance(floors, list) or not floors:
            raise ValueError(f"draft building {building_id} must contain stored floor geometry")
        normalized_floors: list[Dict[str, Any]] = []
        levels: list[int] = []
        for floor in floors:
            if not isinstance(floor, dict):
                raise ValueError(f"draft building {building_id} has a non-object floor")
            level = floor.get("level")
            geometry_json = floor.get("geometry")
            if isinstance(level, bool) or not isinstance(level, int):
                raise ValueError(f"draft building {building_id} has a floor without an integer level")
            if not isinstance(geometry_json, dict):
                raise ValueError(f"draft building {building_id} floor {level} has no polygon geometry")
            try:
                geometry = shape(geometry_json)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"draft building {building_id} floor {level} has invalid geometry") from exc
            if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
                raise ValueError(f"draft building {building_id} floor {level} must be a valid positive-area polygon")
            levels.append(level)
            normalized_floors.append({"level": level, "geometry": geometry_json, "shape": geometry})
        if sorted(levels) != list(range(len(levels))):
            raise ValueError(f"draft building {building_id} floor levels must be contiguous from zero")
        normalized_floors.sort(key=lambda item: item["level"])
        result[building_id] = {
            "floors": normalized_floors,
            "first_floor_height_m": float(first_height),
            "standard_floor_height_m": float(standard_height),
        }
    return result


def _validate_fabric_selection(fabrics: Sequence[str], buildings_override_path: Path | None) -> None:
    unknown = sorted(set(fabrics) - set(FABRICS))
    if unknown:
        raise ValueError(f"unknown fabric selection: {', '.join(unknown)}")
    if not fabrics or len(set(fabrics)) != len(fabrics):
        raise ValueError("fabric selection must contain unique fabric IDs")
    if buildings_override_path is not None and list(fabrics) != ["harbour_grain"]:
        raise ValueError("--buildings-override applies only with --fabrics harbour_grain")


# --- Ear-clipping robust polygon triangulation ---
def ear_clip_polygon(polygon: Polygon) -> list[Polygon]:
    """Triangulate a 2D polygon using ear clipping when Delaunay fails."""
    coords = list(polygon.exterior.coords)[:-1]
    if len(coords) < 3:
        return []
    area = sum(
        coords[i][0] * coords[(i + 1) % len(coords)][1]
        - coords[(i + 1) % len(coords)][0] * coords[i][1]
        for i in range(len(coords))
    )
    if area < 0:
        coords.reverse()

    def is_convex(p_prev, p_curr, p_next):
        return (p_curr[0] - p_prev[0]) * (p_next[1] - p_prev[1]) - (
            p_curr[1] - p_prev[1]
        ) * (p_next[0] - p_prev[0]) > 1e-9

    def point_in_triangle(pt, a, b, c):
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

        d1, d2, d3 = sign(pt, a, b), sign(pt, b, c), sign(pt, c, a)
        return not (
            (d1 < -1e-9 or d2 < -1e-9 or d3 < -1e-9)
            and (d1 > 1e-9 or d2 > 1e-9 or d3 > 1e-9)
        )

    vertices = list(coords)
    triangles: list[Polygon] = []
    it = 0
    max_iter = len(vertices) * len(vertices)
    while len(vertices) > 2 and it < max_iter:
        it += 1
        n = len(vertices)
        ear_found = False
        for i in range(n):
            p_prev, p_curr, p_next = vertices[(i - 1) % n], vertices[i], vertices[(i + 1) % n]
            if not is_convex(p_prev, p_curr, p_next):
                continue
            if any(
                point_in_triangle(vertices[j], p_prev, p_curr, p_next)
                for j in range(n)
                if j not in ((i - 1) % n, i, (i + 1) % n)
            ):
                continue
            triangles.append(Polygon([p_prev, p_curr, p_next]))
            vertices.pop(i)
            ear_found = True
            break
        if not ear_found:
            break
    return triangles


def robust_footprint_to_obstacle(
    poly: Polygon,
    height_m: float,
    obstacle_id: str,
    source: str = "SIMULATION",
    base_z: float = 0.0,
) -> Obstacle:
    """Convert a 2D polygon footprint and height into a 3D multi-face Obstacle."""
    try:
        return footprint_to_obstacle(
            poly, height_m=height_m, base_z=base_z, obstacle_id=obstacle_id, source=source
        )
    except ValueError:
        triangles = ear_clip_polygon(poly)
        if not triangles:
            raise
        faces = []
        top_z = base_z + height_m
        for tri in triangles:
            ring = list(tri.exterior.coords)[:-1]
            faces.append([(float(x), float(y), float(base_z)) for x, y in reversed(ring)])
            faces.append([(float(x), float(y), float(top_z)) for x, y in ring])
        for linear_ring in (poly.exterior, *poly.interiors):
            ring = list(linear_ring.coords)
            for p1, p2 in zip(ring, ring[1:]):
                faces.append([
                    (float(p1[0]), float(p1[1]), float(base_z)),
                    (float(p2[0]), float(p2[1]), float(base_z)),
                    (float(p2[0]), float(p2[1]), float(top_z)),
                    (float(p1[0]), float(p1[1]), float(top_z)),
                ])
        return Obstacle(
            obstacle_id=obstacle_id,
            kind="POLYGONS",
            source=source,
            geometry_hash=_hash_faces(faces),
            faces=faces,
        )


# --- Plan and Context Loading ---
def load_fabric_plan(
    plan_path: Path,
    buildings_override_path: Path | None = None,
) -> Tuple[Dict[str, Any], List[Obstacle], List[Polygon], Dict[str, Polygon], Polygon]:
    """Load a fabric plan and optionally overlay stored formal-draft floor geometry."""
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    site_poly = shape(plan["site"])

    bldg_obstacles: list[Obstacle] = []
    bldg_footprints: list[Polygon] = []
    plan_buildings = list(plan.get("buildings", []))
    draft_buildings = _read_draft_buildings(buildings_override_path) if buildings_override_path else {}
    by_id: dict[str, dict[str, Any]] = {}
    for b in plan_buildings:
        props = b.get("properties", {})
        feature_id = b.get("id") or props.get("id") or props.get("building_id")
        if isinstance(feature_id, str):
            if feature_id in by_id:
                raise ValueError(f"fabric plan contains duplicate building id: {feature_id}")
            by_id[feature_id] = b
    unknown_ids = sorted(set(draft_buildings) - set(by_id))
    if unknown_ids:
        raise ValueError(f"buildings override references unknown plan building IDs: {', '.join(unknown_ids)}")
    for building_id in draft_buildings:
        props = by_id[building_id].get("properties", {})
        if props.get("retained") is True:
            raise ValueError(f"buildings override cannot change retained building: {building_id}")

    effective_plan_buildings: list[dict[str, Any]] = []
    for b in plan_buildings:
        props = b.get("properties", {})
        feature_id = b.get("id") or props.get("id") or props.get("building_id") or "bldg"
        draft = draft_buildings.get(str(feature_id))
        if draft is not None:
            floors = draft["floors"]
            ground_geometry = floors[0]["shape"]
            for floor in floors:
                level = floor["level"]
                base_z = 0.0 if level == 0 else draft["first_floor_height_m"] + (level - 1) * draft["standard_floor_height_m"]
                floor_height = draft["first_floor_height_m"] if level == 0 else draft["standard_floor_height_m"]
                geometry = floor["shape"]
                polygons = [geometry] if isinstance(geometry, Polygon) else [item for item in geometry.geoms if isinstance(item, Polygon)]
                for part_index, polygon in enumerate(polygons):
                    bldg_obstacles.append(
                        robust_footprint_to_obstacle(
                            polygon,
                            height_m=floor_height,
                            base_z=base_z,
                            obstacle_id=f"draft_{feature_id}_floor_{level}_{part_index}",
                            source="FORMAL_DRAFT_OVERRIDE",
                        )
                    )
                    if level == 0:
                        bldg_footprints.append(polygon)
            updated_props = dict(props)
            updated_props["floors"] = len(floors)
            updated_props["height_m"] = draft["first_floor_height_m"] + max(0, len(floors) - 1) * draft["standard_floor_height_m"]
            effective_plan_buildings.append({**b, "geometry": floors[0]["geometry"], "properties": updated_props})
            continue

        effective_plan_buildings.append(b)
        h = props.get("height_m")
        # Demolished buildings with height None or <= 0 do not cast shadows
        if h is None or h <= 0:
            continue
        geom = shape(b["geometry"])
        if not geom.is_valid:
            geom = make_valid(geom)
        polys = (
            [geom]
            if isinstance(geom, Polygon)
            else [g for g in geom.geoms if isinstance(g, Polygon)]
            if hasattr(geom, "geoms")
            else []
        )
        for i, poly in enumerate(polys):
            if poly.is_empty or poly.area < 1.0:
                continue
            bldg_footprints.append(poly)
            feat_id = props.get("id", "bldg")
            bldg_obstacles.append(
                robust_footprint_to_obstacle(
                    poly,
                    height_m=float(h),
                    obstacle_id=f"plan_{feat_id}_{i}",
                    source="PLAN_BUILDING",
                )
            )
    plan["buildings"] = effective_plan_buildings

    # Extract open space geometries by category: parks, waterfront, roads
    open_space_by_category: dict[str, list[Polygon]] = {
        "parks": [],
        "waterfront": [],
        "roads": [],
        "courtyards": [],
        "blocks": [],
        "service": [],
    }
    # Courtyards and other unbuilt block land are open land too; building footprints are
    # removed later by the sensor grid. Retained-building parcels left open (e.g. the
    # demolished #5 plot) are counted with service yards as "other open land".
    land_use_alias = {"retained_buildings": "service"}
    land_use_feats = list(plan.get("land_use", [])) + [
        {"geometry": c["geometry"], "properties": {"category": "courtyards"}} for c in plan.get("courtyards", [])
    ]

    for feat in land_use_feats:
        props = feat.get("properties", {})
        cat = land_use_alias.get(props.get("category"), props.get("category"))
        if cat in open_space_by_category:
            geom = shape(feat["geometry"])
            if not geom.is_valid:
                geom = make_valid(geom)
            if isinstance(geom, Polygon):
                open_space_by_category[cat].append(geom)
            elif hasattr(geom, "geoms"):
                for g in geom.geoms:
                    if isinstance(g, Polygon) and not g.is_empty:
                        open_space_by_category[cat].append(g)

    category_unions = {
        cat: unary_union(geoms) if geoms else Polygon()
        for cat, geoms in open_space_by_category.items()
    }

    return plan, bldg_obstacles, bldg_footprints, category_unions, site_poly


def load_context_obstacles(
    context_geojson_path: Path,
    site_poly: Polygon,
    buffer_m: float = CONTEXT_BUFFER_M,
    default_height_m: float = CONTEXT_ASSUMED_HEIGHT_M,
) -> Tuple[List[Obstacle], Dict[str, Any]]:
    """Load context buildings within buffer of site, converting to 3D obstacles."""
    if not context_geojson_path.is_file():
        return [], {"status": "NOT_FOUND", "path": str(context_geojson_path)}

    with open(context_geojson_path, encoding="utf-8") as f:
        ctx = json.load(f)

    buf_poly = site_poly.buffer(buffer_m)
    obstacles: list[Obstacle] = []
    known_height_count = 0
    assumed_height_count = 0

    for feat in ctx.get("features", []):
        props = feat.get("properties", {})
        if props.get("inside_study_area"):
            continue
        geom = feat.get("geometry")
        if not geom:
            continue
        s = shape(geom)
        # Exclude buildings overlapping site (proposal replaces site buildings)
        if not s.intersects(buf_poly) or s.intersects(site_poly):
            continue

        h = props.get("height_m") or props.get("height")
        if h is not None:
            try:
                h_val = float(h)
                known_height_count += 1
            except Exception:
                h_val = default_height_m
                assumed_height_count += 1
        else:
            h_val = default_height_m
            assumed_height_count += 1

        if h_val <= 0:
            h_val = default_height_m

        if not s.is_valid:
            s = make_valid(s)

        polys = (
            [s]
            if isinstance(s, Polygon)
            else [g for g in s.geoms if isinstance(g, Polygon)]
            if hasattr(s, "geoms")
            else []
        )
        for i, poly in enumerate(polys):
            if poly.is_empty or poly.area < 1.0:
                continue
            feat_id = feat.get("id", "ctx")
            obs = robust_footprint_to_obstacle(
                poly,
                height_m=h_val,
                obstacle_id=f"ctx_{feat_id}_{i}",
                source="CONTEXT_BUILDING",
            )
            obstacles.append(obs)

    meta = {
        "path": str(context_geojson_path),
        "sha256": sha256_file(context_geojson_path),
        "buffer_m": buffer_m,
        "total_context_obstacles": len(obstacles),
        "known_height_obstacles": known_height_count,
        "assumed_height_obstacles": assumed_height_count,
        "assumed_height_value_m": default_height_m,
    }
    return obstacles, meta


# --- Sensor Grid Generation with Category Tagging ---
# Classification priority (first polygon that covers a point wins) and labels.
CATEGORY_ORDER = ("parks", "waterfront", "roads", "courtyards", "blocks", "service")
CATEGORY_LABELS = {
    "parks": "街坊公園/綠軸",
    "waterfront": "水岸公共帶",
    "roads": "街道路權",
    "courtyards": "街廓中庭",
    "blocks": "街廓內其他空地",
    "service": "設備院與其他空地",
}


def generate_categorized_sensor_grid(
    category_unions: Dict[str, Polygon],
    building_footprints: List[Polygon],
    spacing_m: float = 5.0,
    elevation: float = 0.5,
    surface_offset: float = 0.05,
) -> Tuple[List[SensorPoint], Dict[str, str]]:
    """Generate 5m grid points across all open space categories and map each point to its category."""
    all_open_space = unary_union(list(category_unions.values()))
    raw_points = generate_ground_sensor_grid(
        boundary=all_open_space,
        spacing_m=spacing_m,
        elevation=elevation,
        surface_offset=surface_offset,
        building_footprints=building_footprints,
    )

    valid_points = [p for p in raw_points if p.status == "VALID"]
    point_to_cat: dict[str, str] = {}

    for pt in valid_points:
        p_geom = Point(pt.coordinates[0], pt.coordinates[1])
        assigned_cat = "other"
        for cat in CATEGORY_ORDER:
            cat_poly = category_unions.get(cat)
            if cat_poly and not cat_poly.is_empty and cat_poly.covers(p_geom):
                assigned_cat = cat
                break
        if assigned_cat == "other":
            # Distance fallback if boundary precision discrepancy
            closest_cat = "roads"
            min_dist = float("inf")
            for cat in CATEGORY_ORDER:
                cat_poly = category_unions.get(cat)
                if cat_poly and not cat_poly.is_empty:
                    d = cat_poly.distance(p_geom)
                    if d < min_dist:
                        min_dist = d
                        closest_cat = cat
            assigned_cat = closest_cat
        point_to_cat[pt.point_id] = assigned_cat

    return valid_points, point_to_cat


def _courtyard_id(feature: Dict[str, Any]) -> str | None:
    properties = feature.get("properties", {})
    value = properties.get("courtyard_id") or feature.get("courtyard_id") or properties.get("id") or feature.get("id")
    return str(value) if value is not None else None


def assign_courtyard_sensor_points(
    sensors: Sequence[SensorPoint],
    point_to_cat: Dict[str, str],
    courtyards: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    """Associate courtyard-classified sensors with the containing plan courtyard."""
    geometries = []
    for feature in courtyards:
        ident = _courtyard_id(feature)
        if ident is None or not feature.get("geometry"):
            continue
        geometry = shape(feature["geometry"])
        if not geometry.is_valid:
            geometry = make_valid(geometry)
        geometries.append((ident, geometry))
    result: Dict[str, str] = {}
    for sensor in sensors:
        if point_to_cat.get(sensor.point_id) != "courtyards":
            continue
        point = Point(sensor.coordinates[0], sensor.coordinates[1])
        matches = [(geometry.area, ident) for ident, geometry in geometries if geometry.covers(point)]
        if matches:
            result[sensor.point_id] = min(matches)[1]
    return result


def summarize_per_courtyard(
    fabric_id: str,
    courtyard_ids: Sequence[str],
    point_to_courtyard: Dict[str, str],
    daily_results: Dict[str, Sequence[Any]],
    *,
    cell_area_m2: float,
) -> List[Dict[str, Any]]:
    """Summarize the E1 seasonal sensor results by courtyard identifier."""
    dates = {"spring": "2026-03-21", "summer": "2026-06-21", "winter": "2026-12-21"}
    assigned_ids = set(point_to_courtyard)
    records = []
    for courtyard_id in courtyard_ids:
        point_ids = {point_id for point_id in assigned_ids if point_to_courtyard[point_id] == str(courtyard_id)}
        values_by_season = {}
        for season, day in dates.items():
            values_by_season[season] = [item.sunlight_hours for item in daily_results.get(day, [])
                                        if item.point_id in point_ids]
        winter = values_by_season["winter"]
        records.append({
            "fabric_id": fabric_id,
            "courtyard_id": str(courtyard_id),
            "points": len(point_ids),
            "area_m2": round(len(point_ids) * cell_area_m2, 2),
            "spring_mean": round(sum(values_by_season["spring"]) / len(values_by_season["spring"]), 3)
                if values_by_season["spring"] else None,
            "summer_mean": round(sum(values_by_season["summer"]) / len(values_by_season["summer"]), 3)
                if values_by_season["summer"] else None,
            "winter_mean": round(sum(winter) / len(winter), 3) if winter else None,
            "winter_ge_2h_pct": round(sum(value >= 2.0 for value in winter) / len(winter) * 100.0, 2)
                if winter else None,
        })
    return records


def write_per_courtyard_json(output_dir: Path, records: Sequence[Dict[str, Any]]) -> Path:
    path = Path(output_dir) / "per_courtyard.json"
    path.write_text(json.dumps(list(records), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --- Colormap & Palette ---
def get_sunlight_color(hours: float, max_hours: float = 10.0) -> Tuple[int, int, int]:
    """Continuous smooth interpolation from deep shadow to peak sunlight."""
    # Anchors: 0h: shadow navy, 2h: deep blue, 4h: cyan/teal, 6h: amber, 8h: orange, 10h: radiant gold
    anchors = [
        (0.0, (13, 27, 42)),      # Deep Shadow #0d1b2a
        (2.0, (27, 73, 101)),     # Low Sun #1b4965
        (4.0, (42, 157, 143)),    # Moderate Sun #2a9d8f
        (6.0, (233, 196, 106)),   # Warm Amber #e9c46a
        (8.0, (244, 162, 97)),    # Bright Sun #f4a261
        (10.0, (231, 111, 81)),   # Peak Radiant Gold #e76f51
    ]

    h = max(0.0, min(hours, max_hours))
    for i in range(len(anchors) - 1):
        h0, c0 = anchors[i]
        h1, c1 = anchors[i + 1]
        if h0 <= h <= h1:
            t = (h - h0) / (h1 - h0)
            r = int(c0[0] + t * (c1[0] - c0[0]))
            g = int(c0[1] + t * (c1[1] - c0[1]))
            b = int(c0[2] + t * (c1[2] - c0[2]))
            return (r, g, b)
    return anchors[-1][1]


# --- Drawing Helpers ---
def draw_shapely_geom(
    draw: ImageDraw.ImageDraw,
    geom: Any,
    to_scr: Any,
    fill: Optional[str] = None,
    outline: Optional[str] = None,
    width: int = 1,
) -> None:
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, MultiPolygon):
        for poly in geom.geoms:
            draw_shapely_geom(draw, poly, to_scr, fill=fill, outline=outline, width=width)
    elif isinstance(geom, Polygon):
        ext_coords = [to_scr(x, y) for x, y in geom.exterior.coords]
        if len(ext_coords) >= 3:
            if fill:
                draw.polygon(ext_coords, fill=fill)
            if outline:
                if width == 1:
                    draw.polygon(ext_coords, outline=outline)
                else:
                    draw.line(ext_coords + [ext_coords[0]], fill=outline, width=width)
            if fill:
                for interior in geom.interiors:
                    hole_coords = [to_scr(x, y) for x, y in interior.coords]
                    if len(hole_coords) >= 3:
                        draw.polygon(hole_coords, fill="#ffffff", outline=outline)


def draw_north_arrow(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 50, label: str = "北") -> None:
    top = (cx, cy - size)
    bottom = (cx, cy + size // 2)
    left = (cx - size // 3, cy + size // 3)
    right = (cx + size // 3, cy + size // 3)
    center = (cx, cy)
    draw.polygon([top, left, center], fill="#2c3e50")
    draw.polygon([top, right, center], fill="#bdc3c7")
    draw.polygon([top, left, bottom, right], outline="#1a252f", width=2)
    font = get_font(20)
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - size - th - 6), label, font=font, fill="#1a252f")


def draw_scale_bar(
    draw: ImageDraw.ImageDraw, x: int, y: int, scale_px_per_m: float, bar_meters: int = 200
) -> None:
    font = get_font(18)
    bar_px = int(bar_meters * scale_px_per_m)
    h = 8
    half_px = bar_px // 2
    draw.rectangle([x, y, x + half_px, y + h], fill="#2c3e50", outline="#1a252f", width=1)
    draw.rectangle([x + half_px, y, x + bar_px, y + h], fill="#ffffff", outline="#1a252f", width=1)
    draw.line([(x, y - 4), (x, y + h + 4)], fill="#1a252f", width=2)
    draw.line([(x + half_px, y - 4), (x + half_px, y + h + 4)], fill="#1a252f", width=2)
    draw.line([(x + bar_px, y - 4), (x + bar_px, y + h + 4)], fill="#1a252f", width=2)
    draw.text((x - 6, y + h + 6), "0", font=font, fill="#1a252f")
    draw.text((x + half_px - 14, y + h + 6), f"{bar_meters // 2}", font=font, fill="#1a252f")
    draw.text((x + bar_px - 20, y + h + 6), f"{bar_meters} m", font=font, fill="#1a252f")


# --- Heatmap Image Renderer ---
def render_fabric_sunlight_heatmap(
    fabric_id: str,
    date_str: str,
    points: Sequence[SensorPoint],
    results_map: Dict[str, float],
    plan_dict: Dict[str, Any],
    bldg_footprints: List[Polygon],
    context_obstacles: List[Obstacle],
    site_poly: Polygon,
    extent_bounds: Tuple[float, float, float, float],
    stats_dict: Dict[str, Any],
    output_path: Path,
    width: int = 3200,
    height: int = 2400,
    spacing_m: float = 5.0,
) -> None:
    """Render a single fabric daily direct sunlight heatmap with Traditional Chinese legend and metadata."""
    img = Image.new("RGB", (width, height), "#fcfbf9")
    draw = ImageDraw.Draw(img)

    # Frame border
    draw.rectangle([30, 30, width - 30, height - 30], outline="#d5d8d7", width=2)

    # Viewport calculation
    vp_x0, vp_y0 = 60, 160
    vp_w, vp_h = 2400, 2180
    min_x, min_y, max_x, max_y = extent_bounds

    span_x = max_x - min_x
    span_y = max_y - min_y
    scale = min(vp_w / span_x, vp_h / span_y) * 0.95

    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    vp_cx = vp_x0 + vp_w / 2.0
    vp_cy = vp_y0 + vp_h / 2.0

    def to_scr(x: float, y: float) -> Tuple[int, int]:
        sx = vp_cx + (x - center_x) * scale
        sy = vp_cy - (y - center_y) * scale
        return int(round(sx)), int(round(sy))

    # 1. Draw Viewport Background & Water
    water_geom = shape(plan_dict.get("water", {})) if "water" in plan_dict else None
    if water_geom and not water_geom.is_empty:
        draw_shapely_geom(draw, water_geom, to_scr, fill="#dceef5", outline="#b0d0e0", width=1)

    # 2. Draw Site Boundary
    draw_shapely_geom(draw, site_poly, to_scr, fill="#f9f8f4", outline="#bdc3c7", width=2)

    # 3. Draw Context Buildings — 2D footprints from the context layer (obstacle ground faces
    # are triangulated and rendered as shards), clipped to the shared map frame.
    _frame = Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)])
    try:
        with open(DEFAULT_CONTEXT_BUILDINGS, encoding="utf-8") as _fh:
            _ctx = json.load(_fh).get("features", [])
    except OSError:
        _ctx = []
    for _feat in _ctx:
        try:
            _g = shape(_feat["geometry"]).intersection(_frame)
        except Exception:
            continue
        if not _g.is_empty:
            draw_shapely_geom(draw, _g, to_scr, fill="#e8eae9", outline="#d0d4d3", width=1)

    # 4. Draw Sunlight Sensor Cells
    half_cell = spacing_m / 2.0
    for pt in points:
        hours = results_map.get(pt.point_id, 0.0)
        px, py = pt.coordinates[0], pt.coordinates[1]
        x1, y1 = to_scr(px - half_cell, py + half_cell)
        x2, y2 = to_scr(px + half_cell, py - half_cell)
        # Ensure proper rectangle bounds
        left, right = min(x1, x2), max(x1, x2)
        top, bottom = min(y1, y2), max(y1, y2)
        c = get_sunlight_color(hours, max_hours=10.0)
        draw.rectangle([left, top, right, bottom], fill=c, outline=None)

    # 5. Draw Plan Building Footprints (on top of sensors)
    for b_poly in bldg_footprints:
        draw_shapely_geom(draw, b_poly, to_scr, fill="#2d3436", outline="#636e72", width=1)

    # 6. Header Section
    font_title = get_font(42)
    font_sub = get_font(26)
    font_badge = get_font(22)
    font_body = get_font(20)
    font_bold = get_font(22)

    fabric_zh = FABRIC_NAMES_ZH.get(fabric_id, fabric_id)
    date_zh = DATE_LABELS_ZH.get(date_str, date_str)

    draw.text(
        (60, 50),
        f"鹿特丹 M4H 港區活化 ｜ {fabric_zh} 開放空間直射日照時數分析",
        font=font_title,
        fill="#1e272e",
    )
    draw.text(
        (60, 105),
        f"分析日期：{date_zh} ｜ 每日分析時段：08:00–18:00 ｜ 網格間距：{spacing_m:.1f} m ｜ 感測高度：地面＋0.5 m",
        font=font_sub,
        fill="#57606f",
    )

    # Badge: 探索性分析
    badge_text = "【探索性分析】非正式法定審批依據"
    badge_bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw, bh = badge_bbox[2] - badge_bbox[0], badge_bbox[3] - badge_bbox[1]
    bx = width - 60 - bw - 24
    by = 55
    draw.rectangle([bx, by, bx + bw + 24, by + bh + 16], fill="#fff2e5", outline="#f39c12", width=2)
    draw.text((bx + 12, by + 8), badge_text, font=font_badge, fill="#d35400")

    # 7. Sidebar Information & Statistics Panel
    panel_x = 2490
    panel_y = 160
    panel_w = 650
    panel_h = 2180
    draw.rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + panel_h], fill="#ffffff", outline="#dfe4ea", width=2)

    # Panel Header
    draw.rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + 60], fill="#f1f2f6")
    draw.text((panel_x + 20, panel_y + 16), "方案日照指標統計摘要", font=font_bold, fill="#2f3542")

    cur_y = panel_y + 80

    def draw_stat_row(label: str, val_str: str, highlight: bool = False) -> None:
        nonlocal cur_y
        fill_bg = "#f8f9fa" if highlight else "#ffffff"
        draw.rectangle([panel_x + 15, cur_y, panel_x + panel_w - 15, cur_y + 36], fill=fill_bg)
        draw.text((panel_x + 25, cur_y + 6), label, font=font_body, fill="#57606f")
        bbox = draw.textbbox((0, 0), val_str, font=font_bold)
        vw = bbox[2] - bbox[0]
        draw.text((panel_x + panel_w - 30 - vw, cur_y + 5), val_str, font=font_bold, fill="#2f3542")
        cur_y += 42

    draw.text((panel_x + 20, cur_y), "■ 總體開放空間指標", font=font_bold, fill="#1e272e")
    cur_y += 35
    all_s = stats_dict.get("all", {})
    draw_stat_row("開放空間總面積", f"{all_s.get('area_m2', 0):,.0f} 平方公尺")
    draw_stat_row("有效感測網格點數", f"{all_s.get('point_count', 0):,} 點")
    draw_stat_row("平均直射日照時數", f"{all_s.get('mean_hours', 0.0):.2f} 小時", highlight=True)
    draw_stat_row("日照 ≥ 2 小時面積比", f"{all_s.get('pct_ge_2h', 0.0):.1f} %", highlight=True)
    draw_stat_row("日照 ≥ 4 小時面積比", f"{all_s.get('pct_ge_4h', 0.0):.1f} %")

    cur_y += 15
    draw.text((panel_x + 20, cur_y), "■ 分類開放空間指標", font=font_bold, fill="#1e272e")
    cur_y += 35

    cats = [(k, CATEGORY_LABELS[k]) for k in CATEGORY_ORDER]
    for cat_key, cat_name in cats:
        cs = stats_dict.get(cat_key, {})
        draw.text((panel_x + 25, cur_y), f"● {cat_name} ({cs.get('area_m2', 0):,.0f} 平方公尺)", font=font_bold, fill="#2c3e50")
        cur_y += 30
        draw_stat_row("  - 平均日照時數", f"{cs.get('mean_hours', 0.0):.2f} 小時")
        draw_stat_row("  - 日照 ≥ 2 小時比例", f"{cs.get('pct_ge_2h', 0.0):.1f} %")
        cur_y += 8

    cur_y += 15
    draw.text((panel_x + 20, cur_y), "■ 太陽軌跡與幾何設定", font=font_bold, fill="#1e272e")
    cur_y += 35
    draw_stat_row("地理座標", "51.91° N, 4.43° E (鹿特丹)")
    draw_stat_row("時區設定", "Europe/Amsterdam")
    draw_stat_row("網格子午線收斂角", f"{compute_grid_convergence_deg(4.43054, 51.907921):.3f}°")
    draw_stat_row("取樣頻率", "15 分鐘 (每小時 4 次)")
    solar_alt = {"2026-03-21": "38.1°", "2026-06-21": "61.5°", "2026-12-21": "14.7°"}
    draw_stat_row("正午太陽最高仰角", solar_alt.get(date_str, "—"))

    # Colormap Legend inside panel
    cur_y += 25
    draw.text((panel_x + 20, cur_y), "■ 日照時數圖例 (小時)", font=font_bold, fill="#1e272e")
    cur_y += 35

    leg_x = panel_x + 40
    leg_w = panel_w - 80
    leg_h = 24
    for i in range(leg_w):
        val = (i / leg_w) * 10.0
        c = get_sunlight_color(val, max_hours=10.0)
        draw.line([(leg_x + i, cur_y), (leg_x + i, cur_y + leg_h)], fill=c)
    draw.rectangle([leg_x, cur_y, leg_x + leg_w, cur_y + leg_h], outline="#2f3542", width=1)

    cur_y += leg_h + 8
    font_legend = get_font(18)
    for tick in [0, 2, 4, 6, 8, 10]:
        tx = leg_x + int((tick / 10.0) * leg_w)
        draw.line([(tx, cur_y - 8), (tx, cur_y - 2)], fill="#2f3542", width=1)
        t_label = f"{tick}h"
        t_bbox = draw.textbbox((0, 0), t_label, font=font_legend)
        tw = t_bbox[2] - t_bbox[0]
        draw.text((tx - tw // 2, cur_y), t_label, font=font_legend, fill="#2f3542")

    # Bottom notes
    cur_y += 45
    draw.rectangle([panel_x + 15, cur_y, panel_x + panel_w - 15, cur_y + 110], fill="#fdfbf7", outline="#f5cd79", width=1)
    notes = [
        "說明：",
        "1. 日照時數係由 Ladybug Radiance 6.0.2 引擎直射追蹤計算。",
        "2. 包含周邊 300 m 脈絡建築與方案自身建築之全實體遮擋。",
        "3. ≥2 小時為荷蘭都市開放空間冬至/春分舒適度標準參考指標。",
    ]
    for i, line in enumerate(notes):
        draw.text((panel_x + 25, cur_y + 8 + i * 24), line, font=get_font(15), fill="#7f8c8d")

    # 8. North Arrow & Scale Bar
    draw_north_arrow(draw, cx=panel_x + 100, cy=panel_y + panel_h - 100, size=45)
    draw_scale_bar(draw, x=panel_x + 220, y=panel_y + panel_h - 90, scale_px_per_m=scale, bar_meters=200)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)


# --- Render Summary Comparison Graphic ---
def render_comparison_summary_graphic(
    comparison_records: List[Dict[str, Any]],
    output_path: Path,
    width: int = 2400,
    height: int | None = None,
) -> None:
    """Render a comprehensive Traditional Chinese infographic table comparing all 4 fabrics."""
    if height is None:
        height = 150 + 45 + 36 * len(comparison_records) + 30 + 160 + 60
    img = Image.new("RGB", (width, height), "#fcfbf9")
    draw = ImageDraw.Draw(img)

    draw.rectangle([30, 30, width - 30, height - 30], outline="#d5d8d7", width=2)

    font_title = get_font(38)
    font_sub = get_font(24)
    font_th = get_font(20)
    font_td = get_font(18)
    font_bold = get_font(19)

    draw.text((60, 50), "鹿特丹 M4H 港區活化 ｜ 四個紋理方案開放空間日照時數綜合比較表", font=font_title, fill="#1e272e")
    draw.text((60, 100), "模擬條件：5 m 網格、0.5 m 感測高度、15 分鐘取樣、Radiance 6.0.2 引擎、周邊 300 m 脈絡遮擋", font=font_sub, fill="#57606f")

    # Badge
    badge_text = "【探索性比較】"
    draw.rectangle([width - 240, 50, width - 60, 95], fill="#fff2e5", outline="#f39c12", width=1)
    draw.text((width - 225, 60), badge_text, font=font_th, fill="#d35400")

    # Table layout
    table_x = 60
    table_y = 150
    table_w = width - 120

    col_widths = [220, 200, 110, 140, 130, 130, 130, 130, 130, 130]
    headers = [
        "紋理方案",
        "開放空間類別",
        "網格點數",
        "面積 (m2)",
        "春分平均(h)",
        "春分≥2h(%)",
        "夏至平均(h)",
        "夏至≥2h(%)",
        "冬至平均(h)",
        "冬至≥2h(%)",
    ]

    # Draw Header
    draw.rectangle([table_x, table_y, table_x + table_w, table_y + 45], fill="#2f3542")
    cur_x = table_x
    for i, (h_title, w_col) in enumerate(zip(headers, col_widths)):
        draw.text((cur_x + 10, table_y + 12), h_title, font=font_th, fill="#ffffff")
        cur_x += w_col

    cur_y = table_y + 45
    for idx, rec in enumerate(comparison_records):
        is_total = rec["category"] == "全體開放空間"
        bg_color = "#f1f2f6" if is_total else ("#ffffff" if idx % 2 == 0 else "#f8f9fa")
        draw.rectangle([table_x, cur_y, table_x + table_w, cur_y + 36], fill=bg_color)
        draw.line([(table_x, cur_y + 36), (table_x + table_w, cur_y + 36)], fill="#e4e7ea", width=1)

        row_vals = [
            rec["fabric_name_zh"],
            rec["category"],
            f"{rec['points']:,}",
            f"{rec['area_m2']:,.0f}",
            f"{rec['spring_mean']:.2f}",
            f"{rec['spring_ge_2h_pct']:.1f}%",
            f"{rec['summer_mean']:.2f}",
            f"{rec['summer_ge_2h_pct']:.1f}%",
            f"{rec['winter_mean']:.2f}",
            f"{rec['winter_ge_2h_pct']:.1f}%",
        ]
        cur_x = table_x
        f_use = font_bold if is_total else font_td
        fill_text = "#2c3e50" if is_total else "#34495e"
        for val, w_col in zip(row_vals, col_widths):
            draw.text((cur_x + 10, cur_y + 8), val, font=f_use, fill=fill_text)
            cur_x += w_col
        cur_y += 36

    # Summary notes at bottom
    cur_y += 30
    draw.rectangle([table_x, cur_y, table_x + table_w, cur_y + 160], fill="#ffffff", outline="#dfe4ea", width=1)
    notes = [
        "核心結論與比較發現：",
        "1. 「全體開放空間」＝基地內全部未建土地：公園／綠軸、水岸帶、街道、街廓中庭、街廓內其他空地、設備院（建築覆蓋面積不計）。",
        "2. 鹿特丹冬至正午太陽仰角僅 14.7°，中庭與窄街受建築遮擋最明顯；≥2 小時為荷蘭開放空間冬至／春分舒適度參考指標。",
        "3. 四案同一視圖範圍、同一色階；數值為 Ladybug 直射追蹤，探索性分析，非法定審查依據。",
    ]
    for i, line in enumerate(notes):
        draw.text((table_x + 20, cur_y + 15 + i * 34), line, font=get_font(18), fill="#2c3e50")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)


def render_english_comparison_summary(
    comparison_records: List[Dict[str, Any]], output_path: Path, width: int = 2400
) -> None:
    """Render the existing E1 aggregate records with English labels; performs no simulation."""
    height = 150 + 45 + 36 * len(comparison_records) + 30 + 160 + 60
    img = Image.new("RGB", (width, height), "#fcfbf9")
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 30, width - 30, height - 30], outline="#d5d8d7", width=2)

    draw.text(
        (60, 50),
        "Rotterdam M4H | Four-Fabric Open-Space Sunlight Duration Comparison",
        font=get_font(36),
        fill="#1e272e",
    )
    draw.text(
        (60, 100),
        "5 m grid | 0.5 m sensor height | 15-minute sampling | Radiance 6.0.2 | 300 m context obstruction | 08:00–18:00",
        font=get_font(21),
        fill="#57606f",
    )

    badge = "EXPLORATORY"
    draw.rectangle([width - 260, 48, width - 60, 94], fill="#fff2e5", outline="#f39c12", width=1)
    draw.text((width - 246, 60), badge, font=get_font(18), fill="#d35400")

    table_x, table_y = 60, 150
    col_widths = [300, 370, 140, 150, 205, 205, 205, 205, 205, 205]
    headers = [
        "Fabric",
        "Open-space category",
        "Sensor points",
        "Area (m2)",
        "Spring mean (h)",
        "Spring ≥2 h (%)",
        "Summer mean (h)",
        "Summer ≥2 h (%)",
        "Winter mean (h)",
        "Winter ≥2 h (%)",
    ]
    draw.rectangle([table_x, table_y, width - 60, table_y + 45], fill="#2f3542")
    x = table_x
    for label, col_width in zip(headers, col_widths):
        draw.text((x + 10, table_y + 12), label, font=get_font(17), fill="#ffffff")
        x += col_width

    y = table_y + 45
    for index, record in enumerate(comparison_records):
        is_total = record["category_key"] == "all"
        background = "#f1f2f6" if is_total else ("#ffffff" if index % 2 == 0 else "#f8f9fa")
        draw.rectangle([table_x, y, width - 60, y + 36], fill=background)
        draw.line([(table_x, y + 36), (width - 60, y + 36)], fill="#e4e7ea", width=1)
        values = [
            FABRIC_NAMES_EN.get(record["fabric_id"], record["fabric_id"]),
            SPACE_CATEGORY_LABELS_EN.get(record["category_key"], record["category"]),
            f"{record['points']:,}",
            f"{record['area_m2']:,.0f}",
            f"{record['spring_mean']:.2f}",
            f"{record['spring_ge_2h_pct']:.1f}%",
            f"{record['summer_mean']:.2f}",
            f"{record['summer_ge_2h_pct']:.1f}%",
            f"{record['winter_mean']:.2f}",
            f"{record['winter_ge_2h_pct']:.1f}%",
        ]
        x = table_x
        font = get_font(17 if is_total else 16)
        fill = "#2c3e50" if is_total else "#34495e"
        for value, col_width in zip(values, col_widths):
            draw.text((x + 10, y + 8), value, font=font, fill=fill)
            x += col_width
        y += 36

    y += 30
    draw.rectangle([table_x, y, width - 60, y + 160], fill="#ffffff", outline="#dfe4ea", width=1)
    notes = [
        "Comparison notes:",
        "1. All open space covers unbuilt site land: parks and green corridors, waterfront, streets, courtyards, other block land, and service yards; building footprints are excluded.",
        "2. Rotterdam's winter-solstice noon sun altitude is 14.7°. Courtyards and narrow streets show the clearest building-shading effects; ≥2 h is a reference indicator for Dutch open spaces on the winter solstice and spring equinox.",
        "3. All four schemes use the same map extent and colour scale. Values are from Ladybug direct-sun tracing; this is exploratory analysis, not a statutory review basis.",
    ]
    note_font = get_font(16)
    for index, note in enumerate(notes):
        draw.text((table_x + 20, y + 12 + index * 34), note, font=note_font, fill="#2c3e50")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)


def _verify_e1_source_manifest(source_dir: Path, filenames: Sequence[str]) -> Dict[str, Any]:
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"E1 source manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("output_artifacts", {})
    for filename in filenames:
        path = source_dir / filename
        entry = entries.get(filename)
        if not path.is_file() or not isinstance(entry, dict) or not entry.get("sha256"):
            raise ValueError(f"E1 source is not registered in manifest: {filename}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"E1 source hash does not match manifest: {filename}")
    return manifest


def render_existing_english_figures(
    source_dir: Path, output_dir: Path, fabrics: Sequence[str] = FABRICS
) -> List[Path]:
    """Render English E1 figures from registered result JSON/CSV and existing map pixels only."""
    map_names = [f"{fabric}-{day:%Y%m%d}-sunlight-zh.png" for fabric in fabrics for day in ANALYSIS_DATES]
    summary_inputs = ["comparison_table.json", "comparison_summary_zh.png"]
    source_manifest = _verify_e1_source_manifest(source_dir, [*map_names, *summary_inputs])

    records = json.loads((source_dir / "comparison_table.json").read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: List[Path] = []
    render_english_comparison_summary(records, output_dir / "comparison_summary_en.png")
    generated.append(output_dir / "comparison_summary_en.png")

    for fabric in fabrics:
        for day in ANALYSIS_DATES:
            date_str = day.isoformat()
            source = source_dir / f"{fabric}-{day:%Y%m%d}-sunlight-zh.png"
            target = output_dir / f"{fabric}-{day:%Y%m%d}-sunlight-en.png"
            render_english_sunlight_figure(
                source,
                target,
                fabric,
                date_str,
                source_manifest.get("fabric_summaries", {}),
            )
            generated.append(target)
    return generated


def render_english_sunlight_figure(
    source_path: Path,
    output_path: Path,
    fabric_id: str,
    date_str: str,
    fabric_summaries: Dict[str, Any],
) -> None:
    """Retain the source map pixels and render English annotations from its aggregate result JSON."""
    with Image.open(source_path) as source:
        source = source.convert("RGB")
        if source.size != (3200, 2400):
            raise ValueError(f"Unexpected E1 source map size {source.size}: {source_path}")
        img = Image.new("RGB", source.size, "#fcfbf9")
        img.paste(source.crop((30, 160, 2470, 2340)), (30, 160))

    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 30, 3170, 2370], outline="#d5d8d7", width=2)
    name = FABRIC_NAMES_EN[fabric_id]
    selected = " (Selected)" if fabric_id == "harbour_grain" else ""
    draw.text(
        (60, 45),
        f"Rotterdam M4H | {name}{selected} Open-Space Direct Sunlight Duration",
        font=get_font(39),
        fill="#1e272e",
    )
    draw.text(
        (60, 105),
        f"Date: {DATE_LABELS_EN[date_str]} | Daily period: 08:00–18:00 | Grid: 5.0 m | Sensor height: 0.5 m above ground",
        font=get_font(23),
        fill="#57606f",
    )

    badge = "EXPLORATORY | NOT FOR STATUTORY APPROVAL"
    badge_font = get_font(18)
    badge_box = draw.textbbox((0, 0), badge, font=badge_font)
    badge_width = badge_box[2] - badge_box[0]
    badge_x = 3140 - badge_width - 28
    draw.rectangle([badge_x, 46, 3140, 94], fill="#fff2e5", outline="#f39c12", width=2)
    draw.text((badge_x + 12, 58), badge, font=badge_font, fill="#d35400")

    panel_x, panel_y, panel_w, panel_h = 2490, 160, 650, 2180
    draw.rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + panel_h], fill="#ffffff", outline="#dfe4ea", width=2)
    draw.rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + 60], fill="#f1f2f6")
    draw.text((panel_x + 20, panel_y + 16), "Sunlight indicators by fabric", font=get_font(21), fill="#2f3542")

    fabric_summary = fabric_summaries.get(fabric_id)
    if not isinstance(fabric_summary, dict):
        raise ValueError(f"E1 manifest is missing fabric statistics for {fabric_id}")
    day_stats = fabric_summary.get("daily_metrics", {}).get(date_str, {})
    if "all" not in day_stats:
        raise ValueError(f"E1 manifest is missing total daily metrics for {fabric_id} on {date_str}")
    cursor_y = panel_y + 80

    def section_heading(text: str) -> None:
        nonlocal cursor_y
        draw.text((panel_x + 20, cursor_y), f"■ {text}", font=get_font(20), fill="#1e272e")
        cursor_y += 34

    def stat_row(label: str, value: str, highlight: bool = False) -> None:
        nonlocal cursor_y
        y0 = cursor_y
        draw.rectangle(
            [panel_x + 15, y0, panel_x + panel_w - 15, y0 + 34],
            fill="#f8f9fa" if highlight else "#ffffff",
        )
        font_label, font_value = get_font(17), get_font(18)
        draw.text((panel_x + 25, y0 + 6), label, font=font_label, fill="#57606f")
        bbox = draw.textbbox((0, 0), value, font=font_value)
        draw.text((panel_x + panel_w - 30 - (bbox[2] - bbox[0]), y0 + 5), value, font=font_value, fill="#2f3542")
        cursor_y += 38

    total = day_stats["all"]
    section_heading("All open space")
    stat_row("Total area", f"{total['area_m2']:,.0f} m2")
    stat_row("Valid sensor cells", f"{total['point_count']:,}")
    stat_row("Mean direct sunlight", f"{total['mean_hours']:.2f} h", highlight=True)
    stat_row("Area with ≥2 h sunlight", f"{total['pct_ge_2h']:.1f}%", highlight=True)
    stat_row("Area with ≥4 h sunlight", f"{total['pct_ge_4h']:.1f}%")

    cursor_y += 10
    section_heading("Open-space categories")
    for category in ("parks", "waterfront", "roads", "courtyards", "blocks", "service"):
        record = day_stats.get(category)
        if record is None:
            continue
        label = SPACE_CATEGORY_LABELS_EN[category]
        draw.text(
            (panel_x + 25, cursor_y),
            f"● {label} ({record['area_m2']:,.0f} m2)",
            font=get_font(17),
            fill="#2c3e50",
        )
        cursor_y += 25
        stat_row("  Mean direct sunlight", f"{record['mean_hours']:.2f} h")
        stat_row("  Area with ≥2 h sunlight", f"{record['pct_ge_2h']:.1f}%")
        cursor_y += 2

    cursor_y += 8
    section_heading("Solar path and geometry")
    stat_row("Coordinates", "51.91° N, 4.43° E (Rotterdam)")
    stat_row("Time zone", "Europe/Amsterdam")
    convergence = compute_grid_convergence_deg(4.43054, 51.907921)
    stat_row("Grid convergence", f"{convergence:.3f}°")
    stat_row("Sampling", "15 min (4 samples per hour)")
    solar_altitude = {"2026-03-21": "38.1°", "2026-06-21": "61.5°", "2026-12-21": "14.7°"}
    stat_row("Maximum noon solar altitude", solar_altitude[date_str])

    cursor_y += 10
    section_heading("Direct sunlight duration (hours)")
    legend_x, legend_y, legend_w, legend_h = panel_x + 40, cursor_y, panel_w - 80, 24
    for index in range(legend_w):
        draw.line(
            [(legend_x + index, legend_y), (legend_x + index, legend_y + legend_h)],
            fill=get_sunlight_color(index / legend_w * 10.0, max_hours=10.0),
        )
    draw.rectangle([legend_x, legend_y, legend_x + legend_w, legend_y + legend_h], outline="#2f3542", width=1)
    cursor_y += legend_h + 6
    for tick in (0, 2, 4, 6, 8, 10):
        x = legend_x + int(tick / 10.0 * legend_w)
        draw.text((x - 10, cursor_y), f"{tick} h", font=get_font(15), fill="#2f3542")

    note_y = cursor_y + 30
    draw.rectangle([panel_x + 15, note_y, panel_x + panel_w - 15, note_y + 112], fill="#fdfbf7", outline="#f5cd79", width=1)
    notes = [
        "Notes:",
        "1. Ladybug/Radiance 6.0.2 direct-sun tracing.",
        "2. Includes 300 m context buildings and scheme buildings as obstructions.",
        "3. ≥2 h is a reference indicator; it is not statutory certification.",
    ]
    for index, note in enumerate(notes):
        draw.text((panel_x + 25, note_y + 7 + index * 24), note, font=get_font(13), fill="#7f8c8d")

    # Preserve the existing scale geometry while replacing its Chinese north label.
    with Image.open(source_path) as source:
        img.paste(source.convert("RGB").crop((panel_x + 190, 2235, panel_x + panel_w - 10, 2335)), (panel_x + 190, 2235))
    draw = ImageDraw.Draw(img)
    draw_north_arrow(draw, cx=panel_x + 100, cy=panel_y + panel_h - 45, size=45, label="N")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)


# --- Main Pipeline Execution ---
def run_fabric_sunlight_pipeline(
    fabrics: Sequence[str] = FABRICS,
    spacing_m: float = 5.0,
    output_dir: Path = Path("artifacts/w8/e1-fabric"),
    quick: bool = False,
    buildings_override_path: Path | None = None,
) -> Dict[str, Any]:
    """Run full E1 fabric sunlight workflow, generate heatmaps, comparison table, and manifest."""
    _validate_fabric_selection(fabrics, buildings_override_path)
    start_time_all = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    actual_spacing = 20.0 if quick else spacing_m
    print(f"=== E1 紋理方案開放空間日照計算啟動 (網格間距: {actual_spacing:.1f} m) ===")

    # 1. Verify Radiance Runtime
    rad_status = verify_radiance_runtime()
    if not rad_status.available:
        raise RuntimeError(f"Radiance runtime verification failed: {rad_status.reason}")
    print(f"Radiance 執行環境已就緒 (版本: {rad_status.version})")

    # 2. Location & Analysis Period
    loc = get_rotterdam_m4h_demo_location()
    gamma = compute_grid_convergence_deg(loc.longitude, loc.latitude)
    period = AnalysisPeriod(
        start_date=ANALYSIS_DATES[0],
        end_date=ANALYSIS_DATES[-1],
        dates=ANALYSIS_DATES,
        start_hour=8.0,
        end_hour=18.0,
        timestep=4,
    )
    print(f"模擬地點: 鹿特丹 M4H ({loc.latitude}° N, {loc.longitude}° E), 子午線收斂角 gamma={gamma:.4f}°")

    # 3. Compute Union Viewport Bounding Box across all fabrics
    site_bounds_list = []
    plan_data: dict[str, dict] = {}
    for f_id in fabrics:
        p_path = Path(f"artifacts/fab1/run-8/{f_id}-plan.json")
        with open(p_path, encoding="utf-8") as f:
            d = json.load(f)
            plan_data[f_id] = d
            site_bounds_list.append(shape(d["site"]).bounds)

    extent_bounds = (
        min(b[0] for b in site_bounds_list) - 100.0,
        min(b[1] for b in site_bounds_list) - 80.0,
        max(b[2] for b in site_bounds_list) + 100.0,
        max(b[3] for b in site_bounds_list) + 80.0,
    )
    print(f"全案共用視圖邊界 (EPSG:28992): {extent_bounds}")

    # 4. Process Each Fabric
    comparison_records: list[dict[str, Any]] = []
    per_courtyard_records: list[dict[str, Any]] = []
    fabric_summaries: dict[str, Any] = {}
    generated_pngs: list[Path] = []

    for f_id in fabrics:
        t_fab_start = time.time()
        f_name_zh = FABRIC_NAMES_ZH.get(f_id, f_id)
        plan_path = Path(f"artifacts/fab1/run-8/{f_id}-plan.json")
        print(f"\n--- 正在計算方案: {f_name_zh} ({f_id}) ---")

        # Load plan & context
        plan_dict, bldg_obs, bldg_footprints, category_unions, site_poly = load_fabric_plan(
            plan_path, buildings_override_path=buildings_override_path
        )
        ctx_obs, ctx_meta = load_context_obstacles(DEFAULT_CONTEXT_BUILDINGS, site_poly)
        all_obstacles = bldg_obs + ctx_obs
        print(f"障礙物載入完成: 方案建物 {len(bldg_obs)} 棟, 周邊脈絡建物 {len(ctx_obs)} 棟 (共 {len(all_obstacles)} 個 3D 遮擋面組)")

        # Generate Categorized Sensor Grid
        sensors, point_to_cat = generate_categorized_sensor_grid(
            category_unions=category_unions,
            building_footprints=bldg_footprints,
            spacing_m=actual_spacing,
            elevation=0.5,
            surface_offset=0.05,
        )
        print(f"網格點生成完成: 共 {len(sensors)} 個有效地面感測點 (5 m 間距)")

        # Run Sunlight Simulation via Radiance
        t_sim_start = time.time()
        sim_result = calculate_direct_sunlight_hours(
            location=loc,
            period=period,
            sensor_points=sensors,
            obstacles=all_obstacles,
            method="ladybug_radiance",
            true_north_offset_deg=gamma,
        )
        t_sim_end = time.time()
        sim_duration_s = t_sim_end - t_sim_start
        print(f"Radiance 追蹤計算完成: 耗時 {sim_duration_s:.2f} 秒")

        # Compute Category Statistics for Each Day
        cell_area = actual_spacing * actual_spacing
        daily_stats_by_cat: dict[str, dict[str, dict[str, float]]] = {}

        for d_obj in ANALYSIS_DATES:
            d_str = d_obj.isoformat()
            pts = sim_result.daily_results.get(d_str, [])
            pts_by_cat: dict[str, list[float]] = defaultdict(list)
            for p in pts:
                cat = point_to_cat.get(p.point_id, "other")
                pts_by_cat[cat].append(p.sunlight_hours)
                pts_by_cat["all"].append(p.sunlight_hours)

            cat_metrics: dict[str, dict[str, float]] = {}
            for cat_key, hours_list in pts_by_cat.items():
                if not hours_list:
                    continue
                mean_h = sum(hours_list) / len(hours_list)
                pct_2h = sum(h >= 2.0 for h in hours_list) / len(hours_list) * 100.0
                pct_4h = sum(h >= 4.0 for h in hours_list) / len(hours_list) * 100.0
                cat_metrics[cat_key] = {
                    "point_count": len(hours_list),
                    "area_m2": len(hours_list) * cell_area,
                    "mean_hours": round(mean_h, 3),
                    "pct_ge_2h": round(pct_2h, 2),
                    "pct_ge_4h": round(pct_4h, 2),
                }
            daily_stats_by_cat[d_str] = cat_metrics

            # Render Daily Heatmap
            date_compact = d_str.replace("-", "")
            heatmap_filename = f"{f_id}-{date_compact}-sunlight-zh.png"
            heatmap_path = output_dir / heatmap_filename
            results_map = {p.point_id: p.sunlight_hours for p in pts}

            render_fabric_sunlight_heatmap(
                fabric_id=f_id,
                date_str=d_str,
                points=sensors,
                results_map=results_map,
                plan_dict=plan_dict,
                bldg_footprints=bldg_footprints,
                context_obstacles=ctx_obs,
                site_poly=site_poly,
                extent_bounds=extent_bounds,
                stats_dict=cat_metrics,
                output_path=heatmap_path,
                spacing_m=actual_spacing,
            )
            generated_pngs.append(heatmap_path)
            print(f"  > 已輸出熱圖: {heatmap_path.name} (平均 {cat_metrics.get('all', {}).get('mean_hours', 0.0):.2f} h, ≥2h: {cat_metrics.get('all', {}).get('pct_ge_2h', 0.0):.1f}%)")

        point_to_courtyard = assign_courtyard_sensor_points(
            sensors, point_to_cat, plan_dict.get("courtyards", []))
        per_courtyard_records.extend(summarize_per_courtyard(
            f_id,
            [ident for ident in (_courtyard_id(court) for court in plan_dict.get("courtyards", [])) if ident],
            point_to_courtyard,
            sim_result.daily_results,
            cell_area_m2=cell_area,
        ))

        # Add to comparison records
        cat_order = [("all", "全體開放空間")] + [(k, CATEGORY_LABELS[k]) for k in CATEGORY_ORDER]
        sp_m = daily_stats_by_cat["2026-03-21"]
        su_m = daily_stats_by_cat["2026-06-21"]
        wi_m = daily_stats_by_cat["2026-12-21"]

        for cat_k, cat_label in cat_order:
            if cat_k in sp_m:
                comparison_records.append({
                    "fabric_id": f_id,
                    "fabric_name_zh": f_name_zh,
                    "category": cat_label,
                    "category_key": cat_k,
                    "points": sp_m[cat_k]["point_count"],
                    "area_m2": sp_m[cat_k]["area_m2"],
                    "spring_mean": sp_m[cat_k]["mean_hours"],
                    "spring_ge_2h_pct": sp_m[cat_k]["pct_ge_2h"],
                    "summer_mean": su_m[cat_k]["mean_hours"],
                    "summer_ge_2h_pct": su_m[cat_k]["pct_ge_2h"],
                    "winter_mean": wi_m[cat_k]["mean_hours"],
                    "winter_ge_2h_pct": wi_m[cat_k]["pct_ge_2h"],
                })

        fabric_summaries[f_id] = {
            "fabric_id": f_id,
            "fabric_name_zh": f_name_zh,
            "plan_path": str(plan_path),
            "plan_sha256": sha256_file(plan_path),
            "building_obstacles_count": len(bldg_obs),
            "sensor_points_count": len(sensors),
            "simulation_duration_s": round(sim_duration_s, 2),
            "total_execution_duration_s": round(time.time() - t_fab_start, 2),
            "daily_metrics": daily_stats_by_cat,
        }

    # 5. Output Comparison Table (CSV, Markdown, JSON, Graphic PNG)
    csv_path = output_dir / "comparison_table.csv"
    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write("紋理方案代碼,紋理方案名稱,開放空間類別,有效網格點數,代表面積_m2,春分平均日照_小時,春分日照大於等於2小時比例_百分比,夏至平均日照_小時,夏至日照大於等於2小時比例_百分比,冬至平均日照_小時,冬至日照大於等於2小時比例_百分比\n")
        for r in comparison_records:
            f.write(
                f"{r['fabric_id']},{r['fabric_name_zh']},{r['category']},{r['points']},{r['area_m2']:.1f},"
                f"{r['spring_mean']:.3f},{r['spring_ge_2h_pct']:.2f},"
                f"{r['summer_mean']:.3f},{r['summer_ge_2h_pct']:.2f},"
                f"{r['winter_mean']:.3f},{r['winter_ge_2h_pct']:.2f}\n"
            )

    json_path = output_dir / "comparison_table.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(comparison_records, f, ensure_ascii=False, indent=2)

    md_path = output_dir / "comparison_table.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 鹿特丹 M4H 港區活化 ｜ 四個紋理方案開放空間日照時數綜合比較\n\n")
        f.write("> **標籤**：探索性分析（非正式法定審批依據）  \n")
        f.write(f"> **計算設定**：網格間距 {actual_spacing:.1f} m、感測高度 0.5 m、時段 08:00–18:00、15 分鐘取樣、周邊 300 m 脈絡建築遮擋  \n")
        f.write("> **範圍**：「全體開放空間」＝基地內全部未建土地（公園／綠軸、水岸帶、街道、街廓中庭、街廓內其他空地、設備院與其他空地），建築覆蓋面積不計。2026-10-17 起納入中庭與街廓內空地（先前版本只算前三類）。  \n\n")
        f.write("| 紋理方案 | 開放空間類別 | 網格點數 | 面積 (m²) | 春分平均 (h) | 春分 ≥2h (%) | 夏至平均 (h) | 夏至 ≥2h (%) | 冬至平均 (h) | 冬至 ≥2h (%) |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for r in comparison_records:
            bold = "**" if r["category"] == "全體開放空間" else ""
            f.write(
                f"| {bold}{r['fabric_name_zh']}{bold} | {r['category']} | {r['points']:,} | {r['area_m2']:,.0f} | "
                f"{bold}{r['spring_mean']:.2f}{bold} | {bold}{r['spring_ge_2h_pct']:.1f}%{bold} | "
                f"{r['summer_mean']:.2f} | {r['summer_ge_2h_pct']:.1f}% | "
                f"{bold}{r['winter_mean']:.2f}{bold} | {bold}{r['winter_ge_2h_pct']:.1f}%{bold} |\n"
            )

    summary_png_path = output_dir / "comparison_summary_zh.png"
    render_comparison_summary_graphic(comparison_records, summary_png_path)
    generated_pngs.append(summary_png_path)
    per_courtyard_path = write_per_courtyard_json(output_dir, per_courtyard_records)
    print(f"\n比較表輸出完成: {csv_path.name}, {md_path.name}, {json_path.name}, {summary_png_path.name}")

    # 6. Output Manifest
    total_duration_all = time.time() - start_time_all
    manifest_data = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task": "E1 逐案日照：四個紋理方案的開放空間日照時數",
        "fixture_tag": "EXPLORATORY_ANALYSIS_NOT_FORMAL_DECISION",
        "engine": {
            "engine_name": "ladybug-sunpath+ladybug-radiance",
            "radiance_version": rad_status.version,
            "radiance_verified": rad_status.available,
            "rtrace_executable": str(Path.home() / ".local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin/rtrace"),
        },
        "parameters": {
            "grid_spacing_m": actual_spacing,
            "sensor_elevation_m": 0.5,
            "surface_offset_m": 0.05,
            "analysis_dates": [d.isoformat() for d in ANALYSIS_DATES],
            "daily_time_window": "08:00-18:00",
            "sampling_timestep_per_hour": 4,
            "sampling_interval_minutes": 15,
            "location": {
                "name": "Rotterdam M4H StudyArea v5",
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "timezone": loc.timezone,
            },
            "true_north_grid_convergence_deg": gamma,
            "context_buffer_m": CONTEXT_BUFFER_M,
            "context_height_assumptions": (
                "以 ~/.local/share/urban-design-data/context/context-20260927T153054Z/buildings.geojson 為遮擋來源；"
                "有 height_m 欄位即直接採用；無高度欄位之建築採用荷蘭標準低中層脈絡高度假設 12.0 m（參考周邊已知建築中位數 11.5 m）。"
            ),
        },
        "sources": {
            "fabrics": {
                f_id: {
                    "path": str(Path(f"artifacts/fab1/run-8/{f_id}-plan.json")),
                    "sha256": sha256_file(Path(f"artifacts/fab1/run-8/{f_id}-plan.json")),
                }
                for f_id in fabrics
            },
            "context_buildings": ctx_meta,
        },
        "fabric_summaries": fabric_summaries,
        "total_runtime_seconds": round(total_duration_all, 2),
        "output_artifacts": {
            p.name: {
                "path": str(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }
            for p in [csv_path, json_path, md_path, per_courtyard_path] + generated_pngs
        },
    }

    if buildings_override_path is not None:
        manifest_data["sources"]["buildings_override"] = {
            "path": str(buildings_override_path),
            "sha256": sha256_file(buildings_override_path),
        }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    print(f"Manifest 產出完成: {manifest_path.name}")
    print(f"=== E1 紋理方案日照分析全流程完成！總耗時: {total_duration_all:.2f} 秒 ===")

    return manifest_data


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="E1 Fabric Open Space Sunlight Simulation")
    parser.add_argument("--spacing", type=float, default=5.0, help="Grid spacing in metres (default: 5.0)")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/w8/e1-fabric"), help="Output directory")
    parser.add_argument("--source-dir", type=Path, help="Existing E1 result directory; required for --language en")
    parser.add_argument("--language", choices=("zh", "en"), default="zh", help="Figure language (English renders existing results only)")
    parser.add_argument("--fabrics", nargs="+", choices=FABRICS, default=FABRICS, help="Fabrics to simulate")
    parser.add_argument(
        "--buildings-override",
        type=Path,
        help="JSON formal-draft response or editable_buildings list; only valid with --fabrics harbour_grain",
    )
    parser.add_argument("--quick", action="store_true", help="Quick run with 20m spacing for verification")
    args = parser.parse_args(argv)

    if args.language == "en":
        if args.source_dir is None:
            parser.error("--source-dir is required for --language en")
        if args.buildings_override is not None or args.quick:
            parser.error("--language en only renders registered existing result figures")
        render_existing_english_figures(args.source_dir, args.output_dir, args.fabrics)
        return

    try:
        _validate_fabric_selection(args.fabrics, args.buildings_override)
    except ValueError as exc:
        parser.error(str(exc))

    run_fabric_sunlight_pipeline(
        fabrics=args.fabrics,
        spacing_m=args.spacing,
        output_dir=args.output_dir,
        quick=args.quick,
        buildings_override_path=args.buildings_override,
    )


if __name__ == "__main__":
    main()
