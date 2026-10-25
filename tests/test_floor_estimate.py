from __future__ import annotations

import pytest

from urban_design.models import UnavailableValue
from urban_design.morphology.floor_estimate import estimate_floor_count


def test_floor_estimate_uses_p70_height_and_fixture_only_three_metre_height() -> None:
    result = estimate_floor_count(
        building_id="building-1",
        bag_id="0599100010050132",
        roof_p70_height_m=10.0,
        ground_height_m=1.0,
        building_use="woonfunctie",
        height_field_name="roof_p70",
        data_version="fixture-3dbag-v1",
    )

    assert result.floor_count == 3
    assert result.rule_version == "floor-estimate-v1"
    assert result.status == "ESTIMATE"
    assert result.floor_height_m == pytest.approx(3.0)
    assert result.floor_height_status == "FIXTURE_ONLY"
    assert result.height_field_name == "roof_p70"
    assert result.data_version == "fixture-3dbag-v1"


def test_large_space_use_returns_floor_range_for_far_accounting() -> None:
    result = estimate_floor_count(
        building_id="warehouse-1",
        bag_id="bag-warehouse-1",
        roof_p70_height_m=13.0,
        ground_height_m=1.0,
        building_use="industriefunctie",
        height_field_name="roof_p70",
        data_version="fixture-3dbag-v1",
    )

    assert result.floor_count == (1, 4)
    assert result.status == "ESTIMATE"


def test_missing_3d_bag_match_is_unavailable_not_zero() -> None:
    result = estimate_floor_count(
        building_id="unmatched-1",
        bag_id="bag-unmatched-1",
        roof_p70_height_m=None,
        ground_height_m=None,
        building_use="woonfunctie",
        height_field_name="roof_p70",
        data_version="fixture-3dbag-v1",
    )

    assert isinstance(result.floor_count, UnavailableValue)
    assert result.floor_count.status == "unavailable"
    assert result.status == "ESTIMATE"


def test_approved_floor_height_requires_human_decision_reference() -> None:
    with pytest.raises(ValueError, match="HumanDecision"):
        estimate_floor_count(
            building_id="building-1",
            bag_id="bag-1",
            roof_p70_height_m=13.0,
            ground_height_m=1.0,
            building_use="woonfunctie",
            height_field_name="roof_p70",
            data_version="fixture-3dbag-v1",
            floor_height_m=4.0,
            floor_height_status="APPROVED",
        )


def test_approved_floor_height_is_versioned_by_decision_reference() -> None:
    result = estimate_floor_count(
        building_id="building-1",
        bag_id="bag-1",
        roof_p70_height_m=13.0,
        ground_height_m=1.0,
        building_use="woonfunctie",
        height_field_name="roof_p70",
        data_version="fixture-3dbag-v1",
        floor_height_m=4.0,
        floor_height_status="APPROVED",
        floor_height_decision_id="decision-fixture-1",
    )

    assert result.floor_count == 3
    assert result.floor_height_status == "APPROVED"
    assert result.floor_height_decision_id == "decision-fixture-1"


def test_w5_5_far_propagates_retained_floor_range() -> None:
    from urban_design.morphology.metrics import calculate_far

    assert calculate_far((620.0, 680.0), 1000.0) == pytest.approx((0.62, 0.68))
