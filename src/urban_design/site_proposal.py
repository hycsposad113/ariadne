"""Typed, fail-closed contracts for the Milestone 2 Delft site proposal.

This module deliberately separates a proposed boundary from an effective
``Site``.  The proposal may be inspected and replayed, but it cannot make
``Project.site_id`` effective or create a human decision event.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .geometry import (
    GeometryValidationError,
    canonical_geometry_hash,
    polygon_area,
    polygon_perimeter,
    validate_geometry,
)


SHA256_PREFIX = "sha256:"
PROPOSAL_STATUS = "PROPOSED"
HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
_SOURCE_CLASSES = {
    "PROJECT_DECISION",
    "DATASET_OBSERVATION",
    "COMPUTED_RESULT",
    "UNAVAILABLE",
    "UNCERTAIN",
}
_AVAILABILITY = {"OBSERVED", "UNAVAILABLE", "UNCERTAIN"}


class SiteProposalValidationError(ValueError):
    """Raised when a site proposal or boundary artifact is not defensible."""


def _nonempty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value.strip()


def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


def _hash(value: str, field: str = "sha256") -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith(SHA256_PREFIX):
        raise ValueError(f"{field} must be formatted as sha256:<64 lowercase hex characters>")
    if any(char not in "0123456789abcdef" for char in value[len(SHA256_PREFIX) :]):
        raise ValueError(f"{field} must be formatted as sha256:<64 lowercase hex characters>")
    return value


def _relative_path(value: str, field: str = "path") -> str:
    value = _nonempty(value, field).replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("/"):
        raise ValueError(f"{field} must be a repository-relative path")
    return str(path)


class ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceRecord(ProposalModel):
    """One auditable source observation or unavailable check."""

    id: str
    source_class: Literal[
        "PROJECT_DECISION",
        "DATASET_OBSERVATION",
        "COMPUTED_RESULT",
        "UNAVAILABLE",
        "UNCERTAIN",
    ]
    availability: Literal["OBSERVED", "UNAVAILABLE", "UNCERTAIN"]
    publisher: str
    source_identity: str
    query: str
    retrieved_at: datetime
    request_started_at: datetime | None = None
    request_finished_at: datetime | None = None
    request_url: str | None = None
    version: str = "UNSPECIFIED"
    license: str
    attribution: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    validation_status: Literal["VALIDATED", "PROVISIONAL", "UNAVAILABLE"] = "PROVISIONAL"
    artifact_path: str | None = None
    artifact_sha256: str | None = None
    artifact_size_bytes: int | None = Field(default=None, ge=0)
    coverage: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

    _id = field_validator("id", "publisher", "source_identity", "query", "version", "license", "attribution")(
        lambda value, info: _nonempty(value, info.field_name)
    )
    _when = field_validator("retrieved_at")(_timestamp)
    _request_started = field_validator("request_started_at")(
        lambda value: None if value is None else _timestamp(value)
    )
    _request_finished = field_validator("request_finished_at")(
        lambda value: None if value is None else _timestamp(value)
    )
    _request_url = field_validator("request_url")(
        lambda value: None if value is None else _nonempty(value, "request_url")
    )
    _artifact_path = field_validator("artifact_path")(
        lambda value: None if value is None else _relative_path(value, "artifact_path")
    )
    _artifact_hash = field_validator("artifact_sha256")(
        lambda value: None if value is None else _hash(value, "artifact_sha256")
    )

    @field_validator("limitations")
    @classmethod
    def valid_limitations(cls, values: list[str]) -> list[str]:
        return [_nonempty(value, "limitation") for value in values]

    @model_validator(mode="after")
    def source_artifact_contract(self) -> "SourceRecord":
        if self.availability == "OBSERVED" and self.source_class not in {"DATASET_OBSERVATION", "PROJECT_DECISION"}:
            raise ValueError("observed source must be a dataset observation or project decision")
        if self.availability != "OBSERVED" and self.source_class not in {"UNAVAILABLE", "UNCERTAIN"}:
            raise ValueError("unavailable or uncertain source must be classified explicitly")
        if self.availability == "UNAVAILABLE" and self.validation_status != "UNAVAILABLE":
            raise ValueError("unavailable source must have UNAVAILABLE validation status")
        if self.availability == "OBSERVED":
            if self.artifact_path is None or self.artifact_sha256 is None or self.artifact_size_bytes is None:
                raise ValueError("observed source requires retained artifact path, hash, and size")
        if (self.request_started_at is None) != (self.request_finished_at is None):
            raise ValueError("request start and finish timestamps must be supplied together")
        if self.request_started_at is not None and self.request_finished_at < self.request_started_at:
            raise ValueError("request_finished_at cannot precede request_started_at")
        return self


class TransformRecord(ProposalModel):
    input_crs: str
    output_crs: str
    method: str
    tool: str
    tool_version: str
    command: str
    axis_order: str
    vertical_reference_status: str

    _text = field_validator(
        "input_crs",
        "output_crs",
        "method",
        "tool",
        "tool_version",
        "command",
        "axis_order",
        "vertical_reference_status",
    )(lambda value, info: _nonempty(value, info.field_name))


class Measurement(ProposalModel):
    name: Literal["area", "perimeter"]
    value: float
    unit: Literal["m2", "m"]
    source_class: Literal["COMPUTED_RESULT"] = "COMPUTED_RESULT"
    method: str
    crs: str

    @field_validator("value")
    @classmethod
    def finite_positive(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("measurement must be finite and positive")
        return value

    _text = field_validator("method", "crs")(lambda value, info: _nonempty(value, info.field_name))

    @model_validator(mode="after")
    def unit_matches_name(self) -> "Measurement":
        expected = "m2" if self.name == "area" else "m"
        if self.unit != expected:
            raise ValueError(f"{self.name} measurement must use {expected}")
        return self


class SiteProposal(ProposalModel):
    """Approval-ready but non-effective Delft site proposal."""

    id: str
    project_id: str
    version: str
    status: Literal["PROPOSED"] = PROPOSAL_STATUS
    human_decision_status: Literal["HUMAN_DECISION_REQUIRED"] = HUMAN_DECISION_REQUIRED
    boundary_artifact_path: str
    boundary_sha256: str
    boundary_size_bytes: int = Field(ge=1)
    boundary_mime: Literal["application/geo+json"]
    geometry_sha256: str
    geometry: dict[str, Any]
    geometry_type: Literal["Polygon", "MultiPolygon"]
    horizontal_crs: str
    units: Literal["m"]
    vertical_reference_status: str
    transform: TransformRecord
    producer: str
    created_at: datetime
    selection_method: str
    rationale: str
    source_refs: list[str] = Field(min_length=1)
    parent_refs: list[str] = Field(default_factory=list)
    measurements: list[Measurement] = Field(min_length=2)
    delft_context: dict[str, Any]
    dataset_plan: dict[str, Any]
    limitations: list[str] = Field(min_length=1)
    approval_record_path: str
    ledger_event_refs: list[str] = Field(default_factory=list)
    supersedes_proposal_id: str | None = None
    selection_criteria_status: Literal["PROPOSED_PROJECT_DECISION"] | None = None
    selection_criteria: dict[str, Any] = Field(default_factory=dict)
    scale_parameters: dict[str, Any] = Field(default_factory=dict)
    taxonomy_status: Literal["PROPOSED"] | None = None
    map_preview_path: str | None = None
    source_records_path: str | None = None

    _id = field_validator("id", "project_id", "version", "producer", "selection_method", "rationale", "vertical_reference_status")(
        lambda value, info: _nonempty(value, info.field_name)
    )
    _boundary_path = field_validator("boundary_artifact_path", "approval_record_path")(
        lambda value, info: _relative_path(value, info.field_name)
    )
    _optional_paths = field_validator("map_preview_path", "source_records_path")(
        lambda value, info: None if value is None else _relative_path(value, info.field_name)
    )
    _hashes = field_validator("boundary_sha256", "geometry_sha256")(
        lambda value, info: _hash(value, info.field_name)
    )
    _when = field_validator("created_at")(_timestamp)

    @field_validator("source_refs", "parent_refs", "ledger_event_refs")
    @classmethod
    def valid_refs(cls, values: list[str]) -> list[str]:
        return [_nonempty(value, "reference") for value in values]

    @field_validator("limitations")
    @classmethod
    def valid_limitations(cls, values: list[str]) -> list[str]:
        return [_nonempty(value, "limitation") for value in values]

    @model_validator(mode="after")
    def validate_contract(self) -> "SiteProposal":
        if self.horizontal_crs.upper() in {"EPSG:4326", "CRS84", "WGS84"}:
            raise ValueError("metric boundary must use a projected CRS; EPSG:4326 is display-only")
        if self.horizontal_crs.upper() != "EPSG:28992":
            raise ValueError("Delft proposal must use EPSG:28992 for deterministic metric results")
        try:
            summary = validate_geometry(self.geometry)
        except GeometryValidationError as exc:
            raise ValueError(str(exc)) from exc
        if summary["type"] != self.geometry_type:
            raise ValueError("geometry_type does not match geometry")
        if summary["sha256"] != self.geometry_sha256:
            raise ValueError("geometry_sha256 does not match canonical geometry")
        if self.delft_context.get("containment_status") not in {"WITHIN_CONTEXT_BBOX", "INTERSECTS_CONTEXT_BBOX"}:
            if self.delft_context.get("containment_status") not in {
                "WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY",
                "INTERSECTS_INDEPENDENT_MUNICIPAL_BOUNDARY",
            }:
                raise ValueError("Delft containment/intersection status is required")
        if not self.delft_context.get("evidence_ref"):
            raise ValueError("Delft context requires an evidence reference")
        measurements = {measurement.name: measurement for measurement in self.measurements}
        if set(measurements) != {"area", "perimeter"}:
            raise ValueError("area and perimeter computed results are required")
        area = polygon_area(self.geometry)
        perimeter = polygon_perimeter(self.geometry)
        if not math.isclose(area, measurements["area"].value, rel_tol=0.0, abs_tol=1e-7):
            raise ValueError("area measurement does not match deterministic geometry result")
        if not math.isclose(perimeter, measurements["perimeter"].value, rel_tol=0.0, abs_tol=1e-7):
            raise ValueError("perimeter measurement does not match deterministic geometry result")
        if self.transform.output_crs.upper() != self.horizontal_crs.upper():
            raise ValueError("transform output CRS must equal horizontal_crs")
        if self.transform.input_crs.upper() in {"EPSG:28992", "EPSG:4326"} and self.transform.input_crs.upper() == self.horizontal_crs.upper():
            raise ValueError("transform metadata must record the WGS84-to-projected conversion")
        if self.version.casefold() in {"v2", "v3", "v4"}:
            if self.id.startswith("site-proposal-rotterdam-m4h-"):
                expected_parent = {
                    "v2": "site-proposal-rotterdam-m4h-v1",
                    "v3": "site-proposal-rotterdam-m4h-v2",
                    "v4": "site-proposal-rotterdam-m4h-v3",
                }[self.version.casefold()]
            else:
                expected_parent = "site-proposal-delft-v1" if self.version.casefold() == "v2" else "site-proposal-delft-v2"
            if self.supersedes_proposal_id != expected_parent:
                raise ValueError(f"{self.version} proposal must supersede {expected_parent}")
            if self.selection_criteria_status != "PROPOSED_PROJECT_DECISION":
                raise ValueError(f"{self.version} selection criteria must remain a proposed project decision")
            if self.taxonomy_status != "PROPOSED":
                raise ValueError(f"{self.version} destination taxonomy must remain proposed")
            if self.map_preview_path is None or self.source_records_path is None:
                raise ValueError(f"{self.version} proposal requires map and source-record artifact paths")
            if self.delft_context.get("containment_status") not in {
                "WITHIN_INDEPENDENT_MUNICIPAL_BOUNDARY",
                "INTERSECTS_INDEPENDENT_MUNICIPAL_BOUNDARY",
            }:
                raise ValueError(f"{self.version} Delft containment must use an independent municipal boundary")
            if "nominatim" in str(self.delft_context.get("evidence_ref", "")).casefold():
                raise ValueError(f"Nominatim bbox cannot be the {self.version} Delft containment evidence")
        return self


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return SHA256_PREFIX + digest.hexdigest()


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def load_boundary_artifact(path: str | Path) -> tuple[dict[str, Any], str, int]:
    """Load, hash, and validate a retained GeoJSON geometry artifact."""

    raw = Path(path).read_bytes()
    if not raw:
        raise SiteProposalValidationError("boundary artifact is empty")
    actual_hash = SHA256_PREFIX + hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SiteProposalValidationError("boundary artifact is not valid UTF-8 JSON") from exc
    crs = payload.get("crs") if isinstance(payload, Mapping) else None
    crs_name = None
    if isinstance(crs, Mapping):
        properties = crs.get("properties")
        if isinstance(properties, Mapping):
            crs_name = properties.get("name") or properties.get("href")
    if not isinstance(crs_name, str) or crs_name.upper() != "EPSG:28992":
        raise SiteProposalValidationError("boundary artifact must declare projected CRS EPSG:28992")
    if isinstance(payload, Mapping) and payload.get("type") in {"Polygon", "MultiPolygon"}:
        geometry = {"type": payload.get("type"), "coordinates": payload.get("coordinates")}
    elif isinstance(payload, Mapping) and payload.get("type") == "Feature":
        geometry = payload.get("geometry")
    elif isinstance(payload, Mapping) and payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise SiteProposalValidationError("boundary FeatureCollection must contain exactly one feature")
        geometry = features[0].get("geometry") if isinstance(features[0], Mapping) else None
    else:
        geometry = None
    if not isinstance(geometry, Mapping):
        raise SiteProposalValidationError("boundary artifact must contain Polygon or MultiPolygon geometry")
    try:
        validate_geometry(geometry)
    except GeometryValidationError as exc:
        raise SiteProposalValidationError(str(exc)) from exc
    return dict(geometry), actual_hash, len(raw)


def validate_site_proposal(
    proposal: SiteProposal | Mapping[str, Any],
    artifact_root: str | Path,
) -> SiteProposal:
    """Re-read bytes and recompute all deterministic facts before acceptance."""

    candidate = proposal if isinstance(proposal, SiteProposal) else SiteProposal.model_validate(proposal)
    artifact = Path(artifact_root) / candidate.boundary_artifact_path
    geometry, actual_hash, actual_size = load_boundary_artifact(artifact)
    if actual_hash != candidate.boundary_sha256 or actual_size != candidate.boundary_size_bytes:
        raise SiteProposalValidationError("boundary artifact hash or size does not match proposal")
    if canonical_geometry_hash(geometry) != candidate.geometry_sha256:
        raise SiteProposalValidationError("boundary geometry hash does not match proposal")
    if geometry != candidate.geometry:
        raise SiteProposalValidationError("proposal geometry differs from retained boundary bytes")
    return candidate


class V2SourceRecord(SourceRecord):
    """Source record with mandatory per-request timing for M2-R01."""

    @model_validator(mode="after")
    def request_provenance_required(self) -> "V2SourceRecord":
        if self.availability == "OBSERVED":
            if self.request_started_at is None or self.request_finished_at is None or not self.request_url:
                raise ValueError("v2 observed source requires request URL and independent start/end timestamps")
        return self


def assert_no_effective_site_conflict(store: Any, project_id: str) -> None:
    """Refuse a proposal when the project already has an effective site."""

    from .store import EntityNotFoundError

    try:
        project = store.current(project_id)
    except EntityNotFoundError:
        project = None
    if project is not None and project.get("site_id"):
        raise SiteProposalValidationError("project already has an effective site")
    for record in store.replay_project(project_id).values():
        if record.entity_type not in {"Site", "SiteModel"}:
            continue
        if str(record.get("status", "")).upper() in {"APPROVED", "FROZEN"}:
            raise SiteProposalValidationError("project already contains an effective site")


def assert_site_approval_authorized(store: Any, site_id: str) -> None:
    """Verify the explicit human approval event behind an effective Site.

    This guard is intentionally separate from proposal creation. It is used by
    a later adoption transition and prevents a raw ``status=APPROVED`` patch
    from being treated as a human decision.
    """

    from datetime import datetime

    record = store.current(site_id)
    status = str(record.get("status", "")).upper()
    if status not in {"APPROVED", "FROZEN"}:
        return
    required = ("approval_actor", "approval_timestamp", "approval_reason", "approval_event_id")
    missing = [name for name in required if not record.get(name)]
    if missing:
        raise SiteProposalValidationError(
            "effective site requires actor, timestamp, reason, and explicit approval event: " + ", ".join(missing)
        )
    timestamp = record.get("approval_timestamp")
    try:
        parsed = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SiteProposalValidationError("approval_timestamp must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SiteProposalValidationError("approval_timestamp must include a timezone")
    approval_event_id = str(record.get("approval_event_id"))
    events = store.events(project_id=record.project_id)
    if not any(
        event.event_id == approval_event_id
        and event.target_id == site_id
        and event.action in {"Approve", "Accept"}
        and event.actor == record.get("approval_actor")
        and event.reason == record.get("approval_reason")
        for event in events
    ):
        raise SiteProposalValidationError("effective site is missing its matching explicit approval ledger event")


__all__ = [
    "HUMAN_DECISION_REQUIRED",
    "PROPOSAL_STATUS",
    "Measurement",
    "SiteProposal",
    "SiteProposalValidationError",
    "SourceRecord",
    "TransformRecord",
    "V2SourceRecord",
    "assert_no_effective_site_conflict",
    "assert_site_approval_authorized",
    "canonical_json_bytes",
    "load_boundary_artifact",
    "sha256_file",
    "validate_site_proposal",
]
