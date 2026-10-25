"""Persist formal face edits on an unaccepted FORMAL_DRAFT.

The geometry kernel remains ``editing/faces.py``. That kernel only accepts a
FIXTURE_ONLY stack, so this module lends it a copy and writes the resulting
polygons back as FORMAL_DRAFT. The fixture preview route is not used.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import triangulate

from urban_design.editing.faces import FaceEditError, FaceEditHistory
from urban_design.editing.floors import BuildingMassing
from urban_design.editing.formal_authority import FormalAuthorityError, PersistedFormalEditorAdapter
from urban_design.models import ActorKind, Artifact, RunStatus, ToolExecution
from urban_design.scenario_editing_api import _artifact_file, _replace_building_feature, _building_from_payload, _building_payload
from urban_design.editing.formal_publication import publish_formal_draft_edit

# Founder D2 set A: new massing and additions stay at or below 20 m.
MAX_NEW_HEIGHT_M = 20.0


class FormalFaceError(ValueError):
    """A formal face edit cannot be published."""


class FormalFaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    building_id: str = Field(min_length=1)
    operation: Literal["UNDO", "SETBACK", "SPLIT_LINE", "SPLIT_CONTOUR", "SIDE_PUSH", "TOP_EXTRUDE"]
    face_id: str | None = None
    points: list[tuple[float, float]] = Field(default_factory=list)
    steps: StrictInt = 1
    parent_revision: StrictInt = Field(ge=0)
    expected_scenario_revision: StrictInt = Field(ge=1)
    expected_geometry_hash: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


def stack_height_m(building: BuildingMassing) -> float:
    return float(building.first_floor_height_m) + max(0, len(building.floors) - 1) * float(building.standard_floor_height_m)


def _kernel_copy(building: BuildingMassing) -> BuildingMassing:
    return replace(building, provenance="FIXTURE_ONLY")


def _formal_copy(building: BuildingMassing) -> BuildingMassing:
    return replace(building, provenance="FORMAL_DRAFT")


def _session(parameters: dict[str, Any], building_id: str, current: BuildingMassing) -> dict[str, Any]:
    sessions = dict(parameters.get("face_sessions") or {})
    stored = sessions.get(building_id)
    if isinstance(stored, dict) and isinstance(stored.get("baseline"), dict):
        if _formal_copy(_replay(stored).active.building).geometry_hash() == current.geometry_hash():
            return stored
    return {"baseline": _building_payload(current, str(current.id)), "actions": [], "lineage": []}


def _replay(session: dict[str, Any]) -> FaceEditHistory:
    history = FaceEditHistory(_kernel_copy(_building_from_payload(session["baseline"])))
    for action in session.get("actions") or []:
        _apply_action(history, action)
    return history


def _apply_action(history: FaceEditHistory, action: dict[str, Any]) -> None:
    operation = action["operation"]
    parent = int(action["parent_revision"])
    if operation == "UNDO":
        history.undo()
        return
    if operation == "SETBACK":
        history.setback_upper_two(expected_revision=parent, metres=int(action["steps"]))
        return
    face_id = str(action.get("face_id") or "")
    if ":inner:" in face_id:
        raise FaceEditError("inner ring face editing is unsupported", code="INNER_RING_EDITING_UNSUPPORTED")
    if operation in {"SPLIT_LINE", "SPLIT_CONTOUR"}:
        cutter = LineString(action["points"]) if operation == "SPLIT_LINE" else Polygon(action["points"])
        history.subdivide(face_id, expected_revision=parent, cutter=cutter)
        return
    target = next((face for face in history.active.faces if face.id == face_id), None)
    expected_kind = "SIDE" if operation == "SIDE_PUSH" else "TOP"
    if target is None or target.kind != expected_kind:
        raise FaceEditError("operation does not match semantic face kind")
    history.extrude(face_id, expected_revision=parent, steps=int(action["steps"]), semantic_option="NEW_USABLE_FLOORS_PROTOTYPE")


def _triangles(polygon: Polygon) -> list[list[float]]:
    points: list[list[float]] = []
    for triangle in triangulate(polygon):
        clipped = triangle.intersection(polygon)
        pieces = [clipped] if isinstance(clipped, Polygon) else [item for item in getattr(clipped, "geoms", []) if isinstance(item, Polygon)]
        for piece in pieces:
            if piece.is_empty:
                continue
            for x_coord, y_coord in list(piece.exterior.coords)[:3]:
                points.append([float(x_coord), float(y_coord), 0.0])
    return points


def _view(record: Any, building: BuildingMassing, history: FaceEditHistory, session: dict[str, Any]) -> dict[str, Any]:
    revision = history.active
    lineage = [[parent, list(children)] for parent, children in revision.lineage]
    stored_lineage = []
    session_lineage = session.get("lineage")
    if isinstance(session_lineage, list):
        stored_lineage = session_lineage
    return {
        "provenance": "FORMAL_DRAFT",
        "acceptance_eligible": False,
        "analysis_eligible": False,
        "production_status": "DRAFT",
        "building_id": building.id,
        "scenario_revision": int(record.revision),
        "face_revision": int(revision.revision_id),
        "geometry_hash": building.geometry_hash(),
        "height_m": stack_height_m(building),
        "lineage": [[f"{history.baseline_geometry_hash}|{parent}", [f"{history.baseline_geometry_hash}|{child}" for child in children]] for parent, children in (stored_lineage or lineage)],
        "floors": [
            {"id": floor.id, "level": floor.level, "geometry": mapping(floor.geometry)}
            for floor in sorted(building.floors, key=lambda item: item.level)
        ],
        "inner_ring_faces": [
            {"id": f"{history.baseline_geometry_hash}|r{revision.revision_id}:{floor.id}:inner:{ring_index}:side:{edge_index}",
             "floor_id": floor.id, "ring_index": ring_index, "edge_index": edge_index,
             "coordinates": [list(start), list(end)], "editable": False,
             "reason": "INNER_RING_EDITING_UNSUPPORTED"}
            for floor in sorted(building.floors, key=lambda item: item.level)
            for ring_index, ring in enumerate(floor.geometry.interiors)
            for edge_index, (start, end) in enumerate(zip(ring.coords, list(ring.coords)[1:]))
        ],
        "inner_ring_editing_supported": False,
        "inner_ring_editing_reason": "INNER_RING_EDITING_UNSUPPORTED",
        "faces": [
            {
                "id": f"{history.baseline_geometry_hash}|{face.id}",
                "floor_id": face.floor_id,
                "kind": face.kind,
                "edge_index": face.edge_index,
                "parent_revision": int(revision.revision_id),
                "geometry": mapping(face.geometry),
                "triangles": _triangles(face.geometry),
            }
            for face in revision.faces
        ],
    }


def _current_building(record: Any, building_id: str) -> BuildingMassing:
    parameters = record.payload.get("parameters") or {}
    if parameters.get("provenance") != "FORMAL_DRAFT":
        raise FormalFaceError("formal face editing requires a FORMAL_DRAFT")
    match = next((item for item in parameters.get("editable_buildings") or [] if item.get("building_id") == building_id), None)
    if match is None:
        raise FormalFaceError("selected building is not on this formal draft")
    active = parameters.get("active_buildings") or {}
    building = _building_from_payload(active.get(building_id, match))
    if building.provenance != "FORMAL_DRAFT":
        raise FormalFaceError("formal face editing refuses a fixture building")
    return building


def face_state(store: Any, scenario_id: str, building_id: str) -> dict[str, Any]:
    record = store.current(scenario_id)
    PersistedFormalEditorAdapter().resolve(store, record)
    building = _current_building(record, building_id)
    session = _session(record.payload.get("parameters") or {}, building_id, building)
    history = _replay(session)
    replayed = _formal_copy(history.active.building)
    if replayed.geometry_hash() != building.geometry_hash():
        raise FormalFaceError("face session does not match the current draft geometry")
    viewed = _view(record, building, history, session)
    return viewed


def _fingerprint(request: FormalFaceRequest) -> str:
    payload = request.model_dump()
    payload.pop("idempotency_key")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def apply_formal_face_edit(store: Any, artifact_root: Path, scenario_id: str, request: FormalFaceRequest) -> dict[str, Any]:
    record = store.current(scenario_id)
    binding = PersistedFormalEditorAdapter().resolve(store, record)
    parameters = dict(record.payload.get("parameters") or {})
    parameters["editor_binding"] = asdict(binding)
    idempotency = dict(parameters.get("face_idempotency") or {})
    fingerprint = _fingerprint(request)
    prior = idempotency.get(request.idempotency_key)
    # Same key and same payload stay one edit after the draft revision advances.
    if prior is not None:
        if prior.get("fingerprint") != fingerprint:
            raise FormalFaceError("idempotency key was reused for a different face edit")
        return {**face_state(store, scenario_id, request.building_id), "idempotent_replay": True}
    if int(record.revision) != request.expected_scenario_revision:
        raise FormalFaceError("stale scenario revision")
    building = _current_building(record, request.building_id)
    if building.geometry_hash() != request.expected_geometry_hash:
        raise FormalFaceError("stale geometry hash")
    session = _session(parameters, request.building_id, building)
    history = _replay(session)
    replayed = _formal_copy(history.active.building)
    if replayed.geometry_hash() != building.geometry_hash():
        raise FormalFaceError("face session does not match the current draft geometry")
    face_id = request.face_id
    if face_id is not None and "|" in face_id and face_id.split("|", 1)[0] != history.baseline_geometry_hash:
        raise FormalFaceError("stale semantic face ID; reload current faces")
    if face_id is not None and ":inner:" not in face_id:
        current_ids = {face["id"] for face in _view(record, building, history, session)["faces"]}
        if face_id not in current_ids:
            raise FormalFaceError("stale or unknown semantic face ID; reload current faces")
        face_id = face_id.split("|", 1)[1]
    action = {
        "operation": request.operation,
        "face_id": face_id,
        "points": [list(point) for point in request.points],
        "steps": request.steps,
        "parent_revision": request.parent_revision,
    }
    if request.parent_revision != history.active_revision_id:
        raise FormalFaceError("stale parent revision")
    try:
        _apply_action(history, action)
    except FaceEditError:
        raise
    except (ValueError, TypeError) as exc:
        raise FaceEditError(str(exc)) from exc
    edited = _formal_copy(history.active.building)
    height = stack_height_m(edited)
    if height > MAX_NEW_HEIGHT_M:
        raise FormalFaceError(f"new height {height} m exceeds the 20 m cap")
    lineage = list(session.get("lineage") or [])
    lineage.extend([[parent, list(children)] for parent, children in history.active.lineage])
    use_label = next(
        (item.get("use_label", "UNASSIGNED") for item in parameters.get("editable_buildings") or [] if item.get("building_id") == request.building_id),
        "UNASSIGNED",
    )
    updated_building = _building_payload(edited, str(use_label))
    buildings = [
        updated_building if item.get("building_id") == request.building_id else item
        for item in parameters.get("editable_buildings") or []
    ]
    root = Path(artifact_root)
    staging_dir = root / "face-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    published = root / "face-published"
    published.mkdir(parents=True, exist_ok=True)
    face_revision = int(history.active_revision_id)
    publication_key = hashlib.sha256(f"{scenario_id}:{record.revision}:{request.building_id}:{fingerprint}".encode()).hexdigest()
    staging = staging_dir / f"face-{publication_key}.geojson"
    document, _source_path = _artifact_file(store, record.payload["geometry_artifact_id"])
    document = _replace_building_feature(document, edited)
    raw = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with staging.open("xb") as stream:
        stream.write(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    artifact_id = f"face-{publication_key}"
    target = published / staging.name
    try:
        artifact = Artifact(
            id=artifact_id,
            type="FORMAL_FACE_EDIT",
            uri=str(target),
            sha256=digest,
            mime="application/geo+json",
            crs="EPSG:28992",
            producer="formal-face-edit",
            created_at=datetime.now(timezone.utc),
            project_id=record.project_id,
            size_bytes=staging.stat().st_size,
            parent_artifact_ids=[record.payload["geometry_artifact_id"]],
        )
        sessions = dict(parameters.get("face_sessions") or {})
        sessions[request.building_id] = {"baseline": session["baseline"], "actions": [*(session.get("actions") or []), action], "lineage": lineage}
        idempotency[request.idempotency_key] = {"fingerprint": fingerprint, "face_revision": face_revision}
        parameters.update({
            "editable_buildings": buildings,
            "face_sessions": sessions,
            "face_idempotency": idempotency,
            "face_lineage": lineage,
            "acceptance_eligible": False,
            "analysis_eligible": False,
        })
        active = dict(parameters.get("active_buildings") or {})
        if request.building_id in active:
            active[request.building_id] = updated_building
            parameters["active_buildings"] = active
        payload = dict(record.payload)
        payload.update(parameters=parameters, geometry_artifact_id=artifact_id, geometry_sha256=digest)
        execution = ToolExecution(
            id=f"tool-execution-face-{publication_key}",
            project_id=record.project_id,
            scenario_id=scenario_id,
            tool="formal-face-editor",
            tool_version="w6-formal-faces-v1",
            parameters=action,
            output_artifact_refs=[artifact_id],
            output_artifact_hashes=[digest],
            status=RunStatus.SUCCEEDED,
            idempotency_key=request.idempotency_key,
            limitations=["FORMAL_DRAFT; not eligible for acceptance or analysis"],
        )
        def verify_file() -> None:
            if staging.read_bytes() != raw:
                raise FormalFaceError("staging geometry bytes changed before publication")
            with target.open("xb") as stream:
                stream.write(raw)
            if target.read_bytes() != raw:
                raise FormalFaceError("published geometry bytes do not match staging")
        updated = publish_formal_draft_edit(store, record, payload, artifact=artifact,
            execution=execution, reason=f"Formal face {request.operation} revision {face_revision}",
            verify_file=verify_file)
    except (FormalFaceError, FaceEditError):
        raise
    except Exception as exc:
        raise FormalFaceError(f"face publication failed; staging retained at {staging.name}") from exc
    viewed = face_state(store, scenario_id, request.building_id)
    viewed["scenario_revision"] = int(updated.revision)
    viewed["idempotent_replay"] = False
    viewed["artifact_id"] = artifact_id
    return viewed


def register_formal_face_routes(router: APIRouter, store: Any, artifact_root: Path) -> None:
    @router.get("/api/v1/scenarios/{scenario_id}/editing/faces")
    def list_formal_faces(scenario_id: str, building_id: str) -> dict[str, Any]:
        try:
            return face_state(store, scenario_id, building_id)
        except FaceEditError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
        except FormalAuthorityError as exc:
            raise HTTPException(status_code=409, detail=f"BLOCKED: {exc}") from exc
        except FormalFaceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/api/v1/scenarios/{scenario_id}/editing/faces")
    def edit_formal_faces(scenario_id: str, request: FormalFaceRequest) -> dict[str, Any]:
        try:
            return apply_formal_face_edit(store, artifact_root, scenario_id, request)
        except FaceEditError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
        except FormalAuthorityError as exc:
            raise HTTPException(status_code=409, detail=f"BLOCKED: {exc}") from exc
        except FormalFaceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=422, detail=str(exc)) from exc
