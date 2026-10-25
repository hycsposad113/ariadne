"""Contract tests for the Milestone 1 domain models.

These tests intentionally exercise relationship and provenance checks in
addition to basic Pydantic shape validation.  The models are small enough to
be useful as fixtures for later state and ledger work.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from urban_design.models import (
    Artifact,
    Assumption,
    Claim,
    ContestEvent,
    ConstraintSet,
    DatasetSnapshot,
    DesignLedgerEvent,
    EvidenceCard,
    ExperimentPlan,
    HumanDecision,
    ParameterDefinition,
    MetricDefinition,
    ModelRun,
    Project,
    Scenario,
    Site,
    ToolExecution,
)


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def snapshot(*, project_id: str = "project-1", snapshot_id: str = "dataset-1") -> DatasetSnapshot:
    return DatasetSnapshot(
        id=snapshot_id,
        project_id=project_id,
        source="https://example.test/data",
        query="fixture=1",
        retrieved_at=NOW,
        publisher="Fixture publisher",
        license="CC-BY-4.0",
        version="2026-09-14",
        sha256="sha256:" + "a" * 64,
        raw_artifact_id="artifact-raw-1",
    )


def project() -> Project:
    return Project(id="project-1", name="Delft fixture", current_revision=3)


def site() -> Site:
    return Site(
        id="site-1",
        project_id="project-1",
        version="site-v1",
        boundary_artifact_id="artifact-boundary",
        boundary_sha256="sha256:" + "b" * 64,
        crs="EPSG:28992",
        units="m",
        dataset_snapshot_ids=["dataset-1"],
    )


def scenario() -> Scenario:
    return Scenario(
        id="scenario-1",
        project_id="project-1",
        site_id="site-1",
        site_version="site-v1",
        geometry_artifact_id="artifact-geometry",
        geometry_sha256="sha256:" + "c" * 64,
        generator="fixture-generator",
        generator_version="1.0.0",
        seed=7,
        constraint_set_id="constraints-1",
    )


def test_domain_records_round_trip_with_timezone_and_hashes() -> None:
    records = [project(), site(), snapshot(), scenario()]
    for record in records:
        restored = type(record).model_validate_json(record.model_dump_json())
        assert restored == record


def test_snapshot_requires_provenance_and_content_hash() -> None:
    with pytest.raises(ValidationError):
        DatasetSnapshot(
            id="dataset-1",
            project_id="project-1",
            source="fixture",
            query="fixture=1",
            retrieved_at=NOW.replace(tzinfo=None),
            publisher="Fixture publisher",
            license="CC-BY-4.0",
            version="2026-09-14",
            sha256="not-a-sha256",
            raw_artifact_id="artifact-raw-1",
        )


def test_core_provenance_records_require_hashes_and_contestable_links() -> None:
    artifact = Artifact(
        id="artifact-1",
        type="geometry",
        uri="artifacts/geometry.gpkg",
        sha256="sha256:" + "1" * 64,
        mime="application/geopackage+sqlite3",
        crs="EPSG:28992",
        producer="qgis-mcp",
        created_at=NOW,
        project_id="project-1",
    )
    assumption = Assumption(
        id="assumption-1",
        text="Public passage is available on the north edge.",
        scope="scenario-1",
        source="project-decision-1",
        status="challenged",
        project_id="project-1",
        resulting_rerun_ids=["run-2"],
    )
    claim = Claim(
        id="claim-1",
        type="comparison",
        text="Scenario B changes the measured access fraction.",
        evidence_ids=["evidence-1"],
        assumption_ids=[assumption.id],
        scope="scenario-1",
    )
    event = ContestEvent(
        id="contest-1",
        target_id=assumption.id,
        action="Challenge",
        user_reason="Test whether the passage premise changes the result.",
        resulting_event="event-2",
        actor="designer-1",
        timestamp=NOW,
        project_id="project-1",
        scenario_id="scenario-1",
    )
    model_run = ModelRun(
        id="model-run-1",
        provider="deterministic",
        model_id="fixture-model",
        prompt_hash="sha256:" + "2" * 64,
        schema_version="m1",
        response_hash="sha256:" + "3" * 64,
        adapter_version="deterministic-adapter-1",
        status="SUCCEEDED",
        project_id="project-1",
        created_at=NOW,
    )
    assert artifact.crs == "EPSG:28992"
    assert assumption.source_refs == ["project-decision-1"]
    assert claim.evidence_ids == ["evidence-1"]
    assert event.resulting_event_id == "event-2"
    assert model_run.response_hash == "sha256:" + "3" * 64

    with pytest.raises(ValidationError):
        Artifact(
            id="artifact-bad",
            type="geometry",
            uri="artifacts/bad.gpkg",
            sha256="not-a-hash",
            mime="application/octet-stream",
            producer="fixture",
            created_at=NOW,
        )

    with pytest.raises(ValidationError, match="raw_artifact_id"):
        DatasetSnapshot(
            id="dataset-2",
            project_id="project-1",
            source="fixture",
            query="fixture=1",
            retrieved_at=NOW,
            publisher="Fixture publisher",
            license="CC-BY-4.0",
            version="2026-09-14",
            sha256="sha256:" + "a" * 64,
        )


def test_contest_event_retains_required_text_and_timezone_validation():
    payload = {
        "id": "contest-validation",
        "target_id": "assumption-1",
        "action": "Challenge",
        "user_reason": "Challenge the source premise",
        "resulting_event_id": "event-3",
        "actor": "reviewer-1",
        "timestamp": NOW,
    }
    ContestEvent(**payload)
    with pytest.raises(ValidationError, match="identifier must be a non-empty string"):
        ContestEvent(**{**payload, "target_id": "   "})
    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        ContestEvent(**{**payload, "timestamp": datetime(2026, 9, 14, 12, 0)})


def test_project_compatibility_rejects_records_from_another_project() -> None:
    p = project()
    with pytest.raises(ValueError, match="project"):
        p.assert_compatible(snapshot(project_id="other-project"))

    with pytest.raises(ValueError, match="project"):
        p.assert_compatible(
            Scenario(
                id="scenario-other",
                project_id="other-project",
                site_id="site-1",
                site_version="site-v1",
                geometry_artifact_id="artifact-geometry",
                geometry_sha256="sha256:" + "c" * 64,
                generator="fixture-generator",
                generator_version="1.0.0",
                seed=7,
                constraint_set_id="constraints-1",
            )
        )


def test_evidence_card_rejects_wrong_scenario_dataset_and_unit() -> None:
    card = EvidenceCard(
        id="evidence-1",
        project_id="project-1",
        scenario_id="scenario-1",
        input_versions=["dataset-1", "site-v1"],
        claim={
            "id": "claim-1",
            "type": "observation",
            "statement": "The fixture result is bounded.",
        },
        dataset_refs=["dataset-1"],
        metric={"id": "metric-1", "name": "coverage", "unit": "%"},
        parameters=["parameter-1"],
        method={"id": "method-1", "description": "Fixture method"},
        tool="fixture-tool",
        tool_version="1.0.0",
        result={
            "artifact_refs": ["artifact-result"],
            "artifact_hashes": ["sha256:" + "a" * 64],
            "values": {"coverage": 42.0},
            "status": "computed",
            "project_id": "project-1",
            "scenario_id": "scenario-1",
            "units": {"coverage": "%"},
        },
        units={"coverage": "%"},
        confidence={
            "level": "medium",
            "basis": "fixture validator",
            "uncertainty": "fixture only",
            "assessed_by": "validator-1",
        },
        validation_status="validated",
        human_status="inspected",
        created_at=NOW,
    )
    metric_definition = MetricDefinition(
        id="metric-1",
        name="coverage",
        formula="coverage",
        unit="%",
        implementation_version="1.0.0",
        reference_fixture="coverage-fixture-v1",
    )
    tool_run = ToolExecution(
        id="run-1",
        project_id="project-1",
        scenario_id="scenario-1",
        tool="fixture-tool",
        tool_version="1.0.0",
        output_artifact_refs=["artifact-result"],
        output_artifact_hashes=["sha256:" + "a" * 64],
        status="SUCCEEDED",
        idempotency_key="run-1",
    )
    assert card.validate_relationships(
        project=project(),
        scenario=scenario(),
        datasets={"dataset-1": snapshot()},
        metric=metric_definition,
        tool_execution=tool_run,
    ) is card

    with pytest.raises(ValueError, match="scenario"):
        card.model_copy(update={"scenario_id": "scenario-other"}).validate_relationships(
            project=project(),
            scenario=scenario(),
            datasets={"dataset-1": snapshot()},
            metric=metric_definition,
            tool_execution=tool_run,
        )

    with pytest.raises(ValueError, match="dataset"):
        card.validate_relationships(
            project=project(),
            scenario=scenario(),
            datasets={"dataset-1": snapshot(project_id="other-project")},
            metric=metric_definition,
            tool_execution=tool_run,
        )

    with pytest.raises(ValueError, match="unit"):
        EvidenceCard(
            **{
                **card.model_dump(),
                "units": {"coverage": "m"},
                "result": {**card.result.model_dump(), "units": {"coverage": "m"}},
            }
        )


def test_evidence_card_rejects_unavailable_computed_result_and_nonfinite_value() -> None:
    base = dict(
        id="evidence-1",
        project_id="project-1",
        claim={"id": "claim-1", "type": "observation", "statement": "x"},
        metric={"id": "metric-1", "name": "coverage", "unit": "%"},
        method={"id": "method-1", "description": "Fixture method"},
        tool="fixture-tool",
        tool_version="1.0.0",
        confidence={"level": "unknown", "basis": "none", "uncertainty": "unknown", "assessed_by": "validator-1"},
        created_at=NOW,
    )
    with pytest.raises(ValidationError):
        EvidenceCard(
            **base,
            result={"artifact_refs": [], "values": {}, "status": "computed"},
        )
    with pytest.raises(ValidationError):
        EvidenceCard(
            **base,
            result={"artifact_refs": ["artifact-result"], "artifact_hashes": ["sha256:" + "a" * 64], "values": {"coverage": float("nan")}, "status": "computed"},
        )


def test_constraint_tool_ledger_and_human_records_preserve_statuses() -> None:
    constraints = ConstraintSet(
        id="constraints-1",
        project_id="project-1",
        version="constraints-v1",
        constraints=[
            {
                "id": "height-limit",
                "name": "Height limit",
                "value": 24,
                "unit": "m",
                "scope": "site",
                "enforcement": "HARD",
                "status": "effective",
            }
        ],
        status="effective",
    )
    execution = ToolExecution(
        id="tool-run-1",
        project_id="project-1",
        scenario_id="scenario-1",
        tool="fixture-tool",
        tool_version="1.0.0",
        input_refs=["dataset-1", "scenario-1"],
        parameters={"threshold": 800, "unit": "m"},
        output_artifact_refs=["artifact-result"],
        status="OUTCOME_UNKNOWN",
        idempotency_key="run-1",
    )
    decision = HumanDecision(
        id="decision-1",
        project_id="project-1",
        target_id="scenario-1",
        target_type="scenario",
        action="Override",
        status="overridden",
        actor="designer-1",
        reason="Use the declared project rule.",
        timestamp=NOW,
    )
    event = DesignLedgerEvent(
        id="event-1",
        project_id="project-1",
        timestamp=NOW,
        actor="designer-1",
        action="Override",
        target_id="scenario-1",
        prior_status="proposed",
        changed_refs=["decision-1"],
        resulting_refs=["scenario-1"],
        reason="Recorded override",
    )
    assert constraints.status.value == "effective"
    assert execution.status.value == "OUTCOME_UNKNOWN"
    assert decision.status.value == "overridden"
    assert event.action.value == "Override"

    with pytest.raises(ValidationError, match="output"):
        ToolExecution(
            id="tool-run-success-without-output",
            project_id="project-1",
            tool="fixture-tool",
            tool_version="1.0.0",
            status="SUCCEEDED",
            idempotency_key="run-success-without-output",
        )


def test_experiment_plan_requires_one_baseline_and_two_offsets() -> None:
    valid = ExperimentPlan(
        id="experiment-1",
        project_id="project-1",
        scenario_id="scenario-1",
        selected_building_id="building-1",
        independent_variable="translation_along_axis",
        axis="x",
        baseline={"offset": 0, "unit": "m"},
        offsets=[{"offset": -2, "unit": "m"}, {"offset": 2, "unit": "m"}],
        locked_conditions={"weather_hash": "sha256:" + "d" * 64, "sensor_grid_hash": "sha256:" + "e" * 64},
        method_tiers=["ladybug-screening", "honeybee-verification"],
        approval_status="approved",
        approved_by="designer-1",
        approved_at=NOW,
    )
    assert valid.offsets[0].offset == -2
    with pytest.raises(ValidationError):
        ExperimentPlan(**{**valid.model_dump(), "offsets": [{"offset": 2, "unit": "m"}]})
    with pytest.raises(ValidationError, match="baseline"):
        ExperimentPlan(**{**valid.model_dump(), "baseline": {"offset": 1, "unit": "m"}})
    with pytest.raises(ValidationError, match="feasible"):
        ExperimentPlan(**{**valid.model_dump(), "offsets": [{"offset": -2, "unit": "m", "feasible": False}, {"offset": 2, "unit": "m"}]})


def test_lineage_and_metric_references_are_semantically_checked() -> None:
    parent = scenario()
    child = Scenario(
        id="scenario-child",
        project_id="project-1",
        site_id="site-1",
        site_version="site-v1",
        parent_scenario_id=parent.id,
        geometry_artifact_id="artifact-child",
        geometry_sha256="sha256:" + "f" * 64,
        generator="fixture-generator",
        generator_version="1.0.0",
        seed=8,
        constraint_set_id="constraints-1",
    )
    assert child.validate_lineage(parent) is child
    with pytest.raises(ValueError, match="parent"):
        child.validate_lineage(None)

    metric = MetricDefinition(
        id="metric-1",
        name="coverage",
        formula="footprint_area / site_area",
        unit="%",
        implementation_version="1.0.0",
        reference_fixture="coverage-fixture-v1",
    )
    assert metric.unit == "%"


def test_parameter_requires_a_value_or_explicit_unavailable_marker() -> None:
    with pytest.raises(ValidationError, match="value"):
        ParameterDefinition(
            id="parameter-1",
            name="threshold",
            value=None,
            unit="m",
            context="metric",
            scale="spatial",
            source_type="project_decision",
        )


def test_stale_tool_execution_cannot_back_a_validated_evidence_card() -> None:
    card = EvidenceCard(
        id="evidence-1",
        project_id="project-1",
        scenario_id="scenario-1",
        claim={"id": "claim-1", "type": "observation", "statement": "x"},
        dataset_refs=["dataset-1"],
        metric={"id": "metric-1", "name": "coverage", "unit": "%"},
        method={"id": "method-1", "description": "Fixture method"},
        tool="fixture-tool",
        tool_version="1.0.0",
        result={
            "artifact_refs": ["artifact-result"],
            "artifact_hashes": ["sha256:" + "a" * 64],
            "values": {"coverage": 42.0},
            "status": "computed",
            "project_id": "project-1",
            "scenario_id": "scenario-1",
            "units": {"coverage": "%"},
        },
        units={"coverage": "%"},
        confidence={"level": "medium", "basis": "fixture", "uncertainty": "fixture", "assessed_by": "validator"},
        validation_status="validated",
        created_at=NOW,
    )
    stale_run = ToolExecution(
        id="run-stale",
        project_id="project-1",
        scenario_id="scenario-1",
        tool="fixture-tool",
        tool_version="1.0.0",
        status="STALE",
        idempotency_key="run-stale",
    )
    metric_definition = MetricDefinition(
        id="metric-1",
        name="coverage",
        formula="coverage",
        unit="%",
        implementation_version="1.0.0",
        reference_fixture="coverage-fixture-v1",
    )
    with pytest.raises(ValueError, match="stale"):
        card.validate_relationships(
            project=project(),
            scenario=scenario(),
            datasets={"dataset-1": snapshot()},
            metric=metric_definition,
            tool_execution=stale_run,
        )


def test_validated_evidence_rejects_mismatched_tool_artifacts() -> None:
    card = EvidenceCard(
        id="evidence-artifact-mismatch",
        project_id="project-1",
        scenario_id="scenario-1",
        claim={"id": "claim-1", "type": "observation", "statement": "x"},
        metric={"id": "metric-1", "name": "coverage", "unit": "%"},
        method={"id": "method-1", "description": "Fixture method"},
        tool="fixture-tool",
        tool_version="1.0.0",
        result={
            "artifact_refs": ["artifact-result"],
            "artifact_hashes": ["sha256:" + "a" * 64],
            "values": {"coverage": 42.0},
            "status": "computed",
            "project_id": "project-1",
            "scenario_id": "scenario-1",
            "units": {"coverage": "%"},
        },
        units={"coverage": "%"},
        confidence={"level": "medium", "basis": "fixture", "uncertainty": "fixture", "assessed_by": "validator"},
        validation_status="validated",
        created_at=NOW,
    )
    metric = MetricDefinition(
        id="metric-1", name="coverage", formula="coverage", unit="%", implementation_version="1.0.0", reference_fixture="coverage-fixture-v1"
    )
    run = ToolExecution(
        id="run-mismatch", project_id="project-1", scenario_id="scenario-1", tool="fixture-tool", tool_version="1.0.0",
        output_artifact_refs=["other-artifact"], output_artifact_hashes=["sha256:" + "b" * 64], status="SUCCEEDED", idempotency_key="run-mismatch"
    )
    with pytest.raises(ValueError, match="artifact"):
        card.validate_relationships(project=project(), scenario=scenario(), datasets={"dataset-1": snapshot()}, metric=metric, tool_execution=run)
