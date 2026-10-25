"""FAB2 本地框架的確定性執行與實體幾何檢查，無 I/O 或批准效果。"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from shapely import make_valid

from shapely.affinity import affine_transform, rotate
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape
from shapely.ops import unary_union
from shapely.prepared import prep

from .fabric_plan import MODES, _feature, _geom, _parts


@dataclass(frozen=True)
class IntentFrame:
    origin: tuple[float, float]
    angle: float

    @classmethod
    def parse(cls, value: dict) -> IntentFrame:
        origin = tuple(value['origin_epsg28992'])
        angle = 90 - value['axis_azimuth_deg']
        if len(origin) != 2 or not all(math.isfinite(x) for x in (*origin, angle)):
            raise ValueError('意圖座標框架必須為有限數值')
        return cls(origin, angle)

    def world(self, geometry):
        c, s = math.cos(math.radians(self.angle)), math.sin(math.radians(self.angle))
        return affine_transform(geometry, [c, -s, s, c, *self.origin])

    def local(self, geometry):
        c, s = math.cos(math.radians(self.angle)), math.sin(math.radians(self.angle))
        x, y = self.origin
        return affine_transform(geometry, [c, s, -s, c, -c*x-s*y, s*x-c*y])


def _rect(values):
    u0, u1, v0, v1 = values
    if not all(math.isfinite(v) for v in values) or u1 <= u0 or v1 <= v0:
        raise ValueError('rect_uv 必須為遞增且有限的四個座標')
    return box(u0, v0, u1, v1)


def _zone_geometry(zone, frame):
    return frame.world(rotate(_rect(zone['rect_uv']), zone.get('rotation_deg', 0), origin='center'))


def _polygons(geometry):
    return [g for p in _parts(geometry) for g in (_polygons(p) if p.geom_type == 'GeometryCollection' else [p])
            if g.geom_type == 'Polygon' and g.area > 1e-8]


def _dimensions(geometry):
    if geometry.is_empty:
        return (0., 0.)
    hull = geometry.convex_hull
    if hull.geom_type != 'Polygon':
        return (0., hull.length)
    # 以凸包邊方向求最小包絡；先減形心避免大座標的數值消去。
    cx,cy = hull.centroid.coords[0]
    points = [(x-cx,y-cy) for x,y in list(hull.exterior.coords)[:-1]]
    best = (math.inf,(0.,0.))
    for (x,y),(a,b) in zip(points,points[1:]+points[:1]):
        length = math.hypot(a-x,b-y)
        if length < 1e-8:
            continue
        c,s = (a-x)/length,(b-y)/length
        us,vs = [c*u+s*v for u,v in points],[-s*u+c*v for u,v in points]
        dims = (max(us)-min(us),max(vs)-min(vs))
        if dims[0]*dims[1] < best[0]:
            best = (dims[0]*dims[1],tuple(sorted(dims)))
    return best[1]


def _clean(geometry):
    if geometry.is_valid:
        return geometry
    repaired = make_valid(geometry)
    if abs(repaired.area-geometry.area) > .01:
        raise ValueError('旋轉計算的拓樸修復超過0.01平方公尺，停止避免改變意圖')
    return repaired


def _fragment(geometry):
    # 三角形即使面積大，也不是正交建築街廓。
    return geometry.area < 1500 - 1e-6 or _dimensions(geometry)[0] < 30 - 1e-6 or len(geometry.exterior.coords) == 4


def _largest_rectangle(domain, step=2., minimum=(0.,0.)):
    """最大全覆蓋格網矩形；格網只選址，不裁切／扭曲樣板足跡。"""
    if domain.is_empty:
        return None
    x0, y0, x1, y1 = domain.bounds
    if domain.equals(domain.envelope):
        return domain.envelope if x1-x0 >= minimum[0] and y1-y0 >= minimum[1] else None
    nx, ny = math.floor((x1-x0)/step), math.floor((y1-y0)/step)
    if not nx or not ny:
        return None
    safe = prep(domain.buffer(1e-7))
    heights = [0]*nx
    best = (0, None)
    for iy in range(ny):
        for ix in range(nx):
            cell = box(x0+ix*step, y0+iy*step, x0+(ix+1)*step, y0+(iy+1)*step)
            heights[ix] = heights[ix]+1 if safe.covers(cell) else 0
        stack = []
        for ix in range(nx+1):
            height = heights[ix] if ix < nx else 0
            start = ix
            while stack and stack[-1][1] > height:
                left, h = stack.pop()
                area = h*(ix-left)
                if area > best[0] and (ix-left)*step >= minimum[0] and h*step >= minimum[1]:
                    best = (area, box(x0+left*step, y0+(iy+1-h)*step, x0+ix*step, y0+(iy+1)*step))
                start = left
            if height and (not stack or stack[-1][1] < height):
                stack.append((start, height))
    return best[1]


SUPPORTED = {
    'block.rowhouse_strip', 'building.industrial_hall', 'building.i_slab',
    'building.u_block', 'building.courtyard_closed', 'building.courtyard_open_corner',
    'block.perimeter', 'block.hybrid', 'block.open', 'building.comb',
}
COMPONENTS = {
    'block.rowhouse_strip': {'building.rowhouse'},
    'block.perimeter': {'building.courtyard_closed'},
    'block.hybrid': {'building.courtyard_closed', 'building.industrial_hall'},
    'block.open': {'building.i_slab', 'building.point_array'},
}


def _templates(rectangle, zone):
    """重用 FAB1 正交矩形翼／連棟／板樓／廠房的組合方法。"""
    x0, y0, x1, y1 = rectangle.bounds
    w, h = x1-x0, y1-y0
    kind = zone['typology']
    front = zone.get('frontage', ['south'])
    if front and front[0] in {'east','west'}:
        # 先把指定臨街面轉為樣板的北／南面，再還原；軸向仍為正交。
        transformed = copy.deepcopy(zone)
        directions = {'east':'north','west':'south','north':'west','south':'east'}
        transformed['frontage'] = [directions[v] for v in front]
        g = rotate(rectangle,90,origin='center')
        templates, voids = _templates(g,transformed)
        center = rectangle.centroid.coords[0]
        return ([(rotate(p,-90,origin=center),k,d) for p,k,d in templates],
                [rotate(p,-90,origin=center) for p in voids])
    depth = 12.
    shapes = []
    courts = []
    def add(g, component, d):
        if not g.is_empty and g.area > 1:
            shapes.append((g, component, d))
    if kind == 'block.rowhouse_strip':
        n = math.ceil(w/8)
        if n and w/n < 5.4:
            return [], []
        if n and h >= depth:
            ys = [y1-depth if front[0] == 'north' else y0]
            if h >= 2*depth+20:
                ys.append(y0 if ys[0] != y0 else y1-depth)
                courts.append(box(x0, y0+depth, x1, y1-depth))
            for y in ys:
                for i in range(n):
                    add(box(x0+i*w/n, y, x0+(i+1)*w/n, y+depth), 'building.rowhouse', depth)
    elif kind in {'building.industrial_hall', 'building.i_slab', 'block.open'}:
        d = min(30., h) if kind == 'building.industrial_hall' else depth
        if d < (20 if kind == 'building.industrial_hall' else 10):
            return [], []
        n = max(1, math.ceil(w/(60 if kind == 'building.industrial_hall' else 90)))
        module = (w-(n-1)*6)/n
        if module < 20:
            return [], []
        ys = [y1-d if front[0] == 'north' else y0]
        if h >= 2*d+20 and kind != 'building.industrial_hall':
            ys.append(y0 if ys[0] != y0 else y1-d)
        for y in ys:
            for i in range(n):
                x = x0+i*(module+6)
                add(box(x, y, x+module, y+d), 'building.industrial_hall' if kind == 'building.industrial_hall' else 'building.i_slab', d)
    else:
        # 住宅翼可用10–14m；狹帶採10m而中庭仍維持至少20m。
        required = 52 if kind == 'block.hybrid' else (32 if kind=='building.comb' else 40)
        if w < 40 or h < required:
            return [], []
        if min(w,h) < 44 and kind != 'block.hybrid':
            depth = 10.
        # 優先完整大中庭樣板，不把長矩形均分成過密的小院落。
        module_width = 120 if kind=='building.comb' else 69
        nx, ny = max(1, math.ceil(w/module_width) if kind=='building.comb' else math.floor(w/69)), max(1,math.floor(h/69))
        cw, ch = min(w/nx,module_width), min(h/ny,69)
        for ix in range(nx):
            for iy in range(ny):
                depth = 10. if min(cw,ch) < 44 and kind!='block.hybrid' else 12.
                a, b = x0+ix*w/nx, y0+iy*h/ny
                z, t = a+cw, b+ch
                component = 'building.courtyard_closed' if kind in {'block.perimeter', 'block.hybrid'} else kind
                if kind == 'building.comb':
                    # 一條脊與分離指狀翼；不以封閉院落假冒梳狀。
                    spine_north = 'north' in front
                    add(box(a,t-depth,z,t) if spine_north else box(a,b,z,b+depth),component,depth)
                    fingers = max(2, min(5, math.floor((cw+20)/(depth+20))))
                    gap = (cw-fingers*depth)/(fingers-1)
                    for i in range(fingers):
                        x = a+i*(depth+gap)
                        add(box(x,b,x+depth,t-depth) if spine_north else box(x,b+depth,x+depth,t),component,depth)
                        if i < fingers-1:
                            courts.append(box(x+depth,b,x+depth+gap,t-depth) if spine_north else box(x+depth,b+depth,x+depth+gap,t))
                    continue
                if kind == 'building.u_block':
                    # 北岸臨Keileweg的脊在北，開口朝南側水岸；不套用向東開口的U。
                    spine_north = front[0]=='north'
                    add(box(a,t-depth,z,t) if spine_north else box(a,b,z,b+depth),component,depth)
                    for x in (a,z-depth):
                        add(box(x,b,x+depth,t-depth) if spine_north else box(x,b+depth,x+depth,t),component,depth)
                    courts.append(box(a+depth,b,z-depth,t-depth) if spine_north else box(a+depth,b+depth,z-depth,t))
                    continue
                south_depth = 20 if kind == 'block.hybrid' else depth
                if ch-south_depth-depth < 20:
                    continue
                add(box(a, b, z, b+south_depth), 'building.industrial_hall' if kind == 'block.hybrid' else component, south_depth)
                add(box(a, t-depth, z, t), component, depth)
                add(box(a, b+south_depth, a+depth, t-depth), component, depth)
                if kind != 'building.u_block':
                    start = b+south_depth+(8 if kind == 'building.courtyard_open_corner' else 0)
                    if t-depth > start:
                        add(box(z-depth, start, z, t-depth), component, depth)
                courts.append(box(a+depth, b+south_depth, z-depth, t-depth))
    return shapes, courts


def execute_intent(intent: dict, facts: dict, dictionary: dict) -> dict:
    if facts['geometry']['crs'] != 'EPSG:28992':
        raise ValueError('CRS_MISMATCH')
    intent = copy.deepcopy(intent)
    frame = IntentFrame.parse(intent['frame'])
    site = shape(facts['geometry']['site'])
    water = site.intersection(shape(facts['geometry']['water']))
    land = site.difference(water)
    waterfront = shape(facts['geometry']['waterfront_band']).intersection(land)
    original_buildable = shape(facts['geometry']['buildable']).intersection(land)
    retained = copy.deepcopy(facts.get('retained_buildings', []))
    retained_union = unary_union([shape(r['geometry']) for r in retained])
    retained_clearance = retained_union.buffer(6, join_style=2)
    allowed = original_buildable.union(waterfront).difference(retained_clearance).intersection(land)
    buildable = original_buildable.difference(waterfront).difference(retained_clearance)
    issues, roads, land_use, blocks, buildings, courts, instances = [], [], [], [], [], [], []
    def issue(kind, location, message, geometry=None, **details):
        issues.append({'kind': kind, 'location': location, 'message_zh': message,
                       'geometry': mapping(geometry) if geometry is not None else None, **details})
    def allocate(g, category, name, **properties):
        if not g.is_empty:
            land_use.append(_feature(g, f'allocation-{len(land_use)}', category=category,
                name_zh=name, manager='公共空間管理' if category in {'parks','plazas','waterfront','roads'} else '街廓管理',
                **properties))
    for street in intent['streets']:
        if street['width_m'] <= 0 or not math.isfinite(street['width_m']) or len(street['polyline']) < 2:
            raise ValueError('意圖道路需正寬度及至少兩個座標')
        raw = frame.world(LineString(street['polyline']))
        expected_row = raw.buffer(street['width_m']/2, cap_style=2, join_style=2).intersection(land)
        actual_row = expected_row.intersection(allowed)
        conflict = expected_row.difference(allowed)
        if conflict.area > .01:
            issue('street_conflict', street['id'], '意圖路權碰到保留建築六公尺緩衝或不可配置土地；原意圖未改動。', conflict,
                  lost_area_m2=conflict.area)
        actual = raw.intersection(allowed)
        if not actual.is_empty:
            roads.append(_feature(actual, street['id'], role=street['role'], width_m=street['width_m'],
                modes=copy.deepcopy(street['modes']), intent_street_id=street['id'], right_of_way=mapping(actual_row)))
        else:
            issue('street_missing', street['id'], '意圖道路裁切後沒有可用中心線。', raw)
    road_union = unary_union([shape(r['properties']['right_of_way']) for r in roads])
    # 道路優先；公園與其交集不能重複計入土地預算。
    allocate(retained_union.intersection(land), 'retained_buildings', '保留建築用地')
    allocate(road_union, 'roads', '框架路權')
    occupied = retained_union.union(road_union)
    park_rows = []
    for i, park in enumerate(intent['parks']):
        expected = frame.world(_rect(park['rect_uv']))
        actual = expected.intersection(allowed).difference(occupied)
        category = 'plazas' if park.get('type') == 'plaza' else 'parks'
        allocate(actual, category, park['name_zh'], intent_park_index=i, intent_base_geometry=mapping(actual))
        if not actual.is_empty:
            park_rows.append(land_use[-1])
        occupied = occupied.union(actual)
        if actual.area < .9*expected.area:
            issue('park_conflict', park['name_zh'], '公園／廣場經道路及限制裁切後不足意圖面積九成。', expected.difference(actual),
                  required_area_m2=.9*expected.area, actual_area_m2=actual.area)
    rejected = []
    entries = dictionary.get('entries', {})
    for zone in intent['zones']:
        lo, hi = zone['floors']
        if type(lo) is not int or type(hi) is not int or not 1 <= lo <= hi or hi > 5:
            raise ValueError('意圖樓層須為1至5層的有序整數範圍')
        if any(v not in {'north','south','east','west'} for v in zone.get('frontage',[])):
            raise ValueError('意圖 frontage 須為 north／south／east／west')
        raw_zone = _zone_geometry(zone, frame)
        overlap = raw_zone.intersection(unary_union([_geom(b) for b in blocks]))
        if overlap.area > .01:
            issue('zone_overlap', zone['id'], '意圖 zone 與先前 zone 重疊；不重複分配。', overlap)
        available = raw_zone.intersection(buildable).difference(occupied)
        angle = frame.angle+zone.get('rotation_deg', 0)
        uv_center = _rect(zone['rect_uv']).centroid
        center = frame.world(uv_center).coords[0]
        to_local = lambda g: rotate(g, -angle, origin=center)
        to_world = lambda g: rotate(g, angle, origin=center)
        for fragment in _polygons(available):
            if _fragment(fragment):
                name = f'街角口袋綠地（{len(rejected)+1}）'
                allocate(fragment, 'parks', name, source_zone_id=zone['id'], role='不足尺度街廓轉綠地')
                rejected.append({'zone_id':zone['id'], 'area_m2':fragment.area, 'short_m':_dimensions(fragment)[0],
                                 'geometry':mapping(fragment), 'name_zh':name})
                occupied = occupied.union(fragment)
                continue
            bid = f'block-{len(blocks)}'
            blocks.append(_feature(fragment, bid, zone_id=zone['id'], typology=zone['typology'],
                axis_azimuth_deg=(90-angle)%180, rotation_deg=zone.get('rotation_deg',0), floors=zone['floors']))
            allocate(fragment, 'blocks', '框架建築街廓', block_id=bid, zone_id=zone['id'])
            occupied = occupied.union(fragment)
            if zone['typology'] not in SUPPORTED or zone['typology'] not in entries:
                issue('unsupported_template', zone['id'], '意圖零件缺少本地字典或正交樣板；保留空街廓並揭露失敗。', fragment)
                continue
            domain = _clean(to_local(fragment))
            # 每個真實街廓至多抽取8個完整正交樣板包絡；不把斜邊剪成建築。
            for _ in range(8):
                kind = zone['typology']
                minimum = ((5.4,12) if kind=='block.rowhouse_strip' else
                           (20,20) if kind=='building.industrial_hall' else
                           (20,12) if kind in {'building.i_slab','block.open'} else
                           (40,52) if kind=='block.hybrid' else
                           (40,32) if kind=='building.comb' else (40,40))
                rect = _largest_rectangle(domain, minimum=minimum)
                if rect is None or min(_dimensions(rect)) < 10:
                    break
                candidates, voids = _templates(rect, zone)
                if not candidates:
                    break
                instances.append({'block_id':bid,'zone_id':zone['id'], 'local_rectangle':mapping(rect),
                                  'center_epsg28992':center,'angle_deg':angle})
                for g, component, depth in candidates:
                    world = to_world(g)
                    if not fragment.buffer(1e-7).covers(world):
                        continue
                    buildings.append(_feature(world, f'new-{len(buildings)}', block_id=bid, zone_id=zone['id'],
                        retained=False, intent_typology=zone['typology'], building_type=component,
                        template='orthogonal_rectangle', depth_m=depth, floors=lo, min_floors=lo, max_floors=hi,
                        height_m=4+3.5*(lo-1), first_floor_height_m=4., standard_floor_height_m=3.5,
                        use='industrial' if component=='building.industrial_hall' else 'residential',
                        axis_azimuth_deg=(90-angle)%180))
                for g in voids:
                    if fragment.buffer(1e-7).covers(to_world(g)):
                        courts.append(_feature(to_world(g), f'court-{len(courts)}', block_id=bid,
                            clear_width_m=_dimensions(g)[0], label_zh='共用中庭'))
                domain = _clean(domain.difference(rect.buffer(3, join_style=2)))
    for block in blocks:
        if not any(b['properties']['block_id']==block['id'] for b in buildings):
            issue('template_search_limit',block['properties']['zone_id'],
                  '本次有界矩形搜尋未配置出指定樣板；這是執行限制，不是意圖不可行的證明。',_geom(block),block_id=block['id'])
    # 所有陸地都必須有管理歸屬；剩餘地按距離併入既有公園／廣場。
    for remainder in _polygons(land.difference(occupied)):
        if park_rows:
            host = min(park_rows, key=lambda row: remainder.distance(_geom(row)))
            host['geometry'] = mapping(_geom(host).union(remainder))
            host['properties']['absorbed_remainder_area_m2'] = host['properties'].get('absorbed_remainder_area_m2',0)+remainder.area
        else:
            allocate(remainder, 'parks', '基地邊界公共綠地', role='框架剩餘地管理')
            park_rows.append(land_use[-1])
    target = 146873.
    gfa = sum(_geom(b).area*b['properties']['floors'] for b in buildings)
    # 固定足跡，以每棟整數層調整；每次不得超過目標上限。
    for _ in range(5):
        changed = False
        for building in sorted(buildings, key=lambda b: (-_geom(b).area, b['id'])):
            q, area = building['properties'], _geom(building).area
            if q['floors'] < q['max_floors'] and gfa+area <= target+1e-6:
                q['floors'] += 1
                q['height_m'] = 4+3.5*(q['floors']-1)
                gfa += area
                changed = True
        if not changed:
            break
    retained_landmarks={}
    for i, landmark in enumerate(intent.get('landmarks', [])):
        if not buildings:
            issue('landmark_missing', f'地標{i+1}', '沒有可設定地標的建築。')
            continue
        point = frame.world(Point(landmark['at_uv']))
        building = min(buildings, key=lambda b: point.distance(_geom(b)))
        closest_retained=min(retained,key=lambda r:point.distance(shape(r['geometry']))) if retained else None
        if closest_retained is not None and point.distance(shape(closest_retained['geometry']))<=point.distance(_geom(building)):
            existing_height=closest_retained.get('height_above_ground_m')
            if existing_height is not None and abs(existing_height-landmark['height_m'])<1e-6:
                retained_landmarks[closest_retained['id']]=i
            else:
                issue('landmark_retained_conflict',f'地標{i+1}',
                      '地標最近的建築是保留建築；指定高度與現況不符，不改保留建築，也不偷偷改選較遠的新建築。',
                      shape(closest_retained['geometry']),building_id=closest_retained['id'],
                      requested_height_m=landmark['height_m'],existing_height_m=existing_height)
            continue
        floors = 1+(landmark['height_m']-4)/3.5
        q = building['properties']
        if abs(floors-round(floors))<1e-6 and q['min_floors']<=round(floors)<=q['max_floors']:
            q['floors']=round(floors)
        else:
            issue('landmark_floor_conflict',f'地標{i+1}',
                  '最近建築的意圖樓層範圍與指定地標高度不相容；保留指定高度並回報樓層高度失敗。',
                  _geom(building),building_id=building['id'],required_height_m=landmark['height_m'],
                  allowed_floors=[q['min_floors'],q['max_floors']])
        building['properties'].update(height_m=landmark['height_m'], landmark_index=i)
    # 地標若提高樓層，重新在其餘建築的原意圖範圍內配平。
    gfa=sum(_geom(b).area*b['properties']['floors'] for b in buildings)
    while gfa>target+1e-6:
        candidates=[b for b in buildings if 'landmark_index' not in b['properties'] and
                    b['properties']['floors']>b['properties']['min_floors']]
        if not candidates:
            break
        excess=gfa-target
        large=[b for b in candidates if _geom(b).area>=excess]
        building=min(large or candidates,key=lambda b:_geom(b).area if large else -_geom(b).area)
        q=building['properties'];q['floors']-=1;q['height_m']=4+3.5*(q['floors']-1)
        gfa-=_geom(building).area
    new_footprint = unary_union([_geom(b) for b in buildings])
    for row in retained:
        buildings.append(_feature(shape(row['geometry']), row['id'], retained=True,
            source_record=copy.deepcopy(row), height_m=row.get('height_above_ground_m',0),
            floors=row.get('floor_count_upper',1), gfa_upper_m2=row.get('gfa_upper_m2',0),
            building_type='retained', use='retained'))
        buildings[-1]['geometry'] = copy.deepcopy(row['geometry'])
        if row['id'] in retained_landmarks:
            buildings[-1]['properties']['landmark_index']=retained_landmarks[row['id']]
    for mode in MODES:
        if not any(mode in r['properties']['modes'] for r in roads):
            issue('missing_mode', mode, {'fire':'意圖未指定消防模式，不推定汽車道路可供消防。',
                  'service':'意圖未指定服務模式。'}.get(mode, '意圖未指定此通行模式。'))
    plan = {'schema_version':'fab2-intent-plan-v1', 'crs':'EPSG:28992', 'fabric_id':intent['fabric'],
        'orientation_deg':intent['frame']['axis_azimuth_deg'], 'intent':intent, 'intent_issues':issues,
        'parameters':{'target_gfa_m2':target, 'density_status':'ASSUMED', 'first_floor_m':4., 'standard_floor_m':3.5,
                      'retained_buffer_m':6., 'rectangle_search_grid_m':2., 'maximum_rectangles_per_block':8},
        'site':mapping(site), 'water':mapping(water), 'buildable':mapping(buildable),
        'input_buildable':mapping(original_buildable), 'waterfront_band':mapping(waterfront),
        'roads':roads, 'blocks':blocks, 'buildings':buildings, 'land_use':land_use, 'courtyards':courts,
        'boundary_parcels':[], 'retained_inputs':retained,
        'entrances':copy.deepcopy(facts.get('entrances',facts['geometry'].get('entrances',[]))),
        'retained_road_inputs':copy.deepcopy(facts['geometry'].get('retained_roads',[])),
        'fragment_conversions':rejected, 'template_instances':instances,
        'fabric_dictionary':copy.deepcopy(dictionary.get('fabrics',{}).get(intent['fabric'],{})),
        'dictionary_entries':{k:copy.deepcopy(v) for k,v in entries.items() if k in {z['typology'] for z in intent['zones']}},
        'limitations':['探索草稿；未經指揮官跨供應商覆核及 Founder 接受。',
                       '格網搜尋是有界選址；樓層容量僅為本次已配置足跡容量，不是意圖可行性的全域上界。',
                       '文字概念中的院落數量與所有特殊間距未轉成完整機器契約；本輪有界樣板配置不能宣稱文字設計意圖已全數驗證。',
                       '通行檢查依實際路權面，不延伸意圖中心線；至少一公尺共邊或0.01平方公尺交疊才接通，為本輪探索性檢查假設。',
                       '未推定未指定的消防或服務權；保留道路寬度及模式缺來源，不自行指定。'],
        'metrics':{'new_gsi':new_footprint.area/land.area}}
    plan['validation'] = validate_intent_plan(plan)
    plan['metrics'] = plan['validation']['metrics']
    if not plan['validation']['checks']['NEW_GFA_TARGET']['passed']:
        issue('configured_density_limit',intent['fabric'],
              '本次已配置足跡與意圖樓層範圍未達密度目標；不宣稱這是意圖的全域容量上界。',
              new_gfa_m2=plan['metrics']['new_gfa_m2'], configured_capacity_m2=plan['metrics']['configured_footprint_capacity_m2'])
    return plan


def validate_intent_plan(plan: dict) -> dict:
    """從輸出幾何重算：快取metrics／意圖標籤不能使錯誤實體通過。"""
    checks = {}
    def check(key, ok, locations=None, **details):
        checks[key] = {'passed':bool(ok), 'status':'PASS' if ok else 'FAIL',
                       'failure_locations':locations or [], **details}
    def located(row, **details):
        return {'id':row['id'], 'geometry':row['geometry'], **details}
    intent = plan['intent']
    frame = IntentFrame.parse(intent['frame'])
    site, water = shape(plan['site']), shape(plan['water'])
    land = site.difference(water)
    area = land.area
    new = [b for b in plan['buildings'] if not b['properties'].get('retained')]
    retained = [b for b in plan['buildings'] if b['properties'].get('retained')]
    union = unary_union([_geom(row) for row in plan['land_use']])
    rows = plan['roads']+plan['blocks']+plan['buildings']+plan['land_use']
    check('CRS', plan['crs']=='EPSG:28992')
    bad = [located(r) for r in rows if _geom(r).is_empty or not _geom(r).is_valid]
    check('GEOMETRY_VALID', not bad, bad)
    remainder = land.difference(union)
    check('LAND_COVERAGE', remainder.area < .01 and union.difference(land).area < .01,
          [{'geometry':mapping(remainder)}] if remainder.area >= .01 else [], unallocated_m2=remainder.area)
    overlaps = []
    for i, row in enumerate(plan['land_use']):
        for other in plan['land_use'][i+1:]:
            g = _geom(row).intersection(_geom(other))
            if g.area > .01:
                overlaps.append({'ids':[row['id'],other['id']], 'geometry':mapping(g), 'area_m2':g.area})
    check('LAND_NO_OVERLAP', not overlaps, overlaps)
    total_percent = 100*sum(_geom(r).area for r in plan['land_use'])/area
    check('LAND_SUM_100_PERCENT', abs(total_percent-100) < 1e-5, percentage=total_percent)
    check('LAND_MANAGEMENT', all(r['properties'].get('name_zh') and r['properties'].get('manager') for r in plan['land_use']))
    semantic_bad=[]
    expected_categories={
        'roads':unary_union([shape(r['properties']['right_of_way']) for r in plan['roads']]),
        'blocks':unary_union([_geom(r) for r in plan['blocks']]),
        'retained_buildings':unary_union([_geom(r) for r in retained]).intersection(land),
    }
    for category,expected in expected_categories.items():
        actual=unary_union([_geom(r) for r in plan['land_use'] if r['properties']['category']==category])
        difference=expected.symmetric_difference(actual)
        if difference.area>.01:
            semantic_bad.append({'category':category,'geometry':mapping(difference),'difference_m2':difference.area})
    for r in plan['land_use']:
        if r['properties']['category'] not in {'roads','blocks','retained_buildings','parks','plazas'}:
            semantic_bad.append(located(r,reason_zh='未定義土地類別'))
    check('LAND_USE_CATEGORY_SEMANTICS',not semantic_bad,semantic_bad)
    bad = [located(b) for b in plan['blocks'] if _fragment(_geom(b))]
    check('BLOCK_MINIMUM', not bad and bool(plan['blocks']), bad)
    bad = [located(b) for b in new if not shape(plan['buildable']).buffer(1e-6).covers(_geom(b))]
    check('BUILDING_BUILDABLE', not bad, bad)
    bad = [located(b) for b in new if not land.buffer(1e-6).covers(_geom(b))]
    check('BUILDING_CONTAINMENT', not bad, bad)
    block_map = {b['id']:b for b in plan['blocks']}
    bad = [located(b) for b in new if b['properties'].get('block_id') not in block_map or
           not _geom(block_map[b['properties']['block_id']]).buffer(1e-6).covers(_geom(b))]
    check('BUILDING_BLOCK_MEMBERSHIP', not bad, bad)
    overlaps = []
    for i, b in enumerate(plan['buildings']):
        for other in plan['buildings'][i+1:]:
            g = _geom(b).intersection(_geom(other))
            if g.area > .01:
                overlaps.append({'ids':[b['id'],other['id']], 'geometry':mapping(g)})
    check('BUILDING_NO_OVERLAP', not overlaps, overlaps)
    originals = {r['id']:r for r in plan['retained_inputs']}
    check('RETAINED_UNCHANGED', len(retained)==len(originals) and all(b['id'] in originals and
          b['geometry']==originals[b['id']]['geometry'] and b['properties']['source_record']==originals[b['id']] for b in retained))
    keep = unary_union([shape(r['geometry']) for r in plan['retained_inputs']]).buffer(6,join_style=2)
    bad = [located(b) for b in new if _geom(b).intersection(keep).area > .01]
    check('RETAINED_6M_CLEARANCE', not bad, bad)
    bad = [located(b, height_m=b['properties']['height_m']) for b in new if not 0 < b['properties']['height_m'] <= 20]
    check('HEIGHT_CAP', not bad, bad)
    bad = [located(b) for b in new if abs(b['properties']['height_m']-(4+3.5*(b['properties']['floors']-1))) > 1e-6]
    check('FLOOR_HEIGHT', not bad, bad)
    gfa = sum(_geom(b).area*b['properties']['floors'] for b in new)
    capacity = sum(_geom(b).area*b['properties']['max_floors'] for b in new)
    check('NEW_GFA_TARGET', .9*146873-1e-6 <= gfa <= 146873+1e-6, new_gfa_m2=gfa,
          required_m2=[.9*146873,146873], configured_footprint_capacity_m2=capacity, status_basis='ASSUMED')
    bad = [located(b) for b in new if _geom(b).geom_type!='Polygon' or
           abs(math.prod(_dimensions(_geom(b)))-_geom(b).area)>.01]
    check('ORTHOGONAL_TEMPLATES', not bad, bad)
    # 實際矩形短邊與metadata翼深須同時成立；不可只信任depth_m。
    bad, slabs, terraces = [], [], []
    for b in new:
        q = b['properties']; short,long = _dimensions(_geom(b)); depth=q['depth_m']
        industrial = q['building_type']=='building.industrial_hall'
        limits = (20,30) if industrial else (10,14)
        if not limits[0]-1e-6 <= depth <= limits[1]+1e-6 or min(abs(short-depth),abs(long-depth))>.01:
            bad.append(located(b, depth_m=depth, actual_dimensions_m=[short,long]))
        if q['building_type']=='building.i_slab' and long>90+1e-6:
            slabs.append(located(b, long_m=long))
        if q['building_type']=='building.rowhouse' and not 5.4-1e-6 <= short <= 8+1e-6:
            terraces.append(located(b, frontage_m=short))
    check('WING_DEPTH', not bad, bad)
    check('SLAB_LENGTH_DEPTH', not slabs, slabs)
    check('TERRACE_FRONTAGE', not terraces, terraces)
    bad = [located(c, dimensions_m=_dimensions(_geom(c))) for c in plan['courtyards']
           if not 20-1e-6 <= _dimensions(_geom(c))[0] <= 45+1e-6]
    check('COURTYARD_CLEAR_WIDTH', not bad, bad)
    row = unary_union([shape(r['properties']['right_of_way']) for r in plan['roads']])
    bad = [located(b) for b in new if _geom(b).intersection(row).area>.01]
    check('BUILDING_ROAD_CLEARANCE', not bad, bad)
    bad = []
    for b in new:
        cs = list(_geom(b).exterior.coords)
        fronting = max((LineString([a,z]).intersection(row.buffer(3.00001)).length for a,z in zip(cs,cs[1:])),default=0)
        if row.is_empty or _geom(b).distance(row)>3.00001 or fronting<1:
            bad.append(located(b, setback_m=None if row.is_empty else _geom(b).distance(row), fronting_edge_m=fronting))
    check('BUILDING_STREET_EDGE_3M', not bad, bad)
    check('STREET_FRONTAGE', not bad, bad)
    missing_modes=[{'id':e['id'],'coordinates':e['coordinates'],'reason_zh':'入口缺少通行模式證據，不能跳過檢查'}
                   for e in plan['entrances'] if not e.get('modes')]
    check('ENTRANCE_MODE_EVIDENCE',not missing_modes,missing_modes)
    for mode in MODES:
        roads = [r for r in plan['roads'] if mode in r['properties']['modes']]
        # 同一路權被保留建物切斷的兩段不能當成一條連通邊。
        surfaces=[(r['id'],p) for r in roads for p in _polygons(shape(r['properties']['right_of_way']))]
        remaining = set(range(len(surfaces))); groups=[]
        while remaining:
            group={remaining.pop()}; todo=list(group)
            while todo:
                i=todo.pop()
                neighbors=set()
                for j in remaining:
                    crossing=surfaces[i][1].intersection(surfaces[j][1])
                    if crossing.area>.01 or crossing.length>=1-1e-6:
                        neighbors.add(j)
                remaining-=neighbors; group|=neighbors; todo.extend(neighbors)
            groups.append([surfaces[i][0] for i in sorted(group)])
        check('CONNECTIVITY_'+mode.upper(), len(groups)==1,
              [located(r) for r in roads] if roads and len(groups)!=1 else
              [{'mode':mode,'reason_zh':'意圖沒有提供此模式路權'}] if not roads else [],
              components=len(groups), component_members=groups,
              basis_zh='實際路權面交集；至少一公尺共邊或大於0.01平方公尺交疊，點接觸不算接通。')
        network=unary_union([g for _,g in surfaces])
        if mode in {'pedestrian','bicycle','car'}:
            bad=[]
            for entry in plan['entrances']:
                applicable=mode in entry.get('modes',[]) or (mode=='car' and 'motor_vehicle' in entry.get('modes',[]))
                if applicable and (network.is_empty or Point(entry['coordinates']).distance(network)>.05):
                    bad.append({'id':entry['id'],'coordinates':entry['coordinates'],
                                'distance_m':None if network.is_empty else Point(entry['coordinates']).distance(network)})
            check('ENTRANCES_'+mode.upper(), not bad, bad)
    fire=unary_union([shape(r['properties']['right_of_way']) for r in plan['roads'] if 'fire' in r['properties']['modes']])
    bad=[]; max_fire=0.
    for b in plan['buildings']:
        if fire.is_empty:
            bad.append(located(b, reason_zh='未提供消防模式道路')); continue
        ring=_geom(b).boundary; n=max(1,math.ceil(ring.length))
        distance=max(ring.interpolate(ring.length*i/n).distance(fire) for i in range(n+1))+.5
        max_fire=max(max_fire,distance)
        if distance>40:
            bad.append(located(b, distance_upper_m=distance))
    check('FIRE_ALL_EXTERIORS', not fire.is_empty and not bad, bad, max_distance_upper_m=None if fire.is_empty else max_fire)
    percents={}
    for allocation in plan['land_use']:
        category=allocation['properties']['category']
        percents[category]=percents.get(category,0)+100*_geom(allocation).area/area
    waterfront=shape(plan['waterfront_band'])
    road_percent=100*row.difference(waterfront).area/area
    combined=100*row.union(waterfront).area/area
    check('ROAD_AREA_BUDGET',20-1e-6<=road_percent<=28+1e-6,
          [located(r) for r in plan['roads']] if not 20<=road_percent<=28 else [], percentage=road_percent,required_percent=[20,28])
    check('ROAD_WATERFRONT_COMBINED_BUDGET',combined<=32+1e-6,percentage=combined,maximum_percent=32)
    bad=[located(b) for b in new if _geom(b).intersection(waterfront).area>.01]
    check('WATERFRONT_PUBLIC_BAND',not bad,bad)
    bad=[]
    road_map={r['properties'].get('intent_street_id'):r for r in plan['roads']}
    for street in intent['streets']:
        expected=frame.world(LineString(street['polyline']))
        expected_row=expected.buffer(street['width_m']/2,cap_style=2,join_style=2).intersection(land)
        actual=road_map.get(street['id'])
        if actual is None:
            bad.append({'id':street['id'],'reason_zh':'缺少道路','geometry':mapping(expected)}); continue
        q=actual['properties'];lost=expected_row.difference(shape(q['right_of_way']))
        # 忠實執行檢查只忽略基地外線段；基地內被限制截斷仍為衝突。
        if (q['width_m']!=street['width_m'] or q['modes']!=street['modes'] or q['role']!=street['role'] or lost.area>.01 or
                _geom(actual).symmetric_difference(expected.intersection(land)).length>.01):
            bad.append(located(actual,missing_row_m2=lost.area,expected_width_m=street['width_m']))
        actual_expected=_geom(actual).buffer(q['width_m']/2,cap_style=2,join_style=2).intersection(land)
        if shape(q['right_of_way']).difference(actual_expected).area>.01:
            bad.append(located(actual,reason_zh='路權與實際中心線寬度不符'))
    check('INTENT_STREETS',not bad,bad)
    waterfront_bad=[]
    for street in intent['streets']:
        if street['role']!='waterfront':
            continue
        expected=frame.world(LineString(street['polyline'])).intersection(land)
        actual=road_map.get(street['id'])
        missing=expected if actual is None else expected.difference(_geom(actual).buffer(1e-6))
        if missing.length>.01:
            waterfront_bad.append({'id':street['id'],'geometry':mapping(missing),'unserved_length_m':missing.length})
    check('WATERFRONT_CONTINUITY',not waterfront_bad,waterfront_bad)
    zones={z['id']:z for z in intent['zones']}
    bad=[]
    for b in new:
        q=b['properties'];zone=zones.get(q.get('zone_id'))
        if zone is None:
            bad.append(located(b,reason_zh='不屬於意圖zone'));continue
        components=COMPONENTS.get(zone['typology'],{zone['typology']})
        angle=frame.angle+zone.get('rotation_deg',0)
        local=rotate(_geom(b),-angle,origin=_geom(b).centroid)
        aligned=abs(local.envelope.area-local.area)<.01
        if (q.get('intent_typology')!=zone['typology'] or q['building_type'] not in components or not aligned or
                not zone['floors'][0]<=q['floors']<=zone['floors'][1] or
                not _zone_geometry(zone,frame).buffer(1e-6).covers(_geom(b))):
            bad.append(located(b,expected_typology=zone['typology'],expected_floors=zone['floors'],axis_aligned=aligned))
    for zone in intent['zones']:
        if not any(b['properties'].get('zone_id')==zone['id'] for b in new):
            bad.append({'id':zone['id'],'reason_zh':'zone沒有意圖指定建築','geometry':mapping(_zone_geometry(zone,frame))})
    check('INTENT_ZONES',not bad,bad)
    assembly_bad=[]
    for block in plan['blocks']:
        expected_parts=[]
        for instance in plan.get('template_instances',[]):
            if instance['block_id']!=block['id']:
                continue
            zone=zones[instance['zone_id']]
            templates,_=_templates(shape(instance['local_rectangle']),zone)
            expected_parts.extend(rotate(g,instance['angle_deg'],origin=instance['center_epsg28992']) for g,_,_ in templates)
        actual=unary_union([_geom(b) for b in new if b['properties'].get('block_id')==block['id']])
        expected=unary_union(expected_parts)
        difference=expected.symmetric_difference(actual)
        if expected.is_empty or difference.area>.01:
            assembly_bad.append(located(block,difference_m2=difference.area,reason_zh='樣板必要翼或梳狀脊與交付足跡不相符'))
    check('INTENT_TEMPLATE_ASSEMBLY',not assembly_bad,assembly_bad)
    frontage_bad=[]
    for block in plan['blocks']:
        zone=zones[block['properties']['zone_id']]
        directions=zone.get('frontage',[])
        if not directions:
            continue
        angle=frame.angle+zone.get('rotation_deg',0)
        center=_geom(block).centroid.coords[0]
        local=rotate(_geom(block),-angle,origin=center)
        x0,y0,x1,y1=local.bounds
        sides={'north':LineString([(x0,y1),(x1,y1)]),'south':LineString([(x0,y0),(x1,y0)]),
               'east':LineString([(x1,y0),(x1,y1)]),'west':LineString([(x0,y0),(x0,y1)])}
        actual=unary_union([_geom(b) for b in new if b['properties']['block_id']==block['id']])
        for direction in directions:
            expected_side=rotate(sides[direction],angle,origin=center)
            on_side=actual.boundary.intersection(expected_side.buffer(3.00001)) if not actual.is_empty else Polygon()
            real_front=on_side.intersection(row.buffer(3.00001))
            if real_front.length<1:
                frontage_bad.append(located(block,direction=direction,reason_zh='指定臨街面未配置至少一公尺且退縮不超過三公尺的建築邊'))
    check('INTENT_FRONTAGE',not frontage_bad,frontage_bad)
    bad=[]
    for i,park in enumerate(intent['parks']):
        expected=frame.world(_rect(park['rect_uv']))
        # 只計意圖矩形內的實際公園，不能用遠處併入殘地偽造面積。
        actual=unary_union([_geom(r) for r in plan['land_use'] if r['properties'].get('intent_park_index')==i and
                           r['properties']['category']==('plazas' if park.get('type')=='plaza' else 'parks')]).intersection(expected)
        if actual.area+1e-6<.9*expected.area:
            bad.append({'name_zh':park['name_zh'],'geometry':mapping(expected.difference(actual)),
                        'actual_area_m2':actual.area,'required_area_m2':.9*expected.area})
    check('INTENT_PARKS',not bad,bad)
    bad=[]
    for i,landmark in enumerate(intent.get('landmarks',[])):
        point=frame.world(Point(landmark['at_uv']))
        nearest=min(plan['buildings'],key=lambda b:point.distance(_geom(b))) if plan['buildings'] else None
        if nearest is None or nearest['properties'].get('landmark_index')!=i or nearest['properties']['height_m']!=landmark['height_m']:
            bad.append({'landmark_index':i,'at_uv':landmark['at_uv'],'height_m':landmark['height_m'],
                        'nearest_building_id':nearest['id'] if nearest else None,
                        'nearest_is_retained':nearest['properties'].get('retained') if nearest else None,
                        'geometry':nearest['geometry'] if nearest else None})
    check('INTENT_LANDMARKS',not bad,bad)
    for zone in intent['zones']:
        kind=zone['typology']
        if kind not in plan['dictionary_entries'] or kind not in SUPPORTED:
            check('INTENT_DICTIONARY',False,[{'id':zone['id'],'typology':kind}])
    if 'INTENT_DICTIONARY' not in checks:
        check('INTENT_DICTIONARY',True)
    bad=[located(b) for b in plan['blocks'] if not any(q['properties'].get('block_id')==b['id'] for q in new)]
    check('EVERY_BLOCK_BUILT_COVERAGE',not bad,bad)
    retained_roads=unary_union([_geom(r) for r in plan['roads']])
    bad=[{'id':r['id'],'geometry':r['geometry']} for r in plan['retained_road_inputs']
         if shape(r['geometry']).intersection(land).difference(retained_roads.buffer(1e-5)).length>.01]
    check('RETAINED_ROADS_PRESERVED',not bad,bad)
    footprint=unary_union([_geom(b) for b in new])
    all_footprint=unary_union([_geom(b) for b in plan['buildings']])
    metrics={'new_gfa_m2':gfa,'land_area_m2':area,'water_area_m2':water.area,'new_far':gfa/area,
        'gsi':footprint.area/area,'gsi_including_retained':all_footprint.area/area,
        'L':gfa/footprint.area if footprint.area else 0,'land_use_percent':percents,
        'park_area_m2':percents.get('parks',0)*area/100,'road_area_m2':row.area,
        'new_building_count':len(new),'block_count':len(plan['blocks']),
        'max_height_m':max((b['properties']['height_m'] for b in new),default=0),
        'allocation_percent':100*union.intersection(land).area/area,
        'max_fire_distance_upper_m':None if fire.is_empty else max_fire,
        'configured_footprint_capacity_m2':capacity,'density_status':'ASSUMED',
        'denominator_zh':'基地扣除映射水域；平方公尺；新建GFA／FAR及新建足跡GSI不計保留建築。'}
    failures=[key for key,value in checks.items() if not value['passed']]
    return {'passed':not failures,'status':'PASS' if not failures else 'FAIL',
            'failure_ids':failures,'checks':checks,'metrics':metrics}
