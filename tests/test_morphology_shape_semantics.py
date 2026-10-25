from __future__ import annotations

import pytest
from shapely.affinity import rotate, translate
from shapely.geometry import Point, box
from shapely.ops import unary_union

from urban_design.generation.type_registry import InvalidMorphologyParameters, generate_profile_geometry
from urban_design.morphology.dictionary_generator import generate_profile_geometry_v5
from urban_design.generation.hashing import semantic_digest


def h_fixture_reference():
    return unary_union(
        [box(10, 10, 20, 70), box(80, 10, 90, 70), box(20, 35, 80, 45)]
    )


def _assert_measured_match(actual, reference, tolerance=1e-9):
    assert actual.symmetric_difference(reference).area <= tolerance
    assert actual.boundary.hausdorff_distance(reference.boundary) <= tolerance


def test_h_profile_is_not_a_one_sided_comb():
    generated = generate_profile_geometry(
        "building.h_plan",
        box(0, 0, 100, 80),
        {
            "width_m": 80,
            "depth_m": 60,
            "left_wing_width_m": 10,
            "right_wing_width_m": 10,
            "thickness_m": 10,
        },
        crs="EPSG:28992",
        coordinate_unit="m",
    ).geometry
    reference = h_fixture_reference()

    assert reference.area == 1800
    assert reference.is_valid
    assert reference.geom_type == "Polygon"
    assert generated.geom_type == "Polygon"
    _assert_measured_match(generated, reference)
    assert generated.covers(Point(15, 15))
    assert generated.covers(Point(85, 15))
    assert generated.covers(Point(50, 40))
    assert not generated.covers(Point(50, 15))
    assert not generated.covers(Point(50, 65))


def test_h_profile_matches_non_symmetric_dimensions():
    site = box(0, 0, 120, 90)
    generated = generate_profile_geometry(
        "building.h_plan",
        site,
        {
            "width_m": 80,
            "depth_m": 50,
            "left_wing_width_m": 8,
            "right_wing_width_m": 12,
            "thickness_m": 7,
        },
        crs="EPSG:28992",
        coordinate_unit="m",
    ).geometry
    reference = unary_union(
        [box(20, 20, 28, 70), box(88, 20, 100, 70), box(28, 41.5, 88, 48.5)]
    )

    _assert_measured_match(generated, reference)
    assert site.covers(generated)


def test_h_profile_supports_rotate90_and_preserves_site_containment():
    site = box(0, 0, 120, 120)
    parameters = {
        "width_m": 80,
        "depth_m": 60,
        "left_wing_width_m": 10,
        "right_wing_width_m": 10,
        "thickness_m": 10,
        "rotation_deg": 90,
    }
    generated = generate_profile_geometry(
        "building.h_plan", site, parameters, crs="EPSG:28992", coordinate_unit="m"
    ).geometry
    unrotated = h_fixture_reference()
    reference = rotate(translate(unrotated, xoff=10, yoff=20), 90, origin=(60, 60), use_radians=False)

    _assert_measured_match(generated, reference)
    assert site.covers(generated)
    assert round(generated.bounds[2] - generated.bounds[0]) == 60
    assert round(generated.bounds[3] - generated.bounds[1]) == 80


@pytest.mark.parametrize("generator", [generate_profile_geometry, generate_profile_geometry_v5])
def test_h_profile_rejects_retained_obstacle_that_disconnects_central_connector(generator):
    obstacle = box(45, 35, 55, 45)
    with pytest.raises(InvalidMorphologyParameters, match="connector|semantic feature"):
        generator(
            "building.h_plan",
            box(0, 0, 100, 80),
            {
                "width_m": 80,
                "depth_m": 60,
                "left_wing_width_m": 10,
                "right_wing_width_m": 10,
                "thickness_m": 10,
            },
            crs="EPSG:28992",
            coordinate_unit="m",
            preserved_obstacles=[obstacle],
        )


@pytest.mark.parametrize("generator", [generate_profile_geometry, generate_profile_geometry_v5])
def test_h_profile_removes_nonbreaking_retained_obstacle_and_preserves_semantics(generator):
    obstacle = box(10, 10, 12, 12)
    generated = generator(
        "building.h_plan",
        box(0, 0, 100, 80),
        {
            "width_m": 80,
            "depth_m": 60,
            "left_wing_width_m": 10,
            "right_wing_width_m": 10,
            "thickness_m": 10,
        },
        crs="EPSG:28992",
        coordinate_unit="m",
        preserved_obstacles=[obstacle],
    ).geometry

    assert generated.is_valid and generated.geom_type == "Polygon"
    assert generated.area == 1796
    assert generated.intersection(obstacle).area == 0


def test_e_profile_rejects_obstacle_that_splits_the_required_spine():
    with pytest.raises(InvalidMorphologyParameters, match="spine|semantic feature"):
        generate_profile_geometry(
            "building.e_plan",
            box(0, 0, 100, 80),
            {"width_m": 70, "depth_m": 60, "spine_thickness_m": 10, "wing_thickness_m": 8},
            crs="EPSG:28992",
            coordinate_unit="m",
            preserved_obstacles=[box(14, 28, 26, 32)],
        )


def test_e_profile_rejects_obstacle_that_removes_one_required_wing():
    with pytest.raises(InvalidMorphologyParameters, match="wing|semantic feature"):
        generate_profile_geometry(
            "building.e_plan",
            box(0, 0, 100, 80),
            {"width_m": 70, "depth_m": 60, "spine_thickness_m": 10, "wing_thickness_m": 8},
            crs="EPSG:28992",
            coordinate_unit="m",
            preserved_obstacles=[box(25, 16, 85, 24)],
        )


def test_e_profile_is_one_spine_with_three_same_side_wings():
    site = box(0, 0, 100, 80)
    generated = generate_profile_geometry(
        "building.e_plan",
        site,
        {
            "width_m": 70,
            "depth_m": 60,
            "spine_thickness_m": 10,
            "wing_thickness_m": 8,
        },
        crs="EPSG:28992",
        coordinate_unit="m",
    ).geometry
    reference = unary_union(
        [
            box(15, 10, 25, 70),
            box(25, 16, 85, 24),
            box(25, 36, 85, 44),
            box(25, 56, 85, 64),
        ]
    )

    _assert_measured_match(generated, reference)
    assert generated.covers(Point(20, 12))
    assert generated.covers(Point(80, 20))
    assert generated.covers(Point(80, 40))
    assert generated.covers(Point(80, 60))
    assert not generated.covers(Point(80, 30))


def test_h_profile_rejects_invalid_wall_thickness_fail_closed():
    with pytest.raises(ValueError, match="thickness_m"):
        generate_profile_geometry(
            "building.h_plan",
            box(0, 0, 100, 80),
            {
                "width_m": 80,
                "depth_m": 60,
                "left_wing_width_m": 10,
                "right_wing_width_m": 10,
                "thickness_m": 31,
            },
            crs="EPSG:28992",
            coordinate_unit="m",
        )


def test_generated_profile_has_reproducible_hash_that_tracks_geometry():
    site = box(0, 0, 100, 80)
    parameters = {
        "width_m": 80,
        "depth_m": 60,
        "left_wing_width_m": 10,
        "right_wing_width_m": 10,
        "thickness_m": 10,
    }
    first = generate_profile_geometry(
        "building.h_plan", site, parameters, crs="EPSG:28992", coordinate_unit="m"
    )
    replay = generate_profile_geometry(
        "building.h_plan", site, parameters, crs="EPSG:28992", coordinate_unit="m"
    )
    changed = generate_profile_geometry(
        "building.h_plan", site, {**parameters, "width_m": 70}, crs="EPSG:28992", coordinate_unit="m"
    )

    assert semantic_digest(first) == semantic_digest(replay)
    assert semantic_digest(first) != semantic_digest(changed)


@pytest.mark.parametrize("wing_count", [2, 3, 5])
def test_comb_profile_matches_independent_reference_union_for_supported_wing_counts(wing_count):
    site = box(0, 0, 160, 100)
    parameters = {
        "spine_length_m": 120,
        "spine_thickness_m": 10,
        "wing_depth_m": 30,
        "wing_thickness_m": 4,
        "wing_count": wing_count,
        "gap_m": 12,
    }
    generated = generate_profile_geometry(
        "building.comb", site, parameters, crs="EPSG:28992", coordinate_unit="m"
    ).geometry

    center_x, center_y = 80, 50
    spine_left = center_x - parameters["spine_length_m"] / 2
    spine_bottom = center_y - (parameters["spine_thickness_m"] + parameters["wing_depth_m"]) / 2
    spine_top = spine_bottom + parameters["spine_thickness_m"]
    occupied = wing_count * parameters["wing_thickness_m"] + (wing_count - 1) * parameters["gap_m"]
    margin = (parameters["spine_length_m"] - occupied) / 2
    wings = []
    for index in range(wing_count):
        wing_center = spine_left + margin + parameters["wing_thickness_m"] / 2 + index * (
            parameters["wing_thickness_m"] + parameters["gap_m"]
        )
        wings.append(
            box(
                wing_center - parameters["wing_thickness_m"] / 2,
                spine_top,
                wing_center + parameters["wing_thickness_m"] / 2,
                spine_top + parameters["wing_depth_m"],
            )
        )
    reference = unary_union(
        [
            box(
                spine_left,
                spine_bottom,
                spine_left + parameters["spine_length_m"],
                spine_top,
            ),
            *wings,
        ]
    )

    _assert_measured_match(generated, reference)
    assert generated.geom_type == "Polygon"
    assert site.covers(generated)


def test_e_and_comb_three_are_equivalent_only_for_the_matching_dimension_layout():
    site = box(0, 0, 100, 80)
    e_profile = generate_profile_geometry(
        "building.e_plan",
        site,
        {"width_m": 44, "depth_m": 60, "spine_thickness_m": 10, "wing_thickness_m": 8},
        crs="EPSG:28992",
        coordinate_unit="m",
    )
    comb_three = generate_profile_geometry_v5(
        "building.comb",
        site,
        {
            "spine_length_m": 60,
            "spine_thickness_m": 10,
            "wing_depth_m": 34,
            "wing_thickness_m": 8,
            "wing_count": 3,
            "gap_m": 12,
            "rotation_deg": -90,
        },
        crs="EPSG:28992",
        coordinate_unit="m",
    )
    mismatched_comb = generate_profile_geometry(
        "building.comb",
        site,
        {
            "spine_length_m": 60,
            "spine_thickness_m": 10,
            "wing_depth_m": 34,
            "wing_thickness_m": 7,
            "wing_count": 3,
            "gap_m": 12,
            "rotation_deg": -90,
        },
        crs="EPSG:28992",
        coordinate_unit="m",
    )

    _assert_measured_match(comb_three.geometry, e_profile.geometry)
    assert comb_three.type_id == "building.comb"
    assert e_profile.type_id == "building.e_plan"
    assert comb_three.type_id != e_profile.type_id
    assert comb_three.implementation_id != e_profile.implementation_id
    assert comb_three.algorithm_version != e_profile.algorithm_version
    assert mismatched_comb.geometry.symmetric_difference(e_profile.geometry).area > 1e-6


def test_comb_profile_rejects_obstacle_that_splits_the_required_spine():
    with pytest.raises(InvalidMorphologyParameters, match="spine|semantic feature"):
        generate_profile_geometry(
            "building.comb",
            box(0, 0, 160, 100),
            {
                "spine_length_m": 120,
                "spine_thickness_m": 10,
                "wing_depth_m": 30,
                "wing_thickness_m": 4,
                "wing_count": 3,
                "gap_m": 12,
            },
            crs="EPSG:28992",
            coordinate_unit="m",
            preserved_obstacles=[box(19, 34, 141, 36)],
        )
