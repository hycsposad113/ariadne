"""J4 regression: real persisted lineage is visible without granting authority."""
from test_formal_editor_authority import _world, _accept
from urban_design.week7.real_service import RealWeek7Service


def test_formal_edit_exposes_parent_e1_e2_and_syntax_without_rewriting_history(tmp_path):
    store, client, secret, _, ids, geometry_hash = _world(tmp_path)
    try:
        _accept(client, secret, ids)
        parent = store.current(ids[0])
        runs = []
        for tool, kind in [('radiance','sunlight_simulation_result'),('honeybee_radiance','radiation-result'),('depthmap','syntax-result')]:
            artifact = store.create('Artifact', {'type':kind,'sha256':'sha256:'+'a'*64}, project_id=parent.project_id)
            run = store.create('ToolExecution', {'scenario_id':parent.entity_id,'tool':tool,'status':'NOT_RUN','classification':'FIXTURE_ONLY',
                'input_artifact_hashes_by_id':{'art-scenario':geometry_hash},
                'parameters':{'scenario_revision':parent.revision},'output_artifact_refs':[artifact.entity_id]}, project_id=parent.project_id)
            runs.append(run)
        opened = client.post(f'/api/v1/scenarios/{ids[0]}/formal-draft')
        assert opened.status_code == 201, opened.text
        draft_id = opened.json()['scenario_id']
        edited = client.post(f'/api/v1/scenarios/{draft_id}/edits', json={
            'building_id':'b-holed','command':{'type':'remove_floor','floor_id':'b-holed-floor-1'},
            'expected_revision':0,'idempotency_key':'j4-remove-floor'})
        assert edited.status_code == 201, edited.text
        ws = store.create('WorkspaceRevision', {'id':'j4-ws','project_id':parent.project_id,'study_area_id':parent.payload['site_id']},
                          entity_id='j4-ws', project_id=parent.project_id)
        draft = store.current(draft_id)
        statuses = draft.payload['parameters'].get('e1_statuses', {})
        assert statuses and set(statuses.values()) == {'STALE'}
        view = RealWeek7Service(store).view(ws.entity_id, draft_id)
        analyses = {r['execution_id']:r for r in view['analysis_results']}
        assert set(analyses) >= {r.entity_id for r in runs}
        for run in runs:
            assert analyses[run.entity_id]['freshness'] == 'stale'
            assert analyses[run.entity_id]['source_scenario_id'] == parent.entity_id
            assert analyses[run.entity_id]['source_revision'] == parent.revision
            assert store.current(run.entity_id).to_dict() == run.to_dict()
        assert view['human_status'] == 'NOT_ACCEPTED'
    finally:
        store.close()


def test_baseline_analysis_visibility_does_not_assign_foreign_run_to_selected_scenario(tmp_path):
    store, _, _, _, ids, geometry_hash = _world(tmp_path)
    try:
        baseline = store.current(ids[0])
        artifact = store.create('Artifact', {'type':'sunlight_simulation_result','sha256':'sha256:'+'b'*64}, project_id=baseline.project_id)
        run = store.create('ToolExecution', {'scenario_id':ids[1], 'tool':'radiance', 'status':'NOT_RUN', 'classification':'FIXTURE_ONLY',
            'parameters':{'scenario_pins':[{'scenario_id':baseline.entity_id,'scenario_revision':baseline.revision,'geometry_sha256':geometry_hash}]},
            'output_artifact_refs':[artifact.entity_id]}, project_id=baseline.project_id)
        ws = store.create('WorkspaceRevision', {'id':'j4-baseline-ws','project_id':baseline.project_id,'study_area_id':baseline.payload['site_id']},
            entity_id='j4-baseline-ws', project_id=baseline.project_id)
        view = RealWeek7Service(store).view(ws.entity_id, baseline.entity_id)
        analysis = next(v for v in view['analysis_results'] if v['execution_id'] == run.entity_id)
        assert analysis['source_scenario_id'] == baseline.entity_id
        assert all(v['entity_id'] != run.entity_id for v in view['runs']), 'Foreign primary scenario leaked into selected scenario runs'
        assert store.current(run.entity_id).to_dict() == run.to_dict()
    finally:
        store.close()
