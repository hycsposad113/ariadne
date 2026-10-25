"""Environmental run comparison rules and compatibility gates (W6 precursor lane F3).

Enforces:
1. Strict within-method comparison only (cross-method absolute comparison is rejected).
2. Spatial grid definition matching (origin, spacing, coordinate alignment).
3. Weather/solar hash matching and identical analysis periods.
4. Identification and audit of displaced sensors (points occupied by new buildings).
5. Cross-method direction-of-change consistency check without absolute value subtraction.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

from .contracts import ComparisonResult, SensorPoint


class IncompatibleComparisonError(ValueError):
    """Raised when two environmental runs cannot be legitimately compared."""


def _required_reference(run: Mapping[str, Any], name: str) -> str:
    value = run.get(name)
    return value.strip() if isinstance(value, str) else ""


def _sensor_area_summary(points: Any) -> tuple[float, float] | None:
    """Return (total cell area, valid cell area) when every sensor cell is explicit."""
    if not isinstance(points, list) or not points:
        return None

    total_area = 0.0
    valid_area = 0.0
    for point in points:
        if not isinstance(point, Mapping):
            return None
        try:
            cell_area = float(point["cell_area_m2"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(cell_area) or cell_area <= 0.0:
            return None
        status = point.get("status")
        if status not in ("VALID", "EXCLUDED_INSIDE_FOOTPRINT"):
            return None
        total_area += cell_area
        if status == "VALID":
            valid_area += cell_area

    return round(total_area, 6), round(valid_area, 6)


def _occupied_sensor_area(
    baseline_points: Any,
    occupied_points: list[str],
    area_summary: tuple[float, float] | None,
) -> float | None:
    if area_summary is None:
        return None
    if not occupied_points:
        return 0.0

    point_by_id = {
        point.get("point_id"): point
        for point in baseline_points
        if isinstance(point, Mapping)
    }
    areas: list[float] = []
    for point_id in occupied_points:
        point = point_by_id.get(point_id)
        if point is None:
            return None
        try:
            cell_area = float(point["cell_area_m2"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(cell_area) or cell_area <= 0.0:
            return None
        areas.append(cell_area)
    return round(sum(areas), 6)


def _compute_grid_hash(grid_def: Mapping[str, Any]) -> str:
    """Compute deterministic SHA-256 hash for grid definition."""
    canonical = json.dumps(
        {
            "origin_x": round(float(grid_def.get("origin_x", 0.0)), 6),
            "origin_y": round(float(grid_def.get("origin_y", 0.0)), 6),
            "spacing_m": round(float(grid_def.get("spacing_m", 5.0)), 6),
            "crs": str(grid_def.get("crs", "LOCAL_METRE")),
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compare_environmental_runs(
    baseline_run: Mapping[str, Any],
    modified_run: Mapping[str, Any],
    raise_on_incompatible: bool = True,
) -> ComparisonResult:
    """Compare a baseline run with a modified run under strict consistency rules.

    Rejection gates:
    - Different calculation methods
    - Different grid definitions
    - Different weather/solar inputs
    - Different analysis periods
    """
    baseline_method = _required_reference(baseline_run, "method")
    modified_method = _required_reference(modified_run, "method")
    base_grid = baseline_run.get("grid_definition", {})
    mod_grid = modified_run.get("grid_definition", {})
    grid_hash_base = baseline_run.get("grid_hash") or _compute_grid_hash(base_grid)
    grid_hash_mod = modified_run.get("grid_hash") or _compute_grid_hash(mod_grid)
    weather_hash_base = _required_reference(baseline_run, "weather_hash")
    weather_hash_mod = _required_reference(modified_run, "weather_hash")
    period_hash_base = _required_reference(baseline_run, "period_hash")
    period_hash_mod = _required_reference(modified_run, "period_hash")

    rejection: str | None = None

    # Required provenance references must exist before equality checks.
    if not baseline_method or not modified_method:
        rejection = "Missing method reference: both environmental runs require a non-empty method."

    # Gate 1: Same method check
    elif baseline_method != modified_method:
        rejection = (
            f"Cross-method comparison rejected: baseline uses '{baseline_method}', "
            f"modified uses '{modified_method}'. Cross-method absolute comparisons are prohibited."
        )

    # Gate 2: Grid definition match
    elif grid_hash_base != grid_hash_mod:
        rejection = (
            f"Grid mismatch rejected: baseline grid hash {grid_hash_base} "
            f"does not match modified grid hash {grid_hash_mod}."
        )

    # Gate 3: Weather / solar hash presence and match
    elif not weather_hash_base or not weather_hash_mod:
        rejection = "Missing weather reference: both environmental runs require a non-empty weather hash."
    elif weather_hash_base != weather_hash_mod:
        rejection = (
            f"Weather/solar hash mismatch rejected: baseline weather '{weather_hash_base}' "
            f"differs from modified '{weather_hash_mod}'."
        )

    # Gate 4: Analysis period presence and match
    elif not period_hash_base or not period_hash_mod:
        rejection = "Missing period reference: both environmental runs require a non-empty period hash."
    elif period_hash_base != period_hash_mod:
        rejection = (
            f"Period mismatch rejected: baseline period '{period_hash_base}' "
            f"differs from modified '{period_hash_mod}'."
        )

    if rejection:
        if raise_on_incompatible:
            raise IncompatibleComparisonError(rejection)
        return ComparisonResult(
            comparable=False,
            baseline_method=baseline_method,
            modified_method=modified_method,
            grid_hash=grid_hash_base,
            weather_hash=weather_hash_base,
            direction_of_change="INCOMPARABLE",
            occupied_points=[],
            rejection_reason=rejection,
        )

    # Extract points and values
    base_points = {p["point_id"]: p for p in baseline_run.get("points", [])}
    mod_points = {p["point_id"]: p for p in modified_run.get("points", [])}
    baseline_sensor_area = _sensor_area_summary(baseline_run.get("points", []))
    modified_sensor_area = _sensor_area_summary(modified_run.get("points", []))

    # Identify points occupied by new buildings (valid in baseline, excluded in modified)
    occupied_points: list[str] = []
    for pid, b_pt in base_points.items():
        m_pt = mod_points.get(pid)
        if m_pt and b_pt.get("status") == "VALID" and m_pt.get("status") == "EXCLUDED_INSIDE_FOOTPRINT":
            occupied_points.append(pid)

    occupied_area = _occupied_sensor_area(
        baseline_run.get("points", []), occupied_points, baseline_sensor_area
    )

    base_mean = float(baseline_run.get("area_weighted_average", 0.0))
    mod_mean = float(modified_run.get("area_weighted_average", 0.0))
    delta = round(mod_mean - base_mean, 6)

    if delta > 1e-4:
        direction = "INCREASED"
    elif delta < -1e-4:
        direction = "DECREASED"
    else:
        direction = "UNCHANGED"

    return ComparisonResult(
        comparable=True,
        baseline_method=baseline_method,
        modified_method=modified_method,
        grid_hash=grid_hash_base,
        weather_hash=weather_hash_base,
        baseline_mean=base_mean,
        modified_mean=mod_mean,
        delta_mean=delta,
        occupied_sensor_area_m2=occupied_area,
        baseline_area_coverage_ratio=(
            round(baseline_sensor_area[1] / baseline_sensor_area[0], 6)
            if baseline_sensor_area is not None and baseline_sensor_area[0] > 0.0
            else None
        ),
        modified_area_coverage_ratio=(
            round(modified_sensor_area[1] / modified_sensor_area[0], 6)
            if modified_sensor_area is not None and modified_sensor_area[0] > 0.0
            else None
        ),
        direction_of_change=direction,
        occupied_points=sorted(occupied_points),
        rejection_reason=None,
        metadata={
            "occupied_sensor_count": len(occupied_points),
            "common_sensors_evaluated": len(base_points),
        },
    )


def compare_direction_consistency(
    comparison_a: ComparisonResult,
    comparison_b: ComparisonResult,
) -> dict[str, Any]:
    """Compare whether two independent methods agree on the direction of change.

    Note: Cross-method subtraction of raw values is strictly disallowed.
    """
    if not comparison_a.comparable or not comparison_b.comparable:
        return {
            "direction_consistent": False,
            "reason": "One or both comparisons are internally incomparable.",
            "cross_method_absolute_subtraction_allowed": False,
        }

    consistent = (
        comparison_a.direction_of_change == comparison_b.direction_of_change
        and comparison_a.direction_of_change in ("INCREASED", "DECREASED", "UNCHANGED")
    )

    return {
        "direction_consistent": consistent,
        "method_a": comparison_a.baseline_method,
        "method_a_direction": comparison_a.direction_of_change,
        "method_b": comparison_b.baseline_method,
        "method_b_direction": comparison_b.direction_of_change,
        "cross_method_absolute_subtraction_allowed": False,
        "note": "Physical methods may only validate mutual trend direction, never cross-subtracted absolute values.",
    }
