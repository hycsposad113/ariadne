from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import threading

import pytest

from urban_design.generation.job_runner import (
    GenerationJobRunner,
    PreparedOutput,
    write_prepared_manifest,
)
from urban_design.generation.job_store import (
    GenerationJobStore,
    IdempotencyConflict,
    JobStatus,
)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _input_refs():
    return [{"id": "brief-fixture", "sha256": "sha256:" + "1" * 64, "kind": "BRIEF"}]


def _enqueue(store, *, key="click-1", request=None):
    return store.enqueue(
        project_id="fixture-project",
        idempotency_key=key,
        stage="MASSING",
        request=request or {"seed": 31, "selection": ["skeleton-a"]},
        input_refs=_input_refs(),
        expected_revision="revision-4",
    )


def _artifact_handler(executions, *, started=None):
    lock = threading.Lock()

    def run_stage(job, staging_dir, cancellation_token):
        with lock:
            executions.append(job.job_id)
        if started is not None:
            started.set()
        staging_dir.mkdir(parents=True, exist_ok=True)
        data = json.dumps(
            {"seed": job.request["seed"], "selection": job.request["selection"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        (staging_dir / "geometry.json").write_bytes(data)
        output = PreparedOutput(
            artifact_id="fixture-geometry-artifact",
            relative_path="geometry.json",
            sha256=_sha256(data),
            size_bytes=len(data),
        )
        return write_prepared_manifest(
            staging_dir,
            handler_version="fixture-handler-v1",
            input_refs=job.input_refs,
            output_refs=[output],
        )

    return run_stage


def _runner(store, tmp_path, handler, **kwargs):
    runner = GenerationJobRunner(
        store,
        staging_root=tmp_path / "staging",
        output_root=tmp_path / "published",
        **kwargs,
    )
    runner.register_handler("MASSING", "fixture-handler-v1", handler)
    return runner


def _make_stale_and_dead(store, job_id):
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE generation_jobs SET owner_pid = ?, last_heartbeat = ? WHERE job_id = ?",
            (99999999, "2000-01-01T00:00:00+00:00", job_id),
        )


def test_submit_is_idempotent_and_rejects_reusing_a_key_for_different_input(tmp_path):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")

    first, created = _enqueue(store)
    replay, replay_created = _enqueue(store)

    assert created is True
    assert replay_created is False
    assert replay.job_id == first.job_id
    assert replay.request_hash == first.request_hash
    assert [event.to_status for event in store.events(first.job_id)] == [JobStatus.PENDING]
    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE generation_job_events SET reason = 'rewritten' WHERE job_id = ?",
                (first.job_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM generation_job_events WHERE job_id = ?", (first.job_id,))
    with pytest.raises(IdempotencyConflict):
        _enqueue(store, request={"seed": 32, "selection": ["skeleton-a"]})
    assert store.count_jobs() == 1


def test_lost_response_replay_and_get_do_not_dispatch_the_handler_twice(tmp_path):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    accepted, _ = _enqueue(store)
    executions = []
    runner = _runner(store, tmp_path, _artifact_handler(executions))

    # The caller loses the first response and repeats the same request.
    replay, created = _enqueue(store)
    result = runner.run(replay.job_id)
    read_only_get = store.get(accepted.job_id)
    second_run = runner.run(replay.job_id)

    assert created is False
    assert replay.job_id == accepted.job_id
    assert result.status is JobStatus.READY
    assert read_only_get.status is JobStatus.READY
    assert second_run.status is JobStatus.READY
    assert executions == [accepted.job_id]
    assert (tmp_path / "published" / accepted.job_id / "geometry.json").is_file()


@pytest.mark.parametrize("observed_status", [JobStatus.RUNNING, JobStatus.PREPARED])
def test_two_workers_using_separate_connections_dispatch_one_execution(tmp_path, monkeypatch, observed_status):
    first_store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    job, _ = _enqueue(first_store)
    second_store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    executions = []
    barrier = threading.Barrier(2)
    observable = threading.Event()
    release = threading.Event()

    def synchronized_claim(original):
        def claim(*args, **kwargs):
            barrier.wait(timeout=5)
            won = original(*args, **kwargs)
            if not won:
                assert observable.wait(timeout=5)
            return won
        return claim

    handler = _artifact_handler(executions)

    def held_handler(*args):
        if observed_status is JobStatus.RUNNING:
            observable.set()
            assert release.wait(timeout=5)
        return handler(*args)

    def held_prepare(original):
        def prepare(*args, **kwargs):
            result = original(*args, **kwargs)
            if observed_status is JobStatus.PREPARED:
                observable.set()
                assert release.wait(timeout=5)
            return result
        return prepare

    for store in (first_store, second_store):
        monkeypatch.setattr(store, "claim", synchronized_claim(store.claim))
        monkeypatch.setattr(store, "record_prepared", held_prepare(store.record_prepared))
    runners = [_runner(store, tmp_path, held_handler) for store in (first_store, second_store)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(runner.run, job.job_id) for runner in runners]
        from concurrent.futures import wait, FIRST_COMPLETED
        try:
            completed, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert len(completed) == 1
            # The losing worker observes a legal intermediate state, deterministically.
            assert next(iter(completed)).result().status is observed_status
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    assert executions == [job.job_id]
    assert sorted(result.status.value for result in results) == sorted([observed_status.value, JobStatus.READY.value])
    assert [event.to_status for event in first_store.events(job.job_id)].count(JobStatus.RUNNING) == 1
    assert first_store.get(job.job_id).status is JobStatus.READY


def test_publish_disk_full_can_recover_prepared_output_without_rerunning(tmp_path, monkeypatch):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    job, _ = _enqueue(store)
    executions = []
    runner = _runner(store, tmp_path, _artifact_handler(executions))

    def disk_full(*_args, **_kwargs):
        raise OSError("ENOSPC")

    monkeypatch.setattr(runner, "_publish_directory", disk_full)
    prepared = runner.run(job.job_id)
    assert prepared.status is JobStatus.PREPARED
    assert prepared.error_code == "PUBLISH_FAILED"
    assert executions == [job.job_id]

    replay, created = _enqueue(store)
    assert created is False
    assert runner.run(replay.job_id).status is JobStatus.PREPARED
    assert executions == [job.job_id]

    monkeypatch.undo()
    monkeypatch.setattr(runner, "_publish_directory", disk_full)
    failed_recovery = runner.recover(
        job.job_id,
        now=datetime.now(timezone.utc) + timedelta(seconds=2),
        stale_after_seconds=0,
    )
    assert failed_recovery.status is JobStatus.PREPARED

    monkeypatch.undo()
    recovered = runner.recover(
        job.job_id,
        now=datetime.now(timezone.utc) + timedelta(seconds=4),
        stale_after_seconds=0,
    )
    assert recovered.status is JobStatus.READY
    assert executions == [job.job_id]
    assert (tmp_path / "published" / job.job_id / "geometry.json").is_file()


def test_database_failure_after_publish_reconciles_existing_artifact_without_rerun(tmp_path):
    database = tmp_path / "generation-jobs.sqlite3"
    store = GenerationJobStore(database)
    job, _ = _enqueue(store)
    executions = []
    runner = _runner(store, tmp_path, _artifact_handler(executions))
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TRIGGER fail_ready BEFORE UPDATE OF status ON generation_jobs
               WHEN NEW.status = 'READY' BEGIN SELECT RAISE(ABORT, 'simulated db full'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="simulated db full"):
        runner.run(job.job_id)
    assert store.get(job.job_id).status is JobStatus.PREPARED
    assert (tmp_path / "published" / job.job_id / "geometry.json").is_file()
    _make_stale_and_dead(store, job.job_id)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER fail_ready")

    recovered = _runner(store, tmp_path, _artifact_handler(executions)).recover(
        job.job_id,
        now=datetime.now(timezone.utc),
    )

    assert recovered.status is JobStatus.READY
    assert executions == [job.job_id]
    assert [event.to_status for event in store.events(job.job_id)].count(JobStatus.READY) == 1


def test_output_mutated_after_validation_is_blocked_before_atomic_publish(tmp_path, monkeypatch):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    job, _ = _enqueue(store)
    executions = []
    staging_dirs = []

    def record_staging(job_to_run, staging_dir, cancellation_token):
        staging_dirs.append(staging_dir)
        return _artifact_handler(executions)(job_to_run, staging_dir, cancellation_token)

    runner = _runner(store, tmp_path, record_staging)
    original_record_prepared = store.record_prepared

    def mutate_after_validation(*args, **kwargs):
        result = original_record_prepared(*args, **kwargs)
        (staging_dirs[0] / "geometry.json").write_bytes(b"changed-after-validation")
        return result

    monkeypatch.setattr(store, "record_prepared", mutate_after_validation)

    result = runner.run(job.job_id)

    assert result.status is JobStatus.BLOCKED_COLLISION
    assert not (tmp_path / "published" / job.job_id).exists()
    assert (staging_dirs[0] / "geometry.json").read_bytes() == b"changed-after-validation"
    assert executions == [job.job_id]


def test_same_job_output_path_with_a_different_hash_is_preserved_and_blocked(tmp_path):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    job, _ = _enqueue(store)
    existing_directory = tmp_path / "published" / job.job_id
    existing_directory.mkdir(parents=True)
    peer_bytes = b"already-published-peer-output"
    (existing_directory / "geometry.json").write_bytes(peer_bytes)
    write_prepared_manifest(
        existing_directory,
        handler_version="fixture-handler-v1",
        input_refs=_input_refs(),
        output_refs=[
            PreparedOutput(
                artifact_id="fixture-geometry-artifact",
                relative_path="geometry.json",
                sha256=_sha256(peer_bytes),
                size_bytes=len(peer_bytes),
            )
        ],
    )
    executions = []
    runner = _runner(store, tmp_path, _artifact_handler(executions))

    result = runner.run(job.job_id)

    assert result.status is JobStatus.BLOCKED_COLLISION
    assert (existing_directory / "geometry.json").read_bytes() == peer_bytes
    assert executions == [job.job_id]


def test_restart_recovers_manifest_written_before_prepared_db_commit(tmp_path, monkeypatch):
    database = tmp_path / "generation-jobs.sqlite3"
    store = GenerationJobStore(database)
    job, _ = _enqueue(store)
    executions = []
    runner = _runner(store, tmp_path, _artifact_handler(executions))

    def fail_prepared_commit(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated commit failure")

    monkeypatch.setattr(store, "record_prepared", fail_prepared_commit)
    with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
        runner.run(job.job_id)
    assert store.get(job.job_id).status is JobStatus.RUNNING
    still_owned = _runner(store, tmp_path, _artifact_handler(executions)).recover(
        job.job_id,
        now=datetime.now(timezone.utc) + timedelta(minutes=3),
        stale_after_seconds=0,
    )
    assert still_owned.status is JobStatus.RUNNING
    _make_stale_and_dead(store, job.job_id)
    monkeypatch.undo()

    recovered = _runner(store, tmp_path, _artifact_handler(executions)).recover(
        job.job_id,
        now=datetime.now(timezone.utc),
    )

    assert recovered.status is JobStatus.READY
    assert executions == [job.job_id]
    assert (tmp_path / "published" / job.job_id / "geometry.json").is_file()


def test_external_post_dispatch_loss_is_outcome_unknown_and_never_retried(tmp_path):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    job, _ = _enqueue(store)
    executions = []

    def lost_external_response(_job, _staging_dir, _cancellation_token):
        executions.append(job.job_id)
        raise TimeoutError("connection lost after dispatch")

    runner = GenerationJobRunner(
        store,
        staging_root=tmp_path / "staging",
        output_root=tmp_path / "published",
    )
    runner.register_handler("MASSING", "fixture-handler-v1", lost_external_response, external=True)

    assert runner.run(job.job_id).status is JobStatus.OUTCOME_UNKNOWN
    assert runner.run(job.job_id).status is JobStatus.OUTCOME_UNKNOWN
    replay, created = _enqueue(store)
    assert created is False
    assert replay.job_id == job.job_id
    assert executions == [job.job_id]


def test_cancelled_job_keeps_interrupted_staging_and_does_not_publish(tmp_path):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    job, _ = _enqueue(store)
    executions = []
    started = threading.Event()

    def cooperative_handler(current_job, staging_dir, cancellation_token):
        result = _artifact_handler(executions)(current_job, staging_dir, cancellation_token)
        started.set()
        while not cancellation_token.cancelled:
            threading.Event().wait(0.005)
        return result

    runner = _runner(store, tmp_path, cooperative_handler)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(runner.run, job.job_id)
        assert started.wait(timeout=3)
        runner.cancel(job.job_id)
        result = pending.result(timeout=3)

    assert result.status is JobStatus.CANCELLED
    assert not (tmp_path / "published" / job.job_id).exists()
    assert (tmp_path / "staging" / job.job_id / "interrupted.json").is_file()
    assert executions == [job.job_id]


def test_output_is_retained_but_marked_stale_when_expected_revision_is_not_current(tmp_path):
    store = GenerationJobStore(tmp_path / "generation-jobs.sqlite3")
    job, _ = _enqueue(store)
    executions = []
    runner = _runner(store, tmp_path, _artifact_handler(executions), revision_is_current=lambda _job: False)

    result = runner.run(job.job_id)

    assert result.status is JobStatus.STALE_FOR_CURRENT_CONTEXT
    assert (tmp_path / "published" / job.job_id / "geometry.json").is_file()
    assert executions == [job.job_id]


def test_job_store_refuses_the_authoritative_project_database_path(tmp_path):
    authority_path = tmp_path / ".urban_design_runtime" / "state.sqlite3"
    with pytest.raises(ValueError, match="disposable generation-job database"):
        GenerationJobStore(authority_path)
    assert not authority_path.exists()
