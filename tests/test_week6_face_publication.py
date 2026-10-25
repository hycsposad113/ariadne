"""Geometry publication must advance atomically; only disposable fixtures."""
import hashlib
import json
from pathlib import Path

import pytest

from test_formal_face_editing_api import _draft, _state, _edit

def test_floor_edit_changes_scenario_geometry_digest(tmp_path):
    store,client,draft=_draft(tmp_path)
    before=store.current(draft); state=_state(client,draft)
    result=_edit(client,draft,state,operation='SETBACK',face_id=None,points=[],steps=1,idempotency_key='digest-regression')
    assert result.status_code==200,result.text
    after=store.current(draft)
    assert after.payload['geometry_sha256'] != before.payload['geometry_sha256']
    assert after.payload['geometry_artifact_id'] != before.payload['geometry_artifact_id']
    artifact = store.current(after.payload['geometry_artifact_id'])
    raw = Path(artifact.payload['uri']).read_bytes()
    assert artifact.payload['parent_artifact_ids'] == [before.payload['geometry_artifact_id']]
    assert artifact.payload['size_bytes'] == len(raw)
    assert artifact.payload['sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest()
    assert after.payload['geometry_sha256'] == artifact.payload['sha256']
    from shapely.geometry import shape
    floors = [feature for feature in json.loads(raw)['features']
              if feature.get('properties', {}).get('building_id') == 'b-rect']
    assert len(floors) == 4
    assert sum(shape(feature['geometry']).area for feature in floors) == 3728.0
    store.close()

@pytest.mark.parametrize("failure_kind", ["ToolExecution", "DesignScenario"])
def test_failed_batch_leaves_all_authority_unchanged(tmp_path,monkeypatch,failure_kind):
    store,client,draft=_draft(tmp_path);state=_state(client,draft)
    before=store.current(draft)
    counts={kind:len(store.list_current(kind)) for kind in ('Artifact','ToolExecution')}
    events=[e.event_id for e in store.events()]
    original=store._insert_state
    def reject_tool(*args,**kwargs):
        if kwargs.get('entity_type')==failure_kind:
            raise RuntimeError('injected publication insertion failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(store,'_insert_state',reject_tool)
    result=_edit(client,draft,state,operation='SETBACK',face_id=None,points=[],steps=1,idempotency_key='atomic-regression')
    assert result.status_code==409,result.text
    after=store.current(draft)
    assert after.revision==before.revision
    assert after.payload==before.payload
    assert {kind:len(store.list_current(kind)) for kind in counts}==counts
    assert [e.event_id for e in store.events()]==events
    store.close()

def test_unknown_face_operation_is_rejected_without_new_revision(tmp_path):
    store,client,draft=_draft(tmp_path);state=_state(client,draft);before=store.current(draft)
    result=_edit(client,draft,state,operation='UNKNOWN_OPERATION',points=[],idempotency_key='unknown-regression')
    assert result.status_code in (409,422),result.text
    assert store.current(draft).revision==before.revision
    store.close()
