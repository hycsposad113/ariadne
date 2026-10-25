from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sqlite3

from urban_design.week7.fixture_router import create_week7_router
from urban_design.week7.service import Week7Refusal, Week7Service, cache_key, idempotency_key, invalidation_plan
from tests.week7_support import seed_pair

pytest_plugins = ["tests.week7_support"]

WORKSPACE = "ws-w7"


def _mismatch_footprint() -> dict:
    return {
        "id": "mismatch-footprint",
        "kind": "footprint",
        "disposition": "EDITABLE",
        "geometry": {"type": "Polygon", "coordinates": [[[1.0, 1.0], [11.0, 1.0], [11.0, 11.0], [1.0, 11.0], [1.0, 1.0]]]},
        "provenance": "FIXTURE_ONLY",
    }


def test_same_revision_geometry_or_source_mismatch_keeps_previous_value(service: Week7Service) -> None:
    seed_pair(service)
    before = service.view(WORKSPACE)
    assert before["panels"]["dashboard"]["far"] == 2.2
    before_hash = before["head_hash"]
    before_features = before["map"]["features"]
    with pytest.raises(Week7Refusal) as caught:
        service.switch_scheme(
            WORKSPACE,
            project_id="rotterdam-m4h-pilot-project",
            scenario_id="B2",
            revision="rev-b2",
            source_hash="mismatch-source",
            results=[{"kind": "gfa_far", "value": 9.9, "unit": "ratio", "provenance": "FIXTURE_ONLY"}],
            features=[_mismatch_footprint()],
        )
    assert caught.value.code == "source_or_geometry_hash_mismatch"
    refused = service.view(WORKSPACE)
    assert refused["head_hash"] == before_hash
    assert refused["panels"]["dashboard"]["far"] == 2.2
    assert refused["freshness"] == "current"
    assert refused["map"]["features"] == before_features
    assert all(panel["far"] == 2.2 for panel in refused["panels"].values())
    updated = service.switch_scheme(
        WORKSPACE,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B2",
        revision="rev-b2",
        results=[{"kind": "gfa_far", "value": 2.4, "unit": "ratio", "provenance": "FIXTURE_ONLY"}],
    )
    assert updated["panels"]["dashboard"]["far"] == 2.4
    assert updated["map"]["features"] == before_features
    with pytest.raises(Week7Refusal) as source_caught:
        service.switch_scheme(
            WORKSPACE,
            project_id="rotterdam-m4h-pilot-project",
            scenario_id="B2",
            revision="rev-b2",
            source_hash="other-source",
            results=[{"kind": "gfa_far", "value": 9.9, "unit": "ratio", "provenance": "FIXTURE_ONLY"}],
        )
    assert source_caught.value.code == "source_or_geometry_hash_mismatch"
    after = service.view(WORKSPACE)
    assert after["panels"]["dashboard"]["far"] == 2.4
    assert after["map"]["features"] == before_features
    assert after["head_hash"] == updated["head_hash"]


def test_reload_keeps_one_revision_across_panels(service: Week7Service) -> None:
    seed_pair(service)
    service.close()
    reloaded = Week7Service(service.database)
    try:
        view = reloaded.view(WORKSPACE)
    finally:
        reloaded.close()
    revisions = {panel["revision"] for panel in view["panels"].values()}
    fars = {panel["far"] for panel in view["panels"].values()}
    evidence = {tuple(panel["evidence_ids"]) for panel in view["panels"].values()}
    assert revisions == {"rev-b2"}
    assert fars == {2.2}
    assert evidence == {("card-b2-sun",)}
    assert view["revision_label"] == "revision rev-b2"
    assert "B1" not in view["panels"]["ai"]["evidence_ids"][0]
    assert view["cards"][0]["evidence_id"] == "card-b2-sun"
    assert view["cards"][0]["revision"] == "rev-b2"
    assert view["cards"][0]["validation_status"] == "invalid"
    assert isinstance(view["shell"]["study_area_revision"], int)


def test_api_switch_and_direct_call_use_persisted_gate(service: Week7Service) -> None:
    app = FastAPI()
    app.include_router(create_week7_router(service.store))
    client = TestClient(app)
    switched = client.post(
        f"/api/v1/week7/workspaces/{WORKSPACE}/switch",
        json={
            "project_id": "rotterdam-m4h-pilot-project",
            "scenario_id": "B2",
            "revision": "rev-b2",
            "geometry_fault": "self-intersection",
            "results": [{"kind": "gfa_far", "value": 2.2, "unit": "ratio", "provenance": "FIXTURE_ONLY"}],
        },
    )
    assert switched.status_code == 200
    body = switched.json()
    assert {panel["revision"] for panel in body["panels"].values()} == {"rev-b2"}
    denied = client.post(
        f"/api/v1/week7/workspaces/{WORKSPACE}/controls/run_analysis",
        json={"allowed": True, "force": True},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["reason"] == "geometry_invalid"
    assert client.get(f"/api/v1/week7/workspaces/{WORKSPACE}/view").json()["panels"]["dashboard"]["far"] == 2.2


def test_authority_database_is_refused_before_any_write(tmp_path, monkeypatch) -> None:
    import hashlib
    from urban_design.store import ProjectStateStore
    from tests.week7_support import create_injected_authority_refusal_fixture
    from urban_design.week7 import service, fixture_router

    from urban_design.week7.fixture_router import create_week7_router
    from urban_design.week7.service import Week7Refusal, Week7Service

    authority = create_injected_authority_refusal_fixture(tmp_path / 'synthetic-authority.sqlite3')
    monkeypatch.setattr(service, 'AUTHORITY_DATABASE', authority)
    monkeypatch.setattr(fixture_router, 'AUTHORITY_DATABASE', authority)
    before_bytes = authority.read_bytes()
    before_hash = hashlib.sha256(before_bytes).hexdigest()

    with pytest.raises(Week7Refusal) as caught:
        Week7Service(authority)
    assert caught.value.code == "authority_database_write_refused"
    assert authority.read_bytes() == before_bytes
    assert hashlib.sha256(authority.read_bytes()).hexdigest() == before_hash

    with ProjectStateStore(authority, read_only=True) as readonly:
        app = FastAPI()
        app.include_router(create_week7_router(readonly))
        client = TestClient(app)
        refused_get = client.get("/api/v1/week7/workspaces/ws-w7/view")
        assert refused_get.status_code == 409
        assert refused_get.json()["detail"]["code"] == "authority_database_write_refused"

        refused_post = client.post(
            "/api/v1/week7/workspaces/ws-w7/switch",
            json={"project_id": "rotterdam-m4h-pilot-project", "scenario_id": "B2", "revision": "rev-b2"},
        )
        assert refused_post.status_code == 409
        assert refused_post.json()["detail"]["code"] == "authority_database_write_refused"

    assert authority.read_bytes() == before_bytes
    assert hashlib.sha256(authority.read_bytes()).hexdigest() == before_hash


def test_workspace_app_exposes_week7_on_a_database_copy(tmp_path) -> None:
    from urban_design.api import create_workspace_app
    from urban_design.store import ProjectStateStore
    from tests.week7_support import seed_project_database

    database = seed_project_database(tmp_path / "state.sqlite3")
    store = ProjectStateStore(database)
    try:
        app = create_workspace_app(store)
        client = TestClient(app)
        missing = client.get("/api/v1/week7/workspaces/missing-ws/view")
        assert missing.status_code == 409
        assert missing.json()["detail"]["code"] == "workspace_missing"

        found = client.get("/api/v1/week7/workspaces/fixture-workspace/view")
        assert found.status_code == 200
        payload = found.json()
        assert payload["workspace_id"] == "fixture-workspace"
        assert payload["scenario_id"] == "fixture-scenario-1"
        assert payload["human_status"] == "NOT_ACCEPTED"
        assert payload["run_status"] == "NOT_RUN"
        assert payload["evidence_status"] == "UNVERIFIED_OR_MISSING"
        assert payload["geometry_status"] == "HASH_VERIFIED"
        assert "dashboard" in payload["panels"]
    finally:
        store.close()


def test_cache_key_is_not_the_idempotency_key() -> None:
    cached = cache_key(inputs={"scenario": "B2"}, method="far", method_version="1", parameters={"storey_m": 3.5})
    idem = idempotency_key(actor="designer", action="rerun", expected_revision="rev-b2", logical_request="same")
    assert cached.startswith("cache:")
    assert idem.startswith("idem:")
    assert cached != idem
    assert cached != cache_key(inputs={"scenario": "B1"}, method="far", method_version="1", parameters={"storey_m": 3.5})


@pytest.mark.parametrize(
    ("change", "flags", "stale", "reuse"),
    [
        ("floor_height", {}, ["gfa_far", "height_limit", "shadow_environment"], ["network_path"]),
        ("footprint", {"entry_changed": False}, ["coverage_gfa", "collision_retention", "environment"], ["source_observation", "network_path"]),
        ("footprint", {"entry_changed": True}, ["coverage_gfa", "collision_retention", "environment", "network_path"], ["source_observation"]),
        ("road_access_entry", {}, ["graph", "accessibility", "syntax"], ["geometry_area", "shadow"]),
        ("use", {"use_is_destination": False}, ["use_ratio", "energy_assumption"], ["geometry_area", "shadow", "accessibility"]),
        ("use", {"use_is_destination": True}, ["use_ratio", "energy_assumption", "accessibility"], ["geometry_area", "shadow"]),
        ("weather_period_recipe", {}, ["environment_result", "environment_comparison"], ["morphology", "raw_network"]),
        ("legend_camera", {}, ["figure_output"], ["raw_computed"]),
        ("hard_constraint", {}, ["scheme_validation", "acceptance_gate"], ["prior_evidence"]),
    ],
)
def test_invalidation_rows_mark_only_the_dependent_results(service, change, flags, stale, reuse) -> None:
    service.switch_scheme(
        WORKSPACE,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B2",
        revision="rev-b2",
        results=[{"kind": "gfa_far", "value": 2.2, "unit": "ratio"}],
    )
    service.seed_result_kinds(WORKSPACE, list(dict.fromkeys([*stale, *reuse])))
    applied = service.apply_change(WORKSPACE, change, **flags)
    assert invalidation_plan(change, **flags)["stale"] == stale
    for kind in stale:
        assert applied["observed"][kind] == "stale"
    for kind in reuse:
        assert applied["observed"][kind] == "current"
    view = service.view(WORKSPACE)
    assert view["freshness"] == "stale"
    assert "STALE" in view["freshness_text"]


def _on_default_canvas(ring: list[list[float]]) -> None:
    """Match Viewport2D's initial pan/zoom and the EPSG:28992 origin in geoTransform.ts."""
    for easting, northing in ring:
        px = 420 + (easting - 89100.0) * 0.9
        py = 380 - (northing - 435900.0) * 0.9
        assert 0 <= px <= 1440
        assert 0 <= py <= 1100


def test_reopen_returns_only_the_current_head_footprint(service: Week7Service) -> None:
    seed_pair(service)
    service.close()
    reloaded = Week7Service(service.database)
    try:
        view = reloaded.view(WORKSPACE)
        assert view["map"]["revision"] == "rev-b2"
        assert view["shell"]["authority_state"] == "READY"
        assert view["shell"]["workspace_revision"] == "rev-b2"
        features = view["map"]["features"]
        assert features
        assert {item["scenario_id"] for item in features} == {"B2"}
        assert {item["revision"] for item in features} == {"rev-b2"}
        assert {item["provenance"] for item in features} == {"FIXTURE_ONLY"}
        b2_ring = features[0]["geometry"]["coordinates"][0]
        assert b2_ring[0] == b2_ring[-1]
        _on_default_canvas(b2_ring)
        study_area_id = view["shell"]["study_area_id"]
        assert study_area_id
        with sqlite3.connect(f"file:{service.database}?mode=ro", uri=True) as con:
            row = con.execute(
                "SELECT 1 FROM state_heads WHERE entity_type = 'StudyArea' AND entity_id = ?",
                (study_area_id,),
            ).fetchone()
        assert row is not None
        switched = reloaded.switch_scheme(
            WORKSPACE,
            project_id="rotterdam-m4h-pilot-project",
            scenario_id="B1",
            revision="rev-b1",
        )
        b1_features = switched["map"]["features"]
        assert switched["map"]["revision"] == "rev-b1"
        assert {item["id"] for item in b1_features} == {"B1-rev-b1-footprint"}
        assert {item["scenario_id"] for item in b1_features} == {"B1"}
        b1_ring = b1_features[0]["geometry"]["coordinates"][0]
        assert b1_ring != b2_ring
        _on_default_canvas(b1_ring)
        again = reloaded.view(WORKSPACE)
        assert {item["revision"] for item in again["map"]["features"]} == {"rev-b1"}
        assert again["panels"]["dashboard"]["far"] == 1.1
    finally:
        reloaded.close()


def test_explicit_feature_cannot_claim_another_revision(service: Week7Service) -> None:
    ring = [[89100.0, 435900.0], [89140.0, 435900.0], [89140.0, 435940.0], [89100.0, 435940.0], [89100.0, 435900.0]]
    view = service.switch_scheme(
        WORKSPACE,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B2",
        revision="rev-b2",
        features=[
            {
                "id": "custom-b2",
                "scenario_id": "B0",
                "revision": "rev-b0",
                "kind": "footprint",
                "disposition": "PRESERVE",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "provenance": "FIXTURE_ONLY",
            }
        ],
    )
    stored = view["map"]["features"]
    assert [item["id"] for item in stored] == ["custom-b2"]
    assert stored[0]["scenario_id"] == "B2"
    assert stored[0]["revision"] == "rev-b2"
    assert stored[0]["geometry"]["coordinates"][0] == ring
    with pytest.raises(Week7Refusal) as caught:
        service.switch_scheme(
            "ws-refused",
            project_id="rotterdam-m4h-pilot-project",
            scenario_id="B2",
            revision="rev-b2",
            features=[
                {
                    "id": "bad",
                    "disposition": "EDITABLE",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "provenance": "LIVE_ACCEPTED",
                }
            ],
        )
    assert caught.value.code == "provenance_upgrade_refused"
    with pytest.raises(Week7Refusal) as missing:
        service.view("ws-refused")
    assert missing.value.code == "workspace_missing"


def test_invalid_geometry_still_persists_its_own_footprint(service: Week7Service) -> None:
    view = service.switch_scheme(
        WORKSPACE,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B2",
        revision="rev-b2",
        geometry_fault="self-intersection",
    )
    assert view["geometry_valid"] is False
    assert view["map"]["revision"] == "rev-b2"
    assert view["map"]["features"][0]["id"] == "B2-rev-b2-footprint"
    assert view["shell"]["authority_state"] == "READY"


def test_expanded_card_exposes_source_formula_unit_version_and_limits(service) -> None:
    seed_pair(service)
    card = service.expand_card("card-b2-sun")
    assert card["source"] == "fixture sun B2"
    assert card["formula"] == "stored"
    assert card["unit"] == "hour"
    assert card["version"] == "rev-b2"
    assert card["limits"] == "FIXTURE_ONLY"
    assert card["revision"] == "rev-b2"
