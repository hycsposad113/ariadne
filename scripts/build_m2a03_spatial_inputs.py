#!/usr/bin/env python3
"""Publish one immutable Week 2 spatial input package.

The revision is required and must be unused. This command does not acquire
weather, choose a spatial policy, or retry an uncertain live dispatch.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urban_design.analysis_inputs import (
    PROJECT_ID,
    spatial_revision_is_used,
    build_m2a03_spatial_package,
    load_m2a03_spatial_package,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--study-area-id")
    parser.add_argument("--revision", required=True, help="explicit unused spatial revision")
    parser.add_argument("--no-ledger-event", action="store_true")
    return parser


def _active_study_area_id(database: Path, project_id: str) -> str:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT sv.payload_json
            FROM state_heads AS sh
            JOIN state_versions AS sv
              ON sv.entity_id = sh.entity_id AND sv.revision = sh.current_revision
            WHERE sh.entity_id = ? AND sh.entity_type = 'Project'
            """,
            (project_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise SystemExit(f"m2-a03-spatial-inputs: project {project_id} was not found")
    payload = json.loads(row["payload_json"])
    study_area_id = payload.get("active_study_area_id")
    if not isinstance(study_area_id, str) or not study_area_id.strip():
        raise SystemExit("m2-a03-spatial-inputs: project has no active StudyArea")
    return study_area_id.strip()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    revision = args.revision.strip()
    if not revision:
        print("m2-a03-spatial-inputs: revision is required", file=sys.stderr)
        return 2
    study_area_id = args.study_area_id.strip() if isinstance(args.study_area_id, str) and args.study_area_id.strip() else None
    if study_area_id is None:
        if not args.database.exists():
            print("m2-a03-spatial-inputs: database is required to resolve the active StudyArea", file=sys.stderr)
            return 2
        study_area_id = _active_study_area_id(args.database, args.project_id)
    used = spatial_revision_is_used(args.output_root, study_area_id, revision)
    if used is not None:
        print(f"m2-a03-spatial-inputs: revision {revision} is already used at {used}", file=sys.stderr)
        return 2
    try:
        package_dir = build_m2a03_spatial_package(
            args.database,
            args.output_root,
            project_id=args.project_id,
            study_area_id=study_area_id,
            package_revision=revision,
            append_ledger=not args.no_ledger_event,
        )
        package = load_m2a03_spatial_package(package_dir)
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"m2-a03-spatial-inputs: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"package_dir": str(package_dir), "status": package.get("status"), "package_id": package.get("package_id"), "weather_gate": package.get("weather_gate")}, indent=2, sort_keys=True))
    return 0 if package.get("status") == "READY_FOR_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
