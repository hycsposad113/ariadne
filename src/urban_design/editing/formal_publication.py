"""Publish a typed draft revision in the existing commit_batch transaction.

The callback uses existing store insertion primitives while the store owns
its lock and transaction. There is no schema change or human approval path.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import uuid

from urban_design.models import ActorKind, Artifact, Scenario, ScenarioStatus, ToolExecution
from urban_design.store import ProjectStateStore, RevisionConflictError, StateRecord


def publish_formal_draft_edit(
    store: ProjectStateStore,
    record: StateRecord,
    payload: Mapping[str, Any],
    *,
    artifact: Artifact,
    execution: ToolExecution,
    reason: str,
    verify_file: Callable[[], None],
) -> StateRecord:
    scenario = Scenario.model_validate(payload)
    if record.entity_type != "DesignScenario" or scenario.id != record.entity_id:
        raise ValueError("draft publication target mismatch")
    if scenario.project_id != record.project_id or scenario.status != ScenarioStatus.DRAFT:
        raise ValueError("draft publication cannot change project or accept a scenario")
    if record.payload.get("parameters", {}).get("provenance") != "FORMAL_DRAFT":
        raise ValueError("draft publication requires formal draft authority")
    if (
        artifact.project_id != record.project_id
        or execution.project_id != record.project_id
        or execution.scenario_id != record.entity_id
        or scenario.geometry_artifact_id != artifact.id
        or scenario.geometry_sha256 != artifact.sha256
        or execution.output_artifact_refs != [artifact.id]
        or execution.output_artifact_hashes != [artifact.sha256]
    ):
        raise ValueError("draft publication geometry provenance does not match")
    updated: list[StateRecord] = []

    def advance_draft() -> None:
        current = store._find_record(record.entity_id)
        if current.revision != record.revision:
            raise RevisionConflictError("draft changed before publication")
        verify_file()
        event_id = "event-" + uuid.uuid4().hex
        revision = store._insert_state(
            entity_id=record.entity_id,
            entity_type="DesignScenario",
            revision=record.revision + 1,
            project_id=record.project_id,
            payload=scenario.model_dump(mode="json"),
            parent_revision=record.revision,
            supersedes=record.event_id,
            event_id=event_id,
        )
        store._append_ledger_event(
            event_id=event_id,
            timestamp=revision.created_at,
            actor="scenario-editor",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id="scenario-edit-" + uuid.uuid4().hex,
            action="CreateDraftScenarioRevision",
            target_id=record.entity_id,
            target_type="DesignScenario",
            project_id=record.project_id,
            prior_status=record.payload.get("status"),
            changed_refs=None,
            reason=reason,
            resulting_refs=(record.entity_id, artifact.id, execution.id),
            supersedes=record.event_id,
            parent_event_id=record.event_id,
            state_revision=revision.revision,
            payload=None,
        )
        updated.append(revision)

    entities = []
    for model in (artifact, execution):
        entities.append({
            "entity_id": model.id,
            "entity_type": type(model).__name__,
            "payload": model.model_dump(mode="json"),
            "project_id": record.project_id,
            "event_id": "event-" + uuid.uuid4().hex,
            "actor": "scenario-editor",
            "actor_kind": ActorKind.AGENT_AUTOMATION,
            "reason": reason,
        })
    store.commit_batch(entities=entities, events=[], before_commit=advance_draft)
    return updated[0]
