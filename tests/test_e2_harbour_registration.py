"""Fabric registration contracts; all authority mutations use disposable copies."""
import hashlib
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest
from shapely.geometry import box, mapping

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore

PROJECT = 'rotterdam-m4h-pilot-project'
AUTH = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')


def fixture_plan():
    return dict(schema_version='fab1-plan-v1', crs='EPSG:28992', fabric_id='fabric.harbour_grain',
                site=mapping(box(0, 0, 20, 20)), water=mapping(box(0, 0, 2, 20)),
                buildings=[dict(type='Feature', id='b1', geometry=mapping(box(5, 5, 10, 10)),
                                properties=dict(retained=False, height_m=18.0))])


def test_fabric_geometry_preserves_footprint_and_height():
    from urban_design.environment.harbour_registration import fabric_plan_geometry
    from urban_design.environment.geometry_adapter import formal_scenario_geojson_to_environment
    doc = fabric_plan_geometry(fixture_plan())
    building = doc['features'][2]
    assert building['geometry'] == fixture_plan()['buildings'][0]['geometry']
    assert building['properties']['height_m'] == 18.0
    assert building['properties']['role'] == 'new_building'
    geometry = formal_scenario_geojson_to_environment(doc)
    assert len(geometry.obstacles) == 1
    assert max(p[2] for f in geometry.obstacles[0].faces for p in f) == 18
    assert geometry.public_open_space.area == 335


@pytest.mark.parametrize('fault', ['crs', 'height', 'nan', 'bool', 'missing', 'empty', 'duplicate', 'polygon', 'outside'])
def test_fabric_geometry_rejects_bad_input(fault):
    from urban_design.environment.harbour_registration import fabric_plan_geometry
    doc = fixture_plan()
    if fault == 'crs': doc['crs'] = 'EPSG:4326'
    elif fault == 'height': doc['buildings'][0]['properties']['height_m'] = -1
    elif fault == 'nan': doc['buildings'][0]['properties']['height_m'] = float('nan')
    elif fault == 'bool': doc['buildings'][0]['properties']['height_m'] = True
    elif fault == 'missing': del doc['buildings'][0]['properties']['height_m']
    elif fault == 'empty': doc['buildings'] = []
    elif fault == 'duplicate': doc['buildings'] *= 2
    elif fault == 'polygon': doc['buildings'][0]['geometry'] = {'type':'Point', 'coordinates':[5,5]}
    elif fault == 'outside': doc['buildings'][0]['geometry'] = mapping(box(19,19,25,25))
    with pytest.raises(ValueError): fabric_plan_geometry(doc)


@pytest.fixture
def authority(tmp_path):
    database = tmp_path / 'copy.sqlite3'
    with sqlite3.connect(AUTH.as_uri()+'?mode=ro', uri=True) as source, sqlite3.connect(database) as dest:
        source.backup(dest)
    with sqlite3.connect(database) as con:
        con.execute("DROP TRIGGER IF EXISTS state_versions_append_only_delete")
        con.execute("DROP TRIGGER IF EXISTS ledger_events_append_only_delete")
        con.execute("DELETE FROM state_heads WHERE entity_id LIKE 'formal-fabric-harbour-grain-%' OR entity_id LIKE 'artifact-e2-harbour-%'")
        con.execute("DELETE FROM state_versions WHERE entity_id LIKE 'formal-fabric-harbour-grain-%' OR entity_id LIKE 'artifact-e2-harbour-%'")
        con.execute("DELETE FROM ledger_events WHERE target_id LIKE 'formal-fabric-harbour-grain-%' OR target_id LIKE 'artifact-e2-harbour-%'")
        con.execute("DELETE FROM state_heads WHERE entity_type = 'HumanDecision' AND entity_id IN (SELECT entity_id FROM state_versions WHERE json_extract(payload_json, '$.target_id') LIKE 'formal-fabric-harbour-grain-%')")
        con.execute("DELETE FROM state_versions WHERE entity_type = 'HumanDecision' AND json_extract(payload_json, '$.target_id') LIKE 'formal-fabric-harbour-grain-%'")
        con.execute("""CREATE TRIGGER state_versions_append_only_delete
            BEFORE DELETE ON state_versions
            BEGIN
                SELECT RAISE(ABORT, 'append-only state_versions');
            END""")
        con.execute("""CREATE TRIGGER ledger_events_append_only_delete
            BEFORE DELETE ON ledger_events
            BEGIN
                SELECT RAISE(ABORT, 'append-only ledger_events');
            END""")
        con.commit()
    store = ProjectStateStore(database)
    app = create_workspace_app(store=store, decision_key_path=tmp_path/'nonexistent-key')
    app.state.e2_artifact_root = tmp_path/'artifacts'
    with TestClient(app) as client:
        yield store, client, tmp_path
    store.close()


def test_registration_is_proposed_idempotent_hash_bound_and_no_decision(authority):
    store, client, _ = authority
    before = len(store.list_current('HumanDecision', project_id=PROJECT))
    response = client.post('/api/v1/environment/e2/harbour/register', json={'project_id':PROJECT})
    assert response.status_code == 201, response.text
    result = response.json()
    scenario = store.current(result['scenario_id'])
    assert scenario.payload['status'] == result['status'] == 'proposed'
    assert scenario.payload['parameters']['source_validation']['passed'] is False
    assert scenario.payload['parameters']['validation']['scope'] == 'ENVIRONMENT_GEOMETRY_ONLY'
    artifact = store.current(result['geometry_artifact_id'])
    raw = Path(artifact.payload['uri']).read_bytes()
    assert result['geometry_sha256'] == 'sha256:'+hashlib.sha256(raw).hexdigest()
    assert artifact.payload['crs'] == 'EPSG:28992'
    source = Path(__file__).resolve().parents[1]/'artifacts/fab1/run-8/harbour_grain-plan.json'
    plan = json.loads(source.read_bytes())
    assert len(json.loads(raw)['features']) == len(plan['buildings'])+2
    assert result['source_sha256'] == 'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest()
    second = client.post('/api/v1/environment/e2/harbour/register', json={'project_id':PROJECT})
    assert second.json() == result
    assert store.current(result['scenario_id']).revision == scenario.revision
    assert len(store.list_current('HumanDecision', project_id=PROJECT)) == before
    pin = client.get('/api/v1/environment/e2/scenarios/'+result['scenario_id']+'/pin', params={'project_id':PROJECT})
    assert pin.status_code == 200, pin.text
    assert pin.json()['environment_sha256'] == result['environment_sha256']


def test_registration_refuses_paths_and_wrong_project(authority):
    store, client, _ = authority
    assert client.post('/api/v1/environment/e2/harbour/register',json={'project_id':PROJECT,'path':'/tmp/untrusted'}).status_code == 422
    assert client.post('/api/v1/environment/e2/harbour/register',json={'project_id':'other'}).status_code == 409


def test_registration_rejects_source_drift_without_writes(authority, monkeypatch):
    from urban_design.environment import harbour_registration as registration
    store, client, root = authority
    changed = root/'changed.json'
    changed.write_text(json.dumps(fixture_plan()))
    monkeypatch.setattr(registration, 'HARBOUR_PLAN', changed)
    count = len(store.list_current('DesignScenario', project_id=PROJECT))
    assert client.post('/api/v1/environment/e2/harbour/register',json={'project_id':PROJECT}).status_code == 409
    assert len(store.list_current('DesignScenario', project_id=PROJECT)) == count


def test_demolished_retained_missing_height_is_excluded_with_evidence():
    from urban_design.environment.harbour_registration import fabric_plan_geometry
    from urban_design.environment.geometry_adapter import formal_scenario_geojson_to_environment
    doc = fixture_plan()
    doc['buildings'][0]['properties'] = {'retained':True, 'source_record':{'bag_status':'Pand gesloopt', 'floor_count_lower':0, 'floor_count_upper':0}}
    result = formal_scenario_geojson_to_environment(fabric_plan_geometry(doc))
    assert not result.obstacles
    assert len(result.excluded_obstacles) == 1
    assert 'demolished' in result.excluded_obstacles[0]['reason']


def test_proposed_accept_only_via_keyed_decision_and_registration_retains_acceptance(authority):
    from urban_design.decision_key import initialize_decision_key
    from urban_design.environment.harbour_registration import register_harbour
    store, _, root = authority
    result = register_harbour(store, PROJECT, root/'artifacts')
    key = 'test-only-e2-harbour-disposable-passphrase'
    key_path = initialize_decision_key(path=root/'key', password_prompt=lambda _:key)
    app = create_workspace_app(store=store, decision_key_path=key_path)
    request = dict(target_id=result['scenario_id'], target_type='DesignScenario', target_version=str(result['revision']),
                   target_geometry_sha256=result['geometry_sha256'], action='Accept', status='accepted',
                   reason='COPY ONLY selected harbour for E2', actor_session_id='e2-test',decision_key=key)
    with TestClient(app) as client:
        invalid = client.post(f'/api/v1/projects/{PROJECT}/decisions', json={**request,'decision_key':'incorrect'})
        assert invalid.status_code == 403
        response = client.post(f'/api/v1/projects/{PROJECT}/decisions', json=request)
        assert response.status_code == 201, response.text
        accepted = store.current(result['scenario_id'])
        assert accepted.payload['status'] == 'accepted'
        repeated = register_harbour(store, PROJECT, root/'artifacts')
        assert repeated['status'] == 'accepted'
        assert repeated['revision'] == accepted.revision
        assert repeated['geometry_sha256'] == result['geometry_sha256']


@pytest.mark.parametrize('outcome', ['success', 'unknown', 'compare_failed', 'already_accepted'])
def test_formal_script_stops_unknown_and_checks_compare(monkeypatch, capsys, outcome):
    import scripts.e2_harbour_formal_run as script
    import urllib.error
    h = 'sha256:'+'a'*64
    def pin(identifier, revision=2):
        return dict(scenario_id=identifier,revision=revision,geometry_artifact_id='artifact-'+identifier,
                    geometry_sha256=h,environment_sha256=h)
    calls = []
    def fake_call(base, method, path, body=None, params=None, timeout=7200):
        calls.append((method,path,body))
        if method == 'GET':
            if '/weather/' in path: return 200,dict(snapshot_id=script.SNAPSHOT,status='approved',payload_digest=h)
            if '/readiness' in path: return 200,dict(dispatch_allowed=True)
            return 200,pin(script.MIXED if script.MIXED in path else 'harbour-test')
        if path.endswith('/register'):
            return 201,dict(scenario_id='harbour-test',status='accepted' if outcome=='already_accepted' else 'proposed',source_sha256=h,
                            source_validation={'passed':False,'failure_ids':['RETAIN_ORIGINAL_FAIL']})
        if path.endswith('/decisions'): return 201,dict(id='test-decision')
        if path.endswith('/plan'):
            assert body['baseline']['scenario_id'] == script.MIXED
            assert body['modified']['scenario_id'] == 'harbour-test'
            assert body['method_validation_artifact_id'] == script.METHOD_VALIDATION
            return 201,dict(plan_artifact_id='plan',sha256=h,version='1')
        if path.endswith('/simulate'):
            assert body['idempotency_key'] == script.IDEMPOTENCY_KEY
            if outcome == 'unknown': raise urllib.error.URLError('secret-must-not-print')
            return 200,dict(status='SUCCEEDED',job_id='job1')
        if path.endswith('/compare'):
            return (409,{'detail':'blocked'}) if outcome=='compare_failed' else (200,dict(status='SUCCEEDED',job_id='job1',direction_summary={}))
        raise AssertionError(path)
    monkeypatch.setattr(script,'call',fake_call)
    monkeypatch.setattr('sys.argv',['e2_harbour_formal_run.py'])
    monkeypatch.setattr('builtins.input',lambda _: 'y')
    monkeypatch.setattr(script.getpass,'getpass',lambda _: 'test-only-never-print')
    if outcome=='success': script.main()
    else:
        with pytest.raises(SystemExit) as stopped: script.main()
        assert stopped.value.code == (3 if outcome=='unknown' else 2)
    output = capsys.readouterr().out
    assert 'test-only-never-print' not in output and 'secret-must-not-print' not in output
    assert sum(path.endswith('/simulate') for _,path,_ in calls) == (0 if outcome=='already_accepted' else 1)
    if outcome in {'unknown','already_accepted'}: assert not any(path.endswith('/compare') for _,path,_ in calls)
    if outcome=='already_accepted': assert not any(path.endswith('/decisions') or path.endswith('/plan') for _,path,_ in calls)
    if outcome!='success': assert '計算及比較完成' not in output


def test_normal_draft_cannot_use_harbour_exception(authority):
    from urban_design.models import ActorKind, DecisionAction, HumanDecision, HumanStatus
    from urban_design.store import PayloadError
    from urban_design.decision_key import initialize_decision_key
    from datetime import datetime, timezone
    store, _, root = authority
    store.create('DesignScenario',{'id':'ordinary-draft','project_id':PROJECT,'status':'draft',
                                 'geometry_sha256':'sha256:'+'a'*64},entity_id='ordinary-draft',project_id=PROJECT)
    key='test-only-normal-draft'
    key_path=initialize_decision_key(path=root/'key-normal',password_prompt=lambda _:key)
    decision=HumanDecision(id='test-decision',project_id=PROJECT,target_id='ordinary-draft',target_type='DesignScenario',
                           target_version='1',target_geometry_sha256='sha256:'+'a'*64,
                           action=DecisionAction.ACCEPT,status=HumanStatus.ACCEPTED,actor='designer',
                           actor_kind=ActorKind.HUMAN_UI,actor_session_id='test',reason='copy only',timestamp=datetime.now(timezone.utc))
    with pytest.raises(PayloadError,match='not a proposed'):
        store.record_human_decision(decision,decision_key=key,decision_key_path=key_path)
