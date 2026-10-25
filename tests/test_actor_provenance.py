from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _workspace_client(tmp_path: Path):
    from urban_design.api import create_workspace_app
    from urban_design.store import ProjectStateStore

    store = ProjectStateStore(tmp_path / "workspace.sqlite3")
    store.create(
        "StudyArea",
        {"id": "area-v1", "status": "CONFIRMED_FOR_EXPLORATION", "version": "v1", "project_id": "project-a"},
        entity_id="area-v1",
        project_id="project-a",
    )
    store.create("DatasetSnapshot", {"id": "snapshot-a", "status": "CONFIRMED"}, entity_id="snapshot-a", project_id="project-a")
    app = create_workspace_app(store=store)
    return TestClient(app), store


def _decision_client(tmp_path: Path, key_path: Path):
    from urban_design.api import create_workspace_app
    from urban_design.store import ProjectStateStore

    store = ProjectStateStore(tmp_path / "decision.sqlite3")
    store.create(
        "StudyArea",
        {
            "id": "area-v1",
            "status": "CONFIRMED_FOR_EXPLORATION",
            "version": "v1",
            "geometry_sha256": "sha256:" + "a" * 64,
            "artifact_sha256": "sha256:" + "b" * 64,
            "project_id": "project-a",
        },
        entity_id="area-v1",
        project_id="project-a",
    )
    app = create_workspace_app(store=store, decision_key_path=key_path)
    return TestClient(app), store


def _human_decision_count(store) -> int:
    return store.connection.execute(
        "SELECT COUNT(*) FROM state_heads WHERE entity_type='HumanDecision'"
    ).fetchone()[0]


def _sync_payload(**overrides):
    payload = {
        "project_id": "project-a",
        "study_area_id": "area-v1",
        "expected_workspace_revision": 0,
        "source_snapshot_ids": ["snapshot-a"],
        "idempotency_key": "key-" + uuid.uuid4().hex,
        "actor_kind": "TEST_HARNESS",
        "actor_session_id": "test-session-1",
    }
    payload.update(overrides)
    return payload


def _decision_payload(secret: str, **overrides):
    payload = {
        "target_id": "area-v1",
        "target_type": "StudyArea",
        "target_version": "v1",
        "target_geometry_sha256": "sha256:" + "a" * 64,
        "action": "Inspect",
        "status": "inspected",
        "reason": "Review the current exploration record",
        "decision_key": secret,
        "actor_session_id": "human-session-1",
    }
    payload.update(overrides)
    return payload


def test_workspace_sync_requires_actor_kind_and_writes_typed_provenance(tmp_path):
    client, store = _workspace_client(tmp_path)
    before = len(store.events())

    missing = _sync_payload()
    missing.pop("actor_kind")
    response = client.post("/api/v1/workspaces/sync", json=missing)

    assert response.status_code == 422
    assert len(store.events()) == before

    response = client.post("/api/v1/workspaces/sync", json=_sync_payload())
    assert response.status_code == 201, response.text
    event = store.events()[-1]
    assert event.actor_kind.value == "TEST_HARNESS"
    assert event.actor_session_id == "test-session-1"


def test_test_harness_decision_must_match_actor_session_with_ledger(tmp_path):
    from urban_design.store import PayloadError, ProjectStateStore

    store = ProjectStateStore(tmp_path / "session-binding.sqlite3")
    with pytest.raises(PayloadError, match="HumanDecision must be written|HUMAN_UI|verified designer decision key"):
        store.create(
            "HumanDecision",
            {
                "id": "decision-test",
                "project_id": "project-a",
                "target_id": "area-v1",
                "target_type": "StudyArea",
                "target_version": "v1",
                "target_geometry_sha256": "sha256:" + "a" * 64,
                "action": "Inspect",
                "status": "inspected",
                "actor": "designer",
                "actor_kind": "TEST_HARNESS",
                "actor_session_id": "ledger-session",
                "reason": "test",
                "timestamp": "2026-09-25T00:00:00+00:00",
            },
            entity_id="decision-a",
            project_id="project-a",
            actor_kind="TEST_HARNESS",
            actor_session_id="ledger-session",
        )
    assert _human_decision_count(store) == 0


def test_batch_path_cannot_use_test_harness_to_create_human_decision(tmp_path):
    from urban_design.store import PayloadError, ProjectStateStore

    store = ProjectStateStore(tmp_path / "batch-test-harness.sqlite3")
    store.create(
        "StudyArea",
        {
            "id": "area-v1",
            "status": "CONFIRMED_FOR_EXPLORATION",
            "version": "v1",
            "geometry_sha256": "sha256:" + "a" * 64,
            "project_id": "project-a",
        },
        entity_id="area-v1",
        project_id="project-a",
    )
    decision = {
        "id": "decision-batch",
        "project_id": "project-a",
        "target_id": "area-v1",
        "target_type": "StudyArea",
        "target_version": "v1",
        "target_geometry_sha256": "sha256:" + "a" * 64,
        "action": "Inspect",
        "status": "inspected",
        "actor": "designer",
        "actor_kind": "TEST_HARNESS",
        "actor_session_id": "test-session",
        "reason": "test",
        "timestamp": "2026-09-25T00:00:00+00:00",
        "decision_event_id": "approval-event-batch",
    }

    with pytest.raises(PayloadError, match="HUMAN_UI|verified designer decision key"):
        store.commit_batch(
            entities=[
                {
                    "entity_id": "decision-batch",
                    "entity_type": "HumanDecision",
                    "project_id": "project-a",
                    "payload": decision,
                    "event_id": "create-event-batch",
                    "actor": "designer",
                    "actor_kind": "TEST_HARNESS",
                    "actor_session_id": "test-session",
                }
            ],
            events=[],
        )
    assert _human_decision_count(store) == 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("target_id", "missing-area", "target was not found"),
        ("target_type", "Claim", "target_type does not match"),
        ("target_version", "v0", "target version is stale"),
        ("target_geometry_sha256", "sha256:" + "c" * 64, "target_geometry_sha256 does not match"),
    ],
)
def test_authenticated_batch_path_rejects_stale_or_unbound_target(tmp_path, field, value, message):
    from urban_design import decision_key
    from urban_design.store import PayloadError, ProjectStateStore

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    store = ProjectStateStore(tmp_path / "batch-target.sqlite3")
    store.create(
        "StudyArea",
        {
            "id": "area-v1",
            "status": "CONFIRMED_FOR_EXPLORATION",
            "version": "v1",
            "geometry_sha256": "sha256:" + "a" * 64,
            "artifact_sha256": "sha256:" + "b" * 64,
            "project_id": "project-a",
        },
        entity_id="area-v1",
        project_id="project-a",
    )
    decision = {
        "id": "decision-batch",
        "project_id": "project-a",
        "target_id": "area-v1",
        "target_type": "StudyArea",
        "target_version": "v1",
        "target_geometry_sha256": "sha256:" + "a" * 64,
        "action": "Inspect",
        "status": "inspected",
        "actor": "designer",
        "actor_kind": "HUMAN_UI",
        "actor_session_id": "human-session",
        "reason": "test stale target rejection",
        "timestamp": "2026-09-25T00:00:00+00:00",
        "decision_event_id": "approval-event-batch",
    }
    decision[field] = value

    with pytest.raises(PayloadError, match=message):
        store.commit_batch(
            entities=[
                {
                    "entity_id": "decision-batch",
                    "entity_type": "HumanDecision",
                    "project_id": "project-a",
                    "payload": decision,
                    "event_id": "create-event-batch",
                    "actor": "designer",
                    "actor_kind": "HUMAN_UI",
                    "actor_session_id": "human-session",
                }
            ],
            events=[],
            decision_key=secret,
            decision_key_path=key_path,
        )
    assert _human_decision_count(store) == 0


def test_parameter_target_hash_must_appear_in_declared_evidence_refs_not_nested_history(tmp_path):
    from urban_design import decision_key
    from urban_design.models import HumanDecision
    from urban_design.store import PayloadError, ProjectStateStore

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    store = ProjectStateStore(tmp_path / "nested-hash.sqlite3")
    expected_hash = "sha256:" + "a" * 64
    store.create(
        "ParameterDefinition",
        {
            "id": "parameter-v1",
            "project_id": "project-a",
            "version": "v1",
            "evidence_refs": ["study-area-v1"],
            "audit_history": {"prior_geometry_sha256": expected_hash},
        },
        entity_id="parameter-v1",
        project_id="project-a",
    )
    decision = {
        "id": "decision-parameter",
        "project_id": "project-a",
        "target_id": "parameter-v1",
        "target_type": "ParameterDefinition",
        "target_version": "v1",
        "target_geometry_sha256": expected_hash,
        "action": "Approve",
        "status": "approved",
        "actor": "designer",
        "actor_kind": "HUMAN_UI",
        "actor_session_id": "human-session",
        "reason": "reject nested historical hash binding",
        "timestamp": "2026-09-25T00:00:00+00:00",
        "decision_event_id": "approval-event-parameter",
    }

    with pytest.raises(PayloadError, match="target_geometry_sha256 does not match"):
        store.record_human_decision(
            HumanDecision.model_validate(decision),
            decision_key=secret,
            decision_key_path=key_path,
        )
    assert _human_decision_count(store) == 0


def test_decision_attempt_limiter_reserves_concurrent_verification_slots_atomically():
    from urban_design.api import DecisionAttemptLimiter

    limiter = DecisionAttemptLimiter()
    barrier = Barrier(16)

    def reserve() -> bool:
        barrier.wait()
        return limiter.begin_attempt("client-a")

    with ThreadPoolExecutor(max_workers=16) as pool:
        reserved = list(pool.map(lambda _index: reserve(), range(16)))

    assert sum(reserved) == limiter.MAX_FAILURES
    for _ in range(sum(reserved)):
        limiter.finish_attempt("client-a", failed=True)
    assert limiter.is_limited("client-a")
    assert not limiter.begin_attempt("client-a")


def test_successful_decision_key_attempt_clears_prior_failures():
    from urban_design.api import DecisionAttemptLimiter

    limiter = DecisionAttemptLimiter()
    for _ in range(limiter.MAX_FAILURES - 1):
        assert limiter.begin_attempt("client-a")
        limiter.finish_attempt("client-a", failed=True)
    assert limiter.begin_attempt("client-a")
    limiter.finish_attempt("client-a", failed=False)
    assert not limiter.is_limited("client-a")
    assert limiter.begin_attempt("client-a")
    limiter.finish_attempt("client-a", failed=False)


def test_authenticated_batch_rolls_back_when_approval_event_does_not_match(tmp_path):
    from urban_design import decision_key
    from urban_design.store import PayloadError, ProjectStateStore

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    store = ProjectStateStore(tmp_path / "batch-event.sqlite3")
    store.create(
        "StudyArea",
        {
            "id": "area-v1",
            "status": "CONFIRMED_FOR_EXPLORATION",
            "version": "v1",
            "geometry_sha256": "sha256:" + "a" * 64,
            "project_id": "project-a",
        },
        entity_id="area-v1",
        project_id="project-a",
    )
    before_events = len(store.events())
    decision = {
        "id": "decision-batch",
        "project_id": "project-a",
        "target_id": "area-v1",
        "target_type": "StudyArea",
        "target_version": "v1",
        "target_geometry_sha256": "sha256:" + "a" * 64,
        "action": "Inspect",
        "status": "inspected",
        "actor": "designer",
        "actor_kind": "HUMAN_UI",
        "actor_session_id": "human-session",
        "reason": "test event binding",
        "timestamp": "2026-09-25T00:00:00+00:00",
        "decision_event_id": "approval-event-batch",
    }

    with pytest.raises(PayloadError, match="approval event does not match"):
        store.commit_batch(
            entities=[
                {
                    "entity_id": "decision-batch",
                    "entity_type": "HumanDecision",
                    "project_id": "project-a",
                    "payload": decision,
                    "event_id": "create-event-batch",
                    "actor": "designer",
                    "actor_kind": "HUMAN_UI",
                    "actor_session_id": "human-session",
                    "reason": "test event binding",
                }
            ],
            events=[
                {
                    "event_id": "approval-event-batch",
                    "timestamp": decision["timestamp"],
                    "actor": "designer",
                    "actor_kind": "HUMAN_UI",
                    "actor_session_id": "wrong-session",
                    "action": "Inspect",
                    "target_id": "decision-batch",
                    "target_type": "HumanDecision",
                    "project_id": "project-a",
                    "reason": "test event binding",
                    "payload": {"target_geometry_sha256": "sha256:" + "a" * 64},
                }
            ],
            decision_key=secret,
            decision_key_path=key_path,
        )
    assert _human_decision_count(store) == 0
    assert len(store.events()) == before_events


def test_human_decision_is_blocked_until_designer_initializes_key(tmp_path):
    key_path = tmp_path / "config" / "decision-key"
    client, store = _decision_client(tmp_path, key_path)
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    before_events = len(store.events())
    before_decisions = _human_decision_count(store)

    response = client.post("/api/v1/projects/project-a/decisions", json=_decision_payload(secret))

    assert response.status_code == 423
    assert response.json()["status"] == "BLOCKED"
    assert len(store.events()) == before_events
    assert _human_decision_count(store) == before_decisions


def test_decision_endpoint_verifies_key_binds_current_target_and_does_not_persist_secret(tmp_path):
    from urban_design import decision_key

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    client, store = _decision_client(tmp_path, key_path)

    wrong = client.post(
        "/api/v1/projects/project-a/decisions",
        json=_decision_payload(secret + "wrong"),
    )
    assert wrong.status_code == 403
    assert secret not in wrong.text

    stale = client.post(
        "/api/v1/projects/project-a/decisions",
        json=_decision_payload(secret, target_version="v0"),
    )
    assert stale.status_code == 409
    malformed_hash = client.post(
        "/api/v1/projects/project-a/decisions",
        json=_decision_payload(secret, target_geometry_sha256="not-a-sha256"),
    )
    assert malformed_hash.status_code == 422
    assert secret not in malformed_hash.text
    assert _human_decision_count(store) == 0

    response = client.post("/api/v1/projects/project-a/decisions", json=_decision_payload(secret))
    assert response.status_code == 201, response.text
    decision = response.json()
    assert decision["target_id"] == "area-v1"
    assert decision["target_version"] == "v1"
    assert decision["target_geometry_sha256"] == "sha256:" + "a" * 64
    assert decision["actor_kind"] == "HUMAN_UI"
    assert decision["actor_session_id"] == "human-session-1"

    ledger_event = store.events()[-1]
    assert ledger_event.actor_kind.value == "HUMAN_UI"
    assert ledger_event.actor_session_id == "human-session-1"
    encoded_state = json.dumps([item.to_dict() for item in store.events()]).encode()
    assert secret.encode() not in encoded_state
    assert key_path.read_bytes() not in encoded_state
    assert store.current("area-v1").payload["status"] == "CONFIRMED_FOR_EXPLORATION"


def test_human_decision_rejects_superseded_target_even_when_version_and_hash_match(tmp_path):
    from urban_design import decision_key

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    client, store = _decision_client(tmp_path, key_path)
    store.update(
        "area-v1",
        {"status": "SUPERSEDED"},
        actor="fixture-transition",
        actor_kind="AGENT_AUTOMATION",
        actor_session_id="fixture-session",
        reason="Mark the old target as superseded for the rejection test",
    )

    response = client.post("/api/v1/projects/project-a/decisions", json=_decision_payload(secret))

    assert response.status_code == 409
    assert "stale or superseded" in response.text
    assert _human_decision_count(store) == 0


def test_wrong_decision_keys_are_throttled(tmp_path):
    from urban_design import decision_key

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    client, store = _decision_client(tmp_path, key_path)

    for _ in range(5):
        response = client.post(
            "/api/v1/projects/project-a/decisions",
            json=_decision_payload(secret + "wrong"),
        )
        assert response.status_code == 403
    limited = client.post(
        "/api/v1/projects/project-a/decisions",
        json=_decision_payload(secret),
    )
    assert limited.status_code == 429
    assert _human_decision_count(store) == 0


def _row_digest(connection: sqlite3.Connection, event_id: str) -> str:
    row = connection.execute(
        """SELECT sequence, event_id, timestamp, actor, action, target_id, target_type,
                  project_id, prior_status, changed_refs_json, reason, resulting_refs_json,
                  supersedes, parent_event_id, state_revision, payload_json
           FROM ledger_events WHERE event_id=?""",
        (event_id,),
    ).fetchone()
    assert row is not None
    return hashlib.sha256(json.dumps(tuple(row), separators=(",", ":")).encode()).hexdigest()


def test_legacy_ledger_rows_upgrade_as_unclassified_without_rewriting(tmp_path):
    from urban_design.store import ProjectStateStore

    path = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(path)
    con.execute(
        """CREATE TABLE ledger_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
            timestamp TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
            target_id TEXT NOT NULL, target_type TEXT, project_id TEXT, prior_status TEXT,
            changed_refs_json TEXT NOT NULL, reason TEXT, resulting_refs_json TEXT NOT NULL,
            supersedes TEXT, parent_event_id TEXT, state_revision INTEGER, payload_json TEXT NOT NULL
        )"""
    )
    con.execute(
        "INSERT INTO ledger_events(event_id,timestamp,actor,action,target_id,changed_refs_json,resulting_refs_json,payload_json) VALUES(?,?,?,?,?,?,?,?)",
        ("legacy-event", "2026-01-01T00:00:00+00:00", "designer", "Update", "workspace-a", "[]", "[]", "{}"),
    )
    con.commit()
    before = _row_digest(con, "legacy-event")
    con.close()

    store = ProjectStateStore(path)
    event = store.events()[0]
    assert event.actor == "designer"
    assert event.actor_kind is None
    assert event.actor_session_id is None
    assert _row_digest(store.connection, "legacy-event") == before
    assert {row[1] for row in store.connection.execute("PRAGMA table_info(ledger_events)")} >= {
        "actor_kind",
        "actor_session_id",
    }
    store.close()


def test_provenance_annotation_requires_same_project_event_and_is_append_only(tmp_path):
    from urban_design.models import ActorKind, ProvenanceAnnotation
    from urban_design.store import PayloadError, ProjectStateStore

    store = ProjectStateStore(tmp_path / "annotations.sqlite3")
    target = store.create(
        "StudyArea",
        {"id": "area-a", "status": "CONFIRMED_FOR_EXPLORATION", "project_id": "project-a"},
        entity_id="area-a",
        project_id="project-a",
        actor="fixture",
        actor_kind=ActorKind.TEST_HARNESS,
        actor_session_id="annotation-test-session",
    )
    annotation = ProvenanceAnnotation(
        id="annotation-a",
        project_id="project-a",
        target_event_id=target.event_id,
        category="LEGACY_ACTOR_LABEL_UNVERIFIED",
        source_actor_label="designer",
        rationale="The historical label is an unverified default, not authenticated identity.",
        related_revision_refs=["workspace-revision-1"],
    )
    record = store.create_typed(
        annotation,
        actor="annotation-auditor",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        actor_session_id="annotation-audit-session",
    )
    assert record.entity_type == "ProvenanceAnnotation"
    with pytest.raises(PayloadError, match="records are immutable"):
        store.update(record.entity_id, {"rationale": "rewritten"})

    mismatched_project = annotation.model_copy(update={"id": "annotation-b", "project_id": "project-b"})
    with pytest.raises(PayloadError, match="project does not match"):
        store.create_typed(
            mismatched_project,
            actor="annotation-auditor",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="annotation-audit-session",
        )
