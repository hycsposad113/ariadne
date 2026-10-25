import pytest

from urban_design.editing.roads import RoadNode, RoadEdge, RoadGraph, RoadEditError, move_road_node, road_snap_candidates


def fixture(*, level=0, vertical=False, locked=False):
    nodes = [RoadNode('a', 0, 0, level), RoadNode('b', 8, 0, level),
             RoadNode('m', 3, 4, level), RoadNode('tail', 3, 9, level)]
    edges = [RoadEdge('ab', 'a', 'b', level, locked=locked), RoadEdge('spur', 'm', 'tail', level)]
    if vertical:
        nodes += [RoadNode('c', 4, -4, level), RoadNode('d', 4, 4, level)]
        edges += [RoadEdge('cd', 'c', 'd', level)]
    return RoadGraph(tuple(nodes), tuple(edges))


@pytest.mark.parametrize('kind,position,expected', [
    ('ENDPOINT', (.1,.1), (0,0)), ('NEAREST_POINT', (1.2,.1), (1.2,0)),
    ('MIDPOINT', (4.1,.1), (4,0)), ('INTERSECTION', (4.1,.1), (4,0)),
    ('PERPENDICULAR', (3.1,.1), (3,0)), ('QUARTER', (2.1,.1), (2,0)),
    ('THREE_QUARTER', (6.1,.1), (6,0)),
])
def test_seven_known_answer_candidates_and_edits(kind, position, expected):
    graph = fixture(vertical=kind == 'INTERSECTION')
    candidates = road_snap_candidates(graph, 'm', x_m=position[0], y_m=position[1], snap_tolerance_m=.3)
    selected = [c for c in candidates if c.snap_kind == kind]
    assert selected
    assert (selected[0].x_m, selected[0].y_m) == pytest.approx(expected)
    result = move_road_node(graph, 'm', x_m=position[0], y_m=position[1], snap_tolerance_m=.3, snap_kind=kind)
    assert (result.actual_x_m,result.actual_y_m) == pytest.approx(expected)
    assert result.graph.connected_component_count == 1
    if kind == 'INTERSECTION':
        assert {e.edge_id for e in result.graph.edges} == {'ab:1','ab:2','cd:1','cd:2','spur'}
        assert all('m' in (e.start_node_id,e.end_node_id) for e in result.graph.edges)
    if kind in ('MIDPOINT','QUARTER','THREE_QUARTER'):
        assert 'along-length fraction' in selected[0].position_semantics
        assert selected[0].target_length_m == 8
        assert selected[0].distance_along_m == expected[0]
        assert selected[0].target_fraction == expected[0] / 8


def test_connected_polyline_fractions_are_not_the_bbox_centre():
    nodes = (
        RoadNode('n0', 0, 0, 0), RoadNode('n1', 10, 0, 0), RoadNode('n2', 10, 30, 0),
        RoadNode('m', 12, 12, 0), RoadNode('tail', 16, 12, 0),
    )
    edges = (
        RoadEdge('poly:0', 'n0', 'n1', 0, lineage_ids=('poly', 'poly:0')),
        RoadEdge('poly:1', 'n1', 'n2', 0, lineage_ids=('poly', 'poly:1')),
        RoadEdge('spur', 'm', 'tail', 0),
    )
    graph = RoadGraph(nodes, edges)
    wide = road_snap_candidates(graph, 'm', x_m=5, y_m=15, snap_tolerance_m=30)
    assert not any(abs(item.x_m - 5) < 1e-6 and abs(item.y_m - 15) < 1e-6 for item in wide)
    expected = {'MIDPOINT': (10, 10), 'QUARTER': (10, 0), 'THREE_QUARTER': (10, 20)}
    cursors = {'MIDPOINT': (10.2, 10), 'QUARTER': (10.2, 0.2), 'THREE_QUARTER': (10.2, 20.2)}
    for kind, point in expected.items():
        found = [item for item in road_snap_candidates(graph, 'm', x_m=cursors[kind][0], y_m=cursors[kind][1], snap_tolerance_m=1) if item.snap_kind == kind and item.target_length_m == pytest.approx(40)]
        assert len(found) == 1
        assert (found[0].x_m, found[0].y_m) == pytest.approx(point)
        assert found[0].target_length_m == pytest.approx(40)


def test_unknown_level_never_guesses_connection_and_noop_never_stales():
    graph = fixture(level=None)
    assert road_snap_candidates(graph,'m',x_m=4,y_m=0,snap_tolerance_m=1) == ()
    result = move_road_node(graph,'m',x_m=3,y_m=4,snap_tolerance_m=.1,syntax_result_ids=('s',))
    assert result.graph_hash == graph.graph_hash
    assert result.stale_syntax_result_ids == ()
    moved = move_road_node(graph,'m',x_m=4,y_m=0,snap_tolerance_m=.1)
    assert moved.graph.connected_component_count == 2
    assert len(moved.graph.edges) == 2


def test_cross_level_intersection_remains_disconnected():
    graph = fixture()
    graph = RoadGraph(graph.nodes+(RoadNode('c',4,-4,1),RoadNode('d',4,4,1)),
                      graph.edges+(RoadEdge('bridge','c','d',1),))
    result = move_road_node(graph,'m',x_m=4,y_m=.1,snap_tolerance_m=.3,snap_kind='MIDPOINT')
    assert len(result.graph.edges) == 4
    assert result.graph.connected_component_count == 2


def test_duplicate_edges_and_duplicate_created_by_endpoint_merge_rejected():
    with pytest.raises(RoadEditError,match='duplicate'):
        RoadGraph((RoadNode('a',0,0),RoadNode('b',8,0)),(RoadEdge('x','a','b'),RoadEdge('y','b','a')))
    graph = fixture()
    graph = RoadGraph(graph.nodes,graph.edges+(RoadEdge('at','a','tail',0),))
    with pytest.raises(RoadEditError,match='duplicate'):
        move_road_node(graph,'m',x_m=0,y_m=0,snap_tolerance_m=.1,snap_kind='ENDPOINT')


def test_perpendicular_outside_segment_is_not_clamped():
    graph = fixture()
    graph = RoadGraph(tuple(RoadNode(n.node_id, -2 if n.node_id == 'm' else n.x_m,n.y_m,n.layer) for n in graph.nodes),graph.edges)
    candidates = road_snap_candidates(graph,'m',x_m=0,y_m=0,snap_tolerance_m=10)
    assert not any(c.snap_kind == 'PERPENDICULAR' for c in candidates)


def test_locked_crossing_cannot_be_changed_by_another_target():
    graph = fixture(vertical=True,locked=True)
    with pytest.raises(RoadEditError,match='locked'):
        move_road_node(graph,'m',x_m=4,y_m=0,snap_tolerance_m=.1,snap_kind='NEAREST_POINT',target_id='cd')


def test_explicit_unavailable_snap_is_not_ready_and_locked_preview_rejected():
    graph = fixture(level=None)
    with pytest.raises(RoadEditError, match='NOT_READY'):
        move_road_node(graph,'m',x_m=4,y_m=0,snap_tolerance_m=.1,snap_kind='MIDPOINT')
    graph = fixture()
    graph = RoadGraph(graph.nodes,tuple(RoadEdge(e.edge_id,e.start_node_id,e.end_node_id,e.layer,locked=e.edge_id == 'spur') for e in graph.edges))
    with pytest.raises(RoadEditError,match='locked'):
        road_snap_candidates(graph,'m',x_m=4,y_m=0,snap_tolerance_m=.1)


def test_candidate_order_and_graph_hash_do_not_depend_on_input_order():
    graph = fixture(vertical=True)
    reversed_graph = RoadGraph(tuple(reversed(graph.nodes)),tuple(reversed(graph.edges)))
    kwargs = dict(x_m=4,y_m=0,snap_tolerance_m=10)
    assert road_snap_candidates(graph,'m',**kwargs) == road_snap_candidates(reversed_graph,'m',**kwargs)
    assert move_road_node(graph,'m',snap_kind='INTERSECTION',**kwargs).graph_hash == move_road_node(reversed_graph,'m',snap_kind='INTERSECTION',**kwargs).graph_hash


def test_ambiguous_coincident_endpoints_rejected():
    graph = fixture()
    graph = RoadGraph(graph.nodes+(RoadNode('other',0,0,0),RoadNode('end',-4,0,0)),graph.edges+(RoadEdge('other-road','other','end',0),))
    with pytest.raises(RoadEditError,match='ambiguous'):
        move_road_node(graph,'m',x_m=0,y_m=0,snap_tolerance_m=.1,snap_kind='ENDPOINT')


def test_access_refs_preserved_on_split_merge_and_in_hash():
    from dataclasses import replace
    graph = fixture()
    with_refs = RoadGraph(graph.nodes,tuple(replace(e,access_refs=('pedestrian-policy-v1',)) for e in graph.edges))
    assert with_refs.graph_hash != graph.graph_hash
    split = move_road_node(with_refs,'m',x_m=4,y_m=0,snap_tolerance_m=.1,snap_kind='MIDPOINT')
    assert all(e.access_refs == ('pedestrian-policy-v1',) for e in split.graph.edges)
    merged = move_road_node(with_refs,'m',x_m=0,y_m=0,snap_tolerance_m=.1,snap_kind='ENDPOINT')
    assert all(e.access_refs == ('pedestrian-policy-v1',) for e in merged.graph.edges)
    with pytest.raises(RoadEditError,match='access refs'):
        replace(graph.edges[0],access_refs=['not-a-tuple'])
