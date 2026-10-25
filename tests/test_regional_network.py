"""Tests for regional network polygon parsing and boundary containment checks (WC-3)."""

from __future__ import annotations

import json
from pathlib import Path
from shapely.geometry import Point, Polygon, shape

from urban_design.regional_network import (
    parse_poly_file,
    poly_to_rd_new,
    assess_boundary_clearance,
)

ROOT = Path(__file__).resolve().parents[1]
POLY_PATH = ROOT / "artifacts/week4-regional-osm/raw/zuid-holland.poly"
STUDY_AREA_PATH = ROOT / ".urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson"


def test_parse_poly_file_synthetic():
    poly_text = """test_boundary
1
   4.0   51.0
   5.0   51.0
   5.0   52.0
   4.0   52.0
   4.0   51.0
END
END
"""
    geom = parse_poly_file(poly_text)
    assert isinstance(geom, Polygon)
    assert geom.is_valid
    assert geom.area > 0.99 and geom.area < 1.01
    assert geom.contains(Point(4.5, 51.5))


def test_parse_poly_file_with_hole():
    poly_text = """test_with_hole
1
   0.0   0.0
   10.0  0.0
   10.0  10.0
   0.0   10.0
   0.0   0.0
END
!2
   3.0   3.0
   7.0   3.0
   7.0   7.0
   3.0   7.0
   3.0   3.0
END
END
"""
    geom = parse_poly_file(poly_text)
    assert isinstance(geom, Polygon)
    assert geom.is_valid
    assert len(geom.interiors) == 1
    assert geom.contains(Point(1.0, 1.0))
    assert not geom.contains(Point(5.0, 5.0))  # inside hole


def test_zuid_holland_poly_parsing_and_containment():
    if not POLY_PATH.exists():
        return
    poly_wgs84 = parse_poly_file(POLY_PATH)
    assert isinstance(poly_wgs84, (Polygon, type(Polygon())))
    assert poly_wgs84.is_valid

    poly_rd = poly_to_rd_new(poly_wgs84)
    assert poly_rd.is_valid

    if not STUDY_AREA_PATH.exists():
        return
    sa_feat = json.loads(STUDY_AREA_PATH.read_text(encoding="utf-8"))
    sa_geom = shape(sa_feat["geometry"])

    # 4km buffer (for 2km radius)
    res_4km = assess_boundary_clearance(sa_geom, 4000.0, poly_rd)
    assert res_4km["is_fully_contained"] is True
    assert res_4km["readiness"] == "VALIDATED_COVERAGE"
    assert res_4km["provincial_clearance_m"] > 20000.0

    # 6km buffer (for 2km radius comparison)
    res_6km = assess_boundary_clearance(sa_geom, 6000.0, poly_rd)
    assert res_6km["is_fully_contained"] is True
    assert res_6km["readiness"] == "VALIDATED_COVERAGE"

    # 20km buffer (for 10km radius)
    res_20km = assess_boundary_clearance(sa_geom, 20000.0, poly_rd)
    assert res_20km["is_fully_contained"] is True
    assert res_20km["readiness"] == "VALIDATED_COVERAGE"
    assert res_20km["outside_area_m2"] == 0.0


def test_synthetic_boundary_overflow():
    box = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
    center_pt = Point(50, 50)

    # 30m buffer fits completely
    res_in = assess_boundary_clearance(center_pt, 30.0, box)
    assert res_in["is_fully_contained"] is True
    assert res_in["readiness"] == "VALIDATED_COVERAGE"

    # 60m buffer overflows boundary
    res_out = assess_boundary_clearance(center_pt, 60.0, box)
    assert res_out["is_fully_contained"] is False
    assert res_out["readiness"] == "EDGE_AFFECTED_EXTENDS_BEYOND_PROVINCE"
    assert res_out["outside_area_m2"] > 0
    assert res_out["outside_ratio"] > 0


def test_rvv_autoweg_prohibits_pedestrians_and_bicycles():
    from urban_design.regional_network import evaluate_way_for_mode

    # Motorway, trunk, and motorroad=yes (autoweg sign G3) prohibit pedestrians and cyclists
    for hw in ["motorway", "motorway_link", "trunk", "trunk_link"]:
        ped_inc, _, _ = evaluate_way_for_mode({"highway": hw}, "pedestrian")
        bike_inc, _, _ = evaluate_way_for_mode({"highway": hw}, "bicycle")
        car_inc, is_imp, _ = evaluate_way_for_mode({"highway": hw}, "motor_vehicle")
        assert not ped_inc, f"Pedestrian must be prohibited on {hw}"
        assert not bike_inc, f"Bicycle must be prohibited on {hw}"
        assert car_inc, f"Car must be allowed on {hw}"
        assert is_imp, f"Default motor_vehicle on {hw} is imputed"

    # motorroad=yes on primary (autoweg)
    autoweg = {"highway": "primary", "motorroad": "yes"}
    assert not evaluate_way_for_mode(autoweg, "pedestrian")[0]
    assert not evaluate_way_for_mode(autoweg, "bicycle")[0]
    assert evaluate_way_for_mode(autoweg, "motor_vehicle")[0]


def test_rvv_mandatory_sidepath_excludes_bicycle():
    from urban_design.regional_network import evaluate_way_for_mode

    # RVV 1990: sign G11 / G12a requires using sidepath, prohibiting main carriageway
    way = {"highway": "primary", "bicycle": "use_sidepath"}
    bike_inc, _, reason = evaluate_way_for_mode(way, "bicycle")
    assert not bike_inc
    assert "mandatory_sidepath" in reason

    # cycleway=separate or cycleway:both=separate indicates separate track
    for sep_tag in [{"cycleway": "separate"}, {"cycleway:both": "separate"}, {"cycleway:left": "track"}]:
        way_sep = {"highway": "secondary", **sep_tag}
        assert not evaluate_way_for_mode(way_sep, "bicycle")[0]


def test_rvv_fietsstraat_priority():
    from urban_design.regional_network import evaluate_way_for_mode

    for tag in [{"cyclestreet": "yes"}, {"bicycle_road": "yes"}]:
        way = {"highway": "residential", **tag}
        bike_inc, is_imp, reason = evaluate_way_for_mode(way, "bicycle")
        assert bike_inc
        assert not is_imp  # Explicit fietsstraat tag is not imputed
        assert "fietsstraat" in reason


def test_motor_vehicle_service_driveway_and_parking_aisle_exclusion():
    from urban_design.regional_network import evaluate_way_for_mode

    for s_type in ["driveway", "parking_aisle", "drive-through"]:
        way = {"highway": "service", "service": s_type}
        car_inc, _, reason = evaluate_way_for_mode(way, "motor_vehicle")
        assert not car_inc
        assert s_type in reason

    # General service road (not driveway/parking_aisle) is included
    general_service = {"highway": "service"}
    assert evaluate_way_for_mode(general_service, "motor_vehicle")[0]


def test_bus_guideway_and_bus_only_exclusion():
    from urban_design.regional_network import evaluate_way_for_mode

    assert not evaluate_way_for_mode({"highway": "bus_guideway"}, "motor_vehicle")[0]
    assert not evaluate_way_for_mode({"highway": "primary", "access": "no", "bus": "yes"}, "motor_vehicle")[0]
    assert not evaluate_way_for_mode({"highway": "tertiary", "motor_vehicle": "no", "bus": "yes"}, "motor_vehicle")[0]


def test_imputation_tracking_across_modes():
    from urban_design.regional_network import evaluate_way_for_mode

    # Pedestrian on cycleway:
    # 1. No foot tag -> default prohibited, imputed=True
    inc, is_imp, _ = evaluate_way_for_mode({"highway": "cycleway"}, "pedestrian")
    assert not inc and is_imp
    # 2. Explicit foot=designated -> included, imputed=False
    inc, is_imp, _ = evaluate_way_for_mode({"highway": "cycleway", "foot": "designated"}, "pedestrian")
    assert inc and not is_imp

    # Bicycle on footway:
    # 1. No bicycle tag -> default prohibited, imputed=True
    inc, is_imp, _ = evaluate_way_for_mode({"highway": "footway"}, "bicycle")
    assert not inc and is_imp
    # 2. Explicit bicycle=yes -> included, imputed=False
    inc, is_imp, _ = evaluate_way_for_mode({"highway": "footway", "bicycle": "yes"}, "bicycle")
    assert inc and not is_imp

    # Car on residential:
    # 1. No motor_vehicle tag -> default permitted, imputed=True
    inc, is_imp, _ = evaluate_way_for_mode({"highway": "residential"}, "motor_vehicle")
    assert inc and is_imp
    # 2. Explicit motor_vehicle=yes -> included, imputed=False
    inc, is_imp, _ = evaluate_way_for_mode({"highway": "residential", "motor_vehicle": "yes"}, "motor_vehicle")
    assert inc and not is_imp


def test_access_private_and_overrides():
    from urban_design.regional_network import evaluate_way_for_mode

    private_way = {"highway": "residential", "access": "private"}
    assert not evaluate_way_for_mode(private_way, "pedestrian")[0]
    assert not evaluate_way_for_mode(private_way, "bicycle")[0]
    assert not evaluate_way_for_mode(private_way, "motor_vehicle")[0]

    # Foot override
    foot_override = {"highway": "residential", "access": "private", "foot": "yes"}
    assert evaluate_way_for_mode(foot_override, "pedestrian")[0]
    assert not evaluate_way_for_mode(foot_override, "bicycle")[0]

    # Bicycle override
    bike_override = {"highway": "residential", "access": "private", "bicycle": "permissive"}
    assert not evaluate_way_for_mode(bike_override, "pedestrian")[0]
    assert evaluate_way_for_mode(bike_override, "bicycle")[0]
