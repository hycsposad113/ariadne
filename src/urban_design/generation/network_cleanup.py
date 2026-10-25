"""Deterministic, copy-only planar network postprocessing (EPSG:28992 metres).

Retained source records remain byte-equivalent; their noded graph representation
is internal. Conflicting locked anchors are never averaged. Failed operations
leave geometry unchanged and produce measured unresolved records.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import math
from pathlib import Path
import json

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from shapely.geometry import LineString, Point
from shapely.ops import unary_union, polygonize, split, nearest_points
from shapely.strtree import STRtree

from .multimodal_network import NetworkRoad, NetworkRules, Entrance

EPS = 1e-7
MODES = ('pedestrian', 'bicycle', 'motor_vehicle')
CARD = Path(__file__).with_name('network_cleanup_rules.json')


class CleanupRules(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    rule_card_id: str
    snap_tolerance_m: FiniteFloat = Field(gt=0)
    minimum_segment_m: FiniteFloat = Field(gt=0)
    duplicate_distance_m: FiniteFloat = Field(gt=0)
    minimum_turn_deg: FiniteFloat = Field(gt=0, lt=90)
    projection_distance_m: FiniteFloat = Field(gt=0)
    block_min_m: FiniteFloat = Field(gt=0)
    block_max_m: FiniteFloat = Field(gt=0)
    subdivision_spacing_m: FiniteFloat = Field(gt=0)
    max_iterations: int = Field(gt=0)
    parallel_distance_m: FiniteFloat = Field(default=15, gt=0)
    parallel_angle_deg: FiniteFloat = Field(default=20, gt=0, lt=90)

    @classmethod
    def from_card(cls):
        return cls.model_validate(json.loads(CARD.read_text())['parameters'])


class CleanupReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rule_card_id: str
    merged_node_count: int = 0
    contracted_edge_count: int = 0
    deleted_edge_count: int = 0
    t_junction_repair_count: int = 0
    subdivision_segment_count: int = 0
    redundant_parallel_count: int = 0
    reconnect_count: int = 0
    retained_roads_to_improve: list[str] = Field(default_factory=list)
    iterations: int = 0
    mode_components_before: dict[str, int] = Field(default_factory=dict)
    mode_components_after: dict[str, int] = Field(default_factory=dict)
    exempt_locked: list[dict] = Field(default_factory=list)
    unresolved: list[dict] = Field(default_factory=list)
    unresolved_block: list[dict] = Field(default_factory=list)


def lines(g):
    if g.geom_type == 'LineString':
        return [g] if g.length > 0 else []
    return [l for p in getattr(g, 'geoms', ()) for l in lines(p)]


def key(r):
    return (r.layer, tuple(r.coordinates), r.id)


def noded(roads):
    """Node per grade, then reattach every source's mode and provenance."""
    result = []
    for layer in sorted({r.layer for r in roads}):
        sources = sorted([r for r in roads if r.layer == layer], key=key)
        gs = [LineString(r.coordinates) for r in sources]
        tree = STRtree(gs)
        parts = lines(unary_union(gs))
        segments = sorted((LineString([a, b]) for p in parts for a, b in zip(p.coords, list(p.coords)[1:])), key=lambda l: tuple(l.coords))
        for segment in segments:
            if segment.length <= 0:
                continue
            # Coverage, not midpoint proximity, establishes source ownership.
            for i in sorted(tree.query(segment)):
                if segment.difference(gs[i].buffer(EPS)).length > EPS:
                    continue
                r = sources[i]
                result.append(r.model_copy(update={'id': r.id.split(':node:')[0] + ':node:' + str(len(result)), 'coordinates': list(segment.coords)}))
    return sorted(result, key=key)


def components(roads, anchors=()):
    """Metric topology: point anchors attach to line interiors without moving them.

    EPS is a numerical GEOS tolerance, not the rule-card snap distance. Exact
    tuple equality otherwise misclassifies retained entrance intersections.
    """
    counts = {}
    for mode in MODES:
        count = 0
        layers = sorted({r.layer for r in roads if mode in r.modes} | ({0} if any(mode in e.modes for e in anchors) else set()))
        for layer in layers:
            geometries = lines(unary_union([LineString(r.coordinates) for r in roads if mode in r.modes and r.layer == layer]))
            if layer == 0:
                geometries.extend(Point(e.coordinates) for e in anchors if mode in e.modes)
            if not geometries:
                continue
            tree = STRtree(geometries); unseen = set(range(len(geometries)))
            while unseen:
                count += 1; pending = [min(unseen)]; reached = set(pending)
                while pending:
                    i = pending.pop()
                    for j in sorted(tree.query(geometries[i].buffer(EPS))):
                        j = int(j)
                        if j in unseen and j not in reached and geometries[i].distance(geometries[j]) <= EPS:
                            reached.add(j); pending.append(j)
                unseen -= reached
        counts[mode] = count
    return counts


def locked_nodes(edges, entrances):
    return {(r.layer, tuple(c)) for r in edges if r.origin == 'retained' for c in r.coordinates} | {(0, tuple(e.coordinates)) for e in entrances}


def dedup(edges):
    seen = set(); result = []
    for r in sorted(edges, key=key):
        a, b = r.coordinates
        if math.dist(a, b) <= EPS and r.origin != 'retained':
            continue
        identity = (r.layer, tuple(sorted((tuple(a), tuple(b)))), tuple(sorted(r.modes)), r.origin, r.width_m, r.access, r.hierarchy)
        if identity not in seen:
            seen.add(identity); result.append(r)
    return result


def replace_nodes(edges, moves):
    return dedup([r if r.origin == 'retained' else r.model_copy(update={'coordinates': [moves.get((r.layer, tuple(c)), tuple(c)) for c in r.coordinates]}) for r in edges])


def admissible(before, after, obstacles, domain, entrances):
    def geometry_key(r):
        return (r.layer, tuple(sorted(map(tuple, r.coordinates))), r.width_m, tuple(sorted(r.modes)))
    old = {geometry_key(r) for r in before}
    for r in after:
        if r.origin == 'retained' or geometry_key(r) in old:
            continue
        g = LineString(r.coordinates)
        if domain is not None and not domain.buffer(EPS).covers(g):
            return False
        if not obstacles.is_empty and g.buffer(r.width_m / 2, cap_style=2).intersection(obstacles).area > EPS:
            return False
    a, b = components(before, entrances), components(after, entrances)
    return all(b[m] <= a[m] and (a[m] == 0 or b[m] > 0) for m in MODES)


def acute_pairs(edges, threshold):
    junctions = defaultdict(list)
    for i, r in enumerate(edges):
        a, b = map(tuple, r.coordinates)
        junctions[(r.layer, a)].append((i, b)); junctions[(r.layer, b)].append((i, a))
    violations = []
    for (layer, p), rays in sorted(junctions.items()):
        for (i, a), (j, b) in combinations(rays, 2):
            if edges[i].origin == edges[j].origin == 'retained':
                continue
            u, v = (a[0]-p[0], a[1]-p[1]), (b[0]-p[0], b[1]-p[1])
            cosine = (u[0]*v[0]+u[1]*v[1]) / (math.hypot(*u)*math.hypot(*v))
            angle = math.degrees(math.acos(max(-1, min(1, cosine))))
            # Coincident permissions are one physical ray, not a zero-degree turn.
            if angle <= 1e-6 and LineString([p, a]).intersection(LineString([p, b])).length > EPS:
                continue
            if angle < threshold:
                violations.append((layer, p, i, j, angle))
    return violations


def dimensions(block):
    cs = list(block.minimum_rotated_rectangle.exterior.coords)
    lengths = [math.dist(a, b) for a, b in zip(cs, cs[1:])]
    i = max(range(4), key=lambda i: (lengths[i], cs[i], cs[i+1]))
    a, b = cs[i], cs[i+1]; length = lengths[i]
    return min(lengths), length, a, ((b[0]-a[0])/length, (b[1]-a[1])/length)


def blocks(roads, domain):
    # Only physical same-grade roads close blocks; site edges are not fabricated roads.
    support = unary_union([LineString(r.coordinates) for r in roads if r.layer == 0])
    return sorted([b for b in polygonize(support) if domain is None or domain.buffer(EPS).covers(b)], key=lambda b: (b.bounds, b.area))


def _bearing(line):
    (x1, y1), (x2, y2) = line.coords[0], line.coords[-1]
    return math.degrees(math.atan2(y2-y1, x2-x1)) % 180


def _bearing_gap(a, b):
    gap = abs(a-b) % 180
    return min(gap, 180-gap)


def drop_redundant_parallels(edges, rules):
    """Remove new segments that only duplicate a retained road alongside it.

    Design rule (Commander 2026-10-08): existing city roads already give service
    and fire access and carry walking/cycling on their own cross-section; a new
    path drawn a few metres beside them is redundant and creates sliver blocks
    and near-zero junction angles. Removal is recorded so the retained road can
    be flagged for walking/cycling improvement instead.
    """
    retained = [LineString(r.coordinates) for r in edges if r.origin == 'retained' and r.layer == 0]
    if not retained:
        return edges, []
    tree = STRtree(retained)
    kept, dropped = [], []
    for r in edges:
        g = LineString(r.coordinates)
        if r.origin == 'retained' or g.length <= EPS:
            (kept if r.origin == 'retained' else dropped).append(r)
            continue
        # Only structural roads (service loop, main path) are duplicates of a city
        # road; short branches and connectors legitimately leave at shallow angles.
        if r.hierarchy not in ('service', 'main'):
            kept.append(r)
            continue
        near = [retained[int(i)] for i in tree.query(g.buffer(rules.parallel_distance_m))]
        redundant = False
        for line in near:
            if any(Point(c).distance(line) > rules.parallel_distance_m for c in g.coords):
                continue
            at = line.project(g.centroid)
            local = LineString([line.interpolate(max(0., at-5.)), line.interpolate(min(line.length, at+5.))])
            if local.length > EPS and _bearing_gap(_bearing(g), _bearing(local)) < rules.parallel_angle_deg:
                redundant = True
                break
        (dropped if redundant else kept).append(r)
    return kept, dropped


def _mode_components(edges, mode):
    pieces = lines(unary_union([LineString(r.coordinates) for r in edges if mode in r.modes and r.layer == 0]))
    groups = []
    for g in sorted(pieces, key=lambda g: (-g.length, g.wkb_hex)):
        touching = [c for c in groups if c.distance(g) <= EPS]
        groups = [c for c in groups if not any(c is t for t in touching)] + [unary_union([g, *touching])]
    return sorted(groups, key=lambda c: (-c.length, c.wkb_hex))


def reconnect_modes(edges, rules, obstacles, domain, tag):
    """Join each detached piece to the largest same-mode network with the shortest clear link."""
    added = []
    for mode in MODES:
        for _ in range(rules.max_iterations):
            groups = _mode_components(edges, mode)
            if len(groups) <= 1:
                break
            main = groups[0]
            best = None
            for group in groups[1:]:
                for line in lines(group):
                    for end in (Point(line.coords[0]), Point(line.coords[-1])):
                        target = nearest_points(end, main)[1]
                        link = LineString([end, target])
                        if not EPS < link.length <= rules.projection_distance_m:
                            continue
                        if link.length < rules.minimum_segment_m:
                            # Too short for a link: candidate is moving the dangling end onto the target.
                            pass
                        if domain is not None and not domain.buffer(EPS).covers(link):
                            continue
                        if not obstacles.is_empty and link.buffer(.5).intersection(obstacles).area > EPS:
                            continue
                        candidate = (link.length, link.wkb_hex, link, end)
                        best = candidate if best is None or candidate[:2] < best[:2] else best
            if best is None:
                break
            _, _, link, end = best
            source = min((r for r in edges if mode in r.modes and LineString(r.coordinates).distance(end) <= EPS), key=key)
            if link.length < rules.minimum_segment_m and source.origin != 'retained':
                moved = [tuple(link.coords[-1]) if math.dist(tuple(c), end.coords[0]) <= EPS else tuple(c) for c in source.coordinates]
                if LineString(moved).length >= rules.minimum_segment_m:
                    edges = [r if r is not source else source.model_copy(update={'coordinates': moved}) for r in edges]
                    added.append(source)
                    continue
            # Links always carry walking + cycling together (Dutch shared corridor);
            # motor links add service access. Never a cycle-only link without a footway.
            link_modes = ['bicycle', 'motor_vehicle', 'pedestrian'] if mode == 'motor_vehicle' else ['bicycle', 'pedestrian']
            road = source.model_copy(update={'id': f'cleanup:{tag}:reconnect:{mode}:{len(added)}', 'coordinates': list(link.coords), 'origin': 'new',
                                             'source_road_ids': [], 'modes': link_modes,
                                             'hierarchy': source.hierarchy if source.origin != 'retained' else ('service' if mode == 'motor_vehicle' else 'branch')})
            edges = [*edges, road]
            added.append(road)
    return edges, added


def subdivide_blocks(edges, rules, network_rules, obstacles, domain, tag):
    """Cut oversized blocks (closed by roads or the site edge) with clear road-to-road paths."""
    added, unresolved = [], []
    if domain is None:
        # Without a site boundary, the area enclosed by the roads themselves is the domain.
        domain = unary_union(list(polygonize(unary_union([LineString(r.coordinates) for r in edges if r.layer == 0]))))
        if domain.is_empty:
            return edges, added, unresolved
    for _ in range(rules.max_iterations):
        road_lines = unary_union([LineString(r.coordinates) for r in edges if r.layer == 0])
        # Blocks are the buildable remnants (site minus road surfaces and obstacles),
        # the same basis as the final quality check; no exact closure is required.
        surfaces = unary_union([LineString(r.coordinates).buffer(r.width_m/2, cap_style=2) for r in edges if r.layer == 0])
        remnant = domain.difference(unary_union([surfaces, obstacles]))
        closed = [b for b in polygonize(unary_union([road_lines, domain.boundary])) if b.area > 400 and domain.buffer(EPS).covers(b.representative_point())]
        # Slivers that cannot hold a 6 m-wide footprint are not blocks (e.g. a thin frame
        # between a road and the site edge).
        candidates = sorted([b for b in [*(b for b in getattr(remnant, 'geoms', [remnant]) if b.geom_type == 'Polygon' and b.area > 400), *closed]
                             if not b.buffer(-3.).is_empty],
                            key=lambda b: (-dimensions(b)[1], b.bounds))
        target = next((b for b in candidates if dimensions(b)[1] > rules.block_max_m
                       and not any(math.dist(b.centroid.coords[0], u['coordinates']) < 1 for u in unresolved)), None)
        if target is None:
            break
        short, long_side, origin, axis = dimensions(target)
        if short < rules.block_min_m:
            # A strip narrower than the 40m minimum cannot yield compliant children.
            unresolved.append({'coordinates': list(target.centroid.coords[0]), 'bounds': list(target.bounds), 'long_side_m': long_side,
                               'short_side_m': short, 'reason': f'Short side below {rules.block_min_m:g}m minimum; subdivision cannot produce compliant children'})
            continue
        normal = (-axis[1], axis[0])
        sections = max(2, math.ceil(long_side/rules.subdivision_spacing_m))
        placed = []
        for k in range(1, sections):
            base = long_side*k/sections
            for shift in (0, 10, -10, 20, -20, 30, -30):
                t = base+shift
                if not rules.block_min_m <= t <= long_side-rules.block_min_m:
                    continue
                c = (origin[0]+axis[0]*t, origin[1]+axis[1]*t)
                cut = LineString([(c[0]-normal[0]*long_side*2, c[1]-normal[1]*long_side*2), (c[0]+normal[0]*long_side*2, c[1]+normal[1]*long_side*2)])
                pieces = [p for p in lines(cut.intersection(target)) if p.length >= rules.minimum_segment_m]
                if not pieces:
                    continue
                piece = max(pieces, key=lambda p: (p.length, p.wkb_hex))
                # Extend along the cut itself (perpendicular to the block axis) to
                # the first road it meets, so junctions stay close to 90 degrees.
                crossings = [pt for g in lines(road_lines) for pt in getattr(cut.intersection(g), 'geoms', [cut.intersection(g)]) if pt.geom_type == 'Point']
                ends = []
                for end in (Point(piece.coords[0]), Point(piece.coords[-1])):
                    if end.distance(road_lines) <= 1.:
                        ends.append(end)
                        continue
                    other = Point(piece.coords[-1]) if end.equals(Point(piece.coords[0])) else Point(piece.coords[0])
                    outward = [pt for pt in crossings if pt.distance(end) <= rules.parallel_distance_m and pt.distance(other) > end.distance(other)]
                    if not outward:
                        ends = None
                        break
                    ends.append(min(outward, key=lambda pt: (pt.distance(end), pt.wkb_hex)))
                if ends is None:
                    continue
                snapped = []
                nodes = [Point(c) for g in lines(road_lines) for c in (g.coords[0], g.coords[-1])]
                for end in ends:
                    node = min(nodes, key=lambda n: (n.distance(end), n.wkb_hex)) if nodes else None
                    snapped.append(node if node is not None and node.distance(end) < rules.minimum_segment_m else end)
                piece = LineString([snapped[0], snapped[1]])
                def meets_square(end):
                    near = min(lines(road_lines), key=lambda g: (g.distance(end), g.wkb_hex))
                    at = near.project(end)
                    local = LineString([near.interpolate(max(0., at-3.)), near.interpolate(min(near.length, at+3.))])
                    return local.length <= EPS or _bearing_gap(_bearing(local), _bearing(piece)) >= rules.minimum_turn_deg
                if not all(meets_square(e) for e in snapped):
                    continue
                if piece.length < rules.minimum_segment_m or not piece.is_simple:
                    continue
                if not obstacles.is_empty and piece.buffer(network_rules.shared_width_m/2, cap_style=2).intersection(obstacles).area > EPS:
                    continue
                if any(piece.distance(p) < rules.block_min_m for p in placed):
                    continue
                # Respect spacing against every existing road running the same way, not
                # only against cuts placed in this pass (prevents clustered parallels).
                mid = piece.interpolate(.5, normalized=True)
                if any(_bearing_gap(_bearing(LineString(r.coordinates)), _bearing(piece)) < rules.parallel_angle_deg
                       and LineString(r.coordinates).distance(mid) < rules.block_min_m*.75 for r in edges if r.layer == 0 and LineString(r.coordinates).length > EPS):
                    continue
                placed.append(piece)
                break
        if not placed:
            unresolved.append({'coordinates': list(target.centroid.coords[0]), 'bounds': list(target.bounds), 'long_side_m': long_side,
                               'short_side_m': short, 'reason': 'No clear road-to-road cut within ±30 m of even spacing'})
            continue
        for piece in placed:
            road = NetworkRoad(id=f'cleanup:{tag}:subdivision:{len(added)}', coordinates=list(piece.coords), width_m=network_rules.shared_width_m,
                               modes=['pedestrian', 'bicycle'], origin='new', source_road_ids=[], semantics_provenance='Commander block subdivision (DRAFT rule card)',
                               hierarchy='branch', width_class='shared', rule_card_ids=[rules.rule_card_id])
            edges = [*edges, road]
            added.append(road)
    return edges, added, unresolved


def close_dead_ends(edges, entrances, rules, network_rules, obstacles, domain, tag):
    """Link each interior dead end (not an entrance, not on the site edge) to the nearest
    other road with a short square link, so tails do not count against the dead-end cap."""
    added, blocked = [], set()
    for _ in range(rules.max_iterations):
        graph = defaultdict(set)
        for r in edges:
            if r.layer != 0:
                continue
            a, b = (tuple(c) for c in r.coordinates)
            graph[a].add(b); graph[b].add(a)
        anchors = [Point(e.coordinates) for e in entrances]
        boundary = domain.boundary if domain is not None else None
        tails = sorted(p for p, nbrs in graph.items() if len(nbrs) == 1 and p not in blocked
                       and not any(Point(p).distance(a) <= 1e-6 for a in anchors)
                       and (boundary is None or Point(p).distance(boundary) > 1.))
        best = None
        for p in tails:
            point = Point(p)
            own = [LineString(r.coordinates) for r in edges if r.layer == 0 and p in map(tuple, r.coordinates)]
            others = unary_union([LineString(r.coordinates) for r in edges if r.layer == 0 and p not in map(tuple, r.coordinates)])
            if others.is_empty:
                continue
            target = nearest_points(point, others)[1]
            link = LineString([point, target])
            if not rules.minimum_segment_m <= link.length <= rules.projection_distance_m:
                continue
            if domain is not None and not domain.buffer(EPS).covers(link):
                continue
            if not obstacles.is_empty and link.buffer(network_rules.shared_width_m/2, cap_style=2).intersection(obstacles).area > EPS:
                continue
            candidate = (link.length, link.wkb_hex, link, p)
            best = candidate if best is None or candidate[:2] < best[:2] else best
        if best is None:
            break
        _, _, link, p = best
        source = min((r for r in edges if p in map(tuple, r.coordinates)), key=key)
        road = NetworkRoad(id=f'cleanup:{tag}:close-dead-end:{len(added)}', coordinates=list(link.coords), width_m=network_rules.shared_width_m,
                           modes=sorted(set(source.modes) & {'pedestrian', 'bicycle'}) or ['pedestrian', 'bicycle'], origin='new', source_road_ids=[],
                           semantics_provenance='Commander dead-end closure (DRAFT rule card)', hierarchy='branch', width_class='shared', rule_card_ids=[rules.rule_card_id])
        trial = dedup(noded([*edges, road]))
        if len(acute_pairs(trial, rules.minimum_turn_deg)) > len(acute_pairs(dedup(noded(edges)), rules.minimum_turn_deg)):
            # Would create a sharp junction; leave this tail as a recorded dead end.
            blocked.add(p)
            continue
        edges = [*edges, road]
        added.append(road)
    return edges, added


def connect_entrances(edges, entrances, rules, obstacles, domain, tag):
    """Every entrance must touch a same-mode road; link stragglers to the nearest one."""
    added = []
    for entrance in sorted(entrances, key=lambda e: e.id):
        point = Point(entrance.coordinates)
        for mode in entrance.modes:
            if mode == 'motor_vehicle':
                continue
            same = [r for r in edges if mode in r.modes and r.layer == 0]
            if not same or any(LineString(r.coordinates).distance(point) <= EPS for r in same):
                continue
            target = nearest_points(point, unary_union([LineString(r.coordinates) for r in same]))[1]
            link = LineString([point, target])
            if not EPS < link.length <= rules.projection_distance_m:
                continue
            if not obstacles.is_empty and link.buffer(.5).intersection(obstacles).area > EPS:
                continue
            source = min(same, key=lambda r: (LineString(r.coordinates).distance(target), key(r)))
            road = source.model_copy(update={'id': f'cleanup:{tag}:entrance:{entrance.id}:{mode}', 'coordinates': list(link.coords), 'origin': 'new',
                                             'source_road_ids': [], 'modes': ['bicycle', 'pedestrian'],
                                             'hierarchy': 'branch' if source.origin == 'retained' else source.hierarchy})
            edges = [*edges, road]
            added.append(road)
    return edges, added


MICRO_SEGMENT_M = 0.05


def collapse_micro_segments(edges):
    """Merge new segments shorter than 5 cm into a single node.

    Near-coincident nodes (e.g. a link snapped 4 mm off a retained vertex)
    produce millimetre segments that PST drops, which breaks source-line
    coverage. The far endpoint is moved onto the anchor endpoint, preferring
    an endpoint that lies on a retained road; retained geometry never moves.
    """
    retained_pts = {tuple(c) for r in edges if r.origin == 'retained' for c in r.coordinates}
    moves = {}
    kept = []
    for r in edges:
        if r.origin != 'retained' and len(r.coordinates) == 2 and LineString(r.coordinates).length < MICRO_SEGMENT_M:
            a, b = tuple(r.coordinates[0]), tuple(r.coordinates[1])
            if b in retained_pts and a not in retained_pts:
                a, b = b, a
            if b not in retained_pts:
                moves[b] = a
            continue
        kept.append(r)
    if not moves:
        return [r for r in kept if r.origin == 'retained' or LineString(r.coordinates).length > 1e-3]
    def resolve(p):
        seen = set()
        while p in moves and p not in seen:
            seen.add(p); p = moves[p]
        return p
    out = []
    for r in kept:
        if r.origin != 'retained':
            coords = [list(resolve(tuple(c))) for c in r.coordinates]
            if LineString(coords).length <= 1e-3:
                continue
            r = r.model_copy(update={'coordinates': coords})
        out.append(r)
    return out


def heal_isolated_pieces(edges, rules, report, entrances=()):
    """Final pass on the all-mode graph: snap pieces within the short-segment gap onto
    the main network; drop short isolated new stubs that cannot be joined (recorded)."""
    for _ in range(rules.max_iterations):
        pieces = lines(unary_union([LineString(r.coordinates) for r in edges if r.layer == 0]))
        groups = []
        for g in sorted(pieces, key=lambda g: (-g.length, g.wkb_hex)):
            touching = [c for c in groups if c.distance(g) <= 1e-6]
            groups = [c for c in groups if not any(c is t for t in touching)] + [unary_union([g, *touching])]
        groups.sort(key=lambda c: (-c.length, c.wkb_hex))
        if len(groups) <= 1:
            return edges
        main, stray = groups[0], groups[1]
        members = [r for r in edges if r.layer == 0 and LineString(r.coordinates).distance(stray) <= 1e-6]
        anchor_points = [Point(e.coordinates) for e in entrances]
        free_ends = [Point(c) for r in members for c in r.coordinates if not any(Point(c).distance(a) <= 1e-6 for a in anchor_points)]
        if stray.distance(main) < rules.minimum_segment_m and free_ends and all(r.origin != 'retained' for r in members):
            # Entrance points are fixed anchors: never move them; join through a free end.
            end = min(free_ends, key=lambda p: (p.distance(main), p.wkb_hex))
            target = nearest_points(end, main)[1]
            if end.distance(target) < rules.minimum_segment_m:
                edges = [r.model_copy(update={'coordinates': [tuple(target.coords[0]) if math.dist(tuple(c), end.coords[0]) <= EPS else tuple(c) for c in r.coordinates]})
                         if any(r is m for m in members) else r for r in edges]
            else:
                source = min(members, key=key)
                edges = [*edges, source.model_copy(update={'id': f'{source.id}:heal-link', 'coordinates': [end.coords[0], target.coords[0]],
                                                           'modes': ['bicycle', 'pedestrian'], 'source_road_ids': []})]
            report.merged_node_count += 1
            continue
        if free_ends and stray.distance(main) <= rules.projection_distance_m and all(r.origin != 'retained' for r in members):
            end = min(free_ends, key=lambda p: (p.distance(main), p.wkb_hex))
            target = nearest_points(end, main)[1]
            if end.distance(target) >= rules.minimum_segment_m:
                source = min(members, key=key)
                edges = [*edges, source.model_copy(update={'id': f'{source.id}:heal-link', 'coordinates': [end.coords[0], target.coords[0]],
                                                           'modes': ['bicycle', 'pedestrian'], 'source_road_ids': []})]
                report.reconnect_count += 1
                continue
        touches_entrance = any(stray.distance(Point(e.coordinates)) <= 1e-6 for e in entrances)
        if stray.length < 10. and not touches_entrance and all(r.origin != 'retained' for r in members):
            edges = [r for r in edges if not any(r is m for m in members)]
            report.deleted_edge_count += len(members)
            report.unresolved.append({'kind': 'dropped_isolated_stub', 'coordinates': list(stray.centroid.coords[0]), 'length_m': stray.length})
            continue
        report.unresolved.append({'kind': 'isolated_component', 'coordinates': list(stray.centroid.coords[0]), 'length_m': stray.length, 'gap_m': stray.distance(main)})
        return edges
    return edges


def cleanup_network(roads: list[NetworkRoad], entrances: list[Entrance], *,
                    obstacles=None, domain=None, rules: CleanupRules | None = None,
                    network_rules: NetworkRules | None = None):
    rules = rules or CleanupRules.from_card(); network_rules = network_rules or NetworkRules()
    if (rules.minimum_segment_m, rules.minimum_turn_deg, rules.block_min_m, rules.block_max_m) != (network_rules.minimum_segment_m, network_rules.minimum_turn_deg, network_rules.block_min_m, network_rules.block_max_m):
        raise ValueError('cleanup rule card conflicts with network rule card')
    obstacles = unary_union([]) if obstacles is None else obstacles
    fixed = sorted([r for r in roads if r.origin == 'retained'], key=key)
    report = CleanupReport(rule_card_id=rules.rule_card_id, mode_components_before=components(roads, entrances))
    edges = noded(roads)
    tag = (sorted(r.id for r in roads if r.origin != 'retained') or ['network'])[0].split(':')[0]
    edges, dropped = drop_redundant_parallels(edges, rules)
    report.redundant_parallel_count = sum(r.origin != 'retained' for r in dropped)
    edges, links = reconnect_modes(dedup(noded(edges)), rules, obstacles, domain, tag)
    report.reconnect_count += len(links)
    edges = dedup(noded(edges))
    locked = locked_nodes(edges, entrances)
    nodes = sorted({(r.layer, tuple(c)) for r in edges for c in r.coordinates} | locked)
    # Stable union-find gives full distance-connected clusters, not order-dependent pairs.
    parent = {p: p for p in nodes}
    def root(p):
        while parent[p] != p:
            p = parent[p]
        return p
    tree = STRtree([Point(p[1]) for p in nodes])
    for i, p in enumerate(nodes):
        for j in sorted(tree.query(Point(p[1]).buffer(rules.snap_tolerance_m))):
            q = nodes[j]
            if j > i and p[0] == q[0] and math.dist(p[1], q[1]) < rules.snap_tolerance_m:
                x, y = root(p), root(q); parent[max(x, y)] = min(x, y)
    groups = defaultdict(list)
    for p in nodes:
        groups[root(p)].append(p)
    for group in sorted(groups.values()):
        locks = sorted(set(group) & locked)
        if len(group) == 1:
            continue
        if len(locks) > 1:
            report.unresolved.append({'kind': 'locked_cluster', 'coordinates': [p[1] for p in locks], 'reason': 'Distinct locked anchors cannot be merged'})
        center = tuple(sum(p[1][i] for p in group)/len(group) for i in (0, 1))
        moves = {p: min(locks, key=lambda q: (math.dist(p[1], q[1]), q))[1] if locks else center for p in group if p not in locked}
        candidate = replace_nodes(edges, moves)
        if moves and admissible(edges, candidate, obstacles, domain, entrances):
            edges = candidate; report.merged_node_count += sum(p[1] != q for p, q in moves.items())
    def normalize(current):
        raw = noded(current); clean = dedup(raw)
        report.deleted_edge_count += sum(r.origin != 'retained' for r in raw)-sum(r.origin != 'retained' for r in clean)
        return clean

    def contract_short(current):
        for _ in range(rules.max_iterations):
            current = normalize(current); locks = locked_nodes(current, entrances)
            degree = defaultdict(set)
            for r in current:
                a, b = [(r.layer, tuple(c)) for c in r.coordinates]; degree[a].add(b); degree[b].add(a)
            changed = False
            for r in sorted(current, key=lambda r: (LineString(r.coordinates).length, key(r))):
                if r.origin == 'retained' or LineString(r.coordinates).length >= rules.minimum_segment_m:
                    continue
                a, b = [(r.layer, tuple(c)) for c in r.coordinates]
                if a in locks and b in locks:
                    continue
                target = a if a in locks else b if b in locks else min((a, b), key=lambda p: (-len(degree[p]), p))
                source = b if target == a else a
                candidate = replace_nodes(current, {source: target[1]})
                if admissible(current, candidate, obstacles, domain, entrances):
                    current = candidate; report.contracted_edge_count += 1; changed = True; break
            if not changed:
                break
        return current

    edges = contract_short(edges)
    # Removal is monotonic here, so this phase ends after at most len(edges) actions.
    while True:
        changed = False
        for i, j in combinations(range(len(edges)), 2):
            a, b = edges[i], edges[j]
            if a.origin == 'retained' or b.origin == 'retained' or a.layer != b.layer or set(a.modes) != set(b.modes):
                continue
            if LineString(a.coordinates).hausdorff_distance(LineString(b.coordinates)) >= rules.duplicate_distance_m:
                continue
            remove = max((i, j), key=lambda k: (LineString(edges[k].coordinates).length, key(edges[k])))
            candidate = edges[:remove]+edges[remove+1:]
            if admissible(edges, candidate, obstacles, domain, entrances):
                edges = candidate; report.deleted_edge_count += 1; changed = True; break
        if not changed:
            break
    for iteration in range(rules.max_iterations):
        report.iterations = iteration + 1
        edges = normalize(edges); changed = False
        for layer, p, i, j, angle in acute_pairs(edges, rules.minimum_turn_deg):
            degree = sum(1 for r in edges if r.layer == layer and p in map(tuple, r.coordinates))
            if degree == 2 and edges[i].origin != 'retained' and edges[j].origin != 'retained':
                # A zigzag (path doubling back on itself): replace both legs with the chord.
                far_i = next(tuple(c) for c in edges[i].coordinates if tuple(c) != p)
                far_j = next(tuple(c) for c in edges[j].coordinates if tuple(c) != p)
                chord = LineString([far_i, far_j])
                if chord.length >= rules.minimum_segment_m:
                    keep = max((i, j), key=lambda k: (LineString(edges[k].coordinates).length, key(edges[k])))
                    candidate = [r for k, r in enumerate(edges) if k not in (i, j)] + [edges[keep].model_copy(update={'coordinates': [far_i, far_j]})]
                    candidate = dedup(noded(candidate))
                    if admissible(edges, candidate, obstacles, domain, entrances):
                        edges = candidate; report.t_junction_repair_count += 1; changed = True; break
            new = [k for k in (i, j) if edges[k].origin != 'retained']
            k = min(new, key=lambda k: (LineString(edges[k].coordinates).length, key(edges[k])))
            other = edges[j if k == i else i]; shorter = edges[k]
            far = next(tuple(c) for c in shorter.coordinates if tuple(c) != p)
            line = LineString(other.coordinates); distance = line.project(Point(far)); q = tuple(line.interpolate(distance).coords[0])
            # Interior projection is essential: endpoint attachment is not a T.
            if EPS < distance < line.length-EPS and EPS < math.dist(far, q) <= rules.projection_distance_m and math.dist(far, q) >= rules.minimum_segment_m:
                candidate = edges[:k]+edges[k+1:]+[shorter.model_copy(update={'coordinates': [far, q]})]
                candidate = dedup(noded(candidate))
                if admissible(edges, candidate, obstacles, domain, entrances) and len(acute_pairs(candidate, rules.minimum_turn_deg)) < len(acute_pairs(edges, rules.minimum_turn_deg)):
                    edges = contract_short(candidate); report.t_junction_repair_count += 1; changed = True; break
            candidate = edges[:k]+edges[k+1:]
            if admissible(edges, candidate, obstacles, domain, entrances):
                edges = candidate; report.deleted_edge_count += 1; changed = True; break
        if not changed:
            break
    edges, cuts, unresolved_blocks = subdivide_blocks(dedup(noded(edges)), rules, network_rules, obstacles, domain, tag)
    report.subdivision_segment_count += len(cuts)
    report.unresolved_block.extend(unresolved_blocks)
    edges, links = reconnect_modes(dedup(noded(edges)), rules, obstacles, domain, tag+':final')
    report.reconnect_count += len(links)
    edges, closures = close_dead_ends(dedup(noded(edges)), entrances, rules, network_rules, obstacles, domain, tag)
    report.reconnect_count += len(closures)
    edges, entry_links = connect_entrances(dedup(noded(edges)), entrances, rules, obstacles, domain, tag)
    report.reconnect_count += len(entry_links)
    edges = contract_short(edges)
    edges = noded(edges); locked = locked_nodes(edges, entrances)
    for r in edges:
        if r.origin != 'retained' and LineString(r.coordinates).length < rules.minimum_segment_m:
            record = {'kind': 'short_edge', 'coordinates': r.coordinates, 'length_m': LineString(r.coordinates).length, 'road_id': r.id}
            (report.exempt_locked if all((r.layer,tuple(c)) in locked for c in r.coordinates) else report.unresolved).append(record)
    for _, p, i, j, angle in acute_pairs(edges, rules.minimum_turn_deg):
        report.unresolved.append({'kind': 'acute_angle', 'coordinates': p, 'angle_deg': angle, 'road_ids': [edges[i].id,edges[j].id]})
    # Internal retained splits never replace the immutable source records.
    edges = heal_isolated_pieces(dedup(noded(edges)), rules, report, entrances)
    result = [*fixed, *sorted([r for r in dedup(edges) if r.origin != 'retained'], key=key)]
    # Shared-corridor overlays give a footway to retained cycle-only roads; they are
    # part of the retained cross-section and must survive cleanup unchanged.
    for overlay in sorted((r for r in roads if ':shared-existing:' in r.id), key=key):
        covered = unary_union([LineString(r.coordinates) for r in result if 'pedestrian' in r.modes])
        # Restore only the missing stretches; re-adding covered stretches would
        # duplicate geometry that the syntax engine (correctly) refuses.
        for i, piece in enumerate(lines(LineString(overlay.coordinates).difference(covered))):
            if piece.length >= rules.minimum_segment_m:
                result.append(overlay.model_copy(update={'id': f'{overlay.id}:restored:{i}', 'coordinates': list(piece.coords)}))
    # Zero/near-zero new segments are never physical roads.
    result = collapse_micro_segments(result)
    result = [r if r.origin == 'retained' else r.model_copy(update={'id': 'cleanup:'+str(i)+':'+r.id.split(':node:')[0]}) for i,r in enumerate(result)]
    for block in blocks(result, domain):
        minimum, maximum, _, _ = dimensions(block)
        if maximum > rules.block_max_m and not any(math.dist(block.centroid.coords[0], u['coordinates']) < EPS for u in report.unresolved_block):
            report.unresolved_block.append({'coordinates': list(block.centroid.coords[0]), 'bounds': list(block.bounds), 'long_side_m': maximum, 'short_side_m': minimum, 'reason': 'Residual oversized block after cleanup'})
    report.mode_components_after = components(result, entrances)
    return result, report
