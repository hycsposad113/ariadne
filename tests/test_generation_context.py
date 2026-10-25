"""Synthetic resolver outputs exercise freeze without creating HumanDecision records."""
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import box

from urban_design import generation_context as gc
from urban_design.store import ProjectStateStore
from urban_design.morphology.floor_estimate import estimate_floor_count
from urban_design.models import UnavailableValue


def fixture_inputs():
    record = NS(entity_id='fixture', revision=6, entity_type='Fixture', payload={'status': 'FIXTURE_ONLY'})
    decision = NS(id='mock-bound-reference', target_id='fixture', target_version='6', target_payload_digest='a' * 64)
    return NS(workspace_record=record, study_area=record, constraint_record=record,
              source_snapshots=(), source_artifacts=(), workspace=NS(revision=6),
              workspace_decision=decision, constraint_decision=decision, input_hash='b' * 64,
              design_area=box(0, 0, 100, 80), water_geometry=None, constraint_set=NS(allocation_policy='priority', constraints=(NS(name='far_upper_limit', scope='whole_site', denominator=None),)),
              zones=(('a', 'housing', box(0, 0, 60, 80)), ('b', 'work', box(40, 0, 100, 80))))


@pytest.fixture
def client(tmp_path):
    store = ProjectStateStore(tmp_path / 'test.sqlite3')
    app = FastAPI()
    app.include_router(gc.create_generation_context_router(store))
    with TestClient(app) as client:
        yield client, store
    store.close()


def test_no_approval_blocks_without_writes(client):
    client, store = client
    store.create_project({'id': 'p', 'name': 'fixture'}, project_id='p')
    before = store.connection.total_changes
    response = client.get('/projects/p/generation-context/readiness')
    assert response.json()['status'] == 'BLOCKED'
    assert response.json()['context'] is None
    assert client.post('/projects/p/generation-context/freeze', json={
        'expected_workspace_revision': 6, 'expected_context_hash': 'a' * 64}).status_code == 409
    assert store.list_current('HumanDecision', project_id='p') == []
    assert store.connection.total_changes == before


@pytest.mark.parametrize('label', ['ASSUMED', 'FIXTURE_ONLY', 'UNAPPROVED_PREVIEW'])
def test_unapproved_labels_are_never_authority(client, label):
    client, store = client
    store.create_project({'id': 'p', 'name': 'fixture'}, project_id='p')
    store.create('WorkspaceRevision', {'status': label}, entity_id='workspace-p', project_id='p')
    assert client.get('/projects/p/generation-context/readiness').json()['status'] == 'BLOCKED'


def test_freeze_hash_and_stale_409(client, monkeypatch):
    client, store = client
    inputs = fixture_inputs()
    monkeypatch.setattr(gc, '_load_approved_inputs', lambda *a, **kw: inputs)
    monkeypatch.setattr(gc, '_floor_estimates', lambda *a: ((), [{'floor_count': {'status': 'UNAVAILABLE', 'estimate_range': [1, 4]}}]))
    url = '/projects/p/generation-context'
    readiness = client.get(url + '/readiness').json()
    assert readiness['context']['far_denominator']['area_m2'] == 8000
    assert readiness['context']['far_denominator']['scope'] == 'EXPLORATION_DESIGN_AREA'
    assert readiness['context']['floor_estimates'][0]['floor_count']['estimate_range'] == [1, 4]
    request = dict(expected_workspace_revision=6, expected_context_hash=readiness['context_hash'])
    assert client.post(url + '/freeze', json=request).json() == readiness
    assert client.post(url + '/freeze', json={**request, 'approved': True}).status_code == 422
    assert client.post(url + '/freeze', json={**request, 'expected_workspace_revision': 5}).status_code == 409
    inputs.constraint_record = NS(entity_id='constraint', revision=2, entity_type='ConstraintSet', payload={'version': 'changed'})
    assert client.post(url + '/freeze', json=request).json()['detail']['status'] == 'STALE'
    assert store.list_current('HumanDecision') == []


def test_valid_draft_still_requires_bound_human_decision(client):
    from urban_design.workspace_contracts import WorkspaceRevision, WorkspaceSpatialBrief, ExplorationDesignArea, SpatialZone
    from urban_design.approved_generation import _workspace_payload_digest
    from shapely.geometry import mapping
    client, store = client
    store.create_project({'id': 'p', 'name': 'fixture'}, project_id='p')
    area = mapping(box(0, 0, 100, 80))
    workspace = WorkspaceRevision(workspace_id='workspace-p', project_id='p', revision=1,
        study_area_id='study', spatial_brief=WorkspaceSpatialBrief(
            exploration_design_area=ExplorationDesignArea(geometry=area),
            zones=[SpatialZone(zone_id='z', name='fixture', target_use='housing', geometry=area, notes='FIXTURE_ONLY')]))
    workspace.payload_digest = _workspace_payload_digest(workspace)
    store.create('WorkspaceRevision', workspace.model_dump(mode='json'), entity_id='workspace-p', project_id='p')
    result = client.get('/projects/p/generation-context/readiness').json()
    assert result['status'] == 'BLOCKED'
    assert any('no current approved HumanDecision' in reason for reason in result['blockers'])
    assert not any('current WorkspaceRevision is invalid' in reason for reason in result['blockers'])


def test_priority_overlap_is_allocated_once():
    inputs = fixture_inputs()
    zones = gc.allocated_zones(inputs)
    assert [z['allocated_area_m2'] for z in zones] == [4800, 3200]
    inputs.constraint_set.allocation_policy = None
    with pytest.raises(gc.ApprovedGenerationBlocked):
        gc.allocated_zones(inputs)


def test_freeze_checks_3dbag_artifact_bytes(client, monkeypatch, tmp_path):
    import hashlib
    client, store = client
    inputs = fixture_inputs()
    source = tmp_path / 'synthetic-3dbag.json'
    source.write_text('{"type":"FeatureCollection","features":[]}')
    payload = dict(id='artifact-bag', project_id='p', uri=str(source),
                   sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    store.create('Artifact', payload, entity_id='artifact-bag', project_id='p')
    inputs.source_snapshots = (NS(entity_id='snapshot-bag', revision=1, entity_type='DatasetSnapshot',
        payload=dict(source='3D BAG FIXTURE_ONLY', raw_artifact_id='artifact-bag', normalized_artifact_id='artifact-bag')),)
    monkeypatch.setattr(gc, '_load_approved_inputs', lambda *a, **kw: inputs)
    monkeypatch.setattr(gc, '_floor_estimates', lambda *a: ((), []))
    url = '/projects/p/generation-context'
    ready = client.get(url + '/readiness').json()
    assert any(r['id'] == 'artifact-bag' for r in ready['context']['refs'])
    # Fault injection modifies only this synthetic test artifact.
    source.write_text('corrupt fixture bytes')
    blocked = client.get(url + '/readiness').json()
    assert blocked['status'] == 'BLOCKED'
    assert blocked['context'] is None
    assert client.post(url + '/freeze', json=dict(expected_workspace_revision=6,
        expected_context_hash=ready['context_hash'])).status_code == 409


def test_floor_unknown_and_range_remain_estimates():
    args = dict(building_id='fixture', bag_id=None, ground_height_m=0,
                building_use='industriefunctie', height_field_name='roof_p70', data_version='FIXTURE_ONLY')
    assert isinstance(estimate_floor_count(**args, roof_p70_height_m=None).floor_count, UnavailableValue)
    estimate = estimate_floor_count(**args, roof_p70_height_m=12)
    assert estimate.floor_count == (1, 4)
    assert estimate.floor_height_status == 'FIXTURE_ONLY'
