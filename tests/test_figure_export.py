"""Tests for deterministic figure export (CP4-7)."""

from pathlib import Path
import hashlib
import json
import pytest
from shapely.geometry import box, LineString


def test_figure_export_generates_valid_png(tmp_path):
    from urban_design.figure_export import render_site_syntax_figure

    study_area = box(88600, 435500, 89600, 436300)
    segments = [
        {"geometry": LineString([(88700, 435600), (89500, 435600)]), "value": 1.25, "id": "s1"},
        {"geometry": LineString([(89000, 435500), (89000, 436200)]), "value": 2.10, "id": "s2"},
    ]
    out_png = tmp_path / "test_figure.png"

    res = render_site_syntax_figure(
        study_area_geom=study_area,
        study_area_id="study-area-rotterdam-m4h-v5",
        segments_data=segments,
        metric_name="Angular Integration (NAIN, 800m)",
        output_path=out_png,
        title="Rotterdam M4H — Local Scale Space Syntax Integration",
    )

    assert out_png.exists()
    assert out_png.stat().st_size > 500  # Valid non-empty PNG
    # Check PNG magic bytes
    with open(out_png, "rb") as f:
        header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n"

    assert res["status"] == "EXPLORATORY_RENDERED"
    assert res["formal_result_eligible"] is False
    assert res["exploratory_only"] is True
    assert res["sha256"].startswith("sha256:")


def _write_source_linked_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    study_path = tmp_path / "study-area.geojson"
    context_path = tmp_path / "context.geojson"
    manifest_path = tmp_path / "source-manifest.json"
    result_path = tmp_path / "syntax-result.json"
    study_doc = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
        }
    }
    context_doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"way/{idx}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[5, idx * 10], [95, idx * 10]],
                },
                "properties": {"source_feature_id": f"way/{idx}", "tags": {"highway": "residential", "layer": "0"}},
            }
            for idx in range(1, 7)
        ],
    }
    study_path.write_text(json.dumps(study_doc), encoding="utf-8")
    context_path.write_text(json.dumps(context_doc), encoding="utf-8")
    segment_mapping = {
        f"osm_way/{idx}_seg_0": {
            "source_feature_id": f"way/{idx}",
            "source_artifact_id": "artifact-road-1",
            "source_snapshot_id": "snapshot-road-1",
        }
        for idx in range(1, 7)
    }
    manifest = {
        "package_id": "spatial-r01-fixture",
        "package_revision": "fixture-rev-1",
        "study_area_id": "study-area-fixture-v5",
        "crs": "EPSG:28992",
        "study_area_geojson_sha256": hashlib.sha256(study_path.read_bytes()).hexdigest(),
        "context_geojson_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "segment_mapping": segment_mapping,
        "source_completeness_evidence": None,
        "boundary_stability_evidence_by_radius_m": {},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    values = {segment_id: idx / 10 for idx, segment_id in enumerate(segment_mapping, start=1)}
    result = {
        "package_id": manifest["package_id"],
        "package_revision": manifest["package_revision"],
        "study_area_id": manifest["study_area_id"],
        "crs": "EPSG:28992",
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "study_area_geojson_sha256": manifest["study_area_geojson_sha256"],
        "context_geojson_sha256": manifest["context_geojson_sha256"],
        "extract_covers_envelope": None,
        "coverage_buffer_m": None,
        "stability_validated_radii_m": [],
        "layers": [
            {
                "layer_id": "syntax_local_800m_integration",
                "title": "Local Angular Integration",
                "radius_m": 800.0,
                "metric_key": "nain",
                "calculation_status": "COMPUTED",
                "data_readiness": "BLOCKED_COVERAGE_EVIDENCE_ABSENT",
                "statistics": {"min": 0.1, "max": 0.6, "count": 6},
                "segment_values": values,
            }
        ],
    }
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return study_path, context_path, manifest_path, result_path


def test_formal_figure_render_uses_linked_source_result_and_marks_blocked(tmp_path):
    import re
    from scripts.render_syntax_figure import render_formal_syntax_figure

    study_path, context_path, manifest_path, result_path = _write_source_linked_fixture(tmp_path)
    out_png = tmp_path / "test_formal_figure.png"
    result = render_formal_syntax_figure(
        output_path=out_png,
        study_area_geojson_path=study_path,
        context_geojson_path=context_path,
        source_manifest_path=manifest_path,
        syntax_result_path=result_path,
        layer_id="syntax_local_800m_integration",
        min_coverage_pct=100.0,
    )

    assert result["status"] == "EXPLORATORY_RENDERED"
    assert result["formal_result_eligible"] is False
    assert result["exploratory_only"] is True
    assert result["data_readiness"] == "BLOCKED_COVERAGE_EVIDENCE_ABSENT"
    assert result["radius_m"] == 800.0
    assert result["coverage_pct"] == 100.0
    assert result["data_colors_count"] >= 5
    assert len(result["distinct_colors"]) >= 5
    assert result["source_manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert result["context_sha256"] == hashlib.sha256(context_path.read_bytes()).hexdigest()
    assert result["study_area_sha256"] == hashlib.sha256(study_path.read_bytes()).hexdigest()

    svg_path = out_png.with_suffix(".svg")
    assert svg_path.exists()
    svg_content = svg_path.read_text()
    assert 'points=' in svg_content
    assert "SOURCE COVERAGE INSUFFICIENT" in svg_content
    assert "EXPLORATORY ONLY" in svg_content
    assert "BLOCKED COVERAGE EVIDENCE" in svg_content
    assert "ABSENT" in svg_content
    assert "study-area-fixture-v5" in svg_content
    # Check data colors present in svg
    colors = set(re.findall(r'stroke="(#[0-9a-fA-F]{6})"', svg_content))
    assert len(colors - {"#94a3b8", "#cbd5e1", "#86efac", "#ffffff"}) >= 5


def test_formal_figure_rejects_result_segment_without_verified_mapping(tmp_path):
    from scripts.render_syntax_figure import render_formal_syntax_figure

    study_path, context_path, manifest_path, result_path = _write_source_linked_fixture(tmp_path)
    result = json.loads(result_path.read_text())
    result["layers"][0]["segment_values"]["invented-segment"] = 9.9
    result_path.write_text(json.dumps(result))

    with pytest.raises(ValueError, match="unmapped segments"):
        render_formal_syntax_figure(
            tmp_path / "must-not-render.png",
            study_area_geojson_path=study_path,
            context_geojson_path=context_path,
            source_manifest_path=manifest_path,
            syntax_result_path=result_path,
        )


def test_formal_figure_rejects_obsolete_source_complete_flag(tmp_path):
    from scripts.render_syntax_figure import render_formal_syntax_figure

    study_path, context_path, manifest_path, result_path = _write_source_linked_fixture(tmp_path)
    result = json.loads(result_path.read_text())
    result["source_complete"] = False
    result_path.write_text(json.dumps(result))

    with pytest.raises(ValueError, match="obsolete source_complete flag"):
        render_formal_syntax_figure(
            tmp_path / "must-not-render.png",
            study_area_geojson_path=study_path,
            context_geojson_path=context_path,
            source_manifest_path=manifest_path,
            syntax_result_path=result_path,
        )


def test_formal_figure_does_not_treat_an_uncovered_extract_as_validated(tmp_path):
    from scripts.render_syntax_figure import render_formal_syntax_figure

    study_path, context_path, manifest_path, result_path = _write_source_linked_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["source_completeness_evidence"] = {"evidence_id": "fixture-only"}
    manifest["boundary_stability_evidence_by_radius_m"] = {"800.0": {"evidence_id": "fixture-only"}}
    manifest_path.write_text(json.dumps(manifest))
    result = json.loads(result_path.read_text())
    result["source_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    result["extract_covers_envelope"] = False
    result["coverage_buffer_m"] = 1000.0
    result["stability_validated_radii_m"] = [800.0]
    result["layers"][0]["data_readiness"] = "VALIDATED_COVERAGE"
    result_path.write_text(json.dumps(result))

    with pytest.raises(ValueError, match="extract-envelope/completeness/stability evidence"):
        render_formal_syntax_figure(
            tmp_path / "must-not-render.png",
            study_area_geojson_path=study_path,
            context_geojson_path=context_path,
            source_manifest_path=manifest_path,
            syntax_result_path=result_path,
        )
