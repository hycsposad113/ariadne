"""Bounded W6 API rehearsal on a fresh mode=ro SQLite backup only."""
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import shape
from urban_design.scenario_api import register_scenario_routes
from urban_design.store import ProjectStateStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_environment_plan_approval import _key

AUTHORITY = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')
EXPECTED = '2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366'

def run(output):
    output.mkdir(exist_ok=False, parents=True)
    assert hashlib.sha256(AUTHORITY.read_bytes()).hexdigest() == EXPECTED
    scratch = Path(tempfile.mkdtemp(prefix='w6-r2-drill-', dir='/private/tmp'))
    with sqlite3.connect(f'file:{AUTHORITY}?mode=ro', uri=True) as source:
        with sqlite3.connect(scratch / 'state.sqlite3') as target:
            source.backup(target)
    (output / 'copy-receipt.json').write_text(json.dumps({'scratch': str(scratch), 'authority_sha256': EXPECTED}, indent=2))
    # Synthetic fixture credentials, confined to the disposable copy. Never export requests containing them.
    secret, key_path = _key(scratch)
    store = ProjectStateStore(scratch / 'state.sqlite3')
    app = FastAPI()
    register_scenario_routes(app, store, scratch / 'artifacts', decision_key_path=key_path)
    client = TestClient(app)
    def record(name, response, allowed=(200, 201)):
        document = {'http_status': response.status_code, 'body': response.json()}
        (output / (name + '.json')).write_text(json.dumps(document, indent=2))
        assert response.status_code in allowed, f'{name}: {response.status_code}: {response.text}'
        return response.json()
    try:
        scenarios = store.list_current('DesignScenario')
        selected = next(r for r in scenarios if r.payload['parameters'].get('recipe_id') == 'grid-mixed')
        ids = [r.entity_id for r in scenarios]
        record('01-select', client.post('/api/v1/scenarios/comparison/decision', json={
            'project_id': selected.project_id, 'scenario_ids': ids,
            'accepted_scenario_id': selected.entity_id, 'acceptance_reason': 'Disposable copy rehearsal only',
            'rejected_reasons': {i: 'Disposable comparison alternative' for i in ids if i != selected.entity_id},
            'decision_key': secret, 'actor_session_id': 'w6-r2-test-session'}))
        draft = record('02-formal-draft', client.post(f'/api/v1/scenarios/{selected.entity_id}/formal-draft'))
        draft_id = draft['scenario_id']
        building = next(b for b in draft['editor']['editable_buildings'] if len(b['floors']) > 1 and all(shape(f['geometry']).geom_type == 'Polygon' and not shape(f['geometry']).interiors for f in b['floors']))
        building_id = building['building_id']
        top_floor = max(building['floors'], key=lambda f: f['level'])
        massing = record('03-massing', client.post(f'/api/v1/scenarios/{draft_id}/edits', json={
            'building_id': building_id, 'command': {'type': 'remove_floor', 'floor_id': top_floor['floor_id']},
            'expected_revision': 0, 'idempotency_key': 'rehearsal-remove-floor'}))
        face = record('04-face-state', client.get(f'/api/v1/scenarios/{draft_id}/editing/faces', params={'building_id': building_id}))
        top = next(f for f in face['faces'] if f['kind'] == 'SIDE')
        # Use a source-polygon centroid chord, not an invented site measurement.
        polygon = shape(top['geometry']); minx, miny, maxx, maxy = polygon.bounds
        y = polygon.centroid.y
        record('05-face-split', client.post(f'/api/v1/scenarios/{draft_id}/editing/faces', json={
            'building_id': building_id, 'operation': 'SPLIT_LINE', 'face_id': top['id'],
            'points': [[minx - 1, y], [maxx + 1, y]], 'steps': 1,
            'parent_revision': face['face_revision'], 'expected_scenario_revision': face['scenario_revision'],
            'expected_geometry_hash': face['geometry_hash'], 'idempotency_key': 'rehearsal-face-split'}))
        current = store.current(draft_id)
        graph = current.payload['parameters']['road_graph']
        nodes = {n['node_id']: n for n in graph['nodes']}
        moving = nodes[graph['edges'][0]['start_node_id']]
        edge = next(e for e in graph['edges'] if moving['node_id'] not in (e['start_node_id'], e['end_node_id']))
        start = nodes[edge['start_node_id']]; end = nodes[edge['end_node_id']]
        # Snap to an interior point on a nonincident edge; incident edges are ineligible targets.
        x = (start['x_m'] + end['x_m']) / 2; y = (start['y_m'] + end['y_m']) / 2
        road = record('06-road-snap', client.post(f'/api/v1/scenarios/{draft_id}/road-nodes/{moving["node_id"]}/move', json={
            'x_m': x, 'y_m': y, 'snap_kind': 'NEAREST_POINT', 'target_id': edge['edge_id'],
            'expected_revision': 0, 'idempotency_key': 'rehearsal-road-snap'}))
        assert road['snapped_to_edge_id'] or road['snapped_to_node_id']
        assert road['graph_hash_before'] != road['graph_hash_after']
        dashboard = record('07-dashboard', client.get(f'/api/v1/scenarios/{draft_id}/edits/dashboard', params={'building_id': building_id}))
        parameters = store.current(draft_id).payload['parameters']
        active = parameters.get('active_buildings') or {b['building_id']: b for b in parameters['editable_buildings']}
        gfa = sum(shape(f['geometry']).area for b in active.values() for f in b['floors'])
        assert dashboard['land_basis']['floor_polygon_gfa_m2'] == gfa
        assert dashboard['land_basis']['far'] == gfa / 183591.328
        ids = parameters.get('syntax_result_ids', []) + parameters.get('accessibility_result_ids', []) + parameters.get('e1_result_ids', [])
        (output / '08-analysis-status.json').write_text(json.dumps({
            'related_analysis_ids': ids, 'stale_result_ids': road['stale_result_ids'],
            'status': 'PASS' if ids and set(ids) <= set(road['stale_result_ids']) else 'BLOCKED_NO_SCENARIO_BOUND_ANALYSES',
            'limitation': 'No synthetic result IDs or result records are inserted to manufacture staleness.'}, indent=2))
        return {'scratch': str(scratch), 'draft_id': draft_id, 'gfa_m2': gfa, 'stale_analysis_count': len(road['stale_result_ids'])}
    finally:
        store.close()
        assert hashlib.sha256(AUTHORITY.read_bytes()).hexdigest() == EXPECTED

if __name__ == '__main__':
    print(json.dumps(run(Path(sys.argv[1])), indent=2))
