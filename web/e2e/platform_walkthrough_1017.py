#!/usr/bin/env python3
"""W8 isolated bilingual walkthrough. No downloads, Live AI or human decisions.

Default: backup source SQLite read-only, launch API 8983/Vite 5983 with empty
Vite envDir and separate cache, run Chromium, then terminate only own children.
Each language/flow gets a fresh source backup and API/Vite process pair.
External --url runtimes fail closed because clean database reset is unverified. Exit 0 only when all
flows and browser error checks pass; blocked/unproven are never success.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/w8/rehearsal/platform-walkthrough-1017'
SOURCE = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')
PROJECT = 'rotterdam-m4h-pilot-project'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
FLOWS = ('override', 'editing', 'compare_generate')


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def wait_ready(url, process):
    deadline = time.monotonic()+45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Child exited {process.returncode}; see service log')
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(.25)
    raise TimeoutError(url)


def available(port, timeout_s=30.0):
    """Wait for our own just-stopped child to release the port; fail if still busy."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', port))
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def backup_database(source_path, target_path):
    with sqlite3.connect(source_path.resolve().as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(target_path) as target:
            source.backup(target)


def services(args, output, children, handles, report):
    for port in (8983, 5983):
        available(port)
    runtime = Path(tempfile.mkdtemp(prefix='platform-1017-', dir='/private/tmp'))
    database = runtime/'state.sqlite3'
    backup_database(args.source_database, database)
    report['isolation'] = {'source': str(args.source_database), 'database': str(database),
                           'runtime': str(runtime), 'source_open_mode': 'ro'}
    api = [str(ROOT/'.venv/bin/python'), 'scripts/run_workspace_server.py', '--host', '127.0.0.1', '--port', '8983',
           '--database', str(database), '--decision-key-path', str(runtime/'unavailable-decision-key'),
           '--e2-job-database', str(runtime/'jobs.sqlite3'), '--e2-artifact-root', str(runtime/'e2'), '--scenario-artifact-root', str(runtime/'scenario-artifacts'),
           '--morphology-preview-root', str(Path.home()/'.local/share/urban-design-data/dictionary-generator/run-01'),
           '--morphology-preview-manifest-sha256', '14b2378ca16f79b84ce8fd60fbe6aa81ff11e7cccdec875034be5740e6b37452',
           '--syntax-context-root', str(Path.home()/'.local/share/urban-design-data/syntax-context/run-20261001T105231Z'),
           '--syntax-context-manifest-sha256', 'a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1']
    # A config outside the repository prevents .env and shared node_modules cache access.
    config = runtime/'vite.mjs'
    vite = (ROOT/'web/node_modules/vite/dist/node/index.js').as_posix()
    react = (ROOT/'web/node_modules/@vitejs/plugin-react/dist/index.js').as_posix()
    config.write_text(f'import {{defineConfig}} from {json.dumps(vite)};\nimport react from {json.dumps(react)};\nexport default defineConfig({{root:{json.dumps(str(ROOT/"web"))},envDir:{json.dumps(str(runtime))},cacheDir:{json.dumps(str(runtime/"vite-cache"))},plugins:[react()]}});\n')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT/'src'), VITE_API_BASE='http://127.0.0.1:8983', ARIADNE_LIVE='0', PROJECT_AI_AUTHORIZED='0')
    commands = [(api, 'api.log', 'http://127.0.0.1:8983/health'),
                (['node', str(ROOT/'web/node_modules/vite/bin/vite.js'), '--config', str(config), '--configLoader', 'runner', '--host', '127.0.0.1', '--port', '5983', '--strictPort'], 'web.log', 'http://127.0.0.1:5983')]
    for command, log, url in commands:
        handle = (output/log).open('w'); handles.append(handle)
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
        children.append(child)
        report.setdefault('service_commands', []).append(command)
        wait_ready(url, child)
    return 'http://127.0.0.1:5983', 'http://127.0.0.1:8983'


def flow_has_errors(result):
    return any(result.get(key) for key in ('console_errors', 'page_errors', 'http_errors', 'blocked_requests', 'external_requests'))


def run_browser(args, output, report, url, api, *, locales=('zh-TW', 'en'), flows=None):
    from playwright.sync_api import sync_playwright
    from week7_real_override_dialog import exercise_override
    from platform_editing_1017 import exercise_editing
    from platform_compare_1017 import exercise_compare
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.browser, headless=not args.headed, args=['--enable-unsafe-swiftshader'])
        report['browser_launched'] = True
        report['request_policy_note'] = 'Local GET /ariadne-brand.png and /ariadne-favicon.png are allowed; console errors are not filtered. Decision requests, AI/live writes (non-GET) and external requests are blocked; read-only Ariadne GETs are allowed.'
        try:
            for locale in locales:
                for flow in FLOWS if flows is None else flows:
                    key = f'{flow}-{locale}'
                    result = report['flows'][key]
                    result.update(status='INCOMPLETE', reason='Flow started; checks not completed')
                    context = browser.new_context(viewport={'width':1440, 'height':1000})
                    context.add_init_script('localStorage.setItem("urban-design-language", '+json.dumps(locale)+')')
                    def guard(route):
                        request = route.request
                        path = urlsplit(request.url).path
                        local_static_image = (request.method == 'GET' and path in ('/ariadne-brand.png', '/ariadne-favicon.png')
                                              and urlsplit(request.url).hostname in ('127.0.0.1', 'localhost'))
                        # Read-only Ariadne history/status GETs never dispatch a model; anything that could
                        # (POST to /ariadne/*, /live) and every decision request stay blocked.
                        ai_write = request.method != 'GET' and ('/ariadne' in path or '/live' in path)
                        if not local_static_image and (path.endswith('/decisions') or ai_write):
                            result.setdefault('blocked_requests', []).append({'method':request.method, 'path':path})
                            route.abort()
                        elif urlsplit(request.url).hostname not in ('127.0.0.1', 'localhost'):
                            result.setdefault('external_requests', []).append(request.url)
                            route.abort()
                        else:
                            route.continue_()
                    context.route('**/*', guard)
                    page = context.new_page()
                    result.update(console_errors=[], page_errors=[], http_errors=[], screenshots=[])
                    page.on('console', lambda m: result['console_errors'].append(m.text) if m.type=='error' else None)
                    page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
                    page.on('response', lambda r: result['http_errors'].append({'url':r.url,'status':r.status}) if r.status>=400 else None)
                    directory = output/key; directory.mkdir()
                    try:
                        page.goto(url, wait_until='domcontentloaded')
                        page.locator('.design-shell').wait_for(state='visible')
                        if flow=='override':
                            site = get_json(api+f'/api/v1/projects/{PROJECT}/site-context')
                            workspace = site['current_workspace']['workspace_id']
                            scenarios = get_json(api+f'/api/v1/week7/workspaces/{workspace}/scenarios')
                            scenario = next((s['entity_id'] for s in scenarios if s['status'].lower()=='proposed'), None)
                            if not scenario:
                                result.update(status='需人類決策', reason='No existing proposed scenario; no decision synthesized')
                            else:
                                result['receipt'] = exercise_override(page, scenario, directory/'dialog.png', locale)
                                result['status'] = result['receipt']['status']
                                result['screenshots'].append(str(directory/'dialog.png'))
                        elif flow=='editing':
                            receipt = exercise_editing(page, {}, api, directory, locale)
                            result['receipt'] = receipt
                            statuses = [r['status'] for r in receipt.get('actions', {}).values()]
                            result['status'] = receipt.get('status', 'INCOMPLETE')
                            if result['status']=='PASS' and not (statuses and all(s=='PASS' for s in statuses)):
                                result['status']='INCOMPLETE'
                        else:
                            result['receipt'] = exercise_compare(page, context, api, directory, locale)
                            result['status'] = result['receipt']['status']
                        if flow_has_errors(result):
                            result['status']='FAIL'
                            categories = [name for name in ('console_errors', 'page_errors', 'http_errors', 'blocked_requests', 'external_requests') if result.get(name)]
                            result['reason'] = 'Browser checks failed: ' + ', '.join(categories)
                        elif result['status'] == 'PASS':
                            result.pop('reason', None)
                        elif result.get('reason') == 'Flow started; checks not completed':
                            receipt = result.get('receipt', {})
                            result['reason'] = receipt.get('reason') or receipt.get('error') or f"Flow receipt status: {result['status']}"
                    except Exception as error:
                        result.update(status='FAIL', error=str(error), reason=str(error))
                        shot=directory/'failure.png' if 'directory' in locals() else output/(key+'-failure.png')
                        try:
                            page.screenshot(path=str(shot)); result['screenshots'].append(str(shot))
                        except Exception as e:
                            result['screenshot_error']=str(e)
                    finally:
                        context.close()
        finally:
            browser.close()


def stop_children(children, handles, report):
    for child in reversed(children):
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        report['cleanup'].append({'pid': child.pid, 'returncode': child.returncode, 'action': 'terminated own child'})
    for handle in handles:
        handle.close()


def run_isolated_flows(args, output, report):
    """A new read-only source backup and own API process for every language/flow."""
    report['flow_isolation'] = {}
    for locale in ('zh-TW', 'en'):
        for flow in FLOWS:
            key = f'{flow}-{locale}'
            directory = output / ('runtime-' + key)
            directory.mkdir()
            children, handles = [], []
            service_report = {}
            try:
                report['flow_isolation'][key] = service_report
                url, api = services(args, directory, children, handles, service_report)
                run_browser(args, output, report, url, api, locales=(locale,), flows=(flow,))
            finally:
                stop_children(children, handles, report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Already running isolated UI; requires --api-base')
    parser.add_argument('--api-base')
    parser.add_argument('--source-database', type=Path, default=SOURCE)
    parser.add_argument('--browser', default=CHROME)
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=OUT/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')))
    args=parser.parse_args()
    if bool(args.url)!=bool(args.api_base): parser.error('--url and --api-base must be provided together')
    if args.url and (args.url.rstrip('/') != 'http://127.0.0.1:5983' or args.api_base.rstrip('/') != 'http://127.0.0.1:8983'):
        parser.error('External runtime must use isolated loopback ports 5983/8983')
    output=args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=False)
    report={'status':'INCOMPLETE','started_at':datetime.now(timezone.utc).isoformat(), 'browser_launched':False,
            'flows':{f'{f}-{l}':{'status':'BLOCKED','reason':'Flow not started; no page/error checks performed','screenshots':[]} for l in ('zh-TW','en') for f in FLOWS},'cleanup':[]}
    children=[]; handles=[]
    try:
        if args.url:
            raise RuntimeError('Clean database per language/flow cannot be verified for --url; use managed disposable services')
        run_isolated_flows(args, output, report)
        report['status']='PASS' if all(r['status']=='PASS' for r in report['flows'].values()) else 'INCOMPLETE'
    except Exception as error:
        report['error']=str(error)
        report['status']='BLOCKED'
    finally:
        stop_children(children, handles, report)
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        (output/'browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'report':str(output/'browser-report.json')},ensure_ascii=False))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    sys.exit(main())
