#!/usr/bin/env python3
"""Outdoor Thermal Comfort (UTCI) Simulation for Four Urban Fabric Scenarios in Rotterdam M4H.

Calculates hourly Universal Thermal Climate Index (UTCI) from 10:00 to 17:00 on the peak summer day
for public open spaces (parks, waterfront, roads) across four fabric schemes:
- harbour_grain (Founder selected scheme)
- closed_block_extension
- courtyard_islands
- landscape_figure

Uses:
- Verified Radiance 6.0.2 via Ladybug Radiance for Sky View Factor (145 Tregenza patches) and solar obstruction.
- Ladybug Comfort SolarCal outdoor_sky_heat_exch for Mean Radiant Temperature (MRT).
- Ladybug Comfort UTCI polynomial for thermal comfort indices.
- Logarithmic wind profile conversion to pedestrian height (1.1 m) with urban roughness.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time as time_mod
import types
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Prevent src/urban_design/__init__.py from importing unavailable server packages (pyproj, fastapi)
if "urban_design" not in sys.modules:
    pkg = types.ModuleType("urban_design")
    pkg.__path__ = ["src/urban_design"]
    sys.modules["urban_design"] = pkg

from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from ladybug.epw import EPW
from ladybug.location import Location
from ladybug.sunpath import Sunpath
from ladybug_geometry.geometry3d import Face3D, Point3D, Vector3D
import ladybug_radiance.intersection as rad_intersection
try:
    from ladybug_comfort import solarcal, utci
except ModuleNotFoundError as exc:
    if not (exc.name or "").startswith("ladybug_comfort"):
        raise
    solarcal = None
    utci = None

from urban_design.environment.contracts import Obstacle, SensorPoint
from urban_design.environment.geometry_adapter import _hash_faces, footprint_to_obstacle
from urban_design.environment.sensors import generate_ground_sensor_grid
from urban_design.environment.sunlight import (
    box_to_face3d_list,
    configure_radiance_runtime,
    verify_radiance_runtime,
)

# --- Configuration & Paths ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EPW_PATH = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/w5-weather-derived-method-proposal-20260926T115309Z/candidate-01/derived-minute60.epw")
DEFAULT_CONTEXT_BUILDINGS = Path.home() / ".local/share/urban-design-data/context/context-20260927T153054Z/buildings.geojson"
DEFAULT_CONTEXT_WATER = Path.home() / ".local/share/urban-design-data/context/context-20260927T153054Z/water.geojson"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "w8" / "utci"

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

FABRIC_NAMES_EN = {
    "harbour_grain": "Harbour grain",
    "closed_block_extension": "Closed-block extension",
    "courtyard_islands": "Courtyard islands",
    "landscape_figure": "Landscape as figure",
}

FABRIC_DESCRIPTIONS_ZH = {
    "harbour_grain": "Founder 選定方案；以長條街廓呼應碼頭作業軸線",
    "closed_block_extension": "延伸周邊既有圍合街廓網絡與內部街坊維護空間",
    "courtyard_islands": "大型院落島嶼街廓，內部形成大型共用開敞空間",
    "landscape_figure": "以連續綠地景為底圖，建物作為離散散點配置",
}

CATEGORY_NAMES_ZH = {
    "parks": "公園與廣場",
    "waterfront": "水岸公共帶",
    "roads": "街道路權",
    "courtyards": "街廓中庭",
    "blocks": "街廓內其他空地",
    "service": "設備院與其他空地",
    "total": "全體開放空間",
}
CATEGORY_NAMES_EN = {
    "parks": "Parks and plazas",
    "waterfront": "Waterfront public realm",
    "roads": "Streets and road right-of-way",
    "courtyards": "Block courtyards",
    "blocks": "Other block open land",
    "service": "Service yards and other open land",
    "total": "All open space",
}
# Classification priority; "total" = all unbuilt land on site (building footprints excluded).
CATEGORY_ORDER = ("parks", "waterfront", "roads", "courtyards", "blocks", "service")

# Physical & Meteorological Assumptions
URBAN_ROUGHNESS_Z0 = 0.5       # Metres (Davenport-Wieringa class 6 / suburban-urban roughness)
REFERENCE_HEIGHT_Z10 = 10.0    # Metres (EPW wind speed measurement height)
SENSOR_HEIGHT_Z1_1 = 1.1       # Metres (Pedestrian center of gravity height)
SURFACE_OFFSET_M = 0.05        # Metres (Ray offset to prevent self-intersection)
FLOOR_REFLECTANCE = 0.25       # Ladybug default (characteristic of grass, soil, asphalt mix)
HUMAN_POSTURE = "standing"     # Ladybug default
SOLAR_SHARP_DEG = 135.0        # Ladybug default (relative solar-body orientation angle)
BODY_ABSORPTIVITY = 0.7        # Ladybug default (average skin and clothing shortwave absorptivity)
BODY_EMISSIVITY = 0.95         # Ladybug default (human body longwave emissivity)
CONTEXT_BUFFER_M = 300.0       # Metres
CONTEXT_ASSUMED_HEIGHT_M = 12.0  # Metres (Dutch 4-storey block median)

# UTCI Thermal Stress Categories (International Standard)
UTCI_CATEGORIES = [
    {"id": "no_stress", "label_zh": "無熱壓力", "min_c": -float("inf"), "max_c": 26.0, "color": "#2a9d8f", "range_zh": "≤ 26 °C"},
    {"id": "moderate", "label_zh": "中度熱壓力", "min_c": 26.0, "max_c": 32.0, "color": "#e9c46a", "range_zh": "26 – 32 °C"},
    {"id": "strong", "label_zh": "強烈熱壓力", "min_c": 32.0, "max_c": 38.0, "color": "#f4a261", "range_zh": "32 – 38 °C"},
    {"id": "very_strong", "label_zh": "非常強烈熱壓力", "min_c": 38.0, "max_c": 46.0, "color": "#e76f51", "range_zh": "38 – 46 °C"},
    {"id": "extreme", "label_zh": "極度熱壓力", "min_c": 46.0, "max_c": float("inf"), "color": "#7209b7", "range_zh": "> 46 °C"},
]

UTCI_LABELS_EN = {
    "無熱壓力 (≤ 26 °C)": "No thermal stress (≤ 26 °C)",
    "中度熱壓力 (26 – 32 °C)": "Moderate (26 – 32 °C)",
    "強烈熱壓力 (32 – 38 °C)": "Strong (32 – 38 °C)",
    "非常強烈熱壓力 (38 – 46 °C)": "Very strong (38 – 46 °C)",
    "極度熱壓力 (> 46 °C)": "Extreme heat stress (> 46 °C)",
}



_RADIANCE_SIM_FOLDER: str | None = None


def _radiance_sim_folder() -> str:
    """Per-process Radiance working folder. ladybug_radiance defaults to the shared system temp dir with
    fixed file names (scene.oct …), so two concurrent runs corrupt each other's octree."""
    global _RADIANCE_SIM_FOLDER
    if _RADIANCE_SIM_FOLDER is None:
        import atexit, shutil, tempfile
        _RADIANCE_SIM_FOLDER = tempfile.mkdtemp(prefix="urban-design-radiance-")
        atexit.register(shutil.rmtree, _RADIANCE_SIM_FOLDER, True)
    return _RADIANCE_SIM_FOLDER

def classify_utci(val: float) -> str:
    """Classify UTCI temperature value into category ID."""
    if val <= 26.0:
        return "no_stress"
    elif val <= 32.0:
        return "moderate"
    elif val <= 38.0:
        return "strong"
    elif val <= 46.0:
        return "very_strong"
    else:
        return "extreme"


def get_utci_color(val: float) -> str:
    """Return hex color for UTCI value based on standard stress level."""
    for cat in UTCI_CATEGORIES:
        if cat["min_c"] < val <= cat["max_c"]:
            return cat["color"]
    return UTCI_CATEGORIES[0]["color"]


def sha256_file(path: Path) -> str:
    """Compute SHA-256 digest of a file."""
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
        buildings = editor.get("editable_buildings") if isinstance(editor, dict) else None
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


# --- Geometry & Ear-clipping Obstacle Handling ---
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

    open_space_by_category: dict[str, list[Polygon]] = {k: [] for k in CATEGORY_ORDER}
    # Courtyards and other unbuilt block land are open land too (footprints removed by the grid);
    # open retained-building parcels (e.g. demolished #5) count with service yards.
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


def load_context_water(water_geojson_path: Path, site_poly: Polygon, buffer_m: float = 800.0) -> List[Polygon]:
    """Load water geometries around the site for background cartographic rendering."""
    if not water_geojson_path.is_file():
        return []
    with open(water_geojson_path, encoding="utf-8") as f:
        data = json.load(f)
    buf_poly = site_poly.buffer(buffer_m)
    water_polys: list[Polygon] = []
    for feat in data.get("features", []):
        geom = feat.get("geometry")
        if not geom:
            continue
        s = shape(geom)
        if not s.intersects(buf_poly):
            continue
        if not s.is_valid:
            s = make_valid(s)
        polys = (
            [s]
            if isinstance(s, Polygon)
            else [g for g in s.geoms if isinstance(g, Polygon)]
            if hasattr(s, "geoms")
            else []
        )
        for p in polys:
            if not p.is_empty:
                water_polys.append(p)
    return water_polys


# --- Weather Extraction & Solar Analysis ---
def find_hottest_summer_day(epw_path: Path) -> Dict[str, Any]:
    """Identify the hottest summer day (June-August daily mean dry-bulb temperature highest)."""
    epw = EPW(str(epw_path))
    db_temps = epw.dry_bulb_temperature
    datetimes = db_temps.datetimes

    daily_temps: dict[tuple[int, int, int], list[float]] = {}
    for dt, temp in zip(datetimes, db_temps):
        if dt.month in (6, 7, 8):
            d = (dt.year, dt.month, dt.day)
            daily_temps.setdefault(d, []).append(temp)

    avg_daily = {d: sum(vals) / len(vals) for d, vals in daily_temps.items()}
    sorted_days = sorted(avg_daily.items(), key=lambda x: x[1], reverse=True)
    hottest_key, hottest_mean = sorted_days[0]
    hottest_year, hottest_month, hottest_day = hottest_key

    # Extract hourly metrics for 10:00 - 17:00
    hourly_data = {}
    for i, dt in enumerate(datetimes):
        if dt.year == hottest_year and dt.month == hottest_month and dt.day == hottest_day:
            if 10 <= dt.hour <= 17:
                hourly_data[dt.hour] = {
                    "hour": dt.hour,
                    "dry_bulb_c": float(epw.dry_bulb_temperature[i]),
                    "relative_humidity_pct": float(epw.relative_humidity[i]),
                    "wind_speed_10m": float(epw.wind_speed[i]),
                    "dni_w_m2": float(epw.direct_normal_radiation[i]),
                    "dhi_w_m2": float(epw.diffuse_horizontal_radiation[i]),
                    "ghi_w_m2": float(epw.global_horizontal_radiation[i]),
                    "horiz_ir_w_m2": float(epw.horizontal_infrared_radiation_intensity[i]),
                }

    return {
        "date_str": f"{hottest_year:04d}-{hottest_month:02d}-{hottest_day:02d}",
        "year": hottest_year,
        "month": hottest_month,
        "day": hottest_day,
        "mean_daily_temp_c": round(hottest_mean, 2),
        "max_daily_temp_c": round(max(daily_temps[hottest_key]), 2),
        "min_daily_temp_c": round(min(daily_temps[hottest_key]), 2),
        "epw_location": {
            "city": epw.location.city,
            "country": epw.location.country,
            "latitude": epw.location.latitude,
            "longitude": epw.location.longitude,
            "time_zone": epw.location.time_zone,
            "elevation": epw.location.elevation,
        },
        "hourly_data": hourly_data,
    }


def compute_log_wind_1_1m(wind_10m: float, z0: float = URBAN_ROUGHNESS_Z0) -> float:
    """Convert 10 m meteorological wind speed to pedestrian level (1.1 m) using logarithmic law."""
    ratio = math.log(SENSOR_HEIGHT_Z1_1 / z0) / math.log(REFERENCE_HEIGHT_Z10 / z0)
    v1_1 = wind_10m * ratio
    return max(0.5, v1_1)  # UTCI polynomial valid range lower limit


def generate_sun_vectors_for_day(
    lat: float,
    lon: float,
    month: int,
    day: int,
    hours: Sequence[int],
    meridian_convergence_deg: float = -0.753,
) -> Dict[int, Dict[str, Any]]:
    """Generate sun vectors and solar angles for the specified hours aligned to Grid North."""
    loc = Location(city="Rotterdam", country="Netherlands", latitude=lat, longitude=lon, time_zone=1.0)
    sp = Sunpath.from_location(loc)

    rot_rad = -math.radians(meridian_convergence_deg)
    cos_rot = math.cos(rot_rad)
    sin_rot = math.sin(rot_rad)

    sun_dict = {}
    for h in hours:
        sun = sp.calculate_sun(month=month, day=day, hour=h, is_solar_time=False)
        if sun.altitude > 0:
            raw_vx = -sun.sun_vector.x
            raw_vy = -sun.sun_vector.y
            raw_vz = -sun.sun_vector.z

            adj_vx = raw_vx * cos_rot + raw_vy * sin_rot
            adj_vy = raw_vy * cos_rot - raw_vx * sin_rot
            adj_vz = raw_vz
            adj_azimuth = (sun.azimuth - meridian_convergence_deg) % 360.0

            vec_towards_sun = Vector3D(adj_vx, adj_vy, adj_vz).normalize()
            sun_dict[h] = {
                "vector": vec_towards_sun,
                "altitude_deg": sun.altitude,
                "azimuth_deg": adj_azimuth,
            }
        else:
            sun_dict[h] = {
                "vector": Vector3D(0, 0, 1),
                "altitude_deg": 0.0,
                "azimuth_deg": 0.0,
            }
    return sun_dict


# --- Sensor Grid Generation ---
def generate_categorized_sensor_grid(
    category_unions: Dict[str, Polygon],
    building_footprints: List[Polygon],
    spacing_m: float = 5.0,
    elevation: float = SENSOR_HEIGHT_Z1_1,
    surface_offset: float = SURFACE_OFFSET_M,
) -> Tuple[List[SensorPoint], Dict[str, str]]:
    """Generate regular grid points across open space categories and map each point to its category."""
    all_open_space = unary_union(list(category_unions.values()))
    raw_points = generate_ground_sensor_grid(
        boundary=all_open_space,
        spacing_m=spacing_m,
        origin=(0.0, 0.0),
        elevation=elevation,
        surface_offset=surface_offset,
        building_footprints=building_footprints,
    )

    valid_points = [p for p in raw_points if p.status == "VALID"]
    point_to_cat: dict[str, str] = {}

    for pt in valid_points:
        p_geom = Point(pt.coordinates[0], pt.coordinates[1])
        assigned_cat = None
        for cat in CATEGORY_ORDER:
            cat_poly = category_unions.get(cat)
            if cat_poly and not cat_poly.is_empty and cat_poly.covers(p_geom):
                assigned_cat = cat
                break
        if assigned_cat is None:
            assigned_cat = "roads"
            min_dist = float("inf")
            for cat in CATEGORY_ORDER:
                cat_poly = category_unions.get(cat)
                if cat_poly and not cat_poly.is_empty:
                    d = cat_poly.distance(p_geom)
                    if d < min_dist:
                        min_dist = d
                        assigned_cat = cat
        point_to_cat[pt.point_id] = assigned_cat

    return valid_points, point_to_cat


# --- Simulation Core ---
def simulate_fabric_utci(
    fabric_id: str,
    plan_path: Path,
    context_obstacles: List[Obstacle],
    weather_info: Dict[str, Any],
    spacing_m: float = 5.0,
    target_hour: int = 14,
    buildings_override_path: Path | None = None,
) -> Dict[str, Any]:
    """Run full UTCI simulation for one urban fabric scheme across 10:00-17:00."""
    start_time = time_mod.time()

    # 1. Load fabric plan
    plan, bldg_obs, bldg_footprints, cat_unions, site_poly = load_fabric_plan(
        plan_path, buildings_override_path=buildings_override_path
    )

    # 2. Combine 3D context faces
    context_faces: list[Face3D] = []
    for obs in bldg_obs:
        if obs.faces:
            for face_pts in obs.faces:
                context_faces.append(Face3D([Point3D(*p) for p in face_pts]))
    for obs in context_obstacles:
        if obs.faces:
            for face_pts in obs.faces:
                context_faces.append(Face3D([Point3D(*p) for p in face_pts]))

    # 3. Generate sensor points
    valid_points, point_to_cat = generate_categorized_sensor_grid(
        category_unions=cat_unions,
        building_footprints=bldg_footprints,
        spacing_m=spacing_m,
        elevation=SENSOR_HEIGHT_Z1_1,
        surface_offset=SURFACE_OFFSET_M,
    )
    n_pts = len(valid_points)
    if n_pts == 0:
        raise RuntimeError(f"No valid sensor points generated for {fabric_id} with spacing {spacing_m}m")

    lb_pts = [Point3D(*p.coordinates) for p in valid_points]
    lb_norms = [Vector3D(0, 0, 1) for _ in valid_points]

    # 4. Radiance Sky View Factor (SVF) calculation (145 Tregenza sky dome patches)
    sky_vecs = rad_intersection.view_sphere.tregenza_dome_vectors
    sky_solid_angles = rad_intersection.view_sphere.tregenza_solid_angles
    total_hemisphere_sa = 2.0 * math.pi

    t_svf_0 = time_mod.time()
    svf_batch_size = 512
    svf_mtx: list[list[bool]] = []
    for b_start in range(0, n_pts, svf_batch_size):
        b_pts = lb_pts[b_start : b_start + svf_batch_size]
        b_norms = lb_norms[b_start : b_start + svf_batch_size]
        batch_res = rad_intersection.intersection_matrix(
            vectors=sky_vecs,
            points=b_pts,
            normals=b_norms,
            context_geometry=context_faces,
            offset_distance=SURFACE_OFFSET_M,
            numericalize=False,
            sim_folder=_radiance_sim_folder(),
        )
        svf_mtx.extend(batch_res)
    t_svf_1 = time_mod.time()

    # Compute SVF per point
    point_svf: list[float] = []
    for row in svf_mtx:
        vis_sa = sum(sky_solid_angles[i] for i, vis in enumerate(row) if bool(vis))
        svf_val = min(1.0, max(0.0, vis_sa / total_hemisphere_sa))
        point_svf.append(round(svf_val, 4))

    # 5. Radiance Sun Obstruction calculation for hours 10:00 to 17:00
    hours = list(range(10, 18))
    lat = weather_info["epw_location"]["latitude"]
    lon = weather_info["epw_location"]["longitude"]
    sun_info = generate_sun_vectors_for_day(
        lat=lat,
        lon=lon,
        month=weather_info["month"],
        day=weather_info["day"],
        hours=hours,
        meridian_convergence_deg=-0.753,
    )
    sun_vectors = [sun_info[h]["vector"] for h in hours]

    t_sun_0 = time_mod.time()
    sun_mtx: list[list[bool]] = []
    for b_start in range(0, n_pts, svf_batch_size):
        b_pts = lb_pts[b_start : b_start + svf_batch_size]
        b_norms = lb_norms[b_start : b_start + svf_batch_size]
        batch_res = rad_intersection.intersection_matrix(
            vectors=sun_vectors,
            points=b_pts,
            normals=b_norms,
            context_geometry=context_faces,
            offset_distance=SURFACE_OFFSET_M,
            numericalize=False,
            sim_folder=_radiance_sim_folder(),
        )
        sun_mtx.extend(batch_res)
    t_sun_1 = time_mod.time()

    # 6. Hourly MRT and UTCI calculation
    point_results = []
    hourly_category_stats: dict[int, dict[str, Any]] = {}
    hourly_overall_stats: dict[int, dict[str, Any]] = {}

    # Structure to hold all hourly results
    # sensor_hourly_utci[pt_idx][h] = utci_val
    sensor_hourly_utci: list[dict[int, float]] = [{} for _ in range(n_pts)]
    sensor_hourly_mrt: list[dict[int, float]] = [{} for _ in range(n_pts)]

    hourly_weather = weather_info["hourly_data"]

    for h_idx, h in enumerate(hours):
        w = hourly_weather[h]
        ta = w["dry_bulb_c"]
        rh = w["relative_humidity_pct"]
        ws10 = w["wind_speed_10m"]
        dni = w["dni_w_m2"]
        dhi = w["dhi_w_m2"]
        horiz_ir = w["horiz_ir_w_m2"]
        alt = sun_info[h]["altitude_deg"]
        v1_1 = compute_log_wind_1_1m(ws10, URBAN_ROUGHNESS_Z0)

        h_utcis = []
        h_mrts = []

        for pt_idx in range(n_pts):
            svf_val = point_svf[pt_idx]
            sun_vis = bool(sun_mtx[pt_idx][h_idx])
            fract_exposed = 1.0 if sun_vis and alt > 0 else 0.0

            heat_res = solarcal.outdoor_sky_heat_exch(
                srfs_temp=ta,
                horiz_ir=horiz_ir,
                diff_horiz_solar=dhi,
                dir_normal_solar=dni,
                alt=alt,
                sky_exposure=svf_val,
                fract_exposed=fract_exposed,
                floor_reflectance=FLOOR_REFLECTANCE,
                posture=HUMAN_POSTURE,
                sharp=SOLAR_SHARP_DEG,
                body_absorptivity=BODY_ABSORPTIVITY,
                body_emissivity=BODY_EMISSIVITY,
            )
            mrt_val = heat_res["mrt"]
            utci_val = utci.universal_thermal_climate_index(ta, mrt_val, v1_1, rh)

            sensor_hourly_utci[pt_idx][h] = round(utci_val, 2)
            sensor_hourly_mrt[pt_idx][h] = round(mrt_val, 2)
            h_utcis.append(utci_val)
            h_mrts.append(mrt_val)

        hourly_overall_stats[h] = {
            "hour": h,
            "ta_c": ta,
            "rh_pct": rh,
            "v1_1_m_s": round(v1_1, 2),
            "mean_mrt_c": round(sum(h_mrts) / len(h_mrts), 2),
            "mean_utci_c": round(sum(h_utcis) / len(h_utcis), 2),
            "max_utci_c": round(max(h_utcis), 2),
            "min_utci_c": round(min(h_utcis), 2),
        }

    # 7. Aggregate Stress Hours Proportions across 10:00 - 17:00
    # Categories: parks, waterfront, roads, total
    cat_points_map: dict[str, list[int]] = {k: [] for k in CATEGORY_ORDER}
    cat_points_map["total"] = list(range(n_pts))
    for pt_idx, pt in enumerate(valid_points):
        c = point_to_cat[pt.point_id]
        cat_points_map[c].append(pt_idx)

    stress_table = {}
    for cat_key, idx_list in cat_points_map.items():
        n_cat_pts = len(idx_list)
        total_sensor_hours = n_cat_pts * len(hours)
        if total_sensor_hours == 0:
            stress_table[cat_key] = {
                "category_zh": CATEGORY_NAMES_ZH.get(cat_key, cat_key),
                "sensor_count": 0,
                "area_m2": 0.0,
                "total_sensor_hours": 0,
                "no_stress_pct": 0.0,
                "moderate_pct": 0.0,
                "strong_pct": 0.0,
                "very_strong_pct": 0.0,
                "extreme_pct": 0.0,
                "heat_stress_pct": 0.0,
                "strong_plus_pct": 0.0,
                "mean_utci_c": 0.0,
                "max_utci_c": 0.0,
                "mean_mrt_c": 0.0,
                "mean_svf": 0.0,
            }
            continue

        stress_counts = {cat["id"]: 0 for cat in UTCI_CATEGORIES}
        all_utcis = []
        all_mrts = []
        all_svfs = [point_svf[i] for i in idx_list]

        for i in idx_list:
            for h in hours:
                u = sensor_hourly_utci[i][h]
                all_utcis.append(u)
                all_mrts.append(sensor_hourly_mrt[i][h])
                c_id = classify_utci(u)
                stress_counts[c_id] += 1

        heat_stress_hours = sum(stress_counts[cid] for cid in ("moderate", "strong", "very_strong", "extreme"))
        strong_plus_hours = sum(stress_counts[cid] for cid in ("strong", "very_strong", "extreme"))

        stress_table[cat_key] = {
            "category_zh": CATEGORY_NAMES_ZH.get(cat_key, cat_key),
            "sensor_count": n_cat_pts,
            "area_m2": round(n_cat_pts * (spacing_m**2), 1),
            "total_sensor_hours": total_sensor_hours,
            "no_stress_hours": stress_counts["no_stress"],
            "no_stress_pct": round(stress_counts["no_stress"] / total_sensor_hours * 100.0, 1),
            "moderate_hours": stress_counts["moderate"],
            "moderate_pct": round(stress_counts["moderate"] / total_sensor_hours * 100.0, 1),
            "strong_hours": stress_counts["strong"],
            "strong_pct": round(stress_counts["strong"] / total_sensor_hours * 100.0, 1),
            "very_strong_hours": stress_counts["very_strong"],
            "very_strong_pct": round(stress_counts["very_strong"] / total_sensor_hours * 100.0, 1),
            "extreme_hours": stress_counts["extreme"],
            "extreme_pct": round(stress_counts["extreme"] / total_sensor_hours * 100.0, 1),
            "heat_stress_hours": heat_stress_hours,
            "heat_stress_pct": round(heat_stress_hours / total_sensor_hours * 100.0, 1),
            "strong_plus_hours": strong_plus_hours,
            "strong_plus_pct": round(strong_plus_hours / total_sensor_hours * 100.0, 1),
            "mean_utci_c": round(sum(all_utcis) / len(all_utcis), 2),
            "max_utci_c": round(max(all_utcis), 2),
            "mean_mrt_c": round(sum(all_mrts) / len(all_mrts), 2),
            "mean_svf": round(sum(all_svfs) / len(all_svfs), 3),
        }

    # 8. Sensor-level results at target peak hour (14:00)
    target_sensors = []
    for pt_idx, pt in enumerate(valid_points):
        target_sensors.append({
            "point_id": pt.point_id,
            "x": pt.coordinates[0],
            "y": pt.coordinates[1],
            "category": point_to_cat[pt.point_id],
            "svf": point_svf[pt_idx],
            "sun_exposed": bool(sun_mtx[pt_idx][hours.index(target_hour)]),
            "mrt_c": sensor_hourly_mrt[pt_idx][target_hour],
            "utci_c": sensor_hourly_utci[pt_idx][target_hour],
            "stress_category": classify_utci(sensor_hourly_utci[pt_idx][target_hour]),
        })

    elapsed_s = time_mod.time() - start_time

    return {
        "fabric_id": fabric_id,
        "fabric_name_zh": FABRIC_NAMES_ZH.get(fabric_id, fabric_id),
        "fabric_description_zh": FABRIC_DESCRIPTIONS_ZH.get(fabric_id, ""),
        "plan_path": str(plan_path),
        "grid_spacing_m": spacing_m,
        "total_sensor_count": n_pts,
        "elapsed_seconds": round(elapsed_s, 2),
        "radiance_svf_time_s": round(t_svf_1 - t_svf_0, 2),
        "radiance_sun_time_s": round(t_sun_1 - t_sun_0, 2),
        "target_hour": target_hour,
        "hourly_overall_stats": hourly_overall_stats,
        "stress_table": stress_table,
        "target_sensors": target_sensors,
        "site_polygon": site_poly,
        "building_footprints": bldg_footprints,
        "category_unions": cat_unions,
    }


# --- SVG Heatmap Generation ---
def generate_utci_svg(
    sim_data: Dict[str, Any],
    water_polys: List[Polygon],
    context_obstacles: List[Obstacle],
    output_path: Path,
) -> None:
    """Render an aesthetic, publication-grade SVG heatmap of UTCI for a scheme."""
    site_poly = sim_data["site_polygon"]
    bldg_footprints = sim_data["building_footprints"]
    sensors = sim_data["target_sensors"]
    fabric_id = sim_data["fabric_id"]
    name_zh = sim_data["fabric_name_zh"]
    grid_spacing = sim_data["grid_spacing_m"]
    target_hour = sim_data["target_hour"]

    # Calculate bounding box in projected meters
    all_x = [s["x"] for s in sensors]
    all_y = [s["y"] for s in sensors]
    min_x, max_x = min(all_x) - 40.0, max(all_x) + 40.0
    min_y, max_y = min(all_y) - 40.0, max(all_y) + 40.0

    # Include site boundary in bbox
    bx0, by0, bx1, by1 = site_poly.bounds
    min_x, max_x = min(min_x, bx0 - 30.0), max(max_x, bx1 + 30.0)
    min_y, max_y = min(min_y, by0 - 30.0), max(max_y, by1 + 30.0)

    # Canvas dimensions
    width_px = 1200
    world_w = max_x - min_x
    world_h = max_y - min_y
    scale = (width_px - 80) / world_w
    height_px = int(world_h * scale + 180)  # Extra room for title header and bottom legend

    def to_svg(x: float, y: float) -> Tuple[float, float]:
        # y is inverted in SVG
        sx = 40.0 + (x - min_x) * scale
        sy = 120.0 + (max_y - y) * scale
        return (round(sx, 1), round(sy, 1))

    svg_lines = []
    svg_lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_px} {height_px}" width="{width_px}" height="{height_px}" style="background-color: #f8f9fa; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', \'PingFang TC\', \'Hiragino Sans GB\', sans-serif;">')

    # Definitions (drop shadow, patterns)
    svg_lines.append("""
    <defs>
      <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">
        <feDropShadow dx="1" dy="2" stdDeviation="2" flood-opacity="0.15"/>
      </filter>
    </defs>
    """)

    # 1. Header (Title, Subtitle, Metadata)
    svg_lines.append(f'<rect x="0" y="0" width="{width_px}" height="100" fill="#1b263b" />')
    svg_lines.append(f'<text x="40" y="42" fill="#ffffff" font-size="24" font-weight="700">鹿特丹 M4H 夏季最熱日 {target_hour}:00 戶外熱舒適 UTCI 分佈圖</text>')
    sub_text = f"方案：{name_zh} ({fabric_id}) ｜ 氣象條件：2017-08-19 {target_hour}:00, Ta=32.1°C, RH=35%, 1.1m換算風速=1.32 m/s ｜ 網格解析度：{grid_spacing:.0f} m"
    svg_lines.append(f'<text x="40" y="74" fill="#cbd5e1" font-size="14">{sub_text}</text>')

    # 2. Water polygons (Maas & harbour basins)
    for wp in water_polys:
        clipped = wp.intersection(Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]))
        if not clipped.is_empty:
            geoms = [clipped] if isinstance(clipped, Polygon) else [g for g in clipped.geoms if isinstance(g, Polygon)]
            for g in geoms:
                coords = [f"{to_svg(x, y)[0]},{to_svg(x, y)[1]}" for x, y in g.exterior.coords]
                svg_lines.append(f'<polygon points="{" ".join(coords)}" fill="#cce3f0" stroke="#a2c4d9" stroke-width="1" />')

    # 3. Context Buildings (Surrounding buffer buildings)
    # Draw 2D footprints straight from the context layer (obstacle faces are triangulated
    # 3D meshes and rendered as shards), clipped to the map frame so nothing enters the header.
    frame = Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)])
    try:
        with open(DEFAULT_CONTEXT_BUILDINGS, encoding="utf-8") as fh:
            ctx_features = json.load(fh).get("features", [])
    except OSError:
        ctx_features = []
    for feat in ctx_features:
        try:
            geom = shape(feat["geometry"]).intersection(frame)
        except Exception:
            continue
        for g in (getattr(geom, "geoms", None) or [geom]):
            if g.is_empty or g.geom_type != "Polygon":
                continue
            screen_pts = [f"{to_svg(x, y)[0]},{to_svg(x, y)[1]}" for x, y in g.exterior.coords]
            svg_lines.append(f'<polygon points="{" ".join(screen_pts)}" fill="#e2e8f0" stroke="#cbd5e1" stroke-width="0.8" opacity="0.85" />')

    # 4. Site Boundary
    site_coords = [f"{to_svg(x, y)[0]},{to_svg(x, y)[1]}" for x, y in site_poly.exterior.coords]
    svg_lines.append(f'<polygon points="{" ".join(site_coords)}" fill="none" stroke="#64748b" stroke-width="2.0" stroke-dasharray="6,4" />')

    # 5. Open Space Sensor Grid (Heatmap tiles / points)
    half_tile = grid_spacing * scale * 0.52  # slight overlap to avoid white stitching
    for s in sensors:
        sx, sy = to_svg(s["x"], s["y"])
        c = get_utci_color(s["utci_c"])
        svg_lines.append(
            f'<rect x="{sx - half_tile:.1f}" y="{sy - half_tile:.1f}" width="{half_tile*2:.1f}" height="{half_tile*2:.1f}" '
            f'fill="{c}" opacity="0.92"><title>{s["category"]} ({s["point_id"]}): UTCI={s["utci_c"]}°C, MRT={s["mrt_c"]}°C, SVF={s["svf"]}</title></rect>'
        )

    # 6. Scheme Building Footprints (Foreground)
    for b_poly in bldg_footprints:
        b_coords = [f"{to_svg(x, y)[0]},{to_svg(x, y)[1]}" for x, y in b_poly.exterior.coords]
        svg_lines.append(f'<polygon points="{" ".join(b_coords)}" fill="#2d3748" stroke="#ffffff" stroke-width="1.2" filter="url(#shadow)" />')

    # 7. Cartographic Elements (North Arrow & Scale Bar)
    # North Arrow
    nx, ny = width_px - 80, 160
    svg_lines.append(f'<g transform="translate({nx},{ny})">')
    svg_lines.append('<circle cx="0" cy="0" r="22" fill="#ffffff" stroke="#94a3b8" stroke-width="1.5" />')
    svg_lines.append('<polygon points="0,-18 6,2 0,-2" fill="#e53e3e" />')
    svg_lines.append('<polygon points="0,-18 -6,2 0,-2" fill="#c53030" />')
    svg_lines.append('<polygon points="0,14 6,2 0,-2" fill="#718096" />')
    svg_lines.append('<polygon points="0,14 -6,2 0,-2" fill="#4a5568" />')
    svg_lines.append('<text x="0" y="-22" text-anchor="middle" font-size="12" font-weight="700" fill="#1a202c">N</text>')
    svg_lines.append('</g>')

    # Scale Bar (100m)
    bar_m = 100.0
    bar_px = bar_m * scale
    sb_x = width_px - 40 - bar_px  # right-aligned under the north arrow, clear of the legend
    sb_y = 200
    svg_lines.append(f'<g transform="translate({sb_x},{sb_y})">')
    svg_lines.append(f'<rect x="-8" y="-8" width="{bar_px + 16}" height="32" fill="#ffffff" opacity="0.85" />')
    svg_lines.append(f'<rect x="0" y="0" width="{bar_px}" height="5" fill="#1a202c" />')
    svg_lines.append(f'<rect x="{bar_px/2}" y="0" width="{bar_px/2}" height="5" fill="#ffffff" stroke="#1a202c" stroke-width="1" />')
    svg_lines.append('<text x="0" y="18" font-size="11" fill="#475569">0</text>')
    svg_lines.append(f'<text x="{bar_px/2}" y="18" text-anchor="middle" font-size="11" fill="#475569">50 m</text>')
    svg_lines.append(f'<text x="{bar_px}" y="18" text-anchor="end" font-size="11" fill="#475569">100 m</text>')
    svg_lines.append('</g>')

    # 8. Legend at bottom
    leg_y = height_px - 75
    svg_lines.append(f'<g transform="translate(40,{leg_y})">')
    svg_lines.append('<text x="0" y="-12" font-size="13" font-weight="700" fill="#1e293b">UTCI 戶外熱壓力分級（四案共用色階）：</text>')

    lx = 0
    for cat in UTCI_CATEGORIES:
        svg_lines.append(f'<rect x="{lx}" y="0" width="24" height="16" fill="{cat["color"]}" rx="3" stroke="#cbd5e1" stroke-width="0.5"/>')
        label_text = f'{cat["label_zh"]} ({cat["range_zh"]})'
        svg_lines.append(f'<text x="{lx + 30}" y="13" font-size="12" fill="#334155">{label_text}</text>')
        lx += len(label_text) * 9 + 45

    # 9. Disclaimer
    disc_text = "※ 探索性分析結果；風速由 10m EPW 依對數律換算至 1.1m (z0=0.5m)，未考慮微氣候風場建築遮蔽 (留待 E5)；地面反射率 0.25；人體為站姿。"
    svg_lines.append(f'<text x="0" y="38" font-size="11" fill="#64748b">{disc_text}</text>')
    svg_lines.append('</g>')

    svg_lines.append('</svg>')

    output_path.write_text("\n".join(svg_lines), encoding="utf-8")


def convert_svg_to_png(svg_path: Path, png_path: Path, size: int = 1400) -> bool:
    """Convert SVG to PNG at full size via headless Chromium; qlmanage (square thumbnail crop) is only a fallback."""
    renderer = Path(__file__).resolve().parent / "svg_to_png.py"
    chromium_python = "/Users/jackhsieh/.pyenv/versions/3.12.13/bin/python3"
    try:
        subprocess.run([chromium_python, str(renderer), str(svg_path), str(png_path)], check=True, capture_output=True, timeout=120)
        if png_path.exists():
            return True
    except Exception as exc:
        print(f"Warning: Chromium SVG render failed, falling back to qlmanage: {exc}", file=sys.stderr)
    try:
        cmd = ["qlmanage", "-t", "-s", str(size), "-o", str(png_path.parent), str(svg_path)]
        subprocess.run(cmd, capture_output=True, check=True)
        # qlmanage outputs <svg_path.name>.png
        ql_output = png_path.parent / f"{svg_path.name}.png"
        if ql_output.exists():
            if ql_output != png_path:
                ql_output.replace(png_path)
            return True
    except Exception as exc:
        print(f"Warning: qlmanage SVG to PNG conversion failed: {exc}", file=sys.stderr)
    return False


SVG_NS = "http://www.w3.org/2000/svg"


def _svg_text(element: ET.Element) -> str:
    return "".join(element.itertext())


def _translate_utci_label(text: str, fabric_id: str) -> str:
    title = re.fullmatch(r"鹿特丹 M4H 夏季最熱日 (\d{1,2}):00 戶外熱舒適 UTCI 分佈圖", text)
    if title:
        return f"Rotterdam M4H | Outdoor UTCI thermal comfort on the hottest summer day at {title.group(1)}:00"

    subtitle = re.fullmatch(r"方案：.*? \([a-z_]+\) ｜ 氣象條件：(.*?) ｜ 網格解析度：(.*)", text)
    if subtitle:
        weather = subtitle.group(1).replace("1.1m換算風速=", "wind at 1.1 m=")
        return f"Fabric: {FABRIC_NAMES_EN[fabric_id]} ({fabric_id}) | Weather: {weather} | Grid resolution: {subtitle.group(2)}"

    if text == "UTCI 戶外熱壓力分級（四案共用色階）：":
        return "UTCI outdoor thermal stress categories (shared scale for all four fabrics):"
    if text in UTCI_LABELS_EN:
        return UTCI_LABELS_EN[text]
    if text.startswith("※ 探索性分析結果；"):
        return (
            "Exploratory analysis. Wind speed is converted from 10 m EPW data to 1.1 m with a logarithmic profile "
            "(z0 = 0.5 m); building wind sheltering is not modelled (deferred to E5); ground reflectance 0.25; "
            "standing posture."
        )
    return text


def _rewrite_utci_svg_english(source_svg: Path, output_svg: Path, fabric_id: str) -> None:
    """Translate SVG annotations while retaining every source geometry, color, and result value."""
    ET.register_namespace("", SVG_NS)
    tree = ET.parse(source_svg)
    root = tree.getroot()
    style = root.attrib.get("style", "")
    root.set("style", style.replace("'PingFang TC', 'Hiragino Sans GB', sans-serif", "Arial, Helvetica, sans-serif"))

    defs = root.find(f"{{{SVG_NS}}}defs")
    background = ET.Element(
        f"{{{SVG_NS}}}rect",
        {
            "x": "0",
            "y": "0",
            "width": root.attrib.get("width", "1200"),
            "height": root.attrib.get("height", "1039"),
            "fill": "#f8f9fa",
        },
    )
    root.insert(list(root).index(defs) + 1 if defs is not None else 0, background)

    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "text":
            original = _svg_text(element)
            translated = _translate_utci_label(original, fabric_id)
            if translated != original:
                if list(element):
                    raise ValueError(f"Unexpected nested SVG text element in {source_svg}")
                element.text = translated
        elif tag == "title":
            title = _svg_text(element)
            for category_id, category_zh in CATEGORY_NAMES_ZH.items():
                title = title.replace(category_zh, CATEGORY_NAMES_EN[category_id])
            if title != _svg_text(element):
                element.text = title

    legend_title = "UTCI outdoor thermal stress categories (shared scale for all four fabrics):"
    legend = next((element for element in root.iter() if element.tag.endswith("text") and _svg_text(element) == legend_title), None)
    if legend is None:
        raise ValueError(f"UTCI legend title is missing from source SVG: {source_svg}")
    siblings = list(legend.getparent()) if hasattr(legend, "getparent") else None
    if siblings is None:
        parent = next((node for node in root.iter() if legend in list(node)), None)
        siblings = list(parent) if parent is not None else []
    if len(siblings) < 12:
        raise ValueError(f"UTCI legend layout is incomplete in source SVG: {source_svg}")

    cursor_x = 0.0
    for index, category in enumerate(UTCI_CATEGORIES):
        rect = siblings[1 + 2 * index]
        label = siblings[2 + 2 * index]
        translated = UTCI_LABELS_EN[f"{category['label_zh']} ({category['range_zh']})"]
        rect.set("x", str(round(cursor_x, 1)))
        label.set("x", str(round(cursor_x + 30.0, 1)))
        label.set("font-size", "10")
        cursor_x += max(150.0, len(translated) * 6.1 + 38.0)

    output_svg.parent.mkdir(parents=True, exist_ok=True)
    output_svg.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _render_svg_png_with_appkit(svg_path: Path, png_path: Path) -> None:
    """Rasterize an English SVG through local AppKit without launching a browser or service."""
    renderer_python = Path(sys.base_prefix) / "bin" / "python3"
    renderer = r'''
import sys
from AppKit import (
    NSBitmapImageRep, NSBitmapImageFileTypePNG, NSCalibratedRGBColorSpace,
    NSCompositingOperationCopy, NSGraphicsContext, NSImage, NSZeroRect,
)
from Foundation import NSMakeRect

source, target = sys.argv[1], sys.argv[2]
image = NSImage.alloc().initWithContentsOfFile_(source)
if image is None:
    raise RuntimeError(f"AppKit could not load SVG: {source}")
logical_size = image.size()
width, height = round(logical_size.width * 2), round(logical_size.height * 2)
bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, width, height, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0
)
context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(context)
image.drawInRect_fromRect_operation_fraction_(NSMakeRect(0, 0, width, height), NSZeroRect, NSCompositingOperationCopy, 1.0)
context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()
data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
if not data.writeToFile_atomically_(target, True):
    raise RuntimeError(f"AppKit could not write PNG: {target}")
'''
    png_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(svg_path)
    for element in tree.getroot().iter():
        # AppKit drops whole polygons when it encounters Chromium-only shadow filters.
        element.attrib.pop("filter", None)
    with tempfile.TemporaryDirectory(prefix="utci-en-render-") as temporary_dir:
        render_svg = Path(temporary_dir) / svg_path.name
        tree.write(render_svg, encoding="utf-8", xml_declaration=True)
        subprocess.run(
            [str(renderer_python), "-c", renderer, str(render_svg), str(png_path)],
            check=True,
            capture_output=True,
            timeout=120,
        )
    if not png_path.is_file():
        raise RuntimeError(f"AppKit did not create the PNG: {png_path}")


def render_existing_english_figures(source_dir: Path, output_dir: Path, fabrics: Sequence[str] = FABRICS) -> List[Path]:
    """Re-render the registered UTCI map SVGs in English without invoking climate tools."""
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"UTCI source manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("output_files", {})
    generated: List[Path] = []
    for fabric_id in fabrics:
        source_name = f"{fabric_id}_utci_1400.svg"
        source_svg = source_dir / source_name
        entry = entries.get(source_name)
        if not source_svg.is_file() or not isinstance(entry, dict) or not entry.get("sha256"):
            raise ValueError(f"UTCI SVG is missing or unregistered in its manifest: {source_name}")
        if sha256_file(source_svg) != entry["sha256"]:
            raise ValueError(f"UTCI SVG does not match its manifest: {source_name}")

        stem = f"{fabric_id}_utci_1400-en"
        svg_path = output_dir / f"{stem}.svg"
        png_path = output_dir / f"{stem}.png"
        _rewrite_utci_svg_english(source_svg, svg_path, fabric_id)
        _render_svg_png_with_appkit(svg_path, png_path)
        generated.extend((svg_path, png_path))
    return generated


# --- Comparison Table and Manifest Generation ---
def generate_markdown_table(
    all_results: Dict[str, Dict[str, Any]],
    weather_info: Dict[str, Any],
    fabrics: Sequence[str] = FABRICS,
) -> str:
    """Generate Markdown comparison table for heat stress hours proportion across fabrics and categories."""
    lines = []
    lines.append(f"# {len(fabrics)} 個紋理方案夏季開放空間 UTCI 熱舒適與熱壓力時數比例比較表\n")
    lines.append(f"**分析日期**：{weather_info['date_str']}（典型最熱夏日，日均溫 {weather_info['mean_daily_temp_c']:.2f} °C，日最高溫 {weather_info['max_daily_temp_c']:.2f} °C）  ")
    lines.append("**分析時段**：10:00 – 17:00 每小時（共 8 小時）  ")
    lines.append("**感測網格**：開放空間 5 m 網格，離地高度 1.1 m  ")
    lines.append("**重要說明**：*探索性分析；風速採都市粗糙度對數律換算，未考慮建物風場遮蔽（留待 E5 CFD）；地面反射率 0.25，人體參數為站姿。*\n")

    lines.append("## 1. 總體開放空間熱壓力指標比較 (10:00–17:00)\n")
    lines.append("| 方案名稱 | 方案代碼 | 開放空間面積 (m²) | 感測點數 | 平均 UTCI (°C) | 最高 UTCI (°C) | 平均 MRT (°C) | 平均 SVF | 熱壓力總時數比 (>26°C) | 強烈及以上時數比 (>32°C) | 非常強烈時數比 (>38°C) |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for fab in fabrics:
        res = all_results[fab]
        st = res["stress_table"]["total"]
        name_zh = res["fabric_name_zh"]
        lines.append(
            f"| **{name_zh}** | `{fab}` | {st['area_m2']:,.0f} | {st['sensor_count']:,} | "
            f"{st['mean_utci_c']:.1f} | {st['max_utci_c']:.1f} | {st['mean_mrt_c']:.1f} | {st['mean_svf']:.3f} | "
            f"**{st['heat_stress_pct']:.1f}%** | {st['strong_plus_pct']:.1f}% | {st['very_strong_pct']:.1f}% |"
        )

    lines.append("\n## 2. 各類開放空間分類熱壓力時數比例明細表\n")
    lines.append("| 方案 | 空間類別 | 感測點數 | 面積 (m²) | 總點時數 | 無熱壓力 (≤26°C) | 中度 (26–32°C) | 強烈 (32–38°C) | 非常強烈 (38–46°C) | 熱壓力總佔比 (>26°C) | 平均 MRT (°C) | 平均 SVF |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for fab in fabrics:
        res = all_results[fab]
        name_zh = res["fabric_name_zh"]
        for cat_key in (*CATEGORY_ORDER, "total"):
            st = res["stress_table"][cat_key]
            cat_label = st["category_zh"]
            if cat_key == "total":
                cat_label = f"**{cat_label}**"
            lines.append(
                f"| {name_zh} | {cat_label} | {st['sensor_count']:,} | {st['area_m2']:,.0f} | {st['total_sensor_hours']:,} | "
                f"{st['no_stress_pct']:.1f}% | {st['moderate_pct']:.1f}% | {st['strong_pct']:.1f}% | {st['very_strong_pct']:.1f}% | "
                f"**{st['heat_stress_pct']:.1f}%** | {st['mean_mrt_c']:.1f} | {st['mean_svf']:.3f} |"
            )

    lines.append("\n## 3. 最熱時刻 (14:00) 氣象與熱舒適數值\n")
    lines.append("| 指標 | 數值 | 單位 | 備註 |")
    lines.append("| :--- | :---: | :---: | :--- |")
    lines.append("| 日期與時刻 | 2017-08-19 14:00 | - | 夏季節令高溫典型時段 |")
    lines.append(f"| 室外乾球氣溫 (Ta) | {weather_info['hourly_data'][14]['dry_bulb_c']:.1f} | °C | 取自推導天氣 EPW |")
    lines.append(f"| 相對濕度 (RH) | {weather_info['hourly_data'][14]['relative_humidity_pct']:.1f} | % | 取自推導天氣 EPW |")
    lines.append(f"| 氣象 10m 風速 (v10) | {weather_info['hourly_data'][14]['wind_speed_10m']:.1f} | m/s | 取自推導天氣 EPW |")
    lines.append(f"| 1.1m 換算風速 (v1.1) | {compute_log_wind_1_1m(weather_info['hourly_data'][14]['wind_speed_10m']):.2f} | m/s | 對數律換算 (z0=0.5m) |")
    lines.append(f"| 法向直射日照 (DNI) | {weather_info['hourly_data'][14]['dni_w_m2']:.0f} | W/m² | 取自推導天氣 EPW |")
    lines.append(f"| 水平漫射日照 (DHI) | {weather_info['hourly_data'][14]['dhi_w_m2']:.0f} | W/m² | 取自推導天氣 EPW |")
    lines.append(f"| 水平長波紅外輻射 (IR) | {weather_info['hourly_data'][14]['horiz_ir_w_m2']:.0f} | W/m² | 取自推導天氣 EPW |")

    return "\n".join(lines)


def generate_manifest(
    epw_path: Path,
    context_bldg_path: Path,
    context_meta: Dict[str, Any],
    weather_info: Dict[str, Any],
    all_results: Dict[str, Dict[str, Any]],
    output_files: List[Path],
    fabrics: Sequence[str] = FABRICS,
    buildings_override_path: Path | None = None,
) -> Dict[str, Any]:
    """Generate comprehensive manifest with SHA-256 hashes, assumptions, and package versions."""
    import ladybug
    import ladybug_comfort
    import ladybug_radiance
    import honeybee_radiance
    import shapely
    import numpy

    plan_paths = {
        fab: Path(all_results[fab].get("plan_path") or PROJECT_ROOT / f"artifacts/fab1/run-8/{fab}-plan.json")
        for fab in fabrics
    }
    plan_files = {fab: str(path) for fab, path in plan_paths.items()}
    plan_hashes = {fab: sha256_file(path) for fab, path in plan_paths.items()}

    out_file_meta = {}
    for p in output_files:
        if p.exists():
            out_file_meta[p.name] = {
                "path": str(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

    manifest = {
        "manifest_version": "1.0.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "E2/W8 Outdoor Thermal Comfort UTCI Simulation for Four Urban Fabrics",
        "status": "COMPLETED",
        "notice": "探索性；風速未考慮建築遮蔽（依對數律換算至 1.1m 高度，粗糙度採都市值 z0=0.5m，不做 CFD，風場遮蔽留給 E5）",
        "inputs": {
            "epw": {
                "path": str(epw_path),
                "sha256": sha256_file(epw_path),
                "hottest_summer_day": weather_info["date_str"],
                "mean_daily_temp_c": weather_info["mean_daily_temp_c"],
                "max_daily_temp_c": weather_info["max_daily_temp_c"],
                "analysis_hours": "10:00 - 17:00",
            },
            "context_buildings": {
                "path": str(context_bldg_path),
                "sha256": context_meta.get("sha256"),
                "buffer_m": CONTEXT_BUFFER_M,
                "total_obstacles": context_meta.get("total_context_obstacles"),
                "assumed_height_m": CONTEXT_ASSUMED_HEIGHT_M,
            },
            "fabric_plans": {
                fab: {
                    "path": plan_files[fab],
                    "sha256": plan_hashes[fab],
                    "name_zh": FABRIC_NAMES_ZH[fab],
                }
                for fab in fabrics
            },
        },
        "assumptions": {
            "sensor_height_m": SENSOR_HEIGHT_Z1_1,
            "surface_offset_m": SURFACE_OFFSET_M,
            "grid_spacing_m": all_results[fabrics[0]]["grid_spacing_m"],
            "wind_profile": {
                "method": "Logarithmic law: v(1.1) = v(10) * ln(1.1/z0) / ln(10/z0)",
                "z0_m": URBAN_ROUGHNESS_Z0,
                "description": "Davenport-Wieringa class 6 / suburban-urban roughness length; no CFD sheltering modeled",
                "v_min_clamp_m_s": 0.5,
            },
            "solar_and_mrt": {
                "mrt_model": "Ladybug Comfort SolarCal (outdoor_sky_heat_exch)",
                "sky_view_factor_model": "Ladybug Radiance Tregenza dome (145 sky patch vectors with solid angle weighting)",
                "direct_sun_obstruction": "Radiance 6.0.2 intersection_matrix with 3D buildings and 300m context",
                "floor_reflectance": FLOOR_REFLECTANCE,
                "posture": HUMAN_POSTURE,
                "sharp_deg": SOLAR_SHARP_DEG,
                "body_absorptivity": BODY_ABSORPTIVITY,
                "body_emissivity": BODY_EMISSIVITY,
                "surrounding_surface_temp_proxy": "EPW dry-bulb temperature Ta",
            },
            "utci_model": "Ladybug Comfort universal_thermal_climate_index polynomial",
        },
        "environment_versions": {
            "python": sys.version,
            "ladybug_core": getattr(ladybug, "__version__", "0.44.59"),
            "ladybug_comfort": getattr(ladybug_comfort, "__version__", "0.19.8"),
            "ladybug_radiance": getattr(ladybug_radiance, "__version__", "0.2.12"),
            "honeybee_radiance": getattr(honeybee_radiance, "__version__", "1.66.288"),
            "shapely": getattr(shapely, "__version__", "2.2.0"),
            "numpy": getattr(numpy, "__version__", "2.5.4"),
            "radiance": "6.0.2-arm64",
        },
        "runtime_metrics": {
            fab: {
                "sensor_count": all_results[fab]["total_sensor_count"],
                "elapsed_seconds": all_results[fab]["elapsed_seconds"],
                "radiance_svf_s": all_results[fab]["radiance_svf_time_s"],
                "radiance_sun_s": all_results[fab]["radiance_sun_time_s"],
            }
            for fab in fabrics
        },
        "output_files": out_file_meta,
    }
    if buildings_override_path is not None:
        manifest["inputs"]["buildings_override"] = {
            "path": str(buildings_override_path),
            "sha256": sha256_file(buildings_override_path),
        }
    return manifest


# --- CLI Main ---
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outdoor Thermal Comfort UTCI Simulation for Four Urban Fabrics")
    parser.add_argument("--grid-size", type=float, default=5.0, help="Sensor grid spacing in metres (default: 5.0)")
    parser.add_argument("--epw", type=Path, default=DEFAULT_EPW_PATH, help="Path to EPW weather file")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Output directory")
    parser.add_argument("--source-dir", type=Path, help="Existing UTCI result directory; required for --language en")
    parser.add_argument("--language", choices=("zh", "en"), default="zh", help="Figure language (English re-renders existing SVGs only)")
    parser.add_argument("--fabrics", nargs="+", choices=FABRICS, default=FABRICS, help="Fabrics to simulate")
    parser.add_argument(
        "--buildings-override",
        type=Path,
        help="JSON formal-draft response or editable_buildings list; only valid with --fabrics harbour_grain",
    )
    parser.add_argument("--trial", action="store_true", help="Run 20m trial on the first selected fabric to test timing")
    parser.add_argument("--target-hour", type=int, default=14, help="Target peak hour for heatmaps (default: 14)")
    args = parser.parse_args(argv)

    if args.language == "en":
        if args.source_dir is None:
            parser.error("--source-dir is required for --language en")
        if args.buildings_override is not None or args.trial or args.grid_size != 5.0 or args.target_hour != 14:
            parser.error("--language en only renders the registered 5 m, 14:00 result figures")
        for output in render_existing_english_figures(args.source_dir, args.output_dir, args.fabrics):
            print(output)
        return 0

    if solarcal is None or utci is None:
        parser.error("Ladybug Comfort is required for simulation mode; English figure rendering does not require it")

    try:
        _validate_fabric_selection(args.fabrics, args.buildings_override)
    except ValueError as exc:
        parser.error(str(exc))

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print(f"戶外熱舒適 UTCI 模擬分析：{len(args.fabrics)} 個紋理方案夏季開放空間")
    print(f"網格間距：{args.grid_size} m ｜ 目標最熱圖時刻：{args.target_hour}:00")
    print("=" * 80)

    # 1. Verify Radiance 6.0.2
    rad_status = verify_radiance_runtime()
    if not rad_status.available:
        print(f"Error: Radiance runtime not available: {rad_status.reason}", file=sys.stderr)
        return 1
    print(f"[OK] Radiance runtime verified: {rad_status.version}")

    # 2. Extract Weather and find Hottest Summer Day
    print(f"\n[1/5] 讀取 EPW 天氣資料：{args.epw}")
    weather_info = find_hottest_summer_day(args.epw)
    print(f"  最熱夏日日期：{weather_info['date_str']}")
    print(f"  全日平均乾球溫度：{weather_info['mean_daily_temp_c']} °C（最高溫 {weather_info['max_daily_temp_c']} °C, 最低溫 {weather_info['min_daily_temp_c']} °C）")
    print("  10:00–17:00 氣象條件摘要：")
    for h in range(10, 18):
        hw = weather_info["hourly_data"][h]
        v1_1 = compute_log_wind_1_1m(hw["wind_speed_10m"])
        print(f"    {h:02d}:00 | Ta={hw['dry_bulb_c']:4.1f}°C | RH={hw['relative_humidity_pct']:2.0f}% | "
              f"v10={hw['wind_speed_10m']:3.1f}m/s -> v1.1={v1_1:4.2f}m/s | DNI={hw['dni_w_m2']:4.0f} W/m² | DHI={hw['dhi_w_m2']:3.0f} W/m²")

    # 3. Load Context Geometry
    print(f"\n[2/5] 載入周邊脈絡建築與水體（300m 緩衝區）...")
    trial_fabric = args.fabrics[0]
    dummy_site_plan = PROJECT_ROOT / "artifacts" / "fab1" / "run-8" / f"{trial_fabric}-plan.json"
    with open(dummy_site_plan, encoding="utf-8") as f:
        site_poly = shape(json.load(f)["site"])
    context_obstacles, context_meta = load_context_obstacles(DEFAULT_CONTEXT_BUILDINGS, site_poly)
    water_polys = load_context_water(DEFAULT_CONTEXT_WATER, site_poly)
    print(f"  已載入脈絡障礙物：{len(context_obstacles)} 座建築（已知高度 {context_meta['known_height_obstacles']}，假設高度 {context_meta['assumed_height_obstacles']}）")
    print(f"  已載入水體多邊形：{len(water_polys)} 處")

    # 4. Trial run if requested
    if args.trial:
        print(f"\n[測試模式] 以 20 m 網格試跑 {trial_fabric}...")
        t0 = time_mod.time()
        trial_res = simulate_fabric_utci(
            fabric_id=trial_fabric,
            plan_path=dummy_site_plan,
            context_obstacles=context_obstacles,
            weather_info=weather_info,
            spacing_m=20.0,
            target_hour=args.target_hour,
            buildings_override_path=args.buildings_override,
        )
        t_trial = time_mod.time() - t0
        print(f"  20m 試跑完成！感測點數：{trial_res['total_sensor_count']}，耗時：{t_trial:.2f} 秒")
        print(f"  全體開放空間平均 UTCI：{trial_res['stress_table']['total']['mean_utci_c']} °C，熱壓力比例：{trial_res['stress_table']['total']['heat_stress_pct']}%")
        return 0

    # 5. Full Simulation across four fabrics
    target_fabrics = args.fabrics
    all_results: dict[str, dict[str, Any]] = {}

    print(f"\n[3/5] 開始全方案 UTCI 模擬（網格：{args.grid_size} m）...")
    for fab in target_fabrics:
        p_path = PROJECT_ROOT / f"artifacts/fab1/run-8/{fab}-plan.json"
        print(f"\n  ▶ 正在模擬：{FABRIC_NAMES_ZH[fab]} (`{fab}`)...")
        t_fab_0 = time_mod.time()
        res = simulate_fabric_utci(
            fabric_id=fab,
            plan_path=p_path,
            context_obstacles=context_obstacles,
            weather_info=weather_info,
            spacing_m=args.grid_size,
            target_hour=args.target_hour,
            buildings_override_path=args.buildings_override,
        )
        t_fab = time_mod.time() - t_fab_0
        all_results[fab] = res
        tot_st = res["stress_table"]["total"]
        print(f"    完成！感測點：{res['total_sensor_count']} 點 ｜ 耗時：{t_fab:.2f} 秒（SVF: {res['radiance_svf_time_s']}s, 陽光: {res['radiance_sun_time_s']}s）")
        print(f"    熱舒適指標：平均 UTCI={tot_st['mean_utci_c']}°C, 最高 UTCI={tot_st['max_utci_c']}°C, 熱壓力時數比={tot_st['heat_stress_pct']}% (強烈及以上={tot_st['strong_plus_pct']}%)")

    # 6. Render SVGs and PNGs
    print(f"\n[4/5] 繪製選定方案 {args.target_hour}:00 UTCI 熱圖（SVG 及 PNG）...")
    generated_files: list[Path] = []
    for fab in target_fabrics:
        svg_file = output_dir / f"{fab}_utci_{args.target_hour:02d}00.svg"
        png_file = output_dir / f"{fab}_utci_{args.target_hour:02d}00.png"
        generate_utci_svg(all_results[fab], water_polys, context_obstacles, svg_file)
        generated_files.append(svg_file)
        print(f"  已生成 SVG：{svg_file.name}")

        converted = convert_svg_to_png(svg_file, png_file, size=1600)
        if converted and png_file.exists():
            generated_files.append(png_file)
            print(f"  已生成 PNG：{png_file.name}")

    # 7. Generate Tables & Manifest
    print(f"\n[5/5] 生成比較表格與 Manifest...")
    table_md_path = output_dir / "utci_stress_hours_comparison.md"
    table_json_path = output_dir / "utci_stress_hours_comparison.json"
    manifest_path = output_dir / "manifest.json"

    # Markdown table
    md_content = generate_markdown_table(all_results, weather_info, target_fabrics)
    table_md_path.write_text(md_content, encoding="utf-8")
    generated_files.append(table_md_path)
    print(f"  已生成 Markdown 比較表：{table_md_path.name}")

    # JSON structured summary
    json_summary = {
        "weather": {
            "date": weather_info["date_str"],
            "mean_temp_c": weather_info["mean_daily_temp_c"],
            "max_temp_c": weather_info["max_daily_temp_c"],
            "analysis_hours": list(range(10, 18)),
            "hourly_data": weather_info["hourly_data"],
        },
        "fabrics": {
            fab: {
                "name_zh": all_results[fab]["fabric_name_zh"],
                "total_sensor_count": all_results[fab]["total_sensor_count"],
                "stress_table": all_results[fab]["stress_table"],
                "hourly_overall_stats": all_results[fab]["hourly_overall_stats"],
            }
            for fab in target_fabrics
        },
    }
    table_json_path.write_text(json.dumps(json_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    generated_files.append(table_json_path)
    print(f"  已生成 JSON 結構化比較表：{table_json_path.name}")

    # Manifest
    manifest_data = generate_manifest(
        epw_path=args.epw,
        context_bldg_path=DEFAULT_CONTEXT_BUILDINGS,
        context_meta=context_meta,
        weather_info=weather_info,
        all_results=all_results,
        output_files=generated_files,
        fabrics=target_fabrics,
        buildings_override_path=args.buildings_override,
    )
    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
    generated_files.append(manifest_path)
    print(f"  已生成 Manifest：{manifest_path.name}")

    print("\n" + "=" * 80)
    print("戶外熱舒適 UTCI 模擬任務全部順利完成！")
    print(f"輸出目錄：{output_dir}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
