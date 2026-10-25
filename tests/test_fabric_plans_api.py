"""Exploratory API artifact integration and fail-closed boundary checks."""
import hashlib
import json
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.fabric_plans_api import SOURCE_PAIRS, FABRICS, create_fabric_plans_router, resolve_source_roots

# Retained run-5 fixtures exercise API projection independently of run-6 generation.
ARTIFACT_ROOT = SOURCE_PAIRS['run5-int1b'][0]


def client(root=ARTIFACT_ROOT):
    app = FastAPI()
    app.include_router(create_fabric_plans_router(root))
    return TestClient(app)


def test_actual_four_plans_read_only_without_database(tmp_path):
    database = tmp_path / 'formal.sqlite'
    database.write_bytes(b'untouched database sentinel')
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    api = client()
    response = api.get('/api/v1/fabric-plans')
    assert response.status_code == 200
    assert [p['fabric_id'] for p in response.json()['plans']] == list(FABRICS)
    for key in FABRICS:
        response = api.get(f'/api/v1/fabric-plans/{key}')
        assert response.status_code == 200
        detail = response.json()
        assert detail['status'] == 'EXPLORATORY_DRAFT'
        assert detail['source_crs'] == 'EPSG:28992'
        assert detail['output_crs'] == 'EPSG:4326'
        assert detail['projected_crs'] == 'EPSG:28992'
        assert detail['land_use_table']
        assert detail['checks']['fabric_id'] == key
        assert set(detail['layers_projected']) == set(detail['layers'])
        for name, layer in detail['layers'].items():
            assert layer['type'] == 'FeatureCollection'
            assert layer['features'], name
            projected_layer = detail['layers_projected'][name]
            assert projected_layer['type'] == 'FeatureCollection'
            assert len(projected_layer['features']) == len(layer['features'])
        xy = detail['layers']['roads']['features'][0]['geometry']['coordinates'][0]
        assert 4 < xy[0] < 5 and 51 < xy[1] < 53
        projected_xy = detail['layers_projected']['roads']['features'][0]['geometry']['coordinates'][0]
        assert 80_000 < projected_xy[0] < 100_000 and 430_000 < projected_xy[1] < 450_000
        projected_building_properties = detail['layers_projected']['buildings']['features'][0]['properties']
        assert isinstance(projected_building_properties['height_m'], (int, float))
        assert isinstance(projected_building_properties['floors'], int)
        assert isinstance(projected_building_properties['retained'], bool)
        assert isinstance(detail['layers_projected']['roads']['features'][0]['properties']['hierarchy'], int)
        assert detail['layers']['land_use']['features'][0]['properties']['category'] == 'retained_buildings'
        assert api.post(f'/api/v1/fabric-plans/{key}', json={}).status_code == 405
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def fixture_root(tmp_path):
    key = 'harbour_grain'
    for suffix in ('plan.json', 'checks.json', 'landuse.csv'):
        shutil.copyfile(ARTIFACT_ROOT / f'{key}-{suffix}', tmp_path / f'{key}-{suffix}')
    return tmp_path


def test_missing_statement_and_late_statement_are_reloaded(tmp_path):
    root = fixture_root(tmp_path)
    api = client(root)
    url = '/api/v1/fabric-plans/harbour_grain'
    assert api.get(url).json()['design_statement_markdown'] == '設計說明更新中'
    directory = root / 'ai-explanations'
    directory.mkdir()
    statement = directory / 'harbour_grain-design-statement-zh.md'
    statement.write_text('新設計說明', encoding='utf-8')
    assert api.get(url).json()['design_statement_markdown'] == '新設計說明'
    statement.write_text('更新說明', encoding='utf-8')
    assert api.get(url).json()['design_statement_markdown'] == '更新說明'


@pytest.mark.parametrize('identifier', ['unknown', '..', '%2E%2E%2Fharbour_grain'])
def test_invalid_ids(identifier):
    assert client().get(f'/api/v1/fabric-plans/{identifier}').status_code == 404


@pytest.mark.parametrize('mutation', ['crs', 'nonfinite', 'identity'])
def test_invalid_source_fails_closed(tmp_path, mutation):
    root = fixture_root(tmp_path)
    path = root / 'harbour_grain-plan.json'
    plan = json.loads(path.read_text())
    if mutation == 'crs':
        plan['crs'] = 'EPSG:4326'
    elif mutation == 'nonfinite':
        plan['metrics']['fsi'] = float('nan')
    else:
        plan['fabric_id'] = 'fabric.courtyard_islands'
    path.write_text(json.dumps(plan))
    response = client(root).get('/api/v1/fabric-plans/harbour_grain')
    assert response.status_code == 503


def test_syntax_is_filtered_and_reloaded(tmp_path):
    root = fixture_root(tmp_path)
    directory = root / 'syntax'
    directory.mkdir()
    summary = directory / 'syntax-summary.json'
    summary.write_text(json.dumps({'results': [{'fabric_id': 'harbour_grain', 'mode': 'walk'}, {'fabric_id': 'courtyard_islands'}]}))
    response = client(root).get('/api/v1/fabric-plans/harbour_grain')
    assert response.json()['syntax_summary']['results'] == [{'fabric_id': 'harbour_grain', 'mode': 'walk'}]


def test_workspace_app_registration_does_not_mutate_store(tmp_path, monkeypatch):
    monkeypatch.setenv('URBAN_DESIGN_FABRIC_SOURCE', 'run5-int1b')
    from urban_design.api import create_workspace_app
    from urban_design.store import ProjectStateStore
    import sqlite3

    path = tmp_path / 'integration.sqlite3'
    store = ProjectStateStore(path)
    app = create_workspace_app(store=store, context_data_dir=tmp_path / 'context', scenario_artifact_root=tmp_path / 'scenarios')
    def snapshot():
        with sqlite3.connect(path) as connection:
            return tuple(connection.iterdump())
    before = snapshot()
    api = TestClient(app)
    assert api.get('/api/v1/fabric-plans').status_code == 200
    for fabric_id in FABRICS:
        assert api.get(f'/api/v1/fabric-plans/{fabric_id}').status_code == 200
    assert snapshot() == before


def test_unreadable_statement_does_not_hide_plan(tmp_path):
    root = fixture_root(tmp_path)
    directory = root / 'ai-explanations'
    directory.mkdir()
    statement = directory / 'harbour_grain-design-statement-zh.md'
    statement.write_bytes(b'\xff')
    response = client(root).get('/api/v1/fabric-plans/harbour_grain')
    assert response.status_code == 200
    assert response.json()['design_statement_markdown'] == '設計說明更新中'
    assert response.json()['layers']['buildings']['features']


def test_land_budget_summary_and_plain_language_checks():
    from shapely.geometry import shape
    api = client()
    for fabric_id in FABRICS:
        detail = api.get(f'/api/v1/fabric-plans/{fabric_id}').json()
        rows = detail['land_use_table']
        assert sum(row['site_land_percent'] for row in rows) == pytest.approx(100, abs=1e-6)
        plan = json.loads((ARTIFACT_ROOT / f'{fabric_id}-plan.json').read_text())
        for label in ('保留建築', '水岸公共帶'):
            grouped = [row for row in rows if row['category_zh'] == label]
            assert len(grouped) == 1
            # Match by original CSV IDs, independent of category taxonomy.
            import csv
            with (ARTIFACT_ROOT / f'{fabric_id}-landuse.csv').open(encoding='utf-8-sig') as stream:
                ids = {row['圖徵 ID'] for row in csv.DictReader(stream) if row['用途或類別'] == label}
            expected = sum(shape(f['geometry']).area for f in plan['land_use'] if f['id'] in ids)
            assert grouped[0]['area_m2'] == pytest.approx(expected)
        assert set(detail['check_explanations_zh']) == set(detail['checks']['failure_ids'])
        assert all('此項檢查' not in value for value in detail['check_explanations_zh'].values())
        assert detail['design_statement_markdown'] == (ARTIFACT_ROOT / 'ai-explanations' / f'{fabric_id}-design-statement-zh.md').read_text()


def test_explicit_new_syntax_root_prevents_legacy_fallback(tmp_path):
    root = fixture_root(tmp_path)
    legacy = root / 'syntax'
    legacy.mkdir()
    (legacy / 'syntax-summary.json').write_text(json.dumps({'results': [{'fabric_id': 'harbour_grain', 'source': 'legacy'}]}))
    current = tmp_path / 'int1b-syntax'
    current.mkdir()
    (current / 'syntax-summary.json').write_text(json.dumps({'results': [{'fabric_id': 'harbour_grain', 'source': 'int1b'}]}))
    app = FastAPI()
    app.include_router(create_fabric_plans_router(root, current))
    detail = TestClient(app).get('/api/v1/fabric-plans/harbour_grain').json()
    assert detail['syntax_summary']['results'][0]['source'] == 'int1b'


def test_pending_syntax_preserves_global_progress_and_reloads(tmp_path):
    root = fixture_root(tmp_path)
    current = tmp_path / 'int1b-syntax'
    current.mkdir()
    summary = current / 'syntax-summary.json'
    app = FastAPI()
    app.include_router(create_fabric_plans_router(root, current))
    api = TestClient(app)
    for count in (2, 3):
        summary.write_text(json.dumps({
            'status': 'INCOMPLETE', 'computed_count': count, 'expected_count': 12,
            'results': [{'fabric_id': 'harbour_grain', 'mode': 'pedestrian'},
                        {'fabric_id': 'courtyard_islands', 'mode': 'pedestrian'}],
        }))
        response = api.get('/api/v1/fabric-plans/harbour_grain')
        assert response.status_code == 200
        data = response.json()['syntax_summary']
        assert data['computed_count'] == count and data['expected_count'] == 12
        assert data['results'] == [{'fabric_id': 'harbour_grain', 'mode': 'pedestrian'}]


def test_stable_categories_cover_actual_csv_and_fail_closed(tmp_path):
    import csv
    from urban_design.fabric_plans_api import normalize_land_use_category
    observed = set()
    for fabric_id in FABRICS:
        with (ARTIFACT_ROOT / f'{fabric_id}-landuse.csv').open(encoding='utf-8-sig') as stream:
            expected = {normalize_land_use_category(row['用途或類別']) for row in csv.DictReader(stream)}
        rows = client().get(f'/api/v1/fabric-plans/{fabric_id}').json()['land_use_table']
        assert {row['category'] for row in rows} == expected
        assert len(rows) == len(expected)
        observed |= expected
        detail = client().get(f'/api/v1/fabric-plans/{fabric_id}').json()
        geometry_categories = {
            feature['properties']['category']
            for feature in detail['layers']['land_use']['features']
        }
        assert geometry_categories <= {'retained_buildings', 'waterfront_public', 'road', 'park', 'block', 'service', 'plaza', 'utility_yard', 'maintenance_green', 'shared_planting'}
        assert geometry_categories == {
            feature['properties']['category']
            for feature in detail['layers_projected']['land_use']['features']
        }
        assert {feature['properties']['category'] for feature in detail['layers']['parks']['features']} == {'park'}
    assert observed == {'retained_buildings', 'waterfront_public', 'road', 'park', 'block', 'service', 'utility_yard', 'maintenance_green', 'shared_planting'}
    assert normalize_land_use_category('廣場') == 'plaza'
    with pytest.raises(ValueError, match='Unknown land-use category'):
        normalize_land_use_category('未知分類 use-1')
    root = fixture_root(tmp_path)
    path = root / 'harbour_grain-landuse.csv'
    path.write_text(path.read_text(encoding='utf-8-sig').replace('保留建築', '未知分類'), encoding='utf-8')
    assert client(root).get('/api/v1/fabric-plans/harbour_grain').status_code == 503
    geometry_root = tmp_path / 'geometry-category'
    geometry_root.mkdir()
    fixture_root(geometry_root)
    plan_path = geometry_root / 'harbour_grain-plan.json'
    plan = json.loads(plan_path.read_text())
    plan['land_use'][0]['properties']['category'] = 'unknown_geometry_category'
    plan_path.write_text(json.dumps(plan))
    assert client(geometry_root).get('/api/v1/fabric-plans/harbour_grain').status_code == 503


def test_language_specific_statements_reload_without_chinese_fallback(tmp_path):
    root = fixture_root(tmp_path)
    directory = root / 'ai-explanations'
    directory.mkdir()
    (directory / 'harbour_grain-design-statement-zh.md').write_text('中文說明', encoding='utf-8')
    api = client(root)
    url = '/api/v1/fabric-plans/harbour_grain'
    assert api.get(url + '?lang=en').json()['design_statement_markdown'] == 'English design statement updating'
    statement = directory / 'harbour_grain-design-statement-en.md'
    for text in ('English statement', 'Updated statement'):
        statement.write_text(text, encoding='utf-8')
        assert api.get(url + '?lang=en').json()['design_statement_markdown'] == text
        assert api.get(url + '?lang=zh').json()['design_statement_markdown'] == '中文說明'
    assert api.get(url + '?lang=fr').status_code == 422
    for fabric_id in FABRICS:
        detail = client().get(f'/api/v1/fabric-plans/{fabric_id}?lang=en').json()
        assert set(detail['check_explanations_en']) == set(detail['check_explanations_zh']) == set(detail['checks']['failure_ids'])
        assert all('This check has not passed' not in value for value in detail['check_explanations_en'].values())
        assert detail['design_statement_markdown'] == (ARTIFACT_ROOT / 'ai-explanations' / f'{fabric_id}-design-statement-en.md').read_text()


def test_read_only_allowlisted_figures():
    api = client()
    for fabric_id in FABRICS:
        for kind, suffix in [('plan', 'massing'), ('axon', 'axon'), ('landuse', 'landuse')]:
            url = f'/api/v1/fabric-plans/{fabric_id}/figures/{kind}'
            response = api.get(url)
            assert response.status_code == 200
            assert response.headers['content-type'] == 'image/png'
            assert response.content == (ARTIFACT_ROOT / f'{fabric_id}-{suffix}-zh.png').read_bytes()
            assert api.post(url).status_code == 405
    assert api.get('/api/v1/fabric-plans/unknown/figures/plan').status_code == 404
    assert api.get('/api/v1/fabric-plans/harbour_grain/figures/checks').status_code == 422


def test_net1_download_plan_is_current_network_render():
    root, _ = SOURCE_PAIRS['net1']
    api = client(root)
    for fabric_id in FABRICS:
        response = api.get(f'/api/v1/fabric-plans/{fabric_id}/figures/plan')
        assert response.status_code == 200
        assert response.content == (root / f'{fabric_id}-net1-network-zh.png').read_bytes()


@pytest.mark.parametrize('label,category', [
    ('保留建築', 'retained_buildings'), ('水岸公共帶', 'waterfront_public'),
    ('道路', 'road'), ('街坊公共公園 use-16', 'park'),
    ('港灣綠軸公園 use-20', 'park'), ('港灣綠軸道路分界鄰里公園 use-17-road-unit-1', 'park'),
    ('街廓／建築用地', 'block'), ('西側點樓完整矩形街坊管理用地', 'block'),
    ('服務空間', 'service'), ('廣場', 'plaza'), ('街坊設備院 use-47', 'utility_yard'),
    ('街坊邊界綠化維護院 use-43', 'maintenance_green'),
    ('東北街坊共用植栽及維護空間', 'shared_planting'),
])
def test_explicit_land_use_label_mapping(label, category):
    from urban_design.fabric_plans_api import normalize_land_use_category
    assert normalize_land_use_category(label) == category


@pytest.mark.parametrize('source,category', [
    ('retained_buildings', 'retained_buildings'), ('waterfront', 'waterfront_public'),
    ('waterfront_public', 'waterfront_public'), ('roads', 'road'), ('road', 'road'),
    ('parks', 'park'), ('park', 'park'), ('blocks', 'block'), ('block', 'block'),
    ('service', 'service'), ('utility_yard', 'utility_yard'),
    ('maintenance_green', 'maintenance_green'), ('shared_planting', 'shared_planting'),
])
def test_explicit_geometry_category_mapping(source, category):
    from urban_design.fabric_plans_api import normalize_geometry_category
    assert normalize_geometry_category(source) == category


def test_default_and_explicit_legacy_source_pairs(monkeypatch):
    monkeypatch.delenv('URBAN_DESIGN_FABRIC_SOURCE', raising=False)
    root, syntax = resolve_source_roots()
    assert root.parts[-3:] == ('artifacts', 'fab1', 'run-8')
    assert syntax.parts[-4:] == ('artifacts', 'net2', 'round-7', 'syntax')
    monkeypatch.setenv('URBAN_DESIGN_FABRIC_SOURCE', 'net2-r3')
    assert resolve_source_roots() == SOURCE_PAIRS['net2-r3']
    monkeypatch.setenv('URBAN_DESIGN_FABRIC_SOURCE', 'run5-int1b')
    assert resolve_source_roots() == SOURCE_PAIRS['run5-int1b']
    api = FastAPI()
    api.include_router(create_fabric_plans_router())
    data = TestClient(api).get('/api/v1/fabric-plans/harbour_grain').json()
    assert data['source_package']['artifact_root'].endswith('/artifacts/fab1/run-5')
    assert data['source_package']['syntax_root'].endswith('/artifacts/int1b/syntax')
    assert data['syntax_summary']['computed_count'] == 12


@pytest.mark.parametrize('profile', ['net2', 'net2-r3', 'net1', 'run5-int1b'])
def test_known_sources_reject_cross_run_pair(profile):
    root = SOURCE_PAIRS[profile][0]
    other = SOURCE_PAIRS['run5-int1b' if profile == 'net1' else 'net1'][1]
    with pytest.raises(ValueError, match='pair mismatch'):
        resolve_source_roots(root, other)


def test_unknown_source_profile_fails_closed(monkeypatch):
    monkeypatch.setenv('URBAN_DESIGN_FABRIC_SOURCE', 'latest')
    with pytest.raises(ValueError, match='Unknown URBAN_DESIGN_FABRIC_SOURCE'):
        resolve_source_roots()


def test_syntax_summary_rejects_another_plan_receipt(tmp_path):
    root = fixture_root(tmp_path)
    syntax = root / 'syntax'
    syntax.mkdir()
    (syntax / 'syntax-summary.json').write_text(json.dumps({'results': [
        {'fabric_id': 'harbour_grain', 'source_receipts': {'plan': {'sha256': 'sha256:' + '0' * 64}}}
    ]}))
    assert client(root).get('/api/v1/fabric-plans/harbour_grain').status_code == 503


def test_syntax_segments_reject_another_selected_plan(monkeypatch):
    from urban_design import fabric_syntax_segments
    monkeypatch.setattr(fabric_syntax_segments, 'load_verified', lambda path: {
        'metadata': {'fabric_id': 'harbour_grain', 'mode': 'pedestrian',
                     'source_receipts': {'plan': {'sha256': 'sha256:' + '0' * 64}}}
    })
    response = client().get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian')
    assert response.status_code == 503
    assert 'BLOCKED' in response.json()['detail']


def test_segment_response_preserves_optional_net1_assessment(monkeypatch):
    from urban_design import fabric_syntax_segments
    source = SOURCE_PAIRS['run5-int1b'][1] / 'segments' / 'harbour_grain-pedestrian.geojson'
    document = json.loads(source.read_text())
    assessment = {'schema_version': 'net1-assessment-v1', 'status': 'FAIL',
                  'hard_targets_pass': False, 'formal_result_eligible': False,
                  'checks': [{'target': 'primary_street', 'value': None, 'minimum': 80, 'status': 'UNAVAILABLE'}]}
    document['net1_assessment'] = assessment
    monkeypatch.setattr(fabric_syntax_segments, 'load_verified', lambda path: document)
    response = client().get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian')
    assert response.status_code == 200
    assert response.json()['net1_assessment'] == assessment


def test_segment_response_preserves_optional_net2_assessment(monkeypatch):
    from urban_design import fabric_syntax_segments
    source = SOURCE_PAIRS['run5-int1b'][1] / 'segments' / 'harbour_grain-pedestrian.geojson'
    document = json.loads(source.read_text())
    assessment = {'schema_version': 'net2-assessment-v1', 'fabric_id': 'harbour_grain',
                  'mode': 'pedestrian', 'status': 'BLOCKED', 'hard_targets_pass': None,
                  'formal_result_eligible': False, 'baselines': {}, 'checks': []}
    document['net2_assessment'] = assessment
    monkeypatch.setattr(fabric_syntax_segments, 'load_verified', lambda path: document)
    response = client().get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian')
    assert response.status_code == 200
    assert response.json()['net2_assessment'] == assessment


def supplemental_checks(root, key='harbour_grain'):
    plan_path, raw_path = root / f'{key}-plan.json', root / f'{key}-checks.json'
    plan, raw = json.loads(plan_path.read_text()), json.loads(raw_path.read_text())
    wrapper = {'schema_version': 'fabric-api-checks-v1', 'fabric_id': key,
               'core_validator': raw['core_validator'], 'failure_ids': raw['failure_ids'],
               'source_receipts': {name: {'sha256': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()}
                                   for name, path in [('plan', plan_path), ('raw_checks', raw_path)]}}
    (root / f'{key}-api-checks.json').write_text(json.dumps(wrapper))
    return wrapper


@pytest.mark.parametrize('mutation', ['none', 'plan_receipt', 'raw_receipt', 'core', 'failures', 'identity', 'raw_identity', 'validation'])
def test_supplemental_checks_are_strictly_bound_to_plan_and_raw_checks(tmp_path, mutation):
    root = fixture_root(tmp_path)
    raw_path = root / 'harbour_grain-checks.json'
    raw = json.loads(raw_path.read_text())
    raw['fabric_id'] = 'fabric.harbour_grain'
    if mutation == 'raw_identity': raw['fabric_id'] = 'fabric.other'
    raw_path.write_text(json.dumps(raw))
    wrapper = supplemental_checks(root)
    if mutation == 'plan_receipt': wrapper['source_receipts']['plan']['sha256'] = 'sha256:' + '0' * 64
    if mutation == 'raw_receipt': wrapper['source_receipts']['raw_checks']['sha256'] = 'sha256:' + '0' * 64
    if mutation == 'core': wrapper['core_validator']['status'] = 'INVALID'
    if mutation == 'failures': wrapper['failure_ids'] = ['INVENTED']
    if mutation == 'identity': wrapper['fabric_id'] = 'other'
    if mutation == 'validation':
        plan_path = root / 'harbour_grain-plan.json'
        plan = json.loads(plan_path.read_text()); plan['validation']['status'] = 'INVALID'
        plan_path.write_text(json.dumps(plan))
        wrapper['source_receipts']['plan']['sha256'] = 'sha256:' + hashlib.sha256(plan_path.read_bytes()).hexdigest()
    (root / 'harbour_grain-api-checks.json').write_text(json.dumps(wrapper))
    response = client(root).get('/api/v1/fabric-plans/harbour_grain')
    assert response.status_code == (200 if mutation == 'none' else 503)


def test_qualified_raw_identity_without_supplement_remains_blocked(tmp_path):
    root = fixture_root(tmp_path)
    path = root / 'harbour_grain-checks.json'
    raw = json.loads(path.read_text()); raw['fabric_id'] = 'fabric.harbour_grain'
    path.write_text(json.dumps(raw))
    assert client(root).get('/api/v1/fabric-plans/harbour_grain').status_code == 503


def test_missing_ai_explanations_returns_updating_message(tmp_path):
    root = fixture_root(tmp_path)
    api = client(root)
    res_zh = api.get('/api/v1/fabric-plans/harbour_grain?lang=zh')
    assert res_zh.status_code == 200
    assert res_zh.json()['design_statement_markdown'] == '設計說明更新中'

    res_en = api.get('/api/v1/fabric-plans/harbour_grain?lang=en')
    assert res_en.status_code == 200
    assert res_en.json()['design_statement_markdown'] == 'English design statement updating'


def test_default_run8_returns_updating_statement_without_500(monkeypatch, tmp_path):
    # Copy of run-8 without ai-explanations: missing statements must degrade, not 500.
    import shutil
    from urban_design.fabric_plans_api import ARTIFACT_ROOT, SYNTAX_ROOT
    monkeypatch.delenv('URBAN_DESIGN_FABRIC_SOURCE', raising=False)
    root = tmp_path / 'run-8'
    shutil.copytree(ARTIFACT_ROOT, root, ignore=shutil.ignore_patterns('ai-explanations'))
    api = FastAPI()
    api.include_router(create_fabric_plans_router(artifact_root=root, syntax_root=SYNTAX_ROOT))
    test_client = TestClient(api)
    for fabric_id in FABRICS:
        res_zh = test_client.get(f'/api/v1/fabric-plans/{fabric_id}?lang=zh')
        assert res_zh.status_code == 200
        assert res_zh.json()['design_statement_markdown'] == '設計說明更新中'

        res_en = test_client.get(f'/api/v1/fabric-plans/{fabric_id}?lang=en')
        assert res_en.status_code == 200
        assert res_en.json()['design_statement_markdown'] == 'English design statement updating'


def test_verbatim_copy_flag_requires_byte_identical_source(tmp_path):
    from urban_design.fabric_plans_api import _verbatim_copy_ok
    plan_path = tmp_path / "courtyard_islands-plan.json"; plan_path.write_text('{"fabric_id":"fabric.courtyard_islands"}')
    src = tmp_path / "src-plan.json"; src.write_text(plan_path.read_text())
    plan = {"fabric_id": "fabric.courtyard_islands"}
    assert _verbatim_copy_ok({"copied_verbatim_from": str(src)}, plan, plan_path, "courtyard_islands")
    src.write_text('{"fabric_id":"fabric.courtyard_islands","x":1}')
    assert not _verbatim_copy_ok({"copied_verbatim_from": str(src)}, plan, plan_path, "courtyard_islands")
    assert not _verbatim_copy_ok({}, plan, plan_path, "courtyard_islands")
    assert not _verbatim_copy_ok({"copied_verbatim_from": str(plan_path)}, plan, plan_path, "harbour_grain")


def test_syntax_segments_verified_once_then_cached(monkeypatch):
    from urban_design import fabric_syntax_segments
    original = fabric_syntax_segments.load_verified
    calls = []
    def counting(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(fabric_syntax_segments, 'load_verified', counting)
    app = FastAPI()
    app.include_router(create_fabric_plans_router())  # default plan + syntax source pair
    api = TestClient(app)
    first = api.get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian')
    if first.status_code != 200:
        pytest.skip('default syntax package unavailable in this checkout')
    second = api.get('/api/v1/fabric-plans/harbour_grain/syntax/pedestrian')
    assert second.status_code == 200 and second.json() == first.json()
    assert len(calls) == 1
