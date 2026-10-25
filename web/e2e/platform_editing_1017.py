"""Browser-only draft editing flow against the caller's disposable runtime.

Helper opens Refine and an existing accepted scenario. No fixtures, approvals,
or credentials are synthesized. Edits are dispatched only by real UI controls. Playwright sync API.
"""
from pathlib import Path
import json
import re
import math


def floor_preparation(editor):
    """Inspect persisted state; choose a <=4-floor add or remove to three first for face-extrusion headroom."""
    active = editor.get('active_buildings') or {}
    buildings = [active.get(item['building_id'], item) for item in editor.get('editable_buildings', [])]
    if not buildings:
        raise AssertionError('No editable building for a valid floor add')
    chosen = min(buildings, key=lambda item: len(item['floors']))
    return chosen['building_id'], max(0, len(chosen['floors']) - 3)


def assert_preview_matches(displayed, selected):
    assert len(displayed) >= 3, 'Local height/GFA dashboard missing'
    numbers = [float(re.search(r'[-+]?\d+(?:\.\d+)?', value.replace(',', '')).group()) for value in displayed[:3]]
    assert numbers[0] == selected['floor_count'], 'Floor count mismatch'
    assert math.isclose(numbers[1], selected['height_m'], abs_tol=.001), 'Height mismatch'
    assert math.isclose(numbers[2], selected['gfa_m2'], abs_tol=.001), 'GFA mismatch'
    return True


def assert_confirmed_measurements(endpoint, body, request, dashboard, displayed):
    assert dashboard['scenario_revision'] == body['scenario_revision'], 'Mutation/GET revision mismatch'
    if endpoint == '/edits':
        assert dashboard['selected_building'] == body['dashboard']['selected_building'], 'Mutation/GET measurement mismatch'
    else:
        assert body['scenario_revision'] > request['expected_scenario_revision'], 'Face scenario revision did not advance'
        assert body['face_revision'] > request['parent_revision'], 'Face revision did not advance'
        if request.get('operation') in ('SPLIT_LINE', 'SPLIT_CONTOUR'):
            assert body['geometry_hash'] == request['expected_geometry_hash'], 'Split changed building geometry'
            face_ids = {face['id'] for face in body.get('faces', [])}
            assert any(parent == request['face_id'] and len(children) >= 2 and all(child != parent and child in face_ids for child in children) for parent, children in body.get('lineage', [])), 'Split lineage children missing or unselectable'
        else:
            assert body['geometry_hash'] != request['expected_geometry_hash'], 'Face geometry did not change'
        assert not body.get('idempotent_replay'), 'Expected a newly executed face mutation'
    return assert_preview_matches(displayed, dashboard['selected_building'])


def exercise_editing(page, context, api_base, output_dir, locale='en'):
    """Return action receipts; context is caller metadata, not BrowserContext.

    Optional context keys: scenario_id and building_id. Existing accepted input
    opens as an unaccepted formal draft through the UI. API GETs inspect inputs.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result = {'locale': locale, 'actions': {}, 'limitations': [], 'context': context}
    zh = locale == 'zh-TW'

    def capture(name):
        path = output / f'editing-{locale}-{name}.png'
        page.screenshot(path=str(path), full_page=True)
        return str(path)

    def click_post(name, locator, endpoint, *, expect_invalid=False):
        if locator.count() != 1 or not locator.is_enabled():
            result['actions'][name] = {'status': 'UI_GAP', 'reason': 'Control absent, ambiguous or disabled', 'screenshot': capture(name)}
            return None
        confirmed = False
        try:
            with page.expect_response(lambda r: r.request.method == 'POST' and endpoint in r.url, timeout=20000) as pending:
                locator.click()
            response = pending.value
            body = response.json()
            confirmed = True
            receipt = {'status': 'UNPROVEN' if response.ok else 'FAIL', 'http_status': response.status, 'url': response.url, 'response': body, 'request': response.request.post_data_json}
            result['actions'][name] = receipt
            if response.ok and endpoint in ('/edits', '/editing/faces'):
                scenario_url = response.url.rsplit(endpoint, 1)[0]
                building = receipt['request']['building_id']
                fresh = page.request.get(scenario_url + '/edits/dashboard', params={'building_id': building})
                assert fresh.ok, f'Dashboard HTTP {fresh.status}'
                dashboard = fresh.json()
                if endpoint == '/edits':
                    assert dashboard['selected_building'] == body['dashboard']['selected_building'], 'Mutation/GET measurement mismatch'
                assert dashboard['scenario_revision'] == body['scenario_revision'], 'Mutation/GET revision mismatch'
                selected = dashboard['selected_building']
                server = page.get_by_role('region', name='後端草稿測量' if zh else 'Server draft measurements', exact=True)
                expected_gfa = selected['gfa_m2']
                if expected_gfa is None:
                    receipt['reason'] = 'Backend geometry invalid; GFA unavailable while local floor-polygon sum is a preview'
                    receipt['dashboard'] = dashboard
                    if expect_invalid:
                        assert dashboard['geometry_valid'] is False
                        assert dashboard['acceptance_eligible'] is False and dashboard['analysis_eligible'] is False
                        assert selected['height_m'] > 20, 'Overlimit branch did not exceed 20m'
                        assert any(finding['code'] == 'HEIGHT_ABOVE_UPPER_BOUND' for finding in body['validation']['findings'])
                        page.locator('.scenario-invalid').wait_for(state='visible')
                        page.locator('.scenario-failure').filter(has_text=re.compile('height|HEIGHT|高度', re.I)).wait_for(state='visible')
                        page.wait_for_function('arg => [...document.querySelectorAll("section")].find(e => e.getAttribute("aria-label") === arg)?.innerText.includes("'+('無法提供' if zh else 'Unavailable')+'")', arg='後端草稿測量' if zh else 'Server draft measurements')
                        preview = page.get_by_role('region', name='量體指標儀表板' if zh else 'Massing metrics dashboard', exact=True)
                        preview_text = preview.inner_text()
                        assert ('本機預覽' if zh else 'Local preview') in preview_text
                        receipt.update(status='PASS', ui_invalid=True, evidence_difference=receipt['reason'], local_preview_text=preview_text, server_text=server.inner_text())
                else:
                    page.wait_for_function('''arg => {
                      const e=[...document.querySelectorAll('section')].find(e=>e.getAttribute('aria-label')===arg.label);
                      return e?.querySelector('dd')?.textContent === String(arg.gfa)+' m²';
                    }''', arg={'label': '後端草稿測量' if zh else 'Server draft measurements', 'gfa': expected_gfa})
                    values = page.get_by_role('region', name='量體指標儀表板' if zh else 'Massing metrics dashboard', exact=True)
                    if not values.count():
                        values = page.locator('.scenario-dashboard').filter(has=page.locator('.scenario-dashboard-grid'))
                    displayed = values.locator('article').first.locator('dd').all_text_contents()
                    assert_confirmed_measurements(endpoint, body, receipt['request'], dashboard, displayed)
                    receipt.update(status='PASS', dashboard=dashboard, displayed=displayed, server_text=server.inner_text())
            receipt['screenshot'] = capture(name)
            return body
        except AssertionError as error:
            result['actions'].setdefault(name, {}).update(status='FAIL', reason=str(error), screenshot=capture(name))
            return None
        except Exception as error:
            result['actions'].setdefault(name, {}).update(status='FAIL' if confirmed else 'OUTCOME_UNKNOWN', reason=str(error), screenshot=capture(name))
            return None

    try:
        listing_response = page.request.get(f'{api_base}/api/v1/scenarios')
        listing = listing_response.json().get('scenarios', []) if listing_response.ok else []
        requested = (context or {}).get('scenario_id')
        candidates = [s for s in listing if s.get('scenario_id') == requested] if requested else [s for s in listing if s.get('provenance') == 'FORMAL_DRAFT' or (s.get('status') == 'accepted' and s.get('provenance') == 'APPROVED_INPUTS')]
        if not candidates:
            result['actions']['open_formal_draft'] = {'status': 'NEEDS_HUMAN', 'reason': 'No existing accepted input or formal draft; acceptance will not be synthesized'}
            (output / f'editing-{locale}-result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            return result
        chosen = candidates[0]
        page.locator('#stage-refine').click()
        page.locator('.scenario-card-open').first.wait_for(timeout=20000)
        # W6 scenarios now live in the collapsed "historical" section; open it so every card is clickable,
        # then select the card by its scenario id instead of relying on list order.
        history = page.get_by_test_id('scenario-catalog-historical')
        if history.count() and history.get_attribute('open') is None:
            history.locator(':scope > summary').click()
        if not any(s['scenario_id'] == chosen['scenario_id'] for s in listing):
            raise RuntimeError('Chosen scenario disappeared from inspected catalog')
        page.get_by_test_id(f"scenario-card-{chosen['scenario_id']}").locator('.scenario-card-open').click()
        page.get_by_role('button', name='套用位移' if zh else 'Apply move', exact=True).wait_for(timeout=20000)
        result['actions']['open_formal_draft'] = {'status': 'PASS', 'source_scenario_id': chosen['scenario_id'], 'screenshot': capture('opened')}
    except Exception as error:
        result['actions']['open_formal_draft'] = {'status': 'BLOCKED', 'reason': str(error), 'screenshot': capture('open-failed')}
        (output / f'editing-{locale}-result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        return result

    page.get_by_role('spinbutton', name='東西位移 dx（公尺）' if zh else 'Move dx (metres)', exact=True).fill('1')
    page.get_by_role('spinbutton', name='南北位移 dy（公尺）' if zh else 'Move dy (metres)', exact=True).fill('0')
    for key, en, tw in [('move', 'Apply move', '套用位移'), ('rotate', 'Rotate +15°', '旋轉 +15°')]:
        # The English fallback also handles untranslated product copy honestly.
        button = page.get_by_role('button', name=re.compile('^' + re.escape(tw if zh else en) + '$'))
        if not button.count() and zh:
            button = page.get_by_role('button', name=en, exact=True)
        click_post(key, button, '/edits')
        page.wait_for_timeout(300)
        receipt = result['actions'][key]
        receipt['ui_dashboard'] = page.locator('.scenario-dashboard').all_text_contents()
        receipt['verification'] = 'PASS requires mutation/GET revision and measurements plus displayed floor count, height and GFA equality'
        if receipt['status'] == 'OUTCOME_UNKNOWN':
            result['status'] = 'OUTCOME_UNKNOWN'
            (output / f'editing-{locale}-result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            return result

    source = result['actions'].get('move', {})
    if source.get('url'):
        scenario_url = source['url'].rsplit('/edits', 1)[0]
        current = page.request.get(scenario_url)
        assert current.ok, f'Detail HTTP {current.status}'
        building_id, removals = floor_preparation(current.json()['editor'])
        page.get_by_role('combobox', name='選取棟別' if zh else 'Select building', exact=True).select_option(building_id)
        for index in range(removals):
            click_post(f'floor_prepare_remove_{index}', page.get_by_role('button', name='移除頂層' if zh else 'Remove top floor', exact=True), '/edits')
            if result['actions'][f'floor_prepare_remove_{index}']['status'] != 'PASS':
                result['status'] = result['actions'][f'floor_prepare_remove_{index}']['status']
                (output / f'editing-{locale}-result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
                return result
        click_post('floor_extrusion', page.get_by_role('button', name='新增一層' if zh else 'Add one floor', exact=True), '/edits')
        source = result['actions'].get('floor_extrusion', source)
    if result['actions'].get('floor_extrusion', {}).get('status') != 'PASS':
        result['status'] = result['actions'].get('floor_extrusion', {}).get('status', 'INCOMPLETE')
        (output / f'editing-{locale}-result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    formal = page.get_by_role('region', name='Formal face editing', exact=True)
    source = result['actions'].get('floor_extrusion', {})
    if formal.count() and source.get('url'):
        scenario_url = source['url'].rsplit('/edits', 1)[0]
        building_id = source['request']['building_id']
        state_response = page.request.get(scenario_url+'/editing/faces', params={'building_id':building_id})
        faces = state_response.json().get('faces', []) if state_response.ok else []
        top = next((face for face in faces if face['kind']=='TOP'), None)
        if top:
            selected = formal.locator(f'button[data-face-id="{top["id"]}"]')
            selected.click()
            result['actions']['face_select']={'status':'PASS','face_id':top['id'],'screenshot':capture('face-select'),'method':'server semantic face list (not 3D ray picking)'}
            ring=top.get('geometry', {}).get('coordinates', [[]])[0]
            if ring:
                min_x,max_x=min(p[0] for p in ring),max(p[0] for p in ring)
                min_y,max_y=min(p[1] for p in ring),max(p[1] for p in ring)
                middle=(min_x+max_x)/2
                formal.get_by_role('combobox').select_option('SPLIT_LINE')
                formal.get_by_role('textbox').fill(f'{middle},{min_y-1}\n{middle},{max_y+1}')
                split=click_post('face_split', formal.get_by_role('button', name='套用正式分面' if zh else 'Apply formal face edit', exact=True), '/editing/faces')
                if result['actions']['face_split']['status']=='OUTCOME_UNKNOWN':
                    result['status']='OUTCOME_UNKNOWN'
                    (output/f'editing-{locale}-result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
                    return result
                if result['actions']['face_split']['status'] == 'PASS' and split and split.get('faces'):
                    children=[child for parent, children in split.get('lineage', []) if parent==top['id'] for child in children]
                    local=next((face for face in split['faces'] if face['id'] in children and face['kind']=='TOP'), None)
                    if local:
                        formal.locator(f'button[data-face-id="{local["id"]}"]').click()
                        formal.get_by_role('combobox').select_option('TOP_EXTRUDE')
                        click_post('local_extrusion', formal.get_by_role('button',name='套用正式分面' if zh else 'Apply formal face edit',exact=True), '/editing/faces')
                    else:
                        result['actions']['local_extrusion']={'status':'UI_GAP','reason':'Split response has no selectable TOP child with source lineage'}
            else:
                result['actions']['face_split']={'status':'UI_GAP','reason':'No server polygon coordinates for cut line'}
        else:
            result['actions']['face_select']={'status':'UI_GAP','reason':'No server TOP face exposed'}
        if result['actions'].get('local_extrusion',{}).get('status')=='OUTCOME_UNKNOWN':
            result['status']='OUTCOME_UNKNOWN'
            (output/f'editing-{locale}-result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
            return result
        # Fresh side selection after geometry changes; 1 positive step is 1 metre.
        state_response=page.request.get(scenario_url+'/editing/faces',params={'building_id':building_id})
        current_faces=state_response.json().get('faces',[]) if state_response.ok else []
        side=next((face for face in current_faces if face['kind']=='SIDE'),None)
        if side:
            formal.locator(f'button[data-face-id="{side["id"]}"]').click()
            formal.get_by_role('combobox').select_option('SIDE_PUSH')
            formal.get_by_role('spinbutton').fill('1')
            click_post('side_push_1m',formal.get_by_role('button',name='套用正式分面' if zh else 'Apply formal face edit',exact=True),'/editing/faces')
        else:
            result['actions']['side_push_1m']={'status':'UI_GAP','reason':'No server SIDE face exposed'}
    else:
        result['actions']['face_select']={'status':'UI_GAP','reason':'Formal face editor or selected draft context missing'}
    for action in ('face_split','local_extrusion','side_push_1m'):
        result['actions'].setdefault(action,{'status':'UNPROVEN','reason':'Preceding face prerequisite unavailable'})
    if any(a['status']=='OUTCOME_UNKNOWN' for a in result['actions'].values()):
        result['status']='OUTCOME_UNKNOWN'
        (output/f'editing-{locale}-result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
        return result
    page.locator('#shell-view-2d').click()
    nodes = page.locator('circle.scenario-road-node:not(.is-locked)[aria-disabled="false"]')
    road_target = None
    prior = result['actions'].get('move', {})
    if prior.get('url'):
        scenario_url = prior['url'].rsplit('/edits', 1)[0]
        current = page.request.get(scenario_url)
        if current.ok:
            graph = current.json().get('editor', {}).get('road_graph') or {}
            for moving in graph.get('nodes', []):
                locator = page.get_by_role('button', name=f"Road node {moving['node_id']} · draggable", exact=True)
                if not locator.count() or not locator.is_enabled():
                    continue
                incident = {e['end_node_id'] if e['start_node_id'] == moving['node_id'] else e['start_node_id'] for e in graph.get('edges', []) if moving['node_id'] in (e['start_node_id'], e['end_node_id'])}
                for target in graph.get('nodes', []):
                    if target['node_id'] == moving['node_id'] or target['node_id'] in incident:
                        continue
                    if any(target.get(k) != moving.get(k) for k in ('layer', 'bridge', 'tunnel')):
                        continue
                    target_locator = page.get_by_role('button', name=re.compile('^Road node '+re.escape(target['node_id'])+' · '))
                    if locator.bounding_box() and target_locator.count()==1 and target_locator.bounding_box():
                        road_target = (locator, target_locator, moving['node_id'], target['node_id'])
                        break
                if road_target:
                    break
    if road_target:
        node, target_node, moving_id, target_id = road_target
        node.scroll_into_view_if_needed()
        box, target_box = node.bounding_box(), target_node.bounding_box()
        x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
        tx, ty = target_box['x'] + target_box['width']/2, target_box['y'] + target_box['height']/2
        confirmed = False
        try:
            with page.expect_response(lambda r: r.request.method == 'POST' and '/road-nodes/' in r.url and '/move' in r.url, timeout=20000) as pending:
                page.mouse.move(x, y)
                page.mouse.down()
                page.mouse.move(tx, ty, steps=12)
                capture('road-drag-preview')
                page.mouse.up()
            response = pending.value
            body = response.json()
            confirmed = True
            receipt = {'status': 'UNPROVEN' if response.ok else 'FAIL', 'http_status': response.status, 'response': body, 'request': response.request.post_data_json, 'moving_node_id': moving_id, 'target_node_id': target_id}
            result['actions']['road_drag'] = receipt
            validation = body.get('validation', {})
            if response.ok and body.get('snap_kind') in ('ENDPOINT', 'NEAREST_POINT') and validation.get('status') in ('PASS', 'VALID'):
                page.wait_for_function("arg => document.body.innerText.includes(arg.hash) && document.body.innerText.includes(arg.validation)", arg={'hash':body['graph_hash_after'], 'validation':validation['status']})
                receipt['status']='PASS'
                result['actions']['road_snap_topology']={'status':'PASS','snap_kind':body['snap_kind'],'validation':validation,'graph_hash_after':body['graph_hash_after']}
            else:
                result['actions']['road_snap_topology']={'status':'UNPROVEN','snap_kind':body.get('snap_kind'),'validation':validation}
            receipt['screenshot']=capture('road-drag')
        except Exception as error:
            result['actions']['road_drag']={'status':'FAIL' if confirmed else 'OUTCOME_UNKNOWN','reason':str(error)}
    else:
        result['actions']['road_drag']={'status':'UI_GAP','reason':'No visible compatible nonadjacent road-node target; no arbitrary drag dispatched','screenshot':capture('road-gap')}
    result['limitations'].append('This flow exercises road drag using server snapping policy; candidate-panel selection is not independently exercised.')
    result['limitations'].append('Face mutations require fresh API revision/dashboard and screen GFA equality; Commander must separately inspect map/3D geometry.')
    # Separate negative branch, after all valid geometry-dependent operations.
    source = result['actions'].get('floor_extrusion', {})
    if source.get('url') and all(a['status'] == 'PASS' for a in result['actions'].values()):
        scenario_url = source['url'].rsplit('/edits', 1)[0]
        building_id = source['request']['building_id']
        for index in range(20):
            current = page.request.get(scenario_url + '/edits/dashboard', params={'building_id': building_id})
            assert current.ok
            measured = current.json()['selected_building']
            # Read persisted floor heights; do not assume a storey height or change the limit.
            detail = page.request.get(scenario_url).json()
            editor = detail['editor']
            active = editor.get('active_buildings') or {}
            building = active.get(building_id) or next(b for b in editor['editable_buildings'] if b['building_id'] == building_id)
            exceeds = measured['height_m'] + building['standard_floor_height_m'] > 20
            key = 'overlimit_height' if exceeds else f'overlimit_prepare_{index}'
            click_post(key, page.get_by_role('button', name='新增一層' if zh else 'Add one floor', exact=True), '/edits', expect_invalid=exceeds)
            if result['actions'][key]['status'] != 'PASS' or exceeds:
                break
        result['actions'].setdefault('overlimit_height', {'status': 'UNPROVEN', 'reason': 'Bounded preparation did not reach >20m'})
    else:
        result['actions']['overlimit_height'] = {'status': 'UNPROVEN', 'reason': 'Valid action prerequisites failed; no negative mutation dispatched'}
    result['status'] = 'OUTCOME_UNKNOWN' if any(a['status']=='OUTCOME_UNKNOWN' for a in result['actions'].values()) else ('INCOMPLETE' if any(a['status'] != 'PASS' for a in result['actions'].values()) else 'PASS')
    (output / f'editing-{locale}-result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    return result
