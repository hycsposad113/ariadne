"""Single-dispatch generation runner with verified, recoverable publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
from typing import Any, Callable, Mapping, Sequence
import uuid

from urban_design.generation.contracts import FrozenRef
from urban_design.generation.job_store import GenerationJob, GenerationJobStore, JobStatus


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PreparedOutput:
    artifact_id: str
    relative_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class PreparedManifest:
    manifest_path: Path
    sha256: str
    input_refs: tuple[Mapping[str, str], ...]
    output_refs: tuple[PreparedOutput, ...]
    handler_version: str


class CancellationToken:
    """Per-job cancellation flag and heartbeat callback; it never kills a process."""

    def __init__(self, heartbeat: Callable[[], bool] | None = None):
        self._event = threading.Event()
        self._heartbeat = heartbeat

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def heartbeat(self) -> bool:
        return bool(self._heartbeat and self._heartbeat())


@dataclass(frozen=True)
class _HandlerRegistration:
    version: str
    run_stage: Callable[[GenerationJob, Path, CancellationToken], PreparedManifest]
    external: bool


class PostDispatchOutcomeUnknown(RuntimeError):
    """A handler lost transport after external work was dispatched."""


class KnownExecutionFailure(RuntimeError):
    """A dispatched computation returned a known failure, not an unknown outcome."""


class _OutputCollision(RuntimeError):
    pass


def write_prepared_manifest(
    staging_dir: str | Path,
    *,
    handler_version: str,
    input_refs: Sequence[Mapping[str, Any]],
    output_refs: Sequence[PreparedOutput],
) -> PreparedManifest:
    """Write the canonical manifest returned by a deterministic job handler."""

    root = Path(staging_dir)
    root.mkdir(parents=True, exist_ok=True)
    inputs = tuple(FrozenRef.model_validate(ref).model_dump(mode="json") for ref in input_refs)
    outputs = tuple(output_refs)
    body = {
        "manifest_version": "generation-stage-v1",
        "handler_version": handler_version,
        "input_refs": list(inputs),
        "output_refs": [
            {
                "artifact_id": output.artifact_id,
                "relative_path": output.relative_path,
                "sha256": output.sha256,
                "size_bytes": output.size_bytes,
            }
            for output in outputs
        ],
    }
    manifest_path = root / "manifest.json"
    encoded = _json_bytes(body)
    manifest_path.write_bytes(encoded)
    return PreparedManifest(
        manifest_path=manifest_path,
        sha256=_sha256(encoded),
        input_refs=inputs,
        output_refs=outputs,
        handler_version=handler_version,
    )


def _manifest_from_file(path: Path) -> PreparedManifest:
    encoded = path.read_bytes()
    try:
        body = json.loads(encoded)
        if not isinstance(body, dict) or body["manifest_version"] != "generation-stage-v1":
            raise ValueError("unsupported manifest version")
        inputs = tuple(FrozenRef.model_validate(ref).model_dump(mode="json") for ref in body["input_refs"])
        raw_outputs = body["output_refs"]
        if not isinstance(raw_outputs, list):
            raise ValueError("manifest output_refs must be a list")
        outputs_list: list[PreparedOutput] = []
        for item in raw_outputs:
            if not isinstance(item, dict) or set(item) != {"artifact_id", "relative_path", "sha256", "size_bytes"}:
                raise ValueError("manifest output reference has an invalid shape")
            if (
                not isinstance(item["artifact_id"], str)
                or not isinstance(item["relative_path"], str)
                or not isinstance(item["sha256"], str)
                or isinstance(item["size_bytes"], bool)
                or not isinstance(item["size_bytes"], int)
            ):
                raise ValueError("manifest output reference has invalid field types")
            outputs_list.append(PreparedOutput(**item))
        outputs = tuple(outputs_list)
        version = body["handler_version"]
        if not isinstance(version, str) or not version.strip():
            raise ValueError("manifest handler_version must be non-empty text")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("prepared manifest is malformed") from error
    return PreparedManifest(path, _sha256(encoded), inputs, outputs, version)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_relative_output(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ValueError("output path must be a non-empty relative POSIX path")
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise ValueError("output path escapes its staging directory")
    output = root.joinpath(*pure_path.parts)
    resolved = output.resolve(strict=True)
    if not _inside(root.resolve(strict=True), resolved):
        raise ValueError("output path escapes its staging directory")
    current = output
    while current != root:
        if current.is_symlink():
            raise ValueError("symlink outputs are not publishable")
        current = current.parent
    if not resolved.is_file():
        raise ValueError("prepared output must be a regular file")
    return resolved


def _validate_prepared(
    prepared: PreparedManifest,
    root: Path,
    job: GenerationJob,
    expected_handler_version: str,
    *,
    expected_manifest_sha256: str | None = None,
) -> PreparedManifest:
    root = root.resolve(strict=True)
    manifest_path = prepared.manifest_path.resolve(strict=True)
    if not _inside(root, manifest_path) or prepared.manifest_path.is_symlink():
        raise ValueError("manifest path must remain inside its staging directory")
    if not manifest_path.is_file():
        raise ValueError("manifest must be a regular file")
    loaded = _manifest_from_file(manifest_path)
    if loaded.sha256 != prepared.sha256 or loaded != prepared:
        raise ValueError("prepared manifest contents do not match the handler receipt")
    if expected_manifest_sha256 is not None and loaded.sha256 != expected_manifest_sha256:
        raise _OutputCollision("published manifest hash differs from the recorded hash")
    if loaded.handler_version != expected_handler_version:
        raise ValueError("prepared manifest handler version does not match the registered handler")
    if [dict(ref) for ref in loaded.input_refs] != [dict(ref) for ref in job.input_refs]:
        raise ValueError("prepared manifest input references differ from the job")
    if not loaded.output_refs:
        raise ValueError("prepared manifest must include at least one output")
    artifact_ids: set[str] = set()
    paths: set[str] = set()
    for output in loaded.output_refs:
        if not output.artifact_id.strip() or output.artifact_id in artifact_ids:
            raise ValueError("prepared artifact identities must be non-empty and unique")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", output.sha256):
            raise ValueError("prepared artifact hash must use sha256:<64 lowercase hex characters>")
        if isinstance(output.size_bytes, bool) or not isinstance(output.size_bytes, int) or output.size_bytes < 0:
            raise ValueError("prepared artifact size must be a non-negative integer")
        if output.relative_path in paths or output.relative_path == "manifest.json":
            raise ValueError("prepared output paths must be unique and cannot replace the manifest")
        file_path = _validate_relative_output(root, output.relative_path)
        data = file_path.read_bytes()
        if len(data) != output.size_bytes or _sha256(data) != output.sha256:
            raise ValueError(f"prepared artifact failed size/hash verification: {output.artifact_id}")
        artifact_ids.add(output.artifact_id)
        paths.add(output.relative_path)
    return loaded


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class GenerationJobRunner:
    """Dispatches one registered handler for a claimed job and reconciles outputs."""

    def __init__(
        self,
        store: GenerationJobStore,
        *,
        staging_root: str | Path,
        output_root: str | Path,
        revision_is_current: Callable[[GenerationJob], bool] | None = None,
        pid_is_alive: Callable[[int], bool] = _pid_is_alive,
    ):
        self.store = store
        self.staging_root = Path(staging_root).expanduser().resolve()
        self.output_root = Path(output_root).expanduser().resolve()
        self.revision_is_current = revision_is_current
        self.pid_is_alive = pid_is_alive
        self._handlers: dict[str, _HandlerRegistration] = {}
        self._active_lock = threading.Lock()
        self._active_tokens: dict[str, tuple[str, CancellationToken]] = {}

    def register_handler(
        self,
        stage: str,
        version: str,
        run_stage: Callable[[GenerationJob, Path, CancellationToken], PreparedManifest],
        *,
        external: bool = False,
    ) -> None:
        if not stage.strip() or not version.strip() or not callable(run_stage):
            raise ValueError("registered stage handler needs a stage, version, and callable")
        if stage in self._handlers:
            raise ValueError(f"a handler is already registered for stage {stage}")
        self._handlers[stage] = _HandlerRegistration(version.strip(), run_stage, external)

    def has_handler(self, stage: str) -> bool:
        """Expose readiness without dispatching or inspecting private registrations."""
        return stage in self._handlers

    def verify_published(self, job_id: str) -> bool:
        """Read-only integrity check; READY bookkeeping alone is insufficient."""
        job = self.store.get(job_id)
        registration = self._handlers.get(job.stage)
        if job.status is not JobStatus.READY or registration is None or not job.output_manifest_sha256:
            return False
        directory = self._output_dir(job_id)
        try:
            if directory.is_symlink():
                return False
            manifest = _manifest_from_file(directory / "manifest.json")
            _validate_prepared(manifest, directory, job, registration.version,
                               expected_manifest_sha256=job.output_manifest_sha256)
            return [output.__dict__ for output in manifest.output_refs] == [dict(ref) for ref in job.output_refs]
        except (OSError, ValueError):
            return False

    def _attempt_dir(self, job: GenerationJob) -> Path:
        if not job.job_id.isalnum():
            raise ValueError("job ID is not a safe staging-directory name")
        return self.staging_root / job.job_id

    def _output_dir(self, job_id: str) -> Path:
        if not job_id.isalnum():
            raise ValueError("job ID is not a safe output-directory name")
        return self.output_root / job_id

    def _manifest_ref(self, job: GenerationJob) -> str:
        return f"{job.job_id}/manifest.json"

    def _publish_directory(
        self,
        job: GenerationJob,
        attempt_dir: Path,
        prepared: PreparedManifest,
        registration: _HandlerRegistration,
    ) -> Path:
        self.output_root.mkdir(parents=True, exist_ok=True)
        destination = self._output_dir(job.job_id)
        if destination.is_symlink():
            raise _OutputCollision("published job path is a symlink")
        if destination.exists():
            try:
                existing = _manifest_from_file(destination / "manifest.json")
                _validate_prepared(
                    existing,
                    destination,
                    job,
                    registration.version,
                    expected_manifest_sha256=prepared.sha256,
                )
            except _OutputCollision:
                raise
            except (OSError, ValueError) as error:
                raise _OutputCollision("published job directory contains a different or invalid manifest") from error
            return destination

        try:
            _validate_prepared(
                prepared,
                attempt_dir,
                job,
                registration.version,
                expected_manifest_sha256=prepared.sha256,
            )
        except _OutputCollision:
            raise
        except (AttributeError, OSError, TypeError, ValueError) as error:
            raise _OutputCollision("staged output changed after validation") from error

        attempt_device = attempt_dir.stat().st_dev
        output_device = self.output_root.stat().st_dev
        if attempt_device != output_device:
            raise OSError(errno.EXDEV, "staging and published outputs must share a filesystem")
        os.rename(attempt_dir, destination)
        directory_fd = os.open(self.output_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination

    def _mark_cancelled(self, job: GenerationJob, owner_token: str, attempt_dir: Path) -> GenerationJob:
        if attempt_dir.exists():
            marker = attempt_dir / "interrupted.json"
            if not marker.exists():
                marker.write_bytes(
                    _json_bytes({"job_id": job.job_id, "status": JobStatus.CANCELLED.value})
                )
        self.store.finish_cancelled(job.job_id, owner_token)
        return self.store.get(job.job_id)

    def run(self, job_id: str) -> GenerationJob:
        job = self.store.get(job_id)
        if job.status is not JobStatus.PENDING:
            return job
        registration = self._handlers.get(job.stage)
        if registration is None:
            raise ValueError(f"no server-registered handler for stage {job.stage}")

        owner_token = uuid.uuid4().hex
        if not self.store.claim(job_id, owner_token, os.getpid()):
            return self.store.get(job_id)
        job = self.store.get(job_id)
        attempt_dir = self._attempt_dir(job)
        heartbeat = lambda: self.store.heartbeat(job_id, owner_token)
        cancellation_token = CancellationToken(heartbeat)
        with self._active_lock:
            self._active_tokens[job_id] = (owner_token, cancellation_token)
        try:
            if self.store.cancel_requested(job_id):
                cancellation_token.cancel()
            try:
                attempt_dir.mkdir(parents=True, exist_ok=False)
            except OSError:
                self.store.fail(job_id, owner_token, "STAGING_CREATE_FAILED")
                return self.store.get(job_id)

            try:
                prepared = registration.run_stage(job, attempt_dir, cancellation_token)
            except Exception as error:
                if cancellation_token.cancelled or self.store.cancel_requested(job_id):
                    cancellation_token.cancel()
                    return self._mark_cancelled(job, owner_token, attempt_dir)
                self.store.fail(
                    job_id,
                    owner_token,
                    "POST_DISPATCH_CONNECTION_LOST"
                    if registration.external or isinstance(error, PostDispatchOutcomeUnknown)
                    else "KNOWN_COMPUTATION_FAILED"
                    if isinstance(error, KnownExecutionFailure)
                    else "HANDLER_FAILED",
                    unknown=registration.external or isinstance(error, PostDispatchOutcomeUnknown),
                )
                return self.store.get(job_id)

            if cancellation_token.cancelled or self.store.cancel_requested(job_id):
                cancellation_token.cancel()
                return self._mark_cancelled(job, owner_token, attempt_dir)
            try:
                prepared = _validate_prepared(prepared, attempt_dir, job, registration.version)
            except (AttributeError, OSError, TypeError, ValueError):
                self.store.fail(job_id, owner_token, "INVALID_PREPARED_MANIFEST")
                return self.store.get(job_id)

            if not self.store.record_prepared(
                job_id,
                owner_token,
                manifest_ref=self._manifest_ref(job),
                manifest_sha256=prepared.sha256,
                output_refs=[
                    {
                        "artifact_id": output.artifact_id,
                        "relative_path": output.relative_path,
                        "sha256": output.sha256,
                        "size_bytes": output.size_bytes,
                    }
                    for output in prepared.output_refs
                ],
            ):
                return self.store.get(job_id)

            try:
                self._publish_directory(job, attempt_dir, prepared, registration)
            except _OutputCollision:
                self.store.mark_collision(job_id, owner_token)
                return self.store.get(job_id)
            except OSError:
                self.store.note_publish_failed(job_id, owner_token)
                return self.store.get(job_id)

            stale = bool(
                job.expected_revision is not None
                and self.revision_is_current is not None
                and not self.revision_is_current(job)
            )
            self.store.complete(job_id, owner_token, stale=stale)
            return self.store.get(job_id)
        finally:
            with self._active_lock:
                self._active_tokens.pop(job_id, None)

    def cancel(self, job_id: str) -> GenerationJob:
        job = self.store.request_cancel(job_id)
        with self._active_lock:
            active = self._active_tokens.get(job_id)
        if active is not None and job.cancellation_requested:
            active[1].cancel()
        return self.store.get(job_id)

    def recover(
        self,
        job_id: str,
        *,
        now: datetime | None = None,
        stale_after_seconds: float = 60,
    ) -> GenerationJob:
        """Reconcile a dead worker's complete artifact without calling its handler."""

        job = self.store.get(job_id)
        if job.status not in {JobStatus.RUNNING, JobStatus.PREPARED} or job.owner_token is None:
            return job
        registration = self._handlers.get(job.stage)
        if registration is None:
            return job
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("recovery time must be timezone-aware")
        stale_before = (current_time - timedelta(seconds=stale_after_seconds)).astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        )
        new_owner_token = uuid.uuid4().hex

        published_dir = self._output_dir(job.job_id)
        attempt_dir = self._attempt_dir(job)
        candidate_dir: Path | None = None
        prepared: PreparedManifest | None = None
        collision = False
        for directory in (published_dir, attempt_dir):
            if not (directory / "manifest.json").is_file():
                continue
            try:
                receipt = _manifest_from_file(directory / "manifest.json")
                prepared = _validate_prepared(
                    receipt,
                    directory,
                    job,
                    registration.version,
                    expected_manifest_sha256=(
                        job.output_manifest_sha256 if job.status is JobStatus.PREPARED else None
                    ),
                )
                candidate_dir = directory
                break
            except _OutputCollision:
                collision = True
                break
            except (AttributeError, OSError, TypeError, ValueError):
                if directory == published_dir:
                    collision = True
                    break
                continue

        if not self.store.claim_recovery(
            job_id,
            job.owner_token,
            new_owner_token,
            os.getpid(),
            stale_before=stale_before,
            pid_is_alive=self.pid_is_alive,
            now=current_time.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        ):
            return self.store.get(job_id)

        job = self.store.get(job_id)
        if collision:
            self.store.mark_collision(job_id, new_owner_token)
            return self.store.get(job_id)
        if candidate_dir is None or prepared is None:
            if registration.external and job.status is JobStatus.RUNNING:
                self.store.recovered_outcome_unknown(job_id, new_owner_token)
            else:
                self.store.mark_interrupted(job_id, new_owner_token)
            return self.store.get(job_id)

        if job.status is JobStatus.RUNNING:
            if not self.store.record_prepared(
                job_id,
                new_owner_token,
                manifest_ref=self._manifest_ref(job),
                manifest_sha256=prepared.sha256,
                output_refs=[
                    {
                        "artifact_id": output.artifact_id,
                        "relative_path": output.relative_path,
                        "sha256": output.sha256,
                        "size_bytes": output.size_bytes,
                    }
                    for output in prepared.output_refs
                ],
                now=current_time.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            ):
                return self.store.get(job_id)

        try:
            self._publish_directory(job, attempt_dir, prepared, registration)
        except _OutputCollision:
            self.store.mark_collision(job_id, new_owner_token)
            return self.store.get(job_id)
        except OSError:
            self.store.note_publish_failed(job_id, new_owner_token)
            return self.store.get(job_id)

        stale = bool(
            job.expected_revision is not None
            and self.revision_is_current is not None
            and not self.revision_is_current(job)
        )
        self.store.complete(job_id, new_owner_token, stale=stale)
        return self.store.get(job_id)


__all__ = [
    "CancellationToken",
    "GenerationJobRunner",
    "PreparedManifest",
    "PreparedOutput",
    "write_prepared_manifest",
]
