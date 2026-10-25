"""Urban design environment analysis prototype package (W6 precursor lane).

Provides contracts, direct sunlight hour simulation (Radiance or the headless Python E1 screen),
geometry conversion adapters, sensor grids, and comparison rules for environmental indicators.
"""

from __future__ import annotations

from .comparison import (
    IncompatibleComparisonError,
    compare_direction_consistency,
    compare_environmental_runs,
)
from .contracts import (
    AnalysisPeriod,
    ColormapBin,
    ColormapSpec,
    ComparisonResult,
    E1ExperimentPlan,
    E1PipelineRunResult,
    GroundGridDefinition,
    Obstacle,
    PipelineExecutionStatus,
    PointSunlightResult,
    SensorGridResult,
    SensorPoint,
    SiteLocation,
    SunlightSimulationResult,
)
from .geometry_adapter import (
    compute_grid_convergence_deg,
    extract_building_footprints,
    footprint_to_obstacle,
    formal_scenario_geojson_to_environment,
    massing_to_obstacles,
    obstacle_to_2d_footprint,
    rotate_geometry_2d,
    rotate_point_2d,
    validate_coordinate_units,
    verify_geometry_roundtrip,
)
from .pipeline import run_e1_environment_pipeline
from .sensors import (
    compute_area_weighted_metric,
    create_sensor_grid_result,
    generate_ground_sensor_grid,
)
from .sunlight import (
    box_to_face3d_list,
    calculate_direct_sunlight_hours,
    check_point_inside_box,
    check_point_inside_polygon_obstacle,
    create_sunlight_colormap_spec,
    generate_sun_vectors,
    get_rotterdam_m4h_demo_location,
    is_radiance_available,
    pure_python_box_ray_intersection,
    ray_box_intersection,
    ray_polygon_faces_intersection,
    ray_triangle_intersection,
)

__all__ = [
    "AnalysisPeriod",
    "ColormapBin",
    "ColormapSpec",
    "ComparisonResult",
    "E1ExperimentPlan",
    "E1PipelineRunResult",
    "GroundGridDefinition",
    "IncompatibleComparisonError",
    "Obstacle",
    "PipelineExecutionStatus",
    "PointSunlightResult",
    "SensorGridResult",
    "SensorPoint",
    "SiteLocation",
    "SunlightSimulationResult",
    "box_to_face3d_list",
    "calculate_direct_sunlight_hours",
    "check_point_inside_box",
    "check_point_inside_polygon_obstacle",
    "compare_direction_consistency",
    "compare_environmental_runs",
    "compute_area_weighted_metric",
    "compute_grid_convergence_deg",
    "create_sensor_grid_result",
    "create_sunlight_colormap_spec",
    "extract_building_footprints",
    "footprint_to_obstacle",
    "formal_scenario_geojson_to_environment",
    "generate_ground_sensor_grid",
    "generate_sun_vectors",
    "get_rotterdam_m4h_demo_location",
    "is_radiance_available",
    "massing_to_obstacles",
    "obstacle_to_2d_footprint",
    "pure_python_box_ray_intersection",
    "ray_box_intersection",
    "ray_polygon_faces_intersection",
    "ray_triangle_intersection",
    "rotate_geometry_2d",
    "rotate_point_2d",
    "run_e1_environment_pipeline",
    "validate_coordinate_units",
    "verify_geometry_roundtrip",
]
