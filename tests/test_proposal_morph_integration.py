"""P4a integration uses only temporary stores and deterministic providers."""
import copy
from types import SimpleNamespace

import pytest

from urban_design.judgement.proposal_service import (
    ProposalRequest, build_revision_context, format_operation_text,
)
from urban_design.judgement.proposal_router import project_proposal_response
from urban_design.judgement.revision_inputs import _RevisionContext
from test_proposal_service import setup


def test_validated_morph_card_can_seed_proposal(tmp_path, monkeypatch):
    service, provider, draft_id, _ = setup(tmp_path, monkeypatch)
    old_get = service.judgements.get

    def morphology(project, ident):
        card = old_get(project, ident)
        card['skill_id'] = 'J-MORPH'
        return card

    service.judgements.get = morphology
    result = service.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=draft_id))
    assert result['status'] == 'VALIDATED', result
    assert provider.calls == 1
    assert {'seed-courtyard_role', 'seed-season_priority'} <= {r['id'] for r in result['input_bundle']['responses']}
    assert service.store.current(draft_id).revision == 1


@pytest.mark.parametrize(('operation', 'zh', 'en'), [
    ({'op': 'SOLAR_ENVELOPE', 'courtyard_ids': ['courtyard-0', 'courtyard-1'],
      'target': 'north_edge', 'redistribute': True},
     'courtyard-0、courtyard-1 南側日照包絡（到北緣），樓地板移到北側',
     'courtyard-0, courtyard-1: south-side solar envelope (to north edge), redistribute floor area to the north'),
    ({'op': 'SOLAR_ENVELOPE', 'courtyard_ids': ['courtyard-0'],
      'target': 'half_depth', 'redistribute': False},
     'courtyard-0 南側日照包絡（到一半淨深），不移入樓地板',
     'courtyard-0: south-side solar envelope (to half depth), no floor-area redistribution'),
    ({'op': 'COURTYARD_WING_DEPTH', 'courtyard_id': 'courtyard-0', 'side': 'south', 'depth_m': 10},
     'courtyard-0 南側住宅翼進深縮至 10 公尺（所有樓層）',
     'courtyard-0: reduce south wing depth to 10 m (all floors)'),
])
def test_strategy_operation_text(operation, zh, en):
    assert format_operation_text(operation, 'zh-TW') == zh
    assert format_operation_text(operation, 'en') == en


def test_revision_strategy_text_uses_measured_dry_run_and_preserves_report():
    operation = {'op': 'SOLAR_ENVELOPE', 'courtyard_ids': ['courtyard-0', 'courtyard-1'],
                 'target': 'north_edge', 'redistribute': True}
    report = [{'op': 'SOLAR_ENVELOPE', 'operation_index': 0,
               'removed_gfa_m2': 7616.25, 'added_gfa_m2': 7500, 'gfa_shortfall_m2': 116.25}]
    proposal = {'id': 'proposal-test', 'card_id': 'card-test',
                'proposal': {'summary': '測試日照包絡。', 'operations': [operation]},
                'dry_run': {'gfa_before_m2': 138617, 'gfa_after_m2': 138500.75,
                            'affected_building_ids': ['south', 'north'], 'strategy_report': report}}
    card = {'id': 'card-test', 'round': 1, 'skill_id': 'J-MORPH'}
    context = build_revision_context(proposal, card, SimpleNamespace(seed={'stances': []}))
    assert '7,616.25 平方公尺' in context['operations_text_zh'][0]
    assert '7,500 平方公尺' in context['operations_text_zh'][0]
    assert '116.25 平方公尺' in context['operations_text_zh'][0]
    assert '7,616.25 m²' in context['operations_text_en'][0]
    assert context['dry_run']['strategy_report'] == report
    assert _RevisionContext.model_validate(context)
    projected = project_proposal_response(copy.deepcopy(proposal))
    assert projected['dry_run']['strategy_report'] == report


def test_strategy_fake_provider_strict_schema_and_compact_api(tmp_path, monkeypatch):
    from jsonschema import Draft202012Validator
    from test_proposal_strategies import bundle, proposal, envelope
    fixture = bundle()
    fixture['card_id'] = 'card-test'
    body = proposal([envelope()])
    body['responds_to']['card_id'] = 'card-test'
    service, provider, draft_id, _ = setup(tmp_path, monkeypatch, outputs=[body])
    record = service.store.current(draft_id)
    monkeypatch.setattr(service, '_bundle', lambda *_: (copy.deepcopy(fixture), record))
    generate = provider.generate_structured
    captured = []

    def capture(request):
        captured.append(request)
        return generate(request)

    provider.generate_structured = capture
    result = service.create('proj-formal', ProposalRequest(card_id='card-test', draft_id=draft_id))
    assert result['status'] == 'VALIDATED', result
    assert not list(Draft202012Validator(captured[0].response_schema).iter_errors(body))
    for branch in captured[0].response_schema['properties']['operations']['items']['anyOf']:
        assert branch['additionalProperties'] is False
        assert set(branch['required']) == set(branch['properties'])
    public = project_proposal_response(result)
    assert public['dry_run']['strategy_report'] == result['dry_run']['strategy_report']
    assert {b['building_id'] for b in public['dry_run']['affected_buildings']} == set(result['dry_run']['affected_building_ids'])
    assert 'editable_buildings' not in public['dry_run']


def test_strategy_text_describes_actual_non_north_receivers():
    operation = {'op': 'SOLAR_ENVELOPE', 'courtyard_ids': ['courtyard-0'],
                 'target': 'north_edge', 'redistribute': True}
    report = {'removed_gfa_m2': 520, 'added_gfa_m2': 260, 'gfa_shortfall_m2': 260,
              'added': [{'building_id': 'east', 'is_north_of_courtyard': False}]}
    assert '移到同街廓非南側棟' in format_operation_text(operation, 'zh-TW', report)
    assert 'to the non-south-side buildings in the same block' in format_operation_text(operation, 'en', report)
