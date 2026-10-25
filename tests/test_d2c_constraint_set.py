from __future__ import annotations

import copy
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from scripts.d2c_formal_run import (
    D2C_ACTOR_SESSION_ID,
    D2C_ID,
    D2C_IDEMPOTENCY_KEY,
    D2C_NOTES,
    build_d2c_constraints,
    build_d2c_draft_payload,
)
from urban_design import decision_key
from urban_design.api import create_workspace_app
from urban_design.constraint_sets import (
    constraint_set_payload_digest,
    validate_constraint_set_definition,
)
from urban_design.models import ActorKind, Constraint, ConstraintSet, ConstraintStatus
from urban_design.store import ProjectStateStore


def _new_test_key(tmp_path: Path) -> tuple[str, Path]:
    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-d2c-" + uuid.uuid4().hex + "-K"
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    return secret, key_path


def _client(tmp_path: Path, *, project_id: str = "rotterdam-m4h-pilot-project", key_path: Path | None = None):
    store = ProjectStateStore(tmp_path / "d2c-test.sqlite3")
    store.create_project({"id": project_id, "name": "Rotterdam M4H Pilot"}, project_id=project_id)
    app = create_workspace_app(store=store, decision_key_path=key_path)
    return store, TestClient(app)


def test_d2c_draft_payload_definition_and_completeness() -> None:
    payload = build_d2c_draft_payload()
    assert payload["id"] == D2C_ID
    assert payload["actor_kind"] == "AGENT_AUTOMATION"
    assert payload["idempotency_key"] == D2C_IDEMPOTENCY_KEY
    assert "Founder 2026-10-11／10-15 決定" in payload["notes"]
    assert "146,873 m²" in payload["notes"]
    assert "124,842.05 m²" in payload["notes"]
    assert "1–2 層" in payload["notes"]

    constraints = [Constraint.model_validate(c) for c in payload["constraints"]]
    draft = ConstraintSet(
        id=payload["id"],
        project_id="rotterdam-m4h-pilot-project",
        version="v1",
        constraints=constraints,
        notes=payload["notes"],
        status=ConstraintStatus.PROPOSED,
    )

    # Must pass complete validation required for activation
    validate_constraint_set_definition(draft, require_complete=True, require_far_denominator=True)
    digest = constraint_set_payload_digest(draft)
    assert digest.startswith("sha256:")
    assert len(digest) == 71

    # Check the 4 Founder decision items & baseline values
    by_name = {c.name: c for c in constraints if c.name != "road_width"}
    assert by_name["far_upper_limit"].value == 0.8
    assert by_name["far_upper_limit"].denominator == "land_area"
    assert by_name["far_upper_limit"].enforcement == "HARD"
    assert "146,873 m²" in (by_name["far_upper_limit"].source_note or "")

    assert by_name["height_upper_limit"].value == 20.0
    assert by_name["first_floor_height"].value == 4.0
    assert by_name["standard_floor_height"].value == 3.5
    assert by_name["coverage_upper_limit"].value == 0.35
    assert by_name["rotation_step"].value == 15.0

    roads = {c.scope: c.value for c in constraints if c.name == "road_width"}
    assert roads == {"road:primary": 14.0, "road:secondary": 10.0, "road:residential": 6.0}


def test_d2c_draft_creation_and_idempotency(tmp_path: Path) -> None:
    store, client = _client(tmp_path)
    url = "/api/v1/projects/rotterdam-m4h-pilot-project/constraint-sets"
    draft_req = build_d2c_draft_payload()

    # 1. First creation
    first_resp = client.post(url, json=draft_req)
    assert first_resp.status_code == 201, first_resp.text
    first_body = first_resp.json()
    assert first_body["constraint_set"]["id"] == D2C_ID
    assert first_body["constraint_set"]["status"] == "proposed"
    assert first_body["revision"] == 1
    assert first_body["payload_digest"].startswith("sha256:")
    assert len(first_body["constraint_set"]["constraints"]) == 9
    assert all(c["source_refs"] == [] for c in first_body["constraint_set"]["constraints"])

    # Verify event ledger recording
    events = store.events(target_id=D2C_ID)
    assert len(events) == 1
    assert events[0].actor == "agent-automation"
    assert events[0].actor_kind == ActorKind.AGENT_AUTOMATION
    assert events[0].actor_session_id == D2C_ACTOR_SESSION_ID
    assert events[0].action == "CreateConstraintSetDraft"

    # 2. Idempotent repeat call
    second_resp = client.post(url, json=draft_req)
    assert second_resp.status_code == 201
    assert second_resp.json() == first_body
    assert len(store.events(target_id=D2C_ID)) == 1

    # 3. Conflict on modified payload with same ID/idempotency key
    conflict_req = copy.deepcopy(draft_req)
    conflict_req["notes"] = "Tampered notes"
    conflict_resp = client.post(url, json=conflict_req)
    assert conflict_resp.status_code == 409
    store.close()


def test_d2c_unapproved_does_not_become_effective(tmp_path: Path) -> None:
    store, client = _client(tmp_path)
    draft_req = build_d2c_draft_payload()
    created = client.post("/api/v1/projects/rotterdam-m4h-pilot-project/constraint-sets", json=draft_req)
    assert created.status_code == 201

    # Check via GET endpoint
    get_resp = client.get(f"/api/v1/projects/rotterdam-m4h-pilot-project/constraint-sets/{D2C_ID}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["constraint_set"]["status"] == "proposed"
    assert body["revision"] == 1
    assert all(c["status"] == "proposed" for c in body["constraint_set"]["constraints"])

    # Verify no HumanDecision in store
    assert store.list_current("HumanDecision", project_id="rotterdam-m4h-pilot-project") == []
    store.close()


def test_d2c_decision_wrong_key_rejected(tmp_path: Path) -> None:
    secret, key_path = _new_test_key(tmp_path)
    store, client = _client(tmp_path, key_path=key_path)
    draft_req = build_d2c_draft_payload()
    created = client.post("/api/v1/projects/rotterdam-m4h-pilot-project/constraint-sets", json=draft_req)
    assert created.status_code == 201
    digest = created.json()["payload_digest"]

    decision_url = "/api/v1/projects/rotterdam-m4h-pilot-project/decisions"
    bad_submission = {
        "target_id": D2C_ID,
        "target_type": "ConstraintSet",
        "target_version": "v1",
        "target_payload_digest": digest,
        "action": "Approve",
        "status": "approved",
        "reason": "Approval attempt with wrong key",
        "actor_session_id": "founder-test-session",
        "decision_key": "totally-wrong-password",
    }

    bad_resp = client.post(decision_url, json=bad_submission)
    assert bad_resp.status_code == 403
    assert "Decision key is incorrect" in bad_resp.json()["detail"]

    # D2-C must remain proposed and no decision stored
    active = store.current(D2C_ID)
    assert active.revision == 1
    assert active.payload["status"] == "proposed"
    assert store.list_current("HumanDecision", project_id="rotterdam-m4h-pilot-project") == []
    store.close()


def test_d2c_decision_approval_activates_d2c_and_preserves_d2a_and_d2b(tmp_path: Path) -> None:
    secret, key_path = _new_test_key(tmp_path)
    store, client = _client(tmp_path, key_path=key_path)

    # Seed existing D2-A (effective) and D2-B (proposed)
    d2a_payload = {
        "id": "constraint-set-d2-a-20261001",
        "project_id": "rotterdam-m4h-pilot-project",
        "version": "v1",
        "status": "effective",
        "notes": "D2 A",
        "constraints": [
            {"id": "d2-a-far", "name": "far_upper_limit", "value": 0.8, "unit": "ratio", "scope": "whole_site", "enforcement": "HARD", "denominator": "land_area", "status": "effective", "source_refs": ["decision-seed-d2a"]},
            {"id": "d2-a-cov", "name": "coverage_upper_limit", "value": 0.35, "unit": "ratio", "scope": "whole_site", "enforcement": "HARD", "status": "effective", "source_refs": ["decision-seed-d2a"]},
            {"id": "d2-a-hgt", "name": "height_upper_limit", "value": 20.0, "unit": "m", "scope": "whole_site", "enforcement": "HARD", "status": "effective", "source_refs": ["decision-seed-d2a"]},
            {"id": "d2-a-ffh", "name": "first_floor_height", "value": 3.5, "unit": "m", "scope": "whole_site", "enforcement": "HARD", "status": "effective", "source_refs": ["decision-seed-d2a"]},
            {"id": "d2-a-sfh", "name": "standard_floor_height", "value": 3.5, "unit": "m", "scope": "whole_site", "enforcement": "HARD", "status": "effective", "source_refs": ["decision-seed-d2a"]},
            {"id": "d2-a-rd", "name": "road_width", "value": 14.0, "unit": "m", "scope": "road:primary", "enforcement": "HARD", "status": "effective", "source_refs": ["decision-seed-d2a"]},
            {"id": "d2-a-rot", "name": "rotation_step", "value": 15.0, "unit": "degree", "scope": "whole_site", "enforcement": "HARD", "status": "effective", "source_refs": ["decision-seed-d2a"]},
        ],
    }
    store.create("ConstraintSet", d2a_payload, entity_id="constraint-set-d2-a-20261001", actor_kind=ActorKind.HUMAN_UI)

    d2b_payload = {
        "id": "constraint-set-d2-b-20261001",
        "project_id": "rotterdam-m4h-pilot-project",
        "version": "v1",
        "status": "proposed",
        "notes": "D2 B",
        "constraints": [
            {"id": "d2-b-far", "name": "far_upper_limit", "value": 2.0, "unit": "ratio", "scope": "whole_site", "enforcement": "HARD", "denominator": "land_area", "status": "proposed", "source_refs": []},
            {"id": "d2-b-cov", "name": "coverage_upper_limit", "value": 0.5, "unit": "ratio", "scope": "whole_site", "enforcement": "HARD", "status": "proposed", "source_refs": []},
            {"id": "d2-b-hgt", "name": "height_upper_limit", "value": 40.0, "unit": "m", "scope": "whole_site", "enforcement": "HARD", "status": "proposed", "source_refs": []},
            {"id": "d2-b-ffh", "name": "first_floor_height", "value": 3.5, "unit": "m", "scope": "whole_site", "enforcement": "HARD", "status": "proposed", "source_refs": []},
            {"id": "d2-b-sfh", "name": "standard_floor_height", "value": 3.5, "unit": "m", "scope": "whole_site", "enforcement": "HARD", "status": "proposed", "source_refs": []},
            {"id": "d2-b-rd", "name": "road_width", "value": 14.0, "unit": "m", "scope": "road:primary", "enforcement": "HARD", "status": "proposed", "source_refs": []},
            {"id": "d2-b-rot", "name": "rotation_step", "value": 15.0, "unit": "degree", "scope": "whole_site", "enforcement": "HARD", "status": "proposed", "source_refs": []},
        ],
    }
    store.create("ConstraintSet", d2b_payload, entity_id="constraint-set-d2-b-20261001", actor_kind=ActorKind.AGENT_AUTOMATION)

    # 1. Create D2-C draft
    draft_req = build_d2c_draft_payload()
    created = client.post("/api/v1/projects/rotterdam-m4h-pilot-project/constraint-sets", json=draft_req)
    assert created.status_code == 201
    digest = created.json()["payload_digest"]

    # 2. Approve D2-C
    decision_url = "/api/v1/projects/rotterdam-m4h-pilot-project/decisions"
    submission = {
        "target_id": D2C_ID,
        "target_type": "ConstraintSet",
        "target_version": "v1",
        "target_payload_digest": digest,
        "action": "Approve",
        "status": "approved",
        "reason": "Founder 批准 D2-C 約束集正式生效",
        "actor_session_id": "founder-formal-session",
        "decision_key": secret,
    }
    decision_resp = client.post(decision_url, json=submission)
    assert decision_resp.status_code == 201, decision_resp.text
    decision_id = decision_resp.json()["id"]

    # 3. Verify D2-C is activated (status effective, revision 2)
    d2c_active = store.current(D2C_ID)
    assert d2c_active.revision == 2
    assert d2c_active.payload["status"] == "effective"
    assert len(d2c_active.payload["constraints"]) == 9
    assert all(c["status"] == "effective" for c in d2c_active.payload["constraints"])
    assert all(c["source_refs"] == [decision_id] for c in d2c_active.payload["constraints"])

    # 4. Verify D2-A and D2-B are unharmed and retain their states per system rules
    d2a_current = store.current("constraint-set-d2-a-20261001")
    assert d2a_current.payload["status"] == "effective"
    assert d2a_current.revision == 1

    d2b_current = store.current("constraint-set-d2-b-20261001")
    assert d2b_current.payload["status"] == "proposed"
    assert d2b_current.revision == 1

    store.close()
