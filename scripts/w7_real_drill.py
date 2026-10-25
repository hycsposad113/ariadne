"""Offline W7 rehearsal on caller-owned backups; never approves a decision."""
from pathlib import Path
import hashlib
import json
import sqlite3
import argparse
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.store import ProjectStateStore
from urban_design.week7.real_service import RealWeek7Service, EntityRef
from urban_design.week7.router import create_week7_router
from urban_design.week7.service import Week7Refusal
from urban_design.generation.job_store import GenerationJobStore, JobStatus
from urban_design.generation.job_runner import GenerationJobRunner, PreparedOutput, write_prepared_manifest


def run(root: Path, source: Path):
    root.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as src,sqlite3.connect(root/'state-copy.sqlite3') as dst:src.backup(dst)
    job_source=source.with_name('job-state-evidence.sqlite3')
    with sqlite3.connect(job_source.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as src,sqlite3.connect(root/'job-copy.sqlite3') as dst:src.backup(dst)
    rows=[]
    with ProjectStateStore(root/'state-copy.sqlite3') as store:
        service=RealWeek7Service(store);ws=store.list_current('WorkspaceRevision')[0]
        scenarios=store.list_current('DesignScenario');a,b=scenarios[:2]
        app=FastAPI();app.include_router(create_week7_router(store));client=TestClient(app)
        route=f'/api/v1/week7/workspaces/{ws.entity_id}'
        target=lambda r:{'entity_id':r.entity_id,'revision':r.revision}
        view=client.get(route+'/view',params={'scenario_id':a.entity_id}).json()
        before_decisions=len(store.list_current('HumanDecision'))
        operations={}
        for kind in ['inspect','challenge','modify','rerun','compare','fork','reject','override']:
            payload={'target':target(a),'reason':'Offline copied-data rehearsal; proposed only'}
            if kind=='inspect':
                card=next(c for c in view['cards'] if c['payload'].get('scenario_id')==a.entity_id)
                payload['target']={'entity_id':card['evidence_id'],'revision':card['revision']}
            if kind=='compare':payload['compare_targets']=[target(a),target(b)]
            if kind=='fork':payload['branch_id']='w7-real-copy-fork'
            response=client.post(route+'/operations/'+kind,json=payload)
            operations[kind]={'http_status':response.status_code,'body':response.json()}
        (root/'eight-operations.json').write_text(json.dumps(operations,indent=2))
        (root/'view-before.json').write_text(json.dumps(view,indent=2))
        # Copy-owned artifact bytes are fault-injected; original result files stay unchanged.
        geometry=store.current(a.payload['geometry_artifact_id'])
        original=geometry.as_dict()
        corrupt=root/'geometry-corrupt.geojson';corrupt.write_bytes(Path(original['uri']).read_bytes()+b' ')
        store.update(geometry.entity_id,{'uri':str(corrupt)},expected_revision=geometry.revision)
        bad=service.view(ws.entity_id,a.entity_id)
        rows.append({'fault':'source_or_geometry_hash_mismatch','actual':bad['geometry_status'],'status':'PASS' if bad['geometry_status']=='artifact_hash_mismatch' else 'FAIL'})
        restored=store.current(geometry.entity_id);store.update(geometry.entity_id,{'uri':original['uri']},expected_revision=restored.revision)
        gone=store.current(geometry.entity_id);store.update(geometry.entity_id,{'uri':str(root/'missing-source.geojson')},expected_revision=gone.revision)
        absent=service.view(ws.entity_id,a.entity_id)
        rows.append({'fault':'observation_source_unavailable','actual':absent['geometry_status'],'status':'PASS' if absent['geometry_status']=='artifact_file_unavailable' else 'FAIL'})
        gone=store.current(geometry.entity_id);store.update(geometry.entity_id,{'uri':original['uri']},expected_revision=gone.revision)
        jobs=GenerationJobStore(root/'job-copy.sqlite3')
        with sqlite3.connect(jobs.database_path) as c:job_id=c.execute('SELECT job_id FROM generation_jobs ORDER BY created_at LIMIT 1').fetchone()[0]
        original_job=jobs.get(job_id)
        repeated,created=jobs.enqueue(project_id=original_job.project_id,idempotency_key=original_job.idempotency_key,
            stage=original_job.stage,request=original_job.request,input_refs=original_job.input_refs,expected_revision=original_job.expected_revision)
        rows.append({'fault':'repeated_run','actual':{'job_id':repeated.job_id,'created':created,'status':repeated.status.value},'status':'PASS' if not created and repeated.job_id==job_id else 'FAIL'})
        pinned=[{'id':a.payload['geometry_artifact_id'],'sha256':a.payload['geometry_sha256'],'kind':'scenario_geometry'}]
        disconnected,_=jobs.enqueue(project_id=ws.project_id,idempotency_key='w7-real-disconnect',stage='W7_FAULT_TRANSPORT',request={'scenario_id':a.entity_id},input_refs=pinned)
        runner=GenerationJobRunner(jobs,staging_root=root/'disconnect-staging',output_root=root/'disconnect-out')
        def lost(job,staging,token):raise ConnectionError('Injected post-dispatch transport loss; no live engine called')
        runner.register_handler('W7_FAULT_TRANSPORT','fault-transport-v1',lost,external=True)
        unknown=runner.run(disconnected.job_id);again=runner.run(disconnected.job_id)
        rows.append({'fault':'tool_disconnect','actual':{'status':unknown.status.value,'repeat_status':again.status.value},'status':'PASS' if unknown.status==JobStatus.OUTCOME_UNKNOWN and again.status==JobStatus.OUTCOME_UNKNOWN else 'FAIL','qualification':'Real input refs and existing runner; injected transport, not live E1/E2 dispatch'})
        client.post(route+'/switch',json={'target':target(b),'workspace_revision':ws.revision})
        # A late result for A remains linked to A; selected B projection excludes it.
        selected=service.view(ws.entity_id)
        ids={r['entity_id'] for r in selected['runs']}
        a_runs=[r.entity_id for r in store.list_current('ToolExecution') if r.payload.get('scenario_id')==a.entity_id]
        rows.append({'fault':'late_b1_after_b2','actual':{'selected':selected['scenario_id'],'late_result_excluded':not(set(a_runs)&ids)},'status':'PASS' if selected['scenario_id']==b.entity_id and not(set(a_runs)&ids) else 'FAIL','qualification':'Retained real A results delivered/read after B selection; no engine redispatch'})
        reopened=ProjectStateStore(root/'state-copy.sqlite3')
        try:new=RealWeek7Service(reopened).view(ws.entity_id)
        finally:reopened.close()
        rows.append({'fault':'refresh_or_restart','actual':new['revision'],'status':'PASS' if new['revision']==selected['revision'] else 'FAIL'})
        partial,_=jobs.enqueue(project_id=ws.project_id,idempotency_key='w7-real-partial',stage='W7_PUBLICATION_PROBE',request={'scenario_id':a.entity_id},input_refs=pinned)
        publication=GenerationJobRunner(jobs,staging_root=root/'partial-staging',output_root=root/'partial-out')
        def preserve_real_bytes(job,staging,token):
            raw=Path(original['uri']).read_bytes();(staging/'scene.geojson').write_bytes(raw)
            return write_prepared_manifest(staging,handler_version='real-scene-publication-probe-v1',input_refs=job.input_refs,
                output_refs=[PreparedOutput(artifact_id=geometry.entity_id,relative_path='scene.geojson',sha256='sha256:'+hashlib.sha256(raw).hexdigest(),size_bytes=len(raw))])
        publication.register_handler('W7_PUBLICATION_PROBE','real-scene-publication-probe-v1',preserve_real_bytes)
        complete=jobs.complete
        def db_failure(*args,**kwargs):raise sqlite3.OperationalError('Injected bookkeeping DB failure after atomic file publication')
        jobs.complete=db_failure
        try:publication.run(partial.job_id)
        except sqlite3.OperationalError:pass
        finally:jobs.complete=complete
        partial_state=jobs.get(partial.job_id)
        preserved=root/'partial-out'/partial.job_id/'scene.geojson'
        rows.append({'fault':'partial_publish_db_failure','actual':{'status':partial_state.status.value,'file_preserved':preserved.is_file(),'ready_claimed':partial_state.status==JobStatus.READY},'status':'PASS' if preserved.is_file() and partial_state.status!=JobStatus.READY else 'FAIL','qualification':'Real scene bytes; existing publication contract with bookkeeping fault injection'})
        wrong=service.interpret(ws.entity_id,a.entity_id,{'citations':[{'evidence_id':'unrelated-real-id'}],'stated_numbers':[99999]})
        rows.append({'fault':'ai_wrong_citation','actual':wrong['errors'],'status':'PASS' if wrong['status']=='INVALID' else 'FAIL'})
        report={'rows':rows,'scope':'Real E2 result snapshot + authoritative scenario copies; fault injections explicitly identified',
                'human_decisions_created':len(store.list_current('HumanDecision'))-before_decisions,
                'e2_original_job':{'id':original_job.job_id,'status':original_job.status.value,'input_refs':original_job.input_refs,'output_refs':original_job.output_refs},
                'generation_e1_dispatch_coverage':'INCOMPLETE; W6-owned dispatch not modified', 'operations':operations}
        (root/'fault-matrix.json').write_text(json.dumps(report,indent=2))
        return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--source',type=Path,required=True);args=parser.parse_args()
    report=run(args.root,args.source)
    print(json.dumps({'rows':[{'fault':r['fault'],'status':r['status']} for r in report['rows']], 'human_decisions_created':report['human_decisions_created']},indent=2))
