"""W7 projections over authoritative entities. No W7 tables or calculated values.

Selection and contests are append-only events. Job state belongs to existing
non-authoritative generation/E1/E2 stores; publication remains owned by W6.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from urban_design.store import EntityNotFoundError, ProjectStateStore
from urban_design.models import ActorKind, Scenario
from urban_design.week7.service import Week7Refusal, AUTHORITY_DATABASE


class EntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entity_id: str = Field(min_length=1)
    revision: StrictInt = Field(ge=1)


def digest(payload: Any) -> str:
    return 'sha256:' + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def ref(record):
    return {"entity_id": record.entity_id, "revision": record.revision, "entity_type": record.entity_type,
            "payload_sha256": digest(record.as_dict())}


class RealWeek7Service:
    def __init__(self, store: ProjectStateStore):
        self.store = store

    def record(self, entity_id: str, entity_type: str | None = None):
        try:
            record = self.store.current(entity_id)
        except EntityNotFoundError as exc:
            raise Week7Refusal('entity_missing', {'entity_id': entity_id}) from exc
        if entity_type and record.entity_type != entity_type:
            raise Week7Refusal('entity_type_mismatch', {'entity_id': entity_id, 'expected': entity_type})
        return record

    def workspace(self, workspace_id):
        try:
            return self.record(workspace_id, 'WorkspaceRevision')
        except Week7Refusal as exc:
            raise Week7Refusal('workspace_missing', {'workspace_id': workspace_id}) from exc

    def target(self, workspace_id: str, target: EntityRef, allowed=None):
        workspace = self.workspace(workspace_id)
        row = self.record(target.entity_id)
        if row.project_id != workspace.project_id or (allowed and row.entity_type not in allowed):
            raise Week7Refusal('target_out_of_scope', {})
        if row.revision != target.revision:
            raise Week7Refusal('revision_conflict', {'actual_revision': row.revision})
        return workspace, row

    def require_write(self):
        if Path(self.store.database).resolve() == AUTHORITY_DATABASE.resolve():
            raise Week7Refusal('authority_database_write_refused', {})

    def artifact(self, artifact_id: str, project_id: str):
        row = self.record(artifact_id, 'Artifact')
        if row.project_id != project_id:
            raise Week7Refusal('artifact_out_of_scope', {})
        uri = row.payload.get('uri', '')
        if '://' in uri:
            raise Week7Refusal('artifact_file_unavailable', {'artifact_id': artifact_id})
        path = Path(uri)
        if not path.is_file():
            raise Week7Refusal('artifact_file_unavailable', {'artifact_id': artifact_id})
        raw = path.read_bytes()
        if 'sha256:' + hashlib.sha256(raw).hexdigest() != row.payload.get('sha256'):
            raise Week7Refusal('artifact_hash_mismatch', {'artifact_id': artifact_id})
        return row, json.loads(raw)

    def scenarios(self, workspace_id):
        ws = self.workspace(workspace_id)
        return [dict(ref(r), status=r.payload.get('status'), geometry_sha256=r.payload.get('geometry_sha256'),
                     parent_scenario_id=r.payload.get('parent_scenario_id'), label=(r.payload.get('parameters') or {}).get('recipe_id') or r.entity_id)
                for r in self.store.list_current('DesignScenario', project_id=ws.project_id)]

    def selected(self, workspace, scenario_id=None):
        rows = self.store.list_current('DesignScenario', project_id=workspace.project_id)
        if scenario_id is None:
            events = [e for e in self.store.events(target_id=workspace.entity_id) if e.action == 'SelectScenario']
            if events:
                scenario_id = events[-1].payload.get('scenario_id')
        if scenario_id is None:
            accepted = [r for r in rows if str(r.payload.get('status')).lower() == 'accepted']
            scenario_id = (accepted or rows)[0].entity_id if rows else None
        if scenario_id is None:
            raise Week7Refusal('scenario_missing', {})
        row = self.record(scenario_id, 'DesignScenario')
        if row.project_id != workspace.project_id:
            raise Week7Refusal('scenario_out_of_scope', {})
        return row

    def switch(self, workspace_id, target: EntityRef, workspace_revision: int):
        self.require_write()
        ws, scenario = self.target(workspace_id, target, {'DesignScenario'})
        if ws.revision != workspace_revision:
            raise Week7Refusal('workspace_revision_conflict', {})
        self.store.append_ledger_event(target_id=ws.entity_id, actor='week7-ui', actor_kind=ActorKind.AGENT_AUTOMATION,
            action='SelectScenario', reason='View selection only; no design decision',
            payload={'scenario_id': scenario.entity_id, 'scenario_revision': scenario.revision, 'workspace_revision': ws.revision},
            changed_refs=[scenario.entity_id])
        return self.view(workspace_id, scenario.entity_id)

    def freshness(self, row, scenario, workspace):
        """Compare declared immutable inputs; absence of a binding stays UNKNOWN."""
        p = row.payload
        hashes = p.get('input_artifact_hashes_by_id') or p.get('input_hashes') or {}
        versions = p.get('input_versions') or []
        linked = False
        for entity_id, expected in hashes.items():
            try:
                current = self.record(entity_id)
            except Week7Refusal:
                return 'stale'
            actual = current.payload.get('sha256') or digest(current.as_dict())
            if actual != expected:
                return 'stale'
            linked = True
        # E1/E2 geometry bindings: an old geometry artifact still exists but is
        # not necessarily the current scenario geometry.
        if p.get('scenario_id') == scenario.entity_id:
            linked = False
            geometry_hashes = []
            for entity_id, expected in hashes.items():
                try:
                    artifact = self.record(entity_id)
                    if str(artifact.payload.get('type', '')).lower().replace('_', '-') == 'scenario-geometry' or entity_id == scenario.payload.get('geometry_artifact_id'):
                        geometry_hashes.append(expected)
                except Week7Refusal:
                    pass
            if geometry_hashes:
                if scenario.payload.get('geometry_sha256') not in geometry_hashes:
                    return 'stale'
                linked = True
            if versions and str(scenario.revision) in versions:
                linked = True
            elif versions and all(str(v).isdigit() for v in versions):
                return 'stale'
        params = p.get('parameters') or {}
        if not isinstance(params, dict):
            params = {}
        if params.get('scenario_revision') is not None:
            linked = True
            if params['scenario_revision'] != scenario.revision:
                return 'stale'
        if p.get('workspace_revision') is not None:
            linked = True
            if p['workspace_revision'] != workspace.revision:
                return 'stale'
        return 'current' if linked else 'unknown'

    def expand_card(self, evidence_id):
        row = self.record(evidence_id, 'EvidenceCard')
        p = row.as_dict()
        executions = []
        for source in p.get('source_refs', []):
            source_id = source.get('id') if isinstance(source, dict) else source
            try:
                execution = self.record(source_id)
            except Week7Refusal:
                continue
            if execution.entity_type == 'ToolExecution' and execution.project_id == row.project_id:
                executions.append(execution.to_dict())
        return {**row.to_dict(), 'evidence_id': row.entity_id, 'source': json.dumps(p.get('source_refs', [])),
                'formula': json.dumps(p.get('method', {})), 'unit': p.get('units') or (p.get('metric') or {}).get('unit', ''),
                'version': str(row.revision), 'limits': json.dumps(p.get('limitations', [])), 'executions': executions}

    def view(self, workspace_id, scenario_id=None):
        ws = self.workspace(workspace_id)
        scenario = self.selected(ws, scenario_id)
        p = scenario.payload
        revision = f'{ws.entity_id}@{ws.revision}/{scenario.entity_id}@{scenario.revision}'
        validation = (p.get('parameters') or {}).get('validation') or {}
        valid = validation.get('valid')  # missing validation is UNKNOWN, never True
        status = str(p.get('status', 'unknown')).lower()
        from urban_design.decision_resolution import resolve_record_decision
        resolution = resolve_record_decision(self.store, scenario, p.get('geometry_sha256'), 'target_geometry_sha256')
        decision = resolution.decision if resolution.status == 'EFFECTIVE' else None
        human = 'NOT_ACCEPTED'
        if decision and status == 'accepted' and resolution.reason == 'Accept':
            human = 'ACCEPTED'
        elif decision and status == 'rejected' and resolution.reason == 'Reject':
            human = 'REJECTED'
        from urban_design.analysis_lineage import analysis_results, scenario_lineage
        analyses = analysis_results(self.store, scenario)
        by_execution = {r['execution_id']: r for r in analyses}
        lineage_ids = set(scenario_lineage(self.store, scenario))
        runs = [r for r in self.store.list_current('ToolExecution', project_id=ws.project_id)
                if r.payload.get('scenario_id') in lineage_ids]
        cards = [r for r in self.store.list_current('EvidenceCard', project_id=ws.project_id)
                 if r.payload.get('scenario_id') in lineage_ids or (not r.payload.get('scenario_id') and
                 ((r.payload.get('claim') or {}).get('scope') == ws.payload.get('study_area_id') or ws.payload.get('study_area_id') in r.payload.get('input_versions', [])))]
        card_rows = []
        freshness = []
        for card in cards:
            c = self.expand_card(card.entity_id)
            f = self.freshness(card, scenario, ws)
            for execution in c['executions']:
                ef = by_execution.get(execution['entity_id'], {}).get('freshness') or self.freshness(self.record(execution['entity_id']), scenario, ws)
                if ef == 'stale' or (ef == 'current' and f == 'unknown'):
                    f = ef
            freshness.append(f)
            c.update(binding_revision=revision, scenario_id=card.payload.get('scenario_id'), freshness=f,
                     validation_status=card.payload.get('validation_status', 'unverified'))
            card_rows.append(c)
        for run in runs:
            freshness.append(by_execution.get(run.entity_id, {}).get('freshness') or self.freshness(run, scenario, ws))
        fresh = 'stale' if 'stale' in freshness else 'unknown' if not freshness or 'unknown' in freshness else 'current'
        features, geometry_status = [], 'MISSING'
        try:
            artifact, document = self.artifact(p.get('geometry_artifact_id'), ws.project_id)
            if artifact.payload.get('sha256') != p.get('geometry_sha256'):
                raise Week7Refusal('scenario_geometry_hash_mismatch', {})
            features = document.get('features', [])
            geometry_status = 'HASH_VERIFIED'
        except (Week7Refusal, ValueError, OSError) as exc:
            geometry_status = str(getattr(exc, 'code', exc))
        metrics = (p.get('parameters') or {}).get('metrics') or {}
        far = metrics.get('far')
        if isinstance(far, dict):
            far = far.get('value')
        panel = {'revision': revision, 'scenario_id': scenario.entity_id, 'scenario_ref': ref(scenario), 'workspace_ref': ref(ws),
                 'far': far, 'far_unit': 'ratio' if far is not None else None, 'evidence_ids': [c['evidence_id'] for c in card_rows]}
        available = [c for c in card_rows if str(c['validation_status']).lower() in {'validated', 'valid'} and c['freshness'] == 'current' and c['scenario_id'] == scenario.entity_id]
        study_revision = None
        try:
            study_revision = self.record(ws.payload.get('study_area_id'), 'StudyArea').revision
        except Week7Refusal:
            pass
        return {'workspace_id': ws.entity_id, 'project_id': ws.project_id, 'scenario_id': scenario.entity_id,
                'revision': revision, 'revision_label': revision, 'workspace_ref': ref(ws), 'scenario_ref': ref(scenario),
                'lineage': [ref(r) for r in self.store.history(scenario.entity_id)],
                'parent_scenario_id': p.get('parent_scenario_id'), 'human_decision_ref': ref(decision) if decision else None,
                'geometry_valid': valid, 'geometry_status': geometry_status, 'human_status': human,
                'run_status': next((str(r.payload.get('status')) for r in reversed(runs) if r.payload.get('scenario_id') == scenario.entity_id), 'NOT_RUN'),
                'runs': [{**r.to_dict(), 'freshness': by_execution.get(r.entity_id, {}).get('freshness', self.freshness(r, scenario, ws))} for r in runs],
                'analysis_results': analyses,
                'freshness': fresh, 'freshness_text': fresh.upper(),
                'evidence_status': 'VALIDATED' if card_rows and len(available) == len(card_rows) else 'UNVERIFIED_OR_MISSING',
                'evidence_availability': f'{len(available)}/{len(card_rows)}', 'live_ai_label': 'OFFLINE — fake transport only',
                'shell': {'authority_state': 'READY', 'study_area_id': ws.payload.get('study_area_id'), 'study_area_revision': study_revision,
                          'workspace_revision': revision, 'workspace_store_revision': ws.revision},
                'map': {**panel, 'features': features, 'geometry_status': geometry_status},
                'panels': {name: dict(panel) for name in ['map', 'model3d', 'dashboard', 'ai', 'chart', 'export', 'compare']},
                'cards': card_rows}

    def contest(self, workspace_id, target: EntityRef, kind: str, reason: str):
        self.require_write()
        ws, row = self.target(workspace_id, target, {'DesignScenario', 'EvidenceCard', 'ToolExecution'})
        if kind == 'override' and (
            row.entity_type != 'DesignScenario'
            or str(row.payload.get('status', '')).lower() != 'proposed'
        ):
            raise Week7Refusal('override_requires_proposed_scenario', {})
        event = self.store.append_ledger_event(target_id=row.entity_id, actor='week7-ui', actor_kind=ActorKind.AGENT_AUTOMATION,
            action='Contest' if kind == 'challenge' else 'ProposeHumanJudgment', reason=reason,
            payload={'operation': kind, 'target': ref(row), 'workspace_ref': ref(ws),
                     'status': 'PENDING_FOUNDER_DECISION' if kind in {'override', 'reject'} else 'OPEN',
                     'computed_values_unchanged': True})
        decision_endpoint = (
            f'/api/v1/projects/{ws.project_id}/decisions'
            if kind == 'override'
            else '/api/v1/scenarios/comparison/decision' if kind == 'reject'
            else '/api/v1/human-decisions'
        )
        return {'status': 'RECORDED' if kind == 'challenge' else 'PENDING_FOUNDER_DECISION', 'event': event.to_dict(),
                'decision_endpoint': decision_endpoint}

    def modify(self, workspace_id, target: EntityRef):
        self.require_write()
        _, row = self.target(workspace_id, target, {'DesignScenario'})
        from urban_design.editing.formal_authority import open_formal_draft, FormalAuthorityError
        try:
            draft, created = open_formal_draft(self.store, row.entity_id)
        except FormalAuthorityError as exc:
            raise Week7Refusal('BLOCKED_ON_W6_DEFECT_A', {'reason': str(exc), 'endpoint': f'/api/v1/scenarios/{row.entity_id}/formal-draft'}) from exc
        return {'status': 'FORMAL_DRAFT', 'created': created, 'scenario_ref': ref(draft),
                'editor_endpoint': f'/api/v1/scenarios/{draft.entity_id}/editing'}

    def fork(self, workspace_id, target: EntityRef, branch_id: str):
        self.require_write()
        ws, row = self.target(workspace_id, target, {'DesignScenario'})
        payload = row.as_dict()
        payload.update(id=branch_id, parent_scenario_id=row.entity_id, status='draft')
        for key in ('baseline', 'baseline_reason', 'rejection_reason'):
            payload.pop(key, None)
        params = dict(payload.get('parameters') or {})
        for key in ('baseline', 'baseline_decision_id', 'acceptance_eligible', 'analysis_eligible'):
            params.pop(key, None)
        params.update(parent_revision=row.revision, parent_geometry_sha256=row.payload.get('geometry_sha256'),
                      provenance='FORK_PENDING_FORMAL_EDITOR', acceptance_eligible=False, analysis_eligible=False)
        payload['parameters'] = params
        scenario = Scenario.model_validate(payload)
        result = self.store.create_typed(scenario, actor='week7-ui', actor_kind=ActorKind.AGENT_AUTOMATION,
            reason='Unaccepted fork; parent revision and immutable geometry preserved')
        return {'status': 'DRAFT', 'scenario_ref': ref(result), 'parent': ref(row)}

    def compare(self, workspace_id, targets: list[EntityRef]):
        from urban_design.scenario_comparison import build_scenario_comparison
        from urban_design.scenario_comparison_router import _load_scenario_records
        for target in targets:
            self.target(workspace_id, target, {'DesignScenario'})
        return build_scenario_comparison(_load_scenario_records(self.store, [t.entity_id for t in targets]))

    def interpret(self, workspace_id, scenario_id, scripted):
        """Offline transport output checked against the real evidence relationships."""
        from .service import FakeTransport
        self.require_write()
        view = self.view(workspace_id, scenario_id)
        cards = {c['evidence_id']: c for c in view['cards']}
        try:
            output = FakeTransport(scripted).complete({'revision': view['revision'], 'cards': view['cards']})
        except ConnectionError:
            result = {'status': 'FAILED', 'errors': ['FAKE_TRANSPORT_CONNECTION_FAILED'],
                      'output': {'statement': '', 'citations': [], 'stated_numbers': []},
                      'workspace_ref': view['workspace_ref'], 'scenario_ref': view['scenario_ref'],
                      'live_ai': 'OFFLINE', 'provider': 'fake', 'acceptance': 'PENDING'}
        except TimeoutError:
            result = {'status': 'OUTCOME_UNKNOWN', 'errors': ['FAKE_TRANSPORT_TIMEOUT'],
                      'output': {'statement': '', 'citations': [], 'stated_numbers': []},
                      'workspace_ref': view['workspace_ref'], 'scenario_ref': view['scenario_ref'],
                      'live_ai': 'OFFLINE', 'provider': 'fake', 'acceptance': 'PENDING',
                      'retry_allowed': False}
        else:
            result = None
        if result is not None:
            row = self.store.create('ModelRun', result, project_id=view['project_id'],
                                    actor='week7-offline-validator', actor_kind=ActorKind.AGENT_AUTOMATION,
                                    reason='離線 FakeTransport 失敗；未建立證據卡')
            return {**result, 'record_ref': ref(row)}
        errors = []
        from pydantic import ValidationError
        from .contracts import OfflineInterpretation
        try:
            output = OfflineInterpretation.model_validate(output).model_dump(mode='json')
        except ValidationError:
            output = {'statement': '', 'citations': [], 'stated_numbers': []}
            errors.append('malformed_output_redacted')
        numbers = set()
        def collect(value):
            if isinstance(value, (int,float)) and not isinstance(value,bool):
                numbers.add(value)
            elif isinstance(value, dict):
                for item in value.values(): collect(item)
            elif isinstance(value, list):
                for item in value: collect(item)
        for citation in output.get('citations', []):
            card = cards.get(citation.get('evidence_id'))
            if card is None:
                errors.append('unknown_or_out_of_scope_evidence'); continue
            payload = card['payload']
            if payload.get('scenario_id') and payload['scenario_id'] != view['scenario_id']:
                errors.append('wrong_scenario')
            if citation.get('revision') != card['revision']:
                errors.append('wrong_evidence_revision')
            if citation.get('unit') != card['unit']:
                errors.append('wrong_unit')
            if citation.get('method_id') != (payload.get('method') or {}).get('id'):
                errors.append('wrong_method')
            if card['freshness'] != 'current' or str(card['validation_status']).lower() != 'validated':
                errors.append('unavailable_evidence')
            collect((payload.get('result') or {}).get('values', {}))
        if output.get('stated_numbers') and not output.get('citations'):
            errors.append('uncited_numbers')
        if any(n not in numbers for n in output.get('stated_numbers', [])):
            errors.append('model_computed_number')
        result = {'status': 'INVALID' if errors else 'VALIDATED_OFFLINE', 'errors': sorted(set(errors)),
                  'output': output, 'workspace_ref': view['workspace_ref'], 'scenario_ref': view['scenario_ref'],
                  'live_ai': 'OFFLINE', 'provider': 'fake', 'acceptance': 'PENDING'}
        row = self.store.create('ModelRun', result, project_id=view['project_id'], actor='week7-offline-validator',
                                actor_kind=ActorKind.AGENT_AUTOMATION, reason='Fake transport; real evidence semantic validation')
        return {**result, 'record_ref': ref(row)}
