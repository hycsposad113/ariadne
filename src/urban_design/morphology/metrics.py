"""Deterministic W5-5 morphology metrics for synthetic fixtures.

The module intentionally accepts caller-provided planar Shapely geometries only.
It does not acquire data, infer floors, apply planning rules, or write project
state. Callers declare fixture or approved-project provenance explicitly.

Metric definitions:

* GFA is the sum of every included floor plate area.
* FAR is GFA divided by the effective design-area geometry.
* Coverage is the area of the union of building footprints divided by that
  design area.
* Height is first-floor height plus ``(N - 1)`` standard-floor heights.
* Zone floor area is allocated by polygon intersection.  Overlapping zones
  require an explicit allocation policy; otherwise calculation fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Literal, Mapping, Sequence

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from urban_design.models import UnavailableValue


FIXTURE_ONLY = "FIXTURE_ONLY"
_AREA_EPSILON = 1e-9
SITE_GEOMETRY_TOLERANCE_M = 1e-6
_POLYGON_TYPES = frozenset({"Polygon", "MultiPolygon"})


class MetricValidationError(ValueError):
    """Raised when a morphology metric input violates the deterministic contract."""


MetricValue = float | tuple[float, float] | UnavailableValue
FloorCountValue = int | tuple[int, int] | UnavailableValue


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetricValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _positive_number(value: float | int, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise MetricValidationError(f"{field} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise MetricValidationError(f"{field} must be a positive finite number")
    return number


def _nonnegative_number(value: float | int, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise MetricValidationError(f"{field} must be a finite nonnegative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise MetricValidationError(f"{field} must be a finite nonnegative number")
    return number


def _floor_number(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MetricValidationError(f"{field} must be a positive integer")
    return value


def _floor_bounds(value: int | tuple[int, int], field: str) -> tuple[int, int]:
    if isinstance(value, tuple):
        if len(value) != 2:
            raise MetricValidationError(f"{field} range must contain a lower and upper floor count")
        low = _floor_number(value[0], f"{field} lower bound")
        high = _floor_number(value[1], f"{field} upper bound")
        if low > high:
            raise MetricValidationError(f"{field} range lower bound must not exceed upper bound")
        return low, high
    number = _floor_number(value, field)
    return number, number


def _metric_bounds(value: MetricValue, field: str) -> tuple[float, float]:
    if isinstance(value, tuple):
        if len(value) != 2:
            raise MetricValidationError(f"{field} range must contain a lower and upper value")
        low = _nonnegative_number(value[0], f"{field} lower bound")
        high = _nonnegative_number(value[1], f"{field} upper bound")
        if low > high:
            raise MetricValidationError(f"{field} range lower bound must not exceed upper bound")
        return low, high
    number = _nonnegative_number(value, field)
    return number, number


def _geometry(value: BaseGeometry, field: str) -> BaseGeometry:
    if not isinstance(value, BaseGeometry):
        raise MetricValidationError(f"{field} must be a Shapely polygon or multipolygon")
    if value.is_empty or value.geom_type not in _POLYGON_TYPES:
        raise MetricValidationError(f"{field} must be a non-empty polygon or multipolygon")
    if not value.is_valid:
        raise MetricValidationError(f"{field} must be valid")
    area = float(value.area)
    if not math.isfinite(area) or area <= _AREA_EPSILON:
        raise MetricValidationError(f"{field} must have positive finite area")
    return value


def _stable(value: float) -> float:
    """Remove insignificant GEOS floating-point noise while staying deterministic."""

    return float(round(value, 12))


def _unknown(reason: str) -> UnavailableValue:
    return UnavailableValue(reason=_text(reason, "reason"))


@dataclass(frozen=True)
class FloorPlate:
    """One included floor polygon at a zero-based level."""

    id: str
    geometry: BaseGeometry
    level: int = 0
    building_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.id, "floor plate id")
        _geometry(self.geometry, f"floor plate {self.id} geometry")
        if isinstance(self.level, bool) or not isinstance(self.level, int) or self.level < 0:
            raise MetricValidationError(f"floor plate {self.id} level must be a nonnegative integer")
        if self.building_id is not None:
            _text(self.building_id, f"floor plate {self.id} building id")


@dataclass(frozen=True)
class RetainedBuilding:
    """A retained footprint whose floor count may be explicitly unavailable."""

    id: str
    footprint: BaseGeometry
    floor_count: FloorCountValue

    def __post_init__(self) -> None:
        _text(self.id, "retained building id")
        _geometry(self.footprint, f"retained building {self.id} footprint")
        if isinstance(self.floor_count, UnavailableValue):
            return
        _floor_bounds(self.floor_count, f"retained building {self.id} floor count")


@dataclass(frozen=True)
class Zone:
    """A polygon used to allocate floor area by geometric intersection."""

    id: str
    geometry: BaseGeometry

    def __post_init__(self) -> None:
        _text(self.id, "zone id")
        _geometry(self.geometry, f"zone {self.id} geometry")


@dataclass(frozen=True)
class FarBoundCheck:
    """A saveability check and a separate acceptance check for a FAR bound."""

    far: MetricValue
    upper_bound: float
    saveable: bool
    acceptable: bool | None
    reason: str | None = None
    status: Literal["ACCEPTABLE", "UNACCEPTABLE", "UNAVAILABLE", "INDETERMINATE"] = "ACCEPTABLE"


@dataclass(frozen=True)
class MorphologyMetrics:
    """Computed fixture metrics shared by generation, editing, and dashboards."""

    gfa_m2: MetricValue
    far: MetricValue
    coverage_m2: float
    coverage_ratio: float
    height_m: MetricValue
    zone_floor_area_m2: Mapping[str, MetricValue]
    provenance: Literal["FIXTURE_ONLY", "APPROVED_PROJECT_DATA"] = FIXTURE_ONLY
    far_bound_check: FarBoundCheck | None = None


def _unique_ids(items: Iterable[object], *, field: str) -> None:
    ids: list[str] = []
    for item in items:
        identifier = getattr(item, "id")
        if identifier in ids:
            raise MetricValidationError(f"{field} ids must be unique")
        ids.append(identifier)


def _validate_design_area(design_area: BaseGeometry) -> BaseGeometry:
    return _geometry(design_area, "design area")


def _validate_floor_plates(
    floor_plates: Iterable[FloorPlate],
    *,
    design_area: BaseGeometry,
) -> tuple[FloorPlate, ...]:
    plates = tuple(floor_plates)
    _unique_ids(plates, field="floor plate")
    for plate in plates:
        if not design_area.covers(plate.geometry):
            raise MetricValidationError(f"floor plate {plate.id} must be within the design area")
    return plates


def _validate_retained_buildings(
    retained_buildings: Iterable[RetainedBuilding],
    *,
    design_area: BaseGeometry,
) -> tuple[RetainedBuilding, ...]:
    buildings = tuple(retained_buildings)
    _unique_ids(buildings, field="retained building")
    for building in buildings:
        if not design_area.covers(building.footprint):
            raise MetricValidationError(f"retained building {building.id} must be within the design area")
    return buildings


def _validate_zones(
    zones: Iterable[Zone],
    *,
    design_area: BaseGeometry,
    allocation_policy: str | None,
) -> tuple[Zone, ...]:
    zone_items = tuple(zones)
    _unique_ids(zone_items, field="zone")
    for zone in zone_items:
        if not design_area.covers(zone.geometry) and not design_area.buffer(SITE_GEOMETRY_TOLERANCE_M).covers(zone.geometry):
            raise MetricValidationError(f"zone {zone.id} must be within the design area")

    if allocation_policy is not None and allocation_policy not in {"priority"}:
        raise MetricValidationError("allocation policy must be omitted or 'priority'")

    for index, first in enumerate(zone_items):
        for second in zone_items[index + 1 :]:
            overlap_area = first.geometry.intersection(second.geometry).area
            if overlap_area > _AREA_EPSILON and allocation_policy is None:
                raise MetricValidationError(
                    "zone polygons overlap; an explicit allocation policy is required"
                )
    return zone_items


def calculate_gfa(
    floor_plates: Iterable[FloorPlate],
    *,
    retained_buildings: Iterable[RetainedBuilding] = (),
) -> MetricValue:
    """Return the sum of floor plate areas, preserving unknown retained floors."""

    plates = tuple(floor_plates)
    retained = tuple(retained_buildings)
    unknown_reasons = [
        item.floor_count.reason
        for item in retained
        if isinstance(item.floor_count, UnavailableValue)
    ]
    if unknown_reasons:
        return _unknown(unknown_reasons[0])

    lower_area = math.fsum(plate.geometry.area for plate in plates)
    upper_area = lower_area
    has_range = False
    for building in retained:
        low, high = _floor_bounds(building.floor_count, f"retained building {building.id} floor count")
        lower_area += building.footprint.area * low
        upper_area += building.footprint.area * high
        has_range = has_range or low != high
    if has_range:
        return _stable(lower_area), _stable(upper_area)
    return _stable(lower_area)


def calculate_far(gfa_m2: MetricValue, design_area_m2: float) -> MetricValue:
    """Return GFA divided by effective design area, or preserve unavailable GFA."""

    denominator = _positive_number(design_area_m2, "design area")
    if isinstance(gfa_m2, UnavailableValue):
        return gfa_m2
    low, high = _metric_bounds(gfa_m2, "GFA")
    if low != high:
        return _stable(low / denominator), _stable(high / denominator)
    return _stable(low / denominator)


def calculate_coverage(
    design_area: BaseGeometry,
    footprints: Iterable[BaseGeometry],
) -> tuple[float, float]:
    """Return union footprint area and its ratio to the design area."""

    boundary = _validate_design_area(design_area)
    validated = tuple(_geometry(item, "building footprint") for item in footprints)
    for footprint in validated:
        if not boundary.covers(footprint):
            raise MetricValidationError("building footprint must be within the design area")
    union = unary_union(validated) if validated else None
    area = _stable(union.area if union is not None else 0.0)
    return area, _stable(area / boundary.area)


def calculate_height(
    floor_count: FloorCountValue,
    *,
    first_floor_height_m: float,
    standard_floor_height_m: float,
) -> MetricValue:
    """Return first-floor height plus standard heights for the remaining floors."""

    first = _positive_number(first_floor_height_m, "first floor height")
    standard = _positive_number(standard_floor_height_m, "standard floor height")
    if isinstance(floor_count, UnavailableValue):
        return floor_count
    low, high = _floor_bounds(floor_count, "floor count")
    low_height = _stable(first + (low - 1) * standard)
    high_height = _stable(first + (high - 1) * standard)
    return (low_height, high_height) if low != high else low_height


def evaluate_far_upper_bound(
    far: MetricValue,
    *,
    upper_bound: float,
) -> FarBoundCheck:
    """Keep drafts saveable while reporting whether a FAR upper bound is met."""

    bound = _nonnegative_number(upper_bound, "FAR upper bound")
    if isinstance(far, UnavailableValue):
        return FarBoundCheck(
            far=far,
            upper_bound=bound,
            saveable=True,
            acceptable=False,
            reason="FAR unavailable",
            status="UNAVAILABLE",
        )
    low, high = _metric_bounds(far, "FAR")
    if high <= bound + _AREA_EPSILON:
        return FarBoundCheck(
            far=far,
            upper_bound=bound,
            saveable=True,
            acceptable=True,
            status="ACCEPTABLE",
        )
    if low > bound + _AREA_EPSILON:
        return FarBoundCheck(
            far=far,
            upper_bound=bound,
            saveable=True,
            acceptable=False,
            reason="FAR exceeds upper bound",
            status="UNACCEPTABLE",
        )
    return FarBoundCheck(
        far=far,
        upper_bound=bound,
        saveable=True,
        acceptable=None,
        reason="FAR range overlaps upper bound",
        status="INDETERMINATE",
    )


def allocate_floor_area_by_zone(
    floor_plates: Iterable[FloorPlate],
    zones: Iterable[Zone],
    *,
    retained_buildings: Iterable[RetainedBuilding] = (),
    allocation_policy: str | None = None,
) -> dict[str, MetricValue]:
    """Allocate floor area to zones by intersection, sorted by stable zone ID.

    ``priority`` is the sole explicit overlap policy in this fixture kernel:
    input order wins.  Without it, any positive-area overlap is rejected.
    """

    plates = tuple(floor_plates)
    zone_items = tuple(zones)
    retained = tuple(retained_buildings)
    _unique_ids(plates, field="floor plate")
    _unique_ids(zone_items, field="zone")
    _unique_ids(retained, field="retained building")
    if allocation_policy is not None and allocation_policy not in {"priority"}:
        raise MetricValidationError("allocation policy must be omitted or 'priority'")
    for index, first in enumerate(zone_items):
        for second in zone_items[index + 1 :]:
            if first.geometry.intersection(second.geometry).area > _AREA_EPSILON and allocation_policy is None:
                raise MetricValidationError(
                    "zone polygons overlap; an explicit allocation policy is required"
                )

    calculated: dict[str, MetricValue] = {}
    claimed: BaseGeometry | None = None
    # Keep the caller's order for the explicit priority policy. The returned
    # dictionary is sorted below so output order remains stable for all calls.
    for zone in zone_items:
        available = zone.geometry
        if allocation_policy == "priority" and claimed is not None:
            available = available.difference(claimed)

        unknown_reason: str | None = None
        lower_area = math.fsum(plate.geometry.intersection(available).area for plate in plates)
        upper_area = lower_area
        has_range = False
        for building in retained:
            intersection = building.footprint.intersection(available)
            if intersection.area <= _AREA_EPSILON:
                continue
            if isinstance(building.floor_count, UnavailableValue):
                unknown_reason = building.floor_count.reason
            else:
                low, high = _floor_bounds(
                    building.floor_count,
                    f"retained building {building.id} floor count",
                )
                lower_area += intersection.area * low
                upper_area += intersection.area * high
                has_range = has_range or low != high

        calculated[zone.id] = (
            _unknown(unknown_reason)
            if unknown_reason is not None
            else (_stable(lower_area), _stable(upper_area))
            if has_range
            else _stable(lower_area)
        )
        if allocation_policy == "priority":
            claimed = zone.geometry if claimed is None else unary_union((claimed, zone.geometry))
    return {zone_id: calculated[zone_id] for zone_id in sorted(calculated)}


def _infer_floor_count(
    plates: Sequence[FloorPlate],
    retained: Sequence[RetainedBuilding],
) -> FloorCountValue:
    if any(isinstance(item.floor_count, UnavailableValue) for item in retained):
        unknown = next(item.floor_count for item in retained if isinstance(item.floor_count, UnavailableValue))
        return unknown
    lower_counts_by_building: dict[str, int] = {}
    upper_counts_by_building: dict[str, int] = {}
    for plate in plates:
        building_id = plate.building_id or "__unassigned__"
        lower_counts_by_building[building_id] = max(
            lower_counts_by_building.get(building_id, 0), plate.level + 1
        )
        upper_counts_by_building[building_id] = lower_counts_by_building[building_id]
    lower_counts = list(lower_counts_by_building.values())
    upper_counts = list(upper_counts_by_building.values())
    for building in retained:
        low, high = _floor_bounds(building.floor_count, f"retained building {building.id} floor count")
        lower_counts.append(low)
        upper_counts.append(high)
    if not lower_counts:
        return _unknown("floor count is unavailable")
    lower = max(lower_counts)
    upper = max(upper_counts)
    return (lower, upper) if lower != upper else lower


def calculate_morphology_metrics(
    design_area: BaseGeometry,
    floor_plates: Iterable[FloorPlate],
    *,
    first_floor_height_m: float,
    standard_floor_height_m: float,
    retained_buildings: Iterable[RetainedBuilding] = (),
    zones: Iterable[Zone] = (),
    allocation_policy: str | None = None,
    far_upper_bound: float | None = None,
    far_denominator_area_m2: float | None = None,
    floor_count: FloorCountValue | None = None,
    provenance: Literal["FIXTURE_ONLY", "APPROVED_PROJECT_DATA"] = FIXTURE_ONLY,
) -> MorphologyMetrics:
    """Calculate all W5-5 fixture metrics after fail-closed validation."""

    boundary = _validate_design_area(design_area)
    plates = _validate_floor_plates(floor_plates, design_area=boundary)
    retained = _validate_retained_buildings(retained_buildings, design_area=boundary)
    zone_items = _validate_zones(
        zones,
        design_area=boundary,
        allocation_policy=allocation_policy,
    )
    # Validate heights even when the count is unavailable, so malformed input
    # cannot be hidden behind an unavailable result.
    first_height = _positive_number(first_floor_height_m, "first floor height")
    standard_height = _positive_number(standard_floor_height_m, "standard floor height")

    gfa = calculate_gfa(plates, retained_buildings=retained)
    far = calculate_far(gfa, boundary.area if far_denominator_area_m2 is None else far_denominator_area_m2)
    footprints = [plate.geometry for plate in plates]
    footprints.extend(building.footprint for building in retained)
    coverage_m2, coverage_ratio = calculate_coverage(boundary, footprints)
    count = _infer_floor_count(plates, retained) if floor_count is None else floor_count
    height = calculate_height(
        count,
        first_floor_height_m=first_height,
        standard_floor_height_m=standard_height,
    )
    zone_allocations = allocate_floor_area_by_zone(
        plates,
        zone_items,
        retained_buildings=retained,
        allocation_policy=allocation_policy,
    )
    bound_check = (
        evaluate_far_upper_bound(far, upper_bound=far_upper_bound)
        if far_upper_bound is not None
        else None
    )
    return MorphologyMetrics(
        gfa_m2=gfa,
        far=far,
        coverage_m2=coverage_m2,
        coverage_ratio=coverage_ratio,
        height_m=height,
        zone_floor_area_m2=zone_allocations,
        provenance=provenance,
        far_bound_check=bound_check,
    )


__all__ = [
    "FIXTURE_ONLY",
    "FarBoundCheck",
    "FloorPlate",
    "MetricValidationError",
    "MorphologyMetrics",
    "RetainedBuilding",
    "Zone",
    "allocate_floor_area_by_zone",
    "calculate_coverage",
    "calculate_far",
    "calculate_gfa",
    "calculate_height",
    "calculate_morphology_metrics",
    "evaluate_far_upper_bound",
]
