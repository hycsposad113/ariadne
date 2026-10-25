#!/usr/bin/env python3
"""Run a read-only browser rehearsal for fabric comparison and Generate."""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

FABRICS = ('harbour_grain', 'closed_block_extension', 'courtyard_islands', 'landscape_figure')
LOCALES = ('en', 'zh-TW')
STAGES = ('compare', 'generate')
MODES = ('2D', '3D', 'SPLIT')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134F]')

FABRIC_COLORS = {
    'boundary': '#38bdf8', 'retained': '#a4a4a4', '1–2F': '#b7a698',
    '3F': '#a08c7c', '4F': '#897365', '5F': '#715a4c', '6F+': '#3e332c',
    'unknown': '#64748b', 'park': '#89ae86', 'residential': '#e3c598',
    'commercial': '#d5a39b', 'service': '#c49791', 'plazas': '#e9dac1',
    'waterfront': '#94b7c6', 'water': '#287ca2', 'blocks': '#b3a894',
    'roads': '#b6b0a4', 'other': '#d5ccba', 'utility_yard': '#8b7d9c',
    'maintenance_green': '#557a56', 'shared_planting': '#b5ca89',
}
ROAD_COLORS = ('#f59e0b', '#c4a370', '#94a3b8', '#889c89', '#475569')
CANVAS_PIXEL_EVIDENCE_JS = '''canvas => {
  const rect=canvas.getBoundingClientRect(); const ctx=canvas.getContext('2d');
  if (!ctx || canvas.width<1 || canvas.height<1 || rect.width<1 || rect.height<1) return null;
  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
  let nonBackgroundSamples=0, boundaryPixels=0; const sampleStep=64;
  for(let i=0;i<pixels.length;i+=4){
    const r=pixels[i],g=pixels[i+1],b=pixels[i+2],a=pixels[i+3];
    if(a&&(Math.abs(r-11)>5||Math.abs(g-15)>5||Math.abs(b-23)>5)&&i%sampleStep===0) nonBackgroundSamples++;
    if(a&&r>=20&&r<=95&&g>=125&&g<=235&&b>=175&&b>g+12&&g>r+65) boundaryPixels++;
  }
  return {width:canvas.width,height:canvas.height,css_width:rect.width,css_height:rect.height,
    non_background_samples:nonBackgroundSamples,boundary_pixels:boundaryPixels};
}'''


def record_response(report: dict, response) -> None:
    """Record every HTTP 4xx/5xx response, including APIRequestContext reads."""
    evidence = {'url': response.url, 'status': response.status}
    if response.status == 503:
        report.setdefault('http_503', []).append(evidence)
    if response.status >= 400:
        report.setdefault('http_errors', []).append(evidence)


def observe_api_request(report: dict, request) -> None:
    marker = '/api/v1/fabric-plans'
    url = request.url
    path = urlsplit(url).path
    if marker not in path:
        return
    base = url.split(marker, 1)[0].rstrip('/')
    if base and base not in report.setdefault('observed_api_bases', []):
        report['observed_api_bases'].append(base)


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_detail(detail: dict, fabric: str, locale: str = 'zh-TW') -> dict:
    """Validate the source completeness fields alongside the rendered UI."""
    assert detail.get('fabric_id') == fabric, f'fabric identity mismatch: {detail.get("fabric_id")!r}'
    package = detail.get('source_package') or {}
    assert Path(package.get('artifact_root', '')).parts[-3:] == ('artifacts', 'fab1', 'run-8'), 'expected NET2 run-8 plans'
    assert Path(package.get('syntax_root', '')).parts[-4:] == ('artifacts', 'net2', 'round-7', 'syntax'), 'expected NET2 round-7 syntax'
    rows = detail.get('land_use_table')
    assert isinstance(rows, list) and rows, 'land-use summary is missing'
    assert all(_finite_number(row.get('site_land_percent')) for row in rows), 'land-use share is not finite'
    total = sum(row['site_land_percent'] for row in rows)
    assert math.isclose(total, 100, abs_tol=1e-6), f'land-use share sums to {total}, not 100%'
    categories = [row.get('category') for row in rows]
    for category in ('retained_buildings', 'waterfront_public'):
        assert categories.count(category) == 1, f'{category} is not aggregated to one stable category row'

    statement = (detail.get('design_statement_markdown') or '').strip()
    pending = ('English design statement pending', 'English design statement updating') if locale == 'en' else ('設計說明產生中', '設計說明更新中')
    assert statement and (statement not in pending or locale == 'en'), 'design statement is missing or still pending'
    failure_ids = set((detail.get('checks') or {}).get('failure_ids') or [])
    explanations_key = 'check_explanations_en' if locale == 'en' else 'check_explanations_zh'
    explanations = detail.get(explanations_key) or {}
    assert failure_ids == set(explanations), 'failed checks do not have matching localized explanations'

    syntax = detail.get('syntax_summary') or {}
    results = syntax.get('results') or []
    assert syntax.get('status') == 'COMPUTED' and syntax.get('computed_count') == 12, 'syntax source package is incomplete'
    assert len(results) == 3 and {row.get('mode') for row in results} == {'pedestrian', 'bicycle', 'motor_vehicle'}, 'syntax modes are incomplete'
    for row in results:
        assert row.get('status') == 'COMPUTED', 'syntax result is uncomputed'
        assert _finite_number(row.get('delta_mean_integration_nain')), 'syntax delta is nonfinite'
        assert row.get('new_street_ranking_truncated') is False, 'syntax ranking is truncated'

    return {
        'fabric_id': fabric,
        'source_package': package,
        'land_percent_total': total,
        'stable_categories': categories,
        'syntax': {'status': syntax.get('status'), 'computed_count': syntax.get('computed_count'),
                   'result_count': len(results), 'modes': [row.get('mode') for row in results]},
        'failed_check_count': len(failure_ids),
        'design_statement': 'PENDING_ALLOWED_EN' if statement in ('English design statement pending', 'English design statement updating') else 'PRESENT',
    }


def _features(layers: dict, name: str) -> list:
    layer = layers.get(name)
    assert isinstance(layer, dict) and layer.get('type') == 'FeatureCollection', f'{name} is not a FeatureCollection'
    features = layer.get('features')
    assert isinstance(features, list), f'{name}.features is missing'
    return features


def _land_category(properties: dict) -> str:
    raw = next((properties.get(key) for key in ('category', 'land_use', 'role', 'category_zh')
                if properties.get(key) is not None), 'other')
    raw = str(raw).lower()
    aliases = {
        '公園': 'park', 'parks': 'park', '住宅': 'residential', '商業': 'commercial',
        '水域': 'water', 'retained_buildings': 'retained', 'block': 'blocks',
        'road': 'roads', 'plaza': 'plazas', 'waterfront_public': 'waterfront',
    }
    category = aliases.get(raw, raw)
    return category if category in FABRIC_COLORS else 'other'


def _floor_band(properties: dict) -> str:
    floors = properties.get('floors')
    if floors is None:
        floors = properties.get('floor_count')
    if not _finite_number(floors) or floors <= 0:
        return 'unknown'
    if floors <= 2:
        return '1–2F'
    if floors == 3:
        return '3F'
    if floors == 4:
        return '4F'
    if floors == 5:
        return '5F'
    return '6F+'


def _road_tier(properties: dict) -> int:
    tier = properties.get('hierarchy')
    if tier is None:
        tier = properties.get('road_hierarchy')
    if _finite_number(tier) and float(tier).is_integer() and 0 <= tier <= 3:
        return int(tier)
    return 4


def expected_legend(layers: dict, *, include_blocks: bool) -> list[dict]:
    """Mirror fabricLegend() so the browser's exact category set is checked."""
    entries: dict[str, dict] = {}

    def add(key: str, label: str, color: str) -> None:
        entries[key] = {'key': label, 'color': color}

    if _features(layers, 'site'):
        add('boundary', 'Site boundary', FABRIC_COLORS['boundary'])
    for feature in _features(layers, 'land_use'):
        category = _land_category(feature.get('properties') or {})
        add(category, f'Land use: {category}', FABRIC_COLORS.get(category, FABRIC_COLORS['other']))
    if include_blocks and _features(layers, 'blocks'):
        add('blocks', 'Land use: blocks', FABRIC_COLORS['blocks'])
    if _features(layers, 'parks'):
        add('park', 'Land use: park', FABRIC_COLORS['park'])
    water = layers.get('water')
    if water and _features(layers, 'water'):
        add('water', 'Land use: water', FABRIC_COLORS['water'])
    for feature in _features(layers, 'buildings'):
        properties = feature.get('properties') or {}
        band = 'retained' if properties.get('retained') is True else _floor_band(properties)
        color = FABRIC_COLORS[band]
        add('retained' if band == 'retained' else f'building-{band}', 'Land use: retained' if band == 'retained' else f'Buildings: {band}', color)
    for feature in _features(layers, 'roads'):
        tier = _road_tier(feature.get('properties') or {})
        label_tier = 'unknown' if tier == 4 else str(tier)
        add(f'road-{tier}', f'Road hierarchy {label_tier}', ROAD_COLORS[tier])
    return list(entries.values())


def assert_legend(container, layers: dict, *, include_blocks: bool) -> dict:
    expected = expected_legend(layers, include_blocks=include_blocks)
    legend = container.locator('[data-testid="fabric-legend"]')
    legend.wait_for(state='visible', timeout=15000)
    actual = legend.locator('[data-legend-key]').evaluate_all(
        "items => items.map(item => ({key:item.dataset.legendKey,color:item.dataset.legendColor}))"
    )
    declared_count = int(legend.get_attribute('data-legend-count') or '-1')
    assert declared_count == len(expected), f'legend count {declared_count} != palette categories {len(expected)}'
    assert actual == expected, f'legend entries differ from API palette categories: expected={expected!r}, actual={actual!r}'
    return {'count': declared_count, 'entries': actual}


def observe_main_2d(page, viewport, layers: dict) -> dict:
    canvas = viewport.locator('#canvas-viewport-2d')
    canvas.wait_for(state='visible', timeout=15000)
    selector = f'[data-testid="{viewport.get_attribute("data-testid")}"] #canvas-viewport-2d'
    page.wait_for_function(
        f'''selector => {{
          const canvas=document.querySelector(selector);
          const evidence=canvas?({CANVAS_PIXEL_EVIDENCE_JS})(canvas):null;
          return Boolean(evidence && evidence.non_background_samples>5 && evidence.boundary_pixels>0);
        }}''',
        arg=selector,
        timeout=20000,
        polling=250,
    )
    evidence = canvas.evaluate(CANVAS_PIXEL_EVIDENCE_JS)
    assert evidence is not None, '2D Site canvas has no readable rendered frame'
    assert evidence['non_background_samples'] > 5, f'2D Site canvas is blank: {evidence}'
    site_features = _features(layers, 'site')
    assert site_features, 'API has no site geometry to render in 2D'
    assert evidence['boundary_pixels'] > 0, f'2D canvas contains no rendered site-boundary pixels: {evidence}'
    return evidence


def expected_fabric_buildings(layers: dict) -> list[dict]:
    features = [feature for feature in _features(layers, 'buildings') if feature.get('geometry')]
    result = []
    for index, feature in enumerate(features):
        properties = feature.get('properties') or {}
        identifier = properties.get('building_id')
        height = properties.get('height_m')
        result.append({
            'id': str(identifier if identifier is not None else f'fabric-building-{index}'),
            'height_m': height if _finite_number(height) and height > 0 else 0,
        })
    return result


def building_color_pixel_fraction(pixels) -> float:
    assert pixels, '3D screenshot has no pixels'
    # Neutral retained-land fill is also gray, so gray cannot prove buildings rendered.
    colored = sum(1 for r,g,b in pixels if r > 35 and r > g * 1.08 and g > b * 1.08 and r-g < 70)
    return colored / len(pixels)


def observe_main_3d(page, viewport, layers: dict) -> dict:
    container = viewport.locator('#viewport-3d-container')
    canvas = container.locator('canvas')
    canvas.wait_for(state='visible', timeout=15000)
    page.wait_for_function(
        '''selector => document.querySelector(selector)?.dataset.fabricRenderState === 'ready' ''',
        arg=f'[data-testid="{viewport.get_attribute("data-testid")}"] #viewport-3d-container',
        timeout=30000,
    )
    evidence = container.evaluate('''element => {
      const canvas=element.querySelector('canvas'); const rect=canvas?.getBoundingClientRect();
      return {state:element.dataset.fabricRenderState,count:Number(element.dataset.fabricMeshCount),
        rendered:JSON.parse(element.dataset.fabricRenderedHeights || 'null'),
        canvas:canvas?{width:canvas.width,height:canvas.height,css_width:rect.width,css_height:rect.height}:null};
    }''')
    expected = expected_fabric_buildings(layers)
    assert evidence['state'] == 'ready', f'Three fabric geometry has not rendered: {evidence}'
    assert evidence['canvas'] and min(evidence['canvas']['width'], evidence['canvas']['height'], evidence['canvas']['css_width'], evidence['canvas']['css_height']) > 0, f'3D canvas has no pixels: {evidence}'
    assert evidence['count'] == len(expected) and len(evidence['rendered'] or []) == len(expected), (
        f'Three mesh count does not match API projected buildings: expected={len(expected)}, rendered={evidence}'
    )
    actual_by_id = {str(row.get('id')): row.get('height_m') for row in evidence['rendered'] or []}
    expected_by_id = {row['id']: row['height_m'] for row in expected}
    assert actual_by_id.keys() == expected_by_id.keys(), 'Three geometry IDs differ from the projected API buildings'
    for identifier, height in expected_by_id.items():
        rendered_height = actual_by_id[identifier]
        assert _finite_number(rendered_height) and math.isclose(rendered_height, height, abs_tol=1e-5), (
            f'Three geometry height differs for {identifier}: expected {height}, got {rendered_height}'
        )
    from PIL import Image
    pixels = list(Image.open(io.BytesIO(canvas.screenshot())).convert('RGB').getdata())
    # Brown floor-band surfaces, allowing shading and excluding neutral land fill,
    # blue water, syntax and dark background.
    evidence['building_color_pixel_fraction'] = building_color_pixel_fraction(pixels)
    assert evidence['building_color_pixel_fraction'] > .01, f'3D canvas has less than 1% building-color pixels: {evidence}'
    camera = container.evaluate('e => JSON.parse(e.dataset.fabricCamera || "null")')
    assert camera and all(math.isfinite(v) for v in camera['target'] + camera['position'] + [camera['radius']]), f'nonfinite 3D camera: {camera}'
    bounds = container.evaluate('e => JSON.parse(e.dataset.fabricSiteBounds || "null")')
    points = []
    def collect(value):
        if isinstance(value, list) and len(value) >= 2 and all(_finite_number(v) for v in value[:2]): points.append(value[:2])
        elif isinstance(value, list):
            for child in value: collect(child)
    collect(_features(layers, 'site')[0]['geometry']['coordinates'])
    expected_bounds = [[min(p[0] for p in points)-89100,min(p[1] for p in points)-435900,0],
                       [max(p[0] for p in points)-89100,max(p[1] for p in points)-435900,0]]
    assert bounds and all(math.isclose(a,b,abs_tol=.001) for actual,expected in zip(bounds,expected_bounds) for a,b in zip(actual,expected)), '3D fit range differs from 2D projected site'
    coverage = container.evaluate('e => JSON.parse(e.dataset.fabricSiteCoverage || "null")')
    assert coverage and coverage['unclipped'] and max(coverage['width'], coverage['height']) >= .6, f'3D site must occupy >=60% without clipping: {coverage}'
    evidence['site_coverage'] = coverage
    evidence['camera'] = camera
    evidence['site_local_bounds'] = bounds
    evidence['expected_building_count'] = len(expected)
    return evidence


def map_coverage(page, fabric: str, map_id: str | None = None) -> dict:
    """Read the MapLibre projection measurement for the API site's bounds."""
    map_id = map_id or fabric
    selector = f'[data-testid="fabric-map-{map_id}"]'
    page.wait_for_function(
        'selector => document.querySelector(selector)?.dataset.coverageMeasurement === "map-project"',
        arg=selector,
        timeout=15000,
    )
    result = page.locator(selector).evaluate(
        'e => ({basis:e.dataset.fitBasis,measurement:e.dataset.coverageMeasurement,'
        'width:Number(e.dataset.siteWidthCoverage),height:Number(e.dataset.siteHeightCoverage),'
        'area:Number(e.dataset.siteBoundsAreaCoverage)})'
    )
    assert result['basis'] == 'site-mercator-bounding-box', f'MapLibre fit basis is unexpected: {result}'
    assert all(0.85 <= result[key] <= 1.001 for key in ('width', 'height', 'area')), (
        f'MapLibre site bounds must cover at least 85% without clipping: {result}'
    )
    return result


def assert_maplibre_mode(page, fabric: str, mode: str, layers: dict, map_id: str | None = None) -> dict:
    """Verify ready MapLibre output and its actual style, pitch, and site feature."""
    map_id = map_id or fabric
    selector = f'[data-testid="fabric-map-{map_id}"]'
    wrapper = page.locator(selector)
    wrapper.wait_for(state='visible', timeout=15000)
    wrapper.locator('.maplibregl-canvas').wait_for(state='visible', timeout=30000)
    page.wait_for_function(
        '''({mapId, mode}) => {
          const wrapper=document.querySelector(`[data-testid="fabric-map-${mapId}"]`);
          const map=window.__fabricCompareMaps?.[mapId];
          const layers=map?.getStyle?.()?.layers ?? [];
          const twoD=layers.find(layer=>layer.id==='buildings'&&layer.type==='fill');
          const threeD=layers.find(layer=>layer.id==='buildings-3d'&&layer.type==='fill-extrusion');
          const canvas=map?.getCanvas?.();
          if (!wrapper || wrapper.dataset.mapState!=='ready' || wrapper.dataset.mapMode!==mode || !map
              || !canvas || canvas.width<1 || canvas.height<1) return false;
          if (mode==='3D') return map.getPitch()>=30 && threeD?.layout?.visibility==='visible';
          return map.getPitch()<=1 && twoD?.layout?.visibility!=='none'
            && (!threeD || threeD.layout?.visibility==='none');
        }''',
        arg={'mapId': map_id, 'mode': mode},
        timeout=30000,
    )
    evidence = page.evaluate(
        '''mapId => {
          const map=window.__fabricCompareMaps?.[mapId]; const canvas=map?.getCanvas?.();
          let siteFeatures=0;
          try { siteFeatures=map?.queryRenderedFeatures?.({layers:['site']})?.length ?? 0; } catch {}
          const layers=map?.getStyle?.()?.layers ?? [];
          const extrusion=layers.find(layer=>layer.id==='buildings-3d');
          return {pitch:map?.getPitch(),canvas:canvas?{width:canvas.width,height:canvas.height}:null,
            rendered_site_features:siteFeatures,extrusion_type:extrusion?.type,
            extrusion_visibility:extrusion?.layout?.visibility};
        }''',
        map_id,
    )
    assert evidence['rendered_site_features'] > 0, f'MapLibre has no rendered site geometry: {evidence}'
    if mode == '2D':
        evidence['coverage'] = map_coverage(page, fabric, map_id)
    else:
        from PIL import Image
        pixels = list(Image.open(io.BytesIO(wrapper.locator('.maplibregl-canvas').screenshot())).convert('RGB').getdata())
        evidence['building_color_pixel_fraction'] = building_color_pixel_fraction(pixels)
        assert evidence['building_color_pixel_fraction'] > .01, f'four-map 3D has less than 1% building-color pixels: {evidence}'
    evidence['legend'] = assert_legend(wrapper, layers, include_blocks=True)
    return evidence


def assert_properties(page, fabric: str, detail: dict, locale: str) -> dict:
    """Select one plan and bind the visible Properties values back to its API data."""
    button = page.locator(f'[data-testid="fabric-select-{fabric}"]')
    button.click()
    assert button.get_attribute('aria-pressed') == 'true', f'{fabric} did not become the selected plan'
    properties = page.locator('[data-testid="fabric-properties"]')
    page.wait_for_function(
        "fabric => document.querySelector('[data-testid=\"fabric-properties\"]')?.dataset.fabricId === fabric",
        arg=fabric,
        timeout=15000,
    )
    properties.wait_for(state='visible', timeout=15000)
    assert (
        'EXPLORATORY_DRAFT' in properties.inner_text()
        or '探索草案' in properties.inner_text()
        or 'Exploratory draft' in properties.inner_text()
        or properties.locator('[data-status="EXPLORATORY_DRAFT"]').is_visible()
    ), 'Properties does not identify an exploratory draft'
    assert 'UNAPPROVED_PREVIEW' not in properties.inner_text(), 'Properties retains a legacy preview'
    assumption_values = properties.locator('dl').last.locator('dd').all_inner_texts()
    assert len(assumption_values) == 2, 'Properties assumptions are incomplete'
    assert '146,873' in assumption_values[0] and 'ASSUMED' in assumption_values[0], 'New-building-only assumed GFA cap is incorrect'
    assert assumption_values[1].strip() == '20 m', 'Height cap is incorrect'
    label = button.inner_text().strip()
    assert properties.locator('h3').first.inner_text().strip() == label, f'Properties label does not match {fabric}'
    first_dl_values = properties.locator('dl').first.locator('dd').all_inner_texts()
    assert first_dl_values and first_dl_values[0].strip() == fabric, f'Properties scheme ID does not match {fabric}'

    metric_values = properties.locator('dl').nth(1).locator('dd').all_inner_texts()
    expected_metrics = detail.get('metrics') or {}
    metric_keys = ('new_far', 'gsi', 'new_building_count', 'fsi', 'L', 'OSR', 'new_gfa_m2', 'land_area_m2')
    assert len(metric_values) == len(metric_keys), f'Properties metrics are incomplete for {fabric}: {metric_values}'
    parsed_metrics = []
    for rendered, key in zip(metric_values, metric_keys):
        expected = expected_metrics.get(key)
        actual = parse_rendered_number(rendered)
        if _finite_number(expected):
            assert actual is not None and math.isclose(actual, expected, abs_tol=0.00051), (
                f'Properties {key} does not match API {fabric}: expected {expected}, rendered {rendered!r}'
            )
        else:
            assert actual is None, f'Properties {key} should be unavailable, rendered {rendered!r}'
        parsed_metrics.append({'key': key, 'rendered': rendered.strip(), 'api_value': expected})

    assert properties.locator('img').count() == 0, 'static previews must not displace interactive Properties'
    image_paths = properties.locator('a[download]').evaluate_all('links => links.map(link => link.getAttribute("href"))')
    assert len(image_paths) == 1 and all(f'/fabric-plans/{fabric}/figures/plan' in path for path in image_paths), (
        f'Properties figures do not belong to {fabric}: {image_paths}'
    )
    details = page.locator(f'[data-testid="fabric-details"][data-fabric-id="{fabric}"]')
    details.wait_for(state='visible', timeout=15000)
    assert '100%' in details.locator('.fabric-land-table tfoot').inner_text(), 'detail land-use total is not 100%'
    assert details.locator('.fabric-statement details').first.get_attribute('open') is not None, 'design statement preview is collapsed'
    if locale == 'en':
        assert_english_visible_text(page)
    return {'fabric_id': fabric, 'label': label, 'scheme_id': first_dl_values[0].strip(),
            'metrics': parsed_metrics, 'figure_count': len(image_paths)}


def parse_rendered_number(value: str) -> float | None:
    cleaned = value.replace(',', '').replace('\u00a0', '').replace('\u202f', '').strip()
    if cleaned in ('', '—', '-'):
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def assert_parallel_properties(page, details_by_id: dict[str, dict]) -> dict:
    """Validate four Properties rows and their values against the four read-only plans."""
    properties = page.locator('[data-testid="fabric-properties"]')
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"fabric-properties\"]')?.dataset.fabricId === 'all'",
        timeout=15000,
    )
    rows = properties.locator('table tbody tr')
    assert rows.count() == 4, 'parallel Properties does not contain four plan rows'
    evidence = []
    for index, fabric in enumerate(FABRICS):
        cells = rows.nth(index).locator('td').all_inner_texts()
        assert len(cells) == 4, f'parallel Properties row is incomplete: {cells}'
        expected_label = page.locator(f'[data-testid="fabric-select-{fabric}"]').inner_text().strip()
        assert cells[0].strip() == expected_label, f'parallel Properties label does not match {fabric}'
        expected = details_by_id[fabric].get('metrics') or {}
        for cell, key in zip(cells[1:], ('new_far', 'new_gfa_m2', 'new_building_count')):
            actual = parse_rendered_number(cell)
            value = expected.get(key)
            if _finite_number(value):
                assert actual is not None and math.isclose(actual, value, abs_tol=0.00051), (
                    f'parallel Properties {fabric}.{key} differs from API: expected {value}, rendered {cell!r}'
                )
            else:
                assert actual is None, f'parallel Properties {fabric}.{key} should be unavailable'
        evidence.append({'fabric_id': fabric, 'label': cells[0].strip(),
                         'far': cells[1].strip(), 'new_gfa_m2': cells[2].strip(),
                         'new_building_count': cells[3].strip()})
    if page.locator('[data-testid="fabric-compare"]').is_visible():
        # The visible summary is the shell Properties panel; there should be no stale plan previews.
        assert properties.locator('img').count() == 0, 'parallel Properties retained a single-plan figure'
    return {'fabric_id': 'all', 'rows': evidence}


def assert_english_visible_text(page) -> None:
    # Ariadne-generated prose and designer replies carry their own lang attribute (cards are written in the
    # language requested at generation time); only UI text must follow the English interface.
    fabric_text = page.locator('[data-testid="fabric-compare"]').evaluate(
        "el => { const c = el.cloneNode(true); c.querySelectorAll('[lang]:not([lang^=\"en\"])').forEach(n => n.remove()); document.body.appendChild(c); const t = c.innerText; c.remove(); return t; }")
    properties_text = page.locator('[data-testid="fabric-properties"]').inner_text()
    for section, text in (('fabric', fabric_text), ('properties', properties_text)):
        match = CJK.search(text)
        assert match is None, f'English visible {section} text contains CJK character {match.group(0)!r}'


def check_layout(page) -> dict:
    evidence = page.evaluate('''() => ({viewport:innerWidth,document:document.documentElement.scrollWidth,
      body:document.body.scrollWidth,containers:[...document.querySelectorAll('[data-testid="fabric-compare"],.fabric-layout')]
        .map(e=>({width:e.clientWidth,scroll:e.scrollWidth}))})''')
    assert evidence['document'] <= evidence['viewport'] and evidence['body'] <= evidence['viewport'], (
        f'horizontal page overflow at {evidence["viewport"]}px: {evidence}'
    )
    return evidence


def _api_base(args, report: dict) -> str:
    if args.api_base:
        return args.api_base.rstrip('/')
    bases = report.get('observed_api_bases') or []
    assert bases, 'could not derive API base from the read-only fabric-plan requests; supply --api-base'
    assert len(bases) == 1, f'fabric plan requests used multiple API bases: {bases}'
    return bases[0]


def read_plan_data(context, report: dict, api_base: str, locale: str) -> dict[str, dict]:
    """Fetch catalog and plan details with GET only, recording their HTTP status."""
    language = 'en' if locale == 'en' else 'zh'
    catalog_response = context.request.get(f'{api_base}/api/v1/fabric-plans', timeout=30000)
    record_response(report, catalog_response)
    assert catalog_response.status == 200, f'fabric catalog GET returned HTTP {catalog_response.status}'
    catalog = catalog_response.json()
    catalog_ids = [row.get('fabric_id') for row in catalog.get('plans', [])]
    assert tuple(catalog_ids) == FABRICS, f'fabric catalog IDs/order mismatch: {catalog_ids}'

    details = {}
    for fabric in FABRICS:
        response = context.request.get(
            f'{api_base}/api/v1/fabric-plans/{fabric}?lang={language}', timeout=30000
        )
        record_response(report, response)
        assert response.status == 200, f'{fabric} detail GET returned HTTP {response.status}'
        detail = response.json()
        details[fabric] = detail
        check_detail(detail, fabric, locale)
        _features(detail.get('layers_projected') or {}, 'site')
    return details


def assert_main_viewport(page, fabric: str, mode: str, detail: dict) -> dict:
    viewport = page.locator(f'[data-testid="fabric-viewport-{fabric}"]')
    viewport.wait_for(state='visible', timeout=20000)
    assert viewport.get_attribute('data-map-mode') == mode, f'{fabric} wrapper did not enter {mode}'
    assert viewport.get_attribute('data-crs') == 'EPSG:28992', f'{fabric} wrapper has a different CRS'
    evidence = {'mode': mode, 'crs': 'EPSG:28992',
                'legend': assert_legend(viewport, detail['layers_projected'], include_blocks=False)}
    if mode in ('2D', 'SPLIT'):
        evidence['site_2d'] = observe_main_2d(page, viewport, detail['layers_projected'])
    if mode in ('3D', 'SPLIT'):
        evidence['site_3d'] = observe_main_3d(page, viewport, detail['layers_projected'])
    return evidence


def _parallel_map_ids(fabric: str, mode: str) -> list[tuple[str, str]]:
    if mode == '2D':
        return [(fabric, '2D')]
    if mode == '3D':
        return [(fabric, '3D')]
    return [(fabric, '2D'), (f'{fabric}-3d', '3D')]


def check_segment_document(document: dict) -> dict:
    """Reject invented zero deltas and incomplete compact segment contracts."""
    assert document.get('type') == 'FeatureCollection', 'syntax GeoJSON missing'
    assert document.get('crs', {}).get('properties', {}).get('name') == 'EPSG:28992', 'syntax CRS mismatch'
    breaks = document.get('legend_breaks', {})
    for metric in ('nain', 'nach'):
        values = breaks.get(metric)
        assert isinstance(values, list) and len(values) == 6 and all(_finite_number(v) for v in values), 'syntax breaks missing'
        assert values == sorted(values), 'syntax breaks unordered'
    features = document.get('features')
    assert isinstance(features, list) and features, 'syntax segment data empty'
    identifiers = set()
    for feature in features:
        p = feature.get('properties', {})
        assert p.get('segment_id') and p['segment_id'] not in identifiers, 'missing/duplicate segment ID'
        identifiers.add(p['segment_id'])
        assert isinstance(p.get('is_new_street'), bool) and isinstance(p.get('inside_site'), bool), 'segment flags missing'
        assert feature.get('geometry', {}).get('type') in ('LineString', 'MultiLineString'), 'syntax geometry missing'
        for metric in ('nain', 'nach'):
            before, after, delta = (p.get(f'{prefix}_{metric}') for prefix in ('before', 'after', 'delta'))
            assert all(v is None or _finite_number(v) for v in (before, after, delta)), 'nonfinite syntax value'
            if before is None or after is None:
                assert delta is None, 'new/removed segment has fabricated zero delta'
            else:
                assert _finite_number(delta) and math.isclose(delta, after-before, abs_tol=1e-9), 'syntax delta mismatch'
    return {'segment_count': len(features), 'legend_breaks': breaks}


def check_net1_document(document: dict, mode: str) -> dict:
    assessment = document.get('net1_assessment') or {}
    assert assessment.get('schema_version') == 'net1-assessment-v1', 'NET1 assessment missing'
    assert assessment.get('mode') == mode and assessment.get('formal_result_eligible') is False, 'NET1 identity/scope mismatch'
    checks = {c['target']: c for c in assessment.get('checks', [])}
    if mode in ('pedestrian', 'bicycle'):
        expected = {'primary_street': 80 if mode == 'pedestrian' else 70,
                    'connection Keileweg': 1, 'connection Dakpark': 1, 'waterfront multiple joins': 2}
        if mode == 'pedestrian': expected['waterfront_path'] = 50
        for name, minimum in expected.items():
            check = checks.get(name) or {}
            assert check.get('minimum') == minimum, 'NET1 threshold drift'
            assert check.get('status') in ('PASS', 'FAIL', 'UNAVAILABLE'), 'NET1 check status missing'
            if check['status'] == 'UNAVAILABLE': assert check.get('value') is None, 'missing NET1 value replaced by number'
            else:
                assert _finite_number(check.get('value')), 'NET1 measured value missing'
                assert (check['value'] >= minimum) == (check['status'] == 'PASS'), 'NET1 status contradicts measurement'
    else:
        assert assessment.get('status') == 'DESCRIPTIVE_ONLY', 'motor has no percentile acceptance threshold'
    return {'mode': mode, 'status': assessment['status'], 'checks': list(checks.values())}



def check_net2_document(document: dict, mode: str) -> dict:
    assessment = document.get('net2_assessment') or {}
    assert assessment.get('schema_version') == 'net2-assessment-v1', 'NET2 assessment missing'
    assert assessment.get('mode') == mode and assessment.get('formal_result_eligible') is False, 'NET2 scope mismatch'
    baselines = assessment.get('baselines') or {}
    checks = assessment.get('checks') or []
    assert isinstance(checks, list), 'NET2 checks must be a list'
    if mode == 'motor_vehicle':
        assert not checks and assessment.get('status') == 'DESCRIPTIVE_ONLY', 'NET2 motor must be descriptive only without checks'
    else:
        required = {'primary_street', 'connection Keileweg', 'connection Dakpark', 'waterfront multiple joins'}
        if mode == 'pedestrian': required.add('waterfront_path')
        targets = [c.get('target') for c in checks]
        assert required.issubset(targets) and len(targets) == len(set(targets)), 'NET2 required checks missing or duplicated'
    for key in ('primary_meets', 'primary_excellent', 'waterfront_meets'):
        baseline = baselines.get(key) or {}
        assert isinstance(baseline.get('reference'), str) and baseline['reference'].strip(), 'NET2 baseline reference missing'
        assert isinstance(baseline.get('method'), str) and baseline['method'].strip(), 'NET2 baseline method missing'
        count = baseline.get('sample_count')
        assert type(count) is int and count >= 0, 'NET2 baseline sample_count missing'
        percentile = baseline.get('percentile')
        assert percentile is None or (_finite_number(percentile) and 0 <= percentile <= 100 and count > 0), 'NET2 baseline percentile unsupported'
    for check in checks:
        value, minimum = check.get('value'), check.get('minimum')
        key = {'primary_street': 'primary_meets', 'waterfront_path': 'waterfront_meets'}.get(check.get('target'))
        if key:
            assert minimum == baselines[key]['percentile'], 'NET2 threshold differs from measured baseline'
            if key == 'primary_meets':
                assert check.get('excellent_minimum') == baselines['primary_excellent']['percentile'], 'NET2 excellent threshold differs from measured baseline'
        else:
            expected = 2 if check.get('target') == 'waterfront multiple joins' else 1
            assert minimum == expected, 'NET2 junction target drift'
        assert check.get('status') in ('PASS', 'FAIL', 'UNAVAILABLE'), 'NET2 check status missing'
        if check['status'] == 'UNAVAILABLE':
            assert value is None or minimum is None, 'unavailable check has complete measurements'
            continue
        assert _finite_number(value) and _finite_number(minimum), 'NET2 measurement/reference missing'
        assert (value >= minimum) == (check['status'] == 'PASS'), 'NET2 status contradicts measured reference'
    if checks:
        expected_status = 'UNAVAILABLE' if any(c['status'] == 'UNAVAILABLE' for c in checks) else 'PASS' if all(c['status'] == 'PASS' for c in checks) else 'FAIL'
        assert assessment.get('status') == expected_status, 'NET2 aggregate status contradicts checks'
    return {'mode': mode, 'status': assessment.get('status'), 'checks': checks, 'baselines': baselines}

def exercise_syntax(page, context, report, api_base: str, stage: str, locale: str, output_dir: Path) -> None:
    """INT3 controls, rendered legends and paired-camera evidence; GET only."""
    page.locator('#shell-view-2d').click()
    page.locator(f'[data-testid="fabric-select-{FABRICS[0]}"]').click()
    toggle = page.locator('[data-testid="fabric-syntax-toggle"]')
    toggle.wait_for(state='visible', timeout=20000)
    toggle.check()
    for movement in ('pedestrian', 'bicycle', 'motor_vehicle'):
        response = context.request.get(f'{api_base}/api/v1/fabric-plans/{FABRICS[0]}/syntax/{movement}')
        record_response(report, response)
        assert response.status == 200, f'compact syntax GET {movement}: HTTP {response.status}'
        report['checks'].append({'net2': check_net2_document(response.json(), movement)})
        document = check_segment_document(response.json())
        page.locator('[data-testid="fabric-syntax-mode"]').select_option(movement)
        for metric in ('nain', 'nach'):
            page.locator('[data-testid="fabric-syntax-metric"]').select_option(metric)
            for view in ('before', 'after', 'diff'):
                page.locator('[data-testid="fabric-syntax-view"]').select_option(view)
                page.wait_for_function('expected => {const e=document.querySelector("[data-testid=fabric-syntax-comparison]");return e?.dataset.state==="ready"&&e.dataset.mode===expected.mode&&e.dataset.metric===expected.metric&&e.dataset.view===expected.view}', arg={'mode': movement, 'metric': metric, 'view': view}, timeout=30000)
                page.wait_for_function('expected => {const c=document.querySelector("[data-testid=fabric-syntax-comparison] #canvas-viewport-2d");return c?.dataset.syntaxView===expected.view&&c.dataset.syntaxMetric===expected.metric&&Number(c.dataset.syntaxSegmentCount)>0}', arg={'view':view,'metric':metric}, timeout=15000)
                legend = page.locator('[data-testid="fabric-syntax-legend"]')
                legend.wait_for(state='visible', timeout=15000)
                assert legend.inner_text().strip(), 'syntax legend empty'
                assert legend.get_attribute('data-view') == view and legend.get_attribute('data-metric') == metric, 'stale syntax legend'
                if view == 'diff':
                    assert all(label in legend.inner_text() for label in (('Decrease','Unchanged','Increase') if locale=='en' else ('降低','不變','提高'))), 'difference legend is incomplete'
                if locale == 'en':
                    assert_english_visible_text(page)
                # Three distinct views for each stage and language; all other controls are checked too.
                if movement == 'pedestrian' and metric == 'nain':
                    shot = output_dir / f'{stage}-{locale}-syntax-{view}.png'
                    legend.scroll_into_view_if_needed()
                    page.screenshot(path=str(shot), full_page=True)
                    report['screenshots'].append(str(shot))
                report['checks'].append({'syntax_view': view, 'mode': movement, 'metric': metric, **document, 'legend': legend.inner_text()})
    page.locator('[data-testid="fabric-intent-checks"]').wait_for(state='visible', timeout=15000)
    page.locator('[data-testid="fabric-net2-checks"]').wait_for(state='visible', timeout=15000)
    page.locator('[data-testid="fabric-syntax-split"]').click()
    paired = page.locator('[data-testid="fabric-syntax-split-views"]')
    paired.wait_for(state='visible', timeout=15000)
    assert paired.locator('[data-syntax-phase="before"]').count() == 1 and paired.locator('[data-syntax-phase="after"]').count() == 1, 'split is not before/after'
    # Real navigation, followed by equality of the published actual transforms.
    canvas = paired.locator('[data-syntax-phase="before"] canvas').first
    box = canvas.bounding_box()
    assert box, 'split canvas absent'
    page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
    page.mouse.wheel(0, -100)
    page.wait_for_function('() => {const e=document.querySelector("[data-testid=fabric-syntax-split-views]");const a=e?.querySelector("[data-syntax-phase=before] canvas");const b=e?.querySelector("[data-syntax-phase=after] canvas");return a?.dataset.renderTransform&&a.dataset.renderTransform===b?.dataset.renderTransform}', timeout=15000)
    report['checks'].append({'syntax_split_sync': 'PASS'})
    page.locator('#shell-view-3d').click()
    left = paired.locator('[data-syntax-phase="before"] #viewport-3d-container')
    right = paired.locator('[data-syntax-phase="after"] #viewport-3d-container')
    left.locator('canvas').wait_for(state='visible', timeout=15000)
    right.locator('canvas').wait_for(state='visible', timeout=15000)
    page.wait_for_function('() => {const e=document.querySelector("[data-testid=fabric-syntax-split-views]");const a=e?.querySelector("[data-syntax-phase=before] #viewport-3d-container");const b=e?.querySelector("[data-syntax-phase=after] #viewport-3d-container");return a?.dataset.fabricCamera&&a.dataset.fabricCamera===b?.dataset.fabricCamera}', timeout=15000)
    initial = left.get_attribute('data-fabric-camera')
    box = left.locator('canvas').bounding_box()
    assert box, 'split 3D canvas absent'
    page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
    page.mouse.wheel(0, -100)
    page.wait_for_function('initial => {const e=document.querySelector("[data-testid=fabric-syntax-split-views]");const a=e?.querySelector("[data-syntax-phase=before] #viewport-3d-container");const b=e?.querySelector("[data-syntax-phase=after] #viewport-3d-container");return a?.dataset.fabricCamera&&a.dataset.fabricCamera!==initial&&a.dataset.fabricCamera===b?.dataset.fabricCamera}', arg=initial, timeout=15000)
    report['checks'].append({'syntax_split_3d_sync': 'PASS', 'camera': left.get_attribute('data-fabric-camera')})
    page.locator('[data-testid="fabric-syntax-split"]').click()
    toggle.uncheck()


def exercise_stage_locale(browser, args, stage: str, locale: str, output_dir: Path) -> dict:
    report = {
        'stage': stage, 'locale': locale, 'status': 'INCOMPLETE', 'screenshots': [],
        'checks': [], 'observed_api_bases': [], 'console_errors': [], 'page_errors': [],
        'http_errors': [], 'http_503': [],
    }
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
    context.add_init_script(f'localStorage.setItem("urban-design-language", {json.dumps(locale)});')
    page = context.new_page()
    page.on('request', lambda request: observe_api_request(report, request))
    page.on('response', lambda response: record_response(report, response))
    page.on('console', lambda message: report['console_errors'].append(message.text) if message.type == 'error' else None)
    page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
    try:
        page.goto(args.url, wait_until='domcontentloaded', timeout=60000)
        page.locator('.design-shell').wait_for(state='visible', timeout=30000)
        page.wait_for_function(
            'locale => document.querySelector(".design-shell")?.getAttribute("lang") === locale',
            arg=locale, timeout=15000,
        )
        page.locator(f'#stage-{stage}').click()
        page.wait_for_function(
            'stage => document.querySelector(`#stage-${stage}`)?.getAttribute("aria-current") === "step"',
            arg=stage, timeout=15000,
        )
        compare = page.locator('[data-testid="fabric-compare"]')
        compare.wait_for(state='visible', timeout=30000)
        compare.locator(f'[data-testid="fabric-select-{FABRICS[0]}"]').wait_for(state='visible', timeout=30000)
        properties_tab = page.locator('.shell-properties .panel-tabs button').first
        properties_tab.click()
        assert properties_tab.get_attribute('aria-pressed') == 'true', 'could not activate shell Properties'
        api_base = _api_base(args, report)
        report['api_base'] = api_base
        details_by_id = read_plan_data(context, report, api_base, locale)
        compare.scroll_into_view_if_needed()

        for mode in MODES:
            view_button = page.locator(f'#shell-view-{mode.lower()}')
            view_button.click()
            assert view_button.get_attribute('aria-pressed') == 'true', f'{stage} did not select {mode}'
            page.wait_for_timeout(250)
            single_checks = []
            for index, fabric in enumerate(FABRICS):
                properties = assert_properties(page, fabric, details_by_id[fabric], locale)
                rendering = assert_main_viewport(page, fabric, mode, details_by_id[fabric])
                if locale == 'en':
                    assert_english_visible_text(page)
                single_checks.append({'fabric_id': fabric, 'properties': properties, 'rendering': rendering})
                if index == 0:
                    shot = output_dir / f'{stage}-{locale}-{mode.lower()}-selected.png'
                    page.locator('[data-testid="fabric-legend"]').first.scroll_into_view_if_needed()
                    page.screenshot(path=str(shot), full_page=True)
                    report['screenshots'].append(str(shot))
            report['checks'].append({'mode': mode, 'single_selection': single_checks,
                                     'layout': check_layout(page)})

            page.locator('[data-testid="fabric-parallel-toggle"]').click()
            parallel = page.locator('[data-testid="fabric-maps"]')
            page.wait_for_function(
                '() => document.querySelectorAll("[data-testid=fabric-maps] > figure").length === 4',
                timeout=15000,
            )
            assert page.locator('[data-testid="fabric-parallel-toggle"]').get_attribute('aria-pressed') == 'true', 'four-map mode did not turn on'
            parallel_maps = {}
            for fabric in FABRICS:
                per_map = []
                for map_id, map_mode in _parallel_map_ids(fabric, mode):
                    map_selector = f'[data-testid="fabric-map-{map_id}"]'
                    wrapper = parallel.locator(map_selector)
                    wrapper.wait_for(state='visible', timeout=15000)
                    assert wrapper.get_attribute('data-map-mode') == map_mode, f'{map_id} MapLibre mode mismatch'
                    per_map.append({
                        'map_id': map_id,
                        **assert_maplibre_mode(page, fabric, map_mode, details_by_id[fabric]['layers'], map_id),
                    })
                parallel_maps[fabric] = per_map
            summary = assert_parallel_properties(page, details_by_id)
            if locale == 'en':
                assert_english_visible_text(page)
            report['checks'].append({'mode': mode, 'four_map_parallel': parallel_maps,
                                     'properties_summary': summary, 'layout': check_layout(page)})
            shot = output_dir / f'{stage}-{locale}-{mode.lower()}-four-up.png'
            page.screenshot(path=str(shot), full_page=False)
            report['screenshots'].append(str(shot))
            page.locator('[data-testid="fabric-parallel-toggle"]').click()
            assert page.locator('[data-testid="fabric-parallel-toggle"]').get_attribute('aria-pressed') == 'false', 'could not restore single-map mode'

        exercise_syntax(page, context, report, api_base, stage, locale, output_dir)
        assert not report['http_errors'], 'HTTP 4xx/5xx responses: ' + json.dumps(report['http_errors'], ensure_ascii=False)
        assert not report['console_errors'], 'browser console contains errors'
        assert not report['page_errors'], 'browser raised an uncaught page exception'
        report['status'] = 'PASS'
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = str(error)
        try:
            shot = output_dir / f'{stage}-{locale}-failure.png'
            page.screenshot(path=str(shot), full_page=False, timeout=10000)
            report['screenshots'].append(str(shot))
        except Exception as screenshot_error:
            report['failure_screenshot_error'] = str(screenshot_error)
    finally:
        context.close()
    return report


def run(args) -> int:
    output_dir = args.output_dir.expanduser().resolve()
    output_dir_created = False
    report = {
        'schema_version': 'fabric-compare-rehearsal/2', 'status': 'INCOMPLETE',
        'url': args.url, 'output_dir': str(output_dir), 'api_base_argument': args.api_base,
        'reports': {}, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'verification_limits': [
            'This script performs browser and read-only GET checks; it does not start services or write API state.',
        ],
    }
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
        output_dir_created = True
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=args.browser, headless=not args.headed,
                args=['--enable-unsafe-swiftshader'],
            )
            try:
                for stage in STAGES:
                    for locale in LOCALES:
                        key = f'{stage}-{locale}'
                        report['reports'][key] = exercise_stage_locale(browser, args, stage, locale, output_dir)
            finally:
                browser.close()
        report['status'] = 'PASS' if all(
            result.get('status') == 'PASS' for result in report['reports'].values()
        ) else 'FAIL'
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = str(error)
    finally:
        report['completed_at_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            if not output_dir_created:
                raise RuntimeError('output directory already exists or could not be created; refusing to overwrite artifacts')
            (output_dir / 'browser-report.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
            )
        except Exception as write_error:
            report['report_write_error'] = str(write_error)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Commander-provided UI URL; no service or database is started.')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parents[2] / 'artifacts/int3' / ('browser-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')), help='Directory for screenshots and browser-report.json; defaults to a new timestamped artifacts/int3/browser directory.')
    parser.add_argument('--api-base', help='Optional API origin/prefix; otherwise derived from browser fabric-plan requests.')
    parser.add_argument('--browser', default=CHROME, help='Chromium-compatible browser executable path.')
    parser.add_argument('--headed', action='store_true', help='Show the browser window for an attended rehearsal.')
    sys.exit(run(parser.parse_args()))
