"""Real W7 E1 rerun uses an approved draft pin and retains earlier artifacts."""
from types import SimpleNamespace
from datetime import datetime, timezone
from urban_design.models import ActorKind, HumanDecision
from urban_design.geometry import canonical_geometry_hash
from urban_design.workspace_contracts import WorkspaceRevision
from urban_design.approved_generation import _workspace_payload_digest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_environment_plan_approval import _store, _key
from test_decision_resolution_pipeline import decide
from urban_design.environment.plan_service import persist_e1_plan_artifact
from urban_design.environment.router import get_default_draft_plan, router
from urban_design.week7.router import create_week7_router


def test_real_w7_rerun_parent_execution_to_draft_is_unverified(tmp_path):
    store = _store(tmp_path)
    key, path = _key(tmp_path)
    try:
        # J6 requires a genuinely accepted D1 workspace before W7 dispatch.
        # Use the existing temporary test key; do not bypass the resolver.
        geometry = {'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,0]]]}
        geometry_hash = canonical_geometry_hash(geometry)
        store.create('StudyArea', {'id':'j4-study','status':'CONFIRMED_FOR_EXPLORATION','geometry_sha256':geometry_hash},
                     entity_id='j4-study',project_id='project-e1')
        workspace = WorkspaceRevision(workspace_id='j4-ws',project_id='project-e1',study_area_id='j4-study',revision=1,
            spatial_brief={'exploration_design_area':{'geometry':geometry}})
        ws_payload = workspace.model_dump(mode='json')
        ws_payload['payload_digest'] = _workspace_payload_digest(workspace).removeprefix('sha256:')
        ws = store.create('WorkspaceRevision', ws_payload, entity_id='j4-ws',project_id='project-e1')
        approval = HumanDecision(id='j4-workspace-approve',project_id='project-e1',target_id=ws.entity_id,
            target_type='WorkspaceRevision',target_version='1',target_geometry_sha256=geometry_hash,
            target_payload_digest='sha256:'+ws_payload['payload_digest'],action='Approve',status='approved',
            actor='test-founder',actor_kind=ActorKind.HUMAN_UI,actor_session_id='j4-test',
            reason='FIXTURE_ONLY D1 acceptance required by J6',timestamp=datetime(2020,1,1,tzinfo=timezone.utc))
        store.record_human_decision(approval,decision_key=key,decision_key_path=path)
        app = FastAPI(); app.state.project_store = store
        app.state.e1_job_database = tmp_path/'jobs.sqlite3'
        app.include_router(router); app.include_router(create_week7_router(store))
        client = TestClient(app)
        plan = get_default_draft_plan().model_copy(update={'baseline_scenario_id':'formal-baseline','modified_scenario_id':'formal-proposal'})
        old_plan = persist_e1_plan_artifact(store,plan,'project-e1')
        decide(store,old_plan,key,path,'Approve','j4-old-plan',2026)
        old = client.post('/api/environment/e1/simulate',json={'project_id':'project-e1','plan_artifact_id':old_plan.entity_id,
            'baseline_scenario_id':'formal-baseline','modified_scenario_id':'formal-proposal'})
        assert old.status_code == 200, old.text
        old = old.json()
        from urban_design.analysis_lineage import analysis_results
        baseline_analyses = analysis_results(store, store.current('formal-baseline'))
        assert any(v['execution_id'] == old['tool_execution']['id'] for v in baseline_analyses)
        old_artifact = store.current(old['artifact']['id']).to_dict()
        parent = store.current('formal-proposal')
        payload = parent.as_dict(); payload.update(id='j4-draft',status='draft',parent_scenario_id=parent.entity_id)
        payload['parameters'] = {**payload['parameters'],'provenance':'FORMAL_DRAFT','parent_revision':parent.revision,
                                 'parent_geometry_sha256':parent.payload['geometry_sha256']}
        draft = store.create('DesignScenario',payload,entity_id='j4-draft',project_id='project-e1')
        new_plan = persist_e1_plan_artifact(store,plan.model_copy(update={'modified_scenario_id':draft.entity_id}),'project-e1')
        body = {'target':{'entity_id':old['tool_execution']['id'],'revision':1},'stage':'E1','plan_artifact_id':new_plan.entity_id,
                'baseline_scenario_id':'formal-baseline','modified_scenario_id':draft.entity_id,'idempotency_key':'j4-new'}
        assert client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun',json=body).status_code == 409
        decide(store,new_plan,key,path,'Approve','j4-new-plan',2026)
        response = client.post(f'/api/v1/week7/workspaces/{ws.entity_id}/rerun',json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['status'] == 'READY'
        assert result['result']['run_id'] != old['run_id']
        assert result['result']['tool_execution']['scenario_id'] == draft.entity_id
        assert result['result']['evidence_card']['validation_status'] == 'unverified'
        assert store.current(result['result']['evidence_card']['id']).payload['validation_status'] == 'unverified'
        assert store.current(old['artifact']['id']).to_dict() == old_artifact
        assert result['result']['tool_execution']['parameters']['scenario_revision'] == draft.revision
    finally:
        store.close()
