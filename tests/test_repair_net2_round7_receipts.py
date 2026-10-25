"""Publisher failure paths use disposable evidence, never PST or project artifacts."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.fixture
def publisher(monkeypatch, tmp_path):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('round7_publisher_under_test', scripts / 'repair_net2_round7_receipts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    round_dir = tmp_path / 'artifacts/net2/round-7'
    monkeypatch.setattr(module, 'ROUND', round_dir)
    for directory in ('receipts/compact', 'syntax/segments'):
        (round_dir / directory).mkdir(parents=True)
    for filename in ('src/urban_design/fabric_net2_assessment.py', 'scripts/export_net2_syntax.py'):
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('frozen source')
    source = round_dir / 'receipts/source.json'
    source.write_text('{}')
    checkpoint = round_dir / 'receipts/checkpoint.json'
    checkpoint.write_text(json.dumps({'runtime': module.receipt(source), 'raw_result': module.receipt(source)}))
    full = round_dir / 'receipts/full.json'
    full.write_text(json.dumps({'pst_checkpoint_receipts': [module.receipt(checkpoint)]}))
    documents = {}
    reassessed = []
    monkeypatch.setattr(module, 'verify_selected_plan_receipt', lambda *args: None)
    monkeypatch.setattr(module, 'SegmentCollection', SimpleNamespace(model_validate=lambda value: None))
    monkeypatch.setattr(module, 'load_verified', lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(module, 'lineage', lambda compact: ({}, {}, {}))
    monkeypatch.setattr(module, 'waterfront_joins', lambda *args: [])
    def assess(*args, **kwargs):
        reassessed.append(True)
        return {'status': 'RECALCULATED'}
    monkeypatch.setattr(module, 'assess_net2', assess)
    monkeypatch.setattr(module, 'build', lambda path: (copy.deepcopy(documents[path.stem]), {}))

    def make(count=12, drift=False, missing_sidecar=False):
        for index in range(count):
            stem = f'case{index}-pedestrian'
            compact = round_dir / 'receipts/compact' / f'{stem}.json'
            compact.write_text('{}')
            doc = {'features': [index], 'legend_breaks': {}, 'intent_assessment': {},
                   'metadata': {'fabric_id': f'case{index}', 'mode': 'pedestrian', 'source_receipts': {
                       'compact': module.receipt(compact), 'full': module.receipt(full), 'plan': module.receipt(source),
                       'net2_assessor': module.receipt(tmp_path / 'src/urban_design/fabric_net2_assessment.py'),
                       'net2_exporter': module.receipt(tmp_path / 'scripts/export_net2_syntax.py')}}}
            documents[stem] = copy.deepcopy(doc)
            if drift and index == 0:
                documents[stem]['features'] = ['fresh deterministic result']
            destination = round_dir / 'syntax/segments' / f'{stem}.geojson'
            destination.write_text(json.dumps(doc))
            if not (missing_sidecar and index == 9):
                destination.with_suffix('.receipt.json').write_text(json.dumps({'export': module.receipt(destination)}))
            (round_dir / 'syntax' / compact.name).write_text('old compact')
        summary = round_dir / 'receipts/compact/syntax-summary.json'
        summary.write_text(json.dumps({'status': 'COMPUTED', 'computed_count': count, 'results': [{}] * count}))
        (round_dir / 'syntax/syntax-summary.json').write_text('old summary')
        return module, reassessed
    return make


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def test_incomplete_round_never_mutates_originals(publisher):
    module, _ = publisher(count=11)
    before = snapshot(module.ROUND)
    with pytest.raises(ValueError, match='Exactly 12'):
        module.publish()
    assert snapshot(module.ROUND) == before


@pytest.mark.parametrize('blocker', ('late_backup', 'report'))
def test_existing_backup_or_report_preflight_never_mutates(publisher, blocker):
    module, _ = publisher()
    path = (module.ROUND / 'syntax/segments/case9-pedestrian.receipt.json.old' if blocker == 'late_backup'
            else module.ROUND / 'receipts/repair-report.json')
    path.write_text('prior evidence')
    before = snapshot(module.ROUND)
    with pytest.raises(ValueError, match='backup exists|report exists'):
        module.publish()
    assert snapshot(module.ROUND) == before


def test_metric_drift_uses_actual_assessor_and_preserves_old_export(publisher):
    module, reassessed = publisher(drift=True)
    old = (module.ROUND / 'syntax/segments/case0-pedestrian.geojson').read_bytes()
    module.publish()
    destination = module.ROUND / 'syntax/segments/case0-pedestrian.geojson'
    result = json.loads(destination.read_text())
    assert reassessed == [True]
    assert result['features'] == ['fresh deterministic result']
    assert result['net2_assessment']['status'] == 'RECALCULATED'
    assert destination.with_name(destination.name + '.old').read_bytes() == old
    report = json.loads((module.ROUND / 'receipts/repair-report.json').read_text())
    assert len(report) == 12 and sum(row['geometry_metrics_match'] for row in report) == 11


def test_checkpoint_drift_fails_before_publication(publisher):
    module, _ = publisher()
    (module.ROUND / 'receipts/source.json').write_text('tampered raw checkpoint')
    before = snapshot(module.ROUND)
    with pytest.raises(ValueError, match='BLOCKED: missing or mismatched receipt'):
        module.publish()
    assert snapshot(module.ROUND) == before


def test_late_missing_sidecar_fails_before_any_rename(publisher):
    module, _ = publisher(missing_sidecar=True)
    before = snapshot(module.ROUND)
    with pytest.raises(ValueError, match='Missing original artifact'):
        module.publish()
    assert snapshot(module.ROUND) == before
