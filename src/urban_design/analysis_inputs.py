"""Fail-closed M2-A03 analysis-input evidence and decision-package helpers.

This module deliberately stops before live acquisition when the active
StudyArea cannot be mapped to the declared projected CRS.  It also provides
the small, deterministic validation surface used by a later source adapter:
raw bytes are hash-addressed, normalized artifacts retain raw-parent lineage,
and proposed analysis policies are never accepted as executable inputs.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence
import uuid

import pyproj
from pyproj import CRS, Transformer
from shapely.geometry import shape

from .geometry import canonical_geometry_hash
from .models import Artifact, DatasetSnapshot
from .project_anchor import (
    ProjectAnchorError,
    load_project_anchor,
    projected_crs_area_of_use,
)
from .store import EntityNotFoundError, ProjectStateStore, StoreError


PROJECT_ID = "rotterdam-m4h-pilot-project"
# The active StudyArea is a project-owned pointer, not a module constant.  Keep
# this name as a compatibility sentinel for callers that used to pass the old
# default explicitly; ``None`` now means resolve the project pointer.
STUDY_AREA_ID: str | None = None
STUDY_AREA_CRS = "EPSG:28992"
STUDY_AREA_UNITS = "m"
QUERY_BUFFER_METRES = 1200.0
PACKAGE_STATUS_BLOCKED = "BLOCKED"
PROPOSED_PROJECT_DECISION = "PROPOSED_PROJECT_DECISION"
APPROVED_PROJECT_DECISION = "APPROVED_PROJECT_DECISION"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RETRIEVAL_STATUSES = frozenset({"OBSERVED", "EMPTY", "UNAVAILABLE", "FAILED"})
_APPROVED_STATUSES = frozenset({"APPROVED", "ACTIVE", "FROZEN"})


class AnalysisInputError(ValueError):
    """Base error for M2-A03 package and provenance validation."""


class ArtifactIntegrityError(AnalysisInputError):
    """Raised when immutable bytes do not match their recorded metadata."""


class ProvenanceValidationError(AnalysisInputError):
    """Raised when a source record is incomplete or internally inconsistent."""


class StudyAreaAnchorError(AnalysisInputError):
    """Raised when an active StudyArea cannot support a geographic query."""


class AnalysisInputPublicationError(AnalysisInputError):
    """Raised when a package cannot be published and committed atomically."""

    retryable = True


@dataclass(frozen=True)
class StudyAreaInspection:
    """Authoritative active-area evidence used to derive the query envelope."""

    project_id: str
    study_area_id: str
    geometry_artifact_id: str
    geometry_sha256: str
    artifact_sha256: str
    artifact_uri: str
    horizontal_crs: str
    units: str
    vertical_reference: str | None
    geometry_type: str
    observed_bbox: tuple[float, float, float, float]
    query_envelope: tuple[float, float, float, float]
    query_envelope_crs84: tuple[float, float, float, float]
    query_envelope_axis_order: str
    pyproj_version: str
    anchor_status: str
    anchor_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "study_area_id": self.study_area_id,
            "geometry_artifact_id": self.geometry_artifact_id,
            "geometry_sha256": self.geometry_sha256,
            "artifact_sha256": self.artifact_sha256,
            "artifact_uri": self.artifact_uri,
            "horizontal_crs": self.horizontal_crs,
            "units": self.units,
            "vertical_reference": self.vertical_reference,
            "geometry_type": self.geometry_type,
            "observed_bbox": list(self.observed_bbox),
            "query_envelope": list(self.query_envelope),
            "query_envelope_crs": self.horizontal_crs,
            "query_envelope_input_bounds": list(self.query_envelope),
            "query_envelope_crs84": list(self.query_envelope_crs84),
            "query_envelope_output_bounds_crs84": list(self.query_envelope_crs84),
            "query_envelope_axis_order": self.query_envelope_axis_order,
            "query_envelope_crs84_axis_order": "longitude,latitude",
            "pyproj_version": self.pyproj_version,
            "query_buffer_m": QUERY_BUFFER_METRES,
            "anchor_status": self.anchor_status,
            "anchor_reason": self.anchor_reason,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceValidationError(f"{field} is required")
    return value.strip()


def _sha(value: Any, field: str = "sha256") -> str:
    value = _nonempty(value, field)
    if not _SHA256_RE.fullmatch(value):
        raise ProvenanceValidationError(f"{field} must be sha256:<64 lowercase hex characters>")
    return value


def _aware_timestamp(value: Any, field: str) -> str:
    value = _nonempty(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProvenanceValidationError(f"{field} must include a timezone")
    return parsed.isoformat()


def _resolve_under(root: Path, relative_or_absolute: str) -> Path:
    candidate = Path(relative_or_absolute)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ArtifactIntegrityError("artifact path escapes package root")
    return resolved


def validate_artifact_record(record: Mapping[str, Any], *, root: str | Path) -> dict[str, Any]:
    """Validate typed Artifact metadata and the bytes it addresses."""

    root_path = Path(root)
    artifact_id = _nonempty(record.get("id"), "artifact.id")
    uri = _nonempty(record.get("uri"), "artifact.uri")
    path = _resolve_under(root_path, uri)
    if not path.is_file():
        raise ArtifactIntegrityError(f"artifact bytes are missing: {uri}")
    actual_hash = sha256_file(path)
    declared_hash = _sha(record.get("sha256"), "artifact.sha256")
    if actual_hash != declared_hash:
        raise ArtifactIntegrityError(f"artifact hash mismatch: {artifact_id}")
    size = record.get("size_bytes")
    if not isinstance(size, int) or size < 0:
        raise ProvenanceValidationError("artifact.size_bytes must be a non-negative integer")
    if size != path.stat().st_size:
        raise ArtifactIntegrityError(f"artifact size mismatch: {artifact_id}")
    payload = {
        "id": artifact_id,
        "type": _nonempty(record.get("type"), "artifact.type"),
        "uri": uri,
        "sha256": declared_hash,
        "mime": _nonempty(record.get("mime"), "artifact.mime"),
        "crs": record.get("crs"),
        "producer": _nonempty(record.get("producer"), "artifact.producer"),
        "created_at": _aware_timestamp(record.get("created_at"), "artifact.created_at"),
        "project_id": record.get("project_id"),
        "size_bytes": size,
        "parent_artifact_ids": list(record.get("parent_artifact_ids", [])),
    }
    try:
        Artifact.model_validate(payload)
    except Exception as exc:  # pydantic's error type is intentionally not part of this API
        raise ProvenanceValidationError(f"invalid typed Artifact {artifact_id}") from exc
    return payload


def validate_snapshot_record(
    record: Mapping[str, Any],
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    root: str | Path,
) -> dict[str, Any]:
    """Validate a DatasetSnapshot plus the required portable provenance fields."""

    snapshot_id = _nonempty(record.get("id"), "snapshot.id")
    project_id = _nonempty(record.get("project_id"), "snapshot.project_id")
    source_url = _nonempty(record.get("source_url", record.get("source")), "snapshot.source_url")
    query = _nonempty(record.get("query"), "snapshot.query")
    retrieved_at = _aware_timestamp(record.get("retrieved_at"), "snapshot.retrieved_at")
    publisher = _nonempty(record.get("publisher"), "snapshot.publisher")
    license_value = _nonempty(record.get("license", record.get("licence")), "snapshot.license")
    version = _nonempty(record.get("version"), "snapshot.version")
    attribution = _nonempty(record.get("attribution"), "snapshot.attribution")
    raw_artifact_id = _nonempty(record.get("raw_artifact_id"), "snapshot.raw_artifact_id")
    raw_artifact = artifacts.get(raw_artifact_id)
    if raw_artifact is None:
        raise ProvenanceValidationError(f"snapshot references unknown raw artifact: {raw_artifact_id}")
    raw_artifact = validate_artifact_record(raw_artifact, root=root)
    if raw_artifact.get("project_id") != project_id:
        raise ProvenanceValidationError(f"snapshot/raw artifact project mismatch: {snapshot_id}")
    snapshot_hash = _sha(record.get("sha256"), "snapshot.sha256")
    if snapshot_hash != raw_artifact["sha256"]:
        raise ArtifactIntegrityError(f"snapshot/raw artifact hash mismatch: {snapshot_id}")
    limitations = record.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(item, str) or not item.strip() for item in limitations):
        raise ProvenanceValidationError("snapshot.limitations must be a list of non-empty strings")
    availability = _nonempty(record.get("availability"), "snapshot.availability").upper()
    if availability not in _RETRIEVAL_STATUSES:
        raise ProvenanceValidationError(f"unsupported snapshot availability: {availability}")
    payload = {
        "id": snapshot_id,
        "project_id": project_id,
        "source": source_url,
        "query": query,
        "retrieved_at": retrieved_at,
        "publisher": publisher,
        "license": license_value,
        "version": version,
        "sha256": snapshot_hash,
        "raw_artifact_id": raw_artifact_id,
        "normalized_artifact_id": record.get("normalized_artifact_id"),
    }
    try:
        DatasetSnapshot.model_validate(payload)
    except Exception as exc:
        raise ProvenanceValidationError(f"invalid typed DatasetSnapshot {snapshot_id}") from exc
    return {
        **dict(record),
        "id": snapshot_id,
        "project_id": project_id,
        "source_url": source_url,
        "query": query,
        "retrieved_at": retrieved_at,
        "publisher": publisher,
        "license": license_value,
        "version": version,
        "attribution": attribution,
        "sha256": snapshot_hash,
        "raw_artifact_id": raw_artifact_id,
        "limitations": list(limitations),
        "availability": availability,
    }


def validate_normalized_artifact_record(
    record: Mapping[str, Any],
    *,
    raw_artifact: Mapping[str, Any],
    root: str | Path,
) -> dict[str, Any]:
    """Validate a normalized child artifact and its immutable raw parent."""

    parent_id = _nonempty(record.get("raw_parent_artifact_id"), "normalized.raw_parent_artifact_id")
    if parent_id != raw_artifact.get("id"):
        raise ProvenanceValidationError("normalized artifact raw-parent identity mismatch")
    parents = record.get("parent_artifact_ids", [])
    if parent_id not in parents:
        raise ProvenanceValidationError("normalized artifact must list its raw parent")
    normalized = validate_artifact_record(record, root=root)
    if normalized.get("project_id") != raw_artifact.get("project_id"):
        raise ProvenanceValidationError("normalized/raw artifact project mismatch")
    return normalized


def ensure_metric_crs(crs: str) -> str:
    """Return a canonical CRS string and reject geographic CRSs for metres."""

    crs_text = _nonempty(crs, "crs")
    try:
        parsed = CRS.from_user_input(crs_text)
    except Exception as exc:
        raise AnalysisInputError(f"invalid CRS: {crs_text}") from exc
    if parsed.is_geographic:
        raise AnalysisInputError("geographic CRS cannot support metric query operations")
    return parsed.to_authority() and f"{parsed.to_authority()[0]}:{parsed.to_authority()[1]}" or crs_text


def classify_observation(status: str, *, count: int | None = None) -> str:
    """Keep empty, unavailable, and failed observations semantically distinct."""

    value = _nonempty(status, "availability").upper()
    if value not in _RETRIEVAL_STATUSES:
        raise AnalysisInputError(f"invalid observation status: {value}")
    if value == "OBSERVED" and count is not None and count == 0:
        return "EMPTY"
    if value == "EMPTY" and count not in (None, 0):
        raise AnalysisInputError("EMPTY observation cannot contain a positive count")
    return value


def inventory_osm_grocery_tags(features: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Count raw OSM grocery tags without collapsing categories."""

    counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for feature in features:
        properties = feature.get("properties", {}) if isinstance(feature, Mapping) else {}
        tags = properties.get("tags", properties) if isinstance(properties, Mapping) else {}
        shop = tags.get("shop") if isinstance(tags, Mapping) else None
        if isinstance(shop, str) and shop.strip():
            value = shop.strip()
            counts[value] += 1
            records.append({"shop": value, "feature_id": properties.get("@id", properties.get("id"))})
    return {"counts_by_shop_tag": dict(sorted(counts.items())), "records": records}


def require_approved_policy(policy: Mapping[str, Any], *, name: str = "policy") -> Mapping[str, Any]:
    """Reject proposed methodology at every computational-consumer boundary."""

    status = str(policy.get("status", "")).strip().upper()
    if status not in _APPROVED_STATUSES:
        raise AnalysisInputError(f"{name} is not approved for computation")
    return policy


def package_is_stale(package: Mapping[str, Any], *, current_geometry_sha256: str) -> bool:
    """Detect StudyArea replacement without mutating the prior package."""

    expected = package.get("study_area", {}).get("geometry_sha256")
    return expected != current_geometry_sha256


def _rd_new_projected_bounds() -> tuple[float, float, float, float]:
    try:
        return projected_crs_area_of_use(STUDY_AREA_CRS)
    except ProjectAnchorError as exc:  # pragma: no cover - locked project CRS
        raise StudyAreaAnchorError(str(exc)) from exc


def _default_project_anchor_path() -> Path:
    """Return the repository's source-backed M4H drawing guard."""

    return Path(__file__).resolve().parents[2] / "config" / "rotterdam-m4h-anchor.json"


def _load_m4h_anchor(anchor_path: str | Path | None) -> Any:
    """Load the configured anchor while preserving its source provenance.

    The production config stores paths relative to the repository root.  An
    explicit path is supported for isolated package tests; its parent is used
    as the provenance root in that case.
    """

    path = Path(anchor_path).expanduser().resolve() if anchor_path is not None else _default_project_anchor_path()
    if anchor_path is None:
        root = path.parents[1]
    else:
        root = path.parent
    try:
        return load_project_anchor(path, root=root)
    except (OSError, ProjectAnchorError) as exc:
        raise StudyAreaAnchorError(f"configured M4H project anchor could not be validated: {exc}") from exc


def _numeric_coordinates(value: Any) -> Iterable[tuple[float, float]]:
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:2]):
            x, y = float(value[0]), float(value[1])
            if not isfinite(x) or not isfinite(y):
                raise StudyAreaAnchorError("StudyArea contains non-finite coordinates")
            yield x, y
            return
        for child in value:
            yield from _numeric_coordinates(child)


def inspect_active_study_area(
    database: str | Path,
    *,
    project_id: str = PROJECT_ID,
    study_area_id: str | None = None,
    anchor_path: str | Path | None = None,
) -> StudyAreaInspection:
    """Resolve and verify the project-pointer StudyArea and immutable bytes.

    When ``study_area_id`` is omitted, the current project's
    ``active_study_area_id`` is authoritative.  An explicitly supplied ID is
    accepted only when it matches that pointer; this prevents a stale
    package from being silently re-used after v5 activation.
    """

    try:
        with ProjectStateStore(database, read_only=True) as store:
            project = store.current(project_id)
            active_study_area_id = project.payload.get("active_study_area_id")
            if not isinstance(active_study_area_id, str) or not active_study_area_id.strip():
                raise StudyAreaAnchorError("project has no active StudyArea pointer")
            active_study_area_id = active_study_area_id.strip()
            if study_area_id is not None and study_area_id != active_study_area_id:
                raise StudyAreaAnchorError(
                    "requested StudyArea is stale or does not match the active project pointer"
                )
            resolved_study_area_id = active_study_area_id
            area = store.current(resolved_study_area_id)
            if project.entity_type != "Project" or area.entity_type != "StudyArea":
                raise StudyAreaAnchorError("active records have unexpected entity types")
            if area.project_id != project_id or area.payload.get("project_id") != project_id:
                raise StudyAreaAnchorError("StudyArea project relationship does not match")
            area_payload = area.payload
            if area_payload.get("id", area.entity_id) != resolved_study_area_id:
                raise StudyAreaAnchorError("StudyArea payload ID does not match its state identity")
            if area_payload.get("status") != "CONFIRMED_FOR_EXPLORATION":
                raise StudyAreaAnchorError("active StudyArea is not confirmed for exploration")
            confirmation_event_id = area_payload.get("confirmation_event_id")
            if not isinstance(confirmation_event_id, str):
                raise StudyAreaAnchorError("active StudyArea has no confirmation event")
            confirmation_events = [event for event in store.events(project_id=project_id) if event.event_id == confirmation_event_id]
            if (
                not confirmation_events
                or confirmation_events[0].action != "ConfirmStudyArea"
                or confirmation_events[0].target_id != resolved_study_area_id
                or confirmation_events[0].payload.get("confirmation") != "CONFIRMED_FOR_EXPLORATION"
            ):
                raise StudyAreaAnchorError("active StudyArea confirmation event is missing or mismatched")
            activation_events = [
                event
                for event in store.events(project_id=project_id)
                if event.action == "ActivateStudyArea"
                and event.target_id == project_id
                and event.payload.get("active_study_area_id") == resolved_study_area_id
            ]
            if not activation_events:
                raise StudyAreaAnchorError("active StudyArea activation event is missing or mismatched")
            artifact_id = area_payload.get("geometry_artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id.strip():
                raise StudyAreaAnchorError("active StudyArea has no geometry Artifact")
            artifact = store.current(artifact_id)
            if artifact.entity_type != "Artifact" or artifact.project_id != project_id:
                raise StudyAreaAnchorError("active StudyArea geometry Artifact is not project-scoped")
            artifact_payload = artifact.payload
    except (EntityNotFoundError, StoreError) as exc:
        raise StudyAreaAnchorError(str(exc)) from exc

    crs = _nonempty(area_payload.get("horizontal_crs"), "StudyArea.horizontal_crs")
    units = _nonempty(area_payload.get("units"), "StudyArea.units")
    if crs.upper() != STUDY_AREA_CRS or units.casefold() not in {"m", "metre", "meter", "metres", "meters"}:
        raise StudyAreaAnchorError("active StudyArea CRS/units are not EPSG:28992 metres")
    artifact_crs = _nonempty(artifact_payload.get("crs"), "Artifact.crs")
    if artifact_crs.upper() != crs.upper():
        raise StudyAreaAnchorError("StudyArea and geometry Artifact CRS do not match")
    artifact_uri = _nonempty(artifact_payload.get("uri"), "Artifact.uri")
    artifact_path = Path(artifact_uri)
    if not artifact_path.is_absolute():
        artifact_path = Path(database).resolve().parent / artifact_path
    if not artifact_path.is_file():
        raise StudyAreaAnchorError(f"active geometry Artifact is missing: {artifact_uri}")
    raw_bytes = artifact_path.read_bytes()
    artifact_hash = sha256_bytes(raw_bytes)
    declared_artifact_hash = _sha(artifact_payload.get("sha256"), "Artifact.sha256")
    declared_area_hash = _sha(area_payload.get("artifact_sha256"), "StudyArea.artifact_sha256")
    if artifact_hash != declared_artifact_hash or artifact_hash != declared_area_hash:
        raise ArtifactIntegrityError("active StudyArea geometry Artifact hash mismatch")
    try:
        geojson = json.loads(raw_bytes)
        geometry_mapping = geojson.get("geometry") if geojson.get("type") == "Feature" else geojson.get("geometry", geojson)
        geometry = shape(geometry_mapping)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StudyAreaAnchorError("active geometry Artifact is not valid GeoJSON") from exc
    if geometry.is_empty or not geometry.is_valid:
        raise StudyAreaAnchorError("active StudyArea geometry is empty or invalid")
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise StudyAreaAnchorError("active StudyArea geometry must be Polygon or MultiPolygon")
    declared_geometry_hash = _sha(area_payload.get("geometry_sha256"), "StudyArea.geometry_sha256")
    computed_geometry_hash = canonical_geometry_hash(geometry_mapping)
    if declared_geometry_hash != computed_geometry_hash:
        raise ArtifactIntegrityError("active StudyArea canonical geometry hash mismatch")
    coordinates = list(_numeric_coordinates(geometry_mapping.get("coordinates")))
    if not coordinates:
        raise StudyAreaAnchorError("active StudyArea contains no coordinates")
    observed = (
        min(point[0] for point in coordinates),
        min(point[1] for point in coordinates),
        max(point[0] for point in coordinates),
        max(point[1] for point in coordinates),
    )
    envelope = (
        observed[0] - QUERY_BUFFER_METRES,
        observed[1] - QUERY_BUFFER_METRES,
        observed[2] + QUERY_BUFFER_METRES,
        observed[3] + QUERY_BUFFER_METRES,
    )
    transformer = Transformer.from_crs(crs, "OGC:CRS84", always_xy=True)
    envelope_crs84_points = [
        transformer.transform(envelope[0], envelope[1]),
        transformer.transform(envelope[0], envelope[3]),
        transformer.transform(envelope[2], envelope[1]),
        transformer.transform(envelope[2], envelope[3]),
    ]
    envelope_crs84 = (
        min(point[0] for point in envelope_crs84_points),
        min(point[1] for point in envelope_crs84_points),
        max(point[0] for point in envelope_crs84_points),
        max(point[1] for point in envelope_crs84_points),
    )
    allowed = _rd_new_projected_bounds()
    anchor_status = "VALID"
    anchor_reason = None
    if (
        observed[0] < allowed[0]
        or observed[1] < allowed[1]
        or observed[2] > allowed[2]
        or observed[3] > allowed[3]
    ):
        anchor_status = "OUTSIDE_CRS_AREA_OF_USE"
        anchor_reason = (
            f"observed bbox {list(observed)} is outside the EPSG:28992 area-of-use "
            f"projected bounds {list(allowed)}; a Rotterdam query envelope cannot be inferred"
        )
    else:
        anchor = _load_m4h_anchor(anchor_path)
        if anchor.project_id != project_id:
            raise StudyAreaAnchorError("configured project anchor belongs to another project")
        if anchor.horizontal_crs.upper() != crs.upper() or anchor.units.casefold() not in {"m", "metre", "meter", "metres", "meters"}:
            raise StudyAreaAnchorError("configured project anchor CRS/units do not match the StudyArea")
        anchor_bounds = anchor.anchor_extent
        if (
            observed[0] < anchor_bounds[0]
            or observed[1] < anchor_bounds[1]
            or observed[2] > anchor_bounds[2]
            or observed[3] > anchor_bounds[3]
        ):
            anchor_status = "OUTSIDE_PROJECT_ANCHOR"
            anchor_reason = (
                f"observed bbox {list(observed)} is outside the configured M4H anchor "
                f"{list(anchor_bounds)}; an analysis query envelope cannot be inferred"
            )
    return StudyAreaInspection(
        project_id=project_id,
        study_area_id=resolved_study_area_id,
        geometry_artifact_id=artifact_id,
        geometry_sha256=declared_geometry_hash,
        artifact_sha256=artifact_hash,
        artifact_uri=artifact_uri,
        horizontal_crs=crs,
        units="m",
        vertical_reference=None,
        geometry_type=geometry.geom_type,
        observed_bbox=observed,
        query_envelope=envelope,
        query_envelope_crs84=envelope_crs84,
        query_envelope_axis_order="always_xy",
        pyproj_version=pyproj.__version__,
        anchor_status=anchor_status,
        anchor_reason=anchor_reason,
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _manifest_for(root: Path, files: Sequence[Path]) -> dict[str, Any]:
    entries = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        entries.append({"path": relative, "sha256": sha256_bytes(data), "size_bytes": len(data)})
    return {"schema_version": "m2-a03-package-manifest-v1", "files": entries}


def load_analysis_input_package(package_root: str | Path) -> dict[str, Any]:
    """Reload a package offline and verify every listed byte before use."""

    root = Path(package_root)
    manifest_path = root / "package-manifest.json"
    if not manifest_path.is_file():
        raise ArtifactIntegrityError("package-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = _resolve_under(root, entry["path"])
        if not path.is_file():
            raise ArtifactIntegrityError(f"package file is missing: {entry['path']}")
        data = path.read_bytes()
        if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("size_bytes"):
            raise ArtifactIntegrityError(f"package file integrity mismatch: {entry['path']}")
    package_path = root / "analysis-input-decision-package.json"
    if not package_path.is_file():
        raise ArtifactIntegrityError("analysis-input-decision-package.json is missing")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("status") == APPROVED_PROJECT_DECISION:
        raise AnalysisInputError("analysis package cannot activate a project decision")
    artifacts = {record["id"]: record for record in package.get("artifacts", [])}
    for artifact in artifacts.values():
        validate_artifact_record(artifact, root=root)
    for snapshot in package.get("snapshots", []):
        validate_snapshot_record(snapshot, artifacts=artifacts, root=root)
    for normalized in package.get("normalized_artifacts", []):
        parent_id = normalized.get("raw_parent_artifact_id")
        if parent_id not in artifacts:
            raise ProvenanceValidationError(f"normalized artifact has unknown raw parent: {parent_id}")
        validate_normalized_artifact_record(normalized, raw_artifact=artifacts[parent_id], root=root)
    return package


def _state_artifact_payload(
    record: Mapping[str, Any],
    *,
    package_id: str,
    package_root: Path,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Convert a package-relative Artifact into an authoritative state record."""

    relative_uri = _nonempty(record.get("uri"), "artifact.uri")
    source_uri = _resolve_under(package_root, relative_uri)
    if not source_uri.is_file():
        raise ArtifactIntegrityError(f"published artifact bytes are missing: {relative_uri}")
    absolute_uri = _resolve_under(state_root or package_root, relative_uri)
    payload = dict(record)
    payload["uri"] = str(absolute_uri)
    package_metadata = {
        "package_id": package_id,
        "package_relative_uri": relative_uri,
        "package_root_uri": str((state_root or package_root).resolve()),
    }
    # Validate the domain fields through the typed boundary, then retain the
    # package-resolution metadata in the immutable SQLite payload.  Keeping
    # that metadata outside the legacy Pydantic model preserves byte-stable
    # serialization for existing non-package Artifacts.
    typed_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"raw_parent_artifact_id", "package_id", "package_relative_uri", "package_root_uri"}
    }
    state_payload = Artifact.model_validate(typed_payload).model_dump(mode="json", exclude_none=True)
    state_payload.update(package_metadata)
    if record.get("raw_parent_artifact_id") is not None:
        state_payload["raw_parent_artifact_id"] = record["raw_parent_artifact_id"]
    return state_payload


def _package_state_batch(
    package: Mapping[str, Any],
    *,
    package_root: Path,
    state_root: Path | None = None,
    actor: str,
    revision: str,
    target_type: str = "AnalysisInputDecisionPackage",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Prepare typed state and deterministic ledger specifications for a package."""

    package_id = _nonempty(package.get("package_id"), "package_id")
    project_id = _nonempty(package.get("project_id"), "project_id")
    raw_artifacts = list(package.get("artifacts", []))
    normalized_artifacts = list(package.get("normalized_artifacts", []))
    all_records = raw_artifacts + normalized_artifacts
    seen_ids: set[str] = set()
    entities: list[dict[str, Any]] = []
    for record in all_records:
        artifact_id = _nonempty(record.get("id"), "artifact.id")
        if artifact_id in seen_ids:
            raise ProvenanceValidationError(f"duplicate artifact identity in package: {artifact_id}")
        seen_ids.add(artifact_id)
        payload = _state_artifact_payload(
            record,
            package_id=package_id,
            package_root=package_root,
            state_root=state_root,
        )
        if payload.get("project_id") != project_id:
            raise ProvenanceValidationError(f"artifact project mismatch: {artifact_id}")
        artifact_event_id = "m2-a03-artifact-" + hashlib.sha256(artifact_id.encode()).hexdigest()[:24]
        entities.append(
            {
                "entity_id": artifact_id,
                "entity_type": "Artifact",
                "project_id": project_id,
                "payload": payload,
                "event_id": artifact_event_id,
                "actor": actor,
                "action": "RecordArtifact",
                "reason": f"M2-A03 {revision} published source artifact",
                "resulting_refs": (artifact_id,),
                "event_payload": {
                    "package_id": package_id,
                    "package_relative_uri": payload.get("package_relative_uri"),
                    "sha256": payload.get("sha256"),
                },
            }
        )

    for record in package.get("snapshots", []):
        snapshot_id = _nonempty(record.get("id"), "snapshot.id")
        raw_id = _nonempty(record.get("raw_artifact_id"), "snapshot.raw_artifact_id")
        normalized_id = record.get("normalized_artifact_id")
        if raw_id not in seen_ids:
            raise ProvenanceValidationError(f"snapshot references unknown raw artifact: {raw_id}")
        if normalized_id is not None and normalized_id not in seen_ids:
            raise ProvenanceValidationError(f"snapshot references unknown normalized artifact: {normalized_id}")
        snapshot_payload = DatasetSnapshot.model_validate(
            {
                "id": snapshot_id,
                "project_id": project_id,
                "source": record.get("source_url", record.get("source")),
                "query": record.get("query"),
                "retrieved_at": record.get("retrieved_at"),
                "publisher": record.get("publisher"),
                "license": record.get("license", record.get("licence")),
                "version": record.get("version"),
                "sha256": record.get("sha256"),
                "raw_artifact_id": raw_id,
                "normalized_artifact_id": normalized_id,
            }
        ).model_dump(mode="json")
        snapshot_event_id = "m2-a03-snapshot-record-" + hashlib.sha256(snapshot_id.encode()).hexdigest()[:24]
        entities.append(
            {
                "entity_id": snapshot_id,
                "entity_type": "DatasetSnapshot",
                "project_id": project_id,
                "payload": snapshot_payload,
                "event_id": snapshot_event_id,
                "actor": actor,
                "action": "RecordDatasetSnapshot",
                "reason": f"M2-A03 {revision} published source snapshot",
                "resulting_refs": (snapshot_id,),
                "event_payload": {"package_id": package_id, "raw_artifact_id": raw_id},
            }
        )

    event_id = _nonempty(package.get("ledger_event_id"), "package.ledger_event_id")
    study_area_id = package.get("study_area", {}).get("id")
    events: list[dict[str, Any]] = [
        {
            "event_id": event_id,
            "timestamp": package.get("created_at") or utc_now(),
            "actor": actor,
            "action": "SnapshotObservation",
            "target_id": package_id,
            "target_type": target_type,
            "project_id": project_id,
            "prior_status": "UNOBSERVED",
            "changed_refs": (study_area_id,) if isinstance(study_area_id, str) else (),
            "reason": f"M2-A03 {revision} source review package",
            "resulting_refs": (package_id,),
            "payload": {
                "status": package.get("status"),
                "study_area_id": study_area_id,
                "snapshot_count": len(package.get("snapshots", [])),
            },
        }
    ]
    return entities, events


def _stale_package_ids(
    output: Path,
    *,
    package_id: str,
    inspection: StudyAreaInspection | None,
) -> tuple[str, ...]:
    if inspection is None:
        return ()
    stale: list[str] = []
    for package_path in sorted(output.glob("run-*/analysis-input-decision-package.json")):
        try:
            prior = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if prior.get("package_id") == package_id:
            continue
        if package_is_stale(prior, current_geometry_sha256=inspection.geometry_sha256):
            stale.append(str(prior.get("package_id") or package_path.parent.name))
    return tuple(stale)


def _append_stale_event_specs(
    events: list[dict[str, Any]],
    *,
    database: str | Path,
    prior_ids: Iterable[Any],
    project_id: str,
    timestamp: str,
    changed_refs: tuple[str, ...],
    reason: str,
    resulting_package_id: str,
) -> None:
    """Append stale markers while preserving already-recorded immutable events.

    Historical M2-A02 activation may already have marked a blocked package
    stale with a richer payload than this builder emits.  That existing event
    is authoritative and must be treated as satisfied rather than rewritten.
    A conflicting event identity still fails closed.
    """

    with ProjectStateStore(database) as store:
        existing_events = {event.event_id: event for event in store.events()}
    for prior_id in prior_ids:
        prior_text = str(prior_id)
        stale_event_id = "m2-a03-mark-stale-" + hashlib.sha256(prior_text.encode()).hexdigest()[:24]
        existing = existing_events.get(stale_event_id)
        if existing is not None:
            if (
                existing.action != "MarkStale"
                or existing.target_id != prior_text
                or existing.target_type != "AnalysisInputDecisionPackage"
                or existing.project_id != project_id
                or existing.payload.get("status") != "STALE"
            ):
                raise ProvenanceValidationError(
                    f"stale event identity conflicts with an existing immutable event: {stale_event_id}"
                )
            continue
        events.append(
            {
                "event_id": stale_event_id,
                "timestamp": timestamp,
                "actor": "m2-a03-builder",
                "action": "MarkStale",
                "target_id": prior_text,
                "target_type": "AnalysisInputDecisionPackage",
                "project_id": project_id,
                "prior_status": None,
                "changed_refs": changed_refs,
                "reason": reason,
                "resulting_refs": (resulting_package_id,),
                "payload": {"status": "STALE", "superseded_by_package_id": resulting_package_id},
            }
        )


def _package_tree_signature(root: Path) -> tuple[tuple[str, str, int], ...]:
    """Return a complete file signature, including files outside the manifest."""

    entries: list[tuple[str, str, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            entries.append((path.relative_to(root).as_posix(), sha256_bytes(data), len(data)))
    return tuple(entries)


def _publish_without_replacing(stage: Path, target: Path) -> None:
    """Atomically claim a target name without replacing a peer directory.

    The lock directory is an exclusive filesystem claim.  It is removed only
    when this invocation created it; the target itself is never removed here.
    """

    lock = target.with_name(f".{target.name}.publish-lock")
    owner = uuid.uuid4().hex
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise FileExistsError(f"package publication is already in progress: {target}") from exc
    try:
        (lock / "owner").write_text(owner + "\n", encoding="utf-8")
        if target.exists():
            raise FileExistsError(f"package target already exists: {target}")
        os.replace(stage, target)
    finally:
        try:
            if (lock / "owner").read_text(encoding="utf-8").strip() == owner:
                shutil.rmtree(lock, ignore_errors=True)
        except (OSError, UnicodeError):
            pass


def _reconcile_competing_package(
    *,
    stage: Path,
    target: Path,
    expected_package_id: str,
    validator: Any,
) -> dict[str, Any] | None:
    """Accept a peer publication only when every byte is identical."""

    if not target.is_dir() or not stage.is_dir():
        return None
    try:
        staged = validator(stage)
        existing = validator(target)
    except Exception:
        return None
    if staged.get("package_id") != expected_package_id or existing.get("package_id") != expected_package_id:
        return None
    if _package_tree_signature(stage) != _package_tree_signature(target):
        return None
    return existing


def build_m2a03_package(
    database: str | Path,
    output_root: str | Path,
    *,
    project_id: str = PROJECT_ID,
    study_area_id: str | None = None,
    append_ledger: bool = True,
    created_at: str | None = None,
    package_revision: str | None = None,
    fetcher: Any | None = None,
    package_publisher: Any | None = None,
    package_validator: Any | None = None,
    commit_hook: Any | None = None,
) -> Path:
    """Build and atomically publish the v5 source-review package.

    Source adapters run only after the active StudyArea has passed all gates.
    They write into a private staging directory; a source or provenance
    failure publishes only a BLOCKED package with precise evidence and never a
    partial set of apparently valid snapshots.
    """

    from .m2a03_sources import SourceAcquisitionError, acquire_mandatory_sources

    created = _aware_timestamp(created_at or utc_now(), "created_at")
    revision = _nonempty(package_revision or "r03", "package_revision")
    resolved_study_area_id = study_area_id
    if resolved_study_area_id is None:
        try:
            with ProjectStateStore(database) as store:
                pointer = store.current(project_id).payload.get("active_study_area_id")
                if isinstance(pointer, str) and pointer.strip():
                    resolved_study_area_id = pointer.strip()
        except (EntityNotFoundError, StoreError):
            pass

    try:
        inspection = inspect_active_study_area(database, project_id=project_id, study_area_id=study_area_id)
        resolved_study_area_id = inspection.study_area_id
        inspection_payload = inspection.as_dict()
        blocked = inspection.anchor_status != "VALID"
        failure = None if not blocked else {
            "code": "STUDY_AREA_GEOGRAPHIC_ANCHOR_INVALID",
            "message": inspection.anchor_reason,
            "external_requests_executed": False,
            "required_human_action": "Redraw or explicitly georeference the active StudyArea in EPSG:28992 before M2-A03 acquisition.",
        }
    except (AnalysisInputError, OSError, ValueError) as exc:
        inspection = None
        inspection_payload = {
            "project_id": project_id,
            "study_area_id": resolved_study_area_id,
            "query_envelope_crs": STUDY_AREA_CRS,
            "query_buffer_m": QUERY_BUFFER_METRES,
        }
        blocked = True
        failure = {
            "code": "ACTIVE_STUDY_AREA_VALIDATION_FAILED",
            "message": str(exc),
            "external_requests_executed": False,
            "required_human_action": "Repair and re-confirm the active StudyArea before M2-A03 acquisition.",
        }

    package_id = f"m2-a03-analysis-input-{resolved_study_area_id or 'unresolved'}-{revision}"
    run_id = f"run-{resolved_study_area_id or 'unresolved'}-{revision}"
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    package_dir = output / run_id

    def commit_existing_package(existing_package: Mapping[str, Any]) -> None:
        """Reconcile an already published package into SQLite idempotently."""

        if not append_ledger or not existing_package.get("ledger_event_id"):
            return
        entities, events = _package_state_batch(
            existing_package,
            package_root=package_dir,
            state_root=package_dir,
            actor="m2-a03-builder",
            revision=revision,
        )
        _append_stale_event_specs(
            events,
            database=database,
            prior_ids=existing_package.get("stale_prior_packages", []),
            project_id=project_id,
            timestamp=existing_package.get("created_at") or utc_now(),
            changed_refs=(existing_package.get("study_area", {}).get("id"),),
            reason="Active StudyArea supersedes the package input geometry",
            resulting_package_id=existing_package["package_id"],
        )
        with ProjectStateStore(database) as store:
            store.commit_batch(entities=entities, events=events)

    if package_dir.exists():
        manifest = package_dir / "package-manifest.json"
        if not manifest.is_file():
            raise FileExistsError(f"refusing to reuse incomplete package directory: {package_dir}")
        existing_package = load_analysis_input_package(package_dir)
        commit_existing_package(existing_package)
        return package_dir

    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=output))
    source_bundle = None
    source_failure: dict[str, Any] | None = None
    if not blocked and inspection is not None:
        try:
            source_bundle = acquire_mandatory_sources(
                package_root=stage,
                project_id=project_id,
                created_at=created,
                observed_bbox=inspection.observed_bbox,
                fetcher=fetcher,
                package_namespace=package_id,
            )
        except (SourceAcquisitionError, OSError, ValueError, KeyError, TypeError) as exc:
            blocked = True
            request_receipts = list(getattr(exc, "request_records", ()) or ())
            source_failure = {
                "code": "MANDATORY_SOURCE_ACQUISITION_FAILED",
                "message": str(exc),
                "external_requests_executed": any(bool(record.get("request_sent")) for record in request_receipts),
                "failed_source_id": getattr(exc, "source_id", None),
                "source_request_receipts": request_receipts,
                "staged_artifacts_discarded": True,
                "required_human_action": "Resolve the source, pagination, licence, metadata, or EPW gate and rerun this revision.",
            }
            shutil.rmtree(stage, ignore_errors=True)
            stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=output))
    if source_failure is not None:
        failure = source_failure

    if source_bundle is not None:
        source_requests = list(source_bundle.request_records)
        raw_artifacts = list(source_bundle.artifacts)
        normalized_artifacts = list(source_bundle.normalized_artifacts)
        snapshots = list(source_bundle.snapshots)
        origin_candidates = source_bundle.origin_inventory
        grocery_inventory = source_bundle.grocery_inventory
        weather_candidates = source_bundle.weather_candidates
        source_status = "OBSERVED"
        data_gaps: list[dict[str, Any]] = [
            {"id": "M2-A03-GAP-001", "status": "UNSELECTED", "topic": "destination_taxonomy", "detail": "Raw grocery tags are inventoried separately; no destination taxonomy is selected."},
            {"id": "M2-A03-GAP-002", "status": "UNSELECTED", "topic": "origin_denominator", "detail": "Origin candidates are observations only; no denominator or access rule is selected."},
            {"id": "M2-A03-GAP-003", "status": "UNSELECTED", "topic": "network_policy", "detail": "OSM ways/nodes are candidate observations only; no pedestrian network policy is selected."},
            {"id": "M2-A03-GAP-004", "status": "UNSELECTED", "topic": "weather_selection", "detail": "EPW candidates are compared; no weather file is selected and no climate result is computed."},
            {"id": "M2-A03-GAP-005", "status": "UNAVAILABLE", "topic": "vertical_reference", "detail": "Source observations do not establish a vertical reference for the StudyArea."},
        ]
    else:
        source_requests = list((source_failure or {}).get("source_request_receipts") or [])
        if not source_requests:
            source_requests = [
                {"source_id": "pdok-bag", "status": "NOT_ATTEMPTED_BLOCKED", "request_sent": False, "response_received": False, "validation_status": "NOT_RUN", "required_layers": ["pand"]},
                {"source_id": "pdok-bgt", "status": "NOT_ATTEMPTED_BLOCKED", "request_sent": False, "response_received": False, "validation_status": "NOT_RUN", "required_layers": ["wegdeel", "waterdeel"]},
                {"source_id": "osm", "status": "NOT_ATTEMPTED_BLOCKED", "request_sent": False, "response_received": False, "validation_status": "NOT_RUN", "required_layers": ["pedestrian source ways/nodes", "grocery POIs"]},
                {"source_id": "epw", "status": "NOT_ATTEMPTED_BLOCKED", "request_sent": False, "response_received": False, "validation_status": "NOT_RUN", "required_layers": ["Rotterdam-region candidates"]},
            ]
        raw_artifacts = []
        normalized_artifacts = []
        snapshots = []
        origin_candidates = {"status": "UNAVAILABLE", "reason": "No complete mandatory source package was published.", "policy_status": PROPOSED_PROJECT_DECISION}
        grocery_inventory = {"status": "UNAVAILABLE", "reason": "No complete OSM query was published.", "policy_status": PROPOSED_PROJECT_DECISION}
        failed_source_id = (source_failure or {}).get("failed_source_id")
        weather_candidates = {"status": "VALIDATION_FAILED" if failed_source_id == "epw" else "UNAVAILABLE", "reason": (failure or {}).get("message") if failed_source_id == "epw" else "No complete EPW candidate package was published.", "selected_candidate": None, "policy_status": PROPOSED_PROJECT_DECISION}
        source_status = "BLOCKED"
        data_gaps = [
            {"id": "M2-A03-GAP-001", "status": "BLOCKED", "topic": "study_area_or_source_gate", "detail": (failure or {}).get("message") or "Mandatory source acquisition did not complete."},
            {"id": "M2-A03-GAP-002", "status": "UNAVAILABLE", "topic": "source_snapshots", "detail": "No historical snapshot was substituted for the active v5 run."},
        ]

    policies = {
        "destination_taxonomy": {"status": PROPOSED_PROJECT_DECISION, "human_approval_required": True, "raw_tags_kept_separate": ["shop=supermarket", "shop=convenience", "shop=grocery"], "inclusion_rule": "UNSELECTED_PROPOSAL_ONLY", "observed_counts": grocery_inventory.get("counts_by_shop_tag")},
        "pedestrian_network": {"status": PROPOSED_PROJECT_DECISION, "human_approval_required": True, "candidate_rule": "OSM pedestrian ways/nodes with source tags preserved", "cost": "metric_length_m_candidate_only"},
        "origin_denominator": {"status": PROPOSED_PROJECT_DECISION, "human_approval_required": True, "candidate_rule": "fixed public-access reference points; denominator semantics unselected"},
        "weather_selection": {"status": PROPOSED_PROJECT_DECISION, "human_approval_required": True, "selected_candidate": None},
    }
    package = {
        "schema_version": "m2-a03-analysis-input-decision-package-v1",
        "package_id": package_id,
        "package_revision": revision,
        "status": "READY_FOR_HUMAN_REVIEW" if source_bundle is not None else PACKAGE_STATUS_BLOCKED,
        "created_at": created,
        "project_id": project_id,
        "study_area": {"id": resolved_study_area_id, "geometry_sha256": inspection.geometry_sha256 if inspection else None, "artifact_sha256": inspection.artifact_sha256 if inspection else None, "horizontal_crs": STUDY_AREA_CRS, "units": STUDY_AREA_UNITS},
        "query_envelope": inspection_payload,
        "source_requests": source_requests,
        "artifacts": raw_artifacts,
        "normalized_artifacts": normalized_artifacts,
        "snapshots": snapshots,
        "origin_candidates": origin_candidates,
        "destination_candidates": grocery_inventory,
        "raw_grocery_tag_inventory": grocery_inventory,
        "network_manifest": source_bundle.network_manifest if source_bundle is not None else {"status": "UNAVAILABLE"},
        "weather_candidates": weather_candidates,
        "proposed_policies": policies,
        "data_gaps": data_gaps,
        "failure": failure,
        "no_accessibility_result": True,
        "no_climate_result": True,
        "no_approval_event": True,
        "ledger_event_id": (
            "m2-a03-snapshot-" + hashlib.sha256(package_id.encode()).hexdigest()[:24]
            if append_ledger
            else None
        ),
        "stale_prior_packages": [],
    }
    package["stale_prior_packages"] = list(
        _stale_package_ids(output, package_id=package_id, inspection=inspection)
    )
    package["review_artifacts"] = {"source_and_integrity_manifest": "source-and-integrity-manifest.json", "crs_unit_vertical_manifest": "crs-unit-vertical-manifest.json", "data_gap_register": "data-gap-register.json", "origin_candidate_inventory": "origin-candidate-inventory.json", "raw_grocery_tag_inventory": "raw-grocery-tag-inventory.json", "proposed_destination_taxonomy": "proposed-destination-taxonomy.json", "proposed_network_policy": "proposed-network-policy.json", "proposed_origin_policy": "proposed-origin-policy.json", "weather_candidate_comparison": "weather-candidate-comparison.json", "compact_review_table": "compact-review-table.json"}

    request = {"schema_version": "m2-a03-request-v1", "package_id": package_id, "project_id": project_id, "study_area_id": resolved_study_area_id, "created_at": created, "declared_crs": STUDY_AREA_CRS, "declared_units": STUDY_AREA_UNITS, "query_buffer_m": QUERY_BUFFER_METRES, "source_requests": source_requests, "no_live_source_substitution": True}
    _write_json(stage / "request.json", request)
    _write_json(stage / "failure-evidence.json", {"package_id": package_id, "inspection": inspection_payload, "failure": failure})
    source_manifest = {"schema_version": "m2-a03-source-integrity-manifest-v1", "status": package["status"], "raw_artifacts": raw_artifacts, "normalized_artifacts": normalized_artifacts, "snapshots": snapshots, "source_requests": source_requests, "no_live_source_substitution": True}
    _write_json(stage / "source-and-integrity-manifest.json", source_manifest)
    _write_json(stage / "crs-unit-vertical-manifest.json", {"horizontal_crs": STUDY_AREA_CRS, "units": STUDY_AREA_UNITS, "vertical_reference": None, "query_envelope_crs": inspection_payload.get("query_envelope_crs", STUDY_AREA_CRS), "query_buffer_m": QUERY_BUFFER_METRES, "observed_bbox": inspection_payload.get("observed_bbox"), "query_envelope": inspection_payload.get("query_envelope"), "query_envelope_crs84": inspection_payload.get("query_envelope_crs84"), "query_envelope_axis_order": inspection_payload.get("query_envelope_axis_order"), "pyproj_version": inspection_payload.get("pyproj_version"), "anchor_status": inspection_payload.get("anchor_status", "UNVERIFIED"), "derivation": "axis-aligned observed EPSG:28992 bbox expanded by 1,200 m on every side; transformed to OGC:CRS84 with always_xy"})
    _write_json(stage / "data-gap-register.json", {"gaps": data_gaps})
    _write_json(stage / "origin-candidate-inventory.json", origin_candidates)
    _write_json(stage / "raw-grocery-tag-inventory.json", grocery_inventory)
    _write_json(stage / "proposed-destination-taxonomy.json", policies["destination_taxonomy"])
    _write_json(stage / "proposed-network-policy.json", policies["pedestrian_network"])
    _write_json(stage / "proposed-origin-policy.json", policies["origin_denominator"])
    _write_json(stage / "weather-candidate-comparison.json", weather_candidates)
    _write_json(stage / "compact-review-table.json", {"status": package["status"], "map_status": "NOT_RENDERED", "rows": [{"item": "active StudyArea geographic anchor", "status": inspection_payload.get("anchor_status", "UNVERIFIED"), "evidence": "failure-evidence.json"}, {"item": "PDOK BAG/BGT", "status": "OBSERVED" if source_bundle is not None else "NOT_ATTEMPTED_BLOCKED", "evidence": "source-and-integrity-manifest.json"}, {"item": "OSM ways/nodes/grocery POIs", "status": "OBSERVED" if source_bundle is not None else "NOT_ATTEMPTED_BLOCKED", "evidence": "source-and-integrity-manifest.json"}, {"item": "Rotterdam-region EPW candidates", "status": weather_candidates.get("status"), "evidence": "weather-candidate-comparison.json"}, {"item": "origin/destination/network/weather policy", "status": PROPOSED_PROJECT_DECISION, "evidence": "proposed-*.json"}]})

    # Validate all records while still in staging. A normalized artifact always
    # names an existing raw parent, and no state row exists until this succeeds.
    artifacts_by_id = {record["id"]: record for record in raw_artifacts}
    for record in raw_artifacts:
        validate_artifact_record(record, root=stage)
    for record in normalized_artifacts:
        parent = artifacts_by_id.get(record.get("raw_parent_artifact_id"))
        if parent is None:
            raise ProvenanceValidationError(f"normalized artifact has unknown raw parent: {record.get('raw_parent_artifact_id')}")
        validate_normalized_artifact_record(record, raw_artifact=parent, root=stage)
    for record in snapshots:
        validate_snapshot_record(record, artifacts=artifacts_by_id, root=stage)

    _write_json(stage / "analysis-input-decision-package.json", package)
    files = [path for path in stage.rglob("*") if path.name != "package-manifest.json" and path.is_file()]
    _write_json(stage / "package-manifest.json", _manifest_for(stage, files))
    published = False

    def raise_publication_failure(exc: BaseException) -> None:
        # The target may belong to a concurrent publisher or may contain a
        # package published before a later verification/SQLite failure.  Never
        # remove it from a failure path; only this invocation's private stage
        # is safe to clean up.
        shutil.rmtree(stage, ignore_errors=True)
        failure_path = output / f"{run_id}.publication-failure.json"
        try:
            _write_json(
                failure_path,
                {
                    "run_id": run_id,
                    "package_id": package_id,
                    "retryable": True,
                    "published_package_available": published,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        except OSError:
            pass
        raise AnalysisInputPublicationError(
            f"M2-A03 package publication/state commit failed for {package_id}; retry is safe: {exc}"
        ) from exc

    try:
        (package_validator or load_analysis_input_package)(stage)
        if not append_ledger:
            (package_publisher or _publish_without_replacing)(stage, package_dir)
            (package_validator or load_analysis_input_package)(package_dir)
            published = True
            return package_dir

        entities, events = _package_state_batch(
            package,
            package_root=stage,
            state_root=package_dir,
            actor="m2-a03-builder",
            revision=revision,
        )
        _append_stale_event_specs(
            events,
            database=database,
            prior_ids=package["stale_prior_packages"],
            project_id=project_id,
            timestamp=created,
            changed_refs=(resolved_study_area_id,) if resolved_study_area_id else (),
            reason="Active StudyArea v5 supersedes the package input geometry",
            resulting_package_id=package_id,
        )

        def publish_and_verify() -> None:
            nonlocal published
            publisher = package_publisher or _publish_without_replacing
            publisher(stage, package_dir)
            (package_validator or load_analysis_input_package)(package_dir)
            published = True
            if commit_hook is not None:
                commit_hook()

        with ProjectStateStore(database) as store:
            store.commit_batch(entities=entities, events=events, before_commit=publish_and_verify)
    except BaseException as exc:
        if isinstance(exc, FileExistsError) and package_dir.exists():
            competing = _reconcile_competing_package(
                stage=stage,
                target=package_dir,
                expected_package_id=package_id,
                validator=load_analysis_input_package,
            )
            if competing is not None:
                shutil.rmtree(stage, ignore_errors=True)
                commit_existing_package(competing)
                return package_dir
        raise_publication_failure(exc)
    return package_dir


SPATIAL_PACKAGE_SCHEMA = "m2-a03-spatial-input-decision-package-v1"
SPATIAL_TRACK = "SPATIAL_INPUT"
SPATIAL_READY_STATUS = "READY_FOR_HUMAN_REVIEW"
WEATHER_GATE_REFERENCE = {
    "status": "SEMANTICS_UNRESOLVED",
    "required_for": "WEEK_6",
    "blocks_spatial_track": False,
    "evidence_refs": ["R09", "R09-R01"],
}
_SPATIAL_NOT_ATTEMPTED = (
    {"source_id": "pdok-bag-pand", "required_layers": ["pand"]},
    {"source_id": "pdok-bgt-wegdeel", "required_layers": ["wegdeel"]},
    {"source_id": "pdok-bgt-waterdeel", "required_layers": ["waterdeel"]},
    {"source_id": "osm-overpass", "required_layers": ["pedestrian source ways/nodes", "grocery POIs"]},
)


def spatial_run_directory(output_root: str | Path, study_area_id: str, revision: str) -> Path:
    """Return the immutable directory reserved for one spatial revision."""

    return Path(output_root) / f"run-{study_area_id}-spatial-{revision}"


def historical_run_directory(output_root: str | Path, study_area_id: str, revision: str) -> Path:
    return Path(output_root) / f"run-{study_area_id}-{revision}"


def spatial_revision_is_used(output_root: str | Path, study_area_id: str, revision: str) -> Path | None:
    """A revision token is used when either the spatial or historical run exists."""

    for path in (
        spatial_run_directory(output_root, study_area_id, revision),
        historical_run_directory(output_root, study_area_id, revision),
    ):
        if path.exists():
            return path
    return None


def _unavailable_inventory(reason: str) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "reason": reason,
        "count": None,
        "records": None,
        "policy_status": PROPOSED_PROJECT_DECISION,
    }


def _completed_inventory(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a completed empty observation distinct from an unavailable one."""

    published = dict(inventory)
    records = published.get("records")
    counts = published.get("counts_by_shop_tag")
    if published.get("status") == "UNAVAILABLE":
        published["count"] = None
        return published
    if isinstance(records, list):
        published["count"] = len(records)
        if len(records) == 0:
            published["status"] = "EMPTY"
    elif isinstance(counts, Mapping):
        total = sum(int(value) for value in counts.values())
        published["count"] = total
        if total == 0:
            published["status"] = "EMPTY"
    return published


def _assert_spatial_package_has_no_weather(package: Mapping[str, Any], root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.casefold() in {".epw", ".zip"}:
            raise AnalysisInputError(f"spatial package contains a weather file: {path.name}")
    for record in list(package.get("artifacts", [])) + list(package.get("normalized_artifacts", [])):
        artifact_type = str(record.get("type") or "")
        uri = str(record.get("uri") or "")
        if artifact_type in {"epw_weather_file", "raw_weather_archive"} or uri.endswith((".epw", ".zip")):
            raise AnalysisInputError("spatial package contains a weather artifact")
    for snapshot in package.get("snapshots", []):
        identity = json.dumps(snapshot).lower()
        if "weather" in identity or "epw" in identity or identity.endswith(".zip"):
            raise AnalysisInputError("spatial package contains a weather DatasetSnapshot")
    if "weather_candidates" in package or "weather_selection" in package.get("proposed_policies", {}):
        raise AnalysisInputError("spatial package contains a weather-selection policy")


def load_m2a03_spatial_package(package_root: str | Path) -> dict[str, Any]:
    """Reload a spatial package and reject byte drift or a missing raw parent."""

    root = Path(package_root)
    manifest_path = root / "package-manifest.json"
    if not manifest_path.is_file():
        raise ArtifactIntegrityError("package-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = _resolve_under(root, entry["path"])
        if not path.is_file():
            raise ArtifactIntegrityError(f"package file is missing: {entry['path']}")
        data = path.read_bytes()
        if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("size_bytes"):
            raise ArtifactIntegrityError(f"package file integrity mismatch: {entry['path']}")
    package_path = root / "spatial-input-decision-package.json"
    if not package_path.is_file():
        raise ArtifactIntegrityError("spatial-input-decision-package.json is missing")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("schema_version") != SPATIAL_PACKAGE_SCHEMA or package.get("track") != SPATIAL_TRACK:
        raise ProvenanceValidationError("package is not a spatial input decision package")
    _assert_spatial_package_has_no_weather(package, root)
    artifacts = {record["id"]: record for record in package.get("artifacts", [])}
    for artifact in artifacts.values():
        validate_artifact_record(artifact, root=root)
    for normalized in package.get("normalized_artifacts", []):
        parent_id = normalized.get("raw_parent_artifact_id")
        if parent_id not in artifacts:
            raise ProvenanceValidationError(f"normalized artifact has unknown raw parent: {parent_id}")
        validate_normalized_artifact_record(normalized, raw_artifact=artifacts[parent_id], root=root)
    for snapshot in package.get("snapshots", []):
        validate_snapshot_record(snapshot, artifacts=artifacts, root=root)
    return package


def require_spatial_package_use(
    package: Mapping[str, Any],
    *,
    active_geometry_sha256: str,
    active_study_area_id: str | None = None,
) -> dict[str, Any]:
    """Block use when the StudyArea binding is stale or the CRS is not metric RD."""

    study_area = package.get("study_area") if isinstance(package.get("study_area"), Mapping) else {}
    crs_record = package.get("crs_record") if isinstance(package.get("crs_record"), Mapping) else {}
    crs = crs_record.get("horizontal_crs") or study_area.get("horizontal_crs")
    canonical = ensure_metric_crs(str(crs))
    if canonical != STUDY_AREA_CRS:
        raise AnalysisInputError(f"spatial package CRS is not {STUDY_AREA_CRS}: {canonical}")
    if study_area.get("geometry_sha256") != active_geometry_sha256:
        raise StudyAreaAnchorError("spatial package StudyArea binding is stale")
    if active_study_area_id is not None and study_area.get("id") != active_study_area_id:
        raise StudyAreaAnchorError("spatial package StudyArea binding is stale")
    if package.get("status") != SPATIAL_READY_STATUS:
        raise AnalysisInputError("spatial package is not ready for use")
    weather_gate = package.get("weather_gate") if isinstance(package.get("weather_gate"), Mapping) else {}
    if weather_gate.get("blocks_spatial_track") is not False:
        raise AnalysisInputError("weather gate must not block the spatial track")
    return dict(package)


def _spatial_not_attempted_receipts() -> list[dict[str, Any]]:
    return [
        {
            "source_id": spec["source_id"],
            "required_layers": list(spec["required_layers"]),
            "status": "NOT_ATTEMPTED_BLOCKED",
            "request_sent": False,
            "response_received": False,
            "complete_response": False,
            "validation_status": "NOT_RUN",
        }
        for spec in _SPATIAL_NOT_ATTEMPTED
    ]


def build_m2a03_spatial_package(
    database: str | Path,
    output_root: str | Path,
    *,
    project_id: str = PROJECT_ID,
    study_area_id: str | None = None,
    package_revision: str | None = None,
    append_ledger: bool = True,
    created_at: str | None = None,
    fetcher: Any | None = None,
    package_publisher: Any | None = None,
    package_validator: Any | None = None,
    commit_hook: Any | None = None,
) -> Path:
    """Publish one spatial input package. Weather acquisition is not attempted."""

    from .m2a03_sources import SourceAcquisitionError, acquire_spatial_sources

    if package_revision is None or not str(package_revision).strip():
        raise AnalysisInputError("spatial package revision is required and must be unused")
    revision = _nonempty(str(package_revision), "package_revision")
    created = _aware_timestamp(created_at or utc_now(), "created_at")
    resolved_study_area_id = study_area_id
    if resolved_study_area_id is None:
        try:
            with ProjectStateStore(database) as store:
                pointer = store.current(project_id).payload.get("active_study_area_id")
                if isinstance(pointer, str) and pointer.strip():
                    resolved_study_area_id = pointer.strip()
        except (EntityNotFoundError, StoreError):
            pass
    try:
        inspection = inspect_active_study_area(database, project_id=project_id, study_area_id=study_area_id)
        resolved_study_area_id = inspection.study_area_id
        inspection_payload = inspection.as_dict()
        blocked = inspection.anchor_status != "VALID"
        failure = None if not blocked else {
            "code": "STUDY_AREA_GEOGRAPHIC_ANCHOR_INVALID",
            "message": inspection.anchor_reason,
            "external_requests_executed": False,
        }
    except (AnalysisInputError, OSError, ValueError) as exc:
        inspection = None
        inspection_payload = {
            "project_id": project_id,
            "study_area_id": resolved_study_area_id,
            "query_envelope_crs": STUDY_AREA_CRS,
            "query_buffer_m": QUERY_BUFFER_METRES,
        }
        blocked = True
        failure = {
            "code": "ACTIVE_STUDY_AREA_VALIDATION_FAILED",
            "message": str(exc),
            "external_requests_executed": False,
        }
    if not resolved_study_area_id:
        raise AnalysisInputError("spatial package requires a resolved StudyArea")
    package_id = f"m2-a03-spatial-input-{resolved_study_area_id}-{revision}"
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    package_dir = spatial_run_directory(output, resolved_study_area_id, revision)

    def commit_existing(existing_package: Mapping[str, Any]) -> None:
        if not append_ledger or not existing_package.get("ledger_event_id"):
            return
        entities, events = _package_state_batch(
            existing_package,
            package_root=package_dir,
            state_root=package_dir,
            actor="m2-a03-spatial-builder",
            revision=revision,
            target_type="SpatialInputDecisionPackage",
        )
        with ProjectStateStore(database) as store:
            store.commit_batch(entities=entities, events=events)

    if package_dir.exists():
        manifest = package_dir / "package-manifest.json"
        if not manifest.is_file():
            raise FileExistsError(f"refusing to reuse incomplete spatial package directory: {package_dir}")
        existing_package = load_m2a03_spatial_package(package_dir)
        commit_existing(existing_package)
        return package_dir

    stage = Path(tempfile.mkdtemp(prefix=f".{package_dir.name}.", dir=output))
    source_bundle = None
    source_failure: dict[str, Any] | None = None
    if not blocked and inspection is not None:
        try:
            source_bundle = acquire_spatial_sources(
                package_root=stage,
                project_id=project_id,
                created_at=created,
                observed_bbox=inspection.observed_bbox,
                fetcher=fetcher,
                package_namespace=package_id,
            )
        except (SourceAcquisitionError, OSError, ValueError, KeyError, TypeError) as exc:
            blocked = True
            request_receipts = list(getattr(exc, "request_records", ()) or ())
            source_failure = {
                "code": "SPATIAL_SOURCE_ACQUISITION_FAILED",
                "message": str(exc),
                "external_requests_executed": any(bool(record.get("request_sent")) for record in request_receipts),
                "failed_source_id": getattr(exc, "source_id", None),
                "source_request_receipts": request_receipts,
                "staged_artifacts_discarded": True,
            }
            shutil.rmtree(stage, ignore_errors=True)
            stage = Path(tempfile.mkdtemp(prefix=f".{package_dir.name}.", dir=output))
    if source_failure is not None:
        failure = source_failure

    if source_bundle is not None:
        source_requests = list(source_bundle.request_records)
        raw_artifacts = list(source_bundle.artifacts)
        normalized_artifacts = list(source_bundle.normalized_artifacts)
        snapshots = list(source_bundle.snapshots)
        origin_inventory = _completed_inventory(source_bundle.origin_inventory)
        grocery_inventory = _completed_inventory(source_bundle.grocery_inventory)
        network_inventory = dict(source_bundle.network_manifest)
        source_status = SPATIAL_READY_STATUS
        data_gaps = [
            {"id": "SPATIAL-GAP-ORIGIN", "status": "UNSELECTED", "topic": "origin_denominator", "count": None, "detail": "Origin candidates are observations only; no denominator is selected."},
            {"id": "SPATIAL-GAP-DESTINATION", "status": "UNSELECTED", "topic": "destination_taxonomy", "count": None, "detail": "Grocery tags are inventoried only; no destination taxonomy is selected."},
            {"id": "SPATIAL-GAP-NETWORK", "status": "UNSELECTED", "topic": "pedestrian_network", "count": None, "detail": "Network tags are observations only; no include/exclude policy is selected."},
            {"id": "SPATIAL-GAP-VERTICAL", "status": "UNAVAILABLE", "topic": "vertical_reference", "count": None, "detail": "Source observations do not establish a vertical reference."},
            {"id": "SPATIAL-GAP-WEATHER", "status": "SEMANTICS_UNRESOLVED", "topic": "weather_method", "count": None, "detail": "Informational weather gate only. It does not block this spatial package.", "evidence_refs": ["R09", "R09-R01"]},
        ]
    else:
        source_requests = list((source_failure or {}).get("source_request_receipts") or []) or _spatial_not_attempted_receipts()
        raw_artifacts = []
        normalized_artifacts = []
        snapshots = []
        origin_inventory = _unavailable_inventory("No complete spatial source package was published.")
        grocery_inventory = _unavailable_inventory("No complete OSM query was published.")
        network_inventory = {"status": "UNAVAILABLE", "count": None, "network_tag_distribution": None}
        source_status = PACKAGE_STATUS_BLOCKED
        data_gaps = [
            {"id": "SPATIAL-GAP-SOURCE", "status": "BLOCKED", "topic": "spatial_source_gate", "count": None, "detail": (failure or {}).get("message") or "Spatial source acquisition did not complete."},
            {"id": "SPATIAL-GAP-VERTICAL", "status": "UNAVAILABLE", "topic": "vertical_reference", "count": None, "detail": "Vertical reference was not observed."},
        ]

    policies = {
        "origin_denominator": {"status": PROPOSED_PROJECT_DECISION, "human_approval_required": True, "selected": None, "candidate_ids": [record.get("feature_id") for record in (origin_inventory.get("records") or [])] if isinstance(origin_inventory.get("records"), list) else None},
        "destination_taxonomy": {"status": PROPOSED_PROJECT_DECISION, "human_approval_required": True, "selected": None, "observed_counts": grocery_inventory.get("counts_by_shop_tag") if grocery_inventory.get("status") != "UNAVAILABLE" else None},
        "pedestrian_network": {"status": PROPOSED_PROJECT_DECISION, "human_approval_required": True, "selected": None, "required_exclusions": [{"key": "foot", "value": "no"}, {"key": "access", "value": "no"}, {"key": "access", "value": "private"}]},
    }
    package: dict[str, Any] = {
        "schema_version": SPATIAL_PACKAGE_SCHEMA,
        "track": SPATIAL_TRACK,
        "package_id": package_id,
        "package_revision": revision,
        "status": source_status,
        "created_at": created,
        "project_id": project_id,
        "study_area": {
            "id": resolved_study_area_id,
            "geometry_sha256": inspection.geometry_sha256 if inspection else None,
            "artifact_sha256": inspection.artifact_sha256 if inspection else None,
            "horizontal_crs": STUDY_AREA_CRS,
            "units": STUDY_AREA_UNITS,
        },
        "query_envelope": inspection_payload,
        "crs_record": {
            "horizontal_crs": STUDY_AREA_CRS,
            "units": STUDY_AREA_UNITS,
            "vertical_reference": None,
            "vertical_reference_status": "UNAVAILABLE",
        },
        "source_requests": source_requests,
        "request_receipts": source_requests,
        "artifacts": raw_artifacts,
        "normalized_artifacts": normalized_artifacts,
        "snapshots": snapshots,
        "origin_inventory": origin_inventory,
        "grocery_inventory": grocery_inventory,
        "network_inventory": network_inventory,
        "network_manifest": network_inventory,
        "proposed_policies": policies,
        "data_gaps": data_gaps,
        "weather_gate": dict(WEATHER_GATE_REFERENCE),
        "failure": failure,
        "no_accessibility_result": True,
        "no_climate_result": True,
        "no_approval_event": True,
        "formal_claim_status": "BLOCKED",
        "formal_claims": [],
        "site_approval": None,
        "design_boundary_approval": None,
        "ledger_event_id": (
            "m2-a03-spatial-snapshot-" + hashlib.sha256(package_id.encode()).hexdigest()[:24]
            if append_ledger
            else None
        ),
    }
    if source_bundle is not None:
        from .spatial_input_policy import build_spatial_decision_packet

        package["decision_packet"] = build_spatial_decision_packet(package)
    _write_json(stage / "request.json", {"schema_version": "m2-a03-spatial-request-v1", "package_id": package_id, "project_id": project_id, "study_area_id": resolved_study_area_id, "created_at": created, "source_requests": source_requests, "weather_requests": 0})
    _write_json(stage / "failure-evidence.json", {"package_id": package_id, "inspection": inspection_payload, "failure": failure})
    _write_json(stage / "source-and-integrity-manifest.json", {"schema_version": "m2-a03-spatial-source-integrity-v1", "status": package["status"], "raw_artifacts": raw_artifacts, "normalized_artifacts": normalized_artifacts, "snapshots": snapshots, "source_requests": source_requests})
    _write_json(stage / "crs-unit-vertical-manifest.json", package["crs_record"] | {"query_envelope": inspection_payload, "anchor_status": inspection_payload.get("anchor_status", "UNVERIFIED")})
    _write_json(stage / "data-gap-register.json", {"gaps": data_gaps})
    _write_json(stage / "origin-candidate-inventory.json", origin_inventory)
    _write_json(stage / "raw-grocery-tag-inventory.json", grocery_inventory)
    _write_json(stage / "network-inventory.json", network_inventory)
    _write_json(stage / "proposed-origin-policy.json", policies["origin_denominator"])
    _write_json(stage / "proposed-destination-taxonomy.json", policies["destination_taxonomy"])
    _write_json(stage / "proposed-network-policy.json", policies["pedestrian_network"])
    _write_json(stage / "weather-gate.json", package["weather_gate"])
    if source_status == SPATIAL_READY_STATUS:
        artifacts_by_id = {record["id"]: record for record in raw_artifacts}
        for record in raw_artifacts:
            validate_artifact_record(record, root=stage)
        for record in normalized_artifacts:
            parent = artifacts_by_id.get(record.get("raw_parent_artifact_id"))
            if parent is None:
                raise ProvenanceValidationError(f"normalized artifact has unknown raw parent: {record.get('raw_parent_artifact_id')}")
            validate_normalized_artifact_record(record, raw_artifact=parent, root=stage)
        for record in snapshots:
            validate_snapshot_record(record, artifacts=artifacts_by_id, root=stage)
    _assert_spatial_package_has_no_weather(package, stage)
    _write_json(stage / "spatial-input-decision-package.json", package)
    files = [path for path in stage.rglob("*") if path.name != "package-manifest.json" and path.is_file()]
    _write_json(stage / "package-manifest.json", _manifest_for(stage, files))
    published = False

    def raise_publication_failure(exc: BaseException) -> None:
        shutil.rmtree(stage, ignore_errors=True)
        failure_path = output / f"{package_dir.name}.publication-failure.json"
        try:
            _write_json(failure_path, {"run_id": package_dir.name, "package_id": package_id, "retryable": True, "published_package_available": published, "error_type": type(exc).__name__, "error": str(exc)})
        except OSError:
            pass
        raise AnalysisInputPublicationError(
            f"M2-A03 spatial package publication/state commit failed for {package_id}; retry is safe: {exc}"
        ) from exc

    try:
        (package_validator or load_m2a03_spatial_package)(stage)
        if not append_ledger:
            (package_publisher or _publish_without_replacing)(stage, package_dir)
            (package_validator or load_m2a03_spatial_package)(package_dir)
            return package_dir
        entities, events = _package_state_batch(
            package,
            package_root=stage,
            state_root=package_dir,
            actor="m2-a03-spatial-builder",
            revision=revision,
            target_type="SpatialInputDecisionPackage",
        )

        def publish_and_verify() -> None:
            nonlocal published
            (package_publisher or _publish_without_replacing)(stage, package_dir)
            (package_validator or load_m2a03_spatial_package)(package_dir)
            published = True
            if commit_hook is not None:
                commit_hook()

        with ProjectStateStore(database) as store:
            store.commit_batch(entities=entities, events=events, before_commit=publish_and_verify)
    except BaseException as exc:
        if isinstance(exc, FileExistsError) and package_dir.exists():
            competing = _reconcile_competing_package(
                stage=stage,
                target=package_dir,
                expected_package_id=package_id,
                validator=load_m2a03_spatial_package,
            )
            if competing is not None:
                shutil.rmtree(stage, ignore_errors=True)
                commit_existing(competing)
                return package_dir
        raise_publication_failure(exc)
    return package_dir


__all__ = [
    "APPROVED_PROJECT_DECISION",
    "AnalysisInputError",
    "AnalysisInputPublicationError",
    "ArtifactIntegrityError",
    "PACKAGE_STATUS_BLOCKED",
    "PROPOSED_PROJECT_DECISION",
    "ProvenanceValidationError",
    "SPATIAL_PACKAGE_SCHEMA",
    "SPATIAL_READY_STATUS",
    "StudyAreaAnchorError",
    "StudyAreaInspection",
    "WEATHER_GATE_REFERENCE",
    "build_m2a03_package",
    "build_m2a03_spatial_package",
    "classify_observation",
    "ensure_metric_crs",
    "historical_run_directory",
    "inspect_active_study_area",
    "inventory_osm_grocery_tags",
    "load_analysis_input_package",
    "load_m2a03_spatial_package",
    "package_is_stale",
    "require_approved_policy",
    "require_spatial_package_use",
    "sha256_bytes",
    "sha256_file",
    "spatial_revision_is_used",
    "spatial_run_directory",
    "validate_artifact_record",
    "validate_normalized_artifact_record",
    "validate_snapshot_record",
]
