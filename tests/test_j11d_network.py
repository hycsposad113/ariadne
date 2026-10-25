"""J11d scope and construction regressions using measured geometry."""
import math
from shapely.geometry import LineString, box
from urban_design.generation import multimodal_network as n


def road(identity, coords, retained=False):
    r=n._road(LineString(coords),identity,n.NetworkRules())
    return r.model_copy(update={'origin':'retained','hierarchy':'retained','source_road_ids':[identity]}) if retained else r


def test_retained_self_geometry_excluded_from_new_and_junctions_scope():
    fixed=road('fixed',[(0,0),(1,0),(.1,.2)],True)
    q=n.geometry_quality(box(-10,-10,30,30),[fixed],[box(0,0,40,40)],[],n.NetworkRules())
    assert q['scope']=='new_and_junctions'
    assert q['minimum_turn_deg']==180
    assert q['angle_violations']==[]
    assert q['minimum_segment_pass']


def test_new_acute_junction_to_retained_remains_rejected():
    fixed=road('fixed',[(-50,0),(50,0)],True)
    new=road('new',[(0,0),(40,10)])
    q=n.geometry_quality(box(-60,-60,60,60),[fixed,new],[box(0,0,40,40)],[],n.NetworkRules())
    assert q['minimum_turn_deg']<30
    assert not q['valid']
    assert any('new' in v['road_ids'] for v in q['angle_violations'])


def test_new_short_segment_at_retained_junction_remains_rejected():
    q=n.geometry_quality(box(-60,-60,60,60),[road('fixed',[(-50,0),(50,0)],True),road('new',[(0,0),(0,2)])],[box(0,0,40,40)],[],n.NetworkRules())
    assert not q['minimum_segment_pass']


def test_merge_close_junction_nodes_preserves_all_connections_and_fixed_bytes():
    fixed=road('fixed',[(-20,0),(20,0)],True)
    rs=[road('trunk',[(0,-20),(0,20)]),road('branch',[(.2,0),(.2,20)])]
    before=fixed.model_dump()
    cleaned,receipt=n.merge_junction_nodes([fixed,*rs],box(-30,-30,30,30),n.NetworkRules(),anchors=[n.Entrance(id='destination',coordinates=(.2,20),modes=['pedestrian'],source_ids={},weight=1)])
    assert fixed.model_dump()==before
    q=n.geometry_quality(box(-30,-30,30,30),[fixed,*cleaned],[],[],n.NetworkRules())
    assert q['connected_component_count']==1
    assert q['minimum_segment_pass']
    assert receipt['merged_node_count']>0
    assert any(LineString(r.coordinates).distance(LineString([(.2,20),(.2,20.1)]))<1e-7 for r in cleaned)


def test_merge_nodes_does_not_cross_a_retained_obstacle():
    rs=[road('a',[(0,0),(0,10)]),road('b',[(2,0),(2,10)])]
    domain=box(-1,-1,3,11).difference(box(.5,-1,1.5,9))
    cleaned,receipt=n.merge_junction_nodes(rs,domain,n.NetworkRules())
    assert all(domain.buffer(1e-7).covers(LineString(r.coordinates)) for r in cleaned)


def test_acute_fixed_crossing_is_reattached_orthogonally_without_losing_ends():
    fixed=road('fixed',[(-100,0),(100,0)],True)
    new=road('new',[(-80,-8),(80,8)])
    result,receipt=n.reattach_fixed_junctions([fixed,new],box(-110,-30,110,30),n.NetworkRules())
    assert receipt['reattached_count']==1
    assert result[0].coordinates[0]==new.coordinates[0]
    assert result[0].coordinates[-1]==new.coordinates[-1]
    q=n.geometry_quality(box(-110,-30,110,30),[fixed,*result],[],[],n.NetworkRules())
    assert q['minimum_turn_deg']>=30
    assert q['connected_component_count']==1
    assert fixed.coordinates==[(-100.,0.),(100.,0.)]


def test_axial_shared_spine_uses_major_entry_and_wider_active_frontage_class():
    e=n.Entrance(id='north',coordinates=(120,240),modes=['pedestrian','bicycle'],source_ids={},weight=3)
    v=n.generate_variants(box(0,0,240,240),[],[e],'axial',n.NetworkRules())[0]
    main=[r for r in v.roads if r.hierarchy=='main' and 'motor_vehicle' not in r.modes]
    assert any(LineString(r.coordinates).distance(LineString([(120,240),(120,241)]))<1e-7 for r in main)
    assert all(r.width_class=='main_shared' and r.width_m>n.NetworkRules().shared_width_m and r.active_frontage_candidate_sides=='both' for r in main)


def test_existing_geometry_permission_overlay_does_not_make_old_bend_new():
    fixed=road('fixed',[(0,0),(1,0),(.1,.2)],True)
    overlay=fixed.model_copy(update={'id':'walk-overlay','origin':'new','modes':['pedestrian'],'source_road_ids':['fixed']})
    q=n.geometry_quality(box(-10,-10,30,30),[fixed,overlay],[box(0,0,40,40)],[],n.NetworkRules())
    assert q['minimum_turn_deg']==180
    assert q['minimum_segment_pass']


def test_chained_node_contractions_remeasure_current_representatives():
    rs=[road('chain',[(0,0),(2,0),(4,0),(20,0)])]
    cleaned,receipt=n.merge_junction_nodes(rs,box(-1,-1,21,1),n.NetworkRules())
    assert receipt['merges']
    assert all(math.dist(m['from'],m['to'])<n.NetworkRules().minimum_segment_m for m in receipt['merges'])
    assert all(abs(math.dist(m['from'],m['to'])-m['distance_m'])<1e-7 for m in receipt['merges'])
    assert cleaned
