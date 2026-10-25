"""Deterministic, memory-only R-PROPOSE assembly and validation."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import re
from statistics import median
from jsonschema import Draft202012Validator
from shapely.geometry import LineString, shape, box
from shapely.ops import unary_union
from urban_design.scenario_editing_api import _building_from_payload, _building_payload
from urban_design.editing.commands import _apply_command, AddFloorCommand, RemoveFloorCommand, MoveCommand, PushSideCommand
from urban_design.editing.faces import FaceEditHistory, _building as check_stack

SCHEMA_PATH = Path(__file__).resolve().parents[3] / 'knowledge/judgement/proposal.schema.json'
GFA_FLOOR_M2 = 124842
GEOMETRY_OPS = {'REMOVE_TOP_FLOOR', 'ADD_FLOOR', 'SETBACK_UPPER', 'MOVE'}
STRATEGY_OPS = {'SOLAR_ENVELOPE', 'COURTYARD_WING_DEPTH'}
BANNED = ('已核准', '批准', '正式接受', '最佳', '保證改善', '決策成立', 'HumanDecision', 'Jack', '簽署')
ENGLISH_BANNED = re.compile(r'\b(?:approved|approval|formally\s+accepted|best|guarantee(?:d|s)?\s+improvement|guarantee(?:d|s)?\s+to\s+improve)\b', re.IGNORECASE)
SOLAR_LATITUDE_DEG = 51.9
WINTER_DECLINATION_DEG = -23.44
FIRST_FLOOR_HEIGHT_M = 4.0
STANDARD_FLOOR_HEIGHT_M = 3.5


def _noon_sun_altitude_deg(latitude_deg, declination_deg):
    latitude = math.radians(float(latitude_deg))
    declination = math.radians(float(declination_deg))
    sine = math.sin(latitude) * math.sin(declination) + math.cos(latitude) * math.cos(declination)
    return round(math.degrees(math.asin(max(-1.0, min(1.0, sine)))), 2)


def _as_feature_properties(value):
    if value.get('type') == 'Feature':
        return {**value, **value.get('properties', {})}
    return value


def _building_height(building):
    building = _as_feature_properties(building)
    height = building.get('height_m')
    if isinstance(height, (int, float)) and math.isfinite(height):
        return float(height)
    try:
        mass = _building_from_payload(building)
    except (ValueError, KeyError, TypeError):
        return None
    return mass.first_floor_height_m + (len(mass.floors) - 1) * mass.standard_floor_height_m


def _building_floor_count(building, height_m):
    building = _as_feature_properties(building)
    floors = building.get('floors')
    if isinstance(floors, list):
        return len(floors)
    if isinstance(floors, int) and not isinstance(floors, bool):
        return floors
    if height_m is None:
        return None
    return max(1, round((height_m - FIRST_FLOOR_HEIGHT_M) / STANDARD_FLOOR_HEIGHT_M) + 1)


def courtyard_solar_geometry(courtyard, buildings, latitude_deg=SOLAR_LATITUDE_DEG, *, winter_mean_h=None):
    """Return a deterministic winter-noon shadow-height screen for one courtyard."""
    court = _as_feature_properties(courtyard)
    winter_altitude = _noon_sun_altitude_deg(latitude_deg, WINTER_DECLINATION_DEG)
    equinox_altitude = _noon_sun_altitude_deg(latitude_deg, 0.0)
    depth = None
    basis = 'N-S scanline median'
    geometry_payload = court.get('geometry')
    if geometry_payload:
        try:
            geometry = shape(geometry_payload)
            if not geometry.is_empty:
                minx, miny, maxx, maxy = geometry.bounds
                x = minx + 0.5
                lengths = []
                while x < maxx:
                    line = LineString([(x, miny - 1.0), (x, maxy + 1.0)])
                    length = geometry.intersection(line).length
                    if length > 0:
                        lengths.append(length)
                    x += 1.0
                if lengths:
                    depth = float(median(lengths))
                else:
                    depth = float(geometry.intersection(
                        LineString([(geometry.centroid.x, miny - 1.0), (geometry.centroid.x, maxy + 1.0)])).length)
        except (TypeError, ValueError, KeyError):
            depth = None
    if depth is None:
        basis = 'clear_width_m (approx.)'
        clear_width = court.get('clear_width_m')
        depth = float(clear_width) if isinstance(clear_width, (int, float)) and math.isfinite(clear_width) else None

    by_id = {}
    for building in buildings:
        normalized = _as_feature_properties(building)
        ident = normalized.get('building_id', normalized.get('id'))
        if ident:
            by_id[str(ident)] = normalized
    heights = []
    floor_counts = []
    for ident in court.get('south_building_ids', []):
        building = by_id.get(str(ident))
        if not building:
            continue
        height = _building_height(building)
        if height is None:
            continue
        heights.append(height)
        floor_counts.append(_building_floor_count(building, height))
    south_max = max(heights) if heights else None
    south_median = median(heights) if heights else None

    north_edge = depth * math.tan(math.radians(winter_altitude)) if depth is not None else None
    half = depth / 2.0 * math.tan(math.radians(winter_altitude)) if depth is not None else None
    equinox_north = depth * math.tan(math.radians(equinox_altitude)) if depth is not None else None
    floors_to_remove = None
    if heights and north_edge is not None:
        required = []
        possible = True
        for height, floor_count in zip(heights, floor_counts):
            if height <= north_edge + 1e-9:
                required.append(0)
                continue
            if north_edge < FIRST_FLOOR_HEIGHT_M - 1e-9 or floor_count is None:
                possible = False
                break
            remove = max(0, math.ceil((height - north_edge - 1e-9) / STANDARD_FLOOR_HEIGHT_M))
            if remove > floor_count - 1:
                possible = False
                break
            required.append(remove)
        if possible and required:
            floors_to_remove = max(required)

    result = {
        'winter_noon_sun_altitude_deg': winter_altitude,
        'equinox_noon_sun_altitude_deg': equinox_altitude,
        'depth_along_sun_m': round(depth, 2) if depth is not None else None,
        'depth_basis': basis,
        'south_edge_height_max_m': round(south_max, 2) if south_max is not None else None,
        'south_edge_height_median_m': round(south_median, 2) if south_median is not None else None,
        'h_north_edge_m': round(north_edge, 2) if north_edge is not None else None,
        'h_half_m': round(half, 2) if half is not None else None,
        'h_north_edge_equinox_m': round(equinox_north, 2) if equinox_north is not None else None,
        'floors_to_remove_for_north_edge': floors_to_remove,
        'feasible_within_catalogue': floors_to_remove is not None and floors_to_remove <= 2,
        'winter_mean_h': winter_mean_h,
    }
    return result


def _courtyard_sunlight_map(courtyard_sunlight):
    if isinstance(courtyard_sunlight, dict):
        return courtyard_sunlight
    result = {}
    for item in courtyard_sunlight or []:
        if item.get('fabric_id') in (None, 'harbour_grain') and item.get('courtyard_id'):
            normalized = dict(item)
            normalized.setdefault('winter_mean_h', item.get('winter_mean'))
            result[str(item['courtyard_id'])] = normalized
    return result


def proposal_model_input(bundle):
    """Project the stored input bundle into the bounded, geometry-free model contract."""
    top_level = ('card_id', 'round', 'card', 'responses', 'subject', 'draft_revision',
                 'editable_buildings', 'courtyards', 'constraints', 'operation_catalog',
                 'designer_stances', 'sources', 'solar_reference', 'data_gaps')
    building_fields = ('building_id', 'block_id', 'floors', 'height_m', 'gfa_m2',
                       'footprint_area_m2', 'centroid')
    courtyard_fields = ('courtyard_id', 'id', 'block_id', 'clear_width_m', 'area_m2',
                        'south_building_ids', 'north_building_ids', 'sun_side_building_ids',
                        'south_edge_facing_azimuth_deg', 'edges', 'solar_geometry')
    projected = {key: deepcopy(bundle[key]) for key in top_level if key in bundle}
    projected['editable_buildings'] = []
    for building in bundle.get('editable_buildings', []):
        item = {key: deepcopy(building[key]) for key in building_fields if key in building and key != 'floors'}
        floors = building.get('floors')
        if isinstance(floors, list):
            item['floors'] = len(floors)
        elif floors is not None:
            item['floors'] = deepcopy(floors)
        projected['editable_buildings'].append(item)
    projected['courtyards'] = [
        {key: deepcopy(courtyard[key]) for key in courtyard_fields if key in courtyard}
        for courtyard in bundle.get('courtyards', [])
    ]
    return projected


def courtyard_relationships(courtyards, buildings, *, courtyard_sunlight=None, latitude_deg=SOLAR_LATITUDE_DEG):
    """Edge-based courtyard adjacency in projected metres (EPSG:28992, +y = north).

    Courtyards follow the rotated block axis, so "south of the centroid" is meaningless. Each
    building within 12 m of the courtyard (same block) is assigned to its nearest edge of the
    courtyard's minimum rotated rectangle; each edge carries its outward-facing azimuth.
    ``south_building_ids`` = buildings on the most south-facing edge; ``sun_side_building_ids``
    = buildings on any edge facing within 60° of due south (the winter-shading side).
    """
    result = []
    sunlight = _courtyard_sunlight_map(courtyard_sunlight)
    buildings = [{**b, **b.get('properties', {})} if b.get('type') == 'Feature' else b for b in buildings]
    for court in courtyards:
        if court.get('type') == 'Feature': court = {**court, **court.get('properties', {})}
        geometry = shape(court['geometry'])
        centre = geometry.centroid
        rect = geometry.minimum_rotated_rectangle
        corners = list(rect.exterior.coords)[:4]
        edges = []
        for a, b in zip(corners, corners[1:] + corners[:1]):
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            nx, ny = b[1] - a[1], -(b[0] - a[0])
            if nx * (mx - centre.x) + ny * (my - centre.y) < 0:
                nx, ny = -nx, -ny
            length = math.hypot(nx, ny) or 1.0
            nx, ny = nx / length, ny / length
            azimuth = (math.degrees(math.atan2(nx, ny)) + 360.0) % 360.0
            edges.append({'line': LineString([a, b]), 'facing_azimuth_deg': round(azimuth, 1), 'south_component': -ny, 'building_ids': []})
        item = {k: deepcopy(v) for k, v in court.items() if k != 'geometry'}
        item.setdefault('courtyard_id', court.get('id'))
        item.setdefault('area_m2', geometry.area)
        item.setdefault('clear_width_m', min(geometry.bounds[2]-geometry.bounds[0], geometry.bounds[3]-geometry.bounds[1]))
        for building in buildings:
            if building.get('block_id') != court.get('block_id'):
                continue
            footprint = shape(building['geometry']) if building.get('geometry') else unary_union([shape(f['geometry']) for f in building['floors']])
            if footprint.distance(geometry.exterior) > 12:
                continue
            # Which edge a building faces = the edge nearest its centroid (footprint distance ties at corners).
            nearest = min(edges, key=lambda edge: footprint.centroid.distance(edge['line']))
            nearest['building_ids'].append(building.get('building_id', building.get('id')))
        for edge in edges:
            edge['building_ids'].sort()
        south_edge = max(edges, key=lambda edge: edge['south_component'])
        item['south_building_ids'] = list(south_edge['building_ids'])
        item['south_edge_facing_azimuth_deg'] = south_edge['facing_azimuth_deg']
        item['sun_side_building_ids'] = sorted({bid for edge in edges if edge['south_component'] >= math.cos(math.radians(60)) for bid in edge['building_ids']})
        item['edges'] = [{'facing_azimuth_deg': edge['facing_azimuth_deg'], 'building_ids': edge['building_ids']} for edge in edges]
        opposite = min(edges, key=lambda edge: edge['south_component'])
        item['north_building_ids'] = list(opposite['building_ids'])
        sunlight_row = sunlight.get(str(item['courtyard_id']), {})
        solar_courtyard = {**court, 'south_building_ids': item['south_building_ids']}
        item['solar_geometry'] = courtyard_solar_geometry(
            solar_courtyard, buildings, latitude_deg,
            winter_mean_h=sunlight_row.get('winter_mean_h') if sunlight_row else None,
        )
        result.append(item)
    return result


def assemble_proposal_inputs(card_run, draft, responses=None, *, courtyards=None, buildings_metadata=None,
                             courtyard_sunlight=None, latitude_deg=SOLAR_LATITUDE_DEG, data_gaps=None):
    if card_run.get('status') != 'VALIDATED':
        raise ValueError('VALIDATED judgement card required')
    parameters = draft.get('parameters', draft)
    # Courtyard expansions belong to the draft revision, never to the frozen plan.
    overrides = parameters.get('proposal_courtyard_overrides', {})
    courtyards = [deepcopy(raw) for raw in courtyards or []]
    for court in courtyards:
        normalized = _as_feature_properties(court)
        ident = normalized.get('courtyard_id', normalized.get('id'))
        if ident in overrides:
            override = overrides[ident]
            court['geometry'] = deepcopy(override['geometry'])
            properties = court.get('properties', court)
            for key in ('clear_width_m', 'area_m2'):
                if key in override:
                    properties[key] = override[key]
    buildings = deepcopy(parameters.get('editable_buildings', []))
    if not buildings or any(b.get('provenance') != 'FORMAL_DRAFT' for b in buildings):
        raise ValueError('formal draft editable_buildings required')
    active = parameters.get('active_buildings') or {}
    if isinstance(active, list): active = {b['building_id']: b for b in active}
    buildings = [{**b, **deepcopy(active.get(b['building_id'], {}))} for b in buildings]
    metadata = {str(b.get('building_id', b.get('id'))): {**b, **b.get('properties', {})} for b in buildings_metadata or []}
    preserved = deepcopy(parameters.get('preserved_buildings', []))
    preserved.extend({'building_id':ident, 'geometry':item['geometry']} for ident,item in metadata.items() if item.get('retained') and item.get('geometry'))
    buildings = [b for b in buildings if not b.get('retained') and not metadata.get(b['building_id'], {}).get('retained')]
    summaries = []
    for b in buildings:
        b.setdefault('block_id', metadata.get(b['building_id'], {}).get('block_id'))
        mass = _building_from_payload(b)
        footprint = unary_union([f.geometry for f in mass.floors])
        summaries.append({'building_id':mass.id, 'block_id':b.get('block_id'), 'floors':len(mass.floors), 'height_m':mass.first_floor_height_m+(len(mass.floors)-1)*mass.standard_floor_height_m, 'gfa_m2':sum(f.geometry.area for f in mass.floors), 'footprint_area_m2':footprint.area, 'centroid':[footprint.centroid.x, footprint.centroid.y]})
    for summary in summaries:
        raw = next(b for b in buildings if b['building_id']==summary['building_id'])
        meta = metadata.get(summary['building_id'], {})
        for key in ('is_main_street', 'fronts_main_street', 'north_side_is_street'):
            if key in raw or key in meta: summary[key] = raw.get(key, meta.get(key))
    draft_copy = deepcopy(draft)
    if 'parameters' in draft_copy:
        draft_copy['parameters']['editable_buildings'] = buildings
        draft_copy['parameters']['preserved_buildings'] = preserved
    else:
        draft_copy['editable_buildings'] = buildings
        draft_copy['preserved_buildings'] = preserved
    winter_altitude = _noon_sun_altitude_deg(latitude_deg, WINTER_DECLINATION_DEG)
    equinox_altitude = _noon_sun_altitude_deg(latitude_deg, 0.0)
    return {
        'card_id': card_run.get('id', card_run.get('card_id')),
        'round': card_run.get('round'),
        'card': deepcopy(card_run.get('card', card_run)),
        'responses': deepcopy(responses if responses is not None else card_run.get('responses', [])),
        'draft': draft_copy,
        'draft_revision': draft.get('revision', parameters.get('draft_revision', parameters.get('revision'))),
        'editable_buildings': summaries,
        'courtyards': [{**c, 'geometry': next((_as_feature_properties(raw).get('geometry') for raw in courtyards or [] if _as_feature_properties(raw).get('courtyard_id', raw.get('id')) == c['courtyard_id']), None)} for c in courtyard_relationships(courtyards or [], buildings, courtyard_sunlight=courtyard_sunlight, latitude_deg=latitude_deg)],
        'solar_reference': {
            'latitude_deg': latitude_deg,
            'winter_noon_sun_altitude_deg': winter_altitude,
            'equinox_noon_sun_altitude_deg': equinox_altitude,
            'first_floor_height_m': FIRST_FLOOR_HEIGHT_M,
            'standard_floor_height_m': STANDARD_FLOOR_HEIGHT_M,
        },
        'data_gaps': sorted(set(data_gaps or [])),
        'constraints': {'height_cap_m': 20, 'gfa_floor_m2': GFA_FLOOR_M2,
                        'gfa_floor_status': 'ASSUMED', 'gfa_floor_fraction': 0.85,
                        'current_gfa_m2': sum(b['gfa_m2'] for b in summaries)},
        'operation_catalog': sorted(GEOMETRY_OPS | STRATEGY_OPS | {'PLANTING_NOTE', 'RERUN'}),
    }


def validate_proposal(proposal, bundle):
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = [f'schema: {e.message}' for e in Draft202012Validator(schema).iter_errors(proposal)]
    if errors:
        return errors
    serialized = json.dumps(proposal,ensure_ascii=False)
    if any(word.casefold() in serialized.casefold() for word in BANNED) or ENGLISH_BANNED.search(serialized):
        errors.append('forbidden language')
    if proposal['responds_to']['card_id'] != bundle['card_id']:
        errors.append('responds_to card mismatch')
    response_ids = {r['id'] for r in bundle['responses']}
    if not set(proposal['responds_to']['response_ids']) <= response_ids:
        errors.append('unknown response id')
    sources = [bundle['card'], *bundle['responses']]
    ids = {bundle['card_id'], *response_ids}
    def collect(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k == 'id' and isinstance(v,str): ids.add(v)
                collect(v)
        elif isinstance(value,list):
            for v in value: collect(v)
    collect(sources)
    source_texts = []
    def strings(value):
        if isinstance(value, str): source_texts.append(value)
        elif isinstance(value, dict):
            for v in value.values(): strings(v)
        elif isinstance(value, list):
            for v in value: strings(v)
    strings(sources)
    for reason in proposal['rationale']:
        if not any(i and re.search(r'(?<![\w-])'+re.escape(i)+r'(?![\w-])',reason) for i in ids) and not any(reason[i:i+8].strip() and len(reason[i:i+8].strip()) == 8 and any(reason[i:i+8] in text for text in source_texts) for i in range(max(0,len(reason)-7))):
            errors.append('rationale lacks actual id or source excerpt of at least 8 characters')
    ops = proposal['operations']
    if sum(o['op'] in GEOMETRY_OPS for o in ops)>3: errors.append('maximum 3 geometry groups')
    if not any(o['op']=='RERUN' for o in ops): errors.append('RERUN required')
    ids = set()
    known = {b['building_id'] for b in bundle['editable_buildings']}
    for op in ops:
        affected = op.get('building_ids', [op['building_id']] if 'building_id' in op else [])
        ids.update(affected)
        if not set(affected) <= known: errors.append('unknown or preserved building')
        if op['op']=='PLANTING_NOTE':
            targets = {c['courtyard_id'] for c in bundle['courtyards']} | {'open-space','open_space','courtyard','street','park','plaza','green_space','public_open_space'}
            if op['target'] not in targets: errors.append('unknown planting target')
            if not proposal['not_simulated']: errors.append('planting must be marked not simulated')
    strategies = [o for o in ops if o['op'] in STRATEGY_OPS]
    if strategies:
        if len(strategies) > 2: errors.append('maximum 2 strategy groups')
        if sum(o['op'] in GEOMETRY_OPS for o in ops) > 1: errors.append('maximum 1 per-building geometry group with strategies')
        if not any(o['op']=='RERUN' and 'E1' in o['analyses'] for o in ops): errors.append('strategy RERUN requires E1')
        if any(o['op']=='SOLAR_ENVELOPE' for o in strategies):
            all_south = {bid for c in bundle['courtyards'] for bid in c.get('south_building_ids', [])}
            if any(o['op']=='ADD_FLOOR' and all_south.intersection(o['building_ids']) for o in ops):
                errors.append('solar redistribution cannot add floors on any courtyard south side')
            trade_text=' '.join(proposal['trade_offs'])
            if any(field not in trade_text for field in ('removed_gfa_m2','added_gfa_m2','gfa_shortfall_m2')):
                errors.append('solar trade_offs must reference removed_gfa_m2, added_gfa_m2, gfa_shortfall_m2')
        courts = {c['courtyard_id']: c for c in bundle['courtyards']}
        for op in strategies:
            targets = op.get('courtyard_ids', [op.get('courtyard_id')])
            for target in targets:
                court = courts.get(target)
                if not court: errors.append('unknown courtyard'); continue
                solar = court.get('solar_geometry') or {}
                if op['op']=='SOLAR_ENVELOPE':
                    key = 'h_north_edge_m' if op['target']=='north_edge' else 'h_half_m'
                    if not isinstance(solar.get(key), (int,float)) or isinstance(solar.get(key),bool) or not math.isfinite(solar[key]): errors.append('courtyard solar_geometry required')
                    if not court.get('south_building_ids'): errors.append('courtyard south side has no buildings')
                    if not set(court.get('south_building_ids', [])) <= known: errors.append('unknown or preserved building')
                elif not _side_ids(court, op['side']): errors.append('courtyard side has no buildings')
                elif not set(_side_ids(court, op['side'])) <= known: errors.append('unknown or preserved building')
    elif len(ids)>24: errors.append('maximum 24 affected buildings')
    identifiers = sorted({*known, *(c['courtyard_id'] for c in bundle['courtyards']), bundle['card_id'], *response_ids, 'E1', 'E2', 'E3', 'E4', 'E5'}, key=len, reverse=True)
    def without_identifiers(text):
        for ident in identifiers:
            if ident: text = re.sub(r'(?<![\w-])'+re.escape(ident)+r'(?![\w-])', ' ', text)
        return re.sub(r'(?<![\w-])[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+', ' ', text)
    if any(re.search(r'\d',without_identifiers(v)) for v in proposal['expected_effects']): errors.append('expected_effects must be qualitative')
    return errors


def _proposal_claims_courtyard_winter_sun(proposal):
    parts = [proposal.get('summary', '')]
    for key in ('rationale', 'expected_effects'):
        value = proposal.get(key, [])
        parts.extend(value if isinstance(value, list) else [value])
    text = ' '.join(item for item in parts if isinstance(item, str)).casefold()
    winter_courtyard_claim = '中庭' in text and '冬' in text
    e1_courtyard_metric = 'e1.' in text and 'courtyard' in text
    return winter_courtyard_claim or e1_courtyard_metric


def _solar_access_check(proposal, bundle, output_buildings, affected_ids):
    claims = _proposal_claims_courtyard_winter_sun(proposal)
    by_id = {str(item.get('building_id', item.get('id'))): item for item in output_buildings}
    checks = []
    for courtyard in bundle.get('courtyards', []):
        south_ids = {str(ident) for ident in courtyard.get('south_building_ids', [])}
        strategy_courts = {cid for op in proposal.get('operations', []) if op.get('op') in STRATEGY_OPS for cid in op.get('courtyard_ids', [op.get('courtyard_id')])}
        if not south_ids.intersection(affected_ids) and courtyard.get('courtyard_id') not in strategy_courts:
            continue
        # Recompute from the edited floor stack; a carried-over height_m would be the pre-edit value.
        heights = [_building_height({k: v for k, v in by_id[ident].items() if k != 'height_m'}) for ident in south_ids if ident in by_id]
        heights = [height for height in heights if height is not None]
        south_height = max(heights) if heights else None
        solar = courtyard.get('solar_geometry') or {}
        north_edge = solar.get('h_north_edge_m')
        reaches = (south_height is not None and isinstance(north_edge, (int, float))
                   and south_height <= north_edge + 1e-9)
        pockets = []
        for ident in sorted(south_ids.intersection(affected_ids)):
            building = by_id.get(ident)
            if not building:
                continue
            height = _building_height({k: v for k, v in building.items() if k != 'height_m'})
            if height is None or not isinstance(north_edge, (int, float)) or height > north_edge + 1e-9:
                continue
            frontage = None
            basis = None
            floors = building.get('floors') or []
            if floors and isinstance(floors[0], dict) and floors[0].get('geometry'):
                footprint = shape(floors[0]['geometry'])
                azimuth = courtyard.get('south_edge_facing_azimuth_deg')
                if isinstance(azimuth, (int, float)):
                    # Frontage = extent along the courtyard edge (perpendicular to the edge's facing azimuth;
                    # compass degrees, +x east, +y north). Row units here are 6.705 m wide and 13 m deep.
                    a = math.radians(azimuth)
                    ux, uy = math.cos(a), -math.sin(a)
                    projections = [x * ux + y * uy for x, y in footprint.exterior.coords]
                    frontage = round(max(projections) - min(projections), 1)
                    basis = 'extent along courtyard south edge'
                else:
                    rectangle = footprint.minimum_rotated_rectangle
                    corners = list(rectangle.exterior.coords)[:4]
                    frontage = round(min(math.dist(corners[i], corners[(i + 1) % 4]) for i in range(4)), 1)
                    basis = 'short side of minimum rotated rectangle (edge azimuth unavailable)'
            pockets.append({'building_id': ident, 'height_after_m': round(height, 2), 'frontage_m': frontage,
                            'frontage_basis': basis})
        checks.append({
            'courtyard_id': courtyard.get('courtyard_id'),
            'south_height_after_m': round(south_height, 2) if south_height is not None else None,
            'h_north_edge_m': north_edge,
            'reaches_north_edge': bool(reaches),
            'local_sun_pockets': pockets,
        })
    courtyard_wide = any(item['reaches_north_edge'] for item in checks)
    local_only = bool(not courtyard_wide and any(item['local_sun_pockets'] for item in checks))
    warning = bool(claims and checks and not courtyard_wide)
    return {'courtyards': checks, 'claims_courtyard_winter_sun': claims, 'warning': warning, 'local_only': local_only}


def dry_run_proposal(proposal,bundle):
    errors = validate_proposal(proposal,bundle)
    parameters = bundle['draft'].get('parameters',bundle['draft'])
    original = deepcopy(parameters['editable_buildings'])
    before = sum(shape(f['geometry']).area for b in original for f in b['floors'])
    result = {'valid':False,'errors':errors,'editable_buildings':original,'gfa_before_m2':before,'gfa_after_m2':before,'gfa_floor_m2':GFA_FLOOR_M2,'below_gfa_floor':before<GFA_FLOOR_M2,'requires_designer_gfa_decision':before<GFA_FLOOR_M2,
              'solar_access_check': {'courtyards': [], 'claims_courtyard_winter_sun': False, 'warning': False, 'local_only': False}}
    result['limitations'] = []
    if not (parameters.get('design_area') or parameters.get('design_area_geometry')): result['limitations'].append('Design-area containment not assessed: geometry unavailable.')
    if not parameters.get('preserved_buildings'): result['limitations'].append('Retained-building overlap not assessed: geometry unavailable.')
    result['limitations'].append('Nested floor-stack topology checked; no independent 3D shell/manifold verification.')
    if errors: return result
    buildings = {b['building_id']:_building_from_payload(b) for b in original}
    affected = set()
    try:
        strategy_reports = []
        working_bundle = deepcopy(bundle)
        for index,op in enumerate(proposal['operations']):
            if op['op'] in STRATEGY_OPS:
                report, changed = _apply_strategy(op, buildings, working_bundle, index)
                strategy_reports.append(report)
                affected.update(changed)
                if len(affected) > 80: raise ValueError('maximum 80 affected buildings after strategy expansion')
                continue
            if op['op'] not in GEOMETRY_OPS: continue
            for ident in op.get('building_ids',[op.get('building_id')]):
                affected.add(ident)
                b = buildings[ident]
                if op['op'] == 'SETBACK_UPPER':
                    history = FaceEditHistory(replace(b,provenance='FIXTURE_ONLY'))
                    b = replace(history.setback_upper_two(expected_revision=0,metres=op['metres']).building,provenance='FORMAL_DRAFT')
                elif op['op'] == 'MOVE':
                    b = _apply_command(b,MoveCommand(op['dx_m'],op['dy_m']))
                else:
                    for step in range(op['floors']):
                        command = AddFloorCommand(f'{ident}-proposal-{index}-{step}-{len(b.floors)}') if op['op']=='ADD_FLOOR' else RemoveFloorCommand(max(b.floors,key=lambda f:f.level).id)
                        b = _apply_command(b,command)
                check_stack(replace(b,provenance='FIXTURE_ONLY'))
                if b.first_floor_height_m+(len(b.floors)-1)*b.standard_floor_height_m > 20+1e-9: raise ValueError('height exceeds 20 m')
                buildings[ident] = b
        if len(affected) > (80 if strategy_reports else 24): raise ValueError('affected building limit exceeded')
        # All stacks are checked, including preserved baseline massing in the editable set.
        for b in buildings.values():
            check_stack(replace(b,provenance='FIXTURE_ONLY'))
            if b.first_floor_height_m+(len(b.floors)-1)*b.standard_floor_height_m > 20+1e-9: raise ValueError('height exceeds 20 m')
        area_payload = parameters.get('design_area') or parameters.get('design_area_geometry')
        if area_payload:
            area = shape(area_payload)
            for ident in affected:
                if any(not area.covers(f.geometry) for f in buildings[ident].floors): raise ValueError('outside design area')
        for preserved in parameters.get('preserved_buildings', []):
            geometry = preserved.get('geometry')
            geometries = [shape(geometry)] if geometry else [shape(f['geometry']) for f in preserved.get('floors',[])]
            for ident in affected:
                if any(f.geometry.intersection(g).area > 1e-7 for f in buildings[ident].floors for g in geometries): raise ValueError('preserved building overlap')
        all_buildings=list(buildings.values())
        for i,b in enumerate(all_buildings):
            for other in all_buildings[i+1:]:
                if not ({b.id,other.id} & affected): continue
                if any(f.geometry.intersection(g.geometry).area > 1e-7 for f in b.floors for g in other.floors): raise ValueError('building overlap')
        after = sum(f.geometry.area for b in buildings.values() for f in b.floors)
        output = []
        for source in original:
            output.append({**source,**_building_payload(buildings[source['building_id']],source.get('use_label','UNASSIGNED'))})
        for report in strategy_reports:
            report['solar_access_check'] = _solar_access_check({'operations':[proposal['operations'][report['operation_index']]]}, working_bundle, output, affected)
            report['envelope_success'] = bool(report['solar_access_check']['courtyards']) and all(c['reaches_north_edge'] for c in report['solar_access_check']['courtyards']) if report['op']=='SOLAR_ENVELOPE' else None
        trade_text=' '.join(proposal['trade_offs'])
        result['strategy_trade_off_check'] = {
            'north_street_shadow_addressed': not any(r['added_buildings'] for r in strategy_reports) or (('北' in trade_text and ('陰影' in trade_text or '日照' in trade_text)) or ('north' in trade_text.lower() and ('shadow' in trade_text.lower() or 'sun' in trade_text.lower()))),
            'gfa_floor_relationship_addressed': not any(r['gfa_shortfall_m2']>1e-7 for r in strategy_reports) or ('85%' in trade_text or '85％' in trade_text or '下限' in trade_text or 'floor' in trade_text.lower()),
        }
        changed_courts = {op['courtyard_id'] for op in proposal['operations'] if op['op'] == 'COURTYARD_WING_DEPTH'}
        courtyard_overrides = deepcopy(parameters.get('proposal_courtyard_overrides', {}))
        for court in working_bundle['courtyards']:
            if court['courtyard_id'] in changed_courts:
                geometry = shape(court['geometry'])
                courtyard_overrides[court['courtyard_id']] = {
                    'geometry': deepcopy(court['geometry']), 'area_m2': geometry.area,
                    'clear_width_m': court.get('clear_width_m')}
        result['courtyard_geometry_overrides'] = courtyard_overrides
        result.update(valid=True,editable_buildings=output,gfa_after_m2=after,below_gfa_floor=after<GFA_FLOOR_M2,requires_designer_gfa_decision=after<GFA_FLOOR_M2,affected_building_ids=sorted(affected),topology_status='NESTED_FLOOR_STACK_VALIDATED',
                      strategy_report=strategy_reports, solar_access_check=_solar_access_check(proposal, working_bundle, output, affected))
    except (ValueError,KeyError,TypeError) as exc:
        errors.append(str(exc))
    return result


def _side_ids(court, side):
    if side in ('south', 'north'):
        return court.get(side + '_building_ids', [])
    if side + '_building_ids' in court:
        return court[side + '_building_ids']
    target = 90 if side == 'east' else 270
    edges = court.get('edges', [])
    if not edges: return []
    return min(edges, key=lambda e: abs((e['facing_azimuth_deg']-target+180)%360-180))['building_ids']


def _height(mass):
    return mass.first_floor_height_m + (len(mass.floors)-1)*mass.standard_floor_height_m


def _apply_strategy(op, buildings, bundle, index):
    courts = {c['courtyard_id']: c for c in bundle['courtyards']}
    metadata = {b['building_id']: b for b in bundle['editable_buildings']}
    report = {'op':op['op'], 'operation_index':index, 'removed_buildings':[], 'added_buildings':[],
              'removed_gfa_m2':0.0, 'added_gfa_m2':0.0, 'gfa_shortfall_m2':0.0,
              'envelope_unreachable':[]}
    affected = set()
    if op['op']=='SOLAR_ENVELOPE':
        targets = [courts[cid] for cid in op['courtyard_ids']]
        thresholds = {}
        for court in targets:
            threshold = court['solar_geometry']['h_north_edge_m' if op['target']=='north_edge' else 'h_half_m']
            for ident in court['south_building_ids']:
                thresholds[ident] = min(thresholds.get(ident, math.inf), threshold)
        removed_by_block = {}
        added_by_block = {}
        for ident in sorted(thresholds):
            b = buildings[ident]; removed = 0.; count = 0
            while len(b.floors)>1 and _height(b)>thresholds[ident]+1e-9:
                floor = max(b.floors,key=lambda f:f.level)
                removed += floor.geometry.area; count += 1
                b = _apply_command(b,RemoveFloorCommand(floor.id))
            buildings[ident] = b
            if _height(b)>thresholds[ident]+1e-9: report['envelope_unreachable'].append({'building_id':ident,'status':'ENVELOPE_UNREACHABLE'})
            if count:
                affected.add(ident); report['removed_buildings'].append({'building_id':ident,'floors':count,'gfa_m2':removed})
                report['removed_gfa_m2'] += removed
                block = metadata[ident].get('block_id')
                removed_by_block[block] = removed_by_block.get(block, 0.) + removed
        forbidden = {bid for c in courts.values() for bid in c.get('south_building_ids',[])}
        candidates = []
        for court in targets:
            block = court.get('block_id')
            same = sorted(bid for bid in buildings if metadata.get(bid,{}).get('block_id')==block and bid not in forbidden)
            north = sorted(set(court.get('north_building_ids',[])) & set(same))
            main = [bid for bid in same if metadata[bid].get('is_main_street') or metadata[bid].get('fronts_main_street')]
            candidates.extend(north + [bid for bid in same if bid not in north and bid not in main] + main)
        if op['redistribute']:
            for ident in dict.fromkeys(candidates):
                b = buildings[ident]; added = 0.; count = 0
                while _height(b)+b.standard_floor_height_m <= 20+1e-9:
                    area = max(b.floors,key=lambda f:f.level).geometry.area
                    block = metadata[ident].get('block_id')
                    if added_by_block.get(block, 0.)+area > removed_by_block.get(block, 0.)+1e-7: break
                    b = _apply_command(b, AddFloorCommand(f'{ident}-strategy-{index}-{len(b.floors)}'))
                    added += area; count += 1; report['added_gfa_m2'] += area
                    added_by_block[block] = added_by_block.get(block, 0.)+area
                buildings[ident] = b
                if count:
                    affected.add(ident)
                    report['added_buildings'].append({'building_id':ident,'floors':count,'gfa_m2':added,
                       'is_north_of_courtyard':any(ident in c.get('north_building_ids',[]) for c in targets),
                       'north_side_is_street':metadata[ident].get('north_side_is_street')})
        report['gfa_shortfall_m2'] = max(0.,report['removed_gfa_m2']-report['added_gfa_m2'])
    else:
        court = courts[op['courtyard_id']]
        if not court.get('geometry'): raise ValueError('courtyard geometry required for wing depth')
        courtyard_geom = shape(court['geometry'])
        old_footprints = []; new_footprints = []
        for ident in sorted(_side_ids(court, op['side'])):
            b = buildings[ident]; bottom = min(b.floors,key=lambda f:f.level).geometry
            coords = list(bottom.exterior.coords)[:-1]
            edge_lines = [LineString([a,coords[(i+1)%len(coords)]]) for i,a in enumerate(coords)]
            court_edges = court.get('edges', [])
            side_angle = {'south':180, 'north':0, 'east':90, 'west':270}[op['side']]
            selected = min(court_edges, key=lambda e:abs((e['facing_azimuth_deg']-side_angle+180)%360-180)) if court_edges else None
            angle = math.radians(selected['facing_azimuth_deg'] if selected else side_angle)
            direction = (math.cos(angle), -math.sin(angle))
            def face_rank(i):
                a0,z0=coords[i],coords[(i+1)%len(coords)]; length0=math.dist(a0,z0)
                parallel_error=abs((z0[0]-a0[0])*direction[1]-(z0[1]-a0[1])*direction[0])/length0
                return (round(parallel_error, 6),edge_lines[i].interpolate(0.5, normalized=True).distance(courtyard_geom))
            edge = min(range(len(coords)),key=face_rank)
            a,z=coords[edge],coords[(edge+1)%len(coords)]; length=math.dist(a,z)
            normal=(-(z[1]-a[1])/length,(z[0]-a[0])/length)
            projections=[x*normal[0]+y*normal[1] for x,y in coords]
            depth=max(projections)-min(projections)
            delta=depth-op['depth_m']
            if delta < -1e-6 or abs(delta-round(delta))>1e-6: raise ValueError('wing depth requires integer inward face push')
            steps=int(round(delta))
            targets=[]
            for floor in b.floors:
                fc=list(floor.geometry.exterior.coords)[:-1]
                parallel=[]
                for i,fa in enumerate(fc):
                    fz=fc[(i+1)%len(fc)]; fl=math.dist(fa,fz)
                    if fl and abs((fz[0]-fa[0])*(z[1]-a[1])-(fz[1]-fa[1])*(z[0]-a[0]))/(fl*length)<1e-6:
                        parallel.append((LineString([fa,fz]).interpolate(0.5, normalized=True).distance(courtyard_geom),i))
                if not parallel: raise ValueError('no parallel courtyard-facing floor edge')
                targets.append((floor.id,min(parallel)[1]))
            old_footprints.append(bottom)
            before=sum(f.geometry.area for f in b.floors)
            if steps:
                b=_apply_command(b,PushSideCommand(tuple(targets),-steps,b.geometry_hash()))
                affected.add(ident)
            buildings[ident]=b; new_footprints.append(min(b.floors,key=lambda f:f.level).geometry)
            removed=before-sum(f.geometry.area for f in b.floors)
            report['removed_gfa_m2']+=removed
            report['removed_buildings'].append({'building_id':ident,'gfa_m2':removed,'depth_before_m':depth,'depth_after_m':op['depth_m']})
        from urban_design.editing.validation import push_polygon_side
        cc=list(courtyard_geom.exterior.coords)[:-1]
        original_wing=unary_union(old_footprints)
        court_edge=min(range(len(cc)),key=lambda i:LineString([cc[i],cc[(i+1)%len(cc)]]).interpolate(0.5, normalized=True).distance(original_wing))
        deltas={round(item['depth_before_m']-item['depth_after_m']) for item in report['removed_buildings']}
        if len(deltas)!=1: raise ValueError('wing depths inconsistent along courtyard side')
        expanded=push_polygon_side(courtyard_geom,edge_index=court_edge,steps=deltas.pop())
        if not expanded.is_valid: raise ValueError('invalid expanded courtyard geometry')
        from shapely.geometry import mapping
        court['geometry']=mapping(expanded)
        court['solar_geometry']=courtyard_solar_geometry(court,[_building_payload(b,'UNASSIGNED') for b in buildings.values()],bundle.get('solar_reference',{}).get('latitude_deg',SOLAR_LATITUDE_DEG))
        report['courtyard_id']=court['courtyard_id']; report['h_north_edge_m']=court['solar_geometry']['h_north_edge_m']
        report['depth_along_sun_m']=court['solar_geometry']['depth_along_sun_m']
        rectangle=expanded.minimum_rotated_rectangle
        rc=list(rectangle.exterior.coords)[:4]
        report['clear_width_m']=min(math.dist(rc[i],rc[(i+1)%4]) for i in range(4))
        court['clear_width_m']=report['clear_width_m']
        court['area_m2']=expanded.area
        report['gfa_shortfall_m2']=report['removed_gfa_m2']
    report['removed']=[{**item,'floors_removed':item.get('floors',0)} for item in report['removed_buildings']]
    report['added']=[{**item,'floors_added':item.get('floors',0)} for item in report['added_buildings']]
    report['envelope_unreachable_ids']=[item['building_id'] for item in report['envelope_unreachable']]
    output=[_building_payload(b,'UNASSIGNED') for b in buildings.values()]
    report['solar_access_check']=_solar_access_check({'operations':[op]},bundle,output,affected)
    return report, affected
