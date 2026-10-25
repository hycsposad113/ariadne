"""S6 scale and diversity negative controls, independent geometry witnesses."""
from dataclasses import replace
import pytest
from shapely.geometry import box, Polygon
from urban_design.generation.type_registry import generate_block_profile
from urban_design.generation.context_massing import scale_check, context_floors, difference_metrics, S6Rules, ContextEdge
from urban_design.morphology.block_massing import fit_envelopes


def test_small_court_is_rejected_before_figures():
    with pytest.raises(ValueError,match='courtyard'):
        generate_block_profile('building.courtyard_closed',box(0,0,28,28),wing_depth_m=12)


def test_block_court_uses_full_envelope_and_measured_void():
    p=generate_block_profile('block.perimeter',box(0,0,80,64),wing_depth_m=12)
    result=scale_check(p,'Residential')
    assert result['valid']
    assert result['wing_depth_m']==pytest.approx(12)
    assert result['courtyard_width_m']==pytest.approx(40)
    assert p.geometry.area==pytest.approx(80*64-56*40)
    assert p.geometry.envelope.equals(box(0,0,80,64))


def test_streetwall_follows_actual_trapezoid_block_not_small_envelope():
    from urban_design.generation.type_registry import generate_streetwall_profile
    block=Polygon([(0,0),(80,0),(70,70),(10,70)])
    p=generate_streetwall_profile(block,wing_depth_m=12,setback_m=1)
    assert Polygon(p.geometry.exterior).equals(block.buffer(-1,join_style=2))
    assert scale_check(p,'Residential')['valid']


def test_declared_dimensions_cannot_fake_thin_wing_pass():
    p=generate_block_profile('building.courtyard_closed',box(0,0,60,60),wing_depth_m=8)
    r=scale_check(replace(p,wing_depth_m=12),'Residential')
    assert not r['valid']
    assert {'wing_depth','declared_depth_mismatch'}<=set(r['failures'])


@pytest.mark.parametrize('use,depth,valid',[('Residential',10,True),('Mixed',10,False),('Office',12,False),('Manufacturing',14,False),('Manufacturing',24,True)])
def test_depth_matches_use_not_just_type(use,depth,valid):
    p=generate_block_profile('building.industrial_hall',box(0,0,60,depth),wing_depth_m=depth)
    assert scale_check(p,use)['valid']==valid


def test_point_area_upper_bound_and_bar_length_fail_closed():
    p=generate_block_profile('building.point_tower',box(0,0,40,40),wing_depth_m=40)
    assert not scale_check(p,'Residential')['valid']
    p=generate_block_profile('building.i_slab',box(0,0,90,12),wing_depth_m=12)
    assert not scale_check(p,'Residential')['valid']


def test_rowhouse_unit_count_and_frontage_are_real_dimensions():
    p=generate_block_profile('building.rowhouse',box(0,0,63,12),wing_depth_m=12)
    assert p.unit_count==10 and p.unit_frontage_m==pytest.approx(6.3)
    assert scale_check(p,'Residential')['valid']


def test_block_fitting_never_shrinks_to_small_warehouse():
    envelopes=fit_envelopes(box(0,0,64,46),depth_m=12,max_length_m=80)
    assert envelopes and max(p.area for p in envelopes)==pytest.approx(64*12)
    assert fit_envelopes(box(0,0,25,9),depth_m=12)==[]


def test_context_drives_floors_and_strategies_differ():
    assert context_floors('radial',90,10,'Residential',[])==5
    assert context_floors('radial',20,100,'Residential',[])==4
    assert context_floors('green_service',90,10,'Residential',[])==5
    assert context_floors('axial',90,10,'Residential',['dakpark'])==3
    assert context_floors('grid',20,100,'Manufacturing',[])==1


def sample(height=7,use='Residential',offset=0):
    from shapely.geometry import mapping
    g=box(offset,0,offset+40,12)
    return dict(buildings=[dict(height_m=height,footprint_area_m2=g.area,ground_use=use)],features=[dict(geometry=mapping(g),properties=dict(ground_use=use))],open_space=mapping(box(0,0,100,100).difference(g)))


def test_identical_morphology_is_not_distinct_strategy():
    r=difference_metrics(sample(),sample())
    assert not r['distinct'] and not any(r['checks'].values())


def test_three_axes_all_required_for_diversity():
    r=difference_metrics(sample(),sample(height=17.5))
    assert r['checks']['height'] and not r['distinct']
    r=difference_metrics(sample(),sample(height=17.5,use='Public facilities',offset=50))
    assert r['distinct']


def test_unknown_context_cannot_omit_source_or_crs():
    with pytest.raises(ValueError):ContextEdge(kind='dakpark',geometry={'type':'LineString','coordinates':[[0,0],[1,1]]},source_ref='')
    with pytest.raises(ValueError):S6Rules(residential_depth_m=8)


def test_point_fit_has_twenty_metre_complete_plate_not_slab_minimum():
    shapes=fit_envelopes(box(0,0,22,22),depth_m=20,max_length_m=44,min_length_m=20)
    assert shapes
    assert all(g.area>=400 for g in shapes)


def test_rd_coordinate_transform_keeps_independent_courtyard_size():
    from shapely import affinity
    envelope=affinity.translate(affinity.rotate(box(-40,-32,40,32),30),89100,435800)
    profile=generate_block_profile('block.perimeter',envelope,wing_depth_m=12)
    check=scale_check(profile,'Residential')
    assert check['valid']
    assert check['wing_depth_m']==pytest.approx(12,abs=1e-6)
    assert check['courtyard_width_m']==pytest.approx(40,abs=1e-6)


def test_source_syntax_errors_and_hash_mismatch_are_not_replaced():
    from urban_design.generation.context_massing import syntax_inputs
    from urban_design.generation.multimodal_network import NetworkRules
    with pytest.raises(ValueError,match='computed pedestrian'):
        syntax_inputs({'status':'ERROR'},[],NetworkRules(),box(0,0,10,10))
    with pytest.raises(ValueError,match='road hash'):
        syntax_inputs({'status':'COMPUTED','mode':'pedestrian','radius_m':800,'road_input_sha256':'bad'},[],NetworkRules(),box(0,0,10,10))


def test_invalid_building_cannot_be_rendered_even_if_status_says_valid(tmp_path):
    import json,subprocess
    from pathlib import Path
    source=tmp_path/'invalid.json';source.write_text(json.dumps(dict(status='VALID',buildings=[dict(scale=dict(valid=False))])))
    result=subprocess.run(['/Users/jackhsieh/.pyenv/versions/3.12.13/bin/python3','scripts/render_context_massing.py','--input',str(source),'--output',str(tmp_path)],capture_output=True,text=True)
    assert result.returncode!=0
    assert 'figure output prohibited' in result.stderr
    assert not list(tmp_path.glob('*.png'))


def test_shared_motor_baseline_checks_all_source_fields_without_scenario_roads():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('j12_copy_runner',Path(__file__).parents[1]/'scripts/run_context_massing_copy.py')
    runner=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    expected=dict(mode='motor_vehicle',road_input_sha256='fixed-road-hash',site_sha256='site-hash',implementation_sha256='engine-hash')
    runner.validate_motor_baseline(dict(status='COMPUTED',**expected),expected)
    for field in expected:
        with pytest.raises(ValueError,match='mismatch'):
            runner.validate_motor_baseline(dict(status='COMPUTED',**{**expected,field:'drift'}),expected)
    with pytest.raises(ValueError,match='mismatch'):
        runner.validate_motor_baseline(dict(status='ERROR',**expected),expected)


def test_block_capabilities_keep_retained_survey_unknown():
    from urban_design.generation.type_registry import block_scale_capabilities
    entries=block_scale_capabilities()
    assert entries
    retained=[e for e in entries if e.variant_id=='box-in-box-retained-shell']
    assert len(retained)==1 and retained[0].capability_state=='UNKNOWN_INTERNAL_SURVEY'
