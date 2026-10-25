"""Synthetic geometry checks for the KB4 morphology measurement functions."""

from shapely.geometry import LineString, box

from scripts.precedent_morphometrics import calculate_metrics, merge_touching_buildings


def test_synthetic_gsi_fsi_and_floor_coverage():
    area = box(0, 0, 100, 100)
    buildings = [{"geometry": box(10, 10, 15, 15), "area_m2": 25.0, "levels": 2.0}]
    result = calculate_metrics(
        area,
        buildings,
        [],
        [],
        [],
        lambda x, y, z=None: (x, y) if z is None else (x, y, z),
        height_source="synthetic levels",
        snapshot_date="synthetic fixture",
    )
    assert result["GSI"] == 0.0025
    assert result["FSI_known_floor_area_lower_bound"] == 0.005
    assert result["L_area_weighted_known_building_floors"] == 2.0
    assert result["OSR_from_measured_GSI_and_known_FSI"] == 199.5
    assert result["height_coverage_ratio"] == 1.0
    assert result["GSI_gross_water_inclusive"] == result["GSI"]
    assert result["FSI_comparability_status"] == "COMPARABLE"


def test_unobserved_floors_leave_fsi_and_osr_unavailable():
    area = box(0, 0, 100, 100)
    buildings = [{"geometry": box(10, 10, 15, 15), "area_m2": 25.0, "levels": None}]
    result = calculate_metrics(
        area,
        buildings,
        [],
        [],
        [],
        lambda x, y, z=None: (x, y) if z is None else (x, y, z),
        height_source="synthetic no heights",
        snapshot_date="synthetic fixture",
    )
    assert result["GSI"] == 0.0025
    assert result["FSI_known_floor_area_lower_bound"] is None
    assert result["OSR_from_measured_GSI_and_known_FSI"] is None
    assert result["height_coverage_ratio"] == 0.0
    assert result["FSI_comparability_status"] == "NOT_AVAILABLE"


def test_synthetic_streets_split_four_blocks_and_report_edges():
    area = box(0, 0, 300, 300)
    roads = [
        LineString([(100, 0), (100, 300)]), LineString([(200, 0), (200, 300)]),
        LineString([(0, 100), (300, 100)]), LineString([(0, 200), (300, 200)]),
    ]
    result = calculate_metrics(
        area,
        [],
        roads,
        [],
        [],
        lambda x, y, z=None: (x, y) if z is None else (x, y, z),
        height_source="synthetic none",
        snapshot_date="synthetic fixture",
    )
    assert result["block_count"] == 9
    assert result["complete_block_count"] == 1
    assert result["block_area_m2"]["median"] == 10000.0
    assert result["block_edge_length_m"]["median"] == 100.0


def test_mapped_water_is_removed_from_land_denominators_and_gross_values_remain_visible():
    area = box(0, 0, 100, 100)
    land = area.difference(box(0, 0, 10, 100))
    buildings = [{"geometry": box(20, 20, 30, 30), "area_m2": 100.0, "levels": 3.0}]
    result = calculate_metrics(
        area,
        buildings,
        [],
        [],
        [],
        lambda x, y, z=None: (x, y) if z is None else (x, y, z),
        height_source="synthetic levels",
        snapshot_date="synthetic fixture",
        land_area=land,
        water_area_geoms=[box(0, 0, 10, 100)],
    )
    assert result["mapped_water_area_m2"] == 1000.0
    assert result["land_area_m2"] == 9000.0
    assert result["GSI"] == 0.0111
    assert result["FSI_known_floor_area_lower_bound"] == 0.0333
    assert result["GSI_gross_water_inclusive"] == 0.01
    assert result["FSI_gross_water_inclusive_lower_bound"] == 0.03


def test_touching_unit_footprints_are_merged_for_mass_depth():
    buildings = [
        {"id": "way/1", "geometry": box(0, 0, 4, 12), "area_m2": 48.0, "levels": 3.0, "tags": {"building": "house"}},
        {"id": "way/2", "geometry": box(4.3, 0, 8.3, 12), "area_m2": 48.0, "levels": 3.0, "tags": {"building": "house"}},
        {"id": "way/3", "geometry": box(8.7, 0, 12.7, 12), "area_m2": 48.0, "levels": 3.0, "tags": {"building": "house"}},
    ]
    masses = merge_touching_buildings(buildings, tolerance_m=0.5)
    assert len(masses) == 1
    assert masses[0]["constituent_count"] == 3
    assert masses[0]["geometry"].bounds == (0.0, 0.0, 12.7, 12.0)


def test_auxiliary_shed_is_excluded_from_wing_depth_but_kept_in_gsi():
    area = box(0, 0, 100, 100)
    buildings = [
        {"id": "way/1", "geometry": box(10, 10, 30, 30), "area_m2": 400.0, "levels": 2.0, "tags": {"building": "apartments"}},
        {"id": "way/2", "geometry": box(50, 50, 54, 54), "area_m2": 16.0, "levels": 1.0, "tags": {"building": "shed"}},
    ]
    result = calculate_metrics(
        area,
        buildings,
        [],
        [],
        [],
        lambda x, y, z=None: (x, y) if z is None else (x, y, z),
        height_source="synthetic building types",
        snapshot_date="synthetic fixture",
    )
    assert result["building_count"] == 2
    assert result["principal_building_count_for_form"] == 1
    assert result["accessory_building_count_excluded_from_form_metrics"] == 1
    assert result["GSI"] == 0.0416
    assert result["building_wing_depth_proxy_m"]["sample_count"] == 1
    assert result["building_wing_depth_proxy_m"]["median"] == 10.0


def test_small_fragments_are_reported_and_excluded_from_block_count():
    area = box(0, 0, 100, 100)
    roads = [LineString([(5, 0), (5, 100)]), LineString([(0, 50), (100, 50)])]
    result = calculate_metrics(
        area,
        [],
        roads,
        [],
        [],
        lambda x, y, z=None: (x, y) if z is None else (x, y, z),
        height_source="synthetic none",
        snapshot_date="synthetic fixture",
    )
    assert result["block_count"] == 2
    assert result["small_block_fragment_count_excluded_under_1000m2"] == 2
    assert result["small_block_fragment_total_area_excluded_m2"] == 500.0


def test_wing_depth_diagnostic_reports_low_proxies_and_small_masses_without_filtering():
    area = box(0, 0, 100, 100)
    buildings = [
        {"id": "way/1", "geometry": box(10, 10, 12, 15), "area_m2": 10.0, "levels": 2.0, "tags": {"building": "yes"}},
        {"id": "way/2", "geometry": box(40, 40, 50, 50), "area_m2": 100.0, "levels": 2.0, "tags": {"building": "apartments"}},
    ]
    result = calculate_metrics(
        area,
        buildings,
        [],
        [],
        [],
        lambda x, y, z=None: (x, y) if z is None else (x, y, z),
        height_source="synthetic levels",
        snapshot_date="synthetic fixture",
    )
    assert result["building_wing_depth_proxy_under_4m_sample_count"] == 1
    assert result["building_wing_depth_proxy_under_4m_sample_share"] == 0.5
    assert result["principal_mass_under_100m2_sample_count"] == 1
    assert result["principal_mass_under_100m2_sample_share"] == 0.5
    assert result["building_wing_depth_proxy_m"]["sample_count"] == 2
