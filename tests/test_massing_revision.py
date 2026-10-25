"""J12b measured gates and negative geometry controls."""
import pytest
from shapely.geometry import box, mapping, LineString, Point, shape
from urban_design.generation.massing_revision import (revision_checks, noon_sun_altitude,
    dakpark_plates, facade_segments, streetwall_continuity, named_open_spaces)


def building(floors=4,height=14,reason='',use='Residential',plate=None):
    g=box(0,0,40,12)
    return dict(type_id='block.perimeter',floor_count=floors,height_m=height,
        footprint_area_m2=g.area,low_floor_reason_zh=reason,low_floor_rule_card_ids=['POR-017'] if reason else [],
        floors=[dict(geometry=mapping(plate or g),use=use) for _ in range(floors)],
        facade_segments=[dict(length_m=100,active=False)])


def test_height_first_gates_use_actual_plates_and_no_coverage_lower_bound():
    b=building();checks,metrics=revision_checks([b],dict(far=.75,coverage=.12))
    assert all(checks.values()) and metrics['residential_mixed_area_weighted_floors']==4
    b['floors'][-1]['geometry']=mapping(box(0,0,20,12))
    assert not revision_checks([b],dict(far=.75,coverage=.12))[0]['residential_mixed_average_floors']


@pytest.mark.parametrize('far,coverage,height,key',[(.69,.2,14,'far_range'),(.81,.2,14,'far_range'),(.75,.351,14,'coverage_upper'),(.75,.2,20.1,'height_upper')])
def test_bounds_not_replaced_by_mock_pass(far,coverage,height,key):
    assert not revision_checks([building(height=height)],dict(far=far,coverage=coverage))[0][key]


def test_low_floor_reason_and_card_are_mandatory_even_for_maker():
    b=building(floors=1,height=7,use='Manufacturing')
    assert not revision_checks([b],dict(far=.75,coverage=.2))[0]['low_floor_reasons']
    b.update(low_floor_reason_zh='單層挑高maker',low_floor_rule_card_ids=['POR-001'])
    assert revision_checks([b],dict(far=.75,coverage=.2))[0]['low_floor_reasons']
    assert sum(shape(f['geometry']).area for f in b['floors'])==480


def test_active_frontage_over_half_fails():
    b=building();b['facade_segments']=[dict(length_m=51,active=True),dict(length_m=49,active=False)]
    assert not revision_checks([b],dict(far=.75,coverage=.2))[0]['active_frontage_limit']


def test_noon_altitude_and_retreat_actual_plates():
    assert noon_sun_altitude(declination=-23.44)==pytest.approx(14.66)
    assert noon_sun_altitude()==pytest.approx(38.1)
    g=box(0,0,40,20);park=box(-50,25,100,100)
    plates,screen=dakpark_plates(g,4,park,3.5,3.5)
    assert plates[0].equals(g) and plates[1].equals(g)
    assert plates[2].area<plates[1].area and plates[3].area<plates[2].area
    assert screen['datum_status']=='ASSUMED_PORTFOLIO_P21'
    assert screen['results']['winter_solstice']['park_shadow_area_m2']>=0
    assert sum(p.area for p in plates)<4*g.area


def test_facades_exclude_back_walls_and_court_edges():
    from types import SimpleNamespace
    road=SimpleNamespace(coordinates=[(-10,-5),(60,-5)],modes=['pedestrian'])
    g=box(0,0,40,40).difference(box(12,12,28,28))
    edges=facade_segments(g,[road],[LineString(road.coordinates)])
    assert edges and all(e['active'] for e in edges)
    assert sum(e['length_m'] for e in edges)==pytest.approx(40)
    assert all(shape(e['geometry']).bounds[1]==0 for e in edges)


def test_one_sided_wall_never_counts_as_bilateral():
    road=LineString([(0,0),(100,0)])
    def row(y):return dict(type_id='block.perimeter',facade_segments=[dict(geometry=mapping(LineString([(10,y),(90,y)])))])
    assert streetwall_continuity([road],[row(10)])['streetwall_continuity_ratio']==0
    assert streetwall_continuity([road],[row(10),row(-10)])['streetwall_continuity_ratio']==pytest.approx(.8)
    slab=row(-10);slab['type_id']='building.i_slab'
    assert streetwall_continuity([road],[row(10),slab])['streetwall_continuity_ratio']==0


def test_narrow_remnants_are_reported_not_named_as_usable_parks():
    spaces,remnants=named_open_spaces(box(0,0,100,8),box(200,0,220,100),[])
    assert not spaces and sum(r['area_m2'] for r in remnants)==800
