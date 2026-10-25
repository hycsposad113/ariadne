from __future__ import annotations

from urban_design.week7.faults import canonical_rows, run_fault_matrix
from tests.week7_support import seed_project_database

pytest_plugins = ["tests.week7_support"]


def test_two_fresh_copies_agree_on_eight_faults_and_keep_radius_families(tmp_path) -> None:
    runs = []
    for index in (1, 2):
        database = seed_project_database(tmp_path / f"copy-{index}.sqlite3")
        runs.append(run_fault_matrix(database, tmp_path / f"run-{index}"))
    assert [row["fault"] for row in runs[0]["rows"]] == [
        "source_or_geometry_hash_mismatch",
        "observation_source_unavailable",
        "repeated_run",
        "tool_disconnect",
        "late_b1_after_b2",
        "refresh_or_restart",
        "partial_publish_db_failure",
        "ai_wrong_citation",
    ]
    assert canonical_rows(runs[0]["rows"]) == canonical_rows(runs[1]["rows"])
    assert runs[0]["canonical"] == runs[1]["canonical"]
    assert runs[0]["radii"] == runs[1]["radii"]
    access = [row for row in runs[1]["radii"] if row["family"] == "accessibility"]
    syntax = [row for row in runs[1]["radii"] if row["family"] == "syntax"]
    assert [row["radius_m"] for row in access] == [400.0, 800.0, 1200.0]
    assert sorted({row["radius_m"] for row in syntax}) == [800.0, 2000.0, 10000.0]
    assert {row["case_id"] for row in access}.isdisjoint({row["case_id"] for row in syntax})
    assert all(row["value"] is None and row["formal_result"] is False for row in runs[1]["radii"])
    repeated = next(row for row in runs[0]["rows"] if row["fault"] == "repeated_run")
    assert repeated["actual"]["first"] == repeated["actual"]["second"]
    assert repeated["actual"]["created_second"] is False
    assert repeated["recovery"]["same_job"] is True
    disconnected = next(row for row in runs[0]["rows"] if row["fault"] == "tool_disconnect")
    assert disconnected["actual"]["before"] == "FAILED"
    assert disconnected["actual"]["after"] == "OUTCOME_UNKNOWN"
    assert disconnected["actual"]["resent"] is False
    assert disconnected["recovery"]["resubmit_count"] == 0
    partial = next(row for row in runs[0]["rows"] if row["fault"] == "partial_publish_db_failure")
    publication = partial["actual"]["publication"]
    assert publication["status"] == "RECONCILED"
    assert publication["file_exists"] is True
    assert publication["complete_with_missing_file"] is False
    assert partial["actual"]["peer_kept"] is True
    assert partial["recovery"]["peer_kept"] is True
    restart = next(row for row in runs[0]["rows"] if row["fault"] == "refresh_or_restart")
    assert restart["recovery"]["before"] == restart["recovery"]["after"]
    mismatch = next(row for row in runs[0]["rows"] if row["fault"] == "source_or_geometry_hash_mismatch")
    assert mismatch["actual"] == "source_or_geometry_hash_mismatch"
    assert mismatch["recovery"]["before_far"] == 2.2
    assert mismatch["recovery"]["after_far"] == 2.2
    assert mismatch["recovery"]["kept"] is True
    assert mismatch["recovery"]["geometry_kept"] is True
    assert mismatch["recovery"]["head_hash_kept"] is True
    assert mismatch["recovery"]["history_kept"] is True
    late = next(row for row in runs[0]["rows"] if row["fault"] == "late_b1_after_b2")
    assert late["recovery"]["current_scenario"] == "B2"
    assert late["recovery"]["stored_on_scenario"] == "B1"
    assert late["recovery"]["current_far"] == 2.2
