import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import LineString, shape

from urban_design.extent_export import export_geopackage
from urban_design.site_extents import (
    BAG, OVERPASS, THREE_BAG, PLANS, ExtentRequest, ExtentService, ExtentSettings,
    PolygonInput, Response, create_extent_router, digest, encoded, projection, validate_url,
)
from urban_design.store import ProjectStateStore

GEOMETRY = {'type': 'Polygon', 'coordinates': [[[4.42, 51.91], [4.425, 51.91], [4.425, 51.915], [4.42, 51.915], [4.42, 51.91]]]}


def fake_transport(url, *, method='GET', data=None, max_bytes=200_000_000):
    if url == OVERPASS:
        doc = {'elements': [
            {'type': 'way', 'id': 1, 'nodes': [10, 11], 'tags': {'highway': 'residential'},
             'geometry': [{'lon': 4.421, 'lat': 51.911}, {'lon': 4.424, 'lat': 51.914}]},
            {'type': 'way', 'id': 2, 'nodes': [12, 13, 14, 12], 'tags': {'building': 'yes', 'landuse': 'residential'},
             'geometry': [{'lon': 4.421, 'lat': 51.911}, {'lon': 4.422, 'lat': 51.911}, {'lon': 4.422, 'lat': 51.912}, {'lon': 4.421, 'lat': 51.911}]}]}
        return Response(encoded(doc), {})
    if 'gpkg.gz' in url:
        assert method == 'HEAD'  # Oversize tile must never be downloaded.
        return Response(b'', {'content-length': '200000001'})
    if url.startswith(THREE_BAG):
        return Response(encoded({'features': [{'properties': {'gpkg_download': 'https://data.3dbag.nl/v20250903/tiles/9/304/512/9-304-512.gpkg.gz'}}]}), {})
    if url.startswith(PLANS) and 'GetCapabilities' in url:
        return Response(b'<WMS_Capabilities><Capability><Layer><Layer><Name>Enkelbestemming</Name></Layer></Layer></Capability></WMS_Capabilities>', {})
    if url.startswith(PLANS) and 'GetMap' in url:
        return Response(b'\x89PNG\r\n\x1a\n' + b'fake-raster', {})
    params = parse_qs(urlparse(url).query)
    if url.startswith(BAG) or url.startswith(PLANS):
        geom = projection(GEOMETRY)[0]
        is_use = params.get('typeNames') == ['bag:verblijfsobject']
        return Response(encoded({'type': 'FeatureCollection', 'features': [] if params['startIndex'] != ['0'] else [
            {'type': 'Feature', 'id': 'verblijfsobject.1' if is_use else 'pand.1',
             'properties': {'identificatie': '1234567890123456', **({'gebruiksdoel': 'woonfunctie', 'oppervlakte': 100} if is_use else {})},
             'geometry': json.loads(encoded((geom.centroid if is_use else geom).__geo_interface__))}]}), {})
    raise AssertionError(url)


@pytest.fixture
def service(tmp_path):
    store = ProjectStateStore(tmp_path / 'copy.sqlite3')
    store.create_project('project', {'name': 'fixture'})
    service = ExtentService(store, data_root=tmp_path / 'data', transport=fake_transport, settings=ExtentSettings(page_size=1))
    yield service
    store.close()


def request(key='draw1', geometry=GEOMETRY):
    return ExtentRequest(geometry=geometry, idempotency_key=key)


def test_append_only_extent_idempotency_area_and_no_authority(service):
    first = service.create('project', request())
    second = service.create('project', request())
    assert first['job_id'] == second['job_id'] and not second['created']
    assert first['purpose'] == 'DATA_ACQUISITION_ONLY'
    assert 180000 < first['area_m2'] < 210000
    assert first['rd_area_of_use'] is True
    assert len(service.store.list_current('SiteExtentDraft')) == 1
    assert service.store.list_current('StudyArea') == []
    assert service.store.list_current('HumanDecision') == []
    different = json.loads(encoded(GEOMETRY)); different['coordinates'][0][1][0] += .001
    with pytest.raises(ValueError, match='idempotency conflict'):
        service.create('project', request(geometry=different))


@pytest.mark.parametrize('coordinates', [
    [[[4, 52], [5, 52], [5, 53]]],
    [[[4, 52], [5, 53], [4, 53], [5, 52], [4, 52]]],
    [[[4, 52], [float('nan'), 52], [4, 53], [4, 52]]],
])
def test_reject_invalid_geometry(coordinates):
    with pytest.raises(ValueError):
        PolygonInput(type='Polygon', coordinates=coordinates)


def test_area_limit_and_project_binding(service):
    with pytest.raises(ValueError, match='exceeds'):
        service.create('project', request(geometry={'type': 'Polygon', 'coordinates': [[[4, 51], [5, 51], [5, 52], [4, 51]]]}))
    assert not service.store.list_current('SiteExtentDraft')


def test_fetch_manifest_pagination_snapshots_modes_and_export(service, tmp_path):
    job = service.create('project', request())
    result = service.run(job['job_id'])
    assert result['status'] == 'PARTIAL'
    statuses = {source['name']: source['status'] for source in result['sources']}
    assert statuses == {'OSM': 'DONE', 'PDOK BAG': 'DONE', 'PDOK BAG verblijfsobject': 'DONE', '3D BAG': 'DEFERRED_SIZE', 'Public planning': 'DONE', 'ruimtelijkeplannen.nl / DSO keyed APIs': 'BLOCKED_NEEDS_KEY'}
    path = Path(result['manifest_path'])
    manifest = json.loads(path.read_bytes())
    assert manifest['road_buffer_m'] == 10000
    assert manifest['settings']['analysis_buffer_m'] == 1500
    assert manifest['settings']['transit_buffer_m'] == 2000
    assert manifest['runtime']['handler_source_sha256'] == digest(Path('src/urban_design/site_extents.py').read_bytes())
    assert manifest['formal_result_eligible'] is False
    for source in manifest['sources']:
        for artifact in source['artifacts']:
            assert digest(Path(artifact['path']).read_bytes()) == artifact['sha256']
            assert artifact['query'] and artifact['time']
    assert len(service.store.list_current('DatasetSnapshot')) == 8
    assert not service.store.list_current('HumanDecision')
    events = len(service.store.events())
    service.run(job['job_id'])
    assert len(service.store.events()) == events
    network = json.loads((path.parent / 'network-pedestrian.geojson').read_bytes())
    assert network['crs']['properties']['name'] == 'EPSG:28992'
    assert network['features'][0]['properties']['osm_node_ids'] == [10, 11]
    assert (path.parent / 'extraction-manifest_pedestrian_10000m.json').exists()
    receipt = export_geopackage(path, tmp_path / 'extent.gpkg')
    assert receipt['layers']['buildings'] == receipt['layers']['roads_pedestrian'] == 1
    assert receipt['layers']['bag_uses'] == 1
    assert {'transit', 'pois'} <= receipt['layers'].keys()
    with sqlite3.connect(receipt['path']) as connection:
        assert connection.execute('PRAGMA application_id').fetchone()[0] == 1196444487
        blob = connection.execute('SELECT geom FROM roads_pedestrian').fetchone()[0]
        assert blob[:2] == b'GP'
        from shapely import from_wkb
        assert from_wkb(blob[8:]).equals(shape(network['features'][0]['geometry']))
    with pytest.raises(FileExistsError):
        export_geopackage(path, tmp_path / 'extent.gpkg')
    (path.parent / 'roads.geojson').write_bytes(b'changed')
    assert service.status(job['job_id'])['status'] == 'OUTCOME_UNKNOWN'
    with pytest.raises(ValueError, match='hash/size'):
        export_geopackage(path, tmp_path / 'tampered.gpkg')


def test_http_retry_bounded_and_single_combined_query(service):
    calls, sleeps = [], []
    def transport(url, **kwargs):
        if url == OVERPASS:
            calls.append(kwargs)
            if len(calls) <= 2:
                raise HTTPError(url, 429, 'rate limited', {}, None)
        return fake_transport(url, **kwargs)
    service.transport, service.sleep = transport, sleeps.append
    result = service.run(service.create('project', request())['job_id'])
    assert result['sources'][0]['status'] == 'DONE'
    assert len(calls) == 3 and sleeps == [30, 30]
    assert all(b'highway' in call['data'] and b'building' in call['data'] and b'landuse' in call['data'] for call in calls)
    assert all(b'public_transport' in call['data'] and b'ferry_terminal' in call['data'] and b'amenity' in call['data'] and b'rel%28bn.transit%29' in call['data'] for call in calls)


def test_post_dispatch_connection_loss_no_resend(service):
    calls = []
    def transport(url, **kwargs):
        calls.append(url)
        if url == OVERPASS:
            raise ConnectionResetError('connection lost after dispatch')
        return fake_transport(url, **kwargs)
    service.transport = transport
    result = service.run(service.create('project', request())['job_id'])
    assert calls.count(OVERPASS) == 1
    assert result['status'] == 'PARTIAL'
    assert result['sources'][0]['status'] == 'OUTCOME_UNKNOWN'


def test_all_network_failures_have_no_fake_pass(service):
    def transport(url, **kwargs):
        raise PermissionError('sandbox denied network')
    service.transport = transport
    result = service.run(service.create('project', request())['job_id'])
    assert result['status'] == 'FAILED'
    assert len(result['failed_sources']) == 6
    assert not service.store.list_current('DatasetSnapshot')


def test_api_background_job_and_project_isolation(service):
    app = FastAPI(); app.include_router(create_extent_router(service.store, service))
    with TestClient(app) as client:
        prefix = '/api/v1/projects/project/site-extents'
        response = client.post(prefix, json=request().model_dump(mode='json'))
        assert response.status_code == 202
        assert response.json()['status'] == 'PENDING'
        assert len(client.get(prefix).json()['extents']) == 1
        status = client.get(prefix + '/jobs/' + response.json()['job_id'])
        assert status.json()['status'] == 'PARTIAL'
        assert client.get('/api/v1/projects/missing/site-extents').status_code == 404
        assert client.post(prefix, json={'geometry': GEOMETRY, 'idempotency_key': 'bad', 'approve': True}).status_code == 422


def test_allowlist_rejects_keys_and_redirect_targets():
    for url in ['https://api.ruimtelijkeplannen.nl/v1', 'https://evil.example/x', 'http://overpass-api.de/api/interpreter', 'https://user:secret@data.3dbag.nl/api/BAG3D/wfs']:
        with pytest.raises(ValueError):
            validate_url(url)


def test_global_extent_marks_rd_not_applicable(service):
    geometry = {'type': 'Polygon', 'coordinates': [[[-74.01, 40.71], [-74, 40.71], [-74, 40.715], [-74.01, 40.71]]]}
    result = service.create('project', request(geometry=geometry))
    assert not result['rd_area_of_use'] and result['area_method'] == 'local AEQD projected'


def test_height_download_extraction_and_done_status(service, tmp_path):
    from test_3dbag_height_table import _write_fixture_tile
    from shapely.geometry import box
    from urban_design.three_d_bag import load_3dbag_height_table
    geom = projection(GEOMETRY)[0]
    point = geom.centroid
    tile = tmp_path / 'test-tile.gz'
    _write_fixture_tile(tile, buildings=[('1234567890123456', 2., box(point.x, point.y, point.x + 10, point.y + 10))], roof_parts=[('1234567890123456', 1, 14.)])
    def transport(url, **kwargs):
        if 'gpkg.gz' in url:
            return Response(b'' if kwargs['method'] == 'HEAD' else tile.read_bytes(), {'content-length': str(tile.stat().st_size)})
        return fake_transport(url, **kwargs)
    service.transport = transport
    result = service.run(service.create('project', request())['job_id'])
    assert result['status'] == 'DONE'
    table = load_3dbag_height_table(Path(result['manifest_path']).parent / 'heights.json')
    assert table.records['NL.IMBAG.Pand.1234567890123456'].height_above_ground_m == 12.
    assert result['sources'][2]['count'] == 1
    receipt = export_geopackage(Path(result['manifest_path']), tmp_path / 'with-height.gpkg')
    with sqlite3.connect(receipt['path']) as connection:
        props = json.loads(connection.execute('SELECT properties FROM buildings').fetchone()[0])
        assert props['height_above_ground_m'] == 12.


def test_exhausted_retries_partial_paging_and_overpass_remark(service):
    calls, sleeps = [], []
    def transport(url, **kwargs):
        if url == OVERPASS:
            calls.append(url)
            raise HTTPError(url, 503, 'unavailable', {}, None)
        return fake_transport(url, **kwargs)
    service.transport, service.sleep = transport, sleeps.append
    result = service.run(service.create('project', request())['job_id'])
    assert result['sources'][0]['status'] == 'FAILED'
    assert len(calls) == 3 and sleeps == [30, 30]
    assert len(result['sources'][0]['requests']) == 3


def test_paging_duplicates_fail_closed(service):
    def transport(url, **kwargs):
        if url.startswith(BAG):
            url = url.replace('startIndex=1', 'startIndex=0')
        return fake_transport(url, **kwargs)
    service.transport = transport
    result = service.run(service.create('project', request())['job_id'])
    assert result['sources'][1]['status'] == 'FAILED'
    assert 'duplicate' in result['sources'][1]['error']
    assert not (Path(result['manifest_path']).parent / 'buildings.geojson').exists()


def test_compute_context_uses_new_extent_manifest_without_changing_default(service):
    from scripts.compute_syntax_context import compute_mode, EXTRACTION_DIR
    import inspect
    result = service.run(service.create('project', request())['job_id'])
    class Adapter:
        def compute(self, request):
            assert request.radius_m == 800 and request.lines
            class Result:
                segments = ()
                node_counts = ()
                total_depths = ()
                choices = ()
            return Result()
    # The PST runtime manifest is an existing pinned input, never downloaded.
    output = compute_mode('pedestrian', 10000, 800, 10000, Adapter(), Path(result['manifest_path']).parent)
    assert output['max_context_m'] == 10000
    assert output['extract_buffer_m'] == 10000
    assert inspect.signature(compute_mode).parameters['extraction_dir'].default == EXTRACTION_DIR


def test_untrusted_osm_response_geometry_and_node_ids():
    from urban_design.site_extents import overpass_features
    base = {'elements': [{'type': 'way', 'id': 1, 'nodes': [1, 2], 'tags': {'highway': 'residential'},
        'geometry': [{'lon': 4.42, 'lat': 51.91}, {'lon': 4.43, 'lat': 51.92}]}]}
    broken = json.loads(encoded(base)); broken['elements'][0]['geometry'][0]['lon'] = 181
    with pytest.raises(ValueError, match='WGS84'):
        overpass_features(broken)
    broken = json.loads(encoded(base)); broken['elements'][0]['nodes'][0] = True
    with pytest.raises(ValueError, match='node IDs'):
        overpass_features(broken)
    broken = json.loads(encoded(base)); broken['remark'] = 'runtime error: timeout'
    with pytest.raises(ValueError, match='partial/error'):
        overpass_features(broken)
