import csv
import hashlib
import json

import pytest

from urban_design.judgement.core import Registry
from urban_design.judgement.revision_inputs import assemble_revision
from urban_design.judgement.service import JudgementService, RunRequest
from urban_design.store import ProjectStateStore


def revision(tmp_path, *, per_courtyard=False, include_context=False):
    directory = tmp_path / 'revision'
    (directory / 'e1').mkdir(parents=True)
    (directory / 'utci').mkdir()
    fields = ['紋理方案代碼', '開放空間類別', '代表面積_m2']
    for season in ('春分', '夏至', '冬至'):
        fields += [season + '平均日照_小時', season + '日照大於等於2小時比例_百分比']
    with (directory / 'e1/comparison_table.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for category in ['全體開放空間', '街廓中庭', '街道路權']:
            row = dict.fromkeys(fields, 17.25) | {'紋理方案代碼': 'harbour_grain', '開放空間類別': category}
            if include_context and category == '街廓中庭':
                row['冬至平均日照_小時'] = 0.109
            writer.writerow(row)
    if per_courtyard:
        (directory / 'e1/per_courtyard.json').write_text(json.dumps([
            {'fabric_id': 'harbour_grain', 'courtyard_id': 'courtyard-0', 'points': 4, 'area_m2': 100,
             'spring_mean': 3.5, 'summer_mean': 7.0, 'winter_mean': 0.109, 'winter_ge_2h_pct': 25.0},
        ]))
    (directory / 'utci/utci_stress_hours_comparison.json').write_text(json.dumps({
        'fabrics': {'harbour_grain': {'stress_table': {'total': {'very_strong_pct': 13.5}}}}}))
    manifest = {'project_id': 'p', 'subject_id': 'harbour_grain@draft-r7', 'draft_id': 'draft',
                'draft_revision': 7, 'proposal_id': 'proposal-test', 'gfa_after_m2': 125000,
                'analyses': ['E1', 'UTCI'], 'outputs': []}
    for relative in ['e1/comparison_table.csv', 'utci/utci_stress_hours_comparison.json']:
        manifest['outputs'].append({'path': relative, 'sha256': hashlib.sha256((directory / relative).read_bytes()).hexdigest()})
    if per_courtyard:
        relative = 'e1/per_courtyard.json'
        manifest['outputs'].append({'path': relative, 'sha256': hashlib.sha256((directory / relative).read_bytes()).hexdigest()})
    if include_context:
        context = {
            'proposal_id': 'proposal-test', 'card_id': 'card-before', 'card_round': 4,
            'proposal_summary': '降低南側量體以測試中庭冬季日照。',
            'operations_text_zh': ['new-7、new-8 各降 1 層'],
            'operations_text_en': ['new-7, new-8: remove 1 floor each'],
            'designer_responses': [{'id': 'seed-courtyard_role', 'kind': 'seed_stance', 'text': '中庭是住戶停留空間。'}],
            'dry_run': {'gfa_before_m2': 130000, 'gfa_after_m2': 125000,
                        'affected_building_ids': ['new-7', 'new-8'],
                        'solar_access_check': {'courtyards': [{'courtyard_id': 'courtyard-0',
                            'south_height_after_m': 18.0, 'h_north_edge_m': 12.97,
                            'reaches_north_edge': False}], 'warning': True}},
            'before_metrics': {'e1.harbour.courtyard.winter.mean_h': 0.108},
        }
        context_path = directory / 'revision-context.json'
        context_path.write_text(json.dumps(context, ensure_ascii=False))
        manifest['outputs'].append({'path': 'revision-context.json',
                                    'sha256': hashlib.sha256(context_path.read_bytes()).hexdigest()})
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return directory


def test_proposal_revision_results_are_used_and_stale_results_excluded(tmp_path):
    directory = revision(tmp_path)
    bundle = assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)
    assert bundle['metrics']['e1.harbour.courtyard.winter.mean_h']['value'] == 17.25
    assert bundle['metrics']['e1.harbour.all.winter.ge2h_pct']['value'] == 17.25
    assert bundle['metrics']['utci.harbour.all.very_strong_pct']['value'] == 13.5
    assert bundle['metrics']['scheme.harbour.new_gfa_m2']['value'] == 125000
    assert not any(key.startswith(('e2.', 'e3.', 'e4.', 'e5.')) for key in bundle['metrics'])
    assert 'DATA_GAP:e5.*' in bundle['data_gaps']
    assert bundle['subject']['ids'] == ['harbour_grain@draft-r7']


def test_proposal_revision_reads_per_courtyard_metrics_when_present(tmp_path):
    directory = revision(tmp_path, per_courtyard=True)
    bundle = assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)
    assert bundle['metrics']['e1.harbour.courtyard-0.winter.mean_h']['value'] == 0.109
    assert bundle['metrics']['e1.harbour.courtyard-0.winter.ge2h_pct']['value'] == 25.0
    assert 'DATA_GAP:e1.harbour.courtyard_breakdown' not in bundle['data_gaps']


def test_proposal_revision_context_is_loaded_and_summarized_as_text_input(tmp_path):
    directory = revision(tmp_path, per_courtyard=True, include_context=True)
    bundle = assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)

    assert bundle['context']['revision_context']['proposal_id'] == 'proposal-test'
    summary_metric = bundle['metrics']['context.revision_summary_zh']
    assert '重算前中庭冬至平均日照 0.108 小時；重算後 0.109 小時' in summary_metric['value']
    assert '南側最高 18.0 公尺' in summary_metric['value']
    assert '12.97 公尺' in summary_metric['value']
    assert any(item['metric_id'] == 'context.revision_summary_zh' and item['value'] == summary_metric['value']
               for item in bundle['inputs'])
    assert bundle['metrics']['prev.e1.harbour.courtyard.winter.mean_h']['value'] == 0.108
    assert bundle['metrics']['prev.e1.harbour.courtyard.winter.mean_h']['unit'] == 'h'


def test_missing_proposal_revision_context_is_a_data_gap(tmp_path):
    directory = revision(tmp_path)
    bundle = assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)

    assert bundle['context']['revision_context'] is None
    assert 'DATA_GAP:revision_context' in bundle['data_gaps']


def test_proposal_revision_context_sha_mismatch_fails_closed(tmp_path):
    directory = revision(tmp_path, include_context=True)
    (directory / 'revision-context.json').write_text('{"tampered":true}')

    with pytest.raises(ValueError, match='hash mismatch'):
        assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)


def test_proposal_revision_context_rejects_untyped_extra_fields(tmp_path):
    directory = revision(tmp_path, include_context=True)
    context_path = directory / 'revision-context.json'
    context = json.loads(context_path.read_text())
    context['unexpected'] = 'must be rejected'
    context_path.write_text(json.dumps(context, ensure_ascii=False))
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    next(item for item in manifest['outputs'] if item['path'] == 'revision-context.json')['sha256'] = hashlib.sha256(context_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False))

    with pytest.raises(ValueError, match='schema'):
        assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)


def test_proposal_revision_marks_missing_per_courtyard_breakdown_as_data_gap(tmp_path):
    directory = revision(tmp_path)
    bundle = assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)
    assert 'DATA_GAP:e1.harbour.courtyard_breakdown' in bundle['data_gaps']


def test_proposal_revision_source_integrity_and_scope(tmp_path):
    directory = revision(tmp_path)
    with pytest.raises(ValueError, match='project or subject'):
        assemble_revision(None, 'other', 'harbour_grain@draft-r7', Registry(), directory)
    (directory / 'e1/comparison_table.csv').write_text('tampered')
    with pytest.raises(ValueError, match='hash mismatch'):
        assemble_revision(None, 'p', 'harbour_grain@draft-r7', Registry(), directory)


def test_proposal_revision_judgement_service_inputs(tmp_path):
    directory = revision(tmp_path)
    service = JudgementService(ProjectStateStore(tmp_path / 'store.sqlite'), tmp_path / 'judgement.sqlite',
                               revision_catalog={'harbour_grain@draft-r7': directory})
    bundle, previous = service.inputs('p', RunRequest(skill_id='J-CLIMATE', subject_ids=['harbour_grain@draft-r7']))
    assert previous == [] and bundle['context']['draft_revision'] == 7
    with pytest.raises(ValueError, match='unknown draft revision'):
        service.inputs('p', RunRequest(skill_id='J-CLIMATE', subject_ids=['harbour_grain@draft-r8']))


def test_proposal_revision_round_and_catalog_survive_restart(tmp_path, monkeypatch):
    directory = revision(tmp_path)
    monkeypatch.setenv('ARIADNE_LIVE', '0')
    database = tmp_path / 'judgement.sqlite'
    store = ProjectStateStore(tmp_path / 'store.sqlite')
    service = JudgementService(store, database)
    first = service.run('p', RunRequest(skill_id='J-CLIMATE', subject_ids=['harbour_grain']))
    assert first['round'] == 1
    # This is a registered proposal job receipt, not subject-controlled path traversal.
    with service.connect() as db:
        db.execute('CREATE TABLE proposal_jobs (project TEXT, payload TEXT)')
        db.execute('INSERT INTO proposal_jobs VALUES (?,?)', ('p', json.dumps({
            'draft_revision': 7, 'status': 'SUCCEEDED', 'output_dir': str(directory)})))
    restarted = JudgementService(store, database)
    second = restarted.run('p', RunRequest(skill_id='J-CLIMATE', subject_ids=['harbour_grain@draft-r7']))
    assert second['round'] == 2
    assert second['metrics']['e1.harbour.all.winter.mean_h']['value'] == 17.25
    assert second['status'] == 'BLOCKED_AI_AUTHORIZATION'
