"""Draft acquisition extents; no StudyArea or human-decision authority.

Network requests are confined to Founder-approved public dataset services.
Operational dispatch/publication uses GenerationJobStore/GenerationJobRunner.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import platform
import shapely
import pyproj
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlencode, urlparse
from urllib.request import Request
import xml.etree.ElementTree as ET

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import transform

from .generation.job_store import GenerationJobStore, JobStatus
from .generation.job_runner import GenerationJobRunner, PreparedOutput, write_prepared_manifest
from .models import Artifact, DatasetSnapshot
from .regional_network import evaluate_way_for_mode
from .store import EntityNotFoundError, ProjectStateStore

VERSION = 'site-extent-fetch-v2'
OVERPASS = 'https://overpass-api.de/api/interpreter'
BAG = 'https://service.pdok.nl/lv/bag/wfs/v2_0'
THREE_BAG = 'https://data.3dbag.nl/api/BAG3D/wfs'
PLANS = 'https://service.pdok.nl/kadaster/ruimtelijke-plannen/wms/v1_0'
DATA_ROOT = Path.home() / '.local/share/urban-design-data/extent-fetch'
MODES = ('pedestrian', 'bicycle', 'motor_vehicle')


def utc() -> str:
    return subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ'], text=True).strip()


def digest(data: bytes) -> str:
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def save(path: Path, data: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(data)


class PolygonInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['Polygon']
    coordinates: list[list[tuple[float, float]]]

    @model_validator(mode='after')
    def valid(self):
        if not self.coordinates or any(len(ring) < 4 or ring[0] != ring[-1] for ring in self.coordinates):
            raise ValueError('closed polygon rings with at least three vertices required')
        for ring in self.coordinates:
            for lon, lat in ring:
                if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -85 <= lat <= 85:
                    raise ValueError('finite WGS84 longitude/latitude required (latitude ±85°)')
        geom = shape(self.model_dump())
        if not geom.is_valid or geom.is_empty or geom.area <= 0 or geom.bounds[2] - geom.bounds[0] > 180:
            raise ValueError('valid positive-area polygon required; dateline crossing unsupported')
        return self


class ExtentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    geometry: PolygonInput
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


class ExtentSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assumption_status: Literal['ASSUMED_COMMANDER'] = 'ASSUMED_COMMANDER'
    max_area_m2: float = Field(default=25_000_000, gt=0)
    road_buffer_m: float = Field(default=10_000, ge=10_000)
    local_buffer_m: float = Field(default=500, ge=500)
    analysis_buffer_m: float = Field(default=1500, ge=1500)
    transit_buffer_m: float = Field(default=2000, ge=2000)
    max_source_bytes: int = Field(default=200_000_000, gt=0, le=200_000_000)
    page_size: int = Field(default=1000, ge=1, le=1000)
    max_pages: int = Field(default=100, ge=1, le=100)
    overpass_retries: int = Field(default=2, ge=0, le=2)
    retry_delay_s: float = Field(default=30, ge=30)


@dataclass(frozen=True)
class Response:
    body: bytes
    headers: dict[str, str]


class Transport(Protocol):
    def __call__(self, url: str, *, method: str = 'GET', data: bytes | None = None,
                 max_bytes: int = 200_000_000) -> Response: ...


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('public HTTPS only')
    approved = (parsed.hostname == 'overpass-api.de' and parsed.path == '/api/interpreter') or (
        parsed.hostname == 'service.pdok.nl' and any(parsed.path == path for path in
            ('/lv/bag/wfs/v2_0', '/kadaster/ruimtelijke-plannen/wms/v1_0'))
    ) or (parsed.hostname == 'data.3dbag.nl' and (
        parsed.path == '/api/BAG3D/wfs' or re.fullmatch(r'/v\d{8}/tiles/\d+/\d+/\d+/[\d-]+\.gpkg\.gz', parsed.path)))
    if not approved:
        raise ValueError('URL outside approved extent dataset allowlist')


def public_transport(url: str, *, method: str = 'GET', data: bytes | None = None,
                     max_bytes: int = 200_000_000) -> Response:
    validate_url(url)
    # Redirect destinations must also pass the allowlist before a request is sent.
    from urllib.request import HTTPRedirectHandler, build_opener
    class ApprovedRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    request = Request(url, method=method, data=data, headers={
        'User-Agent': 'Q5-UrbanDesign-ExtentFetch/1.0 (TU-Delft research prototype)',
        'Accept': 'application/json,application/xml,application/octet-stream',
        **({'Content-Type': 'application/x-www-form-urlencoded'} if data else {}),
    })
    with build_opener(ApprovedRedirect()).open(request, timeout=120) as result:
        headers = {k.lower(): v for k, v in result.headers.items()}
        if int(headers.get('content-length', '0')) > max_bytes:
            raise ValueError('DEFERRED_SIZE')
        body = result.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError('DEFERRED_SIZE')
        return Response(body, headers)


def projection(geometry: dict) -> tuple[Any, CRS, Any, bool]:
    polygon = shape(geometry)
    # RD has a Netherlands area of use; global buffers use local metric AEQD.
    nl = 3.2 <= polygon.bounds[0] and polygon.bounds[2] <= 7.3 and 50.7 <= polygon.bounds[1] and polygon.bounds[3] <= 53.7
    centre = polygon.centroid
    crs = CRS.from_epsg(28992) if nl else CRS.from_proj4(f'+proj=aeqd +lat_0={centre.y} +lon_0={centre.x} +datum=WGS84 +units=m')
    forward = Transformer.from_crs(4326, crs, always_xy=True).transform
    reverse = Transformer.from_crs(crs, 4326, always_xy=True).transform
    return transform(forward, polygon), crs, reverse, nl


def collection(features: list[dict], crs: str = 'EPSG:28992') -> dict:
    return {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': crs}}, 'features': features}


def overpass_features(doc: dict, crs: int = 28992) -> tuple[list, list, list]:
    if doc.get('remark'):
        raise ValueError('Overpass partial/error response: ' + str(doc['remark']))
    if not isinstance(doc.get('elements'), list):
        raise ValueError('missing Overpass elements')
    roads, buildings, landuse = [], [], []
    rd = Transformer.from_crs(4326, crs, always_xy=True).transform
    for item in doc['elements']:
        if item.get('type') != 'way':
            continue
        tags, geometry, nodes = item.get('tags', {}), item.get('geometry', []), item.get('nodes', [])
        if len(geometry) < 2 or len(nodes) != len(geometry):
            raise ValueError('OSM way geometry/node alignment missing')
        if any(not isinstance(node, int) or isinstance(node, bool) for node in nodes):
            raise ValueError('OSM node IDs must be integer source identities')
        for point in geometry:
            lon, lat = point.get('lon'), point.get('lat')
            if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError('OSM response coordinates are not finite WGS84')
        coords = [rd(point['lon'], point['lat']) for point in geometry]
        if any(not all(math.isfinite(value) for value in coordinate) for coordinate in coords):
            raise ValueError('OSM projection produced non-finite coordinates')
        props = {**tags, 'osm_type': 'way', 'osm_id': item['id'], 'osm_node_ids': nodes}
        if tags.get('highway') and tags.get('area') != 'yes':
            road = LineString(coords)
            if not road.is_valid or road.length <= 0:
                raise ValueError('invalid OSM road geometry')
            roads.append({'type': 'Feature', 'id': item['id'], 'properties': props,
                          'geometry': mapping(road)})
        elif ('building' in tags or 'landuse' in tags) and coords[0] == coords[-1] and len(coords) >= 4:
            geom = Polygon(coords)
            if not geom.is_valid:
                raise ValueError('invalid OSM polygon')
            feature = {'type': 'Feature', 'id': item['id'], 'properties': props, 'geometry': mapping(geom)}
            if 'building' in tags:
                buildings.append(feature)
            if 'landuse' in tags:
                landuse.append(feature)
    return roads, buildings, landuse


def overpass_activity_features(doc: dict, crs: int = 28992) -> tuple[list, list]:
    """Point representatives retain tags and route membership, never invent names."""
    rd = Transformer.from_crs(4326, crs, always_xy=True).transform
    routes: dict[tuple, list] = {}
    for item in doc['elements']:
        if item.get('type') == 'relation' and item.get('tags', {}).get('route'):
            for member in item.get('members', []):
                routes.setdefault((member['type'], member['ref']), []).append({
                    'name': item['tags'].get('name'), 'ref': item['tags'].get('ref'),
                    'mode': item['tags']['route'], 'osm_relation_id': item['id']})
    transit, pois, seen = [], [], set()
    for item in doc['elements']:
        identity = (item['type'], item['id'])
        if identity in seen:
            continue
        seen.add(identity)
        tags = item.get('tags', {})
        if tags.get('route'):
            continue
        is_transit = (tags.get('public_transport') in ('stop_position', 'platform', 'station') or
            tags.get('railway') in ('station', 'halt', 'tram_stop', 'subway_entrance') or
            tags.get('highway') == 'bus_stop' or tags.get('amenity') == 'ferry_terminal')
        is_poi = any(key in tags for key in ('amenity', 'shop', 'office', 'leisure', 'tourism'))
        if not (is_transit or is_poi):
            continue
        if item['type'] == 'node':
            lon, lat = item.get('lon'), item.get('lat')
        elif item.get('center'):
            lon, lat = item['center']['lon'], item['center']['lat']
        elif item.get('geometry'):
            coordinates = [(p['lon'], p['lat']) for p in item['geometry'] if p is not None]
            if not coordinates:
                continue
            centre = LineString(coordinates).centroid
            lon, lat = centre.x, centre.y
        elif item.get('members'):
            from shapely.ops import unary_union
            parts = [LineString([(p['lon'], p['lat']) for p in member['geometry'] if p is not None])
                for member in item['members'] if len([p for p in member.get('geometry', []) if p is not None]) >= 2]
            if not parts:
                continue
            centre = unary_union(parts).centroid
            lon, lat = centre.x, centre.y
        else:
            # Relations without geometry are metadata only, not located origins.
            continue
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError('activity point requires finite WGS84')
        modes = [mode for key, mode in [('bus', 'bus'), ('tram', 'tram'), ('train', 'rail'),
            ('subway', 'metro'), ('ferry', 'ferry')] if tags.get(key) == 'yes']
        if tags.get('railway') in ('station', 'halt'):
            modes.append('rail' if tags.get('station') != 'subway' else 'metro')
        if tags.get('railway') == 'subway_entrance':
            modes.append('metro')
        if tags.get('railway') == 'tram_stop':
            modes.append('tram')
        if tags.get('highway') == 'bus_stop':
            modes.append('bus')
        if tags.get('amenity') == 'ferry_terminal':
            modes.append('ferry')
        memberships = routes.get(identity, [])
        modes.extend({'subway': 'metro', 'train': 'rail'}.get(r['mode'], r['mode']) for r in memberships)
        properties = {**tags, 'osm_type': item['type'], 'osm_id': item['id'],
            'modes': sorted(set(modes)) or ['unknown'], 'routes': memberships,
            'location_method': 'source_node' if item['type'] == 'node' else 'geometry_representative'}
        feature = {'type': 'Feature', 'id': f'{item["type"]}/{item["id"]}', 'properties': properties,
            'geometry': {'type': 'Point', 'coordinates': rd(lon, lat)}}
        if is_transit:
            transit.append(feature)
        elif is_poi:
            pois.append(feature)
    return transit, pois


class ExtentService:
    def __init__(self, store: ProjectStateStore, *, data_root: Path = DATA_ROOT,
                 transport: Transport = public_transport, settings: ExtentSettings | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.store, self.data_root, self.transport, self.sleep = store, Path(data_root), transport, sleep
        self.settings = settings or ExtentSettings()
        operational = Path(store.database).parent / 'extent-jobs'
        self.jobs = GenerationJobStore(operational / 'jobs.sqlite3')
        self.runner = GenerationJobRunner(self.jobs, staging_root=operational / 'staging', output_root=operational / 'outputs')
        self.runner.register_handler(VERSION, VERSION, self._handler, external=True)

    def create(self, project_id: str, request: ExtentRequest) -> dict:
        project = self.store.current(project_id)
        if project.entity_type != 'Project':
            raise ValueError('project required')
        geom = request.geometry.model_dump(mode='json')
        projected, _, _, nl = projection(geom)
        area = float(projected.area)
        if area > self.settings.max_area_m2:
            raise ValueError(f'extent area {area:.1f} m² exceeds {self.settings.max_area_m2:.1f} m²')
        extent_id = 'extent-' + hashlib.sha256((project_id + ':' + request.idempotency_key).encode()).hexdigest()[:32]
        payload = {'id': extent_id, 'project_id': project_id, 'geometry_wgs84': geom,
                   'geometry_epsg28992': mapping(transform(Transformer.from_crs(4326, 28992, always_xy=True).transform, shape(geom))),
                   'rd_area_of_use': nl, 'area_m2': area, 'area_method': 'RD projected' if nl else 'local AEQD projected',
                   'purpose': 'DATA_ACQUISITION_ONLY', 'settings': self.settings.model_dump(), 'created_at': utc()}
        try:
            existing = self.store.current(extent_id)
            if existing.payload['geometry_wgs84'] != geom or existing.payload['settings'] != payload['settings']:
                raise ValueError('idempotency conflict')
            payload = dict(existing.payload)
        except EntityNotFoundError:
            self.store.create('SiteExtentDraft', payload, entity_id=extent_id, project_id=project_id, action='DrawAcquisitionExtent')
        job, created = self.jobs.enqueue(project_id=project_id, idempotency_key='extent:' + request.idempotency_key,
            stage=VERSION, request=payload, input_refs=[{'id': extent_id, 'sha256': digest(encoded(payload)), 'kind': 'site_extent_draft'}])
        return {**payload, 'job_id': job.job_id, 'created': created, 'status': self.status(job.job_id)['status']}

    def status(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if job.status == JobStatus.READY:
            if not self.runner.verify_published(job_id):
                return {'job_id': job_id, 'status': 'OUTCOME_UNKNOWN', 'reason': 'publication integrity failed'}
            result = json.loads((self.runner.output_root / job_id / 'result.json').read_bytes())
            if digest(Path(result['manifest_path']).read_bytes()) != result['manifest_sha256']:
                return {'job_id': job_id, 'status': 'OUTCOME_UNKNOWN', 'reason': 'source manifest changed'}
            try:
                from .extent_export import verified_manifest
                verified_manifest(Path(result['manifest_path']))
            except (OSError, ValueError, KeyError):
                return {'job_id': job_id, 'status': 'OUTCOME_UNKNOWN', 'reason': 'source artifacts failed integrity check'}
            if not any(event.event_id == 'extent-fetch-' + job_id for event in self.store.events(job.project_id)):
                return {'job_id': job_id, 'status': 'OUTCOME_UNKNOWN', 'reason': 'snapshot registration not reconciled'}
            return {**result, 'job_id': job_id}
        return {'job_id': job_id, 'status': job.status.value, 'error_code': job.error_code}

    def run(self, job_id: str) -> dict:
        job = self.runner.run(job_id)
        if job.status != JobStatus.READY:
            return self.status(job_id)
        if not self.runner.verify_published(job_id):
            raise ValueError('job output integrity failed')
        result = json.loads((self.runner.output_root / job_id / 'result.json').read_bytes())
        result['job_id'] = job_id
        if job.status == JobStatus.READY:
            manifest_bytes = Path(result['manifest_path']).read_bytes()
            if digest(manifest_bytes) != result['manifest_sha256']:
                raise ValueError('source manifest hash mismatch')
            from .extent_export import verified_manifest
            manifest = verified_manifest(Path(result['manifest_path']))
            entities = []
            for source in manifest['sources']:
                for item in source.get('artifacts', []):
                    data = Path(item['path']).read_bytes()
                    if digest(data) != item['sha256'] or len(data) != item['bytes']:
                        raise ValueError('source artifact integrity failed')
                    aid = 'extent-artifact-' + job_id + '-' + str(len(entities))
                    artifact = Artifact(id=aid, project_id=job.project_id, type='extent_source', uri=item['path'],
                        sha256=item['sha256'], mime=('image/png' if item['path'].endswith('.png') else 'application/xml' if item['path'].endswith('.xml') else 'application/gzip' if item['path'].endswith('.gz') else 'application/json'), size_bytes=item['bytes'],
                        producer=VERSION, created_at=item['time'])
                    snapshot = DatasetSnapshot(id=aid + '-snapshot', project_id=job.project_id, source=item['url'],
                        query=item['query'], retrieved_at=item['time'], publisher=source['name'], license=source['license'],
                        version=source.get('version', 'unversioned retrieval ' + manifest['created_at']), sha256=item['sha256'], raw_artifact_id=aid)
                    entities.extend([{'entity_id': aid, 'entity_type': 'Artifact', 'project_id': job.project_id,
                        'payload': artifact.model_dump(mode='json')},
                        {'entity_id': snapshot.id, 'entity_type': 'DatasetSnapshot', 'project_id': job.project_id,
                         'payload': {**snapshot.model_dump(mode='json'), 'extent_id': job.request['id'],
                                     'source_status': source['status'], 'feature_count': item.get('count')}}])
            event_id = 'extent-fetch-' + job_id
            if not any(event.event_id == event_id for event in self.store.events(job.project_id)):
                self.store.commit_batch(entities=[{**item, 'event_id': item['entity_id'] + '-registered', 'actor': 'extent-fetch', 'action': 'RegisterExtentSource'} for item in entities], events=[{'event_id': event_id, 'project_id': job.project_id,
                    'actor': 'extent-fetch', 'action': 'ExtentDataFetched', 'target_id': job.request['id'], 'target_type': 'SiteExtentDraft', 'resulting_refs': [x['entity_id'] for x in entities],
                    'payload': result}])
        return result

    def _handler(self, job, staging, token):
        request = job.request
        root = self.data_root / request['id'] / (utc().replace(':', '').replace('-', '') + '-' + job.job_id)
        root.mkdir(parents=True, exist_ok=False)
        projected, _, reverse, nl = projection(request['geometry_wgs84'])
        sources = []
        settings = ExtentSettings.model_validate(request['settings'])

        def source(name, license, action):
            entry = {'name': name, 'license': license, 'artifacts': [], 'requests': [], 'status': 'RUNNING'}
            started = time.perf_counter()
            try:
                action(entry)
                entry['status'] = entry.get('result_status', 'DONE')
            except Exception as exc:
                cause = getattr(exc, 'reason', exc)
                entry['status'] = ('DEFERRED_SIZE' if 'DEFERRED_SIZE' in str(exc) else 'OUTCOME_UNKNOWN' if isinstance(cause, (ConnectionResetError, TimeoutError)) else 'BLOCKED_SANDBOX_NETWORK' if isinstance(cause, PermissionError) else 'FAILED')
                entry['error'] = f'{type(exc).__name__}: {exc}'
            entry['elapsed_s'] = round(time.perf_counter() - started, 3)
            entry['bytes'] = sum(item['bytes'] for item in entry['artifacts'])
            sources.append(entry)
            token.heartbeat()

        def fetch(entry, url, query, name, *, method='GET', data=None, max_bytes=None):
            validate_url(url)
            attempt = {'url': url, 'query': query, 'method': method, 'time': utc(), 'status': 'REQUEST_STARTED'}
            entry['requests'].append(attempt)
            started = time.perf_counter()
            try:
                response = self.transport(url, method=method, data=data, max_bytes=max_bytes or settings.max_source_bytes)
                attempt.update(status='RESPONSE_RECEIVED', bytes=len(response.body), sha256=digest(response.body))
            except Exception as exc:
                attempt.update(status='REQUEST_FAILED', error=f'{type(exc).__name__}: {exc}')
                raise
            finally:
                attempt['elapsed_s'] = round(time.perf_counter() - started, 3)
            if len(response.body) > (max_bytes or settings.max_source_bytes):
                raise ValueError('DEFERRED_SIZE')
            path = root / name
            save(path, response.body)
            entry['artifacts'].append({'path': str(path), 'url': url, 'query': query, 'time': response.headers.get('x-q5-original-retrieved-at', utc()),
                'frozen_replay': response.headers.get('x-q5-frozen-parent-sha256'), 'bytes': len(response.body), 'sha256': digest(response.body), 'count': None})
            return response

        def wfs(entry, endpoint, typename, bbox, prefix, buffer_m=None):
            features, previous = [], set()
            for page in range(settings.max_pages):
                params = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': typename,
                    'outputFormat': 'application/json', 'srsName': 'EPSG:28992', 'bbox': ','.join(map(str, bbox)) + ',urn:ogc:def:crs:EPSG::28992',
                    'count': settings.page_size, 'startIndex': page * settings.page_size}
                remaining = settings.max_source_bytes - sum(item['bytes'] for item in entry['artifacts'])
                if remaining <= 0:
                    raise ValueError('DEFERRED_SIZE')
                result = fetch(entry, endpoint + '?' + urlencode(params), encoded(params).decode(), f'{prefix}-{page}.json', max_bytes=remaining)
                doc = json.loads(result.body)
                if doc.get('type') != 'FeatureCollection' or not isinstance(doc.get('features'), list):
                    raise ValueError('WFS FeatureCollection required')
                raw = doc['features']
                entry['artifacts'][-1]['count'] = len(raw)
                for feature in raw:
                    identifier = feature.get('id') or digest(encoded(feature))
                    if identifier in previous:
                        raise ValueError('WFS duplicate page/feature; refusing truncated result')
                    previous.add(identifier)
                    geometry = shape(feature['geometry'])
                    if not geometry.is_valid or geometry.is_empty:
                        raise ValueError('WFS invalid geometry')
                    if geometry.intersects(projected.buffer(buffer_m or settings.local_buffer_m)):
                        features.append(feature)
                if len(raw) < settings.page_size:
                    entry['count'] = len(features)
                    return features
                if sum(item['bytes'] for item in entry['artifacts']) > settings.max_source_bytes:
                    raise ValueError('DEFERRED_SIZE')
            raise ValueError('WFS_PAGE_LIMIT_INCOMPLETE')

        def osm(entry):
            def bbox(distance):
                x0, y0, x1, y1 = transform(reverse, projected.buffer(distance)).bounds
                return f'{y0},{x0},{y1},{x1}'
            transit_box = bbox(settings.transit_buffer_m)
            activity_box = bbox(settings.analysis_buffer_m)
            selectors = (f'nwr["public_transport"~"^(stop_position|platform|station)$"]({transit_box});'
                f'nwr["railway"~"^(station|halt|tram_stop|subway_entrance)$"]({transit_box});'
                f'node["highway"="bus_stop"]({transit_box});nwr["amenity"="ferry_terminal"]({transit_box});')
            query = (f'[out:json][timeout:110];({selectors})->.transit;'
                f'(way["highway"]({bbox(settings.road_buffer_m)});way["building"]({activity_box});'
                f'way["landuse"]({activity_box});' + ''.join(f'nwr["{key}"]({activity_box});' for key in ('amenity', 'shop', 'office', 'leisure', 'tourism')) +
                '.transit;);out body geom;(rel(bn.transit)["route"];rel(bw.transit)["route"];rel(br.transit)["route"];);out body;')
            # One combined query. Only explicit HTTP failure is retryable. A lost
            # connection after dispatch is retained as UNKNOWN, never resent.
            from urllib.error import HTTPError
            for attempt in range(settings.overpass_retries + 1):
                try:
                    response = fetch(entry, OVERPASS, query, 'osm.json', method='POST', data=urlencode({'data': query}).encode())
                    break
                except HTTPError as exc:
                    if exc.code not in (429, 502, 503, 504) or attempt == settings.overpass_retries:
                        raise
                    self.sleep(settings.retry_delay_s)
            roads, buildings, landuse = overpass_features(json.loads(response.body), 28992 if nl else 4326)
            transit, pois = overpass_activity_features(json.loads(response.body), 28992 if nl else 4326)
            # All normalized layers currently use RD; out-of-area OSM is stored
            # WGS84 and converted to local AEQD for QGIS, never accepted by RD Syntax.
            local = projected.buffer(settings.analysis_buffer_m)
            _, local_crs, _, _ = projection(request['geometry_wgs84'])
            project_geom = Transformer.from_crs(4326, local_crs, always_xy=True).transform
            scope = local
            buildings = [f for f in buildings if (shape(f['geometry']) if nl else transform(project_geom, shape(f['geometry']))).intersects(scope)]
            landuse = [f for f in landuse if (shape(f['geometry']) if nl else transform(project_geom, shape(f['geometry']))).intersects(scope)]
            transit = [f for f in transit if (shape(f['geometry']) if nl else transform(project_geom, shape(f['geometry']))).intersects(projected.buffer(settings.transit_buffer_m))]
            pois = [f for f in pois if (shape(f['geometry']) if nl else transform(project_geom, shape(f['geometry']))).intersects(scope)]
            crs = 'EPSG:28992' if nl else 'EPSG:4326'
            save(root / 'roads.geojson', encoded(collection(roads, crs)))
            save(root / 'osm-buildings.geojson', encoded(collection(buildings, crs)))
            save(root / 'landuse.geojson', encoded(collection(landuse, crs)))
            save(root / 'transit.geojson', encoded(collection(transit, crs)))
            save(root / 'pois.geojson', encoded(collection(pois, crs)))
            for mode in MODES:
                selected = []
                for feature in roads:
                    allowed, imputed, reason = evaluate_way_for_mode(feature['properties'], mode)
                    if allowed:
                        selected.append({**feature, 'properties': {**feature['properties'], 'mode': mode, 'access_imputed': imputed, 'access_reason': reason}})
                save(root / f'network-{mode}.geojson', encoded(collection(selected, crs)))
            if nl:
                from .network_unlinks import detect_grade_separated_unlinks, _vertical_signature
                extent_rd = root / 'syntax-extent.geojson'
                save(extent_rd, encoded(mapping(projected)))
                def reference(path):
                    return {'path': str(path), 'sha256': digest(path.read_bytes()).removeprefix('sha256:'), 'size_bytes': path.stat().st_size}
                for mode in MODES:
                    path = root / f'network-{mode}.geojson'
                    selected = json.loads(path.read_bytes())['features']
                    geoms = [shape(feature['geometry']) for feature in selected]
                    metadata = [{'vertical_signature': _vertical_signature(feature['properties']),
                        'source_node_coordinates': {str(node): coordinate for node, coordinate in zip(
                            feature['properties']['osm_node_ids'], feature['geometry']['coordinates'])}} for feature in selected]
                    unlinks_path = root / f'unlinks-{mode}.json'
                    save(unlinks_path, encoded(detect_grade_separated_unlinks(geoms, metadata)))
                    save(root / f'extraction-manifest_{mode}_{int(settings.road_buffer_m)}m.json', encoded({
                        'extraction': {'buffer_radius_m': settings.road_buffer_m},
                        'inputs': {'study_area': reference(extent_rd)},
                        'outputs': {'network': reference(path), 'unlinks': reference(unlinks_path)},
                        'purpose': 'DATA_ACQUISITION_ONLY', 'formal_result_eligible': False}))
            entry.update(count=len(roads) + len(buildings) + len(landuse) + len(transit) + len(pois), roads=len(roads), buildings=len(buildings), landuse=len(landuse),
                         transit=len(transit), pois=len(pois),
                         topology_limitations='Closed OSM ways only for polygons; multipolygon relations are not acquired. Syntax requires grade/topology validation.')
            entry['artifacts'][-1]['count'] = len(json.loads(response.body)['elements'])

        source('OSM', 'ODbL 1.0; © OpenStreetMap contributors', osm)
        local_bbox = projected.buffer(settings.local_buffer_m).bounds
        def bag(entry):
            if not nl:
                entry['result_status'] = 'NOT_APPLICABLE_OUTSIDE_NL'
                return
            features = wfs(entry, BAG, 'bag:pand', local_bbox, 'bag')
            save(root / 'buildings.geojson', encoded(collection(features)))
        source('PDOK BAG', 'CC0; Kadaster / PDOK', bag)

        def uses(entry):
            if not nl:
                entry['result_status'] = 'NOT_APPLICABLE_OUTSIDE_NL'
                return
            features = wfs(entry, BAG, 'bag:verblijfsobject', projected.buffer(settings.analysis_buffer_m).bounds,
                'bag-uses', settings.analysis_buffer_m)
            save(root / 'bag-uses.geojson', encoded(collection(features)))
        source('PDOK BAG verblijfsobject', 'CC0; Kadaster / PDOK', uses)

        def heights(entry):
            if not nl:
                entry['result_status'] = 'NOT_APPLICABLE_OUTSIDE_NL'
                return
            params = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': 'BAG3D:tiles',
                'outputFormat': 'application/json', 'srsName': 'EPSG:28992', 'bbox': ','.join(map(str, local_bbox)) + ',urn:ogc:def:crs:EPSG::28992'}
            response = fetch(entry, THREE_BAG + '?' + urlencode(params), encoded(params).decode(), '3dbag-index.json')
            tiles = json.loads(response.body)['features']
            entry['artifacts'][-1]['count'] = len(tiles)
            from .three_d_bag import TileSource, extract_3dbag_height_table
            downloads, total = [], 0
            for feature in tiles:
                props = feature['properties']
                urls = [value for value in props.values() if isinstance(value, str) and value.endswith('.gpkg.gz')]
                if len(urls) != 1:
                    raise ValueError('3DBAG tile index needs one versioned GPKG URL')
                url = urls[0]
                validate_url(url)
                head_started = time.perf_counter()
                head = self.transport(url, method='HEAD', max_bytes=settings.max_source_bytes)
                entry['requests'].append({'url': url, 'method': 'HEAD', 'time': utc(), 'status': 'RESPONSE_RECEIVED', 'headers': head.headers, 'elapsed_s': round(time.perf_counter() - head_started, 3)})
                size = int(head.headers.get('content-length', '0'))
                if size <= 0 or size + total > settings.max_source_bytes:
                    entry['result_status'] = 'DEFERRED_SIZE'
                    entry['reason'] = 'Unknown tile size or cumulative compressed download exceeds 200 MB'
                    return
                total += size
                downloads.append((url, size))
            if not downloads:
                raise ValueError('3DBAG tile index empty')
            tile_sources = []
            for index, (url, _) in enumerate(downloads):
                response = fetch(entry, url, 'versioned GPKG tile', f'tile-{index}.gpkg.gz', max_bytes=settings.max_source_bytes - sum(t.path.stat().st_size for t in tile_sources))
                tile_sources.append(TileSource(str(index), root / f'tile-{index}.gpkg.gz', digest(response.body), url))
            extent_path = root / 'extent-rd.geojson'
            save(extent_path, encoded(mapping(projected)))
            table = extract_3dbag_height_table(study_area_geojson_path=extent_path,
                study_area_artifact_sha256=digest(extent_path.read_bytes()), study_area_geometry_sha256=digest(projected.wkb),
                study_area_id=request['id'], study_area_version='draft', study_area_crs='EPSG:28992', tile_sources=tile_sources,
                data_version=url.split('/')[3], buffer_distance_m=settings.local_buffer_m, output_path=root / 'heights.json')
            entry.update(count=len(table.records), version=url.split('/')[3], vertical_reference='roof and ground NAP EPSG:5709; height difference m')
        source('3D BAG', 'CC BY 4.0; © tudelft3d and 3DGI', heights)

        def plans(entry):
            if not nl:
                entry['result_status'] = 'NOT_APPLICABLE_OUTSIDE_NL'
                return
            url = PLANS + '?service=WMS&request=GetCapabilities'
            response = fetch(entry, url, 'GetCapabilities (public WMS, no key)', 'plans-capabilities.xml')
            document = ET.fromstring(response.body)
            types = [node.text for node in document.findall('.//{*}Layer/{*}Name') if node.text]
            layers = [name for name in types if 'enkelbestemming' in name.lower()]
            if not layers:
                raise ValueError('PUBLIC_PLANNING_LAYER_UNAVAILABLE; OSM landuse alternative retained')
            params = {'service': 'WMS', 'version': '1.3.0', 'request': 'GetMap', 'layers': layers[0],
                'styles': '', 'crs': 'EPSG:28992', 'bbox': ','.join(map(str, local_bbox)),
                'width': 1024, 'height': 1024, 'format': 'image/png', 'transparent': 'TRUE'}
            image = fetch(entry, PLANS + '?' + urlencode(params), encoded(params).decode(), 'planning.png')
            if not image.body.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('public planning GetMap did not return PNG')
            entry.update(representation='WMS_RASTER_ONLY', count=None, layer=layers[0],
                bbox_epsg28992=list(local_bbox), limitations='Half-yearly PDOK planning display; no vector zoning or legal compliance claim. OSM landuse remains observational alternative.')
        source('Public planning', 'PDOK service metadata; licence must be verified before formal claims', plans)
        sources.append({'name': 'ruimtelijkeplannen.nl / DSO keyed APIs', 'status': 'BLOCKED_NEEDS_KEY', 'bytes': 0,
                        'elapsed_s': 0, 'artifacts': [], 'license': 'not retrieved', 'alternative': 'OSM landuse (observational; not zoning)'})
        save(root / 'extent.geojson', encoded(collection([{'type': 'Feature', 'properties': {'purpose': 'DATA_ACQUISITION_ONLY'},
            'geometry': mapping(projected) if nl else request['geometry_wgs84']}], 'EPSG:28992' if nl else 'EPSG:4326')))
        successful = [s for s in sources[:-1] if s['status'] == 'DONE']
        status = 'DONE' if all(s['status'] in ('DONE', 'NOT_APPLICABLE_OUTSIDE_NL') for s in sources[:-1]) else ('PARTIAL' if successful else 'FAILED')
        files = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes())} for path in sorted(root.iterdir()) if path.is_file()]
        manifest = {'schema_version': VERSION, 'created_at': utc(), 'extent_id': request['id'], 'project_id': job.project_id,
            'status': status, 'settings': request['settings'], 'sources': sources, 'files': files,
            'runtime': {'python': platform.python_version(), 'shapely': shapely.__version__, 'pyproj': pyproj.__version__, 'handler_version': VERSION,
                'handler_source_sha256': digest(Path(__file__).read_bytes())},
            'road_buffer_m': settings.road_buffer_m, 'formal_result_eligible': False,
            'syntax_limitations': '10 km acquisition envelope alone does not verify completeness or boundary stability.'}
        save(root / 'manifest.json', encoded(manifest))
        result = {'extent_id': request['id'], 'status': status, 'manifest_path': str(root / 'manifest.json'),
                  'manifest_sha256': digest((root / 'manifest.json').read_bytes()), 'sources': sources,
                  'failed_sources': [s['name'] for s in sources if s['status'] not in ('DONE', 'NOT_APPLICABLE_OUTSIDE_NL')]}
        save(staging / 'result.json', encoded(result))
        data = (staging / 'result.json').read_bytes()
        return write_prepared_manifest(staging, handler_version=VERSION, input_refs=job.input_refs,
            output_refs=[PreparedOutput('extent-result-' + job.job_id, 'result.json', digest(data), len(data))])


def create_extent_router(store: ProjectStateStore, service: ExtentService | None = None) -> APIRouter:
    # Lazy initialization keeps unrelated API reads free of new operational DBs.
    router = APIRouter(prefix='/api/v1/projects/{project_id}/site-extents')
    services = [service]
    def current():
        if services[0] is None:
            services[0] = ExtentService(store)
        return services[0]
    def project(project_id):
        try:
            if store.current(project_id).entity_type != 'Project':
                raise EntityNotFoundError(project_id)
        except EntityNotFoundError as exc:
            raise HTTPException(404, 'project not found') from exc
    @router.post('', status_code=202)
    def post_extent(project_id: str, body: ExtentRequest, background: BackgroundTasks):
        project(project_id)
        try:
            result = current().create(project_id, body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if result['created']:
            background.add_task(current().run, result['job_id'])
        return result
    @router.get('')
    def list_extents(project_id: str):
        project(project_id)
        return {'extents': [row.payload for row in store.list_current('SiteExtentDraft', project_id)]}
    @router.get('/jobs/{job_id}')
    def get_job(project_id: str, job_id: str):
        project(project_id)
        try:
            if current().jobs.get(job_id).project_id != project_id:
                raise KeyError(job_id)
            return current().status(job_id)
        except KeyError as exc:
            raise HTTPException(404, 'job not found') from exc
    return router
