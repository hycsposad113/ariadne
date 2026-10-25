"""NET1 additive network study over immutable FAB run-5 geometry.

All endpoints come from supplied frozen mode extracts. No acquisition or adoption.
The visibility search refuses footprint collisions instead of cutting buildings.
"""
from __future__ import annotations

import copy
import heapq
import math

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import nearest_points, unary_union
from shapely.affinity import rotate


def parts(g):
    return list(g.geoms) if hasattr(g, 'geoms') else [g]


def visible_route(a, b, obstacles, width=4):
    """Shortest visibility route in a bounded obstacle corridor, or None."""
    direct = LineString([a, b])
    if direct.length < .01:
        return None
    blocked = obstacles.buffer(width / 2 + .01, join_style=2)
    if direct.intersection(blocked).length < 1e-7:
        return direct
    local = blocked.intersection(direct.buffer(60, cap_style=3))
    nodes = [tuple(a), tuple(b)]
    for polygon in parts(local):
        if polygon.geom_type == 'Polygon':
            # A tiny outward offset makes boundary visibility numerically stable.
            for q in parts(polygon.buffer(.02, join_style=2)):
                if q.geom_type == 'Polygon':
                    nodes.extend(tuple(c) for c in q.exterior.coords[:-1])
    nodes = list(dict.fromkeys(nodes))
    if len(nodes) > 450:
        return None
    edges = [[] for _ in nodes]
    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            line = LineString([a, nodes[j]])
            if line.intersection(blocked).length <= 1e-7:
                edges[i].append((j, line.length)); edges[j].append((i, line.length))
    queue = [(0., 0)]; distances = {0: 0.}; previous = {}
    while queue:
        distance, i = heapq.heappop(queue)
        if distance != distances[i]:
            continue
        if i == 1:
            path = [nodes[1]]
            while i:
                i = previous[i]; path.append(nodes[i])
            return LineString(path[::-1])
        for j, length in edges[i]:
            total = distance + length
            if total < distances.get(j, math.inf):
                distances[j] = total; previous[j] = i; heapq.heappush(queue, (total, j))
    return None


def finish_network(parent, external, context, round_number):
    if round_number not in (1, 2, 3) or parent.get('crs') != 'EPSG:28992':
        raise ValueError('NET1 needs EPSG:28992 and round 1..3')
    plan = copy.deepcopy(parent)
    footprints = unary_union([shape(b['geometry']) for b in plan['buildings']])
    # Whole islands remain inviolate; no public street through their court.
    obstacles = footprints
    if plan['fabric_id'] == 'fabric.courtyard_islands':
        obstacles = obstacles.union(unary_union([shape(b['geometry']) for b in plan['blocks']]))
    if round_number == 3:
        obstacles = obstacles.union(unary_union([shape(b['geometry']) for b in plan.get('boundary_parcels', [])]))
    site = shape(plan['site']); water = shape(plan['water'])
    records = []; rejected = []
    roads = plan['roads']
    land = site.difference(water)
    waterfront_land = unary_union([shape(r['geometry']) for r in plan['land_use'] if r['properties']['category'] == 'waterfront'])
    internal = {'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','park_maintenance_path','south_quay_shared_alley'}
    public = unary_union([shape(r['geometry']).buffer(r['properties']['width_m']/2, cap_style=2, join_style=2)
                          for r in roads if r['properties']['role'] not in internal]).union(waterfront_land).intersection(land)

    def add(line, role, modes, strategy, target=None, assumption=None, width=4):
        nonlocal public
        if line is None or line.length <= .01:
            return
        if line.buffer(width / 2, cap_style=2, join_style=2).intersection(footprints).area > .05:
            rejected.append({'strategy': strategy, 'reason': 'footprint clearance', 'geometry': mapping(line)})
            return
        candidate_public = public.union(line.buffer(width/2, cap_style=2, join_style=2).intersection(land))
        if round_number >= 2 and candidate_public.area/land.area > .32 + 1e-8:
            rejected.append({'strategy': strategy, 'reason': 'combined road-waterfront budget 32 percent', 'geometry': mapping(line)})
            return
        public = candidate_public
        ident = f'net1-{len(records):03d}'
        props = dict(id=ident, width_m=width, modes=modes, role=role, hierarchy=1,
                     net1_strategy=strategy, net1_round=round_number,
                     target_source_id=target, assumption=assumption,
                     evidence_status='ASSUMED' if assumption else 'EXPLORATORY_DESIGN',
                     requires_founder_confirmation=bool(assumption))
        row = {'type': 'Feature', 'id': ident, 'geometry': mapping(line), 'properties': props}
        roads.append(row); records.append(row)

    def route_to(target, mode, anchors, strategy, assumption=None):
        tg = shape(target['geometry'])
        options = []
        for anchor in anchors:
            a, b = nearest_points(anchor, tg)
            if round_number == 3 and 'dakpark' in str(target['properties'].get('name', '')).casefold():
                # A shared layer-0/layer-1 endpoint remains an unlink. Contact
                # the interior of the source's layer-0 entrance segment instead.
                along = tg.project(b)
                b = tg.interpolate(min(max(along, 5.), tg.length-5.))
            if a.distance(b) < .01:
                continue
            route = visible_route(a.coords[0], b.coords[0], obstacles)
            if route is not None:
                options.append(route)
        if options:
            route = min(options, key=lambda x: x.length)
            if route.length <= 350:
                add(route, 'city_connector', [mode], strategy, target['id'], assumption)
                return
        rejected.append({'strategy': strategy, 'target': target['id'], 'reason': 'no bounded clear route'})

    primary = [shape(r['geometry']) for r in roads if r['properties']['role'] == 'primary_street']
    ends = [Point(c) for g in primary for c in (g.coords[0], g.coords[-1])]
    for mode, features in external.items():
        pmode = 'car' if mode == 'motor_vehicle' else mode
        for name in ('Keileweg', 'Vierhavensstraat', 'Marconistraat'):
            targets = [f for f in features if name.casefold() in str(f['properties'].get('name', '')).casefold()
                       and shape(f['geometry']).distance(site) <= 150]
            # Both ends, each to its nearest surviving same-mode source support.
            for end in ends:
                if targets:
                    target = min(targets, key=lambda f: end.distance(shape(f['geometry'])))
                    route_to(target, pmode, [end], 'primary_end_city_connection')
        if mode != 'motor_vehicle':
            targets = [f for f in features if 'dakpark' in str(f['properties'].get('name', '')).casefold()
                       and (round_number == 1 or int(f['properties'].get('layer') or 0) == 0)]
            if targets:
                eastern = max(ends, key=lambda p: p.x)
                target = min(targets, key=lambda f: eastern.distance(shape(f['geometry'])))
                route_to(target, pmode, [eastern], 'dakpark_edge_connection',
                         'ASSUMED_DAKPARK_UNKNOWN_LEVEL_AND_CROSSING')
                if mode == 'pedestrian' and round_number >= 2:
                    route_to(target, 'bicycle', [eastern], 'dakpark_assumed_bicycle_approach',
                             'ASSUMED_DAKPARK_NO_NAMED_BICYCLE_TARGET_UNKNOWN_LEVEL')
            else:
                rejected.append({'strategy': 'dakpark_edge_connection', 'mode': mode,
                                 'reason': 'no surviving named target in frozen mode extract'})

    # Add waterfront-to-city cross links at existing public-road intersections.
    waterfront = unary_union([shape(r['geometry']) for r in roads if r['properties']['role'] == 'waterfront_path'])
    cross = [shape(r['geometry']) for r in parent['roads'] if r['properties']['role'] in ('block_edge_street', 'harbour_cross_lane')]
    selected = []
    for g in sorted(cross, key=lambda g: g.centroid.x):
        a, b = nearest_points(g, waterfront)
        if a.distance(b) > 100 or any(a.distance(old) < 65 for old in selected):
            continue
        route = visible_route(a.coords[0], b.coords[0], obstacles)
        if route is not None:
            add(route, 'cross_street', ['pedestrian', 'bicycle'], 'cross_street_to_waterfront')
            selected.append(a)
        if round_number >= 2:
            for mode in ('pedestrian', 'bicycle'):
                targets = [f for f in external[mode] if 'keileweg' in str(f['properties'].get('name', '')).casefold()]
                if targets:
                    target = min(targets, key=lambda f: a.distance(shape(f['geometry'])))
                    route_to(target, mode, [a], 'cross_street_through_to_keileweg')

    if round_number >= 2 and not water.is_empty:
        # Two perpendicular water crossings with exact landings on public paths.
        axis = context['site']['principal_axis']['long_axis_azimuth_deg']
        origin = tuple(site.centroid.coords[0]); angle = 90 - axis
        local_water = rotate(water, -angle, origin=origin)
        xmin, ymin, xmax, ymax = local_water.bounds
        local_front = rotate(waterfront, -angle, origin=origin)
        for fraction in (.32, .70):
            candidates = []
            for offset in range(-30, 31, 3):
                x = xmin + fraction * (xmax - xmin) + offset
                ray = LineString([(x, ymin - 25), (x, ymax + 25)])
                hits = ray.intersection(local_front)
                pts = [p for p in parts(hits) if p.geom_type == 'Point']
                for a in pts:
                    for b in pts:
                        line = LineString([a, b])
                        if a.y >= b.y or not 30 <= line.intersection(local_water).length <= 90:
                            continue
                        world = rotate(line, angle, origin=origin)
                        if world.buffer(2.01, cap_style=2).intersection(obstacles).area <= .01:
                            candidates.append(world)
            if candidates:
                add(min(candidates, key=lambda g: g.length), 'canal_bridge', ['pedestrian', 'bicycle'],
                    'cross_canal_bridge', assumption='ASSUMED_BRIDGE', width=4)

    if round_number == 3:
        # Close boundary-entry gaps using each mode's authoritative source, not
        # rounded CTX1 candidate endpoints as a substitute for exact contact.
        for entry in plan['entrances']:
            point = Point(entry['coordinates'])
            for mode in ('pedestrian', 'bicycle'):
                targets = [f for f in external[mode] if shape(f['geometry']).distance(point) <= 35]
                if not targets:
                    continue
                target = min(targets, key=lambda f: shape(f['geometry']).distance(point))
                anchors = [shape(r['geometry']) for r in roads if mode in r['properties']['modes']]
                nearest = min(anchors, key=lambda g: g.distance(point))
                route_to(target, mode, [nearest], 'entry_exact_city_connection')
        for candidate in context['continuation_street_candidates']:
            if candidate['distance_to_site_m'] > 150:
                continue
            for mode in ('pedestrian', 'bicycle'):
                targets = [f for f in external[mode] if str(f['properties'].get('name', '')).casefold() == candidate['name'].casefold()
                           and int(f['properties'].get('layer') or 0) == 0]
                if not targets:
                    continue
                endpoint = Point(candidate['street_end_point'])
                target = min(targets, key=lambda f: shape(f['geometry']).distance(endpoint))
                actual = nearest_points(endpoint, shape(target['geometry']))[1]
                boundary = Point(candidate['connection_point'])
                extension = LineString([actual, boundary])
                anchors = [shape(r['geometry']) for r in roads if mode in r['properties']['modes']]
                anchor = min(anchors, key=lambda g: g.distance(boundary))
                inside = visible_route(boundary.coords[0], nearest_points(boundary, anchor)[1].coords[0], obstacles)
                if inside is None:
                    continue
                before = len(records)
                add(LineString(list(extension.coords) + list(inside.coords)[1:]), 'city_connector', [mode],
                    'ctx1_continuation_alignment', target['id'], 'ASSUMED_EXTERNAL_STREET_CONTINUATION')
                if len(records) > before:
                    records[-1]['properties']['ctx1_candidate'] = copy.deepcopy(candidate)
    plan['net1'] = {'round': round_number, 'parent': 'fab1/run-5', 'added_roads': records,
                    'rejected_connections': rejected, 'context_candidates': context['continuation_street_candidates'],
                    'method': 'bounded footprint-clear visibility routes, exact frozen same-mode target coordinates',
                    'vertical_reference': 'UNKNOWN; crossings and bridges remain assumptions',
                    'formal_result_eligible': False}
    plan['limitations'].extend(['NET1 橋梁與 Dakpark 高差／外部道路穿越是假設，需 Founder 確認；未驗證通行權與結構。',
                               '自行車凍結來源缺少具名 Dakpark 路段；不得以步行目標替代。'])
    return plan
