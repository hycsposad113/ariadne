from shapely.geometry import LineString, Polygon
from urban_design.generation.fabric_network_finish import visible_route


def test_visible_route_keeps_exact_target_and_footprint_clearance():
    obstacle = Polygon([(4, -1), (6, -1), (6, 1), (4, 1)])
    route = visible_route((0, 0), (10, 0), obstacle, width=2)
    assert route is not None
    assert tuple(route.coords[0]) == (0, 0)
    assert tuple(route.coords[-1]) == (10, 0)
    assert route.buffer(1, cap_style=2, join_style=2).intersection(obstacle).area < .001
    assert route.length > 10


def test_visible_route_refuses_target_inside_footprint():
    obstacle = Polygon([(4, -1), (6, -1), (6, 1), (4, 1)])
    assert visible_route((0, 0), (5, 0), obstacle, width=2) is None


def test_visible_route_preserves_straight_alignment_when_clear():
    empty = Polygon()
    assert visible_route((0, 0), (10, 0), empty).equals(LineString([(0, 0), (10, 0)]))


def test_sub_epsilon_syntax_support_has_null_delta_without_zero_division():
    from urban_design.fabric_syntax import positive_support_diff
    from urban_design.scenario_syntax import segment_diff
    import pytest
    row = {'id': 'tiny', 'coordinates': [(0, 0), (0.0000001, 0)], 'nain': 1., 'nach': 2.}
    # merge policy v2: segment_diff itself no longer divides by zero for unsupported micro rows
    raw = segment_diff([], [row])
    assert raw[0]['before'] is None and raw[0]['delta'] is None
    result = positive_support_diff([], [row])
    assert result[0]['before'] is None and result[0]['delta'] is None
    assert result[0]['after'] == {'nain': 1., 'nach': 2.}


def test_motor_label_replay_rejects_geometry_and_layer_changes():
    import sys
    from pathlib import Path
    import copy
    import pytest
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from relabel_net1_motor_checkpoint import label_map
    old = [{'type':'Feature','id':'old','geometry':{'type':'LineString','coordinates':[[0,0],[10,0]]},'properties':{'layer':0}}]
    new = copy.deepcopy(old);new[0]['id']='new'
    assert label_map(old,new)=={'old':'new'}
    new[0]['properties']['layer']=1
    with pytest.raises(ValueError):label_map(old,new)
    new[0]['properties']['layer']=0;new[0]['geometry']['coordinates'][1][0]=11
    with pytest.raises(ValueError):label_map(old,new)
