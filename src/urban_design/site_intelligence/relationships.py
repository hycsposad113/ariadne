"""Backend-index relationship checks for site observations and opportunities."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, FiniteFloat, Field

from .contracts import (
    AnalysisStatus,
    ClaimBinding,
    FrozenRef,
    Observation,
    Opportunity,
    StatementTemplate,
    SiteAnalysisBundle,
    compute_site_analysis_bundle_ref,
)


class RelationshipValidationError(ValueError):
    """Raised when a reference resolves but does not support the requested claim."""


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_key: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    allowed_assertions: tuple[str, ...] = ("OBSERVATION", "COMPARISON", "IMPROVEMENT")
    improvement_direction: Literal["HIGHER", "LOWER"] | None = None


class ResolvedReference(BaseModel):
    """Exact record returned by the trusted project index for a frozen ref."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: FrozenRef
    workspace_ref: FrozenRef
    entity_type: Literal[
        "WORKSPACE",
        "STUDY_AREA",
        "SCENARIO",
        "DATASET_SNAPSHOT",
        "ARTIFACT",
        "EVIDENCE",
        "OBSERVATION",
        "OTHER",
    ]
    validation_status: Literal["VALIDATED", "UNVERIFIED", "INVALID", "STALE", "CONTESTED"]
    scope_ref: FrozenRef | None = None
    scenario_ref: FrozenRef | None = None
    metric_key: str | None = None
    unit: str | None = None
    method_version: str | None = None
    value: FiniteFloat | None = Field(default=None, strict=True)
    analysis_status: AnalysisStatus | None = None
    input_refs: tuple[FrozenRef, ...] = ()
    limitation_codes: tuple[str, ...] = ()


class RelationshipResolver(Protocol):
    """Minimal read-only backend index required to validate semantic links."""

    def resolve(self, ref: FrozenRef) -> ResolvedReference | None:
        """Resolve the exact id/revision/hash, never an id-only substitute."""

    def scope_covers(self, source_scope: FrozenRef, target_scope: FrozenRef) -> bool:
        """Return true only when verified scope geometry contains the target."""

    def metric_definition(self, metric_key: str) -> MetricDefinition | None:
        """Resolve a registered metric definition, unit, method, and claim policy."""


_STALE_STATES = {"INVALID", "STALE", "CONTESTED"}
_NUMERIC_LITERAL = re.compile(r"[0-9０-９零〇一二三四五六七八九十百千万萬]")
_THINK_TAG = re.compile(r"</?think\b[^>]*>", re.IGNORECASE)
_CREDENTIAL_TEXT = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+|(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]+"
)
_MAX_AI_NARRATIVE_CHARS = 1000


def has_unbound_numeric_text(text: str, bundle: SiteAnalysisBundle, resolver: RelationshipResolver) -> bool:
    """Only exact registered identifiers/compound versions are exempt from numbers."""
    refs = (bundle.bundle_ref, bundle.workspace_ref, bundle.study_area_ref,
            *bundle.layer_refs, *bundle.coverage_refs,
            *(ref for obs in bundle.observations for ref in (obs.scope_ref, *obs.input_refs)))
    allowed = {ref.id for ref in refs}
    allowed.update(obs.method_version for obs in bundle.observations)
    for obs in bundle.observations:
        definition = resolver.metric_definition(obs.metric_key)
        if (definition is not None and definition.metric_key == obs.metric_key
                and definition.unit == obs.unit and definition.method_version == obs.method_version):
            allowed.add(obs.metric_key)
    allowed.update(bundle.tool_versions.values())
    # Bare numeric versions can also be measurements, so never exempt them.
    allowed = {item for item in allowed if re.search(r"[A-Za-z]", item) and len(item) > 1}
    for item in sorted(allowed, key=len, reverse=True):
        text = re.sub(r"(?<![\w./:@#-])" + re.escape(item) + r"(?![\w/:@#-]|\.\w)", "", text)
    normalized = unicodedata.normalize("NFKC", text)
    if re.search(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|half|halves|quarters?|thirds?|fourths?|fifths?|sixths?|sevenths?|eighths?|ninths?|tenths?|first|second|percent)\b|半數|半数", normalized, re.IGNORECASE) or re.search(r"\b[IVXLCDM]+\b|\b(?:ii|iii|iv|vi|vii|viii|ix|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)\b", normalized):
        return True
    return any(char.isnumeric() or char in "兩两壹貳贰參叁肆伍陸陆柒捌玖拾佰仟" for char in normalized)



STATEMENT_TEMPLATES = {"METRIC_TENDENCY": "{metric_ref} indicates a {direction} tendency; verify through {verification}."}

def render_statement(template: StatementTemplate, bundle: SiteAnalysisBundle, resolver: RelationshipResolver) -> str:
    matching = [obs for obs in bundle.observations if obs.metric_key == template.metric_ref]
    definition = resolver.metric_definition(template.metric_ref)
    if (not matching or definition is None or any(obs.unit != definition.unit or obs.method_version != definition.method_version for obs in matching)):
        raise RelationshipValidationError("statement template metric reference is not registered in bundle")
    return STATEMENT_TEMPLATES[template.template_id].format(
        metric_ref=template.metric_ref, direction={"HIGHER": "higher", "LOWER": "lower", "UNRESOLVED": "unresolved"}[template.direction],
        verification={"DETERMINISTIC_ANALYSIS": "deterministic analysis", "DESIGNER_REVIEW": "designer review"}[template.verification])

_NEVER_SUPPORTED_ASSERTIONS = {"DEAD_END", "PUBLIC_ACCESS", "TRAFFIC_FLOW", "BUILDABILITY"}
_METRIC_ASSERTION_LIMITS: dict[str, set[str]] = {
    "road_degree_one_vertex_count": {"OBSERVATION", "TOPOLOGICAL_DEGREE_COUNT", "COMPARISON"},
    "unclassified_surface_residual_area_m2": {"OBSERVATION", "GEOMETRIC_RESIDUAL", "COMPARISON"},
    "unclassified_surface_residual_ratio": {"OBSERVATION", "GEOMETRIC_RESIDUAL", "COMPARISON"},
    "nonbuilding_nonwater_residual_area_m2": {"OBSERVATION", "GEOMETRIC_RESIDUAL", "COMPARISON"},
    "nonbuilding_nonwater_residual_ratio_pct": {"OBSERVATION", "GEOMETRIC_RESIDUAL", "COMPARISON"},
    "walking_detour_ratio": {"OBSERVATION", "NETWORK_DETOUR_RATIO", "COMPARISON"},
    "max_walking_detour_ratio": {"OBSERVATION", "NETWORK_DETOUR_RATIO", "COMPARISON"},
    "syntax_pedestrian_800m_nain_mean": {"OBSERVATION", "SYNTAX_INTEGRATION", "SYNTAX_CHOICE", "COMPARISON"},
}


def _scenario_matches(record_scenario: FrozenRef | None, bundle_scenario: FrozenRef | None) -> bool:
    if bundle_scenario is None:
        return record_scenario is None
    return record_scenario in {None, bundle_scenario}


def _resolve_exact(
    resolver: RelationshipResolver,
    ref: FrozenRef,
    expected_workspace: FrozenRef,
    *,
    allow_unverified: bool,
) -> ResolvedReference:
    record = resolver.resolve(ref)
    if record is None:
        raise RelationshipValidationError(f"unresolved evidence reference: {ref.id}")
    if record.ref != ref:
        raise RelationshipValidationError(f"reference revision/hash mismatch: {ref.id}")
    if record.workspace_ref != expected_workspace:
        raise RelationshipValidationError(f"reference belongs to another workspace: {ref.id}")
    if record.validation_status in _STALE_STATES:
        raise RelationshipValidationError(f"stale or invalid evidence reference: {ref.id}")
    if not allow_unverified and record.validation_status != "VALIDATED":
        raise RelationshipValidationError(f"unvalidated evidence cannot support an observed claim: {ref.id}")
    return record


def validate_analysis_bundle(
    bundle: SiteAnalysisBundle,
    resolver: RelationshipResolver,
) -> SiteAnalysisBundle:
    """Rehash bundle contents, then check refs against the backend-owned project index.

    The resolver is a trusted backend index for exact records and scope geometry;
    caller-provided identities are not sufficient without content-hash validation.
    """
    try:
        computed_ref = compute_site_analysis_bundle_ref(bundle)
    except Exception as exc:
        raise RelationshipValidationError("analysis bundle content cannot be hashed") from exc
    if computed_ref != bundle.bundle_ref:
        raise RelationshipValidationError("analysis bundle content hash does not match bundle_ref")
    indexed_bundle = _resolve_exact(resolver, bundle.bundle_ref, bundle.workspace_ref, allow_unverified=False)
    if indexed_bundle.entity_type != "ARTIFACT" or indexed_bundle.scope_ref != bundle.study_area_ref:
        raise RelationshipValidationError("analysis bundle reference entity or scope mismatch")
    if indexed_bundle.scenario_ref != bundle.scenario_ref:
        raise RelationshipValidationError("analysis bundle reference scenario mismatch")
    workspace = _resolve_exact(
        resolver,
        bundle.workspace_ref,
        bundle.workspace_ref,
        allow_unverified=False,
    )
    if workspace.entity_type != "WORKSPACE":
        raise RelationshipValidationError("workspace reference does not resolve to a workspace")
    study_area = _resolve_exact(resolver, bundle.study_area_ref, bundle.workspace_ref, allow_unverified=False)
    if study_area.entity_type != "STUDY_AREA":
        raise RelationshipValidationError("bundle study-area reference does not resolve to a StudyArea")
    if bundle.scenario_ref is not None:
        scenario = _resolve_exact(resolver, bundle.scenario_ref, bundle.workspace_ref, allow_unverified=False)
        if scenario.entity_type != "SCENARIO":
            raise RelationshipValidationError("scenario reference does not resolve to a scenario")
    for ref in (*bundle.layer_refs, *bundle.coverage_refs):
        record = _resolve_exact(resolver, ref, bundle.workspace_ref, allow_unverified=True)
        if record.scope_ref is None or not resolver.scope_covers(record.scope_ref, bundle.study_area_ref):
            raise RelationshipValidationError(f"bundle layer or coverage scope mismatch: {ref.id}")
        layer_scope = _resolve_exact(resolver, record.scope_ref, bundle.workspace_ref, allow_unverified=False)
        if layer_scope.entity_type not in {"STUDY_AREA", "ARTIFACT"}:
            raise RelationshipValidationError(f"bundle layer or coverage scope is not spatial: {ref.id}")
        if not _scenario_matches(record.scenario_ref, bundle.scenario_ref):
            raise RelationshipValidationError(f"bundle layer or coverage scenario mismatch: {ref.id}")
    for observation in bundle.observations:
        scope = _resolve_exact(resolver, observation.scope_ref, bundle.workspace_ref, allow_unverified=False)
        if scope.entity_type not in {"STUDY_AREA", "ARTIFACT"} or not resolver.scope_covers(bundle.study_area_ref, observation.scope_ref):
            raise RelationshipValidationError("observation scope is not a spatial entity within bundle StudyArea")
        for ref in observation.input_refs:
            record = _resolve_exact(resolver, ref, bundle.workspace_ref, allow_unverified=True)
            if record.scope_ref is None or not resolver.scope_covers(record.scope_ref, observation.scope_ref):
                raise RelationshipValidationError(f"input scope does not cover observation scope: {ref.id}")
            if not _scenario_matches(record.scenario_ref, bundle.scenario_ref):
                raise RelationshipValidationError(f"input scenario mismatch: {ref.id}")
    return bundle


def _validate_binding(
    binding: ClaimBinding,
    opportunity: Opportunity,
    bundle: SiteAnalysisBundle,
    resolver: RelationshipResolver,
) -> Observation:
    definition = resolver.metric_definition(binding.metric_key)
    if definition is None:
        raise RelationshipValidationError(f"unknown metric key: {binding.metric_key}")
    if definition.metric_key != binding.metric_key:
        raise RelationshipValidationError("metric definition key mismatch")
    if definition.unit != binding.unit:
        raise RelationshipValidationError(f"metric unit mismatch: {binding.metric_key}")
    if definition.method_version != binding.method_version:
        raise RelationshipValidationError(f"metric method mismatch: {binding.metric_key}")
    allowed = set(definition.allowed_assertions)
    limited = _METRIC_ASSERTION_LIMITS.get(binding.metric_key)
    if limited is not None:
        allowed &= limited
    if binding.assertion in _NEVER_SUPPORTED_ASSERTIONS or binding.assertion not in allowed:
        raise RelationshipValidationError(
            f"claim assertion {binding.assertion} is not supported by metric {binding.metric_key}"
        )

    matching = [
        observation
        for observation in bundle.observations
        if observation.metric_key == binding.metric_key
        and observation.unit == binding.unit
        and observation.method_version == binding.method_version
        and observation.scope_ref == binding.scope_ref
    ]
    if len(matching) != 1:
        raise RelationshipValidationError("claim binding does not resolve to one bundle observation")
    observation = matching[0]
    if observation.status not in {"AVAILABLE", "PARTIAL"} or observation.value is None:
        raise RelationshipValidationError("claim binding refers to a missing or unavailable metric value")
    if observation.status == "PARTIAL" and opportunity.kind == "OBSERVED_PROBLEM":
        raise RelationshipValidationError("partial evidence cannot support an observed problem")
    if not resolver.scope_covers(binding.scope_ref, opportunity.scope_ref):
        raise RelationshipValidationError("metric scope does not cover opportunity scope")
    binding_scope = _resolve_exact(
        resolver,
        binding.scope_ref,
        bundle.workspace_ref,
        allow_unverified=False,
    )
    if binding_scope.entity_type not in {"STUDY_AREA", "ARTIFACT"}:
        raise RelationshipValidationError("claim scope does not resolve to a spatial Artifact")
    if set(binding.input_refs) != set(observation.input_refs):
        raise RelationshipValidationError("claim input references do not match the observation lineage")
    if not set(binding.input_refs).issubset(set(opportunity.evidence_refs)):
        raise RelationshipValidationError("claim input references must be cited by the opportunity")

    for ref in binding.input_refs:
        record = _resolve_exact(
            resolver,
            ref,
            bundle.workspace_ref,
            allow_unverified=(opportunity.kind != "OBSERVED_PROBLEM"),
        )
        if record.scope_ref is None or not resolver.scope_covers(record.scope_ref, binding.scope_ref):
            raise RelationshipValidationError(f"claim input scope does not cover its metric: {ref.id}")
        if not _scenario_matches(record.scenario_ref, bundle.scenario_ref):
            raise RelationshipValidationError(f"claim input scenario mismatch: {ref.id}")

    if binding.assertion in {"COMPARISON", "IMPROVEMENT"}:
        assert binding.baseline_ref is not None and binding.candidate_ref is not None
        if not {binding.baseline_ref, binding.candidate_ref}.issubset(set(opportunity.evidence_refs)):
            raise RelationshipValidationError("baseline and candidate must be cited evidence references")
        pair = [binding.baseline_ref, binding.candidate_ref]
        resolved_pair = [
            _resolve_exact(resolver, ref, bundle.workspace_ref, allow_unverified=False)
            for ref in pair
        ]
        for record in resolved_pair:
            if record.entity_type not in {"EVIDENCE", "OBSERVATION"}:
                raise RelationshipValidationError("baseline/candidate entity type must be metric evidence")
            if record.analysis_status in {"BLOCKED", "NOT_RUN"}:
                raise RelationshipValidationError("baseline/candidate analysis status is unavailable")
            if record.analysis_status == "PARTIAL":
                if opportunity.kind == "OBSERVED_PROBLEM":
                    raise RelationshipValidationError("partial comparison evidence cannot support an observed problem")
                if "PARTIAL_ANALYSIS_EVIDENCE" not in opportunity.limitation_codes:
                    raise RelationshipValidationError("partial comparison evidence requires a visible partial limitation")
            if record.entity_type == "OBSERVATION":
                if record.analysis_status not in {None, "AVAILABLE", "PARTIAL"}:
                    raise RelationshipValidationError("comparison observation analysis status must be available or partial")
                if not record.input_refs:
                    raise RelationshipValidationError("comparison observation input lineage is missing")
                if record.ref == binding.candidate_ref and record.input_refs != observation.input_refs:
                    raise RelationshipValidationError("candidate observation input lineage does not match the bundle")
                for input_ref in record.input_refs:
                    source = _resolve_exact(resolver, input_ref, bundle.workspace_ref,
                                            allow_unverified=(opportunity.kind != "OBSERVED_PROBLEM"))
                    if source.scope_ref is None or not resolver.scope_covers(source.scope_ref, binding.scope_ref):
                        raise RelationshipValidationError("comparison observation input lineage scope mismatch")
                    if not _scenario_matches(source.scenario_ref, bundle.scenario_ref):
                        raise RelationshipValidationError("comparison observation input lineage scenario mismatch")
            if (
                record.metric_key != binding.metric_key
                or record.unit != binding.unit
                or record.method_version != binding.method_version
                or record.value is None
                or record.scope_ref != binding.scope_ref
            ):
                raise RelationshipValidationError("baseline/candidate metric, scope, unit, or method mismatch")
        if bundle.scenario_ref is not None and resolved_pair[1].scenario_ref != bundle.scenario_ref:
            raise RelationshipValidationError("candidate scenario must exactly match bundle scenario")
        if resolved_pair[0].ref == resolved_pair[1].ref:
            raise RelationshipValidationError("baseline and candidate must be distinct versions")
        if resolved_pair[1].value != observation.value:
            raise RelationshipValidationError("candidate value does not match the bundle observation")
        if binding.assertion == "COMPARISON" and opportunity.kind == "OBSERVED_PROBLEM":
            if definition.improvement_direction is None:
                raise RelationshipValidationError("observed problem comparison requires a registered metric direction")
            baseline_value = float(resolved_pair[0].value)
            candidate_value = float(resolved_pair[1].value)
            demonstrates_worsening = (
                candidate_value < baseline_value
                if definition.improvement_direction == "HIGHER"
                else candidate_value > baseline_value
            )
            if not demonstrates_worsening:
                raise RelationshipValidationError("comparison does not demonstrate worsening in the registered metric direction")
        if binding.assertion == "IMPROVEMENT":
            if definition.improvement_direction is None:
                raise RelationshipValidationError("metric has no registered improvement direction")
            baseline_value = float(resolved_pair[0].value)
            candidate_value = float(resolved_pair[1].value)
            improved = (
                candidate_value > baseline_value
                if definition.improvement_direction == "HIGHER"
                else candidate_value < baseline_value
            )
            if not improved:
                raise RelationshipValidationError("candidate does not improve the registered metric direction")
    return observation


def validate_opportunity(
    proposal: Opportunity | dict[str, object],
    bundle: SiteAnalysisBundle,
    resolver: RelationshipResolver,
) -> Opportunity:
    """Validate an opportunity against exact project, scope, method, and metric records."""
    validate_analysis_bundle(bundle, resolver)
    try:
        opportunity = proposal if isinstance(proposal, Opportunity) else Opportunity.model_validate(proposal)
    except Exception as exc:
        raise RelationshipValidationError(f"invalid opportunity schema: {exc}") from exc

    workspace = _resolve_exact(
        resolver,
        bundle.workspace_ref,
        bundle.workspace_ref,
        allow_unverified=False,
    )
    if workspace.entity_type != "WORKSPACE":
        raise RelationshipValidationError("workspace reference does not resolve to a workspace")
    study_area = _resolve_exact(
        resolver,
        bundle.study_area_ref,
        bundle.workspace_ref,
        allow_unverified=False,
    )
    if study_area.entity_type != "STUDY_AREA":
        raise RelationshipValidationError("bundle study-area reference does not resolve to a StudyArea")
    if bundle.scenario_ref is not None:
        scenario = _resolve_exact(resolver, bundle.scenario_ref, bundle.workspace_ref, allow_unverified=False)
        if scenario.entity_type != "SCENARIO":
            raise RelationshipValidationError("scenario reference does not resolve to a scenario")
    opportunity_scope = _resolve_exact(
        resolver,
        opportunity.scope_ref,
        bundle.workspace_ref,
        allow_unverified=False,
    )
    if opportunity_scope.entity_type not in {"STUDY_AREA", "ARTIFACT"}:
        raise RelationshipValidationError("opportunity scope does not resolve to a spatial Artifact")
    if not resolver.scope_covers(bundle.study_area_ref, opportunity.scope_ref):
        raise RelationshipValidationError("opportunity scope is outside the bundle StudyArea")
    if (opportunity.kind != "DESIGN_PREFERENCE" or opportunity.origin == "AI_SUGGESTED") and not opportunity.evidence_refs:
        raise RelationshipValidationError("evidence-based opportunity requires evidence references")

    resolved_evidence: dict[FrozenRef, ResolvedReference] = {}
    for ref in opportunity.evidence_refs:
        record = _resolve_exact(
            resolver,
            ref,
            bundle.workspace_ref,
            allow_unverified=(opportunity.kind != "OBSERVED_PROBLEM"),
        )
        if record.scope_ref is None or not resolver.scope_covers(record.scope_ref, opportunity.scope_ref):
            raise RelationshipValidationError(f"evidence scope does not cover opportunity scope: {ref.id}")
        if not _scenario_matches(record.scenario_ref, bundle.scenario_ref):
            raise RelationshipValidationError(f"evidence scenario mismatch: {ref.id}")
        resolved_evidence[ref] = record

    # Notifications are derived by the server; model-authored fields confer no authority.
    limitations: list[str] = []
    questions: list[str] = []
    uncertainties = list(opportunity.uncertainties)
    for record in resolved_evidence.values():
        limitations.extend(record.limitation_codes)
        uncertainties.extend(record.limitation_codes)
        if record.entity_type in {"EVIDENCE", "OBSERVATION"} and record.analysis_status is None:
            limitations.append("LEGACY_ANALYSIS_STATUS_UNSET")
            uncertainties.append("LEGACY_ANALYSIS_STATUS_UNSET")
            questions.append(f"Analysis status was not recorded for {record.ref.id}; designer confirmation required: may this evidence be treated as complete?")
        if record.analysis_status == "PARTIAL":
            limitations.append("PARTIAL_ANALYSIS_EVIDENCE")
            uncertainties.append("PARTIAL_ANALYSIS_EVIDENCE")
    cited = set(opportunity.evidence_refs)
    for observation in bundle.observations:
        if cited.intersection(observation.input_refs) or any(record.entity_type == "OBSERVATION" and record.metric_key == observation.metric_key for record in resolved_evidence.values()):
            if observation.status == "PARTIAL":
                limitations.append("PARTIAL_ANALYSIS_EVIDENCE")
                uncertainties.append("PARTIAL_ANALYSIS_EVIDENCE")
            limitations.extend(observation.limitation_codes)
            uncertainties.extend(observation.limitation_codes)
    opportunity = opportunity.model_copy(update={"limitation_codes": tuple(dict.fromkeys(limitations)), "designer_questions": tuple(dict.fromkeys(questions)), "uncertainties": tuple(dict.fromkeys(uncertainties))})

    for key in opportunity.verification_metric_keys:
        if resolver.metric_definition(key) is None:
            raise RelationshipValidationError(f"unknown verification metric key: {key}")

    for binding in opportunity.claim_bindings:
        observation = _validate_binding(binding, opportunity, bundle, resolver)
        if binding.assertion == "OBSERVATION":
            indexed = [
                record
                for record in resolved_evidence.values()
                if record.entity_type == "OBSERVATION"
                and record.metric_key == binding.metric_key
                and record.unit == binding.unit
                and record.method_version == binding.method_version
                and record.scope_ref == binding.scope_ref
            ]
            if len(indexed) != 1:
                raise RelationshipValidationError("observation binding requires one indexed observation record")
            if indexed[0].analysis_status is not None and indexed[0].analysis_status != observation.status:
                raise RelationshipValidationError("indexed observation status does not match the bundle observation")
            if indexed[0].input_refs != observation.input_refs:
                raise RelationshipValidationError("indexed observation input lineage does not match the bundle observation")
            if indexed[0].value != observation.value:
                raise RelationshipValidationError("indexed observation value does not match the bundle observation value")

    for ref, record in resolved_evidence.items():
        if record.metric_key is None:
            continue
        definition = resolver.metric_definition(record.metric_key)
        if definition is None:
            raise RelationshipValidationError(f"unknown metric key on evidence reference: {record.metric_key}")
        if record.unit != definition.unit or record.method_version != definition.method_version:
            raise RelationshipValidationError(f"evidence unit or method mismatch: {ref.id}")
        if opportunity.kind != "DESIGN_PREFERENCE" and not any(
            binding.metric_key == record.metric_key
            and binding.unit == record.unit
            and binding.method_version == record.method_version
            and binding.scope_ref == record.scope_ref
            for binding in opportunity.claim_bindings
        ):
            raise RelationshipValidationError(f"metric evidence is not bound to an opportunity claim: {ref.id}")

    if opportunity.kind == "OBSERVED_PROBLEM" and not any(
        binding.assertion in {"COMPARISON", "IMPROVEMENT"}
        for binding in opportunity.claim_bindings
    ):
        raise RelationshipValidationError("observed problem requires a validated comparative baseline")

    if opportunity.origin == "AI_SUGGESTED":
        from .opportunities import _THINK_TAG, _CREDENTIAL_TEXT
        text_fields = (opportunity.statement, *opportunity.counterexamples, *proposal.uncertainties) if isinstance(proposal, Opportunity) else (opportunity.statement, *opportunity.counterexamples, *tuple(proposal.get("uncertainties", ())))
        if any(len(value) > _MAX_AI_NARRATIVE_CHARS for value in text_fields):
            raise RelationshipValidationError("AI opportunity narrative exceeds the text length limit")
        if len(opportunity.counterexamples) > 10 or len(text_fields) - 1 - len(opportunity.counterexamples) > 10:
            raise RelationshipValidationError("AI opportunity narrative has too many text entries")
        if any(_THINK_TAG.search(value) or _CREDENTIAL_TEXT.search(value) for value in text_fields):
            raise RelationshipValidationError("AI opportunity narrative contains filtered private or credential text")
        text = " ".join(text_fields)
        if has_unbound_numeric_text(text, bundle, resolver):
            raise RelationshipValidationError(
                "AI output cannot author measured numbers; bind a metric key for server-resolved values"
            )
        if opportunity.statement_template is None or opportunity.statement != render_statement(opportunity.statement_template, bundle, resolver):
            raise RelationshipValidationError("AI statement requires an exact fixed statement template")
        selected = [obs for obs in bundle.observations if obs.metric_key == opportunity.statement_template.metric_ref and obs.status in {"AVAILABLE", "PARTIAL"} and (set(obs.input_refs) - {obs.scope_ref}).issubset(set(opportunity.evidence_refs))]
        if not selected:
            raise RelationshipValidationError("statement template metric requires cited observation input lineage")
    return opportunity
