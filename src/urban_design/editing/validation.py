"""Fail-closed planar validation for fixture-only floor-stack edits."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from urban_design.editing.floors import BuildingMassing, FloorStorey


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    message: str
    severity: Literal["ERROR", "LIMITATION", "INFO"]
    floor_id: str | None = None


@dataclass(frozen=True)
class GeometryValidation:
    findings: tuple[ValidationFinding, ...]
    solid_topology: Literal["NOT_ASSESSED", "UNIFORM_EXTRUSION_VALIDATED"] = "NOT_ASSESSED"
    provenance: str = "FIXTURE_ONLY"

    @property
    def geometry_valid(self) -> bool:
        return not any(finding.severity == "ERROR" for finding in self.findings)

    @property
    def acceptance_eligible(self) -> bool:
        # This package has no approved Scenario/Constraint lineage. Geometry
        # validation alone can never authorize accepting a product proposal.
        return False

    @property
    def analysis_eligible(self) -> bool:
        return self.acceptance_eligible


_POLYGON_TYPES = frozenset({"Polygon", "MultiPolygon"})


def _rings(geometry: BaseGeometry):
    if geometry.geom_type == "Polygon":
        polygon = geometry
        yield polygon.exterior
        yield from polygon.interiors
    elif geometry.geom_type == "MultiPolygon":
        for polygon in geometry.geoms:
            yield polygon.exterior
            yield from polygon.interiors


def _has_finite_xy(geometry: BaseGeometry) -> bool:
    for ring in _rings(geometry):
        for coordinate in ring.coords:
            if len(coordinate) < 2 or any(not math.isfinite(float(value)) for value in coordinate[:2]):
                return False
    return True


def _is_valid_planar_polygon(geometry: object) -> bool:
    return (
        isinstance(geometry, BaseGeometry)
        and geometry.geom_type in _POLYGON_TYPES
        and not geometry.is_empty
        and not geometry.has_z
        and _has_finite_xy(geometry)
        and math.isfinite(float(geometry.area))
        and geometry.area > 0
        and geometry.is_valid
    )


def _is_positive_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _finding_for_geometry(geometry: object, *, floor: FloorStorey) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if not isinstance(geometry, BaseGeometry):
        return [ValidationFinding("INVALID_GEOMETRY_TYPE", "floor geometry must be a polygon", "ERROR", floor.id)]
    if geometry.geom_type not in _POLYGON_TYPES:
        findings.append(
            ValidationFinding("INVALID_GEOMETRY_TYPE", "floor geometry must be Polygon or MultiPolygon", "ERROR", floor.id)
        )
        return findings
    if geometry.is_empty:
        findings.append(ValidationFinding("EMPTY_GEOMETRY", "floor geometry is empty", "ERROR", floor.id))
        return findings
    if geometry.has_z:
        findings.append(
            ValidationFinding("NON_PLANAR_COORDINATE_DIMENSION", "floor footprints must use 2D coordinates", "ERROR", floor.id)
        )
    area = float(geometry.area)
    if not math.isfinite(area) or area <= 0:
        findings.append(
            ValidationFinding("NONPOSITIVE_AREA", "floor geometry must have positive finite area", "ERROR", floor.id)
        )
    if not _has_finite_xy(geometry):
        findings.append(
            ValidationFinding("NONFINITE_COORDINATE", "floor coordinates must be finite", "ERROR", floor.id)
        )
    if not geometry.is_valid:
        validity = explain_validity(geometry)
        code = "SELF_INTERSECTION" if "self-intersection" in validity.lower() else "INVALID_GEOMETRY"
        findings.append(ValidationFinding(code, validity, "ERROR", floor.id))
    return findings


def validate_building(
    building: BuildingMassing,
    *,
    design_area: BaseGeometry | None = None,
    additional_findings: tuple[ValidationFinding, ...] = (),
    admitted_provenance: Literal["FIXTURE_ONLY", "FORMAL_DRAFT"] = "FIXTURE_ONLY",
) -> GeometryValidation:
    """Validate planar floors and only prove topology for a uniform extrusion."""

    findings: list[ValidationFinding] = []
    if not isinstance(building.id, str) or not building.id.strip():
        findings.append(ValidationFinding("INVALID_BUILDING_ID", "building id must be a non-empty string", "ERROR"))
    if not isinstance(building.provenance, str) or (admitted_provenance not in {"FIXTURE_ONLY", "FORMAL_DRAFT"} or building.provenance != admitted_provenance):
        findings.append(
            ValidationFinding(
                "INVALID_PROVENANCE",
                "this editing core accepts only explicitly fixture-only building inputs",
                "ERROR",
            )
        )
    if not building.floors:
        findings.append(ValidationFinding("NO_FLOORS", "building must contain at least one floor", "ERROR"))

    floor_ids = [floor.id for floor in building.floors]
    if len(floor_ids) != len(set(floor_ids)):
        findings.append(ValidationFinding("DUPLICATE_FLOOR_ID", "floor ids must be unique", "ERROR"))

    levels: list[int] = []
    valid_integer_levels = True
    for floor in building.floors:
        if isinstance(floor.level, bool) or not isinstance(floor.level, int) or floor.level < 0:
            findings.append(
                ValidationFinding("INVALID_FLOOR_LEVEL", "floor level must be a nonnegative integer", "ERROR", floor.id)
            )
            valid_integer_levels = False
        else:
            levels.append(floor.level)
        if not isinstance(floor.id, str) or not floor.id.strip():
            findings.append(ValidationFinding("INVALID_FLOOR_ID", "floor id must be a non-empty string", "ERROR"))
        findings.extend(_finding_for_geometry(floor.geometry, floor=floor))

    if len(levels) != len(set(levels)):
        findings.append(ValidationFinding("DUPLICATE_FLOOR_LEVEL", "floor levels must be unique", "ERROR"))
    elif levels and valid_integer_levels and sorted(levels) != list(range(len(levels))):
        findings.append(
            ValidationFinding("NONCONTIGUOUS_FLOOR_LEVELS", "floor levels must start at zero and remain contiguous", "ERROR")
        )

    for value, name in (
        (building.first_floor_height_m, "first-floor height"),
        (building.standard_floor_height_m, "standard-floor height"),
    ):
        if not _is_positive_finite_number(value):
            findings.append(ValidationFinding("INVALID_FLOOR_HEIGHT", f"{name} must be positive and finite", "ERROR"))

    valid_design_area = False
    if design_area is not None:
        valid_design_area = _is_valid_planar_polygon(design_area)
        if not valid_design_area:
            findings.append(
                ValidationFinding("INVALID_DESIGN_AREA", "design area must be a valid 2D polygon", "ERROR")
            )
        else:
            for floor in building.floors:
                if not _is_valid_planar_polygon(floor.geometry):
                    continue
                try:
                    outside = not design_area.covers(floor.geometry)
                except GEOSException:
                    findings.append(
                        ValidationFinding(
                            "DESIGN_AREA_CONTAINMENT_FAILED",
                            "polygon containment could not be evaluated safely",
                            "ERROR",
                            floor.id,
                        )
                    )
                    continue
                if outside:
                    findings.append(
                        ValidationFinding("OUTSIDE_DESIGN_AREA", "floor footprint extends outside the design area", "ERROR", floor.id)
                    )

    findings.extend(additional_findings)
    geometry_valid = not any(finding.severity == "ERROR" for finding in findings)
    uniform_extrusion = geometry_valid and bool(building.floors) and all(
        building.floors[0].geometry.equals(floor.geometry)
        for floor in building.floors[1:]
    )
    if uniform_extrusion:
        solid_topology: Literal["UNIFORM_EXTRUSION_VALIDATED", "NOT_ASSESSED"] = "UNIFORM_EXTRUSION_VALIDATED"
        findings.append(
            ValidationFinding(
                "UNIFORM_EXTRUSION_TOPOLOGY_VALIDATED",
                "Identical valid floor polygons with contiguous positive heights form a closed uniform prism stack.",
                "INFO",
            )
        )
    else:
        solid_topology = "NOT_ASSESSED"
        findings.append(
            ValidationFinding(
                "SOLID_TOPOLOGY_NOT_ASSESSED",
                "Differing floor plates require a 3D shell check; this fixture core does not infer manifold topology.",
                "LIMITATION",
            )
        )
    provenance = building.provenance if isinstance(building.provenance, str) else "INVALID"
    return GeometryValidation(
        findings=tuple(findings),
        solid_topology=solid_topology,
        provenance=provenance,
    )


def push_polygon_side(polygon: Polygon, *, edge_index: int, steps: int) -> Polygon:
    """Displace an exterior floor-plate edge by integer metre steps.

    The input polygon is never rounded.  Result validity is assessed separately
    so an invalid edit can be retained as a blocked DRAFT revision.
    """

    if not isinstance(polygon, Polygon):
        raise ValueError("side push requires one Polygon component")
    if isinstance(edge_index, bool) or not isinstance(edge_index, int):
        raise ValueError("edge index must be an integer")
    if isinstance(steps, bool) or not isinstance(steps, int):
        raise ValueError("side push steps must be an integer number of metres")
    coordinates = list(polygon.exterior.coords)[:-1]
    if edge_index < 0 or edge_index >= len(coordinates):
        raise ValueError(f"edge index {edge_index} is out of range")

    first = coordinates[edge_index]
    second = coordinates[(edge_index + 1) % len(coordinates)]
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("selected edge must have positive finite length")

    # Right-hand normal points outside a counter-clockwise exterior ring.
    origin_x, origin_y = coordinates[0]
    signed_area_twice = math.fsum(
        (x1 - origin_x) * (y2 - origin_y) - (x2 - origin_x) * (y1 - origin_y)
        for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:] + coordinates[:1])
    )
    if not math.isfinite(signed_area_twice) or signed_area_twice == 0:
        raise ValueError("selected floor footprint has no stable exterior winding")
    winding = 1 if signed_area_twice > 0 else -1
    try:
        distance = float(steps)
    except OverflowError as exc:
        raise ValueError("side push step count must fit finite projected coordinates") from exc
    if not math.isfinite(distance):
        raise ValueError("side push step count must fit finite projected coordinates")
    normal_x = winding * dy / length
    normal_y = winding * -dx / length

    displaced = list(coordinates)
    displaced[edge_index] = (first[0] + normal_x * distance, first[1] + normal_y * distance)
    next_index = (edge_index + 1) % len(coordinates)
    displaced[next_index] = (second[0] + normal_x * distance, second[1] + normal_y * distance)
    return Polygon(displaced, [list(ring.coords) for ring in polygon.interiors])
