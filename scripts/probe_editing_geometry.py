"""Probe Week 5/W6 Editing Geometry feasibility and Environment Tooling audit (CP4-1b).

Performs deterministic trial calculations:
1. Floor-by-floor massing (ground + standard floors, footprint areas, GFA, volume).
2. Planar subdivision (splitting footprint cleanly, rejecting collinear/degenerated cuts).
3. 1m lateral step push-pull with area change accounting.
4. Fail-closed rejection of invalid geometries (self-intersection, zero area, empty).
5. Audit of environmental simulation tools (Ladybug, Honeybee, Radiance, E1-E5 tiers).
"""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import sys
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from shapely.affinity import translate
from shapely.geometry import Polygon, LineString, MultiPolygon, mapping
from shapely.geometry import box
from shapely.ops import split, unary_union

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RADIANCE_COMMANDS = ("rad", "gendaymtx", "rtrace", "rfluxmtx", "oconv", "rmtxop")


def _radiance_inventory() -> tuple[dict[str, str | None], list[str]]:
    candidate_dirs = [
        Path("/usr/local/radiance/bin"),
        Path.home() / "radiance" / "bin",
        PROJECT_ROOT / ".urban_design_runtime" / "radiance" / "bin",
        Path("/private/tmp/radiance-arm64/radiance/bin"),
    ]
    for env_name in ("BINPATH", "RADIANCE_BIN"):
        value = os.environ.get(env_name)
        if value:
            candidate_dirs.insert(0, Path(value).expanduser())

    commands: dict[str, str | None] = {}
    for command in RADIANCE_COMMANDS:
        found = shutil.which(command)
        if found is None:
            for directory in candidate_dirs:
                candidate = directory / command
                if candidate.is_file() and candidate.stat().st_mode & 0o111:
                    found = str(candidate)
                    break
        commands[command] = str(Path(found).resolve()) if found else None
    checked = [str(path) for path in candidate_dirs]
    return commands, checked


def _distribution_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


@dataclass(frozen=True)
class MassingStorey:
    floor_index: int
    elevation_m: float
    height_m: float
    polygon: Polygon | MultiPolygon

    @property
    def area_m2(self) -> float:
        return round(self.polygon.area, 4)

    @property
    def volume_m3(self) -> float:
        return round(self.polygon.area * self.height_m, 4)


def compute_building_massing(
    base_footprint: Polygon,
    floor_heights: list[float],
    *,
    floor_footprints: list[Polygon | MultiPolygon] | None = None,
) -> dict:
    if not base_footprint.is_valid or base_footprint.is_empty or base_footprint.area <= 0:
        raise ValueError("Invalid base footprint polygon")
    if not floor_heights:
        raise ValueError("At least one floor height is required")
    footprints = floor_footprints if floor_footprints is not None else [base_footprint] * len(floor_heights)
    if len(footprints) != len(floor_heights):
        raise ValueError("floor footprint count must match floor height count")

    storeys: list[MassingStorey] = []
    current_elev = 0.0
    for idx, h in enumerate(floor_heights):
        if isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(float(h)) or h <= 0:
            raise ValueError(f"Invalid floor height {h} at index {idx}")
        footprint = footprints[idx]
        if not isinstance(footprint, (Polygon, MultiPolygon)) or not footprint.is_valid or footprint.is_empty or footprint.area <= 0:
            raise ValueError(f"Invalid floor footprint at index {idx}")
        storeys.append(
            MassingStorey(
                floor_index=idx,
                elevation_m=round(current_elev, 4),
                height_m=round(h, 4),
                polygon=footprint,
            )
        )
        current_elev += h

    gfa = sum(s.area_m2 for s in storeys)
    total_vol = sum(s.volume_m3 for s in storeys)
    floor_plates = [
        {
            "floor_index": storey.floor_index,
            "elevation_m": storey.elevation_m,
            "height_m": storey.height_m,
            "floor_area_m2": storey.area_m2,
            "volume_m3": storey.volume_m3,
            "geometry_type": storey.polygon.geom_type,
            "bounds": [round(value, 4) for value in storey.polygon.bounds],
            "geometry": mapping(storey.polygon),
        }
        for storey in storeys
    ]

    return {
        "storey_count": len(storeys),
        "total_height_m": round(current_elev, 4),
        "footprint_area_m2": round(base_footprint.area, 4),
        "gross_floor_area_m2": round(gfa, 4),
        "volume_m3": round(total_vol, 4),
        "floor_plates": floor_plates,
    }


def split_footprint(polygon: Polygon, cut_line: LineString) -> list[Polygon]:
    """Split a 2D footprint polygon into sub-polygons."""
    if not polygon.is_valid or polygon.is_empty:
        raise ValueError("Cannot split invalid or empty polygon")
    if not cut_line.is_valid or cut_line.is_empty or not cut_line.intersects(polygon):
        raise ValueError("Cut line does not intersect polygon")

    result = split(polygon, cut_line)
    sub_polys: list[Polygon] = []
    for geom in getattr(result, "geoms", [result]):
        if isinstance(geom, Polygon) and geom.is_valid and geom.area > 1e-4:
            sub_polys.append(geom)

    if len(sub_polys) < 2:
        raise ValueError("Split line did not produce at least two sub-polygons")

    # Verify partition property: total area of sub_polys equals original polygon area
    total_sub_area = sum(p.area for p in sub_polys)
    if not math.isclose(total_sub_area, polygon.area, rel_tol=1e-5):
        raise ValueError("Sub-polygons area does not sum to original footprint area")
    for first in range(len(sub_polys)):
        for second in range(first + 1, len(sub_polys)):
            if sub_polys[first].intersection(sub_polys[second]).area > 1e-8:
                raise ValueError("Sub-polygons overlap after split")
    rebuilt = unary_union(sub_polys)
    if polygon.symmetric_difference(rebuilt).area > max(1e-8, polygon.area * 1e-9):
        raise ValueError("Sub-polygons do not reconstruct the original footprint")

    return sub_polys


def lateral_push_pull(polygon: Polygon, edge_index: int, delta_m: float) -> Polygon:
    """Displace one edge of a polygon outwards or inwards by delta_m metres."""
    if not polygon.is_valid or polygon.is_empty:
        raise ValueError("Invalid input polygon")
    if isinstance(edge_index, bool) or not isinstance(edge_index, int):
        raise ValueError("Edge index must be an integer")
    if isinstance(delta_m, bool) or not isinstance(delta_m, (int, float)) or not math.isfinite(float(delta_m)):
        raise ValueError("Displacement must be a finite number of metres")
    coords = list(polygon.exterior.coords)[:-1]  # unique vertices
    n = len(coords)
    if edge_index < 0 or edge_index >= n:
        raise ValueError(f"Edge index {edge_index} out of range [0, {n-1}]")

    p1 = coords[edge_index]
    p2 = coords[(edge_index + 1) % n]
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("Degenerate edge with zero length")

    # A right-hand normal points outward for counterclockwise exterior rings.
    origin_x, origin_y = coords[0]
    signed_area_twice = math.fsum(
        (x1 - origin_x) * (y2 - origin_y) - (x2 - origin_x) * (y1 - origin_y)
        for (x1, y1), (x2, y2) in zip(coords, coords[1:] + coords[:1])
    )
    winding = 1 if signed_area_twice > 0 else -1
    nx = winding * dy / length
    ny = winding * -dx / length

    new_coords = list(coords)
    new_coords[edge_index] = (p1[0] + nx * delta_m, p1[1] + ny * delta_m)
    new_coords[(edge_index + 1) % n] = (p2[0] + nx * delta_m, p2[1] + ny * delta_m)

    candidate = Polygon(new_coords, [list(ring.coords) for ring in polygon.interiors])
    if not candidate.is_valid or candidate.is_empty or candidate.area <= 0:
        raise ValueError("Lateral displacement resulted in self-intersection or invalid geometry")

    return candidate


def run_geometry_and_tool_probe(output_dir: Path | None = None) -> dict:
    # 1. Trial massing: 20m x 30m rectangle = 600 m2
    rect = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])
    heights = [4.5, 3.5, 3.5, 3.5]  # 4 storeys
    massing_res = compute_building_massing(rect, heights)
    assert massing_res["footprint_area_m2"] == 600.0
    assert massing_res["gross_floor_area_m2"] == 2400.0
    assert massing_res["total_height_m"] == 15.0

    # 2. Planar split: split down the middle x=15
    cutter = LineString([(15, -5), (15, 25)])
    sub_polys = split_footprint(rect, cutter)
    assert len(sub_polys) == 2
    assert math.isclose(sub_polys[0].area, 300.0)
    assert math.isclose(sub_polys[1].area, 300.0)

    # 3. Lateral 1m displacement
    expanded = lateral_push_pull(rect, edge_index=1, delta_m=1.0)
    # Edge 1 is (30,0) to (30,20). Moving outwards (+x) by 1.0 increases width from 30 to 31, area = 31*20 = 620.0
    assert math.isclose(expanded.area, 620.0, rel_tol=1e-5)

    left, right = sorted(sub_polys, key=lambda part: part.bounds[0])
    displaced_right = translate(right, xoff=1.0, yoff=0.0)
    edited_floors = [rect, MultiPolygon([left, displaced_right]), expanded]
    edited_stack = compute_building_massing(rect, [4.5, 3.5, 3.5], floor_footprints=edited_floors)
    editing_envelope = box(0, 0, 34, 20)
    envelope_covers_all_floors = all(editing_envelope.covers(footprint) for footprint in edited_floors)
    assert envelope_covers_all_floors

    # 4. Invalid geometry rejection checks through the probe's actual validator.
    # Self-intersecting hourglass
    bow_tie = Polygon([(0, 0), (20, 20), (20, 0), (0, 20)])
    collinear = Polygon([(0, 0), (10, 0), (20, 0)])
    rejected_invalid = rejected_zero_area = False
    try:
        compute_building_massing(bow_tie, [3.0])
    except ValueError:
        rejected_invalid = True
    try:
        compute_building_massing(collinear, [3.0])
    except ValueError:
        rejected_zero_area = True
    assert rejected_invalid and rejected_zero_area

    # 5. Environment tool audit
    ladybug_present = False
    honeybee_present = False
    radiance_bin_present = False
    try:
        import ladybug
        ladybug_present = True
    except ImportError:
        pass
    try:
        import honeybee
        honeybee_present = True
    except ImportError:
        pass

    # Check radiance binaries
    radiance_commands, radiance_search_paths = _radiance_inventory()
    radiance_exec = radiance_commands.get("rtrace") or radiance_commands.get("rad")
    radiance_bin_present = all(radiance_commands.values())
    python_runtime = {
        "executable": sys.executable,
        "version": platform.python_version(),
        "architecture": platform.machine(),
        "packages": {
            name: _distribution_version(name)
            for name in (
                "ladybug-core",
                "ladybug-geometry",
                "ladybug-radiance",
                "honeybee-core",
                "honeybee-radiance",
                "honeybee-energy",
            )
        },
    }

    report = {
        "schema_version": "probe-editing-geometry-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "geometry_status": "PASS_SYNTHETIC_FEASIBILITY_ONLY",
        "python_runtime": python_runtime,
        "geometry_feasibility": {
            "storey_massing": {
                "status": "PASS",
                "test_case": "4 storeys (4.5m ground + 3x3.5m)",
                "observed": massing_res,
            },
            "edited_floor_stack": {
                "status": "PASS",
                "floor_areas_m2": [floor["floor_area_m2"] for floor in edited_stack["floor_plates"]],
                "gross_floor_area_m2": edited_stack["gross_floor_area_m2"],
                "floor_plates": edited_stack["floor_plates"],
                "local_displacement_m": {"dx": 1.0, "dy": 0.0, "applied_to": "split east half of storey 2"},
                "synthetic_editing_envelope_bounds": list(editing_envelope.bounds),
                "envelope_covers_all_floors": envelope_covers_all_floors,
            },
            "planar_face_split": {
                "status": "PASS",
                "test_case": "20x30m split into 2x 300m2 parts",
                "parts_count": len(sub_polys),
            },
            "lateral_1m_step": {
                "status": "PASS",
                "test_case": "1m outward displacement on 20m edge",
                "area_before_m2": 600.0,
                "area_after_m2": expanded.area,
            },
            "invalid_geometry_rejection": {
                "status": "PASS",
                "self_intersecting_rejected": rejected_invalid,
                "zero_area_rejected": rejected_zero_area,
            }
        },
        "environmental_tools_audit": {
            "status": "PARTIAL_RUNTIME_INVENTORY_ONLY",
            "ladybug_installed": ladybug_present,
            "honeybee_installed": honeybee_present,
            "radiance_bin_available": radiance_bin_present,
            "radiance_binary_path": radiance_exec or "UNVERIFIED_IN_STANDARD_PATH",
            "radiance_commands": radiance_commands,
            "radiance_search_paths": radiance_search_paths,
            "non_climate_runtime_commands": {
                "energyplus": shutil.which("energyplus"),
                "openfoam_blockMesh": shutil.which("blockMesh"),
                "openfoam_simpleFoam": shutil.which("simpleFoam"),
            },
            "tier_readiness": {
                "E1_sunlight_hours": {
                    "status": "METHOD_ONLY_NOT_EXECUTED",
                    "requires_epw": False,
                    "dependencies": ["ladybug-geometry", "solar_vector_calculation"],
                    "notes": "This probe did not execute a sun-hours calculation; method readiness requires a separately validated solver and fixture."
                },
                "E2_radiation_screening_and_verification": {
                    "status": "PRIOR_SYNTHETIC_SMOKE_PASS_CURRENT_WEATHER_GATE_BLOCKED",
                    "requires_epw": True,
                    "weather_semantics": "SEMANTICS_UNRESOLVED",
                    "dependencies": ["ladybug-radiance", "honeybee-radiance", "Radiance 6.0.2"],
                    "notes": "Feasibility verified in M1 smoke; awaiting human weather source decision."
                },
                "E3_building_energy": {
                    "status": "INPUTS_NOT_VERIFIED",
                    "requires_epw": True,
                    "dependencies": ["EnergyPlus", "building_loads", "hvac_systems", "schedules"],
                    "notes": "Requires detailed architectural schedule and EnergyPlus engine."
                },
                "E4_thermal_mass": {
                    "status": "INPUTS_NOT_VERIFIED",
                    "requires_epw": True,
                    "dependencies": ["transient_conduction_model", "material_layer_properties"],
                    "notes": "Requires transient thermal mass solver."
                },
                "E5_cfd_wind": {
                    "status": "INPUTS_NOT_VERIFIED",
                    "requires_epw": False,
                    "dependencies": ["OpenFOAM", "snappyHexMesh", "wind_boundary_conditions"],
                    "notes": "CFD microclimate requires 3D meshing and Navier-Stokes solver."
                }
            }
        }
    }
    report["geometry_feasibility"]["scope"] = {
        "coordinate_space": "synthetic local Cartesian metre grid",
        "actual_rotterdam_geometry_used": False,
        "design_or_buildability_claim": False,
        "3d_solid_or_structural_validation": False,
        "planning_rules_checked": False,
    }

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_file = output_dir / "probe-editing-geometry.json"
        if out_file.exists():
            raise FileExistsError(f"Refusing to overwrite existing probe evidence: {out_file}")
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Editing geometry probe report saved to {out_file}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline synthetic editing-geometry and environment feasibility probe.")
    parser.add_argument("--output-dir", type=Path, help="Optional directory for a JSON report; it is created if absent.")
    args = parser.parse_args()
    report = run_geometry_and_tool_probe(args.output_dir)
    print(json.dumps({"status": report["status"], "geometry_scope": report["geometry_feasibility"]["scope"]}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI smoke
    raise SystemExit(main())
