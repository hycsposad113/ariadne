from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore


def _fixture_client(tmp_path: Path) -> tuple[TestClient, ProjectStateStore, Path]:
    store = ProjectStateStore(tmp_path / "scenarios.sqlite3")
    artifact_root = tmp_path / "scenario-artifacts"
    return TestClient(create_workspace_app(store=store, scenario_artifact_root=artifact_root)), store, artifact_root


def test_fixture_generation_persists_scenarios_artifacts_and_tool_executions(tmp_path: Path) -> None:
    client, store, artifact_root = _fixture_client(tmp_path)

    response = client.post(
        "/api/v1/scenarios/fixtures",
        json={
            "fixture_id": "synthetic-rectangle-100x80-v1",
            "width_m": 100,
            "height_m": 80,
            "seed": 41,
            "road_width_m": 6,
            "first_floor_height_m": 3,
            "standard_floor_height_m": 3,
            "strategy_floor_count": 4,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["provenance"] == "FIXTURE_ONLY"
    assert len(payload["scenarios"]) == 3
    assert len(store.list_current("Scenario")) == 3
    assert len(store.list_current("Artifact")) == 3
    assert len(store.list_current("ToolExecution")) == 3
    assert store.list_current("HumanDecision") == []
    for candidate in payload["scenarios"]:
        scenario = store.current(candidate["scenario_id"])
        artifact = store.current(scenario.payload["geometry_artifact_id"])
        run = store.current(candidate["tool_execution_id"])
        assert scenario.payload["status"] == "proposed"
        assert scenario.payload["parameters"]["provenance"] == "FIXTURE_ONLY"
        assert scenario.payload["parameters"]["input_hash"].startswith("sha256:")
        assert run.payload["parameters"]["validation"]["valid"] is candidate["valid"]
        assert artifact.payload["crs"] == "EPSG:28992"
        geometry_path = Path(artifact.payload["uri"])
        assert artifact_root in geometry_path.parents
        document = json.loads(geometry_path.read_text(encoding="utf-8"))
        assert document["crs"]["properties"]["name"] == "EPSG:28992"
        detail = client.get(f"/api/v1/scenarios/{candidate['scenario_id']}")
        assert detail.status_code == 200
        assert detail.json()["strategy_explanation_status"] == "非 AI 生成"


def test_invalid_fixture_candidates_are_retained_with_validation_reasons(tmp_path: Path) -> None:
    client, store, _artifact_root = _fixture_client(tmp_path)

    response = client.post(
        "/api/v1/scenarios/fixtures",
        json={
            "fixture_id": "synthetic-invalid-height-v1",
            "width_m": 100,
            "height_m": 80,
            "seed": 42,
            "road_width_m": 6,
            "first_floor_height_m": 3,
            "standard_floor_height_m": 3,
            "strategy_floor_count": 4,
            "max_height_m": 2,
        },
    )

    assert response.status_code == 201, response.text
    assert len(response.json()["scenarios"]) == 3
    assert all(item["valid"] is False for item in response.json()["scenarios"])
    assert all(item["failure_reasons"] for item in response.json()["scenarios"])
    assert len(store.list_current("Scenario")) == 3
    assert all(record.payload["parameters"]["validation"]["failure_reasons"] for record in store.list_current("Scenario"))


def test_comparison_api_uses_persisted_scenarios_and_has_no_ranking(tmp_path: Path) -> None:
    client, _store, _artifact_root = _fixture_client(tmp_path)
    generated = client.post(
        "/api/v1/scenarios/fixtures",
        json={
            "fixture_id": "synthetic-comparison-v1",
            "width_m": 100,
            "height_m": 80,
            "seed": 43,
            "road_width_m": 6,
            "first_floor_height_m": 3,
            "standard_floor_height_m": 3,
            "strategy_floor_count": 4,
        },
    )
    assert generated.status_code == 201
    scenario_ids = [item["scenario_id"] for item in generated.json()["scenarios"]]

    compared = client.post("/api/v1/scenarios/comparison", json={"scenario_ids": scenario_ids})

    assert compared.status_code == 200, compared.text
    result = compared.json()
    assert result["status"] == "COMPARABLE"
    assert result["ranking"] is None
    assert result["overall_score"] is None
    assert result["winner"] is None
    assert {row["metric_id"] for row in result["metrics"]} >= {
        "far", "coverage_ratio", "height_m", "road_ratio", "open_space_ratio"
    }
    assert result["eligibility_for_decision"]["can_accept"] is False
    assert result["eligibility_for_decision"]["status"] == "BLOCKED_PREVIEWS_ONLY"


def _create_formal_scenarios(store: ProjectStateStore, artifact_root: Path, project_id: str = "proj-1") -> list[str]:
    from datetime import datetime, timezone
    from urban_design.models import Artifact, Scenario, ScenarioStatus
    import hashlib

    scenario_ids = []
    geom_bytes = b'{"type": "FeatureCollection", "features": []}'
    geom_hash = "sha256:" + hashlib.sha256(geom_bytes).hexdigest()
    geom_path = artifact_root / "formal-geometry.geojson"
    geom_path.parent.mkdir(parents=True, exist_ok=True)
    geom_path.write_bytes(geom_bytes)

    art = Artifact(
        id="art-formal-geom",
        type="SCENARIO_GEOMETRY",
        uri=str(geom_path),
        sha256=geom_hash,
        mime="application/geo+json",
        crs="EPSG:28992",
        producer="formal-generator",
        created_at=datetime.now(timezone.utc),
        project_id=project_id,
        size_bytes=len(geom_bytes),
    )
    store.create_typed(art, actor="generator", actor_kind="AGENT_AUTOMATION", reason="Formal artifact")

    for i in range(1, 4):
        sid = f"formal-proposal-{i}"
        scen = Scenario(
            id=sid,
            project_id=project_id,
            site_id="rotterdam-m4h",
            site_version="v1",
            morphology_family=f"family-{i}",
            geometry_artifact_id="art-formal-geom",
            geometry_sha256=geom_hash,
            generator="formal-generator-v1",
            generator_version="1.0.0",
            seed=100 + i,
            constraint_set_id="cs-m4h-approved-v1",
            status=ScenarioStatus.PROPOSED,
            parameters={
                "provenance": "FORMAL_PROPOSAL",
                "strategy_id": f"strategy-{i}",
                "strategy_label": f"Formal Strategy {i}",
                "comparison_basis": {
                    "denominator_hash": "sha256:" + "d" * 64,
                    "rules_version": "rules-v1",
                },
                "validation": {"valid": True, "failure_reasons": []},
                "metrics": {
                    "far": {"value": 1.0 + i * 0.2, "unit": "ratio", "method": "gfa/site-area", "validation_status": "VALIDATED"},
                    "coverage_ratio": {"value": 0.2 + i * 0.05, "unit": "ratio", "method": "footprint/site-area", "validation_status": "VALIDATED"},
                    "height_m": {"value": 12.0 + i * 3.0, "unit": "m", "method": "floor height", "validation_status": "VALIDATED"},
                    "road_ratio": {"value": 0.1, "unit": "ratio", "method": "road/site-area", "validation_status": "VALIDATED"},
                    "open_space_ratio": {"value": 0.3, "unit": "ratio", "method": "open-space/site-area", "validation_status": "VALIDATED"},
                },
            },
        )
        store.create_typed(scen, actor="generator", actor_kind="AGENT_AUTOMATION", reason="Formal scenario")
        scenario_ids.append(sid)
    return scenario_ids


def test_comparison_decision_rejects_preview_fixtures(tmp_path: Path) -> None:
    from urban_design import decision_key
    import uuid

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-test-key-" + uuid.uuid4().hex
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _p: secret)

    store = ProjectStateStore(tmp_path / "scenarios.sqlite3")
    artifact_root = tmp_path / "scenario-artifacts"
    app = create_workspace_app(store=store, scenario_artifact_root=artifact_root, decision_key_path=key_path)
    client = TestClient(app)

    generated = client.post(
        "/api/v1/scenarios/fixtures",
        json={
            "fixture_id": "synthetic-preview-1",
            "width_m": 100,
            "height_m": 80,
            "seed": 50,
        },
    )
    assert generated.status_code == 201
    sids = [s["scenario_id"] for s in generated.json()["scenarios"]]

    # Attempt decision on fixtures
    res = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={
            "project_id": "fixture-only-project",
            "scenario_ids": sids,
            "accepted_scenario_id": sids[0],
            "acceptance_reason": "I want to accept this preview",
            "rejected_reasons": {sids[1]: "Not suitable", sids[2]: "Too dense"},
            "decision_key": secret,
            "actor_session_id": "session-1",
        },
    )
    assert res.status_code == 409
    assert "Formal proposals required" in res.json()["detail"]


def test_comparison_decision_accepts_formal_baseline_and_rejects_others(tmp_path: Path) -> None:
    from urban_design import decision_key
    import uuid

    key_path = tmp_path / "config" / "decision-key"
    secret = "fixture-test-key-" + uuid.uuid4().hex
    decision_key.initialize_decision_key(path=key_path, password_prompt=lambda _p: secret)

    store = ProjectStateStore(tmp_path / "scenarios.sqlite3")
    artifact_root = tmp_path / "scenario-artifacts"
    app = create_workspace_app(store=store, scenario_artifact_root=artifact_root, decision_key_path=key_path)
    client = TestClient(app)

    sids = _create_formal_scenarios(store, artifact_root, project_id="proj-formal-1")

    # Missing rejection reason
    bad_res = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={
            "project_id": "proj-formal-1",
            "scenario_ids": sids,
            "accepted_scenario_id": sids[0],
            "acceptance_reason": "Balanced FAR and open space ratio",
            "rejected_reasons": {sids[1]: "Excessive height"},  # missing sids[2]
            "decision_key": secret,
            "actor_session_id": "session-founder-1",
        },
    )
    assert bad_res.status_code == 422
    assert "explicit human rejection reason" in bad_res.json()["detail"]

    # Wrong decision key
    wrong_key_res = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={
            "project_id": "proj-formal-1",
            "scenario_ids": sids,
            "accepted_scenario_id": sids[0],
            "acceptance_reason": "Balanced FAR and open space ratio",
            "rejected_reasons": {sids[1]: "Excessive height", sids[2]: "Inadequate daylight"},
            "decision_key": "wrong-secret-key-12345",
            "actor_session_id": "session-founder-1",
        },
    )
    assert wrong_key_res.status_code == 403

    # Successful acceptance as baseline
    ok_res = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={
            "project_id": "proj-formal-1",
            "scenario_ids": sids,
            "accepted_scenario_id": sids[0],
            "acceptance_reason": "Selected as official project baseline: optimal FAR and open space.",
            "rejected_reasons": {
                sids[1]: "Excessive height exceeds 15m target.",
                sids[2]: "Inadequate open space ratio below 0.35 threshold.",
            },
            "decision_key": secret,
            "actor_session_id": "session-founder-1",
        },
    )
    assert ok_res.status_code == 201, ok_res.text
    data = ok_res.json()
    assert data["status"] == "ACCEPTED"
    assert data["baseline_scenario_id"] == sids[0]
    assert data["baseline_decision_id"].startswith("decision-")
    assert sids[1] in data["rejected_decisions"]
    assert sids[2] in data["rejected_decisions"]

    # Verify queryability: all scenarios are still returned and queryable
    scenarios_res = client.get("/api/v1/scenarios")
    assert scenarios_res.status_code == 200
    listed = {s["scenario_id"]: s for s in scenarios_res.json()["scenarios"]}
    assert listed[sids[0]]["is_baseline"] is True
    assert listed[sids[0]]["status"] == "accepted"
    assert listed[sids[1]]["status"] == "rejected"
    assert listed[sids[1]]["rejection_reason"] == "Excessive height exceeds 15m target."
    assert listed[sids[2]]["status"] == "rejected"
    assert listed[sids[2]]["rejection_reason"] == "Inadequate open space ratio below 0.35 threshold."

    # Cannot accept another baseline when baseline already chosen
    re_decision = client.post(
        "/api/v1/scenarios/comparison/decision",
        json={
            "project_id": "proj-formal-1",
            "scenario_ids": sids,
            "accepted_scenario_id": sids[1],
            "acceptance_reason": "Attempting second baseline",
            "rejected_reasons": {sids[0]: "Changed mind", sids[2]: "Inadequate"},
            "decision_key": secret,
            "actor_session_id": "session-founder-1",
        },
    )
    assert re_decision.status_code == 409
    assert "already been accepted" in re_decision.json()["detail"]

