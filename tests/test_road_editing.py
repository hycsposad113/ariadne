from __future__ import annotations

import pytest

from urban_design.editing.roads import (
    RoadEditError,
    RoadEdge,
    RoadGraph,
    RoadNode,
    move_road_node,
)


def _crossing_graph(*, cross_layer: int = 0, cross_bridge: bool = False) -> RoadGraph:
    return RoadGraph(
        nodes=(
            RoadNode("west", -10, 0, lineage_ids=("west-source",), layer=0),
            RoadNode("east", 10, 0, layer=0),
            RoadNode("moving", 0, 10, lineage_ids=("moving-source",), layer=0),
            RoadNode("tail", 0, 20, layer=0),
            RoadNode("north", 0, 20, layer=cross_layer, bridge=cross_bridge),
            RoadNode("south", 0, -10, layer=cross_layer, bridge=cross_bridge),
        ),
        edges=(
            RoadEdge("horizontal", "west", "east", layer=0),
            RoadEdge("vertical", "south", "north", layer=cross_layer, bridge=cross_bridge),
            RoadEdge("moving-spur", "moving", "tail", layer=0),
        ),
    )


def test_at_grade_node_snaps_to_segment_splits_edge_and_marks_syntax_stale():
    source = _crossing_graph()
    result = move_road_node(source, "moving", x_m=0.25, y_m=0.2, snap_tolerance_m=1.0, syntax_result_ids=("syntax-1",))

    assert result.snapped_to_edge_id == "horizontal"
    assert result.graph.node("moving").x_m == pytest.approx(0.25)
    assert result.graph.node("moving").y_m == pytest.approx(0)
    assert {edge.edge_id for edge in result.graph.edges} == {"horizontal:1", "horizontal:2", "vertical", "moving-spur"}
    split = [edge for edge in result.graph.edges if edge.edge_id.startswith("horizontal:")]
    assert all(edge.lineage_ids == ("horizontal",) for edge in split)
    assert result.graph.connected_component_count == 2
    assert result.stale_syntax_result_ids == ("syntax-1",)
    assert source.graph_hash != result.graph.graph_hash


def test_node_snaps_to_compatible_endpoint_with_ground_metre_tolerance():
    result = move_road_node(_crossing_graph(), "moving", x_m=-10.1, y_m=0.1, snap_tolerance_m=0.5)

    assert result.snapped_to_node_id == "west"
    assert result.snapped_to_edge_id is None
    assert (result.actual_x_m, result.actual_y_m) == (-10.0, 0.0)
    assert "moving" not in {node.node_id for node in result.graph.nodes}
    assert result.graph.node("west").lineage_ids == ("moving-source", "west-source")
    assert any(edge.start_node_id == "west" and edge.end_node_id == "tail" for edge in result.graph.edges)


def test_different_layer_bridge_does_not_snap_to_or_connect_at_grade():
    source = RoadGraph(
        nodes=(
            RoadNode("moving", 0, 10, layer=0), RoadNode("tail", 0, 20, layer=0),
            RoadNode("north", 0, 10, layer=1, bridge=True),
            RoadNode("south", 0, -10, layer=1, bridge=True),
        ),
        edges=(
            RoadEdge("moving-spur", "moving", "tail", layer=0),
            RoadEdge("bridge", "south", "north", layer=1, bridge=True),
        ),
    )
    result = move_road_node(source, "moving", x_m=0.25, y_m=0.2, snap_tolerance_m=1.0)

    assert result.snapped_to_edge_id is None
    assert result.graph.node("moving").x_m == pytest.approx(0.25)
    assert result.graph.node("moving").y_m == pytest.approx(0.2)
    assert {edge.edge_id for edge in result.graph.edges} == {"bridge", "moving-spur"}
    assert result.graph.connected_component_count == 2


def test_locked_incident_road_and_zero_length_result_are_rejected_without_mutation():
    locked = RoadGraph(
        nodes=(RoadNode("a", 0, 0, layer=0), RoadNode("b", 10, 0, layer=0)),
        edges=(RoadEdge("locked-road", "a", "b", locked=True, layer=0),),
    )
    with pytest.raises(RoadEditError, match="locked"):
        move_road_node(locked, "a", x_m=1, y_m=1, snap_tolerance_m=0.5)
    assert locked.node("a").x_m == 0

    short = RoadGraph(
        nodes=(RoadNode("c", 0, 0, layer=0), RoadNode("d", 1, 0, layer=0)),
        edges=(RoadEdge("short", "c", "d", layer=0),),
    )
    with pytest.raises(RoadEditError, match="zero-length"):
        move_road_node(short, "c", x_m=1, y_m=0, snap_tolerance_m=0.1)
    assert short.node("c").x_m == 0


def test_invalid_snap_tolerance_is_rejected():
    graph = _crossing_graph()
    with pytest.raises(RoadEditError, match="snap tolerance"):
        move_road_node(graph, "moving", x_m=0, y_m=0, snap_tolerance_m=-1)


def test_edge_crossing_without_shared_nodes_is_not_connected():
    graph = _crossing_graph()
    assert graph.connected_component_count == 3
