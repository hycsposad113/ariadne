"""J17 synthetic negative controls; these fixtures are not Rotterdam evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, box, mapping, shape

from scripts.s6_brief import _brief_segment_rows
from urban_design.generation import brief_driven as bd
from urban_design.generation.multimodal_network import NetworkRoad


def _road():
    return NetworkRoad(id='park-cut', coordinates=[(120, 0), (120, 100)], width_m=6,
        modes=['pedestrian', 'bicycle', 'motor_vehicle'], origin='new', layer=0,
        hierarchy='service', width_class='service', access='service_only',
        semantics_provenance='ILLUSTRATIVE_TEST', rule_card_ids=['test'])


def _mini_row():
    building = box(0, 0, 40, 12)
    floors = [dict(geometry=mapping(building), floor_height_m=3.5, use='Residential') for _ in range(4)]
    return dict(status='VALID', brief_version=bd.VERSION, checks={'fixture': True},
        network_hard_checks={'checks': {'fixture': True}},
        buildings=[dict(type_id='building.i_slab', footprint_area_m2=480., floors=floors,
            floor_count=4, height_m=14., scale={'wing_depth_m': 12., 'unit_count': None, 'unit_frontage_m': None})],
        features=[dict(geometry=mapping(building))],
        structure={'development': [], 'blocks': [dict(strip_id='s', geometry=mapping(box(-1,-1,41,13)))],
            'roads': [], 'meta': {'brief_parks': [dict(geometry=mapping(box(100,0,140,100)), target_area_m2=4000.)]}},
        brief_allocation={'targets_m2': {'s': 1920.}, 'actual_m2': {'s': 1920.}},
        metrics={'retained_gfa_upper_m2': 0., 'far_denominator_m2': 2560.})


def _guard_row():
    row=_mini_row(); row['buildings']=[];row['features']=[];row['structure']['blocks']=[]
    for index in range(32):
        g=box(index*60,0,index*60+40,12)
        record=deepcopy(_mini_row()['buildings'][0])
        for floor in record['floors']:floor['geometry']=mapping(g)
        row['buildings'].append(record);row['features'].append({'geometry':mapping(g)})
        row['structure']['blocks'].append({'strip_id':'s','geometry':mapping(g.buffer(.1))})
    row['brief_allocation']={'targets_m2':{'s':61440.},'actual_m2':{'s':61440.}}
    row['metrics']={'retained_gfa_upper_m2':68907.884,'far_denominator_m2':183591.3,
        'far':(61440.+68907.884)/183591.3,'new_gfa_m2':61440.}
    return row


@pytest.mark.parametrize('station', [0., 12.5, 50., 87.5, 100.])
def test_station_roundtrip_uses_frozen_domain_not_axis_metres(station):
    axis=LineString([(10,20),(70,20),(70,100)])  # measured 140m, facts station length100m
    point=bd.station_to_axis(axis, station, 100.)
    assert point.distance(axis.interpolate(station/100., normalized=True)) < 1e-9
    assert bd.axis_to_station(axis, point, 100.) == pytest.approx(station)
    assert bd.station_to_axis(axis, bd.axis_to_station(axis, point, 100.), 100.).distance(point) < 1e-9


@pytest.mark.parametrize('station', [-1., 101.])
def test_station_mapping_rejects_outside_frozen_domain(station):
    with pytest.raises(ValueError): bd.station_to_axis(LineString([(0,0),(200,0)]),station,100.)


def test_direct_and_nested_chinese_segments_share_canonical_parser():
    parent={'strip_id':'s','typologies':['perimeter'],'floors':[4,5],'frontage':'both_sides'}
    child={'segment_m':[0,100],'building_types_zh':['連棟街屋','混合用途板樓']}
    nested=_brief_segment_rows({'strips':[{**parent,'segments':[child]}]})[0]
    direct=_brief_segment_rows({'strips':[{**parent,**child,'typologies':['連棟街屋','混合用途板樓']}]})[0]
    # Child labels override inherited parent type; fallback only applies when absent.
    assert nested['typologies'] == direct['typologies'] == ['rowhouse','slab']
    assert bd.typology_ids(nested['typologies']) == ('building.rowhouse','building.i_slab')
    assert nested['strip_id']=='s' and nested['floors']==[4,5]


@pytest.mark.parametrize('actual,passed', [(849.99,False),(850.,True),(1000.,True),(1150.,True),(1150.01,False)])
def test_strip_gfa_tolerance_includes_boundaries(actual,passed):
    assert bd.strip_gfa_gate(actual,1000.) is passed


def test_strip_gfa_tolerance_cannot_be_relaxed():
    assert bd.strip_gfa_gate(1200.,1000.,tolerance=.2) is False
    assert bd.strip_gfa_gate(0.,0.) is False


def test_drawing_guard_accepts_measured_fixture():
    bd.brief_drawing_guard(_guard_row())


def test_drawing_guard_rejects_8m_wing_despite_forged_valid_labels():
    row=_guard_row(); g=box(0,0,60,8) # same 480m2/GFA; only independent depth differs
    row['features'][0]['geometry']=mapping(g)
    row['structure']['blocks'][0]['geometry']=mapping(box(-1,-1,61,13))
    for floor in row['buildings'][0]['floors']: floor['geometry']=mapping(g)
    with pytest.raises(ValueError, match='scale|wing|depth'): bd.brief_drawing_guard(row)


def test_park_intent_gate_rejects_motor_cut_and_accepts_shared_path():
    park=box(100,0,140,100); road=_road()
    assert bd.park_target_gate(park,4000.,[]) is True
    assert bd.park_target_gate(park,4000.,[road]) is False
    shared=road.model_copy(update={'modes':['pedestrian','bicycle']})
    assert bd.park_target_gate(park,4000.,[shared]) is True


def test_drawing_guard_rejects_gfa_changed_after_validation():
    row=_guard_row(); row['buildings'][0]['floors']=row['buildings'][0]['floors'][:2]
    with pytest.raises(ValueError): bd.brief_drawing_guard(row)


def _facts():
    site=box(0,-60,200,60); axis=LineString([(0,0),(200,0)])
    return {'geometry': {'crs':'EPSG:28992','site':mapping(site),'water':mapping(box(0,70,200,80)),
        'buildable':mapping(site),'waterfront_band':mapping(box(0,60,200,70)),
        'dakpark':mapping(box(0,90,200,100)),
        'strips':[{'id':'s','geometry':mapping(site),'axis':mapping(axis)}]},
        'buildable':{'strips':[{'id':'s','length_m':100.}]}}


@pytest.mark.parametrize('height,passed', [(14.,True),(100.,False)])
def test_landmark_height_gate_rejects_100m_without_promoting_valid_status(monkeypatch,height,passed):
    structure={'development': [], 'blocks':[{'strip_id':'s','geometry':box(-1,-1,41,13)}],
        'meta':{'brief_parks':[{'valid':True}]}}
    row=_mini_row(); row['failure_reasons']=[]
    monkeypatch.setattr(bd.bf,'generate_block_first',lambda **kwargs:deepcopy(row))
    brief={'gfa_allocation':{'by_strip':[{'strip_id':'s','gfa_m2':1920.}]},
        'height_strategy':{'landmarks':[{'strip_id':'s','station_m':10.,'height_m':height}]}}
    result=bd.generate_brief_driven(brief=brief,facts=_facts(),structure=structure, family='axial', entrances=[], site=shape(_facts()['geometry']['site']))
    assert result['checks']['brief_landmarks'] is passed
    if not passed: assert result['status']=='INVALID' and 'brief_landmarks' in result['failure_reasons']


def test_low_zone_exemption_is_limited_to_its_geometric_interval(monkeypatch):
    facts=_facts(); site=shape(facts['geometry']['site'])
    brief={'development_streets':[{'strip_id':'s','segment_m':[0,100]}], 'strips':[{'strip_id':'s','segment_m':[0,100],'typologies':['slab'],'floors':[4,5]}],
        'height_strategy':{'low_zones':[{'strip_id':'s','segment_m':[0,25],'floors':2}]}}
    monkeypatch.setattr(bd.bf,'roads_from_structure',lambda *args,**kwargs:([],[],None,[]))
    monkeypatch.setattr(bd.bf,'strip_land_blocks',lambda *args,**kwargs:[{'id':'b','geometry':box(0,10,200,60)}])
    result=bd.build_brief_structure(brief=brief,facts=facts,family='axial',site=site,
        water=shape(facts['geometry']['water']),retained={},entrances=[],fixed_roads=[],network_rules=SimpleNamespace())
    low=[b for b in result['blocks'] if b.get('floor_cap')==2]
    normal=[b for b in result['blocks'] if not b.get('floor_cap')]
    assert low and normal, 'partial low zone must split massing domains, preserving ordinary floor minimum elsewhere'
    assert all(b['geometry'].bounds[2] <= 50.00001 for b in low)
    assert all(b['geometry'].bounds[0] >= 49.99999 for b in normal)


def test_landmark_100m_station_offset_is_not_satisfied_by_nearby_other_station(monkeypatch):
    facts=_facts()
    # Folded strip ends lie 10m apart, but stations differ by210m.
    facts['geometry']['strips'][0]['axis']=mapping(LineString([(0,0),(100,0),(100,10),(0,10)]))
    facts['buildable']['strips'][0]['length_m']=210.
    row=_mini_row(); row['failure_reasons']=[]
    lower=box(0,-12,40,0); row['features'][0]['geometry']=mapping(lower)
    for floor in row['buildings'][0]['floors']: floor['geometry']=mapping(lower)
    structure={'development': [], 'blocks':[{'strip_id':'s','geometry':box(-1,-13,41,13)}], 'meta':{'brief_parks':[{'valid':True}]}}
    monkeypatch.setattr(bd.bf,'generate_block_first',lambda **kwargs:deepcopy(row))
    brief={'gfa_allocation':{'by_strip':[{'strip_id':'s','gfa_m2':1920.}]},
        'height_strategy':{'landmarks':[{'strip_id':'s','station_m':210.,'height_m':14.}]}}
    result=bd.generate_brief_driven(brief=brief,facts=facts,structure=structure, family='axial', entrances=[], site=shape(_facts()['geometry']['site']))
    assert result['checks']['brief_landmarks'] is False, 'Euclidean proximity cannot substitute authored station'


def test_one_side_frontage_does_not_inherit_bilateral_denominator():
    axis=LineString([(0,0),(200,0)]); domain=box(0,-65,200,65)
    buildings=[{'type_id':'building.i_slab','geometry':box(0,8,200,20)}]
    single=bd.scoped_frontage_assessment([axis],buildings,domain,'one_side_street')
    both=bd.scoped_frontage_assessment([axis],buildings,domain,'both_sides')
    assert single['brief_frontage_gate'] is True
    assert both['brief_frontage_gate'] is False
    assert both['brief_frontage_ratio'] == 0.


@pytest.mark.parametrize('name', ['radial','grid','axial','green_service'])
def test_real_four_briefs_parse_authored_block_length_shapes(name):
    import json
    from pathlib import Path
    brief=json.loads((Path(__file__).resolve().parents[1]/'artifacts'/'s6-brief'/'briefs-r4b'/f'{name}.json').read_text())
    rows=_brief_segment_rows(brief)
    assert rows
    for row in rows:
        expected=row.get('block_length_m')
        if expected is None:
            dims=row.get('block_dimensions_m')
            expected=dims if isinstance(dims,list) else dims.get('module_range',dims.get('radial_block_module_range')) if isinstance(dims,dict) else None
        if expected is not None:
            assert bd.block_length_range(row) == tuple(map(float,expected))


@pytest.mark.parametrize('text,expected', [
    ('單側連續街牆，不做雙側周邊式','single_side'),
    ('沿發展街兩側設低層街牆','both_sides'),
    ('一側界定，不採雙側量體','single_side'),
    ('不做雙側周邊式','single_side'),
])
def test_chinese_frontage_negation_is_not_bilateral_intent(text,expected):
    assert bd.normalize_frontage(text)==expected


def test_residential_15m_measured_wing_exceeds_upper_scale():
    profile=SimpleNamespace(geometry=box(0,0,40,15),type_id='building.i_slab',wing_depth_m=15.,unit_count=None,unit_frontage_m=None)
    assert bd.measured_scale_gate(profile,'Residential') is False
    profile.geometry=box(0,0,40,14);profile.wing_depth_m=14.
    assert bd.measured_scale_gate(profile,'Residential') is True


def test_landmark_actual_station_offset_of_100m_fails(monkeypatch):
    facts=_facts(); facts['buildable']['strips'][0]['length_m']=200.
    row=_mini_row(); row['failure_reasons']=[]
    structure={'development':[], 'blocks':[{'strip_id':'s','geometry':box(-1,-1,41,13)}], 'meta':{'brief_parks':[{'valid':True}]}}
    monkeypatch.setattr(bd.bf,'generate_block_first',lambda **kwargs:deepcopy(row))
    brief={'gfa_allocation':{'by_strip':[{'strip_id':'s','gfa_m2':1920.}]},
        'height_strategy':{'landmarks':[{'strip_id':'s','station_m':120.,'height_m':14.}]}}
    result=bd.generate_brief_driven(brief=brief,facts=facts,structure=structure,family='axial',entrances=[],site=shape(facts['geometry']['site']))
    assert result['brief_landmarks'][0]['actual_station_difference_m']==pytest.approx(100.)
    assert result['checks']['brief_landmarks'] is False


@pytest.mark.parametrize('frontage,passed', [('單側街牆，不做雙側','single'),('沿發展街兩側','both')])
def test_generation_rebuilds_authored_named_parks_and_substitutes_scoped_checks(monkeypatch,frontage,passed):
    row=_mini_row(); row['failure_reasons']=['development_bilateral_streetwall','defining_edge']
    row['checks'].update(development_bilateral_streetwall=False,defining_edge=False)
    row['named_open_spaces']=[{'name_zh':'舊的推算公園'}]
    park={'name_zh':'設計者潮汐公園','type':'tidal_park','geometry':mapping(box(100,0,140,100)),
        'target_area_m2':4000.,'valid':True}
    structure={'development':[], 'blocks':[{'id':'b','strip_id':'s','geometry':box(-1,-1,41,13)}], 'meta':{'brief_parks':[park]}}
    monkeypatch.setattr(bd.bf,'generate_block_first',lambda **kwargs:deepcopy(row))
    brief={'strips':[{'strip_id':'s','segment_m':[0,20],'typologies':['slab'],'floors':[4,4],'frontage':frontage}],
        'gfa_allocation':{'by_strip':[{'strip_id':'s','gfa_m2':1920.}]}}
    result=bd.generate_brief_driven(brief=brief,facts=_facts(),structure=structure,family='axial',entrances=[],site=shape(_facts()['geometry']['site']))
    assert result['named_open_spaces'][0]['name_zh']=='設計者潮汐公園'
    assert result['named_open_spaces'][0]['type']=='tidal_park'
    assert result['named_open_spaces'][0]['area_m2']==pytest.approx(4000.)
    assert result['legacy_named_open_spaces']==[{'name_zh':'舊的推算公園'}]
    assert result['legacy_frontage_checks']=={'development_bilateral_streetwall':False,'defining_edge':False}
    if passed=='single':
        assert result['checks']['development_bilateral_streetwall'] is True # no bilateral scopes
        assert result['checks']['defining_edge'] is True
        assert 'development_bilateral_streetwall' not in result['failure_reasons']
        assert 'defining_edge' not in result['failure_reasons']
    else:
        assert result['checks']['development_bilateral_streetwall'] is False
        assert 'development_bilateral_streetwall' in result['failure_reasons']


@pytest.mark.parametrize('gap_m',[1.,1.23])
def test_optin_entry_repair_extends_short_link_without_lowering_3m_gate(gap_m):
    from urban_design.generation import block_first as bf
    from urban_design.generation.multimodal_network import Entrance,NetworkRules
    from shapely.ops import unary_union
    modes=['pedestrian','bicycle','motor_vehicle']
    entries=[Entrance(id=f'e{i}',coordinates=(x,gap_m),modes=modes,
        source_ids={mode:['same-external'] for mode in modes},weight=1) for i,x in enumerate([20.,80.])]
    axis=LineString([(0,0),(100,0)])
    kwargs=dict(axes=[dict(id='axis',role='main',geometry=axis,intent_zh='ILLUSTRATIVE_TEST')],
        blocks=[],site=box(-10,-20,110,20),water=box(500,500,510,510),retained={},
        entrances=entries,fixed_roads=[],network_rules=NetworkRules())
    default=bf.roads_from_structure(**kwargs)[0]
    legacy=bf.roads_from_structure(**kwargs,repair_multimodal=False)[0]
    repaired=bf.roads_from_structure(**kwargs,repair_multimodal=True)[0]
    assert [r.model_dump() for r in default]==[r.model_dump() for r in legacy]
    before={r.id:r.model_dump() for r in legacy}; after={r.id:r.model_dump() for r in repaired}
    assert all(after[identity]==record for identity,record in before.items()), 'optin preserves all original roads'
    assert kwargs['network_rules'].minimum_segment_m == 3.
    assert len(repaired)>len(legacy)
    assert all(LineString(r.coordinates).length >= 3.-1e-9 for r in repaired if r.id not in before)
    for mode in modes:
        old_support=unary_union([LineString(r.coordinates) for r in legacy if mode in r.modes])
        new_support=unary_union([LineString(r.coordinates) for r in repaired if mode in r.modes])
        for entry in entries:
            assert Point(entry.coordinates).distance(old_support)==pytest.approx(gap_m)
            assert Point(entry.coordinates).distance(new_support)<1e-9
    for road in repaired:
        if road.id not in before:
            line=LineString(road.coordinates)
            assert line.distance(axis)<1e-9
            assert any(Point(entry.coordinates).distance(line)<1e-9 for entry in entries)


def _metric_row():
    row=_guard_row();row['failure_reasons']=[]
    row['open_space']=mapping(box(2000,0,2300,100))
    row['named_open_spaces']=[{'name_zh':'中央公園','geometry':mapping(box(2000,0,2200,100)),'area_m2':1.},
        {'name_zh':'水岸公園','geometry':mapping(box(2250,0,2260,100)),'area_m2':2.}]
    row['metrics'].update(park_count=6,largest_park_m2=40000.,named_open_space_area_m2=99999.)
    row['checks'].update(largest_park=True,named_park_count=False,open_space_accounting=False)
    return row


def test_finalize_metrics_is_pure_and_remeasures_named_parks():
    original=_metric_row(); before=deepcopy(original)
    result=bd.finalize_brief_metrics(original,{'open_spaces':[{},{}]})
    assert original==before
    assert result['metrics']['legacy_park_count']==6
    assert result['metrics']['legacy_largest_park_m2']==40000.
    assert result['metrics']['park_count']==2
    assert result['metrics']['largest_park_m2']==20000.
    assert result['metrics']['named_open_space_area_m2']==21000.
    assert result['metrics']['unallocated_open_area_m2']==9000.
    assert result['legacy_open_space_checks']['open_space_accounting'] is False
    assert result['checks']['open_space_accounting'] is True
    assert result['status']=='VALID'


@pytest.mark.parametrize('control,code', [
    ('missing_target','brief_named_open_space_count_matches_target'),
    ('overlap','brief_named_open_spaces_nonoverlap'),
    ('outside','brief_named_open_spaces_within_open_reference'),
    ('missing_readback','brief_open_space_readback_available'),
])
def test_finalize_metrics_rejects_missing_or_inconsistent_open_accounting(control,code):
    row=_metric_row(); brief={'open_spaces':[{},{}]}
    if control=='missing_target':brief['open_spaces'].append({})
    elif control=='overlap':row['named_open_spaces'][1]['geometry']=row['named_open_spaces'][0]['geometry']
    elif control=='outside':row['named_open_spaces'][1]['geometry']=mapping(box(2400,0,2410,100))
    else:row.pop('open_space')
    result=bd.finalize_brief_metrics(row,brief)
    assert result['checks'][code] is False
    assert code in result['failure_reasons'] and result['status']=='INVALID'
    if control in ('overlap','outside'):assert result['checks']['open_space_accounting'] is False


def test_fixed_far_denominator_rejects_forged_valid_ratio():
    row=_guard_row(); row['metrics']['far_denominator_m2']=(61440.+68907.884)/.75
    assert row['metrics']['far_denominator_m2'] != 183591.3
    with pytest.raises(ValueError,match='denominator'):bd.brief_drawing_guard(row)
    row['open_space']=mapping(box(2000,0,2300,100));row['named_open_spaces']=[];row['failure_reasons']=[]
    row['metrics']['far']=.75
    result=bd.finalize_brief_metrics(row,{'open_spaces':[]})
    assert result['checks']['brief_user_far_denominator'] is False
