"""Offline contract and relationship tests; not source or design certification."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError
from urban_design.knowledge import DesignKnowledge, RuleCard, SkillSpec, load_knowledge

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def knowledge():
    return load_knowledge(ROOT)


def test_all_cards_and_eight_skills_load(knowledge):
    assert len(knowledge.cards) == 93
    assert len({c.id for c in knowledge.cards}) == len(knowledge.cards)
    assert {s.stage for s in knowledge.skills} == {f'S{i}' for i in range(1, 9)}
    assert {c.domain for c in knowledge.cards} == {'space_syntax','morphology','mobility','public_space','context_response','land_use','policy','portfolio'}
    ids = {c.id for c in knowledge.cards}
    for s in knowledge.skills:
        assert set(s.card_ids) <= ids
        assert all(s.stage in next(c.stages for c in knowledge.cards if c.id == cid) for cid in s.card_ids)


def test_verified_library_relationships_and_independence(knowledge):
    assert len(knowledge.library) == 60
    for c in knowledge.cards:
        entries = [knowledge.library[s.library_id] for s in c.sources]
        assert any(e.kind in ('ACADEMIC_PAPER', 'ACADEMIC_BOOK') for e in entries)
        assert all(s.claim_id in {claim.claim_id for claim in knowledge.library[s.library_id].claims} for s in c.sources)
        assert c.debates_zh and c.context_validity_zh and c.parameters
        eligible=[e for e in entries if e.verification.status=='VERIFIED' and e.kind!='PORTFOLIO']
        assert c.source_count_flag == 'MULTI_SOURCE'
        assert any(set(x.authors).isdisjoint(y.authors) for i,x in enumerate(eligible) for y in eligible[i+1:])
        assert len(c.design_responses) >= 2
        if c.enforcement != 'CANDIDATE_ONLY':
            assert all(e.verification.status == 'VERIFIED' for e in entries)
            assert c.source_count_flag == 'MULTI_SOURCE'
            assert any(set(x.authors).isdisjoint(y.authors) for i,x in enumerate(entries) for y in entries[i+1:])
        assert all(s.library_id not in ('FOUNDER','PORTFOLIO','M4H') for s in c.sources)
    refs = {s.library_id for c in knowledge.cards for s in c.sources}
    assert {'RATTI04','HILLIERPENN04','PORTA06','CONZEN60','CANIGGIA','SPACEMATRIX10','NG10','WHYTE80','LYNCH60','EWING10','PUCHER08','BRAZIL14','BOGOTA17','AZI23'} <= refs
    assert all(c.evidence_level == 'PORTFOLIO' for c in knowledge.cards if c.domain == 'portfolio')


def test_assumptions_stay_proposed_and_guards_have_authority(knowledge):
    for c in knowledge.cards:
        for p in c.parameters:
            if p.provenance == 'ASSUMED_COMMANDER':
                assert p.status == 'PROPOSED_PENDING_FOUNDER'
        if c.enforcement == 'PROJECT_GUARDRAIL':
            assert c.authority_ref
            assert 'FOUNDER' in c.local_context_refs
        if c.check is not None:
            assert c.check.implementation_status == 'SPECIFICATION_ONLY'


def test_default_root_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert len(load_knowledge().cards) == 93


def test_stage_domain_query(knowledge):
    actual = knowledge.cards_for('S5','space_syntax')
    assert actual and all(c.domain == 'space_syntax' and 'S5' in c.stages for c in actual)
    assert knowledge.cards_for('S1','morphology') == ()


def test_conditions_are_and_keys_or_values_and_fail_closed(knowledge):
    ids = lambda conditions: {c.id for c in knowledge.cards_for('S4','mobility',conditions)}
    assert 'MOB-002' not in ids({})
    assert 'MOB-002' not in ids({'setting':'park'})
    assert 'MOB-002' in ids({'setting':'park','mode':['pedestrian','bicycle']})
    assert 'MOB-002' not in ids({'setting':'park','mode':'motor_vehicle'})
    assert 'MOB-007' in ids({'land_use':'mixed','scale':'small_medium'})
    assert 'MOB-007' not in ids({'land_use':'housing','scale':'small_medium'})
    assert 'MOB-001' in ids({})  # universal guardrail
    assert 'POR-005' in {c.id for c in knowledge.cards_for('S6','portfolio',{'strategy':'green_corridor','mode':'bicycle'})}


@pytest.mark.parametrize('kwargs',[{'stage':'S9'}, {'stage':'S2','domain':'invented'}, {'stage':'S2','conditions':{'unknown':'x'}}, {'stage':'S2','conditions':{'mode':[]}}, {'stage':'S2','conditions':{'mode':1}}])
def test_invalid_query_rejected(knowledge,kwargs):
    with pytest.raises(ValueError): knowledge.cards_for(**kwargs)


@pytest.fixture
def card(knowledge):
    return deepcopy(knowledge.cards[0].model_dump(mode='json'))


def test_missing_sources_rejected(card):
    card['sources'] = []
    with pytest.raises(ValidationError): RuleCard.model_validate(card)


@pytest.mark.parametrize('mutation', ['dangling_response','dangling_parameter','unlabelled_assumption','hard_single_source','bad_range','bool_number','source_verified','missing_null_reason','unknown_field'])
def test_invalid_card_relationships_rejected(card,mutation):
    if mutation == 'dangling_response': card['design_responses'][0]['source_ids']=['MISSING']
    elif mutation == 'dangling_parameter':
        card['parameters']=[dict(name='x',value=1,range=None,unit='m',provenance='ASSUMED_COMMANDER',source_ids=['MISSING'],status='PROPOSED_PENDING_FOUNDER',rationale_zh='草案')]
    elif mutation == 'unlabelled_assumption':
        card['parameters']=[dict(name='x',value=1,range=None,unit='m',provenance='ASSUMED_COMMANDER',source_ids=[card['sources'][0]['library_id']],status='PROJECT_INSTRUCTION',rationale_zh='草案')]
    elif mutation == 'hard_single_source':
        card['sources']=card['sources'][:1]; card['source_count_flag']='SINGLE_SOURCE'; card['enforcement']='PROJECT_GUARDRAIL'; card['authority_ref']='asserted'
    elif mutation in ('bad_range','bool_number'):
        card['parameters']=[dict(name='x',value=True if mutation=='bool_number' else None,range=[2,1] if mutation=='bad_range' else None,unit='m',provenance='SOURCE',source_ids=[card['sources'][0]['library_id']],status='CONTEXT_TO_VERIFY',rationale_zh='草案')]
    elif mutation == 'source_verified': card['sources'][0]['verification_status']='VERIFIED'
    elif mutation == 'missing_null_reason': card['check']=None; card['check_unavailable_reason_zh']=None
    elif mutation == 'unknown_field': card['approved']=True
    with pytest.raises(ValidationError): RuleCard.model_validate(card)


def test_single_source_can_only_remain_candidate(card):
    src=card['sources'][0]['library_id']
    card['sources']=card['sources'][:1]
    card['source_count_flag']='SINGLE_SOURCE'
    card['parameters']=[]
    for r in card['design_responses']: r['source_ids']=[src]
    assert RuleCard.model_validate(card).enforcement == 'CANDIDATE_ONLY'


@pytest.mark.parametrize('stage',['S6','S7','S8'])
def test_design_rationale_required_in_late_skills(knowledge,stage):
    spec=next(s for s in knowledge.skills if s.stage==stage).model_dump()
    for field in ['design_intent_zh','rationale_zh','rule_card_ids']:
        bad=deepcopy(spec); bad['output_fields'].pop(field)
        with pytest.raises(ValidationError): SkillSpec.model_validate(bad)
    spec['requires_design_rationale']=False
    with pytest.raises(ValidationError): SkillSpec.model_validate(spec)


def copy_catalog(tmp_path):
    shutil.copytree(ROOT/'knowledge',tmp_path/'knowledge')
    # Only code is copied as read-only input references; no DB or keys.
    shutil.copytree(ROOT/'src/urban_design',tmp_path/'src/urban_design',ignore=shutil.ignore_patterns('__pycache__'))
    return tmp_path


def test_duplicate_card_rejected(tmp_path):
    root=copy_catalog(tmp_path)
    original=next((root/'knowledge/design_rules/cards').glob('*.json'))
    (original.parent/'duplicate.json').write_text(original.read_text())
    with pytest.raises(ValueError,match='duplicate card'): DesignKnowledge(root)


def test_missing_skill_reference_rejected(tmp_path):
    root=copy_catalog(tmp_path)
    skill=next((root/'knowledge/skills').glob('S6-*.md'))
    skill.write_text(skill.read_text().replace('MOR-001','BAD-999'))
    with pytest.raises(ValueError,match='missing card'): DesignKnowledge(root)


def test_schema_drift_rejected(tmp_path):
    root=copy_catalog(tmp_path)
    schema=root/'knowledge/design_rules/schema.json'
    data=json.loads(schema.read_text()); data['title']='OtherContract'
    schema.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='schema.json'): DesignKnowledge(root)


@pytest.mark.parametrize('mutation', ['missing_library','missing_claim','unverified_hard','overlapping_authors','no_academic','dangling_critique','duplicate_library'])
def test_library_fail_closed(tmp_path, mutation):
    root = copy_catalog(tmp_path)
    hard_path = root/'knowledge/design_rules/cards/MOB-001.json'
    card = json.loads(hard_path.read_text())
    entry_path = root/'knowledge/library'/f"{card['sources'][0]['library_id']}.json"
    entry = json.loads(entry_path.read_text())
    if mutation == 'missing_library': card['sources'][0]['library_id'] = 'MISSING'
    elif mutation == 'missing_claim': card['sources'][0]['claim_id'] = 'MISSING'
    elif mutation == 'unverified_hard': entry['verification']['status'] = 'AMBIGUOUS'
    elif mutation == 'overlapping_authors':
        for ref in card['sources']:
            path=root/'knowledge/library'/f"{ref['library_id']}.json"
            data=json.loads(path.read_text()); data['authors']=['Same Author']; path.write_text(json.dumps(data))
        entry['authors']=['Same Author']
    elif mutation == 'no_academic':
        for ref in card['sources']:
            path=root/'knowledge/library'/f"{ref['library_id']}.json"
            data=json.loads(path.read_text());data['kind']='PRACTICE_MANUAL';path.write_text(json.dumps(data))
        entry['kind']='PRACTICE_MANUAL'
    elif mutation == 'dangling_critique': entry['known_critiques']=['MISSING']
    elif mutation == 'duplicate_library': (entry_path.parent/'duplicate.json').write_text(entry_path.read_text())
    hard_path.write_text(json.dumps(card)); entry_path.write_text(json.dumps(entry))
    with pytest.raises(ValueError): DesignKnowledge(root)


def test_author_statistics_actual_denominators_and_target(knowledge):
    from collections import Counter
    stats=knowledge.author_statistics()
    entries=[e for e in knowledge.library.values() if e.verification.status=='VERIFIED' and e.kind!='PORTFOLIO']
    usage=[knowledge.library[s.library_id] for c in knowledge.cards for s in c.sources if knowledge.library[s.library_id].verification.status=='VERIFIED' and knowledge.library[s.library_id].kind!='PORTFOLIO']
    assert stats['catalogue_denominator']==len(entries)==58
    assert stats['citation_denominator']==len(usage)
    for name, dataset, denominator in [('catalogue',entries,len(entries)),('citations',usage,len(usage))]:
        expected=Counter(a for e in dataset for a in set(e.authors))
        assert {row['author']:row['count'] for row in stats[name]}==dict(expected)
        assert all(row['share']==pytest.approx(row['count']/denominator) for row in stats[name])
        assert max(row['share'] for row in stats[name]) <= 0.10
    # Author presence is full counting; percentages across all authors need not sum to 100%.
    assert 'Founder' not in {row['author'] for row in stats['catalogue']}


def test_traditional_phrase_scan_and_legal_characters():
    import re
    banned=('乾擾','限製','控製','管製','強製','製定','髮展','髮生','裡程','鍾頭','關系','输入','输出','状態','必须','哪里','资料','已注册')
    paths=list((ROOT/'knowledge').rglob('*.json'))+list((ROOT/'knowledge/skills').glob('*.md'))
    for p in paths:
        assert not any(word in p.read_text() for word in banned), str(p)
    # Preserve semantically valid characters rather than globally changing them.
    text='製造／干擾／乾燥／之後／裡面／頭髮／一隻／只有／鐘聲／於是／範圍／關係／系統'
    assert not any(word in text for word in banned)


def test_api_evidence_contains_no_abstract_and_only_allowed_urls(knowledge):
    from urllib.parse import urlparse
    rows=[json.loads(line) for line in (ROOT/'artifacts/j8-knowledge-verify/verification-log.jsonl').read_text().splitlines()]
    allowed={'api.openalex.org','api.crossref.org','openlibrary.org'}
    for row in rows:
        assert urlparse(row['url']).hostname in allowed
        assert urlparse(row['url']).scheme=='https'
        assert 'mailto' not in row['url'].lower()
        assert 'abstract_inverted_index' not in row and 'abstract' not in row
        for candidate in row.get('candidates',[]):
            assert 'abstract' not in candidate and 'abstract_inverted_index' not in candidate
    for e in knowledge.library.values():
        assert any(row.get('matched_record_id')==e.verification.matched_record_id and row['source_id']==e.id and row['status']==e.verification.status for row in rows)


def test_s2_required_coverage_and_matrix(knowledge):
    matrix=json.loads((ROOT/'knowledge/coverage-matrix.json').read_text())
    assert set(matrix['stages'])=={f'S{i}' for i in range(1,9)}
    domains={c.domain for c in knowledge.cards}
    for stage,cells in matrix['stages'].items():
        assert set(cells)==domains
        for domain,cell in cells.items():
            expected=sorted(c.id for c in knowledge.cards_for(stage,domain))
            assert cell['card_ids']==expected
            if not expected: assert cell['reason_zh']
            if cell['relevant']: assert expected
    s2=next(s for s in knowledge.skills if s.stage=='S2')
    assert {'transit_accessibility','surrounding_functions','flow_hypotheses','directional_interfaces'} <= s2.output_fields.keys()
    assert {'MOB-012','MOB-013','LAN-003','LAN-004','LAN-005','LAN-006'} <= set(s2.card_ids)


def test_offline_loader_does_not_use_network(monkeypatch):
    import socket
    def reject(*args, **kwargs): raise AssertionError('runtime network forbidden')
    monkeypatch.setattr(socket,'socket',reject)
    assert len(load_knowledge(ROOT).cards)==93
