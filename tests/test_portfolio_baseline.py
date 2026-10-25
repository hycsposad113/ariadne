"""Contract checks for the traceable human-designed portfolio baseline."""

from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

import pytest
from shapely.geometry import shape
from shapely.ops import unary_union

from scripts.build_portfolio_baseline import build_portfolio_baseline


WORKTREE = Path(__file__).resolve().parents[1]
PROJECT = WORKTREE.parent / "project"


def _features(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["features"]


def test_builder_emits_traceable_baseline_in_a_disposable_output(tmp_path: Path) -> None:
    out = tmp_path / "portfolio-baseline"
    build_portfolio_baseline(project_root=PROJECT, output_dir=out)

    expected = {
        "georef.json",
        "preserved-buildings.json",
        "zones.geojson",
        "open-spaces.geojson",
        "program.json",
        "intensity-portfolio.json",
        "intensity-A.json",
        "intensity-B.json",
        "portfolio-scenario.geojson",
    }
    assert expected <= {path.name for path in out.iterdir()}

    study_path = PROJECT / "artifacts/week4-repair-r02/syntax/study-area.geojson"
    study = shape(json.loads(study_path.read_text(encoding="utf-8"))["geometry"])
    normalized = PROJECT / (
        "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
        "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01/"
        "sources/normalized"
    )
    bag_ids: set[str] = set()
    for path in glob.glob(str(normalized / "pdok-bag-pand-p*.geojson")):
        bag_ids.update(
            str(feature.get("properties", {}).get("identificatie"))
            for feature in _features(Path(path))
            if feature.get("properties", {}).get("identificatie")
        )

    preserved = json.loads((out / "preserved-buildings.json").read_text(encoding="utf-8"))
    assert preserved["crs"] == "EPSG:28992"
    assert preserved["buildings"]
    assert all(row["bag_pand_id"] in bag_ids for row in preserved["buildings"])
    assert all(row["confidence"] in {"HIGH", "MEDIUM", "LOW"} for row in preserved["buildings"])
    assert all(row.get("reason") and row.get("source_page") for row in preserved["buildings"])

    water_parts = []
    for path in glob.glob(str(normalized / "pdok-bgt-waterdeel-*.geojson")):
        water_parts.extend(
            shape(feature["geometry"])
            for feature in _features(Path(path))
            if feature.get("geometry")
        )
    land = study.difference(unary_union(water_parts)) if water_parts else study
    for filename in ("zones.geojson", "open-spaces.geojson"):
        collection = json.loads((out / filename).read_text(encoding="utf-8"))
        assert collection["crs"] == {"type": "name", "properties": {"name": "EPSG:28992"}}
        for feature in collection["features"]:
            geom = shape(feature["geometry"])
            assert geom.is_valid and not geom.is_empty
            assert land.buffer(1e-6).covers(geom)
            assert feature["properties"].get("source_page")
            assert feature["properties"].get("extraction_method")

    program = json.loads((out / "program.json").read_text(encoding="utf-8"))
    assert program["tree_map"]["source_page"] == "p18-18.png"
    assert program["tree_map"]["readable_lower_bound_gfa_m2"] > 0
    assert program["tree_map"]["unreadable_item_count"] > 0
    assert all(item.get("source_page") and item.get("extraction_method") for item in program["tree_map"]["items"])
    assert program["tree_map"]["complete_treemap_gfa_m2"] is None
    assert program["tree_map"]["readable_lower_bound_gfa_m2"] == 109177
    assert all(
        category["status"] == "PARTIAL_LOWER_BOUND"
        for category in program["tree_map"]["category_readable_subtotals"].values()
    )
    intensity = json.loads((out / "intensity-portfolio.json").read_text(encoding="utf-8"))
    for metric in intensity["metrics"].values():
        assert metric.get("source_page") and metric.get("method") and metric.get("value") is not None

    scenario = json.loads((out / "portfolio-scenario.geojson").read_text(encoding="utf-8"))
    assert scenario["crs"]["properties"]["name"] == "EPSG:28992"
    assert scenario["features"]
    assert all(feature["properties"].get("floor_count_estimate") for feature in scenario["features"])
    assert all(shape(feature["geometry"]).is_valid for feature in scenario["features"])
    assert scenario["properties"]["metrics"]["provenance"] == "FIXTURE_ONLY"

    for filename, expected_status in (
        ("intensity-A.json", "ASSUMED_FROM_PORTFOLIO"),
        ("intensity-B.json", "ASSUMED_HIGH_DENSITY"),
    ):
        model = json.loads((out / filename).read_text(encoding="utf-8"))
        assert model["status"] == expected_status
        assert model["approval_decision_id"] == "ASSUMED_FROM_PORTFOLIO_2026-09-27"
        assert model["human_approval_recorded"] is False

    model_a = json.loads((out / "intensity-A.json").read_text(encoding="utf-8"))
    assert model_a["parameters"]["far_upper_bound_land"] == pytest.approx(
        intensity["metrics"]["land_far"]["value"] * 1.1, abs=1e-6
    )

    repeated = tmp_path / "portfolio-baseline-repeat"
    build_portfolio_baseline(project_root=PROJECT, output_dir=repeated)
    output_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in out.iterdir()
        if path.is_file()
    }
    repeated_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in repeated.iterdir()
        if path.is_file()
    }
    assert output_hashes == repeated_hashes
