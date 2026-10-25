"""R03 exposes only verified exploratory Syntax outputs and a blocked radius plan."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from urban_design.store import ProjectStateStore
from urban_design.workspace_sources import WorkspaceSourceCatalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPATIAL_R01_ROOT = PROJECT_ROOT / (
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)
LIVE_DATABASE = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")


def _store(tmp_path: Path) -> ProjectStateStore:
    copy_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(f"file:{LIVE_DATABASE}?mode=ro", uri=True) as source:
        source.execute("PRAGMA query_only=ON")
        with sqlite3.connect(copy_path) as target:
            source.backup(target)
    return ProjectStateStore(copy_path)


def test_r03_syntax_exposes_only_two_computed_800m_layers(tmp_path):
    from urban_design.r03_syntax import load_verified_exploratory_syntax

    store = _store(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, SPATIAL_R01_ROOT)
        syntax = load_verified_exploratory_syntax(PROJECT_ROOT, catalog)
        assert syntax["status"] == "EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT"
        assert len(syntax["layers"]) == 2
        assert {layer["radius_m"] for layer in syntax["layers"]} == {800.0}
        assert all(layer["formal_result_eligible"] is False for layer in syntax["layers"])
        assert all(len(layer["segment_values"]) == 1272 for layer in syntax["layers"])
        assert len(syntax["layer_plan"]) == 6
        uncomputed = [layer for layer in syntax["layer_plan"] if layer["radius_m"] in (2000.0, 10000.0)]
        assert len(uncomputed) == 4
        assert all(layer["calculation_status"] == "NOT_COMPUTED_COVERAGE_BLOCKED" for layer in uncomputed)
        assert all(layer["segment_value_count"] == 0 for layer in uncomputed)
        assert all(layer["formal_result_eligible"] is False for layer in syntax["layer_plan"])
    finally:
        store.close()


def test_api_downloads_hash_verified_figure_with_exploratory_headers(tmp_path):
    import hashlib
    import json

    from urban_design.api import create_workspace_app

    store = _store(tmp_path)
    figure_record_path = PROJECT_ROOT / "artifacts/week4-repair-r03/syntax/figure-record.json"
    figure_record = json.loads(figure_record_path.read_text(encoding="utf-8"))
    frozen_svg_path = PROJECT_ROOT / figure_record["files"]["svg"]["path"]
    frozen_svg_bytes_before = frozen_svg_path.read_bytes()
    frozen_svg_sha256 = hashlib.sha256(frozen_svg_bytes_before).hexdigest()
    app = create_workspace_app(
        store,
        source_package_root=SPATIAL_R01_ROOT,
        syntax_figure_record_path=figure_record_path,
    )
    try:
        client = TestClient(app)
        context = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")
        assert context.status_code == 200, context.text
        context_data = context.json()
        assert context_data["syntax_layers_status"] == "EXPLORATORY_CANDIDATE"
        assert len(context_data["syntax_layers"]) == 6
        assert context_data["syntax_layers_source"] == "persisted_database_record"
        layers = context_data["syntax_layers"]
        assert all(layer["calculation_status"] == "COMPUTED" for layer in layers)
        assert all(layer["evidence_level"] == "EXPLORATORY" for layer in layers)
        assert all(layer["formal_result_eligible"] is False for layer in layers)
        syntax_segments = context_data["syntax_segments"]
        assert syntax_segments
        assert all(segment.get("geometry") for segment in syntax_segments)
        segment_ids_by_mode = {
            mode: {
                segment["id"]
                for segment in syntax_segments
                if segment["network_mode"] == mode
            }
            for mode in {segment["network_mode"] for segment in syntax_segments}
        }
        assert len(syntax_segments) == sum(len(ids) for ids in segment_ids_by_mode.values())
        for layer in layers:
            assert layer["network_mode"]
            assert layer["radius_m"] > 0
            assert layer["network_policy_version"]
            assert layer["limitations"]
            assert "method-comparison-v1: FAIL" in layer["limitations"]
            for field in ("output_file_sha256", "source_manifest_sha256", "study_area_sha256", "syntax_result_sha256"):
                digest = layer[field]
                assert len(digest) == 64
                assert all(char in "0123456789abcdef" for char in digest)
            values = layer["segment_values"]
            assert set(values) == segment_ids_by_mode[layer["network_mode"]]
            assert len(values) == len(segment_ids_by_mode[layer["network_mode"]])
        assert any("method-comparison-v1: FAIL" in item for item in context_data["syntax_limitations"])
        assert set(context_data["syntax_figure_downloads"]) == {"svg"}

        response = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/syntax/exploratory-figure.svg")
        assert response.status_code == 200, response.text
        assert response.headers["X-Evidence-Status"] == "EXPLORATORY_ONLY_SOURCE_COVERAGE_INSUFFICIENT"
        assert response.headers["X-Formal-Result-Eligible"] == "false"
        assert response.headers["X-Source-Figure-SHA256"] == f"sha256:{frozen_svg_sha256}"
        assert response.headers["X-Rendered-Figure-Semantics"] == "week4-count-clarification-v1"
        assert "EXPLORATORY ONLY" in response.text
        assert "SOURCE COVERAGE INSUFFICIENT" in response.text
        assert "Displayed linework: 1,328" in response.text
        assert "With Syntax values: 1,272" in response.text
        assert "Without Syntax values: 56" in response.text
        assert "Source-mapped network: 1,355 segments" in response.text
        assert 'x="956" y="513" font-size="9.5"' in response.text
        assert 'x="956" y="538" font-size="13"' in response.text
        assert "Segments: 1,328" not in response.text
        assert "1355 mapped segments" not in response.text
        assert response.content != frozen_svg_bytes_before
        assert hashlib.sha256(frozen_svg_path.read_bytes()).hexdigest() == frozen_svg_sha256

        png_response = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/syntax/exploratory-figure.png")
        assert png_response.status_code == 409
        assert "count labels" in png_response.json()["detail"]
    finally:
        store.close()
