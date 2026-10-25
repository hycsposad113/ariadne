"""Real external E2 handlers must retain late jobs and never resend disconnects."""
import json
import pytest
from test_e2_execution import authority
from test_decision_resolution_e2 import setup_e2
from urban_design.environment import e2_service as service
from urban_design.generation.job_store import JobStatus


@pytest.mark.parametrize('fault',['late_revision','disconnect'])
def test_real_e2_completion_context_and_disconnect(authority, monkeypatch, fault):
    store, client, _, root = authority
    record, _, body = setup_e2(authority)
    calls = []
    actual = service.calculate
    def calculated_then_disconnect(*args, **kwargs):
        values = actual(*args, **kwargs)
        calls.append(values)
        if fault == 'disconnect':
            raise ConnectionError('J4 injected transport lost after actual computation')
        return values
    monkeypatch.setattr(service, 'calculate', calculated_then_disconnect)
    jobs, runner, output = service.open_jobs(store, root/'e2-jobs.sqlite3')
    # API constructs the registered runner. Inject only at persisted PREPARED
    # boundary by instrumenting the same operational store class.
    original = type(jobs).record_prepared
    changed = []
    def prepared_then_changed(self,*args,**kwargs):
        accepted = original(self,*args,**kwargs)
        if fault == 'late_revision':
            row = store.current('j2-fixture-1')
            changed.append(store.update(row.entity_id,{'name':'B2 after real B1 computation'}))
        return accepted
    monkeypatch.setattr(type(jobs),'record_prepared',prepared_then_changed)
    response = client.post('/api/v1/environment/e2/simulate',json=body)
    assert response.status_code == 200, response.text
    result = response.json(); job = jobs.get(result['job_id'])
    if fault == 'disconnect':
        assert job.status is JobStatus.OUTCOME_UNKNOWN, result
        assert len(calls) == 1
        assert result.get('reconciliation', {}).get('redispatch_allowed') is False
        assert result['reconciliation']['ledger_tool_execution_ids']
        assert result['reconciliation']['output_files']
        again = client.post('/api/v1/environment/e2/simulate',json=body)
        assert again.json() == result and len(calls) == 1
        assert len(store.list_current('ToolExecution')) == 1
        assert sum(e.to_status is JobStatus.RUNNING for e in jobs.events(job.job_id)) == 1
    else:
        assert changed and job.status is JobStatus.STALE_FOR_CURRENT_CONTEXT, result
        assert not runner.verify_published(job.job_id)  # current publication API must refuse B1
        import hashlib
        manifest = json.loads((output/job.job_id/'manifest.json').read_bytes())
        assert 'sha256:'+hashlib.sha256((output/job.job_id/'manifest.json').read_bytes()).hexdigest() == job.output_manifest_sha256
        for ref in manifest['output_refs']:
            assert 'sha256:'+hashlib.sha256((output/job.job_id/ref['relative_path']).read_bytes()).hexdigest() == ref['sha256']
        old = json.loads((output/job.job_id/'result.json').read_bytes())
        assert old['results']['honeybee_radiance']['0'][1]['metadata']['scenario_revision'] == 1
        assert store.current('j2-fixture-1').revision == 2


def test_ready_e2_job_view_becomes_stale_after_new_revision(authority):
    from urban_design.week7.jobs import project_job_states
    from urban_design.week7.real_service import RealWeek7Service
    store, client, _, root = authority
    record, _, body = setup_e2(authority)
    response = client.post('/api/v1/environment/e2/simulate',json=body)
    assert response.status_code == 200 and response.json()['status'] == 'SUCCEEDED'
    job_id = response.json()['job_id']
    ws = store.create('WorkspaceRevision',{'id':'j4-ws','project_id':'p'},entity_id='j4-ws',project_id='p')
    row = store.current('j2-fixture-1')
    store.update(row.entity_id,{'name':'B2 after READY B1'})
    projected = project_job_states(RealWeek7Service(store),ws.entity_id,row.entity_id,{'E2':root/'e2-jobs.sqlite3'})
    job = next(j for j in projected['jobs'] if j['job_id'] == job_id)
    assert job['scenario_bound'] is True
    assert job['status'] == 'STALE_FOR_CURRENT_CONTEXT'
    assert job['is_current_revision'] is False
    result = service.read_result(store,job_id,'p',root/'e2-jobs.sqlite3')
    assert result['status'] == 'STALE_FOR_CURRENT_CONTEXT' and result['published_as_current'] is False
