"""Run the Week 7 fault matrix on sqlite backup copies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urban_design.week7.service import Week7Service, copy_authority_database

FAULTS: tuple[str, ...] = (
    "source_or_geometry_hash_mismatch",
    "observation_source_unavailable",
    "repeated_run",
    "tool_disconnect",
    "late_b1_after_b2",
    "refresh_or_restart",
    "partial_publish_db_failure",
    "ai_wrong_citation",
)

PROJECT_ID = "rotterdam-m4h-pilot-project"
WORKSPACE_ID = "ws-w7-fault"


def canonical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "fault": row["fault"],
            "expected": row["expected"],
            "actual": row["actual"],
            "recovery": row["recovery"],
        }
        for row in rows
    ]


def run_fault_matrix(database: Path, scratch: Path) -> dict[str, Any]:
    """Inject each §10 fault on one backup and return the eight rows plus radii."""

    scratch.mkdir(parents=True, exist_ok=True)
    service = Week7Service(database)
    rows: list[dict[str, Any]] = []
    try:
        for name in FAULTS:
            evidence_dir = scratch / name
            evidence_dir.mkdir(parents=True, exist_ok=True)
            row = service.run_fault(
                name,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                scratch=evidence_dir,
            )
            evidence = evidence_dir / "result.json"
            evidence.write_text(json.dumps(row, indent=2, sort_keys=True, default=str), encoding="utf-8")
            rows.append({**row, "evidence_path": str(evidence)})
        radii = service.radius_cases()
    finally:
        service.close()
    if len(rows) != 8:
        raise RuntimeError(f"fault matrix produced {len(rows)} rows")
    return {"rows": rows, "radii": radii, "canonical": canonical_rows(rows)}


def write_fault_matrix(destination: Path, authority: Path) -> dict[str, Any]:
    """Run the matrix twice on fresh backups and refuse a disagreement."""

    destination.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for index in (1, 2):
        database = destination / f"run-{index}-copy.sqlite3"
        copy_authority_database(database, authority)
        result = run_fault_matrix(database, destination / f"run-{index}")
        (destination / f"run-{index}.json").write_text(
            json.dumps(result["canonical"], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (destination / f"run-{index}-radii.json").write_text(
            json.dumps(result["radii"], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        runs.append(result)
    if runs[0]["canonical"] != runs[1]["canonical"] or runs[0]["radii"] != runs[1]["radii"]:
        raise RuntimeError("fault matrix runs disagree")
    summary = {
        "runs": 2,
        "agree": True,
        "rows": runs[0]["canonical"],
        "radii": runs[0]["radii"],
    }
    (destination / "matrix.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary
