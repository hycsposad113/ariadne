from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from urban_design.site_intelligence.contracts import (
    AnalysisExtent,
    ClaimBinding,
    FrozenRef,
    Observation,
    Opportunity,
    SiteAnalysisBundle,
)


def _ref(identifier="synthetic-scope", digest="a"):
    return {"id": identifier, "revision": 1, "sha256": "sha256:" + digest * 64}


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_blocked_observation_rejects_numeric_value(value):
    ref = {"id": "synthetic-scope", "revision": 1, "sha256": "sha256:" + "a" * 64}
    with pytest.raises(ValidationError):
        Observation(
            metric_key="synthetic.distance",
            status="BLOCKED",
            value=value,
            unit="m",
            method_version="fixture-v1",
            scope_ref=ref,
            input_refs=(ref,),
            limitation_codes=("MISSING_INPUT",),
        )


def test_available_zero_is_a_valid_observation():
    observation = Observation(
        metric_key="synthetic.count",
        status="AVAILABLE",
        value=0.0,
        unit="count",
        method_version="fixture-v1",
        scope_ref=_ref(),
        input_refs=(_ref(),),
        limitation_codes=(),
    )
    assert observation.value == 0.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_observation_rejects_nonfinite_values(value):
    with pytest.raises(ValidationError):
        Observation(
            metric_key="synthetic.count",
            status="AVAILABLE",
            value=value,
            unit="count",
            method_version="fixture-v1",
            scope_ref=_ref(),
            input_refs=(_ref(),),
        )


def test_partial_observation_requires_limitations():
    with pytest.raises(ValidationError, match="limitations"):
        Observation(
            metric_key="synthetic.coverage",
            status="PARTIAL",
            value=0.25,
            unit="ratio",
            method_version="fixture-v1",
            scope_ref=_ref(),
            input_refs=(_ref(),),
        )


def test_not_run_observation_keeps_value_null():
    with pytest.raises(ValidationError, match="cannot carry a value"):
        Observation(
            metric_key="synthetic.height",
            status="NOT_RUN",
            value=0.0,
            unit="m",
            method_version="fixture-v1",
            scope_ref=_ref(),
        )


@pytest.mark.parametrize("revision", [True, "1", 1.0])
def test_frozen_reference_rejects_coerced_integer_revision(revision):
    with pytest.raises(ValidationError):
        FrozenRef(id="synthetic", revision=revision, sha256="sha256:" + "a" * 64)


@pytest.mark.parametrize("value", [True, "1.0"])
def test_observation_rejects_coerced_numeric_value(value):
    with pytest.raises(ValidationError):
        Observation(
            metric_key="synthetic.count",
            status="AVAILABLE",
            value=value,
            unit="count",
            method_version="fixture-v1",
            scope_ref=_ref(),
            input_refs=(_ref(),),
        )


def test_blocked_and_not_run_observations_require_reason_codes():
    for status in ("BLOCKED", "NOT_RUN"):
        with pytest.raises(ValidationError, match="reason code"):
            Observation(
                metric_key="synthetic.count",
                status=status,
                value=None,
                unit="count",
                method_version="fixture-v1",
                scope_ref=_ref(),
            )


def test_category_count_rejects_bool_and_string_integer_coercion():
    from urban_design.site_intelligence.contracts import CategoryCount

    for count in (True, "1"):
        with pytest.raises(ValidationError):
            CategoryCount(category="residential", count=count)


def test_available_observation_requires_input_refs():
    with pytest.raises(ValidationError, match="input references"):
        Observation(
            metric_key="synthetic.count",
            status="AVAILABLE",
            value=0.0,
            unit="count",
            method_version="fixture-v1",
            scope_ref=_ref(),
        )


def test_bundle_keeps_analysis_extent_separate_from_study_area():
    study_area = FrozenRef.model_validate(_ref("study-area"))
    workspace = FrozenRef.model_validate(_ref("workspace", "b"))
    extent = AnalysisExtent(
        id="syntax-pedestrian-800m",
        study_area_ref=study_area,
        display_radius_m=800.0,
        calculation_radius_m=800.0,
        source_extraction_buffer_m=1500.0,
        network_mode="pedestrian",
    )
    bundle = SiteAnalysisBundle(
        bundle_ref=FrozenRef.model_validate(_ref("bundle", "c")),
        study_area_ref=study_area,
        workspace_ref=workspace,
        observations=(),
        analysis_extents=(extent,),
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        tool_versions={"pst": "fixture-3.3.1"},
    )
    assert bundle.study_area_ref == study_area
    assert bundle.analysis_extents[0].study_area_ref == study_area
    assert bundle.analysis_extents[0].display_radius_m != bundle.analysis_extents[0].source_extraction_buffer_m


def test_bundle_rejects_nonfinite_method_parameters():
    with pytest.raises(ValidationError, match="finite numbers"):
        SiteAnalysisBundle(
            bundle_ref=FrozenRef.model_validate(_ref("bundle", "c")),
            study_area_ref=FrozenRef.model_validate(_ref("study-area")),
            workspace_ref=FrozenRef.model_validate(_ref("workspace", "b")),
            observations=(),
            created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
            tool_versions={"fixture": "1"},
            method_parameters={"radius_m": float("nan")},
        )


def test_observed_problem_contract_requires_a_comparative_baseline():
    binding = ClaimBinding(
        metric_key="synthetic.coverage",
        scope_ref=_ref(),
        input_refs=(_ref("input", "b"),),
        method_version="fixture-v1",
        unit="ratio",
    )
    with pytest.raises(ValidationError, match="baseline"):
        Opportunity(
            id="problem-1",
            origin="AI_SUGGESTED",
            statement="A measured problem",
            kind="OBSERVED_PROBLEM",
            evidence_refs=(_ref("input", "b"),),
            scope_ref=_ref(),
            claim_bindings=(binding,),
        )
