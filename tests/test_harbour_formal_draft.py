"""Harbour stages and formal opening, exclusively against disposable fixtures."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from shapely.geometry import shape

from urban_design.editing.formal_authority import (
    FormalAuthorityError, _load_stages, _buildings_from_stages,
    _roads_from_stages, floor_polygon_gfa_m2,
)
from test_formal_editor_authority import _world, _human_patch, _accept, PROJECT

PLAN = Path(__file__).resolve().parents[1] / 'artifacts/fab1/run-8/harbour_grain-plan.json'


def parameters(path=PLAN):
    return {'provenance': 'FABRIC_PLAN_E2_ONLY', 'source_path': str(path),
            'source_sha256': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()}


def stages(tmp_path, params=None):
    return _load_stages(None, params or parameters(), str(tmp_path / 'geometry.geojson'))


def test_source_hash_checked_before_json_or_inline_stages(tmp_path):
    source = tmp_path / 'plan.json'
    source.write_bytes(b'not JSON')
    p = parameters(source)
    p.update(source_sha256='sha256:' + '0' * 64, stages={'massing': {}})
    with pytest.raises(FormalAuthorityError, match='source.*hash'):
        stages(tmp_path, p)


def test_plan_building_count_gfa_and_explicit_floor_heights(tmp_path):
    plan = json.loads(PLAN.read_bytes())
    derived = stages(tmp_path)
    assert derived['derivation'] == 'FABRIC_PLAN_PRISM_V1'
    assert derived['source_sha256'] == parameters()['source_sha256']
    buildings = _buildings_from_stages(derived)
    new = [b for b in plan['buildings'] if b['properties']['retained'] is False]
    assert len(buildings) == len(new)
    assert floor_polygon_gfa_m2(buildings) == pytest.approx(plan['metrics']['new_gfa_m2'], rel=.005)
    for b, source in zip(derived['massing']['buildings'], new, strict=True):
        p = source['properties']
        assert [f['level'] for f in b['floors']] == list(range(p['floors']))
        assert [f['floor_height_m'] for f in b['floors']] == [p['first_floor_height_m']] + [p['standard_floor_height_m']] * (p['floors'] - 1)
        assert all(f['geometry'] == source['geometry'] for f in b['floors'])


def test_courtyard_holes_preserved(tmp_path):
    plan = json.loads(PLAN.read_bytes())
    # Explicit holed footprint fixture also covers plans whose delivered new units have no holes.
    new = next(b for b in plan['buildings'] if b['properties']['retained'] is False)
    new['geometry'] = {'type': 'Polygon', 'coordinates': [
        [[0,0],[10,0],[10,10],[0,10],[0,0]],
        [[2,2],[2,4],[4,4],[4,2],[2,2]]]}
    path = tmp_path / 'holed.json'
    path.write_text(json.dumps(plan))
    buildings = _buildings_from_stages(stages(tmp_path, parameters(path)))
    b = next(b for b in buildings if b['building_id'] == new['id'])
    assert all(len(shape(f['geometry']).interiors) == 1 for f in b['floors'])
    assert floor_polygon_gfa_m2([b]) == 96 * new['properties']['floors']


def test_retained_buildings_excluded_and_roads_locked(tmp_path):
    plan = json.loads(PLAN.read_bytes())
    derived = stages(tmp_path)
    ids = {b['building_id'] for b in _buildings_from_stages(derived)}
    assert ids.isdisjoint(b['id'] for b in plan['buildings'] if b['properties']['retained'])
    graph = _roads_from_stages(derived)
    assert graph['nodes'] and graph['edges']
    retained = {r['id'] for r in plan['retained_road_inputs']}
    assert retained
    for rid in retained:
        edges = [e for e in graph['edges'] if rid in e['lineage_ids']]
        assert edges and all(e['locked'] for e in edges)
    assert any(not e['locked'] for e in graph['edges'])


def test_other_sources_still_require_stored_stages(tmp_path):
    p = parameters()
    p['provenance'] = 'APPROVED_INPUTS'
    with pytest.raises(FormalAuthorityError, match='per-floor polygons were not found'):
        stages(tmp_path, p)


def test_accepted_harbour_opens_persisted_draft_without_mutating_authority(tmp_path):
    store, client, secret, _, ids, _ = _world(tmp_path)
    parent = store.current(ids[0])
    p = copy.deepcopy(parent.payload['parameters'])
    p.pop('stages')
    p.update(parameters())
    _human_patch(store, ids[0], {'parameters': p}, 'Disposable harbour source fixture')
    _accept(client, secret, ids)
    before = store.current(ids[0])
    decisions = [(r.entity_id, r.revision, r.payload) for r in store.list_current('HumanDecision', project_id=PROJECT)]
    response = client.post(f'/api/v1/scenarios/{ids[0]}/formal-draft')
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['provenance'] == 'FORMAL_DRAFT'
    assert body['scenario_id'] != ids[0]
    assert any(r['scenario_id'] == ids[0] for r in client.get('/api/v1/scenarios').json()['scenarios'])
    retained_id = next(b['id'] for b in json.loads(PLAN.read_bytes())['buildings'] if b['properties']['retained'])
    denied = client.post(f"/api/v1/scenarios/{body['scenario_id']}/edits", json={
        'building_id': retained_id, 'command': {'type': 'move', 'dx_m': 1, 'dy_m': 0},
        'expected_revision': 0, 'idempotency_key': 'retained-must-stay-locked'})
    assert denied.status_code == 409
    assert 'retained' in denied.text
    buildings = body['editor']['editable_buildings']
    assert len(buildings) == 253
    assert floor_polygon_gfa_m2(buildings) == pytest.approx(139128.3, rel=.005)
    assert store.current(ids[0]) == before
    assert [(r.entity_id, r.revision, r.payload) for r in store.list_current('HumanDecision', project_id=PROJECT)] == decisions
    assert client.post(f'/api/v1/scenarios/{ids[0]}/formal-draft').status_code == 200


def test_hash_failure_creates_no_draft_or_ledger_event(tmp_path):
    store, client, secret, _, ids, _ = _world(tmp_path)
    p = copy.deepcopy(store.current(ids[0]).payload['parameters'])
    p.pop('stages')
    p.update(parameters())
    p['source_sha256'] = 'sha256:' + '0' * 64
    _human_patch(store, ids[0], {'parameters': p}, 'Disposable bad hash fixture')
    _accept(client, secret, ids)
    before = store.events(project_id=PROJECT)
    response = client.post(f'/api/v1/scenarios/{ids[0]}/formal-draft')
    assert response.status_code == 409
    assert 'source hash mismatch' in response.text
    assert store.events(project_id=PROJECT) == before
    assert not any(r.payload.get('parameters', {}).get('provenance') == 'FORMAL_DRAFT'
                   for r in store.list_current('DesignScenario'))


@pytest.mark.parametrize('field,value', [('floors', True), ('floors', 0),
                                        ('first_floor_height_m', None),
                                        ('standard_floor_height_m', -1), ('height_m', 21)])
def test_malformed_prisms_fail_closed(tmp_path, field, value):
    plan = json.loads(PLAN.read_bytes())
    next(b for b in plan['buildings'] if b['properties']['retained'] is False)['properties'][field] = value
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(plan))
    with pytest.raises(FormalAuthorityError, match='invalid fabric plan'):
        stages(tmp_path, parameters(path))


def test_fabric_binding_uses_unchanged_approved_input_hash(monkeypatch):
    from types import SimpleNamespace
    import urban_design.approved_generation as approved
    from urban_design.editing import formal_authority as fa

    def ancestor(provenance='FABRIC_PLAN_E2_ONLY', stored='h1'):
        return SimpleNamespace(project_id='p', payload={'parameters': {'provenance': provenance, 'approved_input_hash': stored}})

    current = SimpleNamespace(input_hash='h1', constraint_set=SimpleNamespace(id='cs'))
    monkeypatch.setattr(approved, '_load_approved_inputs', lambda store, project_id, site_generation: current)
    assert fa._fabric_inputs_still_bound(None, ancestor(), 'cs') is True
    assert fa._fabric_inputs_still_bound(None, ancestor(stored='changed'), 'cs') is False
    assert fa._fabric_inputs_still_bound(None, ancestor(), 'other-cs') is False
    assert fa._fabric_inputs_still_bound(None, ancestor(provenance='FORMAL_GENERATION'), 'cs') is False

    def blocked(*args, **kwargs):
        raise approved.ApprovedGenerationBlocked('inputs no longer approved')
    monkeypatch.setattr(approved, '_load_approved_inputs', blocked)
    assert fa._fabric_inputs_still_bound(None, ancestor(), 'cs') is False
