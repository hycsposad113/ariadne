from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.store import ProjectStateStore
from urban_design.week7.e3e4 import E3E4InputError, entry, inspect_inputs
from urban_design.week7.router import create_week7_router
from tests.week7_support import seed_project_database

pytest_plugins = ["tests.week7_support"]



def test_entry_stays_not_accepted_and_calls_no_engine() -> None:
    body = entry()
    assert body["e3"]["status"] == "NOT_ACCEPTED"
    assert body["e4"]["status"] == "NOT_ACCEPTED"
    assert body["e3"]["run_status"] == "BLOCKED"
    assert body["e4"]["run_status"] == "BLOCKED"
    assert body["benchmark_plan"]["external_engine"] is None
    assert body["benchmark_plan"]["does_not_rank"] is True
    assert body["core_feature"] is False
    assert body["checked_input"] is None


def test_input_check_rejects_incomplete_or_negative_area() -> None:
    with pytest.raises(E3E4InputError) as missing:
        inspect_inputs({"scenario_id": "B2"})
    assert missing.value.code == "input_incomplete"
    with pytest.raises(E3E4InputError) as negative:
        inspect_inputs({
            "scenario_id": "B2",
            "revision": "rev-b2",
            "floor_area_m2": -1,
            "use_mix": {"public": 1},
        })
    assert negative.value.code == "floor_area_negative"
    checked = inspect_inputs({
        "scenario_id": "B2",
        "revision": "rev-b2",
        "floor_area_m2": "1200.5",
        "use_mix": {"public": 1},
    })
    assert checked["external_engine_called"] is False
    assert checked["floor_area_m2"] == 1200.5


def test_api_reports_not_accepted_on_a_database_copy(tmp_path: Path) -> None:
    database = seed_project_database(tmp_path / "state.sqlite3")
    store = ProjectStateStore(database)
    try:
        app = FastAPI()
        app.include_router(create_week7_router(store))
        client = TestClient(app)
        reading = client.get("/api/v1/week7/e3e4")
        assert reading.status_code == 200
        assert reading.json()["e3"]["status"] == "NOT_ACCEPTED"
        assert reading.json()["e4"]["status"] == "NOT_ACCEPTED"
        rejected = client.post("/api/v1/week7/e3e4/check", json={"scenario_id": "B2"})
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "input_incomplete"
        view = client.get("/api/v1/week7/workspaces/missing/view")
        assert view.status_code == 409
        assert view.json()["detail"]["code"] == "workspace_missing"
        ws_view = client.get("/api/v1/week7/workspaces/fixture-workspace/view")
        assert ws_view.status_code == 200
        assert ws_view.json()["human_status"] == "NOT_ACCEPTED"
        assert ws_view.json()["run_status"] == "NOT_RUN"
    finally:
        store.close()
