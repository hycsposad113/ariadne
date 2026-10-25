"""Seven formal-draft snaps. Coordinates come back from the scenario routes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from shapely.geometry import box, mapping


KINDS = ("ENDPOINT", "NEAREST_POINT", "MIDPOINT", "INTERSECTION", "PERPENDICULAR", "QUARTER", "THREE_QUARTER")
POSITIVE = {
    "ENDPOINT": ((0.2, 0.2), (0.0, 0.0)),
    "NEAREST_POINT": ((3.0, 0.4), (3.0, 0.0)),
    "MIDPOINT": ((10.2, 10.0), (10.0, 10.0)),
    "INTERSECTION": ((4.2, 0.2), (4.0, 0.0)),
    "PERPENDICULAR": ((10.2, 12.2), (10.0, 12.0)),
    "QUARTER": ((10.2, 0.2), (10.0, 0.0)),
    "THREE_QUARTER": ((10.2, 20.2), (10.0, 20.0)),
}
NEGATIVE = {
    "ENDPOINT": (3.0, 0.2),
    "NEAREST_POINT": (5.0, 15.0),
    "MIDPOINT": (5.0, 15.0),
    "INTERSECTION": (2.0, 0.2),
    "PERPENDICULAR": (3.0, 0.2),
    "QUARTER": (5.0, 15.0),
    "THREE_QUARTER": (5.0, 15.0),
}


def _helpers():
    path = Path(__file__).with_name("test_formal_editor_authority.py")
    spec = importlib.util.spec_from_file_location("g4_formal_helpers_roads", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stages() -> dict:
    geometry = mapping(box(0, 0, 20, 50))
    floors = [
        {"id": f"b-rect-floor-{level}", "level": level, "floor_height_m": 3.5, "use": "residential", "geometry": geometry}
        for level in range(4)
    ]
    return {
        "massing": {"buildings": [{"id": "b-rect", "use": "residential", "height_m": 14.0, "floors": floors, "footprint": geometry}]},
        "skeleton": {"edges": [
            {"id": "poly", "from_node_id": "n0", "to_node_id": "n2", "level": 0, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0], [10, 30]]}},
            {"id": "spur", "from_node_id": "m", "to_node_id": "tail", "level": 0, "geometry": {"type": "LineString", "coordinates": [[12, 12], [16, 12]]}},
            {"id": "cross", "from_node_id": "c0", "to_node_id": "c1", "level": 0, "geometry": {"type": "LineString", "coordinates": [[4, -4], [4, 4]]}},
            {"id": "bridge", "from_node_id": "b0", "to_node_id": "b1", "level": 1, "geometry": {"type": "LineString", "coordinates": [[30, 0], [30, 20]]}},
        ]},
    }


def _draft(tmp_path: Path):
    helpers = _helpers()
    store, client, secret, _key_path, scenario_ids, _digest = helpers._world(tmp_path, stages=_stages())
    ancestor = store.current(scenario_ids[0])
    parameters = dict(ancestor.payload["parameters"])
    parameters.update({
        "syntax_result_ids": ["syntax-formal"],
        "accessibility_result_ids": ["access-formal"],
        "e1_result_ids": ["e1-formal"],
        "syntax_statuses": {"syntax-formal": "CURRENT"},
        "accessibility_statuses": {"access-formal": "CURRENT"},
        "e1_statuses": {"e1-formal": "CURRENT"},
    })
    helpers._human_patch(store, scenario_ids[0], {"parameters": parameters}, "Attach disposable analysis ids before acceptance")
    helpers._accept(client, secret, scenario_ids)
    opened = client.post(f"/api/v1/scenarios/{scenario_ids[0]}/formal-draft")
    assert opened.status_code == 201, opened.text
    body = opened.json()
    assert body["provenance"] == "FORMAL_DRAFT"
    return client, body


def _candidates(client, draft_id: str, graph_hash: str, point: tuple[float, float]):
    response = client.post(
        f"/api/v1/scenarios/{draft_id}/road-nodes/m/snap-candidates",
        json={"x_m": point[0], "y_m": point[1], "expected_revision": 0, "expected_graph_hash": graph_hash},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "FORMAL_DRAFT"
    assert body["acceptance_eligible"] is False
    return body["candidates"]


def test_formal_draft_has_positive_and_negative_snaps_for_each_kind(tmp_path: Path):
    client, opened = _draft(tmp_path)
    draft_id = opened["scenario_id"]
    graph = opened["editor"]["road_graph"]
    graph_hash = graph["graph_hash"]
    by_id = {node["node_id"]: node for node in graph["nodes"]}
    poly_edges = [edge for edge in graph["edges"] if edge["edge_id"].startswith("poly:")]
    length = 0.0
    for edge in poly_edges:
        start, end = by_id[edge["start_node_id"]], by_id[edge["end_node_id"]]
        length += abs(start["x_m"] - end["x_m"]) + abs(start["y_m"] - end["y_m"])
    assert length == 40.0
    assert not any(abs(node["x_m"] - 5) < 1e-6 and abs(node["y_m"] - 15) < 1e-6 for node in graph["nodes"])
    for kind in KINDS:
        cursor, expected = POSITIVE[kind]
        found = [item for item in _candidates(client, draft_id, graph_hash, cursor) if item["snap_kind"] == kind]
        assert found, kind
        assert (found[0]["x_m"], found[0]["y_m"]) == pytest.approx(expected)
        if kind in {"MIDPOINT", "QUARTER", "THREE_QUARTER"}:
            chain = [item for item in found if item["target_length_m"] == pytest.approx(40)]
            assert (chain[0]["x_m"], chain[0]["y_m"]) == pytest.approx(expected)
        missing = _candidates(client, draft_id, graph_hash, NEGATIVE[kind])
        assert not any(item["snap_kind"] == kind for item in missing), kind
        refused = client.post(
            f"/api/v1/scenarios/{draft_id}/road-nodes/m/move",
            json={
                "x_m": NEGATIVE[kind][0], "y_m": NEGATIVE[kind][1], "expected_revision": 0,
                "expected_graph_hash": graph_hash, "idempotency_key": f"negative-{kind}", "snap_kind": kind,
            },
        )
        assert refused.status_code == 409, refused.text
        assert "NOT_READY" in refused.text
    bridge = _candidates(client, draft_id, graph_hash, (30.0, 10.0))
    assert not any(abs(item["x_m"] - 30) < 1e-6 and abs(item["y_m"] - 10) < 1e-6 for item in bridge)
    centre = _candidates(client, draft_id, graph_hash, (5.0, 15.0))
    assert not any(abs(item["x_m"] - 5) < 1e-6 and abs(item["y_m"] - 15) < 1e-6 for item in centre)
    moved = client.post(
        f"/api/v1/scenarios/{draft_id}/road-nodes/m/move",
        json={
            "x_m": 10.2, "y_m": 10.0, "expected_revision": 0, "expected_graph_hash": graph_hash,
            "idempotency_key": "polyline-midpoint", "snap_kind": "MIDPOINT",
        },
    )
    assert moved.status_code == 201, moved.text
    body = moved.json()
    assert body["status"] == "FORMAL_DRAFT"
    assert body["acceptance_eligible"] is False
    assert (body["actual_x_m"], body["actual_y_m"]) == pytest.approx((10.0, 10.0))
    split = [edge for edge in body["edges"] if "poly:1" in edge["lineage_ids"] and edge["edge_id"] != "poly:1"]
    assert split
    assert all("poly:1" in edge["lineage_ids"] for edge in split)
    bridge_edge = next(edge for edge in body["edges"] if edge["edge_id"] == "bridge")
    assert bridge_edge["layer"] == 1
    assert {bridge_edge["start_node_id"], bridge_edge["end_node_id"]} == {"b0", "b1"}
    assert body["syntax_statuses"]["syntax-formal"] == "STALE"
    assert body["accessibility_statuses"]["access-formal"] == "STALE"
    assert body["e1_statuses"]["e1-formal"] == "STALE"
    again = client.post(
        f"/api/v1/scenarios/{draft_id}/road-nodes/m/move",
        json={
            "x_m": 10.2, "y_m": 10.0, "expected_revision": 0, "expected_graph_hash": graph_hash,
            "idempotency_key": "polyline-midpoint", "snap_kind": "MIDPOINT",
        },
    )
    assert again.status_code == 201, again.text
    assert again.json()["idempotent_replay"] is True
    assert again.json()["revision_id"] == body["revision_id"]
    changed = client.post(
        f"/api/v1/scenarios/{draft_id}/road-nodes/m/move",
        json={
            "x_m": 1.0, "y_m": 1.0, "expected_revision": 0, "expected_graph_hash": graph_hash,
            "idempotency_key": "polyline-midpoint", "snap_kind": "ENDPOINT",
        },
    )
    assert changed.status_code == 409, changed.text
    assert "idempotency key was reused" in changed.text
    reloaded = client.get(f"/api/v1/scenarios/{draft_id}")
    assert reloaded.status_code == 200, reloaded.text
    editor = reloaded.json()["editor"]
    assert editor["syntax_statuses"]["syntax-formal"] == "STALE"
    assert editor["accessibility_statuses"]["access-formal"] == "STALE"
    assert editor["e1_statuses"]["e1-formal"] == "STALE"
    assert editor["road_edit_revision_id"] == 1


def test_adding_a_floor_marks_e1_stale_and_leaves_the_road_graph(tmp_path: Path):
    client, opened = _draft(tmp_path)
    draft_id = opened["scenario_id"]
    before_hash = opened["editor"]["road_graph"]["graph_hash"]
    edited = client.post(
        f"/api/v1/scenarios/{draft_id}/edits",
        json={
            "building_id": "b-rect",
            "command": {"type": "add_floor", "new_floor_id": "b-rect-floor-4"},
            "expected_revision": 0,
            "idempotency_key": "height-only",
        },
    )
    assert edited.status_code == 201, edited.text
    reloaded = client.get(f"/api/v1/scenarios/{draft_id}")
    editor = reloaded.json()["editor"]
    assert editor["e1_statuses"]["e1-formal"] == "STALE"
    assert editor["syntax_statuses"]["syntax-formal"] == "CURRENT"
    assert editor["accessibility_statuses"]["access-formal"] == "CURRENT"
    assert editor["road_graph"]["graph_hash"] == before_hash
