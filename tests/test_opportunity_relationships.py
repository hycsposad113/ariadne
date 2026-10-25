import hashlib
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from urban_design.site_intelligence.contracts import (
    ClaimBinding,
    FrozenRef,
    Observation,
    Opportunity,
    SiteAnalysisBundle,
    StatementTemplate,
)
from urban_design.site_intelligence.relationships import (
    MetricDefinition,
    RelationshipValidationError,
    ResolvedReference,
    validate_opportunity,
    validate_analysis_bundle,
    render_statement,
)


def ref(identifier, revision=1, digest="a"):
    return FrozenRef(id=identifier, revision=revision, sha256="sha256:" + digest * 64)


WORKSPACE = ref("workspace", digest="f")
SITE = ref("site", digest="a")
INPUT = ref("bag-snapshot", digest="b")
BASELINE = ref("baseline-result", digest="c")
CANDIDATE = ref("candidate-result", digest="d")
SCENARIO = ref("scenario-current", digest="e")


class FakeResolver:
    def __init__(self, records=(), metric_definitions=(), covers=()):
        self.records = {record.ref.id: record for record in records}
        self.metric_definitions = {item.metric_key: item for item in metric_definitions}
        self.covers = set(covers)

    def resolve(self, frozen_ref):
        return self.records.get(frozen_ref.id)

    def scope_covers(self, source_scope, target_scope):
        return source_scope == target_scope or (source_scope, target_scope) in self.covers

    def metric_definition(self, metric_key):
        return self.metric_definitions.get(metric_key)


def record(
    frozen_ref,
    *,
    entity_type="DATASET_SNAPSHOT",
    workspace=WORKSPACE,
    scope=SITE,
    scenario=None,
    status="VALIDATED",
    metric_key=None,
    unit=None,
    method=None,
    value=None,
):
    return ResolvedReference(
        ref=frozen_ref,
        workspace_ref=workspace,
        entity_type=entity_type,
        validation_status=status,
        scope_ref=scope,
        scenario_ref=scenario,
        metric_key=metric_key,
        unit=unit,
        method_version=method,
        value=value,
        analysis_status="AVAILABLE" if entity_type == "OBSERVATION" else None,
        input_refs=(INPUT,) if entity_type == "OBSERVATION" else (),
    )


def make_bundle(*, observation_metric="road_degree_one_vertex_count", unit="vertices", scenario_ref=None):
    method = "fixture-v1"
    observation = Observation(
        metric_key=observation_metric,
        status="AVAILABLE",
        value=1.0,
        unit=unit,
        method_version=method,
        scope_ref=SITE,
        input_refs=(INPUT,),
    )
    bundle = SiteAnalysisBundle(
        bundle_ref=ref("bundle", digest="f"),
        study_area_ref=SITE,
        workspace_ref=WORKSPACE,
        scenario_ref=scenario_ref,
        observations=(observation,),
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        tool_versions={"fixture": "1"},
    )
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
        json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()
    return bundle.model_copy(
        update={
            "bundle_ref": FrozenRef(
                id=f"site-analysis-bundle-{digest[:16]}",
                revision=1,
                sha256=f"sha256:{digest}",
            )
        }
    )


def make_resolver(*, bundle=None, scope=SITE, input_status="VALIDATED", input_workspace=WORKSPACE, input_scenario=None):
    bundle = bundle or make_bundle()
    return FakeResolver(
        records=[
            record(bundle.bundle_ref, entity_type="ARTIFACT", scenario=bundle.scenario_ref),
            record(WORKSPACE, entity_type="WORKSPACE"),
            record(SITE, entity_type="STUDY_AREA"),
            record(SCENARIO, entity_type="SCENARIO"),
            record(INPUT, scope=scope, status=input_status, workspace=input_workspace, scenario=input_scenario),
        ],
        metric_definitions=[
            MetricDefinition(
                metric_key="road_degree_one_vertex_count",
                unit="vertices",
                method_version="fixture-v1",
                allowed_assertions=("OBSERVATION", "COMPARISON", "IMPROVEMENT", "DEAD_END", "TOPOLOGICAL_DEGREE_COUNT"),
            ),
        ],
    )


def make_hypothesis(*, evidence=(INPUT,), claim_bindings=(), scope=SITE, statement="Test a route-connectivity hypothesis"):
    template = StatementTemplate(metric_ref="road_degree_one_vertex_count")
    if statement == "Test a route-connectivity hypothesis":
        statement = render_statement(template, make_bundle(), make_resolver())
    return Opportunity(
        statement_template=template,
        id="opportunity-1",
        origin="AI_SUGGESTED",
        statement=statement,
        kind="CONDITIONAL_HYPOTHESIS",
        evidence_refs=tuple(evidence),
        scope_ref=scope,
        suggested_actions=("TEST_HYPOTHESIS",),
        uncertainties=("Network access is not verified.",),
        claim_bindings=tuple(claim_bindings),
    )


def test_valid_hypothesis_resolves_metric_scope_and_input_hash():
    bundle = make_bundle()
    binding = ClaimBinding(
        metric_key="road_degree_one_vertex_count",
        scope_ref=SITE,
        input_refs=(INPUT,),
        method_version="fixture-v1",
        unit="vertices",
        assertion="TOPOLOGICAL_DEGREE_COUNT",
    )
    resolver = make_resolver(bundle=bundle)
    proposal = make_hypothesis(claim_bindings=(binding,))
    assert validate_opportunity(proposal, bundle, resolver) == proposal


def test_fabricated_evidence_ref_is_rejected():
    proposal = make_hypothesis(evidence=(ref("not-in-index", digest="9"),))
    with pytest.raises(RelationshipValidationError, match="unresolved"):
        validate_opportunity(proposal, make_bundle(), make_resolver())


@pytest.mark.parametrize("wrong_ref", [ref("bag-snapshot", revision=2, digest="b"), ref("bag-snapshot", digest="9")])
def test_same_id_with_stale_revision_or_hash_is_rejected(wrong_ref):
    proposal = make_hypothesis(evidence=(wrong_ref,))
    with pytest.raises(RelationshipValidationError, match="revision/hash"):
        validate_opportunity(proposal, make_bundle(), make_resolver())


def test_cross_workspace_evidence_is_rejected():
    resolver = make_resolver(input_workspace=ref("other-workspace", digest="1"))
    with pytest.raises(RelationshipValidationError, match="another workspace"):
        validate_opportunity(make_hypothesis(), make_bundle(), resolver)


def test_out_of_scope_evidence_is_rejected():
    bundle = make_bundle()
    outside = ref("outside-study-area", digest="8")
    resolver = FakeResolver(
        records=[
            record(WORKSPACE, entity_type="WORKSPACE"),
            record(SITE, entity_type="STUDY_AREA"),
            record(SCENARIO, entity_type="SCENARIO"),
            record(INPUT, scope=outside),
            record(bundle.bundle_ref, entity_type="ARTIFACT"),
        ],
        metric_definitions=make_resolver().metric_definitions.values(),
    )
    with pytest.raises(RelationshipValidationError, match="scope does not cover"):
        validate_opportunity(make_hypothesis(), make_bundle(), resolver)


def test_evidence_from_another_scenario_is_rejected():
    resolver = make_resolver(bundle=make_bundle(scenario_ref=SCENARIO), input_scenario=ref("scenario-other", digest="7"))
    with pytest.raises(RelationshipValidationError, match="scenario mismatch"):
        validate_opportunity(
            make_hypothesis(),
            make_bundle(scenario_ref=SCENARIO),
            resolver,
        )


def test_bundle_without_scenario_rejects_scenario_bound_evidence():
    resolver = make_resolver(input_scenario=SCENARIO)
    with pytest.raises(RelationshipValidationError, match="scenario mismatch"):
        validate_opportunity(make_hypothesis(), make_bundle(scenario_ref=None), resolver)


def test_observed_problem_accepts_hash_bound_same_metric_comparison():
    bundle = make_bundle(observation_metric="synthetic.coverage_ratio", unit="ratio")
    resolver = make_resolver(bundle=bundle)
    resolver.records[BASELINE.id] = record(
        BASELINE,
        entity_type="EVIDENCE",
        metric_key="synthetic.coverage_ratio",
        unit="ratio",
        method="fixture-v1",
        value=0.0,
    )
    resolver.records[CANDIDATE.id] = record(
        CANDIDATE,
        entity_type="EVIDENCE",
        metric_key="synthetic.coverage_ratio",
        unit="ratio",
        method="fixture-v1",
        value=1.0,
    )
    resolver.metric_definitions["synthetic.coverage_ratio"] = MetricDefinition(
        metric_key="synthetic.coverage_ratio",
        unit="ratio",
        method_version="fixture-v1",
        allowed_assertions=("OBSERVATION", "COMPARISON", "IMPROVEMENT"),
        improvement_direction="HIGHER",
    )
    binding = ClaimBinding(
        metric_key="synthetic.coverage_ratio",
        scope_ref=SITE,
        input_refs=(INPUT,),
        method_version="fixture-v1",
        unit="ratio",
        assertion="IMPROVEMENT",
        baseline_ref=BASELINE,
        candidate_ref=CANDIDATE,
    )
    proposal = Opportunity(
        id="comparison-1",
        origin="AI_SUGGESTED",
        statement=render_statement(StatementTemplate(metric_ref=bundle.observations[0].metric_key), bundle, resolver), statement_template=StatementTemplate(metric_ref=bundle.observations[0].metric_key),
        kind="OBSERVED_PROBLEM",
        evidence_refs=(INPUT, BASELINE, CANDIDATE),
        scope_ref=SITE,
        claim_bindings=(binding,),
    )
    assert validate_opportunity(proposal, bundle, resolver).statement == proposal.statement


def test_comparison_rejects_method_mismatch():
    bundle = make_bundle(observation_metric="synthetic.coverage_ratio", unit="ratio")
    resolver = make_resolver(bundle=bundle)
    resolver.records[BASELINE.id] = record(
        BASELINE,
        entity_type="EVIDENCE",
        metric_key="synthetic.coverage_ratio",
        unit="ratio",
        method="old-method",
        value=0.0,
    )
    resolver.records[CANDIDATE.id] = record(
        CANDIDATE,
        entity_type="EVIDENCE",
        metric_key="synthetic.coverage_ratio",
        unit="ratio",
        method="fixture-v1",
        value=1.0,
    )
    resolver.metric_definitions["synthetic.coverage_ratio"] = MetricDefinition(
        metric_key="synthetic.coverage_ratio",
        unit="ratio",
        method_version="fixture-v1",
        allowed_assertions=("COMPARISON",),
    )
    binding = ClaimBinding(
        metric_key="synthetic.coverage_ratio",
        scope_ref=SITE,
        input_refs=(INPUT,),
        method_version="fixture-v1",
        unit="ratio",
        assertion="COMPARISON",
        baseline_ref=BASELINE,
        candidate_ref=CANDIDATE,
    )
    proposal = Opportunity(
        id="comparison-2",
        origin="AI_SUGGESTED",
        statement="Compare the same topology metric across versions.",
        kind="OBSERVED_PROBLEM",
        evidence_refs=(INPUT, BASELINE, CANDIDATE),
        scope_ref=SITE,
        claim_bindings=(binding,),
    )
    with pytest.raises(RelationshipValidationError, match="baseline/candidate metric"):
        validate_opportunity(proposal, bundle, resolver)


def test_unknown_metric_or_wrong_unit_cannot_bind_to_an_observation():
    bundle = make_bundle()
    unknown = ClaimBinding(
        metric_key="network.distance_m",
        scope_ref=SITE,
        input_refs=(INPUT,),
        method_version="fixture-v1",
        unit="m",
    )
    proposal = make_hypothesis(claim_bindings=(unknown,))
    with pytest.raises(RelationshipValidationError, match="unknown metric"):
        validate_opportunity(proposal, bundle, make_resolver())

    wrong_unit_resolver = make_resolver(bundle=bundle)
    wrong_unit_resolver.metric_definitions["road_degree_one_vertex_count"] = MetricDefinition(
        metric_key="road_degree_one_vertex_count",
        unit="vertices",
        method_version="fixture-v1",
    )
    wrong_unit = ClaimBinding(
        metric_key="road_degree_one_vertex_count",
        scope_ref=SITE,
        input_refs=(INPUT,),
        method_version="fixture-v1",
        unit="count",
    )
    with pytest.raises(RelationshipValidationError, match="unit mismatch"):
        validate_opportunity(make_hypothesis(claim_bindings=(wrong_unit,)), bundle, wrong_unit_resolver)


def test_syntax_metric_cannot_substitute_for_distance_metric():
    bundle = make_bundle(observation_metric="syntax.nain", unit="NAIN (normalized)")
    resolver = make_resolver(bundle=bundle)
    resolver.metric_definitions["network.distance_m"] = MetricDefinition(
        metric_key="network.distance_m",
        unit="m",
        method_version="fixture-v1",
    )
    binding = ClaimBinding(
        metric_key="network.distance_m",
        scope_ref=SITE,
        input_refs=(INPUT,),
        method_version="fixture-v1",
        unit="m",
    )
    with pytest.raises(RelationshipValidationError, match="does not resolve"):
        validate_opportunity(make_hypothesis(claim_bindings=(binding,)), bundle, resolver)


def test_degree_one_vertex_is_not_a_dead_end_claim():
    binding = ClaimBinding(
        metric_key="road_degree_one_vertex_count",
        scope_ref=SITE,
        input_refs=(INPUT,),
        method_version="fixture-v1",
        unit="vertices",
        assertion="DEAD_END",
    )
    with pytest.raises(RelationshipValidationError, match="not supported"):
        validate_opportunity(
            make_hypothesis(claim_bindings=(binding,)),
            make_bundle(),
            make_resolver(),
        )


def test_observed_problem_needs_valid_baseline_and_candidate():
    with pytest.raises(ValidationError, match="baseline"):
        Opportunity(
            id="unsupported-problem",
            origin="AI_SUGGESTED",
            statement="A measured problem",
            kind="OBSERVED_PROBLEM",
            evidence_refs=(INPUT,),
            scope_ref=SITE,
        )


def test_unbased_conditional_hypothesis_remains_allowed():
    proposal = make_hypothesis()
    assert validate_opportunity(proposal, make_bundle(), make_resolver()) == proposal


def test_unresolved_verification_metric_is_rejected():
    proposal = Opportunity(
        id="opportunity-verify",
        origin="AI_SUGGESTED",
        statement="Test whether the path choice changes the site topology.",
        kind="CONDITIONAL_HYPOTHESIS",
        evidence_refs=(INPUT,),
        scope_ref=SITE,
        verification_metric_keys=("unknown.metric",),
        uncertainties=("The current graph does not establish access rights.",),
    )
    with pytest.raises(RelationshipValidationError, match="unknown verification metric"):
        validate_opportunity(proposal, make_bundle(), make_resolver())


def test_validate_analysis_bundle_checks_input_coverage_and_exact_refs():
    bundle = make_bundle()
    assert validate_analysis_bundle(bundle, make_resolver()) == bundle

    outside = ref("outside-study-area", digest="8")
    resolver = make_resolver(scope=outside)
    with pytest.raises(RelationshipValidationError, match="input scope does not cover"):
        validate_analysis_bundle(bundle, resolver)


def test_ai_numeric_claim_is_rejected_for_server_binding():
    proposal = make_hypothesis(statement="There are 12 dead ends")
    with pytest.raises(RelationshipValidationError, match="cannot author measured numbers"):
        validate_opportunity(proposal, make_bundle(), make_resolver())


@pytest.mark.parametrize("statement", ["Only 120m to the quay", "Only １２０m to the quay", "僅一百二十米到碼頭"])
def test_ai_numeric_claim_rejects_ascii_fullwidth_and_chinese_numbers(statement):
    with pytest.raises(RelationshipValidationError, match="measured numbers"):
        validate_opportunity(make_hypothesis(statement=statement), make_bundle(), make_resolver())


def test_ai_numeric_claim_is_checked_in_uncertainties_and_counterexamples():
    base = make_hypothesis()
    for field in ("counterexamples", "uncertainties"):
        proposal = base.model_copy(update={field: ("The route is 12m longer.",)})
        with pytest.raises(RelationshipValidationError, match="measured numbers"):
            validate_opportunity(proposal, make_bundle(), make_resolver())


@pytest.mark.parametrize(
    "statement",
    ["A" * 1001, "Bearer synthetic-credential-value", "Inspect <think>synthetic-private-text</think> before making a recommendation."],
)
def test_direct_ai_opportunity_text_is_bounded_and_filtered(statement):
    with pytest.raises(RelationshipValidationError):
        validate_opportunity(make_hypothesis(statement=statement), make_bundle(), make_resolver())


def test_direct_ai_opportunity_limits_narrative_list_length():
    proposal = make_hypothesis().model_copy(update={"uncertainties": ("uncertain",) * 11})
    with pytest.raises(RelationshipValidationError, match="too many text entries"):
        validate_opportunity(proposal, make_bundle(), make_resolver())


def test_ai_design_preference_requires_evidence_and_cannot_contain_numbers():
    empty = Opportunity(
        id="preference-empty",
        origin="AI_SUGGESTED",
        statement="Keep a garden option open.",
        kind="DESIGN_PREFERENCE",
        scope_ref=SITE,
    )
    with pytest.raises(RelationshipValidationError, match="evidence references"):
        validate_opportunity(empty, make_bundle(), make_resolver())

    numeric = empty.model_copy(update={"evidence_refs": (INPUT,), "statement": "Keep 3 garden options open."})
    with pytest.raises(RelationshipValidationError, match="measured numbers"):
        validate_opportunity(numeric, make_bundle(), make_resolver())


class FixtureSuggestionProvider:
    is_live = False
    available = True

    def __init__(self, first, repaired=None):
        self.first = first
        self.repaired = repaired
        self.propose_calls = 0
        self.repair_calls = 0

    def propose(self, request):
        self.propose_calls += 1
        return self.first

    def repair(self, request, invalid_output, rejection_codes):
        self.repair_calls += 1
        return self.repaired


def _suggestion_payload(evidence_refs, statement=None, metric_ref="road_degree_one_vertex_count"):
    return {
        "opportunities": [{
            "statement_template": {"template_id": "METRIC_TENDENCY", "metric_ref": metric_ref,
                                   "direction": "UNRESOLVED", "verification": "DETERMINISTIC_ANALYSIS"},
            "evidence_refs": evidence_refs,
            **({"statement": statement} if statement is not None else {}),
        }],
        "evidence_refs": evidence_refs,
        "observations": ["ignored model observation"],
        "limitations": ["The graph does not verify access rights."],
        "next_questions": [],
        "private_reasoning": "must not be retained",
        "privateReasoning": "camelCase private text must not be retained",
        "chainOfThought": "camelCase chain text must not be retained",
        "thinking": "synthetic-private-thinking",
        "scratchpad": "synthetic-private-scratchpad",
        "apiKey": "synthetic-secret-must-not-be-retained",
        "access-token": "synthetic-access-token-must-not-be-retained",
    }


def test_suggestion_request_is_typed_and_has_no_freeform_tool_route():
    from urban_design.site_intelligence.opportunities import build_suggestion_request

    request = build_suggestion_request(make_bundle())
    assert request.observations
    assert request.allowed_actions
    assert all(isinstance(item.metric_key, str) for item in request.observations)
    assert not hasattr(request, "sql")
    assert not hasattr(request, "python")
    assert not hasattr(request, "query")


def test_missing_provider_preserves_manual_design_intent_route():
    from urban_design.site_intelligence.opportunities import (
        SuggestionStatus,
        designer_authored_intent,
        suggest_opportunities,
    )

    bundle = make_bundle()
    result = suggest_opportunities(bundle, make_resolver(), provider=None)
    assert result.status == SuggestionStatus.UNAVAILABLE
    assert result.analysis_ref == bundle.bundle_ref
    assert result.manual_entry_available is True
    intent = designer_authored_intent(
        intent_id="manual-1", text="Keep a public garden option open.", scope_ref=SITE
    )
    assert intent.origin == "DESIGNER_AUTHORED"
    assert intent.kind == "PREFERENCE"


def test_fake_suggestion_uses_exact_refs_and_never_promotes_model_observations():
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    token = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    provider = FixtureSuggestionProvider(_suggestion_payload([token]))
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert result.status == "AVAILABLE"
    assert len(result.opportunities) == 1
    opportunity = result.opportunities[0]
    assert opportunity.kind == "CONDITIONAL_HYPOTHESIS"
    assert opportunity.origin == "AI_SUGGESTED"
    assert opportunity.evidence_refs == (INPUT,)
    assert opportunity.suggested_actions == ("TEST_HYPOTHESIS",)
    assert "private_reasoning" not in result.raw_structured_output
    assert "privateReasoning" not in result.raw_structured_output
    assert "chainOfThought" not in result.raw_structured_output
    assert "thinking" not in result.raw_structured_output
    assert "scratchpad" not in result.raw_structured_output
    assert "apiKey" not in result.raw_structured_output
    assert "access-token" not in result.raw_structured_output
    assert "synthetic-secret-must-not-be-retained" not in repr(result.raw_structured_output)
    assert "synthetic-private-thinking" not in repr(result.raw_structured_output)
    assert "synthetic-private-scratchpad" not in repr(result.raw_structured_output)
    assert provider.propose_calls == 1
    assert provider.repair_calls == 0


def test_invalid_reference_gets_only_one_bounded_repair():
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    exact = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    provider = FixtureSuggestionProvider(
        _suggestion_payload([INPUT.id]),
        repaired=_suggestion_payload([exact]),
    )
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert result.status == "AVAILABLE"
    assert provider.propose_calls == 1
    assert provider.repair_calls == 1
    assert result.repair_attempts == 1


def test_invalid_output_after_single_repair_retains_raw_and_rejection_codes():
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    provider = FixtureSuggestionProvider(
        _suggestion_payload(["fabricated-ref"]),
        repaired=_suggestion_payload(["still-fabricated"]),
    )
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert result.status == "INVALID_MODEL_OUTPUT"
    assert provider.propose_calls == 1
    assert provider.repair_calls == 1
    assert result.raw_structured_output
    assert result.rejection_codes
    assert result.manual_entry_available is True


def test_numeric_model_claim_is_rejected_and_live_provider_is_gated():
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    token = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    provider = FixtureSuggestionProvider(_suggestion_payload([token], "There are 12 dead ends."))
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider, max_repair=0)
    assert result.status == "INVALID_MODEL_OUTPUT"
    assert result.opportunities == ()

    live_provider = FixtureSuggestionProvider(_suggestion_payload([token]))
    live_provider.is_live = True
    gated = suggest_opportunities(make_bundle(), make_resolver(), provider=live_provider)
    assert gated.status == "UNAVAILABLE"
    assert live_provider.propose_calls == 0


def test_unknown_provider_outcome_is_not_retried():
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    provider = FixtureSuggestionProvider({"provider_status": "LIVE_AI: OUTCOME_UNKNOWN"})
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert result.status == "OUTCOME_UNKNOWN"
    assert provider.propose_calls == 1
    assert provider.repair_calls == 0


@pytest.mark.parametrize(
    "status",
    [
        "LIVE_AI: BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED",
        "LIVE_AI: CONNECTION_FAILED",
        "LIVE_AI: REQUEST_REJECTED",
        "LIVE_AI: HERMES_TOOLSET_CHECK_FAILED",
    ],
)
def test_provider_failure_status_is_unavailable_without_repair(status):
    from urban_design.site_intelligence.opportunities import SuggestionStatus, suggest_opportunities

    provider = FixtureSuggestionProvider({"provider_status": status}, repaired=_suggestion_payload(["bad-ref"]))
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=provider)
    assert result.status == SuggestionStatus.UNAVAILABLE
    assert provider.propose_calls == 1
    assert provider.repair_calls == 0


def test_unknown_is_live_provider_and_provider_cannot_claim_designer_origin():
    from urban_design.site_intelligence.opportunities import SuggestionStatus, suggest_opportunities

    class ProviderWithoutLiveFlag:
        available = True

        def __init__(self):
            self.propose_calls = 0

        def propose(self, request):
            self.propose_calls += 1
            return _suggestion_payload([f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"])

    no_flag = ProviderWithoutLiveFlag()
    blocked = suggest_opportunities(make_bundle(), make_resolver(), provider=no_flag)
    assert blocked.status == SuggestionStatus.UNAVAILABLE
    assert no_flag.propose_calls == 0

    forged_origin = FixtureSuggestionProvider(
        _suggestion_payload([f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"], "The route is 12m long.")
    )
    forged_origin.suggestion_origin = "DESIGNER_AUTHORED"
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=forged_origin, max_repair=0)
    assert result.status == SuggestionStatus.INVALID_MODEL_OUTPUT
    assert result.opportunities == ()


def test_repair_limit_is_hard_capped_at_one():
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    with pytest.raises(ValueError, match="cannot exceed one"):
        suggest_opportunities(make_bundle(), make_resolver(), provider=None, max_repair=2)


@pytest.mark.parametrize("field", ["design_hypotheses", "opportunities"])
def test_suggestion_count_is_capped_at_five(field):
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    token = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    entries = ["A conditional design question."] * 6
    raw = {"evidence_refs": [token], field: entries}
    if field == "opportunities":
        raw["opportunities"] = [
            {"statement_template": {"template_id": "METRIC_TENDENCY", "metric_ref": "road_degree_one_vertex_count",
                                    "direction": "UNRESOLVED", "verification": "DETERMINISTIC_ANALYSIS"},
             "evidence_refs": [token], "suggested_actions": ["TEST_HYPOTHESIS"]}
            for text in entries
        ]
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=FixtureSuggestionProvider(raw), max_repair=0)
    assert result.status == "INVALID_MODEL_OUTPUT"
    assert result.opportunities == ()


def test_extremely_large_hypothesis_list_is_rejected_and_raw_output_is_bounded():
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    token = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    raw = {
        "design_hypotheses": ["Conditional hypothesis " + "x" * index for index in range(500)],
        "evidence_refs": [token],
        "next_questions": [],
    }
    result = suggest_opportunities(
        make_bundle(),
        make_resolver(),
        provider=FixtureSuggestionProvider(raw),
        max_repair=0,
    )

    assert result.status == "INVALID_MODEL_OUTPUT"
    assert result.opportunities == ()
    assert len(result.raw_structured_output["design_hypotheses"]) == 200


@pytest.mark.parametrize("field", ["statement", "counterexamples", "uncertainties"])
def test_suggestion_text_fields_have_length_bounds(field):
    from urban_design.site_intelligence.opportunities import suggest_opportunities

    token = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    draft = _suggestion_payload([token])["opportunities"][0]
    if field == "statement":
        draft[field] = "A" * 1001
    else:
        draft[field] = ["A" * 1001]
    raw = {"opportunities": [draft]}
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=FixtureSuggestionProvider(raw), max_repair=0)
    assert result.status == "INVALID_MODEL_OUTPUT"


def test_sanitizer_uses_exact_sensitive_keys_and_filters_think_and_credentials():
    from urban_design.site_intelligence.opportunities import _sanitize_raw

    sanitized = _sanitize_raw({
        "analysis_ref": "expected-analysis-ref",
        "tokens_used": 12,
        "passwd": "synthetic-private-value",
        "ＰＷＤ": "synthetic-private-value",
        "access_key": "synthetic-private-value",
        "cookie": "synthetic-private-value",
        "bearer": "synthetic-private-value",
        "jwt": "synthetic-private-value",
        "session_id": "synthetic-private-value",
        "think": "synthetic-private-value",
        "reason": "synthetic-private-value",
        "statement": "Safe <think>synthetic-private-text</think> Bearer synthetic-credential-value sk-examplecredential",
        "unknown_field": "must not persist",
    })
    assert "analysis_ref" not in sanitized
    assert "tokens_used" not in sanitized
    assert not any(key in sanitized for key in ("passwd", "ＰＷＤ", "access_key", "cookie", "bearer", "jwt", "session_id", "think", "reason"))
    assert "<think>" not in sanitized["statement"]
    assert "synthetic-private-text" not in sanitized["statement"]
    assert "synthetic-credential-value" not in sanitized["statement"]
    assert "sk-examplecredential" not in sanitized["statement"]
    assert "unknown_field" not in sanitized


def test_draft_evidence_references_are_deduplicated_in_first_seen_order():
    from urban_design.site_intelligence.opportunities import _drafts_from_raw, build_suggestion_request

    bundle = make_bundle()
    request = build_suggestion_request(bundle)
    first = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    other = ref("other-input", digest="7")
    request = request.model_copy(update={
        "allowed_evidence_refs": (*request.allowed_evidence_refs, type(request.analysis_ref)(token=f"{other.id}@{other.revision}#{other.sha256}", ref=other))
    })
    draft = _drafts_from_raw(
        _suggestion_payload([first, request.allowed_evidence_refs[-1].token, first]),
        request,
    )[0]
    assert draft["evidence_refs"] == (INPUT, other)


def test_real_site_metrics_bundle_with_multiple_observations_supports_suggestions():
    from shapely.geometry import box
    from urban_design.site_analysis import calculate_site_metrics
    from urban_design.site_intelligence.adapters import ExistingAnalysisResults, build_analysis_bundle
    from urban_design.site_intelligence.opportunities import build_suggestion_request, suggest_opportunities

    sources = (ref("bag-source", digest="b"), ref("water-source", digest="c"), ref("road-source", digest="d"))
    complete = {
        name: {"status": "DECLARED_COMPLETE_WITHIN_SCOPE", "evidence_refs": [f"fixture:{name}"]}
        for name in ("buildings", "water", "roads")
    }
    metrics = calculate_site_metrics(
        study_area_geom=box(0, 0, 100, 100),
        study_area_id=SITE.id,
        building_features=[{"id": "building-1", "geometry": box(10, 10, 20, 20), "properties": {}}],
        water_features=[],
        road_features=[],
        source_coverage=complete,
    )
    bundle = build_analysis_bundle(
        workspace_ref=WORKSPACE,
        study_area_ref=SITE,
        source_refs=sources,
        method_config={},
        results={"site_metrics": metrics, "site_status": "COMPUTED"},
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    resolver = FakeResolver(
        records=[
            record(WORKSPACE, entity_type="WORKSPACE"),
            record(SITE, entity_type="STUDY_AREA"),
            *(record(source, status="UNVERIFIED") for source in sources),
            record(bundle.bundle_ref, entity_type="ARTIFACT"),
        ],
        metric_definitions=make_resolver().metric_definitions.values(),
    )
    request = build_suggestion_request(bundle)
    assert len(request.observations) > 1
    tokens = [item.token for item in request.allowed_evidence_refs]
    for observation in bundle.observations:
        resolver.metric_definitions[observation.metric_key] = MetricDefinition(
            metric_key=observation.metric_key, unit=observation.unit, method_version=observation.method_version)
    result = suggest_opportunities(
        bundle,
        resolver,
        provider=FixtureSuggestionProvider(_suggestion_payload(tokens, metric_ref=bundle.observations[0].metric_key)),
        max_repair=0,
    )
    assert result.status == "AVAILABLE"
    assert result.opportunities[0].evidence_refs == sources

    for obs in bundle.observations:
        resolver.metric_definitions[obs.metric_key] = MetricDefinition(metric_key=obs.metric_key, unit=obs.unit, method_version=obs.method_version)
    from urban_design.model_provider import DeterministicFixtureProvider
    from urban_design.site_intelligence.opportunities import CriticSuggestionAdapter
    real_fixture_result = suggest_opportunities(
        bundle, resolver, provider=CriticSuggestionAdapter(DeterministicFixtureProvider()), max_repair=0,
    )
    assert real_fixture_result.status == "AVAILABLE"
    assert 0 < len(real_fixture_result.opportunities) <= 5
    assert all(item.origin == "RULE_SUGGESTED" for item in real_fixture_result.opportunities)
    assert all(len(set(item.evidence_refs)) == len(item.evidence_refs) for item in real_fixture_result.opportunities)


@pytest.mark.parametrize("candidate_values", [(1.0, 1.0), (0.0, 1.0)])
def test_observed_problem_comparison_must_show_worsening(candidate_values):
    baseline_value, candidate_value = candidate_values
    bundle = make_bundle(observation_metric="synthetic.coverage_ratio", unit="ratio")
    resolver = make_resolver(bundle=bundle)
    resolver.records[BASELINE.id] = record(
        BASELINE, entity_type="EVIDENCE", metric_key="synthetic.coverage_ratio", unit="ratio", method="fixture-v1", value=baseline_value
    )
    resolver.records[CANDIDATE.id] = record(
        CANDIDATE, entity_type="EVIDENCE", metric_key="synthetic.coverage_ratio", unit="ratio", method="fixture-v1", value=candidate_value
    )
    resolver.metric_definitions["synthetic.coverage_ratio"] = MetricDefinition(
        metric_key="synthetic.coverage_ratio", unit="ratio", method_version="fixture-v1",
        allowed_assertions=("OBSERVATION", "COMPARISON", "IMPROVEMENT"), improvement_direction="HIGHER",
    )
    binding = ClaimBinding(
        metric_key="synthetic.coverage_ratio", scope_ref=SITE, input_refs=(INPUT,),
        method_version="fixture-v1", unit="ratio", assertion="COMPARISON",
        baseline_ref=BASELINE, candidate_ref=CANDIDATE,
    )
    proposal = Opportunity(
        id="comparison-problem", origin="AI_SUGGESTED", statement=render_statement(StatementTemplate(metric_ref=bundle.observations[0].metric_key), bundle, resolver), statement_template=StatementTemplate(metric_ref=bundle.observations[0].metric_key),
        kind="OBSERVED_PROBLEM", evidence_refs=(INPUT, BASELINE, CANDIDATE), scope_ref=SITE,
        claim_bindings=(binding,),
    )
    with pytest.raises(RelationshipValidationError, match="worsen|direction"):
        validate_opportunity(proposal, bundle, resolver)


def test_comparison_records_must_be_evidence_or_observation_entities():
    bundle = make_bundle(observation_metric="synthetic.coverage_ratio", unit="ratio")
    resolver = make_resolver(bundle=bundle)
    resolver.records[BASELINE.id] = record(
        BASELINE, entity_type="EVIDENCE", metric_key="synthetic.coverage_ratio", unit="ratio", method="fixture-v1", value=0.0
    )
    resolver.records[CANDIDATE.id] = record(
        CANDIDATE, entity_type="OTHER", metric_key="synthetic.coverage_ratio", unit="ratio", method="fixture-v1", value=1.0
    )
    resolver.metric_definitions["synthetic.coverage_ratio"] = MetricDefinition(
        metric_key="synthetic.coverage_ratio", unit="ratio", method_version="fixture-v1",
        allowed_assertions=("OBSERVATION", "COMPARISON", "IMPROVEMENT"), improvement_direction="HIGHER",
    )
    binding = ClaimBinding(
        metric_key="synthetic.coverage_ratio", scope_ref=SITE, input_refs=(INPUT,),
        method_version="fixture-v1", unit="ratio", assertion="COMPARISON",
        baseline_ref=BASELINE, candidate_ref=CANDIDATE,
    )
    proposal = Opportunity(
        id="comparison-entity", origin="AI_SUGGESTED", statement=render_statement(StatementTemplate(metric_ref=bundle.observations[0].metric_key), bundle, resolver), statement_template=StatementTemplate(metric_ref=bundle.observations[0].metric_key),
        kind="CONDITIONAL_HYPOTHESIS", evidence_refs=(INPUT, BASELINE, CANDIDATE), scope_ref=SITE,
        claim_bindings=(binding,),
    )
    with pytest.raises(RelationshipValidationError, match="entity type"):
        validate_opportunity(proposal, bundle, resolver)


def test_observation_binding_matches_indexed_observation_value():
    indexed_observation = ref("indexed-observation", digest="6")
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    resolver.records[indexed_observation.id] = record(
        indexed_observation,
        entity_type="OBSERVATION",
        metric_key="road_degree_one_vertex_count",
        unit="vertices",
        method="fixture-v1",
        value=99.0,
    )
    binding = ClaimBinding(
        metric_key="road_degree_one_vertex_count", scope_ref=SITE, input_refs=(INPUT,),
        method_version="fixture-v1", unit="vertices", assertion="OBSERVATION",
    )
    proposal = Opportunity(
        id="indexed-observation-claim", origin="AI_SUGGESTED", statement=render_statement(StatementTemplate(metric_ref=bundle.observations[0].metric_key), bundle, resolver), statement_template=StatementTemplate(metric_ref=bundle.observations[0].metric_key),
        kind="CONDITIONAL_HYPOTHESIS", evidence_refs=(INPUT, indexed_observation), scope_ref=SITE,
        claim_bindings=(binding,),
    )
    with pytest.raises(RelationshipValidationError, match="observation value"):
        validate_opportunity(proposal, bundle, resolver)


def test_observation_binding_accepts_matching_indexed_observation_value():
    indexed_observation = ref("indexed-observation-match", digest="6")
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    resolver.records[indexed_observation.id] = record(
        indexed_observation,
        entity_type="OBSERVATION",
        metric_key="road_degree_one_vertex_count",
        unit="vertices",
        method="fixture-v1",
        value=1.0,
    )
    binding = ClaimBinding(
        metric_key="road_degree_one_vertex_count", scope_ref=SITE, input_refs=(INPUT,),
        method_version="fixture-v1", unit="vertices", assertion="OBSERVATION",
    )
    proposal = Opportunity(
        id="indexed-observation-match", origin="AI_SUGGESTED", statement=render_statement(StatementTemplate(metric_ref=bundle.observations[0].metric_key), bundle, resolver), statement_template=StatementTemplate(metric_ref=bundle.observations[0].metric_key),
        kind="CONDITIONAL_HYPOTHESIS", evidence_refs=(INPUT, indexed_observation), scope_ref=SITE,
        claim_bindings=(binding,),
    )
    assert validate_opportunity(proposal, bundle, resolver) == proposal


def test_bundle_content_hash_is_rechecked_before_opportunity_validation():
    bundle = make_bundle()
    altered = bundle.model_copy(update={"observations": (bundle.observations[0].model_copy(update={"value": 999.0}),)})
    with pytest.raises(RelationshipValidationError, match="bundle content hash"):
        validate_opportunity(make_hypothesis(), altered, make_resolver())


@pytest.mark.parametrize(
    ("metric_key", "unit", "unsupported_assertion"),
    [
        ("max_walking_detour_ratio", "ratio", "SYNTAX_CHOICE"),
        ("syntax_pedestrian_800m_nain_mean", "NAIN", "NETWORK_DETOUR_RATIO"),
        ("nonbuilding_nonwater_residual_area_m2", "m2", "GEOMETRIC_PROXIMITY"),
        ("nonbuilding_nonwater_residual_ratio_pct", "%", "GEOMETRIC_PROXIMITY"),
    ],
)
def test_metric_assertion_limits_cover_problem_definition_keys(metric_key, unit, unsupported_assertion):
    bundle = make_bundle(observation_metric=metric_key, unit=unit)
    resolver = make_resolver(bundle=bundle)
    resolver.metric_definitions[metric_key] = MetricDefinition(
        metric_key=metric_key,
        unit=unit,
        method_version="fixture-v1",
        allowed_assertions=("OBSERVATION", "NETWORK_DETOUR_RATIO", "SYNTAX_CHOICE", "GEOMETRIC_PROXIMITY"),
    )
    binding = ClaimBinding(
        metric_key=metric_key, scope_ref=SITE, input_refs=(INPUT,), method_version="fixture-v1",
        unit=unit, assertion=unsupported_assertion,
    )
    with pytest.raises(RelationshipValidationError, match="not supported"):
        validate_opportunity(make_hypothesis(claim_bindings=(binding,)), bundle, resolver)


def test_existing_critic_fixture_adapter_stays_non_live_and_rule_labeled():
    from urban_design.model_provider import DeterministicFixtureProvider
    from urban_design.site_intelligence.opportunities import (
        CriticSuggestionAdapter,
        suggest_opportunities,
    )

    adapter = CriticSuggestionAdapter(DeterministicFixtureProvider())
    result = suggest_opportunities(make_bundle(), make_resolver(), provider=adapter)
    assert result.status == "AVAILABLE"
    assert result.opportunities[0].origin == "RULE_SUGGESTED"
    assert result.opportunities[0].kind == "CONDITIONAL_HYPOTHESIS"


@pytest.mark.parametrize("statement", ["路長١٢٠m", "路長壹佰米", "路長兩米", "Route is 𝟙𝟚m", "Route is ²m"])
def test_numeric_unicode_counterexamples_are_rejected(statement):
    with pytest.raises(RelationshipValidationError, match="measured numbers"):
        validate_opportunity(make_hypothesis(statement=statement), make_bundle(), make_resolver())


def test_registered_method_version_is_an_explicit_identifier_allowlist():
    proposal = make_hypothesis().model_copy(update={"uncertainties": ("Check fixture-v1 evidence for a route hypothesis.",)})
    assert validate_opportunity(proposal, make_bundle(), make_resolver()) == proposal


@pytest.mark.parametrize("key", ["privateKey", "client_secret", "apiToken", "auth", "openai_key", "reasoning_summary", "internal_notes", "思考"])
def test_additional_exact_private_keys_are_filtered(key):
    from urban_design.site_intelligence.opportunities import _sanitize_raw
    assert _sanitize_raw({key: "synthetic-private", "statement": "safe"}) == {"statement": "safe"}


def test_unregistered_content_hashed_bundle_is_rejected():
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    resolver.records.pop(bundle.bundle_ref.id, None)
    with pytest.raises(RelationshipValidationError, match="unresolved evidence reference"):
        validate_analysis_bundle(bundle, resolver)


@pytest.mark.parametrize("mismatch", ["status", "inputs"])
def test_indexed_observation_requires_exact_status_and_lineage(mismatch):
    indexed = ref("indexed-lineage", digest="6")
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    resolved = record(indexed, entity_type="OBSERVATION", metric_key="road_degree_one_vertex_count",
                      unit="vertices", method="fixture-v1", value=1.0)
    # Fixture bypass constructs the adversarial trusted-index response, not a new schema.
    resolved = resolved.model_copy(update={"analysis_status": "BLOCKED" if mismatch == "status" else "AVAILABLE",
                                          "input_refs": () if mismatch == "inputs" else (INPUT,)})
    resolver.records[indexed.id] = resolved
    binding = ClaimBinding(metric_key="road_degree_one_vertex_count", scope_ref=SITE,
                           input_refs=(INPUT,), method_version="fixture-v1", unit="vertices", assertion="OBSERVATION")
    proposal = make_hypothesis(evidence=(INPUT, indexed), claim_bindings=(binding,))
    with pytest.raises(RelationshipValidationError, match="status|lineage"):
        validate_opportunity(proposal, bundle, resolver)



def test_invalid_bundle_never_dispatches_or_repairs_provider():
    from urban_design.site_intelligence.opportunities import suggest_opportunities
    bundle = make_bundle()
    altered = bundle.model_copy(update={"observations": (bundle.observations[0].model_copy(update={"value": 999.0}),)})
    provider = FixtureSuggestionProvider(_suggestion_payload([f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"]))
    result = suggest_opportunities(altered, make_resolver(), provider=provider)
    assert result.status == "UNAVAILABLE"
    assert result.reason_codes == ("ANALYSIS_BUNDLE_INVALID",)
    assert provider.propose_calls == 0
    assert provider.repair_calls == 0



def test_duplicate_metric_observations_still_reject_after_citation_deduplication():
    bundle = make_bundle()
    payload = bundle.model_dump()
    payload["observations"] = [bundle.observations[0], bundle.observations[0]]
    with pytest.raises(ValidationError, match="duplicate metric/scope/method"):
        SiteAnalysisBundle.model_validate(payload)


@pytest.mark.parametrize("registry_state", ["missing", "wrong-unit", "wrong-method"])
def test_numeric_metric_id_exemption_requires_resolved_matching_registry(registry_state):
    key = "fixture.metric_m2"
    bundle = make_bundle(observation_metric=key, unit="m2")
    resolver = make_resolver(bundle=bundle)
    if registry_state != "missing":
        resolver.metric_definitions[key] = MetricDefinition(metric_key=key,
            unit="m" if registry_state == "wrong-unit" else "m2",
            method_version="other-v1" if registry_state == "wrong-method" else "fixture-v1")
    with pytest.raises(RelationshipValidationError, match="measured numbers"):
        validate_opportunity(make_hypothesis(statement="Inspect fixture.metric_m2 evidence."), bundle, resolver)


@pytest.mark.parametrize("extra", ["", " 120m", " 120公尺"])
def test_registered_full_metric_id_does_not_exempt_extra_measured_numbers(extra):
    key = "fixture.metric_m2"
    bundle = make_bundle(observation_metric=key, unit="m2")
    resolver = make_resolver(bundle=bundle)
    resolver.metric_definitions[key] = MetricDefinition(metric_key=key, unit="m2", method_version="fixture-v1")
    template = StatementTemplate(metric_ref=key)
    proposal = make_hypothesis().model_copy(update={"statement_template": template, "statement": render_statement(template, bundle, resolver) + extra})
    if extra:
        with pytest.raises(RelationshipValidationError, match="measured numbers"):
            validate_opportunity(proposal, bundle, resolver)
    else:
        assert validate_opportunity(proposal, bundle, resolver) == proposal


def test_fixture_card_bound_preserves_full_bundle_zero_and_rejects_live_overflow():
    from urban_design.site_intelligence.adapters import ExistingAnalysisResults, build_analysis_bundle
    from urban_design.site_intelligence.opportunities import CriticSuggestionAdapter, build_suggestion_request, suggest_opportunities
    from urban_design.model_provider import DeterministicFixtureProvider
    metrics = {"building_count": 0, "building_footprint_area_m2": 0.0, "ground_coverage_ratio": 0.0,
               "water_area_m2": 0.0, "water_coverage_ratio": 0.0, "total_road_length_m": 0.0,
               "road_segment_count": 0, "usage_distribution": {},
               "source_data_status": {name: "DECLARED_COMPLETE_WITHIN_SCOPE" for name in ("buildings", "water", "roads")}}
    bundle = build_analysis_bundle(workspace_ref=WORKSPACE, study_area_ref=SITE, source_refs=(INPUT,),
        method_config={}, results=ExistingAnalysisResults(site_metrics=metrics, site_status="COMPUTED"),
        created_at=datetime(2026,9,30,tzinfo=timezone.utc))
    before = bundle.model_dump_json()
    resolver = make_resolver(bundle=bundle)
    for obs in bundle.observations:
        resolver.metric_definitions[obs.metric_key] = MetricDefinition(metric_key=obs.metric_key, unit=obs.unit, method_version=obs.method_version)
    request = build_suggestion_request(bundle)
    assert len(request.observations) > 5
    assert request.observations[0].value == 0.0
    fixture = CriticSuggestionAdapter(DeterministicFixtureProvider())
    fixture_request = fixture._critic_request(request, bound_fixture=fixture._deterministic_fixture)
    assert len(fixture_request.evidence_bundle) == 5
    assert fixture_request.evidence_bundle[0]["value"] == 0.0
    result = suggest_opportunities(bundle, resolver, provider=fixture, max_repair=0)
    assert result.status == "AVAILABLE" and len(result.opportunities) == 5
    assert bundle.model_dump_json() == before
    assert len(build_suggestion_request(bundle).observations) == len(request.observations)
    token = f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"
    raw = {"provider_status": "LIVE_AI: ACTIVE", "opportunities": _suggestion_payload([token])["opportunities"] * 6}
    live = FixtureSuggestionProvider(raw)
    live.is_live = True
    rejected = suggest_opportunities(bundle, resolver, provider=live, live_authorized=True, budget_authorized=True, max_repair=0)
    assert rejected.status == "INVALID_MODEL_OUTPUT" and rejected.opportunities == ()
    assert len(rejected.raw_structured_output["opportunities"]) == 6
    assert bundle.model_dump_json() == before


@pytest.mark.parametrize("text", ["Inspect fixture.metric_m2.extra", "Inspect unregistered-fixture.metric_m2"])
def test_registered_metric_id_exemption_never_matches_partial_identifiers(text):
    key = "fixture.metric_m2"
    bundle = make_bundle(observation_metric=key, unit="m2")
    resolver = make_resolver(bundle=bundle)
    resolver.metric_definitions[key] = MetricDefinition(metric_key=key, unit="m2", method_version="fixture-v1")
    with pytest.raises(RelationshipValidationError, match="measured numbers"):
        validate_opportunity(make_hypothesis(statement=text), bundle, resolver)


@pytest.mark.parametrize("entity_type", ["OTHER", "ARTIFACT", "SCENARIO"])
def test_analysis_bundle_requires_study_area_entity_type(entity_type):
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    indexed = resolver.records[bundle.study_area_ref.id]
    resolver.records[bundle.study_area_ref.id] = indexed.model_copy(update={"entity_type": entity_type})
    with pytest.raises(RelationshipValidationError, match="study-area reference does not resolve to a StudyArea"):
        validate_analysis_bundle(bundle, resolver)


def test_analysis_bundle_accepts_exact_study_area_entity_type():
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    assert resolver.records[bundle.study_area_ref.id].entity_type == "STUDY_AREA"
    assert validate_analysis_bundle(bundle, resolver) == bundle


@pytest.mark.parametrize("entity_type", ["OTHER", "ARTIFACT", "SCENARIO"])
def test_invalid_study_area_entity_type_never_dispatches_suggestions(entity_type):
    from urban_design.site_intelligence.opportunities import suggest_opportunities
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    indexed = resolver.records[bundle.study_area_ref.id]
    resolver.records[bundle.study_area_ref.id] = indexed.model_copy(update={"entity_type": entity_type})
    provider = FixtureSuggestionProvider(_suggestion_payload([f"{INPUT.id}@{INPUT.revision}#{INPUT.sha256}"]))
    result = suggest_opportunities(bundle, resolver, provider=provider)
    assert result.status == "UNAVAILABLE"
    assert result.reason_codes == ("ANALYSIS_BUNDLE_INVALID",)
    assert result.opportunities == ()
    assert result.repair_attempts == 0
    assert provider.propose_calls == 0
    assert provider.repair_calls == 0



def comparison_status_fixture(assertion="COMPARISON", entity_type="EVIDENCE", kind="OBSERVED_PROBLEM"):
    bundle = make_bundle(observation_metric="synthetic.coverage_ratio", unit="ratio")
    resolver = make_resolver(bundle=bundle)
    resolver.metric_definitions["synthetic.coverage_ratio"] = MetricDefinition(
        metric_key="synthetic.coverage_ratio", unit="ratio", method_version="fixture-v1",
        improvement_direction="LOWER" if assertion == "COMPARISON" else "HIGHER")
    for ref_value, value in ((BASELINE, 0.0), (CANDIDATE, 1.0)):
        resolver.records[ref_value.id] = record(ref_value, entity_type=entity_type,
            metric_key="synthetic.coverage_ratio", unit="ratio", method="fixture-v1", value=value)
    binding = ClaimBinding(metric_key="synthetic.coverage_ratio", scope_ref=SITE, input_refs=(INPUT,),
        method_version="fixture-v1", unit="ratio", assertion=assertion, baseline_ref=BASELINE, candidate_ref=CANDIDATE)
    proposal = Opportunity(id="status-comparison", origin="AI_SUGGESTED", statement=render_statement(StatementTemplate(metric_ref=bundle.observations[0].metric_key), bundle, resolver), statement_template=StatementTemplate(metric_ref=bundle.observations[0].metric_key),
        kind=kind, evidence_refs=(INPUT, BASELINE, CANDIDATE), scope_ref=SITE, claim_bindings=(binding,))
    return proposal, bundle, resolver


@pytest.mark.parametrize("entity_type", ["EVIDENCE", "OBSERVATION"])
@pytest.mark.parametrize("status", ["BLOCKED", "NOT_RUN"])
@pytest.mark.parametrize("side", [BASELINE, CANDIDATE], ids=["baseline", "candidate"])
@pytest.mark.parametrize("assertion", ["COMPARISON", "IMPROVEMENT"])
def test_comparison_rejects_explicit_unavailable_member(entity_type, status, side, assertion):
    proposal, bundle, resolver = comparison_status_fixture(assertion, entity_type)
    resolver.records[side.id] = resolver.records[side.id].model_copy(update={"analysis_status": status})
    with pytest.raises(RelationshipValidationError, match="analysis status"):
        validate_opportunity(proposal, bundle, resolver)


@pytest.mark.parametrize("side", [BASELINE, CANDIDATE], ids=["baseline", "candidate"])
@pytest.mark.parametrize("assertion", ["COMPARISON", "IMPROVEMENT"])
def test_partial_comparison_cannot_support_observed_problem(side, assertion):
    proposal, bundle, resolver = comparison_status_fixture(assertion)
    resolver.records[side.id] = resolver.records[side.id].model_copy(update={"analysis_status": "PARTIAL"})
    with pytest.raises(RelationshipValidationError, match="partial"):
        validate_opportunity(proposal, bundle, resolver)


@pytest.mark.parametrize("assertion", ["COMPARISON", "IMPROVEMENT"])
def test_legacy_evidence_status_is_accepted_with_notification_and_designer_question(assertion):
    for entity in ("EVIDENCE", "OBSERVATION"):
        proposal, bundle, resolver = comparison_status_fixture(assertion, entity)
        accepted = validate_opportunity(proposal, bundle, resolver)
        assert accepted.statement == proposal.statement
        if entity == "EVIDENCE":
            assert "LEGACY_ANALYSIS_STATUS_UNSET" in accepted.limitation_codes
            assert "LEGACY_ANALYSIS_STATUS_UNSET" in accepted.uncertainties
            assert accepted.designer_questions
        else:
            assert "LEGACY_ANALYSIS_STATUS_UNSET" not in accepted.limitation_codes
            assert accepted.designer_questions == ()


@pytest.mark.parametrize("side", [BASELINE, CANDIDATE], ids=["baseline", "candidate"])
@pytest.mark.parametrize("field,value", [("analysis_status", None), ("input_refs", ())])
def test_comparison_observation_accepts_legacy_status_with_notification_or_requires_lineage(side, field, value):
    proposal, bundle, resolver = comparison_status_fixture(entity_type="OBSERVATION")
    resolver.records[side.id] = resolver.records[side.id].model_copy(update={field: value})
    if field == "analysis_status":
        accepted = validate_opportunity(proposal, bundle, resolver)
        assert "LEGACY_ANALYSIS_STATUS_UNSET" in accepted.limitation_codes
        assert accepted.designer_questions
    else:
        with pytest.raises(RelationshipValidationError, match="lineage"):
            validate_opportunity(proposal, bundle, resolver)


def test_partial_conditional_comparison_automatically_adds_structured_partial_limitation():
    proposal, bundle, resolver = comparison_status_fixture(kind="CONDITIONAL_HYPOTHESIS")
    resolver.records[BASELINE.id] = resolver.records[BASELINE.id].model_copy(update={"analysis_status": "PARTIAL"})
    accepted = validate_opportunity(proposal, bundle, resolver)
    assert "PARTIAL_ANALYSIS_EVIDENCE" in accepted.limitation_codes
    assert "PARTIAL_ANALYSIS_EVIDENCE" in accepted.uncertainties
