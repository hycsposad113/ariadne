"""Traditional Chinese J15 plan/axonometric/sections; gated by measured checks."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager
for font in ('/System/Library/Fonts/STHeiti Medium.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc'):
    if Path(font).is_file():
        font_manager.fontManager.addfont(font)
        matplotlib.rcParams['font.family'] = font_manager.FontProperties(fname=font).get_name()
        break
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
from matplotlib.path import Path as PlotPath
from matplotlib.patches import PathPatch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

TYPES = {'block.perimeter': '周邊式', 'building.courtyard_closed': '合院', 'building.l_block': 'L形街牆', 'building.i_slab': '板樓', 'building.rowhouse': '連棟', 'building.point_tower': '點式', 'building.podium_tower': '基座量體', 'building.industrial_hall': '製造廠房'}
NAMES = {'radial': '向心型', 'axial': '軸線型', 'grid': '網格型', 'green_service': '綠廊服務型'}
ROAD_STYLE = {
    'main': dict(color='#1d4f7a', linestyle='-', linewidth=2.2),
    'branch': dict(color='#3f7ea8', linestyle='-', linewidth=1.4),
    'internal': dict(color='#6aa3c4', linestyle=':', linewidth=1.1),
    'service': dict(color='#8a5a2b', linestyle='--', linewidth=1.4),
    'retained': dict(color='#555555', linestyle='-', linewidth=1.6),
}


def patch(ax, g, **kwargs):
    if g['type'] not in ('Polygon', 'MultiPolygon'):
        return
    for rings in [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']:
        vertices = []
        codes = []
        for ring in rings:
            vertices += ring
            codes += [PlotPath.MOVETO] + [PlotPath.LINETO] * (len(ring) - 2) + [PlotPath.CLOSEPOLY]
        ax.add_patch(PathPatch(PlotPath(vertices, codes), **kwargs))


def plan(row, path, *, zoom=None):
    from shapely.geometry import shape
    fig, ax = plt.subplots(figsize=(12, 8))
    for space in row.get('named_open_spaces', []):
        patch(ax, space['geometry'], facecolor='#c5dda8', edgecolor='#5f7d45', alpha=.7)
        c = shape(space['geometry']).representative_point()
        if space['area_m2'] >= 1500 or space['name_zh'].startswith('整合節點廣場'):
            ax.text(c.x, c.y, f"{space['name_zh']}\n{space['area_m2']:,.0f}平方公尺", fontsize=6, ha='center', clip_on=True)
    for context in row.get('context_edges', []):
        if context['kind'] == 'dakpark':
            patch(ax, context['geometry'], facecolor='#89b573', edgecolor='#537747', alpha=.7)
            c = shape(context['geometry']).representative_point()
            ax.text(c.x, c.y, '高架公園\n高差10公尺（作品集假設）', fontsize=7, ha='center', clip_on=True)
    for f in row['geometry']['features']:
        g = f['geometry']
        p = f['properties']
        role = p['role']
        if role == 'road':
            cs = g['coordinates']
            style = ROAD_STYLE.get(p.get('hierarchy'), ROAD_STYLE['internal'])
            ax.plot([c[0] for c in cs], [c[1] for c in cs], **style)
        elif role == 'entrance':
            ax.scatter(*g['coordinates'], marker='^', color='#163a68', s=28)
            ax.text(g['coordinates'][0], g['coordinates'][1], '入口', fontsize=5, color='#163a68')
        else:
            color = {'retained': '#666666', 'water': '#adcedb', 'new_building': '#dcac6c', 'named_park': 'none'}.get(role, 'none')
            patch(ax, g, facecolor=color, edgecolor='#222222' if role == 'site_area' else '#777777' if role == 'new_building' else 'none', alpha=.8)
            if role == 'new_building':
                center = shape(g).representative_point()
                ax.text(center.x, center.y, f"{p.get('height_m', 0):g}公尺\n{TYPES.get(p.get('type_id'), '量體')}", fontsize=5, clip_on=True)
    for b in row['buildings']:
        for e in b.get('facade_segments', []):
            if e['active']:
                cs = e['geometry']['coordinates']
                ax.plot([p[0] for p in cs], [p[1] for p in cs], color='#d85a27', linewidth=2.5)
    ax.autoscale()
    ax.set_aspect('equal')
    if zoom:
        g = shape(zoom['geometry'])
        x0, y0, x1, y1 = g.bounds
        ax.set_xlim(x0 - 12, x1 + 12)
        ax.set_ylim(y0 - 12, y1 + 12)
        ax.set_title('街廓放大｜周邊式街牆與中庭｜入口需後續驗證')
    else:
        ax.set_title(f"{NAMES[row['family']]}｜街廓先行｜草案｜實線主街／虛線服務／三角入口")
    ax.set_xlabel('RD X 座標（公尺）')
    ax.set_ylabel('RD Y 座標（公尺）')
    fig.savefig(path, dpi=160)
    plt.close(fig)


def render(row, output):
    from urban_design.generation.block_first import drawing_guard
    drawing_guard(row)
    if row.get('status') != 'VALID' or not row.get('buildings') or not all(b.get('scale', {}).get('valid') is True for b in row['buildings']):
        raise ValueError('INVALID massing: figure output prohibited')
    from urban_design.generation.massing_revision import revision_checks
    checks, _ = revision_checks(row['buildings'], row.get('metrics', dict(far=0, coverage=1)))
    if not all(checks.values()) or not all(row.get('checks', {}).values()) or not all(row.get('network_hard_checks', {}).get('checks', {}).values()):
        raise ValueError('INVALID massing: figure output prohibited')
    output = Path(output)
    identity = row['id']
    plan(row, output / (identity + '-plan-zh.png'))
    fig, ax = plt.subplots(figsize=(8, 5))
    heights = [b['height_m'] for b in row['buildings']]
    bins = [0, 3.5, 7, 10.5, 14, 17.5, 21]
    ax.hist(heights, bins=bins, rwidth=.85, color='#c89653')
    ax.set_xticks(bins)
    ax.set_xlabel('建築高度（公尺）')
    ax.set_ylabel('棟數')
    ax.set_title(NAMES[row['family']] + '｜逐棟高度分布｜草案')
    fig.savefig(output / (identity + '-heights-zh.png'), dpi=160)
    plt.close(fig)
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection='3d')
    vertices = []
    colors = []
    allxy = [xy for f in row['features'] for xy in f['geometry']['coordinates'][0]]
    cx = sum(p[0] for p in allxy) / len(allxy)
    cy = sum(p[1] for p in allxy) / len(allxy)
    for f in row['features']:
        p = f['properties']
        base = 0
        for floor in p['floors']:
            top = base + floor['floor_height_m']
            rings = floor['geometry']['coordinates']
            for ring in rings:
                for a, b in zip(ring, ring[1:]):
                    vertices.append([(a[0] - cx, a[1] - cy, base), (b[0] - cx, b[1] - cy, base), (b[0] - cx, b[1] - cy, top), (a[0] - cx, a[1] - cy, top)])
                    colors.append('#dcac6c')
            from shapely.geometry import shape
            from shapely.ops import triangulate
            plate = shape(floor['geometry'])
            for triangle in triangulate(plate):
                if plate.covers(triangle):
                    vertices.append([(x - cx, y - cy, top) for x, y in list(triangle.exterior.coords)[:-1]])
                    colors.append('#e6bd80')
            base = top
    ax.add_collection3d(Poly3DCollection(vertices, facecolors=colors, edgecolors='#795e42', linewidths=.15))
    xs = [p[0] - cx for p in allxy]
    ys = [p[1] - cy for p in allxy]
    ax.set_xlim(min(xs), max(xs))
    ax.set_ylim(min(ys), max(ys))
    ax.set_zlim(0, 20)
    ax.set_box_aspect((max(xs) - min(xs), max(ys) - min(ys), 80))
    ax.view_init(elev=38, azim=-60)
    ax.set_xlabel('東西（公尺）')
    ax.set_ylabel('南北（公尺）')
    ax.set_zlabel('高度（公尺）')
    ax.set_title(NAMES[row['family']] + '｜量體軸測｜高度顯示比例 4 倍｜草案')
    fig.savefig(output / (identity + '-axonometric-zh.png'), dpi=160)
    plt.close(fig)
    court = next((f for f in row['features'] if f['properties']['type_id'] in ('block.perimeter', 'building.courtyard_closed')), None)
    plan(row, output / (identity + '-block-detail-zh.png'), zoom=court or row['features'][0])
    sections(row, output)


def sections(row, output):
    from shapely.geometry import LineString, shape
    from shapely.ops import nearest_points, unary_union
    park = shape(next(e['geometry'] for e in row['context_edges'] if e['kind'] == 'dakpark'))
    masses = unary_union([shape(f['geometry']) for f in row['features']])
    park_point, building_point = nearest_points(park, masses)
    dx, dy = park_point.x - building_point.x, park_point.y - building_point.y
    norm = (dx * dx + dy * dy) ** .5 or 1
    c = building_point
    park_line = LineString([(c.x - dx / norm * 100, c.y - dy / norm * 100), (c.x + dx / norm * 200, c.y + dy / norm * 200)])
    roads = [shape(f['geometry']) for f in row['geometry']['features'] if f['properties']['role'] == 'road' and f['properties'].get('hierarchy') in (('main', 'branch') if row['family'] == 'grid' else ('main', 'service'))]
    if not roads:
        raise ValueError('source-backed main axis required for section')
    lines = []
    for axis in roads:
        a, b = list(axis.coords)[0], list(axis.coords)[-1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = (dx * dx + dy * dy) ** .5 or 1
        for fraction in (.1, .25, .5, .75, .9):
            c = axis.interpolate(fraction, normalized=True)
            candidate = LineString([(c.x - dy / norm * 140, c.y + dx / norm * 140), (c.x + dy / norm * 140, c.y - dx / norm * 140)])
            lines.append(candidate)
    main_line = max(lines, key=lambda line: line.intersection(masses).length)
    if main_line.intersection(masses).length <= 0:
        raise ValueError('main-axis section has no building intersection')
    for suffix, line, title in [('dakpark', park_line, '高架公園介面'), ('main-axis', main_line, '網格發展街橫剖' if row['family'] == 'grid' else '主軸橫剖')]:
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.axhline(0, color='#555555')
        def spans(g):
            cross = line.intersection(g)
            parts = [cross] if cross.geom_type == 'LineString' else getattr(cross, 'geoms', [])
            for part in parts:
                if part.geom_type == 'LineString' and part.length > 0:
                    ts = [line.project(__import__('shapely').geometry.Point(x, y)) for x, y in part.coords]
                    yield min(ts), max(ts)
        for lo, hi in spans(park):
            ax.fill_between([lo, hi], 0, 10, color='#89b573', alpha=.7)
            ax.text((lo + hi) / 2, 10.5, '公園高差10公尺\n作品集假設，非實測', ha='center', fontsize=8)
        for building in row['buildings']:
            z = 0
            for floor in building['floors']:
                top = z + floor['floor_height_m']
                for lo, hi in spans(shape(floor['geometry'])):
                    ax.fill_between([lo, hi], z, top, color='#dcac6c', edgecolor='#795e42', linewidth=.5)
                z = top
        ax.set_xlim(0, line.length)
        ax.set_ylim(-1, 24)
        ax.set_xlabel('剖線距離（公尺）')
        ax.set_ylabel('相對基地高度（公尺）')
        ax.set_title(NAMES[row['family']] + '｜' + title + '｜樓板交切示意，非實測地形')
        ax.text(.01, .97, f'剖線起點 {line.coords[0][0]:.1f}, {line.coords[0][1]:.1f}；終點 {line.coords[-1][0]:.1f}, {line.coords[-1][1]:.1f}', transform=ax.transAxes, va='top', fontsize=7)
        fig.tight_layout()
        fig.savefig(output / (row['id'] + '-section-' + suffix + '-zh.png'), dpi=160)
        plt.close(fig)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    render(json.loads(Path(a.input).read_text()), a.output)
