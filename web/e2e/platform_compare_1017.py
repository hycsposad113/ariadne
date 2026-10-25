"""Read-only Compare/Generate walkthrough using real source-backed fabric plans.

Caller owns services, browser lifecycle, locale initialization and artifact directory.
No request interception, mocked data, decision fixtures or state-changing API calls.
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from . import fabric_compare as existing
except ImportError:
    import fabric_compare as existing


def site_points(layers: dict) -> list[list[float]]:
    points = []

    def collect(value):
        if isinstance(value, list) and len(value) >= 2 and all(existing._finite_number(v) for v in value[:2]):
            points.append(value[:2])
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for feature in existing._features(layers, 'site'):
        collect((feature.get('geometry') or {}).get('coordinates'))
    assert points, 'source site has no finite coordinates'
    return points


def assert_site_2d_fit(canvas, layers: dict) -> dict:
    """Project every source site vertex with the actual rendered canvas transform."""
    state = canvas.evaluate('''c => { const r=c.getBoundingClientRect(); return {
      transform:JSON.parse(c.dataset.renderTransform || 'null'), width:r.width,height:r.height,
      bitmap_width:c.width,bitmap_height:c.height}; }''')
    transform = state['transform']
    assert transform and all(existing._finite_number(v) for v in transform.values()), state
    assert transform['zoom'] > 0 and min(state['width'], state['height']) > 0, state
    projected = [(transform['panX'] + (x-transform['originX'])*transform['zoom'],
                  transform['panY'] - (y-transform['originY'])*transform['zoom'])
                 for x, y in site_points(layers)]
    bounds = {'min_x': min(p[0] for p in projected), 'max_x': max(p[0] for p in projected),
              'min_y': min(p[1] for p in projected), 'max_y': max(p[1] for p in projected)}
    margin = min(state['width'], state['height']) * .02
    assert bounds['min_x'] >= margin and bounds['min_y'] >= margin, f'site clips canvas start: {bounds}, {state}'
    assert bounds['max_x'] <= state['width']-margin and bounds['max_y'] <= state['height']-margin, f'site clips canvas end: {bounds}, {state}'
    coverage = max((bounds['max_x']-bounds['min_x'])/state['width'],
                   (bounds['max_y']-bounds['min_y'])/state['height'])
    assert .85 < coverage <= 1, f'site underfills canvas: {coverage}'
    return {**state, 'projected_bounds': bounds, 'vertex_count': len(projected),
            'limiting_axis_coverage': coverage, 'margin_px': margin}


def exercise_compare(page, context, api_base: str, output_dir, locale: str) -> dict:
    """Exercise both stages in all three modes; return concrete evidence or FAIL."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {'status': 'INCOMPLETE', 'locale': locale, 'stages': [], 'screenshots': [],
              'console_errors': [], 'page_errors': [], 'http_errors': []}
    on_response = lambda response: existing.record_response(report, response)
    on_console = lambda message: report['console_errors'].append(message.text) if message.type == 'error' else None
    on_error = lambda error: report['page_errors'].append(str(error))
    page.on('response', on_response)
    page.on('console', on_console)
    page.on('pageerror', on_error)
    try:
        assert locale in existing.LOCALES, locale
        page.wait_for_function('locale => document.querySelector(".design-shell")?.getAttribute("lang") === locale', arg=locale)
        fabric = existing.FABRICS[0]
        response = context.request.get(f'{api_base.rstrip("/")}/api/v1/fabric-plans/{fabric}?lang={"en" if locale == "en" else "zh"}', timeout=30000)
        existing.record_response(report, response)
        assert response.status == 200, f'fabric detail HTTP {response.status}'
        detail = response.json()
        report['source_checks'] = existing.check_detail(detail, fabric, locale)
        for stage in existing.STAGES:
            page.locator(f'#stage-{stage}').click()
            page.locator('[data-testid="fabric-compare"]').wait_for(state='visible', timeout=30000)
            page.locator('.shell-properties .panel-tabs button').first.click()
            parallel = page.locator('[data-testid="fabric-parallel-toggle"]')
            if parallel.get_attribute('aria-pressed') == 'true':
                parallel.click()
            properties = existing.assert_properties(page, fabric, detail, locale)
            stage_report = {'stage': stage, 'fabric_id': fabric, 'properties': properties, 'modes': []}
            report['stages'].append(stage_report)
            for mode in existing.MODES:
                button = page.locator(f'#shell-view-{mode.lower()}')
                button.click()
                assert button.get_attribute('aria-pressed') == 'true'
                viewport = page.locator(f'[data-testid="fabric-viewport-{fabric}"]')
                viewport.scroll_into_view_if_needed()
                rendering = existing.assert_main_viewport(page, fabric, mode, detail)
                if mode in ('2D', 'SPLIT'):
                    rendering['full_site_2d_fit'] = assert_site_2d_fit(viewport.locator('#canvas-viewport-2d'), detail['layers_projected'])
                if locale == 'en':
                    existing.assert_english_visible_text(page)
                shot = output_dir / f'{stage}-{locale}-{mode.lower()}-single-selected.png'
                assert not shot.exists(), f'refusing to overwrite {shot}'
                page.screenshot(path=str(shot), full_page=True)
                report['screenshots'].append(str(shot))
                stage_report['modes'].append({'mode': mode, 'rendering': rendering, 'layout': existing.check_layout(page), 'screenshot': str(shot)})
        assert not report['http_errors'], json.dumps(report['http_errors'])
        assert not report['console_errors'], json.dumps(report['console_errors'])
        assert not report['page_errors'], json.dumps(report['page_errors'])
        report['status'] = 'PASS'
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = str(error)
        try:
            shot = output_dir / f'compare-generate-{locale}-failure.png'
            if not shot.exists():
                page.screenshot(path=str(shot), full_page=True, timeout=10000)
                report['screenshots'].append(str(shot))
        except Exception as screenshot_error:
            report['failure_screenshot_error'] = str(screenshot_error)
    finally:
        page.remove_listener('response', on_response)
        page.remove_listener('console', on_console)
        page.remove_listener('pageerror', on_error)
    return report
