import pytest
from urban_design.fabric_syntax import proposal_roads, compact_result


def fixture():
    source={'id':'way/1','geometry':{'type':'LineString','coordinates':[[0,0],[1,0]]},'properties':{}}
    plan={'crs':'EPSG:28992','roads':[{'id':'new','geometry':{'type':'LineString','coordinates':[[0,1],[1,1]]},'properties':{'modes':['pedestrian','car','fire'],'width_m':5}}],'retained_road_inputs':[source]}
    return plan,{'pedestrian':[source],'bicycle':[source],'motor_vehicle':[source]}


def test_explicit_modes_and_retained_lineage():
    p,e=fixture();roads=proposal_roads(p,e)
    assert roads[0].modes==['motor_vehicle','pedestrian']
    assert roads[1].origin=='retained' and roads[1].source_road_ids==['way/1']


def test_retained_drift_fails_closed():
    p,e=fixture();p['retained_road_inputs']=[dict(p['retained_road_inputs'][0],geometry={'type':'LineString','coordinates':[[0,0],[1,0.0011]]})]
    with pytest.raises(ValueError,match='retained geometry mismatch'):proposal_roads(p,e)


def test_missing_modes_never_inferred_from_width():
    p,e=fixture();del p['roads'][0]['properties']['modes']
    with pytest.raises(ValueError,match='explicit FAB modes'):proposal_roads(p,e)


def test_blocked_compact_has_null_values():
    from shapely.geometry import box
    result=compact_result({'status':'BLOCKED','before':None,'after':None,'error':'missing'},box(0,0,1,1))
    assert result['delta_mean_integration_nain'] is None and result['new_street_ranking']==[]


def test_computed_summary_site_length_delta_and_all_new_streets():
    from shapely.geometry import box
    from urban_design import scenario_syntax as ss
    def row(identity,coords,nain,nach=1):
        return dict(id=identity,source_line_id=identity,coordinates=coords,nain=nain,nach=nach,inside_site=True,entrance=False)
    before=[row('context',[[-1,0.5],[3,0.5]],2)]
    after=[row('proposal:new:part:0',[[0,0.5],[1,0.5]],4),row('proposal:new:part:1',[[1,0.5],[2,0.5]],6),row('proposal:existing:1',[[0,1],[2,1]],100)]
    roads=[ss.ProposalRoad(id='new',coordinates=[(0,.5),(2,.5)],width_m=5,modes=['pedestrian'],origin='new',semantics_provenance='fixture'),ss.ProposalRoad(id='existing:1',coordinates=[(0,1),(2,1)],width_m=5,modes=['pedestrian'],origin='transformed',source_road_ids=['way/1'],semantics_provenance='fixture')]
    result={'status':'COMPUTED','before':{'segments':before,'metrics':ss._metrics(before,3)},'after':{'segments':after,'metrics':ss._metrics(after,3)}}
    summary=compact_result(result,box(0,0,2,2),roads)
    assert summary['before']['metrics']['high_integration_length_m']==0
    assert summary['after']['metrics']['high_integration_length_m']==4
    assert summary['delta_mean_integration_nain']==pytest.approx(110/3-2)
    assert summary['new_street_ranking']==[dict(road_id='new',nain=5,nach=1,inside_length_m=2,segment_count=2)]
    assert summary['new_street_ranking_count']==1 and summary['new_street_ranking_truncated'] is False


def test_all_new_streets_returned_without_top20_truncation():
    from shapely.geometry import box
    from urban_design import scenario_syntax as ss
    roads=[ss.ProposalRoad(id=f'new-{i}',coordinates=[(0,i),(1,i)],width_m=5,modes=['pedestrian'],origin='new',semantics_provenance='fixture') for i in range(25)]
    rows=[dict(source_line_id='proposal:'+r.id,coordinates=r.coordinates,nain=i,nach=0,inside_site=True) for i,r in enumerate(roads)]
    metrics={'high_threshold_nain':0,'mean_integration_nain':12}
    summary=compact_result({'before':{'segments':rows,'metrics':metrics},'after':{'segments':rows,'metrics':metrics}},box(0,-1,2,26),roads)
    assert len(summary['new_street_ranking'])==25


def test_submillimetre_clipped_support_snaps_to_full_verified_source():
    p,e=fixture();p['retained_road_inputs'][0]=dict(p['retained_road_inputs'][0],geometry={'type':'LineString','coordinates':[[.2,.0005],[.8,.0005]]})
    receipts=[];roads=proposal_roads(p,e,mode='bicycle',receipts=receipts)
    assert roads[1].coordinates==[(0.,0.),(1.,0.)]
    assert receipts[0]['supported'] and receipts[0]['max_vertex_distance_m']==pytest.approx(.0005)
    assert receipts[0]['hausdorff_distance_m']>.1


def test_endpoint_match_cannot_hide_unsupported_middle():
    p,e=fixture();p['retained_road_inputs'][0]=dict(p['retained_road_inputs'][0],geometry={'type':'LineString','coordinates':[[0,0],[.5,.01],[1,0]]})
    with pytest.raises(ValueError,match='retained geometry mismatch'):proposal_roads(p,e,mode='bicycle')


def test_clipped_retained_source_preserves_outside_context_without_duplicate():
    from shapely.geometry import box, shape
    from urban_design import scenario_syntax as ss
    p,e=fixture()
    p['roads']=[]
    p['retained_road_inputs'][0]=dict(p['retained_road_inputs'][0],geometry={'type':'LineString','coordinates':[[.2,.0005],[.8,.0005]]})
    roads=proposal_roads(p,e,mode='bicycle')
    merged=ss.merge_network(e['bicycle'],roads,box(.2,-.1,.8,.1),'bicycle',ss.MergeParameters(snap_tolerance_m=0))
    assert merged['removed']==[]
    assert sum(shape(f['geometry']).length for f in merged['features'])==pytest.approx(1)
    assert all(not f['id'].startswith('proposal:') for f in merged['features'])


def test_compute_script_refuses_existing_evidence(tmp_path):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('compute_fabric_syntax',Path(__file__).parents[1]/'scripts/compute_fabric_syntax.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=tmp_path/'output';output.mkdir();summary=output/'syntax-summary.json';summary.write_text('immutable')
    with pytest.raises(ValueError,match='choose a new --output'):module.run(tmp_path,output,tmp_path/'temp')
    assert summary.read_text()=='immutable'
