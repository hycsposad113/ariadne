"""Real-service projections over synthetic typed fixtures, not actual engine runtime."""
from pathlib import Path
import hashlib
import json
import sqlite3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.store import ProjectStateStore
from urban_design.week7.service import Week7Refusal
from urban_design.models import DecisionAction, HumanStatus, ToolExecution
from tests.week7_support import seed_project_database

from urban_design.week7.real_service import RealWeek7Service, EntityRef
from urban_design.week7.router import create_week7_router
from urban_design.week7.real_figures import render_real_figure

pytest_plugins = ["tests.week7_support"]

@pytest.fixture
def real(tmp_path):
    database=seed_project_database(tmp_path/'fixture.sqlite3')
    with ProjectStateStore(database) as store:
        service=RealWeek7Service(store)
        app=FastAPI();app.include_router(create_week7_router(store))
        yield store,service,TestClient(app),tmp_path

def ids(store):
    ws=store.list_current('WorkspaceRevision')[0]
    scenarios=store.list_current('DesignScenario',project_id=ws.project_id)
    return ws,scenarios

def target(row):
    return {'entity_id':row.entity_id,'revision':row.revision}

def test_real_revision_panels_no_fixture_tables_and_no_forged_values(real):
    store,service,client,_=real;ws,scenarios=ids(store)
    response=client.get(f'/api/v1/week7/workspaces/{ws.entity_id}/view')
    assert response.status_code==200
    body=response.json()
    assert body['scenario_id'] in {r.entity_id for r in scenarios}
    assert body['workspace_ref']['revision']==ws.revision
    assert len({p['revision'] for p in body['panels'].values()})==1
    assert body['revision']==f'{ws.entity_id}@{ws.revision}/{body["scenario_id"]}@1'
    assert body['human_status']=='NOT_ACCEPTED'
    assert body['geometry_valid'] is True
    assert body['evidence_availability']!='complete'
    forged=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/switch',json={
        'target':target(scenarios[1]),'workspace_revision':ws.revision,'results':[{'value':2.2}]})
    assert forged.status_code==422
    with store.locked_connection() as c:
        assert not c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'week7_%'").fetchall()

def test_append_only_contests_fork_no_decisions_or_calculation_changes(real):
    store,service,client,_=real;ws,scenarios=ids(store);row=scenarios[0]
    count=len(store.list_current('HumanDecision'));before=store.current(row.entity_id).to_dict()
    for kind in ['challenge','reject','override']:
        r=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/operations/{kind}',json={'target':target(row),'reason':'test-copy contest'})
        assert r.status_code==200,r.text
        assert r.json()['event']['state_revision']==row.revision
    fork=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/operations/fork',json={'target':target(row),'branch_id':'w7-copy-fork'})
    assert fork.status_code==200,fork.text
    child=store.current('w7-copy-fork')
    assert child.payload['parent_scenario_id']==row.entity_id
    assert child.payload['parameters']['parent_revision']==row.revision
    assert child.payload['status']=='draft'
    assert store.current(row.entity_id).to_dict()==before
    assert len(store.list_current('HumanDecision'))==count
    with store.locked_connection() as c:
        with pytest.raises(sqlite3.DatabaseError):c.execute('DELETE FROM ledger_events')

def test_stale_target_switch_and_compare_existing_contract(real):
    store,service,client,_=real;ws,scenarios=ids(store);a,b=scenarios[:2]
    url=f'/api/v1/week7/workspaces/{ws.entity_id}'
    switched=client.post(url+'/switch',json={'target':target(b),'workspace_revision':ws.revision})
    assert switched.status_code==200,switched.text
    assert switched.json()['scenario_id']==b.entity_id
    stale=client.post(url+'/switch',json={'target':{'entity_id':a.entity_id,'revision':99},'workspace_revision':ws.revision})
    assert stale.status_code==409
    assert service.view(ws.entity_id)['scenario_id']==b.entity_id
    compared=client.post(url+'/operations/compare',json={'target':target(a),'compare_targets':[target(a),target(b)]})
    assert compared.status_code==200,compared.text
    assert compared.json()['status']=='COMPARABLE'

def test_modify_closed_without_acceptance_and_live_transport_denied(real):
    store,service,client,_=real;ws,scenarios=ids(store);row=scenarios[0]
    modified=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/operations/modify',json={'target':target(row)})
    assert modified.status_code==409
    assert modified.json()['detail']['code']=='BLOCKED_ON_W6_DEFECT_A'
    response=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/ai/interpret',json={'transport':'live','scenario_id':row.entity_id})
    assert response.status_code==422
    bad=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/ai/interpret',json={'transport':'fake','scenario_id':row.entity_id,'scripted':{'citations':[{'evidence_id':'not-real'}],'stated_numbers':[999]}})
    assert bad.status_code==200
    assert bad.json()['status']=='INVALID'
    assert 'model_computed_number' in bad.json()['errors']


def test_modify_opens_w6_formal_draft_after_accepted_baseline_and_workspace(tmp_path):
    from shapely.geometry import box, mapping
    from urban_design.approved_generation import _workspace_payload_digest
    from urban_design.api import create_workspace_app
    from urban_design.geometry import canonical_geometry_hash
    from urban_design.workspace_contracts import WorkspaceRevision
    from test_formal_editor_authority import _accept, _decision, _world

    root = tmp_path / 'formal-world'
    root.mkdir()
    store, _formal_client, fixture_key, key_path, scenario_ids, original_hash = _world(root)
    try:
        boundary = mapping(box(0, 0, 100, 100))
        study_geometry_hash = canonical_geometry_hash(boundary)
        study = store.current('study-area-formal')
        store.update(study.entity_id, {'geometry_sha256': study_geometry_hash},
                     expected_revision=study.revision, reason='Isolated test geometry binding')
        store.create('StudyArea', {
            'id': 'w7-wrong-study-area', 'version': '1', 'status': 'CONFIRMED_FOR_EXPLORATION',
            'geometry_sha256': study_geometry_hash,
        }, entity_id='w7-wrong-study-area', project_id='proj-formal')
        _decision(store, fixture_key, key_path, id='decision-study-canonical',
                  project_id='proj-formal', target_id='study-area-formal', target_type='StudyArea',
                  target_version='v5', target_geometry_sha256=study_geometry_hash,
                  action=DecisionAction.APPROVE, status=HumanStatus.APPROVED)
        _accept(_formal_client, fixture_key, scenario_ids)
        workspace = WorkspaceRevision(
            workspace_id='w7-formal-workspace', project_id='proj-formal', revision=1,
            study_area_id='w7-wrong-study-area',
            spatial_brief={'exploration_design_area': {'geometry': boundary}},
        )
        workspace_payload = workspace.model_dump(mode='json')
        workspace_payload['payload_digest'] = _workspace_payload_digest(workspace).removeprefix('sha256:')
        ws = store.create('WorkspaceRevision', workspace_payload, entity_id=workspace.workspace_id,
                          project_id=workspace.project_id)
        app = create_workspace_app(store, decision_key_path=key_path)
        with TestClient(app) as client:
            accepted_workspace = client.post('/api/v1/projects/proj-formal/decisions', json={
                'target_id': ws.entity_id, 'target_type': 'WorkspaceRevision',
                'target_version': str(ws.revision),
                'target_geometry_sha256': canonical_geometry_hash(boundary),
                'target_payload_digest': 'sha256:' + workspace_payload['payload_digest'],
                'action': 'Approve', 'status': 'approved',
                'reason': '隔離測試：確認工作區版本與探索設計範圍。',
                'decision_key': fixture_key, 'actor_session_id': 'w7-test-human-session',
            })
            assert accepted_workspace.status_code == 201, accepted_workspace.text
            parent = store.current(scenario_ids[0])
            parent_before_bad_binding = parent.to_dict()
            bad_binding = client.post(
                f'/api/v1/week7/workspaces/{ws.entity_id}/operations/modify',
                json={'target': {'entity_id': parent.entity_id, 'revision': parent.revision}},
            )
            assert bad_binding.status_code == 409, bad_binding.text
            assert bad_binding.json()['detail']['code'] == 'BLOCKED_ON_W6_DEFECT_A'
            assert store.current(parent.entity_id).to_dict() == parent_before_bad_binding

            corrected_workspace = workspace.model_copy(update={
                'revision': 2, 'study_area_id': study.entity_id,
            })
            corrected_payload = corrected_workspace.model_dump(mode='json')
            corrected_payload['payload_digest'] = _workspace_payload_digest(corrected_workspace).removeprefix('sha256:')
            ws = store.update(ws.entity_id, corrected_payload, expected_revision=ws.revision,
                              reason='Isolated fixture correction to the active StudyArea binding')
            accepted_workspace = client.post('/api/v1/projects/proj-formal/decisions', json={
                'target_id': ws.entity_id, 'target_type': 'WorkspaceRevision',
                'target_version': str(ws.revision),
                'target_geometry_sha256': canonical_geometry_hash(boundary),
                'target_payload_digest': 'sha256:' + corrected_payload['payload_digest'],
                'action': 'Approve', 'status': 'approved',
                'reason': '隔離測試：確認工作區已綁定有效 StudyArea。',
                'decision_key': fixture_key, 'actor_session_id': 'w7-test-human-session',
            })
            assert accepted_workspace.status_code == 201, accepted_workspace.text
            decisions_before_modify = [
                row.to_dict() for row in store.list_current('HumanDecision', project_id='proj-formal')
            ]
            response = client.post(
                f'/api/v1/week7/workspaces/{ws.entity_id}/operations/modify',
                json={'target': {'entity_id': parent.entity_id, 'revision': parent.revision}},
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['status'] == 'FORMAL_DRAFT'
            draft = store.current(result['scenario_ref']['entity_id'])
            assert draft.payload['status'] == 'draft'
            assert draft.payload['parameters']['provenance'] == 'FORMAL_DRAFT'
            assert draft.payload['parent_scenario_id'] == parent.entity_id
            assert draft.payload['parameters']['parent_revision'] == parent.revision
            assert draft.payload['parameters']['parent_geometry_sha256'] == original_hash
            assert [row.to_dict() for row in store.list_current('HumanDecision', project_id='proj-formal')] == decisions_before_modify
            assert draft.payload['parameters']['acceptance_eligible'] is False
            assert draft.payload['parameters']['analysis_eligible'] is False
            assert store.current(parent.entity_id).payload['geometry_sha256'] == original_hash
    finally:
        store.close()


def test_override_pending_event_uses_existing_human_decision_endpoint(tmp_path):
    from urban_design.api import create_workspace_app
    from test_environment_plan_approval import _key

    database = seed_project_database(tmp_path / 'override.sqlite3')
    fixture_key, key_path = _key(tmp_path)
    with ProjectStateStore(database) as store:
        ws, scenarios = ids(store)
        target_row = scenarios[0]
        before_scenario = target_row.to_dict()
        before_cards = [row.to_dict() for row in store.list_current('EvidenceCard', project_id=ws.project_id)]
        app = create_workspace_app(store, decision_key_path=key_path)
        with TestClient(app) as client:
            pending = client.post(
                f'/api/v1/week7/workspaces/{ws.entity_id}/operations/override',
                json={'target': target(target_row), 'reason': '隔離測試：提出覆寫，交由人類審議。'},
            )
            assert pending.status_code == 200, pending.text
            pending_payload = pending.json()
            assert pending_payload['status'] == 'PENDING_FOUNDER_DECISION'
            assert pending_payload['decision_endpoint'] == '/api/v1/projects/rotterdam-m4h-pilot-project/decisions'
            assert len(store.list_current('HumanDecision', project_id=ws.project_id)) == 0
            assert pending_payload['event']['payload']['computed_values_unchanged'] is True

            submission = {
                'target_id': target_row.entity_id, 'target_type': 'DesignScenario',
                'target_version': str(target_row.revision),
                'target_geometry_sha256': target_row.payload['geometry_sha256'],
                'action': 'Override', 'status': 'overridden',
                'reason': '隔離測試：人類確認此覆寫決定。',
                'decision_key': fixture_key, 'actor_session_id': 'w7-human-test-session',
            }
            stale = client.post(
                f'/api/v1/projects/{ws.project_id}/decisions',
                json={**submission, 'target_geometry_sha256': 'sha256:' + '0' * 64},
            )
            assert stale.status_code == 409
            assert len(store.list_current('HumanDecision', project_id=ws.project_id)) == 0
            accepted = client.post(f'/api/v1/projects/{ws.project_id}/decisions', json=submission)
            assert accepted.status_code == 201, accepted.text
            decision = store.current(accepted.json()['id'])
            assert decision.payload['actor_kind'] == 'HUMAN_UI'
            assert decision.payload['action'] == 'Override'
            assert decision.payload['target_version'] == str(target_row.revision)
            assert decision.payload['target_geometry_sha256'] == target_row.payload['geometry_sha256']
            assert store.current(target_row.entity_id).to_dict() == before_scenario
            assert [row.to_dict() for row in store.list_current('EvidenceCard', project_id=ws.project_id)] == before_cards


@pytest.mark.parametrize(
    ('failure', 'expected_status', 'expected_error'),
    [
        (ConnectionError('PRIVATE-TEST-MARKER'), 'FAILED', 'FAKE_TRANSPORT_CONNECTION_FAILED'),
        (TimeoutError('PRIVATE-TEST-MARKER'), 'OUTCOME_UNKNOWN', 'FAKE_TRANSPORT_TIMEOUT'),
    ],
)
def test_fake_model_transport_failure_is_redacted_and_never_creates_evidence(
    real, monkeypatch, failure, expected_status, expected_error,
):
    from urban_design.week7.service import FakeTransport

    store, service, _, _ = real
    ws, scenarios = ids(store)
    calls = []

    def fail(self, bundle):
        calls.append(bundle)
        raise failure

    monkeypatch.setattr(FakeTransport, 'complete', fail)
    before = len(store.list_current('EvidenceCard', project_id=ws.project_id))
    result = service.interpret(
        ws.entity_id, scenarios[0].entity_id,
        {'private_input': 'PRIVATE-TEST-MARKER'},
    )
    stored = store.current(result['record_ref']['entity_id'])
    serialized = json.dumps(stored.as_dict(), sort_keys=True)
    assert result['status'] == expected_status
    assert result['errors'] == [expected_error]
    assert result['output'] == {'statement': '', 'citations': [], 'stated_numbers': []}
    assert 'PRIVATE-TEST-MARKER' not in serialized
    assert len(calls) == 1
    assert len(store.list_current('EvidenceCard', project_id=ws.project_id)) == before
    if expected_status == 'OUTCOME_UNKNOWN':
        assert result['retry_allowed'] is False


def _enqueue_w7_e1_job(store, plan_record, jobs, idempotency_key):
    from urban_design.environment.plan_service import STAGE, approved_plan

    decision_id = approved_plan(store, plan_record.entity_id, plan_record.project_id).decision_id
    return jobs.enqueue(
        project_id=plan_record.project_id, stage=STAGE, idempotency_key=idempotency_key,
        expected_revision=str(plan_record.revision),
        request={'project_id': plan_record.project_id, 'plan_artifact_id': plan_record.entity_id,
                 'decision_id': decision_id, 'baseline_scenario_id': 'formal-baseline',
                 'modified_scenario_id': 'formal-proposal'},
        input_refs=[{'id': plan_record.entity_id, 'sha256': plan_record.payload['sha256'],
                     'kind': 'e1_experiment_plan'}],
    )


def test_e1_calculation_failure_is_failed_and_outcome_unknown_survives_restart(tmp_path, monkeypatch):
    from test_decision_resolution_pipeline import decide, plan_fixture
    from urban_design.environment.contracts import E1PipelineRunResult
    from urban_design.environment import router as environment_router
    from urban_design.environment.plan_service import open_e1_jobs
    from urban_design.generation.job_store import GenerationJobStore, JobStatus
    from urban_design.store import ProjectStateStore

    store, key, key_path, plan_record = plan_fixture(tmp_path)
    try:
        decide(store, plan_record, key, key_path, 'Approve', 'w7-e1-approval', 2026)
        monkeypatch.setattr(environment_router, '_execute_formal_e1', lambda _req, _store, plan:
                            E1PipelineRunResult(run_id='w7-known-failure', status='FAIL', plan=plan))
        job_path = tmp_path / 'w7-e1-known-failure.sqlite3'
        jobs, runner, output = open_e1_jobs(
            store, job_path, environment_router._approved_handler(store),
        )
        job, _ = _enqueue_w7_e1_job(store, plan_record, jobs, 'w7-e1-known-failure')
        failed = runner.run(job.job_id)
        assert failed.status is JobStatus.FAILED
        assert failed.error_code == 'KNOWN_COMPUTATION_FAILED'
        assert not runner.verify_published(job.job_id)
        assert not (output / job.job_id).exists()
        assert store.list_current('ToolExecution', project_id=plan_record.project_id) == []
        assert store.list_current('EvidenceCard', project_id=plan_record.project_id) == []
    finally:
        store.close()


    restart_root = tmp_path / 'unknown-after-restart'
    restart_root.mkdir()
    store, key, key_path, plan_record = plan_fixture(restart_root)
    calls = []
    try:
        decide(store, plan_record, key, key_path, 'Approve', 'w7-e1-unknown-approval', 2026)

        def dispatched_then_lost(*_args, **_kwargs):
            calls.append('dispatched')
            raise ConnectionError('synthetic post-dispatch disconnect')

        monkeypatch.setattr(environment_router, '_execute_formal_e1', dispatched_then_lost)
        job_path = restart_root / 'w7-e1-unknown.sqlite3'
        jobs, runner, _ = open_e1_jobs(store, job_path, environment_router._approved_handler(store))
        job, _ = _enqueue_w7_e1_job(store, plan_record, jobs, 'w7-e1-unknown')
        unknown = runner.run(job.job_id)
        assert unknown.status is JobStatus.OUTCOME_UNKNOWN

        state_path = store.database
        plan_id = plan_record.entity_id
        project_id = plan_record.project_id
        store.close()
        store = ProjectStateStore(state_path)
        assert store.current(plan_id).payload['sha256'] == plan_record.payload['sha256']
        assert store.list_current('ToolExecution', project_id=project_id) == []
        assert store.list_current('EvidenceCard', project_id=project_id) == []

        reopened_jobs = GenerationJobStore(job_path)
        _jobs, reopened_runner, _ = open_e1_jobs(
            store, job_path, environment_router._approved_handler(store),
        )
        persisted = reopened_jobs.get(job.job_id)
        assert persisted.status is JobStatus.OUTCOME_UNKNOWN
        assert reopened_runner.run(job.job_id).status is JobStatus.OUTCOME_UNKNOWN
        replay, created = _enqueue_w7_e1_job(store, plan_record, reopened_jobs, 'w7-e1-unknown')
        assert replay.job_id == job.job_id and created is False
        assert calls == ['dispatched']
        assert not reopened_runner.verify_published(job.job_id)
    finally:
        store.close()


def test_e1_approved_w7_rerun_publishes_current_draft_lineage_once(tmp_path, monkeypatch):
    from datetime import date
    from shapely.geometry import box, mapping
    from test_decision_resolution_pipeline import decide
    from test_environment_plan_approval import _key, _store
    from urban_design.api import create_workspace_app
    from urban_design.approved_generation import _workspace_payload_digest
    from urban_design.environment.contracts import AnalysisPeriod
    from urban_design.environment.plan_service import approve_plan_artifact, persist_e1_plan_artifact
    from urban_design.environment.router import get_default_draft_plan
    from urban_design.geometry import canonical_geometry_hash
    from urban_design.workspace_contracts import WorkspaceRevision

    store = _store(tmp_path)
    fixture_key, key_path = _key(tmp_path)
    project_id = 'project-e1'
    baseline_id, modified_id = 'formal-baseline', 'formal-proposal'
    try:
        baseline = store.current(baseline_id)
        modified = store.current(modified_id)
        decide(store, baseline, fixture_key, key_path, 'Accept', 'w7-e1-baseline-accept', 2026)
        parent_parameters = dict(modified.payload.get('parameters') or {})
        parent_parameters.update({'provenance': 'FORMAL_DRAFT', 'acceptance_eligible': False,
                                  'analysis_eligible': False,
                                  'parent_revision': baseline.revision,
                                  'parent_geometry_sha256': baseline.payload['geometry_sha256']})
        modified = store.update(modified_id, {'parent_scenario_id': baseline_id, 'status': 'draft',
                                               'parameters': parent_parameters},
                                expected_revision=modified.revision,
                                reason='FIXTURE_ONLY W6 draft lineage for W7 rerun')

        boundary = mapping(box(0, 0, 40, 30))
        boundary_hash = canonical_geometry_hash(boundary)
        store.create('StudyArea', {'id': 'w7-e1-study', 'version': '1',
                                   'status': 'CONFIRMED_FOR_EXPLORATION',
                                   'geometry_sha256': boundary_hash},
                     entity_id='w7-e1-study', project_id=project_id)
        workspace = WorkspaceRevision(
            workspace_id='w7-e1-workspace', project_id=project_id, revision=1,
            study_area_id='w7-e1-study',
            spatial_brief={'exploration_design_area': {'geometry': boundary}},
        )
        workspace_payload = workspace.model_dump(mode='json')
        workspace_payload['payload_digest'] = _workspace_payload_digest(workspace).removeprefix('sha256:')
        ws = store.create('WorkspaceRevision', workspace_payload, entity_id=workspace.workspace_id,
                          project_id=project_id)

        anchor_artifact = store.create('Artifact', {
            'id': 'w7-e1-anchor-result', 'type': 'sunlight_simulation_result',
            'sha256': 'sha256:' + '1' * 64, 'project_id': project_id,
        }, entity_id='w7-e1-anchor-result', project_id=project_id)
        anchor = store.create('ToolExecution', {
            'id': 'w7-e1-anchor', 'scenario_id': modified_id, 'tool': 'fixture-e1-anchor',
            'output_artifact_refs': [anchor_artifact.entity_id],
        }, entity_id='w7-e1-anchor', project_id=project_id)

        from urban_design.environment.contracts import GroundGridDefinition
        plan = get_default_draft_plan().model_copy(update={
            'baseline_scenario_id': baseline_id, 'modified_scenario_id': modified_id,
            'period': AnalysisPeriod(start_date=date(2026, 6, 21), end_date=date(2026, 6, 21),
                                     dates=[date(2026, 6, 21)], start_hour=10, end_hour=11, timestep=1),
            'grid_definition': GroundGridDefinition(origin_x=0, origin_y=0, spacing_m=20,
                                                    crs='EPSG:28992', tag='FIXTURE_ONLY'),
        })
        plan_record = persist_e1_plan_artifact(store, plan, project_id)
        approval = approve_plan_artifact(
            store, plan_record.entity_id, decision_key=fixture_key, decision_key_path=key_path,
            actor='test-designer', actor_session_id='w7-e1-test-human',
            reason='隔離測試：批准此精確 E1 計畫版本。',
        )
        app = create_workspace_app(store, decision_key_path=key_path)
        app.state.e1_job_database = tmp_path / 'w7-e1-jobs.sqlite3'
        with TestClient(app) as client:
            workspace_decision = client.post(f'/api/v1/projects/{project_id}/decisions', json={
                'target_id': ws.entity_id, 'target_type': 'WorkspaceRevision',
                'target_version': str(ws.revision),
                'target_geometry_sha256': boundary_hash,
                'target_payload_digest': 'sha256:' + workspace_payload['payload_digest'],
                'action': 'Approve', 'status': 'approved',
                'reason': '隔離測試：確認此工作區版本與範圍。',
                'decision_key': fixture_key, 'actor_session_id': 'w7-e1-test-human',
            })
            assert workspace_decision.status_code == 201, workspace_decision.text
            unapproved_plan = persist_e1_plan_artifact(
                store, plan.model_copy(update={'notes': plan.notes + ' TEST_UNAPPROVED'}), project_id,
            )
            app.state.e1_job_database = tmp_path / 'w7-e1-pre-dispatch.sqlite3'
            unapproved = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun', json={
                'target': {'entity_id': anchor.entity_id, 'revision': anchor.revision},
                'stage': 'E1', 'plan_artifact_id': unapproved_plan.entity_id,
                'baseline_scenario_id': baseline_id, 'modified_scenario_id': modified_id,
                'idempotency_key': 'w7-e1-unapproved-pre-dispatch',
            })
            assert unapproved.status_code == 409
            assert unapproved.json()['detail']['code'] == 'E1_PLAN_NOT_APPROVED'
            assert not app.state.e1_job_database.exists()
            app.state.e1_job_database = tmp_path / 'w7-e1-jobs.sqlite3'
            request = {
                'target': {'entity_id': anchor.entity_id, 'revision': anchor.revision},
                'stage': 'E1', 'plan_artifact_id': plan_record.entity_id,
                'baseline_scenario_id': baseline_id, 'modified_scenario_id': modified_id,
                'idempotency_key': 'w7-e1-current-draft-once',
            }
            response = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun', json=request)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body['status'] == 'READY'
            assert body['created'] is True
            assert body['result']['status'] == 'SUCCESS'
            assert body['result']['plan']['founder_decision_id'] == approval.entity_id
            runs_before_replay = [r for r in store.list_current('ToolExecution', project_id=project_id)
                                  if r.entity_id != anchor.entity_id]
            assert len(runs_before_replay) == 1
            assert runs_before_replay[0].payload['parameters']['result_scope'] == 'DRAFT'
            cards = [r for r in store.list_current('EvidenceCard', project_id=project_id)
                     if r.payload.get('scenario_id') == modified_id]
            assert cards and all(r.payload['validation_status'] == 'unverified' for r in cards)
            replay = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun', json=request)
            assert replay.status_code == 200, replay.text
            assert replay.json()['created'] is False
            runs_after_replay = [r for r in store.list_current('ToolExecution', project_id=project_id)
                                 if r.entity_id != anchor.entity_id]
            assert [r.entity_id for r in runs_after_replay] == [r.entity_id for r in runs_before_replay]
            view = client.get(f'/api/v1/week7/workspaces/{ws.entity_id}/view?scenario_id={modified_id}')
            assert view.status_code == 200
            assert any(run['payload']['scenario_id'] == modified_id for run in view.json()['runs'])

            from urban_design.environment import router as environment_router
            actual_e1 = environment_router._execute_formal_e1
            dispatched = []
            def compute_then_lose_ack(req, current_store, approved_plan):
                result = actual_e1(req, current_store, approved_plan)
                dispatched.append(result.run_id)
                raise ConnectionError('synthetic post-dispatch acknowledgement loss')
            monkeypatch.setattr(environment_router, '_execute_formal_e1', compute_then_lose_ack)
            unknown_request = {**request, 'idempotency_key': 'w7-e1-post-dispatch-unknown'}
            unknown = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun', json=unknown_request)
            assert unknown.status_code == 200, unknown.text
            unknown_body = unknown.json()
            assert unknown_body['status'] == 'OUTCOME_UNKNOWN'
            assert unknown_body['reconciliation_required'] is True
            assert unknown_body['reconciliation']['redispatch_allowed'] is False
            assert unknown_body['reconciliation']['status'] == 'UNRESOLVED'
            assert unknown_body['reconciliation']['candidate_attribution'] == 'AMBIGUOUS_SCENARIO_MATCH'
            assert unknown_body['reconciliation']['candidate_tool_executions']
            receipts = unknown_body['reconciliation']['dispatch_receipts']
            assert len(receipts) == 1
            assert receipts[0]['receipt_type'] == 'E1_HANDLER_ENTRY'
            assert receipts[0]['job_id'] == unknown_body['job_id']
            assert unknown_body['reconciliation']['process_observation']['status'] == 'NOT_RECORDED'
            assert any(item['path'].endswith('handler-entry-receipt.json')
                       for item in unknown_body['reconciliation']['staging_files'])
            assert all(check['verified'] for candidate in unknown_body['reconciliation']['candidate_tool_executions']
                       for check in candidate['output_hashes'])
            assert len(dispatched) == 1
            repeated_unknown = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun', json=unknown_request)
            assert repeated_unknown.status_code == 200
            assert repeated_unknown.json()['job_id'] == unknown_body['job_id']
            assert dispatched == [dispatched[0]]

            from shapely.geometry import Polygon
            from urban_design.environment.contracts import E1ExperimentPlan, E1ScenarioInputBinding
            from urban_design.environment.plan_service import canonical_plan_bytes, plan_content_sha256, plan_artifact_id
            from urban_design.environment.weather_snapshot import canonical_bytes, persist_bytes
            from urban_design.week7.real_service import digest as scenario_digest
            from test_e2_execution import approval as approve_artifact

            before_original = store.current(modified_id).to_dict()
            before_original_history = store.history(modified_id)
            before_runs = [row.to_dict() for row in store.list_current('ToolExecution', project_id=project_id)]
            before_cards = [row.to_dict() for row in store.list_current('EvidenceCard', project_id=project_id)]
            source_geometry = store.current(modified.payload['geometry_artifact_id'])
            invalid_doc = json.loads(Path(source_geometry.payload['uri']).read_bytes())
            invalid_doc['features'][0]['geometry'] = mapping(Polygon(
                [(0, 0), (40, 30), (0, 30), (40, 0), (0, 0)],
            ))
            invalid_artifact = persist_bytes(store, project_id, tmp_path / 'invalid-e1-geometry',
                'scenario-geometry', canonical_bytes(invalid_doc), mime='application/geo+json')
            store.update(invalid_artifact.entity_id, {'crs': 'EPSG:28992'})
            invalid_payload = dict(modified.payload)
            invalid_parameters = dict(invalid_payload.get('parameters') or {})
            invalid_parameters.update({'validation': {'valid': True}, 'provenance': 'FORMAL_DRAFT',
                                       'parent_revision': modified.revision,
                                       'parent_geometry_sha256': modified.payload['geometry_sha256']})
            invalid_payload.update({'id': 'formal-invalid-geometry', 'status': 'draft',
                'parent_scenario_id': modified_id, 'geometry_artifact_id': invalid_artifact.entity_id,
                'geometry_sha256': invalid_artifact.payload['sha256'], 'parameters': invalid_parameters})
            invalid_scenario = store.create('DesignScenario', invalid_payload,
                entity_id='formal-invalid-geometry', project_id=project_id)
            original_plan = E1ExperimentPlan.model_validate(plan_record.payload['plan'])
            invalid_binding = E1ScenarioInputBinding(
                scenario_id=invalid_scenario.entity_id, scenario_revision=invalid_scenario.revision,
                scenario_payload_sha256=scenario_digest(invalid_scenario.payload),
                geometry_artifact_id=invalid_artifact.entity_id, geometry_artifact_revision=invalid_artifact.revision,
                geometry_sha256=invalid_artifact.payload['sha256'],
                public_space_sha256='sha256:' + '2' * 64, domain_sources_sha256='sha256:' + '3' * 64,
            )
            invalid_plan = original_plan.model_copy(update={
                'modified_scenario_id': invalid_scenario.entity_id,
                'frozen_inputs': [original_plan.frozen_inputs[0], invalid_binding],
            })
            invalid_plan_bytes = canonical_plan_bytes(invalid_plan)
            invalid_plan_sha = plan_content_sha256(invalid_plan)
            invalid_plan_id = plan_artifact_id(invalid_plan_sha)
            invalid_plan_record = store.create('Artifact', {
                'id': invalid_plan_id, 'type': 'e1_experiment_plan', 'uri': f'artifact://{invalid_plan_id}',
                'sha256': invalid_plan_sha, 'mime': 'application/json', 'project_id': project_id,
                'producer': 'FIXTURE_ONLY invalid geometry injection', 'size_bytes': len(invalid_plan_bytes),
                'plan': json.loads(invalid_plan_bytes),
            }, entity_id=invalid_plan_id, project_id=project_id)
            assert approve_artifact(client, invalid_plan_record, fixture_key).status_code == 201
            invalid_event_count = len(store.events(target_id=invalid_scenario.entity_id))
            app.state.e1_job_database = tmp_path / 'w7-e1-invalid-geometry-jobs.sqlite3'
            invalid_geometry_response = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun', json={
                'target': {'entity_id': anchor.entity_id, 'revision': anchor.revision}, 'stage': 'E1',
                'plan_artifact_id': invalid_plan_record.entity_id, 'baseline_scenario_id': baseline_id,
                'modified_scenario_id': invalid_scenario.entity_id,
                'idempotency_key': 'w7-e1-invalid-geometry',
            })
            assert invalid_geometry_response.status_code == 409, invalid_geometry_response.text
            assert invalid_geometry_response.json()['detail']['code'] == 'E1_SCENARIO_GEOMETRY_REFUSED'
            assert 'invalid geometry' in invalid_geometry_response.json()['detail']['reason'].lower()
            assert not app.state.e1_job_database.exists()
            assert store.current(modified_id).to_dict() == before_original
            assert store.history(modified_id) == before_original_history
            assert store.current(invalid_scenario.entity_id).revision == invalid_scenario.revision
            assert len(store.events(target_id=invalid_scenario.entity_id)) == invalid_event_count
            assert [row.to_dict() for row in store.list_current('ToolExecution', project_id=project_id)] == before_runs
            assert [row.to_dict() for row in store.list_current('EvidenceCard', project_id=project_id)] == before_cards
            unrelated_payload = dict(baseline.payload)
            unrelated_payload['id'] = 'formal-unrelated-scenario'
            unrelated = store.create('DesignScenario', unrelated_payload,
                                     entity_id='formal-unrelated-scenario', project_id=project_id)
            wrong_target = {
                **request,
                'target': {'entity_id': 'w7-e1-wrong-lineage', 'revision': 1},
            }
            store.create('ToolExecution', {
                    'id': 'w7-e1-wrong-lineage', 'scenario_id': unrelated.entity_id,
                'tool': 'fixture-e1-anchor', 'output_artifact_refs': [anchor_artifact.entity_id],
            }, entity_id='w7-e1-wrong-lineage', project_id=project_id)
            count_before_bad = len(store.list_current('ToolExecution', project_id=project_id))
            denied = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun', json=wrong_target)
            assert denied.status_code == 409
            assert denied.json()['detail']['code'] == 'execution_scenario_mismatch'
            assert len(store.list_current('ToolExecution', project_id=project_id)) == count_before_bad
            assert unrelated.payload['geometry_sha256'] == baseline.payload['geometry_sha256']
    finally:
        store.close()


def test_real_scene_export_preserves_geometry_and_missing_analysis_fails(real):
    store,service,_,tmp=real;ws,scenarios=ids(store);refs=[EntityRef(**target(r)) for r in scenarios[:2]]
    result=render_real_figure(service=service,workspace_id=ws.entity_id,targets=refs,kind='comparison',output_path=tmp/'real.png',png=False)
    assert result['schematic'] is False
    assert result['sources'][0]['sha256']==scenarios[0].payload['geometry_sha256']
    assert result['svg_sha256']==hashlib.sha256(Path(result['svg_path']).read_bytes()).hexdigest()
    assert len(result['scenarios'])==2
    assert 'FIXTURE_ONLY' not in Path(result['svg_path']).read_text()
    assert 'fixture-scenario-' in Path(result['svg_path']).read_text()
    with pytest.raises(Week7Refusal,match='png_output_extension_required'):
        render_real_figure(service=service,workspace_id=ws.entity_id,targets=refs[:1],kind='plan',output_path=tmp/'invalid.svg')
    assert not (tmp/'invalid.svg').exists()
    with pytest.raises(Week7Refusal,match='MISSING_ANALYSIS_DATA'):
        render_real_figure(service=service,workspace_id=ws.entity_id,targets=refs[:1],kind='e1',output_path=tmp/'missing.png',png=False)

def test_declared_input_hash_staleness_and_unknown_are_distinct(real):
    store,service,_,_=real;ws,scenarios=ids(store);row=scenarios[0]
    run=store.create_typed(ToolExecution(id='fixture-pending-binding', project_id=ws.project_id,
        scenario_id=row.entity_id, tool='fixture-no-engine', tool_version='1',
        idempotency_key='fixture-pending-binding', input_artifact_hashes_by_id={
        row.payload['geometry_artifact_id']:row.payload['geometry_sha256']},
        limitations=['FIXTURE_ONLY; input freshness is independent of run success']))
    assert run.payload['status']=='PENDING'
    assert service.freshness(run,row,ws)=='current'
    revised=store.update(row.entity_id,{'geometry_sha256':'sha256:'+'0'*64},expected_revision=row.revision)
    assert service.freshness(run,revised,ws)=='stale'
    unknown=store.current('fixture-card-1')
    assert service.freshness(unknown,row,ws)=='unknown'

def test_authority_projection_is_read_only_and_mutations_are_refused(tmp_path, monkeypatch):
    from urban_design.week7 import real_service
    authority=seed_project_database(tmp_path/'injected-authority.sqlite3')
    monkeypatch.setattr(real_service, 'AUTHORITY_DATABASE', authority)
    before_bytes = authority.read_bytes()
    before = hashlib.sha256(before_bytes).hexdigest()
    with ProjectStateStore(authority,read_only=True) as store:
        app=FastAPI();app.include_router(create_week7_router(store));client=TestClient(app)
        ws,rows=ids(store)
        assert client.get(f'/api/v1/week7/workspaces/{ws.entity_id}/view').status_code==200
        response=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/switch',json={'target':target(rows[0]),'workspace_revision':ws.revision})
        assert response.status_code==409
        assert response.json()['detail']['code']=='authority_database_write_refused'
    assert authority.read_bytes() == before_bytes
    assert hashlib.sha256(authority.read_bytes()).hexdigest() == before



def test_private_reasoning_output_is_rejected_and_not_stored(real):
    store,service,_,_=real;ws,rows=ids(store)
    result=service.interpret(ws.entity_id,rows[0].entity_id,{'chain_of_thought':'PROHIBITED-TEST-MARKER'})
    assert result['status']=='INVALID'
    assert result['errors']==['malformed_output_redacted']
    record=store.current(result['record_ref']['entity_id'])
    assert 'PROHIBITED-TEST-MARKER' not in json.dumps(record.as_dict())

def test_real_png_publication_and_download_have_matching_hashes(real):
    store,service,client,_=real;ws,rows=ids(store)
    decisions=len(store.list_current('HumanDecision'))
    response=client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/figures',json={'kind':'plan','targets':[target(rows[0])]})
    assert response.status_code==200,response.text
    data=response.json();artifact_id=data['artifact_ref']['entity_id']
    record=store.current(artifact_id)
    assert record.payload['type']=='REAL_SCENE_FIGURE'
    assert record.payload['sha256']=='sha256:'+data['png_sha256']
    image=client.get('/api/v1/week7/figures/'+artifact_id)
    assert image.status_code==200
    assert image.content[:8]==b'\x89PNG\r\n\x1a\n'
    assert hashlib.sha256(image.content).hexdigest()==data['png_sha256']
    assert len(store.list_current('HumanDecision'))==decisions


def test_fixture_does_not_read_canonical_main_database(tmp_path, monkeypatch):
    from tests.week7_support import week7_db
    from urban_design.week7.service import AUTHORITY_DATABASE
    original = sqlite3.connect
    def guarded(database, *args, **kwargs):
        assert str(AUTHORITY_DATABASE) not in str(database), "canonical main DB access forbidden"
        return original(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', guarded)
    database = week7_db.__wrapped__(tmp_path)
    assert database.parent == tmp_path


def test_typed_fixture_never_claims_engine_success_or_human_approval(real):
    store, service, _, _ = real
    ws, scenarios = ids(store)
    assert store.list_current('ToolExecution') == []
    assert store.list_current('HumanDecision') == []
    for scenario in scenarios:
        view = service.view(ws.entity_id, scenario.entity_id)
        assert view['run_status'] == 'NOT_RUN'
        assert view['human_status'] == 'NOT_ACCEPTED'
        assert view['evidence_status'] == 'UNVERIFIED_OR_MISSING'
        assert scenario.payload['parameters']['provenance'] == 'FIXTURE_ONLY'
        assert all(c['payload']['result']['status'] == 'observed' for c in view['cards'])


def test_canonical_database_guard_blocks_uri_and_file_reads(no_canonical_main_database, tmp_path):
    import io
    from urban_design.week7.service import AUTHORITY_DATABASE, copy_authority_database
    for operation in (
        lambda: sqlite3.connect(AUTHORITY_DATABASE),
        lambda: sqlite3.connect(AUTHORITY_DATABASE.as_uri() + '?mode=ro', uri=True),
        lambda: AUTHORITY_DATABASE.read_bytes(),
        lambda: open(AUTHORITY_DATABASE, 'rb'),
        lambda: io.open(AUTHORITY_DATABASE, 'rb'),
        lambda: copy_authority_database(tmp_path / 'blocked.sqlite3'),
    ):
        with pytest.raises(AssertionError, match='canonical main DB access forbidden'):
            operation()
