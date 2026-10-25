"""Frozen contracts for source-bound site observations and design hypotheses."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator


AnalysisStatus = Literal["AVAILABLE", "PARTIAL", "BLOCKED", "NOT_RUN"]
ClaimAssertion = Literal[
    "OBSERVATION",
    "COMPARISON",
    "IMPROVEMENT",
    "TOPOLOGICAL_DEGREE_COUNT",
    "NETWORK_DETOUR_RATIO",
    "SYNTAX_INTEGRATION",
    "SYNTAX_CHOICE",
    "GEOMETRIC_RESIDUAL",
    "GEOMETRIC_PROXIMITY",
    "DEAD_END",
    "PUBLIC_ACCESS",
    "TRAFFIC_FLOW",
    "BUILDABILITY",
    "DESIGN_PREFERENCE",
]


def _assert_finite_json(value: Any, path: str = "method_parameters") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_finite_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            _assert_finite_json(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} must contain JSON-compatible values")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenRef(_FrozenModel):
    """Immutable identity of an artifact or versioned project record."""

    id: str = Field(min_length=1)
    revision: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reference id must be non-empty")
        return normalized


class CategoryCount(_FrozenModel):
    category: str = Field(min_length=1)
    count: int = Field(ge=0, strict=True)

    @field_validator("category")
    @classmethod
    def nonblank_category(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("category must be non-empty")
        return normalized


class AnalysisExtent(_FrozenModel):
    """Analysis coverage kept distinct from the displayed StudyArea polygon."""

    id: str = Field(min_length=1)
    study_area_ref: FrozenRef
    display_radius_m: FiniteFloat = Field(gt=0, strict=True)
    network_mode: Literal["common_network", "pedestrian", "bicycle", "motor_vehicle", "none"]
    calculation_radius_m: FiniteFloat | None = Field(default=None, gt=0, strict=True)
    source_extraction_buffer_m: FiniteFloat | None = Field(default=None, gt=0, strict=True)
    input_refs: tuple[FrozenRef, ...] = ()
    limitation_codes: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("analysis extent id must be non-empty")
        return normalized

    @field_validator("limitation_codes")
    @classmethod
    def clean_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("limitation codes must be non-empty")
        return normalized


class Observation(_FrozenModel):
    metric_key: str = Field(min_length=1)
    status: AnalysisStatus
    value: FiniteFloat | None = Field(default=None, strict=True)
    category_counts: tuple[CategoryCount, ...] = ()
    unit: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    scope_ref: FrozenRef
    input_refs: tuple[FrozenRef, ...] = ()
    limitation_codes: tuple[str, ...] = ()
    limitation_details: tuple[str, ...] = ()

    @field_validator("metric_key", "unit", "method_version")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("observation metric, unit, and method must be non-empty")
        return normalized

    @field_validator("limitation_codes")
    @classmethod
    def clean_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("limitation codes must be non-empty")
        return normalized

    @field_validator("limitation_details")
    @classmethod
    def clean_limitation_details(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("limitation details must be non-empty")
        return normalized

    @model_validator(mode="after")
    def guard_value_and_lineage(self) -> "Observation":
        if self.status in {"BLOCKED", "NOT_RUN"} and (self.value is not None or self.category_counts):
            raise ValueError("blocked or not-run observation cannot carry a value")
        if self.status in {"BLOCKED", "NOT_RUN"} and not self.limitation_codes:
            raise ValueError("blocked or not-run observation requires a reason code")
        if self.status == "AVAILABLE" and self.value is None and not self.category_counts:
            raise ValueError("available observation needs a scalar or category counts")
        if self.status in {"AVAILABLE", "PARTIAL"} and not self.input_refs:
            raise ValueError("computed observation needs input references")
        if self.status == "PARTIAL" and not self.limitation_codes:
            raise ValueError("partial result needs limitations")
        if len(set(self.input_refs)) != len(self.input_refs):
            raise ValueError("observation input references must be unique")
        return self


class SiteAnalysisBundle(_FrozenModel):
    schema_version: Literal["site-analysis-bundle-v1"] = "site-analysis-bundle-v1"
    bundle_ref: FrozenRef
    study_area_ref: FrozenRef
    workspace_ref: FrozenRef
    scenario_ref: FrozenRef | None = None
    observations: tuple[Observation, ...]
    analysis_extents: tuple[AnalysisExtent, ...] = ()
    layer_refs: tuple[FrozenRef, ...] = ()
    coverage_refs: tuple[FrozenRef, ...] = ()
    created_at: datetime
    tool_versions: dict[str, str]
    method_parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("tool_versions")
    @classmethod
    def nonblank_tool_versions(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not key.strip() or not version.strip() for key, version in value.items()):
            raise ValueError("tool version names and values must be non-empty")
        return dict(value)

    @field_validator("method_parameters")
    @classmethod
    def finite_method_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _assert_finite_json(value)
        return value

    @model_validator(mode="after")
    def unique_observation_keys(self) -> "SiteAnalysisBundle":
        keys = [
            (item.metric_key, item.scope_ref, item.method_version)
            for item in self.observations
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("bundle contains duplicate metric/scope/method observations")
        return self


def compute_site_analysis_bundle_ref(bundle: SiteAnalysisBundle) -> FrozenRef:
    """Recompute the canonical content reference; ``bundle_ref`` is excluded."""
    base = {
        "schema_version": bundle.schema_version,
        "study_area_ref": bundle.study_area_ref.model_dump(mode="json"),
        "workspace_ref": bundle.workspace_ref.model_dump(mode="json"),
        "scenario_ref": bundle.scenario_ref.model_dump(mode="json") if bundle.scenario_ref else None,
        "observations": [item.model_dump(mode="json") for item in bundle.observations],
        "analysis_extents": [item.model_dump(mode="json") for item in bundle.analysis_extents],
        "layer_refs": [item.model_dump(mode="json") for item in bundle.layer_refs],
        "coverage_refs": [item.model_dump(mode="json") for item in bundle.coverage_refs],
        "created_at": bundle.created_at.isoformat(),
        "tool_versions": bundle.tool_versions,
        "method_parameters": bundle.method_parameters,
    }
    digest = hashlib.sha256(
        json.dumps(
            base,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return FrozenRef(
        id=f"site-analysis-bundle-{digest[:16]}",
        revision=1,
        sha256=f"sha256:{digest}",
    )


class ClaimBinding(_FrozenModel):
    """Binds an interpretation to a metric definition and exact evidence lineage."""

    metric_key: str = Field(min_length=1)
    scope_ref: FrozenRef
    input_refs: tuple[FrozenRef, ...]
    method_version: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    assertion: ClaimAssertion = "OBSERVATION"
    baseline_ref: FrozenRef | None = None
    candidate_ref: FrozenRef | None = None

    @field_validator("metric_key", "method_version", "unit")
    @classmethod
    def nonblank_binding_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("claim binding metric, method, and unit must be non-empty")
        return normalized

    @model_validator(mode="after")
    def coherent_comparison(self) -> "ClaimBinding":
        if len(set(self.input_refs)) != len(self.input_refs):
            raise ValueError("claim binding input references must be unique")
        has_baseline = self.baseline_ref is not None
        has_candidate = self.candidate_ref is not None
        if has_baseline != has_candidate:
            raise ValueError("comparison requires both baseline and candidate references")
        if self.assertion in {"COMPARISON", "IMPROVEMENT"} and not has_baseline:
            raise ValueError("comparison or improvement claim requires baseline and candidate references")
        if self.assertion not in {"COMPARISON", "IMPROVEMENT"} and has_baseline:
            raise ValueError("baseline/candidate references require a comparison assertion")
        return self


class SuggestedAction(str, Enum):
    INSPECT_EVIDENCE = "INSPECT_EVIDENCE"
    COMPARE_OPTIONS = "COMPARE_OPTIONS"
    REQUEST_DATA = "REQUEST_DATA"
    RUN_VALIDATION = "RUN_VALIDATION"
    TEST_HYPOTHESIS = "TEST_HYPOTHESIS"
    EXPLORE_DESIGN_PREFERENCE = "EXPLORE_DESIGN_PREFERENCE"
    REQUEST_DESIGNER_REVIEW = "REQUEST_DESIGNER_REVIEW"


class StatementTemplate(_FrozenModel):
    template_id: Literal["METRIC_TENDENCY"] = "METRIC_TENDENCY"
    metric_ref: str = Field(min_length=1)
    direction: Literal["HIGHER", "LOWER", "UNRESOLVED"] = "UNRESOLVED"
    verification: Literal["DETERMINISTIC_ANALYSIS", "DESIGNER_REVIEW"] = "DETERMINISTIC_ANALYSIS"


class Opportunity(_FrozenModel):
    id: str = Field(min_length=1)
    origin: Literal["AI_SUGGESTED", "DESIGNER_AUTHORED", "RULE_SUGGESTED"]
    statement: str = Field(min_length=1)
    statement_template: StatementTemplate | None = None
    limitation_codes: tuple[str, ...] = ()
    designer_questions: tuple[str, ...] = ()
    kind: Literal["OBSERVED_PROBLEM", "CONDITIONAL_HYPOTHESIS", "DESIGN_PREFERENCE"]
    evidence_refs: tuple[FrozenRef, ...] = ()
    scope_ref: FrozenRef
    suggested_actions: tuple[SuggestedAction, ...] = ()
    counterexamples: tuple[str, ...] = ()
    verification_metric_keys: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    claim_bindings: tuple[ClaimBinding, ...] = ()

    @field_validator("id", "statement")
    @classmethod
    def nonblank_opportunity_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("opportunity id and statement must be non-empty")
        return normalized

    @field_validator("counterexamples", "uncertainties", "verification_metric_keys")
    @classmethod
    def nonblank_list_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("opportunity list values must be non-empty")
        return normalized

    @model_validator(mode="after")
    def observed_problem_requires_comparison(self) -> "Opportunity":
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("opportunity evidence references must be unique")
        if self.kind == "OBSERVED_PROBLEM" and not any(
            binding.assertion in {"COMPARISON", "IMPROVEMENT"}
            and binding.baseline_ref is not None
            and binding.candidate_ref is not None
            for binding in self.claim_bindings
        ):
            raise ValueError("observed problem requires an explicit comparable baseline")
        return self


class DesignIntent(_FrozenModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    scope_ref: FrozenRef
    kind: Literal["PREFERENCE", "REQUIRED_FEATURE", "AVOID_FEATURE"]
    source_opportunity_ids: tuple[str, ...] = ()
    origin: Literal["AI_SUGGESTED", "DESIGNER_AUTHORED", "RULE_SUGGESTED"]
    priority: int | None = Field(default=None, ge=0, strict=True)
    version: int = Field(ge=1, strict=True)

    @field_validator("id", "text")
    @classmethod
    def nonblank_intent_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("design intent id and text must be non-empty")
        return normalized

    @field_validator("source_opportunity_ids")
    @classmethod
    def nonblank_source_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("source opportunity ids must be non-empty")
        return normalized


class DesignBriefRevision(_FrozenModel):
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    parent_ref: FrozenRef | None = None
    workspace_ref: FrozenRef
    analysis_ref: FrozenRef
    intents: tuple[DesignIntent, ...] = ()
    selected_opportunity_ids: tuple[str, ...] = ()
    constraint_set_ref: FrozenRef | None = None
    assumption_refs: tuple[FrozenRef, ...] = ()
    required_decision_refs: tuple[FrozenRef, ...] = ()

    @field_validator("id")
    @classmethod
    def nonblank_brief_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("design brief id must be non-empty")
        return normalized
