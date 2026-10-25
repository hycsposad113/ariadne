"""Deterministic retained-building floor-count estimates for W5-15 fixtures."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from urban_design.models import UnavailableValue
from urban_design.three_d_bag import BuildingHeightTable


FLOOR_ESTIMATE_RULE_VERSION = "floor-estimate-v1"
FIXTURE_FLOOR_HEIGHT_M = 3.0


@dataclass(frozen=True)
class FloorEstimate:
    building_id: str
    bag_id: str | None
    floor_count: int | tuple[int, int] | UnavailableValue
    status: str
    rule_version: str
    floor_height_m: float
    floor_height_status: str
    floor_height_decision_id: str | None
    roof_p70_height_m: float | None
    ground_height_m: float | None
    height_field_name: str
    data_version: str
    limitations: tuple[str, ...]


def _nonempty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _finite_height(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite height in metres")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite height in metres")
    return number


def estimate_floor_count(
    *,
    building_id: str,
    bag_id: str | None,
    roof_p70_height_m: float | None,
    ground_height_m: float | None,
    building_use: str | None,
    height_field_name: str,
    data_version: str,
    floor_height_m: float = FIXTURE_FLOOR_HEIGHT_M,
    floor_height_status: str = "FIXTURE_ONLY",
    floor_height_decision_id: str | None = None,
) -> FloorEstimate:
    """Apply PD-11 floor-estimate-v1 while keeping unknowns and estimates explicit.

    Until the designer approves a standard floor height, 3.0 m is a fixture-only
    assumption. Approved heights must carry their HumanDecision identifier.
    ``roof_p70_height_m`` is the source field's precomputed roof 70th-percentile
    height; this function does not infer or fabricate the height distribution.
    """
    building = _nonempty(building_id, "building_id")
    bag = None if bag_id is None else _nonempty(bag_id, "bag_id")
    field_name = _nonempty(height_field_name, "height_field_name")
    version = _nonempty(data_version, "data_version")
    status = _nonempty(floor_height_status, "floor_height_status").upper()
    if status not in {"FIXTURE_ONLY", "APPROVED"}:
        raise ValueError("floor_height_status must be FIXTURE_ONLY or APPROVED")
    height = _finite_height(floor_height_m, "floor_height_m")
    if height <= 0:
        raise ValueError("floor_height_m must be positive")
    decision_id = None if floor_height_decision_id is None else _nonempty(
        floor_height_decision_id, "floor_height_decision_id"
    )
    if status == "FIXTURE_ONLY":
        if height != FIXTURE_FLOOR_HEIGHT_M:
            raise ValueError("FIXTURE_ONLY floor height must be 3.0 m")
        if decision_id is not None:
            raise ValueError("FIXTURE_ONLY floor height cannot cite an approval HumanDecision")
    elif decision_id is None:
        raise ValueError("APPROVED floor height requires a HumanDecision reference")

    limitations = [
        "ESTIMATE only; not an observed storey count or measured gross floor area.",
        "Height conversion does not establish the number of usable or legal storeys.",
    ]
    if status == "FIXTURE_ONLY":
        limitations.append("3.0 m floor height is FIXTURE_ONLY until a designer HumanDecision approves it.")

    if roof_p70_height_m is None or ground_height_m is None:
        floor_count: int | tuple[int, int] | UnavailableValue = UnavailableValue(
            reason="3D BAG height match is unavailable for this building"
        )
        limitations.append("No matching 3D BAG roof P70 and ground-height pair was available.")
    else:
        roof = _finite_height(roof_p70_height_m, "roof_p70_height_m")
        ground = _finite_height(ground_height_m, "ground_height_m")
        if roof < ground:
            floor_count = UnavailableValue(
                reason="3D BAG roof P70 is below the building ground height"
            )
            limitations.append("The 3D BAG roof P70 is below ground height, so no floor estimate was produced.")
        else:
            estimated = max(1, round((roof - ground) / height))
            if (building_use or "").strip().casefold() == "industriefunctie":
                floor_count = (1, estimated)
                limitations.append(
                    "Large-space industriefunctie can make the height-derived storey estimate high; range shown."
                )
            else:
                floor_count = estimated

    return FloorEstimate(
        building_id=building,
        bag_id=bag,
        floor_count=floor_count,
        status="ESTIMATE",
        rule_version=FLOOR_ESTIMATE_RULE_VERSION,
        floor_height_m=height,
        floor_height_status=status,
        floor_height_decision_id=decision_id,
        roof_p70_height_m=(None if roof_p70_height_m is None else float(roof_p70_height_m)),
        ground_height_m=(None if ground_height_m is None else float(ground_height_m)),
        height_field_name=field_name,
        data_version=version,
        limitations=tuple(limitations),
    )


def estimate_floor_count_from_3dbag(
    *,
    building_id: str,
    bag_id: str | None,
    building_use: str | None,
    height_table: BuildingHeightTable,
    floor_height_m: float = FIXTURE_FLOOR_HEIGHT_M,
    floor_height_status: str = "FIXTURE_ONLY",
    floor_height_decision_id: str | None = None,
) -> FloorEstimate:
    """Resolve a BAG-keyed 3D BAG record, then apply the existing PD-11 rule."""

    if not isinstance(height_table, BuildingHeightTable):
        raise TypeError("height_table must be a validated BuildingHeightTable")
    record = height_table.lookup(bag_id)
    if record is None:
        roof_height = None
        ground_height = None
        resolved_bag_id = bag_id
    else:
        roof_height = record.roof_p70_height_m
        ground_height = record.ground_height_m
        resolved_bag_id = record.bag_identificatie
    result = estimate_floor_count(
        building_id=building_id,
        bag_id=resolved_bag_id,
        roof_p70_height_m=roof_height,
        ground_height_m=ground_height,
        building_use=building_use,
        height_field_name=height_table.roof_p70_field,
        data_version=height_table.data_version,
        floor_height_m=floor_height_m,
        floor_height_status=floor_height_status,
        floor_height_decision_id=floor_height_decision_id,
    )
    if (
        record is not None
        and record.status == "UNAVAILABLE"
        and not isinstance(result.floor_count, UnavailableValue)
    ):
        reason = record.unavailable_reason or "3D BAG height record is marked unavailable"
        return replace(
            result,
            floor_count=UnavailableValue(reason=reason),
            limitations=(*result.limitations, "The matched 3D BAG height record is explicitly marked unavailable."),
        )
    return result


__all__ = [
    "FIXTURE_FLOOR_HEIGHT_M",
    "FLOOR_ESTIMATE_RULE_VERSION",
    "FloorEstimate",
    "estimate_floor_count",
    "estimate_floor_count_from_3dbag",
]
