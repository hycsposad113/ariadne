from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.face_editing_api import create_face_editing_router


def client():
    app = FastAPI()
    app.include_router(create_face_editing_router())
    return TestClient(app)


def fixture():
    return dict(provenance='FIXTURE_ONLY', coordinate_reference='FIXTURE_LOCAL_METRES', building_id='fixture', first_floor_height_m=4, standard_floor_height_m=3,
                floors=[dict(id='f0', level=0, ring=[[0,0],[10,0],[10,10],[0,10],[0,0]])])


def test_fixture_preview_quantities_and_no_authority():
    response = client().post('/api/v1/editing/faces/fixture-preview', json=fixture())
    assert response.status_code == 200
    result = response.json()
    assert result['gfa_m2'] == 100 and result['volume_m3'] == 400
    assert result['production_status'] == 'BLOCKED' and not result['acceptance_eligible']
    assert client().get('/api/v1/editing/faces/readiness').json()['status'] == 'BLOCKED'


def test_rejects_authority_promotion_stale_revision_and_kind_mismatch():
    for patch in [dict(provenance='APPROVED'), dict(approved=True), dict(actions=[dict(operation='SETBACK', parent_revision=2)]), dict(actions=[dict(operation='TOP_EXTRUDE', face_id='r0:f0:side:0', parent_revision=0)])]:
        assert client().post('/api/v1/editing/faces/fixture-preview', json={**fixture(), **patch}).status_code == 422


def test_replay_split_then_undo_recovers_exact_hash_and_gfa():
    initial = client().post('/api/v1/editing/faces/fixture-preview', json=fixture()).json()
    actions = [dict(operation='SPLIT_LINE', face_id='r0:f0:top', parent_revision=0, points=[[5,-1],[5,11]]), dict(operation='UNDO', parent_revision=1)]
    restored = client().post('/api/v1/editing/faces/fixture-preview', json={**fixture(), 'actions': actions}).json()
    assert restored['geometry_hash'] == initial['geometry_hash'] and restored['gfa_m2'] == initial['gfa_m2']


def test_malformed_cut_rejected_without_server_error():
    for operation, points in [('SPLIT_LINE', [[0,0]]), ('SPLIT_CONTOUR', [[0,0],[1,1]])]:
        payload = {**fixture(), 'actions': [dict(operation=operation, parent_revision=0, face_id='r0:f0:top', points=points)]}
        assert client().post('/api/v1/editing/faces/fixture-preview', json=payload).status_code == 422
