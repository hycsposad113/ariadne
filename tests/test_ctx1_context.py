"""Tests for CTX1 context morphology reading pure functions and end-to-end synthetic evaluation."""

from __future__ import annotations

import math
from shapely.geometry import LineString, Polygon, box

from scripts.ctx1_context_morphology import (
    build_context_facts,
    build_context_summary_zh,
    render_alignments_zh,
    render_figure_ground_zh,
)
from urban_design.morphology.context_reading import (
    analyze_block_distribution,
    angle_difference_deg,
    calculate_polygon_mrr_dimensions,
    classify_dominant_typology,
    compute_fsi_and_floors,
    compute_gsi,
    compute_intersection_density,
    compute_orientation_peaks,
    compute_site_principal_axis,
    compute_typical_street_spacing,
    compute_wing_depths,
    cut_blocks_from_network,
    find_continuation_street_candidates,
    normalize_azimuth_deg,
    segment_azimuth_deg,
)


def test_azimuth_and_angle_difference():
    # North segment: azimuth = 0
    assert segment_azimuth_deg((0, 0), (0, 10)) == 0.0
    # East segment: azimuth = 90
    assert segment_azimuth_deg((0, 0), (10, 0)) == 90.0
    # South segment: undirected line azimuth = 0
    assert segment_azimuth_deg((0, 10), (0, 0)) == 0.0
    # Northeast (45 deg)
    assert math.isclose(segment_azimuth_deg((0, 0), (10, 10)), 45.0, abs_tol=1e-3)

    # Angle differences
    assert angle_difference_deg(10.0, 30.0) == 20.0
    assert angle_difference_deg(10.0, 170.0) == 20.0  # 180 - 160 = 20
    assert angle_difference_deg(5.0, 95.0) == 90.0


def test_orientation_peaks_orthogonal_grid():
    # Create grid with lines at 30 deg and 120 deg
    rad1 = math.radians(30.0)
    rad2 = math.radians(120.0)
    lines: list[LineString] = []

    # 10 lines along 30 deg
    for i in range(10):
        dx = 100.0 * math.sin(rad1)
        dy = 100.0 * math.cos(rad1)
        lines.append(LineString([(i * 20.0, 0.0), (i * 20.0 + dx, dy)]))

    # 10 lines along 120 deg
    for i in range(10):
        dx = 80.0 * math.sin(rad2)
        dy = 80.0 * math.cos(rad2)
        lines.append(LineString([(0.0, i * 20.0), (dx, i * 20.0 + dy)]))

    peak1, peak2, hist = compute_orientation_peaks(lines, bin_size_deg=5.0, min_separation_deg=25.0)
    assert abs(peak1 - 30.0) <= 5.0
    assert abs(peak2 - 120.0) <= 5.0
    assert len(hist) > 0


def test_orientation_peaks_are_unknown_without_road_segments():
    peak1, peak2, hist = compute_orientation_peaks([])
    assert peak1 is None
    assert peak2 is None
    assert hist == []


def test_cut_blocks_from_network_and_distribution():
    # Window 200m x 200m
    window = box(0, 0, 200, 200)
    # 2 horizontal roads, 2 vertical roads dividing window into 9 blocks
    roads = [
        LineString([(-10, 60), (210, 60)]),
        LineString([(-10, 140), (210, 140)]),
        LineString([(60, -10), (60, 210)]),
        LineString([(140, -10), (140, 210)]),
    ]
    # No water
    blocks = cut_blocks_from_network(window, roads, water_polygons=None, min_block_area_m2=50.0)
    assert len(blocks) == 9

    stats = analyze_block_distribution(blocks, window)
    assert stats["total_blocks"] == 9
    # Only the center block (60..140, 60..140) doesn't touch the outer boundary
    assert stats["complete_blocks"] == 1
    # Central block size 80x80 = 6400 m2
    assert stats["area_m2"]["median"] > 0
    assert stats["short_edge_m"]["median"] > 0


def test_gsi_water_subtraction_denominator():
    # Study window: 100m x 100m = 10,000 m2
    window = box(0, 0, 100, 100)
    # Water: 100m x 40m = 4,000 m2
    water = [box(0, 0, 100, 40)]
    # Land area is 10,000 - 4,000 = 6,000 m2

    # Buildings: two 30m x 40m buildings on land (y from 40 to 100)
    # Footprint = 2 * (30 * 40) = 2,400 m2
    b1 = box(10, 50, 40, 90)
    b2 = box(60, 50, 90, 90)

    res = compute_gsi(window, [b1, b2], water)
    assert res["window_area_m2"] == 10000.0
    assert res["water_area_m2"] == 4000.0
    assert res["land_area_m2"] == 6000.0
    assert res["building_footprint_m2"] == 2400.0
    # GSI = 2400 / 6000 = 0.400
    assert math.isclose(res["gsi"], 0.400, abs_tol=1e-3)


def test_gsi_is_unknown_when_window_has_no_land():
    window = box(0, 0, 100, 100)
    res = compute_gsi(window, [], [window])
    assert res["land_area_m2"] == 0.0
    assert res["gsi"] is None


def test_wing_depths():
    # 2 buildings:
    # b1: 15m x 60m (depth 15m, area 900)
    # b2: 12m x 50m (depth 12m, area 600)
    # b_small: 4m x 10m (area 40 < 50m2, should be excluded)
    b1 = box(0, 0, 15, 60)
    b2 = box(100, 100, 150, 112)
    b_small = box(200, 200, 204, 210)

    res = compute_wing_depths([b1, b2, b_small], min_area_m2=50.0)
    assert res["count"] == 2
    # Short edges: 15.0 and 12.0 -> median 13.5
    assert math.isclose(res["median_m"], 13.5, abs_tol=0.2)


def test_fsi_and_floors():
    land_area = 10000.0
    # Residential: floor height = 3.0 m
    # Building 1: footprint 1000 m2, height 12.0m -> 4 floors -> GFA 4000 m2
    # Building 2: footprint 500 m2, height 9.0m -> 3 floors -> GFA 1500 m2
    buildings_meta = [
        {"area_m2": 1000.0, "height_m": 12.0, "height_source": "3DBAG", "is_industrial": False},
        {"area_m2": 500.0, "height_m": 9.0, "height_source": "3DBAG", "is_industrial": False},
    ]
    res_res = compute_fsi_and_floors(buildings_meta, land_area, is_industrial=False)
    # Total GFA = 5500 m2 -> FSI = 0.55
    assert math.isclose(res_res["fsi"], 0.55, abs_tol=0.01)
    # Avg floors = 5500 / 1500 = 3.67
    assert math.isclose(res_res["average_floors"], 3.7, abs_tol=0.1)

    # Industrial: floor height = 5.0 m
    # Shed: footprint 4000 m2, height 10.0m -> 2 floors -> GFA 8000 m2
    industrial_meta = [
        {"area_m2": 4000.0, "height_m": 10.0, "height_source": "3DBAG", "is_industrial": True},
    ]
    res_ind = compute_fsi_and_floors(industrial_meta, land_area, is_industrial=True)
    # FSI = 8000 / 10000 = 0.80
    assert math.isclose(res_ind["fsi"], 0.80, abs_tol=0.01)
    assert math.isclose(res_ind["average_floors"], 2.0, abs_tol=0.1)


def test_fsi_is_unknown_when_3dbag_heights_are_missing():
    res = compute_fsi_and_floors(
        [{"area_m2": 1000.0}, {"area_m2": 500.0, "building_levels": 9}],
        land_area_m2=10000.0,
    )
    assert res["status"] == "UNKNOWN"
    assert res["fsi"] is None
    assert res["average_floors"] is None
    assert res["height_coverage_ratio"] == 0.0


def test_fsi_ignores_height_values_without_3dbag_provenance():
    res = compute_fsi_and_floors(
        [{"area_m2": 1000.0, "height_m": 12.0, "height_source": "OpenStreetMap"}],
        land_area_m2=10000.0,
    )
    assert res["status"] == "UNKNOWN"
    assert res["fsi"] is None


def test_fsi_is_unknown_when_use_class_does_not_support_floor_height():
    res = compute_fsi_and_floors(
        [{"area_m2": 1000.0, "height_m": 12.0, "height_source": "3DBAG WFS"}],
        land_area_m2=10000.0,
    )
    assert res["status"] == "UNKNOWN"
    assert res["average_floors"] is None


def test_intersection_density_and_spacing():
    # 3x3 road grid on 1000m x 1000m area (1 km2)
    # 4 horizontal roads at y = 100, 400, 700, 1000
    # 4 vertical roads at x = 100, 400, 700, 1000
    roads: list[LineString] = []
    for y in [100, 400, 700, 1000]:
        roads.append(LineString([(50, y), (1050, y)]))
    for x in [100, 400, 700, 1000]:
        roads.append(LineString([(x, 50), (x, 1050)]))

    land_area = 1_000_000.0  # 1 km2
    count, density = compute_intersection_density(roads, land_area)
    assert count == 16  # 4 x 4 crossings
    assert density == 16.0

    # Spacing for East-West roads (azimuth = 90 deg)
    spacing = compute_typical_street_spacing(roads, peak_azimuth_deg=90.0, tolerance_deg=10.0)
    assert spacing["samples_count"] > 0
    # Spacing between 100, 400, 700 is 300m
    assert math.isclose(spacing["median_m"], 300.0, abs_tol=5.0)

    no_spacing = compute_typical_street_spacing([], peak_azimuth_deg=0.0)
    assert no_spacing["median_m"] is None


def test_dominant_typology_classification():
    # Port warehouse
    typ, desc = classify_dominant_typology(gsi=0.45, avg_floors=1.8, wing_depth_median=35.0, median_block_area_m2=20000.0, large_footprint_ratio=0.55, is_port_industrial=True)
    assert "廠房" in typ or "倉庫" in typ

    # Spangen perimeter block
    typ_peri, _ = classify_dominant_typology(gsi=0.48, avg_floors=4.2, wing_depth_median=14.0, median_block_area_m2=6500.0, large_footprint_ratio=0.05, is_port_industrial=False)
    assert "周邊式" in typ_peri

    # Slab block
    typ_slab, _ = classify_dominant_typology(gsi=0.28, avg_floors=5.0, wing_depth_median=13.0, median_block_area_m2=8000.0, large_footprint_ratio=0.05, is_port_industrial=False)
    assert "板樓" in typ_slab

    typ_unknown, _ = classify_dominant_typology(
        gsi=0.0,
        avg_floors=None,
        wing_depth_median=0.0,
        median_block_area_m2=0.0,
        large_footprint_ratio=0.0,
    )
    assert typ_unknown == "UNKNOWN"


def test_continuation_street_candidates():
    # Site box: 100 to 300 in X, 100 to 300 in Y
    site = box(100, 100, 300, 300)
    # A street from North pointing directly south toward site (x=200, y=500 down to y=350)
    st_north = {
        "name": "North Ave",
        "highway": "secondary",
        "geometry": LineString([(200, 500), (200, 350)]),
    }
    # A distant street 500m away
    st_far = {
        "name": "Far Away Road",
        "highway": "residential",
        "geometry": LineString([(800, 800), (900, 800)]),
    }
    candidates = find_continuation_street_candidates(site, [st_north, st_far], max_search_dist_m=200.0)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["name"] == "North Ave"
    assert c["approach_side"] == "北側"
    assert c["distance_to_site_m"] == 50.0  # 350 - 300 = 50m


def test_parallel_nearby_road_is_not_a_continuation_candidate():
    site = box(100, 100, 300, 300)
    parallel = {
        "name": "Parallel Road",
        "highway": "residential",
        "geometry": LineString([(100, 350), (300, 350)]),
    }
    candidates = find_continuation_street_candidates(site, [parallel], max_search_dist_m=200.0)
    assert candidates == []


def test_end_to_end_synthetic_zone_reading():
    # Synthetic study window 500m x 500m
    window = box(0, 0, 500, 500)
    # Water body covering bottom 100m (0 to 100 in y)
    water = [box(0, 0, 500, 100)]
    # Roads forming 3x3 blocks on land (y between 100 and 500)
    roads = [
        LineString([(0, 200), (500, 200)]),
        LineString([(0, 350), (500, 350)]),
        LineString([(150, 100), (150, 500)]),
        LineString([(350, 100), (350, 500)]),
    ]
    # Buildings on land
    b1 = box(50, 230, 120, 320)
    b2 = box(200, 230, 300, 320)
    b3 = box(380, 230, 460, 320)
    buildings = [b1, b2, b3]

    # 1. Blocks
    blocks = cut_blocks_from_network(window, roads, water, min_block_area_m2=50.0)
    assert len(blocks) >= 4
    block_stats = analyze_block_distribution(blocks, window)
    assert block_stats["total_blocks"] >= 4

    # 2. GSI
    gsi_res = compute_gsi(window, buildings, water)
    assert gsi_res["land_area_m2"] == 200000.0  # 500 * 400
    assert gsi_res["gsi"] > 0.05

    # 3. Orientations
    p1, p2, _ = compute_orientation_peaks(roads)
    assert min(abs(p1 - 0.0), abs(p1 - 90.0)) <= 5.0
    assert min(abs(p2 - 0.0), abs(p2 - 90.0)) <= 5.0

    # 4. Wing depth
    depths = compute_wing_depths(buildings)
    assert depths["count"] == 3
    assert depths["median_m"] > 0.0

    # 5. Typology
    typ, _ = classify_dominant_typology(
        gsi=gsi_res["gsi"],
        avg_floors=3.0,
        wing_depth_median=depths["median_m"],
        median_block_area_m2=block_stats["area_m2"]["median"],
        large_footprint_ratio=0.1,
    )
    assert typ in ("周邊式", "板樓", "廠房 / 倉庫", "點式")


def test_context_facts_builder_runs_on_small_synthetic_features(tmp_path):
    site = box(10000, 10000, 10200, 10200)
    dakpark = box(10600, 10100, 10700, 10200)
    site_facts = {
        "site": {"horizontal_crs": "EPSG:28992", "units": "m"},
        "geometry": {
            "crs": "EPSG:28992",
            "site": {"type": "Polygon", "coordinates": [list(site.exterior.coords)]},
            "water": {"type": "Polygon", "coordinates": [list(box(10000, 10000, 10050, 10200).exterior.coords)]},
            "dakpark": {"type": "Polygon", "coordinates": [list(dakpark.exterior.coords)]},
        },
    }
    features = []
    for y in (8750, 9050, 9350, 9650):
        features.append({"id": f"road-h-{y}", "layer": "highway", "tags": {"highway": "residential"}, "geometry": LineString([(9500, y), (10700, y)])})
    for x in (9700, 10000, 10300):
        features.append({"id": f"road-v-{x}", "layer": "highway", "tags": {"highway": "residential"}, "geometry": LineString([(x, 8500), (x, 9900)])})
    features.extend([
        {"id": "building-a", "layer": "building", "tags": {"building": "apartments"}, "geometry": box(9800, 9100, 9840, 9160)},
        {"id": "building-c", "layer": "building", "tags": {"building": "apartments"}, "geometry": box(9850, 9300, 9870, 9380)},
        {"id": "building-b", "layer": "building", "tags": {"building": "apartments"}, "geometry": box(10100, 9400, 10150, 9460)},
        {"id": "water-a", "layer": "water", "tags": {"natural": "water"}, "geometry": box(9550, 9450, 9650, 9550)},
        {"id": "south-residential", "layer": "landuse", "tags": {"landuse": "residential"}, "geometry": box(9800, 8800, 10000, 9500)},
    ])

    height_features = [{
        "id": "bag-building-a",
        "layer": "building_3dbag",
        "height_source": "3DBAG WFS",
        "height_m": 9.0,
        "tags": {"use": "woonfunctie"},
        "geometry": box(9800, 9100, 9840, 9160),
    }, {
        "id": "bag-building-unclassified",
        "layer": "building_3dbag",
        "height_source": "3DBAG WFS",
        "height_m": 10.0,
        "tags": {"use": "other"},
        "geometry": box(9960, 9200, 9980, 9240),
    }]
    facts = build_context_facts(site_facts, features, request_records=[], height_features=height_features)

    zones = {z["id"]: z for z in facts["texture_zones"]}
    assert {"spangen_bospolder", "m4h_port", "dakpark_vierhavensstraat"}.issubset(zones)
    south = zones["spangen_bospolder"]["metrics"]
    assert south["window_area_m2"] == 140000.0
    assert south["blocks"]["total_blocks"] > 0
    assert south["buildings"]["coverage"]["gsi"] > 0.0
    assert south["buildings"]["fsi"]["status"] == "PARTIAL"
    assert south["buildings"]["fsi"]["average_floors_observed_subset"] == 3.0
    assert facts["boundary_and_alignments"]["dakpark_edge"]["height_difference_m"] is None
    assert facts["boundary_and_alignments"]["dakpark_edge"]["elevation_status"] == "UNKNOWN"
    report = build_context_summary_zh(facts)
    assert "街廓面積中位數 [P25, P75]" in report
    assert "觀測平均樓層" in report
    assert "UNKNOWN" not in report
    render_figure_ground_zh(tmp_path / "figure-ground-zh.png", site_facts, features, facts)
    render_alignments_zh(tmp_path / "alignments-zh.png", site_facts, features, facts)
    assert (tmp_path / "figure-ground-zh.png").stat().st_size < 2 * 1024 * 1024
    assert (tmp_path / "alignments-zh.png").stat().st_size < 2 * 1024 * 1024
