"""Small, provider-independent domain contracts.

The models in this module deliberately describe identity, provenance, and
relationships.  They do not calculate GIS, geometry, accessibility, or
climate values.  Those values belong to deterministic tools and their
validators.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import math
import re
from typing import Any, Iterable, Literal, Mapping

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

try:  # pyproj is a required project dependency, but keep import errors explicit.
    from pyproj import CRS
except ImportError:  # pragma: no cover - dependency installation is a runtime gate
    CRS = None  # type: ignore[assignment,misc]


SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class _ValueEnum(str, Enum):
    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            folded = value.casefold().replace("-", "_")
            for member in cls:
                if member.value.casefold().replace("-", "_") == folded:
                    return member
        return None


class ActorKind(_ValueEnum):
    """Declared origin class for a ledger event; legacy rows remain unclassified."""

    HUMAN_UI = "HUMAN_UI"
    QGIS_PLUGIN = "QGIS_PLUGIN"
    AGENT_AUTOMATION = "AGENT_AUTOMATION"
    TEST_HARNESS = "TEST_HARNESS"


class ProjectStatus(_ValueEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


class SiteStatus(_ValueEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    FROZEN = "frozen"
    BLOCKED = "blocked"


class ConstraintStatus(_ValueEnum):
    PROPOSED = "proposed"
    EFFECTIVE = "effective"
    CHALLENGED = "challenged"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class ScenarioStatus(_ValueEnum):
    PROPOSED = "proposed"
    DRAFT = "draft"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    STALE = "stale"
    BLOCKED = "blocked"


class RunStatus(_ValueEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STALE = "STALE"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class ResultStatus(_ValueEnum):
    OBSERVED = "observed"
    COMPUTED = "computed"
    UNAVAILABLE = "unavailable"


class EvidenceValidationStatus(_ValueEnum):
    UNVERIFIED = "unverified"
    VALIDATED = "validated"
    INVALID = "invalid"
    SUPERSEDED = "superseded"
    CONTESTED = "contested"


class HumanStatus(_ValueEnum):
    NOT_REVIEWED = "not_reviewed"
    INSPECTED = "inspected"
    CHALLENGED = "challenged"
    ACCEPTED = "accepted"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    OVERRIDDEN = "overridden"
    SUPERSEDED = "superseded"
    STALE = "stale"


class ClaimType(_ValueEnum):
    OBSERVATION = "observation"
    COMPARISON = "comparison"
    INFERENCE = "inference"
    NORMATIVE_JUDGEMENT = "normative_judgement"
    CADASTRAL = "CADASTRAL"
    OWNERSHIP = "OWNERSHIP"
    ZONING_COMPLIANCE = "ZONING_COMPLIANCE"
    LEGAL_BUILDABILITY = "LEGAL_BUILDABILITY"


class SourceType(_ValueEnum):
    RESEARCH_FINDING = "research_finding"
    DATASET_OBSERVATION = "dataset_observation"
    PROJECT_DECISION = "project_decision"
    COMPUTED_RESULT = "computed_result"
    INTERPRETATION = "interpretation"
    AI_INTERPRETATION = "AI_INTERPRETATION"
    HYPOTHESIS = "HYPOTHESIS"
    DATA_GAP = "DATA_GAP"
    ILLUSTRATIVE_EXAMPLE = "illustrative_example"


class EvidenceSemanticType(_ValueEnum):
    """Semantic class for an evidence item or model-produced interpretation."""

    DATASET_OBSERVATION = "DATASET_OBSERVATION"
    COMPUTED_RESULT = "COMPUTED_RESULT"
    AI_INTERPRETATION = "AI_INTERPRETATION"
    HYPOTHESIS = "HYPOTHESIS"
    DATA_GAP = "DATA_GAP"


class StudyAreaSource(_ValueEnum):
    HUMAN_DRAWN_QGIS = "HUMAN_DRAWN_QGIS"


class StudyAreaStatus(_ValueEnum):
    DRAFT = "DRAFT"
    CONFIRMED_FOR_EXPLORATION = "CONFIRMED_FOR_EXPLORATION"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"
    BLOCKED = "BLOCKED"

    # Short aliases are useful at adapters while retaining one canonical value.
    CONFIRMED = "CONFIRMED_FOR_EXPLORATION"


class DesignBoundaryStatus(_ValueEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"
    BLOCKED = "BLOCKED"


class ExplorationStage(_ValueEnum):
    UNDERSTAND = "UNDERSTAND"
    EXPLORE = "EXPLORE"
    TEST = "TEST"
    REFINE = "REFINE"


class FormalClaimType(_ValueEnum):
    CADASTRAL = "CADASTRAL"
    OWNERSHIP = "OWNERSHIP"
    ZONING_COMPLIANCE = "ZONING_COMPLIANCE"
    LEGAL_BUILDABILITY = "LEGAL_BUILDABILITY"


class ParameterStatus(_ValueEnum):
    PROPOSED = "proposed"
    EFFECTIVE = "effective"
    CHALLENGED = "challenged"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class AssumptionStatus(_ValueEnum):
    PROPOSED = "proposed"
    EFFECTIVE = "effective"
    CHALLENGED = "challenged"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class ConfidenceLevel(_ValueEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LedgerAction(_ValueEnum):
    INSPECT = "Inspect"
    CHALLENGE = "Challenge"
    MODIFY = "Modify"
    RERUN = "Rerun"
    COMPARE = "Compare"
    FORK = "Fork"
    REJECT = "Reject"
    OVERRIDE = "Override"
    CREATE = "Create"
    APPROVE = "Approve"
    RECONSIDER = "Reconsider"
    CONFIRM_STUDY_AREA = "ConfirmStudyArea"
    ACTIVATE_STUDY_AREA = "ActivateStudyArea"
    SUPERSEDE_STUDY_AREA = "SupersedeStudyArea"
    MARK_STALE = "MarkStale"


class DecisionAction(_ValueEnum):
    INSPECT = "Inspect"
    CHALLENGE = "Challenge"
    MODIFY = "Modify"
    RERUN = "Rerun"
    COMPARE = "Compare"
    FORK = "Fork"
    REJECT = "Reject"
    OVERRIDE = "Override"
    ACCEPT = "Accept"
    APPROVE = "Approve"
    RECONSIDER = "Reconsider"


class ExperimentApprovalStatus(_ValueEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


def _id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string")
    return value.strip()


def _sha256(value: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError("sha256 must be formatted as sha256:<64 lowercase hex characters>")
    return value


def _projected_crs(value: str) -> str:
    """Require a parseable projected horizontal CRS without rewriting its label."""

    value = _id(value)
    if CRS is None:  # pragma: no cover - pyproj is a required dependency
        raise ValueError("projected CRS validation requires pyproj")
    try:
        parsed = CRS.from_user_input(value)
    except Exception as exc:  # pyproj exposes several parser exception types
        raise ValueError("horizontal_crs must be a valid projected CRS") from exc
    if not parsed.is_projected:
        raise ValueError("horizontal_crs must be projected; geographic CRS is not permitted")
    return value


_LINEAR_UNIT_ALIASES = {
    "m": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "ft": "ft",
    "foot": "ft",
    "feet": "ft",
    "international foot": "ft",
    "international feet": "ft",
    "survey foot": "ft",
    "survey feet": "ft",
    "us survey foot": "ft",
    "us survey feet": "ft",
}


def _canonical_linear_unit(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("units must be a non-empty supported linear unit")
    normalized = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
    try:
        return _LINEAR_UNIT_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError("units must be a supported linear unit alias (m or ft)") from exc


def _projected_axis_unit(horizontal_crs: str) -> str:
    """Return the supported linear unit family declared by a projected CRS."""

    if CRS is None:  # pragma: no cover - pyproj is a required dependency
        raise ValueError("projected CRS unit validation requires pyproj")
    try:
        parsed = CRS.from_user_input(horizontal_crs)
    except Exception as exc:
        raise ValueError("horizontal_crs must be a valid projected CRS") from exc
    if not parsed.is_projected:
        raise ValueError("horizontal_crs must be projected; geographic CRS is not permitted")
    axes = tuple(parsed.axis_info[:2])
    if len(axes) != 2:
        raise ValueError("projected CRS must declare two horizontal axes")

    families: list[str] = []
    for axis in axes:
        name = str(axis.unit_name or "").casefold()
        if "degree" in name or "radian" in name:
            raise ValueError("projected CRS horizontal axes must use linear units")
        if "metre" in name or "meter" in name:
            families.append("m")
        elif "foot" in name or "feet" in name:
            families.append("ft")
        else:
            raise ValueError(
                "projected CRS uses an unsupported horizontal axis unit; supported units are metre and foot"
            )
    if families[0] != families[1]:
        raise ValueError("projected CRS horizontal axes must use the same units")
    return families[0]


def canonical_units_for_crs(horizontal_crs: str, units: str) -> str:
    """Normalize a declared unit and require agreement with CRS axes."""

    declared = _canonical_linear_unit(units)
    expected = _projected_axis_unit(horizontal_crs)
    if declared != expected:
        raise ValueError(
            f"declared units {declared!r} do not match projected CRS axis units {expected!r}"
        )
    return declared


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


def _finite(value: Any, path: str = "value") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} cannot be NaN or infinite")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _finite(item, f"{path}[{index}]")


class _DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)

    @field_validator("id", check_fields=False)
    @classmethod
    def valid_id(cls, value: str) -> str:
        return _id(value)


class Project(_DomainModel):
    id: str
    name: str
    schema_version: str = "m1"
    current_revision: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("current_revision", "revision"),
    )
    site_id: str | None = None
    active_study_area_id: str | None = None
    status: ProjectStatus = ProjectStatus.PROPOSED
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "schema_version")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("text value must be non-empty")
        return value.strip()

    @field_validator("site_id", "active_study_area_id")
    @classmethod
    def valid_optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    def assert_compatible(self, record: Any) -> None:
        record_project_id = getattr(record, "project_id", None)
        if record_project_id is None:
            raise ValueError("record has no project identifier")
        if record_project_id != self.id:
            raise ValueError(f"project mismatch: expected {self.id}, got {record_project_id}")


class DatasetSnapshot(_DomainModel):
    id: str
    project_id: str
    source: str = Field(validation_alias=AliasChoices("source", "source_url", "source_identity"))
    query: str = Field(validation_alias=AliasChoices("query", "request_query"))
    retrieved_at: datetime = Field(validation_alias=AliasChoices("retrieved_at", "retrieval_time"))
    publisher: str
    license: str = Field(validation_alias=AliasChoices("license", "licence"))
    version: str
    sha256: str = Field(validation_alias=AliasChoices("sha256", "content_hash"))
    raw_artifact_id: str
    normalized_artifact_id: str | None = None

    _validate_retrieved_at = field_validator("retrieved_at")(_aware)
    _validate_sha256 = field_validator("sha256")(_sha256)

    @field_validator("project_id", "source", "query", "publisher", "license", "version")
    @classmethod
    def nonempty_provenance(cls, value: str) -> str:
        return _id(value)

    @field_validator("raw_artifact_id", "normalized_artifact_id")
    @classmethod
    def valid_artifact_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)


class Artifact(_DomainModel):
    """Immutable file or byte artifact referenced by a run or evidence card."""

    id: str
    type: str = Field(validation_alias=AliasChoices("type", "artifact_type"))
    uri: str
    sha256: str = Field(validation_alias=AliasChoices("sha256", "content_hash"))
    mime: str = Field(validation_alias=AliasChoices("mime", "mime_type"))
    crs: str | None = None
    producer: str
    created_at: datetime
    project_id: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    parent_artifact_ids: list[str] = Field(default_factory=list)

    _validate_created_at = field_validator("created_at")(_aware)
    _validate_hash = field_validator("sha256")(_sha256)

    @field_validator("type", "uri", "mime", "producer")
    @classmethod
    def artifact_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("crs", "project_id")
    @classmethod
    def optional_artifact_text(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("parent_artifact_ids")
    @classmethod
    def artifact_parents(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]


class Assumption(_DomainModel):
    """A visible premise that can be challenged and rerun."""

    id: str
    text: str = Field(validation_alias=AliasChoices("text", "statement"))
    scope: str
    source_refs: list[str] = Field(default_factory=list, validation_alias=AliasChoices("source_refs", "source"))
    status: AssumptionStatus = AssumptionStatus.PROPOSED
    project_id: str | None = None
    resulting_rerun_ids: list[str] = Field(default_factory=list)

    @field_validator("text", "scope")
    @classmethod
    def assumption_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("source_refs", "resulting_rerun_ids", mode="before")
    @classmethod
    def assumption_refs(cls, values: Iterable[str] | str | None) -> list[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        return [_id(value) for value in values]

    @field_validator("project_id")
    @classmethod
    def assumption_project(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)


class Site(_DomainModel):
    id: str
    project_id: str
    version: str
    boundary_artifact_id: str = Field(
        validation_alias=AliasChoices("boundary_artifact_id", "boundary", "boundary_artifact")
    )
    boundary_sha256: str
    crs: str = Field(validation_alias=AliasChoices("crs", "horizontal_crs"))
    vertical_reference: str | None = None
    units: str
    dataset_snapshot_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("dataset_snapshot_ids", "snapshot_ids", "source_snapshot_ids"),
    )
    normalized_layer_ids: list[str] = Field(default_factory=list)
    status: SiteStatus = SiteStatus.PROPOSED
    approval_actor: str | None = None
    approval_timestamp: datetime | None = None
    approval_reason: str | None = None
    approval_event_id: str | None = None

    _validate_boundary_hash = field_validator("boundary_sha256")(_sha256)

    @field_validator("project_id", "version", "boundary_artifact_id", "crs", "units")
    @classmethod
    def required_site_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("dataset_snapshot_ids", "normalized_layer_ids")
    @classmethod
    def valid_id_list(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("approval_actor", "approval_reason", "approval_event_id")
    @classmethod
    def optional_approval_text(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("approval_timestamp")
    @classmethod
    def optional_approval_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)

    @model_validator(mode="after")
    def effective_site_requires_explicit_approval(self) -> "Site":
        if self.status in {SiteStatus.APPROVED, SiteStatus.FROZEN}:
            missing = [
                name
                for name, value in (
                    ("approval_actor", self.approval_actor),
                    ("approval_timestamp", self.approval_timestamp),
                    ("approval_reason", self.approval_reason),
                    ("approval_event_id", self.approval_event_id),
                )
                if value is None or (isinstance(value, str) and not value.strip())
            ]
            if missing:
                raise ValueError(
                    "approved or frozen site requires actor, timestamp, reason, and explicit approval event: "
                    + ", ".join(missing)
                )
        return self

    @property
    def horizontal_crs(self) -> str:
        return self.crs


class StudyArea(_DomainModel):
    """A human-drawn, exploration-scoped polygon saved by QGIS.

    A Study Area is deliberately weaker than a legal or cadastral site.  It is
    sufficient to start the four exploratory stages after a human confirms the
    retained geometry, while formal boundary claims remain guarded by a later
    approved :class:`DesignBoundary`.
    """

    id: str
    project_id: str
    version: str
    geometry_artifact_id: str = Field(
        validation_alias=AliasChoices("geometry_artifact_id", "geometry_artifact", "artifact_id")
    )
    geometry_sha256: str = Field(validation_alias=AliasChoices("geometry_sha256", "geometry_hash"))
    # The file hash is retained in addition to the canonical geometry hash when
    # the confirmation service has read the saved artifact bytes.
    artifact_sha256: str | None = Field(
        default=None,
        validation_alias=AliasChoices("artifact_sha256", "geometry_artifact_sha256", "artifact_hash"),
    )
    horizontal_crs: str = Field(validation_alias=AliasChoices("horizontal_crs", "crs"))
    units: str
    source: StudyAreaSource = StudyAreaSource.HUMAN_DRAWN_QGIS
    status: StudyAreaStatus = StudyAreaStatus.DRAFT
    confirmed_actor: str | None = Field(
        default=None,
        validation_alias=AliasChoices("confirmed_actor", "confirmed_by", "confirmation_actor"),
    )
    confirmed_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("confirmed_at", "confirmation_timestamp", "confirmation_time"),
    )
    confirmation_event_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("confirmation_event_id", "confirmation_event", "event_id"),
    )
    supersedes_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("supersedes_id", "supersedes", "supersedes_study_area_id"),
    )
    superseded_by_id: str | None = None

    _validate_geometry_hash = field_validator("geometry_sha256")(_sha256)
    _validate_artifact_hash = field_validator("artifact_sha256")(
        lambda value: None if value is None else _sha256(value)
    )
    _validate_horizontal_crs = field_validator("horizontal_crs")(_projected_crs)

    @field_validator("project_id", "version", "geometry_artifact_id")
    @classmethod
    def study_area_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("units")
    @classmethod
    def study_area_units(cls, value: str, info: Any) -> str:
        horizontal_crs = info.data.get("horizontal_crs")
        if horizontal_crs is None:
            return _canonical_linear_unit(value)
        return canonical_units_for_crs(horizontal_crs, value)

    @field_validator("confirmed_actor", "confirmation_event_id", "supersedes_id", "superseded_by_id")
    @classmethod
    def optional_study_area_ids(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("confirmed_at")
    @classmethod
    def study_area_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)

    @model_validator(mode="after")
    def confirmed_study_area_requires_human_event(self) -> "StudyArea":
        if self.status is StudyAreaStatus.CONFIRMED_FOR_EXPLORATION:
            missing = [
                name
                for name, value in (
                    ("confirmed_actor", self.confirmed_actor),
                    ("confirmed_at", self.confirmed_at),
                    ("confirmation_event_id", self.confirmation_event_id),
                )
                if value is None or (isinstance(value, str) and not value.strip())
            ]
            if missing:
                raise ValueError(
                    "confirmed study area requires actor, timestamp, and confirmation event: "
                    + ", ".join(missing)
                )
        if self.source is not StudyAreaSource.HUMAN_DRAWN_QGIS:
            raise ValueError("study area source must be HUMAN_DRAWN_QGIS")
        return self

    @property
    def geometry_hash(self) -> str:
        return self.geometry_sha256

    @property
    def artifact_hash(self) -> str | None:
        return self.artifact_sha256

    @property
    def crs(self) -> str:
        return self.horizontal_crs

    @property
    def supersedes(self) -> str | None:
        return self.supersedes_id

    @property
    def confirmed_by(self) -> str | None:
        return self.confirmed_actor

    @property
    def confirmation_timestamp(self) -> datetime | None:
        return self.confirmed_at

    @property
    def event_id(self) -> str | None:
        return self.confirmation_event_id


class DesignBoundary(_DomainModel):
    """A formal boundary that can only become effective through HumanDecision."""

    id: str
    project_id: str
    study_area_id: str
    version: str
    geometry_artifact_id: str = Field(
        validation_alias=AliasChoices("geometry_artifact_id", "geometry_artifact", "artifact_id")
    )
    geometry_sha256: str = Field(validation_alias=AliasChoices("geometry_sha256", "geometry_hash"))
    artifact_sha256: str | None = Field(
        default=None,
        validation_alias=AliasChoices("artifact_sha256", "geometry_artifact_sha256", "artifact_hash"),
    )
    horizontal_crs: str = Field(validation_alias=AliasChoices("horizontal_crs", "crs"))
    units: str
    status: DesignBoundaryStatus = DesignBoundaryStatus.PROPOSED
    human_decision_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("human_decision_id", "decision_id"),
    )
    # A serialized HumanDecision is accepted at this boundary so that an
    # exported boundary remains self-describing without storing private model
    # reasoning.  The approval validator only needs explicit decision data.
    human_decision: Any | None = None
    approval_actor: str | None = None
    approval_timestamp: datetime | None = None
    approval_reason: str | None = None
    approval_event_id: str | None = None
    supersedes_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("supersedes_id", "supersedes", "supersedes_design_boundary_id"),
    )

    _validate_geometry_hash = field_validator("geometry_sha256")(_sha256)
    _validate_artifact_hash = field_validator("artifact_sha256")(
        lambda value: None if value is None else _sha256(value)
    )
    _validate_horizontal_crs = field_validator("horizontal_crs")(_projected_crs)

    @field_validator("project_id", "study_area_id", "version", "geometry_artifact_id")
    @classmethod
    def design_boundary_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("units")
    @classmethod
    def design_boundary_units(cls, value: str, info: Any) -> str:
        horizontal_crs = info.data.get("horizontal_crs")
        if horizontal_crs is None:
            return _canonical_linear_unit(value)
        return canonical_units_for_crs(horizontal_crs, value)

    @field_validator(
        "human_decision_id",
        "approval_actor",
        "approval_reason",
        "approval_event_id",
        "supersedes_id",
    )
    @classmethod
    def optional_design_boundary_text(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("approval_timestamp")
    @classmethod
    def design_boundary_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)

    @model_validator(mode="after")
    def approved_boundary_requires_human_decision(self) -> "DesignBoundary":
        if self.status is DesignBoundaryStatus.APPROVED:
            explicit_payload = self.human_decision
            payload_present = (
                isinstance(explicit_payload, Mapping)
                and bool(explicit_payload)
            ) or (
                isinstance(explicit_payload, (str, bytes))
                and bool(explicit_payload)
            ) or hasattr(explicit_payload, "id")
            explicit_decision = self.human_decision_id is not None or payload_present
            explicit_approval = all(
                value is not None and (not isinstance(value, str) or bool(value.strip()))
                for value in (
                    self.approval_actor,
                    self.approval_timestamp,
                    self.approval_reason,
                    self.approval_event_id,
                )
            )
            if not explicit_decision and not explicit_approval:
                raise ValueError("approved design boundary requires explicit HumanDecision data")
        return self

    @property
    def geometry_hash(self) -> str:
        return self.geometry_sha256

    @property
    def artifact_hash(self) -> str | None:
        return self.artifact_sha256

    @property
    def crs(self) -> str:
        return self.horizontal_crs

    @property
    def supersedes(self) -> str | None:
        return self.supersedes_id

    @property
    def decision_id(self) -> str | None:
        return self.human_decision_id


class Constraint(_DomainModel):
    id: str
    project_id: str | None = None
    name: str
    value: Any
    unit: str
    scope: str
    enforcement: Literal["HARD", "PREFERENCE"]
    status: ConstraintStatus = ConstraintStatus.PROPOSED
    source_refs: list[str] = Field(default_factory=list)
    source_note: str | None = None
    denominator: Literal["land_area", "exploration_design_area"] | None = None

    @field_validator("project_id", "name", "unit", "scope")
    @classmethod
    def constraint_text(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("value")
    @classmethod
    def finite_constraint_value(cls, value: Any) -> Any:
        _finite(value)
        return value

    @field_validator("source_refs")
    @classmethod
    def valid_source_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]


class ConstraintSet(_DomainModel):
    id: str
    project_id: str
    version: str
    constraints: list[Constraint] = Field(default_factory=list)
    allocation_policy: Literal["priority"] | None = None
    notes: str | None = None
    status: ConstraintStatus = ConstraintStatus.PROPOSED

    @field_validator("project_id", "version")
    @classmethod
    def constraint_set_text(cls, value: str) -> str:
        return _id(value)

    @model_validator(mode="after")
    def constraints_same_project(self) -> "ConstraintSet":
        # A constraint can be authored inside a set without duplicating the
        # set scope.  Materialise that scope here before checking consistency.
        for item in self.constraints:
            if item.project_id is None:
                item.project_id = self.project_id
        mismatched = [item.id for item in self.constraints if item.project_id != self.project_id]
        if mismatched:
            raise ValueError(f"constraint project mismatch: {', '.join(mismatched)}")
        return self


class UnavailableValue(_DomainModel):
    """Explicit marker for a value that could not be observed or computed."""

    status: str = "unavailable"
    reason: str

    @field_validator("reason")
    @classmethod
    def unavailable_reason(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("unavailable value requires a reason")
        return value.strip()

    @model_validator(mode="after")
    def fixed_status(self) -> "UnavailableValue":
        if self.status != "unavailable":
            raise ValueError("UnavailableValue status must be unavailable")
        return self


class ParameterAlternative(_DomainModel):
    id: str
    value: Any
    status: str

    @field_validator("status")
    @classmethod
    def alternative_status(cls, value: str) -> str:
        value = _id(value).lower()
        if value not in {"considered", "selected", "rejected", "superseded"}:
            raise ValueError("alternative status must be considered, selected, rejected, or superseded")
        _finite(value)
        return value

    @field_validator("value")
    @classmethod
    def finite_alternative_value(cls, value: Any) -> Any:
        _finite(value)
        return value


class ParameterDefinition(_DomainModel):
    id: str
    name: str
    value: Any
    unit: str
    context: str
    scale: str
    source_type: SourceType
    version: str = "v1"
    evidence_refs: list[str] = Field(default_factory=list)
    alternatives: list[ParameterAlternative] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    sensitivity_required: bool = False
    status: ParameterStatus = ParameterStatus.PROPOSED

    @field_validator("name", "unit", "context", "scale", "version")
    @classmethod
    def parameter_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("evidence_refs")
    @classmethod
    def parameter_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("value")
    @classmethod
    def finite_parameter_value(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("parameter value must be present or an explicit UnavailableValue")
        _finite(value)
        return value


class Scenario(_DomainModel):
    id: str
    project_id: str
    site_id: str
    site_version: str
    parent_scenario_id: str | None = None
    morphology_family: str | None = None
    geometry_artifact_id: str = Field(
        validation_alias=AliasChoices("geometry_artifact_id", "geometry_artifact")
    )
    geometry_sha256: str = Field(validation_alias=AliasChoices("geometry_sha256", "geometry_hash"))
    generator: str
    generator_version: str
    seed: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_refs: list[str] = Field(default_factory=list)
    constraint_set_id: str
    status: ScenarioStatus = ScenarioStatus.PROPOSED
    rejection_reason: str | None = None

    _validate_geometry_hash = field_validator("geometry_sha256")(_sha256)

    @field_validator(
        "project_id",
        "site_id",
        "site_version",
        "geometry_artifact_id",
        "generator",
        "generator_version",
        "constraint_set_id",
    )
    @classmethod
    def scenario_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("parent_scenario_id")
    @classmethod
    def scenario_parent_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("parameter_refs")
    @classmethod
    def scenario_parameter_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("parameters")
    @classmethod
    def finite_scenario_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _finite(value)
        return value

    @model_validator(mode="after")
    def rejected_has_reason(self) -> "Scenario":
        if self.status is ScenarioStatus.REJECTED and not (self.rejection_reason or "").strip():
            raise ValueError("a rejected scenario requires rejection_reason")
        return self

    @property
    def geometry_hash(self) -> str:
        return self.geometry_sha256

    def validate_lineage(self, parent: "Scenario | None") -> "Scenario":
        """Resolve and validate this scenario's parent before use."""

        if self.parent_scenario_id is None:
            if parent is not None:
                raise ValueError("root scenario cannot have a parent record")
            return self
        if parent is None:
            raise ValueError(f"parent scenario is missing: {self.parent_scenario_id}")
        if parent.id != self.parent_scenario_id:
            raise ValueError("parent scenario identifier mismatch")
        if parent.project_id != self.project_id:
            raise ValueError("parent scenario project mismatch")
        if parent.site_id != self.site_id or parent.site_version != self.site_version:
            raise ValueError("parent scenario site mismatch")
        return self


class ToolExecution(_DomainModel):
    id: str
    project_id: str
    scenario_id: str | None = None
    tool: str
    tool_version: str
    environment: dict[str, str] = Field(default_factory=dict)
    input_refs: list[str] = Field(default_factory=list)
    input_snapshot_hashes: dict[str, str] = Field(default_factory=dict)
    input_artifact_ids: list[str] = Field(default_factory=list)
    input_artifact_hashes_by_id: dict[str, str] = Field(default_factory=dict)
    input_artifact_hashes: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_artifact_refs: list[str] = Field(default_factory=list)
    output_artifact_hashes: list[str] = Field(default_factory=list)
    status: RunStatus = RunStatus.PENDING
    idempotency_key: str
    trace_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("project_id", "tool", "tool_version", "idempotency_key")
    @classmethod
    def execution_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("scenario_id")
    @classmethod
    def execution_scenario_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("input_refs", "input_artifact_ids", "output_artifact_refs", "trace_ids")
    @classmethod
    def execution_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("input_snapshot_hashes", "input_artifact_hashes_by_id")
    @classmethod
    def execution_hash_maps(cls, values: dict[str, str]) -> dict[str, str]:
        return {_id(key): _sha256(value) for key, value in values.items()}

    @field_validator("input_artifact_hashes", "output_artifact_hashes")
    @classmethod
    def execution_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @field_validator("parameters")
    @classmethod
    def finite_execution_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _finite(value)
        return value

    @model_validator(mode="after")
    def succeeded_run_has_artifacts(self) -> "ToolExecution":
        if self.status is RunStatus.SUCCEEDED:
            if not self.output_artifact_refs or not self.output_artifact_hashes:
                raise ValueError("a succeeded tool execution requires output artifact references and hashes")
            if len(self.output_artifact_refs) != len(self.output_artifact_hashes):
                raise ValueError("output artifact references and hashes must have matching lengths")
        return self


class QgisAuditRecord(_DomainModel):
    """Typed audit record for every facade request rejected before dispatch."""

    request_id: str
    operation: str
    status: str
    dispatched: bool
    transport_called: bool
    reason: str
    created_at: datetime
    request_hash: str

    _validate_created_at = field_validator("created_at")(_aware)
    _validate_request_hash = field_validator("request_hash")(_sha256)

    @field_validator("request_id", "operation", "reason")
    @classmethod
    def audit_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("audit text must be non-empty")
        return value.strip()

    @field_validator("status")
    @classmethod
    def audit_status(cls, value: str) -> str:
        value = value.strip().upper() if isinstance(value, str) else value
        if value not in {"REJECTED", "SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN"}:
            raise ValueError("unsupported QGIS audit status")
        return value

    @model_validator(mode="after")
    def denied_request_not_dispatched(self) -> "QgisAuditRecord":
        if self.status == "REJECTED" and (self.dispatched or self.transport_called):
            raise ValueError("a rejected QGIS request cannot be dispatched or call transport")
        return self


class ModelRun(_DomainModel):
    """Structured record of one provider/model adapter invocation."""

    id: str
    provider: str
    model_id: str
    prompt_hash: str
    schema_version: str
    response_hash: str | None = None
    adapter_version: str | None = None
    status: RunStatus = RunStatus.PENDING
    project_id: str | None = None
    scenario_id: str | None = None
    created_at: datetime
    limitations: list[str] = Field(default_factory=list)

    _validate_prompt_hash = field_validator("prompt_hash")(_sha256)
    _validate_response_hash = field_validator("response_hash")(
        lambda value: None if value is None else _sha256(value)
    )
    _validate_created_at = field_validator("created_at")(_aware)

    @field_validator("provider", "model_id", "schema_version")
    @classmethod
    def model_run_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("adapter_version", "project_id", "scenario_id")
    @classmethod
    def optional_model_run_text(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("limitations")
    @classmethod
    def model_run_limitations(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @model_validator(mode="after")
    def successful_model_run_has_response(self) -> "ModelRun":
        if self.status is RunStatus.SUCCEEDED and self.response_hash is None:
            raise ValueError("a succeeded model run requires a response hash")
        return self


class Claim(_DomainModel):
    id: str
    type: ClaimType
    statement: str = Field(validation_alias=AliasChoices("statement", "text"))
    evidence_ids: list[str] = Field(default_factory=list, validation_alias=AliasChoices("evidence_ids", "evidence_refs"))
    assumption_ids: list[str] = Field(default_factory=list)
    scope: str = "unspecified"

    @field_validator("statement")
    @classmethod
    def claim_statement(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("claim statement must be non-empty")
        return value.strip()

    @field_validator("evidence_ids", "assumption_ids", mode="before")
    @classmethod
    def claim_refs(cls, values: Iterable[str] | str | None) -> list[str]:
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        return [_id(value) for value in values]

    @field_validator("scope")
    @classmethod
    def claim_scope(cls, value: str) -> str:
        return _id(value)


class DatasetReference(_DomainModel):
    id: str
    project_id: str | None = None
    version: str | None = None
    sha256: str | None = None

    @field_validator("sha256")
    @classmethod
    def validate_reference_hash(cls, value: str | None) -> str | None:
        return None if value is None else _sha256(value)

    @field_validator("project_id", "version")
    @classmethod
    def optional_reference_text(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)


class MetricReference(_DomainModel):
    id: str
    name: str
    unit: str

    @field_validator("name", "unit")
    @classmethod
    def metric_text(cls, value: str) -> str:
        return _id(value)


class MetricDefinition(_DomainModel):
    """Versioned definition of a deterministic metric used by evidence."""

    id: str
    name: str
    formula: str
    unit: str
    input_refs: list[str] = Field(default_factory=list)
    implementation_version: str
    reference_fixture: str

    @field_validator("name", "formula", "unit", "implementation_version", "reference_fixture")
    @classmethod
    def metric_definition_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("input_refs")
    @classmethod
    def metric_definition_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]


class MethodReference(_DomainModel):
    id: str
    description: str

    @field_validator("description")
    @classmethod
    def method_description(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("method description must be non-empty")
        return value.strip()


class EvidenceResult(_DomainModel):
    artifact_refs: list[str] = Field(default_factory=list)
    artifact_hashes: list[str] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)
    status: ResultStatus
    project_id: str | None = None
    scenario_id: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    units: str | dict[str, str] | None = None
    validation_status: EvidenceValidationStatus = EvidenceValidationStatus.UNVERIFIED

    @field_validator("artifact_refs", "dataset_ids")
    @classmethod
    def result_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("artifact_hashes")
    @classmethod
    def result_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @field_validator("project_id", "scenario_id")
    @classmethod
    def optional_result_ids(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("values")
    @classmethod
    def finite_result_values(cls, value: dict[str, Any]) -> dict[str, Any]:
        _finite(value)
        return value

    @model_validator(mode="after")
    def computed_result_requires_artifact(self) -> "EvidenceResult":
        if self.status is ResultStatus.COMPUTED and not self.artifact_refs:
            raise ValueError("computed result requires at least one artifact reference")
        if self.status is ResultStatus.COMPUTED:
            if not self.artifact_hashes or len(self.artifact_refs) != len(self.artifact_hashes):
                raise ValueError("computed result requires matching artifact references and hashes")
        if self.status is ResultStatus.UNAVAILABLE and self.values:
            raise ValueError("unavailable result cannot contain computed values")
        return self


class Confidence(_DomainModel):
    level: ConfidenceLevel
    basis: str
    uncertainty: str
    assessed_by: str

    @field_validator("basis", "uncertainty", "assessed_by")
    @classmethod
    def confidence_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("confidence text must be non-empty")
        return value.strip()


class EvidenceCard(_DomainModel):
    id: str = Field(validation_alias=AliasChoices("id", "evidence_id"))
    project_id: str
    scenario_id: str | None = None
    input_versions: list[str] = Field(default_factory=list)
    claim: Claim
    source_refs: list[str] = Field(default_factory=list)
    dataset_refs: list[DatasetReference] = Field(default_factory=list)
    metric: MetricReference
    parameters: list[str] = Field(default_factory=list)
    method: MethodReference
    tool: str
    tool_version: str
    result: EvidenceResult
    units: str | dict[str, str]
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: Confidence
    validation_status: EvidenceValidationStatus = EvidenceValidationStatus.UNVERIFIED
    semantic_type: EvidenceSemanticType | None = Field(
        default=None,
        validation_alias=AliasChoices("semantic_type", "evidence_type", "evidence_class"),
    )
    human_status: HumanStatus = HumanStatus.NOT_REVIEWED
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_aware)

    @field_validator("project_id", "tool", "tool_version")
    @classmethod
    def evidence_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("scenario_id")
    @classmethod
    def evidence_scenario_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("input_versions", "source_refs", "parameters", "assumptions")
    @classmethod
    def evidence_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("dataset_refs", mode="before")
    @classmethod
    def dataset_reference_models(cls, values: Iterable[Any]) -> list[Any]:
        if values is None:
            return []
        return [DatasetReference(id=item) if isinstance(item, str) else item for item in values]

    @field_validator("units")
    @classmethod
    def evidence_units(cls, value: str | dict[str, str]) -> str | dict[str, str]:
        if isinstance(value, str):
            return _id(value)
        if not value:
            raise ValueError("units must not be empty")
        return {str(key): _id(unit) for key, unit in value.items()}

    @model_validator(mode="after")
    def local_relationship_checks(self) -> "EvidenceCard":
        if self.result.project_id is not None and self.result.project_id != self.project_id:
            raise ValueError("result project mismatch")
        if self.scenario_id is not None and self.result.scenario_id is not None and self.result.scenario_id != self.scenario_id:
            raise ValueError("result scenario mismatch")
        for reference in self.dataset_refs:
            if reference.project_id is not None and reference.project_id != self.project_id:
                raise ValueError("dataset project mismatch")
        expected_units = _unit_map(self.units, self.result.values)
        metric_units = _unit_map(self.metric.unit, self.result.values)
        if expected_units != metric_units:
            raise ValueError("metric and evidence units mismatch")
        if self.result.units is not None:
            result_units = _unit_map(self.result.units, self.result.values)
            if result_units != expected_units:
                raise ValueError("result and evidence units mismatch")
        if self.validation_status is EvidenceValidationStatus.VALIDATED and self.result.status is ResultStatus.UNAVAILABLE:
            raise ValueError("unavailable result cannot support validated evidence")
        return self

    def validate_relationships(
        self,
        *,
        project: Project,
        scenario: Scenario | None = None,
        datasets: Mapping[str, DatasetSnapshot] | Iterable[DatasetSnapshot] = (),
        tool_execution: ToolExecution | None = None,
        metric: MetricDefinition | None = None,
    ) -> "EvidenceCard":
        """Validate references against authoritative records.

        IDs are intentionally not treated as proof.  Callers must provide the
        records from the project state before a card can support a claim.
        """

        project.assert_compatible(self)
        if self.validation_status is EvidenceValidationStatus.VALIDATED:
            if metric is None:
                raise ValueError("validated evidence requires its metric definition")
            if self.result.status is ResultStatus.COMPUTED and tool_execution is None:
                raise ValueError("validated computed evidence requires its tool execution")
        if metric is not None:
            if metric.id != self.metric.id:
                raise ValueError("metric identifier mismatch")
            if metric.unit != self.metric.unit:
                raise ValueError("metric unit mismatch")
        if scenario is not None:
            project.assert_compatible(scenario)
            if self.scenario_id != scenario.id:
                raise ValueError(f"scenario mismatch: card cites {self.scenario_id}, expected {scenario.id}")
        elif self.scenario_id is not None:
            raise ValueError("scenario reference cannot be validated without its scenario record")

        dataset_map = dict(datasets) if isinstance(datasets, Mapping) else {item.id: item for item in datasets}
        for reference in self.dataset_refs:
            dataset = dataset_map.get(reference.id)
            if dataset is None:
                raise ValueError(f"unresolved dataset reference: {reference.id}")
            try:
                project.assert_compatible(dataset)
            except ValueError as exc:
                raise ValueError(f"dataset project mismatch: {reference.id}") from exc
            if reference.project_id is not None and reference.project_id != dataset.project_id:
                raise ValueError(f"dataset project mismatch: {reference.id}")
            if reference.version is not None and reference.version != dataset.version:
                raise ValueError(f"dataset version mismatch: {reference.id}")
            if reference.sha256 is not None and reference.sha256 != dataset.sha256:
                raise ValueError(f"dataset hash mismatch: {reference.id}")

        if self.result.project_id is not None and self.result.project_id != project.id:
            raise ValueError("result project mismatch")
        if scenario is not None and self.result.scenario_id is not None and self.result.scenario_id != scenario.id:
            raise ValueError("result scenario mismatch")
        if tool_execution is not None:
            project.assert_compatible(tool_execution)
            if tool_execution.scenario_id != self.scenario_id:
                raise ValueError("tool execution scenario mismatch")
            if tool_execution.tool != self.tool or tool_execution.tool_version != self.tool_version:
                raise ValueError("tool execution identity mismatch")
            if tool_execution.status is not RunStatus.SUCCEEDED:
                raise ValueError(
                    f"stale or incomplete tool execution status {tool_execution.status.value} cannot back evidence"
                )
            if tool_execution.output_artifact_refs != self.result.artifact_refs:
                raise ValueError("tool execution and evidence artifact references mismatch")
            if tool_execution.output_artifact_hashes != self.result.artifact_hashes:
                raise ValueError("tool execution and evidence artifact hashes mismatch")
        return self

    # A descriptive alias makes the semantic nature of this check explicit.
    validate_references = validate_relationships

    @property
    def evidence_id(self) -> str:
        return self.id

    @property
    def evidence_type(self) -> EvidenceSemanticType | None:
        return self.semantic_type


def _unit_map(units: str | dict[str, str], values: Mapping[str, Any]) -> dict[str, str]:
    if isinstance(units, str):
        return {str(key): units for key in values} if values else {"__all__": units}
    return dict(units)


class HumanDecision(_DomainModel):
    id: str
    project_id: str
    target_id: str
    target_type: str
    target_version: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "target_version",
            "boundary_version",
            "target_design_boundary_version",
            "design_boundary_version",
            "revision",
            "workspace_revision",
        ),
    )
    target_geometry_sha256: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "target_geometry_sha256",
            "target_geometry_hash",
            "geometry_sha256",
            "geometry_hash",
            "boundary_geometry_sha256",
            "boundary_geometry_hash",
            "design_boundary_geometry_sha256",
            "design_area_geometry_sha256",
            "design_area_geometry_hash",
            "exploration_design_area_geometry_sha256",
            "exploration_design_area_geometry_hash",
        ),
    )
    target_artifact_sha256: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "target_artifact_sha256",
            "target_artifact_hash",
            "artifact_sha256",
            "artifact_hash",
            "boundary_artifact_sha256",
            "boundary_artifact_hash",
        ),
    )
    target_payload_digest: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "target_payload_digest",
            "payload_digest",
            "workspace_payload_digest",
            "workspace_digest",
        ),
    )
    action: DecisionAction
    status: HumanStatus
    actor: str
    actor_kind: ActorKind | None = None
    actor_session_id: str | None = None
    reason: str
    timestamp: datetime
    decision_event_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "decision_event_id",
            "approval_event_id",
            "ledger_event_id",
            "event_id",
        ),
    )
    resulting_refs: list[str] = Field(default_factory=list)
    supersedes: str | None = None

    _validate_timestamp = field_validator("timestamp")(_aware)

    @field_validator("project_id", "target_id", "target_type", "actor")
    @classmethod
    def decision_ids(cls, value: str) -> str:
        return _id(value)

    @field_validator("actor_session_id")
    @classmethod
    def decision_actor_session(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("target_version")
    @classmethod
    def decision_target_version(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _id(str(value))

    @field_validator("target_geometry_sha256", "target_artifact_sha256", "target_payload_digest")
    @classmethod
    def decision_target_hashes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            return f"sha256:{value}"
        return _sha256(value)

    @field_validator("reason")
    @classmethod
    def decision_reason(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("human decision requires a reason")
        return value.strip()

    @field_validator("resulting_refs")
    @classmethod
    def decision_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("decision_event_id")
    @classmethod
    def decision_event_ref(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("supersedes")
    @classmethod
    def decision_supersedes(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @model_validator(mode="after")
    def override_status_is_explicit(self) -> "HumanDecision":
        if self.action is DecisionAction.RECONSIDER and (
            self.target_type != "DesignScenario" or self.status is not HumanStatus.NOT_REVIEWED
        ):
            raise ValueError("Reconsider requires DesignScenario and not_reviewed status")
        if self.action is DecisionAction.OVERRIDE and self.status is not HumanStatus.OVERRIDDEN:
            raise ValueError("override decision must have overridden human status")
        return self

    @property
    def decision_id(self) -> str:
        return self.id


class ContestEvent(_DomainModel):
    """A contestability command that leaves the original state inspectable."""

    id: str
    target_id: str
    action: DecisionAction
    user_reason: str = Field(validation_alias=AliasChoices("user_reason", "reason"))
    resulting_event_id: str = Field(validation_alias=AliasChoices("resulting_event_id", "resulting_event"))
    actor: str
    timestamp: datetime
    project_id: str | None = None
    scenario_id: str | None = None
    parent_event_id: str | None = None
    supersedes: str | None = None

    _validate_timestamp = field_validator("timestamp")(_aware)

    @field_validator("target_id", "user_reason", "resulting_event_id", "actor")
    @classmethod
    def contest_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("project_id", "scenario_id", "parent_event_id", "supersedes")
    @classmethod
    def optional_contest_text(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)


class ProvenanceAnnotation(_DomainModel):
    """Append-only note that qualifies legacy provenance without rewriting it."""

    id: str
    project_id: str
    target_event_id: str
    category: Literal[
        "LEGACY_ACTOR_LABEL_UNVERIFIED",
        "AUTOMATION_GUI_OPERATION_MISATTRIBUTED",
    ] | str
    source_actor_label: str
    source_actor_kind: ActorKind | None = None
    rationale: str
    related_revision_refs: list[str] = Field(default_factory=list)

    @field_validator("id", "project_id", "target_event_id", "source_actor_label")
    @classmethod
    def annotation_ids(cls, value: str) -> str:
        return _id(value)

    @field_validator("related_revision_refs")
    @classmethod
    def annotation_revision_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("rationale")
    @classmethod
    def annotation_rationale(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("provenance annotation requires a rationale")
        return value.strip()


class DesignLedgerEvent(_DomainModel):
    id: str
    project_id: str
    timestamp: datetime
    actor: str
    actor_kind: ActorKind | None = None
    actor_session_id: str | None = None
    action: LedgerAction
    target_id: str
    prior_status: str
    changed_refs: list[str] = Field(default_factory=list)
    resulting_refs: list[str] = Field(default_factory=list)
    reason: str
    supersedes: str | None = None
    project_revision: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = None

    _validate_timestamp = field_validator("timestamp")(_aware)

    @field_validator("project_id", "actor", "target_id", "prior_status")
    @classmethod
    def event_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("actor_session_id")
    @classmethod
    def ledger_actor_session(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @field_validator("changed_refs", "resulting_refs")
    @classmethod
    def event_refs(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("reason")
    @classmethod
    def event_reason(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("ledger event requires a reason")
        return value.strip()

    @field_validator("supersedes", "idempotency_key")
    @classmethod
    def optional_event_ids(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @property
    def event_id(self) -> str:
        return self.id


class ExperimentOffset(_DomainModel):
    offset: float
    unit: str
    feasible: bool = True

    @field_validator("offset")
    @classmethod
    def finite_offset(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("offset cannot be NaN or infinite")
        return value

    @field_validator("unit")
    @classmethod
    def offset_unit(cls, value: str) -> str:
        return _id(value)


class ExperimentPlan(_DomainModel):
    id: str
    project_id: str
    scenario_id: str
    selected_building_id: str
    independent_variable: str
    dependent_variables: list[str] = Field(default_factory=list)
    axis: str
    baseline: ExperimentOffset
    offsets: list[ExperimentOffset]
    locked_conditions: dict[str, Any]
    method_tiers: list[str]
    approval_status: ExperimentApprovalStatus = ExperimentApprovalStatus.PROPOSED
    approved_by: str | None = None
    approved_at: datetime | None = None

    @field_validator("approved_at")
    @classmethod
    def validate_optional_approved_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)

    @field_validator("project_id", "scenario_id", "selected_building_id", "independent_variable", "axis")
    @classmethod
    def experiment_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("dependent_variables", "method_tiers")
    @classmethod
    def experiment_lists(cls, values: list[str]) -> list[str]:
        return [_id(value) for value in values]

    @field_validator("locked_conditions")
    @classmethod
    def finite_locked_conditions(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("experiment locked_conditions must be explicit")
        _finite(value)
        return value

    @field_validator("approved_by")
    @classmethod
    def optional_approver(cls, value: str | None) -> str | None:
        return None if value is None else _id(value)

    @model_validator(mode="after")
    def exactly_two_offsets_and_approval(self) -> "ExperimentPlan":
        if len(self.offsets) != 2:
            raise ValueError("experiment plan requires exactly two offsets")
        if self.baseline.offset != 0:
            raise ValueError("experiment baseline offset must be zero")
        if any(not offset.feasible for offset in self.offsets):
            raise ValueError("experiment offsets must be marked feasible")
        if any(offset.unit != self.baseline.unit for offset in self.offsets):
            raise ValueError("experiment offsets and baseline must use the same unit")
        if self.approval_status is ExperimentApprovalStatus.APPROVED and not self.approved_by:
            raise ValueError("approved experiment plan requires approved_by")
        if self.approval_status is ExperimentApprovalStatus.APPROVED and self.approved_at is None:
            raise ValueError("approved experiment plan requires approved_at")
        if len(self.method_tiers) < 2:
            raise ValueError("experiment plan requires screening and verification method tiers")
        tier_names = {tier.casefold() for tier in self.method_tiers}
        if not any("screen" in tier for tier in tier_names) or not any(
            "verif" in tier for tier in tier_names
        ):
            raise ValueError("experiment plan must name screening and verification method tiers")
        return self

    @property
    def plan_id(self) -> str:
        return self.id


# Vocabulary aliases used by the architecture and by later milestones.
SiteModel = Site
DataSnapshot = DatasetSnapshot
DesignScenario = Scenario
ToolRun = ToolExecution
EvidenceRecord = EvidenceCard
LedgerEvent = DesignLedgerEvent
EvidenceType = EvidenceSemanticType
FormalClaim = FormalClaimType


__all__ = [
    "ActorKind",
    "Claim",
    "ClaimType",
    "Confidence",
    "ConfidenceLevel",
    "canonical_units_for_crs",
    "Artifact",
    "Assumption",
    "AssumptionStatus",
    "ContestEvent",
    "Constraint",
    "ConstraintSet",
    "ConstraintStatus",
    "DataSnapshot",
    "DatasetReference",
    "DatasetSnapshot",
    "DecisionAction",
    "DesignBoundary",
    "DesignBoundaryStatus",
    "DesignLedgerEvent",
    "DesignScenario",
    "EvidenceCard",
    "EvidenceRecord",
    "EvidenceResult",
    "EvidenceSemanticType",
    "EvidenceType",
    "EvidenceValidationStatus",
    "ExplorationStage",
    "ExperimentApprovalStatus",
    "ExperimentOffset",
    "ExperimentPlan",
    "HumanDecision",
    "HumanStatus",
    "LedgerAction",
    "LedgerEvent",
    "MetricDefinition",
    "MethodReference",
    "MetricReference",
    "ModelRun",
    "ParameterAlternative",
    "ParameterDefinition",
    "ParameterStatus",
    "Project",
    "ProjectStatus",
    "ProvenanceAnnotation",
    "QgisAuditRecord",
    "ResultStatus",
    "RunStatus",
    "Scenario",
    "ScenarioStatus",
    "Site",
    "SiteModel",
    "SiteStatus",
    "StudyArea",
    "StudyAreaSource",
    "StudyAreaStatus",
    "SourceType",
    "FormalClaimType",
    "FormalClaim",
    "ToolExecution",
    "ToolRun",
    "UnavailableValue",
]
