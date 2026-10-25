from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import uuid
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design import decision_key
from urban_design.models import ActorKind, Artifact, DecisionAction, HumanDecision, HumanStatus, Scenario, ScenarioStatus
from urban_design.scenario_comparison_router import create_scenario_comparison_router
from urban_design.store import PayloadError, ProjectStateStore


def _setup_test_env(tmp_path: Path, limiter: Any = None):
    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-test-key-" + uuid.uuid4().hex
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _p: secret)

    db_path = tmp_path / "test.sqlite3"
    store = ProjectStateStore(db_path)
    store.create_project({"id": "proj-formal", "name": "Formal Project"}, project_id="proj-formal")

    from urban_design.api import DecisionAttemptLimiter
    active_limiter = limiter if limiter is not None else DecisionAttemptLimiter()

    app = FastAPI()
    app.include_router(create_scenario_comparison_router(store=store, decision_key_path=key_path, decision_attempt_limiter=active_limiter))
    client = TestClient(app)

    geom_bytes = b'{"type": "FeatureCollection", "features": []}'
    geom_hash = "sha256:" + hashlib.sha256(geom_bytes).hexdigest()
    art = Artifact(
        id="art-geom-formal-1",
        type="SCENARIO_GEOMETRY",
        uri=str(tmp_path / "geom.geojson"),
        sha256=geom_hash,
        mime="application/geo+json",
        crs="EPSG:28992",
        producer="formal-dictionary-v2",
        created_at=datetime.now(timezone.utc),
        project_id="proj-formal",
        size_bytes=len(geom_bytes),
    )
    store.create_typed(art, actor="generator", actor_kind=ActorKind.AGENT_AUTOMATION, reason="Artifact")

    # Create 3 formal proposals matching formal_pipeline structure (flat metrics)
    scenarios = []
    recipes = [("grid-mixed", "CONNECTED_GRID", 0.76, 0.35, 18.0), ("common-mixed", "CENTRAL_COMMON", 0.75, 0.32, 16.0), ("spine-mixed", "LINEAR_SPINE", 0.74, 0.30, 20.0)]
    for recipe_id, family, far, cov, height in recipes:
        sid = f"formal-dict-3da03eb0172d-{recipe_id}-e4a90f11bc02"
        scen = Scenario(
            id=sid,
            project_id="proj-formal",
            site_id="rotterdam-m4h",
            site_version="v5",
            morphology_family=family,
            geometry_artifact_id="art-geom-formal-1",
            geometry_sha256=geom_hash,
            generator="formal-dictionary-v2",
            generator_version="formal-dictionary-v2",
            constraint_set_id="cs-m4h-1",
            status=ScenarioStatus.PROPOSED,
            parameters={
                "recipe_id": recipe_id,
                "recipe_version": "formal-dictionary-v2",
                "provenance": "APPROVED_INPUTS",
                "validation": {"valid": True, "failure_reasons": []},
                "metrics": {
                    "far": far,
                    "far_denominator": "net_land_area",
                    "far_denominator_m2": 125000.0,
                    "coverage": cov,
                    "highest_new_height_m": height,
                    "open_space_ratio": 0.45,
                    "program_gfa_m2": {"residential": 50000.0, "commercial": 20000.0},
                    "zone_uses": [],
                },
            },
        )
        store.create_typed(scen, actor="generator", actor_kind=ActorKind.AGENT_AUTOMATION, reason="Scenario")
        scenarios.append(sid)

    return store, client, secret, key_path, scenarios, geom_hash


def test_formal_proposals_comparison_and_baseline_decision_happy_path(tmp_path: Path):
    store, client, secret, key_path, sids, geom_hash = _setup_test_env(tmp_path)

    # 1. Deterministic comparison without overall winner
    res = client.post("/api/v1/scenarios/comparison", json={"scenario_ids": sids})
    assert res.status_code == 200
    comp = res.json()
    assert comp["status"] == "COMPARABLE"
    assert comp["ranking"] is None
    assert comp["overall_score"] is None
    assert comp["winner"] is None
    assert comp["eligibility_for_decision"]["can_accept"] is True

    # 2. Baseline decision: accept sids[0], reject sids[1] and sids[2] with explicit reasons
    dec_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "Optimal connectivity and balanced FAR.",
        "rejected_reasons": {
            sids[1]: "Open space geometry not aligned with transit.",
            sids[2]: "Linear massing creates poor microclimate shadow.",
        },
        "decision_key": secret,
        "actor_session_id": "sess-founder-001",
    }
    dec_res = client.post("/api/v1/scenarios/comparison/decision", json=dec_payload)
    assert dec_res.status_code == 201
    body = dec_res.json()
    assert body["status"] == "ACCEPTED"
    assert body["baseline_scenario_id"] == sids[0]
    assert body["baseline_geometry_sha256"] == geom_hash
    assert sids[1] in body["rejected_decisions"]
    assert sids[2] in body["rejected_decisions"]

    # Verify store status transitions
    acc_scen = store.current(sids[0])
    assert acc_scen.payload["status"] == "accepted"
    assert acc_scen.payload["baseline"] is True
    assert acc_scen.payload["baseline_reason"] == "Optimal connectivity and balanced FAR."

    rej_scen_1 = store.current(sids[1])
    assert rej_scen_1.payload["status"] == "rejected"
    assert rej_scen_1.payload["rejection_reason"] == "Open space geometry not aligned with transit."

    rej_scen_2 = store.current(sids[2])
    assert rej_scen_2.payload["status"] == "rejected"
    assert rej_scen_2.payload["rejection_reason"] == "Linear massing creates poor microclimate shadow."

    # Verify HumanDecision records in store
    decisions = store.list_current("HumanDecision", project_id="proj-formal")
    assert len(decisions) == 3
    dec_targets = {d.payload["target_id"]: d.payload for d in decisions}

    assert dec_targets[sids[0]]["action"] == "Accept"
    assert dec_targets[sids[0]]["status"] == "accepted"
    assert dec_targets[sids[0]]["target_geometry_sha256"] == geom_hash
    assert dec_targets[sids[0]]["actor_kind"] == "HUMAN_UI"

    assert dec_targets[sids[1]]["action"] == "Reject"
    assert dec_targets[sids[1]]["status"] == "rejected"
    assert dec_targets[sids[1]]["target_geometry_sha256"] == geom_hash

    assert dec_targets[sids[2]]["action"] == "Reject"
    assert dec_targets[sids[2]]["status"] == "rejected"
    assert dec_targets[sids[2]]["target_geometry_sha256"] == geom_hash

    # Verify ledger events
    events = store.events(project_id="proj-formal")
    event_actions = [e.action for e in events]
    assert "AcceptDesignScenario" in event_actions
    assert event_actions.count("RejectDesignScenario") == 2


def test_decision_wrong_key(tmp_path: Path):
    store, client, _secret, _key_path, sids, _ = _setup_test_env(tmp_path)

    dec_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "Accepted baseline.",
        "rejected_reasons": {
            sids[1]: "Rejected.",
            sids[2]: "Rejected.",
        },
        "decision_key": "wrong-secret-key-123",
        "actor_session_id": "sess-test",
    }
    res = client.post("/api/v1/scenarios/comparison/decision", json=dec_payload)
    assert res.status_code == 403
    assert "Decision key is incorrect" in res.json()["detail"]

    # Nothing written
    assert len(store.list_current("HumanDecision", project_id="proj-formal")) == 0
    assert store.current(sids[0]).payload["status"] == "proposed"


def test_decision_missing_rejection_reason(tmp_path: Path):
    store, client, secret, _key_path, sids, _ = _setup_test_env(tmp_path)

    # Missing rejection reason for sids[2]
    dec_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "Accepted baseline.",
        "rejected_reasons": {
            sids[1]: "Reasonable reason.",
            sids[2]: "   ",  # whitespace only
        },
        "decision_key": secret,
        "actor_session_id": "sess-test",
    }
    res = client.post("/api/v1/scenarios/comparison/decision", json=dec_payload)
    assert res.status_code == 422
    assert "explicit human rejection reason" in res.json()["detail"]

    # Nothing written
    assert len(store.list_current("HumanDecision", project_id="proj-formal")) == 0
    assert store.current(sids[0]).payload["status"] == "proposed"


def test_decision_missing_acceptance_reason(tmp_path: Path):
    store, client, secret, _key_path, sids, _ = _setup_test_env(tmp_path)

    dec_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "   ",
        "rejected_reasons": {
            sids[1]: "Reason 1.",
            sids[2]: "Reason 2.",
        },
        "decision_key": secret,
        "actor_session_id": "sess-test",
    }
    res = client.post("/api/v1/scenarios/comparison/decision", json=dec_payload)
    assert res.status_code == 422

    # Nothing written
    assert len(store.list_current("HumanDecision", project_id="proj-formal")) == 0


def test_double_accept_refusal(tmp_path: Path):
    store, client, secret, _key_path, sids, _ = _setup_test_env(tmp_path)

    dec_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "First acceptance.",
        "rejected_reasons": {
            sids[1]: "Reason 1.",
            sids[2]: "Reason 2.",
        },
        "decision_key": secret,
        "actor_session_id": "sess-test",
    }
    res1 = client.post("/api/v1/scenarios/comparison/decision", json=dec_payload)
    assert res1.status_code == 201

    # Attempting to accept again should be refused with 409
    res2 = client.post("/api/v1/scenarios/comparison/decision", json=dec_payload)
    assert res2.status_code == 409
    assert "already been accepted" in res2.json()["detail"]


def test_decision_non_proposed_refusal(tmp_path: Path):
    store, client, secret, _key_path, sids, _ = _setup_test_env(tmp_path)

    # Manually transition sids[1] to rejected beforehand
    store.update(sids[1], {"status": "rejected"})

    dec_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "Baseline accepted.",
        "rejected_reasons": {
            sids[1]: "Reason 1.",
            sids[2]: "Reason 2.",
        },
        "decision_key": secret,
        "actor_session_id": "sess-test",
    }
    res = client.post("/api/v1/scenarios/comparison/decision", json=dec_payload)
    assert res.status_code == 409
    assert "not in proposed status" in res.json()["detail"]

    # Nothing written for sids[0]
    assert store.current(sids[0]).payload["status"] == "proposed"


def test_agent_automation_refusal(tmp_path: Path):
    store, _client, secret, key_path, sids, geom_hash = _setup_test_env(tmp_path)

    rec = store.current(sids[0])
    auto_decision = HumanDecision(
        id=f"decision-{uuid.uuid4().hex}",
        project_id="proj-formal",
        target_id=rec.entity_id,
        target_type="DesignScenario",
        target_version=str(rec.revision),
        target_geometry_sha256=geom_hash,
        action=DecisionAction.ACCEPT,
        status=HumanStatus.ACCEPTED,
        actor="automated-bot",
        actor_kind=ActorKind.AGENT_AUTOMATION,  # Blocked!
        actor_session_id="sess-auto",
        reason="Automation attempt",
        timestamp=datetime.now(timezone.utc),
        decision_event_id=f"event-{uuid.uuid4().hex}",
    )

    with pytest.raises(PayloadError, match="HUMAN_UI"):
        store.record_human_decision(auto_decision, decision_key=secret, decision_key_path=key_path)

    with pytest.raises(PayloadError, match="HUMAN_UI"):
        store.record_scenario_comparison_decision(
            project_id="proj-formal",
            accepted_decision=auto_decision,
            rejected_decisions=[],
            decision_key=secret,
            decision_key_path=key_path,
        )


def test_decision_atomicity_on_failure(tmp_path: Path):
    store, _client, secret, key_path, sids, geom_hash = _setup_test_env(tmp_path)

    acc_rec = store.current(sids[0])
    acc_decision = HumanDecision(
        id="dec-atom-acc",
        project_id="proj-formal",
        target_id=acc_rec.entity_id,
        target_type="DesignScenario",
        target_version=str(acc_rec.revision),
        target_geometry_sha256=geom_hash,
        action=DecisionAction.ACCEPT,
        status=HumanStatus.ACCEPTED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="sess-atom",
        reason="Accepted.",
        timestamp=datetime.now(timezone.utc),
        decision_event_id="evt-atom-1",
    )

    # Valid rejection for sids[1]
    rej_rec_1 = store.current(sids[1])
    rej_decision_1 = HumanDecision(
        id="dec-atom-rej-1",
        project_id="proj-formal",
        target_id=rej_rec_1.entity_id,
        target_type="DesignScenario",
        target_version=str(rej_rec_1.revision),
        target_geometry_sha256=geom_hash,
        action=DecisionAction.REJECT,
        status=HumanStatus.REJECTED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="sess-atom",
        reason="Reason 1.",
        timestamp=datetime.now(timezone.utc),
        decision_event_id="evt-atom-2",
    )

    # Invalid rejection for sids[2] with mismatched geometry hash to force error during commit
    rej_rec_2 = store.current(sids[2])
    rej_decision_2 = HumanDecision(
        id="dec-atom-rej-2",
        project_id="proj-formal",
        target_id=rej_rec_2.entity_id,
        target_type="DesignScenario",
        target_version=str(rej_rec_2.revision),
        target_geometry_sha256="sha256:" + "0" * 64,  # mismatched hash!
        action=DecisionAction.REJECT,
        status=HumanStatus.REJECTED,
        actor="designer",
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id="sess-atom",
        reason="Reason 2.",
        timestamp=datetime.now(timezone.utc),
        decision_event_id="evt-atom-3",
    )

    with pytest.raises(PayloadError, match="target_geometry_sha256"):
        store.record_scenario_comparison_decision(
            project_id="proj-formal",
            accepted_decision=acc_decision,
            rejected_decisions=[rej_decision_1, rej_decision_2],
            decision_key=secret,
            decision_key_path=key_path,
        )

    # Atomicity check: none of the scenarios should have their status changed
    assert store.current(sids[0]).payload["status"] == "proposed"
    assert store.current(sids[1]).payload["status"] == "proposed"
    assert store.current(sids[2]).payload["status"] == "proposed"

    # No HumanDecision written
    assert len(store.list_current("HumanDecision", project_id="proj-formal")) == 0


def test_scenario_comparison_decision_rate_limiting_and_lockout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import time
    from urban_design.api import DecisionAttemptLimiter

    limiter = DecisionAttemptLimiter()
    store, client, secret, key_path, sids, geom_hash = _setup_test_env(tmp_path, limiter=limiter)

    base_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "Optimal density and excellent street network.",
        "rejected_reasons": {
            sids[1]: "Excessive height.",
            sids[2]: "Inadequate open space.",
        },
        "actor_session_id": "sess-test-rate",
    }

    current_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: current_time[0])

    # 5 wrong key attempts -> 403
    for i in range(5):
        res = client.post(
            "/api/v1/scenarios/comparison/decision",
            json={**base_payload, "decision_key": f"wrong-key-{i}"},
        )
        assert res.status_code == 403, f"Attempt {i} expected 403, got {res.status_code}"
        assert res.json()["detail"] == "Decision key is incorrect"

    # 6th attempt (even with correct key) -> 429
    res_limited = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={**base_payload, "decision_key": secret},
    )
    assert res_limited.status_code == 429
    assert "rate-limited" in res_limited.json()["detail"]

    # Verify no HumanDecision was persisted
    assert len(store.list_current("HumanDecision", project_id="proj-formal")) == 0

    # Advance monotonic time past lockout window (WINDOW_SECONDS = 15 * 60 = 900)
    current_time[0] += 901.0

    # Correct key after lockout window -> 201 Created
    res_success = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={**base_payload, "decision_key": secret},
    )
    assert res_success.status_code == 201
    assert res_success.json()["status"] == "ACCEPTED"
    assert store.current(sids[0]).payload["status"] == "accepted"


def test_scenario_comparison_decision_success_clears_prior_failures(tmp_path: Path):
    from urban_design.api import DecisionAttemptLimiter

    limiter = DecisionAttemptLimiter()
    store, client, secret, key_path, sids, geom_hash = _setup_test_env(tmp_path, limiter=limiter)

    base_payload = {
        "project_id": "proj-formal",
        "scenario_ids": sids,
        "accepted_scenario_id": sids[0],
        "acceptance_reason": "Optimal density and open space.",
        "rejected_reasons": {
            sids[1]: "Excessive height.",
            sids[2]: "Inadequate open space.",
        },
        "actor_session_id": "sess-test-clear",
    }

    # 4 wrong key attempts (below MAX_FAILURES=5)
    for i in range(4):
        res = client.post(
            "/api/v1/scenarios/comparison/decision",
            json={**base_payload, "decision_key": f"wrong-{i}"},
        )
        assert res.status_code == 403

    # 5th attempt with correct key -> succeeds and clears prior failures
    res_success = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={**base_payload, "decision_key": secret},
    )
    assert res_success.status_code == 201
    assert not limiter.is_limited("testclient")

