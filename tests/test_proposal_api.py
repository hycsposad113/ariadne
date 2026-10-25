from types import SimpleNamespace
import copy
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.judgement.proposal_comparison import proposal_comparison
from urban_design.judgement.proposal_router import create_proposal_router, design_dialogue, project_dialogue_response
from urban_design.judgement.proposal_service import ProposalConflict


class Judgements:
    database = 'unused-test-path'
    provider_factory = None
    def list(self, project, **kwargs):
        return {'cards': [self.get(project, 'card-2'), self.get(project, 'card-1')]}
    def get(self, project, ident):
        revision = 1 if ident == 'card-1' else 2
        return {'id': ident, 'created_at': f'2026-10-17T00:00:0{revision}+00:00',
                'status': 'VALIDATED', 'round': revision,
                'subject': {'ids': ['harbour_grain' if revision == 1 else 'harbour_grain@draft-r2']},
                'metrics': {'e1.harbour.all.winter.mean_h': {'value': 2.155}},
                'responses': [{'id': 'response-1', 'created_at': '2026-10-17T00:00:01.1+00:00',
                               'kind': 'supplement', 'text': '保持街牆'}] if revision == 1 else []}


class Proposals:
    def __init__(self, *args, **kwargs): pass
    def get(self, project, ident):
        if project != 'p' or ident != 'proposal-1': raise KeyError(ident)
        return copy.deepcopy({'id': ident, 'card_id': 'card-1', 'created_at': '2026-10-17T00:00:01.2+00:00',
                'status': 'VALIDATED', 'approval': {'created_at': '2026-10-17T00:00:01.3+00:00', 'is_human_decision': False},
                'job': {'id': 'job-1', 'created_at': '2026-10-17T00:00:01.4+00:00',
                        'status': 'SUCCEEDED', 'judgement_id': 'card-2'},
                'input_bundle': {'editable_buildings': [{'building_id': 'b-1', 'floors': [{'geometry': {'type': 'Polygon'}}]}]},
                'attempts': [{'attempt': 1, 'raw_json': {'large': 'provider trace'}}],
                'dry_run': {'affected_building_ids': ['b-1'],
                            'editable_buildings': [{'building_id': 'b-1', 'block_id': 'block-1',
                                                    'floors': [{'geometry': {'type': 'Polygon'}}]}]}})
    def create(self, project, body): return self.get(project, 'proposal-1') | {'force': body.force}
    def list(self, project, card_id=None, **kwargs): return {'proposals': [self.get(project, 'proposal-1')]}
    def approve(self, project, ident, body):
        if ident == 'stale': raise ProposalConflict('stale revision; re-propose')
        return self.get(project, ident)
    def inputs(self, project, ident): return self.get(project, ident)['input_bundle']
    def reconcile(self, project, ident, body): return {'resolution': body.resolution}


def client():
    app = FastAPI()
    app.include_router(create_proposal_router(project_store=SimpleNamespace(),
                       judgement_service_factory=Judgements, service_factory=Proposals))
    return TestClient(app, client=('127.0.0.1', 12000))


def test_proposal_api_contract_and_conflict():
    api = client(); base = '/api/v1/projects/p/ariadne/proposals'
    assert api.post(base, json={'card_id': 'card-1', 'language': 'en', 'force': True}).json()['force']
    assert api.post(base + '/proposal-1/approve', json={}).json()['approval']['is_human_decision'] is False
    assert api.post(base + '/stale/approve', json={'note': 'rerun'}).status_code == 409
    assert api.get(base.replace('/p/', '/other/') + '/proposal-1').status_code == 404
    assert api.get(base + '/proposal-1?language=en').json()['requested_language'] == 'en'
    assert api.get(base + '?card_id=card-1').status_code == 200


def test_proposal_reconciliation_locality():
    api = client(); url = '/api/v1/projects/p/ariadne/proposals/proposal-1/reconcile'
    body = {'resolution': 'NOT_DELIVERED', 'note': 'Verified process receipt'}
    assert api.post(url, json=body).status_code == 200
    api.app.state.testing = True
    assert TestClient(api.app, client=('192.0.2.1', 12000)).post(url, json=body).status_code == 403


def test_dialogue_keeps_agent_responses_distinct_from_designer_responses():
    class AgentResponseJudgements(Judgements):
        def get(self, project, ident):
            result = super().get(project, ident)
            if ident == 'card-1':
                result['responses'] = [{
                    'id': 'agent-response-1',
                    'judgement_id': ident,
                    'kind': 'supplement',
                    'text': 'Please check the evidence coverage.',
                    'language': 'en',
                    'actor_kind': 'AGENT',
                    'actor_id': 'agent-ariadne',
                    'created_at': '2026-10-17T00:00:01.1+00:00',
                    'is_human_decision': False,
                }]
            return result

    result = design_dialogue(AgentResponseJudgements(), Proposals(), 'p', 'harbour_grain')
    event = next(item for item in result['events'] if item['id'] == 'agent-response-1')
    assert event['kind'] == 'agent_response'
    assert event['actor_kind'] == 'AGENT'
    assert event['is_human_decision'] is False


def test_proposal_http_projections_hide_private_payloads_and_expose_audit_inputs():
    api = client()
    base = '/api/v1/projects/p/ariadne/proposals'
    payloads = [api.get(base).json()['proposals'][0], api.get(base + '/proposal-1').json(),
                api.post(base, json={'card_id': 'card-1'}).json(),
                api.post(base + '/proposal-1/approve', json={}).json()]

    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for payload in payloads:
        nested = list(walk(payload))
        assert all('input_bundle' not in item for item in nested)
        assert all('raw_json' not in item for item in nested)
        assert all('editable_buildings' not in item for item in nested)
        assert payload['dry_run']['affected_buildings'] == [
            {'building_id': 'b-1', 'block_id': 'block-1', 'floors_after': 1,
             'footprint': {'type': 'Polygon'}}]
    audit = api.get(base + '/proposal-1/inputs')
    assert audit.status_code == 200
    assert audit.json()['editable_buildings'][0]['building_id'] == 'b-1'


def test_dialogue_projection_removes_large_diagnostics_and_stays_below_200kb():
    raw = {'subject': 'harbour_grain', 'is_human_decision': False, 'events': []}
    for index in range(2):
        raw['events'].append({'kind': 'judgement', 'judgement': {
            'id': f'card-{index}', 'status': 'VALIDATED', 'metrics': {'payload': 'm' * 300_000},
            'inputs': ['i' * 300_000], 'sources': {'payload': 's' * 300_000},
            'knowledge_units': ['k' * 300_000], 'card_json': {'payload': 'c' * 300_000},
            'attempts': [{'raw_json': 'a' * 300_000}],
        }})
    raw['events'].append({'kind': 'proposal', 'proposal': {
        'id': 'proposal-large', 'status': 'VALIDATED', 'input_bundle': {'payload': 'b' * 3_000_000},
        'attempts': [{'raw_json': 'r' * 3_000_000}],
        'dry_run': {'affected_building_ids': ['b-1'], 'editable_buildings': [
            {'building_id': 'b-1', 'block_id': 'block', 'floors': [{'geometry': {'type': 'Polygon'}}]}]},
    }})
    before = len(json.dumps(raw, ensure_ascii=False, separators=(',', ':')).encode())
    result = project_dialogue_response(raw)
    encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
    assert before == 9_600_776
    assert len(encoded) == 452
    assert len(encoded) < 200_000
    judgement = next(event['judgement'] for event in result['events'] if event['kind'] == 'judgement')
    assert not {'metrics', 'inputs', 'sources', 'knowledge_units', 'card_json', 'attempts'} & judgement.keys()


def test_proposal_dialogue_keeps_new_revision_and_orders_events():
    result = design_dialogue(Judgements(), Proposals(), 'p', 'harbour_grain')
    assert [event['kind'] for event in result['events']] == [
        'judgement', 'designer_response', 'proposal', 'approval', 'rerun', 'judgement']
    rerun = next(event for event in result['events'] if event['kind'] == 'rerun')
    assert rerun['post_judgement_id'] == 'card-2'
    assert result['events'][-1]['round'] == 2
    assert client().get('/api/v1/projects/p/ariadne/dialogue?subject=harbour_grain').status_code == 200
    assert client().get('/api/v1/projects/p/ariadne/dialogue?subject=harbour_grain&language=en').json()['requested_language'] == 'en'


def test_proposal_comparison_missing_values_are_not_zero(tmp_path):
    proposal = {'id': 'proposal-1', 'card_id': 'card-1', 'project_id': 'p', 'job': None,
                'dry_run': {'gfa_before_m2': 125000, 'gfa_after_m2': 120000, 'below_gfa_floor': True,
                            'affected_building_ids': ['a', 'b']}}
    result = proposal_comparison(proposal, Judgements(), None, tmp_path)
    assert result['all_winter_mean_h']['before'] == 2.155
    assert result['all_winter_mean_h']['after'] is None
    assert result['courtyard_winter_mean_h']['before'] is None
    assert result['gfa_m2']['before_meets_floor'] and not result['gfa_m2']['after_meets_floor']
    assert result['affected_building_count'] == 2
