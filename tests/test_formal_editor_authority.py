"""Formal editor authority on a disposable database. The authority DB is not opened."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Polygon, box, mapping

from urban_design import decision_key
from urban_design.constraint_sets import constraint_set_payload_digest
from urban_design.editing.formal_authority import (
    FOUNDER_LAND_AREA_M2,
    FormalAuthorityError,
    PersistedFormalEditorAdapter,
    floor_polygon_gfa_m2,
    land_area_far,
)
from urban_design.models import (
    ActorKind,
    Artifact,
    Constraint,
    ConstraintSet,
    ConstraintStatus,
    DecisionAction,
    HumanDecision,
    HumanStatus,
    Scenario,
    ScenarioStatus,
    StudyArea,
    StudyAreaStatus,
)
from urban_design.scenario_api import register_scenario_routes
from urban_design.store import ProjectStateStore


PROJECT = "proj-formal"
STUDY_ID = "study-area-formal"


def _write(path: Path, document: dict) -> str:
    raw = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _artifact(store: ProjectStateStore, artifact_id: str, path: Path, digest: str) -> None:
    store.create_typed(
        Artifact(
            id=artifact_id,
            type="SCENARIO_GEOMETRY",
            uri=str(path),
            sha256=digest,
            mime="application/geo+json",
            crs="EPSG:28992",
            producer="formal-dictionary-v2",
            created_at=datetime.now(timezone.utc),
            project_id=PROJECT,
            size_bytes=path.stat().st_size,
        ),
        actor="generator",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        reason="Disposable geometry artifact",
    )


def _decision(store: ProjectStateStore, secret: str, key_path: Path, **kwargs) -> None:
    store.record_human_decision(
        HumanDecision(
            actor="designer",
            actor_kind=ActorKind.HUMAN_UI,
            actor_session_id="sess-formal-editor",
            reason="Disposable authority fixture",
            timestamp=datetime.now(timezone.utc),
            decision_event_id=f"event-{uuid.uuid4().hex}",
            **kwargs,
        ),
        decision_key=secret,
        decision_key_path=key_path,
    )


def _stages() -> dict:
    polygon = Polygon([(2, 2), (18, 2), (18, 18), (2, 18)], [[(6, 6), (10, 6), (10, 10), (6, 10)]])
    assert polygon.is_valid
    geometry = mapping(polygon)
    floors = [
        {"id": f"b-holed-floor-{level}", "level": level, "floor_height_m": 3.5, "use": "residential", "geometry": geometry}
        for level in (0, 1)
    ]
    return {
        "massing": {"buildings": [{"id": "b-holed", "use": "residential", "height_m": 7.0, "floors": floors, "footprint": geometry}]},
        "skeleton": {"edges": [{"id": "edge-1", "from_node_id": "n-start", "to_node_id": "n-end", "level": 0, "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]}}]},
    }


def _world(tmp_path: Path, stages: dict | None = None):
    key_path = tmp_path / "decision-key"
    secret = "fixture-test-key-" + uuid.uuid4().hex
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    store = ProjectStateStore(tmp_path / "editor.sqlite3")
    store.create_project({"id": PROJECT, "name": "Formal editor fixture"}, project_id=PROJECT)
    study_digest = _write(tmp_path / "study.geojson", {"type": "Feature", "properties": {}, "geometry": mapping(box(0, 0, 100, 100))})
    _artifact(store, "art-study", tmp_path / "study.geojson", study_digest)
    scenario_digest = _write(
        tmp_path / "scenario.geojson",
        {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "b-holed", "properties": {"building_id": "b-holed"}, "geometry": mapping(box(2, 2, 18, 18))}]},
    )
    _artifact(store, "art-scenario", tmp_path / "scenario.geojson", scenario_digest)
    now = datetime.now(timezone.utc)
    store.create_typed(
        StudyArea(
            id=STUDY_ID,
            project_id=PROJECT,
            version="v5",
            geometry_artifact_id="art-study",
            geometry_sha256=study_digest,
            artifact_sha256=study_digest,
            horizontal_crs="EPSG:28992",
            units="m",
            status=StudyAreaStatus.CONFIRMED_FOR_EXPLORATION,
            confirmed_actor="designer",
            confirmed_at=now,
            confirmation_event_id="event-study-confirm",
        ),
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="sess-formal-editor",
        reason="Confirm disposable study area",
    )
    _decision(
        store, secret, key_path,
        id="decision-study",
        project_id=PROJECT,
        target_id=STUDY_ID,
        target_type="StudyArea",
        target_version="v5",
        target_geometry_sha256=study_digest,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
    )
    constraint_set = ConstraintSet(
        id="cs-d2-a",
        project_id=PROJECT,
        version="v1",
        status=ConstraintStatus.PROPOSED,
        constraints=[
            Constraint(id="c-far", name="far_upper_limit", value=2.0, unit="ratio", scope="whole_site", enforcement="HARD", denominator="land_area"),
            Constraint(id="c-coverage", name="coverage_upper_limit", value=0.6, unit="ratio", scope="whole_site", enforcement="HARD"),
            Constraint(id="c-height", name="height_upper_limit", value=20.0, unit="m", scope="whole_site", enforcement="HARD"),
            Constraint(id="c-first", name="first_floor_height", value=3.5, unit="m", scope="whole_site", enforcement="HARD"),
            Constraint(id="c-standard", name="standard_floor_height", value=3.5, unit="m", scope="whole_site", enforcement="HARD"),
            Constraint(id="c-road", name="road_width", value=6.0, unit="m", scope="road:local", enforcement="HARD"),
            Constraint(id="c-rotation", name="rotation_step", value=15.0, unit="degree", scope="whole_site", enforcement="PREFERENCE"),
        ],
    )
    store.create_typed(constraint_set, actor="designer", actor_kind=ActorKind.HUMAN_UI, actor_session_id="sess-formal-editor", reason="Propose D2 A")
    definition = constraint_set_payload_digest(store.current("cs-d2-a").payload)
    _decision(
        store, secret, key_path,
        id="decision-d2",
        project_id=PROJECT,
        target_id="cs-d2-a",
        target_type="ConstraintSet",
        target_version="v1",
        target_payload_digest=definition,
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
    )
    stages = stages or _stages()
    scenario_ids = []
    for recipe_id, family, far in (("grid-mixed", "CONNECTED_GRID", 0.76), ("spine-mixed", "LINEAR_SPINE", 0.74)):
        scenario_id = f"formal-dict-editor-{recipe_id}"
        store.create_typed(
            Scenario(
                id=scenario_id,
                project_id=PROJECT,
                site_id=STUDY_ID,
                site_version="v5",
                morphology_family=family,
                geometry_artifact_id="art-scenario",
                geometry_sha256=scenario_digest,
                generator="formal-dictionary-v2",
                generator_version="formal-dictionary-v2",
                constraint_set_id="cs-d2-a",
                status=ScenarioStatus.PROPOSED,
                parameters={
                    "recipe_id": recipe_id,
                    "recipe_version": "formal-dictionary-v2",
                    "provenance": "APPROVED_INPUTS",
                    "constraint_set_digest": definition,
                    "stages": stages,
                    "validation": {"valid": True, "failure_reasons": []},
                    "metrics": {
                        "far": far,
                        "far_denominator": "land_area",
                        "far_denominator_m2": FOUNDER_LAND_AREA_M2,
                        "coverage": 0.35,
                        "highest_new_height_m": 7.0,
                        "open_space_ratio": 0.45,
                        "program_gfa_m2": {"residential": 480.0},
                        "zone_uses": [],
                    },
                },
            ),
            actor="generator",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            reason="Disposable formal proposal",
        )
        scenario_ids.append(scenario_id)
    app = FastAPI()
    register_scenario_routes(app, store, tmp_path / "draft-artifacts", decision_key_path=key_path)
    return store, TestClient(app), secret, key_path, scenario_ids, scenario_digest


def _accept(client: TestClient, secret: str, scenario_ids: list[str]) -> None:
    response = client.post("/api/v1/scenarios/comparison/decision", json={
        "project_id": PROJECT,
        "scenario_ids": scenario_ids,
        "accepted_scenario_id": scenario_ids[0],
        "acceptance_reason": "Disposable baseline for the formal editor.",
        "rejected_reasons": {scenario_ids[1]: "The other scheme is not the baseline."},
        "decision_key": secret,
        "actor_session_id": "sess-formal-editor",
    })
    assert response.status_code == 201, response.text


def test_only_an_accepted_scenario_opens_a_named_formal_draft(tmp_path: Path):
    store, client, secret, _key_path, scenario_ids, _digest = _world(tmp_path)
    _accept(client, secret, scenario_ids)
    opened = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
    assert opened.status_code == 201, opened.text
    body = opened.json()
    assert body["provenance"] == "FORMAL_DRAFT"
    assert body["status"] == "draft"
    assert body["strategy_label"] == "grid-mixed"
    assert body["editor"]["editable_buildings"]
    assert body["editor"]["editable_buildings"][0]["floors"][0]["geometry"]["coordinates"][1]
    assert body["editor"]["road_graph"]["edges"]
    assert body["editor"]["land_area_m2"] == FOUNDER_LAND_AREA_M2
    assert store.current(scenario_ids[0]).payload["status"] == "accepted"
    again = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
    assert again.status_code == 200, again.text
    assert again.json()["scenario_id"] == body["scenario_id"]
    rejected = client.post(f"/api/v1/scenarios/{scenario_ids[1]}/formal-draft")
    assert rejected.status_code == 409
    assert "REJECTED" in rejected.text
    store.create_typed(
        Scenario(
            id="formal-dict-editor-still-proposed",
            project_id=PROJECT,
            site_id=STUDY_ID,
            site_version="v5",
            morphology_family="CONNECTED_GRID",
            geometry_artifact_id="art-scenario",
            geometry_sha256=store.current(scenario_ids[0]).payload["geometry_sha256"],
            generator="formal-dictionary-v2",
            generator_version="formal-dictionary-v2",
            constraint_set_id="cs-d2-a",
            status=ScenarioStatus.PROPOSED,
            parameters={"recipe_id": "grid-late", "provenance": "APPROVED_INPUTS", "metrics": {"far_denominator": "land_area", "far_denominator_m2": FOUNDER_LAND_AREA_M2}},
        ),
        actor="generator",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        reason="Later proposal",
    )
    proposed = client.post("/api/v1/scenarios/formal-dict-editor-still-proposed/formal-draft")
    assert proposed.status_code == 409
    assert "PROPOSED" in proposed.text
    listed = client.get("/api/v1/scenarios").json()["scenarios"]
    assert any(item["scenario_id"] == scenario_ids[0] and item["strategy_label"] == "grid-mixed" for item in listed)


def test_floor_polygon_gfa_and_land_far_survive_edit_and_restart(tmp_path: Path):
    store, client, secret, _key_path, scenario_ids, _digest = _world(tmp_path)
    _accept(client, secret, scenario_ids)
    opened = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
    draft_id = opened.json()["scenario_id"]
    buildings = opened.json()["editor"]["editable_buildings"]
    gfa = floor_polygon_gfa_m2(buildings)
    bbox = sum(Polygon(floor["geometry"]["coordinates"][0]).envelope.area for building in buildings for floor in building["floors"])
    assert gfa == 480.0
    assert bbox == 512.0
    assert gfa != bbox
    assert land_area_far(gfa) == gfa / FOUNDER_LAND_AREA_M2
    edited = client.post(f"/api/v1/scenarios/{draft_id}/edits", json={
        "building_id": "b-holed",
        "command": {"type": "move", "dx_m": 1, "dy_m": 0},
        "expected_revision": 0,
        "idempotency_key": "formal-move-1",
    })
    assert edited.status_code == 201, edited.text
    assert edited.json()["validation"]["acceptance_eligible"] is False
    assert edited.json()["validation"]["analysis_eligible"] is False
    assert edited.json()["dashboard"]["land_basis"]["denominator_area_m2"] == FOUNDER_LAND_AREA_M2
    assert edited.json()["dashboard"]["land_basis"]["floor_polygon_gfa_m2"] == gfa
    assert edited.json()["dashboard"]["land_basis"]["far"] == gfa / FOUNDER_LAND_AREA_M2
    assert edited.json()["dashboard"]["site"]["far"] is None
    events_before_reuse = len(store.events(project_id=PROJECT))
    reused = client.post(f"/api/v1/scenarios/{draft_id}/edits", json={
        "building_id": "b-holed",
        "command": {"type": "move", "dx_m": 2, "dy_m": 0},
        "expected_revision": 0,
        "idempotency_key": "formal-move-1",
    })
    assert reused.status_code == 409, reused.text
    assert "idempotency key was reused" in reused.text
    assert len(store.events(project_id=PROJECT)) == events_before_reuse
    illegal = client.post(f"/api/v1/scenarios/{draft_id}/edits", json={
        "building_id": "b-holed",
        "command": {"type": "move", "dx_m": 1000, "dy_m": 0},
        "expected_revision": edited.json()["active_revision_id"],
        "idempotency_key": "formal-move-illegal",
    })
    assert illegal.status_code == 201, illegal.text
    assert illegal.json()["validation"]["geometry_valid"] is False
    assert illegal.json()["validation"]["acceptance_eligible"] is False
    assert illegal.json()["validation"]["analysis_eligible"] is False
    reopened = ProjectStateStore(tmp_path / "editor.sqlite3")
    restored = reopened.current(draft_id)
    assert restored.payload["status"] == "draft"
    assert restored.payload["parameters"]["provenance"] == "FORMAL_DRAFT"
    assert floor_polygon_gfa_m2(restored.payload["parameters"]["editable_buildings"]) == gfa
    app = FastAPI()
    register_scenario_routes(app, reopened, tmp_path / "draft-artifacts", decision_key_path=tmp_path / "decision-key")
    restarted = TestClient(app)
    undone = restarted.post(f"/api/v1/scenarios/{draft_id}/edits/undo", json={"expected_revision": illegal.json()["active_revision_id"]})
    assert undone.status_code == 200, undone.text
    redone = restarted.post(f"/api/v1/scenarios/{draft_id}/edits/redo", json={"expected_revision": undone.json()["active_revision_id"]})
    assert redone.status_code == 200, redone.text
    assert reopened.current(draft_id).payload["parameters"]["validation"]["acceptance_eligible"] is False


def _opened(tmp_path: Path):
    store, client, secret, _key_path, scenario_ids, _digest = _world(tmp_path)
    _accept(client, secret, scenario_ids)
    opened = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
    assert opened.status_code == 201, opened.text
    return store, client, scenario_ids, opened.json()["scenario_id"]


def _human_patch(store: ProjectStateStore, entity_id: str, patch: dict, reason: str) -> None:
    current = store.current(entity_id)
    store.update(
        entity_id,
        patch,
        expected_revision=current.revision,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="sess-formal-editor",
        reason=reason,
    )


def test_stale_constraint_geometry_source_parent_and_missing_event_are_refused(tmp_path: Path):
    superseded_root = tmp_path / "superseded"
    store, _client, scenario_ids, draft_id = _opened(superseded_root)
    constraint = store.current("cs-d2-a")
    _human_patch(store, "cs-d2-a", {"status": "superseded"}, "Supersede the disposable constraint set")
    assert store.current("cs-d2-a").revision == constraint.revision + 1
    with pytest.raises(FormalAuthorityError, match="is superseded"):
        PersistedFormalEditorAdapter().resolve(store, store.current(draft_id))

    geometry_root = tmp_path / "geometry"
    store, _client, _scenario_ids, draft_id = _opened(geometry_root)
    (geometry_root / "scenario.geojson").write_bytes(b'{"type":"FeatureCollection","features":[],"tampered":true}\n')
    with pytest.raises(FormalAuthorityError, match="do not match"):
        PersistedFormalEditorAdapter().resolve(store, store.current(draft_id))

    snapshot_root = tmp_path / "snapshot"
    store, client, secret, _key_path, scenario_ids, _digest = _world(snapshot_root)
    ancestor = store.current(scenario_ids[0])
    parameters = dict(ancestor.payload["parameters"])
    parameters["source_snapshot_ids"] = ["snapshot-does-not-exist"]
    _human_patch(store, scenario_ids[0], {"parameters": parameters}, "Point the proposal at an unknown source snapshot before acceptance")
    _accept(client, secret, scenario_ids)
    unknown = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
    assert unknown.status_code == 409, unknown.text
    assert "unknown source snapshot snapshot-does-not-exist" in unknown.text

    parent_root = tmp_path / "parent"
    store, _client, _scenario_ids, draft_id = _opened(parent_root)
    _human_patch(store, draft_id, {"parent_scenario_id": "formal-dict-editor-missing-parent"}, "Detach the formal draft from its accepted parent")
    with pytest.raises(FormalAuthorityError, match="missing parent scenario formal-dict-editor-missing-parent"):
        PersistedFormalEditorAdapter().resolve(store, store.current(draft_id))

    event_root = tmp_path / "event"
    store, _client, scenario_ids, draft_id = _opened(event_root)
    decisions = [
        row for row in store.list_current("HumanDecision", project_id=PROJECT)
        if row.payload.get("target_id") == scenario_ids[0] and row.payload.get("action") == "Accept"
    ]
    assert len(decisions) == 1
    event_id = decisions[0].payload["decision_event_id"]
    store.close()
    connection = sqlite3.connect(event_root / "editor.sqlite3")
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("DROP TRIGGER IF EXISTS ledger_events_append_only_delete")
        deleted = connection.execute("DELETE FROM ledger_events WHERE event_id = ?", (event_id,))
        assert deleted.rowcount == 1
        connection.commit()
    finally:
        connection.close()
    reopened = ProjectStateStore(event_root / "editor.sqlite3")
    with pytest.raises(FormalAuthorityError, match="missing approval event"):
        PersistedFormalEditorAdapter().resolve(reopened, reopened.current(draft_id))

    stale_root = tmp_path / "stale"
    store, _client, scenario_ids, draft_id = _opened(stale_root)
    _human_patch(store, scenario_ids[0], {"editor_note": "revision bumped without a new HumanDecision"}, "Bump the accepted scenario past its decision revision")
    with pytest.raises(FormalAuthorityError, match="baseline decision revision is stale"):
        PersistedFormalEditorAdapter().resolve(store, store.current(draft_id))

    mislabel_root = tmp_path / "mislabel"
    store, _client, scenario_ids, draft_id = _opened(mislabel_root)
    ancestor = store.current(scenario_ids[0])
    parameters = dict(ancestor.payload["parameters"])
    parameters["provenance"] = "FIXTURE_ONLY"
    _human_patch(store, scenario_ids[0], {"parameters": parameters, "generator": "fixture-portfolio"}, "Relabel the accepted scenario as a fixture")
    with pytest.raises(FormalAuthorityError, match="fixture or preview input cannot enter formal editing"):
        PersistedFormalEditorAdapter().resolve(store, store.current(draft_id))
