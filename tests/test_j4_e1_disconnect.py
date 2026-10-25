"""J3's actual E1 disconnect cell must be unknown after real computation."""
import json
from test_decision_resolution_pipeline import plan_fixture, decide
from urban_design.environment.plan_service import open_e1_jobs, STAGE
import importlib
from urban_design.generation.job_store import JobStatus


def test_actual_e1_post_dispatch_disconnect_is_unknown_without_retry(tmp_path,monkeypatch):
    module = importlib.import_module('urban_design.environment.router')
    store,key,path,record = plan_fixture(tmp_path)
    try:
        decide(store,record,key,path,'Approve','j4-disconnect-approval',2026)
        actual = module._execute_formal_e1
        calls = []
        def computed_then_lost(*args,**kwargs):
            result = actual(*args,**kwargs)
            calls.append(result)
            (tmp_path/'real-before-disconnect.json').write_text(json.dumps(result.model_dump(mode='json')))
            raise ConnectionError('J4 post-dispatch disconnect after actual E1 computation')
        monkeypatch.setattr(module,'_execute_formal_e1',computed_then_lost)
        jobs,runner,_ = open_e1_jobs(store,tmp_path/'jobs.sqlite3',module._approved_handler(store))
        job,_ = jobs.enqueue(project_id='project-e1',stage=STAGE,idempotency_key='j4-e1-lost',expected_revision=str(record.revision),
            request={'project_id':'project-e1','plan_artifact_id':record.entity_id,'decision_id':'j4-disconnect-approval',
                     'baseline_scenario_id':'formal-baseline','modified_scenario_id':'formal-proposal'},
            input_refs=[{'id':record.entity_id,'sha256':record.payload['sha256'],'kind':'e1_experiment_plan'}])
        result = runner.run(job.job_id)
        assert calls and calls[0].status == 'SUCCESS'
        assert result.status is JobStatus.OUTCOME_UNKNOWN
        assert runner.run(job.job_id).status is JobStatus.OUTCOME_UNKNOWN and len(calls) == 1
        assert not runner.verify_published(job.job_id)
        assert store.list_current('ToolExecution') and store.list_current('EvidenceCard')
    finally:
        store.close()
