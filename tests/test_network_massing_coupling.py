"""J12c independent negative controls; synthetic geometry is not site evidence."""
from types import SimpleNamespace
import pytest
from shapely.geometry import LineString,box,mapping
from shapely.ops import unary_union
from urban_design.generation.network_massing_coupling import (
    CouplingRules,connected_components,transport_checks,ClusterSelector,
    downgrade_roads,merged_open_spaces,drawing_guard,ranked_development_roads)
from urban_design.generation.multimodal_network import NetworkRoad,NetworkRules,Entrance,syntax_roads
from urban_design.generation.type_registry import generate_block_profile
from urban_design.scenario_syntax import digest


def road(id,coords,*,modes=('pedestrian','bicycle','motor_vehicle'),origin='new',layer=0):
    return NetworkRoad(id=id,coordinates=coords,width_m=6,modes=list(modes),origin=origin,layer=layer,
        source_road_ids=[id] if origin=='retained' else [],semantics_provenance='ILLUSTRATIVE_TEST',
        hierarchy='retained' if origin=='retained' else 'service',width_class='city' if origin=='retained' else 'service',access='service_only' if origin=='new' else 'public',rule_card_ids=['test'])


def external(site):
    feature=dict(id='outside',geometry=mapping(LineString([(-20,0),(5,0)])),properties={'layer':0})
    return dict(_site=site,_water=box(500,500,520,520),motor_vehicle=[feature],pedestrian=[feature],bicycle=[feature])


def entry():
    return Entrance(id='e',coordinates=(0,0),modes=['pedestrian','bicycle','motor_vehicle'],source_ids={m:['outside'] for m in ('pedestrian','bicycle','motor_vehicle')},weight=1)


@pytest.mark.parametrize('field,value',[('bilateral_min',.59),('largest_park_min_m2',19999),('park_count_max',7),('remnant_max_m2',3001),('usable_width_m',11.99),('usable_area_m2',199)])
def test_assigned_gates_cannot_be_relaxed(field,value):
    with pytest.raises(ValueError):CouplingRules(**{field:value})


def test_grade_separated_crossing_does_not_connect():
    roads=[road('a',[(0,0),(100,0)]),road('b',[(50,-50),(50,50)],layer=1)]
    assert len(connected_components(roads,'pedestrian')[2])==2
    assert len(connected_components([roads[0],roads[1].model_copy(update={'layer':0})],'pedestrian')[2])==1


def test_fire_reach_uses_external_connected_motor_roads():
    site=box(0,0,200,200);roads=[road('a',[(0,0),(100,0)]),road('b',[(150,80),(150,180)])]
    checks,metrics=transport_checks(roads,[box(145,100,165,120)],{},[],external(site))
    assert not checks['motor_external_connected'] and not checks['fire_40m']
    assert metrics['motor_vehicle_component_count']==2


def test_each_motor_entrance_must_touch_connected_car_network():
    site=box(0,0,200,200);roads=[road('a',[(0,0),(100,0)])]
    e=Entrance(id='e',coordinates=(150,0),modes=['motor_vehicle'],source_ids={'motor_vehicle':['outside']},weight=1)
    checks,_=transport_checks(roads,[box(20,10,40,30)],{},[e],external(site))
    assert checks['fire_40m'] and not checks['motor_entrance_connected']


def option(block,index,type_id='block.perimeter'):
    p=generate_block_profile(type_id,block,wing_depth_m=12)
    return dict(block_index=index,profile=p,gfa=p.geometry.area*4,height=14,use='Residential',zone_id='z',wall_score=100)


def test_cluster_reserves_complete_two_sided_pair_and_budget():
    r=road('axis',[(0,0),(100,0)],modes=('pedestrian','bicycle'))
    a=option(box(10,4,90,48),0);b=option(box(10,-48,90,-4),1)
    ranked=[dict(road=r,score=90)]
    selector=ClusterSelector(ranked,[r],box(500,500,520,520))
    selected=selector([[a],[b]],a['gfa']+b['gfa'],10000)
    assert len(selected)==2 and len(selector.development)==1
    assert sum(o['gfa'] for o in selected)<=a['gfa']+b['gfa']
    small=ClusterSelector(ranked,[r],box(500,500,520,520))
    small([[a],[b]],a['gfa']+b['gfa']-1,10000)
    assert not small.development


def test_one_sided_candidates_cannot_create_development_street():
    r=road('axis',[(0,0),(100,0)],modes=('pedestrian','bicycle'))
    selector=ClusterSelector([dict(road=r,score=90)],[r],box(500,500,520,520))
    selector([[option(box(10,4,90,48),0)],[option(box(10,60,90,104),1)]],50000,20000)
    assert not selector.development


def test_downgrade_preserves_city_and_retained_service_roads():
    site=box(0,0,200,200);rs=[road('city',[(0,0),(100,0)],origin='retained'),road('service',[(100,0),(100,100)])]
    out,trace=downgrade_roads(rs,[box(20,10,40,30)],{'kept':box(105,50,125,70)},[],external(site),NetworkRules())
    assert [r.model_dump() for r in out]==[r.model_dump() for r in rs]
    assert {t['action'] for t in trace}=={'protected'}


def test_downgrade_reverts_fire_loss_and_preserves_shared_modes_on_success():
    site=box(0,0,200,200)
    rs=[road('city',[(0,0),(100,0)],origin='retained'),road('spur',[(100,0),(100,100)])]
    e=external(site)
    # New building can only be reached by spur within40m: must revert.
    out,trace=downgrade_roads(rs,[box(110,80,130,100)],{},[entry()],e,NetworkRules())
    assert trace[-1]['action']=='reverted' and 'fire_40m' in trace[-1]['failed_checks']
    assert 'motor_vehicle' in out[-1].modes
    # Close building reached from city: spur may become a park shared path.
    out,trace=downgrade_roads(rs,[box(20,10,40,30)],{},[entry()],e,NetworkRules())
    assert next(t for t in trace if t['road_id']=='spur')['action']=='downgraded'
    assert out[-1].modes==['bicycle','pedestrian'] and out[-1].park_shared


def test_removing_duplicate_keeps_actual_walk_and_cycle_connectivity():
    site=box(0,0,200,200)
    rs=[road('city',[(0,0),(100,0)],origin='retained'),road('spur',[(100,0),(100,100)]),road('walk',[(100,0),(100,100)],modes=('pedestrian','bicycle'))]
    out,trace=downgrade_roads(rs,[box(20,10,40,30)],{},[entry()],external(site),NetworkRules())
    assert next(t for t in trace if t['road_id']=='spur')['action']=='removed_duplicate'
    assert {r.id for r in out}=={'city','walk'}


def test_shared_park_paths_do_not_fragment_park_but_car_surface_does():
    site=box(0,0,200,200);water=box(500,500,520,520)
    slow=road('park',[(100,0),(100,200)],modes=('pedestrian','bicycle'))
    ground,spaces,remnants=merged_open_spaces(site,water,[slow],[],{})
    assert ground.area==40000 and len(spaces)==1 and spaces[0]['area_m2']==40000 and not remnants
    car=road('car',[(100,0),(100,200)])
    ground,spaces,remnants=merged_open_spaces(site,water,[car],[],{})
    assert len(spaces)==2 and ground.area==38800
    assert max(s['area_m2'] for s in spaces)<20000


def test_narrow_and_small_fragments_remain_measured_and_unlabelled():
    site=unary_union([box(0,0,500,8),box(600,0,610,10),box(700,0,900,200)])
    ground,spaces,remnants=merged_open_spaces(site,box(1500,1500,1600,1600),[],[],{})
    assert len(spaces)==1 and sum(r['area_m2'] for r in remnants)==4100
    assert sum(s['area_m2'] for s in spaces)+sum(r['area_m2'] for r in remnants)==ground.area


def test_invalid_result_or_forged_valid_status_cannot_be_drawn():
    for row in [{},{'status':'INVALID'},{'status':'VALID','version':'j12c-coupling-v1','buildings':[{}],'coupling':{'rules':CouplingRules().model_dump()},'checks':{'wall':False}}]:
        with pytest.raises(ValueError,match='figure output prohibited'):drawing_guard(row)


def test_bicycle_hash_and_mode_fail_closed_before_ranking():
    site=box(0,0,100,100);r=road('r',[(0,0),(100,0)]);rules=NetworkRules()
    ped=dict(status='COMPUTED',mode='pedestrian',radius_m=800,road_input_sha256=digest([p.model_dump() for p in syntax_roads([r],'pedestrian',rules)]),site_sha256=digest(mapping(site)),after={'segments':[dict(id='p',nain=1,inside_site=True,coordinates=r.coordinates,source_line_id='proposal:r')]})
    with pytest.raises(ValueError,match='bicycle 2km'):
        ranked_development_roads('radial',[r],ped,{'status':'COMPUTED','mode':'bicycle','radius_m':2000,'road_input_sha256':'forged'},site,[],CouplingRules(),rules)


def test_street_can_require_multiple_blocks_on_each_side():
    r=road('axis',[(0,0),(200,0)],modes=('pedestrian','bicycle'))
    options=[option(box(x,4,x+80,48),i*2) for i,x in enumerate((10,110))]+[option(box(x,-48,x+80,-4),i*2+1) for i,x in enumerate((10,110))]
    selector=ClusterSelector([dict(road=r,score=90)],[r],box(500,500,520,520))
    selected=selector([[o] for o in options],sum(o['gfa'] for o in options),20000)
    assert len(selected)==4 and len(selector.development)==1
    assert selector.development[0]['block_indices']==[0,1,2,3]
    # Any single opposite pair covers only0.4; the complete four-block group
    # must cover0.8 without changing the0.6 assignment threshold.
    from urban_design.generation.massing_revision import streetwall_continuity,facade_segments
    witnesses=[dict(type_id=o['profile'].type_id,facade_segments=facade_segments(o['profile'].geometry,[r],[])) for o in selected]
    assert streetwall_continuity([LineString(r.coordinates)],witnesses)['streetwall_continuity_ratio']==pytest.approx(.8)


def test_existing_internal_city_street_is_eligible_without_changing_it():
    site=box(0,0,100,100);r=road('city',[(-100,0),(200,0)],origin='retained');rules=NetworkRules()
    before=dict(id='ext',source_line_id='ext',nain=10,coordinates=r.coordinates,inside_site=True)
    after={**before,'id':'inside','source_line_id':'proposal:city'}
    def doc(mode,radius):
        return dict(status='COMPUTED',mode=mode,radius_m=radius,road_input_sha256=digest([v.model_dump() for v in syntax_roads([r],mode,rules)]),site_sha256=digest(mapping(site)),before={'segments':[before]},after={'segments':[after]})
    e=Entrance(id='high',coordinates=(0,0),modes=['pedestrian','bicycle','motor_vehicle'],source_ids={m:['ext'] for m in ('pedestrian','bicycle','motor_vehicle')},weight=1)
    ranked=ranked_development_roads('axial',[r],doc('pedestrian',800),doc('bicycle',2000),site,[e],CouplingRules(),rules)
    assert len(ranked)==1 and ranked[0]['road'].model_dump()==r.model_dump()
    assert LineString(r.coordinates).length==300
    assert __import__('shapely').geometry.shape(ranked[0]['development_geometry']).length==100


def test_affordable_long_fronts_upgrade_short_cheap_profiles():
    r=road('axis',[(0,0),(100,0)],modes=('pedestrian','bicycle'))
    def group(index,side):
        small=[option(box(10,side*4 if side>0 else -4-size,10+size,4+size if side>0 else -4),index,'building.l_block') for size in (32,34,36)]
        large=option(box(10,4,90,48) if side>0 else box(10,-48,90,-4),index)
        return small+[large]
    a,b=group(0,1),group(1,-1)
    selector=ClusterSelector([dict(road=r,score=90)],[r],box(500,500,520,520))
    budget=a[-1]['gfa']+b[-1]['gfa']
    selected=selector([a,b],budget,20000)
    assert len(selected)==2 and len(selector.development)==1
    assert all(o['profile'].type_id=='block.perimeter' for o in selected)
    assert sum(o['gfa'] for o in selected)<=budget
    assert {o['block_index'] for o in selected}=={0,1}


def test_motor_before_cache_rejects_wrong_site_without_dispatch():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('j12c_runner',Path(__file__).parents[1]/'scripts/run_network_massing_coupling_copy.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    with pytest.raises(ValueError,match='baseline input/implementation mismatch'):
        runner.compare_motor_using_verified_before([],[],box(0,0,10,10),(),{'status':'COMPUTED','mode':'motor_vehicle','site_sha256':'wrong'}, {'sha256':'sha256:untrusted'})


def test_motor_scenario_cache_requires_complete_and_matching_inputs(tmp_path):
    import importlib.util,json
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('j12c_cache',Path(__file__).parents[1]/'scripts/run_network_massing_coupling_copy.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    (tmp_path/'radial-2-motor_vehicle-syntax.json').write_text(json.dumps({'status':'COMPUTED','road_input_sha256':'wrong','before':{},'after':{}}))
    # A partially-written operation is never a complete cache.
    assert runner.matching_motor_cache([tmp_path],'radial-2',{'road_input_sha256':'expected'},tmp_path/'archive') is None
    (tmp_path/'radial-2.json').write_text('{}')
    assert runner.matching_motor_cache([tmp_path],'radial-2',{'road_input_sha256':'expected'},tmp_path/'archive') is None
