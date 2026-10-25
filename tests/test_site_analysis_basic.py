import json
from pathlib import Path
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point, LineString, box, mapping

from urban_design.site_intelligence.basic_analysis import (
    BasicParameters, WalkingGraph, SyntaxOverlay, calculate_basic, landuse_summary,
    create_basic_analysis_router,
)
from urban_design.site_extents import overpass_activity_features, encoded, digest, utc
from urban_design.store import ProjectStateStore


def road(coords, nodes, identifier=1, **tags):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(LineString(coords)),
        'properties': {'osm_type': 'way', 'osm_id': identifier, 'osm_node_ids': nodes, 'highway': 'footway', **tags}}


def point(x, y, identifier='p', **props):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(Point(x, y)), 'properties': props}


def test_routes_follow_walk_network_not_euclidean_and_same_edge_shortcut():
    graph = WalkingGraph([road([(0, 0), (0, 100), (10, 100), (10, 0)], [1, 2, 3, 4])])
    origin, target = graph.snap(Point(0, 0), 1), graph.snap(Point(10, 0), 1)
    distance, coords = graph.route(origin, target, graph.search(target, 1000), 1000)
    assert distance == 210
    assert LineString(coords).length == 210
    assert Point(0, 0).distance(Point(10, 0)) == 10
    target2 = graph.snap(Point(0, 10), 1)
    assert graph.route(origin, target2, graph.search(target2, 1000), 1000)[0] == 10
    assert graph.snap(Point(50, 50), 5) is None


def test_crossing_lines_without_shared_source_nodes_stay_disconnected():
    graph = WalkingGraph([road([(0, 0), (100, 0)], [1, 2]), road([(50, -50), (50, 50)], [3, 4], 2)])
    origin, target = graph.snap(Point(0, 0), 1), graph.snap(Point(50, 50), 1)
    assert graph.route(origin, target, graph.search(target, 1000), 1000) is None


def test_pedestrian_oneway_and_access_restrictions_are_preserved():
    graph = WalkingGraph([road([(0, 0), (100, 0)], [1, 2], **{'oneway:foot': 'yes'}),
        road([(100, 0), (100, 100)], [2, 3], 2, access='private')])
    assert len(graph.edges) == 1
    a, b = graph.snap(Point(10, 0), 1), graph.snap(Point(90, 0), 1)
    assert graph.route(a, b, graph.search(b, 1000), 1000)[0] == 80
    assert graph.route(b, a, graph.search(a, 1000), 1000) is None


def test_sector_floor_area_not_count_and_equal_split_multiuse_missing_area():
    site = box(-10, -10, 10, 10)
    bag = [point(0, 30, '1', gebruiksdoel='woonfunctie', oppervlakte=620),
        point(0, 40, '2', gebruiksdoel='industriefunctie', oppervlakte=380),
        point(30, 0, '3', gebruiksdoel=['kantoorfunctie', 'winkelfunctie'], oppervlakte=200),
        point(0, -30, '4', gebruiksdoel='woonfunctie'), point(0, 600, '5', gebruiksdoel='woonfunctie', oppervlakte=999999)]
    land = [{'geometry': mapping(box(-30, 20, 30, 100)), 'properties': {'landuse': 'residential'}}]
    summary, sectors = landuse_summary(site, bag, land, BasicParameters())
    values = {item['side']: item for item in summary}
    assert values['N']['bag_usage_percent'] == {'industriefunctie': 38, 'woonfunctie': 62}
    assert values['N']['bag_floor_area_m2'] == 1000 and values['N']['bag_object_count'] == 2
    assert values['E']['bag_usage_percent'] == {'kantoorfunctie': 50, 'winkelfunctie': 50}
    assert values['S']['missing_area_count'] == 1 and values['S']['bag_usage_percent'] == {}
    ring = site.buffer(500).difference(site)
    assert sum(shape['geometry']['type'] in ('Polygon', 'MultiPolygon') for shape in sectors) == 4
    assert sum(item['sector_area_m2'] for item in summary) == pytest.approx(ring.area, abs=.03)
    assert values['N']['osm_landuse_area_m2']['residential'] > 0


def calculate(params=None, syntax_segments=None):
    return calculate_basic(box(89000, 435000, 89010, 435010),
        [road([(88950, 435005), (89005, 435005), (89060, 435005)], [1, 2, 3])],
        [point(88960, 435005, 'bus', name='West station', modes=['bus'], routes=[{'name': 'Line 1'}])],
        [point(89050, 435005, 'shop', shop='supermarket', name='Shop')],
        [point(88970, 435005, 'bag', gebruiksdoel='woonfunctie', oppervlakte=100)], [],
        project_id='p', extent_id='e', study_area_id='s', study_area_version='v1', source_hashes={'fixture': 'sha256:test'},
        params=params, syntax_segments=syntax_segments)


def test_entrance_ranking_weights_nearest_mode_source_hash_and_estimation_label():
    result = calculate(BasicParameters(poi_weights={'shop': 0}, bag_weights={'woonfunctie': 0}))
    assert result.closest_transit_side == 'W'
    west = next(item for item in result.transit if item.side == 'W')
    assert west.nearest_by_mode['bus'].distance_m == 40
    assert west.nearest_by_mode['bus'].name == 'West station'
    assert result.entrances[0].side == 'W'
    assert result.interpretation == 'ESTIMATED_ARRIVAL_POTENTIAL_NOT_OBSERVED_FLOW'
    assert result.parameters.status == 'ASSUMED_COMMANDER' and not result.formal_result_eligible
    weighted = calculate(BasicParameters(transit_weights={'bus': 0}, bag_weights={'woonfunctie': 0}, poi_weights={'shop': 10}))
    assert weighted.entrances[0].side == 'E'
    assert weighted.source_hashes['parameters'] != result.source_hashes['parameters']
    assert result.syntax['status'] == 'UNAVAILABLE'
    assert all(entry.syntax_adjusted_potential is None for entry in result.entrances)
    assert {feature['properties']['kind'] for feature in result.overlay_wgs84['features']} >= {'station', 'entrance', 'arrival_route', 'nearest_route', 'sector'}


@pytest.mark.parametrize('value', [-1, float('inf'), float('nan')])
def test_invalid_weights_rejected(value):
    with pytest.raises(ValueError):
        BasicParameters(transit_weights={'bus': value})


def test_syntax_overlay_only_matches_coincident_routes_and_retains_missing():
    overlay = SyntaxOverlay([{'coordinates': [[0, 0], [100, 0]], 'nain': 2., 'nach': 3.}], BasicParameters())
    value = overlay.summary([[0, 0], [100, 0]])
    assert value['coverage_ratio'] == 1 and value['nain_mean'] == 2 and value['multiplier'] == 1.25
    cross = overlay.summary([[50, -50], [50, 50]])
    assert cross['status'] == 'UNAVAILABLE' and cross['multiplier'] is None


def test_osm_transit_modes_route_names_and_poi_representatives():
    document = {'elements': [
        {'type': 'node', 'id': 10, 'lon': 4.42, 'lat': 51.91, 'tags': {'public_transport': 'platform', 'bus': 'yes', 'name': 'Stop'}},
        {'type': 'relation', 'id': 20, 'tags': {'route': 'bus', 'name': 'Line to centre', 'ref': '42'}, 'members': [{'type': 'node', 'ref': 10}]},
        {'type': 'node', 'id': 30, 'lon': 4.43, 'lat': 51.91, 'tags': {'shop': 'supermarket'}},
        {'type': 'node', 'id': 40, 'lon': 4.43, 'lat': 51.91, 'tags': {'amenity': 'ferry_terminal'}}]}
    transit, pois = overpass_activity_features(document)
    assert len(transit) == 2 and len(pois) == 1
    assert transit[0]['properties']['routes'][0]['name'] == 'Line to centre'
    assert transit[1]['properties']['modes'] == ['ferry']


def test_api_read_only_missing_sources_project_isolation_and_verified_result(tmp_path, monkeypatch):
    from shapely.geometry import shape
    from pyproj import Transformer
    from shapely.ops import transform
    store = ProjectStateStore(tmp_path / 'test.sqlite3')
    store.create_project('p', {'name': 'Fixture', 'active_study_area_id': 's'})
    store.create('StudyArea', {'id': 's', 'project_id': 'p', 'version': 'v1', 'crs': 'EPSG:28992', 'geometry_artifact_id': 'a'}, entity_id='s', project_id='p')
    site = box(89000, 435000, 89010, 435010)
    study_path = tmp_path / 'study.geojson'; study_path.write_bytes(encoded(mapping(site)))
    store.create('Artifact', {'id': 'a', 'uri': str(study_path), 'sha256': digest(study_path.read_bytes())}, entity_id='a', project_id='p')
    store.create('SiteExtentDraft', {'id': 'e', 'project_id': 'p', 'geometry_epsg28992': mapping(site.buffer(50).envelope)}, entity_id='e', project_id='p')
    app = FastAPI(); app.include_router(create_basic_analysis_router(store))
    before = len(store.events())
    with TestClient(app) as client:
        url = '/api/v1/projects/p/site-analysis/basic?extent_id=e'
        assert client.get(url).status_code == 409
        assert client.get('/api/v1/projects/missing/site-analysis/basic?extent_id=e').status_code == 404
        assert len(store.events()) == before
        root = tmp_path / 'sources'; root.mkdir()
        docs = {'network-pedestrian.geojson': [road([(88950, 435005), (89060, 435005)], [1, 2])],
            'transit.geojson': [point(88960, 435005, name='Stop', modes=['bus'])], 'pois.geojson': [],
            'bag-uses.geojson': [point(88970, 435005, gebruiksdoel='woonfunctie', oppervlakte=100)], 'landuse.geojson': []}
        files = []
        for name, features in docs.items():
            path = root / name
            path.write_bytes(encoded({'type': 'FeatureCollection', 'crs': {'properties': {'name': 'EPSG:28992'}}, 'features': features}))
            files.append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes())})
        manifest = root / 'manifest.json'; manifest.write_bytes(encoded({'project_id': 'p', 'extent_id': 'e', 'files': files}))
        store.append_event(project_id='p', actor='fixture', action='ExtentDataFetched', target_id='e', target_type='SiteExtentDraft',
            payload={'manifest_path': str(manifest), 'manifest_sha256': digest(manifest.read_bytes())})
        before = len(store.events())
        created = client.post('/api/v1/projects/p/site-analysis/basic/jobs', json={'extent_id': 'e'})
        assert created.status_code == 202, created.text
        job_id = created.json()['job_id']
        deadline = time.monotonic() + 5
        while True:
            job_response = client.get(f'/api/v1/projects/p/site-analysis/basic/jobs/{job_id}')
            assert job_response.status_code == 200, job_response.text
            job = job_response.json()
            if job['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                break
            assert time.monotonic() < deadline, 'basic analysis job did not finish within five seconds'
            time.sleep(.01)
        assert job['status'] == 'SUCCEEDED', job
        assert job['cache_hit'] is False
        assert job['result']['closest_transit_side'] == 'W'
        result_created_at = job['result']['created_at']
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert response.json()['created_at'] == result_created_at
        cached = client.post('/api/v1/projects/p/site-analysis/basic/jobs', json={'extent_id': 'e'})
        assert cached.status_code == 200, cached.text
        cached_job = cached.json()
        assert cached_job['status'] == 'SUCCEEDED'
        assert cached_job['cache_hit'] is True
        assert cached_job['last_analysis_at'] == result_created_at
        assert cached_job['result']['created_at'] == result_created_at
        assert client.delete(f'/api/v1/projects/p/site-analysis/basic/jobs/{cached_job["job_id"]}').json()['status'] == 'SUCCEEDED'
        assert len(store.events()) == before

        store.create('SiteExtentDraft', {'id': 'e2', 'project_id': 'p', 'geometry_epsg28992': mapping(site.buffer(50).envelope)}, entity_id='e2', project_id='p')
        second_manifest = root / 'manifest-e2.json'
        second_manifest.write_bytes(encoded({'project_id': 'p', 'extent_id': 'e2', 'files': files}))
        store.append_event(project_id='p', actor='fixture', action='ExtentDataFetched', target_id='e2', target_type='SiteExtentDraft',
            payload={'manifest_path': str(second_manifest), 'manifest_sha256': digest(second_manifest.read_bytes())})
        import urban_design.site_intelligence.basic_analysis as basic_analysis_module
        real_check_cancel = basic_analysis_module._check_cancel
        entered_analysis = threading.Event()
        def hold_at_analysis_checkpoint(cancel_event):
            if cancel_event is not None and threading.current_thread().name.startswith('basic-analysis-'):
                entered_analysis.set()
                while not cancel_event.wait(.01):
                    pass
            real_check_cancel(cancel_event)
        monkeypatch.setattr(basic_analysis_module, '_check_cancel', hold_at_analysis_checkpoint)
        cancellable = client.post('/api/v1/projects/p/site-analysis/basic/jobs', json={'extent_id': 'e2'})
        assert cancellable.status_code == 202, cancellable.text
        cancel_job_id = cancellable.json()['job_id']
        assert entered_analysis.wait(2), 'analysis worker did not reach a cancellation checkpoint'
        cancel_response = client.delete(f'/api/v1/projects/p/site-analysis/basic/jobs/{cancel_job_id}')
        assert cancel_response.status_code == 200, cancel_response.text
        assert cancel_response.json()['status'] in ('CANCELLING', 'CANCELLED')
        deadline = time.monotonic() + 5
        while True:
            canceled = client.get(f'/api/v1/projects/p/site-analysis/basic/jobs/{cancel_job_id}')
            assert canceled.status_code == 200, canceled.text
            if canceled.json()['status'] in ('CANCELLED', 'FAILED', 'SUCCEEDED'):
                break
            assert time.monotonic() < deadline, 'cancelled analysis job did not stop within five seconds'
            time.sleep(.01)
        assert canceled.json()['status'] == 'CANCELLED'

        (root / 'transit.geojson').write_bytes(b'corrupt')
        assert client.get(url).status_code == 409  # Also reject corruption after cache fill.
        assert client.post('/api/v1/projects/p/site-analysis/basic/jobs', json={'extent_id': 'e'}).status_code == 409
        store.create_project('other', {'name': 'Other'})
        assert client.get('/api/v1/projects/other/site-analysis/basic?extent_id=e').status_code == 404
    store.close()


def test_nonpolygon_tourism_ring_does_not_weaken_building_validation():
    from urban_design.site_extents import overpass_features
    from copy import deepcopy
    raw = {'elements': [{'type': 'way', 'id': 100, 'nodes': [1, 2, 3, 4, 1],
        'tags': {'tourism': 'attraction'}, 'geometry': [{'lon': 4.4, 'lat': 51.9}, {'lon': 4.41, 'lat': 51.91},
        {'lon': 4.4, 'lat': 51.91}, {'lon': 4.41, 'lat': 51.9}, {'lon': 4.4, 'lat': 51.9}]}]}
    assert overpass_features(raw) == ([], [], [])
    changed = deepcopy(raw); changed['elements'][0]['tags']['building'] = 'yes'
    with pytest.raises(ValueError, match='invalid OSM polygon'):
        overpass_features(changed)
    changed['elements'][0]['tags'] = {'landuse': 'industrial'}
    with pytest.raises(ValueError, match='invalid OSM polygon'):
        overpass_features(changed)


def test_relation_poi_location_retains_source_geometry_representative():
    raw = {'elements': [{'type': 'relation', 'id': 11, 'tags': {'leisure': 'park'}, 'members': [
        {'type': 'way', 'ref': 1, 'geometry': [{'lon': 4.4, 'lat': 51.9}, {'lon': 4.41, 'lat': 51.91}]}]}]}
    transit, pois = overpass_activity_features(raw)
    assert transit == [] and len(pois) == 1
    assert pois[0]['properties']['location_method'] == 'geometry_representative'
