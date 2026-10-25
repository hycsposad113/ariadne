from __future__ import annotations

import pytest

from urban_design.generation.hashing import geometry_request_payload, semantic_digest, stage_artifact_digest
from urban_design.generation.workflow import GenerationMode, STOP_AFTER, needs_user_selection


@pytest.mark.parametrize(
    ("mode", "stops"),
    [
        (GenerationMode.SKELETON_FIRST, {"SKELETON", "MASSING"}),
        (GenerationMode.FULL_SCHEME, {"MASSING"}),
        (GenerationMode.STEPWISE, {"SKELETON", "BLOCK_PROGRAM", "MASSING"}),
    ],
)
def test_mode_requires_selection_only_at_its_declared_stop_points(mode, stops):
    assert STOP_AFTER[mode] == frozenset(stops)
    assert {stage for stage in {"SKELETON", "BLOCK_PROGRAM", "MASSING"} if needs_user_selection(mode, stage)} == stops


def test_identical_selections_and_seed_have_identical_g0_hashes_in_all_modes():
    request = {
        "input_refs": [
            {"id": "brief-fixture", "sha256": "sha256:" + "1" * 64, "kind": "BRIEF"},
            {"id": "locked-geometry", "sha256": "sha256:" + "2" * 64, "kind": "HUMAN_CONSTRAINT"},
        ],
        "input_hash": "sha256:" + "3" * 64,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [20, 0], [20, 10], [0, 10], [0, 0]]],
            "crs": "EPSG:28992",
        },
        "seed": 217,
        "strategy_id": "fixture-strategy",
        "algorithm_version": "fixture-v1",
        "method_parameters": {
            "selected_skeleton_ids": ["skeleton-a"],
            "selected_program": {"residential": 0.7, "community": 0.3},
            "locked_geometry_hashes": ["sha256:" + "2" * 64],
        },
    }
    context_hash = "sha256:" + "4" * 64
    artifact = {
        "artifact_id": "fixture-output",
        "context_hash": context_hash,
        "input_refs": request["input_refs"],
        "seed": request["seed"],
        "algorithm_version": request["algorithm_version"],
        "selected_skeleton_ids": request["method_parameters"]["selected_skeleton_ids"],
        "selected_program": request["method_parameters"]["selected_program"],
        "locked_geometry_hashes": request["method_parameters"]["locked_geometry_hashes"],
        "geometry_sha256": "sha256:" + "5" * 64,
        "created_at": "2026-09-30T12:00:00+00:00",
    }

    request_hashes = [
        semantic_digest(geometry_request_payload({**request, "mode": mode.value}))
        for mode in GenerationMode
    ]
    artifact_hashes = [
        stage_artifact_digest({**artifact, "mode": mode.value})
        for mode in GenerationMode
    ]

    assert request_hashes == [request_hashes[0]] * len(GenerationMode)
    assert artifact_hashes == [artifact_hashes[0]] * len(GenerationMode)
    assert "locked-geometry" in {reference["id"] for reference in request["input_refs"]}
    assert stage_artifact_digest(artifact) == artifact_hashes[0]

from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.generation.job_store import GenerationJobStore, JobStatus, IdempotencyConflict
from urban_design.generation.job_runner import GenerationJobRunner
from urban_design.generation.router import create_generation_workflow_router
from urban_design.generation.workflow import (
    GenerationWorkflow, ResolvedGeneration, WorkflowStart, StageSelection,
    register_skeleton_handler, PublicationReceipt,
)
from test_generation_skeleton import _context, _inputs, _catalog
from shapely.geometry import box


def _workflow(tmp_path, *, mode_readiness="FIXTURE_ONLY", later_handlers=True):
    context = _context()
    bundle = ResolvedGeneration(context, _inputs(box(0, 0, 120, 120)), tuple(s for s in _catalog().strategies if s.topology_family != "LINEAR_SPINE"), "revision-fixture", mode_readiness)
    resolver = lambda project: bundle if project == "fixture" else None
    store = GenerationJobStore(tmp_path / "jobs.sqlite3")
    runner = GenerationJobRunner(store, staging_root=tmp_path / "staging", output_root=tmp_path / "outputs")
    register_skeleton_handler(runner, resolver)
    executions = []
    def later(job, directory, token):
        # Explicit offline stage fixture, never a substitute for a G3/G4 adapter.
        from urban_design.generation.job_runner import PreparedOutput, write_prepared_manifest
        import hashlib, json
        executions.append(job.stage)
        data = json.dumps(job.request["parents"], sort_keys=True).encode()
        (directory / "fixture.json").write_bytes(data)
        output = PreparedOutput(f"fixture-{job.stage}", "fixture.json", "sha256:" + hashlib.sha256(data).hexdigest(), len(data))
        return write_prepared_manifest(directory, handler_version="fixture-v1", input_refs=job.input_refs, output_refs=[output])
    if later_handlers:
        for stage in ("BLOCK_PROGRAM", "MASSING"):
            runner.register_handler(stage, "fixture-v1", later)
    return GenerationWorkflow(store, runner, resolver), bundle, executions


def _select(workflow, receipt):
    return workflow.select("fixture", receipt.workflow_id, StageSelection(job_id=receipt.job_id,
        manifest_sha256=receipt.manifest_sha256, artifact_ids=(receipt.output_refs[0]["artifact_id"],)))


@pytest.mark.parametrize("mode", list(GenerationMode))
def test_durable_modes_restart_and_hash_bound_selection(tmp_path, mode):
    workflow, bundle, executions = _workflow(tmp_path)
    start = workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=mode))
    assert workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=mode)).workflow_id == start.workflow_id
    receipt = workflow.advance("fixture", start.workflow_id)
    expected = [stage for stage in ("SKELETON", "BLOCK_PROGRAM", "MASSING") if needs_user_selection(mode, stage)]
    for stage in expected:
        assert receipt.stage == stage
        assert receipt.status == "AWAITING_SELECTION"
        assert receipt.accepted is False
        assert receipt.publication_status == "FIXTURE_ONLY"
        # Reopen the store and orchestration, preserving jobs and selections.
        restarted, _, _ = _workflow(tmp_path)
        assert restarted.get("fixture", start.workflow_id) == receipt
        assert restarted.advance("fixture", start.workflow_id, reconcile=True) == receipt
        with pytest.raises(ValueError):
            restarted.select("fixture", start.workflow_id, StageSelection(job_id=receipt.job_id,
                             manifest_sha256="sha256:" + "0" * 64, artifact_ids=("invented",)))
        selected = _select(restarted, receipt)
        assert _select(restarted, receipt) == selected
        receipt = restarted.advance("fixture", start.workflow_id)
        workflow = restarted
    assert receipt.status == "COMPLETE_UNACCEPTED"
    assert receipt.accepted is False
    assert workflow.advance("fixture", start.workflow_id) == receipt
    assert workflow.store.get(receipt.job_id).request["parents"]
    with pytest.raises(IdempotencyConflict):
        workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=next(m for m in GenerationMode if m != mode)))


def test_missing_approval_and_client_flags_cannot_enable_workflow(tmp_path):
    workflow, _, _ = _workflow(tmp_path)
    app = FastAPI()
    app.include_router(create_generation_workflow_router(workflow))
    client = TestClient(app)
    root = "/api/projects/no-decisions/generation-workflows"
    assert client.get(root + "/readiness").json()["readiness"] == "BLOCKED"
    for mode in GenerationMode:
        response = client.post(root, json={"mode": mode.value, "idempotency_key": "click"})
        assert response.json()["status"] == "NOT_READY"
        assert response.json()["workflow_id"] is None
    assert client.post(root, json={"mode": "FULL_SCHEME", "idempotency_key": "click", "approved": True}).status_code == 422
    assert client.get("/api/projects/no-decisions/generation-workflows/missing").status_code == 404


def test_router_receipts_isolation_and_missing_later_handler(tmp_path):
    workflow, _, _ = _workflow(tmp_path, later_handlers=False)
    app = FastAPI()
    app.include_router(create_generation_workflow_router(workflow))
    client = TestClient(app)
    root = "/api/projects/fixture/generation-workflows"
    start = client.post(root, json={"mode": "FULL_SCHEME", "idempotency_key": "click"}).json()
    url = root + "/" + start["workflow_id"]
    receipt = client.post(url + "/advance").json()
    assert receipt["status"] == "BLOCKED" and receipt["stage"] == "BLOCK_PROGRAM"
    assert receipt["reason"] == "STAGE_HANDLER_NOT_READY"
    assert client.get(url.replace("fixture", "other")).status_code == 404
    assert client.post(root, json={"mode": "STEPWISE", "idempotency_key": "click"}).status_code == 409


def test_ready_job_does_not_claim_authority_and_wrong_publication_blocks(tmp_path):
    workflow, _, _ = _workflow(tmp_path, mode_readiness="APPROVED")
    start = workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=GenerationMode.FULL_SCHEME))
    receipt = workflow.advance("fixture", start.workflow_id)
    assert receipt.job_status == "READY" and receipt.publication_status == "NOT_PUBLISHED"
    assert receipt.accepted is False
    workflow.publication_lookup = lambda job: PublicationReceipt(job_id=job, manifest_sha256="wrong",
                                  authority_revision="fixture-authority", authority_record_sha256="sha256:" + "1" * 64)
    assert workflow.get("fixture", start.workflow_id).reason == "PUBLICATION_RECEIPT_MISMATCH"
    workflow.publication_lookup = lambda job: PublicationReceipt(job_id=job,
        manifest_sha256=workflow.store.get(job).output_manifest_sha256,
        authority_revision="fixture-authority", authority_record_sha256="sha256:" + "1" * 64)
    assert workflow.get("fixture", start.workflow_id).publication_status == "PUBLISHED"
    assert workflow.get("fixture", start.workflow_id).accepted is False


def test_context_drift_blocks_resume_without_dispatch(tmp_path):
    workflow, bundle, executions = _workflow(tmp_path)
    start = workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=GenerationMode.STEPWISE))
    workflow.resolve = lambda _: None
    assert workflow.advance("fixture", start.workflow_id).status == "NOT_READY"
    from dataclasses import replace
    workflow.resolve = lambda _: replace(bundle, revision="new-revision")
    assert workflow.advance("fixture", start.workflow_id).status == "STALE_FOR_CURRENT_CONTEXT"
    assert executions == []


def test_restart_reconciles_prepared_skeleton_without_redispatch(tmp_path, monkeypatch):
    workflow, _, _ = _workflow(tmp_path)
    start = workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=GenerationMode.STEPWISE))
    def disk_full(*args):
        raise OSError("injected publication failure")
    monkeypatch.setattr(workflow.runner, "_publish_directory", disk_full)
    prepared = workflow.advance("fixture", start.workflow_id)
    assert prepared.status == "PREPARED"
    assert prepared.publication_status == "FIXTURE_ONLY"
    import sqlite3
    with sqlite3.connect(workflow.store.database_path) as connection:
        connection.execute("UPDATE generation_jobs SET last_heartbeat=? WHERE job_id=?", ("2000-01-01T00:00:00+00:00", prepared.job_id))
    restarted, _, _ = _workflow(tmp_path)
    registration = restarted.runner._handlers["SKELETON"]
    from dataclasses import replace
    def forbidden_dispatch(*args):
        pytest.fail("recovery must never dispatch G2 again")
    restarted.runner._handlers["SKELETON"] = replace(registration, run_stage=forbidden_dispatch)
    recovered = restarted.advance("fixture", start.workflow_id, reconcile=True)
    assert recovered.status == "AWAITING_SELECTION"
    assert recovered.job_id == prepared.job_id
    assert recovered.manifest_sha256 == prepared.manifest_sha256
    assert recovered.publication_status == "FIXTURE_ONLY"
    assert [event.to_status for event in restarted.store.events(recovered.job_id)].count(JobStatus.RUNNING) == 1


def test_reconcile_never_creates_or_dispatches_new_stage(tmp_path):
    workflow, _, executions = _workflow(tmp_path)
    start = workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=GenerationMode.STEPWISE))
    assert workflow.advance("fixture", start.workflow_id, reconcile=True) == start
    assert workflow._load("fixture", start.workflow_id)[1] == {}
    assert executions == []


def test_corrupt_ready_artifact_blocks_selection_and_downstream(tmp_path):
    workflow, _, executions = _workflow(tmp_path)
    start = workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=GenerationMode.STEPWISE))
    receipt = workflow.advance("fixture", start.workflow_id)
    path = workflow.runner.output_root / receipt.job_id / receipt.output_refs[0]["relative_path"]
    path.write_bytes(b"injected corrupted fixture")
    blocked = workflow.advance("fixture", start.workflow_id)
    assert blocked.status == "BLOCKED"
    assert blocked.reason == "PUBLISHED_ARTIFACT_INTEGRITY_FAILED"
    with pytest.raises(ValueError):
        _select(workflow, receipt)
    assert executions == []


def test_concurrent_workflow_clicks_share_one_skeleton_job(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    workflow, _, _ = _workflow(tmp_path)
    second, _, _ = _workflow(tmp_path)
    start = workflow.start("fixture", WorkflowStart(idempotency_key="click", mode=GenerationMode.STEPWISE))
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda w: w.advance("fixture", start.workflow_id), (workflow, second)))
    assert receipts[0].job_id == receipts[1].job_id
    final = workflow.get("fixture", start.workflow_id)
    assert final.status == "AWAITING_SELECTION"
    assert [event.to_status for event in workflow.store.events(final.job_id)].count(JobStatus.RUNNING) == 1


def test_g2_failure_keeps_geometry_diagnostic_without_retry(tmp_path):
    workflow, bundle, _ = _workflow(tmp_path)
    from dataclasses import replace
    workflow.resolve = lambda _: replace(bundle, strategies=tuple(_catalog().strategies))
    start = workflow.start("fixture", WorkflowStart(idempotency_key="failure", mode=GenerationMode.STEPWISE))
    failed = workflow.advance("fixture", start.workflow_id)
    assert failed.status == "FAILED"
    import json
    diagnostic = json.loads((workflow.runner.staging_root / failed.job_id / "skeleton-failure.json").read_text())
    assert diagnostic["status"] == "BLOCKED"
    assert "entry-to-target" in diagnostic["reason"]
    assert diagnostic["input_refs"]
    assert workflow.advance("fixture", start.workflow_id) == failed
    assert len(failed.stage_receipts) == 1


def test_http_restore_by_request_key_and_stage_selection(tmp_path):
    workflow, _, _ = _workflow(tmp_path)
    app = FastAPI()
    app.include_router(create_generation_workflow_router(workflow))
    client = TestClient(app)
    root = "/api/projects/fixture/generation-workflows"
    start = client.post(root, json={"mode": "STEPWISE", "idempotency_key": "lost-response"}).json()
    assert client.get(root + "/requests/lost-response").json() == start
    url = root + "/" + start["workflow_id"]
    stage = client.post(url + "/advance").json()
    selection = {"job_id": stage["job_id"], "manifest_sha256": stage["manifest_sha256"],
                 "artifact_ids": [stage["output_refs"][0]["artifact_id"]]}
    selected = client.post(url + "/selection", json=selection)
    assert selected.status_code == 200
    assert selected.json()["stage"] == "BLOCK_PROGRAM"
    assert selected.json()["accepted"] is False
    assert selected.json()["stage_receipts"][0]["selected_artifact_ids"] == selection["artifact_ids"]
    assert client.post(url + "/selection", json={**selection, "artifact_ids": [stage["output_refs"][1]["artifact_id"]]}).status_code == 409
