"""A blocked decision dispatch is a failed rehearsal, even without console errors."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('platform_walkthrough_1017', Path(__file__).resolve().parents[1] / 'web/e2e/platform_walkthrough_1017.py')
walkthrough = importlib.util.module_from_spec(spec)
spec.loader.exec_module(walkthrough)


def test_prevented_formal_decision_is_not_a_successful_walkthrough():
    assert walkthrough.flow_has_errors({'blocked_requests': [{'method': 'POST', 'path': '/api/v1/projects/p/decisions'}]})


def test_external_request_is_not_a_successful_walkthrough():
    assert walkthrough.flow_has_errors({'external_requests': ['https://example.invalid/']})


def test_empty_error_lists_are_clean():
    assert not walkthrough.flow_has_errors({'console_errors': [], 'page_errors': [], 'http_errors': []})


def _run_fake_browser(monkeypatch, tmp_path, *, fail=False, console_error=None, guarded_path=None):
    """Execute the real orchestration without launching a browser or making requests."""
    import sys
    from types import SimpleNamespace

    class Page:
        def on(self, event, callback):
            if event == 'console' and console_error:
                callback(SimpleNamespace(type='error', text=console_error))
        def goto(self, *args, **kwargs):
            if fail:
                raise RuntimeError('actual navigation failure')
            for path in (guarded_path,) if guarded_path else ('/ariadne-brand.png', '/ariadne-favicon.png'):
                request = SimpleNamespace(url='http://127.0.0.1:5983'+path, method='GET')
                context.guard(SimpleNamespace(request=request, abort=lambda: result['blocked'].append(path), continue_=lambda: None))
        def locator(self, *args):
            return SimpleNamespace(wait_for=lambda **kwargs: None)
        def screenshot(self, **kwargs):
            pass
    class Context:
        def add_init_script(self, *args):
            pass
        def route(self, pattern, guard):
            self.guard = guard
        def new_page(self):
            return Page()
        def close(self):
            pass
    context = Context()
    result = {'blocked': []}
    browser = SimpleNamespace(new_context=lambda **kwargs: context, close=lambda: None)
    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
        def __exit__(self, *args):
            pass
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(sync_playwright=Playwright))
    for name, fn in (('week7_real_override_dialog', 'exercise_override'), ('platform_editing_1017', 'exercise_editing'), ('platform_compare_1017', 'exercise_compare')):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace(**{fn: lambda *args: {'status': 'PASS'}}))
    monkeypatch.setattr(walkthrough, 'FLOWS', ('compare_generate',))
    report = {'flows': {f'compare_generate-{locale}': {'status': 'BLOCKED', 'reason': 'Browser not launched; no page/error checks performed'} for locale in ('zh-TW', 'en')}}
    walkthrough.run_browser(SimpleNamespace(browser='unused', headed=False), tmp_path, report, 'http://127.0.0.1:5983', 'http://127.0.0.1:8983')
    return report, result


def test_compare_pass_receipt_and_local_brand_assets_remain_pass(monkeypatch, tmp_path):
    report, requests = _run_fake_browser(monkeypatch, tmp_path)
    assert requests['blocked'] == []
    assert report['browser_launched'] is True
    for result in report['flows'].values():
        assert result['receipt']['status'] == 'PASS'
        assert result['status'] == 'PASS'
        assert 'Browser not launched' not in result.get('reason', '')


def test_executed_failure_reports_actual_reason(monkeypatch, tmp_path):
    report, _ = _run_fake_browser(monkeypatch, tmp_path, fail=True)
    for result in report['flows'].values():
        assert result['status'] == 'FAIL'
        assert result['reason'] == 'actual navigation failure'


def test_genuine_console_error_overrides_pass_with_browser_check_reason(monkeypatch, tmp_path):
    report, _ = _run_fake_browser(monkeypatch, tmp_path, console_error='real renderer failure')
    for result in report['flows'].values():
        assert result['status'] == 'FAIL'
        assert result['reason'] == 'Browser checks failed: console_errors'
        assert result['console_errors'] == ['real renderer failure']


def test_decision_request_guard_remains_active(monkeypatch, tmp_path):
    report, requests = _run_fake_browser(monkeypatch, tmp_path, guarded_path='/api/v1/projects/p/decisions')
    assert len(requests['blocked']) == 2
    for result in report['flows'].values():
        assert result['status'] == 'FAIL'
        assert result['reason'] == 'Browser checks failed: blocked_requests'


def test_each_owned_flow_gets_fresh_services_and_cleanup(monkeypatch, tmp_path):
    from types import SimpleNamespace
    seen = []
    class Child:
        pid, returncode = 123, 0
        def terminate(self): seen.append(('terminate',))
        def wait(self, timeout): seen.append(('wait',))
    class Handle:
        def close(self): seen.append(('close',))
    def start(args, output, children, handles, report):
        seen.append(('start', output.name))
        children.append(Child())
        handles.append(Handle())
        return 'ui', 'api'
    def browse(args, output, report, url, api, *, locales, flows):
        seen.append(('browse', locales[0], flows[0]))
    monkeypatch.setattr(walkthrough, 'services', start)
    monkeypatch.setattr(walkthrough, 'run_browser', browse)
    walkthrough.run_isolated_flows(SimpleNamespace(), tmp_path, {'flows': {}, 'cleanup': []})
    assert len([event for event in seen if event[0] == 'start']) == 6
    assert len({event[1] for event in seen if event[0] == 'start'}) == 6
    assert [event[0] for event in seen] == ['start', 'browse', 'terminate', 'wait', 'close'] * 6


def _editing_module():
    spec = importlib.util.spec_from_file_location('editing1017', Path(__file__).resolve().parents[1] / 'web/e2e/platform_editing_1017.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_floor_preparation_prefers_existing_low_building_and_uses_active_state():
    editing = _editing_module()
    buildings = [{'building_id': 'five', 'floors': [0]*5}, {'building_id': 'low', 'floors': [0]*3}]
    assert editing.floor_preparation({'editable_buildings': buildings, 'active_buildings': {}}) == ('low', 0)
    assert editing.floor_preparation({'editable_buildings': buildings[:1], 'active_buildings': {'five': {'building_id': 'five', 'floors': [0]*6}}}) == ('five', 3)


def test_preview_numbers_accept_formatted_ui_but_reject_divergent_gfa():
    import pytest
    editing = _editing_module()
    selected = {'floor_count': 4, 'height_m': 16, 'gfa_m2': 1234.56789}
    assert editing.assert_preview_matches(['4', '16.000m', '1,234.568m²'], selected)
    with pytest.raises(AssertionError, match='GFA'):
        editing.assert_preview_matches(['4', '16m', '999m²'], selected)



def test_isolated_flow_failure_still_stops_owned_children(monkeypatch, tmp_path):
    import pytest
    from types import SimpleNamespace
    events = []
    class Child:
        pid, returncode = 7, 0
        def terminate(self): events.append('terminate')
        def wait(self, timeout): events.append('wait')
    def start(args, output, children, handles, report):
        children.append(Child())
        raise RuntimeError('startup failed after API child')
    monkeypatch.setattr(walkthrough, 'services', start)
    with pytest.raises(RuntimeError, match='startup failed'):
        walkthrough.run_isolated_flows(SimpleNamespace(), tmp_path, {'cleanup': []})
    assert events == ['terminate', 'wait']


def test_database_backups_are_distinct_and_source_unchanged(tmp_path):
    import sqlite3
    import hashlib
    source = tmp_path / 'source.sqlite3'
    with sqlite3.connect(source) as connection:
        connection.execute('CREATE TABLE observations (value TEXT)')
        connection.execute("INSERT INTO observations VALUES ('source')")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for i in range(6):
        target = tmp_path / f'flow-{i}.sqlite3'
        walkthrough.backup_database(source, target)
        with sqlite3.connect(target) as connection:
            assert connection.execute('SELECT value FROM observations').fetchone()[0] == 'source'
            connection.execute("UPDATE observations SET value='changed disposable state'")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_face_measurements_require_new_revision_and_matching_screen():
    import pytest
    editing = _editing_module()
    body = {'scenario_revision': 8, 'face_revision': 3, 'geometry_hash': 'new'}
    request = {'expected_scenario_revision': 7, 'parent_revision': 2, 'expected_geometry_hash': 'old'}
    dashboard = {'scenario_revision': 8, 'selected_building': {'floor_count': 4, 'height_m': 14, 'gfa_m2': 1234}}
    editing.assert_confirmed_measurements('/editing/faces', body, request, dashboard, ['4', '14m', '1,234m²'])
    with pytest.raises(AssertionError, match='revision'):
        editing.assert_confirmed_measurements('/editing/faces', {**body, 'scenario_revision': 7}, request, dashboard, ['4', '14m', '1,234m²'])
    with pytest.raises(AssertionError, match='GFA'):
        editing.assert_confirmed_measurements('/editing/faces', body, request, dashboard, ['4', '14m', '9m²'])


def test_face_split_can_preserve_building_hash_but_must_record_children():
    import pytest
    editing = _editing_module()
    request = {'operation': 'SPLIT_LINE', 'face_id': 'top', 'expected_scenario_revision': 7, 'parent_revision': 2, 'expected_geometry_hash': 'same'}
    body = {'scenario_revision': 8, 'face_revision': 3, 'geometry_hash': 'same', 'lineage': [['top', ['child-a', 'child-b']]], 'faces': [{'id': 'child-a'}, {'id': 'child-b'}]}
    dashboard = {'scenario_revision': 8, 'selected_building': {'floor_count': 4, 'height_m': 14, 'gfa_m2': 1234}}
    editing.assert_confirmed_measurements('/editing/faces', body, request, dashboard, ['4', '14m', '1234m²'])
    with pytest.raises(AssertionError, match='lineage'):
        editing.assert_confirmed_measurements('/editing/faces', {**body, 'lineage': []}, request, dashboard, ['4', '14m', '1234m²'])
