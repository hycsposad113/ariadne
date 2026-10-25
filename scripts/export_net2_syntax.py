"""Receipt verified INT3 exports with a separate, explicit NET2 assessment."""
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


from urban_design.fabric_net2_assessment import assess as assess_net2

def export(source: Path, output: Path, water: dict | None = None) -> dict:
    if not any(part in ("round-1", "round-2", "round-3", "round-3-weld", "round-4", "round-5", "round-6", "round-7") for part in source.parts):
        raise ValueError("BLOCKED: NET2 exports limited to round-1 through round-5")
    modes = ('pedestrian', 'bicycle', 'motor_vehicle')
    candidates = sorted(p for p in source.glob('*.json') if any(p.stem.endswith('-' + m) for m in modes))
    if not candidates:
        raise ValueError('BLOCKED: no completed compact files found')
    if len(candidates) != 12:
        print(f'SKIP: partial syntax round: {len(candidates)}/12 compact files present; missing files skipped.', file=sys.stderr)
    segment_dir = output / 'segments'
    destinations = [segment_dir / (p.stem + '.geojson') for p in candidates]
    report_path = output / 'net2-assessment.json'
    table_path = output / 'net2-table-zh.md'
    if any(p.exists() or p.with_suffix('.receipt.json').exists() for p in destinations) or report_path.exists() or table_path.exists():
        raise ValueError('BLOCKED: round output already exists; no overwrite permitted')
    prepared = []
    skipped_sources = []
    for path in candidates:
        compact = json.loads(path.read_text())
        if compact.get('status') != 'COMPUTED':
            mode = next(m for m in modes if path.stem.endswith('-' + m))
            report = {'fabric_id': compact.get('fabric_id', path.stem.removesuffix('-' + mode)), 'mode': mode, 'intents': []}
            net2 = {'schema_version':'net2-assessment-v1','fabric_id':report['fabric_id'],'mode':mode,'baselines':{},'checks':[],'descriptive_intents':[],'formal_result_eligible':False}
            net2['status'] = 'UNAVAILABLE'
            net2['hard_targets_pass'] = False
            for check in net2['checks']:
                check.update(status='UNAVAILABLE', value=None)
            net2['error'] = compact.get('error', compact.get('reason', 'Syntax compact unavailable: ' + str(compact.get('status'))))
            prepared.append((path, None, report, net2))
            continue
        required = [compact['complete_intermediate'], compact['retained_road_receipts'],
                    compact['source_receipts']['plan'],
                    compact['source_receipts']['extract']['manifest']['outputs']['network']]
        missing = sorted({record['path'] for record in required if not Path(record['path']).is_file()})
        if missing:
            skipped_sources.append({'source_compact': receipt(path), 'missing_paths': missing})
            print(f'SKIP: {path.name}: missing referenced files: {missing}', file=sys.stderr)
            continue
        doc, report = build(path)
        full, plan, network = lineage(compact)
        net2 = assess_net2(full, plan, network, report, waterfront_joins(full, plan) if report['mode'] in ('pedestrian', 'bicycle') else [], water=water)
        net2['direct_join_scope'] = 'All INT3 new proposal roads, after unchanged receipt/surviving-target/unlink checks'
        doc['net2_assessment'] = net2
        doc['metadata']['source_receipts'].update(net2_assessor=receipt(Path(__file__).resolve().parents[1] / 'src/urban_design/fabric_net2_assessment.py'), net2_exporter=receipt(Path(__file__)))
        data = json.dumps(doc, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(data.encode()) >= 5_000_000:
            raise ValueError('BLOCKED: export exceeds 5 MB')
        prepared.append((path, data, report, net2))
    report_estimate = json.dumps({'reports': [{'source_compact': receipt(path), 'intent_assessment': report if data is not None else None, 'net2_assessment': net2} for path, data, report, net2 in prepared]}, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    # Reserve room for export receipts and round metadata before writing artifacts.
    if len(report_estimate.encode()) + 16_384 >= 5_000_000:
        raise ValueError('BLOCKED: report exceeds 5 MB preflight')
    segment_dir.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for path, data, report, net2 in prepared:
        if data is None:
            reports.append({'source_compact': receipt(path), 'export': None, 'error': net2['error'], 'intent_assessment': None, 'net2_assessment': net2})
            continue
        destination = segment_dir / (path.stem + '.geojson')
        with destination.open('x') as stream:
            stream.write(data)
        with destination.with_suffix('.receipt.json').open('x') as stream:
            json.dump({'export': receipt(destination), 'size_bytes': destination.stat().st_size}, stream, indent=2)
        load_verified(destination)
        reports.append({'source_compact': receipt(path), 'export': receipt(destination), 'intent_assessment': report, 'net2_assessment': net2})
    result = {'schema_version': 'net2-round-report-v1', 'source_directory': str(source.resolve()), 'reports': reports, 'skipped_sources': skipped_sources, 'formal_result_eligible': False}
    report_data = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(report_data.encode()) >= 5_000_000:
        raise ValueError('BLOCKED: report exceeds 5 MB')
    with report_path.open('x') as stream:
        stream.write(report_data)
    lines = ['# NET2 判定', '', 'INT3 完整保留。NET2 基準由各運具 before 網絡實測；水岸基準缺1500m水域覆蓋證據則 UNAVAILABLE。方法與樣本數見 JSON；沒有整體優勝或正式驗收。', '', '|方案|模式|目標|值|最低門檻|狀態|', '|---|---|---|---|---|---|']
    lines.extend(['', '基準採具名道路長度加權 NAIN 後取完整 before CDF；方案以來源歸屬與既有共線片段支持，角色覆蓋率須≥90%；重疊區間平均後，角色長度加權NAIN→完整after CDF；原INT3部分道路歸屬值另保留diagnostic。兩者比較各自網絡中的相對名次。', '', '|方案|模式|基準|百分位|樣本數|方法|缺資料原因|', '|---|---|---|---|---|---|---|'])
    for record in reports:
        a=record['net2_assessment']
        for key, baseline in a.get('baselines', {}).items():
            lines.append('|'+ '|'.join(str(v) for v in (a['fabric_id'], a['mode'], baseline['reference'], baseline['percentile'], baseline['sample_count'], baseline['method'], baseline.get('reason') or '—'))+'|')
    lines.extend(['', '|方案|模式|目標|值|最低門檻|狀態|', '|---|---|---|---|---|---|'])
    for record in reports:
        assessment = record['net2_assessment']
        for check in assessment['checks']:
            lines.append('|'+ '|'.join(str(v) for v in (assessment['fabric_id'], assessment['mode'], check['target'], check['value'], check['minimum'], check['status']))+'|')
        if assessment['status'] == 'UNAVAILABLE' and not assessment['checks']:
            lines.append('|'+ '|'.join(str(v) for v in (assessment['fabric_id'], assessment['mode'], 'syntax unavailable', None, '—', 'UNAVAILABLE'))+'|')
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
    parser.add_argument('--water-manifest', type=Path, help='JSON containing dataset and coverage receipts; projected coverage geometry must cover site+1520m')
    args = parser.parse_args()
    result = export(args.source, args.output or args.source.parent, json.loads(args.water_manifest.read_text()) if args.water_manifest else None)
    print(json.dumps({'report_count': len(result['reports']), 'output': str(args.output or args.source.parent)}))
