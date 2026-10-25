"""Tests for E2 formal run wiring: server config, validate-methods endpoint, and plan request assembly."""
import json
from pathlib import Path
import secrets
import sqlite3

import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.decision_key import initialize_decision_key
from urban_design.store import ProjectStateStore
from scripts.run_workspace_server import build_parser, apply_e2_config
from scripts.e2_formal_run import build_plan_request, COMPACT, MIXED


AUTH_DB_PATH = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
PROJECT_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/project")
PROPOSAL_ROOT = PROJECT_ROOT / "artifacts/w5-weather-derived-method-proposal-20260926T115309Z"
DRILL_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "artifacts/w8/e2-drill/api-04.json"


@pytest.fixture
def disposable_authority(tmp_path):
    """Create a temporary DB copy from the authoritative DB in read-only mode."""
    auth = AUTH_DB_PATH
    if not auth.exists():
        auth = Path.cwd().parent / "project/.urban_design_runtime/state.sqlite3"
    assert auth.exists(), f"Authoritative DB not found at {auth}"

    copy_path = tmp_path / "copy.sqlite3"
    with sqlite3.connect(auth.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(copy_path) as destination:
            source.backup(destination)

    store = ProjectStateStore(copy_path)
    projects = store.list_current("Project")
    assert len(projects) > 0, "No projects in authoritative DB copy"
    project_id = projects[0].entity_id

    key = secrets.token_urlsafe(32)
    key_path = initialize_decision_key(path=tmp_path / "test-key", password_prompt=lambda _: key)

    return store, project_id, key, key_path, tmp_path


def test_e2_cli_parser_and_apply_config(tmp_path):
    parser = build_parser()
    args = parser.parse_args([
        "--e2-weather-proposal-root", str(PROPOSAL_ROOT),
        "--e2-weather-source-root", str(PROJECT_ROOT),
        "--e2-artifact-root", str(tmp_path / "artifacts"),
        "--e2-job-database", str(tmp_path / "jobs.sqlite3"),
    ])
    assert args.e2_weather_proposal_root == PROPOSAL_ROOT
    assert args.e2_weather_source_root == PROJECT_ROOT
    assert args.e2_artifact_root == tmp_path / "artifacts"
    assert args.e2_job_database == tmp_path / "jobs.sqlite3"

    # Test applying to an app
    class DummyApp:
        class State:
            pass
        state = State()

    dummy = DummyApp()
    apply_e2_config(dummy, args)
    assert dummy.state.e2_weather_proposal_root == PROPOSAL_ROOT
    assert dummy.state.e2_weather_source_root == PROJECT_ROOT
    assert dummy.state.e2_artifact_root == tmp_path / "artifacts"
    assert dummy.state.e2_job_database == tmp_path / "jobs.sqlite3"


def test_e2_unconfigured_server_returns_blocked(disposable_authority):
    store, project_id, key, key_path, tmp_path = disposable_authority
    # App created without E2 parameters configured
    app = create_workspace_app(store=store, decision_key_path=key_path)
    with TestClient(app) as client:
        resp = client.post("/api/v1/environment/e2/weather/snapshots", json={"project_id": project_id})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["status"] == "BLOCKED"
        assert detail["reason"] == "WEATHER_SOURCE_PATHS_NOT_CONFIGURED"


def test_e2_validation_endpoint_workflow(disposable_authority, monkeypatch):
    store, project_id, key, key_path, tmp_path = disposable_authority
    app = create_workspace_app(store=store, decision_key_path=key_path)

    # Configure server parameters
    app.state.e2_weather_proposal_root = PROPOSAL_ROOT
    app.state.e2_weather_source_root = PROJECT_ROOT
    app.state.e2_artifact_root = tmp_path / "artifacts"
    app.state.e2_job_database = tmp_path / "e2-jobs.sqlite3"

    with TestClient(app) as client:
        # 1. Proposal succeeds with parameters configured
        resp = client.post("/api/v1/environment/e2/weather/snapshots", json={"project_id": project_id})
        assert resp.status_code == 201, resp.text
        snapshot = resp.json()
        snapshot_id = snapshot["snapshot_id"]
        assert snapshot["status"] == "PROPOSED"
        assert snapshot_id.startswith("snapshot-e2-weather-")

        # 2. Before approval, validate-methods returns 409
        val_resp_unapproved = client.post(
            f"/api/v1/environment/e2/weather/snapshots/{snapshot_id}/validate-methods",
            json={"project_id": project_id},
        )
        # The snapshot id is content-addressed; once the Founder approved it in the authority DB
        # (2026-10-16), every copy already carries that approval. Then the gate must pass only
        # because a real approved human decision targets this snapshot.
        already_approved = any(
            r.payload.get("target_id") == snapshot_id and str(r.payload.get("status", "")).lower() == "approved"
            for r in store.list_current("HumanDecision", project_id=project_id))
        if already_approved:
            assert val_resp_unapproved.status_code == 200, val_resp_unapproved.text
        else:
            assert val_resp_unapproved.status_code == 409
            detail = val_resp_unapproved.json()["detail"]
            assert detail["status"] == "BLOCKED"
            assert "NOT_APPROVED" in detail["reason"]

        # 3. Approve the snapshot (skipped when the copy already holds the Founder approval)
        dec_resp = None if already_approved else client.post(f"/api/v1/projects/{project_id}/decisions", json={
            "target_id": snapshot_id,
            "target_type": snapshot["decision_target_type"],
            "target_version": snapshot["version"],
            "target_payload_digest": snapshot["payload_digest"],
            "action": "Approve",
            "status": "approved",
            "reason": "Test approve weather snapshot",
            "decision_key": key,
            "actor_session_id": "test-e2-wiring",
        })
        assert dec_resp is None or dec_resp.status_code == 201, dec_resp.text

        # 4. After approval, validate-methods succeeds
        val_resp_1 = client.post(
            f"/api/v1/environment/e2/weather/snapshots/{snapshot_id}/validate-methods",
            json={"project_id": project_id},
        )
        assert val_resp_1.status_code == 200, val_resp_1.text
        art_id_1 = val_resp_1.json()["method_validation_artifact_id"]
        assert art_id_1.startswith("artifact-e2-method-validation-")

        # Verify the artifact was registered in store
        record = store.current(art_id_1)
        assert record.entity_type == "Artifact"
        assert record.payload["type"] == "method-validation"

        # 5. Second call must be idempotent: returns existing artifact, doesn't re-run validate_methods
        def fail_if_called(*args, **kwargs):
            raise AssertionError("validate_methods should NOT be called on second idempotent invocation!")

        monkeypatch.setattr("urban_design.environment.e2_router.validate_methods", fail_if_called)

        val_resp_2 = client.post(
            f"/api/v1/environment/e2/weather/snapshots/{snapshot_id}/validate-methods",
            json={"project_id": project_id},
        )
        assert val_resp_2.status_code == 200, val_resp_2.text
        art_id_2 = val_resp_2.json()["method_validation_artifact_id"]
        assert art_id_1 == art_id_2


def test_build_plan_request_replaces_three_ids_and_sets_pins():
    assert DRILL_TEMPLATE_PATH.exists(), f"Drill template missing at {DRILL_TEMPLATE_PATH}"
    template = json.loads(DRILL_TEMPLATE_PATH.read_text())["request_without_test_key"]

    new_snapshot_id = "snapshot-e2-weather-test-new-12345"
    new_bundle_sha256 = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    new_validation_id = "artifact-e2-method-validation-new-67890"

    # Case 1: COMPACT selected as baseline
    req_compact = build_plan_request(
        template=template,
        snapshot_id=new_snapshot_id,
        bundle_sha256=new_bundle_sha256,
        method_validation_artifact_id=new_validation_id,
        accepted_scenario_id=COMPACT,
    )
    assert req_compact["weather_snapshot_id"] == new_snapshot_id
    assert req_compact["weather_bundle_sha256"] == new_bundle_sha256
    assert req_compact["method_validation_artifact_id"] == new_validation_id
    assert req_compact["baseline"]["scenario_id"] == COMPACT
    assert req_compact["modified"]["scenario_id"] == MIXED
    assert req_compact["baseline"]["geometry_artifact_id"] == template["baseline"]["geometry_artifact_id"]
    assert req_compact["modified"]["geometry_artifact_id"] == template["modified"]["geometry_artifact_id"]

    # Case 2: MIXED selected as baseline
    req_mixed = build_plan_request(
        template=template,
        snapshot_id=new_snapshot_id,
        bundle_sha256=new_bundle_sha256,
        method_validation_artifact_id=new_validation_id,
        accepted_scenario_id=MIXED,
    )
    assert req_mixed["weather_snapshot_id"] == new_snapshot_id
    assert req_mixed["weather_bundle_sha256"] == new_bundle_sha256
    assert req_mixed["method_validation_artifact_id"] == new_validation_id
    assert req_mixed["baseline"]["scenario_id"] == MIXED
    assert req_mixed["modified"]["scenario_id"] == COMPACT
    assert req_mixed["baseline"]["geometry_artifact_id"] == template["modified"]["geometry_artifact_id"]
    assert req_mixed["modified"]["geometry_artifact_id"] == template["baseline"]["geometry_artifact_id"]
