"""Counterexamples for Founder-approved A2 evidence semantics."""
import pytest
from pydantic import ValidationError
from test_opportunity_relationships import (make_bundle, make_resolver, make_hypothesis,
    comparison_status_fixture, record, ref, INPUT, SITE, SCENARIO, CANDIDATE, BASELINE)
from urban_design.site_intelligence.contracts import StatementTemplate, compute_site_analysis_bundle_ref
from urban_design.site_intelligence.relationships import (validate_opportunity, validate_analysis_bundle,
    RelationshipValidationError, render_statement)


@pytest.mark.parametrize("text", ["two routes", "twenty routes", "half the area", "a third of the area", "three quarters", "IV routes", "iv routes", "半數建築"])
@pytest.mark.parametrize("field", ["statement", "uncertainties", "counterexamples"])
def test_a2_quantities_cannot_enter_ai_narrative(text, field):
    proposal = make_hypothesis().model_copy(update={field: text if field == "statement" else (text,)})
    with pytest.raises(RelationshipValidationError, match="measured numbers"):
        validate_opportunity(proposal, make_bundle(), make_resolver())


@pytest.mark.parametrize("field,value", [("template_id", "FREE_TEXT"), ("direction", "half"), ("verification", "IV"), ("metric_ref", "half the area")])
def test_a2_template_slots_cannot_author_quantities(field, value):
    payload = StatementTemplate(metric_ref="road_degree_one_vertex_count").model_dump()
    payload[field] = value
    if field == "metric_ref":
        with pytest.raises(RelationshipValidationError, match="metric reference"):
            render_statement(StatementTemplate(**payload), make_bundle(), make_resolver())
    else:
        with pytest.raises(ValidationError):
            StatementTemplate(**payload)


def test_a2_free_statement_without_template_is_rejected():
    with pytest.raises(RelationshipValidationError, match="fixed statement template"):
        validate_opportunity(make_hypothesis().model_copy(update={"statement_template": None}), make_bundle(), make_resolver())


@pytest.mark.parametrize("entity", ["EVIDENCE", "OBSERVATION"])
def test_a2_legacy_analysis_status_accepted_notified_and_questioned(entity):
    proposal, bundle, resolver = comparison_status_fixture(entity_type=entity)
    resolver.records[BASELINE.id] = resolver.records[BASELINE.id].model_copy(update={"analysis_status": None})
    accepted = validate_opportunity(proposal, bundle, resolver)
    assert "LEGACY_ANALYSIS_STATUS_UNSET" in accepted.limitation_codes
    assert "LEGACY_ANALYSIS_STATUS_UNSET" in accepted.uncertainties
    assert any(BASELINE.id in question and "designer confirmation required" in question for question in accepted.designer_questions)


def reindex(bundle, resolver):
    bundle = bundle.model_copy(update={"bundle_ref": compute_site_analysis_bundle_ref(bundle)})
    resolver.records[bundle.bundle_ref.id] = record(bundle.bundle_ref, entity_type="ARTIFACT", scenario=bundle.scenario_ref)
    return bundle


def test_a2_observation_limitation_codes_propagate_automatically():
    bundle = make_bundle()
    resolver = make_resolver(bundle=bundle)
    obs = bundle.observations[0].model_copy(update={"limitation_codes": ("SOURCE_COVERAGE_PARTIAL",)})
    bundle = reindex(bundle.model_copy(update={"observations": (obs,)}), resolver)
    accepted = validate_opportunity(make_hypothesis(), bundle, resolver)
    assert "SOURCE_COVERAGE_PARTIAL" in accepted.uncertainties


@pytest.mark.parametrize("assertion", ["IMPROVEMENT", "COMPARISON"])
def test_a2_candidate_requires_exact_bundle_scenario(assertion):
    proposal, bundle, resolver = comparison_status_fixture(assertion)
    bundle = reindex(bundle.model_copy(update={"scenario_ref": SCENARIO}), resolver)
    with pytest.raises(RelationshipValidationError, match="candidate scenario"):
        validate_opportunity(proposal, bundle, resolver)
    resolver.records[CANDIDATE.id] = resolver.records[CANDIDATE.id].model_copy(update={"scenario_ref": SCENARIO})
    assert validate_opportunity(proposal, bundle, resolver).statement == proposal.statement


@pytest.mark.parametrize("entity", ["OTHER", "EVIDENCE", "DATASET_SNAPSHOT"])
def test_a2_observation_scope_rejects_nonspatial_entity(entity):
    bundle = make_bundle()
    resolver = make_resolver()
    invalid_scope = ref("nonspatial-scope", digest="8")
    resolver.records[invalid_scope.id] = record(invalid_scope, entity_type=entity)
    resolver.covers.add((SITE, invalid_scope))
    observation = bundle.observations[0].model_copy(update={"scope_ref": invalid_scope})
    bundle = reindex(bundle.model_copy(update={"observations": (observation,)}), resolver)
    with pytest.raises(RelationshipValidationError, match="not a spatial entity"):
        validate_analysis_bundle(bundle, resolver)


def test_a2_observation_scope_must_be_inside_study_area():
    bundle = make_bundle()
    resolver = make_resolver()
    outside = ref("outside", digest="8")
    resolver.records[outside.id] = record(outside, entity_type="ARTIFACT")
    resolver.covers.add((outside, SITE))
    obs = bundle.observations[0].model_copy(update={"scope_ref": outside})
    bundle = reindex(bundle.model_copy(update={"observations": (obs,)}), resolver)
    with pytest.raises(RelationshipValidationError, match="within bundle StudyArea"):
        validate_analysis_bundle(bundle, resolver)


@pytest.mark.parametrize("field", ["layer_refs", "coverage_refs"])
def test_a2_bundle_layer_coverage_must_cover_study_area(field):
    bundle = make_bundle()
    resolver = make_resolver()
    outside = ref("outside", digest="8")
    resolver.records[INPUT.id] = resolver.records[INPUT.id].model_copy(update={"scope_ref": outside})
    bundle = reindex(bundle.model_copy(update={field: (INPUT,)}), resolver)
    with pytest.raises(RelationshipValidationError, match="layer or coverage scope"):
        validate_analysis_bundle(bundle, resolver)


def test_a2_direct_template_rejects_uncited_metric_lineage():
    bundle = make_bundle()
    resolver = make_resolver()
    unrelated = ref("unrelated-source", digest="9")
    resolver.records[unrelated.id] = record(unrelated)
    proposal = make_hypothesis(evidence=(unrelated,))
    with pytest.raises(RelationshipValidationError, match="cited observation input lineage"):
        validate_opportunity(proposal, bundle, resolver)


def test_a2_incidental_partial_word_is_not_a_structured_limitation():
    proposal, bundle, resolver = comparison_status_fixture(kind="CONDITIONAL_HYPOTHESIS")
    proposal = proposal.model_copy(update={"uncertainties": ("An impartial review is pending.",)})
    resolver.records[BASELINE.id] = resolver.records[BASELINE.id].model_copy(update={"analysis_status": "PARTIAL"})
    accepted = validate_opportunity(proposal, bundle, resolver)
    assert "PARTIAL_ANALYSIS_EVIDENCE" in accepted.limitation_codes
    assert "PARTIAL_ANALYSIS_EVIDENCE" in accepted.uncertainties


def test_a2_model_cannot_inject_server_notifications():
    proposal = make_hypothesis().model_copy(update={
        "designer_questions": ("half the area ghp_synthetic",),
        "limitation_codes": ("MODEL_INVENTED", "PARTIAL_ANALYSIS_EVIDENCE")})
    accepted = validate_opportunity(proposal, make_bundle(), make_resolver())
    assert accepted.designer_questions == ()
    assert accepted.limitation_codes == ()


def test_a2_indexed_evidence_limitations_are_visible():
    bundle = make_bundle()
    resolver = make_resolver()
    resolver.records[INPUT.id] = resolver.records[INPUT.id].model_copy(update={"limitation_codes": ("SOURCE_INCOMPLETE",)})
    accepted = validate_opportunity(make_hypothesis(), bundle, resolver)
    assert "SOURCE_INCOMPLETE" in accepted.uncertainties
    assert "SOURCE_INCOMPLETE" in accepted.limitation_codes
