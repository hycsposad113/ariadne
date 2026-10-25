"""Receipt verified INT3 exports with a separate, explicit NET1 assessment."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from urban_design.fabric_syntax_segments import authored, build, lineage, load_verified, receipt


def waterfront_joins(full: dict, plan: dict) -> list[list[float]]:
    """Unique junction locations, from unsimplified surviving same-mode geometry."""
    roads = {str(r['id']): r for r in plan['roads']}
    waterfront = {key for key, r in roads.items() if r['properties'].get('role') == 'waterfront_path'}
    excluded = {key for key, r in roads.items() if r['properties'].get('role') in ('waterfront_path', 'waterfront_detour')}
    lines = [(authored(r['source_line_id'], roads), LineString(r['coordinates'])) for r in full['after']['segments']]
    waterfront_lines = [line for road, line in lines if road in waterfront]
    street_lines = [line for road, line in lines if road not in excluded]
    if not street_lines:
        return []
    tree = STRtree(street_lines)
    unlinks = [Point(c) for c in full['merge'].get('derived_unlinks', [])]
    joins = []
    for line in waterfront_lines:
        for index in tree.query(line, predicate='intersects'):
            intersection = line.intersection(street_lines[int(index)])
            # Shared linear overlaps do not establish a distinct street junction.
            points = [intersection] if intersection.geom_type == 'Point' else [g for g in getattr(intersection, 'geoms', []) if g.geom_type == 'Point']
            for point in points:
                if any(point.distance(u) <= .001 for u in unlinks):
                    continue
                if not any(point.distance(Point(c)) <= .001 for c in joins):
                    joins.append(list(point.coords[0]))
    return sorted(joins)


def assess(report: dict, joins: list[list[float]], added_road_ids: set[str] | None = None) -> dict:
    mode = report['mode']
    checks = []
    intents = {r['intent_en']: r for r in report['intents']}
    thresholds = {'pedestrian': [('primary_street', 80), ('waterfront_path', 50)], 'bicycle': [('primary_street', 70)]}
    for name, threshold in thresholds.get(mode, []):
        value = intents.get(name, {}).get('percentile')
        checks.append({'target': name, 'metric': 'length_weighted_nain_percentile', 'value': value, 'minimum': threshold, 'status': 'UNAVAILABLE' if value is None else 'PASS' if value >= threshold else 'FAIL'})
    if mode in ('pedestrian', 'bicycle'):
        for name in ('connection Keileweg', 'connection Dakpark'):
            intent = intents.get(name, {})
            unavailable = not intent or intent.get('status') == 'unavailable'
            ids = intent.get('direct_join_road_ids', [])
            if added_road_ids is not None:
                ids = [identifier for identifier in ids if identifier in added_road_ids]
            checks.append({'target': name, 'metric': 'direct_join_road_count', 'value': None if unavailable else len(ids), 'minimum': 1, 'direct_join_road_ids': ids, 'status': 'UNAVAILABLE' if unavailable else 'PASS' if ids else 'FAIL'})
        checks.append({'target': 'waterfront multiple joins', 'metric': 'unique_geometric_same_mode_junction_count', 'value': len(joins), 'minimum': 2, 'coordinates_rd_m': joins, 'status': 'PASS' if len(joins) >= 2 else 'FAIL'})
    return {'schema_version': 'net1-assessment-v1', 'fabric_id': report['fabric_id'], 'mode': mode, 'status': ('PASS' if all(c['status'] == 'PASS' for c in checks) else 'FAIL') if checks else 'DESCRIPTIVE_ONLY', 'hard_targets_pass': all(c['status'] == 'PASS' for c in checks) if checks else None, 'checks': checks, 'descriptive_intents': report['intents'], 'formal_result_eligible': False, 'method': 'NET1 project thresholds only; INT3 intent_assessment unchanged. Unavailable targets fail the hard gate, retain UNAVAILABLE, and are not measured zero. Waterfront junctions use unsimplified surviving same-mode actual point intersections with non-waterfront streets, excluding waterfront detours, linear overlaps and derived unlinks; unique coordinates counted once. Internal proposal junctions need no context connection receipt. Named target checks retain strict INT3 receipt support.'}


def export(source: Path, output: Path) -> dict:
    modes = ('pedestrian', 'bicycle', 'motor_vehicle')
    candidates = sorted(p for p in source.glob('*.json') if any(p.stem.endswith('-' + m) for m in modes))
    identities = {(p.stem.rsplit('-', 1)[0], p.stem.rsplit('-', 1)[1]) for p in candidates}
    fabrics = {f for f, _ in identities}
    if len(candidates) != 12 or len(fabrics) != 4 or identities != {(f, m) for f in fabrics for m in modes}:
        raise ValueError('BLOCKED: requires four fabrics by three modes, 12 compact files')
    segment_dir = source / 'segments'
    destinations = [segment_dir / (p.stem + '.geojson') for p in candidates]
    report_path = output / 'net1-assessment.json'
    table_path = output / 'net1-table-zh.md'
    if any(p.exists() or p.with_suffix('.receipt.json').exists() for p in destinations) or report_path.exists() or table_path.exists():
        raise ValueError('BLOCKED: round output already exists; no overwrite permitted')
    prepared = []
    for path in candidates:
        compact = json.loads(path.read_text())
        if compact.get('status') != 'COMPUTED':
            mode = next(m for m in modes if path.stem.endswith('-' + m))
            report = {'fabric_id': compact.get('fabric_id', path.stem.removesuffix('-' + mode)), 'mode': mode, 'intents': []}
            net1 = assess(report, [])
            net1['status'] = 'BLOCKED'
            net1['hard_targets_pass'] = False
            for check in net1['checks']:
                check.update(status='UNAVAILABLE', value=None)
            net1['error'] = compact.get('error', compact.get('reason', 'Syntax compact unavailable: ' + str(compact.get('status'))))
            prepared.append((path, None, report, net1))
            continue
        doc, report = build(path)
        full, plan, _ = lineage(json.loads(path.read_text()))
        net1 = assess(report, waterfront_joins(full, plan) if report['mode'] in ('pedestrian', 'bicycle') else [],
                      {r['id'] for r in plan.get('net1', {}).get('added_roads', [])})
        net1['direct_join_scope'] = 'NET1-added roads only, after the unchanged INT3 receipt/surviving-target/unlink checks'
        doc['net1_assessment'] = net1
        data = json.dumps(doc, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(data.encode()) >= 5_000_000:
            raise ValueError('BLOCKED: export exceeds 5 MB')
        prepared.append((path, data, report, net1))
    report_estimate = json.dumps({'reports': [{'source_compact': receipt(path), 'intent_assessment': report if data is not None else None, 'net1_assessment': net1} for path, data, report, net1 in prepared]}, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    # Reserve room for export receipts and round metadata before writing artifacts.
    if len(report_estimate.encode()) + 16_384 >= 5_000_000:
        raise ValueError('BLOCKED: report exceeds 5 MB preflight')
    segment_dir.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for path, data, report, net1 in prepared:
        if data is None:
            reports.append({'source_compact': receipt(path), 'export': None, 'error': net1['error'], 'intent_assessment': None, 'net1_assessment': net1})
            continue
        destination = segment_dir / (path.stem + '.geojson')
        with destination.open('x') as stream:
            stream.write(data)
        with destination.with_suffix('.receipt.json').open('x') as stream:
            json.dump({'export': receipt(destination), 'size_bytes': destination.stat().st_size}, stream, indent=2)
        load_verified(destination)
        reports.append({'source_compact': receipt(path), 'export': receipt(destination), 'intent_assessment': report, 'net1_assessment': net1})
    result = {'schema_version': 'net1-round-report-v1', 'source_directory': str(source.resolve()), 'reports': reports, 'formal_result_eligible': False}
    report_data = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(report_data.encode()) >= 5_000_000:
        raise ValueError('BLOCKED: report exceeds 5 MB')
    with report_path.open('x') as stream:
        stream.write(report_data)
    lines = ['# NET1 判定', '', 'INT3 描述性判定完整保留；NET1 另用明示門檻。無資料硬目標判定失敗，保留 UNAVAILABLE。汽車模式只報描述性百分位。沒有整體優勝方案或正式驗收。', '', '|方案|模式|目標|值|最低門檻|狀態|', '|---|---|---|---|---|---|']
    for record in reports:
        assessment = record['net1_assessment']
        for check in assessment['checks']:
            lines.append('|'+ '|'.join(str(v) for v in (assessment['fabric_id'], assessment['mode'], check['target'], check['value'], check['minimum'], check['status']))+'|')
        if assessment['status'] == 'BLOCKED' and not assessment['checks']:
            lines.append('|'+ '|'.join(str(v) for v in (assessment['fabric_id'], assessment['mode'], 'syntax unavailable', None, '—', 'BLOCKED'))+'|')
        if not assessment['checks']:
            for intent in assessment['descriptive_intents']:
                lines.append('|'+ '|'.join(str(v) for v in (assessment['fabric_id'], assessment['mode'], intent['intent_en'], intent['percentile'], '—', 'DESCRIPTIVE_ONLY'))+'|')
    with table_path.open('x') as stream:
        stream.write('\n'.join(lines)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='Report directory; defaults to syntax parent')
    args = parser.parse_args()
    result = export(args.source, args.output or args.source.parent)
    print(json.dumps({'report_count': len(result['reports']), 'output': str(args.output or args.source.parent)}))
