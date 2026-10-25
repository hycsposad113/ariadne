"""Production W7 routes: strict references, existing W6 execution and ledger."""
from __future__ import annotations
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from urban_design.store import ProjectStateStore, StoreError
from .real_service import EntityRef, RealWeek7Service
from .service import Week7Refusal, AUTHORITY_DATABASE
from .e3e4 import entry, E3E4InputError


class SwitchBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: EntityRef
    workspace_revision: StrictInt = Field(ge=1)


class OperationBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: EntityRef
    reason: str = Field(default='', max_length=2000)
    branch_id: str | None = Field(default=None, min_length=1, max_length=200)
    compare_targets: list[EntityRef] = Field(default_factory=list)


class RerunBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: EntityRef
    stage: Literal['E1', 'E2']
    plan_artifact_id: str = Field(min_length=1)
    baseline_scenario_id: str = Field(min_length=1)
    modified_scenario_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class AIRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    transport: Literal['fake']
    scenario_id: str
    scripted: dict = Field(default_factory=dict)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['plan', 'perspective', 'axonometric', 'massing', 'site', 'syntax', 'e1', 'e2', 'comparison']
    targets: list[EntityRef] = Field(min_length=1)
    result_artifact_ids: list[str] = Field(default_factory=list)
    syntax_layer_id: str | None = None

def create_week7_router(store: ProjectStateStore) -> APIRouter:
    router = APIRouter(prefix='/api/v1/week7', tags=['week7'])
    service = RealWeek7Service(store)

    def call(fn, *args, **kwargs):
        try:
            with store.locked_connection():
                return fn(*args, **kwargs)
        except Week7Refusal as exc:
            raise HTTPException(409, detail={'code': exc.code, **exc.detail}) from exc
        except (StoreError, ValueError) as exc:
            raise HTTPException(409, detail={'code': 'store_or_contract_refusal', 'reason': str(exc)}) from exc

    @router.get('/e3e4')
    def optional_entry():
        return entry()

    @router.post('/e3e4/check')
    def optional_check(body: dict):
        try:
            return entry(body)
        except E3E4InputError as exc:
            raise HTTPException(409, detail={'code': exc.code, **exc.detail}) from exc

    @router.get('/workspaces/{workspace_id}/scenarios')
    def scenarios(workspace_id: str):
        return call(service.scenarios, workspace_id)

    @router.get('/workspaces/{workspace_id}/view')
    def view(workspace_id: str, request: Request, scenario_id: str | None = None):
        from pathlib import Path
        from .jobs import project_job_states
        body = call(service.view, workspace_id, scenario_id)
        artifact_root = getattr(request.app.state, 'scenario_artifact_root', Path(store.database).parent/'scenario-artifacts')
        configured = {
            'generation': Path(artifact_root)/'generation'/'jobs.sqlite3',
            'E1': getattr(request.app.state, 'e1_job_database', None) or Path(store.database).with_name('e1-jobs.sqlite3'),
            'E2': getattr(request.app.state, 'e2_job_database', None) or Path(store.database).with_name('e2-jobs.sqlite3'),
        }
        body['job_state'] = call(project_job_states, service, workspace_id, body['scenario_id'], configured)
        bound = [j for j in body['job_state']['jobs'] if j['scenario_bound']]
        if bound:
            body['run_status'] = bound[-1]['status']
        return body

    @router.get('/cards/{evidence_id}')
    def card(evidence_id: str):
        return call(service.expand_card, evidence_id)

    @router.post('/workspaces/{workspace_id}/switch')
    def switch(workspace_id: str, body: SwitchBody):
        return call(service.switch, workspace_id, body.target, body.workspace_revision)

    @router.post('/workspaces/{workspace_id}/operations/{kind}')
    def operation(workspace_id: str, kind: Literal['inspect', 'challenge', 'modify', 'rerun', 'compare', 'fork', 'reject', 'override'], body: OperationBody):
        def run():
            _, row = service.target(workspace_id, body.target)
            if kind == 'inspect':
                return service.expand_card(row.entity_id) if row.entity_type == 'EvidenceCard' else row.to_dict()
            if kind in {'challenge', 'reject', 'override'}:
                if not body.reason.strip():
                    raise Week7Refusal('reason_required', {})
                return service.contest(workspace_id, body.target, kind, body.reason.strip())
            if kind == 'modify':
                return service.modify(workspace_id, body.target)
            if kind == 'fork':
                if not body.branch_id:
                    raise Week7Refusal('branch_id_required', {})
                return service.fork(workspace_id, body.target, body.branch_id)
            if kind == 'compare':
                if len(body.compare_targets) < 2 or len({t.entity_id for t in body.compare_targets}) != len(body.compare_targets):
                    raise Week7Refusal('distinct_compare_targets_required', {})
                return service.compare(workspace_id, body.compare_targets)
            raise Week7Refusal('approved_plan_required', {'endpoint': f'/api/v1/week7/workspaces/{workspace_id}/rerun'})
        return call(run)

    @router.post('/workspaces/{workspace_id}/rerun')
    def rerun(workspace_id: str, body: RerunBody, request: Request):
        def preflight():
            service.require_write()
            ws, execution = service.target(workspace_id, body.target, {'ToolExecution'})
            scenario = service.selected(ws, body.modified_scenario_id)
            from urban_design.analysis_lineage import scenario_lineage
            if execution.payload.get('scenario_id') not in scenario_lineage(store, scenario):
                raise Week7Refusal('execution_scenario_mismatch', {})
            # The old execution is a lineage anchor only. The newly approved
            # plan must pin this draft's own immutable inputs, checked by W6.
            plan = service.record(body.plan_artifact_id, 'Artifact')
            if plan.project_id != ws.project_id:
                raise Week7Refusal('plan_project_mismatch', {})
            if body.stage == 'E2':
                if execution.payload.get('tool') not in {'ladybug_radiance','honeybee_radiance'}:
                    raise Week7Refusal('execution_method_mismatch', {})
                _, document = service.artifact(body.plan_artifact_id, ws.project_id)
                if (document.get('baseline',{}).get('scenario_id'),document.get('modified',{}).get('scenario_id')) != (body.baseline_scenario_id,body.modified_scenario_id):
                    raise Week7Refusal('plan_scenario_pair_mismatch', {})
                from urban_design.environment.e2_service import load_plan
                _, pinned_plan, _ = load_plan(store, body.plan_artifact_id, ws.project_id)
                if (pinned_plan.modified.revision, pinned_plan.modified.geometry_sha256) != (scenario.revision, scenario.payload.get('geometry_sha256')):
                    raise Week7Refusal('rerun_plan_not_bound_to_revision', {})
                # Reject malformed pinned geometry before simulate() opens the
                # operational job store. W6 repeats full readiness validation
                # immediately before dispatch.
                from urban_design.environment.e2_service import scenario_geometry
                try:
                    for pin in (pinned_plan.baseline, pinned_plan.modified):
                        scenario_geometry(store, pin, ws.project_id)
                except (ValueError, KeyError, OSError) as exc:
                    raise Week7Refusal('E2_SCENARIO_GEOMETRY_REFUSED', {'reason': str(exc)}) from exc
            else:
                artifacts=[service.record(i,'Artifact') for i in execution.payload.get('output_artifact_refs',[])]
                if not any(a.payload.get('type')=='sunlight_simulation_result' for a in artifacts):
                    raise Week7Refusal('execution_method_mismatch', {})
            from urban_design.decision_resolution import latest_accepted_workspace
            try:
                accepted, _ = latest_accepted_workspace(store, ws.project_id, workspace_id=ws.entity_id)
            except (ValueError, KeyError, TypeError) as exc:
                raise Week7Refusal('D1_WORKSPACE_NOT_ACCEPTED', {'reason': str(exc)}) from exc
            return accepted
        ws = call(preflight)
        if body.stage == 'E1':
            # W6 owns approval, frozen-input checks, idempotency, execution and
            # publication. Its current E1 contract derives the key from plan.
            from .jobs import execute_e1_rerun
            return call(execute_e1_rerun, service, ws, body, request)
        try:
            from urban_design.environment.e2_service import simulate
        except ImportError as exc:
            raise HTTPException(409, detail={'code': 'BLOCKED_E2_NOT_IN_CHECKOUT', 'reference_commit': 'd6a03e7'}) from exc
        root = getattr(request.app.state, 'e2_artifact_root', None)
        if root is None:
            raise HTTPException(409, detail={'code': 'E2_ARTIFACT_ROOT_NOT_CONFIGURED'})
        return simulate(store, body.plan_artifact_id, ws.project_id, body.idempotency_key, getattr(request.app.state, 'e2_job_database', None))

    @router.post('/workspaces/{workspace_id}/ai/interpret')
    def interpret(workspace_id: str, body: AIRequest):
        return call(service.interpret, workspace_id, body.scenario_id, body.scripted)

    @router.get('/figures/{artifact_id}')
    def download_figure(artifact_id: str):
        import hashlib
        from pathlib import Path
        from fastapi.responses import FileResponse
        def checked():
            row=service.record(artifact_id,'Artifact')
            if row.payload.get('type')!='REAL_SCENE_FIGURE':
                raise Week7Refusal('figure_type_mismatch',{})
            path=Path(row.payload['uri'])
            if not path.is_file() or 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()!=row.payload.get('sha256'):
                raise Week7Refusal('figure_integrity_failed',{})
            return path
        return FileResponse(call(checked),media_type='image/png',filename=artifact_id+'.png')

    @router.post('/workspaces/{workspace_id}/figures')
    def export(workspace_id: str, body: ExportRequest):
        import tempfile
        import hashlib
        from pathlib import Path
        from urban_design.figure_export import render_real_week7_figure
        def run():
            service.require_write()
            root = Path(tempfile.mkdtemp(prefix='w7-real-export-', dir='/private/tmp'))
            result = render_real_week7_figure(service=service, workspace_id=workspace_id, targets=body.targets,
                kind=body.kind, output_path=root/'figure.png', result_artifact_ids=body.result_artifact_ids, syntax_layer_id=body.syntax_layer_id)
            ws = service.workspace(workspace_id)
            try:
                record = store.create('Artifact', {'type': 'REAL_SCENE_FIGURE', 'uri': result['png_path'],
                    'sha256': 'sha256:'+result['png_sha256'], 'mime': 'image/png', 'project_id': ws.project_id,
                    'manifest': result, 'parent_artifact_ids': [s['ref']['entity_id'] for s in result['sources']]},
                    project_id=ws.project_id, actor='week7-real-export', action='PublishFigure',
                    reason='Immutable real-scene export with hash-bound inputs')
            except StoreError as exc:
                raise Week7Refusal('OUTCOME_UNKNOWN', {'preserved_directory':str(root), 'reason':str(exc)}) from exc
            return {**result, 'artifact_ref': {'entity_id':record.entity_id,'revision':record.revision}}
        return call(run)

    return router
