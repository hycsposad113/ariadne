"""FAB2 的幾何、土地閉合及交付實體意圖一致性負控制。"""
from __future__ import annotations

import copy

import pytest
from shapely.affinity import rotate
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import unary_union

from urban_design.generation.fabric_intent import IntentFrame
from urban_design.generation.fabric_plan import plan_from_intent, validate_plan


def inputs():
    facts = {'geometry': {'crs':'EPSG:28992','site':mapping(box(-100,-80,100,80)),
        'water':mapping(Polygon()),'buildable':mapping(box(-100,-80,100,80)),
        'waterfront_band':mapping(Polygon()), 'retained_buildings':[],
        'retained_roads':[], 'entrances':[]}, 'retained_buildings':[]}
    intent = {'fabric':'fabric.harbour_grain','frame':{'origin_epsg28992':[0,0],'axis_azimuth_deg':90},
        'streets':[{'id':'main','role':'primary','width_m':12,
                    'modes':['pedestrian','bicycle','car','service','fire'], 'polyline':[[-100,-6],[100,-6]]}],
        'parks':[{'name_zh':'測試公園','rect_uv':[-80,-40,50,70]}],
        'zones':[{'id':'row','typology':'block.rowhouse_strip','rect_uv':[-80,80,0,40],
                  'floors':[3,5],'rotation_deg':0,'frontage':['south']}], 'landmarks':[]}
    dictionary = {'fabrics':{}, 'entries':{'block.rowhouse_strip':{'id':'block.rowhouse_strip'}}}
    return intent, facts, dictionary


def test_frame_roundtrip_and_known_direction():
    frame=IntentFrame.parse({'origin_epsg28992':[89077.5489,435869.5274],'axis_azimuth_deg':57.6})
    point=Point(100,0)
    world=frame.world(point)
    assert world.x == pytest.approx(89161.9817,abs=.001)
    assert world.y == pytest.approx(435923.1101,abs=.001)
    assert frame.local(world).distance(point)<1e-8
    polygon=box(-300,-80,100,120)
    assert frame.local(frame.world(polygon)).hausdorff_distance(polygon)<1e-8


def test_rotated_zone_fragment_becomes_named_green_and_inputs_immutable():
    intent,facts,dictionary=inputs()
    intent['zones']=[{'id':'rotated','typology':'block.rowhouse_strip','rect_uv':[70,120,45,95],
                       'rotation_deg':35,'floors':[3,4]}]
    saved=copy.deepcopy((intent,facts,dictionary))
    plan=plan_from_intent(intent,facts,dictionary)
    assert plan['fragment_conversions']
    assert not plan['blocks']
    assert not [b for b in plan['buildings'] if not b['properties']['retained']]
    for fragment in plan['fragment_conversions']:
        greens=[r for r in plan['land_use'] if r['properties'].get('source_zone_id')=='rotated']
        assert greens and all(r['properties']['name_zh'] for r in greens)
        assert unary_union([shape(r['geometry']) for r in greens]).covers(shape(fragment['geometry']))
    assert (intent,facts,dictionary)==saved
    assert plan['validation']['checks']['LAND_COVERAGE']['passed']


def test_unallocated_zero_and_land_partition_no_overlap():
    plan=plan_from_intent(*inputs())
    checks=validate_plan(plan)['checks']
    assert checks['LAND_COVERAGE']['unallocated_m2']<1e-8
    assert checks['LAND_SUM_100_PERCENT']['percentage']==pytest.approx(100,abs=1e-8)
    assert checks['LAND_NO_OVERLAP']['passed']
    assert all(r['properties']['name_zh'] for r in plan['land_use'])


@pytest.mark.parametrize('mutation,check_id',[
    ('type','INTENT_ZONES'),('floors','INTENT_ZONES'),('rotation','INTENT_ZONES'),
    ('width','INTENT_STREETS'),('row_geometry','INTENT_STREETS'),('park','INTENT_PARKS'),
])
def test_intent_consistency_negative_controls_recompute_geometry(mutation,check_id):
    plan=plan_from_intent(*inputs())
    assert validate_plan(plan)['checks'][check_id]['passed']
    building=next(b for b in plan['buildings'] if not b['properties']['retained'])
    if mutation=='type':
        # Keep intent_typology cache unchanged; actual component must still fail.
        building['properties']['building_type']='building.i_slab'
    elif mutation=='floors':
        building['properties']['floors']=6
    elif mutation=='rotation':
        building['geometry']=mapping(rotate(shape(building['geometry']),10,origin='center'))
    elif mutation=='width':
        plan['roads'][0]['properties']['width_m']=11
    elif mutation=='row_geometry':
        plan['roads'][0]['properties']['right_of_way']=mapping(box(-100,-7,100,-5))
    else:
        row=next(r for r in plan['land_use'] if r['properties'].get('intent_park_index')==0)
        row['geometry']=mapping(shape(row['geometry']).difference(box(-80,50,-40,70)))
    result=validate_plan(plan)
    assert not result['checks'][check_id]['passed']
    assert result['checks'][check_id]['failure_locations']


def test_no_inferred_fire_mode_and_density_stays_within_zone_range():
    intent,facts,dictionary=inputs()
    intent['streets'][0]['modes'].remove('fire')
    plan=plan_from_intent(intent,facts,dictionary)
    assert 'fire' not in plan['roads'][0]['properties']['modes']
    assert not plan['validation']['checks']['FIRE_ALL_EXTERIORS']['passed']
    assert not plan['validation']['checks']['NEW_GFA_TARGET']['passed']
    assert all(3<=b['properties']['floors']<=5 for b in plan['buildings'])


def test_retained_buffer_conflict_is_located_and_does_not_change_intent():
    intent,facts,dictionary=inputs()
    facts['retained_buildings']=[{'id':'kept','geometry':mapping(box(-5,-10,5,10)),
                                'height_above_ground_m':12,'floor_count_upper':3}]
    facts['geometry']['retained_buildings']=copy.deepcopy(facts['retained_buildings'])
    plan=plan_from_intent(intent,facts,dictionary)
    conflicts=[i for i in plan['intent_issues'] if i['kind']=='street_conflict']
    assert conflicts and conflicts[0]['geometry']
    assert plan['intent']==intent
    assert plan['validation']['checks']['RETAINED_UNCHANGED']['passed']
    assert plan['validation']['checks']['RETAINED_6M_CLEARANCE']['passed']
    assert not plan['validation']['checks']['INTENT_STREETS']['passed']


@pytest.mark.parametrize('kind',['building.comb','building.courtyard_closed','block.hybrid'])
def test_deleted_required_template_wing_fails_assembly(kind):
    intent,facts,dictionary=inputs()
    intent['zones'][0].update(typology=kind,rect_uv=[-70,70,0,65])
    dictionary['entries'][kind]={'id':kind}
    plan=plan_from_intent(intent,facts,dictionary)
    assert plan['validation']['checks']['INTENT_TEMPLATE_ASSEMBLY']['passed']
    victim=next(b for b in plan['buildings'] if not b['properties']['retained'])
    plan['buildings'].remove(victim)
    assert not validate_plan(plan)['checks']['INTENT_TEMPLATE_ASSEMBLY']['passed']


def test_land_category_tampering_fails_semantic_check():
    plan=plan_from_intent(*inputs())
    assert plan['validation']['checks']['LAND_USE_CATEGORY_SEMANTICS']['passed']
    next(r for r in plan['land_use'] if r['properties']['category']=='roads')['properties']['category']='parks'
    check=validate_plan(plan)['checks']['LAND_USE_CATEGORY_SEMANTICS']
    assert not check['passed'] and check['failure_locations']


def test_east_frontage_executed_and_moving_wings_off_front_fails():
    from shapely.affinity import translate
    intent,facts,dictionary=inputs()
    intent['zones'][0].update(rect_uv=[0,40,-60,60],frontage=['east'])
    intent['streets'][0]['polyline']=[[46,-80],[46,80]]
    plan=plan_from_intent(intent,facts,dictionary)
    assert plan['validation']['checks']['INTENT_FRONTAGE']['passed']
    for b in plan['buildings']:
        b['geometry']=mapping(translate(shape(b['geometry']),xoff=-5))
    assert not validate_plan(plan)['checks']['INTENT_FRONTAGE']['passed']


def test_single_street_split_by_exclusion_is_two_mode_components():
    plan=plan_from_intent(*inputs())
    assert plan['validation']['checks']['CONNECTIVITY_PEDESTRIAN']['passed']
    road=plan['roads'][0]
    corridor=shape(road['properties']['right_of_way']).difference(box(-5,-15,5,2))
    road['properties']['right_of_way']=mapping(corridor)
    checks=validate_plan(plan)['checks']
    assert not checks['CONNECTIVITY_PEDESTRIAN']['passed']
    assert checks['CONNECTIVITY_PEDESTRIAN']['components']==2


def test_top_level_entrance_modes_are_used_and_missing_modes_fail_closed():
    intent,facts,dictionary=inputs()
    facts['geometry']['entrances']=[{'id':'entry','coordinates':[90,70]}]
    facts['entrances']=[{'id':'entry','coordinates':[90,70],'modes':['bicycle']}]
    plan=plan_from_intent(intent,facts,dictionary)
    assert plan['entrances'][0]['modes']==['bicycle']
    assert not plan['validation']['checks']['ENTRANCES_BICYCLE']['passed']
    assert plan['validation']['checks']['ENTRANCE_MODE_EVIDENCE']['passed']
    del plan['entrances'][0]['modes']
    assert not validate_plan(plan)['checks']['ENTRANCE_MODE_EVIDENCE']['passed']


@pytest.mark.parametrize('kind',['building.u_block','building.comb'])
def test_north_spine_has_south_opening_for_waterfront(kind):
    from urban_design.generation.fabric_intent import _templates
    templates,_=_templates(box(0,0,60,60),{'typology':kind,'frontage':['north','south']})
    footprint=unary_union([g for g,_,_ in templates])
    assert footprint.covers(Point(30,59))
    assert not footprint.covers(Point(30,1))


def test_landmark_nearest_retained_conflict_does_not_choose_farther_new():
    intent,facts,dictionary=inputs()
    facts['retained_buildings']=[{'id':'kept','geometry':mapping(box(-10,15,10,25)),
                                'height_above_ground_m':12,'floor_count_upper':3}]
    intent['landmarks']=[{'at_uv':[0,20],'height_m':18}]
    plan=plan_from_intent(intent,facts,dictionary)
    kept=next(b for b in plan['buildings'] if b['properties']['retained'])
    assert kept['properties']['height_m']==12
    assert plan['validation']['checks']['RETAINED_UNCHANGED']['passed']
    assert not plan['validation']['checks']['INTENT_LANDMARKS']['passed']
    assert any(i['kind']=='landmark_retained_conflict' for i in plan['intent_issues'])
    assert not any('landmark_index' in b['properties'] for b in plan['buildings'])
