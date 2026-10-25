"""Approval and engine regression probes; disposable state only."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_environment_plan_approval import _key, _store, _python_runtime
from urban_design.environment.plan_service import persist_e1_plan_artifact, approve_plan_artifact
from urban_design.environment.router import router, get_default_draft_plan

def approved_client(tmp_path, monkeypatch, pair):
    _python_runtime(monkeypatch)
    store = _store(tmp_path)
    secret, path = _key(tmp_path)
    plan = get_default_draft_plan().model_copy(update={
        'baseline_scenario_id': pair[0], 'modified_scenario_id': pair[1]})
    record = persist_e1_plan_artifact(store, plan, 'project-e1')
    approve_plan_artifact(store, record.entity_id, decision_key=secret,
        decision_key_path=path, actor='test-designer', actor_session_id='test-session',
        reason='Synthetic review of exact plan; not production approval')
    app = FastAPI(); app.state.project_store=store; app.include_router(router)
    return store, TestClient(app), record

def test_approved_plan_cannot_substitute_scenario_pair(tmp_path, monkeypatch):
    store, client, record = approved_client(tmp_path, monkeypatch, ('formal-proposal', 'formal-baseline'))
    with client:
        result = client.post('/api/environment/e1/simulate', json={
            'project_id':'project-e1','baseline_scenario_id':'formal-baseline',
            'modified_scenario_id':'formal-proposal','plan_artifact_id':record.entity_id})
    assert result.status_code == 409, result.text
    assert result.json()['detail'] == 'APPROVED_PLAN_SCENARIO_PAIR_MISMATCH'
    assert store.list_current('ToolExecution',project_id='project-e1') == []
    store.close()

def test_approved_plan_requires_radiance_no_validated_fallback(tmp_path, monkeypatch):
    store, client, record = approved_client(tmp_path, monkeypatch, ('formal-baseline','formal-proposal'))
    with client:
        result = client.post('/api/environment/e1/simulate', json={
            'project_id':'project-e1','baseline_scenario_id':'formal-baseline',
            'modified_scenario_id':'formal-proposal','plan_artifact_id':record.entity_id})
    assert result.status_code == 409, result.text
    assert 'RADIANCE_REQUIRED_FOR_APPROVED_PLAN' in result.json()['detail']
    assert store.list_current('ToolExecution',project_id='project-e1') == []
    assert store.list_current('EvidenceCard',project_id='project-e1') == []
    store.close()


def test_approved_plan_rejects_scenario_revision_drift(tmp_path, monkeypatch):
    store, client, record = approved_client(tmp_path, monkeypatch, ('formal-baseline', 'formal-proposal'))
    store.update('formal-baseline', {'name': 'Revised after approval'}, reason='Disposable drift probe')
    with client:
        response = client.post('/api/environment/e1/simulate', json={
            'project_id': 'project-e1', 'baseline_scenario_id': 'formal-baseline',
            'modified_scenario_id': 'formal-proposal', 'plan_artifact_id': record.entity_id})
    assert response.status_code == 409, response.text
    assert response.json()['detail'] == 'APPROVED_PLAN_INPUT_DRIFT'
    assert not (tmp_path / 'e1-jobs.sqlite3').exists()
    assert store.list_current('ToolExecution', project_id='project-e1') == []
    store.close()


def test_unbound_draft_cannot_receive_execution_approval(tmp_path):
    import pytest
    from urban_design.environment.plan_service import PlanNotApproved
    store = _store(tmp_path)
    secret, path = _key(tmp_path)
    record = persist_e1_plan_artifact(store, get_default_draft_plan(), 'project-e1')
    before = len(store.events(project_id='project-e1'))
    with pytest.raises(PlanNotApproved, match='APPROVED_PLAN_INPUT_BINDINGS_REQUIRED'):
        approve_plan_artifact(store, record.entity_id, decision_key=secret,
            decision_key_path=path, actor='test-designer', actor_session_id='test-session',
            reason='Disposable approval of an unbound draft must fail')
    assert len(store.events(project_id='project-e1')) == before
    assert store.list_current('HumanDecision', project_id='project-e1') == []
    store.close()


def test_changed_plan_hash_cannot_reuse_old_decision(tmp_path, monkeypatch):
    from urban_design.environment.contracts import E1ExperimentPlan
    from urban_design.environment.plan_service import plan_content_sha256, approved_plan, PlanNotApproved
    import pytest
    store, client, record = approved_client(tmp_path, monkeypatch, ('formal-baseline', 'formal-proposal'))
    assert approved_plan(store, record.entity_id, 'project-e1').sha256 == record.payload['sha256']
    plan = E1ExperimentPlan.model_validate(record.payload['plan'])
    changed = plan.model_copy(update={'notes': plan.notes + ' changed after approval'})
    new_hash = plan_content_sha256(changed)
    assert new_hash != record.payload['sha256']
    store.update(record.entity_id, {'plan': changed.model_dump(mode='json'), 'sha256': new_hash},
        reason='Disposable tamper probe: a new artifact revision cannot inherit approval')
    with pytest.raises(PlanNotApproved, match='PLAN_NOT_APPROVED'):
        approved_plan(store, record.entity_id, 'project-e1')
    response = client.post('/api/environment/e1/simulate', json={
        'project_id': 'project-e1', 'baseline_scenario_id': 'formal-baseline',
        'modified_scenario_id': 'formal-proposal', 'plan_artifact_id': record.entity_id})
    assert response.status_code == 409, response.text
    assert response.json()['detail'] == 'PLAN_NOT_APPROVED'
    assert store.list_current('ToolExecution', project_id='project-e1') == []
    store.close()
