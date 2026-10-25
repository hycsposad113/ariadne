"""INT3 rehearsal contracts without starting a browser or service."""
import copy
import importlib.util
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / 'web/e2e/fabric_compare.py'
    spec = importlib.util.spec_from_file_location('int3_rehearsal', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def document():
    return {
        'type': 'FeatureCollection',
        'crs': {'type': 'name', 'properties': {'name': 'EPSG:28992'}},
        'legend_breaks': {'nain': [0, .2, .4, .6, .8, 1], 'nach': [0, .2, .4, .6, .8, 1]},
        'features': [{'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[89100, 435900], [89110, 435910]]},
                     'properties': {'segment_id': 'new', 'is_new_street': True, 'inside_site': True,
                                    'before_nain': None, 'after_nain': .5, 'delta_nain': None,
                                    'before_nach': None, 'after_nach': .7, 'delta_nach': None}}],
    }


def test_compact_contract_accepts_null_new_segments():
    assert module().check_segment_document(document())['segment_count'] == 1


def test_net1_rehearsal_preserves_unavailable_target_and_failed_measurements():
    data = document()
    data['net1_assessment'] = {'schema_version':'net1-assessment-v1','mode':'bicycle','status':'FAIL','formal_result_eligible':False,
        'checks':[{'target':name,'minimum':minimum,'value':value,'status':status} for name,minimum,value,status in
                  [('primary_street',70,40,'FAIL'),('connection Keileweg',1,1,'PASS'),('connection Dakpark',1,None,'UNAVAILABLE'),('waterfront multiple joins',2,3,'PASS')]]}
    assert module().check_net1_document(data,'bicycle')['status']=='FAIL'
    data['net1_assessment']['checks'][0]['minimum']=60
    with pytest.raises(AssertionError,match='threshold drift'):
        module().check_net1_document(data,'bicycle')


@pytest.mark.parametrize('mutation', ['zero_delta', 'nonfinite', 'crs', 'duplicate', 'breaks'])
def test_compact_contract_rejects_misleading_or_incomplete_evidence(mutation):
    data = document()
    if mutation == 'zero_delta':
        data['features'][0]['properties']['delta_nain'] = 0
    elif mutation == 'nonfinite':
        data['features'][0]['properties']['after_nain'] = float('nan')
    elif mutation == 'crs':
        data['crs']['properties']['name'] = 'EPSG:4326'
    elif mutation == 'duplicate':
        data['features'].append(copy.deepcopy(data['features'][0]))
    else:
        data['legend_breaks']['nain'] = [0, 1, .5, 1, 1, 1]
    with pytest.raises(AssertionError):
        module().check_segment_document(data)


def net2_document(mode='pedestrian'):
    baselines = {key: {'percentile': value, 'reference': reference, 'sample_count': 3, 'method': 'empirical_before_cdf'}
                 for key, value, reference in [('primary_meets', 53.125, 'Vierhavensstraat'),
                 ('primary_excellent', 74.5, 'Keileweg'), ('waterfront_meets', 38.5, 'frozen water sample')]}
    checks = [{'target': 'primary_street', 'value': 61, 'minimum': 53.125, 'excellent_minimum': 74.5, 'status': 'PASS'},
              {'target': 'connection Keileweg', 'value': 1, 'minimum': 1, 'status': 'PASS'},
              {'target': 'connection Dakpark', 'value': 1, 'minimum': 1, 'status': 'PASS'},
              {'target': 'waterfront multiple joins', 'value': 2, 'minimum': 2, 'status': 'PASS'}]
    if mode == 'pedestrian': checks.append({'target': 'waterfront_path', 'value': 45, 'minimum': 38.5, 'status': 'PASS'})
    return {'net2_assessment': {'schema_version': 'net2-assessment-v1', 'mode': mode,
        'status': 'DESCRIPTIVE_ONLY' if mode == 'motor_vehicle' else 'PASS', 'formal_result_eligible': False,
        'baselines': baselines, 'checks': [] if mode == 'motor_vehicle' else checks}}


def test_net2_rehearsal_uses_measured_baselines_without_fixed_thresholds():
    data = net2_document()
    assert module().check_net2_document(data, 'pedestrian')['status'] == 'PASS'
    data['net2_assessment']['checks'][0]['minimum'] = 50
    with pytest.raises(AssertionError, match='measured baseline'):
        module().check_net2_document(data, 'pedestrian')


@pytest.mark.parametrize('mode', ['pedestrian', 'bicycle'])
@pytest.mark.parametrize('missing', ['all', 'primary_street', 'connection Keileweg', 'connection Dakpark', 'waterfront multiple joins', 'waterfront_path'])
def test_net2_rejects_missing_required_checks(mode, missing):
    if mode == 'bicycle' and missing == 'waterfront_path': return
    data = net2_document(mode)
    data['net2_assessment']['checks'] = [c for c in data['net2_assessment']['checks'] if missing != 'all' and c['target'] != missing]
    with pytest.raises(AssertionError, match='required checks'):
        module().check_net2_document(data, mode)


@pytest.mark.parametrize('mutation', ['status', 'checks'])
def test_net2_motor_is_descriptive_only(mutation):
    data = net2_document('motor_vehicle')
    assert module().check_net2_document(data, 'motor_vehicle')['status'] == 'DESCRIPTIVE_ONLY'
    if mutation == 'status': data['net2_assessment']['status'] = 'PASS'
    else: data['net2_assessment']['checks'] = net2_document()['net2_assessment']['checks']
    with pytest.raises(AssertionError): module().check_net2_document(data, 'motor_vehicle')


def test_net2_unavailable_value_still_requires_matching_known_baseline():
    data = net2_document()
    check = data['net2_assessment']['checks'][0]
    check.update(value=None, status='UNAVAILABLE')
    data['net2_assessment']['status'] = 'UNAVAILABLE'
    assert module().check_net2_document(data, 'pedestrian')['status'] == 'UNAVAILABLE'
    check['minimum'] = 1
    with pytest.raises(AssertionError, match='measured baseline'): module().check_net2_document(data, 'pedestrian')


@pytest.mark.parametrize('field', ['reference', 'sample_count', 'method'])
def test_net2_requires_inspectable_baseline_metadata(field):
    data = net2_document()
    del data['net2_assessment']['baselines']['primary_meets'][field]
    with pytest.raises(AssertionError): module().check_net2_document(data, 'pedestrian')
