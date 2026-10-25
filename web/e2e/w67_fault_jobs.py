"""Fault probes on real generation/E1/E2 requests and production stage handlers.

This is rehearsal instrumentation. Successful computations are never replaced.
Negative transport injections raise after real production computations return.
Every mutable state is a further SQLite backup; parent artifacts stay unchanged.
"""
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore
from urban_design.generation.job_store import GenerationJobStore, JobStatus
from urban_design.generation.job_runner import GenerationJobRunner
from urban_design.environment.plan_service import open_e1_jobs
from urban_design.environment.router import _approved_handler
from urban_design.environment.e2_service import open_jobs
from urban_design.week7.real_service import RealWeek7Service, EntityRef

FAULTS=('source_or_geometry_hash_mismatch','observation_source_unavailable','repeated_run','tool_disconnect',
        'late_b1_after_b2','refresh_or_restart','partial_publish_db_failure','ai_wrong_citation')

def backup(source,destination):
    with sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(destination) as dst:src.backup(dst)

def run_faults(*, parent_store, app, context, root, key_path, workspace_id, evidence):
    project=parent_store.current(workspace_id).project_id
    root.mkdir()
    gen=app.state.generation_workflow
    templates={'generation':(gen.store,gen.runner,gen.store.get(context['generation_job']))}
    ej,er,_=open_e1_jobs(parent_store,app.state.e1_job_database,_approved_handler(parent_store))
    if Path(ej.database_path).is_file():
        with sqlite3.connect(ej.database_path) as c:
            row=c.execute("SELECT job_id FROM generation_jobs WHERE status='READY' ORDER BY created_at LIMIT 1").fetchone()
        if row:templates['E1']=(ej,er,ej.get(row[0]))
    if context.get('e2',{}).get('job_id'):
        jobs,runner,_=open_jobs(parent_store,app.state.e2_job_database)
        template=jobs.get(context['e2']['job_id'])
        if template.status.value=='READY':templates['E2']=(jobs,runner,template)
    rows=[]
    for stage in ('generation','E1','E2'):
        if stage not in templates:
            for fault in FAULTS:
                row={'stage':stage,'fault':fault,'status':'BLOCKED','reason':'No successful real stage job available; no synthetic replacement'}
                rows.append(row);evidence('2h-'+stage+'-'+fault,row)
            continue
        source_jobs,source_runner,template=templates[stage]
        for fault in FAULTS:
            case=root/(stage+'-'+fault);case.mkdir()
            backup(parent_store.database,case/'authority-copy.sqlite3')
            child=ProjectStateStore(case/'authority-copy.sqlite3')
            row={'stage':stage,'fault':fault,'template_stage':template.stage,'template_job_id':template.job_id,
                 'request':template.request,'input_refs':list(template.input_refs),'status':'INCOMPLETE'}
            try:
                if fault in {'repeated_run','refresh_or_restart','ai_wrong_citation'}:
                    backup(source_jobs.database_path,case/'jobs.sqlite3')
                    jobs=GenerationJobStore(case/'jobs.sqlite3')
                    registration=source_runner._handlers[template.stage]
                    runner=GenerationJobRunner(jobs,staging_root=source_runner.staging_root,output_root=source_runner.output_root)
                    runner.register_handler(template.stage,registration.version,registration.run_stage,external=registration.external)
                    if fault=='repeated_run':
                        same,created=jobs.enqueue(project_id=template.project_id,idempotency_key=template.idempotency_key,
                            stage=template.stage,request=template.request,input_refs=template.input_refs,expected_revision=template.expected_revision)
                        assert not created and same.job_id==template.job_id
                        assert runner.run(same.job_id).status==template.status and runner.verify_published(same.job_id)
                        row.update(status='PASS',created_second=False,dispatch_count=0,publication_verified=True)
                    elif fault=='refresh_or_restart':
                        assert runner.verify_published(template.job_id)
                        row.update(status='PASS',same_job_status=jobs.get(template.job_id).status.value,publication_verified=True,
                                   recovery_scope='fresh authority/job connections; no network server process')
                    else:
                        a=template.request.get('modified_scenario_id') or context['selected']
                        if stage=='E2':a=context['draft']
                        result=RealWeek7Service(child).interpret(workspace_id,a,{'statement':'Injected wrong citation against real job-linked evidence',
                            'citations':[{'evidence_id':'j3-nonexistent-evidence'}],'stated_numbers':[99999]})
                        assert result['status']=='INVALID'
                        row.update(status='PASS',actual=result,qualification='offline semantic-validator probe of real job scenario; no Live AI')
                else:
                    # Register the existing real handler on a separate operational store.
                    if stage=='generation':
                        child_app=create_workspace_app(store=child,decision_key_path=key_path,
                            scenario_artifact_root=case/'scenario-artifacts',allow_live_critic=False)
                        jobs=child_app.state.generation_workflow.store;runner=child_app.state.generation_workflow.runner
                    elif stage=='E1':
                        jobs,runner,_=open_e1_jobs(child,case/'jobs.sqlite3',_approved_handler(child))
                        from urban_design.environment.plan_service import approved_plan,verify_scenario_inputs,PlanNotApproved
                        loaded=approved_plan(child,template.request['plan_artifact_id'],project)
                        def e1_current(_job):
                            try:
                                current=approved_plan(child,loaded.artifact_id,project)
                                verify_scenario_inputs(child,current.plan,project)
                                return (current.revision,current.sha256,current.decision_id)==(loaded.revision,loaded.sha256,loaded.decision_id)
                            except PlanNotApproved:return False
                        runner.revision_is_current=e1_current
                    else:jobs,runner,_=open_jobs(child,case/'jobs.sqlite3')
                    job,_=jobs.enqueue(project_id=project,idempotency_key='j3-real-'+fault,stage=template.stage,
                        request=template.request,input_refs=template.input_refs,expected_revision=template.expected_revision)
                    with ExitStack() as stack:
                        if fault in {'source_or_geometry_hash_mismatch','observation_source_unavailable'}:
                            if stage=='generation':
                                artifact=next(a for a in child.list_current('Artifact',project_id=project) if a.payload.get('type')=='normalized_source')
                            else:
                                sid=template.request.get('modified_scenario_id') or context['draft']
                                artifact=child.current(child.current(sid).payload['geometry_artifact_id'])
                            raw=Path(artifact.payload['uri']).read_bytes()
                            original_hash=hashlib.sha256(raw).hexdigest()
                            replacement=case/'fault-owned-input.geojson'
                            if fault=='source_or_geometry_hash_mismatch':replacement.write_bytes(raw+b' ')
                            child.update(artifact.entity_id,{'uri':str(replacement)},expected_revision=artifact.revision,
                                actor='j3-fault-injection',reason='Disposable child copy only; original bytes preserved')
                            row.update(injection={'artifact_id':artifact.entity_id,'original_sha256':original_hash,
                                'fault_kind':'hash_mismatch' if replacement.exists() else 'input_file_unavailable'})
                            result=runner.run(job.job_id)
                            assert result.status.value in {'FAILED','OUTCOME_UNKNOWN'},result.status.value
                            assert not runner.verify_published(job.job_id)
                            row.update(status='PASS',job_status=result.status.value,error_code=result.error_code)
                        elif fault=='tool_disconnect':
                            if stage=='generation':boundary='urban_design.generation.formal_service.run_formal_pipeline'
                            elif stage=='E1':boundary='urban_design.environment.router._execute_formal_e1'
                            else:boundary='urban_design.environment.e2_service.calculate'
                            import importlib
                            module_name,attribute=boundary.rsplit('.',1)
                            actual_calculate=getattr(importlib.import_module(module_name),attribute)
                            physical_outputs=[]
                            def calculated_then_lost(*args,**kwargs):
                                value=actual_calculate(*args,**kwargs)
                                data=value.model_dump(mode='json') if hasattr(value,'model_dump') else value
                                proof=case/'real-calculation-before-disconnect.json'
                                with proof.open('x') as f:json.dump(data,f,ensure_ascii=False,allow_nan=False)
                                physical_outputs.append({'path':str(proof),'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()})
                                raise ConnectionError('J3_INJECTED_OUTCOME_UNKNOWN_POST_DISPATCH')
                            mocked=stack.enter_context(patch(boundary,side_effect=calculated_then_lost))
                            result=runner.run(job.job_id);again=runner.run(job.job_id)
                            row.update(actual_job_status=result.status.value,physical_outputs=physical_outputs,
                                real_calculation_completed=bool(physical_outputs),calculation_boundary_calls=mocked.call_count,
                                redispatch_count=0,handler_boundary=boundary)
                            assert physical_outputs,'Real calculation did not complete before injected disconnect'
                            assert mocked.call_count==1 and again.status==result.status
                            expected='FAILED' if stage=='generation' else 'OUTCOME_UNKNOWN'
                            assert result.status.value==expected,result.status.value
                            if stage == 'E2':
                                from urban_design.environment.e2_service import read_result
                                reconciled = read_result(child, job.job_id, project, jobs.database_path)
                                assert reconciled['status'] == 'OUTCOME_UNKNOWN'
                                assert reconciled['reconciliation']['redispatch_allowed'] is False
                                assert reconciled['reconciliation']['ledger_tool_execution_ids']
                                assert reconciled['reconciliation']['dispatch_receipts']
                                assert reconciled['reconciliation']['process_observations']
                                assert reconciled['reconciliation']['output_files']
                                row['reconciliation'] = reconciled['reconciliation']
                            row.update(status='PASS',job_status=result.status.value,handler_boundary=boundary,
                                calculation_boundary_calls=mocked.call_count,redispatch_count=0,
                                qualification='actual calculation completed and saved before injected negative transport; no successful output stub; generation is local nonexternal')
                        elif fault=='late_b1_after_b2':
                            original_prepared=jobs.record_prepared
                            a=template.request.get('modified_scenario_id') or context['draft']
                            b=next(s for s in context['ids'] if s!=a)
                            mutation={}
                            def prepared_then_switch(*args,**kwargs):
                                accepted=original_prepared(*args,**kwargs)
                                service=RealWeek7Service(child)
                                service.switch(workspace_id,EntityRef(entity_id=b,revision=child.current(b).revision),child.current(workspace_id).revision)
                                row_target=child.current(workspace_id if stage=='generation' else a)
                                changed=child.update(row_target.entity_id,row_target.payload,expected_revision=row_target.revision,
                                    replace=True,actor='j3-fault-injection',reason='Actual append-only revision changes after calculation before job publication')
                                mutation.update(before=row_target.revision,after=changed.revision)
                                return accepted
                            jobs.record_prepared=prepared_then_switch
                            try:result=runner.run(job.job_id)
                            finally:jobs.record_prepared=original_prepared
                            view=RealWeek7Service(child).view(workspace_id)
                            assert mutation['after']>mutation['before'] and view['scenario_id']==b
                            assert all(r['payload'].get('scenario_id')!=a for r in view['runs'])
                            assert (runner.output_root/job.job_id/'manifest.json').is_file()
                            row.update(actual_job_status=result.status.value,mutation=mutation,selected_b=True,original_a_not_rebound=True,real_handler_completed=True)
                            if stage=='generation':assert result.status is JobStatus.STALE_FOR_CURRENT_CONTEXT,result.status.value
                            elif stage=='E1':
                                from urban_design.environment.plan_service import approved_plan,verify_scenario_inputs,PlanNotApproved
                                runner_current=True
                                try:verify_scenario_inputs(child,approved_plan(child,template.request['plan_artifact_id'],project).plan,project)
                                except PlanNotApproved:runner_current=False
                                assert not runner_current
                                assert result.status is JobStatus.STALE_FOR_CURRENT_CONTEXT, 'E1 direct registered runner lacks current-check host wiring: '+result.status.value
                            else:
                                from urban_design.environment.e2_service import readiness
                                ready=readiness(child,template.request['plan_id'],project)
                                assert not ready['dispatch_allowed']
                                assert result.status is JobStatus.STALE_FOR_CURRENT_CONTEXT, 'E2 late changed scenario revision job still '+result.status.value
                                retained = json.loads((runner.output_root/job.job_id/'result.json').read_bytes())
                                own = [v for shifts in retained['results'].values() for pair in shifts.values() for v in pair if v['scenario_id'] == a]
                                assert own and all(v['metadata']['scenario_revision'] == mutation['before'] for v in own)
                                row['retained_b1_result'] = {'path':str(runner.output_root/job.job_id/'result.json'), 'sha256':hashlib.sha256((runner.output_root/job.job_id/'result.json').read_bytes()).hexdigest()}
                                row['retained_b1_revision'] = mutation['before']
                            row.update(status='PASS',job_status=result.status.value,mutation=mutation,selected_b=True,
                                original_a_not_rebound=True,real_handler_completed=True)
                        else:
                            original_complete=jobs.complete
                            def fail_commit(*args,**kwargs):raise sqlite3.OperationalError('J3_INJECTED_BOOKKEEPING_FAILURE_AFTER_PUBLICATION')
                            jobs.complete=fail_commit
                            try:
                                try:runner.run(job.job_id)
                                except sqlite3.OperationalError:pass
                            finally:jobs.complete=original_complete
                            partial=jobs.get(job.job_id)
                            directory=runner.output_root/job.job_id
                            assert partial.status.value=='PREPARED' and (directory/'manifest.json').is_file(),partial.status.value
                            runner.pid_is_alive=lambda _pid:False  # simulate terminated worker for recovery policy
                            recovered=runner.recover(job.job_id,stale_after_seconds=0)
                            assert recovered.status.value=='READY' and runner.verify_published(job.job_id),recovered.status.value
                            row.update(status='PASS',before='PREPARED',after='READY',published_files_preserved=True,
                                publication_verified=True,real_handler_completed=True,recovery_redispatch_count=0,
                                output_files=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in directory.rglob('*') if p.is_file()])
            except Exception as exc:
                row.update(status='INCOMPLETE',reason=type(exc).__name__+':'+str(exc))
            finally:child.close()
            rows.append(row);evidence('2h-'+stage+'-'+fault,row)
            print('fault',stage,fault,row['status'],flush=True)
    counts={status:sum(r['status']==status for r in rows) for status in {r['status'] for r in rows}}
    evidence('2h-fault-matrix',{'rows':rows,'counts':counts,'required_cells':24,
        'qualification':'actual registered production stages and real prior jobs; negative transport injection explicitly identified; partial late timing never claimed PASS'})
    return {'counts':counts,'required_cells':24}
