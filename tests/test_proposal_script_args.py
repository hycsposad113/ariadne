"""Focused CLI and geometry tests for proposal E1/UTCI reruns.

The runner tests stub only Radiance-facing work; they still exercise input
selection, draft geometry loading, and output-directory routing.
"""

from __future__ import annotations

import json
import sys
import types
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon, box, mapping, shape

ROOT = Path(__file__).resolve().parents[1]
import urban_design  # Load the actual package before standalone scripts' import shim.

# This checkout's linked .venv is missing the Ladybug packages. The tests mock
# all analysis execution, so provide import-only placeholders when unavailable.
_comfort_stub = importlib.util.find_spec("ladybug_comfort") is None
if _comfort_stub:
    comfort = types.ModuleType("ladybug_comfort")
    comfort.solarcal = types.SimpleNamespace()
    comfort.utci = types.SimpleNamespace()
    sys.modules["ladybug_comfort"] = comfort

from scripts import e1_fabric_sunlight as e1
from scripts import utci_fabric as utci
if _comfort_stub:
    # Module aliases above retain the import-only placeholders without leaking
    # a synthetic dependency into unrelated test modules.
    sys.modules.pop("ladybug_comfort", None)


def _draft_building(building_id: str, lower: Polygon, upper: Polygon) -> dict:
    return {
        "building_id": building_id,
        "floors": [
            {"floor_id": f"{building_id}-floor-0", "level": 0, "geometry": mapping(lower)},
            {"floor_id": f"{building_id}-floor-1", "level": 1, "geometry": mapping(upper)},
        ],
        "first_floor_height_m": 4.0,
        "standard_floor_height_m": 3.0,
        "provenance": "FORMAL_DRAFT",
    }


def _write_plan(path: Path, *, retained: bool = False) -> None:
    plan = {
        "site": mapping(box(0, 0, 10, 10)),
        "buildings": [
            {
                "type": "Feature",
                "id": "building-1",
                "geometry": mapping(box(6, 6, 8, 8)),
                "properties": {"id": "building-1", "retained": retained, "height_m": 6.0},
            }
        ],
        "land_use": [],
        "courtyards": [],
    }
    path.write_text(json.dumps(plan), encoding="utf-8")


@pytest.mark.parametrize("module", [e1, utci], ids=["e1", "utci"])
def test_buildings_override_uses_full_typed_list_for_floors_and_sensor_openness(module, tmp_path):
    plan_path = tmp_path / "plan.json"
    site = box(0, 0, 20, 20)
    baseline_a = box(4, 4, 6, 6)
    baseline_b = box(14, 14, 16, 16)
    retained = box(19, 19, 20, 20)
    plan_path.write_text(
        json.dumps(
            {
                "site": mapping(site),
                "buildings": [
                    {
                        "type": "Feature",
                        "id": "building-1",
                        "geometry": mapping(baseline_a),
                        "properties": {"id": "building-1", "retained": False, "height_m": 6.0},
                    },
                    {
                        "type": "Feature",
                        "id": "building-2",
                        "geometry": mapping(baseline_b),
                        "properties": {"id": "building-2", "retained": False, "height_m": 6.0},
                    },
                    {
                        "type": "Feature",
                        "id": "retained-building",
                        "geometry": mapping(retained),
                        "properties": {"id": "retained-building", "retained": True, "height_m": 9.0},
                    },
                ],
                "land_use": [{"geometry": mapping(site), "properties": {"category": "parks"}}],
                "courtyards": [],
            }
        ),
        encoding="utf-8",
    )
    lower_a = box(0, 0, 4, 4)
    upper_a = box(1, 1, 3, 3)
    lower_b = box(10, 10, 14, 14)
    upper_b = box(11, 11, 13, 13)
    override_path = tmp_path / "draft.json"
    # The job runner passes the typed editable_buildings list directly. The two
    # floors also retain their distinct SETBACK_UPPER footprints.
    override_path.write_text(json.dumps([
        _draft_building("building-1", lower_a, upper_a),
        _draft_building("building-2", lower_b, upper_b),
    ]), encoding="utf-8")

    plan, obstacles, footprints, _categories, _site = module.load_fabric_plan(
        plan_path, buildings_override_path=override_path
    )

    assert len(obstacles) == 5
    assert sum(item.source == "FORMAL_DRAFT_OVERRIDE" for item in obstacles) == 4
    assert sum(item.source == "PLAN_BUILDING" for item in obstacles) == 1
    assert [shape(mapping(footprint)) for footprint in footprints] == [lower_a, lower_b, retained]
    z_bounds = sorted(
        (min(point[2] for face in item.faces for point in face), max(point[2] for face in item.faces for point in face))
        for item in obstacles if item.source == "FORMAL_DRAFT_OVERRIDE"
    )
    assert z_bounds == [(0.0, 4.0), (0.0, 4.0), (4.0, 7.0), (4.0, 7.0)]
    setback_obstacle = next(
        item for item in obstacles if item.obstacle_id == "draft_building-1_floor_1_0"
    )
    assert min(point[0] for face in setback_obstacle.faces for point in face) == 1.0
    assert max(point[0] for face in setback_obstacle.faces for point in face) == 3.0
    assert shape(plan["buildings"][0]["geometry"]).equals(lower_a)
    assert shape(plan["buildings"][1]["geometry"]).equals(lower_b)
    assert shape(plan["buildings"][2]["geometry"]).equals(retained)
    assert plan["buildings"][2]["properties"] == {
        "id": "retained-building", "retained": True, "height_m": 9.0
    }

    # MOVE-like relocation opens the original sensor cells and blocks the new
    # union, while the retained building continues to block its original cell.
    sensors = module.generate_ground_sensor_grid(
        boundary=_site, spacing_m=5.0, building_footprints=footprints
    )
    statuses = {(point.coordinates[0], point.coordinates[1]): point.status for point in sensors}
    assert statuses[(0.0, 0.0)] == "EXCLUDED_INSIDE_FOOTPRINT"
    assert statuses[(5.0, 5.0)] == "VALID"
    assert statuses[(10.0, 10.0)] == "EXCLUDED_INSIDE_FOOTPRINT"
    assert statuses[(15.0, 15.0)] == "VALID"
    assert statuses[(20.0, 20.0)] == "EXCLUDED_INSIDE_FOOTPRINT"


def _real_harbour_building_override(tmp_path: Path) -> Path:
    plan_path = ROOT / "artifacts/fab1/run-8/harbour_grain-plan.json"
    if not plan_path.is_file():
        pytest.skip("real harbour plan unavailable")
    first = json.loads(plan_path.read_text(encoding="utf-8"))["buildings"][0]
    geometry = first["geometry"]
    draft = {
        "building_id": first["id"],
        "floors": [{"floor_id": f"{first['id']}-floor-0", "level": 0, "geometry": geometry}],
        "first_floor_height_m": 4.0,
        "standard_floor_height_m": 3.0,
        "provenance": "FORMAL_DRAFT",
    }
    path = tmp_path / "formal-draft.json"
    path.write_text(json.dumps({"editor": {"editable_buildings": [draft]}}), encoding="utf-8")
    return path


def test_e1_cli_uses_selected_fabric_override_and_output_dir(tmp_path, monkeypatch):
    override_path = _real_harbour_building_override(tmp_path)
    output_dir = tmp_path / "e1-output"
    monkeypatch.setattr(e1, "verify_radiance_runtime", lambda: SimpleNamespace(available=True, version="6.0.2", reason=None))
    monkeypatch.setattr(e1, "load_context_obstacles", lambda *_args, **_kwargs: ([], {"sha256": "fixture", "total_context_obstacles": 0}))

    def fake_load_plan(plan_path, *, buildings_override_path=None):
        assert plan_path.name == "harbour_grain-plan.json"
        assert buildings_override_path == override_path
        site = box(0, 0, 10, 10)
        categories = {name: Polygon() for name in e1.CATEGORY_ORDER}
        categories["parks"] = site
        return {"site": mapping(site), "buildings": []}, [], [], categories, site

    monkeypatch.setattr(e1, "load_fabric_plan", fake_load_plan)
    monkeypatch.setattr(
        e1,
        "generate_categorized_sensor_grid",
        lambda **_kwargs: ([SimpleNamespace(point_id="point-1")], {"point-1": "parks"}),
    )
    monkeypatch.setattr(
        e1,
        "calculate_direct_sunlight_hours",
        lambda **_kwargs: SimpleNamespace(
            daily_results={
                day.isoformat(): [SimpleNamespace(point_id="point-1", sunlight_hours=2.5)]
                for day in e1.ANALYSIS_DATES
            }
        ),
    )
    monkeypatch.setattr(
        e1,
        "render_fabric_sunlight_heatmap",
        lambda **kwargs: (kwargs["output_path"].write_bytes(b"mocked heatmap") or kwargs["output_path"]),
    )
    monkeypatch.setattr(
        e1,
        "render_comparison_summary_graphic",
        lambda _records, path: path.write_bytes(b"mocked summary"),
    )

    e1.main([
        "--fabrics", "harbour_grain",
        "--buildings-override", str(override_path),
        "--output-dir", str(output_dir),
        "--quick",
    ])

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert (output_dir / "comparison_table.json").is_file()
    assert manifest["sources"]["buildings_override"]["path"] == str(override_path)
    assert list(manifest["sources"]["fabrics"]) == ["harbour_grain"]


def _fake_utci_result() -> dict:
    category_stats = {
        key: {
            "category_zh": key,
            "area_m2": 16.0,
            "sensor_count": 1,
            "total_sensor_hours": 8,
            "no_stress_pct": 0.0,
            "moderate_pct": 0.0,
            "strong_pct": 0.0,
            "very_strong_pct": 100.0,
            "heat_stress_pct": 100.0,
            "mean_mrt_c": 45.0,
            "mean_svf": 0.5,
            "mean_utci_c": 40.0,
            "max_utci_c": 42.0,
            "strong_plus_pct": 100.0,
            "very_strong_pct": 100.0,
        }
        for key in (*utci.CATEGORY_ORDER, "total")
    }
    return {
        "fabric_name_zh": utci.FABRIC_NAMES_ZH["harbour_grain"],
        "total_sensor_count": 1,
        "stress_table": category_stats,
        "hourly_overall_stats": {},
        "grid_spacing_m": 5.0,
        "elapsed_seconds": 1.0,
        "radiance_svf_time_s": 0.2,
        "radiance_sun_time_s": 0.3,
    }


def test_utci_cli_uses_selected_fabric_override_and_output_dir(tmp_path, monkeypatch):
    if _comfort_stub:
        monkeypatch.setitem(sys.modules, 'ladybug_comfort', comfort)
    override_path = _real_harbour_building_override(tmp_path)
    output_dir = tmp_path / "utci-output"
    epw_path = tmp_path / "fixture.epw"
    epw_path.write_bytes(b"fixture weather bytes")
    hourly = {
        hour: {
            "dry_bulb_c": 30.0,
            "relative_humidity_pct": 40.0,
            "wind_speed_10m": 2.0,
            "dni_w_m2": 500.0,
            "dhi_w_m2": 100.0,
            "horiz_ir_w_m2": 350.0,
        }
        for hour in range(24)
    }
    weather = {
        "date_str": "2026-07-01",
        "mean_daily_temp_c": 29.0,
        "max_daily_temp_c": 33.0,
        "min_daily_temp_c": 25.0,
        "hourly_data": hourly,
    }
    calls = []
    monkeypatch.setattr(utci, "verify_radiance_runtime", lambda: SimpleNamespace(available=True, reason=None, version="6.0.2"))
    monkeypatch.setattr(utci, "find_hottest_summer_day", lambda _path: weather)
    monkeypatch.setattr(utci, "load_context_obstacles", lambda *_args, **_kwargs: ([], {"sha256": "fixture", "total_context_obstacles": 0, "known_height_obstacles": 0, "assumed_height_obstacles": 0}))
    monkeypatch.setattr(utci, "load_context_water", lambda *_args, **_kwargs: [])

    def fake_simulate(**kwargs):
        calls.append(kwargs)
        return _fake_utci_result()

    monkeypatch.setattr(utci, "simulate_fabric_utci", fake_simulate)
    monkeypatch.setattr(
        utci,
        "generate_utci_svg",
        lambda _result, _water, _context, path: path.write_text("<svg/>", encoding="utf-8"),
    )
    monkeypatch.setattr(utci, "convert_svg_to_png", lambda *_args, **_kwargs: False)

    assert utci.main([
        "--fabrics", "harbour_grain",
        "--buildings-override", str(override_path),
        "--output-dir", str(output_dir),
        "--epw", str(epw_path),
    ]) == 0

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "utci_stress_hours_comparison.json").read_text(encoding="utf-8"))
    assert calls[0]["buildings_override_path"] == override_path
    assert (output_dir / "harbour_grain_utci_1400.svg").is_file()
    assert list(summary["fabrics"]) == ["harbour_grain"]
    assert list(manifest["inputs"]["fabric_plans"]) == ["harbour_grain"]
    assert manifest["inputs"]["buildings_override"]["path"] == str(override_path)
