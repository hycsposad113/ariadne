from __future__ import annotations

import pytest

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from urban_design.week7.fixture_router import create_week7_router
from urban_design.week7.service import Week7Refusal
from tests.week7_support import seed_pair

pytest_plugins = ["tests.week7_support"]

WORKSPACE = "ws-w7"


def test_eight_operations_persist_without_human_decision_or_value_rewrite(service) -> None:
    decisions = service.human_decision_count()
    seed_pair(service)
    inspected = service.inspect(WORKSPACE, "card-b2-sun")
    assert inspected["forged_calculation"] is False
    assert inspected["result_count_unchanged"] is True
    challenged = service.challenge(WORKSPACE, target_revision="rev-b2", assumption="storey height is a project setting")
    assert challenged["target_revision"] == "rev-b2"
    modified = service.modify(WORKSPACE, parameter="storey_height_m", proposed_value=3.5)
    assert modified["grants_acceptance"] is False
    assert modified["human_status"] == "not_reviewed"
    assert modified["human_decision_count_unchanged"] is True
    rerun = service.rerun(WORKSPACE, kind="gfa_far", logical_request="far-again")
    assert rerun["overwrote_baseline"] is False
    assert rerun["baseline_value"] == 2.2
    assert rerun["created_new"] is True
    approved = service.rerun(WORKSPACE, kind="gfa_far", logical_request="far-approved", already_approved=True)
    assert approved["approval_prompt"] is False
    again = service.rerun(WORKSPACE, kind="gfa_far", logical_request="far-approved", already_approved=True)
    assert again["created_new"] is False
    assert again["approval_prompt"] is False
    assert again["run_id"] == approved["run_id"]
    same = service.compare(
        WORKSPACE,
        {"unit": "ratio", "extent_id": "site", "method": "far", "method_version": "1", "radius_family": "accessibility"},
        {"unit": "ratio", "extent_id": "site", "method": "far", "method_version": "1", "radius_family": "accessibility"},
    )
    assert same["comparable"] is True
    assert same["not_comparable"] == []
    mixed = service.compare(
        WORKSPACE,
        {"unit": "ratio", "extent_id": "site", "method": "far", "method_version": "1", "radius_family": "accessibility"},
        {"unit": "m", "extent_id": "other", "method": "syntax", "method_version": "2", "radius_family": "syntax"},
    )
    assert mixed["comparable"] is False
    assert set(mixed["not_comparable"]) == {"unit", "extent", "method", "radius_family"}
    forked = service.fork(WORKSPACE, branch_id="branch-b2")
    assert forked["parent_revision"] == "rev-b2"
    assert forked["lineage"] == ["B2@rev-b2", "branch-b2"]
    rejected = service.reject(WORKSPACE, candidate_id="candidate-b0", reason="does not meet the brief")
    assert rejected["payload"]["still_queryable"] is True
    reread = service.read_operation(rejected["operation_id"])
    assert reread["payload"]["reason"] == "does not meet the brief"
    overridden = service.override(WORKSPACE, kind="gfa_far", judgment="prefer the lower scheme", reason="open space")
    assert overridden["computed_value_unchanged"] is True
    assert overridden["before_value"] == overridden["after_value"] == 2.2
    assert overridden["invalid_evidence_status"] == "invalid"
    assert overridden["human_decision_count_unchanged"] is True
    assert service.human_decision_count() == decisions


def test_unapproved_rerun_reuses_the_existing_run(service) -> None:
    seed_pair(service)
    first = service.rerun(WORKSPACE, kind="gfa_far", logical_request="far-again", already_approved=False)
    second = service.rerun(WORKSPACE, kind="gfa_far", logical_request="far-again", already_approved=False)
    assert first["created_new"] is True
    assert second["created_new"] is False
    assert second["run_id"] == first["run_id"]
    assert second["baseline_value"] == 2.2
    assert second["run_value"] == 2.2
    assert second["overwrote_baseline"] is False
    assert second["approval_prompt"] is True
    with sqlite3.connect(service.database) as con:
        count = con.execute("SELECT COUNT(*) FROM week7_runs WHERE workspace_id = ?", (WORKSPACE,)).fetchone()[0]
    assert count == 1


def test_second_unapproved_rerun_post_returns_the_same_run(service) -> None:
    seed_pair(service)
    app = FastAPI()
    app.include_router(create_week7_router(service.store))
    client = TestClient(app)
    body = {
        "kind": "rerun",
        "payload": {"kind": "gfa_far", "logical_request": "far-again", "already_approved": False},
    }
    path = f"/api/v1/week7/workspaces/{WORKSPACE}/operations/rerun"
    first = client.post(path, json=body)
    second = client.post(path, json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["created_new"] is False
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["baseline_value"] == 2.2
    assert second.json()["overwrote_baseline"] is False
    with sqlite3.connect(service.database) as con:
        count = con.execute("SELECT COUNT(*) FROM week7_runs").fetchone()[0]
    assert count == 1


def test_operation_negatives(service) -> None:
    seed_pair(service)
    with pytest.raises(Week7Refusal):
        service.inspect(WORKSPACE, "missing-card")
    with pytest.raises(Week7Refusal):
        service.read_operation("missing-operation")
    with pytest.raises(Exception):
        service.fork(WORKSPACE, branch_id="branch-b2")
        service.fork(WORKSPACE, branch_id="branch-b2")
