from copy import deepcopy
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union
from urban_design.generation.fabric_finish_ne import finish_ne


def _plan():
    properties = {'building_type':'building.point_array','floors':3,'max_floors':5,'first_floor_height_m':4.,'standard_floor_height_m':3.5,'height_m':11.,'retained':False}
    return {'fabric_id':'fabric.landscape_figure', 'orientation_deg':90,
            'waterfront_band':mapping(box(0,0,10,100)), 'site':mapping(box(0,0,100,100)), 'water':mapping(box(-20,-20,-10,-10)),
            'blocks':[{'id':'block-0','geometry':mapping(box(70,10,95,80))}],
            'boundary_parcels':[{'id':'parcel-0','geometry':mapping(box(60,80,80,100))}],
            'land_use':[{'id':'use-0','geometry':mapping(box(60,80,80,100)), 'properties':{'category':'blocks'}}],
            'roads':[], 'buildings':[{'id':'new-0','geometry':mapping(box(65,85,75,95)), 'properties':{**properties,'parcel_id':'parcel-0'}},
                                    {'id':'new-1','geometry':mapping(box(75,20,85,40)), 'properties':{**properties,'block_id':'block-0'}}]}


def test_cleanup_preserves_input_and_cover_and_restores_gfa():
    original = _plan()
    snapshot = deepcopy(original)
    result = finish_ne(original)
    assert original == snapshot
    assert [b['id'] for b in result['buildings']] == ['new-1']
    assert result['boundary_parcels'] == []
    assert result['rejected_ne_geometry'][0]['geometry'] == original['buildings'][0]['geometry']
    before = unary_union([shape(r['geometry']) for r in original['land_use']])
    after = unary_union([shape(r['geometry']) for r in result['land_use']])
    assert before.symmetric_difference(after).area == 0
    assert result['buildings'][0]['properties']['floors'] == 4
    assert result['ne_finish_evidence']['unreplaced_gfa_m2'] == 100
    assert result['roads'] == original['roads']


def test_unavailable_floor_capacity_is_recorded_without_invention():
    plan = _plan()
    plan['buildings'][1]['properties']['max_floors'] = 3
    result = finish_ne(plan)
    assert result['ne_finish_evidence']['unreplaced_gfa_m2'] == 300
    assert result['buildings'][0]['properties']['floors'] == 3


def test_nonwaterfront_plan_is_outside_scope():
    plan = _plan()
    del plan["waterfront_band"]
    assert finish_ne(plan) == plan
