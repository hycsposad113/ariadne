"""Real dual-runtime fixture and persisted recovery through the E2 API."""
import json
from pathlib import Path

import pytest
from test_e2_execution import authority, approval
from test_e2_weather import PROJECT, PROPOSAL
from urban_design.environment.e2_service import (validate_methods, ScenarioPin, scenario_geometry, E2Plan, readiness)
from urban_design.environment.weather_snapshot import (publish_candidate01, persist_bytes, canonical_bytes, load_weather)
from urban_design.environment.contracts import GroundGridDefinition
from urban_design.store import ProjectStateStore


def test_real_methods_gates_pair_and_restart(authority, monkeypatch):
    store, client, key, root = authority
    snapshot = publish_candidate01(store, 'p', PROPOSAL, PROJECT, root / 'artifacts')
    validation = validate_methods(store, 'p', snapshot.entity_id, root / 'qualification')
    receipt = json.loads(Path(validation.payload['uri']).read_bytes())
    assert receipt['status'] == 'PASS'
    assert receipt['classification'] == 'FIXTURE_ONLY'
    assert receipt['qualification_scope'] == 'EXACT_WEATHER_FIXTURE_ONLY'
    assert receipt['supplier_timing_semantics_proven'] is False
    assert receipt['weather_lineage']['snapshot_id'] == snapshot.entity_id
    assert receipt['weather_lineage']['snapshot_version'] == snapshot.payload['version']
    for cases in receipt['methods'].values():
        assert all(case['weather_lineage'] == receipt['weather_lineage'] for case in cases)
    for method, cases in receipt['methods'].items():
        assert 0 <= cases[1]['value_kwh_m2'] < cases[0]['value_kwh_m2'] <= cases[0]['energy_upper_bound_kwh_m2']
    pins = []
    for i in (0,1):
        features = [{'type':'Feature','properties':{'role':'site_area'},'geometry':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}},
                    {'type':'Feature','properties':{'role':'water'},'geometry':{'type':'Polygon','coordinates':[]}}]
        if i:
            features.append({'type':'Feature','properties':{'role':'new_building','height_m':12,'building_id':'b'},
                             'geometry':{'type':'Polygon','coordinates':[[[6,0],[10,0],[10,10],[6,10],[6,0]]]}})
        doc = {'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:28992'}},'features':features}
        artifact = persist_bytes(store, 'p', root / 'artifacts', 'fixture-geometry', canonical_bytes(doc), mime='application/geo+json')
        store.update(artifact.entity_id, {'crs':'EPSG:28992'})
        scenario = store.create('DesignScenario', {'id':f'scenario-{i}', 'project_id':'p','status':'proposed',
                 'generator':'formal-dictionary-fixture', 'geometry_artifact_id':artifact.entity_id,'geometry_sha256':artifact.payload['sha256'],
                 'site_id':'fixture-site','site_version':'fixture-v1','constraint_set_id':'fixture-constraints','generator_version':'fixture-v1',
                 'parameters':{'validation':{'valid':True}}}, entity_id=f'scenario-{i}', project_id='p')
        pin = ScenarioPin(scenario_id=scenario.entity_id,revision=scenario.revision,geometry_artifact_id=artifact.entity_id,
                          geometry_sha256=artifact.payload['sha256'],environment_sha256='sha256:'+'0'*64)
        _, meta = scenario_geometry(store, pin, 'p')
        pins.append(pin.model_copy(update={'environment_sha256':meta['environment_sha256']}))
    plan = E2Plan(project_id='p',weather_snapshot_id=snapshot.entity_id,weather_bundle_sha256=snapshot.payload['payload_digest'],
        baseline=pins[0],modified=pins[1],grid=GroundGridDefinition(origin_x=0,origin_y=0,spacing_m=5,crs='EPSG:28992',tag='FIXTURE_ONLY'),
        true_north_deg=0,start_month=6,start_day=21,end_month=6,end_day=21,start_hour=9,end_hour=15,
        method_validation_artifact_id=validation.entity_id)
    invalid_plan = plan.model_dump(mode='json')
    invalid_plan['grid']['origin_x'] = float('nan')
    with pytest.raises(ValueError, match='projected metres'):
        E2Plan.model_validate(invalid_plan)
    proposal = client.post('/api/v1/environment/e2/plan' ,json=plan.model_dump(mode='json'))
    assert proposal.status_code == 201, proposal.text
    record = store.current(proposal.json()['plan_artifact_id'])
    request = {'project_id':'p','plan_artifact_id':record.entity_id,'idempotency_key':'real-fixture'}
    assert client.post('/api/v1/environment/e2/simulate',json=request).status_code == 409
    assert not (root / 'e2-jobs.sqlite3').exists()
    assert approval(client,record,key).status_code == 201
    assert readiness(store,record.entity_id,'p')['dispatch_allowed'] is False  # weather approval missing
    assert not (root / 'e2-jobs.sqlite3').exists()
    assert approval(client,snapshot,key).status_code == 201
    assert readiness(store,record.entity_id,'p')['dispatch_allowed'] is True
    # Persisted hash-valid non-object JSON and contradictory attestations
    # must return typed BLOCKED, never READY or an unhandled AttributeError.
    import copy
    from urban_design.environment.e2_service import publish_plan
    from urban_design.environment.weather_snapshot import sha256
    negatives = [(value, 'METHOD_QUALIFICATION_RECEIPT_OBJECT_REQUIRED')
                 for value in (None, [], ['nonmapping'], 'nonmapping', 7, True)]
    for field, value in (('classification', 'FORMAL'),
                         ('supplier_timing_semantics_proven', True),
                         ('supplier_timing_semantics_proven', 0),
                         ('classification', None),
                         ('supplier_timing_semantics_proven', None)):
        bad = copy.deepcopy(receipt)
        if value is None:
            del bad[field]
        else:
            bad[field] = value
        negatives.append((bad, 'METHOD_QUALIFICATION_ATTESTATION_INVALID'))
    failures = []
    for index, (bad, reason) in enumerate(negatives):
        ref = persist_bytes(store, 'p', root / 'FIXTURE_ONLY', 'method-validation', canonical_bytes(bad))
        bad_plan = plan.model_copy(update={'method_validation_artifact_id': ref.entity_id})
        proposal_record = publish_plan(store, bad_plan, root / 'FIXTURE_ONLY')
        assert approval(client, proposal_record, key).status_code == 201
        try:
            denied = readiness(store, proposal_record.entity_id, 'p')
        except AttributeError as exc:
            failures.append((index, 'unhandled AttributeError', str(exc)))
            continue
        if denied != {'status': 'BLOCKED', 'dispatch_allowed': False, 'reasons': [reason]}:
            failures.append((index, denied))
        response = client.post('/api/v1/environment/e2/simulate', json={
            **request, 'plan_artifact_id': proposal_record.entity_id,
            'idempotency_key': 'invalid-receipt-' + str(index)})
        assert response.status_code == 409, response.text
        assert not (root / 'e2-jobs.sqlite3').exists()
    assert failures == [], failures
    # Fresh hash-valid receipts must still fail semantic lineage checks at
    # ready_inputs; all plans/decisions below exist only in this disposable DB.
    import copy
    from urban_design.environment.e2_service import publish_plan
    from urban_design.environment.weather_snapshot import sha256
    for field in ('snapshot_id', 'snapshot_version', 'bundle_sha256', 'source_sha256', 'derived_sha256', 'mapping_sha256'):
        bad = copy.deepcopy(receipt)
        bad['weather_lineage'][field] = 'wrong' if field in ('snapshot_id', 'snapshot_version') else 'sha256:' + '0' * 64
        ref = persist_bytes(store, 'p', root / 'FIXTURE_ONLY', 'method-validation', canonical_bytes(bad))
        bad_plan = plan.model_copy(update={'method_validation_artifact_id': ref.entity_id})
        proposal_record = publish_plan(store, bad_plan, root / 'FIXTURE_ONLY')
        assert approval(client, proposal_record, key).status_code == 201
        denied = readiness(store, proposal_record.entity_id, 'p')
        assert denied['reasons'] == ['METHOD_QUALIFICATION_WEATHER_LINEAGE_INVALID']
        assert not (root / 'e2-jobs.sqlite3').exists()
    # Even with updated artifact bytes and their valid hashes, a fixture case
    # cannot cite a different snapshot than the receipt and approved plan.
    for field in ('snapshot_id', 'snapshot_version', 'bundle_sha256', 'source_sha256', 'derived_sha256', 'mapping_sha256'):
        bad = copy.deepcopy(receipt)
        case = bad['methods']['ladybug_radiance'][0]
        old_digest = sha256(canonical_bytes(case))
        case['weather_lineage'][field] = 'wrong-fixture' if field in ('snapshot_id', 'snapshot_version') else 'sha256:' + '0' * 64
        case_artifact = persist_bytes(store, 'p', root / 'FIXTURE_ONLY', 'method-fixture', canonical_bytes(case))
        bad['fixture_artifacts'] = [({'id': case_artifact.entity_id, 'sha256': case_artifact.payload['sha256']}
                                    if r['sha256'] == old_digest else r) for r in bad['fixture_artifacts']]
        ref = persist_bytes(store, 'p', root / 'FIXTURE_ONLY', 'method-validation', canonical_bytes(bad))
        proposal_record = publish_plan(store, plan.model_copy(update={'method_validation_artifact_id': ref.entity_id}), root / 'FIXTURE_ONLY')
        assert approval(client, proposal_record, key).status_code == 201
        assert readiness(store, proposal_record.entity_id, 'p')['reasons'] == ['METHOD_QUALIFICATION_WEATHER_LINEAGE_INVALID']
        assert not (root / 'e2-jobs.sqlite3').exists()
    # Method qualification drift blocks before any job can be created.
    validation_path = Path(validation.payload['uri'])
    original = validation_path.read_bytes()
    validation_path.write_bytes(b'{}')
    assert readiness(store,record.entity_id,'p')['dispatch_allowed'] is False
    assert not (root / 'e2-jobs.sqlite3').exists()
    validation_path.write_bytes(original)
    result = client.post('/api/v1/environment/e2/simulate',json=request)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['status'] == 'SUCCEEDED', payload
    assert payload['direction_summary']['direction_agreement_by_offset']['0'] is True
    assert all(c['0']['direction'] == 'DECREASED' for c in payload['comparisons'].values())
    assert payload['evidence_validation_status'] == 'validated'
    assert len(store.list_current('ToolExecution',project_id='p')) == 12
    assert len(store.list_current('EvidenceCard',project_id='p')) == 12
    from urban_design.environment.e2_service import PD08_ASSUMPTION_REF
    assert all(PD08_ASSUMPTION_REF in card.payload['assumptions'] for card in store.list_current('EvidenceCard', project_id='p'))
    assert all(e.payload['validation_status'] == 'validated' for e in store.list_current('EvidenceCard',project_id='p'))
    repeated = client.post('/api/v1/environment/e2/simulate',json=request)
    assert repeated.json() == payload
    reopened = ProjectStateStore(root / 'copy.sqlite3')
    try:
        from urban_design.environment.e2_service import read_result
        assert read_result(reopened,payload['job_id'],'p') == payload
    finally:
        reopened.close()
    import urban_design.environment.e2_service as service
    actual_calculate = service.calculate
    revoked = False
    def calculate_then_revoke(*args, **kwargs):
        nonlocal revoked
        values = actual_calculate(*args, **kwargs)
        if not revoked:
            revoked = True
            response = approval(client, record, key, action='Reject', status='rejected')
            assert response.status_code == 201, response.text
        return values
    monkeypatch.setattr(service, 'calculate', calculate_then_revoke)
    unverified = client.post('/api/v1/environment/e2/simulate',json={**request,'idempotency_key':'revoked-plan-fixture'})
    assert unverified.status_code == 200 and unverified.json()['status'] == 'SUCCEEDED'
    assert unverified.json()['evidence_validation_status'] == 'unverified'
    revoked_cards = [c for c in store.list_current('EvidenceCard',project_id='p') if c.payload['result']['status']=='computed' and c.payload['validation_status']=='unverified']
    assert len(revoked_cards) == 12
    assert all(any('EVIDENCE_PROMOTION_BLOCKED' in text for text in c.payload['limitations']) for c in revoked_cards)
    assert approval(client, record, key).status_code == 201
    # A deliberately failing transport exercises failure retention; no fake
    # successful measurement or PASS is supplied.
    import urban_design.environment.e2_service as service
    def failed_calculation(*args, **kwargs):
        raise RuntimeError("TEST_INJECTED_TOOL_FAILURE")
    monkeypatch.setattr(service, 'calculate', failed_calculation)
    failure = client.post('/api/v1/environment/e2/simulate',json={**request,'idempotency_key':'failed-fixture'})
    assert failure.status_code == 200 and failure.json()['status'] == 'FAILED'
    runs = store.list_current('ToolExecution',project_id='p')
    cards = store.list_current('EvidenceCard',project_id='p')
    assert len(runs) == len(cards) == 36
    assert sum(r.payload['status'] == 'FAILED' for r in runs) == 12
    assert sum(c.payload['result']['status'] == 'unavailable' for c in cards) == 12
    assert client.get('/api/v1/environment/e2/results/'+failure.json()['job_id'],params={'project_id':'p'}).json() == failure.json()
    def unknown_calculation(*args, **kwargs):
        raise service.E2Blocked("OUTCOME_UNKNOWN:TEST_CONNECTION_LOST")
    monkeypatch.setattr(service, 'calculate', unknown_calculation)
    unknown = client.post('/api/v1/environment/e2/simulate',json={**request,'idempotency_key':'unknown-fixture'})
    assert unknown.status_code == 200 and unknown.json()['status'] == 'OUTCOME_UNKNOWN'
    assert sum(r.payload['status'] == 'OUTCOME_UNKNOWN' for r in store.list_current('ToolExecution',project_id='p')) == 1
    repeated_unknown = client.post('/api/v1/environment/e2/simulate',json={**request,'idempotency_key':'unknown-fixture'})
    assert repeated_unknown.json() == unknown.json()  # no retry
    assert len(store.list_current('ToolExecution',project_id='p')) == 37
    # Changing a scenario revision invalidates even an approved experiment.
    store.update(pins[1].scenario_id, {'status':'rejected'})
    assert readiness(store,record.entity_id,'p')['dispatch_allowed'] is False
