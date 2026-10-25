from shapely.geometry import mapping, box
from urban_design.fabric_net2_assessment import baselines

def fixture(values):
    rows=[{'source_line_id':str(i),'coordinates':[[i*10,0],[i*10+5,0]],'nain':v} for i,v in enumerate(values)]
    full={'before':{'segments':rows}}
    network={'features':[{'id':str(i),'properties':{'name':name}} for i,name in enumerate(['Vierhavensstraat','Keileweg','Other'])]}
    return full,network

def test_dynamic_and_missing():
    full,network=fixture([1,2,3]); a=baselines(full,{'site':mapping(box(0,0,1,1))},network)
    assert a['primary_meets']['percentile']==100/3
    full['before']['segments'][0]['nain']=4
    assert baselines(full,{'site':mapping(box(0,0,1,1))},network)['primary_meets']['percentile']==100
    network['features'][0]['properties']['name']='missing'
    assert baselines(full,{'site':mapping(box(0,0,1,1))},network)['primary_meets']['percentile'] is None

def test_water_missing_is_unavailable():
    full,network=fixture([1,2,3])
    assert baselines(full,{'site':mapping(box(0,0,1,1))},network)['waterfront_meets']['sample_count']==0

def test_water_filters_and_receipt_drift(tmp_path):
    import json
    import pytest
    from urban_design.fabric_syntax_segments import receipt
    from urban_design.fabric_net2_assessment import water_sample
    dataset=tmp_path/'water.json'; coverage=tmp_path/'coverage.json'
    dataset.write_text(json.dumps({'crs':{'properties':{'name':'EPSG:28992'}},'features':[{'geometry':mapping(box(-5,-5,5,5))}]}))
    coverage.write_text(json.dumps({'crs':'EPSG:28992','geometry':mapping(box(-2000,-2000,2000,2000))}))
    water={'dataset':receipt(dataset),'coverage':receipt(coverage)}
    full={'before':{'segments':[{'coordinates':[[0,25],[5,25]],'nain':1},{'coordinates':[[0,25.01],[5,25.01]],'nain':2},{'coordinates':[[1502,0],[1507,0]],'nain':3}]}}
    sample,reason=water_sample(full,{'site':mapping(box(0,0,1,1))},water)
    assert len(sample)==1 and reason is None
    dataset.write_text('{}')
    with pytest.raises(ValueError,match='receipt'):
        water_sample(full,{'site':mapping(box(0,0,1,1))},water)

def test_water_1500m_filter(tmp_path):
    import json
    from urban_design.fabric_syntax_segments import receipt
    from urban_design.fabric_net2_assessment import water_sample
    dataset=tmp_path/'water.json'; coverage=tmp_path/'coverage.json'
    dataset.write_text(json.dumps({'crs':{'properties':{'name':'EPSG:28992'}},'features':[{'geometry':mapping(box(-2000,-10,2000,10))}]}))
    coverage.write_text(json.dumps({'crs':'EPSG:28992','geometry':mapping(box(-2000,-2000,2000,2000))}))
    full={'before':{'segments':[{'coordinates':[[1501,0],[1506,0]],'nain':1},{'coordinates':[[1501.01,0],[1506,0]],'nain':2}]}}
    sample,_=water_sample(full,{'site':mapping(box(0,0,1,1))},{'dataset':receipt(dataset),'coverage':receipt(coverage)})
    assert len(sample)==1

def test_proposal_retains_int3_after_rank():
    from urban_design.fabric_net2_assessment import assess
    full,network=fixture([1,2,3]); plan={'site':mapping(box(0,0,1,1))}
    report={'mode':'bicycle','fabric_id':'x','intents':[{'intent_en':'primary_street','percentile':26,'roads':[{'nain':100,'length_m':1}]}]}
    result=assess(full,plan,network,report)
    assert result['checks'][0]['value'] is None
    assert result['checks'][0]['diagnostic_int3_percentile']==26
    assert result['descriptive_intents']==report['intents']

def test_missing_excellent_does_not_block_meets():
    from urban_design.fabric_net2_assessment import assess
    full,network=fixture([1,2,3]);network['features'][1]['properties']['name']='missing'
    full['after']={'segments':[{'id':'a','coordinates':[[0,0],[1,0]],'nain':3}]}
    plan={'site':mapping(box(-1,-1,2,2)),'roads':[{'id':'main','properties':{'role':'primary_street'},'geometry':{'type':'LineString','coordinates':[[0,0],[1,0]]}}]}
    result=assess(full,plan,network,{'mode':'bicycle','fabric_id':'x','intents':[{'intent_en':'primary_street','percentile':90}]})
    assert result['checks'][0]['status']=='PASS'
    assert result['checks'][0]['excellent_minimum'] is None

def test_complete_role_physical_support():
    from urban_design.fabric_net2_assessment import physical_role_score
    plan={'site':mapping(box(-1,-1,11,11)), 'roads':[{'id':'main','geometry':mapping(__import__('shapely').geometry.LineString([(0,0),(10,0)])),'properties':{'role':'primary_street'}}]}
    row=lambda a,b,n:{'id':str(n),'coordinates':[a,b],'nain':n}
    full={'after':{'segments':[row((0,0),(5,0),1),row((5,0),(10,0),3),row((2,-1),(2,1),2)]}}
    r=physical_role_score(full,plan,'primary_street')
    assert r['expected_length_m']==10 and r['support_length_m']==10
    assert r['percentile']==200/3
    full['after']['segments']=full['after']['segments'][1:]
    assert physical_role_score(full,plan,'primary_street')['percentile'] is None

def test_role_conflicting_duplicate_averages_overlap():
    from urban_design.fabric_net2_assessment import physical_role_score
    plan={'site':mapping(box(-1,-1,11,1)), 'roads':[{'id':'main','geometry':{'type':'LineString','coordinates':[[0,0],[10,0]]},'properties':{'role':'primary_street'}}]}
    full={'after':{'segments':[{'id':'a','coordinates':[[0,0],[10,0]],'nain':1},{'id':'b','coordinates':[[0,0],[10,0]],'nain':2}]}}
    result=physical_role_score(full,plan,'primary_street')
    assert result['percentile']==50
    assert result['roads'][0]['nain']==1.5
    assert result['conflict_interval_count']==1
    full['after']['segments'][1]['nain']=1
    assert physical_role_score(full,plan,'primary_street')['support_length_m']==10

def test_tolerant_collinear_support_does_not_count_crossings():
    from shapely.geometry import LineString
    from urban_design.fabric_net2_assessment import coextensive_support
    target=LineString([(0,0),(10,0)])
    assert coextensive_support(target,LineString([(0,.00001),(10,.00001)]))==[(0.,10.)]
    assert not coextensive_support(target,LineString([(5,-10),(5,10)]))
    assert not coextensive_support(target,LineString([(0,.0011),(10,.0011)]))

def test_water_coverage_requires_projected_crs(tmp_path):
    import json
    import pytest
    from urban_design.fabric_syntax_segments import receipt
    from urban_design.fabric_net2_assessment import water_sample
    dataset=tmp_path/'water.json'; coverage=tmp_path/'coverage.json'
    dataset.write_text(json.dumps({'crs':{'properties':{'name':'EPSG:28992'}},'features':[]}))
    for crs in [None,'EPSG:4326']:
        coverage.write_text(json.dumps({'crs':crs,'geometry':mapping(box(-2000,-2000,2000,2000))}))
        with pytest.raises(ValueError,match='coverage CRS'):
            water_sample({'before':{'segments':[]}}, {'site':mapping(box(0,0,1,1))}, {'dataset':receipt(dataset),'coverage':receipt(coverage)})


def role_fixture(rows):
    plan={'site':mapping(box(0,-1,10,1)), 'roads':[{'id':'main',
          'geometry':{'type':'LineString','coordinates':[[0,0],[10,0]]},
          'properties':{'role':'primary_street'}}]}
    return {'after':{'segments':rows}},plan


def test_role_authored_and_existing_support():
    from urban_design.fabric_net2_assessment import physical_role_score
    full,plan=role_fixture([
        {'id':'own','source_line_id':'proposal:main:part:0','coordinates':[[0,0],[6,0]],'nain':1},
        {'id':'old','source_line_id':'proposal:existing:way/1','coordinates':[[6,.4],[10,.4]],'nain':3},
        {'id':'cross','source_line_id':'way/2','coordinates':[[5,-1],[5,1]],'nain':9}])
    result=physical_role_score(full,plan,'primary_street')
    assert result['status']=='COMPUTED'
    assert result['coverage']==1
    assert result['roads'][0]['nain']==1.8
    assert result['percentile']==100/3
    assert result['roads'][0]['support_segment_ids']==['old','own']


def test_role_coverage_threshold():
    import pytest
    from urban_design.fabric_net2_assessment import physical_role_score
    for end,expected in [(8.9,'UNAVAILABLE'),(9.,'COMPUTED')]:
        full,plan=role_fixture([{'id':'a','source_line_id':'proposal:main',
                                'coordinates':[[0,0],[end,0]],'nain':1}])
        result=physical_role_score(full,plan,'primary_street')
        assert result['status']==expected
        assert result['coverage']==pytest.approx(end/10)
        if expected=='UNAVAILABLE':
            assert result['percentile'] is None
            assert '0.890000' in result['reason'] and '0.90' in result['reason']


def test_role_overlap_is_weighted_by_interval_length():
    import pytest
    from urban_design.fabric_net2_assessment import physical_role_score
    full,plan=role_fixture([
        {'id':'a','source_line_id':'proposal:main','coordinates':[[0,0],[10,0]],'nain':1},
        {'id':'b','source_line_id':'way/1','coordinates':[[0,0],[4,0]],'nain':3}])
    result=physical_role_score(full,plan,'primary_street')
    # 4m with equal local support lengths at mean 2, then 6m at 1.
    assert result['roads'][0]['nain']==pytest.approx(1.4)
    assert result['support_length_m']==10
    assert result['conflict_interval_count']==1
    assert result['percentile']==50


def test_export_partial_weld_round_skips_missing_files(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('net2_export_test',Path(__file__).parents[1]/'scripts/export_net2_syntax.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    source=tmp_path/'round-3-weld'/'syntax'; source.mkdir(parents=True)
    (source/'harbour_grain-pedestrian.json').write_text(json.dumps({'status':'UNAVAILABLE'}))
    result=module.export(source,tmp_path/'out')
    assert len(result['reports'])==1
    assert not (source/'segments').exists()
    assert (tmp_path/'out'/'net2-assessment.json').is_file()


def test_role_existing_authored_retained_road_also_supplies_support():
    from urban_design.fabric_net2_assessment import physical_role_score
    full,plan=role_fixture([
        {'id':'own','source_line_id':'proposal:main','coordinates':[[0,0],[6,0]],'nain':1},
        {'id':'retained','source_line_id':'proposal:old:part:1','coordinates':[[6,.3],[10,.3]],'nain':3}])
    plan['roads'].append({'id':'old','geometry':{'type':'LineString','coordinates':[[6,.3],[10,.3]]},
                          'properties':{'role':'retained_city_road','source_id':'way/1'}})
    result=physical_role_score(full,plan,'primary_street')
    assert result['status']=='COMPUTED'
    assert result['coverage']==1
    assert result['roads'][0]['nain']==1.8


def test_role_uses_pooled_length_weighted_nain_then_cdf():
    import pytest
    from urban_design.fabric_net2_assessment import physical_role_score
    full,plan=role_fixture([
        {'id':'a','source_line_id':'proposal:main','coordinates':[[0,0],[10,0]],'nain':1},
        {'id':'b','source_line_id':'proposal:second','coordinates':[[0,.8],[10,.8]],'nain':3},
        {'id':'context','source_line_id':'way/3','coordinates':[[20,0],[21,0]],'nain':2}])
    plan['roads'].append({'id':'second','geometry':{'type':'LineString','coordinates':[[0,.8],[10,.8]]},
                          'properties':{'role':'primary_street'}})
    result=physical_role_score(full,plan,'primary_street')
    assert result['nain']==pytest.approx(2)
    assert result['percentile']==200/3


def test_role_coverage_threshold_is_for_complete_role():
    from urban_design.fabric_net2_assessment import physical_role_score
    full,plan=role_fixture([{'id':'a','source_line_id':'proposal:main','coordinates':[[0,0],[10,0]],'nain':1}])
    plan['roads'].append({'id':'second','geometry':{'type':'LineString','coordinates':[[0,.8],[1,.8]]},
                          'properties':{'role':'primary_street'}})
    result=physical_role_score(full,plan,'primary_street')
    assert result['coverage']==10/11
    assert result['status']=='COMPUTED' and result['percentile']==100


def test_authored_source_cannot_project_remote_geometry_onto_role():
    from urban_design.fabric_net2_assessment import physical_role_score
    full,plan=role_fixture([{'id':'remote','source_line_id':'proposal:main',
                            'coordinates':[[0,100],[10,100]],'nain':1}])
    plan['site']=mapping(box(-1,-1,11,101))
    result=physical_role_score(full,plan,'primary_street')
    assert result['status']=='UNAVAILABLE' and result['coverage']==0


def test_existing_support_uses_local_overlap_distance_and_angle():
    from shapely.geometry import LineString
    from urban_design.fabric_net2_assessment import coextensive_support
    target=LineString([(0,0),(1,0)])
    assert coextensive_support(target,LineString([(-100,-1),(100,1)]),.5,15)==[(0.,1.)]
    assert not coextensive_support(target,LineString([(0,.51),(1,.51)]),.5,15)
    assert not coextensive_support(target,LineString([(0,0),(1,.3)]),.5,15)


def test_export_skips_compact_with_missing_referenced_files(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('net2_missing_test',Path(__file__).parents[1]/'scripts/export_net2_syntax.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    source=tmp_path/'round-3-weld'/'syntax'; source.mkdir(parents=True)
    missing={'path':str(tmp_path/'unfinished.json'),'sha256':'sha256:missing'}
    compact={'status':'COMPUTED','complete_intermediate':missing,'retained_road_receipts':missing,
             'source_receipts':{'plan':missing,'extract':{'manifest':{'outputs':{'network':missing}}}}}
    (source/'harbour_grain-pedestrian.json').write_text(json.dumps(compact))
    result=module.export(source,tmp_path/'out')
    assert result['reports']==[]
    assert len(result['skipped_sources'])==1
    assert result['skipped_sources'][0]['missing_paths']==[missing['path']]
