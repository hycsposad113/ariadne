"""No live server or human decision writes; served-store integration."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.store import ProjectStateStore
from urban_design.generation.formal_service import install_formal_service
from urban_design.generation_context import create_generation_context_router


def test_blocked_and_unimplemented_modes_do_not_create_authority(tmp_path):
    with ProjectStateStore(tmp_path/'state.sqlite3') as store:
        store.create_project({'id':'p','name':'synthetic'}, project_id='p')
        from urban_design.api import create_workspace_app
        app = create_workspace_app(store, scenario_artifact_root=tmp_path/'outputs')
        with TestClient(app) as client:
            root = '/api/projects/p/generation-workflows'
            assert client.get(root+'/readiness').json()['readiness'] == 'BLOCKED'
            for mode in ('SKELETON_FIRST', 'STEPWISE'):
                result = client.post(root, json={'mode':mode,'idempotency_key':mode}).json()
                assert result['status'] == 'NOT_READY'
                assert result['reason'] == 'STAGED_FORMAL_SELECTION_NOT_IMPLEMENTED'
            result = client.post(root, json={'mode':'FULL_SCHEME','idempotency_key':'full'}).json()
            assert result['readiness'] == 'BLOCKED'
            assert result['status'] == 'BLOCKED'
            assert client.get('/api/projects/p/formal-proposals').json() == []
            assert client.get('/projects/p/generation-context/readiness').json()['status'] == 'BLOCKED'
        assert store.list_current('Scenario') == []
        assert store.list_current('HumanDecision') == []


def test_job_runs_real_pipeline_and_reuses_proposed_ids(tmp_path, monkeypatch):
    """Synthetic frozen references stand in for pre-existing approval records."""
    from urban_design.generation_context import Readiness, context_digest
    from urban_design.generation import formal_service, formal_persistence
    from test_formal_dictionary_pipeline import fixture
    context, manifest, inputs = fixture()
    ready = Readiness(status='READY', context=manifest, context_hash=context_digest(manifest))
    monkeypatch.setattr(formal_service, 'resolve_readiness', lambda *args: ready)
    monkeypatch.setattr(formal_service, 'freeze_context', lambda *args: ready)
    monkeypatch.setattr(formal_service, '_load_approved_inputs', lambda *args, **kwargs: inputs)
    monkeypatch.setattr(formal_persistence, 'resolve_readiness', lambda *args: ready)
    with ProjectStateStore(tmp_path/'state.sqlite3') as store:
        app = FastAPI()
        install_formal_service(app, store, tmp_path/'outputs')
        with TestClient(app) as client:
            root='/api/projects/p/generation-workflows'
            body={'mode':'FULL_SCHEME','idempotency_key':'same-context'}
            initial=client.post(root,json=body).json()
            assert initial['status']=='READY_TO_RUN'
            url=root+'/'+initial['workflow_id']
            result=client.post(url+'/advance').json()
            assert result['job_status']=='READY', result
            assert result['publication_status']=='PUBLISHED'
            rows=client.get('/api/projects/p/formal-proposals').json()
            assert len(rows)>=3
            assert len(rows)==len(store.list_current('Scenario'))
            assert all(row['status']=='PROPOSED' and row['metrics']['far_denominator']=='land_area' for row in rows)
            before=(len(store.list_current('Scenario')),len(store.list_current('Artifact')))
            assert client.post(root,json=body).json()==result
            assert client.post(url+'/advance').json()==result
            assert before==(len(store.list_current('Scenario')),len(store.list_current('Artifact')))
            # A new request key cannot mint duplicate authority records.
            second=client.post(root,json={**body,'idempotency_key':'another-key'}).json()
            assert client.post(root+'/'+second['workflow_id']+'/advance').json()['job_status']=='READY'
            assert before==(len(store.list_current('Scenario')),len(store.list_current('Artifact')))
            # Artifact tampering cannot be presented as a formal proposal.
            from pathlib import Path
            Path(rows[0]['geometry_path']).write_bytes(b'corrupt test artifact')
            assert client.get('/api/projects/p/formal-proposals').status_code==409
        assert store.list_current('HumanDecision')==[]
