"""E1 plan artifact approval on a disposable database. No production passphrase."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from urban_design import decision_key
from datetime import datetime, timezone

from urban_design.environment.plan_service import (
    approve_plan_artifact,
    canonical_plan_bytes,
    open_e1_jobs,
    persist_e1_plan_artifact,
    plan_artifact_id,
    plan_content_sha256,
)
from urban_design.environment.router import _approved_handler, get_default_draft_plan, router
from urban_design.environment.sunlight import RadianceRuntimeStatus
from urban_design.models import ActorKind, DecisionAction, HumanDecision, HumanStatus
from urban_design.store import PayloadError, ProjectStateStore
from test_environment_formal_e1 import _persist_formal_scenario


def _key(tmp_path: Path) -> tuple[str, Path]:
    key_path = tmp_path / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    return secret, key_path


def _store(tmp_path: Path) -> ProjectStateStore:
    store = ProjectStateStore(tmp_path / "plan-approval.sqlite3")
    store.create_project({"id": "project-e1", "name": "E1 plan fixture"}, project_id="project-e1")
    root = tmp_path / "geometry"
    root.mkdir()
    _persist_formal_scenario(store, root, "formal-baseline", building_x=5)
    _persist_formal_scenario(store, root, "formal-proposal", building_x=20)
    return store


def _python_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("urban_design.environment.router")
    monkeypatch.setattr(
        module,
        "verify_radiance_runtime",
        lambda: RadianceRuntimeStatus(
            available=False,
            version=None,
            manifest_version="6.0.2",
            reason="TEST_RUNTIME_UNAVAILABLE",
        ),
    )


def test_wrong_artifact_hash_cannot_be_approved(tmp_path: Path) -> None:
    secret, key_path = _key(tmp_path)
    store = _store(tmp_path)
    record = persist_e1_plan_artifact(store, get_default_draft_plan(), "project-e1")
    decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="project-e1",
        target_id=record.entity_id,
        target_type="Artifact",
        target_version=str(record.revision),
        target_artifact_sha256="sha256:" + "ab" * 32,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-plan-wrong",
        reason="Attempt to bind a different plan hash",
        timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises(PayloadError, match="target_artifact_sha256"):
        store.record_human_decision(decision, decision_key=secret, decision_key_path=key_path)
    store.close()


def test_changed_plan_bytes_need_a_new_artifact_and_lose_the_old_approval(tmp_path: Path) -> None:
    secret, key_path = _key(tmp_path)
    store = _store(tmp_path)
    original = get_default_draft_plan().model_copy(update={
        "baseline_scenario_id": "formal-baseline", "modified_scenario_id": "formal-proposal"})
    saved = persist_e1_plan_artifact(store, original, "project-e1")
    approve_plan_artifact(
        store,
        saved.entity_id,
        decision_key=secret,
        decision_key_path=key_path,
        actor="designer",
        actor_session_id="session-plan-ok",
        reason="Approve this exact E1 plan document",
    )
    original = type(original).model_validate(saved.payload["plan"])
    changed = original.model_copy(update={"notes": original.notes + " revised grid"})
    changed_saved = persist_e1_plan_artifact(store, changed, "project-e1")
    assert changed_saved.entity_id != saved.entity_id
    assert changed_saved.entity_id == plan_artifact_id(plan_content_sha256(changed))
    assert saved.payload["sha256"] == plan_content_sha256(original)
    assert json.loads(canonical_plan_bytes(original))["status"] == "DRAFT_UNAPPROVED"

    app = FastAPI()
    app.state.project_store = store
    app.include_router(router)
    with TestClient(app) as client:
        rejected = client.post(
            "/api/environment/e1/simulate",
            json={
                "project_id": "project-e1",
                "baseline_scenario_id": "formal-baseline",
                "modified_scenario_id": "formal-proposal",
                "plan_artifact_id": changed_saved.entity_id,
            },
        )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "PLAN_NOT_APPROVED"
    assert not (tmp_path / "e1-jobs.sqlite3").exists()
    store.close()


def test_draft_simulate_does_not_open_the_job_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _python_runtime(monkeypatch)
    store = _store(tmp_path)
    app = FastAPI()
    app.state.project_store = store
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/environment/e1/simulate",
            json={
                "project_id": "project-e1",
                "baseline_scenario_id": "formal-baseline",
                "modified_scenario_id": "formal-proposal",
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["plan"]["status"] == "DRAFT_UNAPPROVED"
    assert payload["evidence_card"]["validation_status"] == "unverified"
    assert store.list_current("HumanDecision", project_id="project-e1") == []
    assert not (tmp_path / "e1-jobs.sqlite3").exists()
    store.close()


def test_approved_plan_job_survives_reopen_and_second_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise the installed real Radiance engine; no approved Python fallback.
    secret, key_path = _key(tmp_path)
    database = tmp_path / "plan-approval.sqlite3"
    store = _store(tmp_path)
    plan = get_default_draft_plan().model_copy(update={
        "baseline_scenario_id": "formal-baseline", "modified_scenario_id": "formal-proposal"})
    saved = persist_e1_plan_artifact(store, plan, "project-e1")
    decision = approve_plan_artifact(
        store,
        saved.entity_id,
        decision_key=secret,
        decision_key_path=key_path,
        actor="designer",
        actor_session_id="session-plan-run",
        reason="Approve the stored E1 plan bytes",
    )
    app = FastAPI()
    app.state.project_store = store
    app.include_router(router)
    body = {
        "project_id": "project-e1",
        "baseline_scenario_id": "formal-baseline",
        "modified_scenario_id": "formal-proposal",
        "plan_artifact_id": saved.entity_id,
    }
    with TestClient(app) as client:
        first = client.post("/api/environment/e1/simulate", json=body)
        second = client.post("/api/environment/e1/simulate", json=body)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    payload = first.json()
    assert payload["status"] == "SUCCESS"
    assert payload["engine"] == "ladybug-sunpath+ladybug-radiance"
    assert payload["plan"]["status"] == "APPROVED"
    assert payload["plan"]["founder_decision_id"] == decision.entity_id
    assert payload["evidence_card"]["validation_status"] == "validated"
    assert second.json()["run_id"] == payload["run_id"]
    assert len(store.list_current("ToolExecution", project_id="project-e1")) == 1
    stored_plan = store.get_record(saved.entity_id)
    assert stored_plan.payload["plan"]["status"] == "DRAFT_UNAPPROVED"
    assert stored_plan.payload["sha256"] == saved.payload["sha256"]
    store.close()

    reopened = ProjectStateStore(database)
    _jobs, runner, _output = open_e1_jobs(reopened, None, _approved_handler(reopened))
    job_id = payload["metadata"]["e1_job_id"]
    recovered = runner.recover(job_id)
    assert recovered.status.value == "READY"
    assert runner.verify_published(job_id) is True
    again = runner.run(job_id)
    assert again.status.value == "READY"
    assert again.job_id == job_id
    result_path = tmp_path / "e1-jobs" / "out" / job_id / "e1-result.json"
    reread = json.loads(result_path.read_bytes())
    assert reread["evidence_card"]["validation_status"] == "validated"
    assert reread["plan"]["founder_decision_id"] == decision.entity_id
    reopened.close()
