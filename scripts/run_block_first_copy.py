"""J15 copy-only block-first run. SQLite source must be a /private/tmp backup."""
import argparse
import csv
import hashlib
import json
import subprocess
import time
from itertools import combinations
from pathlib import Path

from shapely.geometry import LineString, MultiPoint, mapping, shape
from shapely.ops import unary_union

from urban_design.approved_generation import _load_approved_inputs
from urban_design.far import FarSiteContext, resolve_far_denominator
from urban_design.generation import multimodal_network as net
from urban_design.generation.block_first import VERSION, build_structure, difference_metrics, generate_block_first
from urban_design.generation.context_massing import FAMILIES
from urban_design.generation.formal_adapter import retained_gfa_bounds
from urban_design.generation.formal_multimodal import checked_copy, load_j9b, load_sources, retained_roads, unlink_points, utc
from urban_design.generation.formal_pipeline import approved_parameters
from urban_design.generation.massing_revision import facade_segments
from urban_design.generation.network_massing_coupling import CouplingRules, downgrade_roads
from urban_design.store import ProjectStateStore


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


def run(database, network_root, output, *, motor_result_roots=()):
    database = checked_copy(database)
    root = Path(network_root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = utc()
    clock = time.perf_counter()
    archive = output / 'input-snapshot'
    source, inputs_receipt = receipt(root / 'inputs.json', archive)
    with ProjectStateStore(database, read_only=True) as store:
        ledger_before = list(store.connection.execute('select count(*),max(sequence) from ledger_events').fetchone())
        project = store.list_current('Project')[0].entity_id
        inputs = _load_approved_inputs(store, project, site_generation=True)
        constraint = next(c for c in inputs.constraint_set.constraints if c.name == 'far_upper_limit' and c.scope == 'whole_site')
        denominator, label = resolve_far_denominator(constraint, FarSiteContext(inputs.design_area, inputs.water_geometry))
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
        identity = family + '-j16'
        print(identity, '結構', flush=True)
        budget = 0.8 * denominator - bounds['upper_m2']
        built = build_structure(
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
        def analyze(roads, phase=''):
            after_syntax = {}
            for mode in ('pedestrian', 'bicycle', 'motor_vehicle'):
                syntax_roads = net.syntax_roads(roads, mode, rules)
                docs, _ = verified_extract(mode)
                if mode == 'motor_vehicle' and digest([r.model_dump() for r in syntax_roads]) == motor['road_input_sha256']:
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
            result = generate_block_first(
                family=family, site=inputs.design_area, water=inputs.water_geometry, retained=retained,
                entrances=entrances, fixed_roads=fixed, zones=manifest.zones, syntax_document=pedestrian,
                network_rules=rules, denominator=denominator, retained_gfa=bounds['upper_m2'],
                parameters=parameters, context_edges=context, external=external, structure=built,
            )
        except Exception as exc:
            failures.append(dict(id=identity, reason=str(exc)))
            print(identity, 'EXCEPTION', exc, flush=True)
            continue
        # J12c removes unnecessary motor surfaces only after geometric fire and
        # connectivity readback. Recompute all changed-road Syntax before S6.
        revised_roads, road_actions = downgrade_roads(
            built['roads'], [shape(f['geometry']) for f in result['features']], retained,
            entrances, coupling_external, rules, [shape(s['geometry']) for s in result['named_open_spaces']],
        )
        if digest([r.model_dump() for r in revised_roads]) != digest([r.model_dump() for r in built['roads']]):
            built['roads'] = revised_roads
            remaining_ids = {r.id for r in revised_roads}
            built['development'] = [d for d in built['development'] if d['road_id'] in remaining_ids]
            after_syntax = analyze(revised_roads)
            result = generate_block_first(
                family=family, site=inputs.design_area, water=inputs.water_geometry, retained=retained,
                entrances=entrances, fixed_roads=fixed, zones=manifest.zones,
                syntax_document=after_syntax['pedestrian'], network_rules=rules, denominator=denominator,
                retained_gfa=bounds['upper_m2'], parameters=parameters, context_edges=context,
                external=external, structure=built,
            )
        else:
            # Preserve the single calculated artifact, recording its exact file.
            for mode, document in after_syntax.items():
                document['artifact_phase'] = 'before-downgrade; roads unchanged'
        result['coupling']['road_actions'] = road_actions
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
        result['source_receipts'] = dict(inputs=inputs_receipt, motor=motor_receipt, J9b=diagnosis_receipt, Dakpark=dakpark_receipt, baseline=baseline_receipts)
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
        status='DRAFT' if len(results) == 4 and all(r['status'] == 'VALID' for r in results) and all(d['distinct'] for d in differences) and ledger_before == ledger_after else 'INCOMPLETE',
        version=VERSION, start_utc=started, end_utc=utc(), runtime_seconds=time.perf_counter() - clock,
        database=str(database), database_access='READ_ONLY_COPY', copy_ledger_before=ledger_before, copy_ledger_after=ledger_after,
        variant_count=len(results), valid_count=sum(r['status'] == 'VALID' for r in results),
        missing=failures, pairwise_differences=differences, source_receipts=dict(inputs=inputs_receipt, motor=motor_receipt),
        overall_winner=None,
        unfinished=['DRAFT cards require Founder review.', 'Dakpark noon screen is not full E1 sunlight verification.', 'Independent Claude review and Founder acceptance.'],
    )
    # No figure before all strategy difference gates have also passed.
    if report['status'] == 'DRAFT':
        for result in results:
            subprocess.run(['.venv/bin/python', 'scripts/render_block_first.py', '--input',
                            str(output / (result['id'] + '.json')), '--output', str(output)], check=True)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--database', type=Path, required=True)
    p.add_argument('--network-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--motor-result-root', type=Path, action='append', default=[])
    a = p.parse_args()
    r = run(a.database, a.network_root, a.output, motor_result_roots=a.motor_result_root)
    print(r['status'], r['valid_count'], flush=True)
    raise SystemExit(0 if r['status'] == 'DRAFT' else 2)
