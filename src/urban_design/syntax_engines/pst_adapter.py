"""Integrity-checked, subprocess-isolated adapter for PST 3.3.1."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


MAX_TIMEOUT_SECONDS = 2 * 60 * 60
RUNTIME_SCHEMA_VERSION = "pst-runtime-manifest-v1"
REQUEST_SCHEMA_VERSION = "pst-angular-request-v1"
RESULT_SCHEMA_VERSION = "pst-angular-result-v1"
RadiusMode = Literal["straight", "walking", "axmeter"]
MetricMode = Literal["both", "integration", "choice"]


class PSTRuntimeIntegrityError(RuntimeError):
    """Raised when the installed PST runtime does not match its pinned manifest."""


class PSTExecutionError(RuntimeError):
    """Raised when the isolated PST worker fails or returns invalid output."""


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _valid_xy(point: Sequence[float], label: str) -> tuple[float, float]:
    if isinstance(point, (str, bytes)) or len(point) != 2:
        raise ValueError(f"{label} must be an XY coordinate pair")
    return (_finite_number(point[0], f"{label}.x"), _finite_number(point[1], f"{label}.y"))


@dataclass(frozen=True)
class PSTLine:
    """One source network polyline, in projected metres."""

    id: str
    coordinates: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("line ID must be a non-empty string")
        if not isinstance(self.coordinates, tuple) or len(self.coordinates) < 2:
            raise ValueError(f"line {self.id!r} must have at least two coordinates")
        coordinates = tuple(
            _valid_xy(point, f"line {self.id!r} coordinate {index}")
            for index, point in enumerate(self.coordinates)
        )
        if any(math.dist(start, end) <= 0 for start, end in zip(coordinates, coordinates[1:])):
            raise ValueError(f"line {self.id!r} contains a zero-length segment")
        if sum(math.dist(start, end) for start, end in zip(coordinates, coordinates[1:])) <= 0:
            raise ValueError(f"line {self.id!r} must have positive length")


@dataclass(frozen=True)
class PSTRequest:
    """Raw angular metric request; normalization remains outside the adapter."""

    lines: tuple[PSTLine, ...]
    radius_m: float
    unlinks: tuple[tuple[float, float], ...] = ()
    radius_mode: RadiusMode = "walking"
    metric_mode: MetricMode = "both"
    angle_threshold: float = 0.0
    angle_precision: int = 1
    weigh_by_length: bool = False
    segment_map_snap_m: float = 0.0
    segment_map_min_tail_m: float = 0.0
    segment_map_colinear_deviation: float = 1.0
    segment_map_extrude_m: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.lines, tuple) or not self.lines:
            raise ValueError("lines must be a non-empty tuple of PSTLine values")
        if any(not isinstance(line, PSTLine) for line in self.lines):
            raise ValueError("lines must contain only PSTLine values")
        line_ids = [line.id for line in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("line IDs must be unique")
        radius = _finite_number(self.radius_m, "radius_m")
        if radius <= 0:
            raise ValueError("radius_m must be positive")
        if self.radius_mode not in ("straight", "walking", "axmeter"):
            raise ValueError("radius_mode must be straight, walking, or axmeter")
        if self.metric_mode not in ("both", "integration", "choice"):
            raise ValueError("metric_mode must be both, integration, or choice")
        threshold = _finite_number(self.angle_threshold, "angle_threshold")
        if threshold < 0 or threshold > 180:
            raise ValueError("angle_threshold must be between 0 and 180 degrees")
        if isinstance(self.angle_precision, bool) or not isinstance(self.angle_precision, int) or self.angle_precision < 1:
            raise ValueError("angle_precision must be a positive integer")
        if not isinstance(self.weigh_by_length, bool):
            raise ValueError("weigh_by_length must be boolean")
        if not isinstance(self.unlinks, tuple):
            raise ValueError("unlinks must be a tuple of XY coordinate pairs")
        for index, point in enumerate(self.unlinks):
            _valid_xy(point, f"unlink {index}")
        for name, value in (
            ("segment_map_snap_m", self.segment_map_snap_m),
            ("segment_map_min_tail_m", self.segment_map_min_tail_m),
            ("segment_map_colinear_deviation", self.segment_map_colinear_deviation),
            ("segment_map_extrude_m", self.segment_map_extrude_m),
        ):
            if _finite_number(value, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "lines": [
                {"id": line.id, "coordinates": [list(point) for point in line.coordinates]}
                for line in self.lines
            ],
            "unlinks": [list(point) for point in self.unlinks],
            "radius_m": float(self.radius_m),
            "radius_mode": self.radius_mode,
            "metric_mode": self.metric_mode,
            "angle_threshold": float(self.angle_threshold),
            "angle_precision": self.angle_precision,
            "weigh_by_length": self.weigh_by_length,
            "segment_map": {
                "snap_m": float(self.segment_map_snap_m),
                "min_tail_m": float(self.segment_map_min_tail_m),
                "colinear_deviation": float(self.segment_map_colinear_deviation),
                "extrude_m": float(self.segment_map_extrude_m),
            },
        }


@dataclass(frozen=True)
class PSTSegment:
    id: str
    source_line_id: str
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True)
class PSTResult:
    segments: tuple[PSTSegment, ...]
    node_counts: tuple[int, ...]
    total_depths: tuple[float, ...]
    choices: tuple[float, ...]
    total_depth_weights: tuple[float, ...]
    choice_node_counts: tuple[int, ...]
    choice_total_depths: tuple[float, ...]
    choice_total_depth_weights: tuple[float, ...]
    source_line_count: int
    explicit_unlink_count: int
    segment_map_generated_unlink_count: int
    segment_map_settings: Mapping[str, float]

    @property
    def graph_line_count(self) -> int:
        return len(self.segments)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_runtime_root(manifest: Mapping[str, Any], runtime_root: Path | None) -> Path:
    configured = manifest.get("runtime_path")
    if runtime_root is None:
        if not isinstance(configured, str) or not configured.strip():
            raise PSTRuntimeIntegrityError("runtime manifest requires a non-empty runtime_path")
        root = Path(os.path.expandvars(os.path.expanduser(configured)))
    else:
        root = Path(runtime_root)
    # Keep the lexical root path so verify_runtime can detect when the configured
    # runtime directory itself is a symlink before any path resolution follows it.
    return root.absolute()


def verify_runtime(manifest_path: Path, *, runtime_root: Path | None = None) -> Path:
    """Verify every pinned file and reject unlisted files or symlinks."""
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PSTRuntimeIntegrityError(f"cannot read PST runtime manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise PSTRuntimeIntegrityError("unsupported PST runtime manifest schema")

    root = _manifest_runtime_root(manifest, runtime_root)
    if root.is_symlink() or not root.is_dir():
        raise PSTRuntimeIntegrityError(f"PST runtime root is missing or not a directory: {root}")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise PSTRuntimeIntegrityError("runtime manifest files must be a non-empty list")

    expected: dict[str, tuple[int, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PSTRuntimeIntegrityError("runtime manifest file entries must be objects")
        relative = entry.get("path")
        size = entry.get("size_bytes")
        expected_hash = entry.get("sha256")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise PSTRuntimeIntegrityError(f"unsafe runtime manifest path: {relative!r}")
        if relative in expected:
            raise PSTRuntimeIntegrityError(f"duplicate runtime manifest path: {relative}")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PSTRuntimeIntegrityError(f"invalid size_bytes for runtime file: {relative}")
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise PSTRuntimeIntegrityError(f"invalid sha256 for runtime file: {relative}")
        expected[relative] = (size, expected_hash)

    found: set[str] = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in dirs:
            child = current_path / name
            if child.is_symlink():
                raise PSTRuntimeIntegrityError(f"symlink in PST runtime: {child.relative_to(root)}")
        for name in files:
            child = current_path / name
            relative = child.relative_to(root).as_posix()
            if child.is_symlink() or not child.is_file():
                raise PSTRuntimeIntegrityError(f"non-regular file in PST runtime: {relative}")
            found.add(relative)

    if found != set(expected):
        missing = sorted(set(expected) - found)
        extra = sorted(found - set(expected))
        raise PSTRuntimeIntegrityError(f"PST runtime file list mismatch; missing={missing}, extra={extra}")

    for relative, (expected_size, expected_hash) in expected.items():
        file_path = root / relative
        actual_size = file_path.stat().st_size
        actual_hash = _sha256(file_path)
        if actual_size != expected_size:
            raise PSTRuntimeIntegrityError(
                f"size mismatch for {relative}: expected {expected_size}, got {actual_size}"
            )
        if actual_hash != expected_hash:
            raise PSTRuntimeIntegrityError(
                f"sha256 mismatch for {relative}: expected {expected_hash}, got {actual_hash}"
            )
    return root


def _parse_result(payload: Any, expected_source_ids: tuple[str, ...], request: PSTRequest) -> PSTResult:
    if not isinstance(payload, dict) or payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise PSTExecutionError("PST worker returned an unsupported result schema")
    source_line_count = payload.get("source_line_count")
    if isinstance(source_line_count, bool) or not isinstance(source_line_count, int) or source_line_count != len(expected_source_ids):
        raise PSTExecutionError("PST worker result source line count does not match the request")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise PSTExecutionError("PST worker result has no segmented network geometry")
    segments: list[PSTSegment] = []
    source_ids = set(expected_source_ids)
    for record in raw_segments:
        if not isinstance(record, dict):
            raise PSTExecutionError("PST worker segment entries must be objects")
        segment_id = record.get("id")
        source_line_id = record.get("source_line_id")
        if not isinstance(segment_id, str) or not segment_id.strip() or source_line_id not in source_ids:
            raise PSTExecutionError("PST worker segment IDs do not match requested source line IDs")
        start = _valid_xy(record.get("start", ()), f"segment {segment_id!r} start")
        end = _valid_xy(record.get("end", ()), f"segment {segment_id!r} end")
        if math.dist(start, end) <= 0:
            raise PSTExecutionError(f"PST worker returned zero-length segment {segment_id!r}")
        segments.append(PSTSegment(id=segment_id, source_line_id=source_line_id, start=start, end=end))
    segment_ids = [segment.id for segment in segments]
    if len(segment_ids) != len(set(segment_ids)):
        raise PSTExecutionError("PST worker returned duplicate segment IDs")
    represented_source_ids = {segment.source_line_id for segment in segments}
    if represented_source_ids != source_ids:
        missing = sorted(source_ids - represented_source_ids)
        raise PSTExecutionError(f"PST worker result source line coverage is incomplete; missing={missing}")

    count = len(segments)
    def numeric_array(name: str) -> tuple[float, ...]:
        values = payload.get(name)
        if not isinstance(values, list) or len(values) != count:
            raise PSTExecutionError(f"PST worker result {name} length does not match input lines")
        output: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise PSTExecutionError(f"PST worker result {name} contains a non-finite or invalid value")
            output.append(float(value))
        return tuple(output)

    def count_array(name: str) -> tuple[int, ...]:
        values = payload.get(name)
        if not isinstance(values, list) or len(values) != count:
            raise PSTExecutionError(f"PST worker result {name} length does not match input lines")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise PSTExecutionError(f"PST worker result {name} contains an invalid count")
        return tuple(values)

    def non_negative_int(name: str) -> int:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PSTExecutionError(f"PST worker result {name} is invalid")
        return value

    settings = payload.get("segment_map_settings")
    if not isinstance(settings, dict):
        raise PSTExecutionError("PST worker result is missing segment map settings")
    expected_settings = request.to_payload()["segment_map"]
    if settings != expected_settings:
        raise PSTExecutionError("PST worker segment map settings do not match the request")

    return PSTResult(
        segments=tuple(segments),
        node_counts=count_array("node_counts"),
        total_depths=numeric_array("total_depths"),
        choices=numeric_array("choices"),
        total_depth_weights=numeric_array("total_depth_weights"),
        choice_node_counts=count_array("choice_node_counts"),
        choice_total_depths=numeric_array("choice_total_depths"),
        choice_total_depth_weights=numeric_array("choice_total_depth_weights"),
        source_line_count=source_line_count,
        explicit_unlink_count=non_negative_int("explicit_unlink_count"),
        segment_map_generated_unlink_count=non_negative_int("segment_map_generated_unlink_count"),
        segment_map_settings=settings,
    )


class PSTAdapter:
    """Validates pinned runtime files, then delegates all ctypes work to a child."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        runtime_root: Path | None = None,
        timeout_seconds: int = MAX_TIMEOUT_SECONDS,
        worker_script_path: Path | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be between 0 and 7200")
        if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be between 0 and 7200")
        self.manifest_path = Path(manifest_path)
        self.runtime_root = Path(runtime_root) if runtime_root is not None else None
        self.timeout_seconds = float(timeout_seconds)
        self.worker_script_path = Path(worker_script_path) if worker_script_path else Path(__file__).with_name("pst_worker.py")

    def compute(self, request: PSTRequest) -> PSTResult:
        if not isinstance(request, PSTRequest):
            raise ValueError("request must be a PSTRequest")
        runtime_root = verify_runtime(self.manifest_path, runtime_root=self.runtime_root)
        if not self.worker_script_path.is_file() or self.worker_script_path.is_symlink():
            raise PSTExecutionError(f"PST worker script is missing or unsafe: {self.worker_script_path}")

        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(runtime_root / "python")
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment.pop("PSTALGO_DEBUG", None)
        try:
            completed = subprocess.run(
                [sys.executable, str(self.worker_script_path)],
                input=json.dumps(request.to_payload(), allow_nan=False),
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise PSTExecutionError(f"PST worker exceeded {self.timeout_seconds:g} second timeout") from exc
        except OSError as exc:
            raise PSTExecutionError(f"could not start PST worker: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "no diagnostic output").strip()[-2000:]
            raise PSTExecutionError(f"PST worker exited with {completed.returncode}: {detail}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PSTExecutionError("PST worker did not return valid JSON") from exc
        return _parse_result(payload, tuple(line.id for line in request.lines), request)
