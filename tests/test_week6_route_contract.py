"""Canonical /api/v1 paths and their deprecated aliases return the same body."""

from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore

PAIRS = (
    (
        "/api/v1/projects/{project_id}/generation-context/readiness",
        "/projects/{project_id}/generation-context/readiness",
        "/api/v1/projects/p/generation-context/readiness",
        "/projects/p/generation-context/readiness",
        "get",
    ),
    (
        "/api/v1/projects/{project_id}/generation-context/freeze",
        "/projects/{project_id}/generation-context/freeze",
        "/api/v1/projects/p/generation-context/freeze",
        "/projects/p/generation-context/freeze",
        "post",
    ),
    (
        "/api/v1/projects/{project_id}/generation-workflows/readiness",
        "/api/projects/{project_id}/generation-workflows/readiness",
        "/api/v1/projects/p/generation-workflows/readiness",
        "/api/projects/p/generation-workflows/readiness",
        "get",
    ),
    (
        "/api/v1/projects/{project_id}/formal-proposals",
        "/api/projects/{project_id}/formal-proposals",
        "/api/v1/projects/p/formal-proposals",
        "/api/projects/p/formal-proposals",
        "get",
    ),
)


def test_legacy_aliases_match_canonical_bodies_and_openapi_marks_them(tmp_path):
    with ProjectStateStore(tmp_path / "state.sqlite3") as store:
        store.create_project({"id": "p", "name": "route-contract"}, project_id="p")
        app = create_workspace_app(store, scenario_artifact_root=tmp_path / "outputs")
        with TestClient(app) as client:
            readiness = client.get("/api/v1/projects/p/generation-context/readiness")
            assert readiness.status_code == 200
            legacy = client.get("/projects/p/generation-context/readiness")
            assert legacy.status_code == 200
            assert legacy.json() == readiness.json()

            workflow = client.get("/api/v1/projects/p/generation-workflows/readiness")
            legacy_workflow = client.get("/api/projects/p/generation-workflows/readiness")
            assert workflow.status_code == legacy_workflow.status_code == 200
            assert legacy_workflow.json() == workflow.json()

            proposals = client.get("/api/v1/projects/p/formal-proposals")
            legacy_proposals = client.get("/api/projects/p/formal-proposals")
            assert proposals.status_code == legacy_proposals.status_code == 200
            assert legacy_proposals.json() == proposals.json() == []

        schema = app.openapi()
        for canonical, legacy_path, _canonical_url, _legacy_url, method in PAIRS:
            assert canonical in schema["paths"]
            assert legacy_path in schema["paths"]
            assert schema["paths"][legacy_path][method]["deprecated"] is True
            assert schema["paths"][canonical][method].get("deprecated") is not True
