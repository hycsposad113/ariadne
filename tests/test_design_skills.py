from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from urban_design.api import create_workspace_app
from urban_design.knowledge.loader import load_knowledge
from urban_design.model_profiles import ModelProviderProfile, load_model_provider_config
from urban_design.skills.contracts import RunRequest
from urban_design.skills.provider import CodexSkillProvider, OutcomeUnknown
from urban_design.skills.router import create_skills_router
from urban_design.skills.runner import SkillConflict, SkillRunner
from urban_design.skills.validator import validate
from urban_design.store import ProjectStateStore


@pytest.fixture
def knowledge():
    return load_knowledge()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv('PROJECT_AI_AUTHORIZED', raising=False)
    store = ProjectStateStore(tmp_path / '.urban_design_runtime/state.sqlite3')
    store.create_project({'id': 'p', 'name': 'skills fixture'}, project_id='p')
    store.create('Scenario', {'id': 's', 'project_id': 'p', 'status': 'proposed',
                 'geometry_sha256': 'sha256:' + 'a' * 64,
                 'parameters': {'metrics': {'height': {'value': 20.0, 'unit': 'm', 'validation_status': 'VALIDATED'}}}},
                 entity_id='s', project_id='p', actor='TEST_HARNESS')
    yield store
    store.close()


def response(cards=('CTX-001',), **patch):
    data = dict(status='DRAFT', design_intent_zh='讓入口與生活路徑相連。', rationale_zh='以周邊脈絡檢驗量體配置。',
                rule_card_ids=list(cards), library_ids=[], numeric_claims=[], uncertainties_zh=['現況入口仍需查證。'],
                strategies=[], strengths_zh=['入口配置可比較。'], weaknesses_zh=['通行資料仍不完整。'],
                risks_zh=['貨運衝突尚未排除。'], goal_results_zh=['目標與實際需有效結果支持。'],
                walking_zh='先沿外部入口進入生活走廊。', massing_response_zh='依周遭高差保留空間。',
                alternatives_zh=['集中入口並檢驗衝突。', '分散入口並檢驗辨識性。'])
    data.update(patch)
    return json.dumps(data, ensure_ascii=False)


def provider(transport):
    profile = next(p for p in load_model_provider_config().profiles if p.id == 'codex-cli')
    return CodexSkillProvider(profile, transport=transport)


def run(runner, key='one', stage='S8'):
    job, created = runner.submit('s', stage, RunRequest(idempotency_key=key))
    if created:
        runner.execute(job['run_id'])
    return runner.get('s', stage, job['run_id'])


def test_fake_success_accounting_prompt_and_isolation(setup, monkeypatch):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-do-not-inherit')
    calls = []
    def transport(args, **kwargs):
        assert Path(kwargs['cwd']).is_relative_to(Path(setup.database).parent)
        assert list(Path(kwargs['cwd']).iterdir()) == []
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['timeout'] > 0 and kwargs['max_output_bytes'] > 0
        assert 'OPENAI_API_KEY' not in kwargs['env']
        assert args[1:8] == ['exec', '-m', 'gpt-6-luna', '-c', 'model_reasoning_effort=max', '-s', 'read-only']
        assert '--skip-git-repo-check' in args
        [record] = setup.list_current('ModelRun')
        assert record.payload['status'] == 'PENDING'
        import hashlib
        assert record.payload['prompt_hash'] == hashlib.sha256(args[-1].encode()).hexdigest()
        prompt = json.loads(args[-1].split('\n', 1)[1])
        assert prompt['metrics']['scenario.metrics.height']['value'] == 20
        assert prompt['knowledge_status'] == 'CANDIDATE_PENDING_FOUNDER'
        assert 'library' in prompt and 'claims' in prompt['library'][0]
        calls.append(args)
        return response(numeric_claims=[{'metric_id': 'scenario.metrics.height', 'value': 20, 'unit': 'm'}],
                        rationale_zh='scenario.metrics.height 為 20 m，僅解釋輸入而非新量測。')
    runner = SkillRunner(setup, provider=provider(transport))
    result = run(runner)
    assert result['status'] == 'VALIDATED_DRAFT'
    assert result['validation']['errors'] == []
    [record] = setup.list_current('ModelRun')
    assert record.payload['status'] == 'SUCCEEDED'
    assert record.payload['scenario_id'] == 's'
    assert record.payload['response_hash'] == result['response_hash']
    assert setup.list_current('HumanDecision') == []
    assert setup.current('s').revision == 1
    assert run(runner)['run_id'] == result['run_id']
    assert len(calls) == 1


def test_kb_retrieval_context_is_wired_for_s3_s7_s8_without_widening_citations(setup, tmp_path):
    repo = Path(__file__).resolve().parents[1]
    isolated_root = tmp_path / 'isolated-project'
    isolated_root.mkdir()
    (isolated_root / 'src').mkdir()
    shutil.copytree(repo / 'src' / 'urban_design', isolated_root / 'src' / 'urban_design')
    (isolated_root / 'knowledge').mkdir()
    for directory in ('design_rules', 'library', 'skills'):
        shutil.copytree(repo / 'knowledge' / directory, isolated_root / 'knowledge' / directory)
    shutil.copy2(repo / 'knowledge' / 'library-schema.json', isolated_root / 'knowledge' / 'library-schema.json')
    isolated_knowledge = load_knowledge(isolated_root)

    unit_path = isolated_root / 'knowledge' / 'v2' / 'domains' / 'SYN' / 'units' / 'KU-SYN-001.json'
    unit_path.parent.mkdir(parents=True)
    unit_path.write_text(json.dumps({
        'id': 'KU-SYN-001', 'title_zh': '空間語法整合度', 'title_en': 'Space syntax integration',
        'summary_zh': 'Space syntax integration is a local retrieval fixture.',
        'key_points_zh': ['Integration relates to a street network.'],
        'evidence': {'strength': 'THEORETICAL', 'findings': []}, 'values': [],
        'debates_zh': '尺度與圖表示會影響解讀。', 'not_applicable_when_zh': '不可作為實測值。',
        'sources': [{'library_id': next(iter(isolated_knowledge.library)), 'claim_id': 'C1'}],
    }, ensure_ascii=False), encoding='utf-8')
    topic_path = isolated_root / 'knowledge' / 'v2' / 'topics' / 'space-syntax.md'
    topic_path.parent.mkdir(parents=True)
    topic_path.write_text('# 空間語法\n\nSpace syntax integration and street networks. KU-SYN-001\n', encoding='utf-8')

    runner = SkillRunner(setup, knowledge=isolated_knowledge)
    for stage in ('S3', 'S7', 'S8'):
        job, created = runner.submit(
            's', stage,
            RunRequest(idempotency_key='kb3-' + stage, knowledge_query_zh='space syntax integration'),
        )
        assert created
        with setup.locked_connection() as connection:
            row = connection.execute('SELECT payload FROM skill_jobs WHERE run_id=?', (job['run_id'],)).fetchone()
        payload = json.loads(row['payload'])
        prompt_bundle = json.loads(payload['prompt'].split('\n', 1)[1])

        retrieved = prompt_bundle['additional_knowledge_context']
        assert retrieved['query_zh'] == 'space syntax integration'
        assert retrieved['unit_ids']
        assert '主題綜述' in retrieved['context_pack']
        assert len(retrieved['context_pack']) <= 10000
        assert all(f"### {unit_id}｜" in retrieved['context_pack'] for unit_id in retrieved['unit_ids'])
        assert '## 書目' in retrieved['context_pack']
        allowed = prompt_bundle['formal_citation_allowlist']
        assert allowed['rule_card_ids'] == payload['card_ids']
        assert set(allowed['library_ids']) == {
            source.library_id
            for card in isolated_knowledge.cards
            if card.id in payload['card_ids']
            for source in card.sources
        }
        assert '一般專業知識，非文獻依據' in payload['prompt']
    assert setup.list_current('HumanDecision') == []


@pytest.mark.parametrize(('raw','error'), [
    ('{oops', 'INVALID_JSON_OR_SCHEMA'),
    (response(cards=('ZZZ-999',)), 'CARD_NOT_SUPPLIED'),
    (response(library_ids=['LIB-OUTSIDE']), 'EXTERNAL_LITERATURE'),
    (response(rationale_zh='依據 https://outside.test/book 的論點。'), 'EXTERNAL_LITERATURE'),
    (response(rationale_zh='高度是 99 m。'), 'UNSUPPORTED_NUMBER'),
    (response(numeric_claims=[{'metric_id': 'scenario.metrics.height', 'value': 99, 'unit': 'm'}]), 'UNSUPPORTED_NUMBER'),
    (response(numeric_claims=[{'metric_id': 'scenario.metrics.height', 'value': 20, 'unit': 'ft'}]), 'UNSUPPORTED_NUMBER'),
    (response(rationale_zh='高度二十公尺。'), 'UNSUPPORTED_NUMBER'),
])
def test_rejection_preserves_original_and_accounts(setup, monkeypatch, raw, error):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    result = run(SkillRunner(setup, provider=provider(lambda *a, **k: raw)))
    assert result['status'] == 'REJECTED_BY_VALIDATOR'
    assert error in result['validation']['errors']
    assert result['raw_output'] == raw
    assert setup.list_current('ModelRun')[0].payload['status'] == 'MODEL_FAILED'


def test_outcome_unknown_is_not_resent_after_reconstruction(setup, monkeypatch):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    calls = []
    def transport(*args, **kwargs):
        calls.append('launch')
        raise OutcomeUnknown('timeout after launch')
    p = provider(transport)
    runner = SkillRunner(setup, provider=p)
    first = run(runner)
    assert first['status'] == 'OUTCOME_UNKNOWN'
    assert setup.list_current('ModelRun')[0].payload['status'] == 'OUTCOME_UNKNOWN'
    second = run(SkillRunner(setup, provider=p))
    runner.execute(first['run_id'])
    assert first['run_id'] == second['run_id']
    assert calls == ['launch']


@pytest.mark.parametrize('stage', ['S3', 'S7', 'S8'])
def test_template_is_non_ai_and_not_an_acceptance(setup, stage):
    def forbidden(*args, **kwargs):
        pytest.fail('unauthorized dispatch')
    result = run(SkillRunner(setup, provider=provider(forbidden)), stage=stage)
    assert result['status'] == 'NON_AI_TEMPLATE'
    assert result['output']['status'] == 'INCOMPLETE'
    assert result['validation']['errors'] == []
    assert setup.list_current('ModelRun') == []


def test_budget_default_configured_increase_and_exhaustion(setup, monkeypatch):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    config = load_model_provider_config()
    assert config.weekly_call_limit == 200
    raised = type(config).model_validate({**config.model_dump(), 'weekly_call_limit': 500})
    assert raised.weekly_call_limit == 500
    one = type(config).model_validate({**config.model_dump(), 'weekly_call_limit': 1})
    calls = []
    runner = SkillRunner(setup, config=one, provider=provider(lambda *a, **k: calls.append(1) or response()))
    assert run(runner)['status'] == 'VALIDATED_DRAFT'
    exhausted = run(runner, key='two')
    assert exhausted['status'] == 'NON_AI_TEMPLATE'
    assert exhausted['provider_metadata']['error_class'] == 'ModelRunBudgetExceeded'
    assert len(calls) == 1


def test_stale_and_input_drift_idempotency(setup):
    runner = SkillRunner(setup)
    result = run(runner)
    setup.update('s', {'geometry_sha256': 'sha256:' + 'b' * 64}, expected_revision=1, actor='TEST_HARNESS')
    assert runner.get('s', 'S8', result['run_id'])['status'] == 'STALE'
    with pytest.raises(SkillConflict, match='IDEMPOTENCY_INPUT_DRIFT'):
        run(runner)


def test_api_jobs_identity_and_no_scenario_state_change(setup):
    client = TestClient(create_workspace_app(store=setup, scenario_artifact_root=Path(setup.database).parent / 'scenario-artifacts'))
    posted = client.post('/api/v1/scenarios/s/skills/S8/runs', json={'idempotency_key': 'api-one'})
    assert posted.status_code == 202, posted.text
    url = '/api/v1/scenarios/s/skills/S8/runs/' + posted.json()['run_id']
    fetched = client.get(url)
    assert fetched.status_code == 200
    assert fetched.json()['status'] == 'NON_AI_TEMPLATE'
    assert client.get(url.replace('/S8/', '/S7/')).status_code == 404
    assert client.post('/api/v1/scenarios/s/skills/S1/runs', json={'idempotency_key': 'no'}).status_code == 422
    assert client.post('/api/v1/scenarios/missing/skills/S8/runs', json={'idempotency_key': 'no'}).status_code == 404
    assert setup.current('s').revision == 1
    assert setup.list_current('HumanDecision') == []


def test_validator_supplied_card_scope_tolerance_and_hard_sources(knowledge):
    cards = knowledge.cards_for('S8')
    metrics = {'h': {'value': 20, 'unit': 'm'}}
    raw = response(numeric_claims=[{'metric_id': 'h', 'value': 20.0000001, 'unit': 'm'}])
    assert validate(raw, skill_id='S8', cards=cards, library=knowledge.library, metrics=metrics)[1] == []
    assert 'UNSUPPORTED_NUMBER' in validate(raw, skill_id='S8', cards=cards, library=knowledge.library, metrics=metrics, tolerance=0)[1]
    candidate = next(c for c in cards if c.id == 'CTX-001')
    hard = candidate.model_copy(update={'enforcement': 'PROJECT_GUARDRAIL'})
    library = dict(knowledge.library)
    lid = candidate.sources[0].library_id
    library[lid] = library[lid].model_copy(update={'verification': library[lid].verification.model_copy(update={'status': 'NOT_FOUND'})})
    assert 'HARD_CARD_UNVERIFIED_SOURCE' in validate(response(), skill_id='S8', cards=[hard], library=library, metrics={})[1]
    other = next(c for c in knowledge.cards if c.id not in {c.id for c in cards})
    assert 'CARD_NOT_SUPPLIED' in validate(response(cards=(other.id,)), skill_id='S8', cards=cards, library=knowledge.library, metrics={})[1]


@pytest.mark.parametrize('patch', [{'model': 'gpt-6.1-sol'}, {'reasoning_effort': None}, {'reasoning_effort': 'low'}])
def test_codex_profile_requires_luna_max(patch):
    profile = next(p for p in load_model_provider_config().profiles if p.id == 'codex-cli')
    with pytest.raises(ValidationError):
        ModelProviderProfile.model_validate({**profile.model_dump(), **patch})


def test_cli_bounded_process_timeout_and_output_limit(tmp_path):
    import sys
    p = provider(lambda *args, **kwargs: '')
    p.timeout_seconds = .15
    options = {'cwd': str(tmp_path), 'env': {'PATH': '/usr/bin:/bin'}}
    with pytest.raises(OutcomeUnknown, match='timeout'):
        p._execute([sys.executable, '-c', 'import time; time.sleep(2)'], options)
    p.timeout_seconds = 2
    p.max_output_bytes = 1024
    with pytest.raises(OutcomeUnknown, match='output exceeded'):
        p._execute([sys.executable, '-c', 'print("x" * 4096)'], options)
    assert p._execute([sys.executable, '-c', 'import sys; print(repr(sys.stdin.read()))'], options) == "''\n"


def test_codex_jsonl_final_message_ignores_reasoning_events(setup, monkeypatch):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    events = '\n'.join([json.dumps({'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'private-never-store'}}),
                        json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': response()}})])
    result = run(SkillRunner(setup, provider=provider(lambda *a, **k: events)))
    assert result['status'] == 'VALIDATED_DRAFT'
    assert 'private-never-store' not in json.dumps(result)


def test_missing_executable_template_and_pre_dispatch_failure_accounting(setup, monkeypatch):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    from urban_design.model_provider import NoRequestDispatched
    p = provider(lambda *a, **k: (_ for _ in ()).throw(NoRequestDispatched('proved no launch')))
    result = run(SkillRunner(setup, provider=p))
    assert result['status'] == 'NON_AI_TEMPLATE'
    assert result['provider_metadata']['delivery'] == 'not_dispatched'
    assert setup.list_current('ModelRun')[0].payload['status'] == 'MODEL_FAILED'
    monkeypatch.setattr('urban_design.skills.provider.resolve_cli_executable', lambda command: None)
    second = run(SkillRunner(setup), key='missing-cli')
    assert second['status'] == 'NON_AI_TEMPLATE'
    assert len(setup.list_current('ModelRun')) == 1


def test_artifact_tamper_rejected_and_raw_file_preserved(setup):
    runner = SkillRunner(setup)
    result = run(runner)
    artifact = setup.current(result['artifact_id'])
    Path(artifact.payload['uri']).write_text('{tampered')
    with pytest.raises(SkillConflict, match='ARTIFACT_HASH_MISMATCH'):
        runner.get('s', 'S8', result['run_id'])


def test_authoritative_scenario_copy_api(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.delenv('PROJECT_AI_AUTHORIZED', raising=False)
    source = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')
    target = tmp_path / '.urban_design_runtime/state.sqlite3'
    target.parent.mkdir()
    from scripts.skills_smoke import backup_database
    before = backup_database(source, target)
    copy = ProjectStateStore(target)
    try:
        scenario = copy.list_current('Scenario')[0]
        client = TestClient(create_workspace_app(store=copy, scenario_artifact_root=target.parent / 'scenario-artifacts'))
        baseline = len(copy.list_current('HumanDecision'))
        for stage in ('S3', 'S7', 'S8'):
            base = f'/api/v1/scenarios/{scenario.entity_id}/skills/{stage}/runs'
            posted = client.post(base, json={'idempotency_key': 'copy-' + stage})
            assert posted.status_code == 202, posted.text
            fetched = client.get(base + '/' + posted.json()['run_id'])
            assert fetched.status_code == 200
            assert fetched.json()['status'] == 'NON_AI_TEMPLATE'
            assert fetched.json()['validation']['errors'] == []
        assert copy.current(scenario.entity_id).revision == scenario.revision
        assert len(copy.list_current('HumanDecision')) == baseline
    finally:
        copy.close()
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as origin:
        assert origin.execute('SELECT count(*), max(sequence) FROM ledger_events').fetchone() == before


def test_budget_reservations_across_connections(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from urban_design.model_provider import CriticRequest, ModelRunBudgetExceeded, ProjectStateModelRunAccounting
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    other = ProjectStateStore(setup.database)
    try:
        p = provider(lambda *args, **kwargs: response())
        accounts = [ProjectStateModelRunAccounting(store, 'p') for store in (setup, other)]
        def reserve(account):
            try:
                return account.start(profile_id='codex-cli', provider=p, request=CriticRequest(study_area_id='s'), weekly_call_limit=1)
            except ModelRunBudgetExceeded:
                return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, accounts))
        assert results.count('blocked') == 1
        assert len(setup.list_current('ModelRun')) == 1
    finally:
        other.close()


def test_invalid_hard_check_is_preserved_and_cannot_be_overclaimed(setup, monkeypatch):
    record = setup.current('s')
    setup.update('s', {'parameters': {**record.payload['parameters'], 'validation': {'valid': False, 'failure_reasons': ['collision']}}},
                 expected_revision=1, actor='TEST_HARNESS')
    assert run(SkillRunner(setup))['output']['status'] == 'INVALID'
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    result = run(SkillRunner(setup, provider=provider(lambda *a, **k: response())), key='ai-invalid')
    assert result['status'] == 'REJECTED_BY_VALIDATOR'
    assert 'HARD_CHECK_STATUS_CONFLICT' in result['validation']['errors']


def test_formal_scalar_metrics_use_explicit_unit_contract(setup):
    record = setup.current('s')
    setup.update('s', {'parameters': {'metrics': {'far': .5, 'highest_new_height_m': 14,
                 'unidentified': 7, 'program_gfa_m2': {'Office': 2000}}}}, expected_revision=1, actor='TEST_HARNESS')
    runner = SkillRunner(setup)
    metrics = runner._metrics(runner._snapshot('s'))
    assert metrics['scenario.metrics.far']['unit'] == 'ratio'
    assert metrics['scenario.metrics.highest_new_height_m']['value'] == 14
    assert metrics['scenario.metrics.program_gfa_m2.Office']['unit'] == 'm2'
    assert 'scenario.metrics.unidentified' not in metrics


@pytest.mark.parametrize('stage', ['S3', 'S7'])
def test_fake_strategy_and_critique_stage_contracts(setup, monkeypatch, stage):
    monkeypatch.setenv('PROJECT_AI_AUTHORIZED', '1')
    runner = SkillRunner(setup)
    raw = runner._template(stage, ['CTX-001']).model_dump()
    raw['status'] = 'DRAFT'
    p = provider(lambda *a, **k: json.dumps(raw, ensure_ascii=False))
    result = run(SkillRunner(setup, provider=p), stage=stage)
    assert result['status'] == 'VALIDATED_DRAFT'
    assert result['validation']['errors'] == []


def test_inline_unknown_reference_and_external_title(knowledge):
    for raw in (response(rationale_zh='依據 ZZZ-999 的原則。'),
                response(rationale_zh='根據《庫外新書》的研究指出入口須集中。')):
        assert validate(raw, skill_id='S8', cards=knowledge.cards_for('S8'), library=knowledge.library, metrics={})[1]


def test_budget_rechecks_clock_after_lock_acquisition(setup):
    from datetime import timedelta
    from urban_design.model_provider import CriticRequest, ModelRunBudgetExceeded, ProjectStateModelRunAccounting
    from urban_design.skills.runner import utc_now
    now = utc_now()
    setup.create('ModelRun', {'id': 'concurrent-reservation', 'provider': 'codex-cli', 'model_id': 'gpt-6-luna',
        'project_id': 'p', 'status': 'PENDING', 'prompt_hash': 'a' * 64,
        'schema_version': 'test', 'created_at': now.isoformat()},
        entity_id='concurrent-reservation', project_id='p', actor='TEST_HARNESS')
    # A pending contender took its preliminary timestamp before another reservation
    # committed. Its timestamp after acquiring the lock must count that reservation.
    clocks = iter([now - timedelta(seconds=1), now + timedelta(seconds=1)])
    account = ProjectStateModelRunAccounting(setup, 'p', now_factory=lambda: next(clocks))
    with pytest.raises(ModelRunBudgetExceeded):
        account.start(profile_id='codex-cli', provider=provider(lambda *a, **k: ''),
                      request=CriticRequest(study_area_id='s'), weekly_call_limit=1)
    assert len(setup.list_current('ModelRun')) == 1
