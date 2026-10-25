"""Resolve an accepted formal scenario into an editor draft.

The resolver reads persisted authority only. Client approval flags, stage
selection, and a well-formed identifier are not acceptance evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, mapping, shape

from urban_design.constraint_sets import constraint_set_payload_digest
from urban_design.editing.floors import BuildingMassing, FloorStorey
from urban_design.editing.roads import RoadEdge, RoadGraph, RoadNode
from urban_design.models import ActorKind, Scenario, ScenarioStatus
from urban_design.scenario_editing_api import (
    FormalEditorBinding,
    ResolvedEditorRef,
    _building_payload,
    _graph_payload,
    _hash_json,
)
from urban_design.store import EntityNotFoundError, ProjectStateStore

# Founder D2 set A, 2026-10-04. FAR uses this land area, not a building box.
FOUNDER_LAND_AREA_M2 = 183591.328
_ACCEPTED_ACTIONS = {"Accept", "Approve"}
_REJECTED_ACTIONS = {"Reject"}
_ACTIVE_CONSTRAINT = {"effective", "active", "approved", "accepted"}
_BLOCKED_PROVENANCE = {"FIXTURE_ONLY", "UNAPPROVED_PREVIEW", "ASSUMED", "ASSUMED_FROM_PORTFOLIO"}


class FormalAuthorityError(ValueError):
    """A formal editor request cannot be bound to persisted authority."""


def payload_sha256(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def resolved_payload_ref(record: Any) -> ResolvedEditorRef:
    return ResolvedEditorRef(record.entity_id, int(record.revision), payload_sha256(record.payload))


def floor_polygon_gfa_m2(buildings: list[dict[str, Any]]) -> float:
    """Sum stored floor polygons, including holes. A bounding box is not GFA."""

    total = 0.0
    for building in buildings:
        for floor in building.get("floors") or []:
            geometry = floor.get("geometry") if isinstance(floor, dict) else None
            if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                raise FormalAuthorityError("floor is missing its polygon; bounding-box area is not GFA")
            polygon = shape(geometry)
            if polygon.is_empty or not polygon.is_valid:
                raise FormalAuthorityError("floor polygon is empty or invalid")
            total += float(polygon.area)
    if total <= 0 or not math.isfinite(total):
        raise FormalAuthorityError("formal floor polygons have no positive GFA")
    return total


def land_area_far(gfa_m2: float, land_area_m2: float = FOUNDER_LAND_AREA_M2) -> float:
    if not math.isfinite(gfa_m2) or gfa_m2 < 0:
        raise FormalAuthorityError("GFA must be a finite non-negative area")
    if not math.isclose(float(land_area_m2), FOUNDER_LAND_AREA_M2, rel_tol=0, abs_tol=1e-6):
        raise FormalAuthorityError("FAR land denominator is not Founder D2 set A 183591.328 m2")
    return float(gfa_m2) / FOUNDER_LAND_AREA_M2


def _digest_matches(stored: str | None, *candidates: str) -> bool:
    if not isinstance(stored, str) or not stored.strip():
        return False
    accepted = set(candidates)
    accepted.update(item.removeprefix("sha256:") for item in candidates)
    accepted.update(f"sha256:{item}" for item in candidates if not item.startswith("sha256:"))
    return stored in accepted


def _artifact_bytes(store: ProjectStateStore, artifact_id: str) -> tuple[Any, bytes, str]:
    try:
        record = store.current(artifact_id)
    except EntityNotFoundError as exc:
        raise FormalAuthorityError(f"unknown source artifact {artifact_id}") from exc
    uri = record.payload.get("uri")
    if not isinstance(uri, str) or not uri:
        raise FormalAuthorityError(f"source artifact {artifact_id} has no file")
    try:
        content = Path(uri).read_bytes()
    except OSError as exc:
        raise FormalAuthorityError(f"source artifact {artifact_id} bytes are unavailable") from exc
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    recorded = record.payload.get("sha256")
    if recorded != digest:
        raise FormalAuthorityError(f"source artifact {artifact_id} bytes do not match its recorded hash")
    return record, content, digest


def _events(store: ProjectStateStore, project_id: str) -> set[str]:
    return {event.event_id for event in store.events(project_id=project_id)}


def _human_decisions(store: ProjectStateStore, project_id: str, target_id: str) -> list[Any]:
    from urban_design.decision_resolution import resolve_record_decision
    target = store.current(target_id)
    if target.project_id != project_id:
        raise FormalAuthorityError("decision target project mismatch")
    digest = target.payload.get("geometry_sha256")
    if target.entity_type == "WorkspaceRevision":
        from urban_design.geometry import canonical_geometry_hash
        try:
            digest = canonical_geometry_hash(target.payload["spatial_brief"]["exploration_design_area"]["geometry"])
        except (ValueError, TypeError, KeyError) as exc:
            raise FormalAuthorityError("decision target geometry is invalid") from exc
    resolution = resolve_record_decision(store, target, digest, "target_geometry_sha256")
    return [resolution.decision] if resolution.status == "EFFECTIVE" else []


def _require_human_event(store: ProjectStateStore, decision: Any, project_id: str) -> None:
    if decision.payload.get("actor_kind") != ActorKind.HUMAN_UI.value:
        raise FormalAuthorityError("baseline decision actor_kind is not HUMAN_UI")
    event_id = decision.payload.get("decision_event_id")
    if not isinstance(event_id, str) or event_id not in _events(store, project_id):
        raise FormalAuthorityError("missing approval event for the baseline HumanDecision")


def _load_stages(store: ProjectStateStore, parameters: dict[str, Any], geometry_uri: str) -> dict[str, Any]:
    if parameters.get("provenance") == "FABRIC_PLAN_E2_ONLY":
        from urban_design.editing.fabric_plan_stages import fabric_plan_stages
        return fabric_plan_stages(parameters)
    stages = parameters.get("stages")
    if isinstance(stages, dict):
        return stages
    artifact_id = parameters.get("stages_artifact_id")
    if isinstance(artifact_id, str) and artifact_id:
        _record, content, _digest = _artifact_bytes(store, artifact_id)
        document = json.loads(content)
        if not isinstance(document, dict):
            raise FormalAuthorityError("stages artifact is not a JSON object")
        return document
    sibling = Path(geometry_uri).with_name(Path(geometry_uri).name.replace(".geojson", ".stages.json"))
    if sibling.is_file():
        document = json.loads(sibling.read_text(encoding="utf-8"))
        if isinstance(document, dict):
            return document
    raise FormalAuthorityError("formal stages with per-floor polygons were not found")


def _buildings_from_stages(stages: dict[str, Any]) -> list[dict[str, Any]]:
    buildings = ((stages.get("massing") or {}).get("buildings") or [])
    if not isinstance(buildings, list) or not buildings:
        raise FormalAuthorityError("formal stages have no buildings")
    materialized: list[dict[str, Any]] = []
    for building in buildings:
        floors_in = building.get("floors") or []
        if not isinstance(floors_in, list) or not floors_in:
            raise FormalAuthorityError(f"building {building.get('id')} has no stored floors")
        storeys: list[FloorStorey] = []
        heights: list[float] = []
        for floor in floors_in:
            geometry = floor.get("geometry")
            if not isinstance(geometry, dict):
                raise FormalAuthorityError("refusing to invent a floor polygon from a bounding box or floor count")
            polygon = shape(geometry)
            if polygon.geom_type not in {"Polygon", "MultiPolygon"} or polygon.is_empty or not polygon.is_valid:
                raise FormalAuthorityError("stored floor geometry is not a valid polygon")
            height = floor.get("floor_height_m")
            if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(float(height)) or float(height) <= 0:
                raise FormalAuthorityError("stored floor_height_m is missing; refusing to re-estimate storey height")
            level = floor.get("level")
            if isinstance(level, bool) or not isinstance(level, int):
                raise FormalAuthorityError("stored floor level is missing")
            floor_id = floor.get("id") or f"{building.get('id')}-floor-{level}"
            storeys.append(FloorStorey(str(floor_id), level, polygon))
            heights.append(float(height))
        if any(not math.isclose(height, heights[-1], rel_tol=0, abs_tol=1e-9) for height in heights[1:]):
            raise FormalAuthorityError("upper floors do not share one stored height")
        editor_building = BuildingMassing(
            id=str(building.get("id")),
            floors=tuple(storeys),
            first_floor_height_m=heights[0],
            standard_floor_height_m=heights[-1],
            provenance="FORMAL_DRAFT",
        )
        materialized.append(_building_payload(editor_building, str(building.get("use") or "UNASSIGNED")))
    floor_polygon_gfa_m2(materialized)
    return materialized


def _roads_from_stages(stages: dict[str, Any]) -> dict[str, Any]:
    edges_in = ((stages.get("skeleton") or {}).get("edges") or [])
    if not isinstance(edges_in, list) or not edges_in:
        raise FormalAuthorityError("formal stages have no road edges")
    nodes: dict[str, tuple[float, float, int]] = {}
    edges: list[RoadEdge] = []
    for edge in edges_in:
        geometry = edge.get("geometry")
        if not isinstance(geometry, dict):
            raise FormalAuthorityError("road edge is missing its LineString")
        line = shape(geometry)
        if not isinstance(line, LineString) or line.is_empty:
            raise FormalAuthorityError("road edge geometry must be a LineString")
        coordinates = [(float(point[0]), float(point[1])) for point in line.coords]
        if len(coordinates) < 2:
            raise FormalAuthorityError("road edge has fewer than two coordinates")
        edge_id = str(edge.get("id") or "")
        if not edge_id:
            raise FormalAuthorityError("road edge id is missing")
        start = str(edge.get("from_node_id") or f"{edge_id}-start")
        end = str(edge.get("to_node_id") or f"{edge_id}-end")
        level = edge.get("level", 0)
        if isinstance(level, bool) or not isinstance(level, int):
            raise FormalAuthorityError("road edge level must be an integer")
        vertex_ids = [start, *[f"{edge_id}:v{index}" for index in range(1, len(coordinates) - 1)], end]
        for vertex_id, point in zip(vertex_ids, coordinates, strict=True):
            existing = nodes.get(vertex_id)
            recorded = (point[0], point[1], level)
            if existing is not None and existing != recorded:
                raise FormalAuthorityError(f"road node {vertex_id} has conflicting coordinates")
            nodes.setdefault(vertex_id, recorded)
        if len(vertex_ids) == 2:
            edges.append(RoadEdge(edge_id=edge_id, start_node_id=start, end_node_id=end, layer=level, locked=edge.get("locked", False), lineage_ids=tuple(edge.get("lineage_ids") or (edge_id,))))
        else:
            for index in range(len(vertex_ids) - 1):
                segment_id = f"{edge_id}:{index}"
                edges.append(RoadEdge(
                    edge_id=segment_id,
                    start_node_id=vertex_ids[index],
                    end_node_id=vertex_ids[index + 1],
                    layer=level,
                    locked=edge.get("locked", False),
                    lineage_ids=(edge_id, segment_id),
                ))
    graph = RoadGraph(
        nodes=tuple(RoadNode(node_id=key, x_m=value[0], y_m=value[1], layer=value[2], lineage_ids=(key,)) for key, value in sorted(nodes.items())),
        edges=tuple(edges),
    )
    return _graph_payload(graph)


def _constraint_value(constraint_set: Any, name: str) -> float:
    for item in constraint_set.payload.get("constraints") or []:
        if item.get("name") == name and item.get("scope") == "whole_site":
            return float(item["value"])
    raise FormalAuthorityError(f"active constraint set is missing {name}")


def _bind_constraint(store: ProjectStateStore, ancestor: Any) -> tuple[Any, str]:
    constraint_id = ancestor.payload.get("constraint_set_id")
    if not isinstance(constraint_id, str) or not constraint_id:
        raise FormalAuthorityError("scenario has no constraint set")
    try:
        current = store.current(constraint_id)
    except EntityNotFoundError as exc:
        raise FormalAuthorityError(f"unknown constraint set {constraint_id}") from exc
    if current.project_id != ancestor.project_id or current.entity_type != "ConstraintSet":
        raise FormalAuthorityError("constraint set does not belong to this scenario")
    status = str(current.payload.get("status") or "").lower()
    if status in {"superseded", "invalid", "stale"}:
        raise FormalAuthorityError(f"constraint set {constraint_id} is {status}")
    if status not in _ACTIVE_CONSTRAINT:
        raise FormalAuthorityError(f"constraint set {constraint_id} is not an active D2 set ({status or 'missing'})")
    far = next((item for item in current.payload.get("constraints") or [] if item.get("name") == "far_upper_limit" and item.get("scope") == "whole_site"), None)
    if far is None or far.get("denominator") != "land_area":
        raise FormalAuthorityError("D2 FAR denominator is not land_area")
    definition = constraint_set_payload_digest(current.payload)
    stored = (ancestor.payload.get("parameters") or {}).get("constraint_set_digest")
    current_full = payload_sha256(current.payload)
    if _digest_matches(stored, definition, current_full):
        return current, definition
    for past in store.history(constraint_id):
        past_full = payload_sha256(past.payload)
        if _digest_matches(stored, past_full) and constraint_set_payload_digest(past.payload) == definition:
            return current, definition
    if stored is None and _fabric_inputs_still_bound(store, ancestor, constraint_id):
        return current, definition
    raise FormalAuthorityError("constraint set definition changed after the scenario was bound")


def _fabric_inputs_still_bound(store: ProjectStateStore, ancestor: Any, constraint_id: str) -> bool:
    """Fabric-plan registrations bind the approved-input hash, whose manifest already
    contains the constraint-set digest; an unchanged hash proves the same binding."""
    parameters = ancestor.payload.get("parameters") or {}
    stored_hash = parameters.get("approved_input_hash")
    if parameters.get("provenance") != "FABRIC_PLAN_E2_ONLY" or not isinstance(stored_hash, str):
        return False
    from urban_design.approved_generation import ApprovedGenerationBlocked, _load_approved_inputs
    try:
        inputs = _load_approved_inputs(store, ancestor.project_id, site_generation=True)
    except ApprovedGenerationBlocked:
        return False
    return inputs.constraint_set.id == constraint_id and inputs.input_hash == stored_hash


def _bind_study_area(store: ProjectStateStore, ancestor: Any) -> Any:
    site_id = ancestor.payload.get("site_id")
    try:
        study = store.current(site_id)
    except (EntityNotFoundError, TypeError) as exc:
        raise FormalAuthorityError("active StudyArea is missing") from exc
    if study.entity_type != "StudyArea" or study.project_id != ancestor.project_id:
        raise FormalAuthorityError("StudyArea does not belong to this scenario")
    if study.payload.get("status") != "CONFIRMED_FOR_EXPLORATION":
        raise FormalAuthorityError("D1 StudyArea is not confirmed for exploration")
    decisions = _human_decisions(store, ancestor.project_id, study.entity_id)
    latest = decisions[0] if decisions else None
    direct_match = (
        latest is not None
        and latest.payload.get("target_type") == "StudyArea"
        and latest.payload.get("action") in _ACCEPTED_ACTIONS
        and str(latest.payload.get("status") or "").lower() in {"accepted", "approved"}
        and latest.payload.get("target_geometry_sha256") == study.payload.get("geometry_sha256")
        and str(latest.payload.get("target_version")) == str(study.payload.get("version"))
    )
    workspaces = store.list_current("WorkspaceRevision", project_id=ancestor.project_id)
    workspace_match = None
    if workspaces:
        from urban_design.decision_resolution import latest_accepted_workspace
        try:
            workspace, workspace_match = latest_accepted_workspace(store, ancestor.project_id)
        except (ValueError, KeyError, TypeError) as exc:
            raise FormalAuthorityError(str(exc)) from exc
        if workspace.payload.get("study_area_id") != study.entity_id:
            raise FormalAuthorityError("D1 workspace does not bind the active StudyArea")
    if not direct_match and workspace_match is None:
        raise FormalAuthorityError("D1 study-area acceptance is missing or does not match the active StudyArea")
    if direct_match:
        _require_human_event(store, latest, ancestor.project_id)
    artifact_id = study.payload.get("geometry_artifact_id")
    _record, _content, digest = _artifact_bytes(store, artifact_id)
    expected = study.payload.get("artifact_sha256") or study.payload.get("geometry_sha256")
    if expected != digest:
        raise FormalAuthorityError("StudyArea geometry bytes do not match the confirmed hash")
    return study


def _ancestor(store: ProjectStateStore, record: Any) -> Any:
    current = record
    seen: set[str] = set()
    while True:
        if current.entity_id in seen:
            raise FormalAuthorityError("scenario lineage contains a cycle")
        seen.add(current.entity_id)
        if current.entity_type != "DesignScenario" or current.project_id != record.project_id:
            raise FormalAuthorityError("scenario lineage leaves the DesignScenario project")
        parent_id = current.payload.get("parent_scenario_id")
        if not parent_id:
            return current
        try:
            parent = store.current(parent_id)
        except EntityNotFoundError as exc:
            raise FormalAuthorityError(f"missing parent scenario {parent_id}") from exc
        current = parent


def _accepted_decision(store: ProjectStateStore, ancestor: Any) -> Any:
    parameters = ancestor.payload.get("parameters") or {}
    provenance = parameters.get("provenance")
    generator = str(ancestor.payload.get("generator") or "")
    if provenance in _BLOCKED_PROVENANCE or "fixture" in generator.casefold():
        raise FormalAuthorityError("fixture or preview input cannot enter formal editing")
    if not generator.startswith("formal-dictionary") and provenance != "APPROVED_INPUTS":
        raise FormalAuthorityError("scenario is not a formal-dictionary candidate")
    status = str(ancestor.payload.get("status") or "").lower()
    from urban_design.decision_resolution import resolve_record_decision
    resolution = resolve_record_decision(store, ancestor, ancestor.payload.get("geometry_sha256"), "target_geometry_sha256")
    if resolution.reason == "MISSING_APPROVAL_EVENT":
        raise FormalAuthorityError("missing approval event for the baseline HumanDecision")
    if status == "rejected" or resolution.reason == "Reject":
        raise FormalAuthorityError("REJECTED: scenario was rejected")
    if status == "accepted" and resolution.reason == "NO_COMPATIBLE_DECISION":
        raise FormalAuthorityError("PROPOSED: baseline decision revision is stale")
    if status != "accepted" or resolution.status != "EFFECTIVE" or resolution.reason != "Accept":
        raise FormalAuthorityError("PROPOSED: scenario has no bound HUMAN_UI Accept decision: " + resolution.reason)
    latest = resolution.decision
    declared = parameters.get("metrics", {}).get("far_denominator_m2") if isinstance(parameters.get("metrics"), dict) else None
    if declared is not None and not math.isclose(float(declared), FOUNDER_LAND_AREA_M2, rel_tol=0, abs_tol=1e-3):
        raise FormalAuthorityError("FAR land denominator is not Founder D2 set A 183591.328 m2")
    label = parameters.get("metrics", {}).get("far_denominator") if isinstance(parameters.get("metrics"), dict) else None
    if label not in {None, "land_area"}:
        raise FormalAuthorityError("scenario FAR basis is not land_area")
    artifact, _content, digest = _artifact_bytes(store, ancestor.payload.get("geometry_artifact_id"))
    if ancestor.payload.get("geometry_sha256") != digest or artifact.payload.get("sha256") != digest:
        raise FormalAuthorityError("accepted scenario geometry hash does not match artifact bytes")
    for snapshot_id in parameters.get("source_snapshot_ids") or []:
        try:
            snapshot = store.current(snapshot_id)
        except EntityNotFoundError as exc:
            raise FormalAuthorityError(f"unknown source snapshot {snapshot_id}") from exc
        if snapshot.project_id != ancestor.project_id:
            raise FormalAuthorityError(f"source snapshot {snapshot_id} is outside the project")
    return latest


class PersistedFormalEditorAdapter:
    """Live FormalEditorAdapter. Returns the existing binding type and nothing else."""

    def resolve(self, store: ProjectStateStore, record: Any) -> FormalEditorBinding:
        parameters = record.payload.get("parameters") or {}
        if parameters.get("provenance") != "FORMAL_DRAFT":
            raise FormalAuthorityError("formal editing requires a FORMAL_DRAFT fork of an accepted scenario")
        if str(record.payload.get("status") or "").lower() == "accepted":
            raise FormalAuthorityError("formal draft must not inherit baseline acceptance")
        ancestor = _ancestor(store, record)
        if record.payload.get("parent_scenario_id") != ancestor.entity_id:
            raise FormalAuthorityError("formal draft parent does not resolve to the accepted scenario")
        decision = _accepted_decision(store, ancestor)
        if parameters.get("baseline_decision_id") != decision.entity_id:
            raise FormalAuthorityError("formal draft is not bound to the accepted HumanDecision")
        if parameters.get("parent_geometry_sha256") != ancestor.payload.get("geometry_sha256"):
            raise FormalAuthorityError("formal draft parent geometry hash is stale")
        constraint, definition = _bind_constraint(store, ancestor)
        study = _bind_study_area(store, ancestor)
        artifact, _content, digest = _artifact_bytes(store, record.payload.get("geometry_artifact_id"))
        if record.payload.get("geometry_sha256") != digest:
            raise FormalAuthorityError("draft geometry hash does not match artifact bytes")
        source_refs = [resolved_payload_ref(artifact), resolved_payload_ref(study)]
        if store.list_current("WorkspaceRevision", project_id=ancestor.project_id):
            from urban_design.decision_resolution import latest_accepted_workspace
            workspace, _ = latest_accepted_workspace(store, ancestor.project_id)
            source_refs.append(resolved_payload_ref(workspace))
        for snapshot_id in (ancestor.payload.get("parameters") or {}).get("source_snapshot_ids") or []:
            source_refs.append(resolved_payload_ref(store.current(snapshot_id)))
        return FormalEditorBinding(
            scenario_id=record.entity_id,
            scenario_revision=int(record.revision),
            geometry_sha256=digest,
            editor_inputs_sha256="sha256:" + _hash_json(parameters),
            baseline_status="ACCEPTED",
            baseline_decision_ref=resolved_payload_ref(decision),
            constraint_refs=(ResolvedEditorRef(constraint.entity_id, int(constraint.revision), definition if definition.startswith("sha256:") else f"sha256:{definition}"),),
            source_refs=tuple(source_refs),
        )


def _existing_draft(store: ProjectStateStore, ancestor_id: str, decision_id: str) -> Any | None:
    matches = []
    for row in store.list_current("DesignScenario"):
        parameters = row.payload.get("parameters") or {}
        if row.payload.get("parent_scenario_id") == ancestor_id and parameters.get("provenance") == "FORMAL_DRAFT" and parameters.get("baseline_decision_id") == decision_id:
            matches.append(row)
    if len(matches) > 1:
        raise FormalAuthorityError("more than one formal draft is bound to this accepted scenario")
    return matches[0] if matches else None


def open_formal_draft(store: ProjectStateStore, scenario_id: str) -> tuple[Any, bool]:
    """Create one FORMAL_DRAFT fork of an accepted scenario, or return the existing fork."""

    try:
        record = store.current(scenario_id)
    except EntityNotFoundError as exc:
        raise FormalAuthorityError("scenario was not found") from exc
    if record.entity_type != "DesignScenario":
        raise FormalAuthorityError("scenario was not found")
    adapter = PersistedFormalEditorAdapter()
    if (record.payload.get("parameters") or {}).get("provenance") == "FORMAL_DRAFT":
        adapter.resolve(store, record)
        return record, False
    ancestor = _ancestor(store, record)
    if ancestor.entity_id != record.entity_id:
        raise FormalAuthorityError("open the accepted scenario or its formal draft")
    decision = _accepted_decision(store, ancestor)
    constraint, definition = _bind_constraint(store, ancestor)
    study = _bind_study_area(store, ancestor)
    existing = _existing_draft(store, ancestor.entity_id, decision.entity_id)
    if existing is not None:
        adapter.resolve(store, existing)
        return existing, False
    geometry_artifact, geometry_bytes, geometry_digest = _artifact_bytes(store, ancestor.payload.get("geometry_artifact_id"))
    stages = _load_stages(store, ancestor.payload.get("parameters") or {}, geometry_artifact.payload["uri"])
    buildings = _buildings_from_stages(stages)
    roads = _roads_from_stages(stages)
    study_artifact, study_bytes, _study_digest = _artifact_bytes(store, study.payload.get("geometry_artifact_id"))
    study_document = json.loads(study_bytes)
    study_geometry = study_document.get("geometry") if study_document.get("type") == "Feature" else study_document
    if study_document.get("type") == "FeatureCollection":
        study_geometry = next(feature["geometry"] for feature in study_document["features"])
    area = shape(study_geometry)
    parameters = dict(ancestor.payload.get("parameters") or {})
    if store.list_current("WorkspaceRevision", project_id=ancestor.project_id):
        from urban_design.decision_resolution import latest_accepted_workspace
        workspace, _ = latest_accepted_workspace(store, ancestor.project_id)
        parameters["workspace_revision_binding"] = {"id": workspace.entity_id, "revision": workspace.revision, "payload_digest": workspace.payload["payload_digest"]}
    parameters.update({
        "provenance": "FORMAL_DRAFT",
        "strategy_label": parameters.get("strategy_label") or parameters.get("recipe_id") or ancestor.payload.get("morphology_family"),
        "editable_buildings": buildings,
        "road_graph": roads,
        "road_snap_tolerance_m": 1.0,
        "road_edit_policy_version": "formal-road-graph-v1",
        "design_area_geometry": mapping(area),
        "design_area_m2": float(area.area),
        "land_area_m2": FOUNDER_LAND_AREA_M2,
        "limits": {
            "far_upper_bound": _constraint_value(constraint, "far_upper_limit"),
            "max_height_m": _constraint_value(constraint, "height_upper_limit"),
            "max_coverage_ratio": _constraint_value(constraint, "coverage_upper_limit"),
        },
        "parent_scenario_id": ancestor.entity_id,
        "parent_revision": ancestor.revision,
        "parent_geometry_sha256": geometry_digest,
        "baseline_decision_id": decision.entity_id,
        "constraint_set_digest": definition,
        "validation": {"valid": True, "failure_reasons": [], "acceptance_eligible": False, "analysis_eligible": False},
        "acceptance_eligible": False,
        "analysis_eligible": False,
    })
    if stages.get("derivation") == "FABRIC_PLAN_PRISM_V1":
        parameters["stages"] = stages
    parameters.pop("baseline", None)
    draft_id = f"formal-draft-{ancestor.entity_id}"
    try:
        store.current(draft_id)
    except EntityNotFoundError:
        pass
    else:
        # A reconsidered/reselected baseline cannot overwrite its previous draft.
        draft_id += f"-{decision.entity_id}"

    scenario = Scenario(
        id=draft_id,
        project_id=ancestor.project_id,
        site_id=ancestor.payload["site_id"],
        site_version=str(ancestor.payload.get("site_version") or study.payload.get("version") or "v1"),
        parent_scenario_id=ancestor.entity_id,
        morphology_family=ancestor.payload.get("morphology_family"),
        geometry_artifact_id=geometry_artifact.entity_id,
        geometry_sha256=geometry_digest,
        generator=str(ancestor.payload.get("generator")),
        generator_version=str(ancestor.payload.get("generator_version") or ancestor.payload.get("generator")),
        seed=ancestor.payload.get("seed"),
        parameters=parameters,
        constraint_set_id=constraint.entity_id,
        status=ScenarioStatus.DRAFT,
    )
    from urban_design.analysis_lineage import with_analysis_statuses
    from types import SimpleNamespace
    target = SimpleNamespace(entity_id=draft_id, project_id=ancestor.project_id)
    scenario = Scenario.model_validate(with_analysis_statuses(store, target, scenario.model_dump(mode="json"), 1))
    store.create_typed(
        scenario,
        actor="scenario-editor",
        actor_kind=ActorKind.AGENT_AUTOMATION,
        reason="Fork accepted formal scenario into an unaccepted FORMAL_DRAFT",
    )
    # geometry_bytes is read so a truncated artifact cannot be forked; the draft keeps the parent artifact id.
    if hashlib.sha256(geometry_bytes).hexdigest() != geometry_digest.removeprefix("sha256:"):
        raise FormalAuthorityError("accepted geometry changed while the draft was opened")
    if study_artifact.entity_id != study.payload.get("geometry_artifact_id"):
        raise FormalAuthorityError("StudyArea artifact identity changed while the draft was opened")
    created = store.current(draft_id)
    adapter.resolve(store, created)
    return created, True
