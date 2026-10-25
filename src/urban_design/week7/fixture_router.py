"""HTTP mount for the Week 7 service. Gates read persisted state."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from urban_design.store import ProjectStateStore
from urban_design.week7.ai import interpret_request
from urban_design.week7.e3e4 import E3E4InputError, entry as e3e4_entry
from urban_design.week7.service import AUTHORITY_DATABASE, FakeTransport, Week7Refusal, Week7Service


class SwitchBody(BaseModel):
    project_id: str
    scenario_id: str
    revision: str
    geometry_fault: str | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    features: list[dict[str, Any]] | None = None
    constraint_version: str = "unspecified"
    source_hash: str | None = None


class OperationBody(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JobBody(BaseModel):
    logical_run_id: str
    idempotency_key: str
    expected_revision: str


class DeliverBody(BaseModel):
    value: Any


class ControlBody(BaseModel):
    allowed: bool | None = None
    force: bool = False


def create_week7_router(store: ProjectStateStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/week7", tags=["week7"])
    database = Path(getattr(store, "database"))
    if database.resolve() == AUTHORITY_DATABASE.resolve():
        @router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        def authority_refused(rest: str) -> None:
            del rest
            raise HTTPException(status_code=409, detail={"code": "authority_database_write_refused"})

        return router
    service = Week7Service(database)

    def _call(func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Week7Refusal as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, **exc.detail}) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail={"code": "duplicate_logical_run"}) from exc

    @router.get("/e3e4")
    def read_e3e4() -> dict[str, Any]:
        return e3e4_entry()

    @router.post("/e3e4/check")
    def check_e3e4(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return e3e4_entry(body)
        except E3E4InputError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, **exc.detail}) from exc

    @router.get("/workspaces/{workspace_id}/view")
    def read_view(workspace_id: str) -> dict[str, Any]:
        return _call(service.view, workspace_id)

    @router.post("/workspaces/{workspace_id}/switch")
    def switch_scheme(workspace_id: str, body: SwitchBody) -> dict[str, Any]:
        return _call(
            service.switch_scheme,
            workspace_id,
            project_id=body.project_id,
            scenario_id=body.scenario_id,
            revision=body.revision,
            geometry_fault=body.geometry_fault,
            results=body.results,
            cards=body.cards,
            features=body.features,
            constraint_version=body.constraint_version,
            source_hash=body.source_hash,
        )

    @router.get("/cards/{evidence_id}")
    def expand_card(evidence_id: str) -> dict[str, Any]:
        return _call(service.expand_card, evidence_id)

    @router.post("/workspaces/{workspace_id}/operations/{kind}")
    def operate(workspace_id: str, kind: str, body: OperationBody) -> dict[str, Any]:
        payload = body.payload

        def run() -> dict[str, Any]:
            if kind == "inspect":
                return service.inspect(workspace_id, payload["evidence_id"])
            if kind == "challenge":
                return service.challenge(workspace_id, target_revision=payload["target_revision"], assumption=payload["assumption"])
            if kind == "modify":
                return service.modify(workspace_id, parameter=payload["parameter"], proposed_value=payload["proposed_value"])
            if kind == "rerun":
                return service.rerun(
                    workspace_id,
                    kind=payload["kind"],
                    logical_request=payload["logical_request"],
                    already_approved=bool(payload.get("already_approved")),
                )
            if kind == "compare":
                return service.compare(workspace_id, payload["left"], payload["right"])
            if kind == "fork":
                return service.fork(workspace_id, branch_id=payload["branch_id"])
            if kind == "reject":
                return service.reject(workspace_id, candidate_id=payload["candidate_id"], reason=payload["reason"])
            if kind == "override":
                return service.override(workspace_id, kind=payload["kind"], judgment=payload["judgment"], reason=payload["reason"])
            raise Week7Refusal("unknown_operation", {"kind": kind})

        return _call(run)

    @router.post("/workspaces/{workspace_id}/jobs")
    def submit_job(workspace_id: str, body: JobBody) -> dict[str, Any]:
        return _call(
            service.submit_job,
            workspace_id,
            logical_run_id=body.logical_run_id,
            idempotency=body.idempotency_key,
            expected_revision=body.expected_revision,
        )

    @router.post("/jobs/{job_id}/deliver")
    def deliver_job(job_id: str, body: DeliverBody) -> dict[str, Any]:
        return _call(service.deliver_job, job_id, value=body.value)

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        return _call(service.cancel_job, job_id)

    @router.post("/workspaces/{workspace_id}/controls/{control}")
    def control(workspace_id: str, control: str, body: ControlBody) -> dict[str, Any]:
        del body
        decision = _call(service.gate, workspace_id, control)
        if not decision["allowed"]:
            raise HTTPException(status_code=409, detail=decision)
        return decision

    @router.post("/workspaces/{workspace_id}/ai/interpret")
    def interpret(workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("transport") != "fake":
            raise HTTPException(status_code=409, detail={"code": "live_transport_forbidden", "live_ai": "OFFLINE"})
        transport = FakeTransport(body.get("scripted") or {})
        return _call(
            interpret_request,
            service,
            workspace_id,
            transport,
            source_text=str(body.get("source_text") or ""),
        )

    return router
