"""Proposal service tests use disposable formal stores and deterministic fake providers only."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from urban_design.judgement.core import Registry
from urban_design.judgement.proposal_service import ProposalService, ProposalRequest, ApprovalRequest, ProposalConflict, RerunRequest
from urban_design.judgement.service import ReconcileRequest


def draft(tmp_path):
    spec = importlib.util.spec_from_file_location('proposal_face_helpers', Path(__file__).with_name('test_formal_face_editing_api.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store, _, ident = module._draft(tmp_path)
    return store, ident


def output():
    return {'proposal_id': 'provider-placeholder', 'responds_to': {'card_id': 'card-test', 'response_ids': []},
            'summary': '我建議局部退讓以測試日照方向。',
            'operations': [{'op': 'REMOVE_TOP_FLOOR', 'building_ids': ['b-rect'], 'floors': 1}, {'op': 'RERUN', 'analyses': ['E1', 'UTCI']}],
            'rationale': ['card-test 的中庭日照觀察支持局部調整。'], 'expected_effects': ['可能增加局部日照。'],
            'trade_offs': ['減少樓地板面積。'], 'risks': ['效果待重算。'], 'not_simulated': [], 'questions_for_designer': ['你願意測試這個方向嗎？']}


class FakeProvider:
    provider_name = 'fixture'
    is_live_available = True
    profile = SimpleNamespace(id='fixture', model='fixture', adapter='fixture')
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0
    def generate_structured(self, request):
        self.calls += 1
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return {'provider_status': 'LIVE_AI: ACTIVE', 'structured': value, 'provider_model': 'fixture', 'limitations': []}


class Judgements:
    registry = Registry()
    def __init__(self):
        self.revision_catalog = {}
        self.calls = []
    def get(self, project, ident):
        if ident != 'card-test':
            raise KeyError(ident)
        return {'id': ident, 'status': 'VALIDATED', 'skill_id': 'J-CLIMATE', 'round': 1,
                'subject': {'kind': 'scenario', 'ids': ['harbour_grain']},
                'card': {'judgement': {'headline': '中庭日照需要局部調整。'}},
                'metrics': {
                    'e1.harbour.courtyard.winter.mean_h': {'value': 0.108, 'unit': 'h'},
                    'e1.harbour.all.winter.mean_h': {'value': 1.79, 'unit': 'h'},
                    'e1.harbour.all.winter.ge2h_pct': {'value': 12.5, 'unit': '%'},
                    'e1.harbour.street.winter.mean_h': {'value': 1.8, 'unit': 'h'},
                    'utci.harbour.all.very_strong_pct': {'value': 14.2, 'unit': '%'},
                },
                'responses': [{'id': 'response-climate', 'kind': 'contest', 'text': '請確認降層是否足夠。'}]}
    def run(self, project, request):
        self.calls.append(request)
        return {'id': 'next-climate-card', 'status': 'VALIDATED'}


def analysis_fixture(analysis, override, folder):
    folder.mkdir(parents=True)
    if analysis == 'E1':
        (folder/'comparison_table.csv').write_text('紋理方案代碼,開放空間類別,冬至平均日照_小時\nharbour_grain,全體開放空間,1.2\nharbour_grain,街廓中庭,0.8\n')
    else:
        (folder/'utci_stress_hours_comparison.json').write_text('{"fabrics":{"harbour_grain":{"stress_table":{"total":{"very_strong_pct":20}}}}}')


def setup(tmp_path, monkeypatch, outputs=None, runner=None):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    monkeypatch.setenv('ARIADNE_LIVE', '1')
    store, ident = draft(tmp_path)
    monkeypatch.setattr('urban_design.judgement.proposal_service.HARBOUR_DRAFT_ID', ident)
    provider = FakeProvider(outputs or [output()])
    pending = []
    judgements = Judgements()
    svc = ProposalService(store, tmp_path/'proposals.sqlite3', judgement_service=judgements,
                          provider_factory=lambda *args: provider, artifact_root=tmp_path/'runtime',
                          analysis_runner=runner or analysis_fixture,
                          job_executor=lambda *args: pending.append(args))
    return svc, provider, ident, pending


def test_create_cache_durable_accounting_and_no_publication(tmp_path, monkeypatch):
    svc, provider, ident, _ = setup(tmp_path, monkeypatch)
    result = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    assert result['status'] == 'VALIDATED', result
    assert svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))['id'] == result['id']
    assert provider.calls == 1
    assert svc.usage('proj-formal')['calls'] == 1
    assert svc.store.current(ident).revision == 1
    assert 'raw_json' not in result['attempts'][0]
    audit_inputs = svc.inputs('proj-formal', result['id'])
    assert audit_inputs == svc.get('proj-formal', result['id'])['input_bundle']
    assert audit_inputs['draft']['parameters']['editable_buildings'][0]['floors']
    with pytest.raises(KeyError):
        svc.get('other-project', result['id'])


def test_approval_one_revision_idempotent_job_and_success(tmp_path, monkeypatch):
    svc, _, ident, pending = setup(tmp_path, monkeypatch)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    prior_decisions = len(svc.store.list_current('HumanDecision', project_id='proj-formal'))
    approved = svc.approve('proj-formal', proposal['id'], ApprovalRequest(note='測試局部退讓'))
    assert approved['approval']['is_human_decision'] is False
    assert approved['approval']['requires_designer_gfa_decision'] is True
    assert svc.store.current(ident).revision == 2
    assert len(svc.store.list_current('HumanDecision', project_id='proj-formal')) == prior_decisions
    assert svc.approve('proj-formal', proposal['id'], ApprovalRequest())['job']['id'] == approved['job']['id']
    assert len(pending) == 1
    assert len(svc.store.current(ident).payload['parameters']['editable_buildings'][0]['floors']) == 3
    job = svc.run_job('proj-formal', approved['job']['id'])
    assert job['status'] == 'SUCCEEDED', job
    assert job['started_at'] and job['ended_at'] and job['outputs']
    assert svc.judgements.calls[0].subject_ids == ['harbour_grain@draft-r2']
    assert svc.run_job('proj-formal', job['id']) == job
    assert len(svc.judgements.calls) == 1


def test_recalculation_judgement_uses_proposal_language(tmp_path, monkeypatch):
    svc, _, ident, _pending = setup(tmp_path, monkeypatch)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident, language='en'))
    approved = svc.approve('proj-formal', proposal['id'], ApprovalRequest(note='test'))
    job = svc.run_job('proj-formal', approved['job']['id'])
    assert job['status'] == 'SUCCEEDED', job
    assert svc.judgements.calls[0].language == 'en'


def test_rerun_writes_revision_context_and_hashes_it_in_manifest(tmp_path, monkeypatch):
    svc, _, ident, _ = setup(tmp_path, monkeypatch)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    approved = svc.approve('proj-formal', proposal['id'], ApprovalRequest())
    job = svc.run_job('proj-formal', approved['job']['id'])

    revision_dir = tmp_path / 'runtime' / 'revisions' / proposal['id']
    context_path = revision_dir / 'revision-context.json'
    context = json.loads(context_path.read_text())
    manifest = json.loads((revision_dir / 'manifest.json').read_text())
    context_output = next(item for item in manifest['outputs'] if item['path'] == 'revision-context.json')

    assert job['status'] == 'SUCCEEDED'
    assert context['proposal_id'] == proposal['id']
    assert context['card_id'] == 'card-test' and context['card_round'] == 1
    assert context['proposal_summary'] == proposal['proposal']['summary']
    assert set(context['before_metrics']) == {
        'e1.harbour.courtyard.winter.mean_h', 'e1.harbour.all.winter.mean_h',
        'e1.harbour.all.winter.ge2h_pct', 'e1.harbour.street.winter.mean_h',
        'utci.harbour.all.very_strong_pct',
    }
    assert any(item['id'] == 'seed-season_priority' and item['kind'] == 'seed_stance'
               for item in context['designer_responses'])
    assert {'id': 'response-climate', 'kind': 'contest', 'text': '請確認降層是否足夠。'} in context['designer_responses']
    assert context['dry_run']['solar_access_check'] == proposal['dry_run']['solar_access_check']
    assert context_output['sha256'] == hashlib.sha256(context_path.read_bytes()).hexdigest()


@pytest.mark.parametrize(('operation', 'language', 'expected'), [
    ({'op': 'REMOVE_TOP_FLOOR', 'building_ids': ['new-7', 'new-8'], 'floors': 1}, 'zh-TW', 'new-7、new-8 各降 1 層'),
    ({'op': 'REMOVE_TOP_FLOOR', 'building_ids': ['new-7', 'new-8'], 'floors': 1}, 'en', 'new-7, new-8: remove 1 floor each'),
    ({'op': 'SETBACK_UPPER', 'building_ids': ['new-7'], 'metres': 2}, 'zh-TW', 'new-7 上層退縮 2 公尺'),
    ({'op': 'MOVE', 'building_id': 'new-7', 'dx_m': 1, 'dy_m': -2}, 'zh-TW', 'new-7 平移 Δx 1 公尺、Δy -2 公尺'),
    ({'op': 'ADD_FLOOR', 'building_ids': ['new-7'], 'floors': 2}, 'en', 'new-7: add 2 floors'),
    ({'op': 'PLANTING_NOTE', 'target': 'courtyard-0', 'kind': 'both'}, 'zh-TW', 'courtyard-0 記錄落葉樹與棚架植栽意向（未納入模擬）'),
    ({'op': 'RERUN', 'analyses': ['E1', 'UTCI']}, 'zh-TW', '重跑 E1、UTCI 分析'),
])
def test_proposal_operation_text_uses_deterministic_templates(operation, language, expected):
    from urban_design.judgement import proposal_service
    formatter = getattr(proposal_service, 'format_operation_text', None)
    assert callable(formatter)
    assert formatter(operation, language) == expected


def test_stale_revision_conflict_before_any_write(tmp_path, monkeypatch):
    svc, _, ident, _ = setup(tmp_path, monkeypatch)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    with pytest.raises(ProposalConflict):
        svc.approve('proj-formal', proposal['id'], ApprovalRequest(expected_revision=9))
    assert svc.store.current(ident).revision == 1
    assert svc.get('proj-formal', proposal['id'])['job'] is None


def test_failure_keeps_history_and_never_retries(tmp_path, monkeypatch):
    calls = []
    def runner(*args):
        calls.append(args)
        raise RuntimeError('analysis failed')
    svc, _, ident, _ = setup(tmp_path, monkeypatch, runner=runner)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    approved = svc.approve('proj-formal', proposal['id'], ApprovalRequest())
    failed = svc.run_job('proj-formal', approved['job']['id'])
    assert failed['status'] == 'FAILED'
    assert failed['retry_allowed'] is False and failed['ended_at']
    assert svc.store.current(ident).revision == 2
    assert svc.run_job('proj-formal', failed['id']) == failed
    assert len(calls) == 1


def test_unknown_blocks_force_until_explicit_reconciliation(tmp_path, monkeypatch):
    svc, provider, ident, _ = setup(tmp_path, monkeypatch, outputs=[TimeoutError('lost'), output()])
    request = ProposalRequest(card_id='card-test', draft_id=ident)
    first = svc.create('proj-formal', request)
    assert first['status'] == 'OUTCOME_UNKNOWN'
    assert svc.create('proj-formal', request.model_copy(update={'force': True}))['id'] == first['id']
    assert provider.calls == 1
    svc.reconcile('proj-formal', first['id'], ReconcileRequest(resolution='DELIVERED_DISCARD', note='Provider result unavailable; explicitly discarded.'))
    second = svc.create('proj-formal', request)
    assert second['status'] == 'VALIDATED' and second['id'] != first['id']
    assert provider.calls == 2
    with pytest.raises(ValueError):
        svc.reconcile('proj-formal', first['id'], ReconcileRequest(resolution='NOT_DELIVERED', note='duplicate'))


def test_one_validation_correction_attempt(tmp_path, monkeypatch):
    bad = copy.deepcopy(output())
    bad['operations'][0]['building_ids'] = ['unknown']
    svc, provider, ident, _ = setup(tmp_path, monkeypatch, outputs=[bad, output()])
    result = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    assert result['status'] == 'VALIDATED', result
    assert provider.calls == 2 and len(result['attempts']) == 2
    assert result['attempts'][0]['validation_errors']


def test_dry_run_failure_retains_reasons_and_cannot_approve(tmp_path, monkeypatch):
    too_high = output()
    too_high['operations'][0] = {'op': 'ADD_FLOOR', 'building_ids': ['b-rect'], 'floors': 2}
    svc, provider, ident, _ = setup(tmp_path, monkeypatch, outputs=[too_high, too_high])
    result = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    assert result['status'] == 'DRY_RUN_FAILED', result
    assert result['dry_run']['errors']
    assert provider.calls == 2
    with pytest.raises(ValueError):
        svc.approve('proj-formal', result['id'], ApprovalRequest())
    assert svc.store.current(ident).revision == 1


def test_analysis_success_and_ai_blocked_are_separate(tmp_path, monkeypatch):
    svc, _, ident, _ = setup(tmp_path, monkeypatch)
    svc.judgements.run = lambda *args: {'id': 'blocked-card', 'status': 'BLOCKED_AI_AUTHORIZATION'}
    result = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    approved = svc.approve('proj-formal', result['id'], ApprovalRequest())
    job = svc.run_job('proj-formal', approved['job']['id'])
    assert job['status'] == 'SUCCEEDED'
    assert job['judgement_status'] == 'BLOCKED_AI_AUTHORIZATION'
    assert job['output_dir'].endswith(result['id'])


def test_crash_after_publication_reconciles_single_revision(tmp_path, monkeypatch):
    svc, _, ident, pending = setup(tmp_path, monkeypatch)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    publish = svc._publish
    def crash(*args):
        publish(*args)
        raise RuntimeError('lost process after formal commit')
    monkeypatch.setattr(svc, '_publish', crash)
    with pytest.raises(RuntimeError):
        svc.approve('proj-formal', proposal['id'], ApprovalRequest())
    assert svc.store.current(ident).revision == 2
    assert not pending
    approved = svc.approve('proj-formal', proposal['id'], ApprovalRequest())
    assert svc.store.current(ident).revision == 2
    assert approved['job']['previous_revision'] == 1
    assert len(pending) == 1


def test_invalid_current_authority_cannot_publish(tmp_path, monkeypatch):
    svc, _, ident, _ = setup(tmp_path, monkeypatch)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    def invalid(*args):
        raise ValueError('source authority changed')
    monkeypatch.setattr('urban_design.judgement.proposal_service.PersistedFormalEditorAdapter.resolve', invalid)
    with pytest.raises(ValueError, match='source authority changed'):
        svc.approve('proj-formal', proposal['id'], ApprovalRequest())
    assert svc.store.current(ident).revision == 1


def test_provider_prompt_uses_summaries_and_seed_stances(tmp_path, monkeypatch):
    import json
    svc, provider, ident, _ = setup(tmp_path, monkeypatch)
    generate = provider.generate_structured
    captured = []
    def capture(request):
        captured.append(json.loads(request.query))
        return generate(request)
    provider.generate_structured = capture
    result = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    assert result['status'] == 'VALIDATED'
    assert 'draft' not in captured[0]['input']
    assert captured[0]['input']['editable_buildings'][0]['building_id'] == 'b-rect'
    assert set(captured[0]['input']['editable_buildings'][0]) == {
        'building_id', 'block_id', 'floors', 'height_m', 'gfa_m2', 'footprint_area_m2', 'centroid'}
    assert captured[0]['input']['solar_reference']['latitude_deg'] == 51.9
    assert captured[0]['input']['courtyards'][0]['solar_geometry']['depth_along_sun_m'] > 0
    assert 'DATA_GAP:e1.harbour.courtyard_breakdown' in captured[0]['input']['data_gaps']
    assert any(r['id'] == 'seed-season_priority' for r in captured[0]['input']['responses'])
    assert len(json.dumps(captured[0]).encode()) < 120000


def test_proposal_assembly_uses_revision_per_courtyard_e1_when_available(tmp_path, monkeypatch):
    import json
    svc, _, ident, _ = setup(tmp_path, monkeypatch)
    revision_subject = 'harbour_grain@draft-r7'
    revision_dir = tmp_path / 'revision-r7'
    e1_dir = revision_dir / 'e1'
    e1_dir.mkdir(parents=True)
    (e1_dir / 'per_courtyard.json').write_text(json.dumps([
        {'fabric_id': 'harbour_grain', 'courtyard_id': 'courtyard-0', 'winter_mean': 0.109},
    ]))
    svc.judgements.get = lambda project, card_id: {
        'id': card_id, 'status': 'VALIDATED', 'skill_id': 'J-CLIMATE', 'round': 2,
        'subject': {'kind': 'scheme', 'ids': [revision_subject]},
        'context': {'proposal_id': 'proposal-r7'}, 'card': {}, 'responses': [],
    }
    svc.judgements.revision_catalog[revision_subject] = revision_dir
    bundle, _ = svc._bundle('proj-formal', ProposalRequest(card_id='card-revision', draft_id=ident))
    court = next(item for item in bundle['courtyards'] if item['courtyard_id'] == 'courtyard-0')
    assert court['solar_geometry']['winter_mean_h'] == 0.109
    assert 'DATA_GAP:e1.harbour.courtyard_breakdown' not in bundle['data_gaps']


def test_analysis_acknowledgement_without_artifact_is_failed(tmp_path, monkeypatch):
    svc, _, ident, _ = setup(tmp_path, monkeypatch, runner=lambda *args: None)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    approved = svc.approve('proj-formal', proposal['id'], ApprovalRequest())
    failed = svc.run_job('proj-formal', approved['job']['id'])
    assert failed['status'] == 'FAILED'
    assert 'analysis output missing' in failed['errors'][0]
    assert svc.judgements.calls == []


def test_utci_runs_in_climate_venv_and_e1_in_project_venv(tmp_path, monkeypatch):
    import sys
    from urban_design.judgement import proposal_service as ps
    fake = tmp_path / 'climate-python'; fake.write_text('#!/bin/sh\n')
    monkeypatch.setenv('URBAN_DESIGN_CLIMATE_PYTHON', str(fake))
    assert ps.analysis_python('UTCI') == str(fake)
    assert ps.analysis_python('E1') == sys.executable
    monkeypatch.setenv('URBAN_DESIGN_CLIMATE_PYTHON', str(tmp_path / 'missing'))
    assert ps.analysis_python('UTCI') == sys.executable


def test_manual_rerun_after_failure_keeps_failed_outputs_and_succeeds(tmp_path, monkeypatch):
    state = {'fail': True}
    def runner(analysis, override, output_dir):
        if state['fail']:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / 'partial.log').write_text('octree stale')
            raise RuntimeError('analysis failed')
        return analysis_fixture(analysis, override, output_dir)
    svc, _, ident, pending = setup(tmp_path, monkeypatch, runner=runner)
    proposal = svc.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=ident))
    approved = svc.approve('proj-formal', proposal['id'], ApprovalRequest())
    failed = svc.run_job('proj-formal', approved['job']['id'])
    assert failed['status'] == 'FAILED'
    state['fail'] = False
    retried = svc.rerun('proj-formal', proposal['id'], RerunRequest(note='Radiance 暫存衝突已修'))
    assert retried['job']['status'] == 'PENDING' and retried['job']['attempt'] == 2 and retried['job']['retry_of'] == failed['id']
    assert [item['id'] for item in retried['job_history']] == [failed['id']]
    root = Path(failed['output_dir'])
    assert (root / 'failed' / failed['id']).is_dir()
    done = svc.run_job('proj-formal', retried['job']['id'])
    assert done['status'] == 'SUCCEEDED', done
    assert not any(item['path'].startswith('failed/') for item in done['outputs'])
    assert svc.store.current(ident).revision == approved['job']['draft_revision']
    with pytest.raises(ValueError):
        svc.rerun('proj-formal', proposal['id'], RerunRequest())


def test_comparison_before_prefers_previous_revision_results(tmp_path):
    import json
    from urban_design.judgement import proposal_comparison as pc
    revisions = tmp_path / 'revisions'
    (revisions / 'proposal-prev').mkdir(parents=True)
    (revisions / 'proposal-prev' / 'manifest.json').write_text(json.dumps({'subject_id': 'harbour_grain@draft-r3', 'project_id': 'p'}))
    calls = []
    def fake_assemble(store, project, subject, registry, root):
        calls.append((subject, root.name))
        return {'metrics': {'e1.harbour.courtyard.winter.mean_h': {'value': 0.109}}}
    import urban_design.judgement.revision_inputs as ri
    original = ri.assemble_revision
    ri.assemble_revision = fake_assemble
    try:
        before, basis = pc.before_metrics_for({'project_id': 'p'}, {'metrics': {}}, None, None, revisions / 'proposal-new', 3)
    finally:
        ri.assemble_revision = original
    assert basis == 'previous_draft_revision' and before['e1.harbour.courtyard.winter.mean_h']['value'] == 0.109
    assert calls == [('harbour_grain@draft-r3', 'proposal-prev')]
    before, basis = pc.before_metrics_for({'project_id': 'p'}, {'metrics': {'e1.harbour.courtyard.winter.mean_h': {'value': 0.108}}}, None, None, tmp_path / 'none' / 'x', None)
    assert basis == 'judgement_card'
