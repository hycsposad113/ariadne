import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.judgement.core import Registry, validate, digest
from urban_design.judgement.inputs import assemble, assemble_morph_inputs, FABRICS, compact_projection
from urban_design.judgement.service import compliance_checklist, strict_output_schema
from urban_design.judgement.router import create_judgement_router
from urban_design.store import ProjectStateStore
from test_judgement_service import card, Fake


def morph_card(bundle, registry):
    result = card()
    result.update(skill_id='J-MORPH', stage='morphology', subject=bundle['subject'], skill_version=registry.specs['J-MORPH']['version'])
    ref = next(iter(bundle['metrics']))
    for observation in result['observations']:
        observation['refs'] = [{'kind': 'metric', 'id': ref}]
    for reason in result['reasoning']:
        reason['knowledge_refs'] = ['KU-MOR-001']
    failures = [key.split('.check.')[1] for key in bundle['metrics'] if '.check.' in key and key.startswith('morph.')]
    result['limitations'] = ['資料缺口：仍缺少地籍與實際使用資料。']
    result['observations'][0]['text'] = '需要區分路網與量體問題：' + '、'.join(failures)
    return result


def test_registry_runtime_schema_preserves_source():
    registry = Registry()
    spec = registry.specs['J-MORPH']
    assert spec['stage'] == 'morphology'
    assert spec['lenses'] == ['L1', 'L2', 'L3', 'L4', 'L5']
    assert len(spec['required_knowledge_ids']) == 19
    assert 'J-MORPH' in strict_output_schema(registry.schema)['properties']['skill_id']['enum']
    source = json.loads((registry.root / 'knowledge/judgement/judgement-card.schema.json').read_text())
    assert set(source['properties']['skill_id']['enum']) <= set(registry.schema['properties']['skill_id']['enum'])


@pytest.mark.parametrize('fabric,short', FABRICS.items())
def test_real_four_fabric_inputs(fabric, short):
    registry = Registry()
    if not (registry.root / f'artifacts/fab1/run-8/{fabric}-plan.json').is_file():
        pytest.skip('real persisted plan unavailable')
    bundle = assemble_morph_inputs(fabric, registry=registry, project_id='fixture')
    prefix = f'morph.{short}.'
    assert prefix + 'param.block_short_m' in bundle['metrics']
    assert prefix + 'height.median' in bundle['metrics']
    assert any(key.startswith(prefix + 'bound.') for key in bundle['metrics'])
    assert digest(bundle) == digest(assemble_morph_inputs(fabric, registry=registry, project_id='fixture'))
    assert not any(key.startswith(('e1.', 'e5.')) for key in bundle['metrics'])
    assert any(key.startswith('designer.stance.') for key in bundle['metrics'])


def test_failed_checks_validator_and_checklist():
    registry = Registry()
    bundle = assemble_morph_inputs('harbour', registry=registry, project_id='fixture')
    result = morph_card(bundle, registry)
    assert not validate(result, bundle, registry.specs['J-MORPH'], registry.schema)
    result['observations'][0]['text'] = '需要區分路網與量體問題並繼續調查。'
    errors = validate(result, bundle, registry.specs['J-MORPH'], registry.schema)
    assert any(error.startswith('MORPH_FAILURE_OMITTED:') for error in errors)
    assert any('SOUTH_QUAY_FACADE_CONTINUITY' in item for item in compliance_checklist(bundle, registry.specs['J-MORPH']))
    result['limitations'].append('此方案已通過檢核，可以繼續進行。')
    assert 'FORBIDDEN_CLAIM_OR_EXTERNAL_REFERENCE' in validate(result, bundle, registry.specs['J-MORPH'], registry.schema)


def test_existing_post_fake_provider(tmp_path, monkeypatch):
    registry = Registry()
    bundle = assemble_morph_inputs('harbour', registry=registry, project_id='fixture')
    fake = Fake([morph_card(bundle, registry)])
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    monkeypatch.setenv('ARIADNE_LIVE', '1')
    store = ProjectStateStore(tmp_path / 'state.sqlite3')
    app = FastAPI()
    app.include_router(create_judgement_router(project_store=store, registry=registry,
        database=tmp_path / 'judgements.sqlite3', provider_factory=lambda *args: fake))
    client = TestClient(app)
    response = client.post('/api/v1/projects/fixture/ariadne/judgements', json={'skill_id':'J-MORPH','subject_ids':['harbour']})
    assert response.status_code == 200
    assert response.json()['status'] == 'VALIDATED', response.json()['validation_errors']
    assert fake.calls == 1


@pytest.mark.parametrize('subjects', [[], ['harbour', 'closed']])
def test_morph_requires_one_subject(subjects):
    with pytest.raises(ValueError, match='exactly one'):
        assemble(None, 'fixture', 'J-MORPH', subjects, Registry())


def test_harbour_exact_geometry_and_provenance():
    registry = Registry()
    path = registry.root / 'artifacts/fab1/run-8/harbour_grain-plan.json'
    if not path.is_file():
        pytest.skip('real persisted plan unavailable')
    bundle = assemble_morph_inputs('harbour', registry=registry, project_id='fixture')
    metrics = bundle['metrics']
    assert metrics['morph.harbour.param.block_short_m']['value'] == 68.6
    assert metrics['morph.harbour.height.median']['value'] == 18
    assert metrics['morph.harbour.courtyard.courtyard-0.h_north_edge_m']['value'] == 12.97
    assert metrics['morph.harbour.courtyard.courtyard-0.south_edge_height_max_m']['value'] == 18
    assert metrics['morph.harbour.bound.blocks.short_edge_m.minimum']['value'] == 68.6
    assert metrics['basis.harbour.blocks.short_edge_m']['value'].startswith('MEASURED_PRECEDENT_DERIVED')
    assert 'morph.harbour.check.SOUTH_QUAY_FACADE_CONTINUITY' in metrics
    assert len(metrics['morph.harbour.statement']['value']) <= 1200
    assert all(metric['source_sha256'] for metric in metrics.values())


def test_missing_morph_knowledge_is_explicit_gap(tmp_path):
    registry = Registry()
    registry.root = tmp_path
    registry.specs['J-MORPH']['missing_knowledge_ids'] = ['KU-MOR-001']
    bundle = assemble_morph_inputs('harbour', registry=registry, project_id='fixture')
    assert 'DATA_GAP:ku:KU-MOR-001' in bundle['data_gaps']
    assert 'DATA_GAP:morph.harbour.*' in bundle['data_gaps']


def test_failure_chinese_names_are_accepted_and_empty_courtyards_are_gaps():
    registry = Registry()
    bundle = assemble_morph_inputs('harbour', registry=registry, project_id='fixture')
    if 'morph.harbour.check.SOUTH_QUAY_FACADE_CONTINUITY' not in bundle['metrics']:
        pytest.skip('real persisted plan unavailable')
    result = morph_card(bundle, registry)
    labels = [m['label_zh'] for k, m in bundle['metrics'].items() if k.startswith('morph.') and '.check.' in k]
    assert '南碼頭立面連續性' in labels
    result['observations'][0]['text'] = '需要區分路網與量體問題：' + '、'.join(labels)
    assert not validate(result, bundle, registry.specs['J-MORPH'], registry.schema)
    for fabric in FABRICS:
        bundle = assemble_morph_inputs(fabric, registry=registry, project_id='fixture')
        plan = registry.root / f'artifacts/fab1/run-8/{fabric}-plan.json'
        if plan.is_file() and not json.loads(plan.read_text()).get('courtyards'):
            assert f'DATA_GAP:morph.{FABRICS[fabric]}.courtyard.*' in bundle['data_gaps']


def test_dictionary_numeric_bounds_are_in_numeric_whitelist():
    registry = Registry()
    bundle = assemble_morph_inputs('harbour', registry=registry, project_id='fixture')
    result = morph_card(bundle, registry)
    bundle['metrics']['morph.harbour.bound.test.maximum'] = {'value': 234.567891, 'unit': 'm'}
    result['observations'][1]['text'] = '字典探索上限為 234.567891，仍需你決定是否採用。'
    assert not validate(result, bundle, registry.specs['J-MORPH'], registry.schema)


def test_boolean_metric_accepts_true_false_strings_and_street_family():
    registry = Registry()
    bundle = assemble_morph_inputs('harbour', registry=registry, project_id='fixture')
    result = morph_card(bundle, registry)
    feasible = next(k for k in bundle['metrics'] if k.endswith('.feasible_within_catalogue') and bundle['metrics'][k]['value'] is False)
    result['observations'][1]['refs'] = [{'kind': 'metric', 'id': feasible, 'value': 'false', 'unit': None}]
    result['revision_directions'][0]['parameter_family'] = 'street_add_remove'
    errors = validate(result, bundle, registry.specs['J-MORPH'], registry.schema)
    assert not any(e.startswith('METRIC_VALUE_UNIT_MISMATCH') for e in errors)
    assert 'INVALID_PARAMETER_FAMILY' not in errors
    result['observations'][1]['refs'] = [{'kind': 'metric', 'id': feasible, 'value': 'true', 'unit': None}]
    assert any(e.startswith('METRIC_VALUE_UNIT_MISMATCH') for e in validate(result, bundle, registry.specs['J-MORPH'], registry.schema))
