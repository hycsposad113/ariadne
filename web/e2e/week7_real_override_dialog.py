#!/usr/bin/env python3
"""Open the real W7 HumanDecision dialog on a disposable runtime; never submit."""
from __future__ import annotations

import argparse
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


def exercise_override(page, scenario_id: str, screenshot: Path, locale='zh-TW') -> dict:
    """Record a pending override only, then stop at the empty credential field."""
    page.locator('#stage-compare').click()
    outer = page.locator('details.compare-week7')
    outer.locator(':scope > summary').click()
    actions = page.get_by_test_id('week7-actions')
    actions.locator(':scope > summary').click()
    scenario_label = 'W7 方案' if locale == 'zh-TW' else 'W7 scenario'
    select = page.get_by_label(scenario_label, exact=True)
    expect(select.locator(f'option[value="{scenario_id}"]')).to_have_count(1)
    select.select_option(scenario_id)
    switch = actions.get_by_role('button', name='切換方案' if locale == 'zh-TW' else 'Switch scenario', exact=True)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/switch')) as pending:
        switch.click()
    assert pending.value.ok, f'W7 switch HTTP {pending.value.status}'
    # Switching reloads the real action panel; reopen only if it closed.
    actions = page.get_by_test_id('week7-actions')
    expect(actions).to_be_visible()
    if actions.get_attribute('open') is None:
        actions.locator(':scope > summary').click()
    expect(actions.get_by_label(scenario_label, exact=True)).to_have_value(scenario_id)
    expect(actions.get_by_test_id('week7-op-inspect')).to_be_enabled()
    actions.get_by_label('理由／質疑' if locale == 'zh-TW' else 'Reason / challenge', exact=False).fill(
        'Isolated browser walkthrough: request human review of this proposed revision.')
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/operations/override')) as pending:
        actions.get_by_test_id('week7-op-override').click()
    response = pending.value
    assert response.request.post_data_json['target']['entity_id'] == scenario_id, 'Override target changed after scenario switch'
    assert response.ok, f'Override pending event HTTP {response.status}'
    assert response.json().get('status') == 'PENDING_FOUNDER_DECISION'
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text(scenario_id)
    expect(dialog.locator('input[type="password"]')).to_have_count(1)
    expect(dialog.locator('input[type="password"]')).to_be_empty()
    expect(dialog.get_by_test_id('d1-dialog-submit-btn')).to_be_visible()
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    if screenshot.exists():
        raise FileExistsError(screenshot)
    page.screenshot(path=str(screenshot), full_page=True)
    return {'status': 'PASS', 'stopped_at': 'HumanDecision dialog', 'decision_status': '需人類決策',
            'scenario_id': scenario_id, 'screenshot': str(screenshot), 'credential_entered': False,
            'decision_submitted': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--scenario-id', required=True)
    parser.add_argument('--screenshot', type=Path, required=True)
    parser.add_argument('--locale', choices=['en', 'zh-TW'], default='zh-TW')
    parser.add_argument('--browser', default=CHROME)
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser, headless=not args.headed,
                                             args=['--enable-unsafe-swiftshader'])
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.add_init_script(f'localStorage.setItem("urban-design-language", "{args.locale}")')
        # Fail closed if a future edit accidentally dispatches a formal decision.
        context.route('**/api/v1/projects/*/decisions', lambda route: route.abort())
        try:
            page = context.new_page()
            page.goto(args.url, wait_until='domcontentloaded')
            exercise_override(page, args.scenario_id, args.screenshot, args.locale)
            print('Captured HumanDecision dialog; no credential entered or decision submitted.')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
