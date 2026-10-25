"""Building-led access geometry, pruning and original-network budgets."""
import math
from types import SimpleNamespace as NS
from shapely import affinity
from shapely.geometry import LineString, box, mapping, shape
from urban_design.generation.road_access import (
    aligned_access_paths, prune_access_lanes, road_surface, footprint_access_distance,
)


def edge(line, width=6):
    return NS(geometry=NS(model_dump=lambda: mapping(line)), width_m=width)


def test_shortest_mid_edge_attachment_and_grid_alignment():
    angle=15
    rotate=lambda g: affinity.rotate(g,angle,origin=(0,0))
    base=edge(rotate(LineString([(0,0),(0,200)])))
    building=rotate(box(100,80,120,100))
    options=aligned_access_paths([building],[base],angle=angle,
                                site=rotate(box(-50,-50,250,250)),obstacles=box(1000,1000,1010,1010))
    assert options
    lane=affinity.rotate(options[0],-angle,origin=(0,0))
    # True mid-edge attachment, rather than a trip from either road endpoint.
    assert abs(lane.coords[0][0])<1e-7
    assert 70<lane.coords[0][1]<110
    assert lane.length<70
    assert len(lane.coords)<=3
    for a,b in zip(lane.coords,lane.coords[1:]):
        assert min(abs(a[0]-b[0]),abs(a[1]-b[1]))<1e-7
    assert footprint_access_distance(building,road_surface([base,edge(options[0],4.5)]))<=40


def test_obstacles_and_no_lane_for_accessible_building():
    base=edge(LineString([(0,0),(0,200)]))
    assert not aligned_access_paths([box(20,80,40,100)],[base],angle=0,
                                   site=box(-50,-50,250,250),obstacles=box(1000,1000,1010,1010))
    barrier=box(40,-50,60,250)
    assert not aligned_access_paths([box(100,80,120,100)],[base],angle=0,
                                   site=box(-50,-50,250,250),obstacles=barrier)


def test_spur_pruned_when_served_building_dropped():
    base=edge(LineString([(0,0),(0,200)]))
    lane=LineString([(0,90),(70,90)])
    remote=box(100,80,120,100)
    nearby=box(20,20,40,40)
    assert prune_access_lanes([base],[lane],[remote,nearby])==[lane]
    assert prune_access_lanes([base],[lane],[nearby])==[]
    assert prune_access_lanes([base],[lane],[])==[]


def test_original_network_length_budget_regression():
    # A 200 m original street with two building fixtures: a short shared
    # access lane must fit the authored 25% budget, including its own width.
    base=edge(LineString([(0,0),(0,200)]))
    for footprint in (box(85,80,105,100),box(80,80,100,100)):
        options=aligned_access_paths([footprint],[base],angle=0,
                                    site=box(-50,-50,250,250),obstacles=box(1000,1000,1010,1010))
        assert options and options[0].length<=.25*200
        assert footprint_access_distance(footprint,road_surface([base,edge(options[0],4.5)]))<=40


def test_mid_edge_attachment_is_noded_with_original_width_and_tolerance():
    from datetime import datetime, timezone
    from test_formal_dictionary_pipeline import fixture
    from urban_design.generation.formal_pipeline import approved_parameters, skeleton_inputs
    from urban_design.generation.road_access import rebuild_access_skeleton
    from urban_design.generation.strategy_catalog import build_strategy_catalog
    context,manifest,inputs=fixture()
    context=context.model_copy(update={'method_parameters':{**context.method_parameters,**approved_parameters(inputs)}})
    resolved=skeleton_inputs(inputs,context)
    base=NS(edges=(edge(LineString([(0,100),(600,300)]),14),),primary_open_spaces=(NS(geometry=NS(model_dump=lambda: mapping(box(400,20,420,40)))),),created_at=datetime.now(timezone.utc))
    strategy=build_strategy_catalog(NS(intents=())).strategies[0]
    result=rebuild_access_skeleton(context,strategy,resolved,base,[LineString([(300,200),(300,280)])])
    assert len(result.edges)==3
    assert sorted(e.width_m for e in result.edges)==[4.5,14,14]
    junction=next(n for n in result.nodes if shape(n.geometry.model_dump()).distance(__import__('shapely').geometry.Point(300,200))<1e-6)
    assert sum(junction.id in (e.from_node_id,e.to_node_id) for e in result.edges)==3
