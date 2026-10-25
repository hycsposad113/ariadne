"""Tests for fabric open space sunlight analysis script and helpers."""

from __future__ import annotations

from datetime import date
import json
import pytest
from shapely.geometry import Polygon

from urban_design.environment.contracts import AnalysisPeriod, Obstacle, SensorPoint
from urban_design.environment.geometry_adapter import (
    compute_grid_convergence_deg,
    footprint_to_obstacle,
)
from urban_design.environment.sunlight import (
    calculate_direct_sunlight_hours,
    get_rotterdam_m4h_demo_location,
    is_radiance_available,
)


def ear_clip_polygon(polygon: Polygon) -> list[Polygon]:
    """Triangulate a 2D polygon using ear clipping."""
    coords = list(polygon.exterior.coords)[:-1]
    if len(coords) < 3:
        return []
    area = sum(
        coords[i][0] * coords[(i + 1) % len(coords)][1]
        - coords[(i + 1) % len(coords)][0] * coords[i][1]
        for i in range(len(coords))
    )
    if area < 0:
        coords.reverse()

    def is_convex(p_prev, p_curr, p_next):
        return (p_curr[0] - p_prev[0]) * (p_next[1] - p_prev[1]) - (
            p_curr[1] - p_prev[1]
        ) * (p_next[0] - p_prev[0]) > 1e-9

    def point_in_triangle(pt, a, b, c):
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

        d1, d2, d3 = sign(pt, a, b), sign(pt, b, c), sign(pt, c, a)
        return not (
            (d1 < -1e-9 or d2 < -1e-9 or d3 < -1e-9)
            and (d1 > 1e-9 or d2 > 1e-9 or d3 > 1e-9)
        )

    vertices = list(coords)
    triangles: list[Polygon] = []
    it = 0
    max_iter = len(vertices) * len(vertices)
    while len(vertices) > 2 and it < max_iter:
        it += 1
        n = len(vertices)
        ear_found = False
        for i in range(n):
            p_prev, p_curr, p_next = vertices[(i - 1) % n], vertices[i], vertices[(i + 1) % n]
            if not is_convex(p_prev, p_curr, p_next):
                continue
            if any(
                point_in_triangle(vertices[j], p_prev, p_curr, p_next)
                for j in range(n)
                if j not in ((i - 1) % n, i, (i + 1) % n)
            ):
                continue
            triangles.append(Polygon([p_prev, p_curr, p_next]))
            vertices.pop(i)
            ear_found = True
            break
        if not ear_found:
            break
    return triangles


def test_mock_building_shading_reduces_sunlight_hours() -> None:
    """Mock scenario: Sensor point behind a 15m building receives less sunlight than unshaded point."""
    loc = get_rotterdam_m4h_demo_location()
    gamma = compute_grid_convergence_deg(loc.longitude, loc.latitude)

    # Building at [0, 10] x [0, 10], height 15m
    bldg_poly = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    bldg_obs = footprint_to_obstacle(bldg_poly, height_m=15.0, obstacle_id="test_bldg")

    # Sensor A: North of the building (in shade for mid-latitude solar noon)
    pt_shaded = SensorPoint.create(x=5.0, y=14.0, z=0.5, surface_offset=0.05)
    # Sensor B: Far south of the building (unobstructed full sun)
    pt_unshaded = SensorPoint.create(x=5.0, y=-25.0, z=0.5, surface_offset=0.05)

    period = AnalysisPeriod(
        start_date=date(2026, 3, 21),
        end_date=date(2026, 3, 21),
        dates=[date(2026, 3, 21)],
        start_hour=8.0,
        end_hour=18.0,
        timestep=4,
    )

    method = "ladybug_radiance" if is_radiance_available() else "pure_python_box_ray"
    res = calculate_direct_sunlight_hours(
        location=loc,
        period=period,
        sensor_points=[pt_shaded, pt_unshaded],
        obstacles=[bldg_obs],
        method=method,
        true_north_offset_deg=gamma,
    )

    hours_map = {pt.point_id: pt.sunlight_hours for pt in res.results}
    shaded_hours = hours_map[pt_shaded.point_id]
    unshaded_hours = hours_map[pt_unshaded.point_id]

    assert unshaded_hours > 0.0, "Unshaded point should receive direct sunlight"
    assert shaded_hours < unshaded_hours, (
        f"Shaded point ({shaded_hours} h) must have fewer hours than unshaded ({unshaded_hours} h)"
    )


def test_ear_clip_polygon_exact_area() -> None:
    """Ear clipping preserves area and decomposes a concave polygon."""
    # Concave L-shaped polygon
    l_poly = Polygon([(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)])
    triangles = ear_clip_polygon(l_poly)
    assert len(triangles) == 4
    total_tri_area = sum(t.area for t in triangles)
    assert pytest.approx(total_tri_area, abs=1e-6) == l_poly.area


def test_per_courtyard_sunlight_aggregation_is_additive(tmp_path) -> None:
    from types import SimpleNamespace
    from scripts.e1_fabric_sunlight import summarize_per_courtyard, write_per_courtyard_json

    output_dir = tmp_path / 'e1'
    output_dir.mkdir()
    comparison = output_dir / 'comparison_table.json'
    original = b'[{"fabric_id":"harbour_grain","category":"all"}]'
    comparison.write_bytes(original)
    days = {
        '2026-03-21': [SimpleNamespace(point_id='p1', sunlight_hours=4.0),
                       SimpleNamespace(point_id='p2', sunlight_hours=6.0),
                       SimpleNamespace(point_id='p3', sunlight_hours=2.0)],
        '2026-06-21': [SimpleNamespace(point_id='p1', sunlight_hours=8.0),
                       SimpleNamespace(point_id='p2', sunlight_hours=6.0),
                       SimpleNamespace(point_id='p3', sunlight_hours=4.0)],
        '2026-12-21': [SimpleNamespace(point_id='p1', sunlight_hours=2.0),
                       SimpleNamespace(point_id='p2', sunlight_hours=0.0),
                       SimpleNamespace(point_id='p3', sunlight_hours=3.0)],
    }
    records = summarize_per_courtyard(
        'harbour_grain', ['court-a', 'court-b'], {'p1': 'court-a', 'p2': 'court-a', 'p3': 'court-b'},
        days, cell_area_m2=25,
    )
    write_per_courtyard_json(output_dir, records)
    assert json.loads((output_dir / 'per_courtyard.json').read_text()) == [
        {'fabric_id': 'harbour_grain', 'courtyard_id': 'court-a', 'points': 2, 'area_m2': 50,
         'spring_mean': 5.0, 'summer_mean': 7.0, 'winter_mean': 1.0, 'winter_ge_2h_pct': 50.0},
        {'fabric_id': 'harbour_grain', 'courtyard_id': 'court-b', 'points': 1, 'area_m2': 25,
         'spring_mean': 2.0, 'summer_mean': 4.0, 'winter_mean': 3.0, 'winter_ge_2h_pct': 100.0},
    ]
    assert comparison.read_bytes() == original


def test_courtyard_sensor_assignment_uses_plan_id_and_courtyard_id():
    from scripts.e1_fabric_sunlight import assign_courtyard_sensor_points
    sensors = [SensorPoint.create(x=5, y=5, z=0.5), SensorPoint.create(x=25, y=5, z=0.5)]
    courtyards = [
        {'id': 'plan-court-a', 'geometry': {'type': 'Polygon', 'coordinates': [[
            [0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}},
        {'geometry': {'type': 'Polygon', 'coordinates': [[
            [20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]]},
         'properties': {'courtyard_id': 'property-court-b'}},
    ]
    assignments = assign_courtyard_sensor_points(
        sensors, {sensors[0].point_id: 'courtyards', sensors[1].point_id: 'courtyards'}, courtyards)
    assert assignments == {sensors[0].point_id: 'plan-court-a', sensors[1].point_id: 'property-court-b'}
