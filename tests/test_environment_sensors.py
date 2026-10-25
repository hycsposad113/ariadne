"""Tests for ground sensor grid generation, exclusion masks, and area-weighted aggregation (W6 precursor lane F3)."""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from urban_design.environment.contracts import SensorPoint
from urban_design.environment.sensors import (
    compute_area_weighted_metric,
    create_sensor_grid_result,
    generate_ground_sensor_grid,
)


def test_hand_calculated_area_weighted_metric() -> None:
    """Fixture: Known area and values grid, area-weighted mean matches exact hand calculation."""
    # 4 points, spacing 10m -> each cell area = 100 m2
    # Values: 2.0, 4.0, 6.0, 8.0 -> hand mean = (200 + 400 + 600 + 800) / 400 = 5.0
    pts = [
        SensorPoint.create(x=0.0, y=0.0, cell_area_m2=100.0),
        SensorPoint.create(x=10.0, y=0.0, cell_area_m2=100.0),
        SensorPoint.create(x=0.0, y=10.0, cell_area_m2=100.0),
        SensorPoint.create(x=10.0, y=10.0, cell_area_m2=100.0),
    ]
    values = {
        pts[0].point_id: 2.0,
        pts[1].point_id: 4.0,
        pts[2].point_id: 6.0,
        pts[3].point_id: 8.0,
    }

    mean, total_int, total_area = compute_area_weighted_metric(pts, values)
    assert total_area == 400.0
    assert total_int == 2000.0
    assert mean == 5.0


def test_excluded_points_omitted_from_area_weighted_average() -> None:
    """Excluded points are NOT factored into the area-weighted average or valid area."""
    pts = [
        SensorPoint.create(x=0.0, y=0.0, cell_area_m2=50.0, status="VALID"),
        SensorPoint.create(x=10.0, y=0.0, cell_area_m2=50.0, status="VALID"),
        SensorPoint.create(x=20.0, y=0.0, cell_area_m2=50.0, status="EXCLUDED_INSIDE_FOOTPRINT"),
    ]
    values = {
        pts[0].point_id: 10.0,
        pts[1].point_id: 20.0,
        pts[2].point_id: 999.0,  # Excluded point value must not pollute result
    }

    mean, total_int, total_area = compute_area_weighted_metric(pts, values)
    assert total_area == 100.0
    assert total_int == 1500.0  # 50*10 + 50*20
    assert mean == 15.0


def test_grid_generation_and_moving_building_preserves_unaffected_point_ids() -> None:
    """Fixture: Moving a building footprint alters status of affected points while preserving unchanged IDs."""
    boundary = Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])
    origin = (0.0, 0.0)
    spacing = 10.0

    # Baseline: building in southwest quadrant [15, 35] x [15, 35]
    footprint_base = Polygon([(15.0, 15.0), (35.0, 15.0), (35.0, 35.0), (15.0, 35.0)])
    grid_base = generate_ground_sensor_grid(
        boundary=boundary,
        spacing_m=spacing,
        origin=origin,
        building_footprints=[footprint_base],
    )

    # Modified: building moved to northeast quadrant [65, 85] x [65, 85]
    footprint_mod = Polygon([(65.0, 65.0), (85.0, 65.0), (85.0, 85.0), (65.0, 85.0)])
    grid_mod = generate_ground_sensor_grid(
        boundary=boundary,
        spacing_m=spacing,
        origin=origin,
        building_footprints=[footprint_mod],
    )

    assert len(grid_base) == len(grid_mod)

    base_map = {p.point_id: p for p in grid_base}
    mod_map = {p.point_id: p for p in grid_mod}

    # All point IDs match across the grid
    assert set(base_map.keys()) == set(mod_map.keys())

    # Points far from both buildings (e.g. (0,0), (0,10), (90,10)) maintain VALID status and identical ID
    assert base_map["pt_0.0_0.0_0.0"].status == "VALID"
    assert mod_map["pt_0.0_0.0_0.0"].status == "VALID"

    # A point inside the baseline footprint: (20, 20)
    pt_sw = "pt_20.0_20.0_0.0"
    assert base_map[pt_sw].status == "EXCLUDED_INSIDE_FOOTPRINT"
    assert mod_map[pt_sw].status == "VALID"  # Freed in modified

    # A point inside the modified footprint: (70, 70)
    pt_ne = "pt_70.0_70.0_0.0"
    assert base_map[pt_ne].status == "VALID"
    assert mod_map[pt_ne].status == "EXCLUDED_INSIDE_FOOTPRINT"  # Occupied by new building


def test_sensor_grid_result_structure() -> None:
    boundary = Polygon([(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)])
    footprint = Polygon([(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)])
    pts = generate_ground_sensor_grid(boundary=boundary, spacing_m=10.0, building_footprints=[footprint])

    values = {p.point_id: 6.0 for p in pts}
    res = create_sensor_grid_result(points=pts, values=values, spacing_m=10.0)

    assert res.total_points == len(pts)
    assert res.valid_points + res.excluded_points == res.total_points
    assert res.coverage_ratio == pytest.approx(res.valid_points / res.total_points, rel=1e-5)
    assert res.fixture_tag == "FIXTURE_ONLY"
