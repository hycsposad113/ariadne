"""Tests for Task K: Rotterdam M4H Site Analysis Report and Claims Verification.

Verifies:
1. claims.json structure, required fields, and non-empty sources/limitations.
2. Exact recomputation of key numerical metrics by scripts.build_site_analysis_report.
3. Existence and validity of all 12 generated PNG figures under 1.5 MB each.
4. Report presence, mandatory chapters (a)-(i), review record, and disclaimers.
5. Optional syntax-map redraw, skipped when this test interpreter lacks matplotlib.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = ROOT / "artifacts/w5-site-analysis/claims.json"
REPORT_PATH = ROOT / "docs/w5/site-analysis-report-zh.md"
FIGURES_DIR = ROOT / "artifacts/w5-site-analysis/figures"


def test_claims_json_structure_and_sources():
    assert CLAIMS_PATH.exists(), f"claims.json missing at {CLAIMS_PATH}"
    data = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 24, f"Expected 24 retained claims, got {len(data)}"
    assert "claim-w5-site-011" not in {claim["id"] for claim in data}

    required_keys = {"id", "章節", "敘述", "數值", "來源檔案或證據 ID", "證據層級", "限制"}
    chapters_found = set()

    for claim in data:
        missing = required_keys - set(claim.keys())
        assert not missing, f"Claim {claim.get('id')} missing keys: {missing}"
        assert claim["id"].strip(), "Claim ID must not be empty"
        assert claim["章節"].strip(), f"Claim {claim['id']} chapter empty"
        assert claim["敘述"].strip(), f"Claim {claim['id']} statement empty"
        assert claim["來源檔案或證據 ID"].strip(), f"Claim {claim['id']} source empty"
        assert claim["證據層級"].strip(), f"Claim {claim['id']} tier empty"
        
        limits = claim["限制"]
        assert limits, f"Claim {claim['id']} must declare limitations"
        if isinstance(limits, list):
            assert all(str(l).strip() for l in limits), f"Claim {claim['id']} has empty limitation"

        chapters_found.add(claim["章節"])

    expected_chapters = {
        "範圍與資料來源",
        "既有建築",
        "道路與交通",
        "機能與土地使用",
        "開放空間與水體",
        "Space Syntax",
        "資料缺口與建議補充",
    }
    missing_chapters = expected_chapters - chapters_found
    assert not missing_chapters, f"claims.json missing coverage for chapters: {missing_chapters}"


def test_metrics_recomputation_consistency():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_site_analysis_report import compute_site_metrics

    metrics = compute_site_metrics()
    assert metrics is not None

    # Study Area
    study = metrics["study_area"]
    assert pytest.approx(study["area_m2"], rel=1e-3) == 226064.33
    assert study["crs"] == "EPSG:28992"

    # Buildings
    bld = metrics["buildings"]
    assert bld["count"] == 51
    assert pytest.approx(bld["footprint_area_m2"], rel=1e-3) == 44699.56
    assert pytest.approx(bld["footprint_share_pct"], rel=1e-3) == 19.77
    assert bld["registered_gebruiksdoel_count"] == 31
    assert bld["null_gebruiksdoel_count"] == 20

    # 3D BAG
    bld_3d = bld["3dbag"]
    assert bld_3d["matched_count"] == 31
    assert bld_3d["unmatched_count"] == 20
    assert pytest.approx(bld_3d["median_m"], rel=1e-2) == 9.85
    assert pytest.approx(bld_3d["max_m"], rel=1e-2) == 27.41
    assert pytest.approx(bld_3d["min_m"], rel=1e-2) == 2.68
    assert bld_3d["demolished_in_bag_count"] == 19

    # Roads
    roads = metrics["roads"]
    assert pytest.approx(roads["deduplicated_centerline_length_m"], rel=1e-3) == 8496.54
    assert roads["gateway_points_count"] == 22

    # Water & Open Space
    water_open = metrics["water_and_open_space"]
    assert pytest.approx(water_open["bgt_water_area_m2"], rel=1e-3) == 42472.998
    assert pytest.approx(water_open["unclassified_surface_residual_m2"], rel=1e-3) == 138891.77
    assert pytest.approx(water_open["quay_interface_length_m"], rel=1e-2) == 1332.04
    assert pytest.approx(water_open["osm_green_area_m2"], rel=1e-2) == 21886.06
    assert water_open["osm_green_feature_count"] == 21
    assert water_open["green_by_type"] == {"grass": 11454.32, "forest": 1526.74, "allotments": 8905.0}

    # Space Syntax 6 layers
    syntax = metrics["syntax"]
    assert len(syntax["layers"]) == 6
    l0 = syntax["layers"][0]
    assert l0["layer_id"] == "syntax_local_800m_integration"
    assert l0["statistics"]["count"] == 481
    assert pytest.approx(l0["statistics"]["max"], rel=1e-3) == 1.2729
    assert len(l0["legend_breaks"]) == 6
    expected_site_quintile_counts = [
        [96, 95, 95, 95, 96],
        [96, 95, 95, 95, 96],
        [27, 26, 26, 26, 27],
        [29, 24, 26, 26, 27],
        [14, 14, 14, 14, 14],
        [14, 14, 14, 14, 14],
    ]
    assert [layer["site_map"]["quintile_counts"] for layer in syntax["layers"]] == expected_site_quintile_counts
    assert [layer["site_map"]["segment_count"] for layer in syntax["layers"]] == [477, 477, 132, 132, 70, 70]


def test_quintile_helpers_create_balanced_site_bins():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_site_analysis_report import linear_quintile_breaks, quintile_counts

    breaks = linear_quintile_breaks(list(range(1, 21)))
    assert breaks == pytest.approx([1.0, 4.8, 8.6, 12.4, 16.2, 20.0])
    assert quintile_counts(list(range(1, 21)), breaks) == [4, 4, 4, 4, 4]


def test_generated_figures_integrity_and_size():
    assert FIGURES_DIR.exists(), f"Figures directory missing: {FIGURES_DIR}"
    
    expected_figures = [
        "fig01_scope_and_context.png",
        "fig02_existing_buildings_height.png",
        "fig03_transport_road_network.png",
        "fig04_land_use_and_functions.png",
        "fig05_open_space_and_water.png",
        "fig06_syntax_local_800m_integration.png",
        "fig07_syntax_local_800m_choice.png",
        "fig08_syntax_mid_2000m_integration.png",
        "fig09_syntax_mid_2000m_choice.png",
        "fig10_syntax_regional_10000m_integration.png",
        "fig11_syntax_regional_10000m_choice.png",
        "fig12_regional_urban_relationships.png",
    ]

    for fname in expected_figures:
        fpath = FIGURES_DIR / fname
        assert fpath.exists(), f"Figure file missing: {fname}"
        
        # Verify valid PNG header (\x89PNG\r\n\x1a\n)
        header = fpath.read_bytes()[:8]
        assert header == b"\x89PNG\r\n\x1a\n", f"Invalid PNG magic header: {fname}"
        
        # Verify size < 1.5 MB (1,500,000 bytes)
        size = fpath.stat().st_size
        assert size < 1_500_000, f"Figure {fname} exceeds 1.5 MB: {size} bytes"
        assert size > 10_000, f"Figure {fname} is suspiciously small: {size} bytes"


def test_markdown_report_contents():
    assert REPORT_PATH.exists(), f"Markdown report missing at {REPORT_PATH}"
    content = REPORT_PATH.read_text(encoding="utf-8")

    # Author and status requirement
    assert "AntiGravity" in content or "Gemini 3.8 Flash" in content
    assert "待設計者審閱" in content
    assert "審查紀錄" in content
    assert "Codex" in content
    assert "review-codex.md" in content
    assert "QGIS-LTR.app/Contents/MacOS/bin/python3" in content
    assert "找不到 matplotlib" in content
    assert "21 個" in content
    assert "基地內著色段數" in content

    # All chapters (a) through (i)
    chapters = [
        "(a) 範圍與資料來源",
        "(b) 既有建築",
        "(c) 道路與交通",
        "(d) 機能與土地使用",
        "(e) 開放空間與水體",
        "(f) 空間語法",
        "(g) 周邊都市關係",
        "(h) SWOT",
        "(i) 資料缺口",
    ]
    for ch in chapters:
        assert ch in content, f"Report missing chapter: {ch}"

    # Critical methodology disclaimers
    assert "method-comparison-v1" in content
    assert "FAIL" in content
    assert "EXPLORATORY" in content
    assert "PST 3.3.1" in content
    assert "嚴禁將整合度" in content or "不得將 integration 說成人流" in content
    assert "嚴禁將穿行度" in content or "不得將 choice 說成交通量" in content

    # Embedded figure checks
    for i in range(1, 13):
        assert f"fig{i:02d}_" in content, f"Report missing embed for figure {i}"


def test_syntax_map_rerender_when_matplotlib_is_available(tmp_path):
    import importlib.util
    import os
    import subprocess
    import sys

    if importlib.util.find_spec("matplotlib") is None:
        pytest.skip("matplotlib is unavailable in this test interpreter; PNG redraw skipped")

    output_dir = tmp_path / "syntax-figures"
    env = dict(os.environ)
    env["MPLCONFIGDIR"] = str(tmp_path / "matplotlib-config")
    env["PROJ_LIB"] = "/Applications/QGIS-LTR.app/Contents/Resources/proj"
    env["PYTHONPATH"] = f"{ROOT / 'scripts'}:{ROOT / 'src'}:{env.get('PYTHONPATH', '')}"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/render_site_analysis_maps.py"),
            "--syntax-only",
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        timeout=600,
    )
    assert len(list(output_dir.glob("fig*.png"))) == 6
