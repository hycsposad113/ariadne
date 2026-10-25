"""J15 block-first generator. EPSG:28992 metres; copy-only, no state writes.

Roads are derived from authored development blocks. J11/J12 modules stay
unchanged defaults. Assigned J12c quality gates are reused, never relaxed.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape
from shapely.ops import nearest_points, polylabel, unary_union

from . import multimodal_network as net
from .context_massing import (
    FAMILIES,
    S6Rules,
    difference_metrics,
    generate_massing,
    scale_check,
)
from .massing_revision import facade_segments, revision_checks, streetwall_continuity
from .network_massing_coupling import (
    WALL_TYPES,
    ClusterSelector,
    CouplingRules,
    coupling_checks,
    merged_open_spaces,
    transport_checks,
)
from .skeleton import _principal_angle
from .type_registry import generate_block_profile, generate_streetwall_profile

VERSION = 'j16b-strip-land-blocks-v2'
FACADE_TYPES = {
    'block.perimeter', 'building.courtyard_closed', 'building.l_block',
    'building.i_slab', 'building.rowhouse', 'building.industrial_hall',
    'building.point_tower', 'building.podium_tower',
}


class BlockFirstRules(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    crs: Literal['EPSG:28992'] = 'EPSG:28992'
    status: Literal['DRAFT'] = 'DRAFT'
    provenance: Literal['ASSUMED_COMMANDER'] = 'ASSUMED_COMMANDER'
    block_along_m: FiniteFloat = Field(default=80, ge=60, le=100)
    block_depth_m: FiniteFloat = Field(default=56, ge=44, le=100)
    block_min_m: FiniteFloat = Field(default=44, ge=44)
    # Commander 2026-10-09: bilateral denominator is the band that can hold two frontages.
    qualified_band_m: FiniteFloat = Field(default=40, ge=40)
    defining_edge_min: FiniteFloat = Field(default=0.8, ge=0.8, le=1)
    perimeter_outer_m: FiniteFloat = Field(default=46, ge=46)
    wing_depth_m: FiniteFloat = Field(default=12, ge=10, le=16)
    plaza_radius_m: FiniteFloat = Field(default=20, gt=0)
    green_half_width_m: FiniteFloat = Field(default=18, ge=12)
    edge_margin_m: FiniteFloat = Field(default=12, ge=3)
    max_development_streets: int = Field(default=3, ge=1, le=3)
    rule_card_ids: tuple[str, ...] = (
        'MOR-002', 'MOR-003', 'MOB-001', 'MOB-015', 'POR-005', 'PUB-004', 'SYN-002', 'SYN-011',
    )


def parts(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [p for c in getattr(g, 'geoms', []) for p in parts(c)]


def line_parts(g):
    if g.is_empty:
        return []
    if g.geom_type == 'LineString':
        return [g] if g.length > 1e-6 else []
    return [p for c in getattr(g, 'geoms', []) for p in line_parts(c)]


def _clean_coords(line):
    coords = []
    for x, y in line.coords:
        pt = (float(x), float(y))
        if coords and math.dist(coords[-1], pt) < 1e-7:
            continue
        coords.append(pt)
    return coords if len(coords) >= 2 else None


def _route(domain, a, b):
    start = (float(a.x), float(a.y)) if hasattr(a, 'x') else (float(a[0]), float(a[1]))
    end = (float(b.x), float(b.y)) if hasattr(b, 'x') else (float(b[0]), float(b[1]))
    if math.dist(start, end) < 1e-6:
        return None
    cover = domain.buffer(1e-7)
    direct = LineString([start, end])
    if cover.covers(direct):
        return direct
    start_p, end_p = Point(start), Point(end)
    polys = parts(domain) if domain.geom_type != 'Polygon' else [domain]
    for poly in sorted(polys, key=lambda p: (p.distance(start_p) + p.distance(end_p), -p.area)):
        if poly.geom_type != 'Polygon' or poly.is_empty:
            continue
        if len(poly.exterior.coords) > 80:
            poly = poly.simplify(2.0, preserve_topology=True)
            if poly.geom_type != 'Polygon' or poly.is_empty:
                continue
        try:
            return net._router(poly).route(start, end)
        except (ValueError, AttributeError):
            continue
    return None


def _buildable(site, water, retained, network_rules):
    land = site.difference(water)
    kept = unary_union(list(retained.values())) if retained else Point()
    obstacles = unary_union([
        water.buffer(network_rules.waterfront_band_m),
        kept.buffer(network_rules.retained_setback_m) if not kept.is_empty else Point(),
    ])
    domain = land.difference(obstacles)
    return land, domain, kept


def _major_entries(entrances, n=4):
    chosen = []
    for e in sorted(entrances, key=lambda row: (-row.weight, row.id)):
        if not {'pedestrian', 'bicycle'}.intersection(e.modes):
            continue
        if all(Point(e.coordinates).distance(Point(o.coordinates)) >= 40 for o in chosen):
            chosen.append(e)
        if len(chosen) == n:
            break
    return chosen


def _straighten(line, domain):
    coords = list(line.coords)
    if len(coords) < 3:
        return line
    straight = LineString([coords[0], coords[-1]])
    if domain.buffer(1e-6).covers(straight) and straight.length >= line.length * 0.6:
        return straight
    return line


def _center_in_corridor(line, domain, half_width):
    """Shift a centreline so both sides keep roughly equal buildable depth."""
    coords = list(line.coords)
    dx, dy = coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1]
    length = math.hypot(dx, dy)
    if length < 1:
        return line
    nx, ny = -dy / length, dx / length
    shifts = []
    for frac in (0.25, 0.5, 0.75):
        p = line.interpolate(frac, normalized=True)
        left = right = 0.0
        for sign, store in ((1, 'left'), (-1, 'right')):
            reach = 0.0
            for step in range(180):
                q = Point(p.x + nx * sign * (step + 1), p.y + ny * sign * (step + 1))
                if domain.covers(q):
                    reach = float(step + 1)
                else:
                    break
            if sign == 1:
                left = reach
            else:
                right = reach
        shifts.append((left - right) / 2.0)
    shift = sorted(shifts)[len(shifts) // 2]
    if abs(shift) < 1:
        return line
    moved = LineString([(x + nx * shift, y + ny * shift) for x, y in coords])
    clipped = max(line_parts(moved.intersection(domain)), key=lambda p: p.length, default=None)
    return clipped if clipped is not None and clipped.length >= line.length * 0.5 else line


def _axis_through(domain, origin, heading_rad, rules):
    ux, uy = math.cos(heading_rad), math.sin(heading_rad)
    span = max(math.sqrt(domain.area), 200)
    raw = LineString([
        (origin.x - ux * span, origin.y - uy * span),
        (origin.x + ux * span, origin.y + uy * span),
    ])
    candidates = [p for p in line_parts(raw.intersection(domain)) if p.length >= 2 * rules.block_along_m]
    if not candidates:
        candidates = [p for p in line_parts(raw.intersection(domain)) if p.length >= rules.block_min_m]
    chosen = max(candidates, key=lambda p: (p.length, p.wkb_hex), default=None)
    if chosen is None:
        return None
    return _center_in_corridor(chosen, domain, rules.block_depth_m + 8)


def _ray_depth(domain, origin, direction, limit=180):
    reach = 0.0
    for step in range(1, int(limit) + 1):
        q = Point(origin.x + direction[0] * step, origin.y + direction[1] * step)
        if domain.covers(q):
            reach = float(step)
        else:
            break
    return reach


def _section_points(domain, heading, step=20.0, prefer=None):
    """Midpoints of successive cross-sections, longest buildable piece first."""
    polys = [p for p in parts(domain) if p.geom_type == 'Polygon' and p.area > 1]
    if not polys:
        return []
    poly = max(polys, key=lambda p: p.area)
    ux, uy = math.cos(heading), math.sin(heading)
    nx, ny = -uy, ux
    c = poly.centroid
    ts = [((x - c.x) * ux + (y - c.y) * uy) for x, y in poly.exterior.coords]
    t = min(ts) + step
    pts = []
    while t < max(ts) - step / 2:
        origin = (c.x + ux * t, c.y + uy * t)
        cross = LineString([(origin[0] - nx * 2500, origin[1] - ny * 2500), (origin[0] + nx * 2500, origin[1] + ny * 2500)])
        segs = [s for s in line_parts(cross.intersection(domain)) if s.length >= 12]
        if segs:
            seg = max(segs, key=lambda s: (s.length, s.wkb_hex))
            mid = seg.interpolate(0.5, normalized=True)
            if prefer is not None and not prefer.is_empty:
                ranked = sorted(segs, key=lambda s: (s.intersection(prefer).length, s.length, s.wkb_hex), reverse=True)
                piece_parts = [p for p in line_parts(ranked[0].intersection(prefer)) if p.length >= 16]
                if piece_parts:
                    piece = max(piece_parts, key=lambda s: s.length)
                    mid = piece.interpolate(0.5, normalized=True)
            pts.append((float(mid.x), float(mid.y)))
        t += step
    return pts


def _corridor_lines(domain, heading, step=20.0, prefer=None):
    """Centreline pieces through successive cross-sections. Metres, not a Syntax claim.

    Pieces separated by the canal are joined when a route stays inside buildable
    land. The longest continuous piece is kept when no route exists.
    """
    pts = _section_points(domain, heading, step, prefer)
    if len(pts) < 2:
        return []
    groups = [[pts[0]]]
    for pt in pts[1:]:
        if math.dist(groups[-1][-1], pt) > 70:
            groups.append([pt])
        else:
            groups[-1].append(pt)
    groups = [g for g in groups if len(g) >= 2]
    if not groups:
        return []
    stitched = [LineString(groups[0])]
    for group in groups[1:]:
        nxt = LineString(group)
        bridge = _route(domain, Point(stitched[-1].coords[-1]), Point(nxt.coords[0]))
        gap = Point(stitched[-1].coords[-1]).distance(Point(nxt.coords[0]))
        if bridge is not None and bridge.length <= max(120.0, gap * 2.5):
            stitched[-1] = LineString(list(stitched[-1].coords) + list(bridge.coords)[1:] + list(nxt.coords)[1:])
        else:
            stitched.append(nxt)
    return [item.simplify(6.0) for item in stitched if item.length >= 70]


def corridor_axis(domain, heading, step=20.0, prefer=None):
    """Longest buildable centreline. Metres, not a Syntax claim."""
    lines = _corridor_lines(domain, heading, step, prefer)
    return max(lines, key=lambda item: item.length) if lines else None


def _frame(line, distance):
    a = line.interpolate(max(0.0, distance - 1.0))
    b = line.interpolate(min(line.length, distance + 1.0))
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy) or 1.0
    return (dx / length, dy / length), (-dy / length, dx / length)


def side_depths(line, domain, distance, road_half):
    origin = line.interpolate(min(max(distance, 0.0), line.length))
    _tangent, normal = _frame(line, distance)
    left = max(0.0, _ray_depth(domain, origin, normal) - road_half)
    right = max(0.0, _ray_depth(domain, origin, (-normal[0], -normal[1])) - road_half)
    return left, right


def frontage_class(left, right, rules):
    """Width class for one cross-section. `left`/`right` are buildable depths beyond the street."""
    band = left + right
    if left < 12 or right < 12 or band < rules.qualified_band_m:
        return 'single'
    if left >= rules.perimeter_outer_m and right >= rules.perimeter_outer_m and band >= 105:
        return 'both_perimeter'
    if band >= 60 and (left >= rules.perimeter_outer_m or right >= rules.perimeter_outer_m):
        return 'mixed'
    return 'double_bar'


def _intervals(pieces):
    if not pieces:
        return []
    cover = unary_union(pieces)
    geoms = [cover] if cover.geom_type == 'LineString' else list(getattr(cover, 'geoms', []))
    return [(min(g.bounds[0], g.bounds[2]), max(g.bounds[0], g.bounds[2])) for g in geoms if g.length > 1e-6]


def _covered(intervals, start, end):
    return sum(max(0.0, min(end, hi) - max(start, lo)) for lo, hi in intervals)


def frontage_assessment(lines, buildings, domain, rules=None, road_half=3.75, step=5.0):
    """Qualified bilateral ratio plus defining-edge ratio.

    Bilateral denominator is only the development length whose two sides can
    each hold a frontage and together reach the 40 m band. Threshold stays 0.6.
    Defining edge counts every development metre with at least one facing facade.
    """
    rules = rules or BlockFirstRules()
    eligible = covered_both = defined = total = 0.0
    for line in lines:
        if line is None or line.is_empty or line.length < 1:
            continue
        total += line.length
        facade = {-1: [], 1: []}
        for building in buildings:
            if building.get('type_id') not in FACADE_TYPES:
                continue
            geom = building['geometry']
            polys = [geom] if geom.geom_type == 'Polygon' else [p for p in getattr(geom, 'geoms', []) if p.geom_type == 'Polygon']
            for poly in polys:
                coords = list(poly.exterior.coords)
                for a, b in zip(coords, coords[1:]):
                    edge = LineString([a, b])
                    if edge.length < 1:
                        continue
                    mid = edge.interpolate(0.5, normalized=True)
                    nearest = nearest_points(mid, line)[1]
                    distance = line.project(nearest)
                    tangent, _normal = _frame(line, distance)
                    origin = line.interpolate(distance)
                    side = tangent[0] * (mid.y - origin.y) - tangent[1] * (mid.x - origin.x)
                    if abs(side) > 18 or abs(side) < 0.01:
                        continue
                    ex, ey = b[0] - a[0], b[1] - a[1]
                    if abs(ex * tangent[0] + ey * tangent[1]) / (edge.length) < math.sqrt(0.5):
                        continue
                    start,end=sorted((line.project(Point(a)),line.project(Point(b))))
                    if end-start <= 1e-6:
                        continue
                    facade[1 if side > 0 else -1].append(LineString([(start,0),(end,0)]))
        left_i = _intervals(facade[1])
        right_i = _intervals(facade[-1])
        cursor = 0.0
        while cursor < line.length - 1e-6:
            nxt = min(line.length, cursor + step)
            left, right = side_depths(line, domain, (cursor + nxt) / 2, road_half)
            kind = frontage_class(left, right, rules)
            both = _covered(left_i, cursor, nxt) > 0 and _covered(right_i, cursor, nxt) > 0
            one = _covered(left_i, cursor, nxt) > 0 or _covered(right_i, cursor, nxt) > 0
            if kind != 'single':
                eligible += nxt - cursor
                if both:
                    covered_both += nxt - cursor
            if one:
                defined += nxt - cursor
            cursor = nxt
    return dict(
        qualified_bilateral_ratio=(covered_both / eligible) if eligible else 0.0,
        defining_edge_ratio=(defined / total) if total else 0.0,
        eligible_length_m=eligible,
        bilateral_length_m=covered_both,
        defining_length_m=defined,
        development_length_m=total,
        bilateral_gate=eligible > 0 and (covered_both / eligible) >= 0.6,
        defining_gate=total > 0 and (defined / total) >= rules.defining_edge_min,
    )


def _row_length(available):
    for length in range(int(min(72, available)), 31, -1):
        if any(5.4 <= length / n <= 7.2 for n in range(6, 21)):
            return float(length)
    return None


def _use_at(point, zones):
    matches = [z for z in zones if shape(z['geometry']).covers(point)]
    zone = matches[0] if matches else (min(zones, key=lambda z: (shape(z['geometry']).distance(point), z['zone_id'])) if zones else None)
    if zone is None:
        return 'residential', None
    label = zone['target_use'].lower()
    if any(v in label for v in ('maker', 'recycle', 'energy')):
        use = 'manufacturing'
    elif 'residential' in label:
        use = 'residential'
    elif 'office' in label:
        use = 'office'
    else:
        use = 'mixed'
    return use, zone['zone_id']


def strip_axes(domain, family, *, sample_step_m=10.0, segment_m=80.0):
    """Pure strip extraction in projected metres, with no DB/tool authority.

    Track *every* cross-section interval of each land component. Matching must
    overlap and stay within that component; no centreline bridges a canal or
    retained obstacle. Offset regimes use >=60m windows, interpolating offsets
    across windows instead of introducing discontinuous street jumps.
    """
    from shapely.affinity import rotate
    if family not in FAMILIES:
        raise ValueError('unknown S6 strategy')
    if sample_step_m != 10 or not 60 <= segment_m <= 90:
        raise ValueError('J16 requires 10m samples and 60–90m cross-connections')
    axes, sections, strip_records = [], [], []
    components = sorted(parts(domain), key=lambda p: (-p.area, p.wkb_hex))
    for component in components:
        if component.area < 600:
            continue
        ring = list(component.minimum_rotated_rectangle.exterior.coords)
        a,b = max(zip(ring,ring[1:]), key=lambda ab: math.dist(*ab))
        angle = math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
        # Canonical direction makes station IDs stable for reversed rings.
        angle = ((angle + 90) % 180) - 90
        local = rotate(component,-angle,origin=(0,0))
        lo,ylo,hi,yhi = local.bounds
        tracks, active = [], []
        xs = [lo+1+i*sample_step_m for i in range(int((hi-lo-2)//sample_step_m)+1)]
        if not xs or hi-xs[-1] > 1.01:
            xs.append(hi-1)
        for x in xs:
            cuts = sorted(line_parts(LineString([(x,ylo-1),(x,yhi+1)]).intersection(local)),key=lambda g:g.bounds[1])
            nxt,used = [],set()
            for cut in cuts:
                low,high = cut.bounds[1],cut.bounds[3]
                if high-low < 20:
                    continue
                matches = [(abs((low+high)/2-(tr[-1][1]+tr[-1][2])/2),i,tr) for i,tr in enumerate(active)
                           if i not in used and min(high,tr[-1][2])-max(low,tr[-1][1]) > 0]
                if matches:
                    _,i,tr = min(matches,key=lambda q:q[0]); used.add(i)
                else:
                    tr=[];tracks.append(tr)
                tr.append((x,low,high));nxt.append(tr)
            active=nxt
        for tr in tracks:
            if len(tr)<2 or tr[-1][0]-tr[0][0]<60:
                continue
            if 90 < tr[-1][0]-tr[0][0] < 120:
                # No partition can satisfy both bounds; the tail remains park.
                tr=[q for q in tr if q[0]-tr[0][0]<=90]
            strip_id=f'{family}-strip-{len(strip_records)}'
            coords=[]
            # A window can contain tapering widths; use its minimum, never an
            # average that invents clearance at a narrow section.
            count=max(1,min(int((tr[-1][0]-tr[0][0])/60),math.ceil((tr[-1][0]-tr[0][0])/segment_m)))
            window=(tr[-1][0]-tr[0][0])/count
            regimes=[]
            for k in range(count):
                chunk=[q for q in tr if k*window <= q[0]-tr[0][0] <= (k+1)*window]
                width=min(q[2]-q[1] for q in chunk)
                kind='both_perimeter' if width>=105 else 'mixed' if width>=60 else 'double_bar' if width>=40 else 'single'
                regimes.append((tr[0][0]+(k+.5)*window,kind))
            offsets=[]
            for x,low,high in tr:
                width=high-low
                kind=regimes[min(count-1,int((x-tr[0][0])/window))][1]
                # Reserve >=12m on narrow side; remainder is the >=44m side
                # when the actual width permits (60m itself cannot fit 44+15+12).
                target=low+22 if kind=='mixed' else (low+high)/2
                if kind=='single':target=low+3
                offsets.append(target)
                sections.append(dict(strip_id=strip_id,station_m=x-tr[0][0],width_m=width,
                                     left_depth_m=high-target-7.5,right_depth_m=target-low-7.5,**{'class':kind}))
            # Limit lateral change to 1:4; smooth geometry only within land.
            smooth=[]
            for i,((x,low,high),y) in enumerate(zip(tr,offsets)):
                if smooth:y=max(smooth[-1][1]-(x-smooth[-1][0])/4,min(y,smooth[-1][1]+(x-smooth[-1][0])/4))
                y=max(low+3,min(high-3,y));smooth.append((x,y))
            line=rotate(LineString(smooth),angle,origin=(0,0))
            pieces=[g for g in line_parts(line.intersection(component)) if g.length>=60]
            for j,piece in enumerate(pieces):
                single=all(kind=='single' for _,kind in regimes)
                role='path' if single else 'service' if family=='green_service' else 'main'
                axes.append(dict(id=strip_id+f'-{j}',strip_id=strip_id,role=role,geometry=piece,
                    width_m=3.0 if single else 15.0,segment_m=window,
                    intent_zh={'radial':'向心：入口與中心節點優先填量','axial':'軸線：主帶沿街優先填量',
                    'grid':'網格：多帶均衡配置與橫向滲透','green_service':'綠廊：沿帶服務街，保留中央未建地'}[family]))
            strip_records.append(dict(id=strip_id,heading_deg=angle,length_m=tr[-1][0]-tr[0][0],window_m=window))
            # Cross-connections stop at the land edge; bridge connectivity is
            # provided only by retained roads, never an invented water crossing.
            for k in range(1,count):
                x=tr[0][0]+k*window
                cross=rotate(LineString([(x,ylo-1),(x,yhi+1)]),angle,origin=(0,0))
                centre=rotate(Point(x,offsets[min(len(offsets)-1,round(k*window/sample_step_m))]),angle,origin=(0,0))
                cut=min(line_parts(cross.intersection(component)),key=lambda g:g.distance(centre),default=None)
                if cut is not None:
                    axes.append(dict(id=strip_id+f'-cross-{k}',role='branch',geometry=cut,width_m=3.0,
                                     intent_zh='橫向步行＋自行車連接：對齊帶內街廓與水岸'))
    return axes,dict(sample_step_m=sample_step_m,sections=sections,strips=strip_records,
                     centre=mapping(domain.centroid),plaza=None,green=None,green_axis=None,heading_deg=None,entry_ids=[])


def development_axes(family, site, water, retained, entrances, network_rules, rules=None, zones=(), fixed_roads=()):
    rules = rules or BlockFirstRules()
    _land,domain,_kept=_buildable(site,water,retained,network_rules)
    if fixed_roads:
        domain=domain.difference(unary_union([LineString(r.coordinates).buffer(r.width_m/2+1) for r in fixed_roads if r.layer==0]))
    if domain.is_empty:return [],dict(reason_zh='無可建造土地')
    green_axis=None;green=None
    if family=='green_service':
        longest=max(parts(domain),key=lambda g:g.area)
        heading=math.radians(_principal_angle(longest))
        green_axis=corridor_axis(longest,heading,step=10)
        if green_axis is not None:
            green=green_axis.buffer(rules.green_half_width_m,cap_style=2).intersection(domain)
            domain=domain.difference(green)
    axes,meta=strip_axes(domain,family,segment_m=min(90,rules.block_along_m))
    meta['entry_ids']=[e.id for e in _major_entries(entrances)]
    if family=='green_service':
        meta['green']=mapping(green) if green is not None else None
        meta['green_axis']=mapping(green_axis) if green_axis is not None else None
        meta['cross_connections']=[{**a,'geometry':mapping(a['geometry'])} for a in axes if a['role']=='branch']
        axes=[a for a in axes if a['role']!='branch']
    return axes,meta


def _chord_deviation(line, start_m, along):
    end = min(line.length, start_m + along)
    chord = LineString([line.interpolate(start_m), line.interpolate(end)])
    if chord.length < 1:
        return 0.0
    return max(line.interpolate(start_m + (end - start_m) * i / 6).distance(chord) for i in range(1, 6))


def _rectangle_along(axis, start_m, along, depth, side, road_half):
    a = axis.interpolate(start_m)
    b = axis.interpolate(min(start_m + along, axis.length))
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy)
    if length < 8:
        return None
    ux, uy = dx / length, dy / length
    nx, ny = -uy * side, ux * side
    inner = road_half
    outer = road_half + depth
    ring = [
        (a.x + nx * inner, a.y + ny * inner),
        (b.x + nx * inner, b.y + ny * inner),
        (b.x + nx * outer, b.y + ny * outer),
        (a.x + nx * outer, a.y + ny * outer),
    ]
    poly = Polygon(ring)
    return poly if poly.is_valid and poly.area > 0 else None


def _profile_for(raw, kind, rules):
    if kind == 'perimeter':
        return generate_streetwall_profile(raw, wing_depth_m=rules.wing_depth_m, setback_m=1)
    if kind == 'rowhouse':
        return generate_block_profile('building.rowhouse', raw, wing_depth_m=12)
    if kind == 'l':
        return generate_block_profile('building.l_block', raw, wing_depth_m=rules.wing_depth_m)
    if kind == 'hall':
        return generate_block_profile('building.industrial_hall', raw, wing_depth_m=24)
    if kind == 'point':
        return generate_block_profile('building.point_tower', raw, wing_depth_m=20)
    short, _long = _rect_size(raw)
    return generate_block_profile('building.i_slab', raw, wing_depth_m=short)


def _candidate_kinds(depth, use):
    if use == 'manufacturing' and depth >= 26:
        return [('hall', 24, 40)]
    if depth >= 46 and use != 'manufacturing':
        return [('perimeter', min(56.0, depth), 72.0), ('rowhouse', 12, 63)]
    if use in ('residential', 'mixed') and depth >= 12:
        return [('rowhouse', 12, 63), ('l', 28, 42)]
    if depth >= 30 and use != 'manufacturing':
        return [('l', 28, 42), ('slab', 14, 48)]
    if use == 'office' and depth >= 18:
        return [('slab', 16, 48)]
    if depth >= 12:
        return [('slab', 12, 48)]
    return []


def _estimate_gfa(block, dakpark):
    area = block['profile'].geometry.area
    if block['preferred_type'] == 'building.industrial_hall':
        return area
    floors = 3.2 if dakpark is not None and block['profile'].geometry.distance(dakpark) <= 100 else 5.0
    return area * floors


def thin_blocks(blocks, budget, dakpark=None):
    """Drop spare pairs until estimated new GFA fits under the FAR cap, keeping both sides."""
    if not budget or budget <= 0:
        return blocks
    rows = list(blocks)
    target = budget

    def estimate(chosen):
        return sum(_estimate_gfa(b, dakpark) for b in chosen)

    def zone_ids(chosen):
        return {b.get('zone_id') for b in chosen if b.get('zone_id')}

    guard = 0
    while estimate(rows) > target and guard < 400:
        guard += 1
        keys = []
        for block in rows:
            if block.get('pair_key') not in keys:
                keys.append(block['pair_key'])
        removed = False
        for key in reversed(keys):
            nxt = [b for b in rows if b.get('pair_key') != key]
            kept_types = {b['preferred_type'] for b in nxt}
            if 'building.industrial_hall' not in kept_types and any(b['preferred_type'] == 'building.industrial_hall' for b in rows):
                continue
            if 'building.point_tower' not in kept_types and any(b['preferred_type'] == 'building.point_tower' for b in rows):
                continue
            if len(kept_types) < min(4, len({b['preferred_type'] for b in rows})):
                continue
            if zone_ids(nxt) != zone_ids(rows):
                continue
            if len({b['axis_id'] for b in nxt}) < len({b['axis_id'] for b in rows}):
                continue
            rows = nxt
            removed = True
            break
        if not removed:
            break
    return rows


def place_blocks(axes, site, water, retained, network_rules, rules=None, zones=(), gfa_budget=None, dakpark=None, fixed_roads=()):
    """Repeated complete J12 profiles within the 60–90m strip street blocks.

    Candidate capacity is retained until measured floor plates reach the FAR
    budget. No estimate-based thinning before context floors are available.
    """
    rules=rules or BlockFirstRules()
    _land,domain,_kept=_buildable(site,water,retained,network_rules)
    masks=[LineString(r.coordinates).buffer(r.width_m/2+1) for r in fixed_roads if r.layer==0]
    width_domain=domain.difference(unary_union(masks)) if masks else domain
    masks.extend(a['geometry'].buffer(a.get('width_m',15)/2+.5,cap_style=2) for a in axes if a['role']=='branch')
    if masks:domain=domain.difference(unary_union(masks))
    occupied=Point();blocks=[]
    uses={'manufacturing':'Manufacturing','residential':'Residential','office':'Office','mixed':'Mixed'}
    for axis in axes:
        if axis['role']=='branch':continue
        line=axis['geometry'];half=axis.get('width_m',15)/2+1
        segment=axis.get('segment_m',rules.block_along_m)
        cursor=3.0;station=0
        while cursor<line.length-32:
            end=min(cursor+segment-6,line.length-3)
            available=end-cursor
            if available<32:break
            placed=[]
            left,right=side_depths(line,width_domain,cursor+available/2,half)
            sides=((1,left),(-1,right))
            if axis['role']=='path':sides=(max(sides,key=lambda q:q[1]),)
            for side,_depth in sides:
                tangent,normal=_frame(line,cursor+available/2)
                origin=line.interpolate(cursor+available/2)
                probe=Point(origin.x+normal[0]*side*(half+8),origin.y+normal[1]*side*(half+8))
                use,zone_id=_use_at(probe,zones)
                depth=min(side_depths(line,width_domain,cursor+available*f,half)[0 if side==1 else 1] for f in (.08,.25,.5,.75,.92))
                options=_candidate_kinds(depth,use)
                # Complete types respond to programme; repeat full street blocks.
                if depth>=46 and use!='manufacturing':
                    options=[('perimeter',min(56,depth-1),min(72,available)),('l',min(48,depth-1),min(60,available))]+options
                if use!='manufacturing' and depth>=20 and not any(b['preferred_type']=='building.point_tower' for b in blocks) and station==1:
                    options=[('point',20,22)]+options
                if use=='office' and depth>=20:
                    options=[('point',20,22)]+options if station==0 else [('slab',14,min(66,available))]+options
                for kind,depth_m,along in options:
                    along=min(along,available)
                    if kind=='rowhouse':along=_row_length(along) or 0
                    if along<30 and kind!='point':continue
                    if kind=='perimeter' and along<46:continue
                    raw=_rectangle_along(line,cursor,along,depth_m,side,half)
                    if raw is None or not domain.buffer(1e-6).covers(raw):
                        raw=None
                        for cut in range(6,int(along-30),6):
                            shorter=along-cut
                            if kind=='rowhouse':shorter=_row_length(shorter) or 0
                            if shorter<32 or (kind=='perimeter' and shorter<46):continue
                            trial=_rectangle_along(line,cursor,shorter,depth_m,side,half)
                            if trial is not None and domain.buffer(1e-6).covers(trial):
                                raw=trial;along=shorter;break
                        if raw is None:continue
                    if not occupied.is_empty and raw.intersects(occupied.buffer(.4)):continue
                    try:profile=_profile_for(raw,kind,rules)
                    except ValueError:continue
                    actual_use,zone_id=_use_at(raw.representative_point(),zones)
                    if not scale_check(profile,uses[actual_use])['valid']:continue
                    blocks.append(dict(id=f"{axis['id']}-block-{station}-s{side}",axis_id=axis['id'],side=side,
                        geometry=raw,profile=profile,preferred_type=profile.type_id,pair_key=f"{axis['id']}:{station}",zone_id=zone_id,use=actual_use))
                    occupied=unary_union([occupied,raw]);placed.append(along);break
            station+=1;cursor+=(max(placed)+6 if placed else 5)
    return blocks


def strip_land_blocks(axes, roads, site, water, retained, network_rules, *, zones=(), public=()):
    """Pure J16b land subdivision: road surfaces cut land, never building masks.

    Every returned polygon is a complete connected remainder of the buildable
    strip. Small pieces remain open space. Width class is only a J12 preference;
    no profile is fabricated and no minimum building dimension is reduced.
    """
    domain = _buildable(site, water, retained, network_rules)[1]
    obstacles = [LineString(r.coordinates).buffer(r.width_m / 2 + .001, join_style=2)
                 for r in roads if r.layer == 0]
    obstacles += list(public)
    obstacles += [g.buffer(network_rules.retained_setback_m + .001) for g in retained.values()]
    domain = domain.difference(unary_union(obstacles))
    frontages = [a for a in axes if a['role'] != 'branch']
    blocks = []
    for polygon in sorted(parts(domain), key=lambda g: (g.bounds, g.wkb_hex)):
        # GEOS overlay roundoff at oblique source edges must not escape site.
        if not site.covers(polygon):
            polygon = polygon.buffer(-1e-7, join_style=2)
        if polygon.geom_type != 'Polygon':
            continue
        if polygon.area < 600 or not frontages:
            continue
        axis = min(frontages, key=lambda a: (polygon.distance(a['geometry']), a['id']))
        line = axis['geometry']
        station = line.project(polygon.representative_point())
        _, normal = _frame(line, station)
        origin = line.interpolate(station)
        point = polygon.representative_point()
        side = 1 if (point.x-origin.x)*normal[0]+(point.y-origin.y)*normal[1] >= 0 else -1
        short, _ = _rect_size(polygon)
        kind = 'both_perimeter' if short >= 44 else 'mixed' if short >= 24 else 'double_bar' if short >= 14 else 'single'
        preferences = {
            'both_perimeter': ('block.perimeter','building.courtyard_closed','building.l_block'),
            'mixed': ('building.l_block','building.i_slab'),
            'double_bar': ('building.i_slab','building.rowhouse'),
            'single': ('building.rowhouse','building.i_slab'),
        }[kind]
        use, zone = _use_at(point, zones)
        blocks.append(dict(id=f"{axis['id']}-land-{len(blocks)}", axis_id=axis['id'],
                           side=side, geometry=polygon, zone_id=zone, use=use,
                           width_class=kind, type_preferences=preferences,
                           subdivision_method='BUILDABLE_LAND_MINUS_ROAD_SURFACES'))
    return blocks


def _rect_size(polygon):
    ring = list(polygon.minimum_rotated_rectangle.exterior.coords)
    lengths = [math.dist(a, b) for a, b in zip(ring, ring[1:])]
    return min(lengths), max(lengths)


def _make_road(line, identity, network_rules, hierarchy, service=False, park=False):
    coords = _clean_coords(line)
    if coords is None or LineString(coords).length < network_rules.minimum_segment_m:
        return None
    return net._road(LineString(coords), identity, network_rules, hierarchy, service, park)


def _link_mode(roads, domain, mode, family, network_rules, *, service, fallback=None):
    from .network_massing_coupling import connected_components
    added = []
    for _ in range(len(roads)):
        _rs, gs, comps = connected_components([*roads, *added], mode)
        if len(gs) <= 1 or len(comps) <= 1:
            break
        geoms = [unary_union([gs[i] for i in comp]) for comp in comps]
        pairs = []
        for i, left in enumerate(geoms):
            for right in geoms[:i]:
                a, b = nearest_points(left, right)
                gap = a.distance(b)
                if 1e-6 < gap <= 800:
                    pairs.append((gap, a, b))
        pairs.sort(key=lambda item: item[0])
        route = None
        for _gap, a, b in pairs[:8]:
            candidate = _route(domain, a, b)
            if candidate is not None and domain.buffer(2).covers(candidate):
                route = candidate
                break
            if fallback is not None:
                candidate = _route(fallback, a, b)
                if candidate is not None and fallback.buffer(2).covers(candidate):
                    route = candidate
                    break
        if route is None:
            break
        road = _make_road(route, f'{family}-join-{mode}-{len(added)}', network_rules, 'service', service=service, park=not service)
        if road is None:
            break
        if not service:
            road = road.model_copy(update={'modes': ['pedestrian', 'bicycle'], 'park_shared': True, 'access': 'public'})
        added.append(road)
    return added


def _extend_connection(domain, route, support, minimum_m):
    """Keep the entry fixed, move its target along existing support to >= minimum.

    Opt-in J17 repair; no minimum is changed and no retained road is removed.
    """
    endpoint=Point(route.coords[-1]);start=Point(route.coords[0]);candidates=[]
    for line in line_parts(support):
        if line.distance(endpoint)>1e-4:continue
        station=line.project(endpoint)
        for offset in (minimum_m, -minimum_m, 2*minimum_m, -2*minimum_m):
            value=max(0.,min(line.length,station+offset));target=line.interpolate(value)
            proposed=_route(domain,start,target)
            if proposed is not None and proposed.length>=minimum_m and domain.buffer(1e-7).covers(proposed):candidates.append(proposed)
    return min(candidates,key=lambda g:(g.length,g.wkb_hex),default=None)


def _ped_twins(roads, site, network_rules, family):
    ped = unary_union([LineString(r.coordinates) for r in roads if 'pedestrian' in r.modes])
    twins = []
    for road in roads:
        if 'bicycle' not in road.modes:
            continue
        gap = LineString(road.coordinates).intersection(site).difference(ped.buffer(network_rules.bicycle_adjacency_m - 0.05))
        for i, part in enumerate(line_parts(gap)):
            if part.length < network_rules.minimum_segment_m:
                continue
            for side in ('left', 'right'):
                try:
                    shifted = part.parallel_offset(3.0, side, join_style=2)
                except (ValueError, OSError):
                    continue
                piece = max(line_parts(shifted.intersection(site.buffer(0.5))), key=lambda p: p.length, default=None)
                if piece is None or piece.length < network_rules.minimum_segment_m:
                    continue
                twin = _make_road(piece, f'{family}-ped-twin-{road.id}-{i}', network_rules, 'branch', service=False, park=True)
                if twin is None:
                    continue
                twins.append(twin.model_copy(update={'modes': ['pedestrian'], 'park_shared': True, 'width_m': 2.5, 'width_class': 'shared'}))
                break
    return twins


def _motor_ribbon(site, water, roads, blocks, entrances):
    """Car links stay beside streets, block edges, and the site boundary."""
    pieces = []
    for road in roads:
        if 'motor_vehicle' not in road.modes:
            continue
        pieces.append(LineString(road.coordinates).buffer(max(road.width_m / 2 + 6.0, 8.0), cap_style=2, join_style=2))
    pieces.append(site.boundary.buffer(10.0))
    for entrance in entrances:
        if 'motor_vehicle' in entrance.modes:
            pieces.append(Point(entrance.coordinates).buffer(18.0))
    ribbon = unary_union(pieces).intersection(site.difference(water).buffer(1.0))
    if blocks:
        ribbon = ribbon.difference(unary_union([b['geometry'] for b in blocks]).buffer(network_rules_width(roads) + 1.2))
    return ribbon if ribbon is not None and not ribbon.is_empty else site.difference(water)


def network_rules_width(roads):
    return max((r.width_m / 2 for r in roads if 'motor_vehicle' in r.modes), default=4.0) + 0.6


def roads_from_structure(axes, blocks, site, water, retained, entrances, fixed_roads, network_rules, rules=None, family='axial', meta=None, repair_multimodal=False, reserved_parks=()):
    """Development axes become streets; other block edges are slow/shared paths."""
    rules = rules or BlockFirstRules()
    land, domain, kept = _buildable(site, water, retained, network_rules)
    roads = list(fixed_roads)
    development = []
    for axis in axes:
        service = axis['role'] == 'service' or (family == 'green_service' and axis['role'] != 'branch')
        hierarchy = 'service' if service else 'main' if axis['role'] == 'main' else 'branch'
        road = _make_road(axis['geometry'], axis['id'], network_rules, hierarchy, service=service, park=axis['role'] == 'branch')
        if road is None:
            continue
        if axis['role'] in ('main', 'service'):
            road = road.model_copy(update={
                'modes': ['bicycle', 'motor_vehicle', 'pedestrian'],
                'access': 'service_only',
                'width_m': axis.get('width_m', network_rules.main_shared_width_m),
                'width_class': 'main_shared',
                'semantics_provenance': 'J16 DRAFT; 發展軸線步行＋自行車優先，汽車僅進出／30km/h 服務',
                'rule_card_ids': ['MOB-001', 'MOB-015', 'POR-006'],
                'active_frontage_candidate_sides': 'both',
            })
        if axis['role'] in ('path','branch'):
            road=road.model_copy(update={'width_m':axis.get('width_m',3),'modes':['pedestrian','bicycle'],'park_shared':True,'access':'public'})
        roads.append(road)
        if axis['role'] not in ('branch', 'path'):
            development.append(dict(
                road_id=road.id,
                geometry=mapping(axis['geometry']),
                length_m=axis['geometry'].length,
                source_origin='new',
                intent_zh=axis['intent_zh'],
                pair_gfa_m2=0,
                block_indices=[],
            ))
    footprints = unary_union([b['geometry'] for b in blocks]) if blocks else Point()
    clearance = max(network_rules.main_shared_width_m, network_rules.service_width_m) / 2 + 0.8
    free = land.difference(footprints.buffer(clearance)) if not footprints.is_empty else land
    motor_free=free.difference(unary_union(reserved_parks).buffer(clearance)) if reserved_parks else free
    if meta and meta.get('green_axis'):
        green_road = _make_road(shape(meta['green_axis']), f'{family}-green-axis', network_rules, 'branch', service=False, park=True)
        if green_road is not None:
            roads.append(green_road.model_copy(update={'park_shared': True, 'modes': ['bicycle', 'pedestrian']}))
    for axis in axes:
        if axis['role'] == 'branch':
            continue
        line = axis['geometry']
        for side_name, side in (('left', 1), ('right', -1)):
            group = [b for b in blocks if b.get('axis_id') == axis['id'] and b.get('side') == side and b.get('preferred_type') == 'block.perimeter' and b['geometry'].geom_type == 'Polygon']
            if not group:
                continue
            far = max(line.distance(Point(xy)) for b in group for xy in b['geometry'].exterior.coords)
            try:
                offset = line.parallel_offset(far + network_rules.service_width_m / 2 + 0.8, side_name, join_style=2)
            except (ValueError, OSError):
                continue
            for j, part in enumerate(line_parts(offset.intersection(free))):
                if part.length < 20:
                    continue
                # Front street already touches the block, so fire distance is the near edge.
                # A second car lane behind the court would cut the park; keep this edge walking and cycling.
                service = _make_road(part, f"{axis['id']}-rear-{side_name}-{j}", network_rules, 'branch', service=False, park=True)
                if service is not None:
                    roads.append(service.model_copy(update={'modes': ['pedestrian', 'bicycle'], 'park_shared': True, 'access': 'public'}))
    # Only existing retained corridors can bridge land components or extend
    # beyond the site; no new water crossing is introduced by the router.
    retained_corridors=unary_union([LineString(r.coordinates).buffer(r.width_m/2,cap_style=2) for r in fixed_roads if r.layer==0])
    free=unary_union([free,retained_corridors]).difference(kept.buffer(clearance)) if not kept.is_empty else unary_union([free,retained_corridors])
    ribbon = _motor_ribbon(site, water, roads, blocks, entrances)
    if reserved_parks:
        ribbon=ribbon.difference(unary_union(reserved_parks).buffer(clearance))
    motor_free=free.difference(unary_union(reserved_parks).buffer(clearance)) if reserved_parks else free
    roads.extend(_link_mode(roads, ribbon, 'motor_vehicle', family, network_rules, service=True, fallback=motor_free))
    for e in entrances:
        p = Point(e.coordinates)
        for mode, service in (('motor_vehicle', True), ('pedestrian', False), ('bicycle', False)):
            if mode not in e.modes:
                continue
            support = unary_union([LineString(r.coordinates) for r in roads if mode in r.modes])
            if support.is_empty or p.distance(support) <= 1e-4:
                continue
            target = nearest_points(p, support)[1]
            route_domain = unary_union([ribbon,motor_free]) if service else free
            route = _route(route_domain, p, target)
            if route is None:
                continue
            if repair_multimodal and route.length<network_rules.minimum_segment_m:
                route=_extend_connection(route_domain,route,support,network_rules.minimum_segment_m)
                if route is None:continue
            added = _make_road(route, f'entry-link-{mode}-{e.id}', network_rules, 'branch', service=service, park=not service)
            if added is None:
                continue
            if not service:
                added = added.model_copy(update={'park_shared': True, 'modes': ['bicycle', 'pedestrian'] if mode == 'bicycle' else ['pedestrian', 'bicycle']})
            roads.append(added)
    roads.extend(_ped_twins(roads, site, network_rules, family))
    roads.extend(_link_mode(roads, free, 'pedestrian', family, network_rules, service=False))
    roads.extend(_link_mode(roads, free, 'bicycle', family, network_rules, service=False))
    additions, failures = [], []
    for mode in ('pedestrian', 'bicycle'):
        lines = [LineString(r.coordinates).intersection(land.buffer(1e-7)) for r in [*roads, *additions] if mode in r.modes and r.layer == 0]
        bridges, errors = net.connect_support(lines, free, network_rules)
        failures.extend(mode + ':' + e for e in errors)
        for i, bridge in enumerate(bridges):
            if repair_multimodal and bridge.length<network_rules.minimum_segment_m:
                bridge=_extend_connection(free,bridge,unary_union(lines),network_rules.minimum_segment_m)
                if bridge is None:
                    failures.append(mode+':short_connection_cannot_extend');continue
            added = _make_road(bridge, f'{family}-j15:mode-bridge:{mode}:{i}', network_rules, 'branch', service=False, park=True)
            if added is not None:
                if repair_multimodal:
                    added=added.model_copy(update={'modes':['pedestrian','bicycle'],'park_shared':True,'access':'public'})
                additions.append(added)
    roads = roads + additions
    keep_ids = {d['road_id'] for d in development}
    exploded = []
    for r in roads:
        coords = list(r.coordinates)
        if r.origin == 'retained' or len(coords) == 2:
            exploded.append(r)
            continue
        for i, (a, b) in enumerate(zip(coords, coords[1:])):
            if math.dist(a, b) < 1e-7:
                continue
            exploded.append(r.model_copy(update={'id': r.id + f'-segment-{i}', 'coordinates': [a, b]}))
    roads = exploded
    segmented=[]
    for d in development:
        for r in roads:
            if r.id==d['road_id'] or r.id.startswith(d['road_id']+'-segment-'):
                line=LineString(r.coordinates)
                segmented.append({**d,'road_id':r.id,'parent_axis_id':d['road_id'],
                                  'geometry':mapping(line),'length_m':line.length})
    development=segmented
    public = []
    return roads, development, public, failures


def strip_priority(*,family,entry_distance_m,transit_distance_m,baseline_percentile,
                   centre_distance_m,main_strip,axis_gfa_m2):
    """Commander DRAFT fill order only, never an overall strategy winner.

    30% entrance/transit proximity + 30% frozen external integration percentile
    + 40% declared strategy intent. Distances are measured metres; missing
    transit or baseline data contribute zero and remain unavailable metadata.
    """
    proximity=1/(1+entry_distance_m/100)
    if transit_distance_m is not None:proximity=(proximity+1/(1+transit_distance_m/100))/2
    baseline=baseline_percentile/100 if baseline_percentile is not None else 0
    intent=1/(1+centre_distance_m/100) if family=='radial' else float(main_strip) if family=='axial' else 1/(1+axis_gfa_m2/10000) if family=='grid' else float(not main_strip)
    return .3*proximity+.3*baseline+.4*intent


class FrontageSelector:
    """Keep prepared envelopes up to the FAR budget. J12c ClusterSelector stays unchanged."""

    def __init__(self, development, *, family="axial", blocks=(), entrances=(), centre=None, transit=None):
        self.development = []
        self.rejections = []
        self._authored = development
        self.family=family;self.blocks=blocks;self.entrances=entrances;self.centre=centre;self.transit=transit
        self.axis_gfa={}
        axis_lengths={}
        for d in development:
            axis=d.get('parent_axis_id',d['road_id'])
            axis_lengths[axis]=axis_lengths.get(axis,0)+d['length_m']
        self.primary=max(axis_lengths,key=lambda k:(axis_lengths[k],k),default=None)

    def __call__(self, groups, budget, coverage):
        chosen = []
        used = set()
        gfa = 0.0
        area = 0.0
        goal = budget

        def fits(option):
            if option['block_index'] in used:
                return False
            if gfa + option['gfa'] > budget + 1e-6 or area + option['profile'].geometry.area > coverage + 1e-6:
                return False
            if option['profile'].type_id == 'building.i_slab':
                for other in chosen:
                    if other['profile'].type_id != 'building.i_slab':
                        continue
                    if option['profile'].geometry.distance(other['profile'].geometry) < max(option['height'], other['height']) - 1e-6:
                        return False
            return True

        def take(option):
            nonlocal gfa, area
            chosen.append(option)
            used.add(option['block_index'])
            gfa += option['gfa']
            block=self.blocks[option['block_index']] if self.blocks else {}
            axis=block.get('axis_id')
            self.axis_gfa[axis]=self.axis_gfa.get(axis,0)+option['gfa']
            area += option['profile'].geometry.area

        def priority(option):
            g=option['profile'].geometry
            block=self.blocks[option['block_index']] if self.blocks else {}
            return strip_priority(family=self.family,
                entry_distance_m=min((g.distance(Point(e.coordinates))/max(e.weight,1) for e in self.entrances),default=0),
                transit_distance_m=g.distance(self.transit) if self.transit is not None else None,
                baseline_percentile=block.get('baseline_percentile'),
                centre_distance_m=g.distance(self.centre) if self.centre is not None else 0,
                main_strip=block.get('axis_id')==self.primary,axis_gfa_m2=self.axis_gfa.get(block.get('axis_id'),0))
        flat = [option for group in groups for option in group]
        for zone in sorted({option['zone_id'] for option in flat}):
            options = [option for option in flat if option['zone_id'] == zone and fits(option)]
            if options:
                take(max(options, key=lambda option:(priority(option),-option['gfa'])))
        for option in flat:
            if len({item['profile'].type_id for item in chosen}) >= 4:
                break
            if option['profile'].type_id in {item['profile'].type_id for item in chosen} or not fits(option):
                continue
            take(option)
        pending=[o for o in flat if o['block_index'] not in used]
        while pending and gfa<goal:
            option=max(pending,key=lambda o:(priority(o),
                -self.blocks[o['block_index']].get('type_preferences',()).index(o['profile'].type_id)
                if self.blocks and o['profile'].type_id in self.blocks[o['block_index']].get('type_preferences',()) else -10,
                o['wall_score'], o['gfa'],-o['block_index']))
            pending.remove(option)
            if fits(option):take(option)
        for row in self._authored:
            self.development.append(dict(row))
        return chosen


def ranked_from_axes(development, roads):
    by_id = {r.id: r for r in roads}
    ranked = []
    for row in development:
        road = by_id.get(row['road_id'])
        if road is None:
            continue
        ranked.append(dict(road=road, development_geometry=row['geometry'], score=100, intent_zh=row['intent_zh']))
    return ranked


def drawing_guard(row):
    if row.get('status') != 'VALID' or row.get('version') != VERSION or not row.get('buildings') or not row.get('checks') or not all(v is True for v in row['checks'].values()) or not row.get('network_hard_checks', {}).get('checks') or not all(v is True for v in row['network_hard_checks']['checks'].values()):
        raise ValueError('INVALID block-first: figure output prohibited')
    rules = CouplingRules.model_validate(row['coupling']['rules'])
    geometry = row['geometry']['features']
    site = shape(next(f['geometry'] for f in geometry if f['properties']['role'] == 'site_area'))
    water = unary_union([shape(f['geometry']) for f in geometry if f['properties']['role'] == 'water'] or [Polygon()])
    retained = {f.get('id', str(i)): shape(f['geometry']) for i, f in enumerate(geometry) if f['properties']['role'] == 'retained'}
    roads = [net.NetworkRoad.model_validate(dict(id=f['properties']['road_id'], coordinates=f['geometry']['coordinates'], **{k: v for k, v in f['properties'].items() if k in net.NetworkRoad.model_fields and k != 'id'})) for f in geometry if f['properties']['role'] == 'road']
    by_id = {r.id: r for r in roads}
    development = row['coupling']['development_streets']
    if not development or any(d['road_id'] not in by_id or shape(d['geometry']).difference(LineString(by_id[d['road_id']].coordinates).buffer(1e-6)).length > 1e-6 for d in development):
        raise ValueError('INVALID development lineage: figure output prohibited')
    lines = [shape(d['geometry']) for d in development]
    actual = []
    masses = []
    new_gfa = 0.0
    for f, b in zip(row['features'], row['buildings']):
        g = shape(f['geometry'])
        masses.append(g)
        if not scale_check(type('P', (), {'geometry': g, 'type_id': b['type_id'], 'wing_depth_m': b['scale']['wing_depth_m'], 'unit_count': b['scale'].get('unit_count'), 'unit_frontage_m': b['scale'].get('unit_frontage_m')})(), 'Manufacturing' if b['type_id'] == 'building.industrial_hall' else b['floors'][-1]['use'])['valid']:
            raise ValueError('INVALID scale: figure output prohibited')
        h = sum(floor['floor_height_m'] for floor in b['floors'])
        if abs(h - b['height_m']) > 1e-6 or len(b['floors']) != b['floor_count'] or abs(g.area - b['footprint_area_m2']) > 0.01:
            raise ValueError('INVALID measured massing: figure output prohibited')
        new_gfa += sum(shape(floor['geometry']).area for floor in b['floors'])
        actual.append(dict(type_id=b['type_id'], geometry=g, facade_segments=facade_segments(g, roads, lines)))
    block_rules = BlockFirstRules.model_validate(row['coupling'].get('block_first_rules') or {})
    domain = _buildable(site, water, retained, net.NetworkRules())[1]
    road_half = by_id[development[0]['road_id']].width_m / 2
    assessment = frontage_assessment(lines, actual, domain, block_rules, road_half=road_half)
    if not assessment['bilateral_gate'] or not assessment['defining_gate']:
        raise ValueError('INVALID bilateral wall: figure output prohibited')
    ground, spaces, remnants = merged_open_spaces(site, water, roads, masses, retained, rules)
    if max((s['area_m2'] for s in spaces), default=0) < rules.largest_park_min_m2 or not (2 <= len(spaces) <= 5) or sum(r['area_m2'] for r in remnants) > rules.remnant_max_m2:
        raise ValueError('INVALID parks: figure output prohibited')
    m = row['metrics']
    far = (new_gfa + m['retained_gfa_upper_m2']) / m['far_denominator_m2']
    coverage = unary_union(masses + list(retained.values())).intersection(site.difference(water)).area / m['far_denominator_m2']
    if abs(far - m['far']) > 1e-7 or abs(coverage - m['coverage']) > 1e-7 or not all(revision_checks(row['buildings'], dict(far=far, coverage=coverage))[0].values()):
        raise ValueError('INVALID density readback: figure output prohibited')


def build_structure(*, family, site, water, retained, entrances, fixed_roads, network_rules, block_rules=None, zones=(), gfa_budget=None, dakpark=None):
    if family not in FAMILIES:
        raise ValueError('unknown S6 strategy')
    block_rules = block_rules or BlockFirstRules()
    axes, meta = development_axes(family, site, water, retained, entrances, network_rules, block_rules, zones=zones, fixed_roads=fixed_roads)
    axes += [{**a, "geometry": shape(a["geometry"])} for a in meta.get("cross_connections", [])]
    # Connect the road network before allocating land. J12b owns massing.
    roads, development, public, failures = roads_from_structure(
        axes, [], site, water, retained, entrances, fixed_roads, network_rules, block_rules, family=family, meta=meta,
    )
    blocks = strip_land_blocks(axes, roads, site, water, retained, network_rules, zones=zones, public=public)
    meta['subdivision_method'] = 'BUILDABLE_LAND_MINUS_ROAD_SURFACES'
    return dict(family=family, axes=axes, blocks=blocks, roads=roads, development=development, public=public, failures=failures, meta=meta, block_rules=block_rules)


def _public_block(block):
    return {k: v for k, v in block.items() if k != 'profile'} | {
        'geometry': mapping(block['geometry']),
        'preferred_type': block.get('preferred_type'),
    }


def generate_block_first(*, family, site, water, retained, entrances, fixed_roads, zones, syntax_document,
                         network_rules, denominator, retained_gfa, parameters, context_edges=(), external=None,
                         s6_rules=None, coupling_rules=None, block_rules=None, candidate_selector=None, structure=None,
                         gfa_budget=None, dakpark=None):
    """Deterministic block-first proposal. Syntax document must match the new roads."""
    if family not in FAMILIES:
        raise ValueError('unknown S6 strategy')
    block_rules = block_rules or BlockFirstRules()
    coupling_rules = coupling_rules or CouplingRules()
    s6_rules = s6_rules or S6Rules()
    if dakpark is None:
        for edge in context_edges:
            kind = edge['kind'] if isinstance(edge, dict) else edge.kind
            if kind == 'dakpark':
                dakpark = shape(edge['geometry'] if isinstance(edge, dict) else edge.geometry)
                break
    budget = gfa_budget if gfa_budget is not None else max(0.0, 0.8 * denominator - retained_gfa)
    built = structure or build_structure(
        family=family, site=site, water=water, retained=retained, entrances=entrances, fixed_roads=fixed_roads,
        network_rules=network_rules, block_rules=block_rules, zones=zones, gfa_budget=budget, dakpark=dakpark,
    )
    axes, structure_meta = built['axes'], built['meta']
    blocks, roads = built['blocks'], built['roads']
    development, public, construction_failures = built['development'], built['public'], built['failures']
    polygons = [b['geometry'] for b in blocks]
    transit=next((shape(e['geometry']) for e in context_edges if isinstance(e,dict) and e['kind']=='transit'),None)
    selector = candidate_selector or FrontageSelector(development,family=family,blocks=blocks,entrances=entrances,centre=site.centroid,transit=transit)
    massing = generate_massing(
        family=family, blocks=polygons, roads=roads, syntax_document=syntax_document, network_rules=network_rules,
        site=site, water=water, retained=retained, zones=zones, entrances=entrances, denominator=denominator,
        retained_gfa=retained_gfa, parameters=parameters, context_edges=context_edges, rules=s6_rules,
        candidate_selector=selector, block_metadata=blocks if built.get('brief_driven') else None,
    )
    coupling_external = dict(external or {}, _site=site, _water=water)
    buildings = [shape(f['geometry']) for f in massing['features']]
    for d in selector.development:
        d.setdefault('intent_zh', next((row['intent_zh'] for row in development if row['road_id'] == d.get('road_id')), structure_meta.get('heading_deg')))
    development_used = selector.development or development
    cc, cm, ground, spaces, remnants = coupling_checks(
        massing, development_used, roads, site, water, retained, entrances, coupling_external, coupling_rules,
    )
    massing['checks'].update(cc)
    massing['metrics'].update(cm)
    domain = _buildable(site, water, retained, network_rules)[1]
    frontage_buildings = [dict(type_id=record['type_id'], geometry=shape(feature['geometry'])) for feature, record in zip(massing['features'], massing['buildings'])]
    dev_lines = [shape(row['geometry']) for row in development_used]
    matched = next((road for road in roads if development_used and road.id == development_used[0]['road_id']), None)
    road_half = matched.width_m / 2 if matched is not None else network_rules.main_shared_width_m / 2
    assessment = frontage_assessment(dev_lines, frontage_buildings, domain, block_rules, road_half=road_half)
    massing['checks']['development_bilateral_streetwall'] = bool(assessment['bilateral_gate'])
    massing['checks']['defining_edge'] = bool(assessment['defining_gate'])
    massing['checks']['named_park_count'] = 2 <= len(spaces) <= 5
    massing['metrics'].update(assessment)
    massing['metrics']['legacy_streetwall_continuity_ratio'] = cm.get('streetwall_continuity_ratio')
    massing['open_space'] = mapping(ground)
    massing['named_open_spaces'] = spaces
    massing['narrow_remnants'] = remnants
    massing['metrics']['named_open_space_area_m2'] = sum(s['area_m2'] for s in spaces)
    massing['metrics']['park_count'] = len(spaces)
    hard = net.hard_checks(
        site=site, roads=roads, buildings=buildings, retained_before=retained, retained_after=retained,
        water=water, entrances=entrances, external=external or {}, rules=network_rules, public_spaces=public,
    )
    quality = net.geometry_quality(site, roads, net.derive_blocks(site, roads, list(retained.values()), water, network_rules, public), entrances, network_rules)
    massing['network_hard_checks'] = hard
    massing['network_quality'] = quality
    massing['construction_failures'] = construction_failures
    massing['structure'] = dict(
        axes=[{**a, 'geometry': mapping(a['geometry'])} for a in axes],
        blocks=[_public_block(b) for b in blocks],
        meta=structure_meta,
    )
    massing['coupling'] = dict(
        version=VERSION, rules=coupling_rules.model_dump(), development_streets=development_used,
        development_rejections=selector.rejections, road_actions=[], syntax_comparison={},
        block_first_rules=block_rules.model_dump(),
    )
    massing['family'] = family
    massing['version'] = VERSION
    massing['failure_reasons'] = [k for k, v in massing['checks'].items() if not v] + [k for k, v in hard['checks'].items() if not v] + construction_failures
    if not polygons:
        massing['failure_reasons'].append('no_development_blocks')
    massing['status'] = 'VALID' if not massing['failure_reasons'] else 'INVALID'
    massing['design_intent'] = dict(
        reason_zh=next((d.get('intent_zh') for d in development_used if d.get('intent_zh')), '街廓先行結構未形成可量測的發展軸線'),
        method_zh='街廓先行：依可建造寬度放周邊式、L 形、板樓或連棟。雙側街牆只計兩側可建帶合計至少 40 公尺的發展街段，門檻 0.6；界定邊含單側水岸或公園立面，門檻 0.8。道路服務街廓並接到保留城市道路與入口。公園 2 至 5 座、最大至少 2 公頃、殘片不超過 3000 平方公尺。高度與尺度沿用 J12b。',
        rule_card_ids=sorted({c for r in massing['buildings'] for c in r['design_intent']['rule_card_ids']} | set(block_rules.rule_card_ids)),
        knowledge_unit_ids=sorted({k for r in massing['buildings'] for k in r['design_intent']['knowledge_unit_ids']}),
        status='DRAFT',
    )
    massing['roads'] = [r.model_dump() for r in roads]
    return massing


__all__ = [
    'VERSION', 'BlockFirstRules', 'development_axes', 'place_blocks', 'roads_from_structure',
    'build_structure', 'generate_block_first', 'drawing_guard', 'difference_metrics',
]
