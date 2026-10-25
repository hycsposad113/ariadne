"""Tests for the provider-neutral deterministic reasoning adapter."""

import pytest

from urban_design.reasoning import (
    AdapterOutputError,
    DeterministicReasoningAdapter,
    PlanRequest,
)


def test_deterministic_adapter_returns_repeatable_structured_plan() -> None:
    adapter = DeterministicReasoningAdapter()
    request = PlanRequest(
        project_id="project-1",
        objective="Inspect validated evidence for the current scenario.",
        permitted_tools=["evidence_inspector", "deterministic_verifier"],
        context={"scenario_id": "scenario-1", "revision": 3},
    )
    first = adapter.plan_workflow(request)
    second = adapter.plan_workflow(request)

    assert first == second
    assert first.request_hash.startswith("sha256:")
    assert first.steps
    assert first.steps[0].tool == "deterministic_verifier"
    assert first.model_id == "deterministic-fixture"


def test_adapter_rejects_malformed_or_unknown_tool_output_without_guessing() -> None:
    adapter = DeterministicReasoningAdapter()
    with pytest.raises(AdapterOutputError):
        adapter.decode_plan({"project_id": "project-1", "steps": "inspect"})

    valid = adapter.plan_workflow(
        PlanRequest(project_id="project-1", objective="Inspect evidence", permitted_tools=["evidence_inspector"])
    ).model_dump()
    valid["steps"][0]["tool"] = "unregistered-tool"
    with pytest.raises(AdapterOutputError, match="tool"):
        adapter.decode_plan(valid)


def test_adapter_rejects_unknown_fields_and_malformed_request() -> None:
    adapter = DeterministicReasoningAdapter()
    with pytest.raises(AdapterOutputError, match="unknown"):
        adapter.decode_plan({"plan_id": "p", "project_id": "project-1", "steps": [], "unexpected": True})

    with pytest.raises(ValueError):
        PlanRequest(project_id="project-1", objective="", permitted_tools=["evidence_inspector"])


def test_adapter_rejects_a_plan_step_scoped_to_another_project() -> None:
    adapter = DeterministicReasoningAdapter()
    payload = adapter.plan_workflow(
        PlanRequest(project_id="project-1", objective="Inspect evidence")
    ).model_dump()
    payload["steps"][0]["parameters"]["project_id"] = "project-2"
    with pytest.raises(AdapterOutputError, match="project"):
        adapter.decode_plan(payload)


def test_adapter_rejects_a_non_hex_request_hash() -> None:
    adapter = DeterministicReasoningAdapter()
    payload = adapter.plan_workflow(PlanRequest(project_id="project-1", objective="Inspect evidence")).model_dump()
    payload["request_hash"] = "sha256:" + "z" * 64
    with pytest.raises(AdapterOutputError, match="malformed"):
        adapter.decode_plan(payload)
