from __future__ import annotations

import hashlib

from urban_design.figure_export import render_week7_figure
from urban_design.week7.figures import FIGURE_KINDS, legend_inside_canvas, png_dimensions
from urban_design.week7.service import (
    ACCESSIBILITY_RADII_M,
    SYNTAX_RADII_M,
    Week7Service,
)

pytest_plugins = ["tests.week7_support"]


def test_each_preset_png_keeps_legend_text_revision_and_hides_manipulators(tmp_path) -> None:
    schemes = [
        {"scenario_id": "B1", "value": 1.1, "extent_id": "shared-public-open-space"},
        {"scenario_id": "B2", "value": 2.2, "extent_id": "shared-public-open-space"},
    ]
    cameras = set()
    for kind in FIGURE_KINDS:
        metadata = render_week7_figure(
            kind=kind,
            output_path=tmp_path / f"{kind}.png",
            revision="rev-b2",
            unit="ratio",
            period="2026-06-21 08:00-18:00",
            schemes=schemes,
        )
        width, height = png_dimensions(tmp_path / f"{kind}.png")
        assert (width, height) == (metadata["width"], metadata["height"]) == (1240, 850)
        assert legend_inside_canvas(metadata)
        svg = (tmp_path / f"{kind}.svg").read_text(encoding="utf-8")
        assert "LEGEND" in svg
        assert "revision rev-b2" in svg
        assert "unit ratio" in svg
        assert "2026-06-21" in svg
        assert "manipulator" not in svg
        assert "gizmo" not in svg
        assert metadata["improvement_implied_by_image_edit"] is False
        assert metadata["values"] == [{"scenario_id": "B1", "value": 1.1}, {"scenario_id": "B2", "value": 2.2}]
        cameras.add(metadata["camera"]["id"])
    assert cameras == {"week7-consistent-v1"}


def test_same_extent_is_not_labelled_different(tmp_path) -> None:
    metadata = render_week7_figure(
        kind="plan",
        output_path=tmp_path / "same-extent.png",
        revision="rev-b2",
        unit="ratio",
        period="2026-06-21",
        schemes=[
            {"scenario_id": "B1", "value": 1.1, "extent_id": "shared-public-open-space"},
            {"scenario_id": "B2", "value": 2.2, "extent_id": "shared-public-open-space"},
        ],
    )
    assert metadata["extent_differs"] is False
    svg = (tmp_path / "same-extent.svg").read_text(encoding="utf-8")
    assert "EXTENT_DIFFERS" not in svg
    assert "extent shared-public-open-space" in svg


def test_extent_difference_is_written_on_the_figure(tmp_path) -> None:
    metadata = render_week7_figure(
        kind="comparison",
        output_path=tmp_path / "extent.png",
        revision="rev-b2",
        unit="m2",
        period="2026-03-21",
        schemes=[
            {"scenario_id": "B1", "value": 10, "extent_id": "extent-a"},
            {"scenario_id": "B2", "value": 12, "extent_id": "extent-b"},
        ],
    )
    assert metadata["extent_differs"] is True
    assert "EXTENT_DIFFERS" in (tmp_path / "extent.svg").read_text(encoding="utf-8")


def test_export_figure_set_writes_every_kind_with_matching_sha256(tmp_path) -> None:
    from urban_design.week7.figures import export_figure_set

    rows = export_figure_set(
        tmp_path / "figures",
        revision="rev-b2",
        unit="ratio",
        period="2026-06-21 08:00-18:00",
        schemes=[
            {"scenario_id": "B1", "value": 1.1, "extent_id": "shared-public-open-space"},
            {"scenario_id": "B2", "value": 2.2, "extent_id": "shared-public-open-space"},
        ],
    )
    assert [row["kind"] for row in rows] == list(FIGURE_KINDS)
    for row in rows:
        png = tmp_path / "figures" / f"{row['kind']}.png"
        assert png_dimensions(png) == (row["width"], row["height"]) == (1240, 850)
        assert hashlib.sha256(png.read_bytes()).hexdigest() == row["sha256"]
        assert row["manipulators_hidden"] is True
        assert row["camera"] == "week7-consistent-v1"


def test_radius_families_stay_distinct_across_restart(service: Week7Service) -> None:
    before = service.radius_cases()
    service.close()
    restored = Week7Service(service.database)
    try:
        after = restored.radius_cases()
    finally:
        restored.close()
    assert before == after
    access = [row for row in after if row["family"] == "accessibility"]
    syntax = [row for row in after if row["family"] == "syntax"]
    assert [row["radius_m"] for row in access] == list(ACCESSIBILITY_RADII_M)
    assert sorted({row["radius_m"] for row in syntax}) == sorted(SYNTAX_RADII_M)
    assert all(row["formal_result"] is False and row["value"] is None for row in after)
    assert {row["case_id"] for row in access}.isdisjoint({row["case_id"] for row in syntax})
    assert any(row["status"] == "BLOCKED_BOUNDARY_STABILITY_UNASSESSED" for row in syntax)
    assert all(row["status"] == "PROJECT_SETTING_SENSITIVITY_NOT_UNIVERSAL" for row in access)
