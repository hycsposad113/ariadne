from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urban_design import decision_key
from urban_design.api import create_workspace_app
from urban_design.geometry import canonical_geometry_hash
from urban_design.models import ActorKind, DecisionAction, HumanDecision, HumanStatus
from urban_design.store import PayloadError, ProjectStateStore
from urban_design.workspace_contracts import (
    ExplorationDesignArea,
    SyncRequest,
    WorkspaceSpatialBrief,
)
from urban_design.workspace_service import WorkspaceService


def _init_test_key(tmp_path: Path) -> tuple[str, Path]:
    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    return secret, key_path


def _setup_workspace(tmp_path: Path):
    store = ProjectStateStore(tmp_path / "workspace_binding.sqlite3")
    store.create(
        "StudyArea",
        {"id": "area-1", "status": "CONFIRMED_FOR_EXPLORATION", "version": "v1", "project_id": "proj-1"},
        entity_id="area-1",
        project_id="proj-1",
    )
    store.create(
        "DatasetSnapshot",
        {"id": "snapshot-1", "status": "CONFIRMED", "project_id": "proj-1"},
        entity_id="snapshot-1",
        project_id="proj-1",
    )
    service = WorkspaceService(store)
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [100.0, 0.0], [100.0, 50.0], [0.0, 50.0], [0.0, 0.0]]],
    }
    eda = ExplorationDesignArea(geometry=polygon)
    brief = WorkspaceSpatialBrief(exploration_design_area=eda)
    request = SyncRequest(
        project_id="proj-1",
        study_area_id="area-1",
        expected_workspace_revision=0,
        source_snapshot_ids=["snapshot-1"],
        idempotency_key="sync-1",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-sync-1",
        spatial_brief=brief,
    )
    rev1 = service.sync(request)
    return store, service, rev1, polygon


def test_human_decision_binds_workspace_revision_payload_digest(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, _service, rev1, _polygon = _setup_workspace(tmp_path)

    assert rev1.payload_digest is not None
    digest = rev1.payload_digest

    decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="proj-1",
        target_id=rev1.workspace_id,
        target_type="WorkspaceRevision",
        target_version=str(rev1.revision),
        target_payload_digest=digest,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-dec-1",
        reason="Approve initial exploration workspace layout",
        timestamp=datetime.now(timezone.utc),
    )

    rec = store.record_human_decision(
        decision,
        decision_key=secret,
        decision_key_path=key_path,
    )
    assert rec.entity_id == decision.id
    assert rec.payload["target_payload_digest"] == f"sha256:{digest}" if not digest.startswith("sha256:") else digest
    store.close()


def test_human_decision_binds_workspace_exploration_design_area_geometry_hash(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, _service, rev1, polygon = _setup_workspace(tmp_path)

    eda_hash = canonical_geometry_hash(polygon)

    decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="proj-1",
        target_id=rev1.workspace_id,
        target_type="WorkspaceRevision",
        target_version=str(rev1.revision),
        target_geometry_sha256=eda_hash,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-dec-2",
        reason="Approve EDA boundary for workspace",
        timestamp=datetime.now(timezone.utc),
    )

    rec = store.record_human_decision(
        decision,
        decision_key=secret,
        decision_key_path=key_path,
    )
    assert rec.entity_id == decision.id
    assert rec.payload["target_geometry_sha256"] == eda_hash
    store.close()


def test_human_decision_binds_both_digest_and_geometry_hash(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, _service, rev1, polygon = _setup_workspace(tmp_path)

    eda_hash = canonical_geometry_hash(polygon)
    digest = rev1.payload_digest

    decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="proj-1",
        target_id=rev1.workspace_id,
        target_type="WorkspaceRevision",
        target_version=str(rev1.revision),
        target_geometry_sha256=eda_hash,
        target_payload_digest=digest,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-dec-3",
        reason="Approve workspace both digest and geometry",
        timestamp=datetime.now(timezone.utc),
    )

    rec = store.record_human_decision(
        decision,
        decision_key=secret,
        decision_key_path=key_path,
    )
    assert rec.entity_id == decision.id
    store.close()


def test_human_decision_rejects_mismatched_payload_digest(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, _service, rev1, _polygon = _setup_workspace(tmp_path)

    wrong_digest = "sha256:" + "0" * 64

    decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="proj-1",
        target_id=rev1.workspace_id,
        target_type="WorkspaceRevision",
        target_version=str(rev1.revision),
        target_payload_digest=wrong_digest,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-dec-wrong",
        reason="Attempt decision with mismatched digest",
        timestamp=datetime.now(timezone.utc),
    )

    with pytest.raises(PayloadError, match="does not match the current target"):
        store.record_human_decision(
            decision,
            decision_key=secret,
            decision_key_path=key_path,
        )
    store.close()


def test_human_decision_rejects_mismatched_geometry_hash(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, _service, rev1, _polygon = _setup_workspace(tmp_path)

    wrong_geom_hash = "sha256:" + "f" * 64

    decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="proj-1",
        target_id=rev1.workspace_id,
        target_type="WorkspaceRevision",
        target_version=str(rev1.revision),
        target_geometry_sha256=wrong_geom_hash,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-dec-wrong-geom",
        reason="Attempt decision with mismatched geometry hash",
        timestamp=datetime.now(timezone.utc),
    )

    with pytest.raises(PayloadError, match="does not match the current target"):
        store.record_human_decision(
            decision,
            decision_key=secret,
            decision_key_path=key_path,
        )
    store.close()


def test_human_decision_rejects_stale_workspace_target(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, service, rev1, polygon = _setup_workspace(tmp_path)

    # Sync a second revision to advance workspace head
    request2 = SyncRequest(
        project_id="proj-1",
        study_area_id="area-1",
        expected_workspace_revision=1,
        source_snapshot_ids=["snapshot-1"],
        idempotency_key="sync-2",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-sync-2",
        spatial_brief=WorkspaceSpatialBrief(
            exploration_design_area=ExplorationDesignArea(
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[0.0, 0.0], [200.0, 0.0], [200.0, 100.0], [0.0, 100.0], [0.0, 0.0]]],
                }
            )
        ),
    )
    rev2 = service.sync(request2)
    assert rev2.revision == 2

    # Attempt to approve rev1 (which has target_version = "1")
    decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="proj-1",
        target_id=rev1.workspace_id,
        target_type="WorkspaceRevision",
        target_version=str(rev1.revision),
        target_payload_digest=rev1.payload_digest,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="session-dec-stale",
        reason="Attempt decision on stale rev1",
        timestamp=datetime.now(timezone.utc),
    )

    with pytest.raises(PayloadError, match="stale"):
        store.record_human_decision(
            decision,
            decision_key=secret,
            decision_key_path=key_path,
        )
    store.close()


def test_api_human_decision_accepts_workspace_revision_binding(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, _service, rev1, polygon = _setup_workspace(tmp_path)
    app = create_workspace_app(store=store, decision_key_path=key_path)
    client = TestClient(app)

    eda_hash = canonical_geometry_hash(polygon)
    response = client.post(
        "/api/v1/projects/proj-1/decisions",
        json={
            "target_id": rev1.workspace_id,
            "target_type": "WorkspaceRevision",
            "target_version": str(rev1.revision),
            "target_geometry_sha256": eda_hash,
            "target_payload_digest": rev1.payload_digest,
            "action": "Approve",
            "status": "approved",
            "reason": "Approve current workspace layout via API",
            "decision_key": secret,
            "actor_session_id": "web-session-123",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["target_id"] == rev1.workspace_id
    assert data["target_geometry_sha256"] == eda_hash
    store.close()


def test_api_human_decision_rejects_stale_target_with_409(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, service, rev1, _polygon = _setup_workspace(tmp_path)
    app = create_workspace_app(store=store, decision_key_path=key_path)
    client = TestClient(app)

    # Advance revision
    service.sync(
        SyncRequest(
            project_id="proj-1",
            study_area_id="area-1",
            expected_workspace_revision=1,
            source_snapshot_ids=["snapshot-1"],
            idempotency_key="sync-advance",
            actor_kind=ActorKind.HUMAN_UI,
            actor_session_id="session-advance",
            spatial_brief=WorkspaceSpatialBrief(),
        )
    )

    response = client.post(
        "/api/v1/projects/proj-1/decisions",
        json={
            "target_id": rev1.workspace_id,
            "target_type": "WorkspaceRevision",
            "target_version": str(rev1.revision),
            "target_payload_digest": rev1.payload_digest,
            "action": "Approve",
            "status": "approved",
            "reason": "Approve stale rev1 via API",
            "decision_key": secret,
            "actor_session_id": "web-session-123",
        },
    )
    assert response.status_code == 409
    assert "stale" in response.json()["detail"].lower()
    store.close()


def test_api_workspace_decision_summary_flow(tmp_path: Path):
    secret, key_path = _init_test_key(tmp_path)
    store, service, rev1, polygon = _setup_workspace(tmp_path)
    app = create_workspace_app(store=store, decision_key_path=key_path)
    client = TestClient(app)

    # 1. Fetch decision summary before decision
    summary_res = client.get(f"/api/v1/workspaces/{rev1.workspace_id}/decision-summary")
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["workspace_id"] == rev1.workspace_id
    assert summary["revision"] == 1
    assert summary["payload_digest"] == rev1.payload_digest
    assert summary["exploration_design_area"]["geometry_hash"] == canonical_geometry_hash(polygon)
    assert summary["exploration_design_area"]["area_m2"] > 0
    assert summary["latest_decision"] is None
    assert summary["is_current_revision"] is False

    # 2. Reject mismatched geometry hash
    bad_hash = "sha256:" + "0" * 64
    reject_res = client.post(
        "/api/v1/projects/proj-1/decisions",
        json={
            "target_id": rev1.workspace_id,
            "target_type": "WorkspaceRevision",
            "target_version": str(rev1.revision),
            "target_geometry_sha256": bad_hash,
            "target_payload_digest": rev1.payload_digest,
            "action": "Approve",
            "status": "approved",
            "reason": "Mismatched hash attempt",
            "decision_key": secret,
            "actor_session_id": "web-session-123",
        },
    )
    assert reject_res.status_code == 409

    # 3. Approve with correct binding
    eda_hash = canonical_geometry_hash(polygon)
    approve_res = client.post(
        "/api/v1/projects/proj-1/decisions",
        json={
            "target_id": rev1.workspace_id,
            "target_type": "WorkspaceRevision",
            "target_version": str(rev1.revision),
            "target_geometry_sha256": eda_hash,
            "target_payload_digest": rev1.payload_digest,
            "action": "Approve",
            "status": "approved",
            "reason": "Approve Day 1 workspace",
            "decision_key": secret,
            "actor_session_id": "web-session-123",
        },
    )
    assert approve_res.status_code == 201
    dec_id = approve_res.json()["id"]

    # 4. Summary now reports active current decision
    summary_res2 = client.get(f"/api/v1/workspaces/{rev1.workspace_id}/decision-summary")
    assert summary_res2.status_code == 200
    summary2 = summary_res2.json()
    assert summary2["latest_decision"]["id"] == dec_id
    assert summary2["is_current_revision"] is True
    assert summary2["is_stale_for_decision"] is False
    assert summary2["decision_status_label"] == "approved"

    # 5. List decisions endpoint
    list_res = client.get("/api/v1/projects/proj-1/decisions")
    assert list_res.status_code == 200
    decisions = list_res.json()
    assert len(decisions) >= 1
    assert any(d["id"] == dec_id for d in decisions)

    # 6. Advance workspace revision -> summary marks prior decision as stale (corresponds to prior version)
    service.sync(
        SyncRequest(
            project_id="proj-1",
            study_area_id="area-1",
            expected_workspace_revision=1,
            source_snapshot_ids=["snapshot-1"],
            idempotency_key="sync-rev2",
            actor_kind=ActorKind.HUMAN_UI,
            actor_session_id="session-rev2",
            spatial_brief=WorkspaceSpatialBrief(),
        )
    )

    summary_res3 = client.get(f"/api/v1/workspaces/{rev1.workspace_id}/decision-summary")
    assert summary_res3.status_code == 200
    summary3 = summary_res3.json()
    assert summary3["revision"] == 2
    assert summary3["latest_decision"]["id"] == dec_id
    assert summary3["is_current_revision"] is False
    assert summary3["is_stale_for_decision"] is True
    assert summary3["decision_status_label"] == "SUPERSEDED_PRIOR_REVISION"

    store.close()

