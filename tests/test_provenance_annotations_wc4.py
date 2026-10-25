from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from urban_design.models import ActorKind
from urban_design.provenance_audit import annotate_pd14_events
from urban_design.store import PayloadError, ProjectStateStore


def test_pd14_provenance_annotations_are_strictly_append_only(pd14_pre_annotation_db: Path):
    test_db = pd14_pre_annotation_db

    # Record all existing events exactly
    with sqlite3.connect(test_db) as conn:
        conn.row_factory = sqlite3.Row
        pre_total = conn.execute("SELECT count(*) FROM ledger_events").fetchone()[0]
        pre_events = [
            dict(row)
            for row in conn.execute(
                "SELECT sequence, event_id, timestamp, actor, action, target_id, target_type, "
                "project_id, prior_status, changed_refs_json, reason, resulting_refs_json, "
                "supersedes, parent_event_id, state_revision, payload_json, actor_kind, actor_session_id "
                "FROM ledger_events WHERE sequence <= 187 ORDER BY sequence"
            ).fetchall()
        ]

    assert len(pre_events) == 187

    store = ProjectStateStore(test_db)
    records = annotate_pd14_events(store)
    assert len(records) == 6

    # Verify each annotation
    for i, seq in enumerate(range(182, 188)):
        rec = records[i]
        assert rec.entity_id == f"provenance-annotation-seq-{seq}"
        payload = rec.payload
        assert payload["target_event_id"] == pre_events[seq - 1]["event_id"]
        if seq <= 185:
            assert payload["category"] == "LEGACY_ACTOR_LABEL_UNVERIFIED"
            assert "unverified" in payload["rationale"]
        else:
            assert payload["category"] == "AUTOMATION_GUI_OPERATION_MISATTRIBUTED"
            assert "autonomous agent" in payload["rationale"]

    # Verify second run is idempotent
    second_run = annotate_pd14_events(store)
    assert len(second_run) == 0

    # Verify that events 1 to 187 are strictly unmodified
    with sqlite3.connect(test_db) as conn:
        conn.row_factory = sqlite3.Row
        post_events = [
            dict(row)
            for row in conn.execute(
                "SELECT sequence, event_id, timestamp, actor, action, target_id, target_type, "
                "project_id, prior_status, changed_refs_json, reason, resulting_refs_json, "
                "supersedes, parent_event_id, state_revision, payload_json, actor_kind, actor_session_id "
                "FROM ledger_events WHERE sequence <= 187 ORDER BY sequence"
            ).fetchall()
        ]

    assert post_events == pre_events

    # Verify total ledger event count increased by exactly 6 (one for each annotation)
    with sqlite3.connect(test_db) as conn:
        total = conn.execute("SELECT count(*) FROM ledger_events").fetchone()[0]
        assert total == pre_total + 6

    # Verify append-only protection on annotations and ledger
    with pytest.raises(PayloadError, match="immutable"):
        store.update("provenance-annotation-seq-182", {"rationale": "tampered"})

    store.close()
