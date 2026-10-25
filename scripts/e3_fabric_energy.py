#!/usr/bin/env python3
"""Exploratory E3/E4 Honeybee-Energy + EnergyPlus comparison for W6-07.

All modeled values are exploratory and are not an energy certification. The
script keeps simulation work outside the repository under /private/tmp and
writes only the requested report artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shapely import constrained_delaunay_triangles
try:
    from honeybee.boundarycondition import Outdoors, Surface
    from honeybee.model import Model
    from honeybee.room import Room
    from honeybee.shade import Shade
    from honeybee_energy.boundarycondition import Adiabatic
    from honeybee_energy.config import folders
    from honeybee_energy.construction.opaque import OpaqueConstruction
    from honeybee_energy.hvac.idealair import IdealAirSystem, no_limit
    from honeybee_energy.lib.constructionsets import construction_set_by_identifier
    from honeybee_energy.lib.programtypes import program_type_by_identifier
    from honeybee_energy.lib.scheduletypelimits import schedule_type_limit_by_identifier
    from honeybee_energy.material.opaque import EnergyMaterial, EnergyMaterialNoMass
    from honeybee_energy.schedule.ruleset import ScheduleRuleset
    from honeybee_energy.simulation.output import SimulationOutput
    from honeybee_energy.simulation.parameter import SimulationParameter
    from honeybee_energy.simulation.control import SimulationControl
    from honeybee_energy.simulation.shadowcalculation import ShadowCalculation
    from honeybee_energy.simulation.runperiod import RunPeriod
    from honeybee_energy.writer import model_to_idf
    from ladybug_geometry.geometry3d import Face3D, Point3D
    from ladybug_geometry.geometry3d.polyface import Polyface3D
except ImportError:
    # Simulation engines are optional when rendering existing figure results.
    pass
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon, box, shape
from shapely.ops import unary_union


SCRIPT_VERSION = "1.2.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_ROOT = PROJECT_ROOT / "artifacts" / "fab1" / "run-8"
WEATHER_PATH = Path(
    "/Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/"
    "w5-weather-derived-method-proposal-20260926T115309Z/candidate-01/"
    "derived-minute60.epw"
)
CONTEXT_PATH = Path(
    "/Users/jackhsieh/.local/share/urban-design-data/context/"
    "context-20260927T153054Z/buildings.geojson"
)
ENGINE_ROOT = Path(
    "/Users/jackhsieh/.local/share/urban-design-envs/engines/"
    "openstudio-3.11.0/OpenStudio-3.11.0+241b8abb4d-Darwin-arm64"
)
OPENSTUDIO_BIN = ENGINE_ROOT / "bin"
ENERGYPLUS_BIN = ENGINE_ROOT / "EnergyPlus"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "w8" / "e3e4"
DEFAULT_TEMP_ROOT = Path("/private/tmp")
ALL_FABRICS = (
    "harbour_grain",
    "closed_block_extension",
    "courtyard_islands",
    "landscape_figure",
)

CZ5_MASS_ID = "2019::ClimateZone5::Mass"
CZ5_WOOD_ID = "2019::ClimateZone5::WoodFramed"
WWR = 0.40
CONTEXT_BUFFER_M = 100.0
HEATING_COP = 2.5
COOLING_COP = 3.0
HOT_WATER_COP = 1.0
SUMMER_MONTHS = {6, 7, 8}
WINTER_MONTHS = {12, 1, 2}
OVERHEAT_THRESHOLD_C = 26.0

PROGRAM_BY_USE = {
    "residential": "2019::MidriseApartment::Apartment",
    "industrial": "2019::Warehouse::Bulk",
    "office": "2019::MediumOffice::OpenOffice",
    "commercial": "2019::Retail::Retail",
    "retail": "2019::Retail::Retail",
    "civic": "2019::Courthouse::Office",
    "public": "2019::Courthouse::Office",
    "mixed_use": "2019::MediumOffice::OpenOffice",
    "mixed-use": "2019::MediumOffice::OpenOffice",
}

ENERGY_OUTPUTS = (
    "Zone Ideal Loads Supply Air Total Heating Energy",
    "Zone Ideal Loads Supply Air Total Cooling Energy",
    "Zone Ideal Loads Supply Air Total Heating Rate",
    "Zone Ideal Loads Supply Air Total Cooling Rate",
    "Zone Lights Electricity Energy",
    "Zone Electric Equipment Electricity Energy",
    "Zone Ventilation Fan Electricity Energy",
    "Zone Gas Equipment NaturalGas Energy",
    "Water Use Equipment Heating Energy",
)
JOULES_PER_KWH = 3_600_000.0


@dataclass(frozen=True)
class BuildingInput:
    building_id: str
    geometry: Polygon | MultiPolygon
    properties: dict[str, Any]
    use: str
    program_id: str
    floors: int
    height_m: float
    floor_heights_m: tuple[float, ...]
    footprint_area_m2: float
    mezzanine_gfa_m2: float

    @property
    def modeled_gfa_m2(self) -> float:
        return self.footprint_area_m2 * self.floors

    @property
    def reported_gfa_m2(self) -> float:
        return self.modeled_gfa_m2 + self.mezzanine_gfa_m2


@dataclass
class SimulationCase:
    label: str
    fabric_id: str
    construction: str
    cooling_enabled: bool
    sample_mode: bool
    status: str
    run_dir: str
    model_build_seconds: float = 0.0
    idf_translation_seconds: float = 0.0
    simulation_seconds: float = 0.0
    exit_code: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


def safe_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_.-")
    return (value or "id")[:80]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_epw(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"指定 EPW 不存在：{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        header = [next(stream, "") for _ in range(8)]
        rows = list(csv.reader(stream))
    if len(rows) != 8760:
        raise ValueError(
            f"EPW 必須有完整一年 8760 筆資料；實際為 {len(rows)}。依指示停止，不另找天氣檔。"
        )
    if any(len(row) < 35 for row in rows):
        raise ValueError("EPW 有資料列欄位少於 35，停止模擬。")
    date_hours = [(int(row[1]), int(row[2]), int(row[3])) for row in rows]
    if len(set(date_hours)) != 8760:
        raise ValueError("EPW 日期／小時有重複列，停止模擬。")
    minute_values = sorted({row[4] for row in rows})
    if minute_values != ["60"]:
        raise ValueError(f"指定 EPW Minute 不是全數 60：{minute_values}。停止模擬。")
    month_counts = {str(m): sum(int(row[1]) == m for row in rows) for m in range(1, 13)}
    location = next((line.strip() for line in header if line.startswith("LOCATION,")), "")
    typical_note = next((line.strip() for line in header if line.startswith("COMMENTS 1,")), "")
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "header_rows": 8,
        "hourly_rows": len(rows),
        "unique_date_hour_rows": len(set(date_hours)),
        "minute_values": minute_values,
        "month_row_counts": month_counts,
        "location_header": location,
        "typical_year_note": typical_note,
    }


def normalize_use(properties: dict[str, Any]) -> str:
    raw = str(properties.get("use") or properties.get("building_type") or "").lower()
    aliases = {
        "residential": "residential", "housing": "residential", "building.rowhouse": "residential",
        "industrial": "industrial", "industry": "industrial", "building.industrial": "industrial",
        "office": "office", "commercial": "commercial", "retail": "retail",
        "civic": "civic", "public": "public", "mixed-use": "mixed-use", "mixed_use": "mixed_use",
    }
    if raw not in aliases:
        raise ValueError(
            f"plan 用途無已確認的 Honeybee program 對應：use={raw!r}, "
            f"building_type={properties.get('building_type')!r}"
        )
    return aliases[raw]


def _floor_heights(properties: dict[str, Any], floors: int, total_height: float) -> tuple[float, ...]:
    first = properties.get("first_floor_height_m")
    typical = properties.get("standard_floor_height_m")
    if floors == 1:
        return (total_height,)
    if isinstance(first, (int, float)) and isinstance(typical, (int, float)):
        proposed = (float(first),) + (float(typical),) * (floors - 1)
        if all(h > 0 for h in proposed) and abs(sum(proposed) - total_height) <= 0.05:
            return proposed
    return tuple([total_height / floors] * floors)


def parse_plan(plan_path: Path) -> tuple[dict[str, Any], list[BuildingInput], list[dict[str, Any]]]:
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    if data.get("crs") != "EPSG:28992":
        raise ValueError(f"方案水平 CRS 預期 EPSG:28992，實際為 {data.get('crs')!r}")
    new_buildings: list[BuildingInput] = []
    retained: list[dict[str, Any]] = []
    for feature in data.get("buildings", []):
        props = feature.get("properties") or {}
        geom = shape(feature.get("geometry") or {})
        if not geom.is_valid or geom.is_empty or geom.area <= 0:
            raise ValueError(f"無效或零面積建築幾何：{props.get('id', feature.get('id'))}")
        if props.get("retained") is True:
            retained.append({"id": str(props.get("id") or feature.get("id")), "geometry": geom, "properties": props})
            continue
        building_id = str(props.get("id") or feature.get("id") or f"new-{len(new_buildings)+1}")
        floors = int(props.get("floors") or 0)
        height = float(props.get("height_m") or 0)
        if floors < 1 or height <= 0 or not math.isfinite(height):
            raise ValueError(f"建築樓層／高度不可用：{building_id}, floors={floors}, height_m={height}")
        use = normalize_use(props)
        program_id = PROGRAM_BY_USE[use]
        program_type_by_identifier(program_id)
        mezz = float(props.get("mezzanine_gfa_m2") or 0.0)
        new_buildings.append(
            BuildingInput(
                building_id, geom, props, use, program_id, floors, height,
                _floor_heights(props, floors, height), float(geom.area), mezz,
            )
        )
    if not new_buildings:
        raise ValueError(f"方案沒有可建模的新建建築：{plan_path}")
    return data, new_buildings, retained


def _geometry_polygons(geom: Polygon | MultiPolygon) -> Iterable[Polygon]:
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from geom.geoms
    elif isinstance(geom, GeometryCollection):
        for child in geom.geoms:
            yield from _geometry_polygons(child)


def _local_points(poly: Polygon, origin_x: float, origin_y: float, z: float) -> list[Point3D]:
    coords = list(poly.exterior.coords)[:-1]
    return [Point3D(float(x) - origin_x, float(y) - origin_y, z) for x, y in coords]


def _convex_triangles(poly: Polygon) -> list[Polygon]:
    result = constrained_delaunay_triangles(poly)
    triangles = [
        part for part in getattr(result, "geoms", [result])
        if isinstance(part, Polygon) and poly.covers(part)
    ]
    covered_area = sum(float(part.area) for part in triangles)
    if not triangles or abs(covered_area - float(poly.area)) > max(1e-5, poly.area * 1e-8):
        raise ValueError(
            "footprint 凸三角化面積不一致："
            f"footprint={poly.area:.6f} m2, triangles={covered_area:.6f} m2"
        )
    return triangles


def _extruded_polyface(poly: Polygon, origin_x: float, origin_y: float,
                       base_z: float, height: float) -> Polyface3D:
    faces: list[Face3D] = []
    for triangle in _convex_triangles(poly):
        top = _local_points(triangle, origin_x, origin_y, base_z + height)
        bottom = _local_points(triangle, origin_x, origin_y, base_z)
        faces.append(Face3D(list(reversed(bottom))))
        faces.append(Face3D(top))
    rings = [poly.exterior, *poly.interiors]
    for ring in rings:
        points = list(ring.coords)[:-1]
        for a, b in zip(points, points[1:] + points[:1]):
            ax, ay = float(a[0]) - origin_x, float(a[1]) - origin_y
            bx, by = float(b[0]) - origin_x, float(b[1]) - origin_y
            if math.hypot(bx - ax, by - ay) <= 0.01:
                continue
            faces.append(Face3D([
                Point3D(ax, ay, base_z), Point3D(bx, by, base_z),
                Point3D(bx, by, base_z + height), Point3D(ax, ay, base_z + height),
            ]))
    return Polyface3D.from_faces(faces, tolerance=0.01)


def _building_rooms(
    buildings: list[BuildingInput], origin_x: float, origin_y: float,
    construction_set: Any, cooling_enabled: bool, assign_ideal_air: bool = True,
) -> tuple[list[Room], dict[str, dict[str, Any]], int]:
    rooms: list[Room] = []
    room_meta: dict[str, dict[str, Any]] = {}
    off_schedule = None
    if not cooling_enabled:
        fractional = schedule_type_limit_by_identifier("Fractional")
        off_schedule = ScheduleRuleset.from_constant_value("E4_Cooling_Off", 0, fractional)

    for building in buildings:
        polygons = list(_geometry_polygons(building.geometry))
        if not polygons:
            raise ValueError(f"建築幾何沒有 Polygon：{building.building_id}")
        for polygon_index, poly in enumerate(polygons, start=1):
            # Each actual storey is modeled as its own zone to preserve distinct
            # ground, inter-storey, and roof boundary conditions.
            story_z = 0.0
            building_rooms: list[Room] = []
            poly_area = float(poly.area)
            for story, story_height in enumerate(building.floor_heights_m, start=1):
                solid = _extruded_polyface(
                    poly, origin_x, origin_y, story_z, float(story_height),
                )
                room_id = safe_id(f"{building.building_id}_part{polygon_index}_L{story}")
                room = Room.from_polyface3d(room_id, solid, ground_depth=0)
                room.display_name = f"{building.building_id} floor {story}"
                room.properties.energy.program_type = program_type_by_identifier(building.program_id)
                room.properties.energy.construction_set = construction_set
                if assign_ideal_air:
                    hvac = IdealAirSystem(
                        safe_id(f"HVAC_{building.building_id}_L{story}"),
                        economizer_type="NoEconomizer",
                        heating_limit=no_limit,
                        cooling_limit=no_limit,
                    )
                    if off_schedule is not None:
                        hvac.cooling_availability = off_schedule
                    room.properties.energy.hvac = hvac
                room_meta[room.identifier] = {
                    "building_id": building.building_id,
                    "story": story,
                    "use": building.use,
                    "program_id": building.program_id,
                    "floor_area_m2": poly_area,
                    "floor_multiplier": 1,
                    "building_gfa_m2": building.reported_gfa_m2,
                    "represented_gfa_m2": building.reported_gfa_m2,
                    "result_expansion_factor": 1.0,
                }
                rooms.append(room)
                building_rooms.append(room)
                story_z += float(story_height)
            if len(building_rooms) > 1:
                Room.solve_adjacency(building_rooms, tolerance=0.01, remove_mismatched_sub_faces=False)
    return rooms, room_meta, len(rooms)


def _footprint_neighbours(
    buildings: list[BuildingInput], min_shared_edge_m: float = 0.50,
) -> list[tuple[int, int, float]]:
    neighbours = []
    for i, left in enumerate(buildings):
        for j in range(i + 1, len(buildings)):
            right = buildings[j]
            overlap_area = left.geometry.intersection(right.geometry).area
            if overlap_area > 1e-6:
                # Run-8 records sub-nanometre numerical overlaps; these are not shared walls.
                if overlap_area > 0.01:
                    raise ValueError(
                        f"新建足跡有實質重疊：{left.building_id}/{right.building_id}, "
                        f"intersection={overlap_area:.6g} m2"
                    )
                continue
            shared = float(left.geometry.boundary.intersection(right.geometry.boundary).length)
            if shared >= min_shared_edge_m:
                neighbours.append((i, j, shared))
    return neighbours


def room_meta_building_id(room_identifier: str) -> str:
    match = re.match(r"(.+)_part\d+_L\d+$", room_identifier)
    if not match:
        raise ValueError(f"無法從 Honeybee Room ID 取回建築 ID：{room_identifier}")
    return match.group(1)


def _set_shared_walls_adiabatic(
    buildings: list[BuildingInput], rooms: list[Room],
    origin_x: float = 0.0, origin_y: float = 0.0,
    omitted_neighbor_buildings: list[BuildingInput] | None = None,
) -> dict[str, Any]:
    per_building: dict[str, list[Room]] = defaultdict(list)
    for room in rooms:
        per_building[room_meta_building_id(room.identifier)].append(room)
    neighbours = _footprint_neighbours(buildings)
    wall_surface_count = 0
    for i, j, _shared_length in neighbours:
        pair_rooms = per_building[buildings[i].building_id] + per_building[buildings[j].building_id]
        Room.intersect_adjacency(pair_rooms, tolerance=0.01, angle_tolerance=1)
        Room.solve_adjacency(pair_rooms, tolerance=0.01, remove_mismatched_sub_faces=False)
        paired_vertical_faces = []
        for room in pair_rooms:
            for face in room.faces:
                if isinstance(face.boundary_condition, Surface) and face.type.name == "Wall":
                    if abs(float(face.geometry.normal.z)) <= 0.01:
                        paired_vertical_faces.append(face)
        for face in paired_vertical_faces:
            face.boundary_condition = Adiabatic()
        wall_surface_count += len(paired_vertical_faces)
    omitted_wall_surfaces = 0
    if omitted_neighbor_buildings:
        represented_ids = {building.building_id for building in buildings}
        for sampled in buildings:
            sampled_rooms = per_building[sampled.building_id]
            for omitted in omitted_neighbor_buildings:
                if omitted.building_id in represented_ids:
                    continue
                shared_boundary = sampled.geometry.boundary.intersection(omitted.geometry.boundary)
                if float(shared_boundary.length) < 0.50:
                    continue
                for room in sampled_rooms:
                    for face in room.faces:
                        if (
                            face.type.name != "Wall" or
                            not isinstance(face.boundary_condition, Outdoors) or
                            abs(float(face.geometry.normal.z)) > 0.01
                        ):
                            continue
                        xy = {
                            (float(point.x) + origin_x, float(point.y) + origin_y)
                            for point in face.geometry.vertices
                        }
                        if len(xy) != 2:
                            continue
                        wall_line = LineString(sorted(xy))
                        buffered_overlap_m = float(
                            wall_line.buffer(0.02).intersection(shared_boundary).length
                        )
                        if buffered_overlap_m >= 0.50:
                            face.boundary_condition = Adiabatic()
                            omitted_wall_surfaces += 1
    return {
        "shared_footprint_pairs": len(neighbours),
        "adiabatic_wall_surfaces": wall_surface_count,
        "adiabatic_wall_pairs": wall_surface_count // 2,
        "adiabatic_wall_surfaces_to_omitted_new_building_shades": omitted_wall_surfaces,
        "minimum_shared_edge_m": 0.50,
    }


def _add_exterior_apertures(rooms: list[Room], ratio: float = WWR) -> int:
    count = 0
    for room in rooms:
        for face in room.faces:
            if face.type.name == "Wall" and isinstance(face.boundary_condition, Outdoors) and face.area > 0.25:
                prior_count = len(face.apertures)
                face.apertures_by_ratio(ratio, tolerance=0.01, rect_split=True)
                count += len(face.apertures) - prior_count
    return count


def _shade_faces(identifier: str, geom: Polygon | MultiPolygon, height: float,
                 origin_x: float, origin_y: float) -> list[Shade]:
    shades: list[Shade] = []
    for poly_index, poly in enumerate(_geometry_polygons(geom), start=1):
        for roof_index, triangle in enumerate(_convex_triangles(poly), start=1):
            roof = Face3D(_local_points(triangle, origin_x, origin_y, height))
            shades.append(Shade(
                safe_id(f"{identifier}_p{poly_index}_roof{roof_index}"), roof,
            ))
        edge_index = 0
        for ring in [poly.exterior, *poly.interiors]:
            points = list(ring.coords)[:-1]
            for a, b in zip(points, points[1:] + points[:1]):
                x1, y1 = float(a[0]) - origin_x, float(a[1]) - origin_y
                x2, y2 = float(b[0]) - origin_x, float(b[1]) - origin_y
                if math.hypot(x2 - x1, y2 - y1) <= 0.01:
                    continue
                edge_index += 1
                try:
                    wall = Face3D([
                        Point3D(x1, y1, 0), Point3D(x2, y2, 0),
                        Point3D(x2, y2, height), Point3D(x1, y1, height),
                    ])
                except Exception:
                    continue
                shades.append(Shade(safe_id(f"{identifier}_p{poly_index}_w{edge_index}"), wall))
    return shades


def _shade_inputs(
    retained: list[dict[str, Any]], new_buildings: list[BuildingInput], context_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, int], tuple[float, float]]:
    union = unary_union([b.geometry for b in new_buildings])
    min_x, min_y, _max_x, _max_y = union.bounds
    origin_x, origin_y = float(min_x), float(min_y)
    focus = union.buffer(CONTEXT_BUFFER_M)
    shade_rows: list[dict[str, Any]] = []
    counts = {
        "retained_total": len(retained), "retained_used": 0, "retained_missing_height": 0,
        "context_total": 0, "context_with_height_in_buffer": 0,
        "context_missing_height_in_buffer": 0, "context_outside_buffer": 0,
        "context_duplicate_of_retained": 0, "context_invalid_geometry": 0,
    }
    retained_geoms = []
    for row in retained:
        props, geom = row["properties"], row["geometry"]
        retained_geoms.append(geom)
        height = None
        for key in ("height_m", "height_above_ground_m", "height_above_ground", "roof_p70_height_m"):
            raw = props.get(key)
            if isinstance(raw, (int, float)) and math.isfinite(float(raw)) and float(raw) > 0:
                height = float(raw)
                break
        if height is None:
            counts["retained_missing_height"] += 1
            continue
        shade_rows.append({
            "id": f"retained_{row['id']}", "geometry": geom, "height_m": height,
            "source": "run-8 retained building properties",
        })
        counts["retained_used"] += 1

    if not context_path.is_file():
        raise FileNotFoundError(f"指定脈絡建築 GeoJSON 不存在：{context_path}")
    context = json.loads(context_path.read_text(encoding="utf-8"))
    features = context.get("features", [])
    counts["context_total"] = len(features)
    for index, feature in enumerate(features):
        try:
            geom = shape(feature.get("geometry") or {})
            if geom.is_empty or not geom.is_valid:
                counts["context_invalid_geometry"] += 1
                continue
            if not focus.intersects(geom):
                counts["context_outside_buffer"] += 1
                continue
        except Exception:
            counts["context_invalid_geometry"] += 1
            continue
        props = feature.get("properties") or {}
        height = props.get("height_m")
        if not isinstance(height, (int, float)) or not math.isfinite(float(height)) or float(height) <= 0:
            counts["context_missing_height_in_buffer"] += 1
            continue
        counts["context_with_height_in_buffer"] += 1
        duplicate = False
        for retained_geom in retained_geoms:
            if not geom.intersects(retained_geom):
                continue
            denom = min(float(geom.area), float(retained_geom.area))
            if denom > 0 and float(geom.intersection(retained_geom).area) / denom >= 0.80:
                duplicate = True
                break
        if duplicate:
            counts["context_duplicate_of_retained"] += 1
            continue
        shade_rows.append({
            "id": f"context_{props.get('id', feature.get('id', index))}",
            "geometry": geom, "height_m": float(height),
            "source": str(props.get("height_source") or "context buildings.geojson height_m"),
        })
    return shade_rows, counts, (origin_x, origin_y)


def _make_light_construction(template: OpaqueConstruction, target_u_factor: float,
                             identifier: str) -> OpaqueConstruction:
    materials = list(template.materials)
    indices = [i for i, material in enumerate(materials) if isinstance(material, EnergyMaterialNoMass)]
    insert_at = indices[0] if indices else 0

    def build(r_value: float) -> OpaqueConstruction:
        layers = list(materials)
        insulation = EnergyMaterialNoMass(
            safe_id(f"{identifier}_adjusted_insulation"), max(0.0001, float(r_value)),
            roughness="MediumRough", thermal_absorptance=0.9, solar_absorptance=0.7,
        )
        if indices:
            layers[insert_at] = insulation
        else:
            layers.insert(insert_at, insulation)
        return OpaqueConstruction(safe_id(identifier), layers)

    low, high = 0.0001, 64.0
    u_at_low, u_at_high = build(low).u_factor, build(high).u_factor
    if not (u_at_low >= target_u_factor >= u_at_high):
        raise ValueError(
            f"無法以木構低熱容材料組合匹配 CZ5 U-factor：{identifier}; "
            f"target={target_u_factor:.6f}, limits={u_at_low:.6f}/{u_at_high:.6f}"
        )
    for _ in range(70):
        middle = (low + high) / 2.0
        if build(middle).u_factor > target_u_factor:
            low = middle
        else:
            high = middle
    result = build((low + high) / 2.0)
    if abs(result.u_factor - target_u_factor) > 1e-6:
        raise ValueError(f"構造 U-factor 配對誤差過大：{identifier}")
    return result


def construction_sensitivity() -> tuple[Any, Any, dict[str, Any]]:
    heavy = construction_set_by_identifier(CZ5_MASS_ID)
    wood = construction_set_by_identifier(CZ5_WOOD_ID)
    light = heavy.duplicate()
    mass_wall = heavy.wall_set.exterior_construction
    mass_floor = heavy.floor_set.ground_construction
    mass_roof = heavy.roof_ceiling_set.exterior_construction
    light_wall = _make_light_construction(wood.wall_set.exterior_construction, mass_wall.u_factor, "E4_Light_Exterior_Wall")
    # The stock CZ5 wood-framed set still uses the same heavyweight ground slab
    # as the mass set. Replace the slab with a 38 mm timber deck, then tune
    # insulation to keep the same U-factor.
    light_floor_layers = []
    for material in mass_floor.materials:
        if "Normalweight Concrete Floor" in material.identifier:
            light_floor_layers.append(EnergyMaterial(
                "E4_Light_Timber_Floor_38mm", 0.038, 0.13, 500, 1600,
                roughness="MediumRough", thermal_absorptance=0.9,
                solar_absorptance=0.7,
            ))
        else:
            light_floor_layers.append(material)
    light_floor_template = OpaqueConstruction("E4_Light_Ground_Floor_Template", light_floor_layers)
    light_floor = _make_light_construction(light_floor_template, mass_floor.u_factor, "E4_Light_Ground_Floor")
    light_roof = _make_light_construction(wood.roof_ceiling_set.exterior_construction, mass_roof.u_factor, "E4_Light_Roof")
    light.wall_set.exterior_construction = light_wall
    light.floor_set.ground_construction = light_floor
    light.roof_ceiling_set.exterior_construction = light_roof
    comparisons = {}
    for name, mass_con, light_con in (
        ("exterior_wall", mass_wall, light_wall),
        ("ground_floor", mass_floor, light_floor),
        ("exterior_roof", mass_roof, light_roof),
    ):
        comparisons[name] = {
            "heavy_identifier": mass_con.identifier,
            "light_identifier": light_con.identifier,
            "heavy_u_factor_W_m2K": mass_con.u_factor,
            "light_u_factor_W_m2K": light_con.u_factor,
            "u_factor_delta_W_m2K": light_con.u_factor - mass_con.u_factor,
            "heavy_area_heat_capacity_J_m2K": mass_con.area_heat_capacity,
            "light_area_heat_capacity_J_m2K": light_con.area_heat_capacity,
            "heavy_mass_area_density_kg_m2": mass_con.mass_area_density,
            "light_mass_area_density_kg_m2": light_con.mass_area_density,
        }
    return heavy, light, comparisons


def _build_model(
    fabric_id: str, buildings: list[BuildingInput], retained: list[dict[str, Any]],
    construction_set: Any, cooling_enabled: bool, context_path: Path,
    sample_represented_area: dict[str, float] | None = None,
    omitted_neighbor_buildings: list[BuildingInput] | None = None,
    include_shades: bool = True,
    assign_ideal_air: bool = True,
) -> tuple[Model, dict[str, dict[str, Any]], dict[str, Any]]:
    if include_shades:
        shade_rows, shade_counts, (origin_x, origin_y) = _shade_inputs(retained, buildings, context_path)
    else:
        union = unary_union([building.geometry for building in buildings])
        min_x, min_y, _max_x, _max_y = union.bounds
        origin_x, origin_y = float(min_x), float(min_y)
        shade_rows = []
        shade_counts = {"all_shades_disabled_for_diagnostic": True}
    if include_shades and omitted_neighbor_buildings:
        for omitted in omitted_neighbor_buildings:
            shade_rows.append({
                "id": f"unmodeled_new_{omitted.building_id}",
                "geometry": omitted.geometry, "height_m": omitted.height_m,
                "source": "unmodeled new building in same plan, immediate neighbor of representative",
            })
        shade_counts["omitted_new_buildings_used_as_shade"] = len(omitted_neighbor_buildings)
    start = time.monotonic()
    rooms, room_meta, room_count = _building_rooms(
        buildings, origin_x, origin_y, construction_set, cooling_enabled, assign_ideal_air,
    )
    adjacency = _set_shared_walls_adiabatic(
        buildings, rooms, origin_x, origin_y, omitted_neighbor_buildings,
    )
    aperture_count = _add_exterior_apertures(rooms)
    shades: list[Shade] = []
    for row in shade_rows:
        shades.extend(_shade_faces(str(row["id"]), row["geometry"], float(row["height_m"]), origin_x, origin_y))
    model = Model(
        safe_id(f"E3E4_{fabric_id}_{'cool' if cooling_enabled else 'free'}"),
        rooms=rooms, orphaned_shades=shades,
    )
    model.properties.energy.construction_set = construction_set
    for room in rooms:
        building_id = room_meta[room.identifier]["building_id"]
        represented_area = (
            sample_represented_area.get(building_id, room_meta[room.identifier]["building_gfa_m2"])
            if sample_represented_area else room_meta[room.identifier]["building_gfa_m2"]
        )
        room_meta[room.identifier]["represented_gfa_m2"] = represented_area
        room_meta[room.identifier]["result_expansion_factor"] = (
            represented_area / room_meta[room.identifier]["building_gfa_m2"]
            if room_meta[room.identifier]["building_gfa_m2"] > 0 else 1.0
        )
    metadata = {
        "building_count": len(buildings),
        "room_count": room_count,
        "model_floor_area_m2_excluding_mezzanines": float(model.floor_area),
        "shade_object_count": len(shades),
        "shade_building_count": len(shade_rows),
        "shade_source_counts": shade_counts,
        "adjacency": adjacency,
        "aperture_count": aperture_count,
        "origin_epsg28992_m": [origin_x, origin_y],
        "local_coordinate_translation_m": [-origin_x, -origin_y],
        "model_build_seconds": time.monotonic() - start,
        "room_meta": room_meta,
    }
    return model, room_meta, metadata


def representative_sample(buildings: list[BuildingInput]) -> tuple[list[BuildingInput], dict[str, float], dict[str, Any]]:
    strata: dict[tuple[str, str], list[BuildingInput]] = defaultdict(list)
    for building in buildings:
        if building.height_m <= 10:
            height_bin = "<=10m"
        elif building.height_m <= 15:
            height_bin = "10-15m"
        else:
            height_bin = ">15m"
        strata[(building.use, height_bin)].append(building)
    selected: list[BuildingInput] = []
    represented_area: dict[str, float] = {}
    records = []
    for (use, height_bin), group in sorted(strata.items()):
        median_height = sorted(b.height_m for b in group)[len(group) // 2]
        median_floors = sorted(b.floors for b in group)[len(group) // 2]
        median_area = sorted(b.reported_gfa_m2 for b in group)[len(group) // 2]
        def score(b: BuildingInput) -> tuple[float, str]:
            area_ratio = abs(math.log(max(b.reported_gfa_m2, 0.001) / max(median_area, 0.001)))
            return (abs(b.height_m - median_height) + abs(b.floors - median_floors) * 2 + area_ratio * 4, b.building_id)
        representative = min(group, key=score)
        selected.append(representative)
        represented_area[representative.building_id] = sum(b.reported_gfa_m2 for b in group)
        records.append({
            "use": use, "height_bin": height_bin, "stratum_building_count": len(group),
            "representative_building_id": representative.building_id,
            "representative_floors": representative.floors,
            "representative_height_m": representative.height_m,
            "representative_modeled_gfa_m2": representative.modeled_gfa_m2,
            "stratum_gfa_m2": represented_area[representative.building_id],
            "expansion_factor": represented_area[representative.building_id] / representative.reported_gfa_m2,
        })
    return selected, represented_area, {
        "method": "deterministic one-medoid-per-use-and-total-height-bin; metrics expanded by stratum GFA",
        "height_bins_m": ["<=10m", "10-15m", ">15m"],
        "strata": records,
        "sampled_building_count": len(selected),
        "population_building_count": len(buildings),
        "limitations": [
            "一棟代表建築無法估計層內變異或提供統計信賴區間。",
            "尖峰依各分層代表建築同時段負荷乘以樓地板面積權重外推；層內時序差異未建模。",
            "E4 構造比較使用同一組分層代表建築，確保變體幾何相同。",
        ],
    }


def load_reuse_output(
    reuse_dir: Path, source_records: dict[str, Any], fabric_ids: list[str],
    engine_info: dict[str, Any],
) -> tuple[list[SimulationCase], dict[str, Any], list[SimulationCase], dict[str, Any]]:
    """Load successful prior cases only when all their source hashes still match."""
    manifest_path = reuse_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"既有輸出缺少 manifest.json：{reuse_dir}")
    prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prior_engines = prior_manifest.get("engines") or {}
    for key in ("openstudio_version", "energyplus_version"):
        if prior_engines.get(key) != engine_info.get(key):
            raise ValueError(f"不能沿用舊結果：{key} 與目前引擎版本不同")
    prior_sources = prior_manifest.get("source_files") or {}
    for source_name in ("weather", "context"):
        prior = prior_sources.get(source_name) or {}
        current = source_records.get(source_name) or {}
        if prior.get("sha256") != current.get("sha256"):
            raise ValueError(f"不能沿用舊結果：{source_name} SHA-256 與目前輸入不同")
    records_dir = reuse_dir / "run_records"
    if not records_dir.is_dir():
        raise FileNotFoundError(f"既有輸出缺少 run_records/：{reuse_dir}")
    reused_cases: list[SimulationCase] = []
    for record_path in sorted(records_dir.glob("*.json")):
        case = SimulationCase(**json.loads(record_path.read_text(encoding="utf-8")))
        if case.fabric_id not in fabric_ids:
            continue
        if case.status != "success" or not case.result:
            raise ValueError(f"舊 run_record 不是成功且有結果：{record_path}")
        reused_cases.append(case)

    if not reused_cases:
        raise ValueError(f"既有輸出沒有可沿用的 run_record：{reuse_dir}")
    prior_plans = prior_sources.get("plans") or {}
    current_plans = source_records.get("plans") or {}
    for fabric_id in sorted({case.fabric_id for case in reused_cases}):
        prior = prior_plans.get(fabric_id) or {}
        current = current_plans.get(fabric_id) or {}
        if prior.get("sha256") != current.get("sha256"):
            raise ValueError(f"不能沿用舊結果：{fabric_id} plan SHA-256 與目前輸入不同")
    prior_attempts_path = reuse_dir / "attempts.json"
    prior_attempts = []
    if prior_attempts_path.is_file():
        prior_attempts = [
            SimulationCase(**record)
            for record in json.loads(prior_attempts_path.read_text(encoding="utf-8"))
        ]
    reuse_samples = {
        fabric_id: record
        for fabric_id, record in (prior_manifest.get("sample") or {}).items()
        if fabric_id in fabric_ids
    }
    reuse_metadata = {
        "source_output_dir": str(reuse_dir.resolve()),
        "source_manifest_sha256": file_sha256(manifest_path),
        "source_script_version": (prior_manifest.get("script") or {}).get("version"),
        "source_script_sha256": (prior_manifest.get("script") or {}).get("sha256"),
        "reused_case_labels": [case.label for case in reused_cases],
        "reused_attempt_count": len(prior_attempts),
        "source_hashes_verified": True,
    }
    return reused_cases, reuse_samples, prior_attempts, reuse_metadata


def configure_engines() -> dict[str, Any]:
    if not (OPENSTUDIO_BIN / "openstudio").is_file():
        raise FileNotFoundError(f"OpenStudio executable missing: {OPENSTUDIO_BIN / 'openstudio'}")
    if not (ENERGYPLUS_BIN / "energyplus").is_file():
        raise FileNotFoundError(f"EnergyPlus executable missing: {ENERGYPLUS_BIN / 'energyplus'}")
    folders.openstudio_path = str(OPENSTUDIO_BIN)
    folders.energyplus_path = str(ENERGYPLUS_BIN)
    openstudio_version, energyplus_version = tuple(folders.openstudio_version), tuple(folders.energyplus_version)
    if openstudio_version[:2] != (3, 11) or energyplus_version[:2] != (25, 2):
        raise RuntimeError(f"引擎版本不符：OpenStudio={openstudio_version}, EnergyPlus={energyplus_version}")
    return {
        "openstudio_path": str(folders.openstudio_path),
        "openstudio_version": list(openstudio_version),
        "energyplus_path": str(folders.energyplus_path),
        "energyplus_version": list(energyplus_version),
        "honeybee_openstudio_module_available": importlib.util.find_spec("honeybee_openstudio") is not None,
        "translation_method": "Honeybee model_to_idf -> EnergyPlus CLI; OpenStudio configured/version checked but unused because honeybee_openstudio is absent",
    }


class CaseTimeout(RuntimeError):
    """Raised when one annual EnergyPlus case exceeds its time budget."""


def _norm_zone_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _sql_environment_period(cursor: sqlite3.Cursor) -> int:
    rows = cursor.execute(
        "SELECT EnvironmentPeriodIndex, EnvironmentType, EnvironmentName FROM EnvironmentPeriods"
    ).fetchall()
    weather_rows = [row for row in rows if int(row[1]) == 3]
    if not weather_rows:
        raise RuntimeError(f"EnergyPlus SQL 沒有 WeatherRunPeriod；環境列={rows[:8]}")
    return int(weather_rows[-1][0])


def extract_results(sql_path: Path, room_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not sql_path.is_file():
        raise FileNotFoundError(f"EnergyPlus 沒有產生 SQL：{sql_path}")
    connection = sqlite3.connect(f"file:{sql_path}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        environment_index = _sql_environment_period(cursor)
        wanted = {name.lower() for name in ENERGY_OUTPUTS}
        wanted.update({
            "zone operative temperature",
            "zone people occupant count",
        })
        dictionaries = cursor.execute(
            "SELECT ReportDataDictionaryIndex, KeyValue, Name, ReportingFrequency, Units "
            "FROM ReportDataDictionary"
        ).fetchall()
        selected = [
            row for row in dictionaries
            if str(row[2]).lower() in wanted and str(row[3]).lower() == "hourly"
        ]
        available_names = sorted({str(row[2]) for row in selected})
        absent_names = sorted(name for name in wanted if name not in {x.lower() for x in available_names})
        if not selected:
            raise RuntimeError("EnergyPlus SQL 沒有任何要求的 Hourly zone outputs。")

        alias_to_room: dict[str, str] = {}
        for room_id, meta in room_meta.items():
            for alias in (room_id, meta.get("display_name", "")):
                if alias:
                    alias_to_room[_norm_zone_key(alias)] = room_id
        dictionary_by_index = {}
        for row in selected:
            index, key, name, frequency, units = row
            normalized_key = _norm_zone_key(key)
            room_id = alias_to_room.get(normalized_key)
            if room_id is None and normalized_key.endswith("zone"):
                room_id = alias_to_room.get(normalized_key[:-4])
            if room_id is None:
                for suffix in ("idealloadsairsystem", "zone"):
                    if normalized_key.endswith(suffix):
                        room_id = alias_to_room.get(normalized_key[:-len(suffix)])
                        if room_id is not None:
                            break
            if room_id is None:
                for alias, aliased_room_id in alias_to_room.items():
                    if normalized_key.endswith(alias):
                        room_id = aliased_room_id
                        break
            dictionary_by_index[int(index)] = {
                "room_id": room_id, "key": str(key), "name": str(name),
                "units": str(units),
            }

        selected_indices = tuple(dictionary_by_index)
        placeholders = ",".join("?" for _ in selected_indices)
        sql = (
            "SELECT t.TimeIndex, t.Month, t.Day, t.Hour, "
            "rdd.ReportDataDictionaryIndex, SUM(rd.Value) "
            "FROM ReportData rd "
            "JOIN Time t ON t.TimeIndex = rd.TimeIndex "
            "JOIN ReportDataDictionary rdd "
            "ON rdd.ReportDataDictionaryIndex = rd.ReportDataDictionaryIndex "
            f"WHERE t.EnvironmentPeriodIndex = ? AND COALESCE(t.WarmupFlag, 0) = 0 "
            f"AND rd.ReportDataDictionaryIndex IN ({placeholders}) "
            "GROUP BY t.TimeIndex, t.Month, t.Day, t.Hour, rdd.ReportDataDictionaryIndex"
        )
        rows = cursor.execute(sql, (environment_index, *selected_indices))
        hourly: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
        date_by_time: dict[int, tuple[int, int, int]] = {}
        unmatched_keys: set[str] = set()
        matched_room_ids: set[str] = set()
        for time_index, month, day, hour, dictionary_index, value in rows:
            data = dictionary_by_index[int(dictionary_index)]
            room_id = data["room_id"]
            if room_id is None:
                unmatched_keys.add(data["key"])
                continue
            matched_room_ids.add(room_id)
            date_by_time[int(time_index)] = (int(month), int(day), int(hour))
            hourly[(data["name"].lower(), int(time_index))][room_id] = float(value)

        if len(matched_room_ids) < max(1, int(len(room_meta) * 0.95)):
            raise RuntimeError(
                "SQL zone key 無法對應到 Honeybee Room："
                f"matched={len(matched_room_ids)}/{len(room_meta)}, "
                f"unmatched examples={sorted(unmatched_keys)[:12]}"
            )
        available = {x.lower() for x in available_names}
        missing_required = [
            name for name in (
                "Zone Ideal Loads Supply Air Total Heating Energy",
                "Zone Ideal Loads Supply Air Total Cooling Energy",
                "Zone Ideal Loads Supply Air Total Heating Rate",
                "Zone Ideal Loads Supply Air Total Cooling Rate",
                "Zone Operative Temperature",
            ) if name.lower() not in available
        ]
        if missing_required:
            raise RuntimeError(f"SQL 缺必要輸出變數：{missing_required}; available={available_names}")

        variable_totals_j = defaultdict(float)
        hourly_rates_w: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        overheat_hours_area = 0.0
        occupied_overheat_hours_area = 0.0
        unweighted_overheat_zone_hours = 0
        summer_hours = 0
        winter_heating_j = 0.0
        weighted_floor_area = sum(
            float(meta["floor_area_m2"]) * float(meta["result_expansion_factor"])
            for meta in room_meta.values()
        )

        for (name, time_index), zones in hourly.items():
            month = date_by_time.get(time_index, (0, 0, 0))[0]
            is_summer = month in SUMMER_MONTHS
            is_winter = month in WINTER_MONTHS
            for room_id, value in zones.items():
                meta = room_meta[room_id]
                factor = float(meta["result_expansion_factor"])
                weight = float(meta["floor_area_m2"]) * factor
                if name.endswith(" energy"):
                    variable_totals_j[name] += value * factor
                    if is_winter and "heating" in name:
                        winter_heating_j += value * factor
                if name.endswith(" rate"):
                    hourly_rates_w[name][time_index] += value * factor
                if name == "zone operative temperature" and is_summer:
                    summer_hours += 1
                    if value > OVERHEAT_THRESHOLD_C:
                        overheat_hours_area += weight
                        unweighted_overheat_zone_hours += 1
                        occ_values = hourly.get(("zone people occupant count", time_index), {})
                        if float(occ_values.get(room_id, 0.0)) > 0:
                            occupied_overheat_hours_area += weight

        variable_keys = {
            "heating_energy": "zone ideal loads supply air total heating energy",
            "cooling_energy": "zone ideal loads supply air total cooling energy",
            "lights_electricity": "zone lights electricity energy",
            "equipment_electricity": "zone electric equipment electricity energy",
            "fan_electricity": "zone ventilation fan electricity energy",
            "gas_equipment": "zone gas equipment naturalgas energy",
            "water_heating": "water use equipment heating energy",
        }
        energy_kwh = {
            key: variable_totals_j.get(name, 0.0) / JOULES_PER_KWH
            for key, name in variable_keys.items()
        }
        if variable_keys["gas_equipment"] in absent_names:
            energy_kwh["gas_equipment"] = None
        heating_kwh = energy_kwh["heating_energy"]
        cooling_kwh = energy_kwh["cooling_energy"]
        direct_electricity_kwh = (
            energy_kwh["lights_electricity"] +
            energy_kwh["equipment_electricity"] +
            energy_kwh["fan_electricity"]
        )
        estimated_electricity_kwh = (
            direct_electricity_kwh +
            heating_kwh / HEATING_COP +
            cooling_kwh / COOLING_COP +
            energy_kwh["water_heating"] / HOT_WATER_COP
        )

        def peak_kw(rate_name: str) -> float:
            values = hourly_rates_w.get(rate_name, {})
            return max(values.values(), default=0.0) / 1000.0

        return {
            "annual_heating_demand_kwh_thermal": heating_kwh,
            "annual_cooling_demand_kwh_thermal": cooling_kwh,
            "winter_heating_demand_kwh_thermal_dec_feb": winter_heating_j / JOULES_PER_KWH,
            "direct_electricity_kwh_lights_equipment_fans": direct_electricity_kwh,
            "estimated_hvac_and_hot_water_electricity_kwh": (
                estimated_electricity_kwh - direct_electricity_kwh
            ),
            "estimated_total_electricity_kwh": estimated_electricity_kwh,
            "gas_equipment_kwh_thermal_reported_separately": energy_kwh["gas_equipment"],
            "peak_heating_load_kw_thermal_hourly_sum": peak_kw(
                "zone ideal loads supply air total heating rate"
            ),
            "peak_cooling_load_kw_thermal_hourly_sum": peak_kw(
                "zone ideal loads supply air total cooling rate"
            ),
            "summer_operating_hours": summer_hours,
            "summer_overheated_area_weighted_hours_per_m2_basis": (
                overheat_hours_area / weighted_floor_area if weighted_floor_area else 0.0
            ),
            "summer_occupied_overheated_area_weighted_hours_per_m2_basis": (
                occupied_overheat_hours_area / weighted_floor_area if weighted_floor_area else 0.0
            ),
            "summer_overheated_zone_hours": unweighted_overheat_zone_hours,
            "weighted_floor_area_m2": weighted_floor_area,
            "sql_environment_period_index": environment_index,
            "sql_hourly_data_points": len(date_by_time),
            "sql_missing_optional_outputs": absent_names,
            "sql_unmatched_zone_keys": sorted(unmatched_keys),
            "sql_matched_room_count": len(matched_room_ids),
            "sql_expected_room_count": len(room_meta),
            "energy_output_kwh": energy_kwh,
        }
    finally:
        connection.close()


def _simulation_output() -> SimulationOutput:
    output = SimulationOutput(
        reporting_frequency="Hourly", include_sqlite=True, include_html=False,
        summary_reports=(),
    )
    output.add_zone_energy_use()
    output.add_comfort_metrics()
    output.add_output("Zone Ideal Loads Supply Air Total Heating Rate")
    output.add_output("Zone Ideal Loads Supply Air Total Cooling Rate")
    output.add_output("Zone People Occupant Count")
    return output


def _diagnostic_output_without_hvac() -> SimulationOutput:
    output = SimulationOutput(
        reporting_frequency="Hourly", include_sqlite=True, include_html=False,
        summary_reports=(),
    )
    output.add_comfort_metrics()
    return output


def run_case(
    fabric_id: str, buildings: list[BuildingInput], retained: list[dict[str, Any]],
    construction_set: Any, construction_label: str, cooling_enabled: bool,
    context_path: Path, weather_path: Path, run_dir: Path,
    represented_area: dict[str, float] | None, max_seconds: float,
    omitted_neighbor_buildings: list[BuildingInput] | None = None,
    include_shades: bool = True,
    solar_distribution: str = "FullExterior",
    assign_ideal_air: bool = True,
) -> SimulationCase:
    label = f"{fabric_id}_{construction_label}_{'cooling_on' if cooling_enabled else 'heating_only'}"
    case = SimulationCase(
        label, fabric_id, construction_label, cooling_enabled,
        represented_area is not None, "building", str(run_dir),
    )
    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        model, room_meta, metadata = _build_model(
            fabric_id, buildings, retained, construction_set, cooling_enabled,
            context_path, represented_area, omitted_neighbor_buildings, include_shades,
            assign_ideal_air,
        )
        for room_id, meta in room_meta.items():
            meta["display_name"] = str(next(
                room.display_name for room in model.rooms if room.identifier == room_id
            ) or "")
        case.model_build_seconds = float(metadata["model_build_seconds"])
        if time.monotonic() - started >= max_seconds:
            raise CaseTimeout("幾何／Honeybee 模型建立已超過單案時間上限")

        schedules_dir = run_dir / "schedules"
        schedules_dir.mkdir()
        simulation_parameter = SimulationParameter(
            output=(
                _simulation_output() if assign_ideal_air
                else _diagnostic_output_without_hvac()
            ),
            run_period=RunPeriod(), timestep=6,
            shadow_calculation=ShadowCalculation(
                solar_distribution=solar_distribution,
                calculation_method="PolygonClipping",
                calculation_update_method="Periodic",
                calculation_frequency=30,
                maximum_figures=15000,
            ),
            simulation_control=SimulationControl(
                do_zone_sizing=False, do_system_sizing=False, do_plant_sizing=False,
                run_for_sizing_periods=False, run_for_run_periods=True,
            ),
            terrain_type="City",
        )
        translate_started = time.monotonic()
        model_idf = model_to_idf(
            model, schedule_directory=str(schedules_dir),
            use_ideal_air_equivalent=True, patch_missing_adjacencies=False,
            timestep=6,
        )
        idf_text = "\n\n".join((simulation_parameter.to_idf(), str(model_idf)))
        case.idf_translation_seconds = time.monotonic() - translate_started
        idf_path = run_dir / "in.idf"
        idf_path.write_text(str(idf_text), encoding="utf-8")
        if time.monotonic() - started >= max_seconds:
            raise CaseTimeout("Honeybee IDF 轉譯已超過單案時間上限")

        energyplus = ENERGYPLUS_BIN / "energyplus"
        stdout_path, stderr_path = run_dir / "energyplus.stdout.log", run_dir / "energyplus.stderr.log"
        command = [
            str(energyplus), "--annual", "--expandobjects", "--weather", str(weather_path),
            "--output-directory", str(run_dir / "output"),
            str(idf_path),
        ]
        (run_dir / "output").mkdir()
        case_record = {
            "label": label, "command": command,
            "weather_sha256": file_sha256(weather_path),
            "idf_sha256": hashlib.sha256(idf_path.read_bytes()).hexdigest(),
            "model_metadata": metadata,
            "cooling_enabled": cooling_enabled,
            "construction": construction_label,
            "sample_mode": represented_area is not None,
        }
        (run_dir / "case-input.json").write_text(
            json.dumps(case_record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        sim_started = time.monotonic()
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
                completed = subprocess.run(
                    command, cwd=run_dir, stdout=stdout, stderr=stderr,
                    timeout=max(1.0, max_seconds - (time.monotonic() - started)),
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            case.simulation_seconds = time.monotonic() - sim_started
            case.status = "timed_out"
            case.error = f"EnergyPlus 超過單案上限 {max_seconds:.0f} 秒"
            (run_dir / "case-result.json").write_text(
                json.dumps(asdict(case), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            raise CaseTimeout(case.error) from exc
        case.simulation_seconds = time.monotonic() - sim_started
        case.exit_code = int(completed.returncode)
        if completed.returncode != 0:
            case.status = "failed"
            case.error = f"EnergyPlus exit code {completed.returncode}"
            raise RuntimeError(case.error)
        err_path = run_dir / "output" / "eplusout.err"
        diagnostic_severe_lines: list[str] = []
        if err_path.exists():
            diagnostic_severe_lines = [
                line.strip() for line in err_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if "** Severe **" in line
            ]
            fatal_lines = [
                line.strip() for line in err_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if "** Fatal **" in line or "Terminated--Fatal Error Detected" in line
            ]
            if fatal_lines:
                case.status = "failed"
                case.error = "EnergyPlus fatal errors: " + " | ".join(fatal_lines[:8])
                raise RuntimeError(case.error)
        case.result = (
            extract_results(run_dir / "output" / "eplusout.sql", room_meta)
            if assign_ideal_air else {"diagnostic_only_no_hvac": True}
        )
        case.result.update({
            "energyplus_severe_diagnostic_lines": diagnostic_severe_lines,
            "model_metadata": {
                key: value for key, value in metadata.items() if key != "room_meta"
            },
            "model_floor_area_m2_excluding_mezzanines": float(model.floor_area),
            "modeled_building_count": len(buildings),
            "modeled_room_count": len(model.rooms),
            "construction_set": construction_set.identifier,
        })
        case.status = "success"
        return case
    finally:
        if case.status not in ("success", "timed_out"):
            case.status = "failed"
            case.error = case.error or "模擬流程失敗"
        case_record = asdict(case)
        (run_dir / "case-result.json").write_text(
            json.dumps(case_record, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _write_svg(path: Path, title: str, groups: list[dict[str, Any]], subtitle: str, left: int = 310, right: int = 90) -> None:
    width, row_height = 1100, 94
    height = 150 + row_height * len(groups)
    colors = {
        "重質": "#355c7d", "輕質": "#d77841", "方案": "#4b8063",
        "Heavy mass": "#355c7d", "Light": "#d77841", "Scheme": "#4b8063",
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<text x="42" y="52" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="#202b31">{title}</text>',
        f'<text x="42" y="82" font-family="Arial,sans-serif" font-size="15" fill="#52616a">{subtitle}</text>',
    ]
    for index, group in enumerate(groups):
        y = 128 + index * row_height
        name = str(group["label"])
        values = group["values"]
        unit = str(group.get("unit", ""))
        max_value = max([float(item["value"]) for item in values] + [0.000001])
        plot_width = width - left - right
        parts.append(f'<text x="42" y="{y+25}" font-family="Arial,sans-serif" font-size="15" font-weight="700" fill="#26343a">{name}</text>')
        parts.append(f'<text x="42" y="{y+48}" font-family="Arial,sans-serif" font-size="13" fill="#667780">{unit}</text>')
        for j, item in enumerate(values):
            key, value = str(item["series"]), float(item["value"])
            bar_y = y + 5 + j * 34
            bar_width = max(1.0, plot_width * value / max_value)
            color = colors.get(key, "#4b8063")
            parts.append(f'<text x="{left-14}" y="{bar_y+18}" text-anchor="end" font-family="Arial,sans-serif" font-size="14" fill="#40515a">{key}</text>')
            parts.append(f'<rect x="{left}" y="{bar_y}" width="{bar_width:.2f}" height="24" rx="3" fill="{color}"/>')
            parts.append(f'<text x="{left+bar_width+9:.2f}" y="{bar_y+18}" font-family="Arial,sans-serif" font-size="14" fill="#26343a">{_fmt(value, 1)}</text>')
        parts.append(f'<line x1="{left}" y1="{y+row_height-4}" x2="{width-right}" y2="{y+row_height-4}" stroke="#d9dedc" stroke-width="1"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _render_e4_svg_to_png(
    svg_path: Path,
    png_path: Path,
    groups: list[dict[str, Any]],
    title: str,
    subtitle: str,
    left: int = 340,
) -> None:
    """Render E4 SVG to PNG, attempting svg_to_png (playwright) and falling back to PIL."""
    svg_to_png_script = Path(__file__).resolve().parent / "svg_to_png.py"
    for py_bin in (sys.executable, "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "python3"):
        try:
            res = subprocess.run(
                [py_bin, str(svg_to_png_script), str(svg_path), str(png_path), "2.0"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0 and png_path.is_file() and png_path.stat().st_size > 0:
                return
        except Exception:
            pass

    from PIL import Image, ImageDraw, ImageFont
    W, H = 2200, 864
    im = Image.new("RGB", (W, H), (251, 250, 247))
    dr = ImageDraw.Draw(im)

    font_path = "/System/Library/Fonts/Helvetica.ttc"
    if not Path(font_path).is_file():
        font_path = None
    font_bold = lambda s: ImageFont.truetype(font_path, s) if font_path else ImageFont.load_default()
    font_reg = lambda s: ImageFont.truetype(font_path, s) if font_path else ImageFont.load_default()

    dr.text((84, 80), title, fill=(32, 43, 49), font=font_bold(56))
    dr.text((84, 155), subtitle, fill=(82, 97, 106), font=font_reg(30))

    scaled_left = left * 2
    right = 180
    plot_width = W - scaled_left - right
    colors = {
        "Heavy mass": (53, 92, 125), "Light": (215, 120, 65),
        "重質": (53, 92, 125), "輕質": (215, 120, 65),
        "方案": (75, 128, 99), "Scheme": (75, 128, 99),
    }

    for idx, group in enumerate(groups):
        y = 256 + idx * 188
        name = str(group["label"])
        unit = str(group.get("unit", ""))
        vals = group["values"]
        dr.text((84, y + 45), name, fill=(38, 52, 58), font=font_bold(32))
        dr.text((84, y + 90), unit, fill=(102, 119, 128), font=font_reg(26))

        mx_val = max([float(item["value"]) for item in vals] + [0.000001])
        for j, item in enumerate(vals):
            key, value = str(item["series"]), float(item["value"])
            bar_y = y + 10 + j * 68
            bar_w = int(max(2.0, plot_width * value / mx_val))
            col = colors.get(key, (75, 128, 99))

            bb_k = dr.textbbox((0, 0), key, font=font_reg(28))
            kw = bb_k[2] - bb_k[0]
            dr.text((scaled_left - 28 - kw, bar_y + 10), key, fill=(64, 81, 90), font=font_reg(28))

            dr.rounded_rectangle([scaled_left, bar_y, scaled_left + bar_w, bar_y + 48], radius=6, fill=col)
            val_str = f"{value:,.1f}"
            dr.text((scaled_left + bar_w + 18, bar_y + 10), val_str, fill=(38, 52, 58), font=font_reg(28))

        dr.line([(scaled_left, y + 188 - 8), (W - right, y + 188 - 8)], fill=(217, 222, 220), width=2)

    png_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(png_path)


def render_e4_harbour_mass_vs_light_figure(
    e4_data: dict[str, Any],
    output_png: Path,
    language: str = "zh",
    output_svg: Optional[Path] = None,
) -> Path:
    """Render E4 Harbour thermal mass sensitivity chart (SVG and PNG)."""
    if language == "en":
        title = "E4 Harbour Thermal Mass Sensitivity (Heavy Mass vs Light Construction)"
        subtitle = "Heavy mass: CZ5 Mass; Light: low thermal mass, U-factor matched; exploratory, not energy certification."
        groups = [
            {
                "label": "Summer Overheating (heating only)",
                "unit": "Floor-weighted hours/year",
                "values": [
                    {"series": "Heavy mass", "value": e4_data["summer_overheating_mass"]},
                    {"series": "Light", "value": e4_data["summer_overheating_light"]},
                ],
            },
            {
                "label": "Winter Heating Demand (Dec–Feb)",
                "unit": "kWh-thermal",
                "values": [
                    {"series": "Heavy mass", "value": e4_data["winter_heating_mass"]},
                    {"series": "Light", "value": e4_data["winter_heating_light"]},
                ],
            },
            {
                "label": "Peak Cooling Load (cooling on)",
                "unit": "kW-thermal",
                "values": [
                    {"series": "Heavy mass", "value": e4_data["peak_cooling_mass"]},
                    {"series": "Light", "value": e4_data["peak_cooling_light"]},
                ],
            },
        ]
        left_margin = 430  # English metric titles are wider than the Chinese ones
    else:
        title = "E4 港埠蓄熱構造敏感度"
        subtitle = "重質：CZ5 Mass；輕質：低熱容、U-factor 配對；探索性；非能源認證。"
        groups = [
            {
                "label": "夏季過熱（只開暖氣）",
                "unit": "樓地板加權小時/年",
                "values": [
                    {"series": "重質", "value": e4_data["summer_overheating_mass"]},
                    {"series": "輕質", "value": e4_data["summer_overheating_light"]},
                ],
            },
            {
                "label": "冬季暖氣需求（12–2月）",
                "unit": "kWh-熱",
                "values": [
                    {"series": "重質", "value": e4_data["winter_heating_mass"]},
                    {"series": "輕質", "value": e4_data["winter_heating_light"]},
                ],
            },
            {
                "label": "尖峰冷負荷（冷氣開啟）",
                "unit": "kW-熱",
                "values": [
                    {"series": "重質", "value": e4_data["peak_cooling_mass"]},
                    {"series": "輕質", "value": e4_data["peak_cooling_light"]},
                ],
            },
        ]
        left_margin = 310

    target_svg = output_svg or output_png.with_suffix(".svg")
    _write_svg(target_svg, title, groups, subtitle, left=left_margin, right=130 if language == "en" else 90)
    _render_e4_svg_to_png(target_svg, output_png, groups, title, subtitle, left=left_margin)
    return output_png


def _case_summary(case: SimulationCase, plan_gfa_m2: float) -> dict[str, Any]:
    if not case.result:
        raise ValueError(f"成功案例缺少結果：{case.label}")
    result = case.result
    return {
        "fabric_id": case.fabric_id, "label": case.label,
        "construction": case.construction, "cooling_enabled": case.cooling_enabled,
        "sample_mode": case.sample_mode,
        "modeled_building_count": result.get("modeled_building_count"),
        "modeled_room_count": result.get("modeled_room_count"),
        "estimated_total_electricity_kwh": result["estimated_total_electricity_kwh"],
        "annual_heating_demand_kwh_thermal": result["annual_heating_demand_kwh_thermal"],
        "annual_cooling_demand_kwh_thermal": result["annual_cooling_demand_kwh_thermal"],
        "eui_kwh_m2_year": result["estimated_total_electricity_kwh"] / plan_gfa_m2 if plan_gfa_m2 else None,
        "new_gfa_denominator_m2": plan_gfa_m2,
        "modeled_floor_area_m2_excluding_mezzanines": result["model_floor_area_m2_excluding_mezzanines"],
        "peak_heating_kw_thermal": result["peak_heating_load_kw_thermal_hourly_sum"],
        "peak_cooling_kw_thermal": result["peak_cooling_load_kw_thermal_hourly_sum"],
        "winter_heating_kwh_thermal_dec_feb": result["winter_heating_demand_kwh_thermal_dec_feb"],
        "summer_overheated_area_weighted_hours": result["summer_overheated_area_weighted_hours_per_m2_basis"],
        "summer_occupied_overheated_area_weighted_hours": result["summer_occupied_overheated_area_weighted_hours_per_m2_basis"],
        "case_wall_seconds": case.model_build_seconds + case.idf_translation_seconds + case.simulation_seconds,
        "simulation_seconds": case.simulation_seconds,
    }


def write_outputs(
    output_dir: Path, cases: list[SimulationCase], plan_info: dict[str, dict[str, Any]],
    fabric_names: dict[str, str], sample_info: dict[str, Any] | None,
    source_records: dict[str, Any], engine_info: dict[str, Any],
    construction_info: dict[str, Any], assumptions: list[str],
    started_utc: str, total_wall_seconds: float,
    attempts: list[SimulationCase] | None = None,
    reused_results: dict[str, Any] | None = None,
    simulation_script: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_records = output_dir / "run_records"
    run_records.mkdir(exist_ok=True)
    summaries: list[dict[str, Any]] = []
    for case in cases:
        plan_gfa = float(plan_info[case.fabric_id].get("new_gfa_m2") or sum(
            item["modeled_gfa_m2"] for item in plan_info[case.fabric_id]["buildings"]
        ))
        summaries.append(_case_summary(case, plan_gfa))
        (run_records / f"{safe_id(case.label)}.json").write_text(
            json.dumps(asdict(case), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    fan_missing_cases = [
        case.label for case in cases if case.result and any(
            item.lower() == "zone ventilation fan electricity energy"
            for item in case.result.get("sql_missing_optional_outputs", [])
        )
    ]
    gas_missing_cases = [
        case.label for case in cases if case.result and any(
            item.lower() == "zone gas equipment naturalgas energy"
            for item in case.result.get("sql_missing_optional_outputs", [])
        )
    ]
    attempt_records = [asdict(case) for case in (attempts or [])]
    if attempt_records:
        (output_dir / "attempts.json").write_text(
            json.dumps(attempt_records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    e3_by_fabric = {
        row["fabric_id"]: row for row in summaries
        if row["construction"] == "CZ5_Mass" and row["cooling_enabled"]
    }
    if not e3_by_fabric:
        raise ValueError("沒有完成的 E3 重質構造冷氣開啟方案結果。")

    harbor = {
        (row["construction"], row["cooling_enabled"]): row for row in summaries
        if row["fabric_id"] == "harbour_grain"
    }
    mass_on = harbor.get(("CZ5_Mass", True))
    mass_off = harbor.get(("CZ5_Mass", False))
    light_on = harbor.get(("CZ5_Light_U_Matched", True))
    light_off = harbor.get(("CZ5_Light_U_Matched", False))

    csv_columns = [
        ("分析", "analysis"), ("方案", "fabric"), ("建模範圍", "model_scope"),
        ("計算建築棟數", "modeled_building_count"), ("建模熱區數", "modeled_room_count"),
        ("構造", "construction"),
        ("冷氣", "cooling"), ("估算總用電_kWh", "estimated_total_electricity_kwh"),
        ("暖氣需求_kWh_熱", "annual_heating_demand_kwh_thermal"),
        ("冷氣需求_kWh_熱", "annual_cooling_demand_kwh_thermal"),
        ("EUI_kWh_m2年", "eui_kwh_m2_year"), ("新建GFA分母_m2", "new_gfa_denominator_m2"),
        ("模型樓地板_m2", "modeled_floor_area_m2_excluding_mezzanines"),
        ("尖峰暖氣_kW_熱", "peak_heating_kw_thermal"), ("尖峰冷氣_kW_熱", "peak_cooling_kw_thermal"),
        ("冬季暖氣需求_kWh_熱", "winter_heating_kwh_thermal_dec_feb"),
        ("夏季過熱時數_樓地板加權", "summer_overheated_area_weighted_hours"),
        ("模擬秒", "simulation_seconds"),
    ]
    with (output_dir / "e3e4_results_zh.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=[label for label, _ in csv_columns])
        writer.writeheader()
        for row in summaries:
            out = {}
            for label, key in csv_columns:
                if key == "analysis":
                    out[label] = "E3/E4"
                elif key == "fabric":
                    out[label] = fabric_names.get(row["fabric_id"], row["fabric_id"])
                elif key == "model_scope":
                    population = (sample_info or {}).get(row["fabric_id"], {}).get("population_building_count")
                    if row["sample_mode"]:
                        out[label] = f"抽樣（{row['modeled_building_count']}/{population or '?'} 棟）"
                    else:
                        out[label] = f"全量（{row['modeled_building_count']} 棟）"
                elif key == "cooling":
                    out[label] = "開" if row["cooling_enabled"] else "關（只開暖氣）"
                else:
                    out[label] = row.get(key, "")
            writer.writerow(out)

    e3_rows = [
        "| 方案 | 建模範圍 | 新建 GFA (m²) | 估算總用電 (kWh/年) | 暖氣需求 (kWh-熱/年) | 冷氣需求 (kWh-熱/年) | EUI (kWh/m²·年) | 尖峰暖氣 (kW-熱) | 尖峰冷氣 (kW-熱) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fabric_id, row in e3_by_fabric.items():
        population = (sample_info or {}).get(fabric_id, {}).get("population_building_count")
        scope = (
            f"抽樣 {row['modeled_building_count']}/{population or '?'} 棟"
            if row["sample_mode"] else f"全量 {row['modeled_building_count']} 棟"
        )
        e3_rows.append(
            f"| {fabric_names.get(fabric_id, fabric_id)} | {scope} | {_fmt(row['new_gfa_denominator_m2'])} "
            f"| {_fmt(row['estimated_total_electricity_kwh'])} | {_fmt(row['annual_heating_demand_kwh_thermal'])} "
            f"| {_fmt(row['annual_cooling_demand_kwh_thermal'])} | {_fmt(row['eui_kwh_m2_year'], 2)} "
            f"| {_fmt(row['peak_heating_kw_thermal'])} | {_fmt(row['peak_cooling_kw_thermal'])} |"
        )
    lines = [
        "# E3 建築耗能＋E4 蓄熱敏感度",
        "",
        "**探索性；非能源認證。** 使用使用者指定的衍生 EPW 與 Honeybee-Energy／EnergyPlus 理想負荷模型。",
        "",
        "## E3 年度方案比較",
        "",
        *e3_rows,
        "",
        f"估算總用電由照明、插座設備、可用的風機用電，加上理想負荷熱量按暖氣 COP 2.5、冷氣 COP 3.0、熱水 COP 1.0 折算。{len(fan_missing_cases)}/{len(cases)} 個成功模擬組合缺少 Zone Ventilation Fan Electricity Energy 輸出，計算時風機用電按 0 處理，因此本表所有受影響方案的估算總用電與 EUI 未含 HVAC 風機電力；缺值案例標籤詳見 manifest。暖氣與冷氣需求是 EnergyPlus 理想負荷供應熱量，不是實測燃料或電表用電。{len(gas_missing_cases)}/{len(cases)} 個成功組合缺少 Zone Gas Equipment NaturalGas Energy 輸出，run_records 以 null 表示未知，不代表實際用量為零。",
        "",
        "EUI 分母採方案 new_gfa_m2（含 mezzanine），mezzanine 未另建模。尖峰是每小時各 zone 同步負荷加總後取最大值。",
        "",
        "## E4 港埠重質／輕質構造比較",
        "",
    ]
    if all((mass_on, mass_off, light_on, light_off)):
        lines += [
            "| 指標 | 重質 | 輕質 | 輕質減重質 |",
            "|---|---:|---:|---:|",
            f"| 夏季過熱時數（只開暖氣，樓地板加權小時/年） | {_fmt(mass_off['summer_overheated_area_weighted_hours'])} | {_fmt(light_off['summer_overheated_area_weighted_hours'])} | {_fmt(light_off['summer_overheated_area_weighted_hours'] - mass_off['summer_overheated_area_weighted_hours'])} |",
            f"| 夏季有人時過熱時數（樓地板加權小時/年） | {_fmt(mass_off['summer_occupied_overheated_area_weighted_hours'])} | {_fmt(light_off['summer_occupied_overheated_area_weighted_hours'])} | {_fmt(light_off['summer_occupied_overheated_area_weighted_hours'] - mass_off['summer_occupied_overheated_area_weighted_hours'])} |",
            f"| 冬季暖氣需求（12–2 月，kWh-熱） | {_fmt(mass_on['winter_heating_kwh_thermal_dec_feb'])} | {_fmt(light_on['winter_heating_kwh_thermal_dec_feb'])} | {_fmt(light_on['winter_heating_kwh_thermal_dec_feb'] - mass_on['winter_heating_kwh_thermal_dec_feb'])} |",
            f"| 尖峰冷負荷（冷氣開啟，kW-熱） | {_fmt(mass_on['peak_cooling_kw_thermal'])} | {_fmt(light_on['peak_cooling_kw_thermal'])} | {_fmt(light_on['peak_cooling_kw_thermal'] - mass_on['peak_cooling_kw_thermal'])} |",
            "",
            "過熱時數使用 6–8 月逐小時 Zone Operative Temperature >26°C，並以樓地板面積加權平均。過熱版本關閉冷氣、保留暖氣設定；冬季需求和尖峰冷負荷使用冷暖氣皆開啟的年度模型。",
            "",
            "重質採 ASHRAE CZ5 Mass。輕質沿用 CZ5 WoodFramed 外牆與屋頂材料；其標準組仍採混凝土地坪，因此以 38 mm 木質地板層替換 203 mm 混凝土板，並調整非質量保溫層，將外牆、地坪、屋頂 U-factor 配對。其他條件相同。",
        ]
    else:
        lines += ["E4 四個構造／冷氣組合尚未全部完成；不以缺值填補比較。"]
    lines += [
        "",
        "## 建模方法與限制",
        "",
        "- 每層一個 Honeybee Room／EnergyPlus zone；逐層建模樓板、屋頂與底層邊界。足跡共邊至少 0.5 m 的建築共用垂直牆設 Adiabatic。",
        "- 新建建築依 footprint 建模；保留建築與 100 m 即時脈絡範圍內有來源高度的建築建成遮陽面。脈絡 GeoJSON 無 CRS 欄位，依座標範圍與方案位置吻合假設 EPSG:28992；缺高度的遮陽建築排除，不推估高度。",
        "- 用途對應：住宅 MidriseApartment；工業 Warehouse。候選對照：商辦 MediumOffice、零售／商業 Retail、公民／公共 Courthouse。四案實際用途為住宅與工業。",
        "- 採 ASHRAE 2019 climate zone 5 Mass 作鹿特丹近 CZ4A–5A 的保守探索性近似，不代表當地法規或認證。新建外牆 WWR 40% 為假設。",
        "- 方案 mezzanine GFA 未另建模；幾何孔洞未作內院開挖。標準 program schedules 與理想負荷 HVAC 未經現地校準；未模擬逐案控制、通風或真實系統效率。",
        "- Honeybee 直接寫 IDF 並執行 EnergyPlus；已設定並驗證 OpenStudio 路徑與版本，但環境未安裝 honeybee-openstudio，故 OpenStudio 未參與本次轉譯或模擬。",
        "- EPW 為 8760 小時衍生 TMY；結果不代表現場能耗、極端年份或能源認證。",
        "",
        "## 執行與來源",
        "",
        f"- 開始 UTC：{started_utc}；總流程時間：{total_wall_seconds:.1f} 秒。",
        f"- Python {sys.version.split()[0]}；OpenStudio {'.'.join(map(str, engine_info['openstudio_version']))}；EnergyPlus {'.'.join(map(str, engine_info['energyplus_version']))}。",
        f"- EPW SHA-256：{source_records['weather']['sha256']}。",
        "- 每案建模、IDF 轉譯、EnergyPlus 秒數、plan／context SHA-256、假設及版本詳見 manifest.json。",
    ]
    severe_diagnostics = sorted({
        line
        for case in cases
        if case.result
        for line in case.result.get("energyplus_severe_diagnostic_lines", [])
    })
    if severe_diagnostics:
        lines += [
            "",
            "## EnergyPlus 幾何診斷",
            "",
            "模擬雖完成，EnergyPlus 對陰影幾何發出 severe diagnostic（非 fatal termination）；因此陰影值需保守解讀：",
            *[f"- {line}" for line in severe_diagnostics[:8]],
        ]
    if sample_info:
        lines += [
            "",
            "## 代表性抽樣",
            "",
            "下列方案採依用途及總高度分層的 deterministic medoid；各層指標按層 GFA 加權外推。每層只選一棟，無法估計層內變異或提供統計信賴區間；尖峰由代表建築同時段負荷按 GFA 加權，未反映層內時序差異。未列於抽樣清單的方案使用全量建築。",
        ]
        for fabric_id, record in sample_info.items():
            lines.append(
                f"- {fabric_names.get(fabric_id, fabric_id)}：{record['sampled_building_count']}/"
                f"{record['population_building_count']} 棟；代表建築與權重："
            )
            for stratum in record.get("strata", []):
                lines.append(
                    f"  - {stratum['use']}／{stratum['height_bin']}：{stratum['representative_building_id']}，"
                    f"代表 {stratum['representative_modeled_gfa_m2']:.1f} m²，"
                    f"該層 {stratum['stratum_gfa_m2']:.1f} m²，"
                    f"外推係數 {stratum['expansion_factor']:.3f}。"
                )
    else:
        lines += ["", "本次港埠方案使用全量建築，未啟用代表性抽樣。"]
    if reused_results:
        lines += [
            "",
            "## 港埠既有成功案例核對",
            "",
            f"港埠數值沿用已封存輸出的 {len(reused_results.get('reused_case_labels', []))} 份成功 run_records；" 
            "目前 EPW、脈絡、方案及 OpenStudio／EnergyPlus 版本雜湊核對一致。原始全量逾時與失敗抽樣嘗試保留在封存包及本次 attempts.json。",
            "沿用來源 manifest SHA-256：" + str(reused_results.get("source_manifest_sha256")),
        ]
    lines += [
        "",
        "## 圖表",
        "",
        "- [E3 各方案 EUI 長條圖](e3_eui_by_fabric.svg)",
        "- [E4 港埠構造比較圖](e4_harbour_mass_vs_light.svg)",
        "",
    ]
    (output_dir / "e3e4_results_zh.md").write_text("\n".join(lines), encoding="utf-8")

    e3_chart = [{
        "label": fabric_names.get(fabric_id, fabric_id),
        "unit": "估算 EUI（kWh/m²·年）",
        "values": [{"series": "方案", "value": row["eui_kwh_m2_year"]}],
    } for fabric_id, row in e3_by_fabric.items()]
    _write_svg(
        output_dir / "e3_eui_by_fabric.svg", "E3 各方案估算 EUI", e3_chart,
        "探索性；非能源認證。總用電含理想負荷 COP 折算。",
    )
    e4_chart = []
    if all((mass_on, mass_off, light_on, light_off)):
        e4_chart = [
            {"label": "夏季過熱（只開暖氣）", "unit": "樓地板加權小時/年",
             "values": [{"series": "重質", "value": mass_off["summer_overheated_area_weighted_hours"]},
                        {"series": "輕質", "value": light_off["summer_overheated_area_weighted_hours"]}]},
            {"label": "冬季暖氣需求（12–2月）", "unit": "kWh-熱",
             "values": [{"series": "重質", "value": mass_on["winter_heating_kwh_thermal_dec_feb"]},
                        {"series": "輕質", "value": light_on["winter_heating_kwh_thermal_dec_feb"]}]},
            {"label": "尖峰冷負荷（冷氣開啟）", "unit": "kW-熱",
             "values": [{"series": "重質", "value": mass_on["peak_cooling_kw_thermal"]},
                        {"series": "輕質", "value": light_on["peak_cooling_kw_thermal"]}]},
        ]
    _write_svg(
        output_dir / "e4_harbour_mass_vs_light.svg", "E4 港埠蓄熱構造敏感度",
        e4_chart, "重質：CZ5 Mass；輕質：低熱容、U-factor 配對；探索性；非能源認證。",
    )

    manifest = {
        "status": "exploratory_not_energy_certification",
        "status_zh": "探索性；非能源認證",
        "script": {"version": SCRIPT_VERSION, "path": str(Path(__file__).resolve()),
                   "sha256": file_sha256(Path(__file__).resolve())},
        "simulation_script": simulation_script or {
            "version": SCRIPT_VERSION, "sha256": file_sha256(Path(__file__).resolve()),
        },
        "started_utc": started_utc, "finished_utc": datetime.now(timezone.utc).isoformat(),
        "total_wall_seconds": total_wall_seconds,
        "python": {"version": sys.version.split()[0], "executable": sys.executable},
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("honeybee-core", "honeybee-energy", "honeybee-energy-standards", "ladybug-core", "shapely")
        },
        "engines": engine_info, "source_files": source_records, "assumptions": assumptions,
        "program_mappings": PROGRAM_BY_USE,
        "construction_sensitivity": {
            "heavy_construction_set": CZ5_MASS_ID, "light_template_set": CZ5_WOOD_ID,
            "climate_zone_reason": "鹿特丹近 CZ4A–5A，選 CZ5 作保守探索性近似，不作法規判定",
            "window_to_wall_ratio": WWR, "u_factor_and_heat_capacity": construction_info,
        },
        "simulation_method": {
            "zones": "one Room / thermal zone per floor", "timestep_per_hour": 6,
            "opaque_geometry": "roof/floor footprints and shade roofs triangulated into convex faces for EnergyPlus shadow stability",
            "solar_distribution": "FullExterior; shade objects participate, reflections are disabled",
            "annual_weather_hours": 8760, "context_buffer_m": CONTEXT_BUFFER_M,
            "missing_height_shades": "excluded, no imputation",
            "shared_wall": "shared vertical faces with footprint edge >=0.5m are adiabatic",
            "eui_denominator": "plan new_gfa_m2 including mezzanine not modeled as geometry",
            "estimated_electricity_formula": (
                "lights + electric equipment + available fans (missing fan electricity output treated as zero and reported as a limitation) + heating thermal kWh/COP 2.5 "
                "+ cooling thermal kWh/COP 3.0 + hot water thermal kWh/COP 1.0"
            ),
            "fan_electricity_limitation": {
                "missing_output": "Zone Ventilation Fan Electricity Energy",
                "missing_case_count": len(fan_missing_cases), "successful_case_count": len(cases),
                "missing_case_labels": fan_missing_cases,
                "calculation_treatment": "zero; estimated electricity and EUI exclude HVAC fan electricity for these cases",
            },
            "gas_equipment_energy_limitation": {
                "missing_output": "Zone Gas Equipment NaturalGas Energy",
                "missing_case_count": len(gas_missing_cases), "successful_case_count": len(cases),
                "missing_case_labels": gas_missing_cases,
                "calculation_treatment": "null/unknown, not assumed to be zero; natural gas is not included in estimated electricity",
            },
            "idf_translation": engine_info["translation_method"],
            "peak_method": "hourly synchronous sum of zone rates, then annual maximum",
            "overheat_method": "June-August hourly operative temperature >26C with cooling unavailable",
        },
        "sample": sample_info, "cases": [asdict(case) for case in cases],
        "attempts": attempt_records,
        "reused_results": reused_results,
        "e3_summaries": list(e3_by_fabric.values()),
        "e4_summaries": [
            row for row in summaries
            if row["fabric_id"] == "harbour_grain" and (
                row["construction"] != "CZ5_Mass" or not row["cooling_enabled"]
            )
        ],
        "outputs": ["e3e4_results_zh.md", "e3e4_results_zh.csv",
                    "e3_eui_by_fabric.svg", "e4_harbour_mass_vs_light.svg", "run_records/", "attempts.json"],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _case_from_run_dir(run_dir: Path) -> SimulationCase:
    record_path = run_dir / "case-result.json"
    if not record_path.is_file():
        return SimulationCase(
            run_dir.name, "unknown", "unknown", False, False, "failed", str(run_dir),
            error="模擬記錄檔不存在",
        )
    return SimulationCase(**json.loads(record_path.read_text(encoding="utf-8")))


def _run_specs(
    fabric_id: str, buildings: list[BuildingInput], retained: list[dict[str, Any]],
    heavy: Any, light: Any, context_path: Path, weather_path: Path,
    temp_root: Path, mode: str, max_seconds: float,
) -> tuple[list[SimulationCase], bool]:
    specs = [
        (heavy, "CZ5_Mass", True),
    ]
    if fabric_id == "harbour_grain":
        specs += [
            (heavy, "CZ5_Mass", False),
            (light, "CZ5_Light_U_Matched", True),
            (light, "CZ5_Light_U_Matched", False),
        ]
    successful = []
    timed_out = False
    for construction_set, construction_label, cooling_enabled in specs:
        suffix = f"{construction_label}_{'cool' if cooling_enabled else 'heat_only'}"
        run_dir = temp_root / fabric_id / mode / suffix
        try:
            case = run_case(
                fabric_id, buildings, retained, construction_set, construction_label,
                cooling_enabled, context_path, weather_path, run_dir,
                represented_area=None, max_seconds=max_seconds,
            )
            successful.append(case)
        except CaseTimeout:
            successful.append(_case_from_run_dir(run_dir))
            timed_out = True
            break
    return successful, timed_out


def _run_sample_specs(
    fabric_id: str, all_buildings: list[BuildingInput], retained: list[dict[str, Any]],
    heavy: Any, light: Any, context_path: Path, weather_path: Path,
    temp_root: Path, max_seconds: float,
) -> tuple[list[SimulationCase], dict[str, Any]]:
    sample_buildings, represented_area, sample_record = representative_sample(all_buildings)
    sample_record["fabric_id"] = fabric_id
    sampled_ids = {building.building_id for building in sample_buildings}
    immediate_neighbor_ids: set[str] = set()
    for left_index, right_index, _length in _footprint_neighbours(all_buildings):
        left, right = all_buildings[left_index], all_buildings[right_index]
        if left.building_id in sampled_ids and right.building_id not in sampled_ids:
            immediate_neighbor_ids.add(right.building_id)
        elif right.building_id in sampled_ids and left.building_id not in sampled_ids:
            immediate_neighbor_ids.add(left.building_id)
    immediate_neighbors = [
        building for building in all_buildings if building.building_id in immediate_neighbor_ids
    ]
    sample_record["immediate_unmodeled_plan_neighbors_as_shades"] = [
        {
            "id": building.building_id, "height_m": building.height_m,
            "footprint_area_m2": building.footprint_area_m2,
        }
        for building in immediate_neighbors
    ]
    specs = [(heavy, "CZ5_Mass", True)]
    if fabric_id == "harbour_grain":
        specs += [
            (heavy, "CZ5_Mass", False),
            (light, "CZ5_Light_U_Matched", True),
            (light, "CZ5_Light_U_Matched", False),
        ]
    cases = []
    for construction_set, construction_label, cooling_enabled in specs:
        suffix = f"{construction_label}_{'cool' if cooling_enabled else 'heat_only'}"
        run_dir = temp_root / fabric_id / "sample" / suffix
        try:
            case = run_case(
                fabric_id, sample_buildings, retained, construction_set,
                construction_label, cooling_enabled, context_path, weather_path,
                run_dir, represented_area, max_seconds,
                omitted_neighbor_buildings=immediate_neighbors,
            )
        except CaseTimeout:
            cases.append(_case_from_run_dir(run_dir))
            raise RuntimeError(
                f"{fabric_id} 代表樣本單案仍超過 {max_seconds / 60:.0f} 分鐘；"
                "保留目前暫存與 attempts 記錄，停止，不再縮小樣本。"
            )
        cases.append(case)
    return cases, sample_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="探索性 E3 建築耗能與 E4 蓄熱年度 EnergyPlus 分析。"
    )
    parser.add_argument(
        "--fabric", choices=(*ALL_FABRICS, "all"), default="harbour_grain",
        help="先跑港埠（預設）；all 會依序跑港埠與其餘三案 E3。",
    )
    parser.add_argument("--max-case-minutes", type=float, default=60.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--temp-parent", type=Path, default=DEFAULT_TEMP_ROOT)
    parser.add_argument(
        "--sample-only", action="store_true",
        help="已觀察全量超時後，直接跑分層代表樣本，不重跑全量。",
    )
    parser.add_argument(
        "--prior-attempt", type=Path, action="append", default=[],
        help="納入 manifest 的先前 SimulationCase JSON，可重複指定。",
    )
    parser.add_argument(
        "--reuse-output-dir", type=Path,
        help="沿用具有相同天氣、脈絡與方案雜湊的成功舊 run_records，避免重跑；新方案仍照常模擬。",
    )
    parser.add_argument(
        "--diagnostic-no-shades", action="store_true",
        help="僅診斷用：以港埠代表樣本停用所有 shade objects，不輸出正式 E3/E4 報告。",
    )
    parser.add_argument(
        "--diagnostic-tiny-box", action="store_true",
        help="僅診斷用：執行一棟 10x10x3m 無遮陽房間以檢查 EnergyPlus engine。",
    )
    args = parser.parse_args(argv)
    if args.max_case_minutes <= 0:
        parser.error("--max-case-minutes 必須大於 0")
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"輸出目錄已有檔案，為保留既有證據不覆寫：{output_dir}")

    wall_started = time.monotonic()
    started_utc = datetime.now(timezone.utc).isoformat()
    max_seconds = args.max_case_minutes * 60.0
    engine_info = configure_engines()
    weather_info = verify_epw(WEATHER_PATH)
    context_hash = file_sha256(CONTEXT_PATH)
    heavy, light, construction_info = construction_sensitivity()
    fabric_ids = list(ALL_FABRICS) if args.fabric == "all" else [args.fabric]
    fabric_names = {
        "harbour_grain": "港埠線性紋理",
        "closed_block_extension": "圍合街廓延伸",
        "courtyard_islands": "大型院落島",
        "landscape_figure": "地景為圖",
    }
    plan_info: dict[str, dict[str, Any]] = {}
    source_plans = {}
    parsed: dict[str, tuple[list[BuildingInput], list[dict[str, Any]]]] = {}
    for fabric_id in fabric_ids:
        plan_path = PLAN_ROOT / f"{fabric_id}-plan.json"
        plan, buildings, retained = parse_plan(plan_path)
        metrics = plan.get("metrics") or {}
        new_gfa = metrics.get("new_gfa_m2")
        if not isinstance(new_gfa, (int, float)) or float(new_gfa) <= 0:
            raise ValueError(f"方案缺少有效 metrics.new_gfa_m2：{plan_path}")
        plan_info[fabric_id] = {
            "new_gfa_m2": float(new_gfa),
            "buildings": [
                {"id": b.building_id, "modeled_gfa_m2": b.modeled_gfa_m2,
                 "reported_gfa_m2": b.reported_gfa_m2}
                for b in buildings
            ],
        }
        source_plans[fabric_id] = {
            "path": str(plan_path), "sha256": file_sha256(plan_path),
            "new_building_count": len(buildings), "retained_building_count": len(retained),
            "use_counts": {
                use: sum(b.use == use for b in buildings)
                for use in sorted({b.use for b in buildings})
            },
            "modeled_gfa_excluding_mezzanine_m2": sum(b.modeled_gfa_m2 for b in buildings),
            "plan_new_gfa_including_mezzanine_m2": float(new_gfa),
            "zone_count_one_per_floor": sum(b.floors for b in buildings),
        }
        parsed[fabric_id] = (buildings, retained)
    source_records = {
        "weather": weather_info,
        "context": {"path": str(CONTEXT_PATH), "sha256": context_hash},
        "plans": source_plans,
    }
    reused_cases: list[SimulationCase] = []
    reused_samples: dict[str, Any] = {}
    reused_attempts: list[SimulationCase] = []
    reuse_metadata = None
    if args.reuse_output_dir:
        reused_cases, reused_samples, reused_attempts, reuse_metadata = load_reuse_output(
            args.reuse_output_dir.resolve(), source_records, fabric_ids, engine_info,
        )
    assumptions = [
        "每層一個 Honeybee Room/EnergyPlus zone；樓層高度依 plan 首層／標準層參數，若加總不符總高 0.05 m 內則改用平均層高。",
        "用途標準 program：住宅 2019::MidriseApartment::Apartment；工業 2019::Warehouse::Bulk；商辦 2019::MediumOffice::OpenOffice；零售／商業 2019::Retail::Retail；公民／公共 2019::Courthouse::Office。",
        "ASHRAE 2019 climate zone 5 Mass 作鹿特丹 CZ4A–5A 的保守探索近似；外牆 WWR=40%。",
        "共邊長至少 0.5 m 的新建建築垂直共牆設 Adiabatic；水平樓層交界保持 Surface adjacency。",
        "保留／脈絡建築只作遮陽；缺高度者排除。脈絡資料無 CRS 欄位，基於座標範圍與方案位置假設 EPSG:28992。",
        "Context shade 只取新建區外擴 100 m 的即時脈絡，最多用來源提供之高度；無高度不插補。全量 500 m 試跑因陰影初始化超過 60 分鐘，故採 100 m 降低遠距離脈絡計算量。",
        "EUI 使用 plan metrics.new_gfa_m2（包括未另建模的 mezzanine）作分母；模型幾何 floor area 不包含 mezzanine。",
        "理想負荷估算用電折算 COP：暖氣 2.5、冷氣 3.0、熱水 1.0；天然氣設備能源不併入用電。缺少風機用電欄位時，估算計算暫以 0 處理並在結果限制中逐案列名；缺少天然氣設備能源欄位則保留 null 作未知值，不當作零用量。",
        "E4 過熱情境關閉冷氣、保留暖氣，依 6–8 月 Zone Operative Temperature >26°C 計算樓地板面積加權時數。",
        "EnergyPlus 年度逐時輸出、6 timesteps/hour；尖峰為 hourly synchronous zone rate sum 的最大值。",
        "為避免 EnergyPlus 對非凸面陰影幾何不穩定，建築屋頂／樓板與遮陽屋頂拆成同一 zone 中的凸三角面；太陽分佈使用 FullExterior，不計反射。",
        "標準 Honeybee Energy program schedule 代表性建築用途；未經現地使用、設備、控制、通風及能耗資料校準。",
    ]
    temp_parent = args.temp_parent.resolve()
    temp_parent.mkdir(parents=True, exist_ok=True)
    temp_root = temp_parent / f"e3e4-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    temp_root.mkdir()
    all_cases: list[SimulationCase] = []
    attempted: list[SimulationCase] = []
    all_cases.extend(reused_cases)
    attempted.extend(reused_attempts)
    samples: dict[str, Any] = dict(reused_samples)
    for prior_path in args.prior_attempt:
        prior_record = json.loads(prior_path.read_text(encoding="utf-8"))
        attempted.append(SimulationCase(**prior_record))

    if args.diagnostic_no_shades:
        buildings, retained = parsed["harbour_grain"]
        sampled, represented, _sample_record = representative_sample(buildings)
        selected_ids = {building.building_id for building in sampled}
        neighbor_ids: set[str] = set()
        for left_index, right_index, _length in _footprint_neighbours(buildings):
            left, right = buildings[left_index], buildings[right_index]
            if left.building_id in selected_ids and right.building_id not in selected_ids:
                neighbor_ids.add(right.building_id)
            elif right.building_id in selected_ids and left.building_id not in selected_ids:
                neighbor_ids.add(left.building_id)
        neighbors = [b for b in buildings if b.building_id in neighbor_ids]
        diagnostic_dir = temp_root / "harbour_grain" / "diagnostic_no_shades"
        case = run_case(
            "harbour_grain", sampled, retained, heavy, "CZ5_Mass", True,
            CONTEXT_PATH, WEATHER_PATH, diagnostic_dir, represented,
            max_seconds, omitted_neighbor_buildings=neighbors, include_shades=False,
        )
        print(json.dumps(asdict(case), ensure_ascii=False, indent=2))
        return 0 if case.status == "success" else 1
    if args.diagnostic_tiny_box:
        tiny = BuildingInput(
            "diagnostic_tiny", box(0, 0, 10, 10),
            {"id": "diagnostic_tiny"}, "residential",
            PROGRAM_BY_USE["residential"], 1, 3.0, (3.0,),
            100.0, 0.0,
        )
        diagnostic_dir = temp_root / "diagnostic" / "tiny_box"
        case = run_case(
            "diagnostic", [tiny], [], heavy, "CZ5_Mass", True,
            CONTEXT_PATH, WEATHER_PATH, diagnostic_dir, None, max_seconds,
            include_shades=False, solar_distribution="FullExterior",
            assign_ideal_air=True,
        )
        print(json.dumps(asdict(case), ensure_ascii=False, indent=2))
        return 0 if case.status == "success" else 1

    for fabric_id in fabric_ids:
        buildings, retained = parsed[fabric_id]
        if any(
            case.fabric_id == fabric_id and case.construction == "CZ5_Mass"
            and case.cooling_enabled and case.status == "success" and case.result
            for case in reused_cases
        ):
            continue
        if args.sample_only:
            sampled_cases, sample_record = _run_sample_specs(
                fabric_id, buildings, retained, heavy, light, CONTEXT_PATH,
                WEATHER_PATH, temp_root, max_seconds,
            )
            sample_record["trigger"] = "manual_resume_after_recorded_full_case_timeout"
            samples[fabric_id] = sample_record
            all_cases.extend(sampled_cases)
            continue
        full_cases, timed_out = _run_specs(
            fabric_id, buildings, retained, heavy, light, CONTEXT_PATH,
            WEATHER_PATH, temp_root, "full", max_seconds,
        )
        if timed_out:
            attempted.extend(full_cases)
            sampled_cases, sample_record = _run_sample_specs(
                fabric_id, buildings, retained, heavy, light, CONTEXT_PATH,
                WEATHER_PATH, temp_root, max_seconds,
            )
            samples[fabric_id] = sample_record
            all_cases.extend(sampled_cases)
        else:
            all_cases.extend(full_cases)

    write_outputs(
        output_dir, all_cases, plan_info, fabric_names,
        samples or None, source_records, engine_info, construction_info,
        assumptions, started_utc, time.monotonic() - wall_started,
        attempts=attempted,
        reused_results=reuse_metadata,
    )
    print(json.dumps({
        "status": "complete",
        "status_zh": "探索性；非能源認證",
        "output_dir": str(output_dir),
        "temp_dir": str(temp_root),
        "cases": [
            {"label": case.label, "status": case.status,
             "mode": "sample" if case.sample_mode else "full",
             "simulation_seconds": case.simulation_seconds,
             "result": case.result}
            for case in all_cases
        ],
        "sampled_fabrics": sorted(samples),
        "total_wall_seconds": time.monotonic() - wall_started,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
