"""Formal face edits on a disposable FORMAL_DRAFT. The fixture preview route is not called."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from shapely.geometry import box, mapping, shape

from urban_design.models import ActorKind, Artifact
from urban_design.scenario_api import register_scenario_routes
from urban_design.store import ProjectStateStore


def _helpers():
    path = Path(__file__).with_name("test_formal_editor_authority.py")
    spec = importlib.util.spec_from_file_location("g4_formal_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _rect_stages() -> dict:
    geometry = mapping(box(0, 0, 20, 50))
    floors = [
        {"id": f"b-rect-floor-{level}", "level": level, "floor_height_m": 3.5, "use": "residential", "geometry": geometry}
        for level in range(4)
    ]
    return {
        "massing": {"buildings": [{"id": "b-rect", "use": "residential", "height_m": 14.0, "floors": floors, "footprint": geometry}]},
        "skeleton": {"edges": [{"id": "edge-1", "from_node_id": "n-start", "to_node_id": "n-end", "level": 0, "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]}}]},
    }


def _draft(tmp_path: Path):
    helpers = _helpers()
    store, client, secret, _key_path, scenario_ids, _digest = helpers._world(tmp_path, stages=_rect_stages())
    helpers._accept(client, secret, scenario_ids)
    opened = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
    assert opened.status_code == 201, opened.text
    assert opened.json()["provenance"] == "FORMAL_DRAFT"
    return store, client, opened.json()["scenario_id"]


def _gfa(body: dict) -> float:
    return sum(float(shape(floor["geometry"]).area) for floor in body["floors"])


def _top(body: dict) -> dict:
    matches = [face for face in body["faces"] if face["kind"] == "TOP"]
    assert len(matches) == 1
    return matches[0]


def _cut(face: dict) -> list[list[float]]:
    ring = face["geometry"]["coordinates"][0]
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    mid = (min(ys) + max(ys)) / 2
    return [[min(xs) - 1, mid], [max(xs) + 1, mid]]


def _edit(client, draft_id: str, state: dict, **overrides):
    payload = {
        "building_id": "b-rect",
        "operation": "SPLIT_LINE",
        "steps": 1,
        "parent_revision": state["face_revision"],
        "expected_scenario_revision": state["scenario_revision"],
        "expected_geometry_hash": state["geometry_hash"],
        "idempotency_key": "face-edit",
    }
    if "face_id" not in overrides or "points" not in overrides:
        top = _top(state)
        payload["face_id"] = top["id"]
        payload["points"] = _cut(top)
    payload.update(overrides)
    return client.post(f"/api/v1/scenarios/{draft_id}/editing/faces", json=payload)


def _state(client, draft_id: str) -> dict:
    response = client.get(f"/api/v1/scenarios/{draft_id}/editing/faces", params={"building_id": "b-rect"})
    assert response.status_code == 200, response.text
    return response.json()


def test_split_keeps_floor_area_and_upper_setback_changes_gfa_by_272(tmp_path: Path):
    _store, client, draft_id = _draft(tmp_path)
    before = _state(client, draft_id)
    assert _gfa(before) == 4000.0
    split = _edit(client, draft_id, before, idempotency_key="split-only")
    assert split.status_code == 200, split.text
    split_body = split.json()
    assert _gfa(split_body) == 4000.0
    assert split_body["lineage"]
    assert split_body["lineage"][0][0] == _top(before)["id"]
    assert set(split_body["lineage"][0][1]) <= {face["id"] for face in split_body["faces"]}
    assert split_body["acceptance_eligible"] is False
    assert split_body["analysis_eligible"] is False
    setback = _edit(
        client, draft_id, split_body,
        operation="SETBACK", face_id=None, points=[], steps=1, idempotency_key="setback-upper-two",
    )
    assert setback.status_code == 200, setback.text
    body = setback.json()
    areas = sorted(float(shape(floor["geometry"]).area) for floor in body["floors"])
    assert areas == [864.0, 864.0, 1000.0, 1000.0]
    assert _gfa(body) == 3728.0
    assert 4000.0 - _gfa(body) == 272.0
    upper = max(body["floors"], key=lambda floor: floor["level"])
    assert shape(upper["geometry"]).bounds == (1.0, 1.0, 19.0, 49.0)
    assert body["height_m"] <= 20.0
    reopened = ProjectStateStore(tmp_path / "editor.sqlite3")
    app = FastAPI()
    register_scenario_routes(app, reopened, tmp_path / "draft-artifacts", decision_key_path=tmp_path / "decision-key")
    restored = _state(__import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app), draft_id)
    assert restored["lineage"] == body["lineage"]
    assert _gfa(restored) == 3728.0
    assert restored["provenance"] == "FORMAL_DRAFT"


def test_extruding_past_20_metres_is_refused_without_a_staging_file(tmp_path: Path):
    _store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    refused = _edit(client, draft_id, state, operation="TOP_EXTRUDE", steps=2, points=[], idempotency_key="too-tall")
    assert refused.status_code == 409, refused.text
    assert "20" in refused.text
    assert not (tmp_path / "draft-artifacts" / "face-staging").exists()
    assert _gfa(_state(client, draft_id)) == 4000.0
    allowed = _edit(client, draft_id, state, operation="TOP_EXTRUDE", steps=1, points=[], idempotency_key="one-storey")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["height_m"] == 17.5
    assert allowed.json()["height_m"] <= 20.0


def test_stale_revision_and_reused_key_do_not_publish_a_second_edit(tmp_path: Path):
    _store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    stale = _edit(client, draft_id, state, expected_scenario_revision=state["scenario_revision"] + 9, idempotency_key="stale")
    assert stale.status_code == 409, stale.text
    assert "stale" in stale.text
    assert not (tmp_path / "draft-artifacts" / "face-staging").exists()
    first = _edit(client, draft_id, state, idempotency_key="same-key")
    assert first.status_code == 200, first.text
    again = _edit(client, draft_id, state, idempotency_key="same-key")
    assert again.status_code == 200, again.text
    assert again.json()["idempotent_replay"] is True
    assert again.json()["face_revision"] == first.json()["face_revision"]
    changed = _edit(client, draft_id, state, idempotency_key="same-key", points=[[0, 0], [1, 1]])
    assert changed.status_code == 409, changed.text
    assert "idempotency key was reused" in changed.text
    assert _state(client, draft_id)["face_revision"] == first.json()["face_revision"]


def test_publication_failure_keeps_staging_and_the_peer_file(tmp_path: Path):
    store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    published = tmp_path / "draft-artifacts" / "face-published"
    published.mkdir(parents=True)
    peer = published / "peer.geojson"
    peer.write_bytes(b'{"type":"FeatureCollection","features":[]}\n')
    peer_bytes = peer.read_bytes()
    from urban_design.formal_face_editing_api import FormalFaceRequest, _fingerprint
    top = _top(state)
    request = FormalFaceRequest(building_id="b-rect", operation="SPLIT_LINE", steps=1,
        face_id=top["id"], points=_cut(top), parent_revision=state["face_revision"],
        expected_scenario_revision=state["scenario_revision"],
        expected_geometry_hash=state["geometry_hash"], idempotency_key="publish-fails")
    publication_key = __import__("hashlib").sha256(
        f"{draft_id}:{state['scenario_revision']}:b-rect:{_fingerprint(request)}".encode()
    ).hexdigest()
    store.create_typed(
        Artifact(
            id=f"face-{publication_key}",
            type="FORMAL_FACE_EDIT",
            uri=str(peer),
            sha256="sha256:" + __import__("hashlib").sha256(peer_bytes).hexdigest(),
            mime="application/geo+json",
            crs="EPSG:28992",
            producer="formal-face-edit",
            created_at=datetime.now(timezone.utc),
            project_id="proj-formal",
            size_bytes=peer.stat().st_size,
        ),
        actor="scenario-editor",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        reason="Occupy the face artifact id so publication must fail",
    )
    failed = _edit(client, draft_id, state, idempotency_key="publish-fails")
    assert failed.status_code == 409, failed.text
    assert "staging retained" in failed.text
    staging = tmp_path / "draft-artifacts" / "face-staging" / f"face-{publication_key}.geojson"
    assert staging.is_file()
    assert peer.read_bytes() == peer_bytes
    assert _state(client, draft_id)["face_revision"] == 0


def test_kernel_errors_are_machine_readable_422_without_publication(tmp_path):
    _store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    response = _edit(client, draft_id, state, points=[[100, 100], [101, 101]])
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'FACE_EDIT_REJECTED'
    assert 'subdivide' in response.json()['detail']['message']
    assert _state(client, draft_id)['face_revision'] == 0
    assert not (tmp_path / 'draft-artifacts' / 'face-staging').exists()


def test_get_kernel_errors_are_machine_readable_422(tmp_path, monkeypatch):
    _store, client, draft_id = _draft(tmp_path)
    from urban_design.editing.faces import FaceEditError
    def invalid_session(session):
        raise FaceEditError('invalid/self-intersecting/nonmanifold polygon')
    monkeypatch.setattr('urban_design.formal_face_editing_api._replay', invalid_session)
    response = client.get(f'/api/v1/scenarios/{draft_id}/editing/faces', params={'building_id': 'b-rect'})
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'FACE_EDIT_REJECTED'


def test_formal_courtyard_outer_face_edit_preserves_hole_and_reload(tmp_path, monkeypatch):
    from shapely.geometry import Polygon
    stages = _rect_stages()
    courtyard = Polygon([(0,0),(20,0),(20,50),(0,50)], [[(5,10),(15,10),(15,40),(5,40)]])
    building = stages['massing']['buildings'][0]
    building['footprint'] = mapping(courtyard)
    for floor in building['floors']:
        floor['geometry'] = mapping(courtyard)
    monkeypatch.setattr(__import__(__name__, fromlist=['_rect_stages']), '_rect_stages', lambda: stages)
    _store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    assert state['inner_ring_editing_supported'] is False
    assert len(state['inner_ring_faces']) == 16
    inner = state['inner_ring_faces'][0]
    assert inner['editable'] is False
    refused = _edit(client, draft_id, state, operation='SIDE_PUSH', face_id=inner['id'], points=[])
    assert refused.status_code == 422
    assert refused.json()['detail']['code'] == 'INNER_RING_EDITING_UNSUPPORTED'
    side = next(f for f in state['faces'] if f['kind'] == 'SIDE' and f['floor_id'] == 'b-rect-floor-0')
    response = _edit(client, draft_id, state, operation='SIDE_PUSH', face_id=side['id'], points=[])
    assert response.status_code == 200, response.text
    edited = shape(response.json()['floors'][0]['geometry'])
    assert edited.is_valid
    assert Polygon(edited.interiors[0]).equals(Polygon(courtyard.interiors[0]))
    assert _state(client, draft_id)['geometry_hash'] == response.json()['geometry_hash']
    assert response.json()['acceptance_eligible'] is False
    assert response.json()['analysis_eligible'] is False
    moved = client.post(f'/api/v1/scenarios/{draft_id}/edits', json={'building_id': 'b-rect', 'command': {'type': 'move', 'dx_m': 1, 'dy_m': 0}, 'expected_revision': 0, 'idempotency_key': 'courtyard-move'})
    assert moved.status_code == 201, moved.text
    fresh = _state(client, draft_id)
    stale_inner = _edit(client, draft_id, fresh, operation='SIDE_PUSH', face_id=inner['id'], points=[], idempotency_key='old-inner')
    assert stale_inner.status_code == 409, stale_inner.text
    current_inner = _edit(client, draft_id, fresh, operation='SIDE_PUSH', face_id=fresh['inner_ring_faces'][0]['id'], points=[], idempotency_key='current-inner')
    assert current_inner.status_code == 422, current_inner.text
    assert current_inner.json()['detail']['code'] == 'INNER_RING_EDITING_UNSUPPORTED'


def test_inner_ring_face_is_explicitly_uneditable(tmp_path):
    _store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    response = _edit(client, draft_id, state, operation='SIDE_PUSH', face_id='r0:b-rect-floor-0:inner:0:side:0', points=[])
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'INNER_RING_EDITING_UNSUPPORTED'


def test_publication_kernel_error_remains_machine_readable_422(tmp_path, monkeypatch):
    from urban_design.editing.faces import FaceEditError
    _store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    def reject_publication(*args, **kwargs):
        raise FaceEditError('invalid publication geometry')
    monkeypatch.setattr('urban_design.formal_face_editing_api.publish_formal_draft_edit', reject_publication)
    response = _edit(client, draft_id, state)
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'FACE_EDIT_REJECTED'
    assert _state(client, draft_id)['face_revision'] == 0


def test_move_rotate_reloads_current_faces_and_rejects_old_ids(tmp_path):
    _store, client, draft_id = _draft(tmp_path)
    before = _state(client, draft_id)
    for index, command in enumerate([{'type': 'move', 'dx_m': 1, 'dy_m': 0}, {'type': 'rotate', 'angle_degrees': 17}]):
        result = client.post(f'/api/v1/scenarios/{draft_id}/edits', json={'building_id': 'b-rect', 'command': command, 'expected_revision': index, 'idempotency_key': f'massing-{index}'})
        assert result.status_code == 201, result.text
    fresh = _state(client, draft_id)
    assert fresh['geometry_hash'] != before['geometry_hash']
    assert _top(fresh)['id'] != _top(before)['id']
    stale = _edit(client, draft_id, fresh, face_id=_top(before)['id'], points=_cut(_top(fresh)), idempotency_key='stale-face')
    assert stale.status_code == 409, stale.text
    assert 'stale' in stale.json()['detail'].lower()
    split = _edit(client, draft_id, fresh, idempotency_key='fresh-split')
    assert split.status_code == 200, split.text
    assert _state(client, draft_id)['face_revision'] == split.json()['face_revision']


def test_face_session_rebases_after_subdivision_then_massing_move(tmp_path):
    _store, client, draft_id = _draft(tmp_path)
    state = _state(client, draft_id)
    split = _edit(client, draft_id, state, idempotency_key='first-split')
    assert split.status_code == 200, split.text
    moved = client.post(f'/api/v1/scenarios/{draft_id}/edits', json={'building_id': 'b-rect', 'command': {'type': 'move', 'dx_m': 1, 'dy_m': 0}, 'expected_revision': 0, 'idempotency_key': 'move-after-split'})
    assert moved.status_code == 201, moved.text
    fresh = _state(client, draft_id)
    assert fresh['geometry_hash'] != split.json()['geometry_hash']
    assert fresh['face_revision'] == 0
    assert fresh['lineage'] == []
    assert _gfa(fresh) == _gfa(state)
    result = _edit(client, draft_id, fresh, idempotency_key='second-split')
    assert result.status_code == 200, result.text
