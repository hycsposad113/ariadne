"""W7 E2 execution against disposable state, weather, artifact and job stores."""
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import mapping, box

from tests.test_e2_execution import approval
from tests.test_e2_weather import PROJECT, PROPOSAL
from urban_design.api import create_workspace_app
from urban_design.approved_generation import _workspace_payload_digest
from urban_design.decision_key import initialize_decision_key
from urban_design.environment.contracts import GroundGridDefinition
from urban_design.environment.e2_service import (
    E2Plan,
    ScenarioPin,
    open_jobs,
    publish_plan,
    scenario_geometry,
    validate_methods,
)
from urban_design.environment.weather_snapshot import canonical_bytes, persist_bytes, publish_candidate01
from urban_design.geometry import canonical_geometry_hash
from urban_design.store import ProjectStateStore
from urban_design.workspace_contracts import WorkspaceRevision

pytest_plugins = ["tests.week7_support"]


def _geometry_doc(*, building=None):
    features = [
        {"type": "Feature", "properties": {"role": "site_area"},
         "geometry": mapping(box(0, 0, 20, 20))},
        {"type": "Feature", "properties": {"role": "water"},
         "geometry": {"type": "Polygon", "coordinates": []}},
    ]
    if building is not None:
        features.append({"type": "Feature", "properties": {"role": "new_building", "height_m": 8,
                            "building_id": "fixture-building"}, "geometry": mapping(building)})
    return {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
            "features": features}


def _scenario(store, project_id, root, identifier, doc, parent=None, *, validate_geometry=True):
    artifact = persist_bytes(store, project_id, root / "scenario-artifacts", "fixture-geometry",
                             canonical_bytes(doc), mime="application/geo+json")
    store.update(artifact.entity_id, {"crs": "EPSG:28992"})
    row = store.create("DesignScenario", {
        "id": identifier, "project_id": project_id, "status": "draft" if parent else "proposed",
        "generator": "formal-dictionary-fixture", "geometry_artifact_id": artifact.entity_id,
        "geometry_sha256": artifact.payload["sha256"], "parent_scenario_id": parent,
        "site_id": "w7-e2-study", "site_version": "1", "constraint_set_id": "fixture-constraints",
        "generator_version": "fixture-v1", "parameters": {"validation": {"valid": True},
                                                            "provenance": "FIXTURE_ONLY"},
    }, entity_id=identifier, project_id=project_id)
    pin = ScenarioPin(scenario_id=row.entity_id, revision=row.revision,
                      geometry_artifact_id=artifact.entity_id, geometry_sha256=artifact.payload["sha256"],
                      environment_sha256="sha256:" + "0" * 64)
    if validate_geometry:
        _, metadata = scenario_geometry(store, pin, project_id)
        pin = pin.model_copy(update={"environment_sha256": metadata["environment_sha256"]})
    return row, pin


def _accepted_workspace(store, client, project_id, key):
    boundary = mapping(box(0, 0, 20, 20))
    geometry_hash = canonical_geometry_hash(boundary)
    store.create("StudyArea", {"id": "w7-e2-study", "version": "1", "status": "CONFIRMED_FOR_EXPLORATION",
                                "geometry_sha256": geometry_hash}, entity_id="w7-e2-study", project_id=project_id)
    workspace = WorkspaceRevision(
        workspace_id="w7-e2-workspace", project_id=project_id, revision=1,
        study_area_id="w7-e2-study", spatial_brief={"exploration_design_area": {"geometry": boundary}},
    )
    payload = workspace.model_dump(mode="json")
    payload["payload_digest"] = _workspace_payload_digest(workspace).removeprefix("sha256:")
    row = store.create("WorkspaceRevision", payload, entity_id=workspace.workspace_id, project_id=project_id)
    response = client.post(f"/api/v1/projects/{project_id}/decisions", json={
        "target_id": row.entity_id, "target_type": "WorkspaceRevision", "target_version": str(row.revision),
        "target_geometry_sha256": geometry_hash,
        "target_payload_digest": "sha256:" + payload["payload_digest"],
        "action": "Approve", "status": "approved", "reason": "隔離測試：確認工作區與探索範圍。",
        "decision_key": key, "actor_session_id": "w7-e2-test-human",
    })
    assert response.status_code == 201, response.text
    return row


def _anchor(store, project_id, scenario_id, identifier):
    artifact = store.create("Artifact", {"id": identifier + "-artifact", "type": "sunlight_simulation_result",
        "sha256": "sha256:" + "1" * 64, "project_id": project_id},
        entity_id=identifier + "-artifact", project_id=project_id)
    return store.create("ToolExecution", {"id": identifier, "scenario_id": scenario_id,
        "tool": "ladybug_radiance", "output_artifact_refs": [artifact.entity_id]},
        entity_id=identifier, project_id=project_id)


def _w7_rerun(client, workspace_id, anchor, baseline, modified, plan_id, key):
    return client.post(f"/api/v1/week7/workspaces/{workspace_id}/rerun", json={
        "target": {"entity_id": anchor.entity_id, "revision": anchor.revision}, "stage": "E2",
        "plan_artifact_id": plan_id, "baseline_scenario_id": baseline.entity_id,
        "modified_scenario_id": modified.entity_id, "idempotency_key": key,
    })


def test_w7_e2_success_invalid_geometry_failure_unknown_and_restart(tmp_path, monkeypatch):
    import urban_design.environment.e2_service as e2_service

    project_id = "w7-e2-project"
    store_path = tmp_path / "project-copy.sqlite3"
    store = ProjectStateStore(store_path)
    store.create_project({"id": project_id, "name": "FIXTURE_ONLY W7 E2"}, project_id=project_id)
    key = "test-only-e2-human-key"
    key_path = initialize_decision_key(path=tmp_path / "test-key", password_prompt=lambda _: key)
    snapshot = publish_candidate01(store, project_id, PROPOSAL, PROJECT, tmp_path / "weather-artifacts")
    validation = validate_methods(store, project_id, snapshot.entity_id, tmp_path / "method-qualification")

    baseline, baseline_pin = _scenario(store, project_id, tmp_path,
        "w7-e2-baseline", _geometry_doc())
    modified, modified_pin = _scenario(store, project_id, tmp_path,
        "w7-e2-modified", _geometry_doc(building=box(12, 0, 20, 20)), parent=baseline.entity_id)
    unrelated, _unrelated_pin = _scenario(store, project_id, tmp_path,
        "w7-e2-unrelated", _geometry_doc(building=box(0, 0, 6, 10)))
    bad_polygon = mapping(__import__("shapely.geometry", fromlist=["Polygon"]).Polygon(
        [(0, 0), (20, 20), (0, 20), (20, 0), (0, 0)]))
    invalid_doc = _geometry_doc()
    invalid_doc["features"][0]["geometry"] = bad_polygon
    invalid, invalid_pin = _scenario(store, project_id, tmp_path,
        "w7-e2-invalid", invalid_doc, parent=baseline.entity_id, validate_geometry=False)

    workspace_app = create_workspace_app(store=store, decision_key_path=key_path)
    workspace_app.state.e2_artifact_root = tmp_path / "e2-output"
    workspace_app.state.e2_job_database = tmp_path / "e2-jobs.sqlite3"
    try:
        with TestClient(workspace_app) as client:
            ws = _accepted_workspace(store, client, project_id, key)
            assert approval(client, snapshot, key).status_code == 201
            anchor = _anchor(store, project_id, modified.entity_id, "w7-e2-anchor")

            plan = E2Plan(project_id=project_id, weather_snapshot_id=snapshot.entity_id,
                weather_bundle_sha256=snapshot.payload["payload_digest"], baseline=baseline_pin, modified=modified_pin,
                grid=GroundGridDefinition(origin_x=0, origin_y=0, spacing_m=5, crs="EPSG:28992", tag="FIXTURE_ONLY"),
                true_north_deg=0, start_month=6, start_day=21, end_month=6, end_day=21,
                start_hour=9, end_hour=15, method_validation_artifact_id=validation.entity_id)
            plan_record = publish_plan(store, plan, tmp_path / "plan-artifacts")
            assert approval(client, plan_record, key).status_code == 201

            wrong_lineage_anchor = _anchor(store, project_id, unrelated.entity_id, "w7-e2-unrelated-anchor")
            wrong_lineage = _w7_rerun(client, ws.entity_id, wrong_lineage_anchor, baseline, modified,
                                      plan_record.entity_id, "wrong-e2-lineage")
            assert wrong_lineage.status_code == 409
            assert wrong_lineage.json()["detail"]["code"] == "execution_scenario_mismatch"

            success = _w7_rerun(client, ws.entity_id, anchor, baseline, modified,
                                plan_record.entity_id, "w7-e2-success")
            assert success.status_code == 200, success.text
            result = success.json()
            assert result["status"] == "SUCCEEDED"
            assert result["evidence_validation_status"] == "unverified"
            assert len(store.list_current("ToolExecution", project_id=project_id)) == 14
            assert len(store.list_current("EvidenceCard", project_id=project_id)) == 12
            assert all(card.payload["validation_status"] == "unverified"
                       for card in store.list_current("EvidenceCard", project_id=project_id)
                       if card.payload.get("scenario_id") == modified.entity_id)
            compare = client.post(f"/api/v1/week7/workspaces/{ws.entity_id}/operations/compare", json={
                "target": {"entity_id": modified.entity_id, "revision": modified.revision},
                "compare_targets": [{"entity_id": baseline.entity_id, "revision": baseline.revision},
                                    {"entity_id": modified.entity_id, "revision": modified.revision}],
            })
            assert compare.status_code == 200 and compare.json()["status"] == "NOT_COMPARABLE"
            assert compare.json()["winner"] is None
            replay = _w7_rerun(client, ws.entity_id, anchor, baseline, modified,
                               plan_record.entity_id, "w7-e2-success")
            assert replay.status_code == 200 and replay.json()["job_id"] == result["job_id"]
            assert len(store.list_current("ToolExecution", project_id=project_id)) == 14

            invalid_plan = plan.model_copy(update={"modified": invalid_pin})
            invalid_plan_record = publish_plan(store, invalid_plan, tmp_path / "invalid-plan-artifacts")
            assert approval(client, invalid_plan_record, key).status_code == 201
            invalid_anchor = _anchor(store, project_id, invalid.entity_id, "w7-e2-invalid-anchor")
            invalid_plan_head = store.current(invalid.entity_id).to_dict()
            before_invalid_runs = len(store.list_current("ToolExecution", project_id=project_id))
            bad_job_db = tmp_path / "e2-invalid-jobs.sqlite3"
            good_job_db = workspace_app.state.e2_job_database
            workspace_app.state.e2_job_database = bad_job_db
            invalid_response = _w7_rerun(client, ws.entity_id, invalid_anchor, baseline, invalid,
                                         invalid_plan_record.entity_id, "invalid-e2-geometry")
            assert invalid_response.status_code == 409, invalid_response.text
            assert "invalid geometry" in invalid_response.json()["detail"]["reason"].lower()
            assert len(store.list_current("ToolExecution", project_id=project_id)) == before_invalid_runs
            assert store.current(invalid.entity_id).to_dict() == invalid_plan_head
            assert not bad_job_db.exists()
            workspace_app.state.e2_job_database = good_job_db

            monkeypatch.setattr(e2_service, "calculate", lambda *_a, **_k: (_ for _ in ()).throw(
                RuntimeError("W7_TEST_COMPUTATION_FAILURE")))
            failed = _w7_rerun(client, ws.entity_id, anchor, baseline, modified,
                               plan_record.entity_id, "w7-e2-known-failure")
            assert failed.status_code == 200, failed.text
            failure_result = failed.json()
            assert failure_result["status"] == "FAILED"
            assert failure_result["evidence_validation_status"] == "unverified"
            failed_pairs = [pair_item for offsets in failure_result["results"].values()
                            for pair in offsets.values() for pair_item in pair]
            assert all(pair_item["status"] == "FAILED" for pair_item in failed_pairs)
            assert all("distribution" not in pair_item for pair_item in failed_pairs)
            assert all(pair_item["records"]["evidence_validation_status"] == "unverified"
                       for pair_item in failed_pairs)
            failed_runs = [row for row in store.list_current("ToolExecution", project_id=project_id)
                           if row.payload.get("scenario_id") in {baseline.entity_id, modified.entity_id}
                           and row.payload.get("status") == "FAILED"]
            assert len(failed_runs) == 12

            unknown_calls = []
            def unknown_calculation(*_args, **_kwargs):
                unknown_calls.append("dispatch")
                raise e2_service.E2Blocked("OUTCOME_UNKNOWN:TEST_POST_DISPATCH_LOSS")
            monkeypatch.setattr(e2_service, "calculate", unknown_calculation)
            unknown = _w7_rerun(client, ws.entity_id, anchor, baseline, modified,
                                plan_record.entity_id, "w7-e2-outcome-unknown")
            assert unknown.status_code == 200, unknown.text
            unknown_result = unknown.json()
            assert unknown_result["status"] == "OUTCOME_UNKNOWN"
            assert unknown_result["reconciliation"]["redispatch_allowed"] is False
            repeat_unknown = _w7_rerun(client, ws.entity_id, anchor, baseline, modified,
                                       plan_record.entity_id, "w7-e2-outcome-unknown")
            assert repeat_unknown.status_code == 200
            assert repeat_unknown.json()["job_id"] == unknown_result["job_id"]
            assert unknown_calls == ["dispatch"]
    finally:
        store.close()

    reopened = ProjectStateStore(store_path)
    try:
        workspace_app = create_workspace_app(store=reopened, decision_key_path=key_path)
        workspace_app.state.e2_artifact_root = tmp_path / "e2-output"
        workspace_app.state.e2_job_database = tmp_path / "e2-jobs.sqlite3"
        with TestClient(workspace_app) as client:
            view = client.get(f"/api/v1/week7/workspaces/w7-e2-workspace/view",
                              params={"scenario_id": modified.entity_id})
            assert view.status_code == 200
            assert view.json()["scenario_ref"]["entity_id"] == modified.entity_id
            assert any(card["validation_status"] == "unverified" for card in view.json()["cards"])
            replay_unknown = _w7_rerun(client, "w7-e2-workspace", anchor, baseline, modified,
                                       plan_record.entity_id, "w7-e2-outcome-unknown")
            assert replay_unknown.status_code == 200
            assert replay_unknown.json()["status"] == "OUTCOME_UNKNOWN"
            assert replay_unknown.json()["job_id"] == unknown_result["job_id"]
            jobs, _runner, _output = open_jobs(reopened, tmp_path / "e2-jobs.sqlite3")
            persisted_job = jobs.get(unknown_result["job_id"])
            assert persisted_job.status.value == "OUTCOME_UNKNOWN"
            assert len(reopened.list_current("EvidenceCard", project_id=project_id)) == 25
            for row in reopened.list_current("EvidenceCard", project_id=project_id):
                if row.payload.get("result", {}).get("status") == "unavailable":
                    assert row.payload["validation_status"] == "unverified"
    finally:
        reopened.close()
