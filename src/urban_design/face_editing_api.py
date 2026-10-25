"""Isolated, stateless fixture face preview router; no authority or database writes."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from shapely.geometry import LineString, Polygon, mapping
from shapely.errors import GEOSException

from urban_design.editing.faces import FaceEditError, FaceEditHistory, fixture_quantities
from urban_design.editing.floors import BuildingMassing, FloorStorey


class FloorInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    level: StrictInt
    ring: list[tuple[float, float]]


class FaceAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['SPLIT_LINE', 'SPLIT_CONTOUR', 'SIDE_PUSH', 'TOP_EXTRUDE', 'SETBACK', 'UNDO']
    parent_revision: StrictInt = Field(ge=0)
    face_id: str | None = None
    points: list[tuple[float, float]] = Field(default_factory=list)
    steps: StrictInt = 1
    semantics: Literal['NEW_USABLE_FLOORS_PROTOTYPE'] = 'NEW_USABLE_FLOORS_PROTOTYPE'


class FacePreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provenance: Literal['FIXTURE_ONLY']
    coordinate_reference: Literal['FIXTURE_LOCAL_METRES']
    building_id: str = Field(min_length=1)
    first_floor_height_m: float = Field(gt=0, allow_inf_nan=False)
    standard_floor_height_m: float = Field(gt=0, allow_inf_nan=False)
    floors: list[FloorInput] = Field(min_length=1, max_length=100)
    actions: list[FaceAction] = Field(default_factory=list, max_length=100)


def create_face_editing_router() -> APIRouter:
    router = APIRouter(prefix='/api/v1/editing/faces', tags=['face-fixture-preview'])

    @router.get('/readiness')
    def readiness():
        return {'status': 'BLOCKED', 'reason': 'APPROVED_BASELINE_BOUNDS_AND_FOUNDER_FLOOR_SEMANTICS_REQUIRED', 'fixture_preview_available': True, 'acceptance_eligible': False}

    @router.post('/fixture-preview')
    def preview(request: FacePreviewRequest):
        try:
            history = FaceEditHistory(BuildingMassing(request.building_id, tuple(FloorStorey(f.id, f.level, Polygon(f.ring)) for f in request.floors), request.first_floor_height_m, request.standard_floor_height_m))
            for action in request.actions:
                if action.parent_revision != history.active_revision_id:
                    raise FaceEditError('stale parent revision')
                if action.operation == 'UNDO':
                    history.undo()
                elif action.operation == 'SETBACK':
                    history.setback_upper_two(expected_revision=action.parent_revision, metres=action.steps)
                elif action.operation.startswith('SPLIT'):
                    cutter = LineString(action.points) if action.operation == 'SPLIT_LINE' else Polygon(action.points)
                    history.subdivide(action.face_id or '', expected_revision=action.parent_revision, cutter=cutter)
                else:
                    target = next((f for f in history.active.faces if f.id == action.face_id), None)
                    if target is None or target.kind != ('SIDE' if action.operation == 'SIDE_PUSH' else 'TOP'):
                        raise FaceEditError('operation does not match semantic face kind')
                    history.extrude(action.face_id, expected_revision=action.parent_revision, steps=action.steps, semantic_option=action.semantics)
            revision = history.active
            gfa, volume = fixture_quantities(revision.building)
            return {'status': 'FIXTURE_ONLY', 'production_status': 'BLOCKED', 'acceptance_eligible': False, 'analysis_eligible': False,
                    'revision': revision.revision_id, 'parent_revision': revision.parent_revision_id, 'geometry_hash': revision.building.geometry_hash(),
                    'gfa_m2': gfa, 'volume_m3': volume, 'lineage': revision.lineage,
                    'floors': [{'id': f.id, 'level': f.level, 'area_m2': f.geometry.area, 'geometry': mapping(f.geometry)} for f in revision.building.floors],
                    'faces': [{'id': f.id, 'floor_id': f.floor_id, 'kind': f.kind, 'edge_index': f.edge_index, 'geometry': mapping(f.geometry)} for f in revision.faces]}
        except (FaceEditError, ValueError, TypeError, OverflowError, GEOSException) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
