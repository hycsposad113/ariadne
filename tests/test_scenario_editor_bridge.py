"""Synthetic boundary checks; no real approved baseline is created."""
from dataclasses import replace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from test_scenario_editing_api import _scenario
from urban_design.scenario_editing_api import register_scenario_edit_routes


def _mark(store, scenario_id, provenance):
    record = store.current(scenario_id)
    payload = dict(record.payload)
    if provenance == 'FORMAL_DRAFT':
        payload['geometry_sha256'] = store.current(payload['geometry_artifact_id']).payload['sha256']
    payload['parameters'] = {**payload['parameters'], 'provenance': provenance}
    for item in payload['parameters']['editable_buildings']:
        item['provenance'] = provenance
    store.update(scenario_id, payload, expected_revision=record.revision, replace=True,
                 actor='fixture-harness', action='FixtureBoundary', reason='Synthetic adapter boundary')


def _request(store, scenario_id, command=None):
    return {'building_id': store.current(scenario_id).payload['parameters']['editable_buildings'][0]['building_id'],
            'command': command or {'type': 'move', 'dx_m': 1, 'dy_m': 0},
            'expected_revision': 0, 'idempotency_key': 'bridge-fixture'}


@pytest.mark.parametrize('provenance', ['FORMAL_DRAFT', 'ASSUMED', 'UNAPPROVED_PREVIEW'])
def test_nonfixture_input_cannot_be_silently_relabelled(tmp_path, provenance):
    client, store, scenario_id = _scenario(tmp_path)
    _mark(store, scenario_id, provenance)
    before = store.current(scenario_id).revision
    response = client.post(f'/api/v1/scenarios/{scenario_id}/edits', json=_request(store, scenario_id))
    assert response.status_code == 409
    assert 'BLOCKED' in response.text
    assert store.current(scenario_id).revision == before


def test_formal_adapter_keeps_provenance_and_requires_exact_binding(tmp_path):
    from urban_design.scenario_editing_api import FormalEditorBinding, ResolvedEditorRef, _hash_json
    _, store, scenario_id = _scenario(tmp_path)
    _mark(store, scenario_id, 'FORMAL_DRAFT')
    record = store.current(scenario_id)
    binding = FormalEditorBinding(scenario_id=scenario_id, scenario_revision=record.revision,
        geometry_sha256=record.payload['geometry_sha256'],
        editor_inputs_sha256='sha256:' + _hash_json(record.payload['parameters']), baseline_status='ACCEPTED',
        baseline_decision_ref=ResolvedEditorRef('synthetic-resolved-decision', 1, 'sha256:' + '1' * 64),
        constraint_refs=(ResolvedEditorRef('synthetic-resolved-constraints', 1, 'sha256:' + '2' * 64),),
        source_refs=(ResolvedEditorRef('synthetic-resolved-source', 1, 'sha256:' + '3' * 64),))
    class Adapter:
        def resolve(self, store, record):
            return binding
    app = FastAPI(); router = APIRouter()
    register_scenario_edit_routes(router, store, tmp_path / 'formal-artifacts', formal_adapter=Adapter())
    app.include_router(router)
    client = TestClient(app)
    response = client.post(f'/api/v1/scenarios/{scenario_id}/edits', json=_request(store, scenario_id))
    assert response.status_code == 201, response.text
    assert response.json()['building']['provenance'] == 'FORMAL_DRAFT'
    assert response.json()['validation']['geometry_valid'] is True
    assert response.json()['validation']['acceptance_eligible'] is False
    assert response.json()['dashboard']['provenance'] == 'FORMAL_DRAFT'
    binding = replace(binding, scenario_revision=record.revision)
    response = client.post(f'/api/v1/scenarios/{scenario_id}/edits/undo', json={'expected_revision': 1})
    assert response.status_code == 409  # stale server resolution cannot authorize pointer mutation
    assert store.list_current('HumanDecision') == []


def test_invalid_draft_saved_reopened_and_blocked(tmp_path):
    client, store, scenario_id = _scenario(tmp_path)
    response = client.post(f'/api/v1/scenarios/{scenario_id}/edits',
        json=_request(store, scenario_id, {'type': 'move', 'dx_m': 1000, 'dy_m': 0}))
    assert response.status_code == 201, response.text
    validation = response.json()['validation']
    assert validation['geometry_valid'] is False
    assert validation['acceptance_eligible'] is False
    assert validation['analysis_eligible'] is False
    from urban_design.store import ProjectStateStore
    reopened = ProjectStateStore(tmp_path / 'edit-api.sqlite3')
    draft = reopened.current(scenario_id).payload
    assert draft['status'] == 'draft'
    assert draft['parameters']['massing_revision_records'][-1]['validation'] == validation
    assert response.json()['dashboard']['scenario_metrics']['far']['validation_status'] == 'UNAVAILABLE'


def test_dashboard_reopens_active_invalid_revision_and_undo_restores_metrics(tmp_path):
    client, store, scenario_id = _scenario(tmp_path)
    request = _request(store, scenario_id, {'type': 'move', 'dx_m': 1000, 'dy_m': 0})
    assert client.post(f'/api/v1/scenarios/{scenario_id}/edits', json=request).status_code == 201
    dashboard = client.get(f'/api/v1/scenarios/{scenario_id}/edits/dashboard', params={'building_id': request['building_id']}).json()
    assert dashboard['metric_state'] == 'NOT_READY'
    assert dashboard['site']['far'] is None
    assert client.post(f'/api/v1/scenarios/{scenario_id}/edits/undo', json={'expected_revision': 1}).status_code == 200
    restored = client.get(f'/api/v1/scenarios/{scenario_id}/edits/dashboard', params={'building_id': request['building_id']}).json()
    assert restored['metric_state'] == 'BACKEND_CONFIRMED'
    assert restored['site']['far'] is not None


def test_invalid_detail_survives_process_reopen_and_redo(tmp_path):
    _, store, scenario_id = _scenario(tmp_path)
    app = FastAPI(); router = APIRouter()
    register_scenario_edit_routes(router, store, tmp_path / 'restart-artifacts')
    app.include_router(router)
    request = _request(store, scenario_id, {'type': 'move', 'dx_m': 1000, 'dy_m': 0})
    assert TestClient(app).post(f'/api/v1/scenarios/{scenario_id}/edits', json=request).status_code == 201
    assert store.current(scenario_id).payload['parameters']['validation']['valid'] is False
    from urban_design.store import ProjectStateStore
    reopened = ProjectStateStore(tmp_path / 'edit-api.sqlite3')
    new_app = FastAPI(); new_router = APIRouter()
    register_scenario_edit_routes(new_router, reopened, tmp_path / 'restart-artifacts')
    new_app.include_router(new_router)
    client = TestClient(new_app)
    assert client.post(f'/api/v1/scenarios/{scenario_id}/edits/undo', json={'expected_revision': 1}).status_code == 200
    assert client.post(f'/api/v1/scenarios/{scenario_id}/edits/redo', json={'expected_revision': 0}).status_code == 200
    assert reopened.current(scenario_id).payload['parameters']['validation']['valid'] is False


@pytest.mark.parametrize('change', ['missing_constraints', 'bad_hash', 'unapproved', 'wrong_inputs'])
def test_formal_binding_missing_or_unapproved_refs_is_blocked(tmp_path, change):
    from urban_design.scenario_editing_api import FormalEditorBinding, ResolvedEditorRef, _hash_json
    _, store, scenario_id = _scenario(tmp_path)
    _mark(store, scenario_id, 'FORMAL_DRAFT')
    record = store.current(scenario_id)
    ref = ResolvedEditorRef('synthetic-resolved-ref', 1, 'sha256:' + '1' * 64)
    binding = FormalEditorBinding(scenario_id, record.revision, record.payload['geometry_sha256'],
        'sha256:' + _hash_json(record.payload['parameters']), 'ACCEPTED', ref, (ref,), (ref,))
    if change == 'missing_constraints': binding = replace(binding, constraint_refs=())
    if change == 'bad_hash': binding = replace(binding, source_refs=(replace(ref, sha256='bad'),))
    if change == 'unapproved': binding = replace(binding, baseline_status='UNAPPROVED_PREVIEW')
    if change == 'wrong_inputs': binding = replace(binding, editor_inputs_sha256='sha256:' + '0' * 64)
    class Adapter:
        def resolve(self, store, record): return binding
    app = FastAPI(); router = APIRouter()
    register_scenario_edit_routes(router, store, tmp_path / 'negative-artifacts', formal_adapter=Adapter())
    app.include_router(router)
    response = TestClient(app).post(f'/api/v1/scenarios/{scenario_id}/edits', json=_request(store, scenario_id))
    assert response.status_code == 409
    assert store.current(scenario_id).revision == record.revision
    assert store.list_current('HumanDecision') == []
