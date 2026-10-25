"""J17：只在 SQLite backup 副本執行既有意圖書，不呼叫 AI。"""
import argparse
import csv
import hashlib
import json
import subprocess
import time
import textwrap
import sys
from itertools import combinations
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shapely.geometry import LineString, MultiPoint, mapping, shape
from shapely.ops import unary_union

from urban_design.approved_generation import _load_approved_inputs
from urban_design.far import FarSiteContext, resolve_far_denominator
from urban_design.generation import multimodal_network as net
from urban_design.generation.block_first import difference_metrics
from urban_design.generation.brief_driven import VERSION, build_brief_structure, generate_brief_driven, finalize_brief_metrics
from urban_design.generation.context_massing import FAMILIES
from urban_design.generation.formal_adapter import retained_gfa_bounds
from urban_design.generation.formal_multimodal import checked_copy, load_j9b, load_sources, retained_roads, unlink_points, utc
from urban_design.generation.formal_pipeline import approved_parameters
from urban_design.generation.massing_revision import facade_segments
from urban_design.generation.network_massing_coupling import CouplingRules, downgrade_roads
from urban_design.store import ProjectStateStore


BRIEFS_DIR = 'artifacts/s6-brief/briefs-r4b'


def receipt(path, archive=None):
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    result = dict(path=str(Path(path).resolve()), sha256='sha256:' + sha)
    if archive is not None:
        archive.mkdir(exist_ok=True)
        snapshot = archive / (Path(path).stem + '-' + sha[:12] + '.json')
        if not snapshot.exists():
            with snapshot.open('xb') as f:
                f.write(raw)
        elif snapshot.read_bytes() != raw:
            raise ValueError('immutable input snapshot collision')
        result['snapshot_path'] = str(snapshot)
    return json.loads(raw), result


def validate_motor_baseline(motor, expected):
    if motor.get('status') != 'COMPUTED' or any(motor.get(k) != v for k, v in expected.items()):
        raise ValueError('motor baseline input/implementation mismatch')


def compare_motor_using_verified_before(features, roads, site, unlinks, baseline, source_ref):
    from urban_design import scenario_syntax as ss
    parameters = ss.MergeParameters(snap_tolerance_m=0)
    expected = dict(
        mode='motor_vehicle', radius_m=ss.MODES['motor_vehicle'][1],
        site_sha256=ss.digest(mapping(site)), network_input_sha256=ss.digest(features),
        unlinks_sha256=ss.digest(unlinks), implementation_sha256=ss.IMPLEMENTATION_SHA256,
        parameters=parameters.model_dump(), engine='PST 3.3.1',
    )
    validate_motor_baseline(baseline, expected)
    if not source_ref.get('sha256') or not baseline.get('before', {}).get('segments'):
        raise ValueError('verified motor baseline before artifact required')
    started = time.perf_counter()
    merge = ss.merge_network(features, roads, site, 'motor_vehicle', parameters, unlinks)
    common = {k: v for k, v in baseline.items() if k not in ('before', 'after', 'diff', 'merge', 'runtime_seconds', 'before_seconds', 'after_seconds', 'reuse_status')}
    common.update(
        road_input_sha256=ss.digest([r.model_dump() for r in roads]),
        merge={k: v for k, v in merge.items() if k != 'features'},
        before_cache_provenance=source_ref,
        orchestration_method='j16-verified-motor-before-cache-v1',
    )
    if merge['status'] == 'BLOCKED':
        return {**common, 'status': 'BLOCKED', 'error': merge['reason'], 'before': None, 'after': None, 'diff': [], 'runtime_seconds': time.perf_counter() - started}
    before = baseline['before']['segments']
    buffer, radius = ss.MODES['motor_vehicle']
    after_unlinks = tuple(sorted(set(tuple(p) for p in unlinks) | set(merge['derived_unlinks'])))
    clock = time.perf_counter()
    after = before if merge['unchanged'] else ss._compute(merge['features'], ss.PSTAdapter(manifest_path=ss.DEFAULT_PST_MANIFEST), radius, after_unlinks, site)
    after_seconds = time.perf_counter() - clock
    breaks = {key: ss._breaks(before, key) for key in ('nain', 'nach')}
    threshold = breaks['nain'][3]
    for row in after:
        row['boundary_effect_risk'] = row['distance_to_site_m'] > buffer - radius
    return {
        **common, 'status': 'COMPUTED',
        'reuse_status': 'VERIFIED_BEFORE_AND_UNCHANGED_AFTER' if merge['unchanged'] else 'VERIFIED_BEFORE_FRESH_AFTER',
        'before': {'segments': before, 'metrics': ss._metrics(before, threshold)},
        'after': {'segments': after, 'metrics': ss._metrics(after, threshold)},
        'diff': ss.segment_diff(before, after), 'legend_breaks': breaks,
        'before_seconds': 0, 'after_seconds': after_seconds, 'runtime_seconds': time.perf_counter() - started,
    }


def matching_motor_cache(roots, identity, expected, archive):
    for root in roots:
        root = Path(root)
        path = root / (identity + '-motor_vehicle-syntax.json')
        if not path.is_file() or not (root / (identity + '.json')).is_file():
            continue
        document, ref = receipt(path, archive)
        try:
            validate_motor_baseline(document, expected)
        except ValueError:
            continue
        if not document.get('before') or not document.get('after'):
            continue
        return {**document, 'reuse_status': 'HASH_VERIFIED_COMPLETE_SCENARIO_MOTOR_CACHE', 'cache_provenance': ref}
    return None



def matching_syntax_cache(roots, identity, mode, expected, archive):
    """只重用輸入及計算實作雜湊完全相同的實測檔，保留新舊檔案來源。"""
    for root in roots:
        path = Path(root) / (identity + '-before-downgrade-' + mode + '-syntax.json')
        if not path.is_file(): continue
        document, ref = receipt(path, archive)
        try: validate_motor_baseline(document, expected)
        except ValueError: continue
        if not document.get('before', {}).get('segments') or not document.get('after', {}).get('segments'): continue
        return {**document, 'reuse_status': 'J17_HASH_VERIFIED_IDENTICAL_INPUT_CACHE', 'cache_provenance': ref}
    return None


def measured_summary(row):
    from urban_design.generation.network_massing_coupling import connected_components
    roads = [net.NetworkRoad.model_validate(r) for r in row['roads']]
    actual_gfa = sum(shape(f['geometry']).area for b in row['buildings'] for f in b['floors'])
    average = sum(b['floor_count'] for b in row['buildings']) / len(row['buildings']) if row['buildings'] else None
    return dict(
        id=row['id'], family=row['family'], status=row['status'],
        metrics=row['metrics'], checks=row['checks'], failure_reasons=row['failure_reasons'],
        readback_new_gfa_m2=actual_gfa,
        readback_far=(actual_gfa+row['metrics']['retained_gfa_upper_m2'])/row['metrics']['far_denominator_m2'],
        average_floor_count=average, building_count=len(row['buildings']),
        parks=row['structure']['meta'].get('brief_parks', []),
        frontage=row.get('brief_frontage', []), allocation=row.get('brief_allocation'),
        landmarks=row.get('brief_landmarks', []),
        components={mode:len(connected_components(roads,mode)[2]) for mode in ('pedestrian','bicycle','motor_vehicle')},
        network_hard_checks=row['network_hard_checks'],
        construction_failures=row.get('construction_failures', []),
    )


def run(database, network_root, output, *, motor_result_roots=(), structure_only=False, syntax_result_roots=(), placer='j12b', structure_root=None):
    database = checked_copy(database)
    facts_path = Path('artifacts/s6-brief/facts/site-facts.json')
    facts = json.loads(facts_path.read_text())
    briefs = {family: json.loads(Path(BRIEFS_DIR, family + '.json').read_text()) for family in FAMILIES}
    root = Path(network_root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = utc()
    clock = time.perf_counter()
    archive = output / 'input-snapshot'
    source, inputs_receipt = receipt(root / 'inputs.json', archive)
    frozen_facts, facts_receipt = receipt(facts_path, archive)
    if frozen_facts != facts: raise ValueError('site facts changed during input capture')
    brief_receipts = {}
    for family in FAMILIES:
        frozen_brief, ref = receipt(Path(BRIEFS_DIR, family + '.json'), archive)
        if frozen_brief != briefs[family]: raise ValueError('brief changed during input capture')
        brief_receipts[family] = ref
    with ProjectStateStore(database, read_only=True) as store:
        ledger_before = list(store.connection.execute('select count(*),max(sequence) from ledger_events').fetchone())
        project = store.list_current('Project')[0].entity_id
        inputs = _load_approved_inputs(store, project, site_generation=True)
        constraint = next(c for c in inputs.constraint_set.constraints if c.name == 'far_upper_limit' and c.scope == 'whole_site')
        denominator, label = resolve_far_denominator(constraint, FarSiteContext(inputs.design_area, inputs.water_geometry))
        if abs(denominator - 183591.3) > 0.1:
            raise ValueError('J17 核對分母與基地土地面積不一致')
        source_denominator = denominator
        denominator = 183591.3
        label = str(label) + '; J17 Founder 指定核對分母 183591.3 m²（來源未四捨五入值 ' + str(source_denominator) + '）'
        parameters = approved_parameters(inputs)
        manifest = type('Manifest', (), source['frozen_context']['context'])()
        bounds = retained_gfa_bounds(manifest)
        if bounds['status'] == 'UNAVAILABLE':
            raise ValueError('retained GFA UNKNOWN')
        from urban_design.generation_context import resolve_readiness
        ready = resolve_readiness(store, project)
        if ready.status != 'READY' or ready.context_hash != source['frozen_context']['context_hash']:
            raise ValueError('copy/source frozen approval context mismatch')
    rules = net.NetworkRules.model_validate(source['rules'])
    entrances = [net.Entrance.model_validate(e) for e in source['entrances']]
    external, baseline_contexts, baseline_receipts, source_features, mode_lookup = load_sources(inputs.design_area)
    motor, motor_receipt = receipt(root / 'motor-vehicle-syntax.json', archive)
    from urban_design.scenario_syntax import IMPLEMENTATION_SHA256, MergeParameters, compare_syntax, digest, verified_extract
    fixed = retained_roads(source_features, [net.Disposition.model_validate(d) for d in source['dispositions']], mode_lookup, rules)
    motor_inputs = net.syntax_roads(fixed, 'motor_vehicle', rules)
    motor_docs, _ = verified_extract('motor_vehicle')
    validate_motor_baseline(motor, dict(
        mode='motor_vehicle', road_input_sha256=digest([r.model_dump() for r in motor_inputs]),
        network_input_sha256=digest(external['motor_vehicle']), site_sha256=digest(mapping(inputs.design_area)),
        unlinks_sha256=digest(unlink_points(motor_docs['unlinks'])), implementation_sha256=IMPLEMENTATION_SHA256,
        parameters=MergeParameters(snap_tolerance_m=0).model_dump(), engine='PST 3.3.1',
    ))
    retained = {d.feature_id: g for d, g, _ in inputs.retained_buildings}
    context = []
    diagnosis_receipt = source.get('J9b', {})
    if diagnosis_receipt.get('path'):
        raw, doc = load_j9b(diagnosis_receipt['path'], project, next(r['id'] for r in source['frozen_context']['context']['refs'] if r.get('entity_type') == 'StudyArea'))
        if 'sha256:' + hashlib.sha256(raw).hexdigest() != diagnosis_receipt['sha256']:
            raise ValueError('J9b hash drift')
        transit_side = doc['closest_transit_side']
        coords = [e['coordinates'] for e in doc['entrances'] if e['side'] == transit_side]
        if coords:
            context.append(dict(kind='transit', geometry=mapping(MultiPoint(coords)), source_ref=diagnosis_receipt['sha256'] + '; J9b closest-side entrance proxy, not stop geometry'))
    dakpark_doc, dakpark_receipt = receipt(Path('data/context/dakpark-osm-epsg28992.geojson'), archive)
    if dakpark_doc.get('crs', {}).get('properties', {}).get('name') != 'EPSG:28992':
        raise ValueError('Dakpark CRS required')
    if len(dakpark_doc['features']) != 1:
        raise ValueError('exactly one source-backed Dakpark park polygon required')
    park_feature = dakpark_doc['features'][0]
    p = park_feature['properties']
    if p.get('leisure') != 'park' or p.get('name') != 'Dakpark' or not p.get('source_ref') or p.get('elevation_difference_m') != 10 or not p.get('elevation_provenance', '').startswith('ASSUMED_PORTFOLIO_P21'):
        raise ValueError('Dakpark source/elevation provenance mismatch')
    context.append(dict(kind='dakpark', geometry=park_feature['geometry'], source_ref=p['source_ref'] + '; ' + dakpark_receipt['sha256'] + '; ODbL 1.0; ASSUMED_PORTFOLIO_P21', elevation_difference_m=10))
    results = []
    failures = []
    coupling_external = {**external, '_site': inputs.design_area, '_water': inputs.water_geometry}
    for family in FAMILIES:
        identity = family + '-j17'
        brief = briefs[family]
        print(identity, '結構', flush=True)
        budget = 0.8 * denominator - bounds['upper_m2']
        built = build_brief_structure(
            brief=brief, facts=facts,
            family=family, site=inputs.design_area, water=inputs.water_geometry, retained=retained,
            entrances=entrances, fixed_roads=fixed, network_rules=rules, zones=manifest.zones,
            gfa_budget=budget, dakpark=shape(park_feature['geometry']),
        )
        baseline_rows=baseline_contexts['pedestrian']['segments']
        distribution=sorted(r['nain'] for r in baseline_rows if r['distance_to_site_m']<=3000)
        baseline_lines=[LineString(r['coordinates']) for r in baseline_rows]
        from shapely.strtree import STRtree
        baseline_tree=STRtree(baseline_lines)
        for block in built['blocks']:
            index=int(baseline_tree.nearest(block['geometry']))
            value=baseline_rows[index]['nain']
            block['baseline_percentile']=100*sum(v<=value for v in distribution)/len(distribution)
            block['priority_source_ref']=baseline_receipts['pedestrian']['syntax_context']
        print(identity, '軸線', len(built['axes']), '街廓', len(built['blocks']), '道路', len(built['roads']), flush=True)
        (output / (identity + '-structure.json')).write_text(json.dumps({
            'family': family, 'axis_count': len(built['axes']), 'block_count': len(built['blocks']),
            'road_count': len(built['roads']), 'failures': built['failures'],
            'meta': built['meta'],
            'axes': [{**a, 'geometry': mapping(a['geometry']), 'length_m': a['geometry'].length} for a in built['axes']],
            'blocks': [{k: v for k, v in b.items() if k != 'profile'} | {'geometry': mapping(b['geometry']), 'area_m2': b['geometry'].area} for b in built['blocks']],
        }, ensure_ascii=False, indent=2, allow_nan=False))
        if structure_only:
            failures.append(dict(id=identity, failures=built['failures'], blocks=len(built['blocks']), roads=len(built['roads']), parks=built['meta'].get('brief_parks')))
            continue
        def analyze(roads, phase=''):
            after_syntax = {}
            for mode in ('pedestrian', 'bicycle', 'motor_vehicle'):
                syntax_roads = net.syntax_roads(roads, mode, rules)
                docs, _ = verified_extract(mode)
                cache_expected = dict(mode=mode, radius_m=__import__('urban_design.scenario_syntax', fromlist=['MODES']).MODES[mode][1],
                    road_input_sha256=digest([r.model_dump() for r in syntax_roads]),
                    network_input_sha256=digest(external[mode]), site_sha256=digest(mapping(inputs.design_area)),
                    unlinks_sha256=digest(unlink_points(docs['unlinks'])), implementation_sha256=IMPLEMENTATION_SHA256,
                    parameters=MergeParameters(snap_tolerance_m=0).model_dump(), engine='PST 3.3.1')
                cached = matching_syntax_cache(syntax_result_roots, identity, mode, cache_expected, archive)
                if cached is not None:
                    after_doc = cached
                elif mode == 'motor_vehicle' and digest([r.model_dump() for r in syntax_roads]) == motor['road_input_sha256']:
                    after_doc = {**motor, 'reuse_status': 'HASH_VERIFIED_RUN13_PUBLIC_MOTOR_UNCHANGED'}
                elif mode == 'motor_vehicle':
                    expected = dict(
                        mode=mode, radius_m=10000, road_input_sha256=digest([r.model_dump() for r in syntax_roads]),
                        network_input_sha256=digest(external[mode]), site_sha256=digest(mapping(inputs.design_area)),
                        unlinks_sha256=digest(unlink_points(docs['unlinks'])), implementation_sha256=IMPLEMENTATION_SHA256,
                        parameters=MergeParameters(snap_tolerance_m=0).model_dump(), engine='PST 3.3.1',
                    )
                    after_doc = matching_motor_cache(motor_result_roots, identity, expected, archive)
                    if after_doc is None:
                        after_doc = compare_motor_using_verified_before(external[mode], syntax_roads, inputs.design_area, unlink_points(docs['unlinks']), motor, motor_receipt)
                else:
                    after_doc = compare_syntax(external[mode], syntax_roads, inputs.design_area, mode, parameters=MergeParameters(snap_tolerance_m=0), unlinks=unlink_points(docs['unlinks']))
                after_syntax[mode] = after_doc
                (output / (identity + phase + '-' + mode + '-syntax.json')).write_text(json.dumps(after_doc, ensure_ascii=False, indent=2, allow_nan=False))
                print(identity, mode, after_doc.get('status'), after_doc.get('reuse_status'), flush=True)
            return after_syntax

        after_syntax = analyze(built['roads'], '-before-downgrade')
        pedestrian = after_syntax['pedestrian']
        if pedestrian.get('status') != 'COMPUTED':
            failures.append(dict(id=identity, reason=pedestrian.get('error', 'pedestrian Syntax not computed')))
            continue
        try:
            result = generate_brief_driven(
                brief=brief, facts=facts,
                family=family, site=inputs.design_area, water=inputs.water_geometry, retained=retained,
                entrances=entrances, fixed_roads=fixed, zones=manifest.zones, syntax_document=pedestrian,
                network_rules=rules, denominator=denominator, retained_gfa=bounds['upper_m2'],
                parameters=parameters, context_edges=context, external=external, structure=built,
                placer=placer,
            )
        except Exception as exc:
            failures.append(dict(id=identity, reason=str(exc)))
            print(identity, 'EXCEPTION', exc, flush=True)
            continue
        result.setdefault('coupling', {})['road_actions'] = built.get('road_actions', [])
        pedestrian = after_syntax['pedestrian']
        roads = [net.NetworkRoad.model_validate(r) for r in result['roads']]
        result['checks']['syntax_after_computed'] = all(d['status'] == 'COMPUTED' for d in after_syntax.values())
        if not result['checks']['syntax_after_computed']:
            result['failure_reasons'].append('syntax_after_computed')
            result['status'] = 'INVALID'
        for mode, before_doc in (('pedestrian', pedestrian), ('bicycle', after_syntax['bicycle']), ('motor_vehicle', motor)):
            after_doc = after_syntax[mode]
            bm = before_doc.get('before', {}).get('metrics', {}) if mode != 'motor_vehicle' else motor['before']['metrics']
            am = after_doc['after']['metrics'] if after_doc.get('after') else {}
            result['coupling']['syntax_comparison'][mode] = dict(
                before=bm, after=am,
                delta={k: am[k] - v for k, v in bm.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and isinstance(am.get(k), (int, float))},
                after_document_sha256=digest(after_doc), after_road_input_sha256=after_doc.get('road_input_sha256'),
                status=after_doc['status'],
                motor_service_policy='Service-only excluded under unchanged J11 DRAFT rule' if mode == 'motor_vehicle' else None,
            )
        result['id'] = identity
        result['far_denominator'] = label
        result['source_receipts'] = dict(facts=facts_receipt, brief=brief_receipts[family], inputs=inputs_receipt, motor=motor_receipt, J9b=diagnosis_receipt, Dakpark=dakpark_receipt, baseline=baseline_receipts)
        result['utc'] = utc()
        result['database'] = str(database)
        site_features = [
            dict(type='Feature', geometry=mapping(inputs.design_area), properties=dict(role='site_area')),
            dict(type='Feature', geometry=mapping(inputs.water_geometry), properties=dict(role='water')),
        ]
        retained_features = [dict(type='Feature', id=k, geometry=mapping(g), properties=dict(role='retained')) for k, g in retained.items()]
        entrance_features = [dict(type='Feature', geometry=mapping(shape({'type': 'Point', 'coordinates': e.coordinates})), properties=dict(role='entrance', entry_id=e.id, modes=e.modes)) for e in entrances]
        road_features = [dict(type='Feature', geometry=mapping(LineString(r.coordinates)), properties=dict(role='road', road_id=r.id, **{k: v for k, v in r.model_dump().items() if k not in ('id', 'coordinates')})) for r in roads]
        park_features = [dict(type='Feature', geometry=s['geometry'], properties=dict(role='named_park', name_zh=s['name_zh'], area_m2=s['area_m2'])) for s in result.get('named_open_spaces', [])]
        result['geometry'] = dict(type='FeatureCollection', features=site_features + retained_features + entrance_features + road_features + park_features + result['features'])
        result['failure_reasons'] = [k for k, v in result['checks'].items() if not v] + [k for k, v in result['network_hard_checks']['checks'].items() if not v] + result.get('construction_failures', [])
        if not result['checks'].get('syntax_after_computed', False):
            result['failure_reasons'].append('syntax_after_computed')
        result['status'] = 'VALID' if not result['failure_reasons'] else 'INVALID'
        (output / (identity + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=str))
        (output / (identity + '-summary.json')).write_text(json.dumps(measured_summary(result), ensure_ascii=False, indent=2, allow_nan=False, default=str))
        with (output / (identity + '-scale.csv')).open('w') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['建築', '類型', '高度公尺', '層數', '底面積平方公尺', '樓地板平方公尺', '翼深公尺', '中庭淨寬公尺', '合院外框短邊公尺'])
            for b in result['buildings']:
                writer.writerow([b['building_id'], b['type_id'], b['height_m'], b['floor_count'], b['footprint_area_m2'], b['new_gfa_m2'], b['scale']['wing_depth_m'], b['scale'].get('courtyard_width_m'), b['scale'].get('outer_short_m')])
        print(identity, result['status'], {k: result['metrics'].get(k) for k in ('far', 'coverage', 'streetwall_continuity_ratio', 'largest_park_m2', 'park_count', 'narrow_remnant_area_m2')}, result['failure_reasons'], flush=True)
        results.append(result)
    differences = [dict(a=a['id'], b=b['id'], **difference_metrics(a, b)) for a, b in combinations(results, 2) if a['buildings'] and b['buildings']]
    with ProjectStateStore(database, read_only=True) as store:
        ledger_after = list(store.connection.execute('select count(*),max(sequence) from ledger_events').fetchone())
    report = dict(
        status='DRAFT' if len(results) == 4 and all(r['status'] == 'VALID' for r in results) and len(differences) == 6 and all(d['distinct'] for d in differences) and ledger_before == ledger_after else 'INCOMPLETE',
        version=VERSION, start_utc=started, end_utc=utc(), runtime_seconds=time.perf_counter() - clock,
        database=str(database), database_access='READ_ONLY_COPY', copy_ledger_before=ledger_before, copy_ledger_after=ledger_after,
        variant_count=len(results), valid_count=sum(r['status'] == 'VALID' for r in results),
        missing=failures, pairwise_differences=differences, source_receipts=dict(facts=facts_receipt, briefs=brief_receipts, inputs=inputs_receipt, motor=motor_receipt),
        overall_winner=None,
        unfinished=['探索草案仍須 Founder 審查。', 'Dakpark 正午篩檢不能取代完整日照驗證。', 'Claude 跨供應商獨立審查與 Founder 接受。'],
    )
    report['drawing_results'] = render_in_existing_environment(results, output)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report


def render_in_existing_environment(results, output):
    from urban_design.generation.brief_driven import brief_drawing_guard
    receipts, eligible = [], []
    for row in results:
        try: brief_drawing_guard(row)
        except ValueError as exc:
            receipts.append(dict(id=row['id'],status='拒絕出圖',reason=str(exc)))
        else: eligible.append(row)
    if not eligible: return receipts
    # Matplotlib 已存在於這個本機環境；不安裝或修改專案依賴。
    executable = Path('/Users/jackhsieh/.pyenv/versions/3.12.13/bin/python3')
    if not executable.is_file(): raise RuntimeError('既有本機繪圖環境不存在；未安裝或切換環境')
    import os
    environment = dict(os.environ, MPLCONFIGDIR='/private/tmp/j17-mpl-cache', PYTHONPATH='src')
    snippet = "import json,sys; from pathlib import Path; sys.path.insert(0,str(Path.cwd())); from scripts.run_brief_driven_copy import render_eligible; output=Path(sys.argv[1]); rows=[json.loads((output/(identity+'.json')).read_text()) for identity in sys.argv[2:]]; receipts=render_eligible(rows,output); (output/'drawing-receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2))"
    process = subprocess.run([str(executable), '-c', snippet, str(output), *[row['id'] for row in results]], env=environment)
    if process.returncode: raise RuntimeError('既有本機繪圖環境執行失敗，exit='+str(process.returncode))
    return json.loads((output/'drawing-receipts.json').read_text())


CHECK_ZH = {
    'scale': '建築尺度', 'height': '高度', 'far_range': '總容積率範圍',
    'far_upper': '容積率上限', 'quality_far_minimum': '容積率下限',
    'brief_typologies': '段落類型一致性', 'brief_parks': '公園面積與完整性',
    'brief_landmarks': '地標位置與高度', 'brief_gfa_by_strip': '各帶樓地板預算',
    'brief_frontage': '指定街牆連續度', 'bicycle_connected': '自行車連通',
    'pedestrian_connected': '步行連通', 'motor_connected': '汽車連通',
    'motor_entrance_connected': '汽車入口接通', 'entrance_connectivity': '入口接通',
    'all_zones': '分區覆蓋', 'four_types': '建築類型數',
    'residential_mixed_average_floors': '住宅與混合平均層數',
    'syntax_after_computed': '三運具軸線量測', 'height_variation': '高度變化',
}


def failure_zh(key):
    labels = {'brief_strip_gfa':'各帶樓地板預算不足或超出', 'brief_park_targets':'指定公共空間面積或完整性', 'development_bilateral_streetwall':'指定雙側街牆連續度', 'defining_edge':'指定單側街牆連續度', 'named_park_count':'具名公共空間數量', 'largest_park':'最大公園面積', 'remnant_area':'狹窄殘餘土地面積', 'unmerged_sub600_land_fragment':'尚未合併的小於六百平方公尺土地', 'sub600_fragment_crosses_authored_segment_requires_review':'碎片合併跨越意圖書段界，須審查'}
    if key.startswith('development_street_no_same_strip_park_free_offset:'): return '尚未找到同帶且避開公園的完整服務街路線'
    if key.startswith('park_'): return '指定公共空間面積或單一多邊形'
    return labels.get(key, CHECK_ZH.get(key, '其他檢查未通過'))


def readback_run(parent, output):
    """保留母件，以新紀錄讀回量測；不重新生成幾何或運算路網。"""
    started=utc(); clock=time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    parent_report, parent_ref=receipt(parent/'report.json')
    rows=[]; links=[]
    for family in FAMILIES:
        old, ref=receipt(parent/(family+'-j17.json'))
        brief, brief_ref=receipt(Path(BRIEFS_DIR)/(family+'.json'))
        if brief_ref['sha256'] != old['source_receipts']['brief']['sha256']: raise ValueError('意圖書母件雜湊不一致')
        row=finalize_brief_metrics(old, brief)
        invariant=['geometry','roads','features','buildings','open_space','network_hard_checks']
        before={k:hashlib.sha256(json.dumps(old[k],sort_keys=True).encode()).hexdigest() for k in invariant}
        after={k:hashlib.sha256(json.dumps(row[k],sort_keys=True).encode()).hexdigest() for k in invariant}
        if before!=after: raise ValueError('讀回修正改動了幾何或路網')
        row['metric_readback_parent']=ref; row['metric_readback_utc']=utc()
        (output/(row['id']+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2,allow_nan=False))
        (output/(row['id']+'-summary.json')).write_text(json.dumps(measured_summary(row),ensure_ascii=False,indent=2,allow_nan=False))
        links.append(dict(id=row['id'],parent=ref,unchanged_sha256=before)); rows.append(row)
    differences=[dict(a=a['id'],b=b['id'],**difference_metrics(a,b)) for a,b in combinations(rows,2)]
    report=dict(parent_report,version=VERSION,status='INCOMPLETE',valid_count=sum(r['status']=='VALID' for r in rows),parent_report=parent_ref,execution_kind='幾何與路網母件讀回修正，未重新生成或運算 Syntax',start_utc=started,end_utc=utc(),runtime_seconds=time.perf_counter()-clock,pairwise_differences=differences,readback_invariants=links)
    report['drawing_results']=render_in_existing_environment(rows,output)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    return report


def render_eligible(results, output):
    """出圖只接受重新量測的尺度與 FAR，其他失败仍列示。"""
    from urban_design.generation.brief_driven import brief_drawing_guard
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Polygon, Patch
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from shapely.ops import triangulate
    for font in ('/System/Library/Fonts/STHeiti Medium.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc'):
        if Path(font).is_file():
            font_manager.fontManager.addfont(font)
            matplotlib.rcParams['font.family'] = font_manager.FontProperties(fname=font).get_name()
            break
    matplotlib.rcParams['axes.unicode_minus'] = False
    names = dict(radial='向心型', axial='軸線型', grid='網格型', green_service='綠廊服務型')
    eligible, receipts = [], []
    from matplotlib.lines import Line2D

    def area(ax, geom, color, edgecolor='#777777', hatch=None):
        polygons = [geom] if geom.geom_type == 'Polygon' else list(getattr(geom, 'geoms', []))
        for polygon in polygons:
            if polygon.geom_type != 'Polygon':
                continue
            ax.add_patch(Polygon(
                list(polygon.exterior.coords),
                facecolor=color,
                edgecolor=edgecolor,
                linewidth=0.3,
                hatch=hatch,
            ))
            for ring in polygon.interiors:
                ax.add_patch(Polygon(
                    list(ring.coords),
                    facecolor='white',
                    edgecolor=edgecolor,
                    linewidth=0.3,
                ))

    def panel(ax, row, fixed_bounds=None, show_legend=True):
        site_feat = next(f for f in row['geometry']['features'] if f['properties']['role'] == 'site_area')
        site_geom = shape(site_feat['geometry'])
        s_minx, s_miny, s_maxx, s_maxy = site_geom.bounds

        # 先繪製基礎面與未配置土地
        for feature in row['geometry']['features']:
            geom, props = shape(feature['geometry']), feature['properties']
            role = props['role']
            if role in ('site_area', 'water', 'retained'):
                area(ax, geom, {'site_area': '#f5f1e8', 'water': '#b9d8e5', 'retained': '#777777'}[role])

        if 'unallocated_open_geometry' in row and row['unallocated_open_geometry']:
            unalloc = shape(row['unallocated_open_geometry'])
            if not unalloc.is_empty:
                area(ax, unalloc, color='#f0f0f0', edgecolor='#888888', hatch='///')

        # 繪製公園（綠色）與廣場（淺綠）
        for space in row.get('named_open_spaces', []):
            s_geom = shape(space['geometry'])
            is_park = space.get('type') == 'park' or space.get('is_park', True)
            p_color = '#5da852' if is_park else '#bfe3b4'
            area(ax, s_geom, p_color, edgecolor='#444444')
            p = s_geom.representative_point()
            ax.text(p.x, p.y, space['name_zh'], fontsize=5, ha='center', weight='bold')

        # 繪製道路
        for feature in row['geometry']['features']:
            geom, props = shape(feature['geometry']), feature['properties']
            if props['role'] == 'road':
                xy = list(geom.coords)
                ax.plot([p[0] for p in xy], [p[1] for p in xy], color='#486675', linewidth=0.45)

        # 繪製新建建築與標示樓層數
        for feature in row['geometry']['features']:
            geom, props = shape(feature['geometry']), feature['properties']
            if props['role'] == 'new_building':
                area(ax, geom, '#d3a66e', edgecolor='#555555')
                fl_cnt = props.get('floor_count') or len(props.get('floors', []))
                ax.text(
                    geom.centroid.x, geom.centroid.y,
                    f'{fl_cnt}F',
                    fontsize=5.5, ha='center', va='center',
                    color='#111111', weight='bold',
                )

        if fixed_bounds:
            ax.set_xlim(fixed_bounds[0], fixed_bounds[1])
            ax.set_ylim(fixed_bounds[2], fixed_bounds[3])
        else:
            ax.set_xlim(s_minx - 100, s_maxx + 100)
            ax.set_ylim(s_miny - 100, s_maxy + 100)

        ax.set_aspect('equal')
        ax.ticklabel_format(useOffset=False, style='plain')
        ax.set_title(names[row['family']] + f"｜總容積率 {row['metrics']['far']:.3f}", fontsize=10, weight='bold')
        ax.set_xlabel('東向座標（公尺）', fontsize=8)
        ax.set_ylabel('北向座標（公尺）', fontsize=8)

        # 圖例與比例尺
        if show_legend:
            legend_elements = [
                Patch(facecolor='#d3a66e', edgecolor='#555555', label='新建建築'),
                Patch(facecolor='#777777', edgecolor='#555555', label='保留建築'),
                Patch(facecolor='#5da852', edgecolor='#444444', label='公園'),
                Patch(facecolor='#bfe3b4', edgecolor='#444444', label='廣場'),
                Patch(facecolor='#f0f0f0', edgecolor='#888888', hatch='///', label='未配置土地'),
                Patch(facecolor='#b9d8e5', edgecolor='#777777', label='水體'),
                Line2D([0], [0], color='#486675', lw=1.5, label='道路'),
            ]
            ax.legend(handles=legend_elements, loc='upper right', fontsize=6.5, framealpha=0.92)

            sb_x = s_minx - 70
            sb_y = s_miny - 70
            ax.plot([sb_x, sb_x + 200], [sb_y, sb_y], color='black', lw=2.5)
            ax.text(sb_x + 100, sb_y + 12, '200 m', fontsize=6.5, ha='center', va='bottom', weight='bold')

    for row in results:
        try:
            brief_drawing_guard(row)
        except ValueError as exc:
            receipts.append(dict(id=row['id'], status='拒絕出圖', reason=str(exc)))
            continue
        eligible.append(row)
        failures = '未通過：' + '、'.join(dict.fromkeys(failure_zh(k) for k in row['failure_reasons'])) if row['failure_reasons'] else '本案檢查通過；仍須獨立審查及人工接受'
        fig, ax = plt.subplots(figsize=(12, 9))
        panel(ax, row, show_legend=True)
        fig.text(0.03, 0.01, '\n'.join(textwrap.wrap(failures, width=80)), fontsize=7)
        fig.tight_layout(rect=(0, 0.08, 1, 1))
        fig.savefig(output / (row['id'] + '-plan-zh.png'), dpi=160)
        plt.close(fig)

        fig = plt.figure(figsize=(12, 9))
        ax = fig.add_subplot(111, projection='3d')
        vertices = []
        origin = shape(next(f['geometry'] for f in row['geometry']['features'] if f['properties']['role'] == 'site_area')).centroid
        for feature in row['features']:
            base = 0
            for floor in feature['properties']['floors']:
                plate = shape(floor['geometry'])
                top = base + floor['floor_height_m']
                for ring in [plate.exterior, *plate.interiors]:
                    for a, b in zip(ring.coords, list(ring.coords)[1:]):
                        vertices.append([(a[0] - origin.x, a[1] - origin.y, base), (b[0] - origin.x, b[1] - origin.y, base), (b[0] - origin.x, b[1] - origin.y, top), (a[0] - origin.x, a[1] - origin.y, top)])
                for triangle in triangulate(plate):
                    if plate.covers(triangle):
                        vertices.append([(x - origin.x, y - origin.y, top) for x, y in list(triangle.exterior.coords)[:-1]])
                base = top
        ax.add_collection3d(Poly3DCollection(vertices, facecolors='#d3a66e', edgecolors='#796040', linewidths=0.2))
        points = [p for polygon in vertices for p in polygon]
        if points:
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            ax.set_xlim(min(xs), max(xs))
            ax.set_ylim(min(ys), max(ys))
            ax.set_zlim(0, 20)
            ax.set_box_aspect((max(xs) - min(xs), max(ys) - min(ys), 80))
        ax.view_init(elev=38, azim=-60)
        ax.set_title(names[row['family']] + '｜量體軸測｜高度顯示比例四倍｜探索草案')
        ax.set_xlabel('東西（公尺）')
        ax.set_ylabel('南北（公尺）')
        ax.set_zlabel('高度（公尺）')
        fig.text(0.03, 0.01, '\n'.join(textwrap.wrap(failures, width=80)), fontsize=7)
        fig.savefig(output / (row['id'] + '-axonometric-zh.png'), dpi=160)
        plt.close(fig)
        receipts.append(dict(id=row['id'], status='已出圖'))

    # 2x2 四格同比例尺
    fig, axs = plt.subplots(2, 2, figsize=(16, 12))
    common_bounds = None
    if eligible:
        first_site = shape(next(f['geometry'] for f in eligible[0]['geometry']['features'] if f['properties']['role'] == 'site_area'))
        bminx, bminy, bmaxx, bmaxy = first_site.bounds
        common_bounds = (bminx - 100, bmaxx + 100, bminy - 100, bmaxy + 100)

    for ax, family in zip(axs.flat, FAMILIES):
        row = next((r for r in eligible if r['family'] == family), None)
        if row:
            panel(ax, row, fixed_bounds=common_bounds, show_legend=True)
            ax.text(0.01, -0.27, '\n'.join(textwrap.wrap('未通過：' + '、'.join(dict.fromkeys(failure_zh(k) for k in row['failure_reasons'])), width=40)), transform=ax.transAxes, fontsize=7)
        else:
            ax.text(0.5, 0.5, names[family] + '\n尺度或總容積率不合格，未出圖', ha='center', transform=ax.transAxes)
            ax.axis('off')
    if eligible:
        fig.suptitle('J17 意圖書驅動量體｜四案比較｜探索草案', fontsize=14, weight='bold')
        fig.subplots_adjust(hspace=0.7, bottom=0.18)
        fig.savefig(output / 'comparison-2x2-zh.png', dpi=160)
    plt.close(fig)
    return receipts



if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--database', type=Path)
    p.add_argument('--network-root', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--motor-result-root', type=Path, action='append', default=[])
    p.add_argument('--syntax-result-root', type=Path, action='append', default=[], help='只重用雜湊完全相符的既有 Syntax 結果')
    p.add_argument('--briefs-dir', default='artifacts/s6-brief/briefs-r4b', help='設計意圖書目錄（Commander 2026-10-10）')
    p.add_argument('--placer', choices=['j12b', 'frontage'], default='j12b', help='量體配置演算法')
    p.add_argument('--structure-root', type=Path, help='結構檔案來源目錄')
    p.add_argument('--structure-only', action='store_true', help='僅輸出結構診斷，不宣告方案通過')
    p.add_argument('--readback-run', type=Path, help='只讀母件並建立新的量測讀回紀錄')
    a = p.parse_args()
    BRIEFS_DIR = a.briefs_dir
    if not a.readback_run and (not a.database or not a.network_root): p.error('生成需要 database 與 network-root')
    r = readback_run(a.readback_run, a.output) if a.readback_run else run(a.database, a.network_root, a.output, motor_result_roots=a.motor_result_root, structure_only=a.structure_only, syntax_result_roots=a.syntax_result_root, placer=a.placer, structure_root=a.structure_root)
    print(r['status'], r['valid_count'], flush=True)
    raise SystemExit(0 if r['status'] == 'DRAFT' else 2)
