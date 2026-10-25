"""D1 authority regressions on a mode=ro SQLite backup; no new decisions."""
import hashlib
from dataclasses import replace
import sqlite3
from pathlib import Path

import pytest
from urban_design.editing.formal_authority import _bind_study_area, FormalAuthorityError
from urban_design.store import ProjectStateStore

AUTHORITY = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')
EXPECTED = '2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366'

@pytest.fixture
def authority_copy(tmp_path):
    assert hashlib.sha256(AUTHORITY.read_bytes()).hexdigest() == EXPECTED
    with sqlite3.connect(f'file:{AUTHORITY}?mode=ro', uri=True) as source:
        with sqlite3.connect(tmp_path / 'state.sqlite3') as target:
            source.backup(target)
    store = ProjectStateStore(tmp_path / 'state.sqlite3')
    yield store
    store.close()
    assert hashlib.sha256(AUTHORITY.read_bytes()).hexdigest() == EXPECTED


def test_d1_v8_workspace_geometry_binds_active_study_area(authority_copy):
    store = authority_copy
    ancestor = store.list_current('DesignScenario')[0]
    decisions_before = [r.payload for r in store.list_current('HumanDecision')]
    study = _bind_study_area(store, ancestor)
    assert study.entity_id == ancestor.payload['site_id']
    decision = store.current('decision-5e9f0b174dad4882bf4e5cac0b0b1b19')
    assert decision.payload['target_type'] == 'WorkspaceRevision'
    assert decision.payload['target_version'] == '8'
    assert decision.payload['target_geometry_sha256'] == study.payload['geometry_sha256']
    assert [r.payload for r in store.list_current('HumanDecision')] == decisions_before


@pytest.mark.parametrize('patch', [
    {'status': 'STALE'},
    {'revision': 9},
    {'payload_digest': 'f' * 64},
    {'study_area_id': 'different-study'},
])
def test_d1_workspace_drift_fails_closed(authority_copy, patch, monkeypatch):
    store = authority_copy
    workspace = store.get_record('workspace-rotterdam-m4h-pilot-project', revision=8)
    payload = dict(workspace.payload)
    payload.update(patch)
    corrupted = replace(workspace, payload=payload)
    original_get = store.get_record
    original_history = store.history
    monkeypatch.setattr(store, 'get_record', lambda entity_id, revision=None: corrupted if entity_id == workspace.entity_id and revision == 8 else original_get(entity_id, revision))
    monkeypatch.setattr(store, 'history', lambda entity_id: [corrupted if row.revision == 8 else row for row in original_history(entity_id)] if entity_id == workspace.entity_id else original_history(entity_id))
    with pytest.raises(FormalAuthorityError, match='D1'):
        _bind_study_area(store, store.list_current('DesignScenario')[0])


def test_no_d1_decision_never_passes(authority_copy, tmp_path):
    source = authority_copy
    ancestor = source.list_current('DesignScenario')[0]
    study = source.current(ancestor.payload['site_id'])
    isolated = ProjectStateStore(tmp_path / 'no-decision.sqlite3')
    isolated.create_project({'id': ancestor.project_id, 'name': 'Disposable missing-D1 test'}, project_id=ancestor.project_id)
    isolated.create('StudyArea', study.payload, entity_id=study.entity_id, project_id=study.project_id)
    assert isolated.list_current('HumanDecision') == []
    with pytest.raises(FormalAuthorityError, match='D1 study-area acceptance is missing'):
        _bind_study_area(isolated, ancestor)
    isolated.close()
