"""Decision-gated orchestration for fixture and approved-site W5 generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Mapping
import uuid

from shapely.geometry import GeometryCollection, Polygon, box, mapping, shape
from urban_design.far import FarSiteContext, resolve_far_denominator
from shapely.ops import unary_union

from urban_design.constraint_sets import (
    CONSTRAINT_UNIT_BY_NAME,
    REQUIRED_CONSTRAINT_NAMES,
    constraint_set_payload_digest,
    validate_zone_allocation,
)
from urban_design.models import (
    ActorKind,
    Artifact,
    Constraint,
    ConstraintSet,
    DatasetSnapshot,
    DecisionAction,
    HumanDecision,
    HumanStatus,
    RunStatus,
    Scenario,
    ScenarioStatus,
    ToolExecution,
    UnavailableValue,
)
from urban_design.morphology.contracts import (
    ApprovedSiteConstraint,
    NonBuildableArea,
    FixtureGenerationInput,
    MorphologyGenerationError,
    PreservedBuildingInput,
    SiteGenerationInput,
    SiteRoadInput,
    SiteZoneInput,
)
from urban_design.morphology.floor_estimate import estimate_floor_count
from urban_design.morphology.strategies import generate_fixture_strategies, generate_site_strategies
from urban_design.morphology.validation import canonical_geometry_hash
from urban_design.scenario_comparison import build_scenario_comparison
from urban_design.store import EntityNotFoundError, ProjectStateStore, StateRecord
from urban_design.workspace_contracts import (
    FeatureDisposition,
    WorkspaceRevision,
    WorkspaceSpatialBrief,
)


_HASH_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_RULES_VERSION = "w5-7-site-v2"
_FIXTURE_RULES_VERSION = "w5-7-fixture-v1"
_GENERATOR_VERSION = "site-generation-v2"
_FIXTURE_GENERATOR_VERSION = "strategy-catalog-v1"
_FRAGMENT_RULE_VERSION = "site-fragments-minimum-area-width-v1"
_MINIMUM_FRAGMENT_AREA_M2 = 100.0
_MINIMUM_FRAGMENT_WIDTH_M = 6.0


class ApprovedGenerationBlocked(RuntimeError):
    """Raised with one human-readable item per absent, stale, or unsupported input."""

    def __init__(self, missing: list[str]):
        self.missing = list(dict.fromkeys(missing))
        super().__init__("approved generation is blocked")


@dataclass(frozen=True)
class ApprovedInputs:
    project_id: str
    workspace_record: StateRecord
    workspace: WorkspaceRevision
    workspace_decision: HumanDecision
    study_area: StateRecord
    constraint_record: StateRecord
    constraint_set: ConstraintSet
    constraint_decision: HumanDecision
    design_area: Polygon
    zones: tuple[tuple[str, str, Any], ...]
    dispositions: tuple[FeatureDisposition, ...]
    retained_buildings: tuple[tuple[FeatureDisposition, Any, Mapping[str, Any]], ...]
    retained_roads: tuple[tuple[FeatureDisposition, SiteRoadInput, Mapping[str, Any]], ...]
    source_network_roads: tuple[SiteRoadInput, ...]
    source_artifacts: tuple[StateRecord, ...]
    source_snapshots: tuple[StateRecord, ...]
    input_hash: str
    water_geometry: Any = None
    water_artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationResult:
    status: str
    scenario_ids: tuple[str, ...]
    comparison: dict[str, Any]
    output_database: Path
    artifact_root: Path
    snapshot_path: Path | None = None
    snapshot_sha256: str | None = None
    valid_candidate_count: int = 0
    failed_candidate_count: int = 0


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _normalized_hash(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cooked = value.removeprefix("sha256:")
    return cooked if re.fullmatch(r"[0-9a-f]{64}", cooked) else None


def _workspace_payload_digest(workspace: WorkspaceRevision) -> str:
    brief_payload = (
        workspace.spatial_brief.model_dump(mode="json")
        if workspace.spatial_brief is not None
        else {}
    )
    if isinstance(brief_payload, dict) and brief_payload.get("exploration_design_area") is None:
        brief_payload = dict(brief_payload)
        brief_payload.pop("exploration_design_area", None)
    digest_payload = {
        "project_id": workspace.project_id,
        "study_area_id": workspace.study_area_id,
        "source_snapshot_ids": sorted(workspace.source_snapshot_ids),
        "dispositions": sorted(
            [item.model_dump() for item in workspace.feature_dispositions],
            key=lambda item: (item["source_artifact_id"], item["feature_id"]),
        ),
        "spatial_brief": brief_payload,
    }
    return _hash_bytes(json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _approved_decision_for_target(
    decisions: list[StateRecord],
    *,
    target_id: str,
    target_type: str,
    target_version: str,
    target_digest: str,
    label: str,
    missing: list[str],
) -> HumanDecision | None:
    expected_digest = _normalized_hash(target_digest)
    if expected_digest is None:
        missing.append(f"{label}: current target has no valid payload digest to bind")
        return None
    approvals: list[HumanDecision] = []
    stale_versions: list[str] = []
    for record in decisions:
        payload = record.payload
        if payload.get("target_id") != target_id or payload.get("target_type") != target_type:
            continue
        try:
            decision = HumanDecision.model_validate(payload)
        except Exception:
            missing.append(f"{label}: malformed HumanDecision {record.entity_id}")
            continue
        if decision.action is not DecisionAction.APPROVE or decision.status is not HumanStatus.APPROVED:
            continue
        if decision.actor_kind is not ActorKind.HUMAN_UI:
            missing.append(f"{label}: approval {decision.id} was not recorded by HUMAN_UI")
            continue
        if decision.target_version != target_version:
            stale_versions.append(str(decision.target_version))
            continue
        decision_digest = _normalized_hash(decision.target_payload_digest)
        if decision_digest is None or decision_digest != expected_digest:
            missing.append(f"{label}: approval {decision.id} does not bind the current payload digest")
            continue
        approvals.append(decision)

    if len(approvals) == 1:
        return approvals[0]
    if len(approvals) > 1:
        missing.append(f"{label}: multiple current approved HumanDecisions bind the same target")
        return None
    if stale_versions:
        missing.append(
            f"{label}: stale HumanDecision target version(s) {', '.join(sorted(set(stale_versions)))}; current version is {target_version}"
        )
    else:
        missing.append(f"{label}: no current approved HumanDecision binds the current target version and payload digest")
    return None


def _read_artifact_document(store: ProjectStateStore, artifact_id: str, project_id: str) -> tuple[StateRecord, dict[str, Any]]:
    record = store.current(artifact_id)
    if (
        record.entity_type != "Artifact"
        or record.entity_id != artifact_id
        or record.payload.get("id") != artifact_id
        or record.project_id not in {None, project_id}
    ):
        raise ValueError(f"Artifact {artifact_id!r} is missing or belongs to a different project")
    uri = record.payload.get("uri")
    expected = _normalized_hash(record.payload.get("sha256"))
    if not isinstance(uri, str) or not expected:
        raise ValueError(f"Artifact {artifact_id!r} has no local URI or valid SHA-256")
    path = Path(uri)
    if not path.is_file():
        raise ValueError(f"Artifact {artifact_id!r} file is unavailable")
    if _hash_file(path) != expected:
        raise ValueError(f"Artifact {artifact_id!r} bytes do not match its registered SHA-256")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Artifact {artifact_id!r} is not readable GeoJSON") from exc
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise ValueError(f"Artifact {artifact_id!r} is not a GeoJSON FeatureCollection")
    if record.payload.get("crs") != "EPSG:28992":
        raise ValueError(f"Artifact {artifact_id!r} does not declare EPSG:28992")
    return record, document


def _verify_artifact_bytes(store: ProjectStateStore, artifact_id: str, project_id: str) -> StateRecord:
    """Verify a raw artifact without assuming its media is GeoJSON."""
    record = store.current(artifact_id)
    expected = _normalized_hash(record.payload.get("sha256"))
    uri = record.payload.get("uri")
    if (
        record.entity_type != "Artifact"
        or record.entity_id != artifact_id
        or record.payload.get("id") != artifact_id
        or record.project_id not in {None, project_id}
        or not expected
        or not isinstance(uri, str)
        or not Path(uri).is_file()
        or _hash_file(Path(uri)) != expected
    ):
        raise ValueError(f"raw Artifact {artifact_id!r} is missing, cross-project, or hash-invalid")
    return record


def _resolve_source_feature(
    store: ProjectStateStore,
    disposition: FeatureDisposition,
    project_id: str,
    workspace_snapshot_ids: list[str],
) -> tuple[StateRecord, StateRecord, dict[str, Any], Any, dict[str, Any]]:
    if not disposition.source_artifact_id or not disposition.source_feature_id or not disposition.source_snapshot_id:
        raise ValueError(f"FeatureDisposition {disposition.feature_id!r} lacks a source Artifact, DatasetSnapshot, or source feature ID")
    if disposition.source_snapshot_id not in workspace_snapshot_ids:
        raise ValueError(f"DatasetSnapshot {disposition.source_snapshot_id!r} is not referenced by the current WorkspaceRevision")
    snapshot = store.current(disposition.source_snapshot_id)
    if (
        snapshot.entity_type != "DatasetSnapshot"
        or snapshot.project_id != project_id
        or snapshot.payload.get("normalized_artifact_id") != disposition.source_artifact_id
    ):
        raise ValueError(f"Artifact {disposition.source_artifact_id!r} is not the normalized Artifact of DatasetSnapshot {disposition.source_snapshot_id!r}")
    artifact, document = _read_artifact_document(store, disposition.source_artifact_id, project_id)
    matches = []
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        identifiers = {
            feature.get("id"),
            properties.get("source_feature_id"),
            properties.get("feature_id"),
            properties.get("identificatie"),
        }
        if disposition.source_feature_id in identifiers:
            matches.append((feature, properties))
    if len(matches) != 1:
        raise ValueError(
            f"FeatureDisposition {disposition.feature_id!r} resolves to {len(matches)} source features; expected exactly one"
        )
    feature, properties = matches[0]
    try:
        geometry = shape(feature["geometry"])
    except Exception as exc:
        raise ValueError(f"Source feature {disposition.source_feature_id!r} has invalid geometry") from exc
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError(f"Source feature {disposition.source_feature_id!r} has empty or invalid geometry")
    return artifact, snapshot, feature, geometry, properties


def _road_attributes(properties: Mapping[str, Any]) -> dict[str, Any]:
    tags = properties.get("tags")
    attributes = dict(tags) if isinstance(tags, dict) else {}
    attributes.update({key: value for key, value in properties.items() if key != "tags" and value is not None})
    return attributes


def _road_layer(properties: Mapping[str, Any]) -> int:
    attributes = _road_attributes(properties)
    value = attributes.get("layer")
    if value is None:
        value = attributes.get("relatieve_hoogteligging")
    if value is None:
        value = 0
    if isinstance(value, bool):
        raise ValueError("road layer must be an integer, not a boolean")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"road layer {value!r} is not an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"road layer {value!r} is not an integer")
    if isinstance(value, str) and str(parsed) != value.strip():
        raise ValueError(f"road layer {value!r} is not a canonical integer")
    return parsed


def _road_flag(properties: Mapping[str, Any], name: str) -> bool:
    value = _road_attributes(properties).get(name)
    if value is None or value is False or value == 0:
        return False
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "no", "false", "0"}
    raise ValueError(f"road {name} tag must be a boolean or string")


def _road_identifier(feature: Mapping[str, Any], properties: Mapping[str, Any], artifact_id: str) -> str:
    feature_id = feature.get("id") or properties.get("source_feature_id") or properties.get("osm_id")
    if not isinstance(feature_id, (str, int)) or isinstance(feature_id, bool) or not str(feature_id).strip():
        raise ValueError(f"road feature in Artifact {artifact_id!r} has no stable feature identifier")
    return f"{artifact_id}:{feature_id}"


def _approved_road_width_scope(properties: Mapping[str, Any], constraints: tuple[Constraint, ...]) -> str:
    widths = {item.scope: item for item in constraints if item.name == "road_width"}
    attributes = _road_attributes(properties)
    hierarchy = attributes.get("highway")
    if isinstance(hierarchy, str) and f"road:{hierarchy}" in widths:
        return f"road:{hierarchy}"
    if len(widths) == 1:
        return next(iter(widths))
    raise ValueError("road width scope cannot be resolved from the road hierarchy and approved constraints")


def _site_road_input(
    feature: Mapping[str, Any],
    properties: Mapping[str, Any],
    geometry: Any,
    *,
    artifact_id: str,
    snapshot_id: str,
    width_scope: str | None,
) -> SiteRoadInput:
    attributes = _road_attributes(properties)
    highway = attributes.get("highway")
    service = attributes.get("service")
    access = attributes.get("access")
    motor_vehicle = attributes.get("motor_vehicle")
    foot = attributes.get("foot")
    for name, value in (
        ("highway", highway),
        ("service", service),
        ("access", access),
        ("motor_vehicle", motor_vehicle),
        ("foot", foot),
    ):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"road {name} tag must be a string when present")
    inactive_tags = ("construction", "proposed", "disused", "abandoned", "razed")
    inactive = (isinstance(highway, str) and highway.casefold() in inactive_tags) or any(
        key == tag or key.startswith(f"{tag}:")
        for key, value in attributes.items()
        for tag in inactive_tags
        if value not in (None, False, 0, "", "no", "false")
    )
    return SiteRoadInput(
        road_id=_road_identifier(feature, properties, artifact_id),
        geometry=geometry,
        layer=_road_layer(properties),
        bridge=_road_flag(properties, "bridge"),
        tunnel=_road_flag(properties, "tunnel"),
        source_artifact_id=artifact_id,
        source_snapshot_id=snapshot_id,
        road_width_scope=width_scope,
        highway=highway,
        service=service,
        access=access,
        motor_vehicle=motor_vehicle,
        foot=foot,
        inactive=inactive,
    )


def _workspace_source_network_roads(
    store: ProjectStateStore,
    *,
    project_id: str,
    snapshots: Mapping[str, StateRecord],
    road_dispositions: tuple[FeatureDisposition, ...],
    design_area: Polygon,
) -> tuple[tuple[SiteRoadInput, ...], dict[str, StateRecord], list[str]]:
    """Read boundary-crossing roads from current, workspace-referenced snapshots."""
    direct_snapshot_ids = {item.source_snapshot_id for item in road_dispositions if item.source_snapshot_id}
    road_tokens = ("osm", "overpass", "wegdeel", "road network")
    roads: dict[str, SiteRoadInput] = {}
    artifacts: dict[str, StateRecord] = {}
    problems: list[str] = []
    for snapshot_id, snapshot in sorted(snapshots.items()):
        source = str(snapshot.payload.get("source", "")).casefold()
        direct = snapshot_id in direct_snapshot_ids
        if not direct and not any(token in source for token in road_tokens):
            continue
        artifact_id = snapshot.payload.get("normalized_artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            problems.append(f"road-network DatasetSnapshot {snapshot_id!r} has no normalized Artifact")
            continue
        try:
            raw_artifact_id = snapshot.payload.get("raw_artifact_id")
            if not isinstance(raw_artifact_id, str) or not raw_artifact_id:
                raise ValueError("DatasetSnapshot has no raw Artifact")
            raw_artifact = _verify_artifact_bytes(store, raw_artifact_id, project_id)
            if _normalized_hash(snapshot.payload.get("sha256")) != _normalized_hash(raw_artifact.payload.get("sha256")):
                raise ValueError("DatasetSnapshot SHA-256 does not match its raw Artifact")
            artifact, document = _read_artifact_document(store, artifact_id, project_id)
            artifacts[raw_artifact_id] = raw_artifact
            artifacts[artifact_id] = artifact
            for feature in document.get("features", []):
                if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
                    continue
                properties = feature.get("properties")
                properties = properties if isinstance(properties, dict) else {}
                attributes = _road_attributes(properties)
                if not direct and not attributes.get("highway"):
                    continue
                try:
                    geometry = shape(feature["geometry"])
                except Exception as exc:
                    raise ValueError("a selected source road has invalid GeoJSON geometry") from exc
                if geometry.geom_type not in {"LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
                    continue
                if geometry.is_empty or not geometry.is_valid:
                    raise ValueError("a selected source road has empty or invalid geometry")
                if geometry.intersection(design_area.exterior).is_empty:
                    continue
                road = _site_road_input(
                    feature,
                    properties,
                    geometry,
                    artifact_id=artifact_id,
                    snapshot_id=snapshot_id,
                    width_scope=None,
                )
                roads[road.road_id] = road
        except (EntityNotFoundError, ValueError, MorphologyGenerationError) as exc:
            problems.append(f"road-network DatasetSnapshot {snapshot_id!r} is unusable: {exc}")
    return tuple(roads[key] for key in sorted(roads)), artifacts, problems


def _load_approved_inputs(
    store: ProjectStateStore,
    project_id: str,
    *,
    site_generation: bool,
) -> ApprovedInputs:
    missing: list[str] = []
    try:
        project = store.current(project_id)
    except EntityNotFoundError:
        raise ApprovedGenerationBlocked([f"Project {project_id!r} is missing from the database"])
    if project.entity_type != "Project" or project.project_id != project_id:
        raise ApprovedGenerationBlocked([f"Project {project_id!r} does not resolve to a project record"])

    workspace_id = f"workspace-{project_id}"
    try:
        from urban_design.decision_resolution import latest_accepted_workspace
        workspace_record, workspace_decision_record = latest_accepted_workspace(store, project_id, workspace_id=workspace_id)
    except (EntityNotFoundError, ValueError, KeyError, TypeError) as exc:
        raise ApprovedGenerationBlocked([str(exc)])
    if workspace_record.entity_type != "WorkspaceRevision" or workspace_record.project_id != project_id:
        raise ApprovedGenerationBlocked(["current WorkspaceRevision does not belong to the requested project"])
    try:
        workspace = WorkspaceRevision.model_validate(workspace_record.payload)
    except Exception as exc:
        raise ApprovedGenerationBlocked([f"current WorkspaceRevision is invalid: {type(exc).__name__}"])
    if workspace.workspace_id != workspace_id or workspace.project_id != project_id:
        missing.append("WorkspaceRevision payload identity does not match its state record or project")
    calculated_workspace_digest = _workspace_payload_digest(workspace)
    if _normalized_hash(workspace.payload_digest) != calculated_workspace_digest:
        missing.append("current WorkspaceRevision payload digest does not match its design area, dispositions, zones, and source snapshot references")
    if workspace_record.revision != workspace.revision:
        missing.append(
            f"current WorkspaceRevision payload version {workspace.revision} does not match state revision {workspace_record.revision}"
        )
    if workspace.status == "STALE":
        missing.append("current WorkspaceRevision is marked STALE")

    source_snapshots: dict[str, StateRecord] = {}
    for snapshot_id in workspace.source_snapshot_ids:
        try:
            snapshot_record = store.current(snapshot_id)
            if snapshot_record.entity_type != "DatasetSnapshot" or snapshot_record.project_id != project_id:
                raise ValueError("snapshot has the wrong type or project")
            snapshot_payload = {
                name: snapshot_record.payload[name]
                for name in DatasetSnapshot.model_fields
                if name in snapshot_record.payload
            }
            snapshot = DatasetSnapshot.model_validate(snapshot_payload)
            if snapshot.id != snapshot_record.entity_id or snapshot.project_id != project_id:
                raise ValueError("snapshot payload identity does not match its state record or project")
            if str(snapshot_record.payload.get("status", "")).upper() in {
                "STALE", "SUPERSEDED", "BLOCKED", "REJECTED"
            }:
                raise ValueError("snapshot is stale, superseded, blocked, or rejected")
            source_snapshots[snapshot_record.entity_id] = snapshot_record
        except (EntityNotFoundError, ValueError) as exc:
            missing.append(f"WorkspaceRevision source DatasetSnapshot {snapshot_id!r} is invalid: {exc}")

    decisions = store.list_current("HumanDecision", project_id=project_id)
    workspace_decision = HumanDecision.model_validate(workspace_decision_record.payload)

    brief: WorkspaceSpatialBrief | None = workspace.spatial_brief
    design_area = None
    if brief is None or brief.exploration_design_area is None:
        missing.append("approved ExplorationDesignArea is missing from the current WorkspaceRevision")
    else:
        try:
            design_area = shape(brief.exploration_design_area.geometry)
            if (
                brief.exploration_design_area.crs != "EPSG:28992"
                or not isinstance(design_area, Polygon)
                or design_area.is_empty
                or not design_area.is_valid
                or not design_area.area > 0
            ):
                raise ValueError("area must be a valid positive-area EPSG:28992 Polygon")
        except Exception as exc:
            missing.append(f"approved ExplorationDesignArea is invalid: {exc}")

    dispositions: tuple[FeatureDisposition, ...] = ()
    if not workspace.feature_dispositions:
        missing.append("feature dispositions are missing")
    else:
        dispositions = tuple(workspace.feature_dispositions)
        undecided = sorted(item.feature_id for item in dispositions if item.disposition == "undecided")
        if undecided:
            missing.append("feature dispositions remain undecided: " + ", ".join(undecided))

    zones: tuple[tuple[str, str, Any], ...] = ()
    if brief is None or not brief.zones:
        missing.append("approved spatial zones are missing from the current WorkspaceRevision")
    elif design_area is not None:
        try:
            zone_items = []
            for zone in brief.zones:
                geometry = shape(zone.geometry)
                if not design_area.covers(geometry):
                    raise ValueError(f"zone {zone.zone_id!r} lies outside the approved design area")
                zone_items.append((zone.zone_id, zone.target_use, geometry))
            zones = tuple(zone_items)
        except Exception as exc:
            missing.append(f"approved spatial zones are invalid: {exc}")

    constraint_candidates = [
        record for record in store.list_current("ConstraintSet", project_id=project_id)
        if str(record.payload.get("status", "")).casefold() == "effective"
    ]
    constraint_record = None
    constraint_set = None
    constraint_decision = None
    if not constraint_candidates:
        missing.append("effective ConstraintSet is missing")
    elif len(constraint_candidates) != 1:
        missing.append(
            "multiple effective ConstraintSets exist; an explicit current set must be selected (found: "
            + ", ".join(sorted(record.entity_id for record in constraint_candidates))
            + ")"
        )
    else:
        constraint_record = constraint_candidates[0]
        try:
            constraint_set = ConstraintSet.model_validate(constraint_record.payload)
            if constraint_set.id != constraint_record.entity_id or constraint_set.project_id != project_id:
                raise ValueError("ConstraintSet payload identity does not match its state record or project")
            current_digest = constraint_set_payload_digest(constraint_record.payload)
        except Exception as exc:
            missing.append(f"effective ConstraintSet is invalid: {type(exc).__name__}")
            current_digest = ""

        if constraint_set is not None:
            constraint_decision = _approved_decision_for_target(
                decisions,
                target_id=constraint_set.id,
                target_type="ConstraintSet",
                target_version=constraint_set.version,
                target_digest=current_digest,
                label="effective ConstraintSet",
                missing=missing,
            )
            current_names = {item.name for item in constraint_set.constraints}
            missing_constraints = sorted(REQUIRED_CONSTRAINT_NAMES - current_names)
            if missing_constraints:
                missing.append("effective ConstraintSet is missing required constraints: " + ", ".join(missing_constraints))
            if any(item.status.value != "effective" for item in constraint_set.constraints):
                missing.append("effective ConstraintSet contains a non-effective Constraint")
            if constraint_decision is not None:
                for item in constraint_set.constraints:
                    if constraint_decision.id not in item.source_refs:
                        missing.append(f"Constraint {item.id!r} is not linked to the approving HumanDecision")
            if brief is not None:
                try:
                    validate_zone_allocation(brief, allocation_policy=constraint_set.allocation_policy)
                except ValueError as exc:
                    missing.append(f"approved zone allocation rule is incomplete: {exc}")

    try:
        study_area = store.current(workspace.study_area_id)
        if study_area.entity_type != "StudyArea" or study_area.project_id != project_id:
            raise ValueError("StudyArea record has the wrong type or project")
        if str(study_area.payload.get("status", "")).upper() in {"STALE", "SUPERSEDED", "BLOCKED", "REJECTED"}:
            raise ValueError("StudyArea is stale, superseded, blocked, or rejected")
    except (EntityNotFoundError, ValueError) as exc:
        missing.append(f"WorkspaceRevision StudyArea reference is unavailable: {exc}")
        study_area = None

    source_artifacts: dict[str, StateRecord] = {}
    retained_buildings: list[tuple[FeatureDisposition, Any, Mapping[str, Any]]] = []
    retained_road_sources: list[tuple[FeatureDisposition, StateRecord, StateRecord, dict[str, Any], Any, dict[str, Any]]] = []
    retained_roads: list[tuple[FeatureDisposition, SiteRoadInput, Mapping[str, Any]]] = []
    source_network_roads: tuple[SiteRoadInput, ...] = ()
    if design_area is not None:
        for disposition in dispositions:
            if disposition.disposition not in {"preserve", "editable"}:
                continue
            try:
                artifact, snapshot, _feature, geometry, properties = _resolve_source_feature(
                    store,
                    disposition,
                    project_id,
                    workspace.source_snapshot_ids,
                )
                source_artifacts[artifact.entity_id] = artifact
                source_snapshots[snapshot.entity_id] = snapshot
                if disposition.disposition == "preserve" and disposition.feature_kind == "building":
                    if geometry.geom_type not in {"Polygon", "MultiPolygon"} or not design_area.covers(geometry):
                        raise ValueError("preserved building footprint must be polygonal and inside the approved design area")
                    retained_buildings.append((disposition, geometry, dict(properties)))
                elif disposition.disposition == "preserve" and disposition.feature_kind == "road":
                    retained_road_sources.append((disposition, artifact, snapshot, _feature, geometry, dict(properties)))
            except (EntityNotFoundError, ValueError) as exc:
                missing.append(f"element disposition {disposition.feature_id!r} source is invalid: {exc}")

    if workspace_decision is None and not any("design area, element dispositions, and zoning" in item for item in missing):
        missing.append("design area, element dispositions, and zoning lack a current approved HumanDecision")
    if site_generation and design_area is not None and constraint_set is not None:
        source_network_roads, road_artifacts, road_problems = _workspace_source_network_roads(
            store,
            project_id=project_id,
            snapshots=source_snapshots,
            road_dispositions=tuple(item for item in dispositions if item.feature_kind == "road"),
            design_area=design_area,
        )
        source_artifacts.update(road_artifacts)
        missing.extend(road_problems)
        if not source_network_roads:
            missing.append("approved source road network has no feature crossing the design-area boundary")
        for disposition, artifact, snapshot, feature, geometry, properties in retained_road_sources:
            try:
                if geometry.geom_type not in {"LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
                    raise ValueError("preserved road must have line or polygon geometry")
                if not geometry.intersects(design_area):
                    raise ValueError("preserved road does not intersect the approved design area")
                width_scope = (
                    _approved_road_width_scope(properties, tuple(constraint_set.constraints))
                    if geometry.geom_type in {"LineString", "MultiLineString"}
                    else None
                )
                road = _site_road_input(
                    feature,
                    properties,
                    geometry,
                    artifact_id=artifact.entity_id,
                    snapshot_id=snapshot.entity_id,
                    width_scope=width_scope,
                )
                retained_roads.append((disposition, road, properties))
            except (ValueError, MorphologyGenerationError) as exc:
                missing.append(f"preserved road {disposition.feature_id!r} cannot be used: {exc}")
    elif not site_generation and retained_road_sources:
        missing.append("fixture-only generator cannot accept preserved road geometry")

    water_geometry = None
    water_artifact_ids = []
    if site_generation and constraint_set is not None and any(
        item.denominator == "land_area" for item in constraint_set.constraints
    ):
        water_parts = []
        water_snapshots = [item for item in source_snapshots.values()
                           if "bgt" in str(item.payload.get("source", "")).casefold()
                           and "waterdeel" in str(item.payload.get("source", "")).casefold()]
        if not water_snapshots:
            missing.append("land FAR requires a workspace-bound BGT waterdeel snapshot")
        for snapshot in water_snapshots:
            try:
                raw = _verify_artifact_bytes(store, snapshot.payload["raw_artifact_id"], project_id)
                if _normalized_hash(snapshot.payload.get("sha256")) != _normalized_hash(raw.payload.get("sha256")):
                    raise ValueError("water DatasetSnapshot SHA-256 does not match raw Artifact")
                artifact, document = _read_artifact_document(store, snapshot.payload["normalized_artifact_id"], project_id)
                if artifact.payload.get("crs") != "EPSG:28992":
                    raise ValueError("BGT water geometry must use EPSG:28992")
                if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
                    raise ValueError("BGT water artifact must be a FeatureCollection")
                for feature in document["features"]:
                    geometry = shape(feature["geometry"])
                    if geometry.geom_type not in {"Polygon", "MultiPolygon"} or not geometry.is_valid:
                        raise ValueError("BGT water geometry must be valid polygons")
                    water_parts.append(geometry.intersection(design_area))
                source_artifacts[raw.entity_id] = raw
                source_artifacts[artifact.entity_id] = artifact
                water_artifact_ids.append(artifact.entity_id)
            except (ValueError, KeyError, TypeError) as exc:
                missing.append(f"BGT water source cannot be used: {exc}")
        water_geometry = unary_union(water_parts)
        if not missing:
            try:
                for item in constraint_set.constraints:
                    if item.name == "far_upper_limit":
                        resolve_far_denominator(item, FarSiteContext(design_area, water_geometry))
            except ValueError as exc:
                missing.append(str(exc))
    if missing:
        raise ApprovedGenerationBlocked(missing)

    assert workspace_decision is not None
    assert constraint_record is not None and constraint_set is not None and constraint_decision is not None
    assert study_area is not None and design_area is not None
    input_manifest = {
        "project_id": project_id,
        "workspace_id": workspace.workspace_id,
        "workspace_revision": workspace.revision,
        "workspace_payload_digest": workspace.payload_digest,
        "workspace_decision_id": workspace_decision.id,
        "constraint_set_id": constraint_set.id,
        "constraint_set_version": constraint_set.version,
        "constraint_set_digest": constraint_set_payload_digest(constraint_record.payload),
        "constraint_decision_id": constraint_decision.id,
        "study_area_id": workspace.study_area_id,
        "study_area_version": study_area.payload.get("version", str(study_area.revision)),
        "source_snapshot_hashes": {
            item.entity_id: item.payload["sha256"]
            for item in sorted(source_snapshots.values(), key=lambda entry: entry.entity_id)
        },
        "source_artifact_hashes": {
            item.entity_id: item.payload.get("sha256") for item in sorted(source_artifacts.values(), key=lambda entry: entry.entity_id)
        },
        "design_area_geometry_hash": "sha256:" + _hash_bytes(design_area.normalize().wkb),
    }
    input_hash = _hash_bytes(_canonical_json(input_manifest))
    return ApprovedInputs(
        project_id=project_id,
        workspace_record=workspace_record,
        workspace=workspace,
        workspace_decision=workspace_decision,
        study_area=study_area,
        constraint_record=constraint_record,
        constraint_set=constraint_set,
        constraint_decision=constraint_decision,
        design_area=design_area,
        zones=zones,
        dispositions=dispositions,
        retained_buildings=tuple(retained_buildings),
        retained_roads=tuple(retained_roads),
        source_network_roads=source_network_roads,
        source_artifacts=tuple(source_artifacts[key] for key in sorted(source_artifacts)),
        source_snapshots=tuple(source_snapshots[key] for key in sorted(source_snapshots)),
        input_hash=input_hash,
        water_geometry=water_geometry,
        water_artifact_ids=tuple(water_artifact_ids),
    )


def _constraint_values(constraint_set: ConstraintSet) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {}
    for item in constraint_set.constraints:
        if item.name not in CONSTRAINT_UNIT_BY_NAME:
            continue
        result.setdefault(item.name, []).append(item.value)
    return result


def _floor_estimates(
    store: ProjectStateStore,
    inputs: ApprovedInputs,
) -> tuple[tuple[int | None, ...], list[dict[str, Any]]]:
    assert inputs.constraint_decision is not None
    constraints = _constraint_values(inputs.constraint_set)
    standard_floor_height = float(constraints["standard_floor_height"][0])
    snapshots = list(inputs.source_snapshots)
    bag_snapshots = [
        item for item in snapshots
        if any(token in str(item.payload.get("source", "")).casefold() for token in ("3d bag", "3dbag"))
    ]
    bag_features: dict[str, tuple[Mapping[str, Any], str]] = {}
    for snapshot in bag_snapshots:
        artifact_id = snapshot.payload.get("normalized_artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            continue
        try:
            _artifact, document = _read_artifact_document(store, artifact_id, inputs.project_id)
        except (EntityNotFoundError, ValueError):
            continue
        for feature in document.get("features", []):
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue
            bag_id = properties.get("bag_id") or properties.get("identificatie")
            if isinstance(bag_id, str) and bag_id.strip():
                bag_features[bag_id.strip()] = (properties, str(snapshot.payload.get("version", "")))

    floor_counts: list[int | None] = []
    floor_records: list[dict[str, Any]] = []
    for disposition, _geometry, properties in inputs.retained_buildings:
        bag_id_value = properties.get("bag_id") or properties.get("identificatie")
        bag_id = bag_id_value.strip() if isinstance(bag_id_value, str) and bag_id_value.strip() else None
        match = bag_features.get(bag_id) if bag_id else None
        matched = match[0] if match else {}
        roof = matched.get("roof_p70_height_m")
        ground = matched.get("ground_height_m")
        try:
            estimate = estimate_floor_count(
                building_id=disposition.feature_id,
                bag_id=bag_id,
                roof_p70_height_m=roof if isinstance(roof, (int, float)) and not isinstance(roof, bool) else None,
                ground_height_m=ground if isinstance(ground, (int, float)) and not isinstance(ground, bool) else None,
                building_use=str(matched.get("gebruiksdoel", properties.get("gebruiksdoel", ""))),
                height_field_name="roof_p70_height_m",
                data_version=match[1] if match else "3D BAG snapshot or building match unavailable",
                floor_height_m=standard_floor_height,
                floor_height_status="APPROVED",
                floor_height_decision_id=inputs.constraint_decision.id,
            )
            floor_count = estimate.floor_count
        except (TypeError, ValueError):
            floor_count = UnavailableValue(reason="3D BAG floor estimate could not be validated for this building")
            estimate = None
        if isinstance(floor_count, UnavailableValue):
            floor_counts.append(None)
            floor_payload: dict[str, Any] = floor_count.model_dump(mode="json")
        elif isinstance(floor_count, int):
            floor_counts.append(floor_count)
            floor_payload = {"status": "ESTIMATE", "floor_count": floor_count}
        else:
            # The fixture operator cannot enforce/store a ranged floor count.
            # Retain the estimate record, but keep total GFA/FAR unavailable.
            floor_counts.append(None)
            floor_payload = {
                "status": "UNAVAILABLE",
                "reason": "current fixture generator cannot represent the PD-11 estimated floor range",
                "estimate_range": list(floor_count),
            }
        floor_records.append({
            "building_id": disposition.feature_id,
            "bag_id": bag_id,
            "rule_version": "floor-estimate-v1",
            "floor_height_m": standard_floor_height,
            "floor_height_decision_id": inputs.constraint_decision.id,
            "data_version": match[1] if match else None,
            "floor_count": floor_payload,
        })
    return tuple(floor_counts), floor_records


def _site_generation_input(
    inputs: ApprovedInputs,
    retained_floor_counts: tuple[int | None, ...],
) -> SiteGenerationInput:
    assert inputs.constraint_decision is not None
    relevant_names = {
        "far_upper_limit",
        "zone_far_upper_limit",
        "coverage_upper_limit",
        "height_upper_limit",
        "first_floor_height",
        "standard_floor_height",
        "road_width",
    }
    approved_constraints = tuple(
        ApprovedSiteConstraint(
            id=item.id,
            name=item.name,
            value=float(item.value),
            unit=item.unit,
            scope=item.scope,
            enforcement=item.enforcement,
            approval_decision_id=inputs.constraint_decision.id,
            denominator=item.denominator,
        )
        for item in inputs.constraint_set.constraints
        if item.name in relevant_names
    )
    preserved_buildings = tuple(
        PreservedBuildingInput(
            building_id=disposition.feature_id,
            footprint=geometry,
            floor_count=retained_floor_counts[index],
            source_artifact_id=disposition.source_artifact_id,
            source_snapshot_id=disposition.source_snapshot_id or "",
        )
        for index, (disposition, geometry, _properties) in enumerate(inputs.retained_buildings)
    )
    zones = tuple(
        SiteZoneInput(
            zone_id=zone.zone_id,
            geometry=shape(zone.geometry),
            crs=zone.crs,
            target_use=zone.target_use,
            # SpatialZone target uses are human-approved preferences; this
            # contract has no typed source for a binding use restriction.
            use_enforcement="PREFERENCE",
        )
        for zone in inputs.workspace.spatial_brief.zones
    )
    source_status = " ".join(
        f"{item.payload.get('source', '')} {item.payload.get('license', '')}".casefold()
        for item in inputs.source_snapshots
    )
    provenance = "FIXTURE_ONLY" if "fixture" in source_status else "APPROVED_PROJECT_DATA"
    return SiteGenerationInput(
        design_area=inputs.design_area,
        crs=inputs.workspace.spatial_brief.exploration_design_area.crs,
        seed=int(inputs.input_hash[:8], 16),
        source_network_roads=inputs.source_network_roads,
        preserved_roads=tuple(road for _disposition, road, _properties in inputs.retained_roads),
        preserved_buildings=preserved_buildings,
        zones=zones,
        approved_constraints=approved_constraints,
        minimum_fragment_area_m2=_MINIMUM_FRAGMENT_AREA_M2,
        minimum_fragment_width_m=_MINIMUM_FRAGMENT_WIDTH_M,
        fragment_rule_version=_FRAGMENT_RULE_VERSION,
        non_buildable_areas=tuple(
            NonBuildableArea(id=f"bgt-water-{index}", geometry=part, kind="water",
                             source_artifact_id=inputs.water_artifact_ids[0])
            for index, part in enumerate(
                (() if inputs.water_geometry is None or inputs.water_geometry.is_empty else
                 (inputs.water_geometry,) if inputs.water_geometry.geom_type == "Polygon" else inputs.water_geometry.geoms)
            ) if part.geom_type in {"Polygon", "MultiPolygon"} and not part.is_empty
        ),
        allocation_policy=inputs.constraint_set.allocation_policy,
        provenance=provenance,
    )


def _zone_candidate(candidate: Any, inputs: ApprovedInputs) -> Any:
    assigned_buildings = []
    zone_failures: list[str] = []
    for building in candidate.buildings:
        matching = [
            (zone_id, use_label)
            for zone_id, use_label, geometry in inputs.zones
            if geometry.covers(building.footprint)
        ]
        if len(matching) == 1:
            zone_id, use_label = matching[0]
            assigned_buildings.append(replace(
                building,
                use_label=use_label,
                strategy_parameter=building.strategy_parameter + f";zone_id={zone_id}",
            ))
        else:
            zone_failures.append(
                f"building {building.building_id} is covered by {len(matching)} approved zones; exactly one zone is required"
            )
            assigned_buildings.append(building)
    updated = replace(
        candidate,
        buildings=tuple(assigned_buildings),
        valid=candidate.valid and not zone_failures,
        failure_reasons=tuple(dict.fromkeys((*candidate.failure_reasons, *zone_failures))),
    )
    updated = replace(
        updated,
        geometry_hash=canonical_geometry_hash(
            roads=updated.roads,
            road_surfaces=updated.road_surfaces,
            open_space=updated.open_space,
            parcels=updated.parcels,
            buildings=updated.buildings,
            retained_footprints=updated.retained_footprints,
        ),
    )
    return updated


def _metric_record(value: Any, *, unit: str, method: str, data_gaps: list[str]) -> dict[str, Any]:
    if isinstance(value, UnavailableValue):
        return {
            "status": "UNAVAILABLE",
            "reason": value.reason,
            "unit": unit,
            "method": method,
            "validation_status": "UNAVAILABLE",
            "data_gaps": data_gaps,
        }
    if isinstance(value, tuple):
        return {
            "range": [float(value[0]), float(value[1])],
            "unit": unit,
            "method": method,
            "validation_status": "ESTIMATE",
            "data_gaps": data_gaps,
        }
    return {
        "value": float(value),
        "unit": unit,
        "method": method,
        "validation_status": "VALIDATED",
        "data_gaps": data_gaps,
    }


def _candidate_metrics(candidate: Any, area: Polygon, *, has_unknown_retained_floors: bool, inputs: ApprovedInputs | None = None) -> dict[str, dict[str, Any]]:
    fixture_only = candidate.provenance == "FIXTURE_ONLY"
    constraint = None if inputs is None or fixture_only else next(
        item for item in inputs.constraint_set.constraints if item.name == "far_upper_limit" and item.scope == "whole_site")
    far_area, far_label = resolve_far_denominator(
        constraint, FarSiteContext(area, None if inputs is None else inputs.water_geometry))
    if constraint is not None and constraint.denominator is None and not isinstance(candidate.metrics.far, UnavailableValue):
        # Historical known FAR came from the site generator's land geometry;
        # unknown-GFA lower bounds historically used the full EDA.
        legacy = getattr(candidate, "diff_report", {}).get("far_denominator")
        if legacy is not None:
            far_area, far_label = legacy["area_m2"], legacy["label"]
    gaps = (
        ["source snapshots are fixture-only; metrics are not formal project evidence"]
        if fixture_only
        else ["generated alternatives remain system proposals and require designer review"]
    )
    known_gfa = sum(float(building.footprint.area) * building.floor_count for building in candidate.buildings)
    retained_gfa = candidate.metrics.gfa_m2
    metrics: dict[str, dict[str, Any]] = {
        "gfa_m2": _metric_record(
            retained_gfa,
            unit="m²",
            method="generated floor plates plus retained buildings",
            data_gaps=(gaps + ["retained building GFA unavailable because no matching 3D BAG floor estimate exists"])
            if isinstance(retained_gfa, UnavailableValue)
            else gaps,
        ),
        "far": (
            {
                "status": "PARTIALLY_UNKNOWN" if has_unknown_retained_floors else "UNAVAILABLE",
                "known_lower_bound": float(known_gfa / far_area),
                "unit": "ratio",
                "method": "known generated GFA / approved ExplorationDesignArea; retained GFA is unavailable",
                "validation_status": "PARTIALLY_UNKNOWN" if has_unknown_retained_floors else "UNAVAILABLE",
                "data_gaps": gaps + (["retained building GFA is unavailable; this is a lower bound, not total FAR"] if has_unknown_retained_floors else []),
            }
            if isinstance(candidate.metrics.far, UnavailableValue)
            else _metric_record(candidate.metrics.far, unit="ratio", method="total GFA / approved ExplorationDesignArea", data_gaps=gaps)
        ),
        "coverage_ratio": _metric_record(
            candidate.metrics.coverage_ratio,
            unit="ratio",
            method="union generated and retained footprints / approved ExplorationDesignArea",
            data_gaps=gaps,
        ),
        "height_m": _metric_record(
            candidate.metrics.height_m,
            unit="m",
            method="generated massing height; retained building height is not inferred",
            data_gaps=gaps + (["retained building height is not included"] if has_unknown_retained_floors else []),
        ),
        "road_ratio": {
            "value": float(unary_union((*candidate.road_surfaces, *candidate.preserved_road_surfaces)).area / area.area)
            if candidate.road_surfaces or candidate.preserved_road_surfaces else 0.0,
            "unit": "ratio",
            "method": "union of generated and retained road surfaces / approved ExplorationDesignArea",
            "validation_status": "FIXTURE_ONLY" if fixture_only else "VALIDATED",
            "data_gaps": gaps,
        },
        "open_space_ratio": {
            "value": float(candidate.open_space.area / area.area),
            "unit": "ratio",
            "method": "generated open-space area / approved ExplorationDesignArea",
            "validation_status": "FIXTURE_ONLY" if fixture_only else "VALIDATED",
            "data_gaps": gaps,
        },
    }
    if constraint is not None and constraint.denominator is not None and not isinstance(candidate.metrics.gfa_m2, UnavailableValue):
        from urban_design.morphology.metrics import calculate_far
        metrics["far"]["value"] = calculate_far(candidate.metrics.gfa_m2, far_area)
    metrics["far"].update(denominator_label=far_label, denominator_area_m2=far_area)
    metrics["far"]["method"] = "total GFA / selected FAR denominator; denominator: " + far_label if constraint is not None and constraint.denominator is not None else metrics["far"]["method"] + "; denominator: " + far_label
    total_generated_gfa = known_gfa
    use_areas: dict[str, float] = {}
    for building in candidate.buildings:
        label = building.use_label
        use_areas[label] = use_areas.get(label, 0.0) + float(building.footprint.area) * building.floor_count
    for label, use_gfa in sorted(use_areas.items()):
        metrics[f"use_ratio:{label}"] = {
            "value": float(use_gfa / total_generated_gfa) if total_generated_gfa else None,
            "unit": "ratio",
            "method": "generated floor-plate GFA for approved zone use / generated GFA",
            "validation_status": "FIXTURE_ONLY" if fixture_only else "VALIDATED",
            "data_gaps": gaps + (["retained building use is not included"] if has_unknown_retained_floors else []),
        }
    return metrics


def _geojson(candidate: Any, inputs: ApprovedInputs, floor_records: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []

    def add(feature_id: str, kind: str, geometry: Any, **properties: Any) -> None:
        features.append({
            "type": "Feature",
            "id": feature_id,
            "geometry": mapping(geometry),
            "properties": {"feature_kind": kind, **properties},
        })

    for road in candidate.roads:
        add(
            road.segment_id,
            "road_centerline",
            road.geometry,
            layer=road.layer,
            bridge=road.bridge,
            tunnel=road.tunnel,
            road_width_scope=road.road_width_scope,
        )
    for index, surface in enumerate(candidate.road_surfaces, 1):
        add(f"{candidate.candidate_id}-road-surface-{index}", "generated_road_surface", surface)
    for road, surface in zip(candidate.preserved_roads, candidate.preserved_road_surfaces, strict=True):
        add(
            f"preserved-road-{road.road_id}",
            "preserved_road",
            road.geometry,
            locked=True,
            layer=road.layer,
            bridge=road.bridge,
            tunnel=road.tunnel,
            source_artifact_id=road.source_artifact_id,
            source_snapshot_id=road.source_snapshot_id,
        )
        add(f"preserved-road-surface-{road.road_id}", "preserved_road_surface", surface, locked=True)
    unconnected_by_id = {item.contact_id: item for item in candidate.unconnected_contacts}
    for contact in candidate.external_contacts:
        unconnected = unconnected_by_id.get(contact.contact_id)
        add(
            contact.contact_id,
            "external_road_contact",
            contact.point,
            source_road_id=contact.source_road_id,
            source_artifact_id=contact.source_artifact_id,
            source_snapshot_id=contact.source_snapshot_id,
            layer=contact.layer,
            bridge=contact.bridge,
            tunnel=contact.tunnel,
            highway=contact.highway,
            source_mode=contact.source_mode,
            priority=contact.priority,
            connection_status="UNCONNECTED" if unconnected else "CONNECTED",
            connection_reason=unconnected.reason if unconnected else None,
        )
    add(f"{candidate.candidate_id}-open-space", "open_space", candidate.open_space)
    for index, parcel in enumerate(candidate.parcels, 1):
        add(f"{candidate.candidate_id}-parcel-{index}", "parcel", parcel)
    for building in candidate.buildings:
        add(
            building.building_id,
            "building",
            building.footprint,
            floor_count=building.floor_count,
            use_label=building.use_label,
            zone_id=building.zone_id,
            strategy_parameter=building.strategy_parameter,
        )
        for block in building.floor_blocks:
            add(
                f"{building.building_id}-floor-{block.floor_number}",
                "floor_block",
                block.footprint,
                floor_number=block.floor_number,
                base_height_m=block.base_height_m,
                top_height_m=block.top_height_m,
                height_reference="relative_to_local_ground_zero",
                use_label=block.use_label,
            )
    for fragment in candidate.excluded_fragments:
        if fragment.geometry is not None:
            add(
                fragment.fragment_id,
                "excluded_parcel_fragment",
                fragment.geometry,
                excluded=True,
                area_m2=fragment.area_m2,
                minimum_width_m=fragment.minimum_width_m,
                reason=fragment.reason,
            )
    floor_by_id = {item["building_id"]: item for item in floor_records}
    for disposition, geometry, _properties in inputs.retained_buildings:
        add(
            disposition.feature_id,
            "retained_building",
            geometry,
            locked=True,
            source_feature_id=disposition.source_feature_id,
            source_artifact_id=disposition.source_artifact_id,
            gfa=floor_by_id.get(disposition.feature_id, {}).get("floor_count", {
                "status": "unavailable",
                "reason": "retained floor estimate was not computed",
            }),
        )
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": features,
    }


def _strategy_explanation(candidate: Any, inputs: ApprovedInputs, metrics: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    explanation = (
        f"{candidate.strategy_label}. 此系統範本包含 {len(candidate.roads)} 條道路中心線、"
        f"{len(candidate.buildings)} 棟量體、{len(candidate.parcels)} 個街廓，"
        f"開放空間面積為 {float(candidate.open_space.area):.3f} m²。"
        "這是待設計者審查的系統提案，不代表採納、合規判定或方案排名。"
    )
    return explanation, {
        "status": "確定性系統範本說明",
        "provider": "none",
        "provider_status": "NON_AI: DETERMINISTIC_TEMPLATE",
        "evidence_refs": [],
    }


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise FileExistsError(f"immutable artifact path already contains different bytes: {path}")


def _sqlite_backup(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing database: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)


def _authority_snapshot(source: Path, expected_sha256: str) -> tuple[Path, str]:
    expected = expected_sha256.removeprefix("sha256:")
    if not _HASH_RE.fullmatch(expected_sha256):
        raise ValueError("--expected-sha256 must contain 64 lowercase hexadecimal characters, optionally prefixed by sha256:")
    actual = _hash_file(source)
    if actual != expected:
        raise ValueError(f"authority database SHA-256 mismatch: expected {expected}, current {actual}")
    fd, raw_path = tempfile.mkstemp(
        prefix=f"{source.name}.pre-generation-",
        suffix=".sqlite3",
        dir=source.parent,
    )
    os.close(fd)
    snapshot = Path(raw_path)
    # sqlite3 backup API captures a consistent database snapshot, including WAL state.
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(snapshot) as destination_connection:
            source_connection.backup(destination_connection)
    snapshot_hash = _hash_file(snapshot)
    if _hash_file(source) != actual:
        raise ValueError("authority database changed after its expected SHA-256 was checked; no generation writes were made")
    return snapshot, snapshot_hash


def _persist_generated_records(
    store: ProjectStateStore,
    *,
    inputs: ApprovedInputs,
    candidates: list[Any],
    floor_records: list[dict[str, Any]],
    output_database: Path,
    artifact_root: Path,
    run_id: str,
    seed: int,
    fixture_only: bool,
) -> tuple[list[str], dict[str, Any], Artifact, ToolExecution]:
    timestamp = datetime.now(timezone.utc)
    constraint_values = _constraint_values(inputs.constraint_set)
    road_widths = {
        item.scope: float(item.value)
        for item in inputs.constraint_set.constraints
        if item.name == "road_width"
    }
    road_width = next(iter(road_widths.values())) if len(road_widths) == 1 else None
    far_upper = float(constraint_values["far_upper_limit"][0])
    coverage_upper = float(constraint_values["coverage_upper_limit"][0])
    height_limits = [float(item.value) for item in inputs.constraint_set.constraints if item.name == "height_upper_limit"]
    max_height = min(height_limits)
    first_floor_height = float(constraint_values["first_floor_height"][0])
    standard_floor_height = float(constraint_values["standard_floor_height"][0])
    floor_count = max(1, int((max_height - first_floor_height) // standard_floor_height) + 1)
    source_artifacts = list(inputs.source_artifacts)
    source_snapshots = list(inputs.source_snapshots)
    source_hashes = {item.entity_id: item.payload["sha256"] for item in source_artifacts}
    source_artifact_ids = [item.entity_id for item in source_artifacts]
    source_snapshot_ids = [item.entity_id for item in source_snapshots]
    snapshot_hashes = {item.entity_id: item.payload["sha256"] for item in source_snapshots}
    scenario_ids: list[str] = []
    comparison_inputs: list[dict[str, Any]] = []
    rules_version = _FIXTURE_RULES_VERSION if fixture_only else _RULES_VERSION
    generator_name = (
        "urban_design.morphology.strategies.generate_fixture_strategies"
        if fixture_only
        else "urban_design.morphology.strategies.generate_site_strategies"
    )
    generator_version = _FIXTURE_GENERATOR_VERSION if fixture_only else _GENERATOR_VERSION
    artifact_prefix = "scenario-approved-fixture" if fixture_only else "scenario-approved-site"

    for candidate in candidates:
        scenario_id = f"{artifact_prefix}-{run_id}-{candidate.strategy_id}"
        scenario_ids.append(scenario_id)
        metrics = _candidate_metrics(
            candidate,
            inputs.design_area,
            inputs=inputs,
            has_unknown_retained_floors=any(item["floor_count"].get("status") == "unavailable" for item in floor_records),
        )
        explanation, explanation_meta = _strategy_explanation(candidate, inputs, metrics)
        geometry_document = _geojson(candidate, inputs, floor_records)
        geometry_bytes = _canonical_json(geometry_document)
        geometry_sha = _hash_bytes(geometry_bytes)
        geometry_artifact_id = f"artifact-{scenario_id}-geometry"
        geometry_path = artifact_root / run_id / f"{candidate.strategy_id}.geojson"
        _write_immutable(geometry_path, geometry_bytes)
        geometry_artifact = Artifact(
            id=geometry_artifact_id,
            type="scenario-geometry",
            uri=str(geometry_path.resolve()),
            sha256="sha256:" + geometry_sha,
            mime="application/geo+json",
            crs="EPSG:28992",
            producer=f"approved-generation-{candidate.provenance.casefold()}-adapter",
            created_at=timestamp,
            project_id=inputs.project_id,
            size_bytes=len(geometry_bytes),
            parent_artifact_ids=source_artifact_ids,
        )
        store.create_typed(
            geometry_artifact,
            actor="approved-generation",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=run_id,
            reason="Persist deterministic strategy geometry with its provenance and validation receipt",
        )

        far_record = metrics["far"]
        denominator_hash = _hash_bytes(inputs.design_area.normalize().wkb)
        if not fixture_only and not far_record["denominator_label"].startswith("legacy/"):
            denominator_hash = _hash_bytes(_canonical_json({
                "design_area_hash": denominator_hash,
                "label": far_record["denominator_label"],
                "area_m2": far_record["denominator_area_m2"],
                "water_geometry_hash": None if inputs.water_geometry is None else _hash_bytes(inputs.water_geometry.normalize().wkb),
            }))
        parameters = {
            "provenance": candidate.provenance,
            "input_hash": "sha256:" + inputs.input_hash,
            "workspace_id": inputs.workspace.workspace_id,
            "workspace_revision": inputs.workspace.revision,
            "workspace_decision_id": inputs.workspace_decision.id,
            "source_snapshot_ids": source_snapshot_ids,
            "constraint_set_id": inputs.constraint_set.id,
            "constraint_set_version": inputs.constraint_set.version,
            "constraint_decision_id": inputs.constraint_decision.id,
            "seed": seed,
            "strategy_id": candidate.strategy_id,
            "strategy_label": candidate.strategy_label,
            "strategy_explanation_status": explanation_meta["status"],
            "strategy_explanation": explanation,
            "strategy_explanation_model": explanation_meta,
            "floor_estimates": floor_records,
            "metrics": metrics,
            "validation": {
                "valid": bool(candidate.valid),
                "failure_reasons": list(candidate.failure_reasons),
                "road_component_count": candidate.road_component_count,
                "external_connection_count": candidate.external_connection_count,
                "contact_connectivity_rules_version": "contact-connectivity-v2",
                "unconnected_contacts": [
                    {
                        "contact_id": item.contact_id,
                        "source_road_id": item.source_road_id,
                        "highway": item.highway,
                        "source_mode": item.source_mode,
                        "priority": item.priority,
                        "reason": item.reason,
                        "layer": item.layer,
                        "bridge": item.bridge,
                        "tunnel": item.tunnel,
                    }
                    for item in candidate.unconnected_contacts
                ],
            },
            "denominator_hash": denominator_hash,
            "rules_version": rules_version,
            "contact_connectivity_rules_version": "contact-connectivity-v2",
            "parameters": {
                "road_width_m": road_width,
                "road_widths_by_scope_m": road_widths,
                "far_upper_bound": far_upper,
                "max_coverage_ratio": coverage_upper,
                "max_height_m": max_height,
                "first_floor_height_m": first_floor_height,
                "standard_floor_height_m": standard_floor_height,
                "strategy_floor_count": floor_count,
                "fragmentation_rule": {
                    "version": _FRAGMENT_RULE_VERSION,
                    "minimum_area_m2": _MINIMUM_FRAGMENT_AREA_M2,
                    "minimum_width_m": _MINIMUM_FRAGMENT_WIDTH_M,
                    "status": "SYSTEM_TEMPLATE_NOT_DESIGNER_APPROVAL",
                } if not fixture_only else None,
            },
            "strategy_difference": candidate.diff_report,
            "limitations": [
                "System-generated alternative remains a proposal and requires designer review.",
                "A missing OSM layer or relative-height tag is interpreted as at-grade layer 0; bridge and tunnel tags remain separate graph attributes.",
                "Retained building GFA and FAR remain unavailable when a preserved building floor count is unknown.",
            ],
        }
        if fixture_only:
            parameters["fixture_warning"] = "This database and generated strategy output are fixture-only; do not treat as formal project evidence."
            parameters["limitations"] = [
                "Fixture-only strategy geometry; it is not validated real-site evidence.",
                "Retained building GFA and FAR remain unavailable/partial when matching 3D BAG heights are absent.",
            ]
        scenario = Scenario(
            id=scenario_id,
            project_id=inputs.project_id,
            site_id=inputs.workspace.study_area_id,
            site_version=str(inputs.study_area.payload.get("version", inputs.study_area.revision)),
            morphology_family=generator_version,
            geometry_artifact_id=geometry_artifact_id,
            geometry_sha256="sha256:" + geometry_sha,
            generator=generator_name,
            generator_version=generator_version,
            seed=seed,
            parameters=parameters,
            parameter_refs=[inputs.constraint_set.id, inputs.workspace.workspace_id],
            constraint_set_id=inputs.constraint_set.id,
            status=(
                ScenarioStatus.PROPOSED
                if fixture_only or candidate.valid
                else ScenarioStatus.BLOCKED
            ),
        )
        store.create_typed(
            scenario,
            actor="approved-generation",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=run_id,
            reason="Save the generated candidate with its validator-derived proposal or blocked state",
        )
        execution_id = f"tool-execution-{scenario_id}"
        execution = ToolExecution(
            id=execution_id,
            project_id=inputs.project_id,
            scenario_id=scenario_id,
            tool="morphology.fixture-strategy-catalog" if fixture_only else "morphology.site-strategy-catalog",
            tool_version=generator_version,
            environment={"provenance": candidate.provenance, "crs": "EPSG:28992"},
            input_refs=[
                inputs.workspace.workspace_id,
                inputs.workspace_decision.id,
                inputs.constraint_set.id,
                inputs.constraint_decision.id,
                inputs.study_area.entity_id,
                *source_snapshot_ids,
            ],
            input_snapshot_hashes={
                "workspace": "sha256:" + _normalized_hash(inputs.workspace.payload_digest or "") if _normalized_hash(inputs.workspace.payload_digest or "") else "sha256:" + inputs.input_hash,
                "constraint_set": constraint_set_payload_digest(inputs.constraint_record.payload),
                **snapshot_hashes,
                **source_hashes,
            },
            input_artifact_ids=source_artifact_ids,
            input_artifact_hashes_by_id={
                item.entity_id: "sha256:" + _normalized_hash(item.payload["sha256"])
                for item in source_artifacts
            },
            input_artifact_hashes=["sha256:" + _normalized_hash(value) for value in source_hashes.values()],
            parameters={
                "input_hash": "sha256:" + inputs.input_hash,
                "seed": seed,
                "strategy_id": candidate.strategy_id,
                "validation": parameters["validation"],
                "explanation_status": explanation_meta["status"],
            },
            output_artifact_refs=[geometry_artifact_id],
            output_artifact_hashes=["sha256:" + geometry_sha],
            status=RunStatus.SUCCEEDED,
            idempotency_key=f"{inputs.input_hash}:{candidate.strategy_id}:{seed}",
            trace_ids=[run_id],
            limitations=parameters["limitations"],
        )
        store.create_typed(
            execution,
            actor="approved-generation",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=run_id,
            reason="Record deterministic strategy generation and validation receipt",
        )
        if candidate.valid:
            comparison_inputs.append({
                "scenario_id": scenario_id,
                "denominator_hash": denominator_hash,
                "rules_version": rules_version,
                "metrics": metrics,
            })

    comparison = (
        build_scenario_comparison(comparison_inputs)
        if len(comparison_inputs) >= 2
        else {
            "status": "INSUFFICIENT_VALID_CANDIDATES",
            "scenario_ids": [item["scenario_id"] for item in comparison_inputs],
            "metrics": [],
            "ranking": None,
            "overall_score": None,
        }
    )
    comparison_document = {
        **comparison,
        "candidate_count": len(candidates),
        "valid_candidate_count": len(comparison_inputs),
        "failed_candidate_count": len(candidates) - len(comparison_inputs),
        "project_id": inputs.project_id,
        "workspace_id": inputs.workspace.workspace_id,
        "workspace_revision": inputs.workspace.revision,
        "workspace_decision_id": inputs.workspace_decision.id,
        "constraint_set_id": inputs.constraint_set.id,
        "constraint_decision_id": inputs.constraint_decision.id,
        "provenance": "FIXTURE_ONLY" if fixture_only else candidates[0].provenance,
        "rules_version": rules_version,
        "input_hash": "sha256:" + inputs.input_hash,
    }
    comparison_bytes = _canonical_json(comparison_document)
    comparison_sha = _hash_bytes(comparison_bytes)
    comparison_artifact_id = f"artifact-{artifact_prefix}-{run_id}-comparison"
    comparison_scenario_ids = [item["scenario_id"] for item in comparison_inputs]
    comparison_path = artifact_root / run_id / "comparison.json"
    _write_immutable(comparison_path, comparison_bytes)
    comparison_artifact = Artifact(
        id=comparison_artifact_id,
        type="scenario-comparison",
        uri=str(comparison_path.resolve()),
        sha256="sha256:" + comparison_sha,
        mime="application/json",
        producer="urban_design.scenario_comparison.build_scenario_comparison",
        created_at=timestamp,
        project_id=inputs.project_id,
        size_bytes=len(comparison_bytes),
        parent_artifact_ids=[record.payload["geometry_artifact_id"] for record in store.list_current("Scenario", project_id=inputs.project_id) if record.entity_id in comparison_scenario_ids],
    )
    store.create_typed(
        comparison_artifact,
        actor="approved-generation",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        actor_session_id=run_id,
        reason="Persist non-ranking scenario comparison table data",
    )
    comparison_execution = ToolExecution(
        id=f"tool-execution-{artifact_prefix}-{run_id}-comparison",
        project_id=inputs.project_id,
        tool="scenario_comparison.non_ranking",
        tool_version="scenario-comparison-v1",
        environment={"provenance": "FIXTURE_ONLY" if fixture_only else candidates[0].provenance},
        input_refs=comparison_scenario_ids,
        input_snapshot_hashes={
            scenario_id: "sha256:" + _normalized_hash(store.current(scenario_id).payload["geometry_sha256"])
            for scenario_id in comparison_scenario_ids
        },
        parameters={"ranking": None, "overall_score": None, "status": comparison["status"]},
        output_artifact_refs=[comparison_artifact_id],
        output_artifact_hashes=["sha256:" + comparison_sha],
        status=RunStatus.SUCCEEDED,
        idempotency_key=f"{inputs.input_hash}:comparison:{seed}",
        trace_ids=[run_id],
        limitations=["Comparison is descriptive and non-ranking; it does not adopt a design proposal."],
    )
    store.create_typed(
        comparison_execution,
        actor="approved-generation",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        actor_session_id=run_id,
        reason="Record deterministic non-ranking fixture comparison",
    )
    return scenario_ids, comparison_document, comparison_artifact, comparison_execution


def run_approved_generation(
    *,
    source_database: str | Path,
    output_database: str | Path | None,
    artifact_root: str | Path | None,
    project_id: str,
    fixture_only: bool = False,
    write_authority: bool = False,
    expected_sha256: str | None = None,
) -> GenerationResult:
    source = Path(source_database).resolve()
    if not source.is_file():
        raise ApprovedGenerationBlocked([f"source database is not a file: {source}"])
    output = Path(output_database).resolve() if output_database is not None else source.with_name(source.stem + ".approved-generation.sqlite3")
    if write_authority:
        if expected_sha256 is None:
            raise ValueError("--write-authority requires --expected-sha256")
        if output != source:
            raise ValueError("--write-authority requires --output-db to resolve to the source database")
        if fixture_only:
            raise ValueError("fixture-only generation cannot write the authority database")
    else:
        if expected_sha256 is not None:
            raise ValueError("--expected-sha256 is only valid with --write-authority")
        if output == source:
            raise ValueError("in-place database writes require --write-authority and --expected-sha256")
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing output database: {output}")
    root = Path(artifact_root).resolve() if artifact_root is not None else output.with_name(output.stem + ".artifacts")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"refusing to write into non-empty artifact directory: {root}")

    snapshot_path = None
    snapshot_hash = None
    input_database = source
    if write_authority:
        assert expected_sha256 is not None
        snapshot_path, snapshot_hash = _authority_snapshot(source, expected_sha256)
        input_database = snapshot_path

    with ProjectStateStore(input_database, read_only=True) as read_store:
        inputs = _load_approved_inputs(read_store, project_id, site_generation=not fixture_only)
        retained_floor_counts, floor_records = _floor_estimates(read_store, inputs)

    try:
        if fixture_only:
            if not inputs.design_area.equals(box(*inputs.design_area.bounds)):
                raise MorphologyGenerationError("fixture mode accepts an axis-aligned rectangle only")
            if inputs.design_area.interiors:
                raise MorphologyGenerationError("fixture mode does not accept design-area holes")
            constraint_values = _constraint_values(inputs.constraint_set)
            road_width_values = constraint_values.get("road_width", [])
            if len(road_width_values) != 1:
                raise MorphologyGenerationError("fixture mode requires exactly one approved road_width constraint")
            max_height_values = [float(item.value) for item in inputs.constraint_set.constraints if item.name == "height_upper_limit"]
            max_height = min(max_height_values)
            first_floor_height = float(constraint_values["first_floor_height"][0])
            standard_floor_height = float(constraint_values["standard_floor_height"][0])
            floor_count = max(1, int((max_height - first_floor_height) // standard_floor_height) + 1)
            generation_input = FixtureGenerationInput(
                design_area=inputs.design_area,
                crs="EPSG:28992",
                seed=int(inputs.input_hash[:8], 16),
                road_width_m=float(road_width_values[0]),
                first_floor_height_m=first_floor_height,
                standard_floor_height_m=standard_floor_height,
                strategy_floor_count=floor_count,
                far_upper_bound=float(constraint_values["far_upper_limit"][0]),
                max_height_m=max_height,
                max_coverage_ratio=float(constraint_values["coverage_upper_limit"][0]),
                retained_footprints=tuple(item[1] for item in inputs.retained_buildings),
                retained_floor_counts=retained_floor_counts,
                provenance="FIXTURE_ONLY",
                fixture_parameter_version=_FIXTURE_RULES_VERSION,
            )
            generated = generate_fixture_strategies(generation_input)
            candidates = [_zone_candidate(candidate, inputs) for candidate in generated.candidates]
        else:
            generation_input = _site_generation_input(inputs, retained_floor_counts)
            generated = generate_site_strategies(generation_input)
            candidates = list(generated.candidates)
    except (TypeError, ValueError) as exc:
        mode = "fixture" if fixture_only else "approved-site"
        raise ApprovedGenerationBlocked([f"{mode} strategy generation rejected the current approved inputs: {exc}"])
    if len(candidates) != 3:
        raise ApprovedGenerationBlocked([f"strategy catalogue returned {len(candidates)} candidate(s); expected 3 system templates"])

    if not write_authority:
        _sqlite_backup(source, output)
    elif _hash_file(source) != expected_sha256.removeprefix("sha256:"):
        raise ValueError("authority database changed after approval validation; no generation writes were made")

    run_id = uuid.uuid4().hex[:12]
    seed = int(inputs.input_hash[:8], 16)
    try:
        with ProjectStateStore(output) as write_store:
            scenario_ids, comparison, _comparison_artifact, _comparison_execution = _persist_generated_records(
                write_store,
                inputs=inputs,
                candidates=candidates,
                floor_records=floor_records,
                output_database=output,
                artifact_root=root,
                run_id=run_id,
                seed=seed,
                fixture_only=fixture_only,
            )
    except Exception:
        # Preserve the copy/snapshot and any append-only rows for inspection.
        raise
    valid_count = sum(candidate.valid for candidate in candidates)
    provenance = candidates[0].provenance if candidates else "UNKNOWN"
    status = (
        "GENERATED_FIXTURE_ONLY"
        if fixture_only or provenance == "FIXTURE_ONLY"
        else ("GENERATED_PROPOSALS" if valid_count == len(candidates) else f"PARTIAL_VALID_{valid_count}_OF_{len(candidates)}")
    )
    return GenerationResult(
        status=status,
        scenario_ids=tuple(scenario_ids),
        comparison=comparison,
        output_database=output,
        artifact_root=root,
        snapshot_path=snapshot_path,
        snapshot_sha256=snapshot_hash,
        valid_candidate_count=valid_count,
        failed_candidate_count=len(candidates) - valid_count,
    )


__all__ = ["ApprovedGenerationBlocked", "GenerationResult", "run_approved_generation"]
