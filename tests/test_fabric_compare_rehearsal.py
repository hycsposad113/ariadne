"""隔離演練的 HTTP 失敗證據契約；不啟動服務或瀏覽器。"""
import importlib.util
import copy
from pathlib import Path
from types import SimpleNamespace
import pytest


def test_http_503_records_endpoint_without_console_message():
    path = Path(__file__).resolve().parents[1] / 'web/e2e/fabric_compare.py'
    spec = importlib.util.spec_from_file_location('fabric_compare_rehearsal', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {'http_503': []}
    module.record_response(report, SimpleNamespace(status=200, url='http://fixture/health'))
    module.record_response(report, SimpleNamespace(status=503, url='http://fixture/syntax/context'))
    assert report['http_503'] == [{'url': 'http://fixture/syntax/context', 'status': 503}]


@pytest.mark.parametrize('mutation', ['none', 'syntax', 'land', 'aggregation', 'explanation', 'statement', 'pending_statement', 'nonfinite', 'ranking', 'legacy_plan', 'legacy_syntax'])
def test_rehearsal_sidebar_acceptance_requires_complete_sources(mutation):
    path = Path(__file__).resolve().parents[1] / 'web/e2e/fabric_compare.py'
    spec = importlib.util.spec_from_file_location('fabric_compare_sources', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    detail = {'fabric_id': 'fixture', 'source_package': {'artifact_root': '/fixture/artifacts/fab1/run-8', 'syntax_root': '/fixture/artifacts/net2/round-7/syntax'}, 'land_use_table': [
        {'category': 'retained_buildings', 'category_zh': '保留建築', 'site_land_percent': 40},
        {'category': 'waterfront_public', 'category_zh': '水岸公共帶', 'site_land_percent': 60}],
        'design_statement_markdown': '設計說明', 'checks': {'failure_ids': ['WIDTH']},
        'check_explanations_zh': {'WIDTH': '道路寬度未通過檢查'},
        'syntax_summary': {'status': 'COMPUTED', 'computed_count': 12, 'results': [
            {'mode': mode, 'status': 'COMPUTED',
             'before': {'metrics': {'mean_integration_nain': 1., 'high_integration_length_m': 10.}},
             'after': {'metrics': {'mean_integration_nain': 1.1, 'high_integration_length_m': 11.}},
             'delta_mean_integration_nain': .1, 'new_street_ranking': [],
             'new_street_ranking_count': 0, 'new_street_ranking_truncated': False}
            for mode in ('pedestrian', 'bicycle', 'motor_vehicle')]}}
    if mutation == 'syntax': detail['syntax_summary']['computed_count'] = 2
    if mutation == 'land': detail['land_use_table'][0]['site_land_percent'] = 39
    if mutation == 'aggregation':
        row = detail['land_use_table'][0]
        row['site_land_percent'] = 20
        detail['land_use_table'].append(copy.deepcopy(row))
    if mutation == 'explanation': detail['check_explanations_zh'] = {}
    if mutation == 'statement': detail['design_statement_markdown'] = ''
    if mutation == 'pending_statement': detail['design_statement_markdown'] = '設計說明更新中'
    if mutation == 'nonfinite': detail['syntax_summary']['results'][0]['delta_mean_integration_nain'] = float('nan')
    if mutation == 'ranking': detail['syntax_summary']['results'][0]['new_street_ranking_truncated'] = True
    if mutation == 'legacy_plan': detail['source_package']['artifact_root'] = '/fixture/artifacts/fab1/run-7'
    if mutation == 'legacy_syntax': detail['source_package']['syntax_root'] = '/fixture/artifacts/net2/round-3/syntax'
    if mutation == 'none': assert module.check_detail(detail, 'fixture')['land_percent_total'] == 100
    else:
        with pytest.raises(AssertionError): module.check_detail(detail, 'fixture')


@pytest.mark.parametrize('area,accepted', [(.8836, True), (.84, False), (1.1, False)])
def test_rehearsal_requires_actual_site_bounds_coverage(area, accepted):
    path = Path(__file__).resolve().parents[1] / 'web/e2e/fabric_compare.py'
    spec = importlib.util.spec_from_file_location('fabric_compare_coverage', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    measured = {'basis': 'site-mercator-bounding-box', 'measurement': 'map-project',
                'width': .94, 'height': .94, 'area': area}
    page = SimpleNamespace(wait_for_function=lambda expression, arg, **kwargs: None,
                           locator=lambda selector: SimpleNamespace(evaluate=lambda expression: measured))
    if accepted:
        assert module.map_coverage(page, 'harbour_grain') == measured
    else:
        with pytest.raises(AssertionError, match='85%'):
            module.map_coverage(page, 'harbour_grain')


def test_3d_pixels_reject_black_blue_water_and_accept_building_surfaces():
    path = Path(__file__).resolve().parents[1] / 'web/e2e/fabric_compare.py'
    spec = importlib.util.spec_from_file_location('fabric_pixels', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.building_color_pixel_fraction([(11,15,23),(40,124,162),(56,189,248)]) == 0
    assert module.building_color_pixel_fraction([(113,90,76),(164,164,164)]) == .5
    assert module.building_color_pixel_fraction([(179,168,148),(182,176,164),(245,158,11),(196,151,145)]) == 0
    assert module.building_color_pixel_fraction([(11,15,23)]*99+[(113,90,76)]) == .01
