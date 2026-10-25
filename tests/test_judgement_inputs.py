"""Assemblers restate persisted bytes; missing measurements are never calculated."""
import pytest

from urban_design.judgement.core import Registry, digest
from urban_design.judgement.inputs import assemble


def test_real_climate_values_and_scenarios():
    registry = Registry()
    bundle = assemble(None, 'fixture-project', 'J-CLIMATE', ['harbour_grain'], registry)
    metrics = bundle['metrics']
    if 'DATA_GAP:e1.*' in bundle['data_gaps']:
        pytest.skip('real climate artifacts unavailable')
    assert metrics['e1.harbour.all.winter.mean_h']['value'] == 2.155
    assert metrics['e1.harbour.courtyard.winter.mean_h']['value'] == 0.108
    assert metrics['utci.harbour.all.very_strong_pct']['value'] == 26.4
    assert metrics['e3.harbour.eui_kwh_m2']['value'] == 93.36031702270336
    assert metrics['e4.harbour.mass.overheat_h']['value'] == 840.3619688498885
    assert metrics['e4.harbour.mass.overheat_h']['scenario'] == 'cooling off'
    assert metrics['e5.harbour.SW.mean_ratio']['value'] == 0.39
    # No percentage is calculated from E2 delta/baseline.
    assert 'DATA_GAP:e2.harbour_vs_mixed.hb_0h_kwh_m2.pct' in bundle['data_gaps']
    assert 'e2.harbour_vs_mixed.hb_0h_kwh_m2.pct' not in metrics
    assert digest(bundle) == digest(assemble(None, 'fixture-project', 'J-CLIMATE', ['harbour_grain'], registry))
    for item in bundle['inputs']:
        assert item['source_path']
        assert len(item['source_sha256']) == 64


def test_empty_artifacts_become_gaps(tmp_path):
    class EmptyRegistry:
        root = tmp_path
    bundle = assemble(None, 'fixture', 'J-CLIMATE', ['harbour_grain'], EmptyRegistry())
    assert not bundle['metrics']
    assert 'DATA_GAP:e1.*' in bundle['data_gaps']
    assert 'DATA_GAP:e5.harbour.SW.mean_ratio' in bundle['data_gaps']
    assert digest(bundle) == digest(assemble(None, 'fixture', 'J-CLIMATE', ['harbour_grain'], EmptyRegistry()))


def test_compare_contains_only_climate_summary():
    bundle = assemble(None, 'fixture', 'J-COMPARE', ['courtyard_islands'], Registry())
    if 'DATA_GAP:e1.*' in bundle['data_gaps']:
        pytest.skip('real climate artifacts unavailable')
    assert 'e1.courtyard.courtyard.winter.mean_h' in bundle['metrics']
    assert 'utci.courtyard.all.very_strong_pct' in bundle['metrics']
    assert not any(key.startswith(('e4.', 'e5.')) for key in bundle['metrics'])
    assert 'designer.stance.courtyard_role' in bundle['metrics']


def test_site_uses_persisted_geometry_no_derived_counts():
    bundle = assemble(None, 'fixture', 'J-SITE', [], Registry())
    if 'site.design_area_m2' not in bundle['metrics']:
        pytest.skip('real site plan unavailable')
    assert bundle['metrics']['site.design_area_m2']['value'] == 226064.3
    assert bundle['metrics']['site.retained_buildings']['value'] > 0
    assert 'DATA_GAP:site.waterfront_length_m' in bundle['data_gaps']
    assert 'DATA_GAP:evidence_card.*' in bundle['data_gaps']
    assert any(key.startswith('problem.') for key in bundle['metrics'])


def test_site_only_consumes_verified_persistence_results(monkeypatch):
    import urban_design.analysis_persistence as persistence
    cards = [
        {'card_id': 'valid-card', 'status': 'SOURCE_ALIGNED_COVERAGE_LIMITED', 'value': 17.5, 'unit': '%'},
        {'card_id': 'invalid-card', 'status': 'UNVERIFIED', 'value': 999, 'unit': '%'},
    ]
    monkeypatch.setattr(persistence, 'get_persisted_site_analysis', lambda *args: ({}, cards, 'VERIFIED_SOURCE_RESULT_ALIGNMENT', 'a'*64, []))
    monkeypatch.setattr(persistence, 'get_persisted_syntax_bundle', lambda *args: {'status': 'EXPLORATORY_CANDIDATE', 'layers': [{'calculation_status': 'COMPUTED', 'network_mode': 'pedestrian', 'metric_key': 'nain', 'radius_m': 800, 'statistics': {'mean': 0.7828}, 'unit': 'NAIN (normalized)', 'evidence_level': 'EXPLORATORY'}]})
    bundle = assemble(object(), 'fixture', 'J-SITE', [], Registry(), source_catalog=object())
    assert bundle['metrics']['evidence_card:valid-card']['value'] == 17.5
    assert 'evidence_card:invalid-card' not in bundle['metrics']
    assert bundle['references']['evidence_card']['valid-card']['coverage_limited']
    assert bundle['metrics']['syntax.context.ped.nain.800.network.mean']['value'] == 0.7828
    assert 'syntax.context.ped.nain.800.site_mean_pctl' not in bundle['metrics']
    monkeypatch.setattr(persistence, 'get_persisted_site_analysis', lambda *args: ({}, cards, 'STALE', 'a'*64, []))
    stale = assemble(object(), 'fixture', 'J-SITE', [], Registry(), source_catalog=object())
    assert 'evidence_card:valid-card' not in stale['metrics']


def test_selected_formal_harbour_applies_to_climate_and_compare():
    from types import SimpleNamespace
    class Store:
        def list_current(self, kind, **kwargs):
            if kind != 'HumanDecision':
                return []
            return [SimpleNamespace(entity_id='decision-real-target', payload={
                'action': 'Accept', 'status': 'accepted',
                'target_id': 'formal-fabric-harbour-grain-88445febe1b6',
                'timestamp': '2026-10-16T17:18:25.186389Z'})]
    for skill in ('J-CLIMATE', 'J-COMPARE'):
        bundle = assemble(Store(), 'fixture', skill, ['harbour_grain'], Registry())
        assert bundle['metrics']['decision.selected_scheme']['value'] == 'harbour_grain'
        assert 'DATA_GAP:decision.selected_scheme' not in bundle['data_gaps']


def test_real_e2_delta_and_motor_descriptive_percentiles():
    bundle = assemble(None, 'fixture', 'J-COMPARE', ['harbour_grain'], Registry())
    metrics = bundle['metrics']
    if 'e2.harbour_vs_mixed.hb_0h_kwh_m2.delta' not in metrics:
        pytest.skip('real E2 artifact unavailable')
    assert metrics['e2.harbour_vs_mixed.hb_0h_kwh_m2.delta']['value'] == -37.33698544934032
    assert 'DATA_GAP:e2.harbour_vs_mixed.hb_0h_kwh_m2.pct' in bundle['data_gaps']
    assert metrics['syntax.harbour.car.main_street_pctl']['scope'] == 'descriptive_intent'


def test_verified_observation_keeps_coverage_limit(monkeypatch):
    import urban_design.analysis_persistence as persistence
    card = {'card_id': 'legacy', 'status': 'VERIFIED_OBSERVATION', 'value': 3, 'unit': 'count'}
    monkeypatch.setattr(persistence, 'get_persisted_site_analysis', lambda *args: ({}, [card], 'VERIFIED_SOURCE_RESULT_ALIGNMENT', 'a'*64, []))
    monkeypatch.setattr(persistence, 'get_persisted_syntax_bundle', lambda *args: {'status': 'STALE', 'layers': []})
    bundle = assemble(object(), 'fixture', 'J-SITE', [], Registry(), source_catalog=object())
    assert bundle['references']['evidence_card']['legacy']['coverage_limited'] is True
    assert bundle['metrics']['evidence_card:legacy']['value'] == 3
    assert not any(key.startswith('syntax.context.') for key in bundle['metrics'])


def test_persisted_new_primary_street_percentile_is_not_recomputed():
    bundle = assemble(None, 'fixture', 'J-COMPARE', ['courtyard_islands'], Registry())
    metric = bundle['metrics'].get('syntax.courtyard.ped.new_segments_pctl')
    if metric is None:
        pytest.skip('real Commander findings artifact unavailable')
    assert metric['value'] == 37.6
    assert metric['source_path'].endswith('v3-recompute-finding-zh.md')
    assert '60%' in metric['limitations']


def test_compact_projection_has_one_metric_map_and_bounded_text():
    from urban_design.judgement.inputs import compact_projection
    bundle = {'subject': {'kind': 'site', 'ids': ['p']}, 'metrics': {
        'intent.harbour.summary': {'value': '文' * 900, 'unit': None, 'source_sha256': 'a' * 64},
        'context.osm.summary': {'value': '文' * 900, 'unit': None},
        'check.harbour.failures': {'value': ['failure'] * 100, 'unit': None},
        'syntax.harbour.ped.new_street_ranking': {'value': [{'geometry': [1, 2]}] * 1000},
    }, 'references': {}, 'sources': {'x': 'a' * 64}, 'inputs': ['duplicate']}
    view = compact_projection(bundle, 'J-COMPARE')
    assert set(view['metrics']['intent.harbour.summary']) == {'value', 'unit'}
    assert len(view['metrics']['intent.harbour.summary']['value']) == 600
    assert len(view['metrics']['context.osm.summary']['value']) == 400
    assert len(view['metrics']['check.harbour.failures']['value']) <= 160
    assert 'syntax.harbour.ped.new_street_ranking' not in view['metrics']
    assert 'sources' not in view and 'inputs' not in view
    assert bundle['metrics']['intent.harbour.summary']['source_sha256'] == 'a' * 64


def test_compact_real_skills_fit_input_budget():
    import json
    from urban_design.judgement.inputs import compact_projection
    for skill in ('J-SITE', 'J-COMPARE', 'J-CLIMATE'):
        bundle = assemble(None, 'fixture', skill, [], Registry())
        view = compact_projection(bundle, skill)
        assert len(json.dumps(view, ensure_ascii=False).encode()) < 60000
        assert not any(key.endswith(('.retained_building_records', '.retained_road_records', '.new_street_ranking')) for key in view['metrics'])


def test_syntax_scope_comes_from_persisted_coverage(monkeypatch):
    import urban_design.analysis_persistence as persistence
    monkeypatch.setattr(persistence, 'get_persisted_site_analysis', lambda *args: ({}, [], 'VERIFIED_SOURCE_RESULT_ALIGNMENT', 'a'*64, []))
    layers = [{'calculation_status': 'COMPUTED', 'network_mode': 'pedestrian',
               'metric_key': 'nain', 'radius_m': 800, 'statistics': {'mean': 0.7828},
               'unit': 'NAIN', 'coverage_scope': 'study_area_segments'}]
    monkeypatch.setattr(persistence, 'get_persisted_syntax_bundle', lambda *args: {'status': 'EXPLORATORY', 'layers': layers})
    bundle = assemble(object(), 'fixture', 'J-SITE', [], Registry(), source_catalog=object())
    assert bundle['metrics']['syntax.context.ped.nain.800.site.mean']['value'] == 0.7828
    assert 'syntax.context.ped.nain.800.network.mean' not in bundle['metrics']
    layers[0]['coverage_scope'] = 'whole_network'
    bundle = assemble(object(), 'fixture', 'J-SITE', [], Registry(), source_catalog=object())
    assert 'syntax.context.ped.nain.800.network.mean' in bundle['metrics']
    assert 'syntax.context.ped.nain.800.site.mean' not in bundle['metrics']


def test_syntax_missing_mode_radius_statistics_are_explicit_gaps(monkeypatch):
    import urban_design.analysis_persistence as persistence
    monkeypatch.setattr(persistence, 'get_persisted_site_analysis', lambda *args: ({}, [], 'VERIFIED_SOURCE_RESULT_ALIGNMENT', 'a'*64, []))
    monkeypatch.setattr(persistence, 'get_persisted_syntax_bundle', lambda *args: {
        'status': 'EXPLORATORY', 'layers': [{
            'calculation_status': 'COMPUTED', 'network_mode': 'pedestrian',
            'metric_key': 'nain', 'radius_m': 800, 'statistics': {'mean': 0.7828},
            'unit': 'NAIN', 'coverage_scope': 'study_area_segments'}]})
    bundle = assemble(object(), 'fixture', 'J-SITE', [], Registry(), source_catalog=object())
    assert 'DATA_GAP:syntax.context.ped.nain.800.statistics' not in bundle['data_gaps']
    for mode in ('ped', 'bike', 'car'):
        for radius in (800, 2000, 10000):
            for metric in ('nain', 'nach'):
                if (mode, radius, metric) != ('ped', 800, 'nain'):
                    assert f'DATA_GAP:syntax.context.{mode}.{metric}.{radius}.statistics' in bundle['data_gaps']
