#!/usr/bin/env python3
"""J3 real-data TestClient walkthrough; authority is opened mode=ro for backup.

No product patches, fake computed values, live provider, service or browser.
Every invocation creates a fresh temp database/key and exclusive evidence tree.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import traceback
import uuid
from fastapi.testclient import TestClient
from shapely.geometry import shape
from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore
from urban_design.decision_key import initialize_decision_key
from urban_design.environment.plan_service import persist_e1_plan_artifact
from urban_design.environment.router import get_default_draft_plan

AUTHORITY = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')
EXPECTED = '2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366'
WORKTREE = Path(__file__).resolve().parents[2]

def utc():
    return subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'], text=True).strip()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)

def run(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix='q5-j3-w67-', dir='/private/tmp'))
    assert sha(AUTHORITY) == EXPECTED
    database = root/'copy.sqlite3'
    with sqlite3.connect(AUTHORITY.as_uri()+'?mode=ro', uri=True) as source:
        with sqlite3.connect(database) as dest:
            source.backup(dest)
    key_path = root/'test-decision-key'
    secret = 'J3-test-'+uuid.uuid4().hex
    initialize_decision_key(path=key_path, password_prompt=lambda _: secret)
    store = ProjectStateStore(database)
    steps = {}
    receipts = []
    context = {}
    def evidence(label, document):
        path = output/(label+'.json')
        save(path, {'utc':utc(), **document})
        receipts.append({'path':str(path),'sha256':sha(path)})
        return document
    def call(label, method, url, body=None, expected=(200,201)):
        kwargs = {'json':body} if body is not None else {}
        response = client.request(method, url, **kwargs)
        try: data = response.json()
        except ValueError: data = {'text':response.text}
        scrubbed = {k:v for k,v in (body or {}).items() if k!='decision_key'}
        evidence(label, {'method':method,'url':url,'request':scrubbed,
                         'http_status':response.status_code,'response':data})
        assert response.status_code in expected, f'{label}: HTTP {response.status_code}: {response.text[:1000]}'
        return data
    def step(name, fn, dependency=None):
        if dependency and steps.get(dependency,{}).get('status')!='PASS':
            steps[name]={'status':'BLOCKED_DEPENDENCY','dependency':dependency}
            evidence(name+'-blocked',steps[name]);return
        try:
            value=fn()
            steps[name]={'status':'PASS','summary':value}
        except Exception as exc:
            steps[name]={'status':'INCOMPLETE','exception':type(exc).__name__,'reason':str(exc)}
            evidence(name+'-failure',{'traceback':traceback.format_exc(),**steps[name]})
        print(name, steps[name]['status'], flush=True)
    def new_app():
        app = create_workspace_app(store=store, decision_key_path=key_path,
            scenario_artifact_root=root/'scenario-artifacts', allow_live_critic=False)
        app.state.e1_job_database=root/'e1-jobs.sqlite3'
        app.state.e2_job_database=root/'e2-jobs.sqlite3'
        app.state.e2_artifact_root=root/'e2-artifacts'
        return app
    evidence('00-isolation',{'database_copy':str(database),'authority_sha256':EXPECTED,'runner_sha256':sha(__file__),
        'fault_runner_sha256':sha(Path(__file__).with_name('w67_fault_jobs.py')),'test_key_scope':'temporary directory only; never exported'})
    app=new_app()
    ws=store.list_current('WorkspaceRevision')[0]
    project=ws.project_id
    base=f'/api/v1/week7/workspaces/{ws.entity_id}'
    def target(sid):
        row=store.current(sid);return {'entity_id':sid,'revision':row.revision}
    def approve(plan, label):
        field = 'target_artifact_sha256' if plan.entity_type=='Artifact' else 'target_payload_digest'
        value = plan.payload['sha256'] if plan.entity_type=='Artifact' else plan.payload['payload_digest']
        return call(label,'POST',f'/api/v1/projects/{project}/decisions',{
            'target_id':plan.entity_id,'target_type':plan.entity_type,'target_version':str(plan.payload.get('version',plan.revision)),
            field:value,'action':'Approve','status':'approved',
            'reason':'J3 disposable copy rehearsal only; no Founder production decision',
            'decision_key':secret,'actor_session_id':'j3-w67-test-session'})
    def selection(label):
        ids=context['ids'];selected=context['selected']
        return call(label,'POST','/api/v1/scenarios/comparison/decision',{
            'project_id':project,'scenario_ids':ids,'accepted_scenario_id':selected,
            'acceptance_reason':'J3 copy-only selection: grid-mixed retained for the edit walkthrough',
            'rejected_reasons':{sid:'J3 copy-only rejection: alternate '+store.current(sid).payload['parameters']['recipe_id']+' retained in history for comparison' for sid in ids if sid!=selected},
            'decision_key':secret,'actor_session_id':'j3-w67-test-session'})
    with TestClient(app) as client:
        def generation():
            route=f'/api/v1/projects/{project}/generation-workflows'
            ready=call('2a-readiness','GET',route+'/readiness')
            assert ready['readiness']=='APPROVED',ready
            start=call('2a-start','POST',route,{'idempotency_key':'j3-generation-r4','mode':'FULL_SCHEME'})
            context['workflow']=start['workflow_id']
            done=call('2a-generation-job','POST',route+'/'+start['workflow_id']+'/advance')
            assert done['job_status']=='READY',done
            path=root/'scenario-artifacts/generation/jobs'/done['job_id']/'formal-results.json'
            report=json.loads(path.read_bytes())
            evidence('2a-generation-report',{'report':report,'report_path':str(path),'sha256':sha(path)})
            assert report['status']=='READY' and len(report['scenario_ids'])==5,report['status']
            assert report['authored_recipe_settings']['south_strip_collector']['provenance']=='FOUNDER_DECISION_2026-10-04'
            context['ids']=report['scenario_ids']
            context['selected']=next(s for s in context['ids'] if store.current(s).payload['parameters']['recipe_id']=='grid-mixed')
            context['generation_job']=done['job_id']
            context['baseline']=next(r.entity_id for r in store.list_current('DesignScenario',project_id=project) if r.entity_id not in context['ids'] and r.payload.get('parameters',{}).get('recipe_id')=='grid-mixed')
            return {'count':5,'recipe_version':report['authored_recipe_settings'].get('version',store.current(context['selected']).payload['generator']),
                'geometry_hashes':{store.current(s).payload['parameters']['recipe_id']:store.current(s).payload['geometry_sha256'] for s in context['ids']}}
        step('2a',generation)
        def select():
            selection('2b-selection')
            statuses={store.current(s).payload['parameters']['recipe_id']:store.current(s).payload['status'] for s in context['ids']}
            assert list(statuses.values()).count('accepted')==1 and list(statuses.values()).count('rejected')==4,statuses
            return statuses
        step('2b',select,'2a')
        def e1():
            sid=context['selected']
            plan=get_default_draft_plan().model_copy(update={'baseline_scenario_id':context['baseline'],'modified_scenario_id':sid})
            record=persist_e1_plan_artifact(store,plan,project)
            evidence('2c-plan',{'artifact':record.to_dict()})
            approve(record,'2c-plan-approve')
            result=call('2c-e1','POST','/api/environment/e1/simulate',{'project_id':project,
                'baseline_scenario_id':context['baseline'],'modified_scenario_id':sid,'plan_artifact_id':record.entity_id})
            assert result['status']=='SUCCESS',result.get('blocked_reason')
            context['e1']=result
            artifact=store.current(result['artifact']['id'])
            context['old_artifact']=artifact.to_dict()
            context['old_artifact_digest']=hashlib.sha256(json.dumps(artifact.to_dict(),sort_keys=True).encode()).hexdigest()
            return {'status':result['status'],'engine':result['metadata']['engine'],'bound_to_accepted':True,
                    'sensor_count':len(result['modified_sunlight']['results']),'cross_check':result['metadata']['cross_check']['status'],
                    'baseline_mean_hours':result['baseline_march_21_statistics']['mean_hours'],
                    'modified_mean_hours':result['modified_march_21_statistics']['mean_hours']}
        step('2c',e1,'2b')
        def edit():
            draft=call('2d-formal-draft','POST',f'/api/v1/scenarios/{context["selected"]}/formal-draft')
            sid=draft['scenario_id'];context['draft']=sid
            building=next(b for b in draft['editor']['editable_buildings'] if len(b['floors'])>1 and all(shape(f['geometry']).geom_type=='Polygon' and not shape(f['geometry']).interiors for f in b['floors']))
            bid=building['building_id'];context['building']=bid
            top=max(building['floors'],key=lambda f:f['level'])
            mass=call('2d-massing','POST',f'/api/v1/scenarios/{sid}/edits',{'building_id':bid,
                'command':{'type':'remove_floor','floor_id':top['floor_id']},'expected_revision':0,'idempotency_key':'j3-remove-floor'})
            faces=call('2d-faces','GET',f'/api/v1/scenarios/{sid}/editing/faces?building_id={bid}')
            face=next(f for f in faces['faces'] if f['kind']=='SIDE')
            poly=shape(face['geometry']);xmin,_,xmax,_=poly.bounds;y=poly.centroid.y
            split=call('2d-split','POST',f'/api/v1/scenarios/{sid}/editing/faces',{'building_id':bid,'operation':'SPLIT_LINE',
                'face_id':face['id'],'points':[[xmin-1,y],[xmax+1,y]],'steps':1,'parent_revision':faces['face_revision'],
                'expected_scenario_revision':faces['scenario_revision'],'expected_geometry_hash':faces['geometry_hash'],'idempotency_key':'j3-split'})
            context['edit_responses']=[mass,split]
            return {'massing':True,'face_split':True,'draft_revision':store.current(sid).revision}
        step('2d',edit,'2b')
        def stale():
            old=context['e1'];draft=store.current(context['draft'])
            current=call('2e-view','GET',base+'/view?scenario_id='+draft.entity_id)
            statuses=draft.payload['parameters'].get('e1_statuses',{})
            evidence('2e-lineage',{'draft':draft.to_dict(),'old_artifact':store.current(old['artifact']['id']).to_dict(),
                'old_execution':store.current(old['tool_execution']['id']).to_dict(),'view':current,'e1_statuses':statuses})
            assert 'STALE' in {str(v).upper() for v in statuses.values()}, 'Computed accepted-scenario E1 absent from draft e1_statuses; no bound-result STALE proof'
            projected = next(v for v in current['analysis_results'] if v['execution_id'] == old['tool_execution']['id'])
            assert projected['freshness'] == 'stale' and projected['source_scenario_id'] == context['selected']
            return {'old_result_stale':True}
        step('2e',stale,'2c' if steps.get('2c',{}).get('status')!='PASS' else '2d')
        def rerun():
            sid=context['draft'];baseline=context['selected']
            plan=get_default_draft_plan().model_copy(update={'baseline_scenario_id':baseline,'modified_scenario_id':sid})
            record=persist_e1_plan_artifact(store,plan,project);approve(record,'2f-plan-approve')
            context['rerun_plan']=record.entity_id
            old=context['e1'];execution=target(old['tool_execution']['id'])
            body={'target':execution,'stage':'E1','plan_artifact_id':record.entity_id,'baseline_scenario_id':baseline,
                  'modified_scenario_id':sid,'idempotency_key':'j3-rerun-after-edit'}
            result=call('2f-w7-rerun','POST',base+'/rerun',body,expected=(200,409))
            if result.get('status')!='READY':
                # Keep the W7 failure receipt; independent W6 API still exercises the fresh plan.
                context['w7_rerun_refusal']=result
                result=call('2f-e1-new-plan','POST','/api/environment/e1/simulate',{'project_id':project,
                    'baseline_scenario_id':baseline,'modified_scenario_id':sid,'plan_artifact_id':record.entity_id})
            else:result=result['result']
            assert result['status']=='SUCCESS' and result['run_id']!=old['run_id']
            assert result['evidence_card']['validation_status'] == 'unverified'
            assert store.current(result['evidence_card']['id']).payload['validation_status'] == 'unverified'
            assert result['tool_execution']['parameters']['scenario_revision'] == store.current(sid).revision
            assert any(v['scenario_id'] == sid and v['geometry_sha256'] == store.current(sid).payload['geometry_sha256'] for v in result['tool_execution']['parameters']['scenario_pins'])
            digest=hashlib.sha256(json.dumps(store.current(old['artifact']['id']).to_dict(),sort_keys=True).encode()).hexdigest()
            assert digest==context['old_artifact_digest'],'old result overwritten'
            context['rerun']=result
            evidence('2f-history',{'old_artifact_unchanged':True,'old_artifact_digest':digest,'new_run_id':result['run_id'],'old_run_id':old['run_id']})
            assert 'w7_rerun_refusal' not in context,'W7 Rerun refused old accepted execution for new draft; W6 fresh run succeeded separately'
            return {'new_run':True,'old_result_preserved':True}
        step('2f',rerun,'2c' if steps.get('2c',{}).get('status')!='PASS' else '2d')
        def e2():
            from urban_design.environment.weather_snapshot import publish_candidate01
            from urban_design.environment.e2_service import validate_methods, ScenarioPin, scenario_geometry, E2Plan
            from urban_design.environment.contracts import GroundGridDefinition
            proposal=WORKTREE/'artifacts/w5-weather-derived-method-proposal-20260926T115309Z'
            snapshot=publish_candidate01(store,project,proposal,WORKTREE,root/'weather-artifacts')
            evidence('2f-e2-weather',{'snapshot':snapshot.to_dict(),'scope':'Temporary test-key decision only; PD08 assumption retained; supplier semantics unproven'})
            approve(snapshot,'2f-e2-weather-test-approve')
            validation=validate_methods(store,project,snapshot.entity_id,root/'method-qualification')
            evidence('2f-e2-qualification',{'artifact':validation.to_dict(),'receipt':json.loads(Path(validation.payload['uri']).read_bytes())})
            pins=[]
            for sid in (context['selected'],context['draft']):
                row=store.current(sid)
                pin=ScenarioPin(scenario_id=sid,revision=row.revision,geometry_artifact_id=row.payload['geometry_artifact_id'],
                    geometry_sha256=row.payload['geometry_sha256'],environment_sha256='sha256:'+'0'*64)
                geometry,meta=scenario_geometry(store,pin,project)
                pins.append(pin.model_copy(update={'environment_sha256':meta['environment_sha256']}))
            x,y,_,_=geometry.site_area.bounds
            plan=E2Plan(project_id=project,weather_snapshot_id=snapshot.entity_id,weather_bundle_sha256=snapshot.payload['payload_digest'],
                baseline=pins[0],modified=pins[1],grid=GroundGridDefinition(origin_x=x,origin_y=y,spacing_m=5,crs='EPSG:28992',tag='J3_REAL_DATA_DISPOSABLE_COPY'),
                true_north_deg=0,method_validation_artifact_id=validation.entity_id)
            response=call('2f-e2-plan','POST','/api/v1/environment/e2/plan',plan.model_dump(mode='json'))
            record=store.current(response['plan_artifact_id']);approve(record,'2f-e2-plan-test-approve')
            context['e2_plan']=record.entity_id
            ready=call('2f-e2-ready','GET','/api/v1/environment/e2/readiness?project_id='+project+'&plan_artifact_id='+record.entity_id)
            assert ready['dispatch_allowed'],ready
            result=call('2f-e2-run','POST','/api/v1/environment/e2/simulate',{'project_id':project,'plan_artifact_id':record.entity_id,'idempotency_key':'j3-e2-real'})
            context['e2']=result
            assert result['status']=='SUCCEEDED',result
            for comparison in result['comparisons']['honeybee_radiance'].values():
                noise = comparison['noise_metadata']
                assert noise['sample_count'] >= 3 and noise['classification'] == 'ASSUMED_COMMANDER'
                assert comparison['direction'] == noise['direction']
                if abs(noise['delta_mean_kwh_m2']) <= noise['threshold_kwh_m2']:
                    assert comparison['direction'] == 'NOT_SIGNIFICANT'
            draft_runs = [v for shifts in result['results'].values() for pair in shifts.values() for v in pair if v['scenario_id'] == context['draft']]
            assert draft_runs and all(v['records']['evidence_validation_status'] == 'unverified' for v in draft_runs)
            return {'status':result['status'],'methods':sorted(result['results']),'runs':sum(len(pair) for shifts in result['results'].values() for pair in shifts.values()),
                'weather_semantics':'PD08 assumption; NOT_SUPPLIER_PROVEN','method_qualification':'FIXTURE_ONLY',
                'comparison_statistics':result['comparisons']}
        step('2f-e2',e2,'2d')
        def panels():
            sid=context.get('draft',context['selected'])
            call('2g-switch','POST',base+'/switch',{'target':target(sid),'workspace_revision':ws.revision})
            view=call('2g-panels','GET',base+'/view')
            names={'dashboard','chart','ai','export','compare','map','model3d'}
            actual=set(view['panels'])
            assert names==actual,f'7-panel keys expected {sorted(names)}, actual {sorted(actual)}'
            revisions={p['revision'] for p in view['panels'].values()}
            assert revisions=={view['revision']},revisions
            context['view']=view
            return {'panels':sorted(actual),'single_revision':True,'scenario_revision':view['scenario_ref']['revision']}
        step('2g',panels,'2d')
        def faults():
            from w67_fault_jobs import run_faults
            result=run_faults(parent_store=store,app=app,context=context,root=root/'faults',key_path=key_path,
                workspace_id=ws.entity_id,evidence=evidence)
            context['faults']=result
            assert result['counts'].get('PASS',0)==24, f"Real job fault matrix incomplete: {result}"
            return result
        step('2h',faults,'2a')
        def reconsider():
            ids=context['ids']
            for i,sid in enumerate(ids):
                row=store.current(sid)
                call(f'2i-reconsider-{i}','POST','/api/v1/scenarios/reconsider',{'project_id':project,'scenario_id':sid,
                    'target_version':str(row.revision),'target_geometry_sha256':row.payload['geometry_sha256'],
                    'reason':'J3 copy-only reconsideration followed by new selection','decision_key':secret,'actor_session_id':'j3-w67-test-session'})
                assert store.current(sid).payload['status']=='proposed'
            result=selection('2i-reselect')
            return {'reconsidered':5,'accepted':1,'rejected':4,'history_preserved':all(len(store.history(s))>=4 for s in ids)}
        def figures():
            sid=context.get('draft',context['selected'])
            results={}
            for kind in ['plan','perspective','axonometric','e1','e2']:
                body={'kind':kind,'targets':[target(sid)]}
                if kind=='e1' and context.get('rerun'):body['result_artifact_ids']=[context['rerun']['artifact']['id']]
                if kind=='e2' and context.get('e2'):
                    match=next(p for p in context['e2']['results']['honeybee_radiance']['0'] if p['scenario_id']==sid)
                    body['result_artifact_ids']=[match['records']['artifact_id']]
                data=call('2j-'+kind,'POST',base+'/figures',body,expected=(200,409))
                results[kind]={'produced':'png_path' in data,'response':data}
                if data.get('png_path'):
                    assert sha(data['png_path'])==data['png_sha256']
                    copied=output/(kind+'.png')
                    with copied.open('xb') as f:f.write(Path(data['png_path']).read_bytes())
                    assert sha(copied)==data['png_sha256']
            evidence('2j-figures',{'figures':results})
            context['figures']=results
            assert all(v['produced'] for v in results.values()),'Required true-data figures missing: '+','.join(k for k,v in results.items() if not v['produced'])
            return {k:v['produced'] for k,v in results.items()}
        step('2i',reconsider,'2b')
        step('2j',figures,'2d')
        context['recovery_before']=call('2k-before-close','GET',base+'/view')
    store.close()
    store=ProjectStateStore(database)
    app=new_app()
    with TestClient(app) as client:
        def recovery():
            view=call('2k-after-reopen','GET',base+'/view')
            before=context['recovery_before']
            assert view['revision']==before['revision']
            assert view['scenario_id']==before['scenario_id'] and view['human_status']==before['human_status']
            with store.locked_connection() as c:integrity=c.execute('PRAGMA quick_check').fetchone()[0]
            assert integrity=='ok'
            return {'same_revision':True,'same_selection':True,'quick_check':integrity,'scope':'new store and app lifecycle; no server processes'}
        step('2k',recovery)
    if context.get('rerun'):
        evidence('2f-observed-w6-rerun',{'status':context['rerun']['status'],'old_result_preserved':hashlib.sha256(json.dumps(context['old_artifact'],sort_keys=True).encode()).hexdigest()==context['old_artifact_digest'],
            'method':context['rerun']['method'],'comparison':context['rerun']['comparison']})
    final={'classification':'REAL_DATA_DISPOSABLE_COPY_TESTCLIENT','utc':utc(),'database_copy':str(database),
        'authority_before_sha256':EXPECTED,'authority_after_sha256':sha(AUTHORITY),'steps':steps,
        'browser':'BLOCKED_SANDBOX_BROWSER','live_ai':'BLOCKED by Founder','receipts':receipts,
        'entity_counts':{kind:len(store.list_current(kind,project_id=project)) for kind in ['DesignScenario','HumanDecision','ToolExecution','Artifact']}}
    assert final['authority_after_sha256']==EXPECTED
    store.close()
    save(output/'summary.json',final)
    # Compare observable state summaries, not random run/decision identifiers.
    canonical={'classification':final['classification'],'steps':{k:{'status':v['status'], **({'summary':v['summary']} if 'summary' in v else {'exception':v.get('exception'), 'dependency':v.get('dependency')})} for k,v in steps.items()},'browser':final['browser'],
               'live_ai':final['live_ai'],'entity_counts':final['entity_counts']}
    save(output/'state-summary.json',canonical)
    save(output/'evidence-manifest.json',{str(p.relative_to(output)):{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(output.rglob('*')) if p.is_file()})
    print(json.dumps({'output':str(output),'statuses':{k:v['status'] for k,v in steps.items()}},ensure_ascii=False),flush=True)
    return final

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
