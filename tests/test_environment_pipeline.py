"""Comprehensive pipeline, geometry conversion, True North, and fixture tests for W6-11 E1."""

from __future__ import annotations

from datetime import date
import pytest
from shapely.geometry import Polygon

from urban_design.environment.contracts import (
    AnalysisPeriod,
    E1ExperimentPlan,
    GroundGridDefinition,
    Obstacle,
    SensorPoint,
    SiteLocation,
)
from urban_design.environment.geometry_adapter import (
    compute_grid_convergence_deg,
    extract_building_footprints,
    footprint_to_obstacle,
    massing_to_obstacles,
    obstacle_to_2d_footprint,
    rotate_geometry_2d,
    rotate_point_2d,
    validate_coordinate_units,
    verify_geometry_roundtrip,
)
from urban_design.environment.pipeline import run_e1_environment_pipeline
from urban_design.environment.sunlight import (
    calculate_direct_sunlight_hours,
    create_sunlight_colormap_spec,
    generate_sun_vectors,
    get_rotterdam_m4h_demo_location,
    is_radiance_available,
)
from urban_design.models import Artifact, EvidenceCard, ToolExecution


@pytest.fixture
def m4h_location() -> SiteLocation:
    """Rotterdam M4H demo location."""
    return get_rotterdam_m4h_demo_location()


@pytest.fixture
def summer_solstice_period() -> AnalysisPeriod:
    """Midsummer daytime window: 8:00 to 18:00 CEST (10 hours)."""
    return AnalysisPeriod(
        start_date=date(2026, 6, 21),
        end_date=date(2026, 6, 21),
        start_hour=8.0,
        end_hour=18.0,
        timestep=4,
    )


# =========================================================================
# 1. Units and Spatial Preconditions
# =========================================================================

def test_unit_validation_strict() -> None:
    """Simulation requires metres ('m'); fails closed on other or empty units."""
    assert validate_coordinate_units("m") == "m"
    assert validate_coordinate_units("metre") == "m"
    assert validate_coordinate_units("meters") == "m"

    with pytest.raises(ValueError, match="simulation requires metres"):
        validate_coordinate_units("ft")

    with pytest.raises(ValueError, match="simulation requires metres"):
        validate_coordinate_units("cm")

    with pytest.raises(ValueError, match="Coordinate unit is required"):
        validate_coordinate_units("")

    with pytest.raises(ValueError, match="Coordinate unit is required"):
        validate_coordinate_units(None)


# =========================================================================
# 2. True North & Grid Convergence (EPSG:28992)
# =========================================================================

def test_grid_convergence_rotterdam_m4h(m4h_location: SiteLocation) -> None:
    """Verify meridian convergence angle for Rotterdam M4H centroid in EPSG:28992.

    Central meridian: 5.387639° E
    M4H centroid: ~4.430540° E, ~51.907921° N
    Delta lon = -0.957099°
    sin(51.907921°) ~ 0.787018
    Convergence = -0.957099 * 0.787018 = -0.753254°
    """
    gamma = compute_grid_convergence_deg(m4h_location.longitude, m4h_location.latitude)
    assert pytest.approx(gamma, abs=0.01) == -0.753
    assert gamma < 0.0, "For longitudes west of Amersfoort (5.39°E), convergence must be negative"


def test_true_north_vector_rotation(m4h_location: SiteLocation, summer_solstice_period: AnalysisPeriod) -> None:
    """True North rotation shifts sun azimuths deterministically."""
    # Sun vectors without rotation (True North = Grid North)
    v_raw = generate_sun_vectors(m4h_location, summer_solstice_period, true_north_offset_deg=0.0)
    # Sun vectors with Rotterdam convergence (-0.753°)
    v_rot = generate_sun_vectors(m4h_location, summer_solstice_period, true_north_offset_deg=-0.753)

    assert len(v_raw) == len(v_rot)
    for (_, v0, alt0, az0), (_, v1, alt1, az1) in zip(v_raw, v_rot):
        assert alt0 == pytest.approx(alt1, abs=1e-5)
        # Azimuth relative to grid north: az_grid = (az_true - (-0.753)) = az_true + 0.753
        expected_az = (az0 - (-0.753)) % 360.0
        assert az1 == pytest.approx(expected_az, abs=1e-4)


# =========================================================================
# 3. Asymmetric Geometry Conversion & Roundtrip Verification
# =========================================================================

def test_asymmetric_l_shaped_footprint_roundtrip() -> None:
    """Asymmetric L-shaped footprint converts to 3D Obstacle and reconstructs within 1e-6 m tolerance."""
    l_footprint = [
        (0.0, 0.0),
        (40.0, 0.0),
        (40.0, 15.0),
        (20.0, 15.0),
        (20.0, 35.0),
        (0.0, 35.0),
    ]
    height = 21.0  # 7 floors * 3m
    report = verify_geometry_roundtrip(l_footprint, height_m=height, base_z=0.0, tolerance_m=1e-6)

    assert report["roundtrip_passed"] is True
    # Area: 40*15 + 20*20 = 600 + 400 = 1000 m2
    assert report["original_area_m2"] == 1000.0
    assert report["reconstructed_area_m2"] == 1000.0
    assert report["area_diff_m2"] < 1e-6
    assert report["perimeter_diff_m"] < 1e-6
    assert report["max_coordinate_error_m"] < 1e-6
    # Horizontal surfaces are triangulated so concave roof faces remain exact.
    assert report["faces_generated"] > 8


def test_asymmetric_u_shaped_footprint_roundtrip() -> None:
    """Asymmetric U-shaped courtyard building converts and reconstructs accurately."""
    u_footprint = [
        (0.0, 0.0),
        (50.0, 0.0),
        (50.0, 40.0),
        (35.0, 40.0),
        (35.0, 15.0),
        (15.0, 15.0),
        (15.0, 40.0),
        (0.0, 40.0),
    ]
    report = verify_geometry_roundtrip(u_footprint, height_m=15.0, tolerance_m=1e-6)
    assert report["roundtrip_passed"] is True
    assert report["faces_generated"] > 10


def test_massing_setbacks_conversion() -> None:
    """Multi-floor setbacks convert each floor level into separate Obstacle prisms."""
    massing_with_setbacks = {
        "id": "stepped_tower",
        "height_m": 24.0,
        "floors": [
            # Podium: levels 0-2 (0-9m), 30x30m
            {
                "floor_height_m": 9.0,
                "geometry": {"coordinates": [[(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)]]},
            },
            # Tower setback: levels 3-6 (9-24m), 15x15m
            {
                "floor_height_m": 15.0,
                "geometry": {"coordinates": [[(7.5, 7.5), (22.5, 7.5), (22.5, 22.5), (7.5, 22.5)]]},
            },
        ],
    }
    obstacles = massing_to_obstacles([massing_with_setbacks])
    assert len(obstacles) == 2
    assert obstacles[0].obstacle_id == "stepped_tower_fl0"
    assert obstacles[1].obstacle_id == "stepped_tower_fl1"

    fps = extract_building_footprints(obstacles)
    assert len(fps) == 2
    # Podium footprint area = 900 m2
    assert fps[0].area == 900.0
    # Setback tower footprint area = 225 m2
    assert fps[1].area == 225.0


# =========================================================================
# 4. Asymmetric Building Simulation: Radiance matches Pure Python
# =========================================================================

def test_asymmetric_building_radiance_matches_pure_python(
    m4h_location: SiteLocation, summer_solstice_period: AnalysisPeriod
) -> None:
    """An asymmetric L-shaped building produces matching sunlight hours in Radiance and Python."""
    if not is_radiance_available():
        pytest.skip("Radiance runtime not available")

    # L-shaped building footprint
    l_footprint = [
        (10.0, 10.0),
        (30.0, 10.0),
        (30.0, 20.0),
        (20.0, 20.0),
        (20.0, 30.0),
        (10.0, 30.0),
    ]
    obs = footprint_to_obstacle(l_footprint, height_m=15.0, obstacle_id="l_bldg")

    # Sensors north and east of building
    sensors = [
        SensorPoint.create(x=15.0, y=35.0, z=0.0, surface_offset=0.05),  # In north shadow
        SensorPoint.create(x=35.0, y=15.0, z=0.0, surface_offset=0.05),  # East
        SensorPoint.create(x=5.0, y=15.0, z=0.0, surface_offset=0.05),   # West
        SensorPoint.create(x=15.0, y=5.0, z=0.0, surface_offset=0.05),   # South (unshaded)
    ]

    res_py = calculate_direct_sunlight_hours(
        location=m4h_location,
        period=summer_solstice_period,
        sensor_points=sensors,
        obstacles=[obs],
        method="pure_python_box_ray",
    )
    res_rad = calculate_direct_sunlight_hours(
        location=m4h_location,
        period=summer_solstice_period,
        sensor_points=sensors,
        obstacles=[obs],
        method="ladybug_radiance",
    )

    assert len(res_py.results) == len(res_rad.results)
    for p_py, p_rad in zip(res_py.results, res_rad.results):
        assert p_py.point_id == p_rad.point_id
        assert p_py.visible_samples == p_rad.visible_samples
        assert p_py.sunlight_hours == p_rad.sunlight_hours


# =========================================================================
# 5. Founder Point Gate: Unapproved Plan BLOCKED
# =========================================================================

def test_pipeline_unapproved_plan_blocked() -> None:
    """Stop loss: Unapproved plan must return status=BLOCKED without faking approval."""
    loc = get_rotterdam_m4h_demo_location()
    unapproved_plan = E1ExperimentPlan(
        plan_id="e1-unapproved",
        status="PENDING_FOUNDER_APPROVAL",
        period=AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=8.0,
            end_hour=18.0,
            timestep=1,
        ),
        location=loc,
        grid_definition=GroundGridDefinition(origin_x=0.0, origin_y=0.0, spacing_m=10.0),
    )
    boundary = Polygon([(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)])

    res = run_e1_environment_pipeline(
        plan=unapproved_plan,
        baseline_geometry=[],
        modified_geometry=[],
        boundary_polygon=boundary,
        method="pure_python_box_ray",
    )

    assert res.status == "BLOCKED"
    assert "FOUNDER_APPROVAL_REQUIRED" in (res.blocked_reason or "")
    assert res.baseline_sunlight is None
    assert res.modified_sunlight is None


# =========================================================================
# 6. End-to-End Headless Pipeline Execution (Fixture mode)
# =========================================================================

def test_pipeline_fixture_mode_headless_success() -> None:
    """Fixture mode allows headless execution, comparing baseline vs modified."""
    loc = get_rotterdam_m4h_demo_location()
    gamma = compute_grid_convergence_deg(loc.longitude, loc.latitude)
    fixture_plan = E1ExperimentPlan(
        plan_id="e1-fixture-test",
        status="FIXTURE_ONLY",
        period=AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=10.0,
            end_hour=14.0,  # 4 hours
            timestep=1,
        ),
        location=loc,
        grid_definition=GroundGridDefinition(origin_x=0.0, origin_y=0.0, spacing_m=10.0),
        true_north_offset_deg=gamma,
    )
    boundary = Polygon([(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)])

    # Baseline: Low 5m building in south
    baseline_bldg = [
        {
            "id": "bldg_base",
            "height_m": 5.0,
            "footprint": {"coordinates": [[(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)]]},
        }
    ]

    # Modified: Tall 30m tower in south (casts deep shadow to the north) + building footprint in north
    modified_bldg = [
        {
            "id": "tower_tall",
            "height_m": 30.0,
            "footprint": {"coordinates": [[(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)]]},
        },
        {
            "id": "bldg_new_north",
            "height_m": 10.0,
            "footprint": {"coordinates": [[(30.0, 30.0), (40.0, 30.0), (40.0, 40.0), (30.0, 40.0)]]},
        },
    ]

    res = run_e1_environment_pipeline(
        plan=fixture_plan,
        baseline_geometry=baseline_bldg,
        modified_geometry=modified_bldg,
        boundary_polygon=boundary,
        method="pure_python_box_ray",
    )

    assert res.status == "SUCCESS"
    assert res.comparison is not None
    assert res.comparison.comparable is True
    # Tall tower reduces ground sunlight -> direction is DECREASED
    assert res.comparison.direction_of_change == "DECREASED"
    assert res.comparison.delta_mean is not None and res.comparison.delta_mean < 0.0

    # The paired comparison uses only common public space, so the sensor on the
    # modified building footprint is outside that domain and is not compared.
    assert "pt_30.0_30.0_0.0" not in res.metadata["paired_sensor_ids"]
    assert res.comparison.metadata["paired_domain"] == "COMMON_OVERLAP"

    # Validate generated domain models
    assert res.tool_execution is not None
    tool_model = ToolExecution.model_validate(res.tool_execution)
    assert tool_model.status.value == "SUCCEEDED"

    assert res.artifact is not None
    art_model = Artifact.model_validate(res.artifact)
    assert art_model.type == "sunlight_simulation_result"

    assert res.evidence_card is not None
    evidence_model = EvidenceCard.model_validate(res.evidence_card)
    assert evidence_model.metric.unit == "hours"
    assert evidence_model.claim.statement is not None

    # Check colormap specification
    assert res.colormap_spec is not None
    assert res.colormap_spec.min_value == 0.0
    assert res.colormap_spec.max_value >= 4.0
    assert len(res.colormap_spec.bins) == 5


def test_pipeline_radiance_execution_if_available() -> None:
    """Execute real headless pipeline with Radiance 6.0.2."""
    if not is_radiance_available():
        pytest.skip("Radiance runtime not available")

    loc = get_rotterdam_m4h_demo_location()
    fixture_plan = E1ExperimentPlan(
        plan_id="e1-radiance-test",
        status="FIXTURE_ONLY",
        period=AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=11.0,
            end_hour=13.0,
            timestep=1,
        ),
        location=loc,
        grid_definition=GroundGridDefinition(origin_x=0.0, origin_y=0.0, spacing_m=10.0),
    )
    boundary = Polygon([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])

    res = run_e1_environment_pipeline(
        plan=fixture_plan,
        baseline_geometry=[],
        modified_geometry=[],
        boundary_polygon=boundary,
        method="ladybug_radiance",
    )

    assert res.status == "SUCCESS"
    assert res.baseline_sunlight is not None
    assert res.baseline_sunlight.daytime_hours == 2.0
    assert res.comparison is not None
    assert res.comparison.direction_of_change == "UNCHANGED"


# =========================================================================
# 7. Uniform Colormap Specification
# =========================================================================

def test_colormap_spec_uniformity() -> None:
    """Baseline and modified results share the exact same colormap scale."""
    cm = create_sunlight_colormap_spec(max_hours=10.0, num_bins=5)
    assert cm.min_value == 0.0
    assert cm.max_value == 10.0
    assert cm.unit == "hours"
    assert len(cm.bins) == 5
    assert cm.bins[0].min_hours == 0.0
    assert cm.bins[0].max_hours == 2.0
    assert cm.bins[4].max_hours == 10.0


# =========================================================================
# 8. Independent Router Module Endpoints (W6-2 Integration Contract)
# =========================================================================

def test_environment_router_endpoints() -> None:
    """Verify independent router endpoints can be mounted in FastAPI."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from urban_design.environment.router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. /api/environment/runtimes selects Radiance only after manifest verification.
    r_runtimes = client.get("/api/environment/runtimes")
    assert r_runtimes.status_code == 200
    data_runtimes = r_runtimes.json()
    expected_engine = (
        "ladybug-sunpath+ladybug-radiance"
        if data_runtimes["radiance_available"]
        else "ladybug-sunpath+python-raycast"
    )
    assert data_runtimes["engine"] == expected_engine
    assert data_runtimes["engine_available"] is True
    assert data_runtimes["grid_convergence_m4h_deg"] == pytest.approx(-0.73916, abs=1e-4)

    # 2. Default plan is visibly a draft and includes its selected local dates.
    r_plan_draft = client.get("/api/environment/e1/plan")
    assert r_plan_draft.status_code == 200
    assert r_plan_draft.json()["status"] == "DRAFT_UNAPPROVED"
    assert r_plan_draft.json()["period"]["dates"] == ["2026-03-21", "2026-06-21", "2026-12-21"]

    # 3. The pending official and isolated fixture contracts remain distinct.
    r_plan_off = client.get("/api/environment/e1/plan?mode=official")
    assert r_plan_off.json()["status"] == "PENDING_FOUNDER_APPROVAL"
    r_plan_fix = client.get("/api/environment/e1/plan?mode=fixture")
    assert r_plan_fix.status_code == 200
    assert r_plan_fix.json()["status"] == "FIXTURE_ONLY"

    # 4. /api/environment/e1/demo-fixtures remains explicitly location-only.
    r_fixtures = client.get("/api/environment/e1/demo-fixtures")
    assert r_fixtures.status_code == 200
    data_fix = r_fixtures.json()
    assert "DEMO_LOCATION_NOT_ANALYSIS_RESULT" in data_fix["disclaimer"]
    assert data_fix["asymmetric_roundtrip_verification"]["roundtrip_passed"] is True


def test_environment_router_is_mounted_by_workspace_api(tmp_path) -> None:
    from urban_design.api import create_workspace_app
    from urban_design.store import ProjectStateStore

    store = ProjectStateStore(tmp_path / "environment-api-copy.sqlite3")
    app = create_workspace_app(
        store=store,
        scenario_artifact_root=tmp_path / "scenario-artifacts",
        context_data_dir=tmp_path / "context-data",
    )

    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            plan = client.get("/api/environment/e1/plan")
            runtime = client.get("/api/environment/runtimes")
        assert plan.status_code == 200
        assert plan.json()["status"] == "DRAFT_UNAPPROVED"
        assert runtime.status_code == 200
        runtime_data = runtime.json()
        expected_engine = (
            "ladybug-sunpath+ladybug-radiance"
            if runtime_data["radiance_available"]
            else "ladybug-sunpath+python-raycast"
        )
        assert runtime_data["engine"] == expected_engine
    finally:
        store.close()
