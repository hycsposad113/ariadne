"""Standalone W6-5 router; the API integration owner injects server resolvers."""
from fastapi import APIRouter, HTTPException
from urban_design.generation.job_store import IdempotencyConflict
from urban_design.generation.workflow import GenerationWorkflow, WorkflowStart, StageSelection, WorkflowReceipt


def create_generation_workflow_router(workflow: GenerationWorkflow) -> APIRouter:
    from urban_design.route_aliases import with_legacy_prefix

    router = APIRouter(tags=["generation-workflow"])

    def invoke(action, *args, **kwargs):
        try:
            return action(*args, **kwargs)
        except KeyError as error:
            raise HTTPException(404, "Workflow not found") from error
        except (ValueError, IdempotencyConflict) as error:
            raise HTTPException(409, str(error)) from error

    @router.get("/readiness", response_model=WorkflowReceipt)
    def readiness(project_id: str):
        return workflow.readiness(project_id)

    @router.post("", response_model=WorkflowReceipt)
    def start(project_id: str, request: WorkflowStart):
        return invoke(workflow.start, project_id, request)

    @router.get("/requests/{idempotency_key}", response_model=WorkflowReceipt)
    def by_key(project_id: str, idempotency_key: str):
        return invoke(workflow.by_key, project_id, idempotency_key)

    @router.get("/{workflow_id}", response_model=WorkflowReceipt)
    def get(project_id: str, workflow_id: str):
        return invoke(workflow.get, project_id, workflow_id)

    @router.post("/{workflow_id}/advance", response_model=WorkflowReceipt)
    def advance(project_id: str, workflow_id: str):
        return invoke(workflow.advance, project_id, workflow_id)

    @router.post("/{workflow_id}/reconcile", response_model=WorkflowReceipt)
    def reconcile(project_id: str, workflow_id: str):
        return invoke(workflow.advance, project_id, workflow_id, reconcile=True)

    @router.post("/{workflow_id}/selection", response_model=WorkflowReceipt)
    def select(project_id: str, workflow_id: str, request: StageSelection):
        return invoke(workflow.select, project_id, workflow_id, request)

    @router.post("/{workflow_id}/cancel", response_model=WorkflowReceipt)
    def cancel(project_id: str, workflow_id: str):
        return invoke(workflow.cancel, project_id, workflow_id)

    return with_legacy_prefix(
        router,
        canonical="/api/v1/projects/{project_id}/generation-workflows",
        legacy="/api/projects/{project_id}/generation-workflows",
    )
