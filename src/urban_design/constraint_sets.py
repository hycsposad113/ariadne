"""Draft validation and content hashing for W5 ConstraintSet records."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from shapely.geometry import shape

from urban_design.models import ActorKind, Constraint, ConstraintSet, ConstraintStatus
from urban_design.workspace_contracts import WorkspaceSpatialBrief


CONSTRAINT_UNIT_BY_NAME = {
    "far_upper_limit": "ratio",
    "zone_far_upper_limit": "ratio",
    "coverage_upper_limit": "ratio",
    "height_upper_limit": "m",
    "first_floor_height": "m",
    "standard_floor_height": "m",
    "road_width": "m",
    "rotation_step": "degree",
}
REQUIRED_CONSTRAINT_NAMES = frozenset(
    {
        "far_upper_limit",
        "coverage_upper_limit",
        "height_upper_limit",
        "first_floor_height",
        "standard_floor_height",
        "road_width",
        "rotation_step",
    }
)


def constraint_set_payload_digest(value: ConstraintSet | dict[str, Any]) -> str:
    """Hash decision content; omit absent/null additions to preserve legacy hashes.

    Status and source_refs remain excluded. Notes, source_note and denominator
    participate whenever non-null, including empty strings.
    """
    payload = value.model_dump(mode="json") if isinstance(value, ConstraintSet) else value
    constraints = payload.get("constraints")
    if not isinstance(constraints, list):
        raise ValueError("ConstraintSet constraints must be a list")
    definition = {
        "id": payload.get("id"),
        "project_id": payload.get("project_id"),
        "version": payload.get("version"),
        "allocation_policy": payload.get("allocation_policy"),
        "constraints": [
            {
                field: item.get(field)
                for field in ("id", "name", "value", "unit", "scope", "enforcement")
            }
            for item in constraints
        ],
    }
    if payload.get("notes") is not None:
        definition["notes"] = payload["notes"]
    for original, canonical_item in zip(constraints, definition["constraints"]):
        for field in ("source_note", "denominator"):
            if original.get(field) is not None:
                canonical_item[field] = original[field]
    canonical = json.dumps(
        definition,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_constraint_set_definition(
    constraint_set: ConstraintSet,
    *,
    require_complete: bool = False,
    require_far_denominator: bool = False,
) -> None:
    if constraint_set.status is not ConstraintStatus.PROPOSED:
        raise ValueError("new ConstraintSet records must remain proposed drafts")
    if constraint_set.allocation_policy not in {None, "priority"}:
        raise ValueError("allocation_policy must be omitted or 'priority'")

    seen_ids: set[str] = set()
    seen_name_scopes: set[tuple[str, str]] = set()
    names: set[str] = set()
    road_width_count = 0
    for item in constraint_set.constraints:
        if item.id in seen_ids:
            raise ValueError(f"duplicate constraint id: {item.id}")
        seen_ids.add(item.id)
        if item.status is not ConstraintStatus.PROPOSED or item.source_refs:
            raise ValueError("draft constraints cannot carry an active status or source HumanDecision")
        if item.name in {"far_upper_limit", "zone_far_upper_limit"}:
            if require_far_denominator and item.denominator is None:
                raise ValueError(f"{item.name} requires a denominator")
        elif item.denominator is not None:
            raise ValueError("denominator is only supported for FAR constraints")
        expected_unit = CONSTRAINT_UNIT_BY_NAME.get(item.name)
        if expected_unit is None:
            raise ValueError(f"unsupported constraint parameter: {item.name}")
        if item.unit != expected_unit:
            raise ValueError(f"{item.name} unit must be {expected_unit}")
        identity = (item.name, item.scope)
        if identity in seen_name_scopes:
            raise ValueError(f"duplicate constraint for {item.name} in scope {item.scope}")
        seen_name_scopes.add(identity)
        names.add(item.name)

        if isinstance(item.value, bool) or not isinstance(item.value, (int, float)):
            raise ValueError(f"{item.name} value must be numeric")
        if item.value < 0:
            raise ValueError(f"{item.name} value must be nonnegative")
        if item.name == "coverage_upper_limit" and item.value > 1:
            raise ValueError("coverage_upper_limit must be between 0 and 1")
        if item.name == "rotation_step" and not 0 < item.value <= 360:
            raise ValueError("rotation_step must be greater than 0 and at most 360 degrees")

        if item.name in {
            "far_upper_limit",
            "coverage_upper_limit",
            "first_floor_height",
            "standard_floor_height",
            "rotation_step",
        } and item.scope != "whole_site":
            raise ValueError(f"{item.name} scope must be whole_site")
        if item.name == "zone_far_upper_limit" and not re.fullmatch(r"zone:[^\s:]+", item.scope):
            raise ValueError("zone_far_upper_limit scope must use zone:<zone_id>")
        if item.name == "height_upper_limit" and item.scope != "whole_site" and not re.fullmatch(r"zone:[^\s:]+", item.scope):
            raise ValueError("height_upper_limit scope must be whole_site or zone:<zone_id>")
        if item.name == "road_width":
            if not re.fullmatch(r"road:[^\s:]+", item.scope):
                raise ValueError("road_width scope must use road:<hierarchy>")
            road_width_count += 1

    if not constraint_set.constraints:
        raise ValueError("ConstraintSet draft must include at least one constraint")
    if require_complete:
        missing = sorted(REQUIRED_CONSTRAINT_NAMES - names)
        if missing:
            raise ValueError("ConstraintSet cannot be activated; required parameter families are missing: " + ", ".join(missing))
        if road_width_count == 0:
            raise ValueError("ConstraintSet cannot be activated; at least one road_width is required")


def validate_zone_allocation(
    spatial_brief: WorkspaceSpatialBrief | None,
    *,
    allocation_policy: str | None,
) -> None:
    """Reject positive-area zone overlaps unless the W5-5 priority policy is explicit."""
    if allocation_policy not in {None, "priority"}:
        raise ValueError("allocation_policy must be omitted or 'priority'")
    if spatial_brief is None:
        return
    for index, first in enumerate(spatial_brief.zones):
        for second in spatial_brief.zones[index + 1 :]:
            overlap_area = shape(first.geometry).intersection(shape(second.geometry)).area
            if overlap_area > 1e-3 and allocation_policy is None:
                raise ValueError(
                    f"zones {first.zone_id!r} and {second.zone_id!r} overlap without an allocation policy"
                )


class ConstraintSetService:
    """Persist and read nonbinding ConstraintSet drafts through typed records."""

    def __init__(self, store, workspace_service):
        self.store = store
        self.workspace_service = workspace_service

    def create_draft(
        self,
        *,
        project_id: str,
        constraints: list[Constraint],
        allocation_policy: str | None,
        actor_session_id: str,
        actor_kind: ActorKind = ActorKind.HUMAN_UI,
        id: str | None = None,
        idempotency_key: str | None = None,
        notes: str | None = None,
    ):
        from urban_design.store import EntityNotFoundError, PayloadError

        actor_kind = ActorKind(actor_kind)
        if actor_kind not in {ActorKind.HUMAN_UI, ActorKind.AGENT_AUTOMATION}:
            raise ValueError("draft actor_kind must be HUMAN_UI or AGENT_AUTOMATION")
        draft_id = id or (
            f"constraint-set-{uuid.uuid5(uuid.NAMESPACE_URL, project_id + ':' + idempotency_key).hex}"
            if idempotency_key else f"constraint-set-{uuid.uuid4().hex}"
        )
        draft = ConstraintSet(
            id=draft_id, project_id=project_id, version="v1", constraints=constraints,
            allocation_policy=allocation_policy, notes=notes, status=ConstraintStatus.PROPOSED,
        )
        validate_constraint_set_definition(draft, require_far_denominator=True)
        digest = constraint_set_payload_digest(draft)
        # Reconcile with the immutable creation revision, even after human activation.
        for event in self.store.events(project_id=project_id):
            if idempotency_key and event.action == "CreateConstraintSetDraft" and event.payload.get("idempotency_key") == idempotency_key:
                if event.target_id != draft_id:
                    raise PayloadError("idempotency key is already bound to another draft id")
        try:
            original = self.store.get_record(draft_id, revision=1)
        except EntityNotFoundError:
            original = None
        if original is not None:
            event = next(event for event in self.store.events(target_id=draft_id) if event.event_id == original.event_id)
            if (original.entity_type != "ConstraintSet" or original.project_id != project_id
                or original.payload != draft.model_dump(mode="json")
                or event.actor_kind != actor_kind
                or event.action != "CreateConstraintSetDraft"
                or event.payload.get("idempotency_key") != idempotency_key):
                raise PayloadError("draft id or idempotency key conflicts with existing content or actor")
            return original, digest
        workspace = self.workspace_service.get_workspace(
            self.workspace_service._workspace_id(project_id)
        )
        spatial_brief = workspace.spatial_brief if workspace is not None else None
        validate_zone_allocation(spatial_brief, allocation_policy=allocation_policy)
        zone_ids = {zone.zone_id for zone in spatial_brief.zones} if spatial_brief is not None else set()
        for item in constraints:
            if item.scope.startswith("zone:"):
                zone_id = item.scope.removeprefix("zone:")
                if zone_id not in zone_ids:
                    raise ValueError(f"constraint scope references unknown workspace zone: {zone_id}")

        record = self.store.create_typed(
            draft,
            actor="agent-automation" if actor_kind is ActorKind.AGENT_AUTOMATION else "human-ui",
            action="CreateConstraintSetDraft",
            reason="Create nonbinding ConstraintSet draft for designer review",
            actor_kind=actor_kind,
            event_payload={"idempotency_key": idempotency_key},
            actor_session_id=actor_session_id,
        )
        return record, constraint_set_payload_digest(draft)

    def get(self, project_id: str, constraint_set_id: str):
        from urban_design.store import EntityNotFoundError

        try:
            record = self.store.current(constraint_set_id)
        except EntityNotFoundError:
            return None
        if record.entity_type != "ConstraintSet" or record.project_id != project_id:
            return None
        return record, constraint_set_payload_digest(record.payload)

    def list(self, project_id: str) -> list[dict[str, Any]]:
        records = self.store.list_current(entity_type="ConstraintSet", project_id=project_id)
        results: list[dict[str, Any]] = []
        for record in records:
            payload = record.payload if isinstance(record.payload, dict) else {}
            digest = constraint_set_payload_digest(payload)
            constraints = payload.get("constraints") or []
            results.append({
                "id": record.entity_id,
                "version": payload.get("version", f"v{record.revision}"),
                "status": payload.get("status", "proposed"),
                "notes": payload.get("notes"),
                "allocation_policy": payload.get("allocation_policy"),
                "revision": record.revision,
                "payload_digest": digest,
                "constraint_count": len(constraints),
            })
        return results



__all__ = [
    "CONSTRAINT_UNIT_BY_NAME",
    "ConstraintSetService",
    "REQUIRED_CONSTRAINT_NAMES",
    "constraint_set_payload_digest",
    "validate_constraint_set_definition",
    "validate_zone_allocation",
]
