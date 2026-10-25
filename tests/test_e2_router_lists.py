"""Pytest for E2 router list endpoints: jobs, weather snapshots, plans."""
import json
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.generation.job_store import GenerationJobStore
from urban_design.models import Project, Artifact, DatasetSnapshot
from urban_design.store import ProjectStateStore
from urban_design.environment.e2_service import E2Plan, ScenarioPin, Recipe
from urban_design.environment.contracts import GroundGridDefinition
from urban_design.environment.weather_snapshot import persist_bytes, canonical_bytes, sha256


@pytest.fixture
def tmp_e2_setup(tmp_path):
    store_path = tmp_path / "state.sqlite3"
    job_db_path = tmp_path / "e2-jobs.sqlite3"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    store = ProjectStateStore(store_path)
    # Seed projects
    p1 = Project(id="proj-1", name="Project 1")
    p2 = Project(id="proj-2", name="Project 2")
    store.create("Project", p1.model_dump(mode="json"), project_id="proj-1")
    store.create("Project", p2.model_dump(mode="json"), project_id="proj-2")

    app = create_workspace_app(store=store)
    app.state.e2_artifact_root = artifact_root
    app.state.e2_job_database = job_db_path

    return store, app, job_db_path, artifact_root, tmp_path


def test_empty_lists(tmp_e2_setup):
    store, app, job_db_path, artifact_root, tmp_path = tmp_e2_setup
    with TestClient(app) as client:
        # 1. Jobs empty
        resp = client.get("/api/v1/environment/e2/jobs", params={"project_id": "proj-1"})
        assert resp.status_code == 200
        assert resp.json() == []

        # 2. Weather snapshots empty
        resp = client.get("/api/v1/environment/e2/weather/snapshots", params={"project_id": "proj-1"})
        assert resp.status_code == 200
        assert resp.json() == []

        # 3. Plans empty
        resp = client.get("/api/v1/environment/e2/plans", params={"project_id": "proj-1"})
        assert resp.status_code == 200
        assert resp.json() == []


def test_weather_snapshots_populated_and_project_filter(tmp_e2_setup):
    store, app, job_db_path, artifact_root, tmp_path = tmp_e2_setup

    # Insert snapshot for proj-1
    digest1 = "sha256:" + "a" * 64
    snap1 = DatasetSnapshot(
        id="snapshot-e2-weather-111111111111111111111111",
        project_id="proj-1",
        source="http://example.com/w1",
        query="candidate-01",
        retrieved_at="2026-10-18T00:00:00Z",
        publisher="KNMI",
        license="CC-BY",
        version="weather-derived-method-v1",
        sha256="sha256:" + "b" * 64,
        raw_artifact_id="art-w-raw-1",
        normalized_artifact_id="art-w-norm-1"
    )
    payload1 = snap1.model_dump(mode="json")
    payload1.update(status="PROPOSED", payload_digest=digest1)
    store.create("DatasetSnapshot", payload1, project_id="proj-1", entity_id=snap1.id)

    # Insert snapshot for proj-2
    digest2 = "sha256:" + "c" * 64
    snap2 = DatasetSnapshot(
        id="snapshot-e2-weather-222222222222222222222222",
        project_id="proj-2",
        source="http://example.com/w2",
        query="candidate-01",
        retrieved_at="2026-10-18T00:00:00Z",
        publisher="KNMI",
        license="CC-BY",
        version="weather-derived-method-v1",
        sha256="sha256:" + "d" * 64,
        raw_artifact_id="art-w-raw-2",
        normalized_artifact_id="art-w-norm-2"
    )
    payload2 = snap2.model_dump(mode="json")
    payload2.update(status="PROPOSED", payload_digest=digest2)
    store.create("DatasetSnapshot", payload2, project_id="proj-2", entity_id=snap2.id)

    with TestClient(app) as client:
        # proj-1
        resp = client.get("/api/v1/environment/e2/weather/snapshots", params={"project_id": "proj-1"})
        assert resp.status_code == 200
        data1 = resp.json()
        assert len(data1) == 1
        assert data1[0]["id"] == "snapshot-e2-weather-111111111111111111111111"
        assert data1[0]["version"] == "weather-derived-method-v1"
        assert data1[0]["payload_digest"] == digest1
        assert data1[0]["status"] == "PROPOSED"
        assert data1[0]["decision_target_type"] == "DatasetSnapshot"

        # proj-2
        resp = client.get("/api/v1/environment/e2/weather/snapshots", params={"project_id": "proj-2"})
        assert resp.status_code == 200
        data2 = resp.json()
        assert len(data2) == 1
        assert data2[0]["id"] == "snapshot-e2-weather-222222222222222222222222"

        # non-existent project
        resp = client.get("/api/v1/environment/e2/weather/snapshots", params={"project_id": "proj-3"})
        assert resp.status_code == 200
        assert resp.json() == []


def test_plans_populated_and_project_filter(tmp_e2_setup):
    store, app, job_db_path, artifact_root, tmp_path = tmp_e2_setup

    def make_plan(pid, base_scen, mod_scen):
        pin_base = ScenarioPin(
            scenario_id=base_scen, revision=1,
            geometry_artifact_id="geom-base",
            geometry_sha256="sha256:" + "1" * 64,
            environment_sha256="sha256:" + "2" * 64
        )
        pin_mod = ScenarioPin(
            scenario_id=mod_scen, revision=1,
            geometry_artifact_id="geom-mod",
            geometry_sha256="sha256:" + "3" * 64,
            environment_sha256="sha256:" + "4" * 64
        )
        grid = GroundGridDefinition(crs="EPSG:28992", origin_x=100.0, origin_y=200.0, spacing_m=5.0)
        plan = E2Plan(
            project_id=pid,
            weather_snapshot_id="snapshot-e2-weather-1",
            weather_bundle_sha256="sha256:" + "5" * 64,
            baseline=pin_base,
            modified=pin_mod,
            grid=grid,
            true_north_deg=0.0,
            recipe=Recipe(),
            method_validation_artifact_id="art-method-val"
        )
        return plan

    plan1 = make_plan("proj-1", "scen-base-1", "scen-mod-1")
    plan2 = make_plan("proj-2", "scen-base-2", "scen-mod-2")

    raw1 = canonical_bytes(plan1.model_dump(mode="json"))
    raw2 = canonical_bytes(plan2.model_dump(mode="json"))

    persist_bytes(store, "proj-1", artifact_root, "experiment-plan", raw1)
    persist_bytes(store, "proj-2", artifact_root, "experiment-plan", raw2)

    with TestClient(app) as client:
        # proj-1
        resp = client.get("/api/v1/environment/e2/plans", params={"project_id": "proj-1"})
        assert resp.status_code == 200
        p1_list = resp.json()
        assert len(p1_list) == 1
        assert p1_list[0]["sha256"] == sha256(raw1)
        assert p1_list[0]["status"] == "PROPOSED"
        assert p1_list[0]["baseline"]["scenario_id"] == "scen-base-1"
        assert p1_list[0]["modified"]["scenario_id"] == "scen-mod-1"

        # proj-2
        resp = client.get("/api/v1/environment/e2/plans", params={"project_id": "proj-2"})
        assert resp.status_code == 200
        p2_list = resp.json()
        assert len(p2_list) == 1
        assert p2_list[0]["baseline"]["scenario_id"] == "scen-base-2"

        # non-existent project
        resp = client.get("/api/v1/environment/e2/plans", params={"project_id": "proj-3"})
        assert resp.status_code == 200
        assert resp.json() == []


def test_jobs_populated_and_project_filter(tmp_e2_setup):
    store, app, job_db_path, artifact_root, tmp_path = tmp_e2_setup

    # Initialize GenerationJobStore
    job_store = GenerationJobStore(job_db_path)

    # Make a plan in store so list_jobs can read scenario IDs
    pin_base = ScenarioPin(
        scenario_id="scen-base-j1", revision=1,
        geometry_artifact_id="geom-b", geometry_sha256="sha256:" + "1" * 64, environment_sha256="sha256:" + "2" * 64
    )
    pin_mod = ScenarioPin(
        scenario_id="scen-mod-j1", revision=1,
        geometry_artifact_id="geom-m", geometry_sha256="sha256:" + "3" * 64, environment_sha256="sha256:" + "4" * 64
    )
    plan_obj = E2Plan(
        project_id="proj-1", weather_snapshot_id="w-1", weather_bundle_sha256="sha256:" + "5" * 64,
        baseline=pin_base, modified=pin_mod,
        grid=GroundGridDefinition(crs="EPSG:28992", origin_x=0.0, origin_y=0.0, spacing_m=5.0),
        true_north_deg=0.0, method_validation_artifact_id="val-1"
    )
    plan_art = persist_bytes(store, "proj-1", artifact_root, "experiment-plan", canonical_bytes(plan_obj.model_dump(mode="json")))

    # Enqueue job for proj-1
    job1, _ = job_store.enqueue(
        project_id="proj-1", idempotency_key="key-j1", stage="E2_RADIATION",
        request={"plan_id": plan_art.entity_id, "project_id": "proj-1"},
        input_refs=[{"id": plan_art.entity_id, "sha256": plan_art.payload["sha256"], "kind": "experiment_plan"}]
    )

    # Enqueue job for proj-2
    job2, _ = job_store.enqueue(
        project_id="proj-2", idempotency_key="key-j2", stage="E2_RADIATION",
        request={"plan_id": "non-existent-plan", "project_id": "proj-2"},
        input_refs=[{"id": "dummy", "sha256": "sha256:" + "0" * 64, "kind": "plan"}]
    )

    # Create mock result.json for job1
    out_dir = job_db_path.with_suffix("") / "out" / job1.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    result_data = {
        "job_id": job1.job_id,
        "status": "SUCCEEDED",
        "evidence_validation_status": "validated"
    }
    (out_dir / "result.json").write_text(json.dumps(result_data))

    # Mark job1 as ready in sqlite
    with sqlite3.connect(job_db_path) as con:
        con.execute("UPDATE generation_jobs SET status = 'READY' WHERE job_id = ?", (job1.job_id,))

    with TestClient(app) as client:
        # proj-1
        resp = client.get("/api/v1/environment/e2/jobs", params={"project_id": "proj-1"})
        assert resp.status_code == 200
        j1_list = resp.json()
        assert len(j1_list) == 1
        j1 = j1_list[0]
        assert j1["id"] == job1.job_id
        assert j1["job_id"] == job1.job_id
        assert j1["status"] == "READY"
        assert j1["plan_id"] == plan_art.entity_id
        assert j1["baseline_scenario_id"] == "scen-base-j1"
        assert j1["modified_scenario_id"] == "scen-mod-j1"
        assert j1["validated"] is True
        assert j1["completed_at"] is not None

        # proj-2
        resp = client.get("/api/v1/environment/e2/jobs", params={"project_id": "proj-2"})
        assert resp.status_code == 200
        j2_list = resp.json()
        assert len(j2_list) == 1
        j2 = j2_list[0]
        assert j2["id"] == job2.job_id
        assert j2["status"] == "PENDING"
        assert j2["validated"] is False
        assert j2["completed_at"] is None

        # proj-3
        resp = client.get("/api/v1/environment/e2/jobs", params={"project_id": "proj-3"})
        assert resp.status_code == 200
        assert resp.json() == []


def test_result_summary_strips_per_point_arrays(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from urban_design.environment import e2_router
    full = {'job_id': 'j', 'status': 'SUCCEEDED', 'evidence_validation_status': 'validated', 'results': {'ladybug_radiance': [1] * 1000},
            'comparisons': {'ladybug_radiance': {'0': {'baseline_kwh_m2': 1.0, 'modified_kwh_m2': 0.9, 'delta_kwh_m2': -0.1, 'direction': 'DECREASED', 'histogram': [1, 2, 3]}}},
            'direction_summary': {'methods': {}}, 'limitations': ['x']}
    monkeypatch.setattr(e2_router, 'store_and_root', lambda request: (object(), None))
    monkeypatch.setattr(e2_router, 'read_result', lambda *args: full)
    app = FastAPI(); app.include_router(e2_router.router)
    body = TestClient(app).get('/api/v1/environment/e2/results/j/summary', params={'project_id': 'p'}).json()
    assert 'results' not in body and body['summary_of_full_result'] is True
    assert body['comparisons']['ladybug_radiance']['0'] == {'baseline_kwh_m2': 1.0, 'modified_kwh_m2': 0.9, 'delta_kwh_m2': -0.1, 'direction': 'DECREASED'}
    assert body['evidence_validation_status'] == 'validated'
