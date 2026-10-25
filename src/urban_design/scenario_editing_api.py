"""Persistent DRAFT scenario editing routes built on the deterministic cores."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import uuid
from typing import Any, Literal, Protocol

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, StrictStr
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, mapping, shape
from shapely.ops import unary_union

from .editing.commands import (
    AddFloorCommand,
    EditHistory,
    EditCommandError,
    IdempotencyConflict,
    MoveCommand,
    PushSideCommand,
    RemoveFloorCommand,
    RevisionConflict,
    RotateCommand,
)
from .editing.floors import BuildingMassing, FloorStorey
from .editing.roads import RoadEdge, RoadEditError, RoadGraph, RoadNode, move_road_node, road_snap_candidates
from .editing.road_dependencies import stale_road_dependencies
from .editing.validation import ValidationFinding, validate_building
from .models import ActorKind, Artifact, RunStatus, Scenario, ToolExecution
from .store import EntityNotFoundError, PayloadError, ProjectStateStore, RevisionConflictError


@dataclass(frozen=True)
class ResolvedEditorRef:
    entity_id: str
    revision: int
    sha256: str


@dataclass(frozen=True)
class FormalEditorBinding:
    """Server resolver output, never accepted from an HTTP request.

    The injected W6-6/7 resolver must semantically resolve the accepted baseline
    decision, source snapshots, active constraints and their immutable hashes.
    IDs alone are not proof. This module deliberately supplies no live resolver.
    """
    scenario_id: str
    scenario_revision: int
    geometry_sha256: str
    editor_inputs_sha256: str
    baseline_status: str
    baseline_decision_ref: ResolvedEditorRef
    constraint_refs: tuple[ResolvedEditorRef, ...]
    source_refs: tuple[ResolvedEditorRef, ...]


class FormalEditorAdapter(Protocol):
    def resolve(self, store: ProjectStateStore, record: Any) -> FormalEditorBinding:
        """Resolve persisted authority or raise; never trust client approval flags."""
        ...


def _editor_binding(store: ProjectStateStore, record: Any, adapter: FormalEditorAdapter | None) -> FormalEditorBinding | None:
    provenance = record.payload.get("parameters", {}).get("provenance")
    if provenance == "FIXTURE_ONLY":
        return None
    if provenance != "FORMAL_DRAFT" or adapter is None:
        raise HTTPException(status_code=409, detail="BLOCKED: formal editor baseline/authority adapter is NOT_READY")
    try:
        binding = adapter.resolve(store, record)
    except (ValueError, EntityNotFoundError) as exc:
        reason = str(exc).strip() or "formal editor authority references cannot be resolved"
        raise HTTPException(status_code=409, detail=f"BLOCKED: {reason}") from exc
    if not isinstance(binding, FormalEditorBinding) or (
        binding.scenario_id != record.entity_id
        or binding.scenario_revision != record.revision
        or binding.editor_inputs_sha256 != "sha256:" + _hash_json(record.payload.get("parameters", {}))
        or binding.geometry_sha256 != record.payload.get("geometry_sha256")
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", binding.geometry_sha256)
        or binding.baseline_status != "ACCEPTED"
        or not _resolved_refs_valid((binding.baseline_decision_ref,))
        or not binding.constraint_refs or not binding.source_refs
        or not _resolved_refs_valid((*binding.constraint_refs, *binding.source_refs))
    ):
        raise HTTPException(status_code=409, detail="BLOCKED: formal editor binding is stale or incomplete")
    artifact = store.current(record.payload["geometry_artifact_id"])
    if artifact.payload.get("sha256") != binding.geometry_sha256:
        raise HTTPException(status_code=409, detail="BLOCKED: scenario and artifact geometry hashes differ")
    _artifact_file(store, record.payload["geometry_artifact_id"])
    return binding


def _resolved_refs_valid(refs: tuple[ResolvedEditorRef, ...]) -> bool:
    return all(isinstance(ref, ResolvedEditorRef) and isinstance(ref.entity_id, str)
        and bool(ref.entity_id.strip()) and type(ref.revision) is int and ref.revision > 0
        and isinstance(ref.sha256, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", ref.sha256)
        for ref in refs)


class MassingEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    building_id: StrictStr
    command: dict[str, Any]
    expected_revision: StrictInt = Field(..., ge=0)
    idempotency_key: StrictStr = Field(..., min_length=1, max_length=128)


class EditPointerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(..., ge=0)
    revision_id: StrictInt | None = Field(default=None, ge=0)


class RoadSnapPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_m: FiniteFloat
    y_m: FiniteFloat
    expected_revision: StrictInt = Field(..., ge=0)
    perpendicular_anchor_node_id: StrictStr | None = None
    expected_graph_hash: StrictStr | None = None


class RoadNodeMoveRequest(RoadSnapPreviewRequest):
    idempotency_key: StrictStr = Field(..., min_length=1, max_length=128)
    snap_kind: Literal["ENDPOINT", "NEAREST_POINT", "MIDPOINT", "INTERSECTION", "PERPENDICULAR", "QUARTER", "THREE_QUARTER"] | None = None
    target_id: StrictStr | None = None


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_file(store: ProjectStateStore, artifact_id: str) -> tuple[dict[str, Any], Path]:
    try:
        record = store.current(artifact_id)
        content = Path(record.payload["uri"]).read_bytes()
        if "sha256:" + hashlib.sha256(content).hexdigest() != record.payload.get("sha256"):
            raise HTTPException(status_code=409, detail="BLOCKED: scenario geometry artifact hash differs")
        document = json.loads(content)
    except (EntityNotFoundError, OSError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="scenario geometry artifact is unavailable") from exc
    if document.get("type") != "FeatureCollection":
        raise HTTPException(status_code=409, detail="scenario geometry artifact is not a GeoJSON FeatureCollection")
    return document, Path(record.payload["uri"])


def _store_geometry_artifact(
    store: ProjectStateStore,
    artifact_root: Path,
    *,
    scenario_id: str,
    edit_id: str,
    document: dict[str, Any],
    project_id: str,
    parent_artifact_id: str,
) -> tuple[Artifact, str]:
    content = (json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    artifact_id = f"artifact-{scenario_id}-{edit_id}"
    path = artifact_root / digest.removeprefix("sha256:")[:2] / f"{artifact_id}.geojson"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest.removeprefix("sha256:"):
            raise HTTPException(status_code=409, detail="immutable scenario revision artifact already differs")
    else:
        try:
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest.removeprefix("sha256:"):
                raise HTTPException(status_code=409, detail="scenario revision artifact was concurrently replaced")
    artifact = Artifact(
        id=artifact_id,
        type="SCENARIO_GEOMETRY_DRAFT",
        uri=str(path),
        sha256=digest,
        mime="application/geo+json",
        crs="EPSG:28992",
        producer="scenario-edit-api",
        created_at=datetime.now(timezone.utc),
        project_id=project_id,
        size_bytes=len(content),
        parent_artifact_ids=[parent_artifact_id],
    )
    store.create_typed(
        artifact,
        actor="scenario-editor",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        actor_session_id=f"scenario-edit-{uuid.uuid4().hex[:12]}",
        reason="Append immutable DRAFT scenario geometry artifact",
    )
    return artifact, digest


def _validation_payload(result: Any, building: BuildingMassing, area: Any, limits: dict[str, Any]) -> dict[str, Any]:
    validated = validate_building(building, design_area=area, additional_findings=result.validation.findings, admitted_provenance=building.provenance)
    findings = list(validated.findings)
    floor_area = sum(float(floor.geometry.area) for floor in building.floors)
    site_area = float(area.area)
    far = floor_area / site_area if site_area > 0 else None
    coverage = float(unary_union([floor.geometry for floor in building.floors if floor.level == 0]).area / site_area) if site_area > 0 else None
    height = building.first_floor_height_m + max(0, len(building.floors) - 1) * building.standard_floor_height_m
    checks = (
        (limits.get("far_upper_bound"), far, "FAR_ABOVE_UPPER_BOUND", "FAR exceeds declared upper bound"),
        (limits.get("max_coverage_ratio"), coverage, "COVERAGE_ABOVE_UPPER_BOUND", "coverage exceeds declared upper bound"),
        (limits.get("max_height_m"), height, "HEIGHT_ABOVE_UPPER_BOUND", "height exceeds declared upper bound"),
    )
    for upper, value, code, message in checks:
        if upper is not None and value is not None and value > upper:
            findings.append(ValidationFinding(code, message, "ERROR"))
    return {
        "geometry_valid": not any(item.severity == "ERROR" for item in findings),
        "acceptance_eligible": False,
        "analysis_eligible": False,
        "solid_topology": validated.solid_topology,
        "provenance": building.provenance,
        "findings": [
            {"code": item.code, "message": item.message, "severity": item.severity, "floor_id": item.floor_id}
            for item in findings
        ],
    }


def _building_from_payload(value: dict[str, Any]) -> BuildingMassing:
    return BuildingMassing(
        id=value["building_id"],
        floors=tuple(
            FloorStorey(item["floor_id"], int(item["level"]), shape(item["geometry"]))
            for item in value["floors"]
        ),
        first_floor_height_m=float(value["first_floor_height_m"]),
        standard_floor_height_m=float(value["standard_floor_height_m"]),
        provenance=value.get("provenance", "UNKNOWN"),
    )


def _building_payload(building: BuildingMassing, use_label: str) -> dict[str, Any]:
    return {
        "building_id": building.id,
        "floors": [
            {"floor_id": floor.id, "level": floor.level, "geometry": mapping(floor.geometry)}
            for floor in sorted(building.floors, key=lambda item: item.level)
        ],
        "first_floor_height_m": building.first_floor_height_m,
        "standard_floor_height_m": building.standard_floor_height_m,
        "provenance": building.provenance,
        "use_label": use_label,
        "geometry_hash": building.geometry_hash(),
    }


def _massing_command(value: dict[str, Any], before_hash: str) -> Any:
    kind = value.get("type")
    if kind == "add_floor":
        return AddFloorCommand(new_floor_id=value.get("new_floor_id", ""))
    if kind == "remove_floor":
        return RemoveFloorCommand(floor_id=value.get("floor_id", ""))
    if kind == "push_side":
        pairs = value.get("floor_edge_indices", [])
        return PushSideCommand(
            floor_edge_indices=tuple((str(item[0]), item[1]) for item in pairs),
            steps=value.get("steps"),
            origin_geometry_hash=value.get("origin_geometry_hash") or before_hash,
        )
    if kind == "move":
        return MoveCommand(dx_m=value.get("dx_m"), dy_m=value.get("dy_m"))
    if kind == "rotate":
        return RotateCommand(angle_degrees=value.get("angle_degrees"))
    raise HTTPException(status_code=422, detail="unsupported massing edit command")


def _revision_record(revision: Any, revision_id: int, parent_revision_id: int | None, use_label: str, validation: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    return {
        "revision_id": revision_id,
        "parent_revision_id": parent_revision_id,
        "status": "DRAFT",
        "state": "DRAFT",
        "building": _building_payload(revision.building, use_label),
        "command": asdict(revision.command) if revision.command is not None else None,
        "before_geometry_hash": revision.before_geometry_hash,
        "after_geometry_hash": revision.after_geometry_hash,
        "validation": validation,
        "idempotency_key": revision.idempotency_key,
        "artifact_id": artifact_id,
    }


def _graph_from_payload(value: dict[str, Any]) -> RoadGraph:
    return RoadGraph(
        nodes=tuple(RoadNode(**{**item, "lineage_ids": tuple(item.get("lineage_ids", []))}) for item in value["nodes"]),
        edges=tuple(
            RoadEdge(
                **{**item, "lineage_ids": tuple(item.get("lineage_ids", [])), "access_refs": tuple(item.get("access_refs", []))}
            )
            for item in value["edges"]
        ),
    )


def _graph_payload(graph: RoadGraph) -> dict[str, Any]:
    return {
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
        "graph_hash": graph.graph_hash,
    }


def _syntax_dependencies(parameters: dict[str, Any]) -> list[str]:
    value = parameters.get("syntax_result_ids", [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise HTTPException(status_code=409, detail="persisted Syntax dependency references are invalid")
    return sorted(set(item.strip() for item in value))


def _replace_building_feature(document: dict[str, Any], building: BuildingMassing) -> dict[str, Any]:
    features = [
        item for item in document.get("features", [])
        if not (
            item.get("id") == building.id
            or item.get("properties", {}).get("building_id") == building.id
        )
    ]
    for floor in sorted(building.floors, key=lambda item: item.level):
        elevation = building.first_floor_height_m + max(0, floor.level - 1) * building.standard_floor_height_m
        height = building.first_floor_height_m if floor.level == 0 else building.standard_floor_height_m
        features.append({
            "type": "Feature",
            "id": f"{building.id}-{floor.id}",
            "geometry": mapping(floor.geometry),
            "properties": {
                "feature_kind": "building_floor",
                "building_id": building.id,
                "floor_id": floor.id,
                "level": floor.level,
                "base_elevation_m": elevation,
                "floor_height_m": height,
                "locked": False,
            },
        })
    return {**document, "features": features}


def _replace_road_features(document: dict[str, Any], graph: RoadGraph, width_m: float) -> dict[str, Any]:
    features = [
        item for item in document.get("features", [])
        if item.get("properties", {}).get("feature_kind") not in {"road_centerline", "road_surface"}
    ]
    nodes = {item.node_id: item for item in graph.nodes}
    lines = []
    for edge in graph.edges:
        line = LineString([(nodes[edge.start_node_id].x_m, nodes[edge.start_node_id].y_m), (nodes[edge.end_node_id].x_m, nodes[edge.end_node_id].y_m)])
        lines.append(line)
        features.append({
            "type": "Feature",
            "id": edge.edge_id,
            "geometry": mapping(line),
            "properties": {"feature_kind": "road_centerline", "layer": edge.layer, "bridge": edge.bridge, "tunnel": edge.tunnel, "locked": edge.locked, "lineage_ids": list(edge.lineage_ids), "access_refs": list(edge.access_refs)},
        })
    if lines:
        surfaces = unary_union([line.buffer(width_m / 2, cap_style="flat", join_style="mitre") for line in lines])
        parts = list(surfaces.geoms) if surfaces.geom_type == "MultiPolygon" else [surfaces]
        for index, surface in enumerate(parts, 1):
            features.append({"type": "Feature", "id": f"road-surface-{index}", "geometry": mapping(surface), "properties": {"feature_kind": "road_surface"}})
    return {**document, "features": features}


def _apply_scenario_update(store: ProjectStateStore, record: Any, payload: dict[str, Any], reason: str) -> Any:
    try:
        from urban_design.analysis_lineage import with_analysis_statuses
        payload = with_analysis_statuses(store, record, payload, record.revision + 1)
        scenario = Scenario.model_validate(payload)
        return store.update(
            record.entity_id,
            scenario.model_dump(mode="json"),
            expected_revision=record.revision,
            replace=True,
            actor="scenario-editor",
            action="CreateDraftScenarioRevision",
            reason=reason,
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=f"scenario-edit-{uuid.uuid4().hex[:12]}",
        )
    except (RevisionConflictError, PayloadError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"scenario changed or draft revision is invalid: {exc}") from exc


def register_scenario_edit_routes(router: APIRouter, store: ProjectStateStore, artifact_root: Path, *, formal_adapter: FormalEditorAdapter | None = None) -> None:
    @router.get("/api/v1/scenarios/{scenario_id}/edits/dashboard")
    def editor_dashboard(scenario_id: str, building_id: str) -> dict[str, Any]:
        try:
            record = store.current(scenario_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="scenario was not found") from exc
        if record.entity_type != "DesignScenario":
            raise HTTPException(status_code=404, detail="scenario was not found")
        _editor_binding(store, record, formal_adapter)
        return {**_dashboard(record.payload.get("parameters", {}), building_id), "scenario_revision": record.revision}

    @router.post("/api/v1/scenarios/{scenario_id}/edits", status_code=201)
    def edit_massing(scenario_id: str, request: MassingEditRequest) -> dict[str, Any]:
        try:
            record = store.current(scenario_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="scenario was not found") from exc
        if record.entity_type != "DesignScenario":
            raise HTTPException(status_code=404, detail="scenario was not found")
        binding = _editor_binding(store, record, formal_adapter)
        payload = dict(record.payload)
        parameters = dict(payload.get("parameters", {}))
        editable = parameters.get("editable_buildings", [])
        source = next((item for item in editable if item.get("building_id") == request.building_id), None)
        if source is None:
            raise HTTPException(status_code=409, detail="selected building is missing, retained, or not editable")
        parameters.setdefault("editor_baseline_validation", parameters.get("validation", {}))
        histories = dict(parameters.get("edit_histories", {}))
        state = dict(histories.get(request.building_id, {}))
        active_revision_id = int(parameters.get("active_edit_revision_id", 0))
        snapshots = dict(parameters.get("massing_revision_snapshots", {}))
        global_revisions = list(parameters.get("massing_revision_records", []))
        if "0" not in snapshots:
            snapshots["0"] = {
                item["building_id"]: _building_payload(_building_from_payload(item), item.get("use_label", "UNASSIGNED_FIXTURE_USE"))
                for item in editable
            }
        current_buildings = dict(parameters.get("active_buildings", snapshots.get(str(active_revision_id), snapshots["0"])))
        active_source = current_buildings.get(request.building_id, source)
        source_building = _building_from_payload(active_source)
        if not state:
            base_artifact_id = parameters.get("root_geometry_artifact_id", payload["geometry_artifact_id"])
            state = {
                "active_revision_id": 0,
                "revisions": [{
                    "revision_id": 0,
                    "parent_revision_id": None,
                    "state": "BASELINE",
                    "building": _building_payload(_building_from_payload(source), source.get("use_label", "UNASSIGNED_FIXTURE_USE")),
                    "command": None,
                    "before_geometry_hash": None,
                    "after_geometry_hash": _building_from_payload(source).geometry_hash(),
                    "validation": {"geometry_valid": True, "acceptance_eligible": False, "analysis_eligible": False, "findings": []},
                    "idempotency_key": None,
                    "artifact_id": base_artifact_id,
                }],
                "idempotency": {},
            }
        revisions = list(state["revisions"])
        command = _massing_command(request.command, source_building.geometry_hash())
        command_data = asdict(command)
        fingerprint = _hash_json({"expected_revision": request.expected_revision, "command": command_data})
        prior = state.setdefault("idempotency", {}).get(request.idempotency_key)
        if prior is not None:
            if prior["fingerprint"] != fingerprint:
                raise HTTPException(status_code=409, detail="idempotency key was reused for a different edit")
            prior_revision = next(item for item in revisions if item["revision_id"] == prior["revision_id"])
            return JSONResponse(status_code=200, content={**prior_revision, "active_revision_id": active_revision_id, "idempotent_replay": True, "edit_state": "已確認"})
        if request.expected_revision != active_revision_id:
            raise HTTPException(status_code=409, detail=f"expected edit revision {request.expected_revision}, active revision is {active_revision_id}")
        expected_provenance = "FORMAL_DRAFT" if binding is not None else "FIXTURE_ONLY"
        if source_building.provenance != expected_provenance:
            raise HTTPException(status_code=409, detail="BLOCKED: building provenance does not match editor input")
        history = EditHistory(source_building, validator=lambda building, **kwargs: validate_building(building, admitted_provenance=expected_provenance, **kwargs))
        try:
            applied = history.apply(command, expected_revision=0, idempotency_key=request.idempotency_key)
        except RevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (EditCommandError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        area = shape(parameters["design_area_geometry"])
        validation = _validation_payload(applied, applied.building, area, parameters.get("limits", {}))
        validation["geometry_valid"] = validation["geometry_valid"] and applied.validation.geometry_valid
        next_revision_id = int(parameters.get("massing_revision_sequence", max((int(item["revision_id"]) for item in global_revisions), default=0))) + 1
        parent_artifact_id = payload["geometry_artifact_id"]
        document, _path = _artifact_file(store, parent_artifact_id)
        document = _replace_building_feature(document, applied.building)
        artifact, artifact_hash = _store_geometry_artifact(
            store, artifact_root, scenario_id=scenario_id, edit_id=f"massing-r{next_revision_id}",
            document=document, project_id=payload["project_id"], parent_artifact_id=parent_artifact_id,
        )
        use_label = active_source.get("use_label", "UNASSIGNED_FIXTURE_USE")
        revision_data = _revision_record(applied, next_revision_id, active_revision_id, use_label, validation, artifact.id)
        revision_data["building_id"] = request.building_id
        revisions.append(revision_data)
        state["active_revision_id"] = next_revision_id
        state["revisions"] = revisions
        state["idempotency"][request.idempotency_key] = {"fingerprint": fingerprint, "revision_id": next_revision_id}
        histories[request.building_id] = state
        current_buildings[request.building_id] = _building_payload(applied.building, use_label)
        parameters["edit_histories"] = histories
        parameters["active_edit_revision_id"] = next_revision_id
        parameters["massing_revision_sequence"] = next_revision_id
        snapshots[str(next_revision_id)] = dict(current_buildings)
        parameters["massing_revision_snapshots"] = snapshots
        parameters["massing_revision_records"] = [*global_revisions, {
            "revision_id": next_revision_id,
            "parent_revision_id": active_revision_id,
            "building_id": request.building_id,
            "command": command_data,
            "before_geometry_hash": applied.before_geometry_hash,
            "after_geometry_hash": applied.after_geometry_hash,
            "validation": validation,
            "artifact_id": artifact.id,
        }]
        parameters["active_buildings"] = current_buildings
        parameters["parent_scenario_revision"] = record.revision
        if binding is not None:
            parameters["editor_binding"] = asdict(binding)
        confirmed = _dashboard(parameters, request.building_id)
        parameters["metrics"] = confirmed["scenario_metrics"]
        parameters["validation"] = {"valid": confirmed["geometry_valid"], "failure_reasons": [item["code"] for item in validation["findings"] if item["severity"] == "ERROR"], "acceptance_eligible": False, "analysis_eligible": False}
        if len(source_building.floors) != len(applied.building.floors):
            e1_ids = parameters.get("e1_result_ids") or []
            if isinstance(e1_ids, list) and e1_ids:
                e1_statuses = dict(parameters.get("e1_statuses") or {})
                for result_id in e1_ids:
                    e1_statuses[result_id] = "STALE"
                parameters["e1_statuses"] = e1_statuses
        payload.update({"status": "draft", "geometry_artifact_id": artifact.id, "geometry_sha256": artifact_hash, "parameters": parameters})
        updated = _apply_scenario_update(store, record, payload, f"Create massing DRAFT revision {next_revision_id}")
        execution = ToolExecution(
            id=f"tool-execution-{scenario_id}-massing-r{next_revision_id}",
            project_id=payload["project_id"], scenario_id=scenario_id, tool="scenario-massing-editor", tool_version="w5-9-v1",
            parameters={"command": request.command, "building_id": request.building_id, "expected_revision": request.expected_revision, "before_geometry_hash": applied.before_geometry_hash, "after_geometry_hash": applied.after_geometry_hash, "validation": validation},
            output_artifact_refs=[artifact.id], output_artifact_hashes=[artifact_hash], status=RunStatus.SUCCEEDED,
            idempotency_key=request.idempotency_key, limitations=["DRAFT; not eligible for acceptance or analysis"],
        )
        store.create_typed(execution, actor="scenario-editor", actor_kind=ActorKind.AGENT_AUTOMATION, actor_session_id=f"scenario-edit-{uuid.uuid4().hex[:12]}", reason="Record deterministic massing edit execution")
        return {**revision_data, "scenario_revision": updated.revision, "active_revision_id": next_revision_id, "revision_count": len(revisions) - 1, "dashboard": confirmed, "edit_state": "已確認", "idempotent_replay": False}

    @router.post("/api/v1/scenarios/{scenario_id}/edits/undo")
    def undo_massing(scenario_id: str, request: EditPointerRequest) -> dict[str, Any]:
        return _move_massing_pointer(store, scenario_id, request, artifact_root, undo=True, formal_adapter=formal_adapter)

    @router.post("/api/v1/scenarios/{scenario_id}/edits/redo")
    def redo_massing(scenario_id: str, request: EditPointerRequest) -> dict[str, Any]:
        return _move_massing_pointer(store, scenario_id, request, artifact_root, undo=False, formal_adapter=formal_adapter)

    @router.post("/api/v1/scenarios/{scenario_id}/road-nodes/{node_id}/snap-candidates")
    def preview_road_snap(scenario_id: str, node_id: str, request: RoadSnapPreviewRequest) -> dict[str, Any]:
        try:
            record = store.current(scenario_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="scenario was not found") from exc
        if record.entity_type != "DesignScenario":
            raise HTTPException(status_code=404, detail="scenario was not found")
        parameters = record.payload.get("parameters", {})
        revision = parameters.get("road_edit_revision_id", 0)
        if revision != request.expected_revision:
            raise HTTPException(status_code=409, detail="STALE: road preview revision differs")
        try:
            graph = _graph_from_payload(parameters["road_graph"])
            if request.expected_graph_hash is not None and request.expected_graph_hash != graph.graph_hash:
                raise HTTPException(status_code=409, detail="STALE: road graph hash differs")
            tolerance = parameters["road_snap_tolerance_m"]
            candidates = road_snap_candidates(graph, node_id, x_m=request.x_m, y_m=request.y_m,
                snap_tolerance_m=tolerance, perpendicular_anchor_node_id=request.perpendicular_anchor_node_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=f"NOT_READY: {exc}") from exc
        provenance = parameters.get("provenance")
        ready = "NOT_READY" if graph.node(node_id).layer is None else ("FORMAL_DRAFT" if provenance == "FORMAL_DRAFT" else "DRAFT")
        return {"status": ready,
            "blocked_reason": "LEVEL_UNKNOWN" if graph.node(node_id).layer is None else None,
            "revision_id": revision, "graph_hash": graph.graph_hash,
            "snap_tolerance_m": tolerance, "candidates": [asdict(item) for item in candidates],
            "acceptance_eligible": False}

    @router.post("/api/v1/scenarios/{scenario_id}/road-nodes/{node_id}/move", status_code=201)
    def edit_road_node(scenario_id: str, node_id: str, request: RoadNodeMoveRequest) -> dict[str, Any]:
        try:
            record = store.current(scenario_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="scenario was not found") from exc
        if record.entity_type != "DesignScenario":
            raise HTTPException(status_code=404, detail="scenario was not found")
        binding = _editor_binding(store, record, formal_adapter)
        payload = dict(record.payload)
        parameters = dict(payload.get("parameters", {}))
        if binding is not None:
            parameters["editor_binding"] = asdict(binding)
        road_revision = int(parameters.get("road_edit_revision_id", 0))
        history = list(parameters.get("road_edit_history", []))
        try:
            snap_tolerance_m = float(parameters["road_snap_tolerance_m"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="scenario has no persisted road snap tolerance") from exc
        if not math.isfinite(snap_tolerance_m) or snap_tolerance_m <= 0:
            raise HTTPException(status_code=409, detail="scenario road snap tolerance is invalid")
        syntax_result_ids = _syntax_dependencies(parameters)
        command = {
            "node_id": node_id,
            "x_m": request.x_m,
            "y_m": request.y_m,
            "snap_tolerance_m": snap_tolerance_m,
            "syntax_result_ids": syntax_result_ids,
            "expected_graph_hash": request.expected_graph_hash,
            "snap_kind": request.snap_kind,
            "target_id": request.target_id,
            "perpendicular_anchor_node_id": request.perpendicular_anchor_node_id,
        }
        fingerprint = _hash_json({"expected_revision": request.expected_revision, "command": command})
        idempotency = dict(parameters.get("road_idempotency", {}))
        prior = idempotency.get(request.idempotency_key)
        if prior is not None:
            if prior["fingerprint"] != fingerprint:
                raise HTTPException(status_code=409, detail="idempotency key was reused for a different road edit")
            return {**prior["result"], "idempotent_replay": True}
        if request.expected_revision != road_revision:
            raise HTTPException(status_code=409, detail=f"expected road revision {request.expected_revision}, active revision is {road_revision}")
        try:
            graph = _graph_from_payload(parameters["road_graph"])
            if request.expected_graph_hash is not None and request.expected_graph_hash != graph.graph_hash:
                raise HTTPException(status_code=409, detail="STALE: road graph hash differs")
            result = move_road_node(
                graph, node_id, x_m=request.x_m, y_m=request.y_m,
                snap_tolerance_m=snap_tolerance_m,
                syntax_result_ids=syntax_result_ids,
                snap_kind=request.snap_kind, target_id=request.target_id,
                perpendicular_anchor_node_id=request.perpendicular_anchor_node_id,
            )
        except (KeyError, RoadEditError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result.graph_hash == graph.graph_hash:
            raise HTTPException(status_code=409, detail="road node move did not change the graph")
        try:
            invalidation = stale_road_dependencies(parameters, graph.graph_hash, result.graph_hash)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        document, _path = _artifact_file(store, payload["geometry_artifact_id"])
        width = float(parameters.get("strategy_parameters", {}).get("road_width_m", 6.0))
        document = _replace_road_features(document, result.graph, width)
        next_revision = road_revision + 1
        artifact, artifact_hash = _store_geometry_artifact(
            store, artifact_root, scenario_id=scenario_id, edit_id=f"roads-r{next_revision}",
            document=document, project_id=payload["project_id"], parent_artifact_id=payload["geometry_artifact_id"],
        )
        stale_ids = set(invalidation["stale_result_ids"])
        for source_key, status_key in (
            ("syntax_result_ids", "syntax_statuses"),
            ("accessibility_result_ids", "accessibility_statuses"),
            ("e1_result_ids", "e1_statuses"),
        ):
            statuses = dict(parameters.get(status_key) or {})
            for result_id in parameters.get(source_key) or []:
                if result_id in stale_ids:
                    statuses[result_id] = "STALE"
            parameters[status_key] = statuses
        result_payload = {
            "status": "FORMAL_DRAFT" if binding is not None else "DRAFT",
            "revision_id": next_revision,
            "node_id": node_id,
            "requested_x_m": result.requested_x_m,
            "requested_y_m": result.requested_y_m,
            "actual_x_m": result.actual_x_m,
            "actual_y_m": result.actual_y_m,
            "snap_tolerance_m": snap_tolerance_m,
            "snapped_to_node_id": result.snapped_to_node_id,
            "snapped_to_edge_id": result.snapped_to_edge_id,
            "snap_kind": result.snap_kind,
            "acceptance_eligible": False,
            "graph_hash_before": graph.graph_hash,
            "graph_hash_after": result.graph_hash,
            "stale_syntax_result_ids": list(result.stale_syntax_result_ids),
            "stale_result_ids": invalidation["stale_result_ids"],
            "syntax_statuses": parameters["syntax_statuses"],
            "accessibility_statuses": parameters["accessibility_statuses"],
            "e1_statuses": parameters["e1_statuses"],
            "validation": {
                "status": "PASS",
                "valid": True,
                "checks": {
                    "node_references_and_topology": "PASS",
                    "zero_length_edges": "PASS",
                },
                "edge_count": len(result.graph.edges),
                "connected_components": result.graph.connected_component_count,
            },
            "nodes": [asdict(item) for item in result.graph.nodes],
            "edges": [asdict(item) for item in result.graph.edges],
            "artifact_id": artifact.id,
            "idempotent_replay": False,
        }
        parameters["result_statuses"] = invalidation["result_statuses"]
        parameters["road_graph"] = _graph_payload(result.graph)
        parameters["road_edit_revision_id"] = next_revision
        parameters["road_edit_history"] = [*history, {"revision_id": next_revision, "command": command, "graph_hash_before": graph.graph_hash, "graph_hash_after": result.graph_hash, "snap_tolerance_m": snap_tolerance_m, "stale_syntax_result_ids": list(result.stale_syntax_result_ids), "artifact_id": artifact.id}]
        parameters["road_idempotency"] = {**idempotency, request.idempotency_key: {"fingerprint": fingerprint, "result": result_payload}}
        parameters["parent_scenario_revision"] = record.revision
        payload.update({"status": "draft", "geometry_artifact_id": artifact.id, "geometry_sha256": artifact_hash, "parameters": parameters})
        updated = _apply_scenario_update(store, record, payload, f"Create road-node DRAFT revision {next_revision}")
        execution = ToolExecution(
            id=f"tool-execution-{scenario_id}-roads-r{next_revision}", project_id=payload["project_id"], scenario_id=scenario_id,
            tool="scenario-road-node-editor", tool_version="w6-10-v1", parameters={**command, "graph_hash_before": graph.graph_hash, "graph_hash_after": result.graph_hash, "snap_tolerance_m": snap_tolerance_m, "stale_syntax_result_ids": list(result.stale_syntax_result_ids)},
            output_artifact_refs=[artifact.id], output_artifact_hashes=[artifact_hash], status=RunStatus.SUCCEEDED,
            idempotency_key=request.idempotency_key, limitations=["FORMAL_DRAFT; Syntax, E1, and accessibility remain STALE and are not recomputed" if binding is not None else "fixture-only; Syntax remains STALE and is not recomputed"],
        )
        store.create_typed(execution, actor="scenario-editor", actor_kind=ActorKind.AGENT_AUTOMATION, actor_session_id=f"scenario-road-edit-{uuid.uuid4().hex[:12]}", reason="Record deterministic road graph edit execution")
        result_payload["scenario_revision"] = updated.revision
        return result_payload


def _dashboard(parameters: dict[str, Any], selected_building_id: str) -> dict[str, Any]:
    base_buildings = {item["building_id"]: item for item in parameters.get("editable_buildings", [])}
    active = dict(parameters.get("active_buildings", base_buildings))
    active = {key: active.get(key, value) for key, value in base_buildings.items()}
    area = shape(parameters["design_area_geometry"])
    provenance = parameters.get("provenance", "UNKNOWN")
    geometry_valid = all(validate_building(_building_from_payload(item), design_area=area, admitted_provenance=provenance).geometry_valid for item in active.values())
    active_revision = int(parameters.get("active_edit_revision_id", 0))
    current_validation = next((item.get("validation", {}) for item in parameters.get("massing_revision_records", []) if int(item["revision_id"]) == active_revision), {})
    geometry_valid = geometry_valid and current_validation.get("geometry_valid", True)
    for history in parameters.get("edit_histories", {}).values():
        revision = next((item for item in history.get("revisions", []) if int(item["revision_id"]) == int(history.get("active_revision_id", 0))), {})
        geometry_valid = geometry_valid and revision.get("validation", {}).get("geometry_valid", True)
    site_area = float(area.area) if provenance == "FORMAL_DRAFT" else float(parameters.get("design_area_m2", 0))
    gfa_by_building = {key: sum(float(shape(floor["geometry"]).area) for floor in item["floors"]) for key, item in active.items()}
    total_gfa = sum(gfa_by_building.values())
    base_footprints = [shape(floor["geometry"]) for item in active.values() for floor in item["floors"] if int(floor["level"]) == 0]
    coverage_m2 = float(unary_union(base_footprints).area) if base_footprints and geometry_valid else 0.0
    total_far = total_gfa / site_area if site_area else None
    coverage_ratio = coverage_m2 / site_area if site_area else None
    limits = parameters.get("limits", {})
    building_data = active.get(selected_building_id)
    if building_data is None:
        raise HTTPException(status_code=404, detail="selected editable building was not found")
    height = float(building_data["first_floor_height_m"]) + max(0, len(building_data["floors"]) - 1) * float(building_data["standard_floor_height_m"])
    gfa = gfa_by_building[selected_building_id]
    metrics = {key: dict(value) for key, value in parameters.get("metrics", {}).items() if isinstance(value, dict)}

    def update_metric(metric_id: str, value: float | None, unit: str, method: str) -> None:
        prior = metrics.get(metric_id, {})
        metrics[metric_id] = {
            **prior,
            "value": value,
            "unit": unit,
            "method": method,
            "validation_status": "VALIDATED" if value is not None else "UNAVAILABLE",
            "data_gaps": list(prior.get("data_gaps", [])),
        }

    update_metric("far", total_far, "ratio", "editable-building floor-plate GFA / declared design area; retained aggregation not assessed")
    metrics["far"].update(denominator_label="legacy/unspecified:exploration_design_area", denominator_area_m2=site_area)
    update_metric("coverage_ratio", coverage_ratio, "ratio", "union editable ground-floor footprint / declared design area; retained aggregation not assessed")
    max_height = max((float(item["first_floor_height_m"]) + max(0, len(item["floors"]) - 1) * float(item["standard_floor_height_m"]) for item in active.values()), default=None)
    update_metric("height_m", max_height, "m", "maximum editable-building height from stored floor count and declared floor heights")
    total_by_use: dict[str, float] = {}
    for building_id, item in active.items():
        use = str(item.get("use_label", "UNASSIGNED_FIXTURE_USE"))
        total_by_use[use] = total_by_use.get(use, 0.0) + gfa_by_building[building_id]
    for key in [key for key in metrics if key.startswith("use_ratio:")]:
        label = key.partition(":")[2]
        metrics[key]["value"] = total_by_use.get(label, 0.0) / total_gfa if total_gfa else None
        metrics[key]["validation_status"] = "VALIDATED" if total_gfa else "UNAVAILABLE"
    for use, use_gfa in total_by_use.items():
        key = f"use_ratio:{use}"
        if key not in metrics:
            metrics[key] = {"value": use_gfa / total_gfa if total_gfa else None, "unit": "ratio", "method": "editable floor-plate GFA by fixture use / generated fixture GFA", "validation_status": "VALIDATED" if total_gfa else "UNAVAILABLE", "data_gaps": ["synthetic fixture; no designer-approved design area or constraints"]}
    # W6-6 retained-building/zone aggregation is an unresolved dependency.
    # Formal editable-subset metrics cannot masquerade as whole-site results.
    if not geometry_valid or provenance == "FORMAL_DRAFT":
        for metric in metrics.values():
            metric.update(value=None, validation_status="UNAVAILABLE")
    land_gfa = total_gfa
    if provenance == "FORMAL_DRAFT" or not geometry_valid:
        total_gfa = total_far = coverage_m2 = coverage_ratio = None
    land_basis = None
    if provenance == "FORMAL_DRAFT":
        from .editing.formal_authority import FOUNDER_LAND_AREA_M2, land_area_far
        declared = parameters.get("land_area_m2")
        land_ready = geometry_valid and land_gfa is not None and math.isclose(float(declared or 0), FOUNDER_LAND_AREA_M2, rel_tol=0, abs_tol=1e-6)
        land_basis = {
            "denominator_label": "land_area",
            "denominator_area_m2": FOUNDER_LAND_AREA_M2,
            "floor_polygon_gfa_m2": land_gfa if land_ready else None,
            "far": land_area_far(land_gfa) if land_ready else None,
            "validation_status": "FLOOR_POLYGON_LAND_AREA" if land_ready else "UNAVAILABLE",
            "method": "sum of stored floor polygons, holes included, divided by Founder D2 set A land area",
        }
    return {
        "site_metrics_status": "NOT_READY_RETAINED_AGGREGATION" if provenance == "FORMAL_DRAFT" else "FIXTURE_ONLY",
        "geometry_valid": geometry_valid,
        "acceptance_eligible": False,
        "analysis_eligible": False,
        "provenance": parameters.get("provenance", "UNKNOWN"),
        "selected_building": {"building_id": selected_building_id, "floor_count": len(building_data["floors"]), "height_m": height, "gfa_m2": gfa if geometry_valid else None},
        "site": {"gfa_m2": total_gfa, "far": total_far, "coverage_m2": coverage_m2, "coverage_ratio": coverage_ratio, "far_upper_bound": limits.get("far_upper_bound"), "far_remaining": None if limits.get("far_upper_bound") is None or total_far is None else limits["far_upper_bound"] - total_far, "coverage_upper_bound": limits.get("max_coverage_ratio"), "coverage_remaining": None if limits.get("max_coverage_ratio") is None or coverage_ratio is None else limits["max_coverage_ratio"] - coverage_ratio, "height_upper_bound_m": limits.get("max_height_m")},
        "zones": [],
        "zone_metrics_status": "NOT_READY_ZONE_AGGREGATION" if provenance == "FORMAL_DRAFT" else "NOT_ASSESSED_NO_FIXTURE_ZONES",
        "scenario_metrics": metrics,
        "metric_state": "BACKEND_CONFIRMED" if geometry_valid and provenance == "FIXTURE_ONLY" else "NOT_READY",
        "land_basis": land_basis,
    }


def _move_massing_pointer(store: ProjectStateStore, scenario_id: str, request: EditPointerRequest, artifact_root: Path, *, undo: bool, formal_adapter: FormalEditorAdapter | None = None) -> dict[str, Any]:
    try:
        record = store.current(scenario_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="scenario was not found") from exc
    if record.entity_type != "DesignScenario":
        raise HTTPException(status_code=404, detail="scenario was not found")
    binding = _editor_binding(store, record, formal_adapter)
    payload = dict(record.payload)
    parameters = dict(payload.get("parameters", {}))
    if binding is not None:
        parameters["editor_binding"] = asdict(binding)
    global_revisions = list(parameters.get("massing_revision_records", []))
    snapshots = dict(parameters.get("massing_revision_snapshots", {}))
    active = int(parameters.get("active_edit_revision_id", 0))
    if not global_revisions:
        raise HTTPException(status_code=409, detail="scenario has no massing edit history")
    if request.expected_revision != active:
        raise HTTPException(status_code=409, detail=f"expected edit revision {request.expected_revision}, active revision is {active}")
    if undo:
        active_record = next((item for item in global_revisions if int(item["revision_id"]) == active), None)
        if active_record is None:
            raise HTTPException(status_code=409, detail="no massing revision is available to undo")
        target = int(active_record["parent_revision_id"])
    else:
        children = [item for item in global_revisions if int(item["parent_revision_id"]) == active]
        if request.revision_id is None:
            if len(children) != 1:
                raise HTTPException(status_code=409, detail="redo target is missing or ambiguous")
            target = int(children[0]["revision_id"])
        else:
            selected = next((item for item in children if int(item["revision_id"]) == request.revision_id), None)
            if selected is None:
                raise HTTPException(status_code=409, detail="redo target must be a direct child of the active revision")
            target = int(request.revision_id)
    snapshot = snapshots.get(str(target))
    if snapshot is None:
        if target != 0:
            raise HTTPException(status_code=409, detail="massing revision snapshot is unavailable")
        snapshot = {item["building_id"]: item for item in parameters.get("editable_buildings", [])}
    parameters["active_buildings"] = dict(snapshot)
    parameters["active_edit_revision_id"] = target
    histories = dict(parameters.get("edit_histories", {}))
    ancestry: set[int] = set()
    cursor = target
    while cursor > 0:
        ancestry.add(cursor)
        current_record = next((item for item in global_revisions if int(item["revision_id"]) == cursor), None)
        if current_record is None:
            break
        cursor = int(current_record["parent_revision_id"])
    for building_id, state in histories.items():
        matching = [int(item["revision_id"]) for item in state.get("revisions", []) if int(item["revision_id"]) in ancestry]
        state["active_revision_id"] = max(matching, default=0)
        histories[building_id] = state
    parameters["edit_histories"] = histories
    target_record = next((item for item in global_revisions if int(item["revision_id"]) == target), None)
    target_artifact_id = target_record["artifact_id"] if target_record else parameters.get("root_geometry_artifact_id", payload["geometry_artifact_id"])
    if parameters["active_buildings"]:
        dashboard = _dashboard(parameters, next(iter(parameters["active_buildings"])))
        parameters["metrics"] = dashboard["scenario_metrics"]
        parameters["validation"] = {"valid": dashboard["geometry_valid"], "failure_reasons": [] if dashboard["geometry_valid"] else ["INVALID_EDIT_DRAFT"], "acceptance_eligible": False, "analysis_eligible": False}
    if target == 0:
        parameters["validation"] = parameters.get("editor_baseline_validation", parameters.get("validation", {}))
    payload.update({"geometry_artifact_id": target_artifact_id, "parameters": parameters, "status": "draft"})
    artifact = store.current(target_artifact_id)
    payload["geometry_sha256"] = artifact.payload["sha256"]
    updated = _apply_scenario_update(store, record, payload, f"Move massing revision pointer to {target}")
    return {"status": "DRAFT", "active_revision_id": target, "revision_count": len(global_revisions), "scenario_revision": updated.revision}


__all__ = ["FormalEditorBinding", "FormalEditorAdapter", "ResolvedEditorRef", "EditPointerRequest", "MassingEditRequest", "RoadNodeMoveRequest", "register_scenario_edit_routes"]
