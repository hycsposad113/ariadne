"""Fail-closed E2 radiation input contract for the W6 weather pause.

This module validates reference presence only. It never opens weather files,
resolves authority records, or dispatches a radiation calculation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


RadiationMethod = Literal["ladybug_radiance", "honeybee_radiance"]
InputStatus = Literal["NOT_READY", "FIXTURE_ONLY", "ASSUMED", "UNAPPROVED_PREVIEW"]

# This package has no authority path for changing this value. A later execution
# package must explicitly replace this contract after Founder authorization.
E2_WEATHER_PAUSE_ACTIVE = True

_SHARED_REQUIRED_REFERENCES = (
    "weather_snapshot_ref",
    "experiment_plan_ref",
    "scenario_revision_ref",
    "geometry_hash",
    "sensor_grid_hash",
    "method_runtime_manifest_ref",
    "radiance_runtime_manifest_ref",
    "recipe_ref",
    "period_ref",
    "context_ref",
    "material_assumptions_ref",
    "true_north_ref",
    "time_convention_ref",
    "settings_ref",
    "comparison_domain_ref",
    "method_approval_ref",
    "experiment_approval_ref",
    "weather_pause_release_ref",
)


class RadiationInputReferences(BaseModel):
    """Opaque references required before a future, separately authorized E2 run."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    input_status: InputStatus = "NOT_READY"
    method: RadiationMethod | None = None
    weather_snapshot_ref: str | None = None
    experiment_plan_ref: str | None = None
    scenario_revision_ref: str | None = None
    geometry_hash: str | None = None
    sensor_grid_hash: str | None = None
    method_runtime_manifest_ref: str | None = None
    radiance_runtime_manifest_ref: str | None = None
    recipe_ref: str | None = None
    period_ref: str | None = None
    context_ref: str | None = None
    material_assumptions_ref: str | None = None
    true_north_ref: str | None = None
    time_convention_ref: str | None = None
    settings_ref: str | None = None
    comparison_domain_ref: str | None = None
    method_approval_ref: str | None = None
    experiment_approval_ref: str | None = None
    weather_pause_release_ref: str | None = None


class RadiationPreconditionReport(BaseModel):
    """Validation-only result; this W6-12 contract cannot permit dispatch."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["BLOCKED"] = "BLOCKED"
    method: RadiationMethod | None = None
    dispatch_allowed: Literal[False] = False
    weather_file_read: Literal[False] = False
    e2_dispatch_attempted: Literal[False] = False
    missing_references: tuple[str, ...] = ()
    blockers: tuple[str, ...]


def validate_radiation_preconditions(
    inputs: RadiationInputReferences,
) -> RadiationPreconditionReport:
    """Report missing E2 references while preserving the active weather pause.

    Reference values are treated as opaque strings. Presence does not establish
    that an artifact exists, that an approval is authoritative, or that its
    status is anything other than the supplied fixture/assumption label.
    """
    required_references = list(_SHARED_REQUIRED_REFERENCES)
    required_references.append("method")
    missing = [
        name
        for name in required_references
        if not _reference_is_present(getattr(inputs, name))
    ]

    blockers = ["E2_WEATHER_PAUSE_ACTIVE"] if E2_WEATHER_PAUSE_ACTIVE else []
    if missing:
        blockers.append("MISSING_REQUIRED_REFERENCES")
    # No approval status is representable in this work package's input schema.
    blockers.append("INPUTS_NOT_APPROVED")

    return RadiationPreconditionReport(
        method=inputs.method,
        missing_references=tuple(missing),
        blockers=tuple(blockers),
    )


def _reference_is_present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


class MethodControlLimits(BaseModel):
    """Separate material, reflectance, and recipe limits for one E2 method."""

    model_config = ConfigDict(extra="forbid")

    method: RadiationMethod
    role: Literal["screening", "verification"]
    reported_quantity: Literal["area_weighted_summer_cumulative_incident_radiation"]
    material: Literal["NOT_APPROVED"] = "NOT_APPROVED"
    reflectance: Literal["NOT_APPROVED"] = "NOT_APPROVED"
    recipe: Literal["NOT_APPROVED"] = "NOT_APPROVED"


class FormalE2Refusal(BaseModel):
    """Formal E2 stays blocked until Founder approval. The gate is not a pass."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["BLOCKED"] = "BLOCKED"
    gate: Literal["READY_FOR_FOUNDER"] = "READY_FOR_FOUNDER"
    dispatch_allowed: Literal[False] = False
    weather_file_read: Literal[False] = False
    e2_dispatch_attempted: Literal[False] = False
    dataset_snapshot_published: Literal[False] = False
    human_decision_created: Literal[False] = False
    job_created: Literal[False] = False
    scheduler_created: Literal[False] = False
    job_mechanism: Literal[
        "urban_design.generation.job_store.GenerationJobStore"
    ] = "urban_design.generation.job_store.GenerationJobStore"
    job_runner: Literal[
        "urban_design.generation.job_runner.GenerationJobRunner"
    ] = "urban_design.generation.job_runner.GenerationJobRunner"
    comparison_extent: Literal["geometric_analysis_extent"] = "geometric_analysis_extent"
    pairwise_domain: Literal["COMMON_OVERLAP"] = "COMMON_OVERLAP"
    legal_right_of_way: Literal[False] = False
    weather_pause_active: Literal[True] = True
    missing_references: tuple[str, ...] = ()
    blockers: tuple[str, ...]
    method_limits: tuple[MethodControlLimits, MethodControlLimits]
    sensitivity_direction: Literal[
        "REVERSED",
        "NOT_REVERSED",
        "NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS",
    ]


def e2_method_controls() -> tuple[MethodControlLimits, MethodControlLimits]:
    """Ladybug screening and Honeybee verification, with limits kept apart."""
    quantity = "area_weighted_summer_cumulative_incident_radiation"
    return (
        MethodControlLimits(
            method="ladybug_radiance",
            role="screening",
            reported_quantity=quantity,
        ),
        MethodControlLimits(
            method="honeybee_radiance",
            role="verification",
            reported_quantity=quantity,
        ),
    )


def label_hour_shift_comparison_direction(
    baseline_direction: str | None,
    shifted_direction: str | None,
) -> Literal[
    "REVERSED",
    "NOT_REVERSED",
    "NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS",
]:
    """Label whether a ±1 h shift reverses a within-method comparison direction."""
    assessable = {"INCREASED", "DECREASED", "UNCHANGED"}
    if baseline_direction not in assessable or shifted_direction not in assessable:
        return "NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS"
    if {baseline_direction, shifted_direction} == {"INCREASED", "DECREASED"}:
        return "REVERSED"
    return "NOT_REVERSED"


def refuse_formal_e2(
    inputs: RadiationInputReferences,
    *,
    dataset_snapshot_status: str | None = None,
    human_decision_id: str | None = None,
    baseline_direction: str | None = None,
    shifted_direction: str | None = None,
) -> FormalE2Refusal:
    """Refuse formal E2 dispatch. Caller-supplied approval text is not authority.

    DatasetSnapshot publication and HumanDecision creation stay outside this
    function. A future run enqueues only through the existing generation job
    store after those records exist.
    """
    precondition = validate_radiation_preconditions(inputs)
    blockers = list(precondition.blockers)
    blockers.append("DATASET_SNAPSHOT_NOT_APPROVED")
    if dataset_snapshot_status is not None or human_decision_id is not None:
        blockers.append("CALLER_SUPPLIED_APPROVAL_IS_NOT_AUTHORITY")
    if E2_WEATHER_PAUSE_ACTIVE is not True:
        blockers.append("E2_PAUSE_CONTRACT_CHANGED")
    return FormalE2Refusal(
        missing_references=precondition.missing_references,
        blockers=tuple(blockers),
        method_limits=e2_method_controls(),
        sensitivity_direction=label_hour_shift_comparison_direction(
            baseline_direction,
            shifted_direction,
        ),
    )
