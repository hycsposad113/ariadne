"""Independent graph properties and measured J11d geometry regressions."""
import json
import math
from pathlib import Path

import pytest
from shapely.geometry import LineString, box
from urban_design.generation import multimodal_network as n
from urban_design.generation.network_cleanup import cleanup_network, noded, acute_pairs, blocks, dimensions, CleanupRules


def road(identity, coords, locked=False, modes=None):
    r=n._road(LineString(coords),identity,n.NetworkRules())
    return r.model_copy(update={'origin':'retained' if locked else 'new', 'modes':modes or ['pedestrian','bicycle']})


def assert_properties(original, result, report):
    for fixed in [r for r in original if r.origin=='retained']:
        assert next(r for r in result if r.id==fixed.id).model_dump()==fixed.model_dump()
    assert all(report.mode_components_after[m]<=report.mode_components_before[m] for m in report.mode_components_before)
    assert not acute_pairs(noded(result),30)
    exemptions={tuple(map(tuple, e['coordinates'])) for e in report.exempt_locked}
    assert all(LineString(r.coordinates).length>=3 or tuple(map(tuple,r.coordinates)) in exemptions for r in noded(result) if r.origin!='retained')


@pytest.mark.parametrize('delta',[.08057850282031889,.03696921187053893,2.9])
def test_short_edge_contraction_deterministic_and_locked(delta):
    original=[road('fixed',[(-20,0),(20,0)],True),road('up',[(0,0),(0,delta),(0,30)])]
    first,report=cleanup_network(original,[],domain=box(-40,-40,40,40))
    second,again=cleanup_network(original,[],domain=box(-40,-40,40,40))
    assert [r.model_dump() for r in first]==[r.model_dump() for r in second]
    assert report.model_dump()==again.model_dump()
    assert report.merged_node_count>0
    assert_properties(original,first,report)


def test_acute_junction_repaired_to_real_t():
    original=[road('fixed',[(-100,0),(100,0)],True),road('acute',[(0,0),(40,10)])]
    result,report=cleanup_network(original,[],domain=box(-120,-30,120,30))
    assert report.t_junction_repair_count==1
    assert any(r.origin=='new' and set(r.coordinates)=={(40.,0.),(40.,10.)} for r in result)
    assert_properties(original,result,report)


def test_locked_short_edge_exemption_keeps_both_entrances():
    entrances=[n.Entrance(id=str(i),coordinates=p,modes=['pedestrian','bicycle'],source_ids={},weight=1) for i,p in enumerate([(0,0),(2,0)])]
    result,report=cleanup_network([road('link',[(0,0),(2,0)])],entrances)
    assert result and report.exempt_locked
    assert set(result[0].coordinates)=={(0.,0.),(2.,0.)}
    assert report.unresolved[0]['kind']=='locked_cluster'


def test_obstacle_blocks_snap_and_t_without_mock_success():
    original=[road('fixed',[(-100,0),(100,0)],True),road('acute',[(0,0),(40,10)])]
    entry=n.Entrance(id='far',coordinates=(40,10),modes=['pedestrian','bicycle'],source_ids={},weight=1)
    result,report=cleanup_network(original,[entry],obstacles=box(39,1,41,9))
    assert report.unresolved
    assert any(u['kind']=='acute_angle' for u in report.unresolved)
    assert report.t_junction_repair_count==0
    assert any(r.origin=='new' for r in result)


def test_crossing_modes_noded_but_grade_separation_preserved():
    original=[road('horizontal',[(-20,0),(20,0)]),road('vertical',[(0,-20),(0,20)],modes=['pedestrian'])]
    result,report=cleanup_network(original,[])
    assert report.mode_components_after=={'pedestrian':1,'bicycle':1,'motor_vehicle':0}
    elevated=original[1].model_copy(update={'layer':1})
    _,report=cleanup_network([original[0],elevated],[])
    assert report.mode_components_before['pedestrian']==2
    assert report.mode_components_after['pedestrian']==2


def test_long_canal_block_cuts_network_to_network():
    original=[road('boundary',[(0,0),(454.6394189618472,0),(454.6394189618472,80),(0,80),(0,0)],True)]
    result,report=cleanup_network(original,[],domain=box(-1,-1,456,81))
    assert report.subdivision_segment_count==4
    assert not report.unresolved_block
    assert len(blocks(result,None))==5
    assert all(40<=dimensions(b)[0] and dimensions(b)[1]<=120 for b in blocks(result,None))
    assert_properties(original,result,report)


def test_long_narrow_or_obstructed_block_is_explicitly_unresolved():
    original=[road('boundary',[(0,0),(454.6,0),(454.6,30),(0,30),(0,0)],True)]
    result,report=cleanup_network(original,[])
    assert report.subdivision_segment_count==0
    assert report.unresolved_block[0]['long_side_m']==pytest.approx(454.6)
    assert '40m' in report.unresolved_block[0]['reason']


@pytest.mark.parametrize('row_id',['axial-0','radial-0'])
def test_j11d_measured_short_fragment_coordinates(row_id):
    rows=json.loads(Path('artifacts/j11d-network/run-2-geometry-audit.json').read_text())['rows']
    fragment=next(r for r in rows if r['id']==row_id)['minimum_segment']
    a,b=map(tuple,fragment['coordinates']);dx,dy=b[0]-a[0],b[1]-a[1];norm=math.hypot(dx,dy)
    far=(b[0]+dx/norm*30,b[1]+dy/norm*30)
    original=[road('fragment',[a,b,far])]
    result,report=cleanup_network(original,[])
    assert result and report.merged_node_count>0
    assert_properties(original,result,report)


def test_rule_card_conflict_fails_closed():
    with pytest.raises(ValueError,match='conflicts'):
        cleanup_network([],[],network_rules=n.NetworkRules(minimum_segment_m=2))


def test_standalone_mode_edge_cannot_disappear_as_fake_connectivity_improvement():
    result,report=cleanup_network([road('only',[(0,0),(2,0)],modes=['pedestrian'])],[])
    assert result
    assert report.mode_components_after['pedestrian']==1
    assert any(u['kind']=='short_edge' for u in report.unresolved)


def test_j11d_actual_south_canal_block_is_subdivided_or_measured_unresolved():
    doc=json.loads(Path('artifacts/j11d-network/run-2/axial-0.json').read_text())
    from shapely.geometry import shape
    candidates=[shape(f['geometry']) for f in doc['geometry']['features'] if f['properties']['role']=='street_block']
    measured=min(candidates,key=lambda b:abs(dimensions(b)[1]-454.6394189618472))
    assert dimensions(measured)[1]==pytest.approx(454.6394189618472)
    original=[road('actual-canal-boundary',list(measured.exterior.coords),True)]
    result,report=cleanup_network(original,[])
    for b in blocks(result,None):
        assert dimensions(b)[1]<=120 or any(math.dist(b.centroid.coords[0],u['coordinates'])<1e-7 for u in report.unresolved_block)
    assert report.unresolved_block  # Actual strip is less than the 40m child minimum.


@pytest.mark.parametrize('length',[121,160,200,300,454.6394189618472,620.540960])
def test_block_subdivision_property_for_multiple_long_sides(length):
    original=[road('ring',[(0,0),(length,0),(length,80),(0,80),(0,0)],True)]
    result,report=cleanup_network(original,[])
    assert not report.unresolved_block
    assert all(dimensions(b)[1]<=120 for b in blocks(result,None))
    independent=n.geometry_quality(box(-1,-1,length+1,81),result,blocks(result,None),[],n.NetworkRules())
    assert independent['minimum_turn_deg']>=30
    assert independent['minimum_segment_pass']
    assert independent['connected_component_count']==1


def test_locked_interior_entrance_is_one_component_without_coordinate_rounding():
    anchor=n.Entrance(id='interior',coordinates=(10,1e-10),modes=['pedestrian','bicycle'],source_ids={},weight=1)
    fixed=road('fixed',[(0,0),(20,0)],True)
    result,report=cleanup_network([fixed],[anchor])
    assert report.mode_components_before==report.mode_components_after=={'pedestrian':1,'bicycle':1,'motor_vehicle':0}
    assert result[0].model_dump()==fixed.model_dump()
    assert anchor.coordinates==(10,1e-10)



def test_block_just_below_40m_is_not_rounded_into_pass():
    width=40-1e-8
    original=[road('ring',[(0,0),(160,0),(160,width),(0,width),(0,0)],True)]
    _,report=cleanup_network(original,[])
    assert report.subdivision_segment_count==0
    assert report.unresolved_block


def test_angle_just_below_30_degrees_is_not_rounded_into_pass():
    from urban_design.generation.network_cleanup import acute_pairs
    angle=math.radians(30-5e-9)
    original=[road('fixed',[(0,0),(100,0)],True),road('new',[(0,0),(40*math.cos(angle),40*math.sin(angle))])]
    violations=acute_pairs(noded(original),30)
    assert violations
    assert violations[0][-1]<30
