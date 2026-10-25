"""Disposable end-to-end W7 walkthrough across sync, decisions and both reruns."""
from datetime import date, datetime, timezone
import json

from fastapi.testclient import TestClient
from shapely.geometry import LineString, Polygon, box, mapping

from tests.test_formal_editor_authority import _decision, _world
from tests.test_e2_weather import PROJECT as E2_PROJECT, PROPOSAL
from urban_design.api import create_workspace_app
from urban_design.approved_generation import _workspace_payload_digest
from urban_design.environment.contracts import AnalysisPeriod, GroundGridDefinition
from urban_design.environment.e2_service import E2Plan, ScenarioPin, publish_plan, scenario_geometry, validate_methods
from urban_design.environment.plan_service import approve_plan_artifact, persist_e1_plan_artifact
from urban_design.environment.router import get_default_draft_plan
from urban_design.environment.weather_snapshot import canonical_bytes, persist_bytes, publish_candidate01
from urban_design.geometry import canonical_geometry_hash
from urban_design.models import ActorKind, DatasetSnapshot, Scenario, ScenarioStatus
from urban_design.pst_syntax import compute_pst_six_syntax_layers
from urban_design.store import ProjectStateStore
from urban_design.workspace_contracts import (
    FeatureDisposition,
    SpatialZone,
    SyncRequest,
    WorkspaceRevision,
    WorkspaceSpatialBrief,
)
from urban_design.workspace_service import WorkspaceService

pytest_plugins = ["tests.week7_support"]


def _proposal(store, project_id, root, identifier, building_x, constraint_digest):
    # Formal-shaped disposable proposals for the W7 contract walkthrough;
    # their geometry-derived metrics are test inputs, not project evidence.
    site = box(0, 0, 40, 30)
    building = box(building_x, 5, building_x + 5, 10)
    road = box(0, 12, 40, 18)
    open_space = site.difference(building.union(road))
    doc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {"type": "Feature", "properties": {"role": "site_area"}, "geometry": mapping(site)},
            {"type": "Feature", "properties": {"role": "water"},
             "geometry": {"type": "GeometryCollection", "geometries": []}},
            {"type": "Feature", "properties": {"role": "new_building", "building_id": identifier,
                                                       "height_m": 7.0}, "geometry": mapping(building)},
            {"type": "Feature", "properties": {"role": "primary_open_space"}, "geometry": mapping(open_space)},
        ],
    }
    artifact = persist_bytes(store, project_id, root / "scenario-geometry", "scenario-geometry",
                             canonical_bytes(doc), mime="application/geo+json")
    store.update(artifact.entity_id, {"crs": "EPSG:28992"})
    stages = {
        "massing": {"buildings": [{"id": identifier, "use": "residential", "height_m": 7.0,
            "floors": [
                {"id": identifier + "-f0", "level": 0, "floor_height_m": 3.5,
                 "use": "residential", "geometry": mapping(building)},
                {"id": identifier + "-f1", "level": 1, "floor_height_m": 3.5,
                 "use": "residential", "geometry": mapping(building)},
            ], "footprint": mapping(building)}]},
        "skeleton": {"edges": [{"id": identifier + "-road", "from_node_id": identifier + "-n0",
            "to_node_id": identifier + "-n1", "level": 0,
            "geometry": mapping(LineString([(0, 15), (40, 15)]))}]},
    }
    floor_area = float(building.area) * 2
    land_area = 183591.328
    coverage = float(building.area / site.area)
    road_ratio = float(road.difference(building).area / site.area)
    metrics = {
        "far": floor_area / land_area,
        "far_denominator": "land_area",
        "far_denominator_m2": land_area,
        "coverage": coverage,
        "highest_new_height_m": 7.0,
        "road_ratio": road_ratio,
        "open_space_ratio": 1 - coverage - road_ratio,
    }
    scenario = Scenario(
        id=identifier, project_id=project_id, site_id="study-area-formal", site_version="v5",
        morphology_family="CONNECTED_GRID", geometry_artifact_id=artifact.entity_id,
        geometry_sha256=artifact.payload["sha256"], generator="formal-dictionary-v2",
        generator_version="formal-dictionary-v2", constraint_set_id="cs-d2-a",
        status=ScenarioStatus.PROPOSED,
        parameters={"recipe_id": identifier, "recipe_version": "formal-dictionary-v2",
                    "provenance": "APPROVED_INPUTS", "constraint_set_digest": constraint_digest,
                    "stages": stages, "validation": {"valid": True, "failure_reasons": []},
                    "metrics": metrics, "comparison_basis": {"rules_version": "formal-dictionary-v2"}},
    )
    return store.create_typed(scenario, actor="test-harness", actor_kind=ActorKind.TEST_HARNESS,
                              reason="FIXTURE_ONLY deterministic geometry proposal")


def _pin(store, scenario, project_id):
    pin = ScenarioPin(scenario_id=scenario.entity_id, revision=scenario.revision,
        geometry_artifact_id=scenario.payload["geometry_artifact_id"],
        geometry_sha256=scenario.payload["geometry_sha256"], environment_sha256="sha256:" + "0" * 64)
    _geometry, metadata = scenario_geometry(store, pin, project_id)
    return pin.model_copy(update={"environment_sha256": metadata["environment_sha256"]})


def test_week7_real_walkthrough_sync_four_proposals_modify_e1_e2_and_restart(tmp_path):
    from test_e2_execution import approval as approval_artifact
    from urban_design.environment.e2_service import open_jobs
    from urban_design.generation.job_store import GenerationJobStore, JobStatus
    from urban_design.geometry import canonical_geometry_hash

    store, _formal_client, key, key_path, _old_scenarios, _old_hash = _world(tmp_path)
    project_id = "proj-formal"
    try:
        study = store.current("study-area-formal")
        area_geometry = mapping(box(0, 0, 100, 100))
        area_hash = canonical_geometry_hash(area_geometry)
        store.update(study.entity_id, {"geometry_sha256": area_hash}, expected_revision=study.revision,
                     reason="FIXTURE_ONLY workspace geometry binding")
        _decision(store, key, key_path, id="w7-walkthrough-study-decision", project_id=project_id,
            target_id=study.entity_id, target_type="StudyArea", target_version="v5",
            target_geometry_sha256=area_hash, action="Approve", status="approved")

        lines = [{"id": "fixture-road-1", "geometry": {"type": "LineString",
                  "coordinates": [[0, 15], [40, 15]]}, "properties": {"highway": "residential"}},
                 {"id": "fixture-road-2", "geometry": {"type": "LineString",
                  "coordinates": [[20, 0], [20, 30]]}, "properties": {"highway": "residential"}}]
        source_doc = {"type": "FeatureCollection", "features": lines}
        raw_source = persist_bytes(store, project_id, tmp_path / "frozen-source", "source-snapshot",
                                   canonical_bytes(source_doc))
        normalized_source = persist_bytes(store, project_id, tmp_path / "frozen-source", "normalized-source",
                                          canonical_bytes(source_doc))
        snapshot = DatasetSnapshot(id="w7-walkthrough-source", project_id=project_id,
            source="FIXTURE_ONLY frozen local road source", query="two explicit local LineStrings",
            retrieved_at=datetime(2026, 10, 15, tzinfo=timezone.utc), publisher="FIXTURE_ONLY",
            license="CC0-1.0", version="fixture-v1", sha256=raw_source.payload["sha256"],
            raw_artifact_id=raw_source.entity_id, normalized_artifact_id=normalized_source.entity_id)
        snapshot_payload = snapshot.model_dump(mode="json")
        snapshot_payload["status"] = "CONFIRMED"
        store.create("DatasetSnapshot", snapshot_payload, entity_id=snapshot.id, project_id=project_id)
        building_source = persist_bytes(store, project_id, tmp_path / "frozen-source", "building-source",
            canonical_bytes({"source_feature": "building-1", "provenance": "FIXTURE_ONLY"}))
        road_source = persist_bytes(store, project_id, tmp_path / "frozen-source", "road-source",
            canonical_bytes({"source_feature": "road-1", "provenance": "FIXTURE_ONLY"}))

        brief = WorkspaceSpatialBrief(
            exploration_design_area={"geometry": area_geometry, "crs": "EPSG:28992"},
            zones=[
                SpatialZone(zone_id="zone-west", name="西側分區", target_use="住宅", geometry=mapping(box(0, 0, 50, 100)),
                            original_text="西側空間需求"),
                SpatialZone(zone_id="zone-east", name="東側分區", target_use="工作坊", geometry=mapping(box(50, 0, 100, 100)),
                            original_text="東側空間需求"),
            ],
        )
        dispositions = [
            FeatureDisposition(feature_id="building-1", feature_kind="building", disposition="preserve",
                               source_artifact_id=building_source.entity_id, annotation="保留既有建築。"),
            FeatureDisposition(feature_id="road-1", feature_kind="road", disposition="editable",
                               source_artifact_id=road_source.entity_id, annotation="道路可調整；保留來源參照。"),
        ]
        sync_request = SyncRequest(project_id=project_id, study_area_id=study.entity_id,
            expected_workspace_revision=0, source_snapshot_ids=[snapshot.id],
            idempotency_key="w7-walkthrough-sync-v1", actor_kind=ActorKind.HUMAN_UI,
            actor_session_id="w7-walkthrough-human", spatial_brief=brief)
        workspace = WorkspaceService(store).sync(sync_request, dispositions=dispositions)
        workspace_record = store.current(workspace.workspace_id)
        workspace_model = WorkspaceRevision.model_validate(workspace_record.payload)
        assert workspace_record.revision == workspace_model.revision == 1
        assert len(workspace_model.feature_dispositions) == 2
        assert [item.disposition for item in workspace_model.feature_dispositions] == ["preserve", "editable"]
        assert len(workspace_model.spatial_brief.zones) == 2
        assert _workspace_payload_digest(workspace_model) == workspace_model.payload_digest

        syntax = compute_pst_six_syntax_layers(lines, calculate_radii_m=[800.0],
            study_area_geometry=box(0, 0, 100, 100), metric_mode="both")
        assert len(syntax["layers"]) == 6
        assert {layer["calculation_status"] for layer in syntax["layers"]} <= {
            "COMPUTED", "NOT_COMPUTED_COVERAGE_BLOCKED"}
        assert sum(layer["calculation_status"] == "COMPUTED" for layer in syntax["layers"]) == 2
        syntax_artifact = persist_bytes(store, project_id, tmp_path / "syntax-results", "syntax-result",
                                         canonical_bytes(syntax), parents=[normalized_source.entity_id])
        assert syntax_artifact.payload["sha256"] == "sha256:" + __import__("hashlib").sha256(
            canonical_bytes(syntax)).hexdigest()

        app = create_workspace_app(store=store, decision_key_path=key_path)
        app.state.e1_job_database = tmp_path / "walkthrough-e1-jobs.sqlite3"
        app.state.e2_job_database = tmp_path / "walkthrough-e2-jobs.sqlite3"
        app.state.e2_artifact_root = tmp_path / "walkthrough-e2-artifacts"
        with TestClient(app) as client:
            workspace_approval = client.post(f"/api/v1/projects/{project_id}/decisions", json={
                "target_id": workspace_record.entity_id, "target_type": "WorkspaceRevision",
                "target_version": str(workspace_record.revision), "target_geometry_sha256": area_hash,
                "target_payload_digest": "sha256:" + workspace_model.payload_digest,
                "action": "Approve", "status": "approved", "reason": "隔離 walkthrough：確認同步版本、保留處置與空間分區。",
                "decision_key": key, "actor_session_id": "w7-walkthrough-human",
            })
            assert workspace_approval.status_code == 201, workspace_approval.text

            constraint_digest = __import__("urban_design.constraint_sets", fromlist=["constraint_set_payload_digest"]).constraint_set_payload_digest(
                store.current("cs-d2-a").payload)
            proposals = [_proposal(store, project_id, tmp_path, f"w7-walkthrough-s{i}", x, constraint_digest)
                         for i, x in enumerate((2, 10, 18, 26), start=1)]
            proposal_ids = [row.entity_id for row in proposals]
            scenario_rows = client.get(f"/api/v1/week7/workspaces/{workspace.workspace_id}/scenarios")
            assert scenario_rows.status_code == 200
            assert {row["entity_id"] for row in scenario_rows.json()} >= set(proposal_ids)

            compared = client.post(f"/api/v1/week7/workspaces/{workspace.workspace_id}/operations/compare", json={
                "target": {"entity_id": proposals[0].entity_id, "revision": proposals[0].revision},
                "compare_targets": [{"entity_id": row.entity_id, "revision": row.revision} for row in proposals],
            })
            assert compared.status_code == 200, compared.text
            assert compared.json()["winner"] is None
            choice = client.post("/api/v1/scenarios/comparison/decision", json={
                "project_id": project_id, "scenario_ids": proposal_ids,
                "accepted_scenario_id": proposal_ids[0],
                "acceptance_reason": "隔離 walkthrough：設計者選擇第一個正式候選方案。",
                "rejected_reasons": {sid: "保留為可追溯的未選方案。" for sid in proposal_ids[1:]},
                "decision_key": key, "actor_session_id": "w7-walkthrough-human",
            })
            assert choice.status_code == 201, choice.text
            baseline = store.current(proposal_ids[0])
            assert baseline.payload["status"] == "accepted"
            assert store.current(proposal_ids[0]).payload["geometry_sha256"] == baseline.payload["geometry_sha256"]

            switched = client.post(f"/api/v1/week7/workspaces/{workspace.workspace_id}/switch", json={
                "target": {"entity_id": baseline.entity_id, "revision": baseline.revision},
                "workspace_revision": workspace_record.revision,
            })
            assert switched.status_code == 200, switched.text
            before_baseline = store.current(baseline.entity_id).to_dict()
            modify = client.post(f"/api/v1/week7/workspaces/{workspace.workspace_id}/operations/modify", json={
                "target": {"entity_id": baseline.entity_id, "revision": baseline.revision},
            })
            assert modify.status_code == 200, modify.text
            assert modify.json()["status"] == "FORMAL_DRAFT"
            draft = store.current(modify.json()["scenario_ref"]["entity_id"])
            assert draft.payload["parent_scenario_id"] == baseline.entity_id
            assert draft.payload["parameters"]["parent_revision"] == baseline.revision
            assert draft.payload["parameters"]["parent_geometry_sha256"] == baseline.payload["geometry_sha256"]
            assert draft.payload["parameters"]["acceptance_eligible"] is False
            assert store.current(baseline.entity_id).to_dict() == before_baseline

            from urban_design.environment.contracts import E1ScenarioInputBinding
            e1_plan = get_default_draft_plan().model_copy(update={
                "baseline_scenario_id": baseline.entity_id, "modified_scenario_id": draft.entity_id,
                "period": AnalysisPeriod(start_date=date(2026, 6, 21), end_date=date(2026, 6, 21),
                    dates=[date(2026, 6, 21)], start_hour=10, end_hour=11, timestep=1),
                "grid_definition": GroundGridDefinition(origin_x=0, origin_y=0, spacing_m=20,
                    crs="EPSG:28992", tag="FIXTURE_ONLY"),
            })
            e1_record = persist_e1_plan_artifact(store, e1_plan, project_id)
            e1_approval = approve_plan_artifact(store, e1_record.entity_id, decision_key=key,
                decision_key_path=key_path, actor="test-designer", actor_session_id="w7-walkthrough-human",
                reason="隔離 walkthrough：批准鎖定的 E1 計畫版本。")
            anchor_artifact = store.create("Artifact", {"id": "w7-walkthrough-e1-anchor-artifact",
                "type": "sunlight_simulation_result", "sha256": "sha256:" + "1" * 64,
                "project_id": project_id}, entity_id="w7-walkthrough-e1-anchor-artifact", project_id=project_id)
            e1_anchor = store.create("ToolExecution", {"id": "w7-walkthrough-e1-anchor",
                "scenario_id": draft.entity_id, "tool": "fixture-e1-anchor",
                "output_artifact_refs": [anchor_artifact.entity_id]},
                entity_id="w7-walkthrough-e1-anchor", project_id=project_id)
            e1_request = {"target": {"entity_id": e1_anchor.entity_id, "revision": e1_anchor.revision},
                "stage": "E1", "plan_artifact_id": e1_record.entity_id,
                "baseline_scenario_id": baseline.entity_id, "modified_scenario_id": draft.entity_id,
                "idempotency_key": "w7-walkthrough-e1"}
            e1_result = client.post(f"/api/v1/week7/workspaces/{workspace.workspace_id}/rerun", json=e1_request)
            assert e1_result.status_code == 200, e1_result.text
            assert e1_result.json()["status"] == "READY"
            assert e1_result.json()["result"]["status"] == "SUCCESS"
            assert e1_result.json()["result"]["plan"]["founder_decision_id"] == e1_approval.entity_id

            weather = publish_candidate01(store, project_id, PROPOSAL, E2_PROJECT, tmp_path / "weather-artifacts")
            qualification = validate_methods(store, project_id, weather.entity_id, tmp_path / "method-qualification")
            assert approval_artifact(client, weather, key).status_code == 201
            baseline_pin, draft_pin = _pin(store, store.current(baseline.entity_id), project_id), _pin(store, draft, project_id)
            e2_plan = E2Plan(project_id=project_id, weather_snapshot_id=weather.entity_id,
                weather_bundle_sha256=weather.payload["payload_digest"], baseline=baseline_pin, modified=draft_pin,
                grid=GroundGridDefinition(origin_x=0, origin_y=0, spacing_m=20, crs="EPSG:28992", tag="FIXTURE_ONLY"),
                true_north_deg=0, start_month=6, start_day=21, end_month=6, end_day=21,
                start_hour=9, end_hour=10, method_validation_artifact_id=qualification.entity_id)
            e2_record = publish_plan(store, e2_plan, tmp_path / "e2-plan-artifacts")
            assert approval_artifact(client, e2_record, key).status_code == 201
            e2_anchor_artifact = store.create("Artifact", {"id": "w7-walkthrough-e2-anchor-artifact",
                "type": "sunlight_simulation_result", "sha256": "sha256:" + "2" * 64,
                "project_id": project_id}, entity_id="w7-walkthrough-e2-anchor-artifact", project_id=project_id)
            e2_anchor = store.create("ToolExecution", {"id": "w7-walkthrough-e2-anchor",
                "scenario_id": draft.entity_id, "tool": "ladybug_radiance",
                "output_artifact_refs": [e2_anchor_artifact.entity_id]},
                entity_id="w7-walkthrough-e2-anchor", project_id=project_id)
            e2_request = {"target": {"entity_id": e2_anchor.entity_id, "revision": e2_anchor.revision},
                "stage": "E2", "plan_artifact_id": e2_record.entity_id,
                "baseline_scenario_id": baseline.entity_id, "modified_scenario_id": draft.entity_id,
                "idempotency_key": "w7-walkthrough-e2"}
            e2_result = client.post(f"/api/v1/week7/workspaces/{workspace.workspace_id}/rerun", json=e2_request)
            assert e2_result.status_code == 200, e2_result.text
            assert e2_result.json()["status"] == "SUCCEEDED"
            assert e2_result.json()["evidence_validation_status"] == "unverified"

            after_analysis_compare = client.post(
                f"/api/v1/week7/workspaces/{workspace.workspace_id}/operations/compare", json={
                    "target": {"entity_id": baseline.entity_id, "revision": baseline.revision},
                    "compare_targets": [{"entity_id": baseline.entity_id, "revision": baseline.revision},
                                        {"entity_id": draft.entity_id, "revision": draft.revision}],
                })
            assert after_analysis_compare.status_code == 200, after_analysis_compare.text
            assert after_analysis_compare.json()["winner"] is None
            assert e2_result.json()["job_id"]
            before_replay = len(store.list_current("ToolExecution", project_id=project_id))
            state_path = store.database
            draft_id = draft.entity_id
            e1_job_id = e1_result.json()["job_id"]
            e2_job_id = e2_result.json()["job_id"]
    finally:
        store.close()

    reopened = ProjectStateStore(state_path)
    try:
        reopened_app = create_workspace_app(store=reopened, decision_key_path=key_path)
        reopened_app.state.e1_job_database = tmp_path / "walkthrough-e1-jobs.sqlite3"
        reopened_app.state.e2_job_database = tmp_path / "walkthrough-e2-jobs.sqlite3"
        reopened_app.state.e2_artifact_root = tmp_path / "walkthrough-e2-artifacts"
        with TestClient(reopened_app) as client:
            view = client.get(f"/api/v1/week7/workspaces/workspace-{project_id}/view",
                              params={"scenario_id": draft_id})
            assert view.status_code == 200
            assert view.json()["scenario_ref"]["entity_id"] == draft_id
            assert view.json()["lineage"]
            e1_replay = client.post(f"/api/v1/week7/workspaces/workspace-{project_id}/rerun", json=e1_request)
            assert e1_replay.status_code == 200 and e1_replay.json()["job_id"] == e1_job_id
            e2_replay = client.post(f"/api/v1/week7/workspaces/workspace-{project_id}/rerun", json=e2_request)
            assert e2_replay.status_code == 200 and e2_replay.json()["job_id"] == e2_job_id
            assert len(reopened.list_current("ToolExecution", project_id=project_id)) == before_replay
            e1_jobs = GenerationJobStore(tmp_path / "walkthrough-e1-jobs.sqlite3")
            e2_jobs, _runner, _out = open_jobs(reopened, tmp_path / "walkthrough-e2-jobs.sqlite3")
            assert e1_jobs.get(e1_job_id).status is JobStatus.READY
            assert e2_jobs.get(e2_job_id).status is JobStatus.READY
            assert len(reopened.list_current("EvidenceCard", project_id=project_id)) >= 1
            persisted = reopened.current(draft_id)
            geometry_artifact = reopened.current(persisted.payload["geometry_artifact_id"])
            assert geometry_artifact.payload["sha256"] == persisted.payload["geometry_sha256"]
    finally:
        reopened.close()
