"""Fixture-only scenario persistence and comparison routes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, StrictStr, field_validator
from shapely.geometry import LineString, box, mapping
from shapely.ops import unary_union

from .editing.roads import RoadEdge, RoadGraph, RoadNode
from .models import Artifact, ActorKind, RunStatus, Scenario, ScenarioStatus, ToolExecution
from .morphology.contracts import FixtureGenerationInput
from .morphology.strategies import generate_fixture_strategies
from .scenario_comparison import build_scenario_comparison
from .store import EntityExistsError, EntityNotFoundError, ProjectStateStore


class FixtureScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: StrictStr = "synthetic-rectangle-v1"
    width_m: FiniteFloat = Field(default=100, gt=0)
    height_m: FiniteFloat = Field(default=80, gt=0)
    origin_x_m: FiniteFloat = 90_000
    origin_y_m: FiniteFloat = 436_000
    seed: StrictInt = 1
    road_width_m: FiniteFloat = Field(default=6, gt=0)
    first_floor_height_m: FiniteFloat = Field(default=3, gt=0)
    standard_floor_height_m: FiniteFloat = Field(default=3, gt=0)
    strategy_floor_count: StrictInt = Field(default=4, ge=1)
    max_footprint_width_m: FiniteFloat = Field(default=24, gt=0)
    max_footprint_depth_m: FiniteFloat = Field(default=20, gt=0)
    far_upper_bound: FiniteFloat | None = Field(default=None, ge=0)
    max_height_m: FiniteFloat | None = Field(default=None, gt=0)
    max_coverage_ratio: FiniteFloat | None = Field(default=None, ge=0, le=1)
    min_parcel_area_m2: FiniteFloat = Field(default=100, ge=0)
    min_parcel_width_m: FiniteFloat = Field(default=4, ge=0)

    @field_validator("fixture_id")
    @classmethod
    def valid_fixture_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
            raise ValueError("fixture_id must be a bounded identifier")
        return value


class ScenarioComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_ids: list[StrictStr] = Field(..., min_length=2)


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise HTTPException(status_code=409, detail="immutable scenario artifact path already contains different bytes")
        return
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise HTTPException(status_code=409, detail="immutable scenario artifact was concurrently replaced")


def _metric_value(value: Any, *, unit: str, method: str, valid: bool, gaps: list[str]) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("status") == "AVAILABLE":
        return {
            "value": value.get("value"),
            "unit": unit,
            "method": method,
            "validation_status": "VALIDATED" if valid else "INVALID",
            "data_gaps": gaps,
        }
    if isinstance(value, dict) and value.get("status") == "ESTIMATE_RANGE":
        return {
            "range": value.get("range"),
            "unit": unit,
            "method": method,
            "validation_status": "ESTIMATE",
            "data_gaps": gaps,
        }
    return {
        "unit": unit,
        "method": method,
        "validation_status": "UNAVAILABLE",
        "data_gaps": [*gaps, str(value.get("reason", "metric is unavailable")) if isinstance(value, dict) else "metric is unavailable"],
    }


def _candidate_metrics(candidate: Any, area: Any) -> dict[str, dict[str, Any]]:
    report = candidate.diff_report
    gaps = [
        "synthetic fixture; no designer-approved design area or constraints",
        "no compatible Syntax result is available for this fixture",
    ]
    road_union_area = float(unary_union(candidate.road_surfaces).area) if candidate.road_surfaces else 0.0
    total_gfa = sum(float(building.footprint.area) * building.floor_count for building in candidate.buildings)
    use_area: dict[str, float] = {}
    for building in candidate.buildings:
        use_area[building.use_label] = use_area.get(building.use_label, 0.0) + float(building.footprint.area) * building.floor_count
    metrics = {
        "far": _metric_value(report["far"], unit="ratio", method="GFA / synthetic fixture area", valid=candidate.valid, gaps=gaps),
        "coverage_ratio": _metric_value(report["coverage_ratio"], unit="ratio", method="union building footprint / synthetic fixture area", valid=candidate.valid, gaps=gaps),
        "height_m": _metric_value(report["height"], unit="m", method="first-floor height + upper-floor count × standard-floor height", valid=candidate.valid, gaps=gaps),
        "road_ratio": {"value": road_union_area / float(area.area), "unit": "ratio", "method": "union road-surface area / synthetic fixture area", "validation_status": "VALIDATED" if candidate.valid else "INVALID", "data_gaps": gaps},
        "open_space_ratio": {"value": float(candidate.open_space.area / area.area), "unit": "ratio", "method": "open-space area / synthetic fixture area", "validation_status": "VALIDATED" if candidate.valid else "INVALID", "data_gaps": gaps},
    }
    for use_label, area_m2 in use_area.items():
        ratio = area_m2 / total_gfa if total_gfa else None
        metrics[f"use_ratio:{use_label}"] = {
            "value": ratio,
            "unit": "ratio",
            "method": "floor-plate GFA by fixture use / generated fixture GFA",
            "validation_status": "VALIDATED" if candidate.valid else "INVALID",
            "data_gaps": gaps,
        }
    return metrics


def _geojson(candidate: Any) -> dict[str, Any]:
    features: list[dict[str, Any]] = []

    def add(feature_id: str, kind: str, geometry: Any, **properties: Any) -> None:
        features.append({
            "type": "Feature",
            "id": feature_id,
            "geometry": mapping(geometry),
            "properties": {"feature_kind": kind, **properties},
        })

    for road in candidate.roads:
        add(road.segment_id, "road_centerline", road.geometry, layer=road.layer, bridge=road.bridge, tunnel=road.tunnel)
    for index, surface in enumerate(candidate.road_surfaces, 1):
        add(f"{candidate.candidate_id}-road-surface-{index}", "road_surface", surface)
    add(f"{candidate.candidate_id}-open-space", "open_space", candidate.open_space)
    for index, parcel in enumerate(candidate.parcels, 1):
        add(f"{candidate.candidate_id}-parcel-{index}", "parcel", parcel)
    for building in candidate.buildings:
        add(building.building_id, "building", building.footprint, floor_count=building.floor_count, use_label=building.use_label, strategy_parameter=building.strategy_parameter)
    for index, footprint in enumerate(candidate.retained_footprints, 1):
        add(f"retained-building-{index}", "retained_building", footprint, locked=True)
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": features,
    }


def _editable_buildings(candidate: Any, request: FixtureScenarioRequest) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for building in candidate.buildings:
        result.append({
            "building_id": building.building_id,
            "floors": [
                {"floor_id": f"{building.building_id}-floor-{level + 1}", "level": level, "geometry": mapping(building.footprint)}
                for level in range(building.floor_count)
            ],
            "first_floor_height_m": request.first_floor_height_m,
            "standard_floor_height_m": request.standard_floor_height_m,
            "provenance": "FIXTURE_ONLY",
            "use_label": building.use_label,
        })
    return result


def _road_graph_payload(candidate: Any) -> dict[str, Any]:
    nodes_by_key: dict[tuple[float, float, int, bool, bool], str] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node_id(coordinate: tuple[float, ...], road: Any) -> str:
        key = (float(coordinate[0]), float(coordinate[1]), road.layer, road.bridge, road.tunnel)
        if key not in nodes_by_key:
            identifier = f"road-node-{len(nodes_by_key) + 1}"
            nodes_by_key[key] = identifier
            nodes.append({"node_id": identifier, "x_m": key[0], "y_m": key[1], "layer": key[2], "bridge": key[3], "tunnel": key[4], "lineage_ids": [road.segment_id]})
        else:
            existing = next(item for item in nodes if item["node_id"] == nodes_by_key[key])
            existing["lineage_ids"] = sorted(set(existing["lineage_ids"]) | {road.segment_id})
        return nodes_by_key[key]

    for road in candidate.roads:
        parts = list(road.geometry.geoms) if road.geometry.geom_type == "MultiLineString" else [road.geometry]
        for part_index, line in enumerate(parts, 1):
            coordinates = list(line.coords)
            for segment_index, (first, second) in enumerate(zip(coordinates, coordinates[1:]), 1):
                first_id = node_id(first, road)
                second_id = node_id(second, road)
                edges.append({
                    "edge_id": f"{road.segment_id}:part-{part_index}:{segment_index}",
                    "start_node_id": first_id,
                    "end_node_id": second_id,
                    "layer": road.layer,
                    "bridge": road.bridge,
                    "tunnel": road.tunnel,
                    "locked": bool(getattr(road, "locked", False)),
                    "lineage_ids": [road.segment_id],
                })
    graph = RoadGraph(
        nodes=tuple(RoadNode(**{**item, "lineage_ids": tuple(item["lineage_ids"])}) for item in nodes),
        edges=tuple(RoadEdge(**{**item, "lineage_ids": tuple(item["lineage_ids"])}) for item in edges),
    )
    return {"nodes": nodes, "edges": edges, "graph_hash": graph.graph_hash}


def _scenario_response(store: ProjectStateStore, record: Any, *, include_geometry: bool = False) -> dict[str, Any]:
    payload = dict(record.payload)
    parameters = payload.get("parameters", {})

    from .decision_resolution import resolve_record_decision
    resolution = resolve_record_decision(store, record, payload.get("geometry_sha256"), "target_geometry_sha256")
    latest_decision = dict(resolution.decision.payload) if resolution.status == "EFFECTIVE" else None
    status_value = payload.get("status", "proposed")
    is_baseline = resolution.status == "EFFECTIVE" and resolution.reason == "Accept" and status_value == "accepted"
    rejection_reason = payload.get("rejection_reason")

    response = {
        "scenario_id": record.entity_id,
        "revision": record.revision,
        "status": status_value,
        "is_baseline": is_baseline,
        "rejection_reason": rejection_reason,
        "latest_decision": latest_decision,
        "geometry_sha256": payload.get("geometry_sha256"),
        "geometry_artifact_id": payload.get("geometry_artifact_id"),
        "provenance": parameters.get("provenance", "UNKNOWN"),
        "valid": parameters.get("validation", {}).get("valid", False),
        "failure_reasons": parameters.get("validation", {}).get("failure_reasons", []),
        "strategy_id": parameters.get("strategy_id") or parameters.get("recipe_id"),
        "strategy_label": parameters.get("strategy_label") or parameters.get("recipe_id") or payload.get("morphology_family") or record.entity_id,
        "display_name": parameters.get("strategy_label") or parameters.get("recipe_id") or payload.get("morphology_family") or record.entity_id,
        "strategy_explanation_status": parameters.get("strategy_explanation_status", "非 AI 生成"),
        "strategy_explanation": parameters.get("strategy_explanation"),
        "input_hash": parameters.get("input_hash"),
        "metrics": parameters.get("metrics", {}),
        "editor": {
            "provenance": parameters.get("provenance", "UNKNOWN"),
            "design_area_m2": parameters.get("design_area_m2"),
            "limits": parameters.get("limits", {}),
            "editable_buildings": parameters.get("editable_buildings", []),
            "active_buildings": parameters.get("active_buildings", {}),
            "active_edit_revision_id": parameters.get("active_edit_revision_id", 0),
            "road_graph": parameters.get("road_graph", {"nodes": [], "edges": [], "graph_hash": None}),
            "road_edit_revision_id": parameters.get("road_edit_revision_id", 0),
            "road_snap_tolerance_m": parameters.get("road_snap_tolerance_m"),
            "road_edit_policy_version": parameters.get("road_edit_policy_version"),
            "land_area_m2": parameters.get("land_area_m2"),
            "syntax_result_ids": parameters.get("syntax_result_ids", []),
            "syntax_statuses": parameters.get("syntax_statuses", {}),
            "accessibility_result_ids": parameters.get("accessibility_result_ids", []),
            "accessibility_statuses": parameters.get("accessibility_statuses", {}),
            "e1_result_ids": parameters.get("e1_result_ids", []),
            "e1_statuses": parameters.get("e1_statuses", {}),
        },
    }
    if include_geometry:
        try:
            artifact = store.current(payload["geometry_artifact_id"])
            response["geometry"] = json.loads(Path(artifact.payload["uri"]).read_text(encoding="utf-8"))
        except (EntityNotFoundError, OSError, json.JSONDecodeError, KeyError) as exc:
            raise HTTPException(status_code=503, detail="scenario geometry artifact is unavailable or invalid") from exc
    return response


def register_scenario_routes(
    app: Any,
    store: ProjectStateStore,
    artifact_root: str | Path,
    decision_key_path: str | Path | None = None,
) -> None:
    router = APIRouter()
    root = Path(artifact_root).resolve()

    @router.post("/api/v1/scenarios/fixtures", status_code=201)
    def create_fixture_scenarios(request: FixtureScenarioRequest) -> dict[str, Any]:
        area = box(
            request.origin_x_m,
            request.origin_y_m,
            request.origin_x_m + request.width_m,
            request.origin_y_m + request.height_m,
        )
        inputs = FixtureGenerationInput(
            design_area=area,
            crs="EPSG:28992",
            seed=request.seed,
            road_width_m=request.road_width_m,
            first_floor_height_m=request.first_floor_height_m,
            standard_floor_height_m=request.standard_floor_height_m,
            strategy_floor_count=request.strategy_floor_count,
            max_footprint_width_m=request.max_footprint_width_m,
            max_footprint_depth_m=request.max_footprint_depth_m,
            far_upper_bound=request.far_upper_bound,
            max_height_m=request.max_height_m,
            max_coverage_ratio=request.max_coverage_ratio,
            min_parcel_area_m2=request.min_parcel_area_m2,
            min_parcel_width_m=request.min_parcel_width_m,
        )
        request_bytes = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        input_hash = "sha256:" + _hash_bytes(request_bytes)
        denominator_hash = "sha256:" + _hash_bytes(area.normalize().wkb)
        run_id = uuid.uuid4().hex[:12]
        result = generate_fixture_strategies(inputs)
        saved: list[dict[str, Any]] = []

        for candidate in result.candidates:
            scenario_id = f"scenario-{request.seed}-{candidate.strategy_id}-{run_id}"
            artifact_id = f"artifact-{scenario_id}-geometry"
            tool_id = f"tool-execution-{scenario_id}"
            geometry_doc = _geojson(candidate)
            geometry_bytes = (json.dumps(geometry_doc, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            artifact_hash = "sha256:" + _hash_bytes(geometry_bytes)
            artifact_path = root / artifact_hash.removeprefix("sha256:")[:2] / f"{artifact_id}.geojson"
            _write_immutable(artifact_path, geometry_bytes)
            gaps = [
                "synthetic fixture; no designer-approved design area or constraints",
                "no compatible Syntax result is available for this fixture",
            ]
            metrics = _candidate_metrics(candidate, area)
            validation = {"valid": candidate.valid, "failure_reasons": list(candidate.failure_reasons), "road_components": candidate.road_component_count, "external_connections": candidate.external_connection_count}
            parameters = {
                "provenance": "FIXTURE_ONLY",
                "fixture_id": request.fixture_id,
                "seed": request.seed,
                "strategy_id": candidate.strategy_id,
                "strategy_label": candidate.strategy_label,
                "strategy_parameters": {"road_width_m": request.road_width_m, "floor_count": request.strategy_floor_count, "footprint_width_m": request.max_footprint_width_m, "footprint_depth_m": request.max_footprint_depth_m},
                "root_geometry_artifact_id": artifact_id,
                "design_area_geometry": mapping(area),
                "design_area_m2": float(area.area),
                "limits": {"far_upper_bound": request.far_upper_bound, "max_height_m": request.max_height_m, "max_coverage_ratio": request.max_coverage_ratio},
                "editable_buildings": _editable_buildings(candidate, request),
                "road_graph": _road_graph_payload(candidate),
                "road_snap_tolerance_m": 1.0,
                "road_edit_policy_version": "synthetic-road-snap-v1",
                "syntax_result_ids": [],
                "syntax_statuses": {},
                "input_hash": input_hash,
                "comparison_basis": {"denominator_hash": denominator_hash, "rules_version": "morphology-metrics-v1", "syntax_layer_version": None, "syntax_method_version": None},
                "metrics": metrics,
                "validation": validation,
                "data_gaps": gaps,
                "strategy_explanation_status": "非 AI 生成",
                "strategy_explanation": f"{candidate.strategy_label}。此文字由確定性策略模板提供，非 AI 生成。",
                "diff_report": candidate.diff_report,
            }
            artifact = Artifact(
                id=artifact_id,
                type="SCENARIO_GEOMETRY",
                uri=str(artifact_path),
                sha256=artifact_hash,
                mime="application/geo+json",
                crs="EPSG:28992",
                producer="fixture-morphology-generator",
                created_at=datetime.now(timezone.utc),
                project_id="fixture-only-project",
                size_bytes=len(geometry_bytes),
            )
            scenario = Scenario(
                id=scenario_id,
                project_id="fixture-only-project",
                site_id=f"synthetic-{request.fixture_id}",
                site_version="fixture-v1",
                morphology_family=candidate.strategy_id,
                geometry_artifact_id=artifact_id,
                geometry_sha256="sha256:" + candidate.geometry_hash,
                generator="fixture-strategy-catalog-v1",
                generator_version=result.fixture_parameter_version,
                seed=request.seed,
                parameters=parameters,
                constraint_set_id="fixture-only-no-approved-constraints",
                status=ScenarioStatus.PROPOSED,
            )
            execution = ToolExecution(
                id=tool_id,
                project_id="fixture-only-project",
                scenario_id=scenario_id,
                tool="fixture-morphology-generator",
                tool_version=result.fixture_parameter_version,
                environment={"runtime": "local-python", "provenance": "FIXTURE_ONLY"},
                input_refs=[request.fixture_id],
                input_snapshot_hashes={request.fixture_id: input_hash},
                parameters={"seed": request.seed, "strategy_id": candidate.strategy_id, "strategy_parameters": parameters["strategy_parameters"], "input_hash": input_hash, "validation": validation},
                output_artifact_refs=[artifact_id],
                output_artifact_hashes=[artifact_hash],
                status=RunStatus.SUCCEEDED if candidate.valid else RunStatus.FAILED,
                idempotency_key=f"fixture-{run_id}-{candidate.strategy_id}",
                limitations=gaps,
            )
            for record in (artifact, scenario, execution):
                store.create_typed(
                    record,
                    actor="fixture-generator",
                    actor_kind=ActorKind.AGENT_AUTOMATION,
                    actor_session_id=f"w5-7-{run_id}",
                    reason="Persist explicitly synthetic W5-7 fixture candidate and provenance",
                )
            saved.append({**_scenario_response(store, store.current(scenario_id)), "tool_execution_id": tool_id})
        return {"provenance": "FIXTURE_ONLY", "input_hash": input_hash, "scenarios": saved}

    @router.get("/api/v1/scenarios")
    def list_scenarios() -> dict[str, Any]:
        return {"scenarios": [_scenario_response(store, record) for record in store.list_current("Scenario")]}

    @router.get("/api/v1/scenarios/{scenario_id}")
    def get_scenario(scenario_id: str) -> dict[str, Any]:
        try:
            record = store.current(scenario_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="scenario was not found") from exc
        if record.entity_type != "DesignScenario":
            raise HTTPException(status_code=404, detail="scenario was not found")
        return _scenario_response(store, record, include_geometry=True)

    key_path = decision_key_path or getattr(getattr(app, "state", None), "decision_key_path", None)
    limiter = getattr(getattr(app, "state", None), "decision_attempt_limiter", None)
    from .scenario_comparison_router import create_scenario_comparison_router
    router.include_router(create_scenario_comparison_router(store, decision_key_path=key_path, decision_attempt_limiter=limiter))

    from .editing.formal_authority import FormalAuthorityError, PersistedFormalEditorAdapter, open_formal_draft
    from .scenario_editing_api import register_scenario_edit_routes
    formal_adapter = PersistedFormalEditorAdapter()

    @router.post("/api/v1/scenarios/{scenario_id}/formal-draft")
    def open_formal_editor(scenario_id: str) -> JSONResponse:
        try:
            draft, created = open_formal_draft(store, scenario_id)
        except FormalAuthorityError as exc:
            raise HTTPException(status_code=409, detail=f"BLOCKED: {exc}") from exc
        body = _scenario_response(store, draft, include_geometry=True)
        body["created"] = created
        return JSONResponse(status_code=201 if created else 200, content=body)

    register_scenario_edit_routes(router, store, root, formal_adapter=formal_adapter)
    from .formal_face_editing_api import register_formal_face_routes
    register_formal_face_routes(router, store, root)
    app.include_router(router)
    from .scenario_syntax_api import create_scenario_syntax_router
    app.include_router(create_scenario_syntax_router(store, root / "scenario-syntax"))


from .scenario_comparison_router import ScenarioComparisonDecisionRequest

__all__ = [
    "FixtureScenarioRequest",
    "ScenarioComparisonRequest",
    "ScenarioComparisonDecisionRequest",
    "register_scenario_routes",
]

