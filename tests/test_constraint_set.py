from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from urban_design import decision_key
from urban_design.api import create_workspace_app
from urban_design.models import ActorKind, Constraint, ConstraintSet, ConstraintStatus
from urban_design.store import ProjectStateStore
from urban_design.workspace_contracts import (
    SpatialZone,
    WorkspaceRevision,
    WorkspaceSpatialBrief,
)


def _items() -> list[dict[str, object]]:
    return [
        {"id": "far-site", "name": "far_upper_limit", "denominator": "land_area", "value": 0.8, "unit": "ratio", "scope": "whole_site", "enforcement": "HARD"},
        {"id": "far-zone-a", "name": "zone_far_upper_limit", "denominator": "land_area", "value": 0.6, "unit": "ratio", "scope": "zone:zone-a", "enforcement": "PREFERENCE"},
        {"id": "coverage-site", "name": "coverage_upper_limit", "value": 0.35, "unit": "ratio", "scope": "whole_site", "enforcement": "HARD"},
        {"id": "height-site", "name": "height_upper_limit", "value": 18.0, "unit": "m", "scope": "whole_site", "enforcement": "HARD"},
        {"id": "first-floor", "name": "first_floor_height", "value": 4.0, "unit": "m", "scope": "whole_site", "enforcement": "PREFERENCE"},
        {"id": "standard-floor", "name": "standard_floor_height", "value": 3.0, "unit": "m", "scope": "whole_site", "enforcement": "HARD"},
        {"id": "road-local", "name": "road_width", "value": 6.0, "unit": "m", "scope": "road:hierarchy-a", "enforcement": "HARD"},
        {"id": "rotation", "name": "rotation_step", "value": 15.0, "unit": "degree", "scope": "whole_site", "enforcement": "PREFERENCE"},
    ]


def _new_test_key(tmp_path: Path) -> tuple[str, Path]:
    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    return secret, key_path


def _client(tmp_path: Path, *, key_path: Path | None = None):
    store = ProjectStateStore(tmp_path / "constraints.sqlite3")
    store.create_project({"id": "project-1", "name": "fixture"}, project_id="project-1")
    app = create_workspace_app(store=store, decision_key_path=key_path)
    return store, TestClient(app)


def _create_draft(client: TestClient, *, allocation_policy: str | None = None):
    body: dict[str, object] = {"constraints": _items(), "actor_session_id": "fixture-session"}
    if allocation_policy is not None:
        body["allocation_policy"] = allocation_policy
    return client.post("/api/v1/projects/project-1/constraint-sets", json=body)


def _seed_overlapping_workspace(store: ProjectStateStore) -> None:
    left = SpatialZone(
        zone_id="zone-a", name="Zone A", target_use="mixed", geometry={
            "type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]
        }, original_text="fixture A",
    )
    right = SpatialZone(
        zone_id="zone-b", name="Zone B", target_use="mixed", geometry={
            "type": "Polygon", "coordinates": [[[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]]
        }, original_text="fixture B",
    )
    workspace = WorkspaceRevision(
        workspace_id="workspace-project-1",
        project_id="project-1",
        revision=1,
        study_area_id="area-fixture",
        spatial_brief=WorkspaceSpatialBrief(zones=[left, right]),
    )
    store.create(
        "WorkspaceRevision",
        workspace.model_dump(mode="json"),
        entity_id=workspace.workspace_id,
        project_id=workspace.project_id,
        actor="test-fixture",
        actor_kind=ActorKind.TEST_HARNESS,
    )


def _seed_single_zone_workspace(store: ProjectStateStore) -> None:
    zone = SpatialZone(
        zone_id="zone-a",
        name="Zone A",
        target_use="mixed",
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        original_text="fixture zone",
    )
    workspace = WorkspaceRevision(
        workspace_id="workspace-project-1",
        project_id="project-1",
        revision=1,
        study_area_id="area-fixture",
        spatial_brief=WorkspaceSpatialBrief(zones=[zone]),
    )
    store.create(
        "WorkspaceRevision",
        workspace.model_dump(mode="json"),
        entity_id=workspace.workspace_id,
        project_id=workspace.project_id,
        actor="test-fixture",
        actor_kind=ActorKind.TEST_HARNESS,
    )


def test_constraint_model_supports_units_scope_provenance_and_enforcement() -> None:
    item = Constraint.model_validate(_items()[0])
    draft = ConstraintSet(
        id="constraints-fixture",
        project_id="project-1",
        version="v1",
        constraints=[item],
    )

    assert item.unit == "ratio"
    assert item.scope == "whole_site"
    assert item.enforcement == "HARD"
    assert item.source_refs == []
    assert draft.status is ConstraintStatus.PROPOSED


def test_api_creates_and_reads_a_proposed_constraint_set_without_decision(tmp_path: Path) -> None:
    store, client = _client(tmp_path)
    _seed_single_zone_workspace(store)
    created = _create_draft(client)

    assert created.status_code == 201, created.text
    result = created.json()
    assert result["constraint_set"]["status"] == "proposed"
    assert result["constraint_set"]["constraints"][0]["source_refs"] == []
    assert len(result["constraint_set"]["constraints"]) == 8
    assert result["payload_digest"].startswith("sha256:")
    loaded = client.get(
        f"/api/v1/projects/project-1/constraint-sets/{result['constraint_set']['id']}"
    )
    assert loaded.status_code == 200
    assert loaded.json()["payload_digest"] == result["payload_digest"]
    assert store._connection.execute(
        "SELECT COUNT(*) FROM state_heads WHERE entity_type='HumanDecision'"
    ).fetchone()[0] == 0
    store.close()


def test_overlapping_zones_without_allocation_rule_are_rejected(tmp_path: Path) -> None:
    store, client = _client(tmp_path)
    _seed_overlapping_workspace(store)

    rejected = _create_draft(client)
    assert rejected.status_code == 422
    assert "allocation" in rejected.json()["detail"].lower()
    accepted = _create_draft(client, allocation_policy="priority")
    assert accepted.status_code == 201, accepted.text
    store.close()


def test_only_the_authenticated_version_and_hash_decision_activates_set(tmp_path: Path) -> None:
    secret, key_path = _new_test_key(tmp_path)
    store, client = _client(tmp_path, key_path=key_path)
    _seed_single_zone_workspace(store)
    created = _create_draft(client)
    assert created.status_code == 201, created.text
    body = created.json()
    constraint_set = body["constraint_set"]
    decision_url = "/api/v1/projects/project-1/decisions"
    decision = {
        "target_id": constraint_set["id"],
        "target_type": "ConstraintSet",
        "target_version": "stale-v0",
        "target_payload_digest": body["payload_digest"],
        "action": "Approve",
        "status": "approved",
        "reason": "Approve this fixture set.",
        "decision_key": secret,
        "actor_session_id": "fixture-decision-session",
    }

    stale_version = client.post(decision_url, json=decision)
    assert stale_version.status_code == 409
    bad_hash = {**decision, "target_version": "v1", "target_payload_digest": "sha256:" + "0" * 64}
    stale_hash = client.post(decision_url, json=bad_hash)
    assert stale_hash.status_code == 409
    assert store._connection.execute(
        "SELECT COUNT(*) FROM state_heads WHERE entity_type='HumanDecision'"
    ).fetchone()[0] == 0

    valid = client.post(
        decision_url,
        json={**decision, "target_version": "v1"},
    )
    assert valid.status_code == 201, valid.text
    decision_id = valid.json()["id"]
    active = store.current(constraint_set["id"])
    assert active.revision == 2
    assert active.payload["status"] == "effective"
    assert all(item["status"] == "effective" for item in active.payload["constraints"])
    assert all(item["source_refs"] == [decision_id] for item in active.payload["constraints"])
    store.close()


def test_invalid_units_and_parameter_names_cannot_be_saved_as_drafts(tmp_path: Path) -> None:
    store, client = _client(tmp_path)
    invalid_items = [dict(_items()[0], unit="meters")]
    response = client.post(
        "/api/v1/projects/project-1/constraint-sets",
        json={"constraints": invalid_items, "actor_session_id": "fixture-session"},
    )
    assert response.status_code == 422
    unknown = [dict(_items()[0], name="legal_far")]
    response = client.post(
        "/api/v1/projects/project-1/constraint-sets",
        json={"constraints": unknown, "actor_session_id": "fixture-session"},
    )
    assert response.status_code == 422
    store.close()
