from __future__ import annotations

from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.editing.roads import RoadEdge, RoadGraph, RoadNode
from urban_design.store import ProjectStateStore


def _scenario(tmp_path):
    store = ProjectStateStore(tmp_path / "edit-api.sqlite3")
    client = TestClient(create_workspace_app(store=store, scenario_artifact_root=tmp_path / "artifacts"))
    response = client.post(
        "/api/v1/scenarios/fixtures",
        json={
            "fixture_id": "synthetic-editing-v1",
            "width_m": 100,
            "height_m": 80,
            "seed": 61,
            "road_width_m": 6,
            "first_floor_height_m": 3,
            "standard_floor_height_m": 3,
            "strategy_floor_count": 4,
        },
    )
    assert response.status_code == 201, response.text
    return client, store, response.json()["scenarios"][0]["scenario_id"]


def test_massing_edit_persists_draft_history_idempotency_and_pointer_undo_redo(tmp_path):
    client, store, scenario_id = _scenario(tmp_path)
    detail = client.get(f"/api/v1/scenarios/{scenario_id}").json()
    building = next(item for item in detail["geometry"]["features"] if item["properties"]["feature_kind"] == "building")
    building_id = building["id"]
    command = {
        "building_id": building_id,
        "command": {"type": "add_floor", "new_floor_id": "fixture-building-floor-5"},
        "expected_revision": 0,
        "idempotency_key": "edit-add-floor-1",
    }

    edited = client.post(f"/api/v1/scenarios/{scenario_id}/edits", json=command)
    assert edited.status_code == 201, edited.text
    revision = edited.json()
    assert revision["status"] == "DRAFT"
    assert revision["revision_id"] == 1
    assert revision["before_geometry_hash"] != revision["after_geometry_hash"]
    assert revision["validation"]["acceptance_eligible"] is False
    assert store.current(scenario_id).payload["status"] == "draft"

    replay = client.post(f"/api/v1/scenarios/{scenario_id}/edits", json=command)
    assert replay.status_code == 200
    assert replay.json()["revision_id"] == 1
    assert replay.json()["idempotent_replay"] is True

    undone = client.post(
        f"/api/v1/scenarios/{scenario_id}/edits/undo",
        json={"expected_revision": 1},
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["active_revision_id"] == 0
    assert undone.json()["revision_count"] == 1

    redone = client.post(
        f"/api/v1/scenarios/{scenario_id}/edits/redo",
        json={"expected_revision": 0, "revision_id": 1},
    )
    assert redone.status_code == 200, redone.text
    assert redone.json()["active_revision_id"] == 1
    assert redone.json()["revision_count"] == 1
    assert store.list_current("HumanDecision") == []


def test_road_node_edit_splits_edge_preserves_precision_and_marks_syntax_stale(tmp_path):
    client, store, scenario_id = _scenario(tmp_path)
    record = store.current(scenario_id)
    payload = dict(record.payload)
    parameters = dict(payload["parameters"])
    parameters["syntax_result_ids"] = ["syntax-800m-fixture"]
    parameters["syntax_statuses"] = {"syntax-800m-fixture": "CURRENT"}
    payload["parameters"] = parameters
    store.update(
        scenario_id,
        payload,
        expected_revision=record.revision,
        replace=True,
        actor="test-harness",
        action="SeedSyntaxDependency",
        reason="Attach a synthetic server-owned Syntax dependency for the route test",
    )
    record = store.current(scenario_id)
    graph = record.payload["parameters"]["road_graph"]
    # The lower end of the grid's vertical centerline is moved onto the
    # horizontal centerline, forcing an at-grade split of that edge.
    moving = next(
        node for node in graph["nodes"]
        if node["x_m"] == 90050 and node["y_m"] == 436000 and node["layer"] == 0
    )

    spoofed_response = client.post(
        f"/api/v1/scenarios/{scenario_id}/road-nodes/{moving['node_id']}/move",
        json={
            "x_m": 90050.123456,
            "y_m": 436040.2,
            "expected_revision": 0,
            "idempotency_key": "road-node-move-spoofed",
            "syntax_result_ids": ["untrusted-client-result"],
        },
    )
    assert spoofed_response.status_code == 422

    response = client.post(
        f"/api/v1/scenarios/{scenario_id}/road-nodes/{moving['node_id']}/move",
        json={
            "x_m": 90050.123456,
            "y_m": 436040.2,
            "expected_revision": 0,
            "idempotency_key": "road-node-move-1",
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["snap_tolerance_m"] == 1.0
    assert result["snap_kind"] == "NEAREST_POINT"
    assert result["snapped_to_edge_id"] is not None
    assert result["actual_x_m"] == 90050.123456
    assert result["actual_y_m"] == 436040
    assert result["graph_hash_before"] != result["graph_hash_after"]
    assert result["stale_syntax_result_ids"] == ["syntax-800m-fixture"]
    assert result["syntax_statuses"] == {"syntax-800m-fixture": "STALE"}
    assert result["validation"]["status"] == "PASS"
    assert result["validation"]["valid"] is True
    assert len([edge for edge in result["edges"] if edge["edge_id"].startswith(result["snapped_to_edge_id"] + ":")]) == 2


def test_road_node_edit_refuses_locked_road_on_the_server(tmp_path):
    client, store, scenario_id = _scenario(tmp_path)
    record = store.current(scenario_id)
    payload = dict(record.payload)
    parameters = dict(payload["parameters"])
    graph_payload = dict(parameters["road_graph"])
    edges = [dict(edge) for edge in graph_payload["edges"]]
    edges[0]["locked"] = True
    graph_payload["edges"] = edges
    graph = RoadGraph(
        nodes=tuple(RoadNode(**{**item, "lineage_ids": tuple(item.get("lineage_ids", []))}) for item in graph_payload["nodes"]),
        edges=tuple(RoadEdge(**{**item, "lineage_ids": tuple(item.get("lineage_ids", []))}) for item in edges),
    )
    graph_payload["graph_hash"] = graph.graph_hash
    parameters["road_graph"] = graph_payload
    payload["parameters"] = parameters
    store.update(
        scenario_id,
        payload,
        expected_revision=record.revision,
        replace=True,
        actor="test-harness",
        action="SeedLockedRoad",
        reason="Attach a locked road to the synthetic scenario for the route test",
    )
    locked_node_id = edges[0]["start_node_id"]
    before = store.current(scenario_id)

    response = client.post(
        f"/api/v1/scenarios/{scenario_id}/road-nodes/{locked_node_id}/move",
        json={
            "x_m": graph.node(locked_node_id).x_m + 2,
            "y_m": graph.node(locked_node_id).y_m + 2,
            "expected_revision": 0,
            "idempotency_key": "locked-road-node-move",
        },
    )

    assert response.status_code == 409
    assert "locked" in response.json()["detail"]
    assert store.current(scenario_id).revision == before.revision


def test_dashboard_recomputes_site_metrics_and_revision_ids_across_buildings(tmp_path):
    client, _store, scenario_id = _scenario(tmp_path)
    detail = client.get(f"/api/v1/scenarios/{scenario_id}").json()
    buildings = [
        feature for feature in detail["geometry"]["features"]
        if feature["properties"]["feature_kind"] == "building"
    ]
    assert len(buildings) >= 2
    first, second = buildings[:2]
    ring = first["geometry"]["coordinates"][0]
    first_area = abs(sum(
        ring[index][0] * ring[(index + 1) % (len(ring) - 1)][1]
        - ring[(index + 1) % (len(ring) - 1)][0] * ring[index][1]
        for index in range(len(ring) - 1)
    )) / 2
    baseline_far = detail["metrics"]["far"]["value"]

    one = client.post(
        f"/api/v1/scenarios/{scenario_id}/edits",
        json={"building_id": first["id"], "command": {"type": "add_floor", "new_floor_id": "first-extra-floor"}, "expected_revision": 0, "idempotency_key": "first-building-edit"},
    )
    assert one.status_code == 201, one.text
    assert one.json()["dashboard"]["scenario_metrics"]["far"]["value"] == baseline_far + first_area / 8000

    two = client.post(
        f"/api/v1/scenarios/{scenario_id}/edits",
        json={"building_id": second["id"], "command": {"type": "add_floor", "new_floor_id": "second-extra-floor"}, "expected_revision": 1, "idempotency_key": "second-building-edit"},
    )
    assert two.status_code == 201, two.text
    assert two.json()["revision_id"] == 2
    assert two.json()["dashboard"]["scenario_metrics"]["far"]["value"] > baseline_far

    undone = client.post(f"/api/v1/scenarios/{scenario_id}/edits/undo", json={"expected_revision": 2})
    assert undone.status_code == 200, undone.text
    assert undone.json()["active_revision_id"] == 1
    undone_again = client.post(f"/api/v1/scenarios/{scenario_id}/edits/undo", json={"expected_revision": 1})
    assert undone_again.status_code == 200, undone_again.text
    assert undone_again.json()["active_revision_id"] == 0
