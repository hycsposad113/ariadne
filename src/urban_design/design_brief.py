"""Design brief, spatial zones, and user constraint schemas.

Enforces:
- Separation of StudyArea, ContextExtent, and ExplorationDesignArea.
- Explicit human specification for FAR limits (no unapproved default values like 3.5).
- Topological and geometric validation on sketched zones (rejects self-intersection, degenerate coordinates).
- Overlap detection without silently double-counting floor areas.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Sequence
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Polygon, mapping, shape

from .models import ActorKind
from .store import EntityNotFoundError, ProjectStateStore, RevisionConflictError
from .workspace_contracts import FeatureDisposition


class BriefValidationError(Exception):
    """Raised when a spatial brief or zone geometry is invalid."""


class SpatialZone(BaseModel):
    """An annotated local zone sketched by the designer."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(..., min_length=1)
    polygon_geojson: dict[str, Any]
    area_m2: float = Field(..., gt=0)
    program_demands: list[str] = Field(default_factory=list)
    open_space_ratio_target: float | None = None
    max_far: float | None = None
    hard_constraints: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    raw_notes: str = ""
    author: str = "designer"

    @classmethod
    def from_coordinates(
        cls,
        zone_id: str,
        coordinates: Sequence[tuple[float, float]],
        *,
        program_demands: list[str] | None = None,
        open_space_ratio_target: float | None = None,
        max_far: float | None = None,
        hard_constraints: list[str] | None = None,
        soft_preferences: list[str] | None = None,
        raw_notes: str = "",
        author: str = "designer",
    ) -> SpatialZone:
        if len(coordinates) < 3:
            raise BriefValidationError("Polygon requires at least 3 coordinates")
        try:
            poly = Polygon(coordinates)
        except Exception as exc:
            raise BriefValidationError(f"Invalid polygon coordinates: {exc}") from exc

        hull = poly.convex_hull
        if not poly.is_valid:
            if hull.geom_type in ("LineString", "Point"):
                raise BriefValidationError("Polygon has zero area or is degenerate")
            raise BriefValidationError("Polygon is self-intersecting or topologically invalid")
        if poly.is_empty or hull.geom_type in ("LineString", "Point") or poly.area <= 1e-4:
            raise BriefValidationError("Polygon has zero area or is degenerate")

        return cls(
            zone_id=zone_id,
            polygon_geojson=mapping(poly),
            area_m2=round(poly.area, 4),
            program_demands=program_demands or [],
            open_space_ratio_target=open_space_ratio_target,
            max_far=max_far,
            hard_constraints=hard_constraints or [],
            soft_preferences=soft_preferences or [],
            raw_notes=raw_notes,
            author=author,
        )

    def to_shapely(self) -> Polygon:
        return shape(self.polygon_geojson)


class SpatialBrief(BaseModel):
    """The structured spatial design brief containing zones, demands, and constraints."""

    model_config = ConfigDict(extra="forbid")

    brief_id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    revision: int = Field(default=1, ge=1)
    study_area_id: str = Field(..., min_length=1)
    exploration_design_area_m2: float | None = None
    whole_site_far_limit: float | None = None  # None until explicitly entered by designer
    zones: list[SpatialZone] = Field(default_factory=list)
    # Human adoption is not implemented by BriefService. Keep every saved brief
    # in draft until a persisted, validated HumanDecision workflow exists.
    status: Literal["DRAFT"] = "DRAFT"

    def detect_zone_overlaps(self) -> list[tuple[str, str]]:
        overlaps = []
        n = len(self.zones)
        for i in range(n):
            poly_i = self.zones[i].to_shapely()
            for j in range(i + 1, n):
                poly_j = self.zones[j].to_shapely()
                if poly_i.intersects(poly_j):
                    inter = poly_i.intersection(poly_j)
                    if inter.area > 1e-3:
                        overlaps.append((self.zones[i].zone_id, self.zones[j].zone_id))
        return overlaps


class BriefService:
    """Manages persistence and versioning of spatial briefs."""

    def __init__(self, store: ProjectStateStore):
        self.store = store

    def save_brief(
        self,
        brief: SpatialBrief,
        *,
        actor: str,
        actor_kind: ActorKind,
        actor_session_id: str,
    ) -> SpatialBrief:
        if brief.status != "DRAFT":
            raise BriefValidationError(
                "SpatialBrief must remain DRAFT until a valid HumanDecision is persisted"
            )

        entity_id = brief.brief_id
        try:
            current = self.store.current(entity_id)
            next_rev = current.revision + 1
            payload = brief.model_dump()
            payload["revision"] = next_rev
            rec = self.store.update(
                entity_id,
                payload,
                expected_revision=current.revision,
                actor=actor,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
                reason=f"Update spatial brief rev {next_rev}",
                replace=True,
            )
        except EntityNotFoundError:
            payload = brief.model_dump()
            payload["revision"] = 1
            rec = self.store.create(
                entity_type="SpatialBrief",
                payload=payload,
                entity_id=entity_id,
                project_id=brief.project_id,
                actor=actor,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
                action="CreateSpatialBrief",
                reason="Initial spatial brief registration",
            )

        return SpatialBrief.model_validate(rec.payload)

    def get_brief(self, brief_id: str, revision: int | None = None) -> SpatialBrief | None:
        try:
            rec = self.store.replay(brief_id, revision=revision) if revision else self.store.current(brief_id)
            return SpatialBrief.model_validate(rec.payload)
        except EntityNotFoundError:
            return None
