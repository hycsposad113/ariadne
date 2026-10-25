"""API precondition tests; real browser synchronization lives under web/e2e."""

from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore


def test_site_context_fails_closed_without_verified_spatial_source(tmp_path):
    store = ProjectStateStore(tmp_path / "source-precondition.sqlite3")
    client = TestClient(create_workspace_app(store=store))
    before = store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0]

    response = client.get("/api/v1/projects/rotterdam-m4h-pilot-project/site-context")

    assert response.status_code == 503
    assert response.json()["detail"] == "verified spatial-r01 source catalog is unavailable"
    assert store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0] == before
    assert store.connection.execute("SELECT count(*) FROM state_versions").fetchone()[0] == 0
    store.close()
