"""Immutable floor-by-floor massing inputs and fixture metric bridge."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Literal

from shapely.geometry.base import BaseGeometry

from urban_design.morphology.metrics import (
    FloorPlate,
    MorphologyMetrics,
    calculate_morphology_metrics,
)


FIXTURE_ONLY = "FIXTURE_ONLY"


class FloorEditError(ValueError):
    """Raised when a floor command cannot be applied unambiguously."""


@dataclass(frozen=True)
class FloorStorey:
    """A floor polygon in a synthetic editable massing stack.

    Geometry validity is intentionally checked by ``validate_building`` rather
    than construction so a failed geometry edit can remain a recorded draft.
    """

    id: str
    level: int
    geometry: BaseGeometry


@dataclass(frozen=True)
class BuildingMassing:
    """Fixture-only building state shared by deterministic edit commands."""

    id: str
    floors: tuple[FloorStorey, ...]
    first_floor_height_m: float
    standard_floor_height_m: float
    provenance: Literal["FIXTURE_ONLY", "FORMAL_DRAFT"] = FIXTURE_ONLY

    def floor(self, floor_id: str) -> FloorStorey:
        matches = [floor for floor in self.floors if floor.id == floor_id]
        if len(matches) != 1:
            raise FloorEditError(f"floor id {floor_id!r} must match exactly one storey")
        return matches[0]

    def geometry_hash(self) -> str:
        """Hash the floor stack and its exact vertical parameters without rounding."""

        digest = hashlib.sha256()
        digest.update(b"urban-design-floor-stack-geometry-v2\0")
        digest.update(repr(self.first_floor_height_m).encode("utf-8"))
        digest.update(b"\0")
        digest.update(repr(self.standard_floor_height_m).encode("utf-8"))
        digest.update(b"\0")
        for floor in sorted(self.floors, key=lambda item: (str(item.level), str(item.id))):
            digest.update(str(floor.id).encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(floor.level).encode("utf-8"))
            digest.update(b"\0")
            geometry = floor.geometry
            if isinstance(geometry, BaseGeometry):
                digest.update(geometry.wkb)
            else:
                digest.update(repr(geometry).encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()


def _valid_floor_structure(building: BuildingMassing) -> None:
    if not building.floors:
        raise FloorEditError("building must contain at least one floor")
    ids = [floor.id for floor in building.floors]
    if any(not isinstance(identifier, str) or not identifier.strip() for identifier in ids):
        raise FloorEditError("floor ids must be non-empty strings")
    if len(ids) != len(set(ids)):
        raise FloorEditError("floor ids must be unique")
    if any(isinstance(floor.level, bool) or not isinstance(floor.level, int) for floor in building.floors):
        raise FloorEditError("floor levels must be integers")
    levels = [floor.level for floor in building.floors]
    if len(levels) != len(set(levels)):
        raise FloorEditError("floor levels must be unique")


def add_floor(building: BuildingMassing, *, new_floor_id: str) -> BuildingMassing:
    """Copy the current top footprint to one new, explicitly named storey."""

    _valid_floor_structure(building)
    if not isinstance(new_floor_id, str) or not new_floor_id.strip():
        raise FloorEditError("new floor id must be a non-empty string")
    if new_floor_id in {floor.id for floor in building.floors}:
        raise FloorEditError(f"floor id {new_floor_id!r} already exists")

    top_level = max(floor.level for floor in building.floors)
    top_floors = [floor for floor in building.floors if floor.level == top_level]
    if len(top_floors) != 1:
        raise FloorEditError("top storey is ambiguous")
    new_floor = FloorStorey(
        id=new_floor_id.strip(),
        level=top_level + 1,
        geometry=top_floors[0].geometry,
    )
    return BuildingMassing(
        id=building.id,
        floors=(*building.floors, new_floor),
        first_floor_height_m=building.first_floor_height_m,
        standard_floor_height_m=building.standard_floor_height_m,
        provenance=building.provenance,
    )


def remove_floor(building: BuildingMassing, *, floor_id: str) -> BuildingMassing:
    """Remove only the top storey; preserve lower geometry and floor identities."""

    _valid_floor_structure(building)
    if len(building.floors) <= 1:
        raise FloorEditError("a building must retain at least one floor")
    target = building.floor(floor_id)
    top_level = max(floor.level for floor in building.floors)
    if target.level != top_level:
        raise FloorEditError("only the top storey can be removed")
    return BuildingMassing(
        id=building.id,
        floors=tuple(floor for floor in building.floors if floor.id != floor_id),
        first_floor_height_m=building.first_floor_height_m,
        standard_floor_height_m=building.standard_floor_height_m,
        provenance=building.provenance,
    )


def calculate_fixture_metrics(
    building: BuildingMassing,
    *,
    design_area: BaseGeometry,
) -> MorphologyMetrics:
    """Run the shared W5-5 kernel on a valid synthetic stack only."""

    from urban_design.editing.validation import validate_building

    validation = validate_building(building, design_area=design_area)
    if not validation.geometry_valid:
        codes = ", ".join(finding.code for finding in validation.findings if finding.severity == "ERROR")
        raise FloorEditError(f"cannot calculate fixture metrics for invalid geometry: {codes}")

    plates = tuple(
        FloorPlate(
            id=floor.id,
            geometry=floor.geometry,
            level=floor.level,
            building_id=building.id,
        )
        for floor in sorted(building.floors, key=lambda item: item.level)
    )
    result = calculate_morphology_metrics(
        design_area=design_area,
        floor_plates=plates,
        first_floor_height_m=building.first_floor_height_m,
        standard_floor_height_m=building.standard_floor_height_m,
    )
    if result.provenance != FIXTURE_ONLY:
        raise FloorEditError("fixture metric provenance was unexpectedly changed")
    return result
