"""Offline FAB2 intent runner; no formal state writes or design acceptance."""
from __future__ import annotations

import json
import copy
import math
from pathlib import Path
from collections.abc import Mapping

from PIL import Image, ImageDraw
from shapely.ops import triangulate
import run_fabric_plan as base

ROOT = base.ROOT
FROZEN = ROOT / 'artifacts/fab1/run-4/inputs'


def frozen_inputs(intents):
    manifest = base.load_json(FROZEN / 'manifest.json')
    records = []
    for record in manifest['files']:
        relative = Path(record['snapshot_path'])
        # Frozen run-4 retains the original run-2 manifest path labels.
        tail = relative.parts[relative.parts.index('inputs') + 1:]
        path = FROZEN.joinpath(*tail)
        if base.sha256_file(path) != record['snapshot_sha256'] or path.stat().st_size != record['size_bytes']:
            raise ValueError(f'凍結輸入雜湊／大小不符：{path}')
        records.append({'path': str(path.relative_to(ROOT)), 'sha256': base.sha256_file(path), 'size_bytes': path.stat().st_size})
    fabrics = {f'fabric.{fid}': base.load_json(FROZEN / 'fabrics' / f'fabric.{fid}.json') for fid in base.FABRIC_IDS}
    entries = {}
    for path in sorted((FROZEN / 'dictionary_entries').glob('*.yaml')):
        entry = base.load_json(path)
        entries[entry['id']] = entry
    requested = {zone['typology'] for intent in intents.values() for zone in intent.get('zones', [])}
    for path in sorted((ROOT / 'config/morphology-dictionary/entries').glob('*.yaml')):
        entry = base.load_json(path)
        if entry['id'] in requested and entry['id'] not in entries:
            entries[entry['id']] = entry
            records.append({'path':str(path.relative_to(ROOT)), 'sha256':base.sha256_file(path),
                            'size_bytes':path.stat().st_size, 'origin':'local supplemental intent part',
                            'source_revision':base.repository_provenance(ROOT)})
    return base.load_json(FROZEN / 'site-facts.json'), {'fabrics': fabrics, 'entries': entries}, records


def map_panel(plan, facts, title, mode, *, size=(2400, 1600), show_legend=True):
    # No position labels or internal IDs. Floor numerals are retained.
    view = dict(plan)
    view['land_use'] = copy.deepcopy(plan.get('land_use',[]))
    for feature in base.feature_rows(view['land_use']):
        props = feature['properties']
        props['use_zh'] = base.LANDUSE_LABELS_ZH.get(props.get('category'),'未分類')
    view['courtyards'] = []
    view['service_facilities'] = []
    view['waterfront_detours'] = []
    view['roads'] = []
    if mode == 'massing':
        # Avoid the base renderer's repeated Chinese retained-building glyph.
        # This base pass supplies site/water/scale only; massing is drawn below.
        view['land_use'] = []
    audit = {}
    image = base._map_image(title=title, note='', facts=facts, plan=view,
                            canvas_size=size, mode='landuse' if mode=='massing' else mode, show_side_panel=False,
                            fixed_bounds=base._site_bounds(base._site_geometries(facts)[0]), render_audit=audit)
    # Compact footer legends stay outside the map rectangle.
    draw = ImageDraw.Draw(image)
    draw.rectangle((0,size[1]-58,size[0],size[1]),fill=(248,247,242))
    draw.text((50,size[1]-30),'座標：EPSG:28992（m）｜北箭頭為投影網格北｜比例尺以地面公尺計',font=base._font(19),fill=(89,94,95))
    annotations = [title, '座標與投影網格北及地面公尺比例尺說明']
    transform = base.MapTransform(base._site_bounds(base._site_geometries(facts)[0]), (42,130,size[0]-84,size[1]-190))
    if mode == 'massing':
        for block in base.feature_rows(plan.get('blocks')):
            base._draw_geometry(image,base.feature_shape(block),transform,fill=None,outline=(143,133,109),outline_width=2)
    for road in base.feature_rows(plan.get('roads')):
        props = base._properties(road)
        corridor = props.get('right_of_way')
        if not isinstance(corridor, Mapping):
            raise ValueError('FAB2 道路缺少核心 right_of_way；不以中心線補畫路幅。')
        geom = base._shape_value(corridor)
        base._draw_geometry(image, geom, transform, fill=base.ROAD_SURFACE_COLOR, outline=(130,128,121),outline_width=1)
        if mode == 'mobility':
            overlay = Image.new('RGB',size,(0,0,0))
            od = ImageDraw.Draw(overlay)
            for line in base._line_parts(base.feature_shape(road)):
                base._draw_mode_access_strokes(od,list(line.coords),base._road_modes(props),transform)
            mask = Image.new('RGB',size,(0,0,0))
            base._draw_geometry(mask,geom,transform,fill=(255,255,255),outline=None)
            # Apply only nonblack mode pixels inside the authoritative corridor.
            from PIL import ImageChops
            mode_mask = overlay.convert('L').point(lambda v:255 if v else 0)
            image.paste(overlay,(0,0),ImageChops.multiply(mask.convert('L'),mode_mask))
    # Buildings sit above road surfaces; invalid overlaps remain visible in checks.
    for building in base.feature_rows(plan.get('buildings')):
        geom = base.feature_shape(building)
        props = base._properties(building)
        color = (103,103,99) if props.get('retained') else base._height_color(base._feature_height(props,facts)) if mode == 'massing' else (232,222,208)
        base._draw_geometry(image,geom,transform,fill=color,outline=(53,60,64),outline_width=1)
        if mode == 'massing':
            floors = props.get('floors')
            text = 'R' if props.get('retained') else str(int(floors)) if isinstance(floors,(int,float)) else ''
            draw.text(transform.point(geom.representative_point().coords[0]),text,font=base._font(12),fill=(20,25,28),anchor='mm',stroke_width=1,stroke_fill=(242,239,230))
    if show_legend and mode == 'landuse':
        labels = [('街廓／建築用地', base._category_color('街廓／建築用地')),
                  ('公園／綠地', base._category_color('公園／綠地')),
                  ('廣場',base._category_color('廣場')),('保留建築',(103,103,99)),
                  ('道路',base.ROAD_SURFACE_COLOR),('水域',(194,222,230))]
        x = 60
        for text, color in labels:
            draw.rectangle((x, size[1]-68, x+20, size[1]-48), fill=color)
            draw.text((x+28, size[1]-70), text, font=base._font(18), fill=(45,50,52))
            annotations.append(text)
            x += min(260, (size[0]-120)//6)
    elif show_legend and mode == 'mobility':
        x = 60
        for key in ('pedestrian', 'bicycle', 'car'):
            draw.line((x, size[1]-60, x+28, size[1]-60), fill=base.MODE_COLORS[key], width=5)
            draw.text((x+36, size[1]-70), base.MODE_LABELS_ZH[key], font=base._font(18), fill=(45,50,52))
            annotations.append(base.MODE_LABELS_ZH[key])
            x += 200
    elif show_legend:
        draw.text((500, size[1]-70), '數字＝樓層；R＝保留建築；色深＝高度', font=base._font(18), fill=(45,50,52))
        annotations.append('數字＝樓層；R＝保留建築；色深＝高度')
    # MapTransform rectangles use x,y,width,height.
    w, h = size
    audit['map_panel_area_percent'] = round(100*(w-84)*(h-190)/(w*h), 2)
    audit['map_rect_xywh'] = [42,130,w-84,h-190]
    audit['map_text_annotation_count'] = len(annotations)
    audit['chinese_annotations'] = annotations
    audit['annotation_basis_zh'] = '每次固定中文文字繪製各算一標註；樓層數字、拉丁保留符號R及N／公尺數字不計；地圖內沒有重複中文保留符號。'
    audit['retained_building_symbol'] = 'R' if mode=='massing' else None
    if mode == 'massing':
        audit['mobility_overlay_status'] = 'NOT_APPLICABLE'
        audit['land_use_budget_source'] = None
    audit['internal_id_labels'] = 0
    return image, audit


def grid(path, plans, facts, mode):
    image = Image.new('RGB', (2400, 1600), (248,247,242))
    audits = []
    for index, fid in enumerate(base.FABRIC_IDS):
        panel, audit = map_panel(plans[fid], facts, base._fabric_label(fid), mode, size=(1200,800),show_legend=False)
        image.paste(panel, ((index%2)*1200,(index//2)*800))
        audits.append(audit)
    legend = '用地色：橘色街廓、綠色公園、黃色廣場、深灰保留建築、灰色道路、淺藍水域' if mode=='landuse' else '數字＝樓層；R＝保留建築；色深＝高度'
    ImageDraw.Draw(image).text((60,1530),legend,font=base._font(16),fill=(45,50,52))
    image.save(path, optimize=True)
    count = sum(a['map_text_annotation_count'] for a in audits)+1
    return {'same_extent': True, 'same_panel_dimensions': True, 'same_ground_scale': True,
            'map_text_annotation_count':count,'shared_legend':legend,'MAP_TEXT_LABEL_LIMIT':count<=10,'panels': audits}


def concise(value):
    """Summarize structured diagnostics without copying polygon coordinates."""
    def strip_geometry(item):
        if isinstance(item,Mapping):
            if item.get('type') in {'Polygon','MultiPolygon','LineString','MultiLineString','Point','MultiPoint','GeometryCollection'}:
                return '[幾何見 checks.json]'
            return {key:strip_geometry(val) for key,val in item.items() if key not in {'geometry','coordinates','right_of_way'}}
        if isinstance(item,list):
            return [strip_geometry(val) for val in item]
        return item
    if isinstance(value, Mapping):
        clean = strip_geometry(value)
        return json.dumps(clean,ensure_ascii=False,separators=(',',':'),default=base._json_default).replace('|','／')
    if isinstance(value,list):
        return '；'.join(concise(item) for item in value)
    return str(value).replace('|','／')


def location_summary(locations):
    items = locations if isinstance(locations,list) else [locations]
    summaries = [concise(item) for item in items[:20]]
    suffix = f'；共 {len(items)} 個定位，完整資料見 checks.json' if len(items)>20 else ''
    return '；'.join(summaries)+suffix or '未提供定位'


def render_axon(path, plan, facts, label):
    """Project real geometry through the declared local frame and fit its vertices."""
    image = Image.new('RGB',(1920,1400),(248,247,242))
    draw = ImageDraw.Draw(image)
    frame = plan['intent']['frame']
    ox,oy = frame['origin_epsg28992']
    angle = math.radians(90-frame['axis_azimuth_deg'])
    c,s = math.cos(angle),math.sin(angle)
    def uv(point):
        x,y = point[0]-ox,point[1]-oy
        return c*x+s*y,-s*x+c*y
    def raw(point,z=0):
        u,v = uv(point)
        return math.sqrt(3)/2*(u-v),.5*(u+v)-z
    site,water,_ = base._site_geometries(facts)
    buildings = base.feature_rows(plan.get('buildings'))
    def height(feature):
        value = base._finite_number(base._properties(feature).get('height_m'))
        return value if value is not None and value>0 else None
    max_height = max((height(b) or 0 for b in buildings),default=0)
    fit = [raw(point,z) for polygon in base._polygon_parts(site)
           for point in polygon.exterior.coords for z in (0,max_height)]
    x0,y0 = min(p[0] for p in fit),min(p[1] for p in fit)
    x1,y1 = max(p[0] for p in fit),max(p[1] for p in fit)
    left,top,width,panel_height = 60,130,1800,1100
    scale = min(width/max(x1-x0,1e-9),panel_height/max(y1-y0,1e-9))
    px = left+(width-(x1-x0)*scale)/2
    py = top+(panel_height-(y1-y0)*scale)/2
    def project(point,z=0):
        x,y=raw(point,z)
        return round(px+(x-x0)*scale),round(py+(y-y0)*scale)
    def ground(geometry,color):
        for polygon in base._polygon_parts(geometry):
            # Triangles preserve real holes and concave boundaries.
            for triangle in triangulate(polygon):
                if polygon.covers(triangle):
                    draw.polygon([project(point) for point in triangle.exterior.coords],fill=color)
    ground(site,(236,233,222))
    for allocation in base.feature_rows(plan.get('land_use')):
        category=base._properties(allocation).get('category')
        color=(103,103,99) if category=='retained_buildings' else base._category_color(base.LANDUSE_LABELS_ZH.get(category,'未分類'))
        ground(base.feature_shape(allocation),color)
    ground(water,(194,222,230))
    for road in base.feature_rows(plan.get('roads')):
        ground(base._shape_value(base._properties(road)['right_of_way']),base.ROAD_SURFACE_COLOR)
    records=[]
    for building in buildings:
        geom=base.feature_shape(building)
        u,v=uv(geom.representative_point().coords[0])
        records.append((u+v,building,geom,height(building)))
    extruded,unknown=0,0
    for _,building,geom,z in sorted(records,key=lambda row:row[0]):
        props=base._properties(building)
        color=(143,148,145) if props.get('retained') else base._height_color(z)
        side=tuple(round(value*.72) for value in color)
        edge=tuple(round(value*.55) for value in color)
        if z is None:
            unknown+=1
            for polygon in base._polygon_parts(geom):
                draw.line([project(point) for point in polygon.exterior.coords],fill=(98,100,96),width=2)
            continue
        for polygon in base._polygon_parts(geom):
            base._ring_sides(draw,polygon.exterior,z,project,side,edge)
            for ring in polygon.interiors:
                base._ring_sides(draw,ring,z,project,side,edge)
            for triangle in triangulate(polygon):
                if polygon.covers(triangle):
                    draw.polygon([project(point,z) for point in triangle.exterior.coords],fill=color,outline=edge)
        extruded+=1
    # World-grid north (E=0,N=1) transformed through the same local frame.
    ndx,ndy=math.sqrt(3)/2*(s-c),.5*(s+c)
    norm=math.hypot(ndx,ndy)
    nx,ny=round(1790+70*ndx/norm),round(220+70*ndy/norm)
    draw.line((1790,220,nx,ny),fill=(45,50,52),width=4)
    ux,uy=ndx/norm,ndy/norm
    draw.polygon([(nx,ny),(nx-14*ux+6*uy,ny-14*uy-6*ux),(nx-14*ux-6*uy,ny-14*uy+6*ux)],fill=(45,50,52))
    draw.text((nx+8,ny),'N',font=base._font(18),fill=(45,50,52))
    # 100 m along local u; projected length is exactly scale*100.
    sx,sy=80,1260
    ex,ey=sx+100*scale*math.sqrt(3)/2,sy+100*scale*.5
    draw.line((sx,sy,ex,ey),fill=(45,50,52),width=5)
    annotations=[f'{label}｜等角量體圖','依意圖局部軸投影實際建築足跡；高度只讀輸出值',
                 '100 m 地面尺度',f'建築 {len(buildings)} 棟｜擠出 {extruded} 棟｜高度缺值 {unknown} 棟',
                 '高度缺值者僅描建築足跡；灰色為保留建築']
    positions=[(48,28),(50,82),(80,1234),(500,1260),(500,1300)]
    for index,(text,position) in enumerate(zip(annotations,positions)):
        draw.text(position,text,font=base._font(42 if index==0 else 19),fill=(45,50,52))
    image.save(path,optimize=True)
    return {'building_count':len(buildings),'extruded_building_count':extruded,'height_unknown_count':unknown,
            'projection':'local intent frame; x=sqrt(3)/2*(u-v), y=(u+v)/2-z; orthographic',
            'fit_basis':'actual site polygon vertices at z=0 and actual maximum supplied building height',
            'maximum_supplied_height_m':max_height,'map_rect_xywh':[left,top,width,panel_height],
            'map_panel_area_percent':round(100*width*panel_height/(1920*1400),2),
            'map_text_annotation_count':len(annotations),'chinese_annotations':annotations,'internal_id_labels':0,
            'ground_scale_px_per_m':scale,'grid_north_projected_vector':[ndx,ndy],
            'projected_geometry_bounds_px':[px,py,px+(x1-x0)*scale,py+(y1-y0)*scale]}


def render_case(output, fid, plan, facts):
    render = {}
    for mode,label in [('landuse','用地'),('massing','量體與樓層'),('mobility','交通模式')]:
        image,audit = map_panel(plan,facts,f'{base._fabric_label(fid)}｜{label}',mode)
        image.save(output/f'{fid}-{mode}-zh.png',optimize=True)
        render[mode] = audit
    path = output/f'{fid}-axon-zh.png'
    render['axon'] = render_axon(path,plan,facts,base._fabric_label(fid))
    return render


def render_existing(output, facts):
    """Explicit redraw entry point: writes exactly 18 PNGs, returns updated audits.

    Caller must archive superseded images first; plans/checks/README are untouched.
    """
    output = Path(output).resolve()
    plans = {fid:base.load_json(output/f'{fid}-plan.json') for fid in base.FABRIC_IDS}
    audits = {fid:render_case(output,fid,plan,facts) for fid,plan in plans.items()}
    comparison = {mode:grid(output/f'comparison-{mode}-zh.png',plans,facts,mode) for mode in ('landuse','massing')}
    for path in output.glob('*-zh.png'):
        if path.stat().st_size>=base.MAX_ARTIFACT_BYTES:
            raise ValueError(f'圖面必須小於5 MB：{path}')
    return {'cases':audits,'comparison':comparison,'renderer_sha256':base.sha256_file(Path(__file__))}


def landuse_areas(plan):
    areas = {}
    for feature in base.feature_rows(plan.get('land_use')):
        category = base._properties(feature).get('category','unknown')
        # Shapely area includes every polygon inside a GeometryCollection.
        areas[category] = areas.get(category,0.) + base._shape_value(feature['geometry']).area
    return areas


def write_readme(output, plans, checks_by_id, facts, *, intent_source=None):
    output = Path(output)
    source = intent_source or ROOT/'artifacts/fab2/intents'
    rows = []
    for fid in base.FABRIC_IDS:
        check = checks_by_id[fid].get('core_validator',checks_by_id[fid])
        status,_ = base._check_status(check)
        rows.append((fid,status,check.get('metrics',plans[fid].get('metrics',{})),plans[fid].get('intent_issues',[])))
    lines = ['# FAB2 設計意圖方案', '', '本輪依設計意圖生成；只讀 FAB1 run-4 凍結 facts／字典，不寫入正式資料庫。方案仍為探索草案，圖面成功不代表驗證通過或人類接受。', '',
             '| 方案 | 核心檢查 | 新建 GFA (m²) | 新建 FAR | GSI | 平均層數 L | 最高高度 (m) |', '|---|---|---:|---:|---:|---:|---:|']
    for fid,status,m,issues in rows:
        lines.append(f"| {base._fabric_label(fid)} | {status} | {base._fmt(m.get('new_gfa_m2'))} | {base._fmt(m.get('new_far'),3)} | {base._fmt(m.get('gsi'),3)} | {base._fmt(m.get('L'),2)} | {base._fmt(m.get('max_height_m'))} |")
    lines.extend(['','數字讀自核心 metrics；未提供欄位不由圖像估算。L＝新建 GFA／新建足跡面積，為面積加權平均層數。同比例四格採相同 EPSG:28992 範圍及相同畫格。量體圖逐棟標樓層；保留建築標拉丁字母「R」。', '',
                  '生成器使用有界格網與字典樣板，容量表示當前配置可容納的足跡；並未證明最大可行容量，也不是容量最佳化搜尋。', '',
                  '## 土地使用完整分類', '', '| 方案 | 分類 | 面積 (m²) | 陸地占比 (%) |', '|---|---|---:|---:|'])
    categories = set(base.LANDUSE_LABELS_ZH).intersection({'blocks','roads','waterfront','parks','plazas','service','retained_buildings','public_facilities'})
    categories.update(category for _,_,m,_ in rows for category in m.get('land_use_percent',{}))
    for fid,status,m,issues in rows:
        areas = landuse_areas(plans[fid])
        for category in sorted(categories):
            area = areas.get(category,0)
            pct = 100*area/m['land_area_m2'] if m.get('land_area_m2') else None
            lines.append(f"| {base._fabric_label(fid)} | {base.LANDUSE_LABELS_ZH.get(category,category)} | {base._fmt(area,3)} | {base._fmt(pct,2)} |")
        lines.append(f"| {base._fabric_label(fid)} | 陸地合計 | {base._fmt(sum(areas.values()),3)} | {base._fmt(100*sum(areas.values())/m['land_area_m2'],2)} |")
    lines.extend(['','公園、廣場與道路各列實際分類幾何面積；分母為基地扣除水域的陸地面積，重疊／漏配另由核心檢查。',f'水岸公共帶為非互斥的疊加限制，凍結幾何面積 {base._fmt(base._shape_value(plans[base.FABRIC_IDS[0]]["waterfront_band"]).area,1)} m²；實際土地可分類為路權或公園。waterfront 分類為 0 不表示水岸未配置。','', '## 意圖問題與未決項目',''])
    for fid,status,m,issues in rows:
        lines.append(f'### {base._fabric_label(fid)}')
        lines.extend('- '+concise(issue) for issue in issues)
        if not issues:
            lines.append('核心未列出意圖問題；仍須閱讀逐案 checks.json。')
        lines.append('')
    lines.extend(['## 各案未通過檢查與定位摘要','','| 方案 | 檢查 | 定位與數值摘要 |','|---|---|---|'])
    for fid,status,m,issues in rows:
        core_checks = checks_by_id[fid].get('core_validator',checks_by_id[fid])
        failures = [(key,val) for key,val in core_checks.get('checks',{}).items() if val.get('passed') is False or val.get('status')=='FAIL']
        for key,val in failures:
            locations=location_summary(val.get('failure_locations',[]))
            details=concise({k:v for k,v in val.items() if k not in {'passed','status','failure_locations'}})
            lines.append(f'| {base._fabric_label(fid)} | {key} | {locations}；{details} |')
        if not failures:
            lines.append(f'| {base._fabric_label(fid)} | 無逐項 FAIL | 全域狀態 {status} |')
    lines.extend(['## 重現','',f'`TMPDIR=/private/tmp PYTHONPATH=src .venv/bin/python scripts/run_fabric_plan.py --intent-dir {source} --output-dir {output}`','',
                  '輸入與意圖 SHA-256 見 input-provenance.json；所有輸出每檔須小於 5 MB。此 runner 未執行測試套件、獨立跨供應商審查或人類接受。'])
    (output/'README-zh.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def run_intents(intent_dir: Path, output_dir: Path) -> int:
    from urban_design.generation.fabric_plan import plan_from_intent, validate_plan
    source = intent_dir.resolve()
    output = (ROOT / output_dir).resolve() if not output_dir.is_absolute() else output_dir.resolve()
    allowed = ROOT / 'artifacts/fab2'
    try:
        relative = output.relative_to(allowed)
        if not relative.parts or relative.parts[0] == 'intents':
            raise ValueError('輸出不可覆寫意圖來源。')
        if output.exists():
            raise FileExistsError(f'拒絕覆寫既有輸出：{output}')
        intents = {fid: base.load_json(source / f'fabric.{fid}.json') for fid in base.FABRIC_IDS}
        facts, dictionary, records = frozen_inputs(intents)
        output.mkdir(parents=True)
        provenance = {'schema_version':'fab2-input-provenance-v1', 'created_at_utc':base.utc_now(),
                      'frozen_inputs':records, 'frozen_manifest_sha256':base.sha256_file(FROZEN/'manifest.json'),
                      'runner_sha256':base.sha256_file(Path(__file__)),
                      'core_sha256':base.sha256_file(ROOT/'src/urban_design/generation/fabric_plan.py'),
                      'intent_geometry_source':{'path':'src/urban_design/generation/fabric_intent.py',
                          'sha256':base.sha256_file(ROOT/'src/urban_design/generation/fabric_intent.py')},
                      'intent_sources':[]}
        plans, rows, failed = {}, [], False
        for fid, intent in intents.items():
            src = source / f'fabric.{fid}.json'
            provenance['intent_sources'].append({'path':str(src), 'sha256':base.sha256_file(src)})
            saved = output / 'intent-sources' / src.name
            saved.parent.mkdir(exist_ok=True)
            saved.write_bytes(src.read_bytes())
            plan = plan_from_intent(intent, facts, dictionary)
            if not isinstance(plan, Mapping):
                raise TypeError('plan_from_intent 必須回傳 FAB1 相容 mapping。')
            base._check_plan_epsg28992(plan)
            checks = validate_plan(plan)
            if not isinstance(checks, Mapping):
                raise TypeError('validate_plan 必須回傳 mapping。')
            status, failures = base._check_status(checks)
            failed |= status != 'PASS'
            plans[fid] = plan
            base.write_json(output/f'{fid}-plan.json', plan)
            render = render_case(output,fid,plan,facts)
            gates = {'MAP_AREA_70_PERCENT':all(r['map_panel_area_percent']>=70 for r in render.values()),
                     'MAP_TEXT_LABEL_LIMIT':all(r['map_text_annotation_count']<=10 for r in render.values()),
                     'NO_INTERNAL_ID_LABELS':all(r['internal_id_labels']==0 for r in render.values())}
            failed |= not all(gates.values())
            base.write_json(output/f'{fid}-checks.json', {'schema_version':'fab2-plan-checks-v1','core_validator':checks,
                            'intent_checks':plan.get('intent_checks',{}),'intent_issues':plan.get('intent_issues',[]),
                            'render_audit':render,'runner_checks':gates,'failure_ids':failures})
            rows.append((fid,status,checks.get('metrics',plan.get('metrics',{})),plan.get('intent_issues',[])))
        comparison = {mode:grid(output/f'comparison-{mode}-zh.png',plans,facts,mode) for mode in ('landuse','massing')}
        failed |= not all(a['MAP_TEXT_LABEL_LIMIT'] and all(p['map_panel_area_percent']>=70 for p in a['panels']) for a in comparison.values())
        base.write_json(output/'comparison.json', {'schema_version':'fab2-comparison-v1','render_audit':comparison,
                                                  'decision_zh':'未設總體勝出規則，未選勝出方案。'})
        base.write_json(output/'input-provenance.json',provenance)
        write_readme(output,plans,{fid:base.load_json(output/f'{fid}-checks.json') for fid in base.FABRIC_IDS},facts,intent_source=source)
        oversize = [p for p in output.rglob('*') if p.is_file() and p.stat().st_size>=5_000_000]
        if oversize:
            raise ValueError(f'產物超過單檔 5 MB：{oversize}')
        print(json.dumps({'status':'FAIL' if failed else 'PASS','output_dir':str(output)},ensure_ascii=False))
        return 2 if failed else 0
    except Exception as exc:
        print(f'FAB2 runner failed closed: {type(exc).__name__}: {exc}')
        return 1
