"""Scenario road contract and bounded, mode-specific PST comparison (S5).

No network acquisition or HumanDecision is performed here. Inputs are projected
EPSG:28992 metres. Legacy v6 semantics are explicitly commander assumptions.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree

from .pst_syntax import DEFAULT_PST_MANIFEST, prepare_pst_lines
from .syntax_engines.pst_adapter import PSTAdapter, PSTRequest

Mode = Literal['pedestrian', 'bicycle', 'motor_vehicle']
MODES = {'pedestrian': (1500, 800.0), 'bicycle': (6000, 2000.0), 'motor_vehicle': (20000, 10000.0)}
IMPLEMENTATION_SHA256 = 'sha256:' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
EXTRACTION_ROOT = Path.home() / '.local/share/urban-design-data/week5-syntax-modes/extracted'


class ProposalRoad(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    coordinates: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=2)
    width_m: FiniteFloat = Field(gt=0)
    modes: list[Mode] = Field(min_length=1, max_length=3)
    origin: Literal['retained', 'transformed', 'new']
    source_road_ids: list[str] = Field(default_factory=list)
    semantics_provenance: str = Field(min_length=1)
    layer: int = 0

    @model_validator(mode='after')
    def require_lineage(self):
        if self.origin in ('retained','transformed') and not self.source_road_ids:
            raise ValueError('retained/transformed roads require source_road_ids')
        return self

    @field_validator('modes')
    @classmethod
    def unique_modes(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('modes must be unique')
        return sorted(value)

    @field_validator('coordinates')
    @classmethod
    def valid_line(cls, value):
        line = LineString(value)
        if not line.is_valid or line.length <= 0 or any(a == b for a, b in zip(value, value[1:])):
            raise ValueError('road must have finite, non-degenerate line geometry')
        return value


class MergeParameters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snap_tolerance_m: FiniteFloat = Field(default=1.0, ge=0, le=10)
    topology_epsilon_m: FiniteFloat = Field(default=1e-6, gt=0, le=0.001)
    crs: Literal['EPSG:28992'] = 'EPSG:28992'
    policy_version: Literal['scenario-syntax-merge-v2'] = 'scenario-syntax-merge-v2'


def digest(value: Any) -> str:
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def assumed_road_properties(identifier: str) -> dict[str, Any]:
    """No width-based inference. IDs supplied by the generator establish role."""
    collector = identifier.startswith(('road:south_strip_collector:', 'road:south_strip_connector:'))
    return {'modes': ['pedestrian', 'bicycle', 'motor_vehicle'] if collector else ['pedestrian', 'bicycle'],
            'origin': 'new', 'semantics_provenance': 'ASSUMED_COMMANDER',
            'semantics_policy_version': 'v6-mode-defaults-2026-10-08', 'road_id': identifier}


def roads_from_geojson(document: dict) -> tuple[list[ProposalRoad], Any]:
    if document.get('crs', {}).get('properties', {}).get('name') != 'EPSG:28992':
        raise ValueError('BLOCKED: proposal CRS must explicitly be EPSG:28992')
    areas = [shape(f['geometry']) for f in document['features'] if f.get('properties', {}).get('role') == 'site_area']
    if len(areas) != 1 or areas[0].geom_type not in ('Polygon', 'MultiPolygon') or not areas[0].is_valid or areas[0].area <= 0:
        raise ValueError('BLOCKED: one valid site_area is required')
    roads = []
    for i, feature in enumerate(document['features']):
        p = feature.get('properties', {})
        if p.get('role') != 'road' and p.get('feature_kind') not in ('road_segment', 'road_centerline'):
            continue
        identifier = str(p.get('road_id', feature.get('id', f'legacy-road-{i}')))
        # Partial explicit semantics are invalid, rather than silently filled in.
        explicit = any(k in p for k in ('modes', 'origin', 'semantics_provenance'))
        semantics = p if explicit else assumed_road_properties(identifier)
        geometry = shape(feature['geometry'])
        if geometry.geom_type != 'LineString':
            raise ValueError('BLOCKED: road must be a LineString')
        roads.append(ProposalRoad(id=identifier, coordinates=list(geometry.coords), width_m=p['width_m'],
            modes=semantics['modes'], origin=semantics['origin'], semantics_provenance=semantics['semantics_provenance'],
            source_road_ids=p.get('source_road_ids', []), layer=p.get('layer', 0)))
    if len({r.id for r in roads}) != len(roads):
        raise ValueError('BLOCKED: duplicate proposal road IDs')
    return roads, areas[0]


def _parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'LineString':
        return [geometry] if geometry.length > 0 else []
    return [p for g in getattr(geometry, 'geoms', ()) for p in _parts(g)]


def _feature(identifier, line, properties=None):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(line), 'properties': properties or {}}


WELD_TOLERANCE_M = 0.05


def _weld_endpoints(features, unlink_points, epsilon, tolerance=WELD_TOLERANCE_M):
    """Merge same-layer segment endpoints closer than ``tolerance`` onto one node.

    Cutting two lines at the same junction with project/substring yields endpoints
    that differ by floating error (observed 0.5 mm to 3.4 cm); PST connects only
    identical coordinates, so such junctions silently broke streets apart.
    Context coordinates win, so the unedited network keeps its exact geometry.
    """
    ends = []
    for i, f in enumerate(features):
        coords = f['geometry']['coordinates']
        layer = int(f['properties'].get('layer') or 0)
        proposal = bool(f['properties'].get('proposal'))
        ends += [(i, 0, Point(coords[0]), layer, proposal), (i, -1, Point(coords[-1]), layer, proposal)]
    if not ends:
        return features, []
    parent = list(range(len(ends)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    tree = STRtree([e[2] for e in ends])
    for a, (_, _, p, layer, _) in enumerate(ends):
        if any(p.distance(u) <= epsilon for u in unlink_points):
            continue
        for b in tree.query(p.buffer(tolerance)):
            b = int(b)
            if b != a and ends[b][3] == layer and 0 < p.distance(ends[b][2]) <= tolerance \
                    and not any(ends[b][2].distance(u) <= epsilon for u in unlink_points):
                parent[find(a)] = find(b)
    clusters: dict[int, list[int]] = {}
    for a in range(len(ends)):
        clusters.setdefault(find(a), []).append(a)
    canonical = {}
    for members in clusters.values():
        best = min(members, key=lambda m: (ends[m][4], ends[m][2].x, ends[m][2].y))
        for m in members:
            canonical[m] = (ends[best][2].x, ends[best][2].y)
    welded, dropped = [], []
    for i, f in enumerate(features):
        coords = [tuple(c) for c in f['geometry']['coordinates']]
        coords[0] = canonical[2 * i]; coords[-1] = canonical[2 * i + 1]
        line = LineString(coords)
        if line.length <= epsilon:
            dropped.append(f['id']); continue
        welded.append(_feature(f['id'], line, f['properties']))
    return welded, dropped


def _trim_near_collinear(kept, epsilon, tolerance=WELD_TOLERANCE_M, min_overlap_m=0.3, max_angle_deg=10.0):
    """Drop proposal stretches lying within ``tolerance`` of, and parallel to, a context segment.

    The exact-coverage pass uses ``epsilon``; a proposal offset by a few millimetres from an
    existing road survives it, and after endpoint welding the two lines overlap, which PST
    merges (losing a source line). Crossings are unaffected: only overlaps longer than
    ``min_overlap_m`` and within ``max_angle_deg`` of the context direction are removed.
    """
    context = [(shape(f['geometry']), int(f['properties'].get('layer') or 0)) for f in kept if not f['properties'].get('proposal')]
    tree = STRtree([g for g, _ in context]) if context else None
    out, trimmed = [], []
    def heading(line):
        (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
        return math.atan2(y1 - y0, x1 - x0)
    for feature in kept:
        if not feature['properties'].get('proposal') or tree is None:
            out.append(feature); continue
        geometry = shape(feature['geometry']); layer = int(feature['properties'].get('layer') or 0)
        overlaps = []
        for i in tree.query(geometry.buffer(tolerance)):
            g, l = context[int(i)]
            if l != layer:
                continue
            for part in _parts(geometry.intersection(g.buffer(tolerance, cap_style=2))):
                if part.length < min_overlap_m:
                    continue
                d = abs((heading(part) - heading(g) + math.pi / 2) % math.pi - math.pi / 2)
                if math.degrees(d) <= max_angle_deg:
                    overlaps.append(part)
        if not overlaps:
            out.append(feature); continue
        rest = geometry.difference(unary_union([o.buffer(epsilon * 10, cap_style=2) for o in overlaps]))
        pieces = [g for g in _parts(rest) if g.length > 0.05]
        trimmed.append(feature['id'])
        for k, piece in enumerate(pieces):
            out.append(_feature(f"{feature['id']}:trim:{k}", piece, feature['properties']))
    return out, trimmed


def merge_network(features: list[dict], roads: list[ProposalRoad], site, mode: Mode,
                  parameters: MergeParameters, unlinks=()) -> dict:
    """Replace interior geometry, retain exterior stubs, snap then node junctions.

    Context overpasses retain their source geometry and unlinks. Only ground-level
    proposals may meet ground-level context. No global unary_union is applied.
    """
    epsilon = parameters.topology_epsilon_m
    selected = [r for r in roads if mode in r.modes]
    retained = {s for r in selected if r.origin == 'retained' for s in r.source_road_ids}
    source_ids = {str(f.get('id', f.get('properties', {}).get('osm_id'))) for f in features}
    if not retained.issubset(source_ids):
        raise ValueError('BLOCKED: retained road references absent from this mode network')
    by_id = {str(f.get('id', f.get('properties', {}).get('osm_id'))): shape(f['geometry']) for f in features}
    for road in selected:
        if road.origin == 'retained':
            expected = unary_union([by_id[s] for s in road.source_road_ids])
            if expected.symmetric_difference(LineString(road.coordinates)).length > epsilon:
                raise ValueError('BLOCKED: retained geometry differs from its source road references')
    context, removed = [], []
    for i, f in enumerate(features):
        identifier = str(f.get('id', f'context-{i}'))
        line = shape(f['geometry'])
        keep = identifier in retained
        interior = line.intersection(site).difference(site.boundary)
        if not keep and interior.length > epsilon:
            removed.extend(_feature(identifier, p, f.get('properties')) for p in _parts(interior))
            parts = _parts(line.difference(interior))
        else:
            parts = [line]
        for j, part in enumerate(parts):
            context.append(_feature(identifier if len(parts) == 1 else f'{identifier}:outside:{j}', part, f.get('properties')))
    context_lines = [shape(f['geometry']) for f in context]
    # Boundary clipping introduces real junction nodes; all original vertices are also nodes.
    candidates = [(Point(c), int(f.get('properties', {}).get('layer') or 0))
                  for f, line in zip(context, context_lines) for c in line.coords]
    points = [p for p, _ in candidates]
    point_tree = STRtree(points) if points else None
    unlink_points = [Point(p) for p in unlinks]
    snapped, snap_records = [], []
    for road in selected:
        if road.origin == 'retained' and road.source_road_ids:
            continue  # already preserved; no duplicate insertion
        coords = list(road.coordinates)
        for end in (0, -1):
            p = Point(coords[end])
            nearby = point_tree.query(p.buffer(parameters.snap_tolerance_m + epsilon)) if point_tree else []
            eligible = [(p.distance(points[int(i)]), int(i)) for i in nearby
                        if candidates[int(i)][1] == road.layer
                        and p.distance(points[int(i)]) <= parameters.snap_tolerance_m
                        and not any(points[int(i)].distance(u) <= epsilon for u in unlink_points)]
            if eligible:
                distance, index = min(eligible, key=lambda x: (x[0], points[x[1]].x, points[x[1]].y))
                coords[end] = tuple(points[index].coords)[0]
                snap_records.append({'road_id': road.id, 'endpoint': end, 'distance_m': distance, 'target': coords[end]})
        if LineString(coords).length <= epsilon:
            raise ValueError('BLOCKED: snapping collapsed a proposal road')
        snapped.append(_feature('proposal:' + road.id, LineString(coords), {'layer': road.layer, 'proposal': True}))
    # Only proposal/context and proposal/proposal intersections are new junctions.
    combined = context + snapped
    lines = context_lines + [shape(f['geometry']) for f in snapped]
    tree = STRtree(lines) if lines else None
    cuts: dict[int, set[float]] = {i: set() for i in range(len(lines))}
    connections = []
    derived_unlinks = []
    for i in range(len(context), len(lines)):
        for raw_j in tree.query(lines[i]):
            j = int(raw_j)
            if i == j or (j >= len(context) and j < i):
                continue
            intersection = lines[i].intersection(lines[j])
            if int(combined[i]['properties'].get('layer') or 0) != int(combined[j]['properties'].get('layer') or 0):
                if intersection.geom_type == 'Point':
                    derived_unlinks.append(tuple(intersection.coords)[0])
                elif intersection.geom_type == 'MultiPoint':
                    derived_unlinks.extend(tuple(p.coords)[0] for p in intersection.geoms)
                elif intersection.length > epsilon:
                    raise ValueError('BLOCKED: overlapping proposal roads at different layers cannot be represented by point unlinks')
                continue
            junctions = []
            if intersection.geom_type == 'Point':
                junctions = [intersection]
            elif intersection.geom_type == 'MultiPoint':
                junctions = list(intersection.geoms)
            else:
                junctions = [Point(c) for p in _parts(intersection) for c in (p.coords[0], p.coords[-1])]
            for p in junctions:
                if any(p.distance(u) <= epsilon for u in unlink_points):
                    continue
                cuts[i].add(lines[i].project(p)); cuts[j].add(lines[j].project(p))
                if j < len(context):
                    connections.append(tuple(p.coords)[0])
        # Also split proposal roads at every boundary crossing.
        crossing = lines[i].intersection(site.boundary)
        for p in ([crossing] if crossing.geom_type == 'Point' else getattr(crossing, 'geoms', ())):
            if p.geom_type == 'Point':
                cuts[i].add(lines[i].project(p))
    noded = []
    for i, (f, line) in enumerate(zip(combined, lines)):
        distances = sorted({0.0, line.length, *cuts[i]})
        parts = [substring(line, a, b) for a, b in zip(distances, distances[1:]) if b - a > epsilon]
        noded.extend(_feature(f['id'] if len(parts) == 1 else f"{f['id']}:part:{j}", part, f['properties']) for j, part in enumerate(parts))
    # A proposal segment lying on existing same-layer segments of this mode adds
    # nothing to the graph there (it is already walkable/rideable); PST merges the
    # duplicate and then reports the proposal source line as missing. Drop fully
    # covered proposal segments and keep only the uncovered stretches of partially
    # covered ones (coverage may come from several existing segments), with a record.
    covered = []
    kept = [f for f in noded if not f['properties'].get('proposal')]
    base = [(shape(f['geometry']), int(f['properties'].get('layer') or 0)) for f in kept]
    tree = STRtree([g for g, _ in base]) if base else None
    accepted = []
    for feature in noded:
        if not feature['properties'].get('proposal'):
            continue
        geometry = shape(feature['geometry'])
        layer = int(feature['properties'].get('layer') or 0)
        near = [base[i][0] for i in (tree.query(geometry.buffer(epsilon)) if tree is not None else []) if base[i][1] == layer]
        near += [g for g, l in accepted if l == layer and g.distance(geometry) <= epsilon]
        if not near:
            kept.append(feature); accepted.append((geometry, layer)); continue
        cover = unary_union([g.buffer(epsilon) for g in near])
        rest = geometry.difference(cover)
        if rest.is_empty or rest.length <= 0.05:
            covered.append(feature['id']); continue
        if geometry.length - rest.length <= 0.01:
            kept.append(feature); accepted.append((geometry, layer)); continue
        pieces = [g for g in (rest.geoms if hasattr(rest, 'geoms') else [rest]) if g.geom_type == 'LineString' and g.length > 0.05]
        covered.append(feature['id'])
        for k, piece in enumerate(pieces):
            kept.append(_feature(f"{feature['id']}:uncovered:{k}", piece, feature['properties']))
            accepted.append((piece, layer))
    kept, near_collinear_trimmed = _trim_near_collinear(kept, epsilon)
    covered.extend(near_collinear_trimmed)
    noded, welded_away = _weld_endpoints(kept, unlink_points, epsilon)
    unchanged = not removed and not snapped
    # A fully retained network has existing connections even without inserted roads.
    retained_connections = []
    for f in context:
        if f['id'] not in retained:
            continue
        crossing = shape(f['geometry']).intersection(site.boundary)
        for point in ([crossing] if crossing.geom_type == 'Point' else getattr(crossing, 'geoms', ())):
            if point.geom_type == 'Point' and not any(point.distance(u) <= epsilon for u in unlink_points):
                retained_connections.append(tuple(point.coords)[0])
    connected = bool(connections or retained_connections) or (mode == 'motor_vehicle' and unchanged)
    return {'status': 'READY' if connected else 'BLOCKED', 'reason': None if connected else 'NO_SURROUNDING_NETWORK_CONNECTION',
            'features': noded, 'removed': removed, 'covered_by_existing': covered, 'snaps': snap_records, 'connection_points': sorted(set(connections + retained_connections)),
            'derived_unlinks': sorted(set(derived_unlinks)), 'welded_away': welded_away, 'weld_tolerance_m': WELD_TOLERANCE_M, 'unchanged': unchanged, 'proposal_road_count': len(selected)}


def _compute(features, adapter, radius, unlinks, site):
    result = adapter.compute(PSTRequest(lines=prepare_pst_lines(features), radius_m=radius, radius_mode='walking', unlinks=tuple(unlinks)))
    rows = []
    for i, s in enumerate(result.segments):
        nc = max(0, result.node_counts[i] - 1); td = result.total_depths[i]; choice = result.choices[i] / 2
        line = LineString([s.start, s.end]); distance = line.distance(site)
        rows.append({'id': s.id, 'source_line_id': s.source_line_id, 'coordinates': [s.start, s.end],
                     'nain': nc ** 1.2 / (td + 2) if nc > 0 and td > 0 else 0.0,
                     'nach': math.log(choice + 1) / math.log(td + 3) if choice > 0 and td > 0 else 0.0,
                     'inside_site': line.intersection(site).length > 1e-6, 'distance_to_site_m': distance,
                     'entrance': line.intersects(site.boundary)})
    return rows


def _breaks(rows, metric):
    values = sorted(r[metric] for r in rows)
    return [values[0], *[values[min(len(values)-1, int(len(values)*q))] for q in (.2, .4, .6, .8)], values[-1]] if values else [0.] * 6


def _metrics(rows, high_threshold):
    inside = [r for r in rows if r['inside_site']]
    entrances = [r for r in rows if r['entrance']]
    mean = lambda rs, key: sum(r[key] for r in rs)/len(rs) if rs else None
    return {'inside_segment_count': len(inside), 'mean_integration_nain': mean(inside, 'nain'),
            'high_segment_ratio': sum(r['nain'] > high_threshold for r in inside)/len(inside) if inside else None,
            'entrance_integration_nain': mean(entrances, 'nain'),
            'through_site_choice_nach': mean(inside, 'nach'),
            'through_site_choice_method': 'mean NACH of interior segments; proxy, not observed pedestrian volume or a through-trip count',
            'weighting': 'unweighted segment mean', 'high_threshold_nain': high_threshold,
            'high_definition': 'above baseline context 60th percentile (High or Very High); fixed for before and after'}


def segment_diff(before, after, epsilon=1e-6):
    """Compare on common geometric support; added/removed values remain null."""
    before_lines = [LineString(r['coordinates']) for r in before]
    tree = STRtree(before_lines)
    diff = []
    covered: dict[int, list] = {}
    for row in after:
        line = LineString(row['coordinates'])
        matches = []
        for j in tree.query(line.buffer(epsilon)):
            other = before_lines[int(j)]
            overlap = line.intersection(other).length
            if overlap > epsilon:
                matches.append((int(j), overlap)); covered.setdefault(int(j), []).append(line.intersection(other))
        length = sum(w for _, w in matches)
        # Entire after segment must have baseline support. Partial geometry is not a like-for-like delta.
        baseline = {k: sum(before[j][k]*w for j, w in matches)/length for k in ('nain', 'nach')} if length > 0 and length >= line.length-epsilon else None
        diff.append({**row, 'before': baseline, 'after': {k: row[k] for k in ('nain','nach')},
                     'delta': {k: row[k]-baseline[k] for k in ('nain','nach')} if baseline else None,
                     'comparison_status': 'MATCHED_GEOMETRY' if baseline else 'NEW_OR_CHANGED_GEOMETRY'})
    for i, row in enumerate(before):
        remainder = before_lines[i].difference(unary_union(covered.get(i, [])))
        for part in _parts(remainder):
            if part.length > epsilon:
                diff.append({**row, 'id': row['id']+':removed:'+str(len(diff)), 'coordinates': list(part.coords), 'before': {k: row[k] for k in ('nain','nach')}, 'after': None, 'delta': None, 'comparison_status': 'REMOVED'})
    return diff


def compare_syntax(features, roads, site, mode: Mode, *, adapter=None, parameters=None, unlinks=()):
    parameters = parameters or MergeParameters()
    buffer, radius = MODES[mode]
    started = time.perf_counter()
    merge = merge_network(features, roads, site, mode, parameters, unlinks)
    common = {'schema_version': 'scenario-syntax-v1', 'implementation_sha256': IMPLEMENTATION_SHA256, 'status': merge['status'], 'mode': mode, 'radius_m': radius,
              'extract_buffer_m': buffer, 'engine': 'PST 3.3.1', 'formula_version': 'pstalgo-3.3.1-walking-radius-v1',
              'evidence_level': 'EXPLORATORY', 'formal_result_eligible': False, 'parameters': parameters.model_dump(),
              'road_input_sha256': digest([r.model_dump() for r in roads]), 'site_sha256': digest(mapping(site)),
              'network_input_sha256': digest(features), 'unlinks_sha256': digest(unlinks),
              'merge': {k:v for k,v in merge.items() if k != 'features'},
              'limitations': ['OSM completeness, access semantics and undirected movement are not established.',
                              'ASSUMED_COMMANDER legacy road modes are not design facts; role-only legacy roads cannot identify collectors, so default to pedestrian+bicycle without width inference.',
                              'High means High or Very High (> baseline context q60); unweighted segment means are sensitive to segmentation.',
                              f'{radius:g} m walking radius on {buffer} m extract; context farther than {buffer-radius:g} m from site has boundary-effect risk.',
                              'Syntax indicates configurational potential, not observed movement or gathering.']}
    if merge['status'] == 'BLOCKED':
        return {**common, 'error': merge['reason'], 'before': None, 'after': None, 'diff': [], 'runtime_seconds': time.perf_counter()-started}
    adapter = adapter or PSTAdapter(manifest_path=DEFAULT_PST_MANIFEST)
    before_start = time.perf_counter()
    before = _compute(features, adapter, radius, unlinks, site)
    before_seconds = time.perf_counter()-before_start
    after_start = time.perf_counter()
    reused = mode == 'motor_vehicle' and merge['unchanged']
    after_unlinks = tuple(sorted(set(tuple(p) for p in unlinks) | set(merge['derived_unlinks'])))
    after = before if reused else _compute(merge['features'], adapter, radius, after_unlinks, site)
    after_seconds = time.perf_counter()-after_start
    breaks = {key: _breaks(before, key) for key in ('nain','nach')}
    for rows in (before, after):
        for r in rows:
            r['boundary_effect_risk'] = r['distance_to_site_m'] > buffer-radius
    threshold = breaks['nain'][3]
    return {**common, 'status': 'COMPUTED', 'reuse_status': 'REUSED_UNCHANGED_MOTOR_NETWORK' if reused else None,
            'before': {'segments': before, 'metrics': _metrics(before, threshold)},
            'after': {'segments': after, 'metrics': _metrics(after, threshold)},
            'diff': segment_diff(before, after), 'legend_breaks': breaks,
            'before_seconds': before_seconds, 'after_seconds': after_seconds, 'runtime_seconds': time.perf_counter()-started}


def verified_extract(mode: Mode, root=EXTRACTION_ROOT):
    buffer, _ = MODES[mode]
    path = root / f'extraction-manifest_{mode}_{buffer}m.json'
    manifest = json.loads(path.read_bytes())
    if manifest['extraction']['buffer_radius_m'] != buffer or manifest['extraction']['network_mode'] != mode:
        raise ValueError('BLOCKED: extraction mode/range mismatch')
    docs = {}
    for key, record in [('network',manifest['outputs']['network']), ('unlinks',manifest['outputs']['unlinks']), ('study_area',manifest['inputs']['study_area'])]:
        raw = Path(record['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256'].removeprefix('sha256:'):
            raise ValueError('BLOCKED: extraction input hash mismatch: '+key)
        docs[key] = json.loads(raw)
    if docs['network'].get('crs',{}).get('properties',{}).get('name') != 'EPSG:28992':
        raise ValueError('BLOCKED: extraction CRS mismatch')
    return docs, {'manifest': manifest, 'manifest_sha256': 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),
                  'pst_runtime_manifest_sha256': 'sha256:'+hashlib.sha256(DEFAULT_PST_MANIFEST.read_bytes()).hexdigest()}
