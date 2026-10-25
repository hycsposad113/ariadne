"""R04 checks for non-overwriting, explicitly typed E2E output locations."""

from pathlib import Path

import pytest


def test_absolute_temporary_output_is_recorded_as_absolute(tmp_path):
    from urban_design.e2e_outputs import resolve_e2e_output_directory

    project_root = tmp_path / "project"
    project_root.mkdir()
    output_dir = tmp_path / "week4-e2e-run"
    resolved, descriptor = resolve_e2e_output_directory(output_dir, project_root=project_root)
    assert resolved == output_dir.resolve()
    assert descriptor == {"kind": "absolute_temporary", "path": str(output_dir.resolve())}


def test_project_relative_output_is_recorded_as_relative(tmp_path):
    from urban_design.e2e_outputs import resolve_e2e_output_directory

    project_root = tmp_path / "project"
    project_root.mkdir()
    resolved, descriptor = resolve_e2e_output_directory(
        Path("artifacts/week4-repair-r04/browser/run-test"),
        project_root=project_root,
    )
    assert resolved == project_root / "artifacts/week4-repair-r04/browser/run-test"
    assert descriptor == {
        "kind": "project_relative",
        "path": "artifacts/week4-repair-r04/browser/run-test",
    }


@pytest.mark.parametrize("existing_kind", ["empty_directory", "file"])
def test_existing_output_path_is_refused_without_overwrite(tmp_path, existing_kind):
    from urban_design.e2e_outputs import resolve_e2e_output_directory

    project_root = tmp_path / "project"
    project_root.mkdir()
    existing = project_root / "existing-output"
    if existing_kind == "empty_directory":
        existing.mkdir()
    else:
        existing.write_text("preserve", encoding="utf-8")
    original = existing.read_bytes() if existing.is_file() else None
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        resolve_e2e_output_directory(existing, project_root=project_root)
    if original is not None:
        assert existing.read_bytes() == original


def test_existing_report_file_remains_unchanged_when_path_is_rejected(tmp_path):
    from urban_design.e2e_outputs import require_new_report_path

    report = tmp_path / "report.json"
    report.write_text("historical report", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        require_new_report_path(report)
    assert report.read_text(encoding="utf-8") == "historical report"
