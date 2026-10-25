from copy import deepcopy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.constraint_sets import constraint_set_payload_digest
from urban_design.models import ConstraintSet
from urban_design.store import PayloadError, ProjectStateStore


def body():
    return {
        "id": "agent-draft", "idempotency_key": "fixed-request", "actor_kind": "AGENT_AUTOMATION",
        "actor_session_id": "agent-session", "notes": "review these assumptions",
        "constraints": [{"id": "far", "name": "far_upper_limit", "value": 0.8, "unit": "ratio",
                         "scope": "whole_site", "enforcement": "HARD", "denominator": "land_area",
                         "source_note": "FOUNDER_STATED"}],
    }


@pytest.fixture
def setup(tmp_path):
    store = ProjectStateStore(tmp_path / "drafts.sqlite3")
    store.create_project({"id": "p", "name": "fixture"}, project_id="p")
    with TestClient(create_workspace_app(store=store)) as client:
        yield store, client
    store.close()


def test_agent_provenance_idempotency_and_conflicts(setup):
    store, client = setup
    url = "/api/v1/projects/p/constraint-sets"
    first = client.post(url, json=body())
    assert first.status_code == 201
    assert client.post(url, json=body()).json() == first.json()
    events = store.events(target_id="agent-draft")
    assert len(events) == 1
    assert events[0].actor == "agent-automation"
    assert events[0].actor_kind.value == "AGENT_AUTOMATION"
    assert events[0].actor_session_id == "agent-session"
    assert store.current("agent-draft").revision == 1
    for patch in ({"notes": "changed"}, {"id": "other"}, {"actor_kind": "HUMAN_UI"}, {"idempotency_key": "other"}):
        assert client.post(url, json={**body(), **patch}).status_code == 409
    assert store.list_current("HumanDecision", project_id="p") == []


def test_default_human_and_key_without_id(setup):
    store, client = setup
    request = body()
    request.pop("actor_kind")
    request.pop("id")
    url = "/api/v1/projects/p/constraint-sets"
    first = client.post(url, json=request)
    assert first.status_code == 201
    assert client.post(url, json=request).json() == first.json()
    assert store.events(target_id=first.json()["constraint_set"]["id"])[0].actor_kind.value == "HUMAN_UI"


@pytest.mark.parametrize("name,scope", [("far_upper_limit", "whole_site"), ("zone_far_upper_limit", "zone:z")])
@pytest.mark.parametrize("denominator", [None, "water_area"])
def test_far_requires_explicit_valid_denominator(setup, name, scope, denominator):
    _, client = setup
    request = body()
    request["constraints"][0].update(name=name, scope=scope, denominator=denominator)
    assert client.post("/api/v1/projects/p/constraint-sets", json=request).status_code == 422


@pytest.mark.parametrize("status", ["effective", "superseded", "invalid", "challenged"])
def test_agent_cannot_create_or_change_non_draft_state(setup, status):
    store, client = setup
    request = body()
    assert client.post("/api/v1/projects/p/constraint-sets", json={**request, "status": status}).status_code == 422
    assert client.post("/api/v1/projects/p/constraint-sets", json=request).status_code == 201
    with pytest.raises(PayloadError, match="AGENT_AUTOMATION"):
        store.update("agent-draft", {"status": status}, actor="agent-automation", actor_kind="AGENT_AUTOMATION")
    payload = store.current("agent-draft").as_dict()
    payload.update(id="bypass", status=status)
    with pytest.raises(PayloadError, match="only create"):
        store.create("ConstraintSet", payload, entity_id="bypass", actor_kind="AGENT_AUTOMATION")
    assert store.current("agent-draft").revision == 1


@pytest.mark.parametrize("action", ["Approve", "Activate", "Deactivate", "Reject"])
def test_agent_decision_requests_rejected_before_key_access(setup, action, monkeypatch):
    store, client = setup
    def forbidden(*args, **kwargs):
        pytest.fail("Agent request must not access the decision key")
    monkeypatch.setattr("urban_design.api.verify_decision_key_strict", forbidden)
    response = client.post("/api/v1/projects/p/decisions", json={
        "actor_kind": "AGENT_AUTOMATION", "action": action, "target_id": "agent-draft",
        "target_type": "ConstraintSet", "target_version": "v1", "status": "approved",
        "target_payload_digest": "sha256:" + "0" * 64, "reason": "agent request", "actor_session_id": "agent",
    })
    assert response.status_code == 422
    with pytest.raises(PayloadError):
        store.create("HumanDecision", {}, actor_kind="AGENT_AUTOMATION")
    assert store.list_current("HumanDecision", project_id="p") == []


def test_legacy_digest_and_new_fields():
    legacy = {"id": "old", "project_id": "p", "version": "v1", "allocation_policy": None,
              "constraints": [{"id": "far", "name": "far_upper_limit", "value": 0.8, "unit": "ratio",
                               "scope": "whole_site", "enforcement": "HARD"}]}
    old_hash = "sha256:" + hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert constraint_set_payload_digest(legacy) == old_hash
    assert constraint_set_payload_digest(ConstraintSet.model_validate(legacy)) == old_hash
    for field, value in (("notes", "review"), ("source_note", "ASSUMED"), ("denominator", "land_area")):
        modified = deepcopy(legacy)
        target = modified if field == "notes" else modified["constraints"][0]
        target[field] = value
        assert constraint_set_payload_digest(modified) != old_hash
        target[field] = None
        assert constraint_set_payload_digest(modified) == old_hash
    changed = deepcopy(legacy)
    changed["status"] = "effective"
    changed["constraints"][0]["source_refs"] = ["decision-ref"]
    assert constraint_set_payload_digest(changed) == old_hash


def test_retry_after_state_change_returns_original_receipt_without_new_revision(setup):
    store, client = setup
    url = "/api/v1/projects/p/constraint-sets"
    original = client.post(url, json=body()).json()
    # Test fixture only: no HumanDecision or decision key is created.
    store.update("agent-draft", {"status": "effective"}, actor_kind="TEST_HARNESS")
    assert client.post(url, json=body()).json() == original
    assert store.current("agent-draft").revision == 2
    assert len(store.events(target_id="agent-draft")) == 2


def test_nested_active_constraints_and_batch_bypass_are_rejected(setup):
    store, client = setup
    request = body()
    request["constraints"][0]["status"] = "effective"
    assert client.post("/api/v1/projects/p/constraint-sets", json=request).status_code == 422
    payload = ConstraintSet(id="batch-agent", project_id="p", version="v1", constraints=request["constraints"]).model_dump(mode="json")
    with pytest.raises(PayloadError, match="only create"):
        store.commit_batch(entities=[{
            "entity_id": "batch-agent", "entity_type": "ConstraintSet", "payload": payload,
            "event_id": "batch-event", "actor_kind": "AGENT_AUTOMATION",
        }], events=[])
    assert not store.list_current("ConstraintSet", project_id="p")


def test_legacy_record_remains_readable_via_api(setup):
    store, client = setup
    request = body()
    item = request["constraints"][0]
    item.pop("denominator")
    item.pop("source_note")
    legacy = {"id": "legacy", "project_id": "p", "version": "v1", "constraints": [item], "allocation_policy": None, "status": "proposed"}
    store.create("ConstraintSet", legacy, entity_id="legacy", actor_kind="TEST_HARNESS")
    result = client.get("/api/v1/projects/p/constraint-sets/legacy")
    assert result.status_code == 200
    assert result.json()["payload_digest"] == constraint_set_payload_digest(legacy)


def test_agent_store_creation_requires_far_denominator(setup):
    store, _ = setup
    request = body()
    request["constraints"][0].pop("denominator")
    draft = ConstraintSet(id="missing-denominator", project_id="p", version="v1", constraints=request["constraints"])
    with pytest.raises(PayloadError, match="valid ConstraintSet drafts"):
        store.create_typed(draft, actor="agent-automation", actor_kind="AGENT_AUTOMATION")


def test_list_constraint_sets_returns_current_heads_summary(setup):
    store, client = setup
    res0 = client.get("/api/v1/projects/p/constraint-sets")
    assert res0.status_code == 200
    assert res0.json() == {"items": []}

    req1 = body()
    req1["id"] = "draft-1"
    req1["idempotency_key"] = "req-1"
    client.post("/api/v1/projects/p/constraint-sets", json=req1)

    req2 = body()
    req2["id"] = "draft-2"
    req2["idempotency_key"] = "req-2"
    client.post("/api/v1/projects/p/constraint-sets", json=req2)

    events_before = len(store.events(project_id="p"))
    res = client.get("/api/v1/projects/p/constraint-sets")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 2
    ids = {item["id"] for item in items}
    assert ids == {"draft-1", "draft-2"}
    for item in items:
        assert item["status"] == "proposed"
        assert item["version"] == "v1"
        assert item["payload_digest"].startswith("sha256:")
        assert item["constraint_count"] == 1
    assert len(store.events(project_id="p")) == events_before

