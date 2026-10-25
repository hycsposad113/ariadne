"""Synthetic, deterministic W5-9 massing edit and revision tests."""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon, box

from urban_design.editing import EditCommandError
from urban_design.editing.commands import (
    AddFloorCommand,
    EditHistory,
    IdempotencyConflict,
    MoveCommand,
    PushSideCommand,
    RemoveFloorCommand,
    RevisionConflict,
    RotateCommand,
)
from urban_design.editing.floors import (
    BuildingMassing,
    FloorStorey,
    calculate_fixture_metrics,
)
from urban_design.editing.validation import validate_building


def _building(
    floor_count: int = 3,
    *,
    geometry=None,
    origin: tuple[float, float] = (0.0, 0.0),
) -> BuildingMassing:
    x, y = origin
    footprint = geometry if geometry is not None else Polygon(
        [(x, y), (x + 10, y), (x + 10, y + 20), (x, y + 20)]
    )
    return BuildingMassing(
        id="fixture-building",
        floors=tuple(
            FloorStorey(id=f"floor-{level}", level=level, geometry=footprint)
            for level in range(floor_count)
        ),
        first_floor_height_m=4.0,
        standard_floor_height_m=3.0,
    )


def test_add_floor_updates_fixture_metrics_without_mutating_parent() -> None:
    source = _building()
    history = EditHistory(source)

    revision = history.apply(
        AddFloorCommand(new_floor_id="floor-3"),
        expected_revision=0,
        idempotency_key="add-floor-3",
    )

    metrics = calculate_fixture_metrics(revision.building, design_area=box(0, 0, 20, 50))
    assert metrics.gfa_m2 == pytest.approx(800)
    assert metrics.far == pytest.approx(0.8)
    assert metrics.height_m == pytest.approx(13)
    assert len(source.floors) == 3
    assert len(revision.building.floors) == 4
    assert revision.state == "DRAFT"
    assert revision.validation.provenance == "FIXTURE_ONLY"


def test_geometry_hash_includes_vertical_floor_height_parameters() -> None:
    source = _building(1)
    taller = BuildingMassing(
        id=source.id,
        floors=source.floors,
        first_floor_height_m=4.5,
        standard_floor_height_m=source.standard_floor_height_m,
    )

    assert source.geometry_hash() != taller.geometry_hash()


def test_remove_floor_removes_only_the_top_storey() -> None:
    history = EditHistory(_building())
    added = history.apply(
        AddFloorCommand(new_floor_id="floor-3"),
        expected_revision=0,
        idempotency_key="add",
    )

    removed = history.apply(
        RemoveFloorCommand(floor_id="floor-3"),
        expected_revision=added.revision_id,
        idempotency_key="remove",
    )

    metrics = calculate_fixture_metrics(removed.building, design_area=box(0, 0, 20, 50))
    assert [floor.level for floor in removed.building.floors] == [0, 1, 2]
    assert metrics.gfa_m2 == pytest.approx(600)
    assert metrics.height_m == pytest.approx(10)


def test_remove_floor_rejects_non_top_and_last_storey() -> None:
    with pytest.raises(ValueError, match="top storey"):
        EditHistory(_building()).apply(
            RemoveFloorCommand(floor_id="floor-1"),
            expected_revision=0,
            idempotency_key="remove-middle",
        )

    with pytest.raises(ValueError, match="at least one floor"):
        EditHistory(_building(1)).apply(
            RemoveFloorCommand(floor_id="floor-0"),
            expected_revision=0,
            idempotency_key="remove-last",
        )


def test_push_side_uses_integer_metre_steps_relative_to_original_geometry() -> None:
    source = _building()
    source_hash = source.geometry_hash()
    history = EditHistory(source)

    revision = history.apply(
        PushSideCommand(
            floor_edge_indices=(("floor-0", 1),),
            steps=2,
            origin_geometry_hash=source_hash,
        ),
        expected_revision=0,
        idempotency_key="push-two-metres",
    )

    pushed = revision.building.floor("floor-0").geometry
    assert pushed.area == pytest.approx(240)
    assert pushed.bounds == pytest.approx((0, 0, 12, 20))
    assert source.floor("floor-0").geometry.bounds == pytest.approx((0, 0, 10, 20))
    assert revision.before_geometry_hash == source_hash
    assert revision.after_geometry_hash == revision.building.geometry_hash()


def test_push_side_can_apply_one_relative_step_to_selected_levels() -> None:
    history = EditHistory(_building())
    origin_hash = history.active.building.geometry_hash()

    revision = history.apply(
        PushSideCommand(
            floor_edge_indices=(("floor-0", 1), ("floor-1", 1)),
            steps=1,
            origin_geometry_hash=origin_hash,
        ),
        expected_revision=0,
        idempotency_key="push-shared-side",
    )

    assert revision.building.floor("floor-0").geometry.bounds[2] == pytest.approx(11)
    assert revision.building.floor("floor-1").geometry.bounds[2] == pytest.approx(11)
    assert revision.building.floor("floor-2").geometry.bounds[2] == pytest.approx(10)
    assert revision.validation.solid_topology == "NOT_ASSESSED"
    assert revision.validation.acceptance_eligible is False


def test_move_preserves_fractional_project_coordinates() -> None:
    source = _building(origin=(9050.25, 43600.125))
    history = EditHistory(source)

    revision = history.apply(
        MoveCommand(dx_m=0.375, dy_m=-0.625),
        expected_revision=0,
        idempotency_key="move-fractional",
    )

    assert revision.building.floor("floor-0").geometry.bounds == pytest.approx(
        (9050.625, 43599.5, 9060.625, 43619.5), abs=1e-9
    )


def test_move_rejects_integer_outside_finite_float_range_as_command_error() -> None:
    history = EditHistory(_building(1))

    with pytest.raises(EditCommandError, match="finite number"):
        history.apply(
            MoveCommand(dx_m=10**500, dy_m=0),
            expected_revision=0,
            idempotency_key="oversized-move",
        )


def test_rotate_uses_the_lowest_floor_footprint_centroid_and_exact_angle() -> None:
    history = EditHistory(_building(1))

    revision = history.apply(
        RotateCommand(angle_degrees=90.0),
        expected_revision=0,
        idempotency_key="rotate-90",
    )

    rotated = revision.building.floor("floor-0").geometry
    assert rotated.bounds == pytest.approx((-5, 5, 15, 15), abs=1e-9)
    assert rotated.centroid.x == pytest.approx(5)
    assert rotated.centroid.y == pytest.approx(10)


def test_invalid_geometry_is_saved_as_draft_but_not_acceptance_or_analysis_ready() -> None:
    history = EditHistory(_building(1))
    origin_hash = history.active.building.geometry_hash()

    revision = history.apply(
        PushSideCommand(
            floor_edge_indices=(("floor-0", 1),),
            steps=-11,
            origin_geometry_hash=origin_hash,
        ),
        expected_revision=0,
        idempotency_key="invalid-push",
    )

    assert revision.state == "DRAFT"
    assert revision.validation.geometry_valid is False
    assert revision.validation.acceptance_eligible is False
    assert revision.validation.analysis_eligible is False
    assert any(
        finding.code == "SIDE_PUSH_INVERTED_FOOTPRINT"
        for finding in revision.validation.findings
    )
    assert history.active_revision_id == revision.revision_id
    assert len(history.revisions) == 2


def test_uniform_extrusion_topology_is_assessed_but_not_product_accepted() -> None:
    result = validate_building(_building())

    assert result.geometry_valid is True
    assert result.solid_topology == "UNIFORM_EXTRUSION_VALIDATED"
    assert result.acceptance_eligible is False
    assert result.analysis_eligible is False
    assert any(finding.code == "UNIFORM_EXTRUSION_TOPOLOGY_VALIDATED" for finding in result.findings)


def test_differing_floor_plates_fail_closed_without_claiming_manifold_topology() -> None:
    building = _building()
    modified = BuildingMassing(
        id=building.id,
        floors=(
            building.floors[0],
            FloorStorey("floor-1", 1, box(0, 0, 9, 20)),
            building.floors[2],
        ),
        first_floor_height_m=building.first_floor_height_m,
        standard_floor_height_m=building.standard_floor_height_m,
    )

    result = validate_building(modified)

    assert result.geometry_valid is True
    assert result.solid_topology == "NOT_ASSESSED"
    assert result.acceptance_eligible is False
    assert any(finding.code == "SOLID_TOPOLOGY_NOT_ASSESSED" for finding in result.findings)


def test_undo_redo_moves_revision_pointer_without_deleting_history() -> None:
    history = EditHistory(_building())
    first = history.apply(
        AddFloorCommand(new_floor_id="floor-3"),
        expected_revision=0,
        idempotency_key="add",
    )
    second = history.apply(
        MoveCommand(dx_m=2, dy_m=0),
        expected_revision=first.revision_id,
        idempotency_key="move",
    )

    undone = history.undo()
    assert undone.revision_id == first.revision_id
    assert len(history.revisions) == 3
    redone = history.redo()
    assert redone.revision_id == second.revision_id
    assert redone.after_geometry_hash == second.after_geometry_hash
    assert len(history.revisions) == 3


def test_edit_after_undo_keeps_both_branches_and_requires_redo_target() -> None:
    history = EditHistory(_building())
    first = history.apply(
        AddFloorCommand(new_floor_id="floor-3"),
        expected_revision=0,
        idempotency_key="add",
    )
    old_child = history.apply(
        MoveCommand(dx_m=2, dy_m=0),
        expected_revision=first.revision_id,
        idempotency_key="move-old-branch",
    )
    history.undo()
    new_child = history.apply(
        RotateCommand(angle_degrees=45),
        expected_revision=first.revision_id,
        idempotency_key="rotate-new-branch",
    )

    assert len(history.revisions) == 4
    history.undo()
    with pytest.raises(ValueError, match="redo target is ambiguous"):
        history.redo()
    assert history.redo(old_child.revision_id).revision_id == old_child.revision_id
    history.undo()
    assert history.redo(new_child.revision_id).revision_id == new_child.revision_id


def test_idempotent_replay_returns_same_revision_and_conflicting_key_is_rejected() -> None:
    history = EditHistory(_building())
    command = AddFloorCommand(new_floor_id="floor-3")

    first = history.apply(command, expected_revision=0, idempotency_key="same-key")
    replay = history.apply(command, expected_revision=0, idempotency_key="same-key")

    assert replay is first
    assert len(history.revisions) == 2
    with pytest.raises(IdempotencyConflict, match="different edit"):
        history.apply(
            MoveCommand(dx_m=1, dy_m=0),
            expected_revision=0,
            idempotency_key="same-key",
        )


def test_expected_revision_mismatch_is_rejected_without_new_revision() -> None:
    history = EditHistory(_building())
    history.apply(
        AddFloorCommand(new_floor_id="floor-3"),
        expected_revision=0,
        idempotency_key="add",
    )

    with pytest.raises(RevisionConflict, match="expected revision"):
        history.apply(
            MoveCommand(dx_m=1, dy_m=0),
            expected_revision=0,
            idempotency_key="stale-move",
        )
    assert len(history.revisions) == 2


def test_command_replay_is_deterministic_for_same_parent_revision() -> None:
    source = _building()
    first = EditHistory(source).apply(
        RotateCommand(angle_degrees=17.25),
        expected_revision=0,
        idempotency_key="run-a",
    )
    second = EditHistory(source).apply(
        RotateCommand(angle_degrees=17.25),
        expected_revision=0,
        idempotency_key="run-b",
    )

    assert first.after_geometry_hash == second.after_geometry_hash
    assert first.building.floor("floor-0").geometry.equals_exact(
        second.building.floor("floor-0").geometry, tolerance=0
    )


def test_invalid_self_intersecting_input_is_reported_not_silently_used() -> None:
    bow_tie = Polygon([(0, 0), (20, 20), (20, 0), (0, 20)])
    result = validate_building(_building(1, geometry=bow_tie))

    assert result.geometry_valid is False
    assert result.acceptance_eligible is False
    assert any(finding.code == "SELF_INTERSECTION" for finding in result.findings)


def test_invalid_floor_with_design_area_is_reported_without_overlay_exception() -> None:
    bow_tie = Polygon([(0, 0), (20, 20), (20, 0), (0, 20)])

    result = validate_building(
        _building(1, geometry=bow_tie),
        design_area=box(-1, -1, 21, 21),
    )

    assert result.geometry_valid is False
    assert any(finding.code == "SELF_INTERSECTION" for finding in result.findings)
    assert not any(finding.code == "OUTSIDE_DESIGN_AREA" for finding in result.findings)


def test_unrepresentable_floor_height_fails_closed_without_overflow() -> None:
    source = _building(1)
    building = BuildingMassing(
        id=source.id,
        floors=source.floors,
        first_floor_height_m=10**500,
        standard_floor_height_m=source.standard_floor_height_m,
    )

    result = validate_building(building)

    assert result.geometry_valid is False
    assert any(finding.code == "INVALID_FLOOR_HEIGHT" for finding in result.findings)


@pytest.mark.parametrize("command_kind", ["add", "remove", "push", "move", "rotate"])
def test_non_fixture_provenance_is_rejected_and_preserved_by_edit_commands(command_kind: str) -> None:
    source = _building(2)
    non_fixture = BuildingMassing(
        id=source.id,
        floors=source.floors,
        first_floor_height_m=source.first_floor_height_m,
        standard_floor_height_m=source.standard_floor_height_m,
        provenance="SOURCE_VERIFIED",  # type: ignore[arg-type]
    )
    history = EditHistory(non_fixture)
    commands = {
        "add": AddFloorCommand(new_floor_id="floor-2"),
        "remove": RemoveFloorCommand(floor_id="floor-1"),
        "push": PushSideCommand(
            floor_edge_indices=(("floor-0", 1),),
            steps=1,
            origin_geometry_hash=non_fixture.geometry_hash(),
        ),
        "move": MoveCommand(dx_m=1, dy_m=0),
        "rotate": RotateCommand(angle_degrees=12),
    }

    revision = history.apply(
        commands[command_kind],
        expected_revision=0,
        idempotency_key=f"{command_kind}-non-fixture",
    )

    assert non_fixture.provenance == "SOURCE_VERIFIED"
    assert revision.building.provenance == "SOURCE_VERIFIED"
    assert revision.validation.provenance == "SOURCE_VERIFIED"
    assert revision.validation.geometry_valid is False
    assert revision.validation.acceptance_eligible is False
    assert any(finding.code == "INVALID_PROVENANCE" for finding in revision.validation.findings)
