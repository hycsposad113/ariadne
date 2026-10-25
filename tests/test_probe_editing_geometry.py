"""Offline feasibility checks for the bounded floor-plate editing probe."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.affinity import translate
from shapely.ops import unary_union

from scripts.probe_editing_geometry import (
    compute_building_massing,
    lateral_push_pull,
    run_geometry_and_tool_probe,
    split_footprint,
)


def test_massing_exposes_each_floor_geometry_area_and_vertical_interval() -> None:
    base = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])
    left, right = sorted(split_footprint(base, LineString([(15, -1), (15, 21)])), key=lambda part: part.bounds[0])
    pushed_east = translate(right, xoff=2)
    floor_shapes = [base, MultiPolygon([left, pushed_east]), base]

    result = compute_building_massing(base, [3, 3, 3], floor_footprints=floor_shapes)

    assert [floor["floor_index"] for floor in result["floor_plates"]] == [0, 1, 2]
    assert [floor["floor_area_m2"] for floor in result["floor_plates"]] == pytest.approx([600, 600, 600])
    assert [floor["elevation_m"] for floor in result["floor_plates"]] == pytest.approx([0, 3, 6])
    assert [floor["geometry_type"] for floor in result["floor_plates"]] == ["Polygon", "MultiPolygon", "Polygon"]
    assert result["gross_floor_area_m2"] == pytest.approx(1800)
    assert result["floor_plates"][1]["bounds"] == pytest.approx([0, 0, 32, 20])


def test_split_is_a_non_overlapping_area_preserving_partition() -> None:
    footprint = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])
    parts = split_footprint(footprint, LineString([(15, -1), (15, 21)]))

    assert len(parts) == 2
    assert all(part.is_valid and part.area > 0 for part in parts)
    assert sum(part.area for part in parts) == pytest.approx(footprint.area)
    assert parts[0].intersection(parts[1]).area == pytest.approx(0)
    assert footprint.symmetric_difference(unary_union(parts)).area == pytest.approx(0)


def test_local_edge_push_pull_changes_area_and_preserves_validity() -> None:
    footprint = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])
    pushed = lateral_push_pull(footprint, edge_index=1, delta_m=1)

    assert pushed.is_valid
    assert pushed.area == pytest.approx(620)
    assert pushed.bounds == pytest.approx((0, 0, 31, 20))


@pytest.mark.parametrize(
    ("delta_m", "expected_area", "expected_bounds"),
    [
        (1, 630, (0, 0, 30, 21)),
        (-1, 570, (0, 0, 30, 19)),
    ],
)
def test_local_edge_push_pull_is_orientation_invariant_for_clockwise_ring(
    delta_m: float,
    expected_area: float,
    expected_bounds: tuple[float, float, float, float],
) -> None:
    footprint = Polygon([(0, 0), (0, 20), (30, 20), (30, 0)])

    edited = lateral_push_pull(footprint, edge_index=1, delta_m=delta_m)

    assert edited.is_valid
    assert edited.area == pytest.approx(expected_area)
    assert edited.bounds == pytest.approx(expected_bounds)


def test_local_edge_push_pull_preserves_interior_rings() -> None:
    footprint = Polygon(
        [(0, 0), (30, 0), (30, 20), (0, 20)],
        [[(10, 5), (20, 5), (20, 15), (10, 15)]],
    )

    edited = lateral_push_pull(footprint, edge_index=1, delta_m=1)

    assert edited.is_valid
    assert edited.area == pytest.approx(520)
    assert len(edited.interiors) == 1
    assert list(edited.interiors[0].coords) == list(footprint.interiors[0].coords)


def test_local_edge_push_pull_detects_winding_at_large_coordinate_offset() -> None:
    footprint = Polygon(
        [
            (90000, 440000),
            (90100, 440000),
            (90100, 440000.00000001),
            (90000, 440000.00000001),
        ]
    )

    edited = lateral_push_pull(footprint, edge_index=0, delta_m=1)

    assert edited.is_valid
    assert edited.bounds == pytest.approx(
        (90000.0, 439999.0, 90100.0, 440000.00000001), rel=0, abs=1e-9
    )
    assert edited.area == pytest.approx(100.000001, abs=1e-6)


@pytest.mark.parametrize("edge_index", [True, False, 1.0, None, "1"])
def test_local_edge_push_pull_rejects_non_integer_edge_index(edge_index: object) -> None:
    footprint = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])

    with pytest.raises(ValueError, match="Edge index must be an integer"):
        lateral_push_pull(footprint, edge_index=edge_index, delta_m=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("edge_index", [-1, 4])
def test_local_edge_push_pull_rejects_out_of_range_edge_index(edge_index: int) -> None:
    footprint = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])

    with pytest.raises(ValueError, match=r"Edge index .* out of range \[0, 3\]"):
        lateral_push_pull(footprint, edge_index=edge_index, delta_m=1)


def test_invalid_self_intersecting_and_zero_area_base_footprints_are_rejected() -> None:
    bow_tie = Polygon([(0, 0), (20, 20), (20, 0), (0, 20)])
    collinear = Polygon([(0, 0), (10, 0), (20, 0)])

    with pytest.raises(ValueError, match="Invalid base footprint"):
        compute_building_massing(bow_tie, [3])
    with pytest.raises(ValueError, match="Invalid base footprint"):
        compute_building_massing(collinear, [3])


def test_per_floor_geometry_count_and_validity_are_checked() -> None:
    base = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])
    bow_tie = Polygon([(0, 0), (20, 20), (20, 0), (0, 20)])

    with pytest.raises(ValueError, match="count must match"):
        compute_building_massing(base, [3, 3], floor_footprints=[base])
    with pytest.raises(ValueError, match="Invalid floor footprint"):
        compute_building_massing(base, [3], floor_footprints=[bow_tie])


def test_probe_marks_synthetic_scope_and_reports_explicit_limitations() -> None:
    report = run_geometry_and_tool_probe()

    assert report["status"] == "PASS"
    assert report["geometry_feasibility"]["invalid_geometry_rejection"]["self_intersecting_rejected"] is True
    assert report["geometry_feasibility"]["storey_massing"]["observed"]["floor_plates"]
    edited_stack = report["geometry_feasibility"]["edited_floor_stack"]
    assert edited_stack["floor_areas_m2"] == pytest.approx([600, 600, 620])
    assert edited_stack["envelope_covers_all_floors"] is True
    assert report["geometry_feasibility"]["scope"]["actual_rotterdam_geometry_used"] is False
    assert report["environmental_tools_audit"]["tier_readiness"]["E1_sunlight_hours"]["status"] == "METHOD_ONLY_NOT_EXECUTED"
    assert report["environmental_tools_audit"]["tier_readiness"]["E2_radiation_screening_and_verification"]["weather_semantics"] == "SEMANTICS_UNRESOLVED"
