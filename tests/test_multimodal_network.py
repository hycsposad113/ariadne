from types import SimpleNamespace
import pytest
from shapely.geometry import LineString, Point, box
from urban_design.generation import multimodal_network as n


def source(id, coords, highway='residential', **kw):
    return {'type':'Feature','id':id,'geometry':{'type':'LineString','coordinates':coords},'properties':{'highway':highway,**kw}}


def road(id='r', coords=((0,0),(200,0)), **kw):
    return n.NetworkRoad(id=id,coordinates=coords,width_m=4.5,modes=['pedestrian','bicycle','motor_vehicle'],origin='new',semantics_provenance='ASSUMED_COMMANDER',hierarchy='main',width_class='shared',access='service_only',rule_card_ids=['MOB-001'],**kw)


def test_classifier_protects_through_city_road_and_service_junction():
    site=box(0,0,200,200)
    features=[source('city',[(-20,100),(220,100)]),source('dead',[(50,100),(50,150)],'service'),source('join',[(30,100),(70,100)],'service')]
    rows=n.classify_existing(features,site,n.NetworkRules())
    assert rows[0].disposition=='retained'
    assert rows[1].disposition=='removed'  # Founder J11b: local industrial dead end is replaced
    assert all(r.reason and r.rule_card_id for r in rows)
    transformed=n.classify_existing(features,site,n.NetworkRules(transform_dead_end_service=True))
    assert next(r for r in transformed if r.source_id=='dead').disposition=='transformed'
    assert next(r for r in transformed if r.source_id=='city').disposition=='retained'


def test_midrank_baseline_and_targets_are_mode_specific():
    assert n.percentile(2,[1,2,2,3])==50
    assert n.percentile(2,[2,2]) is None
    targets=n.strategy_targets('axial',n.NetworkRules())
    assert len(targets)==6
    assert {(t.mode,t.radius_m) for t in targets}=={('pedestrian',800),('bicycle',2000)}
    assert next(t for t in targets if t.hierarchy=='main').level=='High'


@pytest.mark.parametrize('family',n.FAMILIES)
def test_variants_are_network_first_shared_and_no_spurs(family):
    variants=n.generate_variants(box(0,0,240,240),(),[n.Entrance(id='west',coordinates=(0,120),modes=['pedestrian','bicycle'],source_ids={'pedestrian':['ext'],'bicycle':['ext']},weight=1)],family,n.NetworkRules(),angle=0)
    assert len(variants)>=2
    assert len({n.digest([r.model_dump() for r in v.roads]) for v in variants})==len(variants)
    for v in variants:
        assert v.roads
        assert all({'pedestrian','bicycle'} <= set(r.modes) for r in v.roads)
        assert not any('spur' in r.id for r in v.roads)
        assert all(LineString(r.coordinates).is_simple for r in v.roads)
        assert v.parameters['provenance']=='ASSUMED_COMMANDER'


def test_blocks_subtract_retained_road_and_buildings():
    r=road(coords=((-10,100),(210,100)))
    blocks=n.derive_blocks(box(0,0,200,200),[r],[box(40,40,60,60)],box(-10,-20,210,-10),n.NetworkRules())
    assert all(g.intersection(LineString(r.coordinates).buffer(r.width_m/2)).area==0 for g in blocks)
    assert all(g.intersection(box(40,40,60,60).buffer(3)).area==0 for g in blocks)


def valid_fixture():
    return dict(site=box(-10,-10,210,100),roads=[road()],buildings=[box(20,5,40,25)],retained_before={'keep':box(100,30,110,40)},retained_after={'keep':box(100,30,110,40)},water=box(-20,-30,220,-20),entrances=[n.Entrance(id='e',coordinates=(0,0),modes=['pedestrian','bicycle'],source_ids={'pedestrian':['ext'],'bicycle':['ext']},weight=1)],external={'pedestrian':[source('ext',[(-30,0),(0,0)])],'bicycle':[source('ext',[(-30,0),(0,0)])],'motor_vehicle':[source('ext',[(-30,0),(0,0)])]},rules=n.NetworkRules())


def test_hard_checks_positive():
    r=n.hard_checks(**valid_fixture())
    assert r['status']=='VALID',r
    assert r['road_overlap_area_m2']==0


@pytest.mark.parametrize('violation',('overlap','retained','bicycle_adjacency','bicycle_distance','fire','entrance','water','outside','disconnected'))
def test_hard_checks_each_negative(violation):
    x=valid_fixture()
    if violation=='overlap':x['buildings']=[box(20,-1,40,10)]
    if violation=='retained':x['retained_after']={}
    if violation=='bicycle_adjacency':x['roads']=[road().model_copy(update={'modes':['bicycle']})]
    if violation=='bicycle_distance':x['roads']=[road().model_copy(update={'modes':['pedestrian','motor_vehicle']})]
    if violation=='fire':x['roads']=[road().model_copy(update={'modes':['pedestrian','bicycle']})]
    if violation=='entrance':x['external']['bicycle']=[]
    if violation=='water':x['water']=box(20,20,40,30)
    if violation=='outside':x['buildings']=[box(200,5,230,25)]
    if violation=='disconnected':x['roads'].append(road('isolated',((100,80),(180,80))))
    assert n.hard_checks(**x)['status']=='INVALID'


def test_whole_bicycle_segment_and_each_detached_building_component():
    x=valid_fixture();x['roads']=[road().model_copy(update={'modes':['pedestrian','motor_vehicle']}),road('cycle',((0,0),(0,90))).model_copy(update={'modes':['bicycle']})]
    assert n.hard_checks(**x)['checks']['bicycle_adjacency'] is False
    from shapely.geometry import MultiPolygon
    x=valid_fixture();x['buildings']=[MultiPolygon([box(10,5,20,15),box(10,70,20,80)])]
    assert n.hard_checks(**x)['checks']['fire_service'] is False


def test_selection_rejects_invalid_geometry_and_has_no_overall_winner():
    rows=[{'id':'bad','quality':{'valid':False},'target_score':1,'geometry_score':1}, {'id':'a','quality':{'valid':True},'target_score':.7,'geometry_score':.8},{'id':'b','quality':{'valid':True},'target_score':.9,'geometry_score':.8}]
    assert n.select_variant(rows)['id']=='b'
    assert n.select_variant(rows[:1]) is None


def test_contract_excludes_service_only_from_car_syntax():
    roads=[road()]
    assert n.syntax_roads(roads,'motor_vehicle')==[]
    assert len(n.syntax_roads(roads,'bicycle'))==1
    assert n.VERSION=='formal-dictionary-v7-multimodal'
    with pytest.raises(ValueError): n.NetworkRules(bicycle_distance_m=-1)


def test_quality_rejects_too_large_blocks_deadends_and_acute_bends():
    rules=n.NetworkRules()
    q=n.geometry_quality(box(0,0,500,500),[road(coords=((0,0),(100,0),(1,1)))],[box(0,0,300,300)],[],rules)
    assert not q['valid'] and not q['block_range_pass']
    assert q['minimum_turn_deg']<30


def test_target_score_uses_frozen_sample_and_missing_is_unmet():
    r=road().model_copy(update={'hierarchy':'main'})
    results={'pedestrian':{'after':{'segments':[{'coordinates':r.coordinates,'nain':9}]}}}
    targets=[n.Target(hierarchy='main',mode='pedestrian',radius_m=800,level='High'),n.Target(hierarchy='branch',mode='bicycle',radius_m=2000,level='Medium')]
    reports,score=n.score_targets(targets,[r],results,{'pedestrian':list(range(10)),'bicycle':list(range(10))},n.NetworkRules())
    assert reports[0]['status']=='達成'
    assert reports[1]['status']=='未達成' and reports[1]['actual_mean_nain'] is None
    assert score==.5


def test_draft_pipeline_rejects_runtime_path_before_access():
    from urban_design.generation.formal_multimodal import checked_copy
    with pytest.raises(ValueError,match='private/tmp'):
        checked_copy('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')


def test_fire_service_must_connect_to_external_motor_network():
    x=valid_fixture();x['external']['motor_vehicle']=[]
    assert n.hard_checks(**x)['checks']['fire_service'] is False


def test_boundary_touch_is_road_intersection_even_when_area_zero():
    x=valid_fixture();x['buildings']=[box(20,2.25,40,25)]
    r=n.hard_checks(**x)
    assert r['road_overlap_area_m2']==0
    assert r['checks']['road_overlap'] is False


def test_unlink_input_is_verified_list_not_silently_ignored():
    from urban_design.generation.formal_multimodal import unlink_points
    assert unlink_points([[1,2],[3,4]])==((1,2),(3,4))
    with pytest.raises(ValueError):unlink_points({'points':[]})


def test_diagnosis_reads_per_mode_nain_nach_and_optional_j9b_weights():
    f=source('ext',[(-10,100),(210,100)])
    docs={m:{'segments':[{'source_line_id':'ext','coordinates':f['geometry']['coordinates'],'distance_to_site_m':0,'nain':.9,'nach':.4},
                        {'source_line_id':'far','coordinates':[(0,300),(100,300)],'distance_to_site_m':100,'nain':.1,'nach':.1}]} for m in ('pedestrian','bicycle')}
    entrances,samples=n.diagnose_entrances(box(0,0,200,200),docs,{m:[f] for m in docs})
    weighted,_=n.diagnose_entrances(box(0,0,200,200),docs,{m:[f] for m in docs},{'ext':2})
    assert len(entrances)==2 and len(samples['pedestrian'])==2
    assert all(set(e.modes)=={'pedestrian','bicycle'} for e in entrances)
    assert weighted[0].weight==entrances[0].weight+2
    with pytest.raises(ValueError):n.diagnose_entrances(box(0,0,200,200),docs,{m:[f] for m in docs},{'ext':-1})


def test_source_mode_retention_obeys_j10_exact_geometry():
    from urban_design.generation.formal_multimodal import retained_roads
    from urban_design.scenario_syntax import merge_network,MergeParameters
    site=box(0,0,200,200);features=[source('city',[(-20,100),(220,100)])]
    fixed=retained_roads(features,n.classify_existing(features,site,n.NetworkRules()),{'city':['motor_vehicle']},n.NetworkRules())
    result=merge_network(features,n.syntax_roads(fixed,'motor_vehicle'),site,'motor_vehicle',MergeParameters())
    assert result['unchanged'] and not result['removed']


def test_place_program_on_new_blocks_preserves_road_overlap_zero():
    from tests.test_formal_dictionary_pipeline import fixture
    from urban_design.generation.formal_multimodal import place_candidate
    from datetime import datetime,timezone
    context,manifest,inputs=fixture()
    roads=[road(f'line-{i}',((0,y),(600,y))) for i,y in enumerate((80,160,240,320))]
    parts=n.derive_blocks(inputs.design_area,roads,[g for _,g,_ in inputs.retained_buildings],inputs.water_geometry,n.NetworkRules())
    massing,metrics,checks=place_candidate(context,manifest,inputs,roads,parts,'test-v7',0,n.NetworkRules(),datetime(2026,10,8,tzinfo=timezone.utc))
    from shapely.geometry import shape
    from shapely.ops import unary_union
    surface=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads])
    assert all(shape(b.footprint.model_dump()).intersection(surface).area==0 for b in massing.buildings)
    assert metrics['new_building_count']>0 and metrics['highest_new_height_m']<=20


def test_exact_source_entrance_needs_no_snap_and_short_valid_segment_survives():
    from urban_design.scenario_syntax import merge_network,MergeParameters
    f=source('ext',[(-1,0),(0,0)])
    r=road(coords=((0,0),(.2,0)))
    result=merge_network([f],n.syntax_roads([r],'bicycle'),box(0,-1,10,1),'bicycle',MergeParameters(snap_tolerance_m=0))
    assert result['status']=='READY'
    assert any(shape['id'].startswith('proposal:') for shape in result['features'])


def test_shared_existing_overlay_never_duplicates_bicycle_source_line():
    from urban_design.generation.formal_multimodal import shared_existing_overlay
    cycle=road(coords=((0,0),(.35,0))).model_copy(update={'modes':['bicycle'],'origin':'retained','source_road_ids':['cycle']})
    overlays=shared_existing_overlay([cycle],box(-1,-1,10,10),'test',n.NetworkRules())
    assert len(overlays)==1
    assert overlays[0].modes==['pedestrian'] and overlays[0].pedestrian_only_reason
    assert len(n.syntax_roads([cycle,*overlays],'bicycle'))==1


def test_pst_segment_parent_and_geometry_are_both_required_for_target():
    r=road().model_copy(update={'hierarchy':'main'})
    target=[n.Target(hierarchy='main',mode='pedestrian',radius_m=800,level='High')]
    result={'pedestrian':{'after':{'segments':[{'source_line_id':'proposal:r:part:0','coordinates':[(0,.00001),(100,.00001)],'nain':9,'inside_site':True}]}}}
    report,_=n.score_targets(target,[r],result,{'pedestrian':list(range(10))},n.NetworkRules())
    assert report[0]['status']=='達成' and report[0]['segment_count']==1
    result['pedestrian']['after']['segments'][0]['coordinates']=[(0,10),(100,10)]
    with pytest.raises(ValueError,match='geometry'):n.score_targets(target,[r],result,{'pedestrian':list(range(10))},n.NetworkRules())


def test_indexed_access_equals_union_for_each_detached_component():
    from urban_design.generation.formal_multimodal import DistanceIndex
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union
    geoms=[LineString([(0,0),(100,0)]).buffer(3),LineString([(100,0),(100,100)]).buffer(3)]
    index=DistanceIndex(geoms)
    footprint=MultiPolygon([box(10,10,20,20),box(50,70,60,80)])
    expected=max(g.distance(unary_union(geoms)) for g in footprint.geoms)
    assert index(footprint)==pytest.approx(expected,abs=1e-9)


def test_planned_segmentation_preserves_alignment_and_retained_source():
    from urban_design.generation.formal_multimodal import segment_planned_roads
    from shapely.ops import unary_union
    r=road(coords=((0,0),(100,0),(100,100)))
    retained=r.model_copy(update={'id':'fixed','origin':'retained','source_road_ids':['original']})
    parts=segment_planned_roads([r,retained])
    assert len(parts)==3
    assert parts[-1]==retained
    assert all(len(p.coordinates)==2 for p in parts[:-1])
    assert unary_union([LineString(p.coordinates) for p in parts[:-1]]).equals(LineString(r.coordinates))


def test_classifier_removes_small_loop_and_preserves_public_destination():
    loop=list(Point(100,100).buffer(10,quad_segs=4).exterior.coords)
    features=[source('ring',loop,'footway'),source('park',[(-20,20),(30,30)],'path',destination='Dakpark'),source('city',[(-10,180),(210,180)]),source('parallel',[(-10,184),(210,184)],'cycleway')]
    rows={r.source_id:r for r in n.classify_existing(features,box(0,0,200,200),n.NetworkRules())}
    assert rows['ring'].disposition=='removed'
    assert rows['park'].disposition==rows['parallel'].disposition=='retained'
    assert all(r.rule_card_id and r.reason for r in rows.values())


def test_classifier_protects_retained_service_dependency():
    f=source('service',[(10,10),(10,100)],'service')
    assert n.classify_existing([f],box(0,0,200,200),n.NetworkRules(),[box(15,30,25,40)])[0].disposition=='retained'


@pytest.mark.parametrize('family',n.FAMILIES)
def test_constructed_network_connected_and_dead_end_bounded_with_obstacle(family):
    from shapely.ops import unary_union
    site=box(0,0,240,240)
    entry=n.Entrance(id='e',coordinates=(0,120),modes=['pedestrian','bicycle','motor_vehicle'],source_ids={},weight=1)
    for v in n.generate_variants(site,[box(80,80,110,140)],[entry],family,n.NetworkRules()):
        assert not v.parameters['construction_failures']
        lines=[LineString(r.coordinates) for r in v.roads]
        reached={0}
        while True:
            neighbours={i for i,g in enumerate(lines) if any(g.distance(lines[j])<1e-6 for j in reached)}
            if neighbours==reached:break
            reached=neighbours
        assert len(reached)==len(lines)
        q=n.geometry_quality(site,v.roads,[],[entry],n.NetworkRules())
        assert q['dead_end_count']<=12
        fire=unary_union([g.buffer(r.width_m/2) for g,r in zip(lines,v.roads) if 'motor_vehicle' in r.modes])
        assert box(80,80,110,140).distance(fire)<=40
        assert all(g.intersection(box(80,80,110,140)).length==0 for g in lines)


def test_families_have_core_and_car_free_band_and_distinct_axis():
    variants={f:n.generate_variants(box(0,0,240,240),[],[],f,n.NetworkRules())[0] for f in n.FAMILIES}
    assert variants['radial'].parameters['central_core']
    assert not variants['axial'].parameters['central_core']
    assert variants['green_service'].parameters['green_band']
    from shapely.geometry import shape
    band=shape(variants['green_service'].parameters['green_band'][0])
    assert all(LineString(r.coordinates).intersection(band).length==0 for r in variants['green_service'].roads if 'motor_vehicle' in r.modes)
    assert len({n.digest([r.model_dump() for r in v.roads]) for v in variants.values()})==4


def test_retained_building_also_requires_connected_fire_access():
    x=valid_fixture();x['retained_before']=x['retained_after']={'keep':box(100,60,110,70)}
    r=n.hard_checks(**x)
    assert not r['checks']['retained_fire_service']
    assert r['retained_fire_distances_m']['keep']>40


def test_quality_checks_junction_angles_short_segments_and_disconnected_graph():
    rs=[road('a',((0,0),(100,0))),road('b',((50,0),(100,10))),road('tiny',((0,0),(0,1))),road('island',((150,100),(200,100)))]
    q=n.geometry_quality(box(-10,-10,240,200),rs,[box(10,20,70,80)],[],n.NetworkRules())
    assert q['minimum_turn_deg']<30 and q['short_segments']
    assert q['connected_component_count']==2 and not q['valid']


def test_j9b_local_weights_are_bounded_and_site_checked(tmp_path):
    import json
    from urban_design.generation.formal_multimodal import apply_j9b
    entry=n.Entrance(id='e',coordinates=(0,0),modes=['pedestrian'],source_ids={},weight=1)
    p=tmp_path/'diagnosis.json'
    d={'project_id':'p','study_area_id':'s','crs':'EPSG:28992','distance_unit':'m','entrances':[{'id':'j','coordinates':[0,0],'side':'N','distance_potential':12}],
       'closest_transit_side':'N','created_at':'2026-10-08T00:00:00Z','limitations':['EXPLORATORY']}
    p.write_text(json.dumps(d));entries,receipt=apply_j9b([entry],p,'p','s')
    assert entries[0].weight==2 and receipt['matches'][0]['side']=='N'
    with pytest.raises(ValueError,match='mismatch'):apply_j9b([entry],p,'wrong','s')


def test_service_gate_comes_from_exact_external_motor_source_without_motor_context():
    f=source('city',[(-10,100),(210,100)])
    entries,_=n.diagnose_entrances(box(0,0,200,200),{}, {'motor_vehicle':[f]})
    assert len(entries)==2 and all(e.modes==['motor_vehicle'] for e in entries)
    variants=n.generate_variants(box(0,0,200,200),[],entries,'green_service',n.NetworkRules())
    for v in variants:
        service=[LineString(r.coordinates) for r in v.roads if 'motor_vehicle' in r.modes]
        assert all(any(g.distance(Point(e.coordinates))<1e-6 for g in service) for e in entries)


def test_core_and_green_band_are_reserved_before_placement_and_hard_checked():
    public=box(50,50,90,90)
    blocks=n.derive_blocks(box(0,0,200,200),[],[],box(-20,-30,220,-20),n.NetworkRules(),[public])
    assert all(g.intersection(public).area==0 for g in blocks)
    x=valid_fixture();x['public_spaces']=[box(25,10,35,20)]
    assert not n.hard_checks(**x)['checks']['public_space_clear']
    x['public_spaces']=[public]
    assert n.hard_checks(**x)['checks']['public_space_clear']


def test_j9b_transit_path_protects_untagged_public_footway_but_not_small_loop():
    walkway=source('walk',[(10,40),(90,40)],'footway')
    private=source('private',[(10,60),(90,60)],'footway',access='private')
    loop=source('loop',list(Point(120,100).buffer(10,quad_segs=4).exterior.coords),'footway')
    paths=[LineString(walkway['geometry']['coordinates']),LineString(private['geometry']['coordinates']),LineString(loop['geometry']['coordinates'])]
    rows={d.source_id:d for d in n.classify_existing([walkway,private,loop],box(0,0,200,200),n.NetworkRules(),destination_routes=paths)}
    assert rows['walk'].disposition=='retained'
    assert rows['private'].disposition==rows['loop'].disposition=='removed'


def test_dead_end_cap_counts_retained_internal_tails_too():
    import math
    rs=[road(str(i),((100,100),(100+60*math.cos(i*2*math.pi/13),100+60*math.sin(i*2*math.pi/13)))).model_copy(update={'origin':'retained','source_road_ids':[str(i)]}) for i in range(13)]
    q=n.geometry_quality(box(0,0,200,200),rs,[box(10,10,70,70)],[],n.NetworkRules())
    assert q['new_dead_end_count']==0
    assert q['dead_end_count']==13 and not q['valid']
