"""R04 regressions for explicit OSM road-length aggregation semantics."""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urban_design.analysis_persistence import persist_site_analysis_bundle
from urban_design.api import create_workspace_app
from urban_design.models import ActorKind
from urban_design.r04_evidence import (
    build_r04_observational_evidence_bundle,
    validate_r04_observational_evidence_bundle,
)
from urban_design.store import ProjectStateStore
from urban_design.workspace_sources import WorkspaceSourceCatalog
from urban_design.workspace_sources import DEFAULT_SPATIAL_R01_ROOT


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_DATABASE = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")


def _read_only_copy(tmp_path: Path) -> ProjectStateStore:
    target = tmp_path / "state.sqlite3"
    with sqlite3.connect(f"file:{LIVE_DATABASE}?mode=ro", uri=True) as source:
        source.execute("PRAGMA query_only=ON")
        with sqlite3.connect(target) as destination:
            source.backup(destination)
    return ProjectStateStore(target)


def _persist_r04_site_analysis(store: ProjectStateStore) -> None:
    catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
    bundle = build_r04_observational_evidence_bundle(catalog, store)
    persist_site_analysis_bundle(
        store,
        catalog,
        bundle,
        actor_kind=ActorKind.AGENT_AUTOMATION,
        actor_session_id="session-test-r04-api",
        idempotency_key="test-api-r04-site-analysis",
    )


def test_api_serves_r04_unique_centerline_card_with_dedup_diagnostics(tmp_path):
    store = _read_only_copy(tmp_path)
    try:
        _persist_r04_site_analysis(store)
        client = TestClient(create_workspace_app(store, source_package_root=DEFAULT_SPATIAL_R01_ROOT))
        response = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["evidence_cards_status"] == "VERIFIED_SOURCE_RESULT_ALIGNMENT"
        road = next(
            (card for card in data["evidence_cards"] if card["metric_key"] == "osm_highway_unique_centerline_length"),
            None,
        )
        assert road is not None, "API must expose the R04 deduplicated road metric, not the R03 way-sum card"
        assert road["card_id"].startswith("card-r04-")
        assert road["value"] == pytest.approx(8496.540522, abs=0.000001)
        assert road["unit"] == "m"
        assert road["algorithm_version"] == "r04-deduplicated-osm-centerline-union-v1"
        assert road["method_diagnostics"] == {
            "clipped_way_length_sum_m": 8501.232713,
            "deduplicated_centerline_length_m": 8496.540522,
            "overlap_multiplicity_excess_m": 4.692191,
        }
        assert any("coincident" in item.lower() for item in road["limitations"])
        assert all(card["source_package_revision"] == "spatial-r01" for card in data["evidence_cards"])
        assert all(card["output_sha256"].startswith("sha256:") for card in data["evidence_cards"])
    finally:
        store.close()


def test_api_fails_closed_when_source_package_changes_after_startup(tmp_path, monkeypatch):
    import urban_design.workspace_sources as workspace_sources

    store = _read_only_copy(tmp_path)
    app = create_workspace_app(store, source_package_root=DEFAULT_SPATIAL_R01_ROOT)

    def changed_package(_root):
        raise workspace_sources.AnalysisInputError("package integrity mismatch: normalized source changed")

    monkeypatch.setattr(workspace_sources, "load_m2a03_spatial_package", changed_package)
    try:
        client = TestClient(app)
        response = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")
        assert response.status_code == 503
        assert "verified source state is unavailable" in response.json()["detail"]
        assert "buildings" not in response.json()
        assert "source_integrity_status" not in response.json()
    finally:
        store.close()


def test_verified_package_loader_revalidates_instead_of_serving_cached_metadata(tmp_path, monkeypatch):
    import urban_design.workspace_sources as workspace_sources

    calls = []

    def changing_package(_root):
        calls.append(len(calls) + 1)
        return {"load_number": calls[-1]}

    monkeypatch.setattr(workspace_sources, "load_m2a03_spatial_package", changing_package)
    root = str(tmp_path / "same-package-path")
    try:
        first = workspace_sources._load_verified_package(root)
        second = workspace_sources._load_verified_package(root)
        assert first["load_number"] == 1
        assert second["load_number"] == 2
        assert len(calls) == 2
    finally:
        cache_clear = getattr(workspace_sources._load_verified_package, "cache_clear", None)
        if cache_clear:
            cache_clear()


def test_r04_builder_uses_source_aligned_coverage_limited_status(tmp_path):
    store = _read_only_copy(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        bundle = build_r04_observational_evidence_bundle(catalog, store)

        assert {card["status"] for card in bundle["cards"]} == {"SOURCE_ALIGNED_COVERAGE_LIMITED"}
    finally:
        store.close()


def test_r04_validator_preserves_legacy_status_for_otherwise_current_cards(tmp_path):
    store = _read_only_copy(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        legacy = build_r04_observational_evidence_bundle(catalog, store)
        for card in legacy["cards"]:
            card["status"] = "VERIFIED_OBSERVATION"

        cards = validate_r04_observational_evidence_bundle(legacy, catalog, store)

        assert cards == legacy["cards"]
        assert {card["status"] for card in cards} == {"VERIFIED_OBSERVATION"}
    finally:
        store.close()


def test_overlapping_clipped_ways_have_distinct_sum_and_unique_union_lengths():
    from shapely.geometry import LineString, box

    from urban_design.r04_evidence import calculate_clipped_road_length_metrics

    result = calculate_clipped_road_length_metrics(
        [LineString([(0, 0), (10, 0)]), LineString([(5, 0), (15, 0)])],
        box(0, -1, 10, 1),
    )
    assert result == {
        "clipped_way_length_sum_m": 15.0,
        "deduplicated_centerline_length_m": 10.0,
        "overlap_multiplicity_excess_m": 5.0,
    }


def test_crossings_at_a_point_do_not_reduce_unique_centerline_length():
    from shapely.geometry import LineString, box

    from urban_design.r04_evidence import calculate_clipped_road_length_metrics

    result = calculate_clipped_road_length_metrics(
        [LineString([(0, 0), (10, 0)]), LineString([(5, -5), (5, 5)])],
        box(-1, -6, 11, 6),
    )
    assert result["clipped_way_length_sum_m"] == pytest.approx(20.0)
    assert result["deduplicated_centerline_length_m"] == pytest.approx(20.0)
    assert result["overlap_multiplicity_excess_m"] == pytest.approx(0.0)


def test_site_context_exposes_source_scoped_site_analysis_cards(tmp_path):
    store = _read_only_copy(tmp_path)
    try:
        _persist_r04_site_analysis(store)
        client = TestClient(create_workspace_app(store, source_package_root=DEFAULT_SPATIAL_R01_ROOT))
        response = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")
        assert response.status_code == 200, response.text
        cards = {card["metric_key"]: card for card in response.json()["evidence_cards"]}

        usage = cards["bag_registered_gebruiksdoel_features"]
        assert usage["value"] == 31
        assert usage["unit"] == "features"
        assert usage["method_diagnostics"]["features_with_null_gebruiksdoel"] == 20
        assert usage["method_diagnostics"]["gebruiksdoel::industriefunctie"] == 13
        assert usage["method_diagnostics"]["gebruiksdoel::kantoorfunctie"] == 5
        assert "not a complete land-use inventory" in " ".join(usage["limitations"]).lower()
        assert usage["status"] == "VERIFIED_OBSERVATION"
        assert usage["study_area_id"] == "study-area-rotterdam-m4h-pilot-project-v5"
        assert usage["study_area_geometry_sha256"].startswith("sha256:")
        assert usage["source_artifact_ids"] and usage["dataset_snapshot_ids"]
        assert usage["input_sha256"].startswith("sha256:")
        assert usage["output_sha256"].startswith("sha256:")

        residual = cards["unclassified_surface_residual_area"]
        assert residual["value"] == pytest.approx(138891.771628, abs=0.001)
        assert residual["unit"] == "m²"
        residual_limitations = " ".join(residual["limitations"]).lower()
        assert "not open space" in residual_limitations
        assert "does not establish public access" in residual_limitations
        assert residual["source_artifact_ids"] and residual["dataset_snapshot_ids"]
    finally:
        store.close()


def test_r04_road_input_hash_excludes_derived_diagnostics(tmp_path):
    from urban_design.r03_evidence import _canonical_bytes, _sha256_bytes, build_observational_evidence_bundle
    from urban_design.r04_evidence import ROAD_METHOD, build_r04_observational_evidence_bundle

    store = _read_only_copy(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        r03 = build_observational_evidence_bundle(catalog, store)
        r04 = build_r04_observational_evidence_bundle(catalog, store)
        prior = next(card for card in r03["cards"] if card["metric_key"] == "osm_highway_centerline_length")
        road = next(card for card in r04["cards"] if card["metric_key"] == "osm_highway_unique_centerline_length")
        expected_inputs = {
            "method_definition": ROAD_METHOD,
            "scope": r04["scope"],
            "features": [
                {"id": item.feature_id, "artifact_id": item.source_artifact_id, "geometry": item.geometry}
                for item in catalog.roads
            ],
            "parents": prior["parents"],
            "study_area_geometry": catalog.study_area_geometry,
        }
        expected_input_sha = _sha256_bytes(_canonical_bytes(expected_inputs))
        assert road["input_sha256"] == expected_input_sha
        assert road["method_diagnostics"]["overlap_multiplicity_excess_m"] > 0
    finally:
        store.close()
