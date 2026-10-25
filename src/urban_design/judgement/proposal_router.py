"""HTTP projection of proposal runs and the design dialogue (never decisions)."""

from copy import deepcopy
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from .service import ReconcileRequest


JUDGEMENT_DIALOGUE_PRIVATE_FIELDS = {
    'metrics', 'inputs', 'sources', 'knowledge_units', 'card_json', 'attempts',
}


def _remove_private_payloads(value):
    if isinstance(value, dict):
        return {key: _remove_private_payloads(child) for key, child in value.items()
                if key not in {'input_bundle', 'raw_json', 'courtyard_geometry_overrides'}}
    if isinstance(value, list):
        return [_remove_private_payloads(child) for child in value]
    return value


def project_proposal_response(value):
    """Hide audit/provider payloads and expose only affected footprints to normal clients."""
    projected = _remove_private_payloads(deepcopy(value))

    def project_dry_runs(item):
        if isinstance(item, dict):
            dry_run = item.get('dry_run')
            if isinstance(dry_run, dict):
                buildings = {str(b.get('building_id', b.get('id'))): b
                             for b in dry_run.pop('editable_buildings', [])}
                affected = []
                for ident in dry_run.get('affected_building_ids', []):
                    building = buildings.get(str(ident))
                    if not building:
                        continue
                    floors = building.get('floors', [])
                    first_floor = floors[0] if floors else {}
                    footprint = first_floor.get('geometry') if isinstance(first_floor, dict) else None
                    if isinstance(footprint, dict) and footprint.get('type') == 'Feature':
                        footprint = footprint.get('geometry')
                    affected.append({
                        'building_id': building.get('building_id', building.get('id')),
                        'block_id': building.get('block_id'),
                        'floors_after': len(floors) if isinstance(floors, list) else building.get('floors'),
                        'footprint': deepcopy(footprint),
                    })
                dry_run['affected_buildings'] = affected
            for child in item.values():
                project_dry_runs(child)
        elif isinstance(item, list):
            for child in item:
                project_dry_runs(child)

    project_dry_runs(projected)
    return projected


def project_dialogue_response(value):
    projected = deepcopy(value)
    for event in projected.get('events', []):
        if event.get('kind') == 'judgement' and isinstance(event.get('judgement'), dict):
            event['judgement'] = _remove_judgement_payload(event['judgement'])
        if event.get('kind') == 'proposal' and isinstance(event.get('proposal'), dict):
            event['proposal'] = project_proposal_response(event['proposal'])
        else:
            for key, child in list(event.items()):
                event[key] = _remove_private_payloads(child)
    return projected


def _remove_judgement_payload(value):
    if isinstance(value, dict):
        return {key: _remove_judgement_payload(child) for key, child in value.items()
                if key not in JUDGEMENT_DIALOGUE_PRIVATE_FIELDS}
    if isinstance(value, list):
        return [_remove_judgement_payload(child) for child in value]
    return value


def create_proposal_router(*, project_store, judgement_service_factory, service_factory=None):
    from .proposal_service import ApprovalRequest, ProposalRequest, ProposalService, RerunRequest

    router = APIRouter(prefix='/api/v1/projects/{project_id}/ariadne', tags=['proposals'])
    service = None

    def get_service():
        nonlocal service
        if service is None:
            judgement = judgement_service_factory()
            factory = service_factory or ProposalService
            service = factory(project_store, judgement.database, judgement_service=judgement,
                              provider_factory=judgement.provider_factory)
        return service

    def invoke(fn, *args):
        try:
            return fn(*args)
        except KeyError as exc:
            raise HTTPException(404, 'proposal or judgement not found') from exc
        except ValueError as exc:
            # Conflict classification is explicit in service exceptions; no provider errors escape.
            from .proposal_service import ProposalConflict
            raise HTTPException(409 if isinstance(exc, ProposalConflict) else 422, str(exc)) from exc

    @router.post('/proposals')
    def create(project_id: str, body: ProposalRequest):
        return project_proposal_response(invoke(get_service().create, project_id, body))

    @router.get('/proposals')
    def listing(project_id: str, card_id: str | None = None):
        return project_proposal_response(invoke(get_service().list, project_id, card_id))

    @router.get('/proposals/{proposal_id}')
    def get(project_id: str, proposal_id: str, language: Literal['zh-TW', 'en'] = 'zh-TW'):
        result = project_proposal_response(invoke(get_service().get, project_id, proposal_id))
        return {**result, 'requested_language': language}

    @router.get('/proposals/{proposal_id}/inputs')
    def inputs(project_id: str, proposal_id: str):
        return invoke(get_service().inputs, project_id, proposal_id)

    @router.post('/proposals/{proposal_id}/approve')
    def approve(project_id: str, proposal_id: str, body: ApprovalRequest):
        return project_proposal_response(invoke(get_service().approve, project_id, proposal_id, body))

    @router.post('/proposals/{proposal_id}/rerun')
    def rerun(project_id: str, proposal_id: str, body: RerunRequest):
        return project_proposal_response(invoke(get_service().rerun, project_id, proposal_id, body))

    @router.post('/proposals/{proposal_id}/reconcile')
    def reconcile(project_id: str, proposal_id: str, body: ReconcileRequest, request: Request):
        if request.client is None or request.client.host != '127.0.0.1':
            raise HTTPException(403, 'local reconciliation only')
        return project_proposal_response(invoke(get_service().reconcile, project_id, proposal_id, body))

    @router.get('/dialogue')
    def dialogue(project_id: str, subject: str = 'harbour_grain', language: Literal['zh-TW', 'en'] = 'zh-TW'):
        result = project_dialogue_response(invoke(design_dialogue, judgement_service_factory(), get_service(), project_id, subject))
        return {**result, 'requested_language': language}

    return router


def design_dialogue(judgements, proposals, project, subject):
    aliases = {'harbour': 'harbour_grain'}
    subject = aliases.get(subject, subject)

    def matches(ids):
        return any(aliases.get(ident.split('@')[0], ident.split('@')[0]) == subject for ident in ids)

    events = []
    cards = judgements.list(project)['cards']
    included = {card['id']: card for card in cards if matches(card.get('subject', {}).get('ids', []))}
    for card in included.values():
        events.append({'kind': 'judgement', 'id': card['id'], 'created_at': card['created_at'],
                       'round': card['round'], 'status': card['status'], 'judgement': card})
        for response in card.get('responses', []):
            response_kind = 'agent_response' if response.get('actor_kind') == 'AGENT' else 'designer_response'
            events.append({**response, 'response_kind': response.get('kind'), 'kind': response_kind})
    for proposal in proposals.list(project, with_comparison=False)['proposals']:
        if proposal.get('card_id') not in included:
            continue
        events.append({'kind': 'proposal', 'id': proposal['id'], 'created_at': proposal['created_at'],
                       'status': proposal['status'], 'proposal': proposal})
        approval = proposal.get('approval')
        if approval:
            events.append({'kind': 'approval', 'id': approval.get('id', proposal['id'] + ':approval'), **approval})
        job = proposal.get('job')
        if job:
            rerun_event = {'kind': 'rerun', 'id': job.get('id'),
                           'created_at': job.get('created_at', proposal['created_at']), 'job': job}
            post_judgement_id = proposal.get('post_judgement_id') or job.get('judgement_id')
            if post_judgement_id:
                rerun_event['post_judgement_id'] = post_judgement_id
            events.append(rerun_event)
    priorities = {'judgement': 0, 'designer_response': 1, 'agent_response': 1,
                  'proposal': 2, 'approval': 3, 'rerun': 4}
    def key(event):
        value = event.get('created_at') or ''
        try:
            timestamp = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            timestamp = 0
        return timestamp, priorities[event['kind']], event.get('id') or ''
    events.sort(key=key)
    return project_dialogue_response({'subject': subject, 'events': events, 'is_human_decision': False})
