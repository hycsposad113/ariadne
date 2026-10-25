from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from urban_design.models import ActorKind
from urban_design.store import ProjectStateStore


@pytest.fixture
def pd14_pre_annotation_db(tmp_path: Path) -> Path:
    """Build an isolated synthetic ledger with six unannotated PD-14 targets."""
    database = tmp_path / "pd14-pre-annotation.sqlite3"
    with ProjectStateStore(database) as store:
        for sequence in range(1, 188):
            store.append_ledger_event(
                target_id=f"pd14-fixture-target-{sequence}",
                actor="test-harness",
                action="FixtureSeed",
                project_id="pd14-fixture-project",
                target_type="FixtureTarget",
                reason="Synthetic pre-annotation PD-14 test fixture",
                payload={"fixture_sequence": sequence},
                event_id=f"pd14-fixture-event-{sequence}",
                timestamp=f"2026-09-25T00:{(sequence - 1) % 60:02d}:00+00:00",
                actor_kind=ActorKind.TEST_HARNESS,
                actor_session_id="pd14-preannotation-fixture",
            )

    # The writer verifies the exact source-file hash across sqlite3 .backup.
    # Leave this test-built database checkpointed outside WAL mode for that check.
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        journal_mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        assert journal_mode.lower() == "delete"
        count, minimum, maximum = connection.execute(
            "SELECT COUNT(*), MIN(sequence), MAX(sequence) FROM ledger_events"
        ).fetchone()
        assert (count, minimum, maximum) == (187, 1, 187)
        assert connection.execute(
            "SELECT COUNT(*) FROM ledger_events WHERE sequence BETWEEN 182 AND 187"
        ).fetchone()[0] == 6
        assert connection.execute(
            "SELECT COUNT(*) FROM state_versions WHERE entity_type='ProvenanceAnnotation'"
        ).fetchone()[0] == 0

    return database
