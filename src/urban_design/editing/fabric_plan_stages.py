"""Hash-bound fabric prisms from explicit footprint polygons and storey metadata."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import shape


def fabric_plan_stages(parameters: dict[str, Any]) -> dict[str, Any]:
    # Imported locally to keep the formal authority error contract at the API boundary.
    from urban_design.editing.formal_authority import FormalAuthorityError

    source = parameters.get('source_path')
    expected = parameters.get('source_sha256')
    if not isinstance(source, str) or not source or not isinstance(expected, str):
        raise FormalAuthorityError('fabric source path and hash are required')
    path = Path(source)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FormalAuthorityError('fabric source bytes are unavailable') from exc
    digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
    if digest != expected:
        raise FormalAuthorityError('fabric source hash mismatch')
    try:
        plan = json.loads(raw)
        if (plan['schema_version'] != 'fab1-plan-v1' or plan['crs'] != 'EPSG:28992'
                or plan['fabric_id'] != 'fabric.harbour_grain'):
            raise ValueError('unsupported fabric schema or CRS')
        buildings = []
        identifiers = set()
        for feature in plan['buildings']:
            props = feature['properties']
            if type(props['retained']) is not bool:
                raise ValueError('explicit retained role required')
            if props['retained']:
                continue
            identifier = feature['id']
            if not isinstance(identifier, str) or not identifier or identifier in identifiers:
                raise ValueError('unique building id required')
            identifiers.add(identifier)
            geometry = feature['geometry']
            footprint = shape(geometry)
            if (footprint.geom_type not in {'Polygon', 'MultiPolygon'} or footprint.is_empty
                    or not footprint.is_valid or footprint.has_z):
                raise ValueError('valid projected footprint required')
            count = props['floors']
            if type(count) is not int or count < 1:
                raise ValueError('positive integer floors required')
            first, standard = props['first_floor_height_m'], props['standard_floor_height_m']
            if any(isinstance(h, bool) or not isinstance(h, (int, float))
                   or not math.isfinite(h) or h <= 0 for h in (first, standard)):
                raise ValueError('explicit positive storey heights required')
            height = first + (count - 1) * standard
            if height > 20 or not math.isclose(height, props['height_m'], abs_tol=1e-6):
                raise ValueError('fabric prism height inconsistent or exceeds 20 m')
            buildings.append({'id': identifier, 'use': props.get('use'),
                              'floors': [{'id': f'{identifier}-floor-{level}', 'level': level,
                                          'floor_height_m': first if level == 0 else standard,
                                          'geometry': copy.deepcopy(geometry)} for level in range(count)]})
        edges = []
        road_ids = set()
        retained_roads = {row["id"]: row for row in plan["retained_road_inputs"]}
        for rows, locked in ((plan['roads'], False), (plan['retained_road_inputs'], True)):
            for feature in rows:
                identifier = feature['id']
                props = feature.get('properties') or {}
                if not locked and props.get('role') == 'retained_city_road':
                    retained = retained_roads[props['source_id']]
                    if not shape(feature['geometry']).equals_exact(shape(retained['geometry']), 0):
                        raise ValueError('retained road geometry mismatch')
                    continue
                if not isinstance(identifier, str) or not identifier or identifier in road_ids:
                    raise ValueError('unique road id required')
                road_ids.add(identifier)
                line = shape(feature['geometry'])
                if line.geom_type != 'LineString' or line.is_empty or not line.is_valid or line.has_z:
                    raise ValueError('valid road LineString required')
                edges.append({'id': identifier, 'geometry': copy.deepcopy(feature['geometry']),
                              'level': 0, 'locked': locked})
    except (KeyError, TypeError, ValueError) as exc:
        raise FormalAuthorityError(f'invalid fabric plan: {exc}') from exc
    # Exact coincident segments represent one physical edge. Preserve every source
    # ID and let any retained source lock the shared segment. No snapping is used.
    segments: dict[tuple, dict[str, Any]] = {}
    nodes: dict[tuple, str] = {}
    for edge in edges:
        coordinates = edge['geometry']['coordinates']
        for index, (a, b) in enumerate(zip(coordinates, coordinates[1:])):
            key = tuple(sorted((tuple(a), tuple(b))))
            if a == b:
                raise FormalAuthorityError('invalid fabric plan: zero-length road segment')
            if key in segments:
                segment = segments[key]
                segment['locked'] = segment['locked'] or edge['locked']
                if edge['id'] not in segment['lineage_ids']:
                    segment['lineage_ids'].append(edge['id'])
                continue
            for point in (a, b):
                nodes.setdefault(tuple(point), f'fabric-node-{len(nodes)}')
            segments[key] = {'id': f"{edge['id']}:{index}", 'level': 0,
                             'from_node_id': nodes[tuple(a)], 'to_node_id': nodes[tuple(b)],
                             'geometry': {'type': 'LineString', 'coordinates': [a, b]},
                             'locked': edge['locked'], 'lineage_ids': [edge['id']]}
    return {'derivation': 'FABRIC_PLAN_PRISM_V1', 'source_sha256': digest,
            'massing': {'buildings': buildings}, 'skeleton': {'edges': list(segments.values())}}
