"""S5 controls using synthetic geometry and the real pinned deterministic engine."""
import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from shapely.geometry import LineString, box, mapping, shape

from urban_design.scenario_syntax import (MergeParameters, ProposalRoad, assumed_road_properties, compare_syntax,
    digest, merge_network, roads_from_geojson, segment_diff)
from urban_design.scenario_syntax_api import create_scenario_syntax_router
from urban_design.store import ProjectStateStore
from urban_design.pst_syntax import DEFAULT_PST_MANIFEST
from urban_design.syntax_engines.pst_adapter import PSTAdapter

SITE = box(0,0,10,10)

def feature(id, coords, **properties):
    return {'type':'Feature','id':id,'geometry':mapping(LineString(coords)),'properties':properties}

def road(coords=((0,5),(5,8),(10,5)), **changes):
    return ProposalRoad(**{'id':'proposal','coordinates':coords,'width_m':4.5,'modes':['pedestrian','bicycle'],
        'origin':'new','semantics_provenance':'ASSUMED_COMMANDER',**changes})

NETWORK = [feature('existing',[(-10,5),(20,5)]), feature('branch',[(20,5),(20,20)]), feature('far',[(20,20),(30,20)])]


def test_contract_and_explicit_legacy_assumptions():
    assert set(assumed_road_properties('road:south_strip_collector:a')['modes']) == {'pedestrian','bicycle','motor_vehicle'}
    assert assumed_road_properties('road:access_lane:a')['semantics_provenance'] == 'ASSUMED_COMMANDER'
    assert 'motor_vehicle' not in assumed_road_properties('legacy-without-role')['modes']
    with pytest.raises(ValidationError): road(modes=['pedestrian','pedestrian'])
    with pytest.raises(ValidationError): road(origin='retained')
    with pytest.raises(ValidationError): road(coordinates=[(0,0),(float('nan'),0)])


def test_remove_interior_keeps_exterior_and_nodes_boundary_and_crossings():
    result = merge_network(NETWORK,[road()],SITE,'pedestrian',MergeParameters())
    assert result['status'] == 'READY'
    assert len(result['connection_points']) == 2
    assert sum(shape(f['geometry']).length for f in result['removed']) == 10
    context = [f for f in result['features'] if not f['properties'].get('proposal')]
    assert all(shape(f['geometry']).intersection(SITE).length == 0 for f in context)
    assert sum(shape(f['geometry']).length for f in context) == 45
    cross = merge_network(NETWORK,[road(),road(id='cross',coordinates=[(5,5),(5,10)])],SITE,'pedestrian',MergeParameters())
    assert sum('part:' in f['id'] for f in cross['features']) >= 4


def test_snap_and_block_disconnected_or_overpass_or_unlink():
    result = merge_network(NETWORK,[road(coordinates=[(.5,5),(5,8),(9.5,5)])],SITE,'pedestrian',MergeParameters())
    assert result['status']=='READY'
    assert {r['distance_m'] for r in result['snaps']}=={.5}
    assert merge_network(NETWORK,[road(coordinates=[(4,4),(6,6)])],SITE,'pedestrian',MergeParameters())['status']=='BLOCKED'
    assert merge_network(NETWORK,[road(layer=1)],SITE,'pedestrian',MergeParameters())['status']=='BLOCKED'
    assert merge_network(NETWORK,[road()],SITE,'pedestrian',MergeParameters(),unlinks=[(0,5),(10,5)])['status']=='BLOCKED'


def test_retained_context_and_mode_filter():
    retained = road(origin='retained', source_road_ids=['existing'], coordinates=[(-10,5),(20,5)])
    result = merge_network(NETWORK,[retained],SITE,'pedestrian',MergeParameters())
    assert result['status']=='READY' and result['unchanged'] and not result['removed']
    assert merge_network(NETWORK,[road(modes=['bicycle'])],SITE,'pedestrian',MergeParameters())['status']=='BLOCKED'


class CountingRealAdapter:
    def __init__(self):
        self.adapter=PSTAdapter(manifest_path=DEFAULT_PST_MANIFEST);self.requests=[]
    def compute(self, request):
        self.requests.append(request)
        return self.adapter.compute(request)


def test_real_pst_same_method_and_unchanged_motor_reuse():
    adapter=CountingRealAdapter()
    result=compare_syntax(NETWORK,[road()],SITE,'pedestrian',adapter=adapter)
    assert result['status']=='COMPUTED'
    assert len(adapter.requests)==2
    assert {(r.radius_mode,r.radius_m,r.metric_mode,r.unlinks) for r in adapter.requests}=={('walking',800.,'both',())}
    assert result['before']['metrics']['high_threshold_nain']==result['after']['metrics']['high_threshold_nain']
    motor=CountingRealAdapter()
    retained=road(origin='retained',source_road_ids=['existing'],modes=['motor_vehicle'],coordinates=[(-10,5),(20,5)])
    result=compare_syntax(NETWORK,[retained],SITE,'motor_vehicle',adapter=motor)
    assert result['reuse_status']=='REUSED_UNCHANGED_MOTOR_NETWORK' and len(motor.requests)==1
    assert result['before']==result['after']
    changed=CountingRealAdapter()
    result=compare_syntax(NETWORK,[road(modes=['motor_vehicle'])],SITE,'motor_vehicle',adapter=changed)
    assert result['reuse_status'] is None and len(changed.requests)==2


def test_geometric_delta_never_joins_pst_ids_or_fills_missing_zero():
    base={'id':'same-id','source_line_id':'line','coordinates':[(-10,5),(20,5)],'nain':1.,'nach':2.}
    after={**base,'id':'renumbered','coordinates':[(-10,5),(0,5)],'nain':3.}
    new={**base,'id':'same-id','coordinates':[(0,5),(5,8)],'nain':4.}
    diff=segment_diff([base],[after,new])
    assert diff[0]['delta']['nain']==2
    assert diff[1]['delta'] is None and diff[1]['before'] is None
    assert diff[2]['comparison_status']=='REMOVED'
    assert shape({'type':'LineString','coordinates':diff[2]['coordinates']}).length==20


def api_fixture(tmp_path):
    store=ProjectStateStore(tmp_path/'state.sqlite3')
    proposal={'type':'FeatureCollection','crs':{'properties':{'name':'EPSG:28992'}},'features':[
        {'type':'Feature','geometry':mapping(SITE),'properties':{'role':'site_area'}},
        feature('proposal',[(0,5),(5,8),(10,5)],role='road',width_m=4.5)]}
    proposal=json.loads(json.dumps(proposal))
    path=tmp_path/'proposal.geojson';path.write_text(json.dumps(proposal));sha='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
    store.create(entity_type='Artifact',entity_id='geo',project_id='project',payload={'id':'geo','uri':str(path),'sha256':sha})
    store.create(entity_type='Scenario',entity_id='scenario',project_id='project',payload={'id':'scenario','geometry_artifact_id':'geo','geometry_sha256':sha})
    root=tmp_path/'extract';root.mkdir()
    for mode,buffer in [('pedestrian',1500),('bicycle',6000)]:
        documents={'network':{'type':'FeatureCollection','crs':{'properties':{'name':'EPSG:28992'}},'features':NETWORK},'unlinks':[], 'study_area':mapping(SITE)}
        records={}
        for key,doc in documents.items():
            p=root/f'{key}-{mode}.json';p.write_text(json.dumps(doc));records[key]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        (root/f'extraction-manifest_{mode}_{buffer}m.json').write_text(json.dumps({'extraction':{'buffer_radius_m':buffer,'network_mode':mode},'inputs':{'study_area':records['study_area']},'outputs':{k:records[k] for k in ['network','unlinks']}}))
    app=FastAPI();app.include_router(create_scenario_syntax_router(store,tmp_path/'results',extraction_root=root))
    return TestClient(app),store,path,proposal


def test_api_real_job_persistence_stale_and_integrity(tmp_path):
    client,store,path,proposal=api_fixture(tmp_path)
    assert client.get('/api/v1/scenarios/scenario/syntax').json()['status']=='NOT_COMPUTED'
    response=client.post('/api/v1/scenarios/scenario/syntax',json={'mode':'pedestrian'})
    assert response.status_code==202
    result=client.get('/api/v1/scenarios/scenario/syntax').json()
    assert result['status']=='COMPUTED' and result['before'] and result['after'] and result['diff']
    assert store.current(result['job_id']).payload['status']=='succeeded'
    # Building-only changes leave the road result current.
    proposal['features'].append({'type':'Feature','geometry':mapping(box(2,2,3,3)),'properties':{'role':'new_building'}})
    publication=0
    def publish():
        nonlocal publication
        publication+=1
        new_path=path.with_name(f'proposal-{publication}.geojson');new_path.write_text(json.dumps(proposal))
        sha='sha256:'+hashlib.sha256(new_path.read_bytes()).hexdigest();identifier=f'geo-{publication}'
        store.create(entity_type='Artifact',entity_id=identifier,project_id='project',payload={'id':identifier,'uri':str(new_path),'sha256':sha})
        store.update('scenario',{'geometry_sha256':sha,'geometry_artifact_id':identifier})
    publish();assert client.get('/api/v1/scenarios/scenario/syntax').json()['status']=='COMPUTED'
    from urban_design.analysis_lineage import analysis_results
    assert analysis_results(store,store.current('scenario'))[0]['freshness']=='current'
    proposal['features'][1]['geometry']['coordinates'][1]=[5,9];publish()
    stale=client.get('/api/v1/scenarios/scenario/syntax').json()
    assert stale['status']=='STALE' and stale['after'] is None and stale['diff']==[]
    assert analysis_results(store,store.current('scenario'))[0]['freshness']=='stale'
    assert client.post('/api/v1/scenarios/scenario/syntax',json={'mode':'bogus'}).status_code==422
    assert client.post('/api/v1/scenarios/missing/syntax',json={}).status_code==404


def test_api_failed_extract_hash_does_not_masquerade_as_computed(tmp_path):
    client,store,path,proposal=api_fixture(tmp_path)
    network=tmp_path/'extract/network-pedestrian.json';network.write_text('{}')
    response=client.post('/api/v1/scenarios/scenario/syntax',json={})
    result=client.get('/api/v1/scenarios/scenario/syntax').json()
    assert response.status_code==202 and result['status']=='failed'
    assert 'hash mismatch' in result['error']


def test_boundary_roads_remain_and_false_retention_is_blocked():
    boundary=feature('boundary',[(-10,0),(20,0)])
    result=merge_network([boundary], [road(coordinates=[(0,0),(5,5),(10,0)])], SITE,'pedestrian',MergeParameters())
    assert result['status']=='READY' and not result['removed']
    false=road(origin='retained',source_road_ids=['existing'])
    with pytest.raises(ValueError,match='retained geometry differs'):
        merge_network(NETWORK,[false],SITE,'pedestrian',MergeParameters())


def test_abandoned_job_is_outcome_unknown_not_retryable_success(tmp_path):
    client,store,path,proposal=api_fixture(tmp_path)
    store.create(entity_type='ToolExecution',entity_id='lost-job',project_id='project',payload={
        'id':'lost-job','status':'running','parameters':{'scenario_id':'scenario','mode':'pedestrian'},'output_artifact_refs':[]},action='CreateScenarioSyntaxJob')
    result=client.get('/api/v1/scenarios/scenario/syntax').json()
    assert result['status']=='OUTCOME_UNKNOWN'


def test_new_grade_crossing_is_a_pst_unlink_not_a_false_connection():
    bridge=feature('bridge',[(-10,5),(20,5)],layer=1)
    ground=feature('ground',[(5,-10),(5,20)],layer=0)
    keep=road(id='keep',origin='retained',source_road_ids=['ground'],coordinates=[(5,-10),(5,20)])
    crossing=road(id='bridge-proposal',coordinates=[(0,5),(10,5)],layer=1)
    result=merge_network([bridge,ground],[keep,crossing],SITE,'pedestrian',MergeParameters())
    assert result['status']=='READY'
    assert result['derived_unlinks']==[(5.,5.)]


def test_post_dispatch_worker_loss_is_outcome_unknown(tmp_path):
    from urban_design.syntax_engines.pst_adapter import PSTExecutionError
    _,store,path,proposal=api_fixture(tmp_path)
    class LostAdapter:
        def compute(self, request):
            raise PSTExecutionError('worker connection lost after dispatch')
    app=FastAPI();app.include_router(create_scenario_syntax_router(store,tmp_path/'loss-results',
        extraction_root=tmp_path/'extract',adapter_factory=LostAdapter))
    client=TestClient(app)
    response=client.post('/api/v1/scenarios/scenario/syntax',json={})
    assert response.status_code==202
    result=client.get('/api/v1/scenarios/scenario/syntax').json()
    assert result['status']=='OUTCOME_UNKNOWN'
    assert 'after dispatch' in result['error']
    assert not store.current(response.json()['job_id']).payload['output_artifact_refs']


def test_immutable_scenario_input_tampering_is_blocked_even_if_roads_match(tmp_path):
    client,store,path,proposal=api_fixture(tmp_path)
    assert client.post('/api/v1/scenarios/scenario/syntax',json={}).status_code==202
    proposal['features'].append({'type':'Feature','geometry':mapping(box(2,2,3,3)),'properties':{'role':'new_building'}})
    path.write_text(json.dumps(proposal))
    sha='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
    store.update('geo',{'sha256':sha});store.update('scenario',{'geometry_sha256':sha})
    assert client.get('/api/v1/scenarios/scenario/syntax').status_code==409


def test_weld_endpoints_joins_floating_point_junction_gaps():
    from shapely.geometry import LineString
    from urban_design.scenario_syntax import _feature, _weld_endpoints
    a = _feature('context-a', LineString([(0, 0), (10.0, 0)]), {})
    b = _feature('proposal:main:part:0', LineString([(10.00047, 0.0003), (20, 0)]), {'proposal': True})
    c = _feature('proposal:far', LineString([(10.2, 0), (10.2, 5)]), {'proposal': True})
    welded, dropped = _weld_endpoints([a, b, c], [], 1e-6)
    assert dropped == []
    assert welded[1]['geometry']['coordinates'][0] == welded[0]['geometry']['coordinates'][-1] == (10.0, 0.0)
    assert welded[2]['geometry']['coordinates'][0] == (10.2, 0.0)  # 20 cm away: a real, separate node


def test_weld_endpoints_respects_unlinks_and_layers():
    from shapely.geometry import LineString, Point
    from urban_design.scenario_syntax import _feature, _weld_endpoints
    a = _feature('a', LineString([(0, 0), (10, 0)]), {})
    b = _feature('b', LineString([(10.01, 0), (20, 0)]), {'proposal': True, 'layer': 1})
    c = _feature('c', LineString([(10.01, 0.01), (10, 9)]), {'proposal': True})
    welded, _ = _weld_endpoints([a, b, c], [], 1e-6)
    assert welded[1]['geometry']['coordinates'][0] == (10.01, 0.0)  # other layer: untouched
    assert welded[2]['geometry']['coordinates'][0] == (10.0, 0.0)
    welded, _ = _weld_endpoints([a, c], [Point(10, 0)], 1e-6)
    assert welded[1]['geometry']['coordinates'][0] == (10.01, 0.01)  # unlinked node never welded


def test_segment_diff_tolerates_micro_segments_without_support():
    from urban_design.scenario_syntax import segment_diff
    before = [{'id': 'b', 'source_line_id': 'b', 'coordinates': [(0, 0), (10, 0)], 'nain': 1.0, 'nach': 1.0}]
    after = [{'id': 'a', 'source_line_id': 'a', 'coordinates': [(5, 5), (5, 5.0000015)], 'nain': .5, 'nach': .5}]
    row = segment_diff(before, after)[0]
    assert row['before'] is None and row['comparison_status'] == 'NEW_OR_CHANGED_GEOMETRY'


def test_trim_near_collinear_removes_millimetre_offset_overlap_but_keeps_crossings():
    from shapely.geometry import LineString
    from urban_design.scenario_syntax import _feature, _trim_near_collinear
    context = _feature('way/1:part:5', LineString([(0, 0), (10, 0)]), {})
    parallel = _feature('proposal:road-34:part:2', LineString([(-5, 0.003), (10, 0.003)]), {'proposal': True})
    crossing = _feature('proposal:road-9', LineString([(5, -5), (5, 5)]), {'proposal': True})
    out, trimmed = _trim_near_collinear([context, parallel, crossing], 1e-6)
    assert trimmed == ['proposal:road-34:part:2']
    ids = [f['id'] for f in out]
    assert 'way/1:part:5' in ids and 'proposal:road-9' in ids
    rest = [f for f in out if f['id'].startswith('proposal:road-34')]
    assert len(rest) == 1 and abs(LineString(rest[0]['geometry']['coordinates']).length - 5) < 0.01
