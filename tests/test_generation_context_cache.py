"""Tests proving generation context readiness cache hit and cache invalidation on revision changes."""
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
from shapely.geometry import box

from urban_design import generation_context as gc
from urban_design.store import ProjectStateStore


def fixture_inputs():
    record = NS(entity_id='fixture', revision=6, entity_type='Fixture', payload={'status': 'FIXTURE_ONLY'})
    decision = NS(id='mock-bound-reference', target_id='fixture', target_version='6', target_payload_digest='a' * 64)
    return NS(
        workspace_record=record,
        study_area=record,
        constraint_record=record,
        source_snapshots=(),
        source_artifacts=(),
        workspace=NS(revision=6),
        workspace_decision=decision,
        constraint_decision=decision,
        input_hash='b' * 64,
        design_area=box(0, 0, 100, 80),
        water_geometry=None,
        constraint_set=NS(
            allocation_policy='priority',
            constraints=(NS(name='far_upper_limit', scope='whole_site', denominator=None),),
        ),
        zones=(('a', 'housing', box(0, 0, 60, 80)), ('b', 'work', box(40, 0, 100, 80))),
    )


def test_generation_context_cache_and_invalidation(tmp_path, monkeypatch):
    store = ProjectStateStore(tmp_path / 'cache_test.sqlite3')
    inputs = fixture_inputs()

    art_file = tmp_path / 'artifact.json'
    art_file.write_text('{"test": 1}')
    art_record = NS(entity_id='art-1', revision=1, entity_type='Artifact', payload={'uri': str(art_file)})
    inputs.source_artifacts = (art_record,)

    mock_load = MagicMock(side_effect=lambda *a, **kw: inputs)
    monkeypatch.setattr(gc, '_load_approved_inputs', mock_load)
    mock_estimates = MagicMock(return_value=((), [{'floor_count': {'status': 'UNAVAILABLE', 'estimate_range': [1, 4]}}]))
    monkeypatch.setattr(gc, '_floor_estimates', mock_estimates)

    # 1. Initial resolution (cache miss)
    first = gc.resolve_readiness(store, 'p')
    assert first.status == 'READY'
    assert mock_load.call_count == 1
    assert mock_estimates.call_count == 1

    # 2. Second resolution (cache hit) — DOES NOT call _load_approved_inputs
    second = gc.resolve_readiness(store, 'p')
    assert second.status == 'READY'
    assert second.context_hash == first.context_hash
    assert mock_load.call_count == 1
    assert mock_estimates.call_count == 1

    # 3. Any ledger write invalidates the cache
    with store.locked_connection() as conn:
        conn.execute(
            "INSERT INTO ledger_events(event_id, timestamp, actor, action, target_id, project_id, changed_refs_json, resulting_refs_json, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-invalidate-1", "2026-10-03T12:00:00Z", "TEST", "WRITE", "target-1", "p", "[]", "[]", "{}"),
        )

    third = gc.resolve_readiness(store, 'p')
    assert third.status == 'READY'
    assert mock_load.call_count == 2
    assert mock_estimates.call_count == 2

    # 4. Verify warm cache again
    fourth = gc.resolve_readiness(store, 'p')
    assert fourth.status == 'READY'
    assert mock_load.call_count == 2
    assert mock_estimates.call_count == 2

    # 5. Any file stat change (modification/size/mtime) invalidates the cache
    time.sleep(0.02)
    art_file.write_text('{"test": 2, "expanded": true}')

    fifth = gc.resolve_readiness(store, 'p')
    assert fifth.status == 'READY'
    assert mock_load.call_count == 3
    assert mock_estimates.call_count == 3

    store.close()


def test_freeze_bypasses_readiness_cache(monkeypatch):
    calls = []

    def fake_resolve(store, project_id, *, connection=None, use_cache=True):
        calls.append(use_cache)
        return gc.Readiness(status="BLOCKED", blockers=("x",))

    class _Conn:
        in_transaction = False

        def execute(self, *_):
            pass

        def rollback(self):
            pass

    class _Store:
        from contextlib import contextmanager

        @contextmanager
        def locked_connection(self):
            yield _Conn()

    monkeypatch.setattr(gc, "_resolve", fake_resolve)
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        gc.freeze_context(_Store(), "p", gc.FreezeRequest(expected_workspace_revision=1, expected_context_hash="0" * 64))
    assert calls == [False]


def test_workflow_readiness_reuses_cached_readiness(monkeypatch):
    from urban_design.generation.workflow import GenerationWorkflow, ResolvedGeneration

    mock_resolve = MagicMock()
    mock_resolve.return_value = ResolvedGeneration(
        context=NS(),
        inputs=NS(),
        strategies=(),
        revision="6",
        readiness="APPROVED",
    )
    mock_store = MagicMock()
    mock_runner = MagicMock()

    workflow = GenerationWorkflow(mock_store, mock_runner, mock_resolve, full_scheme_only=True)
    receipt = workflow.readiness("p")
    assert receipt.status == "READY_TO_START"
    assert receipt.readiness == "APPROVED"
    assert mock_resolve.call_count == 1

    # Second check reuses resolve without freeze
    receipt2 = workflow.readiness("p")
    assert receipt2.status == "READY_TO_START"
    assert mock_resolve.call_count == 2

