"""Revision-bound W7 reruns using W6 handlers and publication contracts.

Job databases are operational bookkeeping outside the authoritative state DB.
Computed artifacts and ToolExecution/EvidenceCard publication remain W6-owned.
"""
from pathlib import Path
import hashlib
import json
from urban_design.week7.real_service import digest
from urban_design.week7.service import Week7Refusal
from urban_design.generation.job_store import JobStatus, IdempotencyConflict


def reconcile_e1_unknown(service, jobs, runner, job):
    """Inspect durable E1 evidence for an unknown job without dispatching it."""
    if job.status is not JobStatus.OUTCOME_UNKNOWN:
        raise ValueError('E1 reconciliation requires OUTCOME_UNKNOWN')
    request = job.request
    expected_scenarios = {request.get('baseline_scenario_id'), request.get('modified_scenario_id')}
    candidates = []
    for run in service.store.list_current('ToolExecution', project_id=job.project_id):
        parameters = run.payload.get('parameters') or {}
        pins = parameters.get('scenario_pins') or []
        if (run.payload.get('scenario_id') != request.get('modified_scenario_id')
                or {pin.get('scenario_id') for pin in pins if isinstance(pin, dict)} != expected_scenarios):
            continue
        hashes = []
        output_ids = run.payload.get('output_artifact_refs') or []
        expected_hashes = run.payload.get('output_artifact_hashes') or []
        for index, artifact_id in enumerate(output_ids):
            try:
                artifact = service.record(artifact_id, 'Artifact')
                expected = expected_hashes[index] if index < len(expected_hashes) else None
                declared = artifact.payload.get('sha256')
                bundle = artifact.payload.get('bundle')
                observed = None
                if isinstance(bundle, dict):
                    raw = json.dumps(bundle, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')
                    observed = 'sha256:' + hashlib.sha256(raw).hexdigest()
                hashes.append({'artifact_id': artifact_id, 'expected_sha256': expected,
                               'declared_sha256': declared, 'observed_bundle_sha256': observed,
                               'verified': bool(expected and expected == declared == observed)})
            except (Week7Refusal, TypeError, ValueError):
                hashes.append({'artifact_id': artifact_id, 'verified': False})
        candidates.append({'tool_execution_id': run.entity_id, 'scenario_id': run.payload.get('scenario_id'),
                           'scenario_pins': pins, 'output_hashes': hashes})

    def files_under(directory):
        if not directory.is_dir():
            return []
        return [{'path': str(path.relative_to(directory)),
                 'sha256': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(directory.rglob('*')) if path.is_file()]

    staging_files = files_under(runner.staging_root / job.job_id)
    published_files = files_under(runner.output_root / job.job_id)
    receipt_path = runner.staging_root / job.job_id / 'handler-entry-receipt.json'
    try:
        dispatch_receipts = [json.loads(receipt_path.read_bytes())] if receipt_path.is_file() else []
    except (OSError, json.JSONDecodeError):
        dispatch_receipts = [{'status': 'UNREADABLE', 'path': receipt_path.name}]
    return {
        'status': 'UNRESOLVED',
        'redispatch_allowed': False,
        'candidate_attribution': 'UNIQUE_SCENARIO_MATCH' if len(candidates) == 1 else 'AMBIGUOUS_SCENARIO_MATCH',
        'candidate_tool_executions': candidates,
        'staging_files': staging_files,
        'published_files': published_files,
        'process_observation': {'status': 'NOT_RECORDED',
                                'reason': 'E1 handler entry receipt 不包含引擎完成狀態或子程序識別資料。'},
        'dispatch_receipts': dispatch_receipts,
        'job_events': [{'seq': event.seq, 'status': event.to_status.value, 'reason': event.reason}
                       for event in jobs.events(job.job_id)],
    }


def execute_e1_rerun(service, ws, body, request):
    from urban_design.environment.router import _approved_handler
    from urban_design.environment.plan_service import approved_plan, open_e1_jobs, RESULT_NAME, STAGE, PlanNotApproved
    from urban_design.environment.contracts import E1PipelineRunResult
    store=service.store
    try:
        loaded=approved_plan(store,body.plan_artifact_id,ws.project_id)
    except PlanNotApproved as exc:
        raise Week7Refusal('E1_PLAN_NOT_APPROVED',{'reason':str(exc)}) from exc
    if (loaded.plan.baseline_scenario_id,loaded.plan.modified_scenario_id)!=(body.baseline_scenario_id,body.modified_scenario_id):
        raise Week7Refusal('E1_PLAN_SCENARIO_PAIR_NOT_BOUND',{})
    from urban_design.environment.plan_service import verify_scenario_inputs
    from fastapi import HTTPException
    try:
        # Validate the plan's current immutable scenario inputs before opening
        # an operational job store. The handler repeats this check at dispatch.
        verify_scenario_inputs(store, loaded.plan, ws.project_id)
    except PlanNotApproved as exc:
        raise Week7Refusal('E1_PLAN_INPUT_BINDING_REFUSED', {'reason': str(exc)}) from exc
    except HTTPException as exc:
        raise Week7Refusal('E1_SCENARIO_GEOMETRY_REFUSED', {'reason': str(exc.detail)}) from exc
    from urban_design.decision_resolution import latest_accepted_workspace
    try:
        ws, _ = latest_accepted_workspace(store, ws.project_id, workspace_id=ws.entity_id)
    except (ValueError, KeyError, TypeError) as exc:
        raise Week7Refusal('D1_WORKSPACE_NOT_ACCEPTED', {'reason': str(exc)}) from exc
    baseline=service.selected(ws,body.baseline_scenario_id)
    modified=service.selected(ws,body.modified_scenario_id)
    if baseline.entity_id==modified.entity_id:
        raise Week7Refusal('distinct_scenarios_required',{})
    # Capture actual server-owned immutable refs. No caller approval flag, hash
    # or computed value enters this boundary.
    refs=[{'id':loaded.artifact_id,'sha256':loaded.sha256,'kind':'e1_experiment_plan'}]
    pins=[]
    for scenario in (baseline,modified):
        artifact,_=service.artifact(scenario.payload['geometry_artifact_id'],ws.project_id)
        if artifact.payload['sha256']!=scenario.payload['geometry_sha256']:
            raise Week7Refusal('geometry_hash_mismatch',{})
        refs.append({'id':artifact.entity_id,'sha256':artifact.payload['sha256'],'kind':'scenario_geometry'})
        pins.append((scenario.entity_id,scenario.revision,scenario.payload['geometry_sha256']))
    expected=digest({'workspace_revision':ws.revision,'scenario_pins':pins,'plan_sha256':loaded.sha256})
    jobs,runner,out=open_e1_jobs(store,getattr(request.app.state,'e1_job_database',None),_approved_handler(store))
    if Path(jobs.database_path).resolve()==Path(store.database).resolve():
        raise Week7Refusal('job_database_must_be_separate',{})
    def current(job):
        try:
            if latest_accepted_workspace(store, ws.project_id, workspace_id=ws.entity_id)[0].revision!=ws.revision:return False
            for entity_id,revision,geometry_hash in pins:
                row=service.record(entity_id,'DesignScenario')
                if row.revision!=revision or row.payload.get('geometry_sha256')!=geometry_hash:return False
            now=approved_plan(store,loaded.artifact_id,ws.project_id)
            return (now.sha256,now.revision,now.decision_id)==(loaded.sha256,loaded.revision,loaded.decision_id)
        except (Week7Refusal,PlanNotApproved,ValueError,KeyError,TypeError):return False
    runner.revision_is_current=current
    try:
        job,created=jobs.enqueue(project_id=ws.project_id,idempotency_key='w7-e1:'+body.idempotency_key,stage=STAGE,
            request={'project_id':ws.project_id,'plan_artifact_id':loaded.artifact_id,'decision_id':loaded.decision_id,
                     'baseline_scenario_id':baseline.entity_id,'modified_scenario_id':modified.entity_id},
            input_refs=refs,expected_revision=expected)
    except IdempotencyConflict as exc:
        raise Week7Refusal('idempotency_conflict',{}) from exc
    finished=runner.run(job.job_id)
    if finished.status!=JobStatus.READY:
        payload = {'status':finished.status.value,'job_id':job.job_id,'created':created,'input_refs':refs,
                   'reconciliation_required':finished.status==JobStatus.OUTCOME_UNKNOWN,'published_as_current':False}
        if finished.status == JobStatus.OUTCOME_UNKNOWN:
            payload['reconciliation'] = reconcile_e1_unknown(service, jobs, runner, finished)
        return payload
    if not current(finished) or not runner.verify_published(job.job_id):
        raise Week7Refusal('OUTCOME_UNKNOWN',{'job_id':job.job_id,'reason':'Current input or publication integrity check failed; do not redispatch'})
    payload=json.loads((out/job.job_id/RESULT_NAME).read_bytes())
    result=E1PipelineRunResult.model_validate(payload)
    return {'status':'READY','job_id':job.job_id,'created':created,'input_refs':refs,'result':result.model_dump(mode='json')}


def project_job_states(service, workspace_id, scenario_id, configured):
    """Read existing operational stores; no tables, retries or publication here."""
    import sqlite3
    from pydantic import BaseModel, ConfigDict
    class JobProjection(BaseModel):
        model_config=ConfigDict(extra='forbid')
        stage: str
        job_id: str
        status: str
        expected_revision: str | None
        scenario_bound: bool
        publication_status: str
        is_current_revision: bool
        source_scenario_id: str | None
        source_revision: int | None
    ws=service.workspace(workspace_id)
    scenario=service.selected(ws,scenario_id)
    from urban_design.analysis_lineage import scenario_lineage
    lineage_ids = set(scenario_lineage(service.store, scenario))
    projected=[];missing=[]
    for label,database in configured.items():
        path=Path(database)
        if path.resolve()==Path(service.store.database).resolve():
            raise Week7Refusal('job_database_must_be_separate',{})
        if not path.is_file():
            missing.append({'stage':label,'status':'JOB_STORE_ABSENT'});continue
        try:
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as c:
                c.row_factory=sqlite3.Row
                rows=c.execute('SELECT job_id,stage,status,expected_revision,request_json,input_refs_json,output_manifest_ref,output_manifest_sha256,output_refs_json FROM generation_jobs WHERE project_id=? ORDER BY created_at',(ws.project_id,)).fetchall()
            for row in rows:
                body=json.loads(row['request_json']);refs=json.loads(row['input_refs_json'])
                bound=scenario.entity_id in {body.get('scenario_id'),body.get('baseline_scenario_id'),body.get('modified_scenario_id')} or scenario.payload.get('geometry_artifact_id') in {r['id'] for r in refs}
                pins = []
                plan_id = body.get('plan_id') or body.get('plan_artifact_id')
                if plan_id:
                    plan = service.record(plan_id, 'Artifact')
                    if row['stage'] == 'E2_RADIATION':
                        _, document = service.artifact(plan_id, ws.project_id)
                        pins = [document[name] for name in ('baseline','modified')]
                    else:
                        pins = plan.payload.get('plan', {}).get('frozen_inputs', [])
                relevant = next((pin for pin in pins if pin['scenario_id'] == scenario.entity_id), None)
                relevant = relevant or next((pin for pin in pins if pin['scenario_id'] in lineage_ids), None)
                bound = bound or relevant is not None
                is_current = bool(relevant and relevant['scenario_id'] == scenario.entity_id)
                for pin in pins:
                    source = service.record(pin['scenario_id'], 'DesignScenario')
                    if (source.revision != pin.get('scenario_revision', pin.get('revision'))
                            or source.payload.get('geometry_sha256') != pin['geometry_sha256']):
                        is_current = False
                status = row['status']
                if status == 'READY' and bound and not is_current:
                    status = 'STALE_FOR_CURRENT_CONTEXT'
                publication='NOT_PUBLISHED'
                if status in {'READY','STALE_LATE_RESULT','STALE_FOR_CURRENT_CONTEXT'}:
                    # READY is a job flag; integrity remains explicitly unverified
                    # until the registered W6 runner reconciles its manifest.
                    publication='REQUIRES_REGISTERED_RUNNER_VERIFICATION'
                projected.append(JobProjection(stage=row['stage'],job_id=row['job_id'],status=status,
                    expected_revision=row['expected_revision'],scenario_bound=bound,publication_status=publication,
                    is_current_revision=is_current,source_scenario_id=relevant['scenario_id'] if relevant else None,
                    source_revision=relevant.get('scenario_revision',relevant.get('revision')) if relevant else None).model_dump())
        except (sqlite3.Error,ValueError,KeyError,Week7Refusal) as exc:
            missing.append({'stage':label,'status':'JOB_STATE_UNAVAILABLE','reason':str(exc)})
    return {'jobs':projected,'unavailable':missing,'authoritative':False,
            'reason':'Existing job stores hold scheduling and dispatch bookkeeping; immutable computed entities remain in ProjectStateStore.'}
