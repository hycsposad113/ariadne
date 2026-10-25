"""Exploratory, source-bound site diagnosis. No decision or observation of flow.

Uses source-node pedestrian topology (no geometric crossing auto-links),
BAG floor area and OSM observed landuse. Parameters are commander assumptions.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
import heapq
import math
from pathlib import Path
import threading
import time
from typing import Any, Literal
import json
import uuid

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import unary_union, transform
from shapely.strtree import STRtree
from pyproj import Transformer

from ..extent_export import verified_manifest
from ..site_extents import digest, encoded, utc
from ..regional_network import evaluate_way_for_mode
from ..store import EntityNotFoundError, ProjectStateStore
from ..syntax_context_api import load_verified_manifest, load_verified_mode, syntax_context_readiness, sha256_file

SIDES = ('N', 'E', 'S', 'W')
VERSION = 'basic-site-analysis-v1'


class AnalysisCancelled(ValueError):
    """Raised when a user cancels an in-process basic analysis job."""


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled('basic site analysis cancelled')


class BasicParameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    version: Literal['basic-site-assumptions-v1'] = 'basic-site-assumptions-v1'
    status: Literal['ASSUMED_COMMANDER'] = 'ASSUMED_COMMANDER'
    sector_buffer_m: float = Field(default=500, gt=0, le=500)
    snap_max_m: float = Field(default=30, gt=0, le=100)
    distance_limit_m: float = Field(default=5000, gt=0, le=10000)
    decay_m: float = Field(default=800, gt=0)
    top_routes: int = Field(default=3, ge=1, le=10)
    syntax_match_m: float = Field(default=2, gt=0, le=10)
    syntax_weight: float = Field(default=.25, ge=0, le=1)
    syntax_min_coverage: float = Field(default=.8, gt=0, le=1)
    transit_weights: dict[str, float] = Field(default_factory=lambda: {'bus': 1, 'tram': 2, 'metro': 3, 'rail': 3, 'ferry': 1, 'unknown': 1})
    poi_weights: dict[str, float] = Field(default_factory=lambda: {'amenity': 1, 'shop': 1.5, 'office': 1, 'leisure': 1, 'tourism': 1})
    bag_weights: dict[str, float] = Field(default_factory=lambda: {'woonfunctie': .2, 'kantoorfunctie': 1, 'industriefunctie': .5,
        'winkelfunctie': 1.5, 'onderwijsfunctie': 1.5, 'bijeenkomstfunctie': 1, 'gezondheidszorgfunctie': 1,
        'sportfunctie': 1, 'logiesfunctie': 1, 'overige gebruiksfunctie': .2})

    def model_post_init(self, __context):
        for weights in (self.transit_weights, self.poi_weights, self.bag_weights):
            if any(not math.isfinite(value) or value < 0 for value in weights.values()):
                raise ValueError('weights must be finite and nonnegative')


class RouteResult(BaseModel):
    origin_id: str
    name: str | None
    kind: str
    modes: list[str] = Field(default_factory=list)
    routes: list[dict] = Field(default_factory=list)
    distance_m: float
    connector_m: float
    contribution: float
    coordinates: list[list[float]]
    syntax: dict


class TransitSide(BaseModel):
    side: str
    status: str
    nearest_by_mode: dict[str, RouteResult | None]


class LanduseSide(BaseModel):
    side: str
    bag_floor_area_m2: float
    bag_usage_percent: dict[str, float]
    bag_object_count: int
    missing_area_count: int
    dominant_bag_use: str | None
    osm_landuse_area_m2: dict[str, float]
    osm_ring_area_percent: dict[str, float]
    dominant_osm_landuse: str | None
    sector_area_m2: float


class EntranceResult(BaseModel):
    id: str
    side: str
    coordinates: list[float]
    status: str
    reachable_origins: int
    distance_potential: float
    syntax_adjusted_potential: float | None
    rank: int
    major_routes: list[RouteResult]


class BasicResult(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    schema_version: str = VERSION
    status: str
    interpretation: Literal['ESTIMATED_ARRIVAL_POTENTIAL_NOT_OBSERVED_FLOW'] = 'ESTIMATED_ARRIVAL_POTENTIAL_NOT_OBSERVED_FLOW'
    formal_result_eligible: Literal[False] = False
    project_id: str
    extent_id: str
    study_area_id: str
    study_area_version: str
    created_at: str
    crs: Literal['EPSG:28992'] = 'EPSG:28992'
    distance_unit: Literal['m'] = 'm'
    parameters: BasicParameters
    source_hashes: dict[str, str]
    transit: list[TransitSide]
    closest_transit_side: str | None
    closest_transit_sides: list[str]
    landuse: list[LanduseSide]
    entrances: list[EntranceResult]
    graph: dict
    origins: dict
    syntax: dict
    overlay_wgs84: dict
    limitations: list[str]


def direction(point: Point, centre: Point) -> str:
    dx, dy = point.x - centre.x, point.y - centre.y
    if dy >= abs(dx):
        return 'N'
    if dx > abs(dy):
        return 'E'
    if -dy >= abs(dx):
        return 'S'
    return 'W'


def uses(props: dict) -> list[str]:
    raw = props.get('gebruiksdoel', [])
    if isinstance(raw, str):
        raw = raw.replace(';', ',').split(',')
    return sorted(set(str(value).strip() for value in raw if str(value).strip())) or ['UNKNOWN']


def landuse_summary(site: Polygon, bag: list[dict], landuse: list[dict], params: BasicParameters,
                    cancel_event: threading.Event | None = None) -> tuple[list[dict], list[dict]]:
    centre = site.centroid
    ring = site.buffer(params.sector_buffer_m).difference(site)
    radius = max(site.bounds[2] - site.bounds[0], site.bounds[3] - site.bounds[1]) * 4 + params.sector_buffer_m * 4
    corners = {'N': [(-1, 1), (1, 1)], 'E': [(1, 1), (1, -1)], 'S': [(1, -1), (-1, -1)], 'W': [(-1, -1), (-1, 1)]}
    results, overlays = [], []
    for side in SIDES:
        _check_cancel(cancel_event)
        sector = ring.intersection(Polygon([(centre.x, centre.y)] + [(centre.x + dx * radius, centre.y + dy * radius) for dx, dy in corners[side]]))
        area_by_use: dict[str, float] = defaultdict(float)
        count = missing = 0
        for feature in bag:
            _check_cancel(cancel_event)
            point = shape(feature['geometry']).centroid
            if not ring.covers(point) or direction(point, centre) != side:
                continue
            count += 1
            props = feature['properties']
            raw_area = props.get('oppervlakte')
            try:
                area = float(raw_area)
            except (TypeError, ValueError):
                missing += 1
                continue
            if not math.isfinite(area) or area <= 0:
                missing += 1
                continue
            categories = uses(props)
            for category in categories:
                area_by_use[category] += area / len(categories)
        total = sum(area_by_use.values())
        geometries: dict[str, list] = defaultdict(list)
        for feature in landuse:
            _check_cancel(cancel_event)
            geom = shape(feature['geometry'])
            clipped = geom.intersection(sector)
            if clipped.area > 0:
                geometries[feature['properties']['landuse']].append(clipped)
        osm = {use: unary_union(parts).area for use, parts in geometries.items()}
        results.append({'side': side, 'bag_floor_area_m2': round(total, 2),
            'bag_usage_percent': {key: round(100 * value / total, 2) for key, value in sorted(area_by_use.items())} if total else {},
            'bag_object_count': count, 'missing_area_count': missing,
            'dominant_bag_use': max(area_by_use, key=area_by_use.get) if area_by_use else None,
            'osm_landuse_area_m2': {key: round(value, 2) for key, value in osm.items()},
            'osm_ring_area_percent': {key: round(100 * value / sector.area, 2) for key, value in osm.items()} if sector.area else {},
            'dominant_osm_landuse': max(osm, key=osm.get) if osm else None, 'sector_area_m2': round(sector.area, 2)})
        overlays.append({'type': 'Feature', 'properties': {'kind': 'sector', 'side': side}, 'geometry': mapping(sector)})
    return results, overlays


@dataclass(frozen=True)
class Snap:
    edge: int
    offset: float
    point: Point
    connector: float = 0


class WalkingGraph:
    """Edge lengths in RD metres, adjacency from source OSM node IDs only."""
    def __init__(self, features: list[dict], cancel_event: threading.Event | None = None):
        self.cancel_event = cancel_event
        self.edges: list[tuple[str, str, LineString, bool, bool]] = []
        self.adj = defaultdict(list)
        self.coords = {}
        self.imputed_ways = 0
        self.road_types = defaultdict(float)
        for feature in features:
            _check_cancel(cancel_event)
            props = feature['properties']
            allowed, imputed, _ = evaluate_way_for_mode(props, 'pedestrian')
            if not allowed:
                continue
            self.imputed_ways += int(imputed)
            geometry = shape(feature['geometry'])
            nodes = props.get('osm_node_ids')
            if geometry.geom_type != 'LineString' or not geometry.is_valid or not nodes or len(nodes) != len(geometry.coords):
                raise ValueError('walking edges require aligned OSM source nodes and LineString')
            oneway = str(props.get('oneway:foot', 'no'))
            forward, backward = oneway != '-1', oneway not in ('yes', '1')
            for start, end, a, b in zip(nodes, nodes[1:], geometry.coords, list(geometry.coords)[1:]):
                _check_cancel(cancel_event)
                if not all(math.isfinite(x) for x in (*a[:2], *b[:2])):
                    raise ValueError('nonfinite walking coordinate')
                u, v = str(start), str(end)
                for node, coord in ((u, a[:2]), (v, b[:2])):
                    if node in self.coords and math.dist(self.coords[node], coord) > .01:
                        raise ValueError('inconsistent coordinate for shared OSM source node')
                    self.coords[node] = coord
                line = LineString([a[:2], b[:2]])
                if line.length <= 0:
                    continue
                index = len(self.edges)
                self.edges.append((u, v, line, forward, backward))
                if forward:
                    self.adj[u].append((v, line.length, index))
                if backward:
                    self.adj[v].append((u, line.length, index))
                self.road_types[props.get('highway', 'unknown')] += line.length
        if not self.edges:
            raise ValueError('empty walking graph')
        self.tree = STRtree([edge[2] for edge in self.edges])

    def snap(self, point: Point, maximum: float) -> Snap | None:
        index = int(self.tree.nearest(point))
        line = self.edges[index][2]
        distance = point.distance(line)
        if distance > maximum:
            return None
        offset = line.project(point)
        return Snap(index, offset, line.interpolate(offset), distance)

    def entrances(self, site: Polygon, cancel_event: threading.Event | None = None) -> list[tuple[str, str, Snap]]:
        entries = []
        seen = set()
        for raw_index in self.tree.query(site.boundary):
            _check_cancel(cancel_event)
            index = int(raw_index)
            line = self.edges[index][2]
            intersection = line.intersection(site.boundary)
            if intersection.geom_type == 'Point':
                points = [intersection]
            elif intersection.geom_type == 'MultiPoint':
                points = list(intersection.geoms)
            else:
                continue  # Boundary-coincident roads do not prove an entrance.
            for point in points:
                key = (round(point.x, 3), round(point.y, 3))
                if key in seen:
                    continue
                seen.add(key)
                entries.append((f'entrance-{len(entries)+1}', direction(point, site.centroid), Snap(index, line.project(point), point)))
        return sorted(entries, key=lambda entry: (SIDES.index(entry[1]), entry[2].point.x, entry[2].point.y))

    def search(self, target: Snap, limit: float, cancel_event: threading.Event | None = None):
        # Reverse adjacency computes origin → entrance, including oneway:foot.
        if not hasattr(self, 'reverse'):
            self.reverse = defaultdict(list)
            for node, neighbours in self.adj.items():
                _check_cancel(cancel_event)
                for other, length, edge in neighbours:
                    self.reverse[other].append((node, length, edge))
        u, v, line, forward, backward = self.edges[target.edge]
        seeds = []
        if forward:
            seeds.append((target.offset, u))
        if backward:
            seeds.append((line.length - target.offset, v))
        distances, parent = {}, {}
        queue = []
        for distance, node in seeds:
            if distance < distances.get(node, math.inf):
                distances[node] = distance
                parent[node] = None
                heapq.heappush(queue, (distance, node))
        while queue:
            _check_cancel(cancel_event)
            distance, node = heapq.heappop(queue)
            if distance != distances[node] or distance > limit:
                continue
            for other, length, edge in self.reverse[node]:
                value = distance + length
                if value <= limit and value < distances.get(other, math.inf):
                    distances[other] = value
                    parent[other] = node
                    heapq.heappush(queue, (value, other))
        return distances, parent

    def route(self, origin: Snap, target: Snap, search, limit: float, cancel_event: threading.Event | None = None):
        distances, parent = search
        u, v, line, forward, backward = self.edges[origin.edge]
        candidates = []
        if backward and u in distances:
            candidates.append((origin.offset + distances[u], u))
        if forward and v in distances:
            candidates.append((line.length - origin.offset + distances[v], v))
        if origin.edge == target.edge and ((target.offset >= origin.offset and forward) or (target.offset <= origin.offset and backward)):
            candidates.append((abs(target.offset - origin.offset), None))
        if not candidates:
            return None
        distance, node = min(candidates, key=lambda candidate: candidate[0])
        if distance + origin.connector > limit:
            return None
        coords = [[origin.point.x, origin.point.y]]
        while node is not None:
            _check_cancel(cancel_event)
            coords.append(list(self.coords[node]))
            node = parent[node]
        coords.append([target.point.x, target.point.y])
        return distance + origin.connector, coords


class SyntaxOverlay:
    def __init__(self, segments: list[dict], params: BasicParameters):
        self.params = params
        self.segments = segments
        self.lines = [LineString(segment['coordinates']) for segment in segments]
        self.tree = STRtree(self.lines) if self.lines else None
        self.distributions = {key: sorted(segment[key] for segment in segments) for key in ('nain', 'nach')}
        if any(not math.isfinite(value) for values in self.distributions.values() for value in values):
            raise ValueError('invalid Syntax values')

    def summary(self, coords: list[list[float]], cancel_event: threading.Event | None = None) -> dict:
        from bisect import bisect_right
        total = matched = nain = nach = 0.
        for a, b in zip(coords, coords[1:]):
            _check_cancel(cancel_event)
            edge = LineString([a, b])
            if edge.length <= 0:
                continue
            total += edge.length
            if self.tree is None:
                continue
            middle = edge.interpolate(.5, normalized=True)
            index = int(self.tree.nearest(middle))
            line = self.lines[index]
            # Full path edge must be spatially coincident, not merely near a crossing.
            if not line.buffer(self.params.syntax_match_m).covers(edge):
                continue
            matched += edge.length
            segment = self.segments[index]
            nain += segment['nain'] * edge.length
            nach += segment['nach'] * edge.length
        result = {'status': 'UNAVAILABLE' if not matched else 'EXPLORATORY_PARTIAL_PATH_OVERLAY',
            'matched_length_m': round(matched, 2), 'path_length_m': round(total, 2),
            'coverage_ratio': round(matched / total, 4) if total else 0,
            'nain_mean': nain / matched if matched else None, 'nach_mean': nach / matched if matched else None,
            'multiplier': None}
        if matched and total and matched / total >= self.params.syntax_min_coverage:
            ranks = [bisect_right(self.distributions[key], result[key + '_mean']) / len(self.distributions[key]) for key in ('nain', 'nach')]
            result['multiplier'] = 1 + self.params.syntax_weight * sum(ranks) / 2
        return result


def calculate_basic(site: Polygon, network: list[dict], transit: list[dict], pois: list[dict], bag: list[dict], landuse: list[dict], *,
                    project_id: str, extent_id: str, study_area_id: str, study_area_version: str,
                    source_hashes: dict, params: BasicParameters | None = None, syntax_segments: list[dict] | None = None,
                    syntax_metadata: dict | None = None, cancel_event: threading.Event | None = None) -> BasicResult:
    _check_cancel(cancel_event)
    params = params or BasicParameters()
    if site.geom_type != 'Polygon' or not site.is_valid or site.is_empty or site.area <= 0:
        raise ValueError('valid EPSG:28992 site polygon required')
    graph = WalkingGraph(network, cancel_event)
    entries = graph.entrances(site, cancel_event)
    syntax = SyntaxOverlay(syntax_segments or [], params)
    origins, unsnapped = [], 0
    # A platform and stop_position may describe the same stop. Retain identities;
    # explicitly warn that no passenger-frequency or stop-area dedup is available.
    for kind, features in (('transit', transit), ('poi', pois), ('bag', bag)):
        for index, feature in enumerate(features):
            _check_cancel(cancel_event)
            props = feature['properties']
            point = shape(feature['geometry']).centroid
            if site.covers(point):
                continue
            if kind == 'transit':
                weight = max((params.transit_weights.get(mode, 0) for mode in props.get('modes', ['unknown'])), default=0)
            elif kind == 'poi':
                weight = max((value for key, value in params.poi_weights.items() if props.get(key)), default=0)
            else:
                weight = sum(params.bag_weights.get(use, 0) for use in uses(props)) / len(uses(props))
            snap = graph.snap(point, params.snap_max_m)
            if snap is None:
                unsnapped += 1
            origins.append({'id': str(feature.get('id', f'{kind}-{index}')), 'point': point, 'snap': snap, 'kind': kind,
                'weight': weight, 'name': props.get('name') or props.get('ref'), 'modes': props.get('modes', []), 'routes': props.get('routes', [])})
    transit_sides = {side: {} for side in SIDES}
    entrances, overlays = [], []
    for entrance_id, side, target in entries:
        _check_cancel(cancel_event)
        search = graph.search(target, params.distance_limit_m, cancel_event)
        arrivals = []
        for origin in origins:
            _check_cancel(cancel_event)
            if origin['snap'] is None:
                continue
            path = graph.route(origin['snap'], target, search, params.distance_limit_m, cancel_event)
            if path is None:
                continue
            distance, coordinates = path
            if origin['snap'].connector > 0:
                coordinates.insert(0, [origin['point'].x, origin['point'].y])
            arrivals.append((origin['weight'] * math.exp(-distance / params.decay_m), distance, origin, coordinates))
            if origin['kind'] == 'transit':
                for mode in origin['modes']:
                    previous = transit_sides[side].get(mode)
                    if previous is None or distance < previous['distance_m']:
                        transit_sides[side][mode] = {'origin_id': origin['id'], 'name': origin['name'], 'kind': 'transit',
                            'modes': origin['modes'], 'routes': origin['routes'], 'distance_m': round(distance, 2),
                            'connector_m': round(origin['snap'].connector, 2), 'contribution': 0, 'coordinates': coordinates,
                            'syntax': {'status': 'NOT_USED_FOR_NEAREST_TRANSIT'}}
        arrivals.sort(key=lambda arrival: (-arrival[0], arrival[2]['id']))
        routes = []
        # Only top routes get Syntax overlays. Ranking uses all origins' distance
        # potential; overlay informs interpretation without silently extrapolating.
        for contribution, distance, origin, coordinates in arrivals[:params.top_routes]:
            _check_cancel(cancel_event)
            route = {'origin_id': origin['id'], 'name': origin['name'], 'kind': origin['kind'], 'modes': origin['modes'],
                'routes': origin['routes'], 'distance_m': round(distance, 2), 'connector_m': round(origin['snap'].connector, 2),
                'contribution': round(contribution, 6), 'coordinates': coordinates, 'syntax': syntax.summary(coordinates, cancel_event)}
            routes.append(route)
            overlays.append({'type': 'Feature', 'properties': {'kind': 'arrival_route', 'entrance_id': entrance_id, 'origin_id': origin['id'], 'side': side}, 'geometry': mapping(LineString(coordinates))})
        entrances.append({'id': entrance_id, 'side': side, 'coordinates': [target.point.x, target.point.y],
            'status': 'INFERRED_NETWORK_BOUNDARY_INTERSECTION_NOT_APPROVED_ENTRANCE', 'reachable_origins': len(arrivals),
            'distance_potential': round(sum(value[0] for value in arrivals), 6), 'syntax_adjusted_potential': None,
            'rank': 0, 'major_routes': routes})
        overlays.append({'type': 'Feature', 'properties': {'kind': 'entrance', 'id': entrance_id, 'side': side}, 'geometry': mapping(target.point)})
    entrances.sort(key=lambda entry: (-entry['distance_potential'], entry['id']))
    for rank, entry in enumerate(entrances, 1):
        entry['rank'] = rank
    modes = sorted({mode for feature in transit for mode in feature['properties'].get('modes', ['unknown'])})
    sides = [{'side': side, 'status': 'ROUTED' if transit_sides[side] else 'UNREACHABLE_OR_NO_ENTRANCE',
        'nearest_by_mode': {mode: transit_sides[side].get(mode) for mode in modes}} for side in SIDES]
    distances = {side: min((value['distance_m'] for value in transit_sides[side].values()), default=math.inf) for side in SIDES}
    closest = [side for side in SIDES if math.isfinite(distances[side]) and abs(distances[side] - min(distances.values())) <= .01]
    land, sectors = landuse_summary(site, bag, landuse, params, cancel_event)
    overlays.extend(sectors)
    for feature in transit:
        overlays.append({**feature, 'properties': {**feature['properties'], 'kind': 'station'}})
    for item in sides:
        for route in item['nearest_by_mode'].values():
            if route:
                overlays.append({'type': 'Feature', 'properties': {'kind': 'nearest_route', 'side': item['side'], 'name': route['name']}, 'geometry': mapping(LineString(route['coordinates']))})
    to_wgs = Transformer.from_crs(28992, 4326, always_xy=True).transform
    overlay = {'type': 'FeatureCollection', 'features': [{**feature, 'geometry': mapping(transform(to_wgs, shape(feature['geometry'])))} for feature in overlays]}
    metadata = syntax_metadata or {'status': 'UNAVAILABLE', 'formal_result': False}
    return BasicResult(status='EXPLORATORY' if entries and transit and bag else 'INCOMPLETE_DATA', project_id=project_id, extent_id=extent_id,
        study_area_id=study_area_id, study_area_version=study_area_version, created_at=utc(), parameters=params,
        source_hashes={**source_hashes, 'parameters': digest(encoded(params.model_dump())), 'analysis_code': digest(Path(__file__).read_bytes()),
            'mode_policy_code': digest((Path(__file__).parents[1] / 'regional_network.py').read_bytes())}, transit=sides,
        closest_transit_side=closest[0] if len(closest) == 1 else None, closest_transit_sides=closest, landuse=land, entrances=entrances,
        graph={'nodes': len(graph.coords), 'edges': len(graph.edges), 'imputed_access_ways': graph.imputed_ways,
            'road_length_m_by_highway': {key: round(value, 2) for key, value in graph.road_types.items()},
            'topology': 'SOURCE_OSM_NODE_IDS_ONLY_NO_GEOMETRIC_CROSSING_LINKS'},
        origins={'total': len(origins), 'unsnapped': unsnapped, 'by_kind': {kind: sum(o['kind'] == kind for o in origins) for kind in ('transit', 'poi', 'bag')}},
        syntax=metadata, overlay_wgs84=overlay, limitations=[
            'Arrival potential is an assumed distance-decay estimate, not observed footfall, capacity or trip counts.',
            'Entrances are inferred walking-edge/boundary intersections; physical gates and opening hours are unverified.',
            'Station/POI connectors up to snap_max_m are assumed access links; barriers, vertical access and stop-area duplicates remain unverified.',
            'BAG percentages use recorded object floor area, not land parcel area; multi-use objects split equally (ASSUMED_COMMANDER). Missing areas are excluded and counted.',
            'OSM landuse is observed mapping, not legally adopted zoning; overlapping categories may sum above 100%.',
            'OSM access defaults follow existing mode policy; source-node topology preserves crossings but missing OSM connectivity stays disconnected.',
            'Syntax is a spatial overlay on the top arrival routes, with coverage reported. Entrance ranking uses distance potential; no unobserved Syntax-adjusted total is fabricated.',
            'Nearest stations are within the acquired transit envelope and distance_limit_m, not a claim of global nearest service; no timetables or GTFS frequency.',
        ])


class BasicAnalysisJobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    extent_id: str = Field(min_length=1, max_length=200)


class BasicAnalysisJobResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str
    status: Literal['PENDING', 'RUNNING', 'CANCELLING', 'SUCCEEDED', 'FAILED', 'CANCELLED']
    created_at: str
    elapsed_seconds: float = Field(ge=0)
    cache_hit: bool
    last_analysis_at: str | None = None
    result: BasicResult | None = None
    error: str | None = None


@dataclass(frozen=True)
class PreparedBasicAnalysis:
    cache_key: tuple
    kwargs: dict[str, Any]


@dataclass
class BasicAnalysisJobState:
    job_id: str
    project_id: str
    extent_id: str
    created_at: str
    cache_key: tuple
    status: str = 'PENDING'
    cache_hit: bool = False
    last_analysis_at: str | None = None
    result: BasicResult | None = None
    error: str | None = None
    prepared: PreparedBasicAnalysis | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    started_monotonic: float | None = None
    finished_monotonic: float | None = None
    thread: threading.Thread | None = None


class BasicAnalysisService:
    MAX_CACHE_ENTRIES = 16
    MAX_RETAINED_JOBS = 32
    MAX_ACTIVE_JOBS = 2

    def __init__(self, store: ProjectStateStore, *, syntax_root: Path | None = None, syntax_hash: str | None = None):
        self.store, self.syntax_root, self.syntax_hash = store, syntax_root, syntax_hash
        self.cache: OrderedDict[tuple, BasicResult] = OrderedDict()
        self.jobs: OrderedDict[str, BasicAnalysisJobState] = OrderedDict()
        self.inflight: dict[tuple, str] = {}
        self.lock = threading.RLock()

    def _prepare(self, project_id: str, extent_id: str, cancel_event: threading.Event | None = None) -> PreparedBasicAnalysis:
        _check_cancel(cancel_event)
        project = self.store.current(project_id)
        extent = self.store.current(extent_id)
        if project.entity_type != 'Project' or extent.entity_type != 'SiteExtentDraft' or extent.project_id != project_id:
            raise EntityNotFoundError(extent_id)
        events = [event for event in self.store.events(project_id) if event.action == 'ExtentDataFetched' and event.target_id == extent_id]
        if not events:
            raise ValueError('EXTENT_FETCH_NOT_READY')
        event = events[-1]
        path = Path(event.payload['manifest_path'])
        manifest_data = path.read_bytes()
        if digest(manifest_data) != event.payload['manifest_sha256']:
            raise ValueError('source manifest hash mismatch')
        manifest = verified_manifest(path)
        if manifest['project_id'] != project_id or manifest['extent_id'] != extent_id:
            raise ValueError('source manifest binding mismatch')
        files = {Path(item['path']).name: item for item in manifest['files']}
        layers, hashes = {}, {'extent_manifest': digest(manifest_data),
                              'extent_geometry': digest(encoded(extent.payload['geometry_epsg28992']))}
        for key, name in [('network', 'network-pedestrian.geojson'), ('transit', 'transit.geojson'), ('pois', 'pois.geojson'), ('bag', 'bag-uses.geojson'), ('landuse', 'landuse.geojson')]:
            _check_cancel(cancel_event)
            if name not in files:
                raise ValueError('MISSING_BASIC_SOURCE: ' + name)
            document = json.loads(Path(files[name]['path']).read_bytes())
            if document.get('crs', {}).get('properties', {}).get('name') != 'EPSG:28992':
                raise ValueError('basic analysis currently requires EPSG:28992 sources')
            layers[key] = document['features']
            hashes[key] = files[name]['sha256']
        _check_cancel(cancel_event)
        study = self.store.current(project.payload['active_study_area_id'])
        if study.entity_type != 'StudyArea' or study.project_id != project_id or study.payload.get('horizontal_crs', study.payload.get('crs')) != 'EPSG:28992':
            raise ValueError('active StudyArea binding/CRS mismatch')
        artifact = self.store.current(study.payload['geometry_artifact_id'])
        data = Path(artifact.payload['uri']).read_bytes()
        if digest(data).removeprefix('sha256:') != artifact.payload['sha256'].removeprefix('sha256:'):
            raise ValueError('StudyArea hash mismatch')
        hashes['study_area'] = digest(data)
        study_version = str(study.payload.get('version', study.revision))
        hashes['study_area_binding'] = digest(encoded({'id': study.entity_id, 'version': study_version, 'revision': study.revision}))
        document = json.loads(data)
        site = shape(document['geometry'] if document.get('type') == 'Feature' else document)
        if not shape(extent.payload['geometry_epsg28992']).buffer(.01).covers(site):
            raise ValueError('acquisition extent does not cover active StudyArea')
        segments, metadata = [], None
        if self.syntax_root is not None:
            if self.syntax_hash is None:
                raise ValueError('Syntax manifest pin required')
            syntax_manifest = load_verified_manifest(self.syntax_root, self.syntax_hash)
            syntax_data = load_verified_mode(self.syntax_root, syntax_manifest, 'pedestrian')
            hashes['syntax_manifest'] = 'sha256:' + sha256_file(self.syntax_root / 'manifest.json')
            hashes['syntax_pedestrian'] = 'sha256:' + sha256_file(self.syntax_root / syntax_manifest['outputs']['pedestrian']['path'])
            segments = syntax_data['segments']
            metadata = syntax_context_readiness(mode='pedestrian', radius_m=syntax_data['radius_m'], manifest_sha256=self.syntax_hash)
        params = BasicParameters()
        hashes['parameters'] = digest(encoded(params.model_dump()))
        hashes['analysis_code'] = digest(Path(__file__).read_bytes())
        hashes['mode_policy_code'] = digest((Path(__file__).parents[1] / 'regional_network.py').read_bytes())
        cache_key = (project_id, extent_id, tuple(sorted(hashes.items())))
        return PreparedBasicAnalysis(cache_key=cache_key, kwargs={
            'site': site, **layers, 'project_id': project_id, 'extent_id': extent_id,
            'study_area_id': study.entity_id, 'study_area_version': study_version,
            'source_hashes': hashes, 'syntax_segments': segments, 'syntax_metadata': metadata,
            'params': params,
        })

    def _cached(self, cache_key: tuple) -> BasicResult | None:
        with self.lock:
            result = self.cache.get(cache_key)
            if result is not None:
                self.cache.move_to_end(cache_key)
            return result

    def _run_prepared(self, prepared: PreparedBasicAnalysis, cancel_event: threading.Event | None = None) -> tuple[BasicResult, bool]:
        _check_cancel(cancel_event)
        cached = self._cached(prepared.cache_key)
        if cached is not None:
            return cached, True
        result = calculate_basic(**prepared.kwargs, cancel_event=cancel_event)
        _check_cancel(cancel_event)
        with self.lock:
            existing = self.cache.get(prepared.cache_key)
            if existing is not None:
                self.cache.move_to_end(prepared.cache_key)
                return existing, True
            self.cache[prepared.cache_key] = result
            self.cache.move_to_end(prepared.cache_key)
            while len(self.cache) > self.MAX_CACHE_ENTRIES:
                self.cache.popitem(last=False)
        return result, False

    def get(self, project_id: str, extent_id: str) -> BasicResult:
        return self._run_prepared(self._prepare(project_id, extent_id))[0]

    def create_job(self, project_id: str, extent_id: str) -> tuple[BasicAnalysisJobState, bool]:
        prepared = self._prepare(project_id, extent_id)
        job_id = str(uuid.uuid4())
        now = time.monotonic()
        state = BasicAnalysisJobState(job_id=job_id, project_id=project_id, extent_id=extent_id,
            created_at=utc(), cache_key=prepared.cache_key, prepared=prepared)
        cached = self._cached(prepared.cache_key)
        with self.lock:
            self._prune_jobs()
            if cached is not None:
                state.status = 'SUCCEEDED'
                state.cache_hit = True
                state.result = cached
                state.last_analysis_at = cached.created_at
                state.started_monotonic = state.finished_monotonic = now
                self.jobs[job_id] = state
                return state, True
            existing_id = self.inflight.get(prepared.cache_key)
            if existing_id is not None and existing_id in self.jobs:
                return self.jobs[existing_id], False
            active = sum(job.status in ('PENDING', 'RUNNING', 'CANCELLING') for job in self.jobs.values())
            if active >= self.MAX_ACTIVE_JOBS:
                raise ValueError('BASIC_ANALYSIS_JOB_CAPACITY_REACHED')
            state.status = 'RUNNING'
            state.started_monotonic = now
            state.thread = threading.Thread(target=self._run_job, args=(state,), daemon=True,
                name=f'basic-analysis-{job_id[:8]}')
            self.jobs[job_id] = state
            self.inflight[prepared.cache_key] = job_id
            state.thread.start()
            return state, False

    def _run_job(self, state: BasicAnalysisJobState) -> None:
        try:
            if state.prepared is None:
                raise ValueError('BASIC_ANALYSIS_INPUT_NOT_PREPARED')
            result, cache_hit = self._run_prepared(state.prepared, state.cancel_event)
            with self.lock:
                if state.cancel_event.is_set():
                    state.status = 'CANCELLED'
                else:
                    state.status = 'SUCCEEDED'
                    state.result = result
                    state.cache_hit = cache_hit
                    state.last_analysis_at = result.created_at
        except AnalysisCancelled:
            with self.lock:
                state.status = 'CANCELLED'
        except Exception as exc:
            with self.lock:
                state.status = 'FAILED'
                state.error = str(exc)
        finally:
            with self.lock:
                state.finished_monotonic = time.monotonic()
                self.inflight.pop(state.cache_key, None)

    def cancel_job(self, project_id: str, job_id: str) -> BasicAnalysisJobState:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None or state.project_id != project_id:
                raise EntityNotFoundError(job_id)
            if state.status in ('PENDING', 'RUNNING'):
                state.cancel_event.set()
                state.status = 'CANCELLING'
            return state

    def job(self, project_id: str, job_id: str) -> BasicAnalysisJobState:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None or state.project_id != project_id:
                raise EntityNotFoundError(job_id)
            return state

    def _prune_jobs(self) -> None:
        terminal = ('SUCCEEDED', 'FAILED', 'CANCELLED')
        while len(self.jobs) >= self.MAX_RETAINED_JOBS:
            removable = next((job_id for job_id, job in self.jobs.items() if job.status in terminal), None)
            if removable is None:
                break
            self.jobs.pop(removable)

    def job_response(self, state: BasicAnalysisJobState) -> BasicAnalysisJobResponse:
        now = time.monotonic()
        elapsed = 0.0
        if state.started_monotonic is not None:
            end = state.finished_monotonic if state.finished_monotonic is not None else now
            elapsed = max(0.0, end - state.started_monotonic)
        with self.lock:
            return BasicAnalysisJobResponse(job_id=state.job_id, status=state.status, created_at=state.created_at,
                elapsed_seconds=round(elapsed, 3), cache_hit=state.cache_hit,
                last_analysis_at=state.last_analysis_at, result=state.result, error=state.error)


def create_basic_analysis_router(store: ProjectStateStore, *, syntax_root: Path | None = None, syntax_hash: str | None = None) -> APIRouter:
    router = APIRouter(prefix='/api/v1/projects/{project_id}/site-analysis')
    service = BasicAnalysisService(store, syntax_root=syntax_root, syntax_hash=syntax_hash)

    def not_found(exc: EntityNotFoundError) -> HTTPException:
        return HTTPException(404, 'project, extent, or analysis job not found')

    @router.get('/basic', response_model=BasicResult)
    def basic(project_id: str, extent_id: str = Query(min_length=1)):
        try:
            return service.get(project_id, extent_id)
        except EntityNotFoundError as exc:
            raise not_found(exc) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post('/basic/jobs', response_model=BasicAnalysisJobResponse)
    def create_basic_job(project_id: str, payload: BasicAnalysisJobRequest, response: Response):
        try:
            state, cache_hit = service.create_job(project_id, payload.extent_id)
            response.status_code = 200 if cache_hit else 202
            return service.job_response(state)
        except EntityNotFoundError as exc:
            raise not_found(exc) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get('/basic/jobs/{job_id}', response_model=BasicAnalysisJobResponse)
    def get_basic_job(project_id: str, job_id: str):
        try:
            return service.job_response(service.job(project_id, job_id))
        except EntityNotFoundError as exc:
            raise not_found(exc) from exc

    @router.delete('/basic/jobs/{job_id}', response_model=BasicAnalysisJobResponse)
    def cancel_basic_job(project_id: str, job_id: str):
        try:
            return service.job_response(service.cancel_job(project_id, job_id))
        except EntityNotFoundError as exc:
            raise not_found(exc) from exc

    return router
