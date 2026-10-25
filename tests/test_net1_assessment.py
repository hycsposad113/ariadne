import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('net1_export', Path(__file__).resolve().parents[1] / 'scripts/export_net1_syntax.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def report(mode, primary=80, waterfront=50):
    return {'fabric_id': 'test', 'mode': mode, 'intents': [{'intent_en': 'primary_street', 'percentile': primary}, {'intent_en': 'waterfront_path', 'percentile': waterfront}] + [{'intent_en': 'connection ' + target, 'percentile': 20, 'status': 'not met', 'direct_join_road_ids': ['road']} for target in ('Keileweg', 'Dakpark')]}


@pytest.mark.parametrize('mode,value,expected', [('pedestrian',80,'PASS'),('pedestrian',79.999,'FAIL'),('bicycle',70,'PASS'),('bicycle',69.999,'FAIL')])
def test_primary_explicit_threshold(mode, value, expected):
    assert module.assess(report(mode, value), [[0,0],[1,1]])['status'] == expected


def test_waterfront_threshold_missing_and_direct_counts_preserve_int3():
    source = report('pedestrian')
    assert module.assess(source, [[0,0],[1,1]])['status'] == 'PASS'
    assert source['intents'][2]['status'] == 'not met'
    source['intents'][1]['percentile'] = 49.999
    assert module.assess(source, [[0,0],[1,1]])['status'] == 'FAIL'
    source['intents'][2].update(status='unavailable', direct_join_road_ids=[])
    check = module.assess(source, [])['checks'][2]
    assert check['status'] == 'UNAVAILABLE' and check['value'] is None
    source['intents'][2]['status'] = 'not met'
    assert module.assess(source, [])['checks'][2]['status'] == 'FAIL'


def test_geometric_joins_unique_exclude_unlinks_and_parallel_proximity():
    plan = {'roads': [{'id':'water', 'properties':{'role':'waterfront_path'}}, {'id':'road', 'properties':{'role':'primary_street'}}]}
    full = {'after':{'segments':[{'source_line_id':'proposal:water','coordinates':[[0,0],[10,0]]}, {'source_line_id':'proposal:road','coordinates':[[2,-1],[2,1]]}, {'source_line_id':'external','coordinates':[[5,-1],[5,1]]}, {'source_line_id':'near','coordinates':[[8,.0005],[8,1]]}]},'merge':{'connection_points':[],'derived_unlinks':[[5,0]]}}
    assert module.waterfront_joins(full, plan) == [[2.,0.]]


def test_existing_run5_authored_contact_does_not_count_as_net1_added_contact():
    source = report('pedestrian')
    checks = module.assess(source, [[0,0],[1,1]], {'net1-new'})['checks']
    assert checks[2]['status'] == 'FAIL' and checks[2]['value'] == 0
    source['intents'][2]['direct_join_road_ids'].append('net1-new')
    assert module.assess(source, [[0,0],[1,1]], {'net1-new'})['checks'][2]['value'] == 1


def test_motor_descriptive_and_no_overwrite_incomplete_inputs(tmp_path):
    assert module.assess(report('motor_vehicle'), [])['status'] == 'DESCRIPTIVE_ONLY'
    with pytest.raises(ValueError, match='12 compact'):
        module.export(tmp_path, tmp_path)


def test_existing_round_refuses_before_source_parsing(tmp_path):
    source = tmp_path / 'syntax'
    source.mkdir()
    for fabric in ('a','b','c','d'):
        for mode in ('pedestrian','bicycle','motor_vehicle'):
            (source / f'{fabric}-{mode}.json').write_text('{}')
    retained = tmp_path / 'net1-assessment.json'
    retained.write_text('preserved')
    with pytest.raises(ValueError, match='no overwrite'):
        module.export(source, tmp_path)
    assert retained.read_text() == 'preserved'
    assert not (source / 'segments').exists()


def test_waterfront_internal_street_join_excludes_waterfront_detour():
    plan = {'roads': [{'id': key, 'properties': {'role': role}} for key, role in [('water', 'waterfront_path'), ('detour', 'waterfront_detour'), ('street', 'primary_street')]]}
    full = {'after': {'segments': [{'source_line_id': 'proposal:' + key, 'coordinates': coordinates} for key, coordinates in [('water', [[0,0],[10,0]]), ('detour', [[2,-1],[2,1]]), ('street', [[7,-1],[7,1]])]]}, 'merge': {'connection_points': [], 'derived_unlinks': []}}
    assert module.waterfront_joins(full, plan) == [[7.,0.]]
    full['merge']['derived_unlinks'] = [[7,0]]
    assert module.waterfront_joins(full, plan) == []


def test_blocked_compacts_preserved_without_geojson(tmp_path):
    import json
    source = tmp_path / 'syntax'
    source.mkdir()
    for fabric in ('a', 'b', 'c', 'd'):
        for mode in ('pedestrian', 'bicycle', 'motor_vehicle'):
            (source / f'{fabric}-{mode}.json').write_text(json.dumps({'status':'BLOCKED', 'fabric_id':fabric, 'mode':mode, 'error':'division by zero'}))
    result = module.export(source, tmp_path)
    assert len(result['reports']) == 12
    assert not list((source / 'segments').glob('*.geojson'))
    for record in result['reports']:
        assert record['export'] is None and record['error'] == 'division by zero'
        assert record['net1_assessment']['status'] == 'BLOCKED'
        assert all(c['status'] == 'UNAVAILABLE' and c['value'] is None for c in record['net1_assessment']['checks'])
    assert (tmp_path / 'net1-assessment.json').stat().st_size < 5_000_000
