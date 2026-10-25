"""Typed Pydantic contracts for environment analysis (W6 precursor lane)."""

from __future__ import annotations

import warnings
import zoneinfo
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


E1_PLAN_REVISION = "DRAFT_DOMAIN_FOUNDER_2026-10-04"
E1_PLAN_LABEL = f"E1_PLAN: {E1_PLAN_REVISION}"
E1_PUBLIC_SPACE_DOMAIN_DEFINITION = (
    "Per scheme: site land minus new and retained building footprints and water; "
    "streets and roads are included as public space. Paired delta uses the intersection of both domains. "
    "This extent is a geometric analysis extent and is not a legal right of way."
)


class SiteLocation(BaseModel):
    """Geographic location and timezone definition for solar position calculation."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    elevation: float = Field(default=0.0, description="Elevation above sea level in metres")
    timezone: str = Field(default="Europe/Amsterdam", description="IANA timezone name")
    location_tag: str = Field(default="FIXTURE_ONLY", description="Explicit audit tag")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except Exception as exc:
            raise ValueError(f"Invalid IANA timezone: {v}") from exc
        return v


class AnalysisPeriod(BaseModel):
    """Time interval and sampling rate for environmental simulations."""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    dates: list[date] | None = Field(
        default=None,
        description="Explicit local dates to sample; when omitted every date in the inclusive range is sampled.",
    )
    start_hour: float = Field(ge=0.0, le=24.0, default=0.0)
    end_hour: float = Field(ge=0.0, le=24.0, default=24.0)
    timestep: int = Field(ge=1, le=60, default=1, description="Samples per hour (1, 4, 12, etc.)")

    @model_validator(mode="after")
    def validate_period(self) -> AnalysisPeriod:
        if self.start_date > self.end_date:
            raise ValueError(f"start_date ({self.start_date}) must be <= end_date ({self.end_date})")
        if self.start_hour >= self.end_hour:
            raise ValueError(f"start_hour ({self.start_hour}) must be < end_hour ({self.end_hour})")
        if self.dates is not None:
            if not self.dates:
                raise ValueError("dates must contain at least one analysis date when provided")
            if self.dates != sorted(set(self.dates)):
                raise ValueError("dates must be unique and ordered")
            if self.dates[0] < self.start_date or self.dates[-1] > self.end_date:
                raise ValueError("analysis dates must fall within start_date and end_date")
        return self


class SensorPoint(BaseModel):
    """A discrete spatial sensor point on a horizontal or angled surface."""

    model_config = ConfigDict(extra="forbid")

    point_id: str = Field(description="Deterministic ID derived from world coordinates")
    coordinates: tuple[float, float, float] = Field(description="(x, y, z) in metres (local CRS)")
    normal: tuple[float, float, float] = Field(
        default=(0.0, 0.0, 1.0), description="Normalized surface normal vector"
    )
    surface_offset: float = Field(
        default=0.05,
        ge=0.0,
        description="Normal offset in metres to avoid self-occlusion (must be >= 0.0)",
    )
    status: Literal["VALID", "EXCLUDED_INSIDE_FOOTPRINT"] = Field(
        default="VALID", description="Sensor operational status"
    )
    cell_area_m2: float = Field(default=1.0, gt=0.0, description="Representative grid cell area in m2")

    @field_validator("surface_offset")
    @classmethod
    def validate_offset(cls, v: float) -> float:
        if v == 0.0:
            warnings.warn(
                "SensorPoint surface_offset is 0.0; this may cause coplanar self-occlusion.",
                UserWarning,
                stacklevel=2,
            )
        return v

    @classmethod
    def create(
        cls,
        x: float,
        y: float,
        z: float = 0.0,
        normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
        surface_offset: float = 0.05,
        status: Literal["VALID", "EXCLUDED_INSIDE_FOOTPRINT"] = "VALID",
        cell_area_m2: float = 1.0,
    ) -> SensorPoint:
        """Create a SensorPoint with a deterministic coordinate-based ID."""
        point_id = f"pt_{round(x, 4)}_{round(y, 4)}_{round(z, 4)}"
        return cls(
            point_id=point_id,
            coordinates=(float(x), float(y), float(z)),
            normal=normal,
            surface_offset=surface_offset,
            status=status,
            cell_area_m2=cell_area_m2,
        )


class Obstacle(BaseModel):
    """Context geometry blocking direct sunlight."""

    model_config = ConfigDict(extra="forbid")

    obstacle_id: str
    kind: Literal["BOX_AABB", "POLYGONS"]
    source: str = "FIXTURE_ONLY"
    geometry_hash: str
    bounds: tuple[float, float, float, float, float, float] | None = Field(
        default=None, description="(min_x, min_y, min_z, max_x, max_y, max_z)"
    )
    faces: list[list[tuple[float, float, float]]] | None = Field(
        default=None, description="List of polygon vertex lists in 3D"
    )

    @model_validator(mode="after")
    def validate_obstacle_data(self) -> Obstacle:
        if self.kind == "BOX_AABB" and self.bounds is None:
            raise ValueError("BOX_AABB obstacle requires bounds (min_x, min_y, min_z, max_x, max_y, max_z)")
        if self.kind == "POLYGONS" and not self.faces:
            raise ValueError("POLYGONS obstacle requires faces")
        return self


class PointSunlightResult(BaseModel):
    """Sunlight duration result for a single sensor point."""

    model_config = ConfigDict(extra="forbid")

    point_id: str
    coordinates: tuple[float, float, float]
    status: Literal["VALID", "EXCLUDED_INSIDE_FOOTPRINT"]
    sunlight_hours: float = Field(ge=0.0)
    visible_samples: int = Field(ge=0)
    total_daytime_samples: int = Field(ge=0)
    direct_fraction: float = Field(ge=0.0, le=1.0)


class SunlightSimulationResult(BaseModel):
    """Aggregated sunlight simulation output across all test points."""

    model_config = ConfigDict(extra="forbid")

    results: list[PointSunlightResult]
    daily_results: dict[str, list[PointSunlightResult]] = Field(
        default_factory=dict,
        description="Per-local-date point sunlight results, keyed by YYYY-MM-DD.",
    )
    total_sun_vectors: int = Field(ge=0)
    daytime_hours: float = Field(ge=0.0)
    period: AnalysisPeriod
    location: SiteLocation
    method: Literal["ladybug_radiance", "pure_python_box_ray"]
    engine: str = "ladybug-sunpath+python-raycast"
    version: str = "0.1.0"
    fixture_tag: str = "FIXTURE_ONLY"
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroundGridDefinition(BaseModel):
    """Specification for regular ground sensor grid generation."""

    model_config = ConfigDict(extra="forbid")

    origin_x: float = 0.0
    origin_y: float = 0.0
    spacing_m: float = Field(gt=0.0, default=5.0)
    crs: str = "LOCAL_METRE"
    tag: str = "FIXTURE_ONLY"


class SensorGridResult(BaseModel):
    """Generated sensor grid including coverage and area-weighted metrics."""

    model_config = ConfigDict(extra="forbid")

    grid_definition: GroundGridDefinition
    points: list[SensorPoint]
    total_points: int = Field(ge=0)
    valid_points: int = Field(ge=0)
    excluded_points: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    total_area_m2: float = Field(ge=0.0, description="Total area represented by all sensor cells")
    area_weighted_average: float = Field(description="Area-weighted mean of valid points")
    total_area_integral: float = Field(description="Sum of (area_i * value_i) across valid points")
    valid_area_m2: float = Field(ge=0.0)
    excluded_area_m2: float = Field(ge=0.0, description="Area represented by excluded sensor cells")
    area_coverage_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Valid sensor-cell area divided by total sensor-cell area; not polygon coverage",
    )
    fixture_tag: str = "FIXTURE_ONLY"


class ComparisonResult(BaseModel):
    """Comparison between baseline and modified environmental runs."""

    model_config = ConfigDict(extra="forbid")

    comparable: bool
    baseline_method: str
    modified_method: str
    grid_hash: str
    weather_hash: str
    baseline_mean: float | None = None
    modified_mean: float | None = None
    delta_mean: float | None = None
    occupied_sensor_area_m2: float | None = Field(
        default=None,
        ge=0.0,
        description="Baseline sensor-cell area excluded by the modified run, when cell areas are present",
    )
    baseline_area_coverage_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    modified_area_coverage_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    direction_of_change: Literal["INCREASED", "DECREASED", "UNCHANGED", "INCOMPARABLE"]
    occupied_points: list[str] = Field(
        default_factory=list,
        description="Sensor IDs that were VALID in baseline but EXCLUDED in modified (displaced by new buildings)",
    )
    rejection_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class E1ScenarioInputBinding(BaseModel):
    """Immutable identity of one scenario and its resolved analysis domain."""

    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    scenario_revision: int = Field(ge=1)
    scenario_payload_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    geometry_artifact_id: str
    geometry_artifact_revision: int = Field(ge=1)
    geometry_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    public_space_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    domain_sources_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class E1ExperimentPlan(BaseModel):
    """Experiment plan definition for E1 Sunlight / Shadow analysis.

    Requires explicit Founder approval for official evaluation.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    name: str = "Rotterdam M4H Direct Sunlight Analysis (E1)"
    status: Literal["DRAFT_UNAPPROVED", "PENDING_FOUNDER_APPROVAL", "APPROVED", "REJECTED", "FIXTURE_ONLY"] = "PENDING_FOUNDER_APPROVAL"
    period: AnalysisPeriod
    location: SiteLocation
    grid_definition: GroundGridDefinition
    baseline_scenario_id: str | None = "scenario-baseline"
    modified_scenario_id: str | None = "scenario-proposal-m4h"
    accuracy_rule: str = Field(
        default="timestep=4, surface_offset=0.05m, spacing=5.0m",
        description="Explicit simulation resolution and accuracy parameters",
    )
    true_north_offset_deg: float = Field(
        default=-0.753,
        description="Grid convergence angle from EPSG:28992 Grid North to True North in degrees (clockwise positive)",
    )
    founder_approval_ref: str | None = Field(
        default=None, description="Reference to approved HumanDecision when officially authorized"
    )
    founder_decision_id: str | None = None
    frozen_inputs: list[E1ScenarioInputBinding] = Field(default_factory=list)
    comparison_domain: str = E1_PUBLIC_SPACE_DOMAIN_DEFINITION
    notes: str = Field(
        default="Founder approval required for official design evaluation. Fixture execution permitted for pipeline testing.",
        description="Governance notice",
    )

    @property
    def is_executable(self) -> bool:
        """Permit approved runs and clearly labelled draft/fixture previews.

        DRAFT_UNAPPROVED permits only a provisional preview. It does not mark the
        plan approved or authorize the result as accepted evidence.
        """
        return self.status in ("APPROVED", "FIXTURE_ONLY", "DRAFT_UNAPPROVED")


class ColormapBin(BaseModel):
    """Discrete bin for uniform sunlight colormap rendering."""

    model_config = ConfigDict(extra="forbid")

    min_hours: float = Field(ge=0.0)
    max_hours: float = Field(ge=0.0)
    color_hex: str = Field(description="Hex color code, e.g. #001f3f")
    label: str = Field(description="Human-readable bin label, e.g. '0 - 2h'")


class ColormapSpec(BaseModel):
    """Uniform colormap specification ensuring identical color scale across baseline and modified runs."""

    model_config = ConfigDict(extra="forbid")

    min_value: float = Field(ge=0.0, default=0.0)
    max_value: float = Field(ge=0.0, default=10.0)
    unit: str = Field(default="hours")
    bins: list[ColormapBin]
    palette_name: str = "sunlight_amber_indigo"


class E1SunlightStatistics(BaseModel):
    """Informational per-scheme sunlight statistics for a single local date."""

    model_config = ConfigDict(extra="forbid")

    date: date
    sensor_count: int = Field(gt=0)
    mean_hours: float = Field(ge=0.0)
    median_hours: float = Field(ge=0.0)
    sensors_at_least_2_hours: int = Field(ge=0)
    sensors_at_least_2_hours_pct: float = Field(ge=0.0, le=100.0)
    sensors_at_least_2_hours_note: str = (
        "Reference statistic only. This is not a regulatory determination."
    )
    domain_area_m2: float = Field(gt=0.0)


PipelineExecutionStatus = Literal["SUCCESS", "BLOCKED", "FAIL", "NOT_READY"]


class E1PipelineRunResult(BaseModel):
    """Complete output bundle from an E1 end-to-end pipeline run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: PipelineExecutionStatus
    blocked_reason: str | None = None
    plan: E1ExperimentPlan
    method: Literal["ladybug_radiance", "pure_python_box_ray"] = "ladybug_radiance"
    engine: str = "ladybug-sunpath+python-raycast"
    baseline_sunlight: SunlightSimulationResult | None = None
    modified_sunlight: SunlightSimulationResult | None = None
    baseline_march_21_statistics: E1SunlightStatistics | None = None
    modified_march_21_statistics: E1SunlightStatistics | None = None
    comparison: ComparisonResult | None = None
    colormap_spec: ColormapSpec | None = None
    tool_execution: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None
    evidence_card: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
