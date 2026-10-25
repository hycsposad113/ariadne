"""J2 negative probes exercise actual dispatch, authority and promotion paths."""
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.models import ActorKind, DecisionAction, HumanDecision, HumanStatus
from urban_design.decision_resolution import resolve_record_decision
from urban_design.environment.plan_service import persist_e1_plan_artifact, approved_plan, PlanNotApproved
from urban_design.environment.router import get_default_draft_plan, router, _approved_handler
from urban_design.week7.jobs import execute_e1_rerun
from urban_design.week7.service import Week7Refusal
from test_environment_plan_approval import _store, _key
from test_scenario_comparison_router import _setup_test_env


def decide(store, record, key, path, action, identifier, year):
    field = 'target_geometry_sha256' if record.entity_type == 'DesignScenario' else 'target_artifact_sha256'
    digest = record.payload['geometry_sha256' if record.entity_type == 'DesignScenario' else 'sha256']
    status = {'Approve': 'approved', 'Reject': 'rejected', 'Accept': 'accepted', 'Reconsider': 'not_reviewed'}[action]
    decision = HumanDecision(id=identifier, project_id=record.project_id, target_id=record.entity_id,
        target_type=record.entity_type, target_version=str(record.revision), **{field: digest},
        action=action, status=status, actor='test-founder', actor_kind=ActorKind.HUMAN_UI,
        actor_session_id='j2-test', reason='FIXTURE_ONLY decision probe', timestamp=datetime(year,1,1,tzinfo=timezone.utc))
    return store.record_human_decision(decision, decision_key=key, decision_key_path=path)


def plan_fixture(tmp_path):
    store = _store(tmp_path)
    key, path = _key(tmp_path)
    plan = get_default_draft_plan().model_copy(update={'baseline_scenario_id':'formal-baseline','modified_scenario_id':'formal-proposal'})
    record = persist_e1_plan_artifact(store, plan, 'project-e1')
    return store, key, path, record


def test_ledger_order_actual_e1_and_w7_dispatch(tmp_path):
    store, key, path, record = plan_fixture(tmp_path)
    try:
        decide(store,record,key,path,'Approve','z-old',2030)
        decide(store,record,key,path,'Reject','y-reject',2029)
        with pytest.raises(PlanNotApproved):
            approved_plan(store,record.entity_id,record.project_id)
        app=FastAPI();app.state.project_store=store;app.include_router(router)
        body={'project_id':'project-e1','baseline_scenario_id':'formal-baseline','modified_scenario_id':'formal-proposal','plan_artifact_id':record.entity_id}
        response=TestClient(app).post('/api/environment/e1/simulate',json=body)
        assert response.status_code==409 and response.json()['detail']=='PLAN_NOT_APPROVED'
        with pytest.raises(Week7Refusal, match='E1_PLAN_NOT_APPROVED'):
            execute_e1_rerun(SimpleNamespace(store=store), SimpleNamespace(project_id='project-e1'),SimpleNamespace(**body),None)
        assert not store.list_current('ToolExecution')
        assert not (tmp_path/'e1-jobs.sqlite3').exists()
        decide(store,record,key,path,'Approve','a-new',2020)
        assert approved_plan(store,record.entity_id,record.project_id).decision_id=='a-new'
    finally:
        store.close()


def test_actual_e1_handler_reject_after_approval_before_dispatch(tmp_path):
    store,key,path,record=plan_fixture(tmp_path)
    try:
        decision=decide(store,record,key,path,'Approve','z-old',2030)
        job=SimpleNamespace(request={'project_id':'project-e1','plan_artifact_id':record.entity_id,'decision_id':decision.entity_id},input_refs=[{'sha256':record.payload['sha256']}])
        decide(store,record,key,path,'Reject','a-reject',2020)
        with pytest.raises(PlanNotApproved):
            _approved_handler(store)(job,tmp_path,SimpleNamespace(cancelled=False))
        assert not store.list_current('ToolExecution')
    finally:store.close()


def test_reconsider_actual_comparison_api_and_old_accept_never_revives(tmp_path):
    store,client,key,path,sids,digest=_setup_test_env(tmp_path)
    body={'project_id':'proj-formal','scenario_ids':sids,'accepted_scenario_id':sids[0],
          'acceptance_reason':'FIXTURE_ONLY first selection','rejected_reasons':{s:'FIXTURE_ONLY reject' for s in sids[1:]},
          'decision_key':key,'actor_session_id':'j2-test'}
    try:
        first=client.post('/api/v1/scenarios/comparison/decision',json=body)
        assert first.status_code==201,first.text
        for sid in sids:
            row=store.current(sid)
            request={'project_id':'proj-formal','scenario_id':sid,'target_version':str(row.revision),
                     'target_geometry_sha256':digest,'reason':'FIXTURE_ONLY reconsider','decision_key':key,'actor_session_id':'j2-test'}
            before=len(store.events())
            wrong=client.post('/api/v1/scenarios/reconsider',json={**request,'decision_key':'incorrect-test-secret'})
            assert wrong.status_code==403
            assert len(store.events())==before
            response=client.post('/api/v1/scenarios/reconsider',json=request)
            assert response.status_code==201,response.text
            current=store.current(sid)
            assert current.payload['status']=='proposed' and current.payload['baseline'] is False
            resolved=resolve_record_decision(store,current,digest,'target_geometry_sha256')
            assert resolved.reason=='Reconsider' and resolved.decision.entity_id!=first.json()['baseline_decision_id']
        comparison=client.post('/api/v1/scenarios/comparison',json={'scenario_ids':sids}).json()
        assert all(s['status']=='proposed' and s['is_baseline'] is False for s in comparison['scenarios'])
        second=client.post('/api/v1/scenarios/comparison/decision',json=body)
        assert second.status_code==201,second.text
        assert second.json()['baseline_decision_id']!=first.json()['baseline_decision_id']
        row=store.current(sids[0])
        assert resolve_record_decision(store,row,digest,'target_geometry_sha256').decision.entity_id==second.json()['baseline_decision_id']
        assert len(store.history(sids[0]))==4
    finally:store.close()


def test_parent_revision_without_named_transition_cannot_inherit(tmp_path):
    store,client,key,path,sids,digest=_setup_test_env(tmp_path)
    try:
        row=store.current(sids[0]);decide(store,row,key,path,'Accept','accept-fixture',2020)
        accepted=store.current(row.entity_id)
        assert resolve_record_decision(store,accepted,digest,'target_geometry_sha256').reason=='Accept'
        revised=store.update(row.entity_id,{'name':'arbitrary revision'},reason='FIXTURE_ONLY generic update')
        assert resolve_record_decision(store,revised,digest,'target_geometry_sha256').status=='BLOCKED'
    finally:store.close()


def test_e1_promotion_transaction_rechecks_after_reject_and_retains_history(tmp_path, monkeypatch):
    store,key,path,record=plan_fixture(tmp_path)
    try:
        decide(store,record,key,path,'Approve','z-old',2030)
        original=store.update
        injected=[]
        def update(entity_id,payload,**kwargs):
            if kwargs.get('action')=='PromoteE1Evidence':
                decide(store,record,key,path,'Reject','a-reject',2020)
                check=kwargs['before_commit']
                def transactional_check():
                    with store.locked_connection() as connection:
                        assert connection.in_transaction is True
                    injected.append(True)
                    check()
                kwargs['before_commit']=transactional_check
            return original(entity_id,payload,**kwargs)
        monkeypatch.setattr(store,'update',update)
        app=FastAPI();app.state.project_store=store;app.include_router(router)
        response=TestClient(app).post('/api/environment/e1/simulate',json={
            'project_id':'project-e1','baseline_scenario_id':'formal-baseline',
            'modified_scenario_id':'formal-proposal','plan_artifact_id':record.entity_id})
        assert response.status_code==409,response.text
        assert injected==[True]
        cards=store.list_current('EvidenceCard')
        assert len(cards)==1 and cards[0].payload['validation_status']=='unverified'
        assert len(store.history(cards[0].entity_id))==1
        assert len(store.list_current('ToolExecution'))==1
        assert store.get_record('z-old').payload['action']=='Approve'
        assert store.get_record('a-reject').payload['action']=='Reject'
    finally:store.close()


def test_formal_draft_pipeline_blocks_after_reconsider_and_generic_parent(tmp_path):
    from test_formal_editor_authority import _world, _accept
    store,client,key,path,sids,digest=_world(tmp_path)
    try:
        _accept(client,key,sids)
        assert client.post(f'/api/v1/scenarios/{sids[0]}/formal-draft').status_code==201
        row=store.current(sids[0])
        request={'project_id':row.project_id,'scenario_id':row.entity_id,'target_version':str(row.revision),
                 'target_geometry_sha256':digest,'reason':'FIXTURE_ONLY reconsider','decision_key':key,'actor_session_id':'j2-test'}
        assert client.post('/api/v1/scenarios/reconsider',json=request).status_code==201
        refused=client.post(f'/api/v1/scenarios/{sids[0]}/formal-draft')
        assert refused.status_code==409 and 'PROPOSED' in refused.text
        row=store.current(sids[0]);decide(store,row,key,path,'Accept','new-accept',2020)
        assert client.post(f'/api/v1/scenarios/{sids[0]}/formal-draft').status_code==201
        store.update(row.entity_id,{'name':'generic parent drift'})
        refused=client.post(f'/api/v1/scenarios/{sids[0]}/formal-draft')
        assert refused.status_code==409 and 'PROPOSED' in refused.text
    finally:store.close()


def test_w7_view_requires_exact_named_transition(tmp_path):
    from tests.week7_support import seed_project_database
    from urban_design.store import ProjectStateStore
    from urban_design.week7.real_service import RealWeek7Service
    database=seed_project_database(tmp_path/'w7-fixture.sqlite3')
    key,path=_key(tmp_path)
    with ProjectStateStore(database) as store:
        ws=store.list_current('WorkspaceRevision')[0]
        row=store.list_current('DesignScenario',project_id=ws.project_id)[0]
        decide(store,row,key,path,'Accept','w7-test-accept',2020)
        service=RealWeek7Service(store)
        assert service.view(ws.entity_id,row.entity_id)['human_status']=='ACCEPTED'
        store.update(row.entity_id,{'name':'generic revision cannot inherit'})
        assert service.view(ws.entity_id,row.entity_id)['human_status']=='NOT_ACCEPTED'


def test_missing_latest_reject_event_blocks_actual_dispatch_not_old_approval(tmp_path):
    store,key,path,record=plan_fixture(tmp_path)
    try:
        decide(store,record,key,path,'Approve','z-old',2030)
        rejected=decide(store,record,key,path,'Reject','a-reject',2020)
        # Deliberately corrupt only disposable persistence; never production.
        with store.locked_connection() as connection:
            connection.execute('DROP TRIGGER IF EXISTS ledger_events_append_only_delete')
            connection.execute('DELETE FROM ledger_events WHERE event_id=?',(rejected.event_id,))
            connection.commit()
        app=FastAPI();app.state.project_store=store;app.include_router(router)
        response=TestClient(app).post('/api/environment/e1/simulate',json={
            'project_id':'project-e1','baseline_scenario_id':'formal-baseline',
            'modified_scenario_id':'formal-proposal','plan_artifact_id':record.entity_id})
        assert response.status_code==409,response.text
        assert not store.list_current('ToolExecution')
        assert not (tmp_path/'e1-jobs.sqlite3').exists()
    finally:store.close()


@pytest.mark.parametrize('replacement',['Reject','Approve'])
def test_actual_w7_rerun_changed_decision_aborts_promotion_even_same_plan_sha(tmp_path,monkeypatch,replacement):
    from urban_design.week7.real_service import RealWeek7Service
    from urban_design.generation.job_store import GenerationJobStore
    store,key,path,record=plan_fixture(tmp_path)
    try:
        decide(store,record,key,path,'Approve','z-old',2030)
        from urban_design.geometry import canonical_geometry_hash
        from urban_design.workspace_contracts import WorkspaceRevision
        from urban_design.approved_generation import _workspace_payload_digest
        geometry = {'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,0]]]}
        geometry_hash = canonical_geometry_hash(geometry)
        store.create('StudyArea', {'id':'j2-study','status':'CONFIRMED_FOR_EXPLORATION','geometry_sha256':geometry_hash},entity_id='j2-study',project_id='project-e1')
        workspace = WorkspaceRevision(workspace_id='j2-workspace',project_id='project-e1',study_area_id='j2-study',revision=1,spatial_brief={'exploration_design_area':{'geometry':geometry}})
        payload = workspace.model_dump(mode='json')
        payload['payload_digest'] = _workspace_payload_digest(workspace).removeprefix('sha256:')
        ws=store.create('WorkspaceRevision',payload,entity_id='j2-workspace',project_id='project-e1')
        approval = HumanDecision(id='j2-workspace-approve',project_id='project-e1',target_id=ws.entity_id,target_type='WorkspaceRevision',target_version='1',target_geometry_sha256=geometry_hash,target_payload_digest='sha256:'+payload['payload_digest'],action='Approve',status='approved',actor='test-founder',actor_kind=ActorKind.HUMAN_UI,actor_session_id='j2-test',reason='Synthetic workspace approval for rerun gate',timestamp=datetime(2020,1,1,tzinfo=timezone.utc))
        store.record_human_decision(approval,decision_key=key,decision_key_path=path)
        service=RealWeek7Service(store)
        original=store.update
        changed=[]
        def update(entity_id,payload,**kwargs):
            if kwargs.get('action')=='PromoteE1Evidence':
                decide(store,record,key,path,replacement,'a-new-decision',2020)
                changed.append(True)
            return original(entity_id,payload,**kwargs)
        monkeypatch.setattr(store,'update',update)
        body=SimpleNamespace(plan_artifact_id=record.entity_id,baseline_scenario_id='formal-baseline',modified_scenario_id='formal-proposal',idempotency_key='j2-w7-race')
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(e1_job_database=tmp_path/'j2-w7-jobs.sqlite3')))
        result=execute_e1_rerun(service,ws,body,request)
        assert changed==[True]
        assert result['status']=='FAILED' and result['published_as_current'] is False
        assert store.current(record.entity_id).payload['sha256']==record.payload['sha256']
        cards=store.list_current('EvidenceCard')
        assert len(cards)==1 and cards[0].payload['validation_status']=='unverified'
        assert store.list_current('ToolExecution')
        assert store.current('z-old').payload['action']=='Approve'
        assert store.current('a-new-decision').payload['action']==replacement
    finally:store.close()


@pytest.mark.parametrize('field,value',[
    ('state_revision',None),('target_type','DesignScenario'),('project_id','other-project'),
    ('parent_event_id','unrelated-event'),('action','Approve'),('actor_session_id','wrong-session'),
    ('payload_json','{'),('actor_kind','FORGED_ACTOR'),
])
def test_corrupt_latest_decision_event_blocks_actual_e1_pipeline(tmp_path,field,value):
    store,key,path,record=plan_fixture(tmp_path)
    try:
        decide(store,record,key,path,'Approve','z-old',2020)
        row=decide(store,record,key,path,'Reject','a-reject',2020)
        with store.locked_connection() as connection:
            connection.execute('DROP TRIGGER IF EXISTS ledger_events_append_only_update')
            # Column names are fixed by the test cases, never caller input.
            if field == 'actor_kind':
                import sqlite3
                # Existing SQLite CHECK rejects this corruption before parsing.
                # Keep that gate enabled and prove the attempted write fails.
                with pytest.raises(sqlite3.IntegrityError, match='actor_kind'):
                    connection.execute(f'UPDATE ledger_events SET {field}=? WHERE event_id=?',(value,row.event_id))
            else:
                connection.execute(f'UPDATE ledger_events SET {field}=? WHERE event_id=?',(value,row.event_id))
            connection.commit()
        app=FastAPI();app.state.project_store=store;app.include_router(router)
        response=TestClient(app).post('/api/environment/e1/simulate',json={
            'project_id':'project-e1','baseline_scenario_id':'formal-baseline',
            'modified_scenario_id':'formal-proposal','plan_artifact_id':record.entity_id})
        assert response.status_code==409,response.text
        assert not store.list_current('ToolExecution') and not (tmp_path/'e1-jobs.sqlite3').exists()
    finally:store.close()


@pytest.mark.parametrize('field,value',[
    ('target_type','DesignScenario'),('target_id','unrelated-target'),('target_version','999'),
    ('target_artifact_sha256','sha256:'+'0'*64),('project_id','other-project'),
])
def test_current_scope_state_event_conflict_blocks_actual_e1_pipeline(tmp_path,field,value):
    import json
    store,key,path,record=plan_fixture(tmp_path)
    try:
        decide(store,record,key,path,'Approve','z-old',2020)
        rejected=decide(store,record,key,path,'Reject','a-reject',2020)
        payload=dict(rejected.payload);payload[field]=value
        with store.locked_connection() as connection:
            triggers=connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='state_versions'").fetchall()
            for trigger in triggers:
                connection.execute('DROP TRIGGER "'+trigger[0].replace('"','""')+'"')
            connection.execute('UPDATE state_versions SET payload_json=? WHERE entity_id=?',(json.dumps(payload),rejected.entity_id))
            connection.commit()
        app=FastAPI();app.state.project_store=store;app.include_router(router)
        response=TestClient(app).post('/api/environment/e1/simulate',json={
            'project_id':'project-e1','baseline_scenario_id':'formal-baseline',
            'modified_scenario_id':'formal-proposal','plan_artifact_id':record.entity_id})
        assert response.status_code==409,response.text
        assert not store.list_current('ToolExecution') and not (tmp_path/'e1-jobs.sqlite3').exists()
    finally:store.close()
