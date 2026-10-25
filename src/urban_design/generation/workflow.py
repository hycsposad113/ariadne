"""Interaction policy for the shared staged generation pipeline.

Modes decide where a designer is asked to review and select. They do not
change generation inputs, deterministic geometry, or artifact identity.
"""

from enum import StrEnum


class GenerationMode(StrEnum):
    SKELETON_FIRST = "SKELETON_FIRST"
    FULL_SCHEME = "FULL_SCHEME"
    STEPWISE = "STEPWISE"


STOP_AFTER = {
    GenerationMode.SKELETON_FIRST: frozenset({"SKELETON", "MASSING"}),
    GenerationMode.FULL_SCHEME: frozenset({"MASSING"}),
    GenerationMode.STEPWISE: frozenset({"SKELETON", "BLOCK_PROGRAM", "MASSING"}),
}


def needs_user_selection(mode: GenerationMode, stage: str) -> bool:
    """Return whether this mode pauses for the designer after ``stage``."""

    return stage in STOP_AFTER[mode]


__all__ = ["GenerationMode", "STOP_AFTER", "needs_user_selection"]

# Durable workflow orchestration. This database remains isolated from authority.
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field
from urban_design.generation.contracts import GenerationContext, StrategySpec
from urban_design.generation.hashing import generation_context_digest
from urban_design.generation.job_runner import GenerationJobRunner, PreparedOutput, write_prepared_manifest
from urban_design.generation.job_store import GenerationJobStore, IdempotencyConflict, JobStatus
from urban_design.generation.skeleton import SkeletonInputs, SkeletonBuildError, build_skeleton

STAGES = ("SKELETON", "BLOCK_PROGRAM", "MASSING")


@dataclass(frozen=True)
class ResolvedGeneration:
    """Server-owned resolver result, never constructed from HTTP approval flags.

    APPROVED requires the integration resolver to verify effective EDA,
    dispositions, brief and ConstraintSet against authoritative frozen records.
    FIXTURE_ONLY is an explicitly injected offline resolver, never publication.
    """
    context: GenerationContext
    inputs: SkeletonInputs
    strategies: tuple[StrategySpec, ...]
    revision: str
    readiness: Literal["APPROVED", "FIXTURE_ONLY"]


class WorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=1, max_length=200)
    mode: GenerationMode


class StageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str
    manifest_sha256: str
    artifact_ids: tuple[str, ...] = Field(min_length=1)


class PublicationReceipt(BaseModel):
    """Read-only reconciliation evidence supplied by the authority integration."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str
    manifest_sha256: str
    authority_revision: str = Field(min_length=1)
    authority_record_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class WorkflowReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str | None = None
    project_id: str
    mode: GenerationMode | None = None
    status: str
    readiness: str
    context_hash: str | None = None
    stage: str | None = None
    job_id: str | None = None
    job_status: str | None = None
    manifest_sha256: str | None = None
    output_refs: list[dict] = Field(default_factory=list)
    selected_artifact_ids: list[str] = Field(default_factory=list)
    stage_receipts: list[dict] = Field(default_factory=list)
    publication_status: str = "NOT_PUBLISHED"
    publication: PublicationReceipt | None = None
    reason: str | None = None
    accepted: Literal[False] = False


class GenerationWorkflow:
    def __init__(self, store: GenerationJobStore, runner: GenerationJobRunner,
                 resolve: Callable[[str], ResolvedGeneration | None], *,
                 publication_lookup: Callable[[str], PublicationReceipt | None] | None = None,
                 full_scheme_only: bool = False):
        self.full_scheme_only = full_scheme_only
        self.store, self.runner, self.resolve = store, runner, resolve
        self.publication_lookup = publication_lookup
        previous_revision_check = runner.revision_is_current
        def current(job):
            resolved = self.resolve(job.project_id)
            return bool(resolved is not None and resolved.revision == job.expected_revision
                        and generation_context_digest(resolved.context) == job.request.get("context_hash")
                        and resolved.readiness == job.request.get("readiness")
                        and (previous_revision_check is None or previous_revision_check(job)))
        runner.revision_is_current = current
        with store._transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS generation_workflows (
                    workflow_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, request_json TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key));
                CREATE TABLE IF NOT EXISTS generation_workflow_stages (
                    workflow_id TEXT NOT NULL, stage TEXT NOT NULL, job_id TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, stage));
                CREATE TABLE IF NOT EXISTS generation_stage_selections (
                    workflow_id TEXT NOT NULL, stage TEXT NOT NULL, selection_json TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, stage));
            """)

    def readiness(self, project_id: str) -> WorkflowReceipt:
        resolved = self.resolve(project_id)
        return WorkflowReceipt(project_id=project_id, status=("BLOCKED" if self.full_scheme_only else "NOT_READY") if resolved is None else "READY_TO_START",
                               readiness="BLOCKED" if resolved is None else resolved.readiness,
                               reason="APPROVED_GENERATION_CONTEXT_REQUIRED" if resolved is None else None)

    def start(self, project_id: str, request: WorkflowStart) -> WorkflowReceipt:
        if self.full_scheme_only and request.mode != GenerationMode.FULL_SCHEME:
            return WorkflowReceipt(project_id=project_id, mode=request.mode, status="NOT_READY", readiness="BLOCKED", reason="STAGED_FORMAL_SELECTION_NOT_IMPLEMENTED")
        try:
            resolved = self.resolve(project_id, use_cache=False)
        except TypeError:
            resolved = self.resolve(project_id)
        if resolved is None:
            return self.readiness(project_id)
        body = json.dumps({"mode": request.mode.value, "context_hash": generation_context_digest(resolved.context),
                           "revision": resolved.revision, "readiness": resolved.readiness,
                           "strategies": [item.model_dump(mode="json") for item in resolved.strategies]}, sort_keys=True)
        with self.store._transaction() as connection:
            row = connection.execute("SELECT workflow_id, request_json FROM generation_workflows WHERE project_id=? AND idempotency_key=?",
                                     (project_id, request.idempotency_key)).fetchone()
            if row:
                if row["request_json"] != body:
                    raise IdempotencyConflict("workflow key already binds a different mode or frozen context")
                workflow_id = row["workflow_id"]
            else:
                workflow_id = uuid.uuid4().hex
                connection.execute("INSERT INTO generation_workflows VALUES (?, ?, ?, ?)",
                                   (workflow_id, project_id, request.idempotency_key, body))
        return self.get(project_id, workflow_id)

    def by_key(self, project_id: str, idempotency_key: str) -> WorkflowReceipt:
        with self.store._transaction() as connection:
            row = connection.execute("SELECT workflow_id FROM generation_workflows WHERE project_id=? AND idempotency_key=?",
                                     (project_id, idempotency_key)).fetchone()
        if row is None:
            raise KeyError(idempotency_key)
        return self.get(project_id, row[0])

    def _load(self, project_id, workflow_id):
        with self.store._transaction() as connection:
            row = connection.execute("SELECT * FROM generation_workflows WHERE workflow_id=? AND project_id=?",
                                     (workflow_id, project_id)).fetchone()
            if row is None:
                raise KeyError(workflow_id)
            jobs = {r["stage"]: r["job_id"] for r in connection.execute(
                "SELECT * FROM generation_workflow_stages WHERE workflow_id=?", (workflow_id,))}
            selections = {r["stage"]: json.loads(r["selection_json"]) for r in connection.execute(
                "SELECT * FROM generation_stage_selections WHERE workflow_id=?", (workflow_id,))}
        return json.loads(row["request_json"]), jobs, selections

    def get(self, project_id: str, workflow_id: str) -> WorkflowReceipt:
        body, jobs, selections = self._load(project_id, workflow_id)
        mode = GenerationMode(body["mode"])
        receipt = WorkflowReceipt(workflow_id=workflow_id, project_id=project_id, mode=mode,
                                  status="READY_TO_RUN", readiness=body["readiness"], context_hash=body["context_hash"])
        receipt.stage_receipts = [
            {"stage": stage, "job_id": job.job_id, "job_status": job.status.value,
             "manifest_sha256": job.output_manifest_sha256, "output_refs": [dict(ref) for ref in job.output_refs],
             "selected_artifact_ids": list(selections.get(stage, {}).get("artifact_ids", []))}
            for stage in STAGES if stage in jobs for job in (self.store.get(jobs[stage]),)
        ]
        resolved = self.resolve(project_id)
        if resolved is None:
            return receipt.model_copy(update={"status": "BLOCKED" if self.full_scheme_only else "NOT_READY", "readiness": "BLOCKED", "reason": "APPROVED_GENERATION_CONTEXT_REQUIRED"})
        if (generation_context_digest(resolved.context) != body["context_hash"] or resolved.revision != body["revision"]
                or resolved.readiness != body["readiness"]):
            return receipt.model_copy(update={"status": "STALE_FOR_CURRENT_CONTEXT", "reason": "FROZEN_CONTEXT_CHANGED"})
        for stage in (("MASSING",) if self.full_scheme_only else STAGES):
            receipt.stage = stage
            if stage not in jobs:
                receipt.job_id = None
                receipt.job_status = None
                receipt.manifest_sha256 = None
                receipt.output_refs = []
                receipt.selected_artifact_ids = []
                receipt.publication_status = "NOT_PUBLISHED"
                receipt.publication = None
                return receipt
            job = self.store.get(jobs[stage])
            receipt.job_id, receipt.job_status = job.job_id, job.status.value
            receipt.manifest_sha256 = job.output_manifest_sha256
            receipt.output_refs = [dict(ref) for ref in job.output_refs]
            receipt.selected_artifact_ids = list(selections.get(stage, {}).get("artifact_ids", []))
            receipt.publication_status = "FIXTURE_ONLY" if body["readiness"] == "FIXTURE_ONLY" else "NOT_PUBLISHED"
            receipt.publication = None
            if job.status is JobStatus.READY and not self.runner.verify_published(job.job_id):
                receipt.status, receipt.reason = "BLOCKED", "PUBLISHED_ARTIFACT_INTEGRITY_FAILED"
                return receipt
            if body["readiness"] == "APPROVED" and self.publication_lookup and job.status is JobStatus.READY:
                publication = self.publication_lookup(job.job_id)
                if publication:
                    if publication.job_id != job.job_id or publication.manifest_sha256 != job.output_manifest_sha256:
                        receipt.status, receipt.reason = "BLOCKED", "PUBLICATION_RECEIPT_MISMATCH"
                        return receipt
                    receipt.publication_status, receipt.publication = "PUBLISHED", publication
            if job.status is not JobStatus.READY:
                receipt.status = job.status.value
                receipt.reason = job.error_code
                return receipt
            if needs_user_selection(mode, stage) and stage not in selections:
                receipt.status = "AWAITING_SELECTION"
                return receipt
        receipt.status = "COMPLETE_UNACCEPTED"
        return receipt

    def advance(self, project_id: str, workflow_id: str, *, reconcile: bool = False) -> WorkflowReceipt:
        for _ in STAGES:
            receipt = self.get(project_id, workflow_id)
            if receipt.status not in {"READY_TO_RUN", "PENDING", "RUNNING", "PREPARED"}:
                return receipt
            body, jobs, selections = self._load(project_id, workflow_id)
            stage = receipt.stage
            if reconcile:
                if stage in jobs:
                    self.runner.recover(jobs[stage])
                return self.get(project_id, workflow_id)
            if stage not in jobs:
                if not self.runner.has_handler(stage):
                    return receipt.model_copy(update={"status": "BLOCKED", "reason": "STAGE_HANDLER_NOT_READY"})
                resolved = self.resolve(project_id)
                if resolved is None:
                    return self.get(project_id, workflow_id)
                refs = [ref.model_dump(mode="json") for ref in (resolved.context.workspace_ref, resolved.context.analysis_ref,
                        resolved.context.brief_ref, *resolved.context.source_refs, *resolved.context.constraint_refs)]
                parents = []
                for prior in (() if self.full_scheme_only else STAGES[:STAGES.index(stage)]):
                    job = self.store.get(jobs[prior])
                    chosen = selections.get(prior, {}).get("artifact_ids")
                    outputs = [dict(ref) for ref in job.output_refs if chosen is None or ref["artifact_id"] in chosen]
                    parents.append({"stage": prior, "job_id": job.job_id, "manifest_sha256": job.output_manifest_sha256,
                                    "outputs": outputs})
                    refs.extend({"id": ref["artifact_id"], "sha256": ref["sha256"], "kind": "STAGE_OUTPUT"} for ref in outputs)
                request = {"workflow_id": workflow_id, "context_hash": body["context_hash"],
                           "context": resolved.context.model_dump(mode="json"), "readiness": body["readiness"], "strategies": body["strategies"],
                           "parents": parents}
                job, _ = self.store.enqueue(project_id=project_id, idempotency_key=f"workflow:{workflow_id}:{stage}",
                                             stage=stage, request=request, input_refs=refs, expected_revision=body["revision"])
                with self.store._transaction() as connection:
                    connection.execute("INSERT OR IGNORE INTO generation_workflow_stages VALUES (?, ?, ?)",
                                       (workflow_id, stage, job.job_id))
            else:
                job = self.store.get(jobs[stage])
            if job.status is JobStatus.PENDING:
                self.runner.run(job.job_id)
            else:
                return self.get(project_id, workflow_id)
        return self.get(project_id, workflow_id)

    def select(self, project_id: str, workflow_id: str, selection: StageSelection) -> WorkflowReceipt:
        receipt = self.get(project_id, workflow_id)
        body, jobs, selections = self._load(project_id, workflow_id)
        stage = next((s for s, job_id in jobs.items() if job_id == selection.job_id), None)
        encoded = json.dumps(selection.model_dump(mode="json"), sort_keys=True)
        if stage in selections:
            if json.dumps(selections[stage], sort_keys=True) != encoded:
                raise IdempotencyConflict("stage selection is immutable; start a new workflow")
            return receipt
        if receipt.status != "AWAITING_SELECTION" or selection.job_id != receipt.job_id:
            raise ValueError("selection requires the current READY stage stop")
        available = {ref["artifact_id"] for ref in receipt.output_refs}
        if (selection.manifest_sha256 != receipt.manifest_sha256 or len(set(selection.artifact_ids)) != len(selection.artifact_ids)
                or not set(selection.artifact_ids) <= available):
            raise ValueError("selection must bind this manifest and its unique output identities")
        with self.store._transaction() as connection:
            existing = connection.execute("SELECT selection_json FROM generation_stage_selections WHERE workflow_id=? AND stage=?",
                                          (workflow_id, stage)).fetchone()
            if existing and existing[0] != encoded:
                raise IdempotencyConflict("stage selection is immutable")
            connection.execute("INSERT OR IGNORE INTO generation_stage_selections VALUES (?, ?, ?)", (workflow_id, stage, encoded))
        return self.get(project_id, workflow_id)

    def cancel(self, project_id: str, workflow_id: str) -> WorkflowReceipt:
        receipt = self.get(project_id, workflow_id)
        if receipt.job_id and receipt.job_status in {"PENDING", "RUNNING"}:
            self.runner.cancel(receipt.job_id)
        return self.get(project_id, workflow_id)


def register_skeleton_handler(runner: GenerationJobRunner, resolve: Callable[[str], ResolvedGeneration | None]) -> None:
    """Attach G2 to U0/U1; recheck the server context immediately before dispatch."""
    def run(job, staging_dir: Path, cancellation_token):
        import hashlib
        resolved = resolve(job.project_id)
        if (resolved is None or generation_context_digest(resolved.context) != job.request["context_hash"]
                or resolved.revision != job.expected_revision or resolved.readiness != job.request["readiness"]):
            raise ValueError("frozen generation context is no longer current")
        outputs = []
        for raw in job.request["strategies"]:
            if cancellation_token.cancelled:
                raise ValueError("cancelled before next skeleton")
            strategy = StrategySpec.model_validate(raw)
            try:
                artifact = build_skeleton(resolved.context, strategy, resolved.inputs).artifact
            except SkeletonBuildError as error:
                from shapely.geometry import mapping
                failure = {"status": "BLOCKED", "strategy_id": error.strategy_id,
                           "reason": str(error), "context_hash": job.request["context_hash"],
                           "input_refs": list(job.input_refs),
                           "failure_geometry": mapping(error.failure_geometry) if error.failure_geometry is not None else None}
                (staging_dir / "skeleton-failure.json").write_text(json.dumps(failure, sort_keys=True), encoding="utf-8")
                raise
            data = artifact.model_dump_json().encode("utf-8")
            relative_path = f"skeleton-{len(outputs)}.json"
            (staging_dir / relative_path).write_bytes(data)
            outputs.append(PreparedOutput(artifact.artifact_id, relative_path, "sha256:" + hashlib.sha256(data).hexdigest(), len(data)))
            cancellation_token.heartbeat()
        return write_prepared_manifest(staging_dir, handler_version="g2-skeleton-workflow-v1",
                                       input_refs=job.input_refs, output_refs=outputs)
    runner.register_handler("SKELETON", "g2-skeleton-workflow-v1", run)
