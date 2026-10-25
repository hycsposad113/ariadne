"""Deterministic commands and append-only in-memory revision history."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import math
from typing import Callable, Literal, TypeAlias

from shapely.affinity import rotate, translate

from urban_design.editing.floors import BuildingMassing, FloorStorey, add_floor, remove_floor
from urban_design.editing.validation import (
    GeometryValidation,
    ValidationFinding,
    push_polygon_side,
    validate_building,
)


class EditCommandError(ValueError):
    """Raised when an edit request is malformed or cannot be applied safely."""


class RevisionConflict(EditCommandError):
    """Raised when an edit was based on an old active revision."""


class IdempotencyConflict(EditCommandError):
    """Raised when a key is reused with a different edit request."""


@dataclass(frozen=True)
class AddFloorCommand:
    new_floor_id: str
    kind: Literal["ADD_FLOOR"] = "ADD_FLOOR"


@dataclass(frozen=True)
class RemoveFloorCommand:
    floor_id: str
    kind: Literal["REMOVE_FLOOR"] = "REMOVE_FLOOR"


@dataclass(frozen=True)
class PushSideCommand:
    floor_edge_indices: tuple[tuple[str, int], ...]
    steps: int
    origin_geometry_hash: str
    kind: Literal["PUSH_SIDE"] = "PUSH_SIDE"


@dataclass(frozen=True)
class MoveCommand:
    dx_m: float
    dy_m: float
    kind: Literal["MOVE"] = "MOVE"


@dataclass(frozen=True)
class RotateCommand:
    angle_degrees: float
    kind: Literal["ROTATE"] = "ROTATE"


EditCommand: TypeAlias = (
    AddFloorCommand | RemoveFloorCommand | PushSideCommand | MoveCommand | RotateCommand
)


@dataclass(frozen=True)
class EditRevision:
    revision_id: int
    parent_revision_id: int | None
    building: BuildingMassing
    command: EditCommand | None
    before_geometry_hash: str | None
    after_geometry_hash: str
    validation: GeometryValidation
    idempotency_key: str | None
    state: Literal["DRAFT"] = "DRAFT"


def _fingerprint(command: EditCommand, expected_revision: int) -> str:
    if not is_dataclass(command):
        raise EditCommandError("edit command must be a typed dataclass")
    payload = {"expected_revision": expected_revision, "command": asdict(command)}
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EditCommandError("edit command parameters must be finite JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EditCommandError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise EditCommandError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise EditCommandError(f"{name} must be a finite number")
    return number


def _move(building: BuildingMassing, command: MoveCommand) -> BuildingMassing:
    dx = _finite_number(command.dx_m, "dx_m")
    dy = _finite_number(command.dy_m, "dy_m")
    return BuildingMassing(
        id=building.id,
        floors=tuple(
            FloorStorey(floor.id, floor.level, translate(floor.geometry, xoff=dx, yoff=dy))
            for floor in building.floors
        ),
        first_floor_height_m=building.first_floor_height_m,
        standard_floor_height_m=building.standard_floor_height_m,
        provenance=building.provenance,
    )


def _rotate(building: BuildingMassing, command: RotateCommand) -> BuildingMassing:
    angle = _finite_number(command.angle_degrees, "angle_degrees")
    if not building.floors:
        raise EditCommandError("cannot rotate a building without floors")
    base = min(building.floors, key=lambda floor: floor.level)
    if not hasattr(base.geometry, "centroid"):
        raise EditCommandError("lowest floor has no geometric centroid")
    centroid = base.geometry.centroid
    if not math.isfinite(float(centroid.x)) or not math.isfinite(float(centroid.y)):
        raise EditCommandError("lowest-floor centroid must be finite")
    origin = (float(centroid.x), float(centroid.y))
    return BuildingMassing(
        id=building.id,
        floors=tuple(
            FloorStorey(floor.id, floor.level, rotate(floor.geometry, angle, origin=origin, use_radians=False))
            for floor in building.floors
        ),
        first_floor_height_m=building.first_floor_height_m,
        standard_floor_height_m=building.standard_floor_height_m,
        provenance=building.provenance,
    )


def _push_side(building: BuildingMassing, command: PushSideCommand) -> BuildingMassing:
    before_hash = building.geometry_hash()
    if not isinstance(command.origin_geometry_hash, str) or not command.origin_geometry_hash:
        raise EditCommandError("side push requires the original geometry hash")
    if command.origin_geometry_hash != before_hash:
        raise RevisionConflict("side push origin geometry hash does not match the expected revision")
    if isinstance(command.steps, bool) or not isinstance(command.steps, int):
        raise EditCommandError("side push steps must be an integer number of metres")
    if not command.floor_edge_indices:
        raise EditCommandError("side push must identify at least one floor edge")

    ids = [floor_id for floor_id, _ in command.floor_edge_indices]
    if len(ids) != len(set(ids)):
        raise EditCommandError("side push floor targets must be unique")
    edge_index_by_floor = dict(command.floor_edge_indices)
    unknown = sorted(set(edge_index_by_floor) - {floor.id for floor in building.floors})
    if unknown:
        raise EditCommandError(f"side push references unknown floors: {', '.join(unknown)}")

    updated: list[FloorStorey] = []
    for floor in building.floors:
        if floor.id not in edge_index_by_floor:
            updated.append(floor)
            continue
        updated.append(
            FloorStorey(
                floor.id,
                floor.level,
                push_polygon_side(
                    floor.geometry,
                    edge_index=edge_index_by_floor[floor.id],
                    steps=command.steps,
                ),
            )
        )
    return BuildingMassing(
        id=building.id,
        floors=tuple(updated),
        first_floor_height_m=building.first_floor_height_m,
        standard_floor_height_m=building.standard_floor_height_m,
        provenance=building.provenance,
    )


def _apply_command(building: BuildingMassing, command: EditCommand) -> BuildingMassing:
    if isinstance(command, AddFloorCommand):
        return add_floor(building, new_floor_id=command.new_floor_id)
    if isinstance(command, RemoveFloorCommand):
        return remove_floor(building, floor_id=command.floor_id)
    if isinstance(command, PushSideCommand):
        return _push_side(building, command)
    if isinstance(command, MoveCommand):
        return _move(building, command)
    if isinstance(command, RotateCommand):
        return _rotate(building, command)
    raise EditCommandError("unsupported edit command")


def _side_push_findings(
    before: BuildingMassing,
    after: BuildingMassing,
    command: PushSideCommand,
) -> tuple[ValidationFinding, ...]:
    """Detect an edge moving through the opposite side of its floor polygon."""

    before_floors = {floor.id: floor for floor in before.floors}
    after_floors = {floor.id: floor for floor in after.floors}
    findings: list[ValidationFinding] = []
    for floor_id, _ in command.floor_edge_indices:
        original = before_floors[floor_id].geometry
        edited = after_floors[floor_id].geometry
        if not hasattr(original, "exterior") or not hasattr(edited, "exterior"):
            continue
        original_coordinates = list(original.exterior.coords)[:-1]
        edited_coordinates = list(edited.exterior.coords)[:-1]
        if len(original_coordinates) != len(edited_coordinates) or not original_coordinates:
            continue

        def signed_area(coordinates: list[tuple[float, ...]]) -> float:
            origin_x, origin_y = coordinates[0][:2]
            return math.fsum(
                (x1 - origin_x) * (y2 - origin_y) - (x2 - origin_x) * (y1 - origin_y)
                for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:] + coordinates[:1])
            )

        if signed_area(original_coordinates) * signed_area(edited_coordinates) < 0:
            findings.append(
                ValidationFinding(
                    "SIDE_PUSH_INVERTED_FOOTPRINT",
                    "the selected side moved through the opposite boundary and inverted the floor ring",
                    "ERROR",
                    floor_id,
                )
            )
    return tuple(findings)


class EditHistory:
    """In-memory append-only revision graph for deterministic fixture edits.

    A production API/store adapter is intentionally outside this C/D-line
    package.  Undo and redo move the active pointer; they never delete a draft.
    """

    def __init__(self, initial: BuildingMassing, *, validator: Callable[..., GeometryValidation] = validate_building) -> None:
        self._validate = validator
        initial_hash = initial.geometry_hash()
        self._revisions: dict[int, EditRevision] = {
            0: EditRevision(
                revision_id=0,
                parent_revision_id=None,
                building=initial,
                command=None,
                before_geometry_hash=None,
                after_geometry_hash=initial_hash,
                validation=self._validate(initial),
                idempotency_key=None,
            )
        }
        self._children: dict[int, list[int]] = {0: []}
        self._idempotency: dict[str, tuple[str, int]] = {}
        self.active_revision_id = 0

    @property
    def active(self) -> EditRevision:
        return self._revisions[self.active_revision_id]

    @property
    def revisions(self) -> tuple[EditRevision, ...]:
        return tuple(self._revisions[index] for index in sorted(self._revisions))

    def apply(
        self,
        command: EditCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> EditRevision:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise EditCommandError("expected_revision must be a nonnegative integer")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise EditCommandError("idempotency key must be a non-empty string")
        key = idempotency_key.strip()
        fingerprint = _fingerprint(command, expected_revision)
        prior = self._idempotency.get(key)
        if prior is not None:
            prior_fingerprint, prior_revision = prior
            if prior_fingerprint != fingerprint:
                raise IdempotencyConflict("idempotency key was already used for a different edit")
            return self._revisions[prior_revision]
        if expected_revision != self.active_revision_id:
            raise RevisionConflict(
                f"expected revision {expected_revision}, active revision is {self.active_revision_id}"
            )

        parent = self.active
        before_hash = parent.building.geometry_hash()
        next_building = _apply_command(parent.building, command)
        after_hash = next_building.geometry_hash()
        command_findings = (
            _side_push_findings(parent.building, next_building, command)
            if isinstance(command, PushSideCommand)
            else ()
        )
        revision_id = max(self._revisions) + 1
        revision = EditRevision(
            revision_id=revision_id,
            parent_revision_id=parent.revision_id,
            building=next_building,
            command=command,
            before_geometry_hash=before_hash,
            after_geometry_hash=after_hash,
            validation=self._validate(next_building, additional_findings=command_findings),
            idempotency_key=key,
        )
        self._revisions[revision_id] = revision
        self._children.setdefault(parent.revision_id, []).append(revision_id)
        self._children[revision_id] = []
        self._idempotency[key] = (fingerprint, revision_id)
        self.active_revision_id = revision_id
        return revision

    def undo(self) -> EditRevision:
        active = self.active
        if active.parent_revision_id is None:
            raise EditCommandError("no earlier revision to undo")
        self.active_revision_id = active.parent_revision_id
        return self.active

    def redo(self, revision_id: int | None = None) -> EditRevision:
        children = self._children.get(self.active_revision_id, [])
        if revision_id is None:
            if not children:
                raise EditCommandError("no later revision to redo")
            if len(children) > 1:
                raise EditCommandError("redo target is ambiguous; choose a child revision")
            revision_id = children[0]
        if revision_id not in children:
            raise EditCommandError("redo target must be a direct child of the active revision")
        self.active_revision_id = revision_id
        return self.active
