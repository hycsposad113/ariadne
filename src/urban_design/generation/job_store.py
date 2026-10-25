"""Durable, isolated bookkeeping for staged generation jobs.

This store owns a dedicated disposable SQLite file. It deliberately does not
open or migrate the project's authoritative state database.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping, Sequence
import uuid

from urban_design.generation.contracts import FrozenRef


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PREPARED = "PREPARED"
    READY = "READY"
    STALE_FOR_CURRENT_CONTEXT = "STALE_FOR_CURRENT_CONTEXT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    BLOCKED_COLLISION = "BLOCKED_COLLISION"


class IdempotencyConflict(ValueError):
    """Raised when a project-scoped key is reused with a different request."""


@dataclass(frozen=True)
class GenerationJob:
    job_id: str
    project_id: str
    idempotency_key: str
    request_hash: str
    request: Mapping[str, Any]
    input_refs: tuple[Mapping[str, str], ...]
    stage: str
    expected_revision: str | None
    status: JobStatus
    owner_token: str | None
    owner_pid: int | None
    last_heartbeat: str | None
    output_manifest_ref: str | None
    output_manifest_sha256: str | None
    output_refs: tuple[Mapping[str, Any], ...]
    error_code: str | None
    cancellation_requested: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class JobEvent:
    event_id: str
    job_id: str
    seq: int
    time: str
    from_status: JobStatus | None
    to_status: JobStatus
    reason: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


class GenerationJobStore:
    """SQLite job/event store for one disposable generation-job database."""

    def __init__(self, database_path: str | Path):
        path = Path(database_path).expanduser().resolve()
        if path.name == "state.sqlite3" and path.parent.name == ".urban_design_runtime":
            raise ValueError("generation jobs require a disposable generation-job database")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = path
        connection = sqlite3.connect(self.database_path, timeout=5, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS generation_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    input_refs_json TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    expected_revision TEXT,
                    status TEXT NOT NULL,
                    owner_token TEXT,
                    owner_pid INTEGER,
                    last_heartbeat TEXT,
                    output_manifest_ref TEXT,
                    output_manifest_sha256 TEXT,
                    output_refs_json TEXT NOT NULL DEFAULT '[]',
                    error_code TEXT,
                    cancellation_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS generation_job_events (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES generation_jobs(job_id),
                    seq INTEGER NOT NULL,
                    time TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    UNIQUE(job_id, seq)
                );

                CREATE TRIGGER IF NOT EXISTS generation_job_events_no_update
                BEFORE UPDATE ON generation_job_events
                BEGIN SELECT RAISE(ABORT, 'generation job events are append-only'); END;

                CREATE TRIGGER IF NOT EXISTS generation_job_events_no_delete
                BEFORE DELETE ON generation_job_events
                BEGIN SELECT RAISE(ABORT, 'generation job events are append-only'); END;
                """
            )
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _job(row: sqlite3.Row) -> GenerationJob:
        return GenerationJob(
            job_id=row["job_id"],
            project_id=row["project_id"],
            idempotency_key=row["idempotency_key"],
            request_hash=row["request_hash"],
            request=json.loads(row["request_json"]),
            input_refs=tuple(json.loads(row["input_refs_json"])),
            stage=row["stage"],
            expected_revision=row["expected_revision"],
            status=JobStatus(row["status"]),
            owner_token=row["owner_token"],
            owner_pid=row["owner_pid"],
            last_heartbeat=row["last_heartbeat"],
            output_manifest_ref=row["output_manifest_ref"],
            output_manifest_sha256=row["output_manifest_sha256"],
            output_refs=tuple(json.loads(row["output_refs_json"])),
            error_code=row["error_code"],
            cancellation_requested=bool(row["cancellation_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        job_id: str,
        from_status: JobStatus | None,
        to_status: JobStatus,
        reason: str,
        timestamp: str,
    ) -> None:
        seq = connection.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM generation_job_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO generation_job_events
               (event_id, job_id, seq, time, from_status, to_status, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex,
                job_id,
                seq,
                timestamp,
                from_status.value if from_status else None,
                to_status.value,
                reason,
            ),
        )

    def enqueue(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        stage: str,
        request: Mapping[str, Any],
        input_refs: Sequence[Mapping[str, Any]],
        expected_revision: str | None = None,
    ) -> tuple[GenerationJob, bool]:
        project_id = _text(project_id, "project_id")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        stage = _text(stage, "stage")
        if not isinstance(request, Mapping):
            raise TypeError("request must be a JSON object")
        if not isinstance(input_refs, (list, tuple)) or not input_refs:
            raise ValueError("input_refs must contain at least one frozen reference")
        references = [FrozenRef.model_validate(ref).model_dump(mode="json") for ref in input_refs]
        request_value = json.loads(_json(dict(request)))
        revision = _text(expected_revision, "expected_revision") if expected_revision is not None else None
        payload = {
            "stage": stage,
            "request": request_value,
            "input_refs": references,
            "expected_revision": revision,
        }
        rendered = _json(payload)
        request_hash = _hash(rendered)
        timestamp = _now()

        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM generation_jobs WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict("idempotency key was already used for a different request")
                return self._job(existing), False

            job_id = uuid.uuid4().hex
            connection.execute(
                """INSERT INTO generation_jobs
                   (job_id, project_id, idempotency_key, request_hash, request_json,
                    input_refs_json, stage, expected_revision, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    project_id,
                    idempotency_key,
                    request_hash,
                    _json(request_value),
                    _json(references),
                    stage,
                    revision,
                    JobStatus.PENDING.value,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(connection, job_id, None, JobStatus.PENDING, "REQUEST_ACCEPTED", timestamp)
            row = connection.execute("SELECT * FROM generation_jobs WHERE job_id = ?", (job_id,)).fetchone()
            assert row is not None
            return self._job(row), True

    def get(self, job_id: str) -> GenerationJob:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM generation_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return self._job(row)
        finally:
            connection.close()

    def events(self, job_id: str) -> tuple[JobEvent, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM generation_job_events WHERE job_id = ? ORDER BY seq", (job_id,)
            ).fetchall()
            return tuple(
                JobEvent(
                    event_id=row["event_id"],
                    job_id=row["job_id"],
                    seq=row["seq"],
                    time=row["time"],
                    from_status=JobStatus(row["from_status"]) if row["from_status"] else None,
                    to_status=JobStatus(row["to_status"]),
                    reason=row["reason"],
                )
                for row in rows
            )
        finally:
            connection.close()

    def count_jobs(self) -> int:
        connection = self._connect()
        try:
            return int(connection.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0])
        finally:
            connection.close()

    def claim(self, job_id: str, owner_token: str, owner_pid: int, *, now: str | None = None) -> bool:
        owner_token = _text(owner_token, "owner_token")
        timestamp = now or _now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE generation_jobs
                   SET status = ?, owner_token = ?, owner_pid = ?, last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND status = ? AND owner_token IS NULL""",
                (
                    JobStatus.RUNNING.value,
                    owner_token,
                    owner_pid,
                    timestamp,
                    timestamp,
                    job_id,
                    JobStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(
                connection,
                job_id,
                JobStatus.PENDING,
                JobStatus.RUNNING,
                "WORKER_CLAIMED",
                timestamp,
            )
            return True

    def heartbeat(self, job_id: str, owner_token: str, *, now: str | None = None) -> bool:
        timestamp = now or _now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE generation_jobs SET last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (timestamp, timestamp, job_id, owner_token, JobStatus.RUNNING.value),
            )
            return cursor.rowcount == 1

    def record_prepared(
        self,
        job_id: str,
        owner_token: str,
        *,
        manifest_ref: str,
        manifest_sha256: str,
        output_refs: Sequence[Mapping[str, Any]],
        now: str | None = None,
    ) -> bool:
        timestamp = now or _now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE generation_jobs
                   SET status = ?, output_manifest_ref = ?, output_manifest_sha256 = ?,
                       output_refs_json = ?, error_code = NULL, last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (
                    JobStatus.PREPARED.value,
                    manifest_ref,
                    manifest_sha256,
                    _json(list(output_refs)),
                    timestamp,
                    timestamp,
                    job_id,
                    owner_token,
                    JobStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(
                connection,
                job_id,
                JobStatus.RUNNING,
                JobStatus.PREPARED,
                "OUTPUTS_PREPARED",
                timestamp,
            )
            return True

    def note_publish_failed(self, job_id: str, owner_token: str, *, now: str | None = None) -> bool:
        timestamp = now or _now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE generation_jobs
                   SET error_code = 'PUBLISH_FAILED', owner_pid = NULL,
                       last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (timestamp, timestamp, job_id, owner_token, JobStatus.PREPARED.value),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(
                connection,
                job_id,
                JobStatus.PREPARED,
                JobStatus.PREPARED,
                "PUBLISH_FAILED",
                timestamp,
            )
            return True

    def complete(
        self,
        job_id: str,
        owner_token: str,
        *,
        stale: bool = False,
        now: str | None = None,
    ) -> bool:
        timestamp = now or _now()
        final_status = JobStatus.STALE_FOR_CURRENT_CONTEXT if stale else JobStatus.READY
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE generation_jobs
                   SET status = ?, error_code = NULL, owner_pid = NULL,
                       last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (
                    final_status.value,
                    timestamp,
                    timestamp,
                    job_id,
                    owner_token,
                    JobStatus.PREPARED.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(
                connection,
                job_id,
                JobStatus.PREPARED,
                final_status,
                "OUTPUT_PUBLISHED_STALE" if stale else "OUTPUT_PUBLISHED",
                timestamp,
            )
            return True

    def fail(self, job_id: str, owner_token: str, error_code: str, *, unknown: bool = False) -> bool:
        timestamp = _now()
        final_status = JobStatus.OUTCOME_UNKNOWN if unknown else JobStatus.FAILED
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status FROM generation_jobs WHERE job_id = ? AND owner_token = ?",
                (job_id, owner_token),
            ).fetchone()
            if row is None or JobStatus(row["status"]) is not JobStatus.RUNNING:
                return False
            cursor = connection.execute(
                """UPDATE generation_jobs SET status = ?, error_code = ?, owner_pid = NULL,
                   last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (
                    final_status.value,
                    _text(error_code, "error_code"),
                    timestamp,
                    timestamp,
                    job_id,
                    owner_token,
                    JobStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(
                connection,
                job_id,
                JobStatus.RUNNING,
                final_status,
                "DISPATCH_OUTCOME_UNKNOWN" if unknown else "HANDLER_FAILED",
                timestamp,
            )
            return True

    def cancel_requested(self, job_id: str) -> bool:
        return self.get(job_id).cancellation_requested

    def request_cancel(self, job_id: str) -> GenerationJob:
        timestamp = _now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status, cancellation_requested FROM generation_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            status = JobStatus(row["status"])
            if status is JobStatus.PENDING:
                connection.execute(
                    "UPDATE generation_jobs SET status = ?, cancellation_requested = 1, updated_at = ? WHERE job_id = ?",
                    (JobStatus.CANCELLED.value, timestamp, job_id),
                )
                self._append_event(
                    connection,
                    job_id,
                    JobStatus.PENDING,
                    JobStatus.CANCELLED,
                    "CANCELLED_BEFORE_DISPATCH",
                    timestamp,
                )
            elif status is JobStatus.RUNNING:
                if not bool(row["cancellation_requested"]):
                    connection.execute(
                        "UPDATE generation_jobs SET cancellation_requested = 1, updated_at = ? WHERE job_id = ?",
                        (timestamp, job_id),
                    )
                    self._append_event(
                        connection,
                        job_id,
                        JobStatus.RUNNING,
                        JobStatus.RUNNING,
                        "CANCELLATION_REQUESTED",
                        timestamp,
                    )
            row = connection.execute("SELECT * FROM generation_jobs WHERE job_id = ?", (job_id,)).fetchone()
            assert row is not None
            return self._job(row)

    def finish_cancelled(self, job_id: str, owner_token: str) -> bool:
        timestamp = _now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE generation_jobs SET status = ?, owner_pid = NULL,
                   last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ? AND cancellation_requested = 1""",
                (
                    JobStatus.CANCELLED.value,
                    timestamp,
                    timestamp,
                    job_id,
                    owner_token,
                    JobStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(
                connection,
                job_id,
                JobStatus.RUNNING,
                JobStatus.CANCELLED,
                "CANCELLED_BY_REQUEST",
                timestamp,
            )
            return True

    def mark_interrupted(self, job_id: str, owner_token: str) -> bool:
        timestamp = _now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status FROM generation_jobs WHERE job_id = ? AND owner_token = ?",
                (job_id, owner_token),
            ).fetchone()
            if row is None or JobStatus(row["status"]) not in {JobStatus.RUNNING, JobStatus.PREPARED}:
                return False
            old_status = JobStatus(row["status"])
            cursor = connection.execute(
                """UPDATE generation_jobs SET status = ?, error_code = 'RECOVERY_REQUIRED',
                   owner_pid = NULL, last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (JobStatus.INTERRUPTED.value, timestamp, timestamp, job_id, owner_token, old_status.value),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(connection, job_id, old_status, JobStatus.INTERRUPTED, "INCOMPLETE_STAGING", timestamp)
            return True

    def mark_collision(self, job_id: str, owner_token: str) -> bool:
        timestamp = _now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status FROM generation_jobs WHERE job_id = ? AND owner_token = ?",
                (job_id, owner_token),
            ).fetchone()
            if row is None or JobStatus(row["status"]) not in {JobStatus.RUNNING, JobStatus.PREPARED}:
                return False
            old_status = JobStatus(row["status"])
            cursor = connection.execute(
                """UPDATE generation_jobs SET status = ?, error_code = 'BLOCKED_COLLISION',
                   owner_pid = NULL, last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (JobStatus.BLOCKED_COLLISION.value, timestamp, timestamp, job_id, owner_token, old_status.value),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(connection, job_id, old_status, JobStatus.BLOCKED_COLLISION, "OUTPUT_COLLISION", timestamp)
            return True

    def claim_recovery(
        self,
        job_id: str,
        expected_owner_token: str,
        new_owner_token: str,
        owner_pid: int,
        *,
        stale_before: str,
        pid_is_alive,
        now: str | None = None,
    ) -> bool:
        timestamp = now or _now()
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM generation_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None or row["owner_token"] != expected_owner_token:
                return False
            old_status = JobStatus(row["status"])
            if old_status not in {JobStatus.RUNNING, JobStatus.PREPARED}:
                return False
            if row["last_heartbeat"] is not None and row["last_heartbeat"] >= stale_before:
                return False
            if row["owner_pid"] is not None and pid_is_alive(int(row["owner_pid"])):
                return False
            cursor = connection.execute(
                """UPDATE generation_jobs
                   SET owner_token = ?, owner_pid = ?, last_heartbeat = ?, updated_at = ?
                   WHERE job_id = ? AND owner_token = ? AND status = ?""",
                (
                    new_owner_token,
                    owner_pid,
                    timestamp,
                    timestamp,
                    job_id,
                    expected_owner_token,
                    old_status.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event(
                connection,
                job_id,
                old_status,
                old_status,
                "RECOVERY_CLAIMED",
                timestamp,
            )
            return True

    def recovered_outcome_unknown(self, job_id: str, owner_token: str) -> bool:
        return self.fail(job_id, owner_token, "POST_DISPATCH_CONNECTION_LOST", unknown=True)
