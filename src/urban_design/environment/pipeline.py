"""End-to-end environmental simulation pipeline (W6-11 E1).

Executes:
1. Experiment plan validation (only approved runs are validated; draft previews stay provisional)
2. Platform geometry conversion to 3D simulation obstacles (with True North adjustment)
3. Ground sensor grid generation with building footprint exclusion
4. Direct sunlight duration calculation (optional Ladybug Radiance or headless Python raycasting)
5. Strict within-method comparison (baseline vs modified, tracking displaced sensors)
6. Uniform color scale generation (identical min/max and bins for baseline and modified)
7. Audit-ready persistence as ToolExecution, Artifact, and EvidenceCard models
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.ops import unary_union

from ..models import (
    ActorKind,
    Artifact,
    Claim,
    ClaimType,
    Confidence,
    ConfidenceLevel,
    EvidenceCard,
    EvidenceResult,
    EvidenceValidationStatus,
    HumanStatus,
    MethodReference,
    MetricReference,
    ResultStatus,
    RunStatus,
    ToolExecution,
)
from .comparison import (
    IncompatibleComparisonError,
    _compute_grid_hash,
    compare_environmental_runs,
)
from .contracts import (
    AnalysisPeriod,
    ComparisonResult,
    E1SunlightStatistics,
    E1ExperimentPlan,
    E1_PLAN_LABEL,
    E1_PLAN_REVISION,
    E1PipelineRunResult,
    GroundGridDefinition,
    Obstacle,
    PipelineExecutionStatus,
    SensorGridResult,
    SensorPoint,
    SiteLocation,
    SunlightSimulationResult,
)
from .geometry_adapter import (
    extract_building_footprints,
    massing_to_obstacles,
    validate_coordinate_units,
)
from .sensors import (
    compute_area_weighted_metric,
    create_sensor_grid_result,
    generate_ground_sensor_grid,
)
from .sunlight import (
    calculate_direct_sunlight_hours,
    create_sunlight_colormap_spec,
    is_radiance_available,
)


def _compute_period_hash(period: AnalysisPeriod) -> str:
    payload = {
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
        "dates": [d.isoformat() for d in (period.dates or [])],
        "start_hour": round(float(period.start_hour), 4),
        "end_hour": round(float(period.end_hour), 4),
        "timestep": int(period.timestep),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _compute_solar_hash(location: SiteLocation, period: AnalysisPeriod, true_north_deg: float) -> str:
    payload = {
        "lat": round(float(location.latitude), 6),
        "lon": round(float(location.longitude), 6),
        "tz": str(location.timezone),
        "true_north": round(float(true_north_deg), 6),
        "period": _compute_period_hash(period),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _normalize_polygonal_domain(value: Any, name: str) -> Polygon | MultiPolygon:
    if isinstance(value, (Polygon, MultiPolygon)):
        polygon = value
    elif isinstance(value, (list, tuple)):
        polygon = Polygon(value)
    elif isinstance(value, dict):
        if "type" not in value and "coordinates" in value:
            polygon = Polygon(value.get("coordinates", [[]])[0])
        else:
            polygon = shape(value)
    else:
        raise ValueError(f"{name} is missing or has an unsupported geometry type")
    if polygon.geom_type not in {"Polygon", "MultiPolygon"} or polygon.is_empty or not polygon.is_valid:
        raise ValueError(f"{name} must be a valid, non-empty Polygon or MultiPolygon")
    return polygon


def _e1_plan_revision(plan: E1ExperimentPlan) -> str:
    return E1_PLAN_REVISION if plan.status == "DRAFT_UNAPPROVED" else plan.status


def _march_21_statistics(
    simulation: SunlightSimulationResult,
    domain: Polygon | MultiPolygon,
) -> E1SunlightStatistics | None:
    date_key = "2026-03-21"
    if date_key not in simulation.daily_results:
        return None
    values = [
        point.sunlight_hours
        for point in simulation.daily_results[date_key]
        if point.status == "VALID"
    ]
    if not values or domain.area <= 0:
        return None
    over_two = sum(value >= 2.0 for value in values)
    return E1SunlightStatistics(
        date=date_key,
        sensor_count=len(values),
        mean_hours=round(math.fsum(values) / len(values), 6),
        median_hours=round(statistics.median(values), 6),
        sensors_at_least_2_hours=over_two,
        sensors_at_least_2_hours_pct=round(100.0 * over_two / len(values), 4),
        domain_area_m2=round(domain.area, 4),
    )


CROSS_CHECK_SAMPLE_SIZE = 48
CROSS_CHECK_SAMPLE_SEED = 20261004


def select_cross_check_sensors(points: Sequence[Any], *, scope: Literal["stratified", "full"] = "stratified") -> tuple[list[Any], dict[str, Any]]:
    """Pick the Python cross-check sample.

    Stratified mode keeps a fixed count and a fixed seed. Full comparison stays
    available when the caller asks for it. Fewer valid points than the sample
    size uses every valid point and says so.
    """
    valid = [point for point in points if getattr(point, "status", "VALID") == "VALID"]
    ordered = sorted(valid, key=lambda point: point.point_id)
    if scope == "full" or len(ordered) <= CROSS_CHECK_SAMPLE_SIZE:
        mode = "FULL" if scope == "full" else "FULL_BECAUSE_POPULATION_WITHIN_SAMPLE"
        chosen = ordered
    else:
        mode = "STRATIFIED_FIXED_COUNT"
        generator = random.Random(CROSS_CHECK_SAMPLE_SEED)
        chosen = []
        for index in range(CROSS_CHECK_SAMPLE_SIZE):
            start = index * len(ordered) // CROSS_CHECK_SAMPLE_SIZE
            end = (index + 1) * len(ordered) // CROSS_CHECK_SAMPLE_SIZE
            chunk = ordered[start:end]
            chosen.append(chunk[generator.randrange(len(chunk))])
    return chosen, {
        "mode": mode,
        "sample_size_requested": CROSS_CHECK_SAMPLE_SIZE,
        "sample_size_used": len(chosen),
        "population_valid_count": len(ordered),
        "seed": CROSS_CHECK_SAMPLE_SEED,
        "rule": "Sort valid paired sensors by point_id, split into equal index bins, draw one point per bin with Random(20261004). Full comparison is optional.",
    }


def run_e1_environment_pipeline(
    plan: E1ExperimentPlan,
    baseline_geometry: Sequence[Any],
    modified_geometry: Sequence[Any],
    boundary_polygon: Any,
    method: Literal["ladybug_radiance", "pure_python_box_ray"] = "ladybug_radiance",
    store: Any | None = None,
    project_id: str = "rotterdam-m4h",
    run_id: str | None = None,
    coordinate_unit: str = "m",
    input_scenario_ids: Sequence[str] = (),
    input_artifact_ids: Sequence[str] = (),
    input_artifact_hashes: Sequence[str] = (),
    cross_check_method: Literal["pure_python_box_ray"] | None = None,
    cross_check_scope: Literal["stratified", "full"] = "stratified",
    excluded_obstacles_by_scenario: Mapping[str, Sequence[Mapping[str, str]]] | None = None,
    engine_selection: Mapping[str, Any] | None = None,
    baseline_domain: Any | None = None,
    modified_domain: Any | None = None,
    domain_sources: Mapping[str, Any] | None = None,
    authority_check: Any | None = None,
) -> E1PipelineRunResult:
    """Execute the complete E1 direct sunlight analysis pipeline.

    Fails closed / stops on:
    - Missing plan or pending/rejected plan (returns BLOCKED; DRAFT_UNAPPROVED is preview-only)
    - Missing or inexecutable runtime (returns BLOCKED)
    - Empty or invalid boundary / sensor grid (returns BLOCKED or FAIL)
    - Unit mismatches (returns FAIL)
    """
    active_run_id = run_id or f"e1_run_{uuid.uuid4().hex[:12]}"
    started_perf = time.perf_counter()

    if len(input_artifact_ids) != len(input_artifact_hashes):
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="FAIL",
            blocked_reason="INVALID_INPUT_PROVENANCE: artifact IDs and hashes must have matching lengths",
            plan=plan,
            method=method,
        )

    # Gate 1: Coordinate unit validation
    try:
        validate_coordinate_units(coordinate_unit)
    except Exception as exc:
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="FAIL",
            blocked_reason=f"INVALID_UNITS: {exc}",
            plan=plan,
            method=method,
        )

    # Gate 2: Founder approval point (Stop loss rule)
    if not plan.is_executable:
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="BLOCKED",
            blocked_reason="FOUNDER_APPROVAL_REQUIRED: E1 experiment plan pending Founder approval",
            plan=plan,
            method=method,
            metadata={
                "governance_note": "Human approval required for climate experiment plan; cannot fake approval or upgrade draft preview.",
                "plan_status": plan.status,
            },
        )

    # Gate 3: Runtime availability check
    if method == "ladybug_radiance" and not is_radiance_available():
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="BLOCKED",
            blocked_reason="RUNTIME_NOT_AVAILABLE: Radiance 6.0.2 is not operational or missing",
            plan=plan,
            method=method,
        )

    # Gate 4: Boundary validation
    try:
        poly_boundary = _normalize_polygonal_domain(boundary_polygon, "Boundary polygon")
        base_domain = _normalize_polygonal_domain(
            baseline_domain if baseline_domain is not None else poly_boundary,
            "Baseline public-space domain",
        )
        mod_domain = _normalize_polygonal_domain(
            modified_domain if modified_domain is not None else poly_boundary,
            "Modified public-space domain",
        )
        paired_domain = poly_boundary.intersection(base_domain).intersection(mod_domain)
        if isinstance(paired_domain, GeometryCollection) or paired_domain.geom_type == "GeometryCollection":
            polygon_parts = [
                part
                for part in paired_domain.geoms
                if isinstance(part, (Polygon, MultiPolygon)) and part.area > 0.0
            ]
            paired_domain = unary_union(polygon_parts) if polygon_parts else GeometryCollection()
        if paired_domain.is_empty or not paired_domain.is_valid or paired_domain.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Common overlap of the scheme domains is empty or invalid")
    except Exception as exc:
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="FAIL",
            blocked_reason=f"INVALID_GEOMETRY: {exc}",
            plan=plan,
            method=method,
        )

    # Convert platform geometries to 3D Obstacles
    source_tag = (
        "APPROVED"
        if plan.status == "APPROVED"
        else "DRAFT_UNAPPROVED"
        if plan.status == "DRAFT_UNAPPROVED"
        else "FIXTURE_ONLY"
    )
    baseline_obstacles = massing_to_obstacles(baseline_geometry, source=source_tag)
    modified_obstacles = massing_to_obstacles(modified_geometry, source=source_tag)

    baseline_footprints = extract_building_footprints(baseline_obstacles)
    modified_footprints = extract_building_footprints(modified_obstacles)

    # Generate ground sensor grids
    grid_def = plan.grid_definition
    try:
        base_sensors = generate_ground_sensor_grid(
            boundary=base_domain,
            spacing_m=grid_def.spacing_m,
            origin=(grid_def.origin_x, grid_def.origin_y),
            building_footprints=baseline_footprints,
            crs=grid_def.crs,
        )
        mod_sensors = generate_ground_sensor_grid(
            boundary=mod_domain,
            spacing_m=grid_def.spacing_m,
            origin=(grid_def.origin_x, grid_def.origin_y),
            building_footprints=modified_footprints,
            crs=grid_def.crs,
        )
        paired_sensors = generate_ground_sensor_grid(
            boundary=paired_domain,
            spacing_m=grid_def.spacing_m,
            origin=(grid_def.origin_x, grid_def.origin_y),
            building_footprints=[*baseline_footprints, *modified_footprints],
            crs=grid_def.crs,
        )
    except Exception as exc:
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="FAIL",
            blocked_reason=f"SENSOR_GRID_ERROR: {exc}",
            plan=plan,
            method=method,
        )

    valid_base_count = sum(1 for p in base_sensors if p.status == "VALID")
    if valid_base_count == 0:
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="BLOCKED",
            blocked_reason="EMPTY_SENSOR_GRID: Boundary contains zero valid sensor points outside building footprints",
            plan=plan,
            method=method,
        )

    paired_sensor_ids = {
        point.point_id for point in paired_sensors if point.status == "VALID"
    }
    base_sensor_ids = {point.point_id for point in base_sensors if point.status == "VALID"}
    mod_sensor_ids = {point.point_id for point in mod_sensors if point.status == "VALID"}
    paired_sensor_ids &= base_sensor_ids & mod_sensor_ids
    if not paired_sensor_ids:
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="BLOCKED",
            blocked_reason="EMPTY_PAIRED_SENSOR_GRID: Common overlap contains zero sensors valid in both schemes",
            plan=plan,
            method=method,
        )
    paired_sensors = [point for point in paired_sensors if point.point_id in paired_sensor_ids]

    # Execute direct sunlight simulations
    baseline_started = time.perf_counter()
    base_sim = calculate_direct_sunlight_hours(
        location=plan.location,
        period=plan.period,
        sensor_points=base_sensors,
        obstacles=baseline_obstacles,
        method=method,
        true_north_offset_deg=plan.true_north_offset_deg,
    )
    baseline_elapsed_seconds = round(time.perf_counter() - baseline_started, 3)

    modified_started = time.perf_counter()
    mod_sim = calculate_direct_sunlight_hours(
        location=plan.location,
        period=plan.period,
        sensor_points=mod_sensors,
        obstacles=modified_obstacles,
        method=method,
        true_north_offset_deg=plan.true_north_offset_deg,
    )
    modified_elapsed_seconds = round(time.perf_counter() - modified_started, 3)
    if plan.status == "DRAFT_UNAPPROVED":
        base_sim = base_sim.model_copy(update={"fixture_tag": "DRAFT_UNAPPROVED"})
        mod_sim = mod_sim.model_copy(update={"fixture_tag": "DRAFT_UNAPPROVED"})

    selected_engine = (
        "ladybug-sunpath+python-raycast"
        if method == "pure_python_box_ray"
        else "ladybug-sunpath+ladybug-radiance"
    )
    runtime_selection_payload = dict(engine_selection or {
        "requested_engine": "ladybug-sunpath+ladybug-radiance",
        "selected_engine": selected_engine,
        "radiance_manifest_version": "6.0.2" if method == "ladybug_radiance" else None,
        "fallback_reason": None,
    })
    excluded_obstacles_payload = {
        "baseline": [dict(item) for item in (excluded_obstacles_by_scenario or {}).get("baseline", ())],
        "modified": [dict(item) for item in (excluded_obstacles_by_scenario or {}).get("modified", ())],
    }

    cross_check_payload: dict[str, Any] | None = None
    cross_check_sample: list[Any] = []
    cross_check_sample_meta: dict[str, Any] | None = None
    if cross_check_method is not None:
        try:
            cross_check_sample, cross_check_sample_meta = select_cross_check_sensors(
                paired_sensors, scope=cross_check_scope,
            )
            base_cross_check = calculate_direct_sunlight_hours(
                location=plan.location,
                period=plan.period,
                sensor_points=cross_check_sample,
                obstacles=baseline_obstacles,
                method=cross_check_method,
                true_north_offset_deg=plan.true_north_offset_deg,
            )
            mod_cross_check = calculate_direct_sunlight_hours(
                location=plan.location,
                period=plan.period,
                sensor_points=cross_check_sample,
                obstacles=modified_obstacles,
                method=cross_check_method,
                true_north_offset_deg=plan.true_north_offset_deg,
            )

            def compare_point_hours(
                primary: SunlightSimulationResult,
                reference: SunlightSimulationResult,
            ) -> dict[str, Any]:
                primary_by_id = {point.point_id: point for point in primary.results}
                reference_by_id = {point.point_id: point for point in reference.results}
                if primary_by_id.keys() != reference_by_id.keys():
                    return {
                        "status": "INCOMPARABLE",
                        "sensor_count": 0,
                        "reason": "Sensor point IDs differ between the primary and cross-check engines.",
                    }
                differences = [
                    abs(primary_by_id[point_id].sunlight_hours - reference_by_id[point_id].sunlight_hours)
                    for point_id in primary_by_id
                    if primary_by_id[point_id].status == "VALID" and reference_by_id[point_id].status == "VALID"
                ]
                if not differences:
                    return {
                        "status": "INCOMPARABLE",
                        "sensor_count": 0,
                        "reason": "No matching valid sensor points were available for the cross-check.",
                    }
                mean_absolute_delta = sum(differences) / len(differences)
                return {
                    "status": "PASS" if mean_absolute_delta <= 0.25 else "DISAGREEMENT",
                    "sensor_count": len(differences),
                    "mean_absolute_delta_hours": round(mean_absolute_delta, 4),
                    "max_absolute_delta_hours": round(max(differences), 4),
                }

            sample_ids = {point.point_id for point in cross_check_sample}

            def select_paired(simulation: SunlightSimulationResult) -> SunlightSimulationResult:
                return simulation.model_copy(update={
                    "results": [point for point in simulation.results if point.point_id in sample_ids],
                    "daily_results": {
                        day: [point for point in points if point.point_id in sample_ids]
                        for day, points in simulation.daily_results.items()
                    },
                })

            baseline_cross_check = compare_point_hours(select_paired(base_sim), base_cross_check)
            modified_cross_check = compare_point_hours(select_paired(mod_sim), mod_cross_check)
            overall_status = (
                "PASS"
                if baseline_cross_check["status"] == "PASS" and modified_cross_check["status"] == "PASS"
                else "DISAGREEMENT"
                if baseline_cross_check["status"] == "DISAGREEMENT" or modified_cross_check["status"] == "DISAGREEMENT"
                else "INCOMPARABLE"
            )
            cross_check_payload = {
                "status": overall_status,
                "primary_engine": selected_engine,
                "cross_check_engine": "ladybug-sunpath+python-raycast",
                "tolerance_mean_absolute_delta_hours": 0.25,
                "sample": cross_check_sample_meta,
                "baseline": baseline_cross_check,
                "modified": modified_cross_check,
            }
        except Exception as exc:
            cross_check_payload = {
                "status": "UNAVAILABLE",
                "primary_engine": selected_engine,
                "cross_check_engine": "ladybug-sunpath+python-raycast",
                "tolerance_mean_absolute_delta_hours": 0.25,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    # Aggregate area-weighted metrics
    base_vals = {p.point_id: p.sunlight_hours for p in base_sim.results}
    mod_vals = {p.point_id: p.sunlight_hours for p in mod_sim.results}

    base_grid_res = create_sensor_grid_result(
        points=base_sensors,
        values=base_vals,
        spacing_m=grid_def.spacing_m,
        origin=(grid_def.origin_x, grid_def.origin_y),
        crs=grid_def.crs,
    )
    mod_grid_res = create_sensor_grid_result(
        points=mod_sensors,
        values=mod_vals,
        spacing_m=grid_def.spacing_m,
        origin=(grid_def.origin_x, grid_def.origin_y),
        crs=grid_def.crs,
    )
    paired_base_grid_res = create_sensor_grid_result(
        points=paired_sensors,
        values=base_vals,
        spacing_m=grid_def.spacing_m,
        origin=(grid_def.origin_x, grid_def.origin_y),
        crs=grid_def.crs,
    )
    paired_mod_grid_res = create_sensor_grid_result(
        points=paired_sensors,
        values=mod_vals,
        spacing_m=grid_def.spacing_m,
        origin=(grid_def.origin_x, grid_def.origin_y),
        crs=grid_def.crs,
    )
    baseline_march_21_statistics = _march_21_statistics(base_sim, base_domain)
    modified_march_21_statistics = _march_21_statistics(mod_sim, mod_domain)

    # Hashes for within-method comparison validation
    grid_hash = _compute_grid_hash(grid_def.model_dump())
    period_hash = _compute_period_hash(plan.period)
    solar_hash = _compute_solar_hash(plan.location, plan.period, plan.true_north_offset_deg)

    base_run_record = {
        "method": method,
        "grid_hash": grid_hash,
        "weather_hash": solar_hash,
        "period_hash": period_hash,
        "area_weighted_average": paired_base_grid_res.area_weighted_average,
        "points": [p.model_dump() for p in paired_sensors],
    }
    mod_run_record = {
        "method": method,
        "grid_hash": grid_hash,
        "weather_hash": solar_hash,
        "period_hash": period_hash,
        "area_weighted_average": paired_mod_grid_res.area_weighted_average,
        "points": [p.model_dump() for p in paired_sensors],
    }

    try:
        comparison = compare_environmental_runs(base_run_record, mod_run_record)
    except IncompatibleComparisonError as exc:
        return E1PipelineRunResult(
            run_id=active_run_id,
            status="FAIL",
            blocked_reason=f"COMPARISON_REJECTED: {exc}",
            plan=plan,
            method=method,
            baseline_sunlight=base_sim,
            modified_sunlight=mod_sim,
        )

    # Uniform colormap specification: both runs share the exact same scale
    max_daytime_hours = max(base_sim.daytime_hours, 10.0)
    colormap_spec = create_sunlight_colormap_spec(max_hours=max_daytime_hours, num_bins=5)
    plan_revision = _e1_plan_revision(plan)
    plan_label = E1_PLAN_LABEL if plan.status == "DRAFT_UNAPPROVED" else f"E1_PLAN: {plan_revision}"
    comparison.metadata.update({
        "paired_domain": "COMMON_OVERLAP",
        "analysis_extent": "geometric_analysis_extent",
        "legal_right_of_way": False,
        "domain_disclaimer": "Geometric analysis extent only. This extent is not a legal right of way.",
        "paired_sensor_count": len(paired_sensor_ids),
        "paired_domain_area_m2": round(paired_domain.area, 4),
        "baseline_domain_area_m2": round(base_domain.area, 4),
        "modified_domain_area_m2": round(mod_domain.area, 4),
        "baseline_sensor_count": base_grid_res.valid_points,
        "modified_sensor_count": mod_grid_res.valid_points,
    })

    # Build immutable persistence payloads
    now_utc = datetime.now(timezone.utc)
    tool_name = "urban_design.environment.sunlight"
    tool_ver = "ladybug-sunpath-python-raycast-v1" if method == "pure_python_box_ray" else "6.0.2"
    exec_id = f"tool-exec-e1-{active_run_id}"
    artifact_id = f"artifact-e1-{active_run_id}"
    evidence_id = f"evidence-e1-{active_run_id}"

    bundle_payload = {
        "run_id": active_run_id,
        "E1_PLAN": plan_revision,
        "plan_label": plan_label,
        "plan_status": plan.status,
        "plan_id": plan.plan_id,
        "method": method,
        "engine": selected_engine,
        "engine_selection": runtime_selection_payload,
        "cross_check": cross_check_payload,
        "excluded_obstacles": excluded_obstacles_payload,
        "comparison_domain": plan.comparison_domain,
        "domain_sources": None if domain_sources is None else dict(domain_sources),
        "scenario_ids": list(input_scenario_ids) or [
            scenario_id
            for scenario_id in (plan.baseline_scenario_id, plan.modified_scenario_id)
            if scenario_id is not None
        ],
        "input_artifact_ids": list(input_artifact_ids),
        "input_artifact_hashes": list(input_artifact_hashes),
        "location": plan.location.model_dump(),
        "period": {
            "start_date": plan.period.start_date.isoformat(),
            "end_date": plan.period.end_date.isoformat(),
            "dates": [d.isoformat() for d in (plan.period.dates or [])],
            "start_hour": plan.period.start_hour,
            "end_hour": plan.period.end_hour,
            "timestep": plan.period.timestep,
        },
        "baseline_summary": {
            "valid_sensors": base_grid_res.valid_points,
            "area_weighted_average_hours": base_grid_res.area_weighted_average,
            "daytime_hours": base_sim.daytime_hours,
            "domain_area_m2": round(base_domain.area, 4),
            "march_21_informational_statistics": baseline_march_21_statistics.model_dump(mode="json") if baseline_march_21_statistics else None,
        },
        "modified_summary": {
            "valid_sensors": mod_grid_res.valid_points,
            "area_weighted_average_hours": mod_grid_res.area_weighted_average,
            "daytime_hours": mod_sim.daytime_hours,
            "domain_area_m2": round(mod_domain.area, 4),
            "march_21_informational_statistics": modified_march_21_statistics.model_dump(mode="json") if modified_march_21_statistics else None,
        },
        "comparison": comparison.model_dump(),
        "paired_domain": {
            "definition": "Intersection of both schemes' public-space domains inside the supplied boundary.",
            "area_m2": round(paired_domain.area, 4),
            "sensor_count": len(paired_sensor_ids),
            "sensor_ids": sorted(paired_sensor_ids),
        },
        "colormap": colormap_spec.model_dump(),
        "baseline_results": [p.model_dump(mode="json") for p in base_sim.results],
        "modified_results": [p.model_dump(mode="json") for p in mod_sim.results],
    }
    bundle_bytes = json.dumps(bundle_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    bundle_sha = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
    # Wall time stays outside the hashed bundle so a slower machine does not change the result hash.
    elapsed_seconds = round(time.perf_counter() - started_perf, 3)

    # Approval of an experiment never accepts the geometry of its draft.
    scenario_pins = [v.model_dump(mode="json") for v in plan.frozen_inputs]
    draft_result = False
    if store is not None and plan.modified_scenario_id:
        modified_record = store.current(plan.modified_scenario_id)
        draft_result = (str(modified_record.payload.get("status", "")).lower() == "draft"
                        or modified_record.payload.get("parameters", {}).get("provenance") == "FORMAL_DRAFT")
    modified_pin = next((v for v in scenario_pins if v["scenario_id"] == plan.modified_scenario_id), {})
    # Domain Models
    tool_exec_model = ToolExecution(
        id=exec_id,
        project_id=project_id,
        scenario_id=plan.modified_scenario_id,
        tool=tool_name,
        tool_version=tool_ver,
        environment={
            "python_raycaster": "enabled" if method == "pure_python_box_ray" else "disabled",
            "radiance_available": str(is_radiance_available()).lower(),
            "timezone": plan.location.timezone,
            "crs": plan.grid_definition.crs,
        },
        input_refs=list(input_scenario_ids),
        input_artifact_ids=list(input_artifact_ids),
        input_artifact_hashes=list(input_artifact_hashes),
        input_artifact_hashes_by_id=dict(zip(input_artifact_ids, input_artifact_hashes)),
        parameters={
            "scenario_revision": modified_pin.get("scenario_revision"),
            "scenario_pins": scenario_pins,
            "result_scope": "DRAFT" if draft_result else "SCENARIO_ANALYSIS",
            "method": method,
            "engine": bundle_payload["engine"],
            "engine_selection": runtime_selection_payload,
            "cross_check": cross_check_payload,
            "E1_PLAN": plan_revision,
            "plan_label": plan_label,
            "plan_status": plan.status,
            "comparison_domain": plan.comparison_domain,
            "analysis_dates": [d.isoformat() for d in (plan.period.dates or [])],
            "timestep": plan.period.timestep,
            "true_north_offset_deg": plan.true_north_offset_deg,
            "spacing_m": grid_def.spacing_m,
            "unit": "hours",
            "elapsed_seconds": elapsed_seconds,
            "baseline_elapsed_seconds": baseline_elapsed_seconds,
            "modified_elapsed_seconds": modified_elapsed_seconds,
            "domain_sources": None if domain_sources is None else dict(domain_sources),
        },
        idempotency_key=f"ik_e1_{active_run_id}",
        status=RunStatus.SUCCEEDED,
        output_artifact_refs=[artifact_id],
        output_artifact_hashes=[bundle_sha],
        limitations=[
            "Direct beam sunlight duration only; does not model diffuse solar radiation.",
            "Weather Epw data suspended; uses clear-sky geometric direct sun vectors.",
        ],
    )

    artifact_model = Artifact(
        id=artifact_id,
        type="sunlight_simulation_result",
        uri=f"store://artifacts/environment/{artifact_id}",
        sha256=bundle_sha,
        mime="application/json",
        crs=plan.grid_definition.crs,
        producer=tool_name,
        created_at=now_utc,
        project_id=project_id,
        size_bytes=len(bundle_bytes),
    )

    evidence_card_model = EvidenceCard(
        id=evidence_id,
        project_id=project_id,
        scenario_id=plan.modified_scenario_id,
        claim=Claim(
            id=f"claim-e1-{active_run_id}",
            type=ClaimType.COMPARISON,
            statement=(
                f"Direct sunlight analysis for selected dates "
                f"{', '.join(d.isoformat() for d in (plan.period.dates or [plan.period.start_date]))} shows a "
                f"{comparison.direction_of_change.lower()} in area-weighted ground sunlight hours "
                f"(delta: {comparison.delta_mean:+.2f} h) under method {method}."
            ),
        ),
        metric=MetricReference(
            id="direct_sunlight_hours",
            name="Direct Sunlight Duration",
            unit="hours",
        ),
        method=MethodReference(
            id=f"e1_direct_sunlight_{method}",
            description=f"Direct sunlight hour ray-intersection simulation using {method}",
        ),
        tool=tool_name,
        tool_version=tool_ver,
        units="hours",
        result=EvidenceResult(
            artifact_refs=[artifact_id],
            artifact_hashes=[bundle_sha],
            status=ResultStatus.COMPUTED,
            values={
                "baseline_mean_hours": paired_base_grid_res.area_weighted_average,
                "modified_mean_hours": paired_mod_grid_res.area_weighted_average,
                "delta_mean_hours": comparison.delta_mean,
                "direction_of_change": comparison.direction_of_change,
                "occupied_sensor_count": len(comparison.occupied_points),
                "paired_sensor_count": len(paired_sensor_ids),
                "baseline_march_21_informational_statistics": baseline_march_21_statistics.model_dump(mode="json") if baseline_march_21_statistics else None,
                "modified_march_21_informational_statistics": modified_march_21_statistics.model_dump(mode="json") if modified_march_21_statistics else None,
            },
        ),
        confidence=Confidence(
            level=ConfidenceLevel.UNKNOWN if plan.status == "DRAFT_UNAPPROVED" else ConfidenceLevel.MEDIUM,
            basis="Deterministic geometric direct-sun screening; experiment plan approval status is recorded separately",
            uncertainty="Plan is unapproved; diffuse radiation, terrain, materials, weather, and measured context are excluded",
            assessed_by="urban_design_environment_pipeline",
        ),
        validation_status=(
            EvidenceValidationStatus.UNVERIFIED
            if plan.status == "DRAFT_UNAPPROVED" or draft_result
            else EvidenceValidationStatus.VALIDATED
        ),
        human_status=HumanStatus.NOT_REVIEWED,
        created_at=now_utc,
    )

    # Persist if store is provided
    if store is not None:
        store.create(
            entity_type="Artifact",
            payload={**artifact_model.model_dump(mode="json"), "bundle": bundle_payload},
            entity_id=artifact_id,
            project_id=project_id,
            actor="environment_pipeline",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            action="CreateArtifact",
        )
        store.create_typed(
            tool_exec_model,
            actor="environment_pipeline",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            action="CreateToolExecution",
            reason=f"E1 {plan.status} deterministic sunlight run",
        )
        initial_evidence = evidence_card_model.model_copy(deep=True)
        initial_evidence.validation_status = EvidenceValidationStatus.UNVERIFIED
        initial_evidence.result.validation_status = EvidenceValidationStatus.UNVERIFIED
        store.create_typed(initial_evidence, actor="environment_pipeline",
                           actor_kind=ActorKind.AGENT_AUTOMATION, action="CreateEvidenceCard",
                           reason=f"E1 {plan.status} result retained before promotion")
        if plan.status == "APPROVED" and not draft_result:
            if authority_check is None:
                raise ValueError("E1_PROMOTION_AUTHORITY_CHECK_REQUIRED")
            store.update(evidence_id, evidence_card_model.model_dump(mode="json"), replace=True,
                         actor="environment_pipeline", actor_kind=ActorKind.AGENT_AUTOMATION,
                         action="PromoteE1Evidence", before_commit=authority_check)

    return E1PipelineRunResult(
        run_id=active_run_id,
        status="SUCCESS",
        plan=plan,
        method=method,
        engine=bundle_payload["engine"],
        baseline_sunlight=base_sim,
        modified_sunlight=mod_sim,
        baseline_march_21_statistics=baseline_march_21_statistics,
        modified_march_21_statistics=modified_march_21_statistics,
        comparison=comparison,
        colormap_spec=colormap_spec,
        tool_execution=tool_exec_model.model_dump(),
        artifact=artifact_model.model_dump(),
        evidence_card=evidence_card_model.model_dump(),
        metadata={
            "baseline_mean_hours": paired_base_grid_res.area_weighted_average,
            "modified_mean_hours": paired_mod_grid_res.area_weighted_average,
            "baseline_sensor_count": base_grid_res.valid_points,
            "modified_sensor_count": mod_grid_res.valid_points,
            "paired_sensor_count": len(paired_sensor_ids),
            "baseline_domain_area_m2": round(base_domain.area, 4),
            "modified_domain_area_m2": round(mod_domain.area, 4),
            "paired_domain_area_m2": round(paired_domain.area, 4),
            "delta_mean_hours": comparison.delta_mean,
            "direction_of_change": comparison.direction_of_change,
            "occupied_sensor_count": len(comparison.occupied_points),
            "bundle_sha256": bundle_sha,
            "analysis_window": f"{plan.period.start_date.isoformat()} {plan.period.start_hour:02.0f}:00 - {plan.period.end_hour:02.0f}:00",
            "unit": "hours",
            "engine": bundle_payload["engine"],
            "engine_selection": runtime_selection_payload,
            "cross_check": cross_check_payload,
            "excluded_obstacles": excluded_obstacles_payload,
            "E1_PLAN": plan_revision,
            "plan_label": plan_label,
            "plan_status": plan.status,
            "analysis_dates": [d.isoformat() for d in (plan.period.dates or [])],
            "comparison_domain": plan.comparison_domain,
            "baseline_march_21_statistics": baseline_march_21_statistics.model_dump(mode="json") if baseline_march_21_statistics else None,
            "modified_march_21_statistics": modified_march_21_statistics.model_dump(mode="json") if modified_march_21_statistics else None,
            "paired_sensor_ids": sorted(paired_sensor_ids),
            "elapsed_seconds": elapsed_seconds,
            "baseline_elapsed_seconds": baseline_elapsed_seconds,
            "modified_elapsed_seconds": modified_elapsed_seconds,
            "domain_sources": None if domain_sources is None else dict(domain_sources),
        },
    )
