"""E2 real dispatch/promotion refusal under plan or snapshot revocation."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from test_e2_execution import authority, approval
from test_e2_weather import PROJECT, PROPOSAL
from urban_design.environment.e2_service import E2Plan, ScenarioPin, publish_plan, validate_methods, scenario_geometry
from urban_design.environment.weather_snapshot import publish_candidate01, persist_bytes, canonical_bytes
from urban_design.environment.contracts import GroundGridDefinition


def setup_e2(authority):
    store,client,key,root=authority
    weather=publish_candidate01(store,'p',PROPOSAL,PROJECT,root/'artifacts')
    qualification=validate_methods(store,'p',weather.entity_id,root/'qualification')
    pins=[]
    for index in range(2):
        features=[{'type':'Feature','properties':{'role':'site_area'},'geometry':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}},
                  {'type':'Feature','properties':{'role':'water'},'geometry':{'type':'Polygon','coordinates':[]}}]
        if index:
            features.append({'type':'Feature','properties':{'role':'new_building','height_m':12,'building_id':'b'},
                             'geometry':{'type':'Polygon','coordinates':[[[6,0],[10,0],[10,10],[6,10],[6,0]]]}})
        geometry={'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:28992'}},'features':features}
        artifact=persist_bytes(store,'p',root/'artifacts','FIXTURE_ONLY-geometry',canonical_bytes(geometry),mime='application/geo+json')
        store.update(artifact.entity_id,{'crs':'EPSG:28992'})
        row=store.create('DesignScenario',{'id':f'j2-fixture-{index}','project_id':'p','status':'proposed',
            'generator':'formal-dictionary-fixture','geometry_artifact_id':artifact.entity_id,'geometry_sha256':artifact.payload['sha256'],
            'site_id':'fixture-site','site_version':'fixture-v1','constraint_set_id':'fixture-constraints','generator_version':'fixture-v1',
            'parameters':{'validation':{'valid':True}}},entity_id=f'j2-fixture-{index}',project_id='p')
        pin=ScenarioPin(scenario_id=row.entity_id,revision=row.revision,geometry_artifact_id=artifact.entity_id,
            geometry_sha256=artifact.payload['sha256'],environment_sha256='sha256:'+'0'*64)
        _,meta=scenario_geometry(store,pin,'p')
        pins.append(pin.model_copy(update={'environment_sha256':meta['environment_sha256']}))
    plan=E2Plan(project_id='p',weather_snapshot_id=weather.entity_id,weather_bundle_sha256=weather.payload['payload_digest'],
        baseline=pins[0],modified=pins[1],grid=GroundGridDefinition(origin_x=0,origin_y=0,spacing_m=5,crs='EPSG:28992',tag='FIXTURE_ONLY'),
        true_north_deg=0,start_month=6,start_day=21,end_month=6,end_day=21,start_hour=9,end_hour=15,
        method_validation_artifact_id=qualification.entity_id)
    record=publish_plan(store,plan,root/'artifacts')
    assert approval(client,record,key).status_code==201
    assert approval(client,weather,key).status_code==201
    return record,weather,{'project_id':'p','plan_artifact_id':record.entity_id,'idempotency_key':'j2-negative'}


@pytest.mark.parametrize('revoked',['plan','weather'])
def test_actual_e2_dispatch_reject_blocks_without_job(authority,revoked):
    store,client,key,root=authority
    plan,weather,body=setup_e2(authority)
    response=approval(client,plan if revoked=='plan' else weather,key,action='Reject',status='rejected')
    assert response.status_code==201,response.text
    result=client.post('/api/v1/environment/e2/simulate',json=body)
    assert result.status_code==409,result.text
    assert 'APPROVAL_BINDING_INVALID:Reject' in result.json()['detail']['reason']
    assert not (root/'e2-jobs.sqlite3').exists()
    assert not store.list_current('ToolExecution')
    assert not store.list_current('EvidenceCard')


def test_actual_e2_promotion_reject_between_check_and_transaction(authority,monkeypatch):
    store,client,key,root=authority
    plan,weather,body=setup_e2(authority)
    original=store.update
    injected=[]
    def update(entity_id,payload,**kwargs):
        if kwargs.get('action')=='PromoteE2Evidence' and not injected:
            from datetime import datetime, timezone
            from urban_design.models import HumanDecision, ActorKind
            store.record_human_decision(HumanDecision(id='j2-race-reject',project_id='p',
                target_id=plan.entity_id,target_type='Artifact',target_version=str(plan.revision),
                target_artifact_sha256=plan.payload['sha256'],action='Reject',status='rejected',
                actor='test-founder',actor_kind=ActorKind.HUMAN_UI,actor_session_id='j2-test',
                reason='FIXTURE_ONLY promotion race',timestamp=datetime.now(timezone.utc)),
                decision_key=key,decision_key_path=root/'test-key')
            check=kwargs['before_commit']
            def transactional_check():
                with store.locked_connection() as connection:
                    assert connection.in_transaction
                injected.append(True)
                check()
            kwargs['before_commit']=transactional_check
        return original(entity_id,payload,**kwargs)
    monkeypatch.setattr(store,'update',update)
    response=client.post('/api/v1/environment/e2/simulate',json=body)
    assert response.status_code==200,response.text
    assert injected==[True]
    cards=store.list_current('EvidenceCard')
    assert cards and all(c.payload['validation_status']=='unverified' for c in cards)
    assert any('EVIDENCE_PROMOTION_BLOCKED:' in str(c.payload['limitations']) for c in cards)
    assert store.list_current('ToolExecution')
    assert len(store.list_current('HumanDecision'))==3
