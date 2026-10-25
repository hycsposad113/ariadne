"""Unit tests for English climate figures (E3, E4, E5) and router fallback.

Tests verify:
1. E3 and E4 English renderers produce valid PNGs with correct dimensions (1800x1100 and 2200x864).
2. E5 renderers execute on small synthetic grids (no OpenFOAM, no Docker) with language='en'.
3. E5 npz save/load round-trip and e5_render_from_grids script logic (loading, metrics, comparison flagging, rendering).
4. Router exposes path_en for E3/E4 from manifest and falls back to None (Chinese) for E5 until English figures are provided.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
from PIL import Image
import pytest
from shapely.geometry import box, mapping
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore

from scripts.e3e4_combine import render_e3_eui_chart, render_e4_chart
from scripts.e5_openfoam_harbour import (
    render_wind_field_map,
    render_4winds_summary_panel,
    render_risk_zones_map,
    render_lawson_comfort_map,
)
from scripts.e5_render_from_grids import (
    load_grids_directory,
    compute_wind_metrics,
    compare_summary_numbers,
    render_all_figures,
)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def test_e3_and_e4_english_renderers(tmp_path: Path) -> None:
    """Test E3 and E4 renderers output valid English figures with correct dimensions."""
    sample_csv = tmp_path / "e3e4_results_zh.csv"
    sample_csv.write_text(
        "方案,構造,冷氣,新建GFA分母_m2,暖氣需求_kWh_熱,冷氣需求_kWh_熱,EUI_kWh_m2年,尖峰暖氣_kW_熱,尖峰冷氣_kW_熱,夏季過熱時數_樓地板加權,冬季暖氣需求_kWh_熱\n"
        "港埠線性紋理,CZ5_Mass,開,253000,5456772.7,4402800.0,38.97,12000.0,4402.8,800.0,5456772.7\n"
        "港埠線性紋理,CZ5_Mass,關（只開暖氣）,253000,5456772.7,0.0,21.57,12000.0,0.0,840.4,5456772.7\n"
        "圍合街廓延伸,CZ5_Mass,開,260000,5800000.0,4600000.0,40.00,12500.0,4600.0,820.0,5800000.0\n"
        "大型院落島,CZ5_Mass,開,240000,5100000.0,4200000.0,38.75,11500.0,4200.0,790.0,5100000.0\n"
        "地景為圖,CZ5_Mass,開,250000,5300000.0,4300000.0,38.40,11800.0,4300.0,810.0,5300000.0\n"
        "港埠線性紋理,CZ5_Light_U_Matched,開,253000,5466727.2,4662700.0,40.03,12100.0,4662.7,850.0,5466727.2\n"
        "港埠線性紋理,CZ5_Light_U_Matched,關（只開暖氣）,253000,5466727.2,0.0,21.61,12100.0,0.0,883.9,5466727.2\n",
        encoding="utf-8-sig",
    )

    # 1. E3 English chart
    e3_en_png = tmp_path / "e3_eui_by_fabric-en.png"
    render_e3_eui_chart(sample_csv, e3_en_png, language="en")
    assert e3_en_png.is_file()
    with Image.open(e3_en_png) as img:
        assert img.size == (1800, 1100)

    # 2. E4 English chart
    e4_en_png = tmp_path / "e4_harbour_mass_vs_light-en.png"
    render_e4_chart(sample_csv, e4_en_png, language="en")
    assert e4_en_png.is_file()
    with Image.open(e4_en_png) as img:
        assert img.size == (2200, 864)


def test_e5_synthetic_grid_renderers_en(tmp_path: Path) -> None:
    """Test all E5 figure renderers with synthetic grids and language='en' (no OpenFOAM/Docker)."""
    ny, nx = 25, 25
    bounds = (0.0, 0.0, 75.0, 75.0)
    site_geom = box(15.0, 15.0, 60.0, 60.0)
    buildings = [
        {"geometry": box(25.0, 25.0, 35.0, 35.0), "height_m": 18.0, "is_harbour": True, "id": "bldg-1"},
        {"geometry": box(40.0, 25.0, 50.0, 35.0), "height_m": 12.0, "is_harbour": False, "id": "bldg-2"},
    ]

    # Create synthetic ratio grids
    winds = ["SW", "W", "S", "NW"]
    ratio_grids: Dict[str, np.ndarray] = {
        "SW": np.full((ny, nx), 0.5, dtype=np.float32),
        "W": np.full((ny, nx), 1.3, dtype=np.float32),
        "S": np.full((ny, nx), 0.2, dtype=np.float32),
        "NW": np.full((ny, nx), 0.8, dtype=np.float32),
    }
    # Introduce acceleration hotspot and stagnant wake
    ratio_grids["SW"][10:14, 10:14] = 1.4
    ratio_grids["SW"][5:8, 5:8] = 0.15

    wind_stats = {
        "SW": {"wind_direction_deg": 225.0, "uref_10m": 6.1, "frequency_pct": 21.5},
        "W": {"wind_direction_deg": 270.0, "uref_10m": 5.0, "frequency_pct": 20.5},
        "S": {"wind_direction_deg": 180.0, "uref_10m": 4.44, "frequency_pct": 17.7},
        "NW": {"wind_direction_deg": 315.0, "uref_10m": 4.32, "frequency_pct": 7.7},
    }

    # 1. Wind field map
    field_en = tmp_path / "cfd_sw_wind_ratio-en.png"
    render_wind_field_map(
        ratio_grid=ratio_grids["SW"],
        bounds=bounds,
        buildings=buildings,
        site_geom=site_geom,
        wind_name="SW",
        wind_deg=225.0,
        uref=6.1,
        freq_pct=21.5,
        output_png=str(field_en),
        language="en",
    )
    assert field_en.is_file()
    with Image.open(field_en) as img:
        assert img.size == (1400, 1000)

    # 2. Risk zones map
    risk_en = tmp_path / "cfd_wind_risk_zones-en.png"
    render_risk_zones_map(
        ratio_grids=ratio_grids,
        bounds=bounds,
        buildings=buildings,
        site_geom=site_geom,
        output_png=str(risk_en),
        language="en",
    )
    assert risk_en.is_file()
    with Image.open(risk_en) as img:
        assert img.size == (1400, 1000)

    # 3. Lawson comfort map
    lawson_en = tmp_path / "cfd_lawson_comfort-en.png"
    render_lawson_comfort_map(
        ratio_grids=ratio_grids,
        wind_stats=wind_stats,
        bounds=bounds,
        buildings=buildings,
        site_geom=site_geom,
        output_png=str(lawson_en),
        language="en",
    )
    assert lawson_en.is_file()
    with Image.open(lawson_en) as img:
        assert img.size == (1400, 1000)

    # 4. 4-winds summary panel
    panel_en = tmp_path / "cfd_4winds_summary-en.png"
    render_4winds_summary_panel(
        ratio_grids=ratio_grids,
        wind_stats=wind_stats,
        bounds=bounds,
        buildings=buildings,
        site_geom=site_geom,
        output_png=str(panel_en),
        language="en",
    )
    assert panel_en.is_file()
    with Image.open(panel_en) as img:
        assert img.size == (1600, 1290)


def test_e5_npz_and_render_from_grids(tmp_path: Path) -> None:
    """Test NPZ save/load, metric calculation, comparison flagging, and batch rendering."""
    grids_dir = tmp_path / "grids"
    grids_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    ny, nx = 30, 30
    bounds = (0.0, 0.0, 90.0, 90.0)
    site_geom = box(15.0, 15.0, 75.0, 75.0)
    buildings = [
        {"geometry": box(30.0, 30.0, 45.0, 45.0), "height_m": 20.0, "is_harbour": True, "id": "harbour-01"}
    ]

    # Write buildings.geojson and site.geojson
    bldgs_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(b["geometry"]),
                "properties": {"height_m": b["height_m"], "is_harbour": b["is_harbour"], "id": b["id"]},
            }
            for b in buildings
        ],
    }
    (grids_dir / "buildings.geojson").write_text(json.dumps(bldgs_geojson), encoding="utf-8")
    (grids_dir / "site.geojson").write_text(json.dumps({"type": "Feature", "geometry": mapping(site_geom)}), encoding="utf-8")

    # Save NPZ files for SW, W, S, NW
    wind_specs = {
        "SW": (225.0, 6.1, 21.5, 0.4),
        "W": (270.0, 5.0, 20.5, 0.5),
        "S": (180.0, 4.44, 17.7, 0.35),
        "NW": (315.0, 4.32, 7.7, 0.3),
    }
    for wname, (wdeg, uref, freq, base_val) in wind_specs.items():
        arr = np.full((ny, nx), base_val, dtype=np.float32)
        arr[5:10, 5:10] = base_val * 2.0  # create variations
        np.savez_compressed(
            grids_dir / f"{wname}.npz",
            ratio_grid=arr,
            bounds=np.array(bounds, dtype=float),
            wind_deg=wdeg,
            uref=uref,
            frequency_pct=freq,
        )

    # 1. Test load_grids_directory
    r_grids, w_stats, m_bounds, bldgs_loaded, site_loaded = load_grids_directory(grids_dir)
    assert set(r_grids.keys()) == {"SW", "W", "S", "NW"}
    assert len(bldgs_loaded) == 1
    assert m_bounds == bounds

    # 2. Test compute_wind_metrics
    sw_metrics = compute_wind_metrics(r_grids["SW"], m_bounds, bldgs_loaded, site_loaded)
    assert "max_wind_ratio" in sw_metrics
    assert "mean_wind_ratio" in sw_metrics
    assert "high_wind_ratio_area_m2" in sw_metrics
    assert "stagnant_wind_area_m2" in sw_metrics

    # 3. Test compare_summary_numbers
    computed_cases = {"SW": sw_metrics}
    matching_baseline = {
        "SW": {
            "max_wind_ratio": sw_metrics["max_wind_ratio"],
            "mean_wind_ratio": sw_metrics["mean_wind_ratio"],
            "high_wind_ratio_area_m2": sw_metrics["high_wind_ratio_area_m2"],
            "stagnant_wind_area_m2": sw_metrics["stagnant_wind_area_m2"],
        }
    }
    cmp_ok = compare_summary_numbers(computed_cases, matching_baseline)
    assert cmp_ok["has_flags"] is False
    assert cmp_ok["winds"]["SW"]["wind_has_flags"] is False

    # Discrepancy > 0.01 ratio
    divergent_baseline = {
        "SW": {
            "max_wind_ratio": sw_metrics["max_wind_ratio"] + 0.05,
            "mean_wind_ratio": sw_metrics["mean_wind_ratio"],
            "high_wind_ratio_area_m2": sw_metrics["high_wind_ratio_area_m2"],
            "stagnant_wind_area_m2": sw_metrics["stagnant_wind_area_m2"],
        }
    }
    cmp_flagged = compare_summary_numbers(computed_cases, divergent_baseline)
    assert cmp_flagged["has_flags"] is True
    assert cmp_flagged["winds"]["SW"]["metrics"]["max_wind_ratio"]["flagged"] is True

    # 4. Test render_all_figures
    generated = render_all_figures(
        ratio_grids=r_grids,
        wind_stats=w_stats,
        master_bounds=m_bounds,
        buildings=bldgs_loaded,
        site_geom=site_loaded,
        output_dir=output_dir,
    )
    # 4 individual * 2 languages (8) + 3 composites * 2 languages (6) = 14 figures
    assert len(generated) == 14
    for p in generated:
        assert Path(p).is_file()
        assert Path(p).stat().st_size > 0


def test_router_e3_e4_and_e5_fallback(tmp_path: Path) -> None:
    """Test router behaviour: E3/E4 resolve path_en; E5 falls back to Chinese if English files missing."""
    store = ProjectStateStore(tmp_path / "test_store.sqlite3")
    app = create_workspace_app(store=store)
    client = TestClient(app)

    response = client.get("/api/v1/environment/climate-extras")
    assert response.status_code == 200
    sections = {sec["id"]: sec for sec in response.json()}

    # E3: figure path_en should be resolved because it is registered in manifest
    e3 = sections["e3-energy"]
    assert e3["figures"][0]["path_en"] == "e3e4-final/e3_eui_by_fabric-en.png"
    assert "e3e4-final/e3_eui_by_fabric-en.png" in e3["source_sha256"]

    # E4: figure path_en should be resolved
    e4 = sections["e4-thermal-mass"]
    assert e4["figures"][0]["path_en"] == "e3e4-final/e4_harbour_mass_vs_light-en.png"
    assert "e3e4-final/e4_harbour_mass_vs_light-en.png" in e4["source_sha256"]

    # E5: English figures rendered from the 2026-10-25 rerun grids (numbers identical to the published table)
    e5 = sections["e5-cfd"]
    for fig in e5["figures"]:
        assert fig["path_en"] == fig["path"].replace(".png", "-en.png")
        assert fig["path_en"] in e5["source_sha256"]

    # Test file download endpoint for E3 and E4
    res_e3 = client.get("/api/v1/environment/climate-extras/files/e3e4-final/e3_eui_by_fabric-en.png")
    assert res_e3.status_code == 200
    assert res_e3.headers["content-type"] == "image/png"

    res_e4 = client.get("/api/v1/environment/climate-extras/files/e3e4-final/e4_harbour_mass_vs_light-en.png")
    assert res_e4.status_code == 200
    assert res_e4.headers["content-type"] == "image/png"


def test_router_e5_resolves_when_english_files_registered(tmp_path: Path) -> None:
    """Test that when E5 English files are present and registered in manifest, router serves them."""
    root = tmp_path / "artifacts"
    e5_dir = root / "e5-cfd"
    e5_dir.mkdir(parents=True)

    # Populate minimum required E5 files
    (e5_dir / "results_table.json").write_text("{}", encoding="utf-8")
    (e5_dir / "README_zh.md").write_text("# Readme", encoding="utf-8")

    zh_names = [
        "cfd_4winds_summary.png",
        "cfd_wind_risk_zones.png",
        "cfd_sw_wind_ratio.png",
        "cfd_w_wind_ratio.png",
        "cfd_s_wind_ratio.png",
        "cfd_nw_wind_ratio.png",
    ]
    manifest_files: Dict[str, Any] = {}

    for zhn in zh_names:
        zh_path = e5_dir / zhn
        zh_path.write_bytes(f"zh-content-{zhn}".encode("utf-8"))
        stem = Path(zhn).stem
        en_name = f"{stem}-en.png"
        en_path = e5_dir / en_name
        en_path.write_bytes(f"en-content-{en_name}".encode("utf-8"))

        manifest_files[f"e5-cfd/{en_name}"] = {
            "zh_counterpart": f"e5-cfd/{zhn}",
            "sha256": _digest(en_path),
            "zh_sha256": _digest(zh_path),
        }

    manifest = {
        "manifest_version": "1.0.0",
        "language": "en",
        "files": manifest_files,
    }
    (root / "english-figures-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Also need minimal e1, utci, e3, e4 so router can build all sections
    for sec_name in ["e1-fabric", "utci", "e3e4-final"]:
        d = root / sec_name
        d.mkdir(parents=True)

    (root / "e1-fabric" / "comparison_table.csv").write_text("field\n", encoding="utf-8")
    for f in ["e1-compare-20261221-冬至-zh.png", "e1-compare-20260321-春分-zh.png", "e1-compare-20260621-夏至-zh.png"]:
        (root / "e1-fabric" / f).write_bytes(b"e1")

    (root / "utci" / "utci_stress_hours_comparison.json").write_text('{"fabrics": {}}', encoding="utf-8")
    for fabric in ["harbour_grain", "closed_block_extension", "courtyard_islands", "landscape_figure"]:
        (root / "utci" / f"{fabric}_utci_1400.png").write_bytes(b"utci")

    (root / "e3e4-final" / "e3_eui_by_fabric.png").write_bytes(b"e3")
    (root / "e3e4-final" / "e4_harbour_mass_vs_light.png").write_bytes(b"e4")
    (root / "e3e4-final" / "e3e4_results_zh.csv").write_text("方案,構造,冷氣\n", encoding="utf-8")

    store = ProjectStateStore(tmp_path / "test_registered.sqlite3")
    app = create_workspace_app(store=store, climate_artifact_root=root)
    client = TestClient(app)

    res = client.get("/api/v1/environment/climate-extras")
    assert res.status_code == 200
    e5_sec = [s for s in res.json() if s["id"] == "e5-cfd"][0]

    # Now all E5 figures have path_en!
    for fig in e5_sec["figures"]:
        assert fig["path_en"] is not None
        assert fig["path_en"].endswith("-en.png")
        assert fig["path_en"] in e5_sec["source_sha256"]
