"""INT1b 交付摘要的整體檢查；只讀取已計算結果，不取代 PST 計算。"""
import hashlib
import json
import math
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.fabric_plans_api import FABRICS, create_fabric_plans_router
from urban_design.scenario_syntax import MODES, verified_extract
from urban_design.syntax_engines.pst_adapter import verify_runtime
from urban_design.pst_syntax import DEFAULT_PST_MANIFEST

ROOT = Path(__file__).resolve().parents[1]


def test_verifier_refuses_incomplete_summary(tmp_path):
    import importlib.util
    import sys
    import pytest
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('verify_fabric_syntax', ROOT / 'scripts/verify_fabric_syntax.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    summary = tmp_path / 'summary.json'
    summary.write_text(json.dumps({'status': 'INCOMPLETE', 'computed_count': 2, 'expected_count': 12, 'results': []}))
    with pytest.raises(ValueError, match='十二組計算尚未完整'):
        module.verify(summary)


def test_delivered_twelve_syntax_results_and_api_projection():
    summary = json.loads((ROOT / 'artifacts/int1b/syntax/syntax-summary.json').read_text())
    assert summary['status'] == 'COMPUTED'
    assert summary['computed_count'] == summary['expected_count'] == 12
    assert {(row['fabric_id'], row['mode']) for row in summary['results']} == {
        (fabric, mode) for fabric in FABRICS for mode in MODES
    }
    for row in summary['results']:
        assert row['status'] == 'COMPUTED' and row['formal_result_eligible'] is False
        for phase in ('before', 'after'):
            assert math.isfinite(row[phase]['metrics']['mean_integration_nain'])
            assert row[phase]['metrics']['high_integration_length_m'] >= 0
        assert math.isfinite(row['delta_mean_integration_nain'])
        assert row['new_street_ranking_truncated'] is False
        assert row['new_street_ranking_count'] == len(row['new_street_ranking'])
        intermediate=row['complete_intermediate']
        full_path=Path(intermediate['path'])
        assert 'sha256:' + hashlib.sha256(full_path.read_bytes()).hexdigest() == intermediate['sha256']
        _,extract=verified_extract(row['mode'])
        assert row['source_receipts']['extract']==extract
        verify_runtime(DEFAULT_PST_MANIFEST)
        assert extract['pst_runtime_manifest_sha256']=='sha256:'+hashlib.sha256(DEFAULT_PST_MANIFEST.read_bytes()).hexdigest()
        receipt = row['retained_road_receipts']
        path = Path(receipt['path'])
        assert 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() == receipt['sha256']
        roads = json.loads(path.read_text())
        assert roads and all(road['supported'] and road['tolerance_m'] == .001 for road in roads)
        assert all(road['outside_tolerance_support_length_m'] == 0 for road in roads)
        plan = row['source_receipts']['plan']
        assert 'sha256:' + hashlib.sha256(Path(plan['path']).read_bytes()).hexdigest() == plan['sha256']
    app = FastAPI()
    app.include_router(create_fabric_plans_router())
    with TestClient(app) as api:
        for fabric in FABRICS:
            response = api.get(f'/api/v1/fabric-plans/{fabric}')
            assert response.status_code == 200
            detail = response.json()['syntax_summary']
            assert detail['computed_count'] == 12
            assert len(detail['results']) == 3
            assert all(row['fabric_id'] == fabric for row in detail['results'])


def test_compute_cache_never_reuses_changed_request_or_runtime():
    import importlib.util
    from shapely.geometry import box
    spec=importlib.util.spec_from_file_location('compute_fabric_syntax',ROOT/'scripts/compute_fabric_syntax.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    def compute(*args):
        calls.append(args); return [{'nain':len(calls)}]
    cache=module.ComputeCache(compute,{'sha256':'runtime-a'},'implementation-a')
    args=([{'id':'a'}],None,800,((1,2),),box(0,0,1,1))
    assert cache(*args)==cache(*args) and len(calls)==1
    for changed in (([{'id':'b'}],None,800,((1,2),),args[4]),
                    (args[0],None,2000,args[3],args[4]),
                    (args[0],None,800,((2,2),),args[4]),
                    (args[0],None,800,args[3],box(0,0,2,2))):
        before=len(calls);cache(*changed);assert len(calls)==before+1
    cache.runtime={'sha256':'runtime-b'};cache(*args);assert len(calls)==6
    cache.implementation='implementation-b';cache(*args);assert len(calls)==7


def test_compute_checkpoint_survives_process_resume_and_rejects_drift(tmp_path):
    import importlib.util
    import pytest
    from shapely.geometry import box
    spec=importlib.util.spec_from_file_location('compute_fabric_syntax',ROOT/'scripts/compute_fabric_syntax.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    def compute(*args):
        calls.append(args)
        return [{'nain': 1.25}]
    args=([{'id':'a'}],None,800,((1,2),),box(0,0,1,1))
    assert module.ComputeCache(compute,{'sha256':'runtime-a'},'implementation-a',tmp_path)(*args)==[{'nain':1.25}]
    assert module.ComputeCache(compute,{'sha256':'runtime-a'},'implementation-a',tmp_path)(*args)==[{'nain':1.25}]
    assert len(calls)==1
    next(tmp_path.glob('*-segments.json')).write_text('[{"nain":999}]')
    with pytest.raises(ValueError,match='checkpoint receipt drift'):
        module.ComputeCache(compute,{'sha256':'runtime-a'},'implementation-a',tmp_path)(*args)
    assert len(calls)==1
