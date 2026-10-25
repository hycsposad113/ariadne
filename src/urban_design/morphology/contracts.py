"""Typed fixture-only contracts for W5-7 strategy generation."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Literal

from shapely.geometry import GeometryCollection, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from urban_design.morphology.metrics import MorphologyMetrics, SITE_GEOMETRY_TOLERANCE_M
from urban_design.models import UnavailableValue

MASK_GEOMETRY_CLEARANCE_M = 0.001
ROAD_CENTERLINE_CLEARANCE_MARGIN_M = 0.01


class MorphologyGenerationError(ValueError):
    """Raised when a strategy-generation input is outside its declared scope."""


@dataclass(frozen=True)
class ApprovedSiteConstraint:
    """A numeric site parameter with an explicit approval or assumption reference."""

    id: str
    name: str
    value: float
    unit: str
    scope: str
    enforcement: Literal["HARD", "PREFERENCE"]
    approval_decision_id: str
    denominator: Literal["land_area", "exploration_design_area"] | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.scope.strip() or not self.approval_decision_id.strip():
            raise MorphologyGenerationError("approved constraint identity, scope, and decision reference are required")
        expected_units = {
            "far_upper_limit": "ratio",
            "zone_far_upper_limit": "ratio",
            "coverage_upper_limit": "ratio",
            "height_upper_limit": "m",
            "first_floor_height": "m",
            "standard_floor_height": "m",
            "road_width": "m",
        }
        if self.name not in expected_units:
            raise MorphologyGenerationError(f"unsupported approved site constraint {self.name!r}")
        if self.unit != expected_units[self.name]:
            raise MorphologyGenerationError(f"{self.name} unit must be {expected_units[self.name]}")
        if self.enforcement not in {"HARD", "PREFERENCE"}:
            raise MorphologyGenerationError(f"{self.name} enforcement must be HARD or PREFERENCE")
        if isinstance(self.value, bool) or not isinstance(self.value, (float, int)) or not math.isfinite(float(self.value)):
            raise MorphologyGenerationError(f"{self.name} must have a finite numeric approved value")
        if self.value < 0:
            raise MorphologyGenerationError(f"{self.name} must be nonnegative")
        if self.name in {"road_width", "height_upper_limit", "first_floor_height", "standard_floor_height"} and self.value <= 0:
            raise MorphologyGenerationError(f"{self.name} must be positive")
        if self.name == "coverage_upper_limit" and self.value > 1:
            raise MorphologyGenerationError("coverage_upper_limit must be between zero and one")
        if self.name in {"far_upper_limit", "coverage_upper_limit", "first_floor_height", "standard_floor_height"} and self.scope != "whole_site":
            raise MorphologyGenerationError(f"{self.name} scope must be whole_site")
        if self.name == "road_width" and not self.scope.startswith("road:"):
            raise MorphologyGenerationError("road_width scope must be road:<hierarchy>")
        if self.name in {"zone_far_upper_limit", "height_upper_limit"} and self.scope != "whole_site" and not self.scope.startswith("zone:"):
            raise MorphologyGenerationError(f"{self.name} scope must be whole_site or zone:<zone_id>")


@dataclass(frozen=True)
class SiteRoadInput:
    """Source road geometry with explicit vertical topology and provenance."""

    road_id: str
    geometry: BaseGeometry
    layer: int
    bridge: bool
    tunnel: bool
    source_artifact_id: str
    source_snapshot_id: str
    road_width_scope: str | None
    highway: str | None = None
    service: str | None = None
    access: str | None = None
    motor_vehicle: str | None = None
    foot: str | None = None
    inactive: bool = False

    def __post_init__(self) -> None:
        if not self.road_id.strip() or not self.source_artifact_id.strip() or not self.source_snapshot_id.strip():
            raise MorphologyGenerationError("road id and source Artifact/DatasetSnapshot references are required")
        if self.geometry.geom_type not in {"LineString", "MultiLineString", "Polygon", "MultiPolygon"} or self.geometry.is_empty or not self.geometry.is_valid:
            raise MorphologyGenerationError(f"road {self.road_id!r} must have valid line or polygon geometry")
        if isinstance(self.layer, bool) or not isinstance(self.layer, int):
            raise MorphologyGenerationError(f"road {self.road_id!r} requires an integer layer")
        if not isinstance(self.bridge, bool) or not isinstance(self.tunnel, bool):
            raise MorphologyGenerationError(f"road {self.road_id!r} requires explicit bridge/tunnel flags")
        if not isinstance(self.inactive, bool):
            raise MorphologyGenerationError(f"road {self.road_id!r} inactive status must be boolean")
        if self.road_width_scope is not None and not self.road_width_scope.startswith("road:"):
            raise MorphologyGenerationError("road_width_scope must use road:<hierarchy> or be explicitly None")
        for name in ("highway", "service", "access", "motor_vehicle", "foot"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise MorphologyGenerationError(f"road {self.road_id!r} {name} tag must be a non-empty string or None")


@dataclass(frozen=True)
class PreservedBuildingInput:
    """An immutable observed footprint; unknown floors remain explicitly unknown."""

    building_id: str
    footprint: BaseGeometry
    floor_count: int | None
    source_artifact_id: str
    source_snapshot_id: str

    def __post_init__(self) -> None:
        if not self.building_id.strip() or not self.source_artifact_id.strip() or not self.source_snapshot_id.strip():
            raise MorphologyGenerationError("preserved building id and source references are required")
        if self.footprint.geom_type not in {"Polygon", "MultiPolygon"} or self.footprint.is_empty or not self.footprint.is_valid:
            raise MorphologyGenerationError(f"preserved building {self.building_id!r} needs valid polygon geometry")
        if self.floor_count is not None and (
            isinstance(self.floor_count, bool) or not isinstance(self.floor_count, int) or self.floor_count < 1
        ):
            raise MorphologyGenerationError(f"preserved building {self.building_id!r} floor count must be positive or explicitly unknown")


@dataclass(frozen=True)
class SiteZoneInput:
    """Approved zone geometry and an explicitly hard or preferred use."""

    zone_id: str
    geometry: BaseGeometry
    crs: str
    target_use: str
    use_enforcement: Literal["HARD", "PREFERENCE"]

    def __post_init__(self) -> None:
        if not self.zone_id.strip() or not self.target_use.strip():
            raise MorphologyGenerationError("zone id and target use are required")
        if self.crs != "EPSG:28992":
            raise MorphologyGenerationError(f"zone {self.zone_id!r} must use EPSG:28992")
        if self.geometry.geom_type not in {"Polygon", "MultiPolygon"} or self.geometry.is_empty or not self.geometry.is_valid:
            raise MorphologyGenerationError(f"zone {self.zone_id!r} must have valid polygon geometry")
        if self.use_enforcement not in {"HARD", "PREFERENCE"}:
            raise MorphologyGenerationError(f"zone {self.zone_id!r} use enforcement must be HARD or PREFERENCE")


@dataclass(frozen=True)
class NonBuildableArea:
    """A source-linked polygon excluded from generation and land FAR area."""

    id: str
    geometry: BaseGeometry
    kind: str
    source_artifact_id: str

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.kind.strip() or not self.source_artifact_id.strip():
            raise MorphologyGenerationError("non-buildable area id, kind, and source Artifact reference are required")
        if self.geometry.geom_type not in {"Polygon", "MultiPolygon"} or self.geometry.is_empty or not self.geometry.is_valid:
            raise MorphologyGenerationError(f"non-buildable area {self.id!r} needs valid polygon geometry")
        if not math.isfinite(float(self.geometry.area)) or self.geometry.area <= 0:
            raise MorphologyGenerationError(f"non-buildable area {self.id!r} must have positive finite area")


@dataclass(frozen=True)
class ExternalRoadContact:
    contact_id: str
    source_road_id: str
    point: BaseGeometry
    layer: int
    bridge: bool
    tunnel: bool
    source_artifact_id: str
    source_snapshot_id: str
    highway: str
    source_mode: Literal["motor_vehicle", "pedestrian"]
    priority: Literal["major", "minor"]


@dataclass(frozen=True)
class UnconnectedRoadContact:
    contact_id: str
    source_road_id: str
    highway: str
    source_mode: Literal["motor_vehicle", "pedestrian"]
    priority: Literal["major", "minor"]
    reason: str
    layer: int
    bridge: bool
    tunnel: bool


@dataclass(frozen=True)
class GeneratedFloorBlock:
    """One storey volume interval represented by a footprint and vertical range."""

    floor_number: int
    footprint: BaseGeometry
    base_height_m: float
    top_height_m: float
    use_label: str


@dataclass(frozen=True)
class SiteGenerationInput:
    """Non-rectangular site inputs. Every policy value is supplied explicitly."""

    design_area: BaseGeometry
    crs: str
    seed: int
    source_network_roads: tuple[SiteRoadInput, ...]
    preserved_roads: tuple[SiteRoadInput, ...]
    preserved_buildings: tuple[PreservedBuildingInput, ...]
    zones: tuple[SiteZoneInput, ...]
    approved_constraints: tuple[ApprovedSiteConstraint, ...]
    minimum_fragment_area_m2: float
    minimum_fragment_width_m: float
    fragment_rule_version: str
    allocation_policy: Literal["priority"] | None
    provenance: Literal["APPROVED_PROJECT_DATA", "FIXTURE_ONLY", "ASSUMED"]
    non_buildable_areas: tuple[NonBuildableArea, ...] = ()
    waterfront_public_areas: tuple[BaseGeometry, ...] = ()
    minimum_footprint_area_m2: float = 0.0
    minimum_short_edge_m: float = 0.0

    def __post_init__(self) -> None:
        if self.crs != "EPSG:28992":
            raise MorphologyGenerationError("site generation requires EPSG:28992")
        if not isinstance(self.design_area, Polygon) or self.design_area.is_empty or not self.design_area.is_valid:
            raise MorphologyGenerationError("design area must be a valid, positive-area EPSG:28992 Polygon; holes are supported")
        if not math.isfinite(float(self.design_area.area)) or self.design_area.area <= 0:
            raise MorphologyGenerationError("design area must have finite positive area")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise MorphologyGenerationError("site generation seed must be an integer")
        if self.provenance not in {"APPROVED_PROJECT_DATA", "FIXTURE_ONLY", "ASSUMED"}:
            raise MorphologyGenerationError("site generation provenance must be explicit")
        _positive(self.minimum_fragment_area_m2, "minimum fragment area")
        _positive(self.minimum_fragment_width_m, "minimum fragment width")
        _nonnegative(self.minimum_footprint_area_m2, "minimum footprint area")
        _nonnegative(self.minimum_short_edge_m, "minimum footprint short edge")
        if not self.fragment_rule_version.strip():
            raise MorphologyGenerationError("fragment rule version is required")
        if self.allocation_policy not in {None, "priority"}:
            raise MorphologyGenerationError("zone allocation policy must be None or priority")
        if not self.source_network_roads:
            raise MorphologyGenerationError("source network roads are required to derive external road contacts")
        if not self.zones:
            raise MorphologyGenerationError("approved zoning inputs are required")
        zone_ids = [item.zone_id for item in self.zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise MorphologyGenerationError("zone IDs must be unique")
        for zone in self.zones:
            if not self.design_area.covers(zone.geometry) and not self.design_area.buffer(SITE_GEOMETRY_TOLERANCE_M).covers(zone.geometry):
                raise MorphologyGenerationError(f"zone {zone.zone_id!r} lies outside the design area")
        if self.allocation_policy is None:
            for index, zone in enumerate(self.zones):
                if any(zone.geometry.intersection(other.geometry).area > 1e-3 for other in self.zones[index + 1 :]):
                    raise MorphologyGenerationError("positive-area zone overlap requires an explicit priority allocation policy")
        mask_ids = [item.id for item in self.non_buildable_areas]
        if len(mask_ids) != len(set(mask_ids)):
            raise MorphologyGenerationError("non-buildable area IDs must be unique")
        for item in self.non_buildable_areas:
            if not item.geometry.intersects(self.design_area):
                raise MorphologyGenerationError(f"non-buildable area {item.id!r} does not intersect the design area")
        for index, geometry in enumerate(self.waterfront_public_areas):
            if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
                raise MorphologyGenerationError("waterfront public areas need valid polygon geometry")
            if not self.land_area.covers(geometry) and not self.land_area.buffer(SITE_GEOMETRY_TOLERANCE_M).covers(geometry):
                raise MorphologyGenerationError("waterfront public area must lie on non-masked land")
            if any(geometry.intersection(other).area > 1e-6 for other in self.waterfront_public_areas[index + 1 :]):
                raise MorphologyGenerationError("waterfront public areas must not overlap")
        required = {
            "far_upper_limit": "whole_site",
            "coverage_upper_limit": "whole_site",
            "height_upper_limit": "whole_site",
            "first_floor_height": "whole_site",
            "standard_floor_height": "whole_site",
        }
        for name, scope in required.items():
            matches = [item for item in self.approved_constraints if item.name == name and item.scope == scope]
            if len(matches) != 1:
                raise MorphologyGenerationError(f"exactly one approved {name} constraint scoped to {scope} is required")
        road_widths = [item for item in self.approved_constraints if item.name == "road_width"]
        if not road_widths:
            raise MorphologyGenerationError("at least one approved road_width constraint is required")
        for item in self.approved_constraints:
            if item.scope.startswith("zone:") and item.scope.removeprefix("zone:") not in zone_ids:
                raise MorphologyGenerationError(f"constraint {item.name!r} references unknown zone {item.scope!r}")
        identities = [(item.name, item.scope) for item in self.approved_constraints]
        if len(identities) != len(set(identities)):
            raise MorphologyGenerationError("approved site constraints must have unique name and scope pairs")
        if not any(road.geometry.intersection(self.design_area.exterior).geom_type in {"Point", "MultiPoint", "LineString", "MultiLineString", "GeometryCollection"} and not road.geometry.intersection(self.design_area.exterior).is_empty for road in self.source_network_roads):
            raise MorphologyGenerationError("source road network does not intersect the design-area exterior boundary")
        for road in self.preserved_roads:
            if not road.geometry.intersects(self.design_area):
                raise MorphologyGenerationError(f"preserved road {road.road_id!r} does not intersect the design area")
            if road.geometry.geom_type in {"LineString", "MultiLineString"} and road.road_width_scope is None:
                if self.provenance == "APPROVED_PROJECT_DATA":
                    raise MorphologyGenerationError(f"preserved line road {road.road_id!r} requires an approved width scope")
                # Non-approved runs may keep the source centerline when no width
                # is declared for its hierarchy. Do not invent a width.
                continue
        for building in self.preserved_buildings:
            if not self.design_area.covers(building.footprint):
                raise MorphologyGenerationError(f"preserved building {building.building_id!r} lies outside the design area")
            if building.footprint.intersection(self.non_buildable_geometry).area > 1e-9:
                raise MorphologyGenerationError(f"preserved building {building.building_id!r} overlaps a non-buildable area")
        for index, building in enumerate(self.preserved_buildings):
            if any(building.footprint.intersection(other.footprint).area > 1e-9 for other in self.preserved_buildings[index + 1 :]):
                raise MorphologyGenerationError("preserved building footprints overlap")

    @property
    def non_buildable_geometry(self) -> BaseGeometry:
        geometries = [
            item.geometry if self.design_area.covers(item.geometry) else item.geometry.intersection(self.design_area)
            for item in self.non_buildable_areas
        ]
        geometries = [item for item in geometries if not item.is_empty]
        return unary_union(geometries) if geometries else GeometryCollection()

    @property
    def water_geometry(self) -> BaseGeometry:
        geometries = [
            item.geometry if self.design_area.covers(item.geometry) else item.geometry.intersection(self.design_area)
            for item in self.non_buildable_areas
            if item.kind.casefold() == "water"
        ]
        geometries = [item for item in geometries if not item.is_empty]
        return unary_union(geometries) if geometries else GeometryCollection()

    @property
    def non_buildable_clearance_geometry(self) -> BaseGeometry:
        if self.non_buildable_geometry.is_empty:
            return GeometryCollection()
        return self.non_buildable_geometry.buffer(MASK_GEOMETRY_CLEARANCE_M)

    @property
    def land_area(self) -> BaseGeometry:
        if not self.non_buildable_areas:
            return self.design_area
        result = self.design_area.difference(self.non_buildable_geometry)
        if result.is_empty or not result.is_valid or not math.isfinite(float(result.area)) or result.area <= 0:
            raise MorphologyGenerationError("non-buildable masks leave no valid positive-area land")
        return result

    @property
    def development_area(self) -> BaseGeometry:
        result = self.land_area
        if not self.non_buildable_geometry.is_empty:
            result = result.difference(self.non_buildable_clearance_geometry)
        if self.waterfront_public_areas:
            result = result.difference(unary_union(self.waterfront_public_areas))
        return result


def _positive(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value <= 0:
        raise MorphologyGenerationError(f"{field_name} must be a positive finite number")
    return float(value)


def _nonnegative(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise MorphologyGenerationError(f"{field_name} must be a finite nonnegative number")
    return float(value)


@dataclass(frozen=True)
class FixtureGenerationInput:
    """A synthetic rectangular EPSG:28992 boundary and versioned fixture parameters."""

    design_area: BaseGeometry
    crs: str
    seed: int
    road_width_m: float
    first_floor_height_m: float
    standard_floor_height_m: float
    strategy_floor_count: int
    max_footprint_width_m: float = 24.0
    max_footprint_depth_m: float = 20.0
    far_upper_bound: float | None = None
    max_height_m: float | None = None
    max_coverage_ratio: float | None = None
    retained_footprints: tuple[BaseGeometry, ...] = ()
    retained_floor_counts: tuple[int | None, ...] = ()
    min_parcel_area_m2: float = 100.0
    min_parcel_width_m: float = 4.0
    provenance: str = "FIXTURE_ONLY"
    fixture_parameter_version: str = "w5-7-fixture-v1"

    def __post_init__(self) -> None:
        if self.provenance != "FIXTURE_ONLY":
            raise MorphologyGenerationError("W5-7 D2 generator accepts FIXTURE_ONLY inputs only")
        if self.crs != "EPSG:28992":
            raise MorphologyGenerationError("fixture design area must use EPSG:28992")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise MorphologyGenerationError("seed must be an integer")
        if not isinstance(self.design_area, Polygon) or not self.design_area.is_valid or self.design_area.is_empty:
            raise MorphologyGenerationError("design area must be a valid non-empty rectangular polygon")
        bounds = self.design_area.bounds
        if self.design_area.interiors or not self.design_area.equals(box(*bounds)):
            raise MorphologyGenerationError("D2 fixture design area must be axis-aligned rectangular and hole-free")
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise MorphologyGenerationError("design area dimensions must be positive")
        _positive(self.road_width_m, "road width")
        _positive(self.first_floor_height_m, "first-floor height")
        _positive(self.standard_floor_height_m, "standard-floor height")
        _positive(self.max_footprint_width_m, "maximum fixture footprint width")
        _positive(self.max_footprint_depth_m, "maximum fixture footprint depth")
        if isinstance(self.strategy_floor_count, bool) or not isinstance(self.strategy_floor_count, int) or self.strategy_floor_count < 1:
            raise MorphologyGenerationError("strategy floor count must be a positive integer")
        if self.far_upper_bound is not None:
            _nonnegative(self.far_upper_bound, "FAR upper bound")
        if self.max_height_m is not None:
            _positive(self.max_height_m, "maximum height")
        if self.max_coverage_ratio is not None and not 0 <= _nonnegative(self.max_coverage_ratio, "maximum coverage ratio") <= 1:
            raise MorphologyGenerationError("maximum coverage ratio must be between 0 and 1")
        _nonnegative(self.min_parcel_area_m2, "minimum parcel area")
        _nonnegative(self.min_parcel_width_m, "minimum parcel width")
        if not isinstance(self.fixture_parameter_version, str) or not self.fixture_parameter_version.strip():
            raise MorphologyGenerationError("fixture parameter version must be non-empty")
        for index, footprint in enumerate(self.retained_footprints):
            if not isinstance(footprint, BaseGeometry) or footprint.is_empty or not footprint.is_valid:
                raise MorphologyGenerationError(f"retained footprint {index} must be valid non-empty geometry")
            if footprint.geom_type not in {"Polygon", "MultiPolygon"} or not self.design_area.covers(footprint):
                raise MorphologyGenerationError(f"retained footprint {index} must be polygonal and inside the design area")
        counts = self.retained_floor_counts
        if self.retained_footprints and not counts:
            counts = tuple(None for _ in self.retained_footprints)
            object.__setattr__(self, "retained_floor_counts", counts)
        if len(counts) != len(self.retained_footprints):
            raise MorphologyGenerationError("retained floor counts must align one-to-one with retained footprints")
        for index, count in enumerate(counts):
            if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count <= 0):
                raise MorphologyGenerationError(f"retained floor count {index} must be a positive integer or unavailable")


@dataclass(frozen=True)
class RoadSegment:
    segment_id: str
    geometry: BaseGeometry
    layer: int = 0
    bridge: bool = False
    tunnel: bool = False
    road_width_scope: str | None = None

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise MorphologyGenerationError("road segment id must be non-empty")
        if self.geometry.geom_type not in {"LineString", "MultiLineString"} or self.geometry.is_empty or not self.geometry.is_valid:
            raise MorphologyGenerationError(f"road segment {self.segment_id} must be a valid non-empty line")
        if isinstance(self.layer, bool) or not isinstance(self.layer, int):
            raise MorphologyGenerationError(f"road segment {self.segment_id} layer must be an integer")
        if not isinstance(self.bridge, bool) or not isinstance(self.tunnel, bool):
            raise MorphologyGenerationError(f"road segment {self.segment_id} bridge/tunnel flags must be boolean")
        if self.road_width_scope is not None and not self.road_width_scope.startswith("road:"):
            raise MorphologyGenerationError(f"road segment {self.segment_id} width scope must use road:<hierarchy>")


@dataclass(frozen=True)
class GeneratedBuilding:
    building_id: str
    footprint: BaseGeometry
    floor_count: int
    use_label: str
    strategy_parameter: str
    zone_id: str | None = None
    floor_blocks: tuple[GeneratedFloorBlock, ...] = ()


@dataclass(frozen=True)
class StrategyCandidate:
    candidate_id: str
    strategy_id: str
    strategy_label: str
    seed: int
    scenario_status: str
    provenance: str
    geometry_hash: str
    roads: tuple[RoadSegment, ...]
    road_surfaces: tuple[BaseGeometry, ...]
    open_space: BaseGeometry
    parcels: tuple[BaseGeometry, ...]
    buildings: tuple[GeneratedBuilding, ...]
    retained_footprints: tuple[BaseGeometry, ...]
    metrics: MorphologyMetrics
    valid: bool
    failure_reasons: tuple[str, ...] = ()
    diff_report: dict[str, Any] = field(default_factory=dict)
    road_component_count: int = 0
    external_connection_count: int = 0
    preserved_roads: tuple[SiteRoadInput, ...] = ()
    preserved_road_surfaces: tuple[BaseGeometry, ...] = ()
    external_contacts: tuple[ExternalRoadContact, ...] = ()
    unconnected_contacts: tuple[UnconnectedRoadContact, ...] = ()
    excluded_fragments: tuple[Any, ...] = ()


@dataclass(frozen=True)
class StrategyGenerationResult:
    fixture_parameter_version: str
    candidates: tuple[StrategyCandidate, ...]
    provenance: str = "FIXTURE_ONLY"


@dataclass(frozen=True)
class SiteStrategyGenerationResult:
    rules_version: str
    candidates: tuple[StrategyCandidate, ...]
    provenance: str
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ApprovedSiteConstraint",
    "ExternalRoadContact",
    "FixtureGenerationInput",
    "GeneratedFloorBlock",
    "GeneratedBuilding",
    "MorphologyGenerationError",
    "PreservedBuildingInput",
    "RoadSegment",
    "SiteGenerationInput",
    "SiteRoadInput",
    "SiteStrategyGenerationResult",
    "SiteZoneInput",
    "SITE_GEOMETRY_TOLERANCE_M",
    "StrategyCandidate",
    "StrategyGenerationResult",
    "UnconnectedRoadContact",
]
