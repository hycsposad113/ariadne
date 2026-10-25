"""Human-confirmed Study Area workflow for early exploration.

The Study Area is an exploration envelope drawn and saved by the designer.  It
is intentionally weaker than a formal DesignBoundary: its confirmation proves
only that the retained polygon may be used by the four exploratory stages.  A
formal cadastral, ownership, zoning, or legal-buildability claim still needs an
explicitly approved DesignBoundary backed by HumanDecision data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from pyproj import CRS
from shapely.geometry import shape

from .geometry import GeometryValidationError, canonical_geometry_hash, validate_geometry
from .models import (
    ActorKind,
    Artifact,
    DecisionAction,
    DesignBoundary,
    DesignBoundaryStatus,
    EvidenceSemanticType,
    ExplorationStage,
    FormalClaimType,
    HumanDecision,
    HumanStatus,
    StudyArea,
    StudyAreaSource,
    StudyAreaStatus,
    canonical_units_for_crs,
)
from .project_anchor import ProjectAnchorError, ProjectGeographicAnchor
from .store import EntityNotFoundError, PayloadError, ProjectStateStore, StateRecord, StoreError


class StudyAreaValidationError(ValueError):
    """Raised when a saved Study Area artifact is not exploration-safe."""


class StudyAreaConfirmationError(StudyAreaValidationError):
    """Raised when a confirmation cannot be committed to project state."""


class FormalClaimGuardError(ValueError):
    """Raised when a formal claim is attempted without an approved boundary."""


FORMAL_CLAIM_TYPES = frozenset(item.value for item in FormalClaimType)
EXPLORATION_STAGES = tuple(ExplorationStage)
STUDY_AREA_ARTIFACT_TYPE = "study_area_geometry"
STUDY_AREA_ARTIFACT_MIME = "application/geo+json"
STUDY_AREA_ARTIFACT_PRODUCER = "QGIS"


@dataclass(frozen=True)
class ValidatedStudyAreaArtifact:
    """Deterministic facts re-read from a saved polygon artifact."""

    geometry: dict[str, Any]
    geometry_sha256: str
    artifact_sha256: str
    size_bytes: int
    horizontal_crs: str
    units: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "geometry": self.geometry,
            "geometry_sha256": self.geometry_sha256,
            "artifact_sha256": self.artifact_sha256,
            "size_bytes": self.size_bytes,
            "horizontal_crs": self.horizontal_crs,
            "units": self.units,
        }


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StudyAreaValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise StudyAreaConfirmationError("confirmed_at must include a timezone")
    return value


def _extract_crs(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            for key in ("name", "href", "code"):
                item = properties.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
        for key in ("name", "href", "code"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _normalise_projected_crs(value: Any) -> str:
    candidate = _nonempty(value, "horizontal_crs")
    try:
        parsed = CRS.from_user_input(candidate)
    except Exception as exc:
        raise StudyAreaValidationError("horizontal_crs must be a valid projected CRS") from exc
    if not parsed.is_projected:
        raise StudyAreaValidationError("horizontal_crs must be projected")
    authority = parsed.to_authority()
    if authority:
        return f"{authority[0].upper()}:{authority[1]}"
    return parsed.to_string()


def _unit_candidates(payload: Mapping[str, Any], explicit: str | None) -> list[str]:
    candidates: list[str] = []
    if explicit is not None:
        candidates.append(explicit)
    root = payload.get("units")
    if isinstance(root, str) and root.strip():
        candidates.append(root.strip())
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        item = metadata.get("units")
        if isinstance(item, str) and item.strip():
            candidates.append(item.strip())
    properties = payload.get("properties")
    if isinstance(properties, Mapping):
        item = properties.get("units")
        if isinstance(item, str) and item.strip():
            candidates.append(item.strip())
    return candidates


def _extract_units(payload: Mapping[str, Any], explicit: str | None) -> str | None:
    """Return the first declared unit; compatibility is checked after CRS parsing."""

    candidates = _unit_candidates(payload, explicit)
    return _nonempty(candidates[0], "units") if candidates else None


def _crs_candidates(payload: Mapping[str, Any]) -> list[str]:
    candidates: list[str] = []
    for candidate in (payload.get("crs"),):
        extracted = _extract_crs(candidate)
        if extracted:
            candidates.append(extracted)
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        extracted = _extract_crs(metadata.get("crs"))
        if extracted:
            candidates.append(extracted)
    properties = payload.get("properties")
    if isinstance(properties, Mapping):
        extracted = _extract_crs(properties.get("crs"))
        if extracted:
            candidates.append(extracted)
    return candidates


def _extract_geometry(payload: Mapping[str, Any]) -> dict[str, Any]:
    payload_type = payload.get("type")
    if payload_type is None and isinstance(payload.get("geometry"), Mapping):
        geometry = payload.get("geometry")
    elif payload_type in {"Polygon", "MultiPolygon"}:
        geometry = {"type": payload_type, "coordinates": payload.get("coordinates")}
    elif payload_type == "Feature":
        geometry = payload.get("geometry")
    elif payload_type == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise StudyAreaValidationError(
                "Study Area FeatureCollection must contain exactly one polygon feature"
            )
        feature = features[0]
        geometry = feature.get("geometry") if isinstance(feature, Mapping) else None
    else:
        geometry = None
    if not isinstance(geometry, Mapping):
        raise StudyAreaValidationError("artifact must contain Polygon or MultiPolygon geometry")
    geometry_type = geometry.get("type")
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise StudyAreaValidationError("Study Area geometry must be Polygon or MultiPolygon")
    return {"type": geometry_type, "coordinates": geometry.get("coordinates")}


@dataclass(frozen=True)
class _ArtifactInput:
    """Resolved artifact input plus any persisted metadata supplied by the caller."""

    artifact_id: str | None
    source: Any
    metadata: Mapping[str, Any]
    persisted: StateRecord | None
    explicit_id: bool


def _resolve_local_path(artifact: str | Path, *, artifact_root: str | Path | None = None) -> Path:
    raw_value = str(artifact)
    parsed = urlparse(raw_value)
    if parsed.scheme and parsed.scheme != "file":
        raise StudyAreaValidationError("Study Area artifact URI must be a local file path")
    if parsed.scheme == "file":
        if parsed.netloc not in {"", "localhost"}:
            raise StudyAreaValidationError("Study Area artifact file URI must be local")
        raw_value = unquote(parsed.path)
    path = Path(raw_value).expanduser()
    if artifact_root is not None and not path.is_absolute():
        path = Path(artifact_root) / path
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise StudyAreaValidationError("Study Area artifact does not exist") from exc
    if not resolved.is_file():
        raise StudyAreaValidationError("Study Area artifact must be a regular file")
    if artifact_root is not None:
        root = Path(artifact_root).expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise StudyAreaValidationError("Study Area artifact is outside the artifact root") from exc
    return resolved


def _canonical_artifact_uri(
    source: str | Path | Mapping[str, Any],
    *,
    artifact_root: str | Path | None,
    artifact_sha256: str,
) -> str:
    if isinstance(source, Mapping):
        return "artifact://" + artifact_sha256.removeprefix("sha256:")
    return str(_resolve_local_path(source, artifact_root=artifact_root))


def _comparable_artifact_uri(value: Any, *, artifact_root: str | Path | None = None) -> str:
    """Normalize local path/file-URI spellings for retained artifact comparison."""

    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return str(_resolve_local_path(value, artifact_root=artifact_root))
    except StudyAreaValidationError:
        return value.strip()


def _read_artifact(
    artifact: str | Path | Mapping[str, Any],
    *,
    artifact_root: str | Path | None = None,
) -> tuple[bytes, Mapping[str, Any]]:
    if isinstance(artifact, Mapping):
        try:
            encoded = json.dumps(
                artifact,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise StudyAreaValidationError("artifact mapping must be JSON serializable") from exc
        return encoded, artifact

    resolved = _resolve_local_path(artifact, artifact_root=artifact_root)
    try:
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StudyAreaValidationError("Study Area artifact must be UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise StudyAreaValidationError("Study Area artifact must encode a JSON object")
    return raw, payload


def validate_study_area_artifact(
    artifact: str | Path | Mapping[str, Any],
    *,
    expected_sha256: str | None = None,
    horizontal_crs: str | None = None,
    units: str | None = None,
    expected_geometry_sha256: str | None = None,
    artifact_root: str | Path | None = None,
    project_anchor: ProjectGeographicAnchor | None = None,
) -> ValidatedStudyAreaArtifact:
    """Re-read a saved QGIS polygon and validate only exploration prerequisites."""

    raw, payload = _read_artifact(artifact, artifact_root=artifact_root)
    actual_artifact_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual_artifact_hash != expected_sha256:
        raise StudyAreaValidationError("Study Area artifact hash does not match retained metadata")
    try:
        geometry = _extract_geometry(payload)
        validate_geometry(geometry)
    except GeometryValidationError as exc:
        raise StudyAreaValidationError(str(exc)) from exc
    try:
        planar = shape(geometry)
    except Exception as exc:
        raise StudyAreaValidationError("Study Area geometry could not be parsed") from exc
    if planar.is_empty or not planar.is_valid:
        raise StudyAreaValidationError("Study Area polygon must be non-empty and valid")
    area = float(planar.area)
    if not math_is_finite_positive(area):
        raise StudyAreaValidationError("Study Area polygon area must be finite and positive")

    embedded_candidates = _crs_candidates(payload)
    embedded_crs = embedded_candidates[0] if embedded_candidates else None
    effective_crs = horizontal_crs or embedded_crs
    if effective_crs is None:
        raise StudyAreaValidationError("Study Area requires an explicit horizontal CRS")
    effective_crs = _normalise_projected_crs(effective_crs)
    if embedded_candidates:
        try:
            embedded_parsed = [CRS.from_user_input(candidate) for candidate in embedded_candidates]
            if any(not embedded_parsed[0].equals(candidate) for candidate in embedded_parsed[1:]):
                raise StudyAreaValidationError("artifact CRS declarations do not match")
            if horizontal_crs is not None and not CRS.from_user_input(horizontal_crs).equals(embedded_parsed[0]):
                raise StudyAreaValidationError("artifact and confirmation CRS do not match")
        except StudyAreaValidationError:
            raise
        except Exception as exc:
            raise StudyAreaValidationError("artifact CRS is invalid") from exc
    unit_candidates = _unit_candidates(payload, units)
    if not unit_candidates:
        raise StudyAreaValidationError("Study Area requires explicit units")
    try:
        canonical_units = [canonical_units_for_crs(effective_crs, item) for item in unit_candidates]
    except ValueError as exc:
        raise StudyAreaValidationError(str(exc)) from exc
    if any(item != canonical_units[0] for item in canonical_units[1:]):
        raise StudyAreaValidationError("artifact and confirmation units do not match")
    effective_units = canonical_units[0]
    if project_anchor is not None:
        if project_anchor.horizontal_crs.casefold() != effective_crs.casefold():
            raise StudyAreaValidationError("Study Area CRS does not match the configured project anchor")
        try:
            project_anchor.validate_geometry(geometry)
        except ProjectAnchorError as exc:
            raise StudyAreaValidationError(str(exc)) from exc
    geometry_hash = canonical_geometry_hash(geometry)
    if expected_geometry_sha256 is not None and geometry_hash != expected_geometry_sha256:
        raise StudyAreaValidationError("Study Area geometry hash does not match retained metadata")
    return ValidatedStudyAreaArtifact(
        geometry=geometry,
        geometry_sha256=geometry_hash,
        artifact_sha256=actual_artifact_hash,
        size_bytes=len(raw),
        horizontal_crs=effective_crs,
        units=effective_units,
    )


def math_is_finite_positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


def validate_study_area_geometry(
    geometry: Mapping[str, Any],
    *,
    horizontal_crs: str,
    units: str,
    project_anchor: ProjectGeographicAnchor | None = None,
) -> dict[str, Any]:
    """Validate an in-memory polygon with the same Study Area preconditions."""

    if not isinstance(geometry, Mapping):
        raise StudyAreaValidationError("geometry must be an object")
    payload = {
        "type": "Feature",
        "geometry": dict(geometry),
        "crs": {"type": "name", "properties": {"name": horizontal_crs}},
        "units": units,
    }
    # This helper is intentionally deterministic and uses the same checks as a
    # saved artifact; the hash is for the canonical in-memory geometry.
    result = validate_study_area_artifact(
        payload,
        horizontal_crs=horizontal_crs,
        units=units,
        project_anchor=project_anchor,
    )
    return result.as_dict()


def _coerce_claim_type(claim_type: FormalClaimType | str) -> str:
    if isinstance(claim_type, str) and hasattr(claim_type, "value"):
        return str(getattr(claim_type, "value"))
    text = _nonempty(claim_type, "claim_type").upper().replace("-", "_")
    return text


def _coerce_boundary(value: DesignBoundary | Mapping[str, Any] | StateRecord) -> DesignBoundary:
    if isinstance(value, DesignBoundary):
        return value
    if isinstance(value, StateRecord):
        if value.entity_type != "DesignBoundary":
            raise FormalClaimGuardError("formal claim target must be a DesignBoundary record")
        value = value.payload
    try:
        return DesignBoundary.model_validate(value)
    except (TypeError, ValueError) as exc:
        raise FormalClaimGuardError(
            "formal claim requires valid HumanDecision-backed DesignBoundary data"
        ) from exc


def _coerce_human_decision(value: Any) -> HumanDecision:
    if isinstance(value, HumanDecision):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise FormalClaimGuardError(
            "approved DesignBoundary requires a complete typed HumanDecision payload"
        )
    try:
        return HumanDecision.model_validate(value)
    except (TypeError, ValueError) as exc:
        raise FormalClaimGuardError(
            "approved DesignBoundary requires a complete typed HumanDecision payload"
        ) from exc


def _decision_relationship(
    boundary: DesignBoundary,
    decision: HumanDecision,
    *,
    require_decision_event_id: bool = True,
) -> None:
    """Validate the semantic relationship between a boundary and its decision."""

    if boundary.human_decision_id is None or boundary.human_decision_id != decision.id:
        raise FormalClaimGuardError("HumanDecision id does not match DesignBoundary human_decision_id")
    if decision.project_id != boundary.project_id:
        raise FormalClaimGuardError("HumanDecision project does not match DesignBoundary project")
    if decision.target_id != boundary.id:
        raise FormalClaimGuardError("HumanDecision target does not match DesignBoundary")
    if decision.target_type.casefold().replace("_", "") != "designboundary":
        raise FormalClaimGuardError("HumanDecision target_type must be DesignBoundary")
    if decision.target_version is None or decision.target_version != boundary.version:
        raise FormalClaimGuardError("HumanDecision target version does not match DesignBoundary")
    if decision.target_geometry_sha256 is None or decision.target_geometry_sha256 != boundary.geometry_sha256:
        raise FormalClaimGuardError("HumanDecision target geometry hash does not match DesignBoundary")
    if boundary.artifact_sha256 is not None:
        if decision.target_artifact_sha256 is None or decision.target_artifact_sha256 != boundary.artifact_sha256:
            raise FormalClaimGuardError("HumanDecision target artifact hash does not match DesignBoundary")
    elif decision.target_artifact_sha256 is not None:
        raise FormalClaimGuardError("HumanDecision target artifact hash has no matching DesignBoundary value")
    if decision.actor_kind is not ActorKind.HUMAN_UI:
        raise FormalClaimGuardError("HumanDecision must identify an authenticated HUMAN_UI actor")
    if not isinstance(decision.actor_session_id, str) or not decision.actor_session_id.strip():
        raise FormalClaimGuardError("HumanDecision must include a non-empty actor session")
    if decision.action not in {DecisionAction.APPROVE, DecisionAction.ACCEPT}:
        raise FormalClaimGuardError("HumanDecision must record an explicit approve or accept action")
    if decision.status not in {HumanStatus.APPROVED, HumanStatus.ACCEPTED}:
        raise FormalClaimGuardError("HumanDecision status must be approved or accepted")
    if decision.decision_event_id is None and (
        require_decision_event_id or boundary.approval_event_id is None
    ):
        raise FormalClaimGuardError("HumanDecision must reference a decision ledger event")
    for name, boundary_value, decision_value in (
        ("actor", boundary.approval_actor, decision.actor),
        ("reason", boundary.approval_reason, decision.reason),
        ("event", boundary.approval_event_id, decision.decision_event_id),
    ):
        if name == "event" and decision_value is None and boundary_value is not None:
            continue
        if boundary_value is not None and boundary_value != decision_value:
            raise FormalClaimGuardError(f"DesignBoundary approval {name} does not match HumanDecision")
    if boundary.approval_timestamp is not None and boundary.approval_timestamp != decision.timestamp:
        raise FormalClaimGuardError("DesignBoundary approval timestamp does not match HumanDecision")


def _decision_event_authorizes(
    boundary: DesignBoundary,
    decision: HumanDecision,
    store: ProjectStateStore,
) -> None:
    events = store.events(project_id=boundary.project_id)
    explicit_event_id = decision.decision_event_id or boundary.approval_event_id
    if explicit_event_id is not None:
        candidates = [event for event in events if event.event_id == explicit_event_id]
    else:
        candidates = [
            event
            for event in events
            if event.target_id in {boundary.id, decision.id}
            and event.action.casefold() in {"create", "approve", "accept"}
        ]
    if not candidates:
        raise FormalClaimGuardError("referenced HumanDecision ledger event does not exist")
    authorized = False
    for event in candidates:
        if (
            event.project_id != boundary.project_id
            or event.actor != decision.actor
            or event.actor_kind is not ActorKind.HUMAN_UI
            or not isinstance(event.actor_session_id, str)
            or not event.actor_session_id.strip()
            or event.actor_session_id != decision.actor_session_id
            or event.reason != decision.reason
            or str(event.timestamp) != decision.timestamp.isoformat()
        ):
            continue
        action = event.action.casefold()
        if event.target_id == boundary.id:
            if (event.target_type or "").casefold().replace("_", "") != "designboundary":
                continue
            if action not in {"approve", "accept"}:
                continue
            payload = event.payload or {}
            if (
                payload.get("decision_id") != decision.id
                or payload.get("target_version") != decision.target_version
                or payload.get("target_geometry_sha256") != decision.target_geometry_sha256
                or payload.get("target_artifact_sha256") != decision.target_artifact_sha256
            ):
                continue
        elif event.target_id == decision.id:
            if (event.target_type or "").casefold().replace("_", "") != "humandecision":
                continue
            if action not in {"approve", "accept"} or event.action != decision.action.value:
                continue
            payload = event.payload or {}
            if (
                payload.get("target_geometry_sha256") != decision.target_geometry_sha256
                or payload.get("target_artifact_sha256") != decision.target_artifact_sha256
            ):
                continue
        else:
            continue
        authorized = True
        break
    if not authorized:
        raise FormalClaimGuardError("HumanDecision ledger event does not authorize this boundary")


def validate_formal_claim(
    claim_type: FormalClaimType | str,
    *,
    design_boundary: DesignBoundary | Mapping[str, Any] | StateRecord | None = None,
    store: ProjectStateStore | None = None,
) -> None:
    """Fail closed for formal claims without a HumanDecision-approved boundary."""

    normalized = _coerce_claim_type(claim_type)
    if normalized not in {item.value for item in FormalClaimType}:
        return
    if design_boundary is None:
        raise FormalClaimGuardError(
            f"formal claim {normalized} requires an approved DesignBoundary backed by HumanDecision"
        )
    boundary = _coerce_boundary(design_boundary)
    if boundary.status is not DesignBoundaryStatus.APPROVED:
        raise FormalClaimGuardError(
            f"formal claim {normalized} requires DesignBoundary status APPROVED"
        )
    if store is None:
        portable_payload = boundary.human_decision
        if portable_payload is None:
            raise FormalClaimGuardError(
                f"formal claim {normalized} requires a complete typed HumanDecision payload"
            )
        portable_decision = _coerce_human_decision(portable_payload)
        _decision_relationship(boundary, portable_decision)
        return

    portable_payload = boundary.human_decision
    portable_decision = _coerce_human_decision(portable_payload) if portable_payload is not None else None
    decision_id = boundary.human_decision_id or (portable_decision.id if portable_decision is not None else None)
    if decision_id is None:
        raise FormalClaimGuardError("approved DesignBoundary requires a HumanDecision identifier")
    try:
        persisted_record = store.current(decision_id)
    except EntityNotFoundError as exc:
        raise FormalClaimGuardError("persisted HumanDecision record does not exist") from exc
    if persisted_record.entity_type != "HumanDecision":
        raise FormalClaimGuardError("human_decision_id must resolve to a HumanDecision record")
    try:
        persisted_decision = HumanDecision.model_validate(persisted_record.payload)
    except (TypeError, ValueError) as exc:
        raise FormalClaimGuardError("persisted HumanDecision record is invalid") from exc
    _decision_relationship(
        boundary,
        persisted_decision,
        require_decision_event_id=boundary.approval_event_id is None,
    )
    if portable_decision is not None:
        _decision_relationship(
            boundary,
            portable_decision,
            require_decision_event_id=boundary.approval_event_id is None,
        )
        if portable_decision.model_dump(mode="json") != persisted_decision.model_dump(mode="json"):
            raise FormalClaimGuardError("portable HumanDecision conflicts with persisted authorization")
    _decision_event_authorizes(boundary, persisted_decision, store)


require_approved_design_boundary = validate_formal_claim
guard_formal_claim = validate_formal_claim
authorize_formal_claim = validate_formal_claim


def can_make_formal_claim(
    claim_type: FormalClaimType | str,
    *,
    design_boundary: DesignBoundary | Mapping[str, Any] | StateRecord | None = None,
    store: ProjectStateStore | None = None,
) -> bool:
    """Boolean adapter for UIs; the command guard remains fail-closed."""

    try:
        validate_formal_claim(claim_type, design_boundary=design_boundary, store=store)
    except (FormalClaimGuardError, StudyAreaValidationError, ValueError):
        return False
    return True


formal_claim_allowed = can_make_formal_claim


def validate_exploration_scope(
    study_area: StudyArea | Mapping[str, Any] | StateRecord,
    stage: ExplorationStage | str,
    *,
    design_boundary: DesignBoundary | Mapping[str, Any] | None = None,
    store: ProjectStateStore | None = None,
) -> None:
    """Allow all four exploratory stages after StudyArea confirmation.

    ``design_boundary`` is accepted for callers that already have one, but it
    is intentionally not required by this guard.
    """

    if isinstance(study_area, StudyArea):
        area = study_area
    elif isinstance(study_area, StateRecord):
        area = StudyArea.model_validate(study_area.payload)
    else:
        area = StudyArea.model_validate(study_area)
    try:
        selected_stage = stage if isinstance(stage, ExplorationStage) else ExplorationStage(stage)
    except ValueError as exc:
        raise StudyAreaValidationError("stage must be UNDERSTAND, EXPLORE, TEST, or REFINE") from exc
    if area.status is not StudyAreaStatus.CONFIRMED_FOR_EXPLORATION:
        raise StudyAreaConfirmationError(
            f"{selected_stage.value} requires StudyArea status CONFIRMED_FOR_EXPLORATION"
        )
    if store is not None:
        authorize_exploration_scope(store, area, selected_stage)


def authorize_exploration_scope(
    store: ProjectStateStore,
    study_area: StudyArea | Mapping[str, Any] | StateRecord,
    stage: ExplorationStage | str,
) -> None:
    """Authorize an exploration stage against persisted state and ledger events.

    The in-memory record is treated as a candidate only.  A matching current
    StudyArea head, project pointer, confirmation event, and later activation
    event are all required before a stage can run.
    """

    if not isinstance(store, ProjectStateStore):
        raise StudyAreaConfirmationError("runtime exploration authorization requires a ProjectStateStore")
    if isinstance(study_area, StudyArea):
        area = study_area
    elif isinstance(study_area, StateRecord):
        try:
            area = StudyArea.model_validate(study_area.payload)
        except (TypeError, ValueError) as exc:
            raise StudyAreaConfirmationError("persisted StudyArea payload is invalid") from exc
    else:
        try:
            area = StudyArea.model_validate(study_area)
        except (TypeError, ValueError) as exc:
            raise StudyAreaConfirmationError("StudyArea payload is invalid") from exc
    try:
        selected_stage = stage if isinstance(stage, ExplorationStage) else ExplorationStage(stage)
    except ValueError as exc:
        raise StudyAreaValidationError("stage must be UNDERSTAND, EXPLORE, TEST, or REFINE") from exc
    if area.status is not StudyAreaStatus.CONFIRMED_FOR_EXPLORATION:
        raise StudyAreaConfirmationError(
            f"{selected_stage.value} requires StudyArea status CONFIRMED_FOR_EXPLORATION"
        )
    try:
        persisted_record = store.current(area.id)
    except EntityNotFoundError as exc:
        raise StudyAreaConfirmationError("StudyArea is not persisted") from exc
    if persisted_record.entity_type != "StudyArea" or persisted_record.project_id != area.project_id:
        raise StudyAreaConfirmationError("persisted StudyArea project or entity type does not match")
    try:
        persisted_area = StudyArea.model_validate(persisted_record.payload)
    except (TypeError, ValueError) as exc:
        raise StudyAreaConfirmationError("persisted StudyArea payload is invalid") from exc
    for field in (
        "id",
        "project_id",
        "version",
        "geometry_artifact_id",
        "geometry_sha256",
        "artifact_sha256",
        "horizontal_crs",
        "units",
        "confirmation_event_id",
        "confirmed_actor",
        "status",
    ):
        if getattr(area, field) != getattr(persisted_area, field):
            raise StudyAreaConfirmationError(f"in-memory StudyArea {field} does not match persisted state")

    try:
        artifact_record = store.current(area.geometry_artifact_id)
    except EntityNotFoundError as exc:
        raise StudyAreaConfirmationError("StudyArea geometry Artifact is not persisted") from exc
    if artifact_record.entity_type != "Artifact" or artifact_record.project_id != area.project_id:
        raise StudyAreaConfirmationError("StudyArea geometry Artifact project or type does not match")
    if area.artifact_sha256 is not None and artifact_record.get("sha256") != area.artifact_sha256:
        raise StudyAreaConfirmationError("StudyArea geometry Artifact hash does not match")

    try:
        project = store.current(area.project_id)
    except EntityNotFoundError as exc:
        raise StudyAreaConfirmationError("StudyArea project is not persisted") from exc
    if project.entity_type != "Project" or project.get("active_study_area_id") != area.id:
        raise StudyAreaConfirmationError("project active_study_area_id does not match StudyArea")

    events = store.events(project_id=area.project_id)
    confirmation_events = [
        event
        for event in events
        if event.event_id == area.confirmation_event_id
        and event.action.casefold() == "confirmstudyarea"
        and event.target_id == area.id
        and (event.target_type or "").casefold() == "studyarea"
        and event.project_id == area.project_id
        and event.payload.get("study_area_id") == area.id
        and event.payload.get("geometry_sha256", event.payload.get("geometry_hash")) == area.geometry_sha256
        and event.actor == area.confirmed_actor
    ]
    if not confirmation_events:
        raise StudyAreaConfirmationError("matching ConfirmStudyArea event is missing or invalid")
    confirmation = confirmation_events[-1]
    activation_events = [
        event
        for event in events
        if event.action.casefold() == "activatestudyarea"
        and event.target_id == area.project_id
        and (event.target_type or "").casefold() == "project"
        and event.project_id == area.project_id
        and event.payload.get("active_study_area_id") == area.id
        and event.payload.get("confirmation_event_id") == area.confirmation_event_id
        and event.payload.get("geometry_sha256", event.payload.get("geometry_hash")) == area.geometry_sha256
        and event.sequence > confirmation.sequence
    ]
    if not activation_events:
        raise StudyAreaConfirmationError("matching ActivateStudyArea event is missing or invalid")


runtime_exploration_allowed = authorize_exploration_scope
assert_exploration_authorized = authorize_exploration_scope


exploratory_scope_allowed = validate_exploration_scope
assert_exploration_allowed = validate_exploration_scope


def can_explore(
    study_area: StudyArea | Mapping[str, Any] | StateRecord,
    stage: ExplorationStage | str,
    *,
    store: ProjectStateStore | None = None,
) -> bool:
    try:
        validate_exploration_scope(study_area, stage, store=store)
    except (StudyAreaValidationError, ValueError):
        return False
    return True


def evidence_semantic_contract(
    semantic_type: EvidenceSemanticType | str,
    *,
    numeric_values: Mapping[str, Any] | None = None,
    formal_claim_type: FormalClaimType | str | None = None,
) -> None:
    """Validate the semantic limits of AI interpretations and data gaps.

    AI interpretation and hypothesis records can suggest risks or next
    analyses, but cannot carry numerical values or formal legal/ownership
    conclusions.  Dataset observations and computed results remain the source
    of numerical evidence.
    """

    if isinstance(semantic_type, EvidenceSemanticType):
        selected = semantic_type
    else:
        try:
            selected = EvidenceSemanticType(semantic_type)
        except ValueError as exc:
            raise StudyAreaValidationError("unsupported evidence semantic type") from exc
    if selected in {EvidenceSemanticType.AI_INTERPRETATION, EvidenceSemanticType.HYPOTHESIS}:
        if numeric_values:
            raise StudyAreaValidationError(
                f"{selected.value} cannot author numerical values; cite a computed result instead"
            )
        if formal_claim_type is not None and _coerce_claim_type(formal_claim_type) in {
            item.value for item in FormalClaimType
        }:
            raise StudyAreaValidationError(
                f"{selected.value} cannot establish formal claim {_coerce_claim_type(formal_claim_type)}"
            )
    if selected is EvidenceSemanticType.DATA_GAP and numeric_values:
        raise StudyAreaValidationError("DATA_GAP cannot contain computed numerical values")


def is_stale_dependency(
    record_or_payload: StateRecord | Mapping[str, Any],
    *,
    previous_study_area_id: str,
    previous_geometry_sha256: str,
) -> bool:
    """Deterministically detect an explicit dependency on a superseded area."""

    payload = (
        record_or_payload.payload
        if isinstance(record_or_payload, StateRecord)
        else record_or_payload
    )
    if not isinstance(payload, Mapping):
        return False
    id_keys = {
        "study_area_id",
        "input_study_area_id",
        "study_area_ref",
        "study_area_reference",
    }
    hash_keys = {
        "study_area_geometry_sha256",
        "input_study_area_geometry_sha256",
        "study_area_hash",
        "input_study_area_hash",
        "geometry_input_sha256",
    }
    collection_keys = {
        "input_refs",
        "input_artifact_refs",
        "input_hashes",
        "input_artifact_hashes",
        "geometry_input_hashes",
        "study_area_refs",
    }

    def walk(value: Any, key: str | None = None) -> bool:
        if key in id_keys and value == previous_study_area_id:
            return True
        if key in hash_keys and value == previous_geometry_sha256:
            return True
        if key in collection_keys and isinstance(value, (list, tuple, set)):
            if previous_study_area_id in value or previous_geometry_sha256 in value:
                return True
        if isinstance(value, Mapping):
            return any(walk(item, str(item_key)) for item_key, item in value.items())
        if isinstance(value, (list, tuple, set)):
            return any(walk(item, key) for item in value)
        return False

    return walk(payload)


evaluate_staleness = is_stale_dependency
deterministic_staleness_evaluator = is_stale_dependency


def _record_payload(record_or_payload: Any) -> dict[str, Any]:
    if isinstance(record_or_payload, StateRecord):
        return record_or_payload.as_dict()
    if hasattr(record_or_payload, "model_dump"):
        return record_or_payload.model_dump(mode="json")
    if isinstance(record_or_payload, Mapping):
        return dict(record_or_payload)
    raise StudyAreaConfirmationError("artifact metadata must be a typed Artifact or JSON record")


def _artifact_like_mapping(value: Mapping[str, Any]) -> bool:
    """Return whether a mapping is artifact metadata rather than GeoJSON."""

    return any(key in value for key in ("uri", "sha256", "content_hash", "mime", "mime_type"))


def _artifact_crs_matches(left: Any, right: str) -> bool:
    if not isinstance(left, str) or not left.strip():
        return False
    try:
        return CRS.from_user_input(left).equals(CRS.from_user_input(right))
    except Exception:
        return left.strip().casefold() == right.strip().casefold()


def _artifact_field_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _validate_artifact_identity(
    record: StateRecord,
    *,
    project_id: str,
    source: str | Path | Mapping[str, Any],
    artifact_root: str | Path | None,
    validated: ValidatedStudyAreaArtifact,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Check every authoritative Artifact field against the bytes just read."""

    if record.entity_type != "Artifact":
        raise StudyAreaConfirmationError("geometry_artifact_id must reference an Artifact record")
    payload = record.as_dict()
    if payload.get("id") != record.entity_id:
        raise StudyAreaConfirmationError("persisted Artifact id does not match its state identity")
    if _artifact_field_text(payload.get("project_id")) != project_id:
        raise StudyAreaConfirmationError("artifact project_id does not match the confirming project")
    expected_uri = _canonical_artifact_uri(
        source,
        artifact_root=artifact_root,
        artifact_sha256=validated.artifact_sha256,
    )
    if _comparable_artifact_uri(payload.get("uri"), artifact_root=artifact_root) != _comparable_artifact_uri(
        expected_uri, artifact_root=artifact_root
    ):
        raise StudyAreaConfirmationError("persisted Artifact URI does not match the validated source")
    if payload.get("sha256") != validated.artifact_sha256:
        raise StudyAreaConfirmationError("persisted Artifact hash does not match the validated bytes")
    if (
        isinstance(payload.get("size_bytes"), bool)
        or not isinstance(payload.get("size_bytes"), int)
        or payload.get("size_bytes") != validated.size_bytes
    ):
        raise StudyAreaConfirmationError("persisted Artifact size does not match the validated bytes")
    if _artifact_field_text(payload.get("mime")).casefold() != STUDY_AREA_ARTIFACT_MIME.casefold():
        raise StudyAreaConfirmationError("persisted Artifact MIME does not identify GeoJSON")
    if not _artifact_crs_matches(payload.get("crs"), validated.horizontal_crs):
        raise StudyAreaConfirmationError("persisted Artifact CRS does not match the validated CRS")
    if _artifact_field_text(payload.get("producer")).casefold() != STUDY_AREA_ARTIFACT_PRODUCER.casefold():
        raise StudyAreaConfirmationError("persisted Artifact producer must be QGIS")
    if _artifact_field_text(payload.get("type")).casefold() != STUDY_AREA_ARTIFACT_TYPE.casefold():
        raise StudyAreaConfirmationError("persisted Artifact type is not a Study Area geometry")

    # Caller-supplied metadata is evidence to check, never an override for the
    # persisted record.  This closes the old merge path that let a caller hide a
    # mismatch by replacing persisted values before validation.
    supplied = metadata or {}
    if supplied:
        for key in ("project_id", "sha256", "size_bytes", "mime", "producer", "type"):
            if key in supplied and supplied.get(key) != payload.get(key):
                raise StudyAreaConfirmationError(f"caller Artifact {key} does not match the persisted record")
        if "uri" in supplied and _comparable_artifact_uri(supplied.get("uri"), artifact_root=artifact_root) != _comparable_artifact_uri(
            payload.get("uri"), artifact_root=artifact_root
        ):
            raise StudyAreaConfirmationError("caller Artifact URI does not match the persisted record")
        if "crs" in supplied and not _artifact_crs_matches(supplied.get("crs"), validated.horizontal_crs):
            raise StudyAreaConfirmationError("caller Artifact CRS does not match the persisted record")


def _validate_supplied_artifact_metadata(
    metadata: Mapping[str, Any],
    *,
    project_id: str,
    artifact_root: str | Path | None,
    validated: ValidatedStudyAreaArtifact,
    expected_uri: str,
) -> None:
    """Validate optional caller metadata before a new Artifact is registered."""

    if not metadata:
        return
    if "project_id" in metadata and metadata.get("project_id") != project_id:
        raise StudyAreaConfirmationError("caller Artifact project_id does not match the confirming project")
    if "uri" in metadata and _comparable_artifact_uri(metadata.get("uri"), artifact_root=artifact_root) != _comparable_artifact_uri(
        expected_uri, artifact_root=artifact_root
    ):
        raise StudyAreaConfirmationError("caller Artifact URI does not match the validated source")
    if "sha256" in metadata and metadata.get("sha256") != validated.artifact_sha256:
        raise StudyAreaConfirmationError("caller Artifact hash does not match the validated bytes")
    if "size_bytes" in metadata:
        supplied_size = metadata.get("size_bytes")
        if (
            isinstance(supplied_size, bool)
            or not isinstance(supplied_size, int)
            or supplied_size != validated.size_bytes
        ):
            raise StudyAreaConfirmationError("caller Artifact size does not match the validated bytes")
    if "mime" in metadata and _artifact_field_text(metadata.get("mime")).casefold() != STUDY_AREA_ARTIFACT_MIME.casefold():
        raise StudyAreaConfirmationError("caller Artifact MIME must identify GeoJSON")
    if "crs" in metadata and not _artifact_crs_matches(metadata.get("crs"), validated.horizontal_crs):
        raise StudyAreaConfirmationError("caller Artifact CRS does not match the validated CRS")
    if "producer" in metadata and _artifact_field_text(metadata.get("producer")).casefold() != STUDY_AREA_ARTIFACT_PRODUCER.casefold():
        raise StudyAreaConfirmationError("caller Artifact producer must be QGIS")
    if "type" in metadata and _artifact_field_text(metadata.get("type")).casefold() != STUDY_AREA_ARTIFACT_TYPE.casefold():
        raise StudyAreaConfirmationError("caller Artifact type is not a Study Area geometry")


class StudyAreaConfirmationService:
    """Bounded command that confirms a saved polygon and activates exploration."""

    def __init__(
        self,
        store: ProjectStateStore,
        *,
        artifact_root: str | Path | None = None,
        project_anchor: ProjectGeographicAnchor | None = None,
    ):
        self.store = store
        self.artifact_root = artifact_root
        self.project_anchor = project_anchor

    def _artifact_metadata(
        self,
        artifact: Any,
        *,
        artifact_id: str | None,
        artifact_path: str | Path | None,
    ) -> _ArtifactInput:
        """Resolve one artifact input without allowing metadata shadowing.

        A supplied identifier is an assertion about durable state.  It is never
        treated as a newly-created reference merely because a path also happens
        to be present.
        """

        metadata: dict[str, Any] = {}
        chosen_id = artifact_id
        explicit_id = artifact_id is not None
        source: Any = artifact_path
        persisted: StateRecord | None = None
        if isinstance(artifact, StateRecord):
            if artifact.entity_type != "Artifact":
                raise StudyAreaConfirmationError("artifact record must have entity type Artifact")
            chosen_id = chosen_id or artifact.entity_id
            explicit_id = True
            metadata = artifact.as_dict()
        elif hasattr(artifact, "model_dump") and hasattr(artifact, "id"):
            chosen_id = chosen_id or str(artifact.id)
            explicit_id = True
            metadata = _record_payload(artifact)
        elif isinstance(artifact, Mapping):
            # A GeoJSON mapping is an artifact body; an Artifact-like mapping
            # has a URI and hash and is resolved through the store/path below.
            if _artifact_like_mapping(artifact):
                chosen_id = chosen_id or artifact.get("id")
                explicit_id = explicit_id or artifact.get("id") is not None
                metadata = dict(artifact)
            else:
                source = artifact if source is None else source
        elif artifact is not None:
            source = artifact if source is None else source
        if chosen_id is not None:
            chosen_id = _nonempty(chosen_id, "artifact_id")
            if "id" in metadata and metadata.get("id") is not None:
                supplied_metadata_id = _nonempty(metadata.get("id"), "artifact.id")
                if supplied_metadata_id != chosen_id:
                    raise StudyAreaConfirmationError("caller Artifact id does not match artifact_id")
            try:
                state_artifact = self.store.current(chosen_id)
            except EntityNotFoundError:
                state_artifact = None
            if state_artifact is not None:
                if state_artifact.entity_type != "Artifact":
                    raise StudyAreaConfirmationError("artifact_id must reference an Artifact record")
                persisted = state_artifact
            elif explicit_id:
                raise StudyAreaConfirmationError(f"artifact {chosen_id!r} does not exist")
        if source is None:
            source = metadata.get("uri")
        if source is None:
            raise StudyAreaConfirmationError("a saved Study Area artifact path or URI is required")
        normalized = dict(metadata)
        for canonical, aliases in {
            "sha256": ("content_hash",),
            "mime": ("mime_type",),
            "type": ("artifact_type",),
            "crs": ("horizontal_crs",),
        }.items():
            if canonical in normalized:
                for alias in aliases:
                    if alias in normalized and normalized[alias] != normalized[canonical]:
                        raise StudyAreaConfirmationError(
                            f"Artifact {canonical} aliases do not agree"
                        )
            if canonical not in normalized:
                for alias in aliases:
                    if alias in normalized:
                        normalized[canonical] = normalized[alias]
                        break
        return _ArtifactInput(
            artifact_id=chosen_id,
            source=source,
            metadata=normalized,
            persisted=persisted,
            explicit_id=explicit_id,
        )

    def _project_study_areas(self, project_id: str) -> list[StateRecord]:
        """Return every current StudyArea head for a project, including superseded heads."""

        records = self.store.replay_project(project_id).values()
        return sorted(
            (record for record in records if record.entity_type == "StudyArea"),
            key=lambda record: record.entity_id,
        )

    @staticmethod
    def _version_number(value: Any) -> int | None:
        if not isinstance(value, str):
            return None
        match = re.fullmatch(r"v([1-9][0-9]*)", value.strip(), flags=re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _next_study_area_version(self, project_id: str) -> str:
        numbers = [
            number
            for record in self._project_study_areas(project_id)
            if (number := self._version_number(record.get("version"))) is not None
        ]
        return f"v{max(numbers, default=0) + 1}"

    def confirm(
        self,
        project_id: str,
        *,
        actor: str,
        actor_kind: ActorKind,
        actor_session_id: str,
        artifact: Any = None,
        artifact_id: str | None = None,
        artifact_path: str | Path | None = None,
        version: str | None = None,
        study_area_id: str | None = None,
        horizontal_crs: str | None = None,
        units: str | None = None,
        geometry_sha256: str | None = None,
        artifact_sha256: str | None = None,
        supersedes_id: str | None = None,
        confirmed_at: datetime | None = None,
        confirmation_event_id: str | None = None,
        activation_event_id: str | None = None,
        confirmation_payload: Mapping[str, Any] | None = None,
        reason: str = "Human confirmed the saved QGIS Study Area for exploration",
    ) -> StudyArea:
        project_id = _nonempty(project_id, "project_id")
        actor = _nonempty(actor, "actor")
        try:
            project = self.store.current(project_id)
        except EntityNotFoundError as exc:
            raise StudyAreaConfirmationError(f"project {project_id!r} does not exist") from exc
        if project.entity_type != "Project":
            raise StudyAreaConfirmationError(f"{project_id!r} is not a Project entity")
        if self.project_anchor is not None and self.project_anchor.project_id != project_id:
            raise StudyAreaConfirmationError("configured project anchor does not match the confirming project")
        artifact_input = self._artifact_metadata(
            artifact,
            artifact_id=artifact_id,
            artifact_path=artifact_path,
        )
        source = artifact_input.source
        metadata = artifact_input.metadata
        artifact_ref = artifact_input.artifact_id
        expected_hash = metadata.get("sha256")
        artifact_crs = metadata.get("crs")
        artifact_units = metadata.get("units")
        artifact_mime = metadata.get("mime")
        metadata_crs = _extract_crs(artifact_crs)
        effective_crs = horizontal_crs or metadata_crs
        effective_units = units or artifact_units
        if artifact_sha256 is not None and expected_hash is not None and artifact_sha256 != expected_hash:
            raise StudyAreaConfirmationError("artifact hash arguments do not match")
        if artifact_mime is not None and _artifact_field_text(artifact_mime).casefold() != STUDY_AREA_ARTIFACT_MIME.casefold():
            raise StudyAreaConfirmationError("Study Area artifact MIME must be application/geo+json")
        if "producer" in metadata and _artifact_field_text(metadata.get("producer")).casefold() != STUDY_AREA_ARTIFACT_PRODUCER.casefold():
            raise StudyAreaConfirmationError("Study Area artifact producer must be QGIS")
        validated = validate_study_area_artifact(
            source,
            expected_sha256=artifact_sha256 or expected_hash,
            horizontal_crs=effective_crs,
            units=effective_units,
            expected_geometry_sha256=geometry_sha256,
            artifact_root=self.artifact_root,
            project_anchor=self.project_anchor,
        )
        confirmed_time = _timestamp(confirmed_at)

        expected_uri = _canonical_artifact_uri(
            source,
            artifact_root=self.artifact_root,
            artifact_sha256=validated.artifact_sha256,
        )
        _validate_supplied_artifact_metadata(
            metadata,
            project_id=project_id,
            artifact_root=self.artifact_root,
            validated=validated,
            expected_uri=expected_uri,
        )
        if artifact_ref is None:
            artifact_ref = "study-area-artifact-" + validated.artifact_sha256.removeprefix("sha256:")[:24]
            # A content hash alone does not identify a distinct retained URI.
            # If the same bytes arrive from another local path, derive a
            # deterministic secondary identifier instead of mutating or
            # mislinking the first Artifact.  Caller-provided IDs still fail on
            # any URI mismatch below.
            try:
                existing_auto = self.store.current(artifact_ref)
            except EntityNotFoundError:
                existing_auto = None
            if existing_auto is not None:
                if existing_auto.entity_type != "Artifact":
                    raise StudyAreaConfirmationError("generated artifact identifier collides with another entity")
                same_uri = _comparable_artifact_uri(
                    existing_auto.get("uri"), artifact_root=self.artifact_root
                ) == _comparable_artifact_uri(expected_uri, artifact_root=self.artifact_root)
                if not same_uri or existing_auto.get("project_id") != project_id:
                    uri_suffix = hashlib.sha256(
                        f"{project_id}\0{expected_uri}".encode("utf-8")
                    ).hexdigest()[:12]
                    artifact_ref = artifact_ref + "-" + uri_suffix
        retained_identity = artifact_input.persisted.as_dict() if artifact_input.persisted is not None else {}
        artifact_payload = Artifact(
            id=artifact_ref,
            type=retained_identity.get("type", STUDY_AREA_ARTIFACT_TYPE),
            uri=retained_identity.get("uri", expected_uri),
            sha256=validated.artifact_sha256,
            mime=retained_identity.get("mime", STUDY_AREA_ARTIFACT_MIME),
            crs=retained_identity.get("crs", validated.horizontal_crs),
            producer=retained_identity.get("producer", STUDY_AREA_ARTIFACT_PRODUCER),
            created_at=confirmed_time,
            project_id=project_id,
            size_bytes=validated.size_bytes,
        )
        if artifact_input.persisted is not None:
            _validate_artifact_identity(
                artifact_input.persisted,
                project_id=project_id,
                source=source,
                artifact_root=self.artifact_root,
                validated=validated,
                metadata=metadata,
            )

        active_id = project.get("active_study_area_id")
        if supersedes_id is not None and (active_id is None or supersedes_id != active_id):
            raise StudyAreaConfirmationError("supersedes_id must match the project's active StudyArea")
        previous_id = supersedes_id if supersedes_id is not None else active_id
        previous_record = None
        if previous_id:
            try:
                previous_record = self.store.current(str(previous_id))
            except EntityNotFoundError as exc:
                raise StudyAreaConfirmationError("project active StudyArea cannot be resolved") from exc
            if previous_record.entity_type != "StudyArea" or previous_record.project_id != project_id:
                raise StudyAreaConfirmationError("supersedes_id must reference this project's StudyArea")
        if version is None:
            version = self._next_study_area_version(project_id)
        version = _nonempty(version or "v1", "version")
        existing_areas = self._project_study_areas(project_id)
        version_folded = version.casefold()
        if any(str(record.get("version", "")).casefold() == version_folded for record in existing_areas):
            raise StudyAreaConfirmationError(f"StudyArea version {version!r} already exists in this project")
        if study_area_id is None:
            study_area_id = "study-area-" + project_id + "-" + version
        study_area_id = _nonempty(study_area_id, "study_area_id")
        if any(record.entity_id == study_area_id for record in existing_areas):
            raise StudyAreaConfirmationError(f"StudyArea {study_area_id!r} already exists in this project")
        if previous_id == study_area_id:
            raise StudyAreaConfirmationError("a StudyArea cannot supersede itself")

        event_id = _nonempty(confirmation_event_id or "confirm-study-area-" + uuid4().hex, "confirmation_event_id")
        candidate = StudyArea(
            id=study_area_id,
            project_id=project_id,
            version=version,
            geometry_artifact_id=artifact_ref,
            geometry_sha256=validated.geometry_sha256,
            artifact_sha256=validated.artifact_sha256,
            horizontal_crs=validated.horizontal_crs,
            units=validated.units,
            source=StudyAreaSource.HUMAN_DRAWN_QGIS,
            status=StudyAreaStatus.CONFIRMED_FOR_EXPLORATION,
            confirmed_actor=actor,
            confirmed_at=confirmed_time,
            confirmation_event_id=event_id,
            supersedes_id=previous_id,
        )
        try:
            self.store.confirm_study_area(
                candidate.model_dump(mode="json"),
                project_id=project_id,
                actor=actor,
                reason=_nonempty(reason, "reason"),
                confirmation_event_id=event_id,
                activation_event_id=activation_event_id,
                supersedes_id=previous_id,
                artifact_payload=artifact_payload.model_dump(mode="json"),
                confirmation_payload=confirmation_payload,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
            )
        except (PayloadError, EntityNotFoundError, StoreError, StudyAreaValidationError) as exc:
            if isinstance(exc, StudyAreaConfirmationError):
                raise
            raise StudyAreaConfirmationError(str(exc)) from exc
        return candidate

    confirm_study_area = confirm


StudyAreaWorkflow = StudyAreaConfirmationService


def confirm_study_area(
    store: ProjectStateStore,
    project_id: str,
    artifact: Any = None,
    *,
    actor: str,
    actor_kind: ActorKind,
    actor_session_id: str,
    artifact_root: str | Path | None = None,
    **kwargs: Any,
) -> StudyArea:
    """Convenience command for the bounded confirmation service."""

    return StudyAreaConfirmationService(store, artifact_root=artifact_root).confirm(
        project_id,
        actor=actor,
        actor_kind=actor_kind,
        actor_session_id=actor_session_id,
        artifact=artifact,
        **kwargs,
    )


__all__ = [
    "EXPLORATION_STAGES",
    "FORMAL_CLAIM_TYPES",
    "DesignBoundary",
    "DesignBoundaryStatus",
    "FormalClaimGuardError",
    "StudyAreaConfirmationError",
    "StudyAreaConfirmationService",
    "StudyAreaValidationError",
    "StudyAreaWorkflow",
    "ValidatedStudyAreaArtifact",
    "ProjectAnchorError",
    "ProjectGeographicAnchor",
    "authorize_exploration_scope",
    "authorize_formal_claim",
    "assert_exploration_allowed",
    "assert_exploration_authorized",
    "can_explore",
    "can_make_formal_claim",
    "confirm_study_area",
    "deterministic_staleness_evaluator",
    "evaluate_staleness",
    "evidence_semantic_contract",
    "exploratory_scope_allowed",
    "formal_claim_allowed",
    "guard_formal_claim",
    "is_stale_dependency",
    "runtime_exploration_allowed",
    "require_approved_design_boundary",
    "validate_exploration_scope",
    "validate_formal_claim",
    "validate_study_area_artifact",
    "validate_study_area_geometry",
]
