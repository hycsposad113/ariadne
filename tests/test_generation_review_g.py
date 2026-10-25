"""Formal regressions from Claude reviewG p_shape/p_hash3/p_nz/p_contract."""
import pytest
from pydantic import ValidationError
from shapely.geometry import box, Polygon
from urban_design.generation.type_registry import generate_profile_geometry, InvalidMorphologyParameters, build_type_registry
from urban_design.generation.hashing import semantic_digest, canonical_geometry_payload
from urban_design.generation.contracts import AssumptionSpec, MethodProvenance, LocalWorldTransform, GenerationContext

H = dict(width_m=80, depth_m=60, left_wing_width_m=10, right_wing_width_m=10, thickness_m=10)
E = dict(width_m=44, depth_m=60, spine_thickness_m=10, wing_thickness_m=8)
C = dict(spine_length_m=60, spine_thickness_m=10, wing_depth_m=34, wing_thickness_m=8, wing_count=3, gap_m=12)

def gen(kind, params, obstacles=()):
    return generate_profile_geometry(kind, box(0,0,100,80), params, crs='EPSG:28992', coordinate_unit='m', preserved_obstacles=obstacles)

@pytest.mark.parametrize('width', [1e-9, 1e-3, 2.99])
@pytest.mark.parametrize('kind,params,obstacle', [
    ('building.h_plan', H, lambda w: box(40,35,60,45-w)),
    ('building.e_plan', E, lambda w: box(38,15,73,24-w)),
    ('building.comb', C, lambda w: box(25,28,34-w,63)),
])
def test_retained_slivers_reject(kind, params, obstacle, width):
    with pytest.raises(InvalidMorphologyParameters):
        gen(kind,params,[obstacle(width)])

@pytest.mark.parametrize('kind,params,obstacle', [
    ('building.h_plan', H, box(40,35,60,41.99)),
    ('building.e_plan', E, box(38,15,73,20.99)),
    ('building.comb', C, box(25,28,30.99,63)),
])
def test_retained_width_above_engineering_threshold_hashes(kind,params,obstacle):
    result = gen(kind,params,[obstacle])
    assert canonical_geometry_payload(result.geometry)
    assert semantic_digest(result).startswith('sha256:')

@pytest.mark.parametrize('kind,params', [('building.h_plan',H),('building.e_plan',E),('building.comb',C)])
@pytest.mark.parametrize('rotation', [0,90])
def test_every_returned_profile_hashes(kind,params,rotation):
    result=generate_profile_geometry(kind,box(-100,-100,200,200),{**params,'rotation_deg':rotation},crs='EPSG:28992',coordinate_unit='m')
    assert canonical_geometry_payload(result.geometry)
    assert semantic_digest(result)

def test_negative_zero_equal_values_have_equal_hashes():
    assert semantic_digest(box(-1,-1,0,0)) == semantic_digest(Polygon([(-1,-1),(-0.0,-1),(-0.0,-0.0),(-1,-0.0)]))
    assert semantic_digest({'x':[-0.0]}) == semantic_digest({'x':[0.0]})
    a=LocalWorldTransform(forward=[[0,1,-200],[-1,0,100]],inverse=[[0,-1,100],[1,0,200]])
    b=LocalWorldTransform(forward=[[-0.0,1,-200],[-1,-0.0,100]],inverse=[[-0.0,-1,100],[1,-0.0,200]])
    assert a == b
    assert semantic_digest(a) == semantic_digest(b)

REF=dict(id='parameter',sha256='sha256:'+'a'*64,kind='fixture')
@pytest.mark.parametrize('model,fields', [(AssumptionSpec,dict(id='parameter',statement='s')),(MethodProvenance,dict(method_id='m',version='1',description='d'))])
@pytest.mark.parametrize('kind',['PROJECT_DATA','HUMAN_DECISION'])
def test_source_kinds_require_refs(model,fields,kind):
    if kind not in {x.value for x in model.model_fields['source_kind'].annotation}:
        return
    with pytest.raises(ValidationError):
        model(**fields,source_kind=kind)
    assert model(**fields,source_kind=kind,source_refs=[REF])

def test_context_parameter_keys_require_basis():
    base=dict(workspace_ref=REF,analysis_ref=REF,brief_ref=REF,crs='EPSG:28992',coordinate_unit='m',seed=3,generation_class='EXPLORATORY',method_parameters={'parameter':3})
    with pytest.raises(ValidationError,match='assumption or source'):
        GenerationContext(**base)
    assert GenerationContext(**base,source_refs=[REF])
    assert GenerationContext(**base,assumptions=[dict(id='parameter',statement='executor engineering assumption',source_kind='EXPLICIT_ASSUMPTION')])

def test_capability_envelope_nature_is_serialized():
    for kind in ('building.h_plan','building.e_plan','building.comb'):
        payload=build_type_registry().entries[kind].model_dump()
        assert payload['range_basis']=='EDITORIAL_ENVELOPE_V1'
        assert payload['not_regulatory'] is True
        assert 'executor-defined' in payload['range_source']

@pytest.mark.parametrize('kind,params', [('building.h_plan',H),('building.e_plan',E),('building.comb',C)])
def test_non_axis_rotation_returns_hashable_geometry_or_fails_closed(kind,params):
    # Existing independently rotated feature boundaries may fail exact topology.
    try:
        result=generate_profile_geometry(kind,box(-100,-100,200,200),{**params,'rotation_deg':37.3},crs='EPSG:28992',coordinate_unit='m')
    except InvalidMorphologyParameters as error:
        assert 'semantic feature' in str(error) or 'hashable' in str(error) or 'retained width' in str(error)
    else:
        assert canonical_geometry_payload(result.geometry)
        assert semantic_digest(result)
