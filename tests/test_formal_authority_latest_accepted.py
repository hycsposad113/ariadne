"""Fresh disposable authority regressions; never create formal decisions."""
from dataclasses import replace
import pytest
from test_week6_d1_workspace_binding import authority_copy
from urban_design.decision_resolution import latest_accepted_workspace
from urban_design.editing.formal_authority import _bind_study_area, FormalAuthorityError


def test_draft_nine_binds_eight(authority_copy):
    store = authority_copy
    head = store.list_current('WorkspaceRevision')[0]
    assert head.revision == 9
    assert head.payload['status'] == 'DRAFT'
    workspace, decision = latest_accepted_workspace(store, head.project_id)
    assert workspace.revision == 8
    assert decision.payload['target_version'] == '8'
    assert _bind_study_area(store, store.list_current('DesignScenario')[0]).entity_id == workspace.payload['study_area_id']


def test_payload_tamper_fails(authority_copy, monkeypatch):
    store = authority_copy
    head = store.list_current('WorkspaceRevision')[0]
    record = store.get_record(head.entity_id, 8)
    corrupt = replace(record, payload={**record.payload, 'payload_digest': 'f'*64})
    get = store.get_record
    history = store.history
    monkeypatch.setattr(store, 'get_record', lambda entity_id, revision=None: corrupt if entity_id == head.entity_id and revision == 8 else get(entity_id, revision))
    monkeypatch.setattr(store, 'history', lambda entity_id: [corrupt if row.revision == 8 else row for row in history(entity_id)])
    with pytest.raises(FormalAuthorityError, match='D1'):
        _bind_study_area(store, store.list_current('DesignScenario')[0])


def test_no_acceptance_fails(tmp_path):
    from urban_design.store import ProjectStateStore
    with ProjectStateStore(tmp_path/'empty.sqlite3') as store:
        store.create_project({'id':'empty-project','name':'No acceptance fixture'},project_id='empty-project')
        geometry = {'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,0]]]}
        store.create('WorkspaceRevision', {'workspace_id':'empty-workspace','project_id':'empty-project','revision':1,'status':'DRAFT','spatial_brief':{'exploration_design_area':{'geometry':geometry}}},entity_id='empty-workspace',project_id='empty-project')
        with pytest.raises(ValueError, match='no current approved HumanDecision'):
            latest_accepted_workspace(store, 'empty-project')


def test_reject_after_approve_uses_ledger_sequence(tmp_path):
    from urban_design.store import ProjectStateStore
    from urban_design.decision_key import initialize_decision_key
    from urban_design.models import ActorKind, HumanDecision
    from urban_design.geometry import canonical_geometry_hash
    from urban_design.workspace_contracts import WorkspaceRevision
    from urban_design.approved_generation import _workspace_payload_digest
    from datetime import datetime, timezone
    geometry = {'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,0]]]}
    geometry_hash = canonical_geometry_hash(geometry)
    project = 'synthetic-j6'
    key = 'temporary-j6-test-only-password'
    key_path = initialize_decision_key(path=tmp_path/'key', password_prompt=lambda _:key)
    with ProjectStateStore(tmp_path/'state.sqlite3') as store:
        store.create_project({'id':project,'name':'Synthetic J6'},project_id=project)
        store.create('StudyArea', {'id':'study','version':'1','status':'CONFIRMED_FOR_EXPLORATION','geometry_sha256':geometry_hash},entity_id='study',project_id=project)
        ws = WorkspaceRevision(workspace_id='workspace-'+project,project_id=project,study_area_id='study',revision=1,status='DRAFT',source_snapshot_ids=[],feature_dispositions=[],spatial_brief={'exploration_design_area':{'geometry':geometry}})
        payload=ws.model_dump(mode='json');payload['payload_digest']=_workspace_payload_digest(ws).removeprefix('sha256:')
        record=store.create('WorkspaceRevision',payload,entity_id=ws.workspace_id,project_id=project)
        for action,status,year in [('Approve','approved',2030),('Reject','rejected',2020)]:
            decision=HumanDecision(id='decision-'+action,project_id=project,target_id=record.entity_id,target_type='WorkspaceRevision',target_version='1',target_geometry_sha256=geometry_hash,target_payload_digest='sha256:'+payload['payload_digest'],action=action,status=status,actor='test-founder',actor_kind=ActorKind.HUMAN_UI,actor_session_id='j6-fixture',reason='Synthetic only',timestamp=datetime(year,1,1,tzinfo=timezone.utc))
            store.record_human_decision(decision,decision_key=key,decision_key_path=key_path)
            if action=='Approve':assert latest_accepted_workspace(store,project)[0].revision==1
        with pytest.raises(ValueError,match='revoked'):
            latest_accepted_workspace(store,project)


def test_historical_resolution_is_workspace_only(tmp_path):
    from urban_design.store import ProjectStateStore
    from urban_design.decision_resolution import DecisionTarget, resolve_decision
    with ProjectStateStore(tmp_path/'historical.sqlite3') as store:
        result = resolve_decision(store, DecisionTarget('p','DesignScenario','s','1','sha256:'+'a'*64,'target_geometry_sha256',1))
        assert result.status == 'BLOCKED'
        assert result.reason == 'HISTORICAL_TARGET_TYPE_FORBIDDEN'


def test_road_edit_records_resolved_authority(tmp_path):
    from test_formal_editor_authority import _world, _accept
    from test_formal_road_snapping import _stages
    store, client, secret, _, scenario_ids, _ = _world(tmp_path, stages=_stages())
    try:
        _accept(client, secret, scenario_ids)
        opened = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
        assert opened.status_code == 201, opened.text
        draft_id = opened.json()['scenario_id']
        before = store.current(draft_id)
        response = client.post(f"/api/v1/scenarios/{draft_id}/road-nodes/m/move", json={
            'x_m':10.2,'y_m':10.0,'expected_revision':0,
            'expected_graph_hash':opened.json()['editor']['road_graph']['graph_hash'],
            'idempotency_key':'j6-road-binding','snap_kind':'MIDPOINT',
        })
        assert response.status_code == 201, response.text
        binding = store.current(draft_id).payload['parameters']['editor_binding']
        assert binding['scenario_revision'] == before.revision
        assert binding['geometry_sha256'] == before.payload['geometry_sha256']
        assert binding['source_refs']
    finally:
        store.close()


def test_undo_redo_records_each_resolved_authority(tmp_path):
    from test_formal_editor_authority import _world, _accept
    store, client, secret, _, scenario_ids, _ = _world(tmp_path)
    try:
        _accept(client, secret, scenario_ids)
        opened = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
        assert opened.status_code == 201, opened.text
        draft_id = opened.json()['scenario_id']
        edited = client.post(f"/api/v1/scenarios/{draft_id}/edits", json={
            'building_id':'b-holed','command':{'type':'move','dx_m':1,'dy_m':0},
            'expected_revision':0,'idempotency_key':'j6-pointer-binding',
        })
        assert edited.status_code == 201, edited.text
        expected_revision = edited.json()['active_revision_id']
        for operation in ('undo','redo'):
            before = store.current(draft_id)
            response = client.post(f"/api/v1/scenarios/{draft_id}/edits/{operation}",json={'expected_revision':expected_revision})
            assert response.status_code == 200, response.text
            binding = store.current(draft_id).payload['parameters']['editor_binding']
            assert binding['scenario_revision'] == before.revision
            assert binding['geometry_sha256'] == before.payload['geometry_sha256']
            expected_revision = response.json()['active_revision_id']
    finally:
        store.close()


def test_face_edit_records_resolved_authority(tmp_path):
    from test_formal_face_editing_api import _draft, _state, _edit
    store, client, draft_id = _draft(tmp_path)
    try:
        before = store.current(draft_id)
        response = _edit(client, draft_id, _state(client,draft_id),idempotency_key='j6-face-binding')
        assert response.status_code == 200, response.text
        binding = store.current(draft_id).payload['parameters']['editor_binding']
        assert binding['scenario_revision'] == before.revision
        assert binding['geometry_sha256'] == before.payload['geometry_sha256']
        assert binding['source_refs']
    finally:
        store.close()
