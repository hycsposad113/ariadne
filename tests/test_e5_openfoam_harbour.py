"""Tests for E5 OpenFOAM Harbour screening geometry and domain calculations.

Validates STL extrusion facet count, watertightness, and domain bounds logic without running OpenFOAM.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from scripts.e5_openfoam_harbour import (
    DEFAULT_H,
    check_watertight,
    compute_domain_bounds,
    earclip_polygon,
    extrude_polygon_to_stl_facets,
    parse_epw_wind_data,
    EPW_PATH,
)


def test_earclip_simple_polygon():
    # Square: 4 vertices -> 2 triangles
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    triangles, ccw_pts = earclip_polygon(square)
    assert len(triangles) == 2
    assert len(ccw_pts) == 4

    # L-shaped polygon (non-convex): 6 vertices -> 4 triangles
    l_shape = [
        (0.0, 0.0),
        (20.0, 0.0),
        (20.0, 10.0),
        (10.0, 10.0),
        (10.0, 20.0),
        (0.0, 20.0),
    ]
    triangles_l, ccw_pts_l = earclip_polygon(l_shape)
    assert len(triangles_l) == 4
    assert len(ccw_pts_l) == 6


def test_extrude_polygon_facets_and_watertightness():
    # Test rectangle extrusion
    rect = [(0.0, 0.0), (30.0, 0.0), (30.0, 15.0), (0.0, 15.0)]
    height = 18.0
    facets = extrude_polygon_to_stl_facets(rect, height=height)

    # For N=4 vertices:
    # Bottom: N-2 = 2 triangles
    # Top: N-2 = 2 triangles
    # Side walls: 2N = 8 triangles
    # Total = 4N - 4 = 12 triangles
    assert len(facets) == 12

    # Check watertightness: every edge must have multiplicity exactly 2
    is_watertight, non_manifold_count, total = check_watertight(facets)
    assert is_watertight is True
    assert non_manifold_count == 0
    assert total == 12


def test_extrude_non_convex_polygon_watertightness():
    # Test L-shaped building extrusion
    l_shape = [
        (0.0, 0.0),
        (25.0, 0.0),
        (25.0, 10.0),
        (12.0, 10.0),
        (12.0, 20.0),
        (0.0, 20.0),
    ]
    height = 20.7
    facets = extrude_polygon_to_stl_facets(l_shape, height=height)

    # N=6 vertices: 4N - 4 = 20 triangles
    assert len(facets) == 20

    is_watertight, non_manifold_count, total = check_watertight(facets)
    assert is_watertight is True
    assert non_manifold_count == 0
    assert total == 20


def test_domain_bounds_calculation():
    # Synthetic cluster bounds: x from -100 to 200 (width 300), y from -50 to 150 (depth 200)
    pts = np.array([
        [-100.0, -50.0],
        [200.0, -50.0],
        [200.0, 150.0],
        [-100.0, 150.0],
    ])
    H = 20.0
    domain = compute_domain_bounds(pts, H=H)

    # Upstream: xmin - 5H = -100 - 100 = -200
    # Downstream: xmax + 15H = 200 + 300 = 500
    # Lateral: ymin - 5H = -50 - 100 = -150; ymax + 5H = 150 + 100 = 250
    # Height: zmax = 6H = 120
    assert domain["xmin"] <= -100.0 - 5.0 * H
    assert domain["xmax"] >= 200.0 + 15.0 * H
    assert domain["ymin"] <= -50.0 - 5.0 * H
    assert domain["ymax"] >= 150.0 + 5.0 * H
    assert domain["zmin"] == 0.0
    assert domain["zmax"] == 6.0 * H  # exactly 120m for H=20m


def test_weather_parsing():
    import os
    if os.path.exists(EPW_PATH):
        res = parse_epw_wind_data(EPW_PATH)
        assert res["total_hours"] >= 8760
        selected = res["selected_4_winds"]
        assert set(selected.keys()) == {"SW", "W", "S", "NW"}
        for k in ["SW", "W", "S", "NW"]:
            assert selected[k]["mean_speed_10m"] > 0
            assert selected[k]["frequency_pct"] > 0


def test_log_law_scaling():
    from scripts.e5_openfoam_harbour import log_law_scale_pedestrian_wind

    # When zp <= 1.5, should return directly
    assert math.isclose(log_law_scale_pedestrian_wind(3.0, 1.2, z0=0.5, z_target=1.5), 3.0)
    assert math.isclose(log_law_scale_pedestrian_wind(3.0, 1.5, z0=0.5, z_target=1.5), 3.0)

    # When zp = 6.0m (z0=0.5): ln(2/0.5)/ln(6.5/0.5) = ln(4)/ln(13) ~ 0.5405
    u_scaled = log_law_scale_pedestrian_wind(5.34, 6.0, z0=0.5, z_target=1.5)
    expected = 5.34 * math.log(2.0 / 0.5) / math.log(6.5 / 0.5)
    assert math.isclose(u_scaled, expected, rel_tol=1e-5)
    assert 2.8 <= u_scaled <= 2.9


def test_outdoor_mask_excludes_buildings():
    from shapely.geometry import Polygon
    from scripts.e5_openfoam_harbour import get_site_outdoor_mask

    site = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    # Building in the middle: 30 to 70
    bldg = {
        "geometry": Polygon([(30, 30), (70, 30), (70, 70), (30, 70)]),
        "is_harbour": True,
    }
    bounds = (0.0, 0.0, 100.0, 100.0)
    shape = (100, 100)

    mask = get_site_outdoor_mask(site, [bldg], bounds, shape, buffer_dist=0.0)

    # Check center (building interior) is False
    assert not mask[50, 50]
    # Check outside building but inside site is True (e.g. at (10, 10))
    # In pixel coords: x=10 -> col=10; y=10 -> row=90 (since py inverts y)
    assert mask[90, 10]


