from __future__ import annotations

import pytest
from shapely.geometry import box

from urban_design.generation.type_registry import (
    CapabilityState,
    InvalidMorphologyParameters,
    UnsupportedMorphologyType,
    build_type_registry,
    generate_profile_geometry,
)
from urban_design.morphology.dictionary_generator import generate_profile_geometry_v5
from urban_design.morphology_dictionary import load_dictionary


def test_registry_covers_every_checked_in_dictionary_type_id():
    dictionary = load_dictionary()
    registry = build_type_registry(dictionary)

    assert set(registry.entries) == {entry["id"] for entry in dictionary["entries"]}
    for capability in registry.entries.values():
        if capability.capability_state is CapabilityState.SUPPORTED:
            assert capability.implementation_id
            assert capability.algorithm_version
            assert capability.semantic_test_ids
        else:
            assert capability.unsupported_reason
            assert capability.implementation_id is None


def test_h_and_e_are_explicit_checked_capabilities_and_slab_fails_closed():
    registry = build_type_registry(load_dictionary())

    h_plan = registry.entries["building.h_plan"]
    e_plan = registry.entries["building.e_plan"]
    assert h_plan.capability_state is CapabilityState.SUPPORTED
    assert e_plan.capability_state is CapabilityState.SUPPORTED
    assert h_plan.supported_capabilities == ("footprint_geometry",)
    assert e_plan.supported_capabilities == ("footprint_geometry",)
    for capability in (h_plan, e_plan):
        assert {
            "openings",
            "opening_orientation",
            "ground_upper_floor_range",
            "variable_comb_count",
            "public_access_policy",
        } <= set(capability.unsupported_capabilities)
    slab = registry.entries["building.i_slab"]
    assert slab.capability_state is CapabilityState.UNSUPPORTED
    assert "adapter" in slab.unsupported_reason.lower()
    comb = registry.entries["building.comb"]
    assert comb.capability_state is CapabilityState.SUPPORTED
    assert {"footprint_geometry", "variable_comb_count"} <= set(comb.supported_capabilities)
    assert "variable_comb_count" not in comb.unsupported_capabilities
    assert comb.implementation_id == "comb_profile_v1"
    assert comb.algorithm_version == "morphology-profile-comb-v1"
    assert comb.variant_id == "variable-wing"
    assert comb.integer_parameters == ("wing_count",)
    assert comb.parameter_ranges == (
        ("spine_length_m", 40.0, 120.0),
        ("wing_depth_m", 10.0, 36.0),
        ("wing_count", 2.0, 5.0),
        ("gap_m", 12.0, 30.0),
    )
    assert comb.semantic_test_ids == (
        "test_comb_profile_matches_independent_reference_union_for_supported_wing_counts",
        "test_e_and_comb_three_are_equivalent_only_for_the_matching_dimension_layout",
        "test_comb_profile_rejects_obstacle_that_splits_the_required_spine",
    )


def test_unknown_profile_is_explicit_error():
    site = box(0, 0, 100, 80)

    with pytest.raises(UnsupportedMorphologyType, match="unknown morphology type"):
        generate_profile_geometry("building.not_in_dictionary", site, {}, crs="EPSG:28992", coordinate_unit="m")


@pytest.mark.parametrize("generator", [generate_profile_geometry, generate_profile_geometry_v5])
def test_unsupported_slab_fails_closed_instead_of_returning_empty_geometry(generator):
    site = box(0, 0, 100, 80)

    with pytest.raises(UnsupportedMorphologyType, match="no versioned geometry adapter"):
        generator(
            "building.i_slab", site, {"width_m": 50, "depth_m": 12}, crs="EPSG:28992", coordinate_unit="m"
        )


_COMB_PARAMETERS = {
    "spine_length_m": 60,
    "spine_thickness_m": 10,
    "wing_depth_m": 30,
    "wing_thickness_m": 6,
    "wing_count": 3,
    "gap_m": 12,
}


@pytest.mark.parametrize("generator", [generate_profile_geometry, generate_profile_geometry_v5])
@pytest.mark.parametrize("wing_count", [1, 6, 2.0, True, "3"])
def test_comb_wing_count_is_strict_integer_in_dictionary_domain(generator, wing_count):
    with pytest.raises(InvalidMorphologyParameters, match="wing_count"):
        generator(
            "building.comb",
            box(0, 0, 120, 80),
            {**_COMB_PARAMETERS, "wing_count": wing_count},
            crs="EPSG:28992",
            coordinate_unit="m",
        )


@pytest.mark.parametrize("generator", [generate_profile_geometry, generate_profile_geometry_v5])
@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("spine_length_m", 39.9),
        ("spine_length_m", 120.1),
        ("wing_depth_m", 9.9),
        ("wing_depth_m", 36.1),
        ("gap_m", 11.9),
        ("gap_m", 30.1),
        ("spine_thickness_m", 30),
        ("wing_thickness_m", 13),
    ],
)
def test_comb_dimensions_and_thickness_gap_domain_fail_closed(generator, parameter, value):
    with pytest.raises(InvalidMorphologyParameters):
        generator(
            "building.comb",
            box(0, 0, 160, 100),
            {**_COMB_PARAMETERS, parameter: value},
            crs="EPSG:28992",
            coordinate_unit="m",
        )


def test_v5_comb_adapter_preserves_type_variant_and_strict_wing_count_metadata():
    generated = generate_profile_geometry_v5(
        "building.comb",
        box(0, 0, 120, 80),
        _COMB_PARAMETERS,
        crs="EPSG:28992",
        coordinate_unit="m",
    )

    assert generated.type_id == "building.comb"
    assert generated.variant_id == "variable-wing"
    assert generated.algorithm_version == "morphology-profile-comb-v1"
    assert type(generated.parameters["wing_count"]) is int


def test_supported_v5_dictionary_adapter_matches_registry_geometry():
    site = box(0, 0, 100, 80)
    parameters = {
        "width_m": 80,
        "depth_m": 60,
        "left_wing_width_m": 10,
        "right_wing_width_m": 10,
        "thickness_m": 10,
    }

    direct = generate_profile_geometry("building.h_plan", site, parameters, crs="EPSG:28992", coordinate_unit="m")
    adapted = generate_profile_geometry_v5(
        "building.h_plan", site, parameters, crs="EPSG:28992", coordinate_unit="m"
    )

    assert adapted.geometry.equals(direct.geometry)
    assert adapted.algorithm_version == "morphology-profile-h-v1"


def test_type_specific_parameters_reject_unknown_keys_and_invalid_thickness():
    site = box(0, 0, 100, 80)
    parameters = {
        "width_m": 80,
        "depth_m": 60,
        "left_wing_width_m": 10,
        "right_wing_width_m": 10,
        "thickness_m": 30,
    }

    with pytest.raises(ValueError, match="thickness_m"):
        generate_profile_geometry("building.h_plan", site, parameters, crs="EPSG:28992", coordinate_unit="m")
    with pytest.raises(ValueError, match="unsupported parameter"):
        generate_profile_geometry(
            "building.h_plan",
            site,
            {**parameters, "wall_color": "red"},
            crs="EPSG:28992",
            coordinate_unit="m",
        )


@pytest.mark.parametrize("generator", [generate_profile_geometry, generate_profile_geometry_v5])
@pytest.mark.parametrize(
    ("unsupported_parameter", "unsupported_value"),
    [
        ("openings", [{"orientation": "east"}]),
        ("opening_orientation", "east"),
        ("ground_upper_floor_range", [0, 4]),
        ("public_access_policy", {"status": "PUBLIC"}),
    ],
)
def test_unsupported_opening_floor_and_access_parameters_fail_closed(
    generator, unsupported_parameter, unsupported_value
):
    parameters = {
        "width_m": 80,
        "depth_m": 60,
        "left_wing_width_m": 10,
        "right_wing_width_m": 10,
        "thickness_m": 10,
        unsupported_parameter: unsupported_value,
    }
    with pytest.raises(ValueError, match="unsupported parameter"):
        generator(
            "building.h_plan",
            box(0, 0, 100, 80),
            parameters,
            crs="EPSG:28992",
            coordinate_unit="m",
        )


@pytest.mark.parametrize("generator", [generate_profile_geometry, generate_profile_geometry_v5])
def test_e_profile_rejects_variable_wing_count(generator):
    with pytest.raises(ValueError, match="unsupported parameter.*wing_count"):
        generator(
            "building.e_plan",
            box(0, 0, 100, 80),
            {
                "width_m": 70,
                "depth_m": 60,
                "spine_thickness_m": 10,
                "wing_thickness_m": 8,
                "wing_count": 4,
            },
            crs="EPSG:28992",
            coordinate_unit="m",
        )


def test_profile_generation_validates_crs_and_explicit_coordinate_unit():
    site = box(0, 0, 100, 80)
    parameters = {
        "width_m": 80,
        "depth_m": 60,
        "left_wing_width_m": 10,
        "right_wing_width_m": 10,
        "thickness_m": 10,
    }

    with pytest.raises(ValueError, match="EPSG:28992"):
        generate_profile_geometry("building.h_plan", site, parameters, crs="EPSG:4326", coordinate_unit="m")
    with pytest.raises(ValueError, match="unit"):
        generate_profile_geometry("building.h_plan", site, parameters, crs="EPSG:28992", coordinate_unit="degrees")
