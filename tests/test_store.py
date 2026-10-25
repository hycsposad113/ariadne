"""Acceptance tests for the backend-owned state and Design Ledger store."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from urban_design.models import ActorKind, Project

from src.urban_design.store import (
    ProjectStateStore,
    RevisionConflictError,
)


def test_read_only_legacy_database_does_not_migrate_or_change_bytes(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE state_heads (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            project_id TEXT,
            current_revision INTEGER NOT NULL
        );
        CREATE TABLE state_versions (
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            revision INTEGER NOT NULL,
            project_id TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            parent_revision INTEGER,
            supersedes TEXT,
            event_id TEXT NOT NULL,
            PRIMARY KEY (entity_id, revision)
        );
        CREATE TABLE ledger_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target_id TEXT NOT NULL,
            target_type TEXT,
            project_id TEXT,
            prior_status TEXT,
            changed_refs_json TEXT NOT NULL,
            reason TEXT,
            resulting_refs_json TEXT NOT NULL,
            supersedes TEXT,
            parent_event_id TEXT,
            state_revision INTEGER,
            payload_json TEXT NOT NULL
        );
        INSERT INTO state_heads VALUES ('project-legacy', 'Project', 'project-legacy', 1);
        INSERT INTO state_versions VALUES (
            'project-legacy', 'Project', 1, 'project-legacy', '{"name":"legacy"}',
            '2026-01-01T00:00:00+00:00', NULL, NULL, 'event-legacy'
        );
        INSERT INTO ledger_events (
            event_id, timestamp, actor, action, target_id, target_type, project_id,
            prior_status, changed_refs_json, reason, resulting_refs_json, supersedes,
            parent_event_id, state_revision, payload_json
        ) VALUES (
            'event-legacy', '2026-01-01T00:00:00+00:00', 'legacy-import', 'Create',
            'project-legacy', 'Project', 'project-legacy', NULL, '[]', NULL,
            '["project-legacy"]', NULL, NULL, 1, '{}'
        );
        """
    )
    connection.commit()
    connection.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    with ProjectStateStore(database, read_only=True) as store:
        assert store.current("project-legacy").payload == {"name": "legacy"}
        events = store.events("project-legacy")
        assert len(events) == 1
        assert events[0].actor_kind is None
        assert events[0].actor_session_id is None
        assert "actor_kind" not in {
            row[1] for row in store.connection.execute("PRAGMA table_info(ledger_events)")
        }

    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_create_current_update_and_reopen(tmp_path):
    database = tmp_path / "project.sqlite3"

    store = ProjectStateStore(database)
    first = store.create_project(
        {"name": "Delft pilot", "status": "PROPOSED"},
        project_id="project-1",
        actor="designer",
    )
    assert first.revision == 1
    assert store.current("project-1").payload["status"] == "PROPOSED"

    second = store.update(
        "project-1",
        {"status": "APPROVED"},
        expected_revision=1,
        actor="designer",
        reason="site approved",
    )
    assert second.revision == 2
    assert second.parent_revision == 1
    assert store.current("project-1").payload == {
        "name": "Delft pilot",
        "status": "APPROVED",
    }
    store.close()

    reopened = ProjectStateStore(database)
    assert reopened.current("project-1").revision == 2
    assert reopened.current("project-1").payload["status"] == "APPROVED"
    assert [event.action for event in reopened.ledger("project-1")] == [
        "Create",
        "Update",
    ]


def test_update_is_atomic_when_ledger_append_fails(tmp_path, monkeypatch):
    store = ProjectStateStore(tmp_path / "atomic.sqlite3")
    store.create_project({"status": "PROPOSED"}, project_id="project-1")

    def fail_append(*_args, **_kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(store, "_append_ledger_event", fail_append)
    with pytest.raises(RuntimeError, match="ledger unavailable"):
        store.update("project-1", {"status": "APPROVED"})

    current = store.current("project-1")
    assert current.revision == 1
    assert current.payload["status"] == "PROPOSED"
    assert len(store.ledger("project-1")) == 1

    # The connection remains usable after rollback, so a later valid update
    # can commit both its state revision and event.
    monkeypatch.undo()
    store.update("project-1", {"status": "APPROVED"})
    assert store.current("project-1").revision == 2
    assert len(store.ledger("project-1")) == 2


def test_failed_updater_rolls_back_and_revision_precondition_is_enforced(tmp_path):
    store = ProjectStateStore(tmp_path / "rollback.sqlite3")
    store.create_project({"status": "PROPOSED"}, project_id="project-1")

    def failed_updater(_current):
        raise ValueError("invalid design state")

    with pytest.raises(ValueError, match="invalid design state"):
        store.update("project-1", failed_updater)
    assert store.current("project-1").revision == 1
    assert len(store.ledger("project-1")) == 1

    with pytest.raises(RevisionConflictError):
        store.update("project-1", {"status": "APPROVED"}, expected_revision=99)
    assert store.current("project-1").revision == 1
    assert len(store.ledger("project-1")) == 1


def test_ledger_and_state_history_are_append_only(tmp_path):
    database = tmp_path / "append-only.sqlite3"
    store = ProjectStateStore(database)
    store.create_project({"status": "PROPOSED"}, project_id="project-1")
    store.update("project-1", {"status": "APPROVED"})

    history = store.history("project-1")
    assert [record.revision for record in history] == [1, 2]
    assert history[0].payload["status"] == "PROPOSED"

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute(
            "UPDATE state_versions SET payload_json = ? WHERE entity_id = ? AND revision = 1",
            ('{"status":"ERASED"}', "project-1"),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute(
            "DELETE FROM ledger_events WHERE target_id = ?", ("project-1",)
        )

    assert store.replay("project-1", revision=1).payload["status"] == "PROPOSED"
    assert store.replay("project-1").payload["status"] == "APPROVED"


def test_legacy_override_helper_cannot_create_an_unauthenticated_decision(tmp_path):
    from src.urban_design.store import PayloadError

    store = ProjectStateStore(tmp_path / "override.sqlite3")
    store.create_project({"status": "PROPOSED"}, project_id="project-1")
    recommendation = store.create(
        "Claim",
        {
            "status": "validated",
            "recommendation": "retain perimeter block",
            "project_id": "project-1",
        },
        entity_id="claim-1",
        project_id="project-1",
        actor="scenario-critic",
    )

    with pytest.raises(PayloadError, match="authenticated decision endpoint"):
        store.record_override(
            recommendation.entity_id,
            {
                "status": "overridden",
                "decision": "retain linear block",
            },
            decision_id="decision-1",
            actor="designer",
            actor_kind=ActorKind.TEST_HARNESS,
            actor_session_id="override-test-session",
            reason="public-space access is the governing project priority",
        )
    assert store.current("claim-1").payload["recommendation"] == "retain perimeter block"
    assert store.connection.execute("SELECT COUNT(*) FROM state_heads WHERE entity_type='HumanDecision'").fetchone()[0] == 0


def test_replay_project_reconstructs_each_entity_at_a_ledger_point(tmp_path):
    store = ProjectStateStore(tmp_path / "replay.sqlite3")
    store.create_project({"status": "PROPOSED"}, project_id="project-1")
    scenario = store.create(
        "DesignScenario",
        {"status": "generated", "project_id": "project-1"},
        entity_id="scenario-1",
        project_id="project-1",
    )
    first_cutoff = store.ledger("project-1")[1].sequence
    store.update(scenario.entity_id, {"status": "accepted"})

    historical = store.replay_project("project-1", at_sequence=first_cutoff)
    assert historical["scenario-1"].payload["status"] == "generated"
    assert store.replay_project("project-1")["scenario-1"].payload["status"] == "accepted"


def test_required_typed_entity_names_are_persistable(tmp_path):
    store = ProjectStateStore(tmp_path / "typed-entities.sqlite3")
    store.create_project({"name": "fixture"}, project_id="project-1")
    for entity_type in ("DatasetSnapshot", "ConstraintSet", "ToolExecution", "ParameterDefinition"):
        record = store.create(
            entity_type,
            {"project_id": "project-1", "status": "proposed"},
            entity_id=f"{entity_type.lower()}-1",
            project_id="project-1",
        )
        assert record.entity_type == entity_type


def test_create_typed_persists_a_validated_domain_record(tmp_path):
    store = ProjectStateStore(tmp_path / "typed-record.sqlite3")
    typed = Project(id="project-typed", name="Typed fixture")
    record = store.create_typed(typed, actor="validator")
    assert record.entity_type == "Project"
    assert record.payload["name"] == "Typed fixture"
