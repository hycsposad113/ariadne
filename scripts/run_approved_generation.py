#!/usr/bin/env python3
"""Run generation from current designer-approved database decisions."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from urban_design.approved_generation import ApprovedGenerationBlocked, run_approved_generation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read the current approved workspace and active ConstraintSet. "
            "The existing morphology operator currently supports fixture mode only."
        )
    )
    parser.add_argument("--database", required=True, type=Path, help="Source project database")
    parser.add_argument("--project-id", required=True, help="Project state identifier")
    parser.add_argument("--output-db", type=Path, help="Output database; omitted means a new SQLite backup copy")
    parser.add_argument("--artifact-root", type=Path, help="Directory for immutable geometry and comparison artifacts")
    parser.add_argument("--fixture-only", action="store_true", help="Explicitly permit the current fixture-only morphology operator")
    parser.add_argument("--write-authority", action="store_true", help="Write in place to --database after SHA-256 and backup checks")
    parser.add_argument("--expected-sha256", help="Required with --write-authority; SHA-256 of the current database file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    source = args.database.expanduser().resolve()
    output = args.output_db.expanduser().resolve() if args.output_db is not None else source.with_name(source.stem + ".approved-generation.sqlite3")
    expected = args.expected_sha256

    if args.write_authority:
        if not expected:
            parser.error("--write-authority requires --expected-sha256")
        if not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", expected):
            parser.error("--expected-sha256 must be 64 lowercase hexadecimal characters, optionally prefixed by sha256:")
        if output != source:
            parser.error("--write-authority requires --output-db to resolve to --database")
        if args.fixture_only:
            parser.error("--fixture-only cannot write the authority database")
    else:
        if expected:
            parser.error("--expected-sha256 is only valid with --write-authority")
        if output == source:
            parser.error("in-place database writes require --write-authority and --expected-sha256")

    try:
        result = run_approved_generation(
            source_database=source,
            output_database=output,
            artifact_root=args.artifact_root,
            project_id=args.project_id,
            fixture_only=args.fixture_only,
            write_authority=args.write_authority,
            expected_sha256=expected,
        )
    except ApprovedGenerationBlocked as exc:
        print("狀態：BLOCKED")
        print("缺少、過期或不支援的項目：")
        for item in exc.missing:
            print(f"- {item}")
        return 2
    except (ValueError, OSError) as exc:
        print(f"狀態：FAIL — {exc}", file=sys.stderr)
        return 2

    print(f"狀態：{result.status}")
    print(f"資料庫：{result.output_database}")
    print(f"Artifacts：{result.artifact_root}")
    print("Scenarios：")
    for scenario_id in result.scenario_ids:
        print(f"- {scenario_id}")
    print(f"比較狀態：{result.comparison.get('status')}")
    print("排名／總分：未計算")
    if result.snapshot_path is not None:
        print(f"權威 DB 前置快照：{result.snapshot_path}")
        print(f"快照 SHA-256：{result.snapshot_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
