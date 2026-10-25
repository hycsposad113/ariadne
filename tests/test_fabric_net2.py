import json
from pathlib import Path
from shapely.geometry import shape
from urban_design.generation.fabric_net2 import keileweg_alignment


def test_alignment_uses_frozen_geometry_and_direct_junction():
    from urban_design import scenario_syntax as ss
    external = ss.verified_extract('motor_vehicle')[0]['network']['features']
    line, receipt = keileweg_alignment(external)
    assert line.is_valid and line.length > 700
    assert tuple(line.coords[-1]) == (89427.348, 436216.183)
    assert receipt['source_ids'][0] == 'way/7518596'
    for ident in receipt['source_ids']:
        source = next(f for f in external if f['id'] == ident)
        assert shape(source['geometry']).difference(line.buffer(1e-7)).length < .01


def test_original_net1_geometry_preserved_verbatim():
    import copy
    from shapely.geometry import LineString, box, mapping
    from urban_design.generation.fabric_net2 import retain_and_connect_network
    def road(ident, coords, role, **props):
        return {'id': ident, 'type': 'Feature', 'geometry': mapping(LineString(coords)),
                'properties': {'role': role, 'width_m': 4, 'modes': ['pedestrian','bicycle'], **props}}
    original = road('bridge', [(1,1),(1,5)], 'canal_bridge', assumption='ASSUMED_BRIDGE')
    parent = {'net1': {'added_roads': [original]}}
    plan = {'roads': [road('main', [(0,0),(10,0)], 'primary_street'),
                      road('front', [(0,10),(10,10)], 'waterfront_path')],
            'buildings': [{'geometry': mapping(box(20,20,25,25))}], 'net2': {},
            'site':mapping(box(-10,-10,30,30)), 'water':mapping(box(28,28,29,29))}
    result = retain_and_connect_network(plan, parent)
    assert next(r for r in result['roads'] if r['id']=='bridge') == original
    assert result['net2']['network_preservation']['geometry_changed_ids'] == []
    assert parent == {'net1': {'added_roads': [original]}}


def test_five_storey_cap_changes_actual_floor_area_and_height():
    from shapely.geometry import box, mapping
    from urban_design.generation.fabric_net2 import enforce_five_storeys_and_fill
    building={'geometry':mapping(box(0,0,20,20)), 'properties':{'floors':6,'max_floors':6,
        'first_floor_height_m':4,'standard_floor_height_m':3.2,'height_m':20,'retained':False}}
    plan={'fabric_id':'fabric.harbour_grain','buildings':[building],'parameters':{'point_floor_height_assumption':{}},'net2':{}}
    result=enforce_five_storeys_and_fill(plan)
    assert building['properties']['floors']==5
    assert building['properties']['max_floors']==5
    assert building['properties']['height_m']==18
    assert result['net2']['five_storey_capacity']['gfa_after_additions_m2']==2000


def test_new_links_cannot_cross_water_without_bridge_assumption():
    from shapely.geometry import LineString, box, mapping
    from urban_design.generation.fabric_net2 import retain_and_connect_network
    def road(ident, coords, role):
        return {'id':ident,'geometry':mapping(LineString(coords)),
                'properties':{'role':role,'width_m':4,'modes':['pedestrian','bicycle']}}
    plan={'roads':[road('main',[(1,1),(19,1)],'primary_street'),
                   road('front',[(1,19),(19,19)],'waterfront_path')],
          'site':mapping(box(-5,-5,25,25)),'water':mapping(box(-5,8,25,12)),
          'buildings':[{'geometry':mapping(box(50,50,55,55))}],'net2':{}}
    result=retain_and_connect_network(plan,{'net1':{'added_roads':[]}})
    assert not result['net2']['network_preservation']['new_links']
    assert result['net2']['network_preservation']['failed_links'][0]['reason']=='new approach leaves full-width site land or crosses water'


def test_round4_transverses_reserve_real_junction_to_water_before_massing():
    from shapely.geometry import LineString, box, mapping
    from urban_design.generation.fabric_net2 import transverse_reservations
    land=box(0,0,100,100)
    waterfront=LineString([(0,10),(100,10)])
    external=[{'id':'junction','geometry':mapping(LineString([(50,105),(50,100)])),
               'properties':{'name':'Keileweg'}}]
    routes, receipt=transverse_reservations(land,waterfront,box(70,40,80,60),external,[(50,100)])
    assert len(routes)==1
    assert routes[0].distance(waterfront)<1e-7
    assert routes[0].distance(LineString([(0,90),(100,90)]))<1e-7
    assert routes[0].buffer(2,cap_style=2).difference(land).area<.05
    assert receipt[0]['external_target']==[50,100]
    assert receipt[0]['status']=='RESERVED'
    blocked, receipt=transverse_reservations(land,waterfront,box(40,40,60,60),external,[(50,100)])
    assert not blocked and receipt[0]['status']=='BLOCKED_RETAINED_BUILDING'


def test_round5_capacity_uses_actual_floors_without_exceeding_five():
    from shapely.geometry import box, mapping
    from urban_design.generation.fabric_net2 import enforce_five_storeys_and_fill
    building={'id':'new','geometry':mapping(box(0,0,100,100)), 'properties':{
        'floors':3,'max_floors':5,'first_floor_height_m':4,'height_m':11,'retained':False}}
    plan={'fabric_id':'fabric.courtyard_islands','buildings':[building],
          'parameters':{},'net2':{'round':5}}
    result=enforce_five_storeys_and_fill(plan)
    assert building['properties']['floors']==5
    assert building['properties']['height_m']==18
    assert result['net2']['five_storey_capacity']['raised_floor_buildings']==['new']
    assert result['net2']['five_storey_capacity']['gfa_after_additions_m2']==50000


def test_round5_point_capacity_keeps_depth_host_and_road_clearance():
    from shapely.geometry import box, mapping, LineString
    from urban_design.generation.fabric_net2 import enforce_five_storeys_and_fill
    b={'id':'point','geometry':mapping(box(0,0,20,20)),'properties':{
       'building_type':'building.point_array','depth_m':20,'block_id':'host',
       'floors':5,'max_floors':5,'first_floor_height_m':4,'height_m':18}}
    host={'id':'host','geometry':mapping(box(-20,0,50,30))}
    road={'geometry':mapping(LineString([(-20,-2),(50,-2)])),'properties':{'width_m':4}}
    plan={'fabric_id':'fabric.landscape_figure','net2':{'round':5},'parameters':{},
          'buildings':[b],'blocks':[host],'boundary_parcels':[],'courtyards':[],
          'roads':[road],'buildable':host['geometry'],'site':mapping(box(-30,-10,60,40)),
          'water':mapping(box(55,-10,60,40)),'block_axis_azimuth_deg':90}
    result=enforce_five_storeys_and_fill(plan)
    actual=shape(b['geometry'])
    assert actual.area>400
    assert shape(host['geometry']).covers(actual)
    assert actual.intersection(shape(road['geometry']).buffer(2,cap_style=2)).area<1e-6
    assert b['properties']['depth_m']==20 and b['properties']['floors']==5
    assert result['net2']['five_storey_capacity']['expanded_point_footprints'][0]['before_m2']==400


def test_round5_floor_fill_respects_building_specific_maximum():
    from shapely.geometry import box, mapping
    from urban_design.generation.fabric_net2 import enforce_five_storeys_and_fill
    b={'id':'hall','geometry':mapping(box(0,0,40,40)),'properties':{
       'floors':1,'max_floors':1,'first_floor_height_m':6,'height_m':6}}
    plan={'fabric_id':'fabric.courtyard_islands','buildings':[b],'parameters':{},'net2':{'round':5}}
    enforce_five_storeys_and_fill(plan)
    assert b['properties']['floors']==1
    assert b['properties']['height_m']==6


def test_round6_gfa_threshold_is_exact_85_percent():
    from urban_design.generation import fabric_plan as base
    assert base.NEW_GFA_MIN_M2 == 146873 * .85


def test_round6_point_growth_preserves_short_edge_and_host():
    from shapely.geometry import box, mapping
    from urban_design.generation.fabric_net2 import fill_round6_points
    b={'id':'p','geometry':mapping(box(0,0,20,26)),'properties':{'building_type':'building.point_array',
       'block_id':'host','floors':5,'depth_m':20}}
    plan={'fabric_id':'fabric.landscape_figure','buildings':[b],'roads':[], 'courtyards':[],
          'blocks':[{'id':'host','geometry':mapping(box(0,0,20,40))}], 'boundary_parcels':[],
          'buildable':mapping(box(0,0,20,40)), 'site':mapping(box(0,0,100,100)),
          'block_axis_azimuth_deg':90,'net2':{}}
    fill_round6_points(plan)
    assert shape(b['geometry']).area > 520
    assert shape(plan['buildable']).covers(shape(b['geometry']))
    assert shape(b['geometry']).bounds[2] == 20


def test_round7_rejects_service_land_and_outside_site_links_and_restores_mass():
    import copy
    from shapely.geometry import box, LineString, mapping
    from urban_design.generation.fabric_net2 import repair_round7_links
    def road(ident,points):
        return {'id':ident,'geometry':mapping(LineString(points)), 'properties':{'width_m':4}}
    parent={'site':mapping(box(0,0,100,100)),'water':mapping(box(90,0,100,100)),
            'land_use':[{'geometry':mapping(box(0,0,90,20)), 'properties':{'category':'roads'}}],
            'roads':[road('old',[(0,10),(100,10)])],
            'buildings':[{'id':'restore-me','geometry':mapping(box(30,30,40,40))}]}
    candidate=copy.deepcopy(parent);candidate['buildings']=[];candidate['net2']={}
    candidate['roads'] += [road('net2-r6-direct-valid',[(5,10),(20,10)]),
                           road('net2-r6-direct-service',[(5,30),(20,30)]),
                           road('net2-r6-direct-water',[(85,10),(95,10)]),
                           road('net2-r6-direct-outside',[(-5,10),(5,10)])]
    repair_round7_links(candidate,parent)
    assert [r['id'] for r in candidate['roads']]==['old','net2-r6-direct-valid']
    assert candidate['buildings']==parent['buildings']
    assert len(candidate['net2']['round7_repair']['links'])==4
