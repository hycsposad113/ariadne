"""Persist a typed E1 plan as an Artifact and bind Founder approval to its hash.

This module does not read a passphrase and does not approve the production database.
Callers pass an already-unlocked test or Founder key into the existing decision API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from pydantic import ValidationError

from urban_design.environment.contracts import E1ExperimentPlan
from urban_design.generation.job_runner import GenerationJobRunner, PreparedOutput, write_prepared_manifest
from urban_design.generation.job_store import GenerationJobStore
from urban_design.models import ActorKind, Artifact, DecisionAction, HumanDecision, HumanStatus
from urban_design.store import EntityNotFoundError


HANDLER_VERSION = "e1-plan-approval-v1"
RESULT_NAME = "e1-result.json"
STAGE = "E1_SUNLIGHT"


class PlanNotApproved(Exception):
    """The requested artifact is not bound to a current Approve decision."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LoadedPlan:
    artifact_id: str
    revision: str
    sha256: str
    plan: E1ExperimentPlan
    decision_id: str


def canonical_plan_bytes(plan: E1ExperimentPlan) -> bytes:
    """Hash only the typed plan document, not artifact bookkeeping."""

    payload = plan.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def plan_content_sha256(plan: E1ExperimentPlan) -> str:
    return "sha256:" + hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def plan_artifact_id(digest: str) -> str:
    return "artifact-e1-plan-" + digest.removeprefix("sha256:")[:24]


def capture_scenario_inputs(store, plan: E1ExperimentPlan, project_id: str):
    """Resolve exact scenario revisions, verified geometry and effective domains."""
    from shapely.geometry import mapping
    from .contracts import E1ScenarioInputBinding
    from .router import _formal_scenario_environment

    def digest(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    bindings = []
    cache = {}
    for scenario_id in (plan.baseline_scenario_id, plan.modified_scenario_id):
        if not scenario_id:
            raise PlanNotApproved("APPROVED_PLAN_INPUT_BINDINGS_REQUIRED")
        scenario, artifact, _document, geometry, sources = _formal_scenario_environment(
            store, scenario_id, project_id, cache)
        bindings.append(E1ScenarioInputBinding(
            scenario_id=scenario.entity_id, scenario_revision=scenario.revision,
            scenario_payload_sha256=digest(scenario.payload),
            geometry_artifact_id=artifact.entity_id,
            geometry_artifact_revision=artifact.revision,
            geometry_sha256=artifact.payload["sha256"],
            public_space_sha256=digest(mapping(geometry.public_open_space)),
            domain_sources_sha256=digest(sources)))
    return bindings


def verify_scenario_inputs(store, plan: E1ExperimentPlan, project_id: str):
    if len(plan.frozen_inputs) != 2:
        raise PlanNotApproved("APPROVED_PLAN_INPUT_BINDINGS_REQUIRED")
    if capture_scenario_inputs(store, plan, project_id) != plan.frozen_inputs:
        raise PlanNotApproved("APPROVED_PLAN_INPUT_DRIFT")


def persist_e1_plan_artifact(store, plan: E1ExperimentPlan, project_id: str):
    """Store the plan once. A different document gets a new hash-derived id."""

    if plan.baseline_scenario_id and plan.modified_scenario_id:
        current_inputs = capture_scenario_inputs(store, plan, project_id)
        if plan.frozen_inputs and plan.frozen_inputs != current_inputs:
            raise PlanNotApproved("APPROVED_PLAN_INPUT_DRIFT")
        plan = plan.model_copy(update={"frozen_inputs": current_inputs})
    raw = canonical_plan_bytes(plan)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    entity_id = plan_artifact_id(digest)
    try:
        existing = store.get_record(entity_id)
    except EntityNotFoundError:
        existing = None
    if existing is not None:
        if existing.payload.get("sha256") != digest or existing.payload.get("plan") != json.loads(raw):
            raise PlanNotApproved("PLAN_ARTIFACT_HASH_MISMATCH")
        return existing
    artifact = Artifact(
        id=entity_id,
        type="e1_experiment_plan",
        uri=f"artifact://{entity_id}",
        sha256=digest,
        mime="application/json",
        producer="urban_design.environment.plan_service",
        created_at=datetime.now(timezone.utc),
        project_id=project_id,
        size_bytes=len(raw),
    )
    payload = artifact.model_dump(mode="json")
    payload["plan"] = json.loads(raw)
    return store.create(
        "Artifact",
        payload,
        entity_id=entity_id,
        project_id=project_id,
        actor="plan_service",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        action="CreateArtifact",
    )


def approve_plan_artifact(
    store,
    artifact_id: str,
    *,
    decision_key: str,
    decision_key_path: str | Path,
    actor: str,
    actor_session_id: str,
    reason: str,
    decision_id: str | None = None,
):
    """Bind one HumanDecision to the current artifact bytes. No passphrase prompt."""

    record = store.get_record(artifact_id)
    if record.entity_type != "Artifact":
        raise PlanNotApproved("PLAN_ARTIFACT_NOT_FOUND")
    try:
        plan = E1ExperimentPlan.model_validate(record.payload.get("plan"))
    except ValidationError as exc:
        raise PlanNotApproved("PLAN_ARTIFACT_INVALID") from exc
    if plan_content_sha256(plan) != record.payload.get("sha256"):
        raise PlanNotApproved("PLAN_ARTIFACT_HASH_MISMATCH")
    verify_scenario_inputs(store, plan, record.project_id)
    decision = HumanDecision(
        id=decision_id or f"decision-{uuid.uuid4().hex}",
        project_id=record.project_id,
        target_id=record.entity_id,
        target_type="Artifact",
        target_version=str(record.revision),
        target_artifact_sha256=record.payload.get("sha256"),
        action=DecisionAction.APPROVE,
        status=HumanStatus.APPROVED,
        actor=actor,
        actor_kind=ActorKind.HUMAN_UI,
        actor_session_id=actor_session_id,
        reason=reason,
        timestamp=datetime.now(timezone.utc),
    )
    return store.record_human_decision(
        decision,
        decision_key=decision_key,
        decision_key_path=decision_key_path,
    )


def approved_plan(store, artifact_id: str, project_id: str) -> LoadedPlan:
    """Return the plan only while a current Approve decision matches its sha256."""

    try:
        record = store.get_record(artifact_id)
    except EntityNotFoundError as exc:
        raise PlanNotApproved("PLAN_ARTIFACT_NOT_FOUND") from exc
    if record.entity_type != "Artifact" or record.project_id != project_id:
        raise PlanNotApproved("PLAN_ARTIFACT_PROJECT_MISMATCH")
    plan_payload = record.payload.get("plan")
    declared = record.payload.get("sha256")
    if not isinstance(plan_payload, dict) or not isinstance(declared, str):
        raise PlanNotApproved("PLAN_ARTIFACT_HASH_MISMATCH")
    try:
        plan = E1ExperimentPlan.model_validate(plan_payload)
    except ValidationError as exc:
        raise PlanNotApproved("PLAN_ARTIFACT_INVALID") from exc
    actual = plan_content_sha256(plan)
    if actual != declared:
        raise PlanNotApproved("PLAN_ARTIFACT_HASH_MISMATCH")
    version = str(record.revision)
    from urban_design.decision_resolution import resolve_record_decision
    resolution = resolve_record_decision(store, record, declared, "target_artifact_sha256")
    if resolution.status != "EFFECTIVE" or resolution.reason != "Approve":
        raise PlanNotApproved("PLAN_NOT_APPROVED")
    chosen = resolution.decision
    return LoadedPlan(
        artifact_id=record.entity_id,
        revision=version,
        sha256=declared,
        plan=plan,
        decision_id=chosen.entity_id,
    )


def resolve_e1_job_database(store, override: str | Path | None) -> Path:
    """Use a sibling job database. Draft runs must not call this."""

    if override is not None:
        path = Path(override).expanduser()
    else:
        raw = getattr(store, "database", None)
        if not isinstance(raw, (str, Path)) or str(raw) in {":memory:", ""} or str(raw).startswith("file::memory:"):
            raise PlanNotApproved("E1_JOB_DATABASE_REQUIRED")
        path = Path(raw).expanduser().with_name("e1-jobs.sqlite3")
    if path.name == "state.sqlite3" and ".urban_design_runtime" in path.parts:
        raise PlanNotApproved("E1_JOB_DATABASE_REQUIRED")
    return path


def open_e1_jobs(store, override: str | Path | None, run_stage):
    job_database = resolve_e1_job_database(store, override)
    jobs = GenerationJobStore(job_database)
    work = job_database.with_suffix("")
    output_root = work / "out"
    runner = GenerationJobRunner(jobs, staging_root=work / "staging", output_root=output_root)

    def checked_run_stage(job, staging, token):
        from urban_design.generation.job_runner import (
            KnownExecutionFailure,
            PostDispatchOutcomeUnknown,
        )

        # This records stage entry for later reconciliation; it does not claim
        # that the engine completed or identify a child process.
        receipt = {
            "receipt_type": "E1_HANDLER_ENTRY",
            "job_id": job.job_id,
            "stage": job.stage,
            "plan_artifact_id": job.request.get("plan_artifact_id"),
            "input_refs": job.input_refs,
            "baseline_scenario_id": job.request.get("baseline_scenario_id"),
            "modified_scenario_id": job.request.get("modified_scenario_id"),
            "observation_limit": "handler entry only; engine completion and process identity are not recorded here",
        }
        receipt_path = Path(staging) / "handler-entry-receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            prepared = run_stage(job, staging, token)
        except (ConnectionError, TimeoutError) as exc:
            raise PostDispatchOutcomeUnknown("E1_OUTCOME_UNKNOWN_POST_DISPATCH") from exc

        try:
            result = json.loads((Path(staging) / RESULT_NAME).read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            raise KnownExecutionFailure("E1_RESULT_MISSING_OR_INVALID") from exc
        if result.get("status") != "SUCCESS":
            raise KnownExecutionFailure("E1_COMPUTATION_FAILED")
        return prepared

    runner.register_handler(STAGE, HANDLER_VERSION, checked_run_stage)
    return jobs, runner, output_root


def write_e1_job_manifest(staging, job, digest: str, size: int):
    output = PreparedOutput(
        artifact_id=f"e1-result-{job.job_id}",
        relative_path=RESULT_NAME,
        sha256=digest,
        size_bytes=size,
    )
    return write_prepared_manifest(
        staging,
        handler_version=HANDLER_VERSION,
        input_refs=job.input_refs,
        output_refs=[output],
    )
