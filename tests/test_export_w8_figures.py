import json
from pathlib import Path

from shapely.geometry import LineString, Polygon, box, mapping

from scripts import export_w8_figures as exporter


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


def _feature(geometry: object, properties: dict) -> dict:
    return {"type": "Feature", "geometry": mapping(geometry), "properties": properties}


def test_export_small_fake_w8_dataset(tmp_path: Path, monkeypatch) -> None:
    plans_dir = tmp_path / "plans"
    syntax_dir = tmp_path / "syntax"
    output_dir = tmp_path / "figures"
    context_dir = tmp_path / "context"
    monkeypatch.setattr(exporter, "CONTEXT_DATASET_DIR", context_dir)

    site = box(0, 0, 100, 80)
    plan = {
        "crs": "EPSG:28992",
        "site": mapping(site),
        "roads": [
            _feature(
                LineString([(0, 40), (100, 40)]),
                {"role": "primary_street", "width_m": 18, "modes": ["pedestrian"]},
            )
        ],
        "blocks": [],
        "buildings": [
            _feature(box(15, 45, 30, 60), {"height_m": 12, "retained": True}),
            _feature(box(60, 45, 80, 65), {"height_m": 18, "retained": False}),
        ],
        "land_use": [],
        "water": mapping(box(5, 5, 10, 15)),
        "metrics": {"new_gfa_m2": 500},
    }
    plans_dir.mkdir(parents=True)
    (plans_dir / "harbour_grain-plan.json").write_text(json.dumps(plan), encoding="utf-8")

    _write_geojson(
        syntax_dir / "segments" / "harbour_grain-pedestrian.geojson",
        [
            _feature(
                LineString([(10, 20), (90, 20)]),
                {
                    "comparison_status": "MATCHED_GEOMETRY",
                    "after_nain": 0.8,
                    "delta_nain": 0.04,
                    "after_nach": 1.1,
                    "is_new_street": False,
                    "inside_site": True,
                    "road_role": "primary_street",
                },
            ),
            _feature(
                LineString([(20, 30), (80, 30)]),
                {
                    "comparison_status": "NEW_OR_CHANGED_GEOMETRY",
                    "after_nain": 0.6,
                    "delta_nain": None,
                    "after_nach": 0.9,
                    "is_new_street": True,
                    "inside_site": True,
                    "road_role": "waterfront_path",
                },
            ),
            _feature(
                LineString([(20, 50), (80, 50)]),
                {
                    "comparison_status": "REMOVED",
                    "after_nain": None,
                    "delta_nain": None,
                    "after_nach": None,
                    "is_new_street": False,
                    "inside_site": True,
                },
            ),
        ],
    )

    _write_geojson(
        syntax_dir / "segments" / "harbour_grain-bicycle.geojson",
        [
            _feature(
                LineString([(10, 20), (90, 20)]),
                {
                    "comparison_status": "MATCHED_GEOMETRY",
                    "after_nain": 0.75,
                    "delta_nain": 0.02,
                    "after_nach": 1.25,
                    "is_new_street": False,
                    "inside_site": True,
                    "road_role": "primary_street",
                },
            ),
            _feature(
                LineString([(20, 30), (80, 30)]),
                {
                    "comparison_status": "NEW_OR_CHANGED_GEOMETRY",
                    "after_nain": 0.55,
                    "delta_nain": None,
                    "after_nach": 0.85,
                    "is_new_street": True,
                    "inside_site": True,
                    "road_role": "waterfront_path",
                },
            ),
        ],
    )

    _write_geojson(context_dir / "buildings.geojson", [_feature(box(-20, -20, -5, -5), {})])
    _write_geojson(context_dir / "roads.geojson", [_feature(LineString([(-20, 10), (120, 10)]), {})])
    _write_geojson(context_dir / "water.geojson", [_feature(Polygon([(-20, -20), (0, -20), (0, -5), (-20, -5)]), {})])

    manifest = exporter.run_export(plans_dir, syntax_dir, output_dir, "test-run")

    generated = [figure for figure in manifest["figures"] if figure["status"] == "GENERATED"]
    assert {figure["filename"] for figure in generated} >= {
        "harbour_grain-massing.png",
        "harbour_grain-existing-site.png",
        "harbour_grain-syntax-after.png",
        "harbour_grain-syntax-delta.png",
        "harbour_grain-site-nain-pedestrian.png",
        "harbour_grain-site-nach-pedestrian.png",
        "harbour_grain-site-nain-bicycle.png",
        "harbour_grain-site-nach-bicycle.png",
        "comparison-massing.png",
        "comparison-site-nain-pedestrian.png",
    }
    for figure in generated:
        assert figure["pixel_dimensions"][0] >= 3000
        assert figure["pixel_dimensions"][1] > 0
        assert figure["dpi"] >= 300
        assert len(figure["sha256"]) == 64
        assert figure["source_files"]
        assert all(len(source["sha256"]) == 64 for source in figure["source_files"])
        assert (output_dir / figure["filename"]).is_file()
        from PIL import Image
        with Image.open(output_dir / figure["filename"]) as image:
            assert min(image.info["dpi"]) >= 300

    # Verify site syntax figure specific metadata in manifest
    site_figures = [f for f in generated if "site-" in f["filename"] or "comparison-site" in f["filename"]]
    assert len(site_figures) >= 5
    for sf in site_figures:
        assert "class_breaks" in sf
        assert len(sf["class_breaks"]) == 6
        assert "network_percentiles" in sf
        assert len(sf["network_percentiles"]) == 6

    assert manifest["extent_buffer_m"] == 120.0
    assert manifest["axonometric_view_margin_m"] == 20.0
    assert manifest["crs"] == "EPSG:28992"
    assert manifest["context_data"]["status"] == "AVAILABLE"
    assert manifest["syntax_feature_summary"]["harbour_grain"]["new_street_count"] == 1
    assert "site_syntax_scales" in manifest
    assert "harbour_grain" in manifest["site_syntax_scales"]
    assert "comparison_site_nain_pedestrian" in manifest["site_syntax_scales"]
    assert manifest["e1_sunlight"]["status"] == "MISSING"
    assert any(
        figure["type"] == "e1_sunlight" and figure["status"] == "MISSING"
        for figure in manifest["figures"]
    )

