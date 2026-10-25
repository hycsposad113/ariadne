"""Deterministic, fixture-only morphology metrics."""

from .metrics import (
    FIXTURE_ONLY,
    FarBoundCheck,
    FloorPlate,
    MetricValidationError,
    MorphologyMetrics,
    RetainedBuilding,
    Zone,
    allocate_floor_area_by_zone,
    calculate_coverage,
    calculate_far,
    calculate_gfa,
    calculate_height,
    calculate_morphology_metrics,
    evaluate_far_upper_bound,
)
from .contracts import (
    FixtureGenerationInput,
    GeneratedBuilding,
    MorphologyGenerationError,
    NonBuildableArea,
    RoadSegment,
    StrategyCandidate,
    StrategyGenerationResult,
)
from .strategies import generate_fixture_strategies, strategy_catalog_v1

__all__ = [
    "FIXTURE_ONLY",
    "FixtureGenerationInput",
    "GeneratedBuilding",
    "FarBoundCheck",
    "FloorPlate",
    "MetricValidationError",
    "MorphologyMetrics",
    "MorphologyGenerationError",
    "NonBuildableArea",
    "RoadSegment",
    "RetainedBuilding",
    "StrategyCandidate",
    "StrategyGenerationResult",
    "Zone",
    "allocate_floor_area_by_zone",
    "calculate_coverage",
    "calculate_far",
    "calculate_gfa",
    "calculate_height",
    "calculate_morphology_metrics",
    "evaluate_far_upper_bound",
    "generate_fixture_strategies",
    "strategy_catalog_v1",
]
