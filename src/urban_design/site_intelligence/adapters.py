"""Deterministic projections of existing site and problem analysis results.

This module does not calculate geometry or validate source provenance. It makes
the limits of the existing result loaders explicit in a typed bundle.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    AnalysisExtent,
    CategoryCount,
    FrozenRef,
    Observation,
    SiteAnalysisBundle,
    compute_site_analysis_bundle_ref,
)


class ExistingAnalysisResults(BaseModel):
    """Values/statuses returned by existing deterministic functions or loaders."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    site_metrics: Any | None = None
    site_status: str = "NOT_RUN"
    site_method_version: str = "site-analysis-m4h-v1"
    syntax_bundle: Any | None = None
    syntax_status: str = "NOT_RUN"
    problem_definition: Any | None = None
    problem_status: str = "NOT_RUN"
    problem_method_version: str | None = None
    metric_scope_refs: dict[str, FrozenRef] = Field(default_factory=dict)
    metric_input_refs: dict[str, tuple[FrozenRef, ...]] = Field(default_factory=dict)
    metric_method_versions: dict[str, str] = Field(default_factory=dict)
    analysis_extents: tuple[AnalysisExtent, ...] = ()
    layer_refs: tuple[FrozenRef, ...] = ()
    coverage_refs: tuple[FrozenRef, ...] = ()
    tool_versions: dict[str, str] = Field(default_factory=dict)
    scenario_ref: FrozenRef | None = None


_SITE_METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("building.count", "building_count", "buildings", "buildings"),
    ("building.footprint_union_area_m2", "building_footprint_area_m2", "m2", "buildings"),
    ("building.ground_coverage_ratio", "ground_coverage_ratio", "ratio", "buildings"),
    ("water.area_m2", "water_area_m2", "m2", "water"),
    ("water.coverage_ratio", "water_coverage_ratio", "ratio", "water"),
    (
        "unclassified_surface_residual_area_m2",
        "unclassified_surface_residual_area_m2",
        "m2",
        "residual",
    ),
    (
        "unclassified_surface_residual_ratio",
        "unclassified_surface_residual_ratio",
        "ratio",
        "residual",
    ),
    ("road.segment_count", "road_segment_count", "segments", "roads"),
    ("road.total_length_m", "total_road_length_m", "m", "roads"),
)

_ALLOWED_LOADER_STATES = {
    "COMPUTED",
    "AVAILABLE",
    "PARTIAL",
    "VERIFIED_SOURCE_RESULT_ALIGNMENT",
}


def _unique_refs(refs: tuple[FrozenRef, ...] | list[FrozenRef]) -> tuple[FrozenRef, ...]:
    return tuple(dict.fromkeys(refs))


def _execution_blocker(status: str) -> str | None:
    normalized = str(status or "NOT_RUN").strip().upper()
    if normalized in {"NOT_RUN", "NOT_COMPUTED"}:
        return "NOT_RUN"
    return None if normalized in _ALLOWED_LOADER_STATES else normalized or "UNRECOGNIZED_LOADER_STATUS"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        candidates = (value,)
    elif isinstance(value, (list, tuple)):
        candidates = tuple(item for item in value if isinstance(item, str))
    else:
        candidates = ()
    return tuple(text.strip() for text in candidates if text.strip())


def _make_observation(
    *,
    metric_key: str,
    raw_value: Any,
    unit: str,
    method_version: str | None,
    scope_ref: FrozenRef,
    input_refs: tuple[FrozenRef, ...],
    blocker: str | None = None,
    domain_complete: bool = True,
    extra_limits: tuple[str, ...] = (),
    limitation_details: tuple[str, ...] = (),
    category_counts: tuple[CategoryCount, ...] = (),
    allow_empty_category_set: bool = False,
) -> Observation:
    limitations: list[str] = list(extra_limits)
    if blocker == "NOT_RUN":
        limitations.append("ANALYSIS_NOT_RUN")
        status = "NOT_RUN"
        value = None
        counts: tuple[CategoryCount, ...] = ()
    elif blocker is not None:
        limitations.append(blocker)
        limitations.append(f"SOURCE_STATUS_{blocker.replace(' ', '_')}")
        status = "BLOCKED"
        value = None
        counts: tuple[CategoryCount, ...] = ()
    elif not domain_complete:
        limitations.append("MISSING_OR_INCOMPLETE_SOURCE_COVERAGE")
        status = "BLOCKED"
        value = None
        counts = ()
    elif not method_version or not method_version.strip():
        limitations.append("METHOD_VERSION_MISSING")
        status = "BLOCKED"
        value = None
        counts = ()
    elif not input_refs or not any(ref != scope_ref for ref in input_refs):
        limitations.append("SOURCE_INPUT_REFERENCE_MISSING")
        status = "BLOCKED"
        value = None
        counts = ()
    elif raw_value is None and not category_counts and not allow_empty_category_set:
        limitations.append("SOURCE_VALUE_MISSING")
        status = "BLOCKED"
        value = None
        counts = ()
    elif raw_value is not None and _finite_number(raw_value) is None:
        limitations.append("SOURCE_VALUE_NOT_FINITE_NUMERIC")
        status = "BLOCKED"
        value = None
        counts = ()
    else:
        # The existing site calculations and loaders do not bind provenance to
        # server-verified immutable source hashes. Preserve values as partial.
        limitations.extend(("PROVENANCE_NOT_VERIFIED", "SOURCE_CRS_NOT_VERIFIED_BY_PROJECTION"))
        status = "PARTIAL"
        value = _finite_number(raw_value)
        counts = category_counts
    return Observation(
        metric_key=metric_key,
        status=status,
        value=value,
        category_counts=counts,
        unit=unit,
        method_version=(method_version or "method-unresolved"),
        scope_ref=scope_ref,
        input_refs=input_refs if status in {"AVAILABLE", "PARTIAL"} else (),
        limitation_codes=tuple(dict.fromkeys(limitations)),
        limitation_details=limitation_details,
    )


def _loader_refs(
    results: ExistingAnalysisResults,
    metric_key: str,
    source_refs: tuple[FrozenRef, ...],
    scope_ref: FrozenRef,
    *,
    extent: AnalysisExtent | None = None,
) -> tuple[FrozenRef, ...]:
    configured = results.metric_input_refs.get(metric_key)
    if configured is not None:
        candidates = configured
    elif extent is not None and extent.input_refs:
        candidates = extent.input_refs
    else:
        candidates = source_refs
    return _unique_refs([*candidates, scope_ref])


def _site_observations(
    results: ExistingAnalysisResults,
    source_refs: tuple[FrozenRef, ...],
    study_area_ref: FrozenRef,
) -> list[Observation]:
    raw_metrics = results.site_metrics
    metrics = raw_metrics if isinstance(raw_metrics, Mapping) else {}
    blocker = _execution_blocker(results.site_status)
    if raw_metrics is not None and not isinstance(raw_metrics, Mapping):
        blocker = "LOADER_RESULT_NOT_OBJECT"
    raw_source_status = metrics.get("source_data_status")
    source_status = raw_source_status if isinstance(raw_source_status, Mapping) else {}
    observations: list[Observation] = []
    for key, source_field, unit, domain in _SITE_METRICS:
        required_domains = ("buildings", "water") if domain == "residual" else (domain,)
        complete = all(source_status.get(item) == "DECLARED_COMPLETE_WITHIN_SCOPE" for item in required_domains)
        obs_blocker = blocker
        if raw_metrics is None and obs_blocker is None:
            obs_blocker = "SITE_RESULT_MISSING"
        limits = ("RESIDUAL_IS_NOT_BUILDABLE_OR_PUBLIC_SPACE",) if domain == "residual" else ()
        details: tuple[str, ...] = ()
        if key == "building.ground_coverage_ratio":
            details = (
                "Building footprint coverage is the union of clipped observed footprints divided by StudyArea area; it does not establish a planning or legal coverage allowance.",
                "Height and FAR are unavailable in the current PDOK snapshot; missing heights are not treated as zero.",
            )
        elif key in {"road.total_length_m", "road.segment_count"}:
            details = (
                "This is a sum of clipped source road lengths, not a graph or connectivity measure; overlapping or duplicate source features may be counted more than once.",
                "It does not establish public access, passability, safety, or travel time; OSM tags may omit access restrictions on port-facility roads.",
            )
        elif domain == "residual":
            details = (
                "Residual of observed building and BGT water geometries only; it is not open space, public access, ownership, availability, or buildability.",
            )
        source_details = _text_values(metrics.get("limitation_details", {}).get(key)) if isinstance(metrics.get("limitation_details"), Mapping) else ()
        details = tuple(dict.fromkeys((*details, *source_details)))
        inputs = _loader_refs(results, key, source_refs, study_area_ref)
        observations.append(
            _make_observation(
                metric_key=key,
                raw_value=metrics.get(source_field),
                unit=unit,
                method_version=results.metric_method_versions.get(
                    key, str(metrics.get("formula_version") or results.site_method_version)
                ),
                scope_ref=study_area_ref,
                input_refs=inputs,
                blocker=obs_blocker,
                domain_complete=complete,
                extra_limits=limits,
                limitation_details=details,
            )
        )

    usage = metrics.get("usage_distribution")
    usage_complete = source_status.get("buildings") == "DECLARED_COMPLETE_WITHIN_SCOPE"
    usage_counts: tuple[CategoryCount, ...] = ()
    invalid_usage = False
    if isinstance(usage, Mapping):
        collected: list[CategoryCount] = []
        for category, count in sorted(usage.items(), key=lambda item: str(item[0])):
            if not isinstance(category, str) or not category.strip() or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                invalid_usage = True
                break
            collected.append(CategoryCount(category=category, count=count))
        if not invalid_usage:
            usage_counts = tuple(collected)
    if isinstance(usage, Mapping):
        building_count = metrics.get("building_count")
        if type(building_count) is not int or building_count < 0 or sum(item.count for item in usage_counts) != building_count:
            invalid_usage = True
    if usage is not None and not isinstance(usage, Mapping):
        invalid_usage = True
    usage_observation = _make_observation(
        metric_key="building.registered_use_distribution",
        raw_value=None,
        unit="buildings by registered use category",
        method_version=results.metric_method_versions.get("building.registered_use_distribution", results.site_method_version),
        scope_ref=study_area_ref,
        input_refs=_loader_refs(results, "building.registered_use_distribution", source_refs, study_area_ref),
        blocker=("INVALID_USAGE_DISTRIBUTION" if invalid_usage else blocker),
        domain_complete=usage_complete,
        category_counts=usage_counts if usage_complete else (),
        extra_limits=("CATEGORY_COUNTS_ARE_NOT_RESIDENTIAL_COUNTS",),
        allow_empty_category_set=usage_complete and isinstance(usage, Mapping) and not usage and not invalid_usage,
    )
    if invalid_usage:
        usage_observation = usage_observation.model_copy(
            update={"limitation_codes": ("INVALID_USAGE_DISTRIBUTION",)}
        )
    observations.append(usage_observation)

    # A zero residential count is safe only for an explicitly complete empty
    # building source. Otherwise the existing helper does not publish a
    # separately validated residential count, height statistic, or FAR.
    residential_is_zero = (
        usage_complete
        and isinstance(usage, Mapping)
        and not usage
        and metrics.get("building_count") == 0
    )
    residential = _make_observation(
        metric_key="building.registered_residential_count",
        raw_value=0.0 if residential_is_zero else None,
        unit="buildings",
        method_version=results.metric_method_versions.get("building.registered_residential_count", results.site_method_version),
        scope_ref=study_area_ref,
        input_refs=_loader_refs(results, "building.registered_residential_count", source_refs, study_area_ref),
        blocker=blocker,
        domain_complete=usage_complete and residential_is_zero,
        extra_limits=("RESIDENTIAL_COUNT_ONLY_ZERO_FOR_COMPLETE_EMPTY_BUILDING_SOURCE",),
    )
    observations.append(residential)

    data_gaps = metrics.get("data_gaps") if isinstance(metrics.get("data_gaps"), (list, tuple)) else ()
    for key, unit, limit, source_field in (
        ("building.height_median_m", "m", "HEIGHT_DATA_UNAVAILABLE", "building_height"),
        ("building.floor_area_ratio", "ratio", "FAR_DATA_UNAVAILABLE", "floor_area_ratio"),
    ):
        not_run = raw_metrics is None and results.site_status.strip().upper() in {"NOT_RUN", "NOT_COMPUTED"}
        unavailable_status = "NOT_RUN" if not_run else "BLOCKED"
        limitation = ("ANALYSIS_NOT_RUN", limit) if not_run else (limit,)
        if blocker and not not_run:
            limitation = (*limitation, blocker)
        details = tuple(
            str(gap.get("impact")).strip()
            for gap in data_gaps
            if isinstance(gap, Mapping)
            and source_field in str(gap.get("field", "")).lower()
            and isinstance(gap.get("impact"), str)
            and gap.get("impact", "").strip()
        )
        observations.append(
            Observation(
                metric_key=key,
                status=unavailable_status,
                value=None,
                unit=unit,
                method_version=results.metric_method_versions.get(key, results.site_method_version),
                scope_ref=study_area_ref,
                input_refs=(),
                limitation_codes=limitation,
                limitation_details=details,
            )
        )
    return observations


def _problem_summary(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "to_summary_dict") and callable(value.to_summary_dict):
        try:
            value = value.to_summary_dict()
        except Exception:
            return None
    return value if isinstance(value, Mapping) else None


def _problem_observations(
    results: ExistingAnalysisResults,
    source_refs: tuple[FrozenRef, ...],
    study_area_ref: FrozenRef,
) -> list[Observation]:
    summary = _problem_summary(results.problem_definition)
    if summary is None:
        if results.problem_definition is None:
            return []
        return [
            _make_observation(
                metric_key="problem_definition.loader_result",
                raw_value=None,
                unit="unresolved",
                method_version=results.problem_method_version,
                scope_ref=study_area_ref,
                input_refs=(),
                blocker="LOADER_RESULT_NOT_OBJECT",
            )
        ]
    blocker = _execution_blocker(results.problem_status)
    metadata = summary.get("metadata") if isinstance(summary.get("metadata"), Mapping) else {}
    methodology = results.problem_method_version or metadata.get("methodology")
    output: list[Observation] = []
    raw_problems = summary.get("problems", ())
    if not isinstance(raw_problems, (list, tuple)):
        return [
            _make_observation(
                metric_key="problem_definition.loader_result",
                raw_value=None,
                unit="unresolved",
                method_version=results.problem_method_version,
                scope_ref=study_area_ref,
                input_refs=(),
                blocker="LOADER_RESULT_NOT_OBJECT",
            )
        ]
    malformed_nested_payload = False
    for problem in raw_problems:
        if not isinstance(problem, Mapping):
            malformed_nested_payload = True
            continue
        problem_metrics = problem.get("metrics", ())
        if not isinstance(problem_metrics, (list, tuple)):
            malformed_nested_payload = True
            continue
        for metric in problem_metrics:
            if not isinstance(metric, Mapping):
                malformed_nested_payload = True
                continue
            key = metric.get("key") or metric.get("metric_key")
            if not isinstance(key, str) or not key.strip():
                continue
            scope = results.metric_scope_refs.get(key)
            explicit_inputs = results.metric_input_refs.get(key)
            metric_blocker = blocker
            if scope is None:
                metric_blocker = "METRIC_SCOPE_REFERENCE_MISSING"
                scope = study_area_ref
            if explicit_inputs is None or not explicit_inputs:
                metric_blocker = "METRIC_INPUT_REFERENCES_MISSING"
                metric_inputs: tuple[FrozenRef, ...] = ()
            else:
                metric_inputs = _unique_refs([*explicit_inputs, scope])
            raw_method = results.metric_method_versions.get(key, methodology)
            if not isinstance(raw_method, str) or not raw_method.strip():
                metric_blocker = "METHOD_VERSION_MISSING"
            evidence_level = metric.get("evidence_level")
            if evidence_level is not None and evidence_level != "COMPUTED_RESULT":
                metric_blocker = f"EVIDENCE_LEVEL_{str(evidence_level).upper()}"
            elif evidence_level is None:
                metric_blocker = "EVIDENCE_LEVEL_MISSING"
            unit = metric.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                unit = "unit-unresolved"
                metric_blocker = "UNIT_MISSING"
            limitation_details = (
                *_text_values(problem.get("limitations")),
                *_text_values(metric.get("limitations")),
            )
            codes: list[str] = ["PROBLEM_OUTPUT_PROVENANCE_NOT_VERIFIED"]
            problem_status = problem.get("status")
            if isinstance(problem_status, str) and problem_status.strip():
                codes.append(f"PROBLEM_STATUS_{re.sub(r'[^A-Z0-9]+', '_', problem_status.strip().upper()).strip('_')}")
            if limitation_details:
                codes.append("SOURCE_LIMITATIONS_RETAINED_IN_SOURCE_SUMMARY")
            if key == "road_degree_one_vertex_count":
                codes.append("DEGREE_ONE_IS_NOT_DEAD_END")
            if key in {
                "unclassified_surface_residual_area_m2",
                "unclassified_surface_residual_ratio",
                "nonbuilding_nonwater_residual_area_m2",
                "nonbuilding_nonwater_residual_ratio_pct",
            }:
                codes.append("RESIDUAL_IS_NOT_BUILDABLE_OR_PUBLIC_SPACE")
            value = metric.get("value")
            if _finite_number(value) is None:
                metric_blocker = metric_blocker or "MISSING_OR_NON_NUMERIC_METRIC"
            output.append(
                _make_observation(
                    metric_key=key,
                    raw_value=value,
                    unit=unit,
                    method_version=raw_method if isinstance(raw_method, str) else None,
                    scope_ref=scope,
                    input_refs=metric_inputs,
                    blocker=metric_blocker,
                    domain_complete=True,
                    extra_limits=tuple(codes),
                    limitation_details=limitation_details,
                )
            )
    if malformed_nested_payload:
        output.append(
            _make_observation(
                metric_key="problem_definition.loader_result",
                raw_value=None,
                unit="unresolved",
                method_version=results.problem_method_version,
                scope_ref=study_area_ref,
                input_refs=(),
                blocker="LOADER_RESULT_NOT_OBJECT",
            )
        )
    return output


def _syntax_observations(
    results: ExistingAnalysisResults,
    source_refs: tuple[FrozenRef, ...],
    study_area_ref: FrozenRef,
) -> list[Observation]:
    syntax = results.syntax_bundle
    if syntax is None:
        return []
    if not isinstance(syntax, Mapping):
        return [
            _make_observation(
                metric_key="syntax.loader_result",
                raw_value=None,
                unit="unresolved",
                method_version=None,
                scope_ref=study_area_ref,
                input_refs=(),
                blocker="LOADER_RESULT_NOT_OBJECT",
            )
        ]
    blocker = _execution_blocker(results.syntax_status)
    layers = syntax.get("layers") or syntax.get("layer_plan", ())
    if not isinstance(layers, (list, tuple)):
        return [
            _make_observation(
                metric_key="syntax.loader_result",
                raw_value=None,
                unit="unresolved",
                method_version=None,
                scope_ref=study_area_ref,
                input_refs=(),
                blocker="LOADER_RESULT_NOT_OBJECT",
            )
        ]
    output: list[Observation] = []
    malformed_layer_payload = False
    for layer in layers:
        if not isinstance(layer, Mapping):
            malformed_layer_payload = True
            continue
        key = layer.get("layer_id") or layer.get("id") or layer.get("metric_key")
        if not isinstance(key, str) or not key.strip():
            continue
        extent: AnalysisExtent | None = None
        extent_mismatch = False
        extent_id = layer.get("extent_id")
        radius = _finite_number(layer.get("radius_m"))
        mode = layer.get("network_mode")
        if extent_id:
            id_matches = [candidate for candidate in results.analysis_extents if candidate.id == extent_id]
            if len(id_matches) == 1:
                candidate = id_matches[0]
                if (
                    radius != candidate.calculation_radius_m
                    or mode != candidate.network_mode
                    or candidate.study_area_ref != study_area_ref
                ):
                    extent_mismatch = True
                else:
                    extent = candidate
        elif radius is not None and mode is not None:
            extent_candidates = [
                candidate
                for candidate in results.analysis_extents
                if candidate.calculation_radius_m == radius
                and candidate.network_mode == mode
                and candidate.study_area_ref == study_area_ref
            ]
            if len(extent_candidates) == 1:
                extent = extent_candidates[0]
        scope = extent.study_area_ref if extent is not None else study_area_ref
        metric_inputs = _loader_refs(results, key, source_refs, scope, extent=extent)
        layer_status = str(layer.get("calculation_status") or "NOT_RUN").strip().upper()
        layer_blocker = blocker
        if extent_mismatch:
            layer_blocker = "ANALYSIS_EXTENT_MISMATCH"
        if layer_blocker is None:
            layer_blocker = _execution_blocker(layer_status)
        data_readiness = str(layer.get("data_readiness") or "").strip().upper()
        if data_readiness.startswith("BLOCKED"):
            layer_blocker = data_readiness
        if extent is None and layer_blocker is None:
            layer_blocker = "ANALYSIS_EXTENT_UNRESOLVED"
        statistics = layer.get("statistics") if isinstance(layer.get("statistics"), Mapping) else {}
        raw_value = layer.get("value", statistics.get("mean"))
        segment_values = layer.get("segment_values")
        has_no_segments = _finite_number(statistics.get("count")) == 0.0 or (
            "segment_values" in layer and isinstance(segment_values, (list, tuple, Mapping)) and not segment_values
        )
        if has_no_segments:
            raw_value = None
            layer_blocker = layer_blocker or "SYNTAX_LAYER_HAS_NO_SEGMENT_VALUES"
        method = (
            results.metric_method_versions.get(key)
            or layer.get("formula_version")
            or layer.get("algorithm_version")
            or syntax.get("engine")
        )
        unit = layer.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            unit = "unit-unresolved"
            layer_blocker = "UNIT_MISSING"
        limits = [
            "SYNTAX_IS_NOT_DISTANCE_OR_ACCESS",
            "SYNTAX_IS_NOT_MEASURED_PEDESTRIAN_OR_TRAFFIC_FLOW",
        ]
        if data_readiness.startswith("BLOCKED"):
            limits.append(data_readiness)
        if has_no_segments:
            limits.append("SYNTAX_LAYER_HAS_NO_SEGMENT_VALUES")
        if "EXPLORATORY" in str(syntax.get("engine", "")).upper():
            limits.append("SYNTAX_METHOD_EXPLORATORY")
        if extent is not None and extent.network_mode != "common_network":
            limits.append("MODE_SPECIFIC_NETWORK_RESULTS_NOT_CROSS_RANKED")
        if extent is not None and extent.source_extraction_buffer_m is not None:
            limits.append("SOURCE_EXTRACTION_BUFFER_IS_NOT_ANALYSIS_RADIUS")
        output.append(
            _make_observation(
                metric_key=key,
                raw_value=raw_value,
                unit=unit,
                method_version=method if isinstance(method, str) else None,
                scope_ref=scope,
                input_refs=metric_inputs,
                blocker=layer_blocker,
                domain_complete=True,
                extra_limits=tuple(limits),
                limitation_details=_text_values(layer.get("limitations")),
            )
        )
    if malformed_layer_payload:
        output.append(
            _make_observation(
                metric_key="syntax.loader_result",
                raw_value=None,
                unit="unresolved",
                method_version=None,
                scope_ref=study_area_ref,
                input_refs=(),
                blocker="LOADER_RESULT_NOT_OBJECT",
            )
        )
    return output


def build_analysis_bundle(
    workspace_ref: FrozenRef,
    source_refs: tuple[FrozenRef, ...],
    method_config: Mapping[str, Any],
    *,
    study_area_ref: FrozenRef,
    results: ExistingAnalysisResults | Mapping[str, Any],
    created_at: datetime,
) -> SiteAnalysisBundle:
    """Project existing outputs without rerunning or altering their calculations."""
    existing = results if isinstance(results, ExistingAnalysisResults) else ExistingAnalysisResults.model_validate(results)
    sources = _unique_refs(tuple(source_refs))
    observations = [
        *_site_observations(existing, sources, study_area_ref),
        *_problem_observations(existing, sources, study_area_ref),
        *_syntax_observations(existing, sources, study_area_ref),
    ]
    # The adapter has no authority to promote the source refs it receives.
    # Values from existing calculations therefore remain PARTIAL at best.
    tool_versions = dict(existing.tool_versions)
    tool_versions.setdefault("site_intelligence_adapter", "site-intelligence-v1")
    provisional = SiteAnalysisBundle(
        bundle_ref=FrozenRef(id="provisional-site-analysis-bundle", revision=1, sha256="sha256:" + "0" * 64),
        study_area_ref=study_area_ref,
        workspace_ref=workspace_ref,
        scenario_ref=existing.scenario_ref,
        observations=tuple(observations),
        analysis_extents=existing.analysis_extents,
        layer_refs=existing.layer_refs,
        coverage_refs=existing.coverage_refs,
        created_at=created_at,
        tool_versions=tool_versions,
        method_parameters=dict(method_config),
    )
    return provisional.model_copy(update={"bundle_ref": compute_site_analysis_bundle_ref(provisional)})
