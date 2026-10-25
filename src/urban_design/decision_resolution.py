"""Resolve human authority by persisted ledger order and exact target bindings."""
from dataclasses import dataclass
from typing import Literal
import re
import sqlite3
from pydantic import ValidationError
from urban_design.models import ActorKind, DecisionAction, HumanDecision, HumanStatus
from urban_design.store import EntityNotFoundError, ProjectStateStore, StateRecord, StoreError

HashField = Literal['target_artifact_sha256', 'target_payload_digest', 'target_geometry_sha256']

@dataclass(frozen=True)
class DecisionTarget:
    project_id: str
    target_type: str
    target_id: str
    version: str
    content_hash: str
    hash_field: HashField
    state_revision: int | None = None

@dataclass(frozen=True)
class DecisionResolution:
    status: Literal['EFFECTIVE', 'BLOCKED']
    reason: str
    decision: StateRecord | None = None
    sequence: int | None = None


def resolve_decision(store: ProjectStateStore, target: DecisionTarget) -> DecisionResolution:
    """Unreadable persisted data blocks; it never falls back to prior authority."""
    try:
        return _resolve_decision(store, target)
    except (StoreError, sqlite3.Error, ValueError):
        return DecisionResolution('BLOCKED', 'PERSISTED_DECISION_DATA_INVALID')


def _resolve_decision(store: ProjectStateStore, target: DecisionTarget) -> DecisionResolution:
    """No UUID/time ordering, hash alternatives, or generic ancestry fallback."""
    blocked = lambda reason: DecisionResolution('BLOCKED', reason)
    if target.state_revision is not None and target.target_type != "WorkspaceRevision":
        return blocked("HISTORICAL_TARGET_TYPE_FORBIDDEN")
    if target.hash_field not in {'target_artifact_sha256', 'target_payload_digest', 'target_geometry_sha256'}:
        return blocked('TARGET_HASH_FIELD_INVALID')
    if not isinstance(target.content_hash, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', target.content_hash):
        return blocked('TARGET_HASH_INVALID')
    try:
        current = store.get_record(target.target_id, revision=target.state_revision)
    except EntityNotFoundError:
        return blocked('TARGET_NOT_FOUND')
    if (current.entity_type != target.target_type or current.project_id != target.project_id
            or str(current.payload.get('version', current.revision)) != target.version):
        return blocked('TARGET_BINDING_CHANGED')
    field = {'target_artifact_sha256': 'sha256' if target.target_type == 'Artifact' else 'artifact_sha256',
             'target_geometry_sha256': 'geometry_sha256', 'target_payload_digest': 'payload_digest'}[target.hash_field]
    current_hash = current.payload.get(field)
    if target.target_type == 'WorkspaceRevision' and target.hash_field == 'target_geometry_sha256':
        from urban_design.geometry import canonical_geometry_hash
        try:
            current_hash = canonical_geometry_hash(current.payload['spatial_brief']['exploration_design_area']['geometry'])
        except (ValueError, TypeError, KeyError):
            return blocked('TARGET_GEOMETRY_INVALID')
    if target.target_type == "WorkspaceRevision" and target.hash_field == "target_payload_digest" and isinstance(current_hash, str):
        current_hash = "sha256:" + current_hash.removeprefix("sha256:")
    if current_hash != target.content_hash:
        return blocked('TARGET_HASH_CHANGED')
    events = store.events(project_id=target.project_id, target_id=target.target_id)
    by_id = {e.event_id: e for e in events}
    transition = by_id.get(current.event_id)
    inherited_id = None
    binding = current
    if target.target_type == 'DesignScenario' and transition and transition.action in {
            'AcceptDesignScenario', 'RejectDesignScenario', 'ReconsiderDesignScenario'}:
        if transition.parent_event_id not in by_id:
            return blocked('MISSING_APPROVAL_EVENT')
        inherited_id = transition.payload.get('human_decision_id')
        if not inherited_id or current.parent_revision != current.revision - 1:
            return blocked('TRANSITION_BINDING_INVALID')
        binding = store.get_record(current.entity_id, revision=current.parent_revision)
        geometry_id = current.payload.get('geometry_artifact_id')
        if geometry_id != binding.payload.get('geometry_artifact_id') or not geometry_id:
            return blocked('TRANSITION_GEOMETRY_CHANGED')
        try:
            geometry = store.get_record(geometry_id)
        except EntityNotFoundError:
            return blocked('TRANSITION_GEOMETRY_UNAVAILABLE')
        if (geometry.entity_type != 'Artifact' or geometry.project_id != target.project_id
                or geometry.payload.get('sha256') != target.content_hash):
            return blocked('TRANSITION_GEOMETRY_INVALID')
        expected = {'AcceptDesignScenario': 'accepted', 'RejectDesignScenario': 'rejected',
                    'ReconsiderDesignScenario': 'proposed'}[transition.action]
        if (binding.project_id != current.project_id or binding.entity_type != current.entity_type
                or binding.payload.get(field) != target.content_hash
                or transition.state_revision != current.revision or transition.target_type != current.entity_type
                or transition.payload.get('status') != expected or current.payload.get('status') != expected):
            return blocked('TRANSITION_BINDING_INVALID')
    version = str(binding.payload.get('version', binding.revision))
    # Heads are only a completeness audit. They never select authority or order it.
    # A missing latest event must block instead of reviving an earlier approval.
    for row in store.list_current('HumanDecision'):
        payload = row.payload
        if (payload.get('target_id') == target.target_id and payload.get('target_type') == target.target_type
                and payload.get('target_version') == version and payload.get(target.hash_field) == target.content_hash):
            event = by_id.get(row.event_id)
            if event is None:
                return blocked('MISSING_APPROVAL_EVENT')
            if event.payload.get('decision_id') != row.entity_id:
                return blocked('DECISION_EVENT_BINDING_INVALID')
    candidates = []
    for event in events:
        identifier = event.payload.get('decision_id')
        if identifier is None:
            continue
        try:
            row = store.get_record(identifier, revision=event.state_revision)
            decision = HumanDecision.model_validate(row.payload)
        except (EntityNotFoundError, ValidationError):
            return blocked('DECISION_STATE_INVALID')
        if (decision.target_type != target.target_type or decision.target_id != target.target_id
                or decision.target_version != version or getattr(decision, target.hash_field) != target.content_hash):
            if (event.target_type == target.target_type and event.payload.get('target_version') == version
                    and event.payload.get(target.hash_field) == target.content_hash):
                return blocked('DECISION_STATE_EVENT_CONFLICT')
            continue
        if (row.entity_type != 'HumanDecision' or row.project_id != target.project_id
                or decision.project_id != target.project_id or row.event_id != event.event_id
                or event.state_revision != row.revision or row.revision != 1
                or decision.decision_event_id != event.event_id or decision.id != row.entity_id
                or event.target_type != target.target_type or event.action != decision.action.value
                or event.parent_event_id != binding.event_id or event.payload.get('target_version') != version
                or event.actor_kind != ActorKind.HUMAN_UI or decision.actor_kind != ActorKind.HUMAN_UI
                or event.actor_session_id != decision.actor_session_id or not decision.actor_session_id
                or event.actor != decision.actor or event.reason != decision.reason
                or event.prior_status != binding.payload.get("status", binding.payload.get("human_status"))
                or target.target_id not in event.changed_refs or identifier not in event.resulting_refs):
            return blocked('DECISION_EVENT_BINDING_INVALID')
        if event.payload.get(target.hash_field) != target.content_hash:
            return blocked('DECISION_EVENT_HASH_INVALID')
        candidates.append((event, row, decision))
    if not candidates:
        return blocked('NO_COMPATIBLE_DECISION')
    event, row, decision = max(candidates, key=lambda item: item[0].sequence)
    pairs = {DecisionAction.APPROVE: HumanStatus.APPROVED, DecisionAction.ACCEPT: HumanStatus.ACCEPTED,
             DecisionAction.REJECT: HumanStatus.REJECTED, DecisionAction.RECONSIDER: HumanStatus.NOT_REVIEWED}
    if pairs.get(decision.action) != decision.status:
        return blocked('DECISION_ACTION_STATUS_INVALID')
    if inherited_id is not None and (
            row.entity_id != inherited_id or transition.parent_event_id != event.event_id
            or transition.supersedes != binding.event_id or transition.actor_kind != ActorKind.HUMAN_UI
            or transition.actor != decision.actor or transition.actor_session_id != decision.actor_session_id
            or target.target_id not in transition.resulting_refs or inherited_id not in transition.resulting_refs):
        return blocked('TRANSITION_DECISION_CHANGED')
    return DecisionResolution('EFFECTIVE', decision.action.value, row, event.sequence)


def resolve_record_decision(store, record, digest, hash_field):
    return resolve_decision(store, DecisionTarget(record.project_id, record.entity_type, record.entity_id,
                            str(record.payload.get('version', record.revision)), digest, hash_field,
                            record.revision if record.entity_type == "WorkspaceRevision" else None))


def latest_accepted_workspace(store: ProjectStateStore, project_id: str, *, workspace_id: str | None = None) -> tuple[StateRecord, StateRecord]:
    """Select historical authority, resolving every decision in ledger order."""
    from urban_design.geometry import canonical_geometry_hash
    from urban_design.workspace_contracts import WorkspaceRevision
    from urban_design.approved_generation import _workspace_payload_digest
    heads = store.list_current("WorkspaceRevision", project_id=project_id)
    if workspace_id is not None:
        heads = [head for head in heads if head.entity_id == workspace_id]
    rows = [row for head in heads for row in store.history(head.entity_id)]
    for row in sorted(rows, key=lambda item: item.revision, reverse=True):
        declared = [decision for decision in store.list_current("HumanDecision", project_id=project_id)
                    if decision.payload.get("target_type") == "WorkspaceRevision"
                    and decision.payload.get("target_id") == row.entity_id
                    and str(decision.payload.get("target_version")) == str(row.revision)]
        digest = str(row.payload.get("payload_digest") or "")
        digest = digest if digest.startswith("sha256:") else "sha256:" + digest
        try:
            geometry = canonical_geometry_hash(row.payload["spatial_brief"]["exploration_design_area"]["geometry"])
        except (KeyError, TypeError, ValueError):
            if declared:
                raise ValueError("D1 approved ExplorationDesignArea is missing or invalid")
            continue
        resolution = resolve_record_decision(store, row, geometry, "target_geometry_sha256")
        if resolution.status == "EFFECTIVE" and resolution.reason in {"Reject", "Reconsider"}:
            raise ValueError("D1 workspace acceptance was revoked")
        if resolution.status != "EFFECTIVE" or resolution.reason not in {"Accept", "Approve"}:
            if declared:
                raise ValueError("D1 workspace decision binding invalid: " + resolution.reason)
            continue
        workspace = WorkspaceRevision.model_validate(row.payload)
        if (workspace.revision != row.revision or workspace.workspace_id != row.entity_id
                or workspace.project_id != project_id):
            raise ValueError("D1 workspace revision identity mismatch")
        if workspace.status.lower() in {"superseded", "stale"}:
            raise ValueError("D1 workspace revision is superseded or stale")
        if _workspace_payload_digest(workspace).removeprefix("sha256:") != digest.removeprefix("sha256:"):
            raise ValueError("D1 workspace payload digest mismatch")
        geometry = canonical_geometry_hash(row.payload["spatial_brief"]["exploration_design_area"]["geometry"])
        decision = resolution.decision
        if (decision.payload.get("target_geometry_sha256") != geometry
                or decision.payload.get("target_payload_digest") != digest):
            raise ValueError("D1 workspace EDA decision geometry mismatch")
        study = store.current(workspace.study_area_id)
        active_study_id = store.current(project_id).payload.get("active_study_area_id")
        if active_study_id is not None and active_study_id != study.entity_id:
            raise ValueError("D1 workspace does not bind the active StudyArea")
        if (study.entity_type != "StudyArea" or study.project_id != project_id
                or study.payload.get("status") != "CONFIRMED_FOR_EXPLORATION"
                or study.payload.get("geometry_sha256") != geometry):
            raise ValueError("D1 workspace does not bind the active StudyArea")
        # A later status invalidation of this binding cannot revive historical authority.
        for later in rows:
            if (later.entity_id == row.entity_id and later.revision > row.revision
                    and later.payload.get("status", "").lower() in {"superseded", "stale"}
                    and str(later.payload.get("payload_digest", "")).removeprefix("sha256:") == digest.removeprefix("sha256:")):
                raise ValueError("D1 workspace revision is superseded or stale")
        return row, decision
    raise ValueError("D1 workspace: no current approved HumanDecision; acceptance is missing or does not match any revision")
