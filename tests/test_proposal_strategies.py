"""Offline strategy expansion, quantities, validation and immutable-input checks."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from shapely.geometry import box, mapping, shape
from urban_design.judgement.proposals import assemble_proposal_inputs, dry_run_proposal, validate_proposal


def building(ident, x, y, floors=5, block='block', width=20, depth=13):
    return {'building_id':ident,'block_id':block,'provenance':'FORMAL_DRAFT',
            'first_floor_height_m':4,'standard_floor_height_m':3.5,
            'floors':[{'floor_id':f'{ident}-{i}','level':i,'geometry':mapping(box(x,y,x+width,y+depth))} for i in range(floors)]}


def proposal(ops):
    return {'proposal_id':'test-strategy','responds_to':{'card_id':'card','response_ids':[]},
            'summary':'我調整中庭量體以測試冬季日照','operations':ops+[{'op':'RERUN','analyses':['E1','UTCI']}],
            'rationale':['根據 obs-1 調整'],'expected_effects':['可能增加中庭冬季日照，需看重算'],
            'trade_offs':['removed_gfa_m2、added_gfa_m2 與 gfa_shortfall_m2 需比較；移入北側增加街道冬季陰影，GFA 下限由你取捨'],
            'risks':['效果待重算'],'not_simulated':[],'questions_for_designer':['你接受量體取捨嗎？']}


def bundle():
    return assemble_proposal_inputs({'id':'card','status':'VALIDATED','card':{'observations':[{'id':'obs-1'}]}},
        {'revision':1,'parameters':{'editable_buildings':[building('s',0,0),building('n',0,60,2),building('e',25,0,2)]}},
        courtyards=[{'courtyard_id':'c','block_id':'block','geometry':mapping(box(0,13,20,60))}])


def envelope(ids=['c'], **kwargs):
    return {'op':'SOLAR_ENVELOPE','courtyard_ids':ids,'target':'north_edge','redistribute':True,**kwargs}


def test_envelope_exact_quantities_and_isolation():
    b=bundle(); original=deepcopy(b); result=dry_run_proposal(proposal([envelope()]),b)
    assert result['valid'], result['errors']; assert b==original
    report=result['strategy_report'][0]
    assert report['removed_gfa_m2']==520
    assert report['added_gfa_m2']==520
    assert report['gfa_shortfall_m2']==0
    assert report['added_buildings'][0]['building_id']=='n'
    assert report['added_buildings'][0]['is_north_of_courtyard']
    assert result['solar_access_check']['courtyards'][0]['reaches_north_edge']
    assert all(len(item['floors'])>=1 for item in result['editable_buildings'])


def test_south_of_any_courtyard_forbids_redistribution_and_never_overshoots():
    b=bundle(); b['courtyards'].append({'courtyard_id':'other','block_id':'block','south_building_ids':['n'], 'solar_geometry':{'h_north_edge_m':30}})
    # Remaining eligible plate is larger than the removed quantity: it must be skipped.
    b['draft']['parameters']['editable_buildings'][2]=building('e',25,0,2,width=100)
    r=dry_run_proposal(proposal([envelope()]),b); assert r['valid'],r['errors']
    report=r['strategy_report'][0]; assert report['added_gfa_m2']==0; assert report['gfa_shortfall_m2']==520


def test_unreachable_keeps_ground_floor():
    b=bundle(); b['courtyards'][0]['solar_geometry']['h_north_edge_m']=2
    r=dry_run_proposal(proposal([envelope(redistribute=False)]),b); assert r['valid'],r['errors']
    assert len(r['editable_buildings'][0]['floors'])==1
    assert r['strategy_report'][0]['envelope_unreachable'][0]['status']=='ENVELOPE_UNREACHABLE'
    assert not r['solar_access_check']['courtyards'][0]['reaches_north_edge']


@pytest.mark.parametrize('change',[lambda p:p['operations'][0].update(courtyard_ids=['unknown']),lambda p:p['operations'][0].update(target='unknown'),lambda p:p['operations'][-1].update(analyses=['UTCI']),lambda p:p['operations'].insert(0,envelope()),lambda p:p['operations'].extend([{'op':'MOVE','building_id':'s','dx_m':0,'dy_m':0}]*2)])
def test_validation_groups_and_fields(change):
    b=bundle(); p=proposal([envelope(),envelope()]); change(p); assert validate_proposal(p,b)


def test_unknown_solar_rejected():
    b=bundle(); b['courtyards'][0]['solar_geometry']={}
    assert validate_proposal(proposal([envelope()]),b)


@pytest.mark.parametrize('depth',[9,13,10.5,True])
def test_invalid_depth(depth):
    assert validate_proposal(proposal([{'op':'COURTYARD_WING_DEPTH','courtyard_id':'c','side':'south','depth_m':depth}]),bundle())


def test_wing_depth_all_floors_and_solar_recomputed():
    b=bundle(); old=b['courtyards'][0]['solar_geometry']['h_north_edge_m']
    r=dry_run_proposal(proposal([{'op':'COURTYARD_WING_DEPTH','courtyard_id':'c','side':'south','depth_m':10}]),b)
    assert r['valid'],r['errors']
    assert all(shape(f['geometry']).bounds[3]-shape(f['geometry']).bounds[1]==10 for f in r['editable_buildings'][0]['floors'])
    assert r['strategy_report'][0]['h_north_edge_m']>old
    assert r['strategy_report'][0]['removed_gfa_m2']==300


def test_expanded_building_limit():
    b=bundle(); source=b['draft']['parameters']['editable_buildings']; source[:]=[building(f's{i}',i*30,0) for i in range(81)]
    b['editable_buildings']=[{'building_id':x['building_id'],'block_id':'block'} for x in source]
    b['courtyards'][0]['south_building_ids']=[x['building_id'] for x in source]
    r=dry_run_proposal(proposal([envelope(redistribute=False)]),b)
    assert not r['valid']; assert 'maximum 80 affected buildings after strategy expansion' in r['errors']


def harbour_bundle():
    path=Path(__file__).parents[1]/'artifacts/fab1/run-8/harbour_grain-plan.json'
    if not path.exists(): pytest.skip('preserved harbour plan unavailable')
    plan=json.loads(path.read_text())
    bs=[]
    for item in plan['buildings']:
        props=item['properties']
        if props['retained']: continue
        b={'building_id':item['id'],'block_id':props['block_id'],'provenance':'FORMAL_DRAFT',
           'first_floor_height_m':props['first_floor_height_m'],'standard_floor_height_m':props['standard_floor_height_m'],
           'floors':[{'floor_id':f"{item['id']}-{i}",'level':i,'geometry':item['geometry']} for i in range(props['floors'])]}
        bs.append(b)
    return assemble_proposal_inputs({'id':'card','status':'VALIDATED','card':{'observations':[{'id':'obs-1'}]}},
        {'revision':1,'parameters':{'editable_buildings':bs}},courtyards=plan['courtyards'])


def test_real_harbour_courtyards_zero_and_one(capsys):
    r=dry_run_proposal(proposal([envelope(['courtyard-0','courtyard-1'])]),harbour_bundle())
    assert r['valid'],r['errors']
    report=r['strategy_report'][0]
    assert report['removed_gfa_m2']>0; assert report['added_gfa_m2']<=report['removed_gfa_m2']
    assert {c['courtyard_id'] for c in r['solar_access_check']['courtyards']} >= {'courtyard-0','courtyard-1'}
    assert all(c['reaches_north_edge'] for c in r['solar_access_check']['courtyards'] if c['courtyard_id'] in ['courtyard-0','courtyard-1'])


def test_requested_three_south_three_north_h112():
    bs=[building(f's{i}',i*30,0,5) for i in range(3)]+[building(f'n{i}',i*30,70,3) for i in range(3)]
    b=assemble_proposal_inputs({'id':'card','status':'VALIDATED','card':{'id':'obs-1'}},
        {'parameters':{'editable_buildings':bs}},courtyards=[{'courtyard_id':'c','block_id':'block','geometry':mapping(box(0,13,80,70))}])
    b['courtyards'][0]['south_building_ids']=['s0','s1','s2']; b['courtyards'][0]['north_building_ids']=['n0','n1','n2']
    b['courtyards'][0]['solar_geometry']['h_north_edge_m']=11.2
    r=dry_run_proposal(proposal([envelope()]),b); assert r['valid'],r['errors']
    report=r['strategy_report'][0]
    assert [x['floors_removed'] for x in report['removed']]==[2,2,2]
    assert [x['floors_added'] for x in report['added']]==[2,2,2]
    assert report['removed_gfa_m2']==report['added_gfa_m2']==1560
    assert report['gfa_shortfall_m2']==0


def test_solar_trade_off_field_references_required():
    p=proposal([envelope()]); p['trade_offs']=['樓地板下降']
    assert any('trade_offs' in e for e in validate_proposal(p,bundle()))


def test_explicit_south_add_cannot_bypass_solar_redistribution():
    p=proposal([envelope(),{'op':'ADD_FLOOR','building_ids':['s'],'floors':1}])
    assert 'solar redistribution cannot add floors on any courtyard south side' in validate_proposal(p,bundle())


def test_final_solar_check_reflects_later_edit():
    p=proposal([envelope(),{'op':'MOVE','building_id':'n','dx_m':0,'dy_m':0}])
    r=dry_run_proposal(p,bundle()); assert r['valid'],r['errors']
    assert r['strategy_report'][0]['envelope_success']


def test_redistribute_false_reports_entire_removed_quantity_as_shortfall():
    r = dry_run_proposal(proposal([envelope(redistribute=False)]), bundle())
    assert r['valid'], r['errors']
    report = r['strategy_report'][0]
    assert report['added'] == []
    assert report['added_gfa_m2'] == 0
    assert report['gfa_shortfall_m2'] == report['removed_gfa_m2'] == 520


def test_wing_depth_increases_north_south_clear_depth_by_three():
    b = bundle()
    old = b['courtyards'][0]['solar_geometry']['depth_along_sun_m']
    r = dry_run_proposal(proposal([{'op': 'COURTYARD_WING_DEPTH', 'courtyard_id': 'c', 'side': 'south', 'depth_m': 10}]), b)
    assert r['valid'], r['errors']
    assert r['strategy_report'][0]['depth_along_sun_m'] == old + 3


def test_wing_courtyard_geometry_survives_next_draft_input():
    b = bundle()
    p = proposal([{'op': 'COURTYARD_WING_DEPTH', 'courtyard_id': 'c', 'side': 'south', 'depth_m': 10}])
    first = dry_run_proposal(p, b)
    assert first['valid'], first['errors']
    parameters = {'editable_buildings': first['editable_buildings'],
                  'proposal_courtyard_overrides': first['courtyard_geometry_overrides']}
    next_bundle = assemble_proposal_inputs(
        {'id': 'card', 'status': 'VALIDATED', 'card': {'id': 'obs-1'}},
        {'parameters': parameters},
        courtyards=[{'courtyard_id': 'c', 'block_id': 'block', 'geometry': mapping(box(0, 13, 20, 60))}])
    assert next_bundle['courtyards'][0]['solar_geometry']['depth_along_sun_m'] == 50
