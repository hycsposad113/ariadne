"""Fixture-only known-answer tests for the W5-5 morphology metric kernel."""

from __future__ import annotations

import pytest
from shapely.geometry import box

from urban_design.models import UnavailableValue
from urban_design.morphology.metrics import (
    FloorPlate,
    MetricValidationError,
    RetainedBuilding,
    Zone,
    calculate_height,
    calculate_morphology_metrics,
    evaluate_far_upper_bound,
)


def _blueprint_floors(*, extra_floor: bool = False) -> tuple[FloorPlate, ...]:
    floor_count = 4 if extra_floor else 3
    return tuple(
        FloorPlate(id=f"floor-{level}", geometry=box(0, 0, 10, 20), level=level, building_id="blueprint")
        for level in range(floor_count)
    )


def test_blueprint_fixture_known_answers_for_gfa_far_and_height() -> None:
    result = calculate_morphology_metrics(
        design_area=box(0, 0, 20, 50),
        floor_plates=_blueprint_floors(),
        first_floor_height_m=4,
        standard_floor_height_m=3,
    )

    assert result.gfa_m2 == pytest.approx(600)
    assert result.far == pytest.approx(0.6)
    assert result.coverage_m2 == pytest.approx(200)
    assert result.coverage_ratio == pytest.approx(0.2)
    assert result.height_m == pytest.approx(10)
    assert result.provenance == "FIXTURE_ONLY"


def test_adding_one_floor_updates_gfa_far_and_height_deterministically() -> None:
    result = calculate_morphology_metrics(
        design_area=box(0, 0, 20, 50),
        floor_plates=_blueprint_floors(extra_floor=True),
        first_floor_height_m=4,
        standard_floor_height_m=3,
    )

    assert result.gfa_m2 == pytest.approx(800)
    assert result.far == pytest.approx(0.8)
    assert result.height_m == pytest.approx(13)


def test_far_upper_bound_is_saveable_but_not_acceptable_when_exceeded() -> None:
    result = evaluate_far_upper_bound(0.8, upper_bound=0.7)

    assert result.saveable is True
    assert result.acceptable is False
    assert result.reason == "FAR exceeds upper bound"


def test_coverage_uses_union_instead_of_summing_overlapping_footprints() -> None:
    floors = (
        FloorPlate(id="a", geometry=box(0, 0, 10, 10), level=0, building_id="a"),
        FloorPlate(id="b", geometry=box(5, 0, 15, 10), level=0, building_id="b"),
    )
    result = calculate_morphology_metrics(
        design_area=box(0, 0, 20, 10),
        floor_plates=floors,
        first_floor_height_m=4,
        standard_floor_height_m=3,
    )

    assert result.coverage_m2 == pytest.approx(150)
    assert result.coverage_ratio == pytest.approx(0.75)


def test_zone_allocation_uses_floor_polygon_intersections() -> None:
    result = calculate_morphology_metrics(
        design_area=box(0, 0, 20, 10),
        floor_plates=(FloorPlate(id="floor", geometry=box(0, 0, 10, 10), level=0),),
        first_floor_height_m=4,
        standard_floor_height_m=3,
        zones=(
            Zone(id="west", geometry=box(0, 0, 5, 10)),
            Zone(id="east", geometry=box(5, 0, 20, 10)),
        ),
    )

    assert result.zone_floor_area_m2 == {"east": pytest.approx(50), "west": pytest.approx(50)}


def test_overlapping_zones_fail_without_explicit_allocation_policy() -> None:
    with pytest.raises(MetricValidationError, match="overlap"):
        calculate_morphology_metrics(
            design_area=box(0, 0, 20, 10),
            floor_plates=(FloorPlate(id="floor", geometry=box(0, 0, 10, 10), level=0),),
            first_floor_height_m=4,
            standard_floor_height_m=3,
            zones=(
                Zone(id="a", geometry=box(0, 0, 8, 10)),
                Zone(id="b", geometry=box(5, 0, 15, 10)),
            ),
        )


def test_unknown_retained_building_floors_stay_unavailable_and_never_become_zero() -> None:
    result = calculate_morphology_metrics(
        design_area=box(0, 0, 20, 50),
        floor_plates=_blueprint_floors(),
        retained_buildings=(
            RetainedBuilding(
                id="retained-unknown",
                footprint=box(10, 0, 20, 10),
                floor_count=UnavailableValue(reason="3D BAG match unavailable"),
            ),
        ),
        first_floor_height_m=4,
        standard_floor_height_m=3,
    )

    assert isinstance(result.gfa_m2, UnavailableValue)
    assert isinstance(result.far, UnavailableValue)
    assert isinstance(result.height_m, UnavailableValue)
    assert result.coverage_m2 == pytest.approx(300)
    assert result.gfa_m2.reason == "3D BAG match unavailable"


def test_height_propagates_unknown_floor_count() -> None:
    unknown = UnavailableValue(reason="retained floor count not observed")
    result = calculate_height(unknown, first_floor_height_m=4, standard_floor_height_m=3)

    assert result == unknown


def test_retained_floor_range_propagates_through_gfa_far_height_and_bound_check() -> None:
    result = calculate_morphology_metrics(
        design_area=box(0, 0, 20, 50),
        floor_plates=_blueprint_floors(),
        retained_buildings=(
            RetainedBuilding(
                id="retained-warehouse",
                footprint=box(10, 0, 20, 10),
                floor_count=(1, 4),
            ),
        ),
        first_floor_height_m=4,
        standard_floor_height_m=3,
        far_upper_bound=0.7,
    )

    assert result.gfa_m2 == pytest.approx((700, 1000))
    assert result.far == pytest.approx((0.7, 1.0))
    assert result.height_m == pytest.approx((10, 13))
    assert result.far_bound_check is not None
    assert result.far_bound_check.acceptable is None
    assert result.far_bound_check.status == "INDETERMINATE"


def test_setback_changes_only_the_floor_that_was_changed() -> None:
    floors = _blueprint_floors()
    set_back = (*floors[:2], FloorPlate(id="floor-2", geometry=box(0, 0, 5, 20), level=2, building_id="blueprint"))
    result = calculate_morphology_metrics(
        design_area=box(0, 0, 20, 50),
        floor_plates=set_back,
        first_floor_height_m=4,
        standard_floor_height_m=3,
    )

    assert result.gfa_m2 == pytest.approx(500)
    assert result.coverage_m2 == pytest.approx(200)


def test_metric_input_validation_rejects_duplicate_ids_and_nonpositive_heights() -> None:
    duplicate_floors = (
        FloorPlate(id="same", geometry=box(0, 0, 10, 10), level=0),
        FloorPlate(id="same", geometry=box(0, 0, 10, 10), level=1),
    )
    with pytest.raises(MetricValidationError, match="unique"):
        calculate_morphology_metrics(
            design_area=box(0, 0, 20, 20),
            floor_plates=duplicate_floors,
            first_floor_height_m=4,
            standard_floor_height_m=3,
        )
    with pytest.raises(MetricValidationError, match="positive"):
        calculate_height(3, first_floor_height_m=0, standard_floor_height_m=3)


def test_repeated_fixture_calculation_has_identical_results() -> None:
    kwargs = {
        "design_area": box(0, 0, 20, 50),
        "floor_plates": _blueprint_floors(),
        "first_floor_height_m": 4,
        "standard_floor_height_m": 3,
    }

    first = calculate_morphology_metrics(**kwargs)
    second = calculate_morphology_metrics(**kwargs)

    assert first == second
