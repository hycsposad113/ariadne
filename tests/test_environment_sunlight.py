"""Tests for direct sunlight hour simulation and contracts (W6 precursor lane F2)."""

from __future__ import annotations

import warnings
import zoneinfo
from datetime import date, datetime, timedelta, time
import pytest

from urban_design.environment.contracts import (
    AnalysisPeriod,
    Obstacle,
    SensorPoint,
    SiteLocation,
)
from urban_design.environment.sunlight import (
    calculate_direct_sunlight_hours,
    check_point_inside_box,
    generate_sun_vectors,
    get_rotterdam_m4h_demo_location,
    is_radiance_available,
    ray_box_intersection,
)


@pytest.fixture
def amsterdam_location() -> SiteLocation:
    """Standard Amsterdam fixture location."""
    return SiteLocation(
        latitude=52.37,
        longitude=4.89,
        elevation=0.0,
        timezone="Europe/Amsterdam",
        location_tag="FIXTURE_ONLY",
    )


def test_site_location_validation() -> None:
    loc = SiteLocation(latitude=52.0, longitude=4.5, timezone="Europe/Amsterdam")
    assert loc.latitude == 52.0
    assert loc.timezone == "Europe/Amsterdam"

    with pytest.raises(ValueError, match="Invalid IANA timezone"):
        SiteLocation(latitude=52.0, longitude=4.5, timezone="Invalid/Timezone")

    with pytest.raises(ValueError):
        SiteLocation(latitude=95.0, longitude=4.5, timezone="Europe/Amsterdam")


def test_analysis_period_validation() -> None:
    p = AnalysisPeriod(
        start_date=date(2026, 6, 21),
        end_date=date(2026, 6, 21),
        start_hour=8.0,
        end_hour=18.0,
        timestep=4,
    )
    assert p.timestep == 4

    with pytest.raises(ValueError, match="start_date .* must be <= end_date"):
        AnalysisPeriod(
            start_date=date(2026, 6, 22),
            end_date=date(2026, 6, 21),
            start_hour=8.0,
            end_hour=18.0,
        )

    with pytest.raises(ValueError, match="start_hour .* must be < end_hour"):
        AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=18.0,
            end_hour=8.0,
        )


def test_sensor_point_offset_and_deterministic_id() -> None:
    pt = SensorPoint.create(x=10.0, y=20.0, z=0.0, surface_offset=0.05)
    assert pt.point_id == "pt_10.0_20.0_0.0"
    assert pt.status == "VALID"

    # Surface offset <= 0 warning
    with pytest.warns(UserWarning, match="surface_offset is 0.0"):
        SensorPoint.create(x=1.0, y=2.0, surface_offset=0.0)

    # Surface offset < 0 rejected by schema
    with pytest.raises(ValueError):
        SensorPoint.create(x=1.0, y=2.0, surface_offset=-0.05)


def test_fixture_unobstructed_horizontal_plane(amsterdam_location: SiteLocation) -> None:
    """Fixture: Unobstructed horizontal plane sunlight hours equals daylight duration in window."""
    # Midsummer daytime window: 10:00 to 16:00 (6 hours)
    period = AnalysisPeriod(
        start_date=date(2026, 6, 21),
        end_date=date(2026, 6, 21),
        start_hour=10.0,
        end_hour=16.0,
        timestep=4,
    )
    pt = SensorPoint.create(x=0.0, y=0.0, z=0.0, surface_offset=0.05)

    res_py = calculate_direct_sunlight_hours(
        location=amsterdam_location,
        period=period,
        sensor_points=[pt],
        obstacles=[],
        method="pure_python_box_ray",
    )
    assert res_py.results[0].sunlight_hours == 6.0
    assert res_py.daytime_hours == 6.0

    if is_radiance_available():
        res_rad = calculate_direct_sunlight_hours(
            location=amsterdam_location,
            period=period,
            sensor_points=[pt],
            obstacles=[],
            method="ladybug_radiance",
        )
        assert res_rad.results[0].sunlight_hours == 6.0
    else:
        pytest.skip("Radiance not available for ladybug_radiance test")


def test_fixture_known_occlusion_winter_solstice(amsterdam_location: SiteLocation) -> None:
    """Fixture: On winter solstice noon, a high wall south of sensor shades the point."""
    # Amsterdam winter solstice noon (approx 12:40 local, solar altitude ~14.2 deg, azimuth ~180 deg)
    period = AnalysisPeriod(
        start_date=date(2026, 12, 21),
        end_date=date(2026, 12, 21),
        start_hour=12.0,
        end_hour=13.0,
        timestep=4,
    )
    sensor = SensorPoint.create(x=0.0, y=0.0, z=0.0, surface_offset=0.05)

    # High wall south of sensor: y in [-3, -1], spanning x [-10, 10], height 10m
    wall = Obstacle(
        obstacle_id="south_wall_fixture",
        kind="BOX_AABB",
        source="FIXTURE_ONLY",
        geometry_hash="sha256:wallfixture",
        bounds=(-10.0, -3.0, 0.0, 10.0, -1.0, 10.0),
    )

    res_py = calculate_direct_sunlight_hours(
        location=amsterdam_location,
        period=period,
        sensor_points=[sensor],
        obstacles=[wall],
        method="pure_python_box_ray",
    )
    # The wall completely blocks the south sun at noon
    assert res_py.results[0].visible_samples == 0
    assert res_py.results[0].sunlight_hours == 0.0

    if is_radiance_available():
        res_rad = calculate_direct_sunlight_hours(
            location=amsterdam_location,
            period=period,
            sensor_points=[sensor],
            obstacles=[wall],
            method="ladybug_radiance",
        )
        assert res_rad.results[0].visible_samples == 0
        assert res_rad.results[0].sunlight_hours == 0.0


def test_fixture_nighttime_zero(amsterdam_location: SiteLocation) -> None:
    """Fixture: Night hours produce exactly 0 sunlight hours."""
    period = AnalysisPeriod(
        start_date=date(2026, 6, 21),
        end_date=date(2026, 6, 21),
        start_hour=23.0,
        end_hour=24.0,
        timestep=1,
    )
    sensor = SensorPoint.create(x=0.0, y=0.0, z=0.0)
    res = calculate_direct_sunlight_hours(
        location=amsterdam_location,
        period=period,
        sensor_points=[sensor],
        obstacles=[],
        method="pure_python_box_ray",
    )
    assert res.total_sun_vectors == 0
    assert res.daytime_hours == 0.0
    assert res.results[0].sunlight_hours == 0.0


def test_fixture_daylight_saving_transition_dates() -> None:
    """Fixture: DST transition days in Europe/Amsterdam (2026-03-29 and 2026-10-25).

    Verifies local to UTC conversions do not gain or lose an hour.
    """
    tz = zoneinfo.ZoneInfo("Europe/Amsterdam")
    utc = zoneinfo.ZoneInfo("UTC")

    # Spring forward: 2026-03-29
    # At 02:00 local, clock leaps to 03:00. Day duration is 23 physical hours.
    d_spring = date(2026, 3, 29)
    dt_spring_start = datetime.combine(d_spring, time(0, 0), tzinfo=tz)
    dt_spring_end = datetime.combine(d_spring + timedelta(days=1), time(0, 0), tzinfo=tz)
    spring_hours = (dt_spring_end.astimezone(utc) - dt_spring_start.astimezone(utc)).total_seconds() / 3600.0
    assert spring_hours == 23.0, f"Expected 23 physical hours on spring forward, got {spring_hours}"

    # Fall back: 2026-10-25
    # At 03:00 local, clock jumps back to 02:00. Day duration is 25 physical hours.
    d_fall = date(2026, 10, 25)
    dt_fall_start = datetime.combine(d_fall, time(0, 0), tzinfo=tz)
    dt_fall_end = datetime.combine(d_fall + timedelta(days=1), time(0, 0), tzinfo=tz)
    fall_hours = (dt_fall_end.astimezone(utc) - dt_fall_start.astimezone(utc)).total_seconds() / 3600.0
    assert fall_hours == 25.0, f"Expected 25 physical hours on fall back, got {fall_hours}"

    # Verify sun vectors generated on DST days
    loc = SiteLocation(latitude=52.37, longitude=4.89, timezone="Europe/Amsterdam")
    p_spring = AnalysisPeriod(start_date=d_spring, end_date=d_spring, start_hour=8.0, end_hour=16.0, timestep=1)
    vectors_spring = generate_sun_vectors(loc, p_spring)
    # Between 8:00 and 16:00 is 8 daytime hours
    assert len(vectors_spring) == 8


def test_fixture_timestep_convergence_and_boundedness(amsterdam_location: SiteLocation) -> None:
    """Fixture: Timesteps 1, 4, 12 converge and results never exceed period length."""
    # Analysis period of 10 hours
    period_hours = 10.0
    wall = Obstacle(
        obstacle_id="obst",
        kind="BOX_AABB",
        source="FIXTURE_ONLY",
        geometry_hash="sha256:box",
        bounds=(-2.0, -5.0, 0.0, 2.0, -3.0, 4.0),
    )
    pt = SensorPoint.create(x=0.0, y=0.0, z=0.0, surface_offset=0.05)

    results_by_timestep = {}
    for ts in (1, 4, 12):
        p = AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=8.0,
            end_hour=18.0,
            timestep=ts,
        )
        res = calculate_direct_sunlight_hours(
            location=amsterdam_location,
            period=p,
            sensor_points=[pt],
            obstacles=[wall],
            method="pure_python_box_ray",
        )
        hours = res.results[0].sunlight_hours
        assert 0.0 <= hours <= period_hours, f"Hours {hours} exceeded period {period_hours}"
        results_by_timestep[ts] = hours

    # As timestep refines from 1 to 4 to 12, results are stable within discrete step tolerance
    assert abs(results_by_timestep[4] - results_by_timestep[12]) < 0.5


def test_fixture_sensor_inside_obstacle_rejected(amsterdam_location: SiteLocation) -> None:
    """Fixture: Sensor point located inside an obstacle geometry is rejected with ValueError."""
    box = Obstacle(
        obstacle_id="building_a",
        kind="BOX_AABB",
        source="FIXTURE_ONLY",
        geometry_hash="sha256:bldga",
        bounds=(0.0, 0.0, 0.0, 10.0, 10.0, 15.0),
    )
    inside_pt = SensorPoint.create(x=5.0, y=5.0, z=2.0)
    period = AnalysisPeriod(
        start_date=date(2026, 6, 21),
        end_date=date(2026, 6, 21),
        start_hour=10.0,
        end_hour=12.0,
    )

    with pytest.raises(ValueError, match="is inside obstacle"):
        calculate_direct_sunlight_hours(
            location=amsterdam_location,
            period=period,
            sensor_points=[inside_pt],
            obstacles=[box],
            method="pure_python_box_ray",
        )


def test_fixture_primary_method_matches_independent_reference(amsterdam_location: SiteLocation) -> None:
    """Fixture: Primary method (Radiance) and independent reference (Python ray-box) match exactly."""
    if not is_radiance_available():
        pytest.skip("Radiance runtime not available, skipping primary method comparison.")

    # Multi-point setup around a box obstacle
    box = Obstacle(
        obstacle_id="block_b",
        kind="BOX_AABB",
        source="FIXTURE_ONLY",
        geometry_hash="sha256:bldgb",
        bounds=(-3.0, -6.0, 0.0, 3.0, -2.0, 5.0),
    )
    points = [
        SensorPoint.create(x=0.0, y=0.0, z=0.0, surface_offset=0.05),   # North of box
        SensorPoint.create(x=0.0, y=-10.0, z=0.0, surface_offset=0.05), # South of box
        SensorPoint.create(x=10.0, y=0.0, z=0.0, surface_offset=0.05),  # East of box
    ]
    period = AnalysisPeriod(
        start_date=date(2026, 6, 21),
        end_date=date(2026, 6, 21),
        start_hour=8.0,
        end_hour=18.0,
        timestep=4,
    )

    res_py = calculate_direct_sunlight_hours(
        location=amsterdam_location,
        period=period,
        sensor_points=points,
        obstacles=[box],
        method="pure_python_box_ray",
    )
    res_rad = calculate_direct_sunlight_hours(
        location=amsterdam_location,
        period=period,
        sensor_points=points,
        obstacles=[box],
        method="ladybug_radiance",
    )

    assert len(res_py.results) == len(res_rad.results)
    for p_py, p_rad in zip(res_py.results, res_rad.results):
        assert p_py.point_id == p_rad.point_id
        assert p_py.visible_samples == p_rad.visible_samples
        assert p_py.sunlight_hours == p_rad.sunlight_hours
    mean_absolute_delta = sum(
        abs(p_py.sunlight_hours - p_rad.sunlight_hours)
        for p_py, p_rad in zip(res_py.results, res_rad.results)
    ) / len(res_py.results)
    assert mean_absolute_delta <= 0.25


def test_rotterdam_m4h_demo_location_tag() -> None:
    """Verify demo location has proper disclaimer tag and correct coordinates."""
    demo_loc = get_rotterdam_m4h_demo_location()
    assert "位置示範，非分析結果" in demo_loc.location_tag
    assert 51.9 <= demo_loc.latitude <= 52.0
    assert 4.4 <= demo_loc.longitude <= 4.5
