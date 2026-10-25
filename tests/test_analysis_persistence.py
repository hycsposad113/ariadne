"""Tests for analysis persistence, idempotency, and staleness detection (C3 / WC-2)."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urban_design.analysis_persistence import (
    get_persisted_site_analysis,
    get_persisted_syntax_bundle,
    persist_site_analysis_bundle,
    persist_syntax_bundle,
)
import urban_design.api as api_module
from urban_design.api import create_workspace_app
from urban_design.models import ActorKind, Artifact, EvidenceCard, ToolExecution
from urban_design.r03_syntax import load_verified_exploratory_syntax
from urban_design.r04_evidence import build_r04_observational_evidence_bundle
from urban_design.store import ProjectStateStore
from urban_design.workspace_sources import DEFAULT_SPATIAL_R01_ROOT, WorkspaceSourceCatalog

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_DATABASE = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")


def _copy_db(tmp_path: Path) -> ProjectStateStore:
    copy_path = tmp_path / "test_state.sqlite3"
    with sqlite3.connect(f"file:{LIVE_DATABASE}?mode=ro", uri=True) as source:
        source.execute("PRAGMA query_only=ON")
        with sqlite3.connect(copy_path) as target:
            source.backup(target)
    return ProjectStateStore(copy_path)


def _assert_authoritative_pd20_syntax_context(data: dict) -> None:
    layers = data["syntax_layers"]
    layer_plan = data["syntax_layer_plan"]
    assert data["syntax_layers_status"] == "EXPLORATORY_CANDIDATE"
    assert data["syntax_layers_source"] == "persisted_database_record"
    assert len(layers) == len(layer_plan) == 6
    expected_layer_specs = {
        ("pedestrian", 800.0, "nain"),
        ("pedestrian", 800.0, "nach"),
        ("bicycle", 2000.0, "nain"),
        ("bicycle", 2000.0, "nach"),
        ("motor_vehicle", 10000.0, "nain"),
        ("motor_vehicle", 10000.0, "nach"),
    }
    assert {
        (layer["network_mode"], layer["radius_m"], layer["metric_key"])
        for layer in layers
    } == expected_layer_specs
    assert {layer["layer_id"] for layer in layer_plan} == {
        layer["layer_id"] for layer in layers
    }
    assert all(layer["calculation_status"] == "COMPUTED" for layer in layers)
    assert all(layer["calculation_status"] == "COMPUTED" for layer in layer_plan)
    assert all(layer["evidence_level"] == "EXPLORATORY" for layer in layers)
    assert all(layer["formal_result_eligible"] is False for layer in layers)

    hash_fields = (
        "output_file_sha256",
        "source_manifest_sha256",
        "study_area_sha256",
        "syntax_result_sha256",
    )
    for layer in layers:
        assert layer["network_mode"]
        assert layer["radius_m"] > 0
        assert layer["network_policy_version"]
        assert isinstance(layer["limitations"], str) and layer["limitations"].strip()
        assert "method-comparison-v1: FAIL" in layer["limitations"]
        for field in hash_fields:
            digest = layer[field]
            assert len(digest) == 64
            assert all(char in "0123456789abcdef" for char in digest)

    segments = data["syntax_segments"]
    assert segments
    assert all(segment.get("geometry") for segment in segments)
    segment_ids_by_mode = {
        mode: {
            segment["id"]
            for segment in segments
            if segment["network_mode"] == mode
        }
        for mode in {segment["network_mode"] for segment in segments}
    }
    assert set(segment_ids_by_mode) == {"pedestrian", "bicycle", "motor_vehicle"}
    assert len(segments) == sum(len(ids) for ids in segment_ids_by_mode.values())
    for layer in layers:
        values = layer["segment_values"]
        assert set(values) == segment_ids_by_mode[layer["network_mode"]]
        assert len(values) == len(segment_ids_by_mode[layer["network_mode"]])

    assert any("method-comparison-v1: FAIL" in item for item in data["syntax_limitations"])


def test_site_context_serves_current_persisted_analysis(tmp_path):
    store = _copy_db(tmp_path)
    try:
        client = TestClient(create_workspace_app(store, source_package_root=DEFAULT_SPATIAL_R01_ROOT))
        res = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")
        assert res.status_code == 200
        data = res.json()
        assert data["evidence_cards_status"] == "VERIFIED_SOURCE_RESULT_ALIGNMENT"
        assert data["evidence_cards"]
        _assert_authoritative_pd20_syntax_context(data)
    finally:
        store.close()


def test_site_context_marks_verified_file_syntax_fallback_when_database_has_no_record(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _copy_db(tmp_path)
    no_persisted_result = {
        "status": "NOT_COMPUTED",
        "result_source": "none",
        "layers": [],
        "layer_plan": [],
        "segments": [],
        "figure": {},
        "limitations": ["No persisted Syntax ToolExecution found."],
    }
    file_result = {
        "status": "EXPLORATORY_CANDIDATE",
        "layers": [{"layer_id": "file-syntax-layer", "calculation_status": "COMPUTED"}],
        "layer_plan": [],
        "segments": [],
        "figure": {},
        "limitations": ["Verified file candidate."],
    }
    monkeypatch.setattr(api_module, "get_persisted_syntax_bundle", lambda *args, **kwargs: no_persisted_result)
    monkeypatch.setattr(api_module, "load_verified_exploratory_syntax", lambda *args, **kwargs: file_result)
    try:
        response = TestClient(
            create_workspace_app(store, source_package_root=DEFAULT_SPATIAL_R01_ROOT),
        ).get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")

        assert response.status_code == 200
        data = response.json()
        assert data["syntax_layers_source"] == "verified_file_fallback"
        assert data["syntax_layers"][0]["layer_id"] == "file-syntax-layer"
        assert any("No persisted Syntax record" in item for item in data["syntax_limitations"])
    finally:
        store.close()


def test_site_context_serves_persisted_syntax_bundle_with_segment_geometry(tmp_path):
    store = _copy_db(tmp_path)
    try:
        client = TestClient(
            create_workspace_app(store, source_package_root=DEFAULT_SPATIAL_R01_ROOT),
            raise_server_exceptions=False,
        )
        response = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")

        assert response.status_code == 200
        data = response.json()
        _assert_authoritative_pd20_syntax_context(data)
        assert data["syntax_figure"] == {}
    finally:
        store.close()


def test_persist_site_analysis_and_idempotency(tmp_path):
    store = _copy_db(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        bundle = build_r04_observational_evidence_bundle(catalog, store)

        event_count_before = len(store.events(catalog.project_id))

        exec_rec, artifact_rec, card_recs = persist_site_analysis_bundle(
            store,
            catalog,
            bundle,
            actor="agent-automation",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="session-test-wc2",
            idempotency_key="test-key-001",
        )

        assert exec_rec.payload["tool"] == "site-analysis"
        assert exec_rec.payload["status"] == "succeeded"
        assert artifact_rec.payload["type"] == "evidence_bundle"
        assert len(card_recs) == len(bundle["cards"])
        typed_execution = ToolExecution.model_validate(exec_rec.payload)
        typed_artifact = Artifact.model_validate(
            {key: value for key, value in artifact_rec.payload.items() if key != "bundle"}
        )
        typed_cards = [EvidenceCard.model_validate(record.payload) for record in card_recs]
        assert typed_execution.output_artifact_hashes == [typed_artifact.sha256]
        assert all(card.result.artifact_refs == typed_execution.output_artifact_refs for card in typed_cards)
        assert all(card.result.artifact_hashes == typed_execution.output_artifact_hashes for card in typed_cards)
        assert all(card.result.status.value == "computed" for card in typed_cards)
        assert typed_execution.parameters["persistence_schema_version"] == "typed-evidence-v2"

        event_count_after = len(store.events(catalog.project_id))
        assert event_count_after > event_count_before

        # Second persistence call with same idempotency key must not create new events
        exec_rec2, artifact_rec2, card_recs2 = persist_site_analysis_bundle(
            store,
            catalog,
            bundle,
            actor="agent-automation",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="session-test-wc2",
            idempotency_key="test-key-001",
        )
        assert exec_rec2.entity_id == exec_rec.entity_id
        assert artifact_rec2.entity_id == artifact_rec.entity_id
        assert len(store.events(catalog.project_id)) == event_count_after

        # API now serves persisted cards
        client = TestClient(create_workspace_app(store, source_package_root=DEFAULT_SPATIAL_R01_ROOT))
        res = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")
        assert res.status_code == 200
        data = res.json()
        assert data["evidence_cards_status"] == "VERIFIED_SOURCE_RESULT_ALIGNMENT"
        assert len(data["evidence_cards"]) == len(bundle["cards"])
    finally:
        store.close()


def test_persist_site_analysis_keeps_existing_legacy_card_status_on_replay(tmp_path):
    store = _copy_db(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        bundle = build_r04_observational_evidence_bundle(catalog, store)
        legacy_bundle = copy.deepcopy(bundle)
        legacy_card = legacy_bundle["cards"][0]
        legacy_card["status"] = "VERIFIED_OBSERVATION"
        card_id = legacy_card["card_id"]

        first_exec, first_artifact, _ = persist_site_analysis_bundle(
            store,
            catalog,
            legacy_bundle,
            actor_kind=ActorKind.AGENT_AUTOMATION,
            idempotency_key="test-legacy-status-replay",
        )
        saved_legacy_card = store.current(card_id).payload
        event_count_after_first_write = len(store.events(catalog.project_id))

        replay_exec, replay_artifact, _ = persist_site_analysis_bundle(
            store,
            catalog,
            bundle,
            actor_kind=ActorKind.AGENT_AUTOMATION,
            idempotency_key="test-legacy-status-replay",
        )

        assert saved_legacy_card["status"] == "VERIFIED_OBSERVATION"
        assert replay_exec.entity_id == first_exec.entity_id
        assert replay_artifact.payload["sha256"] == first_artifact.payload["sha256"]
        assert store.current(card_id).payload == saved_legacy_card
        assert len(store.events(catalog.project_id)) == event_count_after_first_write
    finally:
        store.close()


def test_staleness_detection_on_input_hash_change(tmp_path):
    store = _copy_db(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        bundle = build_r04_observational_evidence_bundle(catalog, store)

        persist_site_analysis_bundle(
            store,
            catalog,
            bundle,
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="session-test-wc2",
        )

        # Fault injection: change study_area_geometry_sha256 on catalog
        mutated_catalog = copy.copy(catalog)
        object.__setattr__(mutated_catalog, "study_area_geometry_sha256", "0" * 64)

        bundle_out, cards_out, status, _, gaps = get_persisted_site_analysis(
            store, catalog.project_id, mutated_catalog
        )
        assert status == "STALE"
        assert any(g.get("status") == "STALE" for g in gaps)

        changed_snapshots = copy.copy(catalog)
        snapshot_records = dict(catalog.snapshots)
        snapshot_records["snapshot-new-input"] = {"sha256": "f" * 64}
        object.__setattr__(changed_snapshots, "snapshots", snapshot_records)
        _, _, snapshot_status, _, snapshot_gaps = get_persisted_site_analysis(
            store, catalog.project_id, changed_snapshots
        )
        assert snapshot_status == "STALE"
        assert any("snapshot" in g.get("reason", "").lower() for g in snapshot_gaps)

        changed_artifacts = copy.copy(catalog)
        artifact_records = copy.deepcopy(catalog.normalized_artifacts)
        artifact_id = next(iter(artifact_records))
        artifact_records[artifact_id]["sha256"] = "f" * 64
        object.__setattr__(changed_artifacts, "normalized_artifacts", artifact_records)
        _, _, artifact_status, _, artifact_gaps = get_persisted_site_analysis(
            store, catalog.project_id, changed_artifacts
        )
        assert artifact_status == "STALE"
        assert any("hash" in g.get("reason", "") for g in artifact_gaps)
    finally:
        store.close()


def test_persisted_site_analysis_blocks_artifact_hash_mismatch(tmp_path):
    store = _copy_db(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        bundle = build_r04_observational_evidence_bundle(catalog, store)
        _, artifact, _ = persist_site_analysis_bundle(store, catalog, bundle, idempotency_key="hash-check")

        corrupted = copy.deepcopy(artifact.payload)
        corrupted["bundle"]["integrity_fault_marker"] = "tampered"
        store.update(
            artifact.entity_id,
            corrupted,
            expected_revision=artifact.revision,
            actor="agent-automation",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="session-test-hash-fault",
            action="InjectArtifactHashFault",
            replace=True,
        )

        returned_bundle, cards, status, bundle_sha, gaps = get_persisted_site_analysis(
            store, catalog.project_id, catalog
        )
        assert status == "BLOCKED_ARTIFACT_HASH_MISMATCH"
        assert returned_bundle is None
        assert cards == []
        assert bundle_sha is None
        assert gaps[0]["status"] == "BLOCKED"
    finally:
        store.close()


def test_syntax_persistence_and_status(tmp_path):
    store = _copy_db(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        syntax = load_verified_exploratory_syntax(PROJECT_ROOT, catalog)

        # 1. Persist R02 historical syntax
        exec_r02, art_r02 = persist_syntax_bundle(
            store,
            catalog,
            syntax,
            is_historical_r02=True,
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="session-test-wc2",
            idempotency_key="r02-syntax-hist",
        )
        assert exec_r02.payload["tool"] == "space-syntax-historical"
        assert art_r02.payload["producer"] == "space-syntax-historical"
        assert ToolExecution.model_validate(exec_r02.payload).output_artifact_hashes == [
            Artifact.model_validate({key: value for key, value in art_r02.payload.items() if key != "bundle"}).sha256
        ]

        bundle_ret = get_persisted_syntax_bundle(store, catalog.project_id, catalog)
        assert bundle_ret["status"] == "EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT"
        assert len(bundle_ret["layers"]) == 2

        # 2. Persist new PST 3.3.1 recalculated results
        pst_layers_path = PROJECT_ROOT / "artifacts/week4-regional-osm/syntax_results/syntax_800m.json"
        if pst_layers_path.exists():
            pst_data = json.loads(pst_layers_path.read_text())
            pst_bundle = {
                "engine": "PST 3.3.1",
                "status": "COMPUTED",
                "layers": pst_data["layers"],
                "layer_plan": pst_data["layers"],
                "segments": [],
                "figure": {},
                "limitations": ["Recalculated with PST 3.3.1 from regional OSM PBF."],
            }
            exec_pst, art_pst = persist_syntax_bundle(
                store,
                catalog,
                pst_bundle,
                tool="PST 3.3.1",
                tool_version="3.3.1",
                is_historical_r02=False,
                actor_kind=ActorKind.AGENT_AUTOMATION,
                actor_session_id="session-test-wc2",
                idempotency_key="pst-331-recalc",
            )
            assert exec_pst.payload["tool"] == "PST 3.3.1"
            assert ToolExecution.model_validate(exec_pst.payload).output_artifact_hashes == [
                Artifact.model_validate({key: value for key, value in art_pst.payload.items() if key != "bundle"}).sha256
            ]

            # Prefer PST 3.3.1 over historical
            bundle_pst_ret = get_persisted_syntax_bundle(store, catalog.project_id, catalog)
            assert bundle_pst_ret["engine"] == "PST 3.3.1"
            assert bundle_pst_ret["status"] == "COMPUTED"
    finally:
        store.close()


def test_persisted_syntax_blocks_artifact_hash_mismatch(tmp_path):
    store = _copy_db(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        bundle = {
            "engine": "PST 3.3.1",
            "status": "COMPUTED",
            "layers": [],
            "layer_plan": [],
            "segments": [],
            "figure": {},
            "limitations": [],
        }
        _, artifact = persist_syntax_bundle(
            store,
            catalog,
            bundle,
            idempotency_key="hash-check",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="session-test-hash-fault",
        )
        corrupted = copy.deepcopy(artifact.payload)
        corrupted["bundle"]["integrity_fault_marker"] = "tampered"
        store.update(
            artifact.entity_id,
            corrupted,
            expected_revision=artifact.revision,
            actor="agent-automation",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="session-test-hash-fault",
            action="InjectArtifactHashFault",
            replace=True,
        )
        result = get_persisted_syntax_bundle(store, catalog.project_id, catalog)
        assert result["status"] == "BLOCKED_ARTIFACT_HASH_MISMATCH"
        assert result["layers"] == []
        assert all(layer["calculation_status"] == "BLOCKED" for layer in result["layer_plan"])
    finally:
        store.close()


def test_stale_persisted_syntax_does_not_expose_old_metric_values(tmp_path):
    store = _copy_db(tmp_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        layer = {
            "layer_id": "syntax_local_800m_integration",
            "radius_m": 800.0,
            "metric_key": "nain",
            "calculation_status": "COMPUTED",
            "data_readiness": "EXPLORATORY",
            "segment_values": {"segment-a": 0.42},
            "statistics": {"count": 1, "min": 0.42, "mean": 0.42, "max": 0.42},
            "legend_breaks": [0.42],
        }
        persist_syntax_bundle(
            store,
            catalog,
            {
                "engine": "PST 3.3.1",
                "status": "COMPUTED",
                "layers": [layer],
                "layer_plan": [layer],
                "segments": [],
                "figure": {},
                "limitations": [],
            },
            idempotency_key="stale-syntax-values",
            actor_kind=ActorKind.AGENT_AUTOMATION,
        )
        changed_catalog = copy.copy(catalog)
        object.__setattr__(changed_catalog, "study_area_geometry_sha256", "0" * 64)

        result = get_persisted_syntax_bundle(store, catalog.project_id, changed_catalog)

        assert result["status"] == "STALE"
        assert result["layers"][0]["calculation_status"] == "STALE"
        assert result["layers"][0]["segment_values"] == {}
        assert result["layers"][0]["statistics"] is None
        assert "legend_breaks" not in result["layers"][0]
    finally:
        store.close()
