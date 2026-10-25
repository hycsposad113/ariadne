"""Exact facade translations preserve dimensions and all physical constraints."""
from copy import deepcopy
from shapely.geometry import box, LineString, mapping, shape
from urban_design.generation.fabric_plan import _align_actual_public_frontage


def _plan(parent):
    return {'site':mapping(box(-10,-10,60,60)), 'water':mapping(box(-30,-30,-20,-20)),
            'buildable':mapping(parent), 'blocks':[{'id':'block-0','geometry':mapping(parent)}],
            'boundary_parcels':[],
            'roads':[{'id':'street','geometry':mapping(LineString([(0,0),(0,50)])),
                      'properties':{'width_m':4.,'role':'block_edge_street'}}],
            'buildings':[{'id':'new-0','geometry':mapping(box(30,10,40,20)),
                          'properties':{'block_id':'block-0','retained':False,
                                        'mezzanine_geometry':mapping(box(30,10,40,15))}}]}


def test_actual_row_translation_beyond_old_lattice_limit_preserves_geometry():
    plan=_plan(box(2,0,50,50));original=deepcopy(plan)
    result=_align_actual_public_frontage(plan)
    before=shape(original['buildings'][0]['geometry']);after=shape(result['buildings'][0]['geometry'])
    public=shape(result['roads'][0]['geometry']).buffer(2,cap_style=2)
    assert after.distance(public)==2.5
    assert after.area==before.area
    assert shape(result['buildable']).covers(after)
    assert after.intersection(public).area==0
    assert result['public_frontage_alignment_attempts'][0]['status']=='MOVED'
    assert shape(result['buildings'][0]['properties']['mezzanine_geometry']).area==50


def test_parent_cannot_be_enlarged_to_claim_frontage():
    plan=_plan(box(30,0,50,50));original=deepcopy(plan)
    result=_align_actual_public_frontage(plan)
    assert result['buildings']==original['buildings']
    assert result['blocks']==original['blocks']
    assert result['public_frontage_alignment_attempts'][0]['status']=='NO_BOUNDED_FIT'
