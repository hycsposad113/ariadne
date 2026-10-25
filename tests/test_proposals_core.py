from copy import deepcopy
import pytest
from shapely.geometry import box, mapping
from urban_design.judgement.proposals import (
    assemble_proposal_inputs,
    courtyard_solar_geometry,
    proposal_model_input,
    validate_proposal,
    dry_run_proposal,
)


def fixture():
    def building(ident,x,y):
        return {'building_id':ident,'block_id':'block','provenance':'FORMAL_DRAFT','first_floor_height_m':4,'standard_floor_height_m':3,'floors':[{'floor_id':f'{ident}-{i}','level':i,'geometry':mapping(box(x,y,x+20,y+10))} for i in range(4)]}
    draft={'id':'formal-draft-test','revision':2,'parameters':{'editable_buildings':[building('south',0,0),building('north',0,30)]}}
    bundle=assemble_proposal_inputs({'id':'jc-test','status':'VALIDATED','card':{'observations':[{'id':'obs-1','text':'中庭冬季日照需要局部修正以測試影響'}]}},draft,courtyards=[{'courtyard_id':'court','block_id':'block','geometry':mapping(box(0,12,20,28))}])
    proposal={'proposal_id':'program-id','responds_to':{'card_id':'jc-test','response_ids':[]},'summary':'我建議局部修正','operations':[{'op':'REMOVE_TOP_FLOOR','building_ids':['south'],'floors':1},{'op':'RERUN','analyses':['E1','UTCI']}],'rationale':['根據 obs-1 進行局部修正'],'expected_effects':['可能增加中庭日照'],'trade_offs':['樓地板減少'],'risks':['效果待驗證'],'not_simulated':[],'questions_for_designer':['您是否接受此取捨？']}
    return bundle,proposal


def test_assembly_courtyards_and_isolation():
    b,p=fixture(); assert b['courtyards'][0]['south_building_ids']==['south']; assert b['courtyards'][0]['north_building_ids']==['north']
    original=deepcopy(b); r=dry_run_proposal(p,b); assert r['valid'],r; assert r['gfa_after_m2']==1400;assert r['below_gfa_floor'];assert b==original

@pytest.mark.parametrize('op',[{'op':'SETBACK_UPPER','building_ids':['south'],'metres':1},{'op':'ADD_FLOOR','building_ids':['south'],'floors':2},{'op':'MOVE','building_id':'south','dx_m':1,'dy_m':0}])
def test_operations(op):
    b,p=fixture();p['operations'][0]=op;r=dry_run_proposal(p,b);assert r['valid'],r
    assert r['editable_buildings'][0]['block_id']=='block'
    if op['op']=='SETBACK_UPPER':
        floors=r['editable_buildings'][0]['floors'];from shapely.geometry import shape
        assert [shape(f['geometry']).area for f in floors]==[200,200,144,144]

@pytest.mark.parametrize('change',[lambda p:p['operations'][0].update(floors=3),lambda p:p['operations'][0].update(floors=True),lambda p:p['operations'][0].update(building_ids=['preserved']),lambda p:p['operations'].pop(),lambda p:p.update(summary='保證改善'),lambda p:p.update(rationale=['unrelated rationale']),lambda p:p.update(expected_effects=['增加 10 小時'])])
def test_rejections(change):
    b,p=fixture();change(p);assert validate_proposal(p,b)


def test_height_and_floor_limits():
    b,p=fixture();p['operations'][0]={'op':'ADD_FLOOR','building_ids':['south'],'floors':2};p['operations'].insert(1,deepcopy(p['operations'][0])); assert not dry_run_proposal(p,b)['valid']
    b,p=fixture();p['operations'].insert(1,{'op':'REMOVE_TOP_FLOOR','building_ids':['south'],'floors':2});p['operations'].insert(2,{'op':'REMOVE_TOP_FLOOR','building_ids':['south'],'floors':1});assert not dry_run_proposal(p,b)['valid']


def test_invalid_card_and_formal_provenance():
    b,p=fixture()
    with pytest.raises(ValueError):assemble_proposal_inputs({'status':'FAILED'},b['draft'])
    draft=deepcopy(b['draft']);draft['parameters']['editable_buildings'][0]['provenance']='FIXTURE_ONLY'
    with pytest.raises(ValueError):assemble_proposal_inputs({'status':'VALIDATED'},draft)


def test_geometry_groups_overlap_and_bounds():
    b,p=fixture();p['operations']=[deepcopy(p['operations'][0]) for _ in range(4)]+[p['operations'][-1]]
    assert any('groups' in e for e in validate_proposal(p,b))
    b,p=fixture();b['draft']['parameters']['preserved_buildings']=[{'geometry':mapping(box(20,0,30,10))}]
    p['operations'][0]={'op':'MOVE','building_id':'south','dx_m':1,'dy_m':0}
    assert 'preserved building overlap' in dry_run_proposal(p,b)['errors']
    b,p=fixture();b['draft']['parameters']['design_area']=mapping(box(0,0,20,40));p['operations'][0]={'op':'MOVE','building_id':'south','dx_m':-1,'dy_m':0}
    assert 'outside design area' in dry_run_proposal(p,b)['errors']


def test_rationale_excerpt_and_no_extra_params():
    b,p=fixture();p['rationale']=['中庭冬季日照需要局部修正'];assert not validate_proposal(p,b)
    p['operations'][0]['arbitrary']='no';assert validate_proposal(p,b)


def test_active_building_overlay_retains_metadata():
    b,p=fixture();draft=deepcopy(b['draft']);active=deepcopy(draft['parameters']['editable_buildings'][0]);active['floors'].pop();active.pop('block_id');draft['parameters']['active_buildings']={'south':active}
    bundle=assemble_proposal_inputs({'id':'jc-test','status':'VALIDATED'},draft)
    assert bundle['editable_buildings'][0]['floors']==3
    assert bundle['editable_buildings'][0]['block_id']=='block'


def test_real_courtyard_relationship_fixture_is_reproducible():
    import hashlib,json
    from pathlib import Path
    from urban_design.judgement.proposals import courtyard_relationships
    root=Path(__file__).resolve().parents[1]
    saved=json.loads((root/'knowledge/judgement/eval/proposals/harbour-courtyard-relationships.json').read_text())
    raw=(root/saved['source']).read_bytes();assert hashlib.sha256(raw).hexdigest()==saved['sha256']
    plan=json.loads(raw)
    current=courtyard_relationships(plan['courtyards'],[b for b in plan['buildings'] if not b['properties']['retained']])
    assert [{k:v for k,v in item.items() if k!='solar_geometry'} for item in current]==saved['courtyards']
    assert all(item['solar_geometry']['depth_basis']=='N-S scanline median' for item in current)
    assert len(current)==7 and all(c['south_building_ids'] for c in current)


@pytest.mark.parametrize('text',['approved','approval','best','guaranteed improvement','formally accepted','HumanDecision','決策成立'])
def test_common_forbidden_language(text):
    b,p=fixture();p['summary']=text;assert 'forbidden language' in validate_proposal(p,b)


def test_preserved_plan_feature_enforces_overlap_and_excludes_editability():
    b,p=fixture();feature={'type':'Feature','id':'south','properties':{'id':'south','retained':True,'block_id':'block'},'geometry':mapping(box(0,0,20,10))}
    assembled=assemble_proposal_inputs({'id':'jc-test','status':'VALIDATED'},b['draft'],buildings_metadata=[feature])
    assert [item['building_id'] for item in assembled['editable_buildings']]==['north']
    assert len(assembled['draft']['parameters']['preserved_buildings'])==1
    assert 'unknown or preserved building' in validate_proposal(p,assembled)


def test_dryrun_limitations_are_explicit():
    b,p=fixture();result=dry_run_proposal(p,b);assert result['valid'];assert len(result['limitations'])==3


def test_courtyard_distance_uses_exact_exterior_not_axis_aligned_bbox():
    from urban_design.judgement.proposals import courtyard_relationships
    from shapely.geometry import Polygon
    court={'courtyard_id':'diagonal','block_id':'b','geometry':mapping(Polygon([(0,50),(50,100),(100,50),(50,0)]))}
    building={'building_id':'outside','block_id':'b','floors':[{'geometry':mapping(box(0,0,2,2))}]}
    assert courtyard_relationships([court],[building])[0]['south_building_ids']==[]


def test_expected_effects_allow_identifiers_but_not_values():
    b,p=fixture()
    p['expected_effects']=['局部降低 south 可能增加冬季日照進入 court 的機會，待 E1 重算確認；e1.harbour.courtyard.winter.mean_h 方向待查。']
    assert 'expected_effects must be qualitative' not in validate_proposal(p,b)
    p['expected_effects']=['E1 重算後中庭日照可增加 0.5 小時']
    assert 'expected_effects must be qualitative' in validate_proposal(p,b)


def test_courtyard_solar_geometry_uses_winter_and_equinox_noon_altitudes():
    from shapely.geometry import mapping, box
    courtyard = {'courtyard_id': 'court-40', 'south_building_ids': ['south'],
                 'clear_width_m': 40, 'geometry': mapping(box(0, 0, 40, 40))}
    south = {'building_id': 'south', 'height_m': 18}
    result = courtyard_solar_geometry(courtyard, [south])
    assert result['winter_noon_sun_altitude_deg'] == pytest.approx(14.66, abs=0.01)
    assert result['equinox_noon_sun_altitude_deg'] == pytest.approx(38.10, abs=0.01)
    assert result['depth_along_sun_m'] == pytest.approx(40)
    assert result['depth_basis'] == 'N-S scanline median'
    assert result['h_north_edge_m'] == pytest.approx(10.46, abs=0.02)
    assert result['floors_to_remove_for_north_edge'] == 3
    assert result['feasible_within_catalogue'] is False


def test_proposal_input_assembly_attaches_solar_geometry_reference_and_data_gaps():
    from shapely.geometry import box, mapping
    source = {'id': 'court-40', 'courtyard_id': 'court-40', 'block_id': 'block',
              'clear_width_m': 40, 'geometry': mapping(box(0, 12, 20, 28))}
    draft = {'revision': 1, 'parameters': {'editable_buildings': [
        {'building_id': 'south', 'block_id': 'block', 'provenance': 'FORMAL_DRAFT',
         'first_floor_height_m': 4, 'standard_floor_height_m': 3.5,
         'floors': [{'floor_id': f'south-{i}', 'level': i, 'geometry': mapping(box(0, 0, 20, 10))}
                    for i in range(5)]}]}}
    bundle = assemble_proposal_inputs(
        {'id': 'jc-test', 'status': 'VALIDATED'}, draft, courtyards=[source],
        data_gaps=['DATA_GAP:e1.harbour.courtyard_breakdown'],
    )
    assert bundle['solar_reference'] == {
        'latitude_deg': 51.9, 'winter_noon_sun_altitude_deg': 14.66,
        'equinox_noon_sun_altitude_deg': 38.1, 'first_floor_height_m': 4.0,
        'standard_floor_height_m': 3.5}
    assert bundle['courtyards'][0]['solar_geometry']['winter_mean_h'] is None
    assert bundle['courtyards'][0]['solar_geometry']['south_edge_height_max_m'] == pytest.approx(18)
    assert 'DATA_GAP:e1.harbour.courtyard_breakdown' in bundle['data_gaps']


def test_courtyard_solar_geometry_marks_42m_depth_feasible_within_catalogue():
    from shapely.geometry import mapping, box
    courtyard = {'courtyard_id': 'court-42', 'south_building_ids': ['south'],
                 'clear_width_m': 42.6, 'geometry': mapping(box(0, 0, 24, 42.6))}
    result = courtyard_solar_geometry(courtyard, [{'building_id': 'south', 'height_m': 18}])
    assert result['depth_along_sun_m'] == pytest.approx(42.6)
    assert result['h_north_edge_m'] == pytest.approx(11.16, abs=0.02)
    assert result['floors_to_remove_for_north_edge'] == 2
    assert result['feasible_within_catalogue'] is True


def test_courtyard_solar_geometry_falls_back_to_clear_width_and_reports_height_statistics():
    courtyard = {'courtyard_id': 'approx', 'clear_width_m': 42.6,
                 'south_building_ids': ['a', 'b']}
    result = courtyard_solar_geometry(courtyard, [
        {'building_id': 'a', 'height_m': 14.5}, {'building_id': 'b', 'height_m': 18},
    ])
    assert result['depth_along_sun_m'] == pytest.approx(42.6)
    assert result['depth_basis'] == 'clear_width_m (approx.)'
    assert result['south_edge_height_max_m'] == 18
    assert result['south_edge_height_median_m'] == pytest.approx(16.25)
    assert result['h_half_m'] == pytest.approx(5.58, abs=0.02)
    assert result['h_north_edge_equinox_m'] == pytest.approx(33.40, abs=0.03)


def test_courtyard_solar_geometry_returns_null_when_first_floor_cannot_reach_north_edge():
    from shapely.geometry import box, mapping
    courtyard = {'courtyard_id': 'too-shallow', 'south_building_ids': ['south'],
                 'geometry': mapping(box(0, 0, 12, 8))}
    result = courtyard_solar_geometry(courtyard, [{'building_id': 'south', 'height_m': 18}])
    assert result['floors_to_remove_for_north_edge'] is None
    assert result['feasible_within_catalogue'] is False


def test_courtyard_solar_geometry_rotated_rectangle_uses_scanline_median():
    import statistics
    from shapely.affinity import rotate
    from shapely.geometry import LineString, box, mapping
    geometry = rotate(box(-40, -10, 40, 10), 30, origin=(0, 0))
    courtyard = {'courtyard_id': 'rotated', 'south_building_ids': [],
                 'clear_width_m': 20, 'geometry': mapping(geometry)}
    minx, miny, maxx, maxy = geometry.bounds
    lengths = [geometry.intersection(LineString([(x, miny - 1), (x, maxy + 1)])).length
               for x in _scanline_x_values(minx, maxx)]
    result = courtyard_solar_geometry(courtyard, [])
    assert result['depth_along_sun_m'] == pytest.approx(statistics.median(lengths), abs=0.01)
    assert result['depth_along_sun_m'] != pytest.approx(maxy - miny, abs=0.1)


def _scanline_x_values(minx, maxx):
    x = minx + 0.5
    values = []
    while x < maxx:
        values.append(x)
        x += 1.0
    return values


def test_dry_run_warns_when_claimed_winter_sun_still_misses_north_edge():
    bundle, proposal = fixture()
    bundle['courtyards'][0]['solar_geometry'] = {'h_north_edge_m': 4.2}
    proposal['rationale'] = ['obs-1 支持改善中庭冬至日照。']
    proposal['expected_effects'] = ['可能讓中庭冬季多受日照。']
    result = dry_run_proposal(proposal, bundle)
    assert result['valid'] is True
    assert result['solar_access_check']['claims_courtyard_winter_sun'] is True
    assert result['solar_access_check']['courtyards'][0]['south_height_after_m'] == pytest.approx(10)
    assert result['solar_access_check']['courtyards'][0]['reaches_north_edge'] is False
    assert result['solar_access_check']['warning'] is True


def test_dry_run_does_not_warn_when_two_floors_reach_42m_courtyard_north_edge():
    bundle, proposal = fixture()
    source = bundle['draft']['parameters']['editable_buildings'][0]
    source['first_floor_height_m'] = 4.0
    source['standard_floor_height_m'] = 3.5
    source['floors'] = [{'floor_id': f'south-{i}', 'level': i,
                         'geometry': source['floors'][0]['geometry']} for i in range(5)]
    bundle['courtyards'][0]['solar_geometry'] = {'h_north_edge_m': 11.16}
    proposal['operations'][0]['floors'] = 2
    proposal['rationale'] = ['obs-1 支持改善中庭冬至日照。']
    proposal['expected_effects'] = ['可能讓中庭冬季多受日照。']
    result = dry_run_proposal(proposal, bundle)
    assert result['valid'] is True
    assert result['solar_access_check']['courtyards'][0]['south_height_after_m'] == pytest.approx(11)
    assert result['solar_access_check']['courtyards'][0]['reaches_north_edge'] is True
    assert result['solar_access_check']['warning'] is False


def test_dry_run_solar_warning_requires_winter_courtyard_claim():
    bundle, proposal = fixture()
    bundle['courtyards'][0]['solar_geometry'] = {'h_north_edge_m': 4.2}
    proposal['rationale'] = ['obs-1 支持局部調整。']
    proposal['expected_effects'] = ['可能改善量體關係。']
    result = dry_run_proposal(proposal, bundle)
    assert result['valid'] is True
    assert result['solar_access_check']['claims_courtyard_winter_sun'] is False
    assert result['solar_access_check']['warning'] is False


def test_dry_run_solar_warning_stays_false_when_no_courtyard_south_building_is_modified():
    bundle, proposal = fixture()
    bundle['courtyards'][0]['solar_geometry'] = {'h_north_edge_m': 4.2}
    proposal['operations'][0]['building_ids'] = ['north']
    proposal['rationale'] = ['obs-1 支持改善中庭冬至日照。']
    proposal['expected_effects'] = ['可能讓中庭冬季多受日照。']
    result = dry_run_proposal(proposal, bundle)
    assert result['valid'] is True
    assert result['solar_access_check']['claims_courtyard_winter_sun'] is True
    assert result['solar_access_check']['courtyards'] == []
    assert result['solar_access_check']['warning'] is False


def test_model_input_projection_removes_floor_geometry_and_reports_size_drop():
    from urban_design.judgement.core import canonical
    from shapely.geometry import box, mapping
    geometry = mapping(box(0, 0, 20, 10))
    bundle = {'card_id': 'card', 'round': 1, 'card': {'judgement': 'text'}, 'responses': [],
              'draft_revision': 1,
              'editable_buildings': [{'building_id': f'b-{i}', 'block_id': 'block',
                  'height_m': 18, 'gfa_m2': 1000, 'footprint_area_m2': 200,
                  'centroid': [10, 5], 'floors': [{'geometry': geometry} for _ in range(5)]}
                  for i in range(253)],
              'courtyards': [{'courtyard_id': 'court', 'solar_geometry': {'depth_along_sun_m': 42.6}}],
              'solar_reference': {'latitude_deg': 51.9}, 'constraints': {}, 'operation_catalog': [],
              'draft': {'parameters': {'editable_buildings': [{'floors': [geometry] * 5} for _ in range(253)]}}}
    before = len(canonical({**bundle, 'input': {k: v for k, v in bundle.items() if k != 'draft'}}).encode())
    projected = proposal_model_input(bundle)
    after = len(canonical(projected).encode())
    assert 'draft' not in projected
    assert set(projected['editable_buildings'][0]) == {
        'building_id', 'block_id', 'floors', 'height_m', 'gfa_m2', 'footprint_area_m2', 'centroid'}
    assert projected['editable_buildings'][0]['floors'] == 5
    assert after < before


def test_dry_run_reports_local_sun_pocket_when_only_part_of_south_edge_is_lowered():
    bundle, proposal = fixture()
    bundle['courtyards'][0]['south_building_ids'] = ['south', 'north']
    bundle['courtyards'][0]['solar_geometry'] = {'h_north_edge_m': 8.0}
    proposal['operations'][0]['floors'] = 2
    proposal['rationale'] = ['obs-1 支持改善中庭冬至日照。']
    proposal['expected_effects'] = ['可能讓中庭冬季多受日照。']
    check = dry_run_proposal(proposal, bundle)['solar_access_check']
    court = check['courtyards'][0]
    assert court['reaches_north_edge'] is False
    assert court['local_sun_pockets'] == [{'building_id': 'south', 'height_after_m': 7.0, 'frontage_m': 20.0,
                                           'frontage_basis': 'extent along courtyard south edge'}]
    bundle['courtyards'][0].pop('south_edge_facing_azimuth_deg', None)
    court = dry_run_proposal(proposal, bundle)['solar_access_check']['courtyards'][0]
    assert court['local_sun_pockets'][0]['frontage_m'] == 10.0
    assert court['local_sun_pockets'][0]['frontage_basis'].startswith('short side')
    assert check['local_only'] is True and check['warning'] is True
