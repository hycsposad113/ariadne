import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.fabric_syntax_segments import receipt,verify,load_verified,build,SegmentCollection,display_breaks
from urban_design.fabric_plans_api import create_fabric_plans_router,FABRICS
ROOT=Path(__file__).resolve().parents[1]/'artifacts/int1b/syntax'

def test_missing_and_mismatch_fail_closed(tmp_path):
    p=tmp_path/'x';p.write_text('original');r=receipt(p);p.write_text('changed')
    with pytest.raises(ValueError,match='BLOCKED'):verify(r)
    r['path']=str(tmp_path/'missing')
    with pytest.raises(ValueError,match='BLOCKED'):verify(r)

@pytest.mark.parametrize('fabric',FABRICS)
@pytest.mark.parametrize('mode',['pedestrian','bicycle','motor_vehicle'])
def test_actual_exports_and_api(fabric,mode):
    p=ROOT/'segments'/f'{fabric}-{mode}.geojson';doc=load_verified(p)
    assert p.stat().st_size<5_000_000
    assert doc['crs']['properties']['name']=='EPSG:28992'
    assert doc['metadata']['analysis_legend_breaks']==json.loads((ROOT/f'{fabric}-{mode}.json').read_text())['legend_breaks']
    assert doc['features']
    from shapely.geometry import shape,LineString
    compact=json.loads((ROOT/f'{fabric}-{mode}.json').read_text())
    full=json.loads(verify(compact['complete_intermediate']).read_text())
    assert doc['legend_breaks']==display_breaks(full)
    plan=json.loads(verify(compact['source_receipts']['plan']).read_text())
    scope=shape(plan['site']).buffer(1000)
    originals={r['id']:r for r in full['before']['segments'] if LineString(r['coordinates']).intersection(scope).length>0}
    exported_originals={f['properties']['segment_id'].removeprefix('before:'):f for f in doc['features'] if f['properties']['render_phase']=='before'}
    assert originals.keys()==exported_originals.keys()
    for identity,row in originals.items():
        for metric in ('nain','nach'):assert exported_originals[identity]['properties']['before_'+metric]==row[metric]
    for f in doc['features']:assert scope.buffer(.001).covers(shape(f['geometry']))
    assert 0<len(doc['intent_assessment']['top5_new'])<=5
    assert all(r['is_new_street'] and not r['role'].startswith('retained_') for r in doc['intent_assessment']['all_new_roads'])
    assert all(0<=r['nain_percentile']<=100 and 0<=r['nach_percentile']<=100 for r in doc['intent_assessment']['all_new_roads'])
    for f in doc['features']:
        props=f['properties']
        assert {'segment_id','before_nain','after_nain','delta_nain','before_nach','after_nach','delta_nach','is_new_street','inside_site'}<=props.keys()
        if props['comparison_status']!='MATCHED_GEOMETRY':assert props['delta_nain'] is None
    app=FastAPI();app.include_router(create_fabric_plans_router(artifact_root=ROOT.parents[1]/'fab1/run-5', syntax_root=ROOT))
    r=TestClient(app).get(f'/api/v1/fabric-plans/{fabric}/syntax/{mode}')
    assert r.status_code==200
    assert r.json()['metadata']['mode']==mode

def test_api_missing_export_503(tmp_path):
    app=FastAPI();app.include_router(create_fabric_plans_router(syntax_root=tmp_path))
    assert TestClient(app).get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian').status_code==503

def test_export_receipt_drift_503(tmp_path):
    segments=tmp_path/'segments';segments.mkdir();p=segments/'harbour_grain-pedestrian.geojson';p.write_text('{}');r=receipt(p)
    p.with_suffix('.receipt.json').write_text(json.dumps({'export':r}));p.write_text('{"drift":true}')
    app=FastAPI();app.include_router(create_fabric_plans_router(syntax_root=tmp_path))
    assert TestClient(app).get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian').status_code==503


def test_source_receipt_drift_503(tmp_path):
    segments=tmp_path/'segments';segments.mkdir()
    original=ROOT/'segments'/'harbour_grain-pedestrian.geojson'
    doc=json.loads(original.read_text())
    source=tmp_path/'compact.json';source.write_text('original')
    doc['metadata']['source_receipts']['compact']=receipt(source)
    p=segments/original.name;p.write_text(json.dumps(doc));p.with_suffix('.receipt.json').write_text(json.dumps({'export':receipt(p)}))
    source.write_text('changed')
    app=FastAPI();app.include_router(create_fabric_plans_router(syntax_root=tmp_path))
    assert TestClient(app).get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian').status_code==503


def test_build_rejects_missing_or_mismatched_full_receipt(tmp_path):
    compact=json.loads((ROOT/'harbour_grain-pedestrian.json').read_text())
    full=tmp_path/'full.json';full.write_text('original')
    compact['complete_intermediate']=receipt(full)
    p=tmp_path/'compact.json';p.write_text(json.dumps(compact))
    full.write_text('changed')
    with pytest.raises(ValueError,match='BLOCKED'):build(p)
    compact['complete_intermediate']['path']=str(tmp_path/'missing.json');p.write_text(json.dumps(compact))
    with pytest.raises(ValueError,match='BLOCKED'):build(p)


def test_delta_and_geometry_schema_fail_closed():
    doc=json.loads((ROOT/'segments'/'harbour_grain-pedestrian.geojson').read_text())
    feature=next(f for f in doc['features'] if f['properties']['comparison_status']=='MATCHED_GEOMETRY')
    feature['properties']['delta_nain']+=1
    with pytest.raises(ValueError,match='incomparable delta'):SegmentCollection.model_validate(doc)
    feature['properties']['delta_nain']-=1
    feature['geometry']={'type':'Point','coordinates':[89100,435900]}
    with pytest.raises(ValueError,match='invalid segment geometry'):SegmentCollection.model_validate(doc)


def test_connector_junctions_have_receipt_and_surviving_target_support():
    from shapely.geometry import LineString,Point
    compact=json.loads((ROOT/'harbour_grain-pedestrian.json').read_text())
    full=json.loads(verify(compact['complete_intermediate']).read_text())
    doc=load_verified(ROOT/'segments'/'harbour_grain-pedestrian.geojson')
    connection=next(r for r in doc['intent_assessment']['intents'] if r['intent_en']=='connection Keileweg')
    assert connection['roads'] and connection['direct_join_road_ids']
    for road in connection['roads']:
        road_lines=[LineString(r['coordinates']) for r in full['after']['segments'] if r['source_line_id'].startswith('proposal:'+road['road_id']+':') or r['source_line_id']=='proposal:'+road['road_id']]
        assert any(any(line.distance(Point(point))<=.001 for line in road_lines) for point in full['merge']['connection_points'])


def test_api_rejects_valid_receipted_export_for_different_fabric(tmp_path):
    segments=tmp_path/'segments';segments.mkdir()
    doc=json.loads((ROOT/'segments'/'harbour_grain-pedestrian.geojson').read_text())
    p=segments/'closed_block_extension-pedestrian.geojson';p.write_text(json.dumps(doc))
    p.with_suffix('.receipt.json').write_text(json.dumps({'export':receipt(p)}))
    app=FastAPI();app.include_router(create_fabric_plans_router(syntax_root=tmp_path))
    assert TestClient(app).get('/api/v1/fabric-plans/closed_block_extension/syntax/pedestrian').status_code==503
