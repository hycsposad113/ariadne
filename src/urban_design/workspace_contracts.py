"""Typed contracts for workspace synchronization and feature dispositions.

Enforces fail-closed validation:
- Client cannot supply extra parameters (e.g. approved=True).
- Source snapshots, features, and study areas are explicitly typed.
- Feature dispositions preserve/editable/undecided are strictly bounded.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator
from shapely.geometry import shape

from .models import ActorKind


class DraftNumericValue(BaseModel):
    """A client-entered numeric brief that has no binding effect."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(..., ge=0)
    unit: Literal["ratio", "m"]
    status: Literal["DRAFT_PENDING_HUMAN_DECISION"] = "DRAFT_PENDING_HUMAN_DECISION"

    @field_validator("value", mode="before")
    @classmethod
    def reject_bool_and_text(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("numeric brief values must be JSON numbers")
        return value

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("numeric brief values must be finite")
        return value


class SpatialZone(BaseModel):
    """Typed, local, non-binding program brief and polygon."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    target_use: str = Field(..., min_length=1)
    geometry: dict[str, Any]
    crs: Literal["EPSG:28992"] = "EPSG:28992"
    area_m2: float = Field(default=0, ge=0)
    author: str = Field(default="designer", min_length=1)
    revision: int = Field(default=1, ge=1)
    original_text: str = ""
    notes: str = ""
    program_demands: list[str] = Field(default_factory=list)
    open_space_demands: list[str] = Field(default_factory=list)
    draft_constraints: list[str] = Field(default_factory=list)
    draft_preferences: list[str] = Field(default_factory=list)
    target_far: DraftNumericValue | None = None
    target_coverage_ratio: DraftNumericValue | None = None
    target_height_m: DraftNumericValue | None = None
    status: Literal["DRAFT_PENDING_HUMAN_DECISION"] = "DRAFT_PENDING_HUMAN_DECISION"

    @model_validator(mode="before")
    @classmethod
    def make_numeric_targets_nonbinding(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cooked = dict(data)
        for key, unit in (("target_far", "ratio"), ("target_coverage_ratio", "ratio"), ("target_height_m", "m")):
            value = cooked.get(key)
            if value is None or isinstance(value, dict):
                continue
            cooked[key] = {"value": value, "unit": unit, "status": "DRAFT_PENDING_HUMAN_DECISION"}
        return cooked

    @model_validator(mode="after")
    def validate_geometry_and_recompute_area(self) -> "SpatialZone":
        if self.crs != "EPSG:28992":
            raise ValueError("SpatialZone geometry must use EPSG:28992")
        if not self.original_text.strip() and not self.notes.strip():
            raise ValueError("SpatialZone must preserve the designer's original note")
        if not self.program_demands and self.target_use.strip():
            self.program_demands = [self.target_use.strip()]
        if self.geometry.get("type") != "Polygon":
            raise ValueError("SpatialZone geometry must be a GeoJSON Polygon")
        if self.target_far is not None and self.target_far.unit != "ratio":
            raise ValueError("target_far unit must be ratio")
        if self.target_coverage_ratio is not None and self.target_coverage_ratio.unit != "ratio":
            raise ValueError("target_coverage_ratio unit must be ratio")
        if self.target_height_m is not None and self.target_height_m.unit != "m":
            raise ValueError("target_height_m unit must be m")
        try:
            polygon = shape(self.geometry)
        except Exception as exc:
            raise ValueError("SpatialZone geometry is not valid GeoJSON") from exc
        if polygon.geom_type != "Polygon" or polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise ValueError("SpatialZone must be a valid, positive-area Polygon")
        coordinates = self.geometry.get("coordinates")
        if not _finite_coordinates(coordinates):
            raise ValueError("SpatialZone coordinates must be finite")
        self.area_m2 = float(polygon.area)
        return self


class WorkspaceSpatialBrief(BaseModel):
    """Unapproved local design intent; it cannot activate project constraints."""

    model_config = ConfigDict(extra="forbid")

    exploration_design_area: "ExplorationDesignArea | None" = None
    zones: list[SpatialZone] = Field(default_factory=list)
    status: Literal["DRAFT_PENDING_HUMAN_DECISION"] = "DRAFT_PENDING_HUMAN_DECISION"

    @model_validator(mode="after")
    def unique_zone_ids(self) -> "WorkspaceSpatialBrief":
        zone_ids = [zone.zone_id for zone in self.zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("SpatialBrief zone IDs must be unique")
        return self


class ExplorationDesignArea(BaseModel):
    """A conceptual, non-legal denominator for exploratory design work."""

    model_config = ConfigDict(extra="forbid")

    geometry: dict[str, Any]
    crs: Literal["EPSG:28992"] = "EPSG:28992"
    area_m2: float = Field(default=0, ge=0)
    scope: Literal["EXPLORATION_DESIGN_AREA"] = "EXPLORATION_DESIGN_AREA"
    status: Literal["DRAFT_PENDING_HUMAN_DECISION"] = "DRAFT_PENDING_HUMAN_DECISION"
    author: str = Field(default="designer", min_length=1)
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_geometry_and_recompute_area(self) -> "ExplorationDesignArea":
        if self.geometry.get("type") != "Polygon":
            raise ValueError("ExplorationDesignArea geometry must be a GeoJSON Polygon")
        try:
            polygon = shape(self.geometry)
        except Exception as exc:
            raise ValueError("ExplorationDesignArea geometry is not valid GeoJSON") from exc
        if (
            polygon.geom_type != "Polygon"
            or polygon.is_empty
            or not polygon.is_valid
            or not isfinite(float(polygon.area))
            or polygon.area <= 0
        ):
            raise ValueError("ExplorationDesignArea must be a valid, finite, positive-area Polygon")
        if not _finite_coordinates(self.geometry.get("coordinates")):
            raise ValueError("ExplorationDesignArea coordinates must be finite")
        self.area_m2 = float(polygon.area)
        return self


def spatial_brief_zone_violations(
    spatial_brief: WorkspaceSpatialBrief | None,
) -> dict[str, str]:
    """Return draft zones outside the chosen exploration area or overlapping peers.

    Zones are non-binding drafts. No allocation rule is part of this contract,
    so positive-area overlap is rejected instead of being assigned implicitly.
    """
    if spatial_brief is None:
        return {}

    exploration_area = (
        shape(spatial_brief.exploration_design_area.geometry)
        if spatial_brief.exploration_design_area is not None
        else None
    )
    geometries = [(zone.zone_id, shape(zone.geometry)) for zone in spatial_brief.zones]
    violations: dict[str, str] = {}

    if exploration_area is not None:
        for zone_id, geometry in geometries:
            if not exploration_area.covers(geometry):
                violations[zone_id] = "outside the Exploration Design Area"

    for index, (left_id, left_geometry) in enumerate(geometries):
        for right_id, right_geometry in geometries[index + 1 :]:
            if left_geometry.intersection(right_geometry).area > 1e-3:
                violations[left_id] = "overlaps another spatial zone without an allocation rule"
                violations[right_id] = "overlaps another spatial zone without an allocation rule"

    return violations


def validate_spatial_brief_zoning(spatial_brief: WorkspaceSpatialBrief | None) -> None:
    """Fail closed when a draft zone escapes its scope or overlaps another zone."""
    violations = spatial_brief_zone_violations(spatial_brief)
    if violations:
        zone_id = next(zone.zone_id for zone in spatial_brief.zones if zone.zone_id in violations)
        raise ValueError(f"SpatialZone {zone_id!r} {violations[zone_id]}")


def _finite_coordinates(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:2]):
            return isfinite(float(value[0])) and isfinite(float(value[1]))
        return all(_finite_coordinates(item) for item in value)
    return False


class FeatureDisposition(BaseModel):
    """Designer-selected disposition and local note for an observed feature."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(..., min_length=1)
    feature_kind: Literal["building", "road"]
    disposition: Literal["preserve", "editable", "undecided"]
    source_artifact_id: str = ""
    source_snapshot_id: str | None = None
    source_feature_id: str | None = None
    annotation: str = Field(default="", max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize disposition casing
            if "disposition" in data and isinstance(data["disposition"], str):
                data["disposition"] = data["disposition"].lower()
            # Map alias feature_type -> feature_kind
            if "feature_type" in data and "feature_kind" not in data:
                data["feature_kind"] = data.pop("feature_type")
            elif "feature_type" in data and "feature_kind" in data:
                data.pop("feature_type")
        return data


class SyncRequest(BaseModel):
    """Request payload to synchronize workspace state from QGIS / source snapshots."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    study_area_id: str = Field(..., min_length=1)
    expected_workspace_revision: int = Field(..., ge=0)
    source_snapshot_ids: list[str] = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    actor_kind: ActorKind
    actor_session_id: StrictStr = Field(..., min_length=1, max_length=128)
    feature_dispositions: list[FeatureDisposition] = Field(default_factory=list)
    spatial_brief: WorkspaceSpatialBrief | None = None

    @field_validator("actor_session_id")
    @classmethod
    def nonempty_actor_session(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("actor_session_id must not be blank")
        return value.strip()


class WorkspaceRevision(BaseModel):
    """Immutable, versioned snapshot of designer's workspace state."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    revision: int = Field(..., ge=1)
    study_area_id: str = Field(..., min_length=1)
    source_snapshot_ids: list[str] = Field(default_factory=list)
    feature_dispositions: list[FeatureDisposition] = Field(default_factory=list)
    spatial_brief: WorkspaceSpatialBrief | None = None
    status: Literal["DRAFT", "VALIDATED", "STALE"] = "DRAFT"
    idempotency_key: str | None = None
    payload_digest: str | None = None


class WorkspaceSyncResponse(BaseModel):
    """API response for a successful workspace synchronization."""

    model_config = ConfigDict(extra="forbid")

    workspace_revision: WorkspaceRevision
    idempotent_replay: bool = False
