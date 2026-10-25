"""Publish freshly computed round-7 PST lineage, preserving prior exports as .old.

Run compute_fabric_syntax.py first with --output receipts/compact --temp
receipts/full --cache-dir receipts/pst-cache --positive-support-diff. This
publisher never fabricates a missing full result or substitutes a metric.
"""
from pathlib import Path
import json
import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from urban_design.fabric_syntax_segments import build, receipt, load_verified, verify, lineage, SegmentCollection
from urban_design.fabric_plans_api import verify_selected_plan_receipt
from export_net2_syntax import waterfront_joins, assess_net2

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / 'artifacts/net2/round-7'


def publish():
    report = ROUND / 'receipts/repair-report.json'
    if report.exists():
        raise ValueError('Repair report exists; reconcile before retry')
    changes = []
    prepared = []
    canonical = []
    for compact in sorted((ROUND / 'receipts/compact').glob('*.json')):
        if compact.name.endswith('-road-receipts.json') or compact.name == 'syntax-summary.json':
            continue
        fresh, _ = build(compact)
        fresh = json.loads(json.dumps(fresh, allow_nan=False))
        full = json.loads(verify(fresh['metadata']['source_receipts']['full']).read_text())
        if not full.get('pst_checkpoint_receipts'):
            raise ValueError('Missing actual PST checkpoint lineage: ' + compact.stem)
        for ref in full['pst_checkpoint_receipts']:
            checkpoint = json.loads(verify(ref).read_text())
            verify(checkpoint['runtime'])
            verify(checkpoint['raw_result'])
        destination = ROUND / 'syntax/segments' / (compact.stem + '.geojson')
        previous = json.loads(destination.read_text())
        # The independent NET2 assessment remains valid only if all exported
        # measurements and geometry match the newly calculated PST result.
        same = all(fresh[k] == previous[k] for k in ('features', 'legend_breaks', 'intent_assessment'))
        fresh['metadata']['source_receipts']['compact'] = {**receipt(compact), 'path': str(ROUND / 'syntax' / compact.name)}
        previous['metadata']['source_receipts'] = fresh['metadata']['source_receipts']
        for key in ('net2_assessor', 'net2_exporter'):
            old = json.loads(destination.read_text())['metadata']['source_receipts'][key]
            local = ROOT / ('src/urban_design/fabric_net2_assessment.py' if key == 'net2_assessor' else 'scripts/export_net2_syntax.py')
            verify({**old, 'path': str(local)})
            previous['metadata']['source_receipts'][key] = receipt(local)
        # Resolve retained water receipts by exact hash, without changing data.
        water = previous.get('net2_assessment', {}).get('baselines', {}).get('waterfront_meets', {}).get('source_receipts', {})
        for key, ref in water.items():
            if '/artifacts/' in ref['path']:
                local = ROOT / ('artifacts/' + ref['path'].split('/artifacts/', 1)[1])
                verify({**ref, 'path': str(local)})
                water[key] = {**ref, 'path': str(local)}
            else:
                verify(ref)
        if not same:
            full, plan, network = lineage(json.loads(compact.read_text()))
            fresh['net2_assessment'] = assess_net2(full, plan, network, fresh['intent_assessment'], waterfront_joins(full, plan) if fresh['metadata']['mode'] in ('pedestrian', 'bicycle') else [], water=water or None)
            fresh['net2_assessment']['direct_join_scope'] = 'All INT3 new proposal roads, after unchanged receipt/surviving-target/unlink checks'
            fresh['metadata']['source_receipts'] = previous['metadata']['source_receipts']
            previous = fresh
        verify_selected_plan_receipt(ROOT / 'artifacts/fab1/run-8', fresh['metadata']['fabric_id'], fresh['metadata']['source_receipts']['plan'])
        SegmentCollection.model_validate(previous)
        if len(json.dumps(previous, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()) >= 5_000_000:
            raise ValueError('Export exceeds 5 MB: ' + compact.stem)
        prepared.append((destination, previous))
        canonical.append((ROUND / 'syntax' / compact.name, compact.read_bytes()))
        changes.append({'file': str(destination.relative_to(ROOT)), 'geometry_metrics_match': same, 'prior_export_sha256': receipt(destination)['sha256'], 'prior_full_sha256': json.loads(destination.read_text())['metadata']['source_receipts']['full']['sha256'], 'fresh_full_sha256': fresh['metadata']['source_receipts']['full']['sha256']})
    if len(prepared) != 12:
        raise ValueError('Exactly 12 verified fresh computations required')
    summary = ROUND / 'receipts/compact/syntax-summary.json'
    summary_document = json.loads(summary.read_text())
    if summary_document['status'] != 'COMPUTED' or summary_document['computed_count'] != 12 or len(summary_document['results']) != 12:
        raise ValueError('Fresh summary must contain twelve computed results')
    canonical.append((ROUND / 'syntax/syntax-summary.json', summary.read_bytes()))
    for destination, _ in canonical:
        if not destination.is_file():
            raise ValueError('Missing canonical artifact: ' + str(destination))
        if destination.with_name(destination.name + '.old').exists():
            raise ValueError('Prior canonical backup exists: ' + str(destination))
    for destination, _ in prepared:
        sidecar = destination.with_suffix('.receipt.json')
        for path in (destination, sidecar):
            if not path.is_file():
                raise ValueError('Missing original artifact: ' + str(path))
            old = path.with_name(path.name + '.old')
            if old.exists():
                raise ValueError('Prior backup exists; reconcile before retry: ' + str(old))
    for destination, data in canonical:
        destination.rename(destination.with_name(destination.name + '.old'))
        destination.write_bytes(data)
    for destination, document in prepared:
        sidecar = destination.with_suffix('.receipt.json')
        destination.rename(destination.with_name(destination.name + '.old'))
        sidecar.rename(sidecar.with_name(sidecar.name + '.old'))
        destination.write_text(json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
        sidecar.write_text(json.dumps({'export': receipt(destination), 'size_bytes': destination.stat().st_size}, indent=2))
        load_verified(destination)
    report.write_text(json.dumps(changes, indent=2))
    print(json.dumps({'verified_count': len(prepared), 'geometry_metrics_match_count': sum(c['geometry_metrics_match'] for c in changes)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compute', action='store_true', help='Run fresh pinned PST into persistent repo receipts first')
    args = parser.parse_args()
    if args.compute:
        from compute_fabric_syntax import run
        result = run(ROUND / 'plans', ROUND / 'receipts/compact', ROUND / 'receipts/full', cache_dir=ROUND / 'receipts/pst-cache', positive_support=True)
        if result['status'] != 'COMPUTED':
            raise ValueError('Fresh PST calculation incomplete; exports remain unchanged')
    publish()
