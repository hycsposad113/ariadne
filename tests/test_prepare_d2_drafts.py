import importlib.util
from pathlib import Path
import json
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.models import ConstraintSet
from urban_design.constraint_sets import validate_constraint_set_definition
from urban_design.store import ProjectStateStore

spec = importlib.util.spec_from_file_location("prepare_d2", Path(__file__).parents[1] / "scripts/prepare_d2_drafts.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_d2_content():
    drafts = module.prepare_drafts()
    assert len(drafts) == 2
    for draft, values in zip(drafts, [(0.8, 0.35, 20), (2.0, 0.5, 40)]):
        model = ConstraintSet(id=draft["id"], project_id=module.PROJECT_ID, version="v1", constraints=draft["constraints"], notes=draft["notes"], allocation_policy=draft["allocation_policy"])
        validate_constraint_set_definition(model, require_complete=True, require_far_denominator=True)
        by_name = {item["name"]: item for item in draft["constraints"]}
        assert tuple(by_name[name]["value"] for name in ("far_upper_limit", "coverage_upper_limit", "height_upper_limit")) == values
        assert by_name["far_upper_limit"]["denominator"] == "land_area"
        assert by_name["first_floor_height"]["value"] == by_name["standard_floor_height"]["value"] == 3.5
        assert by_name["rotation_step"]["value"] == 15
        assert {i["scope"]: i["value"] for i in draft["constraints"] if i["name"] == "road_width"} == {"road:primary": 14, "road:secondary": 10, "road:residential": 6}
        assert all(item["source_note"] for item in draft["constraints"])
        assert "≥40%" in draft["notes"] and "15 m" in draft["notes"]
        assert draft["actor_kind"] == "AGENT_AUTOMATION"
        assert "zone_far_upper_limit" not in by_name


def test_offline_cli_only_outputs_json():
    import sys
    result = subprocess.run([sys.executable, str(spec.origin)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"project_id": module.PROJECT_ID, "drafts": module.prepare_drafts()}


def test_in_process_rehearsal_is_idempotent_and_nonbinding(tmp_path):
    with ProjectStateStore(tmp_path / "d2.sqlite3") as store:
        store.create_project({"id": module.PROJECT_ID, "name": "test"}, project_id=module.PROJECT_ID)
        with TestClient(create_workspace_app(store=store)) as client:
            first = module.submit_drafts("http://testserver", client)
            assert module.submit_drafts("http://testserver", client) == first
        assert len(store.list_current("ConstraintSet", project_id=module.PROJECT_ID)) == 2
        assert not store.list_current("HumanDecision", project_id=module.PROJECT_ID)
        for result in first:
            assert result["constraint_set"]["status"] == "proposed"
            assert len(store.events(target_id=result["constraint_set"]["id"])) == 1


@pytest.mark.parametrize("error", [401, 402, 500, "disconnect"])
def test_dispatch_failure_stops_without_retry(error):
    calls = []
    def handler(request):
        calls.append(request)
        if error == "disconnect":
            raise httpx.ReadError("uncertain outcome", request=request)
        return httpx.Response(error, json={"detail": "stop"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPError):
            module.submit_drafts("http://testserver", client)
    assert len(calls) == 1
