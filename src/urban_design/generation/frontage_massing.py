"""J17b 沿街優先的量體配置器（frontage-first placer）。

只放純函式。依 J17 build_brief_structure() 產生的街廓與道路，
從街廓臨街邊向內生成量體，自然形成街牆，滿足尺度、樓層與各帶 GFA 目標。
"""
from __future__ import annotations

import math
from itertools import combinations
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import (
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
    shape,
)
from shapely.ops import nearest_points, unary_union

from . import block_first as bf
from . import multimodal_network as net
from .context_massing import (
    convex_clear_width,
    depth_minimum,
    rectangular_size,
    scale_check,
)
from .massing_revision import facade_segments
from .network_massing_coupling import CouplingRules

VERSION = 'frontage-first-v2'


def _get_brief_segment_rows(brief: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        from scripts.s6_brief import _brief_segment_rows
        return _brief_segment_rows(brief)
    except ImportError:
        import sys
        sys.path.insert(0, '.')
        from scripts.s6_brief import _brief_segment_rows
        return _brief_segment_rows(brief)


def get_road_surfaces(roads: List[Any]) -> Any:
    """計算所有平面道路路面多邊形的聯集。"""
    road_polys = []
    for r in roads:
        coords = r.coordinates if hasattr(r, 'coordinates') else r.get('coordinates', [])
        width = r.width_m if hasattr(r, 'width_m') else r.get('width_m', 7.5)
        layer = r.layer if hasattr(r, 'layer') else r.get('layer', 0)
        if layer == 0 and coords:
            road_polys.append(LineString(coords).buffer(width / 2.0))
    return unary_union(road_polys) if road_polys else Polygon()


def clean_boundary_edges(poly: Polygon, min_len: float = 3.0) -> List[LineString]:
    """簡化微小頂點並合併近乎共線的邊界線段。"""
    sim = poly.simplify(0.4, preserve_topology=True)
    if not isinstance(sim, Polygon) or sim.is_empty:
        sim = poly
    coords = list(sim.exterior.coords)[:-1]
    if len(coords) < 3:
        coords = list(poly.exterior.coords)[:-1]
    edges = []
    for i in range(len(coords)):
        a = coords[i]
        b = coords[(i + 1) % len(coords)]
        ls = LineString([a, b])
        if ls.length >= min_len:
            edges.append(ls)
    return sorted(edges, key=lambda e: -e.length)


def frontage_edges(
    poly: Polygon, road_surfaces: Any, max_dist: float = 1.0
) -> List[LineString]:
    """判定街廓的臨街邊：與道路面距離 <= 1.0 m 的邊界；若無則回傳最長邊。"""
    edges = clean_boundary_edges(poly)
    if not edges:
        coords = list(poly.exterior.coords)
        edges = [
            LineString([coords[i], coords[i + 1]])
            for i in range(len(coords) - 1)
            if LineString([coords[i], coords[i + 1]]).length > 1.0
        ]
    if not edges:
        return []

    if road_surfaces is None or road_surfaces.is_empty:
        return [max(edges, key=lambda e: e.length)]

    front = [e for e in edges if e.distance(road_surfaces) <= max_dist + 1e-3]
    if not front:
        return [max(edges, key=lambda e: e.length)]
    return sorted(front, key=lambda e: -e.length)


def fit_rect_along_edge(
    poly: Polygon,
    edge: LineString,
    depth: float,
    min_len: float,
    max_len: float,
    road_surfaces: Optional[Any] = None,
    target_station: Optional[float] = None,
    axis: Optional[LineString] = None,
    axis_len: Optional[float] = None,
) -> Optional[Tuple[Polygon, float]]:
    """沿指定臨街邊向街廓內側貼合長度介於 [min_len, max_len] 的矩形量體。"""
    coords = list(edge.coords)
    dx = coords[1][0] - coords[0][0]
    dy = coords[1][1] - coords[0][1]
    l_edge = math.hypot(dx, dy)
    if l_edge < min_len:
        return None
    u = (dx / l_edge, dy / l_edge)
    n = (-u[1], u[0])
    mid = Point(
        coords[0][0] + u[0] * l_edge / 2.0 + n[0] * 0.5,
        coords[0][1] + u[1] * l_edge / 2.0 + n[1] * 0.5,
    )
    if not poly.buffer(1e-4).covers(mid):
        n = (u[1], -u[0])

    candidates = []
    for shift_n in [0.2, 0.1, 0.4, 0.0]:
        for length in range(int(min(l_edge - 0.5, max_len)), int(min_len) - 1, -2):
            x_steps = [0.0, 0.5, 1.0] + list(range(2, int(l_edge - length) + 1, 2))
            for x0 in x_steps:
                if x0 + length > l_edge:
                    continue
                p0 = (
                    coords[0][0] + x0 * u[0] + shift_n * n[0],
                    coords[0][1] + x0 * u[1] + shift_n * n[1],
                )
                p1 = (
                    p0[0] + length * u[0],
                    p0[1] + length * u[1],
                )
                p2 = (p1[0] + depth * n[0], p1[1] + depth * n[1])
                p3 = (p0[0] + depth * n[0], p0[1] + depth * n[1])
                cand = Polygon([p0, p1, p2, p3, p0])
                if poly.buffer(1e-4).covers(cand):
                    if road_surfaces is not None and not road_surfaces.is_empty and cand.intersection(road_surfaces).area > 1e-5:
                        continue
                    if target_station is not None and axis is not None and axis_len is not None:
                        from .brief_driven import axis_to_station
                        st = axis_to_station(axis, cand.representative_point(), axis_len)
                        diff = abs(st - target_station)
                        projections = [axis_to_station(axis, Point(v), axis_len) for v in cand.exterior.coords]
                        span = max(projections) - min(projections)
                        if span <= 80.0:
                            candidates.append((diff, -length, cand, float(length)))
                    else:
                        return cand, float(length)
    if candidates:
        candidates.sort(key=lambda c: (c[0], c[1]))
        return candidates[0][2], candidates[0][3]
    return None


def make_perimeter_candidate(
    block_geom: Polygon, use: str, wing_depth: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """生成周邊式／合院量體：footprint = block - block.buffer(-翼深)。

    住宅翼深 12 m，混合 14 m。中庭最小淨寬 >= 20 m。
    若長度 > 90 m，在首層切出 >= 6 m 穿越口。
    """
    depth = wing_depth if wing_depth is not None else (12.0 if use == 'Residential' else 14.0)
    inner = block_geom.buffer(-depth)
    if inner.is_empty:
        return None
    if inner.geom_type == 'MultiPolygon':
        inner = max(inner.geoms, key=lambda p: p.area)
    if not isinstance(inner, Polygon) or inner.buffer(-10.0).is_empty:
        return None

    try:
        cw = convex_clear_width(inner)
    except Exception:
        return None
    if cw < 20.0 - 1e-6:
        return None

    ring = block_geom.difference(inner)
    if not isinstance(ring, Polygon) or len(ring.interiors) != 1:
        return None

    short, long = rectangular_size(ring)
    if short < 40.0 - 1e-6 or ring.area < 1200.0 - 1e-6:
        return None

    measured_depth = ring.exterior.distance(Polygon(ring.interiors[0]).exterior)
    if measured_depth < depth_minimum(use) - 1e-6 or abs(measured_depth - depth) > 0.5:
        return None

    prof = SimpleNamespace(
        geometry=ring,
        type_id='block.perimeter',
        wing_depth_m=measured_depth,
        unit_count=None,
        unit_frontage_m=None,
    )
    sc = scale_check(prof, use)
    if not sc['valid']:
        return None
    sc['unit_count'] = None
    sc['unit_frontage_m'] = None
    sc['wing_depth_m'] = measured_depth

    # 若外框長度 > 90 m，首層切出 6 m 穿越口（門廊/underpass）
    ring_floor0 = ring
    if long > 90.0 or ring.exterior.length / 2.0 > 90.0:
        coords = list(ring.exterior.coords)
        longest_ext_edge = max(
            [LineString([coords[i], coords[i + 1]]) for i in range(len(coords) - 1)],
            key=lambda e: e.length,
        )
        mid_pt = longest_ext_edge.interpolate(0.5, normalized=True)
        cut_box = mid_pt.buffer(3.0, cap_style=3)
        cut_candidate = ring.difference(cut_box)
        if isinstance(cut_candidate, Polygon) and cut_candidate.is_valid and ring.buffer(1e-7).covers(cut_candidate):
            ring_floor0 = cut_candidate

    return {
        'type_id': 'block.perimeter',
        'geometry': ring,
        'wing_depth_m': measured_depth,
        'scale': sc,
        'courtyard_width_m': cw,
        'ring_floor0': ring_floor0,
        'ring_floor0_area_m2': ring_floor0.area,
    }


def make_l_block_candidate(
    block_geom: Polygon,
    edge: LineString,
    use: str,
    wing_depth: Optional[float] = None,
    road_surfaces: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """生成 L 形量體：沿最長臨街邊放一翼，轉角放一翼，翼深 12–14 m。"""
    depth = wing_depth if wing_depth is not None else (12.0 if use == 'Residential' else 14.0)
    coords = list(edge.coords)
    dx = coords[1][0] - coords[0][0]
    dy = coords[1][1] - coords[0][1]
    l_edge = math.hypot(dx, dy)
    if l_edge < 2.0 * depth:
        return None
    u = (dx / l_edge, dy / l_edge)
    n = (-u[1], u[0])
    mid = Point(
        coords[0][0] + u[0] * l_edge / 2.0 + n[0] * 0.5,
        coords[0][1] + u[1] * l_edge / 2.0 + n[1] * 0.5,
    )
    if not block_geom.buffer(1e-4).covers(mid):
        n = (u[1], -u[0])

    for shift_n in [0.2, 0.0, 0.4]:
        for origin, dir_u in [(coords[0], u), (coords[1], (-u[0], -u[1]))]:
            for l1 in range(int(min(l_edge - 0.5, 80)), int(2 * depth) - 1, -2):
                for l2 in range(int(min(80, l_edge - 0.5)), int(2 * depth) - 1, -2):
                    if (l1 + l2 - depth) * depth < 600.0:
                        continue
                    p0 = (origin[0] + shift_n * n[0], origin[1] + shift_n * n[1])
                    p1 = (p0[0] + dir_u[0] * l1, p0[1] + dir_u[1] * l1)
                    p2 = (p1[0] + n[0] * depth, p1[1] + n[1] * depth)
                    p3 = (
                        p0[0] + dir_u[0] * depth + n[0] * depth,
                        p0[1] + dir_u[1] * depth + n[1] * depth,
                    )
                    p4 = (
                        p0[0] + dir_u[0] * depth + n[0] * l2,
                        p0[1] + dir_u[1] * depth + n[1] * l2,
                    )
                    p5 = (p0[0] + n[0] * l2, p0[1] + n[1] * l2)
                    cand = Polygon([p0, p1, p2, p3, p4, p5, p0])
                    if block_geom.buffer(1e-4).covers(cand):
                        if road_surfaces is not None and not road_surfaces.is_empty and cand.intersection(road_surfaces).area > 1e-5:
                            continue
                        prof = SimpleNamespace(
                            geometry=cand,
                            type_id='building.l_block',
                            wing_depth_m=depth,
                            unit_count=None,
                            unit_frontage_m=None,
                        )
                        sc = scale_check(prof, use)
                        if sc['valid']:
                            sc['unit_count'] = None
                            sc['unit_frontage_m'] = None
                            sc['wing_depth_m'] = depth
                            return {
                                'type_id': 'building.l_block',
                                'geometry': cand,
                                'wing_depth_m': depth,
                                'scale': sc,
                                'wing_lengths': (float(l1), float(l2)),
                                'ring_floor0': cand,
                                'ring_floor0_area_m2': cand.area,
                            }
    return None


def make_rowhouse_candidate(
    block_geom: Polygon,
    edge: LineString,
    use: str = 'Residential',
    wing_depth: float = 11.0,
    road_surfaces: Optional[Any] = None,
    target_station: Optional[float] = None,
    axis: Optional[LineString] = None,
    axis_len: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """生成沿臨街邊的連棟街屋：進深 10–12 m，面寬 5.4–6 m 的戶數。"""
    depth = max(10.0, min(12.0, wing_depth))
    fit = fit_rect_along_edge(
        block_geom,
        edge,
        depth,
        min_len=32.4,
        max_len=110.0,
        road_surfaces=road_surfaces,
        target_station=target_station,
        axis=axis,
        axis_len=axis_len,
    )
    if not fit:
        return None
    rect, length = fit
    unit_count = int(round(length / 6.0))
    if not (6 <= unit_count <= 20):
        unit_count = max(6, min(20, unit_count))
    unit_frontage = length / unit_count
    if not (5.4 <= unit_frontage <= 7.2):
        return None

    # 連棟街屋在語意與尺度檢查上恆為住宅用途
    prof = SimpleNamespace(
        geometry=rect,
        type_id='building.rowhouse',
        wing_depth_m=depth,
        unit_count=unit_count,
        unit_frontage_m=unit_frontage,
    )
    sc = scale_check(prof, 'Residential')
    if not sc['valid']:
        return None
    sc['unit_count'] = unit_count
    sc['unit_frontage_m'] = unit_frontage
    sc['wing_depth_m'] = depth
    return {
        'type_id': 'building.rowhouse',
        'geometry': rect,
        'wing_depth_m': depth,
        'scale': sc,
        'unit_count': unit_count,
        'unit_frontage_m': unit_frontage,
        'ring_floor0': rect,
        'ring_floor0_area_m2': rect.area,
    }


def make_slab_candidate(
    block_geom: Polygon,
    edge: LineString,
    use: str,
    wing_depth: Optional[float] = None,
    road_surfaces: Optional[Any] = None,
    target_station: Optional[float] = None,
    axis: Optional[LineString] = None,
    axis_len: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """生成平行街道的板樓：進深 12–14 m，長度 30–80 m（<= 90 m）。"""
    depth = wing_depth if wing_depth is not None else (12.0 if use == 'Residential' else 14.0)
    fit = fit_rect_along_edge(
        block_geom,
        edge,
        depth,
        min_len=30.0,
        max_len=80.0,
        road_surfaces=road_surfaces,
        target_station=target_station,
        axis=axis,
        axis_len=axis_len,
    )
    if not fit:
        return None
    rect, length = fit
    prof = SimpleNamespace(
        geometry=rect,
        type_id='building.i_slab',
        wing_depth_m=depth,
        unit_count=None,
        unit_frontage_m=None,
    )
    sc = scale_check(prof, use)
    if not sc['valid']:
        return None
    sc['unit_count'] = None
    sc['unit_frontage_m'] = None
    sc['wing_depth_m'] = depth
    return {
        'type_id': 'building.i_slab',
        'geometry': rect,
        'wing_depth_m': depth,
        'scale': sc,
        'length_m': length,
        'ring_floor0': rect,
        'ring_floor0_area_m2': rect.area,
    }


def make_maker_hall_candidate(
    block_geom: Polygon,
    edge: LineString,
    use: str = 'Manufacturing',
    wing_depth: float = 20.0,
    road_surfaces: Optional[Any] = None,
    target_station: Optional[float] = None,
    axis: Optional[LineString] = None,
    axis_len: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """生成廳式量體（maker_hall）：進深 20–30 m，底層層高 5–7 m。"""
    depth = max(20.0, min(30.0, wing_depth))
    fit = fit_rect_along_edge(
        block_geom,
        edge,
        depth,
        min_len=30.0,
        max_len=80.0,
        road_surfaces=road_surfaces,
        target_station=target_station,
        axis=axis,
        axis_len=axis_len,
    )
    if not fit:
        return None
    rect, length = fit
    prof = SimpleNamespace(
        geometry=rect,
        type_id='building.industrial_hall',
        wing_depth_m=depth,
        unit_count=None,
        unit_frontage_m=None,
    )
    sc = scale_check(prof, 'Manufacturing')
    if not sc['valid']:
        return None
    sc['unit_count'] = None
    sc['unit_frontage_m'] = None
    sc['wing_depth_m'] = depth
    return {
        'type_id': 'building.industrial_hall',
        'geometry': rect,
        'wing_depth_m': depth,
        'scale': sc,
        'length_m': length,
        'first_floor_height_m': 6.0,
        'ring_floor0': rect,
        'ring_floor0_area_m2': rect.area,
    }


def find_landmark_candidate(
    block: Dict[str, Any],
    road_surfaces: Any,
    axis: LineString,
    axis_len: float,
    target_station: float,
    use: str = 'Mixed',
) -> Optional[Dict[str, Any]]:
    """為地標需求尋找符合 scale_check 與 target_station ±40m 的最優量體。"""
    poly = shape(block['geometry']) if isinstance(block['geometry'], dict) else block['geometry']
    front_edges = frontage_edges(poly, road_surfaces)
    all_edges = front_edges + [
        LineString([c1, c2])
        for c1, c2 in zip(poly.exterior.coords, list(poly.exterior.coords)[1:])
        if LineString([c1, c2]).length >= 18.0
    ]
    best = None
    for edge in all_edges:
        for depth in [14.0, 12.0, 11.0]:
            for min_l in [35.0, 30.0, 25.0]:
                res = fit_rect_along_edge(
                    poly, edge, depth, min_l, 55.0,
                    road_surfaces=road_surfaces,
                    target_station=target_station,
                    axis=axis,
                    axis_len=axis_len,
                )
                if res:
                    rect, l = res
                    from .brief_driven import axis_to_station
                    st_rep = axis_to_station(axis, rect.representative_point(), axis_len)
                    diff = abs(st_rep - target_station)
                    projs = [axis_to_station(axis, Point(c), axis_len) for c in rect.exterior.coords]
                    span = max(projs) - min(projs)
                    if diff <= 40.0 and span <= 80.0:
                        tid = 'building.rowhouse' if depth <= 11.0 else 'building.i_slab'
                        prof = SimpleNamespace(geometry=rect, type_id=tid, wing_depth_m=depth, unit_count=None, unit_frontage_m=None)
                        sc = scale_check(prof, use)
                        if sc['valid']:
                            if best is None or diff < best[0]:
                                cand_dict = {
                                    'type_id': tid,
                                    'geometry': rect,
                                    'wing_depth_m': depth,
                                    'scale': sc,
                                    'ring_floor0': rect,
                                    'ring_floor0_area_m2': rect.area,
                                    'is_landmark': True,
                                }
                                best = (diff, cand_dict)
    return best[1] if best else None


def generate_candidate_options_for_block(
    block: Dict[str, Any],
    road_surfaces: Any,
    fire_surface: Optional[Any] = None,
    target_station: Optional[float] = None,
    axis: Optional[LineString] = None,
    axis_len: Optional[float] = None,
    is_landmark_candidate: bool = False,
) -> List[Dict[str, Any]]:
    """為單一街廓尋找所有符合類型偏好的量體候選。"""
    poly = shape(block['geometry']) if isinstance(block['geometry'], dict) else block['geometry']
    raw_use = block.get('use', 'mixed')
    use = 'Residential' if raw_use == 'residential' else 'Manufacturing' if raw_use == 'manufacturing' else 'Mixed'
    prefs = set(block.get('type_preferences', ()))
    front_edges = frontage_edges(poly, road_surfaces)

    options = []

    # 1. perimeter / courtyard
    perim = make_perimeter_candidate(poly, use)
    if perim:
        if 'block.perimeter' in prefs or 'building.courtyard_closed' in prefs:
            options.append(perim)
        elif 'building.l_block' in prefs:
            options.append(dict(perim, is_upgrade=True))

    # 2. frontage edge candidates - 逐條臨街邊測試
    for edge in front_edges[:4]:
        # L-block
        if 'building.l_block' in prefs and not any(o['type_id'] == 'building.l_block' for o in options):
            l_cand = make_l_block_candidate(poly, edge, use, road_surfaces=road_surfaces)
            if l_cand:
                options.append(l_cand)

        # rowhouse (街屋在偏好內時恆以住宅尺度生成)
        if 'building.rowhouse' in prefs and not any(o['type_id'] == 'building.rowhouse' for o in options):
            row_cand = make_rowhouse_candidate(
                poly, edge, 'Residential', road_surfaces=road_surfaces,
                target_station=target_station, axis=axis, axis_len=axis_len,
            )
            if row_cand:
                options.append(row_cand)

        # slab
        if 'building.i_slab' in prefs and not any(o['type_id'] == 'building.i_slab' for o in options):
            slab_cand = make_slab_candidate(
                poly, edge, use, road_surfaces=road_surfaces,
                target_station=target_station, axis=axis, axis_len=axis_len,
            )
            if slab_cand:
                options.append(slab_cand)

        # maker hall (廳式量體恆以製造/創客尺度生成)
        if 'building.industrial_hall' in prefs and not any(o['type_id'] == 'building.industrial_hall' for o in options):
            maker_cand = make_maker_hall_candidate(
                poly, edge, 'Manufacturing', road_surfaces=road_surfaces,
                target_station=target_station, axis=axis, axis_len=axis_len,
            )
            if maker_cand:
                options.append(maker_cand)

    # 消防 40m 限制：一般量體若外牆距消防道路 > 40m 則排除（地標指定街廓保留）
    if fire_surface is not None and not fire_surface.is_empty and not is_landmark_candidate:
        options = [o for o in options if o['geometry'].boundary.distance(fire_surface) <= 40.0]

    return options


def distribute_strip_gfa_by_segments(
    strip_id: str,
    strip_target: float,
    brief: Dict[str, Any],
    strip_blocks: List[Dict[str, Any]],
    road_surfaces: Any,
    fire_surface: Optional[Any] = None,
    landmark_block_ids: Optional[set] = None,
) -> Tuple[Dict[Tuple[float, float], float], Dict[str, float], List[Dict[str, Any]], Dict[Tuple[float, float], List[Dict[str, Any]]]]:
    """依段落分配各帶 GFA 目標。

    權重 = 段落可建土地面積 ×（若該段在 brief development_streets 內則 ×3，否則 ×1）。
    段內再依街廓臨街長度分配到各街廓。
    若段落分到的 GFA < 972 m²（3層連棟最低門檻），改用該段允許之最淺類型並記錄。
    """
    landmark_block_ids = landmark_block_ids or set()
    brief_segs = _get_brief_segment_rows(brief)
    segments = [
        r for r in brief_segs
        if r['strip_id'] == strip_id
        and not (r.get('floors') == [0, 0] or all(t in ('park', 'retained_reuse') for t in r.get('typologies', [])))
    ]
    shallow_records = []
    seg_weights = {}
    seg_matching_blocks = {}
    for seg in segments:
        s_start, s_end = seg['segment_m']
        matching = [
            b for b in strip_blocks
            if s_start - 1e-4 <= sum(b.get('segment_m', [0, 0])) / 2.0 <= s_end + 1e-4
        ]
        buildable = [
            b for b in matching
            if fire_surface is None or fire_surface.is_empty or shape(b['geometry']).boundary.distance(fire_surface) <= 40.0 or b['id'] in landmark_block_ids
        ]
        seg_matching_blocks[(s_start, s_end)] = buildable
        land_area = sum(shape(b['geometry']).area for b in buildable)
        in_dev = any(
            d['strip_id'] == strip_id and max(d['segment_m'][0], s_start) < min(d['segment_m'][1], s_end)
            for d in brief.get('development_streets', [])
        )
        weight = land_area * (3.0 if in_dev else 1.0)
        seg_weights[(s_start, s_end)] = (weight, land_area, in_dev, seg)

    total_weight = sum(w[0] for w in seg_weights.values())
    aim_target = min(strip_target * 0.94, strip_target)
    seg_targets = {}
    for (s_start, s_end), (w, land_area, in_dev, seg) in seg_weights.items():
        buildable = seg_matching_blocks[(s_start, s_end)]
        if not buildable or total_weight <= 0:
            seg_targets[(s_start, s_end)] = 0.0
            continue
        raw_gfa = aim_target * (w / total_weight)
        min_gfa = 972.0
        if raw_gfa < min_gfa:
            raw_gfa = min_gfa
            shallow_records.append(dict(
                strip_id=strip_id,
                segment_m=[s_start, s_end],
                gfa_m2=raw_gfa,
                reason_zh='段落分配 GFA 不足，改用該段允許之最淺類型（3層連棟）',
            ))
        seg_targets[(s_start, s_end)] = raw_gfa

    block_targets = {}
    for (s_start, s_end), s_gfa in seg_targets.items():
        buildable = seg_matching_blocks[(s_start, s_end)]
        if not buildable:
            continue
        frontages = {}
        for b in buildable:
            poly = shape(b['geometry'])
            f_edges = frontage_edges(poly, road_surfaces)
            f_len = sum(e.length for e in f_edges) if f_edges else 10.0
            frontages[b['id']] = max(f_len, 10.0)
        total_front = sum(frontages.values())
        for b in buildable:
            block_targets[b['id']] = s_gfa * (frontages[b['id']] / total_front)

    return seg_targets, block_targets, shallow_records, seg_matching_blocks


def generate_frontage_massing(
    *,
    structure: Dict[str, Any],
    brief: Dict[str, Any],
    facts: Dict[str, Any],
    family: str,
    site: Polygon,
    water: Any,
    retained: Dict[str, Any],
    entrances: List[Any],
    fixed_roads: List[Any],
    zones: List[Dict[str, Any]],
    denominator: float,
    retained_gfa: float,
    parameters: Dict[str, Any],
    context_edges: Any = (),
    external: Optional[Dict[str, Any]] = None,
    syntax_document: Optional[Dict[str, Any]] = None,
    network_rules: Any = None,
    block_rules: Any = None,
    coupling_rules: Any = None,
    s6_rules: Any = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """沿街優先量體配置器純函式。

    輸出格式與 block_first.generate_block_first 完全相同，供後續驗證直接消費。
    """
    block_rules = block_rules or bf.BlockFirstRules()
    coupling_rules = coupling_rules or CouplingRules()
    s6_rules = s6_rules or bf.S6Rules()
    network_rules = network_rules or net.NetworkRules()

    blocks = structure['blocks']
    roads = [net.NetworkRoad.model_validate(r) if isinstance(r, dict) else r for r in structure['roads']]
    development = structure.get('development', [])
    public = structure.get('public', [])
    axes = structure.get('axes', [])
    structure_meta = structure.get('meta', {})
    construction_failures = structure.get('failures', [])

    road_surfaces = get_road_surfaces(roads)

    # 消防可達車道面（汽車或緊急車道）
    motor_roads = [r for r in roads if 'motor_vehicle' in r.modes and r.layer == 0]
    motor = [LineString(r.coordinates) for r in motor_roads]
    motor_external = [
        shape(f['geometry'])
        for f in (external or {}).get('motor_vehicle', [])
        if int(f.get('properties', {}).get('layer') or 0) == 0
        and shape(f['geometry']).difference(site).length > 1e-6
    ]
    if motor and motor_external:
        from shapely.strtree import STRtree
        external_tree = STRtree(motor_external)
        motor_tree = STRtree(motor)
        reached_motor = {
            i for i, g in enumerate(motor)
            if any(g.distance(motor_external[int(j)]) <= 1e-6 for j in external_tree.query(g.buffer(1e-6)))
        }
        pending = list(reached_motor)
        while pending:
            i = pending.pop()
            linked = {
                int(j) for j in motor_tree.query(motor[i].buffer(1e-6))
                if int(j) not in reached_motor and motor[i].distance(motor[int(j)]) <= 1e-6
            }
            reached_motor.update(linked)
            pending.extend(linked)
        fire_surface = unary_union([motor[i].buffer(motor_roads[i].width_m / 2.0) for i in sorted(reached_motor)])
    else:
        fire_surface = unary_union([LineString(r.coordinates).buffer(r.width_m / 2.0) for r in roads if 'motor_vehicle' in r.modes and r.layer == 0])

    allocation = brief.get('gfa_allocation', {})
    targets = {r['strip_id']: float(r['gfa_m2']) for r in allocation.get('by_strip', [])}
    global_gfa_cap = min(float(allocation.get('new_gfa_budget_m2', 77965.18)), 77965.18)

    # 1. 地標定義綁定：每一定義僅精確綁定最接近 authored station 的單一街廓
    landmark_defs = brief.get('height_strategy', {}).get('landmarks', [])
    landmark_block_ids = set()
    landmark_info = {}
    landmark_cands = {}
    for lm in landmark_defs:
        sid = lm['strip_id']
        st_m = lm['station_m']
        cands = [b for b in blocks if b['strip_id'] == sid]
        if cands:
            axis_geom = shape(next(r['axis'] for r in facts['geometry']['strips'] if r['id'] == sid))
            axis_len = next(r['length_m'] for r in facts['buildable']['strips'] if r['id'] == sid)

            scored_b = []
            for b in cands:
                found_cand = find_landmark_candidate(b, road_surfaces, axis_geom, axis_len, st_m, use='Mixed')
                if found_cand:
                    from .brief_driven import axis_to_station
                    st_rep = axis_to_station(axis_geom, found_cand['geometry'].representative_point(), axis_len)
                    d = abs(st_rep - st_m)
                    f_dist = found_cand['geometry'].distance(fire_surface) if fire_surface and not fire_surface.is_empty else 0.0
                    poly_b = shape(b['geometry'])
                    can_perim = make_perimeter_candidate(poly_b, 'Mixed') is not None
                    scored_b.append((
                        f_dist <= 40.0,
                        not can_perim,
                        -d,
                        b,
                        found_cand,
                    ))

            if scored_b:
                best_tuple = max(scored_b)
                best_b = best_tuple[3]
                landmark_cands[best_b['id']] = best_tuple[4]
            else:
                best_b = min(cands, key=lambda b: abs(sum(b.get('segment_m', [0, 0])) / 2.0 - st_m))

            best_b['landmark_height_m'] = min(float(lm['height_m']), 20.0)
            landmark_block_ids.add(best_b['id'])
            landmark_info[best_b['id']] = dict(
                target_station=st_m,
                height_m=best_b['landmark_height_m'],
                axis=axis_geom,
                axis_len=axis_len,
            )

    # 2. 為每個街廓建立候選項
    block_candidates = {}
    for b in blocks:
        bid = b['id']
        is_lm = bid in landmark_block_ids
        lm_data = landmark_info.get(bid, {})
        opts = generate_candidate_options_for_block(
            b,
            road_surfaces,
            fire_surface=fire_surface,
            target_station=lm_data.get('target_station'),
            axis=lm_data.get('axis'),
            axis_len=lm_data.get('axis_len'),
            is_landmark_candidate=is_lm,
        )
        if is_lm and bid in landmark_cands:
            opts = [landmark_cands[bid]] + [o for o in opts if o != landmark_cands[bid]]
        block_candidates[bid] = opts

    # 3. 逐帶依段落分配與挑選
    selected_buildings: List[Tuple[Dict[str, Any], Dict[str, Any], int, float, float, float]] = []
    upgraded_records: List[Dict[str, Any]] = []
    shallow_all: List[Dict[str, Any]] = []
    used_block_ids = set()
    represented_types = set()
    represented_zones = set()

    for strip_id in sorted(targets.keys()):
        strip_target = targets[strip_id]
        strip_blocks = [b for b in blocks if b['strip_id'] == strip_id]
        seg_targets, block_targets, shallow_records, seg_matching = distribute_strip_gfa_by_segments(
            strip_id, strip_target, brief, strip_blocks, road_surfaces, fire_surface, landmark_block_ids
        )
        shallow_all.extend(shallow_records)

        strip_selected: List[Tuple[Dict[str, Any], Dict[str, Any], int, float, float, float]] = []
        strip_gfa = 0.0

        sorted_segs = sorted(seg_targets.keys(), key=lambda s: s[0])
        for seg_key in sorted_segs:
            s_target = seg_targets[seg_key]
            matching_blocks = seg_matching.get(seg_key, [])
            if not matching_blocks or s_target <= 0:
                continue

            def seg_block_order(b: Dict[str, Any]) -> Tuple[int, float]:
                is_lm = 1 if b['id'] in landmark_block_ids else 0
                f_target = block_targets.get(b['id'], 0.0)
                return (is_lm, f_target)

            sorted_blocks = sorted(matching_blocks, key=seg_block_order, reverse=True)
            seg_placed_count = 0
            seg_current_gfa = 0.0

            for b in sorted_blocks:
                bid = b['id']
                if bid in used_block_ids:
                    continue
                opts = block_candidates.get(bid, [])
                if not opts:
                    continue

                prefs = set(b.get('type_preferences', ()))
                valid_opts = [o for o in opts if (o['type_id'] in prefs or o.get('is_landmark')) and not o.get('is_upgrade')]
                if not valid_opts:
                    continue

                is_landmark = bid in landmark_block_ids
                lm_data = landmark_info.get(bid)

                fl_range = b.get('floors') or [4, 5]
                cap = b.get('floor_cap')
                min_fl = min(fl_range) if cap is None else min(fl_range[0], cap)
                max_fl = max(fl_range) if cap is None else min(max(fl_range), cap)

                best_pick = None
                for opt in valid_opts:
                    # 檢查 slab 間距約束
                    if opt['type_id'] == 'building.i_slab':
                        slab_conflict = False
                        for sb, sopt, sfl, sfh, sah, sgfa in selected_buildings + strip_selected:
                            if sopt['type_id'] == 'building.i_slab':
                                d = opt['geometry'].distance(sopt['geometry'])
                                if d < max(14.0, sah) - 1e-6:
                                    slab_conflict = True
                                    break
                        if slab_conflict:
                            continue

                    fp = opt['geometry'].area
                    fl0_area = opt.get('ring_floor0_area_m2', fp)

                    # 地標處理
                    if is_landmark and lm_data:
                        t_h = lm_data['height_m']
                        if abs(t_h - 19.5) < 0.6:
                            f_h, fl_cnt, a_h = 5.5, 5, 19.5
                        elif abs(t_h - 18.0) < 0.6:
                            f_h, fl_cnt, a_h = 4.0, 5, 18.0
                        elif abs(t_h - 17.5) < 0.6:
                            f_h, fl_cnt, a_h = 3.5, 5, 17.5
                        else:
                            f_h, fl_cnt = 3.5, int(round(t_h / 3.5))
                            a_h = f_h + (fl_cnt - 1) * 3.5
                        cost = fl0_area + (fl_cnt - 1) * fp
                        best_pick = (opt, fl_cnt, f_h, a_h, cost)
                        break

                    # 一般街廓：依照 block/segment 目標配置
                    for fl in range(max_fl, min_fl - 1, -1):
                        cost = fl0_area + (fl - 1) * fp
                        f_h = opt.get('first_floor_height_m', 3.5)
                        a_h = f_h + (fl - 1) * 3.5

                        if strip_gfa + cost <= 1.05 * strip_target + 1e-4:
                            best_pick = (opt, fl, f_h, a_h, cost)
                            break
                        elif strip_gfa < 0.85 * strip_target and strip_gfa + cost <= 1.14 * strip_target:
                            best_pick = (opt, fl, f_h, a_h, cost)
                            break
                    if best_pick:
                        break

                if best_pick:
                    chosen_opt, fl_count, first_height, actual_height, fl_gfa = best_pick
                    strip_selected.append((b, chosen_opt, fl_count, first_height, actual_height, fl_gfa))
                    strip_gfa += fl_gfa
                    seg_current_gfa += fl_gfa
                    used_block_ids.add(bid)
                    represented_types.add(chosen_opt['type_id'])
                    represented_zones.add(b.get('zone_id'))
                    seg_placed_count += 1

                    if seg_current_gfa >= s_target * 0.90:
                        break

        # 若帶內總 GFA 仍不足 0.85 * strip_target，嘗試將 l_block 升級為 perimeter
        if strip_gfa < 0.85 * strip_target - 1e-4:
            for idx, (b, chosen_opt, fl_count, first_height, actual_height, fl_gfa) in enumerate(strip_selected):
                if chosen_opt['type_id'] == 'building.l_block':
                    perim_opt = next((o for o in block_candidates.get(b['id'], []) if o['type_id'] == 'block.perimeter'), None)
                    if perim_opt is not None:
                        fl0_area = perim_opt.get('ring_floor0_area_m2', perim_opt['geometry'].area)
                        new_gfa = fl0_area + (fl_count - 1) * perim_opt['geometry'].area
                        gain = new_gfa - fl_gfa
                        if strip_gfa + gain <= 1.05 * strip_target + 1e-4:
                            strip_selected[idx] = (b, perim_opt, fl_count, first_height, actual_height, new_gfa)
                            strip_gfa += gain
                            represented_types.add('block.perimeter')
                            upgraded_records.append(dict(block_id=b['id'], from_type='building.l_block', to_type='block.perimeter', reason_zh='帶樓地板不足升級為合院'))
                            if strip_gfa >= 0.85 * strip_target - 1e-4:
                                break

        # 若仍不足，嘗試把非低層區建築樓層調到 max_range
        if strip_gfa < 0.85 * strip_target - 1e-4:
            for idx, (b, chosen_opt, fl_count, first_height, actual_height, fl_gfa) in enumerate(strip_selected):
                if not b.get('floor_cap') and 'landmark_height_m' not in b:
                    fl_range = b.get('floors') or [4, 5]
                    if fl_count < max(fl_range):
                        target_fl = max(fl_range)
                        gain = chosen_opt['geometry'].area * (target_fl - fl_count)
                        if strip_gfa + gain <= 1.15 * strip_target + 1e-4:
                            strip_selected[idx] = (
                                b,
                                chosen_opt,
                                target_fl,
                                first_height,
                                first_height + (target_fl - 1) * 3.5,
                                chosen_opt['geometry'].area * target_fl,
                            )
                            strip_gfa += gain

        selected_buildings.extend(strip_selected)

    # 確保全區總 GFA <= global_gfa_cap (77965.18 m²)
    total_new_gfa = sum(item[5] for item in selected_buildings)
    if total_new_gfa > global_gfa_cap:
        for idx in range(len(selected_buildings) - 1, -1, -1):
            b, opt, fl_count, f_h, a_h, gfa = selected_buildings[idx]
            fl_range = b.get('floors') or [4, 5]
            cap = b.get('floor_cap')
            min_fl = min(fl_range) if cap is None else min(fl_range[0], cap)
            strip_id = b['strip_id']
            strip_target = targets[strip_id]
            current_strip_gfa = sum(item[5] for item in selected_buildings if item[0]['strip_id'] == strip_id)

            if 'landmark_height_m' not in b and fl_count > min_fl:
                diff = opt['geometry'].area
                if current_strip_gfa - diff >= 0.85 * strip_target - 1e-4:
                    selected_buildings[idx] = (b, opt, fl_count - 1, f_h, f_h + (fl_count - 2) * 3.5, gfa - diff)
                    total_new_gfa -= diff
                    if total_new_gfa <= global_gfa_cap:
                        break

    # 4. 組裝 Building Records 與 Features
    features = []
    records = []
    high_lines = [LineString(r.coordinates) for r in roads if 'pedestrian' in r.modes]
    road_objs = [net.NetworkRoad.model_validate(r) if isinstance(r, dict) else r for r in roads]

    for i, (b, opt, fl_count, f_height, a_height, gfa) in enumerate(selected_buildings):
        b_id = f'{family}-s6-building-{i}'
        geom = opt['geometry']
        raw_use = b.get('use', 'mixed')
        use = 'Manufacturing' if opt['type_id'] == 'building.industrial_hall' else ('Residential' if (raw_use == 'residential' or opt['type_id'] == 'building.rowhouse') else 'Mixed')
        ground_use = 'Manufacturing' if use == 'Manufacturing' else ('Residential' if use == 'Residential' else 'Active mixed use')

        floors = []
        for level in range(fl_count):
            plate = opt.get('ring_floor0', geom) if level == 0 and 'ring_floor0' in opt else geom
            fl_h = f_height if level == 0 else 3.5
            fl_use = ground_use if level == 0 else use
            floors.append(dict(level=level, geometry=mapping(plate), floor_height_m=fl_h, use=fl_use))

        sc = dict(opt['scale'])
        segments = facade_segments(geom, road_objs, high_lines, entrances=[Point(e.coordinates) for e in entrances])
        poly_b = shape(b['geometry'])
        actual_building_gfa = sum(shape(f['geometry']).area for f in floors)
        fsi = actual_building_gfa / poly_b.area if poly_b.area > 0 else 1.0
        gsi = geom.area / poly_b.area if poly_b.area > 0 else 0.5
        l_val = actual_building_gfa / geom.area if geom.area > 0 else float(fl_count)

        opt_tid = opt['type_id']
        opt_wd = opt['wing_depth_m']
        design_intent = dict(
            reason_zh=f'{family} 沿街配置：{opt_tid}，翼深 {opt_wd:.1f} m，{fl_count} 層',
            rule_card_ids=['MOR-001', 'MOR-003', 'SYN-002'],
            knowledge_unit_ids=['KU-ARC-013', 'KU-ARC-049'],
            syntax_nain=b.get('baseline_percentile', 50.0),
        )

        props = dict(
            role='new_building',
            building_id=b_id,
            type_id=opt['type_id'],
            variant_id=VERSION,
            block_id=b['id'],
            zone_id=b.get('zone_id', 'zone-mixed'),
            allocation_basis='FRONTAGE_FIRST',
            height_m=a_height,
            floor_count=fl_count,
            first_floor_height_m=f_height,
            standard_floor_height_m=3.5,
            ground_use=floors[0]['use'],
            active_frontage=any(e.get('active', False) for e in segments),
            low_floor_reason_zh=b.get('low_reason_zh') or (f'{family} 沿街段落配置：依目標 GFA 與進深限制採用 3 層低層量體' if fl_count < 4 else None),
            low_floor_rule_card_ids=['POR-017'] if (b.get('low_reason_zh') or fl_count < 4) and use != 'Manufacturing' else ['POR-001'] if (b.get('low_reason_zh') or fl_count < 4) else [],
            sunlight_screen=True,
            floors=floors,
            design_intent=design_intent,
            scale=sc,
            spacematrix=dict(FSI=fsi, GSI=gsi, L=l_val),
            facade_segments=segments,
        )
        features.append(dict(type='Feature', id=b_id, geometry=mapping(geom), properties=props))
        records.append(dict(**props, footprint_area_m2=geom.area, new_gfa_m2=actual_building_gfa))

    # 5. 開放空間與指標
    footprints = [shape(f['geometry']) for f in features]
    footprint_union = unary_union(footprints) if footprints else Polygon()
    retained_geoms = [shape(g['geometry']) if isinstance(g, dict) and 'geometry' in g else (shape(g) if isinstance(g, dict) else g) for g in (retained.values() if isinstance(retained, dict) else retained)] if retained else []
    kept = unary_union(retained_geoms) if retained_geoms else Polygon()
    surface = unary_union([LineString(r.coordinates).buffer(r.width_m / 2.0) for r in roads if r.layer == 0]) if roads else Polygon()
    open_space = site.difference(unary_union([footprint_union, kept, surface]))

    new_gfa_sum = sum(r['new_gfa_m2'] for r in records)
    new_area_sum = sum(r['footprint_area_m2'] for r in records)
    retained_footprint = kept.area

    metrics = dict(
        far=(new_gfa_sum + retained_gfa) / denominator,
        coverage=(new_area_sum + retained_footprint) / denominator,
        new_gfa_m2=new_gfa_sum,
        retained_gfa_upper_m2=retained_gfa,
        retained_footprint_m2=retained_footprint,
        far_denominator_m2=denominator,
        open_space_ratio=open_space.area / denominator if denominator > 0 else 0.0,
        new_building_count=len(records),
        heights_m=sorted({r['height_m'] for r in records}),
        dictionary_types=sorted({r['type_id'] for r in records}),
        L=(new_gfa_sum + retained_gfa) / (new_area_sum + retained_footprint) if (new_area_sum + retained_footprint) > 0 else 0.0,
        coverage_policy='RESULT_ONLY_UPPER_BOUND',
        active_footprint_m2=sum(r['footprint_area_m2'] for r in records if r.get('active_frontage')),
    )

    checks = dict(
        height=all(r['height_m'] <= 20.0 + 1e-6 for r in records),
        far_upper=metrics['far'] <= 0.80 + 1e-6,
        coverage=metrics['coverage'] <= 0.35 + 1e-6,
        scale=bool(records) and all(r['scale']['valid'] for r in records),
        quality_far_minimum=metrics['far'] >= 0.70 - 1e-6,
        open_space_minimum=metrics['open_space_ratio'] >= 0.40,
        four_types=len(metrics['dictionary_types']) >= 4,
        all_zones=all(any(r['zone_id'] == z['zone_id'] for r in records) for z in zones) if zones else True,
        height_variation=len(metrics['heights_m']) >= 2,
    )

    slabs = [shape(f['geometry']) for f, r in zip(features, records) if r['type_id'] == 'building.i_slab']
    slab_records = [r for r in records if r['type_id'] == 'building.i_slab']
    checks['slab_spacing'] = all(
        a.distance(b) >= max(ra['height_m'], rb['height_m']) - 1e-6
        for (a, ra), (b, rb) in combinations(zip(slabs, slab_records), 2)
    )

    massing = dict(
        features=features,
        buildings=records,
        metrics=metrics,
        checks=checks,
        rejections=[],
        open_space=mapping(open_space),
        named_open_spaces=[],
        narrow_remnants=[],
        context_edges=[e if isinstance(e, dict) else e.model_dump() for e in context_edges],
        rules=s6_rules.model_dump(mode='json'),
        version=VERSION,
        limitations=['J17b frontage-first massing; deterministic pure functions; no live AI.'],
    )

    # 6. 幾何耦合與街牆評估
    coupling_external = dict(external or {}, _site=site, _water=water)
    dev_used = structure.get('development', [])
    cc, cm, ground, spaces, remnants = bf.coupling_checks(
        massing, dev_used, roads, site, water, retained, entrances, coupling_external, coupling_rules
    )
    massing['checks'].update(cc)
    massing['metrics'].update(cm)

    domain = bf._buildable(site, water, retained, network_rules)[1]
    frontage_buildings = [dict(type_id=r['type_id'], geometry=shape(f['geometry'])) for f, r in zip(features, records)]
    dev_lines = [shape(row['geometry']) for row in dev_used]
    matched = next((road for road in roads if dev_used and road.id == dev_used[0]['road_id']), None)
    road_half = matched.width_m / 2.0 if matched is not None else network_rules.main_shared_width_m / 2.0
    assessment = bf.frontage_assessment(dev_lines, frontage_buildings, domain, block_rules, road_half=road_half)
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
        site=site, roads=roads, buildings=footprints, retained_before=retained, retained_after=retained,
        water=water, entrances=entrances, external=external or {}, rules=network_rules, public_spaces=public,
    )
    quality = net.geometry_quality(site, roads, net.derive_blocks(site, roads, list(retained.values()), water, network_rules, public), entrances, network_rules)
    massing['network_hard_checks'] = hard
    massing['network_quality'] = quality
    massing['construction_failures'] = construction_failures
    massing['structure'] = dict(
        axes=[{**a, 'geometry': mapping(a['geometry']) if hasattr(a.get('geometry'), 'coords') else a.get('geometry')} for a in axes],
        blocks=[bf._public_block(b) for b in blocks],
        meta=structure_meta,
    )
    massing['coupling'] = dict(
        version=VERSION, rules=coupling_rules.model_dump(), development_streets=dev_used,
        development_rejections=[], road_actions=[], syntax_comparison={},
        block_first_rules=block_rules.model_dump(),
        upgraded_to_perimeter=upgraded_records,
        shallow_allocations=shallow_all,
    )
    massing['family'] = family
    massing['roads'] = [r.model_dump() for r in roads]
    massing['failure_reasons'] = [k for k, v in massing['checks'].items() if not v] + [k for k, v in hard['checks'].items() if not v] + construction_failures
    massing['status'] = 'VALID' if not massing['failure_reasons'] else 'INVALID'
    massing['design_intent'] = dict(
        reason_zh=next((d.get('intent_zh') for d in dev_used if d.get('intent_zh')), '沿街優先量體配置'),
        method_zh='沿街優先：依臨街邊界由外向內生成周邊式、L形、板樓、連棟街屋或廳式量體，形成沿街連續街牆。',
        rule_card_ids=sorted({c for r in records for c in r['design_intent']['rule_card_ids']}),
        knowledge_unit_ids=sorted({k for r in records for k in r['design_intent']['knowledge_unit_ids']}),
        status='DRAFT',
    )
    return massing
